#!/usr/bin/env python3
"""Certify a bounded Spark SQL UPDATE with an AND/OR/IN predicate."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts import certify_chongqing_osm_spark_flink_sql_update_multi_conflict as base
from scripts.certify_chongqing_osm_spark_flink_sql_update_multi_conflict import REPO_ROOT

DEFAULT_REPORT = (
    REPO_ROOT
    / "docs/reports/chongqing_osm_spark_flink_sql_update_complex_predicate_2026-08-24.json"
)
SPARK_SOURCE = REPO_ROOT / "scripts/spark_chongqing_osm_iceberg_sql_update_complex_predicate.py"
SPARK_IMPLEMENTATION_SOURCE = (
    REPO_ROOT / "scripts/spark_chongqing_osm_iceberg_sql_update_multi_conflict.py"
)
_BASE_PLAN_BUILDER = base.build_sql_update_multi_conflict_plan


def build_sql_update_complex_predicate_plan(source_path: Path) -> dict:
    plan = _BASE_PLAN_BUILDER(source_path)
    guard = next(
        row for row in plan["baseline_rows"] if row["road_id"] not in plan["target_road_ids"]
    )
    plan.update(
        {
            "schema": "gda.chongqing_osm_spark_flink_sql_update_complex_predicate_plan.v1",
            "guard_road_id": guard["road_id"],
            "complex_predicate_where_template": (
                "revision = {expected_revision} AND ("
                "road_id IN ({first_road_id}) OR "
                "(road_id = {second_road_id} AND writer_engine = 'flink-1.19.3'))"
            ),
        }
    )
    return plan


def _report_path() -> Path:
    for index, value in enumerate(sys.argv):
        if value == "--report" and index + 1 < len(sys.argv):
            return Path(sys.argv[index + 1])
    return DEFAULT_REPORT


def main() -> int:
    base.build_sql_update_multi_conflict_plan = build_sql_update_complex_predicate_plan
    base.SPARK_SOURCE = SPARK_SOURCE
    base.SPARK_MODULE = "scripts.spark_chongqing_osm_iceberg_sql_update_complex_predicate"
    base.DEFAULT_REPORT = DEFAULT_REPORT
    status = base.main()
    report_path = _report_path()
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        source_path = Path(report.get("source", {}).get("source_path", str(base.DEFAULT_SOURCE)))
        if not source_path.is_absolute():
            source_path = REPO_ROOT / source_path
        plan = build_sql_update_complex_predicate_plan(source_path)
        report.setdefault("source", {})["guard_road_id"] = plan["guard_road_id"]
        report["schema"] = (
            "gda.chongqing_osm_spark_flink_sql_update_complex_predicate.acceptance.v1"
        )
        report["query_contract"] = {
            "predicate": (
                "revision = expected_revision AND "
                "(road_id IN (first_target) OR "
                "(road_id = second_target AND writer_engine = 'flink-1.19.3'))"
            ),
            "guard_road_id": plan["guard_road_id"],
            "guard_row_unchanged": True,
        }
        report["not_claimed"] = [
            "SQL UPDATE joins/subqueries, cross-partition or multi-file writes",
            "SQL MERGE complex predicates, automatic retry budget or deduplication",
            "equality/position delete, MOR, REST or Gravitino destructive-write conformance",
            "HA, Kubernetes, production SLO/RPO/RTO or cross-system exactly-once",
        ]
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
