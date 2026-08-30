from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_update_complex_predicate import (
    SPARK_IMPLEMENTATION_SOURCE,
    build_sql_update_complex_predicate_plan,
)


def test_complex_update_plan_is_deterministic_and_has_a_guard_row() -> None:
    first = build_sql_update_complex_predicate_plan(DEFAULT_SOURCE)
    second = build_sql_update_complex_predicate_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert first["guard_road_id"] not in first["target_road_ids"]
    assert "AND" in first["complex_predicate_where_template"]
    assert "OR" in first["complex_predicate_where_template"]
    assert "IN" in first["complex_predicate_where_template"]


def test_complex_update_uses_the_plan_bound_predicate() -> None:
    source = SPARK_IMPLEMENTATION_SOURCE.read_text(encoding="utf-8")

    assert "complex_predicate_where_template" in source
    assert "spark_sql_update_multi_conflict" in source


def test_complex_update_preserves_guard_and_updates_both_flink_rows() -> None:
    plan = build_sql_update_complex_predicate_plan(DEFAULT_SOURCE)
    final_targets = [
        row for row in plan["final_sql_update_rows"] if row["road_id"] in plan["target_road_ids"]
    ]
    guard_rows = [
        row for row in plan["final_sql_update_rows"] if row["road_id"] == plan["guard_road_id"]
    ]

    assert sorted((row["road_id"], row["revision"]) for row in final_targets) == sorted(
        [(road_id, 1) for road_id in plan["target_road_ids"]]
        + [(road_id, 3) for road_id in plan["target_road_ids"]]
    )
    assert len(guard_rows) == 1
    assert guard_rows[0]["revision"] == 1
    assert sum(row["commit_token"] == plan["sql_update_fresh_token"] for row in final_targets) == 2
