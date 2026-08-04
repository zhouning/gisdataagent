-- 116: Approval-bound DataProduct release of an adopted architecture successor.
--
-- The release binding is append-only. A deferred constraint prevents a
-- DataProductVersion from pointing at an adopted successor unless the same
-- transaction also records the independently approved release plan.

-- The architecture table already owns this identity, but the three-column
-- foreign key below also binds the exact fingerprint approved for release.
ALTER TABLE gda_control.resource_version_architecture_binding
    ADD CONSTRAINT uq_gda_architecture_binding_resource_sha
    UNIQUE (tenant_id, resource_version_id, binding_sha256);

CREATE TABLE gda_control.data_product_architecture_release (
    tenant_id TEXT NOT NULL,
    data_product_version_id UUID NOT NULL,
    product_urn TEXT NOT NULL,
    predecessor_data_product_version_id UUID NOT NULL,
    predecessor_output_resource_version_id UUID NOT NULL,
    successor_output_resource_version_id UUID NOT NULL,
    architecture_adoption_case_ref TEXT NOT NULL,
    architecture_successor_plan_sha256 CHAR(64) NOT NULL,
    release_approval_case_ref TEXT NOT NULL,
    release_plan_sha256 CHAR(64) NOT NULL,
    architecture_binding_sha256 CHAR(64) NOT NULL,
    quality_evidence_artifact_id UUID NOT NULL,
    distribution_artifact_ids JSONB NOT NULL,
    rollback_target_version_id UUID NOT NULL,
    bound_by TEXT NOT NULL,
    bound_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, data_product_version_id),
    CONSTRAINT uq_gda_product_arch_release_plan
        UNIQUE (tenant_id, release_plan_sha256),
    CONSTRAINT uq_gda_product_arch_release_approval
        UNIQUE (tenant_id, release_approval_case_ref),
    CONSTRAINT fk_gda_product_arch_release_version
        FOREIGN KEY (tenant_id, product_urn, data_product_version_id)
        REFERENCES gda_control.data_product_version(
            tenant_id, product_urn, data_product_version_id
        ),
    CONSTRAINT fk_gda_product_arch_release_predecessor
        FOREIGN KEY (
            tenant_id, product_urn, predecessor_data_product_version_id
        ) REFERENCES gda_control.data_product_version(
            tenant_id, product_urn, data_product_version_id
        ),
    CONSTRAINT fk_gda_product_arch_release_predecessor_output
        FOREIGN KEY (tenant_id, predecessor_output_resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT fk_gda_product_arch_release_successor_output
        FOREIGN KEY (tenant_id, successor_output_resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT fk_gda_product_arch_release_adoption_case
        FOREIGN KEY (tenant_id, architecture_adoption_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT fk_gda_product_arch_release_release_case
        FOREIGN KEY (tenant_id, release_approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT fk_gda_product_arch_release_architecture_binding
        FOREIGN KEY (
            tenant_id, successor_output_resource_version_id,
            architecture_binding_sha256
        ) REFERENCES gda_control.resource_version_architecture_binding(
            tenant_id, resource_version_id, binding_sha256
        ),
    CONSTRAINT fk_gda_product_arch_release_quality_artifact
        FOREIGN KEY (tenant_id, quality_evidence_artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT ck_gda_product_arch_release_sha256 CHECK (
        architecture_successor_plan_sha256 ~ '^[0-9a-f]{64}$'
        AND release_plan_sha256 ~ '^[0-9a-f]{64}$'
        AND architecture_binding_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_product_arch_release_artifacts CHECK (
        jsonb_typeof(distribution_artifact_ids) = 'array'
        AND jsonb_array_length(distribution_artifact_ids) > 0
    ),
    CONSTRAINT ck_gda_product_arch_release_rollback CHECK (
        rollback_target_version_id = predecessor_data_product_version_id
        AND data_product_version_id <> predecessor_data_product_version_id
    ),
    CONSTRAINT ck_gda_product_arch_release_actor CHECK (
        NULLIF(btrim(bound_by), '') IS NOT NULL
    )
);

CREATE OR REPLACE FUNCTION gda_control.guard_data_product_architecture_release()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_version gda_control.data_product_version%ROWTYPE;
    v_predecessor gda_control.data_product_version%ROWTYPE;
    v_output gda_control.resource_version%ROWTYPE;
    v_adoption gda_control.approval_case%ROWTYPE;
    v_release gda_control.approval_case%ROWTYPE;
    v_quality gda_control.artifact%ROWTYPE;
    v_distribution_count INTEGER;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'DataProduct architecture release tenant is mismatched'
            USING ERRCODE = '42501';
    END IF;

    SELECT * INTO v_version
      FROM gda_control.data_product_version
     WHERE tenant_id = NEW.tenant_id
       AND product_urn = NEW.product_urn
       AND data_product_version_id = NEW.data_product_version_id;
    SELECT * INTO v_predecessor
      FROM gda_control.data_product_version
     WHERE tenant_id = NEW.tenant_id
       AND product_urn = NEW.product_urn
       AND data_product_version_id = NEW.predecessor_data_product_version_id;
    IF v_version.data_product_version_id IS NULL
       OR v_predecessor.data_product_version_id IS NULL
       OR v_version.predecessor_version_id IS DISTINCT FROM
            NEW.predecessor_data_product_version_id
       OR v_version.output_resource_version_id IS DISTINCT FROM
            NEW.successor_output_resource_version_id
       OR v_predecessor.output_resource_version_id IS DISTINCT FROM
            NEW.predecessor_output_resource_version_id
       OR v_version.quality_evidence_artifact_id IS DISTINCT FROM
            NEW.quality_evidence_artifact_id
       OR v_version.published_by IS DISTINCT FROM NEW.bound_by
       OR v_version.published_at IS DISTINCT FROM NEW.bound_at THEN
        RAISE EXCEPTION 'DataProduct release does not match its immutable version chain'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_output
      FROM gda_control.resource_version
     WHERE tenant_id = NEW.tenant_id
       AND resource_version_id = NEW.successor_output_resource_version_id;
    IF v_output.predecessor_version_id IS DISTINCT FROM
            NEW.predecessor_output_resource_version_id THEN
        RAISE EXCEPTION 'DataProduct output does not follow the architecture successor chain'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM gda_control.lineage_event
         WHERE tenant_id = NEW.tenant_id
           AND source_resource_version_id =
                NEW.predecessor_output_resource_version_id
           AND target_resource_version_id =
                NEW.successor_output_resource_version_id
           AND facets->>'operation' = 'create_successor_version'
           AND facets->>'architecture_successor_plan_sha256' =
                NEW.architecture_successor_plan_sha256
    ) THEN
        RAISE EXCEPTION 'DataProduct release lacks adopted successor lineage'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_adoption
      FROM gda_control.approval_case
     WHERE tenant_id = NEW.tenant_id
       AND approval_case_ref = NEW.architecture_adoption_case_ref;
    IF v_adoption.status IS DISTINCT FROM 'approved'
       OR v_adoption.action IS DISTINCT FROM
            'data_architecture.create_successor_version'
       OR v_adoption.target_fingerprint IS DISTINCT FROM
            NEW.architecture_successor_plan_sha256
       OR v_adoption.request_context->>'successor_resource_version_id'
            IS DISTINCT FROM NEW.successor_output_resource_version_id::text
       OR v_adoption.request_context->>'predecessor_resource_version_id'
            IS DISTINCT FROM NEW.predecessor_output_resource_version_id::text
       OR v_adoption.request_context->>'successor_binding_sha256'
            IS DISTINCT FROM NEW.architecture_binding_sha256 THEN
        RAISE EXCEPTION 'DataProduct release lacks approved architecture adoption evidence'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_release
      FROM gda_control.approval_case
     WHERE tenant_id = NEW.tenant_id
       AND approval_case_ref = NEW.release_approval_case_ref;
    IF v_release.status IS DISTINCT FROM 'approved'
       OR v_release.action IS DISTINCT FROM
            'data_product.publish_architecture_successor'
       OR v_release.target_resource_urn IS DISTINCT FROM NEW.product_urn
       OR v_release.target_fingerprint IS DISTINCT FROM NEW.release_plan_sha256
       OR v_release.request_context->>'schema' IS DISTINCT FROM
            'gda.architecture_successor_data_product_release.v1'
       OR v_release.request_context->>'plan_sha256'
            IS DISTINCT FROM NEW.release_plan_sha256
       OR v_release.request_context->>'data_product_version_id'
            IS DISTINCT FROM NEW.data_product_version_id::text
       OR v_release.request_context->>'predecessor_data_product_version_id'
            IS DISTINCT FROM NEW.predecessor_data_product_version_id::text
       OR v_release.request_context->>'architecture_adoption_case_ref'
            IS DISTINCT FROM NEW.architecture_adoption_case_ref
       OR v_release.request_context->>'architecture_successor_plan_sha256'
            IS DISTINCT FROM NEW.architecture_successor_plan_sha256
       OR v_release.request_context->>'architecture_binding_sha256'
            IS DISTINCT FROM NEW.architecture_binding_sha256
       OR v_release.request_context->>'data_product_manifest_sha256'
            IS DISTINCT FROM v_version.manifest_sha256
       OR v_release.request_context->>'quality_evidence_artifact_id'
            IS DISTINCT FROM NEW.quality_evidence_artifact_id::text
       OR v_release.request_context->'distribution_artifact_ids'
            IS DISTINCT FROM NEW.distribution_artifact_ids
       OR v_release.request_context->>'rollback_target_version_id'
            IS DISTINCT FROM NEW.rollback_target_version_id::text
       OR v_release.decided_at IS NULL
       OR v_release.decided_at > NEW.bound_at THEN
        RAISE EXCEPTION 'DataProduct release ApprovalCase does not bind this plan'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_quality
      FROM gda_control.artifact
     WHERE tenant_id = NEW.tenant_id
       AND artifact_id = NEW.quality_evidence_artifact_id;
    IF v_quality.artifact_role IS DISTINCT FROM 'evidence'
       OR v_quality.resource_version_id IS DISTINCT FROM
            NEW.successor_output_resource_version_id THEN
        RAISE EXCEPTION 'quality evidence is not bound to the successor output'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT value
          FROM jsonb_array_elements_text(NEW.distribution_artifact_ids) AS value
         GROUP BY value HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'distribution Artifact identities must be unique'
            USING ERRCODE = '23514';
    END IF;
    SELECT count(*) INTO v_distribution_count
      FROM gda_control.artifact artifact
     WHERE artifact.tenant_id = NEW.tenant_id
       AND artifact.artifact_id IN (
            SELECT value::uuid
              FROM jsonb_array_elements_text(NEW.distribution_artifact_ids)
       )
       AND artifact.artifact_role = 'output'
       AND artifact.resource_version_id =
            NEW.successor_output_resource_version_id;
    IF v_distribution_count <> jsonb_array_length(NEW.distribution_artifact_ids) THEN
        RAISE EXCEPTION 'distribution Artifacts are not bound to the successor output'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_gda_product_architecture_release_guard
BEFORE INSERT ON gda_control.data_product_architecture_release
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_data_product_architecture_release();

CREATE OR REPLACE FUNCTION gda_control.require_architecture_successor_release()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM gda_control.lineage_event
         WHERE tenant_id = NEW.tenant_id
           AND target_resource_version_id = NEW.output_resource_version_id
           AND facets->>'operation' = 'create_successor_version'
    ) AND NOT EXISTS (
        SELECT 1 FROM gda_control.data_product_architecture_release
         WHERE tenant_id = NEW.tenant_id
           AND data_product_version_id = NEW.data_product_version_id
    ) THEN
        RAISE EXCEPTION 'adopted architecture successor requires approved DataProduct release'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER trg_gda_product_architecture_release_required
AFTER INSERT ON gda_control.data_product_version
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION gda_control.require_architecture_successor_release();

CREATE TRIGGER trg_gda_product_architecture_release_immutable
BEFORE UPDATE OR DELETE ON gda_control.data_product_architecture_release
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.data_product_architecture_release ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.data_product_architecture_release FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation
    ON gda_control.data_product_architecture_release
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON gda_control.data_product_architecture_release
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT, INSERT ON gda_control.data_product_architecture_release
    TO gda_control_gateway;
