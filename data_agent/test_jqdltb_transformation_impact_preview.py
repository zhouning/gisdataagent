from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from scripts.preview_chongqing_jqdltb_transformation_impact import build_preview

ROOT = Path(__file__).resolve().parents[1]


def test_real_jqdltb_impact_preview_is_read_only_and_binds_frozen_identity() -> None:
    report = build_preview(evaluated_at=datetime(2026, 8, 26, tzinfo=UTC))

    assert report["mode"] == "aggregate_only_read_only"
    assert report["source_bytes_modified"] is False
    assert report["authority_state_created"] is False
    assert report["layer_artifacts_written"] is False
    assert report["identities"]["bundle_sha256_before"] == (
        "cae2047f6b72127e5eae0651909761c0f06d8c3e0491921dbd806c653ba715c3"
    )
    assert report["identities"]["bundle_sha256_after"] == report["identities"][
        "bundle_sha256_before"
    ]
    assert report["identities"]["diagnostic_sha256"] == (
        "da192c3f443f41cb189c3253473918000acbc8f9c087868e9eb702a4a4520b11"
    )
    assert len(report["matrix"]) == 6
    assert report["identities"]["selected_strategy_sha256"] is None
    assert len({item["scenario_sha256"] for item in report["matrix"]}) == 6

    quarantine_preserve = next(
        item
        for item in report["matrix"]
        if item["policy"]["nonpositive_area_policy"] == "quarantine"
        and item["policy"]["area_deviation_policy"] == "preserve_source"
    )
    assert quarantine_preserve["status"] == "impact_computed"
    assert quarantine_preserve["projection"]["records_quarantined"] == 6
    assert quarantine_preserve["projection"]["records_after_area_policy"] == 1549
    assert quarantine_preserve["semantic_derivations"]["status"] == "pending_approval"
    assert quarantine_preserve["quality"]["promotion_ready"] is False

    quarantine_area = next(
        item
        for item in report["matrix"]
        if item["policy"]["nonpositive_area_policy"] == "quarantine"
        and item["policy"]["area_deviation_policy"] == "quarantine"
    )
    assert quarantine_area["projection"]["records_quarantined"] == 13
    assert quarantine_area["projection"]["records_after_area_policy"] == 1542

    correction = next(
        item
        for item in report["matrix"]
        if item["policy"]["nonpositive_area_policy"] == "business_correction"
    )
    assert correction["status"] == "impact_computed"
    assert "business_correction_resource_version_missing" in correction[
        "policy_input_blockers"
    ]
    assert correction["projection"]["exact"] is False
    assert correction["projection"]["records_after_area_policy"] is None
    assert report["conclusion"]["any_policy_promotable"] is False
