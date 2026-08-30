from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_merge_delete import (
    SPARK_SOURCE,
    build_sql_merge_delete_plan,
)


def test_delete_plan_is_deterministic_and_binds_one_flink_revision() -> None:
    first = build_sql_merge_delete_plan(DEFAULT_SOURCE)
    second = build_sql_merge_delete_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert first["delete_source_row"]["expected_revision"] == 2
    assert first["delete_source_row"]["result_revision"] == -1
    assert first["delete_source_row"]["road_id"] == first["target_road_id"]
    assert len(first["merge_source_rows"]) == 1


def test_delete_source_uses_real_sql_merge_delete_branch() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")

    assert "MERGE INTO" in source
    assert "WHEN MATCHED THEN DELETE" in source
    assert "overwritePartitions" not in source


def test_delete_final_state_preserves_baseline_revision_and_removes_flink_revision() -> None:
    plan = build_sql_merge_delete_plan(DEFAULT_SOURCE)
    target_rows = [
        row for row in plan["final_merge_rows"] if row["road_id"] == plan["target_road_id"]
    ]

    assert [row["revision"] for row in target_rows] == [1]
    assert all(row["revision"] != 2 for row in target_rows)
    assert len(plan["final_merge_rows"]) == 3
