from __future__ import annotations

from scripts.certify_chongqing_osm_flink_iceberg_interop import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_merge_retry_budget import (
    SPARK_SOURCE,
    build_sql_merge_retry_budget_plan,
)


def test_retry_budget_plan_is_deterministic_and_exceeds_attempt_budget() -> None:
    first = build_sql_merge_retry_budget_plan(DEFAULT_SOURCE)
    second = build_sql_merge_retry_budget_plan(DEFAULT_SOURCE)

    assert first == second
    assert first["source"]["source_feature_count"] == 50_366
    assert first["retry_budget"] == 1
    assert first["forced_retry_attempts"] == 2
    assert len(first["retry_budget_rows"]) == 2
    assert {row["expected_revision"] for row in first["retry_budget_rows"]} == {2}


def test_retry_budget_worker_has_explicit_budget_phase() -> None:
    source = SPARK_SOURCE.read_text(encoding="utf-8")
    implementation = (
        SPARK_SOURCE.parent / "spark_chongqing_osm_iceberg_sql_merge_auto_retry.py"
    ).read_text(encoding="utf-8")

    assert "spark_chongqing_osm_iceberg_sql_merge_auto_retry" in source
    assert '"budget-exhausted"' in implementation
    assert "attempts_after_budget_not_submitted" in implementation


def test_retry_budget_rows_cannot_match_baseline_revision() -> None:
    plan = build_sql_merge_retry_budget_plan(DEFAULT_SOURCE)
    assert all(row["expected_revision"] == 2 for row in plan["retry_budget_rows"])
    assert all(row["new_revision"] in {4, 5} for row in plan["retry_budget_rows"])
