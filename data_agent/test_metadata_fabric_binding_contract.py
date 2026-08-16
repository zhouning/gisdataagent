import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.metadata_fabric_binding_contract import (
    MetadataFabricBindingContractError,
    MetadataFabricBindingRecord,
    MetadataFabricProviderEvidence,
    build_metadata_fabric_binding_record,
    parse_metadata_fabric_execution_plan_artifact,
    parse_metadata_fabric_provider_evidence_artifact,
)
from data_agent.metadata_fabric_binding_ledger import (
    DEFAULT_EVIDENCE_PATH,
    build_binding_ledger_bundle,
    build_contract_report,
    validate_rehearsal_evidence,
)


def test_m3_2_live_provider_identity_builds_deterministic_binding_record():
    first = build_binding_ledger_bundle()
    second = build_binding_ledger_bundle()

    assert first == second
    assert str(first.record.binding.openmetadata.entity_id) == (
        "522fb32f-8613-4ff5-96cd-0306da155d00"
    )
    assert first.record.binding.binding_sha256 == (
        "125d7197f05ff9c37999a94d090d123dcf905480b776da0738d9625ab5045598"
    )
    assert first.record.binding.openmetadata.entity_id != UUID(
        "10000000-0000-4000-8000-000000000001"
    )
    assert first.record.record_sha256 == (
        "19bdbddedc27d2ed8a35119e8f065a47a02345f9bbd3a51075856cb9587f4176"
    )


def test_execution_and_provider_evidence_artifacts_are_content_bound():
    bundle = build_binding_ledger_bundle()
    execution, _policy, _approval, provider = bundle.artifacts

    plan = parse_metadata_fabric_execution_plan_artifact(execution)
    evidence = parse_metadata_fabric_provider_evidence_artifact(provider)

    assert plan.resource_version_id == bundle.record.binding.resource_version_id
    assert evidence.binding == bundle.record.binding
    with pytest.raises(
        MetadataFabricBindingContractError,
        match="not content-bound",
    ):
        parse_metadata_fabric_execution_plan_artifact(
            execution.model_copy(update={"content_sha256": "0" * 64})
        )
    with pytest.raises(
        MetadataFabricBindingContractError,
        match="metadata does not match",
    ):
        parse_metadata_fabric_provider_evidence_artifact(
            provider.model_copy(update={"size_bytes": provider.size_bytes + 1})
        )


def test_provider_evidence_and_record_reject_tampering():
    bundle = build_binding_ledger_bundle()
    provider = bundle.artifacts[-1]
    manifest = dict(provider.manifest)
    manifest["replay_mutation_count"] = 1
    with pytest.raises(ValidationError):
        MetadataFabricProviderEvidence.model_validate(manifest)

    record = bundle.record
    payload = record.model_dump(mode="json", by_alias=True)
    payload["record_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="SHA-256 does not match"):
        MetadataFabricBindingRecord.model_validate(payload)

    rebuilt = build_metadata_fabric_binding_record(
        binding=record.binding,
        execution_plan_artifact_id=record.execution_plan_artifact_id,
        policy_decision_artifact_id=record.policy_decision_artifact_id,
        approval_artifact_id=record.approval_artifact_id,
        provider_evidence_artifact_id=record.provider_evidence_artifact_id,
        recorded_by=record.recorded_by,
        recorded_at=record.recorded_at,
    )
    assert rebuilt == record


def test_binding_ledger_contract_and_committed_evidence_validate():
    report = build_contract_report()
    evidence = json.loads(DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))

    assert report["status"] == "valid"
    assert report["errors"] == []
    assert validate_rehearsal_evidence(evidence) == []
    tampered = {**evidence, "first_commit_created": False}
    assert "binding ledger evidence SHA-256 does not match" in (
        validate_rehearsal_evidence(tampered)
    )
