-- 246: Durable provider operation receipts for AgentOps specialist activities.
--
-- Temporal activity history records what the worker observed.  This ledger records
-- the provider operation identity and terminal state independently, so a lost
-- activity response cannot cause a second provider submission.

CREATE TABLE IF NOT EXISTS gda_control.agentops_specialist_operation_receipt_history (
    tenant_id TEXT NOT NULL,
    operation_ref TEXT NOT NULL,
    receipt_sequence BIGINT NOT NULL,
    receipt_sha256 CHAR(64) NOT NULL,
    workflow_id TEXT NOT NULL,
    run_id UUID NOT NULL,
    step_id UUID NOT NULL,
    tool_call_id UUID NOT NULL,
    activity_id UUID NOT NULL,
    attempt_no INTEGER NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    provider_ref TEXT NOT NULL,
    provider_receipt_ref TEXT NOT NULL,
    status TEXT NOT NULL,
    output_artifact_id UUID,
    failure_type TEXT,
    cancellation_requested BOOLEAN NOT NULL DEFAULT FALSE,
    receipt_document JSONB NOT NULL,
    recorded_by TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, operation_ref, receipt_sequence),
    CONSTRAINT uq_gda_agentops_specialist_operation_receipt_sha
        UNIQUE (tenant_id, receipt_sha256),
    CONSTRAINT fk_gda_agentops_specialist_operation_output
        FOREIGN KEY (tenant_id, output_artifact_id)
        REFERENCES gda_control.artifact (tenant_id, artifact_id),
    CONSTRAINT ck_gda_agentops_specialist_operation_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_agentops_specialist_operation_ref
        CHECK (NULLIF(btrim(operation_ref), '') IS NOT NULL
            AND octet_length(operation_ref) <= 512),
    CONSTRAINT ck_gda_agentops_specialist_operation_workflow
        CHECK (workflow_id ~ '^[a-z][a-z0-9._:-]{1,254}$'),
    CONSTRAINT ck_gda_agentops_specialist_operation_attempt
        CHECK (attempt_no >= 1),
    CONSTRAINT ck_gda_agentops_specialist_operation_hashes CHECK (
        receipt_sha256 ~ '^[0-9a-f]{64}$'
        AND request_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_agentops_specialist_operation_provider
        CHECK (NULLIF(btrim(provider_ref), '') IS NOT NULL
            AND octet_length(provider_ref) <= 256
            AND NULLIF(btrim(provider_receipt_ref), '') IS NOT NULL
            AND octet_length(provider_receipt_ref) <= 512),
    CONSTRAINT ck_gda_agentops_specialist_operation_status
        CHECK (status IN ('submitted', 'succeeded', 'failed', 'cancelled', 'unknown')),
    CONSTRAINT ck_gda_agentops_specialist_operation_terminal_payload CHECK (
        (status = 'succeeded' AND output_artifact_id IS NOT NULL AND failure_type IS NULL)
        OR (status IN ('failed', 'cancelled')
            AND output_artifact_id IS NULL
            AND NULLIF(btrim(failure_type), '') IS NOT NULL)
        OR (status IN ('submitted', 'unknown')
            AND output_artifact_id IS NULL
            AND failure_type IS NULL)
    ),
    CONSTRAINT ck_gda_agentops_specialist_operation_document CHECK (
        jsonb_typeof(receipt_document) = 'object'
        AND receipt_document <> '{}'::jsonb
    ),
    CONSTRAINT ck_gda_agentops_specialist_operation_actor CHECK (
        recorded_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_agentops_specialist_operation_current
    ON gda_control.agentops_specialist_operation_receipt_history (
        tenant_id, operation_ref, receipt_sequence DESC
    );

CREATE INDEX IF NOT EXISTS idx_gda_agentops_specialist_operation_activity
    ON gda_control.agentops_specialist_operation_receipt_history (
        tenant_id, workflow_id, activity_id, attempt_no, recorded_at
    );

CREATE OR REPLACE VIEW gda_control.agentops_specialist_operation_receipt_current
WITH (security_invoker = true)
AS
SELECT DISTINCT ON (tenant_id, operation_ref)
       tenant_id, operation_ref, receipt_sequence, receipt_sha256,
       workflow_id, run_id, step_id, tool_call_id, activity_id, attempt_no,
       request_sha256, provider_ref, provider_receipt_ref, status,
       output_artifact_id, failure_type, cancellation_requested,
       receipt_document, recorded_by, recorded_at
FROM gda_control.agentops_specialist_operation_receipt_history
ORDER BY tenant_id, operation_ref, receipt_sequence DESC;

CREATE OR REPLACE FUNCTION gda_control.guard_agentops_specialist_operation_receipt()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.agentops_specialist_operation_write_allowed', true), ''
    ) <> '1' THEN
        RAISE EXCEPTION 'use the AgentOps specialist operation authority functions'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'AgentOps specialist operation tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_agentops_specialist_operation_immutable
    ON gda_control.agentops_specialist_operation_receipt_history;
CREATE TRIGGER trg_gda_agentops_specialist_operation_immutable
BEFORE UPDATE OR DELETE
ON gda_control.agentops_specialist_operation_receipt_history
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_agentops_specialist_operation_guard
    ON gda_control.agentops_specialist_operation_receipt_history;
CREATE TRIGGER trg_gda_agentops_specialist_operation_guard
BEFORE INSERT
ON gda_control.agentops_specialist_operation_receipt_history
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_agentops_specialist_operation_receipt();

ALTER TABLE gda_control.agentops_specialist_operation_receipt_history
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.agentops_specialist_operation_receipt_history
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.agentops_specialist_operation_receipt_history;
CREATE POLICY tenant_isolation
ON gda_control.agentops_specialist_operation_receipt_history
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE OR REPLACE FUNCTION gda_control.record_agentops_specialist_operation_receipt(
    p_tenant_id TEXT,
    p_operation_ref TEXT,
    p_receipt_document JSONB,
    p_fingerprint_payload TEXT,
    p_recorded_by TEXT
)
RETURNS TABLE(receipt_document JSONB, receipt_sequence BIGINT, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, gda_control
SET row_security = on
AS $$
DECLARE
    v_current gda_control.agentops_specialist_operation_receipt_history%ROWTYPE;
    v_existing gda_control.agentops_specialist_operation_receipt_history%ROWTYPE;
    v_sequence BIGINT;
    v_receipt_sha256 TEXT;
    v_status TEXT;
    v_existing_found BOOLEAN := FALSE;
    v_allowed BOOLEAN := FALSE;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'AgentOps specialist operation tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_tenant_id !~ '^[a-z0-9][a-z0-9._-]{0,63}$'
       OR NULLIF(btrim(p_operation_ref), '') IS NULL
       OR octet_length(p_operation_ref) > 512
       OR p_receipt_document IS NULL
       OR jsonb_typeof(p_receipt_document) <> 'object'
       OR p_fingerprint_payload IS NULL
       OR p_recorded_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$' THEN
        RAISE EXCEPTION 'AgentOps specialist operation receipt identity is invalid'
            USING ERRCODE = '22023';
    END IF;

    v_receipt_sha256 := p_receipt_document ->> 'receipt_sha256';
    v_status := p_receipt_document ->> 'status';
    IF v_receipt_sha256 !~ '^[0-9a-f]{64}$'
       OR v_status NOT IN ('submitted', 'succeeded', 'failed', 'cancelled', 'unknown')
       OR p_receipt_document ->> 'tenant_id' IS DISTINCT FROM p_tenant_id
       OR p_receipt_document ->> 'operation_ref' IS DISTINCT FROM p_operation_ref
       OR p_receipt_document ->> 'workflow_id' !~ '^[a-z][a-z0-9._:-]{1,254}$'
       OR p_receipt_document ->> 'request_sha256' !~ '^[0-9a-f]{64}$'
       OR p_receipt_document ->> 'provider_ref' IS NULL
       OR p_receipt_document ->> 'provider_receipt_ref' IS NULL
       OR p_fingerprint_payload::JSONB IS DISTINCT FROM jsonb_build_object(
            'schema', 'gda.specialist_operation_receipt.v1',
            'data', p_receipt_document - 'receipt_sha256'
       )
       OR encode(
            public.digest(convert_to(p_fingerprint_payload, 'UTF8'), 'sha256'), 'hex'
       ) IS DISTINCT FROM v_receipt_sha256 THEN
        RAISE EXCEPTION 'AgentOps specialist operation receipt fingerprint or identity is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'agentops-specialist-operation|' || p_tenant_id || '|' || p_operation_ref,
        0
    ));

    SELECT history.* INTO v_existing
    FROM gda_control.agentops_specialist_operation_receipt_history AS history
    WHERE history.tenant_id = p_tenant_id
      AND history.receipt_sha256 = v_receipt_sha256
    LIMIT 1;
    IF FOUND THEN
        IF v_existing.operation_ref IS DISTINCT FROM p_operation_ref
           OR v_existing.receipt_document IS DISTINCT FROM p_receipt_document
           OR v_existing.recorded_by IS DISTINCT FROM p_recorded_by THEN
            RAISE EXCEPTION 'AgentOps specialist operation receipt idempotency evidence differs'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT
            v_existing.receipt_document, v_existing.receipt_sequence, FALSE;
        RETURN;
    END IF;

    SELECT history.* INTO v_current
    FROM gda_control.agentops_specialist_operation_receipt_history AS history
    WHERE history.tenant_id = p_tenant_id
      AND history.operation_ref = p_operation_ref
    ORDER BY history.receipt_sequence DESC
    LIMIT 1
    FOR UPDATE;
    v_existing_found := FOUND;

    IF NOT v_existing_found THEN
        IF v_status <> 'submitted' THEN
            RAISE EXCEPTION 'first specialist operation receipt must be submitted'
                USING ERRCODE = '40001';
        END IF;
        v_sequence := 1;
    ELSE
        IF p_receipt_document ->> 'workflow_id' IS DISTINCT FROM v_current.workflow_id
           OR (p_receipt_document ->> 'run_id')::UUID IS DISTINCT FROM v_current.run_id
           OR (p_receipt_document ->> 'step_id')::UUID IS DISTINCT FROM v_current.step_id
           OR (p_receipt_document ->> 'tool_call_id')::UUID IS DISTINCT FROM v_current.tool_call_id
           OR (p_receipt_document ->> 'activity_id')::UUID IS DISTINCT FROM v_current.activity_id
           OR (p_receipt_document ->> 'attempt_no')::INTEGER IS DISTINCT FROM v_current.attempt_no
           OR p_receipt_document ->> 'request_sha256' IS DISTINCT FROM v_current.request_sha256
           OR p_receipt_document ->> 'provider_ref' IS DISTINCT FROM v_current.provider_ref
           OR p_receipt_document ->> 'provider_receipt_ref'
                IS DISTINCT FROM v_current.provider_receipt_ref THEN
            RAISE EXCEPTION 'AgentOps specialist operation identity is already bound differently'
                USING ERRCODE = '40001';
        END IF;
        v_allowed := CASE v_current.status
            WHEN 'submitted' THEN v_status IN ('submitted', 'unknown', 'succeeded', 'failed', 'cancelled')
            WHEN 'unknown' THEN v_status IN ('unknown', 'succeeded', 'failed', 'cancelled')
            ELSE v_status = v_current.status
        END;
        IF NOT v_allowed THEN
            RAISE EXCEPTION 'AgentOps specialist operation terminal receipt conflicts'
                USING ERRCODE = '40001';
        END IF;
        IF v_status = v_current.status
           AND p_receipt_document IS DISTINCT FROM v_current.receipt_document THEN
            RAISE EXCEPTION 'AgentOps specialist operation state is not idempotent'
                USING ERRCODE = '40001';
        END IF;
        v_sequence := v_current.receipt_sequence + 1;
    END IF;

    PERFORM set_config('gda.agentops_specialist_operation_write_allowed', '1', true);
    INSERT INTO gda_control.agentops_specialist_operation_receipt_history (
        tenant_id, operation_ref, receipt_sequence, receipt_sha256,
        workflow_id, run_id, step_id, tool_call_id, activity_id, attempt_no,
        request_sha256, provider_ref, provider_receipt_ref, status,
        output_artifact_id, failure_type, cancellation_requested,
        receipt_document, recorded_by
    ) VALUES (
        p_tenant_id, p_operation_ref, v_sequence, v_receipt_sha256,
        p_receipt_document ->> 'workflow_id',
        (p_receipt_document ->> 'run_id')::UUID,
        (p_receipt_document ->> 'step_id')::UUID,
        (p_receipt_document ->> 'tool_call_id')::UUID,
        (p_receipt_document ->> 'activity_id')::UUID,
        (p_receipt_document ->> 'attempt_no')::INTEGER,
        p_receipt_document ->> 'request_sha256',
        p_receipt_document ->> 'provider_ref',
        p_receipt_document ->> 'provider_receipt_ref',
        v_status,
        NULLIF(p_receipt_document ->> 'output_artifact_id', '')::UUID,
        NULLIF(p_receipt_document ->> 'failure_type', ''),
        COALESCE((p_receipt_document ->> 'cancellation_requested')::BOOLEAN, FALSE),
        p_receipt_document, p_recorded_by
    );
    PERFORM set_config('gda.agentops_specialist_operation_write_allowed', '0', true);
    RETURN QUERY SELECT p_receipt_document, v_sequence, TRUE;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.agentops_specialist_operation_write_allowed', '0', true);
    RAISE;
END;
$$;

REVOKE ALL ON gda_control.agentops_specialist_operation_receipt_history
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON gda_control.agentops_specialist_operation_receipt_current
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON gda_control.agentops_specialist_operation_receipt_history
    TO gda_control_gateway;
GRANT SELECT ON gda_control.agentops_specialist_operation_receipt_current
    TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_agentops_specialist_operation_receipt(
    text, text, jsonb, text, text
) TO gda_control_gateway;
