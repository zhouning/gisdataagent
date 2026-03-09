"""PostGIS compute push-down strategies for large datasets.

When both data sources are backed by PostGIS tables and combined row count
exceeds 100K, spatial operations are pushed down to the database engine
instead of loading into Python memory.

SQL injection prevention: table names are validated against a strict pattern.
"""
import logging
import re
from typing import Optional

import geopandas as gpd
from sqlalchemy import text

from ...db_engine import get_engine
from ...gis_processors import _generate_output_path

logger = logging.getLogger(__name__)

# Strict table name pattern — alphanumeric + underscore + optional schema.table
_TABLE_NAME_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_.]{0,126}$')


def _validate_table_name(name: str) -> str:
    """Validate and quote a PostGIS table name to prevent SQL injection."""
    if not _TABLE_NAME_RE.match(name):
        raise ValueError(f"Invalid table name: {name!r}")
    # Double-quote each part for safe identifier quoting
    parts = name.split(".")
    return ".".join(f'"{p}"' for p in parts)


def _should_pushdown(sources) -> bool:
    """Check if PostGIS push-down is applicable for the given sources.

    Requires:
      - Both sources have postgis_table set
      - Combined row count > 100,000
      - Database engine is available
    """
    if len(sources) < 2:
        return False
    if not (sources[0].postgis_table and sources[1].postgis_table):
        return False
    total_rows = sources[0].row_count + sources[1].row_count
    if total_rows <= 100_000:
        return False
    engine = get_engine()
    if not engine:
        return False
    return True


def _pushdown_spatial_join(
    sources,
    params: dict,
) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Execute spatial join via PostGIS ST_Intersects."""
    log = []
    predicate = params.get("spatial_predicate", "intersects")

    table_a = _validate_table_name(sources[0].postgis_table)
    table_b = _validate_table_name(sources[1].postgis_table)

    predicate_fn = {
        "intersects": "ST_Intersects",
        "contains": "ST_Contains",
        "within": "ST_Within",
    }.get(predicate, "ST_Intersects")

    sql = f"""
        SELECT a.*, b.*
        FROM {table_a} a
        JOIN {table_b} b
        ON {predicate_fn}(a.geom, b.geom)
    """

    engine = get_engine()
    result = gpd.read_postgis(text(sql), engine, geom_col="geom")

    log.append(f"PostGIS push-down spatial_join ({predicate}): "
               f"{sources[0].postgis_table} × {sources[1].postgis_table} "
               f"→ {len(result)} rows")
    return result, log


def _pushdown_overlay(
    sources,
    params: dict,
) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Execute overlay via PostGIS ST_Intersection."""
    log = []

    table_a = _validate_table_name(sources[0].postgis_table)
    table_b = _validate_table_name(sources[1].postgis_table)

    sql = f"""
        SELECT
            ST_Intersection(a.geom, b.geom) AS geom,
            a.*, b.*
        FROM {table_a} a, {table_b} b
        WHERE ST_Intersects(a.geom, b.geom)
          AND NOT ST_IsEmpty(ST_Intersection(a.geom, b.geom))
    """

    engine = get_engine()
    result = gpd.read_postgis(text(sql), engine, geom_col="geom")

    log.append(f"PostGIS push-down overlay: "
               f"{sources[0].postgis_table} × {sources[1].postgis_table} "
               f"→ {len(result)} features")
    return result, log


def _pushdown_nearest_join(
    sources,
    params: dict,
) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Execute nearest-neighbor join via PostGIS LATERAL + <-> operator."""
    log = []

    table_a = _validate_table_name(sources[0].postgis_table)
    table_b = _validate_table_name(sources[1].postgis_table)

    sql = f"""
        SELECT a.*, b_nearest.*
        FROM {table_a} a
        CROSS JOIN LATERAL (
            SELECT b.*
            FROM {table_b} b
            ORDER BY b.geom <-> a.geom
            LIMIT 1
        ) b_nearest
    """

    engine = get_engine()
    result = gpd.read_postgis(text(sql), engine, geom_col="geom")

    log.append(f"PostGIS push-down nearest_join: "
               f"{sources[0].postgis_table} × {sources[1].postgis_table} "
               f"→ {len(result)} rows")
    return result, log


# Registry of PostGIS-equivalent strategies
POSTGIS_STRATEGIES = {
    "spatial_join": _pushdown_spatial_join,
    "overlay": _pushdown_overlay,
    "nearest_join": _pushdown_nearest_join,
}


def has_postgis_equivalent(strategy: str) -> bool:
    """Check if a strategy has a PostGIS push-down implementation."""
    return strategy in POSTGIS_STRATEGIES


def execute_pushdown(
    strategy: str,
    sources,
    params: dict,
) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Execute a PostGIS push-down strategy.

    Args:
        strategy: Strategy name (must be in POSTGIS_STRATEGIES).
        sources: List of FusionSource with postgis_table set.
        params: Strategy-specific parameters.

    Returns:
        (result_gdf, log_messages)
    """
    fn = POSTGIS_STRATEGIES.get(strategy)
    if not fn:
        raise ValueError(f"No PostGIS push-down for strategy: {strategy}")
    return fn(sources, params)
