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
    """Delegate to api.mcp_routes (S-4 refactoring)."""
    from .api.mcp_routes import mcp_servers
    return await mcp_servers(request)


async def _api_mcp_tools(request: Request):
    """Delegate to api.mcp_routes (S-4 refactoring)."""
    from .api.mcp_routes import mcp_tools
    return await mcp_tools(request)


async def _api_mcp_toggle(request: Request):
    """Delegate to api.mcp_routes (S-4 refactoring)."""
    from .api.mcp_routes import mcp_toggle
    return await mcp_toggle(request)


async def _api_mcp_reconnect(request: Request):
    """Delegate to api.mcp_routes (S-4 refactoring)."""
    from .api.mcp_routes import mcp_reconnect
    return await mcp_reconnect(request)


async def _api_mcp_test_connection(request: Request):
    """Delegate to api.mcp_routes (S-4 refactoring)."""
    from .api.mcp_routes import mcp_test_connection
    return await mcp_test_connection(request)


async def _api_mcp_server_create(request: Request):
    """Delegate to api.mcp_routes (S-4 refactoring)."""
    from .api.mcp_routes import mcp_server_create
    return await mcp_server_create(request)


async def _api_mcp_server_update(request: Request):
    """Delegate to api.mcp_routes (S-4 refactoring)."""
    from .api.mcp_routes import mcp_server_update
    return await mcp_server_update(request)


async def _api_mcp_server_delete(request: Request):
    """Delegate to api.mcp_routes (S-4 refactoring)."""
    from .api.mcp_routes import mcp_server_delete
    return await mcp_server_delete(request)


async def _api_mcp_servers_mine(request: Request):
    """Delegate to api.mcp_routes (S-4 refactoring)."""
    from .api.mcp_routes import mcp_servers_mine
    return await mcp_servers_mine(request)


async def _api_mcp_server_share(request: Request):
    """Delegate to api.mcp_routes (S-4 refactoring)."""
    from .api.mcp_routes import mcp_server_share
    return await mcp_server_share(request)
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
        Route("/api/mcp/servers/mine", endpoint=_api_mcp_servers_mine, methods=["GET"]),
        Route("/api/mcp/servers/test", endpoint=_api_mcp_test_connection, methods=["POST"]),
        Route("/api/mcp/servers/{name}/toggle", endpoint=_api_mcp_toggle, methods=["POST"]),
        Route("/api/mcp/servers/{name}/reconnect", endpoint=_api_mcp_reconnect, methods=["POST"]),
        Route("/api/mcp/servers/{name}/share", endpoint=_api_mcp_server_share, methods=["POST"]),
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
        Route("/api/workflows/{id:int}/runs/{run_id:int}/status", endpoint=_api_workflow_run_status, methods=["GET"]),
        # Map/Data pending updates (v7.0 — bypass Chainlit metadata limitation)
        Route("/api/map/pending", endpoint=_api_map_pending, methods=["GET"]),
        # Capabilities (aggregated skills + toolsets)
        Route("/api/capabilities", endpoint=_api_capabilities, methods=["GET"]),
        # Custom Skills (v8.0.1)
        Route("/api/skills", endpoint=_api_skills_list, methods=["GET"]),
        Route("/api/skills", endpoint=_api_skills_create, methods=["POST"]),
        Route("/api/skills/{id:int}", endpoint=_api_skills_detail, methods=["GET"]),
        Route("/api/skills/{id:int}", endpoint=_api_skills_update, methods=["PUT"]),
        Route("/api/skills/{id:int}", endpoint=_api_skills_delete, methods=["DELETE"]),
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
        Route("/api/user-tools/{id:int}", endpoint=_api_user_tools_detail, methods=["GET"]),
        Route("/api/user-tools/{id:int}", endpoint=_api_user_tools_update, methods=["PUT"]),
        Route("/api/user-tools/{id:int}", endpoint=_api_user_tools_delete, methods=["DELETE"]),
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
