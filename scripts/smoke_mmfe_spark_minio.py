"""Smoke test Spark S3A read/write against the local MMFE MinIO lakehouse."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


DEFAULT_INPUT = (
    "s3a://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/"
    "twm_mmfe_business_view.csv"
)
DEFAULT_OUTPUT = (
    "s3a://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/"
    "spark_smoke/business_summary"
)
DEFAULT_PACKAGES = "org.apache.hadoop:hadoop-aws:3.3.4,com.amazonaws:aws-java-sdk-bundle:1.12.262"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-uri", default=DEFAULT_INPUT)
    parser.add_argument("--output-uri", default=DEFAULT_OUTPUT)
    parser.add_argument("--endpoint-url", default=os.environ.get("AWS_ENDPOINT_URL", "http://minio:9000"))
    parser.add_argument("--access-key-id", default=os.environ.get("AWS_ACCESS_KEY_ID", "minio_admin"))
    parser.add_argument("--secret-access-key", default=os.environ.get("AWS_SECRET_ACCESS_KEY", "local_dev_minio_secret"))
    parser.add_argument("--packages", default=os.environ.get("SPARK_JARS_PACKAGES", DEFAULT_PACKAGES))
    args = parser.parse_args()

    summary = run_smoke(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F

    builder = (
        SparkSession.builder.master("local[1]")
        .appName("mmfe-spark-minio-smoke")
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
        row_count = df.count()
        if row_count <= 0:
            _exit_error("input produced no rows", {"input_uri": args.input_uri})
        summary = df.select(
            F.first("product_id", ignorenulls=True).alias("product_id"),
            F.first("dataset_id", ignorenulls=True).alias("dataset_id"),
            F.first("layer_count", ignorenulls=True).alias("layer_count"),
            F.first("rule_eval_count", ignorenulls=True).alias("rule_eval_count"),
            F.lit(row_count).alias("spark_input_rows"),
        )
        summary.coalesce(1).write.mode("overwrite").option("header", "true").csv(args.output_uri)
        written = spark.read.option("header", "true").csv(args.output_uri)
        output_rows = written.count()
        out = written.collect()[0].asDict() if output_rows else {}
        return {
            "status": "ok",
            "spark_version": spark.version,
            "input_uri": args.input_uri,
            "output_uri": args.output_uri,
            "input_rows": row_count,
            "input_columns": df.columns,
            "output_rows": output_rows,
            "output_product_id": out.get("product_id"),
            "output_dataset_id": out.get("dataset_id"),
            "packages": args.packages,
        }
    finally:
        spark.stop()


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
