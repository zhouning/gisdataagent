from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_merge_multi_source_conflict import (
    SPARK_SOURCE,
    build_sql_merge_multi_source_conflict_plan,
)


def test_multi_source_merge_plan_is_deterministic_and_contains_duplicate_target_rows() -> None:
    first = build_sql_merge_multi_source_conflict_plan(DEFAULT_SOURCE)
    second = build_sql_merge_multi_source_conflict_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert len(first["merge_source_stale_rows"]) == 2
    assert first["stale_source_row_ids"] == ["stale-source-a", "stale-source-b"]
    assert {row["road_id"] for row in first["merge_source_stale_rows"]} == {first["target_road_id"]}
    assert {row["expected_revision"] for row in first["merge_source_stale_rows"]} == {1}
    assert first["sql_merge_stale_tokens"][0] != first["sql_merge_stale_tokens"][1]


def test_multi_source_merge_uses_real_merge_and_duplicate_source_barrier_contract() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")

    assert "MERGE INTO" in source
    assert "WHEN MATCHED THEN UPDATE SET" in source
    assert "source_row_count" in source
    assert "gda.spark_sql_merge_multi_source_conflict_ready.v1" in source
    assert "overwritePartitions" not in source


def test_deduplicated_retry_preserves_baseline_and_flink_revision() -> None:
    plan = build_sql_merge_multi_source_conflict_plan(DEFAULT_SOURCE)
    target_rows = [
        row for row in plan["final_merge_rows"] if row["road_id"] == plan["target_road_id"]
    ]

    assert [row["revision"] for row in target_rows] == [1, 3]
    assert target_rows[-1]["commit_token"] == plan["sql_merge_fresh_token"]
    assert plan["merge_source_fresh"]["source_row_id"] == "fresh-source-deduplicated"
    assert len({row["road_id"] for row in plan["final_merge_rows"]}) == 3
