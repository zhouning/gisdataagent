from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from data_agent.dolphinscheduler_adapter import (
    DolphinSchedulerContractError,
    DolphinSchedulerDefinitionBinding,
    build_dolphinscheduler_jqdltb_transformation_plan_artifact,
    compile_dolphinscheduler_workflow,
    parse_dolphinscheduler_binding_artifact,
    parse_dolphinscheduler_jqdltb_transformation_plan_artifact,
)
from data_agent.platform_contracts import (
    ApprovalCase,
    ApprovalCaseStatus,
    JqdltbAreaDeviationPolicy,
    JqdltbAreaPolicy,
    JqdltbDerivationContract,
    JqdltbDerivationStatus,
    JqdltbTransformationContract,
    JqdltbTransformationStrategy,
    canonical_json_fingerprint,
    compile_jqdltb_executable_contract,
)
from scripts.deploy_chongqing_jqdltb_transformation import (
    DEFINITION_VERSION_ID,
    SOURCE_RESOURCE_VERSION_ID,
    _definition,
    _validate_contract,
)
from scripts.manage_chongqing_jqdltb_transformation_approval import _build_approval

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "config/freezes/ar0-jqdltb-transformation-contract-2026-08-22.json"


def _contract() -> JqdltbTransformationContract:
    baseline = JqdltbTransformationContract.model_validate_json(BASELINE.read_text())
    proposal, pending = _build_approval(
        baseline=baseline,
        strategy=JqdltbTransformationStrategy(
            canonical_key="TBBH",
            nonpositive_area_policy=JqdltbAreaPolicy.QUARANTINE,
            area_deviation_policy=JqdltbAreaDeviationPolicy.PRESERVE_SOURCE,
            derivation_contracts=(
                JqdltbDerivationContract(
                    target_field="SJNF",
                    status=JqdltbDerivationStatus.PROPOSED,
                    source_fields=("JQDLMC",),
                    semantic_contract_ref="gda://local-dev/semantic_rule/sjnf-v1",
                    semantic_contract_sha256="1" * 64,
                    method="first non-blank approved source value",
                ),
                JqdltbDerivationContract(
                    target_field="MSSM",
                    status=JqdltbDerivationStatus.PROPOSED,
                    source_fields=("JQDLMC",),
                    semantic_contract_ref="gda://local-dev/semantic_rule/mssm-v1",
                    semantic_contract_sha256="2" * 64,
                    method="first non-blank approved source value",
                ),
            ),
        ),
        case_id="scheduler-plan-test",
        requester_subject="workload:ar0-contract-builder",
        request_reason="test scheduler plan",
        created_by="workload:ar0-contract-builder",
        proposed_at=datetime(2026, 8, 23, 1, tzinfo=UTC),
        requested_at=datetime(2026, 8, 23, 1, 1, tzinfo=UTC),
        expires_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    approved_payload = pending.model_dump(mode="json")
    approved_payload.update(
        {
            "status": ApprovalCaseStatus.APPROVED,
            "state_version": 1,
            "decided_by": "human:business-steward",
            "decision_reason": "approved scheduler plan",
            "decided_at": "2026-08-23T02:00:00Z",
        }
    )
    return compile_jqdltb_executable_contract(
        proposal,
        approval_case=ApprovalCase.model_validate(approved_payload),
        created_by="workload:ar0-contract-compiler",
        created_at=datetime(2026, 8, 23, 3, tzinfo=UTC),
    )


def _binding() -> DolphinSchedulerDefinitionBinding:
    return DolphinSchedulerDefinitionBinding(
        tenant_id="local-dev",
        definition_version_id=DEFINITION_VERSION_ID,
        project_code=7,
        workflow_definition_code=123,
        workflow_definition_version=4,
        compiled_sha256="a" * 64,
    )


def test_scheduler_plan_artifact_round_trips_through_generic_dispatch_parser() -> None:
    contract = _contract()
    artifact = build_dolphinscheduler_jqdltb_transformation_plan_artifact(
        _binding(),
        contract,
        created_by="workload:dolphinscheduler-gda-dataops",
        created_at=contract.created_at,
    )

    binding, persisted = parse_dolphinscheduler_jqdltb_transformation_plan_artifact(artifact)
    assert binding == _binding()
    assert persisted == contract
    assert parse_dolphinscheduler_binding_artifact(artifact) == _binding()
    assert artifact.resource_version_id == DEFINITION_VERSION_ID
    assert (
        artifact.manifest["transformation_contract"]["contract_sha256"]
        == contract.contract_sha256
    )


def test_scheduler_plan_artifact_rejects_contract_or_metadata_drift() -> None:
    contract = _contract()
    artifact = build_dolphinscheduler_jqdltb_transformation_plan_artifact(
        _binding(),
        contract,
        created_by="workload:dolphinscheduler-gda-dataops",
        created_at=contract.created_at,
    )
    manifest = dict(artifact.manifest)
    manifest["transformation_contract"] = dict(manifest["transformation_contract"])
    manifest["transformation_contract"]["plan_sha256"] = "0" * 64
    with pytest.raises(DolphinSchedulerContractError):
        parse_dolphinscheduler_jqdltb_transformation_plan_artifact(
            artifact.model_copy(update={"manifest": manifest})
        )


def test_transformation_definition_binds_contract_and_never_audit_endpoint() -> None:
    contract = _contract()
    definition = _definition(456, contract)
    spec = compile_dolphinscheduler_workflow(definition)
    task = definition.definition_document["dolphinscheduler"]["task_definitions"][0]
    raw_script = task["taskParams"]["rawScript"]

    assert definition.definition_version_id == DEFINITION_VERSION_ID
    assert definition.input_contract["source"]["resource_version_id"] == str(
        SOURCE_RESOURCE_VERSION_ID
    )
    assert (
        definition.definition_document["authority"]["contract_sha256"]
        == contract.contract_sha256
    )
    assert "/v1/execute/chongqing-jqdltb-transformation" in raw_script
    assert "/v1/execute/chongqing-jqdltb-audit" not in raw_script
    assert '"${gda_tenant_id}"' not in raw_script
    assert "strategy" not in raw_script
    assert spec.compiled_sha256 == canonical_json_fingerprint(
        spec.model_dump(mode="json", exclude={"compiled_sha256"})
    )


def test_deployment_requires_authoritative_approval_case_for_exact_plan() -> None:
    contract = _contract()

    class Authority:
        def get(self, tenant_id: str, approval_case_ref: str) -> ApprovalCase:
            assert tenant_id == contract.tenant_id
            assert approval_case_ref == contract.approval_case.approval_case_ref
            return contract.approval_case

    _validate_contract(contract, approval_authority=Authority())

    tampered = contract.approval_case.model_copy(
        update={"target_fingerprint": "0" * 64}
    )
    with pytest.raises(ValueError, match="does not match authoritative"):
        _validate_contract(
            contract.model_copy(update={"approval_case": tampered}),
            approval_authority=Authority(),
        )
