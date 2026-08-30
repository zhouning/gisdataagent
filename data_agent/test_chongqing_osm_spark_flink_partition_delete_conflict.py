"""Focused contracts for partitioned Spark/Flink delete conflict isolation."""

from __future__ import annotations

from pathlib import Path

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_partition_delete_conflict import (
    build_partition_delete_conflict_plan,
)
from scripts.spark_chongqing_osm_iceberg_partition_delete_conflict import BARRIER_RE


def test_partition_delete_plan_is_real_deterministic_and_targeted() -> None:
    first = build_partition_delete_conflict_plan(DEFAULT_SOURCE)
    second = build_partition_delete_conflict_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert len(first["baseline_rows"]) == 3
    assert len(first["after_flink_rows"]) == 4
    assert len(first["final_rows"]) == 2
    assert first["flink_row"]["road_id"] == first["target_road_id"]
    assert any(row["road_id"] == first["target_road_id"] for row in first["baseline_rows"])


def test_partition_delete_removes_both_target_revisions_only() -> None:
    plan = build_partition_delete_conflict_plan(DEFAULT_SOURCE)
    target = plan["target_road_id"]
    target_revisions = sorted(
        row["revision"] for row in plan["after_flink_rows"] if row["road_id"] == target
    )

    assert target_revisions == [1, 2]
    assert all(row["road_id"] != target for row in plan["final_rows"])
    assert plan["final_rows"] == [row for row in plan["baseline_rows"] if row["road_id"] != target]
    assert plan["final_content_sha256"] != plan["baseline_content_sha256"]


def test_partition_delete_tokens_are_distinct_and_stable() -> None:
    plan = build_partition_delete_conflict_plan(DEFAULT_SOURCE)

    assert plan["spark_delete_token"] != plan["flink_commit_token"]
    assert len(plan["spark_delete_token"]) == 64
    assert (
        sum(row["commit_token"] == plan["flink_commit_token"] for row in plan["after_flink_rows"])
        == 1
    )


def test_partition_delete_barrier_scope_is_fail_closed() -> None:
    safe = Path(
        "/workspace/.tmp/source-sync-certification/"
        "flink_iceberg_partition_delete_conflict_0123456789/spark-ready.json"
    )

    assert BARRIER_RE.fullmatch(safe.as_posix())
    assert not BARRIER_RE.fullmatch(
        "/workspace/.tmp/source-sync-certification/"
        "flink_iceberg_delete_conflict_0123456789/spark-ready.json"
    )
    assert not BARRIER_RE.fullmatch("/workspace/spark-ready.json")
