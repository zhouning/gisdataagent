from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_merge_multi_branch import (
    SPARK_SOURCE,
    build_sql_merge_multi_branch_plan,
)


def test_multi_branch_plan_is_deterministic_and_has_matched_and_insert_sources() -> None:
    first = build_sql_merge_multi_branch_plan(DEFAULT_SOURCE)
    second = build_sql_merge_multi_branch_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert first["matched_source_row"]["expected_revision"] == 2
    assert first["matched_source_row"]["result_revision"] == 3
    assert first["insert_source_row"]["expected_revision"] == -1
    assert first["inserted_road_id"] not in {row["road_id"] for row in first["baseline_rows"]}
    assert len(first["merge_source_rows"]) == 2


def test_multi_branch_source_uses_both_real_sql_merge_branches() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")

    assert "MERGE INTO" in source
    assert "WHEN MATCHED THEN UPDATE SET" in source
    assert "WHEN NOT MATCHED THEN INSERT" in source
    assert "overwritePartitions" not in source


def test_multi_branch_final_state_keeps_flink_revision_and_inserts_new_road() -> None:
    plan = build_sql_merge_multi_branch_plan(DEFAULT_SOURCE)
    target_rows = [
        row for row in plan["final_merge_rows"] if row["road_id"] == plan["target_road_id"]
    ]
    inserted_rows = [
        row for row in plan["final_merge_rows"] if row["road_id"] == plan["inserted_road_id"]
    ]

    assert [row["revision"] for row in target_rows] == [1, 3]
    assert len(inserted_rows) == 1
    assert inserted_rows[0]["commit_token"] == plan["sql_merge_insert_token"]
    assert target_rows[-1]["commit_token"] == plan["sql_merge_matched_token"]
