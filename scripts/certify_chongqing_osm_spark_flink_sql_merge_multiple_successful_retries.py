#!/usr/bin/env python3
"""Certify two consecutive successful fresh-state SQL MERGE retries."""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import certify_chongqing_osm_spark_flink_sql_merge_auto_retry as base
from scripts.certify_chongqing_osm_spark_flink_sql_merge_auto_retry import REPO_ROOT

DEFAULT_REPORT = (
    REPO_ROOT
    / "docs/reports/chongqing_osm_spark_flink_sql_merge_multiple_successful_retries_2026-08-24.json"
)
SPARK_SOURCE = (
    REPO_ROOT / "scripts/spark_chongqing_osm_iceberg_sql_merge_multiple_successful_retries.py"
)
_BASE_PLAN_BUILDER = base.build_sql_merge_auto_retry_plan


def build_sql_merge_multiple_successful_retries_plan(source_path: Path) -> dict:
    plan = _BASE_PLAN_BUILDER(source_path)
    first = dict(plan["merge_source_fresh"])
    second = dict(first)
    second.update(
        {
            "expected_revision": 3,
            "new_revision": 4,
            "writer_engine": "spark-sql-merge-retry-2",
            "source_row_id": "fresh-source-retry-2",
            "commit_token": base._canonical_sha256(
                {
                    "operation": "merge-successful-retry-2",
                    "source_sha256": plan["source"]["source_parquet_sha256"],
                }
            ),
        }
    )
    second_row = {
        "road_id": second["road_id"],
        "revision": 4,
        "road_name_base64": second["road_name_base64"],
        "geometry_sha256": second["geometry_sha256"],
        "writer_engine": second["writer_engine"],
        "commit_token": second["commit_token"],
    }
    final_rows = sorted(
        [
            row
            for row in plan["final_merge_rows"]
            if row["road_id"] != second["road_id"] or row["revision"] != 3
        ]
        + [second_row],
        key=lambda row: (int(row["road_id"]), int(row["revision"]), str(row["writer_engine"])),
    )
    plan.update(
        {
            "schema": "gda.chongqing_osm_spark_flink_sql_merge_multiple_successful_retries_plan.v1",
            "successful_retry_sequence": [second],
            "successful_retry_count": 2,
            "final_merge_rows": final_rows,
            "final_merge_content_sha256": base._canonical_sha256(final_rows),
        }
    )
    return plan


def _report_path() -> Path:
    for index, value in enumerate(sys.argv):
        if value == "--report" and index + 1 < len(sys.argv):
            return Path(sys.argv[index + 1])
    return DEFAULT_REPORT


def main() -> int:
    base.build_sql_merge_auto_retry_plan = build_sql_merge_multiple_successful_retries_plan
    base.SPARK_SOURCE = SPARK_SOURCE
    base.SPARK_MODULE = "scripts.spark_chongqing_osm_iceberg_sql_merge_multiple_successful_retries"
    base.DEFAULT_REPORT = DEFAULT_REPORT
    status = base.main()
    report_path = _report_path()
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["schema"] = (
            "gda.chongqing_osm_spark_flink_sql_merge_multiple_successful_retries.acceptance.v1"
        )
        report["successful_retry_sequence"] = {
            "total_successful_retry_count": 2,
            "additional_retry_count": 1,
            "observed_additional_retries": report.get("table", {})
            .get("automatic_retry", {})
            .get("successful_retry_sequence", []),
        }
        report["not_claimed"] = [
            "cross-process successful retry, provider abort recovery or production HA",
            (
                "SQL MERGE cross-target/cross-partition survivorship, UPDATE joins/subqueries "
                "or multi-file writes"
            ),
            (
                "REST or Gravitino destructive-write conformance, Kubernetes or production "
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
