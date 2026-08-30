from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from data_agent.platform_contracts import (
    ApprovalCase,
    ApprovalCaseStatus,
    JqdltbAreaDeviationPolicy,
    JqdltbAreaPolicy,
    JqdltbDerivationContract,
    JqdltbDerivationStatus,
    JqdltbTransformationMode,
    PlatformContractError,
    build_jqdltb_transformation_approval_case,
    build_jqdltb_transformation_contract,
    canonical_json_fingerprint,
    compile_jqdltb_executable_contract,
    validate_jqdltb_transformation_execution,
)

ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTIC_PATH = (
    ROOT
    / "benchmarks/standard_mapping_chongqing_v0_1/source_quality_repair_diagnostic.json"
)
SEMANTIC_AUDIT_PATH = (
    ROOT / "docs/reports/jqdltb_semantic_candidate_audit_2026-08-26.json"
)
SOURCE_VERSION_ID = UUID("34441c77-2cf0-5ca2-83bf-81dd6a488d5b")
SOURCE_URN = "gda://local-dev/dataset/chongqing-bizhu-jqdltb-source"


def _diagnostic() -> dict:
    return json.loads(DIAGNOSTIC_PATH.read_text(encoding="utf-8"))


def _accepted_semantic_audit() -> dict:
    audit = json.loads(SEMANTIC_AUDIT_PATH.read_text(encoding="utf-8"))
    for target, accepted_field in (("SJNF", "PZWH"), ("MSSM", "JQDLMC")):
        for candidate in audit["candidates"][target]:
            if candidate["field"] == accepted_field:
                candidate["status"] = "accepted"
        audit["decisions"][target] = "accepted_candidate_available"
    audit.pop("report_sha256")
    audit["report_sha256"] = canonical_json_fingerprint(audit)
    return audit


def _common() -> dict[str, object]:
    diagnostic = _diagnostic()
    return {
        "tenant_id": "local-dev",
        "source_resource_version_id": SOURCE_VERSION_ID,
        "source_resource_urn": SOURCE_URN,
        "archive_sha256": diagnostic["source"]["archive_sha256"],
        "bundle_sha256": diagnostic["source"]["bundle_sha256"],
        "standard_version_ref": "NR_ONE_MAP_TWM_CORE_2026:2026-06-16-draft",
        "standard_fingerprint": "a9b58ea766e1f7fd0f203b07bb23e3848e1db7dad560ebf04843b83a5b713630",
        "diagnostic_sha256": diagnostic["diagnostic_sha256"],
        "created_by": "workload:test",
        "created_at": datetime(2026, 8, 23, tzinfo=UTC),
    }


def _proposed_derivations() -> tuple[JqdltbDerivationContract, ...]:
    return (
        JqdltbDerivationContract(
            target_field="SJNF",
            status=JqdltbDerivationStatus.PROPOSED,
            source_fields=("PZWH",),
            semantic_contract_ref="gda://local-dev/semantic_rule/sjnf-v1",
            semantic_contract_sha256="1" * 64,
            method="proposed source-year mapping",
        ),
        JqdltbDerivationContract(
            target_field="MSSM",
            status=JqdltbDerivationStatus.PROPOSED,
            source_fields=("JQDLMC",),
            semantic_contract_ref="gda://local-dev/semantic_rule/mssm-v1",
            semantic_contract_sha256="2" * 64,
            method="proposed description mapping",
        ),
    )


def _proposal():
    return build_jqdltb_transformation_contract(
        **_common(),
        mode=JqdltbTransformationMode.DRY_RUN,
        nonpositive_area_policy=JqdltbAreaPolicy.QUARANTINE,
        area_deviation_policy=JqdltbAreaDeviationPolicy.PRESERVE_SOURCE,
        derivation_contracts=_proposed_derivations(),
    )


def _approved_case(proposal):
    pending = build_jqdltb_transformation_approval_case(
        proposal,
        case_id="jqdltb-transform-v1",
        requester_subject="workload:ar0-contract-builder",
        request_reason="approve the exact JQDLTB transformation plan",
        requested_at=datetime(2026, 8, 23, 1, tzinfo=UTC),
        expires_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    payload = pending.model_dump(mode="json")
    payload.update(
        {
            "status": ApprovalCaseStatus.APPROVED,
            "state_version": 1,
            "decided_by": "human:business-steward",
            "decision_reason": "approved for the frozen source and standard",
            "decided_at": "2026-08-23T02:00:00Z",
        }
    )
    return ApprovalCase.model_validate(payload)


def _executable_contract():
    proposal = _proposal()
    return compile_jqdltb_executable_contract(
        proposal,
        approval_case=_approved_case(proposal),
        created_by="workload:ar0-contract-compiler",
        created_at=datetime(2026, 8, 23, 3, tzinfo=UTC),
    )


def test_approval_required_contract_is_hash_complete_and_non_executable() -> None:
    contract = build_jqdltb_transformation_contract(
        **_common(), mode=JqdltbTransformationMode.APPROVAL_REQUIRED
    )

    assert contract.mode is JqdltbTransformationMode.APPROVAL_REQUIRED
    assert contract.canonical_key == "TBBH"
    assert contract.nonpositive_area_policy is None
    assert contract.area_deviation_policy is None
    assert contract.approval_case is None
    assert len(contract.contract_fingerprint()) == 64


def test_unapproved_strategy_cannot_be_smuggled_into_draft() -> None:
    with pytest.raises(ValueError, match="cannot select strategy values"):
        build_jqdltb_transformation_contract(
            **_common(),
            mode=JqdltbTransformationMode.APPROVAL_REQUIRED,
            nonpositive_area_policy=JqdltbAreaPolicy.QUARANTINE,
        )

    with pytest.raises(ValueError):
        build_jqdltb_transformation_contract(
            **_common(),
            mode=JqdltbTransformationMode.APPROVAL_REQUIRED,
            canonical_key="BSM",
        )

    with pytest.raises(ValueError, match="must not smuggle"):
        JqdltbDerivationContract(
            target_field="SJNF",
            status=JqdltbDerivationStatus.PENDING_APPROVAL,
            source_fields=("PZWH",),
        )


def test_high_impact_area_policies_require_versioned_inputs() -> None:
    with pytest.raises(ValueError, match="versioned correction binding"):
        build_jqdltb_transformation_contract(
            **_common(),
            mode=JqdltbTransformationMode.EXECUTE,
            nonpositive_area_policy=JqdltbAreaPolicy.BUSINESS_CORRECTION,
            area_deviation_policy=JqdltbAreaDeviationPolicy.PRESERVE_SOURCE,
            derivation_contracts=_proposed_derivations(),
        )

    with pytest.raises(ValueError, match="fingerprinted area rule"):
        build_jqdltb_transformation_contract(
            **_common(),
            mode=JqdltbTransformationMode.EXECUTE,
            nonpositive_area_policy=JqdltbAreaPolicy.QUARANTINE,
            area_deviation_policy=JqdltbAreaDeviationPolicy.USE_GEOMETRY,
            derivation_contracts=_proposed_derivations(),
        )


def test_approved_contract_binds_plan_and_execution_inputs() -> None:
    proposal = _proposal()
    approval_case = _approved_case(proposal)
    executable = _executable_contract()
    assert proposal.mode is JqdltbTransformationMode.DRY_RUN
    assert approval_case.target_fingerprint == proposal.plan_sha256
    assert approval_case.request_context == proposal.approval_context()
    assert executable.plan_sha256 == proposal.plan_sha256
    assert executable.contract_sha256 != proposal.contract_sha256
    assert executable.approval_case == approval_case
    validate_jqdltb_transformation_execution(
        executable,
        authoritative_approval_case=approval_case,
        diagnostic=_diagnostic(),
        archive_sha256=executable.archive_sha256,
        bundle_sha256=executable.bundle_sha256,
        standard_version_ref=executable.standard_version_ref,
        standard_fingerprint=executable.standard_fingerprint,
        source_resource_version_id=executable.source_resource_version_id,
    )


def test_execution_revalidates_semantic_audit_bound_by_approved_plan() -> None:
    audit = _accepted_semantic_audit()
    proposal = build_jqdltb_transformation_contract(
        **_common(),
        mode=JqdltbTransformationMode.DRY_RUN,
        semantic_candidate_audit_sha256=audit["report_sha256"],
        nonpositive_area_policy=JqdltbAreaPolicy.QUARANTINE,
        area_deviation_policy=JqdltbAreaDeviationPolicy.PRESERVE_SOURCE,
        derivation_contracts=_proposed_derivations(),
    )
    approval_case = _approved_case(proposal)
    executable = compile_jqdltb_executable_contract(
        proposal,
        approval_case=approval_case,
        created_by="workload:ar0-contract-compiler",
        created_at=datetime(2026, 8, 23, 3, tzinfo=UTC),
    )
    inputs = {
        "authoritative_approval_case": approval_case,
        "diagnostic": _diagnostic(),
        "archive_sha256": executable.archive_sha256,
        "bundle_sha256": executable.bundle_sha256,
        "standard_version_ref": executable.standard_version_ref,
        "standard_fingerprint": executable.standard_fingerprint,
        "source_resource_version_id": executable.source_resource_version_id,
    }

    with pytest.raises(PlatformContractError, match="audit is required"):
        validate_jqdltb_transformation_execution(executable, **inputs)

    validate_jqdltb_transformation_execution(
        executable,
        semantic_candidate_audit=audit,
        **inputs,
    )

    tampered = json.loads(json.dumps(audit))
    tampered["candidates"]["SJNF"][0]["reason"] = "tampered"
    with pytest.raises(PlatformContractError, match="fingerprint is invalid"):
        validate_jqdltb_transformation_execution(
            executable,
            semantic_candidate_audit=tampered,
            **inputs,
        )

    blocked_decision = json.loads(json.dumps(audit))
    blocked_decision["decisions"]["SJNF"] = "blocked_no_authoritative_derivation"
    blocked_decision.pop("report_sha256")
    blocked_decision["report_sha256"] = canonical_json_fingerprint(blocked_decision)
    blocked_proposal = build_jqdltb_transformation_contract(
        **_common(),
        mode=JqdltbTransformationMode.DRY_RUN,
        semantic_candidate_audit_sha256=blocked_decision["report_sha256"],
        nonpositive_area_policy=JqdltbAreaPolicy.QUARANTINE,
        area_deviation_policy=JqdltbAreaDeviationPolicy.PRESERVE_SOURCE,
        derivation_contracts=_proposed_derivations(),
    )
    blocked_case = _approved_case(blocked_proposal)
    blocked_executable = compile_jqdltb_executable_contract(
        blocked_proposal,
        approval_case=blocked_case,
        created_by="workload:ar0-contract-compiler",
        created_at=datetime(2026, 8, 23, 3, tzinfo=UTC),
    )
    with pytest.raises(PlatformContractError, match="decision is not accepted"):
        validate_jqdltb_transformation_execution(
            blocked_executable,
            authoritative_approval_case=blocked_case,
            diagnostic=_diagnostic(),
            archive_sha256=blocked_executable.archive_sha256,
            bundle_sha256=blocked_executable.bundle_sha256,
            standard_version_ref=blocked_executable.standard_version_ref,
            standard_fingerprint=blocked_executable.standard_fingerprint,
            source_resource_version_id=blocked_executable.source_resource_version_id,
            semantic_candidate_audit=blocked_decision,
        )

    revoked = json.loads(json.dumps(audit))
    for candidate in revoked["candidates"]["SJNF"]:
        if candidate["field"] == "PZWH":
            candidate["status"] = "rejected"
    revoked.pop("report_sha256")
    revoked["report_sha256"] = canonical_json_fingerprint(revoked)
    revoked_proposal = build_jqdltb_transformation_contract(
        **_common(),
        mode=JqdltbTransformationMode.DRY_RUN,
        semantic_candidate_audit_sha256=revoked["report_sha256"],
        nonpositive_area_policy=JqdltbAreaPolicy.QUARANTINE,
        area_deviation_policy=JqdltbAreaDeviationPolicy.PRESERVE_SOURCE,
        derivation_contracts=_proposed_derivations(),
    )
    revoked_case = _approved_case(revoked_proposal)
    revoked_executable = compile_jqdltb_executable_contract(
        revoked_proposal,
        approval_case=revoked_case,
        created_by="workload:ar0-contract-compiler",
        created_at=datetime(2026, 8, 23, 3, tzinfo=UTC),
    )
    with pytest.raises(PlatformContractError, match="lost semantic admission: PZWH"):
        validate_jqdltb_transformation_execution(
            revoked_executable,
            authoritative_approval_case=revoked_case,
            diagnostic=_diagnostic(),
            archive_sha256=revoked_executable.archive_sha256,
            bundle_sha256=revoked_executable.bundle_sha256,
            standard_version_ref=revoked_executable.standard_version_ref,
            standard_fingerprint=revoked_executable.standard_fingerprint,
            source_resource_version_id=revoked_executable.source_resource_version_id,
            semantic_candidate_audit=revoked,
        )


def test_incomplete_contract_cannot_enter_approval_workflow() -> None:
    unresolved = build_jqdltb_transformation_contract(
        **_common(), mode=JqdltbTransformationMode.APPROVAL_REQUIRED
    )
    with pytest.raises(PlatformContractError, match="complete dry-run proposal"):
        build_jqdltb_transformation_approval_case(
            unresolved,
            case_id="incomplete-jqdltb-transform",
            requester_subject="workload:test",
            request_reason="invalid incomplete request",
            requested_at=datetime(2026, 8, 23, 1, tzinfo=UTC),
            expires_at=datetime(2026, 9, 23, tzinfo=UTC),
        )


def test_execution_rejects_diagnostic_and_source_drift() -> None:
    contract = build_jqdltb_transformation_contract(
        **_common(), mode=JqdltbTransformationMode.APPROVAL_REQUIRED
    )
    with pytest.raises(PlatformContractError, match="approval_required"):
        validate_jqdltb_transformation_execution(
            contract,
            authoritative_approval_case=_approved_case(_proposal()),
            diagnostic=_diagnostic(),
            archive_sha256=contract.archive_sha256,
            bundle_sha256=contract.bundle_sha256,
            standard_version_ref=contract.standard_version_ref,
            standard_fingerprint=contract.standard_fingerprint,
            source_resource_version_id=contract.source_resource_version_id,
        )


def test_execution_rejects_input_checksum_drift() -> None:
    executable = _executable_contract()
    with pytest.raises(PlatformContractError, match="bundle_sha256"):
        validate_jqdltb_transformation_execution(
            executable,
            authoritative_approval_case=executable.approval_case,
            diagnostic=_diagnostic(),
            archive_sha256=executable.archive_sha256,
            bundle_sha256="f" * 64,
            standard_version_ref=executable.standard_version_ref,
            standard_fingerprint=executable.standard_fingerprint,
            source_resource_version_id=executable.source_resource_version_id,
        )

    with pytest.raises(PlatformContractError, match="source_resource_version_id"):
        validate_jqdltb_transformation_execution(
            executable,
            authoritative_approval_case=executable.approval_case,
            diagnostic=_diagnostic(),
            archive_sha256=executable.archive_sha256,
            bundle_sha256=executable.bundle_sha256,
            standard_version_ref=executable.standard_version_ref,
            standard_fingerprint=executable.standard_fingerprint,
            source_resource_version_id=UUID("00000000-0000-0000-0000-000000000001"),
        )


def test_execution_rejects_diagnostic_fingerprint_drift() -> None:
    executable = _executable_contract()
    diagnostic = _diagnostic()
    diagnostic["area_consistency"]["outside_tolerance_count"] = 8
    diagnostic.pop("diagnostic_sha256")
    diagnostic["diagnostic_sha256"] = canonical_json_fingerprint(diagnostic)
    with pytest.raises(PlatformContractError, match="diagnostic fingerprint drifted"):
        validate_jqdltb_transformation_execution(
            executable,
            authoritative_approval_case=executable.approval_case,
            diagnostic=diagnostic,
            archive_sha256=executable.archive_sha256,
            bundle_sha256=executable.bundle_sha256,
            standard_version_ref=executable.standard_version_ref,
            standard_fingerprint=executable.standard_fingerprint,
            source_resource_version_id=executable.source_resource_version_id,
        )


def test_execution_rejects_approval_for_a_different_plan() -> None:
    executable = _executable_contract()
    payload = executable.model_dump(mode="json")
    payload["approval_case"]["target_fingerprint"] = "f" * 64
    with pytest.raises(ValueError, match="exact JQDLTB transformation plan"):
        type(executable).model_validate(payload)


def test_execution_requires_authoritative_approval_record() -> None:
    executable = _executable_contract()
    authoritative = executable.approval_case.model_dump(mode="json")
    authoritative["decision_reason"] = "different stored decision"
    with pytest.raises(PlatformContractError, match="authoritative ApprovalCase"):
        validate_jqdltb_transformation_execution(
            executable,
            authoritative_approval_case=ApprovalCase.model_validate(authoritative),
            diagnostic=_diagnostic(),
            archive_sha256=executable.archive_sha256,
            bundle_sha256=executable.bundle_sha256,
            standard_version_ref=executable.standard_version_ref,
            standard_fingerprint=executable.standard_fingerprint,
            source_resource_version_id=executable.source_resource_version_id,
        )
