-- 195: Atomically project bounded grouped metric results into observations.

ALTER TABLE gda_control.metric_observation
    ADD COLUMN IF NOT EXISTS result_row_ordinal INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS result_row_fingerprint CHAR(64) NOT NULL
        DEFAULT repeat('0', 64);

ALTER TABLE gda_control.metric_observation
    DROP CONSTRAINT IF EXISTS uq_gda_metric_observation_run;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
         WHERE conrelid = 'gda_control.metric_observation'::regclass
           AND conname = 'uq_gda_metric_observation_run_row'
    ) THEN
        ALTER TABLE gda_control.metric_observation
            ADD CONSTRAINT uq_gda_metric_observation_run_row
            UNIQUE (tenant_id, run_id, result_row_ordinal);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
         WHERE conrelid = 'gda_control.metric_observation'::regclass
           AND conname = 'ck_gda_metric_observation_result_row'
    ) THEN
        ALTER TABLE gda_control.metric_observation
            ADD CONSTRAINT ck_gda_metric_observation_result_row CHECK (
                result_row_ordinal >= 0
                AND result_row_fingerprint ~ '^[0-9a-f]{64}$'
            );
    END IF;
END
$$;

CREATE OR REPLACE FUNCTION gda_control.record_metric_observation_batch(
    p_tenant_id TEXT,
    p_run_id UUID,
    p_rows JSONB,
    p_recorded_by TEXT
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_admission gda_control.metric_query_execution_admission%ROWTYPE;
    v_query gda_control.metric_query_execution_observation%ROWTYPE;
    v_run gda_control.platform_run%ROWTYPE;
    v_unit TEXT;
    v_row JSONB;
    v_position BIGINT;
    v_count INTEGER;
    v_existing_count INTEGER;
    v_existing gda_control.metric_observation%ROWTYPE;
    v_window_start TIMESTAMPTZ;
    v_window_end TIMESTAMPTZ;
    v_payload JSONB;
    v_fingerprint TEXT;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'metric observation tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_recorded_by <> 'workload:metric-observation-projector'
       OR jsonb_typeof(p_rows) <> 'array' THEN
        RAISE EXCEPTION 'metric observation batch input is invalid'
            USING ERRCODE = '22023';
    END IF;
    v_count := jsonb_array_length(p_rows);
    IF v_count < 1 OR v_count > 10000 THEN
        RAISE EXCEPTION 'metric observation batch size is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_admission
      FROM gda_control.metric_query_execution_admission
     WHERE tenant_id = p_tenant_id AND run_id = p_run_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'metric query admission was not found'
            USING ERRCODE = 'P0002';
    END IF;
    SELECT * INTO v_query
      FROM gda_control.metric_query_execution_observation
     WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF NOT FOUND OR v_query.outcome <> 'succeeded'
       OR v_query.result_artifact_id IS NULL
       OR v_query.result_sha256 IS NULL
       OR v_query.rows_returned <> v_count THEN
        RAISE EXCEPTION 'metric query has no complete successful result evidence'
            USING ERRCODE = '55000';
    END IF;
    SELECT * INTO STRICT v_run
      FROM gda_control.platform_run
     WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF v_run.status <> 'succeeded' THEN
        RAISE EXCEPTION 'metric query run is not terminally successful'
            USING ERRCODE = '55000';
    END IF;
    SELECT definition_document->>'unit' INTO v_unit
      FROM gda_control.metric_definition_version
     WHERE tenant_id = p_tenant_id
       AND metric_version_ref = v_admission.metric_version_ref
       AND definition_fingerprint = v_admission.metric_fingerprint;
    IF NULLIF(btrim(v_unit), '') IS NULL THEN
        RAISE EXCEPTION 'metric definition unit was not found'
            USING ERRCODE = '23503';
    END IF;

    FOR v_row, v_position IN
        SELECT value, ordinality
          FROM jsonb_array_elements(p_rows) WITH ORDINALITY
    LOOP
        IF jsonb_typeof(v_row) <> 'object'
           OR (SELECT count(*) FROM jsonb_object_keys(v_row)) <> 8
           OR NOT v_row ?& ARRAY[
                'observation_id', 'result_row_ordinal',
                'result_row_fingerprint', 'value_canonical', 'dimensions',
                'window_start', 'window_end', 'spatial_ref'
           ]
           OR (v_row->>'result_row_ordinal')::INTEGER <> v_position - 1
           OR v_row->>'result_row_fingerprint' !~ '^[0-9a-f]{64}$'
           OR v_row->>'value_canonical'
              !~ '^-?(0|[1-9][0-9]*)(\.[0-9]+)?$'
           OR jsonb_typeof(v_row->'dimensions') <> 'object'
           OR (SELECT count(*) FROM jsonb_object_keys(v_row->'dimensions')) > 100
           OR EXISTS (
                SELECT 1 FROM jsonb_object_keys(v_row->'dimensions') AS name
                 WHERE name !~ '^[a-z][a-z0-9_]{0,127}$'
           )
           OR EXISTS (
                SELECT 1
                  FROM jsonb_each(v_row->'dimensions') AS d(name, value)
                 WHERE jsonb_typeof(value) NOT IN ('null', 'string', 'number', 'boolean')
                    OR jsonb_typeof(value) = 'number'
                       AND value::text !~ '^-?(0|[1-9][0-9]*)$'
           )
           OR v_row->>'spatial_ref' IS NOT NULL
              AND v_row->>'spatial_ref' !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/'
                  '(feature|grid|administrative_unit|catchment)/'
                  '[a-z0-9][a-z0-9._-]{0,127}$' THEN
            RAISE EXCEPTION 'metric observation batch row is invalid'
                USING ERRCODE = '22023';
        END IF;
        PERFORM (v_row->>'observation_id')::UUID;
        v_window_start := (v_row->>'window_start')::TIMESTAMPTZ;
        v_window_end := (v_row->>'window_end')::TIMESTAMPTZ;
        IF v_window_start IS NOT NULL AND v_window_end IS NOT NULL
           AND v_window_end < v_window_start THEN
            RAISE EXCEPTION 'metric observation batch window is invalid'
                USING ERRCODE = '22023';
        END IF;
    END LOOP;

    SELECT count(*) INTO v_existing_count
      FROM gda_control.metric_observation
     WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF v_existing_count > 0 THEN
        IF v_existing_count <> v_count THEN
            RAISE EXCEPTION 'metric observation replay has a partial batch'
                USING ERRCODE = '40001';
        END IF;
        FOR v_row, v_position IN
            SELECT value, ordinality
              FROM jsonb_array_elements(p_rows) WITH ORDINALITY
        LOOP
            SELECT * INTO v_existing
              FROM gda_control.metric_observation
             WHERE tenant_id = p_tenant_id AND run_id = p_run_id
               AND result_row_ordinal = v_position - 1;
            IF NOT FOUND
               OR v_existing.observation_id <> (v_row->>'observation_id')::UUID
               OR v_existing.result_row_fingerprint
                  <> v_row->>'result_row_fingerprint'
               OR v_existing.value_canonical <> v_row->>'value_canonical'
               OR v_existing.dimensions IS DISTINCT FROM v_row->'dimensions'
               OR v_existing.window_start IS DISTINCT FROM
                  (v_row->>'window_start')::TIMESTAMPTZ
               OR v_existing.window_end IS DISTINCT FROM
                  (v_row->>'window_end')::TIMESTAMPTZ
               OR v_existing.spatial_ref IS DISTINCT FROM v_row->>'spatial_ref' THEN
                RAISE EXCEPTION 'metric observation replay has conflicting batch input'
                    USING ERRCODE = '40001';
            END IF;
        END LOOP;
        RETURN v_existing_count;
    END IF;

    FOR v_row, v_position IN
        SELECT value, ordinality
          FROM jsonb_array_elements(p_rows) WITH ORDINALITY
    LOOP
        v_window_start := (v_row->>'window_start')::TIMESTAMPTZ;
        v_window_end := (v_row->>'window_end')::TIMESTAMPTZ;
        v_payload := jsonb_build_object(
            'schema_id', 'gda.metric_observation.v1',
            'tenant_id', p_tenant_id,
            'observation_id', v_row->>'observation_id',
            'run_id', p_run_id::text,
            'query_observation_id', v_query.query_observation_id::text,
            'result_artifact_id', v_query.result_artifact_id::text,
            'metric_version_ref', v_admission.metric_version_ref,
            'metric_fingerprint', v_admission.metric_fingerprint,
            'projection_version_ref', v_admission.projection_version_ref,
            'projection_fingerprint', v_admission.projection_fingerprint,
            'output_resource_version_id', v_admission.output_resource_version_id::text,
            'value', v_row->>'value_canonical',
            'unit', v_unit,
            'dimensions', v_row->'dimensions',
            'window_start', CASE WHEN v_window_start IS NULL THEN 'null'::jsonb
                ELSE to_jsonb(to_char(v_window_start AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')) END,
            'window_end', CASE WHEN v_window_end IS NULL THEN 'null'::jsonb
                ELSE to_jsonb(to_char(v_window_end AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')) END,
            'spatial_ref', v_row->>'spatial_ref',
            'observed_at', to_jsonb(to_char(v_query.observed_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')),
            'recorded_by', p_recorded_by
        );
        v_fingerprint := encode(
            digest(convert_to(v_payload::text, 'UTF8'), 'sha256'), 'hex'
        );
        INSERT INTO gda_control.metric_observation (
            tenant_id, observation_id, run_id, query_observation_id,
            result_artifact_id, result_row_ordinal, result_row_fingerprint,
            metric_version_ref, metric_fingerprint, projection_version_ref,
            projection_fingerprint, output_resource_version_id,
            value_canonical, unit, dimensions, window_start, window_end,
            spatial_ref, observed_at, recorded_by, observation_fingerprint
        ) VALUES (
            p_tenant_id, (v_row->>'observation_id')::UUID, p_run_id,
            v_query.query_observation_id, v_query.result_artifact_id,
            v_position - 1, v_row->>'result_row_fingerprint',
            v_admission.metric_version_ref, v_admission.metric_fingerprint,
            v_admission.projection_version_ref, v_admission.projection_fingerprint,
            v_admission.output_resource_version_id, v_row->>'value_canonical',
            v_unit, v_row->'dimensions', v_window_start, v_window_end,
            v_row->>'spatial_ref', v_query.observed_at, p_recorded_by, v_fingerprint
        );
    END LOOP;
    RETURN v_count;
END;
$$;

REVOKE ALL ON FUNCTION gda_control.record_metric_observation_batch(
    TEXT, UUID, JSONB, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.record_metric_observation_batch(
    TEXT, UUID, JSONB, TEXT
) TO gda_control_gateway;
