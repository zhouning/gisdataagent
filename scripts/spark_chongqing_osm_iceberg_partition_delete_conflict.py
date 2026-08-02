#!/usr/bin/env python3
"""Reject a stale partition delete, retry from fresh state, and verify Iceberg."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.spark_chongqing_osm_iceberg_concurrent_append import COLUMNS, _schema
from scripts.spark_chongqing_osm_iceberg_delete_conflict import (
    _iceberg_table,
    _key_expression,
    _snapshots,
)
from scripts.spark_chongqing_osm_iceberg_interop import (
    CATALOG,
    _canonical_sha256,
    _spark,
)
from scripts.spark_chongqing_osm_iceberg_overwrite_conflict import (
    classify_conflict_error,
)

BARRIER_RE = re.compile(
    r"^/workspace/\.tmp/source-sync-certification/"
    r"flink_iceberg_partition_delete_conflict_[0-9a-f]{10}/"
    r"spark-(?:ready|release)\.json$"
)


def _rows(frame) -> tuple[dict[str, Any], ...]:
    return tuple(
        {key: row[key] for key in COLUMNS}
        for row in frame.select(*COLUMNS).orderBy("road_id", "revision", "writer_engine").collect()
    )


def _baseline(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    from pyspark.sql.functions import col

    namespace = args.table.split(".")[1]
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.{namespace}")
    if spark.catalog.tableExists(args.table):
        raise RuntimeError("isolated partition delete table already exists")
    frame = spark.createDataFrame(plan["baseline_rows"], schema=_schema())
    (
        frame.writeTo(args.table)
        .using("iceberg")
        .partitionedBy(col("road_id"))
        .tableProperty("format-version", "2")
        .tableProperty("gda.acceptance", "spark-flink-partition-delete-conflict")
        .tableProperty("gda.source_sha256", plan["source"]["source_parquet_sha256"])
        .create()
    )
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    target_rows = [row for row in actual if row["road_id"] == plan["target_road_id"]]
    checks = {
        "baseline_rows_exact": list(actual) == plan["baseline_rows"],
        "baseline_content_exact": _canonical_sha256(actual) == plan["baseline_content_sha256"],
        "target_revision_one_present": len(target_rows) == 1 and target_rows[0]["revision"] == 1,
        "one_partitioned_baseline_snapshot": len(snapshots) == 1
        and snapshots[0]["operation"] == "append",
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


def _validate_barriers(args: argparse.Namespace) -> None:
    if not args.ready_marker or not args.release_marker:
        raise ValueError("concurrent partition delete requires both barrier paths")
    for path in (args.ready_marker, args.release_marker):
        if not BARRIER_RE.fullmatch(path.as_posix()):
            raise ValueError("unsafe partition delete conflict barrier path")


def _concurrent_delete(
    spark,
    args: argparse.Namespace,
    plan: dict[str, Any],
) -> dict[str, Any]:
    _validate_barriers(args)
    snapshots_before = _snapshots(spark, args.table)
    baseline_rows = _rows(spark.table(args.table))
    if (
        len(snapshots_before) != 1
        or snapshots_before[0]["snapshot_id"] != args.baseline_snapshot_id
        or list(baseline_rows) != plan["baseline_rows"]
    ):
        raise RuntimeError("Spark partition delete did not start from the exact baseline")

    iceberg_table = _iceberg_table(spark, args.table)
    provider_baseline = str(iceberg_table.currentSnapshot().snapshotId())
    if provider_baseline != args.baseline_snapshot_id:
        raise RuntimeError("Iceberg partition delete intent did not bind the baseline")
    target_filter = _key_expression(spark, plan["target_road_id"])
    delete_intent = (
        iceberg_table.newOverwrite()
        .overwriteByRowFilter(target_filter)
        .validateFromSnapshot(int(args.baseline_snapshot_id))
        .conflictDetectionFilter(target_filter)
        .validateNoConflictingData()
        .validateNoConflictingDeletes()
        .set("gda.commit-token", plan["spark_delete_token"])
        .set("gda.operation", "partition-delete-by-road-id")
    )
    ready_payload = {
        "schema": "gda.spark_iceberg_partition_delete_conflict_ready.v1",
        "baseline_snapshot_id": args.baseline_snapshot_id,
        "commit_token": plan["spark_delete_token"],
        "target_road_id": plan["target_road_id"],
    }
    args.ready_marker.write_text(
        json.dumps(ready_payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    deadline = time.monotonic() + args.barrier_timeout_seconds
    while time.monotonic() < deadline and not args.release_marker.is_file():
        time.sleep(0.1)
    if not args.release_marker.is_file():
        raise RuntimeError("Spark partition delete conflict barrier timed out")

    conflict: dict[str, Any] | None = None
    delete_committed = False
    try:
        delete_intent.commit()
        delete_committed = True
    except Exception as exc:  # Spark wraps the Iceberg provider exception.
        conflict = classify_conflict_error(exc)

    release = json.loads(args.release_marker.read_text(encoding="utf-8"))
    spark.catalog.clearCache()
    spark.catalog.refreshTable(args.table)
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    target_rows = [row for row in actual if row["road_id"] == plan["target_road_id"]]
    token_snapshots = sum(item["commit_token"] == plan["spark_delete_token"] for item in snapshots)
    checks = {
        "ready_marker_persisted": args.ready_marker.is_file(),
        "release_marker_observed": release
        == {
            "schema": "gda.spark_iceberg_partition_delete_conflict_release.v1",
            "flink_snapshot_id": release.get("flink_snapshot_id"),
            "flink_commit_token": plan["flink_commit_token"],
        },
        "stale_partition_delete_rejected": not delete_committed,
        "iceberg_validation_failure_observed": bool(
            conflict and conflict["is_iceberg_validation_failure"]
        ),
        "flink_state_preserved_after_conflict": list(actual) == plan["after_flink_rows"],
        "target_revisions_one_and_two_visible": sorted(row["revision"] for row in target_rows)
        == [1, 2],
        "flink_payload_visible_once": sum(
            row["commit_token"] == plan["flink_commit_token"] for row in target_rows
        )
        == 1,
        "delete_token_absent_after_conflict": token_snapshots == 0,
        "catalog_remained_on_flink_snapshot": (
            len(snapshots) == 2
            and snapshots[0]["snapshot_id"] == args.baseline_snapshot_id
            and snapshots[1]["snapshot_id"] == release.get("flink_snapshot_id")
            and snapshots[1]["parent_id"] == args.baseline_snapshot_id
            and all(item["operation"] == "append" for item in snapshots)
        ),
    }
    return {
        "phase": "concurrent-delete",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "conflict": conflict,
        "delete_committed": delete_committed,
        "target_revisions": sorted(row["revision"] for row in target_rows),
        "delete_commit_token_snapshot_count": token_snapshots,
    }


def _retry(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    current = _rows(spark.table(args.table))
    before = _snapshots(spark, args.table)
    fresh_state_exact = (
        list(current) == plan["after_flink_rows"]
        and len(before) == 2
        and before[-1]["snapshot_id"] == args.flink_snapshot_id
    )
    if not fresh_state_exact:
        raise RuntimeError("partition delete retry did not read the exact Flink state")
    target_rows = [row for row in current if row["road_id"] == plan["target_road_id"]]
    if len(target_rows) != 2 or sorted(row["revision"] for row in target_rows) != [1, 2]:
        raise RuntimeError("partition delete retry cannot identify both target revisions")
    iceberg_table = _iceberg_table(spark, args.table)
    iceberg_table.refresh()
    if str(iceberg_table.currentSnapshot().snapshotId()) != args.flink_snapshot_id:
        raise RuntimeError("partition delete provider state drifted before retry")
    (
        iceberg_table.newDelete()
        .deleteFromRowFilter(_key_expression(spark, plan["target_road_id"]))
        .set("gda.commit-token", plan["spark_delete_token"])
        .set("gda.operation", "partition-delete-by-road-id")
        .commit()
    )
    spark.catalog.clearCache()
    spark.catalog.refreshTable(args.table)
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    token_count = sum(item["commit_token"] == plan["spark_delete_token"] for item in snapshots)
    checks = {
        "retry_read_fresh_flink_state": fresh_state_exact,
        "both_target_revisions_removed": all(
            row["road_id"] != plan["target_road_id"] for row in actual
        ),
        "non_target_partitions_preserved": list(actual) == plan["final_rows"],
        "delete_commit_token_committed_once": token_count == 1,
        "retry_delete_parent_is_flink_snapshot": (
            len(snapshots) == 3
            and snapshots[-1]["operation"] == "delete"
            and snapshots[-1]["parent_id"] == args.flink_snapshot_id
            and snapshots[-1]["commit_token"] == plan["spark_delete_token"]
        ),
    }
    return {
        "phase": "retry",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "retry_snapshot_id": snapshots[-1]["snapshot_id"],
        "delete_commit_token_snapshot_count": token_count,
    }


def _verify(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    baseline_rows = _rows(
        spark.read.option("snapshot-id", args.baseline_snapshot_id).table(args.table)
    )
    flink_rows = _rows(spark.read.option("snapshot-id", args.flink_snapshot_id).table(args.table))
    chain_exact = len(snapshots) == 3 and all(
        snapshots[index]["parent_id"] == snapshots[index - 1]["snapshot_id"]
        for index in range(1, len(snapshots))
    )
    token_count = sum(item["commit_token"] == plan["spark_delete_token"] for item in snapshots)
    checks = {
        "final_rows_exact_without_non_target_loss": list(actual) == plan["final_rows"],
        "final_content_exact": _canonical_sha256(actual) == plan["final_content_sha256"],
        "target_partition_absent": all(row["road_id"] != plan["target_road_id"] for row in actual),
        "two_non_target_partitions_remain": len(actual) == 2
        and len({row["road_id"] for row in actual}) == 2,
        "append_append_delete_chain_exact": chain_exact
        and [item["operation"] for item in snapshots] == ["append", "append", "delete"],
        "delete_commit_token_unique": token_count == 1,
        "baseline_time_travel_exact": list(baseline_rows) == plan["baseline_rows"],
        "flink_time_travel_exact": list(flink_rows) == plan["after_flink_rows"],
    }
    return {
        "phase": "verify",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "delete_commit_token_snapshot_count": token_count,
        "baseline_time_travel_rows": len(baseline_rows),
        "flink_time_travel_rows": len(flink_rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=("baseline", "concurrent-delete", "retry", "verify"),
    )
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
        elif args.phase == "concurrent-delete":
            phase = _concurrent_delete(spark, args, plan)
        elif args.phase == "retry":
            phase = _retry(spark, args, plan)
        else:
            phase = _verify(spark, args, plan)
    finally:
        spark.stop()
    report = {
        "schema": "gda.spark_flink_iceberg_partition_delete_conflict_phase.v1",
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
