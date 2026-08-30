"""Materialize the restricted Chongqing building snapshot into Iceberg ODS."""

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
    "s3a://gis-agent-lakehouse/raw/planning/chongqing_central_buildings_2021/"
    "bundle-sha256-e2697e8215a26de4b5c2a526eb9bce7401ebc27e1fc64d5f6c30bf85ff149c0d/"
    "physical-sha256-6fd8c873ffce0c0a91089c554b3b0d432527102272260a7363744cb75290bf29/"
    "chongqing-central-buildings-2021.geojson"
)
DEFAULT_WAREHOUSE = "s3a://gis-agent-lakehouse/warehouse/iceberg"
DEFAULT_TABLE = "lakehouse.gis_ods.chongqing_central_buildings_2021"
DEFAULT_SEMANTIC_SHA256 = (
    "e2697e8215a26de4b5c2a526eb9bce7401ebc27e1fc64d5f6c30bf85ff149c0d"
)
DEFAULT_SOURCE_SHA256 = (
    "6fd8c873ffce0c0a91089c554b3b0d432527102272260a7363744cb75290bf29"
)
DEFAULT_SOURCE_RESOURCE_VERSION_ID = "c012afeb-9f1f-59a2-9e86-bb16169743af"
DEFAULT_EXPECTED_BBOX = (
    106.20951745600001,
    29.212573738600042,
    106.821612684,
    29.831229147900103,
)
_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_FINGERPRINT_COLUMNS = (
    "source_fid",
    "source_id",
    "floor_count",
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
    parser.add_argument(
        "--source-resource-version-id",
        default=DEFAULT_SOURCE_RESOURCE_VERSION_ID,
    )
    parser.add_argument("--materialization-run-id", required=True)
    parser.add_argument("--expected-rows", type=int, default=107452)
    parser.add_argument("--expected-null-geometry", type=int, default=417)
    parser.add_argument("--expected-duplicate-geometry", type=int, default=416)
    parser.add_argument("--expected-floor-min", type=int, default=1)
    parser.add_argument("--expected-floor-max", type=int, default=66)
    parser.add_argument(
        "--expected-bbox",
        type=_parse_bbox,
        default=DEFAULT_EXPECTED_BBOX,
        metavar="XMIN,YMIN,XMAX,YMAX",
    )
    parser.add_argument(
        "--endpoint-url",
        default=os.environ.get("AWS_ENDPOINT_URL", "http://minio:9000"),
    )
    parser.add_argument(
        "--access-key-id",
        default=os.environ.get("AWS_ACCESS_KEY_ID", "minio_admin"),
    )
    parser.add_argument(
        "--secret-access-key",
        default=os.environ.get(
            "AWS_SECRET_ACCESS_KEY", "local_dev_minio_secret"
        ),
    )
    parser.add_argument("--report-path", type=Path)
    args = parser.parse_args()

    report = run_smoke(args)
    rendered = json.dumps(report, ensure_ascii=True, indent=2, default=str)
    if args.report_path:
        args.report_path.parent.mkdir(parents=True, exist_ok=True)
        args.report_path.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
    from sedona.spark import SedonaContext

    catalog, namespace, _ = _validated_table(args.table)
    spark = (
        SparkSession.builder.master("local[2]")
        .appName("chongqing-central-buildings-ods-lakehouse")
        .config(
            "spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        )
        .config(
            f"spark.sql.catalog.{catalog}",
            "org.apache.iceberg.spark.SparkCatalog",
        )
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
    try:
        spark.sparkContext.setLogLevel("WARN")
        sedona = SedonaContext.create(spark)
        source = _read_source(spark, F, args.input_uri)
        source.createOrReplaceTempView("chongqing_central_buildings_source")
        transformed = sedona.sql(
            """
            SELECT
              source_fid,
              source_id,
              floor_count,
              ST_AsBinary(geom) AS geometry_wkb,
              4326 AS srid,
              ST_XMin(geom) AS bbox_xmin,
              ST_YMin(geom) AS bbox_ymin,
              ST_XMax(geom) AS bbox_xmax,
              ST_YMax(geom) AS bbox_ymax,
              CASE WHEN geom IS NULL THEN NULL ELSE ST_IsValid(geom) END
                AS geometry_valid
            FROM (
              SELECT
                *,
                CASE WHEN geometry_json IS NULL THEN NULL
                     ELSE ST_GeomFromGeoJSON(geometry_json) END AS geom
              FROM chongqing_central_buildings_source
            ) parsed
            """
        ).cache()
        source_metrics = _quality_metrics(transformed, F)
        checks = _quality_checks(
            source_metrics,
            expected_rows=args.expected_rows,
            expected_null_geometry=args.expected_null_geometry,
            expected_duplicate_geometry=args.expected_duplicate_geometry,
            expected_floor=(args.expected_floor_min, args.expected_floor_max),
            expected_bbox=args.expected_bbox,
        )
        if not all(checks.values()):
            raise RuntimeError(f"building ODS source checks failed: {checks}")

        output = transformed.drop("geometry_valid")
        content_fingerprint = _content_fingerprint(output, F)
        spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {catalog}.{namespace}")
        existed = _table_exists(spark, args.table)
        previous_snapshot_id, previous_history_count = _snapshot_state(
            spark, args.table
        )
        reused = (
            existed
            and _table_property(spark, args.table, "gda.semantic_sha256")
            == args.semantic_sha256
            and _table_property(spark, args.table, "gda.source_sha256")
            == args.source_sha256
            and _table_property(spark, args.table, "gda.content_fingerprint")
            == content_fingerprint
        )
        if not reused:
            writer = (
                output.writeTo(args.table)
                .using("iceberg")
                .tableProperty("format-version", "2")
                .tableProperty("gda.semantic_sha256", args.semantic_sha256)
                .tableProperty("gda.source_sha256", args.source_sha256)
                .tableProperty("gda.content_fingerprint", content_fingerprint)
                .tableProperty(
                    "gda.source_resource_version_id",
                    args.source_resource_version_id,
                )
                .tableProperty("gda.source_uri", args.input_uri)
                .tableProperty("gda.logical_stage", "ods")
                .tableProperty("gda.classification", "restricted")
                .tableProperty("gda.standardization_status", "unmatched_holdout")
                .tableProperty("gda.promotion_eligible", "false")
            )
            if existed:
                writer.createOrReplace()
            else:
                writer.create()

        table = spark.table(args.table).cache()
        table_metrics = _quality_metrics(
            table.withColumn(
                "geometry_valid",
                F.when(F.col("geometry_wkb").isNull(), F.lit(None)).otherwise(
                    F.lit(True)
                ),
            ),
            F,
        )
        table_checks = _quality_checks(
            table_metrics,
            expected_rows=args.expected_rows,
            expected_null_geometry=args.expected_null_geometry,
            expected_duplicate_geometry=args.expected_duplicate_geometry,
            expected_floor=(args.expected_floor_min, args.expected_floor_max),
            expected_bbox=args.expected_bbox,
        )
        table_content_fingerprint = _content_fingerprint(table, F)
        snapshot_id, history_count = _snapshot_state(spark, args.table)
        time_travel_rows = (
            spark.read.option("snapshot-id", str(snapshot_id))
            .table(args.table)
            .count()
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
                "promotion_blocked": (
                    _table_property(spark, args.table, "gda.promotion_eligible")
                    == "false"
                    and _table_property(
                        spark, args.table, "gda.standardization_status"
                    )
                    == "unmatched_holdout"
                ),
            }
        )
        status = "passed" if all(checks.values()) else "failed"
        report = {
            "schema": "gda.chongqing_central_buildings_ods_acceptance.v1",
            "status": status,
            "generated_at": datetime.now(UTC).isoformat(),
            "profile": "default_lakehouse",
            "logical_stage": "ods",
            "classification": "restricted",
            "spark_version": spark.version,
            "sedona_version": version("apache-sedona"),
            "iceberg_format_version": 2,
            "input_uri": args.input_uri,
            "warehouse_uri": args.warehouse_uri,
            "table": args.table,
            "source_resource_version_id": args.source_resource_version_id,
            "materialization_run_id": args.materialization_run_id,
            "semantic_sha256": args.semantic_sha256,
            "source_sha256": args.source_sha256,
            "content_fingerprint": content_fingerprint,
            "table_content_fingerprint": table_content_fingerprint,
            **table_metrics,
            "snapshot_id": snapshot_id,
            "history_count": history_count,
            "previous_snapshot_id": previous_snapshot_id,
            "previous_history_count": previous_history_count,
            "time_travel_rows": time_travel_rows,
            "table_created": not existed,
            "snapshot_reused": reused,
            "checks": checks,
            "release_disposition": {
                "promotion_eligible": False,
                "highest_allowed_stage": "ods",
                "data_product_version_created": False,
                "reasons": [
                    "standard_mapping_unresolved",
                    "source_id_not_unique",
                    "null_geometry_present",
                ],
            },
        }
        if status != "passed":
            raise RuntimeError(f"building ODS acceptance failed: {report}")
        return report
    finally:
        spark.stop()


def _read_source(spark, functions, input_uri: str):
    raw = spark.read.option("multiLine", "true").json(input_uri)
    return raw.select(functions.explode("features").alias("feature")).select(
        functions.col("feature.properties.source_fid")
        .cast("long")
        .alias("source_fid"),
        functions.col("feature.properties.source_id").cast("long").alias("source_id"),
        functions.col("feature.properties.floor_count")
        .cast("int")
        .alias("floor_count"),
        functions.to_json("feature.geometry").alias("geometry_json"),
    )


def _quality_metrics(frame, functions) -> dict[str, Any]:
    row = frame.agg(
        functions.count("*").alias("row_count"),
        functions.countDistinct("source_fid").alias("distinct_source_fids"),
        functions.countDistinct("source_id").alias("distinct_source_ids"),
        functions.sum(functions.col("source_fid").isNull().cast("int")).alias(
            "null_source_fids"
        ),
        functions.sum(functions.col("geometry_wkb").isNull().cast("int")).alias(
            "null_geometry"
        ),
        functions.sum(
            (
                functions.col("geometry_wkb").isNotNull()
                & (functions.col("geometry_valid") == functions.lit(False))
            ).cast("int")
        ).alias("invalid_geometry"),
        functions.min("floor_count").alias("floor_min"),
        functions.max("floor_count").alias("floor_max"),
        functions.min("bbox_xmin").alias("xmin"),
        functions.min("bbox_ymin").alias("ymin"),
        functions.max("bbox_xmax").alias("xmax"),
        functions.max("bbox_ymax").alias("ymax"),
        functions.min("srid").alias("min_srid"),
        functions.max("srid").alias("max_srid"),
    ).first()
    duplicate_geometry = _duplicate_count(frame, functions, include_null=True)
    duplicate_non_null_geometry = _duplicate_count(
        frame, functions, include_null=False
    )
    return {
        "row_count": int(row["row_count"]),
        "distinct_source_fids": int(row["distinct_source_fids"]),
        "distinct_source_ids": int(row["distinct_source_ids"]),
        "null_source_fids": int(row["null_source_fids"] or 0),
        "null_geometry": int(row["null_geometry"] or 0),
        "invalid_geometry": int(row["invalid_geometry"] or 0),
        "duplicate_geometry": duplicate_geometry,
        "duplicate_non_null_geometry": duplicate_non_null_geometry,
        "floor_min": int(row["floor_min"]),
        "floor_max": int(row["floor_max"]),
        "bbox": [float(row[name]) for name in ("xmin", "ymin", "xmax", "ymax")],
        "srids": [int(row["min_srid"]), int(row["max_srid"])],
    }


def _duplicate_count(frame, functions, *, include_null: bool) -> int:
    values = frame if include_null else frame.where(functions.col("geometry_wkb").isNotNull())
    row = (
        values.groupBy("geometry_wkb")
        .count()
        .where(functions.col("count") > 1)
        .select(functions.sum(functions.col("count") - 1).alias("duplicates"))
        .first()
    )
    return int(row["duplicates"] or 0)


def _quality_checks(
    metrics: dict[str, Any],
    *,
    expected_rows: int,
    expected_null_geometry: int,
    expected_duplicate_geometry: int,
    expected_floor: tuple[int, int],
    expected_bbox: tuple[float, float, float, float],
) -> dict[str, bool]:
    return {
        "row_count_preserved": metrics["row_count"] == expected_rows,
        "technical_fid_unique_complete": (
            metrics["distinct_source_fids"] == expected_rows
            and metrics["null_source_fids"] == 0
        ),
        "source_id_defect_recorded": metrics["distinct_source_ids"] == 1,
        "null_geometry_defect_recorded": (
            metrics["null_geometry"] == expected_null_geometry
        ),
        "duplicate_geometry_defect_recorded": (
            metrics["duplicate_geometry"] == expected_duplicate_geometry
            and metrics["duplicate_non_null_geometry"] == 0
        ),
        "non_null_geometry_valid": metrics["invalid_geometry"] == 0,
        "floor_range_preserved": (
            metrics["floor_min"], metrics["floor_max"]
        )
        == expected_floor,
        "srid_is_4326": metrics["srids"] == [4326, 4326],
        "bbox_preserved": all(
            abs(actual - expected) <= 1e-6
            for actual, expected in zip(
                metrics["bbox"], expected_bbox, strict=True
            )
        ),
    }


def _content_fingerprint(frame, functions) -> str:
    row_hashes = (
        frame.select(
            "source_fid",
            functions.sha2(
                functions.to_json(functions.struct(*_FINGERPRINT_COLUMNS)), 256
            ).alias("row_sha256"),
        )
        .orderBy("source_fid")
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


def _validated_table(table: str) -> tuple[str, str, str]:
    parts = tuple(table.split("."))
    if len(parts) != 3 or any(
        not _IDENTIFIER_RE.fullmatch(part) for part in parts
    ):
        raise ValueError("table must be catalog.namespace.table with safe identifiers")
    if parts[1] != "gis_ods":
        raise ValueError("unstandardized building source may only target gis_ods")
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
