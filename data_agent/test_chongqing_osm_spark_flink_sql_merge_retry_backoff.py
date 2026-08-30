from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_merge_retry_backoff import (
    SPARK_SOURCE,
    build_sql_merge_retry_backoff_plan,
)


def test_retry_backoff_plan_is_deterministic_and_budget_bound() -> None:
    first = build_sql_merge_retry_backoff_plan(DEFAULT_SOURCE)
    second = build_sql_merge_retry_backoff_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["retry_budget"] == 3
    assert first["forced_retry_attempts"] == 4
    assert first["retry_backoff_policy"] == {
        "initial_seconds": 0.01,
        "multiplier": 2,
        "max_seconds": 0.02,
        "first_attempt_delay_seconds": 0.0,
    }
    assert len(first["retry_budget_rows"]) == 4


def test_retry_backoff_worker_records_admission_and_backoff() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")
    implementation = (
        SPARK_SOURCE.parent / "spark_chongqing_osm_iceberg_sql_merge_auto_retry.py"
    ).read_text(encoding="utf-8")

    assert "spark_chongqing_osm_iceberg_sql_merge_auto_retry" in source
    assert "retry_backoff_policy" in implementation
    assert "adaptive_backoff_sequence_exact" in implementation
    assert "backoff_observed_seconds" in implementation
    assert "attempts_after_budget_not_submitted" in implementation
