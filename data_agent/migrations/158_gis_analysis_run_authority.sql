-- Durable, version-bound PostGIS analysis runs and provider evidence.

ALTER TABLE gda_control.platform_command_outbox
    DROP CONSTRAINT IF EXISTS ck_gda_command_type;
ALTER TABLE gda_control.platform_command_outbox
    ADD CONSTRAINT ck_gda_command_type CHECK (
        command_type IN (
            'dolphinscheduler.dispatch',
            'dolphinscheduler.reconcile',
            'dolphinscheduler.cancel',
            'metric_query.execute',
            'gis_analysis.execute',
            'gis_analysis.cancel'
        )
    );

CREATE TABLE IF NOT EXISTS gda_control.gis_analysis_execution_admission (
    tenant_id TEXT NOT NULL,
    run_id UUID PRIMARY KEY,
    client_request_id TEXT NOT NULL,
    definition_version_id UUID NOT NULL,
    plan_artifact_id UUID NOT NULL,
    plan_document JSONB NOT NULL,
    plan_fingerprint CHAR(64) NOT NULL,
    cache_key CHAR(64) NOT NULL,
    operation TEXT NOT NULL,
    admitted_by TEXT NOT NULL,
    admitted_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_gis_analysis_admission_tenant_run
        UNIQUE (tenant_id, run_id),
    CONSTRAINT uq_gda_gis_analysis_admission_client
        UNIQUE (tenant_id, client_request_id),
    CONSTRAINT uq_gda_gis_analysis_admission_artifact
        UNIQUE (tenant_id, plan_artifact_id),
    CONSTRAINT fk_gda_gis_analysis_admission_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.platform_run(tenant_id, run_id),
    CONSTRAINT fk_gda_gis_analysis_admission_definition
        FOREIGN KEY (tenant_id, definition_version_id)
        REFERENCES gda_control.platform_definition_version(
            tenant_id, definition_version_id
        ),
    CONSTRAINT fk_gda_gis_analysis_admission_artifact
        FOREIGN KEY (tenant_id, plan_artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT ck_gda_gis_analysis_admission_client CHECK (
        client_request_id ~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{2,127}$'
    ),
    CONSTRAINT ck_gda_gis_analysis_admission_operation CHECK (
        operation IN ('buffer', 'clip', 'intersection')
    ),
    CONSTRAINT ck_gda_gis_analysis_admission_hashes CHECK (
        plan_fingerprint ~ '^[0-9a-f]{64}$'
        AND cache_key ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_gis_analysis_admission_actor CHECK (
        admitted_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'
    ),
    CONSTRAINT ck_gda_gis_analysis_admission_plan CHECK (
        jsonb_typeof(plan_document) = 'object'
        AND plan_document->>'schema_id' = 'gda.gis_analysis_plan.v1'
        AND plan_document->>'tenant_id' = tenant_id
        AND plan_document->>'operation' = operation
        AND plan_document->>'engine' = 'postgis'
        AND plan_document->>'execution_mode' = 'asynchronous'
        AND plan_document->>'algorithm_spec_fingerprint' ~ '^[0-9a-f]{64}$'
        AND plan_document->>'cache_key' = cache_key
        AND jsonb_typeof(plan_document->'sources') = 'array'
        AND jsonb_typeof(plan_document->'budget') = 'object'
    )
);

CREATE TABLE IF NOT EXISTS gda_control.gis_analysis_execution_observation (
    tenant_id TEXT NOT NULL,
    analysis_observation_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    attempt_no INTEGER NOT NULL,
    start_observation_id UUID NOT NULL,
    terminal_observation_id UUID NOT NULL,
    result_artifact_id UUID,
    outcome TEXT NOT NULL,
    features_returned BIGINT NOT NULL,
    bytes_scanned BIGINT NOT NULL,
    duration_ms BIGINT NOT NULL,
    result_sha256 CHAR(64),
    error_code TEXT,
    error_message TEXT,
    observed_at TIMESTAMPTZ NOT NULL,
    recorded_by TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gda_gis_analysis_observation_tenant_id
        UNIQUE (tenant_id, analysis_observation_id),
    CONSTRAINT uq_gda_gis_analysis_observation_run
        UNIQUE (tenant_id, run_id),
    CONSTRAINT uq_gda_gis_analysis_observation_terminal
        UNIQUE (tenant_id, terminal_observation_id),
    CONSTRAINT fk_gda_gis_analysis_observation_admission
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.gis_analysis_execution_admission(tenant_id, run_id),
    CONSTRAINT fk_gda_gis_analysis_observation_start
        FOREIGN KEY (tenant_id, start_observation_id)
        REFERENCES gda_control.framework_attempt_observation(
            tenant_id, observation_id
        ),
    CONSTRAINT fk_gda_gis_analysis_observation_terminal
        FOREIGN KEY (tenant_id, terminal_observation_id)
        REFERENCES gda_control.framework_attempt_observation(
            tenant_id, observation_id
        ),
    CONSTRAINT fk_gda_gis_analysis_observation_result
        FOREIGN KEY (tenant_id, result_artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT ck_gda_gis_analysis_observation_counts CHECK (
        attempt_no BETWEEN 1 AND 100
        AND features_returned >= 0
        AND bytes_scanned >= 0
        AND duration_ms BETWEEN 0 AND 1795000
    ),
    CONSTRAINT ck_gda_gis_analysis_observation_result CHECK (
        (
            outcome = 'succeeded'
            AND result_artifact_id IS NOT NULL
            AND result_sha256 ~ '^[0-9a-f]{64}$'
            AND error_code IS NULL
            AND error_message IS NULL
        ) OR (
            outcome = 'failed'
            AND result_artifact_id IS NULL
            AND result_sha256 IS NULL
            AND error_code ~ '^[a-z][a-z0-9_]{0,127}$'
            AND NULLIF(btrim(error_message), '') IS NOT NULL
        )
    ),
    CONSTRAINT ck_gda_gis_analysis_observation_actor CHECK (
        recorded_by ~ '^workload:[^[:space:]]{1,128}$'
    )
);

CREATE TABLE IF NOT EXISTS gda_control.gis_analysis_cancel_admission (
    tenant_id TEXT NOT NULL,
    run_id UUID PRIMARY KEY,
    cancel_request_id TEXT NOT NULL,
    cancel_command_id UUID NOT NULL,
    start_observation_id UUID NOT NULL,
    requested_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    backend_pid INTEGER NOT NULL,
    backend_start TIMESTAMPTZ NOT NULL,
    database_oid OID NOT NULL,
    user_oid OID NOT NULL,
    application_name TEXT NOT NULL,
    backend_binding_fingerprint CHAR(64) NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_gis_cancel_admission_tenant_run
        UNIQUE (tenant_id, run_id),
    CONSTRAINT uq_gda_gis_cancel_admission_request
        UNIQUE (tenant_id, cancel_request_id),
    CONSTRAINT uq_gda_gis_cancel_admission_command
        UNIQUE (tenant_id, cancel_command_id),
    CONSTRAINT fk_gda_gis_cancel_admission_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.gis_analysis_execution_admission(tenant_id, run_id),
    CONSTRAINT fk_gda_gis_cancel_admission_start
        FOREIGN KEY (tenant_id, start_observation_id)
        REFERENCES gda_control.framework_attempt_observation(
            tenant_id, observation_id
        ),
    CONSTRAINT ck_gda_gis_cancel_admission_request CHECK (
        cancel_request_id ~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{2,127}$'
    ),
    CONSTRAINT ck_gda_gis_cancel_admission_actor CHECK (
        requested_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'
    ),
    CONSTRAINT ck_gda_gis_cancel_admission_backend CHECK (
        backend_pid > 0
        AND application_name ~ '^gda-gis-analysis/[0-9a-f-]{36}$'
        AND backend_binding_fingerprint ~ '^[0-9a-f]{64}$'
    )
);

CREATE TABLE IF NOT EXISTS gda_control.gis_analysis_cancel_receipt (
    tenant_id TEXT NOT NULL,
    run_id UUID PRIMARY KEY,
    cancel_command_id UUID NOT NULL,
    cancel_observation_id UUID NOT NULL,
    outcome TEXT NOT NULL,
    backend_binding_fingerprint CHAR(64) NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    recorded_by TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gda_gis_cancel_receipt_tenant_run
        UNIQUE (tenant_id, run_id),
    CONSTRAINT uq_gda_gis_cancel_receipt_command
        UNIQUE (tenant_id, cancel_command_id),
    CONSTRAINT uq_gda_gis_cancel_receipt_observation
        UNIQUE (tenant_id, cancel_observation_id),
    CONSTRAINT fk_gda_gis_cancel_receipt_admission
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.gis_analysis_cancel_admission(tenant_id, run_id),
    CONSTRAINT ck_gda_gis_cancel_receipt_outcome CHECK (
        outcome IN ('signalled', 'not_found', 'unknown')
    ),
    CONSTRAINT ck_gda_gis_cancel_receipt_hash CHECK (
        backend_binding_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_gis_cancel_receipt_actor CHECK (
        recorded_by = 'workload:gis-analysis-postgis-canceller'
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_gis_analysis_admission_time
    ON gda_control.gis_analysis_execution_admission(tenant_id, admitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_gda_gis_analysis_observation_time
    ON gda_control.gis_analysis_execution_observation(tenant_id, observed_at DESC);

CREATE OR REPLACE FUNCTION gda_control.gis_analysis_command_uuid(
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
        public.digest(convert_to(p_dedupe_key, 'UTF8'), 'sha256'), 'hex'
    );
    RETURN (
        substr(v_hex, 1, 8) || '-' || substr(v_hex, 9, 4) || '-5' ||
        substr(v_hex, 14, 3) || '-8' || substr(v_hex, 18, 3) || '-' ||
        substr(v_hex, 21, 12)
    )::uuid;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.gis_analysis_backend_binding_fingerprint(
    p_backend_pid INTEGER,
    p_backend_start TIMESTAMPTZ,
    p_database_oid OID,
    p_user_oid OID,
    p_application_name TEXT
)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
STRICT
SET search_path = pg_catalog, public
AS $$
    SELECT encode(
        public.digest(
            convert_to(
                '{"application_name":' || to_json(p_application_name)::text ||
                ',"backend_pid":' || p_backend_pid::text ||
                ',"backend_start":' || to_json(
                    rtrim(
                        rtrim(
                            to_char(
                                p_backend_start AT TIME ZONE 'UTC',
                                'YYYY-MM-DD"T"HH24:MI:SS.US'
                            ),
                            '0'
                        ),
                        '.'
                    ) || 'Z'
                )::text ||
                ',"database_oid":' || p_database_oid::text ||
                ',"schema_id":"gda.gis_analysis_backend_binding.v1"' ||
                ',"user_oid":' || p_user_oid::text || '}',
                'UTF8'
            ),
            'sha256'
        ),
        'hex'
    )
$$;

CREATE OR REPLACE FUNCTION gda_control.admit_gis_analysis_execution(
    p_tenant_id TEXT,
    p_run_id UUID,
    p_client_request_id TEXT,
    p_definition_version_id UUID,
    p_subject_context JSONB,
    p_idempotency_key TEXT,
    p_cache_key TEXT,
    p_plan_artifact_id UUID,
    p_plan_document JSONB,
    p_admitted_by TEXT,
    p_admitted_at TIMESTAMPTZ,
    p_provider_subject TEXT
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_definition gda_control.platform_definition_version%ROWTYPE;
    v_existing gda_control.gis_analysis_execution_admission%ROWTYPE;
    v_existing_run gda_control.platform_run%ROWTYPE;
    v_source JSONB;
    v_source_count INTEGER;
    v_expected_sources INTEGER;
    v_plan_fingerprint TEXT;
    v_dedupe_key TEXT;
    v_command_id UUID;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'GIS analysis tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_client_request_id
            !~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{2,127}$'
       OR NULLIF(btrim(p_idempotency_key), '') IS NULL
       OR p_cache_key !~ '^[0-9a-f]{64}$'
       OR p_admitted_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR p_provider_subject <> 'workload:gis-analysis-postgis'
       OR p_admitted_at IS NULL
       OR jsonb_typeof(p_subject_context) <> 'object'
       OR p_subject_context->>'tenant_id' <> p_tenant_id
       OR jsonb_typeof(p_subject_context->'roles') <> 'array'
       OR p_admitted_by <> concat(
            p_subject_context->>'subject_type', ':',
            p_subject_context->>'subject_id'
       ) THEN
        RAISE EXCEPTION 'GIS analysis admission identity is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(p_plan_document) <> 'object'
       OR p_plan_document->>'schema_id' <> 'gda.gis_analysis_plan.v1'
       OR p_plan_document->>'tenant_id' <> p_tenant_id
       OR p_plan_document->>'engine' <> 'postgis'
       OR p_plan_document->>'execution_mode' <> 'asynchronous'
       OR p_plan_document->>'algorithm_id'
            NOT IN (
                'postgis.st_buffer_geography',
                'postgis.st_clip',
                'postgis.st_intersection'
            )
       OR p_plan_document->>'algorithm_version'
            <> 'gda.postgis-spatial-analysis.v1'
       OR p_plan_document->>'algorithm_spec_fingerprint' !~ '^[0-9a-f]{64}$'
       OR NOT (
            (
                p_plan_document->>'operation' = 'buffer'
                AND p_plan_document->>'algorithm_id'
                    = 'postgis.st_buffer_geography'
                AND p_plan_document->>'algorithm_spec_fingerprint'
                    = '28fd66b7ee57b3471d405813bd642941135fe11d00676ffa2470795510737ff2'
            )
            OR (
                p_plan_document->>'operation' = 'clip'
                AND p_plan_document->>'algorithm_id' = 'postgis.st_clip'
                AND p_plan_document->>'algorithm_spec_fingerprint'
                    = '59887943945a96ceebae7e76f7702e6d1703c9b21286a898c46d08acfaa729d1'
            )
            OR (
                p_plan_document->>'operation' = 'intersection'
                AND p_plan_document->>'algorithm_id'
                    = 'postgis.st_intersection'
                AND p_plan_document->>'algorithm_spec_fingerprint'
                    = 'da3cd4bbf6bbf3b61c81ce1001a8874aaa14c10643c2a529ed41159521556d8d'
            )
       )
       OR p_plan_document->>'operation'
            NOT IN ('buffer', 'clip', 'intersection')
       OR p_plan_document->>'cache_key' <> p_cache_key
       OR p_plan_document->>'security_context_fingerprint'
            !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_plan_document->'sources') <> 'array'
       OR jsonb_typeof(p_plan_document->'budget') <> 'object'
       OR (p_plan_document->'budget'->>'max_features')::bigint
            NOT BETWEEN 1 AND 100000
       OR (p_plan_document->'budget'->>'max_output_bytes')::bigint
            NOT BETWEEN 1024 AND 10000000000
       OR (p_plan_document->'budget'->>'max_duration_ms')::bigint
            NOT BETWEEN 100 AND 1795000 THEN
        RAISE EXCEPTION 'GIS analysis plan document is invalid'
            USING ERRCODE = '22023';
    END IF;
    v_expected_sources := CASE p_plan_document->>'operation'
        WHEN 'buffer' THEN 1 ELSE 2 END;
    SELECT jsonb_array_length(p_plan_document->'sources') INTO v_source_count;
    IF v_source_count <> v_expected_sources THEN
        RAISE EXCEPTION 'GIS analysis source count is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_existing
    FROM gda_control.gis_analysis_execution_admission
    WHERE tenant_id = p_tenant_id
      AND client_request_id = p_client_request_id
    FOR UPDATE;
    IF FOUND THEN
        SELECT * INTO STRICT v_existing_run
        FROM gda_control.platform_run
        WHERE tenant_id = p_tenant_id AND run_id = v_existing.run_id;
        IF v_existing.run_id <> p_run_id
           OR v_existing.definition_version_id <> p_definition_version_id
           OR v_existing.cache_key <> p_cache_key
           OR v_existing.plan_artifact_id <> p_plan_artifact_id
           OR v_existing.admitted_by <> p_admitted_by
           OR v_existing_run.subject_context <> p_subject_context
           OR v_existing_run.idempotency_key <> p_idempotency_key THEN
            RAISE EXCEPTION 'GIS analysis client request has conflicting evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN v_existing.run_id;
    END IF;

    SELECT * INTO v_definition
    FROM gda_control.platform_definition_version
    WHERE tenant_id = p_tenant_id
      AND definition_version_id = p_definition_version_id
      AND orchestration_class = 'dataops'
      AND capability_id = 'gis.analysis.execute'
      AND portability_class = 'engine_family'
      AND definition_document->>'schema'
            = 'gda.gis_analysis_executor_definition.v1'
      AND definition_document->>'engine' = 'postgis';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS analysis executor definition was not found'
            USING ERRCODE = '23503';
    END IF;

    FOR v_source IN
        SELECT value FROM jsonb_array_elements(p_plan_document->'sources')
    LOOP
        IF v_source->>'role' NOT IN ('input', 'overlay')
           OR (v_source->>'binding_id') !~
                '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
           OR (v_source->>'resource_version_id') !~
                '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
           OR v_source->>'content_sha256' !~ '^[0-9a-f]{64}$'
           OR v_source->>'authority_version_sha256' !~ '^[0-9a-f]{64}$'
           OR v_source->>'physical_binding_sha256' !~ '^[0-9a-f]{64}$'
           OR v_source->>'physical_relation'
                !~ '^[a-z_][a-z0-9_]{0,62}(\.[a-z_][a-z0-9_]{0,62})?$'
           OR v_source->>'geometry_column' !~ '^[a-z_][a-z0-9_]{0,62}$'
           OR (v_source->>'source_srid')::integer NOT BETWEEN 1 AND 999999 THEN
            RAISE EXCEPTION 'GIS source binding is invalid'
                USING ERRCODE = '22023';
        END IF;
        PERFORM 1
        FROM gda_control.nl2sql_source_binding_activation AS active
        JOIN gda_control.nl2sql_source_binding AS binding
          ON binding.tenant_id = active.tenant_id
         AND binding.binding_id = active.binding_id
        JOIN gda_control.resource_version AS version
          ON version.tenant_id = binding.tenant_id
         AND version.resource_version_id = binding.resource_version_id
         AND version.resource_urn = binding.resource_urn
         AND version.version_key = binding.version_key
         AND version.content_sha256 = binding.content_sha256
        WHERE active.tenant_id = p_tenant_id
          AND active.semantic_source_name = v_source->>'semantic_source_name'
          AND active.execution_engine = 'postgis'
          AND binding.binding_id = (v_source->>'binding_id')::uuid
          AND binding.resource_version_id
                = (v_source->>'resource_version_id')::uuid
          AND binding.content_sha256 = v_source->>'content_sha256'
          AND binding.authority_version_sha256
                = v_source->>'authority_version_sha256'
          AND binding.physical_binding_sha256
                = v_source->>'physical_binding_sha256'
          AND binding.source_mode = 'immutable_snapshot'
          AND regexp_replace(
                lower(binding.physical_locator),
                '^(postgis://)?(public\.)?', ''
              ) = regexp_replace(
                lower(v_source->>'physical_relation'),
                '^(public\.)?', ''
              );
        IF NOT FOUND THEN
            RAISE EXCEPTION 'GIS admission requires exact active immutable source evidence'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;

    v_plan_fingerprint := encode(
        digest(convert_to(p_plan_document::text, 'UTF8'), 'sha256'), 'hex'
    );
    INSERT INTO gda_control.platform_run (
        tenant_id, run_id, definition_version_id, orchestration_class,
        subject_context, idempotency_key, policy_refs, config_fingerprint,
        submitted_by, submitted_at
    ) VALUES (
        p_tenant_id, p_run_id, p_definition_version_id, 'dataops',
        p_subject_context, p_idempotency_key, '{}'::jsonb, p_cache_key,
        p_admitted_by, p_admitted_at
    );
    INSERT INTO gda_control.platform_run_input_binding (
        tenant_id, run_id, binding_name, resource_version_id, semantic_type
    )
    SELECT
        p_tenant_id,
        p_run_id,
        value->>'role',
        (value->>'resource_version_id')::uuid,
        'gda.gis_analysis.source.v1'
    FROM jsonb_array_elements(p_plan_document->'sources');
    INSERT INTO gda_control.artifact (
        tenant_id, artifact_id, artifact_key, artifact_role,
        storage_uri, media_type, content_sha256, size_bytes,
        run_id, resource_version_id, manifest, created_by, created_at
    ) VALUES (
        p_tenant_id, p_plan_artifact_id, 'gis-analysis-plan', 'execution_plan',
        'postgresql://gda-control/gis-analysis-plan/' || p_run_id::text,
        'application/vnd.gda.gis-analysis-plan+json',
        v_plan_fingerprint, octet_length(p_plan_document::text),
        p_run_id, NULL,
        jsonb_build_object(
            'schema', 'gda.gis_analysis_plan_artifact.v1',
            'operation', p_plan_document->>'operation',
            'algorithm_id', p_plan_document->>'algorithm_id',
            'algorithm_version', p_plan_document->>'algorithm_version',
            'algorithm_spec_fingerprint',
                p_plan_document->>'algorithm_spec_fingerprint',
            'cache_key', p_cache_key,
            'security_context_fingerprint',
                p_plan_document->>'security_context_fingerprint'
        ),
        p_admitted_by, p_admitted_at
    );
    INSERT INTO gda_control.gis_analysis_execution_admission (
        tenant_id, run_id, client_request_id, definition_version_id,
        plan_artifact_id, plan_document, plan_fingerprint, cache_key,
        operation, admitted_by, admitted_at
    ) VALUES (
        p_tenant_id, p_run_id, p_client_request_id, p_definition_version_id,
        p_plan_artifact_id, p_plan_document, v_plan_fingerprint, p_cache_key,
        p_plan_document->>'operation', p_admitted_by, p_admitted_at
    );

    v_dedupe_key := concat(
        'gis_analysis.execute:', p_tenant_id, ':', p_run_id::text, ':',
        p_plan_artifact_id::text, ':', v_plan_fingerprint
    );
    v_command_id := gda_control.gis_analysis_command_uuid(v_dedupe_key);
    INSERT INTO gda_control.platform_command_outbox (
        tenant_id, command_id, run_id, command_type,
        execution_plan_artifact_id, trigger_observation_id,
        dedupe_key, actor_subject, payload, status, attempt_count,
        max_attempts, available_at, created_at
    ) VALUES (
        p_tenant_id, v_command_id, p_run_id, 'gis_analysis.execute',
        p_plan_artifact_id, NULL, v_dedupe_key, p_provider_subject,
        jsonb_build_object(
            'schema', 'gda.gis_analysis_execute_command.v1',
            'run_id', p_run_id,
            'plan_artifact_id', p_plan_artifact_id,
            'plan_fingerprint', v_plan_fingerprint,
            'cache_key', p_cache_key,
            'engine', 'postgis',
            'execution_mode', 'asynchronous',
            'operation', p_plan_document->>'operation',
            'algorithm_id', p_plan_document->>'algorithm_id',
            'algorithm_version', p_plan_document->>'algorithm_version',
            'algorithm_spec_fingerprint',
                p_plan_document->>'algorithm_spec_fingerprint'
        ),
        'pending', 0, 5, p_admitted_at, p_admitted_at
    );
    RETURN p_run_id;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.start_gis_analysis_execution(
    p_tenant_id TEXT,
    p_run_id UUID,
    p_expected_state_version INTEGER,
    p_start_observation_id UUID,
    p_attempt_no INTEGER,
    p_external_namespace TEXT,
    p_external_run_id TEXT,
    p_external_attempt_id TEXT,
    p_backend_pid INTEGER,
    p_backend_start TIMESTAMPTZ,
    p_database_oid OID,
    p_user_oid OID,
    p_application_name TEXT,
    p_backend_binding_fingerprint TEXT,
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
    v_admission gda_control.gis_analysis_execution_admission%ROWTYPE;
    v_run gda_control.platform_run%ROWTYPE;
    v_existing gda_control.framework_attempt_observation%ROWTYPE;
    v_command gda_control.platform_command_outbox%ROWTYPE;
    v_evidence JSONB;
    v_fingerprint TEXT;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'GIS analysis tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_actor_subject <> 'workload:gis-analysis-postgis'
       OR p_attempt_no NOT BETWEEN 1 AND 100
       OR NULLIF(btrim(p_external_namespace), '') IS NULL
       OR NULLIF(btrim(p_external_run_id), '') IS NULL
       OR p_backend_pid <= 0
       OR p_backend_start IS NULL
       OR p_database_oid IS NULL
       OR p_user_oid IS NULL
       OR p_application_name !~ '^gda-gis-analysis/[0-9a-f-]{36}$'
       OR p_backend_binding_fingerprint !~ '^[0-9a-f]{64}$'
       OR p_backend_binding_fingerprint <>
            gda_control.gis_analysis_backend_binding_fingerprint(
                p_backend_pid, p_backend_start, p_database_oid,
                p_user_oid, p_application_name
            )
       OR p_backend_start > p_observed_at
       OR p_observed_at IS NULL THEN
        RAISE EXCEPTION 'GIS analysis start evidence is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_admission
    FROM gda_control.gis_analysis_execution_admission
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS analysis admission was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF p_observed_at < v_admission.admitted_at THEN
        RAISE EXCEPTION 'GIS provider start cannot predate admission'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_command
    FROM gda_control.platform_command_outbox
    WHERE tenant_id = p_tenant_id
      AND run_id = p_run_id
      AND command_type = 'gis_analysis.execute'
      AND actor_subject = p_actor_subject;
    IF NOT FOUND OR v_command.status NOT IN ('in_flight', 'done') THEN
        RAISE EXCEPTION 'GIS provider start requires a claimed governed command'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_run
    FROM gda_control.platform_run
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id
    FOR UPDATE;
    SELECT * INTO v_existing
    FROM gda_control.framework_attempt_observation
    WHERE tenant_id = p_tenant_id AND observation_id = p_start_observation_id;
    IF FOUND THEN
        IF v_existing.run_id <> p_run_id
           OR v_existing.attempt_no <> p_attempt_no
           OR v_existing.external_namespace <> p_external_namespace
           OR v_existing.external_run_id <> p_external_run_id
           OR v_existing.external_attempt_id IS DISTINCT FROM p_external_attempt_id
           OR v_existing.observed_state <> 'running'
           OR (v_existing.evidence->'backend'->>'backend_pid')::integer
                IS DISTINCT FROM p_backend_pid
           OR (v_existing.evidence->'backend'->>'backend_start')::timestamptz
                IS DISTINCT FROM p_backend_start
           OR (v_existing.evidence->'backend'->>'database_oid')::oid
                IS DISTINCT FROM p_database_oid
           OR (v_existing.evidence->'backend'->>'user_oid')::oid
                IS DISTINCT FROM p_user_oid
           OR v_existing.evidence->'backend'->>'application_name'
                IS DISTINCT FROM p_application_name
           OR v_existing.evidence->'backend'->>'binding_fingerprint'
                IS DISTINCT FROM p_backend_binding_fingerprint
           OR v_run.status <> 'running' THEN
            RAISE EXCEPTION 'GIS analysis start replay has conflicting evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN v_run.state_version;
    END IF;
    IF v_run.state_version <> p_expected_state_version
       OR v_run.status <> 'accepted' THEN
        RAISE EXCEPTION 'GIS analysis start state conflict'
            USING ERRCODE = '40001';
    END IF;
    v_evidence := jsonb_build_object(
        'schema', 'gda.gis_analysis_provider_start.v1',
        'plan_artifact_id', v_admission.plan_artifact_id,
        'plan_fingerprint', v_admission.plan_fingerprint,
        'cache_key', v_admission.cache_key,
        'operation', v_admission.operation,
        'engine', 'postgis',
        'backend', jsonb_build_object(
            'schema_id', 'gda.gis_analysis_backend_binding.v1',
            'backend_pid', p_backend_pid,
            'backend_start', p_backend_start,
            'database_oid', p_database_oid,
            'user_oid', p_user_oid,
            'application_name', p_application_name,
            'binding_fingerprint', p_backend_binding_fingerprint
        )
    );
    v_fingerprint := encode(
        digest(convert_to(v_evidence::text, 'UTF8'), 'sha256'), 'hex'
    );
    PERFORM gda_control.apply_platform_run_transition(
        p_tenant_id, p_run_id, p_expected_state_version,
        'dispatching', p_actor_subject, 'GIS provider accepted',
        jsonb_build_object(
            'schema', 'gda.gis_analysis_dispatch.v1',
            'plan_artifact_id', v_admission.plan_artifact_id
        )
    );
    PERFORM gda_control.apply_platform_run_transition(
        p_tenant_id, p_run_id, p_expected_state_version + 1,
        'running', p_actor_subject, 'GIS provider started', v_evidence
    );
    INSERT INTO gda_control.framework_attempt_observation (
        tenant_id, observation_id, run_id, attempt_no, framework_kind,
        external_namespace, external_run_id, external_attempt_id,
        observed_state, observation_sha256, evidence, observed_at
    ) VALUES (
        p_tenant_id, p_start_observation_id, p_run_id, p_attempt_no,
        'postgis', p_external_namespace, p_external_run_id,
        p_external_attempt_id, 'running', v_fingerprint,
        v_evidence, p_observed_at
    );
    RETURN p_expected_state_version + 2;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.complete_gis_analysis_execution(
    p_tenant_id TEXT,
    p_run_id UUID,
    p_expected_state_version INTEGER,
    p_analysis_observation_id UUID,
    p_start_observation_id UUID,
    p_terminal_observation_id UUID,
    p_result_artifact_id UUID,
    p_attempt_no INTEGER,
    p_outcome TEXT,
    p_features_returned BIGINT,
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
    v_admission gda_control.gis_analysis_execution_admission%ROWTYPE;
    v_run gda_control.platform_run%ROWTYPE;
    v_start gda_control.framework_attempt_observation%ROWTYPE;
    v_existing gda_control.gis_analysis_execution_observation%ROWTYPE;
    v_terminal_evidence JSONB;
    v_terminal_fingerprint TEXT;
    v_state INTEGER;
    v_budget JSONB;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'GIS analysis tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_actor_subject <> 'workload:gis-analysis-postgis'
       OR p_attempt_no NOT BETWEEN 1 AND 100
       OR p_outcome NOT IN ('succeeded', 'failed')
       OR p_features_returned < 0 OR p_bytes_scanned < 0
       OR p_duration_ms NOT BETWEEN 0 AND 1795000
       OR jsonb_typeof(p_result_manifest) <> 'object'
       OR p_observed_at IS NULL THEN
        RAISE EXCEPTION 'GIS analysis terminal evidence is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF p_outcome = 'succeeded' AND (
        p_result_artifact_id IS NULL
        OR NULLIF(btrim(p_result_storage_uri), '') IS NULL
        OR p_result_storage_uri !~ '^(file|s3|gs|obs|https|postgresql)://'
        OR p_result_media_type <> 'application/geo+json'
        OR p_result_sha256 !~ '^[0-9a-f]{64}$'
        OR p_result_size_bytes < 0
        OR p_result_manifest->>'result_schema' IS DISTINCT FROM
            'gda.gis_analysis_result.v1'
        OR p_result_manifest->>'format' IS DISTINCT FROM 'canonical-geojson'
        OR p_result_manifest->>'output_crs' IS NULL
        OR p_error_code IS NOT NULL OR p_error_message IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'successful GIS analysis requires result Artifact evidence'
            USING ERRCODE = '22023';
    ELSIF p_outcome = 'failed' AND (
        p_result_artifact_id IS NOT NULL
        OR p_result_storage_uri IS NOT NULL
        OR p_result_media_type IS NOT NULL
        OR p_result_sha256 IS NOT NULL
        OR p_result_size_bytes IS NOT NULL
        OR p_error_code !~ '^[a-z][a-z0-9_]{0,127}$'
        OR NULLIF(btrim(p_error_message), '') IS NULL
    ) THEN
        RAISE EXCEPTION 'failed GIS analysis requires error evidence only'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_existing
    FROM gda_control.gis_analysis_execution_observation
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF FOUND THEN
        SELECT * INTO STRICT v_run
        FROM gda_control.platform_run
        WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
        IF v_existing.analysis_observation_id <> p_analysis_observation_id
           OR v_existing.start_observation_id <> p_start_observation_id
           OR v_existing.terminal_observation_id <> p_terminal_observation_id
           OR v_existing.outcome <> p_outcome
           OR v_existing.result_sha256 IS DISTINCT FROM p_result_sha256
           OR v_run.status <> p_outcome THEN
            RAISE EXCEPTION 'GIS analysis completion replay has conflicting evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN v_run.state_version;
    END IF;

    SELECT * INTO v_admission
    FROM gda_control.gis_analysis_execution_admission
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS analysis admission was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF p_outcome = 'succeeded'
       AND p_result_manifest->>'operation' IS DISTINCT FROM v_admission.operation THEN
        RAISE EXCEPTION 'GIS result manifest operation does not match its admitted plan'
            USING ERRCODE = '23514';
    END IF;
    v_budget := v_admission.plan_document->'budget';
    IF p_features_returned > (v_budget->>'max_features')::bigint
       OR p_duration_ms > (v_budget->>'max_duration_ms')::bigint
       OR (
            p_outcome = 'succeeded'
            AND p_result_size_bytes > (v_budget->>'max_output_bytes')::bigint
       ) THEN
        RAISE EXCEPTION 'GIS provider result exceeds the admitted budget'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_run
    FROM gda_control.platform_run
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id
    FOR UPDATE;
    IF v_run.state_version <> p_expected_state_version
       OR v_run.status NOT IN ('running', 'reconciling') THEN
        RAISE EXCEPTION 'GIS analysis completion state conflict'
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
        RAISE EXCEPTION 'GIS analysis start observation was not found'
            USING ERRCODE = '23514';
    END IF;
    IF p_observed_at < v_start.observed_at THEN
        RAISE EXCEPTION 'GIS completion cannot predate provider start'
            USING ERRCODE = '22023';
    END IF;

    v_terminal_evidence := jsonb_build_object(
        'schema', 'gda.gis_analysis_provider_terminal.v1',
        'plan_artifact_id', v_admission.plan_artifact_id,
        'plan_fingerprint', v_admission.plan_fingerprint,
        'cache_key', v_admission.cache_key,
        'operation', v_admission.operation,
        'outcome', p_outcome,
        'features_returned', p_features_returned,
        'bytes_scanned', p_bytes_scanned,
        'duration_ms', p_duration_ms,
        'result_sha256', p_result_sha256,
        'error_code', p_error_code
    );
    v_terminal_fingerprint := encode(
        digest(convert_to(v_terminal_evidence::text, 'UTF8'), 'sha256'), 'hex'
    );
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
            p_tenant_id, p_result_artifact_id, 'gis-analysis-result', 'output',
            p_result_storage_uri, p_result_media_type, p_result_sha256,
            p_result_size_bytes, p_run_id, NULL,
            jsonb_build_object(
                'schema', 'gda.gis_analysis_result_artifact.v1',
                'plan_artifact_id', v_admission.plan_artifact_id,
                'cache_key', v_admission.cache_key,
                'operation', v_admission.operation,
                'features_returned', p_features_returned,
                'bytes_scanned', p_bytes_scanned,
                'duration_ms', p_duration_ms
            ) || p_result_manifest,
            p_actor_subject, p_observed_at
        );
    END IF;
    INSERT INTO gda_control.gis_analysis_execution_observation (
        tenant_id, analysis_observation_id, run_id, attempt_no,
        start_observation_id, terminal_observation_id, result_artifact_id,
        outcome, features_returned, bytes_scanned, duration_ms,
        result_sha256, error_code, error_message, observed_at, recorded_by
    ) VALUES (
        p_tenant_id, p_analysis_observation_id, p_run_id, p_attempt_no,
        p_start_observation_id, p_terminal_observation_id, p_result_artifact_id,
        p_outcome, p_features_returned, p_bytes_scanned, p_duration_ms,
        p_result_sha256, p_error_code, p_error_message, p_observed_at,
        p_actor_subject
    );
    v_state := gda_control.apply_platform_run_transition(
        p_tenant_id, p_run_id, p_expected_state_version,
        p_outcome, p_actor_subject,
        CASE p_outcome
            WHEN 'succeeded' THEN 'GIS result evidence accepted'
            ELSE 'GIS failure evidence accepted'
        END,
        jsonb_build_object(
            'schema', 'gda.gis_analysis_terminal_evidence.v1',
            'analysis_observation_id', p_analysis_observation_id,
            'terminal_observation_id', p_terminal_observation_id,
            'result_artifact_id', p_result_artifact_id,
            'plan_artifact_id', v_admission.plan_artifact_id,
            'outcome', p_outcome
        )
    );
    RETURN v_state;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.cancel_pending_gis_analysis_execution(
    p_tenant_id TEXT,
    p_run_id UUID,
    p_expected_state_version INTEGER,
    p_actor_subject TEXT,
    p_reason TEXT
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_run gda_control.platform_run%ROWTYPE;
    v_command gda_control.platform_command_outbox%ROWTYPE;
    v_state INTEGER;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'GIS cancellation tenant context is mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_actor_subject !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR NULLIF(btrim(p_reason), '') IS NULL THEN
        RAISE EXCEPTION 'GIS cancellation evidence is invalid'
            USING ERRCODE = '22023';
    END IF;
    PERFORM 1
    FROM gda_control.gis_analysis_execution_admission
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS analysis admission was not found'
            USING ERRCODE = 'P0002';
    END IF;
    SELECT * INTO v_run
    FROM gda_control.platform_run
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id
    FOR UPDATE;
    SELECT * INTO v_command
    FROM gda_control.platform_command_outbox
    WHERE tenant_id = p_tenant_id
      AND run_id = p_run_id
      AND command_type = 'gis_analysis.execute'
    FOR UPDATE;
    IF v_run.state_version <> p_expected_state_version
       OR v_run.status <> 'accepted'
       OR v_command.status <> 'pending' THEN
        RAISE EXCEPTION 'only a pending GIS analysis can be cancelled safely'
            USING ERRCODE = '40001';
    END IF;
    UPDATE gda_control.platform_command_outbox
    SET status = 'failed',
        claimed_by = NULL,
        claimed_until = NULL,
        last_error = 'cancelled before provider start',
        completed_at = clock_timestamp()
    WHERE tenant_id = p_tenant_id AND command_id = v_command.command_id;
    v_state := gda_control.apply_platform_run_transition(
        p_tenant_id, p_run_id, p_expected_state_version,
        'cancelled', p_actor_subject, p_reason,
        jsonb_build_object(
            'schema', 'gda.gis_analysis_prestart_cancel.v1',
            'command_id', v_command.command_id
        )
    );
    RETURN v_state;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.admit_running_gis_analysis_cancel(
    p_tenant_id TEXT,
    p_run_id UUID,
    p_cancel_request_id TEXT,
    p_expected_state_version INTEGER,
    p_actor_subject TEXT,
    p_reason TEXT,
    p_requested_at TIMESTAMPTZ,
    p_canceller_subject TEXT
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_run gda_control.platform_run%ROWTYPE;
    v_admission gda_control.gis_analysis_execution_admission%ROWTYPE;
    v_start gda_control.framework_attempt_observation%ROWTYPE;
    v_existing gda_control.gis_analysis_cancel_admission%ROWTYPE;
    v_backend JSONB;
    v_dedupe_key TEXT;
    v_command_id UUID;
    v_state INTEGER;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'GIS cancellation tenant context is mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_cancel_request_id
            !~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{2,127}$'
       OR p_actor_subject !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR NULLIF(btrim(p_reason), '') IS NULL
       OR length(p_reason) > 512
       OR p_requested_at IS NULL
       OR p_canceller_subject <> 'workload:gis-analysis-postgis-canceller' THEN
        RAISE EXCEPTION 'GIS cancellation evidence is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_existing
    FROM gda_control.gis_analysis_cancel_admission
    WHERE tenant_id = p_tenant_id AND cancel_request_id = p_cancel_request_id;
    IF FOUND THEN
        SELECT * INTO STRICT v_run
        FROM gda_control.platform_run
        WHERE tenant_id = p_tenant_id AND run_id = v_existing.run_id;
        IF v_existing.run_id <> p_run_id
           OR v_existing.requested_by <> p_actor_subject
           OR v_existing.reason <> p_reason
           OR v_run.status NOT IN ('cancelling', 'reconciling', 'cancelled') THEN
            RAISE EXCEPTION 'GIS cancel request has conflicting evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN v_run.state_version;
    END IF;
    SELECT * INTO v_admission
    FROM gda_control.gis_analysis_execution_admission
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS analysis admission was not found'
            USING ERRCODE = 'P0002';
    END IF;
    SELECT * INTO v_run
    FROM gda_control.platform_run
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id
    FOR UPDATE;
    IF v_run.state_version <> p_expected_state_version
       OR v_run.status <> 'running' THEN
        RAISE EXCEPTION 'only a running GIS analysis can admit backend cancellation'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO v_start
    FROM gda_control.framework_attempt_observation
    WHERE tenant_id = p_tenant_id
      AND run_id = p_run_id
      AND framework_kind = 'postgis'
      AND observed_state = 'running'
    ORDER BY observed_at DESC
    LIMIT 1;
    v_backend := v_start.evidence->'backend';
    IF NOT FOUND
       OR jsonb_typeof(v_backend) <> 'object'
       OR v_backend->>'schema_id' <> 'gda.gis_analysis_backend_binding.v1'
       OR (v_backend->>'backend_pid')::integer <= 0
       OR (v_backend->>'database_oid')::oid IS NULL
       OR (v_backend->>'user_oid')::oid IS NULL
       OR (v_backend->>'backend_start')::timestamptz IS NULL
       OR v_backend->>'application_name'
            !~ '^gda-gis-analysis/[0-9a-f-]{36}$'
       OR v_backend->>'binding_fingerprint' !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'GIS cancellation requires exact PostGIS backend evidence'
            USING ERRCODE = '23514';
    END IF;
    IF p_requested_at < v_start.observed_at THEN
        RAISE EXCEPTION 'GIS cancellation request cannot predate provider start'
            USING ERRCODE = '22023';
    END IF;
    v_dedupe_key := concat(
        'gis_analysis.cancel:', p_tenant_id, ':', p_run_id::text, ':',
        p_cancel_request_id, ':', v_backend->>'binding_fingerprint'
    );
    v_command_id := gda_control.gis_analysis_command_uuid(v_dedupe_key);
    INSERT INTO gda_control.gis_analysis_cancel_admission (
        tenant_id, run_id, cancel_request_id, cancel_command_id,
        start_observation_id, requested_by, reason, backend_pid,
        backend_start, database_oid, user_oid, application_name,
        backend_binding_fingerprint, requested_at
    ) VALUES (
        p_tenant_id, p_run_id, p_cancel_request_id, v_command_id,
        v_start.observation_id, p_actor_subject, p_reason,
        (v_backend->>'backend_pid')::integer,
        (v_backend->>'backend_start')::timestamptz,
        (v_backend->>'database_oid')::oid,
        (v_backend->>'user_oid')::oid,
        v_backend->>'application_name',
        v_backend->>'binding_fingerprint', p_requested_at
    );
    INSERT INTO gda_control.platform_command_outbox (
        tenant_id, command_id, run_id, command_type,
        execution_plan_artifact_id, trigger_observation_id,
        dedupe_key, actor_subject, payload, status, attempt_count,
        max_attempts, available_at, created_at
    ) VALUES (
        p_tenant_id, v_command_id, p_run_id, 'gis_analysis.cancel',
        v_admission.plan_artifact_id, v_start.observation_id,
        v_dedupe_key, p_canceller_subject,
        jsonb_build_object(
            'schema', 'gda.gis_analysis_cancel_command.v1',
            'run_id', p_run_id,
            'plan_artifact_id', v_admission.plan_artifact_id,
            'backend_pid', (v_backend->>'backend_pid')::integer,
            'backend_start', v_backend->>'backend_start',
            'database_oid', (v_backend->>'database_oid')::bigint,
            'user_oid', (v_backend->>'user_oid')::bigint,
            'application_name', v_backend->>'application_name',
            'backend_binding_fingerprint',
                v_backend->>'binding_fingerprint'
        ),
        'pending', 0, 5, p_requested_at, p_requested_at
    );
    v_state := gda_control.apply_platform_run_transition(
        p_tenant_id, p_run_id, p_expected_state_version,
        'cancelling', p_actor_subject, p_reason,
        jsonb_build_object(
            'schema', 'gda.gis_analysis_cancel_admission.v1',
            'cancel_request_id', p_cancel_request_id,
            'cancel_command_id', v_command_id,
            'start_observation_id', v_start.observation_id,
            'backend_binding_fingerprint',
                v_backend->>'binding_fingerprint'
        )
    );
    RETURN v_state;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_gis_analysis_cancel_signal(
    p_tenant_id TEXT,
    p_run_id UUID,
    p_cancel_command_id UUID,
    p_outcome TEXT,
    p_backend_binding_fingerprint TEXT,
    p_actor_subject TEXT,
    p_observed_at TIMESTAMPTZ
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_run gda_control.platform_run%ROWTYPE;
    v_cancel gda_control.gis_analysis_cancel_admission%ROWTYPE;
    v_command gda_control.platform_command_outbox%ROWTYPE;
    v_existing gda_control.gis_analysis_cancel_receipt%ROWTYPE;
    v_observation_id UUID;
    v_state INTEGER;
    v_receipt_exists BOOLEAN;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'GIS cancellation tenant context is mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_actor_subject <> 'workload:gis-analysis-postgis-canceller'
       OR p_outcome NOT IN ('signalled', 'not_found', 'unknown')
       OR p_backend_binding_fingerprint !~ '^[0-9a-f]{64}$'
       OR p_observed_at IS NULL THEN
        RAISE EXCEPTION 'GIS cancel signal evidence is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_cancel
    FROM gda_control.gis_analysis_cancel_admission
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS cancellation admission was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF p_observed_at < v_cancel.requested_at THEN
        RAISE EXCEPTION 'GIS cancel signal cannot predate its request'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_command
    FROM gda_control.platform_command_outbox
    WHERE tenant_id = p_tenant_id AND command_id = p_cancel_command_id;
    IF NOT FOUND
       OR v_cancel.cancel_command_id <> p_cancel_command_id
       OR v_cancel.backend_binding_fingerprint
            <> p_backend_binding_fingerprint
       OR v_command.command_type <> 'gis_analysis.cancel'
       OR v_command.actor_subject <> p_actor_subject
       OR v_command.status NOT IN ('in_flight', 'done') THEN
        RAISE EXCEPTION 'GIS cancel signal does not bind its governed command'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_existing
    FROM gda_control.gis_analysis_cancel_receipt
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    v_receipt_exists := FOUND;
    SELECT * INTO STRICT v_run
    FROM gda_control.platform_run
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id
    FOR UPDATE;
    IF v_receipt_exists THEN
        IF v_existing.cancel_command_id <> p_cancel_command_id
           OR v_existing.outcome <> p_outcome
           OR v_existing.backend_binding_fingerprint
                <> p_backend_binding_fingerprint THEN
            RAISE EXCEPTION 'GIS cancel signal replay has conflicting evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN v_run.state_version;
    END IF;
    IF v_run.status <> 'cancelling' THEN
        RAISE EXCEPTION 'GIS cancel signal found a conflicting Run state'
            USING ERRCODE = '40001';
    END IF;
    v_observation_id := gda_control.gis_analysis_command_uuid(
        concat(
            'gis-analysis-cancel-signal:', p_run_id::text, ':',
            p_cancel_command_id::text
        )
    );
    INSERT INTO gda_control.gis_analysis_cancel_receipt (
        tenant_id, run_id, cancel_command_id, cancel_observation_id,
        outcome, backend_binding_fingerprint, observed_at, recorded_by
    ) VALUES (
        p_tenant_id, p_run_id, p_cancel_command_id, v_observation_id,
        p_outcome, p_backend_binding_fingerprint, p_observed_at, p_actor_subject
    );
    IF p_outcome IN ('not_found', 'unknown') THEN
        v_state := gda_control.apply_platform_run_transition(
            p_tenant_id, p_run_id, v_run.state_version,
            'reconciling', p_actor_subject,
            'PostGIS cancellation outcome requires reconciliation',
            jsonb_build_object(
                'schema', 'gda.gis_analysis_cancel_unknown.v1',
                'cancel_command_id', p_cancel_command_id,
                'outcome', p_outcome,
                'backend_binding_fingerprint', p_backend_binding_fingerprint
            )
        );
        RETURN v_state;
    END IF;
    RETURN v_run.state_version;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.complete_cancelled_gis_analysis_execution(
    p_tenant_id TEXT,
    p_run_id UUID,
    p_start_observation_id UUID,
    p_backend_binding_fingerprint TEXT,
    p_actor_subject TEXT,
    p_observed_at TIMESTAMPTZ
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_run gda_control.platform_run%ROWTYPE;
    v_cancel gda_control.gis_analysis_cancel_admission%ROWTYPE;
    v_receipt gda_control.gis_analysis_cancel_receipt%ROWTYPE;
    v_start gda_control.framework_attempt_observation%ROWTYPE;
    v_observation_id UUID;
    v_evidence JSONB;
    v_fingerprint TEXT;
    v_state INTEGER;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'GIS cancellation tenant context is mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_actor_subject <> 'workload:gis-analysis-postgis'
       OR p_backend_binding_fingerprint !~ '^[0-9a-f]{64}$'
       OR p_observed_at IS NULL THEN
        RAISE EXCEPTION 'GIS cancelled terminal evidence is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_cancel
    FROM gda_control.gis_analysis_cancel_admission
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS cancellation admission was not found'
            USING ERRCODE = 'P0002';
    END IF;
    SELECT * INTO v_receipt
    FROM gda_control.gis_analysis_cancel_receipt
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS cancellation signal receipt was not found'
            USING ERRCODE = '23514';
    END IF;
    IF p_observed_at < v_receipt.observed_at THEN
        RAISE EXCEPTION 'GIS cancelled terminal cannot predate its signal receipt'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_start
    FROM gda_control.framework_attempt_observation
    WHERE tenant_id = p_tenant_id
      AND observation_id = p_start_observation_id
      AND run_id = p_run_id
      AND observed_state = 'running';
    IF NOT FOUND
       OR v_cancel.start_observation_id <> p_start_observation_id
       OR v_cancel.backend_binding_fingerprint
            <> p_backend_binding_fingerprint
       OR v_receipt.outcome <> 'signalled'
       OR v_receipt.backend_binding_fingerprint
            <> p_backend_binding_fingerprint THEN
        RAISE EXCEPTION 'GIS cancelled terminal lacks exact signal evidence'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO STRICT v_run
    FROM gda_control.platform_run
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id
    FOR UPDATE;
    IF v_run.status = 'cancelled' THEN
        RETURN v_run.state_version;
    END IF;
    IF v_run.status NOT IN ('cancelling', 'reconciling') THEN
        RAISE EXCEPTION 'GIS cancelled terminal found a conflicting Run state'
            USING ERRCODE = '40001';
    END IF;
    v_observation_id := gda_control.gis_analysis_command_uuid(
        concat(
            'gis-analysis-cancelled:', p_run_id::text, ':',
            p_start_observation_id::text
        )
    );
    v_evidence := jsonb_build_object(
        'schema', 'gda.gis_analysis_provider_cancelled.v1',
        'cancel_command_id', v_cancel.cancel_command_id,
        'cancel_observation_id', v_receipt.cancel_observation_id,
        'backend_binding_fingerprint', p_backend_binding_fingerprint
    );
    v_fingerprint := encode(
        digest(convert_to(v_evidence::text, 'UTF8'), 'sha256'), 'hex'
    );
    INSERT INTO gda_control.framework_attempt_observation (
        tenant_id, observation_id, run_id, attempt_no, framework_kind,
        external_namespace, external_run_id, external_attempt_id,
        observed_state, observation_sha256, evidence, observed_at
    ) VALUES (
        p_tenant_id, v_observation_id, p_run_id, v_start.attempt_no,
        v_start.framework_kind, v_start.external_namespace,
        v_start.external_run_id, v_start.external_attempt_id,
        'cancelled', v_fingerprint, v_evidence, p_observed_at
    ) ON CONFLICT (tenant_id, observation_id) DO NOTHING;
    v_state := gda_control.apply_platform_run_transition(
        p_tenant_id, p_run_id, v_run.state_version,
        'cancelled', p_actor_subject, 'PostGIS confirmed query cancellation',
        v_evidence
    );
    RETURN v_state;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_gis_analysis_admission_immutable
    ON gda_control.gis_analysis_execution_admission;
CREATE TRIGGER trg_gda_gis_analysis_admission_immutable
BEFORE UPDATE OR DELETE ON gda_control.gis_analysis_execution_admission
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_gis_analysis_observation_immutable
    ON gda_control.gis_analysis_execution_observation;
CREATE TRIGGER trg_gda_gis_analysis_observation_immutable
BEFORE UPDATE OR DELETE ON gda_control.gis_analysis_execution_observation
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_gis_cancel_admission_immutable
    ON gda_control.gis_analysis_cancel_admission;
CREATE TRIGGER trg_gda_gis_cancel_admission_immutable
BEFORE UPDATE OR DELETE ON gda_control.gis_analysis_cancel_admission
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_gis_cancel_receipt_immutable
    ON gda_control.gis_analysis_cancel_receipt;
CREATE TRIGGER trg_gda_gis_cancel_receipt_immutable
BEFORE UPDATE OR DELETE ON gda_control.gis_analysis_cancel_receipt
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.gis_analysis_execution_admission
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.gis_analysis_execution_admission
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gis_analysis_admission_tenant_isolation
    ON gda_control.gis_analysis_execution_admission;
CREATE POLICY gis_analysis_admission_tenant_isolation
    ON gda_control.gis_analysis_execution_admission
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.gis_analysis_execution_observation
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.gis_analysis_execution_observation
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gis_analysis_observation_tenant_isolation
    ON gda_control.gis_analysis_execution_observation;
CREATE POLICY gis_analysis_observation_tenant_isolation
    ON gda_control.gis_analysis_execution_observation
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.gis_analysis_cancel_admission
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.gis_analysis_cancel_admission
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gis_analysis_cancel_admission_tenant_isolation
    ON gda_control.gis_analysis_cancel_admission;
CREATE POLICY gis_analysis_cancel_admission_tenant_isolation
    ON gda_control.gis_analysis_cancel_admission
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.gis_analysis_cancel_receipt
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.gis_analysis_cancel_receipt
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gis_analysis_cancel_receipt_tenant_isolation
    ON gda_control.gis_analysis_cancel_receipt;
CREATE POLICY gis_analysis_cancel_receipt_tenant_isolation
    ON gda_control.gis_analysis_cancel_receipt
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.gis_analysis_execution_admission
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.gis_analysis_execution_observation
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.gis_analysis_cancel_admission
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.gis_analysis_cancel_receipt
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON gda_control.gis_analysis_execution_admission
    TO gda_control_gateway;
GRANT SELECT ON gda_control.gis_analysis_execution_observation
    TO gda_control_gateway;
GRANT SELECT ON gda_control.gis_analysis_cancel_admission
    TO gda_control_gateway;
GRANT SELECT ON gda_control.gis_analysis_cancel_receipt
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.admit_gis_analysis_execution(
    TEXT, UUID, TEXT, UUID, JSONB, TEXT, TEXT, UUID, JSONB,
    TEXT, TIMESTAMPTZ, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.gis_analysis_backend_binding_fingerprint(
    INTEGER, TIMESTAMPTZ, OID, OID, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.start_gis_analysis_execution(
    TEXT, UUID, INTEGER, UUID, INTEGER, TEXT, TEXT, TEXT,
    INTEGER, TIMESTAMPTZ, OID, OID, TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.complete_gis_analysis_execution(
    TEXT, UUID, INTEGER, UUID, UUID, UUID, UUID, INTEGER, TEXT,
    BIGINT, BIGINT, BIGINT, TEXT, TEXT, TEXT, BIGINT, JSONB,
    TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.cancel_pending_gis_analysis_execution(
    TEXT, UUID, INTEGER, TEXT, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.admit_running_gis_analysis_cancel(
    TEXT, UUID, TEXT, INTEGER, TEXT, TEXT, TIMESTAMPTZ, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_gis_analysis_cancel_signal(
    TEXT, UUID, UUID, TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.complete_cancelled_gis_analysis_execution(
    TEXT, UUID, UUID, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.admit_gis_analysis_execution(
    TEXT, UUID, TEXT, UUID, JSONB, TEXT, TEXT, UUID, JSONB,
    TEXT, TIMESTAMPTZ, TEXT
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.start_gis_analysis_execution(
    TEXT, UUID, INTEGER, UUID, INTEGER, TEXT, TEXT, TEXT,
    INTEGER, TIMESTAMPTZ, OID, OID, TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.complete_gis_analysis_execution(
    TEXT, UUID, INTEGER, UUID, UUID, UUID, UUID, INTEGER, TEXT,
    BIGINT, BIGINT, BIGINT, TEXT, TEXT, TEXT, BIGINT, JSONB,
    TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.cancel_pending_gis_analysis_execution(
    TEXT, UUID, INTEGER, TEXT, TEXT
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.admit_running_gis_analysis_cancel(
    TEXT, UUID, TEXT, INTEGER, TEXT, TEXT, TIMESTAMPTZ, TEXT
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_gis_analysis_cancel_signal(
    TEXT, UUID, UUID, TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.complete_cancelled_gis_analysis_execution(
    TEXT, UUID, UUID, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
