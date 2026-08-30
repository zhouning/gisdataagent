#!/usr/bin/env python3
"""Run a bounded Spark SQL MERGE updating two distinct target rows in one snapshot."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pyspark.sql.functions import col
from pyspark.sql.types import IntegerType, LongType, StringType, StructField, StructType

from scripts.iceberg_file_scope import (
    _file_scope_evidence,
    _partition_road_id,
    _stable_partition_value,
)
from scripts.spark_chongqing_osm_iceberg_concurrent_append import COLUMNS
from scripts.spark_chongqing_osm_iceberg_interop import (
    CATALOG,
    _canonical_sha256,
    _snapshots,
    _spark,
)


def _schema() -> StructType:
    return StructType(
        [
            StructField("road_id", LongType(), False),
            StructField("revision", IntegerType(), False),
            StructField("road_name_base64", StringType(), False),
            StructField("geometry_sha256", StringType(), False),
            StructField("writer_engine", StringType(), False),
            StructField("commit_token", StringType(), True),
        ]
    )


def _merge_schema() -> StructType:
    return StructType(
        [
            StructField("road_id", LongType(), False),
            StructField("expected_revision", IntegerType(), False),
            StructField("result_revision", IntegerType(), False),
            StructField("road_name_base64", StringType(), False),
            StructField("geometry_sha256", StringType(), False),
            StructField("writer_engine", StringType(), False),
            StructField("commit_token", StringType(), False),
            StructField("source_row_id", StringType(), False),
        ]
    )


def _rows(frame) -> tuple[dict[str, Any], ...]:
    return tuple(
        {key: row[key] for key in COLUMNS}
        for row in frame.select(*COLUMNS)
        .orderBy("road_id", "revision", "writer_engine")
        .collect()
    )


def _file_inventory(spark, table: str) -> tuple[dict[str, Any], ...]:
    """Read the provider's physical data-file inventory for one table snapshot."""
    frame = spark.table(f"{table}.files")
    missing = {"file_path", "partition"}.difference(frame.columns)
    if missing:
        raise RuntimeError(f"Iceberg files metadata missing required columns: {sorted(missing)}")
    rows = []
    for row in frame.select("file_path", "partition").collect():
        partition = _stable_partition_value(row["partition"])
        rows.append(
            {
                "file_path": str(row["file_path"]),
                "partition": partition,
                "road_id": _partition_road_id(partition),
            }
        )
    return tuple(sorted(rows, key=lambda item: (item["road_id"], item["file_path"])))


def _baseline(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    namespace = args.table.split(".")[1]
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.{namespace}")
    if spark.catalog.tableExists(args.table):
        raise RuntimeError("isolated multi-target SQL MERGE table already exists")
    frame = spark.createDataFrame(plan["baseline_rows"], schema=_schema())
    (
        frame.writeTo(args.table)
        .using("iceberg")
        .partitionedBy(col("road_id"))
        .tableProperty("format-version", "2")
        .tableProperty("gda.acceptance", "spark-sql-merge-multi-target")
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


def _merge(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    before = _snapshots(spark, args.table)
    current = _rows(spark.table(args.table))
    if len(before) != 2 or before[-1]["snapshot_id"] != args.flink_snapshot_id:
        raise RuntimeError("multi-branch SQL MERGE did not start from Flink snapshot")
    if list(current) != plan["after_flink_rows"]:
        raise RuntimeError("multi-branch SQL MERGE did not read exact Flink state")
    before_files = _file_inventory(spark, args.table) if plan.get("file_scope_contract") else ()
    source = plan["merge_source_rows"]
    candidates = plan.get("survivorship_candidates")
    selected_source_ids = {row["source_row_id"] for row in source}
    if candidates:
        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in candidates:
            grouped.setdefault(int(row["road_id"]), []).append(row)
        source = [
            sorted(
                rows,
                key=lambda row: (
                    -int(row["survivorship_rank"]),
                    str(row["source_row_id"]),
                ),
            )[0]
            for rows in grouped.values()
        ]
    source = [{key: row[key] for key in _merge_schema().fieldNames()} for row in source]
    spark.createDataFrame(source, schema=_merge_schema()).createOrReplaceTempView(
        "gda_sql_merge_multi_target_source"
    )
    spark.sql(
        f"""
        MERGE INTO {args.table} AS target
        USING gda_sql_merge_multi_target_source AS source
        ON target.road_id = source.road_id
           AND target.revision = source.expected_revision
        WHEN MATCHED THEN UPDATE SET
          target.revision = source.result_revision,
          target.road_name_base64 = source.road_name_base64,
          target.geometry_sha256 = source.geometry_sha256,
          target.writer_engine = source.writer_engine,
          target.commit_token = source.commit_token
        """
    )
    spark.catalog.clearCache()
    spark.catalog.refreshTable(args.table)
    actual = _rows(spark.table(args.table))
    after_files = _file_inventory(spark, args.table) if plan.get("file_scope_contract") else ()
    snapshots = _snapshots(spark, args.table)
    matched = plan["matched_source_rows"]
    checks = {
        "merge_committed": True,
        "matched_update_tokens_once": all(
            sum(row["commit_token"] == source_row["commit_token"] for row in actual) == 1
            for source_row in matched
        ),
        "unselected_survivorship_tokens_absent": not candidates
        or all(
            not any(row["commit_token"] == candidate["commit_token"] for row in actual)
            for candidate in candidates
            if candidate["source_row_id"] not in selected_source_ids
        ),
        "final_rows_exact": list(actual) == plan["final_merge_rows"],
        "snapshot_child_of_flink": len(snapshots) == 3
        and snapshots[-1]["parent_id"] == args.flink_snapshot_id,
        "merge_snapshot_operation_observed": len(snapshots) == 3
        and snapshots[-1]["operation"] in {"overwrite", "append"},
    }
    file_scope = None
    if plan.get("file_scope_contract"):
        file_scope = _file_scope_evidence(before_files, after_files, plan)
        checks.update(file_scope["checks"])
    return {
        "phase": "merge",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "actual_rows": actual,
        "expected_rows": plan["final_merge_rows"],
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "matched_update_token_counts": {
            source_row["source_row_id"]: sum(
                row["commit_token"] == source_row["commit_token"] for row in actual
            )
            for source_row in matched
        },
        "merge_snapshot_id": snapshots[-1]["snapshot_id"],
        "file_scope": file_scope,
    }


def _verify(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    baseline = _rows(spark.read.option("snapshot-id", args.baseline_snapshot_id).table(args.table))
    flink = _rows(spark.read.option("snapshot-id", args.flink_snapshot_id).table(args.table))
    matched = plan["matched_source_rows"]
    checks = {
        "final_rows_exact": list(actual) == plan["final_merge_rows"],
        "final_content_exact": _canonical_sha256(actual) == plan["final_merge_content_sha256"],
        "baseline_time_travel_exact": list(baseline) == plan["baseline_rows"],
        "flink_time_travel_exact": list(flink) == plan["after_flink_rows"],
        "both_target_revisions_updated": all(
            any(
                row["road_id"] == source_row["road_id"]
                and row["revision"] == source_row["result_revision"]
                and row["commit_token"] == source_row["commit_token"]
                for row in actual
            )
            for source_row in matched
        ),
        "road_revision_keys_unique": len(
            {(row["road_id"], row["revision"]) for row in actual}
        )
        == len(actual),
        "snapshot_chain_exact": len(snapshots) == 3
        and [item["operation"] for item in snapshots][:2] == ["append", "append"]
        and snapshots[1]["parent_id"] == snapshots[0]["snapshot_id"]
        and snapshots[2]["parent_id"] == snapshots[1]["snapshot_id"],
        "final_row_count_is_four": len(actual) == 4,
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
    parser.add_argument("phase", choices=("baseline", "merge", "verify"))
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
    if args.phase in ("merge", "verify") and not args.flink_snapshot_id:
        parser.error(f"{args.phase} requires --flink-snapshot-id")
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        if not os.environ.get(name):
            raise RuntimeError(f"missing required environment variable {name}")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    spark = _spark(args)
    try:
        spark.sparkContext.setLogLevel("WARN")
        if args.phase == "baseline":
            phase = _baseline(spark, args, plan)
        elif args.phase == "merge":
            phase = _merge(spark, args, plan)
        else:
            phase = _verify(spark, args, plan)
    finally:
        spark.stop()
    report = {
        "schema": "gda.spark_flink_iceberg_sql_merge_multi_target_phase.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        **phase,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"phase": args.phase, "status": report["status"]}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
