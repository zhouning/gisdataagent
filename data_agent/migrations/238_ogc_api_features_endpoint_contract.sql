-- 238: Keep OGC API Features endpoint identity in the GIS control plane.
-- The provider may be replaced, but the active endpoint must name the exact
-- layer collection advertised by the release-bound service definition.

CREATE OR REPLACE FUNCTION gda_control.validate_ogc_api_features_endpoint_contract()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_service_type TEXT;
    v_layer_key TEXT;
BEGIN
    IF NEW.endpoint_protocol <> 'ogc_api_features' THEN
        RETURN NEW;
    END IF;

    SELECT definition.service_type, layer.layer_key
      INTO v_service_type, v_layer_key
      FROM gda_control.service_deployment_revision AS deployment
      JOIN gda_control.gis_service_definition_version AS definition
        ON definition.tenant_id = deployment.tenant_id
       AND definition.service_definition_version_id = deployment.service_definition_version_id
      JOIN gda_control.layer_definition_version AS layer
        ON layer.tenant_id = deployment.tenant_id
       AND layer.service_definition_version_id = deployment.service_definition_version_id
     WHERE deployment.tenant_id = NEW.tenant_id
       AND deployment.deployment_revision_id = NEW.deployment_revision_id
       AND layer.layer_definition_version_id = (
           SELECT release.layer_definition_version_id
             FROM gda_control.service_deployment_revision AS release_deployment
             JOIN gda_control.service_release_binding AS release
               ON release.tenant_id = release_deployment.tenant_id
              AND release.service_release_binding_id = release_deployment.service_release_binding_id
            WHERE release_deployment.tenant_id = NEW.tenant_id
              AND release_deployment.deployment_revision_id = NEW.deployment_revision_id
       );

    IF v_service_type IS DISTINCT FROM 'feature' THEN
        RAISE EXCEPTION 'OGC API Features endpoint requires a feature service'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.endpoint_contract->>'schema' IS DISTINCT FROM 'gda.ogc_api_features_endpoint.v1'
       OR NEW.endpoint_contract->>'collection_id' IS DISTINCT FROM v_layer_key
       OR (SELECT count(*) FROM jsonb_object_keys(NEW.endpoint_contract)) <> 2 THEN
        RAISE EXCEPTION 'OGC API Features endpoint must bind its release layer collection exactly'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_ogc_api_features_endpoint_contract
    ON gda_control.endpoint_revision;
CREATE TRIGGER trg_validate_ogc_api_features_endpoint_contract
    BEFORE INSERT ON gda_control.endpoint_revision
    FOR EACH ROW
    EXECUTE FUNCTION gda_control.validate_ogc_api_features_endpoint_contract();

CREATE OR REPLACE FUNCTION gda_control.validate_ogc_api_features_activation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_endpoint gda_control.endpoint_revision%ROWTYPE;
    v_layer_key TEXT;
BEGIN
    SELECT endpoint.* INTO v_endpoint
      FROM gda_control.endpoint_revision AS endpoint
     WHERE endpoint.tenant_id = NEW.tenant_id
       AND endpoint.endpoint_revision_id = NEW.to_endpoint_revision_id;
    IF NOT FOUND OR v_endpoint.endpoint_protocol <> 'ogc_api_features' THEN
        RETURN NEW;
    END IF;
    SELECT layer.layer_key INTO v_layer_key
      FROM gda_control.service_deployment_revision AS deployment
      JOIN gda_control.service_release_binding AS release
        ON release.tenant_id = deployment.tenant_id
       AND release.service_release_binding_id = deployment.service_release_binding_id
      JOIN gda_control.layer_definition_version AS layer
        ON layer.tenant_id = release.tenant_id
       AND layer.layer_definition_version_id = release.layer_definition_version_id
     WHERE deployment.tenant_id = v_endpoint.tenant_id
       AND deployment.deployment_revision_id = v_endpoint.deployment_revision_id;
    IF v_endpoint.endpoint_contract->>'schema' IS DISTINCT FROM 'gda.ogc_api_features_endpoint.v1'
       OR v_endpoint.endpoint_contract->>'collection_id' IS DISTINCT FROM v_layer_key
       OR (SELECT count(*) FROM jsonb_object_keys(v_endpoint.endpoint_contract)) <> 2 THEN
        RAISE EXCEPTION 'OGC API Features activation must bind its release layer collection exactly'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_ogc_api_features_activation
    ON gda_control.gis_service_endpoint_activation_event;
CREATE TRIGGER trg_validate_ogc_api_features_activation
    BEFORE INSERT ON gda_control.gis_service_endpoint_activation_event
    FOR EACH ROW
    EXECUTE FUNCTION gda_control.validate_ogc_api_features_activation();

REVOKE ALL ON FUNCTION gda_control.validate_ogc_api_features_endpoint_contract()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.validate_ogc_api_features_activation()
    FROM PUBLIC;
