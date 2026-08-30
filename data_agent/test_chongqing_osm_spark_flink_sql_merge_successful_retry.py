from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_merge_successful_retry import (
    SPARK_SOURCE,
    build_sql_merge_successful_retry_plan,
)


def test_successful_retry_plan_is_deterministic_and_backoff_bound() -> None:
    first = build_sql_merge_successful_retry_plan(DEFAULT_SOURCE)
    second = build_sql_merge_successful_retry_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["successful_retry_backoff_policy"]["delay_seconds"] == 0.01
    assert first["successful_retry_backoff_policy"]["reason"]
    assert len(first["merge_source_stale_rows"]) == 2


def test_successful_retry_entry_point_records_backoff_and_fresh_commit() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")
    implementation = (
        SPARK_SOURCE.parent / "spark_chongqing_osm_iceberg_sql_merge_auto_retry.py"
    ).read_text(encoding="utf-8")

    assert "spark_chongqing_osm_iceberg_sql_merge_auto_retry" in source
    assert "successful_retry_backoff_policy" in implementation
    assert "successful_retry_backoff_observed_lower_bound" in implementation
    assert "automatic_retry_snapshot_child_of_flink" in implementation
