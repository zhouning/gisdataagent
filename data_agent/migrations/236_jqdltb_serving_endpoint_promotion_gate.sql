-- 236: Consume the JQDLTB serving bridge at GIS endpoint promotion.
--
-- Generic GIS services retain the existing release/cache/policy gates.  A
-- definition whose product version is explicitly marked as JQDLTB must also
-- have the exact post-publication serving binding recorded by migration 235.

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
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_jqdltb_active_endpoint_serving_binding
    ON gda_control.gis_service;
CREATE TRIGGER trg_gda_jqdltb_active_endpoint_serving_binding
BEFORE UPDATE OF active_endpoint_revision_id ON gda_control.gis_service
FOR EACH ROW EXECUTE FUNCTION gda_control.enforce_jqdltb_serving_endpoint_binding();

REVOKE ALL ON FUNCTION gda_control.enforce_jqdltb_serving_endpoint_binding()
    FROM PUBLIC;
