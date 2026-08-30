-- 216: Harden renewal recorder against forged decision actor/timestamp.
--
-- Keep the 215 implementation available as a private implementation detail,
-- and put the ApprovalCase decision identity check at the Gateway-executable
-- function boundary.

ALTER FUNCTION gda_control.record_service_consumer_binding_renewal(
    TEXT, UUID, UUID, CHAR(64), UUID, TEXT, UUID, UUID, TEXT, TEXT, TEXT,
    JSONB, TEXT, TIMESTAMPTZ, CHAR(64), JSONB, CHAR(64), TEXT, TIMESTAMPTZ,
    TEXT, CHAR(64), TEXT, TIMESTAMPTZ
) RENAME TO record_service_consumer_binding_renewal_unverified;

CREATE FUNCTION gda_control.record_service_consumer_binding_renewal(
    p_tenant_id TEXT,
    p_service_consumer_binding_renewal_id UUID,
    p_source_binding_id UUID,
    p_source_binding_sha256 CHAR(64),
    p_target_binding_id UUID,
    p_service_urn TEXT,
    p_service_definition_version_id UUID,
    p_service_release_binding_id UUID,
    p_consumer_ref TEXT,
    p_action TEXT,
    p_purpose TEXT,
    p_scope JSONB,
    p_credential_ref TEXT,
    p_expires_at TIMESTAMPTZ,
    p_compatibility_fingerprint CHAR(64),
    p_compatibility_evidence JSONB,
    p_target_binding_sha256 CHAR(64),
    p_created_by TEXT,
    p_created_at TIMESTAMPTZ,
    p_approval_case_ref TEXT,
    p_renewal_plan_sha256 CHAR(64),
    p_renewed_by TEXT,
    p_renewed_at TIMESTAMPTZ
)
RETURNS TABLE(service_consumer_binding_renewal_id UUID, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_case gda_control.approval_case%ROWTYPE;
BEGIN
    IF p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION
            'service consumer binding renewal tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;

    SELECT approval.* INTO v_case
      FROM gda_control.approval_case AS approval
     WHERE approval.tenant_id = p_tenant_id
       AND approval.approval_case_ref = p_approval_case_ref
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'service consumer binding renewal ApprovalCase was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_case.status <> 'approved'
       OR v_case.action <> 'gis_service_consumer_binding.renew'
       OR v_case.target_fingerprint <> p_renewal_plan_sha256
       OR v_case.decided_by IS DISTINCT FROM p_renewed_by
       OR v_case.decided_at IS NULL
       OR p_renewed_at IS NULL
       OR v_case.decided_at IS DISTINCT FROM p_renewed_at
       OR p_renewed_at > clock_timestamp() THEN
        RAISE EXCEPTION
            'renewal actor and timestamp must match the approved human decision'
            USING ERRCODE = '23514';
    END IF;

    RETURN QUERY
    SELECT * FROM gda_control.record_service_consumer_binding_renewal_unverified(
        p_tenant_id,
        p_service_consumer_binding_renewal_id,
        p_source_binding_id,
        p_source_binding_sha256,
        p_target_binding_id,
        p_service_urn,
        p_service_definition_version_id,
        p_service_release_binding_id,
        p_consumer_ref,
        p_action,
        p_purpose,
        p_scope,
        p_credential_ref,
        p_expires_at,
        p_compatibility_fingerprint,
        p_compatibility_evidence,
        p_target_binding_sha256,
        p_created_by,
        p_created_at,
        p_approval_case_ref,
        p_renewal_plan_sha256,
        p_renewed_by,
        p_renewed_at
    );
END;
$$;

REVOKE ALL ON FUNCTION gda_control.record_service_consumer_binding_renewal_unverified(
    TEXT, UUID, UUID, CHAR(64), UUID, TEXT, UUID, UUID, TEXT, TEXT, TEXT,
    JSONB, TEXT, TIMESTAMPTZ, CHAR(64), JSONB, CHAR(64), TEXT, TIMESTAMPTZ,
    TEXT, CHAR(64), TEXT, TIMESTAMPTZ
) FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.record_service_consumer_binding_renewal(
    TEXT, UUID, UUID, CHAR(64), UUID, TEXT, UUID, UUID, TEXT, TEXT, TEXT,
    JSONB, TEXT, TIMESTAMPTZ, CHAR(64), JSONB, CHAR(64), TEXT, TIMESTAMPTZ,
    TEXT, CHAR(64), TEXT, TIMESTAMPTZ
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.record_service_consumer_binding_renewal(
    TEXT, UUID, UUID, CHAR(64), UUID, TEXT, UUID, UUID, TEXT, TEXT, TEXT,
    JSONB, TEXT, TIMESTAMPTZ, CHAR(64), JSONB, CHAR(64), TEXT, TIMESTAMPTZ,
    TEXT, CHAR(64), TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
