-- 213: Approval-bound issuance for exact-release GIS service consumer bindings.
--
-- Migration 212 established the immutable endpoint authorization fact.  This
-- migration attaches new issuance to the existing generic ApprovalCase
-- authority.  Historic 212 rows remain readable with null lifecycle columns;
-- the replacement recorder requires the two columns for every new row.

ALTER TABLE gda_control.service_consumer_binding
    ADD COLUMN approval_case_ref TEXT,
    ADD COLUMN grant_plan_sha256 CHAR(64);

ALTER TABLE gda_control.service_consumer_binding
    ADD CONSTRAINT fk_gda_service_consumer_binding_approval_case
        FOREIGN KEY (tenant_id, approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    ADD CONSTRAINT ck_gda_service_consumer_binding_approval_binding CHECK (
        (
            approval_case_ref IS NULL
            AND grant_plan_sha256 IS NULL
        ) OR (
            approval_case_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/[a-z0-9][a-z0-9._-]{0,127}$'
            AND split_part(approval_case_ref, '/', 3) = tenant_id
            AND grant_plan_sha256 ~ '^[0-9a-f]{64}$'
        )
    );

CREATE UNIQUE INDEX uq_gda_service_consumer_binding_approval_case
    ON gda_control.service_consumer_binding(tenant_id, approval_case_ref)
    WHERE approval_case_ref IS NOT NULL;

-- The 16-argument recorder remains installed only for migration history.  The
-- Gateway no longer has EXECUTE, so it cannot bypass the approval-bound form.
REVOKE ALL ON FUNCTION gda_control.record_service_consumer_binding(
    TEXT, UUID, TEXT, UUID, UUID, TEXT, TEXT, TEXT, JSONB, TEXT,
    TIMESTAMPTZ, CHAR(64), JSONB, CHAR(64), TEXT, TIMESTAMPTZ
) FROM PUBLIC, gda_control_gateway;

CREATE FUNCTION gda_control.record_service_consumer_binding(
    p_tenant_id TEXT,
    p_service_consumer_binding_id UUID,
    p_approval_case_ref TEXT,
    p_grant_plan_sha256 CHAR(64),
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
    p_binding_sha256 CHAR(64),
    p_created_by TEXT,
    p_created_at TIMESTAMPTZ
)
RETURNS TABLE(service_consumer_binding_id UUID, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_case gda_control.approval_case%ROWTYPE;
    v_plan JSONB;
    v_existing gda_control.service_consumer_binding%ROWTYPE;
    v_inserted UUID;
    v_expected_case_ref TEXT;
BEGIN
    IF p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'service consumer binding tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;

    v_expected_case_ref := format(
        'gda://%s/approval_case/gis-service-consumer-binding-grant-%s',
        p_tenant_id,
        replace(p_service_consumer_binding_id::TEXT, '-', '')
    );
    IF p_approval_case_ref IS NULL
       OR p_approval_case_ref <> v_expected_case_ref
       OR p_grant_plan_sha256 IS NULL
       OR p_grant_plan_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'service consumer binding requires its deterministic grant ApprovalCase and plan fingerprint'
            USING ERRCODE = '22023';
    END IF;

    SELECT approval.* INTO v_case
      FROM gda_control.approval_case AS approval
     WHERE approval.tenant_id = p_tenant_id
       AND approval.approval_case_ref = p_approval_case_ref
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'service consumer binding grant ApprovalCase was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_case.status <> 'approved'
       OR clock_timestamp() >= v_case.expires_at
       OR v_case.action <> 'gis_service_consumer_binding.grant'
       OR v_case.target_resource_urn <> p_service_urn
       OR v_case.target_fingerprint <> p_grant_plan_sha256 THEN
        RAISE EXCEPTION 'service consumer binding requires a live approved matching grant ApprovalCase'
            USING ERRCODE = '23514';
    END IF;

    v_plan := v_case.request_context -> 'service_consumer_binding';
    IF v_case.request_context ->> 'schema'
           <> 'gda.gis_service_consumer_binding_grant.v1'
       OR v_case.request_context ->> 'grant_plan_sha256'
           <> p_grant_plan_sha256
       OR jsonb_typeof(v_plan) <> 'object'
       OR v_plan ->> 'tenant_id' <> p_tenant_id
       OR v_plan ->> 'service_consumer_binding_id'
           <> p_service_consumer_binding_id::TEXT
       OR v_plan ->> 'service_urn' <> p_service_urn
       OR v_plan ->> 'service_definition_version_id'
           <> p_service_definition_version_id::TEXT
       OR v_plan ->> 'service_release_binding_id'
           <> p_service_release_binding_id::TEXT
       OR v_plan ->> 'consumer_ref' <> p_consumer_ref
       OR v_plan ->> 'action' <> p_action
       OR v_plan ->> 'purpose' <> p_purpose
       OR v_plan -> 'scope' IS DISTINCT FROM p_scope
       OR v_plan ->> 'credential_ref' <> p_credential_ref
       OR (v_plan ->> 'expires_at')::TIMESTAMPTZ IS DISTINCT FROM p_expires_at
       OR v_plan ->> 'compatibility_fingerprint'
           <> p_compatibility_fingerprint::TEXT
       OR v_plan -> 'compatibility_evidence'
           IS DISTINCT FROM p_compatibility_evidence
       OR v_plan ->> 'binding_sha256' <> p_binding_sha256::TEXT
       OR v_plan ->> 'created_by' <> p_created_by
       OR (v_plan ->> 'created_at')::TIMESTAMPTZ IS DISTINCT FROM p_created_at THEN
        RAISE EXCEPTION 'grant ApprovalCase does not authorize this service consumer binding payload'
            USING ERRCODE = '23514';
    END IF;

    PERFORM 1
      FROM gda_control.gis_service_definition_version AS definition
      JOIN gda_control.service_release_binding AS release
        ON release.tenant_id = definition.tenant_id
       AND release.service_definition_version_id = definition.service_definition_version_id
       AND release.service_release_binding_id = p_service_release_binding_id
     WHERE definition.tenant_id = p_tenant_id
       AND definition.service_definition_version_id = p_service_definition_version_id
       AND definition.service_urn = p_service_urn
       AND definition.service_type = 'vector_tile';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'service consumer binding must target one vector-tile service release'
            USING ERRCODE = '23514';
    END IF;

    PERFORM set_config('gda.service_consumer_binding_allowed', '1', true);
    INSERT INTO gda_control.service_consumer_binding (
        tenant_id, service_consumer_binding_id, approval_case_ref,
        grant_plan_sha256, service_urn, service_definition_version_id,
        service_release_binding_id, consumer_ref, action, purpose, scope,
        credential_ref, expires_at, compatibility_fingerprint,
        compatibility_evidence, binding_sha256, created_by, created_at
    ) VALUES (
        p_tenant_id, p_service_consumer_binding_id, p_approval_case_ref,
        p_grant_plan_sha256, p_service_urn, p_service_definition_version_id,
        p_service_release_binding_id, p_consumer_ref, p_action, p_purpose,
        p_scope, p_credential_ref, p_expires_at, p_compatibility_fingerprint,
        p_compatibility_evidence, p_binding_sha256, p_created_by, p_created_at
    ) ON CONFLICT DO NOTHING
    RETURNING gda_control.service_consumer_binding.service_consumer_binding_id
        INTO v_inserted;

    SELECT binding.* INTO v_existing
      FROM gda_control.service_consumer_binding AS binding
     WHERE binding.tenant_id = p_tenant_id
       AND (
           binding.service_consumer_binding_id = p_service_consumer_binding_id
           OR binding.binding_sha256 = p_binding_sha256
           OR binding.approval_case_ref = p_approval_case_ref
       )
     ORDER BY (
         binding.service_consumer_binding_id = p_service_consumer_binding_id
     ) DESC
     LIMIT 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'service consumer binding write was not visible'
            USING ERRCODE = '40001';
    END IF;
    IF v_existing.service_consumer_binding_id IS DISTINCT FROM p_service_consumer_binding_id
       OR v_existing.approval_case_ref IS DISTINCT FROM p_approval_case_ref
       OR v_existing.grant_plan_sha256 IS DISTINCT FROM p_grant_plan_sha256
       OR v_existing.service_urn IS DISTINCT FROM p_service_urn
       OR v_existing.service_definition_version_id IS DISTINCT FROM p_service_definition_version_id
       OR v_existing.service_release_binding_id IS DISTINCT FROM p_service_release_binding_id
       OR v_existing.consumer_ref IS DISTINCT FROM p_consumer_ref
       OR v_existing.action IS DISTINCT FROM p_action
       OR v_existing.purpose IS DISTINCT FROM p_purpose
       OR v_existing.scope IS DISTINCT FROM p_scope
       OR v_existing.credential_ref IS DISTINCT FROM p_credential_ref
       OR v_existing.expires_at IS DISTINCT FROM p_expires_at
       OR v_existing.compatibility_fingerprint IS DISTINCT FROM p_compatibility_fingerprint
       OR v_existing.compatibility_evidence IS DISTINCT FROM p_compatibility_evidence
       OR v_existing.binding_sha256 IS DISTINCT FROM p_binding_sha256
       OR v_existing.created_by IS DISTINCT FROM p_created_by
       OR v_existing.created_at IS DISTINCT FROM p_created_at THEN
        RAISE EXCEPTION 'ServiceConsumerBinding identity already has a different payload'
            USING ERRCODE = '23505';
    END IF;
    RETURN QUERY SELECT v_existing.service_consumer_binding_id, (v_inserted IS NOT NULL);
END;
$$;

REVOKE ALL ON FUNCTION gda_control.record_service_consumer_binding(
    TEXT, UUID, TEXT, CHAR(64), TEXT, UUID, UUID, TEXT, TEXT, TEXT,
    JSONB, TEXT, TIMESTAMPTZ, CHAR(64), JSONB, CHAR(64), TEXT, TIMESTAMPTZ
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.record_service_consumer_binding(
    TEXT, UUID, TEXT, CHAR(64), TEXT, UUID, UUID, TEXT, TEXT, TEXT,
    JSONB, TEXT, TIMESTAMPTZ, CHAR(64), JSONB, CHAR(64), TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
