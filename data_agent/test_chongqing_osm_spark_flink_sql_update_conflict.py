from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_update_conflict import (
    SPARK_SOURCE,
    build_sql_update_conflict_plan,
)


def test_sql_update_plan_is_deterministic_and_binds_stale_and_fresh_revisions() -> None:
    first = build_sql_update_conflict_plan(DEFAULT_SOURCE)
    second = build_sql_update_conflict_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert first["sql_update_stale"]["expected_revision"] == 1
    assert first["sql_update_stale"]["new_revision"] == 2
    assert first["sql_update_fresh"]["expected_revision"] == 2
    assert first["sql_update_fresh"]["new_revision"] == 3
    assert first["sql_update_stale_token"] != first["sql_update_fresh_token"]


def test_sql_update_source_uses_real_update_and_barrier_contract() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")

    assert "UPDATE {args.table}" in source
    assert "SET revision =" in source
    assert "gda_sql_update_barrier(road_id)" in source
    assert "gda.spark_sql_update_conflict_ready.v1" in source
    assert "MERGE INTO" not in source
    assert "overwritePartitions" not in source


def test_sql_update_plan_keeps_baseline_and_updates_only_flink_revision_on_retry() -> None:
    plan = build_sql_update_conflict_plan(DEFAULT_SOURCE)
    target_rows = [
        row for row in plan["final_sql_update_rows"] if row["road_id"] == plan["target_road_id"]
    ]

    assert [row["revision"] for row in target_rows] == [1, 3]
    assert target_rows[-1]["writer_engine"] == "spark-sql-update"
    assert target_rows[-1]["commit_token"] == plan["sql_update_fresh_token"]
    assert len({row["road_id"] for row in plan["final_sql_update_rows"]}) == 3
