-- 240: Durable AgentOps checkpoint and Temporal reconciliation evidence authority.

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;

CREATE TABLE IF NOT EXISTS gda_control.agentops_temporal_checkpoint_history (
    tenant_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    checkpoint_sequence BIGINT NOT NULL,
    checkpoint_sha256 CHAR(64) NOT NULL,
    previous_checkpoint_sha256 CHAR(64),
    run_id UUID NOT NULL,
    run_status TEXT NOT NULL,
    run_state_version INTEGER NOT NULL,
    workflow_input_sha256 CHAR(64) NOT NULL,
    execution_state_sha256 CHAR(64) NOT NULL,
    checkpoint_document JSONB NOT NULL,
    recorded_by TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, workflow_id, checkpoint_sequence),
    CONSTRAINT uq_gda_agentops_temporal_checkpoint_sha
        UNIQUE (tenant_id, checkpoint_sha256),
    CONSTRAINT uq_gda_agentops_temporal_checkpoint_workflow_sha
        UNIQUE (tenant_id, workflow_id, checkpoint_sha256),
    CONSTRAINT ck_gda_agentops_temporal_checkpoint_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_agentops_temporal_checkpoint_workflow CHECK (
        workflow_id ~ '^[a-z][a-z0-9._:-]{1,254}$'
    ),
    CONSTRAINT ck_gda_agentops_temporal_checkpoint_sequence
        CHECK (checkpoint_sequence >= 1),
    CONSTRAINT ck_gda_agentops_temporal_checkpoint_hashes CHECK (
        checkpoint_sha256 ~ '^[0-9a-f]{64}$'
        AND workflow_input_sha256 ~ '^[0-9a-f]{64}$'
        AND execution_state_sha256 ~ '^[0-9a-f]{64}$'
        AND (
            previous_checkpoint_sha256 IS NULL
            OR previous_checkpoint_sha256 ~ '^[0-9a-f]{64}$'
        )
        AND previous_checkpoint_sha256 IS DISTINCT FROM checkpoint_sha256
    ),
    CONSTRAINT ck_gda_agentops_temporal_checkpoint_run CHECK (
        run_status IN (
            'accepted', 'planning', 'running', 'waiting_review',
            'reconciling', 'paused', 'succeeded', 'failed', 'cancelled'
        )
        AND run_state_version >= 0
    ),
    CONSTRAINT ck_gda_agentops_temporal_checkpoint_document CHECK (
        jsonb_typeof(checkpoint_document) = 'object'
        AND checkpoint_document <> '{}'::jsonb
    ),
    CONSTRAINT ck_gda_agentops_temporal_checkpoint_actor CHECK (
        recorded_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_agentops_temporal_checkpoint_current
    ON gda_control.agentops_temporal_checkpoint_history (
        tenant_id, workflow_id, checkpoint_sequence DESC
    );

CREATE OR REPLACE VIEW gda_control.agentops_temporal_checkpoint_current
WITH (security_invoker = true)
AS
SELECT DISTINCT ON (tenant_id, workflow_id)
       tenant_id, workflow_id, checkpoint_sequence, checkpoint_sha256,
       previous_checkpoint_sha256, run_id, run_status, run_state_version,
       workflow_input_sha256, execution_state_sha256, checkpoint_document,
       recorded_by, recorded_at
FROM gda_control.agentops_temporal_checkpoint_history
ORDER BY tenant_id, workflow_id, checkpoint_sequence DESC;

CREATE TABLE IF NOT EXISTS gda_control.agentops_temporal_reconciliation_evidence (
    tenant_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    provider_run_id TEXT NOT NULL,
    checkpoint_sha256 CHAR(64) NOT NULL,
    history_sha256 CHAR(64) NOT NULL,
    observation_sha256 CHAR(64) NOT NULL,
    reconciliation_sha256 CHAR(64) NOT NULL,
    verdict TEXT NOT NULL,
    provider_status TEXT NOT NULL,
    observation_document JSONB NOT NULL,
    reconciliation_document JSONB NOT NULL,
    recorded_by TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, reconciliation_sha256),
    CONSTRAINT uq_gda_agentops_temporal_reconciliation_identity UNIQUE (
        tenant_id, workflow_id, provider_run_id,
        checkpoint_sha256, history_sha256
    ),
    CONSTRAINT fk_gda_agentops_temporal_reconciliation_checkpoint
        FOREIGN KEY (tenant_id, workflow_id, checkpoint_sha256)
        REFERENCES gda_control.agentops_temporal_checkpoint_history (
            tenant_id, workflow_id, checkpoint_sha256
        ),
    CONSTRAINT ck_gda_agentops_temporal_reconciliation_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_agentops_temporal_reconciliation_workflow CHECK (
        workflow_id ~ '^[a-z][a-z0-9._:-]{1,254}$'
        AND NULLIF(btrim(provider_run_id), '') IS NOT NULL
        AND octet_length(provider_run_id) <= 512
    ),
    CONSTRAINT ck_gda_agentops_temporal_reconciliation_hashes CHECK (
        checkpoint_sha256 ~ '^[0-9a-f]{64}$'
        AND history_sha256 ~ '^[0-9a-f]{64}$'
        AND observation_sha256 ~ '^[0-9a-f]{64}$'
        AND reconciliation_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_agentops_temporal_reconciliation_verdict CHECK (
        verdict IN ('matched', 'checkpoint_behind', 'provider_behind')
        AND provider_status IN (
            'running', 'completed', 'failed', 'cancelled',
            'terminated', 'timed_out'
        )
    ),
    CONSTRAINT ck_gda_agentops_temporal_reconciliation_documents CHECK (
        jsonb_typeof(observation_document) = 'object'
        AND observation_document <> '{}'::jsonb
        AND jsonb_typeof(reconciliation_document) = 'object'
        AND reconciliation_document <> '{}'::jsonb
    ),
    CONSTRAINT ck_gda_agentops_temporal_reconciliation_actor CHECK (
        recorded_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_agentops_temporal_reconciliation_history
    ON gda_control.agentops_temporal_reconciliation_evidence (
        tenant_id, workflow_id, recorded_at, reconciliation_sha256
    );

CREATE OR REPLACE FUNCTION gda_control.guard_agentops_temporal_authority_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.agentops_temporal_authority_write_allowed', true),
        ''
    ) <> '1' THEN
        RAISE EXCEPTION 'use the AgentOps Temporal authority functions'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'AgentOps Temporal tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_agentops_temporal_checkpoint(
    p_tenant_id TEXT,
    p_workflow_id TEXT,
    p_previous_checkpoint_sha256 TEXT,
    p_checkpoint_document JSONB,
    p_fingerprint_payload TEXT,
    p_recorded_by TEXT
)
RETURNS TABLE(
    checkpoint_document JSONB,
    checkpoint_sequence BIGINT,
    created BOOLEAN
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, gda_control
SET row_security = on
AS $$
DECLARE
    v_checkpoint_sha256 TEXT;
    v_run_id UUID;
    v_run_status TEXT;
    v_run_state_version INTEGER;
    v_workflow_input_sha256 TEXT;
    v_execution_state_sha256 TEXT;
    v_current gda_control.agentops_temporal_checkpoint_history%ROWTYPE;
    v_existing gda_control.agentops_temporal_checkpoint_history%ROWTYPE;
    v_sequence BIGINT;
    v_expected_fingerprint JSONB;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'AgentOps Temporal tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_tenant_id !~ '^[a-z0-9][a-z0-9._-]{0,63}$'
       OR p_workflow_id !~ '^[a-z][a-z0-9._:-]{1,254}$'
       OR p_checkpoint_document IS NULL
       OR jsonb_typeof(p_checkpoint_document) <> 'object'
       OR p_fingerprint_payload IS NULL
       OR p_recorded_by IS NULL
       OR p_recorded_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR (
            p_previous_checkpoint_sha256 IS NOT NULL
            AND p_previous_checkpoint_sha256 !~ '^[0-9a-f]{64}$'
       ) THEN
        RAISE EXCEPTION 'AgentOps checkpoint identity or document is invalid'
            USING ERRCODE = '22023';
    END IF;

    BEGIN
        v_checkpoint_sha256 := p_checkpoint_document ->> 'checkpoint_sha256';
        v_run_id := (p_checkpoint_document #>> '{run,run_id}')::UUID;
        v_run_status := p_checkpoint_document #>> '{run,status}';
        v_run_state_version :=
            (p_checkpoint_document #>> '{run,state_version}')::INTEGER;
        v_workflow_input_sha256 :=
            p_checkpoint_document #>> '{workflow_input,input_sha256}';
        v_execution_state_sha256 :=
            p_checkpoint_document #>> '{execution,state_sha256}';
        v_expected_fingerprint := jsonb_build_object(
            'schema', 'gda.agentops_temporal_workflow_checkpoint.v2',
            'data', p_checkpoint_document - 'checkpoint_sha256'
        );
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'AgentOps checkpoint document fields are invalid'
            USING ERRCODE = '22023';
    END;

    IF p_checkpoint_document #>> '{workflow_input,tenant_id}'
            IS DISTINCT FROM p_tenant_id
       OR p_checkpoint_document #>> '{workflow_input,identity,workflow_id}'
            IS DISTINCT FROM p_workflow_id
       OR p_checkpoint_document #>> '{run,tenant_id}'
            IS DISTINCT FROM p_tenant_id
       OR p_checkpoint_document #>> '{execution,tenant_id}'
            IS DISTINCT FROM p_tenant_id
       OR v_checkpoint_sha256 !~ '^[0-9a-f]{64}$'
       OR v_workflow_input_sha256 !~ '^[0-9a-f]{64}$'
       OR v_execution_state_sha256 !~ '^[0-9a-f]{64}$'
       OR v_run_status NOT IN (
            'accepted', 'planning', 'running', 'waiting_review',
            'reconciling', 'paused', 'succeeded', 'failed', 'cancelled'
       )
       OR v_run_state_version < 0
       OR p_previous_checkpoint_sha256 IS NOT DISTINCT FROM v_checkpoint_sha256
       OR p_fingerprint_payload::JSONB IS DISTINCT FROM v_expected_fingerprint
       OR encode(
            public.digest(convert_to(p_fingerprint_payload, 'UTF8'), 'sha256'),
            'hex'
       ) IS DISTINCT FROM v_checkpoint_sha256 THEN
        RAISE EXCEPTION 'AgentOps checkpoint contract fingerprint is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'agentops-temporal-checkpoint|' || p_tenant_id || '|' || p_workflow_id,
        0
    ));

    SELECT history.* INTO v_existing
    FROM gda_control.agentops_temporal_checkpoint_history AS history
    WHERE history.tenant_id = p_tenant_id
      AND history.checkpoint_sha256 = v_checkpoint_sha256
    LIMIT 1;
    IF FOUND THEN
        IF v_existing.workflow_id IS DISTINCT FROM p_workflow_id
           OR v_existing.previous_checkpoint_sha256
                IS DISTINCT FROM p_previous_checkpoint_sha256
           OR v_existing.checkpoint_document
                IS DISTINCT FROM p_checkpoint_document
           OR v_existing.recorded_by IS DISTINCT FROM p_recorded_by THEN
            RAISE EXCEPTION 'AgentOps checkpoint idempotency evidence differs'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT
            v_existing.checkpoint_document,
            v_existing.checkpoint_sequence,
            FALSE;
        RETURN;
    END IF;

    SELECT history.* INTO v_current
    FROM gda_control.agentops_temporal_checkpoint_history AS history
    WHERE history.tenant_id = p_tenant_id
      AND history.workflow_id = p_workflow_id
    ORDER BY history.checkpoint_sequence DESC
    LIMIT 1
    FOR UPDATE;
    IF NOT FOUND THEN
        IF p_previous_checkpoint_sha256 IS NOT NULL THEN
            RAISE EXCEPTION 'initial AgentOps checkpoint cannot have a predecessor'
                USING ERRCODE = '40001';
        END IF;
        v_sequence := 1;
    ELSE
        IF p_previous_checkpoint_sha256
                IS DISTINCT FROM v_current.checkpoint_sha256
           OR v_run_id IS DISTINCT FROM v_current.run_id
           OR v_workflow_input_sha256
                IS DISTINCT FROM v_current.workflow_input_sha256
           OR v_run_state_version < v_current.run_state_version
           OR (
                v_run_state_version = v_current.run_state_version
                AND v_run_status IS DISTINCT FROM v_current.run_status
           ) THEN
            RAISE EXCEPTION 'AgentOps checkpoint predecessor or run identity conflict'
                USING ERRCODE = '40001';
        END IF;
        v_sequence := v_current.checkpoint_sequence + 1;
    END IF;

    PERFORM set_config(
        'gda.agentops_temporal_authority_write_allowed', '1', true
    );
    INSERT INTO gda_control.agentops_temporal_checkpoint_history (
        tenant_id, workflow_id, checkpoint_sequence, checkpoint_sha256,
        previous_checkpoint_sha256, run_id, run_status, run_state_version,
        workflow_input_sha256, execution_state_sha256, checkpoint_document,
        recorded_by
    ) VALUES (
        p_tenant_id, p_workflow_id, v_sequence, v_checkpoint_sha256,
        p_previous_checkpoint_sha256, v_run_id, v_run_status,
        v_run_state_version, v_workflow_input_sha256,
        v_execution_state_sha256, p_checkpoint_document, p_recorded_by
    ) RETURNING * INTO v_existing;
    PERFORM set_config(
        'gda.agentops_temporal_authority_write_allowed', '0', true
    );

    RETURN QUERY SELECT
        v_existing.checkpoint_document,
        v_existing.checkpoint_sequence,
        TRUE;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config(
        'gda.agentops_temporal_authority_write_allowed', '0', true
    );
    RAISE;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_agentops_temporal_reconciliation(
    p_tenant_id TEXT,
    p_workflow_id TEXT,
    p_provider_run_id TEXT,
    p_checkpoint_sha256 TEXT,
    p_observation_document JSONB,
    p_observation_fingerprint_payload TEXT,
    p_reconciliation_document JSONB,
    p_reconciliation_fingerprint_payload TEXT,
    p_recorded_by TEXT
)
RETURNS TABLE(
    observation_document JSONB,
    reconciliation_document JSONB,
    created BOOLEAN
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, gda_control
SET row_security = on
AS $$
DECLARE
    v_history_sha256 TEXT;
    v_observation_sha256 TEXT;
    v_reconciliation_sha256 TEXT;
    v_verdict TEXT;
    v_provider_status TEXT;
    v_expected_observation JSONB;
    v_expected_reconciliation JSONB;
    v_existing gda_control.agentops_temporal_reconciliation_evidence%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'AgentOps Temporal tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_tenant_id !~ '^[a-z0-9][a-z0-9._-]{0,63}$'
       OR p_workflow_id !~ '^[a-z][a-z0-9._:-]{1,254}$'
       OR NULLIF(btrim(p_provider_run_id), '') IS NULL
       OR octet_length(p_provider_run_id) > 512
       OR p_checkpoint_sha256 !~ '^[0-9a-f]{64}$'
       OR p_observation_document IS NULL
       OR jsonb_typeof(p_observation_document) <> 'object'
       OR p_reconciliation_document IS NULL
       OR jsonb_typeof(p_reconciliation_document) <> 'object'
       OR p_observation_fingerprint_payload IS NULL
       OR p_reconciliation_fingerprint_payload IS NULL
       OR p_recorded_by IS NULL
       OR p_recorded_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$' THEN
        RAISE EXCEPTION 'AgentOps reconciliation identity or document is invalid'
            USING ERRCODE = '22023';
    END IF;

    v_history_sha256 := p_observation_document ->> 'history_sha256';
    v_observation_sha256 := p_observation_document ->> 'observation_sha256';
    v_reconciliation_sha256 :=
        p_reconciliation_document ->> 'reconciliation_sha256';
    v_verdict := p_reconciliation_document ->> 'verdict';
    v_provider_status := p_observation_document ->> 'status';
    v_expected_observation := jsonb_build_object(
        'schema', 'gda.temporal_workflow_history_observation.v1',
        'data', p_observation_document - 'observation_sha256'
    );
    v_expected_reconciliation := jsonb_build_object(
        'schema', 'gda.temporal_checkpoint_reconciliation.v1',
        'data', p_reconciliation_document - 'reconciliation_sha256'
    );

    IF p_observation_document ->> 'tenant_id' IS DISTINCT FROM p_tenant_id
       OR p_observation_document ->> 'workflow_id'
            IS DISTINCT FROM p_workflow_id
       OR p_observation_document ->> 'provider_run_id'
            IS DISTINCT FROM p_provider_run_id
       OR p_reconciliation_document ->> 'tenant_id'
            IS DISTINCT FROM p_tenant_id
       OR p_reconciliation_document ->> 'workflow_id'
            IS DISTINCT FROM p_workflow_id
       OR p_reconciliation_document ->> 'provider_run_id'
            IS DISTINCT FROM p_provider_run_id
       OR p_reconciliation_document ->> 'checkpoint_sha256'
            IS DISTINCT FROM p_checkpoint_sha256
       OR p_reconciliation_document ->> 'history_sha256'
            IS DISTINCT FROM v_history_sha256
       OR p_reconciliation_document ->> 'provider_workflow_status'
            IS DISTINCT FROM v_provider_status
       OR v_history_sha256 !~ '^[0-9a-f]{64}$'
       OR v_observation_sha256 !~ '^[0-9a-f]{64}$'
       OR v_reconciliation_sha256 !~ '^[0-9a-f]{64}$'
       OR v_verdict NOT IN ('matched', 'checkpoint_behind', 'provider_behind')
       OR v_provider_status NOT IN (
            'running', 'completed', 'failed', 'cancelled',
            'terminated', 'timed_out'
       )
       OR p_observation_fingerprint_payload::JSONB
            IS DISTINCT FROM v_expected_observation
       OR p_reconciliation_fingerprint_payload::JSONB
            IS DISTINCT FROM v_expected_reconciliation
       OR encode(public.digest(
            convert_to(p_observation_fingerprint_payload, 'UTF8'), 'sha256'
       ), 'hex') IS DISTINCT FROM v_observation_sha256
       OR encode(public.digest(
            convert_to(p_reconciliation_fingerprint_payload, 'UTF8'), 'sha256'
       ), 'hex') IS DISTINCT FROM v_reconciliation_sha256 THEN
        RAISE EXCEPTION 'AgentOps reconciliation contract fingerprint is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'agentops-temporal-reconciliation|' || p_tenant_id || '|' ||
        p_workflow_id || '|' || p_provider_run_id || '|' ||
        p_checkpoint_sha256 || '|' || v_history_sha256,
        0
    ));

    SELECT evidence.* INTO v_existing
    FROM gda_control.agentops_temporal_reconciliation_evidence AS evidence
    WHERE evidence.tenant_id = p_tenant_id
      AND (
          evidence.reconciliation_sha256 = v_reconciliation_sha256
          OR (
              evidence.workflow_id = p_workflow_id
              AND evidence.provider_run_id = p_provider_run_id
              AND evidence.checkpoint_sha256 = p_checkpoint_sha256
              AND evidence.history_sha256 = v_history_sha256
          )
      )
    ORDER BY (
        evidence.reconciliation_sha256 = v_reconciliation_sha256
    ) DESC
    LIMIT 1;
    IF FOUND THEN
        IF v_existing.workflow_id IS DISTINCT FROM p_workflow_id
           OR v_existing.provider_run_id IS DISTINCT FROM p_provider_run_id
           OR v_existing.checkpoint_sha256 IS DISTINCT FROM p_checkpoint_sha256
           OR v_existing.history_sha256 IS DISTINCT FROM v_history_sha256
           OR v_existing.observation_document
                IS DISTINCT FROM p_observation_document
           OR v_existing.reconciliation_document
                IS DISTINCT FROM p_reconciliation_document
           OR v_existing.recorded_by IS DISTINCT FROM p_recorded_by THEN
            RAISE EXCEPTION 'AgentOps reconciliation idempotency evidence differs'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT
            v_existing.observation_document,
            v_existing.reconciliation_document,
            FALSE;
        RETURN;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM gda_control.agentops_temporal_checkpoint_history AS checkpoint
        WHERE checkpoint.tenant_id = p_tenant_id
          AND checkpoint.workflow_id = p_workflow_id
          AND checkpoint.checkpoint_sha256 = p_checkpoint_sha256
    ) THEN
        RAISE EXCEPTION 'AgentOps reconciliation checkpoint is unknown'
            USING ERRCODE = '40001';
    END IF;

    PERFORM set_config(
        'gda.agentops_temporal_authority_write_allowed', '1', true
    );
    INSERT INTO gda_control.agentops_temporal_reconciliation_evidence (
        tenant_id, workflow_id, provider_run_id, checkpoint_sha256,
        history_sha256, observation_sha256, reconciliation_sha256,
        verdict, provider_status, observation_document,
        reconciliation_document, recorded_by
    ) VALUES (
        p_tenant_id, p_workflow_id, p_provider_run_id, p_checkpoint_sha256,
        v_history_sha256, v_observation_sha256, v_reconciliation_sha256,
        v_verdict, v_provider_status, p_observation_document,
        p_reconciliation_document, p_recorded_by
    ) RETURNING * INTO v_existing;
    PERFORM set_config(
        'gda.agentops_temporal_authority_write_allowed', '0', true
    );

    RETURN QUERY SELECT
        v_existing.observation_document,
        v_existing.reconciliation_document,
        TRUE;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config(
        'gda.agentops_temporal_authority_write_allowed', '0', true
    );
    RAISE;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_agentops_temporal_checkpoint_insert_guard
    ON gda_control.agentops_temporal_checkpoint_history;
CREATE TRIGGER trg_gda_agentops_temporal_checkpoint_insert_guard
BEFORE INSERT ON gda_control.agentops_temporal_checkpoint_history
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_agentops_temporal_authority_insert();

DROP TRIGGER IF EXISTS trg_gda_agentops_temporal_checkpoint_immutable
    ON gda_control.agentops_temporal_checkpoint_history;
CREATE TRIGGER trg_gda_agentops_temporal_checkpoint_immutable
BEFORE UPDATE OR DELETE ON gda_control.agentops_temporal_checkpoint_history
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_agentops_temporal_reconciliation_insert_guard
    ON gda_control.agentops_temporal_reconciliation_evidence;
CREATE TRIGGER trg_gda_agentops_temporal_reconciliation_insert_guard
BEFORE INSERT ON gda_control.agentops_temporal_reconciliation_evidence
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_agentops_temporal_authority_insert();

DROP TRIGGER IF EXISTS trg_gda_agentops_temporal_reconciliation_immutable
    ON gda_control.agentops_temporal_reconciliation_evidence;
CREATE TRIGGER trg_gda_agentops_temporal_reconciliation_immutable
BEFORE UPDATE OR DELETE ON gda_control.agentops_temporal_reconciliation_evidence
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.agentops_temporal_checkpoint_history
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.agentops_temporal_checkpoint_history
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.agentops_temporal_checkpoint_history;
CREATE POLICY tenant_isolation
    ON gda_control.agentops_temporal_checkpoint_history
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.agentops_temporal_reconciliation_evidence
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.agentops_temporal_reconciliation_evidence
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.agentops_temporal_reconciliation_evidence;
CREATE POLICY tenant_isolation
    ON gda_control.agentops_temporal_reconciliation_evidence
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.agentops_temporal_checkpoint_history
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.agentops_temporal_checkpoint_current
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.agentops_temporal_reconciliation_evidence
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.agentops_temporal_checkpoint_history
    TO gda_control_gateway;
GRANT SELECT ON TABLE gda_control.agentops_temporal_checkpoint_current
    TO gda_control_gateway;
GRANT SELECT ON TABLE gda_control.agentops_temporal_reconciliation_evidence
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.guard_agentops_temporal_authority_insert()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_agentops_temporal_checkpoint(
    TEXT, TEXT, TEXT, JSONB, TEXT, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_agentops_temporal_reconciliation(
    TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, JSONB, TEXT, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.record_agentops_temporal_checkpoint(
    TEXT, TEXT, TEXT, JSONB, TEXT, TEXT
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_agentops_temporal_reconciliation(
    TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, JSONB, TEXT, TEXT
) TO gda_control_gateway;
