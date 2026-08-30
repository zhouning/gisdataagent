#!/usr/bin/env python3
"""Certify a backoff-gated successful fresh-state SQL MERGE retry."""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import certify_chongqing_osm_spark_flink_sql_merge_auto_retry as base
from scripts.certify_chongqing_osm_spark_flink_sql_merge_auto_retry import REPO_ROOT

DEFAULT_REPORT = (
    REPO_ROOT / "docs/reports/chongqing_osm_spark_flink_sql_merge_successful_retry_2026-08-24.json"
)
SPARK_SOURCE = REPO_ROOT / "scripts/spark_chongqing_osm_iceberg_sql_merge_successful_retry.py"
_BASE_PLAN_BUILDER = base.build_sql_merge_auto_retry_plan


def build_sql_merge_successful_retry_plan(source_path: Path) -> dict:
    plan = _BASE_PLAN_BUILDER(source_path)
    plan.update(
        {
            "schema": "gda.chongqing_osm_spark_flink_sql_merge_successful_retry_plan.v1",
            "successful_retry_backoff_policy": {
                "delay_seconds": 0.01,
                "reason": "cardinality_rejection_before_fresh_deduplicated_merge",
            },
        }
    )
    return plan


def _report_path() -> Path:
    for index, value in enumerate(sys.argv):
        if value == "--report" and index + 1 < len(sys.argv):
            return Path(sys.argv[index + 1])
    return DEFAULT_REPORT


def main() -> int:
    base.build_sql_merge_auto_retry_plan = build_sql_merge_successful_retry_plan
    base.SPARK_SOURCE = SPARK_SOURCE
    base.SPARK_MODULE = "scripts.spark_chongqing_osm_iceberg_sql_merge_successful_retry"
    base.DEFAULT_REPORT = DEFAULT_REPORT
    status = base.main()
    report_path = _report_path()
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["schema"] = "gda.chongqing_osm_spark_flink_sql_merge_successful_retry.acceptance.v1"
        automatic_retry = report.get("table", {}).get("automatic_retry", {})
        report["successful_retry_backoff"] = automatic_retry.get("retry_backoff")
        report["not_claimed"] = [
            "multiple successful retries, cross-process budget or provider abort recovery",
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
