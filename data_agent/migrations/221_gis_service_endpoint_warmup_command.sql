-- 221: Managed provider-origin warmup command and evidence-gated Run success.
--
-- The shared PlatformCommand outbox delivers the work. Martin remains a
-- read-only provider, and migration 220 remains the release-bound receipt
-- authority. This migration only adds the dedicated Run success gate needed
-- to settle both authorities in one Gateway transaction.

ALTER TABLE gda_control.platform_command_outbox
    DROP CONSTRAINT IF EXISTS ck_gda_command_type;
ALTER TABLE gda_control.platform_command_outbox
    ADD CONSTRAINT ck_gda_command_type CHECK (
        command_type IN (
            'dolphinscheduler.dispatch',
            'dolphinscheduler.reconcile',
            'dolphinscheduler.cancel',
            'metric_query.execute',
            'gis_analysis.execute',
            'gis_analysis.cancel',
            'gis_analysis.reconcile',
            'blueprint_provider.execute',
            'blueprint_provider.retry',
            'gis_service.endpoint_warmup'
        )
    );

CREATE OR REPLACE FUNCTION
gda_control.finalize_gis_service_endpoint_warmup_success(
    p_tenant_id TEXT,
    p_run_id UUID,
    p_expected_state_version INTEGER,
    p_actor_subject TEXT,
    p_reason TEXT,
    p_details JSONB
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_run gda_control.platform_run%ROWTYPE;
    v_event gda_control.platform_run_event%ROWTYPE;
    v_definition gda_control.platform_definition_version%ROWTYPE;
    v_observation gda_control.framework_attempt_observation%ROWTYPE;
    v_plan gda_control.artifact%ROWTYPE;
    v_evidence gda_control.artifact%ROWTYPE;
    v_quality gda_control.quality_result%ROWTYPE;
    v_lineage gda_control.lineage_event%ROWTYPE;
    v_observation_id UUID;
    v_evidence_artifact_id UUID;
    v_quality_result_id UUID;
    v_lineage_event_id UUID;
    v_plan_artifact_id UUID;
    v_source_resource_version_id UUID;
    v_expected_evidence_sha256 TEXT;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'platform run tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_actor_subject IS DISTINCT FROM
       'workload:gis-warmup-controller'
       OR NULLIF(btrim(p_reason), '') IS NULL THEN
        RAISE EXCEPTION 'GIS warmup finalization requires its workload authority'
            USING ERRCODE = '42501';
    END IF;
    IF jsonb_typeof(p_details) <> 'object'
       OR p_details->>'schema' <> 'gda.run_success_evidence.v1'
       OR p_details->>'tenant_id' IS DISTINCT FROM p_tenant_id
       OR p_details->>'run_id' IS DISTINCT FROM p_run_id::text
       OR COALESCE(p_details->>'evidence_sha256', '')
            !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'GIS warmup success evidence envelope is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_run
      FROM gda_control.platform_run
     WHERE tenant_id = p_tenant_id AND run_id = p_run_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'platform run % not found', p_run_id
            USING ERRCODE = 'P0002';
    END IF;
    IF v_run.status = 'succeeded' THEN
        SELECT * INTO v_event
          FROM gda_control.platform_run_event
         WHERE tenant_id = p_tenant_id
           AND run_id = p_run_id
           AND sequence_no = v_run.state_version;
        IF FOUND
           AND v_event.to_status = 'succeeded'
           AND v_event.actor_subject = p_actor_subject
           AND v_event.reason = p_reason
           AND v_event.details = p_details THEN
            RETURN v_run.state_version;
        END IF;
        RAISE EXCEPTION 'successful GIS warmup Run has a different verdict'
            USING ERRCODE = '40001';
    END IF;
    IF v_run.state_version <> p_expected_state_version THEN
        RAISE EXCEPTION 'platform run state version conflict: expected %, actual %',
            p_expected_state_version, v_run.state_version
            USING ERRCODE = '40001';
    END IF;
    IF v_run.status NOT IN ('running', 'reconciling') THEN
        RAISE EXCEPTION 'GIS warmup success requires running or reconciling Run'
            USING ERRCODE = '23514';
    END IF;
    IF v_run.subject_context->>'subject_type' <> 'workload'
       OR concat(
           v_run.subject_context->>'subject_type', ':',
           v_run.subject_context->>'subject_id'
       ) IS DISTINCT FROM p_actor_subject
       OR v_run.subject_context->>'purpose' IS DISTINCT FROM
           'gis_service.endpoint_warmup' THEN
        RAISE EXCEPTION 'GIS warmup Run workload or purpose is invalid'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_definition
      FROM gda_control.platform_definition_version
     WHERE tenant_id = p_tenant_id
       AND definition_version_id = v_run.definition_version_id;
    IF NOT FOUND OR v_definition.capability_id IS DISTINCT FROM
       'gis-service-endpoint-warmup' THEN
        RAISE EXCEPTION 'Run definition is not the GIS endpoint warmup capability'
            USING ERRCODE = '23514';
    END IF;

    BEGIN
        v_observation_id := (p_details->>'attempt_observation_id')::uuid;
        v_evidence_artifact_id := (p_details->>'output_artifact_id')::uuid;
        v_quality_result_id := (p_details->>'quality_result_id')::uuid;
        v_lineage_event_id := (p_details->>'lineage_event_id')::uuid;
    EXCEPTION WHEN invalid_text_representation OR null_value_not_allowed THEN
        RAISE EXCEPTION 'GIS warmup success identifiers must be UUIDs'
            USING ERRCODE = '22023';
    END;
    v_expected_evidence_sha256 := encode(
        sha256(convert_to(
            '{"attempt_observation_id":'
            || to_json(v_observation_id::text)::text
            || ',"lineage_event_id":'
            || to_json(v_lineage_event_id::text)::text
            || ',"output_artifact_id":'
            || to_json(v_evidence_artifact_id::text)::text
            || ',"quality_result_id":'
            || to_json(v_quality_result_id::text)::text
            || ',"run_id":' || to_json(p_run_id::text)::text
            || ',"tenant_id":' || to_json(p_tenant_id)::text || '}',
            'UTF8'
        )), 'hex'
    );
    IF p_details->>'evidence_sha256' IS DISTINCT FROM
       v_expected_evidence_sha256 THEN
        RAISE EXCEPTION 'GIS warmup success fingerprint does not match bindings'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_observation
      FROM gda_control.framework_attempt_observation
     WHERE tenant_id = p_tenant_id
       AND observation_id = v_observation_id
       AND run_id = p_run_id
       AND framework_kind = 'cloud'
       AND external_namespace = 'martin'
       AND lower(observed_state) = 'success';
    IF NOT FOUND
       OR v_observation.evidence->>'schema' IS DISTINCT FROM
           'gda.gis_service_martin_endpoint_warmup.v1'
       OR v_observation.evidence->>'tenant_id' IS DISTINCT FROM p_tenant_id
       OR v_observation.evidence->>'run_id' IS DISTINCT FROM p_run_id::text
       OR v_observation.evidence->>'provider_system' IS DISTINCT FROM 'martin'
       OR COALESCE(v_observation.evidence->>'receipt_sha256', '')
            !~ '^[0-9a-f]{64}$'
       OR COALESCE(v_observation.evidence->>'execution_plan_sha256', '')
            !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'release-bound Martin warmup observation was not found'
            USING ERRCODE = '23514';
    END IF;
    BEGIN
        v_plan_artifact_id := (
            v_observation.evidence->>'execution_plan_artifact_id'
        )::uuid;
        v_source_resource_version_id := (
            v_observation.evidence->>'source_output_resource_version_id'
        )::uuid;
    EXCEPTION WHEN invalid_text_representation OR null_value_not_allowed THEN
        RAISE EXCEPTION 'Martin observation plan bindings are invalid'
            USING ERRCODE = '22023';
    END;

    SELECT * INTO v_plan
      FROM gda_control.artifact
     WHERE tenant_id = p_tenant_id
       AND artifact_id = v_plan_artifact_id
       AND run_id = p_run_id
       AND artifact_role = 'execution_plan';
    IF NOT FOUND
       OR v_plan.manifest->>'plan_sha256' IS DISTINCT FROM
           v_observation.evidence->>'execution_plan_sha256'
       OR v_plan.manifest->>'schema' IS DISTINCT FROM
           'gda.gis_service_endpoint_warmup_execution_plan.v1'
       OR v_plan.manifest->>'run_id' IS DISTINCT FROM p_run_id::text
       OR v_plan.manifest->>'definition_version_id' IS DISTINCT FROM
           v_run.definition_version_id::text
       OR v_plan.manifest->>'definition_sha256' IS DISTINCT FROM
           v_definition.definition_sha256
       OR v_plan.manifest->>'provider_system' IS DISTINCT FROM 'martin'
       OR v_plan.manifest->>'provider_layer_ref' IS DISTINCT FROM
           'gda_mvt_serving_projection'
       OR v_plan.manifest->>'source_output_resource_version_id' IS DISTINCT FROM
           v_source_resource_version_id::text
       OR v_plan.manifest->>'sample_set_sha256' IS DISTINCT FROM
           v_observation.evidence->>'sample_set_sha256'
       OR v_plan.manifest->>'endpoint_revision_id' IS DISTINCT FROM
           v_observation.evidence->>'endpoint_revision_id'
       OR v_plan.manifest->>'deployment_revision_id' IS DISTINCT FROM
           v_observation.evidence->>'deployment_revision_id'
       OR v_plan.manifest->>'service_release_binding_id' IS DISTINCT FROM
           v_observation.evidence->>'service_release_binding_id'
       OR v_plan.manifest->>'cache_policy_version_id' IS DISTINCT FROM
           v_observation.evidence->>'cache_policy_version_id'
       OR jsonb_typeof(v_plan.manifest->'samples') <> 'array'
       OR jsonb_array_length(v_plan.manifest->'samples') < 1
       OR jsonb_array_length(v_plan.manifest->'samples') > 100 THEN
        RAISE EXCEPTION 'GIS warmup execution plan is missing or inconsistent'
            USING ERRCODE = '23514';
    END IF;
    PERFORM 1
      FROM gda_control.platform_run_input_binding
     WHERE tenant_id = p_tenant_id
       AND run_id = p_run_id
       AND binding_name = 'source_product_output'
       AND resource_version_id = v_source_resource_version_id
       AND semantic_type = 'gda.gis_service.warmup_source';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS warmup plan source is not a Run input'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_evidence
      FROM gda_control.artifact
     WHERE tenant_id = p_tenant_id
       AND artifact_id = v_evidence_artifact_id
       AND run_id = p_run_id
       AND resource_version_id = v_source_resource_version_id
       AND artifact_role = 'evidence';
    IF NOT FOUND
       OR v_evidence.content_sha256 IS DISTINCT FROM
           v_observation.evidence->>'receipt_sha256'
       OR v_evidence.created_by IS DISTINCT FROM p_actor_subject
       OR v_evidence.manifest->>'schema' IS DISTINCT FROM
           'gda.gis_service_endpoint_warmup_receipt.v1'
       OR v_evidence.manifest->>'endpoint_revision_id' IS DISTINCT FROM
           v_plan.manifest->>'endpoint_revision_id'
       OR v_evidence.manifest->>'deployment_revision_id' IS DISTINCT FROM
           v_plan.manifest->>'deployment_revision_id'
       OR v_evidence.manifest->>'service_definition_version_id' IS DISTINCT FROM
           v_plan.manifest->>'service_definition_version_id'
       OR v_evidence.manifest->>'service_release_binding_id' IS DISTINCT FROM
           v_plan.manifest->>'service_release_binding_id'
       OR v_evidence.manifest->>'cache_policy_version_id' IS DISTINCT FROM
           v_plan.manifest->>'cache_policy_version_id'
       OR v_evidence.manifest->>'cache_namespace' IS DISTINCT FROM
           v_plan.manifest->>'cache_namespace'
       OR v_evidence.manifest->>'sample_set_sha256' IS DISTINCT FROM
           v_plan.manifest->>'sample_set_sha256'
       OR v_evidence.manifest->>'provider_receipt_sha256' IS DISTINCT FROM
           v_observation.evidence->>'receipt_sha256' THEN
        RAISE EXCEPTION 'GIS warmup evidence Artifact is missing or forged'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_quality
      FROM gda_control.quality_result
     WHERE tenant_id = p_tenant_id
       AND quality_result_id = v_quality_result_id
       AND run_id = p_run_id
       AND resource_version_id = v_source_resource_version_id
       AND evidence_artifact_id = v_evidence_artifact_id
       AND verdict = 'passed'
       AND rule_version_ref = 'gda:gis-service-endpoint-warmup/v1'
       AND evaluated_by = p_actor_subject;
    IF NOT FOUND
       OR v_quality.metrics->>'schema' IS DISTINCT FROM
           'gda.gis_service_endpoint_warmup_quality.v1'
       OR v_quality.metrics->>'requested_sample_count' IS DISTINCT FROM
           v_evidence.manifest->>'requested_sample_count'
       OR v_quality.metrics->>'successful_sample_count' IS DISTINCT FROM
           v_evidence.manifest->>'successful_sample_count'
       OR v_quality.metrics->>'sample_set_sha256' IS DISTINCT FROM
           v_evidence.manifest->>'sample_set_sha256'
       OR v_quality.metrics->>'provider_receipt_sha256' IS DISTINCT FROM
           v_evidence.content_sha256 THEN
        RAISE EXCEPTION 'passed GIS warmup QualityResult was not found'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_lineage
      FROM gda_control.lineage_event
     WHERE tenant_id = p_tenant_id
       AND lineage_event_id = v_lineage_event_id
       AND run_id = p_run_id
       AND definition_version_id = v_run.definition_version_id
       AND artifact_id = v_evidence_artifact_id
       AND source_resource_version_id = v_source_resource_version_id
       AND target_resource_version_id = v_run.definition_version_id
       AND producer = p_actor_subject;
    IF NOT FOUND
       OR v_lineage.facets->>'schema' IS DISTINCT FROM
           'gda.gis_service_endpoint_warmup_lineage.v1'
       OR v_lineage.facets->>'execution_plan_sha256' IS DISTINCT FROM
           v_plan.manifest->>'plan_sha256'
       OR v_lineage.facets->>'provider_receipt_sha256' IS DISTINCT FROM
           v_evidence.content_sha256 THEN
        RAISE EXCEPTION 'GIS warmup source-to-definition LineageEvent was not found'
            USING ERRCODE = '23514';
    END IF;

    RETURN gda_control.apply_platform_run_transition(
        p_tenant_id, p_run_id, p_expected_state_version,
        'succeeded', p_actor_subject, p_reason, p_details
    );
END;
$$;

CREATE OR REPLACE FUNCTION
gda_control.fail_gis_service_endpoint_warmup_command_terminal(
    p_tenant_id TEXT,
    p_command_id UUID,
    p_worker_id TEXT,
    p_error TEXT
)
RETURNS SETOF gda_control.platform_command_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_command gda_control.platform_command_outbox%ROWTYPE;
    v_run gda_control.platform_run%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    IF NULLIF(btrim(p_worker_id), '') IS NULL
       OR NULLIF(btrim(p_error), '') IS NULL THEN
        RAISE EXCEPTION 'worker identity and terminal error are required'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_command
      FROM gda_control.platform_command_outbox
     WHERE tenant_id = p_tenant_id
       AND command_id = p_command_id
     FOR UPDATE;
    IF NOT FOUND
       OR v_command.command_type <> 'gis_service.endpoint_warmup'
       OR v_command.actor_subject <> 'workload:gis-warmup-controller'
       OR v_command.status <> 'in_flight'
       OR v_command.claimed_by IS DISTINCT FROM p_worker_id
       OR v_command.claimed_until <= clock_timestamp() THEN
        RAISE EXCEPTION 'live GIS warmup command claim is missing or mismatched'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO v_run
      FROM gda_control.platform_run
     WHERE tenant_id = p_tenant_id
       AND run_id = v_command.run_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS warmup PlatformRun was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_run.status NOT IN ('succeeded', 'failed', 'cancelled', 'timed_out') THEN
        PERFORM gda_control.apply_platform_run_transition(
            p_tenant_id, v_run.run_id, v_run.state_version,
            'failed', v_command.actor_subject,
            'GIS endpoint warmup contract rejected',
            jsonb_build_object(
                'schema', 'gda.gis_service_endpoint_warmup_failure.v1',
                'command_id', p_command_id::text,
                'error', left(p_error, 2000)
            )
        );
    ELSIF v_run.status = 'succeeded' THEN
        RAISE EXCEPTION 'successful GIS warmup Run cannot be failed'
            USING ERRCODE = '40001';
    END IF;
    RETURN QUERY
    UPDATE gda_control.platform_command_outbox AS command
       SET status = 'failed',
           claimed_by = NULL,
           claimed_until = NULL,
           last_error = left(p_error, 2000),
           completed_at = clock_timestamp()
     WHERE command.tenant_id = p_tenant_id
       AND command.command_id = p_command_id
    RETURNING command.*;
END;
$$;

REVOKE ALL ON FUNCTION
gda_control.finalize_gis_service_endpoint_warmup_success(
    TEXT, UUID, INTEGER, TEXT, TEXT, JSONB
) FROM PUBLIC, gda_control_gateway;
GRANT EXECUTE ON FUNCTION
gda_control.finalize_gis_service_endpoint_warmup_success(
    TEXT, UUID, INTEGER, TEXT, TEXT, JSONB
) TO gda_control_gateway;

REVOKE ALL ON FUNCTION
gda_control.fail_gis_service_endpoint_warmup_command_terminal(
    TEXT, UUID, TEXT, TEXT
) FROM PUBLIC, gda_control_gateway;
GRANT EXECUTE ON FUNCTION
gda_control.fail_gis_service_endpoint_warmup_command_terminal(
    TEXT, UUID, TEXT, TEXT
) TO gda_control_gateway;
