from __future__ import annotations

from pathlib import Path

from scripts.certify_chongqing_osm_spark_flink_sql_merge_auto_retry import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_merge_multiple_successful_retries import (
    build_sql_merge_multiple_successful_retries_plan,
)


def test_cross_process_plan_has_distinct_revision_3_and_revision_4_workers() -> None:
    plan = build_sql_merge_multiple_successful_retries_plan(DEFAULT_SOURCE)
    baseline_target_rows = [
        row for row in plan["after_flink_rows"] if row["road_id"] == plan["target_road_id"]
    ]
    assert [row["revision"] for row in baseline_target_rows] == [1, 2]
    assert plan["merge_source_fresh"]["new_revision"] == 3
    assert plan["successful_retry_sequence"][0]["expected_revision"] == 3
    assert plan["successful_retry_sequence"][0]["new_revision"] == 4


def test_cross_process_worker_entrypoint_declares_both_phases() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "spark_chongqing_osm_iceberg_sql_merge_cross_process_successful_retry.py"
    ).read_text(encoding="utf-8")
    assert "spark_chongqing_osm_iceberg_sql_merge_auto_retry" in source
    assert "cross-process successful SQL MERGE retry" in source
