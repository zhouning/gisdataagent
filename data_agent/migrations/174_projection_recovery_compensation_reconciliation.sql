-- 174: Resolve started-only compensation attempts through explicit authority.
--
-- A human-observed Provider state and a separate ApprovalCase may seal the
-- original attempt as committed or not committed. Unknown state stays
-- blocked. A committed ruling queues authority recovery with the persisted
-- receipt; a not-committed ruling still requires a new compensation approval.

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;

CREATE TABLE IF NOT EXISTS
gda_control.cross_store_projection_compensation_reconciliation_event (
    tenant_id TEXT NOT NULL,
    reconciliation_event_id UUID NOT NULL DEFAULT public.gen_random_uuid(),
    compensation_attempt_id UUID NOT NULL,
    job_id UUID NOT NULL,
    original_approval_case_ref TEXT NOT NULL,
    reconciliation_approval_case_ref TEXT NOT NULL,
    target_fingerprint CHAR(64) NOT NULL,
    resume_snapshot_sha256 CHAR(64) NOT NULL,
    plan_sha256 CHAR(64) NOT NULL,
    plan_idempotency_key CHAR(64) NOT NULL,
    verdict TEXT NOT NULL,
    observed_by TEXT NOT NULL,
    observation_ref TEXT NOT NULL,
    observation_sha256 CHAR(64) NOT NULL,
    reason TEXT NOT NULL,
    provider_commit_ref JSONB,
    receipt_sha256 CHAR(64),
    resumed_automatically BOOLEAN NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, reconciliation_event_id),
    CONSTRAINT uq_gda_projection_compensation_reconciliation_attempt
        UNIQUE (tenant_id, original_approval_case_ref),
    CONSTRAINT uq_gda_projection_compensation_reconciliation_approval
        UNIQUE (tenant_id, reconciliation_approval_case_ref),
    CONSTRAINT fk_gda_projection_compensation_reconciliation_job
        FOREIGN KEY (tenant_id, job_id)
        REFERENCES gda_control.cross_store_projection_recovery_job(tenant_id, job_id),
    CONSTRAINT fk_gda_projection_compensation_reconciliation_original_approval
        FOREIGN KEY (tenant_id, original_approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT fk_gda_projection_compensation_reconciliation_approval
        FOREIGN KEY (tenant_id, reconciliation_approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT ck_gda_projection_compensation_reconciliation_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_projection_compensation_reconciliation_approval_refs CHECK (
        original_approval_case_ref ~ (
            '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/'
            || '[a-z0-9][a-z0-9._-]{0,127}$'
        )
        AND reconciliation_approval_case_ref ~ (
            '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/'
            || '[a-z0-9][a-z0-9._-]{0,127}$'
        )
        AND split_part(original_approval_case_ref, '/', 3) = tenant_id
        AND split_part(reconciliation_approval_case_ref, '/', 3) = tenant_id
        AND original_approval_case_ref <> reconciliation_approval_case_ref
    ),
    CONSTRAINT ck_gda_projection_compensation_reconciliation_hashes CHECK (
        target_fingerprint ~ '^[0-9a-f]{64}$'
        AND resume_snapshot_sha256 ~ '^[0-9a-f]{64}$'
        AND plan_sha256 ~ '^[0-9a-f]{64}$'
        AND plan_idempotency_key ~ '^[0-9a-f]{64}$'
        AND observation_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_projection_compensation_reconciliation_observer
        CHECK (observed_by ~ '^human:[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_projection_compensation_reconciliation_text CHECK (
        NULLIF(btrim(observation_ref), '') IS NOT NULL
        AND octet_length(observation_ref) <= 512
        AND NULLIF(btrim(reason), '') IS NOT NULL
        AND octet_length(reason) <= 1024
    ),
    CONSTRAINT ck_gda_projection_compensation_reconciliation_verdict CHECK (
        (
            verdict = 'provider_committed'
            AND jsonb_typeof(provider_commit_ref) = 'object'
            AND receipt_sha256 ~ '^[0-9a-f]{64}$'
            AND resumed_automatically
        ) OR (
            verdict = 'provider_not_committed'
            AND provider_commit_ref IS NULL
            AND receipt_sha256 IS NULL
            AND NOT resumed_automatically
        )
    )
);

CREATE OR REPLACE FUNCTION
gda_control.guard_projection_compensation_reconciliation_write()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(
        current_setting(
            'gda.projection_compensation_reconciliation_write_allowed', true
        ),
        ''
    ) <> '1' THEN
        RAISE EXCEPTION 'use governed projection compensation reconciliation function'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR COALESCE(NEW.tenant_id, OLD.tenant_id)
            IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'projection compensation reconciliation tenant mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_projection_compensation_reconciliation_guard
    ON gda_control.cross_store_projection_compensation_reconciliation_event;
CREATE TRIGGER trg_gda_projection_compensation_reconciliation_guard
BEFORE INSERT OR UPDATE OR DELETE
ON gda_control.cross_store_projection_compensation_reconciliation_event
FOR EACH ROW
EXECUTE FUNCTION gda_control.guard_projection_compensation_reconciliation_write();

DROP TRIGGER IF EXISTS trg_gda_projection_compensation_reconciliation_immutable
    ON gda_control.cross_store_projection_compensation_reconciliation_event;
CREATE TRIGGER trg_gda_projection_compensation_reconciliation_immutable
BEFORE UPDATE OR DELETE
ON gda_control.cross_store_projection_compensation_reconciliation_event
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.cross_store_projection_compensation_reconciliation_event
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.cross_store_projection_compensation_reconciliation_event
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.cross_store_projection_compensation_reconciliation_event;
CREATE POLICY tenant_isolation
    ON gda_control.cross_store_projection_compensation_reconciliation_event
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE FUNCTION gda_control.reconcile_projection_recovery_compensation(
    p_tenant_id TEXT,
    p_job_id UUID,
    p_original_approval_case_ref TEXT,
    p_reconciliation_approval_case_ref TEXT,
    p_compensation_attempt_id UUID,
    p_target_fingerprint TEXT,
    p_verdict TEXT,
    p_observed_by TEXT,
    p_observation_ref TEXT,
    p_observation_sha256 TEXT,
    p_reason TEXT,
    p_provider_commit_ref JSONB,
    p_receipt_sha256 TEXT
)
RETURNS TABLE(
    tenant_id TEXT,
    reconciliation_event_id UUID,
    compensation_attempt_id UUID,
    job_id UUID,
    original_approval_case_ref TEXT,
    reconciliation_approval_case_ref TEXT,
    target_fingerprint TEXT,
    resume_snapshot_sha256 TEXT,
    plan_sha256 TEXT,
    plan_idempotency_key TEXT,
    strategy TEXT,
    verdict TEXT,
    observed_by TEXT,
    observation_ref TEXT,
    observation_sha256 TEXT,
    reason TEXT,
    provider_commit_ref JSONB,
    receipt_sha256 TEXT
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
    v_approval gda_control.approval_case%ROWTYPE;
    v_existing
        gda_control.cross_store_projection_compensation_reconciliation_event%ROWTYPE;
    v_recorded
        gda_control.cross_store_projection_compensation_reconciliation_event%ROWTYPE;
    v_expected_action TEXT;
    v_expected_target TEXT;
    v_target_fingerprint TEXT;
    v_resumed_automatically BOOLEAN;
    v_terminal_type TEXT;
    v_error_code TEXT;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'projection compensation reconciliation tenant mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_compensation_attempt_id IS NULL
       OR p_target_fingerprint !~ '^[0-9a-f]{64}$'
       OR p_verdict NOT IN ('provider_committed', 'provider_not_committed')
       OR p_observed_by !~ '^human:[^[:space:]]{1,128}$'
       OR NULLIF(btrim(p_observation_ref), '') IS NULL
       OR octet_length(p_observation_ref) > 512
       OR p_observation_sha256 !~ '^[0-9a-f]{64}$'
       OR NULLIF(btrim(p_reason), '') IS NULL
       OR octet_length(p_reason) > 1024
       OR p_original_approval_case_ref IS NULL
       OR p_reconciliation_approval_case_ref IS NULL
       OR p_original_approval_case_ref = p_reconciliation_approval_case_ref THEN
        RAISE EXCEPTION 'projection compensation reconciliation evidence is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF (
        p_verdict = 'provider_committed'
        AND (
            p_provider_commit_ref IS NULL
            OR jsonb_typeof(p_provider_commit_ref) <> 'object'
            OR p_receipt_sha256 !~ '^[0-9a-f]{64}$'
        )
    ) OR (
        p_verdict = 'provider_not_committed'
        AND (p_provider_commit_ref IS NOT NULL OR p_receipt_sha256 IS NOT NULL)
    ) THEN
        RAISE EXCEPTION 'projection compensation reconciliation verdict is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'projection-compensation-reconciliation|'
            || p_tenant_id || '|' || p_original_approval_case_ref,
            0
        )
    );
    SELECT job.* INTO v_job
    FROM gda_control.cross_store_projection_recovery_job AS job
    WHERE job.tenant_id = p_tenant_id AND job.job_id = p_job_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'projection recovery job was not found'
            USING ERRCODE = 'P0002';
    END IF;

    SELECT event.* INTO v_started
    FROM gda_control.cross_store_projection_compensation_event AS event
    WHERE event.tenant_id = p_tenant_id
      AND event.approval_case_ref = p_original_approval_case_ref
      AND event.event_index = 1;
    IF NOT FOUND
       OR v_started.event_type <> 'started'
       OR v_started.compensation_attempt_id
            IS DISTINCT FROM p_compensation_attempt_id
       OR v_started.job_id IS DISTINCT FROM p_job_id
       OR v_started.resume_snapshot_sha256
            IS DISTINCT FROM v_job.resume_snapshot_sha256
       OR v_started.plan_sha256 IS DISTINCT FROM v_job.plan_sha256
       OR v_started.plan_idempotency_key
            IS DISTINCT FROM v_job.plan_idempotency_key THEN
        RAISE EXCEPTION 'started compensation attempt is missing or drifted'
            USING ERRCODE = '23514';
    END IF;

    v_target_fingerprint := encode(
        public.digest(
            convert_to(
                concat_ws(
                    chr(31),
                    'gda.projection-recovery-compensation-reconciliation-target.v1',
                    p_tenant_id,
                    p_job_id::TEXT,
                    p_compensation_attempt_id::TEXT,
                    v_started.resume_snapshot_sha256,
                    v_started.plan_sha256,
                    v_started.plan_idempotency_key,
                    v_started.strategy
                ),
                'UTF8'
            ),
            'sha256'
        ),
        'hex'
    );
    IF p_target_fingerprint IS DISTINCT FROM v_target_fingerprint THEN
        RAISE EXCEPTION 'reconciliation target fingerprint differs from attempt'
            USING ERRCODE = '23514';
    END IF;

    SELECT event.* INTO v_existing
    FROM gda_control.cross_store_projection_compensation_reconciliation_event AS event
    WHERE event.tenant_id = p_tenant_id
      AND event.original_approval_case_ref = p_original_approval_case_ref;
    IF FOUND THEN
        IF v_existing.job_id IS DISTINCT FROM p_job_id
           OR v_existing.compensation_attempt_id
                IS DISTINCT FROM p_compensation_attempt_id
           OR v_existing.reconciliation_approval_case_ref
                IS DISTINCT FROM p_reconciliation_approval_case_ref
           OR v_existing.target_fingerprint IS DISTINCT FROM p_target_fingerprint
           OR v_existing.verdict IS DISTINCT FROM p_verdict
           OR v_existing.observed_by IS DISTINCT FROM p_observed_by
           OR v_existing.observation_ref IS DISTINCT FROM btrim(p_observation_ref)
           OR v_existing.observation_sha256
                IS DISTINCT FROM p_observation_sha256
           OR v_existing.reason IS DISTINCT FROM btrim(p_reason)
           OR v_existing.provider_commit_ref IS DISTINCT FROM p_provider_commit_ref
           OR v_existing.receipt_sha256 IS DISTINCT FROM p_receipt_sha256 THEN
            RAISE EXCEPTION 'compensation reconciliation evidence differs'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT
            v_existing.tenant_id,
            v_existing.reconciliation_event_id,
            v_existing.compensation_attempt_id,
            v_existing.job_id,
            v_existing.original_approval_case_ref,
            v_existing.reconciliation_approval_case_ref,
            v_existing.target_fingerprint::TEXT,
            v_existing.resume_snapshot_sha256::TEXT,
            v_existing.plan_sha256::TEXT,
            v_existing.plan_idempotency_key::TEXT,
            v_started.strategy,
            v_existing.verdict,
            v_existing.observed_by,
            v_existing.observation_ref,
            v_existing.observation_sha256::TEXT,
            v_existing.reason,
            v_existing.provider_commit_ref,
            v_existing.receipt_sha256::TEXT;
        RETURN;
    END IF;

    IF v_job.status <> 'waiting_operator'
       OR v_job.next_action IS DISTINCT FROM 'manual_compensation'
       OR v_job.snapshot_sha256 IS DISTINCT FROM v_started.resume_snapshot_sha256 THEN
        RAISE EXCEPTION 'only waiting started-only compensation may be reconciled'
            USING ERRCODE = '40001';
    END IF;
    SELECT event.* INTO v_terminal
    FROM gda_control.cross_store_projection_compensation_event AS event
    WHERE event.tenant_id = p_tenant_id
      AND event.approval_case_ref = p_original_approval_case_ref
      AND event.event_index = 2;
    IF FOUND THEN
        RAISE EXCEPTION 'compensation attempt already has terminal evidence'
            USING ERRCODE = '40001';
    END IF;

    IF p_verdict = 'provider_committed' THEN
        v_expected_action :=
            'projection.recovery.compensation.reconcile_committed';
        v_resumed_automatically := TRUE;
        v_terminal_type := 'succeeded';
        v_error_code := NULL;
        IF p_provider_commit_ref ->> 'plan_sha256'
                IS DISTINCT FROM v_started.plan_sha256
           OR p_provider_commit_ref ->> 'idempotency_key'
                IS DISTINCT FROM v_started.plan_idempotency_key THEN
            RAISE EXCEPTION 'reconciled provider receipt is not plan-bound'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        v_expected_action :=
            'projection.recovery.compensation.reconcile_not_committed';
        v_resumed_automatically := FALSE;
        v_terminal_type := 'failed_known';
        v_error_code := 'operator_verified_not_committed';
    END IF;
    v_expected_target := format(
        'gda://%s/projection_compensation_attempt/%s',
        p_tenant_id,
        p_compensation_attempt_id::TEXT
    );
    SELECT approval.* INTO v_approval
    FROM gda_control.approval_case AS approval
    WHERE approval.tenant_id = p_tenant_id
      AND approval.approval_case_ref = p_reconciliation_approval_case_ref;
    IF NOT FOUND
       OR v_approval.status IS DISTINCT FROM 'approved'
       OR clock_timestamp() >= v_approval.expires_at
       OR v_approval.target_resource_urn IS DISTINCT FROM v_expected_target
       OR v_approval.target_fingerprint IS DISTINCT FROM v_target_fingerprint
       OR v_approval.action IS DISTINCT FROM v_expected_action
       OR v_approval.request_context ->> 'compensation_attempt_id'
            IS DISTINCT FROM p_compensation_attempt_id::TEXT
       OR v_approval.request_context ->> 'original_approval_case_ref'
            IS DISTINCT FROM p_original_approval_case_ref
       OR v_approval.request_context ->> 'observed_by'
            IS DISTINCT FROM p_observed_by
       OR v_approval.request_context ->> 'observation_ref'
            IS DISTINCT FROM btrim(p_observation_ref)
       OR v_approval.request_context ->> 'observation_sha256'
            IS DISTINCT FROM p_observation_sha256
       OR v_approval.request_context ->> 'verdict'
            IS DISTINCT FROM p_verdict
       OR (
            p_verdict = 'provider_committed'
            AND v_approval.request_context ->> 'receipt_sha256'
                IS DISTINCT FROM p_receipt_sha256
       ) THEN
        RAISE EXCEPTION 'ApprovalCase does not authorize this reconciliation'
            USING ERRCODE = '23514';
    END IF;

    PERFORM set_config(
        'gda.projection_compensation_reconciliation_write_allowed', '1', true
    );
    INSERT INTO
        gda_control.cross_store_projection_compensation_reconciliation_event (
            tenant_id, compensation_attempt_id, job_id,
            original_approval_case_ref, reconciliation_approval_case_ref,
            target_fingerprint, resume_snapshot_sha256, plan_sha256,
            plan_idempotency_key, verdict, observed_by, observation_ref,
            observation_sha256, reason, provider_commit_ref, receipt_sha256,
            resumed_automatically
        ) VALUES (
            p_tenant_id, p_compensation_attempt_id, p_job_id,
            p_original_approval_case_ref, p_reconciliation_approval_case_ref,
            v_target_fingerprint, v_started.resume_snapshot_sha256,
            v_started.plan_sha256, v_started.plan_idempotency_key,
            p_verdict, p_observed_by, btrim(p_observation_ref),
            p_observation_sha256, btrim(p_reason), p_provider_commit_ref,
            p_receipt_sha256, v_resumed_automatically
        )
    RETURNING * INTO v_recorded;
    PERFORM set_config(
        'gda.projection_compensation_reconciliation_write_allowed', '0', true
    );

    PERFORM set_config('gda.projection_compensation_event_write_allowed', '1', true);
    INSERT INTO gda_control.cross_store_projection_compensation_event (
        tenant_id, approval_case_ref, event_index, compensation_attempt_id,
        job_id, resume_snapshot_sha256, plan_sha256, plan_idempotency_key,
        strategy, worker_id, lease_generation, event_type,
        provider_commit_ref, receipt_sha256, error_code
    ) VALUES (
        p_tenant_id, p_original_approval_case_ref, 2,
        p_compensation_attempt_id, p_job_id,
        v_started.resume_snapshot_sha256, v_started.plan_sha256,
        v_started.plan_idempotency_key, v_started.strategy,
        'worker:operator-reconciliation', v_started.lease_generation,
        v_terminal_type, p_provider_commit_ref, p_receipt_sha256, v_error_code
    );
    PERFORM set_config('gda.projection_compensation_event_write_allowed', '0', true);

    IF v_resumed_automatically THEN
        PERFORM set_config(
            'gda.cross_store_projection_recovery_job_write_allowed', '1', true
        );
        UPDATE gda_control.cross_store_projection_recovery_job AS job
           SET status = 'queued',
               next_action = NULL,
               max_attempts = GREATEST(job.max_attempts, job.attempt_count + 1),
               available_at = clock_timestamp(),
               error_code = NULL,
               error_message = NULL,
               updated_at = clock_timestamp()
         WHERE job.tenant_id = p_tenant_id AND job.job_id = p_job_id;
        PERFORM set_config(
            'gda.cross_store_projection_recovery_job_write_allowed', '0', true
        );
    END IF;

    RETURN QUERY SELECT
        v_recorded.tenant_id,
        v_recorded.reconciliation_event_id,
        v_recorded.compensation_attempt_id,
        v_recorded.job_id,
        v_recorded.original_approval_case_ref,
        v_recorded.reconciliation_approval_case_ref,
        v_recorded.target_fingerprint::TEXT,
        v_recorded.resume_snapshot_sha256::TEXT,
        v_recorded.plan_sha256::TEXT,
        v_recorded.plan_idempotency_key::TEXT,
        v_started.strategy,
        v_recorded.verdict,
        v_recorded.observed_by,
        v_recorded.observation_ref,
        v_recorded.observation_sha256::TEXT,
        v_recorded.reason,
        v_recorded.provider_commit_ref,
        v_recorded.receipt_sha256::TEXT;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config(
        'gda.projection_compensation_reconciliation_write_allowed', '0', true
    );
    PERFORM set_config('gda.projection_compensation_event_write_allowed', '0', true);
    PERFORM set_config(
        'gda.cross_store_projection_recovery_job_write_allowed', '0', true
    );
    RAISE;
END;
$$;

REVOKE ALL ON TABLE
    gda_control.cross_store_projection_compensation_reconciliation_event
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE
    gda_control.cross_store_projection_compensation_reconciliation_event
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION
gda_control.guard_projection_compensation_reconciliation_write()
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.reconcile_projection_recovery_compensation(
    TEXT, UUID, TEXT, TEXT, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    JSONB, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.reconcile_projection_recovery_compensation(
    TEXT, UUID, TEXT, TEXT, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    JSONB, TEXT
) TO gda_control_gateway;
