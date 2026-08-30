"""Focused contracts for Spark/Flink overwrite conflict isolation."""

from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_overwrite_conflict import (
    build_overwrite_conflict_plan,
)
from scripts.spark_chongqing_osm_iceberg_overwrite_conflict import (
    classify_conflict_error,
)


def test_overwrite_conflict_plan_is_deterministic_and_preserves_flink_row() -> None:
    first = build_overwrite_conflict_plan(DEFAULT_SOURCE)
    second = build_overwrite_conflict_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert len(first["baseline_rows"]) == 3
    assert len(first["stale_overwrite_rows"]) == 3
    assert len(first["after_flink_rows"]) == 4
    assert len(first["final_rows"]) == 4
    assert first["stale_overwrite_content_sha256"] != first["final_content_sha256"]
    assert any(row["commit_token"] == first["flink_commit_token"] for row in first["final_rows"])


def test_overwrite_conflict_plan_updates_one_baseline_row_exactly_once() -> None:
    plan = build_overwrite_conflict_plan(DEFAULT_SOURCE)
    target = plan["target_road_id"]
    baseline = next(row for row in plan["baseline_rows"] if row["road_id"] == target)
    final = next(row for row in plan["final_rows"] if row["road_id"] == target)

    assert final["revision"] == baseline["revision"] + 1
    assert final["writer_engine"] == "spark-3.5-overwrite"
    assert final["commit_token"] == plan["spark_commit_token"]
    assert sum(row["commit_token"] == plan["spark_commit_token"] for row in plan["final_rows"]) == 1


def test_conflict_classifier_identifies_provider_validation_without_message_leak() -> None:
    conflict = RuntimeError(
        "org.apache.iceberg.exceptions.ValidationException: Cannot commit, "
        "found new data files for replaced partition"
    )
    unrelated = RuntimeError("org.apache.iceberg.exceptions.CommitFailedException")

    classified = classify_conflict_error(conflict)
    assert classified["provider_exception"] == "ValidationException"
    assert classified["is_iceberg_validation_failure"] is True
    assert "Cannot commit" in classified["matched_markers"]
    assert classified["message_sha256"]
    assert classify_conflict_error(unrelated)["is_iceberg_validation_failure"] is False
