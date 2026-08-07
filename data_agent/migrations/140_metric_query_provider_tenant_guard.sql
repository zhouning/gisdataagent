-- Preserve migration 139 immutability while adding explicit provider tenant guards.

CREATE OR REPLACE FUNCTION gda_control.start_metric_query_execution(
    p_tenant_id TEXT,
    p_run_id UUID,
    p_expected_state_version INTEGER,
    p_start_observation_id UUID,
    p_attempt_no INTEGER,
    p_external_namespace TEXT,
    p_external_run_id TEXT,
    p_external_attempt_id TEXT,
    p_actor_subject TEXT,
    p_observed_at TIMESTAMPTZ
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_admission gda_control.metric_query_execution_admission%ROWTYPE;
    v_command gda_control.platform_command_outbox%ROWTYPE;
    v_expected_actor TEXT;
    v_expected_dedupe TEXT;
    v_expected_command_id UUID;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'metric query tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_admission
    FROM gda_control.metric_query_execution_admission
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'metric query admission was not found'
            USING ERRCODE = 'P0002';
    END IF;
    v_expected_actor := CASE v_admission.engine
        WHEN 'postgis' THEN 'workload:metric-query-postgis'
        WHEN 'duckdb' THEN 'workload:metric-query-duckdb'
        ELSE 'workload:metric-query-spark'
    END;
    v_expected_dedupe := concat(
        'metric_query.execute:', p_tenant_id, ':', p_run_id::text, ':',
        v_admission.plan_artifact_id::text, ':', v_admission.plan_fingerprint
    );
    v_expected_command_id := gda_control.metric_query_command_uuid(
        v_expected_dedupe
    );
    SELECT * INTO v_command
    FROM gda_control.platform_command_outbox
    WHERE tenant_id = p_tenant_id
      AND run_id = p_run_id
      AND command_type = 'metric_query.execute'
      AND command_id::text = p_external_run_id;
    IF p_actor_subject IS DISTINCT FROM v_expected_actor THEN
        RAISE EXCEPTION 'metric query provider identity does not match engine'
            USING ERRCODE = '42501';
    END IF;
    IF NOT FOUND
       OR v_command.status <> 'in_flight'
       OR v_command.command_id <> v_expected_command_id
       OR v_command.dedupe_key <> v_expected_dedupe
       OR v_command.actor_subject <> v_expected_actor
       OR v_command.execution_plan_artifact_id
            <> v_admission.plan_artifact_id
       OR v_command.payload->>'plan_fingerprint'
            <> v_admission.plan_fingerprint
       OR v_command.payload->>'cache_key' <> v_admission.cache_key
       OR v_command.payload->>'engine' <> v_admission.engine
       OR v_command.payload->>'execution_mode' <> v_admission.execution_mode
       OR p_attempt_no <> 1
       OR p_external_namespace <> 'gda/metric-query/' || v_admission.engine
       OR p_external_attempt_id IS DISTINCT FROM 'provider-attempt-1' THEN
        RAISE EXCEPTION 'metric query start is not bound to an active command'
            USING ERRCODE = '23514';
    END IF;
    RETURN gda_control.start_metric_query_execution_v138(
        p_tenant_id, p_run_id, p_expected_state_version,
        p_start_observation_id, p_attempt_no, p_external_namespace,
        p_external_run_id, p_external_attempt_id, p_actor_subject,
        p_observed_at
    );
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.complete_metric_query_execution(
    p_tenant_id TEXT,
    p_run_id UUID,
    p_expected_state_version INTEGER,
    p_query_observation_id UUID,
    p_start_observation_id UUID,
    p_terminal_observation_id UUID,
    p_result_artifact_id UUID,
    p_attempt_no INTEGER,
    p_outcome TEXT,
    p_cache_status TEXT,
    p_rows_returned BIGINT,
    p_rows_scanned BIGINT,
    p_bytes_scanned BIGINT,
    p_duration_ms BIGINT,
    p_result_storage_uri TEXT,
    p_result_media_type TEXT,
    p_result_sha256 TEXT,
    p_result_size_bytes BIGINT,
    p_result_manifest JSONB,
    p_error_code TEXT,
    p_error_message TEXT,
    p_actor_subject TEXT,
    p_observed_at TIMESTAMPTZ
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_admission gda_control.metric_query_execution_admission%ROWTYPE;
    v_start gda_control.framework_attempt_observation%ROWTYPE;
    v_command gda_control.platform_command_outbox%ROWTYPE;
    v_expected_actor TEXT;
    v_expected_dedupe TEXT;
    v_expected_command_id UUID;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'metric query tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_admission
    FROM gda_control.metric_query_execution_admission
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'metric query admission was not found'
            USING ERRCODE = 'P0002';
    END IF;
    v_expected_actor := CASE v_admission.engine
        WHEN 'postgis' THEN 'workload:metric-query-postgis'
        WHEN 'duckdb' THEN 'workload:metric-query-duckdb'
        ELSE 'workload:metric-query-spark'
    END;
    v_expected_dedupe := concat(
        'metric_query.execute:', p_tenant_id, ':', p_run_id::text, ':',
        v_admission.plan_artifact_id::text, ':', v_admission.plan_fingerprint
    );
    v_expected_command_id := gda_control.metric_query_command_uuid(
        v_expected_dedupe
    );
    IF p_actor_subject IS DISTINCT FROM v_expected_actor THEN
        RAISE EXCEPTION 'metric query provider identity does not match engine'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_start
    FROM gda_control.framework_attempt_observation
    WHERE tenant_id = p_tenant_id
      AND observation_id = p_start_observation_id
      AND run_id = p_run_id
      AND attempt_no = 1
      AND evidence->>'provider_subject' = v_expected_actor;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'metric query completion has no bound provider start'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_command
    FROM gda_control.platform_command_outbox
    WHERE tenant_id = p_tenant_id
      AND run_id = p_run_id
      AND command_type = 'metric_query.execute'
      AND command_id::text = v_start.external_run_id;
    IF NOT FOUND
       OR v_command.status = 'pending'
       OR v_command.command_id <> v_expected_command_id
       OR v_command.dedupe_key <> v_expected_dedupe
       OR v_command.actor_subject <> v_expected_actor
       OR v_command.execution_plan_artifact_id
            <> v_admission.plan_artifact_id
       OR v_command.payload->>'plan_fingerprint'
            <> v_admission.plan_fingerprint
       OR v_command.payload->>'cache_key' <> v_admission.cache_key
       OR v_command.payload->>'engine' <> v_admission.engine
       OR v_command.payload->>'execution_mode' <> v_admission.execution_mode
       OR p_attempt_no <> 1 THEN
        RAISE EXCEPTION 'metric query completion is not bound to its command'
            USING ERRCODE = '23514';
    END IF;
    RETURN gda_control.complete_metric_query_execution_v138(
        p_tenant_id, p_run_id, p_expected_state_version,
        p_query_observation_id, p_start_observation_id,
        p_terminal_observation_id, p_result_artifact_id,
        p_attempt_no, p_outcome, p_cache_status,
        p_rows_returned, p_rows_scanned, p_bytes_scanned,
        p_duration_ms, p_result_storage_uri, p_result_media_type,
        p_result_sha256, p_result_size_bytes, p_result_manifest,
        p_error_code, p_error_message, p_actor_subject, p_observed_at
    );
END;
$$;
