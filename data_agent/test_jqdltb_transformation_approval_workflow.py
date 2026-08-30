from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from data_agent.jqdltb_transformation_approval import (
    JqdltbTransformationApprovalService,
)
from data_agent.platform_contracts import (
    ApprovalCase,
    ApprovalCaseStatus,
    JqdltbAreaDeviationPolicy,
    JqdltbAreaPolicy,
    JqdltbDerivationContract,
    JqdltbDerivationStatus,
    JqdltbTransformationContract,
    JqdltbTransformationMode,
    JqdltbTransformationStrategy,
    canonical_json_fingerprint,
)
from scripts.manage_chongqing_jqdltb_transformation_approval import (
    _build_approval,
    build_readiness_report,
    compile_approved,
    main,
    prepare_approval,
)

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = (
    ROOT / "config/freezes/ar0-jqdltb-transformation-contract-2026-08-22.json"
)
DIAGNOSTIC_PATH = (
    ROOT
    / "benchmarks/standard_mapping_chongqing_v0_1/source_quality_repair_diagnostic.json"
)
MANIFEST_PATH = ROOT / "config/freezes/ar0-first-vertical-slice-2026-08-22.json"
SEMANTIC_AUDIT_PATH = (
    ROOT / "docs/reports/jqdltb_semantic_candidate_audit_2026-08-26.json"
)


class _FakeApprovalAuthority:
    def __init__(self) -> None:
        self.cases: dict[str, ApprovalCase] = {}

    def create(self, case: ApprovalCase, *, owner_ref: str):
        assert owner_ref == "team:data-platform"
        self.cases[case.approval_case_ref] = case
        return SimpleNamespace(approval_case=case, created=True)

    def get(self, tenant_id: str, approval_case_ref: str) -> ApprovalCase:
        case = self.cases[approval_case_ref]
        assert case.tenant_id == tenant_id
        return case


def _baseline() -> JqdltbTransformationContract:
    return JqdltbTransformationContract.model_validate_json(
        BASELINE_PATH.read_text(encoding="utf-8")
    )


def _strategy() -> JqdltbTransformationStrategy:
    return JqdltbTransformationStrategy(
        canonical_key="TBBH",
        nonpositive_area_policy=JqdltbAreaPolicy.QUARANTINE,
        area_deviation_policy=JqdltbAreaDeviationPolicy.PRESERVE_SOURCE,
        derivation_contracts=(
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
        ),
    )


def _prepare():
    return _build_approval(
        baseline=_baseline(),
        strategy=_strategy(),
        case_id="jqdltb-transform-workflow-v1",
        requester_subject="workload:ar0-contract-builder",
        request_reason="approve exact JQDLTB transformation choices",
        created_by="workload:ar0-contract-builder",
        proposed_at=datetime(2026, 8, 23, tzinfo=UTC),
        requested_at=datetime(2026, 8, 23, 1, tzinfo=UTC),
        expires_at=datetime(2026, 9, 23, tzinfo=UTC),
    )


def _approve(case: ApprovalCase) -> ApprovalCase:
    payload = case.model_dump(mode="json")
    payload.update(
        {
            "status": ApprovalCaseStatus.APPROVED,
            "state_version": 1,
            "decided_by": "human:business-steward",
            "decision_reason": "approved exact proposal",
            "decided_at": "2026-08-23T02:00:00Z",
        }
    )
    return ApprovalCase.model_validate(payload)


def _accepted_semantic_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Build disposable accepted evidence; this is not a real business approval."""

    audit = json.loads(SEMANTIC_AUDIT_PATH.read_text(encoding="utf-8"))
    for target, accepted_field in (("SJNF", "PZWH"), ("MSSM", "JQDLMC")):
        for candidate in audit["candidates"][target]:
            if candidate["field"] == accepted_field:
                candidate["status"] = "accepted"
        audit["decisions"][target] = "accepted_candidate_available"
    audit.pop("report_sha256")
    audit["report_sha256"] = canonical_json_fingerprint(audit)
    audit_path = tmp_path / "accepted-semantic-audit.json"
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    evidence = manifest["evidence"]
    evidence["semantic_candidate_audit"] = str(audit_path)
    evidence["semantic_candidate_audit_sha256"] = audit["report_sha256"]
    evidence["semantic_candidate_audit_content_sha256"] = hashlib.sha256(
        audit_path.read_bytes()
    ).hexdigest()
    evidence["expected_semantic_candidate_findings"]["decisions"] = audit[
        "decisions"
    ]
    manifest_path = tmp_path / "accepted-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path, audit_path


def test_prepare_binds_one_complete_proposal_to_pending_approval() -> None:
    proposal, case = _prepare()

    assert proposal.mode is JqdltbTransformationMode.DRY_RUN
    assert case.status is ApprovalCaseStatus.PENDING
    assert case.target_fingerprint == proposal.plan_sha256
    assert case.request_context == proposal.approval_context()
    assert case.request_context["nonpositive_area_policy"] == "quarantine"
    assert case.request_context["area_deviation_policy"] == "preserve_source"


def test_public_prepare_cannot_bypass_frozen_semantic_admission() -> None:
    with pytest.raises(
        ValueError, match="SJNF derivation uses semantically rejected source fields: PZWH"
    ):
        prepare_approval(
            baseline=_baseline(),
            strategy=_strategy(),
            case_id="jqdltb-public-prepare-rejected-v1",
            requester_subject="workload:ar0-contract-builder",
            request_reason="must pass frozen semantic admission",
            created_by="workload:ar0-contract-builder",
            proposed_at=datetime(2026, 8, 23, tzinfo=UTC),
            requested_at=datetime(2026, 8, 23, 1, tzinfo=UTC),
            expires_at=datetime(2026, 9, 23, tzinfo=UTC),
        )


def test_public_prepare_accepts_only_manifest_bound_semantic_evidence(
    tmp_path: Path,
) -> None:
    manifest_path, semantic_audit_path = _accepted_semantic_fixture(tmp_path)

    proposal, case = prepare_approval(
        baseline=_baseline(),
        strategy=_strategy(),
        case_id="jqdltb-public-prepare-accepted-fixture-v1",
        requester_subject="workload:ar0-contract-builder",
        request_reason="disposable accepted semantic evidence",
        created_by="workload:ar0-contract-builder",
        proposed_at=datetime(2026, 8, 23, tzinfo=UTC),
        requested_at=datetime(2026, 8, 23, 1, tzinfo=UTC),
        expires_at=datetime(2026, 9, 23, tzinfo=UTC),
        manifest_path=manifest_path,
        diagnostic_path=DIAGNOSTIC_PATH,
        semantic_audit_path=semantic_audit_path,
    )

    assert case.target_fingerprint == proposal.plan_sha256
    assert case.status is ApprovalCaseStatus.PENDING
    assert proposal.semantic_candidate_audit_sha256 == json.loads(
        semantic_audit_path.read_text(encoding="utf-8")
    )["report_sha256"]
    assert (
        case.request_context["semantic_candidate_audit_sha256"]
        == proposal.semantic_candidate_audit_sha256
    )

    tampered = proposal.model_dump(mode="json")
    tampered["semantic_candidate_audit_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="plan_sha256"):
        JqdltbTransformationContract.model_validate(tampered)


def test_public_prepare_rejects_a_baseline_different_from_manifest(
    tmp_path: Path,
) -> None:
    manifest_path, semantic_audit_path = _accepted_semantic_fixture(tmp_path)
    tampered_baseline = _baseline().model_copy(
        update={"created_at": datetime(2026, 8, 24, tzinfo=UTC)}
    )

    with pytest.raises(ValueError, match="baseline does not match"):
        prepare_approval(
            baseline=tampered_baseline,
            strategy=_strategy(),
            case_id="jqdltb-public-prepare-baseline-drift-v1",
            requester_subject="workload:ar0-contract-builder",
            request_reason="must reject baseline drift",
            created_by="workload:ar0-contract-builder",
            proposed_at=datetime(2026, 8, 23, tzinfo=UTC),
            requested_at=datetime(2026, 8, 23, 1, tzinfo=UTC),
            expires_at=datetime(2026, 9, 23, tzinfo=UTC),
            manifest_path=manifest_path,
            diagnostic_path=DIAGNOSTIC_PATH,
            semantic_audit_path=semantic_audit_path,
        )


def test_readiness_without_strategy_reports_exact_external_blockers() -> None:
    report = build_readiness_report(
        manifest_path=MANIFEST_PATH,
        baseline_path=BASELINE_PATH,
        diagnostic_path=DIAGNOSTIC_PATH,
    )

    assert report["freeze"] == {
        "manifest_id": "ar0-first-vertical-slice-2026-08-22",
        "status": "awaiting_business_approval",
        "valid": True,
        "promotion_ready": False,
    }
    assert not report["transformation_proposal"]["ready"]
    assert set(report["transformation_proposal"]["blockers"]) == {
        "transformation_strategy_missing",
        "semantic_derivation_evidence_missing.SJNF",
        "semantic_derivation_evidence_missing.MSSM",
    }
    assert report["decision_requirements"]["canonical_key"]["allowed"] == ["TBBH"]
    assert report["decision_requirements"]["nonpositive_area_policy"][
        "observed_counts"
    ] == {"TBDLMJ": 6, "TBMJ": 6}
    semantic = report["decision_requirements"]["semantic_evidence"]
    assert semantic["sjnf_definition"] == "数据年份为数据生产的年份"
    assert semantic["mssm_type"] == "Char"
    assert semantic["mssm_length"] == "2"
    assert semantic["mssm_value_domain_present"] is False
    assert semantic["candidate_non_blank_counts"] == {
        "PZWH": 10,
        "SM": 0,
        "DLBZ": 0,
        "JQDLMC": 1555,
    }
    assert semantic["candidate_statuses"]["SJNF"][
        "permitted_source_fields"
    ] == []
    assert semantic["candidate_statuses"]["SJNF"]["rejected_source_fields"] == [
        "JQDLMC",
        "PZWH",
        "SM",
        "metadata_processing_history",
    ]
    assert set(report["product_promotion"]["blockers"]) == {
        "business_steward",
        "license_status",
        "slo_on_call",
        "environment_owner.staging_missing",
        "environment_owner.production_missing",
        "source_quality_not_passed",
        "data_product_version_not_created",
        "transformation_strategy_missing",
        "semantic_derivation_evidence_missing.SJNF",
        "semantic_derivation_evidence_missing.MSSM",
    }
    assert not report["authority_state_created"]
    assert not report["source_bytes_modified"]


def test_readiness_requires_accepted_semantic_evidence_before_preview(
    tmp_path: Path,
) -> None:
    strategy = _strategy()
    with pytest.raises(
        ValueError, match="SJNF derivation uses semantically rejected source fields: PZWH"
    ):
        build_readiness_report(
            manifest_path=MANIFEST_PATH,
            baseline_path=BASELINE_PATH,
            diagnostic_path=DIAGNOSTIC_PATH,
            strategy=strategy,
        )

    manifest_path, semantic_audit_path = _accepted_semantic_fixture(tmp_path)
    report = build_readiness_report(
        manifest_path=manifest_path,
        baseline_path=BASELINE_PATH,
        diagnostic_path=DIAGNOSTIC_PATH,
        semantic_audit_path=semantic_audit_path,
        strategy=strategy,
    )

    assert report["transformation_proposal"]["ready"]
    assert report["transformation_proposal"]["blockers"] == []
    preview = report["transformation_proposal"]["preview"]
    assert preview["approval_context"]["canonical_key"] == "TBBH"
    assert preview["approval_context"]["nonpositive_area_policy"] == "quarantine"
    assert preview["plan_sha256"] == preview["approval_context"]["plan_sha256"]
    assert report["identities"]["strategy_sha256"]
    assert "transformation_approval_missing" in report["product_promotion"]["blockers"]

    invalid = strategy.model_dump(mode="json")
    invalid["derivation_contracts"][0]["source_fields"] = ["NOT_OBSERVED"]
    with pytest.raises(ValueError, match="unobserved source fields: NOT_OBSERVED"):
        build_readiness_report(
            manifest_path=manifest_path,
            baseline_path=BASELINE_PATH,
            diagnostic_path=DIAGNOSTIC_PATH,
            semantic_audit_path=semantic_audit_path,
            strategy=JqdltbTransformationStrategy.model_validate(invalid),
        )


def test_readiness_cli_writes_only_a_preflight_report(tmp_path: Path) -> None:
    output = tmp_path / "readiness.json"

    assert main(["readiness", "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema"] == "gda.jqdltb_transformation_approval_readiness.v1"
    assert report["scope"] == "read_only_preflight"
    assert report["readiness_sha256"]
    assert not report["authority_state_created"]


def test_compile_rejects_pending_or_context_drift_and_preserves_plan() -> None:
    proposal, pending = _prepare()
    with pytest.raises(ValueError, match="must be approved"):
        compile_approved(
            proposal=proposal,
            approval_case=pending,
            created_by="workload:ar0-contract-compiler",
            compiled_at=datetime(2026, 8, 23, 3, tzinfo=UTC),
        )

    approved = _approve(pending)
    tampered = approved.model_dump(mode="json")
    tampered["request_context"]["area_deviation_policy"] = "quarantine"
    with pytest.raises(ValueError, match="context must describe the exact plan"):
        compile_approved(
            proposal=proposal,
            approval_case=ApprovalCase.model_validate(tampered),
            created_by="workload:ar0-contract-compiler",
            compiled_at=datetime(2026, 8, 23, 3, tzinfo=UTC),
        )

    executable = compile_approved(
        proposal=proposal,
        approval_case=approved,
        created_by="workload:ar0-contract-compiler",
        compiled_at=datetime(2026, 8, 23, 3, tzinfo=UTC),
    )
    assert executable.mode is JqdltbTransformationMode.EXECUTE
    assert executable.plan_sha256 == proposal.plan_sha256
    assert executable.approval_case == approved


def test_prepare_cli_emits_proposal_and_generic_approval_case(tmp_path: Path) -> None:
    strategy_path = tmp_path / "strategy.json"
    proposal_path = tmp_path / "proposal.json"
    approval_path = tmp_path / "approval-case.json"
    manifest_path, semantic_audit_path = _accepted_semantic_fixture(tmp_path)
    strategy_path.write_text(
        json.dumps(_strategy().model_dump(mode="json")), encoding="utf-8"
    )

    result = main(
        [
            "prepare",
            "--manifest",
            str(manifest_path),
            "--semantic-audit",
            str(semantic_audit_path),
            "--strategy",
            str(strategy_path),
            "--proposal-output",
            str(proposal_path),
            "--approval-output",
            str(approval_path),
            "--case-id",
            "jqdltb-transform-cli-v1",
            "--requester-subject",
            "workload:ar0-contract-builder",
            "--request-reason",
            "approve exact JQDLTB transformation choices",
            "--proposed-at",
            "2026-08-23T00:00:00Z",
            "--requested-at",
            "2026-08-23T01:00:00Z",
            "--expires-at",
            "2026-09-23T00:00:00Z",
        ]
    )

    assert result == 0
    proposal = JqdltbTransformationContract.model_validate_json(
        proposal_path.read_text(encoding="utf-8")
    )
    case = ApprovalCase.model_validate_json(approval_path.read_text(encoding="utf-8"))
    assert case.target_fingerprint == proposal.plan_sha256


def test_prepare_cli_rejects_frozen_semantic_candidates_before_writing(
    tmp_path: Path,
) -> None:
    strategy_path = tmp_path / "rejected-strategy.json"
    proposal_path = tmp_path / "proposal.json"
    approval_path = tmp_path / "approval-case.json"
    strategy_path.write_text(
        json.dumps(_strategy().model_dump(mode="json")), encoding="utf-8"
    )

    with pytest.raises(
        ValueError, match="SJNF derivation uses semantically rejected source fields: PZWH"
    ):
        main(
            [
                "prepare",
                "--strategy",
                str(strategy_path),
                "--proposal-output",
                str(proposal_path),
                "--approval-output",
                str(approval_path),
                "--case-id",
                "jqdltb-transform-rejected-v1",
                "--requester-subject",
                "workload:ar0-contract-builder",
                "--request-reason",
                "must fail before approval artifacts",
                "--proposed-at",
                "2026-08-23T00:00:00Z",
                "--requested-at",
                "2026-08-23T01:00:00Z",
                "--expires-at",
                "2026-09-23T00:00:00Z",
            ]
        )

    assert not proposal_path.exists()
    assert not approval_path.exists()


def test_compile_cli_preserves_the_approved_plan(tmp_path: Path) -> None:
    proposal, pending = _prepare()
    proposal_path = tmp_path / "proposal.json"
    approval_path = tmp_path / "approved-case.json"
    output_path = tmp_path / "execute-contract.json"
    proposal_path.write_text(
        json.dumps(proposal.model_dump(mode="json")), encoding="utf-8"
    )
    approval_path.write_text(
        json.dumps(_approve(pending).model_dump(mode="json")), encoding="utf-8"
    )

    result = main(
        [
            "compile",
            "--proposal",
            str(proposal_path),
            "--approval-case",
            str(approval_path),
            "--output",
            str(output_path),
            "--compiled-at",
            "2026-08-23T03:00:00Z",
        ]
    )

    assert result == 0
    executable = JqdltbTransformationContract.model_validate_json(
        output_path.read_text(encoding="utf-8")
    )
    assert executable.mode is JqdltbTransformationMode.EXECUTE
    assert executable.plan_sha256 == proposal.plan_sha256


def test_service_uses_authority_for_request_compile_and_execution() -> None:
    authority = _FakeApprovalAuthority()
    service = JqdltbTransformationApprovalService(authority)
    proposal, _unused = _prepare()
    pending = service.request(
        proposal,
        case_id="jqdltb-transform-service-v1",
        requester_subject="workload:ar0-contract-builder",
        request_reason="approve exact JQDLTB transformation choices",
        owner_ref="team:data-platform",
        requested_at=datetime(2026, 8, 23, 1, tzinfo=UTC),
        expires_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="must be approved"):
        service.compile(
            proposal,
            approval_case_ref=pending.approval_case_ref,
            created_by="workload:ar0-contract-compiler",
            created_at=datetime(2026, 8, 23, 3, tzinfo=UTC),
        )

    authority.cases[pending.approval_case_ref] = _approve(pending)
    executable = service.compile(
        proposal,
        approval_case_ref=pending.approval_case_ref,
        created_by="workload:ar0-contract-compiler",
        created_at=datetime(2026, 8, 23, 3, tzinfo=UTC),
    )
    diagnostic = json.loads(DIAGNOSTIC_PATH.read_text(encoding="utf-8"))
    service.validate_execution(
        executable,
        diagnostic=diagnostic,
        archive_sha256=executable.archive_sha256,
        bundle_sha256=executable.bundle_sha256,
        standard_version_ref=executable.standard_version_ref,
        standard_fingerprint=executable.standard_fingerprint,
        source_resource_version_id=executable.source_resource_version_id,
    )

    stored = authority.cases[pending.approval_case_ref].model_dump(mode="json")
    stored["decision_reason"] = "authority record changed"
    authority.cases[pending.approval_case_ref] = ApprovalCase.model_validate(stored)
    with pytest.raises(ValueError, match="authoritative ApprovalCase"):
        service.validate_execution(
            executable,
            diagnostic=diagnostic,
            archive_sha256=executable.archive_sha256,
            bundle_sha256=executable.bundle_sha256,
            standard_version_ref=executable.standard_version_ref,
            standard_fingerprint=executable.standard_fingerprint,
            source_resource_version_id=executable.source_resource_version_id,
        )
