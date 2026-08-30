-- 242: Durable registration and discovery authority for Temporal start receipts.
--
-- A provider start receipt is not a reconciler configuration.  This table is
-- the durable hand-off between the start gateway and the managed reconciler:
-- the request/result evidence is immutable, while claim and settlement state
-- is recoverable.  Temporal remains the execution authority; GDA only owns
-- the registration, target lifecycle and evidence correlation.

CREATE TABLE IF NOT EXISTS gda_control.agentops_temporal_start_target (
    tenant_id TEXT NOT NULL,
    target_id UUID NOT NULL DEFAULT gen_random_uuid(),
    namespace_ref TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    workflow_type TEXT NOT NULL,
    task_queue_ref TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    start_request_sha256 CHAR(64) NOT NULL,
    start_request_document JSONB NOT NULL,
    start_result_sha256 CHAR(64) NOT NULL,
    start_result_document JSONB NOT NULL,
    start_reconciliation_sha256 CHAR(64),
    start_reconciliation_document JSONB,
    provider_run_id TEXT,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL,
    claimed_by TEXT,
    claimed_until TIMESTAMPTZ,
    last_error TEXT,
    registered_by TEXT NOT NULL,
    registered_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, target_id),
    CONSTRAINT uq_gda_agentops_temporal_start_target_id
        UNIQUE (target_id),
    CONSTRAINT uq_gda_agentops_temporal_start_target_workflow
        UNIQUE (tenant_id, workflow_id),
    CONSTRAINT uq_gda_agentops_temporal_start_target_idempotency
        UNIQUE (tenant_id, workflow_id, idempotency_key),
    CONSTRAINT ck_gda_agentops_temporal_start_target_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_agentops_temporal_start_target_namespace
        CHECK (namespace_ref ~ '^[a-z][a-z0-9._-]{1,62}$'),
    CONSTRAINT ck_gda_agentops_temporal_start_target_workflow
        CHECK (workflow_id ~ '^[a-z][a-z0-9._:-]{1,254}$'),
    CONSTRAINT ck_gda_agentops_temporal_start_target_workflow_type
        CHECK (workflow_type ~ '^[a-z][a-z0-9._-]{1,127}$'),
    CONSTRAINT ck_gda_agentops_temporal_start_target_queue
        CHECK (task_queue_ref ~ '^[a-z][a-z0-9._-]{1,62}$'),
    CONSTRAINT ck_gda_agentops_temporal_start_target_idempotency
        CHECK (NULLIF(btrim(idempotency_key), '') IS NOT NULL),
    CONSTRAINT ck_gda_agentops_temporal_start_target_hashes
        CHECK (
            start_request_sha256 ~ '^[0-9a-f]{64}$'
            AND start_result_sha256 ~ '^[0-9a-f]{64}$'
            AND (
                start_reconciliation_sha256 IS NULL
                OR start_reconciliation_sha256 ~ '^[0-9a-f]{64}$'
            )
        ),
    CONSTRAINT ck_gda_agentops_temporal_start_target_documents
        CHECK (
            jsonb_typeof(start_request_document) = 'object'
            AND start_request_document <> '{}'::jsonb
            AND jsonb_typeof(start_result_document) = 'object'
            AND start_result_document <> '{}'::jsonb
            AND (
                start_reconciliation_document IS NULL
                OR jsonb_typeof(start_reconciliation_document) = 'object'
            )
        ),
    CONSTRAINT ck_gda_agentops_temporal_start_target_status
        CHECK (status IN (
            'pending_start_reconciliation', 'ready', 'claimed', 'completed', 'failed'
        )),
    CONSTRAINT ck_gda_agentops_temporal_start_target_attempts
        CHECK (attempt_count >= 0),
    CONSTRAINT ck_gda_agentops_temporal_start_target_claim
        CHECK ((claimed_by IS NULL) = (claimed_until IS NULL)),
    CONSTRAINT ck_gda_agentops_temporal_start_target_actor
        CHECK (registered_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_agentops_temporal_start_target_state
        CHECK (
            (status = 'pending_start_reconciliation'
                AND provider_run_id IS NULL
                AND claimed_by IS NULL AND completed_at IS NULL)
            OR (status = 'ready'
                AND provider_run_id IS NOT NULL
                AND start_reconciliation_document IS NOT NULL
                AND claimed_by IS NULL AND completed_at IS NULL)
            OR (status = 'claimed'
                AND claimed_by IS NOT NULL AND completed_at IS NULL)
            OR (status = 'completed'
                AND provider_run_id IS NOT NULL
                AND start_reconciliation_document IS NOT NULL
                AND claimed_by IS NULL AND completed_at IS NOT NULL)
            OR (status = 'failed'
                AND claimed_by IS NULL AND completed_at IS NOT NULL
                AND NULLIF(btrim(last_error), '') IS NOT NULL)
        )
);

CREATE INDEX IF NOT EXISTS idx_gda_agentops_temporal_start_target_due
    ON gda_control.agentops_temporal_start_target(
        tenant_id, available_at, registered_at, target_id
    ) WHERE status IN ('pending_start_reconciliation', 'ready');
CREATE INDEX IF NOT EXISTS idx_gda_agentops_temporal_start_target_claim
    ON gda_control.agentops_temporal_start_target(tenant_id, claimed_until, target_id)
    WHERE status = 'claimed';

CREATE OR REPLACE FUNCTION gda_control.guard_agentops_temporal_start_target()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.agentops_temporal_start_target_write_allowed', true), ''
    ) <> '1' THEN
        RAISE EXCEPTION 'use the AgentOps Temporal start target functions'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR (CASE WHEN TG_OP = 'DELETE' THEN OLD.tenant_id ELSE NEW.tenant_id END)
            IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'AgentOps Temporal start target tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
           OR NEW.target_id IS DISTINCT FROM OLD.target_id
           OR NEW.namespace_ref IS DISTINCT FROM OLD.namespace_ref
           OR NEW.workflow_id IS DISTINCT FROM OLD.workflow_id
           OR NEW.workflow_type IS DISTINCT FROM OLD.workflow_type
           OR NEW.task_queue_ref IS DISTINCT FROM OLD.task_queue_ref
           OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
           OR NEW.start_request_sha256 IS DISTINCT FROM OLD.start_request_sha256
           OR NEW.start_request_document IS DISTINCT FROM OLD.start_request_document
           OR NEW.start_result_sha256 IS DISTINCT FROM OLD.start_result_sha256
           OR NEW.start_result_document IS DISTINCT FROM OLD.start_result_document
           OR (
                OLD.start_reconciliation_document IS NOT NULL
                AND OLD.start_reconciliation_document ->> 'verdict'
                    IS DISTINCT FROM 'unknown_pending'
                AND (
                    NEW.start_reconciliation_sha256 IS DISTINCT FROM OLD.start_reconciliation_sha256
                    OR NEW.start_reconciliation_document IS DISTINCT FROM OLD.start_reconciliation_document
                )
           )
           OR NEW.registered_by IS DISTINCT FROM OLD.registered_by
           OR NEW.registered_at IS DISTINCT FROM OLD.registered_at THEN
            RAISE EXCEPTION 'Temporal start target registration evidence is immutable'
                USING ERRCODE = '55000';
        END IF;
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.register_agentops_temporal_start_target(
    p_tenant_id TEXT,
    p_namespace_ref TEXT,
    p_workflow_id TEXT,
    p_workflow_type TEXT,
    p_task_queue_ref TEXT,
    p_idempotency_key TEXT,
    p_start_request_document JSONB,
    p_start_request_fingerprint_payload TEXT,
    p_start_result_document JSONB,
    p_start_result_fingerprint_payload TEXT,
    p_start_reconciliation_document JSONB,
    p_start_reconciliation_fingerprint_payload TEXT,
    p_registered_by TEXT,
    p_registered_at TIMESTAMPTZ,
    p_available_at TIMESTAMPTZ
)
RETURNS TABLE(target_id UUID, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_existing gda_control.agentops_temporal_start_target%ROWTYPE;
    v_target_id UUID;
    v_request_sha256 TEXT;
    v_result_sha256 TEXT;
    v_reconciliation_sha256 TEXT;
    v_result_status TEXT;
    v_provider_run_id TEXT;
    v_provider_receipt_ref TEXT;
    v_status TEXT;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'Temporal start target tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    IF p_tenant_id !~ '^[a-z0-9][a-z0-9._-]{0,63}$'
       OR p_namespace_ref !~ '^[a-z][a-z0-9._-]{1,62}$'
       OR p_workflow_id !~ '^[a-z][a-z0-9._:-]{1,254}$'
       OR p_workflow_type !~ '^[a-z][a-z0-9._-]{1,127}$'
       OR p_task_queue_ref !~ '^[a-z][a-z0-9._-]{1,62}$'
       OR NULLIF(btrim(p_idempotency_key), '') IS NULL
       OR p_start_request_document IS NULL
       OR p_start_result_document IS NULL
       OR p_registered_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR p_registered_at IS NULL OR p_available_at IS NULL THEN
        RAISE EXCEPTION 'Temporal start target registration identity is invalid' USING ERRCODE = '22023';
    END IF;
    IF p_start_request_document #>> '{payload,identity,idempotency_key}' IS DISTINCT FROM p_idempotency_key
       OR p_start_request_document #>> '{payload,identity,namespace,namespace_ref}' IS DISTINCT FROM p_namespace_ref
       OR p_start_request_document #>> '{payload,identity,workflow_id}' IS DISTINCT FROM p_workflow_id
       OR p_start_request_document #>> '{payload,identity,workflow_type}' IS DISTINCT FROM p_workflow_type
       OR p_start_request_document #>> '{payload,identity,task_queue,queue_ref}' IS DISTINCT FROM p_task_queue_ref
       OR p_start_request_document #>> '{payload,policy_decision_ref}' IS NULL
       OR p_start_request_document #>> '{payload,policy_decision_ref}' IS DISTINCT FROM
            p_start_request_document ->> 'policy_decision_ref' THEN
        RAISE EXCEPTION 'Temporal start request identity binding is invalid' USING ERRCODE = '22023';
    END IF;
    v_request_sha256 := p_start_request_document ->> 'payload_sha256';
    v_result_sha256 := p_start_result_document ->> 'result_sha256';
    v_result_status := p_start_result_document ->> 'status';
    v_provider_run_id := NULLIF(btrim(p_start_result_document ->> 'provider_run_id'), '');
    v_provider_receipt_ref := NULLIF(
        btrim(p_start_result_document ->> 'provider_receipt_ref'), ''
    );
    v_reconciliation_sha256 := NULLIF(
        btrim(p_start_reconciliation_document ->> 'reconciliation_sha256'), ''
    );
    IF p_start_request_document ->> 'tenant_id' IS DISTINCT FROM p_tenant_id
       OR p_start_request_document ->> 'namespace_ref' IS DISTINCT FROM p_namespace_ref
       OR p_start_request_document ->> 'workflow_id' IS DISTINCT FROM p_workflow_id
       OR p_start_request_document ->> 'workflow_type' IS DISTINCT FROM p_workflow_type
       OR p_start_request_document ->> 'task_queue_ref' IS DISTINCT FROM p_task_queue_ref
       OR p_start_result_document ->> 'tenant_id' IS DISTINCT FROM p_tenant_id
       OR p_start_result_document ->> 'namespace_ref' IS DISTINCT FROM p_namespace_ref
       OR p_start_result_document ->> 'workflow_id' IS DISTINCT FROM p_workflow_id
       OR v_request_sha256 !~ '^[0-9a-f]{64}$'
       OR v_result_sha256 !~ '^[0-9a-f]{64}$'
       OR v_result_status NOT IN ('started', 'already_exists', 'unknown')
       OR p_start_request_fingerprint_payload::JSONB IS DISTINCT FROM jsonb_build_object(
            'schema', 'gda.temporal_start_request.v1',
            'data', p_start_request_document - 'payload_sha256'
       )
       OR encode(public.digest(convert_to(p_start_request_fingerprint_payload, 'UTF8'), 'sha256'), 'hex')
            IS DISTINCT FROM v_request_sha256
       OR p_start_result_fingerprint_payload::JSONB IS DISTINCT FROM jsonb_build_object(
            'schema', 'gda.temporal_start_result.v1',
            'data', p_start_result_document - 'result_sha256'
       )
       OR encode(public.digest(convert_to(p_start_result_fingerprint_payload, 'UTF8'), 'sha256'), 'hex')
            IS DISTINCT FROM v_result_sha256 THEN
        RAISE EXCEPTION 'Temporal start target receipt fingerprint or identity is invalid' USING ERRCODE = '22023';
    END IF;
    IF v_result_status IN ('started', 'already_exists')
       AND (v_provider_run_id IS NULL OR v_provider_receipt_ref IS NULL) THEN
        RAISE EXCEPTION 'known Temporal start result requires provider run and receipt' USING ERRCODE = '22023';
    END IF;
    IF v_result_status = 'unknown' AND v_provider_receipt_ref IS NULL THEN
        RAISE EXCEPTION 'unknown Temporal start result requires provider receipt' USING ERRCODE = '22023';
    END IF;
    IF p_start_reconciliation_document IS NULL
       AND p_start_reconciliation_fingerprint_payload IS NOT NULL THEN
        RAISE EXCEPTION 'start reconciliation fingerprint requires a document' USING ERRCODE = '22023';
    END IF;
    IF p_start_reconciliation_document IS NOT NULL THEN
        IF p_start_reconciliation_fingerprint_payload IS NULL
           OR v_reconciliation_sha256 !~ '^[0-9a-f]{64}$'
           OR p_start_reconciliation_document ->> 'tenant_id' IS DISTINCT FROM p_tenant_id
           OR p_start_reconciliation_document ->> 'namespace_ref' IS DISTINCT FROM p_namespace_ref
           OR p_start_reconciliation_document ->> 'workflow_id' IS DISTINCT FROM p_workflow_id
           OR p_start_reconciliation_document ->> 'provider_status' IS DISTINCT FROM v_result_status
           OR p_start_reconciliation_document ->> 'request_sha256' IS DISTINCT FROM v_request_sha256
           OR p_start_reconciliation_document ->> 'provider_receipt_ref' IS DISTINCT FROM
                p_start_result_document ->> 'provider_receipt_ref'
           OR p_start_reconciliation_fingerprint_payload::JSONB IS DISTINCT FROM jsonb_build_object(
                'schema', 'gda.temporal_start_reconciliation.v1',
                'data', p_start_reconciliation_document - 'reconciliation_sha256'
           )
           OR encode(public.digest(convert_to(p_start_reconciliation_fingerprint_payload, 'UTF8'), 'sha256'), 'hex')
                IS DISTINCT FROM v_reconciliation_sha256 THEN
            RAISE EXCEPTION 'Temporal start reconciliation fingerprint or identity is invalid' USING ERRCODE = '22023';
        END IF;
        IF p_start_reconciliation_document ->> 'verdict' IS NULL
           OR (v_result_status = 'started'
               AND p_start_reconciliation_document ->> 'verdict' <> 'started')
           OR (v_result_status = 'already_exists'
               AND p_start_reconciliation_document ->> 'verdict' <> 'already_exists_matched')
           OR (v_result_status = 'unknown'
               AND p_start_reconciliation_document ->> 'verdict'
                    NOT IN ('already_exists_matched', 'unknown_pending')) THEN
            RAISE EXCEPTION 'Temporal start reconciliation verdict is invalid for result status' USING ERRCODE = '22023';
        END IF;
        IF p_start_reconciliation_document ->> 'verdict' = 'unknown_pending'
           AND p_start_reconciliation_document ->> 'provider_run_id' IS NOT NULL THEN
            RAISE EXCEPTION 'unknown pending reconciliation cannot claim a provider run' USING ERRCODE = '22023';
        END IF;
        IF p_start_reconciliation_document ->> 'verdict' = 'already_exists_matched'
           AND p_start_reconciliation_document ->> 'observed_input_sha256' IS DISTINCT FROM v_request_sha256 THEN
            RAISE EXCEPTION 'matched Temporal reconciliation input fingerprint differs' USING ERRCODE = '22023';
        END IF;
        IF p_start_reconciliation_document ->> 'verdict' = 'unknown_pending'
           AND p_start_reconciliation_document ->> 'observed_input_sha256' IS NOT NULL THEN
            RAISE EXCEPTION 'pending Temporal reconciliation cannot carry input evidence' USING ERRCODE = '22023';
        END IF;
        IF p_start_reconciliation_document ->> 'verdict' = 'started'
           AND p_start_reconciliation_document ->> 'observed_input_sha256' IS NOT NULL THEN
            RAISE EXCEPTION 'started Temporal reconciliation cannot carry input evidence' USING ERRCODE = '22023';
        END IF;
        IF p_start_reconciliation_document ->> 'provider_run_id' IS DISTINCT FROM v_provider_run_id
           AND v_result_status <> 'unknown' THEN
            RAISE EXCEPTION 'known Temporal start reconciliation provider run differs' USING ERRCODE = '22023';
        END IF;
    END IF;
    IF v_result_status = 'unknown' AND p_start_reconciliation_document IS NULL THEN
        v_status := 'pending_start_reconciliation';
    ELSIF p_start_reconciliation_document IS NULL THEN
        RAISE EXCEPTION 'known Temporal start result requires start reconciliation evidence' USING ERRCODE = '22023';
    ELSIF p_start_reconciliation_document ->> 'verdict' = 'unknown_pending' THEN
        v_status := 'pending_start_reconciliation';
    ELSE
        v_status := 'ready';
    END IF;

    SELECT target.* INTO v_existing
      FROM gda_control.agentops_temporal_start_target AS target
     WHERE target.tenant_id = p_tenant_id
       AND target.workflow_id = p_workflow_id
     FOR UPDATE;
    IF FOUND THEN
        IF v_existing.namespace_ref IS DISTINCT FROM p_namespace_ref
           OR v_existing.workflow_type IS DISTINCT FROM p_workflow_type
           OR v_existing.task_queue_ref IS DISTINCT FROM p_task_queue_ref
           OR v_existing.idempotency_key IS DISTINCT FROM p_idempotency_key
           OR v_existing.start_request_sha256 IS DISTINCT FROM v_request_sha256
           OR v_existing.start_request_document IS DISTINCT FROM p_start_request_document
           OR v_existing.start_result_sha256 IS DISTINCT FROM v_result_sha256
           OR v_existing.start_result_document IS DISTINCT FROM p_start_result_document
           OR v_existing.start_reconciliation_sha256 IS DISTINCT FROM v_reconciliation_sha256
           OR v_existing.start_reconciliation_document IS DISTINCT FROM p_start_reconciliation_document THEN
            RAISE EXCEPTION 'Temporal start target replay has different immutable evidence' USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT v_existing.target_id, FALSE;
        RETURN;
    END IF;

    PERFORM set_config('gda.agentops_temporal_start_target_write_allowed', '1', true);
    INSERT INTO gda_control.agentops_temporal_start_target (
        tenant_id, namespace_ref, workflow_id, workflow_type, task_queue_ref,
        idempotency_key, start_request_sha256, start_request_document,
        start_result_sha256, start_result_document, start_reconciliation_sha256,
        start_reconciliation_document, provider_run_id, status, available_at,
        registered_by, registered_at, updated_at
    ) VALUES (
        p_tenant_id, p_namespace_ref, p_workflow_id, p_workflow_type, p_task_queue_ref,
        p_idempotency_key, v_request_sha256, p_start_request_document,
        v_result_sha256, p_start_result_document, v_reconciliation_sha256,
        p_start_reconciliation_document, v_provider_run_id, v_status, p_available_at,
        p_registered_by, p_registered_at, p_registered_at
    ) RETURNING agentops_temporal_start_target.target_id INTO v_target_id;
    PERFORM set_config('gda.agentops_temporal_start_target_write_allowed', '0', true);
    RETURN QUERY SELECT v_target_id, TRUE;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.agentops_temporal_start_target_write_allowed', '0', true);
    RAISE;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.claim_agentops_temporal_start_targets(
    p_tenant_id TEXT,
    p_namespace_ref TEXT,
    p_worker_id TEXT,
    p_limit INTEGER DEFAULT 10,
    p_lease_seconds INTEGER DEFAULT 60
)
RETURNS SETOF gda_control.agentops_temporal_start_target
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id
       OR p_worker_id !~ '^(workload|agent):[^[:space:]]{1,128}$' THEN
        RAISE EXCEPTION 'Temporal start target worker authority is invalid' USING ERRCODE = '42501';
    END IF;
    IF p_limit NOT BETWEEN 1 AND 100 OR p_lease_seconds NOT BETWEEN 5 AND 3600 THEN
        RAISE EXCEPTION 'Temporal start target claim bounds are invalid' USING ERRCODE = '22023';
    END IF;
    PERFORM set_config('gda.agentops_temporal_start_target_write_allowed', '1', true);
    UPDATE gda_control.agentops_temporal_start_target
       SET status = CASE WHEN provider_run_id IS NULL
                         THEN 'pending_start_reconciliation' ELSE 'ready' END,
           claimed_by = NULL, claimed_until = NULL, available_at = clock_timestamp(),
           updated_at = clock_timestamp(),
           last_error = COALESCE(last_error, 'target claim lease expired')
     WHERE tenant_id = p_tenant_id AND status = 'claimed'
       AND claimed_until <= clock_timestamp();
    RETURN QUERY
    WITH due AS (
        SELECT target_id
          FROM gda_control.agentops_temporal_start_target
         WHERE tenant_id = p_tenant_id
           AND status IN ('pending_start_reconciliation', 'ready')
           AND (p_namespace_ref IS NULL OR namespace_ref = p_namespace_ref)
           AND available_at <= clock_timestamp()
         ORDER BY available_at, registered_at, target_id
         FOR UPDATE SKIP LOCKED LIMIT p_limit
    )
    UPDATE gda_control.agentops_temporal_start_target AS target
       SET status = 'claimed', attempt_count = target.attempt_count + 1,
           claimed_by = p_worker_id,
           claimed_until = clock_timestamp() + make_interval(secs => p_lease_seconds),
           updated_at = clock_timestamp(), last_error = NULL
      FROM due
     WHERE target.tenant_id = p_tenant_id AND target.target_id = due.target_id
    RETURNING target.*;
    PERFORM set_config('gda.agentops_temporal_start_target_write_allowed', '0', true);
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.agentops_temporal_start_target_write_allowed', '0', true);
    RAISE;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.release_agentops_temporal_start_target_claim(
    p_tenant_id TEXT, p_target_id UUID, p_worker_id TEXT, p_error TEXT,
    p_available_at TIMESTAMPTZ
)
RETURNS SETOF gda_control.agentops_temporal_start_target
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, gda_control SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id
       OR p_worker_id !~ '^(workload|agent):[^[:space:]]{1,128}$'
       OR NULLIF(btrim(p_error), '') IS NULL OR p_available_at IS NULL THEN
        RAISE EXCEPTION 'Temporal start target retry authority is invalid' USING ERRCODE = '22023';
    END IF;
    PERFORM set_config('gda.agentops_temporal_start_target_write_allowed', '1', true);
    RETURN QUERY UPDATE gda_control.agentops_temporal_start_target
       SET status = CASE WHEN provider_run_id IS NULL
                         THEN 'pending_start_reconciliation' ELSE 'ready' END,
           claimed_by = NULL, claimed_until = NULL, available_at = p_available_at,
           last_error = left(p_error, 2000), updated_at = clock_timestamp()
     WHERE tenant_id = p_tenant_id AND target_id = p_target_id
       AND status = 'claimed' AND claimed_by = p_worker_id
       AND claimed_until > clock_timestamp()
    RETURNING gda_control.agentops_temporal_start_target.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Temporal start target cannot be retried by this worker' USING ERRCODE = '40001';
    END IF;
    PERFORM set_config('gda.agentops_temporal_start_target_write_allowed', '0', true);
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.agentops_temporal_start_target_write_allowed', '0', true);
    RAISE;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.renew_agentops_temporal_start_target_claim(
    p_tenant_id TEXT, p_target_id UUID, p_worker_id TEXT, p_lease_seconds INTEGER DEFAULT 60
)
RETURNS SETOF gda_control.agentops_temporal_start_target
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, gda_control SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id
       OR p_worker_id !~ '^(workload|agent):[^[:space:]]{1,128}$'
       OR p_lease_seconds NOT BETWEEN 5 AND 3600 THEN
        RAISE EXCEPTION 'Temporal start target renewal authority is invalid' USING ERRCODE = '42501';
    END IF;
    PERFORM set_config('gda.agentops_temporal_start_target_write_allowed', '1', true);
    RETURN QUERY UPDATE gda_control.agentops_temporal_start_target
       SET claimed_until = clock_timestamp() + make_interval(secs => p_lease_seconds),
           updated_at = clock_timestamp()
     WHERE tenant_id = p_tenant_id AND target_id = p_target_id
       AND status = 'claimed' AND claimed_by = p_worker_id
       AND claimed_until > clock_timestamp()
    RETURNING gda_control.agentops_temporal_start_target.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Temporal start target claim is stale or not owned' USING ERRCODE = '40001';
    END IF;
    PERFORM set_config('gda.agentops_temporal_start_target_write_allowed', '0', true);
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.agentops_temporal_start_target_write_allowed', '0', true);
    RAISE;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.attach_agentops_temporal_start_target_run(
    p_tenant_id TEXT, p_target_id UUID, p_worker_id TEXT, p_provider_run_id TEXT,
    p_start_reconciliation_document JSONB, p_start_reconciliation_fingerprint_payload TEXT
)
RETURNS SETOF gda_control.agentops_temporal_start_target
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public SET row_security = on
AS $$
DECLARE
    v_target gda_control.agentops_temporal_start_target%ROWTYPE;
    v_reconciliation_sha256 TEXT;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id
       OR p_worker_id !~ '^(workload|agent):[^[:space:]]{1,128}$'
       OR NULLIF(btrim(p_provider_run_id), '') IS NULL
       OR p_start_reconciliation_document IS NULL
       OR p_start_reconciliation_fingerprint_payload IS NULL THEN
        RAISE EXCEPTION 'Temporal start target run attachment is invalid' USING ERRCODE = '22023';
    END IF;
    SELECT target.* INTO v_target
      FROM gda_control.agentops_temporal_start_target AS target
     WHERE target.tenant_id = p_tenant_id AND target.target_id = p_target_id
     FOR UPDATE;
    IF NOT FOUND OR v_target.status <> 'claimed'
       OR v_target.claimed_by IS DISTINCT FROM p_worker_id
       OR v_target.claimed_until <= clock_timestamp()
       OR v_target.provider_run_id IS NOT NULL THEN
        RAISE EXCEPTION 'Temporal start target is not held by this worker' USING ERRCODE = '40001';
    END IF;
    v_reconciliation_sha256 := p_start_reconciliation_document ->> 'reconciliation_sha256';
    IF v_target.start_result_document ->> 'status' <> 'unknown'
       OR v_target.start_reconciliation_document IS NOT NULL
          AND v_target.start_reconciliation_document ->> 'verdict' <> 'unknown_pending'
       OR p_start_reconciliation_document ->> 'tenant_id' IS DISTINCT FROM v_target.tenant_id::TEXT
       OR p_start_reconciliation_document ->> 'namespace_ref' IS DISTINCT FROM v_target.namespace_ref
       OR p_start_reconciliation_document ->> 'workflow_id' IS DISTINCT FROM v_target.workflow_id
       OR p_start_reconciliation_document ->> 'provider_status' <> 'unknown'
       OR p_start_reconciliation_document ->> 'verdict' <> 'already_exists_matched'
       OR p_start_reconciliation_document ->> 'request_sha256' IS DISTINCT FROM v_target.start_request_sha256
       OR p_start_reconciliation_document ->> 'provider_receipt_ref' IS DISTINCT FROM
            v_target.start_result_document ->> 'provider_receipt_ref'
       OR p_start_reconciliation_document ->> 'observed_input_sha256' IS DISTINCT FROM
            v_target.start_request_sha256
       OR p_start_reconciliation_document ->> 'provider_run_id' IS DISTINCT FROM p_provider_run_id
       OR v_reconciliation_sha256 !~ '^[0-9a-f]{64}$'
       OR p_start_reconciliation_fingerprint_payload::JSONB IS DISTINCT FROM jsonb_build_object(
            'schema', 'gda.temporal_start_reconciliation.v1',
            'data', p_start_reconciliation_document - 'reconciliation_sha256'
       )
       OR encode(public.digest(convert_to(p_start_reconciliation_fingerprint_payload, 'UTF8'), 'sha256'), 'hex')
            IS DISTINCT FROM v_reconciliation_sha256 THEN
        RAISE EXCEPTION 'Temporal start target run attachment evidence is invalid' USING ERRCODE = '22023';
    END IF;
    PERFORM set_config('gda.agentops_temporal_start_target_write_allowed', '1', true);
    RETURN QUERY UPDATE gda_control.agentops_temporal_start_target
       SET provider_run_id = p_provider_run_id,
           start_reconciliation_sha256 = v_reconciliation_sha256,
           start_reconciliation_document = p_start_reconciliation_document,
           updated_at = clock_timestamp()
     WHERE tenant_id = p_tenant_id AND target_id = p_target_id
    RETURNING gda_control.agentops_temporal_start_target.*;
    PERFORM set_config('gda.agentops_temporal_start_target_write_allowed', '0', true);
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.agentops_temporal_start_target_write_allowed', '0', true);
    RAISE;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.complete_agentops_temporal_start_target(
    p_tenant_id TEXT, p_target_id UUID, p_worker_id TEXT
)
RETURNS SETOF gda_control.agentops_temporal_start_target
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, gda_control SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id
       OR p_worker_id !~ '^(workload|agent):[^[:space:]]{1,128}$' THEN
        RAISE EXCEPTION 'Temporal start target completion authority is invalid' USING ERRCODE = '42501';
    END IF;
    PERFORM set_config('gda.agentops_temporal_start_target_write_allowed', '1', true);
    RETURN QUERY UPDATE gda_control.agentops_temporal_start_target
       SET status = 'completed', claimed_by = NULL, claimed_until = NULL,
           completed_at = clock_timestamp(), updated_at = clock_timestamp()
     WHERE tenant_id = p_tenant_id AND target_id = p_target_id
       AND status = 'claimed' AND claimed_by = p_worker_id
       AND claimed_until > clock_timestamp()
       AND provider_run_id IS NOT NULL AND start_reconciliation_document IS NOT NULL
    RETURNING gda_control.agentops_temporal_start_target.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Temporal start target cannot be completed by this worker' USING ERRCODE = '40001';
    END IF;
    PERFORM set_config('gda.agentops_temporal_start_target_write_allowed', '0', true);
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.agentops_temporal_start_target_write_allowed', '0', true);
    RAISE;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.fail_agentops_temporal_start_target(
    p_tenant_id TEXT, p_target_id UUID, p_worker_id TEXT, p_error TEXT
)
RETURNS SETOF gda_control.agentops_temporal_start_target
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, gda_control SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id
       OR p_worker_id !~ '^(workload|agent):[^[:space:]]{1,128}$'
       OR NULLIF(btrim(p_error), '') IS NULL THEN
        RAISE EXCEPTION 'Temporal start target failure authority is invalid' USING ERRCODE = '22023';
    END IF;
    PERFORM set_config('gda.agentops_temporal_start_target_write_allowed', '1', true);
    RETURN QUERY UPDATE gda_control.agentops_temporal_start_target
       SET status = 'failed', claimed_by = NULL, claimed_until = NULL,
           last_error = left(p_error, 2000), completed_at = clock_timestamp(),
           updated_at = clock_timestamp()
     WHERE tenant_id = p_tenant_id AND target_id = p_target_id
       AND status = 'claimed' AND claimed_by = p_worker_id
       AND claimed_until > clock_timestamp()
    RETURNING gda_control.agentops_temporal_start_target.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Temporal start target cannot be failed by this worker' USING ERRCODE = '40001';
    END IF;
    PERFORM set_config('gda.agentops_temporal_start_target_write_allowed', '0', true);
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.agentops_temporal_start_target_write_allowed', '0', true);
    RAISE;
END;
$$;

CREATE OR REPLACE VIEW gda_control.agentops_temporal_start_target_current
WITH (security_invoker = true) AS
SELECT * FROM gda_control.agentops_temporal_start_target;

DROP TRIGGER IF EXISTS trg_gda_agentops_temporal_start_target_guard
    ON gda_control.agentops_temporal_start_target;
CREATE TRIGGER trg_gda_agentops_temporal_start_target_guard
BEFORE INSERT OR UPDATE OR DELETE ON gda_control.agentops_temporal_start_target
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_agentops_temporal_start_target();

ALTER TABLE gda_control.agentops_temporal_start_target ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.agentops_temporal_start_target FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.agentops_temporal_start_target;
CREATE POLICY tenant_isolation ON gda_control.agentops_temporal_start_target
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.agentops_temporal_start_target FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.agentops_temporal_start_target TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.guard_agentops_temporal_start_target() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.register_agentops_temporal_start_target(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, JSONB, TEXT, JSONB, TEXT, TEXT, TIMESTAMPTZ, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.claim_agentops_temporal_start_targets(TEXT, TEXT, TEXT, INTEGER, INTEGER)
    TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.renew_agentops_temporal_start_target_claim(TEXT, UUID, TEXT, INTEGER)
    TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.attach_agentops_temporal_start_target_run(TEXT, UUID, TEXT, TEXT, JSONB, TEXT)
    TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.complete_agentops_temporal_start_target(TEXT, UUID, TEXT)
    TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.fail_agentops_temporal_start_target(TEXT, UUID, TEXT, TEXT)
    TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.release_agentops_temporal_start_target_claim(TEXT, UUID, TEXT, TEXT, TIMESTAMPTZ)
    TO gda_control_gateway;
