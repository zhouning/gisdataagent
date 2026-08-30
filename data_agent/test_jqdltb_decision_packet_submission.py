from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_agent.platform_contracts import JqdltbDecisionPacketStatus
from scripts.manage_chongqing_jqdltb_transformation_approval import (
    main,
)

ROOT = Path(__file__).resolve().parents[1]
DRAFT = ROOT / "docs/reports/jqdltb_business_decision_packet_2026-08-26.json"


def _write_decisions(path: Path, decisions: dict[str, dict[str, object]]) -> None:
    path.write_text(
        json.dumps({"decisions": decisions}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _cli_args(decisions: Path, output: Path) -> list[str]:
    return [
        "submit-decision-packet",
        "--draft",
        str(DRAFT),
        "--decisions",
        str(decisions),
        "--submitted-by",
        "human:business-steward",
        "--submitted-at",
        "2026-08-30T12:00:00Z",
        "--output",
        str(output),
    ]


def _update_cli_args(
    base: Path,
    decisions: Path,
    output: Path,
    *,
    submitted_at: str = "2026-08-30T13:00:00Z",
) -> list[str]:
    return [
        "update-submitted-decision-packet",
        "--base",
        str(base),
        "--decisions",
        str(decisions),
        "--submitted-by",
        "human:business-steward",
        "--submitted-at",
        submitted_at,
        "--output",
        str(output),
    ]


def test_submit_cli_preserves_omitted_targets_as_pending(tmp_path: Path) -> None:
    decisions_path = tmp_path / "decisions.json"
    output = tmp_path / "submitted.json"
    _write_decisions(
        decisions_path,
        {
            "canonical_key": {
                "selected_value": "TBBH",
                "owner_ref": "human:business-steward",
            }
        },
    )

    main(_cli_args(decisions_path, output))
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == JqdltbDecisionPacketStatus.SUBMITTED.value
    by_target = {item["target"]: item for item in payload["decisions"]}
    assert by_target["canonical_key"]["status"] == "submitted"
    assert by_target["canonical_key"]["selected_value"] == "TBBH"
    assert by_target["SJNF"]["status"] == "pending_business_evidence"


def test_submit_records_explicit_semantic_quarantine_as_deferred(tmp_path: Path) -> None:
    decisions_path = tmp_path / "decisions.json"
    output = tmp_path / "submitted.json"
    _write_decisions(
        decisions_path,
        {
            "SJNF": {
                "selected_value": "quarantine_until_authority_exists",
                "owner_ref": "human:business-steward",
            },
            "MSSM": {
                "selected_value": "quarantine_until_authority_exists",
                "owner_ref": "human:business-steward",
            },
        },
    )

    main(_cli_args(decisions_path, output))
    payload = json.loads(output.read_text(encoding="utf-8"))
    by_target = {item["target"]: item for item in payload["decisions"]}
    assert by_target["SJNF"]["status"] == "deferred"
    assert by_target["MSSM"]["status"] == "deferred"
    assert by_target["SJNF"]["selected_value"] == "quarantine_until_authority_exists"


def test_submit_records_correction_choice_as_deferred_until_artifact_arrives(
    tmp_path: Path,
) -> None:
    decisions_path = tmp_path / "decisions.json"
    output = tmp_path / "submitted.json"
    _write_decisions(
        decisions_path,
        {
            "nonpositive_area_policy": {
                "selected_value": "business_correction",
                "owner_ref": "human:business-steward",
            }
        },
    )

    main(_cli_args(decisions_path, output))
    payload = json.loads(output.read_text(encoding="utf-8"))
    decision = next(
        item for item in payload["decisions"] if item["target"] == "nonpositive_area_policy"
    )
    assert decision["status"] == "deferred"
    assert decision["selected_value"] == "business_correction"
    assert decision["selected_resource_version_id"] is None


def test_correction_deferred_target_can_be_resolved_incrementally(tmp_path: Path) -> None:
    first_decisions = tmp_path / "first-decisions.json"
    first_output = tmp_path / "first-submitted.json"
    _write_decisions(
        first_decisions,
        {
            "nonpositive_area_policy": {
                "selected_value": "business_correction",
                "owner_ref": "human:business-steward",
            }
        },
    )
    main(_cli_args(first_decisions, first_output))

    second_decisions = tmp_path / "second-decisions.json"
    second_output = tmp_path / "second-submitted.json"
    _write_decisions(
        second_decisions,
        {
            "nonpositive_area_policy": {
                "selected_value": "business_correction",
                "owner_ref": "human:business-steward",
                "selected_resource_version_id": "d1000000-0000-4000-8000-000000000061",
                "selected_artifact_sha256": "a" * 64,
            }
        },
    )

    main(_update_cli_args(first_output, second_decisions, second_output))
    payload = json.loads(second_output.read_text(encoding="utf-8"))
    decision = next(
        item for item in payload["decisions"] if item["target"] == "nonpositive_area_policy"
    )
    assert decision["status"] == "submitted"
    assert decision["selected_resource_version_id"] == "d1000000-0000-4000-8000-000000000061"


def test_submit_rejects_unknown_target_before_writing(tmp_path: Path) -> None:
    decisions_path = tmp_path / "decisions.json"
    output = tmp_path / "submitted.json"
    _write_decisions(
        decisions_path,
        {"unexpected": {"selected_value": "x", "owner_ref": "human:test"}},
    )

    with pytest.raises(ValueError, match="unknown targets"):
        main(_cli_args(decisions_path, output))
    assert not output.exists()


def test_submit_rejects_unsupported_patch_field_before_writing(tmp_path: Path) -> None:
    decisions_path = tmp_path / "decisions.json"
    output = tmp_path / "submitted.json"
    _write_decisions(
        decisions_path,
        {
            "canonical_key": {
                "selected_value": "TBBH",
                "owner_ref": "human:business-steward",
                "evidence": "must-not-be-replaced",
            }
        },
    )

    with pytest.raises(ValueError, match="unsupported fields"):
        main(_cli_args(decisions_path, output))
    assert not output.exists()


def test_submit_rejects_complete_transformation_without_semantic_acceptance(
    tmp_path: Path,
) -> None:
    decisions_path = tmp_path / "decisions.json"
    output = tmp_path / "submitted.json"
    decisions = {
        "canonical_key": {
            "selected_value": "TBBH",
            "owner_ref": "human:business-steward",
        },
        "nonpositive_area_policy": {
            "selected_value": "quarantine",
            "owner_ref": "human:business-steward",
        },
        "area_deviation_policy": {
            "selected_value": "preserve_source",
            "owner_ref": "human:business-steward",
        },
    }
    for target, field in (("SJNF", "PZWH"), ("MSSM", "JQDLMC")):
        decisions[target] = {
            "selected_value": "2025" if target == "SJNF" else "01",
            "owner_ref": "human:business-steward",
            "source_fields": [field],
            "semantic_contract_ref": f"gda://local-dev/semantic_rule/{target.lower()}-v1",
            "semantic_contract_sha256": "a" * 64,
            "method": "extract the proposed source field",
        }
    _write_decisions(decisions_path, decisions)

    with pytest.raises(ValueError, match="semantically rejected source fields"):
        main(_cli_args(decisions_path, output))
    assert not output.exists()


def test_incremental_update_preserves_previous_submissions(tmp_path: Path) -> None:
    first_decisions = tmp_path / "first-decisions.json"
    first_output = tmp_path / "first-submitted.json"
    _write_decisions(
        first_decisions,
        {
            "canonical_key": {
                "selected_value": "TBBH",
                "owner_ref": "human:business-steward",
            }
        },
    )
    main(_cli_args(first_decisions, first_output))

    second_decisions = tmp_path / "second-decisions.json"
    second_output = tmp_path / "second-submitted.json"
    _write_decisions(
        second_decisions,
        {
            "area_deviation_policy": {
                "selected_value": "preserve_source",
                "owner_ref": "human:business-steward",
            }
        },
    )
    main(_update_cli_args(first_output, second_decisions, second_output))

    payload = json.loads(second_output.read_text(encoding="utf-8"))
    by_target = {item["target"]: item for item in payload["decisions"]}
    assert by_target["canonical_key"]["status"] == "submitted"
    assert by_target["canonical_key"]["selected_value"] == "TBBH"
    assert by_target["area_deviation_policy"]["status"] == "submitted"
    assert by_target["area_deviation_policy"]["selected_value"] == "preserve_source"


def test_incremental_update_rejects_overwriting_submitted_target(tmp_path: Path) -> None:
    first_decisions = tmp_path / "first-decisions.json"
    first_output = tmp_path / "first-submitted.json"
    _write_decisions(
        first_decisions,
        {
            "canonical_key": {
                "selected_value": "TBBH",
                "owner_ref": "human:business-steward",
            }
        },
    )
    main(_cli_args(first_decisions, first_output))

    overwrite = tmp_path / "overwrite.json"
    output = tmp_path / "overwrite-output.json"
    _write_decisions(
        overwrite,
        {
            "canonical_key": {
                "selected_value": "TBBH",
                "owner_ref": "human:other",
            }
        },
    )
    with pytest.raises(ValueError, match="cannot overwrite submitted target"):
        main(_update_cli_args(first_output, overwrite, output))
    assert not output.exists()


def test_incremental_update_requires_monotonic_submission_time(tmp_path: Path) -> None:
    first_decisions = tmp_path / "first-decisions.json"
    first_output = tmp_path / "first-submitted.json"
    _write_decisions(
        first_decisions,
        {
            "canonical_key": {
                "selected_value": "TBBH",
                "owner_ref": "human:business-steward",
            }
        },
    )
    main(_cli_args(first_decisions, first_output))

    second_decisions = tmp_path / "second-decisions.json"
    output = tmp_path / "second-submitted.json"
    _write_decisions(
        second_decisions,
        {
            "area_deviation_policy": {
                "selected_value": "preserve_source",
                "owner_ref": "human:business-steward",
            }
        },
    )
    with pytest.raises(ValueError, match="later submission time"):
        main(
            _update_cli_args(
                first_output,
                second_decisions,
                output,
                submitted_at="2026-08-30T12:00:00Z",
            )
        )
    assert not output.exists()
