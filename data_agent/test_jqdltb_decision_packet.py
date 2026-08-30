from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from data_agent.platform_contracts import (
    JqdltbDecision,
    JqdltbDecisionPacket,
    JqdltbDecisionPacketStatus,
    JqdltbDecisionStatus,
    PlatformContractError,
    build_jqdltb_decision_packet,
    canonical_json_fingerprint,
)
from scripts.manage_chongqing_jqdltb_transformation_approval import (
    build_decision_packet,
    build_readiness_report,
    main,
    validate_decision_packet,
)

ROOT = Path(__file__).resolve().parents[1]
PACKET_PATH = ROOT / "docs/reports/jqdltb_business_decision_packet_2026-08-26.json"
BASELINE_PATH = (
    ROOT / "config/freezes/ar0-jqdltb-transformation-contract-2026-08-22.json"
)
MANIFEST_PATH = ROOT / "config/freezes/ar0-first-vertical-slice-2026-08-22.json"
DIAGNOSTIC_PATH = (
    ROOT
    / "benchmarks/standard_mapping_chongqing_v0_1/source_quality_repair_diagnostic.json"
)
SEMANTIC_AUDIT_PATH = (
    ROOT / "docs/reports/jqdltb_semantic_candidate_audit_2026-08-26.json"
)


def _packet() -> JqdltbDecisionPacket:
    return JqdltbDecisionPacket.model_validate_json(PACKET_PATH.read_text())


def _submitted_packet_fixture(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> tuple[JqdltbDecisionPacket, Path, Path]:
    """Create disposable accepted evidence without changing the real AR-0 state."""

    fixture_root = Path(
        tempfile.mkdtemp(
            prefix=f"pytest-{tmp_path.name}-decision-packet-",
            dir=ROOT / ".tmp",
        )
    )
    request.addfinalizer(lambda: shutil.rmtree(fixture_root, ignore_errors=True))

    audit = json.loads(SEMANTIC_AUDIT_PATH.read_text(encoding="utf-8"))
    accepted_sources = {"SJNF": "PZWH", "MSSM": "JQDLMC"}
    for target, accepted_field in accepted_sources.items():
        for candidate in audit["candidates"][target]:
            if candidate["field"] == accepted_field:
                candidate["status"] = "accepted"
        audit["decisions"][target] = "accepted_candidate_available"
    audit.pop("report_sha256")
    audit["report_sha256"] = canonical_json_fingerprint(audit)
    audit_path = fixture_root / "accepted-semantic-audit.json"
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    evidence = manifest["evidence"]
    evidence["semantic_candidate_audit"] = str(audit_path.relative_to(ROOT))
    evidence["semantic_candidate_audit_sha256"] = audit["report_sha256"]
    evidence["semantic_candidate_audit_content_sha256"] = hashlib.sha256(
        audit_path.read_bytes()
    ).hexdigest()
    evidence["expected_semantic_candidate_findings"]["decisions"] = audit[
        "decisions"
    ]
    manifest_path = fixture_root / "accepted-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    draft = build_decision_packet(
        manifest_path=manifest_path,
        baseline_path=BASELINE_PATH,
        diagnostic_path=DIAGNOSTIC_PATH,
        semantic_audit_path=audit_path,
        packet_id="jqdltb-submitted-readiness-fixture-v1",
        created_by="workload:test",
        created_at=datetime(2026, 8, 26, tzinfo=UTC),
    )
    values = {
        "canonical_key": "TBBH",
        "nonpositive_area_policy": "quarantine",
        "area_deviation_policy": "preserve_source",
        "SJNF": "2025",
        "MSSM": "01",
    }
    decisions = []
    for pending in draft.decisions:
        if pending.target not in values:
            decisions.append(pending)
            continue
        decision = pending.model_dump(mode="json")
        decision.update(
            status="submitted",
            selected_value=values[pending.target],
            owner_ref="human:business-steward",
        )
        if pending.target in accepted_sources:
            decision.update(
                source_fields=[accepted_sources[pending.target]],
                semantic_contract_ref=(
                    f"gda://local-dev/semantic_rule/{pending.target.lower()}-v1"
                ),
                semantic_contract_sha256="a" * 64,
                method="extract the accepted source field",
            )
        decisions.append(JqdltbDecision.model_validate(decision))
    submitted = build_jqdltb_decision_packet(
        packet_id=draft.packet_id,
        identity=draft.identity,
        decisions=tuple(decisions),
        created_by=draft.created_by,
        created_at=draft.created_at,
        status="submitted",
        submitted_by="human:business-steward",
        submitted_at=datetime(2026, 8, 26, 1, tzinfo=UTC),
    )
    return submitted, manifest_path, audit_path


def test_draft_packet_contains_all_required_targets_and_frozen_identity() -> None:
    packet = _packet()
    assert packet.status is JqdltbDecisionPacketStatus.DRAFT
    assert {item.target for item in packet.decisions} == {
        "canonical_key",
        "nonpositive_area_policy",
        "area_deviation_policy",
        "SJNF",
        "MSSM",
        "business_steward",
        "license_status",
        "slo_on_call",
        "environment_owner.staging",
        "environment_owner.production",
    }
    assert all(
        item.status is JqdltbDecisionStatus.PENDING_BUSINESS_EVIDENCE
        for item in packet.decisions
    )
    assert packet.identity.source_resource_version_id
    assert all(item.evidence is not None for item in packet.decisions)
    assert all(item.owner_ref.startswith("unassigned:") for item in packet.decisions)


def test_packet_builder_is_deterministic_for_explicit_timestamp() -> None:
    left = build_decision_packet(
        packet_id="jqdltb-packet-test-v1",
        created_by="workload:test",
        created_at=datetime(2026, 8, 26, tzinfo=UTC),
    )
    right = build_decision_packet(
        packet_id="jqdltb-packet-test-v1",
        created_by="workload:test",
        created_at=datetime(2026, 8, 26, tzinfo=UTC),
    )
    assert left == right
    assert left.packet_sha256 == canonical_json_fingerprint(
        left.model_dump(mode="json", exclude={"packet_sha256"})
    )


def test_packet_validation_reports_pending_targets_without_authority_state() -> None:
    result = validate_decision_packet(_packet())
    assert result["identity_bound"] is True
    assert result["strategy_ready"] is False
    assert set(result["blockers"]) == {
        "canonical_key",
        "nonpositive_area_policy",
        "area_deviation_policy",
        "SJNF",
        "MSSM",
        "business_steward",
        "license_status",
        "slo_on_call",
        "environment_owner.staging",
        "environment_owner.production",
    }
    assert set(result["transformation_blockers"]) == {
        "canonical_key",
        "nonpositive_area_policy",
        "area_deviation_policy",
        "SJNF",
        "MSSM",
    }
    assert set(result["promotion_blockers"]) == {
        "business_steward",
        "license_status",
        "slo_on_call",
        "environment_owner.staging",
        "environment_owner.production",
    }


def test_readiness_reports_draft_packet_without_strategy_or_authority_state() -> None:
    packet = _packet()
    report = build_readiness_report(decision_packet=packet)

    assert report["decision_packet"] == {
        "packet_id": packet.packet_id,
        "status": "draft",
        "packet_sha256": packet.packet_sha256,
        "validation_sha256": report["decision_packet"]["validation_sha256"],
        "identity_bound": True,
        "strategy_ready": False,
        "transformation_blockers": {
            target: "pending_business_evidence"
            for target in (
                "canonical_key",
                "nonpositive_area_policy",
                "area_deviation_policy",
                "SJNF",
                "MSSM",
            )
        },
        "promotion_blockers": {
            target: "pending_business_evidence"
            for target in (
                "business_steward",
                "license_status",
                "slo_on_call",
                "environment_owner.staging",
                "environment_owner.production",
            )
        },
    }
    assert report["identities"]["decision_packet_sha256"] == packet.packet_sha256
    assert report["transformation_proposal"]["preview"] is None
    assert not report["transformation_proposal"]["ready"]
    assert "decision_packet.status.draft" in report["transformation_proposal"][
        "blockers"
    ]
    assert "decision_packet.status.draft" in report["product_promotion"]["blockers"]
    assert not report["authority_state_created"]


def test_packet_rejects_identity_drift_before_strategy_conversion() -> None:
    payload = json.loads(PACKET_PATH.read_text())
    payload["identity"]["bundle_sha256"] = "f" * 64
    for decision in payload["decisions"]:
        decision["evidence"]["identity"]["bundle_sha256"] = "f" * 64
    payload["packet_sha256"] = canonical_json_fingerprint(
        {key: value for key, value in payload.items() if key != "packet_sha256"}
    )
    with pytest.raises(ValueError, match="identity does not match"):
        validate_decision_packet(JqdltbDecisionPacket.model_validate(payload))
    with pytest.raises(ValueError, match="identity does not match"):
        build_readiness_report(
            decision_packet=JqdltbDecisionPacket.model_validate(payload)
        )


def test_pending_packet_cannot_be_compiled_to_strategy() -> None:
    with pytest.raises(PlatformContractError, match="only a submitted"):
        _packet().to_strategy()


def test_prepare_accepts_packet_input_but_does_not_create_artifacts_for_draft(
    tmp_path: Path,
) -> None:
    proposal = tmp_path / "proposal.json"
    approval = tmp_path / "approval.json"
    with pytest.raises(PlatformContractError, match="only a submitted"):
        main(
            [
                "prepare",
                "--decision-packet",
                str(PACKET_PATH),
                "--proposal-output",
                str(proposal),
                "--approval-output",
                str(approval),
                "--case-id",
                "jqdltb-draft-packet-v1",
                "--requester-subject",
                "workload:test",
                "--request-reason",
                "draft must not create approval",
                "--proposed-at",
                "2026-08-26T00:00:00Z",
                "--requested-at",
                "2026-08-26T01:00:00Z",
                "--expires-at",
                "2026-09-26T00:00:00Z",
            ]
        )
    assert not proposal.exists()
    assert not approval.exists()


def test_submitted_packet_requires_human_submitter_and_submission_time() -> None:
    packet = _packet()
    decisions = []
    for pending in packet.decisions:
        decision = pending.model_dump(mode="json")
        decision.update(
            status="submitted",
            selected_value={
            "canonical_key": "TBBH",
            "nonpositive_area_policy": "quarantine",
            "area_deviation_policy": "preserve_source",
            "SJNF": "2025",
            "MSSM": "01",
            }.get(pending.target, "accepted"),
            owner_ref="human:business-steward",
        )
        if pending.target in {"SJNF", "MSSM"}:
            decision.update(
                source_fields=["PZWH"],
                semantic_contract_ref=f"gda://local-dev/semantic_rule/{pending.target.lower()}-v1",
                semantic_contract_sha256="a" * 64,
                method="extract an approved source field",
            )
        decisions.append(JqdltbDecision.model_validate(decision))
    with pytest.raises(ValueError, match="requires submitter and time"):
        build_jqdltb_decision_packet(
            packet_id="submitted-without-actor-v1",
            identity=packet.identity,
            decisions=tuple(decisions),
            created_by=packet.created_by,
            created_at=packet.created_at,
            status="submitted",
        )


def test_submitted_transformation_choices_can_compile_with_promotion_items_pending() -> None:
    packet = _packet()
    decisions = []
    values = {
        "canonical_key": "TBBH",
        "nonpositive_area_policy": "quarantine",
        "area_deviation_policy": "preserve_source",
        "SJNF": "2025",
        "MSSM": "01",
    }
    for pending in packet.decisions:
        if pending.target in values:
            decision = pending.model_dump(mode="json")
            decision.update(
                status="submitted",
                selected_value=values[pending.target],
                owner_ref="human:business-steward",
            )
            if pending.target in {"SJNF", "MSSM"}:
                decision.update(
                    source_fields=["PZWH"],
                    semantic_contract_ref=f"gda://local-dev/semantic_rule/{pending.target.lower()}-v1",
                    semantic_contract_sha256="a" * 64,
                    method="extract an approved source field",
                )
            decisions.append(JqdltbDecision.model_validate(decision))
        else:
            decisions.append(pending)
    submitted = build_jqdltb_decision_packet(
        packet_id="jqdltb-partial-submission-v1",
        identity=packet.identity,
        decisions=tuple(decisions),
        created_by=packet.created_by,
        created_at=packet.created_at,
        status="submitted",
        submitted_by="human:business-steward",
        submitted_at=datetime(2026, 8, 26, 1, tzinfo=UTC),
    )
    strategy = submitted.to_strategy()
    assert strategy.canonical_key == "TBBH"
    assert strategy.area_deviation_policy.value == "preserve_source"


def test_readiness_previews_submitted_transformation_and_keeps_promotion_blocked(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    packet, manifest_path, semantic_audit_path = _submitted_packet_fixture(
        tmp_path, request
    )

    report = build_readiness_report(
        manifest_path=manifest_path,
        baseline_path=BASELINE_PATH,
        diagnostic_path=DIAGNOSTIC_PATH,
        semantic_audit_path=semantic_audit_path,
        decision_packet=packet,
    )

    assert report["decision_packet"]["status"] == "submitted"
    assert report["decision_packet"]["strategy_ready"] is True
    assert report["decision_packet"]["transformation_blockers"] == {}
    assert set(report["decision_packet"]["promotion_blockers"]) == {
        "business_steward",
        "license_status",
        "slo_on_call",
        "environment_owner.staging",
        "environment_owner.production",
    }
    proposal = report["transformation_proposal"]
    assert proposal["ready"] is True
    assert proposal["preview"]["plan_sha256"] == proposal["preview"][
        "approval_context"
    ]["plan_sha256"]
    assert proposal["next_action"] == "run prepare with this exact decision packet"
    assert report["product_promotion"]["ready"] is False
    assert len(report["product_promotion"]["blockers"]) == len(
        set(report["product_promotion"]["blockers"])
    )
    assert "decision_packet.business_steward.pending_business_evidence" in report[
        "product_promotion"
    ]["blockers"]


def test_readiness_cli_cannot_overwrite_decision_packet() -> None:
    before = PACKET_PATH.read_bytes()
    with pytest.raises(ValueError, match="must not overwrite an input"):
        main(
            [
                "readiness",
                "--decision-packet",
                str(PACKET_PATH),
                "--output",
                str(PACKET_PATH),
            ]
        )
    assert PACKET_PATH.read_bytes() == before
