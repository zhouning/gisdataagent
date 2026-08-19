-- Immutable, tenant-scoped source-version bindings for governed NL2SQL.

CREATE TABLE IF NOT EXISTS gda_control.nl2sql_source_binding (
    tenant_id VARCHAR(64) NOT NULL,
    binding_id UUID NOT NULL,
    semantic_source_name VARCHAR(255) NOT NULL,
    execution_engine VARCHAR(16) NOT NULL,
    physical_locator TEXT NOT NULL,
    source_mode VARCHAR(32) NOT NULL,
    resource_version_id UUID NOT NULL,
    resource_urn TEXT NOT NULL,
    version_key VARCHAR(128) NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    authority_version_sha256 CHAR(64) NOT NULL,
    physical_binding_sha256 CHAR(64) NOT NULL,
    registered_by TEXT NOT NULL,
    registered_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, binding_id),
    CONSTRAINT fk_nl2sql_source_binding_resource_version
        FOREIGN KEY (tenant_id, resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT ck_nl2sql_source_binding_engine
        CHECK (execution_engine IN ('postgis', 'lake')),
    CONSTRAINT ck_nl2sql_source_binding_mode
        CHECK (source_mode IN ('immutable_snapshot', 'mutable_view')),
    CONSTRAINT ck_nl2sql_source_binding_actor
        CHECK (registered_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_nl2sql_source_binding_content_sha
        CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_nl2sql_source_binding_authority_sha
        CHECK (authority_version_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_nl2sql_source_binding_fingerprint
        CHECK (physical_binding_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS gda_control.nl2sql_source_binding_activation (
    tenant_id VARCHAR(64) NOT NULL,
    semantic_source_name VARCHAR(255) NOT NULL,
    execution_engine VARCHAR(16) NOT NULL,
    binding_id UUID NOT NULL,
    activated_by TEXT NOT NULL,
    activated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, semantic_source_name, execution_engine),
    CONSTRAINT fk_nl2sql_source_binding_activation
        FOREIGN KEY (tenant_id, binding_id)
        REFERENCES gda_control.nl2sql_source_binding(tenant_id, binding_id),
    CONSTRAINT ck_nl2sql_source_activation_engine
        CHECK (execution_engine IN ('postgis', 'lake')),
    CONSTRAINT ck_nl2sql_source_activation_actor
        CHECK (activated_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$')
);

CREATE INDEX IF NOT EXISTS idx_nl2sql_source_binding_resource_version
    ON gda_control.nl2sql_source_binding(tenant_id, resource_version_id);

ALTER TABLE gda_control.nl2sql_source_binding ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.nl2sql_source_binding FORCE ROW LEVEL SECURITY;
ALTER TABLE gda_control.nl2sql_source_binding_activation ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.nl2sql_source_binding_activation FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS nl2sql_source_binding_tenant_policy
    ON gda_control.nl2sql_source_binding;
CREATE POLICY nl2sql_source_binding_tenant_policy
    ON gda_control.nl2sql_source_binding
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant', true), '')
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant', true), '')
    );

DROP POLICY IF EXISTS nl2sql_source_binding_activation_tenant_policy
    ON gda_control.nl2sql_source_binding_activation;
CREATE POLICY nl2sql_source_binding_activation_tenant_policy
    ON gda_control.nl2sql_source_binding_activation
    USING (
        tenant_id = NULLIF(current_setting('app.current_tenant', true), '')
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.current_tenant', true), '')
    );

CREATE OR REPLACE FUNCTION gda_control.activate_nl2sql_source_binding(
    p_tenant_id VARCHAR(64),
    p_binding_id UUID,
    p_semantic_source_name VARCHAR(255),
    p_execution_engine VARCHAR(16),
    p_physical_locator TEXT,
    p_source_mode VARCHAR(32),
    p_resource_version_id UUID,
    p_resource_urn TEXT,
    p_version_key VARCHAR(128),
    p_content_sha256 CHAR(64),
    p_authority_version_sha256 CHAR(64),
    p_physical_binding_sha256 CHAR(64),
    p_registered_by TEXT,
    p_registered_at TIMESTAMPTZ,
    p_activated_by TEXT
) RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
AS $$
DECLARE
    v_existing gda_control.nl2sql_source_binding%ROWTYPE;
BEGIN
    IF p_tenant_id IS DISTINCT FROM
       NULLIF(current_setting('app.current_tenant', true), '') THEN
        RAISE EXCEPTION 'NL2SQL source binding tenant mismatch' USING ERRCODE = '42501';
    END IF;

    INSERT INTO gda_control.nl2sql_source_binding (
        tenant_id, binding_id, semantic_source_name, execution_engine,
        physical_locator, source_mode, resource_version_id, resource_urn,
        version_key, content_sha256, authority_version_sha256,
        physical_binding_sha256, registered_by, registered_at
    ) VALUES (
        p_tenant_id, p_binding_id, p_semantic_source_name, p_execution_engine,
        p_physical_locator, p_source_mode, p_resource_version_id, p_resource_urn,
        p_version_key, p_content_sha256, p_authority_version_sha256,
        p_physical_binding_sha256, p_registered_by, p_registered_at
    ) ON CONFLICT (tenant_id, binding_id) DO NOTHING;

    SELECT * INTO v_existing
      FROM gda_control.nl2sql_source_binding
     WHERE tenant_id = p_tenant_id AND binding_id = p_binding_id;
    IF v_existing IS NULL OR ROW(
        v_existing.semantic_source_name, v_existing.execution_engine,
        v_existing.physical_locator, v_existing.source_mode,
        v_existing.resource_version_id, v_existing.resource_urn,
        v_existing.version_key, v_existing.content_sha256,
        v_existing.authority_version_sha256, v_existing.physical_binding_sha256,
        v_existing.registered_by, v_existing.registered_at
    ) IS DISTINCT FROM ROW(
        p_semantic_source_name, p_execution_engine, p_physical_locator,
        p_source_mode, p_resource_version_id, p_resource_urn, p_version_key,
        p_content_sha256, p_authority_version_sha256,
        p_physical_binding_sha256, p_registered_by, p_registered_at
    ) THEN
        RAISE EXCEPTION 'NL2SQL source binding identity conflict' USING ERRCODE = '23505';
    END IF;

    INSERT INTO gda_control.nl2sql_source_binding_activation (
        tenant_id, semantic_source_name, execution_engine, binding_id,
        activated_by, activated_at
    ) VALUES (
        p_tenant_id, p_semantic_source_name, p_execution_engine, p_binding_id,
        p_activated_by, clock_timestamp()
    ) ON CONFLICT (tenant_id, semantic_source_name, execution_engine) DO UPDATE SET
        binding_id = EXCLUDED.binding_id,
        activated_by = EXCLUDED.activated_by,
        activated_at = EXCLUDED.activated_at;

    RETURN p_binding_id;
END;
$$;

REVOKE ALL ON TABLE gda_control.nl2sql_source_binding FROM PUBLIC;
REVOKE ALL ON TABLE gda_control.nl2sql_source_binding_activation FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.activate_nl2sql_source_binding(
    VARCHAR, UUID, VARCHAR, VARCHAR, TEXT, VARCHAR, UUID, TEXT, VARCHAR,
    CHAR, CHAR, CHAR, TEXT, TIMESTAMPTZ, TEXT
) FROM PUBLIC;

GRANT SELECT ON TABLE gda_control.nl2sql_source_binding TO gda_control_gateway;
GRANT SELECT ON TABLE gda_control.nl2sql_source_binding_activation TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.activate_nl2sql_source_binding(
    VARCHAR, UUID, VARCHAR, VARCHAR, TEXT, VARCHAR, UUID, TEXT, VARCHAR,
    CHAR, CHAR, CHAR, TEXT, TIMESTAMPTZ, TEXT
) TO gda_control_gateway;
