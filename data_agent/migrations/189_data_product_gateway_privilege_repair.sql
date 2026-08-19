-- 189: Repair DataProduct gateway ACL drift caused by out-of-order 094 replay.
--
-- Migration 100 originally granted these exact privileges. A legacy real-
-- PostgreSQL test later replayed migration 094 against a shared database and
-- committed its schema-wide gateway revoke while skipping migration 100 when
-- the DataProduct tables already existed. Reassert the least-privilege target;
-- runtime login membership remains an environment-owned operation.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname = 'gda_control_gateway'
    ) THEN
        RAISE EXCEPTION 'gda_control_gateway role is required before ACL repair'
            USING ERRCODE = '42704';
    END IF;
    IF to_regclass('gda_control.data_product') IS NULL
       OR to_regclass('gda_control.data_product_version') IS NULL
       OR to_regclass('gda_control.data_product_event') IS NULL THEN
        RAISE EXCEPTION 'DataProduct registry tables are required before ACL repair'
            USING ERRCODE = '42P01';
    END IF;
END
$$;

REVOKE ALL ON TABLE gda_control.data_product
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.data_product_version
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.data_product_event
    FROM PUBLIC, gda_control_gateway;

GRANT SELECT, INSERT, UPDATE ON TABLE gda_control.data_product
    TO gda_control_gateway;
GRANT SELECT, INSERT ON TABLE gda_control.data_product_version
    TO gda_control_gateway;
GRANT SELECT, INSERT ON TABLE gda_control.data_product_event
    TO gda_control_gateway;
