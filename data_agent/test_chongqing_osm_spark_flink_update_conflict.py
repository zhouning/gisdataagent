"""Focused contracts for partitioned Spark/Flink update conflict isolation."""

from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_update_conflict import (
    FLINK_COMMITTED_RE,
    FLINK_SOURCE,
    FLINK_STARTED_RE,
    build_update_conflict_plan,
)


def test_update_conflict_plan_is_real_deterministic_and_partition_scoped() -> None:
    first = build_update_conflict_plan(DEFAULT_SOURCE)
    second = build_update_conflict_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert len(first["baseline_rows"]) == 3
    assert len(first["after_flink_rows"]) == 4
    assert len(first["final_rows"]) == 3
    assert first["flink_row"]["road_id"] == first["target_road_id"]
    assert first["fresh_update_row"]["road_id"] == first["target_road_id"]


def test_fresh_update_incorporates_flink_payload_and_advances_revision() -> None:
    plan = build_update_conflict_plan(DEFAULT_SOURCE)
    flink = plan["flink_row"]
    final = plan["fresh_update_row"]

    assert flink["revision"] == 2
    assert final["revision"] == 3
    assert final["road_name_base64"] == flink["road_name_base64"]
    assert final["geometry_sha256"] == flink["geometry_sha256"]
    assert final["writer_engine"] == "spark-3.5-update"
    assert final["commit_token"] == plan["spark_update_token"]


def test_stale_update_differs_from_fresh_retry_and_tokens_are_unique() -> None:
    plan = build_update_conflict_plan(DEFAULT_SOURCE)

    assert plan["stale_update_content_sha256"] != plan["final_content_sha256"]
    assert plan["spark_update_token"] != plan["flink_commit_token"]
    assert sum(row["commit_token"] == plan["spark_update_token"] for row in plan["final_rows"]) == 1


def test_partition_append_job_has_one_query_lifecycle() -> None:
    source = FLINK_SOURCE.read_text(encoding="utf-8")

    assert "SELECT COUNT(*)" not in source
    assert source.count('return "INSERT INTO "') == 1
    assert "classloader.check-leaked-classloader" not in source


def test_partition_append_markers_bind_row_revision_and_token() -> None:
    token = "a" * 64
    started = FLINK_STARTED_RE.fullmatch(
        f"GDA_PARTITION_FLINK_STARTED road_id=102262017 revision=2 token={token}"
    )
    committed = FLINK_COMMITTED_RE.fullmatch(
        f"GDA_PARTITION_FLINK_COMMITTED road_id=102262017 revision=2 token={token}"
    )

    assert started and started.groups() == ("102262017", "2", token)
    assert committed and committed.groups() == ("102262017", "2", token)
    assert not FLINK_COMMITTED_RE.fullmatch(
        "GDA_PARTITION_FLINK_COMMITTED road_id=102262017 revision=2 token=unsafe"
    )
