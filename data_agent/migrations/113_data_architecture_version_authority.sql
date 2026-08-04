-- 113: Immutable ResourceVersion data-architecture authority bindings.
--
-- The ledger stores stable references and canonical fingerprints only. Full
-- schema and contract documents remain in Gravitino/providers/OpenMetadata.

CREATE TABLE IF NOT EXISTS gda_control.schema_version (
    tenant_id TEXT NOT NULL,
    schema_version_id UUID PRIMARY KEY,
    resource_version_id UUID NOT NULL,
    schema_format TEXT NOT NULL,
    authority_system TEXT NOT NULL,
    authority_namespace TEXT NOT NULL,
    authority_object_id TEXT NOT NULL,
    authority_version_ref TEXT NOT NULL,
    schema_sha256 CHAR(64) NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_schema_version_tenant_id
        UNIQUE (tenant_id, schema_version_id),
    CONSTRAINT uq_gda_schema_version_resource
        UNIQUE (tenant_id, resource_version_id),
    CONSTRAINT uq_gda_schema_version_resource_id
        UNIQUE (tenant_id, resource_version_id, schema_version_id),
    CONSTRAINT uq_gda_schema_version_fingerprint
        UNIQUE (tenant_id, schema_sha256),
    CONSTRAINT fk_gda_schema_version_resource_version
        FOREIGN KEY (tenant_id, resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT ck_gda_schema_version_format CHECK (
        schema_format ~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$'
    ),
    CONSTRAINT ck_gda_schema_version_authority
        CHECK (authority_system IN ('gravitino', 'provider')),
    CONSTRAINT ck_gda_schema_version_refs CHECK (
        length(btrim(authority_namespace)) BETWEEN 1 AND 512
        AND length(btrim(authority_object_id)) BETWEEN 1 AND 512
        AND length(btrim(authority_version_ref)) BETWEEN 1 AND 512
    ),
    CONSTRAINT ck_gda_schema_version_sha256
        CHECK (schema_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_schema_version_actor
        CHECK (length(btrim(created_by)) BETWEEN 1 AND 512)
);

CREATE TABLE IF NOT EXISTS gda_control.data_contract_version (
    tenant_id TEXT NOT NULL,
    data_contract_version_id UUID PRIMARY KEY,
    resource_version_id UUID NOT NULL,
    contract_kind TEXT NOT NULL,
    enforcement_mode TEXT NOT NULL,
    authority_system TEXT NOT NULL,
    authority_namespace TEXT NOT NULL,
    authority_object_id TEXT NOT NULL,
    authority_version_ref TEXT NOT NULL,
    contract_sha256 CHAR(64) NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_contract_version_tenant_id
        UNIQUE (tenant_id, data_contract_version_id),
    CONSTRAINT uq_gda_contract_version_resource
        UNIQUE (tenant_id, resource_version_id),
    CONSTRAINT uq_gda_contract_version_resource_id
        UNIQUE (tenant_id, resource_version_id, data_contract_version_id),
    CONSTRAINT uq_gda_contract_version_fingerprint
        UNIQUE (tenant_id, contract_sha256),
    CONSTRAINT fk_gda_contract_version_resource_version
        FOREIGN KEY (tenant_id, resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT ck_gda_contract_version_kind CHECK (
        contract_kind ~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$'
    ),
    CONSTRAINT ck_gda_contract_version_enforcement
        CHECK (enforcement_mode IN ('advisory', 'required')),
    CONSTRAINT ck_gda_contract_version_authority
        CHECK (authority_system IN ('openmetadata', 'provider')),
    CONSTRAINT ck_gda_contract_version_refs CHECK (
        length(btrim(authority_namespace)) BETWEEN 1 AND 512
        AND length(btrim(authority_object_id)) BETWEEN 1 AND 512
        AND length(btrim(authority_version_ref)) BETWEEN 1 AND 512
    ),
    CONSTRAINT ck_gda_contract_version_sha256
        CHECK (contract_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_contract_version_actor
        CHECK (length(btrim(created_by)) BETWEEN 1 AND 512)
);

CREATE TABLE IF NOT EXISTS gda_control.physical_location (
    tenant_id TEXT NOT NULL,
    physical_location_id UUID PRIMARY KEY,
    resource_version_id UUID NOT NULL,
    location_kind TEXT NOT NULL,
    provider_system TEXT NOT NULL,
    provider_namespace TEXT NOT NULL,
    provider_locator TEXT NOT NULL,
    snapshot_ref TEXT,
    revision_ref TEXT,
    checksum_algorithm TEXT NOT NULL,
    content_checksum TEXT NOT NULL,
    location_sha256 CHAR(64) NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_physical_location_tenant_id
        UNIQUE (tenant_id, physical_location_id),
    CONSTRAINT uq_gda_physical_location_resource
        UNIQUE (tenant_id, resource_version_id),
    CONSTRAINT uq_gda_physical_location_resource_id
        UNIQUE (tenant_id, resource_version_id, physical_location_id),
    CONSTRAINT uq_gda_physical_location_fingerprint
        UNIQUE (tenant_id, location_sha256),
    CONSTRAINT fk_gda_physical_location_resource_version
        FOREIGN KEY (tenant_id, resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT ck_gda_physical_location_kind CHECK (
        location_kind ~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$'
    ),
    CONSTRAINT ck_gda_physical_location_provider CHECK (
        provider_system ~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$'
        AND length(btrim(provider_namespace)) BETWEEN 1 AND 512
        AND length(btrim(provider_locator)) BETWEEN 1 AND 2048
    ),
    CONSTRAINT ck_gda_physical_location_revision CHECK (
        snapshot_ref IS NOT NULL OR revision_ref IS NOT NULL
    ),
    CONSTRAINT ck_gda_physical_location_optional_refs CHECK (
        (snapshot_ref IS NULL OR length(btrim(snapshot_ref)) BETWEEN 1 AND 512)
        AND (revision_ref IS NULL OR length(btrim(revision_ref)) BETWEEN 1 AND 512)
    ),
    CONSTRAINT ck_gda_physical_location_checksum CHECK (
        checksum_algorithm ~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$'
        AND length(btrim(content_checksum)) BETWEEN 1 AND 512
    ),
    CONSTRAINT ck_gda_physical_location_sha256
        CHECK (location_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_physical_location_actor
        CHECK (length(btrim(created_by)) BETWEEN 1 AND 512)
);

CREATE TABLE IF NOT EXISTS gda_control.resource_version_architecture_binding (
    tenant_id TEXT NOT NULL,
    resource_version_id UUID NOT NULL,
    schema_version_id UUID NOT NULL,
    data_contract_version_id UUID NOT NULL,
    physical_location_id UUID NOT NULL,
    binding_sha256 CHAR(64) NOT NULL,
    bound_by TEXT NOT NULL,
    bound_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, resource_version_id),
    CONSTRAINT uq_gda_architecture_binding_fingerprint
        UNIQUE (tenant_id, binding_sha256),
    CONSTRAINT fk_gda_architecture_binding_resource_version
        FOREIGN KEY (tenant_id, resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT fk_gda_architecture_binding_schema FOREIGN KEY (
        tenant_id, resource_version_id, schema_version_id
    ) REFERENCES gda_control.schema_version(
        tenant_id, resource_version_id, schema_version_id
    ),
    CONSTRAINT fk_gda_architecture_binding_contract FOREIGN KEY (
        tenant_id, resource_version_id, data_contract_version_id
    ) REFERENCES gda_control.data_contract_version(
        tenant_id, resource_version_id, data_contract_version_id
    ),
    CONSTRAINT fk_gda_architecture_binding_location FOREIGN KEY (
        tenant_id, resource_version_id, physical_location_id
    ) REFERENCES gda_control.physical_location(
        tenant_id, resource_version_id, physical_location_id
    ),
    CONSTRAINT ck_gda_architecture_binding_sha256
        CHECK (binding_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_architecture_binding_actor
        CHECK (length(btrim(bound_by)) BETWEEN 1 AND 512)
);

DO $$
DECLARE
    relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'schema_version',
        'data_contract_version',
        'physical_location',
        'resource_version_architecture_binding'
    ]
    LOOP
        EXECUTE format(
            'ALTER TABLE gda_control.%I ENABLE ROW LEVEL SECURITY',
            relation_name
        );
        EXECUTE format(
            'ALTER TABLE gda_control.%I FORCE ROW LEVEL SECURITY',
            relation_name
        );
        EXECUTE format(
            'DROP POLICY IF EXISTS tenant_isolation ON gda_control.%I',
            relation_name
        );
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON gda_control.%I '
            'USING (tenant_id = gda_control.current_tenant()) '
            'WITH CHECK (tenant_id = gda_control.current_tenant())',
            relation_name
        );
        EXECUTE format(
            'DROP TRIGGER IF EXISTS trg_gda_architecture_immutable '
            'ON gda_control.%I',
            relation_name
        );
        EXECUTE format(
            'CREATE TRIGGER trg_gda_architecture_immutable '
            'BEFORE UPDATE OR DELETE ON gda_control.%I '
            'FOR EACH ROW EXECUTE FUNCTION '
            'gda_control.reject_immutable_mutation()',
            relation_name
        );
    END LOOP;
END;
$$;

REVOKE ALL ON TABLE
    gda_control.schema_version,
    gda_control.data_contract_version,
    gda_control.physical_location,
    gda_control.resource_version_architecture_binding
FROM PUBLIC, gda_control_gateway;

GRANT SELECT, INSERT ON TABLE
    gda_control.schema_version,
    gda_control.data_contract_version,
    gda_control.physical_location,
    gda_control.resource_version_architecture_binding
TO gda_control_gateway;
