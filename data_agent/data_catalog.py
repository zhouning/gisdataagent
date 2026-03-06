"""
Data Asset Catalog — unified registry for data assets across local, cloud, and PostGIS.

Provides:
- Auto-registration of tool outputs (raster/vector/tabular)
- Spatial metadata extraction (CRS, bbox, feature count)
- ADK tool functions for agents to discover, search, and manage data assets
- RLS-based multi-tenancy (each user sees own + shared assets)
"""
import os
import json
from difflib import SequenceMatcher
from typing import Optional, List

from sqlalchemy import text

from .db_engine import get_engine
from .database_tools import _inject_user_context
from .user_context import current_user_id, current_user_role
from .observability import get_logger

logger = get_logger("data_catalog")

T_DATA_CATALOG = "agent_data_catalog"

# Asset type detection by file extension
_EXT_TYPE_MAP = {
    '.tif': 'raster', '.tiff': 'raster', '.img': 'raster', '.nc': 'raster',
    '.shp': 'vector', '.geojson': 'vector', '.gpkg': 'vector', '.kml': 'vector',
    '.kmz': 'vector',
    '.csv': 'tabular', '.xlsx': 'tabular', '.xls': 'tabular',
    '.html': 'map', '.png': 'map', '.jpg': 'map',
    '.docx': 'report', '.pdf': 'report',
    '.py': 'script',
}


# =====================================================================
# Table Initialization
# =====================================================================

def ensure_data_catalog_table():
    """Create the data catalog table if not exists. Called at startup."""
    engine = get_engine()
    if not engine:
        print("[DataCatalog] WARNING: Database not configured. Data catalog disabled.")
        return

    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_DATA_CATALOG} (
                    id SERIAL PRIMARY KEY,
                    asset_name VARCHAR(500) NOT NULL,
                    asset_type VARCHAR(50) NOT NULL,
                    format VARCHAR(50) DEFAULT '',
                    storage_backend VARCHAR(20) NOT NULL,
                    cloud_key VARCHAR(1000) DEFAULT '',
                    local_path VARCHAR(1000) DEFAULT '',
                    postgis_table VARCHAR(255) DEFAULT '',
                    spatial_extent JSONB DEFAULT NULL,
                    crs VARCHAR(50) DEFAULT '',
                    srid INTEGER DEFAULT 0,
                    feature_count INTEGER DEFAULT 0,
                    file_size_bytes BIGINT DEFAULT 0,
                    creation_tool VARCHAR(200) DEFAULT '',
                    creation_params JSONB DEFAULT '{{}}'::jsonb,
                    source_assets JSONB DEFAULT '[]'::jsonb,
                    tags JSONB DEFAULT '[]'::jsonb,
                    description TEXT DEFAULT '',
                    owner_username VARCHAR(100) NOT NULL,
                    is_shared BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    CONSTRAINT uq_asset_per_user UNIQUE (asset_name, owner_username, storage_backend)
                )
            """))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_data_catalog_owner ON {T_DATA_CATALOG} (owner_username)"
            ))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_data_catalog_type ON {T_DATA_CATALOG} (asset_type)"
            ))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_data_catalog_backend ON {T_DATA_CATALOG} (storage_backend)"
            ))
            conn.commit()
        print("[DataCatalog] Data catalog table ready.")
    except Exception as e:
        print(f"[DataCatalog] Error initializing data catalog: {e}")


# =====================================================================
# Spatial Metadata Extraction
# =====================================================================

def _extract_spatial_metadata(path: str) -> dict:
    """Extract spatial metadata from a file (CRS, bbox, feature count, file size).

    Non-fatal: returns partial metadata on errors.
    """
    meta = {"file_size_bytes": 0, "crs": "", "srid": 0,
            "feature_count": 0, "spatial_extent": None}

    if not os.path.exists(path):
        return meta

    meta["file_size_bytes"] = os.path.getsize(path)
    ext = os.path.splitext(path)[1].lower()

    try:
        if ext in ('.shp', '.geojson', '.gpkg', '.kml', '.kmz'):
            import geopandas as gpd
            gdf = gpd.read_file(path)
            meta["feature_count"] = len(gdf)
            if gdf.crs:
                meta["crs"] = str(gdf.crs)
                try:
                    meta["srid"] = gdf.crs.to_epsg() or 0
                except Exception:
                    pass
            if not gdf.empty:
                bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
                meta["spatial_extent"] = {
                    "minx": round(float(bounds[0]), 6),
                    "miny": round(float(bounds[1]), 6),
                    "maxx": round(float(bounds[2]), 6),
                    "maxy": round(float(bounds[3]), 6),
                }
        elif ext in ('.tif', '.tiff', '.img'):
            import rasterio
            with rasterio.open(path) as src:
                meta["crs"] = str(src.crs) if src.crs else ""
                try:
                    meta["srid"] = src.crs.to_epsg() or 0
                except Exception:
                    pass
                bounds = src.bounds
                meta["spatial_extent"] = {
                    "minx": round(float(bounds.left), 6),
                    "miny": round(float(bounds.bottom), 6),
                    "maxx": round(float(bounds.right), 6),
                    "maxy": round(float(bounds.top), 6),
                }
                meta["feature_count"] = src.count  # band count for rasters
        elif ext in ('.csv', '.xlsx', '.xls'):
            import pandas as pd
            if ext == '.csv':
                df = pd.read_csv(path, nrows=0)
            else:
                df = pd.read_excel(path, nrows=0)
            meta["feature_count"] = 0  # header only
    except Exception as e:
        logger.debug("[DataCatalog] Metadata extraction partial for %s: %s", path, e)

    return meta


def _detect_asset_type(path: str) -> str:
    """Detect asset type from file extension."""
    ext = os.path.splitext(path)[1].lower()
    return _EXT_TYPE_MAP.get(ext, 'other')


# =====================================================================
# Internal Registration Functions
# =====================================================================

def auto_register_from_path(local_path: str, creation_tool: str = "",
                            creation_params: dict = None,
                            storage_backend: str = "local",
                            cloud_key: str = "",
                            owner: str = "",
                            source_assets: list = None) -> Optional[int]:
    """Register a data asset from a file path. Returns asset ID or None.

    Extracts spatial metadata automatically. Upserts on (asset_name, owner, backend).
    """
    engine = get_engine()
    if not engine:
        return None

    owner = owner or current_user_id.get() or "anonymous"
    asset_name = os.path.basename(local_path)
    asset_type = _detect_asset_type(local_path)
    fmt = os.path.splitext(local_path)[1].lstrip('.').lower()

    meta = _extract_spatial_metadata(local_path)

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            result = conn.execute(text(f"""
                INSERT INTO {T_DATA_CATALOG}
                    (asset_name, asset_type, format, storage_backend, cloud_key,
                     local_path, spatial_extent, crs, srid, feature_count,
                     file_size_bytes, creation_tool, creation_params,
                     source_assets, owner_username)
                VALUES
                    (:name, :type, :fmt, :backend, :cloud_key,
                     :local_path, CAST(:extent AS jsonb), :crs, :srid, :count,
                     :size, :tool, CAST(:params AS jsonb),
                     CAST(:sources AS jsonb), :owner)
                ON CONFLICT (asset_name, owner_username, storage_backend)
                DO UPDATE SET
                    asset_type = EXCLUDED.asset_type,
                    format = EXCLUDED.format,
                    cloud_key = EXCLUDED.cloud_key,
                    local_path = EXCLUDED.local_path,
                    spatial_extent = EXCLUDED.spatial_extent,
                    crs = EXCLUDED.crs,
                    srid = EXCLUDED.srid,
                    feature_count = EXCLUDED.feature_count,
                    file_size_bytes = EXCLUDED.file_size_bytes,
                    creation_tool = EXCLUDED.creation_tool,
                    creation_params = EXCLUDED.creation_params,
                    source_assets = EXCLUDED.source_assets,
                    updated_at = NOW()
                RETURNING id
            """), {
                "name": asset_name,
                "type": asset_type,
                "fmt": fmt,
                "backend": storage_backend,
                "cloud_key": cloud_key,
                "local_path": local_path,
                "extent": json.dumps(meta["spatial_extent"]) if meta["spatial_extent"] else None,
                "crs": meta["crs"],
                "srid": meta["srid"],
                "count": meta["feature_count"],
                "size": meta["file_size_bytes"],
                "tool": creation_tool,
                "params": json.dumps(creation_params or {}),
                "sources": json.dumps(source_assets or []),
                "owner": owner,
            })
            row = result.fetchone()
            conn.commit()
            asset_id = row[0] if row else None
            logger.info("[DataCatalog] Registered: %s (id=%s, backend=%s)",
                        asset_name, asset_id, storage_backend)
            return asset_id
    except Exception as e:
        logger.error("[DataCatalog] Registration failed for %s: %s", local_path, e)
        return None


def _resolve_source_assets(paths: list) -> list:
    """Look up catalog entries for source file paths.

    Returns list of {"id": N, "name": "..."} for known assets,
    or {"name": "..."} for unknown paths. Non-fatal.
    """
    if not paths:
        return []

    engine = get_engine()
    if not engine:
        return [{"name": os.path.basename(p)} for p in paths]

    resolved = []
    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            for p in paths:
                name = os.path.basename(p) if os.sep in p or '/' in p else p
                row = conn.execute(text(f"""
                    SELECT id, asset_name FROM {T_DATA_CATALOG}
                    WHERE asset_name = :name
                    ORDER BY updated_at DESC LIMIT 1
                """), {"name": name}).fetchone()
                if row:
                    resolved.append({"id": row[0], "name": row[1]})
                else:
                    resolved.append({"name": name})
    except Exception:
        resolved = [{"name": os.path.basename(p)} for p in paths]

    return resolved


def register_tool_output(local_path: str, tool_name: str,
                         tool_params: dict = None, cloud_key: str = "",
                         source_paths: list = None) -> Optional[int]:
    """Non-fatal wrapper for auto_register_from_path. Used by app.py after tool execution."""
    try:
        backend = "cloud" if cloud_key else "local"
        source_assets = _resolve_source_assets(source_paths or [])
        return auto_register_from_path(
            local_path, creation_tool=tool_name,
            creation_params=tool_params,
            storage_backend=backend, cloud_key=cloud_key,
            source_assets=source_assets,
        )
    except Exception as e:
        logger.debug("[DataCatalog] register_tool_output non-fatal error: %s", e)
        return None


def register_postgis_asset(table_name: str, owner: str = "",
                           description: str = "") -> Optional[int]:
    """Register a PostGIS table as a data asset in the catalog."""
    engine = get_engine()
    if not engine:
        return None

    owner = owner or current_user_id.get() or "anonymous"

    # Try to extract spatial metadata from the PostGIS table
    meta = {"crs": "", "srid": 0, "feature_count": 0, "spatial_extent": None}
    try:
        with engine.connect() as conn:
            # Get SRID
            srid_row = conn.execute(text(
                "SELECT srid FROM geometry_columns WHERE f_table_name = :tbl AND f_table_schema = 'public'"
            ), {"tbl": table_name}).fetchone()
            if srid_row:
                meta["srid"] = srid_row[0]
                meta["crs"] = f"EPSG:{srid_row[0]}"

            # Get feature count
            count_row = conn.execute(text(
                f'SELECT count(*) FROM "{table_name}"'
            )).fetchone()
            if count_row:
                meta["feature_count"] = count_row[0]

            # Get spatial extent
            geom_col_row = conn.execute(text(
                "SELECT f_geometry_column FROM geometry_columns "
                "WHERE f_table_name = :tbl AND f_table_schema = 'public'"
            ), {"tbl": table_name}).fetchone()
            if geom_col_row:
                gcol = geom_col_row[0]
                ext_row = conn.execute(text(
                    f'SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) '
                    f'FROM (SELECT ST_Extent("{gcol}") AS e FROM "{table_name}") sub'
                )).fetchone()
                if ext_row and ext_row[0] is not None:
                    meta["spatial_extent"] = {
                        "minx": round(float(ext_row[0]), 6),
                        "miny": round(float(ext_row[1]), 6),
                        "maxx": round(float(ext_row[2]), 6),
                        "maxy": round(float(ext_row[3]), 6),
                    }
    except Exception as e:
        logger.debug("[DataCatalog] PostGIS metadata extraction partial for %s: %s", table_name, e)

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            result = conn.execute(text(f"""
                INSERT INTO {T_DATA_CATALOG}
                    (asset_name, asset_type, format, storage_backend, postgis_table,
                     spatial_extent, crs, srid, feature_count, description, owner_username)
                VALUES
                    (:name, 'vector', 'postgis', 'postgis', :tbl,
                     CAST(:extent AS jsonb), :crs, :srid, :count, :desc, :owner)
                ON CONFLICT (asset_name, owner_username, storage_backend)
                DO UPDATE SET
                    spatial_extent = EXCLUDED.spatial_extent,
                    crs = EXCLUDED.crs,
                    srid = EXCLUDED.srid,
                    feature_count = EXCLUDED.feature_count,
                    description = EXCLUDED.description,
                    updated_at = NOW()
                RETURNING id
            """), {
                "name": table_name,
                "tbl": table_name,
                "extent": json.dumps(meta["spatial_extent"]) if meta["spatial_extent"] else None,
                "crs": meta["crs"],
                "srid": meta["srid"],
                "count": meta["feature_count"],
                "desc": description,
                "owner": owner,
            })
            row = result.fetchone()
            conn.commit()
            return row[0] if row else None
    except Exception as e:
        logger.error("[DataCatalog] PostGIS registration failed for %s: %s", table_name, e)
        return None


# =====================================================================
# ADK Tool Functions (exposed to agents)
# =====================================================================

def list_data_assets(asset_type: str = "", tags: str = "",
                     keyword: str = "", storage_backend: str = "") -> dict:
    """
    [Data Lake Tool] Browse the data asset catalog.

    Lists all data assets the current user can access (own + shared).
    Supports filtering by asset_type, tags, keyword, and storage_backend.

    Args:
        asset_type: Filter by type (raster/vector/tabular/map/report/script/other). Empty = all.
        tags: Comma-separated tags to filter by. Empty = all.
        keyword: Search keyword to match against asset_name and description.
        storage_backend: Filter by backend (local/cloud/postgis). Empty = all.

    Returns:
        Dict with status and list of matching assets.
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)

            conditions = []
            params = {}

            if asset_type:
                conditions.append("asset_type = :atype")
                params["atype"] = asset_type
            if storage_backend:
                conditions.append("storage_backend = :backend")
                params["backend"] = storage_backend
            if keyword:
                conditions.append(
                    "(asset_name ILIKE :kw OR description ILIKE :kw)")
                params["kw"] = f"%{keyword}%"
            if tags:
                tag_list = [t.strip() for t in tags.split(",") if t.strip()]
                for i, tag in enumerate(tag_list):
                    conditions.append(f"tags @> CAST(:tag{i} AS jsonb)")
                    params[f"tag{i}"] = json.dumps([tag])

            where = " AND ".join(conditions) if conditions else "TRUE"

            rows = conn.execute(text(f"""
                SELECT id, asset_name, asset_type, format, storage_backend,
                       crs, feature_count, file_size_bytes, tags, description,
                       owner_username, is_shared, created_at
                FROM {T_DATA_CATALOG}
                WHERE {where}
                ORDER BY updated_at DESC
                LIMIT 100
            """), params).fetchall()

            assets = []
            for r in rows:
                assets.append({
                    "id": r[0], "name": r[1], "type": r[2], "format": r[3],
                    "backend": r[4], "crs": r[5], "features": r[6],
                    "size_bytes": r[7],
                    "tags": r[8] if isinstance(r[8], list) else json.loads(r[8] or "[]"),
                    "description": r[9],
                    "owner": r[10], "shared": r[11],
                    "created": str(r[12]),
                })

            return {
                "status": "success",
                "count": len(assets),
                "assets": assets,
                "message": f"Found {len(assets)} data assets"
                           + (f" matching '{keyword}'" if keyword else ""),
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def describe_data_asset(asset_name_or_id: str) -> dict:
    """
    [Data Lake Tool] Get full metadata for a single data asset.

    Args:
        asset_name_or_id: The asset name (filename) or numeric ID.

    Returns:
        Dict with full asset metadata including spatial extent and lineage.
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)

            # Try numeric ID first
            if asset_name_or_id.isdigit():
                row = conn.execute(text(f"""
                    SELECT * FROM {T_DATA_CATALOG} WHERE id = :id
                """), {"id": int(asset_name_or_id)}).fetchone()
            else:
                row = conn.execute(text(f"""
                    SELECT * FROM {T_DATA_CATALOG}
                    WHERE asset_name ILIKE :name
                    ORDER BY updated_at DESC LIMIT 1
                """), {"name": f"%{asset_name_or_id}%"}).fetchone()

            if not row:
                return {"status": "error",
                        "message": f"Asset '{asset_name_or_id}' not found or access denied"}

            keys = row._mapping.keys()
            asset = {k: (str(v) if hasattr(v, 'isoformat') else v) for k, v in zip(keys, row)}

            return {"status": "success", "asset": asset}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def search_data_assets(query: str) -> dict:
    """
    [Data Lake Tool] Semantic fuzzy search across data assets.

    Searches asset names, descriptions, and tags using fuzzy string matching.
    More flexible than list_data_assets keyword filtering.

    Args:
        query: Search query (natural language, e.g. "土地利用" or "DEM 斑竹").

    Returns:
        Dict with ranked list of matching assets.
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)

            rows = conn.execute(text(f"""
                SELECT id, asset_name, asset_type, format, storage_backend,
                       crs, feature_count, file_size_bytes, tags, description,
                       owner_username, is_shared
                FROM {T_DATA_CATALOG}
                ORDER BY updated_at DESC
            """)).fetchall()

            query_lower = query.lower()
            # Split query into tokens for partial matching
            # (e.g. "和平村边界" → ["和平村", "边界"] if Chinese,
            # Split query into tokens for partial matching.
            # For Chinese: use n-gram sliding window (2-4 chars) to handle
            # unsegmented queries like "和平村边界" → ["和平", "平村", "村边", "边界", "和平村", ...]
            # For English/numbers: split by non-alphanumeric chars.
            import re as _re
            raw_tokens = _re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9_]+', query_lower)
            query_tokens = []
            for tok in raw_tokens:
                if _re.match(r'^[\u4e00-\u9fff]+$', tok) and len(tok) > 2:
                    # Chinese: generate 2-char and 3-char n-grams
                    for n in (2, 3):
                        for i in range(len(tok) - n + 1):
                            query_tokens.append(tok[i:i+n])
                    query_tokens.append(tok)  # also keep the full token
                else:
                    query_tokens.append(tok)
            # Deduplicate while preserving order
            seen_tokens = set()
            unique_tokens = []
            for t in query_tokens:
                if t not in seen_tokens:
                    seen_tokens.add(t)
                    unique_tokens.append(t)
            query_tokens = unique_tokens

            scored = []
            for r in rows:
                name = r[1] or ""
                desc = r[9] or ""
                tags_val = r[8]
                if isinstance(tags_val, str):
                    tags_val = json.loads(tags_val or "[]")
                tags_str = " ".join(tags_val) if tags_val else ""

                # Combine searchable text
                searchable = f"{name} {desc} {tags_str}".lower()

                # Direct substring match (high priority)
                if query_lower in searchable:
                    score = 0.9
                else:
                    # Token-based matching: count how many query tokens appear
                    if query_tokens:
                        hits = sum(1 for t in query_tokens if t in searchable)
                        token_score = hits / len(query_tokens)
                    else:
                        token_score = 0.0

                    # Fuzzy match on name only (more effective than on full text)
                    name_fuzzy = SequenceMatcher(None, query_lower, name.lower()).ratio()

                    # Take the best score
                    score = max(token_score * 0.85, name_fuzzy)

                if score >= 0.3:
                    scored.append((score, {
                        "id": r[0], "name": name, "type": r[2], "format": r[3],
                        "backend": r[4], "crs": r[5], "features": r[6],
                        "size_bytes": r[7], "tags": tags_val, "description": desc,
                        "owner": r[10], "shared": r[11],
                        "relevance": round(score, 2),
                    }))

            scored.sort(key=lambda x: x[0], reverse=True)
            results = [s[1] for s in scored[:20]]

            return {
                "status": "success",
                "count": len(results),
                "assets": results,
                "message": f"Found {len(results)} assets matching '{query}'",
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def register_data_asset(asset_name: str, asset_type: str,
                        storage_backend: str, description: str = "",
                        cloud_key: str = "", local_path: str = "",
                        postgis_table: str = "", tags: str = "") -> dict:
    """
    [Data Lake Tool] Manually register an external data asset.

    Args:
        asset_name: Name for the data asset.
        asset_type: Type: raster/vector/tabular/map/report/script/other.
        storage_backend: Where the data lives: local/cloud/postgis.
        description: Human-readable description.
        cloud_key: Cloud storage key (for cloud backend).
        local_path: Local file path (for local backend).
        postgis_table: PostGIS table name (for postgis backend).
        tags: Comma-separated tags.

    Returns:
        Dict with status and asset ID.
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    owner = current_user_id.get() or "anonymous"
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)

            # Extract metadata if local path exists
            meta = _extract_spatial_metadata(local_path) if local_path else {
                "file_size_bytes": 0, "crs": "", "srid": 0,
                "feature_count": 0, "spatial_extent": None,
            }

            result = conn.execute(text(f"""
                INSERT INTO {T_DATA_CATALOG}
                    (asset_name, asset_type, format, storage_backend, cloud_key,
                     local_path, postgis_table, spatial_extent, crs, srid,
                     feature_count, file_size_bytes, tags, description, owner_username)
                VALUES
                    (:name, :type, :fmt, :backend, :cloud_key,
                     :local_path, :pg_table, CAST(:extent AS jsonb), :crs, :srid,
                     :count, :size, CAST(:tags AS jsonb), :desc, :owner)
                ON CONFLICT (asset_name, owner_username, storage_backend)
                DO UPDATE SET
                    description = EXCLUDED.description,
                    tags = EXCLUDED.tags,
                    updated_at = NOW()
                RETURNING id
            """), {
                "name": asset_name,
                "type": asset_type,
                "fmt": os.path.splitext(asset_name)[1].lstrip('.').lower(),
                "backend": storage_backend,
                "cloud_key": cloud_key,
                "local_path": local_path,
                "pg_table": postgis_table,
                "extent": json.dumps(meta["spatial_extent"]) if meta["spatial_extent"] else None,
                "crs": meta["crs"],
                "srid": meta["srid"],
                "count": meta["feature_count"],
                "size": meta["file_size_bytes"],
                "tags": json.dumps(tag_list),
                "desc": description,
                "owner": owner,
            })
            row = result.fetchone()
            conn.commit()
            asset_id = row[0] if row else None

            return {
                "status": "success",
                "asset_id": asset_id,
                "message": f"Registered '{asset_name}' (id={asset_id})",
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def tag_data_asset(asset_id: str, tags_json: str) -> dict:
    """
    [Data Lake Tool] Add or replace tags on a data asset.

    Args:
        asset_id: Numeric asset ID.
        tags_json: JSON array of tags, e.g. '["遥感","DEM","斑竹"]'.

    Returns:
        Dict with status.
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    try:
        tag_list = json.loads(tags_json)
        if not isinstance(tag_list, list):
            return {"status": "error", "message": "tags_json must be a JSON array"}
    except json.JSONDecodeError:
        return {"status": "error", "message": "Invalid JSON for tags_json"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            result = conn.execute(text(f"""
                UPDATE {T_DATA_CATALOG}
                SET tags = CAST(:tags AS jsonb), updated_at = NOW()
                WHERE id = :id
            """), {"tags": json.dumps(tag_list), "id": int(asset_id)})
            conn.commit()
            if result.rowcount == 0:
                return {"status": "error", "message": f"Asset {asset_id} not found or access denied"}
            return {"status": "success", "message": f"Updated tags for asset {asset_id}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def delete_data_asset(asset_id: str) -> dict:
    """
    [Data Lake Tool] Delete a data asset from the catalog.

    Only removes the catalog entry. Does not delete the actual file.

    Args:
        asset_id: Numeric asset ID to delete.

    Returns:
        Dict with status.
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            result = conn.execute(text(f"""
                DELETE FROM {T_DATA_CATALOG} WHERE id = :id
            """), {"id": int(asset_id)})
            conn.commit()
            if result.rowcount == 0:
                return {"status": "error", "message": f"Asset {asset_id} not found or access denied"}
            return {"status": "success", "message": f"Deleted asset {asset_id}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def share_data_asset(asset_id: str) -> dict:
    """
    [Data Lake Tool] Share a data asset with all users (admin only).

    Args:
        asset_id: Numeric asset ID to share.

    Returns:
        Dict with status.
    """
    role = current_user_role.get()
    if role != "admin":
        return {"status": "error", "message": "Only admins can share data assets"}

    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            result = conn.execute(text(f"""
                UPDATE {T_DATA_CATALOG}
                SET is_shared = TRUE, updated_at = NOW()
                WHERE id = :id
            """), {"id": int(asset_id)})
            conn.commit()
            if result.rowcount == 0:
                return {"status": "error", "message": f"Asset {asset_id} not found"}
            return {"status": "success", "message": f"Asset {asset_id} is now shared"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_data_lineage(asset_name_or_id: str, direction: str = "both") -> dict:
    """
    [Data Lake Tool] Trace data provenance chain for a data asset.

    Shows where data came from (ancestors) and what was derived from it (descendants).

    Args:
        asset_name_or_id: The asset name (filename) or numeric ID.
        direction: "ancestors" (sources), "descendants" (derived), or "both".

    Returns:
        Dict with lineage tree including ancestors and/or descendants.
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)

            # Find the target asset
            if asset_name_or_id.isdigit():
                target = conn.execute(text(f"""
                    SELECT id, asset_name, asset_type, creation_tool, source_assets
                    FROM {T_DATA_CATALOG} WHERE id = :id
                """), {"id": int(asset_name_or_id)}).fetchone()
            else:
                target = conn.execute(text(f"""
                    SELECT id, asset_name, asset_type, creation_tool, source_assets
                    FROM {T_DATA_CATALOG}
                    WHERE asset_name ILIKE :name
                    ORDER BY updated_at DESC LIMIT 1
                """), {"name": f"%{asset_name_or_id}%"}).fetchone()

            if not target:
                return {"status": "error",
                        "message": f"Asset '{asset_name_or_id}' not found or access denied"}

            target_id = target[0]
            target_info = {
                "id": target[0], "name": target[1],
                "type": target[2], "creation_tool": target[3],
            }

            result = {"status": "success", "asset": target_info}

            # Walk ancestors (what was this derived from)
            if direction in ("ancestors", "both"):
                ancestors = _walk_ancestors(conn, target[4], max_depth=10)
                result["ancestors"] = ancestors

            # Find descendants (what was derived from this)
            if direction in ("descendants", "both"):
                descendants = _find_descendants(conn, target_id, target[1])
                result["descendants"] = descendants

            # Build summary message
            parts = []
            if "ancestors" in result:
                n = len(result["ancestors"])
                parts.append(f"{n} source(s)" if n else "no known sources")
            if "descendants" in result:
                n = len(result["descendants"])
                parts.append(f"{n} derived asset(s)" if n else "no derived assets")
            result["message"] = f"Lineage for '{target[1]}': {', '.join(parts)}"

            return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _walk_ancestors(conn, source_assets_raw, max_depth: int = 10) -> list:
    """Recursively walk the source_assets chain upward."""
    if not source_assets_raw:
        return []

    sources = source_assets_raw if isinstance(source_assets_raw, list) else json.loads(
        source_assets_raw or "[]")
    if not sources:
        return []

    ancestors = []
    visited = set()

    def _recurse(items, depth):
        if depth >= max_depth:
            return
        for item in items:
            asset_id = item.get("id")
            asset_name = item.get("name", "")

            key = asset_id or asset_name
            if key in visited:
                continue
            visited.add(key)

            entry = {"name": asset_name, "depth": depth}
            if asset_id:
                entry["id"] = asset_id
                row = conn.execute(text(f"""
                    SELECT id, asset_name, asset_type, creation_tool, source_assets
                    FROM {T_DATA_CATALOG} WHERE id = :id
                """), {"id": asset_id}).fetchone()
                if row:
                    entry["type"] = row[2]
                    entry["creation_tool"] = row[3]
                    parent_sources = row[4] if isinstance(row[4], list) else json.loads(
                        row[4] or "[]")
                    if parent_sources:
                        _recurse(parent_sources, depth + 1)
            ancestors.append(entry)

    _recurse(sources, 0)
    return ancestors


def _find_descendants(conn, asset_id: int, asset_name: str) -> list:
    """Find assets whose source_assets reference this asset."""
    descendants = []
    try:
        rows = conn.execute(text(f"""
            SELECT id, asset_name, asset_type, creation_tool
            FROM {T_DATA_CATALOG}
            WHERE source_assets::text LIKE :pattern_id
               OR source_assets::text LIKE :pattern_name
            ORDER BY created_at
            LIMIT 50
        """), {
            "pattern_id": f'%"id": {asset_id}%',
            "pattern_name": f'%"name": "{asset_name}"%',
        }).fetchall()

        for r in rows:
            descendants.append({
                "id": r[0], "name": r[1],
                "type": r[2], "creation_tool": r[3],
            })
    except Exception:
        pass
    return descendants


def download_cloud_asset(asset_name_or_id: str) -> dict:
    """
    [Data Lake Tool] Download a cloud-stored data asset to local disk.

    Looks up the asset in the catalog, downloads from cloud storage
    (OBS/S3/GCS) to the user's local upload directory, and returns
    the local file path for subsequent analysis.

    For PostGIS assets, returns the table name directly (no download needed).
    For local assets, returns the existing local path.

    Args:
        asset_name_or_id: The asset name or numeric ID from the catalog.

    Returns:
        Dict with status, local_path (for file-based) or postgis_table,
        and asset metadata.
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)

            if asset_name_or_id.isdigit():
                row = conn.execute(text(f"""
                    SELECT id, asset_name, asset_type, format, storage_backend,
                           cloud_key, local_path, postgis_table, crs, srid
                    FROM {T_DATA_CATALOG} WHERE id = :id
                """), {"id": int(asset_name_or_id)}).fetchone()
            else:
                row = conn.execute(text(f"""
                    SELECT id, asset_name, asset_type, format, storage_backend,
                           cloud_key, local_path, postgis_table, crs, srid
                    FROM {T_DATA_CATALOG}
                    WHERE asset_name ILIKE :name
                    ORDER BY updated_at DESC LIMIT 1
                """), {"name": f"%{asset_name_or_id}%"}).fetchone()

            if not row:
                return {"status": "error",
                        "message": f"Asset '{asset_name_or_id}' not found"}

            asset_id, name, atype, fmt, backend = row[0], row[1], row[2], row[3], row[4]
            cloud_key, local_path, pg_table = row[5], row[6], row[7]
            crs, srid = row[8], row[9]

            meta = {"asset_id": asset_id, "asset_name": name,
                    "asset_type": atype, "format": fmt, "crs": crs, "srid": srid}

            # PostGIS: no download needed
            if backend == "postgis" and pg_table:
                return {"status": "success", "postgis_table": pg_table,
                        "storage": "postgis", **meta}

            # Local: return existing path
            if backend == "local" and local_path and os.path.exists(local_path):
                return {"status": "success", "local_path": local_path,
                        "storage": "local", **meta}

            # Cloud: download to user's upload dir
            if backend == "cloud" and cloud_key:
                from .obs_storage import is_obs_configured, download_file_smart
                from .user_context import get_user_upload_dir

                if not is_obs_configured():
                    return {"status": "error",
                            "message": "Cloud storage not configured"}

                user_dir = get_user_upload_dir()
                os.makedirs(user_dir, exist_ok=True)

                dl_path = download_file_smart(cloud_key, user_dir)
                if dl_path and os.path.exists(dl_path):
                    # Update catalog with local_path for future access
                    conn.execute(text(f"""
                        UPDATE {T_DATA_CATALOG}
                        SET local_path = :lp, updated_at = NOW()
                        WHERE id = :id
                    """), {"lp": dl_path, "id": asset_id})
                    conn.commit()
                    return {"status": "success", "local_path": dl_path,
                            "storage": "cloud_downloaded", **meta}
                else:
                    return {"status": "error",
                            "message": f"Failed to download '{cloud_key}' from cloud"}

            return {"status": "error",
                    "message": f"Cannot resolve asset (backend={backend})"}

    except Exception as e:
        return {"status": "error", "message": str(e)}
