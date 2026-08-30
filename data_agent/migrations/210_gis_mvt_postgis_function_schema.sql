-- 210: Resolve PostGIS symbols explicitly inside the governed MVT function.
--
-- The function deliberately runs with a restricted SECURITY DEFINER
-- search_path. PostGIS is installed into the extension's public schema in the
-- supported Compose image, so unqualified ST_* calls resolve only when a
-- caller-controlled search_path leaks into a normal SQL session. Qualify every
-- PostGIS function instead of weakening the SECURITY DEFINER search_path.

CREATE OR REPLACE FUNCTION map_serving.gda_mvt_serving_projection_mvt(
    z INTEGER,
    x INTEGER,
    y INTEGER,
    query_params JSON
) RETURNS BYTEA
LANGUAGE plpgsql
STABLE
STRICT
PARALLEL SAFE
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, map_serving
AS $body$
DECLARE
    requested_id UUID;
    projection gda_control.mvt_serving_projection_version%ROWTYPE;
    property_sql TEXT;
    geometry_sql TEXT;
    tile_sql TEXT;
    tile BYTEA;
BEGIN
    BEGIN
        requested_id := NULLIF(query_params->>'serving_projection_version_id', '')::UUID;
    EXCEPTION WHEN invalid_text_representation THEN
        RETURN '\x'::BYTEA;
    END;

    SELECT * INTO projection
      FROM gda_control.mvt_serving_projection_version
     WHERE mvt_serving_projection_version_id = requested_id;
    IF NOT FOUND OR z < 0 OR z > 30 OR x < 0 OR y < 0
       OR x >= 2^z OR y >= 2^z THEN
        RETURN '\x'::BYTEA;
    END IF;

    SELECT string_agg(format('%I', property_name), ', ' ORDER BY ordinal)
      INTO property_sql
      FROM unnest(projection.property_allowlist)
           WITH ORDINALITY AS properties(property_name, ordinal);
    IF property_sql IS NULL OR property_sql = '' THEN
        property_sql := '';
    ELSE
        property_sql := ', ' || property_sql;
    END IF;

    geometry_sql := format(
        'public.ST_Force2D(CASE WHEN public.ST_IsValid(%1$I) '
        'THEN %1$I ELSE public.ST_MakeValid(%1$I) END)',
        projection.geometry_column
    );
    tile_sql := format(
        'SELECT public.ST_AsMVT(tile, %L, 4096, ''geom'') FROM ('
        'SELECT %I::text AS feature_id%s, '
        'public.ST_AsMVTGeom('
        'public.ST_Transform(public.ST_CurveToLine(public.ST_Intersection(%s, '
        'public.ST_MakeEnvelope($4, $5, $6, $7, %s))), 3857), '
        'public.ST_TileEnvelope($1, $2, $3), 4096, 64, true) AS geom '
        'FROM %I.%I '
        'WHERE %I IS NOT NULL AND NOT public.ST_IsEmpty(%I) '
        'AND %I && public.ST_MakeEnvelope($4, $5, $6, $7, %s) '
        'AND %I && public.ST_Transform(public.ST_TileEnvelope($1, $2, $3), %s) '
        'LIMIT %s) tile WHERE geom IS NOT NULL',
        'gda_mvt_serving_projection', projection.feature_id_column, property_sql,
        geometry_sql, projection.geometry_srid,
        projection.source_schema, projection.source_table,
        projection.geometry_column, projection.geometry_column,
        projection.geometry_column, projection.geometry_srid,
        projection.geometry_column, projection.geometry_srid,
        projection.max_features_per_tile
    );
    EXECUTE tile_sql INTO tile USING z, x, y,
        projection.allowed_spatial_extent[1], projection.allowed_spatial_extent[2],
        projection.allowed_spatial_extent[3], projection.allowed_spatial_extent[4];
    RETURN COALESCE(tile, '\x'::BYTEA);
END
$body$;

DO $migration$
BEGIN
    IF to_regprocedure(
        'map_serving.gda_mvt_serving_projection_mvt(integer,integer,integer,json)'
    ) IS NOT NULL THEN
        REVOKE ALL ON FUNCTION map_serving.gda_mvt_serving_projection_mvt(
            INTEGER, INTEGER, INTEGER, JSON
        ) FROM PUBLIC;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_user')
       AND to_regprocedure(
           'map_serving.gda_mvt_serving_projection_mvt(integer,integer,integer,json)'
       ) IS NOT NULL THEN
        GRANT USAGE ON SCHEMA map_serving TO agent_user;
        GRANT EXECUTE ON FUNCTION map_serving.gda_mvt_serving_projection_mvt(
            INTEGER, INTEGER, INTEGER, JSON
        ) TO agent_user;
    END IF;
END;
$migration$;
