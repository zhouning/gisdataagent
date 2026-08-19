-- 194: Repair the exact gateway reads required by MetricObservation.
--
-- A legacy replay of migration 094 can revoke schema-wide gateway privileges
-- after the metric migrations have already been recorded. Reassert only the
-- tenant-RLS-protected reads used by query ownership checks and projection.

DO $$
DECLARE
    required_table TEXT;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname = 'gda_control_gateway'
    ) THEN
        RAISE EXCEPTION 'gda_control_gateway role is required before metric ACL repair'
            USING ERRCODE = '42704';
    END IF;

    FOREACH required_table IN ARRAY ARRAY[
        'gda_control.metric_definition_version',
        'gda_control.metric_query_execution_admission',
        'gda_control.metric_query_execution_observation'
    ]
    LOOP
        IF to_regclass(required_table) IS NULL THEN
            RAISE EXCEPTION 'required metric table is missing: %', required_table
                USING ERRCODE = '42P01';
        END IF;
    END LOOP;
END
$$;

GRANT SELECT ON gda_control.metric_definition_version
    TO gda_control_gateway;
GRANT SELECT ON gda_control.metric_query_execution_admission
    TO gda_control_gateway;
GRANT SELECT ON gda_control.metric_query_execution_observation
    TO gda_control_gateway;
