-- 184: Enforce customer compensation rule lifecycle monotonicity at the table boundary.
--
-- Migration 183 validates the governed function path before idempotency. This
-- trigger also protects any future governed SQL entry point that can insert.

CREATE OR REPLACE FUNCTION gda_control.guard_customer_compensation_rule_lifecycle()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_current_status TEXT;
    v_current_rank INTEGER;
    v_new_rank INTEGER;
BEGIN
    SELECT stored.status INTO v_current_status
    FROM gda_control.customer_compensation_rule_contract AS stored
    WHERE stored.tenant_id = NEW.tenant_id
      AND stored.rule_id = NEW.rule_id
    ORDER BY stored.recorded_at DESC, stored.contract_sha256 DESC
    LIMIT 1;

    IF FOUND THEN
        v_current_rank := CASE v_current_status
            WHEN 'draft_unreviewed' THEN 1
            WHEN 'awaiting_customer_approval' THEN 2
            WHEN 'customer_approved' THEN 3
        END;
        v_new_rank := CASE NEW.status
            WHEN 'draft_unreviewed' THEN 1
            WHEN 'awaiting_customer_approval' THEN 2
            WHEN 'customer_approved' THEN 3
        END;
        IF v_new_rank < v_current_rank THEN
            RAISE EXCEPTION 'customer compensation rule lifecycle cannot regress'
                USING ERRCODE = '22023';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_customer_compensation_rule_lifecycle_guard
    ON gda_control.customer_compensation_rule_contract;
CREATE TRIGGER trg_gda_customer_compensation_rule_lifecycle_guard
BEFORE INSERT ON gda_control.customer_compensation_rule_contract
FOR EACH ROW
EXECUTE FUNCTION gda_control.guard_customer_compensation_rule_lifecycle();

REVOKE ALL ON FUNCTION
    gda_control.guard_customer_compensation_rule_lifecycle()
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    gda_control.guard_customer_compensation_rule_lifecycle()
    TO gda_control_gateway;
