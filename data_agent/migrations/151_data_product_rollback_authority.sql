-- 151: Bind every DataProduct rollback to an active Incident or human approval.
--
-- The product pointer remains mutable only through the registry transaction;
-- the lifecycle event carries immutable authority evidence and direct SQL
-- rollback inserts are rejected by the trigger below.

ALTER TABLE gda_control.data_product_event
    ADD COLUMN IF NOT EXISTS rollback_authority_kind TEXT,
    ADD COLUMN IF NOT EXISTS rollback_authority_ref TEXT,
    ADD COLUMN IF NOT EXISTS rollback_authority_sha256 CHAR(64);

ALTER TABLE gda_control.data_product_event
    DROP CONSTRAINT IF EXISTS ck_gda_data_product_event_rollback_authority;
ALTER TABLE gda_control.data_product_event
    ADD CONSTRAINT ck_gda_data_product_event_rollback_authority CHECK (
        (
            event_type = 'rolled_back'
            AND rollback_authority_kind IN ('incident', 'approval_case')
            AND NULLIF(btrim(rollback_authority_ref), '') IS NOT NULL
            AND rollback_authority_sha256 ~ '^[0-9a-f]{64}$'
        )
        OR (
            event_type <> 'rolled_back'
            AND rollback_authority_kind IS NULL
            AND rollback_authority_ref IS NULL
            AND rollback_authority_sha256 IS NULL
        )
    ) NOT VALID;

CREATE OR REPLACE FUNCTION gda_control.guard_data_product_rollback_event()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_subject_resource_urn TEXT;
    v_incident_status TEXT;
    v_incident_sha256 TEXT;
    v_case_target TEXT;
    v_case_fingerprint TEXT;
    v_case_action TEXT;
    v_case_status TEXT;
    v_case_context JSONB;
    v_case_decided_at TIMESTAMPTZ;
    v_case_expires_at TIMESTAMPTZ;
BEGIN
    IF NEW.event_type <> 'rolled_back' THEN
        RETURN NEW;
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'rollback event tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF COALESCE(
        current_setting('gda.data_product_rollback_event_allowed', true), ''
    ) <> '1' THEN
        RAISE EXCEPTION 'use the governed DataProduct rollback recorder'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.rollback_authority_kind = 'incident' THEN
        IF to_regclass('gda_control.data_incident') IS NULL THEN
            RAISE EXCEPTION 'DataIncident authority migration is not installed'
                USING ERRCODE = '55000';
        END IF;
        EXECUTE $query$
            SELECT subject_resource_urn, status, incident_sha256
              FROM gda_control.data_incident
             WHERE tenant_id = $1
               AND incident_id = $2::uuid
        $query$
        INTO v_subject_resource_urn, v_incident_status, v_incident_sha256
        USING NEW.tenant_id, NEW.rollback_authority_ref;
        IF v_subject_resource_urn IS DISTINCT FROM NEW.product_urn
           OR v_incident_status NOT IN ('open', 'acknowledged')
           OR v_incident_sha256 IS DISTINCT FROM NEW.rollback_authority_sha256 THEN
            RAISE EXCEPTION 'rollback Incident authority is not active and product-bound'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.rollback_authority_kind = 'approval_case' THEN
        IF to_regclass('gda_control.approval_case') IS NULL THEN
            RAISE EXCEPTION 'ApprovalCase authority migration is not installed'
                USING ERRCODE = '55000';
        END IF;
        EXECUTE $query$
            SELECT target_resource_urn, target_fingerprint, action, status,
                   request_context, decided_at, expires_at
              FROM gda_control.approval_case
             WHERE tenant_id = $1
               AND approval_case_ref = $2
        $query$
        INTO v_case_target, v_case_fingerprint, v_case_action,
             v_case_status, v_case_context, v_case_decided_at,
             v_case_expires_at
        USING NEW.tenant_id, NEW.rollback_authority_ref;
        IF v_case_target IS DISTINCT FROM NEW.product_urn
           OR v_case_fingerprint IS DISTINCT FROM NEW.rollback_authority_sha256
           OR v_case_action IS DISTINCT FROM 'data_product.rollback'
           OR v_case_status IS DISTINCT FROM 'approved'
           OR v_case_decided_at IS NULL
           OR v_case_decided_at > NEW.occurred_at
           OR NEW.occurred_at >= v_case_expires_at
           OR v_case_context->>'schema' IS DISTINCT FROM
                'gda.data_product.rollback.v1'
           OR v_case_context->>'product_urn' IS DISTINCT FROM NEW.product_urn
           OR v_case_context->>'from_version_id' IS DISTINCT FROM
                NEW.from_version_id::text
           OR v_case_context->>'to_version_id' IS DISTINCT FROM
                NEW.to_version_id::text THEN
            RAISE EXCEPTION 'rollback ApprovalCase authority does not bind this event'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'rollback authority kind is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_data_product_rollback_event_guard
    ON gda_control.data_product_event;
CREATE TRIGGER trg_gda_data_product_rollback_event_guard
BEFORE INSERT ON gda_control.data_product_event
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_data_product_rollback_event();

REVOKE ALL ON FUNCTION gda_control.guard_data_product_rollback_event() FROM PUBLIC;
