"""
MCP Hub Manager — config-driven MCP server connection management.

Loads mcp_servers.yaml at startup, creates ADK McpToolset instances per
enabled server, and provides aggregated tool access for agent integration.

Singleton pattern follows db_engine.py (module-level global + get function).
"""
import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import yaml

from .i18n import t

try:
    from .observability import get_logger
    logger = get_logger("mcp_hub")
except Exception:
    import logging
    logger = logging.getLogger("mcp_hub")


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

    # ----- Config loading -----

    def load_config(self) -> list[McpServerConfig]:
        """Load server configs from YAML. Returns list of configs."""
        if not os.path.isfile(self._config_path):
            logger.info(t("mcp.no_config"))
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
            )
            configs.append(config)
            self._servers[config.name] = McpServerStatus(config=config)

        logger.info("Loaded %d MCP server config(s)", len(configs))
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
        """Enable/disable a server. Connects or disconnects accordingly."""
        status = self._servers.get(name)
        if not status:
            return {"status": "error", "message": f"Server '{name}' not found"}

        status.config.enabled = enabled
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

    # ----- Tool access -----

    def get_server_statuses(self) -> list[dict]:
        """Return status info for all configured servers."""
        result = []
        for name, s in self._servers.items():
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
            })
        return result

    async def get_all_tools(self, pipeline: str = None) -> list:
        """Get tools from all connected servers, optionally filtered by pipeline."""
        tools = []
        for name, s in self._servers.items():
            if s.status != "connected" or s.toolset is None:
                continue
            if pipeline and pipeline not in s.config.pipelines:
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
