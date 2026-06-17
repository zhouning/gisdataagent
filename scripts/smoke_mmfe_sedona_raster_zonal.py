"""Smoke test MMFE vector/raster semantic fusion with Sedona zonal stats.

This validates a hard MMFE path: TWM project polygons are transformed into the
NDVI raster CRS, summarized against a GeoTIFF through Sedona raster SQL, then
written to the local MinIO lakehouse with S3A and read back.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.smoke_mmfe_sedona_twm_geojson import _load_project_rows, _project_schema


DEFAULT_DATA_DIR = Path("data_agent/test_data/twm_bishan_demo")
DEFAULT_RASTER = DEFAULT_DATA_DIR / "real_imagery/sentinel2_l2a_ndvi.tif"
DEFAULT_OUTPUT = (
    "s3a://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/"
    "spark_smoke/sedona_project_ndvi_zonal_stats"
)
DEFAULT_PACKAGES = ",".join(
    [
        "org.apache.sedona:sedona-spark-shaded-3.5_2.12:1.9.0",
        "org.datasyslab:geotools-wrapper:1.9.0-33.5",
        "org.apache.hadoop:hadoop-aws:3.3.4",
        "com.amazonaws:aws-java-sdk-bundle:1.12.262",
    ]
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--projects-file", default="synthetic_projects.geojson")
    parser.add_argument("--raster", type=Path, default=DEFAULT_RASTER)
    parser.add_argument("--raster-product-id", default=None)
    parser.add_argument("--raster-alias-zh", default=None)
    parser.add_argument("--output-uri", default=DEFAULT_OUTPUT)
    parser.add_argument("--endpoint-url", default=os.environ.get("AWS_ENDPOINT_URL", "http://minio:9000"))
    parser.add_argument("--access-key-id", default=os.environ.get("AWS_ACCESS_KEY_ID", "minio_admin"))
    parser.add_argument("--secret-access-key", default=os.environ.get("AWS_SECRET_ACCESS_KEY", "local_dev_minio_secret"))
    parser.add_argument("--packages", default=os.environ.get("SEDONA_RASTER_ZONAL_SPARK_PACKAGES", DEFAULT_PACKAGES))
    parser.add_argument("--source-crs", default="EPSG:4326")
    parser.add_argument("--raster-crs", default="EPSG:32648")
    parser.add_argument("--min-zonal-rows", type=int, default=1)
    parser.add_argument("--min-observed-rows", type=int, default=1)
    args = parser.parse_args()

    summary = run_smoke(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
    from pyspark.sql import types as T
    from sedona.spark import SedonaContext

    project_path = args.data_dir / args.projects_file
    raster_path = _require_file(args.raster)
    project_rows = _load_project_rows(project_path)
    if not project_rows:
        _exit_error("missing project features", {"projects_file": str(project_path)})

    raster_metadata = _find_raster_metadata(args.data_dir, raster_path)
    raster_product_id = args.raster_product_id or _text(raster_metadata.get("product_id")) or raster_path.stem
    raster_alias_zh = (
        args.raster_alias_zh
        or _text(raster_metadata.get("alias_zh"))
        or _default_raster_alias_zh(raster_metadata, raster_path)
    )

    builder = (
        SparkSession.builder.master("local[1]")
        .appName("mmfe-sedona-raster-zonal-smoke")
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
    if args.packages:
        builder = builder.config("spark.jars.packages", args.packages)

    spark = builder.getOrCreate()
    try:
        sedona = SedonaContext.create(spark)
        spark.createDataFrame(project_rows, _project_schema(T)).createOrReplaceTempView("raw_twm_projects")

        # Use the DataFrame reader rather than SQL binaryFile path literals, so
        # shell quoting cannot corrupt paths containing Spark SQL backticks.
        raster_df = (
            spark.read.format("binaryFile")
            .load(str(raster_path))
            .selectExpr("path", "length", "RS_FromGeoTiff(content) AS raster")
        )
        raster_df.createOrReplaceTempView("raw_ndvi_raster")

        source_crs = _sql_string_literal(args.source_crs)
        raster_crs = _sql_string_literal(args.raster_crs)
        product_id_literal = _sql_string_literal(raster_product_id)
        alias_literal = _sql_string_literal(raster_alias_zh)

        sedona.sql(
            f"""
CREATE OR REPLACE TEMP VIEW twm_projects_metric AS
SELECT
  project_id,
  project_name,
  xmdm,
  xmmc,
  risk_scenario,
  review_priority,
  project_area_m2,
  ST_Transform(ST_GeomFromGeoJSON(geometry_json), {source_crs}, {raster_crs}) AS geom_metric
FROM raw_twm_projects
WHERE geometry_json IS NOT NULL
"""
        )

        sedona.sql(
            f"""
CREATE OR REPLACE TEMP VIEW ndvi_raster AS
SELECT
  {product_id_literal} AS raster_product_id,
  {alias_literal} AS raster_alias_zh,
  path AS raster_path,
  length AS raster_bytes,
  raster,
  RS_SRID(raster) AS raster_srid,
  RS_Width(raster) AS raster_width,
  RS_Height(raster) AS raster_height,
  RS_NumBands(raster) AS raster_bands,
  RS_Envelope(raster) AS raster_extent,
  RS_SummaryStatsAll(raster, 1, true) AS raster_stats
FROM raw_ndvi_raster
"""
        )

        result = sedona.sql(
            f"""
SELECT
  relation_id,
  relation_type,
  project_id,
  project_name,
  xmdm,
  xmmc,
  risk_scenario,
  review_priority,
  project_area_m2,
  raster_product_id,
  raster_alias_zh,
  raster_path,
  raster_srid,
  raster_width,
  raster_height,
  raster_bands,
  project_area_metric_m2,
  raster_overlap_area_m2,
  z.count AS ndvi_valid_pixel_count,
  z.sum AS ndvi_sum,
  z.mean AS ndvi_mean,
  z.median AS ndvi_median,
  z.mode AS ndvi_mode,
  z.stddev AS ndvi_stddev,
  z.variance AS ndvi_variance,
  z.min AS ndvi_min,
  z.max AS ndvi_max,
  CASE
    WHEN z.count <= 0 THEN '无有效像元'
    WHEN z.mean >= 0.75 THEN '高植被覆盖'
    WHEN z.mean >= 0.50 THEN '中高植被覆盖'
    WHEN z.mean >= 0.30 THEN '中低植被覆盖'
    ELSE '低植被覆盖'
  END AS ndvi_semantic_class_zh,
  CASE WHEN z.count > 0 THEN 'observed' ELSE 'no_valid_pixels' END AS observation_status,
  'territorial_project' AS left_role,
  'remote_sensing_ndvi_observation' AS right_role,
  'project_ndvi_zonal_stats' AS semantic_metric,
  {source_crs} AS source_crs,
  {raster_crs} AS raster_crs,
  'apache_sedona_raster_zonal_stats' AS computed_by
FROM (
  SELECT
    concat('PROJECT_NDVI_ZONAL-', p.project_id, '-', r.raster_product_id) AS relation_id,
    'PROJECT_OBSERVED_BY_RASTER_ZONAL_STATS' AS relation_type,
    p.project_id,
    p.project_name,
    p.xmdm,
    p.xmmc,
    p.risk_scenario,
    p.review_priority,
    p.project_area_m2,
    r.raster_product_id,
    r.raster_alias_zh,
    r.raster_path,
    r.raster_srid,
    r.raster_width,
    r.raster_height,
    r.raster_bands,
    ST_Area(p.geom_metric) AS project_area_metric_m2,
    ST_Area(ST_Intersection(p.geom_metric, r.raster_extent)) AS raster_overlap_area_m2,
    RS_ZonalStatsAll(r.raster, p.geom_metric, 1, true, true, true) AS z
  FROM twm_projects_metric p
  CROSS JOIN ndvi_raster r
  WHERE ST_Intersects(p.geom_metric, r.raster_extent)
) zonal
"""
        )

        result = (
            result.withColumn(
                "raster_coverage_ratio",
                F.when(F.col("project_area_metric_m2") > 0, F.col("raster_overlap_area_m2") / F.col("project_area_metric_m2")),
            )
            .orderBy(F.col("ndvi_valid_pixel_count").desc(), F.col("ndvi_mean").desc_nulls_last(), F.col("project_id"))
        )

        zonal_rows = result.count()
        if zonal_rows < args.min_zonal_rows:
            _exit_error(
                "Sedona project/NDVI zonal stats produced too few rows",
                {"actual": zonal_rows, "min_zonal_rows": args.min_zonal_rows},
            )

        observed_rows = result.where(F.col("ndvi_valid_pixel_count") > 0).count()
        if observed_rows < args.min_observed_rows:
            _exit_error(
                "Sedona project/NDVI zonal stats produced too few observed rows",
                {"actual": observed_rows, "min_observed_rows": args.min_observed_rows},
            )

        result.coalesce(1).write.mode("overwrite").option("header", "true").csv(args.output_uri)
        written = spark.read.option("header", "true").csv(args.output_uri)
        output_rows = written.count()
        if output_rows != zonal_rows:
            _exit_error(
                "S3A read-back row count does not match Sedona zonal result",
                {"computed_rows": zonal_rows, "output_rows": output_rows, "output_uri": args.output_uri},
            )

        raster_summary = sedona.sql(
            """
SELECT
  raster_product_id,
  raster_alias_zh,
  raster_path,
  raster_srid,
  raster_width,
  raster_height,
  raster_bands,
  raster_stats.count AS raster_valid_pixel_count,
  raster_stats.mean AS raster_mean,
  raster_stats.min AS raster_min,
  raster_stats.max AS raster_max
FROM ndvi_raster
"""
        ).collect()[0].asDict(recursive=True)

        aggregate = result.agg(
            F.sum("ndvi_valid_pixel_count").alias("total_project_valid_pixels"),
            F.avg("ndvi_mean").alias("avg_project_ndvi_mean"),
            F.max("ndvi_mean").alias("max_project_ndvi_mean"),
            F.min("ndvi_mean").alias("min_project_ndvi_mean"),
        ).collect()[0].asDict()

        sample_rows = [row.asDict() for row in written.limit(5).collect()]
        return {
            "status": "ok",
            "spark_version": spark.version,
            "projects_file": str(project_path),
            "project_rows": len(project_rows),
            "raster_file": str(raster_path),
            "raster_metadata_found": bool(raster_metadata),
            "raster_summary": raster_summary,
            "zonal_rows": zonal_rows,
            "observed_rows": observed_rows,
            "aggregate": aggregate,
            "output_uri": args.output_uri,
            "output_rows": output_rows,
            "sample_rows": sample_rows,
            "source_crs": args.source_crs,
            "raster_crs": args.raster_crs,
            "packages": args.packages,
        }
    finally:
        spark.stop()


def _find_raster_metadata(data_dir: Path, raster_path: Path) -> dict[str, Any]:
    candidates = [
        data_dir / "real_imagery_manifest.json",
        data_dir / "raster_manifest.json",
    ]
    normalized_targets = _path_match_values(raster_path)
    for manifest_path in candidates:
        if not manifest_path.exists():
            continue
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
        products = manifest.get("products") or {}
        if not isinstance(products, dict):
            continue
        for product in products.values():
            if not isinstance(product, dict):
                continue
            product_paths = {
                _normalize_path_text(product.get("path")),
                _normalize_path_text(product.get("relative_path")),
                _normalize_path_text(str(data_dir / str(product.get("relative_path"))))
                if product.get("relative_path")
                else None,
            }
            if normalized_targets.intersection(value for value in product_paths if value):
                return dict(product)
    return {}


def _path_match_values(path: Path) -> set[str]:
    values = {_normalize_path_text(str(path)), _normalize_path_text(path.as_posix())}
    try:
        values.add(_normalize_path_text(str(path.resolve())))
    except OSError:
        pass
    return {value for value in values if value}


def _normalize_path_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).replace("\\", "/").lstrip("./")


def _default_raster_alias_zh(metadata: dict[str, Any], raster_path: Path) -> str:
    product_type = metadata.get("type")
    if product_type == "spectral_index" and "ndvi" in raster_path.name.lower():
        return "Sentinel-2 L2A NDVI观测栅格"
    if "ndvi" in raster_path.name.lower():
        return "NDVI观测栅格"
    return raster_path.stem


def _require_file(path: Path) -> Path:
    if not path.exists():
        _exit_error("raster file does not exist", {"path": str(path)})
    return path


def _text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _sql_string_literal(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''").replace("\n", " ") + "'"


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
