-- 190: tenant-scoped, append-only current authority for governed queries.
--
-- A policy version is immutable.  Replacing or revoking a policy appends a
-- record and the callback-time reader derives the current decision.  No table
-- update is used as an authorization shortcut.

CREATE TABLE IF NOT EXISTS gda_control.governed_query_purpose_registration (
    tenant_id VARCHAR(64) NOT NULL,
    purpose_code VARCHAR(128) NOT NULL,
    description TEXT NOT NULL,
    registered_by TEXT NOT NULL,
    registered_at TIMESTAMPTZ NOT NULL,
    registration_sha256 CHAR(64) NOT NULL,
    PRIMARY KEY (tenant_id, purpose_code),
    CONSTRAINT ck_gda_query_purpose_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_query_purpose_code
        CHECK (purpose_code ~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$'),
    CONSTRAINT ck_gda_query_purpose_actor
        CHECK (registered_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_query_purpose_hash
        CHECK (registration_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS gda_control.governed_query_policy_version (
    tenant_id VARCHAR(64) NOT NULL,
    policy_ref TEXT NOT NULL,
    policy_version VARCHAR(128) NOT NULL,
    purpose_code VARCHAR(128) NOT NULL,
    effect VARCHAR(8) NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    subject_types JSONB NOT NULL,
    subject_ids JSONB NOT NULL,
    required_roles JSONB NOT NULL,
    channels JSONB NOT NULL,
    adapter_ids JSONB NOT NULL,
    resource_prefixes JSONB NOT NULL,
    obligations JSONB NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    published_by TEXT NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    record_sha256 CHAR(64) NOT NULL,
    PRIMARY KEY (tenant_id, policy_ref, policy_version),
    CONSTRAINT fk_gda_query_policy_purpose
        FOREIGN KEY (tenant_id, purpose_code)
        REFERENCES gda_control.governed_query_purpose_registration
            (tenant_id, purpose_code),
    CONSTRAINT ck_gda_query_policy_effect
        CHECK (effect IN ('allow', 'deny')),
    CONSTRAINT ck_gda_query_policy_priority
        CHECK (priority BETWEEN 0 AND 10000),
    CONSTRAINT ck_gda_query_policy_window
        CHECK (expires_at > valid_from AND published_at <= expires_at),
    CONSTRAINT ck_gda_query_policy_json
        CHECK (
            jsonb_typeof(subject_types) = 'array'
            AND jsonb_typeof(subject_ids) = 'array'
            AND jsonb_typeof(required_roles) = 'array'
            AND jsonb_typeof(channels) = 'array'
            AND jsonb_typeof(adapter_ids) = 'array'
            AND jsonb_typeof(resource_prefixes) = 'array'
            AND jsonb_typeof(obligations) = 'array'
        ),
    CONSTRAINT ck_gda_query_policy_actor
        CHECK (published_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_query_policy_hashes
        CHECK (content_sha256 ~ '^[0-9a-f]{64}$' AND record_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS gda_control.governed_query_policy_revocation (
    tenant_id VARCHAR(64) NOT NULL,
    policy_ref TEXT NOT NULL,
    policy_version VARCHAR(128) NOT NULL,
    revoked_at TIMESTAMPTZ NOT NULL,
    revoked_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    revocation_sha256 CHAR(64) NOT NULL,
    PRIMARY KEY (tenant_id, policy_ref, policy_version),
    CONSTRAINT fk_gda_query_revocation_policy
        FOREIGN KEY (tenant_id, policy_ref, policy_version)
        REFERENCES gda_control.governed_query_policy_version
            (tenant_id, policy_ref, policy_version),
    CONSTRAINT ck_gda_query_revocation_actor
        CHECK (revoked_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_query_revocation_hash
        CHECK (revocation_sha256 ~ '^[0-9a-f]{64}$')
);

ALTER TABLE gda_control.governed_query_purpose_registration ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.governed_query_purpose_registration FORCE ROW LEVEL SECURITY;
ALTER TABLE gda_control.governed_query_policy_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.governed_query_policy_version FORCE ROW LEVEL SECURITY;
ALTER TABLE gda_control.governed_query_policy_revocation ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.governed_query_policy_revocation FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS governed_query_purpose_tenant ON gda_control.governed_query_purpose_registration;
CREATE POLICY governed_query_purpose_tenant
    ON gda_control.governed_query_purpose_registration
    USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), ''));
DROP POLICY IF EXISTS governed_query_policy_tenant ON gda_control.governed_query_policy_version;
CREATE POLICY governed_query_policy_tenant
    ON gda_control.governed_query_policy_version
    USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), ''));
DROP POLICY IF EXISTS governed_query_revocation_tenant ON gda_control.governed_query_policy_revocation;
CREATE POLICY governed_query_revocation_tenant
    ON gda_control.governed_query_policy_revocation
    USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), ''));

CREATE OR REPLACE FUNCTION gda_control.guard_governed_query_policy_immutable()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'governed query policy authority is append-only'
        USING ERRCODE = '55000';
END;
$$;

DROP TRIGGER IF EXISTS governed_query_purpose_immutable
    ON gda_control.governed_query_purpose_registration;
CREATE TRIGGER governed_query_purpose_immutable
    BEFORE UPDATE OR DELETE ON gda_control.governed_query_purpose_registration
    FOR EACH ROW EXECUTE FUNCTION gda_control.guard_governed_query_policy_immutable();
DROP TRIGGER IF EXISTS governed_query_policy_immutable
    ON gda_control.governed_query_policy_version;
CREATE TRIGGER governed_query_policy_immutable
    BEFORE UPDATE OR DELETE ON gda_control.governed_query_policy_version
    FOR EACH ROW EXECUTE FUNCTION gda_control.guard_governed_query_policy_immutable();
DROP TRIGGER IF EXISTS governed_query_revocation_immutable
    ON gda_control.governed_query_policy_revocation;
CREATE TRIGGER governed_query_revocation_immutable
    BEFORE UPDATE OR DELETE ON gda_control.governed_query_policy_revocation
    FOR EACH ROW EXECUTE FUNCTION gda_control.guard_governed_query_policy_immutable();

REVOKE ALL ON TABLE gda_control.governed_query_purpose_registration FROM PUBLIC;
REVOKE ALL ON TABLE gda_control.governed_query_policy_version FROM PUBLIC;
REVOKE ALL ON TABLE gda_control.governed_query_policy_revocation FROM PUBLIC;
GRANT SELECT ON gda_control.governed_query_purpose_registration TO gda_control_gateway;
GRANT SELECT ON gda_control.governed_query_policy_version TO gda_control_gateway;
GRANT SELECT ON gda_control.governed_query_policy_revocation TO gda_control_gateway;
