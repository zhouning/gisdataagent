#!/usr/bin/env python3
"""Certify deterministic automatic deduplication before a fresh SQL MERGE retry."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts import certify_chongqing_osm_spark_flink_sql_merge_auto_retry as base
from scripts.certify_chongqing_osm_spark_flink_sql_merge_auto_retry import REPO_ROOT

DEFAULT_REPORT = (
    REPO_ROOT / "docs/reports/chongqing_osm_spark_flink_sql_merge_auto_dedup_2026-08-24.json"
)
SPARK_SOURCE = REPO_ROOT / "scripts/spark_chongqing_osm_iceberg_sql_merge_auto_dedup.py"
_BASE_PLAN_BUILDER = base.build_sql_merge_auto_retry_plan


def build_sql_merge_auto_dedup_plan(source_path: Path) -> dict:
    plan = _BASE_PLAN_BUILDER(source_path)
    selected = dict(plan["merge_source_fresh"])
    selected["dedup_rank"] = 100
    lower_priority = dict(selected)
    lower_priority.update(
        {
            "source_row_id": "candidate-lower-priority",
            "new_revision": 88,
            "writer_engine": "spark-sql-merge-unselected-candidate",
            "commit_token": base._canonical_sha256(
                {
                    "operation": "merge-auto-dedup-unselected",
                    "source_sha256": plan["source"]["source_parquet_sha256"],
                }
            ),
            "dedup_rank": 10,
        }
    )
    plan.update(
        {
            "schema": "gda.chongqing_osm_spark_flink_sql_merge_auto_dedup_plan.v1",
            "deduplication_policy": "highest_rank_then_source_row_id",
            "merge_source_candidates": [selected, lower_priority],
            "deduplication_selected_source_row_id": selected["source_row_id"],
        }
    )
    return plan


def _report_path() -> Path:
    for index, value in enumerate(sys.argv):
        if value == "--report" and index + 1 < len(sys.argv):
            return Path(sys.argv[index + 1])
    return DEFAULT_REPORT


def main() -> int:
    base.build_sql_merge_auto_retry_plan = build_sql_merge_auto_dedup_plan
    base.SPARK_SOURCE = SPARK_SOURCE
    base.SPARK_MODULE = "scripts.spark_chongqing_osm_iceberg_sql_merge_auto_dedup"
    base.DEFAULT_REPORT = DEFAULT_REPORT
    status = base.main()
    report_path = _report_path()
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        plan = build_sql_merge_auto_dedup_plan(base.DEFAULT_SOURCE)
        report["schema"] = "gda.chongqing_osm_spark_flink_sql_merge_auto_dedup.acceptance.v1"
        retry_checks = report.get("table", {}).get("automatic_retry", {}).get("checks", {})
        report["deduplication"] = {
            "policy": plan["deduplication_policy"],
            "candidate_source_row_ids": [
                row["source_row_id"] for row in plan["merge_source_candidates"]
            ],
            "selected_source_row_id": plan["deduplication_selected_source_row_id"],
            "unselected_candidate_commit_token_absent": retry_checks.get(
                "unselected_candidate_tokens_absent", False
            ),
        }
        report["not_claimed"] = [
            "automatic retry budget/退避, SQL UPDATE joins/subqueries or cross-partition writes",
            "MERGE delete/insert branches, equality/position delete or MOR",
            (
                "REST or Gravitino destructive-write conformance, HA, Kubernetes or "
                "production SLO/RPO/RTO"
            ),
        ]
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
