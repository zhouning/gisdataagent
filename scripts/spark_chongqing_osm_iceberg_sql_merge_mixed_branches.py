#!/usr/bin/env python3
"""Run a bounded Spark SQL MERGE with matched and not-matched branches."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pyspark.sql.functions import col
from pyspark.sql.types import IntegerType, LongType, StringType, StructField, StructType

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
            StructField("action", StringType(), False),
        ]
    )


def _rows(frame) -> tuple[dict[str, Any], ...]:
    return tuple(
        {key: row[key] for key in COLUMNS}
        for row in frame.select(*COLUMNS)
        .orderBy("road_id", "revision", "writer_engine")
        .collect()
    )


def _baseline(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    namespace = args.table.split(".")[1]
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.{namespace}")
    if spark.catalog.tableExists(args.table):
        raise RuntimeError("isolated mixed-branch SQL MERGE table already exists")
    frame = spark.createDataFrame(plan["baseline_rows"], schema=_schema())
    (
        frame.writeTo(args.table)
        .using("iceberg")
        .partitionedBy(col("road_id"))
        .tableProperty("format-version", "2")
        .tableProperty("gda.acceptance", "spark-sql-merge-mixed-branches")
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
        raise RuntimeError("mixed-branch SQL MERGE did not start from Flink snapshot")
    if list(current) != plan["after_flink_rows"]:
        raise RuntimeError("mixed-branch SQL MERGE did not read exact Flink state")
    source = plan["merge_source_rows"]
    spark.createDataFrame(source, schema=_merge_schema()).createOrReplaceTempView(
        "gda_sql_merge_mixed_branches_source"
    )
    spark.sql(
        f"""
        MERGE INTO {args.table} AS target
        USING gda_sql_merge_mixed_branches_source AS source
        ON target.road_id = source.road_id
           AND target.revision = source.expected_revision
        WHEN MATCHED AND source.action = 'delete' THEN DELETE
        WHEN MATCHED THEN UPDATE SET
          target.revision = source.result_revision,
          target.road_name_base64 = source.road_name_base64,
          target.geometry_sha256 = source.geometry_sha256,
          target.writer_engine = source.writer_engine,
          target.commit_token = source.commit_token
        WHEN NOT MATCHED AND source.action = 'insert_priority' THEN INSERT
          (road_id, revision, road_name_base64, geometry_sha256, writer_engine, commit_token)
        VALUES
          (source.road_id, source.result_revision, source.road_name_base64,
           source.geometry_sha256, source.writer_engine, source.commit_token)
        WHEN NOT MATCHED THEN INSERT
          (road_id, revision, road_name_base64, geometry_sha256, writer_engine, commit_token)
        VALUES
          (source.road_id, source.result_revision, source.road_name_base64,
           source.geometry_sha256, source.writer_engine, source.commit_token)
        """
    )
    spark.catalog.clearCache()
    spark.catalog.refreshTable(args.table)
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    delete_source = plan["delete_source_row"]
    update_source = plan["update_source_row"]
    priority_source = plan["priority_insert_source_row"]
    default_source = plan["default_insert_source_row"]
    checks = {
        "merge_committed": True,
        "delete_branch_token_absent": not any(
            row["commit_token"] == delete_source["commit_token"] for row in actual
        ),
        "update_branch_token_once": sum(
            row["commit_token"] == update_source["commit_token"] for row in actual
        )
        == 1,
        "priority_insert_branch_token_once": sum(
            row["commit_token"] == priority_source["commit_token"] for row in actual
        )
        == 1,
        "default_insert_branch_token_once": sum(
            row["commit_token"] == default_source["commit_token"] for row in actual
        )
        == 1,
        "final_rows_exact": list(actual) == plan["final_merge_rows"],
        "snapshot_child_of_flink": len(snapshots) == 3
        and snapshots[-1]["parent_id"] == args.flink_snapshot_id,
        "merge_snapshot_operation_observed": len(snapshots) == 3
        and snapshots[-1]["operation"] in {"overwrite", "append"},
    }
    return {
        "phase": "merge",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "actual_rows": actual,
        "expected_rows": plan["final_merge_rows"],
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "branch_token_counts": {
            "delete": sum(
                row["commit_token"] == delete_source["commit_token"] for row in actual
            ),
            "update": sum(
                row["commit_token"] == update_source["commit_token"] for row in actual
            ),
            "priority_insert": sum(
                row["commit_token"] == priority_source["commit_token"] for row in actual
            ),
            "default_insert": sum(
                row["commit_token"] == default_source["commit_token"] for row in actual
            ),
        },
        "merge_snapshot_id": snapshots[-1]["snapshot_id"],
    }


def _verify(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    baseline = _rows(spark.read.option("snapshot-id", args.baseline_snapshot_id).table(args.table))
    flink = _rows(spark.read.option("snapshot-id", args.flink_snapshot_id).table(args.table))
    delete_source = plan["delete_source_row"]
    update_source = plan["update_source_row"]
    priority_source = plan["priority_insert_source_row"]
    default_source = plan["default_insert_source_row"]
    checks = {
        "final_rows_exact": list(actual) == plan["final_merge_rows"],
        "final_content_exact": _canonical_sha256(actual) == plan["final_merge_content_sha256"],
        "baseline_time_travel_exact": list(baseline) == plan["baseline_rows"],
        "flink_time_travel_exact": list(flink) == plan["after_flink_rows"],
        "delete_target_revision_two_absent": not any(
            row["road_id"] == delete_source["road_id"]
            and row["revision"] == delete_source["expected_revision"]
            for row in actual
        ),
        "delete_target_baseline_revision_preserved": any(
            row["road_id"] == delete_source["road_id"] and row["revision"] == 1
            for row in actual
        ),
        "update_target_revision_exact": any(
            row["road_id"] == update_source["road_id"]
            and row["revision"] == update_source["result_revision"]
            and row["commit_token"] == update_source["commit_token"]
            for row in actual
        ),
        "priority_insert_target_exact": sum(
            row["road_id"] == priority_source["road_id"]
            and row["commit_token"] == priority_source["commit_token"]
            for row in actual
        )
        == 1,
        "default_insert_target_exact": sum(
            row["road_id"] == default_source["road_id"]
            and row["commit_token"] == default_source["commit_token"]
            for row in actual
        )
        == 1,
        "road_revision_keys_unique": len(
            {(row["road_id"], row["revision"]) for row in actual}
        )
        == len(actual),
        "snapshot_chain_exact": len(snapshots) == 3
        and [item["operation"] for item in snapshots][:2] == ["append", "append"]
        and snapshots[1]["parent_id"] == snapshots[0]["snapshot_id"]
        and snapshots[2]["parent_id"] == snapshots[1]["snapshot_id"],
        "final_row_count_is_five": len(actual) == 5,
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
        "schema": "gda.spark_flink_iceberg_sql_merge_mixed_branches_phase.v1",
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
