-- 203: Immutable, service-bound cache policy for governed MVT releases.
--
-- Cache policy is release input, not provider configuration. Historic releases
-- remain readable with a NULL policy; newly recorded vector-tile releases must
-- bind one policy that partitions every response by tenant, release, principal,
-- and tile. The policy only permits short-lived private caches.

CREATE TABLE gda_control.cache_policy_version (
    tenant_id TEXT NOT NULL,
    cache_policy_version_id UUID PRIMARY KEY,
    service_definition_version_id UUID NOT NULL,
    cache_policy_key TEXT NOT NULL,
    version_key TEXT NOT NULL,
    predecessor_version_id UUID,
    cache_namespace TEXT NOT NULL,
    cache_max_age_seconds INTEGER NOT NULL,
    cache_key_dimensions TEXT[] NOT NULL,
    policy_sha256 CHAR(64) NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_cache_policy_tenant_id
        UNIQUE (tenant_id, cache_policy_version_id),
    CONSTRAINT uq_gda_cache_policy_service_id
        UNIQUE (
            tenant_id, service_definition_version_id, cache_policy_version_id
        ),
    CONSTRAINT uq_gda_cache_policy_lineage_id
        UNIQUE (
            tenant_id, service_definition_version_id, cache_policy_key,
            cache_policy_version_id
        ),
    CONSTRAINT uq_gda_cache_policy_key
        UNIQUE (
            tenant_id, service_definition_version_id, cache_policy_key,
            version_key
        ),
    CONSTRAINT fk_gda_cache_policy_service
        FOREIGN KEY (tenant_id, service_definition_version_id)
        REFERENCES gda_control.gis_service_definition_version(
            tenant_id, service_definition_version_id
        ),
    CONSTRAINT fk_gda_cache_policy_predecessor
        FOREIGN KEY (
            tenant_id, service_definition_version_id, cache_policy_key,
            predecessor_version_id
        ) REFERENCES gda_control.cache_policy_version(
            tenant_id, service_definition_version_id, cache_policy_key,
            cache_policy_version_id
        ),
    CONSTRAINT ck_gda_cache_policy_keys CHECK (
        cache_policy_key ~ '^[a-z0-9][a-z0-9._-]{0,127}$'
        AND version_key ~ '^v[0-9]+\.[0-9]+\.[0-9]+$'
        AND cache_namespace ~ '^[a-z0-9][a-z0-9._-]{0,127}$'
    ),
    CONSTRAINT ck_gda_cache_policy_not_self CHECK (
        predecessor_version_id IS NULL
        OR predecessor_version_id <> cache_policy_version_id
    ),
    CONSTRAINT ck_gda_cache_policy_max_age CHECK (
        cache_max_age_seconds BETWEEN 1 AND 300
    ),
    CONSTRAINT ck_gda_cache_policy_dimensions CHECK (
        cardinality(cache_key_dimensions) = 4
        AND array_position(cache_key_dimensions, NULL) IS NULL
        AND cache_key_dimensions @> ARRAY[
            'tenant', 'service_release', 'principal', 'tile'
        ]::TEXT[]
        AND cache_key_dimensions <@ ARRAY[
            'tenant', 'service_release', 'principal', 'tile'
        ]::TEXT[]
    ),
    CONSTRAINT ck_gda_cache_policy_sha256 CHECK (
        policy_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_cache_policy_actor CHECK (
        length(btrim(created_by)) BETWEEN 1 AND 512
    )
);

ALTER TABLE gda_control.service_release_binding
    ADD COLUMN cache_policy_version_id UUID;
ALTER TABLE gda_control.service_release_binding
    DROP CONSTRAINT uq_gda_service_release_content;
ALTER TABLE gda_control.service_release_binding
    ADD CONSTRAINT uq_gda_service_release_content
    UNIQUE NULLS NOT DISTINCT (
        tenant_id, service_definition_version_id,
        layer_definition_version_id, style_definition_version_id,
        tile_matrix_set_definition_version_id, cache_policy_version_id
    );
ALTER TABLE gda_control.service_release_binding
    ADD CONSTRAINT fk_gda_service_release_cache_policy
    FOREIGN KEY (
        tenant_id, service_definition_version_id, cache_policy_version_id
    ) REFERENCES gda_control.cache_policy_version(
        tenant_id, service_definition_version_id, cache_policy_version_id
    );

CREATE TRIGGER trg_gda_cache_policy_insert
BEFORE INSERT ON gda_control.cache_policy_version
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_gis_service_record_insert();
CREATE TRIGGER trg_gda_cache_policy_immutable
BEFORE UPDATE OR DELETE ON gda_control.cache_policy_version
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

CREATE OR REPLACE FUNCTION gda_control.record_cache_policy_version(
    p_tenant_id TEXT,
    p_cache_policy_version_id UUID,
    p_service_definition_version_id UUID,
    p_cache_policy_key TEXT,
    p_version_key TEXT,
    p_predecessor_version_id UUID,
    p_cache_namespace TEXT,
    p_cache_max_age_seconds INTEGER,
    p_cache_key_dimensions TEXT[],
    p_policy_sha256 TEXT,
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
    v_existing gda_control.cache_policy_version%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'cache policy tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_existing
      FROM gda_control.cache_policy_version
     WHERE tenant_id = p_tenant_id
       AND cache_policy_version_id = p_cache_policy_version_id;
    IF FOUND THEN
        IF v_existing.service_definition_version_id = p_service_definition_version_id
           AND v_existing.cache_policy_key = p_cache_policy_key
           AND v_existing.version_key = p_version_key
           AND v_existing.predecessor_version_id IS NOT DISTINCT FROM p_predecessor_version_id
           AND v_existing.cache_namespace = p_cache_namespace
           AND v_existing.cache_max_age_seconds = p_cache_max_age_seconds
           AND v_existing.cache_key_dimensions = p_cache_key_dimensions
           AND v_existing.policy_sha256 = p_policy_sha256
           AND v_existing.created_by = p_created_by
           AND v_existing.created_at = p_created_at THEN
            RETURN p_cache_policy_version_id;
        END IF;
        RAISE EXCEPTION 'cache policy identity has different immutable content'
            USING ERRCODE = '40001';
    END IF;
    PERFORM 1 FROM gda_control.gis_service_definition_version
     WHERE tenant_id = p_tenant_id
       AND service_definition_version_id = p_service_definition_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'cache policy must bind an exact service definition'
            USING ERRCODE = '23514';
    END IF;
    PERFORM set_config('gda.gis_service_record_allowed', '1', true);
    INSERT INTO gda_control.cache_policy_version (
        tenant_id, cache_policy_version_id, service_definition_version_id,
        cache_policy_key, version_key, predecessor_version_id,
        cache_namespace, cache_max_age_seconds, cache_key_dimensions,
        policy_sha256, created_by, created_at
    ) VALUES (
        p_tenant_id, p_cache_policy_version_id,
        p_service_definition_version_id, p_cache_policy_key, p_version_key,
        p_predecessor_version_id, p_cache_namespace, p_cache_max_age_seconds,
        p_cache_key_dimensions, p_policy_sha256, p_created_by, p_created_at
    );
    RETURN p_cache_policy_version_id;
END;
$$;

DROP FUNCTION gda_control.record_service_release_binding(
    TEXT, UUID, UUID, UUID, UUID, UUID, TEXT, TEXT, TEXT, TIMESTAMPTZ
);

CREATE FUNCTION gda_control.record_service_release_binding(
    p_tenant_id TEXT,
    p_service_release_binding_id UUID,
    p_service_definition_version_id UUID,
    p_layer_definition_version_id UUID,
    p_style_definition_version_id UUID,
    p_tile_matrix_set_definition_version_id UUID,
    p_cache_policy_version_id UUID,
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
    PERFORM set_config('gda.gis_service_record_allowed', '1', true);
    INSERT INTO gda_control.service_release_binding (
        tenant_id, service_release_binding_id,
        service_definition_version_id, layer_definition_version_id,
        style_definition_version_id, tile_matrix_set_definition_version_id,
        cache_policy_version_id, release_key, binding_sha256, created_by,
        created_at
    ) VALUES (
        p_tenant_id, p_service_release_binding_id,
        p_service_definition_version_id, p_layer_definition_version_id,
        p_style_definition_version_id, p_tile_matrix_set_definition_version_id,
        p_cache_policy_version_id, p_release_key, p_binding_sha256, p_created_by,
        p_created_at
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
           OR release.cache_policy_version_id IS NOT NULL
       );
    IF NOT FOUND THEN
        RAISE EXCEPTION 'endpoint requires a complete cache-governed service release'
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
           OR release.cache_policy_version_id IS NOT NULL
       );
    IF NOT FOUND THEN
        RAISE EXCEPTION 'active endpoint requires a complete cache-governed service release'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

ALTER TABLE gda_control.cache_policy_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.cache_policy_version FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON gda_control.cache_policy_version
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.cache_policy_version
FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.cache_policy_version TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.record_cache_policy_version(
    TEXT, UUID, UUID, TEXT, TEXT, UUID, TEXT, INTEGER, TEXT[], TEXT, TEXT,
    TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_service_release_binding(
    TEXT, UUID, UUID, UUID, UUID, UUID, UUID, TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.enforce_endpoint_release_binding() FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.enforce_active_endpoint_release_binding() FROM PUBLIC;

GRANT EXECUTE ON FUNCTION gda_control.record_cache_policy_version(
    TEXT, UUID, UUID, TEXT, TEXT, UUID, TEXT, INTEGER, TEXT[], TEXT, TEXT,
    TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_service_release_binding(
    TEXT, UUID, UUID, UUID, UUID, UUID, UUID, TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
