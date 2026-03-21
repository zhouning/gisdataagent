"""
Virtual Data Sources — remote WFS/STAC/OGC API/custom API connectors (v13.0).

Users register external geospatial data services and query them on demand.
Credentials are Fernet-encrypted at rest. Connectors return GeoDataFrames
(WFS/OGC) or structured dicts (STAC/custom API) with automatic CRS alignment.

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

VALID_SOURCE_TYPES = {"wfs", "stac", "ogc_api", "custom_api"}
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
# Auth header builder
# ---------------------------------------------------------------------------

def _build_auth_headers(auth_config: dict) -> dict:
    """Build HTTP headers from auth_config."""
    if not auth_config:
        return {}
    atype = auth_config.get("type", "none")
    if atype == "bearer":
        return {"Authorization": f"Bearer {auth_config.get('token', '')}"}
    if atype == "basic":
        import base64 as b64
        cred = b64.b64encode(
            f"{auth_config.get('username', '')}:{auth_config.get('password', '')}".encode()
        ).decode()
        return {"Authorization": f"Basic {cred}"}
    if atype == "apikey":
        header = auth_config.get("header", "X-API-Key")
        return {header: auth_config.get("key", "")}
    return {}


# ---------------------------------------------------------------------------
# Connectors
# ---------------------------------------------------------------------------

_HTTP_TIMEOUT = 30


async def query_wfs(
    endpoint_url: str,
    auth_config: dict,
    query_config: dict,
    bbox: list[float] | None = None,
    cql_filter: str | None = None,
    max_features: int = 1000,
    target_crs: str | None = None,
):
    """Query a WFS service and return a GeoDataFrame.

    Parameters
    ----------
    endpoint_url : WFS base URL
    auth_config  : decrypted auth config dict
    query_config : {feature_type, version, max_features, ...}
    bbox         : [minx, miny, maxx, maxy] in EPSG:4326
    cql_filter   : optional CQL filter string
    max_features : feature limit
    target_crs   : target CRS for auto-alignment (e.g. "EPSG:4326")
    """
    import httpx
    import geopandas as gpd

    feature_type = query_config.get("feature_type", "")
    version = query_config.get("version", "2.0.0")
    max_feat = query_config.get("max_features", max_features)

    params = {
        "service": "WFS",
        "request": "GetFeature",
        "typeName": feature_type,
        "version": version,
        "outputFormat": "application/json",
        "count": str(min(max_feat, max_features)),
    }
    if bbox:
        params["bbox"] = ",".join(str(v) for v in bbox)
    if cql_filter:
        params["CQL_FILTER"] = cql_filter

    headers = _build_auth_headers(auth_config)

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(endpoint_url, params=params, headers=headers)
        resp.raise_for_status()

    data = resp.json()
    if not data.get("features"):
        return gpd.GeoDataFrame()

    gdf = gpd.GeoDataFrame.from_features(data["features"], crs="EPSG:4326")

    # CRS from response
    crs_info = data.get("crs", {}).get("properties", {}).get("name")
    if crs_info:
        try:
            gdf = gdf.set_crs(crs_info, allow_override=True)
        except Exception:
            pass

    # Auto-align CRS
    if target_crs and gdf.crs and str(gdf.crs) != target_crs:
        gdf = gdf.to_crs(target_crs)

    return gdf


async def search_stac(
    endpoint_url: str,
    auth_config: dict,
    query_config: dict,
    bbox: list[float] | None = None,
    datetime_range: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Search a STAC catalog and return items.

    Parameters
    ----------
    endpoint_url   : STAC API base URL (e.g. https://earth-search.aws.element84.com/v1)
    auth_config    : decrypted auth config dict
    query_config   : {collection_id, datetime_range, ...}
    bbox           : [minx, miny, maxx, maxy]
    datetime_range : ISO 8601 range (e.g. "2024-01-01/2024-12-31")
    limit          : max items to return
    """
    import httpx

    search_url = endpoint_url.rstrip("/") + "/search"
    headers = _build_auth_headers(auth_config)
    headers["Content-Type"] = "application/json"

    body: dict = {"limit": min(limit, 100)}
    collection_id = query_config.get("collection_id")
    if collection_id:
        body["collections"] = [collection_id]
    if bbox:
        body["bbox"] = bbox
    dt = datetime_range or query_config.get("datetime_range")
    if dt:
        body["datetime"] = dt

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(search_url, json=body, headers=headers)
        resp.raise_for_status()

    data = resp.json()
    items = data.get("features", [])
    # Flatten useful fields
    results = []
    for item in items:
        props = item.get("properties", {})
        assets = item.get("assets", {})
        results.append({
            "id": item.get("id"),
            "datetime": props.get("datetime"),
            "bbox": item.get("bbox"),
            "collection": item.get("collection"),
            "cloud_cover": props.get("eo:cloud_cover"),
            "thumbnail": assets.get("thumbnail", {}).get("href"),
            "data_href": (assets.get("data", {}).get("href")
                          or assets.get("visual", {}).get("href")),
            "properties": props,
        })
    return results


async def query_api(
    endpoint_url: str,
    auth_config: dict,
    query_config: dict,
    params: dict | None = None,
) -> dict:
    """Query a custom REST API and return parsed response.

    Parameters
    ----------
    endpoint_url : API endpoint URL (may contain {placeholders})
    auth_config  : decrypted auth config dict
    query_config : {method, response_path, params, body, ...}
    params       : runtime parameter overrides
    """
    import httpx

    method = query_config.get("method", "GET").upper()
    response_path = query_config.get("response_path", "")
    default_params = query_config.get("params", {})
    body = query_config.get("body")

    merged_params = {**default_params, **(params or {})}

    # Template URL placeholders
    url = endpoint_url
    try:
        url = url.format_map(merged_params)
    except (KeyError, ValueError):
        pass

    headers = _build_auth_headers(auth_config)

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        if method in ("POST", "PUT", "PATCH") and body:
            headers["Content-Type"] = "application/json"
            resp = await client.request(method, url, json=body, headers=headers)
        else:
            resp = await client.request(method, url, params=merged_params, headers=headers)
        resp.raise_for_status()

    data = resp.json()

    # Extract nested path (e.g. "data.features")
    if response_path:
        for key in response_path.split("."):
            if isinstance(data, dict):
                data = data.get(key, data)
            else:
                break

    return data if isinstance(data, dict) else {"results": data}


async def query_ogc_api(
    endpoint_url: str,
    auth_config: dict,
    query_config: dict,
    bbox: list[float] | None = None,
    limit: int = 1000,
    target_crs: str | None = None,
):
    """Query an OGC API Features service and return a GeoDataFrame."""
    import httpx
    import geopandas as gpd

    collection = query_config.get("collection", "")
    items_url = f"{endpoint_url.rstrip('/')}/collections/{collection}/items"

    params = {"f": "json", "limit": str(min(limit, query_config.get("limit", 1000)))}
    if bbox:
        params["bbox"] = ",".join(str(v) for v in bbox)

    headers = _build_auth_headers(auth_config)

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(items_url, params=params, headers=headers)
        resp.raise_for_status()

    data = resp.json()
    features = data.get("features", [])
    if not features:
        return gpd.GeoDataFrame()

    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    if target_crs and gdf.crs and str(gdf.crs) != target_crs:
        gdf = gdf.to_crs(target_crs)
    return gdf


# ---------------------------------------------------------------------------
# Unified query dispatcher
# ---------------------------------------------------------------------------

async def query_virtual_source(
    source: dict,
    bbox: list[float] | None = None,
    filter_expr: str | None = None,
    limit: int = 1000,
    extra_params: dict | None = None,
):
    """Query a virtual source by its config dict. Returns GeoDataFrame or list/dict."""
    stype = source["source_type"]
    url = source["endpoint_url"]
    auth = source.get("auth_config", {})
    qcfg = source.get("query_config", {})
    target_crs = source.get("default_crs", "EPSG:4326")

    if stype == "wfs":
        return await query_wfs(url, auth, qcfg, bbox=bbox,
                               cql_filter=filter_expr, max_features=limit,
                               target_crs=target_crs)
    elif stype == "stac":
        return await search_stac(url, auth, qcfg, bbox=bbox,
                                 datetime_range=filter_expr, limit=limit)
    elif stype == "ogc_api":
        return await query_ogc_api(url, auth, qcfg, bbox=bbox,
                                   limit=limit, target_crs=target_crs)
    elif stype == "custom_api":
        return await query_api(url, auth, qcfg, params=extra_params)
    else:
        return {"status": "error", "message": f"Unknown source type: {stype}"}


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

    import httpx
    url = source["endpoint_url"]
    auth = source.get("auth_config", {})
    headers = _build_auth_headers(auth)
    health = "healthy"
    message = "OK"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            stype = source["source_type"]
            if stype == "wfs":
                resp = await client.get(url, params={
                    "service": "WFS", "request": "GetCapabilities"
                }, headers=headers)
            elif stype == "stac":
                resp = await client.get(url, headers=headers)
            elif stype == "ogc_api":
                resp = await client.get(url, headers=headers)
            else:
                resp = await client.request("HEAD", url, headers=headers)
            resp.raise_for_status()
    except httpx.TimeoutException:
        health = "timeout"
        message = "Connection timed out"
    except Exception as e:
        health = "error"
        message = str(e)[:200]

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
