#!/usr/bin/env python3
"""Certify snapshot-bound Spark SQL UPDATE conflict rejection and fresh retry."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pyspark.sql.functions import col
from pyspark.sql.types import BooleanType

from scripts.spark_chongqing_osm_iceberg_interop import (
    CATALOG,
    _canonical_sha256,
    _snapshots,
    _spark,
)
from scripts.spark_chongqing_osm_iceberg_overwrite_conflict import classify_conflict_error
from scripts.spark_chongqing_osm_iceberg_sql_merge_conflict import _rows, _schema

BARRIER_RE = re.compile(
    r"^/workspace/\.tmp/source-sync-certification/"
    r"flink_iceberg_sql_update_conflict_[0-9a-f]{10}/spark-ready\.json$"
)


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _validate_barriers(args: argparse.Namespace) -> None:
    if not args.ready_marker or not args.release_marker:
        raise ValueError("concurrent SQL UPDATE requires both barrier paths")
    if not BARRIER_RE.fullmatch(args.ready_marker.as_posix()):
        raise ValueError("unsafe SQL UPDATE barrier path")
    if not BARRIER_RE.fullmatch(
        args.release_marker.as_posix().replace("spark-release.json", "spark-ready.json")
    ):
        raise ValueError("unsafe SQL UPDATE barrier path")
    if args.release_marker.as_posix() != args.ready_marker.as_posix().replace(
        "spark-ready.json", "spark-release.json"
    ):
        raise ValueError("SQL UPDATE release marker must share the acceptance work directory")


def _baseline(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    namespace = args.table.split(".")[1]
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.{namespace}")
    if spark.catalog.tableExists(args.table):
        raise RuntimeError("isolated SQL UPDATE table already exists")
    frame = spark.createDataFrame(plan["baseline_rows"], schema=_schema())
    (
        frame.writeTo(args.table)
        .using("iceberg")
        .partitionedBy(col("road_id"))
        .tableProperty("format-version", "2")
        .tableProperty("gda.acceptance", "spark-sql-update-conflict")
        .tableProperty("gda.source_sha256", plan["source"]["source_parquet_sha256"])
        .create()
    )
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    checks = {
        "baseline_rows_exact": list(actual) == plan["baseline_rows"],
        "baseline_content_exact": _canonical_sha256(actual) == plan["baseline_content_sha256"],
        "one_baseline_snapshot": len(snapshots) == 1 and snapshots[0]["operation"] == "append",
    }
    return {
        "phase": "baseline",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "baseline_snapshot_id": snapshots[0]["snapshot_id"],
    }


def _register_barrier(spark, args: argparse.Namespace, plan: dict[str, Any]) -> None:
    _validate_barriers(args)
    payload = {
        "schema": "gda.spark_sql_update_conflict_ready.v1",
        "baseline_snapshot_id": args.baseline_snapshot_id,
        "commit_token": plan["sql_update_stale_token"],
        "target_road_id": plan["target_road_id"],
        "expected_revision": plan["sql_update_stale_expected_revision"],
    }
    marker = args.ready_marker
    release = args.release_marker
    timeout = args.barrier_timeout_seconds

    def barrier(_value: int) -> bool:
        marker.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not release.is_file():
            time.sleep(0.1)
        if not release.is_file():
            raise RuntimeError("SQL UPDATE barrier timed out")
        return True

    spark.udf.register("gda_sql_update_barrier", barrier, BooleanType())


def _run_update(
    spark, args: argparse.Namespace, plan: dict[str, Any], *, wait: bool
) -> dict[str, Any]:
    if wait:
        _register_barrier(spark, args, plan)
        spark.sql("SELECT gda_sql_update_barrier(road_id) FROM " + args.table).collect()
        spark.catalog.clearCache()
        spark.catalog.refreshTable(args.table)
        snapshots_after_barrier = _snapshots(spark, args.table)
        current_snapshot_id = (
            snapshots_after_barrier[-1]["snapshot_id"] if snapshots_after_barrier else None
        )
        if current_snapshot_id != args.baseline_snapshot_id:
            source = plan["sql_update_stale"]
            conflict = {
                "conflict_type": "snapshot_guard_rejected",
                "guard_rejected": True,
                "is_iceberg_validation_failure": False,
                "baseline_snapshot_id": args.baseline_snapshot_id,
                "current_snapshot_id": current_snapshot_id,
                "commit_token": source["commit_token"],
            }
            actual = _rows(spark.table(args.table))
            return {
                "update_committed": False,
                "conflict": conflict,
                "actual_rows": list(actual),
                "snapshots": snapshots_after_barrier,
                "commit_token_count": 0,
            }
    source = plan["sql_update_stale"] if wait else plan["sql_update_fresh"]
    query = f"""
        UPDATE {args.table}
        SET revision = {source["new_revision"]},
            road_name_base64 = {_sql_string(source["road_name_base64"])},
            geometry_sha256 = {_sql_string(source["geometry_sha256"])},
            writer_engine = {_sql_string(source["writer_engine"])},
            commit_token = {_sql_string(source["commit_token"])}
        WHERE road_id = {source["road_id"]}
          AND revision = {source["expected_revision"]}
    """
    update_committed = False
    conflict: dict[str, Any] | None = None
    try:
        spark.sql(query)
        update_committed = True
    except Exception as exc:
        conflict = classify_conflict_error(exc)
    spark.catalog.clearCache()
    spark.catalog.refreshTable(args.table)
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    token_count = sum(row["commit_token"] == source["commit_token"] for row in actual)
    return {
        "update_committed": update_committed,
        "conflict": conflict,
        "actual_rows": list(actual),
        "snapshots": snapshots,
        "commit_token_count": token_count,
    }


def _concurrent_update(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    before = _snapshots(spark, args.table)
    if len(before) != 1 or before[0]["snapshot_id"] != args.baseline_snapshot_id:
        raise RuntimeError("SQL UPDATE did not start from exact baseline snapshot")
    result = _run_update(spark, args, plan, wait=True)
    release = json.loads(args.release_marker.read_text(encoding="utf-8"))
    target_rows = [row for row in result["actual_rows"] if row["road_id"] == plan["target_road_id"]]
    checks = {
        "update_not_committed": not result["update_committed"],
        "stale_snapshot_guard_rejected": bool(
            result["conflict"] and result["conflict"].get("guard_rejected")
        ),
        "baseline_and_flink_rows_preserved": result["actual_rows"] == plan["after_flink_rows"],
        "stale_update_token_absent": result["commit_token_count"] == 0,
        "target_revisions_one_and_two_visible": sorted(row["revision"] for row in target_rows)
        == [1, 2],
        "release_marker_exact": release.get("schema") == "gda.spark_sql_update_conflict_release.v1"
        and release.get("flink_commit_token") == plan["flink_commit_token"],
        "catalog_snapshot_chain_unchanged": len(result["snapshots"]) == 2
        and result["snapshots"][-1]["snapshot_id"] == str(release.get("flink_snapshot_id")),
    }
    return {
        "phase": "concurrent-update",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(result["actual_rows"]),
        "content_sha256": _canonical_sha256(result["actual_rows"]),
        "snapshots": result["snapshots"],
        "conflict": result["conflict"],
        "release": release,
        "update_committed": result["update_committed"],
        "stale_update_token_count": result["commit_token_count"],
    }


def _retry(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    current = _rows(spark.table(args.table))
    before = _snapshots(spark, args.table)
    if (
        list(current) != plan["after_flink_rows"]
        or before[-1]["snapshot_id"] != args.flink_snapshot_id
    ):
        raise RuntimeError("SQL UPDATE retry did not read exact Flink state")
    result = _run_update(spark, args, plan, wait=False)
    actual = result["actual_rows"]
    snapshots = result["snapshots"]
    checks = {
        "fresh_sql_update_committed": result["update_committed"],
        "final_rows_exact": actual == plan["final_sql_update_rows"],
        "fresh_update_token_once": result["commit_token_count"] == 1,
        "retry_snapshot_child_of_flink": len(snapshots) == 3
        and snapshots[-1]["parent_id"] == args.flink_snapshot_id
        and snapshots[-1]["operation"] == "overwrite",
    }
    return {
        "phase": "retry",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "retry_snapshot_id": snapshots[-1]["snapshot_id"],
    }


def _verify(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    baseline = _rows(spark.read.option("snapshot-id", args.baseline_snapshot_id).table(args.table))
    flink = _rows(spark.read.option("snapshot-id", args.flink_snapshot_id).table(args.table))
    checks = {
        "final_rows_exact": list(actual) == plan["final_sql_update_rows"],
        "final_content_exact": _canonical_sha256(actual) == plan["final_sql_update_content_sha256"],
        "baseline_time_travel_exact": list(baseline) == plan["baseline_rows"],
        "flink_time_travel_exact": list(flink) == plan["after_flink_rows"],
        "snapshot_chain_exact": len(snapshots) == 3
        and [item["operation"] for item in snapshots] == ["append", "append", "overwrite"],
        "road_ids_remain_bounded": len(actual) == 4,
    }
    return {
        "phase": "verify",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("baseline", "concurrent-update", "retry", "verify"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--warehouse-uri", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--endpoint-url", default="http://minio:9000")
    parser.add_argument("--baseline-snapshot-id")
    parser.add_argument("--flink-snapshot-id")
    parser.add_argument("--ready-marker", type=Path)
    parser.add_argument("--release-marker", type=Path)
    parser.add_argument("--barrier-timeout-seconds", type=int, default=180)
    args = parser.parse_args()
    if args.phase != "baseline" and not args.baseline_snapshot_id:
        parser.error(f"{args.phase} requires --baseline-snapshot-id")
    if args.phase in ("retry", "verify") and not args.flink_snapshot_id:
        parser.error(f"{args.phase} requires --flink-snapshot-id")
    if not 30 <= args.barrier_timeout_seconds <= 300:
        parser.error("barrier timeout must be between 30 and 300 seconds")
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        if not os.environ.get(name):
            raise RuntimeError(f"missing required environment variable {name}")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    spark = _spark(args)
    try:
        spark.sparkContext.setLogLevel("WARN")
        if args.phase == "baseline":
            phase = _baseline(spark, args, plan)
        elif args.phase == "concurrent-update":
            phase = _concurrent_update(spark, args, plan)
        elif args.phase == "retry":
            phase = _retry(spark, args, plan)
        else:
            phase = _verify(spark, args, plan)
    finally:
        spark.stop()
    report = {
        "schema": "gda.spark_flink_iceberg_sql_update_conflict_phase.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        **phase,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"phase": args.phase, "status": report["status"]}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
