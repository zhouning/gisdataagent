#!/usr/bin/env python3
"""Exercise a bounded Iceberg partition-spec evolution and mixed-spec read."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.iceberg_file_scope import _stable_partition_value
from scripts.spark_chongqing_osm_iceberg_concurrent_append import COLUMNS, _schema
from scripts.spark_chongqing_osm_iceberg_delete_conflict import _iceberg_table
from scripts.spark_chongqing_osm_iceberg_interop import (
    CATALOG,
    _canonical_sha256,
    _snapshots,
    _spark,
)


def _rows(frame) -> tuple[dict[str, Any], ...]:
    return tuple(
        {key: row[key] for key in COLUMNS}
        for row in frame.select(*COLUMNS)
        .orderBy("road_id", "revision", "writer_engine")
        .collect()
    )


def _file_inventory(spark, table: str) -> tuple[dict[str, Any], ...]:
    frame = spark.table(f"{table}.files")
    required = {"content", "file_path", "record_count", "spec_id"}
    missing = required.difference(frame.columns)
    if missing:
        raise RuntimeError(f"Iceberg files metadata missing required columns: {sorted(missing)}")
    rows = []
    columns = ["content", "file_path", "record_count", "spec_id"]
    has_partition_column = "partition" in frame.columns
    if has_partition_column:
        columns.insert(2, "partition")
    for row in frame.select(*columns).collect():
        if int(row["content"]) != 0:
            continue
        rows.append(
            {
                "file_path": str(row["file_path"]),
                "partition": (
                    _stable_partition_value(row["partition"])
                    if has_partition_column
                    else {}
                ),
                "record_count": int(row["record_count"]),
                "spec_id": int(row["spec_id"]),
            }
        )
    return tuple(sorted(rows, key=lambda item: (item["spec_id"], item["file_path"])))


def _spec_fields(spark, table: str) -> list[dict[str, str]]:
    spec = _iceberg_table(spark, table).spec()
    return [
        {"name": str(field.name()), "transform": str(field.transform())}
        for field in spec.fields()
    ]


def _baseline(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    namespace = args.table.split(".")[1]
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.{namespace}")
    if spark.catalog.tableExists(args.table):
        raise RuntimeError("isolated partition evolution table already exists")
    frame = spark.createDataFrame(plan["baseline_rows"], schema=_schema())
    (
        frame.writeTo(args.table)
        .using("iceberg")
        .tableProperty("format-version", "2")
        .tableProperty("gda.acceptance", "spark-flink-partition-evolution")
        .tableProperty("gda.source_sha256", plan["source"]["source_parquet_sha256"])
        .create()
    )
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    files = _file_inventory(spark, args.table)
    checks = {
        "baseline_rows_exact": list(actual) == plan["baseline_rows"],
        "baseline_content_exact": _canonical_sha256(actual)
        == plan["baseline_content_sha256"],
        "baseline_spec_is_unpartitioned": _spec_fields(spark, args.table) == [],
        "baseline_files_use_spec_zero": len(files) >= 1
        and {item["spec_id"] for item in files} == {0},
        "one_baseline_snapshot": len(snapshots) == 1
        and snapshots[0]["operation"] == "append",
    }
    return {
        "phase": "baseline",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "files": files,
        "spec_fields": _spec_fields(spark, args.table),
        "baseline_snapshot_id": snapshots[0]["snapshot_id"],
    }


def _evolve(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    snapshots = _snapshots(spark, args.table)
    if len(snapshots) != 1 or snapshots[0]["snapshot_id"] != args.baseline_snapshot_id:
        raise RuntimeError("partition evolution did not start from exact baseline")
    before_files = _file_inventory(spark, args.table)
    spark.sql(f"ALTER TABLE {args.table} ADD PARTITION FIELD identity(road_id)")
    after_files = _file_inventory(spark, args.table)
    fields = _spec_fields(spark, args.table)
    checks = {
        "baseline_files_preserved_during_evolution": {
            (item["file_path"], item["record_count"], item["spec_id"])
            for item in after_files
        }
        == {
            (item["file_path"], item["record_count"], item["spec_id"])
            for item in before_files
        },
        "current_spec_has_identity_road_id": fields == [
            {"name": "road_id", "transform": "identity"}
        ],
        "snapshot_chain_unchanged_by_spec_evolution": len(_snapshots(spark, args.table))
        == 1,
    }
    return {
        "phase": "evolve",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "before_files": before_files,
        "after_files": after_files,
        "spec_fields": fields,
        "snapshots": _snapshots(spark, args.table),
    }


def _verify(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    actual = _rows(spark.table(args.table))
    baseline = _rows(
        spark.read.option("snapshot-id", args.baseline_snapshot_id).table(args.table)
    )
    snapshots = _snapshots(spark, args.table)
    files = _file_inventory(spark, args.table)
    spec_zero = [item for item in files if item["spec_id"] == 0]
    spec_one = [item for item in files if item["spec_id"] == 1]
    new_road_id = int(plan["flink_row"]["road_id"])
    checks = {
        "final_rows_exact": list(actual) == plan["after_flink_rows"],
        "final_content_exact": _canonical_sha256(actual)
        == plan["after_flink_content_sha256"],
        "baseline_time_travel_exact": list(baseline) == plan["baseline_rows"],
        "both_partition_specs_materialized": bool(spec_zero) and bool(spec_one),
        "legacy_unpartitioned_file_retained": bool(spec_zero)
        and all(
            item["partition"] in ({}, {"road_id": None}) for item in spec_zero
        ),
        "new_identity_partition_file_bound": bool(spec_one)
        and all(
            item["partition"].get("road_id") == new_road_id for item in spec_one
        ),
        "new_file_contains_flink_revision": any(
            item["record_count"] >= 1 for item in spec_one
        ),
        "append_snapshot_parent_chain_exact": len(snapshots) == 2
        and [item["operation"] for item in snapshots] == ["append", "append"]
        and snapshots[1]["parent_id"] == snapshots[0]["snapshot_id"],
        "flink_snapshot_is_current_child": snapshots[-1]["snapshot_id"]
        == args.flink_snapshot_id,
    }
    return {
        "phase": "verify",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "files": files,
        "baseline_time_travel_rows": len(baseline),
        "spec_fields": _spec_fields(spark, args.table),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("baseline", "evolve", "verify"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--warehouse-uri", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--endpoint-url", default="http://minio:9000")
    parser.add_argument("--baseline-snapshot-id")
    parser.add_argument("--flink-snapshot-id")
    args = parser.parse_args()
    if args.phase != "baseline" and not args.baseline_snapshot_id:
        parser.error(f"{args.phase} requires --baseline-snapshot-id")
    if args.phase == "verify" and not args.flink_snapshot_id:
        parser.error("verify requires --flink-snapshot-id")
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        if not os.environ.get(name):
            raise RuntimeError(f"missing required environment variable {name}")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    spark = _spark(args)
    try:
        spark.sparkContext.setLogLevel("WARN")
        if args.phase == "baseline":
            phase = _baseline(spark, args, plan)
        elif args.phase == "evolve":
            phase = _evolve(spark, args, plan)
        else:
            phase = _verify(spark, args, plan)
    finally:
        spark.stop()
    report = {
        "schema": "gda.spark_flink_iceberg_partition_evolution_phase.v1",
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
