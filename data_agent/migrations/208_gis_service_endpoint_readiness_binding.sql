-- 208: Require every new endpoint revision to match the ready deployment evidence.
--
-- Endpoint metadata is a control-plane projection, not an independently chosen
-- provider address. Reuse the existing deployment and observation ledgers; no
-- endpoint-health table, registry, queue, or provider worker is introduced.

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
    v_terminal_observation_id UUID;
    v_observed_endpoint_uri TEXT;
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
           deployment.terminal_observation_id,
           observation.evidence ->> 'endpoint_uri',
           definition.service_urn, definition.service_type,
           release.mvt_serving_projection_version_id
      INTO v_deployment_state, v_deployment_terminal_at,
           v_terminal_observation_id, v_observed_endpoint_uri,
           v_service_urn, v_service_type, v_mvt_serving_projection_version_id
      FROM gda_control.service_deployment_revision AS deployment
      JOIN gda_control.gis_service_definition_version AS definition
        ON definition.tenant_id = deployment.tenant_id
       AND definition.service_definition_version_id = deployment.service_definition_version_id
      LEFT JOIN gda_control.service_release_binding AS release
        ON release.tenant_id = deployment.tenant_id
       AND release.service_definition_version_id = deployment.service_definition_version_id
       AND release.service_release_binding_id = deployment.service_release_binding_id
      LEFT JOIN gda_control.framework_attempt_observation AS observation
        ON observation.tenant_id = deployment.tenant_id
       AND observation.observation_id = deployment.terminal_observation_id
       AND observation.run_id = deployment.run_id
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
    IF v_terminal_observation_id IS NULL
       OR v_observed_endpoint_uri IS DISTINCT FROM p_endpoint_uri THEN
        RAISE EXCEPTION 'endpoint revision must match the ready deployment evidence URI'
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

REVOKE ALL ON FUNCTION gda_control.record_endpoint_revision(
    TEXT, UUID, TEXT, UUID, TEXT, TEXT, JSONB, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.record_endpoint_revision(
    TEXT, UUID, TEXT, UUID, TEXT, TEXT, JSONB, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
