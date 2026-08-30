-- 237: Attest the physical PostGIS relation behind a release-bound MVT projection.
--
-- The projection contract names a source relation, but a name alone is not a
-- serving proof: a table can be absent, recreated, or have its geometry and
-- allowlisted columns changed.  This migration records the live catalog
-- observation and makes endpoint promotion re-check that observation.

CREATE TABLE gda_control.mvt_serving_relation_attestation (
    tenant_id TEXT NOT NULL,
    mvt_serving_projection_version_id UUID NOT NULL,
    source_schema TEXT NOT NULL,
    source_table TEXT NOT NULL,
    relation_oid OID NOT NULL,
    relation_kind CHAR(1) NOT NULL,
    geometry_column TEXT NOT NULL,
    geometry_type TEXT NOT NULL,
    geometry_srid INTEGER NOT NULL,
    geometry_dimensions INTEGER NOT NULL,
    feature_id_column TEXT NOT NULL,
    feature_id_data_type TEXT NOT NULL,
    property_columns TEXT[] NOT NULL,
    property_column_types TEXT[] NOT NULL,
    relation_schema_sha256 CHAR(64) NOT NULL,
    attested_by TEXT NOT NULL,
    attested_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, mvt_serving_projection_version_id),
    CONSTRAINT fk_gda_mvt_relation_attestation_projection
        FOREIGN KEY (tenant_id, mvt_serving_projection_version_id)
        REFERENCES gda_control.mvt_serving_projection_version(
            tenant_id, mvt_serving_projection_version_id
        ),
    CONSTRAINT ck_gda_mvt_relation_attestation_identifiers CHECK (
        source_schema ~ '^[A-Za-z_][A-Za-z0-9_$]{0,62}$'
        AND source_table ~ '^[A-Za-z_][A-Za-z0-9_$]{0,62}$'
        AND geometry_column ~ '^[A-Za-z_][A-Za-z0-9_$]{0,62}$'
        AND feature_id_column ~ '^[A-Za-z_][A-Za-z0-9_$]{0,62}$'
    ),
    CONSTRAINT ck_gda_mvt_relation_attestation_geometry CHECK (
        length(btrim(geometry_type)) BETWEEN 1 AND 64
        AND geometry_srid > 0
        AND geometry_dimensions BETWEEN 2 AND 4
    ),
    CONSTRAINT ck_gda_mvt_relation_attestation_properties CHECK (
        cardinality(property_columns) BETWEEN 0 AND 16
        AND array_position(property_columns, NULL) IS NULL
        AND cardinality(property_column_types) = cardinality(property_columns)
        AND array_position(property_column_types, NULL) IS NULL
    ),
    CONSTRAINT ck_gda_mvt_relation_attestation_hash CHECK (
        relation_schema_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_mvt_relation_attestation_actor CHECK (
        length(btrim(attested_by)) BETWEEN 1 AND 512
    )
);

CREATE OR REPLACE FUNCTION gda_control.observe_mvt_serving_relation(
    p_tenant_id TEXT,
    p_mvt_serving_projection_version_id UUID
)
RETURNS TABLE (
    relation_oid OID,
    relation_kind CHAR(1),
    geometry_column TEXT,
    geometry_type TEXT,
    geometry_srid INTEGER,
    geometry_dimensions INTEGER,
    feature_id_column TEXT,
    feature_id_data_type TEXT,
    property_columns TEXT[],
    property_column_types TEXT[],
    relation_schema_sha256 CHAR(64)
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_projection gda_control.mvt_serving_projection_version%ROWTYPE;
    v_relation_oid OID;
    v_relation_kind CHAR(1);
    v_geometry_type TEXT;
    v_geometry_srid INTEGER;
    v_geometry_dimensions INTEGER;
    v_feature_id_data_type TEXT;
    v_property_columns TEXT[];
    v_property_column_types TEXT[];
    v_document JSONB;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'MVT relation observation tenant context mismatch'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_projection
      FROM gda_control.mvt_serving_projection_version
     WHERE tenant_id = p_tenant_id
       AND mvt_serving_projection_version_id =
            p_mvt_serving_projection_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'MVT serving projection was not found'
            USING ERRCODE = '23514';
    END IF;

    SELECT c.oid, c.relkind
      INTO v_relation_oid, v_relation_kind
      FROM pg_catalog.pg_class AS c
      JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
     WHERE n.nspname = v_projection.source_schema
       AND c.relname = v_projection.source_table;
    IF NOT FOUND OR v_relation_kind NOT IN ('r', 'p', 'v', 'm', 'f') THEN
        RAISE EXCEPTION 'MVT serving source relation is missing or unsupported'
            USING ERRCODE = '23514';
    END IF;

    SELECT gc.type, gc.srid, gc.coord_dimension
      INTO v_geometry_type, v_geometry_srid, v_geometry_dimensions
      FROM public.geometry_columns AS gc
     WHERE gc.f_table_schema = v_projection.source_schema
       AND gc.f_table_name = v_projection.source_table
       AND gc.f_geometry_column = v_projection.geometry_column;
    IF NOT FOUND
       OR v_geometry_srid IS DISTINCT FROM v_projection.geometry_srid
       OR v_geometry_dimensions IS NULL
       OR v_geometry_dimensions < 2 THEN
        RAISE EXCEPTION 'MVT serving source geometry metadata does not match projection'
            USING ERRCODE = '23514';
    END IF;

    SELECT pg_catalog.format_type(a.atttypid, a.atttypmod)
      INTO v_feature_id_data_type
      FROM pg_catalog.pg_attribute AS a
     WHERE a.attrelid = v_relation_oid
       AND a.attnum > 0
       AND NOT a.attisdropped
       AND a.attname = v_projection.feature_id_column;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'MVT serving feature ID column is missing from source relation'
            USING ERRCODE = '23514';
    END IF;

    SELECT COALESCE(
        pg_catalog.array_agg(a.attname ORDER BY a.attnum),
        ARRAY[]::TEXT[]
    )
      INTO v_property_columns
      FROM pg_catalog.pg_attribute AS a
     WHERE a.attrelid = v_relation_oid
       AND a.attnum > 0
       AND NOT a.attisdropped
       AND a.attname = ANY(v_projection.property_allowlist);
    IF cardinality(v_property_columns) <> cardinality(v_projection.property_allowlist)
       OR EXISTS (
           SELECT 1
             FROM pg_catalog.unnest(v_projection.property_allowlist) AS expected(name)
            WHERE NOT (expected.name = ANY(v_property_columns))
       ) THEN
        RAISE EXCEPTION 'MVT serving property allowlist does not match source relation'
            USING ERRCODE = '23514';
    END IF;
    SELECT COALESCE(
        pg_catalog.array_agg(
            pg_catalog.format_type(a.atttypid, a.atttypmod)
            ORDER BY pg_catalog.array_position(v_projection.property_allowlist, a.attname)
        ),
        ARRAY[]::TEXT[]
    )
      INTO v_property_column_types
      FROM pg_catalog.pg_attribute AS a
     WHERE a.attrelid = v_relation_oid
       AND a.attnum > 0
       AND NOT a.attisdropped
       AND a.attname = ANY(v_projection.property_allowlist);

    v_document := pg_catalog.jsonb_build_object(
        'relation_oid', v_relation_oid::TEXT,
        'relation_kind', v_relation_kind::TEXT,
        'source_schema', v_projection.source_schema,
        'source_table', v_projection.source_table,
        'geometry_column', v_projection.geometry_column,
        'geometry_type', v_geometry_type,
        'geometry_srid', v_geometry_srid,
        'geometry_dimensions', v_geometry_dimensions,
        'feature_id_column', v_projection.feature_id_column,
        'feature_id_data_type', v_feature_id_data_type,
        'property_columns', v_property_columns,
        'property_column_types', v_property_column_types
    );
    RETURN QUERY SELECT
        v_relation_oid,
        v_relation_kind,
        v_projection.geometry_column,
        v_geometry_type,
        v_geometry_srid,
        v_geometry_dimensions,
        v_projection.feature_id_column,
        v_feature_id_data_type,
        v_property_columns,
        v_property_column_types,
        pg_catalog.encode(
            public.digest(
                pg_catalog.convert_to(v_document::TEXT, 'UTF8'), 'sha256'
            ),
            'hex'
        )::CHAR(64);
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_mvt_serving_relation_attestation(
    p_tenant_id TEXT,
    p_mvt_serving_projection_version_id UUID,
    p_attested_by TEXT,
    p_attested_at TIMESTAMPTZ
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_observed RECORD;
    v_existing gda_control.mvt_serving_relation_attestation%ROWTYPE;
    v_projection gda_control.mvt_serving_projection_version%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'MVT relation attestation tenant context mismatch'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_projection
      FROM gda_control.mvt_serving_projection_version
     WHERE tenant_id = p_tenant_id
       AND mvt_serving_projection_version_id =
            p_mvt_serving_projection_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'MVT serving projection was not found'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_observed
      FROM gda_control.observe_mvt_serving_relation(
          p_tenant_id, p_mvt_serving_projection_version_id
      );

    SELECT * INTO v_existing
      FROM gda_control.mvt_serving_relation_attestation
     WHERE tenant_id = p_tenant_id
       AND mvt_serving_projection_version_id =
            p_mvt_serving_projection_version_id;
    IF FOUND THEN
        IF v_existing.source_schema = v_projection.source_schema
           AND v_existing.source_table = v_projection.source_table
           AND v_existing.relation_oid = v_observed.relation_oid
           AND v_existing.relation_kind = v_observed.relation_kind
           AND v_existing.geometry_column = v_observed.geometry_column
           AND v_existing.geometry_type = v_observed.geometry_type
           AND v_existing.geometry_srid = v_observed.geometry_srid
           AND v_existing.geometry_dimensions = v_observed.geometry_dimensions
           AND v_existing.feature_id_column = v_observed.feature_id_column
           AND v_existing.feature_id_data_type = v_observed.feature_id_data_type
           AND v_existing.property_columns = v_observed.property_columns
           AND v_existing.property_column_types = v_observed.property_column_types
           AND v_existing.relation_schema_sha256 = v_observed.relation_schema_sha256
           AND v_existing.attested_by = p_attested_by
           AND v_existing.attested_at = p_attested_at THEN
            RETURN p_mvt_serving_projection_version_id;
        END IF;
        RAISE EXCEPTION 'MVT relation attestation identity has different immutable content'
            USING ERRCODE = '40001';
    END IF;

    PERFORM set_config('gda.gis_service_record_allowed', '1', true);
    INSERT INTO gda_control.mvt_serving_relation_attestation (
        tenant_id, mvt_serving_projection_version_id, source_schema,
        source_table, relation_oid, relation_kind, geometry_column,
        geometry_type, geometry_srid, geometry_dimensions, feature_id_column,
        feature_id_data_type, property_columns, property_column_types,
        relation_schema_sha256,
        attested_by, attested_at
    ) VALUES (
        p_tenant_id, p_mvt_serving_projection_version_id,
        v_projection.source_schema, v_projection.source_table,
        v_observed.relation_oid, v_observed.relation_kind,
        v_observed.geometry_column, v_observed.geometry_type,
        v_observed.geometry_srid, v_observed.geometry_dimensions,
        v_observed.feature_id_column, v_observed.feature_id_data_type,
        v_observed.property_columns, v_observed.property_column_types,
        v_observed.relation_schema_sha256,
        p_attested_by, p_attested_at
    );
    RETURN p_mvt_serving_projection_version_id;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.assert_mvt_serving_relation_attestation(
    p_tenant_id TEXT,
    p_mvt_serving_projection_version_id UUID
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_attestation gda_control.mvt_serving_relation_attestation%ROWTYPE;
    v_observed RECORD;
BEGIN
    SELECT * INTO v_attestation
      FROM gda_control.mvt_serving_relation_attestation
     WHERE tenant_id = p_tenant_id
       AND mvt_serving_projection_version_id =
            p_mvt_serving_projection_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'MVT endpoint promotion requires a serving relation attestation'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_observed
      FROM gda_control.observe_mvt_serving_relation(
          p_tenant_id, p_mvt_serving_projection_version_id
      );
    IF v_attestation.relation_oid IS DISTINCT FROM v_observed.relation_oid
       OR v_attestation.relation_kind IS DISTINCT FROM v_observed.relation_kind
       OR v_attestation.geometry_column IS DISTINCT FROM v_observed.geometry_column
       OR v_attestation.geometry_type IS DISTINCT FROM v_observed.geometry_type
       OR v_attestation.geometry_srid IS DISTINCT FROM v_observed.geometry_srid
       OR v_attestation.geometry_dimensions IS DISTINCT FROM v_observed.geometry_dimensions
       OR v_attestation.feature_id_column IS DISTINCT FROM v_observed.feature_id_column
       OR v_attestation.feature_id_data_type IS DISTINCT FROM v_observed.feature_id_data_type
       OR v_attestation.property_columns IS DISTINCT FROM v_observed.property_columns
       OR v_attestation.property_column_types IS DISTINCT FROM v_observed.property_column_types
       OR v_attestation.relation_schema_sha256 IS DISTINCT FROM v_observed.relation_schema_sha256 THEN
        RAISE EXCEPTION 'MVT endpoint promotion detected serving relation drift'
            USING ERRCODE = '23514';
    END IF;
    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.reject_mvt_relation_attestation_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'MVT serving relation attestations are immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER trg_gda_mvt_relation_attestation_guard
BEFORE INSERT ON gda_control.mvt_serving_relation_attestation
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_gis_service_record_insert();
CREATE TRIGGER trg_gda_mvt_relation_attestation_immutable
BEFORE UPDATE OR DELETE ON gda_control.mvt_serving_relation_attestation
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_mvt_relation_attestation_mutation();

ALTER TABLE gda_control.mvt_serving_relation_attestation ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.mvt_serving_relation_attestation FORCE ROW LEVEL SECURITY;
CREATE POLICY gda_mvt_relation_attestation_tenant_policy
    ON gda_control.mvt_serving_relation_attestation
    USING (tenant_id = current_setting('app.current_tenant', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', true));
REVOKE ALL ON TABLE gda_control.mvt_serving_relation_attestation FROM PUBLIC;
REVOKE ALL ON TABLE gda_control.mvt_serving_relation_attestation FROM agent_user;
GRANT SELECT ON TABLE gda_control.mvt_serving_relation_attestation TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.observe_mvt_serving_relation(TEXT, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_mvt_serving_relation_attestation(TEXT, UUID, TEXT, TIMESTAMPTZ) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.assert_mvt_serving_relation_attestation(TEXT, UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.record_mvt_serving_relation_attestation(TEXT, UUID, TEXT, TIMESTAMPTZ) TO gda_control_gateway;

-- Replace the JQDLTB promotion trigger function only after this migration has
-- created the attestation authority.  Generic GIS services retain migration
-- 236's existing release gates.
CREATE OR REPLACE FUNCTION gda_control.enforce_jqdltb_serving_endpoint_binding()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_definition gda_control.gis_service_definition_version%ROWTYPE;
    v_deployment gda_control.service_deployment_revision%ROWTYPE;
    v_release gda_control.service_release_binding%ROWTYPE;
    v_product_version gda_control.data_product_version%ROWTYPE;
BEGIN
    SELECT definition.* INTO v_definition
      FROM gda_control.endpoint_revision AS endpoint
      JOIN gda_control.service_deployment_revision AS deployment
        ON deployment.tenant_id = endpoint.tenant_id
       AND deployment.deployment_revision_id = endpoint.deployment_revision_id
      JOIN gda_control.gis_service_definition_version AS definition
        ON definition.tenant_id = deployment.tenant_id
       AND definition.service_definition_version_id =
            deployment.service_definition_version_id
     WHERE endpoint.tenant_id = NEW.tenant_id
       AND endpoint.service_urn = NEW.service_urn
       AND endpoint.endpoint_revision_id = NEW.active_endpoint_revision_id;
    IF NOT FOUND THEN
        RETURN NEW;
    END IF;

    SELECT version.* INTO v_product_version
      FROM gda_control.data_product_version AS version
     WHERE version.tenant_id = v_definition.tenant_id
       AND version.product_urn = v_definition.source_product_urn
       AND version.data_product_version_id =
            v_definition.source_data_product_version_id;
    IF NOT FOUND
       OR v_product_version.mapping_contract->>'schema' IS DISTINCT FROM
            'gda.jqdltb_mapping_binding.v1' THEN
        RETURN NEW;
    END IF;

    SELECT deployment.* INTO v_deployment
      FROM gda_control.service_deployment_revision AS deployment
     WHERE deployment.tenant_id = NEW.tenant_id
       AND deployment.deployment_revision_id = (
            SELECT endpoint.deployment_revision_id
              FROM gda_control.endpoint_revision AS endpoint
             WHERE endpoint.tenant_id = NEW.tenant_id
               AND endpoint.endpoint_revision_id = NEW.active_endpoint_revision_id
       );
    SELECT release.* INTO v_release
      FROM gda_control.service_release_binding AS release
     WHERE release.tenant_id = v_deployment.tenant_id
       AND release.service_definition_version_id =
            v_deployment.service_definition_version_id
       AND release.service_release_binding_id =
            v_deployment.service_release_binding_id;

    PERFORM 1
      FROM gda_control.jqdltb_serving_release_binding AS serving
     WHERE serving.tenant_id = v_definition.tenant_id
       AND serving.product_urn = v_definition.source_product_urn
       AND serving.data_product_version_id =
            v_definition.source_data_product_version_id
       AND serving.manifest_sha256 = v_definition.source_manifest_sha256
       AND serving.service_urn = v_definition.service_urn
       AND serving.service_definition_version_id =
            v_definition.service_definition_version_id
       AND serving.layer_definition_version_id =
            v_release.layer_definition_version_id
       AND serving.mvt_serving_projection_version_id =
            v_release.mvt_serving_projection_version_id
       AND serving.service_release_binding_id =
            v_release.service_release_binding_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION
            'JQDLTB endpoint promotion requires an exact serving release binding'
            USING ERRCODE = '23514';
    END IF;
    PERFORM gda_control.assert_mvt_serving_relation_attestation(
        v_definition.tenant_id,
        v_release.mvt_serving_projection_version_id
    );
    RETURN NEW;
END;
$$;
