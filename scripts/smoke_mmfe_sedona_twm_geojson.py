"""Smoke test Apache Sedona spatial SQL over real TWM GeoJSON layers.

This validates the hard path from TWM vector GeoJSON inputs to Spark/Sedona
spatial joins and back to the local MinIO lakehouse through S3A.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


DEFAULT_DATA_DIR = Path("data_agent/test_data/twm_bishan_demo")
DEFAULT_OUTPUT = (
    "s3a://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/"
    "spark_smoke/sedona_project_pbf_intersections"
)
DEFAULT_PACKAGES = ",".join(
    [
        "org.apache.sedona:sedona-spark-shaded-3.5_2.12:1.9.0",
        "org.apache.hadoop:hadoop-aws:3.3.4",
        "com.amazonaws:aws-java-sdk-bundle:1.12.262",
    ]
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--projects-file", default="synthetic_projects.geojson")
    parser.add_argument("--pbf-file", default="synthetic_pbf.geojson")
    parser.add_argument("--reference-rel-csv", default="relations/project_pbf_rel.csv")
    parser.add_argument("--output-uri", default=DEFAULT_OUTPUT)
    parser.add_argument("--endpoint-url", default=os.environ.get("AWS_ENDPOINT_URL", "http://minio:9000"))
    parser.add_argument("--access-key-id", default=os.environ.get("AWS_ACCESS_KEY_ID", "minio_admin"))
    parser.add_argument("--secret-access-key", default=os.environ.get("AWS_SECRET_ACCESS_KEY", "local_dev_minio_secret"))
    parser.add_argument("--packages", default=os.environ.get("SEDONA_TWM_SPARK_PACKAGES", DEFAULT_PACKAGES))
    parser.add_argument("--source-crs", default="EPSG:4326")
    parser.add_argument("--projected-crs", default="EPSG:32648")
    parser.add_argument("--min-intersections", type=int, default=1)
    args = parser.parse_args()

    summary = run_smoke(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
    from pyspark.sql import types as T
    from sedona.spark import SedonaContext

    project_path = args.data_dir / args.projects_file
    pbf_path = args.data_dir / args.pbf_file
    reference_path = args.data_dir / args.reference_rel_csv

    project_rows = _load_project_rows(project_path)
    pbf_rows = _load_pbf_rows(pbf_path)
    if not project_rows or not pbf_rows:
        _exit_error(
            "missing input features",
            {
                "projects_file": str(project_path),
                "project_rows": len(project_rows),
                "pbf_file": str(pbf_path),
                "pbf_rows": len(pbf_rows),
            },
        )

    builder = (
        SparkSession.builder.master("local[1]")
        .appName("mmfe-sedona-twm-geojson-smoke")
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
        spark.createDataFrame(pbf_rows, _pbf_schema(T)).createOrReplaceTempView("raw_twm_pbf")

        projects = sedona.sql(
            """
SELECT
  project_id,
  project_name,
  xmdm,
  xmmc,
  risk_scenario,
  review_priority,
  project_area_m2,
  ST_GeomFromGeoJSON(geometry_json) AS geom
FROM raw_twm_projects
WHERE geometry_json IS NOT NULL
"""
        )
        projects.createOrReplaceTempView("twm_projects")

        pbf = sedona.sql(
            """
SELECT
  control_id,
  control_name,
  yjjbnttbbh,
  dlmc,
  wdgd,
  pbf_area_m2,
  ST_GeomFromGeoJSON(geometry_json) AS geom
FROM raw_twm_pbf
WHERE geometry_json IS NOT NULL
"""
        )
        pbf.createOrReplaceTempView("twm_pbf")

        pairs = sedona.sql(
            """
SELECT
  concat('SEDONA_PROJECT_PBF-', p.project_id, '-', c.control_id) AS relation_id,
  'PROJECT_OVERLAPS_PBF' AS relation_type,
  p.project_id,
  p.project_name,
  p.xmdm,
  p.xmmc,
  p.risk_scenario,
  p.review_priority,
  p.project_area_m2,
  c.control_id,
  c.control_name,
  c.yjjbnttbbh,
  c.dlmc AS pbf_dlmc,
  c.wdgd,
  c.pbf_area_m2,
  ST_Intersection(p.geom, c.geom) AS overlap_geom
FROM twm_projects p
JOIN twm_pbf c
  ON ST_Intersects(p.geom, c.geom)
"""
        )
        pairs.createOrReplaceTempView("twm_project_pbf_pairs")

        metric_mode = "projected_m2"
        try:
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
  control_id,
  control_name,
  yjjbnttbbh,
  pbf_dlmc,
  wdgd,
  pbf_area_m2,
  ST_Area(ST_Transform(overlap_geom, '{args.source_crs}', '{args.projected_crs}')) AS overlap_area_m2,
  ST_Area(overlap_geom) AS overlap_area_degrees2,
  ST_AsText(ST_Centroid(overlap_geom)) AS overlap_centroid_wkt,
  '{args.source_crs}' AS source_crs,
  '{args.projected_crs}' AS metric_crs,
  'apache_sedona' AS computed_by
FROM twm_project_pbf_pairs
"""
            )
            result.count()
        except Exception as exc:  # pragma: no cover - depends on local Sedona jars
            metric_mode = "wgs84_degrees2_only"
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
  control_id,
  control_name,
  yjjbnttbbh,
  pbf_dlmc,
  wdgd,
  pbf_area_m2,
  CAST(NULL AS DOUBLE) AS overlap_area_m2,
  ST_Area(overlap_geom) AS overlap_area_degrees2,
  ST_AsText(ST_Centroid(overlap_geom)) AS overlap_centroid_wkt,
  '{args.source_crs}' AS source_crs,
  CAST(NULL AS STRING) AS metric_crs,
  concat('apache_sedona; projected metric fallback: ', {_sql_string_literal(str(exc)[:300])}) AS computed_by
FROM twm_project_pbf_pairs
"""
            )

        result = (
            result.withColumn(
                "overlap_ratio_project",
                F.when(F.col("project_area_m2") > 0, F.col("overlap_area_m2") / F.col("project_area_m2")),
            )
            .withColumn(
                "overlap_ratio_pbf",
                F.when(F.col("pbf_area_m2") > 0, F.col("overlap_area_m2") / F.col("pbf_area_m2")),
            )
            .orderBy(F.col("overlap_area_m2").desc_nulls_last(), F.col("overlap_area_degrees2").desc_nulls_last())
        )

        intersection_rows = result.count()
        if intersection_rows < args.min_intersections:
            _exit_error(
                "Sedona project/PBF spatial join produced too few intersections",
                {"actual": intersection_rows, "min_intersections": args.min_intersections},
            )

        result.coalesce(1).write.mode("overwrite").option("header", "true").csv(args.output_uri)
        written = spark.read.option("header", "true").csv(args.output_uri)
        output_rows = written.count()
        if output_rows != intersection_rows:
            _exit_error(
                "S3A read-back row count does not match Sedona result",
                {"computed_rows": intersection_rows, "output_rows": output_rows, "output_uri": args.output_uri},
            )

        sample_rows = [row.asDict() for row in written.limit(3).collect()]
        reference_rows = _count_csv_data_rows(reference_path)
        max_overlap = result.select(F.max("overlap_area_m2").alias("max_overlap_area_m2")).collect()[0][
            "max_overlap_area_m2"
        ]
        return {
            "status": "ok",
            "spark_version": spark.version,
            "projects_file": str(project_path),
            "pbf_file": str(pbf_path),
            "project_rows": len(project_rows),
            "pbf_rows": len(pbf_rows),
            "intersection_rows": intersection_rows,
            "reference_relation_rows": reference_rows,
            "output_uri": args.output_uri,
            "output_rows": output_rows,
            "metric_mode": metric_mode,
            "source_crs": args.source_crs,
            "projected_crs": args.projected_crs if metric_mode == "projected_m2" else None,
            "max_overlap_area_m2": max_overlap,
            "sample_rows": sample_rows,
            "packages": args.packages,
        }
    finally:
        spark.stop()


def _load_project_rows(path: Path) -> list[dict[str, Any]]:
    features = _load_features(path)
    rows: list[dict[str, Any]] = []
    for idx, feature in enumerate(features):
        props = feature.get("properties") or {}
        geometry = feature.get("geometry")
        if not geometry:
            continue
        project_id = _text(props.get("project_id") or props.get("XMDM") or f"project-{idx:05d}")
        project_name = _text(props.get("project_name") or props.get("XMMC") or project_id)
        rows.append(
            {
                "project_id": project_id,
                "project_name": project_name,
                "xmdm": _text(props.get("XMDM")),
                "xmmc": _text(props.get("XMMC")),
                "risk_scenario": _text(props.get("risk_scenario")),
                "review_priority": _text(props.get("review_priority")),
                "project_area_m2": _number(
                    props.get("geom_area_m2") or props.get("planned_area_m2") or props.get("YDMJ")
                ),
                "geometry_json": json.dumps(geometry, ensure_ascii=False, separators=(",", ":")),
            }
        )
    return rows


def _load_pbf_rows(path: Path) -> list[dict[str, Any]]:
    features = _load_features(path)
    rows: list[dict[str, Any]] = []
    for idx, feature in enumerate(features):
        props = feature.get("properties") or {}
        geometry = feature.get("geometry")
        if not geometry:
            continue
        control_id = _text(props.get("control_id") or props.get("YJJBNTTBBH") or props.get("BSM") or f"pbf-{idx:05d}")
        control_name = _text(props.get("control_name") or props.get("SJMC") or control_id)
        rows.append(
            {
                "control_id": control_id,
                "control_name": control_name,
                "yjjbnttbbh": _text(props.get("YJJBNTTBBH")),
                "dlmc": _text(props.get("DLMC")),
                "wdgd": _text(props.get("WDGD")),
                "pbf_area_m2": _number(props.get("geom_area_m2") or props.get("YJJBNTMJ") or props.get("YJJBNTTBMJ")),
                "geometry_json": json.dumps(geometry, ensure_ascii=False, separators=(",", ":")),
            }
        )
    return rows


def _load_features(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        _exit_error("GeoJSON file does not exist", {"path": str(path)})
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    features = payload.get("features")
    if not isinstance(features, list):
        _exit_error("GeoJSON payload is not a FeatureCollection", {"path": str(path)})
    return features


def _project_schema(types: Any) -> Any:
    return types.StructType(
        [
            types.StructField("project_id", types.StringType(), False),
            types.StructField("project_name", types.StringType(), True),
            types.StructField("xmdm", types.StringType(), True),
            types.StructField("xmmc", types.StringType(), True),
            types.StructField("risk_scenario", types.StringType(), True),
            types.StructField("review_priority", types.StringType(), True),
            types.StructField("project_area_m2", types.DoubleType(), True),
            types.StructField("geometry_json", types.StringType(), False),
        ]
    )


def _pbf_schema(types: Any) -> Any:
    return types.StructType(
        [
            types.StructField("control_id", types.StringType(), False),
            types.StructField("control_name", types.StringType(), True),
            types.StructField("yjjbnttbbh", types.StringType(), True),
            types.StructField("dlmc", types.StringType(), True),
            types.StructField("wdgd", types.StringType(), True),
            types.StructField("pbf_area_m2", types.DoubleType(), True),
            types.StructField("geometry_json", types.StringType(), False),
        ]
    )


def _count_csv_data_rows(path: Path) -> int | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        line_count = sum(1 for line in f if line.strip())
    return max(0, line_count - 1)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
