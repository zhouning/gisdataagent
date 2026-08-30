"""Focused contracts for Spark/Flink equality-delete conflict isolation."""

from __future__ import annotations

from pathlib import Path

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_equality_delete_conflict import (
    build_equality_delete_conflict_plan,
)
from scripts.spark_chongqing_osm_iceberg_equality_delete_conflict import BARRIER_RE


def test_equality_delete_conflict_plan_is_real_deterministic_and_same_key() -> None:
    first = build_equality_delete_conflict_plan(DEFAULT_SOURCE)
    second = build_equality_delete_conflict_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert len(first["baseline_rows"]) == 3
    assert len(first["after_flink_rows"]) == 2
    assert first["delete_row"]["road_id"] == first["target_road_id"]
    assert first["stale_update_row"]["road_id"] == first["target_road_id"]
    assert first["spark_update_token"] != first["flink_commit_token"]


def test_equality_delete_conflict_uses_delete_wins_reconciliation() -> None:
    plan = build_equality_delete_conflict_plan(DEFAULT_SOURCE)

    assert plan["reconciliation_policy"] == "delete-wins-target-absent-no-resurrection"
    assert all(
        row["road_id"] != plan["target_road_id"] for row in plan["after_flink_rows"]
    )
    assert plan["stale_update_content_sha256"] != plan["after_flink_content_sha256"]


def test_equality_delete_conflict_barriers_are_fail_closed() -> None:
    safe = Path(
        "/workspace/.tmp/source-sync-certification/"
        "flink_iceberg_equality_delete_conflict_0123456789/spark-ready.json"
    )

    assert BARRIER_RE.fullmatch(safe.as_posix())
    assert not BARRIER_RE.fullmatch(
        "/workspace/.tmp/source-sync-certification/"
        "flink_iceberg_equality_delete_0123456789/spark-ready.json"
    )
    assert not BARRIER_RE.fullmatch("/workspace/spark-ready.json")


def test_spark_intent_validates_conflicting_deletes() -> None:
    source = (
        Path(__file__).parents[1]
        / "scripts/spark_chongqing_osm_iceberg_equality_delete_conflict.py"
    ).read_text(encoding="utf-8")

    assert ".validateFromSnapshot(" in source
    assert ".conflictDetectionFilter(target_filter)" in source
    assert ".validateNoConflictingDeletes()" in source
    assert "delete-wins-target-absent-no-resurrection" in source
