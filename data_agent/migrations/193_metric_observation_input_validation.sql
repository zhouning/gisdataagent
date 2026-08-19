-- 193: Add bounded metric-observation dimension and spatial-ref validation.

ALTER FUNCTION gda_control.record_metric_observation(
    TEXT, UUID, UUID, TEXT, JSONB, TIMESTAMPTZ, TIMESTAMPTZ, TEXT, TEXT
) RENAME TO record_metric_observation_v192;

REVOKE ALL ON FUNCTION gda_control.record_metric_observation_v192(
    TEXT, UUID, UUID, TEXT, JSONB, TIMESTAMPTZ, TIMESTAMPTZ, TEXT, TEXT
) FROM PUBLIC, gda_control_gateway;

CREATE FUNCTION gda_control.record_metric_observation(
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
    v_dimension_count INTEGER;
BEGIN
    IF jsonb_typeof(p_dimensions) <> 'object'
       OR p_spatial_ref IS NOT NULL
          AND p_spatial_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/'
              '(feature|grid|administrative_unit|catchment)/'
              '[a-z0-9][a-z0-9._-]{0,127}$' THEN
        RAISE EXCEPTION 'metric observation projection input is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT count(*) INTO v_dimension_count
      FROM jsonb_object_keys(p_dimensions);
    IF v_dimension_count > 100
       OR EXISTS (
            SELECT 1
              FROM jsonb_object_keys(p_dimensions) AS dimension_name
             WHERE dimension_name !~ '^[a-z][a-z0-9_]{0,127}$'
        )
       OR EXISTS (
            SELECT 1
              FROM jsonb_each(p_dimensions)
                   AS dimension(dimension_name, dimension_value)
             WHERE jsonb_typeof(dimension_value)
                   NOT IN ('null', 'string', 'number', 'boolean')
                OR jsonb_typeof(dimension_value) = 'number'
                   AND dimension_value::text !~ '^-?(0|[1-9][0-9]*)$'
        ) THEN
        RAISE EXCEPTION 'metric observation dimensions are invalid'
            USING ERRCODE = '22023';
    END IF;

    RETURN gda_control.record_metric_observation_v192(
        p_tenant_id,
        p_run_id,
        p_observation_id,
        p_value_canonical,
        p_dimensions,
        p_window_start,
        p_window_end,
        p_spatial_ref,
        p_recorded_by
    );
END;
$$;

REVOKE ALL ON FUNCTION gda_control.record_metric_observation(
    TEXT, UUID, UUID, TEXT, JSONB, TIMESTAMPTZ, TIMESTAMPTZ, TEXT, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.record_metric_observation(
    TEXT, UUID, UUID, TEXT, JSONB, TIMESTAMPTZ, TIMESTAMPTZ, TEXT, TEXT
) TO gda_control_gateway;
