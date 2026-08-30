from __future__ import annotations

from pathlib import Path

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_update_scalar_subquery import (
    SPARK_IMPLEMENTATION_SOURCE,
    SPARK_SOURCE,
    build_sql_update_scalar_subquery_plan,
)


def test_scalar_subquery_plan_has_one_scope_value_per_target_and_guard() -> None:
    first = build_sql_update_scalar_subquery_plan(DEFAULT_SOURCE)
    second = build_sql_update_scalar_subquery_plan(DEFAULT_SOURCE)

    assert first == second
    rows = first["scalar_subquery_scope_rows"]
    assert len(rows) == 3
    assert {row["scope_road_id"] for row in rows} == {
        *first["target_road_ids"],
        first["guard_road_id"],
    }
    assert sum(row["eligible"] for row in rows) == 2
    assert all(row["writer_engine"] for row in rows)


def test_scalar_subquery_entry_points_bind_set_expression_to_outer_row() -> None:
    source = SPARK_IMPLEMENTATION_SOURCE.read_text(encoding="utf-8")
    wrapper = SPARK_SOURCE.read_text(encoding="utf-8")
    certifier = Path(build_sql_update_scalar_subquery_plan.__code__.co_filename).read_text(
        encoding="utf-8"
    )

    assert "scalar_subquery_set_template" in source
    assert "writer_engine = {writer_expression}" in source
    assert "SELECT scope.writer_engine FROM gda_sql_update_scope" in certifier
    assert "scope.scope_road_id = road_id" in certifier
    assert "spark_chongqing_osm_iceberg_sql_update_multi_conflict" in wrapper
