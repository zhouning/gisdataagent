"""
Tile Server — PostGIS-backed vector tile (MVT) generation.

Manages temporary spatial tables for on-the-fly MVT serving via ST_AsMVT.
Lifecycle: GeoJSON import → temp PostGIS table → tile queries → expiry cleanup.
"""
import os
import uuid
import hashlib
from typing import Optional

import mercantile
import geopandas as gpd
from sqlalchemy import text

try:
    from .db_engine import get_engine
    from .user_context import current_user_id
    from .observability import get_logger
except ImportError:
    from data_agent.db_engine import get_engine
    from data_agent.user_context import current_user_id
    from data_agent.observability import get_logger

logger = get_logger("tile_server")

# Feature count thresholds (configurable via env)
MVT_FEATURE_THRESHOLD = int(os.environ.get("MVT_FEATURE_THRESHOLD", "50000"))
FGB_FEATURE_THRESHOLD = int(os.environ.get("FGB_FEATURE_THRESHOLD", "10000"))

# Maximum attribute columns to include in tiles
_MAX_TILE_COLUMNS = 20

# In-memory metadata cache for tile layers (layer_id -> metadata dict)
_layer_cache: dict[str, dict] = {}


def create_tile_layer(
    geojson_path: str,
    user_id: str,
    layer_name: str = "default",
) -> dict:
    """Import a GeoJSON file into a temporary PostGIS table for MVT serving.

    Returns metadata dict: {layer_id, table_name, srid, bounds, feature_count, columns}.
    """
    gdf = gpd.read_file(geojson_path)
    if gdf.empty:
        raise ValueError("GeoJSON file is empty")

    # Ensure valid CRS
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)
    srid = gdf.crs.to_epsg() or 4326

    # Generate unique table name
    uid_hash = hashlib.md5(user_id.encode()).hexdigest()[:4]
    short_id = uuid.uuid4().hex[:8]
    layer_id = short_id
    table_name = f"_mvt_{uid_hash}_{short_id}"

    # Select attribute columns (non-geometry, limited count)
    geom_col = gdf.geometry.name
    attr_cols = [c for c in gdf.columns if c != geom_col][:_MAX_TILE_COLUMNS]
    # Sanitize column names for SQL safety
    safe_cols = [c for c in attr_cols if c.isidentifier() or c.replace("_", "").isalnum()]

    # Import to PostGIS
    engine = get_engine()
    gdf.to_postgis(table_name, engine, if_exists="replace", index=False)
    logger.info("[TileServer] Imported %d features to %s (SRID %d)",
                len(gdf), table_name, srid)

    # Create spatial index
    with engine.connect() as conn:
        conn.execute(text(
            f'CREATE INDEX IF NOT EXISTS idx_{table_name}_geom '
            f'ON "{table_name}" USING GIST (geometry)'
        ))
        conn.commit()

    # Compute bounds in WGS84
    gdf_4326 = gdf.to_crs(epsg=4326) if srid != 4326 else gdf
    total_bounds = gdf_4326.total_bounds  # [minx, miny, maxx, maxy]
    bounds = [float(total_bounds[0]), float(total_bounds[1]),
              float(total_bounds[2]), float(total_bounds[3])]

    # Register in tracking table
    meta = {
        "layer_id": layer_id,
        "table_name": table_name,
        "owner_username": user_id,
        "layer_name": layer_name,
        "srid": srid,
        "feature_count": len(gdf),
        "bounds": bounds,
        "columns": safe_cols,
        "source_file": os.path.basename(geojson_path),
    }

    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO agent_mvt_layers
                (layer_id, table_name, owner_username, layer_name, srid,
                 feature_count, bounds, columns, source_file)
            VALUES
                (:layer_id, :table_name, :owner_username, :layer_name, :srid,
                 :feature_count, :bounds, :columns, :source_file)
        """), {
            **meta,
            "bounds": bounds,
            "columns": safe_cols,
        })
        conn.commit()

    # Cache metadata
    _layer_cache[layer_id] = meta
    logger.info("[TileServer] Registered tile layer %s (%d features, bounds=%s)",
                layer_id, len(gdf), bounds)
    return meta


def get_layer_metadata(layer_id: str) -> Optional[dict]:
    """Get metadata for a tile layer (from cache or DB)."""
    if layer_id in _layer_cache:
        return _layer_cache[layer_id]

    engine = get_engine()
    if engine is None:
        return None

    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT layer_id, table_name, owner_username, layer_name, srid, "
            "feature_count, bounds, columns, source_file "
            "FROM agent_mvt_layers WHERE layer_id = :lid"
        ), {"lid": layer_id}).fetchone()

    if not row:
        return None

    meta = {
        "layer_id": row[0],
        "table_name": row[1],
        "owner_username": row[2],
        "layer_name": row[3],
        "srid": row[4],
        "feature_count": row[5],
        "bounds": list(row[6]) if row[6] else [-180, -90, 180, 90],
        "columns": list(row[7]) if row[7] else [],
        "source_file": row[8],
    }
    _layer_cache[layer_id] = meta
    return meta


def generate_tile(layer_id: str, z: int, x: int, y: int) -> Optional[bytes]:
    """Generate a Mapbox Vector Tile (MVT) for the given z/x/y coordinates.

    Returns PBF bytes or None for empty/invalid tiles.
    """
    meta = get_layer_metadata(layer_id)
    if meta is None:
        return None

    table_name = meta["table_name"]
    srid = meta["srid"]
    layer_name = meta["layer_name"] or "default"
    columns = meta.get("columns", [])

    # Build attribute column list for the query
    col_expr = ", ".join(f'"{c}"' for c in columns) if columns else ""
    col_select = f", {col_expr}" if col_expr else ""

    # Generate tile using ST_AsMVT
    sql = text(f"""
        WITH bounds AS (
            SELECT ST_TileEnvelope(:z, :x, :y) AS geom
        ),
        mvtgeom AS (
            SELECT ST_AsMVTGeom(
                ST_Transform(t.geometry, 3857),
                bounds.geom,
                4096, 64, true
            ) AS geom
            {col_select}
            FROM "{table_name}" t, bounds
            WHERE ST_Intersects(
                t.geometry,
                ST_Transform(bounds.geom, :srid)
            )
        )
        SELECT ST_AsMVT(mvtgeom, :layer_name, 4096, 'geom')
        FROM mvtgeom
    """)

    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(sql, {
            "z": z, "x": x, "y": y,
            "srid": srid, "layer_name": layer_name,
        }).fetchone()

    if not result or not result[0]:
        return None

    tile_bytes = bytes(result[0])
    if len(tile_bytes) == 0:
        return None

    return tile_bytes


def cleanup_tile_layer(layer_id: str) -> bool:
    """Drop the PostGIS table and remove tracking metadata for a tile layer."""
    meta = get_layer_metadata(layer_id)
    if meta is None:
        return False

    table_name = meta["table_name"]
    engine = get_engine()

    with engine.connect() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS "{table_name}"'))
        conn.execute(text(
            "DELETE FROM agent_mvt_layers WHERE layer_id = :lid"
        ), {"lid": layer_id})
        conn.commit()

    _layer_cache.pop(layer_id, None)
    logger.info("[TileServer] Cleaned up tile layer %s (table %s)", layer_id, table_name)
    return True


def cleanup_expired_layers(max_age_hours: int = 24) -> int:
    """Remove all expired tile layers. Returns count of layers cleaned up."""
    engine = get_engine()
    if engine is None:
        return 0

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT layer_id, table_name FROM agent_mvt_layers "
                "WHERE expires_at < NOW()"
            )).fetchall()

            count = 0
            for row in rows:
                layer_id, table_name = row[0], row[1]
                try:
                    conn.execute(text(f'DROP TABLE IF EXISTS "{table_name}"'))
                    conn.execute(text(
                        "DELETE FROM agent_mvt_layers WHERE layer_id = :lid"
                    ), {"lid": layer_id})
                    _layer_cache.pop(layer_id, None)
                    count += 1
                except Exception as e:
                    logger.warning("[TileServer] Failed to clean layer %s: %s",
                                   layer_id, e)
            conn.commit()
            if count:
                logger.info("[TileServer] Cleaned up %d expired tile layers", count)
            return count
    except Exception as e:
        logger.warning("[TileServer] Expired layer cleanup failed: %s", e)
        return 0
