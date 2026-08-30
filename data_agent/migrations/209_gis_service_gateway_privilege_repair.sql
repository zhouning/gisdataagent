-- 209: Restore the least-privilege Gateway ACL for the GIS service control plane.
--
-- A migration ledger can be current while an operational role grant has been
-- removed later by environment administration.  The Gateway must be able to
-- read its own active control projection and use only the existing controlled
-- recorder functions.  This migration deliberately grants no direct mutation
-- of immutable GIS control-plane tables.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'gda_control_gateway'
    ) THEN
        RAISE EXCEPTION 'gda_control_gateway role is required before GIS ACL repair';
    END IF;
END;
$$;

REVOKE ALL ON TABLE
    gda_control.gis_service,
    gda_control.gis_service_definition_version,
    gda_control.layer_definition_version,
    gda_control.style_definition_version,
    gda_control.tile_matrix_set_definition_version,
    gda_control.cache_policy_version,
    gda_control.service_policy_binding,
    gda_control.mvt_serving_projection_version,
    gda_control.service_release_binding,
    gda_control.service_deployment_revision,
    gda_control.service_deployment_event,
    gda_control.endpoint_revision,
    gda_control.gis_service_endpoint_activation_event
FROM PUBLIC, gda_control_gateway;

GRANT SELECT ON TABLE
    gda_control.gis_service,
    gda_control.gis_service_definition_version,
    gda_control.layer_definition_version,
    gda_control.style_definition_version,
    gda_control.tile_matrix_set_definition_version,
    gda_control.cache_policy_version,
    gda_control.service_policy_binding,
    gda_control.mvt_serving_projection_version,
    gda_control.service_release_binding,
    gda_control.service_deployment_revision,
    gda_control.service_deployment_event,
    gda_control.endpoint_revision,
    gda_control.gis_service_endpoint_activation_event
TO gda_control_gateway;

REVOKE ALL ON TABLE gda_control.framework_attempt_observation
FROM PUBLIC, gda_control_gateway;
GRANT SELECT, INSERT ON TABLE gda_control.framework_attempt_observation
TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.record_gis_service_definition_version(
    TEXT, UUID, TEXT, TEXT, UUID, UUID, TEXT, UUID, TEXT, TEXT, JSONB,
    TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
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
REVOKE ALL ON FUNCTION gda_control.record_cache_policy_version(
    TEXT, UUID, UUID, TEXT, TEXT, UUID, TEXT, INTEGER, TEXT[], TEXT, TEXT,
    TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_service_policy_binding(
    TEXT, UUID, UUID, UUID, TEXT, TEXT, UUID, TEXT, TEXT, TEXT[], TEXT[],
    TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_mvt_serving_projection_version(
    TEXT, UUID, UUID, UUID, TEXT, TEXT, UUID, UUID, TEXT, TEXT, TEXT,
    INTEGER, TEXT, TEXT[], DOUBLE PRECISION[], INTEGER, TEXT, TEXT, TEXT,
    TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_service_release_binding(
    TEXT, UUID, UUID, UUID, UUID, UUID, UUID, UUID, TEXT, TEXT, TEXT,
    TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_service_deployment_revision(
    TEXT, UUID, UUID, UUID, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.transition_service_deployment_revision(
    TEXT, UUID, INTEGER, TEXT, UUID, TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_endpoint_revision(
    TEXT, UUID, TEXT, UUID, TEXT, TEXT, JSONB, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.activate_gis_service_endpoint(
    TEXT, TEXT, UUID, INTEGER, TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION gda_control.record_gis_service_definition_version(
    TEXT, UUID, TEXT, TEXT, UUID, UUID, TEXT, UUID, TEXT, TEXT, JSONB,
    TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
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
GRANT EXECUTE ON FUNCTION gda_control.record_cache_policy_version(
    TEXT, UUID, UUID, TEXT, TEXT, UUID, TEXT, INTEGER, TEXT[], TEXT, TEXT,
    TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_service_policy_binding(
    TEXT, UUID, UUID, UUID, TEXT, TEXT, UUID, TEXT, TEXT, TEXT[], TEXT[],
    TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_mvt_serving_projection_version(
    TEXT, UUID, UUID, UUID, TEXT, TEXT, UUID, UUID, TEXT, TEXT, TEXT,
    INTEGER, TEXT, TEXT[], DOUBLE PRECISION[], INTEGER, TEXT, TEXT, TEXT,
    TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_service_release_binding(
    TEXT, UUID, UUID, UUID, UUID, UUID, UUID, UUID, TEXT, TEXT, TEXT,
    TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_service_deployment_revision(
    TEXT, UUID, UUID, UUID, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.transition_service_deployment_revision(
    TEXT, UUID, INTEGER, TEXT, UUID, TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_endpoint_revision(
    TEXT, UUID, TEXT, UUID, TEXT, TEXT, JSONB, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.activate_gis_service_endpoint(
    TEXT, TEXT, UUID, INTEGER, TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
