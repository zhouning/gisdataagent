-- 114: Append-only provider observations for architecture reconciliation.
--
-- Observations store bounded references and fingerprints, not provider schema
-- documents or credentials. Transport/query failures are never tombstones.

CREATE TABLE IF NOT EXISTS gda_control.architecture_provider_observation (
    tenant_id TEXT NOT NULL,
    observation_id UUID PRIMARY KEY,
    resource_version_id UUID NOT NULL,
    provider_system TEXT NOT NULL,
    provider_namespace TEXT NOT NULL,
    provider_object_id TEXT NOT NULL,
    object_state TEXT NOT NULL,
    source_revision TEXT,
    schema_content_sha256 CHAR(64),
    schema_version_sha256 CHAR(64),
    physical_location_sha256 CHAR(64),
    observed_at TIMESTAMPTZ NOT NULL,
    fresh_until TIMESTAMPTZ NOT NULL,
    observation_sha256 CHAR(64) NOT NULL,
    observed_by TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_gda_architecture_observation_tenant_id
        UNIQUE (tenant_id, observation_id),
    CONSTRAINT uq_gda_architecture_observation_fingerprint
        UNIQUE (tenant_id, observation_sha256),
    CONSTRAINT fk_gda_architecture_observation_resource_version
        FOREIGN KEY (tenant_id, resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT ck_gda_architecture_observation_provider CHECK (
        provider_system ~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$'
        AND length(btrim(provider_namespace)) BETWEEN 1 AND 512
        AND length(btrim(provider_object_id)) BETWEEN 1 AND 512
    ),
    CONSTRAINT ck_gda_architecture_observation_state
        CHECK (object_state IN ('present', 'tombstoned')),
    CONSTRAINT ck_gda_architecture_observation_payload CHECK (
        (
            object_state = 'present'
            AND length(btrim(source_revision)) BETWEEN 1 AND 512
            AND schema_content_sha256 ~ '^[0-9a-f]{64}$'
            AND schema_version_sha256 ~ '^[0-9a-f]{64}$'
            AND physical_location_sha256 ~ '^[0-9a-f]{64}$'
        )
        OR
        (
            object_state = 'tombstoned'
            AND source_revision IS NULL
            AND schema_content_sha256 IS NULL
            AND schema_version_sha256 IS NULL
            AND physical_location_sha256 IS NULL
        )
    ),
    CONSTRAINT ck_gda_architecture_observation_freshness CHECK (
        fresh_until >= observed_at + interval '5 seconds'
        AND fresh_until <= observed_at + interval '1 day'
        AND recorded_at >= observed_at
    ),
    CONSTRAINT ck_gda_architecture_observation_sha256
        CHECK (observation_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_architecture_observation_actor
        CHECK (length(btrim(observed_by)) BETWEEN 1 AND 512)
);

CREATE INDEX IF NOT EXISTS idx_gda_architecture_observation_latest
    ON gda_control.architecture_provider_observation(
        tenant_id, resource_version_id, observed_at DESC, observation_id DESC
    );

ALTER TABLE gda_control.architecture_provider_observation
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.architecture_provider_observation
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.architecture_provider_observation;
CREATE POLICY tenant_isolation
    ON gda_control.architecture_provider_observation
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

DROP TRIGGER IF EXISTS trg_gda_architecture_observation_immutable
    ON gda_control.architecture_provider_observation;
CREATE TRIGGER trg_gda_architecture_observation_immutable
BEFORE UPDATE OR DELETE ON gda_control.architecture_provider_observation
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

REVOKE ALL ON TABLE gda_control.architecture_provider_observation
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT, INSERT ON TABLE gda_control.architecture_provider_observation
    TO gda_control_gateway;
