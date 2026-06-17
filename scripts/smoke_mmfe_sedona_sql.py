"""Smoke test Apache Sedona SQL in the local PySpark runtime."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


DEFAULT_PACKAGES = "org.apache.sedona:sedona-spark-shaded-3.5_2.12:1.9.0"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages", default=os.environ.get("SEDONA_SPARK_PACKAGES", DEFAULT_PACKAGES))
    args = parser.parse_args()

    summary = run_smoke(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    from pyspark.sql import SparkSession
    from sedona.spark import SedonaContext

    builder = (
        SparkSession.builder.master("local[1]")
        .appName("mmfe-sedona-sql-smoke")
        .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer")
        .config("spark.kryo.registrator", "org.apache.sedona.core.serde.SedonaKryoRegistrator")
    )
    if args.packages:
        builder = builder.config("spark.jars.packages", args.packages)

    spark = builder.getOrCreate()
    try:
        sedona = SedonaContext.create(spark)
        row = sedona.sql(
            """
SELECT
  ST_Distance(ST_Point(0.0, 0.0), ST_Point(3.0, 4.0)) AS distance,
  ST_Contains(
    ST_PolygonFromEnvelope(0.0, 0.0, 10.0, 10.0),
    ST_Point(3.0, 4.0)
  ) AS contains_point
"""
        ).collect()[0]
        distance = float(row["distance"])
        contains_point = bool(row["contains_point"])
        if abs(distance - 5.0) > 1e-9 or not contains_point:
            _exit_error(
                "unexpected Sedona SQL result",
                {"distance": distance, "contains_point": contains_point},
            )
        return {
            "status": "ok",
            "spark_version": spark.version,
            "distance": distance,
            "contains_point": contains_point,
            "packages": args.packages,
            "raster_note": "GeoTools is not required for this vector SQL smoke; raster operations need extra jars.",
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
