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
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import make_url

from .db_engine import get_engine
from .database_tools import T_VIRTUAL_SOURCES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_SOURCE_TYPES = {
    "wfs",
    "stac",
    "ogc_api",
    "custom_api",
    "wms",
    "arcgis_rest",
    "database",
    "object_storage",
}
VALID_REFRESH_POLICIES = {"on_demand", "interval:5m", "interval:30m", "interval:1h", "realtime"}
VALID_AUTH_TYPES = {"bearer", "basic", "apikey", "none"}
SOURCE_NAME_MAX = 200
ENDPOINT_URL_MAX = 1000
MAX_SOURCES_PER_USER = 50
_SECRET_FIELDS = frozenset(
    {
        "access_key_id",
        "auth_config",
        "aws_access_key_id",
        "aws_secret_access_key",
        "key",
        "password",
        "secret",
        "secret_access_key",
        "session_token",
        "token",
    }
)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# ---------------------------------------------------------------------------
# Fernet encryption (keyed from CHAINLIT_AUTH_SECRET, distinct salt)
# ---------------------------------------------------------------------------

_FERNET_KEY: Optional[bytes] = None
_fernet_lock = threading.Lock()


def _secret_from_file(path_value: str) -> str:
    """Read one dotenv-style secret without mutating the process environment."""

    path = Path(path_value).expanduser()
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            key, separator, value = line.partition("=")
            if not separator or key.strip() not in {
                "GDA_VSOURCE_ENCRYPTION_SECRET",
                "CHAINLIT_AUTH_SECRET",
            }:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            if value:
                return value
    except (OSError, UnicodeError):
        return ""
    return ""


def _vsource_encryption_secret() -> str:
    """Resolve the source-encryption key with an explicit local override.

    ``CHAINLIT_AUTH_SECRET`` remains the production default.  A separate
    ``GDA_VSOURCE_SECRET_FILE`` or ``GDA_VSOURCE_ENCRYPTION_SECRET`` is useful
    for a local app whose Chainlit secret was rotated independently; it is
    explicit and never silently replaces an injected Chainlit secret.
    """

    direct = os.environ.get("GDA_VSOURCE_ENCRYPTION_SECRET", "").strip()
    if direct:
        return direct
    configured_file = os.environ.get("GDA_VSOURCE_SECRET_FILE", "").strip()
    if configured_file:
        from_file = _secret_from_file(configured_file)
        if from_file:
            return from_file
    return os.environ.get("CHAINLIT_AUTH_SECRET", "").strip()


def _get_fernet():
    """Return a Fernet instance keyed from the configured source secret."""
    global _FERNET_KEY
    if _FERNET_KEY is not None:
        from cryptography.fernet import Fernet

        return Fernet(_FERNET_KEY)
    with _fernet_lock:
        # Double-check after acquiring lock
        if _FERNET_KEY is not None:
            from cryptography.fernet import Fernet

            return Fernet(_FERNET_KEY)
        secret = _vsource_encryption_secret()
        if not secret:
            return None
        _FERNET_KEY = base64.urlsafe_b64encode(
            hashlib.pbkdf2_hmac("sha256", secret.encode(), b"vsource-salt", 100_000, dklen=32)
        )
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


def _decrypt_dict_with_status(val) -> tuple[dict, bool]:
    """Decrypt an auth document and retain whether encrypted credentials loaded."""

    if isinstance(val, str):
        try:
            val = json.loads(val) if val else {}
        except json.JSONDecodeError:
            return {}, False
    if not isinstance(val, dict):
        return {}, False
    if "_enc" in val:
        f = _get_fernet()
        if f:
            try:
                result = json.loads(f.decrypt(val["_enc"].encode()).decode())
                return (result, True) if isinstance(result, dict) else ({}, False)
            except Exception:
                pass
        return {}, False
    return val, True


def _decrypt_dict(val) -> dict:
    """Decrypt from DB value (dict or str), preserving the legacy API."""

    result, _loaded = _decrypt_dict_with_status(val)
    return result


# ---------------------------------------------------------------------------
# Table initialization
# ---------------------------------------------------------------------------


def ensure_virtual_sources_table():
    """Legacy bootstrap for the original virtual-source table only."""
    engine = get_engine()
    if not engine:
        print("[VirtualSources] WARNING: Database not configured. Virtual sources disabled.")
        return
    try:
        sql_path = os.path.join(
            os.path.dirname(__file__),
            "migrations",
            "012_virtual_sources.sql",
        )
        with open(sql_path, encoding="utf-8") as file_handle:
            ddl = file_handle.read()
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
    if stype == "database":
        try:
            parsed = make_url(url)
        except Exception:
            return "database endpoint_url must be a valid SQLAlchemy URL"
        if parsed.get_backend_name() != "postgresql":
            return "governed database virtual sources currently require PostgreSQL"
        if parsed.username is not None or parsed.password is not None:
            return "database endpoint_url must not embed credentials"
        if not parsed.database:
            return "database endpoint_url must include a database name"
        try:
            _normalize_database_query_config(data.get("query_config") or {})
        except ValueError as exc:
            return str(exc)
    return None


def _normalize_database_query_config(query_config: dict) -> dict:
    if not isinstance(query_config, dict):
        raise ValueError("database query_config must be a JSON object")
    normalized = dict(query_config)
    raw_schemas = normalized.get("allowed_schemas") or []
    if isinstance(raw_schemas, str):
        raw_schemas = [raw_schemas]
    schemas = [str(value).strip() for value in raw_schemas if str(value).strip()]
    schemas = list(dict.fromkeys(schemas))
    table = str(normalized.get("table") or "").strip()
    if not schemas and table:
        schemas = [table.split(".", 1)[0] if "." in table else "public"]
    if any(not _IDENTIFIER_RE.fullmatch(schema) for schema in schemas):
        raise ValueError("database allowed_schemas contains an invalid identifier")
    normalized["allowed_schemas"] = schemas
    normalized.setdefault("discovery_mode", "metadata_only")
    normalized.setdefault("discovery_limit", 5000)
    normalized.setdefault("statement_timeout_ms", 15_000)
    normalized.setdefault("lock_timeout_ms", 2_000)
    normalized.setdefault("max_rows", 1000)

    from .source_connector_governance import DatabaseSourceConfig

    try:
        validated = DatabaseSourceConfig.model_validate(normalized)
    except Exception as exc:
        raise ValueError(f"invalid governed database query_config: {exc}") from exc
    return validated.model_dump(mode="json", exclude_none=True)


def _secret_free_source_documents(
    *,
    source_name: str,
    source_type: str,
    endpoint_url: str,
    owner_username: str,
    auth_config: dict,
    query_config: dict,
) -> tuple[dict, dict]:
    identity = hashlib.sha256(
        f"{owner_username}\0{source_name}\0{source_type}".encode("utf-8")
    ).hexdigest()[:24]
    credential_reference = {
        "credential_id": f"virtual-source:{identity}",
        "version": 1,
        "auth_type": str(auth_config.get("type") or "none"),
        "provider": "encrypted-agent-control-plane",
    }
    source_definition = {
        "schema": "gda.virtual-source-definition.v1",
        "source_name": source_name,
        "source_type": source_type,
        "endpoint_url": endpoint_url,
        "owner_ref": owner_username,
        "credential_reference": credential_reference,
        "query_config": query_config,
        "read_only": source_type == "database",
    }
    return credential_reference, source_definition


def _json_value(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _credentials_require_encryption(auth_config: dict) -> bool:
    return bool(
        auth_config
        and auth_config.get("type", "none") != "none"
        and any(auth_config.get(key) for key in _SECRET_FIELDS)
    )


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
    auth_config = auth_config or {}
    query_config = query_config or {}
    if source_type == "database":
        try:
            query_config = _normalize_database_query_config(query_config)
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}
    if _credentials_require_encryption(auth_config) and _get_fernet() is None:
        return {
            "status": "error",
            "message": "Control-plane credential encryption is not configured",
        }
    data = {
        "source_name": source_name,
        "source_type": source_type,
        "endpoint_url": endpoint_url,
        "auth_config": auth_config,
        "query_config": query_config,
    }
    err = _validate_source(data)
    if err:
        return {"status": "error", "message": err}

    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not available"}

    try:
        credential_reference, source_definition = _secret_free_source_documents(
            source_name=source_name,
            source_type=source_type,
            endpoint_url=endpoint_url,
            owner_username=owner_username,
            auth_config=auth_config,
            query_config=query_config,
        )
        # Check per-user limit
        with engine.connect() as conn:
            cnt = conn.execute(
                text(f"SELECT COUNT(*) FROM {T_VIRTUAL_SOURCES} WHERE owner_username = :u"),
                {"u": owner_username},
            ).scalar()
            if cnt and cnt >= MAX_SOURCES_PER_USER:
                return {
                    "status": "error",
                    "message": f"Max {MAX_SOURCES_PER_USER} sources per user",
                }

            conn.execute(
                text(f"""
                INSERT INTO {T_VIRTUAL_SOURCES}
                    (source_name, source_type, endpoint_url, auth_config,
                     query_config, schema_mapping, default_crs, spatial_extent,
                     refresh_policy, owner_username, is_shared,
                     credential_reference, source_definition)
                VALUES
                    (:name, :stype, :url, CAST(:auth AS jsonb),
                     CAST(:qcfg AS jsonb), CAST(:smap AS jsonb), :crs, CAST(:extent AS jsonb),
                     :refresh, :owner, :shared,
                     CAST(:credential_reference AS jsonb), CAST(:source_definition AS jsonb))
            """),
                {
                    "name": source_name,
                    "stype": source_type,
                    "url": endpoint_url,
                    "auth": _encrypt_dict(auth_config),
                    "qcfg": json.dumps(query_config),
                    "smap": json.dumps(schema_mapping or {}),
                    "crs": default_crs,
                    "extent": json.dumps(spatial_extent) if spatial_extent else None,
                    "refresh": refresh_policy,
                    "owner": owner_username,
                    "shared": is_shared,
                    "credential_reference": json.dumps(credential_reference),
                    "source_definition": json.dumps(source_definition),
                },
            )
            row = conn.execute(
                text(
                    f"SELECT id FROM {T_VIRTUAL_SOURCES} WHERE source_name = :n AND owner_username = :u"
                ),
                {"n": source_name, "u": owner_username},
            ).fetchone()
            conn.commit()
        sid = row[0] if row else None
        logger.info(
            "Created virtual source '%s' (type=%s, owner=%s)",
            source_name,
            source_type,
            owner_username,
        )
        return {"status": "ok", "id": sid}
    except Exception as e:
        if "uq_vsource" in str(e).lower() or "unique" in str(e).lower():
            return {
                "status": "error",
                "message": f"Source '{source_name}' already exists for this user",
            }
        logger.warning("Failed to create virtual source: %s", e)
        return {"status": "error", "message": str(e)}


def list_virtual_sources(owner_username: str, include_shared: bool = True) -> list[dict]:
    """List virtual sources visible to a user."""
    engine = get_engine()
    if not engine:
        return []
    try:
        if include_shared:
            q = (
                f"SELECT id, source_name, source_type, endpoint_url, query_config, "
                f"default_crs, spatial_extent, refresh_policy, enabled, "
                f"owner_username, is_shared, health_status, created_at, updated_at, "
                f"discovery_status, discovery_fingerprint, last_discovery_at "
                f"FROM {T_VIRTUAL_SOURCES} "
                f"WHERE owner_username = :u OR is_shared = TRUE "
                f"ORDER BY source_name"
            )
        else:
            q = (
                f"SELECT id, source_name, source_type, endpoint_url, query_config, "
                f"default_crs, spatial_extent, refresh_policy, enabled, "
                f"owner_username, is_shared, health_status, created_at, updated_at, "
                f"discovery_status, discovery_fingerprint, last_discovery_at "
                f"FROM {T_VIRTUAL_SOURCES} "
                f"WHERE owner_username = :u ORDER BY source_name"
            )
        with engine.connect() as conn:
            rows = conn.execute(text(q), {"u": owner_username}).fetchall()
        results = []
        for r in rows:
            qcfg = r[4] if isinstance(r[4], dict) else (json.loads(r[4]) if r[4] else {})
            extent = r[6] if isinstance(r[6], dict) else (json.loads(r[6]) if r[6] else None)
            results.append(
                {
                    "id": r[0],
                    "source_name": r[1],
                    "source_type": r[2],
                    "endpoint_url": r[3],
                    "query_config": qcfg,
                    "default_crs": r[5],
                    "spatial_extent": extent,
                    "refresh_policy": r[7],
                    "enabled": bool(r[8]),
                    "owner_username": r[9],
                    "is_shared": bool(r[10]),
                    "health_status": r[11],
                    "created_at": str(r[12]) if r[12] else None,
                    "updated_at": str(r[13]) if r[13] else None,
                    "discovery_status": r[14],
                    "discovery_fingerprint": r[15],
                    "last_discovery_at": str(r[16]) if r[16] else None,
                }
            )
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
            row = conn.execute(
                text(
                    f"SELECT id, source_name, source_type, endpoint_url, auth_config, "
                    f"query_config, schema_mapping, default_crs, spatial_extent, "
                    f"refresh_policy, enabled, owner_username, is_shared, "
                    f"health_status, last_health_check, created_at, updated_at, "
                    f"credential_reference, source_definition, discovery_snapshot, "
                    f"discovery_fingerprint, profile_snapshot, profile_fingerprint, "
                    f"last_discovery_at, discovery_status, discovery_error "
                    f"FROM {T_VIRTUAL_SOURCES} "
                    f"WHERE id = :id AND (owner_username = :u OR is_shared = TRUE)"
                ),
                {"id": source_id, "u": owner_username},
            ).fetchone()
        if not row:
            return None
        qcfg = row[5] if isinstance(row[5], dict) else (json.loads(row[5]) if row[5] else {})
        smap = row[6] if isinstance(row[6], dict) else (json.loads(row[6]) if row[6] else {})
        extent = row[8] if isinstance(row[8], dict) else (json.loads(row[8]) if row[8] else None)
        auth_config, credentials_loaded = _decrypt_dict_with_status(row[4])
        encrypted_credentials = False
        raw_auth = row[4]
        if isinstance(raw_auth, str):
            try:
                raw_auth = json.loads(raw_auth) if raw_auth else {}
            except json.JSONDecodeError:
                raw_auth = {}
        if isinstance(raw_auth, dict):
            encrypted_credentials = "_enc" in raw_auth
        return {
            "id": row[0],
            "source_name": row[1],
            "source_type": row[2],
            "endpoint_url": row[3],
            "auth_config": auth_config,
            "credential_status": (
                "available" if credentials_loaded or not encrypted_credentials else "unavailable"
            ),
            "credential_error": (
                None
                if credentials_loaded or not encrypted_credentials
                else "virtual_source_credentials_unavailable"
            ),
            "query_config": qcfg,
            "schema_mapping": smap,
            "default_crs": row[7],
            "spatial_extent": extent,
            "refresh_policy": row[9],
            "enabled": bool(row[10]),
            "owner_username": row[11],
            "is_shared": bool(row[12]),
            "health_status": row[13],
            "last_health_check": str(row[14]) if row[14] else None,
            "created_at": str(row[15]) if row[15] else None,
            "updated_at": str(row[16]) if row[16] else None,
            "credential_reference": _json_value(row[17], {}),
            "source_definition": _json_value(row[18], {}),
            "discovery_snapshot": _json_value(row[19], None),
            "discovery_fingerprint": row[20],
            "profile_snapshot": _json_value(row[21], None),
            "profile_fingerprint": row[22],
            "last_discovery_at": str(row[23]) if row[23] else None,
            "discovery_status": row[24],
            "discovery_error": row[25],
        }
    except Exception as e:
        logger.warning("Failed to get virtual source %s: %s", source_id, e)
        return None


def get_virtual_source_discovery(
    source_id: int,
    owner_username: str,
) -> dict | None:
    """Return persisted discovery evidence without loading source credentials."""
    engine = get_engine()
    if not engine:
        return None
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    f"SELECT id, source_name, source_type, owner_username, "
                    f"discovery_snapshot, discovery_fingerprint, profile_snapshot, "
                    f"profile_fingerprint, last_discovery_at, discovery_status, "
                    f"discovery_error FROM {T_VIRTUAL_SOURCES} "
                    f"WHERE id = :id AND (owner_username = :u OR is_shared = TRUE)"
                ),
                {"id": source_id, "u": owner_username},
            ).fetchone()
        if not row:
            return None
        return {
            "source_id": row[0],
            "source_name": row[1],
            "source_type": row[2],
            "owner_username": row[3],
            "discovery_snapshot": _json_value(row[4], None),
            "discovery_fingerprint": row[5],
            "profile_snapshot": _json_value(row[6], None),
            "profile_fingerprint": row[7],
            "last_discovery_at": str(row[8]) if row[8] else None,
            "discovery_status": row[9],
            "discovery_error": row[10],
        }
    except Exception as e:
        logger.warning(
            "Failed to get virtual source discovery %s: %s",
            source_id,
            e,
        )
        return None


def update_virtual_source(source_id: int, owner_username: str, **kwargs) -> dict:
    """Update a virtual source. Only owner can update. Returns status dict."""
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not available"}

    allowed = {
        "source_name",
        "source_type",
        "endpoint_url",
        "auth_config",
        "query_config",
        "schema_mapping",
        "default_crs",
        "spatial_extent",
        "refresh_policy",
        "enabled",
        "is_shared",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return {"status": "error", "message": "No valid fields to update"}

    # Re-validate changed fields
    if "source_type" in updates and updates["source_type"] not in VALID_SOURCE_TYPES:
        return {"status": "error", "message": f"source_type must be one of {VALID_SOURCE_TYPES}"}
    if "endpoint_url" in updates and len(updates["endpoint_url"]) > ENDPOINT_URL_MAX:
        return {"status": "error", "message": f"endpoint_url max {ENDPOINT_URL_MAX} chars"}

    governed_fields = {"source_type", "endpoint_url", "auth_config", "query_config"}
    if governed_fields.intersection(updates):
        existing = get_virtual_source(source_id, owner_username)
        if not existing or existing.get("owner_username") != owner_username:
            return {"status": "error", "message": "Source not found or not owned by you"}
        merged = {
            "source_name": updates.get("source_name", existing["source_name"]),
            "source_type": updates.get("source_type", existing["source_type"]),
            "endpoint_url": updates.get("endpoint_url", existing["endpoint_url"]),
            "auth_config": updates.get("auth_config", existing.get("auth_config") or {}),
            "query_config": updates.get("query_config", existing.get("query_config") or {}),
        }
        if _credentials_require_encryption(merged["auth_config"]) and _get_fernet() is None:
            return {
                "status": "error",
                "message": "Control-plane credential encryption is not configured",
            }
        if merged["source_type"] == "database":
            try:
                merged["query_config"] = _normalize_database_query_config(merged["query_config"])
            except ValueError as exc:
                return {"status": "error", "message": str(exc)}
            updates["query_config"] = merged["query_config"]
        validation_error = _validate_source(merged)
        if validation_error:
            return {"status": "error", "message": validation_error}
        credential_reference, source_definition = _secret_free_source_documents(
            source_name=merged["source_name"],
            source_type=merged["source_type"],
            endpoint_url=merged["endpoint_url"],
            owner_username=owner_username,
            auth_config=merged["auth_config"],
            query_config=merged["query_config"],
        )
        previous_reference = existing.get("credential_reference") or {}
        if "auth_config" in updates:
            credential_reference["version"] = int(previous_reference.get("version") or 0) + 1
        else:
            credential_reference["version"] = int(previous_reference.get("version") or 1)
        source_definition["credential_reference"] = credential_reference
        updates["credential_reference"] = credential_reference
        updates["source_definition"] = source_definition

    try:
        set_clauses = []
        params: dict = {"id": source_id, "owner": owner_username}
        for k, v in updates.items():
            if k == "auth_config":
                set_clauses.append(f"auth_config = CAST(:auth AS jsonb)")
                params["auth"] = _encrypt_dict(v if isinstance(v, dict) else {})
            elif k in (
                "query_config",
                "schema_mapping",
                "spatial_extent",
                "credential_reference",
                "source_definition",
            ):
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
            result = conn.execute(
                text(
                    f"UPDATE {T_VIRTUAL_SOURCES} SET {', '.join(set_clauses)} "
                    f"WHERE id = :id AND owner_username = :owner"
                ),
                params,
            )
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
            result = conn.execute(
                text(f"DELETE FROM {T_VIRTUAL_SOURCES} WHERE id = :id AND owner_username = :owner"),
                {"id": source_id, "owner": owner_username},
            )
            conn.commit()
        if result.rowcount == 0:
            return {"status": "error", "message": "Source not found or not owned by you"}
        logger.info("Deleted virtual source %s (owner=%s)", source_id, owner_username)
        return {"status": "ok"}
    except Exception as e:
        logger.warning("Failed to delete virtual source %s: %s", source_id, e)
        return {"status": "error", "message": str(e)}


def _redact_runtime_message(message: str, auth_config: dict) -> str:
    redacted = str(message)
    for key, value in (auth_config or {}).items():
        if key.casefold() in _SECRET_FIELDS and isinstance(value, str) and value:
            redacted = redacted.replace(value, "[REDACTED]")
    redacted = re.sub(r"(://[^:/\s]+:)[^@/\s]+@", r"\1[REDACTED]@", redacted)
    return redacted[:500]


def _discovery_documents(source: dict, raw: dict) -> tuple[dict, str, dict, str]:
    resources = []
    for layer in raw.get("layers") or []:
        columns = [
            {
                "name": str(column.get("name") or ""),
                "type": str(column.get("type") or "unknown"),
                "nullable": bool(column.get("nullable", True)),
            }
            for column in layer.get("columns") or []
            if column.get("name")
        ]
        columns.sort(key=lambda item: item["name"])
        foreign_keys = [
            {
                "name": str(item["name"]) if item.get("name") else None,
                "columns": sorted(str(value) for value in item.get("columns") or []),
                "referred_schema": str(item.get("referred_schema") or ""),
                "referred_table": str(item.get("referred_table") or ""),
                "referred_columns": sorted(
                    str(value) for value in item.get("referred_columns") or []
                ),
            }
            for item in layer.get("foreign_keys") or []
        ]
        foreign_keys.sort(
            key=lambda item: (
                item["referred_schema"],
                item["referred_table"],
                item["name"] or "",
            )
        )
        indexes = [
            {
                "name": str(item["name"]) if item.get("name") else None,
                "columns": sorted(str(value) for value in item.get("columns") or []),
                "unique": bool(item.get("unique", False)),
            }
            for item in layer.get("indexes") or []
        ]
        indexes.sort(key=lambda item: (item["name"] or "", item["columns"]))
        estimated = layer.get("estimated_record_count")
        qualified_name = str(layer.get("name") or "unnamed")
        if "." in qualified_name:
            resource_schema, resource_name = qualified_name.split(".", 1)
        else:
            resource_schema, resource_name = "public", qualified_name
        resources.append(
            {
                "name": resource_name,
                "schema": resource_schema,
                "qualified_name": qualified_name,
                "resource_type": str(layer.get("type") or "unknown"),
                "columns": columns,
                "primary_key": sorted(str(value) for value in layer.get("primary_key") or []),
                "foreign_keys": foreign_keys,
                "indexes": indexes,
                "estimated_record_count": int(estimated) if estimated is not None else None,
                "comment": str(layer["comment"])[:4000] if layer.get("comment") else None,
            }
        )
    resources.sort(key=lambda item: item["name"])
    query_config = source.get("query_config") or {}
    snapshot = {
        "schema": "gda.virtual-source-discovery.v1",
        "source_id": int(source["id"]),
        "provider": str(raw.get("provider") or raw.get("service") or "unknown"),
        "provider_version": str(raw.get("provider_version") or "unknown"),
        "spatial_version": str(raw.get("spatial_version") or "not_applicable"),
        "database_name": str(raw.get("database_name") or "unknown"),
        "discovery_scope": str(raw.get("discovery_scope") or "registered_source"),
        "authorized_schemas": list(query_config.get("allowed_schemas") or []),
        "schema_access": raw.get("schema_access") or {},
        "truncated": bool(raw.get("truncated", False)),
        "resource_count": len(resources),
        "reported_resource_count": int(raw.get("table_count") or len(resources)),
        "resources": resources,
        "contains_source_rows": False,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    profile = {
        "schema": "gda.virtual-source-metadata-profile.v1",
        "source_id": int(source["id"]),
        "metadata_only": True,
        "resource_count": len(resources),
        "field_count": sum(len(item["columns"]) for item in resources),
        "geometry_resource_count": sum(
            any("geometry" in column["type"].casefold() for column in item["columns"])
            for item in resources
        ),
        "relationship_count": sum(len(item["foreign_keys"]) for item in resources),
        "index_count": sum(len(item["indexes"]) for item in resources),
        "estimated_record_count": sum(item["estimated_record_count"] or 0 for item in resources),
        "contains_source_rows": False,
    }
    profile_fingerprint = hashlib.sha256(
        json.dumps(
            profile,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return snapshot, fingerprint, profile, profile_fingerprint


def _persist_discovery_state(
    source_id: int,
    owner_username: str,
    *,
    status: str,
    snapshot: dict | None = None,
    fingerprint: str | None = None,
    profile: dict | None = None,
    profile_fingerprint: str | None = None,
    error: str | None = None,
) -> bool:
    engine = get_engine()
    if not engine:
        return False
    with engine.connect() as conn:
        result = conn.execute(
            text(
                f"UPDATE {T_VIRTUAL_SOURCES} SET "
                "discovery_status = :status, "
                "discovery_snapshot = CASE WHEN :snapshot IS NULL THEN discovery_snapshot "
                "ELSE CAST(:snapshot AS jsonb) END, "
                "discovery_fingerprint = CASE WHEN :fingerprint IS NULL "
                "THEN discovery_fingerprint ELSE :fingerprint END, "
                "profile_snapshot = CASE WHEN :profile IS NULL THEN profile_snapshot "
                "ELSE CAST(:profile AS jsonb) END, "
                "profile_fingerprint = CASE WHEN :profile_fingerprint IS NULL "
                "THEN profile_fingerprint ELSE :profile_fingerprint END, "
                "discovery_error = :error, "
                "last_discovery_at = CASE WHEN :status IN ('succeeded', 'failed') "
                "THEN NOW() ELSE last_discovery_at END, updated_at = NOW() "
                "WHERE id = :id AND owner_username = :owner"
            ),
            {
                "status": status,
                "snapshot": json.dumps(snapshot) if snapshot is not None else None,
                "fingerprint": fingerprint,
                "profile": json.dumps(profile) if profile is not None else None,
                "profile_fingerprint": profile_fingerprint,
                "error": error,
                "id": source_id,
                "owner": owner_username,
            },
        )
        conn.commit()
    return bool(result.rowcount)


async def discover_virtual_source(source_id: int, owner_username: str) -> dict:
    """Discover one registered source and persist a secret-free metadata snapshot."""
    source = get_virtual_source(source_id, owner_username)
    if not source or source.get("owner_username") != owner_username:
        return {"status": "error", "message": "Source not found or not owned by you"}

    from .connectors import ConnectorRegistry

    connector = ConnectorRegistry.get(source["source_type"])
    if connector is None:
        return {"status": "error", "message": "Unknown source type"}
    try:
        _persist_discovery_state(source_id, owner_username, status="running")
        raw = await connector.discover(
            source["endpoint_url"],
            source.get("auth_config") or {},
            source.get("query_config") or {},
        )
        if raw.get("error"):
            raise ValueError(str(raw["error"]))
        snapshot, fingerprint, profile, profile_fingerprint = _discovery_documents(
            source,
            raw,
        )
        if snapshot["truncated"]:
            raise ValueError("registered source discovery was truncated")
        if not _persist_discovery_state(
            source_id,
            owner_username,
            status="succeeded",
            snapshot=snapshot,
            fingerprint=fingerprint,
            profile=profile,
            profile_fingerprint=profile_fingerprint,
        ):
            raise LookupError("registered source disappeared during discovery")
        return {
            "status": "ok",
            "source_id": source_id,
            "discovery_status": "succeeded",
            "discovery_fingerprint": fingerprint,
            "profile_fingerprint": profile_fingerprint,
            "snapshot": snapshot,
            "profile": profile,
        }
    except Exception as exc:
        message = _redact_runtime_message(
            str(exc),
            source.get("auth_config") or {},
        )
        try:
            _persist_discovery_state(
                source_id,
                owner_username,
                status="failed",
                error=message,
            )
        except Exception:
            logger.exception("Failed to persist discovery failure for source %s", source_id)
        return {"status": "error", "message": message}


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
    register_result: bool = True,
):
    """Query a virtual source by its config dict. Returns GeoDataFrame or list/dict."""
    from .connectors import ConnectorRegistry

    credential_error = str(source.get("credential_error") or "").strip()
    if credential_error:
        # Do not call the connector with an empty password.  Apart from being
        # clearer to operators, this prevents a misleading driver error such
        # as ``fe_sendauth: no password supplied`` from escaping the product
        # route.  The message contains no endpoint or secret material.
        return {"status": "error", "message": credential_error}

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

    # Federated database results remain virtual by default and are never written
    # to the upload catalog as an implicit side effect.
    if register_result and stype != "database":
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
            creation_params={"source_name": src_name, "endpoint": source.get("endpoint_url", "")},
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

_SEMANTIC_THRESHOLD = 0.72
_schema_embedding_cache: dict[str, list[float]] = {}


def _get_schema_embeddings(texts: list[str]) -> list[list[float]]:
    """Get embedding vectors for schema field names. Cached."""
    uncached = [t for t in texts if t not in _schema_embedding_cache]
    if uncached:
        try:
            from .embedding_gateway import get_embeddings

            results = get_embeddings(uncached)
            for txt, emb in zip(uncached, results):
                _schema_embedding_cache[txt] = emb
        except Exception as e:
            logger.debug("Schema embedding API failed: %s — skipping semantic mapping", e)
            return []
    return [_schema_embedding_cache.get(t, []) for t in texts]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x**2 for x in a) ** 0.5
    norm_b = sum(x**2 for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def infer_schema_mapping(
    columns: list[str], threshold: float = _SEMANTIC_THRESHOLD
) -> dict[str, str]:
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

    col_embs = embeddings[: len(columns)]
    canon_embs = embeddings[len(columns) :]

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
                conn.execute(
                    text(
                        f"UPDATE {T_VIRTUAL_SOURCES} SET health_status = :h, "
                        f"last_health_check = NOW(), updated_at = NOW() WHERE id = :id"
                    ),
                    {"h": health, "id": source_id},
                )
                conn.commit()
        except Exception as e:
            logger.warning("Failed to update health status: %s", e)

    return {"status": "ok", "health": health, "message": message}
