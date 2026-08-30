-- 206: Additive hardening for the release-bound MVT serving projection.
--
-- This migration intentionally carries controls that were authored after 205
-- had already been applied.  Never revise an applied migration's checksum.

CREATE OR REPLACE FUNCTION gda_control.record_mvt_serving_projection_version(
    p_tenant_id TEXT,
    p_mvt_serving_projection_version_id UUID,
    p_service_definition_version_id UUID,
    p_layer_definition_version_id UUID,
    p_projection_key TEXT,
    p_version_key TEXT,
    p_predecessor_version_id UUID,
    p_source_output_resource_version_id UUID,
    p_source_schema TEXT,
    p_source_table TEXT,
    p_geometry_column TEXT,
    p_geometry_srid INTEGER,
    p_feature_id_column TEXT,
    p_property_allowlist TEXT[],
    p_allowed_spatial_extent DOUBLE PRECISION[],
    p_max_features_per_tile INTEGER,
    p_source_content_sha256 TEXT,
    p_projection_sha256 TEXT,
    p_created_by TEXT,
    p_created_at TIMESTAMPTZ
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_existing gda_control.mvt_serving_projection_version%ROWTYPE;
    v_layer_geometry_column TEXT;
    v_layer_source_output_resource_version_id UUID;
    v_layer_schema_contract JSONB;
    v_source_content_sha256 CHAR(64);
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'MVT serving projection tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_existing
      FROM gda_control.mvt_serving_projection_version
     WHERE tenant_id = p_tenant_id
       AND mvt_serving_projection_version_id = p_mvt_serving_projection_version_id;
    IF FOUND THEN
        IF v_existing.service_definition_version_id = p_service_definition_version_id
           AND v_existing.layer_definition_version_id = p_layer_definition_version_id
           AND v_existing.projection_key = p_projection_key
           AND v_existing.version_key = p_version_key
           AND v_existing.predecessor_version_id IS NOT DISTINCT FROM p_predecessor_version_id
           AND v_existing.source_output_resource_version_id = p_source_output_resource_version_id
           AND v_existing.source_schema = p_source_schema
           AND v_existing.source_table = p_source_table
           AND v_existing.geometry_column = p_geometry_column
           AND v_existing.geometry_srid = p_geometry_srid
           AND v_existing.feature_id_column = p_feature_id_column
           AND v_existing.property_allowlist = p_property_allowlist
           AND v_existing.allowed_spatial_extent = p_allowed_spatial_extent
           AND v_existing.max_features_per_tile = p_max_features_per_tile
           AND v_existing.source_content_sha256 = p_source_content_sha256
           AND v_existing.projection_sha256 = p_projection_sha256
           AND v_existing.created_by = p_created_by
           AND v_existing.created_at = p_created_at THEN
            RETURN p_mvt_serving_projection_version_id;
        END IF;
        RAISE EXCEPTION 'MVT serving projection identity has different immutable content'
            USING ERRCODE = '40001';
    END IF;

    SELECT layer.geometry_column, layer.source_output_resource_version_id,
           layer.schema_contract
      INTO v_layer_geometry_column, v_layer_source_output_resource_version_id,
           v_layer_schema_contract
      FROM gda_control.gis_service_definition_version AS definition
      JOIN gda_control.layer_definition_version AS layer
        ON layer.tenant_id = definition.tenant_id
       AND layer.service_definition_version_id = definition.service_definition_version_id
       AND layer.layer_definition_version_id = p_layer_definition_version_id
     WHERE definition.tenant_id = p_tenant_id
       AND definition.service_definition_version_id = p_service_definition_version_id
       AND definition.service_type = 'vector_tile';
    IF NOT FOUND
       OR v_layer_geometry_column <> p_geometry_column
       OR v_layer_source_output_resource_version_id <> p_source_output_resource_version_id THEN
        RAISE EXCEPTION 'MVT serving projection must bind its vector-tile layer and exact output'
            USING ERRCODE = '23514';
    END IF;
    SELECT content_sha256
      INTO v_source_content_sha256
      FROM gda_control.resource_version
     WHERE tenant_id = p_tenant_id
       AND resource_version_id = p_source_output_resource_version_id;
    IF NOT FOUND OR v_source_content_sha256 <> p_source_content_sha256 THEN
        RAISE EXCEPTION 'MVT serving projection source content hash does not match its output version'
            USING ERRCODE = '23514';
    END IF;
    IF NOT COALESCE((v_layer_schema_contract->'properties') ? p_feature_id_column, false)
       OR EXISTS (
            SELECT 1
              FROM unnest(p_property_allowlist) AS property_name(name)
             WHERE property_name.name = p_feature_id_column
                OR NOT COALESCE((v_layer_schema_contract->'properties') ? property_name.name, false)
       ) THEN
        RAISE EXCEPTION 'MVT serving fields must be declared by the layer schema contract'
            USING ERRCODE = '23514';
    END IF;
    IF (
        SELECT count(*) FROM unnest(p_property_allowlist) AS property_name(name)
    ) <> (
        SELECT count(DISTINCT property_name.name)
          FROM unnest(p_property_allowlist) AS property_name(name)
    ) THEN
        RAISE EXCEPTION 'MVT serving projection properties must not repeat'
            USING ERRCODE = '23514';
    END IF;

    PERFORM set_config('gda.gis_service_record_allowed', '1', true);
    INSERT INTO gda_control.mvt_serving_projection_version (
        tenant_id, mvt_serving_projection_version_id,
        service_definition_version_id, layer_definition_version_id,
        projection_key, version_key, predecessor_version_id,
        source_output_resource_version_id, source_schema, source_table,
        geometry_column, geometry_srid, feature_id_column, property_allowlist,
        allowed_spatial_extent, max_features_per_tile, source_content_sha256,
        projection_sha256, created_by, created_at
    ) VALUES (
        p_tenant_id, p_mvt_serving_projection_version_id,
        p_service_definition_version_id, p_layer_definition_version_id,
        p_projection_key, p_version_key, p_predecessor_version_id,
        p_source_output_resource_version_id, p_source_schema, p_source_table,
        p_geometry_column, p_geometry_srid, p_feature_id_column, p_property_allowlist,
        p_allowed_spatial_extent, p_max_features_per_tile, p_source_content_sha256,
        p_projection_sha256, p_created_by, p_created_at
    );
    RETURN p_mvt_serving_projection_version_id;
END;
$$;

DO $$
BEGIN
    IF to_regprocedure(
        'map_serving.gda_mvt_serving_projection_mvt(integer,integer,integer,json)'
    ) IS NOT NULL THEN
        COMMENT ON FUNCTION map_serving.gda_mvt_serving_projection_mvt(
            INTEGER, INTEGER, INTEGER, JSON
        ) IS '{"description":"Release-bound MVT serving projection","vector_layers":[{"id":"gda_mvt_serving_projection","fields":{"feature_id":"String"}}]}';
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
$$;
