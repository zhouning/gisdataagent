"""
MCP Hub Manager — config-driven MCP server connection management.

Loads servers from database (primary) + mcp_servers.yaml (fallback/seed),
creates ADK McpToolset instances per enabled server, and provides
aggregated tool access for agent integration.

Singleton pattern follows db_engine.py (module-level global + get function).
"""
import asyncio
import json
import math
import os
import sys
import threading
import time
import weakref
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import yaml
from sqlalchemy import text

from .i18n import t
from .mcp_transport import (
    McpConfigurationError,
    RedactingTextIO,
    build_httpx_client_factory,
    install_runtime_secret_log_filter,
    redact_mcp_text,
    register_runtime_secrets,
    resolve_ca_bundle,
    resolve_secret_reference,
    unregister_runtime_secrets,
)

try:
    from .observability import get_logger
    logger = get_logger("mcp_hub")
except Exception:
    import logging
    logger = logging.getLogger("mcp_hub")


T_MCP_SERVERS = "agent_mcp_servers"
MAX_MCP_SERVERS = int(os.environ.get("MCP_MAX_SERVERS", "20"))


# ---------------------------------------------------------------------------
# Encryption helpers — Fernet key derived from CHAINLIT_AUTH_SECRET
# ---------------------------------------------------------------------------

_FERNET_KEY: Optional[bytes] = None


def _get_fernet():
    """Return a Fernet instance keyed from CHAINLIT_AUTH_SECRET, or None."""
    global _FERNET_KEY
    if _FERNET_KEY is not None:
        from cryptography.fernet import Fernet
        return Fernet(_FERNET_KEY)
    secret = os.environ.get("CHAINLIT_AUTH_SECRET", "")
    if not secret:
        return None
    import base64
    import hashlib
    _FERNET_KEY = base64.urlsafe_b64encode(
        hashlib.pbkdf2_hmac("sha256", secret.encode(), b"mcp-hub-salt", 100_000, dklen=32))
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
    return val  # plain dict — backward compat with pre-encryption data


# ---------------------------------------------------------------------------
# Configuration data classes
# ---------------------------------------------------------------------------

@dataclass
class McpServerConfig:
    """Parsed config for a single MCP server."""
    name: str
    description: str = ""
    transport: str = "stdio"  # stdio | sse | streamable_http
    enabled: bool = False
    category: str = ""
    pipelines: list[str] = field(default_factory=lambda: ["general", "planner"])
    # stdio fields
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None
    # sse / streamable_http fields
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 5.0
    bearer_token_env_var: str = ""
    bearer_token_file_env_var: str = ""
    ca_bundle_env_var: str = ""
    system_managed: bool = False
    expose_raw_tools: bool = True
    configuration_error_code: str = ""
    configuration_error_message: str = ""
    # DB tracking
    source: str = "yaml"  # yaml | db | environment
    # Per-user isolation (v10.0.1)
    owner_username: Optional[str] = None  # None = legacy global
    is_shared: bool = True  # True = visible to all users


@dataclass
class McpServerStatus:
    """Runtime status for a connected MCP server."""
    config: McpServerConfig
    toolset: object = None  # McpToolset instance (typed as object to avoid import at module level)
    status: str = "disconnected"  # connected | disconnected | error
    tool_count: int = 0
    tool_names: list[str] = field(default_factory=list)
    error_message: str = ""
    error_code: str = ""
    connected_at: Optional[float] = None
    runtime_secrets: tuple[str, ...] = field(default_factory=tuple, repr=False)


_PUBLIC_MCP_ERRORS = {
    "ARCPY_MCP_DISABLED": "ArcPy MCP service is disabled",
    "ARCPY_MCP_ENABLED_INVALID": "ArcPy MCP enablement configuration is invalid",
    "ARCPY_MCP_URL_MISSING": "ArcPy MCP URL is not configured",
    "ARCPY_MCP_URL_INVALID": "ArcPy MCP URL configuration is invalid",
    "ARCPY_MCP_CONNECT_TIMEOUT_INVALID": "ArcPy MCP timeout configuration is invalid",
    "ARCPY_MCP_TOKEN_MISSING": "MCP credential is not available",
    "ARCPY_MCP_CA_MISSING": "MCP CA bundle is not available",
    "ARCPY_MCP_TLS_FAILED": "ArcPy MCP secure connection failed",
    "ARCPY_MCP_AUTH_FAILED": "ArcPy MCP authentication failed",
    "ARCPY_MCP_UNREACHABLE": "ArcPy MCP service is unreachable",
}


def _public_mcp_error(status: McpServerStatus) -> tuple[str, str]:
    """Map internal diagnostics to stable public error fields."""
    if status.error_code in _PUBLIC_MCP_ERRORS:
        return status.error_code, _PUBLIC_MCP_ERRORS[status.error_code]
    if status.status == "error" or status.error_message:
        return "MCP_CONNECTION_FAILED", "MCP server connection failed"
    return "", ""


def _streamable_http_kwargs(
    config: McpServerConfig,
    timeout: float,
    redaction_secrets: list[str],
) -> dict:
    """Build runtime-only streamable HTTP parameters for an MCP server."""
    if not config.url.strip():
        raise McpConfigurationError(
            "ARCPY_MCP_URL_MISSING", "ArcPy MCP URL is not configured"
        )
    runtime_headers = dict(config.headers or {})
    if config.bearer_token_env_var or config.bearer_token_file_env_var:
        token = resolve_secret_reference(
            config.bearer_token_env_var,
            config.bearer_token_file_env_var,
        )
        redaction_secrets.append(token)
        runtime_headers["Authorization"] = f"Bearer {token}"

    kwargs = {
        "url": config.url,
        "headers": runtime_headers or None,
        "timeout": timeout,
    }
    if config.ca_bundle_env_var:
        ca_bundle = resolve_ca_bundle(config.ca_bundle_env_var)
        kwargs["httpx_client_factory"] = build_httpx_client_factory(ca_bundle)
    return kwargs


# ---------------------------------------------------------------------------
# MCP Hub Manager
# ---------------------------------------------------------------------------

class McpHubManager:
    """Manages MCP server connections and tool aggregation.

    Load config → connect enabled servers → provide tools to agents.
    """

    def __init__(self):
        self._servers: dict[str, McpServerStatus] = {}
        self._config_path = os.path.join(
            os.path.dirname(__file__), "mcp_servers.yaml"
        )
        self._started = False
        self._closing = False
        self._lifecycle_locks = weakref.WeakKeyDictionary()
        self._lifecycle_locks_guard = threading.RLock()

    def _get_lifecycle_lock(self, name: str) -> asyncio.Lock:
        """Return the server lock scoped to the current event loop."""
        loop = asyncio.get_running_loop()
        with self._lifecycle_locks_guard:
            loop_locks = self._lifecycle_locks.get(loop)
            if loop_locks is None:
                loop_locks = weakref.WeakValueDictionary()
                self._lifecycle_locks[loop] = loop_locks
            lock = loop_locks.get(name)
            if lock is None:
                lock = asyncio.Lock()
                loop_locks[name] = lock
            return lock

    # ----- DB table -----

    def _ensure_table(self):
        """Create agent_mcp_servers table if it doesn't exist."""
        from .db_engine import get_engine
        engine = get_engine()
        if not engine:
            return False
        try:
            with engine.connect() as conn:
                conn.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS {T_MCP_SERVERS} (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(100) UNIQUE NOT NULL,
                        description TEXT DEFAULT '',
                        transport VARCHAR(30) DEFAULT 'stdio',
                        enabled BOOLEAN DEFAULT false,
                        category VARCHAR(50) DEFAULT '',
                        pipelines JSONB DEFAULT '["general","planner"]',
                        command VARCHAR(500) DEFAULT '',
                        args JSONB DEFAULT '[]',
                        env JSONB DEFAULT '{{}}',
                        cwd VARCHAR(500),
                        url VARCHAR(500) DEFAULT '',
                        headers JSONB DEFAULT '{{}}',
                        timeout REAL DEFAULT 5.0,
                        bearer_token_env_var VARCHAR(255) DEFAULT '',
                        bearer_token_file_env_var VARCHAR(255) DEFAULT '',
                        ca_bundle_env_var VARCHAR(255) DEFAULT '',
                        system_managed BOOLEAN DEFAULT FALSE,
                        expose_raw_tools BOOLEAN DEFAULT TRUE,
                        owner_username VARCHAR(100),
                        is_shared BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                """))
                # Add columns for existing tables (idempotent migration)
                conn.execute(text(f"""
                    ALTER TABLE {T_MCP_SERVERS}
                    ADD COLUMN IF NOT EXISTS owner_username VARCHAR(100)
                """))
                conn.execute(text(f"""
                    ALTER TABLE {T_MCP_SERVERS}
                    ADD COLUMN IF NOT EXISTS is_shared BOOLEAN DEFAULT TRUE
                """))
                conn.execute(text(f"""
                    ALTER TABLE {T_MCP_SERVERS}
                    ADD COLUMN IF NOT EXISTS bearer_token_env_var VARCHAR(255) DEFAULT ''
                """))
                conn.execute(text(f"""
                    ALTER TABLE {T_MCP_SERVERS}
                    ADD COLUMN IF NOT EXISTS bearer_token_file_env_var VARCHAR(255) DEFAULT ''
                """))
                conn.execute(text(f"""
                    ALTER TABLE {T_MCP_SERVERS}
                    ADD COLUMN IF NOT EXISTS ca_bundle_env_var VARCHAR(255) DEFAULT ''
                """))
                conn.execute(text(f"""
                    ALTER TABLE {T_MCP_SERVERS}
                    ADD COLUMN IF NOT EXISTS system_managed BOOLEAN DEFAULT FALSE
                """))
                conn.execute(text(f"""
                    ALTER TABLE {T_MCP_SERVERS}
                    ADD COLUMN IF NOT EXISTS expose_raw_tools BOOLEAN DEFAULT TRUE
                """))
                conn.commit()
            return True
        except Exception as e:
            logger.warning("Failed to create MCP servers table: %s", e)
            return False

    # ----- DB CRUD -----

    def _load_from_db(self, username: str = None) -> list[McpServerConfig]:
        """Load server configs from database. Returns configs list.

        If *username* is given, only returns servers owned by that user or shared.
        If None, returns all servers (for startup / admin).
        """
        from .db_engine import get_engine
        engine = get_engine()
        if not engine:
            return []
        try:
            cols = (
                "name, description, transport, enabled, category, "
                "pipelines, command, args, env, cwd, url, headers, timeout, "
                "bearer_token_env_var, bearer_token_file_env_var, ca_bundle_env_var, "
                "system_managed, expose_raw_tools, owner_username, is_shared"
            )
            if username:
                query = (
                    f"SELECT {cols} FROM {T_MCP_SERVERS} "
                    f"WHERE owner_username = :u OR is_shared = TRUE "
                    f"OR owner_username IS NULL ORDER BY name"
                )
                params = {"u": username}
            else:
                query = f"SELECT {cols} FROM {T_MCP_SERVERS} ORDER BY name"
                params = {}

            with engine.connect() as conn:
                rows = conn.execute(text(query), params).fetchall()

            configs = []
            for r in rows:
                pipelines = r[5] if isinstance(r[5], list) else json.loads(r[5]) if r[5] else ["general", "planner"]
                args = r[7] if isinstance(r[7], list) else json.loads(r[7]) if r[7] else []
                env = _decrypt_dict(r[8])
                headers = _decrypt_dict(r[11])
                config = McpServerConfig(
                    name=r[0], description=r[1] or "", transport=r[2] or "stdio",
                    enabled=bool(r[3]), category=r[4] or "", pipelines=pipelines,
                    command=r[6] or "", args=args, env=env, cwd=r[9],
                    url=r[10] or "", headers=headers, timeout=float(r[12] or 5.0),
                    bearer_token_env_var=r[13] or "",
                    bearer_token_file_env_var=r[14] or "",
                    ca_bundle_env_var=r[15] or "",
                    # Persisted rows never establish deployment provenance.
                    system_managed=False,
                    expose_raw_tools=bool(r[17]) if r[17] is not None else True,
                    source="db",
                    owner_username=r[18], is_shared=bool(r[19]) if r[19] is not None else True,
                )
                configs.append(config)
            return configs
        except Exception as e:
            logger.warning("Failed to load MCP servers from DB: %s", e)
            return []

    def _save_to_db(self, config: McpServerConfig) -> bool:
        """Upsert a server config to database."""
        from .db_engine import get_engine
        engine = get_engine()
        if not engine:
            return False
        try:
            with engine.connect() as conn:
                conn.execute(text(f"""
                    INSERT INTO {T_MCP_SERVERS}
                        (name, description, transport, enabled, category, pipelines,
                         command, args, env, cwd, url, headers, timeout,
                         bearer_token_env_var, bearer_token_file_env_var,
                         ca_bundle_env_var, system_managed, expose_raw_tools,
                         owner_username, is_shared, updated_at)
                    VALUES (:name, :desc, :transport, :enabled, :category, CAST(:pipelines AS jsonb),
                            :command, CAST(:args AS jsonb), CAST(:env AS jsonb), :cwd, :url, CAST(:headers AS jsonb),
                            :timeout, :bearer_token_env_var, :bearer_token_file_env_var,
                            :ca_bundle_env_var, :system_managed, :expose_raw_tools,
                            :owner_username, :is_shared, NOW())
                    ON CONFLICT (name) DO UPDATE SET
                        description = EXCLUDED.description,
                        transport = EXCLUDED.transport,
                        enabled = EXCLUDED.enabled,
                        category = EXCLUDED.category,
                        pipelines = EXCLUDED.pipelines,
                        command = EXCLUDED.command,
                        args = EXCLUDED.args,
                        env = EXCLUDED.env,
                        cwd = EXCLUDED.cwd,
                        url = EXCLUDED.url,
                        headers = EXCLUDED.headers,
                        timeout = EXCLUDED.timeout,
                        bearer_token_env_var = EXCLUDED.bearer_token_env_var,
                        bearer_token_file_env_var = EXCLUDED.bearer_token_file_env_var,
                        ca_bundle_env_var = EXCLUDED.ca_bundle_env_var,
                        system_managed = EXCLUDED.system_managed,
                        expose_raw_tools = EXCLUDED.expose_raw_tools,
                        owner_username = EXCLUDED.owner_username,
                        is_shared = EXCLUDED.is_shared,
                        updated_at = NOW()
                """), {
                    "name": config.name,
                    "desc": config.description,
                    "transport": config.transport,
                    "enabled": config.enabled,
                    "category": config.category,
                    "pipelines": json.dumps(config.pipelines),
                    "command": config.command,
                    "args": json.dumps(config.args),
                    "env": _encrypt_dict(config.env),
                    "cwd": config.cwd,
                    "url": config.url,
                    "headers": _encrypt_dict(config.headers),
                    "timeout": config.timeout,
                    "bearer_token_env_var": config.bearer_token_env_var,
                    "bearer_token_file_env_var": config.bearer_token_file_env_var,
                    "ca_bundle_env_var": config.ca_bundle_env_var,
                    "system_managed": config.system_managed,
                    "expose_raw_tools": config.expose_raw_tools,
                    "owner_username": config.owner_username,
                    "is_shared": config.is_shared,
                })
                conn.commit()
            return True
        except Exception as e:
            logger.warning("Failed to save MCP server '%s' to DB: %s", config.name, e)
            return False

    def _delete_from_db(self, name: str) -> bool:
        """Delete a server config from database."""
        from .db_engine import get_engine
        engine = get_engine()
        if not engine:
            return False
        try:
            with engine.connect() as conn:
                result = conn.execute(text(
                    f"DELETE FROM {T_MCP_SERVERS} WHERE name = :name"
                ), {"name": name})
                conn.commit()
            return result.rowcount > 0
        except Exception as e:
            logger.warning("Failed to delete MCP server '%s' from DB: %s", name, e)
            return False

    def _update_enabled_in_db(self, name: str, enabled: bool):
        """Update just the enabled flag in DB (for toggle)."""
        from .db_engine import get_engine
        engine = get_engine()
        if not engine:
            return
        try:
            with engine.connect() as conn:
                conn.execute(text(
                    f"UPDATE {T_MCP_SERVERS} SET enabled = :enabled, updated_at = NOW() "
                    f"WHERE name = :name"
                ), {"name": name, "enabled": enabled})
                conn.commit()
        except Exception:
            pass  # best-effort persistence

    # ----- Config loading -----

    def load_config(self) -> list[McpServerConfig]:
        """Load DB/YAML configs, then overlay system-managed environment configs."""
        # 1. Ensure DB table exists and load DB configs
        db_ok = self._ensure_table()
        db_configs = self._load_from_db() if db_ok else []
        db_names = {c.name for c in db_configs}

        # 2. Load YAML and seed any new servers into DB
        yaml_configs = self._load_yaml()
        for yc in yaml_configs:
            if yc.name not in db_names:
                if db_ok:
                    self._save_to_db(yc)
                    yc.source = "db"
                db_configs.append(yc)
                db_names.add(yc.name)

        # Defense in depth: only the environment overlay can establish provenance,
        # even when a loader is replaced or returns legacy managed rows.
        for persisted_config in db_configs:
            persisted_config.system_managed = False

        # 3. Overlay non-persistent system configs by name so environment wins.
        configs_by_name = {config.name: config for config in db_configs}
        persisted_arcpy = configs_by_name.get("arcpy-remote")
        arcpy_enabled_state = self._arcpy_mcp_enabled_state()
        system_configs = self._load_system_configs()
        for config in system_configs:
            configs_by_name[config.name] = config

        invalid_system_arcpy = any(
            config.name == "arcpy-remote"
            and bool(config.configuration_error_code)
            for config in system_configs
        )
        if arcpy_enabled_state == "disabled" and persisted_arcpy is not None:
            persisted_arcpy.enabled = False
        if (
            (arcpy_enabled_state in ("disabled", "invalid") or invalid_system_arcpy)
            and persisted_arcpy is not None
            and persisted_arcpy.source == "db"
        ):
            self._update_enabled_in_db(persisted_arcpy.name, False)

        configs = list(configs_by_name.values())

        # 4. When the remote service is enabled, retain but disable the old
        # Windows-local stdio row. Persistence is deliberately best effort.
        remote_enabled = any(
            config.name == "arcpy-remote" and config.enabled
            for config in system_configs
        )
        if remote_enabled:
            legacy = configs_by_name.get("arcgis-pro-tools")
            if legacy and self._is_windows_stdio(legacy):
                legacy.enabled = False
                marker = "Legacy Windows stdio configuration"
                if marker not in legacy.description:
                    legacy.description = (
                        f"{legacy.description.rstrip()} — {marker}"
                        if legacy.description.strip()
                        else marker
                    )
                self._update_enabled_in_db(legacy.name, False)

        # 5. Build runtime state.
        for config in configs:
            status = McpServerStatus(config=config)
            if config.configuration_error_code:
                status.status = "error"
                status.error_code = config.configuration_error_code
                status.error_message = config.configuration_error_message
            self._servers[config.name] = status

        logger.info(
            "Loaded %d MCP server config(s) (%d from DB, %d from YAML seed, %d system-managed)",
            len(configs),
            sum(1 for c in configs if c.source == "db"),
            len(yaml_configs),
            len(system_configs),
        )
        return configs

    @staticmethod
    def _is_windows_stdio(config: McpServerConfig) -> bool:
        """Return whether a config is the legacy Windows-local stdio shape."""
        if config.transport != "stdio":
            return False
        command = (config.command or "").strip()
        return bool(
            "\\" in command
            or (len(command) >= 2 and command[0].isalpha() and command[1] == ":")
        )

    def _load_system_configs(self) -> list[McpServerConfig]:
        """Build system-managed configs from references in process environment."""
        state = self._arcpy_mcp_enabled_state()
        if state in ("unset", "disabled"):
            return []

        url = os.environ.get("ARCPY_MCP_URL", "").strip()
        timeout = 10.0
        error_code = ""
        error_message = ""

        if state == "invalid":
            error_code = "ARCPY_MCP_ENABLED_INVALID"
            error_message = "ArcPy MCP enablement configuration is invalid"
        elif not url:
            error_code = "ARCPY_MCP_URL_MISSING"
            error_message = "ArcPy MCP URL is not configured"
        else:
            try:
                parsed_url = urlparse(url)
                valid_url = (
                    parsed_url.scheme in ("http", "https")
                    and bool(parsed_url.netloc)
                )
            except ValueError:
                valid_url = False
            if not valid_url:
                error_code = "ARCPY_MCP_URL_INVALID"
                error_message = "ArcPy MCP URL configuration is invalid"

        raw_timeout = os.environ.get("ARCPY_MCP_CONNECT_TIMEOUT", "10")
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError):
            timeout = 10.0
            if not error_code:
                error_code = "ARCPY_MCP_CONNECT_TIMEOUT_INVALID"
                error_message = "ArcPy MCP timeout configuration is invalid"
        else:
            if not math.isfinite(timeout) or timeout <= 0 or timeout > 300:
                if not error_code:
                    error_code = "ARCPY_MCP_CONNECT_TIMEOUT_INVALID"
                    error_message = "ArcPy MCP timeout configuration is invalid"
                timeout = 10.0

        return [McpServerConfig(
            name="arcpy-remote",
            description="Private ArcGIS Pro 3.7.1 ArcPy MCP service",
            transport="streamable_http",
            enabled=not bool(error_code),
            category="gis",
            pipelines=["general", "planner", "governance"],
            url=url,
            timeout=timeout,
            bearer_token_env_var="ARCPY_MCP_TOKEN",
            bearer_token_file_env_var="ARCPY_MCP_TOKEN_FILE",
            ca_bundle_env_var="ARCPY_MCP_CA_BUNDLE",
            system_managed=True,
            expose_raw_tools=False,
            configuration_error_code=error_code,
            configuration_error_message=error_message,
            source="environment",
            is_shared=True,
        )]

    @staticmethod
    def _arcpy_mcp_enabled_state() -> str:
        """Return fail-closed ArcPy enablement state from the environment."""
        raw = os.environ.get("ARCPY_MCP_ENABLED")
        if raw is None:
            return "unset"
        value = raw.strip().lower()
        if value in ("true", "1", "yes"):
            return "enabled"
        if value in ("false", "0", "no"):
            return "disabled"
        return "invalid"

    def _load_yaml(self) -> list[McpServerConfig]:
        """Load server configs from YAML file."""
        if not os.path.isfile(self._config_path):
            return []
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("Failed to parse mcp_servers.yaml: %s", e)
            return []

        servers_raw = data.get("servers") or []
        configs: list[McpServerConfig] = []
        for raw in servers_raw:
            if not isinstance(raw, dict) or "name" not in raw:
                continue
            config = McpServerConfig(
                name=raw["name"],
                description=raw.get("description", ""),
                transport=raw.get("transport", "stdio"),
                enabled=raw.get("enabled", False),
                category=raw.get("category", ""),
                pipelines=raw.get("pipelines", ["general", "planner"]),
                command=raw.get("command", ""),
                args=raw.get("args", []),
                env=raw.get("env", {}),
                cwd=raw.get("cwd"),
                url=raw.get("url", ""),
                headers=raw.get("headers", {}),
                timeout=raw.get("timeout", 5.0),
                bearer_token_env_var=raw.get("bearer_token_env_var", ""),
                bearer_token_file_env_var=raw.get("bearer_token_file_env_var", ""),
                ca_bundle_env_var=raw.get("ca_bundle_env_var", ""),
                # YAML is persisted deployment data, not trusted provenance.
                system_managed=False,
                expose_raw_tools=raw.get("expose_raw_tools", True),
                source="yaml",
            )
            configs.append(config)
        return configs

    # ----- Connection lifecycle -----

    async def connect_server(self, name: str) -> bool:
        """Connect to a single MCP server by name. Returns success."""
        async with self._get_lifecycle_lock(name):
            connected = await self._connect_server_unlocked(name)
            self._refresh_started_state()
            status = self._servers.get(name)
            if (
                not connected
                and status is not None
                and status.config.enabled
            ):
                self._started = False
            return connected

    async def _connect_server_unlocked(self, name: str) -> bool:
        """Connect while the caller owns the server lifecycle lock."""
        status = self._servers.get(name)
        if not status:
            return False
        config = status.config
        if self._closing or not config.enabled:
            self._started = False if self._closing else self._started
            return False
        if status.status == "connected" and status.toolset is not None:
            return True
        redaction_secrets: list[str] = []
        if status.toolset is not None or status.runtime_secrets:
            await self._cleanup_runtime(name, status)
        status.error_code = ""
        toolset = None
        secrets_registered = False
        ownership_transferred = False

        try:
            try:
                from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
                from google.adk.tools.mcp_tool.mcp_session_manager import (
                    StdioConnectionParams,
                    SseConnectionParams,
                    StreamableHTTPConnectionParams,
                )
                from mcp import StdioServerParameters

                if config.transport == "stdio":
                    conn_params = StdioConnectionParams(
                        server_params=StdioServerParameters(
                            command=config.command,
                            args=config.args,
                            env=config.env or None,
                            cwd=config.cwd,
                        ),
                        timeout=config.timeout,
                    )
                elif config.transport == "sse":
                    conn_params = SseConnectionParams(
                        url=config.url,
                        headers=config.headers or None,
                        timeout=config.timeout,
                    )
                elif config.transport == "streamable_http":
                    connection_kwargs = _streamable_http_kwargs(
                        config, config.timeout, redaction_secrets
                    )
                    if redaction_secrets:
                        install_runtime_secret_log_filter()
                        register_runtime_secrets(redaction_secrets)
                        secrets_registered = True
                    conn_params = StreamableHTTPConnectionParams(**connection_kwargs)
                else:
                    status.status = "error"
                    status.error_message = f"Unknown transport: {config.transport}"
                    return False

                if self._closing or not config.enabled:
                    return False
                prefix = config.name.replace("-", "_")
                toolset = McpToolset(
                    connection_params=conn_params,
                    tool_name_prefix=prefix,
                    errlog=RedactingTextIO(sys.stderr),
                )
                tools = await toolset.get_tools()

                if self._closing or not config.enabled:
                    return False
                status.toolset = toolset
                status.status = "connected"
                status.tool_count = len(tools)
                status.tool_names = [tool.name for tool in tools]
                status.connected_at = time.time()
                status.error_message = ""
                status.error_code = ""
                status.runtime_secrets = tuple(redaction_secrets)
                ownership_transferred = True

                logger.info(
                    t("mcp.server_connected", name=name, count=len(tools))
                )
                return True

            except Exception as e:
                error_message = redact_mcp_text(str(e), redaction_secrets)
                status.status = "error"
                status.error_message = error_message
                status.error_code = (
                    e.code if isinstance(e, McpConfigurationError) else ""
                )
                logger.warning(
                    t("mcp.server_failed", name=name, error=error_message)
                )
                return False
        finally:
            if not ownership_transferred:
                status.toolset = None
                status.tool_count = 0
                status.tool_names = []
                status.connected_at = None
                status.runtime_secrets = ()
                try:
                    if toolset is not None:
                        await self._close_toolset(
                            name, toolset, redaction_secrets
                        )
                finally:
                    if secrets_registered:
                        unregister_runtime_secrets(redaction_secrets)

    async def _close_toolset(self, name: str, toolset, secrets=()):
        """Close a toolset, logging only sanitized cleanup failures."""
        try:
            await toolset.close()
        except Exception as e:
            error_message = redact_mcp_text(str(e), secrets)
            logger.warning("Error closing MCP server '%s': %s", name, error_message)

    async def _cleanup_runtime(self, name: str, status: McpServerStatus):
        """Close a toolset and clear runtime-only state without changing status."""
        try:
            if status.toolset is not None:
                await self._close_toolset(name, status.toolset, status.runtime_secrets)
        finally:
            unregister_runtime_secrets(status.runtime_secrets)
            status.toolset = None
            status.tool_count = 0
            status.tool_names = []
            status.connected_at = None
            status.runtime_secrets = ()

    async def disconnect_server(self, name: str) -> bool:
        """Disconnect and cleanup a single server."""
        async with self._get_lifecycle_lock(name):
            disconnected = await self._disconnect_server_unlocked(name)
            if disconnected:
                self._refresh_started_state()
            return disconnected

    async def _disconnect_server_unlocked(self, name: str) -> bool:
        """Disconnect while the caller owns the server lifecycle lock."""
        status = self._servers.get(name)
        if not status:
            return False

        await self._cleanup_runtime(name, status)
        status.status = "disconnected"
        status.error_message = ""
        status.error_code = ""
        logger.info(t("mcp.server_disconnected", name=name))
        return True

    async def startup(self) -> bool:
        """Load config and connect enabled servers, returning full success."""
        if self._started:
            return True

        if not self._servers:
            self.load_config()

        enabled = [
            name for name, s in self._servers.items() if s.config.enabled
        ]
        connected = 0
        for name in enabled:
            if await self.connect_server(name):
                connected += 1

        total = len(enabled)
        logger.info(
            t("mcp.hub_startup", connected=connected, total=total)
        )
        self._started = not self._closing and connected == total
        return self._started

    async def retry_failed_servers(
        self,
        delays=(2, 5, 10, 20),
        sleep=asyncio.sleep,
    ) -> bool:
        """Retry enabled non-connected servers on a bounded schedule."""
        if self._closing:
            self._started = False
            return False
        pending = self._enabled_non_connected_servers()
        if not pending:
            return self._refresh_started_state()

        self._started = False
        for delay in delays:
            if self._closing:
                return False
            await sleep(delay)
            if self._closing:
                self._started = False
                return False
            for name in list(self._enabled_non_connected_servers()):
                if self._closing:
                    self._started = False
                    return False
                await self.connect_server(name)
            pending = self._enabled_non_connected_servers()
            if not pending:
                return self._refresh_started_state()
        return False

    def _enabled_non_connected_servers(self) -> list[str]:
        """Return enabled servers without a live connected runtime."""
        return [
            name for name, status in self._servers.items()
            if status.config.enabled and (
                status.status != "connected" or status.toolset is None
            )
        ]

    def _refresh_started_state(self) -> bool:
        """Recompute whether every enabled server owns a live connection."""
        self._started = (
            not self._closing and not self._enabled_non_connected_servers()
        )
        return self._started

    async def shutdown(self):
        """Disconnect all servers gracefully."""
        self._closing = True
        self._started = False
        for name in list(self._servers.keys()):
            async with self._get_lifecycle_lock(name):
                status = self._servers.get(name)
                if status is None:
                    continue
                if status.status == "connected":
                    await self._disconnect_server_unlocked(name)
                elif status.toolset is not None or status.runtime_secrets:
                    await self._cleanup_runtime(name, status)
        self._started = False

    # ----- Dynamic control -----

    async def toggle_server(self, name: str, enabled: bool) -> dict:
        """Enable/disable a server. Connects or disconnects accordingly. Persists to DB."""
        async with self._get_lifecycle_lock(name):
            status = self._servers.get(name)
            if not status:
                return {"status": "error", "message": f"Server '{name}' not found"}
            if status.config.system_managed:
                return {
                    "status": "forbidden",
                    "message": f"Server '{name}' is system-managed",
                }

            status.config.enabled = enabled
            self._update_enabled_in_db(name, enabled)

            if enabled and status.status != "connected":
                ok = await self._connect_server_unlocked(name)
                self._refresh_started_state()
                if not ok:
                    self._started = False
                return {
                    "status": "ok" if ok else "error",
                    "server": name,
                    "enabled": True,
                    "connected": ok,
                }
            if not enabled and status.status == "connected":
                await self._disconnect_server_unlocked(name)
                self._refresh_started_state()
                return {
                    "status": "ok",
                    "server": name,
                    "enabled": False,
                    "connected": False,
                }
            self._refresh_started_state()
            return {
                "status": "ok",
                "server": name,
                "enabled": enabled,
                "connected": status.status == "connected",
            }

    async def reconnect_server(self, name: str) -> dict:
        """Force disconnect then reconnect a server."""
        async with self._get_lifecycle_lock(name):
            status = self._servers.get(name)
            if not status:
                return {"status": "error", "message": f"Server '{name}' not found"}

            await self._disconnect_server_unlocked(name)
            ok = await self._connect_server_unlocked(name)
            self._refresh_started_state()
            if not ok:
                self._started = False
            return {
                "status": "ok" if ok else "error",
                "server": name,
                "connected": ok,
                "tool_count": status.tool_count,
            }

    async def test_connection(self, config: McpServerConfig) -> dict:
        """Test connectivity to an MCP server without persisting. Returns result dict."""
        redaction_secrets: list[str] = []
        toolset = None
        secrets_registered = False
        try:
            from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
            from google.adk.tools.mcp_tool.mcp_session_manager import (
                StdioConnectionParams, SseConnectionParams, StreamableHTTPConnectionParams,
            )
            from mcp import StdioServerParameters

            timeout = min(config.timeout, 10.0)
            if config.transport == "stdio":
                conn_params = StdioConnectionParams(
                    server_params=StdioServerParameters(
                        command=config.command, args=config.args,
                        env=config.env or None, cwd=config.cwd),
                    timeout=timeout)
            elif config.transport == "sse":
                conn_params = SseConnectionParams(
                    url=config.url, headers=config.headers or None, timeout=timeout)
            elif config.transport == "streamable_http":
                connection_kwargs = _streamable_http_kwargs(
                    config, timeout, redaction_secrets
                )
                if redaction_secrets:
                    install_runtime_secret_log_filter()
                    register_runtime_secrets(redaction_secrets)
                    secrets_registered = True
                conn_params = StreamableHTTPConnectionParams(**connection_kwargs)
            else:
                return {
                    "status": "error",
                    "message": f"Unknown transport: {config.transport}",
                    "error_code": "",
                }

            toolset = McpToolset(
                connection_params=conn_params,
                errlog=RedactingTextIO(sys.stderr),
            )
            tools = await toolset.get_tools()
            tool_count = len(tools)
            return {"status": "ok", "tool_count": tool_count,
                    "message": f"连接成功，发现 {tool_count} 个工具"}
        except Exception as e:
            message = redact_mcp_text(str(e), redaction_secrets)
            return {
                "status": "error",
                "message": message[:200],
                "error_code": (
                    e.code if isinstance(e, McpConfigurationError) else ""
                ),
            }
        finally:
            try:
                if toolset is not None:
                    await self._close_toolset(config.name, toolset, redaction_secrets)
            finally:
                if secrets_registered:
                    unregister_runtime_secrets(redaction_secrets)

    # ----- CRUD (hot-reload capable) -----

    async def add_server(self, config: McpServerConfig) -> dict:
        """Add a new server config. Saves to DB + registers in memory.
        Optionally connects if enabled.
        """
        async with self._get_lifecycle_lock(config.name):
            if config.name in self._servers:
                return {
                    "status": "error",
                    "message": f"Server '{config.name}' already exists",
                }
            if not config.name or len(config.name) > 100:
                return {"status": "error", "message": "Invalid server name"}
            if len(self._servers) >= MAX_MCP_SERVERS:
                return {
                    "status": "error",
                    "message": f"Maximum {MAX_MCP_SERVERS} servers reached",
                }

            config.source = "db"
            if not self._save_to_db(config):
                return {"status": "error", "message": "Failed to save to database"}

            self._servers[config.name] = McpServerStatus(config=config)
            connected = False
            if config.enabled:
                connected = await self._connect_server_unlocked(config.name)
            self._refresh_started_state()
            if config.enabled and not connected:
                self._started = False

            logger.info(
                "Added MCP server '%s' (transport=%s, enabled=%s, owner=%s)",
                config.name,
                config.transport,
                config.enabled,
                config.owner_username,
            )
            return {
                "status": "ok",
                "server": config.name,
                "connected": connected,
            }

    def _can_manage_server(self, name: str, username: str, role: str) -> bool:
        """Check if user can manage (update/delete) a server.

        Admins can manage any server. Non-admins can only manage their own.
        """
        status = self._servers.get(name)
        if not status:
            return False
        if status.config.system_managed:
            return False
        if role == "admin":
            return True
        return status.config.owner_username == username

    async def update_server(self, name: str, updates: dict) -> dict:
        """Update an existing server's config fields. Persists to DB."""
        async with self._get_lifecycle_lock(name):
            status = self._servers.get(name)
            if not status:
                return {"status": "error", "message": f"Server '{name}' not found"}
            if status.config.system_managed:
                return {
                    "status": "forbidden",
                    "message": f"Server '{name}' is system-managed",
                }

            config = status.config
            was_connected = status.status == "connected"

            for key in (
                "description", "transport", "category", "command", "url",
                "cwd", "timeout", "bearer_token_env_var",
                "bearer_token_file_env_var", "ca_bundle_env_var",
                "system_managed", "expose_raw_tools", "is_shared",
            ):
                if key in updates:
                    setattr(config, key, updates[key])
            for key in ("pipelines", "args", "env", "headers"):
                if key in updates:
                    setattr(config, key, updates[key])
            if "enabled" in updates:
                config.enabled = updates["enabled"]

            if not self._save_to_db(config):
                return {"status": "error", "message": "Failed to save to database"}

            needs_reconnect = any(k in updates for k in (
                "transport", "command", "args", "env", "cwd", "url",
                "headers", "timeout", "bearer_token_env_var",
                "bearer_token_file_env_var", "ca_bundle_env_var",
            ))
            if was_connected and needs_reconnect:
                await self._disconnect_server_unlocked(name)
                await self._connect_server_unlocked(name)

            self._refresh_started_state()

            return {"status": "ok", "server": name}

    async def remove_server(self, name: str) -> dict:
        """Remove a server completely. Disconnects, deletes from DB, removes from memory."""
        async with self._get_lifecycle_lock(name):
            status = self._servers.get(name)
            if not status:
                return {"status": "error", "message": f"Server '{name}' not found"}
            if status.config.system_managed:
                return {
                    "status": "forbidden",
                    "message": f"Server '{name}' is system-managed",
                }

            await self._cleanup_runtime(name, status)
            self._delete_from_db(name)
            del self._servers[name]
            self._refresh_started_state()

            logger.info("Removed MCP server '%s'", name)
            return {"status": "ok", "server": name}

    # ----- Tool access -----

    def get_server_statuses(self, username: str = None) -> list[dict]:
        """Return status info for configured servers.

        If *username* is given, filters to servers owned by that user or shared/global.
        If None, returns all (for admin / startup).
        """
        result = []
        for name, s in self._servers.items():
            if username:
                owner = s.config.owner_username
                shared = s.config.is_shared
                if owner is not None and owner != username and not shared:
                    continue
            public_error_code, public_error_message = _public_mcp_error(s)
            result.append({
                "name": name,
                "description": s.config.description,
                "transport": s.config.transport,
                "enabled": s.config.enabled,
                "category": s.config.category,
                "pipelines": s.config.pipelines,
                "status": s.status,
                "tool_count": s.tool_count,
                "tool_names": s.tool_names,
                "error_message": public_error_message,
                "error_code": public_error_code,
                "connected_at": s.connected_at,
                "source": s.config.source,
                "system_managed": s.config.system_managed,
                "expose_raw_tools": s.config.expose_raw_tools,
                "owner_username": s.config.owner_username,
                "is_shared": s.config.is_shared,
            })
        return result

    async def get_all_tools(self, pipeline: str = None, username: str = None) -> list:
        """Get tools from all connected servers, optionally filtered by pipeline and user visibility."""
        tools = []
        for name in list(self._servers):
            async with self._get_lifecycle_lock(name):
                status = self._servers.get(name)
                if (
                    status is None
                    or status.status != "connected"
                    or status.toolset is None
                    or not status.config.expose_raw_tools
                ):
                    continue
                if pipeline and pipeline not in status.config.pipelines:
                    continue
                if username:
                    owner = status.config.owner_username
                    shared = status.config.is_shared
                    if owner is not None and owner != username and not shared:
                        continue
                try:
                    server_tools = await status.toolset.get_tools()
                    tools.extend(server_tools)
                except Exception as e:
                    error_message = redact_mcp_text(
                        str(e), status.runtime_secrets
                    )
                    logger.warning(
                        "Failed to get tools from '%s': %s",
                        name,
                        error_message,
                    )
                    status.status = "error"
                    status.error_message = error_message
                    status.error_code = ""
                    self._started = False
                    await self._cleanup_runtime(name, status)
        return tools

    async def get_tools_for_server(self, name: str) -> list[dict]:
        """Get tool metadata for a specific server (for API/UI)."""
        async with self._get_lifecycle_lock(name):
            status = self._servers.get(name)
            if (
                status is None
                or status.status != "connected"
                or status.toolset is None
                or not status.config.expose_raw_tools
            ):
                return []

            try:
                tools = await status.toolset.get_tools()
                result = []
                for tool in tools:
                    info = {
                        "name": tool.name,
                        "description": getattr(tool, "description", ""),
                        "server": name,
                    }
                    result.append(info)
                return result
            except Exception as e:
                error_message = redact_mcp_text(
                    str(e), status.runtime_secrets
                )
                logger.warning(
                    "Failed to get tools from '%s': %s", name, error_message
                )
                status.status = "error"
                status.error_message = error_message
                status.error_code = ""
                self._started = False
                await self._cleanup_runtime(name, status)
                return []


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_hub: Optional[McpHubManager] = None


def get_mcp_hub() -> McpHubManager:
    """Get or create the singleton McpHubManager."""
    global _hub
    if _hub is None:
        _hub = McpHubManager()
    return _hub


def reset_mcp_hub():
    """Reset the singleton. Used for testing."""
    global _hub
    _hub = None


# ---------------------------------------------------------------------------
# Tool Selection Rule Engine (v15.6)
# ---------------------------------------------------------------------------

class ToolSelectionRule:
    """A rule mapping task_type → tool + server + parameters."""

    __slots__ = (
        "id", "task_type", "tool_name", "server_name",
        "parameters", "priority", "fallback_tool", "fallback_server",
    )

    def __init__(self, **kwargs):
        for k in self.__slots__:
            setattr(self, k, kwargs.get(k))

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


class ToolRuleEngine:
    """Manages tool selection rules: CRUD + matching.

    Rules are stored in agent_mcp_tool_rules table and cached in memory.
    """

    _TABLE = "agent_mcp_tool_rules"

    @classmethod
    def _ensure_table(cls):
        from .db_engine import get_engine
        engine = get_engine()
        if not engine:
            return
        try:
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS {cls._TABLE} (
                        id SERIAL PRIMARY KEY,
                        task_type VARCHAR(100) NOT NULL,
                        tool_name VARCHAR(200) NOT NULL,
                        server_name VARCHAR(100) NOT NULL,
                        parameters JSONB DEFAULT '{{}}'::jsonb,
                        priority INTEGER DEFAULT 0,
                        fallback_tool VARCHAR(200),
                        fallback_server VARCHAR(100),
                        owner_username VARCHAR(100),
                        is_shared BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                """))
                conn.commit()
        except Exception:
            pass

    @classmethod
    def add_rule(cls, task_type: str, tool_name: str, server_name: str,
                 parameters: dict = None, priority: int = 0,
                 fallback_tool: str = None, fallback_server: str = None) -> Optional[int]:
        """Add a tool selection rule. Returns rule ID."""
        from .db_engine import get_engine
        engine = get_engine()
        if not engine:
            return None
        try:
            import json
            from sqlalchemy import text
            from .user_context import current_user_id
            username = current_user_id.get() or "system"
            with engine.connect() as conn:
                result = conn.execute(text(f"""
                    INSERT INTO {cls._TABLE}
                        (task_type, tool_name, server_name, parameters, priority,
                         fallback_tool, fallback_server, owner_username)
                    VALUES (:tt, :tn, :sn, :params::jsonb, :pri, :ft, :fs, :user)
                    RETURNING id
                """), {
                    "tt": task_type, "tn": tool_name, "sn": server_name,
                    "params": json.dumps(parameters or {}), "pri": priority,
                    "ft": fallback_tool, "fs": fallback_server, "user": username,
                })
                row = result.fetchone()
                conn.commit()
                return row[0] if row else None
        except Exception as e:
            logger.error("Failed to add tool rule: %s", e)
            return None

    @classmethod
    def list_rules(cls, task_type: str = None) -> list[dict]:
        """List rules, optionally filtered by task_type."""
        from .db_engine import get_engine
        engine = get_engine()
        if not engine:
            return []
        try:
            from sqlalchemy import text
            sql = f"SELECT * FROM {cls._TABLE}"
            params = {}
            if task_type:
                sql += " WHERE task_type = :tt"
                params["tt"] = task_type
            sql += " ORDER BY priority DESC, id"
            with engine.connect() as conn:
                rows = conn.execute(text(sql), params).mappings().all()
                return [dict(r) for r in rows]
        except Exception:
            return []

    @classmethod
    def match_tool(cls, task_type: str) -> Optional[dict]:
        """Find the best matching tool for a task type.

        Returns dict with tool_name, server_name, parameters, fallback info.
        """
        rules = cls.list_rules(task_type=task_type)
        if not rules:
            return None
        # Return highest priority rule
        best = rules[0]
        return {
            "tool_name": best["tool_name"],
            "server_name": best["server_name"],
            "parameters": best.get("parameters", {}),
            "fallback_tool": best.get("fallback_tool"),
            "fallback_server": best.get("fallback_server"),
        }

    @classmethod
    def delete_rule(cls, rule_id: int) -> bool:
        """Delete a rule by ID."""
        from .db_engine import get_engine
        engine = get_engine()
        if not engine:
            return False
        try:
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text(f"DELETE FROM {cls._TABLE} WHERE id = :id"), {"id": rule_id})
                conn.commit()
                return True
        except Exception:
            return False
