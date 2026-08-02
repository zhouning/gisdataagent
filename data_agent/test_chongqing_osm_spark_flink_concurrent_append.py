"""Focused contracts for the Spark/Flink concurrent append acceptance."""

from __future__ import annotations

from scripts.certify_chongqing_osm_spark_flink_concurrent_append import (
    DEFAULT_SOURCE,
    build_concurrent_append_plan,
)


def test_concurrent_append_plan_is_real_deterministic_and_disjoint() -> None:
    first = build_concurrent_append_plan(DEFAULT_SOURCE)
    second = build_concurrent_append_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert len(first["baseline_rows"]) == 3
    assert len(first["after_flink_rows"]) == 4
    assert len(first["final_rows"]) == 5
    assert len({row["road_id"] for row in first["final_rows"]}) == 5
    assert first["flink_commit_token"] != first["spark_commit_token"]


def test_concurrent_rows_bind_engine_and_commit_token_exactly_once() -> None:
    plan = build_concurrent_append_plan(DEFAULT_SOURCE)

    assert plan["flink_row"]["writer_engine"] == "flink-1.19.3"
    assert plan["flink_row"]["commit_token"] == plan["flink_commit_token"]
    assert plan["spark_row"]["writer_engine"] == "spark-3.5"
    assert plan["spark_row"]["commit_token"] == plan["spark_commit_token"]
    assert sum(row["commit_token"] == plan["flink_commit_token"] for row in plan["final_rows"]) == 1
    assert sum(row["commit_token"] == plan["spark_commit_token"] for row in plan["final_rows"]) == 1
