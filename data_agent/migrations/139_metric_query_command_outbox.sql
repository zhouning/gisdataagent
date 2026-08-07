-- Route governed metric-query admissions through the unified PlatformCommand outbox.

ALTER TABLE gda_control.platform_command_outbox
    DROP CONSTRAINT IF EXISTS ck_gda_command_type;

ALTER TABLE gda_control.platform_command_outbox
    ADD CONSTRAINT ck_gda_command_type CHECK (
        command_type IN (
            'dolphinscheduler.dispatch',
            'dolphinscheduler.reconcile',
            'dolphinscheduler.cancel',
            'metric_query.execute'
        )
    );

CREATE OR REPLACE FUNCTION gda_control.metric_query_command_uuid(
    p_dedupe_key TEXT
)
RETURNS UUID
LANGUAGE plpgsql
IMMUTABLE
STRICT
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_hex TEXT;
BEGIN
    v_hex := encode(
        public.digest(convert_to(p_dedupe_key, 'UTF8'), 'sha256'),
        'hex'
    );
    RETURN (
        substr(v_hex, 1, 8) || '-' ||
        substr(v_hex, 9, 4) || '-5' ||
        substr(v_hex, 14, 3) || '-8' ||
        substr(v_hex, 18, 3) || '-' ||
        substr(v_hex, 21, 12)
    )::uuid;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.enqueue_metric_query_command(
    p_tenant_id TEXT,
    p_run_id UUID
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_admission gda_control.metric_query_execution_admission%ROWTYPE;
    v_existing gda_control.platform_command_outbox%ROWTYPE;
    v_actor TEXT;
    v_dedupe_key TEXT;
    v_command_id UUID;
    v_payload JSONB;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'metric query command tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;

    SELECT * INTO v_admission
    FROM gda_control.metric_query_execution_admission
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'metric query admission was not found'
            USING ERRCODE = 'P0002';
    END IF;

    v_actor := CASE v_admission.engine
        WHEN 'postgis' THEN 'workload:metric-query-postgis'
        WHEN 'duckdb' THEN 'workload:metric-query-duckdb'
        ELSE 'workload:metric-query-spark'
    END;
    v_dedupe_key := concat(
        'metric_query.execute:', p_tenant_id, ':', p_run_id::text, ':',
        v_admission.plan_artifact_id::text, ':', v_admission.plan_fingerprint
    );
    v_command_id := gda_control.metric_query_command_uuid(v_dedupe_key);
    v_payload := jsonb_build_object(
        'schema', 'gda.metric_query_execute_command.v1',
        'run_id', p_run_id::text,
        'plan_artifact_id', v_admission.plan_artifact_id::text,
        'plan_fingerprint', v_admission.plan_fingerprint,
        'cache_key', v_admission.cache_key,
        'engine', v_admission.engine,
        'execution_mode', v_admission.execution_mode
    );

    INSERT INTO gda_control.platform_command_outbox (
        tenant_id, command_id, run_id, command_type,
        execution_plan_artifact_id, trigger_observation_id,
        dedupe_key, actor_subject, payload, status,
        attempt_count, max_attempts, available_at, created_at
    ) VALUES (
        p_tenant_id, v_command_id, p_run_id, 'metric_query.execute',
        v_admission.plan_artifact_id, NULL,
        v_dedupe_key, v_actor, v_payload, 'pending',
        0, 3, v_admission.admitted_at, v_admission.admitted_at
    )
    ON CONFLICT DO NOTHING;

    SELECT * INTO v_existing
    FROM gda_control.platform_command_outbox
    WHERE tenant_id = p_tenant_id AND dedupe_key = v_dedupe_key;
    IF NOT FOUND
       OR v_existing.command_id <> v_command_id
       OR v_existing.run_id <> p_run_id
       OR v_existing.command_type <> 'metric_query.execute'
       OR v_existing.execution_plan_artifact_id
            <> v_admission.plan_artifact_id
       OR v_existing.trigger_observation_id IS NOT NULL
       OR v_existing.actor_subject <> v_actor
       OR v_existing.payload <> v_payload
       OR v_existing.max_attempts <> 3
       OR v_existing.created_at <> v_admission.admitted_at THEN
        RAISE EXCEPTION 'metric query command identity has conflicting evidence'
            USING ERRCODE = '40001';
    END IF;
    RETURN v_command_id;
END;
$$;

ALTER FUNCTION gda_control.admit_metric_query_execution(
    text, uuid, text, uuid, text, jsonb, text, text, uuid, uuid,
    jsonb, text, timestamptz
) RENAME TO admit_metric_query_execution_v138;

CREATE FUNCTION gda_control.admit_metric_query_execution(
    p_tenant_id TEXT,
    p_run_id UUID,
    p_client_request_id TEXT,
    p_definition_version_id UUID,
    p_orchestration_class TEXT,
    p_subject_context JSONB,
    p_idempotency_key TEXT,
    p_config_fingerprint TEXT,
    p_output_resource_version_id UUID,
    p_plan_artifact_id UUID,
    p_plan_document JSONB,
    p_admitted_by TEXT,
    p_admitted_at TIMESTAMPTZ
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_existing gda_control.metric_query_execution_admission%ROWTYPE;
    v_existing_run gda_control.platform_run%ROWTYPE;
    v_run_id UUID;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'metric query tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;

    SELECT * INTO v_existing
    FROM gda_control.metric_query_execution_admission
    WHERE tenant_id = p_tenant_id
      AND client_request_id = p_client_request_id
    FOR UPDATE;
    IF FOUND THEN
        SELECT * INTO STRICT v_existing_run
        FROM gda_control.platform_run
        WHERE tenant_id = p_tenant_id AND run_id = v_existing.run_id;
        IF v_existing.run_id <> p_run_id
           OR v_existing.definition_version_id <> p_definition_version_id
           OR v_existing.cache_key <> p_config_fingerprint
           OR v_existing.plan_artifact_id <> p_plan_artifact_id
           OR v_existing.output_resource_version_id
                <> p_output_resource_version_id
           OR v_existing.admitted_by <> p_admitted_by
           OR v_existing.plan_document->'metric_version_ref'
                IS DISTINCT FROM p_plan_document->'metric_version_ref'
           OR v_existing.plan_document->'metric_fingerprint'
                IS DISTINCT FROM p_plan_document->'metric_fingerprint'
           OR v_existing.plan_document->'projection_version_ref'
                IS DISTINCT FROM p_plan_document->'projection_version_ref'
           OR v_existing.plan_document->'projection_fingerprint'
                IS DISTINCT FROM p_plan_document->'projection_fingerprint'
           OR v_existing.plan_document->'source_manifest_sha256'
                IS DISTINCT FROM p_plan_document->'source_manifest_sha256'
           OR v_existing.plan_document->'source_snapshot_ref'
                IS DISTINCT FROM p_plan_document->'source_snapshot_ref'
           OR v_existing.plan_document->'security_context_fingerprint'
                IS DISTINCT FROM p_plan_document->'security_context_fingerprint'
           OR v_existing.plan_document->'physical_intent'
                IS DISTINCT FROM p_plan_document->'physical_intent'
           OR v_existing.plan_document->'engine'
                IS DISTINCT FROM p_plan_document->'engine'
           OR v_existing.plan_document->'execution_mode'
                IS DISTINCT FROM p_plan_document->'execution_mode'
           OR v_existing_run.definition_version_id <> p_definition_version_id
           OR v_existing_run.orchestration_class <> p_orchestration_class
           OR v_existing_run.subject_context <> p_subject_context
           OR v_existing_run.idempotency_key <> p_idempotency_key
           OR v_existing_run.config_fingerprint <> p_config_fingerprint
           OR v_existing_run.submitted_by <> p_admitted_by THEN
            RAISE EXCEPTION 'metric query client request has conflicting evidence'
                USING ERRCODE = '40001';
        END IF;
        PERFORM gda_control.enqueue_metric_query_command(
            p_tenant_id, v_existing.run_id
        );
        RETURN v_existing.run_id;
    END IF;

    v_run_id := gda_control.admit_metric_query_execution_v138(
        p_tenant_id, p_run_id, p_client_request_id,
        p_definition_version_id, p_orchestration_class,
        p_subject_context, p_idempotency_key, p_config_fingerprint,
        p_output_resource_version_id, p_plan_artifact_id,
        p_plan_document, p_admitted_by, p_admitted_at
    );
    PERFORM gda_control.enqueue_metric_query_command(p_tenant_id, v_run_id);
    RETURN v_run_id;
END;
$$;

ALTER FUNCTION gda_control.start_metric_query_execution(
    text, uuid, integer, uuid, integer, text, text, text, text, timestamptz
) RENAME TO start_metric_query_execution_v138;

CREATE FUNCTION gda_control.start_metric_query_execution(
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

ALTER FUNCTION gda_control.complete_metric_query_execution(
    text, uuid, integer, uuid, uuid, uuid, uuid, integer, text, text,
    bigint, bigint, bigint, bigint, text, text, text, bigint, jsonb,
    text, text, text, timestamptz
) RENAME TO complete_metric_query_execution_v138;

CREATE FUNCTION gda_control.complete_metric_query_execution(
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

-- Existing pre-139 admissions receive the same stable command on upgrade.
DO $$
DECLARE
    v_admission RECORD;
BEGIN
    FOR v_admission IN
        SELECT tenant_id, run_id
        FROM gda_control.metric_query_execution_admission
        ORDER BY tenant_id, run_id
    LOOP
        PERFORM set_config('app.current_tenant', v_admission.tenant_id, true);
        PERFORM gda_control.enqueue_metric_query_command(
            v_admission.tenant_id, v_admission.run_id
        );
    END LOOP;
END;
$$;

REVOKE ALL ON FUNCTION gda_control.metric_query_command_uuid(text)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.enqueue_metric_query_command(text, uuid)
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.admit_metric_query_execution_v138(
    text, uuid, text, uuid, text, jsonb, text, text, uuid, uuid,
    jsonb, text, timestamptz
) FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.start_metric_query_execution_v138(
    text, uuid, integer, uuid, integer, text, text, text, text, timestamptz
) FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.complete_metric_query_execution_v138(
    text, uuid, integer, uuid, uuid, uuid, uuid, integer, text, text,
    bigint, bigint, bigint, bigint, text, text, text, bigint, jsonb,
    text, text, text, timestamptz
) FROM PUBLIC, gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.admit_metric_query_execution(
    text, uuid, text, uuid, text, jsonb, text, text, uuid, uuid,
    jsonb, text, timestamptz
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.start_metric_query_execution(
    text, uuid, integer, uuid, integer, text, text, text, text, timestamptz
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.complete_metric_query_execution(
    text, uuid, integer, uuid, uuid, uuid, uuid, integer, text, text,
    bigint, bigint, bigint, bigint, text, text, text, bigint, jsonb,
    text, text, text, timestamptz
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION gda_control.admit_metric_query_execution(
    text, uuid, text, uuid, text, jsonb, text, text, uuid, uuid,
    jsonb, text, timestamptz
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.start_metric_query_execution(
    text, uuid, integer, uuid, integer, text, text, text, text, timestamptz
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.complete_metric_query_execution(
    text, uuid, integer, uuid, uuid, uuid, uuid, integer, text, text,
    bigint, bigint, bigint, bigint, text, text, text, bigint, jsonb,
    text, text, text, timestamptz
) TO gda_control_gateway;
