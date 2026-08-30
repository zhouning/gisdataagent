-- Approval-bound JQDLTB layered candidate publication authority.

CREATE TABLE gda_control.jqdltb_data_product_release (
    tenant_id VARCHAR(64) NOT NULL,
    data_product_version_id UUID NOT NULL,
    product_urn TEXT NOT NULL,
    run_id UUID NOT NULL,
    source_resource_version_id UUID NOT NULL,
    output_resource_version_id UUID NOT NULL,
    output_artifact_id UUID NOT NULL,
    quality_result_id UUID NOT NULL,
    quality_evidence_artifact_id UUID NOT NULL,
    lineage_event_id UUID NOT NULL,
    transformation_approval_case_ref TEXT NOT NULL,
    release_approval_case_ref TEXT NOT NULL,
    release_plan_sha256 CHAR(64) NOT NULL,
    operating_contract JSONB NOT NULL,
    bound_by TEXT NOT NULL,
    bound_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, data_product_version_id),
    CONSTRAINT fk_jqdltb_release_product_version
        FOREIGN KEY (tenant_id, data_product_version_id)
        REFERENCES gda_control.data_product_version(
            tenant_id, data_product_version_id
        ) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_jqdltb_release_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.platform_run(tenant_id, run_id),
    CONSTRAINT fk_jqdltb_release_source
        FOREIGN KEY (tenant_id, source_resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT fk_jqdltb_release_output
        FOREIGN KEY (tenant_id, output_resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT fk_jqdltb_release_output_artifact
        FOREIGN KEY (tenant_id, output_artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT fk_jqdltb_release_quality_result
        FOREIGN KEY (tenant_id, quality_result_id)
        REFERENCES gda_control.quality_result(tenant_id, quality_result_id),
    CONSTRAINT fk_jqdltb_release_quality_artifact
        FOREIGN KEY (tenant_id, quality_evidence_artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT fk_jqdltb_release_lineage
        FOREIGN KEY (tenant_id, lineage_event_id)
        REFERENCES gda_control.lineage_event(tenant_id, lineage_event_id),
    CONSTRAINT fk_jqdltb_release_transformation_approval
        FOREIGN KEY (tenant_id, transformation_approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT fk_jqdltb_release_approval
        FOREIGN KEY (tenant_id, release_approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT chk_jqdltb_release_plan_sha256
        CHECK (release_plan_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_jqdltb_release_operating_contract
        CHECK (
            operating_contract->>'tenant_id' = tenant_id
            AND operating_contract->>'business_steward_ref' <> ''
            AND operating_contract->>'license_id' <> ''
            AND operating_contract->>'data_slo_ref' <> ''
            AND operating_contract->>'service_slo_ref' <> ''
            AND operating_contract->>'on_call_ref' <> ''
            AND operating_contract->>'environment_owner_ref' <> ''
            AND operating_contract->>'deployment_profile_ref' <> ''
            AND operating_contract->>'backup_restore_evidence_artifact_id' <> ''
            AND lower(operating_contract::text) !~
                '(pending|unknown|unassigned|tbd|todo)'
        )
);

CREATE OR REPLACE FUNCTION gda_control.require_jqdltb_data_product_release()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_release gda_control.jqdltb_data_product_release%ROWTYPE;
    v_run gda_control.platform_run%ROWTYPE;
    v_run_source UUID;
    v_output gda_control.artifact%ROWTYPE;
    v_quality gda_control.quality_result%ROWTYPE;
    v_quality_evidence gda_control.artifact%ROWTYPE;
    v_backup_evidence gda_control.artifact%ROWTYPE;
    v_lineage gda_control.lineage_event%ROWTYPE;
    v_transform_case gda_control.approval_case%ROWTYPE;
    v_release_case gda_control.approval_case%ROWTYPE;
    v_product gda_control.data_product%ROWTYPE;
BEGIN
    IF NEW.mapping_contract->>'schema' IS DISTINCT FROM
            'gda.jqdltb_mapping_binding.v1' THEN
        RETURN NEW;
    END IF;

    SELECT * INTO v_release
      FROM gda_control.jqdltb_data_product_release
     WHERE tenant_id = NEW.tenant_id
       AND data_product_version_id = NEW.data_product_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'JQDLTB DataProductVersion requires an approved release binding'
            USING ERRCODE = '23514';
    END IF;
    IF v_release.product_urn IS DISTINCT FROM NEW.product_urn
       OR v_release.source_resource_version_id IS DISTINCT FROM
            NEW.source_resource_version_id
       OR v_release.output_resource_version_id IS DISTINCT FROM
            NEW.output_resource_version_id
       OR v_release.quality_evidence_artifact_id IS DISTINCT FROM
            NEW.quality_evidence_artifact_id
       OR v_release.transformation_approval_case_ref IS DISTINCT FROM
            NEW.mapping_contract->>'transformation_approval_case_ref'
       OR v_release.release_approval_case_ref IS DISTINCT FROM
            NEW.distribution_manifest->>'release_approval_case_ref'
       OR v_release.bound_by IS DISTINCT FROM NEW.published_by
       OR v_release.bound_at IS DISTINCT FROM NEW.published_at THEN
        RAISE EXCEPTION 'JQDLTB release binding differs from DataProductVersion'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_run
      FROM gda_control.platform_run
     WHERE tenant_id = NEW.tenant_id AND run_id = v_release.run_id;
    SELECT resource_version_id INTO v_run_source
      FROM gda_control.platform_run_input_binding
     WHERE tenant_id = NEW.tenant_id
       AND run_id = v_release.run_id
       AND binding_name = 'source';
    SELECT * INTO v_output FROM gda_control.artifact
     WHERE tenant_id = NEW.tenant_id
       AND artifact_id = v_release.output_artifact_id;
    SELECT * INTO v_quality FROM gda_control.quality_result
     WHERE tenant_id = NEW.tenant_id
       AND quality_result_id = v_release.quality_result_id;
    SELECT * INTO v_quality_evidence FROM gda_control.artifact
     WHERE tenant_id = NEW.tenant_id
       AND artifact_id = v_release.quality_evidence_artifact_id;
    SELECT * INTO v_backup_evidence FROM gda_control.artifact
     WHERE tenant_id = NEW.tenant_id
       AND artifact_id = (
            v_release.operating_contract
                ->>'backup_restore_evidence_artifact_id'
       )::uuid;
    SELECT * INTO v_lineage FROM gda_control.lineage_event
     WHERE tenant_id = NEW.tenant_id
       AND lineage_event_id = v_release.lineage_event_id;
    SELECT * INTO v_transform_case FROM gda_control.approval_case
     WHERE tenant_id = NEW.tenant_id
       AND approval_case_ref = v_release.transformation_approval_case_ref;
    SELECT * INTO v_release_case FROM gda_control.approval_case
     WHERE tenant_id = NEW.tenant_id
       AND approval_case_ref = v_release.release_approval_case_ref;
    SELECT * INTO v_product FROM gda_control.data_product
     WHERE tenant_id = NEW.tenant_id AND product_urn = NEW.product_urn;

    IF v_run.status IS DISTINCT FROM 'succeeded'
       OR v_run_source IS DISTINCT FROM NEW.source_resource_version_id
       OR v_output.artifact_role IS DISTINCT FROM 'output'
       OR v_output.run_id IS DISTINCT FROM v_release.run_id
       OR v_output.resource_version_id IS DISTINCT FROM NEW.output_resource_version_id
       OR v_output.content_sha256 IS DISTINCT FROM
            NEW.distribution_manifest->>'layer_manifest_sha256'
       OR v_output.manifest->>'bundle_sha256' IS DISTINCT FROM
            v_output.content_sha256
       OR v_output.manifest->'layers' IS DISTINCT FROM
            NEW.distribution_manifest->'layers'
       OR v_quality.verdict IS DISTINCT FROM 'passed'
       OR v_quality.run_id IS DISTINCT FROM v_release.run_id
       OR v_quality.resource_version_id IS DISTINCT FROM NEW.output_resource_version_id
       OR v_quality.evidence_artifact_id IS DISTINCT FROM
            NEW.quality_evidence_artifact_id
       OR v_quality.quality_result_id::text IS DISTINCT FROM
            NEW.quality_contract->>'quality_result_id'
       OR v_quality.result_sha256 IS DISTINCT FROM
            NEW.quality_contract->>'quality_result_sha256'
       OR v_quality_evidence.artifact_role IS DISTINCT FROM 'evidence'
       OR v_quality_evidence.run_id IS DISTINCT FROM v_release.run_id
       OR v_quality_evidence.resource_version_id IS DISTINCT FROM
            NEW.output_resource_version_id
       OR v_backup_evidence.artifact_role IS DISTINCT FROM 'evidence'
       OR v_lineage.run_id IS DISTINCT FROM v_release.run_id
       OR v_lineage.source_resource_version_id IS DISTINCT FROM
            NEW.source_resource_version_id
       OR v_lineage.target_resource_version_id IS DISTINCT FROM
            NEW.output_resource_version_id
       OR v_lineage.artifact_id IS DISTINCT FROM v_release.output_artifact_id THEN
        RAISE EXCEPTION 'JQDLTB release evidence graph is incomplete or inconsistent'
            USING ERRCODE = '23514';
    END IF;

    IF v_transform_case.status IS DISTINCT FROM 'approved'
       OR v_transform_case.action IS DISTINCT FROM 'jqdltb.transform'
       OR v_transform_case.target_fingerprint IS DISTINCT FROM
            NEW.mapping_contract->>'transformation_plan_sha256'
       OR v_release_case.status IS DISTINCT FROM 'approved'
       OR v_release_case.action IS DISTINCT FROM 'data_product.publish_jqdltb'
       OR v_release_case.target_resource_urn IS DISTINCT FROM NEW.product_urn
       OR v_release_case.target_fingerprint IS DISTINCT FROM
            v_release.release_plan_sha256
       OR v_release_case.request_context->>'schema' IS DISTINCT FROM
            'gda.jqdltb_data_product_release.v1'
       OR v_release_case.request_context->>'plan_sha256' IS DISTINCT FROM
            v_release.release_plan_sha256
       OR v_release_case.request_context->>'product_urn' IS DISTINCT FROM
            NEW.product_urn
       OR v_release_case.request_context->>'data_product_version_id'
            IS DISTINCT FROM NEW.data_product_version_id::text
       OR v_release_case.request_context->>'version_key'
            IS DISTINCT FROM NEW.version_key
       OR v_release_case.request_context->>'manifest_sha256'
            IS DISTINCT FROM NEW.manifest_sha256
       OR v_release_case.request_context->>'run_id'
            IS DISTINCT FROM v_release.run_id::text
       OR v_release_case.request_context->>'source_resource_version_id'
            IS DISTINCT FROM NEW.source_resource_version_id::text
       OR v_release_case.request_context->>'output_resource_version_id'
            IS DISTINCT FROM NEW.output_resource_version_id::text
       OR v_release_case.request_context
            ->>'transformation_approval_case_ref' IS DISTINCT FROM
            v_release.transformation_approval_case_ref
       OR v_release_case.request_context->>'quality_result_id'
            IS DISTINCT FROM v_release.quality_result_id::text
       OR v_release_case.request_context->>'lineage_event_id'
            IS DISTINCT FROM v_release.lineage_event_id::text
       OR v_release_case.request_context->'operating_contract'
            IS DISTINCT FROM v_release.operating_contract
       OR NEW.distribution_manifest->>'transformation_output_artifact_id'
            IS DISTINCT FROM v_release.output_artifact_id::text
       OR NEW.distribution_manifest->>'lineage_event_id'
            IS DISTINCT FROM v_release.lineage_event_id::text
       OR NEW.distribution_manifest->'operating_contract'
            IS DISTINCT FROM v_release.operating_contract
       OR v_release_case.decided_at IS NULL
       OR v_release_case.decided_at > NEW.published_at
       OR NEW.published_at >= v_release_case.expires_at THEN
        RAISE EXCEPTION 'JQDLTB release ApprovalCase is not an approved plan binding'
            USING ERRCODE = '23514';
    END IF;

    IF v_product.owner_ref IS DISTINCT FROM
            v_release.operating_contract->>'business_steward_ref'
       OR v_product.governance_ref->>'license_id' IS DISTINCT FROM
            v_release.operating_contract->>'license_id' THEN
        RAISE EXCEPTION 'JQDLTB product owner or license differs from release authority'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE CONSTRAINT TRIGGER trg_gda_jqdltb_product_release_required
AFTER INSERT OR UPDATE ON gda_control.data_product_version
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION gda_control.require_jqdltb_data_product_release();

CREATE OR REPLACE FUNCTION gda_control.reject_jqdltb_release_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'JQDLTB product release bindings are immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER trg_gda_jqdltb_release_immutable
BEFORE UPDATE OR DELETE ON gda_control.jqdltb_data_product_release
FOR EACH ROW
EXECUTE FUNCTION gda_control.reject_jqdltb_release_mutation();

ALTER TABLE gda_control.jqdltb_data_product_release ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.jqdltb_data_product_release FORCE ROW LEVEL SECURITY;
CREATE POLICY gda_jqdltb_release_tenant_policy
ON gda_control.jqdltb_data_product_release
USING (tenant_id = current_setting('app.current_tenant', true))
WITH CHECK (tenant_id = current_setting('app.current_tenant', true));

REVOKE ALL ON TABLE gda_control.jqdltb_data_product_release FROM PUBLIC;
REVOKE ALL ON TABLE gda_control.jqdltb_data_product_release FROM agent_user;
GRANT SELECT, INSERT ON TABLE gda_control.jqdltb_data_product_release
    TO gda_control_gateway;
REVOKE UPDATE, DELETE ON TABLE gda_control.jqdltb_data_product_release
    FROM gda_control_gateway;
