#!/usr/bin/env python3
"""Certify bounded retry budget exhaustion after SQL MERGE cardinality rejection."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts import certify_chongqing_osm_spark_flink_sql_merge_auto_retry as base
from scripts.certify_chongqing_osm_spark_flink_sql_merge_auto_retry import REPO_ROOT

DEFAULT_REPORT = (
    REPO_ROOT / "docs/reports/chongqing_osm_spark_flink_sql_merge_retry_budget_2026-08-24.json"
)
SPARK_SOURCE = REPO_ROOT / "scripts/spark_chongqing_osm_iceberg_sql_merge_retry_budget.py"
_BASE_PLAN_BUILDER = base.build_sql_merge_auto_retry_plan


def build_sql_merge_retry_budget_plan(source_path: Path) -> dict:
    plan = _BASE_PLAN_BUILDER(source_path)
    fresh = plan["merge_source_fresh"]
    retry_rows = []
    for index, new_revision in enumerate((4, 5), start=1):
        row = dict(fresh)
        row.update(
            {
                "expected_revision": 2,
                "new_revision": new_revision,
                "source_row_id": f"budget-failure-{index}",
                "writer_engine": "spark-sql-merge-budget-failure",
                "commit_token": base._canonical_sha256(
                    {
                        "operation": "merge-retry-budget-failure",
                        "attempt": index,
                        "source_sha256": plan["source"]["source_parquet_sha256"],
                    }
                ),
            }
        )
        retry_rows.append(row)
    plan.update(
        {
            "schema": "gda.chongqing_osm_spark_flink_sql_merge_retry_budget_plan.v1",
            "retry_budget": 1,
            "forced_retry_attempts": 2,
            "retry_budget_policy": "stop_before_attempt_after_budget",
            "retry_budget_rows": retry_rows,
        }
    )
    return plan


def _report_path() -> Path:
    for index, value in enumerate(sys.argv):
        if value == "--report" and index + 1 < len(sys.argv):
            return Path(sys.argv[index + 1])
    return DEFAULT_REPORT


def main() -> int:
    base.build_sql_merge_auto_retry_plan = build_sql_merge_retry_budget_plan
    base.SPARK_SOURCE = SPARK_SOURCE
    base.SPARK_MODULE = "scripts.spark_chongqing_osm_iceberg_sql_merge_retry_budget"
    base.DEFAULT_REPORT = DEFAULT_REPORT
    if "--budget-only" not in sys.argv:
        sys.argv.insert(1, "--budget-only")
    status = base.main()
    report_path = _report_path()
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        source_path = Path(
            next(
                (
                    sys.argv[index + 1]
                    for index, value in enumerate(sys.argv)
                    if value == "--source" and index + 1 < len(sys.argv)
                ),
                str(base.DEFAULT_SOURCE),
            )
        )
        if not source_path.is_absolute():
            source_path = REPO_ROOT / source_path
        plan = build_sql_merge_retry_budget_plan(source_path)
        report["schema"] = "gda.chongqing_osm_spark_flink_sql_merge_retry_budget.acceptance.v1"
        report["retry_budget"] = {
            "policy": plan["retry_budget_policy"],
            "budget": plan["retry_budget"],
            "forced_retry_attempts": plan["forced_retry_attempts"],
            "attempts_recorded": report.get("table", {})
            .get("automatic_retry", {})
            .get("attempts", []),
            "prevented_attempts": report.get("table", {})
            .get("automatic_retry", {})
            .get("prevented_attempts", 0),
        }
        report["not_claimed"] = [
            "successful retry after budget exhaustion, unbounded retry or adaptive backoff",
            (
                "SQL MERGE cross-target/cross-partition survivorship, UPDATE joins/subqueries "
                "or multi-file writes"
            ),
            (
                "REST or Gravitino destructive-write conformance, HA, Kubernetes or production "
                "SLO/RPO/RTO"
            ),
        ]
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
