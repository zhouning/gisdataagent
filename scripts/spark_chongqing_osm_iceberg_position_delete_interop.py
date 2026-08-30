#!/usr/bin/env python3
"""Create and verify one Spark MOR position delete for Flink interoperability."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.spark_chongqing_osm_iceberg_concurrent_append import COLUMNS, _schema
from scripts.spark_chongqing_osm_iceberg_delete_conflict import _snapshots
from scripts.spark_chongqing_osm_iceberg_interop import (
    CATALOG,
    _canonical_sha256,
    _spark,
)


def _rows(frame) -> tuple[dict[str, Any], ...]:
    return tuple(
        {key: row[key] for key in COLUMNS}
        for row in frame.select(*COLUMNS).orderBy("road_id").collect()
    )


def _data_files(spark, table: str) -> list[dict[str, Any]]:
    return [
        {
            "content": int(row["content"]),
            "file_path": row["file_path"],
            "file_format": row["file_format"],
            "record_count": int(row["record_count"]),
        }
        for row in spark.sql(
            f"SELECT content, file_path, file_format, record_count "
            f"FROM {table}.data_files ORDER BY file_path"
        ).collect()
    ]


def _delete_files(spark, table: str) -> list[dict[str, Any]]:
    return [
        {
            "content": int(row["content"]),
            "file_path": row["file_path"],
            "file_format": row["file_format"],
            "record_count": int(row["record_count"]),
            "equality_ids": list(row["equality_ids"] or []),
        }
        for row in spark.sql(
            f"SELECT content, file_path, file_format, record_count, equality_ids "
            f"FROM {table}.delete_files ORDER BY file_path"
        ).collect()
    ]


def _position_deletes(spark, table: str) -> list[dict[str, Any]]:
    return [
        {"file_path": row["file_path"], "pos": int(row["pos"])}
        for row in spark.sql(
            f"SELECT file_path, pos FROM {table}.position_deletes ORDER BY file_path, pos"
        ).collect()
    ]


def is_single_position_delete_file(delete_files: list[dict[str, Any]]) -> bool:
    return (
        len(delete_files) == 1
        and delete_files[0]["content"] == 1
        and delete_files[0]["file_format"].upper() == "PARQUET"
        and delete_files[0]["record_count"] == 1
        and delete_files[0]["equality_ids"] == []
    )


def position_targets_single_data_file(
    data_files: list[dict[str, Any]], positions: list[dict[str, Any]]
) -> bool:
    return (
        len(data_files) == 1
        and len(positions) == 1
        and positions[0]["pos"] >= 0
        and positions[0]["file_path"] == data_files[0]["file_path"]
    )


def _baseline(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    namespace = args.table.split(".")[1]
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.{namespace}")
    if spark.catalog.tableExists(args.table):
        raise RuntimeError("isolated position delete table already exists")
    frame = spark.createDataFrame(plan["baseline_rows"], schema=_schema()).coalesce(1)
    (
        frame.writeTo(args.table)
        .using("iceberg")
        .tableProperty("format-version", "2")
        .tableProperty("write.delete.mode", "merge-on-read")
        .tableProperty("gda.acceptance", "spark-flink-position-delete-interop")
        .tableProperty("gda.source_sha256", plan["source"]["source_parquet_sha256"])
        .create()
    )
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    data_files = _data_files(spark, args.table)
    delete_files = _delete_files(spark, args.table)
    checks = {
        "baseline_rows_exact": list(actual) == plan["baseline_rows"],
        "baseline_content_exact": _canonical_sha256(actual) == plan["baseline_content_sha256"],
        "one_three_row_data_file": len(data_files) == 1
        and data_files[0]["content"] == 0
        and data_files[0]["record_count"] == 3,
        "no_baseline_delete_files": delete_files == [],
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
        "delete_files": delete_files,
        "baseline_snapshot_id": snapshots[0]["snapshot_id"],
    }


def _delete(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    current = _rows(spark.table(args.table))
    before = _snapshots(spark, args.table)
    if (
        list(current) != plan["baseline_rows"]
        or len(before) != 1
        or before[0]["snapshot_id"] != args.baseline_snapshot_id
    ):
        raise RuntimeError("position delete did not start from the exact baseline")
    spark.sql(
        f"DELETE FROM {args.table} WHERE road_id = {int(plan['target_road_id'])}"
    ).collect()
    spark.catalog.clearCache()
    spark.catalog.refreshTable(args.table)
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    data_files = _data_files(spark, args.table)
    delete_files = _delete_files(spark, args.table)
    positions = _position_deletes(spark, args.table)
    checks = {
        "final_rows_exact": list(actual) == plan["final_rows"],
        "final_content_exact": _canonical_sha256(actual) == plan["final_content_sha256"],
        "target_road_absent": all(
            row["road_id"] != plan["target_road_id"] for row in actual
        ),
        "original_data_file_retained": len(data_files) == 1
        and data_files[0]["record_count"] == 3,
        "one_position_delete_file_materialized": is_single_position_delete_file(
            delete_files
        ),
        "one_position_targets_original_file": position_targets_single_data_file(
            data_files, positions
        ),
        "append_delete_snapshot_chain": len(snapshots) == 2
        and [item["operation"] for item in snapshots] == ["append", "delete"]
        and snapshots[1]["parent_id"] == args.baseline_snapshot_id,
    }
    return {
        "phase": "delete",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "data_files": data_files,
        "delete_files": delete_files,
        "position_deletes": positions,
        "delete_snapshot_id": snapshots[-1]["snapshot_id"],
    }


def _verify(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    actual = _rows(spark.table(args.table))
    baseline = _rows(
        spark.read.option("snapshot-id", args.baseline_snapshot_id).table(args.table)
    )
    snapshots = _snapshots(spark, args.table)
    delete_files = _delete_files(spark, args.table)
    positions = _position_deletes(spark, args.table)
    checks = {
        "final_rows_exact": list(actual) == plan["final_rows"],
        "final_content_exact": _canonical_sha256(actual) == plan["final_content_sha256"],
        "baseline_time_travel_exact": list(baseline) == plan["baseline_rows"],
        "delete_snapshot_is_current": len(snapshots) == 2
        and snapshots[-1]["snapshot_id"] == args.delete_snapshot_id,
        "position_delete_file_still_current": len(delete_files) == 1
        and delete_files[0]["content"] == 1,
        "one_deleted_position_still_readable": len(positions) == 1,
    }
    return {
        "phase": "verify",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "delete_files": delete_files,
        "position_deletes": positions,
        "baseline_time_travel_rows": len(baseline),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("baseline", "delete", "verify"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--warehouse-uri", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--endpoint-url", default="http://minio:9000")
    parser.add_argument("--baseline-snapshot-id")
    parser.add_argument("--delete-snapshot-id")
    args = parser.parse_args()
    if args.phase != "baseline" and not args.baseline_snapshot_id:
        parser.error(f"{args.phase} requires --baseline-snapshot-id")
    if args.phase == "verify" and not args.delete_snapshot_id:
        parser.error("verify requires --delete-snapshot-id")
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        if not os.environ.get(name):
            raise RuntimeError(f"missing required environment variable {name}")

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    spark = _spark(args)
    try:
        spark.sparkContext.setLogLevel("WARN")
        if args.phase == "baseline":
            phase = _baseline(spark, args, plan)
        elif args.phase == "delete":
            phase = _delete(spark, args, plan)
        else:
            phase = _verify(spark, args, plan)
    finally:
        spark.stop()
    report = {
        "schema": "gda.spark_flink_iceberg_position_delete_phase.v1",
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
