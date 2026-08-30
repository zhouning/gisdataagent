#!/usr/bin/env python3
"""Run a bounded Spark Iceberg REST catalog acceptance against Gravitino."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import UUID, uuid5

from data_agent.iceberg_architecture_harvester import (
    IcebergArchitectureTarget,
    harvest_gravitino_iceberg_table,
    project_iceberg_rest_table_response,
)

SPARK_JARS = ",".join(
    (
        "/opt/spark/jars-extra/iceberg-spark-runtime-3.5_2.12-1.6.1.jar",
        "/opt/spark/jars-extra/iceberg-aws-bundle-1.6.1.jar",
        "/opt/spark/jars-extra/postgresql-42.7.4.jar",
    )
)
SPARK_CLASSPATH = SPARK_JARS.replace(",", ":")
TABLE_RE = re.compile(r"^rest\.gda_rest_[0-9a-f]{10}\.chongqing_osm_roads$")
ARCHITECTURE_IDENTITY = UUID("9c5a4d44-3df1-4c71-8e47-e13d8127ec79")


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
        raise ValueError("unsafe REST Iceberg table identifier")
    rest_uri = os.environ.get("GRAVITINO_ICEBERG_REST_URI", "")
    rest_prefix = os.environ.get("GRAVITINO_ICEBERG_REST_PREFIX", "")
    if rest_uri != "http://gravitino:9001/iceberg":
        raise ValueError("unexpected Gravitino Iceberg REST URI")
    if rest_prefix != "default_catalog":
        raise ValueError("unexpected Gravitino Iceberg REST prefix")
    return (
        SparkSession.builder.master("local[2]")
        .appName("gda-gravitino-iceberg-rest-acceptance")
        .config("spark.jars", SPARK_JARS)
        .config("spark.driver.extraClassPath", SPARK_CLASSPATH)
        .config("spark.executor.extraClassPath", SPARK_CLASSPATH)
        .config(
            "spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        )
        .config("spark.sql.catalog.rest", "org.apache.iceberg.spark.SparkCatalog")
        .config(
            "spark.sql.catalog.rest.catalog-impl",
            "org.apache.iceberg.rest.RESTCatalog",
        )
        .config("spark.sql.catalog.rest.uri", rest_uri)
        .config("spark.sql.catalog.rest.prefix", rest_prefix)
        .config(
            "spark.sql.catalog.rest.io-impl",
            "org.apache.iceberg.aws.s3.S3FileIO",
        )
        .config("spark.sql.catalog.rest.s3.endpoint", "http://minio:9000")
        .config("spark.sql.catalog.rest.s3.path-style-access", "true")
        .config("spark.sql.catalog.rest.client.region", "us-east-1")
        .getOrCreate()
    )


def _rows(frame, columns: list[str]) -> list[dict[str, Any]]:
    return [
        {column: row[column] for column in columns}
        for row in frame.select(*columns).orderBy("road_id").collect()
    ]


def _snapshots(spark, table: str) -> list[dict[str, Any]]:
    return [
        {
            "snapshot_id": str(row["snapshot_id"]),
            "parent_id": str(row["parent_id"])
            if row["parent_id"] is not None
            else None,
            "operation": row["operation"],
        }
        for row in spark.sql(
            f"SELECT snapshot_id, parent_id, operation FROM {table}.snapshots "
            "ORDER BY committed_at, snapshot_id"
        ).collect()
    ]


def _table_location(spark, table: str) -> str | None:
    for row in spark.sql(f"DESCRIBE TABLE EXTENDED {table}").collect():
        if row["col_name"] == "Location":
            return str(row["data_type"])
    return None


def _read_rest_table(table: str) -> tuple[str, dict[str, Any]]:
    rest_uri = os.environ["GRAVITINO_ICEBERG_REST_URI"].rstrip("/")
    rest_prefix = os.environ["GRAVITINO_ICEBERG_REST_PREFIX"]
    _, namespace, object_name = table.split(".")
    endpoint = (
        f"{rest_uri}/v1/{quote(rest_prefix, safe='')}"
        f"/namespaces/{quote(namespace, safe='')}/tables/{quote(object_name, safe='')}"
    )
    request = Request(endpoint, headers={"Accept": "application/json"})
    with urlopen(request, timeout=10) as response:  # noqa: S310 - fixed disposable endpoint
        if response.status != 200:
            raise RuntimeError(f"Gravitino REST table GET returned HTTP {response.status}")
        payload = json.load(response)
    return endpoint, project_iceberg_rest_table_response(payload, object_name=object_name)


def _architecture_harvest(
    projected: dict[str, Any],
    *,
    table: str,
    content_checksum: str,
) -> dict[str, Any]:
    _, namespace, object_name = table.split(".")
    tenant_id = "gravitino-rest-acceptance"
    target = IcebergArchitectureTarget(
        tenant_id=tenant_id,
        resource_urn=f"gda://{tenant_id}/dataset/{object_name}",
        resource_version_id=uuid5(ARCHITECTURE_IDENTITY, table),
        metalake="rest",
        catalog=os.environ["GRAVITINO_ICEBERG_REST_PREFIX"],
        namespace=namespace,
        object_name=object_name,
        snapshot_ref=f"iceberg-table:{table}",
        content_checksum=content_checksum,
    )
    harvest = harvest_gravitino_iceberg_table(
        projected,
        target,
        observed_by="workload:gravitino-rest-acceptance",
        observed_at=datetime.now(UTC),
    )
    assert harvest.schema_snapshot is not None
    assert harvest.schema_candidate is not None
    assert harvest.physical_location_candidate is not None
    return {
        "observation": harvest.observation.model_dump(mode="json"),
        "schema_snapshot": {
            "field_count": len(harvest.schema_snapshot.fields),
            "snapshot_sha256": harvest.schema_snapshot.snapshot_sha256,
        },
        "schema_candidate_sha256": harvest.schema_candidate.schema_sha256,
        "physical_location_sha256": harvest.physical_location_candidate.location_sha256,
        "snapshot_lineage": [
            entry.model_dump(mode="json")
            for entry in (harvest.snapshot_lineage or ())
        ],
    }


def run_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    spark = _spark(args)
    table = args.table
    base_columns = [
        "road_id",
        "revision",
        "road_name_base64",
        "geometry_sha256",
    ]
    final_columns = [*base_columns, "flink_commit_tag"]
    if args.plan:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        baseline_rows = plan["baseline_rows"]
        appended_row = {
            **plan["append_row"],
            "flink_commit_tag": plan["commit_tag"],
        }
        if plan["commit_tag"] != args.commit_tag:
            raise ValueError("interop plan commit tag does not match acceptance tag")
    else:
        baseline_rows = [
            {
                "road_id": 1,
                "revision": 1,
                "road_name_base64": "cm9hZF8x",
                "geometry_sha256": "a" * 64,
            },
            {
                "road_id": 2,
                "revision": 1,
                "road_name_base64": "cm9hZF8y",
                "geometry_sha256": "b" * 64,
            },
            {
                "road_id": 3,
                "revision": 1,
                "road_name_base64": "cm9hZF8z",
                "geometry_sha256": "c" * 64,
            },
        ]
        appended_row = {
            "road_id": 4,
            "revision": 2,
            "road_name_base64": "cm9hZF80",
            "geometry_sha256": "d" * 64,
            "flink_commit_tag": args.commit_tag,
        }
    expected_final = [
        {**row, "flink_commit_tag": None} for row in baseline_rows
    ] + [appended_row]
    expected_final.sort(key=lambda row: row["road_id"])
    try:
        namespace = table.split(".")[1]
        if args.verify_only:
            final_actual = _rows(spark.table(table), final_columns)
            snapshots = _snapshots(spark, table)
            baseline_time_travel = _rows(
                spark.read.option(
                    "snapshot-id", snapshots[0]["snapshot_id"]
                ).table(table),
                base_columns,
            )
            rest_endpoint, rest_table = _read_rest_table(table)
            architecture = _architecture_harvest(
                rest_table,
                table=table,
                content_checksum=_canonical_sha256(final_actual),
            )
            checks = {
                "final_rows_exact": final_actual == expected_final,
                "schema_evolution_visible": "flink_commit_tag"
                in [field.name for field in spark.table(table).schema.fields],
                "snapshot_parent_chain": len(snapshots) >= 2
                and all(
                    item["parent_id"] == snapshots[index - 1]["snapshot_id"]
                    for index, item in enumerate(snapshots[1:], start=1)
                ),
                "baseline_time_travel_exact": baseline_time_travel == baseline_rows,
                "rest_table_read_through_rest": bool(rest_endpoint),
                "rest_payload_projected_to_architecture_candidate": bool(
                    architecture["observation"]["observation_sha256"]
                ),
                "rest_snapshot_lineage_matches_spark": rest_table["snapshots"] == snapshots,
            }
            return {
                "schema": "gda.gravitino_iceberg_rest.verify.v1",
                "status": "passed" if all(checks.values()) else "failed",
                "table": table,
                "location": _table_location(spark, table),
                "final": {
                    "rows": len(final_actual),
                    "content_sha256": _canonical_sha256(final_actual),
                    "snapshots": snapshots,
                },
                "rest": {"endpoint": rest_endpoint, "table": rest_table},
                "architecture_harvest": architecture,
                "checks": checks,
            }
        spark.sql(f"CREATE NAMESPACE IF NOT EXISTS rest.{namespace}")
        frame = spark.createDataFrame(baseline_rows)
        (
            frame.writeTo(table)
            .using("iceberg")
            .tableProperty("format-version", "2")
            .tableProperty("gda.acceptance", "gravitino-iceberg-rest")
            .create()
        )
        baseline_actual = _rows(spark.table(table), base_columns)
        baseline_snapshots = _snapshots(spark, table)
        if args.prepare_only:
            return {
                "schema": "gda.gravitino_iceberg_rest.prepare.v1",
                "status": "passed",
                "table": table,
                "location": _table_location(spark, table),
                "baseline": {
                    "rows": len(baseline_actual),
                    "content_sha256": _canonical_sha256(baseline_actual),
                    "snapshot_id": baseline_snapshots[0]["snapshot_id"],
                },
                "checks": {
                    "namespace_created_through_rest": True,
                    "baseline_rows_exact": baseline_actual == baseline_rows,
                    "baseline_snapshot_created": len(baseline_snapshots) == 1,
                    "table_location_is_s3": (
                        _table_location(spark, table) or ""
                    ).startswith("s3://gis-agent-lakehouse/acceptance/gravitino-rest/"),
                },
            }
        spark.sql(f"ALTER TABLE {table} ADD COLUMNS (flink_commit_tag STRING)")
        append_frame = spark.createDataFrame([appended_row])
        append_frame.writeTo(table).append()
        final_actual = _rows(spark.table(table), final_columns)
        evolved_snapshots = _snapshots(spark, table)
        baseline_time_travel = _rows(
            spark.read.option(
                "snapshot-id", baseline_snapshots[0]["snapshot_id"]
            ).table(table),
            base_columns,
        )
        rest_endpoint, rest_table = _read_rest_table(table)
        architecture = _architecture_harvest(
            rest_table,
            table=table,
            content_checksum=_canonical_sha256(final_actual),
        )
        rest_snapshots = rest_table["snapshots"]
        checks = {
            "namespace_created_through_rest": True,
            "baseline_rows_exact": baseline_actual == baseline_rows,
            "baseline_snapshot_created": len(baseline_snapshots) == 1,
            "schema_evolution_visible": "flink_commit_tag"
            in [field.name for field in spark.table(table).schema.fields],
            "append_visible": final_actual == expected_final,
            "snapshot_parent_chain": len(evolved_snapshots) >= 2
            and all(
                item["parent_id"] == evolved_snapshots[index - 1]["snapshot_id"]
                for index, item in enumerate(evolved_snapshots[1:], start=1)
            ),
            "baseline_time_travel_exact": baseline_time_travel == baseline_rows,
            "table_location_is_s3": (
                _table_location(spark, table) or ""
            ).startswith("s3://gis-agent-lakehouse/acceptance/gravitino-rest/"),
            "rest_table_read_through_rest": bool(rest_endpoint),
            "rest_payload_projected_to_architecture_candidate": bool(
                architecture["observation"]["observation_sha256"]
            ),
            "rest_snapshot_lineage_matches_spark": rest_snapshots == evolved_snapshots,
        }
        return {
            "schema": "gda.gravitino_iceberg_rest.acceptance.v1",
            "status": "passed" if all(checks.values()) else "failed",
            "table": table,
            "location": _table_location(spark, table),
            "baseline": {
                "rows": len(baseline_actual),
                "content_sha256": _canonical_sha256(baseline_actual),
                "snapshot_id": baseline_snapshots[0]["snapshot_id"],
            },
            "final": {
                "rows": len(final_actual),
                "content_sha256": _canonical_sha256(final_actual),
                "snapshots": evolved_snapshots,
            },
            "rest": {
                "endpoint": rest_endpoint,
                "table": rest_table,
            },
            "architecture_harvest": architecture,
            "checks": checks,
        }
    finally:
        spark.stop()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--commit-tag", default="rest_catalog_acceptance")
    parser.add_argument("--plan", type=Path)
    args = parser.parse_args()
    report = run_acceptance(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
