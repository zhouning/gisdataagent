"""
Virtual Data Sources — pluggable remote connector framework (v14.5).

Users register external geospatial data services and query them on demand.
Credentials are Fernet-encrypted at rest.  Connector logic lives in
``data_agent.connectors`` (BaseConnector plugin architecture).

All DB operations are non-fatal (never raise to caller).
"""
import json
import logging
import os
import base64
import hashlib
import threading
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from .db_engine import get_engine
from .database_tools import T_VIRTUAL_SOURCES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_SOURCE_TYPES = {"wfs", "stac", "ogc_api", "custom_api", "wms", "arcgis_rest", "database", "object_storage"}
VALID_REFRESH_POLICIES = {"on_demand", "interval:5m", "interval:30m", "interval:1h", "realtime"}
VALID_AUTH_TYPES = {"bearer", "basic", "apikey", "none"}
SOURCE_NAME_MAX = 200
ENDPOINT_URL_MAX = 1000
MAX_SOURCES_PER_USER = 50

# ---------------------------------------------------------------------------
# Fernet encryption (keyed from CHAINLIT_AUTH_SECRET, distinct salt)
# ---------------------------------------------------------------------------

_FERNET_KEY: Optional[bytes] = None
_fernet_lock = threading.Lock()


def _get_fernet():
    """Return a Fernet instance keyed from CHAINLIT_AUTH_SECRET, or None."""
    global _FERNET_KEY
    if _FERNET_KEY is not None:
        from cryptography.fernet import Fernet
        return Fernet(_FERNET_KEY)
    with _fernet_lock:
        # Double-check after acquiring lock
        if _FERNET_KEY is not None:
            from cryptography.fernet import Fernet
            return Fernet(_FERNET_KEY)
        secret = os.environ.get("CHAINLIT_AUTH_SECRET", "")
        if not secret:
            return None
        _FERNET_KEY = base64.urlsafe_b64encode(
            hashlib.pbkdf2_hmac("sha256", secret.encode(), b"vsource-salt", 100_000, dklen=32))
        from cryptography.fernet import Fernet
        return Fernet(_FERNET_KEY)


def _encrypt_dict(d: dict) -> str:
    """Encrypt a dict to JSON string. Wraps as {"_enc": token} if Fernet available."""
    if not d:
        return json.dumps(d)
    f = _get_fernet()
    if not f:
        return json.dumps(d)
    return json.dumps({"_enc": f.encrypt(json.dumps(d).encode()).decode()})


def _decrypt_dict(val) -> dict:
    """Decrypt from DB value (dict or str). Handles {"_enc": ...} and plain dicts."""
    if isinstance(val, str):
        val = json.loads(val) if val else {}
    if not isinstance(val, dict):
        return {}
    if "_enc" in val:
        f = _get_fernet()
        if f:
            try:
                return json.loads(f.decrypt(val["_enc"].encode()).decode())
            except Exception:
                pass
        return {}
    return val


# ---------------------------------------------------------------------------
# Table initialization
# ---------------------------------------------------------------------------

def ensure_virtual_sources_table():
    """Create agent_virtual_sources table from migration SQL. Called at startup."""
    engine = get_engine()
    if not engine:
        print("[VirtualSources] WARNING: Database not configured. Virtual sources disabled.")
        return
    try:
        sql_path = os.path.join(os.path.dirname(__file__), "migrations", "012_virtual_sources.sql")
        with open(sql_path, encoding="utf-8") as f:
            ddl = f.read()
        with engine.connect() as conn:
            for stmt in ddl.split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(text(stmt))
            conn.commit()
        logger.info("Virtual sources table ensured")
    except Exception as e:
        logger.warning("Failed to ensure virtual sources table: %s", e)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_source(data: dict) -> Optional[str]:
    """Validate source fields. Returns error message or None."""
    name = data.get("source_name", "")
    if not name or len(name) > SOURCE_NAME_MAX:
        return f"source_name is required (max {SOURCE_NAME_MAX} chars)"
    stype = data.get("source_type", "")
    if stype not in VALID_SOURCE_TYPES:
        return f"source_type must be one of {VALID_SOURCE_TYPES}"
    url = data.get("endpoint_url", "")
    if not url or len(url) > ENDPOINT_URL_MAX:
        return f"endpoint_url is required (max {ENDPOINT_URL_MAX} chars)"
    auth = data.get("auth_config", {})
    if auth and auth.get("type") and auth["type"] not in VALID_AUTH_TYPES:
        return f"auth_config.type must be one of {VALID_AUTH_TYPES}"
    return None


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_virtual_source(
    source_name: str,
    source_type: str,
    endpoint_url: str,
    owner_username: str,
    auth_config: dict | None = None,
    query_config: dict | None = None,
    schema_mapping: dict | None = None,
    default_crs: str = "EPSG:4326",
    spatial_extent: dict | None = None,
    refresh_policy: str = "on_demand",
    is_shared: bool = False,
) -> dict:
    """Create a new virtual data source. Returns {"status": "ok", "id": N} or error."""
    data = {
        "source_name": source_name,
        "source_type": source_type,
        "endpoint_url": endpoint_url,
    }
    err = _validate_source(data)
    if err:
        return {"status": "error", "message": err}

    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not available"}

    try:
        # Check per-user limit
        with engine.connect() as conn:
            cnt = conn.execute(
                text(f"SELECT COUNT(*) FROM {T_VIRTUAL_SOURCES} WHERE owner_username = :u"),
                {"u": owner_username},
            ).scalar()
            if cnt and cnt >= MAX_SOURCES_PER_USER:
                return {"status": "error", "message": f"Max {MAX_SOURCES_PER_USER} sources per user"}

            conn.execute(text(f"""
                INSERT INTO {T_VIRTUAL_SOURCES}
                    (source_name, source_type, endpoint_url, auth_config,
                     query_config, schema_mapping, default_crs, spatial_extent,
                     refresh_policy, owner_username, is_shared)
                VALUES
                    (:name, :stype, :url, CAST(:auth AS jsonb),
                     CAST(:qcfg AS jsonb), CAST(:smap AS jsonb), :crs, CAST(:extent AS jsonb),
                     :refresh, :owner, :shared)
            """), {
                "name": source_name,
                "stype": source_type,
                "url": endpoint_url,
                "auth": _encrypt_dict(auth_config or {}),
                "qcfg": json.dumps(query_config or {}),
                "smap": json.dumps(schema_mapping or {}),
                "crs": default_crs,
                "extent": json.dumps(spatial_extent) if spatial_extent else None,
                "refresh": refresh_policy,
                "owner": owner_username,
                "shared": is_shared,
            })
            row = conn.execute(
                text(f"SELECT id FROM {T_VIRTUAL_SOURCES} WHERE source_name = :n AND owner_username = :u"),
                {"n": source_name, "u": owner_username},
            ).fetchone()
            conn.commit()
        sid = row[0] if row else None
        logger.info("Created virtual source '%s' (type=%s, owner=%s)", source_name, source_type, owner_username)
        return {"status": "ok", "id": sid}
    except Exception as e:
        if "uq_vsource" in str(e).lower() or "unique" in str(e).lower():
            return {"status": "error", "message": f"Source '{source_name}' already exists for this user"}
        logger.warning("Failed to create virtual source: %s", e)
        return {"status": "error", "message": str(e)}


def list_virtual_sources(owner_username: str, include_shared: bool = True) -> list[dict]:
    """List virtual sources visible to a user."""
    engine = get_engine()
    if not engine:
        return []
    try:
        if include_shared:
            q = (f"SELECT id, source_name, source_type, endpoint_url, query_config, "
                 f"default_crs, spatial_extent, refresh_policy, enabled, "
                 f"owner_username, is_shared, health_status, created_at, updated_at "
                 f"FROM {T_VIRTUAL_SOURCES} "
                 f"WHERE owner_username = :u OR is_shared = TRUE "
                 f"ORDER BY source_name")
        else:
            q = (f"SELECT id, source_name, source_type, endpoint_url, query_config, "
                 f"default_crs, spatial_extent, refresh_policy, enabled, "
                 f"owner_username, is_shared, health_status, created_at, updated_at "
                 f"FROM {T_VIRTUAL_SOURCES} "
                 f"WHERE owner_username = :u ORDER BY source_name")
        with engine.connect() as conn:
            rows = conn.execute(text(q), {"u": owner_username}).fetchall()
        results = []
        for r in rows:
            qcfg = r[4] if isinstance(r[4], dict) else (json.loads(r[4]) if r[4] else {})
            extent = r[6] if isinstance(r[6], dict) else (json.loads(r[6]) if r[6] else None)
            results.append({
                "id": r[0], "source_name": r[1], "source_type": r[2],
                "endpoint_url": r[3], "query_config": qcfg,
                "default_crs": r[5], "spatial_extent": extent,
                "refresh_policy": r[7], "enabled": bool(r[8]),
                "owner_username": r[9], "is_shared": bool(r[10]),
                "health_status": r[11],
                "created_at": str(r[12]) if r[12] else None,
                "updated_at": str(r[13]) if r[13] else None,
            })
        return results
    except Exception as e:
        logger.warning("Failed to list virtual sources: %s", e)
        return []


def get_virtual_source(source_id: int, owner_username: str) -> Optional[dict]:
    """Get a single virtual source by ID (owner or shared)."""
    engine = get_engine()
    if not engine:
        return None
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                f"SELECT id, source_name, source_type, endpoint_url, auth_config, "
                f"query_config, schema_mapping, default_crs, spatial_extent, "
                f"refresh_policy, enabled, owner_username, is_shared, "
                f"health_status, last_health_check, created_at, updated_at "
                f"FROM {T_VIRTUAL_SOURCES} "
                f"WHERE id = :id AND (owner_username = :u OR is_shared = TRUE)"
            ), {"id": source_id, "u": owner_username}).fetchone()
        if not row:
            return None
        qcfg = row[5] if isinstance(row[5], dict) else (json.loads(row[5]) if row[5] else {})
        smap = row[6] if isinstance(row[6], dict) else (json.loads(row[6]) if row[6] else {})
        extent = row[8] if isinstance(row[8], dict) else (json.loads(row[8]) if row[8] else None)
        return {
            "id": row[0], "source_name": row[1], "source_type": row[2],
            "endpoint_url": row[3], "auth_config": _decrypt_dict(row[4]),
            "query_config": qcfg, "schema_mapping": smap,
            "default_crs": row[7], "spatial_extent": extent,
            "refresh_policy": row[9], "enabled": bool(row[10]),
            "owner_username": row[11], "is_shared": bool(row[12]),
            "health_status": row[13],
            "last_health_check": str(row[14]) if row[14] else None,
            "created_at": str(row[15]) if row[15] else None,
            "updated_at": str(row[16]) if row[16] else None,
        }
    except Exception as e:
        logger.warning("Failed to get virtual source %s: %s", source_id, e)
        return None


def update_virtual_source(source_id: int, owner_username: str, **kwargs) -> dict:
    """Update a virtual source. Only owner can update. Returns status dict."""
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not available"}

    allowed = {
        "source_name", "source_type", "endpoint_url", "auth_config",
        "query_config", "schema_mapping", "default_crs", "spatial_extent",
        "refresh_policy", "enabled", "is_shared",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return {"status": "error", "message": "No valid fields to update"}

    # Re-validate changed fields
    if "source_type" in updates and updates["source_type"] not in VALID_SOURCE_TYPES:
        return {"status": "error", "message": f"source_type must be one of {VALID_SOURCE_TYPES}"}
    if "endpoint_url" in updates and len(updates["endpoint_url"]) > ENDPOINT_URL_MAX:
        return {"status": "error", "message": f"endpoint_url max {ENDPOINT_URL_MAX} chars"}

    try:
        set_clauses = []
        params: dict = {"id": source_id, "owner": owner_username}
        for k, v in updates.items():
            if k == "auth_config":
                set_clauses.append(f"auth_config = CAST(:auth AS jsonb)")
                params["auth"] = _encrypt_dict(v if isinstance(v, dict) else {})
            elif k in ("query_config", "schema_mapping", "spatial_extent"):
                set_clauses.append(f"{k} = CAST(:{k} AS jsonb)")
                params[k] = json.dumps(v) if v is not None else None
            elif k == "enabled":
                set_clauses.append(f"enabled = :enabled")
                params["enabled"] = bool(v)
            elif k == "is_shared":
                set_clauses.append(f"is_shared = :is_shared")
                params["is_shared"] = bool(v)
            else:
                set_clauses.append(f"{k} = :{k}")
                params[k] = v
        set_clauses.append("updated_at = NOW()")

        with engine.connect() as conn:
            result = conn.execute(text(
                f"UPDATE {T_VIRTUAL_SOURCES} SET {', '.join(set_clauses)} "
                f"WHERE id = :id AND owner_username = :owner"
            ), params)
            conn.commit()
        if result.rowcount == 0:
            return {"status": "error", "message": "Source not found or not owned by you"}
        return {"status": "ok"}
    except Exception as e:
        logger.warning("Failed to update virtual source %s: %s", source_id, e)
        return {"status": "error", "message": str(e)}


def delete_virtual_source(source_id: int, owner_username: str) -> dict:
    """Delete a virtual source. Only owner can delete."""
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not available"}
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                f"DELETE FROM {T_VIRTUAL_SOURCES} WHERE id = :id AND owner_username = :owner"
            ), {"id": source_id, "owner": owner_username})
            conn.commit()
        if result.rowcount == 0:
            return {"status": "error", "message": "Source not found or not owned by you"}
        logger.info("Deleted virtual source %s (owner=%s)", source_id, owner_username)
        return {"status": "ok"}
    except Exception as e:
        logger.warning("Failed to delete virtual source %s: %s", source_id, e)
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Auth header builder (delegates to connectors package)
# ---------------------------------------------------------------------------

def _build_auth_headers(auth_config: dict) -> dict:
    """Build HTTP headers from auth_config."""
    from .connectors import build_auth_headers
    return build_auth_headers(auth_config)


# ---------------------------------------------------------------------------
# Unified query dispatcher (registry-based)
# ---------------------------------------------------------------------------

async def query_virtual_source(
    source: dict,
    bbox: list[float] | None = None,
    filter_expr: str | None = None,
    limit: int = 1000,
    extra_params: dict | None = None,
):
    """Query a virtual source by its config dict. Returns GeoDataFrame or list/dict."""
    from .connectors import ConnectorRegistry

    stype = source["source_type"]
    connector = ConnectorRegistry.get(stype)
    if not connector:
        return {"status": "error", "message": f"Unknown source type: {stype}"}

    result = await connector.query(
        endpoint_url=source["endpoint_url"],
        auth_config=source.get("auth_config", {}),
        query_config=source.get("query_config", {}),
        bbox=bbox,
        filter_expr=filter_expr,
        limit=limit,
        extra_params=extra_params,
        target_crs=source.get("default_crs", "EPSG:4326"),
    )

    # Auto-register successful query results into the data catalog
    _auto_register_virtual_result(source, result)

    return result


def _auto_register_virtual_result(source: dict, result) -> None:
    """Register a virtual source query result in the data catalog (non-fatal)."""
    try:
        import geopandas as gpd
        if not isinstance(result, gpd.GeoDataFrame) or result.empty:
            return

        from .data_catalog import auto_register_from_path
        from .user_context import current_user_id

        # Save result as GeoJSON in user sandbox for traceability
        user_id = current_user_id.get() or "anonymous"
        out_dir = os.path.join(os.path.dirname(__file__), "uploads", user_id)
        os.makedirs(out_dir, exist_ok=True)

        import uuid
        src_name = source.get("name", source.get("source_type", "virtual"))
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in src_name)
        fname = f"vs_{safe_name}_{uuid.uuid4().hex[:8]}.geojson"
        out_path = os.path.join(out_dir, fname)

        result.to_file(out_path, driver="GeoJSON")

        auto_register_from_path(
            out_path,
            creation_tool=f"virtual_source:{source.get('source_type', '')}",
            creation_params={"source_name": src_name,
                             "endpoint": source.get("endpoint_url", "")},
        )
    except Exception:
        pass  # non-fatal


# ---------------------------------------------------------------------------
# Schema mapping
# ---------------------------------------------------------------------------

# Canonical geospatial vocabulary for semantic matching
_CANONICAL_FIELDS: dict[str, str] = {
    "geometry": "几何对象 / spatial geometry shape",
    "name": "名称 / feature name label title",
    "population": "人口 / population count inhabitants",
    "area": "面积 / area size square meters hectares",
    "perimeter": "周长 / perimeter boundary length",
    "elevation": "海拔 / elevation altitude height DEM",
    "land_use": "土地利用 / land use cover type category",
    "land_cover": "地表覆盖 / land cover vegetation type",
    "road_type": "道路类型 / road highway street classification",
    "building_type": "建筑类型 / building structure category",
    "water_body": "水体 / water body river lake pond",
    "soil_type": "土壤类型 / soil classification texture",
    "slope": "坡度 / slope gradient inclination degree",
    "aspect": "坡向 / aspect orientation direction",
    "ndvi": "植被指数 / NDVI vegetation index greenness",
    "temperature": "温度 / temperature celsius degree",
    "precipitation": "降水 / precipitation rainfall amount",
    "district": "行政区划 / district county city province region",
    "address": "地址 / address location street",
    "longitude": "经度 / longitude lon lng x coordinate",
    "latitude": "纬度 / latitude lat y coordinate",
    "date": "日期 / date time datetime timestamp",
    "id": "标识符 / identifier code unique key",
    "class": "分类 / class category classification type",
    "value": "数值 / value amount measurement",
    "density": "密度 / density concentration per unit",
    "distance": "距离 / distance length meters kilometers",
    "boundary": "边界 / boundary border outline",
    "centroid": "质心 / centroid center point",
    "buffer": "缓冲区 / buffer zone radius",
    "zoning": "分区规划 / zoning planning regulation",
}

_EMBEDDING_MODEL = "text-embedding-004"
_SEMANTIC_THRESHOLD = 0.72
_schema_embedding_cache: dict[str, list[float]] = {}


def _get_schema_embeddings(texts: list[str]) -> list[list[float]]:
    """Get embedding vectors for schema field names. Cached."""
    uncached = [t for t in texts if t not in _schema_embedding_cache]
    if uncached:
        try:
            from google import genai
            client = genai.Client()
            response = client.models.embed_content(
                model=_EMBEDDING_MODEL,
                contents=uncached,
            )
            for txt, emb in zip(uncached, response.embeddings):
                _schema_embedding_cache[txt] = emb.values
        except Exception as e:
            logger.debug("Schema embedding API failed: %s — skipping semantic mapping", e)
            return []
    return [_schema_embedding_cache.get(t, []) for t in texts]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x ** 2 for x in a) ** 0.5
    norm_b = sum(x ** 2 for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def infer_schema_mapping(columns: list[str], threshold: float = _SEMANTIC_THRESHOLD) -> dict[str, str]:
    """Infer column-to-canonical mapping via embedding similarity.

    For each remote column name, find the best matching canonical field
    if similarity exceeds threshold.

    Returns: {"remote_col": "canonical_name", ...}
    """
    if not columns:
        return {}

    canonical_names = list(_CANONICAL_FIELDS.keys())
    canonical_descs = list(_CANONICAL_FIELDS.values())

    # Build embedding texts: column names enriched with lowercase variants
    col_texts = [col.replace("_", " ").lower() for col in columns]
    all_texts = col_texts + canonical_descs

    embeddings = _get_schema_embeddings(all_texts)
    if not embeddings or len(embeddings) < len(all_texts):
        return {}

    col_embs = embeddings[:len(columns)]
    canon_embs = embeddings[len(columns):]

    mapping = {}
    for i, col in enumerate(columns):
        if not col_embs[i]:
            continue
        best_score = 0.0
        best_name = ""
        for j, cname in enumerate(canonical_names):
            if not canon_embs[j]:
                continue
            score = _cosine_similarity(col_embs[i], canon_embs[j])
            if score > best_score:
                best_score = score
                best_name = cname
        if best_score >= threshold and best_name != col:
            mapping[col] = best_name

    return mapping


def apply_schema_mapping(gdf, schema_mapping: dict, auto_infer: bool = False):
    """Rename GeoDataFrame columns per schema_mapping config.

    schema_mapping: {"original_col": "target_col", ...}
    auto_infer: if True and schema_mapping is empty, attempt semantic inference.
    """
    if not hasattr(gdf, "rename"):
        return gdf

    if not schema_mapping and auto_infer:
        cols = [c for c in gdf.columns if c != "geometry"]
        schema_mapping = infer_schema_mapping(cols)

    if not schema_mapping:
        return gdf

    rename_map = {k: v for k, v in schema_mapping.items() if k in gdf.columns}
    if rename_map:
        gdf = gdf.rename(columns=rename_map)
    return gdf


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

async def check_source_health(source_id: int, owner_username: str) -> dict:
    """Test connectivity to a virtual source and update health_status."""
    source = get_virtual_source(source_id, owner_username)
    if not source:
        return {"status": "error", "message": "Source not found"}

    from .connectors import ConnectorRegistry

    stype = source["source_type"]
    url = source["endpoint_url"]
    auth = source.get("auth_config", {})

    connector = ConnectorRegistry.get(stype)
    if connector:
        result = await connector.health_check(url, auth)
        health = result.get("health", "error")
        message = result.get("message", "")
    else:
        health = "error"
        message = f"Unknown source type: {stype}"

    # Persist health status
    engine = get_engine()
    if engine:
        try:
            with engine.connect() as conn:
                conn.execute(text(
                    f"UPDATE {T_VIRTUAL_SOURCES} SET health_status = :h, "
                    f"last_health_check = NOW(), updated_at = NOW() WHERE id = :id"
                ), {"h": health, "id": source_id})
                conn.commit()
        except Exception as e:
            logger.warning("Failed to update health status: %s", e)

    return {"status": "ok", "health": health, "message": message}
