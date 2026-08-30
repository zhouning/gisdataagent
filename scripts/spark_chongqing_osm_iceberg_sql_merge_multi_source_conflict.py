#!/usr/bin/env python3
"""Certify duplicate-source-row Spark SQL MERGE rejection and fresh retry."""

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
from pyspark.sql.types import (
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
)

from scripts.spark_chongqing_osm_iceberg_concurrent_append import COLUMNS
from scripts.spark_chongqing_osm_iceberg_interop import (
    CATALOG,
    _canonical_sha256,
    _snapshots,
    _spark,
)

BARRIER_RE = re.compile(
    r"^/workspace/\.tmp/source-sync-certification/"
    r"flink_iceberg_sql_merge_multi_source_conflict_[0-9a-f]{10}/spark-ready\.json$"
)


def _schema():
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


def _merge_schema():
    return StructType(
        [
            StructField("road_id", LongType(), False),
            StructField("expected_revision", IntegerType(), False),
            StructField("new_revision", IntegerType(), False),
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
        for row in frame.select(*COLUMNS).orderBy("road_id", "revision", "writer_engine").collect()
    )


def _validate_barriers(args: argparse.Namespace) -> None:
    if not args.ready_marker or not args.release_marker:
        raise ValueError("multi-source SQL MERGE requires both barrier paths")
    if not BARRIER_RE.fullmatch(args.ready_marker.as_posix()):
        raise ValueError("unsafe multi-source SQL MERGE barrier path")
    if not BARRIER_RE.fullmatch(
        args.release_marker.as_posix().replace("spark-release.json", "spark-ready.json")
    ):
        raise ValueError("unsafe multi-source SQL MERGE barrier path")
    if args.release_marker.as_posix() != args.ready_marker.as_posix().replace(
        "spark-ready.json", "spark-release.json"
    ):
        raise ValueError(
            "multi-source SQL MERGE release marker must share the acceptance work directory"
        )


def _baseline(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    namespace = args.table.split(".")[1]
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.{namespace}")
    if spark.catalog.tableExists(args.table):
        raise RuntimeError("isolated multi-source SQL MERGE table already exists")
    frame = spark.createDataFrame(plan["baseline_rows"], schema=_schema())
    (
        frame.writeTo(args.table)
        .using("iceberg")
        .partitionedBy(col("road_id"))
        .tableProperty("format-version", "2")
        .tableProperty("gda.acceptance", "spark-sql-merge-multi-source-conflict")
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


def _wait_partition(rows, *, marker: Path, release: Path, payload: dict[str, Any], timeout: int):
    values = list(rows)
    marker.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not release.is_file():
        time.sleep(0.1)
    if not release.is_file():
        raise RuntimeError("multi-source SQL MERGE barrier timed out")
    yield from values


def _merge_source(
    spark, args: argparse.Namespace, sources: list[dict[str, Any]], *, wait: bool
) -> None:
    frame = spark.createDataFrame(sources, schema=_merge_schema()).repartition(1)
    if wait:
        _validate_barriers(args)
        payload = {
            "schema": "gda.spark_sql_merge_multi_source_conflict_ready.v1",
            "baseline_snapshot_id": args.baseline_snapshot_id,
            "source_row_count": len(sources),
            "source_row_ids": [source["source_row_id"] for source in sources],
            "target_road_id": sources[0]["road_id"],
            "expected_revision": sources[0]["expected_revision"],
        }
        frame = frame.rdd.mapPartitions(
            lambda rows: _wait_partition(
                rows,
                marker=args.ready_marker,
                release=args.release_marker,
                payload=payload,
                timeout=args.barrier_timeout_seconds,
            ),
            preservesPartitioning=True,
        ).toDF(_merge_schema())
    frame.createOrReplaceTempView("gda_sql_merge_source")


def _run_merge(
    spark, args: argparse.Namespace, sources: list[dict[str, Any]], *, wait: bool
) -> dict[str, Any]:
    _merge_source(spark, args, sources, wait=wait)
    merge_committed = False
    conflict: dict[str, Any] | None = None
    try:
        spark.sql(
            f"""
            MERGE INTO {args.table} AS target
            USING gda_sql_merge_source AS source
            ON target.road_id = source.road_id
               AND target.revision = source.expected_revision
            WHEN MATCHED THEN UPDATE SET
              target.revision = source.new_revision,
              target.road_name_base64 = source.road_name_base64,
              target.geometry_sha256 = source.geometry_sha256,
              target.writer_engine = source.writer_engine,
              target.commit_token = source.commit_token
            """
        )
        merge_committed = True
    except Exception as exc:
        text = str(exc)
        lower = text.lower()
        conflict = {
            "conflict_type": "multiple_source_rows_match_target",
            "source_row_conflict": any(
                phrase in lower
                for phrase in (
                    "multiple source rows",
                    "multiple rows",
                    "multiple matches",
                    "more than one source row",
                    "matched more than one",
                    "duplicate source",
                    "bitmapcardinalityvalidator",
                    "mergerows",
                    "duplicate",
                )
            ),
            "is_iceberg_validation_failure": "validationexception" in lower,
            "error_type": type(exc).__name__,
            "error": text[-2000:],
        }
    spark.catalog.clearCache()
    spark.catalog.refreshTable(args.table)
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    source_tokens = {source["commit_token"] for source in sources}
    token_count = sum(row["commit_token"] in source_tokens for row in actual)
    checks = {
        "merge_not_committed": merge_committed if not wait else True,
        "source_row_conflict_observed": bool(conflict and conflict["source_row_conflict"])
        if wait
        else True,
    }
    return {
        "merge_committed": merge_committed,
        "conflict": conflict,
        "actual_rows": list(actual),
        "snapshots": snapshots,
        "commit_token_count": token_count,
        "checks": checks,
    }


def _concurrent_merge(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    before = _snapshots(spark, args.table)
    if len(before) != 1 or before[0]["snapshot_id"] != args.baseline_snapshot_id:
        raise RuntimeError("SQL MERGE did not start from exact baseline snapshot")
    result = _run_merge(spark, args, plan["merge_source_stale_rows"], wait=True)
    release = json.loads(args.release_marker.read_text(encoding="utf-8"))
    target_rows = [row for row in result["actual_rows"] if row["road_id"] == plan["target_road_id"]]
    checks = {
        **result["checks"],
        "merge_not_committed": not result["merge_committed"],
        "baseline_and_flink_rows_preserved": result["actual_rows"] == plan["after_flink_rows"],
        "stale_merge_token_absent": result["commit_token_count"] == 0,
        "target_revisions_one_and_two_visible": sorted(row["revision"] for row in target_rows)
        == [1, 2],
        "source_row_conflict_observed": bool(
            result["conflict"] and result["conflict"].get("source_row_conflict")
        ),
        "release_marker_exact": release.get("schema")
        == "gda.spark_sql_merge_multi_source_conflict_release.v1"
        and release.get("flink_commit_token") == plan["flink_commit_token"]
        and release.get("source_row_count") == 2
        and release.get("source_row_ids") == plan["stale_source_row_ids"],
        "catalog_snapshot_chain_unchanged": len(result["snapshots"]) == 2
        and result["snapshots"][-1]["snapshot_id"] == str(release.get("flink_snapshot_id")),
    }
    return {
        "phase": "concurrent-merge",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(result["actual_rows"]),
        "content_sha256": _canonical_sha256(result["actual_rows"]),
        "snapshots": result["snapshots"],
        "conflict": result["conflict"],
        "release": release,
        "merge_committed": result["merge_committed"],
        "stale_merge_token_count": result["commit_token_count"],
    }


def _retry(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    current = _rows(spark.table(args.table))
    before = _snapshots(spark, args.table)
    if (
        list(current) != plan["after_flink_rows"]
        or before[-1]["snapshot_id"] != args.flink_snapshot_id
    ):
        raise RuntimeError("SQL MERGE retry did not read exact Flink state")
    result = _run_merge(spark, args, [plan["merge_source_fresh"]], wait=False)
    actual = result["actual_rows"]
    snapshots = result["snapshots"]
    checks = {
        "fresh_sql_merge_committed": result["merge_committed"],
        "final_rows_exact": actual == plan["final_merge_rows"],
        "fresh_merge_token_once": result["commit_token_count"] == 1,
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
        "final_rows_exact": list(actual) == plan["final_merge_rows"],
        "final_content_exact": _canonical_sha256(actual) == plan["final_merge_content_sha256"],
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
    parser.add_argument("phase", choices=("baseline", "concurrent-merge", "retry", "verify"))
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
        elif args.phase == "concurrent-merge":
            phase = _concurrent_merge(spark, args, plan)
        elif args.phase == "retry":
            phase = _retry(spark, args, plan)
        else:
            phase = _verify(spark, args, plan)
    finally:
        spark.stop()
    report = {
        "schema": "gda.spark_flink_iceberg_sql_merge_multi_source_conflict_phase.v1",
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
