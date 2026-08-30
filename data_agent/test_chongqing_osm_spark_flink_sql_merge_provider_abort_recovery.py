from __future__ import annotations

from pathlib import Path

from scripts.certify_chongqing_osm_spark_flink_sql_merge_auto_retry import DEFAULT_SOURCE
from scripts.certify_chongqing_osm_spark_flink_sql_merge_provider_abort_recovery import (
    REPORT_SCHEMA,
    SPARK_SOURCE,
    build_sql_merge_auto_retry_plan,
)

WORKER_IMPLEMENTATION = (
    Path(__file__).resolve().parents[1]
    / "scripts/spark_chongqing_osm_iceberg_sql_merge_auto_retry.py"
)


def test_provider_abort_plan_is_single_fresh_revision_write() -> None:
    plan = build_sql_merge_auto_retry_plan(DEFAULT_SOURCE)
    target_rows = [
        row for row in plan["after_flink_rows"] if row["road_id"] == plan["target_road_id"]
    ]
    assert [row["revision"] for row in target_rows] == [1, 2]
    assert plan["merge_source_fresh"]["expected_revision"] == 2
    assert plan["merge_source_fresh"]["new_revision"] == 3
    assert any(row["revision"] == 3 for row in plan["final_merge_rows"])


def test_provider_abort_worker_contract_has_marker_and_reconcile_phase() -> None:
    source = WORKER_IMPLEMENTATION.read_text(encoding="utf-8")
    assert "abort-after-commit" in source
    assert "abort-reconcile" in source
    assert "gda.spark_sql_merge_abort_after_commit.v1" in source
    assert '"committed_unacknowledged"' in source
    assert SPARK_SOURCE.is_file()


def test_provider_abort_certifier_uses_dedicated_report_schema() -> None:
    certifier = Path(__file__).resolve().parents[1] / (
        "scripts/certify_chongqing_osm_spark_flink_sql_merge_provider_abort_recovery.py"
    )
    assert certifier.is_file()
    assert REPORT_SCHEMA.endswith("provider_abort_recovery.acceptance.v1")
