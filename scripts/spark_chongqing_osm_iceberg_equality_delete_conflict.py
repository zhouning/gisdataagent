#!/usr/bin/env python3
"""Reject a stale Spark update after a same-key Flink equality delete."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.spark_chongqing_osm_iceberg_concurrent_append import _schema
from scripts.spark_chongqing_osm_iceberg_delete_conflict import (
    _iceberg_table,
    _key_expression,
    _snapshots,
)
from scripts.spark_chongqing_osm_iceberg_equality_delete_interop import (
    _identifier_evidence,
    _rows,
    is_single_equality_delete_file,
)
from scripts.spark_chongqing_osm_iceberg_interop import (
    CATALOG,
    _canonical_sha256,
    _spark,
)
from scripts.spark_chongqing_osm_iceberg_overwrite_conflict import (
    classify_conflict_error,
)
from scripts.spark_chongqing_osm_iceberg_position_delete_interop import (
    _data_files,
    _delete_files,
)

BARRIER_RE = re.compile(
    r"^/workspace/\.tmp/source-sync-certification/"
    r"flink_iceberg_equality_delete_conflict_[0-9a-f]{10}/"
    r"spark-(?:ready|release)\.json$"
)


def _baseline(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    namespace = args.table.split(".")[1]
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.{namespace}")
    if spark.catalog.tableExists(args.table):
        raise RuntimeError("isolated equality delete conflict table already exists")
    frame = spark.createDataFrame(plan["baseline_rows"], schema=_schema()).coalesce(1)
    spark.sql(
        f"CREATE TABLE {args.table} ("
        "road_id BIGINT NOT NULL, revision INT NOT NULL, "
        "road_name_base64 STRING NOT NULL, geometry_sha256 STRING NOT NULL, "
        "writer_engine STRING NOT NULL, commit_token STRING) USING iceberg "
        "TBLPROPERTIES ("
        "'format-version'='2', 'write.upsert.enabled'='true', "
        "'write.delete.mode'='merge-on-read', "
        "'gda.acceptance'='flink-spark-equality-delete-conflict', "
        f"'gda.source_sha256'='{plan['source']['source_parquet_sha256']}')"
    )
    frame.writeTo(args.table).append()
    iceberg = _iceberg_table(spark, args.table)
    iceberg.updateSchema().setIdentifierFields(
        spark._jvm.java.util.Collections.singletonList("road_id")  # noqa: SLF001
    ).commit()
    iceberg.refresh()
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    data_files = _data_files(spark, args.table)
    identifiers = _identifier_evidence(spark, args.table)
    checks = {
        "baseline_rows_exact": list(actual) == plan["baseline_rows"],
        "baseline_content_exact": _canonical_sha256(actual)
        == plan["baseline_content_sha256"],
        "road_id_identifier_field_exact": identifiers["road_id_is_identifier"],
        "one_three_row_data_file": len(data_files) == 1
        and data_files[0]["record_count"] == 3,
        "one_append_snapshot": len(snapshots) == 1
        and snapshots[0]["operation"] == "append",
    }
    return {
        "phase": "baseline",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "data_files": data_files,
        "identifiers": identifiers,
        "baseline_snapshot_id": snapshots[0]["snapshot_id"],
    }


def _validate_barriers(args: argparse.Namespace) -> None:
    if not args.ready_marker or not args.release_marker:
        raise ValueError("concurrent equality delete requires both barrier paths")
    for path in (args.ready_marker, args.release_marker):
        if not BARRIER_RE.fullmatch(path.as_posix()):
            raise ValueError("unsafe equality delete conflict barrier path")


def _concurrent_update(
    spark, args: argparse.Namespace, plan: dict[str, Any]
) -> dict[str, Any]:
    _validate_barriers(args)
    snapshots_before = _snapshots(spark, args.table)
    baseline_rows = _rows(spark.table(args.table))
    if (
        len(snapshots_before) != 1
        or snapshots_before[0]["snapshot_id"] != args.baseline_snapshot_id
        or list(baseline_rows) != plan["baseline_rows"]
    ):
        raise RuntimeError("Spark update intent did not bind the exact baseline")

    iceberg = _iceberg_table(spark, args.table)
    if str(iceberg.currentSnapshot().snapshotId()) != args.baseline_snapshot_id:
        raise RuntimeError("provider update intent did not bind the baseline")
    target_filter = _key_expression(spark, plan["target_road_id"])
    update_intent = (
        iceberg.newOverwrite()
        .overwriteByRowFilter(target_filter)
        .validateFromSnapshot(int(args.baseline_snapshot_id))
        .conflictDetectionFilter(target_filter)
        .validateNoConflictingData()
        .validateNoConflictingDeletes()
        .set("gda.commit-token", plan["spark_update_token"])
        .set("gda.operation", "update-after-equality-delete")
    )
    ready = {
        "schema": "gda.spark_equality_delete_conflict_ready.v1",
        "baseline_snapshot_id": args.baseline_snapshot_id,
        "commit_token": plan["spark_update_token"],
        "target_road_id": plan["target_road_id"],
        "stale_content_sha256": plan["stale_update_content_sha256"],
    }
    args.ready_marker.write_text(
        json.dumps(ready, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    deadline = time.monotonic() + args.barrier_timeout_seconds
    while time.monotonic() < deadline and not args.release_marker.is_file():
        time.sleep(0.1)
    if not args.release_marker.is_file():
        raise RuntimeError("Spark equality delete conflict barrier timed out")

    conflict: dict[str, Any] | None = None
    update_committed = False
    try:
        update_intent.commit()
        update_committed = True
    except Exception as exc:  # Spark wraps the Iceberg provider exception.
        conflict = classify_conflict_error(exc)

    release = json.loads(args.release_marker.read_text(encoding="utf-8"))
    spark.catalog.clearCache()
    spark.catalog.refreshTable(args.table)
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    delete_files = _delete_files(spark, args.table)
    identifiers = _identifier_evidence(spark, args.table)
    token_count = sum(
        item["commit_token"] == plan["spark_update_token"] for item in snapshots
    )
    checks = {
        "ready_marker_persisted": args.ready_marker.is_file(),
        "release_marker_observed": release
        == {
            "schema": "gda.spark_equality_delete_conflict_release.v1",
            "flink_snapshot_id": release.get("flink_snapshot_id"),
            "flink_commit_token": plan["flink_commit_token"],
        },
        "stale_update_rejected": not update_committed,
        "iceberg_validation_failure_observed": bool(
            conflict and conflict["is_iceberg_validation_failure"]
        ),
        "flink_delete_state_preserved": list(actual) == plan["after_flink_rows"],
        "target_remained_absent": all(
            row["road_id"] != plan["target_road_id"] for row in actual
        ),
        "spark_update_snapshot_absent": token_count == 0,
        "catalog_remained_on_flink_delete": len(snapshots) == 2
        and snapshots[-1]["snapshot_id"] == release.get("flink_snapshot_id")
        and snapshots[-1]["parent_id"] == args.baseline_snapshot_id,
        "equality_delete_file_preserved": is_single_equality_delete_file(
            delete_files,
            road_id_field_id=identifiers["road_id_field_id"],
        ),
    }
    return {
        "phase": "concurrent-update",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "delete_files": delete_files,
        "conflict": conflict,
        "update_committed": update_committed,
        "spark_update_token_count": token_count,
    }


def _reconcile(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    current = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    fresh_state_exact = (
        list(current) == plan["after_flink_rows"]
        and len(snapshots) == 2
        and snapshots[-1]["snapshot_id"] == args.flink_snapshot_id
    )
    target_absent = all(
        row["road_id"] != plan["target_road_id"] for row in current
    )
    checks = {
        "fresh_flink_delete_state_read": fresh_state_exact,
        "target_absence_confirmed": target_absent,
        "implicit_resurrection_refused": fresh_state_exact and target_absent,
        "reconciliation_created_no_snapshot": len(snapshots) == 2,
    }
    return {
        "phase": "reconcile",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(current),
        "content_sha256": _canonical_sha256(current),
        "snapshots": snapshots,
        "retry_authorized": False,
        "decision": "delete-wins-target-absent-no-resurrection",
    }


def _verify(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    baseline = _rows(
        spark.read.option("snapshot-id", args.baseline_snapshot_id).table(args.table)
    )
    delete_files = _delete_files(spark, args.table)
    identifiers = _identifier_evidence(spark, args.table)
    checks = {
        "final_delete_state_exact": list(actual) == plan["after_flink_rows"],
        "final_content_exact": _canonical_sha256(actual)
        == plan["after_flink_content_sha256"],
        "target_not_resurrected": all(
            row["road_id"] != plan["target_road_id"] for row in actual
        ),
        "append_delete_chain_exact": len(snapshots) == 2
        and [item["operation"] for item in snapshots] == ["append", "delete"]
        and snapshots[-1]["snapshot_id"] == args.flink_snapshot_id
        and snapshots[-1]["parent_id"] == args.baseline_snapshot_id,
        "baseline_time_travel_exact": list(baseline) == plan["baseline_rows"],
        "equality_delete_still_current": is_single_equality_delete_file(
            delete_files,
            road_id_field_id=identifiers["road_id_field_id"],
        ),
        "spark_update_token_absent": all(
            item["commit_token"] != plan["spark_update_token"] for item in snapshots
        ),
    }
    return {
        "phase": "verify",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "delete_files": delete_files,
        "baseline_time_travel_rows": len(baseline),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase", choices=("baseline", "concurrent-update", "reconcile", "verify")
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
    if args.phase in ("reconcile", "verify") and not args.flink_snapshot_id:
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
        elif args.phase == "reconcile":
            phase = _reconcile(spark, args, plan)
        else:
            phase = _verify(spark, args, plan)
    finally:
        spark.stop()
    report = {
        "schema": "gda.spark_flink_equality_delete_conflict_phase.v1",
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
