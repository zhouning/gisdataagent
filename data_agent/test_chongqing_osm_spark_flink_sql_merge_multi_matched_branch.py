from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_merge_multi_matched_branch import (
    SPARK_SOURCE,
    build_sql_merge_multi_matched_branch_plan,
)


def test_multi_matched_branch_plan_is_deterministic_and_has_delete_update_sources() -> None:
    first = build_sql_merge_multi_matched_branch_plan(DEFAULT_SOURCE)
    second = build_sql_merge_multi_matched_branch_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert first["delete_source_row"]["action"] == "delete"
    assert first["update_source_row"]["action"] == "update"
    assert {row["action"] for row in first["matched_source_rows"]} == {"delete", "update"}
    assert len({row["road_id"] for row in first["matched_source_rows"]}) == 2
    assert len(first["merge_source_rows"]) == 2


def test_multi_matched_branch_source_uses_ordered_delete_and_update_branches() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")

    assert "MERGE INTO" in source
    assert "WHEN MATCHED AND source.action = 'delete' THEN DELETE" in source
    assert "WHEN MATCHED THEN UPDATE SET" in source
    assert "WHEN NOT MATCHED THEN INSERT" not in source
    assert "overwritePartitions" not in source


def test_multi_matched_branch_final_state_deletes_one_and_updates_one() -> None:
    plan = build_sql_merge_multi_matched_branch_plan(DEFAULT_SOURCE)
    delete_source = plan["delete_source_row"]
    update_source = plan["update_source_row"]
    delete_rows = [
        row for row in plan["final_merge_rows"] if row["road_id"] == delete_source["road_id"]
    ]
    assert [row["revision"] for row in delete_rows] == [1]
    updated = [
        row
        for row in plan["final_merge_rows"]
        if row["commit_token"] == update_source["commit_token"]
    ]
    assert len(updated) == 1
    assert updated[0]["revision"] == update_source["result_revision"]
    assert len(plan["final_merge_rows"]) == 3
