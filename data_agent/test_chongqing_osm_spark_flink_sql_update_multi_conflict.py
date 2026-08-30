from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_update_multi_conflict import (
    SPARK_SOURCE,
    build_sql_update_multi_conflict_plan,
)


def test_multi_row_sql_update_plan_is_deterministic_and_has_two_targets() -> None:
    first = build_sql_update_multi_conflict_plan(DEFAULT_SOURCE)
    second = build_sql_update_multi_conflict_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert first["target_road_ids"] == sorted(set(first["target_road_ids"]))
    assert len(first["target_road_ids"]) == 2
    assert len(first["flink_rows"]) == 2
    assert first["sql_update_stale"]["expected_revision"] == 1
    assert first["sql_update_fresh"]["expected_revision"] == 2
    assert first["sql_update_stale_token"] != first["sql_update_fresh_token"]


def test_multi_row_sql_update_is_one_real_update_with_all_target_predicate() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")

    assert "UPDATE {args.table}" in source
    assert "road_id IN ({ids})" in source
    assert 'AND revision = {source["expected_revision"]}' in source
    assert "gda_sql_update_multi_barrier(road_id)" in source
    assert "gda.spark_sql_update_multi_conflict_ready.v1" in source
    assert "MERGE INTO" not in source
    assert "overwritePartitions" not in source


def test_multi_row_retry_updates_both_flink_revisions_and_preserves_baseline_rows() -> None:
    plan = build_sql_update_multi_conflict_plan(DEFAULT_SOURCE)
    final_targets = [
        row for row in plan["final_sql_update_rows"] if row["road_id"] in plan["target_road_ids"]
    ]
    assert sorted((row["road_id"], row["revision"]) for row in final_targets) == sorted(
        [(road_id, 1) for road_id in plan["target_road_ids"]]
        + [(road_id, 3) for road_id in plan["target_road_ids"]]
    )
    assert sum(row["commit_token"] == plan["sql_update_fresh_token"] for row in final_targets) == 2
    assert len(plan["final_sql_update_rows"]) == 5
