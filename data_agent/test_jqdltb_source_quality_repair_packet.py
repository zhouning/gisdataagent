from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.build_chongqing_jqdltb_source_quality_repair_packet import (
    build_packet,
    validate_packet,
)

ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def _by_target(packet: dict) -> dict[str, dict]:
    return {item["target"]: item for item in packet["decisions"]}


def test_real_repair_candidate_packet_is_pending_read_only_and_aggregate_only() -> None:
    packet = build_packet()
    result = validate_packet(packet)

    assert result["decision_count"] == 10
    assert result["all_decisions_pending"] is True
    assert result["promotion_ready"] is False
    assert packet["privacy"] == {
        "source_values_included": False,
        "feature_ids_included": False,
        "only_aggregate_evidence": True,
    }
    assert packet["side_effects"] == {
        "source_bytes_modified": False,
        "source_values_persisted": False,
        "authority_state_created": False,
        "strategy_created": False,
        "approval_case_created": False,
        "correction_artifact_created": False,
        "layer_artifacts_written": False,
        "data_product_version_created": False,
    }
    assert packet["conclusion"]["ar0_status_unchanged"] == "awaiting_business_approval"
    assert packet["conclusion"]["source_quality_verdict"] == "failed"
    assert all(item["selected_value"] is None for item in packet["decisions"])
    assert all(item["status"] == "pending_business_evidence" for item in packet["decisions"])


def test_packet_exposes_real_policy_impact_without_selecting_a_policy() -> None:
    packet = build_packet()
    decisions = _by_target(packet)

    nonpositive = {
        item["value"]: item
        for item in decisions["nonpositive_area_policy"]["options"]
    }
    assert nonpositive["quarantine"]["effect"] == {
        "records_quarantined": 6,
        "records_after_area_policy": 1549,
    }
    assert nonpositive["business_correction"]["effect"]["projection_exact"] is False
    assert nonpositive["business_correction"]["effect"]["records_quarantined"] is None

    deviation = {
        item["value"]: item
        for item in decisions["area_deviation_policy"]["options"]
    }
    assert deviation["quarantine"]["effect"] == {
        "records_quarantined": 13,
        "records_after_area_policy": 1542,
    }
    assert deviation["use_geometry"]["effect"]["geometry_is_canonical_without_rule"] is False
    assert decisions["canonical_key"]["selected_value"] is None
    for target in ("SJNF", "MSSM"):
        deferred = next(
            option
            for option in decisions[target]["options"]
            if option["value"] == "quarantine_until_authority_exists"
        )
        assert deferred["closes_blockers_when_accepted"] == []
        assert "promotion_not_permitted" in deferred[
            "blockers_remaining_after_acceptance"
        ]


def test_packet_names_which_blocker_each_decision_can_close() -> None:
    packet = build_packet()
    decisions = _by_target(packet)

    for target, decision in decisions.items():
        blocker = f"decision_packet.{target}.pending_business_evidence"
        assert decision["gating_blocker"] == blocker
        assert any(
            blocker in option["closes_blockers_when_accepted"]
            for option in decision["options"]
            if option["value"] not in {"reject_and_rediagnose"}
        ) or any(
            "promotion_not_permitted"
            in option["blockers_remaining_after_acceptance"]
            for option in decision["options"]
        )
        assert decision["fail_closed_if_missing"] is True


def test_packet_rejects_evidence_identity_drift_before_output(tmp_path: Path) -> None:
    diagnostic = json.loads(
        (
            ROOT
            / "benchmarks/standard_mapping_chongqing_v0_1/source_quality_repair_diagnostic.json"
        ).read_text(encoding="utf-8")
    )
    diagnostic["source"]["bundle_sha256"] = "0" * 64
    from data_agent.platform_contracts import canonical_json_fingerprint

    diagnostic.pop("diagnostic_sha256")
    diagnostic["diagnostic_sha256"] = canonical_json_fingerprint(diagnostic)
    path = _write_json(tmp_path / "drifted-diagnostic.json", diagnostic)

    with pytest.raises(ValueError, match="baseline and diagnostic identity differ"):
        build_packet(diagnostic_path=path)


def test_packet_rejects_preview_that_claims_a_side_effect(tmp_path: Path) -> None:
    preview = json.loads(
        (
            ROOT / "docs/reports/jqdltb_transformation_impact_preview_2026-08-26.json"
        ).read_text(encoding="utf-8")
    )
    preview["authority_state_created"] = True
    from data_agent.platform_contracts import canonical_json_fingerprint

    preview.pop("preview_sha256")
    preview["preview_sha256"] = canonical_json_fingerprint(preview)
    path = _write_json(tmp_path / "side-effect-preview.json", preview)

    with pytest.raises(ValueError, match="created authority state"):
        build_packet(impact_preview_path=path)


def test_packet_validator_rejects_automatic_selection() -> None:
    packet = build_packet()
    packet["decisions"][0]["selected_value"] = "TBBH"
    from data_agent.platform_contracts import canonical_json_fingerprint

    packet.pop("packet_sha256")
    packet["packet_sha256"] = canonical_json_fingerprint(packet)
    with pytest.raises(ValueError, match="must not choose a business value"):
        validate_packet(packet)


def test_existing_packet_cli_revalidates_all_evidence() -> None:
    result = subprocess.run(
        [
            str(ROOT / ".venv/bin/python"),
            str(
                ROOT
                / "scripts/build_chongqing_jqdltb_source_quality_repair_packet.py"
            ),
            "--validate",
            str(
                ROOT
                / "docs/reports/"
                "jqdltb_source_quality_repair_candidate_packet_2026-08-30.json"
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    assert json.loads(result.stdout)["decision_count"] == 10
