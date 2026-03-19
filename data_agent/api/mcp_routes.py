"""
MCP Hub API routes — server CRUD, tool listing, connection management.

Extracted from frontend_api.py (S-4 refactoring).
"""
import os
from starlette.requests import Request
from starlette.responses import JSONResponse

from .helpers import _get_user_from_request, _set_user_context, _require_admin
from ..observability import get_logger
from ..audit_logger import (
    record_audit,
    ACTION_MCP_SERVER_CREATE, ACTION_MCP_SERVER_UPDATE,
    ACTION_MCP_SERVER_DELETE, ACTION_MCP_SERVER_TOGGLE,
    ACTION_MCP_SERVER_RECONNECT,
)

logger = get_logger("api.mcp")

# Allowed commands for stdio transport
_MCP_ALLOWED_COMMANDS = {"python", "python3", "node", "npx", "uvx", "docker", "deno"}


def _validate_mcp_config(body: dict, transport: str, *, partial: bool = False):
    """Validate MCP server config. Returns error string or None."""
    if transport == "stdio":
        cmd = (body.get("command") or "").strip()
        if not partial and not cmd:
            return "command required for stdio transport"
        if cmd:
            base = os.path.basename(cmd.split()[0]).lower().rstrip(".exe")
            if base not in _MCP_ALLOWED_COMMANDS:
                return f"command '{base}' not in allowed list: {sorted(_MCP_ALLOWED_COMMANDS)}"
            if any(c in cmd for c in ";|&`$\n"):
                return "command contains disallowed shell metacharacters"
    elif transport in ("sse", "streamable_http"):
        url = (body.get("url") or "").strip()
        if not partial and not url:
            return f"url required for {transport} transport"
        if url and not url.startswith(("http://", "https://")):
            return "url must start with http:// or https://"
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
    _set_user_context(user)
    from ..mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    tools = []
    for name, status in hub._servers.items():
        if status.status == "connected" and status.session:
            try:
                resp = await status.session.list_tools()
                for t in resp.tools:
                    tools.append({"server": name, "name": t.name, "description": t.description or ""})
            except Exception:
                pass
    return JSONResponse({"tools": tools, "count": len(tools)})


async def mcp_toggle(request: Request):
    """POST /api/mcp/servers/{name}/toggle — enable/disable a server."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    server_name = request.path_params.get("name", "")
    from ..mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    status_obj = hub._servers.get(server_name)
    if not status_obj:
        return JSONResponse({"error": f"Server '{server_name}' not found"}, status_code=404)
    if role != "admin" and status_obj.config.owner_username != username:
        return JSONResponse({"error": "Not authorized"}, status_code=403)
    new_enabled = not status_obj.config.enabled
    status_obj.config.enabled = new_enabled
    hub._save_to_db(status_obj.config)
    if new_enabled:
        await hub._connect_server(status_obj.config)
    else:
        await hub._disconnect_server(server_name)
    record_audit(username, ACTION_MCP_SERVER_TOGGLE, details={"server": server_name, "enabled": new_enabled})
    return JSONResponse({"status": "ok", "enabled": new_enabled})


async def mcp_reconnect(request: Request):
    """POST /api/mcp/servers/{name}/reconnect — force reconnect."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    server_name = request.path_params.get("name", "")
    from ..mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    status_obj = hub._servers.get(server_name)
    if not status_obj:
        return JSONResponse({"error": f"Server '{server_name}' not found"}, status_code=404)
    await hub._disconnect_server(server_name)
    await hub._connect_server(status_obj.config)
    record_audit(username, ACTION_MCP_SERVER_RECONNECT, details={"server": server_name})
    return JSONResponse({"status": "ok"})


async def mcp_test_connection(request: Request):
    """POST /api/mcp/servers/test — test connection without persisting."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    transport = (body.get("transport") or "").strip()
    if transport not in ("stdio", "sse", "streamable_http"):
        return JSONResponse({"error": "transport must be stdio, sse, or streamable_http"}, status_code=400)
    val_err = _validate_mcp_config(body, transport)
    if val_err:
        return JSONResponse({"error": val_err}, status_code=400)
    from ..mcp_hub import get_mcp_hub, McpServerConfig
    config = McpServerConfig(
        name="__test__", transport=transport,
        command=body.get("command", ""), args=body.get("args", []),
        env=body.get("env", {}), cwd=body.get("cwd"),
        url=body.get("url", ""), headers=body.get("headers", {}),
        timeout=float(body.get("timeout", 5.0)))
    hub = get_mcp_hub()
    result = await hub.test_connection(config)
    status_code = 200 if result.get("status") == "ok" else 400
    return JSONResponse(result, status_code=status_code)


async def mcp_server_create(request: Request):
    """POST /api/mcp/servers — register a new MCP server."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    transport = (body.get("transport") or "").strip()
    if transport not in ("stdio", "sse", "streamable_http"):
        return JSONResponse({"error": "transport must be stdio, sse, or streamable_http"}, status_code=400)
    val_err = _validate_mcp_config(body, transport)
    if val_err:
        return JSONResponse({"error": val_err}, status_code=400)
    from ..mcp_hub import get_mcp_hub, McpServerConfig
    hub = get_mcp_hub()
    if name in hub._servers:
        return JSONResponse({"error": f"Server '{name}' already exists"}, status_code=409)
    config = McpServerConfig(
        name=name, transport=transport,
        command=body.get("command", ""), args=body.get("args", []),
        env=body.get("env", {}), cwd=body.get("cwd"),
        url=body.get("url", ""), headers=body.get("headers", {}),
        timeout=float(body.get("timeout", 30.0)),
        owner_username=username,
        is_shared=body.get("is_shared", False))
    hub._save_to_db(config)
    hub._servers[name] = hub._make_status(config)
    if config.enabled:
        await hub._connect_server(config)
    record_audit(username, ACTION_MCP_SERVER_CREATE, details={"server": name, "transport": transport})
    return JSONResponse({"status": "ok", "server": name}, status_code=201)


async def mcp_server_update(request: Request):
    """PUT /api/mcp/servers/{name} — update server config."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    server_name = request.path_params.get("name", "")
    from ..mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    status_obj = hub._servers.get(server_name)
    if not status_obj:
        return JSONResponse({"error": f"Server '{server_name}' not found"}, status_code=404)
    if role != "admin" and status_obj.config.owner_username != username:
        return JSONResponse({"error": "Not authorized"}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    transport = body.get("transport", status_obj.config.transport)
    val_err = _validate_mcp_config(body, transport, partial=True)
    if val_err:
        return JSONResponse({"error": val_err}, status_code=400)
    cfg = status_obj.config
    for field in ("command", "args", "env", "cwd", "url", "headers", "timeout", "transport", "enabled"):
        if field in body:
            setattr(cfg, field, body[field])
    hub._save_to_db(cfg)
    if cfg.enabled:
        await hub._disconnect_server(server_name)
        await hub._connect_server(cfg)
    record_audit(username, ACTION_MCP_SERVER_UPDATE, details={"server": server_name})
    return JSONResponse({"status": "ok"})


async def mcp_server_delete(request: Request):
    """DELETE /api/mcp/servers/{name} — remove a server."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    server_name = request.path_params.get("name", "")
    from ..mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    status_obj = hub._servers.get(server_name)
    if not status_obj:
        return JSONResponse({"error": f"Server '{server_name}' not found"}, status_code=404)
    if role != "admin" and status_obj.config.owner_username != username:
        return JSONResponse({"error": "Not authorized"}, status_code=403)
    await hub._disconnect_server(server_name)
    hub._delete_from_db(server_name)
    del hub._servers[server_name]
    record_audit(username, ACTION_MCP_SERVER_DELETE, details={"server": server_name})
    return JSONResponse({"status": "ok"})


async def mcp_servers_mine(request: Request):
    """GET /api/mcp/servers/mine — list servers owned by current user."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    from ..mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    mine = [s for s in hub.get_server_statuses() if s.get("owner_username") == username]
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
    record_audit(username, ACTION_MCP_SERVER_UPDATE, details={"server": server_name, "is_shared": is_shared})
    return JSONResponse({"status": "ok", "server": server_name, "is_shared": is_shared})
