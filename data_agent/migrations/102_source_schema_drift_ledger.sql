-- 102: Persist governed source schema drift and its controlled lifecycle.
--
-- The immutable drift evidence is stored once. Only status/state_version may
-- change, through a CAS transition function that appends lifecycle evidence.
-- Approval remains external: breaking drift decisions must carry an
-- ApprovalCase ResourceURN, but this migration does not create an approval
-- authority or a second approval state machine.

CREATE TABLE IF NOT EXISTS gda_control.source_schema_drift (
    tenant_id TEXT NOT NULL,
    drift_event_id CHAR(64) NOT NULL,
    source_id TEXT NOT NULL,
    source_definition_fingerprint CHAR(64) NOT NULL,
    previous_discovery_fingerprint CHAR(64) NOT NULL,
    current_discovery_fingerprint CHAR(64) NOT NULL,
    breaking BOOLEAN NOT NULL,
    event_payload JSONB NOT NULL,
    detected_by TEXT NOT NULL,
    status TEXT NOT NULL,
    state_version INTEGER NOT NULL DEFAULT 0,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, drift_event_id),
    CONSTRAINT ck_gda_source_drift_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_source_drift_event_id
        CHECK (drift_event_id ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_source_drift_source_id
        CHECK (source_id ~ '^[a-z][a-z0-9._-]{2,127}$'),
    CONSTRAINT ck_gda_source_drift_definition_sha
        CHECK (source_definition_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_source_drift_previous_sha
        CHECK (previous_discovery_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_source_drift_current_sha
        CHECK (current_discovery_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_source_drift_changed
        CHECK (previous_discovery_fingerprint <> current_discovery_fingerprint),
    CONSTRAINT ck_gda_source_drift_payload
        CHECK (
            jsonb_typeof(event_payload) = 'object'
            AND jsonb_typeof(event_payload->'source_id') = 'string'
            AND jsonb_typeof(
                event_payload->'previous_discovery_fingerprint'
            ) = 'string'
            AND jsonb_typeof(
                event_payload->'current_discovery_fingerprint'
            ) = 'string'
            AND jsonb_typeof(event_payload->'breaking') = 'boolean'
            AND jsonb_typeof(event_payload->'added_resources') = 'array'
            AND jsonb_typeof(event_payload->'removed_resources') = 'array'
            AND jsonb_typeof(event_payload->'changed_resources') = 'array'
            AND jsonb_typeof(event_payload->'field_changes') = 'array'
        ),
    CONSTRAINT ck_gda_source_drift_payload_identity CHECK (
        event_payload->>'source_id' = source_id
        AND event_payload->>'previous_discovery_fingerprint'
            = previous_discovery_fingerprint
        AND event_payload->>'current_discovery_fingerprint'
            = current_discovery_fingerprint
        AND (event_payload->>'breaking')::boolean = breaking
    ),
    CONSTRAINT ck_gda_source_drift_detector
        CHECK (NULLIF(btrim(detected_by), '') IS NOT NULL),
    CONSTRAINT ck_gda_source_drift_status CHECK (
        status IN (
            'observed','approval_required','approved','rejected','reconciled'
        )
    ),
    CONSTRAINT ck_gda_source_drift_state_version CHECK (state_version >= 0),
    CONSTRAINT ck_gda_source_drift_initial_state CHECK (
        (state_version = 0 AND (
            (breaking AND status = 'approval_required')
            OR (NOT breaking AND status = 'observed')
        ))
        OR state_version > 0
    ),
    CONSTRAINT ck_gda_source_drift_time CHECK (updated_at >= detected_at)
);

CREATE INDEX IF NOT EXISTS idx_gda_source_drift_attention
    ON gda_control.source_schema_drift(
        tenant_id, status, breaking, detected_at DESC
    );
CREATE INDEX IF NOT EXISTS idx_gda_source_drift_source
    ON gda_control.source_schema_drift(tenant_id, source_id, detected_at DESC);

CREATE TABLE IF NOT EXISTS gda_control.source_schema_drift_lifecycle_event (
    tenant_id TEXT NOT NULL,
    lifecycle_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    drift_event_id CHAR(64) NOT NULL,
    sequence_no INTEGER NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL,
    approval_case_ref TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_gda_source_drift_lifecycle_tenant_id
        UNIQUE (tenant_id, lifecycle_event_id),
    CONSTRAINT uq_gda_source_drift_lifecycle_sequence
        UNIQUE (tenant_id, drift_event_id, sequence_no),
    CONSTRAINT fk_gda_source_drift_lifecycle_drift
        FOREIGN KEY (tenant_id, drift_event_id)
        REFERENCES gda_control.source_schema_drift(tenant_id, drift_event_id),
    CONSTRAINT ck_gda_source_drift_lifecycle_sequence CHECK (sequence_no >= 0),
    CONSTRAINT ck_gda_source_drift_lifecycle_from_status CHECK (
        from_status IS NULL OR from_status IN (
            'observed','approval_required','approved','rejected','reconciled'
        )
    ),
    CONSTRAINT ck_gda_source_drift_lifecycle_to_status CHECK (
        to_status IN (
            'observed','approval_required','approved','rejected','reconciled'
        )
    ),
    CONSTRAINT ck_gda_source_drift_lifecycle_initial CHECK (
        (sequence_no = 0 AND from_status IS NULL
            AND to_status IN ('observed','approval_required'))
        OR (sequence_no > 0 AND from_status IS NOT NULL)
    ),
    CONSTRAINT ck_gda_source_drift_lifecycle_actor
        CHECK (NULLIF(btrim(actor_subject), '') IS NOT NULL),
    CONSTRAINT ck_gda_source_drift_lifecycle_reason
        CHECK (NULLIF(btrim(reason), '') IS NOT NULL),
    CONSTRAINT ck_gda_source_drift_lifecycle_approval_ref CHECK (
        approval_case_ref IS NULL OR (
            approval_case_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/[a-z0-9][a-z0-9._-]{0,127}$'
            AND split_part(approval_case_ref, '/', 3) = tenant_id
        )
    ),
    CONSTRAINT ck_gda_source_drift_lifecycle_decision_ref CHECK (
        (to_status IN ('approved','rejected') AND approval_case_ref IS NOT NULL)
        OR (to_status NOT IN ('approved','rejected') AND approval_case_ref IS NULL)
    ),
    CONSTRAINT ck_gda_source_drift_lifecycle_details
        CHECK (jsonb_typeof(details) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_gda_source_drift_lifecycle_event
    ON gda_control.source_schema_drift_lifecycle_event(
        tenant_id, drift_event_id, sequence_no
    );

CREATE OR REPLACE FUNCTION gda_control.guard_source_schema_drift_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'source schema drift tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF NEW.state_version <> 0
       OR NEW.status IS DISTINCT FROM (CASE
            WHEN NEW.breaking THEN 'approval_required'
            ELSE 'observed'
          END) THEN
        RAISE EXCEPTION 'source schema drift has an invalid initial state'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.initialize_source_schema_drift_event()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'source schema drift tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    INSERT INTO gda_control.source_schema_drift_lifecycle_event (
        tenant_id, drift_event_id, sequence_no, from_status, to_status,
        actor_subject, reason, details, occurred_at
    ) VALUES (
        NEW.tenant_id, NEW.drift_event_id, 0, NULL, NEW.status,
        NEW.detected_by, 'schema drift detected',
        jsonb_build_object(
            'breaking', NEW.breaking,
            'source_id', NEW.source_id,
            'source_definition_fingerprint', NEW.source_definition_fingerprint
        ),
        NEW.detected_at
    );
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.guard_source_schema_drift_update()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(current_setting('gda.schema_drift_transition_allowed', true), '') <> '1' THEN
        RAISE EXCEPTION 'use gda_control.transition_source_schema_drift()'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.drift_event_id IS DISTINCT FROM OLD.drift_event_id
       OR NEW.source_id IS DISTINCT FROM OLD.source_id
       OR NEW.source_definition_fingerprint IS DISTINCT FROM OLD.source_definition_fingerprint
       OR NEW.previous_discovery_fingerprint IS DISTINCT FROM OLD.previous_discovery_fingerprint
       OR NEW.current_discovery_fingerprint IS DISTINCT FROM OLD.current_discovery_fingerprint
       OR NEW.breaking IS DISTINCT FROM OLD.breaking
       OR NEW.event_payload IS DISTINCT FROM OLD.event_payload
       OR NEW.detected_by IS DISTINCT FROM OLD.detected_by
       OR NEW.detected_at IS DISTINCT FROM OLD.detected_at THEN
        RAISE EXCEPTION 'immutable source schema drift evidence cannot be changed'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.state_version <> OLD.state_version + 1 OR NEW.status = OLD.status THEN
        RAISE EXCEPTION 'schema drift transition must advance state_version once'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.transition_source_schema_drift(
    p_tenant_id TEXT,
    p_drift_event_id TEXT,
    p_expected_state_version INTEGER,
    p_to_status TEXT,
    p_actor_subject TEXT,
    p_reason TEXT,
    p_approval_case_ref TEXT DEFAULT NULL,
    p_details JSONB DEFAULT '{}'::jsonb
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_drift gda_control.source_schema_drift%ROWTYPE;
    v_allowed BOOLEAN := FALSE;
    v_new_version INTEGER;
    v_occurred_at TIMESTAMPTZ;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'source schema drift tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_drift_event_id IS NULL
       OR p_drift_event_id !~ '^[0-9a-f]{64}$'
       OR NULLIF(btrim(p_actor_subject), '') IS NULL
       OR NULLIF(btrim(p_reason), '') IS NULL THEN
        RAISE EXCEPTION 'drift identity, transition actor and reason are required'
            USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(p_details) <> 'object' THEN
        RAISE EXCEPTION 'schema drift transition details must be a JSON object'
            USING ERRCODE = '22023';
    END IF;
    IF p_to_status IN ('approved','rejected') THEN
        IF p_approval_case_ref IS NULL
           OR p_approval_case_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/[a-z0-9][a-z0-9._-]{0,127}$'
           OR split_part(p_approval_case_ref, '/', 3) <> p_tenant_id THEN
            RAISE EXCEPTION 'approved or rejected drift requires a tenant ApprovalCase reference'
                USING ERRCODE = '23514';
        END IF;
    ELSIF p_approval_case_ref IS NOT NULL THEN
        RAISE EXCEPTION 'ApprovalCase reference is only valid for a decision transition'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_drift
    FROM gda_control.source_schema_drift
    WHERE tenant_id = p_tenant_id AND drift_event_id = p_drift_event_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'source schema drift % not found', p_drift_event_id
            USING ERRCODE = 'P0002';
    END IF;
    IF v_drift.state_version <> p_expected_state_version THEN
        RAISE EXCEPTION 'schema drift state version conflict: expected %, actual %',
            p_expected_state_version, v_drift.state_version
            USING ERRCODE = '40001';
    END IF;

    v_allowed := CASE v_drift.status
        WHEN 'observed' THEN p_to_status = 'reconciled'
        WHEN 'approval_required' THEN p_to_status IN ('approved','rejected')
        WHEN 'approved' THEN p_to_status = 'reconciled'
        ELSE FALSE
    END;
    IF NOT v_allowed THEN
        RAISE EXCEPTION 'invalid schema drift transition % -> %',
            v_drift.status, p_to_status
            USING ERRCODE = '23514';
    END IF;

    v_new_version := v_drift.state_version + 1;
    v_occurred_at := clock_timestamp();
    PERFORM set_config('gda.schema_drift_transition_allowed', '1', true);
    UPDATE gda_control.source_schema_drift
    SET status = p_to_status,
        state_version = v_new_version,
        updated_at = v_occurred_at
    WHERE tenant_id = p_tenant_id AND drift_event_id = p_drift_event_id;
    PERFORM set_config('gda.schema_drift_transition_allowed', '0', true);

    INSERT INTO gda_control.source_schema_drift_lifecycle_event (
        tenant_id, drift_event_id, sequence_no, from_status, to_status,
        actor_subject, reason, approval_case_ref, details, occurred_at
    ) VALUES (
        v_drift.tenant_id, v_drift.drift_event_id, v_new_version,
        v_drift.status, p_to_status, p_actor_subject, p_reason,
        p_approval_case_ref, p_details, v_occurred_at
    );
    RETURN v_new_version;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.schema_drift_transition_allowed', '0', true);
    RAISE;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_source_schema_drift_insert_guard
    ON gda_control.source_schema_drift;
CREATE TRIGGER trg_gda_source_schema_drift_insert_guard
BEFORE INSERT ON gda_control.source_schema_drift
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_source_schema_drift_insert();

DROP TRIGGER IF EXISTS trg_gda_source_schema_drift_initialize
    ON gda_control.source_schema_drift;
CREATE TRIGGER trg_gda_source_schema_drift_initialize
AFTER INSERT ON gda_control.source_schema_drift
FOR EACH ROW EXECUTE FUNCTION gda_control.initialize_source_schema_drift_event();

DROP TRIGGER IF EXISTS trg_gda_source_schema_drift_update_guard
    ON gda_control.source_schema_drift;
CREATE TRIGGER trg_gda_source_schema_drift_update_guard
BEFORE UPDATE ON gda_control.source_schema_drift
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_source_schema_drift_update();

DROP TRIGGER IF EXISTS trg_gda_source_schema_drift_delete_guard
    ON gda_control.source_schema_drift;
CREATE TRIGGER trg_gda_source_schema_drift_delete_guard
BEFORE DELETE ON gda_control.source_schema_drift
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_source_schema_drift_lifecycle_immutable
    ON gda_control.source_schema_drift_lifecycle_event;
CREATE TRIGGER trg_gda_source_schema_drift_lifecycle_immutable
BEFORE UPDATE OR DELETE ON gda_control.source_schema_drift_lifecycle_event
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.source_schema_drift ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.source_schema_drift FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.source_schema_drift;
CREATE POLICY tenant_isolation ON gda_control.source_schema_drift
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.source_schema_drift_lifecycle_event
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.source_schema_drift_lifecycle_event
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.source_schema_drift_lifecycle_event;
CREATE POLICY tenant_isolation
    ON gda_control.source_schema_drift_lifecycle_event
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.source_schema_drift
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.source_schema_drift_lifecycle_event
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT, INSERT ON gda_control.source_schema_drift
    TO gda_control_gateway;
GRANT SELECT ON gda_control.source_schema_drift_lifecycle_event
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.guard_source_schema_drift_insert()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.initialize_source_schema_drift_event()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.guard_source_schema_drift_update()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.transition_source_schema_drift(
    TEXT, TEXT, INTEGER, TEXT, TEXT, TEXT, TEXT, JSONB
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.transition_source_schema_drift(
    TEXT, TEXT, INTEGER, TEXT, TEXT, TEXT, TEXT, JSONB
) TO gda_control_gateway;
