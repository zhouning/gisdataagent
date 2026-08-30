#!/usr/bin/env python3
"""Certify a bounded Spark SQL UPDATE with a correlated scalar SET subquery."""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import certify_chongqing_osm_spark_flink_sql_update_multi_conflict as base
from scripts.certify_chongqing_osm_spark_flink_sql_update_multi_conflict import REPO_ROOT

REPORT_SCHEMA = "gda.chongqing_osm_spark_flink_sql_update_scalar_subquery.acceptance.v1"
DEFAULT_REPORT = REPO_ROOT / (
    "docs/reports/chongqing_osm_spark_flink_sql_update_scalar_subquery_2026-08-25.json"
)
SPARK_SOURCE = REPO_ROOT / "scripts/spark_chongqing_osm_iceberg_sql_update_scalar_subquery.py"
SPARK_IMPLEMENTATION_SOURCE = (
    REPO_ROOT / "scripts/spark_chongqing_osm_iceberg_sql_update_multi_conflict.py"
)
_BASE_PLAN_BUILDER = base.build_sql_update_multi_conflict_plan
_BASE_SPARK_PHASE = base._spark_phase


def build_sql_update_scalar_subquery_plan(source_path: Path) -> dict:
    plan = _BASE_PLAN_BUILDER(source_path)
    guard = next(
        row for row in plan["baseline_rows"] if row["road_id"] not in plan["target_road_ids"]
    )
    plan.update(
        {
            "schema": "gda.chongqing_osm_spark_flink_sql_update_scalar_subquery_plan.v1",
            "scalar_subquery_scope_rows": [
                {
                    "scope_road_id": int(value),
                    "eligible": True,
                    "writer_engine": plan["sql_update_fresh"]["writer_engine"],
                }
                for value in plan["target_road_ids"]
            ]
            + [
                {
                    "scope_road_id": int(guard["road_id"]),
                    "eligible": False,
                    "writer_engine": "guard-must-remain-unchanged",
                }
            ],
            "subquery_where_template": (
                "road_id IN ("
                "SELECT scope_road_id FROM gda_sql_update_scope WHERE eligible = true"
                ") AND revision = {expected_revision}"
            ),
            "capability_probe": True,
            "scalar_subquery_set_template": (
                "(SELECT scope.writer_engine FROM gda_sql_update_scope AS scope "
                "WHERE scope.scope_road_id = road_id AND scope.eligible = true)"
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


def _diagnostic_spark_phase(args, **kwargs):
    try:
        return _BASE_SPARK_PHASE(args, **kwargs)
    except Exception as exc:
        report_path = Path(kwargs["report_path"])
        if report_path.exists():
            phase_report = json.loads(report_path.read_text(encoding="utf-8"))
            raise RuntimeError(
                f"{kwargs['phase']} phase checks={phase_report.get('checks')} "
                f"conflict={phase_report.get('conflict')} "
                f"error={phase_report.get('error')}"
            ) from exc
        raise


def main() -> int:
    base.build_sql_update_multi_conflict_plan = build_sql_update_scalar_subquery_plan
    base._spark_phase = _diagnostic_spark_phase
    base.SPARK_SOURCE = SPARK_SOURCE
    base.SPARK_MODULE = "scripts.spark_chongqing_osm_iceberg_sql_update_scalar_subquery"
    base.DEFAULT_REPORT = DEFAULT_REPORT
    status = base.main()
    report_path = _report_path()
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        source_path = Path(report.get("source", {}).get("source_path", str(base.DEFAULT_SOURCE)))
        if not source_path.is_absolute():
            source_path = REPO_ROOT / source_path
        plan = build_sql_update_scalar_subquery_plan(source_path)
        report.setdefault("source", {})["guard_road_id"] = plan["guard_road_id"]
        report["schema"] = REPORT_SCHEMA
        report["query_contract"] = {
            "where_predicate": (
                "road_id IN (SELECT scope_road_id FROM gda_sql_update_scope "
                "WHERE eligible = true) AND revision = expected_revision"
            ),
            "set_expression": (
                "(SELECT scope.writer_engine FROM gda_sql_update_scope AS scope "
                "WHERE scope.scope_road_id = road_id AND scope.eligible = true)"
            ),
            "scope_rows": plan["scalar_subquery_scope_rows"],
            "correlation_key": "scope.scope_road_id = target.road_id",
            "guard_road_id": plan["guard_road_id"],
            "guard_row_unchanged": True,
            "capability_probe": True,
        }
        report["capability_status"] = "unsupported_fail_closed"
        report["not_claimed"] = [
            "UPDATE joins, multi-table writes or multiple matching scalar scope rows",
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
