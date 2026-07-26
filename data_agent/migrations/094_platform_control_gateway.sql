-- 094: Least-privilege database role for the AR-1 platform gateway.
--
-- The role is deliberately NOLOGIN and NOINHERIT. A deployment-specific login
-- must be granted membership out of band and explicitly SET LOCAL ROLE inside
-- each transaction. This migration never creates or stores login credentials.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gda_control_gateway') THEN
        CREATE ROLE gda_control_gateway
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
END
$$;

ALTER ROLE gda_control_gateway
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;

-- The trigger must append the initial RunEvent without granting the gateway
-- role arbitrary INSERT on the event ledger.
ALTER FUNCTION gda_control.initialize_platform_run_event() SECURITY DEFINER;
ALTER FUNCTION gda_control.initialize_platform_run_event()
    SET search_path TO pg_catalog, gda_control;
ALTER FUNCTION gda_control.initialize_platform_run_event()
    SET row_security TO on;

REVOKE ALL ON SCHEMA gda_control FROM gda_control_gateway;
REVOKE ALL ON ALL TABLES IN SCHEMA gda_control FROM gda_control_gateway;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA gda_control FROM gda_control_gateway;

GRANT USAGE ON SCHEMA gda_control TO gda_control_gateway;

GRANT SELECT ON
    gda_control.resource,
    gda_control.resource_version,
    gda_control.platform_definition_version,
    gda_control.platform_run,
    gda_control.platform_run_input_binding,
    gda_control.platform_run_event,
    gda_control.framework_attempt_observation,
    gda_control.artifact,
    gda_control.lineage_event
TO gda_control_gateway;

GRANT INSERT ON
    gda_control.resource,
    gda_control.resource_version,
    gda_control.platform_definition_version,
    gda_control.platform_run,
    gda_control.platform_run_input_binding,
    gda_control.framework_attempt_observation,
    gda_control.artifact,
    gda_control.lineage_event
TO gda_control_gateway;

GRANT EXECUTE ON FUNCTION gda_control.current_tenant()
    TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.transition_platform_run(
    text, uuid, integer, text, text, text, jsonb
) TO gda_control_gateway;

REVOKE CREATE ON SCHEMA gda_control FROM gda_control_gateway;
