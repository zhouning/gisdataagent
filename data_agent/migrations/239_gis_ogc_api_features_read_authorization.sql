-- 239: Add the governed OGC API Features read profile to the existing GIS
-- service policy and exact-release consumer-binding authorities.
--
-- MVT remains the default profile.  This migration does not introduce a
-- second registry: action/purpose and service type are checked together at
-- the existing recorder boundary.

ALTER TABLE gda_control.service_policy_binding
    DROP CONSTRAINT ck_gda_service_policy_profile,
    ADD CONSTRAINT ck_gda_service_policy_profile CHECK (
        enforcement_point = 'gateway'
        AND required_consumer_operation = 'read'
        AND action IN ('mvt.read', 'ogc_features.read')
    );

ALTER TABLE gda_control.service_consumer_binding
    DROP CONSTRAINT ck_gda_service_consumer_binding_profile,
    ADD CONSTRAINT ck_gda_service_consumer_binding_profile CHECK (
        scope = '{"operations":["read"]}'::jsonb
        AND (
            (action = 'mvt.read' AND purpose = 'gis_mvt_read')
            OR (action = 'ogc_features.read' AND purpose = 'ogc_features_read')
        )
    );

CREATE OR REPLACE FUNCTION gda_control.record_service_policy_binding(
    p_tenant_id TEXT,
    p_service_policy_binding_id UUID,
    p_service_definition_version_id UUID,
    p_service_release_binding_id UUID,
    p_policy_key TEXT,
    p_version_key TEXT,
    p_predecessor_version_id UUID,
    p_action TEXT,
    p_enforcement_point TEXT,
    p_allowed_roles TEXT[],
    p_consumer_binding_required_roles TEXT[],
    p_required_consumer_operation TEXT,
    p_policy_sha256 TEXT,
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
    v_existing gda_control.service_policy_binding%ROWTYPE;
    v_service_type TEXT;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'service policy tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_action NOT IN ('mvt.read', 'ogc_features.read')
       OR p_enforcement_point <> 'gateway'
       OR p_required_consumer_operation <> 'read' THEN
        RAISE EXCEPTION 'unsupported GIS service policy profile'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_existing
      FROM gda_control.service_policy_binding
     WHERE tenant_id = p_tenant_id
       AND service_policy_binding_id = p_service_policy_binding_id;
    IF FOUND THEN
        IF v_existing.service_definition_version_id = p_service_definition_version_id
           AND v_existing.service_release_binding_id = p_service_release_binding_id
           AND v_existing.policy_key = p_policy_key
           AND v_existing.version_key = p_version_key
           AND v_existing.predecessor_version_id IS NOT DISTINCT FROM p_predecessor_version_id
           AND v_existing.action = p_action
           AND v_existing.enforcement_point = p_enforcement_point
           AND v_existing.allowed_roles = p_allowed_roles
           AND v_existing.consumer_binding_required_roles = p_consumer_binding_required_roles
           AND v_existing.required_consumer_operation = p_required_consumer_operation
           AND v_existing.policy_sha256 = p_policy_sha256
           AND v_existing.created_by = p_created_by
           AND v_existing.created_at = p_created_at THEN
            RETURN p_service_policy_binding_id;
        END IF;
        RAISE EXCEPTION 'service policy identity has different immutable content'
            USING ERRCODE = '40001';
    END IF;
    SELECT definition.service_type INTO v_service_type
      FROM gda_control.gis_service_definition_version AS definition
      JOIN gda_control.service_release_binding AS release
        ON release.tenant_id = definition.tenant_id
       AND release.service_definition_version_id = definition.service_definition_version_id
       AND release.service_release_binding_id = p_service_release_binding_id
     WHERE definition.tenant_id = p_tenant_id
       AND definition.service_definition_version_id = p_service_definition_version_id;
    IF v_service_type IS NULL
       OR (p_action = 'mvt.read' AND v_service_type <> 'vector_tile')
       OR (p_action = 'ogc_features.read' AND v_service_type <> 'feature') THEN
        RAISE EXCEPTION 'service policy action does not match GIS service type'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM unnest(p_consumer_binding_required_roles) AS role(role)
        WHERE NOT role = ANY (p_allowed_roles)
    ) THEN
        RAISE EXCEPTION 'consumer-binding roles must be admitted by the service policy'
            USING ERRCODE = '23514';
    END IF;
    IF (SELECT count(*) FROM unnest(p_allowed_roles) AS role(role))
         <> (SELECT count(DISTINCT role) FROM unnest(p_allowed_roles) AS role(role))
       OR (SELECT count(*) FROM unnest(p_consumer_binding_required_roles) AS role(role))
         <> (SELECT count(DISTINCT role) FROM unnest(p_consumer_binding_required_roles) AS role(role)) THEN
        RAISE EXCEPTION 'service policy roles must not repeat' USING ERRCODE = '23514';
    END IF;
    PERFORM set_config('gda.gis_service_record_allowed', '1', true);
    INSERT INTO gda_control.service_policy_binding (
        tenant_id, service_policy_binding_id, service_definition_version_id,
        service_release_binding_id, policy_key, version_key, predecessor_version_id,
        action, enforcement_point, allowed_roles, consumer_binding_required_roles,
        required_consumer_operation, policy_sha256, created_by, created_at
    ) VALUES (
        p_tenant_id, p_service_policy_binding_id, p_service_definition_version_id,
        p_service_release_binding_id, p_policy_key, p_version_key,
        p_predecessor_version_id, p_action, p_enforcement_point, p_allowed_roles,
        p_consumer_binding_required_roles, p_required_consumer_operation,
        p_policy_sha256, p_created_by, p_created_at
    );
    RETURN p_service_policy_binding_id;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_service_consumer_binding(
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
    v_service_type TEXT;
BEGIN
    IF p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'service consumer binding tenant context is missing or mismatched' USING ERRCODE = '42501';
    END IF;
    IF NOT ((p_action = 'mvt.read' AND p_purpose = 'gis_mvt_read')
            OR (p_action = 'ogc_features.read' AND p_purpose = 'ogc_features_read'))
       OR p_scope <> '{"operations":["read"]}'::jsonb THEN
        RAISE EXCEPTION 'unsupported GIS service consumer binding profile' USING ERRCODE = '23514';
    END IF;
    v_expected_case_ref := format(
        'gda://%s/approval_case/gis-service-consumer-binding-grant-%s',
        p_tenant_id, replace(p_service_consumer_binding_id::TEXT, '-', '')
    );
    IF p_approval_case_ref IS NULL OR p_approval_case_ref <> v_expected_case_ref
       OR p_grant_plan_sha256 IS NULL OR p_grant_plan_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'service consumer binding requires its deterministic grant ApprovalCase and plan fingerprint' USING ERRCODE = '22023';
    END IF;
    SELECT approval.* INTO v_case
      FROM gda_control.approval_case AS approval
     WHERE approval.tenant_id = p_tenant_id AND approval.approval_case_ref = p_approval_case_ref
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'service consumer binding grant ApprovalCase was not found' USING ERRCODE = 'P0002';
    END IF;
    IF v_case.status <> 'approved' OR clock_timestamp() >= v_case.expires_at
       OR v_case.action <> 'gis_service_consumer_binding.grant'
       OR v_case.target_resource_urn <> p_service_urn
       OR v_case.target_fingerprint <> p_grant_plan_sha256 THEN
        RAISE EXCEPTION 'service consumer binding requires a live approved matching grant ApprovalCase' USING ERRCODE = '23514';
    END IF;
    v_plan := v_case.request_context -> 'service_consumer_binding';
    IF v_case.request_context ->> 'schema' <> 'gda.gis_service_consumer_binding_grant.v1'
       OR v_case.request_context ->> 'grant_plan_sha256' <> p_grant_plan_sha256
       OR jsonb_typeof(v_plan) <> 'object'
       OR v_plan ->> 'tenant_id' <> p_tenant_id
       OR v_plan ->> 'service_consumer_binding_id' <> p_service_consumer_binding_id::TEXT
       OR v_plan ->> 'service_urn' <> p_service_urn
       OR v_plan ->> 'service_definition_version_id' <> p_service_definition_version_id::TEXT
       OR v_plan ->> 'service_release_binding_id' <> p_service_release_binding_id::TEXT
       OR v_plan ->> 'consumer_ref' <> p_consumer_ref
       OR v_plan ->> 'action' <> p_action OR v_plan ->> 'purpose' <> p_purpose
       OR v_plan -> 'scope' IS DISTINCT FROM p_scope
       OR v_plan ->> 'credential_ref' <> p_credential_ref
       OR (v_plan ->> 'expires_at')::TIMESTAMPTZ IS DISTINCT FROM p_expires_at
       OR v_plan ->> 'compatibility_fingerprint' <> p_compatibility_fingerprint::TEXT
       OR v_plan -> 'compatibility_evidence' IS DISTINCT FROM p_compatibility_evidence
       OR v_plan ->> 'binding_sha256' <> p_binding_sha256::TEXT
       OR v_plan ->> 'created_by' <> p_created_by
       OR (v_plan ->> 'created_at')::TIMESTAMPTZ IS DISTINCT FROM p_created_at THEN
        RAISE EXCEPTION 'grant ApprovalCase does not authorize this service consumer binding payload' USING ERRCODE = '23514';
    END IF;
    SELECT definition.service_type INTO v_service_type
      FROM gda_control.gis_service_definition_version AS definition
      JOIN gda_control.service_release_binding AS release
        ON release.tenant_id = definition.tenant_id
       AND release.service_definition_version_id = definition.service_definition_version_id
       AND release.service_release_binding_id = p_service_release_binding_id
     WHERE definition.tenant_id = p_tenant_id
       AND definition.service_definition_version_id = p_service_definition_version_id
       AND definition.service_urn = p_service_urn;
    IF v_service_type IS NULL
       OR (p_action = 'mvt.read' AND v_service_type <> 'vector_tile')
       OR (p_action = 'ogc_features.read' AND v_service_type <> 'feature') THEN
        RAISE EXCEPTION 'service consumer binding action does not match GIS service type' USING ERRCODE = '23514';
    END IF;
    PERFORM set_config('gda.service_consumer_binding_allowed', '1', true);
    INSERT INTO gda_control.service_consumer_binding (
        tenant_id, service_consumer_binding_id, approval_case_ref, grant_plan_sha256,
        service_urn, service_definition_version_id, service_release_binding_id,
        consumer_ref, action, purpose, scope, credential_ref, expires_at,
        compatibility_fingerprint, compatibility_evidence, binding_sha256,
        created_by, created_at
    ) VALUES (
        p_tenant_id, p_service_consumer_binding_id, p_approval_case_ref, p_grant_plan_sha256,
        p_service_urn, p_service_definition_version_id, p_service_release_binding_id,
        p_consumer_ref, p_action, p_purpose, p_scope, p_credential_ref, p_expires_at,
        p_compatibility_fingerprint, p_compatibility_evidence, p_binding_sha256,
        p_created_by, p_created_at
    ) ON CONFLICT DO NOTHING
    RETURNING gda_control.service_consumer_binding.service_consumer_binding_id INTO v_inserted;
    SELECT binding.* INTO v_existing
      FROM gda_control.service_consumer_binding AS binding
     WHERE binding.tenant_id = p_tenant_id
       AND (binding.service_consumer_binding_id = p_service_consumer_binding_id
            OR binding.binding_sha256 = p_binding_sha256
            OR binding.approval_case_ref = p_approval_case_ref)
     ORDER BY (binding.service_consumer_binding_id = p_service_consumer_binding_id) DESC
     LIMIT 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'service consumer binding write was not visible' USING ERRCODE = '40001';
    END IF;
    IF v_existing.service_consumer_binding_id IS DISTINCT FROM p_service_consumer_binding_id
       OR v_existing.approval_case_ref IS DISTINCT FROM p_approval_case_ref
       OR v_existing.grant_plan_sha256 IS DISTINCT FROM p_grant_plan_sha256
       OR v_existing.service_urn IS DISTINCT FROM p_service_urn
       OR v_existing.service_definition_version_id IS DISTINCT FROM p_service_definition_version_id
       OR v_existing.service_release_binding_id IS DISTINCT FROM p_service_release_binding_id
       OR v_existing.consumer_ref IS DISTINCT FROM p_consumer_ref
       OR v_existing.action IS DISTINCT FROM p_action OR v_existing.purpose IS DISTINCT FROM p_purpose
       OR v_existing.scope IS DISTINCT FROM p_scope OR v_existing.credential_ref IS DISTINCT FROM p_credential_ref
       OR v_existing.expires_at IS DISTINCT FROM p_expires_at
       OR v_existing.compatibility_fingerprint IS DISTINCT FROM p_compatibility_fingerprint
       OR v_existing.compatibility_evidence IS DISTINCT FROM p_compatibility_evidence
       OR v_existing.binding_sha256 IS DISTINCT FROM p_binding_sha256
       OR v_existing.created_by IS DISTINCT FROM p_created_by OR v_existing.created_at IS DISTINCT FROM p_created_at THEN
        RAISE EXCEPTION 'ServiceConsumerBinding identity already has a different payload' USING ERRCODE = '23505';
    END IF;
    RETURN QUERY SELECT v_existing.service_consumer_binding_id, (v_inserted IS NOT NULL);
END;
$$;

COMMENT ON TABLE gda_control.service_consumer_binding IS
    'Exact-release GIS consumer grants for mvt.read and ogc_features.read; approval-bound issuance is mandatory.';

CREATE OR REPLACE FUNCTION gda_control.enforce_endpoint_release_binding()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_service_type TEXT;
BEGIN
    SELECT definition.service_type INTO v_service_type
      FROM gda_control.service_deployment_revision AS deployment
      JOIN gda_control.gis_service_definition_version AS definition
        ON definition.tenant_id = deployment.tenant_id
       AND definition.service_definition_version_id = deployment.service_definition_version_id
     WHERE deployment.tenant_id = NEW.tenant_id
       AND deployment.deployment_revision_id = NEW.deployment_revision_id
       AND definition.service_urn = NEW.service_urn;
    IF v_service_type IS NULL THEN
        RAISE EXCEPTION 'endpoint deployment does not resolve to a GIS service' USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM gda_control.service_deployment_revision AS deployment
          JOIN gda_control.service_release_binding AS release
            ON release.tenant_id = deployment.tenant_id
           AND release.service_definition_version_id = deployment.service_definition_version_id
           AND release.service_release_binding_id = deployment.service_release_binding_id
          JOIN gda_control.service_policy_binding AS policy
            ON policy.tenant_id = deployment.tenant_id
           AND policy.service_definition_version_id = deployment.service_definition_version_id
           AND policy.service_release_binding_id = deployment.service_release_binding_id
         WHERE deployment.tenant_id = NEW.tenant_id
           AND deployment.deployment_revision_id = NEW.deployment_revision_id
           AND (
               (v_service_type = 'vector_tile'
                AND release.cache_policy_version_id IS NOT NULL
                AND policy.action = 'mvt.read')
               OR (v_service_type = 'feature' AND policy.action = 'ogc_features.read')
           )
    ) THEN
        RAISE EXCEPTION 'endpoint requires a protocol-matched policy-governed GIS release' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.enforce_active_endpoint_release_binding()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_service_type TEXT;
BEGIN
    SELECT definition.service_type INTO v_service_type
      FROM gda_control.endpoint_revision AS endpoint
      JOIN gda_control.service_deployment_revision AS deployment
        ON deployment.tenant_id = endpoint.tenant_id
       AND deployment.deployment_revision_id = endpoint.deployment_revision_id
      JOIN gda_control.gis_service_definition_version AS definition
        ON definition.tenant_id = deployment.tenant_id
       AND definition.service_definition_version_id = deployment.service_definition_version_id
     WHERE endpoint.tenant_id = NEW.tenant_id
       AND endpoint.service_urn = NEW.service_urn
       AND endpoint.endpoint_revision_id = NEW.active_endpoint_revision_id;
    IF v_service_type IS NULL THEN
        RAISE EXCEPTION 'active endpoint does not resolve to a GIS service' USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM gda_control.endpoint_revision AS endpoint
          JOIN gda_control.service_deployment_revision AS deployment
            ON deployment.tenant_id = endpoint.tenant_id
           AND deployment.deployment_revision_id = endpoint.deployment_revision_id
          JOIN gda_control.service_release_binding AS release
            ON release.tenant_id = deployment.tenant_id
           AND release.service_definition_version_id = deployment.service_definition_version_id
           AND release.service_release_binding_id = deployment.service_release_binding_id
          JOIN gda_control.service_policy_binding AS policy
            ON policy.tenant_id = deployment.tenant_id
           AND policy.service_definition_version_id = deployment.service_definition_version_id
           AND policy.service_release_binding_id = deployment.service_release_binding_id
         WHERE endpoint.tenant_id = NEW.tenant_id
           AND endpoint.service_urn = NEW.service_urn
           AND endpoint.endpoint_revision_id = NEW.active_endpoint_revision_id
           AND (
               (v_service_type = 'vector_tile'
                AND release.cache_policy_version_id IS NOT NULL
                AND policy.action = 'mvt.read')
               OR (v_service_type = 'feature' AND policy.action = 'ogc_features.read')
           )
    ) THEN
        RAISE EXCEPTION 'active endpoint requires a protocol-matched policy-governed GIS release' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
