\set ON_ERROR_STOP on
BEGIN READ ONLY;
SET LOCAL ROLE gda_control_gateway;
SELECT set_config('app.current_tenant', :'tenant_id', true) AS tenant_scope \gset

WITH evidence AS (
    SELECT run.tenant_id,
           run.run_id::text AS run_id,
           definition.capability_id,
           definition.definition_version_id::text AS definition_version_id,
           definition.definition_sha256,
           run.status AS run_status,
           run.submitted_at AS run_submitted_at,
           run.started_at AS run_started_at,
           run.terminal_at AS run_terminal_at,
           terminal.actor_subject AS terminal_actor_subject,
           terminal.to_status AS event_to_status,
           terminal.occurred_at AS terminal_event_occurred_at,
           terminal.details->>'schema' AS success_evidence_schema,
           terminal.details->>'attempt_observation_id' AS attempt_observation_id,
           terminal.details->>'output_artifact_id' AS output_artifact_id,
           terminal.details->>'quality_result_id' AS quality_result_id,
           terminal.details->>'lineage_event_id' AS lineage_event_id,
           terminal.details->>'evidence_sha256'
               AS run_success_evidence_fingerprint,
           attempt.framework_kind AS attempt_framework_kind,
           attempt.observed_state AS attempt_observed_state,
           attempt.observed_at AS attempt_observed_at,
           output.artifact_role AS output_artifact_role,
           output.content_sha256 AS output_artifact_sha256,
           output.resource_version_id::text AS output_resource_version_id,
           output.created_at AS output_created_at,
           quality.verdict AS quality_verdict,
           quality.resource_version_id::text AS quality_resource_version_id,
           quality.rule_version_ref AS quality_rule_version_ref,
           quality.metrics AS quality_metrics,
           quality.evidence_artifact_id::text
               AS quality_evidence_artifact_id,
           quality.result_sha256 AS quality_result_sha256,
           quality.evaluated_by AS quality_evaluated_by,
           quality.evaluated_at AS quality_evaluated_at,
           quality_evidence.artifact_role AS quality_evidence_artifact_role,
           lineage.target_resource_version_id::text
               AS lineage_target_resource_version_id,
           lineage.source_resource_version_id::text
               AS lineage_source_resource_version_id,
           lineage.occurred_at AS lineage_occurred_at
    FROM gda_control.platform_run AS run
    JOIN gda_control.platform_definition_version AS definition
      ON definition.tenant_id = run.tenant_id
     AND definition.definition_version_id = run.definition_version_id
    JOIN gda_control.platform_run_event AS terminal
      ON terminal.tenant_id = run.tenant_id
     AND terminal.run_id = run.run_id
     AND terminal.sequence_no = run.state_version
    JOIN gda_control.framework_attempt_observation AS attempt
      ON attempt.tenant_id = run.tenant_id
     AND attempt.run_id = run.run_id
     AND attempt.observation_id::text =
         terminal.details->>'attempt_observation_id'
    JOIN gda_control.artifact AS output
      ON output.tenant_id = run.tenant_id
     AND output.run_id = run.run_id
     AND output.artifact_id::text = terminal.details->>'output_artifact_id'
    JOIN gda_control.resource_version AS output_version
      ON output_version.tenant_id = output.tenant_id
     AND output_version.resource_version_id = output.resource_version_id
     AND output_version.content_sha256 = output.content_sha256
    JOIN gda_control.quality_result AS quality
      ON quality.tenant_id = run.tenant_id
     AND quality.run_id = run.run_id
     AND quality.quality_result_id::text =
         terminal.details->>'quality_result_id'
    JOIN gda_control.artifact AS quality_evidence
      ON quality_evidence.tenant_id = quality.tenant_id
     AND quality_evidence.artifact_id = quality.evidence_artifact_id
     AND quality_evidence.run_id = run.run_id
     AND quality_evidence.resource_version_id = quality.resource_version_id
     AND quality_evidence.created_by = quality.evaluated_by
    JOIN gda_control.lineage_event AS lineage
      ON lineage.tenant_id = run.tenant_id
     AND lineage.run_id = run.run_id
     AND lineage.lineage_event_id::text =
         terminal.details->>'lineage_event_id'
     AND lineage.definition_version_id = run.definition_version_id
     AND lineage.artifact_id = output.artifact_id
    WHERE run.tenant_id = :'tenant_id'
      AND run.run_id = CAST(:'run_id' AS uuid)
      AND definition.capability_id = :'capability_id'
      AND quality.evaluated_at >= output.created_at
      AND EXISTS (
          SELECT 1
          FROM gda_control.platform_run_input_binding AS input
          WHERE input.tenant_id = run.tenant_id
            AND input.run_id = run.run_id
            AND input.resource_version_id = lineage.source_resource_version_id
      )
)
SELECT jsonb_build_object(
    'schema', 'gda.staging_golden_ledger_export.v1',
    'rows', COALESCE(jsonb_agg(to_jsonb(evidence)), '[]'::jsonb)
)::text
FROM evidence;

ROLLBACK;
