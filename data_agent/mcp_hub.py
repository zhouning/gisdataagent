"""
MCP Hub Manager — config-driven MCP server connection management.

Loads servers from database (primary) + mcp_servers.yaml (fallback/seed),
creates ADK McpToolset instances per enabled server, and provides
aggregated tool access for agent integration.

Singleton pattern follows db_engine.py (module-level global + get function).
"""
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import yaml
from sqlalchemy import text

from .i18n import t

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
    # DB tracking
    source: str = "yaml"  # yaml | db
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
    connected_at: Optional[float] = None


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
                "owner_username, is_shared"
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
                    source="db",
                    owner_username=r[13], is_shared=bool(r[14]) if r[14] is not None else True,
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
                         owner_username, is_shared, updated_at)
                    VALUES (:name, :desc, :transport, :enabled, :category, CAST(:pipelines AS jsonb),
                            :command, CAST(:args AS jsonb), CAST(:env AS jsonb), :cwd, :url, CAST(:headers AS jsonb),
                            :timeout, :owner_username, :is_shared, NOW())
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
        """Load server configs from DB (primary) + YAML (seed/fallback)."""
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

        # 3. Build runtime state
        for config in db_configs:
            self._servers[config.name] = McpServerStatus(config=config)

        logger.info("Loaded %d MCP server config(s) (%d from DB, %d from YAML seed)",
                     len(db_configs), sum(1 for c in db_configs if c.source == "db"), len(yaml_configs))
        return db_configs

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
                source="yaml",
            )
            configs.append(config)
        return configs

    # ----- Connection lifecycle -----

    async def connect_server(self, name: str) -> bool:
        """Connect to a single MCP server by name. Returns success."""
        status = self._servers.get(name)
        if not status:
            return False
        config = status.config

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
                conn_params = StreamableHTTPConnectionParams(
                    url=config.url,
                    headers=config.headers or None,
                    timeout=config.timeout,
                )
            else:
                status.status = "error"
                status.error_message = f"Unknown transport: {config.transport}"
                return False

            # Create toolset with name prefix to avoid tool name collisions
            prefix = config.name.replace("-", "_")
            toolset = McpToolset(
                connection_params=conn_params,
                tool_name_prefix=prefix,
                errlog=sys.stderr,
            )

            # Probe tools to verify connection
            tools = await toolset.get_tools()

            status.toolset = toolset
            status.status = "connected"
            status.tool_count = len(tools)
            status.tool_names = [tool.name for tool in tools]
            status.connected_at = time.time()
            status.error_message = ""

            logger.info(
                t("mcp.server_connected", name=name, count=len(tools))
            )
            return True

        except Exception as e:
            status.status = "error"
            status.error_message = str(e)
            status.toolset = None
            status.tool_count = 0
            status.tool_names = []
            logger.warning(t("mcp.server_failed", name=name, error=str(e)))
            return False

    async def disconnect_server(self, name: str) -> bool:
        """Disconnect and cleanup a single server."""
        status = self._servers.get(name)
        if not status:
            return False

        if status.toolset is not None:
            try:
                await status.toolset.close()
            except Exception as e:
                logger.warning("Error closing MCP server '%s': %s", name, e)

        status.toolset = None
        status.status = "disconnected"
        status.tool_count = 0
        status.tool_names = []
        status.connected_at = None
        status.error_message = ""
        logger.info(t("mcp.server_disconnected", name=name))
        return True

    async def startup(self):
        """Load config and connect all enabled servers."""
        if self._started:
            return

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
        self._started = True

    async def shutdown(self):
        """Disconnect all servers gracefully."""
        for name in list(self._servers.keys()):
            if self._servers[name].status == "connected":
                await self.disconnect_server(name)
        self._started = False

    # ----- Dynamic control -----

    async def toggle_server(self, name: str, enabled: bool) -> dict:
        """Enable/disable a server. Connects or disconnects accordingly. Persists to DB."""
        status = self._servers.get(name)
        if not status:
            return {"status": "error", "message": f"Server '{name}' not found"}

        status.config.enabled = enabled
        self._update_enabled_in_db(name, enabled)

        if enabled and status.status != "connected":
            ok = await self.connect_server(name)
            return {
                "status": "ok" if ok else "error",
                "server": name,
                "enabled": True,
                "connected": ok,
            }
        elif not enabled and status.status == "connected":
            await self.disconnect_server(name)
            return {"status": "ok", "server": name, "enabled": False, "connected": False}
        return {"status": "ok", "server": name, "enabled": enabled, "connected": status.status == "connected"}

    async def reconnect_server(self, name: str) -> dict:
        """Force disconnect then reconnect a server."""
        status = self._servers.get(name)
        if not status:
            return {"status": "error", "message": f"Server '{name}' not found"}

        await self.disconnect_server(name)
        ok = await self.connect_server(name)
        return {
            "status": "ok" if ok else "error",
            "server": name,
            "connected": ok,
            "tool_count": status.tool_count,
        }

    async def test_connection(self, config: McpServerConfig) -> dict:
        """Test connectivity to an MCP server without persisting. Returns result dict."""
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
                conn_params = StreamableHTTPConnectionParams(
                    url=config.url, headers=config.headers or None, timeout=timeout)
            else:
                return {"status": "error", "message": f"Unknown transport: {config.transport}"}

            toolset = McpToolset(connection_params=conn_params, errlog=sys.stderr)
            tools = await toolset.get_tools()
            tool_count = len(tools)
            await toolset.close()
            return {"status": "ok", "tool_count": tool_count,
                    "message": f"连接成功，发现 {tool_count} 个工具"}
        except Exception as e:
            return {"status": "error", "message": str(e)[:200]}

    # ----- CRUD (hot-reload capable) -----

    async def add_server(self, config: McpServerConfig) -> dict:
        """Add a new server config. Saves to DB + registers in memory.
        Optionally connects if enabled.
        """
        if config.name in self._servers:
            return {"status": "error", "message": f"Server '{config.name}' already exists"}
        if not config.name or len(config.name) > 100:
            return {"status": "error", "message": "Invalid server name"}
        if len(self._servers) >= MAX_MCP_SERVERS:
            return {"status": "error", "message": f"Maximum {MAX_MCP_SERVERS} servers reached"}

        config.source = "db"
        if not self._save_to_db(config):
            return {"status": "error", "message": "Failed to save to database"}

        self._servers[config.name] = McpServerStatus(config=config)
        connected = False
        if config.enabled:
            connected = await self.connect_server(config.name)

        logger.info("Added MCP server '%s' (transport=%s, enabled=%s, owner=%s)",
                     config.name, config.transport, config.enabled, config.owner_username)
        return {"status": "ok", "server": config.name, "connected": connected}

    def _can_manage_server(self, name: str, username: str, role: str) -> bool:
        """Check if user can manage (update/delete) a server.

        Admins can manage any server. Non-admins can only manage their own.
        """
        if role == "admin":
            return True
        status = self._servers.get(name)
        if not status:
            return False
        return status.config.owner_username == username

    async def update_server(self, name: str, updates: dict) -> dict:
        """Update an existing server's config fields. Persists to DB."""
        status = self._servers.get(name)
        if not status:
            return {"status": "error", "message": f"Server '{name}' not found"}

        config = status.config
        was_connected = status.status == "connected"

        # Apply updatable fields
        for key in ("description", "transport", "category", "command", "url",
                     "cwd", "timeout"):
            if key in updates:
                setattr(config, key, updates[key])
        for key in ("pipelines", "args", "env", "headers"):
            if key in updates:
                setattr(config, key, updates[key])
        if "enabled" in updates:
            config.enabled = updates["enabled"]

        if not self._save_to_db(config):
            return {"status": "error", "message": "Failed to save to database"}

        # Reconnect if connection-relevant fields changed
        needs_reconnect = any(k in updates for k in ("transport", "command", "args",
                                                       "env", "cwd", "url", "headers", "timeout"))
        if was_connected and needs_reconnect:
            await self.disconnect_server(name)
            await self.connect_server(name)

        return {"status": "ok", "server": name}

    async def remove_server(self, name: str) -> dict:
        """Remove a server completely. Disconnects, deletes from DB, removes from memory."""
        status = self._servers.get(name)
        if not status:
            return {"status": "error", "message": f"Server '{name}' not found"}

        if status.status == "connected":
            await self.disconnect_server(name)

        self._delete_from_db(name)
        del self._servers[name]

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
                "error_message": s.error_message,
                "connected_at": s.connected_at,
                "source": s.config.source,
                "owner_username": s.config.owner_username,
                "is_shared": s.config.is_shared,
            })
        return result

    async def get_all_tools(self, pipeline: str = None, username: str = None) -> list:
        """Get tools from all connected servers, optionally filtered by pipeline and user visibility."""
        tools = []
        for name, s in self._servers.items():
            if s.status != "connected" or s.toolset is None:
                continue
            if pipeline and pipeline not in s.config.pipelines:
                continue
            # Per-user visibility filter
            if username:
                owner = s.config.owner_username
                shared = s.config.is_shared
                if owner is not None and owner != username and not shared:
                    continue
            try:
                server_tools = await s.toolset.get_tools()
                tools.extend(server_tools)
            except Exception as e:
                logger.warning("Failed to get tools from '%s': %s", name, e)
                s.status = "error"
                s.error_message = str(e)
        return tools

    async def get_tools_for_server(self, name: str) -> list[dict]:
        """Get tool metadata for a specific server (for API/UI)."""
        status = self._servers.get(name)
        if not status or status.status != "connected" or status.toolset is None:
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
        except Exception:
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
