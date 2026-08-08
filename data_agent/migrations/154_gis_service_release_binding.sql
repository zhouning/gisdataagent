-- 154: Versioned GIS layer/style/tile-matrix authority and atomic releases.
--
-- Existing deployments remain readable with a NULL release binding. Every new
-- deployment and every endpoint activation must bind one immutable release.

CREATE OR REPLACE FUNCTION gda_control.valid_spatial_extent(
    p_extent DOUBLE PRECISION[]
)
RETURNS BOOLEAN
LANGUAGE plpgsql
IMMUTABLE
AS $$
BEGIN
    RETURN cardinality(p_extent) = 4
       AND array_position(p_extent, NULL) IS NULL
       AND p_extent[1] <= p_extent[3]
       AND p_extent[2] <= p_extent[4]
       AND p_extent[1] > '-Infinity'::DOUBLE PRECISION
       AND p_extent[2] > '-Infinity'::DOUBLE PRECISION
       AND p_extent[3] < 'Infinity'::DOUBLE PRECISION
       AND p_extent[4] < 'Infinity'::DOUBLE PRECISION;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.valid_scale_denominators(
    p_scales DOUBLE PRECISION[]
)
RETURNS BOOLEAN
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    v_index INTEGER;
BEGIN
    IF cardinality(p_scales) IS NULL OR cardinality(p_scales) = 0
       OR array_position(p_scales, NULL) IS NOT NULL THEN
        RETURN FALSE;
    END IF;
    FOR v_index IN 1..cardinality(p_scales) LOOP
        IF p_scales[v_index] <= 0
           OR p_scales[v_index] >= 'Infinity'::DOUBLE PRECISION
           OR (
               v_index > 1
               AND p_scales[v_index - 1] <= p_scales[v_index]
           ) THEN
            RETURN FALSE;
        END IF;
    END LOOP;
    RETURN TRUE;
END;
$$;

CREATE TABLE gda_control.layer_definition_version (
    tenant_id TEXT NOT NULL,
    layer_definition_version_id UUID PRIMARY KEY,
    service_definition_version_id UUID NOT NULL,
    layer_key TEXT NOT NULL,
    version_key TEXT NOT NULL,
    predecessor_version_id UUID,
    source_output_resource_version_id UUID NOT NULL,
    geometry_type TEXT NOT NULL,
    geometry_column TEXT NOT NULL,
    schema_contract JSONB NOT NULL,
    crs_uri TEXT NOT NULL,
    spatial_extent DOUBLE PRECISION[] NOT NULL,
    definition_sha256 CHAR(64) NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_layer_definition_tenant_id
        UNIQUE (tenant_id, layer_definition_version_id),
    CONSTRAINT uq_gda_layer_definition_service_id
        UNIQUE (
            tenant_id, service_definition_version_id,
            layer_definition_version_id
        ),
    CONSTRAINT uq_gda_layer_definition_lineage_id
        UNIQUE (
            tenant_id, service_definition_version_id, layer_key,
            layer_definition_version_id
        ),
    CONSTRAINT uq_gda_layer_definition_key
        UNIQUE (
            tenant_id, service_definition_version_id, layer_key, version_key
        ),
    CONSTRAINT fk_gda_layer_definition_service
        FOREIGN KEY (tenant_id, service_definition_version_id)
        REFERENCES gda_control.gis_service_definition_version(
            tenant_id, service_definition_version_id
        ),
    CONSTRAINT fk_gda_layer_definition_predecessor
        FOREIGN KEY (
            tenant_id, service_definition_version_id, layer_key,
            predecessor_version_id
        ) REFERENCES gda_control.layer_definition_version(
            tenant_id, service_definition_version_id, layer_key,
            layer_definition_version_id
        ),
    CONSTRAINT fk_gda_layer_definition_output
        FOREIGN KEY (tenant_id, source_output_resource_version_id)
        REFERENCES gda_control.resource_version(
            tenant_id, resource_version_id
        ),
    CONSTRAINT ck_gda_layer_definition_keys CHECK (
        layer_key ~ '^[a-z0-9][a-z0-9._-]{0,127}$'
        AND version_key ~ '^v[0-9]+\.[0-9]+\.[0-9]+$'
    ),
    CONSTRAINT ck_gda_layer_definition_not_self CHECK (
        predecessor_version_id IS NULL
        OR predecessor_version_id <> layer_definition_version_id
    ),
    CONSTRAINT ck_gda_layer_definition_geometry CHECK (
        geometry_type IN (
            'geometry', 'point', 'multipoint', 'linestring',
            'multilinestring', 'polygon', 'multipolygon',
            'geometrycollection'
        )
        AND length(btrim(geometry_column)) BETWEEN 1 AND 128
    ),
    CONSTRAINT ck_gda_layer_definition_schema CHECK (
        jsonb_typeof(schema_contract) = 'object'
        AND schema_contract <> '{}'::jsonb
    ),
    CONSTRAINT ck_gda_layer_definition_crs CHECK (
        length(btrim(crs_uri)) BETWEEN 1 AND 512
    ),
    CONSTRAINT ck_gda_layer_definition_extent CHECK (
        gda_control.valid_spatial_extent(spatial_extent)
    ),
    CONSTRAINT ck_gda_layer_definition_sha256 CHECK (
        definition_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_layer_definition_actor CHECK (
        length(btrim(created_by)) BETWEEN 1 AND 512
    )
);

CREATE UNIQUE INDEX uq_gda_layer_definition_root
    ON gda_control.layer_definition_version(
        tenant_id, service_definition_version_id, layer_key
    ) WHERE predecessor_version_id IS NULL;
CREATE UNIQUE INDEX uq_gda_layer_definition_successor
    ON gda_control.layer_definition_version(
        tenant_id, service_definition_version_id, layer_key,
        predecessor_version_id
    ) WHERE predecessor_version_id IS NOT NULL;

CREATE TABLE gda_control.style_definition_version (
    tenant_id TEXT NOT NULL,
    style_definition_version_id UUID PRIMARY KEY,
    service_definition_version_id UUID NOT NULL,
    layer_definition_version_id UUID NOT NULL,
    style_key TEXT NOT NULL,
    version_key TEXT NOT NULL,
    predecessor_version_id UUID,
    style_format TEXT NOT NULL,
    style_document JSONB NOT NULL,
    style_sha256 CHAR(64) NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_style_definition_tenant_id
        UNIQUE (tenant_id, style_definition_version_id),
    CONSTRAINT uq_gda_style_definition_layer_id
        UNIQUE (
            tenant_id, service_definition_version_id,
            layer_definition_version_id, style_definition_version_id
        ),
    CONSTRAINT uq_gda_style_definition_lineage_id
        UNIQUE (
            tenant_id, service_definition_version_id,
            layer_definition_version_id, style_key,
            style_definition_version_id
        ),
    CONSTRAINT uq_gda_style_definition_key
        UNIQUE (
            tenant_id, service_definition_version_id,
            layer_definition_version_id, style_key, version_key
        ),
    CONSTRAINT fk_gda_style_definition_layer
        FOREIGN KEY (
            tenant_id, service_definition_version_id,
            layer_definition_version_id
        ) REFERENCES gda_control.layer_definition_version(
            tenant_id, service_definition_version_id,
            layer_definition_version_id
        ),
    CONSTRAINT fk_gda_style_definition_predecessor
        FOREIGN KEY (
            tenant_id, service_definition_version_id,
            layer_definition_version_id, style_key,
            predecessor_version_id
        ) REFERENCES gda_control.style_definition_version(
            tenant_id, service_definition_version_id,
            layer_definition_version_id, style_key,
            style_definition_version_id
        ),
    CONSTRAINT ck_gda_style_definition_keys CHECK (
        style_key ~ '^[a-z0-9][a-z0-9._-]{0,127}$'
        AND version_key ~ '^v[0-9]+\.[0-9]+\.[0-9]+$'
    ),
    CONSTRAINT ck_gda_style_definition_not_self CHECK (
        predecessor_version_id IS NULL
        OR predecessor_version_id <> style_definition_version_id
    ),
    CONSTRAINT ck_gda_style_definition_format CHECK (
        style_format IN ('mapbox_style', 'sld', 'qml')
    ),
    CONSTRAINT ck_gda_style_definition_document CHECK (
        jsonb_typeof(style_document) = 'object'
        AND style_document <> '{}'::jsonb
    ),
    CONSTRAINT ck_gda_style_definition_sha256 CHECK (
        style_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_style_definition_actor CHECK (
        length(btrim(created_by)) BETWEEN 1 AND 512
    )
);

CREATE UNIQUE INDEX uq_gda_style_definition_root
    ON gda_control.style_definition_version(
        tenant_id, service_definition_version_id,
        layer_definition_version_id, style_key
    ) WHERE predecessor_version_id IS NULL;
CREATE UNIQUE INDEX uq_gda_style_definition_successor
    ON gda_control.style_definition_version(
        tenant_id, service_definition_version_id,
        layer_definition_version_id, style_key, predecessor_version_id
    ) WHERE predecessor_version_id IS NOT NULL;

CREATE TABLE gda_control.tile_matrix_set_definition_version (
    tenant_id TEXT NOT NULL,
    tile_matrix_set_definition_version_id UUID PRIMARY KEY,
    service_definition_version_id UUID NOT NULL,
    layer_definition_version_id UUID,
    tile_matrix_set_key TEXT NOT NULL,
    version_key TEXT NOT NULL,
    predecessor_version_id UUID,
    crs_uri TEXT NOT NULL,
    tile_width INTEGER NOT NULL,
    tile_height INTEGER NOT NULL,
    min_zoom INTEGER NOT NULL,
    max_zoom INTEGER NOT NULL,
    scale_denominators DOUBLE PRECISION[] NOT NULL,
    spatial_extent DOUBLE PRECISION[] NOT NULL,
    definition_sha256 CHAR(64) NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_tile_matrix_tenant_id
        UNIQUE (tenant_id, tile_matrix_set_definition_version_id),
    CONSTRAINT uq_gda_tile_matrix_service_id
        UNIQUE (
            tenant_id, service_definition_version_id,
            tile_matrix_set_definition_version_id
        ),
    CONSTRAINT uq_gda_tile_matrix_lineage_id
        UNIQUE (
            tenant_id, service_definition_version_id,
            tile_matrix_set_key, tile_matrix_set_definition_version_id
        ),
    CONSTRAINT uq_gda_tile_matrix_key
        UNIQUE (
            tenant_id, service_definition_version_id,
            tile_matrix_set_key, version_key
        ),
    CONSTRAINT fk_gda_tile_matrix_service
        FOREIGN KEY (tenant_id, service_definition_version_id)
        REFERENCES gda_control.gis_service_definition_version(
            tenant_id, service_definition_version_id
        ),
    CONSTRAINT fk_gda_tile_matrix_layer
        FOREIGN KEY (
            tenant_id, service_definition_version_id,
            layer_definition_version_id
        ) REFERENCES gda_control.layer_definition_version(
            tenant_id, service_definition_version_id,
            layer_definition_version_id
        ),
    CONSTRAINT fk_gda_tile_matrix_predecessor
        FOREIGN KEY (
            tenant_id, service_definition_version_id,
            tile_matrix_set_key, predecessor_version_id
        ) REFERENCES gda_control.tile_matrix_set_definition_version(
            tenant_id, service_definition_version_id,
            tile_matrix_set_key, tile_matrix_set_definition_version_id
        ),
    CONSTRAINT ck_gda_tile_matrix_keys CHECK (
        tile_matrix_set_key ~ '^[a-z0-9][a-z0-9._-]{0,127}$'
        AND version_key ~ '^v[0-9]+\.[0-9]+\.[0-9]+$'
    ),
    CONSTRAINT ck_gda_tile_matrix_not_self CHECK (
        predecessor_version_id IS NULL
        OR predecessor_version_id <> tile_matrix_set_definition_version_id
    ),
    CONSTRAINT ck_gda_tile_matrix_crs CHECK (
        length(btrim(crs_uri)) BETWEEN 1 AND 512
    ),
    CONSTRAINT ck_gda_tile_matrix_dimensions CHECK (
        tile_width BETWEEN 1 AND 8192
        AND tile_height BETWEEN 1 AND 8192
        AND min_zoom BETWEEN 0 AND 30
        AND max_zoom BETWEEN min_zoom AND 30
    ),
    CONSTRAINT ck_gda_tile_matrix_scales CHECK (
        cardinality(scale_denominators) = max_zoom - min_zoom + 1
        AND gda_control.valid_scale_denominators(scale_denominators)
    ),
    CONSTRAINT ck_gda_tile_matrix_extent CHECK (
        gda_control.valid_spatial_extent(spatial_extent)
    ),
    CONSTRAINT ck_gda_tile_matrix_sha256 CHECK (
        definition_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_tile_matrix_actor CHECK (
        length(btrim(created_by)) BETWEEN 1 AND 512
    )
);

CREATE UNIQUE INDEX uq_gda_tile_matrix_root
    ON gda_control.tile_matrix_set_definition_version(
        tenant_id, service_definition_version_id, tile_matrix_set_key
    ) WHERE predecessor_version_id IS NULL;
CREATE UNIQUE INDEX uq_gda_tile_matrix_successor
    ON gda_control.tile_matrix_set_definition_version(
        tenant_id, service_definition_version_id, tile_matrix_set_key,
        predecessor_version_id
    ) WHERE predecessor_version_id IS NOT NULL;

CREATE TABLE gda_control.service_release_binding (
    tenant_id TEXT NOT NULL,
    service_release_binding_id UUID PRIMARY KEY,
    service_definition_version_id UUID NOT NULL,
    layer_definition_version_id UUID NOT NULL,
    style_definition_version_id UUID NOT NULL,
    tile_matrix_set_definition_version_id UUID,
    release_key TEXT NOT NULL,
    binding_sha256 CHAR(64) NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_service_release_tenant_id
        UNIQUE (tenant_id, service_release_binding_id),
    CONSTRAINT uq_gda_service_release_definition_id
        UNIQUE (
            tenant_id, service_definition_version_id,
            service_release_binding_id
        ),
    CONSTRAINT uq_gda_service_release_key
        UNIQUE (tenant_id, service_definition_version_id, release_key),
    CONSTRAINT uq_gda_service_release_content
        UNIQUE NULLS NOT DISTINCT (
            tenant_id, service_definition_version_id,
            layer_definition_version_id, style_definition_version_id,
            tile_matrix_set_definition_version_id
        ),
    CONSTRAINT fk_gda_service_release_layer
        FOREIGN KEY (
            tenant_id, service_definition_version_id,
            layer_definition_version_id
        ) REFERENCES gda_control.layer_definition_version(
            tenant_id, service_definition_version_id,
            layer_definition_version_id
        ),
    CONSTRAINT fk_gda_service_release_style
        FOREIGN KEY (
            tenant_id, service_definition_version_id,
            layer_definition_version_id, style_definition_version_id
        ) REFERENCES gda_control.style_definition_version(
            tenant_id, service_definition_version_id,
            layer_definition_version_id, style_definition_version_id
        ),
    CONSTRAINT fk_gda_service_release_tile_matrix
        FOREIGN KEY (
            tenant_id, service_definition_version_id,
            tile_matrix_set_definition_version_id
        ) REFERENCES gda_control.tile_matrix_set_definition_version(
            tenant_id, service_definition_version_id,
            tile_matrix_set_definition_version_id
        ),
    CONSTRAINT ck_gda_service_release_key CHECK (
        release_key ~ '^v[0-9]+\.[0-9]+\.[0-9]+$'
    ),
    CONSTRAINT ck_gda_service_release_sha256 CHECK (
        binding_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_service_release_actor CHECK (
        length(btrim(created_by)) BETWEEN 1 AND 512
    )
);

ALTER TABLE gda_control.service_deployment_revision
    ADD COLUMN service_release_binding_id UUID;
ALTER TABLE gda_control.service_deployment_revision
    ADD CONSTRAINT fk_gda_service_deployment_release
    FOREIGN KEY (
        tenant_id, service_definition_version_id, service_release_binding_id
    ) REFERENCES gda_control.service_release_binding(
        tenant_id, service_definition_version_id, service_release_binding_id
    );

CREATE INDEX idx_gda_layer_definition_service
    ON gda_control.layer_definition_version(
        tenant_id, service_definition_version_id, layer_key, created_at DESC
    );
CREATE INDEX idx_gda_style_definition_layer
    ON gda_control.style_definition_version(
        tenant_id, layer_definition_version_id, style_key, created_at DESC
    );
CREATE INDEX idx_gda_tile_matrix_service
    ON gda_control.tile_matrix_set_definition_version(
        tenant_id, service_definition_version_id,
        tile_matrix_set_key, created_at DESC
    );

CREATE TRIGGER trg_gda_layer_definition_insert
BEFORE INSERT ON gda_control.layer_definition_version
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_gis_service_record_insert();
CREATE TRIGGER trg_gda_style_definition_insert
BEFORE INSERT ON gda_control.style_definition_version
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_gis_service_record_insert();
CREATE TRIGGER trg_gda_tile_matrix_definition_insert
BEFORE INSERT ON gda_control.tile_matrix_set_definition_version
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_gis_service_record_insert();
CREATE TRIGGER trg_gda_service_release_insert
BEFORE INSERT ON gda_control.service_release_binding
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_gis_service_record_insert();

CREATE TRIGGER trg_gda_layer_definition_immutable
BEFORE UPDATE OR DELETE ON gda_control.layer_definition_version
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();
CREATE TRIGGER trg_gda_style_definition_immutable
BEFORE UPDATE OR DELETE ON gda_control.style_definition_version
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();
CREATE TRIGGER trg_gda_tile_matrix_definition_immutable
BEFORE UPDATE OR DELETE ON gda_control.tile_matrix_set_definition_version
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();
CREATE TRIGGER trg_gda_service_release_immutable
BEFORE UPDATE OR DELETE ON gda_control.service_release_binding
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

CREATE OR REPLACE FUNCTION gda_control.guard_service_deployment_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF COALESCE(current_setting('gda.gis_service_record_allowed', true), '') <> '1' THEN
            RAISE EXCEPTION 'use the governed service deployment recorder'
                USING ERRCODE = '42501';
        END IF;
        IF NEW.service_release_binding_id IS NULL
           OR NEW.state <> 'planned' OR NEW.state_version <> 0
           OR NEW.terminal_observation_id IS NOT NULL
           OR NEW.terminal_at IS NOT NULL THEN
            RAISE EXCEPTION 'service deployment must start planned with a release binding'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF COALESCE(current_setting('gda.service_deployment_transition_allowed', true), '') <> '1' THEN
        RAISE EXCEPTION 'use the governed service deployment transition recorder'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.deployment_revision_id IS DISTINCT FROM OLD.deployment_revision_id
       OR NEW.service_definition_version_id IS DISTINCT FROM OLD.service_definition_version_id
       OR NEW.service_release_binding_id IS DISTINCT FROM OLD.service_release_binding_id
       OR NEW.run_id IS DISTINCT FROM OLD.run_id
       OR NEW.revision_key IS DISTINCT FROM OLD.revision_key
       OR NEW.provider_system IS DISTINCT FROM OLD.provider_system
       OR NEW.provider_namespace IS DISTINCT FROM OLD.provider_namespace
       OR NEW.provider_deployment_id IS DISTINCT FROM OLD.provider_deployment_id
       OR NEW.provider_revision_ref IS DISTINCT FROM OLD.provider_revision_ref
       OR NEW.config_sha256 IS DISTINCT FROM OLD.config_sha256
       OR NEW.deployment_sha256 IS DISTINCT FROM OLD.deployment_sha256
       OR NEW.created_by IS DISTINCT FROM OLD.created_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.state_version <> OLD.state_version + 1
       OR NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'service deployment immutable binding changed'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
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
       AND release.service_definition_version_id =
            deployment.service_definition_version_id
       AND release.service_release_binding_id =
            deployment.service_release_binding_id
      JOIN gda_control.gis_service_definition_version AS definition
        ON definition.tenant_id = deployment.tenant_id
       AND definition.service_definition_version_id =
            deployment.service_definition_version_id
     WHERE deployment.tenant_id = NEW.tenant_id
       AND deployment.deployment_revision_id = NEW.deployment_revision_id
       AND definition.service_urn = NEW.service_urn;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'endpoint requires a complete atomic service release'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_gda_endpoint_release_binding
BEFORE INSERT ON gda_control.endpoint_revision
FOR EACH ROW EXECUTE FUNCTION gda_control.enforce_endpoint_release_binding();

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
       AND release.service_definition_version_id =
            deployment.service_definition_version_id
       AND release.service_release_binding_id =
            deployment.service_release_binding_id
     WHERE endpoint.tenant_id = NEW.tenant_id
       AND endpoint.service_urn = NEW.service_urn
       AND endpoint.endpoint_revision_id = NEW.active_endpoint_revision_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'active endpoint requires a complete atomic service release'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_gda_active_endpoint_release_binding
BEFORE UPDATE OF active_endpoint_revision_id ON gda_control.gis_service
FOR EACH ROW EXECUTE FUNCTION gda_control.enforce_active_endpoint_release_binding();

CREATE OR REPLACE FUNCTION gda_control.record_layer_definition_version(
    p_tenant_id TEXT,
    p_layer_definition_version_id UUID,
    p_service_definition_version_id UUID,
    p_layer_key TEXT,
    p_version_key TEXT,
    p_predecessor_version_id UUID,
    p_source_output_resource_version_id UUID,
    p_geometry_type TEXT,
    p_geometry_column TEXT,
    p_schema_contract JSONB,
    p_crs_uri TEXT,
    p_spatial_extent DOUBLE PRECISION[],
    p_definition_sha256 TEXT,
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
    v_existing gda_control.layer_definition_version%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'layer definition tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_existing
      FROM gda_control.layer_definition_version
     WHERE tenant_id = p_tenant_id
       AND layer_definition_version_id = p_layer_definition_version_id;
    IF FOUND THEN
        IF v_existing.service_definition_version_id = p_service_definition_version_id
           AND v_existing.layer_key = p_layer_key
           AND v_existing.version_key = p_version_key
           AND v_existing.predecessor_version_id IS NOT DISTINCT FROM p_predecessor_version_id
           AND v_existing.source_output_resource_version_id = p_source_output_resource_version_id
           AND v_existing.geometry_type = p_geometry_type
           AND v_existing.geometry_column = p_geometry_column
           AND v_existing.schema_contract = p_schema_contract
           AND v_existing.crs_uri = p_crs_uri
           AND v_existing.spatial_extent = p_spatial_extent
           AND v_existing.definition_sha256 = p_definition_sha256
           AND v_existing.created_by = p_created_by
           AND v_existing.created_at = p_created_at THEN
            RETURN p_layer_definition_version_id;
        END IF;
        RAISE EXCEPTION 'layer definition identity has different immutable content'
            USING ERRCODE = '40001';
    END IF;
    PERFORM 1
      FROM gda_control.gis_service_definition_version AS definition
      JOIN gda_control.data_product_version AS product_version
        ON product_version.tenant_id = definition.tenant_id
       AND product_version.product_urn = definition.source_product_urn
       AND product_version.data_product_version_id =
            definition.source_data_product_version_id
     WHERE definition.tenant_id = p_tenant_id
       AND definition.service_definition_version_id =
            p_service_definition_version_id
       AND product_version.output_resource_version_id =
            p_source_output_resource_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'layer source must be the exact service product output version'
            USING ERRCODE = '23514';
    END IF;
    PERFORM set_config('gda.gis_service_record_allowed', '1', true);
    INSERT INTO gda_control.layer_definition_version (
        tenant_id, layer_definition_version_id,
        service_definition_version_id, layer_key, version_key,
        predecessor_version_id, source_output_resource_version_id,
        geometry_type, geometry_column, schema_contract, crs_uri,
        spatial_extent, definition_sha256, created_by, created_at
    ) VALUES (
        p_tenant_id, p_layer_definition_version_id,
        p_service_definition_version_id, p_layer_key, p_version_key,
        p_predecessor_version_id, p_source_output_resource_version_id,
        p_geometry_type, p_geometry_column, p_schema_contract, p_crs_uri,
        p_spatial_extent, p_definition_sha256, p_created_by, p_created_at
    );
    RETURN p_layer_definition_version_id;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_style_definition_version(
    p_tenant_id TEXT,
    p_style_definition_version_id UUID,
    p_service_definition_version_id UUID,
    p_layer_definition_version_id UUID,
    p_style_key TEXT,
    p_version_key TEXT,
    p_predecessor_version_id UUID,
    p_style_format TEXT,
    p_style_document JSONB,
    p_style_sha256 TEXT,
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
    v_existing gda_control.style_definition_version%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'style definition tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_existing
      FROM gda_control.style_definition_version
     WHERE tenant_id = p_tenant_id
       AND style_definition_version_id = p_style_definition_version_id;
    IF FOUND THEN
        IF v_existing.service_definition_version_id = p_service_definition_version_id
           AND v_existing.layer_definition_version_id = p_layer_definition_version_id
           AND v_existing.style_key = p_style_key
           AND v_existing.version_key = p_version_key
           AND v_existing.predecessor_version_id IS NOT DISTINCT FROM p_predecessor_version_id
           AND v_existing.style_format = p_style_format
           AND v_existing.style_document = p_style_document
           AND v_existing.style_sha256 = p_style_sha256
           AND v_existing.created_by = p_created_by
           AND v_existing.created_at = p_created_at THEN
            RETURN p_style_definition_version_id;
        END IF;
        RAISE EXCEPTION 'style definition identity has different immutable content'
            USING ERRCODE = '40001';
    END IF;
    PERFORM 1 FROM gda_control.layer_definition_version
     WHERE tenant_id = p_tenant_id
       AND service_definition_version_id = p_service_definition_version_id
       AND layer_definition_version_id = p_layer_definition_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'style definition must bind an exact layer definition'
            USING ERRCODE = '23514';
    END IF;
    PERFORM set_config('gda.gis_service_record_allowed', '1', true);
    INSERT INTO gda_control.style_definition_version (
        tenant_id, style_definition_version_id,
        service_definition_version_id, layer_definition_version_id,
        style_key, version_key, predecessor_version_id, style_format,
        style_document, style_sha256, created_by, created_at
    ) VALUES (
        p_tenant_id, p_style_definition_version_id,
        p_service_definition_version_id, p_layer_definition_version_id,
        p_style_key, p_version_key, p_predecessor_version_id, p_style_format,
        p_style_document, p_style_sha256, p_created_by, p_created_at
    );
    RETURN p_style_definition_version_id;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_tile_matrix_set_definition_version(
    p_tenant_id TEXT,
    p_tile_matrix_set_definition_version_id UUID,
    p_service_definition_version_id UUID,
    p_layer_definition_version_id UUID,
    p_tile_matrix_set_key TEXT,
    p_version_key TEXT,
    p_predecessor_version_id UUID,
    p_crs_uri TEXT,
    p_tile_width INTEGER,
    p_tile_height INTEGER,
    p_min_zoom INTEGER,
    p_max_zoom INTEGER,
    p_scale_denominators DOUBLE PRECISION[],
    p_spatial_extent DOUBLE PRECISION[],
    p_definition_sha256 TEXT,
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
    v_existing gda_control.tile_matrix_set_definition_version%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'tile matrix set tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_existing
      FROM gda_control.tile_matrix_set_definition_version
     WHERE tenant_id = p_tenant_id
       AND tile_matrix_set_definition_version_id =
            p_tile_matrix_set_definition_version_id;
    IF FOUND THEN
        IF v_existing.service_definition_version_id = p_service_definition_version_id
           AND v_existing.layer_definition_version_id IS NOT DISTINCT FROM p_layer_definition_version_id
           AND v_existing.tile_matrix_set_key = p_tile_matrix_set_key
           AND v_existing.version_key = p_version_key
           AND v_existing.predecessor_version_id IS NOT DISTINCT FROM p_predecessor_version_id
           AND v_existing.crs_uri = p_crs_uri
           AND v_existing.tile_width = p_tile_width
           AND v_existing.tile_height = p_tile_height
           AND v_existing.min_zoom = p_min_zoom
           AND v_existing.max_zoom = p_max_zoom
           AND v_existing.scale_denominators = p_scale_denominators
           AND v_existing.spatial_extent = p_spatial_extent
           AND v_existing.definition_sha256 = p_definition_sha256
           AND v_existing.created_by = p_created_by
           AND v_existing.created_at = p_created_at THEN
            RETURN p_tile_matrix_set_definition_version_id;
        END IF;
        RAISE EXCEPTION 'tile matrix set identity has different immutable content'
            USING ERRCODE = '40001';
    END IF;
    IF p_layer_definition_version_id IS NULL THEN
        PERFORM 1 FROM gda_control.gis_service_definition_version
         WHERE tenant_id = p_tenant_id
           AND service_definition_version_id = p_service_definition_version_id;
    ELSE
        PERFORM 1 FROM gda_control.layer_definition_version
         WHERE tenant_id = p_tenant_id
           AND service_definition_version_id = p_service_definition_version_id
           AND layer_definition_version_id = p_layer_definition_version_id;
    END IF;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'tile matrix set must bind the exact service or layer definition'
            USING ERRCODE = '23514';
    END IF;
    PERFORM set_config('gda.gis_service_record_allowed', '1', true);
    INSERT INTO gda_control.tile_matrix_set_definition_version (
        tenant_id, tile_matrix_set_definition_version_id,
        service_definition_version_id, layer_definition_version_id,
        tile_matrix_set_key, version_key, predecessor_version_id, crs_uri,
        tile_width, tile_height, min_zoom, max_zoom, scale_denominators,
        spatial_extent, definition_sha256, created_by, created_at
    ) VALUES (
        p_tenant_id, p_tile_matrix_set_definition_version_id,
        p_service_definition_version_id, p_layer_definition_version_id,
        p_tile_matrix_set_key, p_version_key, p_predecessor_version_id,
        p_crs_uri, p_tile_width, p_tile_height, p_min_zoom, p_max_zoom,
        p_scale_denominators, p_spatial_extent, p_definition_sha256,
        p_created_by, p_created_at
    );
    RETURN p_tile_matrix_set_definition_version_id;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_service_release_binding(
    p_tenant_id TEXT,
    p_service_release_binding_id UUID,
    p_service_definition_version_id UUID,
    p_layer_definition_version_id UUID,
    p_style_definition_version_id UUID,
    p_tile_matrix_set_definition_version_id UUID,
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
       AND layer.service_definition_version_id =
            definition.service_definition_version_id
       AND layer.layer_definition_version_id = p_layer_definition_version_id
      JOIN gda_control.style_definition_version AS style
        ON style.tenant_id = layer.tenant_id
       AND style.service_definition_version_id =
            layer.service_definition_version_id
       AND style.layer_definition_version_id = layer.layer_definition_version_id
       AND style.style_definition_version_id = p_style_definition_version_id
     WHERE definition.tenant_id = p_tenant_id
       AND definition.service_definition_version_id =
            p_service_definition_version_id;
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
           AND tile_matrix_set_definition_version_id =
                p_tile_matrix_set_definition_version_id;
        IF NOT FOUND OR (
            v_tile_layer_definition_version_id IS NOT NULL
            AND v_tile_layer_definition_version_id <>
                p_layer_definition_version_id
        ) THEN
            RAISE EXCEPTION 'service release tile matrix set belongs to another layer'
                USING ERRCODE = '23514';
        END IF;
    ELSIF v_service_type = 'vector_tile' THEN
        RAISE EXCEPTION 'vector tile release requires a tile matrix set definition'
            USING ERRCODE = '23514';
    END IF;
    PERFORM set_config('gda.gis_service_record_allowed', '1', true);
    INSERT INTO gda_control.service_release_binding (
        tenant_id, service_release_binding_id,
        service_definition_version_id, layer_definition_version_id,
        style_definition_version_id,
        tile_matrix_set_definition_version_id, release_key,
        binding_sha256, created_by, created_at
    ) VALUES (
        p_tenant_id, p_service_release_binding_id,
        p_service_definition_version_id, p_layer_definition_version_id,
        p_style_definition_version_id,
        p_tile_matrix_set_definition_version_id, p_release_key,
        p_binding_sha256, p_created_by, p_created_at
    );
    RETURN p_service_release_binding_id;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_service_deployment_revision(
    p_tenant_id TEXT,
    p_deployment_revision_id UUID,
    p_service_definition_version_id UUID,
    p_service_release_binding_id UUID,
    p_run_id UUID,
    p_revision_key TEXT,
    p_provider_system TEXT,
    p_provider_namespace TEXT,
    p_provider_deployment_id TEXT,
    p_provider_revision_ref TEXT,
    p_config_sha256 TEXT,
    p_deployment_sha256 TEXT,
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
    v_existing gda_control.service_deployment_revision%ROWTYPE;
    v_platform_definition_version_id UUID;
    v_output_resource_version_id UUID;
    v_run_definition_version_id UUID;
    v_run_status TEXT;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'service deployment tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_service_release_binding_id IS NULL THEN
        RAISE EXCEPTION 'service deployment requires an atomic release binding'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_existing
      FROM gda_control.service_deployment_revision
     WHERE tenant_id = p_tenant_id
       AND deployment_revision_id = p_deployment_revision_id;
    IF FOUND THEN
        IF v_existing.service_definition_version_id = p_service_definition_version_id
           AND v_existing.service_release_binding_id = p_service_release_binding_id
           AND v_existing.run_id = p_run_id
           AND v_existing.revision_key = p_revision_key
           AND v_existing.provider_system = p_provider_system
           AND v_existing.provider_namespace = p_provider_namespace
           AND v_existing.provider_deployment_id = p_provider_deployment_id
           AND v_existing.provider_revision_ref = p_provider_revision_ref
           AND v_existing.config_sha256 = p_config_sha256
           AND v_existing.deployment_sha256 = p_deployment_sha256
           AND v_existing.created_by = p_created_by
           AND v_existing.created_at = p_created_at THEN
            RETURN p_deployment_revision_id;
        END IF;
        RAISE EXCEPTION 'service deployment identity has different immutable content'
            USING ERRCODE = '40001';
    END IF;
    SELECT definition.platform_definition_version_id,
           product_version.output_resource_version_id
      INTO v_platform_definition_version_id, v_output_resource_version_id
      FROM gda_control.gis_service_definition_version AS definition
      JOIN gda_control.data_product_version AS product_version
        ON product_version.tenant_id = definition.tenant_id
       AND product_version.product_urn = definition.source_product_urn
       AND product_version.data_product_version_id =
            definition.source_data_product_version_id
      JOIN gda_control.service_release_binding AS release
        ON release.tenant_id = definition.tenant_id
       AND release.service_definition_version_id =
            definition.service_definition_version_id
       AND release.service_release_binding_id = p_service_release_binding_id
     WHERE definition.tenant_id = p_tenant_id
       AND definition.service_definition_version_id =
            p_service_definition_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'atomic service release was not found for the definition'
            USING ERRCODE = 'P0002';
    END IF;
    SELECT definition_version_id, status
      INTO v_run_definition_version_id, v_run_status
      FROM gda_control.platform_run
     WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'PlatformRun was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_run_definition_version_id <> v_platform_definition_version_id
       OR v_run_status NOT IN ('accepted', 'dispatching', 'running', 'reconciling') THEN
        RAISE EXCEPTION 'service deployment Run does not bind the service definition'
            USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM gda_control.platform_run_input_binding
     WHERE tenant_id = p_tenant_id
       AND run_id = p_run_id
       AND resource_version_id = v_output_resource_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'service deployment Run does not bind the product output version'
            USING ERRCODE = '23514';
    END IF;
    PERFORM set_config('gda.gis_service_record_allowed', '1', true);
    INSERT INTO gda_control.service_deployment_revision (
        tenant_id, deployment_revision_id, service_definition_version_id,
        service_release_binding_id, run_id, revision_key, provider_system,
        provider_namespace, provider_deployment_id, provider_revision_ref,
        config_sha256, deployment_sha256, created_by, created_at, updated_at
    ) VALUES (
        p_tenant_id, p_deployment_revision_id,
        p_service_definition_version_id, p_service_release_binding_id,
        p_run_id, p_revision_key, p_provider_system, p_provider_namespace,
        p_provider_deployment_id, p_provider_revision_ref, p_config_sha256,
        p_deployment_sha256, p_created_by, p_created_at, p_created_at
    );
    RETURN p_deployment_revision_id;
END;
$$;

DO $$
DECLARE
    relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'layer_definition_version',
        'style_definition_version',
        'tile_matrix_set_definition_version',
        'service_release_binding'
    ]
    LOOP
        EXECUTE format(
            'ALTER TABLE gda_control.%I ENABLE ROW LEVEL SECURITY',
            relation_name
        );
        EXECUTE format(
            'ALTER TABLE gda_control.%I FORCE ROW LEVEL SECURITY',
            relation_name
        );
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON gda_control.%I '
            'USING (tenant_id = gda_control.current_tenant()) '
            'WITH CHECK (tenant_id = gda_control.current_tenant())',
            relation_name
        );
    END LOOP;
END;
$$;

REVOKE ALL ON TABLE
    gda_control.layer_definition_version,
    gda_control.style_definition_version,
    gda_control.tile_matrix_set_definition_version,
    gda_control.service_release_binding
FROM PUBLIC, gda_control_gateway;

GRANT SELECT ON TABLE
    gda_control.layer_definition_version,
    gda_control.style_definition_version,
    gda_control.tile_matrix_set_definition_version,
    gda_control.service_release_binding
TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.valid_spatial_extent(
    DOUBLE PRECISION[]
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.valid_scale_denominators(
    DOUBLE PRECISION[]
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.enforce_endpoint_release_binding() FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.enforce_active_endpoint_release_binding() FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_layer_definition_version(
    TEXT, UUID, UUID, TEXT, TEXT, UUID, UUID, TEXT, TEXT, JSONB, TEXT,
    DOUBLE PRECISION[], TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_style_definition_version(
    TEXT, UUID, UUID, UUID, TEXT, TEXT, UUID, TEXT, JSONB, TEXT, TEXT,
    TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_tile_matrix_set_definition_version(
    TEXT, UUID, UUID, UUID, TEXT, TEXT, UUID, TEXT, INTEGER, INTEGER,
    INTEGER, INTEGER, DOUBLE PRECISION[], DOUBLE PRECISION[], TEXT, TEXT,
    TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_service_release_binding(
    TEXT, UUID, UUID, UUID, UUID, UUID, TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_service_deployment_revision(
    TEXT, UUID, UUID, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    TEXT, TIMESTAMPTZ
) FROM gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.record_service_deployment_revision(
    TEXT, UUID, UUID, UUID, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    TEXT, TIMESTAMPTZ
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION gda_control.record_layer_definition_version(
    TEXT, UUID, UUID, TEXT, TEXT, UUID, UUID, TEXT, TEXT, JSONB, TEXT,
    DOUBLE PRECISION[], TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_style_definition_version(
    TEXT, UUID, UUID, UUID, TEXT, TEXT, UUID, TEXT, JSONB, TEXT, TEXT,
    TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_tile_matrix_set_definition_version(
    TEXT, UUID, UUID, UUID, TEXT, TEXT, UUID, TEXT, INTEGER, INTEGER,
    INTEGER, INTEGER, DOUBLE PRECISION[], DOUBLE PRECISION[], TEXT, TEXT,
    TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_service_release_binding(
    TEXT, UUID, UUID, UUID, UUID, UUID, TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_service_deployment_revision(
    TEXT, UUID, UUID, UUID, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
