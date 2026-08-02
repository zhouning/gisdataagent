#!/usr/bin/env python3
"""Create a Spark baseline and verify one Flink position-delete commit."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.spark_chongqing_osm_iceberg_concurrent_append import _schema
from scripts.spark_chongqing_osm_iceberg_delete_conflict import (
    _iceberg_table,
    _snapshots,
)
from scripts.spark_chongqing_osm_iceberg_interop import CATALOG, _canonical_sha256, _spark
from scripts.spark_chongqing_osm_iceberg_position_delete_interop import (
    _data_files,
    _delete_files,
    _position_deletes,
    _rows,
    is_single_position_delete_file,
    position_targets_single_data_file,
)


def _physical_rows(spark, table: str) -> list[dict[str, Any]]:
    return [
        {
            "road_id": int(row["road_id"]),
            "file_path": row["file_path"],
            "pos": int(row["pos"]),
        }
        for row in spark.sql(
            f"SELECT road_id, _file AS file_path, _pos AS pos "
            f"FROM {table} ORDER BY road_id"
        ).collect()
    ]


def _baseline(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    namespace = args.table.split(".")[1]
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.{namespace}")
    if spark.catalog.tableExists(args.table):
        raise RuntimeError("isolated Flink position delete table already exists")
    frame = spark.createDataFrame(plan["baseline_rows"], schema=_schema()).coalesce(1)
    (
        frame.writeTo(args.table)
        .using("iceberg")
        .tableProperty("format-version", "2")
        .tableProperty("write.delete.mode", "merge-on-read")
        .tableProperty("gda.acceptance", "flink-spark-position-delete-interop")
        .tableProperty("gda.source_sha256", plan["source"]["source_parquet_sha256"])
        .create()
    )
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    data_files = _data_files(spark, args.table)
    delete_files = _delete_files(spark, args.table)
    physical_rows = _physical_rows(spark, args.table)
    targets = [
        row for row in physical_rows if row["road_id"] == plan["target_road_id"]
    ]
    properties = dict(_iceberg_table(spark, args.table).properties())
    physical_binding_exact = (
        len(data_files) == 1
        and len(physical_rows) == len(plan["baseline_rows"])
        and [row["road_id"] for row in physical_rows]
        == [row["road_id"] for row in plan["baseline_rows"]]
        and len({row["pos"] for row in physical_rows}) == len(physical_rows)
        and all(
            row["pos"] >= 0 and row["file_path"] == data_files[0]["file_path"]
            for row in physical_rows
        )
        and len(targets) == 1
    )
    checks = {
        "baseline_rows_exact": list(actual) == plan["baseline_rows"],
        "baseline_content_exact": _canonical_sha256(actual)
        == plan["baseline_content_sha256"],
        "one_three_row_data_file": len(data_files) == 1
        and data_files[0]["content"] == 0
        and data_files[0]["record_count"] == 3,
        "target_physical_position_bound": physical_binding_exact,
        "merge_on_read_delete_enabled": properties.get("write.delete.mode")
        == "merge-on-read",
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
        "physical_rows": physical_rows,
        "baseline_snapshot_id": snapshots[0]["snapshot_id"],
        "target_data_file_path": targets[0]["file_path"] if len(targets) == 1 else None,
        "target_row_position": targets[0]["pos"] if len(targets) == 1 else None,
    }


def _verify(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    actual = _rows(spark.table(args.table))
    baseline = _rows(
        spark.read.option("snapshot-id", args.baseline_snapshot_id).table(args.table)
    )
    snapshots = _snapshots(spark, args.table)
    data_files = _data_files(spark, args.table)
    delete_files = _delete_files(spark, args.table)
    positions = _position_deletes(spark, args.table)
    target_position_exact = positions == [
        {
            "file_path": args.expected_data_file_path,
            "pos": int(args.expected_row_position),
        }
    ]
    checks = {
        "final_rows_exact": list(actual) == plan["final_rows"],
        "final_content_exact": _canonical_sha256(actual) == plan["final_content_sha256"],
        "target_road_absent": all(
            row["road_id"] != plan["target_road_id"] for row in actual
        ),
        "baseline_time_travel_exact": list(baseline) == plan["baseline_rows"],
        "original_data_file_retained": len(data_files) == 1
        and data_files[0]["record_count"] == 3
        and data_files[0]["file_path"] == args.expected_data_file_path,
        "one_position_delete_file_materialized": is_single_position_delete_file(
            delete_files
        ),
        "position_targets_original_data_file": position_targets_single_data_file(
            data_files, positions
        )
        and target_position_exact,
        "append_delete_snapshot_chain_exact": len(snapshots) == 2
        and [item["operation"] for item in snapshots] == ["append", "delete"]
        and snapshots[0]["snapshot_id"] == args.baseline_snapshot_id
        and snapshots[1]["snapshot_id"] == args.delete_snapshot_id
        and snapshots[1]["parent_id"] == args.baseline_snapshot_id,
        "flink_commit_token_bound": len(snapshots) == 2
        and snapshots[1]["commit_token"] == plan["flink_commit_token"],
    }
    return {
        "phase": "verify",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "data_files": data_files,
        "delete_files": delete_files,
        "position_deletes": positions,
        "baseline_time_travel_rows": len(baseline),
        "delete_snapshot_id": snapshots[-1]["snapshot_id"],
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
    parser.add_argument("--delete-snapshot-id")
    parser.add_argument("--expected-data-file-path")
    parser.add_argument("--expected-row-position", type=int)
    args = parser.parse_args()
    if args.phase == "verify" and not all(
        (
            args.baseline_snapshot_id,
            args.delete_snapshot_id,
            args.expected_data_file_path,
            args.expected_row_position is not None,
        )
    ):
        parser.error("verify requires snapshot and physical-position bindings")
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
        "schema": "gda.spark_flink_position_delete_write_phase.v1",
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
