-- 168: Make completion honor cancellation requested before the final boundary.

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
DECLARE
    v_job gda_control.chongqing_data_package_reconciliation_job%ROWTYPE;
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

    SELECT * INTO v_job
      FROM gda_control.chongqing_data_package_reconciliation_job
     WHERE tenant_id = p_tenant_id
       AND job_id = p_job_id
       AND status IN ('running', 'cancel_requested')
       AND claimed_by = p_worker_id
       AND lease_expires_at > clock_timestamp()
     FOR UPDATE;
    IF NOT FOUND
       OR p_response_document ->> 'request_sha256' <> v_job.request_sha256
       OR p_response_document ->> 'idempotency_key' <> v_job.idempotency_key THEN
        RAISE EXCEPTION 'reconciliation job completion claim is invalid'
            USING ERRCODE = '40001';
    END IF;

    IF v_job.status = 'cancel_requested' THEN
        UPDATE gda_control.chongqing_data_package_reconciliation_job
           SET status = 'cancelled',
               phase = 'cancelled',
               phase_detail = 'cancelled_at_completion_boundary',
               claimed_by = NULL,
               lease_expires_at = NULL,
               response_document = NULL,
               error_code = NULL,
               error_message = NULL,
               updated_at = clock_timestamp(),
               completed_at = clock_timestamp()
         WHERE tenant_id = p_tenant_id AND job_id = p_job_id
        RETURNING * INTO v_job;
    ELSE
        UPDATE gda_control.chongqing_data_package_reconciliation_job
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
         WHERE tenant_id = p_tenant_id AND job_id = p_job_id
        RETURNING * INTO v_job;
    END IF;
    RETURN NEXT v_job;
END;
$$;
