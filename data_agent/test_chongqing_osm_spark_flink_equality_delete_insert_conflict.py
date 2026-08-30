"""Focused contracts for equality-delete/insert conflict isolation."""

from __future__ import annotations

from pathlib import Path

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_equality_delete_insert_conflict import (
    INSERT_COMMITTED_RE,
    INSERT_JAVA_SOURCE,
    INSERT_STARTED_RE,
    SPARK_SOURCE,
    build_equality_delete_insert_conflict_plan,
    parse_flink_insert_markers,
)
from scripts.spark_chongqing_osm_iceberg_equality_delete_insert_conflict import (
    BARRIER_RE,
)


def test_equality_delete_insert_plan_is_real_deterministic_and_targeted() -> None:
    first = build_equality_delete_insert_conflict_plan(DEFAULT_SOURCE)
    second = build_equality_delete_insert_conflict_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert len(first["baseline_rows"]) == 3
    assert len(first["after_insert_rows"]) == 4
    assert first["final_rows"] == first["baseline_rows"]
    assert first["insert_row"]["road_id"] == first["target_road_id"]
    assert all(row["road_id"] != first["target_road_id"] for row in first["baseline_rows"])


def test_insert_authorization_and_delete_tokens_are_distinct() -> None:
    plan = build_equality_delete_insert_conflict_plan(DEFAULT_SOURCE)

    assert len(
        {
            plan["insert_commit_token"],
            plan["delete_authorization_token"],
            plan["delete_commit_token"],
        }
    ) == 3
    assert plan["baseline_content_sha256"] == plan["final_content_sha256"]
    assert plan["after_insert_content_sha256"] != plan["final_content_sha256"]


def test_single_insert_job_has_one_provider_query() -> None:
    source = INSERT_JAVA_SOURCE.read_text(encoding="utf-8")

    assert source.count("TableResult insertion = tableEnvironment.executeSql(") == 1
    assert "SELECT COUNT(*)" not in source
    assert "classloader.check-leaked-classloader" not in source


def test_insert_race_baseline_forces_append_semantics() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")

    assert "'write.upsert.enabled'='false'" in source
    assert "upsert_disabled_for_append_insert" in source


def test_single_insert_markers_bind_key_and_token() -> None:
    plan = build_equality_delete_insert_conflict_plan(DEFAULT_SOURCE)
    output = (
        "GDA_SINGLE_INSERT_FLINK_STARTED "
        f"road_id={plan['target_road_id']} token={plan['insert_commit_token']}\n"
        "GDA_SINGLE_INSERT_FLINK_COMMITTED "
        f"road_id={plan['target_road_id']} token={plan['insert_commit_token']}\n"
    )

    assert INSERT_STARTED_RE.search(output)
    assert INSERT_COMMITTED_RE.search(output)
    assert parse_flink_insert_markers(output, plan)["status"] == "passed"
    assert parse_flink_insert_markers(output.replace("COMMITTED", "FAILED"), plan)[
        "status"
    ] == "failed"


def test_equality_insert_conflict_barriers_are_fail_closed() -> None:
    safe = Path(
        "/workspace/.tmp/source-sync-certification/"
        "flink_iceberg_equality_insert_conflict_0123456789/spark-ready.json"
    )

    assert BARRIER_RE.fullmatch(safe.as_posix())
    assert not BARRIER_RE.fullmatch(
        "/workspace/.tmp/source-sync-certification/"
        "flink_iceberg_equality_delete_conflict_0123456789/spark-ready.json"
    )
    assert not BARRIER_RE.fullmatch("/workspace/spark-ready.json")
