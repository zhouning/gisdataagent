"""MCP Hub routes — extracted from frontend_api.py (S-4 refactoring v12.1)."""

import os
import logging
from typing import Optional
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context, _require_admin

logger = logging.getLogger("data_agent.api.mcp_routes")

_MCP_ALLOWED_COMMANDS = {"python", "python3", "node", "npx", "uvx", "docker", "deno"}


def _validate_mcp_config(body: dict, transport: str, *, partial: bool = False) -> Optional[str]:
    """Validate MCP server config fields. Returns error message or None."""
    if transport == "stdio":
        cmd = body.get("command")
        if cmd is not None or not partial:
            cmd = (cmd or "").strip()
            if not cmd:
                return "command required for stdio transport"
            base = os.path.basename(cmd.split()[0]).lower().rstrip(".exe")
            if base not in _MCP_ALLOWED_COMMANDS:
                return f"command not in allowed list: {sorted(_MCP_ALLOWED_COMMANDS)}"
            if any(c in cmd for c in ";|&`$\n"):
                return "command contains disallowed shell metacharacters"
    else:
        url = body.get("url")
        if url is not None or not partial:
            url = (url or "").strip()
            if not url:
                return f"url required for {transport} transport"
            if not url.startswith(("http://", "https://")):
                return "url must start with http:// or https://"
    args = body.get("args")
    if args is not None and (not isinstance(args, list) or not all(isinstance(a, str) for a in args)):
        return "args must be a list of strings"
    headers = body.get("headers")
    if headers is not None and (not isinstance(headers, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in headers.items())):
        return "headers must be a dict of string:string"
    return None


async def mcp_servers(request: Request):
    """GET /api/mcp/servers — list MCP servers visible to current user."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    from ..mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    filter_user = None if role == "admin" else username
    servers = hub.get_server_statuses(username=filter_user)
    return JSONResponse({"servers": servers, "count": len(servers)})


async def mcp_tools(request: Request):
    """GET /api/mcp/tools — list all tools from connected MCP servers."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    server_name = request.query_params.get("server")
    from ..mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    if server_name:
        tools = await hub.get_tools_for_server(server_name)
    else:
        tools = []
        for status in hub.get_server_statuses():
            if status["status"] == "connected":
                server_tools = await hub.get_tools_for_server(status["name"])
                tools.extend(server_tools)
    return JSONResponse({"tools": tools, "count": len(tools)})


async def mcp_toggle(request: Request):
    """POST /api/mcp/servers/{name}/toggle — enable/disable a server (admin only)."""
    user, username, role, err = _require_admin(request)
    if err:
        return err
    server_name = request.path_params.get("name", "")
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    enabled = body.get("enabled", True)
    from ..mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    result = await hub.toggle_server(server_name, enabled)
    if result.get("status") == "ok":
        from ..audit_logger import record_audit, ACTION_MCP_SERVER_TOGGLE
        record_audit(username, ACTION_MCP_SERVER_TOGGLE, details={"server": server_name, "enabled": enabled})
    status_code = 200 if result.get("status") == "ok" else 404
    return JSONResponse(result, status_code=status_code)


async def mcp_reconnect(request: Request):
    """POST /api/mcp/servers/{name}/reconnect — force reconnect (admin only)."""
    user, username, role, err = _require_admin(request)
    if err:
        return err
    server_name = request.path_params.get("name", "")
    from ..mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    result = await hub.reconnect_server(server_name)
    if result.get("status") == "ok":
        from ..audit_logger import record_audit, ACTION_MCP_SERVER_RECONNECT
        record_audit(username, ACTION_MCP_SERVER_RECONNECT, details={"server": server_name})
    status_code = 200 if result.get("status") == "ok" else 404
    return JSONResponse(result, status_code=status_code)


async def mcp_test_connection(request: Request):
    """POST /api/mcp/test — test MCP server connection without saving."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    transport = body.get("transport", "stdio")
    err = _validate_mcp_config(body, transport)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    from ..mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    result = await hub.test_connection(body)
    status_code = 200 if result.get("status") == "ok" else 400
    return JSONResponse(result, status_code=status_code)


async def mcp_server_create(request: Request):
    """POST /api/mcp/servers — register a new MCP server."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    name = body.get("name", "").strip()
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    transport = body.get("transport", "stdio")
    if transport not in ("stdio", "sse", "streamable_http"):
        return JSONResponse({"error": "transport must be stdio, sse, or streamable_http"}, status_code=400)
    err = _validate_mcp_config(body, transport)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    from ..mcp_hub import get_mcp_hub, MCPServerConfig
    config = MCPServerConfig(
        name=name, transport=transport,
        command=body.get("command", ""), args=body.get("args", []),
        url=body.get("url", ""), headers=body.get("headers", {}),
        env=body.get("env", {}), description=body.get("description", ""),
        owner_username=username, is_shared=body.get("is_shared", False),
    )
    hub = get_mcp_hub()
    result = await hub.add_server(config)
    if result.get("status") == "ok":
        from ..audit_logger import record_audit, ACTION_MCP_SERVER_CREATE
        record_audit(username, ACTION_MCP_SERVER_CREATE, details={"server": name})
    status_code = 201 if result.get("status") == "ok" else 400
    return JSONResponse(result, status_code=status_code)


async def mcp_server_update(request: Request):
    """PUT /api/mcp/servers/{name} — update MCP server config."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    server_name = request.path_params.get("name", "")
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    from ..mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    if not hub._can_manage_server(server_name, username, role):
        return JSONResponse({"error": "Permission denied"}, status_code=403)
    transport = body.get("transport")
    if transport:
        err = _validate_mcp_config(body, transport, partial=True)
    else:
        existing = hub._servers.get(server_name)
        transport = existing.config.transport if existing else "stdio"
        err = _validate_mcp_config(body, transport, partial=True)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    result = await hub.update_server(server_name, body)
    if result.get("status") == "ok":
        from ..audit_logger import record_audit, ACTION_MCP_SERVER_UPDATE
        record_audit(username, ACTION_MCP_SERVER_UPDATE, details={"server": server_name})
    status_code = 200 if result.get("status") == "ok" else 404
    return JSONResponse(result, status_code=status_code)


async def mcp_server_delete(request: Request):
    """DELETE /api/mcp/servers/{name} — remove MCP server."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    server_name = request.path_params.get("name", "")
    from ..mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    if not hub._can_manage_server(server_name, username, role):
        return JSONResponse({"error": "Permission denied"}, status_code=403)
    result = await hub.remove_server(server_name)
    if result.get("status") == "ok":
        from ..audit_logger import record_audit, ACTION_MCP_SERVER_DELETE
        record_audit(username, ACTION_MCP_SERVER_DELETE, details={"server": server_name})
    status_code = 200 if result.get("status") == "ok" else 404
    return JSONResponse(result, status_code=status_code)


async def mcp_servers_mine(request: Request):
    """GET /api/mcp/servers/mine — list only the current user's personal MCP servers."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role = _set_user_context(user)
    from ..mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    all_servers = hub.get_server_statuses()
    mine = [s for s in all_servers if s.get("owner_username") == username]
    return JSONResponse({"servers": mine, "count": len(mine)})


async def mcp_server_share(request: Request):
    """POST /api/mcp/servers/{name}/share — toggle is_shared flag (admin only)."""
    user, username, role, err = _require_admin(request)
    if err:
        return err
    server_name = request.path_params.get("name", "")
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    is_shared = body.get("is_shared", True)
    from ..mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    status_obj = hub._servers.get(server_name)
    if not status_obj:
        return JSONResponse({"error": f"Server '{server_name}' not found"}, status_code=404)
    status_obj.config.is_shared = is_shared
    hub._save_to_db(status_obj.config)
    from ..audit_logger import record_audit, ACTION_MCP_SERVER_UPDATE
    record_audit(username, ACTION_MCP_SERVER_UPDATE, details={"server": server_name, "is_shared": is_shared})
    return JSONResponse({"status": "ok", "server": server_name, "is_shared": is_shared})


def get_mcp_routes() -> list:
    """Return Route objects for MCP Hub endpoints."""
    return [
        Route("/api/mcp/servers", mcp_servers, methods=["GET"]),
        Route("/api/mcp/servers", mcp_server_create, methods=["POST"]),
        Route("/api/mcp/servers/mine", mcp_servers_mine, methods=["GET"]),
        Route("/api/mcp/tools", mcp_tools, methods=["GET"]),
        Route("/api/mcp/test", mcp_test_connection, methods=["POST"]),
        Route("/api/mcp/servers/{name:path}/toggle", mcp_toggle, methods=["POST"]),
        Route("/api/mcp/servers/{name:path}/reconnect", mcp_reconnect, methods=["POST"]),
        Route("/api/mcp/servers/{name:path}/share", mcp_server_share, methods=["POST"]),
        Route("/api/mcp/servers/{name:path}", mcp_server_update, methods=["PUT"]),
        Route("/api/mcp/servers/{name:path}", mcp_server_delete, methods=["DELETE"]),
    ]
