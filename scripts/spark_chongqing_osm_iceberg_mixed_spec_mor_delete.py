#!/usr/bin/env python3
"""Delete one logical road across legacy and evolved Iceberg partition specs."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.iceberg_file_scope import _stable_partition_value
from scripts.spark_chongqing_osm_iceberg_concurrent_append import COLUMNS, _schema
from scripts.spark_chongqing_osm_iceberg_delete_conflict import _iceberg_table, _snapshots
from scripts.spark_chongqing_osm_iceberg_interop import (
    CATALOG,
    _canonical_sha256,
    _spark,
)


def _rows(frame) -> tuple[dict[str, Any], ...]:
    return tuple(
        {key: row[key] for key in COLUMNS}
        for row in frame.select(*COLUMNS).orderBy("road_id", "revision", "writer_engine").collect()
    )


def _spec_fields(spark, table: str) -> list[dict[str, str]]:
    spec = _iceberg_table(spark, table).spec()
    return [
        {"name": str(field.name()), "transform": str(field.transform())} for field in spec.fields()
    ]


def _files(spark, table: str, *, include_deletes: bool = False) -> list[dict[str, Any]]:
    frame = spark.table(f"{table}.files")
    required = {"content", "file_path", "record_count", "spec_id"}
    missing = required.difference(frame.columns)
    if missing:
        raise RuntimeError(f"Iceberg files metadata missing required columns: {sorted(missing)}")
    columns = ["content", "file_path", "record_count", "spec_id"]
    has_partition = "partition" in frame.columns
    if has_partition:
        columns.insert(2, "partition")
    rows = []
    for row in frame.select(*columns).collect():
        content = int(row["content"])
        if not include_deletes and content != 0:
            continue
        rows.append(
            {
                "content": content,
                "file_path": str(row["file_path"]),
                "partition": (_stable_partition_value(row["partition"]) if has_partition else {}),
                "record_count": int(row["record_count"]),
                "spec_id": int(row["spec_id"]),
            }
        )
    return sorted(rows, key=lambda item: (item["content"], item["spec_id"], item["file_path"]))


def _physical_rows(spark, table: str) -> list[dict[str, Any]]:
    return [
        {
            "road_id": int(row["road_id"]),
            "revision": int(row["revision"]),
            "file_path": str(row["file_path"]),
            "pos": int(row["pos"]),
        }
        for row in spark.sql(
            f"SELECT road_id, revision, _file AS file_path, _pos AS pos FROM {table}"
        ).collect()
    ]


def _delete_files(spark, table: str) -> list[dict[str, Any]]:
    frame = spark.table(f"{table}.delete_files")
    columns = ["content", "file_path", "file_format", "record_count"]
    if "equality_ids" in frame.columns:
        columns.append("equality_ids")
    rows = []
    for row in frame.select(*columns).collect():
        rows.append(
            {
                "content": int(row["content"]),
                "file_path": str(row["file_path"]),
                "file_format": str(row["file_format"]),
                "record_count": int(row["record_count"]),
                "equality_ids": list(row["equality_ids"] or [])
                if "equality_ids" in columns
                else [],
            }
        )
    return sorted(rows, key=lambda item: item["file_path"])


def _position_deletes(spark, table: str) -> list[dict[str, Any]]:
    frame = spark.table(f"{table}.position_deletes")
    return [
        {"file_path": str(row["file_path"]), "pos": int(row["pos"])}
        for row in frame.select("file_path", "pos").collect()
    ]


def _baseline(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    namespace = args.table.split(".")[1]
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.{namespace}")
    if spark.catalog.tableExists(args.table):
        raise RuntimeError("isolated mixed-spec MOR table already exists")
    frame = spark.createDataFrame(plan["baseline_rows"], schema=_schema())
    (
        frame.writeTo(args.table)
        .using("iceberg")
        .tableProperty("format-version", "2")
        .tableProperty("write.delete.mode", "merge-on-read")
        .tableProperty("gda.acceptance", "spark-flink-mixed-spec-mor-delete")
        .tableProperty("gda.source_sha256", plan["source"]["source_parquet_sha256"])
        .create()
    )
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    files = _files(spark, args.table)
    properties = dict(_iceberg_table(spark, args.table).properties())
    checks = {
        "baseline_rows_exact": list(actual) == plan["baseline_rows"],
        "baseline_content_exact": _canonical_sha256(actual) == plan["baseline_content_sha256"],
        "merge_on_read_enabled": properties.get("write.delete.mode") == "merge-on-read",
        "baseline_spec_unpartitioned": _spec_fields(spark, args.table) == [],
        "baseline_files_spec_zero": bool(files) and {item["spec_id"] for item in files} == {0},
        "one_baseline_snapshot": len(snapshots) == 1 and snapshots[0]["operation"] == "append",
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
    before = _files(spark, args.table)
    snapshots = _snapshots(spark, args.table)
    if len(snapshots) != 1 or snapshots[0]["snapshot_id"] != args.baseline_snapshot_id:
        raise RuntimeError("mixed-spec evolution did not start from exact baseline")
    spark.sql(f"ALTER TABLE {args.table} ADD PARTITION FIELD identity(road_id)")
    after = _files(spark, args.table)
    fields = _spec_fields(spark, args.table)
    checks = {
        "legacy_files_preserved": {
            (item["file_path"], item["record_count"], item["spec_id"]) for item in before
        }
        == {(item["file_path"], item["record_count"], item["spec_id"]) for item in after},
        "current_spec_identity_road_id": fields == [{"name": "road_id", "transform": "identity"}],
        "evolution_did_not_create_snapshot": len(_snapshots(spark, args.table)) == 1,
    }
    return {
        "phase": "evolve",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "before_files": before,
        "after_files": after,
        "spec_fields": fields,
    }


def _mixed_delete(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    before_rows = _rows(spark.table(args.table))
    before_files = _files(spark, args.table)
    before_physical = _physical_rows(spark, args.table)
    snapshots = _snapshots(spark, args.table)
    if list(before_rows) != plan["after_flink_rows"] or len(snapshots) != 2:
        raise RuntimeError("mixed-spec delete did not start from exact Flink state")
    target = int(plan["target_road_id"])
    target_physical = [row for row in before_physical if row["road_id"] == target]
    target_files = {row["file_path"] for row in target_physical}
    if len(target_files) < 2:
        raise RuntimeError("mixed-spec delete target is not present in both physical specs")
    spark.sql(f"DELETE FROM {args.table} WHERE road_id = {target}").collect()
    spark.catalog.clearCache()
    spark.catalog.refreshTable(args.table)
    actual = _rows(spark.table(args.table))
    after_files = _files(spark, args.table, include_deletes=True)
    delete_files = _delete_files(spark, args.table)
    positions = _position_deletes(spark, args.table)
    checks = {
        "final_rows_exact": list(actual) == plan["after_mixed_delete_rows"],
        "final_content_exact": _canonical_sha256(actual)
        == plan["after_mixed_delete_content_sha256"],
        "target_logical_key_removed": all(row["road_id"] != target for row in actual),
        "both_specs_were_targeted": len(target_files) >= 2,
        "copy_on_write_observed_without_delete_files": not delete_files and not positions,
        "copy_on_write_removed_target_files_exactly": (
            {item["file_path"] for item in before_files}
            - {item["file_path"] for item in after_files}
        )
        == target_files,
        "copy_on_write_retained_non_target_files": (
            {item["file_path"] for item in before_files} - target_files
        ).issubset({item["file_path"] for item in after_files}),
        "delete_snapshot_is_flink_child": len(_snapshots(spark, args.table)) == 3
        and _snapshots(spark, args.table)[-1]["parent_id"] == args.flink_snapshot_id,
        "copy_on_write_did_not_rewrite_guard_file": (
            {item["file_path"] for item in before_files} - target_files
        ).issubset({item["file_path"] for item in after_files}),
    }
    return {
        "phase": "mixed-delete",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": _snapshots(spark, args.table),
        "before_files": before_files,
        "before_physical_rows": before_physical,
        "after_files": after_files,
        "delete_files": delete_files,
        "position_deletes": positions,
        "target_file_paths": sorted(target_files),
    }


def _verify(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    actual = _rows(spark.table(args.table))
    baseline = _rows(spark.read.option("snapshot-id", args.baseline_snapshot_id).table(args.table))
    flink = _rows(spark.read.option("snapshot-id", args.flink_snapshot_id).table(args.table))
    snapshots = _snapshots(spark, args.table)
    checks = {
        "final_rows_exact": list(actual) == plan["after_mixed_delete_rows"],
        "final_content_exact": _canonical_sha256(actual)
        == plan["after_mixed_delete_content_sha256"],
        "baseline_time_travel_exact": list(baseline) == plan["baseline_rows"],
        "flink_time_travel_exact": list(flink) == plan["after_flink_rows"],
        "append_append_delete_chain_exact": len(snapshots) == 3
        and [item["operation"] for item in snapshots] == ["append", "append", "delete"]
        and snapshots[1]["parent_id"] == snapshots[0]["snapshot_id"]
        and snapshots[2]["parent_id"] == snapshots[1]["snapshot_id"],
        "current_snapshot_is_delete_child": snapshots[-1]["snapshot_id"] == args.delete_snapshot_id,
    }
    return {
        "phase": "verify",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "baseline_time_travel_rows": len(baseline),
        "flink_time_travel_rows": len(flink),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("baseline", "evolve", "mixed-delete", "verify"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--warehouse-uri", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--endpoint-url", default="http://minio:9000")
    parser.add_argument("--baseline-snapshot-id")
    parser.add_argument("--flink-snapshot-id")
    parser.add_argument("--delete-snapshot-id")
    args = parser.parse_args()
    if args.phase != "baseline" and not args.baseline_snapshot_id:
        parser.error(f"{args.phase} requires --baseline-snapshot-id")
    if args.phase in ("mixed-delete", "verify") and not args.flink_snapshot_id:
        parser.error(f"{args.phase} requires --flink-snapshot-id")
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
        elif args.phase == "evolve":
            phase = _evolve(spark, args, plan)
        elif args.phase == "mixed-delete":
            phase = _mixed_delete(spark, args, plan)
        else:
            phase = _verify(spark, args, plan)
    finally:
        spark.stop()
    report = {
        "schema": "gda.spark_flink_iceberg_mixed_spec_mor_delete_phase.v1",
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
