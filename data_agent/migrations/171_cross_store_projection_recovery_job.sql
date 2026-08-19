-- 171: Durable leased jobs for cross-store projection recovery workers.

CREATE TABLE IF NOT EXISTS gda_control.cross_store_projection_recovery_job (
    tenant_id TEXT NOT NULL,
    job_id UUID NOT NULL,
    plan_sha256 CHAR(64) NOT NULL,
    plan_idempotency_key CHAR(64) NOT NULL,
    projection_id TEXT NOT NULL,
    target_engine TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    plan_document JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    next_action TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    claimed_by TEXT,
    lease_expires_at TIMESTAMPTZ,
    lease_generation BIGINT NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    submitted_by TEXT NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    resumed_by TEXT,
    resumed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    completed_at TIMESTAMPTZ,
    snapshot_sha256 CHAR(64),
    error_code TEXT,
    error_message TEXT,
    PRIMARY KEY (tenant_id, job_id),
    CONSTRAINT uq_gda_projection_recovery_job_plan
        UNIQUE (tenant_id, plan_sha256),
    CONSTRAINT ck_gda_projection_recovery_job_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_projection_recovery_job_plan
        CHECK (plan_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_projection_recovery_job_idempotency
        CHECK (plan_idempotency_key ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_projection_recovery_job_projection
        CHECK (projection_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'),
    CONSTRAINT ck_gda_projection_recovery_job_engine
        CHECK (target_engine IN ('postgis', 'rdf', 'vector', 'object_store', 'lakehouse')),
    CONSTRAINT ck_gda_projection_recovery_job_target
        CHECK (NULLIF(btrim(target_ref), '') IS NOT NULL AND octet_length(target_ref) <= 512),
    CONSTRAINT ck_gda_projection_recovery_job_plan_document
        CHECK (
            jsonb_typeof(plan_document) = 'object'
            AND plan_document ->> 'tenant_id' = tenant_id
            AND plan_document ->> 'projection_id' = projection_id
            AND plan_document ->> 'target_engine' = target_engine
            AND plan_document ->> 'target_ref' = target_ref
            AND plan_document ->> 'plan_sha256' = plan_sha256
            AND plan_document ->> 'plan_idempotency_key' = plan_idempotency_key
        ),
    CONSTRAINT ck_gda_projection_recovery_job_status
        CHECK (status IN ('queued', 'running', 'waiting_operator', 'succeeded', 'failed')),
    CONSTRAINT ck_gda_projection_recovery_job_action
        CHECK (
            next_action IS NULL OR next_action IN (
                'execute_provider', 'retry_authority', 'reobserve_target',
                'manual_compensation', 'none'
            )
        ),
    CONSTRAINT ck_gda_projection_recovery_job_attempts
        CHECK (
            attempt_count >= 0
            AND max_attempts BETWEEN 1 AND 100
            AND lease_generation >= 0
        ),
    CONSTRAINT ck_gda_projection_recovery_job_claim
        CHECK ((claimed_by IS NULL) = (lease_expires_at IS NULL)),
    CONSTRAINT ck_gda_projection_recovery_job_claimed_by
        CHECK (claimed_by IS NULL OR claimed_by ~ '^worker:[A-Za-z0-9][A-Za-z0-9._:-]{0,246}$'),
    CONSTRAINT ck_gda_projection_recovery_job_submitted_by
        CHECK (submitted_by ~ '^(human|agent|workload):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_projection_recovery_job_resumed_by
        CHECK (
            resumed_by IS NULL
            OR resumed_by ~ '^(human|agent|workload):[^[:space:]]{1,128}$'
        ),
    CONSTRAINT ck_gda_projection_recovery_job_resume_evidence
        CHECK ((resumed_by IS NULL) = (resumed_at IS NULL)),
    CONSTRAINT ck_gda_projection_recovery_job_snapshot
        CHECK (snapshot_sha256 IS NULL OR snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_projection_recovery_job_terminal
        CHECK (
            (status IN ('succeeded', 'failed')) = (completed_at IS NOT NULL)
            AND (status = 'running') = (claimed_by IS NOT NULL)
        ),
    CONSTRAINT ck_gda_projection_recovery_job_success
        CHECK (
            status <> 'succeeded'
            OR (next_action = 'none' AND snapshot_sha256 IS NOT NULL)
        ),
    CONSTRAINT ck_gda_projection_recovery_job_waiting
        CHECK (status <> 'waiting_operator' OR next_action = 'manual_compensation')
);

CREATE INDEX IF NOT EXISTS idx_gda_projection_recovery_job_claim
    ON gda_control.cross_store_projection_recovery_job
        (tenant_id, status, available_at, submitted_at);
CREATE INDEX IF NOT EXISTS idx_gda_projection_recovery_job_lease
    ON gda_control.cross_store_projection_recovery_job
        (tenant_id, lease_expires_at)
    WHERE status = 'running';

CREATE OR REPLACE FUNCTION gda_control.guard_cross_store_projection_recovery_job_write()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_tenant_id TEXT;
BEGIN
    IF COALESCE(
        current_setting('gda.cross_store_projection_recovery_job_write_allowed', true),
        ''
    ) <> '1' THEN
        RAISE EXCEPTION 'use governed projection recovery job functions'
            USING ERRCODE = '55000';
    END IF;
    v_tenant_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.tenant_id ELSE NEW.tenant_id END;
    IF gda_control.current_tenant() IS NULL
       OR v_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'projection recovery job tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.enqueue_cross_store_projection_recovery_job(
    p_tenant_id TEXT,
    p_job_id UUID,
    p_plan_sha256 TEXT,
    p_plan_idempotency_key TEXT,
    p_projection_id TEXT,
    p_target_engine TEXT,
    p_target_ref TEXT,
    p_plan_document JSONB,
    p_submitted_by TEXT,
    p_max_attempts INTEGER DEFAULT 5
)
RETURNS SETOF gda_control.cross_store_projection_recovery_job
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_job gda_control.cross_store_projection_recovery_job%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'projection recovery job tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_plan_document IS NULL OR jsonb_typeof(p_plan_document) <> 'object'
       OR p_plan_document ->> 'tenant_id' IS DISTINCT FROM p_tenant_id
       OR p_plan_document ->> 'projection_id' IS DISTINCT FROM p_projection_id
       OR p_plan_document ->> 'target_engine' IS DISTINCT FROM p_target_engine
       OR p_plan_document ->> 'target_ref' IS DISTINCT FROM p_target_ref
       OR p_plan_document ->> 'plan_sha256' IS DISTINCT FROM p_plan_sha256
       OR p_plan_document ->> 'plan_idempotency_key'
            IS DISTINCT FROM p_plan_idempotency_key THEN
        RAISE EXCEPTION 'projection recovery job plan identity is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended('projection-recovery-job|' || p_tenant_id || '|' || p_plan_sha256, 0)
    );
    SELECT job.* INTO v_job
    FROM gda_control.cross_store_projection_recovery_job AS job
    WHERE job.tenant_id = p_tenant_id AND job.plan_sha256 = p_plan_sha256;
    IF FOUND THEN
        IF v_job.job_id IS DISTINCT FROM p_job_id
           OR v_job.plan_idempotency_key IS DISTINCT FROM p_plan_idempotency_key
           OR v_job.projection_id IS DISTINCT FROM p_projection_id
           OR v_job.target_engine IS DISTINCT FROM p_target_engine
           OR v_job.target_ref IS DISTINCT FROM p_target_ref
           OR v_job.plan_document IS DISTINCT FROM p_plan_document
           OR v_job.submitted_by IS DISTINCT FROM p_submitted_by
           OR v_job.max_attempts IS DISTINCT FROM p_max_attempts THEN
            RAISE EXCEPTION 'projection recovery job idempotency evidence differs'
                USING ERRCODE = '40001';
        END IF;
        RETURN NEXT v_job;
        RETURN;
    END IF;

    PERFORM set_config('gda.cross_store_projection_recovery_job_write_allowed', '1', true);
    INSERT INTO gda_control.cross_store_projection_recovery_job (
        tenant_id, job_id, plan_sha256, plan_idempotency_key,
        projection_id, target_engine, target_ref, plan_document,
        submitted_by, max_attempts
    ) VALUES (
        p_tenant_id, p_job_id, p_plan_sha256, p_plan_idempotency_key,
        p_projection_id, p_target_engine, p_target_ref, p_plan_document,
        p_submitted_by, p_max_attempts
    ) RETURNING * INTO v_job;
    PERFORM set_config('gda.cross_store_projection_recovery_job_write_allowed', '0', true);
    RETURN NEXT v_job;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.cross_store_projection_recovery_job_write_allowed', '0', true);
    RAISE;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.claim_cross_store_projection_recovery_jobs(
    p_tenant_id TEXT,
    p_worker_id TEXT,
    p_limit INTEGER DEFAULT 1,
    p_lease_seconds INTEGER DEFAULT 120
)
RETURNS SETOF gda_control.cross_store_projection_recovery_job
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'projection recovery job tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_worker_id IS NULL
       OR p_worker_id !~ '^worker:[A-Za-z0-9][A-Za-z0-9._:-]{0,246}$'
       OR p_limit NOT BETWEEN 1 AND 100
       OR p_lease_seconds NOT BETWEEN 5 AND 3600 THEN
        RAISE EXCEPTION 'projection recovery job claim parameters are invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM set_config('gda.cross_store_projection_recovery_job_write_allowed', '1', true);
    UPDATE gda_control.cross_store_projection_recovery_job AS job
       SET status = CASE
               WHEN job.attempt_count >= job.max_attempts THEN 'failed'
               ELSE 'queued'
           END,
           claimed_by = NULL,
           lease_expires_at = NULL,
           available_at = clock_timestamp(),
           completed_at = CASE
               WHEN job.attempt_count >= job.max_attempts THEN clock_timestamp()
               ELSE NULL
           END,
           error_code = CASE
               WHEN job.attempt_count >= job.max_attempts THEN 'recovery_attempts_exhausted'
               ELSE job.error_code
           END,
           error_message = CASE
               WHEN job.attempt_count >= job.max_attempts THEN 'recovery worker lease expired at max attempts'
               ELSE job.error_message
           END,
           updated_at = clock_timestamp()
     WHERE job.tenant_id = p_tenant_id
       AND job.status = 'running'
       AND job.lease_expires_at <= clock_timestamp();

    RETURN QUERY
    WITH candidates AS (
        SELECT job.tenant_id, job.job_id
        FROM gda_control.cross_store_projection_recovery_job AS job
        WHERE job.tenant_id = p_tenant_id
          AND job.status = 'queued'
          AND job.available_at <= clock_timestamp()
          AND job.attempt_count < job.max_attempts
        ORDER BY job.available_at, job.submitted_at, job.job_id
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    )
    UPDATE gda_control.cross_store_projection_recovery_job AS job
       SET status = 'running',
           claimed_by = p_worker_id,
           lease_expires_at = clock_timestamp()
                + make_interval(secs => p_lease_seconds),
           lease_generation = job.lease_generation + 1,
           attempt_count = job.attempt_count + 1,
           updated_at = clock_timestamp(),
           completed_at = NULL
      FROM candidates
     WHERE job.tenant_id = candidates.tenant_id
       AND job.job_id = candidates.job_id
    RETURNING job.*;
    PERFORM set_config('gda.cross_store_projection_recovery_job_write_allowed', '0', true);
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.cross_store_projection_recovery_job_write_allowed', '0', true);
    RAISE;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.renew_cross_store_projection_recovery_job_lease(
    p_tenant_id TEXT,
    p_job_id UUID,
    p_worker_id TEXT,
    p_lease_generation BIGINT,
    p_lease_seconds INTEGER DEFAULT 120
)
RETURNS SETOF gda_control.cross_store_projection_recovery_job
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant()
       OR p_lease_generation < 1
       OR p_lease_seconds NOT BETWEEN 5 AND 3600 THEN
        RAISE EXCEPTION 'projection recovery lease parameters are invalid'
            USING ERRCODE = '22023';
    END IF;
    PERFORM set_config('gda.cross_store_projection_recovery_job_write_allowed', '1', true);
    RETURN QUERY
    UPDATE gda_control.cross_store_projection_recovery_job AS job
       SET lease_expires_at = clock_timestamp()
                + make_interval(secs => p_lease_seconds),
           updated_at = clock_timestamp()
     WHERE job.tenant_id = p_tenant_id
       AND job.job_id = p_job_id
       AND job.status = 'running'
       AND job.claimed_by = p_worker_id
       AND job.lease_generation = p_lease_generation
       AND job.lease_expires_at > clock_timestamp()
    RETURNING job.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'projection recovery job lease is stale or missing'
            USING ERRCODE = '40001';
    END IF;
    PERFORM set_config('gda.cross_store_projection_recovery_job_write_allowed', '0', true);
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.cross_store_projection_recovery_job_write_allowed', '0', true);
    RAISE;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.finish_cross_store_projection_recovery_job(
    p_tenant_id TEXT,
    p_job_id UUID,
    p_worker_id TEXT,
    p_lease_generation BIGINT,
    p_status TEXT,
    p_next_action TEXT,
    p_snapshot_sha256 TEXT,
    p_error_code TEXT,
    p_error_message TEXT,
    p_retry_delay_seconds INTEGER DEFAULT 30
)
RETURNS SETOF gda_control.cross_store_projection_recovery_job
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_job gda_control.cross_store_projection_recovery_job%ROWTYPE;
    v_status TEXT := p_status;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'projection recovery job tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_status NOT IN ('queued', 'waiting_operator', 'succeeded', 'failed')
       OR p_retry_delay_seconds NOT BETWEEN 0 AND 86400
       OR (p_snapshot_sha256 IS NOT NULL
           AND p_snapshot_sha256 !~ '^[0-9a-f]{64}$')
       OR (p_status = 'succeeded'
           AND (p_next_action IS DISTINCT FROM 'none' OR p_snapshot_sha256 IS NULL))
       OR (p_status = 'waiting_operator'
           AND p_next_action IS DISTINCT FROM 'manual_compensation') THEN
        RAISE EXCEPTION 'projection recovery job completion evidence is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT job.* INTO v_job
    FROM gda_control.cross_store_projection_recovery_job AS job
    WHERE job.tenant_id = p_tenant_id AND job.job_id = p_job_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'projection recovery job was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_job.status <> 'running'
       OR v_job.claimed_by IS DISTINCT FROM p_worker_id
       OR v_job.lease_generation IS DISTINCT FROM p_lease_generation
       OR v_job.lease_expires_at <= clock_timestamp() THEN
        RAISE EXCEPTION 'projection recovery job lease is stale or missing'
            USING ERRCODE = '40001';
    END IF;
    IF v_status = 'queued' AND v_job.attempt_count >= v_job.max_attempts THEN
        v_status := 'failed';
    END IF;

    PERFORM set_config('gda.cross_store_projection_recovery_job_write_allowed', '1', true);
    UPDATE gda_control.cross_store_projection_recovery_job AS job
       SET status = v_status,
           next_action = p_next_action,
           snapshot_sha256 = p_snapshot_sha256,
           claimed_by = NULL,
           lease_expires_at = NULL,
           available_at = CASE
               WHEN v_status = 'queued' THEN clock_timestamp()
                    + make_interval(secs => p_retry_delay_seconds)
               ELSE job.available_at
           END,
           completed_at = CASE
               WHEN v_status IN ('succeeded', 'failed') THEN clock_timestamp()
               ELSE NULL
           END,
           error_code = CASE
               WHEN v_status = 'succeeded' THEN NULL
               WHEN v_status = 'failed' AND p_error_code IS NULL
                   THEN 'recovery_attempts_exhausted'
               ELSE p_error_code
           END,
           error_message = CASE
               WHEN v_status = 'succeeded' THEN NULL
               WHEN v_status = 'failed' AND p_error_message IS NULL
                   THEN 'projection recovery attempts exhausted'
               ELSE p_error_message
           END,
           updated_at = clock_timestamp()
     WHERE job.tenant_id = p_tenant_id AND job.job_id = p_job_id
    RETURNING * INTO v_job;
    PERFORM set_config('gda.cross_store_projection_recovery_job_write_allowed', '0', true);
    RETURN NEXT v_job;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.cross_store_projection_recovery_job_write_allowed', '0', true);
    RAISE;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.resume_cross_store_projection_recovery_job(
    p_tenant_id TEXT,
    p_job_id UUID,
    p_requested_by TEXT
)
RETURNS SETOF gda_control.cross_store_projection_recovery_job
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_job gda_control.cross_store_projection_recovery_job%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'projection recovery job tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_requested_by IS NULL
       OR p_requested_by !~ '^(human|agent|workload):[^[:space:]]{1,128}$' THEN
        RAISE EXCEPTION 'projection recovery resume actor is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT job.* INTO v_job
    FROM gda_control.cross_store_projection_recovery_job AS job
    WHERE job.tenant_id = p_tenant_id AND job.job_id = p_job_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'projection recovery job was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_job.status <> 'waiting_operator' THEN
        RAISE EXCEPTION 'only waiting projection recovery jobs may be resumed'
            USING ERRCODE = '40001';
    END IF;
    IF v_job.attempt_count >= 100 THEN
        RAISE EXCEPTION 'projection recovery job reached the absolute attempt limit'
            USING ERRCODE = '40001';
    END IF;
    PERFORM set_config('gda.cross_store_projection_recovery_job_write_allowed', '1', true);
    UPDATE gda_control.cross_store_projection_recovery_job AS job
       SET status = 'queued',
           next_action = NULL,
           max_attempts = GREATEST(job.max_attempts, job.attempt_count + 1),
           available_at = clock_timestamp(),
           resumed_by = p_requested_by,
           resumed_at = clock_timestamp(),
           error_code = NULL,
           error_message = NULL,
           updated_at = clock_timestamp()
     WHERE job.tenant_id = p_tenant_id AND job.job_id = p_job_id
    RETURNING * INTO v_job;
    PERFORM set_config('gda.cross_store_projection_recovery_job_write_allowed', '0', true);
    RETURN NEXT v_job;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.cross_store_projection_recovery_job_write_allowed', '0', true);
    RAISE;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_projection_recovery_job_guard
    ON gda_control.cross_store_projection_recovery_job;
CREATE TRIGGER trg_gda_projection_recovery_job_guard
BEFORE INSERT OR UPDATE OR DELETE ON gda_control.cross_store_projection_recovery_job
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_cross_store_projection_recovery_job_write();

ALTER TABLE gda_control.cross_store_projection_recovery_job ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.cross_store_projection_recovery_job FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.cross_store_projection_recovery_job;
CREATE POLICY tenant_isolation ON gda_control.cross_store_projection_recovery_job
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.cross_store_projection_recovery_job
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.cross_store_projection_recovery_job
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.guard_cross_store_projection_recovery_job_write()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.enqueue_cross_store_projection_recovery_job(
    TEXT, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, INTEGER
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.claim_cross_store_projection_recovery_jobs(
    TEXT, TEXT, INTEGER, INTEGER
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.renew_cross_store_projection_recovery_job_lease(
    TEXT, UUID, TEXT, BIGINT, INTEGER
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.finish_cross_store_projection_recovery_job(
    TEXT, UUID, TEXT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.resume_cross_store_projection_recovery_job(
    TEXT, UUID, TEXT
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION gda_control.enqueue_cross_store_projection_recovery_job(
    TEXT, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, INTEGER
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.claim_cross_store_projection_recovery_jobs(
    TEXT, TEXT, INTEGER, INTEGER
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.renew_cross_store_projection_recovery_job_lease(
    TEXT, UUID, TEXT, BIGINT, INTEGER
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.finish_cross_store_projection_recovery_job(
    TEXT, UUID, TEXT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.resume_cross_store_projection_recovery_job(
    TEXT, UUID, TEXT
) TO gda_control_gateway;
