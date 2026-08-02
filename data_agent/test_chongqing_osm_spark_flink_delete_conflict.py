"""Focused contracts for Spark/Flink key-delete conflict isolation."""

from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_delete_conflict import (
    build_delete_conflict_plan,
)


def test_delete_conflict_plan_is_real_deterministic_and_key_scoped() -> None:
    first = build_delete_conflict_plan(DEFAULT_SOURCE)
    second = build_delete_conflict_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert len(first["baseline_rows"]) == 3
    assert len(first["after_flink_rows"]) == 4
    assert len(first["final_rows"]) == 3
    assert all(row["road_id"] != first["target_road_id"] for row in first["baseline_rows"])
    assert first["flink_row"]["road_id"] == first["target_road_id"]


def test_fresh_delete_result_preserves_every_non_target_baseline_row() -> None:
    plan = build_delete_conflict_plan(DEFAULT_SOURCE)

    assert plan["final_rows"] == plan["baseline_rows"]
    assert plan["final_content_sha256"] == plan["baseline_content_sha256"]
    assert plan["after_flink_content_sha256"] != plan["final_content_sha256"]
    assert (
        sum(row["commit_token"] == plan["flink_commit_token"] for row in plan["after_flink_rows"])
        == 1
    )


def test_delete_and_flink_tokens_are_distinct() -> None:
    plan = build_delete_conflict_plan(DEFAULT_SOURCE)

    assert plan["spark_delete_token"] != plan["flink_commit_token"]
    assert len(plan["spark_delete_token"]) == 64
