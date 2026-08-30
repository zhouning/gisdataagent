#!/usr/bin/env python3
"""Exercise an isolated full baseline and incremental Iceberg merge."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from scripts.smoke_chongqing_osm_roads_default_lakehouse import (
    DEFAULT_EXPECTED_BBOX,
    DEFAULT_INPUT,
    DEFAULT_SOURCE_SHA256,
    _content_fingerprint,
    _quality_checks,
    _quality_metrics,
    _read_source,
    _sedona_version,
    _snapshot_state,
    _table_exists,
    _validated_table,
)

UPDATE_MARKER = "GDA source-sync certification update"
INSERT_MARKER = "GDA source-sync certification insert"
TABLE_COLUMNS = (
    "road_id",
    "road_class",
    "road_class_code",
    "road_name",
    "route_ref",
    "travel_direction",
    "max_speed_kph",
    "layer_level",
    "is_bridge",
    "is_tunnel",
    "source_vintage",
    "geometry_wkb",
    "srid",
    "bbox_xmin",
    "bbox_ymin",
    "bbox_xmax",
    "bbox_ymax",
)


def _canonical_fingerprint(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def baseline_previous_cursor(source_sha256: str) -> dict[str, Any]:
    return {"phase": "bootstrap_pending", "source_sha256": source_sha256}


def baseline_next_cursor(source_sha256: str) -> dict[str, Any]:
    return {"phase": "baseline_committed", "source_sha256": source_sha256}


def delta_next_cursor(source_slice_sha256: str) -> dict[str, Any]:
    return {
        "phase": "delta_committed",
        "sequence": 1,
        "source_slice_sha256": source_slice_sha256,
    }


def _validate_isolated_target(warehouse_uri: str, table: str) -> tuple[str, str, str]:
    catalog, namespace, table_name = _validated_table(table)
    parts = urlsplit(warehouse_uri)
    path_parts = tuple(part for part in parts.path.split("/") if part)
    if (
        parts.scheme != "s3a"
        or parts.netloc != "gis-agent-lakehouse"
        or len(path_parts) != 4
        or path_parts[:2] != ("acceptance", "source-sync")
        or path_parts[2] != namespace
        or path_parts[3] != "warehouse"
        or not namespace.startswith("gda_sync_cert_")
        or table_name != "osm_roads_incremental"
    ):
        raise ValueError("target must use one isolated source-sync certification namespace")
    return catalog, namespace, table_name


def _spark_session(args: argparse.Namespace):
    from pyspark.sql import SparkSession

    catalog, _, _ = _validate_isolated_target(args.warehouse_uri, args.table)
    return (
        SparkSession.builder.master("local[2]")
        .appName(f"chongqing-osm-source-sync-{args.phase}")
        .config(
            "spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        )
        .config(f"spark.sql.catalog.{catalog}", "org.apache.iceberg.spark.SparkCatalog")
        .config(f"spark.sql.catalog.{catalog}.type", "hadoop")
        .config(f"spark.sql.catalog.{catalog}.warehouse", args.warehouse_uri)
        .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer")
        .config(
            "spark.kryo.registrator",
            "org.apache.sedona.core.serde.SedonaKryoRegistrator",
        )
        .config("spark.hadoop.fs.s3a.endpoint", args.endpoint_url)
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
        .config("spark.hadoop.fs.s3a.access.key", args.access_key_id)
        .config("spark.hadoop.fs.s3a.secret.key", args.secret_access_key)
        .config(
            "spark.hadoop.fs.s3a.aws.credentials.provider",
            "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider",
        )
        .getOrCreate()
    )


def _transformed_source(spark, sedona, functions, input_uri: str):
    source = _read_source(spark, functions, input_uri)
    source.createOrReplaceTempView("chongqing_osm_incremental_source")
    return sedona.sql(
        """
        SELECT
          road_id,
          road_class,
          road_class_code,
          road_name,
          route_ref,
          travel_direction,
          max_speed_kph,
          layer_level,
          is_bridge,
          is_tunnel,
          source_vintage,
          ST_AsBinary(geom) AS geometry_wkb,
          4326 AS srid,
          ST_XMin(geom) AS bbox_xmin,
          ST_YMin(geom) AS bbox_ymin,
          ST_XMax(geom) AS bbox_xmax,
          ST_YMax(geom) AS bbox_ymax,
          ST_IsValid(geom) AS geometry_valid
        FROM (
          SELECT *, ST_GeomFromGeoJSON(geometry_json) AS geom
          FROM chongqing_osm_incremental_source
        ) parsed
        """
    ).cache()


def _row_fingerprints(frame, functions, road_ids: tuple[str, ...]) -> dict[str, str]:
    rows = (
        frame.where(functions.col("road_id").isin(*road_ids))
        .select(
            "road_id",
            functions.sha2(
                functions.to_json(functions.struct(*TABLE_COLUMNS)),
                256,
            ).alias("row_sha256"),
        )
        .collect()
    )
    return {str(row["road_id"]): str(row["row_sha256"]) for row in rows}


def _baseline(spark, sedona, functions, args: argparse.Namespace) -> dict[str, Any]:
    catalog, namespace, _ = _validate_isolated_target(args.warehouse_uri, args.table)
    if _table_exists(spark, args.table):
        raise RuntimeError("isolated baseline table already exists")
    transformed = _transformed_source(spark, sedona, functions, args.input_uri)
    metrics = _quality_metrics(transformed, functions)
    checks = _quality_checks(
        metrics,
        expected_rows=args.expected_rows,
        expected_bbox=DEFAULT_EXPECTED_BBOX,
    )
    if not all(checks.values()):
        raise RuntimeError(f"baseline source quality checks failed: {checks}")
    output = transformed.drop("geometry_valid")
    content_fingerprint = _content_fingerprint(output, functions)
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {catalog}.{namespace}")
    (
        output.writeTo(args.table)
        .using("iceberg")
        .tableProperty("format-version", "2")
        .tableProperty("gda.acceptance_scope", "isolated_source_sync")
        .tableProperty("gda.source_sha256", args.source_sha256)
        .tableProperty("gda.content_fingerprint", content_fingerprint)
        .create()
    )
    snapshot_id, history_count = _snapshot_state(spark, args.table)
    readback = spark.read.option("snapshot-id", str(snapshot_id)).table(args.table)
    checks.update(
        {
            "one_baseline_snapshot": snapshot_id is not None and history_count == 1,
            "baseline_time_travel_rows": readback.count() == args.expected_rows,
            "baseline_content_preserved": (
                _content_fingerprint(readback, functions) == content_fingerprint
            ),
        }
    )
    return {
        "schema": "gda.chongqing_osm_source_sync_provider.v1",
        "status": "passed" if all(checks.values()) else "failed",
        "phase": "baseline",
        "generated_at": datetime.now(UTC).isoformat(),
        "spark_version": spark.version,
        "sedona_version": _sedona_version(),
        "input_uri": args.input_uri,
        "source_slice_sha256": args.source_sha256,
        "previous_cursor": baseline_previous_cursor(args.source_sha256),
        "next_cursor": baseline_next_cursor(args.source_sha256),
        "target_commit_ref": {
            "provider": "iceberg",
            "operation": "full_baseline",
            "table": args.table,
            "snapshot_id": snapshot_id,
        },
        "target_content_sha256": content_fingerprint,
        "snapshot_id": snapshot_id,
        "history_count": history_count,
        "records_read": args.expected_rows,
        "records_inserted": args.expected_rows,
        "records_updated": 0,
        "records_deleted": 0,
        "records_output": args.expected_rows,
        "checks": checks,
    }


def _incremental(spark, functions, args: argparse.Namespace) -> dict[str, Any]:
    _validate_isolated_target(args.warehouse_uri, args.table)
    if not _table_exists(spark, args.table):
        raise RuntimeError("incremental table is missing its full baseline")
    baseline_snapshot_id, baseline_history_count = _snapshot_state(spark, args.table)
    if baseline_snapshot_id is None or baseline_history_count != 1:
        raise RuntimeError("incremental phase requires exactly one baseline snapshot")
    baseline = spark.table(args.table).cache()
    selected = baseline.orderBy("road_id").select("road_id", "road_name").limit(2).collect()
    if len(selected) != 2:
        raise RuntimeError("baseline does not contain two deterministic change targets")
    delete_road_id = str(selected[0]["road_id"])
    update_road_id = str(selected[1]["road_id"])
    update_previous_name = selected[1]["road_name"]
    insert_road_id = args.insert_road_id
    if baseline.where(functions.col("road_id") == insert_road_id).limit(1).count() != 0:
        raise RuntimeError("certification insert road ID already exists")

    before_hashes = _row_fingerprints(
        baseline,
        functions,
        (delete_road_id, update_road_id),
    )
    delete_change = (
        baseline.where(functions.col("road_id") == delete_road_id)
        .withColumn("_change_type", functions.lit("delete"))
    )
    update_change = (
        baseline.where(functions.col("road_id") == update_road_id)
        .withColumn("road_name", functions.lit(UPDATE_MARKER))
        .withColumn("_change_type", functions.lit("update"))
    )
    insert_change = (
        baseline.where(functions.col("road_id") == update_road_id)
        .withColumn("road_id", functions.lit(insert_road_id))
        .withColumn("road_name", functions.lit(INSERT_MARKER))
        .withColumn("_change_type", functions.lit("insert"))
    )
    changes = delete_change.unionByName(update_change).unionByName(insert_change).cache()
    if changes.count() != 3:
        raise RuntimeError("incremental source slice must contain exactly three changes")
    after_hashes = _row_fingerprints(
        changes.drop("_change_type"),
        functions,
        (update_road_id, insert_road_id),
    )
    delta_manifest = (
        {
            "operation": "delete",
            "road_id": delete_road_id,
            "before_sha256": before_hashes[delete_road_id],
            "after_sha256": None,
        },
        {
            "operation": "update",
            "road_id": update_road_id,
            "before_sha256": before_hashes[update_road_id],
            "after_sha256": after_hashes[update_road_id],
        },
        {
            "operation": "insert",
            "road_id": insert_road_id,
            "before_sha256": None,
            "after_sha256": after_hashes[insert_road_id],
        },
    )
    source_slice_sha256 = _canonical_fingerprint(delta_manifest)
    changes.createOrReplaceTempView("chongqing_osm_road_changes")
    update_set = ", ".join(f"target.{name} = source.{name}" for name in TABLE_COLUMNS)
    insert_columns = ", ".join(TABLE_COLUMNS)
    insert_values = ", ".join(f"source.{name}" for name in TABLE_COLUMNS)
    spark.sql(
        f"""
        MERGE INTO {args.table} AS target
        USING chongqing_osm_road_changes AS source
        ON target.road_id = source.road_id
        WHEN MATCHED AND source._change_type = 'delete' THEN DELETE
        WHEN MATCHED AND source._change_type = 'update' THEN UPDATE SET {update_set}
        WHEN NOT MATCHED AND source._change_type = 'insert'
          THEN INSERT ({insert_columns}) VALUES ({insert_values})
        """
    )

    incremental_snapshot_id, history_count = _snapshot_state(spark, args.table)
    current = spark.table(args.table).cache()
    current_fingerprint = _content_fingerprint(current, functions)
    baseline_time_travel = spark.read.option(
        "snapshot-id", str(baseline_snapshot_id)
    ).table(args.table)
    incremental_time_travel = spark.read.option(
        "snapshot-id", str(incremental_snapshot_id)
    ).table(args.table)
    checks = {
        "merge_created_one_snapshot": (
            incremental_snapshot_id != baseline_snapshot_id and history_count == 2
        ),
        "row_count_conserved": current.count() == args.expected_rows,
        "road_ids_remain_unique": (
            current.select("road_id").distinct().count() == args.expected_rows
        ),
        "delete_applied": (
            current.where(functions.col("road_id") == delete_road_id).count() == 0
        ),
        "update_applied": (
            current.where(
                (functions.col("road_id") == update_road_id)
                & (functions.col("road_name") == UPDATE_MARKER)
            ).count()
            == 1
        ),
        "insert_applied": (
            current.where(
                (functions.col("road_id") == insert_road_id)
                & (functions.col("road_name") == INSERT_MARKER)
            ).count()
            == 1
        ),
        "baseline_time_travel_preserved": (
            baseline_time_travel.count() == args.expected_rows
            and baseline_time_travel.where(
                functions.col("road_id") == delete_road_id
            ).count()
            == 1
            and baseline_time_travel.where(
                functions.col("road_id") == insert_road_id
            ).count()
            == 0
            and baseline_time_travel.where(
                (functions.col("road_id") == update_road_id)
                & functions.col("road_name").eqNullSafe(update_previous_name)
            ).count()
            == 1
        ),
        "incremental_time_travel_preserved": (
            incremental_time_travel.count() == args.expected_rows
            and _content_fingerprint(incremental_time_travel, functions)
            == current_fingerprint
        ),
    }
    return {
        "schema": "gda.chongqing_osm_source_sync_provider.v1",
        "status": "passed" if all(checks.values()) else "failed",
        "phase": "incremental",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_slice_sha256": source_slice_sha256,
        "source_slice": list(delta_manifest),
        "previous_cursor": baseline_next_cursor(args.source_sha256),
        "next_cursor": delta_next_cursor(source_slice_sha256),
        "target_commit_ref": {
            "provider": "iceberg",
            "operation": "merge",
            "table": args.table,
            "snapshot_id": incremental_snapshot_id,
            "parent_snapshot_id": baseline_snapshot_id,
        },
        "target_content_sha256": current_fingerprint,
        "baseline_snapshot_id": baseline_snapshot_id,
        "snapshot_id": incremental_snapshot_id,
        "history_count": history_count,
        "delete_road_id": delete_road_id,
        "update_road_id": update_road_id,
        "insert_road_id": insert_road_id,
        "records_read": 3,
        "records_inserted": 1,
        "records_updated": 1,
        "records_deleted": 1,
        "records_output": args.expected_rows,
        "checks": checks,
    }


def _verify_cleanup(spark, functions, args: argparse.Namespace) -> dict[str, Any]:
    catalog, namespace, _ = _validate_isolated_target(args.warehouse_uri, args.table)
    checks: dict[str, bool] = {}
    cleanup: dict[str, bool] = {}
    try:
        snapshot_id, history_count = _snapshot_state(spark, args.table)
        baseline = spark.read.option(
            "snapshot-id", str(args.baseline_snapshot_id)
        ).table(args.table)
        incremental = spark.read.option(
            "snapshot-id", str(args.incremental_snapshot_id)
        ).table(args.table)
        checks = {
            "replay_created_no_snapshot": (
                history_count == args.expected_history_count
                and snapshot_id == args.incremental_snapshot_id
            ),
            "baseline_time_travel_rows": baseline.count() == args.expected_rows,
            "incremental_time_travel_rows": incremental.count() == args.expected_rows,
            "baseline_delete_target_present": baseline.where(
                functions.col("road_id") == args.delete_road_id
            ).count()
            == 1,
            "incremental_delete_target_absent": incremental.where(
                functions.col("road_id") == args.delete_road_id
            ).count()
            == 0,
            "incremental_insert_present": incremental.where(
                functions.col("road_id") == args.insert_road_id
            ).count()
            == 1,
            "incremental_update_present": incremental.where(
                (functions.col("road_id") == args.update_road_id)
                & (functions.col("road_name") == UPDATE_MARKER)
            ).count()
            == 1,
        }
    finally:
        if _table_exists(spark, args.table):
            spark.sql(f"DROP TABLE {args.table} PURGE")
        spark.sql(f"DROP NAMESPACE IF EXISTS {catalog}.{namespace}")
        hadoop_path = spark._jvm.org.apache.hadoop.fs.Path(args.warehouse_uri)
        filesystem = hadoop_path.getFileSystem(spark._jsc.hadoopConfiguration())
        filesystem.delete(hadoop_path, True)
        cleanup = {
            "table_removed": not _table_exists(spark, args.table),
            "warehouse_prefix_removed": not bool(filesystem.exists(hadoop_path)),
        }
    return {
        "schema": "gda.chongqing_osm_source_sync_provider.v1",
        "status": (
            "passed" if checks and all(checks.values()) and all(cleanup.values()) else "failed"
        ),
        "phase": "verify_cleanup",
        "generated_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "cleanup": cleanup,
    }


def run_phase(args: argparse.Namespace) -> dict[str, Any]:
    from pyspark.sql import functions as F
    from sedona.spark import SedonaContext

    spark = _spark_session(args)
    try:
        spark.sparkContext.setLogLevel("WARN")
        sedona = SedonaContext.create(spark)
        if args.phase == "baseline":
            return _baseline(spark, sedona, F, args)
        if args.phase == "incremental":
            return _incremental(spark, F, args)
        return _verify_cleanup(spark, F, args)
    finally:
        spark.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("baseline", "incremental", "verify-cleanup"))
    parser.add_argument("--warehouse-uri", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--input-uri", default=DEFAULT_INPUT)
    parser.add_argument("--source-sha256", default=DEFAULT_SOURCE_SHA256)
    parser.add_argument("--expected-rows", type=int, default=50366)
    parser.add_argument("--insert-road-id", default="gda-source-sync-cert-insert")
    parser.add_argument("--baseline-snapshot-id", type=int)
    parser.add_argument("--incremental-snapshot-id", type=int)
    parser.add_argument("--expected-history-count", type=int, default=2)
    parser.add_argument("--delete-road-id")
    parser.add_argument("--update-road-id")
    parser.add_argument("--endpoint-url", default=os.environ.get("AWS_ENDPOINT_URL", "http://minio:9000"))
    parser.add_argument(
        "--access-key-id",
        default=os.environ.get("AWS_ACCESS_KEY_ID", "minio_admin"),
    )
    parser.add_argument(
        "--secret-access-key",
        default=os.environ.get("AWS_SECRET_ACCESS_KEY", "local_dev_minio_secret"),
    )
    parser.add_argument("--report-path", type=Path, required=True)
    args = parser.parse_args()
    if args.phase == "verify-cleanup" and any(
        value is None
        for value in (
            args.baseline_snapshot_id,
            args.incremental_snapshot_id,
            args.delete_road_id,
            args.update_road_id,
        )
    ):
        parser.error("verify-cleanup requires snapshot and changed-road arguments")
    report = run_phase(args)
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
