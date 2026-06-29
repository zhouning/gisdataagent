"""End-to-end TxPoint10M MinIO + Iceberg + Sedona analysis.

The pipeline reads the 10M-point transaction Shapefile from MinIO, materializes
an Iceberg transaction table in the MinIO warehouse, builds spatial-temporal
aggregate Iceberg tables, and exports a browser-friendly Leaflet map.
"""

from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "outputs" / "txpoint10m_lakehouse"
SUMMARY_PATH = OUTPUT_DIR / "txpoint10m_summary.json"
GEOJSON_PATH = OUTPUT_DIR / "txpoint10m_grid_025deg_top.geojson"
MAP_HTML_PATH = OUTPUT_DIR / "txpoint10m_leaflet_map.html"
TWM_SCALE_PROFILE_PATH = OUTPUT_DIR / "txpoint10m_twm_production_scale_profile.json"

RAW_URI = os.environ.get(
    "TXPOINT10M_RAW_URI",
    "s3a://gis-agent-lakehouse/raw/txpoint10m/TxPoint10M.shp",
)
WAREHOUSE_URI = os.environ.get(
    "TXPOINT10M_ICEBERG_WAREHOUSE_URI",
    "s3a://gis-agent-lakehouse/warehouse/iceberg",
)
MINIO_ENDPOINT = os.environ.get("AWS_ENDPOINT_URL", "http://minio:9000")
MINIO_ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY_ID", "minio_admin")
MINIO_SECRET_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "local_dev_minio_secret")

CATALOG = os.environ.get("TXPOINT10M_ICEBERG_CATALOG", "mmfe")
NAMESPACE = os.environ.get("TXPOINT10M_ICEBERG_NAMESPACE", "txpoint10m")
TX_TABLE = f"{CATALOG}.{NAMESPACE}.transactions"
GRID_TABLE = f"{CATALOG}.{NAMESPACE}.grid_025deg"
DAILY_TABLE = f"{CATALOG}.{NAMESPACE}.daily_summary"
HOURLY_TABLE = f"{CATALOG}.{NAMESPACE}.hourly_summary"

WEB_MERCATOR_RADIUS = 6378137.0
GRID_DEGREES = 0.25


def build_spark(app_name: str = "txpoint10m-lakehouse-analysis"):
    from sedona.spark import SedonaContext

    builder = (
        SedonaContext.builder()
        .master(os.environ.get("SPARK_MASTER", "local[4]"))
        .appName(app_name)
        .config("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
        .config(f"spark.sql.catalog.{CATALOG}", "org.apache.iceberg.spark.SparkCatalog")
        .config(f"spark.sql.catalog.{CATALOG}.type", "hadoop")
        .config(f"spark.sql.catalog.{CATALOG}.warehouse", WAREHOUSE_URI)
        .config("spark.hadoop.fs.s3a.endpoint", MINIO_ENDPOINT)
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
        .config("spark.hadoop.fs.s3a.access.key", MINIO_ACCESS_KEY)
        .config("spark.hadoop.fs.s3a.secret.key", MINIO_SECRET_KEY)
        .config(
            "spark.hadoop.fs.s3a.aws.credentials.provider",
            "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider",
        )
        .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer")
        .config("spark.kryo.registrator", "org.apache.sedona.core.serde.SedonaKryoRegistrator")
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.sql.adaptive.coalescePartitions.enabled", "true")
        .config("spark.sql.shuffle.partitions", os.environ.get("TXPOINT10M_SHUFFLE_PARTITIONS", "96"))
        .config("spark.driver.memory", os.environ.get("SPARK_DRIVER_MEMORY", "6g"))
        .config("spark.executor.memory", os.environ.get("SPARK_EXECUTOR_MEMORY", "6g"))
    )
    spark = builder.getOrCreate()
    SedonaContext.create(spark)
    return spark


def run_analysis(map_top_n: int = 8000, rebuild: bool = True) -> dict[str, Any]:
    """Run the full lakehouse analysis and return a serializable summary."""
    from pyspark.sql import functions as F

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    spark = build_spark()
    try:
        spark.sparkContext.setLogLevel(os.environ.get("SPARK_LOG_LEVEL", "WARN"))
        spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {CATALOG}.{NAMESPACE}")

        if rebuild or not _table_exists(spark, TX_TABLE):
            source_df = spark.read.format("shapefile").load(RAW_URI)
            transformed = (
                source_df.select(
                    F.col("ORIG_ID").alias("orig_id"),
                    F.col("DEST_ID").alias("dest_id"),
                    F.col("AMOUNT").cast("long").alias("amount"),
                    F.to_timestamp("DATE_TIME", "yyyy-MM-dd HH:mm:ss").alias("transaction_ts"),
                    F.expr("ST_X(geometry)").cast("double").alias("x_3857"),
                    F.expr("ST_Y(geometry)").cast("double").alias("y_3857"),
                )
                .withColumn("lon", F.expr(f"degrees(x_3857 / {WEB_MERCATOR_RADIUS})"))
                .withColumn("lat", F.expr(f"degrees(atan(sinh(y_3857 / {WEB_MERCATOR_RADIUS})))"))
                .withColumn("transaction_date", F.to_date("transaction_ts"))
                .withColumn("transaction_month", F.month("transaction_ts"))
                .withColumn("transaction_hour", F.hour("transaction_ts"))
                .withColumn("amount_band", F.floor(F.col("amount") / F.lit(1000)).cast("int"))
                .repartition(24, "transaction_month")
            )
            transformed.createOrReplaceTempView("txpoint10m_stage")
            spark.sql(
                f"""
                CREATE OR REPLACE TABLE {TX_TABLE}
                USING iceberg
                PARTITIONED BY (transaction_month)
                TBLPROPERTIES (
                  'write.format.default'='parquet',
                  'format-version'='2'
                )
                AS
                SELECT * FROM txpoint10m_stage
                """
            )

        if rebuild or not _table_exists(spark, GRID_TABLE):
            spark.sql(
                f"""
                CREATE OR REPLACE TABLE {GRID_TABLE}
                USING iceberg
                TBLPROPERTIES (
                  'write.format.default'='parquet',
                  'format-version'='2'
                )
                AS
                WITH binned AS (
                  SELECT
                    ROUND(FLOOR(lon / {GRID_DEGREES}) * {GRID_DEGREES}, 4) AS lon_min,
                    ROUND(FLOOR(lat / {GRID_DEGREES}) * {GRID_DEGREES}, 4) AS lat_min,
                    amount,
                    orig_id,
                    dest_id,
                    transaction_ts,
                    transaction_hour
                  FROM {TX_TABLE}
                  WHERE lon BETWEEN -180 AND 180
                    AND lat BETWEEN -85 AND 85
                )
                SELECT
                  lon_min,
                  lat_min,
                  ROUND(lon_min + {GRID_DEGREES / 2.0}, 4) AS lon,
                  ROUND(lat_min + {GRID_DEGREES / 2.0}, 4) AS lat,
                  COUNT(*) AS txn_count,
                  SUM(amount) AS amount_sum,
                  AVG(amount) AS amount_avg,
                  MIN(amount) AS amount_min,
                  MAX(amount) AS amount_max,
                  APPROX_COUNT_DISTINCT(orig_id) AS approx_unique_orig,
                  APPROX_COUNT_DISTINCT(dest_id) AS approx_unique_dest,
                  MIN(transaction_ts) AS first_seen,
                  MAX(transaction_ts) AS last_seen
                FROM binned
                GROUP BY lon_min, lat_min
                """
            )

        if rebuild or not _table_exists(spark, DAILY_TABLE):
            spark.sql(
                f"""
                CREATE OR REPLACE TABLE {DAILY_TABLE}
                USING iceberg
                AS
                SELECT
                  transaction_date,
                  COUNT(*) AS txn_count,
                  SUM(amount) AS amount_sum,
                  AVG(amount) AS amount_avg,
                  APPROX_COUNT_DISTINCT(orig_id) AS approx_unique_orig,
                  APPROX_COUNT_DISTINCT(dest_id) AS approx_unique_dest
                FROM {TX_TABLE}
                GROUP BY transaction_date
                """
            )

        if rebuild or not _table_exists(spark, HOURLY_TABLE):
            spark.sql(
                f"""
                CREATE OR REPLACE TABLE {HOURLY_TABLE}
                USING iceberg
                AS
                SELECT
                  transaction_hour,
                  COUNT(*) AS txn_count,
                  SUM(amount) AS amount_sum,
                  AVG(amount) AS amount_avg
                FROM {TX_TABLE}
                GROUP BY transaction_hour
                """
            )

        summary = _collect_summary(spark)
        features = _export_grid_geojson(spark, map_top_n)
        _write_leaflet_map(summary, features)

        summary["artifacts"] = {
            "summary_json": str(SUMMARY_PATH),
            "grid_geojson": str(GEOJSON_PATH),
            "leaflet_map_html": str(MAP_HTML_PATH),
        }
        summary["elapsed_seconds"] = round(time.monotonic() - started, 2)
        write_twm_production_scale_profile(summary, TWM_SCALE_PROFILE_PATH)
        summary["artifacts"]["twm_production_scale_profile"] = str(TWM_SCALE_PROFILE_PATH)
        SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        return summary
    finally:
        spark.stop()


def load_summary() -> dict[str, Any]:
    return json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))


def build_twm_production_scale_profile(summary: dict[str, Any]) -> dict[str, Any]:
    """Convert a TxPoint10M lakehouse summary into TWM scale-readiness evidence."""
    tx_stats = dict(summary.get("transaction_stats") or {})
    grid_stats = dict(summary.get("grid_stats") or {})
    tables = dict(summary.get("tables") or {})
    artifacts = dict(summary.get("artifacts") or {})
    row_count = _int_value(tx_stats.get("row_count"))
    grid_cell_count = _int_value(grid_stats.get("grid_cell_count"))
    covered_txn_count = _int_value(grid_stats.get("covered_txn_count"))
    elapsed_seconds = _float_value(summary.get("elapsed_seconds"))
    generated_at = str(summary.get("generated_at") or datetime.now(timezone.utc).isoformat())
    return {
        "schema": "territory_world_model.production_scale_profile.v1",
        "example_only": False,
        "not_for_production": False,
        "profile_id": "txpoint10m_minio_iceberg_sedona_scale_evidence",
        "created_by": "scripts/txpoint10m_lakehouse_analysis.py",
        "created_at": generated_at,
        "scope": {
            "region_scope": "continental_us_synthetic_transaction_points",
            "business_scope": "lakehouse_spatiotemporal_point_analytics_benchmark",
            "sensitivity": "sanitized_metadata_only",
            "source_summary_status": str(summary.get("status") or "unknown"),
        },
        "layers": [
            {
                "name": "txpoint10m_transactions",
                "row_count": row_count,
                "storage_format": "iceberg",
                "lakehouse_table": True,
                "lakehouse_table_name": tables.get("transactions"),
                "raw_uri": summary.get("raw_uri"),
                "partition_columns": ["transaction_month"],
                "spatial_index": "grid_025deg",
                "tiling": "0.25_degree_grid",
                "sampling_strategy": "spatial_temporal_grid_holdout_ready",
                "temporal_extent": {
                    "min_ts": str(tx_stats.get("min_ts") or ""),
                    "max_ts": str(tx_stats.get("max_ts") or ""),
                    "active_day_count": _int_value((summary.get("daily_stats") or {}).get("active_day_count")),
                },
                "spatial_extent": {
                    "min_lon": _float_value(tx_stats.get("min_lon")),
                    "max_lon": _float_value(tx_stats.get("max_lon")),
                    "min_lat": _float_value(tx_stats.get("min_lat")),
                    "max_lat": _float_value(tx_stats.get("max_lat")),
                },
            },
            {
                "name": "txpoint10m_grid_025deg",
                "row_count": grid_cell_count,
                "storage_format": "iceberg",
                "lakehouse_table": True,
                "lakehouse_table_name": tables.get("grid_025deg"),
                "partition_columns": [],
                "spatial_index": "grid_025deg",
                "tiling": "0.25_degree_grid",
                "covered_source_row_count": covered_txn_count,
            },
        ],
        "storage": {
            "table_format": "iceberg",
            "object_store": "minio",
            "warehouse_uri": summary.get("warehouse_uri"),
            "partition_columns": ["transaction_month"],
            "spatial_index": "grid_025deg",
            "catalog_tables": tables,
        },
        "compute": {
            "engine": "spark",
            "spatial_engine": "sedona",
            "sql_engine": "spark_sql",
            "distributed": True,
            "spark_version": summary.get("spark_version"),
            "execution_note": "Spark/Sedona engine family exercised locally; production cluster capacity remains a separate gate.",
        },
        "validation": {
            "sampling_strategy": "spatial_temporal_grid_holdout",
            "chunking": "transaction_month_plus_grid_025deg",
            "benchmark_elapsed_seconds": elapsed_seconds,
            "benchmark_row_count": row_count,
        },
        "serving": {
            "tiling": "leaflet_grid_025deg_top_cells",
            "tile_cache": "map_artifact_exported",
            "artifacts": {
                "grid_geojson": artifacts.get("grid_geojson"),
                "leaflet_map_html": artifacts.get("leaflet_map_html"),
                "summary_json": artifacts.get("summary_json"),
            },
        },
        "claim_boundary": (
            "TxPoint10M lakehouse scale evidence proves the MinIO/Iceberg/Sedona analytics path can exercise "
            "a ten-million-row spatiotemporal point workload; it does not prove full TWM production accuracy, "
            "national-scale cluster capacity, simulator quality or planner optimality."
        ),
    }


def write_twm_production_scale_profile(summary: dict[str, Any], path: Path | str = TWM_SCALE_PROFILE_PATH) -> dict[str, Any]:
    profile = build_twm_production_scale_profile(summary)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return profile


def _table_exists(spark, table: str) -> bool:
    try:
        spark.table(table).limit(1).collect()
        return True
    except Exception:
        return False


def _int_value(value: Any) -> int:
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def _float_value(value: Any) -> float:
    try:
        parsed = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(parsed):
        return 0.0
    return round(parsed, 6)


def _collect_summary(spark) -> dict[str, Any]:
    tx_stats = spark.sql(
        f"""
        SELECT
          COUNT(*) AS row_count,
          MIN(transaction_ts) AS min_ts,
          MAX(transaction_ts) AS max_ts,
          MIN(amount) AS min_amount,
          MAX(amount) AS max_amount,
          AVG(amount) AS avg_amount,
          MIN(lon) AS min_lon,
          MAX(lon) AS max_lon,
          MIN(lat) AS min_lat,
          MAX(lat) AS max_lat,
          APPROX_COUNT_DISTINCT(orig_id) AS approx_unique_orig,
          APPROX_COUNT_DISTINCT(dest_id) AS approx_unique_dest
        FROM {TX_TABLE}
        """
    ).collect()[0].asDict()
    grid_stats = spark.sql(
        f"""
        SELECT
          COUNT(*) AS grid_cell_count,
          MAX(txn_count) AS max_cell_txn_count,
          SUM(txn_count) AS covered_txn_count
        FROM {GRID_TABLE}
        """
    ).collect()[0].asDict()
    daily_stats = spark.sql(
        f"""
        SELECT
          COUNT(*) AS active_day_count,
          MAX(txn_count) AS max_daily_txn_count,
          MIN(txn_count) AS min_daily_txn_count
        FROM {DAILY_TABLE}
        """
    ).collect()[0].asDict()
    hourly_rows = [
        row.asDict()
        for row in spark.sql(
            f"""
            SELECT transaction_hour, txn_count, amount_sum, amount_avg
            FROM {HOURLY_TABLE}
            ORDER BY transaction_hour
            """
        ).collect()
    ]
    top_cells = [
        row.asDict()
        for row in spark.sql(
            f"""
            SELECT lon, lat, txn_count, amount_sum, amount_avg,
                   approx_unique_orig, approx_unique_dest, first_seen, last_seen
            FROM {GRID_TABLE}
            ORDER BY txn_count DESC
            LIMIT 10
            """
        ).collect()
    ]
    return {
        "status": "ok",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "spark_version": spark.version,
        "raw_uri": RAW_URI,
        "warehouse_uri": WAREHOUSE_URI,
        "tables": {
            "transactions": TX_TABLE,
            "grid_025deg": GRID_TABLE,
            "daily_summary": DAILY_TABLE,
            "hourly_summary": HOURLY_TABLE,
        },
        "transaction_stats": tx_stats,
        "grid_stats": grid_stats,
        "daily_stats": daily_stats,
        "hourly_summary": hourly_rows,
        "top_grid_cells": top_cells,
    }


def _export_grid_geojson(spark, map_top_n: int) -> list[dict[str, Any]]:
    rows = [
        row.asDict()
        for row in spark.sql(
            f"""
            SELECT lon, lat, txn_count, amount_sum, amount_avg,
                   amount_min, amount_max, approx_unique_orig,
                   approx_unique_dest, first_seen, last_seen
            FROM {GRID_TABLE}
            ORDER BY txn_count DESC
            LIMIT {int(map_top_n)}
            """
        ).collect()
    ]
    features = []
    for row in rows:
        lon = float(row["lon"])
        lat = float(row["lat"])
        props = {
            "txn_count": int(row["txn_count"]),
            "amount_sum": int(row["amount_sum"]),
            "amount_avg": round(float(row["amount_avg"]), 2),
            "amount_min": int(row["amount_min"]),
            "amount_max": int(row["amount_max"]),
            "approx_unique_orig": int(row["approx_unique_orig"]),
            "approx_unique_dest": int(row["approx_unique_dest"]),
            "first_seen": str(row["first_seen"]),
            "last_seen": str(row["last_seen"]),
        }
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": props,
            }
        )
    feature_collection = {
        "type": "FeatureCollection",
        "metadata": {
            "source": GRID_TABLE,
            "grid_degrees": GRID_DEGREES,
            "top_n": map_top_n,
        },
        "features": features,
    }
    GEOJSON_PATH.write_text(json.dumps(feature_collection, ensure_ascii=False, default=str), encoding="utf-8")
    return features


def _write_leaflet_map(summary: dict[str, Any], features: list[dict[str, Any]]) -> None:
    tx_stats = summary["transaction_stats"]
    grid_stats = summary["grid_stats"]
    max_count = max((int(f["properties"]["txn_count"]) for f in features), default=1)
    data_json = json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, default=str)
    summary_json = json.dumps(
        {
            "rows": int(tx_stats["row_count"]),
            "time_range": f"{tx_stats['min_ts']} to {tx_stats['max_ts']}",
            "amount_range": f"{tx_stats['min_amount']} to {tx_stats['max_amount']}",
            "grid_cells": int(grid_stats["grid_cell_count"]),
            "shown_cells": len(features),
            "raw_uri": summary["raw_uri"],
            "transactions_table": summary["tables"]["transactions"],
            "grid_table": summary["tables"]["grid_025deg"],
        },
        ensure_ascii=False,
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TxPoint10M Lakehouse Hotspot Map</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    html, body {{ margin: 0; height: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    #map {{ height: 100vh; width: 100%; background: #f4f6f8; }}
    .info {{
      background: rgba(255, 255, 255, 0.94);
      border: 1px solid #c9d1d9;
      border-radius: 6px;
      box-shadow: 0 2px 12px rgba(0, 0, 0, 0.16);
      color: #1f2937;
      line-height: 1.35;
      padding: 10px 12px;
      max-width: 360px;
    }}
    .info h1 {{ font-size: 15px; margin: 0 0 8px; font-weight: 700; }}
    .info div {{ margin: 3px 0; font-size: 12px; }}
    .legend-dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 5px; }}
  </style>
</head>
<body>
  <div id="map"></div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const geojson = {data_json};
    const summary = {summary_json};
    const maxCount = {max_count};
    const map = L.map('map', {{ preferCanvas: true }}).setView([39.5, -98.5], 4);
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      maxZoom: 12,
      attribution: '&copy; OpenStreetMap contributors'
    }}).addTo(map);

    function colorFor(count) {{
      const t = Math.max(0, Math.min(1, Math.log1p(count) / Math.log1p(maxCount)));
      if (t > 0.82) return '#7f0000';
      if (t > 0.66) return '#d7301f';
      if (t > 0.48) return '#fc8d59';
      if (t > 0.30) return '#fdbb84';
      return '#2b8cbe';
    }}
    function radiusFor(count) {{
      return Math.max(3, Math.min(20, 2 + Math.sqrt(count / maxCount) * 20));
    }}
    const layer = L.geoJSON(geojson, {{
      pointToLayer: function(feature, latlng) {{
        const count = feature.properties.txn_count;
        return L.circleMarker(latlng, {{
          radius: radiusFor(count),
          color: '#263238',
          weight: 0.4,
          fillColor: colorFor(count),
          fillOpacity: 0.64
        }});
      }},
      onEachFeature: function(feature, layer) {{
        const p = feature.properties;
        layer.bindTooltip(
          `<b>${{p.txn_count.toLocaleString()}} transactions</b><br>` +
          `Amount sum: ${{p.amount_sum.toLocaleString()}}<br>` +
          `Avg amount: ${{p.amount_avg.toLocaleString()}}<br>` +
          `Unique origin/dest: ${{p.approx_unique_orig.toLocaleString()}} / ${{p.approx_unique_dest.toLocaleString()}}<br>` +
          `${{p.first_seen}} - ${{p.last_seen}}`
        );
      }}
    }}).addTo(map);
    if (layer.getBounds().isValid()) map.fitBounds(layer.getBounds(), {{ padding: [18, 18] }});

    const info = L.control({{ position: 'topright' }});
    info.onAdd = function() {{
      const div = L.DomUtil.create('div', 'info');
      div.innerHTML = `
        <h1>TxPoint10M lakehouse hotspot map</h1>
        <div><b>Rows:</b> ${{summary.rows.toLocaleString()}}</div>
        <div><b>Time:</b> ${{summary.time_range}}</div>
        <div><b>Amount:</b> ${{summary.amount_range}}</div>
        <div><b>Grid:</b> ${{summary.grid_cells.toLocaleString()}} cells, showing top ${{summary.shown_cells.toLocaleString()}}</div>
        <div><b>Raw:</b> ${{summary.raw_uri}}</div>
        <div><b>Iceberg:</b> ${{summary.transactions_table}}</div>
        <div style="margin-top: 8px;">
          <span class="legend-dot" style="background:#2b8cbe"></span>low
          <span class="legend-dot" style="background:#fc8d59"></span>medium
          <span class="legend-dot" style="background:#7f0000"></span>high
        </div>`;
      return div;
    }};
    info.addTo(map);
  </script>
</body>
</html>
"""
    MAP_HTML_PATH.write_text(html, encoding="utf-8")


def main() -> None:
    map_top_n = int(os.environ.get("TXPOINT10M_MAP_TOP_N", "8000"))
    rebuild = os.environ.get("TXPOINT10M_REBUILD", "1") not in {"0", "false", "False"}
    summary = run_analysis(map_top_n=map_top_n, rebuild=rebuild)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
