#!/usr/bin/env python3
"""Certify explicit rank survivorship for duplicate sources across two targets."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts import certify_chongqing_osm_spark_flink_sql_merge_multi_target as base
from scripts.certify_chongqing_osm_spark_flink_sql_merge_multi_target import REPO_ROOT

DEFAULT_REPORT = (
    REPO_ROOT
    / "docs/reports/chongqing_osm_spark_flink_sql_merge_cross_target_survivorship_2026-08-24.json"
)
SPARK_SOURCE = (
    REPO_ROOT / "scripts/spark_chongqing_osm_iceberg_sql_merge_cross_target_survivorship.py"
)
_BASE_PLAN_BUILDER = base.build_sql_merge_multi_target_plan


def build_cross_target_survivorship_plan(source_path: Path) -> dict:
    plan = _BASE_PLAN_BUILDER(source_path)
    candidates: list[dict] = []
    selected: list[dict] = []
    for source in plan["merge_source_rows"]:
        high = dict(source)
        high["survivorship_rank"] = 100
        low = dict(source)
        low.update(
            {
                "source_row_id": f"{source['source_row_id']}-lower",
                "result_revision": source["result_revision"] + 50,
                "writer_engine": "spark-sql-merge-unselected-survivorship",
                "commit_token": base._canonical_sha256(
                    {
                        "operation": "cross-target-survivorship-unselected",
                        "road_id": source["road_id"],
                        "source_sha256": plan["source"]["source_parquet_sha256"],
                    }
                ),
                "survivorship_rank": 10,
            }
        )
        candidates.extend((high, low))
        selected.append(high)
    plan["merge_source_rows"] = selected
    final_rows = [
        row
        for row in plan["after_flink_rows"]
        if not any(
            row["road_id"] == source["road_id"]
            and row["revision"] == source["expected_revision"]
            for source in selected
        )
    ] + [
        {
            "road_id": source["road_id"],
            "revision": source["result_revision"],
            "road_name_base64": source["road_name_base64"],
            "geometry_sha256": source["geometry_sha256"],
            "writer_engine": source["writer_engine"],
            "commit_token": source["commit_token"],
        }
        for source in selected
    ]
    plan.update(
        {
            "schema": "gda.chongqing_osm_spark_flink_sql_merge_cross_target_survivorship_plan.v1",
            "survivorship_policy": "highest_rank_then_source_row_id_per_target",
            "survivorship_candidates": candidates,
            "final_merge_rows": sorted(
                final_rows,
                key=lambda row: (
                    int(row["road_id"]),
                    int(row["revision"]),
                    str(row["writer_engine"]),
                ),
            ),
        }
    )
    plan["final_merge_content_sha256"] = base._canonical_sha256(plan["final_merge_rows"])
    return plan


def _report_path() -> Path:
    for index, value in enumerate(sys.argv):
        if value == "--report" and index + 1 < len(sys.argv):
            return Path(sys.argv[index + 1])
    return DEFAULT_REPORT


def main() -> int:
    base.build_sql_merge_multi_target_plan = build_cross_target_survivorship_plan
    base.SPARK_SOURCE = SPARK_SOURCE
    base.SPARK_MODULE = "scripts.spark_chongqing_osm_iceberg_sql_merge_cross_target_survivorship"
    base.DEFAULT_REPORT = DEFAULT_REPORT
    status = base.main()
    report_path = _report_path()
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        plan = build_cross_target_survivorship_plan(base.DEFAULT_SOURCE)
        report["schema"] = (
            "gda.chongqing_osm_spark_flink_sql_merge_cross_target_survivorship.acceptance.v1"
        )
        report["survivorship"] = {
            "policy": plan["survivorship_policy"],
            "candidate_count": len(plan["survivorship_candidates"]),
            "selected_source_row_ids": [row["source_row_id"] for row in plan["merge_source_rows"]],
            "unselected_token_absent": report.get("table", {})
            .get("merge", {})
            .get("checks", {})
            .get("unselected_survivorship_tokens_absent", False),
        }
        report["not_claimed"] = [
            "cross-partition or multi-file writes, adaptive retry/backoff, provider abort recovery",
            (
                "MERGE deletes/inserts, SQL UPDATE joins/subqueries, REST or Gravitino "
                "destructive-write conformance"
            ),
            "HA, Kubernetes, production SLO/RPO/RTO or cross-system exactly-once",
        ]
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
