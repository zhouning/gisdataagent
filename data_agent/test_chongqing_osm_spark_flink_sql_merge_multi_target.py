from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_merge_multi_target import (
    SPARK_SOURCE,
    build_sql_merge_multi_target_plan,
)


def test_multi_target_plan_is_deterministic_and_has_two_unique_source_rows() -> None:
    first = build_sql_merge_multi_target_plan(DEFAULT_SOURCE)
    second = build_sql_merge_multi_target_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert len(first["matched_source_rows"]) == 2
    assert len({row["road_id"] for row in first["matched_source_rows"]}) == 2
    assert {row["expected_revision"] for row in first["matched_source_rows"]} == {1, 2}
    assert len(first["merge_source_rows"]) == 2


def test_multi_target_source_uses_real_sql_merge_update_branch() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")

    assert "MERGE INTO" in source
    assert "WHEN MATCHED THEN UPDATE SET" in source
    assert "WHEN MATCHED THEN UPDATE SET" in source
    assert "WHEN NOT MATCHED THEN INSERT" not in source
    assert "overwritePartitions" not in source


def test_multi_target_final_state_updates_both_targets_once() -> None:
    plan = build_sql_merge_multi_target_plan(DEFAULT_SOURCE)
    for source in plan["matched_source_rows"]:
        rows = [row for row in plan["final_merge_rows"] if row["road_id"] == source["road_id"]]
        updated = [row for row in rows if row["commit_token"] == source["commit_token"]]
        assert len(updated) == 1
        assert updated[0]["revision"] == source["result_revision"]
    assert len(plan["final_merge_rows"]) == 4
