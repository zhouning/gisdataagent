import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

from data_agent import metadata_fabric_active_metadata_scheduler_delivery as delivery
from data_agent.dolphinscheduler_adapter import (
    DolphinSchedulerDefinitionBinding,
    compile_dolphinscheduler_workflow,
    parse_dolphinscheduler_binding_artifact,
)


def _binding(definition_bundle):
    return DolphinSchedulerDefinitionBinding(
        tenant_id=delivery.TENANT,
        definition_version_id=delivery.DEFINITION_ID,
        project_code=180000000000001,
        workflow_definition_code=180000000000002,
        workflow_definition_version=1,
        compiled_sha256=definition_bundle.workflow.compiled_sha256,
    )


def test_provider_native_delivery_bundle_binds_real_resource_and_exact_workflow():
    created_at = datetime(2026, 7, 30, 9, 0, tzinfo=UTC)
    definition_bundle = delivery.build_scheduler_definition(created_at)
    content_sha256 = "f" * 64
    bundle = delivery.build_scheduler_delivery_bundle(
        content_sha256,
        definition_bundle,
        _binding(definition_bundle),
        authorized_at=created_at + timedelta(minutes=1),
    )

    assert definition_bundle.definition.portability_class.value == "provider_native"
    assert compile_dolphinscheduler_workflow(definition_bundle.definition) == (
        definition_bundle.workflow
    )
    assert bundle.source_version.content_sha256 == content_sha256
    assert bundle.authorization.content_sha256 == content_sha256
    assert bundle.authorization.execution_plan_artifact_id == (
        bundle.execution_plan.artifact_id
    )
    assert parse_dolphinscheduler_binding_artifact(bundle.execution_plan) == (
        _binding(definition_bundle)
    )
    assert bundle.run.subject_context.subject_id == "metadata-projection-runner"
    assert bundle.authorization.provider_mutations_executed is False


def test_static_contract_requires_consumer_submission_readback_and_reconciling():
    report = delivery.build_contract_report()

    assert report["status"] == "valid"
    assert report["errors"] == []
    assert report["provider_success_platform_state"] == "reconciling"
    assert report["governed_mutation_mode"] == "no_side_effect"
    assert report["production_scheduler_submission_verified"] is False
    assert report["provider_mutations_executed"] is False
    assert report["production_ready"] is False
    assert all(not item["path"].startswith("/") for item in report["files"].values())


def test_checked_scheduler_delivery_evidence_is_current_and_fail_closed():
    evidence = json.loads(delivery.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))

    assert delivery.validate_rehearsal_evidence(evidence) == []
    assert evidence["provider"]["server_version"] == "3.4.2"
    assert evidence["provider"]["terminal_state"] == "SUCCESS"
    assert evidence["matching_provider_instance_count"] == 1
    assert evidence["attempt_states"] == ["submitted", "success"]
    assert evidence["platform_run_status"] == "reconciling"
    assert evidence["platform_run_succeeded"] is False
    assert evidence["provider_mutations_executed"] is False
    assert evidence["production_scheduler_submission_verified"] is False
    assert evidence["production_ready"] is False
    serialized = json.dumps(evidence)
    assert "/Users/" not in serialized
    assert "Downloads/" not in serialized
    assert '"token"' not in serialized
    assert '"password"' not in serialized
    assert '"session"' not in serialized


def test_scheduler_delivery_evidence_rejects_tampering_and_overclaim():
    evidence = json.loads(delivery.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    tampered = deepcopy(evidence)
    tampered["matching_provider_instance_count"] = 2
    tampered["platform_run_succeeded"] = True
    tampered["production_ready"] = True

    errors = delivery.validate_rehearsal_evidence(tampered)

    assert "scheduler delivery evidence SHA-256 does not match" in errors
    assert "scheduler delivery must read back one correlated instance" in errors
    assert "local provider success may not claim platform success" in errors
    assert "local scheduler delivery may not claim production_ready" in errors
