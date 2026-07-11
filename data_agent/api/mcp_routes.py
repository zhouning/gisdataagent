"""MCP Hub routes — extracted from frontend_api.py (S-4 refactoring v12.1)."""

import os
import math
import logging
from typing import Optional
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context, _require_admin

logger = logging.getLogger("data_agent.api.mcp_routes")

_MCP_ALLOWED_COMMANDS = {"python", "python3", "node", "npx", "uvx", "docker", "deno"}
_MCP_ALLOWED_TRANSPORTS = {"stdio", "sse", "streamable_http"}
_MCP_MAX_TIMEOUT_SECONDS = 300.0
_MCP_METADATA_UPDATE_FIELDS = {"description", "category", "pipelines"}
_MCP_CONFIG_FIELDS = (
    "description", "transport", "enabled", "category", "pipelines",
    "command", "args", "env", "cwd", "url", "headers", "timeout",
    "bearer_token_env_var", "bearer_token_file_env_var", "ca_bundle_env_var",
    "system_managed", "expose_raw_tools",
    "is_shared",
)
_MCP_ADMIN_UPDATE_FIELDS = set(_MCP_CONFIG_FIELDS)


async def _read_mcp_body(request: Request):
    """Read an MCP request body and require a JSON object."""
    try:
        body = await request.json()
    except Exception:
        return None, JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    if not isinstance(body, dict):
        return None, JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    return body, None


def _validate_mcp_config(body: dict, transport: str, *, partial: bool = False) -> Optional[str]:
    """Validate MCP server config fields. Returns error message or None."""
    if not isinstance(transport, str) or transport not in _MCP_ALLOWED_TRANSPORTS:
        return "transport must be stdio, sse, or streamable_http"

    for field_name in (
        "description", "category", "command", "url",
        "bearer_token_env_var", "bearer_token_file_env_var", "ca_bundle_env_var",
    ):
        if field_name in body and not isinstance(body[field_name], str):
            return f"{field_name} must be a string"

    if (
        "cwd" in body
        and body["cwd"] is not None
        and not isinstance(body["cwd"], str)
    ):
        return "cwd must be a string or null"

    for field_name in ("enabled", "is_shared", "system_managed", "expose_raw_tools"):
        if field_name in body and not isinstance(body[field_name], bool):
            return f"{field_name} must be a boolean"

    for field_name in ("args", "pipelines"):
        value = body.get(field_name)
        if field_name in body and (not isinstance(value, list) or not all(
                isinstance(item, str) for item in value)):
            return f"{field_name} must be a list of strings"

    for field_name in ("env", "headers"):
        value = body.get(field_name)
        if field_name in body and (not isinstance(value, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in value.items())):
            return f"{field_name} must be a dict of string:string"

    if "timeout" in body:
        raw_timeout = body["timeout"]
        if isinstance(raw_timeout, bool):
            return f"timeout must be a number between 0 and {_MCP_MAX_TIMEOUT_SECONDS:g}"
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError):
            return f"timeout must be a number between 0 and {_MCP_MAX_TIMEOUT_SECONDS:g}"
        if not math.isfinite(timeout) or timeout <= 0 or timeout > _MCP_MAX_TIMEOUT_SECONDS:
            return f"timeout must be a number between 0 and {_MCP_MAX_TIMEOUT_SECONDS:g}"

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
    return None


def _mcp_config_body(config) -> dict:
    """Return the validated, mutable fields from an existing MCP config."""
    return {field_name: getattr(config, field_name) for field_name in _MCP_CONFIG_FIELDS}


def _reject_system_managed_mutation(hub, server_name: str):
    """Return a 403 response when a server is managed by process configuration."""
    status = hub._servers.get(server_name)
    if status and status.config.system_managed:
        return JSONResponse(
            {"error": f"Server '{server_name}' is system-managed"},
            status_code=403,
        )
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
    protected = _reject_system_managed_mutation(hub, server_name)
    if protected is not None:
        return protected
    result = await hub.toggle_server(server_name, enabled)
    if result.get("status") == "ok":
        from ..audit_logger import record_audit, ACTION_MCP_SERVER_TOGGLE
        record_audit(username, ACTION_MCP_SERVER_TOGGLE, details={"server": server_name, "enabled": enabled})
    status_code = (
        200 if result.get("status") == "ok"
        else 403 if result.get("status") == "forbidden"
        else 404
    )
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
    """POST /api/mcp/servers/test — test MCP server connection without saving."""
    user, username, role, err = _require_admin(request)
    if err:
        return err
    body, body_err = await _read_mcp_body(request)
    if body_err:
        return body_err
    transport = body.get("transport", "stdio")
    err = _validate_mcp_config(body, transport)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    from ..mcp_hub import get_mcp_hub, McpServerConfig
    config = McpServerConfig(
        name="__test__", transport=transport,
        command=body.get("command", ""), args=body.get("args", []),
        env=body.get("env", {}), cwd=body.get("cwd"),
        url=body.get("url", ""), headers=body.get("headers", {}),
        timeout=float(body.get("timeout", 5.0)),
        bearer_token_env_var=body.get("bearer_token_env_var", ""),
        bearer_token_file_env_var=body.get("bearer_token_file_env_var", ""),
        ca_bundle_env_var=body.get("ca_bundle_env_var", ""),
        system_managed=body.get("system_managed", False),
        expose_raw_tools=body.get("expose_raw_tools", True),
    )
    hub = get_mcp_hub()
    result = await hub.test_connection(config)
    status_code = 200 if result.get("status") == "ok" else 400
    return JSONResponse(result, status_code=status_code)


async def mcp_server_create(request: Request):
    """POST /api/mcp/servers — register a new MCP server (admin only)."""
    user, username, role, err = _require_admin(request)
    if err:
        return err
    body, body_err = await _read_mcp_body(request)
    if body_err:
        return body_err
    raw_name = body.get("name")
    if not isinstance(raw_name, str) or not raw_name.strip():
        return JSONResponse({"error": "name is required"}, status_code=400)
    name = raw_name.strip()
    transport = body.get("transport", "stdio")
    err = _validate_mcp_config(body, transport)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    from ..mcp_hub import get_mcp_hub, McpServerConfig
    config = McpServerConfig(
        name=name,
        description=body.get("description", ""),
        transport=transport,
        enabled=body.get("enabled", False),
        category=body.get("category", ""),
        pipelines=body.get("pipelines", ["general", "planner"]),
        command=body.get("command", ""),
        args=body.get("args", []),
        env=body.get("env", {}),
        cwd=body.get("cwd"),
        url=body.get("url", ""),
        headers=body.get("headers", {}),
        timeout=float(body.get("timeout", 5.0)),
        bearer_token_env_var=body.get("bearer_token_env_var", ""),
        bearer_token_file_env_var=body.get("bearer_token_file_env_var", ""),
        ca_bundle_env_var=body.get("ca_bundle_env_var", ""),
        system_managed=body.get("system_managed", False),
        expose_raw_tools=body.get("expose_raw_tools", True),
        owner_username=username,
        is_shared=body.get("is_shared", False),
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
    body, body_err = await _read_mcp_body(request)
    if body_err:
        return body_err

    body_fields = set(body)
    if role != "admin":
        if not body_fields.issubset(_MCP_METADATA_UPDATE_FIELDS):
            return JSONResponse({"error": "Permission denied"}, status_code=403)
    elif not body_fields.issubset(_MCP_ADMIN_UPDATE_FIELDS):
        return JSONResponse({"error": "Unknown update field"}, status_code=400)

    from ..mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    protected = _reject_system_managed_mutation(hub, server_name)
    if protected is not None:
        return protected
    if not hub._can_manage_server(server_name, username, role):
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    existing = hub._servers.get(server_name)
    if not existing:
        return JSONResponse({"error": f"Server '{server_name}' not found"}, status_code=404)

    candidate = _mcp_config_body(existing.config)
    candidate.update(body)
    transport = candidate.get("transport", "stdio")
    err = _validate_mcp_config(candidate, transport)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    updates = dict(body)
    if "timeout" in updates:
        updates["timeout"] = float(updates["timeout"])
    result = await hub.update_server(server_name, updates)
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
    protected = _reject_system_managed_mutation(hub, server_name)
    if protected is not None:
        return protected
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
    protected = _reject_system_managed_mutation(hub, server_name)
    if protected is not None:
        return protected
    status_obj.config.is_shared = is_shared
    hub._save_to_db(status_obj.config)
    from ..audit_logger import record_audit, ACTION_MCP_SERVER_UPDATE
    record_audit(username, ACTION_MCP_SERVER_UPDATE, details={"server": server_name, "is_shared": is_shared})
    return JSONResponse({"status": "ok", "server": server_name, "is_shared": is_shared})


async def mcp_rules_list(request: Request):
    """GET /api/mcp/rules — list tool selection rules."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    task_type = request.query_params.get("task_type", "")
    from ..mcp_hub import ToolRuleEngine
    rules = ToolRuleEngine.list_rules(task_type=task_type or None)
    return JSONResponse({"rules": rules})


async def mcp_rules_create(request: Request):
    """POST /api/mcp/rules — create a tool selection rule."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    task_type = body.get("task_type", "").strip()
    tool_name = body.get("tool_name", "").strip()
    server_name = body.get("server_name", "").strip()
    if not task_type or not tool_name or not server_name:
        return JSONResponse({"error": "task_type, tool_name, server_name required"}, status_code=400)

    from ..mcp_hub import ToolRuleEngine
    rule_id = ToolRuleEngine.add_rule(
        task_type=task_type, tool_name=tool_name, server_name=server_name,
        parameters=body.get("parameters"), priority=body.get("priority", 0),
        fallback_tool=body.get("fallback_tool"), fallback_server=body.get("fallback_server"),
    )
    if rule_id is None:
        return JSONResponse({"error": "Failed to create rule"}, status_code=500)
    return JSONResponse({"id": rule_id}, status_code=201)


async def mcp_rules_match(request: Request):
    """GET /api/mcp/rules/match — find best tool for a task type."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    task_type = request.query_params.get("task_type", "")
    if not task_type:
        return JSONResponse({"error": "task_type query param required"}, status_code=400)
    from ..mcp_hub import ToolRuleEngine
    match = ToolRuleEngine.match_tool(task_type)
    if not match:
        return JSONResponse({"error": f"No rule found for task_type '{task_type}'"}, status_code=404)
    return JSONResponse({"match": match})


async def mcp_rules_delete(request: Request):
    """DELETE /api/mcp/rules/{id} — delete a tool selection rule."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    rule_id = int(request.path_params["id"])
    from ..mcp_hub import ToolRuleEngine
    ok = ToolRuleEngine.delete_rule(rule_id)
    if not ok:
        return JSONResponse({"error": "Failed to delete rule"}, status_code=500)
    return JSONResponse({"deleted": rule_id})


def get_mcp_routes() -> list:
    """Return Route objects for MCP Hub endpoints."""
    return [
        Route("/api/mcp/servers", mcp_servers, methods=["GET"]),
        Route("/api/mcp/servers", mcp_server_create, methods=["POST"]),
        Route("/api/mcp/servers/mine", mcp_servers_mine, methods=["GET"]),
        Route("/api/mcp/tools", mcp_tools, methods=["GET"]),
        Route("/api/mcp/servers/test", mcp_test_connection, methods=["POST"]),
        Route("/api/mcp/rules", mcp_rules_list, methods=["GET"]),
        Route("/api/mcp/rules", mcp_rules_create, methods=["POST"]),
        Route("/api/mcp/rules/match", mcp_rules_match, methods=["GET"]),
        Route("/api/mcp/rules/{id:int}", mcp_rules_delete, methods=["DELETE"]),
        Route("/api/mcp/servers/{name:path}/toggle", mcp_toggle, methods=["POST"]),
        Route("/api/mcp/servers/{name:path}/reconnect", mcp_reconnect, methods=["POST"]),
        Route("/api/mcp/servers/{name:path}/share", mcp_server_share, methods=["POST"]),
        Route("/api/mcp/servers/{name:path}", mcp_server_update, methods=["PUT"]),
        Route("/api/mcp/servers/{name:path}", mcp_server_delete, methods=["DELETE"]),
    ]
