-- 205: Immutable, release-bound Martin/PostGIS serving projection for MVT.
--
-- A service policy that only gates the Gateway cannot restrict which features
-- or attributes Martin reads.  This migration introduces the first executable
-- data-plane obligation: a release-bound source projection with an attribute
-- allowlist and a source-CRS spatial clip.  It is deliberately one Martin MVT
-- profile, not a generic row/column/spatial policy language.

CREATE TABLE gda_control.mvt_serving_projection_version (
    tenant_id TEXT NOT NULL,
    mvt_serving_projection_version_id UUID PRIMARY KEY,
    service_definition_version_id UUID NOT NULL,
    layer_definition_version_id UUID NOT NULL,
    projection_key TEXT NOT NULL,
    version_key TEXT NOT NULL,
    predecessor_version_id UUID,
    source_output_resource_version_id UUID NOT NULL,
    source_schema TEXT NOT NULL,
    source_table TEXT NOT NULL,
    geometry_column TEXT NOT NULL,
    geometry_srid INTEGER NOT NULL,
    feature_id_column TEXT NOT NULL,
    property_allowlist TEXT[] NOT NULL,
    allowed_spatial_extent DOUBLE PRECISION[] NOT NULL,
    max_features_per_tile INTEGER NOT NULL,
    source_content_sha256 CHAR(64) NOT NULL,
    projection_sha256 CHAR(64) NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_mvt_projection_tenant_id
        UNIQUE (tenant_id, mvt_serving_projection_version_id),
    CONSTRAINT uq_gda_mvt_projection_definition_id
        UNIQUE (
            tenant_id, service_definition_version_id,
            mvt_serving_projection_version_id
        ),
    CONSTRAINT uq_gda_mvt_projection_release_component
        UNIQUE (
            tenant_id, service_definition_version_id,
            layer_definition_version_id, mvt_serving_projection_version_id
        ),
    CONSTRAINT uq_gda_mvt_projection_key
        UNIQUE (
            tenant_id, service_definition_version_id, projection_key, version_key
        ),
    CONSTRAINT uq_gda_mvt_projection_lineage_target
        UNIQUE (
            tenant_id, service_definition_version_id, projection_key,
            mvt_serving_projection_version_id
        ),
    CONSTRAINT fk_gda_mvt_projection_layer
        FOREIGN KEY (
            tenant_id, service_definition_version_id, layer_definition_version_id
        ) REFERENCES gda_control.layer_definition_version(
            tenant_id, service_definition_version_id, layer_definition_version_id
        ),
    CONSTRAINT fk_gda_mvt_projection_source_output
        FOREIGN KEY (tenant_id, source_output_resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT fk_gda_mvt_projection_predecessor
        FOREIGN KEY (
            tenant_id, service_definition_version_id, projection_key,
            predecessor_version_id
        ) REFERENCES gda_control.mvt_serving_projection_version(
            tenant_id, service_definition_version_id, projection_key,
            mvt_serving_projection_version_id
        ),
    CONSTRAINT ck_gda_mvt_projection_keys CHECK (
        projection_key ~ '^[a-z0-9][a-z0-9._-]{0,127}$'
        AND version_key ~ '^v[0-9]+\.[0-9]+\.[0-9]+$'
    ),
    CONSTRAINT ck_gda_mvt_projection_not_self CHECK (
        predecessor_version_id IS NULL
        OR predecessor_version_id <> mvt_serving_projection_version_id
    ),
    CONSTRAINT ck_gda_mvt_projection_identifiers CHECK (
        source_schema ~ '^[A-Za-z_][A-Za-z0-9_$]{0,62}$'
        AND source_table ~ '^[A-Za-z_][A-Za-z0-9_$]{0,62}$'
        AND geometry_column ~ '^[A-Za-z_][A-Za-z0-9_$]{0,62}$'
        AND feature_id_column ~ '^[A-Za-z_][A-Za-z0-9_$]{0,62}$'
    ),
    CONSTRAINT ck_gda_mvt_projection_srid CHECK (geometry_srid > 0),
    CONSTRAINT ck_gda_mvt_projection_properties CHECK (
        cardinality(property_allowlist) BETWEEN 0 AND 16
        AND array_position(property_allowlist, NULL) IS NULL
        AND COALESCE(array_to_string(property_allowlist, ','), '')
            ~ '^$|^[A-Za-z_][A-Za-z0-9_$]{0,62}(,[A-Za-z_][A-Za-z0-9_$]{0,62})*$'
    ),
    CONSTRAINT ck_gda_mvt_projection_extent CHECK (
        gda_control.valid_spatial_extent(allowed_spatial_extent)
    ),
    CONSTRAINT ck_gda_mvt_projection_feature_limit CHECK (
        max_features_per_tile BETWEEN 100 AND 100000
    ),
    CONSTRAINT ck_gda_mvt_projection_hashes CHECK (
        source_content_sha256 ~ '^[0-9a-f]{64}$'
        AND projection_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_mvt_projection_actor CHECK (
        length(btrim(created_by)) BETWEEN 1 AND 512
    )
);

CREATE UNIQUE INDEX uq_gda_mvt_projection_root
    ON gda_control.mvt_serving_projection_version(
        tenant_id, service_definition_version_id, projection_key
    ) WHERE predecessor_version_id IS NULL;
CREATE UNIQUE INDEX uq_gda_mvt_projection_successor
    ON gda_control.mvt_serving_projection_version(
        tenant_id, service_definition_version_id, projection_key,
        predecessor_version_id
    ) WHERE predecessor_version_id IS NOT NULL;

CREATE TRIGGER trg_gda_mvt_projection_insert
BEFORE INSERT ON gda_control.mvt_serving_projection_version
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_gis_service_record_insert();
CREATE TRIGGER trg_gda_mvt_projection_immutable
BEFORE UPDATE OR DELETE ON gda_control.mvt_serving_projection_version
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

CREATE FUNCTION gda_control.record_mvt_serving_projection_version(
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

ALTER TABLE gda_control.service_release_binding
    ADD COLUMN mvt_serving_projection_version_id UUID;
ALTER TABLE gda_control.service_release_binding
    DROP CONSTRAINT uq_gda_service_release_content;
ALTER TABLE gda_control.service_release_binding
    ADD CONSTRAINT uq_gda_service_release_content
    UNIQUE NULLS NOT DISTINCT (
        tenant_id, service_definition_version_id,
        layer_definition_version_id, style_definition_version_id,
        tile_matrix_set_definition_version_id, cache_policy_version_id,
        mvt_serving_projection_version_id
    );
ALTER TABLE gda_control.service_release_binding
    ADD CONSTRAINT fk_gda_service_release_mvt_projection
    FOREIGN KEY (
        tenant_id, service_definition_version_id, layer_definition_version_id,
        mvt_serving_projection_version_id
    ) REFERENCES gda_control.mvt_serving_projection_version(
        tenant_id, service_definition_version_id, layer_definition_version_id,
        mvt_serving_projection_version_id
    );

DROP FUNCTION gda_control.record_service_release_binding(
    TEXT, UUID, UUID, UUID, UUID, UUID, UUID, TEXT, TEXT, TEXT, TIMESTAMPTZ
);

CREATE FUNCTION gda_control.record_service_release_binding(
    p_tenant_id TEXT,
    p_service_release_binding_id UUID,
    p_service_definition_version_id UUID,
    p_layer_definition_version_id UUID,
    p_style_definition_version_id UUID,
    p_tile_matrix_set_definition_version_id UUID,
    p_cache_policy_version_id UUID,
    p_mvt_serving_projection_version_id UUID,
    p_release_key TEXT,
    p_binding_sha256 TEXT,
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
    v_existing gda_control.service_release_binding%ROWTYPE;
    v_service_type TEXT;
    v_tile_layer_definition_version_id UUID;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'service release tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_existing
      FROM gda_control.service_release_binding
     WHERE tenant_id = p_tenant_id
       AND service_release_binding_id = p_service_release_binding_id;
    IF FOUND THEN
        IF v_existing.service_definition_version_id = p_service_definition_version_id
           AND v_existing.layer_definition_version_id = p_layer_definition_version_id
           AND v_existing.style_definition_version_id = p_style_definition_version_id
           AND v_existing.tile_matrix_set_definition_version_id IS NOT DISTINCT FROM p_tile_matrix_set_definition_version_id
           AND v_existing.cache_policy_version_id IS NOT DISTINCT FROM p_cache_policy_version_id
           AND v_existing.mvt_serving_projection_version_id IS NOT DISTINCT FROM p_mvt_serving_projection_version_id
           AND v_existing.release_key = p_release_key
           AND v_existing.binding_sha256 = p_binding_sha256
           AND v_existing.created_by = p_created_by
           AND v_existing.created_at = p_created_at THEN
            RETURN p_service_release_binding_id;
        END IF;
        RAISE EXCEPTION 'service release identity has different immutable content'
            USING ERRCODE = '40001';
    END IF;
    SELECT definition.service_type
      INTO v_service_type
      FROM gda_control.gis_service_definition_version AS definition
      JOIN gda_control.layer_definition_version AS layer
        ON layer.tenant_id = definition.tenant_id
       AND layer.service_definition_version_id = definition.service_definition_version_id
       AND layer.layer_definition_version_id = p_layer_definition_version_id
      JOIN gda_control.style_definition_version AS style
        ON style.tenant_id = layer.tenant_id
       AND style.service_definition_version_id = layer.service_definition_version_id
       AND style.layer_definition_version_id = layer.layer_definition_version_id
       AND style.style_definition_version_id = p_style_definition_version_id
     WHERE definition.tenant_id = p_tenant_id
       AND definition.service_definition_version_id = p_service_definition_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'service release layer and style do not form one version chain'
            USING ERRCODE = '23514';
    END IF;
    IF p_tile_matrix_set_definition_version_id IS NOT NULL THEN
        SELECT layer_definition_version_id
          INTO v_tile_layer_definition_version_id
          FROM gda_control.tile_matrix_set_definition_version
         WHERE tenant_id = p_tenant_id
           AND service_definition_version_id = p_service_definition_version_id
           AND tile_matrix_set_definition_version_id = p_tile_matrix_set_definition_version_id;
        IF NOT FOUND OR (
            v_tile_layer_definition_version_id IS NOT NULL
            AND v_tile_layer_definition_version_id <> p_layer_definition_version_id
        ) THEN
            RAISE EXCEPTION 'service release tile matrix set belongs to another layer'
                USING ERRCODE = '23514';
        END IF;
    ELSIF v_service_type = 'vector_tile' THEN
        RAISE EXCEPTION 'vector tile release requires a tile matrix set definition'
            USING ERRCODE = '23514';
    END IF;
    IF p_cache_policy_version_id IS NOT NULL THEN
        PERFORM 1 FROM gda_control.cache_policy_version
         WHERE tenant_id = p_tenant_id
           AND service_definition_version_id = p_service_definition_version_id
           AND cache_policy_version_id = p_cache_policy_version_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'service release cache policy belongs to another service'
                USING ERRCODE = '23514';
        END IF;
    ELSIF v_service_type = 'vector_tile' THEN
        RAISE EXCEPTION 'vector tile release requires a cache policy'
            USING ERRCODE = '23514';
    END IF;
    IF p_mvt_serving_projection_version_id IS NOT NULL THEN
        PERFORM 1 FROM gda_control.mvt_serving_projection_version
         WHERE tenant_id = p_tenant_id
           AND service_definition_version_id = p_service_definition_version_id
           AND layer_definition_version_id = p_layer_definition_version_id
           AND mvt_serving_projection_version_id = p_mvt_serving_projection_version_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'service release MVT serving projection belongs to another layer'
                USING ERRCODE = '23514';
        END IF;
    ELSIF v_service_type = 'vector_tile' THEN
        RAISE EXCEPTION 'vector tile release requires an MVT serving projection'
            USING ERRCODE = '23514';
    END IF;
    PERFORM set_config('gda.gis_service_record_allowed', '1', true);
    INSERT INTO gda_control.service_release_binding (
        tenant_id, service_release_binding_id,
        service_definition_version_id, layer_definition_version_id,
        style_definition_version_id, tile_matrix_set_definition_version_id,
        cache_policy_version_id, mvt_serving_projection_version_id,
        release_key, binding_sha256, created_by, created_at
    ) VALUES (
        p_tenant_id, p_service_release_binding_id,
        p_service_definition_version_id, p_layer_definition_version_id,
        p_style_definition_version_id, p_tile_matrix_set_definition_version_id,
        p_cache_policy_version_id, p_mvt_serving_projection_version_id,
        p_release_key, p_binding_sha256, p_created_by, p_created_at
    );
    RETURN p_service_release_binding_id;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.enforce_endpoint_release_binding()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM 1
      FROM gda_control.service_deployment_revision AS deployment
      JOIN gda_control.service_release_binding AS release
        ON release.tenant_id = deployment.tenant_id
       AND release.service_definition_version_id = deployment.service_definition_version_id
       AND release.service_release_binding_id = deployment.service_release_binding_id
      JOIN gda_control.gis_service_definition_version AS definition
        ON definition.tenant_id = deployment.tenant_id
       AND definition.service_definition_version_id = deployment.service_definition_version_id
     WHERE deployment.tenant_id = NEW.tenant_id
       AND deployment.deployment_revision_id = NEW.deployment_revision_id
       AND definition.service_urn = NEW.service_urn
       AND (
           definition.service_type <> 'vector_tile'
           OR (
               release.cache_policy_version_id IS NOT NULL
               AND release.mvt_serving_projection_version_id IS NOT NULL
               AND EXISTS (
                   SELECT 1
                     FROM gda_control.service_policy_binding AS policy
                    WHERE policy.tenant_id = deployment.tenant_id
                      AND policy.service_definition_version_id = deployment.service_definition_version_id
                      AND policy.service_release_binding_id = deployment.service_release_binding_id
               )
           )
       );
    IF NOT FOUND THEN
        RAISE EXCEPTION 'endpoint requires a cache-, policy-, and serving-projection-governed release'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.enforce_active_endpoint_release_binding()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM 1
      FROM gda_control.endpoint_revision AS endpoint
      JOIN gda_control.service_deployment_revision AS deployment
        ON deployment.tenant_id = endpoint.tenant_id
       AND deployment.deployment_revision_id = endpoint.deployment_revision_id
      JOIN gda_control.service_release_binding AS release
        ON release.tenant_id = deployment.tenant_id
       AND release.service_definition_version_id = deployment.service_definition_version_id
       AND release.service_release_binding_id = deployment.service_release_binding_id
      JOIN gda_control.gis_service_definition_version AS definition
        ON definition.tenant_id = deployment.tenant_id
       AND definition.service_definition_version_id = deployment.service_definition_version_id
     WHERE endpoint.tenant_id = NEW.tenant_id
       AND endpoint.service_urn = NEW.service_urn
       AND endpoint.endpoint_revision_id = NEW.active_endpoint_revision_id
       AND (
           definition.service_type <> 'vector_tile'
           OR (
               release.cache_policy_version_id IS NOT NULL
               AND release.mvt_serving_projection_version_id IS NOT NULL
               AND EXISTS (
                   SELECT 1
                     FROM gda_control.service_policy_binding AS policy
                    WHERE policy.tenant_id = deployment.tenant_id
                      AND policy.service_definition_version_id = deployment.service_definition_version_id
                      AND policy.service_release_binding_id = deployment.service_release_binding_id
               )
           )
       );
    IF NOT FOUND THEN
        RAISE EXCEPTION 'active endpoint requires a cache-, policy-, and serving-projection-governed release'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_endpoint_revision(
    p_tenant_id TEXT,
    p_endpoint_revision_id UUID,
    p_service_urn TEXT,
    p_deployment_revision_id UUID,
    p_endpoint_protocol TEXT,
    p_endpoint_uri TEXT,
    p_endpoint_contract JSONB,
    p_endpoint_sha256 TEXT,
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
    v_existing gda_control.endpoint_revision%ROWTYPE;
    v_deployment_state TEXT;
    v_deployment_terminal_at TIMESTAMPTZ;
    v_service_urn TEXT;
    v_service_type TEXT;
    v_mvt_serving_projection_version_id UUID;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'endpoint tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_existing FROM gda_control.endpoint_revision
     WHERE tenant_id = p_tenant_id
       AND endpoint_revision_id = p_endpoint_revision_id;
    IF FOUND THEN
        IF v_existing.service_urn = p_service_urn
           AND v_existing.deployment_revision_id = p_deployment_revision_id
           AND v_existing.endpoint_protocol = p_endpoint_protocol
           AND v_existing.endpoint_uri = p_endpoint_uri
           AND v_existing.endpoint_contract = p_endpoint_contract
           AND v_existing.endpoint_sha256 = p_endpoint_sha256
           AND v_existing.created_by = p_created_by
           AND v_existing.created_at = p_created_at THEN
            RETURN p_endpoint_revision_id;
        END IF;
        RAISE EXCEPTION 'endpoint revision identity has different immutable content'
            USING ERRCODE = '40001';
    END IF;

    SELECT deployment.state, deployment.terminal_at,
           definition.service_urn, definition.service_type,
           release.mvt_serving_projection_version_id
      INTO v_deployment_state, v_deployment_terminal_at,
           v_service_urn, v_service_type, v_mvt_serving_projection_version_id
      FROM gda_control.service_deployment_revision AS deployment
      JOIN gda_control.gis_service_definition_version AS definition
        ON definition.tenant_id = deployment.tenant_id
       AND definition.service_definition_version_id = deployment.service_definition_version_id
      LEFT JOIN gda_control.service_release_binding AS release
        ON release.tenant_id = deployment.tenant_id
       AND release.service_definition_version_id = deployment.service_definition_version_id
       AND release.service_release_binding_id = deployment.service_release_binding_id
     WHERE deployment.tenant_id = p_tenant_id
       AND deployment.deployment_revision_id = p_deployment_revision_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ServiceDeploymentRevision was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_deployment_state <> 'ready'
       OR v_service_urn <> p_service_urn
       OR p_created_at < v_deployment_terminal_at THEN
        RAISE EXCEPTION 'endpoint revision requires a ready deployment for this service'
            USING ERRCODE = '23514';
    END IF;
    IF NOT (
        (v_service_type = 'feature' AND p_endpoint_protocol IN ('arcgis_rest', 'ogc_api_features'))
        OR (v_service_type = 'map' AND p_endpoint_protocol IN ('arcgis_rest', 'wms', 'wmts'))
        OR (v_service_type = 'vector_tile' AND p_endpoint_protocol IN ('arcgis_rest', 'mvt', 'wmts'))
        OR (v_service_type = 'coverage' AND p_endpoint_protocol IN ('arcgis_rest', 'wms'))
    ) THEN
        RAISE EXCEPTION 'endpoint protocol is incompatible with the service type'
            USING ERRCODE = '23514';
    END IF;
    IF v_service_type = 'vector_tile' AND p_endpoint_protocol = 'mvt' AND (
        v_mvt_serving_projection_version_id IS NULL
        OR p_endpoint_contract->>'schema' IS DISTINCT FROM 'gda.mvt_endpoint.v1'
        OR p_endpoint_contract->>'provider_layer_ref' IS DISTINCT FROM 'gda_mvt_serving_projection'
        OR jsonb_typeof(p_endpoint_contract->'provider_query') IS DISTINCT FROM 'object'
        OR p_endpoint_contract->'provider_query'->>'serving_projection_version_id'
            IS DISTINCT FROM v_mvt_serving_projection_version_id::text
        OR (SELECT count(*) FROM jsonb_object_keys(p_endpoint_contract->'provider_query')) <> 1
    ) THEN
        RAISE EXCEPTION 'MVT endpoint must bind the release serving projection exactly'
            USING ERRCODE = '23514';
    END IF;

    PERFORM set_config('gda.gis_service_record_allowed', '1', true);
    INSERT INTO gda_control.endpoint_revision (
        tenant_id, endpoint_revision_id, service_urn,
        deployment_revision_id, endpoint_protocol, endpoint_uri,
        endpoint_contract, endpoint_sha256, created_by, created_at
    ) VALUES (
        p_tenant_id, p_endpoint_revision_id, p_service_urn,
        p_deployment_revision_id, p_endpoint_protocol, p_endpoint_uri,
        p_endpoint_contract, p_endpoint_sha256, p_created_by, p_created_at
    );
    RETURN p_endpoint_revision_id;
END;
$$;

ALTER TABLE gda_control.mvt_serving_projection_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.mvt_serving_projection_version FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON gda_control.mvt_serving_projection_version
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.mvt_serving_projection_version
FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.mvt_serving_projection_version TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.record_mvt_serving_projection_version(
    TEXT, UUID, UUID, UUID, TEXT, TEXT, UUID, UUID, TEXT, TEXT, TEXT,
    INTEGER, TEXT, TEXT[], DOUBLE PRECISION[], INTEGER, TEXT, TEXT, TEXT,
    TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_service_release_binding(
    TEXT, UUID, UUID, UUID, UUID, UUID, UUID, UUID, TEXT, TEXT, TEXT,
    TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_endpoint_revision(
    TEXT, UUID, TEXT, UUID, TEXT, TEXT, JSONB, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.enforce_endpoint_release_binding() FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.enforce_active_endpoint_release_binding() FROM PUBLIC;

GRANT EXECUTE ON FUNCTION gda_control.record_mvt_serving_projection_version(
    TEXT, UUID, UUID, UUID, TEXT, TEXT, UUID, UUID, TEXT, TEXT, TEXT,
    INTEGER, TEXT, TEXT[], DOUBLE PRECISION[], INTEGER, TEXT, TEXT, TEXT,
    TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_service_release_binding(
    TEXT, UUID, UUID, UUID, UUID, UUID, UUID, UUID, TEXT, TEXT, TEXT,
    TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_endpoint_revision(
    TEXT, UUID, TEXT, UUID, TEXT, TEXT, JSONB, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;

-- Martin uses this dedicated function for the governed Gateway route.  The
-- legacy map_publication function remains available for its compatibility API.
-- PostGIS profiles install the function; a control-plane-only PostgreSQL
-- profile still receives the immutable authority above.
CREATE SCHEMA IF NOT EXISTS map_serving;
DO $migration$
BEGIN
    IF to_regtype('geometry') IS NOT NULL THEN
        EXECUTE $function$
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
        'ST_Force2D(CASE WHEN ST_IsValid(%1$I) THEN %1$I ELSE ST_MakeValid(%1$I) END)',
        projection.geometry_column
    );
    tile_sql := format(
        'SELECT ST_AsMVT(tile, %L, 4096, ''geom'') FROM ('
        'SELECT %I::text AS feature_id%s, '
        'ST_AsMVTGeom('
        'ST_Transform(ST_CurveToLine(ST_Intersection(%s, '
        'ST_MakeEnvelope($4, $5, $6, $7, %s))), 3857), '
        'ST_TileEnvelope($1, $2, $3), 4096, 64, true) AS geom '
        'FROM %I.%I '
        'WHERE %I IS NOT NULL AND NOT ST_IsEmpty(%I) '
        'AND %I && ST_MakeEnvelope($4, $5, $6, $7, %s) '
        'AND %I && ST_Transform(ST_TileEnvelope($1, $2, $3), %s) '
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
$function$;
    END IF;
END;
$migration$;

DO $$
BEGIN
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
