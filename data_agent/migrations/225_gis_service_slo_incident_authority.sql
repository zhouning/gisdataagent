-- 225: Atomically gate a GIS ServiceSLO incident on the exact active binding.
--
-- Alertmanager reconciliation must not validate a ServiceSLO binding in one
-- transaction and insert DataIncident in another. This authority locks the
-- active generic SLO row and exact GIS projection row until the caller's
-- incident transaction commits.

CREATE OR REPLACE FUNCTION gda_control.assert_gis_service_slo_incident_authority(
    p_tenant_id TEXT,
    p_service_urn TEXT,
    p_slo_definition_ref TEXT,
    p_active_version_ref TEXT,
    p_definition_fingerprint TEXT,
    p_approval_case_ref TEXT,
    p_activation_version INTEGER
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_active gda_control.slo_definition_activation%ROWTYPE;
    v_definition gda_control.slo_definition_version%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'GIS ServiceSLO incident tenant context mismatch'
            USING ERRCODE = '42501';
    END IF;
    IF p_service_urn !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/gis_service/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_service_urn, '/', 3) <> p_tenant_id
       OR p_slo_definition_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/slo_definition/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_slo_definition_ref, '/', 3) <> p_tenant_id
       OR p_active_version_ref IS NULL
       OR p_definition_fingerprint !~ '^[0-9a-f]{64}$'
       OR p_approval_case_ref IS NULL
       OR p_activation_version < 1 THEN
        RAISE EXCEPTION 'GIS ServiceSLO incident authority identity is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM gda_control.gis_service
        WHERE tenant_id = p_tenant_id AND service_urn = p_service_urn
    ) THEN
        RAISE EXCEPTION 'GIS service % was not found', p_service_urn
            USING ERRCODE = 'P0002';
    END IF;

    -- FOR SHARE prevents an activation CAS update from committing while the
    -- caller writes the incident in the same transaction.
    SELECT * INTO v_active
    FROM gda_control.slo_definition_activation
    WHERE tenant_id = p_tenant_id
      AND slo_definition_ref = p_slo_definition_ref
    FOR SHARE;
    IF NOT FOUND
       OR v_active.active_version_ref IS DISTINCT FROM p_active_version_ref
       OR v_active.active_fingerprint IS DISTINCT FROM p_definition_fingerprint
       OR v_active.approval_case_ref IS DISTINCT FROM p_approval_case_ref
       OR v_active.activation_version IS DISTINCT FROM p_activation_version THEN
        RAISE EXCEPTION 'GIS ServiceSLO incident requires the exact active authority'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_definition
    FROM gda_control.slo_definition_version
    WHERE tenant_id = p_tenant_id
      AND slo_version_ref = p_active_version_ref
      AND definition_fingerprint = p_definition_fingerprint
      AND service_resource_urn = p_service_urn
    FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS ServiceSLO incident definition does not match the service'
            USING ERRCODE = '23514';
    END IF;

    PERFORM 1
    FROM gda_control.gis_service_slo_binding
    WHERE tenant_id = p_tenant_id
      AND service_urn = p_service_urn
      AND slo_definition_ref = p_slo_definition_ref
      AND active_version_ref = p_active_version_ref
      AND definition_fingerprint = p_definition_fingerprint
      AND approval_case_ref = p_approval_case_ref
      AND activation_version = p_activation_version
    FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS ServiceSLO incident has no exact binding'
            USING ERRCODE = '23514';
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION gda_control.assert_gis_service_slo_incident_authority(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER
) FROM PUBLIC, gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.assert_gis_service_slo_incident_authority(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER
) TO gda_control_gateway;
