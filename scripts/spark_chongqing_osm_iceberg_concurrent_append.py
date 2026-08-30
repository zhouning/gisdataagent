#!/usr/bin/env python3
"""Create, block, append, and verify a concurrent Spark/Iceberg write."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.spark_chongqing_osm_iceberg_interop import (
    CATALOG,
    _canonical_sha256,
    _snapshots,
    _spark,
)

COLUMNS = (
    "road_id",
    "revision",
    "road_name_base64",
    "geometry_sha256",
    "writer_engine",
    "commit_token",
)
BARRIER_RE = re.compile(
    r"^/workspace/\.tmp/source-sync-certification/"
    r"flink_iceberg_concurrent_[0-9a-f]{10}/spark-(?:ready|release)\.json$"
)


def _rows(frame) -> tuple[dict[str, Any], ...]:
    return tuple(
        {key: row[key] for key in COLUMNS}
        for row in frame.select(*COLUMNS).orderBy("road_id").collect()
    )


def _schema():
    from pyspark.sql.types import (
        IntegerType,
        LongType,
        StringType,
        StructField,
        StructType,
    )

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


def _baseline(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    namespace = args.table.split(".")[1]
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.{namespace}")
    if spark.catalog.tableExists(args.table):
        raise RuntimeError("isolated concurrent append table already exists")
    frame = spark.createDataFrame(plan["baseline_rows"], schema=_schema())
    (
        frame.writeTo(args.table)
        .using("iceberg")
        .tableProperty("format-version", "2")
        .tableProperty("gda.acceptance", "spark-flink-concurrent-append")
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


def _concurrent_append(
    spark,
    args: argparse.Namespace,
    plan: dict[str, Any],
) -> dict[str, Any]:
    from pyspark.sql.functions import col, udf
    from pyspark.sql.types import StringType

    if not args.ready_marker or not args.release_marker:
        raise ValueError("concurrent append requires both barrier paths")
    for path in (args.ready_marker, args.release_marker):
        if not BARRIER_RE.fullmatch(path.as_posix()):
            raise ValueError("unsafe concurrent append barrier path")
    snapshots_before = _snapshots(spark, args.table)
    if (
        len(snapshots_before) != 1
        or snapshots_before[0]["snapshot_id"] != args.baseline_snapshot_id
    ):
        raise RuntimeError("Spark concurrent append did not start from the baseline")

    ready_path = args.ready_marker.as_posix()
    release_path = args.release_marker.as_posix()
    ready_payload = json.dumps(
        {
            "schema": "gda.spark_iceberg_concurrent_append_ready.v1",
            "baseline_snapshot_id": args.baseline_snapshot_id,
            "commit_token": plan["spark_commit_token"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    timeout_seconds = args.barrier_timeout_seconds

    @udf(returnType=StringType())
    def wait_for_release(value: str) -> str:
        ready = Path(ready_path)
        release = Path(release_path)
        ready.write_text(ready_payload + "\n", encoding="utf-8")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if release.is_file():
                return value
            time.sleep(0.1)
        raise RuntimeError("Spark concurrent append barrier timed out")

    frame = spark.createDataFrame([plan["spark_row"]], schema=_schema()).withColumn(
        "writer_engine",
        wait_for_release(col("writer_engine")),
    )
    frame.writeTo(args.table).append()
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    matching = sum(row["commit_token"] == plan["spark_commit_token"] for row in actual)
    checks = {
        "ready_marker_persisted": args.ready_marker.is_file(),
        "release_marker_observed": args.release_marker.is_file(),
        "spark_row_committed_once": matching == 1,
        "spark_append_rebased_after_flink": len(snapshots) == 3
        and snapshots[-1]["parent_id"] != args.baseline_snapshot_id,
    }
    return {
        "phase": "concurrent-append",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "spark_snapshot_id": snapshots[-1]["snapshot_id"],
    }


def _verify(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    baseline_rows = _rows(
        spark.read.option("snapshot-id", args.baseline_snapshot_id).table(args.table)
    )
    flink_rows = _rows(spark.read.option("snapshot-id", args.flink_snapshot_id).table(args.table))
    engine_counts = {
        engine: sum(row["writer_engine"] == engine for row in actual)
        for engine in ("spark-baseline", "flink-1.19.3", "spark-3.5")
    }
    token_counts = {
        token: sum(row["commit_token"] == token for row in actual)
        for token in (plan["flink_commit_token"], plan["spark_commit_token"])
    }
    chain_exact = len(snapshots) == 3 and all(
        snapshots[index]["parent_id"] == snapshots[index - 1]["snapshot_id"]
        for index in range(1, len(snapshots))
    )
    checks = {
        "five_rows_exact_without_loss_or_duplicates": list(actual) == plan["final_rows"],
        "final_content_exact": _canonical_sha256(actual) == plan["final_content_sha256"],
        "road_ids_unique": len({row["road_id"] for row in actual}) == len(actual),
        "writer_engine_counts_exact": engine_counts
        == {"spark-baseline": 3, "flink-1.19.3": 1, "spark-3.5": 1},
        "commit_tokens_unique": all(value == 1 for value in token_counts.values()),
        "three_append_snapshots_in_linear_chain": chain_exact
        and all(item["operation"] == "append" for item in snapshots),
        "flink_committed_between_baseline_and_spark": (
            snapshots[0]["snapshot_id"] == args.baseline_snapshot_id
            and snapshots[1]["snapshot_id"] == args.flink_snapshot_id
            and snapshots[2]["parent_id"] == args.flink_snapshot_id
        ),
        "baseline_time_travel_exact": list(baseline_rows) == plan["baseline_rows"],
        "flink_time_travel_exact": list(flink_rows) == plan["after_flink_rows"],
    }
    return {
        "phase": "verify",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "rows": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "engine_counts": engine_counts,
        "token_counts": token_counts,
        "snapshots": snapshots,
        "baseline_time_travel_rows": len(baseline_rows),
        "flink_time_travel_rows": len(flink_rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("baseline", "concurrent-append", "verify"))
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
    if args.phase == "verify" and not args.flink_snapshot_id:
        parser.error("verify requires --flink-snapshot-id")
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
        elif args.phase == "concurrent-append":
            phase = _concurrent_append(spark, args, plan)
        else:
            phase = _verify(spark, args, plan)
    finally:
        spark.stop()
    report = {
        "schema": "gda.spark_flink_iceberg_concurrent_append_phase.v1",
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
