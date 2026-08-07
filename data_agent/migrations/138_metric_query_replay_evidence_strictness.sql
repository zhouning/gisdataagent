-- Tighten metric-query provider replay checks without mutating migration 137.

CREATE TABLE IF NOT EXISTS gda_control.metric_query_execution_admission (
    tenant_id TEXT NOT NULL,
    run_id UUID PRIMARY KEY,
    client_request_id TEXT NOT NULL,
    definition_version_id UUID NOT NULL,
    plan_artifact_id UUID NOT NULL,
    plan_document JSONB NOT NULL,
    plan_fingerprint CHAR(64) NOT NULL,
    cache_key CHAR(64) NOT NULL,
    metric_version_ref TEXT NOT NULL,
    metric_fingerprint CHAR(64) NOT NULL,
    projection_version_ref TEXT NOT NULL,
    projection_fingerprint CHAR(64) NOT NULL,
    output_resource_version_id UUID NOT NULL,
    engine TEXT NOT NULL,
    execution_mode TEXT NOT NULL,
    admitted_by TEXT NOT NULL,
    admitted_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_metric_query_admission_tenant_run
        UNIQUE (tenant_id, run_id),
    CONSTRAINT uq_gda_metric_query_admission_client
        UNIQUE (tenant_id, client_request_id),
    CONSTRAINT uq_gda_metric_query_admission_artifact
        UNIQUE (tenant_id, plan_artifact_id),
    CONSTRAINT fk_gda_metric_query_admission_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.platform_run(tenant_id, run_id),
    CONSTRAINT fk_gda_metric_query_admission_definition
        FOREIGN KEY (tenant_id, definition_version_id)
        REFERENCES gda_control.platform_definition_version(
            tenant_id, definition_version_id
        ),
    CONSTRAINT fk_gda_metric_query_admission_artifact
        FOREIGN KEY (tenant_id, plan_artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT fk_gda_metric_query_admission_metric
        FOREIGN KEY (tenant_id, metric_version_ref, metric_fingerprint)
        REFERENCES gda_control.metric_definition_version(
            tenant_id, metric_version_ref, definition_fingerprint
        ),
    CONSTRAINT fk_gda_metric_query_admission_projection
        FOREIGN KEY (
            tenant_id, projection_version_ref, projection_fingerprint
        ) REFERENCES gda_control.metric_projection_version(
            tenant_id, projection_version_ref, projection_fingerprint
        ),
    CONSTRAINT fk_gda_metric_query_admission_output
        FOREIGN KEY (tenant_id, output_resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT ck_gda_metric_query_admission_client CHECK (
        client_request_id ~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{2,127}$'
    ),
    CONSTRAINT ck_gda_metric_query_admission_plan CHECK (
        jsonb_typeof(plan_document) = 'object'
        AND plan_document->>'schema_id' = 'gda.metric_query_plan.v1'
        AND plan_document->>'tenant_id' = tenant_id
        AND plan_document->>'metric_version_ref' = metric_version_ref
        AND plan_document->>'metric_fingerprint' = metric_fingerprint
        AND plan_document->>'projection_version_ref' = projection_version_ref
        AND plan_document->>'projection_fingerprint' = projection_fingerprint
        AND plan_document->>'output_resource_version_id'
            = output_resource_version_id::text
        AND plan_document->>'cache_key' = cache_key
        AND plan_document->>'engine' = engine
        AND plan_document->>'execution_mode' = execution_mode
    ),
    CONSTRAINT ck_gda_metric_query_admission_hashes CHECK (
        plan_fingerprint ~ '^[0-9a-f]{64}$'
        AND cache_key ~ '^[0-9a-f]{64}$'
        AND metric_fingerprint ~ '^[0-9a-f]{64}$'
        AND projection_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_metric_query_admission_engine CHECK (
        engine IN ('postgis', 'duckdb', 'iceberg_spark')
    ),
    CONSTRAINT ck_gda_metric_query_admission_mode CHECK (
        execution_mode IN ('synchronous', 'asynchronous')
        AND (
            (execution_mode = 'synchronous' AND engine IN ('postgis', 'duckdb'))
            OR (execution_mode = 'asynchronous' AND engine = 'iceberg_spark')
        )
    ),
    CONSTRAINT ck_gda_metric_query_admission_actor CHECK (
        admitted_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_metric_query_admission_metric
    ON gda_control.metric_query_execution_admission(
        tenant_id, metric_version_ref, admitted_at DESC
    );
CREATE INDEX IF NOT EXISTS idx_gda_metric_query_admission_projection
    ON gda_control.metric_query_execution_admission(
        tenant_id, projection_version_ref, admitted_at DESC
    );

CREATE TABLE IF NOT EXISTS gda_control.metric_query_execution_observation (
    tenant_id TEXT NOT NULL,
    query_observation_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    attempt_no INTEGER NOT NULL,
    start_observation_id UUID NOT NULL,
    terminal_observation_id UUID NOT NULL,
    result_artifact_id UUID,
    outcome TEXT NOT NULL,
    cache_status TEXT NOT NULL,
    rows_returned BIGINT NOT NULL,
    rows_scanned BIGINT NOT NULL,
    bytes_scanned BIGINT NOT NULL,
    duration_ms BIGINT NOT NULL,
    result_sha256 CHAR(64),
    error_code TEXT,
    error_message TEXT,
    observed_at TIMESTAMPTZ NOT NULL,
    recorded_by TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gda_metric_query_observation_tenant_id
        UNIQUE (tenant_id, query_observation_id),
    CONSTRAINT uq_gda_metric_query_observation_run
        UNIQUE (tenant_id, run_id),
    CONSTRAINT uq_gda_metric_query_observation_terminal
        UNIQUE (tenant_id, terminal_observation_id),
    CONSTRAINT fk_gda_metric_query_observation_admission
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.metric_query_execution_admission(tenant_id, run_id),
    CONSTRAINT fk_gda_metric_query_observation_start
        FOREIGN KEY (tenant_id, start_observation_id)
        REFERENCES gda_control.framework_attempt_observation(
            tenant_id, observation_id
        ),
    CONSTRAINT fk_gda_metric_query_observation_terminal
        FOREIGN KEY (tenant_id, terminal_observation_id)
        REFERENCES gda_control.framework_attempt_observation(
            tenant_id, observation_id
        ),
    CONSTRAINT fk_gda_metric_query_observation_result
        FOREIGN KEY (tenant_id, result_artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT ck_gda_metric_query_observation_attempt CHECK (
        attempt_no BETWEEN 1 AND 100
    ),
    CONSTRAINT ck_gda_metric_query_observation_outcome CHECK (
        outcome IN ('succeeded', 'failed')
    ),
    CONSTRAINT ck_gda_metric_query_observation_cache CHECK (
        cache_status IN ('hit', 'miss', 'bypass')
        AND (cache_status <> 'hit' OR outcome = 'succeeded')
    ),
    CONSTRAINT ck_gda_metric_query_observation_counts CHECK (
        rows_returned BETWEEN 0 AND 1000000000000000
        AND rows_scanned BETWEEN 0 AND 1000000000000000
        AND bytes_scanned BETWEEN 0 AND 1000000000000000000
        AND duration_ms BETWEEN 0 AND 86400000
    ),
    CONSTRAINT ck_gda_metric_query_observation_result CHECK (
        (
            outcome = 'succeeded'
            AND result_artifact_id IS NOT NULL
            AND result_sha256 IS NOT NULL
            AND result_sha256 ~ '^[0-9a-f]{64}$'
            AND error_code IS NULL
            AND error_message IS NULL
        ) OR (
            outcome = 'failed'
            AND result_artifact_id IS NULL
            AND result_sha256 IS NULL
            AND error_code IS NOT NULL
            AND error_code ~ '^[a-z][a-z0-9_]{0,127}$'
            AND NULLIF(btrim(error_message), '') IS NOT NULL
            AND char_length(error_message) <= 2048
        )
    ),
    CONSTRAINT ck_gda_metric_query_observation_actor CHECK (
        recorded_by ~ '^workload:[^[:space:]]{1,128}$'
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_metric_query_observation_time
    ON gda_control.metric_query_execution_observation(
        tenant_id, observed_at DESC
    );
CREATE INDEX IF NOT EXISTS idx_gda_metric_query_observation_cache
    ON gda_control.metric_query_execution_observation(
        tenant_id, cache_status, observed_at DESC
    );

CREATE OR REPLACE FUNCTION gda_control.admit_metric_query_execution(
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
    v_definition gda_control.platform_definition_version%ROWTYPE;
    v_projection gda_control.metric_projection_version%ROWTYPE;
    v_existing gda_control.metric_query_execution_admission%ROWTYPE;
    v_existing_run gda_control.platform_run%ROWTYPE;
    v_plan_fingerprint TEXT;
    v_expected_orchestration TEXT;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'metric query tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_client_request_id
            !~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{2,127}$'
       OR NULLIF(btrim(p_idempotency_key), '') IS NULL
       OR p_config_fingerprint !~ '^[0-9a-f]{64}$'
       OR p_admitted_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR p_admitted_at IS NULL
       OR jsonb_typeof(p_subject_context) <> 'object'
       OR p_subject_context->>'tenant_id' <> p_tenant_id
       OR jsonb_typeof(p_subject_context->'roles') <> 'array'
       OR p_subject_context->>'subject_type' NOT IN ('human', 'workload', 'agent')
       OR NULLIF(btrim(p_subject_context->>'subject_id'), '') IS NULL
       OR NULLIF(btrim(p_subject_context->>'purpose'), '') IS NULL
       OR p_admitted_by <> concat(
            p_subject_context->>'subject_type', ':',
            p_subject_context->>'subject_id'
       ) THEN
        RAISE EXCEPTION 'metric query admission identity is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(p_plan_document) <> 'object'
       OR p_plan_document->>'schema_id' <> 'gda.metric_query_plan.v1'
       OR p_plan_document->>'tenant_id' <> p_tenant_id
       OR p_plan_document->>'cache_key' <> p_config_fingerprint
       OR p_plan_document->>'metric_fingerprint' !~ '^[0-9a-f]{64}$'
       OR p_plan_document->>'projection_fingerprint' !~ '^[0-9a-f]{64}$'
       OR p_plan_document->>'security_context_fingerprint' !~ '^[0-9a-f]{64}$'
       OR p_plan_document->>'engine'
            NOT IN ('postgis', 'duckdb', 'iceberg_spark')
       OR p_plan_document->>'execution_mode'
            NOT IN ('synchronous', 'asynchronous')
       OR p_plan_document->>'output_resource_version_id'
            <> p_output_resource_version_id::text THEN
        RAISE EXCEPTION 'metric query plan document is invalid'
            USING ERRCODE = '22023';
    END IF;
    v_expected_orchestration := CASE
        WHEN p_plan_document->>'execution_mode' = 'synchronous'
            THEN 'synchronous'
        ELSE 'dataops'
    END;
    IF p_orchestration_class <> v_expected_orchestration
       OR (
            p_plan_document->>'execution_mode' = 'synchronous'
            AND p_plan_document->>'engine' NOT IN ('postgis', 'duckdb')
       )
       OR (
            p_plan_document->>'execution_mode' = 'asynchronous'
            AND p_plan_document->>'engine' <> 'iceberg_spark'
       ) THEN
        RAISE EXCEPTION 'metric query execution mode and engine are inconsistent'
            USING ERRCODE = '22023';
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
           OR v_existing.admitted_by <> p_admitted_by
           OR v_existing_run.subject_context <> p_subject_context
           OR v_existing_run.idempotency_key <> p_idempotency_key THEN
            RAISE EXCEPTION 'metric query client request has conflicting evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN v_existing.run_id;
    END IF;

    SELECT * INTO v_definition
    FROM gda_control.platform_definition_version
    WHERE tenant_id = p_tenant_id
      AND definition_version_id = p_definition_version_id
      AND orchestration_class = p_orchestration_class
      AND capability_id = 'metric.query.execute'
      AND portability_class = 'engine_family'
      AND definition_document->>'schema'
            = 'gda.metric_query_executor_definition.v1'
      AND definition_document->>'execution_mode'
            = p_plan_document->>'execution_mode';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'metric query executor definition was not found'
            USING ERRCODE = '23503';
    END IF;

    SELECT projection.* INTO v_projection
    FROM gda_control.metric_projection_version AS projection
    JOIN gda_control.metric_projection_activation AS projection_active
      ON projection_active.tenant_id = projection.tenant_id
     AND projection_active.active_version_ref = projection.projection_version_ref
     AND projection_active.active_fingerprint = projection.projection_fingerprint
    JOIN gda_control.metric_definition_activation AS metric_active
      ON metric_active.tenant_id = projection.tenant_id
     AND metric_active.active_version_ref = projection.metric_version_ref
     AND metric_active.active_fingerprint = projection.metric_fingerprint
    WHERE projection.tenant_id = p_tenant_id
      AND projection.metric_version_ref
            = p_plan_document->>'metric_version_ref'
      AND projection.metric_fingerprint
            = p_plan_document->>'metric_fingerprint'
      AND projection.projection_version_ref
            = p_plan_document->>'projection_version_ref'
      AND projection.projection_fingerprint
            = p_plan_document->>'projection_fingerprint'
      AND projection.output_resource_version_id = p_output_resource_version_id
      AND projection.source_manifest_sha256
            = p_plan_document->>'source_manifest_sha256'
      AND projection.source_snapshot_ref
            = p_plan_document->>'source_snapshot_ref'
      AND projection.projection_document->>'engine'
            = p_plan_document->>'engine';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'query admission requires exact active metric and projection evidence'
            USING ERRCODE = '23514';
    END IF;

    v_plan_fingerprint := encode(
        digest(convert_to(p_plan_document::text, 'UTF8'), 'sha256'),
        'hex'
    );
    INSERT INTO gda_control.platform_run (
        tenant_id, run_id, definition_version_id, orchestration_class,
        subject_context, idempotency_key, policy_refs, config_fingerprint,
        submitted_by, submitted_at
    ) VALUES (
        p_tenant_id, p_run_id, p_definition_version_id,
        p_orchestration_class, p_subject_context, p_idempotency_key,
        '{}'::jsonb, p_config_fingerprint, p_admitted_by, p_admitted_at
    );
    INSERT INTO gda_control.platform_run_input_binding (
        tenant_id, run_id, binding_name, resource_version_id, semantic_type
    ) VALUES (
        p_tenant_id, p_run_id, 'metric_source',
        p_output_resource_version_id, 'gda.metric_projection.source.v1'
    );
    INSERT INTO gda_control.artifact (
        tenant_id, artifact_id, artifact_key, artifact_role,
        storage_uri, media_type, content_sha256, size_bytes,
        run_id, resource_version_id, manifest, created_by, created_at
    ) VALUES (
        p_tenant_id, p_plan_artifact_id, 'metric-query-plan', 'execution_plan',
        'postgresql://gda-control/metric-query-plan/' || p_run_id::text,
        'application/vnd.gda.metric-query-plan+json',
        v_plan_fingerprint, octet_length(p_plan_document::text),
        p_run_id, NULL,
        jsonb_build_object(
            'schema', 'gda.metric_query_plan_artifact.v1',
            'metric_version_ref', p_plan_document->>'metric_version_ref',
            'metric_fingerprint', p_plan_document->>'metric_fingerprint',
            'projection_version_ref', p_plan_document->>'projection_version_ref',
            'projection_fingerprint', p_plan_document->>'projection_fingerprint',
            'cache_key', p_config_fingerprint,
            'security_context_fingerprint',
                p_plan_document->>'security_context_fingerprint'
        ),
        p_admitted_by, p_admitted_at
    );
    INSERT INTO gda_control.metric_query_execution_admission (
        tenant_id, run_id, client_request_id, definition_version_id,
        plan_artifact_id, plan_document, plan_fingerprint, cache_key,
        metric_version_ref, metric_fingerprint,
        projection_version_ref, projection_fingerprint,
        output_resource_version_id, engine, execution_mode,
        admitted_by, admitted_at
    ) VALUES (
        p_tenant_id, p_run_id, p_client_request_id,
        p_definition_version_id, p_plan_artifact_id,
        p_plan_document, v_plan_fingerprint, p_config_fingerprint,
        p_plan_document->>'metric_version_ref',
        p_plan_document->>'metric_fingerprint',
        p_plan_document->>'projection_version_ref',
        p_plan_document->>'projection_fingerprint',
        p_output_resource_version_id, p_plan_document->>'engine',
        p_plan_document->>'execution_mode', p_admitted_by, p_admitted_at
    );
    RETURN p_run_id;
END;
$$;

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
    v_run gda_control.platform_run%ROWTYPE;
    v_existing gda_control.framework_attempt_observation%ROWTYPE;
    v_framework TEXT;
    v_evidence JSONB;
    v_fingerprint TEXT;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'metric query tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_actor_subject IS NULL
       OR p_actor_subject !~ '^workload:[^[:space:]]{1,128}$'
       OR p_attempt_no IS NULL
       OR p_attempt_no NOT BETWEEN 1 AND 100
       OR NULLIF(btrim(p_external_namespace), '') IS NULL
       OR char_length(p_external_namespace) > 512
       OR NULLIF(btrim(p_external_run_id), '') IS NULL
       OR char_length(p_external_run_id) > 512
       OR char_length(p_external_attempt_id) > 512
       OR p_observed_at IS NULL THEN
        RAISE EXCEPTION 'metric query start evidence is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_admission
    FROM gda_control.metric_query_execution_admission
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'metric query admission was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF p_observed_at < v_admission.admitted_at THEN
        RAISE EXCEPTION 'metric query provider start cannot predate admission'
            USING ERRCODE = '22023';
    END IF;
    v_framework := CASE v_admission.engine
        WHEN 'postgis' THEN 'postgis'
        WHEN 'duckdb' THEN 'duckdb'
        ELSE 'spark'
    END;
    v_evidence := jsonb_build_object(
        'schema', 'gda.metric_query_provider_start.v1',
        'plan_artifact_id', v_admission.plan_artifact_id,
        'plan_fingerprint', v_admission.plan_fingerprint,
        'cache_key', v_admission.cache_key,
        'engine', v_admission.engine,
        'execution_mode', v_admission.execution_mode,
        'provider_subject', p_actor_subject
    );
    v_fingerprint := encode(
        digest(convert_to(v_evidence::text, 'UTF8'), 'sha256'), 'hex'
    );
    SELECT * INTO v_run
    FROM gda_control.platform_run
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id
    FOR UPDATE;
    SELECT * INTO v_existing
    FROM gda_control.framework_attempt_observation
    WHERE tenant_id = p_tenant_id
      AND observation_id = p_start_observation_id;
    IF FOUND THEN
        IF v_existing.run_id <> p_run_id
           OR v_existing.attempt_no <> p_attempt_no
           OR v_existing.external_namespace <> p_external_namespace
           OR v_existing.external_run_id <> p_external_run_id
           OR v_existing.external_attempt_id IS DISTINCT FROM p_external_attempt_id
           OR v_existing.framework_kind <> v_framework
           OR v_existing.observed_state <> 'running'
           OR v_existing.observation_sha256 <> v_fingerprint
           OR v_existing.evidence <> v_evidence
           OR v_existing.observed_at <> p_observed_at
           OR v_run.status <> 'running' THEN
            RAISE EXCEPTION 'metric query start replay has conflicting evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN v_run.state_version;
    END IF;
    IF v_run.state_version <> p_expected_state_version
       OR v_run.status <> 'accepted' THEN
        RAISE EXCEPTION 'metric query start state conflict'
            USING ERRCODE = '40001';
    END IF;
    PERFORM gda_control.apply_platform_run_transition(
        p_tenant_id, p_run_id, p_expected_state_version,
        'dispatching', p_actor_subject, 'metric query provider accepted',
        jsonb_build_object(
            'schema', 'gda.metric_query_dispatch.v1',
            'plan_artifact_id', v_admission.plan_artifact_id,
            'engine', v_admission.engine
        )
    );
    PERFORM gda_control.apply_platform_run_transition(
        p_tenant_id, p_run_id, p_expected_state_version + 1,
        'running', p_actor_subject, 'metric query provider started', v_evidence
    );
    INSERT INTO gda_control.framework_attempt_observation (
        tenant_id, observation_id, run_id, attempt_no, framework_kind,
        external_namespace, external_run_id, external_attempt_id,
        observed_state, observation_sha256, evidence, observed_at
    ) VALUES (
        p_tenant_id, p_start_observation_id, p_run_id, p_attempt_no,
        v_framework, p_external_namespace, p_external_run_id,
        p_external_attempt_id, 'running', v_fingerprint,
        v_evidence, p_observed_at
    );
    RETURN p_expected_state_version + 2;
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
    v_run gda_control.platform_run%ROWTYPE;
    v_start gda_control.framework_attempt_observation%ROWTYPE;
    v_existing gda_control.metric_query_execution_observation%ROWTYPE;
    v_existing_terminal gda_control.framework_attempt_observation%ROWTYPE;
    v_existing_result gda_control.artifact%ROWTYPE;
    v_terminal_evidence JSONB;
    v_terminal_fingerprint TEXT;
    v_result_manifest JSONB;
    v_state INTEGER;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'metric query tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_actor_subject IS NULL
       OR p_actor_subject !~ '^workload:[^[:space:]]{1,128}$'
       OR p_attempt_no IS NULL
       OR p_attempt_no NOT BETWEEN 1 AND 100
       OR p_outcome IS NULL
       OR p_outcome NOT IN ('succeeded', 'failed')
       OR p_cache_status IS NULL
       OR p_cache_status NOT IN ('hit', 'miss', 'bypass')
       OR (p_cache_status = 'hit' AND p_outcome <> 'succeeded')
       OR p_rows_returned IS NULL
       OR p_rows_returned NOT BETWEEN 0 AND 1000000000000000
       OR p_rows_scanned IS NULL
       OR p_rows_scanned NOT BETWEEN 0 AND 1000000000000000
       OR p_bytes_scanned IS NULL
       OR p_bytes_scanned NOT BETWEEN 0 AND 1000000000000000000
       OR p_duration_ms IS NULL
       OR p_duration_ms NOT BETWEEN 0 AND 86400000
       OR p_result_manifest IS NULL
       OR jsonb_typeof(p_result_manifest) <> 'object'
       OR p_observed_at IS NULL THEN
        RAISE EXCEPTION 'metric query terminal evidence is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF p_outcome = 'succeeded' AND (
        p_result_artifact_id IS NULL
        OR NULLIF(btrim(p_result_storage_uri), '') IS NULL
        OR char_length(p_result_storage_uri) > 512
        OR NULLIF(btrim(p_result_media_type), '') IS NULL
        OR char_length(p_result_media_type) > 256
        OR p_result_sha256 IS NULL
        OR p_result_sha256 !~ '^[0-9a-f]{64}$'
        OR p_result_size_bytes IS NULL
        OR p_result_size_bytes NOT BETWEEN 0 AND 1000000000000000000
        OR p_error_code IS NOT NULL
        OR p_error_message IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'successful metric query requires result Artifact evidence'
            USING ERRCODE = '22023';
    ELSIF p_outcome = 'failed' AND (
        p_result_artifact_id IS NOT NULL
        OR p_result_storage_uri IS NOT NULL
        OR p_result_media_type IS NOT NULL
        OR p_result_sha256 IS NOT NULL
        OR p_result_size_bytes IS NOT NULL
        OR p_error_code IS NULL
        OR p_error_code !~ '^[a-z][a-z0-9_]{0,127}$'
        OR NULLIF(btrim(p_error_message), '') IS NULL
        OR char_length(p_error_message) > 2048
    ) THEN
        RAISE EXCEPTION 'failed metric query requires error evidence only'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_admission
    FROM gda_control.metric_query_execution_admission
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'metric query admission was not found'
            USING ERRCODE = 'P0002';
    END IF;
    v_terminal_evidence := jsonb_build_object(
        'schema', 'gda.metric_query_provider_terminal.v1',
        'plan_artifact_id', v_admission.plan_artifact_id,
        'plan_fingerprint', v_admission.plan_fingerprint,
        'cache_key', v_admission.cache_key,
        'engine', v_admission.engine,
        'outcome', p_outcome,
        'cache_status', p_cache_status,
        'rows_returned', p_rows_returned,
        'rows_scanned', p_rows_scanned,
        'bytes_scanned', p_bytes_scanned,
        'duration_ms', p_duration_ms,
        'result_sha256', p_result_sha256,
        'error_code', p_error_code,
        'provider_subject', p_actor_subject
    );
    v_terminal_fingerprint := encode(
        digest(convert_to(v_terminal_evidence::text, 'UTF8'), 'sha256'),
        'hex'
    );
    v_result_manifest := p_result_manifest || jsonb_build_object(
        'schema', 'gda.metric_query_result_artifact.v1',
        'plan_artifact_id', v_admission.plan_artifact_id,
        'cache_key', v_admission.cache_key,
        'cache_status', p_cache_status,
        'rows_returned', p_rows_returned,
        'rows_scanned', p_rows_scanned,
        'bytes_scanned', p_bytes_scanned,
        'duration_ms', p_duration_ms
    );

    SELECT * INTO v_existing
    FROM gda_control.metric_query_execution_observation
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF FOUND THEN
        SELECT * INTO STRICT v_run
        FROM gda_control.platform_run
        WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
        SELECT * INTO STRICT v_existing_terminal
        FROM gda_control.framework_attempt_observation
        WHERE tenant_id = p_tenant_id
          AND observation_id = v_existing.terminal_observation_id;
        IF p_outcome = 'succeeded' THEN
            SELECT * INTO STRICT v_existing_result
            FROM gda_control.artifact
            WHERE tenant_id = p_tenant_id
              AND artifact_id = v_existing.result_artifact_id;
        END IF;
        IF v_existing.query_observation_id <> p_query_observation_id
           OR v_existing.start_observation_id <> p_start_observation_id
           OR v_existing.terminal_observation_id <> p_terminal_observation_id
           OR v_existing.result_artifact_id IS DISTINCT FROM p_result_artifact_id
           OR v_existing.attempt_no <> p_attempt_no
           OR v_existing.outcome <> p_outcome
           OR v_existing.cache_status <> p_cache_status
           OR v_existing.rows_returned <> p_rows_returned
           OR v_existing.rows_scanned <> p_rows_scanned
           OR v_existing.bytes_scanned <> p_bytes_scanned
           OR v_existing.duration_ms <> p_duration_ms
           OR v_existing.result_sha256 IS DISTINCT FROM p_result_sha256
           OR v_existing.error_code IS DISTINCT FROM p_error_code
           OR v_existing.error_message IS DISTINCT FROM p_error_message
           OR v_existing.observed_at <> p_observed_at
           OR v_existing.recorded_by <> p_actor_subject
           OR v_existing_terminal.observation_sha256 <> v_terminal_fingerprint
           OR v_existing_terminal.evidence <> v_terminal_evidence
           OR v_existing_terminal.observed_at <> p_observed_at
           OR (
                p_outcome = 'succeeded'
                AND (
                    v_existing_result.storage_uri <> p_result_storage_uri
                    OR v_existing_result.media_type <> p_result_media_type
                    OR v_existing_result.content_sha256 <> p_result_sha256
                    OR v_existing_result.size_bytes <> p_result_size_bytes
                    OR v_existing_result.manifest <> v_result_manifest
                    OR v_existing_result.created_by <> p_actor_subject
                    OR v_existing_result.created_at <> p_observed_at
                )
           )
           OR v_run.status <> p_outcome THEN
            RAISE EXCEPTION 'metric query completion replay has conflicting evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN v_run.state_version;
    END IF;

    SELECT * INTO v_run
    FROM gda_control.platform_run
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id
    FOR UPDATE;
    IF v_run.state_version <> p_expected_state_version
       OR v_run.status <> 'running' THEN
        RAISE EXCEPTION 'metric query completion state conflict'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO v_start
    FROM gda_control.framework_attempt_observation
    WHERE tenant_id = p_tenant_id
      AND observation_id = p_start_observation_id
      AND run_id = p_run_id
      AND attempt_no = p_attempt_no
      AND observed_state = 'running';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'metric query start observation was not found'
            USING ERRCODE = '23514';
    END IF;
    IF p_observed_at < v_start.observed_at THEN
        RAISE EXCEPTION 'metric query completion cannot predate provider start'
            USING ERRCODE = '22023';
    END IF;

    INSERT INTO gda_control.framework_attempt_observation (
        tenant_id, observation_id, run_id, attempt_no, framework_kind,
        external_namespace, external_run_id, external_attempt_id,
        observed_state, observation_sha256, evidence, observed_at
    ) VALUES (
        p_tenant_id, p_terminal_observation_id, p_run_id, p_attempt_no,
        v_start.framework_kind, v_start.external_namespace,
        v_start.external_run_id, v_start.external_attempt_id,
        p_outcome, v_terminal_fingerprint, v_terminal_evidence, p_observed_at
    );
    IF p_outcome = 'succeeded' THEN
        INSERT INTO gda_control.artifact (
            tenant_id, artifact_id, artifact_key, artifact_role,
            storage_uri, media_type, content_sha256, size_bytes,
            run_id, resource_version_id, manifest, created_by, created_at
        ) VALUES (
            p_tenant_id, p_result_artifact_id, 'metric-query-result', 'output',
            p_result_storage_uri, p_result_media_type, p_result_sha256,
            p_result_size_bytes, p_run_id, NULL,
            v_result_manifest,
            p_actor_subject, p_observed_at
        );
    END IF;
    INSERT INTO gda_control.metric_query_execution_observation (
        tenant_id, query_observation_id, run_id, attempt_no,
        start_observation_id, terminal_observation_id, result_artifact_id,
        outcome, cache_status, rows_returned, rows_scanned, bytes_scanned,
        duration_ms, result_sha256, error_code, error_message,
        observed_at, recorded_by
    ) VALUES (
        p_tenant_id, p_query_observation_id, p_run_id, p_attempt_no,
        p_start_observation_id, p_terminal_observation_id,
        p_result_artifact_id, p_outcome, p_cache_status,
        p_rows_returned, p_rows_scanned, p_bytes_scanned, p_duration_ms,
        p_result_sha256, p_error_code, p_error_message,
        p_observed_at, p_actor_subject
    );
    v_state := gda_control.apply_platform_run_transition(
        p_tenant_id, p_run_id, p_expected_state_version,
        p_outcome, p_actor_subject,
        CASE p_outcome
            WHEN 'succeeded' THEN 'metric query result evidence accepted'
            ELSE 'metric query failure evidence accepted'
        END,
        jsonb_build_object(
            'schema', 'gda.metric_query_terminal_evidence.v1',
            'query_observation_id', p_query_observation_id,
            'terminal_observation_id', p_terminal_observation_id,
            'result_artifact_id', p_result_artifact_id,
            'plan_artifact_id', v_admission.plan_artifact_id,
            'outcome', p_outcome,
            'cache_status', p_cache_status
        )
    );
    RETURN v_state;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_metric_query_admission_immutable
    ON gda_control.metric_query_execution_admission;
CREATE TRIGGER trg_gda_metric_query_admission_immutable
BEFORE UPDATE OR DELETE ON gda_control.metric_query_execution_admission
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_metric_query_observation_immutable
    ON gda_control.metric_query_execution_observation;
CREATE TRIGGER trg_gda_metric_query_observation_immutable
BEFORE UPDATE OR DELETE ON gda_control.metric_query_execution_observation
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.metric_query_execution_admission
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.metric_query_execution_admission
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.metric_query_execution_admission;
CREATE POLICY tenant_isolation
    ON gda_control.metric_query_execution_admission
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.metric_query_execution_observation
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.metric_query_execution_observation
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.metric_query_execution_observation;
CREATE POLICY tenant_isolation
    ON gda_control.metric_query_execution_observation
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.metric_query_execution_admission
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.metric_query_execution_observation
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON gda_control.metric_query_execution_admission
    TO gda_control_gateway;
GRANT SELECT ON gda_control.metric_query_execution_observation
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.admit_metric_query_execution(
    TEXT, UUID, TEXT, UUID, TEXT, JSONB, TEXT, TEXT, UUID, UUID,
    JSONB, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.start_metric_query_execution(
    TEXT, UUID, INTEGER, UUID, INTEGER, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.complete_metric_query_execution(
    TEXT, UUID, INTEGER, UUID, UUID, UUID, UUID, INTEGER, TEXT, TEXT,
    BIGINT, BIGINT, BIGINT, BIGINT, TEXT, TEXT, TEXT, BIGINT, JSONB,
    TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.admit_metric_query_execution(
    TEXT, UUID, TEXT, UUID, TEXT, JSONB, TEXT, TEXT, UUID, UUID,
    JSONB, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.start_metric_query_execution(
    TEXT, UUID, INTEGER, UUID, INTEGER, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.complete_metric_query_execution(
    TEXT, UUID, INTEGER, UUID, UUID, UUID, UUID, INTEGER, TEXT, TEXT,
    BIGINT, BIGINT, BIGINT, BIGINT, TEXT, TEXT, TEXT, BIGINT, JSONB,
    TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
