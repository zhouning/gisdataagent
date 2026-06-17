"""Smoke test Spark Iceberg table commits against the local MinIO lakehouse."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


DEFAULT_INPUT = (
    "s3a://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/"
    "twm_mmfe_business_view.csv"
)
DEFAULT_WAREHOUSE = "s3a://gis-agent-lakehouse/warehouse/iceberg"
DEFAULT_TABLE = "mmfe.gis_fusion.semantic_products_smoke"
DEFAULT_PACKAGES = ",".join(
    [
        "org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.6.1",
        "org.apache.hadoop:hadoop-aws:3.3.4",
        "com.amazonaws:aws-java-sdk-bundle:1.12.262",
    ]
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-uri", default=DEFAULT_INPUT)
    parser.add_argument("--warehouse-uri", default=os.environ.get("MMFE_ICEBERG_WAREHOUSE_URI", DEFAULT_WAREHOUSE))
    parser.add_argument("--table", default=os.environ.get("MMFE_ICEBERG_SMOKE_TABLE", DEFAULT_TABLE))
    parser.add_argument("--endpoint-url", default=os.environ.get("AWS_ENDPOINT_URL", "http://minio:9000"))
    parser.add_argument("--access-key-id", default=os.environ.get("AWS_ACCESS_KEY_ID", "minio_admin"))
    parser.add_argument("--secret-access-key", default=os.environ.get("AWS_SECRET_ACCESS_KEY", "local_dev_minio_secret"))
    parser.add_argument("--packages", default=os.environ.get("ICEBERG_SPARK_PACKAGES", DEFAULT_PACKAGES))
    args = parser.parse_args()

    summary = run_smoke(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F

    builder = (
        SparkSession.builder.master("local[1]")
        .appName("mmfe-iceberg-minio-smoke")
        .config("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
        .config("spark.sql.catalog.mmfe", "org.apache.iceberg.spark.SparkCatalog")
        .config("spark.sql.catalog.mmfe.type", "hadoop")
        .config("spark.sql.catalog.mmfe.warehouse", args.warehouse_uri)
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
    if args.packages:
        builder = builder.config("spark.jars.packages", args.packages)

    spark = builder.getOrCreate()
    try:
        df = spark.read.option("header", "true").csv(args.input_uri)
        if df.count() <= 0:
            _exit_error("input produced no rows", {"input_uri": args.input_uri})
        out = df.select(
            "product_id",
            "dataset_id",
            "layer_count",
            "rule_eval_count",
        ).withColumn("ingested_by", F.lit("spark_iceberg_smoke"))

        _ensure_namespace(spark, args.table)
        out.writeTo(args.table).using("iceberg").createOrReplace()
        rows = spark.table(args.table).collect()
        history = spark.sql(f"SELECT * FROM {args.table}.history").collect()
        if not rows or not history:
            _exit_error("Iceberg table read-back or history is empty", {"table": args.table})
        first = rows[0].asDict()
        snapshot = history[-1].asDict()
        return {
            "status": "ok",
            "spark_version": spark.version,
            "input_uri": args.input_uri,
            "warehouse_uri": args.warehouse_uri,
            "table": args.table,
            "row_count": len(rows),
            "product_id": first.get("product_id"),
            "dataset_id": first.get("dataset_id"),
            "snapshot_id": snapshot.get("snapshot_id"),
            "history_count": len(history),
            "packages": args.packages,
        }
    finally:
        spark.stop()


def _ensure_namespace(spark, table: str) -> None:
    parts = table.split(".")
    if len(parts) < 3:
        return
    catalog = parts[0]
    namespace = ".".join(parts[1:-1])
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {catalog}.{namespace}")


def _exit_error(message: str, payload: dict[str, Any]) -> None:
    print(
        json.dumps(
            {"status": "error", "message": message, "details": payload},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        file=sys.stderr,
    )
    raise SystemExit(1)


if __name__ == "__main__":
    main()
