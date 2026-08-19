-- 191: harden governed-query policy values and add controlled write ports.

ALTER TABLE gda_control.governed_query_policy_version
    DROP CONSTRAINT ck_gda_query_policy_json;
ALTER TABLE gda_control.governed_query_policy_version
    ADD CONSTRAINT ck_gda_query_policy_json
    CHECK (
        jsonb_typeof(subject_types) = 'array'
        AND jsonb_array_length(subject_types) BETWEEN 1 AND 3
        AND jsonb_typeof(subject_ids) = 'array'
        AND jsonb_array_length(subject_ids) <= 100
        AND jsonb_typeof(required_roles) = 'array'
        AND jsonb_array_length(required_roles) <= 32
        AND jsonb_typeof(channels) = 'array'
        AND jsonb_array_length(channels) BETWEEN 1 AND 16
        AND jsonb_typeof(adapter_ids) = 'array'
        AND jsonb_array_length(adapter_ids) BETWEEN 1 AND 32
        AND jsonb_typeof(resource_prefixes) = 'array'
        AND jsonb_array_length(resource_prefixes) <= 100
        AND jsonb_typeof(obligations) = 'array'
        AND jsonb_array_length(obligations) <= 32
        AND subject_types <@ '["human", "workload", "agent"]'::JSONB
        AND (effect = 'allow' OR jsonb_array_length(obligations) = 0)
    ) NOT VALID;
ALTER TABLE gda_control.governed_query_policy_version
    VALIDATE CONSTRAINT ck_gda_query_policy_json;

CREATE OR REPLACE FUNCTION gda_control.register_governed_query_purpose(
    p_tenant_id VARCHAR(64),
    p_purpose_code VARCHAR(128),
    p_description TEXT,
    p_registered_by TEXT,
    p_registered_at TIMESTAMPTZ,
    p_registration_sha256 TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_existing gda_control.governed_query_purpose_registration%ROWTYPE;
BEGIN
    IF p_tenant_id IS DISTINCT FROM
       NULLIF(current_setting('app.current_tenant', true), '') THEN
        RAISE EXCEPTION 'governed query purpose tenant mismatch'
            USING ERRCODE = '42501';
    END IF;

    INSERT INTO gda_control.governed_query_purpose_registration (
        tenant_id, purpose_code, description, registered_by, registered_at,
        registration_sha256
    ) VALUES (
        p_tenant_id, p_purpose_code, p_description, p_registered_by,
        p_registered_at, p_registration_sha256
    ) ON CONFLICT (tenant_id, purpose_code) DO NOTHING;

    SELECT * INTO v_existing
    FROM gda_control.governed_query_purpose_registration
    WHERE tenant_id = p_tenant_id AND purpose_code = p_purpose_code;
    IF v_existing.tenant_id IS NULL OR ROW(
        v_existing.description, v_existing.registered_by,
        v_existing.registered_at, v_existing.registration_sha256
    ) IS DISTINCT FROM ROW(
        p_description, p_registered_by, p_registered_at,
        p_registration_sha256::CHAR(64)
    ) THEN
        RAISE EXCEPTION 'governed query purpose immutable identity conflict'
            USING ERRCODE = '23505';
    END IF;
    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.register_governed_query_policy_version(
    p_tenant_id VARCHAR(64),
    p_policy_ref TEXT,
    p_policy_version VARCHAR(128),
    p_purpose_code VARCHAR(128),
    p_effect VARCHAR(8),
    p_priority INTEGER,
    p_subject_types JSONB,
    p_subject_ids JSONB,
    p_required_roles JSONB,
    p_channels JSONB,
    p_adapter_ids JSONB,
    p_resource_prefixes JSONB,
    p_obligations JSONB,
    p_valid_from TIMESTAMPTZ,
    p_expires_at TIMESTAMPTZ,
    p_published_at TIMESTAMPTZ,
    p_published_by TEXT,
    p_content_sha256 TEXT,
    p_record_sha256 TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_existing gda_control.governed_query_policy_version%ROWTYPE;
BEGIN
    IF p_tenant_id IS DISTINCT FROM
       NULLIF(current_setting('app.current_tenant', true), '') THEN
        RAISE EXCEPTION 'governed query policy tenant mismatch'
            USING ERRCODE = '42501';
    END IF;

    INSERT INTO gda_control.governed_query_policy_version (
        tenant_id, policy_ref, policy_version, purpose_code, effect, priority,
        subject_types, subject_ids, required_roles, channels, adapter_ids,
        resource_prefixes, obligations, valid_from, expires_at, published_at,
        published_by, content_sha256, record_sha256
    ) VALUES (
        p_tenant_id, p_policy_ref, p_policy_version, p_purpose_code, p_effect,
        p_priority, p_subject_types, p_subject_ids, p_required_roles, p_channels,
        p_adapter_ids, p_resource_prefixes, p_obligations, p_valid_from,
        p_expires_at, p_published_at, p_published_by, p_content_sha256,
        p_record_sha256
    ) ON CONFLICT (tenant_id, policy_ref, policy_version) DO NOTHING;

    SELECT * INTO v_existing
    FROM gda_control.governed_query_policy_version
    WHERE tenant_id = p_tenant_id
      AND policy_ref = p_policy_ref
      AND policy_version = p_policy_version;
    IF v_existing.tenant_id IS NULL OR ROW(
        v_existing.purpose_code, v_existing.effect, v_existing.priority,
        v_existing.subject_types, v_existing.subject_ids,
        v_existing.required_roles, v_existing.channels, v_existing.adapter_ids,
        v_existing.resource_prefixes, v_existing.obligations,
        v_existing.valid_from, v_existing.expires_at, v_existing.published_at,
        v_existing.published_by, v_existing.content_sha256,
        v_existing.record_sha256
    ) IS DISTINCT FROM ROW(
        p_purpose_code, p_effect, p_priority, p_subject_types, p_subject_ids,
        p_required_roles, p_channels, p_adapter_ids, p_resource_prefixes,
        p_obligations, p_valid_from, p_expires_at, p_published_at,
        p_published_by, p_content_sha256::CHAR(64), p_record_sha256::CHAR(64)
    ) THEN
        RAISE EXCEPTION 'governed query policy immutable identity conflict'
            USING ERRCODE = '23505';
    END IF;
    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.revoke_governed_query_policy(
    p_tenant_id VARCHAR(64),
    p_policy_ref TEXT,
    p_policy_version VARCHAR(128),
    p_revoked_at TIMESTAMPTZ,
    p_revoked_by TEXT,
    p_reason TEXT,
    p_revocation_sha256 TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_policy gda_control.governed_query_policy_version%ROWTYPE;
    v_existing gda_control.governed_query_policy_revocation%ROWTYPE;
BEGIN
    IF p_tenant_id IS DISTINCT FROM
       NULLIF(current_setting('app.current_tenant', true), '') THEN
        RAISE EXCEPTION 'governed query policy revocation tenant mismatch'
            USING ERRCODE = '42501';
    END IF;

    SELECT * INTO v_policy
    FROM gda_control.governed_query_policy_version
    WHERE tenant_id = p_tenant_id
      AND policy_ref = p_policy_ref
      AND policy_version = p_policy_version;
    IF v_policy.tenant_id IS NULL OR p_revoked_at < v_policy.published_at THEN
        RAISE EXCEPTION 'governed query policy revocation is invalid'
            USING ERRCODE = '22023';
    END IF;

    INSERT INTO gda_control.governed_query_policy_revocation (
        tenant_id, policy_ref, policy_version, revoked_at, revoked_by, reason,
        revocation_sha256
    ) VALUES (
        p_tenant_id, p_policy_ref, p_policy_version, p_revoked_at, p_revoked_by,
        p_reason, p_revocation_sha256
    ) ON CONFLICT (tenant_id, policy_ref, policy_version) DO NOTHING;

    SELECT * INTO v_existing
    FROM gda_control.governed_query_policy_revocation
    WHERE tenant_id = p_tenant_id
      AND policy_ref = p_policy_ref
      AND policy_version = p_policy_version;
    IF v_existing.tenant_id IS NULL OR ROW(
        v_existing.revoked_at, v_existing.revoked_by, v_existing.reason,
        v_existing.revocation_sha256
    ) IS DISTINCT FROM ROW(
        p_revoked_at, p_revoked_by, p_reason, p_revocation_sha256::CHAR(64)
    ) THEN
        RAISE EXCEPTION 'governed query policy revocation immutable conflict'
            USING ERRCODE = '23505';
    END IF;
    RETURN TRUE;
END;
$$;

REVOKE ALL ON FUNCTION gda_control.register_governed_query_purpose(
    VARCHAR, VARCHAR, TEXT, TEXT, TIMESTAMPTZ, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.register_governed_query_policy_version(
    VARCHAR, TEXT, VARCHAR, VARCHAR, VARCHAR, INTEGER, JSONB, JSONB, JSONB,
    JSONB, JSONB, JSONB, JSONB, TIMESTAMPTZ, TIMESTAMPTZ, TIMESTAMPTZ,
    TEXT, TEXT, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.revoke_governed_query_policy(
    VARCHAR, TEXT, VARCHAR, TIMESTAMPTZ, TEXT, TEXT, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.register_governed_query_purpose(
    VARCHAR, VARCHAR, TEXT, TEXT, TIMESTAMPTZ, TEXT
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.register_governed_query_policy_version(
    VARCHAR, TEXT, VARCHAR, VARCHAR, VARCHAR, INTEGER, JSONB, JSONB, JSONB,
    JSONB, JSONB, JSONB, JSONB, TIMESTAMPTZ, TIMESTAMPTZ, TIMESTAMPTZ,
    TEXT, TEXT, TEXT
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.revoke_governed_query_policy(
    VARCHAR, TEXT, VARCHAR, TIMESTAMPTZ, TEXT, TEXT, TEXT
) TO gda_control_gateway;
