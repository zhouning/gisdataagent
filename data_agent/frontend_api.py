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
# Pipeline Analytics handlers (v9.0.5 — delegated to pipeline_analytics.py)
# ---------------------------------------------------------------------------

async def _api_analytics_latency(request: Request):
    from .pipeline_analytics import api_analytics_latency
    return await api_analytics_latency(request)

async def _api_analytics_tool_success(request: Request):
    from .pipeline_analytics import api_analytics_tool_success
    return await api_analytics_tool_success(request)

# Message Bus handlers (v15.9)
async def _api_messaging_stats(request: Request):
    from .api.messaging_routes import messaging_stats
    return await messaging_stats(request)

async def _api_messaging_list(request: Request):
    from .api.messaging_routes import list_messages
    return await list_messages(request)

async def _api_messaging_replay(request: Request):
    from .api.messaging_routes import replay_message
    return await replay_message(request)

async def _api_messaging_cleanup(request: Request):
    from .api.messaging_routes import cleanup_messages
    return await cleanup_messages(request)

async def _api_analytics_token_efficiency(request: Request):
    from .pipeline_analytics import api_analytics_token_efficiency
    return await api_analytics_token_efficiency(request)

async def _api_analytics_throughput(request: Request):
    from .pipeline_analytics import api_analytics_throughput
    return await api_analytics_throughput(request)

async def _api_analytics_agent_breakdown(request: Request):
    from .pipeline_analytics import api_analytics_agent_breakdown
    return await api_analytics_agent_breakdown(request)


# ---------------------------------------------------------------------------
# Pipeline SSE Streaming (v9.5.4)
# ---------------------------------------------------------------------------

async def _api_pipeline_stream(request: Request):
    """SSE streaming endpoint for pipeline execution."""
    import json
    from starlette.responses import StreamingResponse

    user = await _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    prompt = request.query_params.get("prompt", "")
    if not prompt:
        return JSONResponse({"error": "Missing prompt parameter"}, status_code=400)

    pipeline_type = request.query_params.get("pipeline", "general")

    async def event_generator():
        from .pipeline_runner import run_pipeline_streaming
        from google.adk.sessions import InMemorySessionService

        # Dynamically import agent
        try:
            if pipeline_type == "optimization":
                from .agent import data_pipeline as agent
            elif pipeline_type == "governance":
                from .agent import governance_pipeline as agent
            else:
                from .agent import general_pipeline as agent
        except ImportError:
            yield f"data: {json.dumps({'type': 'error', 'data': 'Pipeline not available'})}\n\n"
            return

        session_service = InMemorySessionService()

        async for event in run_pipeline_streaming(
            agent=agent,
            session_service=session_service,
            user_id=user["username"],
            session_id=f"stream-{user['username']}-{int(__import__('time').time())}",
            prompt=prompt,
            pipeline_type=pipeline_type,
            role=user.get("role", "analyst"),
        ):
            yield f"data: {json.dumps({'type': event.type, 'data': event.data, 'ts': event.timestamp})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Pending Map/Data Updates (shared with app.py)
# ---------------------------------------------------------------------------
# Chainlit's React client does not deliver step-level metadata to the frontend.
# This in-memory store + polling endpoint provides an alternative delivery path.
import threading as _threading

pending_map_updates: dict[str, dict] = {}   # user_id -> map config
pending_data_updates: dict[str, dict] = {}  # user_id -> data config
pending_chart_updates: dict[str, list] = {}  # user_id -> [chart configs]
_pending_lock = _threading.Lock()


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
        offset=int(params.get("offset", "0")),
        limit=int(params.get("limit", "50")),
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
    if result.get("status") == "success":
        try:
            from .data_distribution import log_access
            log_access(int(asset_id), user.identifier, "view")
        except Exception:
            pass
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


async def _api_catalog_search(request: Request):
    """GET /api/catalog/search — semantic hybrid search."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    q = request.query_params.get("q", "").strip()
    if not q:
        return JSONResponse({"error": "参数 q 必填"}, status_code=400)

    from .data_catalog import search_data_assets
    result = search_data_assets(q)
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


async def _api_user_change_password(request: Request):
    """PUT /api/user/password — change current user's password."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    old_password = body.get("old_password", "")
    new_password = body.get("new_password", "")
    if not old_password or not new_password:
        return JSONResponse({"error": "old_password and new_password required"}, status_code=400)

    from .auth import change_password
    result = change_password(username, old_password, new_password)
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
    """GET /api/mcp/servers — list MCP servers visible to current user."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    username, role = _set_user_context(user)

    from .mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    # Admins see all; non-admins see own + shared
    filter_user = None if role == "admin" else username
    servers = hub.get_server_statuses(username=filter_user)
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
    """POST /api/mcp/servers — add a new MCP server.

    Admins can create shared or private servers.
    Non-admins can only create private (is_shared=False) servers.
    """
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    username, role = _set_user_context(user)

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

    # Non-admins always create private servers
    is_shared = body.get("is_shared", False) if role == "admin" else False

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
        owner_username=username,
        is_shared=is_shared,
    )

    hub = get_mcp_hub()
    result = await hub.add_server(config)
    if result.get("status") == "ok":
        record_audit(username, ACTION_MCP_SERVER_CREATE, details={"server": name, "transport": transport})
    status_code = 201 if result.get("status") == "ok" else 400
    return JSONResponse(result, status_code=status_code)


async def _api_mcp_server_update(request: Request):
    """PUT /api/mcp/servers/{name} — update an MCP server config (owner or admin)."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    username, role = _set_user_context(user)

    server_name = request.path_params.get("name", "")
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    from .mcp_hub import get_mcp_hub
    hub = get_mcp_hub()

    # Ownership check
    if not hub._can_manage_server(server_name, username, role):
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    # Non-admins cannot change is_shared to True
    if role != "admin" and body.get("is_shared"):
        body["is_shared"] = False

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
    """DELETE /api/mcp/servers/{name} — remove an MCP server (owner or admin)."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    username, role = _set_user_context(user)

    server_name = request.path_params.get("name", "")
    from .mcp_hub import get_mcp_hub
    hub = get_mcp_hub()

    # Ownership check
    if not hub._can_manage_server(server_name, username, role):
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    result = await hub.remove_server(server_name)
    if result.get("status") == "ok":
        record_audit(username, ACTION_MCP_SERVER_DELETE, details={"server": server_name})
    status_code = 200 if result.get("status") == "ok" else 404
    return JSONResponse(result, status_code=status_code)


async def _api_mcp_servers_mine(request: Request):
    """GET /api/mcp/servers/mine — list only the current user's personal MCP servers."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    username, _role = _set_user_context(user)
    from .mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    all_servers = hub.get_server_statuses()
    mine = [s for s in all_servers if s.get("owner_username") == username]
    return JSONResponse({"servers": mine, "count": len(mine)})


async def _api_mcp_server_share(request: Request):
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
    from .mcp_hub import get_mcp_hub
    hub = get_mcp_hub()
    status_obj = hub._servers.get(server_name)
    if not status_obj:
        return JSONResponse({"error": f"Server '{server_name}' not found"}, status_code=404)

    status_obj.config.is_shared = is_shared
    hub._save_to_db(status_obj.config)
    record_audit(username, ACTION_MCP_SERVER_UPDATE, details={"server": server_name, "is_shared": is_shared})
    return JSONResponse({"status": "ok", "server": server_name, "is_shared": is_shared})



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

    from .workflow_engine import execute_workflow, execute_workflow_dag, get_workflow, _is_dag_workflow

    # Auto-detect DAG: if any step has depends_on, use DAG executor
    workflow = get_workflow(wf_id)
    steps = workflow.get("steps", []) if workflow else []
    if _is_dag_workflow(steps):
        result = await execute_workflow_dag(
            workflow_id=wf_id,
            param_overrides=param_overrides,
            run_by=username,
        )
    else:
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


async def _api_workflow_run_status(request: Request):
    """GET /api/workflows/{id}/runs/{run_id}/status — live per-node DAG execution status."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    run_id = int(request.path_params["run_id"])
    from .workflow_engine import get_live_run_status
    status = get_live_run_status(run_id)
    if status is None:
        return JSONResponse({"error": "Run not found or already completed"}, status_code=404)
    return JSONResponse(status)


# ---------------------------------------------------------------------------
# Map/Data Pending Updates Endpoint
# ---------------------------------------------------------------------------

async def _api_map_pending(request: Request):
    """GET /api/map/pending — pop and return pending map/data updates for current user."""
    user = _get_user_from_request(request)
    
    # Fallback for dev mode
    if user:
        _set_user_context(user)
    else:
        current_user_id.set("admin")

    uid = current_user_id.get("")
    
    logger.info(f"[/api/map/pending] user={uid}, pending_keys={list(pending_map_updates.keys())}")

    result = {}
    with _pending_lock:
        map_cfg = pending_map_updates.pop(uid, None)
        data_cfg = pending_data_updates.pop(uid, None)
    if map_cfg:
        result["map_update"] = map_cfg
    if data_cfg:
        result["data_update"] = data_cfg
    return JSONResponse(result)


async def _api_chart_pending(request: Request):
    """GET /api/chart/pending — pop and return pending chart updates for current user."""
    user = _get_user_from_request(request)
    if user:
        _set_user_context(user)
    else:
        current_user_id.set("admin")
    uid = current_user_id.get("")
    with _pending_lock:
        charts = pending_chart_updates.pop(uid, None)
    if charts:
        return JSONResponse({"chart_updates": charts})
    return JSONResponse({"chart_updates": []})


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


async def _api_memory_search(request: Request):
    """GET /api/memory/search — search user memories by keyword and type."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    keyword = request.query_params.get("keyword", "")
    memory_type = request.query_params.get("type", "")
    from .memory import recall_memories
    result = recall_memories(memory_type=memory_type, keyword=keyword)
    return JSONResponse(result)


async def _api_user_drawn_features(request: Request):
    """POST /api/user/drawn-features — save drawn GeoJSON features to user uploads."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        geojson = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    import json as _json, uuid as _uuid, os as _os
    from data_agent.user_context import get_user_upload_dir
    upload_dir = get_user_upload_dir()
    _os.makedirs(upload_dir, exist_ok=True)
    fname = f"drawn_{_uuid.uuid4().hex[:8]}.geojson"
    fpath = _os.path.join(upload_dir, fname)
    with open(fpath, 'w', encoding='utf-8') as f:
        _json.dump(geojson, f, ensure_ascii=False)
    return JSONResponse({"status": "ok", "file_path": fpath, "file_name": fname})


async def _api_pipeline_trace(request: Request):
    """GET /api/pipeline/trace/{trace_id} — get decision trace for a pipeline run."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    trace_id = request.path_params.get("trace_id", "")
    # Look up trace from session or DB
    import chainlit as cl
    decision_trace = cl.user_session.get("decision_trace")
    if decision_trace and decision_trace.trace_id == trace_id:
        result = decision_trace.to_dict()
        result["mermaid"] = decision_trace.to_mermaid_sequence()
        return JSONResponse(result)
    return JSONResponse({"error": "Trace not found"}, status_code=404)


# ---------------------------------------------------------------------------
# Capabilities (aggregated skills + toolsets listing)
# ---------------------------------------------------------------------------


async def _api_capabilities(request: Request):
    """GET /api/capabilities — aggregated built-in skills, custom skills, toolsets."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    from .capabilities import list_builtin_skills, list_toolsets
    from .custom_skills import list_custom_skills
    return JSONResponse({
        "builtin_skills": list_builtin_skills(),
        "custom_skills": list_custom_skills(include_shared=True),
        "toolsets": list_toolsets(),
    })


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
# Custom Skill Bundles API (v10.0.2)
# ---------------------------------------------------------------------------


async def _api_bundles_list(request: Request):
    """Delegate to api.bundle_routes (S-4 refactoring)."""
    from .api.bundle_routes import bundles_list
    return await bundles_list(request)


async def _api_bundles_create(request: Request):
    """Delegate to api.bundle_routes (S-4 refactoring)."""
    from .api.bundle_routes import bundles_create
    return await bundles_create(request)


async def _api_bundles_detail(request: Request):
    """Delegate to api.bundle_routes (S-4 refactoring)."""
    from .api.bundle_routes import bundles_detail
    return await bundles_detail(request)


async def _api_bundles_update(request: Request):
    """Delegate to api.bundle_routes (S-4 refactoring)."""
    from .api.bundle_routes import bundles_update
    return await bundles_update(request)


async def _api_bundles_delete(request: Request):
    """Delegate to api.bundle_routes (S-4 refactoring)."""
    from .api.bundle_routes import bundles_delete
    return await bundles_delete(request)


async def _api_bundles_available_tools(request: Request):
    """Delegate to api.bundle_routes (S-4 refactoring)."""
    from .api.bundle_routes import bundles_available_tools
    return await bundles_available_tools(request)


# ---------------------------------------------------------------------------
# Workflow Templates API (v10.0.4)
# ---------------------------------------------------------------------------


async def _api_templates_list(request: Request):
    """GET /api/templates — list published templates."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    category = request.query_params.get("category")
    keyword = request.query_params.get("keyword")
    from .workflow_templates import list_templates
    templates = list_templates(category=category, keyword=keyword)
    return JSONResponse({"templates": templates, "count": len(templates)})


async def _api_templates_create(request: Request):
    """POST /api/templates — create a new template."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    name = (body.get("template_name") or "").strip()
    if not name:
        return JSONResponse({"error": "template_name required"}, status_code=400)

    from .workflow_templates import create_template
    tid = create_template(
        template_name=name,
        description=body.get("description", ""),
        category=body.get("category", "general"),
        pipeline_type=body.get("pipeline_type", "general"),
        steps=body.get("steps", []),
        default_parameters=body.get("default_parameters", {}),
        tags=body.get("tags", []),
    )
    if tid is None:
        return JSONResponse({"error": "Failed to create template"}, status_code=400)
    return JSONResponse({"id": tid, "template_name": name}, status_code=201)


async def _api_templates_detail(request: Request):
    """GET /api/templates/{id} — get template detail."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    tid = int(request.path_params.get("id", 0))
    from .workflow_templates import get_template
    template = get_template(tid)
    if not template:
        return JSONResponse({"error": "Template not found"}, status_code=404)
    return JSONResponse(template)


async def _api_templates_update(request: Request):
    """PUT /api/templates/{id} — update a template (author only)."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    tid = int(request.path_params.get("id", 0))
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    from .workflow_templates import update_template
    ok = update_template(tid, **body)
    if not ok:
        return JSONResponse({"error": "Failed to update template"}, status_code=400)
    return JSONResponse({"status": "ok"})


async def _api_templates_delete(request: Request):
    """DELETE /api/templates/{id} — delete a template (author only)."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    tid = int(request.path_params.get("id", 0))
    from .workflow_templates import delete_template
    ok = delete_template(tid)
    if not ok:
        return JSONResponse({"error": "Template not found"}, status_code=404)
    return JSONResponse({"status": "ok"})


async def _api_templates_clone(request: Request):
    """POST /api/templates/{id}/clone — clone template as user's workflow."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    tid = int(request.path_params.get("id", 0))
    try:
        body = await request.json()
    except Exception:
        body = {}

    from .workflow_templates import clone_template
    wf_id = clone_template(tid,
                           workflow_name=body.get("workflow_name"),
                           param_overrides=body.get("parameters"))
    if wf_id is None:
        return JSONResponse({"error": "Failed to clone template"}, status_code=400)
    return JSONResponse({"status": "ok", "workflow_id": wf_id}, status_code=201)


# ---------------------------------------------------------------------------
# Knowledge Base API (v8.0.2)
# ---------------------------------------------------------------------------


async def _api_kb_list(request: Request):
    from .api.kb_routes import kb_list
    return await kb_list(request)

async def _api_kb_create(request: Request):
    from .api.kb_routes import kb_create
    return await kb_create(request)

async def _api_kb_detail(request: Request):
    from .api.kb_routes import kb_detail
    return await kb_detail(request)

async def _api_kb_delete(request: Request):
    from .api.kb_routes import kb_delete
    return await kb_delete(request)

async def _api_kb_doc_upload(request: Request):
    from .api.kb_routes import kb_doc_upload
    return await kb_doc_upload(request)

async def _api_kb_doc_delete(request: Request):
    from .api.kb_routes import kb_doc_delete
    return await kb_doc_delete(request)

async def _api_kb_search(request: Request):
    from .api.kb_routes import kb_search
    return await kb_search(request)

async def _api_kb_build_graph(request: Request):
    from .api.kb_routes import kb_build_graph
    return await kb_build_graph(request)

async def _api_kb_graph(request: Request):
    from .api.kb_routes import kb_graph
    return await kb_graph(request)

async def _api_kb_graph_search(request: Request):
    from .api.kb_routes import kb_graph_search
    return await kb_graph_search(request)

async def _api_kb_entities(request: Request):
    from .api.kb_routes import kb_entities
    return await kb_entities(request)


# ---------------------------------------------------------------------------
# Task Queue API (v11.0.1)
# ---------------------------------------------------------------------------


async def _api_tasks_submit(request: Request):
    """POST /api/tasks/submit — submit a new background task."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return JSONResponse({"error": "prompt required"}, status_code=400)

    from .task_queue import get_task_queue
    queue = get_task_queue()
    try:
        job_id = queue.submit(
            user_id=username,
            prompt=prompt,
            pipeline_type=body.get("pipeline_type", "general"),
            priority=body.get("priority", 5),
            role=role,
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=429)

    return JSONResponse({"job_id": job_id, "status": "queued"}, status_code=201)


async def _api_tasks_list(request: Request):
    """GET /api/tasks — list tasks for current user."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)

    status_filter = request.query_params.get("status")
    from .task_queue import get_task_queue
    queue = get_task_queue()
    # Admins can see all, others see own
    uid = None if role == "admin" else username
    jobs = queue.list_jobs(user_id=uid, status=status_filter)
    return JSONResponse({"jobs": jobs, "count": len(jobs), "stats": queue.queue_stats})


async def _api_tasks_detail(request: Request):
    """GET /api/tasks/{job_id} — get task status."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    job_id = request.path_params.get("job_id", "")
    from .task_queue import get_task_queue
    queue = get_task_queue()
    job = queue.get_status(job_id)
    if not job:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    return JSONResponse(job)


async def _api_tasks_cancel(request: Request):
    """DELETE /api/tasks/{job_id} — cancel a task."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    job_id = request.path_params.get("job_id", "")
    from .task_queue import get_task_queue
    queue = get_task_queue()
    ok = queue.cancel(job_id)
    if not ok:
        return JSONResponse({"error": "Task not found or not cancellable"}, status_code=404)
    return JSONResponse({"status": "cancelled", "job_id": job_id})


# ---------------------------------------------------------------------------
# Proactive Suggestions API (v11.0.3)
# ---------------------------------------------------------------------------


async def _api_suggestions_list(request: Request):
    """GET /api/suggestions — list pending analysis suggestions."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role = _set_user_context(user)

    from .proactive_explorer import get_suggestions
    suggestions = get_suggestions(username)
    return JSONResponse({"suggestions": suggestions, "count": len(suggestions)})


async def _api_suggestions_execute(request: Request):
    """POST /api/suggestions/{id}/execute — execute a suggestion via task queue."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)

    obs_id = request.path_params.get("id", "")
    try:
        body = await request.json()
    except Exception:
        body = {}

    prompt = body.get("prompt", "")
    pipeline_type = body.get("pipeline_type", "general")

    if not prompt:
        return JSONResponse({"error": "prompt required"}, status_code=400)

    from .task_queue import get_task_queue
    queue = get_task_queue()
    try:
        job_id = queue.submit(username, prompt, pipeline_type, role=role)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=429)

    return JSONResponse({"job_id": job_id, "status": "queued"}, status_code=201)


async def _api_suggestions_dismiss(request: Request):
    """POST /api/suggestions/{id}/dismiss — dismiss a suggestion."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    obs_id = request.path_params.get("id", "")
    from .proactive_explorer import dismiss_suggestion
    ok = dismiss_suggestion(obs_id)
    if not ok:
        return JSONResponse({"error": "Suggestion not found"}, status_code=404)
    return JSONResponse({"status": "dismissed"})


# ---------------------------------------------------------------------------
# System Status API (v12.0)
# ---------------------------------------------------------------------------


async def _api_system_status(request: Request):
    """GET /api/system/status — aggregated system health for admin dashboard."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    from .health import check_database, check_mcp_hub, _get_feature_flags

    # Database
    db = check_database()

    # MCP Hub
    mcp = check_mcp_hub()

    # Feature flags (arcpy, cloud, streaming, planner)
    flags = _get_feature_flags()

    # Bots status
    bots = {}
    for bot_name, module_name, func_name, env_keys in [
        ("wecom", "wecom_bot", "is_wecom_configured",
         ["WECOM_CORP_ID", "WECOM_APP_SECRET", "WECOM_TOKEN", "WECOM_ENCODING_AES_KEY", "WECOM_AGENT_ID"]),
        ("dingtalk", "dingtalk_bot", "is_dingtalk_configured",
         ["DINGTALK_APP_KEY", "DINGTALK_APP_SECRET", "DINGTALK_ROBOT_CODE"]),
        ("feishu", "feishu_bot", "is_feishu_configured",
         ["FEISHU_APP_ID", "FEISHU_APP_SECRET"]),
    ]:
        import importlib
        try:
            mod = importlib.import_module(f".{module_name}", package="data_agent")
            configured = getattr(mod, func_name)()
        except Exception:
            configured = False
        missing = [k for k in env_keys if not os.environ.get(k)]
        bots[bot_name] = {
            "configured": configured,
            "missing_env": missing,
        }

    # A2A status
    try:
        from .a2a_server import get_a2a_status, A2A_ENABLED
        a2a = get_a2a_status()
    except Exception:
        a2a = {"enabled": False}

    # Model config
    import os as _os
    model_config = {
        "fast": _os.environ.get("MODEL_FAST", "gemini-2.0-flash"),
        "standard": _os.environ.get("MODEL_STANDARD", "gemini-2.5-flash"),
        "premium": _os.environ.get("MODEL_PREMIUM", "gemini-2.5-pro"),
        "router": "gemini-2.0-flash",
    }

    return JSONResponse({
        "database": db,
        "mcp_hub": mcp,
        "bots": bots,
        "a2a": a2a,
        "features": flags,
        "models": model_config,
    })


async def _api_bots_status(request: Request):
    """GET /api/bots/status — detailed bot status for each platform."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    result = {}
    for bot_name, module_name, func_name, env_keys, label in [
        ("wecom", "wecom_bot", "is_wecom_configured",
         ["WECOM_CORP_ID", "WECOM_APP_SECRET", "WECOM_TOKEN", "WECOM_ENCODING_AES_KEY", "WECOM_AGENT_ID"],
         "企业微信"),
        ("dingtalk", "dingtalk_bot", "is_dingtalk_configured",
         ["DINGTALK_APP_KEY", "DINGTALK_APP_SECRET", "DINGTALK_ROBOT_CODE"],
         "钉钉"),
        ("feishu", "feishu_bot", "is_feishu_configured",
         ["FEISHU_APP_ID", "FEISHU_APP_SECRET"],
         "飞书"),
    ]:
        import importlib
        try:
            mod = importlib.import_module(f".{module_name}", package="data_agent")
            configured = getattr(mod, func_name)()
        except Exception:
            configured = False
        configured_keys = [k for k in env_keys if os.environ.get(k)]
        missing_keys = [k for k in env_keys if not os.environ.get(k)]
        result[bot_name] = {
            "label": label,
            "configured": configured,
            "total_env_keys": len(env_keys),
            "configured_keys": len(configured_keys),
            "missing_keys": missing_keys,
        }

    return JSONResponse({"bots": result})


async def _api_config_models(request: Request):
    """GET /api/config/models — current LLM model configuration."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    from .agent import get_model_config
    config = get_model_config()

    # Add provider detection
    for tier_info in config["tiers"].values():
        model = tier_info["model"]
        if "gemini" in model.lower():
            tier_info["provider"] = "Google Gemini"
        elif "claude" in model.lower():
            tier_info["provider"] = "Anthropic"
        elif "gpt" in model.lower() or "o1" in model.lower() or "o3" in model.lower():
            tier_info["provider"] = "OpenAI"
        else:
            tier_info["provider"] = "LiteLLM / Other"

    router_model = config["router_model"]
    if "gemini" in router_model.lower():
        config["router_provider"] = "Google Gemini"
    elif "claude" in router_model.lower():
        config["router_provider"] = "Anthropic"
    else:
        config["router_provider"] = "Other"

    return JSONResponse(config)


# ---------------------------------------------------------------------------
# A2A Server API (v11.0.4)
# ---------------------------------------------------------------------------


async def _api_a2a_card(request: Request):
    """GET /api/a2a/card — return the A2A agent card."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    from .a2a_server import build_agent_card
    card = build_agent_card()
    return JSONResponse(card)


async def _api_a2a_status(request: Request):
    """GET /api/a2a/status — A2A server status."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    from .a2a_server import get_a2a_status
    return JSONResponse(get_a2a_status())


# ---------------------------------------------------------------------------
# User-Defined Tools API (v12.0)
# ---------------------------------------------------------------------------

async def _api_user_tools_list(request: Request):
    """GET /api/user-tools — list user's tools + shared."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    from .user_tools import list_user_tools
    tools = list_user_tools()
    return JSONResponse({"tools": tools, "count": len(tools)})


async def _api_user_tools_create(request: Request):
    """POST /api/user-tools — create a new user tool."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    from .user_tools import (
        create_user_tool, validate_tool_name,
        validate_parameters, validate_template_config,
    )

    tool_name = (body.get("tool_name") or "").strip()
    err = validate_tool_name(tool_name)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    parameters = body.get("parameters", [])
    err = validate_parameters(parameters)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    template_type = (body.get("template_type") or "").strip()
    template_config = body.get("template_config", {})
    err = validate_template_config(template_type, template_config)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    # Python sandbox: validate code via AST
    if template_type == "python_sandbox":
        python_code = template_config.get("python_code", "")
        if not python_code.strip():
            return JSONResponse({"error": "python_sandbox requires python_code in template_config"}, status_code=400)
        from .user_tools import validate_python_code
        code_err = validate_python_code(python_code)
        if code_err:
            return JSONResponse({"error": code_err}, status_code=400)

    tool_id = create_user_tool(
        tool_name=tool_name,
        description=body.get("description", ""),
        parameters=parameters,
        template_type=template_type,
        template_config=template_config,
        is_shared=body.get("is_shared", False),
        timeout_seconds=body.get("timeout_seconds", 30),
    )
    if tool_id is None:
        return JSONResponse({"error": "Failed to create tool (limit reached or duplicate name)"}, status_code=400)

    return JSONResponse({"id": tool_id, "tool_name": tool_name}, status_code=201)


async def _api_user_tools_detail(request: Request):
    """GET /api/user-tools/{id} — get tool detail."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    tool_id = int(request.path_params.get("id", 0))
    from .user_tools import get_user_tool
    tool = get_user_tool(tool_id)
    if not tool:
        return JSONResponse({"error": "Tool not found"}, status_code=404)
    return JSONResponse(tool)


async def _api_user_tools_update(request: Request):
    """PUT /api/user-tools/{id} — update a tool (owner only)."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    tool_id = int(request.path_params.get("id", 0))
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    # Validate fields if provided
    from .user_tools import (
        update_user_tool, validate_tool_name,
        validate_parameters, validate_template_config,
    )

    if "tool_name" in body:
        err = validate_tool_name(body["tool_name"])
        if err:
            return JSONResponse({"error": err}, status_code=400)
    if "parameters" in body:
        err = validate_parameters(body["parameters"])
        if err:
            return JSONResponse({"error": err}, status_code=400)
    if "template_type" in body and "template_config" in body:
        err = validate_template_config(body["template_type"], body["template_config"])
        if err:
            return JSONResponse({"error": err}, status_code=400)
        if body["template_type"] == "python_sandbox":
            python_code = body["template_config"].get("python_code", "")
            if not python_code.strip():
                return JSONResponse({"error": "python_sandbox requires python_code"}, status_code=400)
            from .user_tools import validate_python_code
            code_err = validate_python_code(python_code)
            if code_err:
                return JSONResponse({"error": code_err}, status_code=400)

    ok = update_user_tool(tool_id, **body)
    if not ok:
        return JSONResponse({"error": "Failed to update tool"}, status_code=400)
    return JSONResponse({"status": "ok"})


async def _api_user_tools_delete(request: Request):
    """DELETE /api/user-tools/{id} — delete a tool (owner only)."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    tool_id = int(request.path_params.get("id", 0))
    from .user_tools import delete_user_tool
    ok = delete_user_tool(tool_id)
    if not ok:
        return JSONResponse({"error": "Failed to delete tool"}, status_code=404)
    return JSONResponse({"status": "ok"})


async def _api_user_tools_test(request: Request):
    """POST /api/user-tools/{id}/test — dry-run a tool with sample params."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    tool_id = int(request.path_params.get("id", 0))
    from .user_tools import get_user_tool
    tool = get_user_tool(tool_id)
    if not tool:
        return JSONResponse({"error": "Tool not found"}, status_code=404)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    test_params = body.get("params", {})
    from .user_tool_engines import _dispatch_engine
    try:
        result = _dispatch_engine(tool, test_params)
        return JSONResponse({"status": "ok", "result": result})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


async def _api_user_tools_rate(request: Request):
    """POST /api/user-tools/{id}/rate — rate a shared user tool (1-5)."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    tool_id = int(request.path_params.get("id", 0))
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    score = body.get("score", 0)
    if not isinstance(score, int) or score < 1 or score > 5:
        return JSONResponse({"error": "score must be 1-5"}, status_code=400)
    from .user_tools import rate_tool
    if rate_tool(tool_id, score):
        return JSONResponse({"ok": True})
    return JSONResponse({"error": "Tool not found or not shared"}, status_code=404)


async def _api_user_tools_clone(request: Request):
    """POST /api/user-tools/{id}/clone — clone a shared user tool to current user."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    tool_id = int(request.path_params.get("id", 0))
    try:
        body = await request.json()
    except Exception:
        body = {}
    from .user_tools import clone_tool
    new_id = clone_tool(tool_id, username, new_name=body.get("tool_name"))
    if new_id is None:
        return JSONResponse({"error": "Clone failed (not found or not shared)"}, status_code=404)
    return JSONResponse({"ok": True, "id": new_id}, status_code=201)


async def _api_marketplace(request: Request):
    """GET /api/marketplace — aggregated view of all shared skills/tools/templates/bundles."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    sort_by = request.query_params.get("sort", "rating")  # rating | usage | recent

    items = []
    # Shared custom skills
    try:
        from .custom_skills import list_custom_skills
        for s in list_custom_skills(include_shared=True):
            if s.get("is_shared"):
                rating_count = s.get("rating_count", 0) or 0
                rating_avg = round(s.get("rating_sum", 0) / rating_count, 1) if rating_count else 0
                items.append({
                    "id": s["id"], "name": s["skill_name"], "type": "skill",
                    "description": s.get("description", ""),
                    "owner": s["owner_username"],
                    "rating": rating_avg, "rating_count": rating_count,
                    "clone_count": s.get("clone_count", 0) or 0,
                    "created_at": s.get("created_at"),
                })
    except Exception:
        pass

    # Shared user tools
    try:
        from .user_tools import list_user_tools
        for t in list_user_tools(include_shared=True):
            if t.get("is_shared"):
                rating_count = t.get("rating_count", 0) or 0
                rating_avg = round(t.get("rating_sum", 0) / rating_count, 1) if rating_count else 0
                items.append({
                    "id": t["id"], "name": t["tool_name"], "type": "tool",
                    "description": t.get("description", ""),
                    "template_type": t.get("template_type", ""),
                    "owner": t["owner_username"],
                    "rating": rating_avg, "rating_count": rating_count,
                    "clone_count": t.get("clone_count", 0) or 0,
                    "created_at": t.get("created_at"),
                })
    except Exception:
        pass

    # Published workflow templates
    try:
        from .workflow_templates import list_templates
        for tmpl in list_templates():
            if tmpl.get("is_published"):
                rc = tmpl.get("rating_count", 0) or 0
                items.append({
                    "id": tmpl["id"], "name": tmpl["template_name"], "type": "template",
                    "description": tmpl.get("description", ""),
                    "category": tmpl.get("category", ""),
                    "owner": tmpl.get("owner_username", ""),
                    "rating": round(tmpl.get("rating_sum", 0) / rc, 1) if rc else 0,
                    "rating_count": rc,
                    "clone_count": tmpl.get("clone_count", 0) or 0,
                    "created_at": tmpl.get("created_at"),
                })
    except Exception:
        pass

    # Shared skill bundles
    try:
        from .custom_skill_bundles import list_skill_bundles
        for b in list_skill_bundles():
            if b.get("is_shared"):
                items.append({
                    "id": b["id"], "name": b["bundle_name"], "type": "bundle",
                    "description": b.get("description", ""),
                    "owner": b.get("owner_username", ""),
                    "rating": 0, "rating_count": 0,
                    "clone_count": b.get("use_count", 0) or 0,
                    "created_at": b.get("created_at"),
                })
    except Exception:
        pass

    # Sort
    if sort_by == "rating":
        items.sort(key=lambda x: (x.get("rating", 0), x.get("clone_count", 0)), reverse=True)
    elif sort_by == "usage":
        items.sort(key=lambda x: x.get("clone_count", 0), reverse=True)
    else:  # recent
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    return JSONResponse({"items": items, "count": len(items)})


async def _api_drl_scenarios(request: Request):
    """GET /api/drl/scenarios — list available DRL scenario templates."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    from .drl_engine import list_scenarios
    return JSONResponse({"scenarios": list_scenarios()})


async def _api_drl_run_custom(request: Request):
    """POST /api/drl/run-custom — run DRL optimization with custom weights."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    body = await request.json()
    scenario_id = body.get("scenario_id", "farmland_optimization")
    data_path = body.get("data_path", "")
    if not data_path:
        return JSONResponse({"error": "data_path 必填"}, status_code=400)

    # Validate weight ranges
    weights = {}
    for key, lo, hi in [
        ("slope_weight", 100, 3000),
        ("contiguity_weight", 100, 2000),
        ("balance_weight", 100, 2000),
        ("pair_bonus", 0.1, 10.0),
    ]:
        val = body.get(key)
        if val is not None:
            try:
                fval = float(val)
                if not (lo <= fval <= hi):
                    return JSONResponse(
                        {"error": f"{key} 须在 [{lo}, {hi}] 范围内，当前值: {fval}"},
                        status_code=400,
                    )
                weights[key] = str(fval)
            except (ValueError, TypeError):
                return JSONResponse({"error": f"{key} 须为数值"}, status_code=400)

    import asyncio
    from .toolsets.analysis_tools import drl_model
    try:
        result = await asyncio.to_thread(
            drl_model,
            data_path,
            scenario_id,
            weights.get("slope_weight", ""),
            weights.get("contiguity_weight", ""),
            weights.get("balance_weight", ""),
            weights.get("pair_bonus", ""),
        )
        if isinstance(result, dict):
            return JSONResponse(result)
        import json
        return JSONResponse(json.loads(result) if result.startswith("{") else {"result": result})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def _api_drl_explain(request: Request):
    """POST /api/drl/explain — explain DRL decision feature importance."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        body = {}

    scenario_id = body.get("scenario_id", "farmland_optimization")

    # Try to find model weights
    import os
    model_path = os.path.join(os.path.dirname(__file__), "weights", "scorer_weights_v7")

    from data_agent.drl_interpretability import explain_drl_decision, get_scenario_feature_summary

    # If no model available, return scenario-based summary
    if not os.path.exists(model_path + ".zip"):
        summary = get_scenario_feature_summary(scenario_id)
        return JSONResponse({"status": "ok", "mode": "scenario_based", **summary})

    upload_dir = os.path.join(os.path.dirname(__file__), "uploads", username)
    os.makedirs(upload_dir, exist_ok=True)

    result = explain_drl_decision(model_path, output_dir=upload_dir)
    return JSONResponse(result)


async def _api_drl_history(request: Request):
    """GET /api/drl/history — list DRL optimization run history."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    from data_agent.drl_engine import list_run_history
    runs = list_run_history(username)
    return JSONResponse({"runs": runs})


async def _api_drl_compare(request: Request):
    """GET /api/drl/compare?a=ID&b=ID — compare two DRL runs."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    run_a_id = request.query_params.get("a")
    run_b_id = request.query_params.get("b")
    if not run_a_id or not run_b_id:
        return JSONResponse({"error": "Both a and b run IDs required"}, status_code=400)

    from data_agent.drl_engine import list_run_history, compare_runs
    runs = list_run_history(username, limit=100)
    run_a = next((r for r in runs if str(r["id"]) == str(run_a_id)), None)
    run_b = next((r for r in runs if str(r["id"]) == str(run_b_id)), None)
    if not run_a or not run_b:
        return JSONResponse({"error": "Run not found"}, status_code=404)

    result = compare_runs(run_a, run_b)
    return JSONResponse(result)


async def _api_memory_search(request: Request):
    """GET /api/memory/search?q=keyword&type=region — search user spatial memories."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    query = request.query_params.get("q", "")
    mem_type = request.query_params.get("type", "")
    from .memory import recall_memories
    result = recall_memories(memory_type=mem_type, keyword=query)
    return JSONResponse(result)


async def _api_memory_batch_save(request: Request):
    """POST /api/memory/batch-save — save multiple facts as memories."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        body = await request.json()
        facts = body.get("facts", [])
        from .memory import save_auto_extract_memories
        result = save_auto_extract_memories(facts)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


async def _api_chains_list(request: Request):
    """GET /api/chains — list analysis chains for current user."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    from .analysis_chains import list_chains
    return JSONResponse({"chains": list_chains(username)})


async def _api_chains_create(request: Request):
    """POST /api/chains — create an analysis chain."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    if not body.get("chain_name") or not body.get("trigger_condition") or not body.get("follow_up_prompt"):
        return JSONResponse({"error": "chain_name, trigger_condition, follow_up_prompt required"}, status_code=400)
    from .analysis_chains import create_chain
    result = create_chain(
        chain_name=body["chain_name"],
        trigger_condition=body["trigger_condition"],
        follow_up_prompt=body["follow_up_prompt"],
        follow_up_pipeline=body.get("follow_up_pipeline", "general"),
        description=body.get("description", ""),
    )
    if result["status"] == "error":
        return JSONResponse({"error": result["message"]}, status_code=400)
    return JSONResponse(result, status_code=201)


async def _api_chains_delete(request: Request):
    """DELETE /api/chains/{id} — delete an analysis chain."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    chain_id = int(request.path_params.get("id", 0))
    from .analysis_chains import delete_chain
    if delete_chain(chain_id):
        return JSONResponse({"ok": True})
    return JSONResponse({"error": "Chain not found"}, status_code=404)


async def _api_annotations_export(request: Request):
    """GET /api/annotations/export?format=geojson — export annotations as GeoJSON or CSV."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    fmt = request.query_params.get("format", "geojson")

    from .db_engine import get_engine
    engine = get_engine()
    if not engine:
        return JSONResponse({"error": "Database not available"}, status_code=500)

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, lng, lat, title, comment, color, is_resolved, created_at "
                "FROM agent_map_annotations WHERE user_id = :u ORDER BY created_at"
            ), {"u": username}).fetchall()

        if fmt == "geojson":
            features = []
            for r in rows:
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [float(r[1]), float(r[2])]},
                    "properties": {
                        "id": r[0], "title": r[3], "comment": r[4],
                        "color": r[5], "resolved": bool(r[6]),
                        "created_at": str(r[7]),
                    },
                })
            return JSONResponse({
                "type": "FeatureCollection",
                "features": features,
            })
        else:  # csv
            import csv
            import io
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["id", "lng", "lat", "title", "comment", "color", "resolved", "created_at"])
            for r in rows:
                writer.writerow([r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]])
            from starlette.responses import Response
            return Response(
                content=output.getvalue(),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=annotations.csv"},
            )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def _api_plugins_list(request: Request):
    """GET /api/plugins — list installed plugins."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    from .plugin_registry import list_plugins
    return JSONResponse({"plugins": list_plugins()})


async def _api_plugins_install(request: Request):
    """POST /api/plugins — install a plugin."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    from .plugin_registry import register_plugin
    result = register_plugin(
        plugin_id=body.get("plugin_id", ""),
        plugin_name=body.get("plugin_name", ""),
        tab_label=body.get("tab_label", ""),
        description=body.get("description", ""),
        entry_url=body.get("entry_url", ""),
        owner_username=username,
    )
    if result["status"] == "error":
        return JSONResponse({"error": result["message"]}, status_code=400)
    return JSONResponse(result, status_code=201)


async def _api_a2a_task_create(request: Request):
    """POST /api/a2a/tasks — create a new A2A task (v14.3 lifecycle)."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    from .a2a_server import create_task
    result = create_task(body.get("message", ""), body.get("caller_id", "api"))
    return JSONResponse(result, status_code=201)


async def _api_a2a_task_execute(request: Request):
    """POST /api/a2a/tasks/{task_id}/execute — execute a submitted task."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    task_id = request.path_params.get("task_id", "")
    from .a2a_server import execute_task
    result = await execute_task(task_id)
    return JSONResponse(result)


async def _api_a2a_task_status(request: Request):
    """GET /api/a2a/tasks/{task_id} — get task status."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    task_id = request.path_params.get("task_id", "")
    from .a2a_server import get_task_status
    status = get_task_status(task_id)
    if not status:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    return JSONResponse(status)


async def _api_a2a_federation(request: Request):
    """GET /api/a2a/federation — get federation config and peer agents."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    from .a2a_server import get_federation_config
    return JSONResponse(get_federation_config())


# ---------------------------------------------------------------------------
# HITL Dashboard API
# ---------------------------------------------------------------------------

async def _api_hitl_stats(request: Request):
    """GET /api/hitl/stats — HITL decision statistics."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    days = int(request.query_params.get("days", "30"))
    from .hitl_approval import get_hitl_stats
    return JSONResponse(get_hitl_stats(days))


async def _api_hitl_risk_registry(request: Request):
    """GET /api/hitl/risk-registry — current risk registry."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    from .hitl_approval import get_risk_registry
    return JSONResponse({"tools": get_risk_registry()})


async def _api_cost_estimate(request: Request):
    """GET /api/cost/estimate?pipeline=general — pre-execution cost estimate."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    pipeline = request.query_params.get("pipeline", "general")
    model = request.query_params.get("model", "gemini-2.5-flash")
    from .token_tracker import estimate_pipeline_cost
    return JSONResponse(estimate_pipeline_cost(pipeline, model))


# ---------------------------------------------------------------------------
# BCG Platform Enhancement APIs (v15.8)
# ---------------------------------------------------------------------------

async def _api_prompts_versions(request: Request):
    """GET /api/prompts/versions?domain=general&env=prod — list prompt versions."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    domain = request.query_params.get("domain", "general")
    env = request.query_params.get("env", "prod")
    engine = get_engine()
    if not engine:
        return JSONResponse({"versions": []})
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, prompt_key, version, is_active, deployed_at, created_at
            FROM agent_prompt_versions
            WHERE domain = :domain AND environment = :env
            ORDER BY prompt_key, version DESC
        """), {"domain": domain, "env": env})
        versions = [{"id": r[0], "prompt_key": r[1], "version": r[2], "is_active": r[3],
                     "deployed_at": r[4].isoformat() if r[4] else None,
                     "created_at": r[5].isoformat() if r[5] else None} for r in result]
    return JSONResponse({"versions": versions})


async def _api_prompts_deploy(request: Request):
    """POST /api/prompts/deploy — deploy prompt version to target env."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    body = await request.json()
    version_id = body.get("version_id")
    target_env = body.get("target_env", "prod")
    if not version_id:
        return JSONResponse({"error": "version_id required"}, status_code=400)
    from .prompt_registry import PromptRegistry
    registry = PromptRegistry()
    try:
        result = registry.deploy(version_id, target_env)
        return JSONResponse({"status": "success", "result": result})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Prompt Auto-Optimizer Endpoints (v17.2)
# ---------------------------------------------------------------------------

async def _api_prompts_collect_bad_cases(request: Request):
    """POST /api/prompts/collect-bad-cases — collect bad cases from all sources."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    body = await request.json()
    min_score = float(body.get("min_score", 0.5))
    days = int(body.get("days", 7))
    min_rating = int(body.get("min_rating", 2))
    limit = min(int(body.get("limit", 50)), 200)
    from .prompt_optimizer import BadCaseCollector
    collector = BadCaseCollector()
    cases = await collector.collect_all(
        min_score=min_score, days=days, min_rating=min_rating, limit=limit,
    )
    return JSONResponse({"bad_cases": cases, "count": len(cases)})


async def _api_prompts_analyze_failures(request: Request):
    """POST /api/prompts/analyze-failures — analyze failure patterns from bad cases."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    body = await request.json()
    bad_cases = body.get("bad_cases", [])
    if not bad_cases:
        return JSONResponse({"error": "bad_cases required"}, status_code=400)
    from .prompt_optimizer import FailureAnalyzer
    analyzer = FailureAnalyzer()
    try:
        analysis = await analyzer.analyze(bad_cases)
        return JSONResponse({"analysis": analysis})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def _api_prompts_optimize(request: Request):
    """POST /api/prompts/optimize — generate improvement suggestion for a prompt."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    body = await request.json()
    domain = body.get("domain")
    prompt_key = body.get("prompt_key")
    failure_analysis = body.get("failure_analysis", {})
    if not domain or not prompt_key:
        return JSONResponse({"error": "domain and prompt_key required"}, status_code=400)
    from .prompt_optimizer import PromptOptimizer
    optimizer = PromptOptimizer()
    try:
        suggestion = await optimizer.suggest_improvements(domain, prompt_key, failure_analysis)
        return JSONResponse({"suggestion": suggestion})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def _api_prompts_apply_suggestion(request: Request):
    """POST /api/prompts/apply-suggestion — apply suggestion as new prompt version."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    body = await request.json()
    domain = body.get("domain")
    prompt_key = body.get("prompt_key")
    suggested_prompt = body.get("suggested_prompt")
    environment = body.get("environment", "dev")
    if not domain or not prompt_key or not suggested_prompt:
        return JSONResponse(
            {"error": "domain, prompt_key, and suggested_prompt required"},
            status_code=400,
        )
    from .prompt_optimizer import PromptOptimizer
    optimizer = PromptOptimizer()
    try:
        result = await optimizer.apply_suggestion(domain, prompt_key, suggested_prompt, environment)
        return JSONResponse({"result": result})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def _api_gateway_models(request: Request):
    """GET /api/gateway/models — list available models with capabilities.

    Query params:
    - online_only: filter to online models
    - offline_only: filter to offline/local models
    """
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    from .model_gateway import ModelRegistry
    online_only = request.query_params.get("online_only") == "true"
    offline_only = request.query_params.get("offline_only") == "true"
    models = ModelRegistry.list_models(online_only=online_only, offline_only=offline_only)
    return JSONResponse({"models": models})


async def _api_gateway_cost_summary(request: Request):
    """GET /api/gateway/cost-summary?days=30 — cost breakdown by scenario/project."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    days = int(request.query_params.get("days", "30"))
    engine = get_engine()
    if not engine:
        return JSONResponse({"summary": []})
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT scenario, project_id, SUM(cost_usd) as total_cost, COUNT(*) as call_count
            FROM agent_token_usage
            WHERE timestamp > NOW() - INTERVAL :days DAY
            GROUP BY scenario, project_id
            ORDER BY total_cost DESC
        """), {"days": days})
        summary = [{"scenario": r[0], "project_id": r[1], "total_cost": float(r[2] or 0),
                    "call_count": r[3]} for r in result]
    return JSONResponse({"summary": summary})


async def _api_eval_history(request: Request):
    """GET /api/eval/history?pipeline=general&limit=50 — evaluation history."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    pipeline = request.query_params.get("pipeline", "")
    limit = int(request.query_params.get("limit", "50"))
    from .eval_history import get_eval_history
    return JSONResponse({"history": get_eval_history(pipeline or None, limit)})


async def _api_eval_trend(request: Request):
    """GET /api/eval/trend?pipeline=general&days=90 — score trend over time."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    pipeline = request.query_params.get("pipeline", "general")
    days = int(request.query_params.get("days", "90"))
    from .eval_history import get_eval_trend
    return JSONResponse({"trend": get_eval_trend(pipeline, days)})


async def _api_context_preview(request: Request):
    """GET /api/context/preview?task_type=qc&step=detection — preview context blocks."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    task_type = request.query_params.get("task_type", "general")
    step = request.query_params.get("step", "")
    from .context_manager import ContextManager
    manager = ContextManager()
    blocks = manager.prepare(task_type, step, {"user_id": user})
    return JSONResponse({"blocks": [{"source": b.source, "content": b.content[:200],
                                     "relevance": b.relevance, "tokens": b.tokens} for b in blocks]})


async def _api_eval_datasets_create(request: Request):
    """POST /api/eval/datasets — create evaluation dataset."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    body = await request.json()
    scenario = body.get("scenario", "")
    name = body.get("name", "")
    test_cases = body.get("test_cases", [])
    if not scenario or not name or not test_cases:
        return JSONResponse({"error": "scenario, name, test_cases required"}, status_code=400)
    from .eval_scenario import EvalDatasetManager
    manager = EvalDatasetManager()
    try:
        dataset_id = manager.create_dataset(scenario, name, test_cases,
                                           version=body.get("version", "1.0"),
                                           description=body.get("description", ""),
                                           created_by=user)
        return JSONResponse({"status": "success", "dataset_id": dataset_id})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def _api_eval_run(request: Request):
    """POST /api/eval/run — run evaluation against dataset."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    body = await request.json()
    dataset_id = body.get("dataset_id")
    scenario = body.get("scenario", "surveying_qc")
    if not dataset_id:
        return JSONResponse({"error": "dataset_id required"}, status_code=400)
    from .eval_scenario import EvalDatasetManager, SurveyingQCScenario
    manager = EvalDatasetManager()
    try:
        dataset = manager.get_dataset(dataset_id)
        evaluator = SurveyingQCScenario()
        results = []
        for case in dataset["test_cases"]:
            metrics = evaluator.evaluate(case.get("actual", ), case.get("expected", {}))
            results.append({"case_id": case.get("id"), "metrics": metrics})
        return JSONResponse({"status": "success", "results": results})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def _api_eval_scenarios(request: Request):
    """GET /api/eval/scenarios — list available evaluation scenarios."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    scenarios = [{"name": "surveying_qc", "description": "测绘质检评估场景",
                  "metrics": ["defect_precision", "defect_recall", "defect_f1", "fix_success_rate"]}]
    return JSONResponse({"scenarios": scenarios})


# ---------------------------------------------------------------------------
# Evaluator Registry API
# ---------------------------------------------------------------------------

async def _api_eval_evaluators(request: Request):
    """GET /api/eval/evaluators?category=quality — list available evaluators."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    category = request.query_params.get("category")
    from .evaluator_registry import EvaluatorRegistry
    evaluators = EvaluatorRegistry.list_evaluators(category=category or None)
    return JSONResponse({"evaluators": evaluators})


async def _api_eval_evaluate(request: Request):
    """POST /api/eval/evaluate — run evaluators on test cases."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    body = await request.json()
    evaluator_names = body.get("evaluators", [])
    test_cases = body.get("test_cases", [])
    if not evaluator_names or not test_cases:
        return JSONResponse({"error": "evaluators and test_cases required"}, status_code=400)
    from .evaluator_registry import EvaluatorRegistry
    try:
        results = EvaluatorRegistry.run_evaluation(evaluator_names, test_cases)
        return JSONResponse({"status": "success", **results})
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Feature Flags API (admin only)
# ---------------------------------------------------------------------------

async def _api_flags_list(request: Request):
    """GET /api/admin/flags — list all feature flags."""
    user, username, role, err = _require_admin(request)
    if err:
        return err
    from .feature_flags import get_all_flags
    return JSONResponse({"flags": get_all_flags()})


async def _api_flags_set(request: Request):
    """PUT /api/admin/flags — set a feature flag."""
    user, username, role, err = _require_admin(request)
    if err:
        return err
    body = await request.json()
    flag_name = body.get("name", "")
    enabled = body.get("enabled", False)
    if not flag_name:
        return JSONResponse({"error": "name required"}, status_code=400)
    from .feature_flags import set_flag
    set_flag(flag_name, bool(enabled))
    return JSONResponse({"status": "success", "flag": flag_name, "enabled": bool(enabled)})


async def _api_flags_delete(request: Request):
    """DELETE /api/admin/flags/{name} — delete a feature flag."""
    user, username, role, err = _require_admin(request)
    if err:
        return err
    name = request.path_params.get("name", "")
    from .feature_flags import delete_flag
    deleted = delete_flag(name)
    if deleted:
        return JSONResponse({"status": "success", "deleted": name})
    return JSONResponse({"error": "Flag not found"}, status_code=404)


# ---------------------------------------------------------------------------
# Route Mounting
# ---------------------------------------------------------------------------

def get_frontend_api_routes():
    """Return list of Starlette routes for the frontend API."""
    from .api.mcp_routes import get_mcp_routes
    from .api.workflow_routes import get_workflow_routes
    from .api.skills_routes import get_skills_routes
    from .api.virtual_routes import get_virtual_source_routes
    from .api.world_model_routes import get_world_model_routes
    from .api.causal_routes import get_causal_routes
    from .api.causal_world_model_routes import get_causal_world_model_routes
    from .api.quality_routes import get_quality_routes
    from .api.distribution_routes import get_distribution_routes
    from .api.file_routes import get_file_routes
    from .api.topology_routes import get_topology_routes
    from .api.metadata_routes import get_metadata_routes
    from .api.fusion_v2_routes import get_fusion_v2_routes
    from .api.tile_routes import get_tile_routes
    from .api.context_routes import get_context_routes
    from .api.feedback_routes import get_feedback_routes
    from .api.reference_query_routes import get_reference_query_routes
    from .api.semantic_model_routes import get_semantic_model_routes

    return [
        Route("/api/catalog", endpoint=_api_catalog_list, methods=["GET"]),
        Route("/api/catalog/search", endpoint=_api_catalog_search, methods=["GET"]),
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
        Route("/api/user/password", endpoint=_api_user_change_password, methods=["PUT"]),
        Route("/api/user/analysis-perspective", endpoint=_api_user_perspective_get, methods=["GET"]),
        Route("/api/user/analysis-perspective", endpoint=_api_user_perspective_put, methods=["PUT"]),
        Route("/api/user/memories", endpoint=_api_user_memories_list, methods=["GET"]),
        Route("/api/user/memories/{id:int}", endpoint=_api_user_memories_delete, methods=["DELETE"]),
        Route("/api/memory/search", endpoint=_api_memory_search, methods=["GET"]),
        Route("/api/user/drawn-features", endpoint=_api_user_drawn_features, methods=["POST"]),
        Route("/api/sessions", endpoint=_api_sessions_list, methods=["GET"]),
        Route("/api/sessions/{session_id}", endpoint=_api_session_delete, methods=["DELETE"]),
        # MCP Hub (S-4: delegated to api/mcp_routes.py)
        *get_mcp_routes(),
        # Workflows (v5.4)
        # Workflows (S-4: delegated to api/workflow_routes.py)
        *get_workflow_routes(),
        # Map/Data pending updates (v7.0 — bypass Chainlit metadata limitation)
        Route("/api/map/pending", endpoint=_api_map_pending, methods=["GET"]),
        Route("/api/chart/pending", endpoint=_api_chart_pending, methods=["GET"]),
        # Capabilities (aggregated skills + toolsets)
        Route("/api/capabilities", endpoint=_api_capabilities, methods=["GET"]),
        # Marketplace (v14.0)
        Route("/api/marketplace", endpoint=_api_marketplace, methods=["GET"]),
        # DRL Scenarios (v14.0) + Custom Weights (v15.3)
        Route("/api/drl/scenarios", endpoint=_api_drl_scenarios, methods=["GET"]),
        Route("/api/drl/run-custom", endpoint=_api_drl_run_custom, methods=["POST"]),
        Route("/api/drl/explain", endpoint=_api_drl_explain, methods=["POST"]),
        Route("/api/drl/history", endpoint=_api_drl_history, methods=["GET"]),
        Route("/api/drl/compare", endpoint=_api_drl_compare, methods=["GET"]),
        # Memory Search (v14.0)
        Route("/api/memory/search", endpoint=_api_memory_search, methods=["GET"]),
        Route("/api/memory/batch-save", endpoint=_api_memory_batch_save, methods=["POST"]),
        # Analysis Chains (v14.2)
        Route("/api/chains", endpoint=_api_chains_list, methods=["GET"]),
        Route("/api/chains", endpoint=_api_chains_create, methods=["POST"]),
        Route("/api/chains/{id:int}", endpoint=_api_chains_delete, methods=["DELETE"]),
        # Annotation Export (v14.2)
        Route("/api/annotations/export", endpoint=_api_annotations_export, methods=["GET"]),
        # Plugins (v14.3)
        Route("/api/plugins", endpoint=_api_plugins_list, methods=["GET"]),
        Route("/api/plugins", endpoint=_api_plugins_install, methods=["POST"]),
        # A2A Task Lifecycle (v14.3)
        Route("/api/a2a/tasks", endpoint=_api_a2a_task_create, methods=["POST"]),
        Route("/api/a2a/tasks/{task_id}", endpoint=_api_a2a_task_status, methods=["GET"]),
        Route("/api/a2a/tasks/{task_id}/execute", endpoint=_api_a2a_task_execute, methods=["POST"]),
        Route("/api/a2a/federation", endpoint=_api_a2a_federation, methods=["GET"]),
        # HITL Dashboard
        Route("/api/hitl/stats", endpoint=_api_hitl_stats, methods=["GET"]),
        Route("/api/hitl/risk-registry", endpoint=_api_hitl_risk_registry, methods=["GET"]),
        # Cost Management
        Route("/api/cost/estimate", endpoint=_api_cost_estimate, methods=["GET"]),
        # BCG Platform Enhancement APIs (v15.8)
        Route("/api/prompts/versions", endpoint=_api_prompts_versions, methods=["GET"]),
        Route("/api/prompts/deploy", endpoint=_api_prompts_deploy, methods=["POST"]),
        # Prompt Auto-Optimizer (v17.2)
        Route("/api/prompts/collect-bad-cases", endpoint=_api_prompts_collect_bad_cases, methods=["POST"]),
        Route("/api/prompts/analyze-failures", endpoint=_api_prompts_analyze_failures, methods=["POST"]),
        Route("/api/prompts/optimize", endpoint=_api_prompts_optimize, methods=["POST"]),
        Route("/api/prompts/apply-suggestion", endpoint=_api_prompts_apply_suggestion, methods=["POST"]),
        Route("/api/gateway/models", endpoint=_api_gateway_models, methods=["GET"]),
        Route("/api/gateway/cost-summary", endpoint=_api_gateway_cost_summary, methods=["GET"]),
        Route("/api/context/preview", endpoint=_api_context_preview, methods=["GET"]),
        Route("/api/eval/datasets", endpoint=_api_eval_datasets_create, methods=["POST"]),
        Route("/api/eval/run", endpoint=_api_eval_run, methods=["POST"]),
        Route("/api/eval/scenarios", endpoint=_api_eval_scenarios, methods=["GET"]),
        # Evaluator Registry
        Route("/api/eval/evaluators", endpoint=_api_eval_evaluators, methods=["GET"]),
        Route("/api/eval/evaluate", endpoint=_api_eval_evaluate, methods=["POST"]),
        # Eval History
        Route("/api/eval/history", endpoint=_api_eval_history, methods=["GET"]),
        Route("/api/eval/trend", endpoint=_api_eval_trend, methods=["GET"]),
        # Feature Flags (admin)
        Route("/api/admin/flags", endpoint=_api_flags_list, methods=["GET"]),
        Route("/api/admin/flags", endpoint=_api_flags_set, methods=["PUT"]),
        Route("/api/admin/flags/{name}", endpoint=_api_flags_delete, methods=["DELETE"]),
        # Custom Skills (v8.0.1)
        # Custom Skills (S-4: delegated to api/skills_routes.py)
        *get_skills_routes(),
        # Virtual Data Sources (v13.0)
        *get_virtual_source_routes(),
        # World Model (Tech Preview)
        *get_world_model_routes(),
        # Causal Reasoning (Angle B) + Causal World Model (Angle C)
        *get_causal_routes(),
        *get_causal_world_model_routes(),
        *get_quality_routes(),
        *get_distribution_routes(),
        # File Management (upload, browse, delete, local-data)
        *get_file_routes(),
        # Knowledge Base (v8.0.2)
        # Bundles (v10.0.2)
        Route("/api/bundles", endpoint=_api_bundles_list, methods=["GET"]),
        Route("/api/bundles", endpoint=_api_bundles_create, methods=["POST"]),
        Route("/api/bundles/available-tools", endpoint=_api_bundles_available_tools, methods=["GET"]),
        Route("/api/bundles/{id:int}", endpoint=_api_bundles_detail, methods=["GET"]),
        Route("/api/bundles/{id:int}", endpoint=_api_bundles_update, methods=["PUT"]),
        Route("/api/bundles/{id:int}", endpoint=_api_bundles_delete, methods=["DELETE"]),

        # Knowledge Base (v8.0.2)
        # Templates (v10.0.4)
        Route("/api/templates", endpoint=_api_templates_list, methods=["GET"]),
        Route("/api/templates", endpoint=_api_templates_create, methods=["POST"]),
        Route("/api/templates/{id:int}/clone", endpoint=_api_templates_clone, methods=["POST"]),
        Route("/api/templates/{id:int}", endpoint=_api_templates_detail, methods=["GET"]),
        Route("/api/templates/{id:int}", endpoint=_api_templates_update, methods=["PUT"]),
        Route("/api/templates/{id:int}", endpoint=_api_templates_delete, methods=["DELETE"]),

        # Knowledge Base (v8.0.2)
        Route("/api/kb", endpoint=_api_kb_list, methods=["GET"]),
        Route("/api/kb", endpoint=_api_kb_create, methods=["POST"]),
        Route("/api/kb/search", endpoint=_api_kb_search, methods=["POST"]),
        Route("/api/kb/{id:int}", endpoint=_api_kb_detail, methods=["GET"]),
        Route("/api/kb/{id:int}", endpoint=_api_kb_delete, methods=["DELETE"]),
        Route("/api/kb/{id:int}/documents", endpoint=_api_kb_doc_upload, methods=["POST"]),
        Route("/api/kb/{id:int}/documents/{doc_id:int}", endpoint=_api_kb_doc_delete, methods=["DELETE"]),
        # GraphRAG (v10.0.5)
        Route("/api/kb/{id:int}/build-graph", endpoint=_api_kb_build_graph, methods=["POST"]),
        Route("/api/kb/{id:int}/graph", endpoint=_api_kb_graph, methods=["GET"]),
        Route("/api/kb/{id:int}/graph-search", endpoint=_api_kb_graph_search, methods=["POST"]),
        Route("/api/kb/{id:int}/entities", endpoint=_api_kb_entities, methods=["GET"]),
        # Pipeline Analytics (v9.0.5)
        Route("/api/analytics/latency", endpoint=_api_analytics_latency, methods=["GET"]),
        Route("/api/analytics/tool-success", endpoint=_api_analytics_tool_success, methods=["GET"]),
        Route("/api/analytics/token-efficiency", endpoint=_api_analytics_token_efficiency, methods=["GET"]),
        Route("/api/analytics/throughput", endpoint=_api_analytics_throughput, methods=["GET"]),
        Route("/api/analytics/agent-breakdown", endpoint=_api_analytics_agent_breakdown, methods=["GET"]),
        # Pipeline SSE Streaming (v9.5.4)
        Route("/api/pipeline/stream", endpoint=_api_pipeline_stream, methods=["GET"]),
        Route("/api/pipeline/trace/{trace_id}", endpoint=_api_pipeline_trace, methods=["GET"]),
        # Task Queue (v11.0.1)
        Route("/api/tasks/submit", endpoint=_api_tasks_submit, methods=["POST"]),
        Route("/api/tasks", endpoint=_api_tasks_list, methods=["GET"]),
        Route("/api/tasks/{job_id}", endpoint=_api_tasks_detail, methods=["GET"]),
        Route("/api/tasks/{job_id}", endpoint=_api_tasks_cancel, methods=["DELETE"]),
        # Proactive Suggestions (v11.0.3)
        Route("/api/suggestions", endpoint=_api_suggestions_list, methods=["GET"]),
        Route("/api/suggestions/{id}/execute", endpoint=_api_suggestions_execute, methods=["POST"]),
        Route("/api/suggestions/{id}/dismiss", endpoint=_api_suggestions_dismiss, methods=["POST"]),
        # A2A Server (v11.0.4)
        Route("/api/a2a/card", endpoint=_api_a2a_card, methods=["GET"]),
        Route("/api/a2a/status", endpoint=_api_a2a_status, methods=["GET"]),
        # System Status (v12.0)
        Route("/api/system/status", endpoint=_api_system_status, methods=["GET"]),
        Route("/api/bots/status", endpoint=_api_bots_status, methods=["GET"]),
        Route("/api/config/models", endpoint=_api_config_models, methods=["GET"]),
        # User-Defined Tools (v12.0)
        Route("/api/user-tools", endpoint=_api_user_tools_list, methods=["GET"]),
        Route("/api/user-tools", endpoint=_api_user_tools_create, methods=["POST"]),
        Route("/api/user-tools/{id:int}/test", endpoint=_api_user_tools_test, methods=["POST"]),
        Route("/api/user-tools/{id:int}/rate", endpoint=_api_user_tools_rate, methods=["POST"]),
        Route("/api/user-tools/{id:int}/clone", endpoint=_api_user_tools_clone, methods=["POST"]),
        Route("/api/user-tools/{id:int}", endpoint=_api_user_tools_detail, methods=["GET"]),
        Route("/api/user-tools/{id:int}", endpoint=_api_user_tools_update, methods=["PUT"]),
        Route("/api/user-tools/{id:int}", endpoint=_api_user_tools_delete, methods=["DELETE"]),
        # Agent Topology (v15.8)
        *get_topology_routes(),
        # Metadata Management (v15.8)
        *get_metadata_routes(),
        # Fusion v2.0 (v17.0)
        *get_fusion_v2_routes(),
        # Vector Tile Serving (v17.1)
        *get_tile_routes(),
        # Message Bus Monitoring (v15.9)
        Route("/api/messaging/stats", endpoint=_api_messaging_stats, methods=["GET"]),
        Route("/api/messaging/messages", endpoint=_api_messaging_list, methods=["GET"]),
        Route("/api/messaging/{id:int}/replay", endpoint=_api_messaging_replay, methods=["POST"]),
        Route("/api/messaging/cleanup", endpoint=_api_messaging_cleanup, methods=["DELETE"]),
        # Context Engine v2 (v19.0)
        *get_context_routes(),
        # Feedback Loop (v19.0)
        *get_feedback_routes(),
        # Reference Query Library (v19.0)
        *get_reference_query_routes(),
        # Semantic Models (v19.0)
        *get_semantic_model_routes(),
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
