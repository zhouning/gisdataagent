-- 147: Durable, append-only PostgreSQL CDC recovery-controller observations.
--
-- Artifact remains the immutable evidence projection.  This table is the
-- queryable control-plane authority for checkpoint-bound slot observations and
-- decisions; the SECURITY DEFINER function requires the matching Artifact to
-- exist before it can append a row.

CREATE OR REPLACE FUNCTION
gda_control.postgresql_cdc_recovery_reason_codes_valid(p_reason_codes TEXT[])
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT p_reason_codes = ARRAY(
               SELECT DISTINCT value
               FROM unnest(p_reason_codes) AS value
               ORDER BY value
           )
       AND NOT EXISTS (
           SELECT 1
           FROM unnest(p_reason_codes) AS value
           WHERE value !~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$'
       );
$$;

CREATE TABLE IF NOT EXISTS gda_control.postgresql_cdc_recovery_observation (
    tenant_id TEXT NOT NULL,
    artifact_id UUID PRIMARY KEY,
    sync_definition_version_id UUID NOT NULL,
    run_id UUID NOT NULL,
    sync_definition_urn TEXT NOT NULL,
    checkpoint_state_version INTEGER NOT NULL,
    checkpoint_cursor JSONB NOT NULL,
    observation_sha256 CHAR(64) NOT NULL,
    decision_sha256 CHAR(64) NOT NULL,
    disposition TEXT NOT NULL,
    reason_codes TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    recovery_plan_sha256 CHAR(64) NOT NULL,
    observation JSONB NOT NULL,
    decision JSONB NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL,
    recorded_by TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gda_postgresql_cdc_recovery_observation_tenant_sha
        UNIQUE (tenant_id, observation_sha256),
    CONSTRAINT fk_gda_postgresql_cdc_recovery_observation_artifact
        FOREIGN KEY (artifact_id)
        REFERENCES gda_control.artifact(artifact_id),
    CONSTRAINT fk_gda_postgresql_cdc_recovery_observation_definition
        FOREIGN KEY (tenant_id, sync_definition_version_id)
        REFERENCES gda_control.source_sync_definition(
            tenant_id, sync_definition_version_id
        ),
    CONSTRAINT fk_gda_postgresql_cdc_recovery_observation_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.platform_run(tenant_id, run_id),
    CONSTRAINT ck_gda_postgresql_cdc_recovery_observation_tenant
        CHECK (
            sync_definition_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/sync_definition/[a-z0-9][a-z0-9._-]{0,127}$'
            AND split_part(sync_definition_urn, '/', 3) = tenant_id
        ),
    CONSTRAINT ck_gda_postgresql_cdc_recovery_observation_version
        CHECK (checkpoint_state_version >= 0),
    CONSTRAINT ck_gda_postgresql_cdc_recovery_observation_cursor
        CHECK (jsonb_typeof(checkpoint_cursor) = 'object'),
    CONSTRAINT ck_gda_postgresql_cdc_recovery_observation_sha
        CHECK (observation_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_postgresql_cdc_recovery_decision_sha
        CHECK (decision_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_postgresql_cdc_recovery_plan_sha
        CHECK (recovery_plan_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_postgresql_cdc_recovery_disposition
        CHECK (disposition IN ('resume_cdc', 'schedule_resnapshot', 'rejected_fail_closed')),
    CONSTRAINT ck_gda_postgresql_cdc_recovery_reason_codes
        CHECK (gda_control.postgresql_cdc_recovery_reason_codes_valid(reason_codes)),
    CONSTRAINT ck_gda_postgresql_cdc_recovery_documents
        CHECK (
            jsonb_typeof(observation) = 'object'
            AND jsonb_typeof(decision) = 'object'
            AND observation->>'observation_sha256' = observation_sha256
            AND decision->>'decision_sha256' = decision_sha256
            AND decision->>'disposition' = disposition
            AND observation->>'sync_definition_version_id' = sync_definition_version_id::TEXT
            AND decision->>'sync_definition_version_id' = sync_definition_version_id::TEXT
            AND decision->>'observation_sha256' = observation_sha256
            AND observation->'checkpoint_cursor' = checkpoint_cursor
        ),
    CONSTRAINT ck_gda_postgresql_cdc_recovery_actor
        CHECK (recorded_by ~ '^workload:[^[:space:]]+$'),
    CONSTRAINT ck_gda_postgresql_cdc_recovery_timestamps
        CHECK (decided_at >= observed_at)
);

CREATE INDEX IF NOT EXISTS idx_gda_postgresql_cdc_recovery_definition
    ON gda_control.postgresql_cdc_recovery_observation(
        tenant_id, sync_definition_version_id, recorded_at DESC
    );
CREATE INDEX IF NOT EXISTS idx_gda_postgresql_cdc_recovery_run
    ON gda_control.postgresql_cdc_recovery_observation(tenant_id, run_id);
CREATE INDEX IF NOT EXISTS idx_gda_postgresql_cdc_recovery_disposition
    ON gda_control.postgresql_cdc_recovery_observation(
        tenant_id, disposition, recorded_at DESC
    );

CREATE OR REPLACE FUNCTION gda_control.guard_postgresql_cdc_recovery_observation_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.postgresql_cdc_recovery_observation_allowed', true),
        ''
    ) <> '1' THEN
        RAISE EXCEPTION
            'use gda_control.record_postgresql_cdc_recovery_observation()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION
            'postgresql CDC recovery observation tenant is mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_postgresql_cdc_recovery_observation(
    p_tenant_id TEXT,
    p_artifact_id UUID,
    p_recovery_plan_sha256 TEXT,
    p_observation JSONB,
    p_decision JSONB
)
RETURNS TABLE(result_artifact_id UUID, result_created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_artifact gda_control.artifact%ROWTYPE;
    v_definition gda_control.source_sync_definition%ROWTYPE;
    v_run gda_control.platform_run%ROWTYPE;
    v_existing gda_control.postgresql_cdc_recovery_observation%ROWTYPE;
    v_tenant_id TEXT;
    v_sync_definition_urn TEXT;
    v_sync_definition_version_id UUID;
    v_run_id UUID;
    v_checkpoint_state_version INTEGER;
    v_checkpoint_cursor JSONB;
    v_observation_sha256 TEXT;
    v_decision_sha256 TEXT;
    v_disposition TEXT;
    v_reason_codes TEXT[];
    v_observed_at TIMESTAMPTZ;
    v_decided_at TIMESTAMPTZ;
    v_recorded_by TEXT;
    v_inserted_artifact_id UUID;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'postgresql CDC recovery observation tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_observation IS NULL
       OR jsonb_typeof(p_observation) <> 'object'
       OR p_decision IS NULL
       OR jsonb_typeof(p_decision) <> 'object'
       OR p_recovery_plan_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'postgresql CDC recovery observation evidence is incomplete'
            USING ERRCODE = '22023';
    END IF;

    BEGIN
        v_tenant_id := p_observation->>'tenant_id';
        v_sync_definition_urn := p_observation->>'sync_definition_urn';
        v_sync_definition_version_id :=
            (p_observation->>'sync_definition_version_id')::UUID;
        v_checkpoint_state_version :=
            (p_observation->>'checkpoint_state_version')::INTEGER;
        v_checkpoint_cursor := p_observation->'checkpoint_cursor';
        v_observation_sha256 := p_observation->>'observation_sha256';
        v_decision_sha256 := p_decision->>'decision_sha256';
        v_disposition := p_decision->>'disposition';
        v_observed_at := (p_observation->>'observed_at')::TIMESTAMPTZ;
        v_decided_at := (p_decision->>'decided_at')::TIMESTAMPTZ;
        v_recorded_by := p_decision->>'decided_by';
        IF jsonb_typeof(p_decision->'reason_codes') <> 'array' THEN
            RAISE EXCEPTION 'reason_codes must be an array';
        END IF;
        SELECT COALESCE(array_agg(value ORDER BY value), ARRAY[]::TEXT[])
        INTO v_reason_codes
        FROM jsonb_array_elements_text(p_decision->'reason_codes') AS item(value);
    EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
        RAISE EXCEPTION 'postgresql CDC recovery observation values are invalid'
            USING ERRCODE = '22023';
    END;

    IF v_tenant_id IS DISTINCT FROM p_tenant_id
       OR v_sync_definition_urn IS NULL
       OR v_sync_definition_version_id IS NULL
       OR v_checkpoint_state_version IS NULL
       OR v_checkpoint_cursor IS NULL
       OR jsonb_typeof(v_checkpoint_cursor) <> 'object'
       OR v_observation_sha256 !~ '^[0-9a-f]{64}$'
       OR v_decision_sha256 !~ '^[0-9a-f]{64}$'
       OR v_disposition NOT IN ('resume_cdc', 'schedule_resnapshot', 'rejected_fail_closed')
       OR v_observed_at IS NULL
       OR v_decided_at IS NULL
       OR v_decided_at < v_observed_at
       OR v_recorded_by !~ '^workload:[^[:space:]]+$'
       OR p_decision->>'tenant_id' IS DISTINCT FROM p_tenant_id
       OR p_decision->>'observation_sha256' IS DISTINCT FROM v_observation_sha256
       OR p_decision->>'sync_definition_version_id'
          IS DISTINCT FROM v_sync_definition_version_id::TEXT
       OR p_observation->>'schema'
          IS DISTINCT FROM 'gda.postgresql_cdc_slot_continuity_observation.v1'
       OR p_decision->>'schema'
          IS DISTINCT FROM 'gda.postgresql_cdc_recovery_controller_decision.v1' THEN
        RAISE EXCEPTION 'postgresql CDC recovery observation identity is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_artifact
    FROM gda_control.artifact AS artifact
    WHERE artifact.tenant_id = p_tenant_id
      AND artifact.artifact_id = p_artifact_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'recovery controller Artifact was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_artifact.artifact_role <> 'evidence'
       OR v_artifact.manifest->>'schema'
          IS DISTINCT FROM 'gda.postgresql_cdc_recovery_controller_evidence.v1'
       OR v_artifact.manifest->'observation' IS DISTINCT FROM p_observation
       OR v_artifact.manifest->'decision' IS DISTINCT FROM p_decision
       OR v_artifact.manifest->>'recovery_plan_sha256'
          IS DISTINCT FROM p_recovery_plan_sha256 THEN
        RAISE EXCEPTION 'recovery controller Artifact does not match ledger evidence'
            USING ERRCODE = '23514';
    END IF;

    v_run_id := v_artifact.run_id;
    IF v_run_id IS NULL
       OR v_artifact.resource_version_id IS DISTINCT FROM v_sync_definition_version_id THEN
        RAISE EXCEPTION 'recovery controller Artifact is not bound to the observation'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_definition
    FROM gda_control.source_sync_definition AS definition
    WHERE definition.tenant_id = p_tenant_id
      AND definition.sync_definition_version_id = v_sync_definition_version_id;
    IF NOT FOUND
       OR v_definition.sync_definition_urn IS DISTINCT FROM v_sync_definition_urn THEN
        RAISE EXCEPTION 'recovery controller observation definition binding is invalid'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_run
    FROM gda_control.platform_run AS run
    WHERE run.tenant_id = p_tenant_id
      AND run.run_id = v_run_id;
    IF NOT FOUND
       OR v_run.definition_version_id <> v_definition.platform_definition_version_id
       OR v_run.orchestration_class <> 'dataops' THEN
        RAISE EXCEPTION 'recovery controller observation Run binding is invalid'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_existing
    FROM gda_control.postgresql_cdc_recovery_observation AS observation
    WHERE observation.tenant_id = p_tenant_id
      AND observation.artifact_id = p_artifact_id;
    IF FOUND THEN
        IF v_existing.observation_sha256 IS DISTINCT FROM v_observation_sha256
           OR v_existing.decision_sha256 IS DISTINCT FROM v_decision_sha256
           OR v_existing.recovery_plan_sha256 IS DISTINCT FROM p_recovery_plan_sha256
           OR v_existing.observation IS DISTINCT FROM p_observation
           OR v_existing.decision IS DISTINCT FROM p_decision THEN
            RAISE EXCEPTION 'recovery controller observation identity has different evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT p_artifact_id, FALSE;
        RETURN;
    END IF;

    SELECT * INTO v_existing
    FROM gda_control.postgresql_cdc_recovery_observation AS observation
    WHERE observation.tenant_id = p_tenant_id
      AND observation.observation_sha256 = v_observation_sha256;
    IF FOUND THEN
        RAISE EXCEPTION 'recovery controller observation has a different Artifact identity'
            USING ERRCODE = '40001';
    END IF;

    PERFORM set_config(
        'gda.postgresql_cdc_recovery_observation_allowed', '1', true
    );
    INSERT INTO gda_control.postgresql_cdc_recovery_observation (
        tenant_id, artifact_id, sync_definition_version_id, run_id,
        sync_definition_urn, checkpoint_state_version, checkpoint_cursor,
        observation_sha256, decision_sha256, disposition, reason_codes,
        recovery_plan_sha256, observation, decision, observed_at, decided_at,
        recorded_by
    ) VALUES (
        p_tenant_id, p_artifact_id, v_sync_definition_version_id, v_run_id,
        v_sync_definition_urn, v_checkpoint_state_version, v_checkpoint_cursor,
        v_observation_sha256, v_decision_sha256, v_disposition, v_reason_codes,
        p_recovery_plan_sha256, p_observation, p_decision, v_observed_at,
        v_decided_at, v_recorded_by
    ) ON CONFLICT DO NOTHING
    RETURNING artifact_id INTO v_inserted_artifact_id;
    PERFORM set_config(
        'gda.postgresql_cdc_recovery_observation_allowed', '0', true
    );

    SELECT * INTO v_existing
    FROM gda_control.postgresql_cdc_recovery_observation AS observation
    WHERE observation.tenant_id = p_tenant_id
      AND observation.artifact_id = p_artifact_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'recovery controller observation was not recorded'
            USING ERRCODE = '40001';
    END IF;
    RETURN QUERY SELECT p_artifact_id, v_inserted_artifact_id IS NOT NULL;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config(
        'gda.postgresql_cdc_recovery_observation_allowed', '0', true
    );
    RAISE;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_postgresql_cdc_recovery_observation_insert_guard
    ON gda_control.postgresql_cdc_recovery_observation;
CREATE TRIGGER trg_gda_postgresql_cdc_recovery_observation_insert_guard
BEFORE INSERT ON gda_control.postgresql_cdc_recovery_observation
FOR EACH ROW EXECUTE FUNCTION
    gda_control.guard_postgresql_cdc_recovery_observation_insert();

DROP TRIGGER IF EXISTS trg_gda_postgresql_cdc_recovery_observation_immutable
    ON gda_control.postgresql_cdc_recovery_observation;
CREATE TRIGGER trg_gda_postgresql_cdc_recovery_observation_immutable
BEFORE UPDATE OR DELETE ON gda_control.postgresql_cdc_recovery_observation
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.postgresql_cdc_recovery_observation ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.postgresql_cdc_recovery_observation FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.postgresql_cdc_recovery_observation;
CREATE POLICY tenant_isolation
    ON gda_control.postgresql_cdc_recovery_observation
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.postgresql_cdc_recovery_observation
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.postgresql_cdc_recovery_observation
    TO gda_control_gateway;
REVOKE ALL ON FUNCTION
    gda_control.guard_postgresql_cdc_recovery_observation_insert()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_postgresql_cdc_recovery_observation(
    TEXT, UUID, TEXT, JSONB, JSONB
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.record_postgresql_cdc_recovery_observation(
    TEXT, UUID, TEXT, JSONB, JSONB
) TO gda_control_gateway;
