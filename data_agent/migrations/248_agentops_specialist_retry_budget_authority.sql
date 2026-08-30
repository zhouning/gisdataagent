-- 248: durable retry budget for provider-bound AgentOps operations.
-- The operation family is stable across activity attempts and worker processes.

CREATE TABLE IF NOT EXISTS gda_control.agentops_specialist_retry_budget (
    tenant_id TEXT NOT NULL,
    operation_key TEXT NOT NULL,
    max_attempts INTEGER NOT NULL CHECK (max_attempts BETWEEN 1 AND 100),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'exhausted')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, operation_key),
    CONSTRAINT ck_gda_specialist_retry_budget_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_specialist_retry_budget_key
        CHECK (NULLIF(btrim(operation_key), '') IS NOT NULL
            AND octet_length(operation_key) <= 512),
    CONSTRAINT ck_gda_specialist_retry_budget_count
        CHECK (attempt_count <= max_attempts)
);

CREATE TABLE IF NOT EXISTS gda_control.agentops_specialist_retry_admission_history (
    tenant_id TEXT NOT NULL,
    operation_key TEXT NOT NULL,
    event_sequence BIGINT NOT NULL,
    event_sha256 CHAR(64) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    attempt_no INTEGER NOT NULL CHECK (attempt_no >= 1),
    max_attempts INTEGER NOT NULL CHECK (max_attempts BETWEEN 1 AND 100),
    worker_id TEXT NOT NULL,
    admitted BOOLEAN NOT NULL,
    reason TEXT NOT NULL,
    event_document JSONB NOT NULL,
    recorded_by TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, operation_key, event_sequence),
    UNIQUE (tenant_id, event_sha256),
    UNIQUE (tenant_id, operation_key, request_sha256, attempt_no),
    CONSTRAINT fk_gda_specialist_retry_budget
        FOREIGN KEY (tenant_id, operation_key)
        REFERENCES gda_control.agentops_specialist_retry_budget(tenant_id, operation_key),
    CONSTRAINT ck_gda_specialist_retry_event_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_specialist_retry_event_key
        CHECK (NULLIF(btrim(operation_key), '') IS NOT NULL
            AND octet_length(operation_key) <= 512),
    CONSTRAINT ck_gda_specialist_retry_event_hash
        CHECK (event_sha256 ~ '^[0-9a-f]{64}$' AND request_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_specialist_retry_event_worker
        CHECK (worker_id ~ '^(workload|agent):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_specialist_retry_event_actor
        CHECK (recorded_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_specialist_retry_event_document
        CHECK (jsonb_typeof(event_document) = 'object' AND event_document <> '{}'::jsonb)
);

CREATE INDEX IF NOT EXISTS idx_gda_specialist_retry_budget_due
    ON gda_control.agentops_specialist_retry_budget(tenant_id, updated_at);

ALTER TABLE gda_control.agentops_specialist_retry_budget ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.agentops_specialist_retry_budget FORCE ROW LEVEL SECURITY;
ALTER TABLE gda_control.agentops_specialist_retry_admission_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.agentops_specialist_retry_admission_history FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.agentops_specialist_retry_budget;
CREATE POLICY tenant_isolation ON gda_control.agentops_specialist_retry_budget
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());
DROP POLICY IF EXISTS tenant_isolation ON gda_control.agentops_specialist_retry_admission_history;
CREATE POLICY tenant_isolation ON gda_control.agentops_specialist_retry_admission_history
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE OR REPLACE FUNCTION gda_control.guard_agentops_specialist_retry_budget()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF COALESCE(current_setting('gda.agentops_specialist_retry_budget_write_allowed', true), '') <> '1' THEN
        RAISE EXCEPTION 'use the AgentOps specialist retry budget authority functions' USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'AgentOps specialist retry budget tenant context is missing or mismatched' USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_specialist_retry_budget_guard
    ON gda_control.agentops_specialist_retry_budget;
CREATE TRIGGER trg_gda_specialist_retry_budget_guard
BEFORE INSERT OR UPDATE ON gda_control.agentops_specialist_retry_budget
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_agentops_specialist_retry_budget();

CREATE OR REPLACE FUNCTION gda_control.guard_agentops_specialist_retry_event()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF COALESCE(current_setting('gda.agentops_specialist_retry_budget_write_allowed', true), '') <> '1' THEN
        RAISE EXCEPTION 'use the AgentOps specialist retry budget authority functions' USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'AgentOps specialist retry event tenant context is missing or mismatched' USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_specialist_retry_event_guard
    ON gda_control.agentops_specialist_retry_admission_history;
CREATE TRIGGER trg_gda_specialist_retry_event_guard
BEFORE INSERT ON gda_control.agentops_specialist_retry_admission_history
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_agentops_specialist_retry_event();
DROP TRIGGER IF EXISTS trg_gda_specialist_retry_event_immutable
    ON gda_control.agentops_specialist_retry_admission_history;
CREATE TRIGGER trg_gda_specialist_retry_event_immutable
BEFORE UPDATE OR DELETE ON gda_control.agentops_specialist_retry_admission_history
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

CREATE OR REPLACE FUNCTION gda_control.record_agentops_specialist_retry_admission(
    p_tenant_id TEXT,
    p_operation_key TEXT,
    p_admitted_event_document JSONB,
    p_admitted_fingerprint_payload TEXT,
    p_denied_event_document JSONB,
    p_denied_fingerprint_payload TEXT,
    p_max_attempts INTEGER,
    p_recorded_by TEXT
)
RETURNS TABLE(event_document JSONB, created BOOLEAN)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, gda_control
SET row_security = on
AS $$
DECLARE
    v_budget gda_control.agentops_specialist_retry_budget%ROWTYPE;
    v_existing gda_control.agentops_specialist_retry_admission_history%ROWTYPE;
    v_event JSONB;
    v_attempt INTEGER;
    v_admitted BOOLEAN;
    v_reason TEXT;
    v_sequence BIGINT;
    v_hash TEXT;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id
       OR p_tenant_id !~ '^[a-z0-9][a-z0-9._-]{0,63}$'
       OR NULLIF(btrim(p_operation_key), '') IS NULL
       OR octet_length(p_operation_key) > 512
       OR p_admitted_event_document IS NULL OR jsonb_typeof(p_admitted_event_document) <> 'object'
       OR p_denied_event_document IS NULL OR jsonb_typeof(p_denied_event_document) <> 'object'
       OR p_max_attempts NOT BETWEEN 1 AND 100
       OR p_recorded_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$' THEN
        RAISE EXCEPTION 'AgentOps specialist retry admission identity is invalid' USING ERRCODE = '22023';
    END IF;
    IF p_admitted_fingerprint_payload::JSONB IS DISTINCT FROM jsonb_build_object(
           'schema', 'gda.specialist_retry_admission.v1',
           'data', p_admitted_event_document - 'event_sha256')
       OR p_denied_fingerprint_payload::JSONB IS DISTINCT FROM jsonb_build_object(
           'schema', 'gda.specialist_retry_admission.v1',
           'data', p_denied_event_document - 'event_sha256')
       OR encode(public.digest(convert_to(p_admitted_fingerprint_payload, 'UTF8'), 'sha256'), 'hex')
            IS DISTINCT FROM p_admitted_event_document ->> 'event_sha256'
       OR encode(public.digest(convert_to(p_denied_fingerprint_payload, 'UTF8'), 'sha256'), 'hex')
            IS DISTINCT FROM p_denied_event_document ->> 'event_sha256' THEN
        RAISE EXCEPTION 'retry admission fingerprint is invalid' USING ERRCODE = '22023';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'agentops-specialist-retry|' || p_tenant_id || '|' || p_operation_key, 0));

    SELECT * INTO v_budget
    FROM gda_control.agentops_specialist_retry_budget
    WHERE tenant_id = p_tenant_id AND operation_key = p_operation_key
    FOR UPDATE;
    IF NOT FOUND THEN
        PERFORM set_config('gda.agentops_specialist_retry_budget_write_allowed', '1', true);
        INSERT INTO gda_control.agentops_specialist_retry_budget
            (tenant_id, operation_key, max_attempts)
        VALUES (p_tenant_id, p_operation_key, p_max_attempts);
        PERFORM set_config('gda.agentops_specialist_retry_budget_write_allowed', '0', true);
        SELECT * INTO v_budget
        FROM gda_control.agentops_specialist_retry_budget
        WHERE tenant_id = p_tenant_id AND operation_key = p_operation_key
        FOR UPDATE;
    ELSIF v_budget.max_attempts <> p_max_attempts THEN
        RAISE EXCEPTION 'retry budget max_attempts differs from existing operation family' USING ERRCODE = '40001';
    END IF;

    SELECT * INTO v_existing
    FROM gda_control.agentops_specialist_retry_admission_history
    WHERE tenant_id = p_tenant_id
      AND operation_key = p_operation_key
      AND request_sha256 = p_admitted_event_document ->> 'request_sha256'
      AND attempt_no = (p_admitted_event_document ->> 'attempt_no')::INTEGER;
    IF FOUND THEN
        v_event := CASE WHEN v_existing.admitted
            THEN p_admitted_event_document ELSE p_denied_event_document END;
        -- Worker identity is audit metadata and may change on restart. Its hash
        -- therefore changes too; all semantic request and decision fields must match.
        IF (v_existing.event_document - 'worker_id' - 'event_sha256')
             IS DISTINCT FROM (v_event - 'worker_id' - 'event_sha256') THEN
            RAISE EXCEPTION 'retry admission idempotency evidence differs' USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT v_existing.event_document, FALSE;
        RETURN;
    END IF;

    v_attempt := v_budget.attempt_count + 1;
    v_admitted := v_budget.status = 'active' AND v_attempt <= v_budget.max_attempts;
    v_reason := CASE WHEN v_admitted THEN 'budget_admitted' ELSE 'retry_budget_exhausted' END;
    v_event := CASE WHEN v_admitted THEN p_admitted_event_document ELSE p_denied_event_document END;
    v_hash := v_event ->> 'event_sha256';
    v_event := jsonb_set(v_event, '{event_sha256}', to_jsonb(v_hash));

    IF v_admitted THEN
        PERFORM set_config('gda.agentops_specialist_retry_budget_write_allowed', '1', true);
        UPDATE gda_control.agentops_specialist_retry_budget
        SET attempt_count = v_attempt,
            status = CASE WHEN v_attempt >= max_attempts THEN 'exhausted' ELSE status END,
            updated_at = clock_timestamp()
        WHERE tenant_id = p_tenant_id AND operation_key = p_operation_key;
        PERFORM set_config('gda.agentops_specialist_retry_budget_write_allowed', '0', true);
    END IF;
    SELECT COALESCE(MAX(event_sequence), 0) + 1 INTO v_sequence
    FROM gda_control.agentops_specialist_retry_admission_history
    WHERE tenant_id = p_tenant_id AND operation_key = p_operation_key;
    PERFORM set_config('gda.agentops_specialist_retry_budget_write_allowed', '1', true);
    INSERT INTO gda_control.agentops_specialist_retry_admission_history (
        tenant_id, operation_key, event_sequence, event_sha256, request_sha256,
        attempt_no, max_attempts, worker_id, admitted, reason, event_document, recorded_by
    ) VALUES (
        p_tenant_id, p_operation_key, v_sequence, v_hash,
        v_event ->> 'request_sha256', (v_event ->> 'attempt_no')::INTEGER,
        p_max_attempts, v_event ->> 'worker_id', v_admitted, v_reason, v_event, p_recorded_by
    );
    PERFORM set_config('gda.agentops_specialist_retry_budget_write_allowed', '0', true);
    RETURN QUERY SELECT v_event, TRUE;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.agentops_specialist_retry_budget_write_allowed', '0', true);
    RAISE;
END;
$$;

REVOKE ALL ON gda_control.agentops_specialist_retry_budget FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON gda_control.agentops_specialist_retry_admission_history FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON gda_control.agentops_specialist_retry_budget TO gda_control_gateway;
GRANT SELECT ON gda_control.agentops_specialist_retry_admission_history TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_agentops_specialist_retry_admission(
    text, text, jsonb, text, jsonb, text, integer, text
) TO gda_control_gateway;
