-- 167: Recoverable asynchronous jobs for Chongqing package reconciliation.

CREATE TABLE IF NOT EXISTS gda_control.chongqing_data_package_reconciliation_job (
    tenant_id TEXT NOT NULL,
    job_id UUID NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    request_document JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    phase TEXT NOT NULL DEFAULT 'queued',
    phase_detail TEXT NOT NULL DEFAULT 'queued',
    phase_completed INTEGER NOT NULL DEFAULT 0,
    phase_total INTEGER NOT NULL DEFAULT 1,
    progress_percent INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    available_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    claimed_by TEXT,
    lease_expires_at TIMESTAMPTZ,
    submitted_by TEXT NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    started_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    completed_at TIMESTAMPTZ,
    cancel_requested_by TEXT,
    cancel_reason TEXT,
    cancel_requested_at TIMESTAMPTZ,
    response_document JSONB,
    error_code TEXT,
    error_message TEXT,
    PRIMARY KEY (tenant_id, job_id),
    CONSTRAINT uq_gda_cq_package_reconciliation_job_request
        UNIQUE (tenant_id, idempotency_key),
    CONSTRAINT ck_gda_cq_package_reconciliation_job_identity CHECK (
        tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'
        AND idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'
        AND request_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_cq_package_reconciliation_job_documents CHECK (
        jsonb_typeof(request_document) = 'object'
        AND request_document ->> 'schema_id'
            = 'gda.chongqing-data-package-reconciliation-request.v1'
        AND request_document ->> 'tenant_id' = tenant_id
        AND request_document ->> 'idempotency_key' = idempotency_key
        AND request_document ->> 'recorded_by' = submitted_by
        AND (response_document IS NULL OR jsonb_typeof(response_document) = 'object')
    ),
    CONSTRAINT ck_gda_cq_package_reconciliation_job_status CHECK (
        status IN (
            'queued', 'running', 'cancel_requested',
            'cancelled', 'succeeded', 'failed'
        )
    ),
    CONSTRAINT ck_gda_cq_package_reconciliation_job_phase CHECK (
        phase IN (
            'queued', 'planning', 'applying', 'finalizing',
            'completed', 'cancelled', 'failed'
        )
        AND NULLIF(btrim(phase_detail), '') IS NOT NULL
    ),
    CONSTRAINT ck_gda_cq_package_reconciliation_job_progress CHECK (
        phase_completed >= 0
        AND phase_total >= 0
        AND (phase_total = 0 OR phase_completed <= phase_total)
        AND progress_percent BETWEEN 0 AND 100
    ),
    CONSTRAINT ck_gda_cq_package_reconciliation_job_attempts CHECK (
        attempt_count >= 0 AND max_attempts BETWEEN 1 AND 100
    ),
    CONSTRAINT ck_gda_cq_package_reconciliation_job_actors CHECK (
        submitted_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'
        AND (claimed_by IS NULL OR claimed_by ~ '^worker:[^[:space:]]{1,128}$')
        AND (
            cancel_requested_by IS NULL
            OR cancel_requested_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'
        )
    ),
    CONSTRAINT ck_gda_cq_package_reconciliation_job_claim CHECK (
        (claimed_by IS NULL) = (lease_expires_at IS NULL)
    ),
    CONSTRAINT ck_gda_cq_package_reconciliation_job_cancel CHECK (
        (cancel_requested_by IS NULL)
            = (cancel_reason IS NULL)
        AND (cancel_requested_by IS NULL)
            = (cancel_requested_at IS NULL)
    ),
    CONSTRAINT ck_gda_cq_package_reconciliation_job_result CHECK (
        (status = 'succeeded' AND response_document IS NOT NULL)
        OR (status <> 'succeeded' AND response_document IS NULL)
    ),
    CONSTRAINT ck_gda_cq_package_reconciliation_job_state CHECK (
        (status = 'queued'
            AND claimed_by IS NULL
            AND completed_at IS NULL)
        OR (status IN ('running', 'cancel_requested')
            AND claimed_by IS NOT NULL
            AND completed_at IS NULL)
        OR (status IN ('cancelled', 'succeeded', 'failed')
            AND claimed_by IS NULL
            AND completed_at IS NOT NULL)
    ),
    CONSTRAINT ck_gda_cq_package_reconciliation_job_failure CHECK (
        (status = 'failed'
            AND error_code ~ '^[a-z][a-z0-9_]{0,127}$'
            AND NULLIF(btrim(error_message), '') IS NOT NULL)
        OR status <> 'failed'
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_cq_package_reconciliation_job_due
    ON gda_control.chongqing_data_package_reconciliation_job(
        tenant_id, available_at, submitted_at, job_id
    )
    WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS idx_gda_cq_package_reconciliation_job_lease
    ON gda_control.chongqing_data_package_reconciliation_job(
        tenant_id, lease_expires_at
    )
    WHERE status IN ('running', 'cancel_requested');

ALTER TABLE gda_control.chongqing_data_package_reconciliation_job
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.chongqing_data_package_reconciliation_job
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.chongqing_data_package_reconciliation_job;
CREATE POLICY tenant_isolation
    ON gda_control.chongqing_data_package_reconciliation_job
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE OR REPLACE FUNCTION gda_control.enqueue_chongqing_data_package_reconciliation_job(
    p_tenant_id TEXT,
    p_job_id UUID,
    p_idempotency_key TEXT,
    p_request_sha256 TEXT,
    p_submitted_by TEXT,
    p_request_document JSONB
)
RETURNS SETOF gda_control.chongqing_data_package_reconciliation_job
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_existing gda_control.chongqing_data_package_reconciliation_job%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'reconciliation job tenant context mismatch'
            USING ERRCODE = '42501';
    END IF;
    IF p_job_id IS NULL
       OR p_request_sha256 !~ '^[0-9a-f]{64}$'
       OR p_idempotency_key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'
       OR p_submitted_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR jsonb_typeof(p_request_document) <> 'object'
       OR p_request_document ->> 'tenant_id' IS DISTINCT FROM p_tenant_id
       OR p_request_document ->> 'idempotency_key' IS DISTINCT FROM p_idempotency_key
       OR p_request_document ->> 'recorded_by' IS DISTINCT FROM p_submitted_by THEN
        RAISE EXCEPTION 'reconciliation job submission is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'cq-package-reconciliation-job|' || p_tenant_id || '|' ||
            p_idempotency_key,
            0
        )
    );
    SELECT * INTO v_existing
      FROM gda_control.chongqing_data_package_reconciliation_job
     WHERE tenant_id = p_tenant_id AND idempotency_key = p_idempotency_key;
    IF FOUND THEN
        IF v_existing.job_id <> p_job_id
           OR v_existing.request_sha256 <> p_request_sha256
           OR v_existing.request_document <> p_request_document THEN
            RAISE EXCEPTION 'reconciliation job idempotency evidence differs'
                USING ERRCODE = '23505';
        END IF;
        RETURN NEXT v_existing;
        RETURN;
    END IF;

    INSERT INTO gda_control.chongqing_data_package_reconciliation_job (
        tenant_id, job_id, idempotency_key, request_sha256,
        request_document, submitted_by
    ) VALUES (
        p_tenant_id, p_job_id, p_idempotency_key, p_request_sha256,
        p_request_document, p_submitted_by
    )
    RETURNING * INTO v_existing;
    RETURN NEXT v_existing;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.claim_chongqing_data_package_reconciliation_jobs(
    p_tenant_id TEXT,
    p_worker_id TEXT,
    p_limit INTEGER DEFAULT 1,
    p_lease_seconds INTEGER DEFAULT 600
)
RETURNS SETOF gda_control.chongqing_data_package_reconciliation_job
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'reconciliation job tenant context mismatch'
            USING ERRCODE = '42501';
    END IF;
    IF p_worker_id !~ '^worker:[^[:space:]]{1,128}$'
       OR p_limit NOT BETWEEN 1 AND 100
       OR p_lease_seconds NOT BETWEEN 30 AND 3600 THEN
        RAISE EXCEPTION 'reconciliation job claim is invalid'
            USING ERRCODE = '22023';
    END IF;

    UPDATE gda_control.chongqing_data_package_reconciliation_job
       SET status = 'cancelled',
           phase = 'cancelled',
           phase_detail = 'cancelled_after_worker_lease_expired',
           claimed_by = NULL,
           lease_expires_at = NULL,
           updated_at = clock_timestamp(),
           completed_at = clock_timestamp()
     WHERE tenant_id = p_tenant_id
       AND status = 'cancel_requested'
       AND lease_expires_at <= clock_timestamp();

    UPDATE gda_control.chongqing_data_package_reconciliation_job
       SET status = 'failed',
           phase = 'failed',
           phase_detail = 'worker_lease_expired',
           claimed_by = NULL,
           lease_expires_at = NULL,
           error_code = 'worker_lease_expired',
           error_message = 'worker lease expired after maximum attempts',
           updated_at = clock_timestamp(),
           completed_at = clock_timestamp()
     WHERE tenant_id = p_tenant_id
       AND status = 'running'
       AND lease_expires_at <= clock_timestamp()
       AND attempt_count >= max_attempts;

    RETURN QUERY
    WITH candidates AS (
        SELECT job_id
          FROM gda_control.chongqing_data_package_reconciliation_job
         WHERE tenant_id = p_tenant_id
           AND attempt_count < max_attempts
           AND (
               (status = 'queued' AND available_at <= clock_timestamp())
               OR (status = 'running' AND lease_expires_at <= clock_timestamp())
           )
         ORDER BY available_at, submitted_at, job_id
         LIMIT p_limit
         FOR UPDATE SKIP LOCKED
    )
    UPDATE gda_control.chongqing_data_package_reconciliation_job AS job
       SET status = 'running',
           phase = 'planning',
           phase_detail = 'planning',
           phase_completed = 0,
           phase_total = 1,
           progress_percent = 5,
           attempt_count = job.attempt_count + 1,
           claimed_by = p_worker_id,
           lease_expires_at = clock_timestamp()
               + make_interval(secs => p_lease_seconds),
           started_at = COALESCE(job.started_at, clock_timestamp()),
           updated_at = clock_timestamp(),
           completed_at = NULL,
           error_code = NULL,
           error_message = NULL
      FROM candidates
     WHERE job.tenant_id = p_tenant_id
       AND job.job_id = candidates.job_id
    RETURNING job.*;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.checkpoint_chongqing_data_package_reconciliation_job(
    p_tenant_id TEXT,
    p_job_id UUID,
    p_worker_id TEXT,
    p_phase_detail TEXT,
    p_phase_completed INTEGER,
    p_phase_total INTEGER,
    p_lease_seconds INTEGER
)
RETURNS SETOF gda_control.chongqing_data_package_reconciliation_job
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_phase TEXT;
    v_percent INTEGER;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'reconciliation job tenant context mismatch'
            USING ERRCODE = '42501';
    END IF;
    IF COALESCE(btrim(p_phase_detail), '') = ''
       OR p_phase_completed < 0 OR p_phase_total < 0
       OR (p_phase_total > 0 AND p_phase_completed > p_phase_total)
       OR p_lease_seconds NOT BETWEEN 30 AND 3600 THEN
        RAISE EXCEPTION 'reconciliation job checkpoint is invalid'
            USING ERRCODE = '22023';
    END IF;
    v_phase := CASE
        WHEN p_phase_detail = 'planning' THEN 'planning'
        WHEN p_phase_detail LIKE 'apply:%'
          OR p_phase_detail LIKE 'applying:%'
          OR p_phase_detail LIKE 'verify_replay:%'
          OR p_phase_detail = 'applying' THEN 'applying'
        WHEN p_phase_detail = 'finalizing' THEN 'finalizing'
        WHEN p_phase_detail = 'completed' THEN 'completed'
        ELSE NULL
    END;
    IF v_phase IS NULL THEN
        RAISE EXCEPTION 'reconciliation job checkpoint phase is invalid'
            USING ERRCODE = '22023';
    END IF;
    v_percent := CASE v_phase
        WHEN 'planning' THEN 5
        WHEN 'applying' THEN CASE
            WHEN p_phase_total = 0 THEN 90
            ELSE 10 + floor(80.0 * p_phase_completed / p_phase_total)::integer
        END
        WHEN 'finalizing' THEN 95
        WHEN 'completed' THEN 100
    END;

    RETURN QUERY
    UPDATE gda_control.chongqing_data_package_reconciliation_job AS job
       SET phase = CASE
               WHEN job.status = 'cancel_requested' THEN job.phase
               ELSE v_phase END,
           phase_detail = CASE
               WHEN job.status = 'cancel_requested' THEN job.phase_detail
               ELSE left(p_phase_detail, 256) END,
           phase_completed = CASE
               WHEN job.status = 'cancel_requested' THEN job.phase_completed
               ELSE p_phase_completed END,
           phase_total = CASE
               WHEN job.status = 'cancel_requested' THEN job.phase_total
               ELSE p_phase_total END,
           progress_percent = CASE
               WHEN job.status = 'cancel_requested' THEN job.progress_percent
               ELSE v_percent END,
           lease_expires_at = clock_timestamp()
               + make_interval(secs => p_lease_seconds),
           updated_at = clock_timestamp()
     WHERE job.tenant_id = p_tenant_id
       AND job.job_id = p_job_id
       AND job.status IN ('running', 'cancel_requested')
       AND job.claimed_by = p_worker_id
       AND job.lease_expires_at > clock_timestamp()
    RETURNING job.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'reconciliation job claim is missing or expired'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.cancel_chongqing_data_package_reconciliation_job(
    p_tenant_id TEXT,
    p_job_id UUID,
    p_requested_by TEXT,
    p_reason TEXT
)
RETURNS SETOF gda_control.chongqing_data_package_reconciliation_job
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_existing gda_control.chongqing_data_package_reconciliation_job%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'reconciliation job tenant context mismatch'
            USING ERRCODE = '42501';
    END IF;
    IF p_requested_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR length(btrim(p_reason)) NOT BETWEEN 3 AND 1024 THEN
        RAISE EXCEPTION 'reconciliation job cancellation is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_existing
      FROM gda_control.chongqing_data_package_reconciliation_job
     WHERE tenant_id = p_tenant_id AND job_id = p_job_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'reconciliation job was not found' USING ERRCODE = 'P0002';
    END IF;
    IF v_existing.status IN ('cancel_requested', 'cancelled') THEN
        IF v_existing.cancel_requested_by <> p_requested_by
           OR v_existing.cancel_reason <> btrim(p_reason) THEN
            RAISE EXCEPTION 'reconciliation cancellation evidence differs'
                USING ERRCODE = '23505';
        END IF;
        RETURN NEXT v_existing;
        RETURN;
    END IF;
    IF v_existing.status IN ('succeeded', 'failed') THEN
        RETURN NEXT v_existing;
        RETURN;
    END IF;

    UPDATE gda_control.chongqing_data_package_reconciliation_job
       SET status = CASE WHEN status = 'queued' THEN 'cancelled'
                         ELSE 'cancel_requested' END,
           phase = CASE WHEN status = 'queued' THEN 'cancelled'
                        ELSE phase END,
           phase_detail = CASE WHEN status = 'queued' THEN 'cancelled_before_start'
                               ELSE phase_detail END,
           cancel_requested_by = p_requested_by,
           cancel_reason = btrim(p_reason),
           cancel_requested_at = clock_timestamp(),
           updated_at = clock_timestamp(),
           completed_at = CASE WHEN status = 'queued' THEN clock_timestamp()
                               ELSE completed_at END
     WHERE tenant_id = p_tenant_id AND job_id = p_job_id
    RETURNING * INTO v_existing;
    RETURN NEXT v_existing;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.complete_chongqing_data_package_reconciliation_job(
    p_tenant_id TEXT,
    p_job_id UUID,
    p_worker_id TEXT,
    p_response_document JSONB
)
RETURNS SETOF gda_control.chongqing_data_package_reconciliation_job
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'reconciliation job tenant context mismatch'
            USING ERRCODE = '42501';
    END IF;
    IF jsonb_typeof(p_response_document) <> 'object'
       OR p_response_document ->> 'tenant_id' IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'reconciliation job result is invalid'
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    UPDATE gda_control.chongqing_data_package_reconciliation_job AS job
       SET status = 'succeeded',
           phase = 'completed',
           phase_detail = 'completed',
           phase_completed = 1,
           phase_total = 1,
           progress_percent = 100,
           claimed_by = NULL,
           lease_expires_at = NULL,
           response_document = p_response_document,
           error_code = NULL,
           error_message = NULL,
           updated_at = clock_timestamp(),
           completed_at = clock_timestamp()
     WHERE job.tenant_id = p_tenant_id
       AND job.job_id = p_job_id
       AND job.status IN ('running', 'cancel_requested')
       AND job.claimed_by = p_worker_id
       AND job.lease_expires_at > clock_timestamp()
       AND p_response_document ->> 'request_sha256' = job.request_sha256
       AND p_response_document ->> 'idempotency_key' = job.idempotency_key
    RETURNING job.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'reconciliation job completion claim is invalid'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.finish_chongqing_data_package_reconciliation_cancel(
    p_tenant_id TEXT,
    p_job_id UUID,
    p_worker_id TEXT
)
RETURNS SETOF gda_control.chongqing_data_package_reconciliation_job
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'reconciliation job tenant context mismatch'
            USING ERRCODE = '42501';
    END IF;
    RETURN QUERY
    UPDATE gda_control.chongqing_data_package_reconciliation_job AS job
       SET status = 'cancelled',
           phase = 'cancelled',
           phase_detail = 'cancelled_at_atomic_batch_boundary',
           claimed_by = NULL,
           lease_expires_at = NULL,
           updated_at = clock_timestamp(),
           completed_at = clock_timestamp()
     WHERE job.tenant_id = p_tenant_id
       AND job.job_id = p_job_id
       AND job.status = 'cancel_requested'
       AND job.claimed_by = p_worker_id
       AND job.lease_expires_at > clock_timestamp()
    RETURNING job.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'reconciliation cancellation claim is invalid'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.fail_chongqing_data_package_reconciliation_job(
    p_tenant_id TEXT,
    p_job_id UUID,
    p_worker_id TEXT,
    p_error_code TEXT,
    p_error_message TEXT,
    p_retry_delay_seconds INTEGER DEFAULT 30
)
RETURNS SETOF gda_control.chongqing_data_package_reconciliation_job
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'reconciliation job tenant context mismatch'
            USING ERRCODE = '42501';
    END IF;
    IF p_error_code !~ '^[a-z][a-z0-9_]{0,127}$'
       OR COALESCE(btrim(p_error_message), '') = ''
       OR p_retry_delay_seconds NOT BETWEEN 0 AND 86400 THEN
        RAISE EXCEPTION 'reconciliation job failure evidence is invalid'
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    UPDATE gda_control.chongqing_data_package_reconciliation_job AS job
       SET status = CASE
               WHEN job.status = 'cancel_requested' THEN 'cancelled'
               WHEN job.attempt_count >= job.max_attempts THEN 'failed'
               ELSE 'queued' END,
           phase = CASE
               WHEN job.status = 'cancel_requested' THEN 'cancelled'
               WHEN job.attempt_count >= job.max_attempts THEN 'failed'
               ELSE 'queued' END,
           phase_detail = CASE
               WHEN job.status = 'cancel_requested'
                   THEN 'cancelled_after_execution_error'
               WHEN job.attempt_count >= job.max_attempts
                   THEN 'failed_after_max_attempts'
               ELSE 'queued_for_retry' END,
           phase_completed = CASE
               WHEN job.attempt_count >= job.max_attempts THEN job.phase_completed
               ELSE 0 END,
           phase_total = CASE
               WHEN job.attempt_count >= job.max_attempts THEN job.phase_total
               ELSE 1 END,
           progress_percent = CASE
               WHEN job.attempt_count >= job.max_attempts THEN job.progress_percent
               ELSE 0 END,
           claimed_by = NULL,
           lease_expires_at = NULL,
           available_at = CASE
               WHEN job.attempt_count >= job.max_attempts THEN job.available_at
               ELSE clock_timestamp()
                   + make_interval(secs => p_retry_delay_seconds) END,
           error_code = CASE
               WHEN job.status = 'cancel_requested' THEN NULL
               ELSE left(p_error_code, 128) END,
           error_message = CASE
               WHEN job.status = 'cancel_requested' THEN NULL
               ELSE left(p_error_message, 2000) END,
           updated_at = clock_timestamp(),
           completed_at = CASE
               WHEN job.status = 'cancel_requested'
                 OR job.attempt_count >= job.max_attempts
               THEN clock_timestamp() ELSE NULL END
     WHERE job.tenant_id = p_tenant_id
       AND job.job_id = p_job_id
       AND job.status IN ('running', 'cancel_requested')
       AND job.claimed_by = p_worker_id
       AND job.lease_expires_at > clock_timestamp()
    RETURNING job.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'reconciliation job failure claim is invalid'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

REVOKE ALL ON TABLE gda_control.chongqing_data_package_reconciliation_job
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.chongqing_data_package_reconciliation_job
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.enqueue_chongqing_data_package_reconciliation_job(
    TEXT, UUID, TEXT, TEXT, TEXT, JSONB
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.claim_chongqing_data_package_reconciliation_jobs(
    TEXT, TEXT, INTEGER, INTEGER
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.checkpoint_chongqing_data_package_reconciliation_job(
    TEXT, UUID, TEXT, TEXT, INTEGER, INTEGER, INTEGER
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.cancel_chongqing_data_package_reconciliation_job(
    TEXT, UUID, TEXT, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.complete_chongqing_data_package_reconciliation_job(
    TEXT, UUID, TEXT, JSONB
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.finish_chongqing_data_package_reconciliation_cancel(
    TEXT, UUID, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.fail_chongqing_data_package_reconciliation_job(
    TEXT, UUID, TEXT, TEXT, TEXT, INTEGER
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION gda_control.enqueue_chongqing_data_package_reconciliation_job(
    TEXT, UUID, TEXT, TEXT, TEXT, JSONB
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.claim_chongqing_data_package_reconciliation_jobs(
    TEXT, TEXT, INTEGER, INTEGER
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.checkpoint_chongqing_data_package_reconciliation_job(
    TEXT, UUID, TEXT, TEXT, INTEGER, INTEGER, INTEGER
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.cancel_chongqing_data_package_reconciliation_job(
    TEXT, UUID, TEXT, TEXT
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.complete_chongqing_data_package_reconciliation_job(
    TEXT, UUID, TEXT, JSONB
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.finish_chongqing_data_package_reconciliation_cancel(
    TEXT, UUID, TEXT
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.fail_chongqing_data_package_reconciliation_job(
    TEXT, UUID, TEXT, TEXT, TEXT, INTEGER
) TO gda_control_gateway;
