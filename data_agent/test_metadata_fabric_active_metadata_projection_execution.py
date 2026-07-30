import json
from copy import deepcopy
from datetime import UTC, datetime

from data_agent import metadata_fabric_active_metadata_projection_execution as execution
from data_agent import metadata_fabric_ingestion_replay as replay
from data_agent.dolphinscheduler_adapter import DolphinSchedulerDefinitionBinding


def _binding(definition_bundle):
    return DolphinSchedulerDefinitionBinding(
        tenant_id=execution.TENANT,
        definition_version_id=execution.DEFINITION_ID,
        project_code=190000000000001,
        workflow_definition_code=190000000000002,
        workflow_definition_version=1,
        compiled_sha256=definition_bundle.workflow.compiled_sha256,
    )


def _request_and_plan():
    at = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    profile = execution.build_projection_profile(at)
    plan = execution.build_projection_plan("f" * 64, profile)
    return profile, plan, execution.build_execution_request(plan)


def test_real_data_projection_plan_and_callback_request_are_content_bound():
    profile, plan, request = _request_and_plan()

    assert plan.tenant_id == execution.TENANT
    assert plan.resource_version_id == execution.SOURCE_ID
    assert plan.content_sha256 == "f" * 64
    assert plan.openmetadata_fqn == (
        "gda_chongqing_m3_18.cultural_heritage.published.cultural_districts"
    )
    assert plan.gravitino_identity == (
        "gda_chongqing_m3_18.iceberg.cultural_heritage.cultural_districts"
    )
    assert request.apply_plan_sha256 == plan.apply_plan_sha256
    assert request.content_sha256 == plan.content_sha256
    assert profile.authorization.action == replay.ACTION


def test_scheduler_definition_executes_exact_projection_request():
    _profile, _plan, request = _request_and_plan()
    bundle = execution.build_scheduler_definition(
        "http://host.docker.internal:43123/v1/execute-projection",
        request,
        created_at=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
    )
    script = bundle.workflow.task_definitions[0]["taskParams"]["rawScript"]

    assert bundle.definition.portability_class.value == "provider_native"
    assert "curl --fail" in script
    assert request.request_sha256 in script
    assert bundle.workflow.task_definitions[0]["name"] == ("execute_active_metadata_projection")


def test_dispatch_and_provider_apply_authorizations_are_independent():
    profile, plan, request = _request_and_plan()
    definition = execution.build_scheduler_definition(
        "http://host.docker.internal:43123/v1/execute-projection",
        request,
        created_at=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
    )
    dispatch = execution.build_dispatch_bundle(
        plan.content_sha256,
        definition,
        _binding(definition),
        authorized_at=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
    )
    apply_authorization = execution.build_provider_apply_authorization(
        plan,
        dispatch.run,
        profile,
    )
    apply_decision = replay.parse_policy_decision_artifact(
        apply_authorization.policy_decision_artifact
    )

    assert dispatch.activation_authorization.provider_mutations_executed is False
    assert apply_decision.action == replay.ACTION
    assert apply_decision.execution_plan_artifact_id != (dispatch.dispatch_plan.artifact_id)
    assert dispatch.run.status.value == "accepted"


def test_static_contract_declares_reconciling_and_local_claim_boundary():
    report = execution.build_contract_report()

    assert report["status"] == "valid"
    assert report["errors"] == []
    assert report["provider_mutation_mode"] == ("authorized_apply_then_zero_mutation_replay")
    assert report["provider_success_platform_state"] == "reconciling"
    assert report["provider_apply_authorized"] is False
    assert report["provider_mutations_executed"] is False
    assert report["production_ready"] is False


def test_checked_projection_execution_evidence_is_current_and_fail_closed():
    evidence = json.loads(execution.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))

    assert execution.validate_rehearsal_evidence(evidence) == []
    assert evidence["scheduler_provider"]["terminal_state"] == "SUCCESS"
    assert evidence["first_apply"]["status"] == "created"
    assert evidence["first_apply"]["mutation_count"] > 0
    assert evidence["replay"]["status"] == "no_op"
    assert evidence["replay"]["mutation_count"] == 0
    assert evidence["first_apply"]["openmetadata"] == (evidence["replay"]["openmetadata"])
    assert evidence["first_apply"]["gravitino"] == evidence["replay"]["gravitino"]
    assert evidence["platform_run_status"] == "reconciling"
    assert evidence["platform_run_succeeded"] is False
    assert evidence["provider_mutations_executed"] is True
    assert evidence["production_ingestion_verified"] is False
    assert evidence["production_ready"] is False


def test_projection_execution_evidence_rejects_replay_drift_and_overclaim():
    evidence = json.loads(execution.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    tampered = deepcopy(evidence)
    tampered["replay"]["mutation_count"] = 1
    tampered["platform_run_succeeded"] = True
    tampered["production_ready"] = True

    errors = execution.validate_rehearsal_evidence(tampered)

    assert "projection execution evidence SHA-256 does not match" in errors
    assert "exact scheduler-triggered replay was not mutation-free" in errors
    assert "local provider success may not claim platform success" in errors
    assert "local projection execution may not claim production_ready" in errors
