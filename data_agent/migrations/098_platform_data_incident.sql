-- 098: Add governed DataIncident lifecycle and cancellation convergence evidence.
--
-- Incidents keep their immutable cause/evidence binding in data_incident while
-- status changes are CAS-controlled and appended to data_incident_event.

CREATE TABLE IF NOT EXISTS gda_control.data_incident (
    tenant_id TEXT NOT NULL,
    incident_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL,
    dedupe_key TEXT NOT NULL,
    incident_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    summary TEXT NOT NULL,
    trigger_observation_id UUID,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    incident_sha256 CHAR(64) NOT NULL,
    detected_by TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    state_version INTEGER NOT NULL DEFAULT 0,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gda_data_incident_tenant_id UNIQUE (tenant_id, incident_id),
    CONSTRAINT uq_gda_data_incident_dedupe UNIQUE (tenant_id, dedupe_key),
    CONSTRAINT fk_gda_data_incident_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.platform_run(tenant_id, run_id),
    CONSTRAINT fk_gda_data_incident_observation
        FOREIGN KEY (tenant_id, trigger_observation_id)
        REFERENCES gda_control.framework_attempt_observation(tenant_id, observation_id),
    CONSTRAINT ck_gda_data_incident_dedupe
        CHECK (dedupe_key ~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$'),
    CONSTRAINT ck_gda_data_incident_type
        CHECK (incident_type ~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$'),
    CONSTRAINT ck_gda_data_incident_severity
        CHECK (severity IN ('low','medium','high','critical')),
    CONSTRAINT ck_gda_data_incident_summary
        CHECK (NULLIF(btrim(summary), '') IS NOT NULL),
    CONSTRAINT ck_gda_data_incident_details
        CHECK (jsonb_typeof(details) = 'object'),
    CONSTRAINT ck_gda_data_incident_sha256
        CHECK (incident_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_data_incident_detector
        CHECK (detected_by ~ '^workload:[^[:space:]]+$'),
    CONSTRAINT ck_gda_data_incident_status
        CHECK (status IN ('open','acknowledged','resolved')),
    CONSTRAINT ck_gda_data_incident_state_version CHECK (state_version >= 0),
    CONSTRAINT ck_gda_data_incident_initial_state CHECK (
        (state_version = 0 AND status = 'open')
        OR (state_version > 0 AND status <> 'open')
    ),
    CONSTRAINT ck_gda_data_incident_time CHECK (updated_at >= opened_at)
);

CREATE INDEX IF NOT EXISTS idx_gda_data_incident_attention
    ON gda_control.data_incident(tenant_id, status, severity, opened_at DESC);
CREATE INDEX IF NOT EXISTS idx_gda_data_incident_run
    ON gda_control.data_incident(tenant_id, run_id, opened_at DESC);

CREATE TABLE IF NOT EXISTS gda_control.data_incident_event (
    tenant_id TEXT NOT NULL,
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID NOT NULL,
    sequence_no INTEGER NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gda_data_incident_event_tenant_id UNIQUE (tenant_id, event_id),
    CONSTRAINT uq_gda_data_incident_event_sequence
        UNIQUE (tenant_id, incident_id, sequence_no),
    CONSTRAINT fk_gda_data_incident_event_incident
        FOREIGN KEY (tenant_id, incident_id)
        REFERENCES gda_control.data_incident(tenant_id, incident_id),
    CONSTRAINT ck_gda_data_incident_event_sequence CHECK (sequence_no >= 0),
    CONSTRAINT ck_gda_data_incident_event_from_status CHECK (
        from_status IS NULL OR from_status IN ('open','acknowledged','resolved')
    ),
    CONSTRAINT ck_gda_data_incident_event_to_status
        CHECK (to_status IN ('open','acknowledged','resolved')),
    CONSTRAINT ck_gda_data_incident_event_initial CHECK (
        (sequence_no = 0 AND from_status IS NULL AND to_status = 'open')
        OR (sequence_no > 0 AND from_status IS NOT NULL)
    ),
    CONSTRAINT ck_gda_data_incident_event_actor
        CHECK (NULLIF(btrim(actor_subject), '') IS NOT NULL),
    CONSTRAINT ck_gda_data_incident_event_reason
        CHECK (NULLIF(btrim(reason), '') IS NOT NULL),
    CONSTRAINT ck_gda_data_incident_event_details
        CHECK (jsonb_typeof(details) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_gda_data_incident_event_incident
    ON gda_control.data_incident_event(tenant_id, incident_id, sequence_no);

CREATE OR REPLACE FUNCTION gda_control.initialize_data_incident_event()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'data incident tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    INSERT INTO gda_control.data_incident_event (
        tenant_id, incident_id, sequence_no, from_status, to_status,
        actor_subject, reason, details, occurred_at
    ) VALUES (
        NEW.tenant_id, NEW.incident_id, 0, NULL, 'open',
        NEW.detected_by, 'incident detected', NEW.details, NEW.opened_at
    );
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.guard_data_incident_update()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(current_setting('gda.incident_transition_allowed', true), '') <> '1' THEN
        RAISE EXCEPTION 'use gda_control.transition_data_incident()'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.incident_id IS DISTINCT FROM OLD.incident_id
       OR NEW.run_id IS DISTINCT FROM OLD.run_id
       OR NEW.dedupe_key IS DISTINCT FROM OLD.dedupe_key
       OR NEW.incident_type IS DISTINCT FROM OLD.incident_type
       OR NEW.severity IS DISTINCT FROM OLD.severity
       OR NEW.summary IS DISTINCT FROM OLD.summary
       OR NEW.trigger_observation_id IS DISTINCT FROM OLD.trigger_observation_id
       OR NEW.details IS DISTINCT FROM OLD.details
       OR NEW.incident_sha256 IS DISTINCT FROM OLD.incident_sha256
       OR NEW.detected_by IS DISTINCT FROM OLD.detected_by
       OR NEW.opened_at IS DISTINCT FROM OLD.opened_at THEN
        RAISE EXCEPTION 'immutable data incident binding cannot be changed'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.state_version <> OLD.state_version + 1 OR NEW.status = OLD.status THEN
        RAISE EXCEPTION 'data incident transition must advance state_version once'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.transition_data_incident(
    p_tenant_id TEXT,
    p_incident_id UUID,
    p_expected_state_version INTEGER,
    p_to_status TEXT,
    p_actor_subject TEXT,
    p_reason TEXT,
    p_details JSONB DEFAULT '{}'::jsonb
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_incident gda_control.data_incident%ROWTYPE;
    v_allowed BOOLEAN := FALSE;
    v_new_version INTEGER;
    v_occurred_at TIMESTAMPTZ;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'data incident tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF NULLIF(btrim(p_actor_subject), '') IS NULL
       OR NULLIF(btrim(p_reason), '') IS NULL THEN
        RAISE EXCEPTION 'incident transition actor and reason are required'
            USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(p_details) <> 'object' THEN
        RAISE EXCEPTION 'incident transition details must be a JSON object'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_incident
    FROM gda_control.data_incident
    WHERE tenant_id = p_tenant_id AND incident_id = p_incident_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'data incident % not found', p_incident_id
            USING ERRCODE = 'P0002';
    END IF;
    IF v_incident.state_version <> p_expected_state_version THEN
        RAISE EXCEPTION 'data incident state version conflict: expected %, actual %',
            p_expected_state_version, v_incident.state_version
            USING ERRCODE = '40001';
    END IF;

    v_allowed := CASE v_incident.status
        WHEN 'open' THEN p_to_status = ANY (ARRAY['acknowledged','resolved'])
        WHEN 'acknowledged' THEN p_to_status = 'resolved'
        ELSE FALSE
    END;
    IF NOT v_allowed THEN
        RAISE EXCEPTION 'invalid data incident transition % -> %',
            v_incident.status, p_to_status
            USING ERRCODE = '23514';
    END IF;

    v_new_version := v_incident.state_version + 1;
    v_occurred_at := clock_timestamp();
    PERFORM set_config('gda.incident_transition_allowed', '1', true);
    UPDATE gda_control.data_incident
    SET status = p_to_status,
        state_version = v_new_version,
        updated_at = v_occurred_at
    WHERE tenant_id = p_tenant_id AND incident_id = p_incident_id;
    PERFORM set_config('gda.incident_transition_allowed', '0', true);

    INSERT INTO gda_control.data_incident_event (
        tenant_id, incident_id, sequence_no, from_status, to_status,
        actor_subject, reason, details, occurred_at
    ) VALUES (
        v_incident.tenant_id, v_incident.incident_id, v_new_version,
        v_incident.status, p_to_status, p_actor_subject, p_reason,
        p_details, v_occurred_at
    );
    RETURN v_new_version;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.incident_transition_allowed', '0', true);
    RAISE;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_data_incident_initialize
    ON gda_control.data_incident;
CREATE TRIGGER trg_gda_data_incident_initialize
AFTER INSERT ON gda_control.data_incident
FOR EACH ROW EXECUTE FUNCTION gda_control.initialize_data_incident_event();

DROP TRIGGER IF EXISTS trg_gda_data_incident_guard
    ON gda_control.data_incident;
CREATE TRIGGER trg_gda_data_incident_guard
BEFORE UPDATE ON gda_control.data_incident
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_data_incident_update();

DROP TRIGGER IF EXISTS trg_gda_data_incident_immutable_delete
    ON gda_control.data_incident;
CREATE TRIGGER trg_gda_data_incident_immutable_delete
BEFORE DELETE ON gda_control.data_incident
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_data_incident_event_immutable
    ON gda_control.data_incident_event;
CREATE TRIGGER trg_gda_data_incident_event_immutable
BEFORE UPDATE OR DELETE ON gda_control.data_incident_event
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.data_incident ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.data_incident FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.data_incident;
CREATE POLICY tenant_isolation ON gda_control.data_incident
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.data_incident_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.data_incident_event FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.data_incident_event;
CREATE POLICY tenant_isolation ON gda_control.data_incident_event
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.data_incident FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.data_incident_event FROM PUBLIC, gda_control_gateway;
GRANT SELECT, INSERT ON gda_control.data_incident TO gda_control_gateway;
GRANT SELECT ON gda_control.data_incident_event TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.initialize_data_incident_event() FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.guard_data_incident_update() FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.transition_data_incident(
    TEXT, UUID, INTEGER, TEXT, TEXT, TEXT, JSONB
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.transition_data_incident(
    TEXT, UUID, INTEGER, TEXT, TEXT, TEXT, JSONB
) TO gda_control_gateway;
