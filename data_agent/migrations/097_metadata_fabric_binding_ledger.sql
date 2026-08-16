-- 097: Immutable, tenant-scoped Metadata Fabric binding ledger.
--
-- A provider read-back is still evidence, not GDA truth. This table records
-- the verified relationship to one immutable ResourceVersion together with
-- the exact execution, policy, approval and provider evidence Artifacts.

CREATE TABLE IF NOT EXISTS gda_control.metadata_fabric_binding (
    tenant_id TEXT NOT NULL,
    binding_id UUID PRIMARY KEY,
    resource_urn TEXT NOT NULL,
    resource_version_id UUID NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    binding_document JSONB NOT NULL,
    binding_sha256 CHAR(64) NOT NULL,
    execution_plan_artifact_id UUID NOT NULL,
    policy_decision_artifact_id UUID NOT NULL,
    approval_artifact_id UUID NOT NULL,
    provider_evidence_artifact_id UUID NOT NULL,
    record_sha256 CHAR(64) NOT NULL,
    recorded_by TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_metadata_fabric_binding_tenant_id
        UNIQUE (tenant_id, binding_id),
    CONSTRAINT uq_gda_metadata_fabric_binding_target
        UNIQUE (tenant_id, resource_version_id),
    CONSTRAINT uq_gda_metadata_fabric_binding_record
        UNIQUE (tenant_id, record_sha256),
    CONSTRAINT fk_gda_metadata_fabric_binding_resource_version
        FOREIGN KEY (
            tenant_id, resource_urn, resource_version_id, content_sha256
        ) REFERENCES gda_control.resource_version(
            tenant_id, resource_urn, resource_version_id, content_sha256
        ),
    CONSTRAINT fk_gda_metadata_fabric_binding_execution_plan
        FOREIGN KEY (tenant_id, execution_plan_artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT fk_gda_metadata_fabric_binding_policy
        FOREIGN KEY (tenant_id, policy_decision_artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT fk_gda_metadata_fabric_binding_approval
        FOREIGN KEY (tenant_id, approval_artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT fk_gda_metadata_fabric_binding_provider_evidence
        FOREIGN KEY (tenant_id, provider_evidence_artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT ck_gda_metadata_fabric_binding_document
        CHECK (
            jsonb_typeof(binding_document) = 'object'
            AND binding_document->>'schema' = 'gda.metadata_fabric_binding.v1'
            AND binding_document->>'tenant_id' = tenant_id
            AND binding_document->>'resource_urn' = resource_urn
            AND binding_document->>'resource_version_id'
                = resource_version_id::text
            AND binding_document->>'content_sha256' = content_sha256
            AND binding_document->>'binding_sha256' = binding_sha256
        ),
    CONSTRAINT ck_gda_metadata_fabric_binding_sha256
        CHECK (binding_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_metadata_fabric_binding_record_sha256
        CHECK (record_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_metadata_fabric_binding_recorder
        CHECK (recorded_by ~ '^workload:.+'),
    CONSTRAINT ck_gda_metadata_fabric_binding_artifacts_distinct
        CHECK (
            execution_plan_artifact_id <> policy_decision_artifact_id
            AND execution_plan_artifact_id <> approval_artifact_id
            AND execution_plan_artifact_id <> provider_evidence_artifact_id
            AND policy_decision_artifact_id <> approval_artifact_id
            AND policy_decision_artifact_id <> provider_evidence_artifact_id
            AND approval_artifact_id <> provider_evidence_artifact_id
        )
);

CREATE INDEX IF NOT EXISTS idx_gda_metadata_fabric_binding_resource
    ON gda_control.metadata_fabric_binding(tenant_id, resource_urn);

DROP TRIGGER IF EXISTS trg_gda_immutable
    ON gda_control.metadata_fabric_binding;
CREATE TRIGGER trg_gda_immutable
BEFORE UPDATE OR DELETE ON gda_control.metadata_fabric_binding
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.metadata_fabric_binding ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.metadata_fabric_binding FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.metadata_fabric_binding;
CREATE POLICY tenant_isolation ON gda_control.metadata_fabric_binding
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.metadata_fabric_binding FROM PUBLIC;
REVOKE ALL ON TABLE gda_control.metadata_fabric_binding
    FROM gda_control_gateway;
GRANT SELECT, INSERT ON gda_control.metadata_fabric_binding
    TO gda_control_gateway;
