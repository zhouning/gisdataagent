from __future__ import annotations

from pathlib import Path

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_update_correlated_subquery import (
    SPARK_IMPLEMENTATION_SOURCE,
    SPARK_SOURCE,
    build_sql_update_correlated_subquery_plan,
)


def test_correlated_subquery_plan_is_deterministic_and_has_guard_scope() -> None:
    first = build_sql_update_correlated_subquery_plan(DEFAULT_SOURCE)
    second = build_sql_update_correlated_subquery_plan(DEFAULT_SOURCE)

    assert first == second
    assert len(first["subquery_scope_rows"]) == 3
    assert {row["scope_road_id"] for row in first["subquery_scope_rows"]} == {
        *first["target_road_ids"],
        first["guard_road_id"],
    }
    assert sum(row["eligible"] for row in first["subquery_scope_rows"]) == 2


def test_correlated_subquery_entry_points_use_outer_row_correlation() -> None:
    source = SPARK_IMPLEMENTATION_SOURCE.read_text(encoding="utf-8")
    wrapper = SPARK_SOURCE.read_text(encoding="utf-8")
    certifier = Path(build_sql_update_correlated_subquery_plan.__code__.co_filename).read_text(
        encoding="utf-8"
    )

    assert "correlated_subquery_where_template" in source
    assert "scope.scope_road_id = road_id" in certifier
    assert "correlation_key" in certifier
    assert "spark_chongqing_osm_iceberg_sql_update_multi_conflict" in wrapper
