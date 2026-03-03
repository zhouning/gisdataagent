"""
Frontend Integration API — REST endpoints for the React three-panel frontend.

Provides:
- /api/catalog — data asset browsing and lineage
- /api/semantic — semantic hierarchy browsing
- /api/pipeline — user pipeline run history
- /api/user/token-usage — per-user token consumption
- /api/admin/users — user management (admin only)
- /api/admin/metrics/summary — aggregated dashboard metrics

All user-facing endpoints use JWT cookie auth.
Admin endpoints require JWT + admin role.

Routes are mounted before the Chainlit catch-all via mount_frontend_api().
"""
import json
from typing import Optional

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from sqlalchemy import text

from .observability import get_logger
from .user_context import current_user_id, current_user_role
from .db_engine import get_engine

logger = get_logger("frontend_api")


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
        Route("/api/sessions", endpoint=_api_sessions_list, methods=["GET"]),
        Route("/api/sessions/{session_id}", endpoint=_api_session_delete, methods=["DELETE"]),
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
