#!/usr/bin/env python3
"""Create two Spark data files and verify one Flink RowDelta deleting both positions."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.spark_chongqing_osm_iceberg_concurrent_append import _schema
from scripts.spark_chongqing_osm_iceberg_delete_conflict import _snapshots
from scripts.spark_chongqing_osm_iceberg_interop import CATALOG, _canonical_sha256, _spark
from scripts.spark_chongqing_osm_iceberg_position_delete_interop import (
    _data_files,
    _delete_files,
    _position_deletes,
    _rows,
)


def _physical_rows(frame) -> list[dict[str, Any]]:
    return [
        {
            "road_id": int(row["road_id"]),
            "file_path": str(row["file_path"]),
            "pos": int(row["pos"]),
        }
        for row in frame.select("road_id", "_file", "_pos")
        .withColumnRenamed("_file", "file_path")
        .withColumnRenamed("_pos", "pos")
        .orderBy("road_id")
        .collect()
    ]


def _baseline(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    namespace = args.table.split(".")[1]
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.{namespace}")
    if spark.catalog.tableExists(args.table):
        raise RuntimeError("isolated multi-file position delete table already exists")
    rows = plan["baseline_rows"]
    target_ids = plan["target_road_ids"]
    frame = spark.createDataFrame(rows, schema=_schema())
    first = frame.where(f"road_id = {int(target_ids[0])}").coalesce(1)
    remainder = frame.where(f"road_id <> {int(target_ids[0])}").coalesce(1)
    (
        first.writeTo(args.table)
        .using("iceberg")
        .tableProperty("format-version", "2")
        .tableProperty("write.delete.mode", "merge-on-read")
        .tableProperty("gda.acceptance", "flink-spark-multi-file-position-delete")
        .tableProperty("gda.source_sha256", plan["source"]["source_parquet_sha256"])
        .create()
    )
    remainder.writeTo(args.table).append()
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    data_files = _data_files(spark, args.table)
    delete_files = _delete_files(spark, args.table)
    physical_rows = _physical_rows(spark.table(args.table))
    bindings = [row for row in physical_rows if row["road_id"] in target_ids]
    checks = {
        "baseline_rows_exact": list(actual) == rows,
        "baseline_content_exact": _canonical_sha256(actual) == plan["baseline_content_sha256"],
        "two_data_files_materialized": len(data_files) == 2
        and sorted(item["record_count"] for item in data_files) == [1, 2],
        "two_append_snapshots": len(snapshots) == 2
        and [item["operation"] for item in snapshots] == ["append", "append"],
        "target_bindings_exact": len(bindings) == 2
        and len({item["file_path"] for item in bindings}) == 2
        and all(item["pos"] >= 0 for item in bindings),
        "no_baseline_delete_files": delete_files == [],
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
        "physical_rows": physical_rows,
        "target_bindings": bindings,
        "baseline_snapshot_id": snapshots[-1]["snapshot_id"],
    }


def _verify(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    actual = _rows(spark.table(args.table))
    baseline_frame = spark.read.option("snapshot-id", args.baseline_snapshot_id).table(args.table)
    baseline = _rows(baseline_frame)
    baseline_physical = _physical_rows(baseline_frame)
    expected_bindings = sorted(
        (row["file_path"], row["pos"])
        for row in baseline_physical
        if row["road_id"] in plan["target_road_ids"]
    )
    snapshots = _snapshots(spark, args.table)
    data_files = _data_files(spark, args.table)
    delete_files = _delete_files(spark, args.table)
    positions = _position_deletes(spark, args.table)
    observed_bindings = sorted((item["file_path"], item["pos"]) for item in positions)
    checks = {
        "final_rows_exact": list(actual) == plan["final_rows"],
        "final_content_exact": _canonical_sha256(actual) == plan["final_content_sha256"],
        "both_target_roads_absent": all(
            row["road_id"] not in plan["target_road_ids"] for row in actual
        ),
        "baseline_time_travel_exact": list(baseline) == plan["baseline_rows"],
        "original_data_files_retained": len(data_files) == 2
        and sorted(item["record_count"] for item in data_files) == [1, 2],
        "one_multi_row_position_delete_file": len(delete_files) == 1
        and delete_files[0]["content"] == 1
        and delete_files[0]["file_format"].upper() == "PARQUET"
        and delete_files[0]["record_count"] == 2
        and delete_files[0]["equality_ids"] == [],
        "both_file_positions_bound_exactly": observed_bindings == expected_bindings
        and len({file_path for file_path, _ in observed_bindings}) == 2,
        "snapshot_chain_exact": len(snapshots) == 3
        and [item["operation"] for item in snapshots] == ["append", "append", "delete"]
        and snapshots[0]["snapshot_id"] != args.baseline_snapshot_id
        and snapshots[1]["snapshot_id"] == args.baseline_snapshot_id
        and snapshots[2]["parent_id"] == args.baseline_snapshot_id,
    }
    return {
        "phase": "verify",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "actual_rows": list(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "data_files": data_files,
        "delete_files": delete_files,
        "position_deletes": positions,
        "expected_bindings": expected_bindings,
        "observed_bindings": observed_bindings,
        "baseline_time_travel_rows": len(baseline),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("baseline", "verify"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--warehouse-uri", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--endpoint-url", default="http://minio:9000")
    parser.add_argument("--baseline-snapshot-id")
    args = parser.parse_args()
    if args.phase == "verify" and not args.baseline_snapshot_id:
        parser.error("verify requires --baseline-snapshot-id")
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        if not os.environ.get(name):
            raise RuntimeError(f"missing required environment variable {name}")

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    spark = _spark(args)
    try:
        spark.sparkContext.setLogLevel("WARN")
        phase = (
            _baseline(spark, args, plan)
            if args.phase == "baseline"
            else _verify(spark, args, plan)
        )
    finally:
        spark.stop()
    report = {
        "schema": "gda.spark_flink_multi_file_position_delete_phase.v1",
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
