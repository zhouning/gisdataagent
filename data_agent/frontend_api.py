"""
Frontend Integration API — REST endpoints for the React three-panel frontend.

Provides:
- /api/catalog — data asset browsing and lineage
- /api/semantic — semantic hierarchy browsing
- /api/pipeline — user pipeline run history
- /api/user/token-usage — per-user token consumption
- /api/admin/users — user management (admin only)
- /api/admin/metrics/summary — aggregated dashboard metrics
- /api/workflows — workflow CRUD, execution, and run history (v5.4)

All user-facing endpoints use JWT cookie auth.
Admin endpoints require JWT + admin role.

Routes are mounted before the Chainlit catch-all via mount_frontend_api().
"""
import json
import os
import re
from typing import Optional

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from sqlalchemy import text

from .observability import get_logger
from .user_context import current_user_id, current_user_role
from .db_engine import get_engine
from .audit_logger import (
    record_audit,
    ACTION_MCP_SERVER_CREATE, ACTION_MCP_SERVER_UPDATE,
    ACTION_MCP_SERVER_DELETE, ACTION_MCP_SERVER_TOGGLE,
    ACTION_MCP_SERVER_RECONNECT,
)

logger = get_logger("frontend_api")


# ---------------------------------------------------------------------------
# Pending Map/Data Updates (shared with app.py)
# ---------------------------------------------------------------------------
# Chainlit's React client does not deliver step-level metadata to the frontend.
# This in-memory store + polling endpoint provides an alternative delivery path.
pending_map_updates: dict[str, dict] = {}   # user_id -> map config
pending_data_updates: dict[str, dict] = {}  # user_id -> data config


# ---------------------------------------------------------------------------
# Auth Helpers
# ---------------------------------------------------------------------------

def _get_user_from_request(request: Request):
    """Extract authenticated user from JWT in request cookies."""
    try:
        from chainlit.auth.cookie import get_token_from_cookies
        from chainlit.auth.jwt import decode_jwt
    except ImportError:
        return None
    token = get_token_from_cookies(dict(request.cookies))
    if not token:
        return None
    try:
        return decode_jwt(token)
    except Exception:
        return None


def _set_user_context(user):
    """Set ContextVars from a decoded JWT user object."""
    username = user.identifier if hasattr(user, "identifier") else str(user)
    role = "analyst"
    if hasattr(user, "metadata") and isinstance(user.metadata, dict):
        role = user.metadata.get("role", "analyst")
    current_user_id.set(username)
    current_user_role.set(role)
    return username, role


def _require_admin(request: Request):
    """Returns (user, username, role, error_response).

    If error_response is not None, the caller should return it immediately.
    """
    user = _get_user_from_request(request)
    if not user:
        return None, None, None, JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    if role != "admin":
        return user, username, role, JSONResponse({"error": "Admin required"}, status_code=403)
    return user, username, role, None


# ---------------------------------------------------------------------------
# Catalog API (reuses data_catalog.py)
# ---------------------------------------------------------------------------

async def _api_catalog_list(request: Request):
    """GET /api/catalog — list data assets for authenticated user."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    from .data_catalog import list_data_assets
    params = request.query_params
    result = list_data_assets(
        asset_type=params.get("asset_type", ""),
        tags=params.get("tags", ""),
        keyword=params.get("keyword", ""),
        storage_backend=params.get("storage_backend", ""),
    )
    return JSONResponse(result)


async def _api_catalog_detail(request: Request):
    """GET /api/catalog/{asset_id} — get full asset metadata."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    asset_id = request.path_params.get("asset_id", "")
    from .data_catalog import describe_data_asset
    result = describe_data_asset(asset_id)
    return JSONResponse(result)


async def _api_catalog_lineage(request: Request):
    """GET /api/catalog/{asset_id}/lineage — get data lineage."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    asset_id = request.path_params.get("asset_id", "")
    direction = request.query_params.get("direction", "both")
    from .data_catalog import get_data_lineage
    result = get_data_lineage(asset_id, direction)
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# Semantic Hierarchy API (reuses semantic_layer.py)
# ---------------------------------------------------------------------------

async def _api_semantic_domains(request: Request):
    """GET /api/semantic/domains — list available semantic domains."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    from .semantic_layer import _load_catalog
    catalog = _load_catalog()
    domains = []
    for name, info in catalog.get("domains", {}).items():
        domains.append({
            "name": name,
            "description": info.get("description", ""),
            "has_hierarchy": bool(info.get("hierarchy")),
        })
    return JSONResponse({"domains": domains})


async def _api_semantic_hierarchy(request: Request):
    """GET /api/semantic/hierarchy/{domain} — browse hierarchy tree."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    domain = request.path_params.get("domain", "LAND_USE")
    from .semantic_layer import browse_hierarchy
    result = browse_hierarchy(domain)
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# Pipeline History API (reuses audit_logger data)
# ---------------------------------------------------------------------------

async def _api_pipeline_history(request: Request):
    """GET /api/pipeline/history — user's own pipeline execution history."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)

    days = min(int(request.query_params.get("days", "30")), 90)
    limit = min(int(request.query_params.get("limit", "50")), 200)

    engine = get_engine()
    if not engine:
        return JSONResponse({"runs": [], "count": 0})

    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT details, created_at FROM agent_audit_log
                WHERE username = :u AND action = 'pipeline_complete'
                  AND created_at >= NOW() - make_interval(days => :d)
                ORDER BY created_at DESC LIMIT :lim
            """), {"u": username, "d": days, "lim": limit}).fetchall()

        runs = []
        for r in rows:
            details = r[0] if isinstance(r[0], dict) else json.loads(r[0] or "{}")
            runs.append({
                "timestamp": r[1].isoformat() if r[1] else None,
                "pipeline_type": details.get("pipeline_type", ""),
                "intent": details.get("intent", ""),
                "input_tokens": details.get("input_tokens", 0),
                "output_tokens": details.get("output_tokens", 0),
                "files_generated": details.get("files_generated", 0),
            })
        return JSONResponse({"runs": runs, "count": len(runs)})
    except Exception as e:
        logger.warning("Pipeline history query failed: %s", e)
        return JSONResponse({"runs": [], "count": 0})


# ---------------------------------------------------------------------------
# User Token Usage API
# ---------------------------------------------------------------------------

async def _api_user_token_usage(request: Request):
    """GET /api/user/token-usage — current user's token consumption."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)

    from .token_tracker import get_daily_usage, get_monthly_usage, check_usage_limit, get_pipeline_breakdown
    daily = get_daily_usage(username)
    monthly = get_monthly_usage(username)
    limits = check_usage_limit(username, role)
    breakdown = get_pipeline_breakdown(username)
    return JSONResponse({
        "daily": daily,
        "monthly": monthly,
        "limits": limits,
        "pipeline_breakdown": breakdown,
    })


# ---------------------------------------------------------------------------
# Admin: User Management
# ---------------------------------------------------------------------------

async def _api_admin_users_list(request: Request):
    """GET /api/admin/users — list all users (admin only)."""
    user, username, role, err = _require_admin(request)
    if err:
        return err

    engine = get_engine()
    if not engine:
        return JSONResponse({"users": []})

    try:
        from .database_tools import T_APP_USERS
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT id, username, display_name, role, auth_provider, created_at
                FROM {T_APP_USERS}
                ORDER BY created_at DESC
            """)).fetchall()
        users = []
        for r in rows:
            users.append({
                "id": r[0],
                "username": r[1],
                "display_name": r[2] or "",
                "role": r[3] or "analyst",
                "auth_provider": r[4] or "password",
                "created_at": r[5].isoformat() if r[5] else None,
            })
        return JSONResponse({"users": users, "count": len(users)})
    except Exception as e:
        logger.warning("User list query failed: %s", e)
        return JSONResponse({"users": [], "error": str(e)}, status_code=500)


async def _api_admin_update_role(request: Request):
    """PUT /api/admin/users/{username}/role — update user role (admin only)."""
    user, admin_name, _, err = _require_admin(request)
    if err:
        return err

    target_username = request.path_params.get("username", "")
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    new_role = body.get("role", "")
    if new_role not in ("admin", "analyst", "viewer"):
        return JSONResponse({"error": f"Invalid role: {new_role}"}, status_code=400)

    engine = get_engine()
    if not engine:
        return JSONResponse({"error": "Database not configured"}, status_code=503)

    try:
        from .database_tools import T_APP_USERS
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                UPDATE {T_APP_USERS} SET role = :role WHERE username = :u
            """), {"role": new_role, "u": target_username})
            conn.commit()
            if result.rowcount == 0:
                return JSONResponse({"error": "User not found"}, status_code=404)
        return JSONResponse({"status": "ok", "username": target_username, "role": new_role})
    except Exception as e:
        logger.warning("Role update failed: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


async def _api_admin_delete_user(request: Request):
    """DELETE /api/admin/users/{username} — delete user (admin only, cannot delete self)."""
    user, admin_name, _, err = _require_admin(request)
    if err:
        return err

    target_username = request.path_params.get("username", "")
    if target_username == admin_name:
        return JSONResponse({"error": "Cannot delete yourself"}, status_code=400)

    engine = get_engine()
    if not engine:
        return JSONResponse({"error": "Database not configured"}, status_code=503)

    try:
        from .database_tools import T_APP_USERS
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                DELETE FROM {T_APP_USERS} WHERE username = :u
            """), {"u": target_username})
            conn.commit()
            if result.rowcount == 0:
                return JSONResponse({"error": "User not found"}, status_code=404)
        return JSONResponse({"status": "ok", "deleted": target_username})
    except Exception as e:
        logger.warning("User delete failed: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Admin: Metrics Summary
# ---------------------------------------------------------------------------

async def _api_admin_metrics_summary(request: Request):
    """GET /api/admin/metrics/summary — aggregated metrics for admin dashboard."""
    user, username, role, err = _require_admin(request)
    if err:
        return err

    from .audit_logger import get_audit_stats
    audit_stats = get_audit_stats(days=30)

    # User count
    user_count = 0
    engine = get_engine()
    if engine:
        try:
            from .database_tools import T_APP_USERS
            with engine.connect() as conn:
                row = conn.execute(text(f"SELECT COUNT(*) FROM {T_APP_USERS}")).fetchone()
                user_count = row[0] if row else 0
        except Exception:
            pass

    return JSONResponse({
        "audit_stats": audit_stats,
        "user_count": user_count,
    })


# ---------------------------------------------------------------------------
# Map Annotations API
# ---------------------------------------------------------------------------

async def _api_annotations_list(request: Request):
    """GET /api/annotations — list user's annotations."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)

    team_id = request.query_params.get("team_id")
    from .map_annotations import list_annotations
    result = list_annotations(username, int(team_id) if team_id else None)
    return JSONResponse(result)


async def _api_annotations_create(request: Request):
    """POST /api/annotations — create a new annotation."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    lng = body.get("lng")
    lat = body.get("lat")
    if lng is None or lat is None:
        return JSONResponse({"error": "lng and lat are required"}, status_code=400)

    from .map_annotations import create_annotation
    result = create_annotation(
        username=username,
        lng=float(lng),
        lat=float(lat),
        title=body.get("title", ""),
        comment=body.get("comment", ""),
        color=body.get("color", "#e63946"),
        team_id=int(body["team_id"]) if body.get("team_id") else None,
    )
    status_code = 201 if result.get("status") == "success" else 400
    return JSONResponse(result, status_code=status_code)


async def _api_annotations_update(request: Request):
    """PUT /api/annotations/{id} — update an annotation."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)

    annotation_id = int(request.path_params.get("id", "0"))
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    from .map_annotations import update_annotation
    result = update_annotation(
        annotation_id=annotation_id,
        username=username,
        is_resolved=body.get("is_resolved"),
        title=body.get("title"),
        comment=body.get("comment"),
        color=body.get("color"),
    )
    return JSONResponse(result)


async def _api_annotations_delete(request: Request):
    """DELETE /api/annotations/{id} — delete an annotation."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)

    annotation_id = int(request.path_params.get("id", "0"))
    from .map_annotations import delete_annotation
    result = delete_annotation(annotation_id, username)
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# Basemap Configuration API
# ---------------------------------------------------------------------------

async def _api_config_basemaps(request: Request):
    """GET /api/config/basemaps — available basemap layers for frontend."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    import os
    tianditu_token = os.environ.get("TIANDITU_TOKEN", "")
    return JSONResponse({
        "gaode_enabled": True,
        "tianditu_enabled": bool(tianditu_token),
        "tianditu_token": tianditu_token,
    })


# ---------------------------------------------------------------------------
# User Account Self-Deletion API
# ---------------------------------------------------------------------------

async def _api_user_delete_account(request: Request):
    """DELETE /api/user/account — self-delete user account with password confirmation."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    password = body.get("password", "")
    if not password:
        return JSONResponse({"error": "Password required"}, status_code=400)

    from .auth import delete_user_account
    result = delete_user_account(username, password)
    status_code = 200 if result.get("status") == "success" else 400
    return JSONResponse(result, status_code=status_code)


# ---------------------------------------------------------------------------
# Sessions — thread history
# ---------------------------------------------------------------------------

async def _api_sessions_list(request: Request):
    """GET /api/sessions — list current user's chat threads."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    username = user.get("identifier") or user.get("id")
    engine = get_engine()
    if not engine:
        return JSONResponse({"sessions": []})

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                'SELECT id, name, "createdAt", "updatedAt" '
                'FROM "Thread" '
                'WHERE "userIdentifier" = :uid '
                'ORDER BY "updatedAt" DESC LIMIT 50'
            ), {"uid": username}).fetchall()
        sessions = [
            {"id": r[0], "name": r[1],
             "created_at": r[2].isoformat() if r[2] else None,
             "updated_at": r[3].isoformat() if r[3] else None}
            for r in rows
        ]
        return JSONResponse({"sessions": sessions})
    except Exception as e:
        logger.warning("Failed to list sessions: %s", e)
        return JSONResponse({"sessions": []})


async def _api_session_delete(request: Request):
    """DELETE /api/sessions/{session_id} — delete a chat thread."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    username = user.get("identifier") or user.get("id")
    session_id = request.path_params["session_id"]
    engine = get_engine()
    if not engine:
        return JSONResponse({"error": "Database not configured"}, status_code=500)

    try:
        with engine.connect() as conn:
            # Only delete if thread belongs to user
            result = conn.execute(text(
                'DELETE FROM "Thread" '
                'WHERE id = :sid AND "userIdentifier" = :uid'
            ), {"sid": session_id, "uid": username})
            conn.commit()
        if result.rowcount == 0:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return JSONResponse({"status": "deleted", "session_id": session_id})
    except Exception as e:
        logger.warning("Failed to delete session: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# MCP Tool Market API
# ---------------------------------------------------------------------------

async def _api_mcp_servers(request: Request):
    """GET /api/mcp/servers — list configured MCP servers with status."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    from .mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    servers = hub.get_server_statuses()
    return JSONResponse({"servers": servers, "count": len(servers)})


async def _api_mcp_tools(request: Request):
    """GET /api/mcp/tools — list all tools from connected MCP servers."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    server_name = request.query_params.get("server")
    from .mcp_hub import get_mcp_hub
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


async def _api_mcp_toggle(request: Request):
    """POST /api/mcp/servers/{name}/toggle — enable/disable a server (admin only)."""
    user, username, role, err = _require_admin(request)
    if err:
        return err

    server_name = request.path_params.get("name", "")
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    enabled = body.get("enabled", False)
    from .mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    result = await hub.toggle_server(server_name, enabled)
    if result.get("status") == "ok":
        record_audit(username, ACTION_MCP_SERVER_TOGGLE, details={"server": server_name, "enabled": enabled})
    status_code = 200 if result.get("status") == "ok" else 404
    return JSONResponse(result, status_code=status_code)


async def _api_mcp_reconnect(request: Request):
    """POST /api/mcp/servers/{name}/reconnect — force reconnect (admin only)."""
    user, username, role, err = _require_admin(request)
    if err:
        return err

    server_name = request.path_params.get("name", "")
    from .mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    result = await hub.reconnect_server(server_name)
    if result.get("status") == "ok":
        record_audit(username, ACTION_MCP_SERVER_RECONNECT, details={"server": server_name})
    status_code = 200 if result.get("status") == "ok" else 404
    return JSONResponse(result, status_code=status_code)


async def _api_mcp_test_connection(request: Request):
    """POST /api/mcp/servers/test — test MCP server connectivity (admin only)."""
    user, username, role, err = _require_admin(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    transport = body.get("transport", "stdio")
    val_err = _validate_mcp_config(body, transport)
    if val_err:
        return JSONResponse({"error": val_err}, status_code=400)

    from .mcp_hub import get_mcp_hub, McpServerConfig
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


_MCP_ALLOWED_COMMANDS = {"python", "python3", "node", "npx", "uvx", "docker", "deno"}


def _validate_mcp_config(body: dict, transport: str, *, partial: bool = False) -> Optional[str]:
    """Validate MCP server config fields. Returns error message or None.
    If partial=True, only validate fields present in body (for updates).
    """
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


async def _api_mcp_server_create(request: Request):
    """POST /api/mcp/servers — add a new MCP server (admin only)."""
    user, username, role, err = _require_admin(request)
    if err:
        return err

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    name = (body.get("name") or "").strip()
    if not name or len(name) > 100:
        return JSONResponse({"error": "Name required (max 100 chars)"}, status_code=400)

    transport = body.get("transport", "stdio")
    if transport not in ("stdio", "sse", "streamable_http"):
        return JSONResponse({"error": "Invalid transport type"}, status_code=400)

    val_err = _validate_mcp_config(body, transport)
    if val_err:
        return JSONResponse({"error": val_err}, status_code=400)

    from .mcp_hub import get_mcp_hub, McpServerConfig
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
    )

    hub = get_mcp_hub()
    result = await hub.add_server(config)
    if result.get("status") == "ok":
        record_audit(username, ACTION_MCP_SERVER_CREATE, details={"server": name, "transport": transport})
    status_code = 201 if result.get("status") == "ok" else 400
    return JSONResponse(result, status_code=status_code)


async def _api_mcp_server_update(request: Request):
    """PUT /api/mcp/servers/{name} — update an MCP server config (admin only)."""
    user, username, role, err = _require_admin(request)
    if err:
        return err

    server_name = request.path_params.get("name", "")
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    from .mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    # Determine transport for validation (from body or current config)
    transport = body.get("transport")
    if not transport:
        status_obj = hub._servers.get(server_name)
        transport = status_obj.config.transport if status_obj else "stdio"
    val_err = _validate_mcp_config(body, transport, partial=True)
    if val_err:
        return JSONResponse({"error": val_err}, status_code=400)

    result = await hub.update_server(server_name, body)
    if result.get("status") == "ok":
        record_audit(username, ACTION_MCP_SERVER_UPDATE, details={"server": server_name, "fields": list(body.keys())})
    status_code = 200 if result.get("status") == "ok" else 404
    return JSONResponse(result, status_code=status_code)


async def _api_mcp_server_delete(request: Request):
    """DELETE /api/mcp/servers/{name} — remove an MCP server (admin only)."""
    user, username, role, err = _require_admin(request)
    if err:
        return err

    server_name = request.path_params.get("name", "")
    from .mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    result = await hub.remove_server(server_name)
    if result.get("status") == "ok":
        record_audit(username, ACTION_MCP_SERVER_DELETE, details={"server": server_name})
    status_code = 200 if result.get("status") == "ok" else 404
    return JSONResponse(result, status_code=status_code)


# ---------------------------------------------------------------------------
# Workflows API (v5.4)
# ---------------------------------------------------------------------------

async def _api_workflows_list(request: Request):
    """GET /api/workflows — list workflows visible to current user."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)

    keyword = request.query_params.get("keyword", "")
    from .workflow_engine import list_workflows
    workflows = list_workflows(keyword=keyword)
    return JSONResponse({"workflows": workflows})


async def _api_workflows_create(request: Request):
    """POST /api/workflows — create a new workflow."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    name = body.get("workflow_name", "").strip()
    if not name:
        return JSONResponse({"error": "workflow_name is required"}, status_code=400)

    from .workflow_engine import create_workflow
    wf_id = create_workflow(
        name=name,
        description=body.get("description", ""),
        steps=body.get("steps", []),
        parameters=body.get("parameters", {}),
        graph_data=body.get("graph_data", {}),
        cron_schedule=body.get("cron_schedule"),
        webhook_url=body.get("webhook_url"),
        pipeline_type=body.get("pipeline_type", "general"),
    )
    if wf_id is None:
        return JSONResponse({"error": "Failed to create workflow"}, status_code=500)
    return JSONResponse({"id": wf_id, "workflow_name": name}, status_code=201)


async def _api_workflow_detail(request: Request):
    """GET /api/workflows/{id} — get workflow detail."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    wf_id = int(request.path_params["id"])
    from .workflow_engine import get_workflow
    wf = get_workflow(wf_id)
    if not wf:
        return JSONResponse({"error": "Workflow not found"}, status_code=404)
    return JSONResponse(wf)


async def _api_workflow_update(request: Request):
    """PUT /api/workflows/{id} — update workflow (owner only)."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    wf_id = int(request.path_params["id"])
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    from .workflow_engine import update_workflow
    ok = update_workflow(wf_id, **body)
    if not ok:
        return JSONResponse({"error": "Update failed or not authorized"}, status_code=403)
    return JSONResponse({"status": "ok"})


async def _api_workflow_delete(request: Request):
    """DELETE /api/workflows/{id} — delete workflow (owner only)."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    wf_id = int(request.path_params["id"])
    from .workflow_engine import delete_workflow
    ok = delete_workflow(wf_id)
    if not ok:
        return JSONResponse({"error": "Delete failed or not authorized"}, status_code=403)
    return JSONResponse({"status": "ok"})


async def _api_workflow_execute(request: Request):
    """POST /api/workflows/{id}/execute — execute workflow."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)

    wf_id = int(request.path_params["id"])
    try:
        body = await request.json()
    except Exception:
        body = {}

    param_overrides = body.get("parameters", {})

    from .workflow_engine import execute_workflow
    result = await execute_workflow(
        workflow_id=wf_id,
        param_overrides=param_overrides,
        run_by=username,
    )
    status_code = 200 if result.get("status") == "completed" else 500
    return JSONResponse(result, status_code=status_code)


async def _api_workflow_runs(request: Request):
    """GET /api/workflows/{id}/runs — get execution history."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    wf_id = int(request.path_params["id"])
    limit = int(request.query_params.get("limit", "20"))
    from .workflow_engine import get_workflow_runs
    runs = get_workflow_runs(wf_id, limit=limit)
    return JSONResponse({"runs": runs})


# ---------------------------------------------------------------------------
# Map/Data Pending Updates Endpoint
# ---------------------------------------------------------------------------

async def _api_map_pending(request: Request):
    """GET /api/map/pending — pop and return pending map/data updates for current user."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    uid = current_user_id.get("")
    result = {}
    map_cfg = pending_map_updates.pop(uid, None)
    if map_cfg:
        result["map_update"] = map_cfg
    data_cfg = pending_data_updates.pop(uid, None)
    if data_cfg:
        result["data_update"] = data_cfg
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# User Analysis Perspective API (v7.1)
# ---------------------------------------------------------------------------

async def _api_user_perspective_get(request: Request):
    """GET /api/user/analysis-perspective — get current user's analysis perspective."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)

    from .memory import get_analysis_perspective
    perspective = get_analysis_perspective()
    return JSONResponse({"perspective": perspective})


async def _api_user_perspective_put(request: Request):
    """PUT /api/user/analysis-perspective — update analysis perspective."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    perspective = body.get("perspective", "").strip()
    if len(perspective) > 2000:
        return JSONResponse({"error": "Perspective too long (max 2000 chars)"}, status_code=400)

    from .memory import save_memory, recall_memories, delete_memory

    if perspective:
        result = save_memory(
            "analysis_perspective",
            "user_perspective",
            json.dumps({"perspective": perspective}, ensure_ascii=False),
            "用户分析视角",
        )
    else:
        existing = recall_memories(memory_type="analysis_perspective")
        memories = existing.get("memories", [])
        if memories:
            delete_memory(str(memories[0]["id"]))
        result = {"status": "success", "message": "已清除分析视角"}

    status_code = 200 if result.get("status") == "success" else 400
    return JSONResponse(result, status_code=status_code)


# ---------------------------------------------------------------------------
# User Auto-Extract Memories API (v7.5)
# ---------------------------------------------------------------------------

async def _api_user_memories_list(request: Request):
    """GET /api/user/memories — list user's auto-extracted memories."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    from .memory import list_auto_extract_memories
    result = list_auto_extract_memories()
    return JSONResponse(result)


async def _api_user_memories_delete(request: Request):
    """DELETE /api/user/memories/{id} — delete a specific memory."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    memory_id = request.path_params.get("id", "0")
    from .memory import delete_memory
    result = delete_memory(str(memory_id))
    status_code = 200 if result.get("status") == "success" else 400
    return JSONResponse(result, status_code=status_code)


# ---------------------------------------------------------------------------
# Custom Skills CRUD (v8.0.1)
# ---------------------------------------------------------------------------

async def _api_skills_list(request: Request):
    """GET /api/skills — list custom skills for current user."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    from .custom_skills import list_custom_skills
    skills = list_custom_skills(include_shared=True)
    return JSONResponse({"skills": skills})


async def _api_skills_create(request: Request):
    """POST /api/skills — create a custom skill."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    from .custom_skills import (
        validate_skill_name, validate_instruction, validate_toolset_names,
        create_custom_skill, VALID_MODEL_TIERS,
    )
    # Validate
    err = validate_skill_name(body.get("skill_name", ""))
    if err:
        return JSONResponse({"error": err}, status_code=400)
    err = validate_instruction(body.get("instruction", ""))
    if err:
        return JSONResponse({"error": err}, status_code=400)
    err = validate_toolset_names(body.get("toolset_names") or [])
    if err:
        return JSONResponse({"error": err}, status_code=400)
    model_tier = body.get("model_tier", "standard")
    if model_tier not in VALID_MODEL_TIERS:
        return JSONResponse({"error": f"model_tier must be one of {sorted(VALID_MODEL_TIERS)}"}, status_code=400)

    skill_id = create_custom_skill(
        skill_name=body["skill_name"].strip(),
        instruction=body["instruction"].strip(),
        description=body.get("description", ""),
        toolset_names=body.get("toolset_names") or [],
        trigger_keywords=body.get("trigger_keywords") or [],
        model_tier=model_tier,
        is_shared=body.get("is_shared", False),
    )
    if skill_id is None:
        return JSONResponse({"error": "Failed to create skill (duplicate name?)"}, status_code=409)

    # Audit log
    try:
        from .audit_logger import record_audit, ACTION_CUSTOM_SKILL_CREATE
        record_audit(ACTION_CUSTOM_SKILL_CREATE, details={"skill_name": body["skill_name"], "id": skill_id})
    except Exception:
        pass

    return JSONResponse({"id": skill_id, "skill_name": body["skill_name"]}, status_code=201)


async def _api_skills_detail(request: Request):
    """GET /api/skills/{id} — get skill details."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    skill_id = request.path_params.get("id", 0)
    from .custom_skills import get_custom_skill
    skill = get_custom_skill(int(skill_id))
    if not skill:
        return JSONResponse({"error": "Skill not found"}, status_code=404)
    return JSONResponse(skill)


async def _api_skills_update(request: Request):
    """PUT /api/skills/{id} — update a custom skill."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    skill_id = int(request.path_params.get("id", 0))
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    from .custom_skills import (
        validate_skill_name, validate_instruction, validate_toolset_names,
        update_custom_skill, VALID_MODEL_TIERS,
    )
    # Partial validation — only validate fields present in body
    if "skill_name" in body:
        err = validate_skill_name(body["skill_name"])
        if err:
            return JSONResponse({"error": err}, status_code=400)
    if "instruction" in body:
        err = validate_instruction(body["instruction"])
        if err:
            return JSONResponse({"error": err}, status_code=400)
    if "toolset_names" in body:
        err = validate_toolset_names(body["toolset_names"] or [])
        if err:
            return JSONResponse({"error": err}, status_code=400)
    if "model_tier" in body and body["model_tier"] not in VALID_MODEL_TIERS:
        return JSONResponse({"error": f"model_tier must be one of {sorted(VALID_MODEL_TIERS)}"}, status_code=400)

    ok = update_custom_skill(skill_id, **body)
    if not ok:
        return JSONResponse({"error": "Skill not found or not owned by you"}, status_code=404)

    try:
        from .audit_logger import record_audit, ACTION_CUSTOM_SKILL_UPDATE
        record_audit(ACTION_CUSTOM_SKILL_UPDATE, details={"id": skill_id})
    except Exception:
        pass

    return JSONResponse({"ok": True})


async def _api_skills_delete(request: Request):
    """DELETE /api/skills/{id} — delete a custom skill."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    skill_id = int(request.path_params.get("id", 0))
    from .custom_skills import delete_custom_skill
    ok = delete_custom_skill(skill_id)
    if not ok:
        return JSONResponse({"error": "Skill not found or not owned by you"}, status_code=404)

    try:
        from .audit_logger import record_audit, ACTION_CUSTOM_SKILL_DELETE
        record_audit(ACTION_CUSTOM_SKILL_DELETE, details={"id": skill_id})
    except Exception:
        pass

    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Knowledge Base API (v8.0.2)
# ---------------------------------------------------------------------------


async def _api_kb_list(request: Request):
    """GET /api/kb — list user's knowledge bases."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    from .knowledge_base import list_knowledge_bases
    kbs = list_knowledge_bases(include_shared=True)
    return JSONResponse({"knowledge_bases": kbs})


async def _api_kb_create(request: Request):
    """POST /api/kb — create a knowledge base."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)

    from .knowledge_base import create_knowledge_base
    kb_id = create_knowledge_base(
        name=name,
        description=(body.get("description") or "").strip(),
        is_shared=body.get("is_shared", False),
    )
    if kb_id is None:
        return JSONResponse({"error": "Failed to create (duplicate name or limit reached)"}, status_code=409)

    try:
        from .audit_logger import record_audit, ACTION_KB_CREATE
        record_audit(ACTION_KB_CREATE, details={"kb_name": name, "id": kb_id})
    except Exception:
        pass

    return JSONResponse({"id": kb_id, "name": name}, status_code=201)


async def _api_kb_detail(request: Request):
    """GET /api/kb/{id} — knowledge base detail with documents."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    kb_id = int(request.path_params.get("id", 0))
    from .knowledge_base import get_knowledge_base, list_documents
    kb = get_knowledge_base(kb_id)
    if not kb:
        return JSONResponse({"error": "Knowledge base not found"}, status_code=404)
    docs = list_documents(kb_id)
    kb["documents"] = docs
    return JSONResponse(kb)


async def _api_kb_delete(request: Request):
    """DELETE /api/kb/{id} — delete a knowledge base."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    kb_id = int(request.path_params.get("id", 0))
    from .knowledge_base import delete_knowledge_base
    ok = delete_knowledge_base(kb_id)
    if not ok:
        return JSONResponse({"error": "Not found or not owned by you"}, status_code=404)

    try:
        from .audit_logger import record_audit, ACTION_KB_DELETE
        record_audit(ACTION_KB_DELETE, details={"id": kb_id})
    except Exception:
        pass

    return JSONResponse({"ok": True})


async def _api_kb_doc_upload(request: Request):
    """POST /api/kb/{id}/documents — upload a document to knowledge base."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    kb_id = int(request.path_params.get("id", 0))

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    text_content = (body.get("text") or "").strip()
    filename = (body.get("filename") or "document.txt").strip()
    if not text_content:
        return JSONResponse({"error": "text is required"}, status_code=400)

    from .knowledge_base import add_document
    doc_id = add_document(kb_id, filename, text_content, content_type=body.get("content_type"))
    if doc_id is None:
        return JSONResponse({"error": "Failed to add document"}, status_code=400)

    try:
        from .audit_logger import record_audit, ACTION_KB_DOC_ADD
        record_audit(ACTION_KB_DOC_ADD, details={"kb_id": kb_id, "filename": filename, "doc_id": doc_id})
    except Exception:
        pass

    return JSONResponse({"doc_id": doc_id, "filename": filename}, status_code=201)


async def _api_kb_doc_delete(request: Request):
    """DELETE /api/kb/{id}/documents/{doc_id} — delete a document."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    kb_id = int(request.path_params.get("id", 0))
    doc_id = int(request.path_params.get("doc_id", 0))
    from .knowledge_base import delete_document
    ok = delete_document(doc_id, kb_id)
    if not ok:
        return JSONResponse({"error": "Not found or not owned by you"}, status_code=404)

    try:
        from .audit_logger import record_audit, ACTION_KB_DOC_DELETE
        record_audit(ACTION_KB_DOC_DELETE, details={"kb_id": kb_id, "doc_id": doc_id})
    except Exception:
        pass

    return JSONResponse({"ok": True})


async def _api_kb_search(request: Request):
    """POST /api/kb/search — semantic search across knowledge bases."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    query = (body.get("query") or "").strip()
    if not query:
        return JSONResponse({"error": "query is required"}, status_code=400)

    from .knowledge_base import search_kb
    results = search_kb(
        query=query,
        kb_id=body.get("kb_id"),
        top_k=body.get("top_k", 5),
    )
    return JSONResponse({"results": results})


# ---------------------------------------------------------------------------
# Route Mounting
# ---------------------------------------------------------------------------

def get_frontend_api_routes():
    """Return list of Starlette routes for the frontend API."""
    return [
        Route("/api/catalog", endpoint=_api_catalog_list, methods=["GET"]),
        Route("/api/catalog/{asset_id:int}", endpoint=_api_catalog_detail, methods=["GET"]),
        Route("/api/catalog/{asset_id:int}/lineage", endpoint=_api_catalog_lineage, methods=["GET"]),
        Route("/api/semantic/domains", endpoint=_api_semantic_domains, methods=["GET"]),
        Route("/api/semantic/hierarchy/{domain}", endpoint=_api_semantic_hierarchy, methods=["GET"]),
        Route("/api/pipeline/history", endpoint=_api_pipeline_history, methods=["GET"]),
        Route("/api/user/token-usage", endpoint=_api_user_token_usage, methods=["GET"]),
        Route("/api/admin/users", endpoint=_api_admin_users_list, methods=["GET"]),
        Route("/api/admin/users/{username}/role", endpoint=_api_admin_update_role, methods=["PUT"]),
        Route("/api/admin/users/{username}", endpoint=_api_admin_delete_user, methods=["DELETE"]),
        Route("/api/admin/metrics/summary", endpoint=_api_admin_metrics_summary, methods=["GET"]),
        Route("/api/annotations", endpoint=_api_annotations_list, methods=["GET"]),
        Route("/api/annotations", endpoint=_api_annotations_create, methods=["POST"]),
        Route("/api/annotations/{id:int}", endpoint=_api_annotations_update, methods=["PUT"]),
        Route("/api/annotations/{id:int}", endpoint=_api_annotations_delete, methods=["DELETE"]),
        Route("/api/config/basemaps", endpoint=_api_config_basemaps, methods=["GET"]),
        Route("/api/user/account", endpoint=_api_user_delete_account, methods=["DELETE"]),
        Route("/api/user/analysis-perspective", endpoint=_api_user_perspective_get, methods=["GET"]),
        Route("/api/user/analysis-perspective", endpoint=_api_user_perspective_put, methods=["PUT"]),
        Route("/api/user/memories", endpoint=_api_user_memories_list, methods=["GET"]),
        Route("/api/user/memories/{id:int}", endpoint=_api_user_memories_delete, methods=["DELETE"]),
        Route("/api/sessions", endpoint=_api_sessions_list, methods=["GET"]),
        Route("/api/sessions/{session_id}", endpoint=_api_session_delete, methods=["DELETE"]),
        Route("/api/mcp/servers", endpoint=_api_mcp_servers, methods=["GET"]),
        Route("/api/mcp/servers", endpoint=_api_mcp_server_create, methods=["POST"]),
        Route("/api/mcp/tools", endpoint=_api_mcp_tools, methods=["GET"]),
        Route("/api/mcp/servers/test", endpoint=_api_mcp_test_connection, methods=["POST"]),
        Route("/api/mcp/servers/{name}/toggle", endpoint=_api_mcp_toggle, methods=["POST"]),
        Route("/api/mcp/servers/{name}/reconnect", endpoint=_api_mcp_reconnect, methods=["POST"]),
        Route("/api/mcp/servers/{name}", endpoint=_api_mcp_server_update, methods=["PUT"]),
        Route("/api/mcp/servers/{name}", endpoint=_api_mcp_server_delete, methods=["DELETE"]),
        # Workflows (v5.4)
        Route("/api/workflows", endpoint=_api_workflows_list, methods=["GET"]),
        Route("/api/workflows", endpoint=_api_workflows_create, methods=["POST"]),
        Route("/api/workflows/{id:int}", endpoint=_api_workflow_detail, methods=["GET"]),
        Route("/api/workflows/{id:int}", endpoint=_api_workflow_update, methods=["PUT"]),
        Route("/api/workflows/{id:int}", endpoint=_api_workflow_delete, methods=["DELETE"]),
        Route("/api/workflows/{id:int}/execute", endpoint=_api_workflow_execute, methods=["POST"]),
        Route("/api/workflows/{id:int}/runs", endpoint=_api_workflow_runs, methods=["GET"]),
        # Map/Data pending updates (v7.0 — bypass Chainlit metadata limitation)
        Route("/api/map/pending", endpoint=_api_map_pending, methods=["GET"]),
        # Custom Skills (v8.0.1)
        Route("/api/skills", endpoint=_api_skills_list, methods=["GET"]),
        Route("/api/skills", endpoint=_api_skills_create, methods=["POST"]),
        Route("/api/skills/{id:int}", endpoint=_api_skills_detail, methods=["GET"]),
        Route("/api/skills/{id:int}", endpoint=_api_skills_update, methods=["PUT"]),
        Route("/api/skills/{id:int}", endpoint=_api_skills_delete, methods=["DELETE"]),
        # Knowledge Base (v8.0.2)
        Route("/api/kb", endpoint=_api_kb_list, methods=["GET"]),
        Route("/api/kb", endpoint=_api_kb_create, methods=["POST"]),
        Route("/api/kb/search", endpoint=_api_kb_search, methods=["POST"]),
        Route("/api/kb/{id:int}", endpoint=_api_kb_detail, methods=["GET"]),
        Route("/api/kb/{id:int}", endpoint=_api_kb_delete, methods=["DELETE"]),
        Route("/api/kb/{id:int}/documents", endpoint=_api_kb_doc_upload, methods=["POST"]),
        Route("/api/kb/{id:int}/documents/{doc_id:int}", endpoint=_api_kb_doc_delete, methods=["DELETE"]),
    ]


def mount_frontend_api(app) -> bool:
    """Insert frontend API routes before Chainlit catch-all."""
    routes = get_frontend_api_routes()
    inserted = False
    for route in routes:
        for i, r in enumerate(app.router.routes):
            if hasattr(r, "path") and r.path == "/{full_path:path}":
                app.router.routes.insert(i, route)
                inserted = True
                break
        else:
            app.router.routes.append(route)
            inserted = True
    if inserted:
        logger.info("Frontend API routes mounted (%d endpoints)", len(routes))
    return inserted
