#!/usr/bin/env python3
"""Create and verify the Spark side of the Flink/Iceberg interop acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CATALOG = "lakehouse"
SPARK_JARS = ",".join(
    (
        "/opt/spark/jars-extra/iceberg-spark-runtime-3.5_2.12-1.6.1.jar",
        "/opt/spark/jars-extra/iceberg-aws-bundle-1.6.1.jar",
        "/opt/spark/jars-extra/postgresql-42.7.4.jar",
    )
)
SPARK_CLASSPATH = SPARK_JARS.replace(",", ":")
TABLE_RE = re.compile(
    r"^lakehouse\.gda_interop_[0-9a-f]{10}\.chongqing_osm_roads$"
)


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _spark(args: argparse.Namespace):
    from pyspark.sql import SparkSession

    if not TABLE_RE.fullmatch(args.table):
        raise ValueError("unsafe Iceberg table identifier")
    if not args.warehouse_uri.startswith(
        "s3://gis-agent-lakehouse/acceptance/flink-iceberg/"
    ):
        raise ValueError("warehouse is outside the acceptance prefix")
    catalog_uri = os.environ.get("ICEBERG_CATALOG_URI", "")
    catalog_user = os.environ.get("ICEBERG_CATALOG_USER", "")
    catalog_password = os.environ.get("ICEBERG_CATALOG_PASSWORD", "")
    if not re.fullmatch(
        r"jdbc:postgresql://gda-iceberg-pg-[0-9a-f]{10}:5432/iceberg_catalog",
        catalog_uri,
    ):
        raise ValueError("unexpected Iceberg catalog URI")
    if catalog_user != "iceberg_admin" or not catalog_password:
        raise ValueError("invalid Iceberg catalog credentials")
    return (
        SparkSession.builder.master("local[2]")
        .appName(f"gda-flink-iceberg-{args.phase}")
        .config("spark.jars", SPARK_JARS)
        .config("spark.driver.extraClassPath", SPARK_CLASSPATH)
        .config("spark.executor.extraClassPath", SPARK_CLASSPATH)
        .config(
            "spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        )
        .config(f"spark.sql.catalog.{CATALOG}", "org.apache.iceberg.spark.SparkCatalog")
        .config(
            f"spark.sql.catalog.{CATALOG}.catalog-impl",
            "org.apache.iceberg.jdbc.JdbcCatalog",
        )
        .config(f"spark.sql.catalog.{CATALOG}.uri", catalog_uri)
        .config(f"spark.sql.catalog.{CATALOG}.jdbc.user", catalog_user)
        .config(f"spark.sql.catalog.{CATALOG}.jdbc.password", catalog_password)
        .config(f"spark.sql.catalog.{CATALOG}.warehouse", args.warehouse_uri)
        .config(
            f"spark.sql.catalog.{CATALOG}.io-impl",
            "org.apache.iceberg.aws.s3.S3FileIO",
        )
        .config(f"spark.sql.catalog.{CATALOG}.s3.endpoint", args.endpoint_url)
        .config(f"spark.sql.catalog.{CATALOG}.s3.path-style-access", "true")
        .config(f"spark.sql.catalog.{CATALOG}.client.region", "us-east-1")
        .getOrCreate()
    )


def _rows(frame, *, include_tag: bool) -> tuple[dict[str, Any], ...]:
    columns = ["road_id", "revision", "road_name_base64", "geometry_sha256"]
    if include_tag:
        columns.append("flink_commit_tag")
    return tuple(
        {
            key: row[key]
            for key in columns
        }
        for row in frame.select(*columns).orderBy("road_id").collect()
    )


def _snapshots(spark, table: str) -> list[dict[str, Any]]:
    return [
        {
            "snapshot_id": str(row["snapshot_id"]),
            "parent_id": str(row["parent_id"]) if row["parent_id"] is not None else None,
            "operation": row["operation"],
        }
        for row in spark.sql(
            f"SELECT snapshot_id, parent_id, operation FROM {table}.snapshots "
            "ORDER BY committed_at, snapshot_id"
        ).collect()
    ]


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
        raise RuntimeError("isolated Iceberg acceptance table already exists")
    schema = StructType(
        [
            StructField("road_id", LongType(), False),
            StructField("revision", IntegerType(), False),
            StructField("road_name_base64", StringType(), False),
            StructField("geometry_sha256", StringType(), False),
        ]
    )
    frame = spark.createDataFrame(plan["baseline_rows"], schema=schema)
    (
        frame.writeTo(args.table)
        .using("iceberg")
        .tableProperty("format-version", "2")
        .tableProperty("gda.acceptance", "flink-iceberg-interoperability")
        .tableProperty("gda.source_slice_sha256", plan["source_slice_sha256"])
        .create()
    )
    actual_rows = _rows(spark.table(args.table), include_tag=False)
    snapshots = _snapshots(spark, args.table)
    checks = {
        "baseline_rows_exact": list(actual_rows) == plan["baseline_rows"],
        "baseline_content_exact": _canonical_sha256(actual_rows)
        == plan["baseline_content_sha256"],
        "one_create_snapshot": len(snapshots) == 1
        and snapshots[0]["operation"] == "append",
    }
    return {
        "phase": "baseline",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "row_count": len(actual_rows),
        "content_sha256": _canonical_sha256(actual_rows),
        "schema": spark.table(args.table).schema.jsonValue(),
        "snapshots": snapshots,
        "baseline_snapshot_id": snapshots[0]["snapshot_id"],
    }


def _verify(spark, args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    table = spark.table(args.table)
    actual_rows = _rows(table, include_tag=True)
    snapshots = _snapshots(spark, args.table)
    baseline = (
        spark.read.option("snapshot-id", args.baseline_snapshot_id)
        .table(args.table)
    )
    baseline_rows = _rows(baseline, include_tag=False)
    schema_fields = [field.name for field in table.schema.fields]
    checks = {
        "flink_schema_evolution_visible": schema_fields
        == [
            "road_id",
            "revision",
            "road_name_base64",
            "geometry_sha256",
            "flink_commit_tag",
        ],
        "flink_append_visible_to_spark": list(actual_rows) == plan["final_rows"],
        "final_content_exact": _canonical_sha256(actual_rows)
        == plan["final_content_sha256"],
        "two_append_snapshots": len(snapshots) == 2
        and all(item["operation"] == "append" for item in snapshots),
        "snapshot_parent_chain_exact": len(snapshots) == 2
        and snapshots[1]["parent_id"] == snapshots[0]["snapshot_id"],
        "spark_time_travel_to_pre_flink_snapshot": (
            len(baseline_rows) == len(plan["baseline_rows"])
            and _canonical_sha256(baseline_rows)
            == plan["baseline_content_sha256"]
        ),
    }
    return {
        "phase": "verify",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "row_count": len(actual_rows),
        "content_sha256": _canonical_sha256(actual_rows),
        "schema": table.schema.jsonValue(),
        "snapshots": snapshots,
        "baseline_time_travel_rows": len(baseline_rows),
    }


def _recovery_verify(
    spark, args: argparse.Namespace, plan: dict[str, Any]
) -> dict[str, Any]:
    table = spark.table(args.table)
    columns = [
        "road_id",
        "revision",
        "road_name_base64",
        "geometry_sha256",
        "stream_event_id",
        "flink_commit_tag",
    ]
    actual_rows = tuple(
        {key: row[key] for key in columns}
        for row in table.select(*columns)
        .orderBy("road_id", "stream_event_id")
        .collect()
    )
    snapshots = _snapshots(spark, args.table)
    baseline = spark.read.option("snapshot-id", args.baseline_snapshot_id).table(
        args.table
    )
    baseline_rows = _rows(baseline, include_tag=False)
    schema_fields = [field.name for field in table.schema.fields]
    stream_event_ids = [
        row["stream_event_id"]
        for row in actual_rows
        if row["stream_event_id"] is not None
    ]
    parent_chain_exact = all(
        snapshots[index]["parent_id"] == snapshots[index - 1]["snapshot_id"]
        for index in range(1, len(snapshots))
    )
    checks = {
        "recovery_schema_visible_to_spark": schema_fields == columns,
        "checkpointed_rows_exact_without_duplicates": list(actual_rows)
        == plan["final_rows"],
        "four_unique_stream_events": (
            len(stream_event_ids) == 4
            and len(set(stream_event_ids)) == 4
            and set(stream_event_ids) == set(plan["stream_event_ids"])
        ),
        "final_content_exact": _canonical_sha256(actual_rows)
        == plan["final_content_sha256"],
        "checkpoint_append_snapshots_materialized": len(snapshots) >= 3
        and all(item["operation"] == "append" for item in snapshots),
        "snapshot_parent_chain_exact": parent_chain_exact,
        "spark_time_travel_to_pre_recovery_snapshot": (
            len(baseline_rows) == len(plan["baseline_rows"])
            and _canonical_sha256(baseline_rows)
            == plan["baseline_content_sha256"]
        ),
    }
    return {
        "phase": "recovery-verify",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "row_count": len(actual_rows),
        "stream_event_count": len(stream_event_ids),
        "content_sha256": _canonical_sha256(actual_rows),
        "schema": table.schema.jsonValue(),
        "snapshots": snapshots,
        "baseline_time_travel_rows": len(baseline_rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("baseline", "verify", "recovery-verify"))
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
        if args.phase == "baseline":
            phase = _baseline(spark, args, plan)
        elif args.phase == "verify":
            phase = _verify(spark, args, plan)
        else:
            phase = _recovery_verify(spark, args, plan)
    finally:
        spark.stop()
    report = {
        "schema": "gda.spark_iceberg_interop_phase.v1",
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
