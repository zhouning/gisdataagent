#!/usr/bin/env python3
"""Create and independently probe an Iceberg reconciliation acceptance table."""

from __future__ import annotations

import argparse
import json
import os
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
    "stream_event_id",
    "flink_commit_tag",
)


def _rows(frame) -> tuple[dict[str, Any], ...]:
    return tuple(
        {key: row[key] for key in COLUMNS}
        for row in frame.select(*COLUMNS).orderBy("road_id", "stream_event_id").collect()
    )


def _baseline(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    from pyspark.sql.types import (
        IntegerType,
        LongType,
        StringType,
        StructField,
        StructType,
    )

    namespace = args.table.split(".")[1]
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.{namespace}")
    if spark.catalog.tableExists(args.table):
        raise RuntimeError("isolated Iceberg reconciliation table already exists")
    schema = StructType(
        [
            StructField("road_id", LongType(), False),
            StructField("revision", IntegerType(), False),
            StructField("road_name_base64", StringType(), False),
            StructField("geometry_sha256", StringType(), False),
            StructField("stream_event_id", StringType(), True),
            StructField("flink_commit_tag", StringType(), True),
        ]
    )
    frame = spark.createDataFrame(plan["baseline_rows"], schema=schema)
    (
        frame.writeTo(args.table)
        .using("iceberg")
        .tableProperty("format-version", "2")
        .tableProperty("gda.acceptance", "flink-iceberg-reconciliation")
        .tableProperty("gda.source_slice_sha256", plan["source_slice_sha256"])
        .create()
    )
    actual = _rows(spark.table(args.table))
    snapshots = _snapshots(spark, args.table)
    checks = {
        "baseline_rows_exact": list(actual) == plan["baseline_rows"],
        "baseline_content_exact": _canonical_sha256(actual) == plan["baseline_content_sha256"],
        "one_create_snapshot": len(snapshots) == 1 and snapshots[0]["operation"] == "append",
    }
    return {
        "phase": "baseline",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "row_count": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "snapshot_evidence": _snapshot_evidence(spark, args, plan, snapshots),
        "baseline_snapshot_id": snapshots[0]["snapshot_id"],
    }


def _snapshot_evidence(
    spark,
    args: argparse.Namespace,
    plan: dict[str, Any],
    snapshots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence = []
    for snapshot in snapshots:
        frame = spark.read.option("snapshot-id", snapshot["snapshot_id"]).table(args.table)
        rows = _rows(frame)
        matching = sum(row["flink_commit_tag"] == plan["commit_tag"] for row in rows)
        evidence.append(
            {
                "snapshot_id": snapshot["snapshot_id"],
                "parent_snapshot_id": snapshot["parent_id"],
                "operation": snapshot["operation"],
                "record_count": len(rows),
                "matching_records": matching,
                "commit_token": plan["commit_tag"] if matching else None,
                "content_sha256": _canonical_sha256(rows),
            }
        )
    return evidence


def _probe(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    snapshots = _snapshots(spark, args.table)
    evidence = _snapshot_evidence(spark, args, plan, snapshots)
    actual = _rows(spark.table(args.table))
    baseline = next(item for item in evidence if item["snapshot_id"] == args.baseline_snapshot_id)
    chain_exact = all(
        snapshots[index]["parent_id"] == snapshots[index - 1]["snapshot_id"]
        for index in range(1, len(snapshots))
    )
    terminal = [
        item
        for item in evidence
        if item["matching_records"] == len(plan["stream_rows"])
        and item["record_count"] == len(plan["final_rows"])
        and item["content_sha256"] == plan["final_content_sha256"]
    ]
    if args.phase == "cancel-probe":
        checks = {
            "cancel_left_one_baseline_snapshot": len(snapshots) == 1,
            "cancel_left_baseline_rows_exact": list(actual) == plan["baseline_rows"],
            "cancel_created_no_commit_marker": not any(
                item["matching_records"] for item in evidence
            ),
            "baseline_snapshot_unchanged": baseline["content_sha256"]
            == plan["baseline_content_sha256"],
        }
    else:
        checks = {
            "uncertain_commit_rows_exact": list(actual) == plan["final_rows"],
            "uncertain_commit_content_exact": _canonical_sha256(actual)
            == plan["final_content_sha256"],
            "one_terminal_snapshot_matches_intent": len(terminal) == 1,
            "snapshot_parent_chain_exact": chain_exact,
            "baseline_time_travel_unchanged": baseline["content_sha256"]
            == plan["baseline_content_sha256"],
        }
    return {
        "phase": args.phase,
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "row_count": len(actual),
        "content_sha256": _canonical_sha256(actual),
        "snapshots": snapshots,
        "snapshot_evidence": evidence,
        "terminal_snapshot_id": terminal[0]["snapshot_id"] if len(terminal) == 1 else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("baseline", "cancel-probe", "commit-probe"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--warehouse-uri", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--endpoint-url", default="http://minio:9000")
    parser.add_argument("--baseline-snapshot-id")
    args = parser.parse_args()
    if args.phase != "baseline" and not args.baseline_snapshot_id:
        parser.error(f"{args.phase} requires --baseline-snapshot-id")
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        if not os.environ.get(name):
            raise RuntimeError(f"missing required environment variable {name}")

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    spark = _spark(args)
    try:
        spark.sparkContext.setLogLevel("WARN")
        phase = (
            _baseline(spark, args, plan) if args.phase == "baseline" else _probe(spark, args, plan)
        )
    finally:
        spark.stop()
    report = {
        "schema": "gda.spark_iceberg_reconciliation_phase.v1",
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
