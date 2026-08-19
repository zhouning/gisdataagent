-- 172: Bind manual projection recovery compensation to exact ApprovalCase evidence.
--
-- A waiting recovery job may be resumed only by consuming one unexpired,
-- approved ApprovalCase whose tenant, target job, waiting snapshot and action
-- all match. Consumption is append-only so one verdict cannot authorize a
-- second compensation attempt.

ALTER TABLE gda_control.cross_store_projection_recovery_job
    ADD COLUMN IF NOT EXISTS resume_approval_case_ref TEXT,
    ADD COLUMN IF NOT EXISTS resume_reason TEXT,
    ADD COLUMN IF NOT EXISTS resume_snapshot_sha256 CHAR(64);

ALTER TABLE gda_control.cross_store_projection_recovery_job
    DROP CONSTRAINT IF EXISTS ck_gda_projection_recovery_job_complete_resume_evidence;
ALTER TABLE gda_control.cross_store_projection_recovery_job
    ADD CONSTRAINT ck_gda_projection_recovery_job_complete_resume_evidence CHECK (
        num_nonnulls(
            resumed_by,
            resumed_at,
            resume_approval_case_ref,
            resume_reason,
            resume_snapshot_sha256
        ) IN (0, 5)
    ) NOT VALID;

ALTER TABLE gda_control.cross_store_projection_recovery_job
    DROP CONSTRAINT IF EXISTS ck_gda_projection_recovery_job_resume_approval_ref;
ALTER TABLE gda_control.cross_store_projection_recovery_job
    ADD CONSTRAINT ck_gda_projection_recovery_job_resume_approval_ref CHECK (
        resume_approval_case_ref IS NULL OR (
            resume_approval_case_ref ~ (
                '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/'
                || '[a-z0-9][a-z0-9._-]{0,127}$'
            )
            AND split_part(resume_approval_case_ref, '/', 3) = tenant_id
        )
    ) NOT VALID;

ALTER TABLE gda_control.cross_store_projection_recovery_job
    DROP CONSTRAINT IF EXISTS ck_gda_projection_recovery_job_resume_reason;
ALTER TABLE gda_control.cross_store_projection_recovery_job
    ADD CONSTRAINT ck_gda_projection_recovery_job_resume_reason CHECK (
        resume_reason IS NULL OR (
            NULLIF(btrim(resume_reason), '') IS NOT NULL
            AND octet_length(resume_reason) <= 1024
        )
    ) NOT VALID;

ALTER TABLE gda_control.cross_store_projection_recovery_job
    DROP CONSTRAINT IF EXISTS ck_gda_projection_recovery_job_resume_snapshot;
ALTER TABLE gda_control.cross_store_projection_recovery_job
    ADD CONSTRAINT ck_gda_projection_recovery_job_resume_snapshot CHECK (
        resume_snapshot_sha256 IS NULL
        OR resume_snapshot_sha256 ~ '^[0-9a-f]{64}$'
    ) NOT VALID;

ALTER TABLE gda_control.cross_store_projection_recovery_job
    DROP CONSTRAINT IF EXISTS fk_gda_projection_recovery_job_resume_approval;
ALTER TABLE gda_control.cross_store_projection_recovery_job
    ADD CONSTRAINT fk_gda_projection_recovery_job_resume_approval
    FOREIGN KEY (tenant_id, resume_approval_case_ref)
    REFERENCES gda_control.approval_case(tenant_id, approval_case_ref)
    NOT VALID;

CREATE TABLE IF NOT EXISTS gda_control.cross_store_projection_recovery_resume_event (
    tenant_id TEXT NOT NULL,
    approval_case_ref TEXT NOT NULL,
    job_id UUID NOT NULL,
    resume_snapshot_sha256 CHAR(64) NOT NULL,
    resumed_by TEXT NOT NULL,
    resume_reason TEXT NOT NULL,
    resumed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, approval_case_ref),
    CONSTRAINT fk_gda_projection_recovery_resume_event_job
        FOREIGN KEY (tenant_id, job_id)
        REFERENCES gda_control.cross_store_projection_recovery_job(tenant_id, job_id),
    CONSTRAINT fk_gda_projection_recovery_resume_event_approval
        FOREIGN KEY (tenant_id, approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT ck_gda_projection_recovery_resume_event_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_projection_recovery_resume_event_approval_ref CHECK (
        approval_case_ref ~ (
            '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/'
            || '[a-z0-9][a-z0-9._-]{0,127}$'
        )
        AND split_part(approval_case_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_projection_recovery_resume_event_snapshot
        CHECK (resume_snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_projection_recovery_resume_event_actor
        CHECK (resumed_by ~ '^(human|agent|workload):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_projection_recovery_resume_event_reason CHECK (
        NULLIF(btrim(resume_reason), '') IS NOT NULL
        AND octet_length(resume_reason) <= 1024
    )
);

DROP TRIGGER IF EXISTS trg_gda_projection_recovery_resume_event_immutable
    ON gda_control.cross_store_projection_recovery_resume_event;
CREATE TRIGGER trg_gda_projection_recovery_resume_event_immutable
BEFORE UPDATE OR DELETE ON gda_control.cross_store_projection_recovery_resume_event
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.cross_store_projection_recovery_resume_event
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.cross_store_projection_recovery_resume_event
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.cross_store_projection_recovery_resume_event;
CREATE POLICY tenant_isolation
    ON gda_control.cross_store_projection_recovery_resume_event
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.cross_store_projection_recovery_resume_event
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.cross_store_projection_recovery_resume_event
    TO gda_control_gateway;

-- Remove the migration-171 entry point: actor identity alone is not authority.
REVOKE ALL ON FUNCTION gda_control.resume_cross_store_projection_recovery_job(
    TEXT, UUID, TEXT
) FROM PUBLIC, gda_control_gateway;
DROP FUNCTION gda_control.resume_cross_store_projection_recovery_job(
    TEXT, UUID, TEXT
);

CREATE FUNCTION gda_control.resume_cross_store_projection_recovery_job(
    p_tenant_id TEXT,
    p_job_id UUID,
    p_requested_by TEXT,
    p_approval_case_ref TEXT,
    p_reason TEXT
)
RETURNS SETOF gda_control.cross_store_projection_recovery_job
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_job gda_control.cross_store_projection_recovery_job%ROWTYPE;
    v_approval gda_control.approval_case%ROWTYPE;
    v_expected_target TEXT;
    v_resumed_at TIMESTAMPTZ;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'projection recovery job tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_requested_by IS NULL
       OR p_requested_by !~ '^(human|agent|workload):[^[:space:]]{1,128}$'
       OR p_approval_case_ref IS NULL
       OR p_approval_case_ref !~ (
            '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/'
            || '[a-z0-9][a-z0-9._-]{0,127}$'
       )
       OR split_part(p_approval_case_ref, '/', 3) <> p_tenant_id
       OR NULLIF(btrim(p_reason), '') IS NULL
       OR octet_length(btrim(p_reason)) > 1024 THEN
        RAISE EXCEPTION 'projection recovery resume evidence is invalid'
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
    IF v_job.status <> 'waiting_operator'
       OR v_job.next_action IS DISTINCT FROM 'manual_compensation' THEN
        RAISE EXCEPTION 'only waiting compensation jobs may be resumed'
            USING ERRCODE = '40001';
    END IF;
    IF v_job.snapshot_sha256 IS NULL THEN
        RAISE EXCEPTION 'waiting recovery job lacks a bound snapshot'
            USING ERRCODE = '23514';
    END IF;
    IF v_job.attempt_count >= 100 THEN
        RAISE EXCEPTION 'projection recovery job reached the absolute attempt limit'
            USING ERRCODE = '40001';
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
       OR v_approval.target_fingerprint IS DISTINCT FROM v_job.snapshot_sha256
       OR v_approval.action IS DISTINCT FROM 'projection.recovery.compensate' THEN
        RAISE EXCEPTION 'ApprovalCase does not authorize this recovery compensation'
            USING ERRCODE = '23514';
    END IF;

    v_resumed_at := clock_timestamp();
    INSERT INTO gda_control.cross_store_projection_recovery_resume_event (
        tenant_id,
        approval_case_ref,
        job_id,
        resume_snapshot_sha256,
        resumed_by,
        resume_reason,
        resumed_at
    ) VALUES (
        p_tenant_id,
        p_approval_case_ref,
        p_job_id,
        v_job.snapshot_sha256,
        p_requested_by,
        btrim(p_reason),
        v_resumed_at
    );

    PERFORM set_config('gda.cross_store_projection_recovery_job_write_allowed', '1', true);
    UPDATE gda_control.cross_store_projection_recovery_job AS job
       SET status = 'queued',
           next_action = NULL,
           max_attempts = GREATEST(job.max_attempts, job.attempt_count + 1),
           available_at = v_resumed_at,
           resumed_by = p_requested_by,
           resumed_at = v_resumed_at,
           resume_approval_case_ref = p_approval_case_ref,
           resume_reason = btrim(p_reason),
           resume_snapshot_sha256 = v_job.snapshot_sha256,
           error_code = NULL,
           error_message = NULL,
           updated_at = v_resumed_at
     WHERE job.tenant_id = p_tenant_id AND job.job_id = p_job_id
    RETURNING * INTO v_job;
    PERFORM set_config('gda.cross_store_projection_recovery_job_write_allowed', '0', true);
    RETURN NEXT v_job;
EXCEPTION WHEN unique_violation THEN
    PERFORM set_config('gda.cross_store_projection_recovery_job_write_allowed', '0', true);
    RAISE EXCEPTION 'ApprovalCase was already consumed for recovery compensation'
        USING ERRCODE = '40001';
WHEN OTHERS THEN
    PERFORM set_config('gda.cross_store_projection_recovery_job_write_allowed', '0', true);
    RAISE;
END;
$$;

REVOKE ALL ON FUNCTION gda_control.resume_cross_store_projection_recovery_job(
    TEXT, UUID, TEXT, TEXT, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.resume_cross_store_projection_recovery_job(
    TEXT, UUID, TEXT, TEXT, TEXT
) TO gda_control_gateway;
