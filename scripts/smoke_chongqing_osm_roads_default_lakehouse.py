"""Validate the Chongqing OSM product through Spark, Sedona, and Iceberg."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

DEFAULT_INPUT = (
    "s3a://gis-agent-lakehouse/serving/ads_transportation/chongqing_osm_roads/"
    "sha256-52645a3b7cdac54a89df26dc88004f2ae93ce96f81e36af940bdb2237262353d/"
    "chongqing-osm-roads-52645a3b7cda.geojson"
)
DEFAULT_WAREHOUSE = "s3a://gis-agent-lakehouse/warehouse/iceberg"
DEFAULT_TABLE = "lakehouse.gis_dwd.chongqing_osm_roads"
DEFAULT_SEMANTIC_SHA256 = (
    "52645a3b7cdac54a89df26dc88004f2ae93ce96f81e36af940bdb2237262353d"
)
DEFAULT_SOURCE_SHA256 = (
    "c0e99b5f69239e9ade8360399edc15fa47e71f9cfb68939223d3b8f4c3041164"
)
DEFAULT_RUN_ID = "859195f5-5e81-59a6-855a-de52b3b11d7d"
DEFAULT_EXPECTED_BBOX = (105.30805, 28.163572, 110.173223, 32.156202)
_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_FINGERPRINT_COLUMNS = (
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-uri", default=DEFAULT_INPUT)
    parser.add_argument("--warehouse-uri", default=DEFAULT_WAREHOUSE)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--semantic-sha256", default=DEFAULT_SEMANTIC_SHA256)
    parser.add_argument("--source-sha256", default=DEFAULT_SOURCE_SHA256)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--materialization-run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--expected-rows", type=int, default=50366)
    parser.add_argument(
        "--expected-bbox",
        type=_parse_bbox,
        default=DEFAULT_EXPECTED_BBOX,
        metavar="XMIN,YMIN,XMAX,YMAX",
    )
    parser.add_argument("--endpoint-url", default=os.environ.get("AWS_ENDPOINT_URL", "http://minio:9000"))
    parser.add_argument(
        "--access-key-id",
        default=os.environ.get("AWS_ACCESS_KEY_ID", "minio_admin"),
    )
    parser.add_argument(
        "--secret-access-key",
        default=os.environ.get("AWS_SECRET_ACCESS_KEY", "local_dev_minio_secret"),
    )
    parser.add_argument("--report-path", type=Path)
    args = parser.parse_args()

    report = run_smoke(args)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.report_path:
        args.report_path.parent.mkdir(parents=True, exist_ok=True)
        args.report_path.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
    from sedona.spark import SedonaContext

    catalog, namespace, _ = _validated_table(args.table)
    builder = (
        SparkSession.builder.master("local[2]")
        .appName("chongqing-osm-roads-default-lakehouse")
        .config(
            "spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        )
        .config(f"spark.sql.catalog.{catalog}", "org.apache.iceberg.spark.SparkCatalog")
        .config(f"spark.sql.catalog.{catalog}.type", "hadoop")
        .config(f"spark.sql.catalog.{catalog}.warehouse", args.warehouse_uri)
        .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer")
        .config("spark.kryo.registrator", "org.apache.sedona.core.serde.SedonaKryoRegistrator")
        .config("spark.hadoop.fs.s3a.endpoint", args.endpoint_url)
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
        .config("spark.hadoop.fs.s3a.access.key", args.access_key_id)
        .config("spark.hadoop.fs.s3a.secret.key", args.secret_access_key)
        .config(
            "spark.hadoop.fs.s3a.aws.credentials.provider",
            "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider",
        )
    )
    spark = builder.getOrCreate()
    try:
        spark.sparkContext.setLogLevel("WARN")
        sedona = SedonaContext.create(spark)
        source = _read_source(spark, F, args.input_uri)
        source.createOrReplaceTempView("chongqing_osm_roads_source")
        transformed = sedona.sql(
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
              FROM chongqing_osm_roads_source
            ) parsed
            """
        ).cache()
        source_metrics = _quality_metrics(transformed, F)
        checks = _quality_checks(
            source_metrics,
            expected_rows=args.expected_rows,
            expected_bbox=args.expected_bbox,
        )
        if not all(checks.values()):
            raise RuntimeError(f"source quality checks failed: {checks}")

        output = transformed.drop("geometry_valid")
        content_fingerprint = _content_fingerprint(output, F)
        spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {catalog}.{namespace}")
        existed = _table_exists(spark, args.table)
        previous_snapshot_id, previous_history_count = _snapshot_state(spark, args.table)
        current_semantic_sha256 = _table_property(
            spark,
            args.table,
            "gda.semantic_sha256",
        )
        current_content_fingerprint = _table_property(
            spark,
            args.table,
            "gda.content_fingerprint",
        )
        reused = (
            existed
            and current_semantic_sha256 == args.semantic_sha256
            and current_content_fingerprint == content_fingerprint
        )
        if not reused:
            writer = (
                output.writeTo(args.table)
                .using("iceberg")
                .tableProperty("format-version", "2")
                .tableProperty("gda.semantic_sha256", args.semantic_sha256)
                .tableProperty("gda.source_sha256", args.source_sha256)
                .tableProperty("gda.content_fingerprint", content_fingerprint)
                .tableProperty("gda.run_id", args.run_id)
                .tableProperty("gda.source_uri", args.input_uri)
            )
            if existed:
                writer.createOrReplace()
            else:
                writer.create()

        table = spark.table(args.table).cache()
        table_metrics = _quality_metrics(
            table.withColumn("geometry_valid", F.lit(True)),
            F,
        )
        table_checks = _quality_checks(
            table_metrics,
            expected_rows=args.expected_rows,
            expected_bbox=args.expected_bbox,
        )
        table_content_fingerprint = _content_fingerprint(table, F)
        snapshot_id, history_count = _snapshot_state(spark, args.table)
        time_travel_rows = (
            spark.read.option("snapshot-id", str(snapshot_id)).table(args.table).count()
        )
        checks.update(
            {
                "iceberg_readback": all(table_checks.values()),
                "content_fingerprint_preserved": (
                    table_content_fingerprint == content_fingerprint
                ),
                "time_travel_readback": time_travel_rows == args.expected_rows,
                "idempotent_snapshot_reuse": (
                    not reused
                    or (
                        snapshot_id == previous_snapshot_id
                        and history_count == previous_history_count
                    )
                ),
            }
        )
        status = "passed" if all(checks.values()) else "failed"
        report = {
            "schema": "gda.chongqing_osm_roads_default_lakehouse_acceptance.v1",
            "status": status,
            "generated_at": datetime.now(UTC).isoformat(),
            "profile": "default_lakehouse",
            "spark_version": spark.version,
            "sedona_version": _sedona_version(),
            "iceberg_format_version": 2,
            "input_uri": args.input_uri,
            "warehouse_uri": args.warehouse_uri,
            "table": args.table,
            "source_run_id": args.run_id,
            "materialization_run_id": args.materialization_run_id,
            "semantic_sha256": args.semantic_sha256,
            "source_sha256": args.source_sha256,
            "content_fingerprint": content_fingerprint,
            "table_content_fingerprint": table_content_fingerprint,
            "row_count": table_metrics["row_count"],
            "distinct_road_ids": table_metrics["distinct_road_ids"],
            "bbox": table_metrics["bbox"],
            "snapshot_id": snapshot_id,
            "history_count": history_count,
            "previous_snapshot_id": previous_snapshot_id,
            "previous_history_count": previous_history_count,
            "time_travel_rows": time_travel_rows,
            "table_created": not existed,
            "snapshot_reused": reused,
            "checks": checks,
        }
        if status != "passed":
            raise RuntimeError(f"default lakehouse acceptance failed: {report}")
        return report
    finally:
        spark.stop()


def _read_source(spark, functions, input_uri: str):
    raw = spark.read.option("multiLine", "true").json(input_uri)
    return raw.select(functions.explode("features").alias("feature")).select(
        functions.col("feature.properties.road_id").cast("string").alias("road_id"),
        functions.col("feature.properties.road_class").cast("string").alias("road_class"),
        functions.col("feature.properties.road_class_code").cast("int").alias("road_class_code"),
        functions.col("feature.properties.road_name").cast("string").alias("road_name"),
        functions.col("feature.properties.route_ref").cast("string").alias("route_ref"),
        functions.col("feature.properties.travel_direction").cast("string").alias("travel_direction"),
        functions.col("feature.properties.max_speed_kph").cast("int").alias("max_speed_kph"),
        functions.col("feature.properties.layer_level").cast("int").alias("layer_level"),
        functions.col("feature.properties.is_bridge").cast("boolean").alias("is_bridge"),
        functions.col("feature.properties.is_tunnel").cast("boolean").alias("is_tunnel"),
        functions.col("feature.properties.source_vintage").cast("int").alias("source_vintage"),
        functions.to_json("feature.geometry").alias("geometry_json"),
    )


def _quality_metrics(frame, functions) -> dict[str, Any]:
    row = frame.agg(
        functions.count("*").alias("row_count"),
        functions.countDistinct("road_id").alias("distinct_road_ids"),
        functions.sum(functions.col("road_id").isNull().cast("int")).alias("null_road_ids"),
        functions.sum(functions.col("geometry_wkb").isNull().cast("int")).alias("null_geometry"),
        functions.sum((~functions.col("geometry_valid")).cast("int")).alias("invalid_geometry"),
        functions.min("bbox_xmin").alias("xmin"),
        functions.min("bbox_ymin").alias("ymin"),
        functions.max("bbox_xmax").alias("xmax"),
        functions.max("bbox_ymax").alias("ymax"),
        functions.min("srid").alias("min_srid"),
        functions.max("srid").alias("max_srid"),
    ).first()
    return {
        "row_count": int(row["row_count"]),
        "distinct_road_ids": int(row["distinct_road_ids"]),
        "null_road_ids": int(row["null_road_ids"] or 0),
        "null_geometry": int(row["null_geometry"] or 0),
        "invalid_geometry": int(row["invalid_geometry"] or 0),
        "bbox": [float(row[name]) for name in ("xmin", "ymin", "xmax", "ymax")],
        "srids": [int(row["min_srid"]), int(row["max_srid"])],
    }


def _quality_checks(
    metrics: dict[str, Any],
    *,
    expected_rows: int,
    expected_bbox: tuple[float, float, float, float],
) -> dict[str, bool]:
    return {
        "row_count_preserved": metrics["row_count"] == expected_rows,
        "road_id_unique_complete": (
            metrics["distinct_road_ids"] == expected_rows
            and metrics["null_road_ids"] == 0
        ),
        "geometry_valid_complete": (
            metrics["null_geometry"] == 0 and metrics["invalid_geometry"] == 0
        ),
        "srid_is_4326": metrics["srids"] == [4326, 4326],
        "bbox_preserved": all(
            abs(actual - expected) <= 1e-6
            for actual, expected in zip(metrics["bbox"], expected_bbox, strict=True)
        ),
    }


def _content_fingerprint(frame, functions) -> str:
    row_hashes = (
        frame.select(
            "road_id",
            functions.sha2(
                functions.to_json(functions.struct(*_FINGERPRINT_COLUMNS)),
                256,
            ).alias("row_sha256"),
        )
        .orderBy("road_id")
        .select("row_sha256")
    )
    digest = hashlib.sha256()
    for row in row_hashes.toLocalIterator():
        digest.update(row["row_sha256"].encode("ascii"))
    return digest.hexdigest()


def _table_exists(spark, table: str) -> bool:
    try:
        spark.sql(f"DESCRIBE TABLE {table}").limit(1).collect()
        return True
    except Exception:
        return False


def _table_property(spark, table: str, key: str) -> str | None:
    if not _table_exists(spark, table):
        return None
    row = spark.sql(f"SHOW TBLPROPERTIES {table} ('{key}')").first()
    if row is None:
        return None
    value = str(row["value"])
    if value.startswith("Table ") and "does not have property" in value:
        return None
    return value


def _snapshot_state(spark, table: str) -> tuple[int | None, int]:
    if not _table_exists(spark, table):
        return None, 0
    rows = spark.sql(
        f"SELECT snapshot_id FROM {table}.history ORDER BY made_current_at, snapshot_id"
    ).collect()
    return (int(rows[-1]["snapshot_id"]), len(rows)) if rows else (None, 0)


def _sedona_version() -> str:
    return version("apache-sedona")


def _validated_table(table: str) -> tuple[str, str, str]:
    parts = tuple(table.split("."))
    if len(parts) != 3 or any(not _IDENTIFIER_RE.fullmatch(part) for part in parts):
        raise ValueError("table must be catalog.namespace.table with safe identifiers")
    return parts


def _parse_bbox(value: str) -> tuple[float, float, float, float]:
    try:
        bbox = tuple(float(part) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("bbox must contain four numbers") from exc
    if len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise argparse.ArgumentTypeError("bbox must be xmin,ymin,xmax,ymax")
    return bbox


if __name__ == "__main__":
    main()
