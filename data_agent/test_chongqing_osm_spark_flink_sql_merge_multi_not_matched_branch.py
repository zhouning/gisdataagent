from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_merge_multi_not_matched_branch import (
    SPARK_SOURCE,
    build_sql_merge_multi_not_matched_branch_plan,
)


def test_multi_not_matched_plan_is_deterministic_and_has_two_insert_sources() -> None:
    first = build_sql_merge_multi_not_matched_branch_plan(DEFAULT_SOURCE)
    second = build_sql_merge_multi_not_matched_branch_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert first["priority_insert_source_row"]["action"] == "insert_priority"
    assert first["default_insert_source_row"]["action"] == "insert_default"
    assert first["priority_insert_source_row"]["expected_revision"] == -1
    assert first["default_insert_source_row"]["expected_revision"] == -1
    baseline_ids = {row["road_id"] for row in first["baseline_rows"]}
    assert first["priority_inserted_road_id"] not in baseline_ids
    assert first["default_inserted_road_id"] not in baseline_ids
    assert len(first["merge_source_rows"]) == 2


def test_multi_not_matched_source_uses_both_real_sql_merge_branches() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")

    assert "MERGE INTO" in source
    assert "WHEN NOT MATCHED AND source.action = 'insert_priority' THEN INSERT" in source
    assert "WHEN NOT MATCHED THEN INSERT" in source
    assert 'StructField("action", StringType(), False)' in source
    assert "overwritePartitions" not in source


def test_multi_not_matched_final_state_preserves_flink_row_and_inserts_both_roads() -> None:
    plan = build_sql_merge_multi_not_matched_branch_plan(DEFAULT_SOURCE)
    assert plan["final_merge_rows"][: len(plan["after_flink_rows"])] != []
    assert list(plan["final_merge_rows"]).count(plan["flink_row"]) == 1
    priority_rows = [
        row
        for row in plan["final_merge_rows"]
        if row["road_id"] == plan["priority_inserted_road_id"]
    ]
    default_rows = [
        row
        for row in plan["final_merge_rows"]
        if row["road_id"] == plan["default_inserted_road_id"]
    ]
    assert len(priority_rows) == 1
    assert len(default_rows) == 1
    assert priority_rows[0]["commit_token"] == plan["sql_merge_priority_insert_token"]
    assert default_rows[0]["commit_token"] == plan["sql_merge_default_insert_token"]
    assert len(plan["final_merge_rows"]) == 6
