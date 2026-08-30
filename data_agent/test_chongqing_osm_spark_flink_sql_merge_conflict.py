from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_merge_conflict import (
    SPARK_SOURCE,
    build_sql_merge_conflict_plan,
)


def test_sql_merge_plan_is_deterministic_and_binds_stale_and_fresh_revisions() -> None:
    first = build_sql_merge_conflict_plan(DEFAULT_SOURCE)
    second = build_sql_merge_conflict_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert first["merge_source_stale"]["expected_revision"] == 1
    assert first["merge_source_stale"]["new_revision"] == 2
    assert first["merge_source_fresh"]["expected_revision"] == 2
    assert first["merge_source_fresh"]["new_revision"] == 3
    assert first["sql_merge_stale_token"] != first["sql_merge_fresh_token"]
    assert any(row["writer_engine"] == "spark-sql-merge" for row in first["final_merge_rows"])


def test_sql_merge_source_uses_real_iceberg_merge_and_barrier_contract() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")

    assert "MERGE INTO" in source
    assert "WHEN MATCHED THEN UPDATE SET" in source
    assert "target.revision = source.new_revision" in source
    assert "gda.spark_sql_merge_conflict_ready.v1" in source
    assert "validateNoConflictingData" not in source
    assert "overwritePartitions" not in source


def test_sql_merge_plan_keeps_flink_row_and_baseline_for_fresh_retry() -> None:
    plan = build_sql_merge_conflict_plan(DEFAULT_SOURCE)
    target_id = plan["target_road_id"]
    target_rows = [row for row in plan["final_merge_rows"] if row["road_id"] == target_id]

    assert [row["revision"] for row in target_rows] == [1, 3]
    assert target_rows[-1]["road_name_base64"] == plan["flink_row"]["road_name_base64"]
    assert target_rows[-1]["commit_token"] == plan["sql_merge_fresh_token"]
    assert len({row["road_id"] for row in plan["final_merge_rows"]}) == 3
