-- 173: Persist compensation execution intent before any provider side effect.
--
-- One consumed ApprovalCase owns one immutable attempt chain. A started event
-- without a terminal event is indeterminate and must never be auto-replayed.

CREATE TABLE IF NOT EXISTS gda_control.cross_store_projection_compensation_event (
    tenant_id TEXT NOT NULL,
    approval_case_ref TEXT NOT NULL,
    event_index SMALLINT NOT NULL,
    compensation_attempt_id UUID NOT NULL,
    job_id UUID NOT NULL,
    resume_snapshot_sha256 CHAR(64) NOT NULL,
    plan_sha256 CHAR(64) NOT NULL,
    plan_idempotency_key CHAR(64) NOT NULL,
    strategy TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    lease_generation BIGINT NOT NULL,
    event_type TEXT NOT NULL,
    provider_commit_ref JSONB,
    receipt_sha256 CHAR(64),
    error_code TEXT,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, approval_case_ref, event_index),
    CONSTRAINT uq_gda_projection_compensation_attempt_event
        UNIQUE (tenant_id, compensation_attempt_id, event_index),
    CONSTRAINT fk_gda_projection_compensation_resume
        FOREIGN KEY (tenant_id, approval_case_ref)
        REFERENCES gda_control.cross_store_projection_recovery_resume_event(
            tenant_id, approval_case_ref
        ),
    CONSTRAINT fk_gda_projection_compensation_job
        FOREIGN KEY (tenant_id, job_id)
        REFERENCES gda_control.cross_store_projection_recovery_job(tenant_id, job_id),
    CONSTRAINT ck_gda_projection_compensation_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_projection_compensation_approval CHECK (
        approval_case_ref ~ (
            '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/'
            || '[a-z0-9][a-z0-9._-]{0,127}$'
        )
        AND split_part(approval_case_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_projection_compensation_snapshot
        CHECK (resume_snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_projection_compensation_plan
        CHECK (plan_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_projection_compensation_idempotency
        CHECK (plan_idempotency_key ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_projection_compensation_strategy
        CHECK (strategy = 'approved_reapply_sealed_plan'),
    CONSTRAINT ck_gda_projection_compensation_worker
        CHECK (worker_id ~ '^worker:[A-Za-z0-9][A-Za-z0-9._:-]{0,246}$'),
    CONSTRAINT ck_gda_projection_compensation_generation
        CHECK (lease_generation >= 1),
    CONSTRAINT ck_gda_projection_compensation_event CHECK (
        (
            event_index = 1
            AND event_type = 'started'
            AND provider_commit_ref IS NULL
            AND receipt_sha256 IS NULL
            AND error_code IS NULL
        ) OR (
            event_index = 2
            AND event_type = 'succeeded'
            AND jsonb_typeof(provider_commit_ref) = 'object'
            AND receipt_sha256 ~ '^[0-9a-f]{64}$'
            AND error_code IS NULL
        ) OR (
            event_index = 2
            AND event_type IN ('failed_known', 'failed_unknown')
            AND provider_commit_ref IS NULL
            AND receipt_sha256 IS NULL
            AND NULLIF(btrim(error_code), '') IS NOT NULL
            AND octet_length(error_code) <= 128
        )
    )
);

CREATE OR REPLACE FUNCTION gda_control.guard_projection_compensation_event_write()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.projection_compensation_event_write_allowed', true),
        ''
    ) <> '1' THEN
        RAISE EXCEPTION 'use governed projection compensation functions'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR COALESCE(NEW.tenant_id, OLD.tenant_id)
            IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'projection compensation tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_projection_compensation_event_guard
    ON gda_control.cross_store_projection_compensation_event;
CREATE TRIGGER trg_gda_projection_compensation_event_guard
BEFORE INSERT OR UPDATE OR DELETE
ON gda_control.cross_store_projection_compensation_event
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_projection_compensation_event_write();

DROP TRIGGER IF EXISTS trg_gda_projection_compensation_event_immutable
    ON gda_control.cross_store_projection_compensation_event;
CREATE TRIGGER trg_gda_projection_compensation_event_immutable
BEFORE UPDATE OR DELETE
ON gda_control.cross_store_projection_compensation_event
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.cross_store_projection_compensation_event
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.cross_store_projection_compensation_event
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.cross_store_projection_compensation_event;
CREATE POLICY tenant_isolation
    ON gda_control.cross_store_projection_compensation_event
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE FUNCTION gda_control.begin_projection_recovery_compensation(
    p_tenant_id TEXT,
    p_job_id UUID,
    p_worker_id TEXT,
    p_lease_generation BIGINT,
    p_approval_case_ref TEXT,
    p_resume_snapshot_sha256 TEXT,
    p_plan_sha256 TEXT,
    p_plan_idempotency_key TEXT,
    p_strategy TEXT,
    p_compensation_attempt_id UUID
)
RETURNS TABLE(
    compensation_attempt_id UUID,
    outcome TEXT,
    provider_commit_ref JSONB,
    receipt_sha256 TEXT,
    error_code TEXT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_job gda_control.cross_store_projection_recovery_job%ROWTYPE;
    v_approval gda_control.approval_case%ROWTYPE;
    v_resume gda_control.cross_store_projection_recovery_resume_event%ROWTYPE;
    v_recovery RECORD;
    v_started gda_control.cross_store_projection_compensation_event%ROWTYPE;
    v_terminal gda_control.cross_store_projection_compensation_event%ROWTYPE;
    v_expected_target TEXT;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'projection compensation tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_worker_id IS NULL
       OR p_worker_id !~ '^worker:[A-Za-z0-9][A-Za-z0-9._:-]{0,246}$'
       OR p_lease_generation < 1
       OR p_approval_case_ref IS NULL
       OR p_resume_snapshot_sha256 !~ '^[0-9a-f]{64}$'
       OR p_plan_sha256 !~ '^[0-9a-f]{64}$'
       OR p_plan_idempotency_key !~ '^[0-9a-f]{64}$'
       OR p_strategy IS DISTINCT FROM 'approved_reapply_sealed_plan'
       OR p_compensation_attempt_id IS NULL THEN
        RAISE EXCEPTION 'projection compensation execution identity is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'projection-compensation|' || p_tenant_id || '|' || p_approval_case_ref,
            0
        )
    );
    SELECT job.* INTO v_job
    FROM gda_control.cross_store_projection_recovery_job AS job
    WHERE job.tenant_id = p_tenant_id AND job.job_id = p_job_id
    FOR UPDATE;
    IF NOT FOUND
       OR v_job.status <> 'running'
       OR v_job.claimed_by IS DISTINCT FROM p_worker_id
       OR v_job.lease_generation IS DISTINCT FROM p_lease_generation
       OR v_job.lease_expires_at <= clock_timestamp()
       OR v_job.resume_approval_case_ref IS DISTINCT FROM p_approval_case_ref
       OR v_job.resume_snapshot_sha256 IS DISTINCT FROM p_resume_snapshot_sha256
       OR v_job.snapshot_sha256 IS DISTINCT FROM p_resume_snapshot_sha256
       OR v_job.plan_sha256 IS DISTINCT FROM p_plan_sha256
       OR v_job.plan_idempotency_key IS DISTINCT FROM p_plan_idempotency_key THEN
        RAISE EXCEPTION 'projection compensation job lease or identity drifted'
            USING ERRCODE = '40001';
    END IF;

    SELECT resume.* INTO v_resume
    FROM gda_control.cross_store_projection_recovery_resume_event AS resume
    WHERE resume.tenant_id = p_tenant_id
      AND resume.approval_case_ref = p_approval_case_ref;
    IF NOT FOUND
       OR v_resume.job_id IS DISTINCT FROM p_job_id
       OR v_resume.resume_snapshot_sha256
            IS DISTINCT FROM p_resume_snapshot_sha256
       OR v_resume.resumed_by IS DISTINCT FROM v_job.resumed_by
       OR v_resume.resumed_at IS DISTINCT FROM v_job.resumed_at
       OR v_resume.resume_reason IS DISTINCT FROM v_job.resume_reason THEN
        RAISE EXCEPTION 'projection compensation resume evidence drifted'
            USING ERRCODE = '23514';
    END IF;

    SELECT recovery.plan_idempotency_key, recovery.projection_id,
           recovery.target_engine, recovery.target_ref,
           recovery.snapshot_sha256, recovery.snapshot_document
      INTO v_recovery
    FROM gda_control.cross_store_projection_recovery_snapshot_current AS recovery
    WHERE recovery.tenant_id = p_tenant_id
      AND recovery.plan_sha256 = p_plan_sha256;
    IF NOT FOUND
       OR v_recovery.plan_idempotency_key
            IS DISTINCT FROM p_plan_idempotency_key
       OR v_recovery.projection_id IS DISTINCT FROM v_job.projection_id
       OR v_recovery.target_engine IS DISTINCT FROM v_job.target_engine
       OR v_recovery.target_ref IS DISTINCT FROM v_job.target_ref
       OR v_recovery.snapshot_sha256
            IS DISTINCT FROM p_resume_snapshot_sha256
       OR v_recovery.snapshot_document ->> 'state' NOT IN (
            'reconciliation_required', 'compensation_required'
       )
       OR v_recovery.snapshot_document ->> 'next_action'
            IS DISTINCT FROM 'manual_compensation' THEN
        RAISE EXCEPTION 'projection compensation durable snapshot drifted'
            USING ERRCODE = '23514';
    END IF;

    SELECT event.* INTO v_started
    FROM gda_control.cross_store_projection_compensation_event AS event
    WHERE event.tenant_id = p_tenant_id
      AND event.approval_case_ref = p_approval_case_ref
      AND event.event_index = 1;
    IF FOUND THEN
        IF v_started.compensation_attempt_id
                IS DISTINCT FROM p_compensation_attempt_id
           OR v_started.job_id IS DISTINCT FROM p_job_id
           OR v_started.resume_snapshot_sha256
                IS DISTINCT FROM p_resume_snapshot_sha256
           OR v_started.plan_sha256 IS DISTINCT FROM p_plan_sha256
           OR v_started.plan_idempotency_key
                IS DISTINCT FROM p_plan_idempotency_key
           OR v_started.strategy IS DISTINCT FROM p_strategy THEN
            RAISE EXCEPTION 'projection compensation attempt evidence differs'
                USING ERRCODE = '40001';
        END IF;
        SELECT event.* INTO v_terminal
        FROM gda_control.cross_store_projection_compensation_event AS event
        WHERE event.tenant_id = p_tenant_id
          AND event.approval_case_ref = p_approval_case_ref
          AND event.event_index = 2;
        IF FOUND THEN
            RETURN QUERY SELECT
                v_started.compensation_attempt_id,
                v_terminal.event_type,
                v_terminal.provider_commit_ref,
                v_terminal.receipt_sha256::TEXT,
                v_terminal.error_code;
        ELSE
            RETURN QUERY SELECT
                v_started.compensation_attempt_id,
                'indeterminate'::TEXT,
                NULL::JSONB,
                NULL::TEXT,
                NULL::TEXT;
        END IF;
        RETURN;
    END IF;

    v_expected_target := format(
        'gda://%s/projection_recovery_job/%s',
        p_tenant_id,
        p_job_id::TEXT
    );
    SELECT approval.* INTO v_approval
    FROM gda_control.approval_case AS approval
    WHERE approval.tenant_id = p_tenant_id
      AND approval.approval_case_ref = p_approval_case_ref;
    IF NOT FOUND
       OR v_approval.status IS DISTINCT FROM 'approved'
       OR clock_timestamp() >= v_approval.expires_at
       OR v_approval.target_resource_urn IS DISTINCT FROM v_expected_target
       OR v_approval.target_fingerprint
            IS DISTINCT FROM p_resume_snapshot_sha256
       OR v_approval.action IS DISTINCT FROM 'projection.recovery.compensate' THEN
        RAISE EXCEPTION 'ApprovalCase no longer authorizes compensation execution'
            USING ERRCODE = '23514';
    END IF;

    PERFORM set_config('gda.projection_compensation_event_write_allowed', '1', true);
    INSERT INTO gda_control.cross_store_projection_compensation_event (
        tenant_id, approval_case_ref, event_index, compensation_attempt_id,
        job_id, resume_snapshot_sha256, plan_sha256, plan_idempotency_key,
        strategy, worker_id, lease_generation, event_type
    ) VALUES (
        p_tenant_id, p_approval_case_ref, 1, p_compensation_attempt_id,
        p_job_id, p_resume_snapshot_sha256, p_plan_sha256,
        p_plan_idempotency_key, p_strategy, p_worker_id,
        p_lease_generation, 'started'
    );
    PERFORM set_config('gda.projection_compensation_event_write_allowed', '0', true);
    RETURN QUERY SELECT
        p_compensation_attempt_id,
        'started'::TEXT,
        NULL::JSONB,
        NULL::TEXT,
        NULL::TEXT;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.projection_compensation_event_write_allowed', '0', true);
    RAISE;
END;
$$;

CREATE FUNCTION gda_control.finish_projection_recovery_compensation(
    p_tenant_id TEXT,
    p_job_id UUID,
    p_worker_id TEXT,
    p_lease_generation BIGINT,
    p_approval_case_ref TEXT,
    p_compensation_attempt_id UUID,
    p_outcome TEXT,
    p_provider_commit_ref JSONB,
    p_receipt_sha256 TEXT,
    p_error_code TEXT
)
RETURNS TABLE(
    compensation_attempt_id UUID,
    outcome TEXT,
    provider_commit_ref JSONB,
    receipt_sha256 TEXT,
    error_code TEXT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_job gda_control.cross_store_projection_recovery_job%ROWTYPE;
    v_started gda_control.cross_store_projection_compensation_event%ROWTYPE;
    v_terminal gda_control.cross_store_projection_compensation_event%ROWTYPE;
    v_recovery RECORD;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'projection compensation tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_outcome NOT IN ('succeeded', 'failed_known', 'failed_unknown')
       OR (
            p_outcome = 'succeeded'
            AND (
                p_provider_commit_ref IS NULL
                OR jsonb_typeof(p_provider_commit_ref) <> 'object'
                OR p_receipt_sha256 !~ '^[0-9a-f]{64}$'
                OR p_error_code IS NOT NULL
            )
       )
       OR (
            p_outcome IN ('failed_known', 'failed_unknown')
            AND (
                p_provider_commit_ref IS NOT NULL
                OR p_receipt_sha256 IS NOT NULL
                OR NULLIF(btrim(p_error_code), '') IS NULL
                OR octet_length(p_error_code) > 128
            )
       ) THEN
        RAISE EXCEPTION 'projection compensation terminal evidence is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'projection-compensation|' || p_tenant_id || '|' || p_approval_case_ref,
            0
        )
    );
    SELECT job.* INTO v_job
    FROM gda_control.cross_store_projection_recovery_job AS job
    WHERE job.tenant_id = p_tenant_id AND job.job_id = p_job_id
    FOR UPDATE;
    IF NOT FOUND
       OR v_job.status <> 'running'
       OR v_job.claimed_by IS DISTINCT FROM p_worker_id
       OR v_job.lease_generation IS DISTINCT FROM p_lease_generation
       OR v_job.lease_expires_at <= clock_timestamp()
       OR v_job.resume_approval_case_ref IS DISTINCT FROM p_approval_case_ref THEN
        RAISE EXCEPTION 'projection compensation terminal lease was lost'
            USING ERRCODE = '40001';
    END IF;

    SELECT recovery.snapshot_sha256 INTO v_recovery
    FROM gda_control.cross_store_projection_recovery_snapshot_current AS recovery
    WHERE recovery.tenant_id = p_tenant_id
      AND recovery.plan_sha256 = v_job.plan_sha256;
    IF NOT FOUND
       OR v_recovery.snapshot_sha256
            IS DISTINCT FROM v_job.resume_snapshot_sha256 THEN
        RAISE EXCEPTION 'projection compensation terminal snapshot drifted'
            USING ERRCODE = '40001';
    END IF;

    SELECT event.* INTO v_started
    FROM gda_control.cross_store_projection_compensation_event AS event
    WHERE event.tenant_id = p_tenant_id
      AND event.approval_case_ref = p_approval_case_ref
      AND event.event_index = 1;
    IF NOT FOUND
       OR v_started.compensation_attempt_id
            IS DISTINCT FROM p_compensation_attempt_id
       OR v_started.job_id IS DISTINCT FROM p_job_id
       OR v_started.resume_snapshot_sha256
            IS DISTINCT FROM v_job.resume_snapshot_sha256
       OR v_started.plan_sha256 IS DISTINCT FROM v_job.plan_sha256
       OR v_started.plan_idempotency_key
            IS DISTINCT FROM v_job.plan_idempotency_key THEN
        RAISE EXCEPTION 'projection compensation start evidence is missing or drifted'
            USING ERRCODE = '23514';
    END IF;

    SELECT event.* INTO v_terminal
    FROM gda_control.cross_store_projection_compensation_event AS event
    WHERE event.tenant_id = p_tenant_id
      AND event.approval_case_ref = p_approval_case_ref
      AND event.event_index = 2;
    IF FOUND THEN
        IF v_terminal.event_type IS DISTINCT FROM p_outcome
           OR v_terminal.provider_commit_ref IS DISTINCT FROM p_provider_commit_ref
           OR v_terminal.receipt_sha256 IS DISTINCT FROM p_receipt_sha256
           OR v_terminal.error_code IS DISTINCT FROM p_error_code THEN
            RAISE EXCEPTION 'projection compensation terminal evidence differs'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT
            v_terminal.compensation_attempt_id,
            v_terminal.event_type,
            v_terminal.provider_commit_ref,
            v_terminal.receipt_sha256::TEXT,
            v_terminal.error_code;
        RETURN;
    END IF;

    PERFORM set_config('gda.projection_compensation_event_write_allowed', '1', true);
    INSERT INTO gda_control.cross_store_projection_compensation_event (
        tenant_id, approval_case_ref, event_index, compensation_attempt_id,
        job_id, resume_snapshot_sha256, plan_sha256, plan_idempotency_key,
        strategy, worker_id, lease_generation, event_type,
        provider_commit_ref, receipt_sha256, error_code
    ) VALUES (
        p_tenant_id, p_approval_case_ref, 2, p_compensation_attempt_id,
        p_job_id, v_started.resume_snapshot_sha256, v_started.plan_sha256,
        v_started.plan_idempotency_key, v_started.strategy, p_worker_id,
        p_lease_generation, p_outcome, p_provider_commit_ref,
        p_receipt_sha256, p_error_code
    ) RETURNING * INTO v_terminal;
    PERFORM set_config('gda.projection_compensation_event_write_allowed', '0', true);
    RETURN QUERY SELECT
        v_terminal.compensation_attempt_id,
        v_terminal.event_type,
        v_terminal.provider_commit_ref,
        v_terminal.receipt_sha256::TEXT,
        v_terminal.error_code;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.projection_compensation_event_write_allowed', '0', true);
    RAISE;
END;
$$;

REVOKE ALL ON TABLE gda_control.cross_store_projection_compensation_event
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.cross_store_projection_compensation_event
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.guard_projection_compensation_event_write()
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.begin_projection_recovery_compensation(
    TEXT, UUID, TEXT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, UUID
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.begin_projection_recovery_compensation(
    TEXT, UUID, TEXT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, UUID
) TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.finish_projection_recovery_compensation(
    TEXT, UUID, TEXT, BIGINT, TEXT, UUID, TEXT, JSONB, TEXT, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.finish_projection_recovery_compensation(
    TEXT, UUID, TEXT, BIGINT, TEXT, UUID, TEXT, JSONB, TEXT, TEXT
) TO gda_control_gateway;
