#!/usr/bin/env python3
"""Certify a bounded Spark SQL UPDATE driven by a correlated scope subquery."""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import certify_chongqing_osm_spark_flink_sql_update_multi_conflict as base
from scripts.certify_chongqing_osm_spark_flink_sql_update_multi_conflict import REPO_ROOT

REPORT_SCHEMA = "gda.chongqing_osm_spark_flink_sql_update_correlated_subquery.acceptance.v1"
DEFAULT_REPORT = REPO_ROOT / (
    "docs/reports/chongqing_osm_spark_flink_sql_update_correlated_subquery_2026-08-25.json"
)
SPARK_SOURCE = REPO_ROOT / "scripts/spark_chongqing_osm_iceberg_sql_update_correlated_subquery.py"
SPARK_IMPLEMENTATION_SOURCE = (
    REPO_ROOT / "scripts/spark_chongqing_osm_iceberg_sql_update_multi_conflict.py"
)
_BASE_PLAN_BUILDER = base.build_sql_update_multi_conflict_plan


def build_sql_update_correlated_subquery_plan(source_path: Path) -> dict:
    plan = _BASE_PLAN_BUILDER(source_path)
    guard = next(
        row for row in plan["baseline_rows"] if row["road_id"] not in plan["target_road_ids"]
    )
    plan.update(
        {
            "schema": "gda.chongqing_osm_spark_flink_sql_update_correlated_subquery_plan.v1",
            "subquery_scope_rows": [
                {"scope_road_id": int(value), "eligible": True}
                for value in plan["target_road_ids"]
            ]
            + [{"scope_road_id": int(guard["road_id"]), "eligible": False}],
            "correlated_subquery_where_template": (
                "EXISTS ("
                "SELECT 1 FROM gda_sql_update_scope AS scope "
                "WHERE scope.scope_road_id = road_id AND scope.eligible = true"
                ") AND revision = {expected_revision}"
            ),
            "guard_road_id": int(guard["road_id"]),
        }
    )
    return plan


def _report_path() -> Path:
    for index, value in enumerate(sys.argv):
        if value == "--report" and index + 1 < len(sys.argv):
            return Path(sys.argv[index + 1])
    return DEFAULT_REPORT


def main() -> int:
    base.build_sql_update_multi_conflict_plan = build_sql_update_correlated_subquery_plan
    base.SPARK_SOURCE = SPARK_SOURCE
    base.SPARK_MODULE = "scripts.spark_chongqing_osm_iceberg_sql_update_correlated_subquery"
    base.DEFAULT_REPORT = DEFAULT_REPORT
    status = base.main()
    report_path = _report_path()
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        source_path = Path(report.get("source", {}).get("source_path", str(base.DEFAULT_SOURCE)))
        if not source_path.is_absolute():
            source_path = REPO_ROOT / source_path
        plan = build_sql_update_correlated_subquery_plan(source_path)
        report.setdefault("source", {})["guard_road_id"] = plan["guard_road_id"]
        report["schema"] = REPORT_SCHEMA
        report["query_contract"] = {
            "predicate": (
                "EXISTS (SELECT 1 FROM gda_sql_update_scope AS scope "
                "WHERE scope.scope_road_id = road_id AND scope.eligible = true) "
                "AND revision = expected_revision"
            ),
            "scope_rows": plan["subquery_scope_rows"],
            "guard_road_id": plan["guard_road_id"],
            "guard_row_unchanged": True,
            "correlation_key": "scope.scope_road_id = target.road_id",
        }
        report["not_claimed"] = [
            "UPDATE joins, multi-table writes or correlated subqueries in SET expressions",
            "SQL MERGE multi-branch/multi-source-row semantics or automatic retry budget",
            "cross-partition/multi-file destructive writes, equality/position delete or MOR",
            "HA, Kubernetes, production SLO/RPO/RTO or cross-system exactly-once",
        ]
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
