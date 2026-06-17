"""Smoke test MMFE raster product materialization with Sedona clipping.

This validates the next hard MMFE raster path after zonal stats: TWM project
polygons clip a real NDVI GeoTIFF through Sedona, clipped GeoTIFF bytes are
materialized to the local MinIO lakehouse through Hadoop S3A, and the outputs
are read back as rasters.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.smoke_mmfe_sedona_raster_zonal import (  # noqa: E402
    _default_raster_alias_zh,
    _find_raster_metadata,
    _sql_string_literal,
    _text,
)
from scripts.smoke_mmfe_sedona_twm_geojson import _load_project_rows, _project_schema  # noqa: E402


DEFAULT_DATA_DIR = Path("data_agent/test_data/twm_bishan_demo")
DEFAULT_RASTER = DEFAULT_DATA_DIR / "real_imagery/sentinel2_l2a_ndvi.tif"
DEFAULT_OUTPUT = (
    "s3a://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/"
    "spark_smoke/sedona_project_ndvi_clips"
)
DEFAULT_LOCAL_STAGE = Path(".tmp/mmfe-sedona-raster-clips")
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
    parser.add_argument("--local-stage-dir", type=Path, default=DEFAULT_LOCAL_STAGE)
    parser.add_argument("--endpoint-url", default=os.environ.get("AWS_ENDPOINT_URL", "http://minio:9000"))
    parser.add_argument("--access-key-id", default=os.environ.get("AWS_ACCESS_KEY_ID", "minio_admin"))
    parser.add_argument("--secret-access-key", default=os.environ.get("AWS_SECRET_ACCESS_KEY", "local_dev_minio_secret"))
    parser.add_argument("--packages", default=os.environ.get("SEDONA_RASTER_CLIP_SPARK_PACKAGES", DEFAULT_PACKAGES))
    parser.add_argument("--source-crs", default="EPSG:4326")
    parser.add_argument("--raster-crs", default="EPSG:32648")
    parser.add_argument("--max-clips", type=int, default=3)
    parser.add_argument("--min-valid-pixels", type=int, default=1)
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
    if args.max_clips < 1:
        _exit_error("max_clips must be positive", {"max_clips": args.max_clips})

    raster_metadata = _find_raster_metadata(args.data_dir, raster_path)
    raster_product_id = args.raster_product_id or _text(raster_metadata.get("product_id")) or raster_path.stem
    raster_alias_zh = (
        args.raster_alias_zh
        or _text(raster_metadata.get("alias_zh"))
        or _default_raster_alias_zh(raster_metadata, raster_path)
    )

    builder = (
        SparkSession.builder.master("local[1]")
        .appName("mmfe-sedona-raster-clip-smoke")
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
    keep_spark = bool(getattr(args, "keep_spark", False))
    try:
        sedona = SedonaContext.create(spark)
        spark.createDataFrame(project_rows, _project_schema(T)).createOrReplaceTempView("raw_twm_projects")
        spark.read.format("binaryFile").load(str(raster_path)).selectExpr(
            "path",
            "length",
            "RS_FromGeoTiff(content) AS raster",
        ).createOrReplaceTempView("raw_ndvi_raster")

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
  RS_Envelope(raster) AS raster_extent
FROM raw_ndvi_raster
"""
        )

        clips = sedona.sql(
            f"""
SELECT
  relation_id,
  project_id,
  project_name,
  xmdm,
  xmmc,
  risk_scenario,
  review_priority,
  project_area_m2,
  raster_product_id,
  raster_alias_zh,
  raster_srid,
  clipped_width,
  clipped_height,
  clipped_stats.count AS ndvi_valid_pixel_count,
  clipped_stats.mean AS ndvi_mean,
  clipped_stats.min AS ndvi_min,
  clipped_stats.max AS ndvi_max,
  geotiff_bytes,
  length(geotiff_bytes) AS geotiff_size_bytes,
  'PROJECT_NDVI_CLIPPED_GEOTIFF' AS relation_type,
  'territorial_project' AS left_role,
  'remote_sensing_ndvi_observation' AS right_role,
  'project_ndvi_clipped_geotiff' AS semantic_metric,
  {source_crs} AS source_crs,
  {raster_crs} AS raster_crs,
  'apache_sedona_rs_clip_as_geotiff' AS computed_by
  FROM (
    SELECT
    concat('PROJECT_NDVI_CLIP-', project_id, '-', raster_product_id) AS relation_id,
    project_id,
    project_name,
    xmdm,
    xmmc,
    risk_scenario,
    review_priority,
    project_area_m2,
    raster_product_id,
    raster_alias_zh,
    raster_srid,
    RS_Width(clipped_raster) AS clipped_width,
    RS_Height(clipped_raster) AS clipped_height,
    RS_SummaryStatsAll(clipped_raster, 1, true) AS clipped_stats,
    RS_AsGeoTiff(clipped_raster) AS geotiff_bytes
  FROM (
    SELECT
      p.*,
      r.raster_product_id,
      r.raster_alias_zh,
      r.raster_srid,
      RS_Clip(r.raster, 1, p.geom_metric) AS clipped_raster
    FROM twm_projects_metric p
    CROSS JOIN ndvi_raster r
    WHERE ST_Intersects(p.geom_metric, r.raster_extent)
  ) clipped
) materialized
WHERE clipped_stats.count >= {int(args.min_valid_pixels)}
ORDER BY clipped_stats.count DESC, clipped_stats.mean DESC, project_id
LIMIT {int(args.max_clips)}
"""
        )

        clip_rows = [row.asDict(recursive=True) for row in clips.collect()]
        if not clip_rows:
            _exit_error(
                "Sedona project/NDVI clipping produced no materializable GeoTIFFs",
                {"max_clips": args.max_clips, "min_valid_pixels": args.min_valid_pixels},
            )

        args.local_stage_dir.mkdir(parents=True, exist_ok=True)
        artifact_rows: list[dict[str, Any]] = []
        for row in clip_rows:
            geotiff_bytes = bytes(row.pop("geotiff_bytes"))
            if not _looks_like_tiff(geotiff_bytes):
                _exit_error(
                    "RS_AsGeoTiff produced bytes without a TIFF signature",
                    {"project_id": row.get("project_id"), "geotiff_size_bytes": len(geotiff_bytes)},
                )
            filename = f"{_safe_slug(str(row['project_id']))}_{_safe_slug(str(row['raster_product_id']))}_ndvi_clip.tif"
            local_path = args.local_stage_dir / filename
            local_path.write_bytes(geotiff_bytes)
            target_uri = _join_uri(args.output_uri, "geotiff", filename)
            _copy_local_file_to_hadoop_uri(spark, local_path, target_uri)
            artifact_rows.append(
                {
                    **row,
                    "artifact_uri": target_uri,
                    "artifact_href": _s3a_to_s3_uri(target_uri),
                    "local_stage_path": str(local_path),
                    "content_type": "image/tiff; application=geotiff",
                    "geotiff_size_bytes": len(geotiff_bytes),
                    "not_for_production": True,
                }
            )

        manifest = spark.createDataFrame(artifact_rows, _artifact_schema(T))
        manifest_uri = _join_uri(args.output_uri, "manifest")
        manifest.coalesce(1).write.mode("overwrite").option("header", "true").csv(manifest_uri)
        manifest_readback = spark.read.option("header", "true").csv(manifest_uri)
        manifest_rows = manifest_readback.count()
        if manifest_rows != len(artifact_rows):
            _exit_error(
                "S3A manifest read-back row count does not match clipped artifacts",
                {"manifest_rows": manifest_rows, "artifact_rows": len(artifact_rows), "manifest_uri": manifest_uri},
            )

        readback_rows = []
        for artifact in artifact_rows:
            readback = (
                spark.read.format("binaryFile")
                .load(str(artifact["artifact_uri"]))
                .selectExpr(
                    "path",
                    "length",
                    "RS_FromGeoTiff(content) AS raster",
                )
            )
            readback.createOrReplaceTempView("clip_readback")
            summary = sedona.sql(
                """
SELECT
  path,
  length,
  RS_Width(raster) AS width,
  RS_Height(raster) AS height,
  RS_SRID(raster) AS srid,
  RS_SummaryStatsAll(raster, 1, true) AS stats
FROM clip_readback
"""
            ).collect()[0].asDict(recursive=True)
            readback_rows.append(summary)

        if len(readback_rows) != len(artifact_rows):
            _exit_error(
                "S3A GeoTIFF read-back count does not match clipped artifacts",
                {"readback_rows": len(readback_rows), "artifact_rows": len(artifact_rows)},
            )

        summary = {
            "status": "ok",
            "spark_version": spark.version,
            "projects_file": str(project_path),
            "project_rows": len(project_rows),
            "raster_file": str(raster_path),
            "raster_metadata_found": bool(raster_metadata),
            "raster_product_id": raster_product_id,
            "raster_alias_zh": raster_alias_zh,
            "clip_rows": len(artifact_rows),
            "output_uri": args.output_uri,
            "manifest_uri": manifest_uri,
            "manifest_rows": manifest_rows,
            "artifacts": artifact_rows,
            "readback_rows": readback_rows,
            "source_crs": args.source_crs,
            "raster_crs": args.raster_crs,
            "packages": args.packages,
        }
        if keep_spark:
            summary["_spark"] = spark
            summary["_sedona"] = sedona
        return summary
    finally:
        if not keep_spark:
            spark.stop()


def _artifact_schema(types: Any) -> Any:
    return types.StructType(
        [
            types.StructField("relation_id", types.StringType(), False),
            types.StructField("project_id", types.StringType(), False),
            types.StructField("project_name", types.StringType(), True),
            types.StructField("xmdm", types.StringType(), True),
            types.StructField("xmmc", types.StringType(), True),
            types.StructField("risk_scenario", types.StringType(), True),
            types.StructField("review_priority", types.StringType(), True),
            types.StructField("project_area_m2", types.DoubleType(), True),
            types.StructField("raster_product_id", types.StringType(), False),
            types.StructField("raster_alias_zh", types.StringType(), True),
            types.StructField("raster_srid", types.IntegerType(), True),
            types.StructField("clipped_width", types.IntegerType(), True),
            types.StructField("clipped_height", types.IntegerType(), True),
            types.StructField("ndvi_valid_pixel_count", types.DoubleType(), True),
            types.StructField("ndvi_mean", types.DoubleType(), True),
            types.StructField("ndvi_min", types.DoubleType(), True),
            types.StructField("ndvi_max", types.DoubleType(), True),
            types.StructField("geotiff_size_bytes", types.IntegerType(), True),
            types.StructField("relation_type", types.StringType(), False),
            types.StructField("left_role", types.StringType(), False),
            types.StructField("right_role", types.StringType(), False),
            types.StructField("semantic_metric", types.StringType(), False),
            types.StructField("source_crs", types.StringType(), False),
            types.StructField("raster_crs", types.StringType(), False),
            types.StructField("computed_by", types.StringType(), False),
            types.StructField("artifact_uri", types.StringType(), False),
            types.StructField("artifact_href", types.StringType(), False),
            types.StructField("local_stage_path", types.StringType(), False),
            types.StructField("content_type", types.StringType(), False),
            types.StructField("not_for_production", types.BooleanType(), False),
        ]
    )


def _copy_local_file_to_hadoop_uri(spark: Any, local_path: Path, target_uri: str) -> None:
    jvm = spark.sparkContext._jvm
    conf = spark.sparkContext._jsc.hadoopConfiguration()
    target = jvm.org.apache.hadoop.fs.Path(target_uri)
    fs = target.getFileSystem(conf)
    parent = target.getParent()
    if parent is not None:
        fs.mkdirs(parent)
    stream = fs.create(target, True)
    try:
        stream.write(bytearray(local_path.read_bytes()))
    finally:
        stream.close()


def _join_uri(base_uri: str, *parts: str) -> str:
    base = base_uri.rstrip("/")
    clean_parts = [str(part).strip("/") for part in parts if str(part).strip("/")]
    if not clean_parts:
        return base
    return "/".join([base, *clean_parts])


def _s3a_to_s3_uri(uri: str) -> str:
    if uri.startswith("s3a://"):
        return "s3://" + uri[6:]
    return uri


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    slug = slug.strip("-._")
    return slug or "item"


def _looks_like_tiff(content: bytes) -> bool:
    return content.startswith(b"II*\x00") or content.startswith(b"MM\x00*")


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
