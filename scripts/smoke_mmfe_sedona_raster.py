"""Smoke test Apache Sedona raster SQL with the local TWM GeoTIFF fixtures."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


DEFAULT_SYNTHETIC_RASTER = Path("data_agent/test_data/twm_bishan_demo/rasters/synthetic_ndvi_2026.tif")
DEFAULT_REAL_RASTER = Path("data_agent/test_data/twm_bishan_demo/real_imagery/sentinel2_l2a_ndvi.tif")
DEFAULT_PACKAGES = ",".join(
    [
        "org.apache.sedona:sedona-spark-shaded-3.5_2.12:1.9.0",
        "org.datasyslab:geotools-wrapper:1.9.0-33.5",
    ]
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-raster", type=Path, default=DEFAULT_SYNTHETIC_RASTER)
    parser.add_argument("--real-raster", type=Path, default=DEFAULT_REAL_RASTER)
    parser.add_argument("--packages", default=os.environ.get("SEDONA_RASTER_SPARK_PACKAGES", DEFAULT_PACKAGES))
    args = parser.parse_args()

    summary = run_smoke(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    from pyspark.sql import SparkSession
    from sedona.spark import SedonaContext

    synthetic_path = _require_file(args.synthetic_raster)
    real_path = _require_file(args.real_raster)

    builder = (
        SparkSession.builder.master("local[1]")
        .appName("mmfe-sedona-raster-smoke")
        .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer")
        .config("spark.kryo.registrator", "org.apache.sedona.core.serde.SedonaKryoRegistrator")
    )
    if args.packages:
        builder = builder.config("spark.jars.packages", args.packages)

    spark = builder.getOrCreate()
    try:
        sedona = SedonaContext.create(spark)
        constructed = sedona.sql(
            """
SELECT
  RS_Width(r) AS width,
  RS_Height(r) AS height,
  RS_NumBands(r) AS bands,
  RS_Count(r, 1, true) AS pixel_count,
  RS_SummaryStatsAll(r, 1, true) AS stats,
  RS_AsMatrix(RS_MakeEmptyRaster(1, 2, 2, 0.0D, 0.0D, 1.0D), 1) AS matrix
FROM (
  SELECT RS_MakeEmptyRaster(1, 10, 20, 0.0D, 0.0D, 1.0D) AS r
)
"""
        ).collect()[0].asDict(recursive=True)
        if constructed["width"] != 10 or constructed["height"] != 20 or constructed["bands"] != 1:
            _exit_error("unexpected constructed raster metadata", constructed)
        if constructed["pixel_count"] != 200:
            _exit_error("unexpected constructed raster pixel count", constructed)

        synthetic = _read_geotiff_summary(sedona, synthetic_path)
        real = _read_geotiff_summary(sedona, real_path)
        if synthetic["width"] <= 0 or synthetic["height"] <= 0 or synthetic["bands"] <= 0:
            _exit_error("synthetic GeoTIFF summary is invalid", synthetic)
        if real["width"] <= 0 or real["height"] <= 0 or real["bands"] <= 0:
            _exit_error("real GeoTIFF summary is invalid", real)

        return {
            "status": "ok",
            "spark_version": spark.version,
            "constructed_raster": constructed,
            "synthetic_geotiff": synthetic,
            "real_geotiff": real,
            "packages": args.packages,
            "geotools_wrapper": "org.datasyslab:geotools-wrapper:1.9.0-33.5",
        }
    finally:
        spark.stop()


def _read_geotiff_summary(sedona: Any, path: Path) -> dict[str, Any]:
    safe_path = str(path).replace("`", "\\`")
    row = sedona.sql(
        f"""
SELECT
  path,
  length,
  RS_Width(r) AS width,
  RS_Height(r) AS height,
  RS_NumBands(r) AS bands,
  RS_Metadata(r) AS metadata,
  RS_SRID(r) AS srid
FROM (
  SELECT path, length, RS_FromGeoTiff(content) AS r
  FROM binaryFile.`{safe_path}`
)
"""
    ).collect()[0]
    return row.asDict(recursive=True)


def _require_file(path: Path) -> Path:
    if not path.exists():
        _exit_error("raster file does not exist", {"path": str(path)})
    return path


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
