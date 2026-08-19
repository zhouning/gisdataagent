-- 192: Append-only business observations projected from successful metric runs.
--
-- The query result remains an immutable Artifact. This table stores the small
-- business-facing projection and keeps every identity/version binding explicit.

CREATE TABLE IF NOT EXISTS gda_control.metric_observation (
    tenant_id TEXT NOT NULL,
    observation_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    query_observation_id UUID NOT NULL,
    result_artifact_id UUID NOT NULL,
    metric_version_ref TEXT NOT NULL,
    metric_fingerprint CHAR(64) NOT NULL,
    projection_version_ref TEXT NOT NULL,
    projection_fingerprint CHAR(64) NOT NULL,
    output_resource_version_id UUID NOT NULL,
    value_canonical TEXT NOT NULL,
    unit TEXT NOT NULL,
    dimensions JSONB NOT NULL DEFAULT '{}'::jsonb,
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,
    spatial_ref TEXT,
    observed_at TIMESTAMPTZ NOT NULL,
    recorded_by TEXT NOT NULL,
    observation_fingerprint CHAR(64) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gda_metric_observation_tenant_id
        UNIQUE (tenant_id, observation_id),
    CONSTRAINT uq_gda_metric_observation_run
        UNIQUE (tenant_id, run_id),
    CONSTRAINT fk_gda_metric_observation_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.metric_query_execution_admission(tenant_id, run_id),
    CONSTRAINT fk_gda_metric_observation_query
        FOREIGN KEY (tenant_id, query_observation_id)
        REFERENCES gda_control.metric_query_execution_observation(
            tenant_id, query_observation_id
        ),
    CONSTRAINT fk_gda_metric_observation_artifact
        FOREIGN KEY (tenant_id, result_artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT fk_gda_metric_observation_output
        FOREIGN KEY (tenant_id, output_resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT ck_gda_metric_observation_value CHECK (
        value_canonical ~ '^-?(0|[1-9][0-9]*)(\.[0-9]+)?$'
    ),
    CONSTRAINT ck_gda_metric_observation_unit CHECK (
        NULLIF(btrim(unit), '') IS NOT NULL AND char_length(unit) <= 64
    ),
    CONSTRAINT ck_gda_metric_observation_dimensions CHECK (
        jsonb_typeof(dimensions) = 'object'
    ),
    CONSTRAINT ck_gda_metric_observation_window CHECK (
        window_end IS NULL OR window_start IS NULL OR window_end >= window_start
    ),
    CONSTRAINT ck_gda_metric_observation_actor CHECK (
        recorded_by = 'workload:metric-observation-projector'
    ),
    CONSTRAINT ck_gda_metric_observation_hash CHECK (
        metric_fingerprint ~ '^[0-9a-f]{64}$'
        AND projection_fingerprint ~ '^[0-9a-f]{64}$'
        AND observation_fingerprint ~ '^[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_metric_observation_metric_time
    ON gda_control.metric_observation(
        tenant_id, metric_version_ref, observed_at DESC
    );

CREATE OR REPLACE FUNCTION gda_control.record_metric_observation(
    p_tenant_id TEXT,
    p_run_id UUID,
    p_observation_id UUID,
    p_value_canonical TEXT,
    p_dimensions JSONB,
    p_window_start TIMESTAMPTZ,
    p_window_end TIMESTAMPTZ,
    p_spatial_ref TEXT,
    p_recorded_by TEXT
)
RETURNS UUID
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
    v_existing gda_control.metric_observation%ROWTYPE;
    v_payload JSONB;
    v_fingerprint TEXT;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'metric observation tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_value_canonical !~ '^-?(0|[1-9][0-9]*)(\.[0-9]+)?$'
       OR jsonb_typeof(p_dimensions) <> 'object'
       OR p_window_end IS NOT NULL AND p_window_start IS NOT NULL
          AND p_window_end < p_window_start
       OR p_recorded_by <> 'workload:metric-observation-projector' THEN
        RAISE EXCEPTION 'metric observation projection input is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_admission
      FROM gda_control.metric_query_execution_admission
     WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'metric query admission was not found'
            USING ERRCODE = 'P0002';
    END IF;
    SELECT * INTO v_query
      FROM gda_control.metric_query_execution_observation
     WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF NOT FOUND OR v_query.outcome <> 'succeeded'
       OR v_query.result_artifact_id IS NULL
       OR v_query.result_sha256 IS NULL THEN
        RAISE EXCEPTION 'metric query has no successful result evidence'
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

    SELECT * INTO v_existing
      FROM gda_control.metric_observation
     WHERE tenant_id = p_tenant_id AND run_id = p_run_id
     FOR UPDATE;
    IF FOUND THEN
        IF v_existing.observation_id <> p_observation_id
           OR v_existing.value_canonical <> p_value_canonical
           OR v_existing.dimensions IS DISTINCT FROM p_dimensions
           OR v_existing.window_start IS DISTINCT FROM p_window_start
           OR v_existing.window_end IS DISTINCT FROM p_window_end
           OR v_existing.spatial_ref IS DISTINCT FROM p_spatial_ref THEN
            RAISE EXCEPTION 'metric observation replay has conflicting projection input'
                USING ERRCODE = '40001';
        END IF;
        RETURN v_existing.observation_id;
    END IF;

    v_payload := jsonb_build_object(
        'schema_id', 'gda.metric_observation.v1',
        'tenant_id', p_tenant_id,
        'observation_id', p_observation_id::text,
        'run_id', p_run_id::text,
        'query_observation_id', v_query.query_observation_id::text,
        'result_artifact_id', v_query.result_artifact_id::text,
        'metric_version_ref', v_admission.metric_version_ref,
        'metric_fingerprint', v_admission.metric_fingerprint,
        'projection_version_ref', v_admission.projection_version_ref,
        'projection_fingerprint', v_admission.projection_fingerprint,
        'output_resource_version_id', v_admission.output_resource_version_id::text,
        'value', p_value_canonical,
        'unit', v_unit,
        'dimensions', p_dimensions,
        'window_start', CASE
            WHEN p_window_start IS NULL THEN 'null'::jsonb
            ELSE to_jsonb(to_char(
                p_window_start AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
            ))
        END,
        'window_end', CASE
            WHEN p_window_end IS NULL THEN 'null'::jsonb
            ELSE to_jsonb(to_char(
                p_window_end AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
            ))
        END,
        'spatial_ref', p_spatial_ref,
        'observed_at', to_jsonb(to_char(
            v_query.observed_at AT TIME ZONE 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
        )),
        'recorded_by', p_recorded_by
    );
    v_fingerprint := encode(
        digest(convert_to(v_payload::text, 'UTF8'), 'sha256'),
        'hex'
    );
    INSERT INTO gda_control.metric_observation (
        tenant_id, observation_id, run_id, query_observation_id,
        result_artifact_id, metric_version_ref, metric_fingerprint,
        projection_version_ref, projection_fingerprint,
        output_resource_version_id, value_canonical, unit, dimensions,
        window_start, window_end, spatial_ref, observed_at, recorded_by,
        observation_fingerprint
    ) VALUES (
        p_tenant_id, p_observation_id, p_run_id, v_query.query_observation_id,
        v_query.result_artifact_id, v_admission.metric_version_ref,
        v_admission.metric_fingerprint, v_admission.projection_version_ref,
        v_admission.projection_fingerprint, v_admission.output_resource_version_id,
        p_value_canonical, v_unit, p_dimensions, p_window_start, p_window_end,
        p_spatial_ref, v_query.observed_at, p_recorded_by, v_fingerprint
    );
    RETURN p_observation_id;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_metric_observation_immutable
    ON gda_control.metric_observation;
CREATE TRIGGER trg_gda_metric_observation_immutable
BEFORE UPDATE OR DELETE ON gda_control.metric_observation
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.metric_observation ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.metric_observation FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.metric_observation;
CREATE POLICY tenant_isolation ON gda_control.metric_observation
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.metric_observation
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON gda_control.metric_observation TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.record_metric_observation(
    TEXT, UUID, UUID, TEXT, JSONB, TIMESTAMPTZ, TIMESTAMPTZ, TEXT, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.record_metric_observation(
    TEXT, UUID, UUID, TEXT, JSONB, TIMESTAMPTZ, TIMESTAMPTZ, TEXT, TEXT
) TO gda_control_gateway;
