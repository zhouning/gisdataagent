-- Post-publication JQDLTB serving authority. The product must be current
-- before the GIS service definition is registered.

CREATE TABLE gda_control.jqdltb_serving_release_binding (
    tenant_id TEXT NOT NULL,
    data_product_version_id UUID NOT NULL,
    product_urn TEXT NOT NULL,
    manifest_sha256 CHAR(64) NOT NULL,
    output_resource_version_id UUID NOT NULL,
    service_urn TEXT NOT NULL,
    service_definition_version_id UUID NOT NULL,
    layer_definition_version_id UUID NOT NULL,
    mvt_serving_projection_version_id UUID NOT NULL,
    service_release_binding_id UUID NOT NULL,
    slo_binding_id UUID NOT NULL,
    serving_release_binding_sha256 CHAR(64) NOT NULL,
    bound_by TEXT NOT NULL,
    bound_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, data_product_version_id),
    CONSTRAINT fk_jqdltb_serving_product FOREIGN KEY (
        tenant_id, product_urn, data_product_version_id
    ) REFERENCES gda_control.data_product_version(
        tenant_id, product_urn, data_product_version_id
    ),
    CONSTRAINT fk_jqdltb_serving_output FOREIGN KEY (
        tenant_id, output_resource_version_id
    ) REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT fk_jqdltb_serving_service FOREIGN KEY (tenant_id, service_urn)
        REFERENCES gda_control.gis_service(tenant_id, service_urn),
    CONSTRAINT fk_jqdltb_serving_definition FOREIGN KEY (
        tenant_id, service_definition_version_id
    ) REFERENCES gda_control.gis_service_definition_version(
        tenant_id, service_definition_version_id
    ),
    CONSTRAINT fk_jqdltb_serving_layer FOREIGN KEY (
        tenant_id, service_definition_version_id, layer_definition_version_id
    ) REFERENCES gda_control.layer_definition_version(
        tenant_id, service_definition_version_id, layer_definition_version_id
    ),
    CONSTRAINT fk_jqdltb_serving_projection FOREIGN KEY (
        tenant_id, service_definition_version_id, layer_definition_version_id,
        mvt_serving_projection_version_id
    ) REFERENCES gda_control.mvt_serving_projection_version(
        tenant_id, service_definition_version_id, layer_definition_version_id,
        mvt_serving_projection_version_id
    ),
    CONSTRAINT fk_jqdltb_serving_release FOREIGN KEY (
        tenant_id, service_definition_version_id, service_release_binding_id
    ) REFERENCES gda_control.service_release_binding(
        tenant_id, service_definition_version_id, service_release_binding_id
    ),
    CONSTRAINT fk_jqdltb_serving_slo FOREIGN KEY (tenant_id, slo_binding_id)
        REFERENCES gda_control.gis_service_slo_binding(tenant_id, binding_id),
    CONSTRAINT ck_jqdltb_serving_hashes CHECK (
        manifest_sha256 ~ '^[0-9a-f]{64}$'
        AND serving_release_binding_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_jqdltb_serving_actor CHECK (
        bound_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'
    )
);

CREATE OR REPLACE FUNCTION gda_control.record_jqdltb_serving_release_binding(
    p_tenant_id TEXT, p_data_product_version_id UUID, p_product_urn TEXT,
    p_manifest_sha256 TEXT, p_output_resource_version_id UUID,
    p_service_urn TEXT, p_service_definition_version_id UUID,
    p_layer_definition_version_id UUID, p_mvt_serving_projection_version_id UUID,
    p_service_release_binding_id UUID, p_slo_binding_id UUID,
    p_serving_release_binding_sha256 TEXT, p_bound_by TEXT,
    p_bound_at TIMESTAMPTZ
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_existing gda_control.jqdltb_serving_release_binding%ROWTYPE;
    v_product gda_control.data_product_version%ROWTYPE;
    v_definition gda_control.gis_service_definition_version%ROWTYPE;
    v_layer gda_control.layer_definition_version%ROWTYPE;
    v_projection gda_control.mvt_serving_projection_version%ROWTYPE;
    v_release gda_control.service_release_binding%ROWTYPE;
    v_slo gda_control.gis_service_slo_binding%ROWTYPE;
    v_output_sha TEXT;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'JQDLTB serving binding tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_product FROM gda_control.data_product_version AS version
     WHERE version.tenant_id = p_tenant_id AND version.product_urn = p_product_urn
       AND version.data_product_version_id = p_data_product_version_id
       AND version.manifest_sha256 = p_manifest_sha256
       AND EXISTS (SELECT 1 FROM gda_control.data_product AS product
                    WHERE product.tenant_id = version.tenant_id
                      AND product.product_urn = version.product_urn
                      AND product.current_version_id = version.data_product_version_id);
    IF NOT FOUND THEN
        RAISE EXCEPTION 'JQDLTB serving binding requires the current DataProductVersion' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_definition FROM gda_control.gis_service_definition_version
     WHERE tenant_id = p_tenant_id AND service_definition_version_id = p_service_definition_version_id;
    IF NOT FOUND OR v_definition.service_urn IS DISTINCT FROM p_service_urn
       OR v_definition.source_product_urn IS DISTINCT FROM p_product_urn
       OR v_definition.source_data_product_version_id IS DISTINCT FROM p_data_product_version_id
       OR v_definition.source_manifest_sha256 IS DISTINCT FROM p_manifest_sha256 THEN
        RAISE EXCEPTION 'GIS service definition does not bind the exact DataProductVersion' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_layer FROM gda_control.layer_definition_version
     WHERE tenant_id = p_tenant_id AND service_definition_version_id = p_service_definition_version_id
       AND layer_definition_version_id = p_layer_definition_version_id;
    IF NOT FOUND OR v_layer.source_output_resource_version_id IS DISTINCT FROM p_output_resource_version_id THEN
        RAISE EXCEPTION 'GIS serving layer does not bind the JQDLTB ADS output' USING ERRCODE = '23514';
    END IF;
    SELECT content_sha256 INTO v_output_sha FROM gda_control.resource_version
     WHERE tenant_id = p_tenant_id AND resource_version_id = p_output_resource_version_id;
    SELECT * INTO v_projection FROM gda_control.mvt_serving_projection_version
     WHERE tenant_id = p_tenant_id AND service_definition_version_id = p_service_definition_version_id
       AND layer_definition_version_id = p_layer_definition_version_id
       AND mvt_serving_projection_version_id = p_mvt_serving_projection_version_id;
    IF NOT FOUND OR v_projection.source_output_resource_version_id IS DISTINCT FROM p_output_resource_version_id
       OR v_projection.source_content_sha256 IS DISTINCT FROM v_output_sha THEN
        RAISE EXCEPTION 'MVT projection does not bind the exact ADS content identity' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_release FROM gda_control.service_release_binding
     WHERE tenant_id = p_tenant_id AND service_definition_version_id = p_service_definition_version_id
       AND service_release_binding_id = p_service_release_binding_id;
    IF NOT FOUND OR v_release.layer_definition_version_id IS DISTINCT FROM p_layer_definition_version_id
       OR v_release.mvt_serving_projection_version_id IS DISTINCT FROM p_mvt_serving_projection_version_id THEN
        RAISE EXCEPTION 'GIS service release does not bind the exact MVT projection' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_slo FROM gda_control.gis_service_slo_binding
     WHERE tenant_id = p_tenant_id AND binding_id = p_slo_binding_id;
    IF NOT FOUND OR v_slo.service_urn IS DISTINCT FROM p_service_urn THEN
        RAISE EXCEPTION 'GIS ServiceSLO binding does not belong to the serving service' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_existing FROM gda_control.jqdltb_serving_release_binding
     WHERE tenant_id = p_tenant_id AND data_product_version_id = p_data_product_version_id;
    IF FOUND THEN
        IF v_existing.product_urn = p_product_urn AND v_existing.manifest_sha256 = p_manifest_sha256
           AND v_existing.output_resource_version_id = p_output_resource_version_id
           AND v_existing.service_urn = p_service_urn
           AND v_existing.service_definition_version_id = p_service_definition_version_id
           AND v_existing.layer_definition_version_id = p_layer_definition_version_id
           AND v_existing.mvt_serving_projection_version_id = p_mvt_serving_projection_version_id
           AND v_existing.service_release_binding_id = p_service_release_binding_id
           AND v_existing.slo_binding_id = p_slo_binding_id
           AND v_existing.serving_release_binding_sha256 = p_serving_release_binding_sha256
           AND v_existing.bound_by = p_bound_by AND v_existing.bound_at = p_bound_at THEN
            RETURN p_data_product_version_id;
        END IF;
        RAISE EXCEPTION 'JQDLTB serving binding identity has different immutable content' USING ERRCODE = '40001';
    END IF;
    -- The serving binding is part of the GIS control plane, so its insert
    -- must pass the same governed recorder guard as definitions/releases.
    PERFORM set_config('gda.gis_service_record_allowed', '1', true);
    INSERT INTO gda_control.jqdltb_serving_release_binding (
        tenant_id, data_product_version_id, product_urn, manifest_sha256,
        output_resource_version_id, service_urn, service_definition_version_id,
        layer_definition_version_id, mvt_serving_projection_version_id,
        service_release_binding_id, slo_binding_id, serving_release_binding_sha256,
        bound_by, bound_at
    ) VALUES (
        p_tenant_id, p_data_product_version_id, p_product_urn, p_manifest_sha256,
        p_output_resource_version_id, p_service_urn, p_service_definition_version_id,
        p_layer_definition_version_id, p_mvt_serving_projection_version_id,
        p_service_release_binding_id, p_slo_binding_id, p_serving_release_binding_sha256,
        p_bound_by, p_bound_at
    );
    RETURN p_data_product_version_id;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.reject_jqdltb_serving_binding_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'JQDLTB serving release bindings are immutable' USING ERRCODE = '55000';
END;
$$;
CREATE TRIGGER trg_gda_jqdltb_serving_binding_guard
BEFORE INSERT ON gda_control.jqdltb_serving_release_binding
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_gis_service_record_insert();
CREATE TRIGGER trg_gda_jqdltb_serving_binding_immutable
BEFORE UPDATE OR DELETE ON gda_control.jqdltb_serving_release_binding
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_jqdltb_serving_binding_mutation();
ALTER TABLE gda_control.jqdltb_serving_release_binding ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.jqdltb_serving_release_binding FORCE ROW LEVEL SECURITY;
CREATE POLICY gda_jqdltb_serving_tenant_policy ON gda_control.jqdltb_serving_release_binding
USING (tenant_id = current_setting('app.current_tenant', true))
WITH CHECK (tenant_id = current_setting('app.current_tenant', true));
REVOKE ALL ON TABLE gda_control.jqdltb_serving_release_binding FROM PUBLIC;
REVOKE ALL ON TABLE gda_control.jqdltb_serving_release_binding FROM agent_user;
GRANT SELECT ON TABLE gda_control.jqdltb_serving_release_binding TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.record_jqdltb_serving_release_binding(
    TEXT, UUID, TEXT, TEXT, UUID, TEXT, UUID, UUID, UUID, UUID, UUID, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.record_jqdltb_serving_release_binding(
    TEXT, UUID, TEXT, TEXT, UUID, TEXT, UUID, UUID, UUID, UUID, UUID, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
