import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from data_agent import metadata_fabric_real_feature_ingestion as m322
from data_agent import metadata_fabric_retained_real_feature_terminal_success as terminal
from data_agent.dolphinscheduler_adapter import DolphinSchedulerDefinitionBinding


def _source() -> dict:
    return json.loads(terminal.DEFAULT_SOURCE_EVIDENCE_PATH.read_text(encoding="utf-8"))


def _plan() -> m322.RealFeatureIngestionPlan:
    return m322.RealFeatureIngestionPlan.model_validate(
        _source()["observation"]["plan"]
    )


def _request(retention_id: str = "m3-24-unit-retention"):
    return terminal.build_execution_request(_plan(), retention_id=retention_id)


def _definition(now: datetime):
    return terminal.build_terminal_definition(
        "http://host.docker.internal:42424/execute",
        _request(),
        created_at=now,
    )


def _binding(now: datetime):
    definition = _definition(now)
    return definition, DolphinSchedulerDefinitionBinding(
        tenant_id=terminal.TENANT,
        definition_version_id=terminal.DEFINITION_VERSION_ID,
        project_code=2401,
        workflow_definition_code=2402,
        workflow_definition_version=1,
        compiled_sha256=definition.workflow.compiled_sha256,
    )


def _retention(now: datetime):
    base = terminal.m323.build_promotion(_source())
    return terminal.build_retained_material_observation(
        tenant_id=terminal.TENANT,
        run_id=terminal.RUN_ID,
        output_resource_version_id=terminal.OUTPUT_RESOURCE_VERSION_ID,
        output_content_sha256=base.output_resource_version.content_sha256,
        storage_uri=base.output_artifact.storage_uri,
        retention_id="m3-24-unit-retention",
        owner="team:metadata-platform",
        namespace="gda-metadata-spark-object-store",
        namespace_uid="00000000-0000-4000-8000-000000000024",
        control_database_ref="docker:gda-m3-24-control-unit",
        object_inventory_sha256="1" * 64,
        metadata_body_sha256="2" * 64,
        row_set_sha256=base.output_artifact.manifest["row_set_sha256"],
        snapshot_id=base.output_artifact.manifest["snapshot_id"],
        feature_count=20,
        data_file_count=1,
        data_size_bytes=base.output_artifact.size_bytes,
        readable=True,
        source_payload_retained=False,
        materialized_at=now,
        observed_at=now + timedelta(seconds=2),
        expires_at=now + timedelta(days=7),
    )


def test_execution_request_and_definition_bind_exact_real_feature_plan():
    now = datetime(2026, 7, 31, 2, tzinfo=UTC)
    request = _request()
    definition = _definition(now)

    assert request.ingestion_plan_sha256 == _plan().ingestion_plan_sha256
    assert request.output_content_sha256 == _plan().output_content_sha256
    assert definition.definition.output_contract["retained_staging_material"] is True
    assert definition.definition.output_contract["platform_run_terminal_success"] is True
    raw_script = definition.workflow.task_definitions[0]["taskParams"]["rawScript"]
    assert "curl --fail" in raw_script
    assert request.request_sha256 in raw_script


def test_execution_request_survives_real_json_transport():
    request = _request()
    transported = json.loads(request.model_dump_json(by_alias=True))

    assert terminal.RetainedExecutionRequest.model_validate(transported) == request


def test_complete_authorization_uses_dolphinscheduler_dispatch_and_approval():
    now = datetime(2026, 7, 31, 2, tzinfo=UTC)
    definition, binding = _binding(now)
    bundle = terminal.build_terminal_authorization(
        _source(), definition, binding, authorized_at=now + timedelta(minutes=1)
    )

    assert bundle.run.policy_refs is not None
    assert bundle.run.policy_refs.policy_decision_artifact_id == (
        bundle.policy_decision.artifact_id
    )
    assert bundle.run.policy_refs.approval_artifact_id == bundle.approval.artifact_id
    assert bundle.execution_plan.artifact_role.value == "execution_plan"
    decision = bundle.policy_decision.manifest["decision"]
    assert decision["action"] == "dolphinscheduler.dispatch"
    assert decision["subject_context"]["subject_id"] == (
        terminal.RUNNER.removeprefix("workload:")
    )


def test_retained_promotion_replaces_executor_quality_evidence_provenance():
    now = datetime(2026, 7, 31, 3, tzinfo=UTC)
    retention = _retention(now)
    promotion = terminal.build_terminal_promotion(_source(), retention)

    assert promotion.output_artifact.storage_uri == retention.storage_uri
    assert promotion.output_artifact.manifest["retention_id"] == retention.retention_id
    assert promotion.quality_evidence_artifact.created_by == terminal.QUALITY_EVALUATOR
    assert promotion.quality_result.evaluated_by == terminal.QUALITY_EVALUATOR
    assert promotion.quality_evidence_artifact.created_by == (
        promotion.quality_result.evaluated_by
    )
    assert promotion.quality_result.metrics["independent_material_readback"] is True
    assert promotion.lineage_event.facets["retention_id"] == retention.retention_id


def test_retained_observation_rejects_unordered_expiry():
    now = datetime(2026, 7, 31, 3, tzinfo=UTC)
    values = _retention(now).model_dump(mode="python", by_alias=True)
    values["expires_at"] = now + timedelta(seconds=1)
    values.pop("observation_sha256")

    with pytest.raises(ValidationError, match="timestamps are not ordered"):
        terminal.build_retained_material_observation(**values)


def test_retained_promotion_rejects_different_material_identity():
    now = datetime(2026, 7, 31, 3, tzinfo=UTC)
    values = _retention(now).model_dump(mode="python", by_alias=True)
    values.pop("observation_sha256")
    values["row_set_sha256"] = "0" * 64
    retention = terminal.build_retained_material_observation(**values)

    with pytest.raises(
        terminal.RetainedTerminalSuccessError,
        match="does not bind",
    ):
        terminal.build_terminal_promotion(_source(), retention)


def test_checked_predecessor_tampering_is_rejected():
    source = deepcopy(_source())
    source["observation"]["plan"]["output_content_sha256"] = "0" * 64
    now = datetime(2026, 7, 31, 3, tzinfo=UTC)

    with pytest.raises(terminal.m323.RealFeatureLedgerPromotionError):
        terminal.build_terminal_promotion(source, _retention(now))


def test_contract_keeps_retained_staging_below_production_boundary():
    report = terminal.build_contract_report()

    assert report["status"] == "valid"
    assert report["errors"] == []
    assert report["requires_retained_material_readback"] is True
    assert report["requires_complete_authorization_artifacts"] is True
    assert report["requires_dolphinscheduler_success_observation"] is True
    assert report["requires_independent_quality_evidence_creator"] is True
    assert report["retained_staging_is_production"] is False
    assert report["production_ready"] is False
