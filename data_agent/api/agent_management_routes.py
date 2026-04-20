"""
Agent Management API — alias/display_name/pin/hide for @mention targets.
"""
from typing import Optional
from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..db_engine import get_engine
from ..observability import get_logger
from .helpers import _get_user_from_request, _set_user_context

logger = get_logger("agent_management")


def list_aliases_for_user(user_id: str) -> list[dict]:
    """Return all alias records for a user."""
    engine = get_engine()
    if engine is None:
        return []
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT handle, aliases, display_name, pinned, hidden
                FROM agent_aliases
                WHERE user_id = :user_id
            """), {"user_id": user_id})
            rows = result.mappings().all()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("list_aliases_for_user failed: %s", e)
        return []


def upsert_alias(
    user_id: str,
    handle: str,
    aliases: Optional[list[str]] = None,
    display_name: Optional[str] = None,
) -> None:
    """Insert or update alias/display_name for (user_id, handle)."""
    engine = get_engine()
    if engine is None:
        return
    aliases = aliases or []
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO agent_aliases (user_id, handle, aliases, display_name, updated_at)
                VALUES (:user_id, :handle, :aliases, :display_name, CURRENT_TIMESTAMP)
                ON CONFLICT (handle, user_id) DO UPDATE SET
                    aliases = EXCLUDED.aliases,
                    display_name = EXCLUDED.display_name,
                    updated_at = CURRENT_TIMESTAMP
            """), {
                "user_id": user_id,
                "handle": handle,
                "aliases": aliases,
                "display_name": display_name,
            })
    except Exception as e:
        logger.error("upsert_alias failed: %s", e)
        raise


def set_flag(user_id: str, handle: str, flag: str, value: bool) -> None:
    """Set pinned or hidden flag for a handle. flag must be 'pinned' or 'hidden'."""
    if flag not in ("pinned", "hidden"):
        raise ValueError(f"Invalid flag: {flag}")
    engine = get_engine()
    if engine is None:
        return
    try:
        with engine.begin() as conn:
            conn.execute(text(f"""
                INSERT INTO agent_aliases (user_id, handle, {flag}, updated_at)
                VALUES (:user_id, :handle, :value, CURRENT_TIMESTAMP)
                ON CONFLICT (handle, user_id) DO UPDATE SET
                    {flag} = EXCLUDED.{flag},
                    updated_at = CURRENT_TIMESTAMP
            """), {
                "user_id": user_id,
                "handle": handle,
                "value": value,
            })
    except Exception as e:
        logger.error("set_flag failed: %s", e)
        raise


from ..mention_registry import build_registry


async def _api_mention_targets(request: Request):
    """GET /api/agents/mention-targets — RBAC-filtered mention targets with alias/pinned/hidden."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    include_hidden = request.query_params.get("include_hidden") in ("1", "true")

    registry = build_registry(user_id=username, role=role)
    out = []
    for t in registry:
        if t.get("hidden") and not include_hidden:
            continue
        out.append({
            "handle": t["handle"],
            "label": t.get("label", t["handle"]),
            "display_name": t.get("display_name", ""),
            "aliases": t.get("aliases", []),
            "pinned": bool(t.get("pinned", False)),
            "hidden": bool(t.get("hidden", False)),
            "type": t["type"],
            "description": t.get("description", ""),
            "allowed": role in t.get("allowed_roles", []),
            "allowed_roles": t.get("allowed_roles", []),
            "required_state_keys": t.get("required_state_keys", []),
            "pipeline": t.get("pipeline"),
        })
    type_order = {"pipeline": 0, "sub_agent": 1, "adk_skill": 2, "custom_skill": 3}
    out.sort(key=lambda t: (
        0 if t["pinned"] else 1,
        type_order.get(t["type"], 99),
        t["handle"].lower(),
    ))
    return JSONResponse({"targets": out})


async def _api_set_alias(request: Request):
    """PUT /api/agents/{handle}/alias — set aliases + display_name."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    handle = request.path_params["handle"]
    try:
        body = await request.json()
    except Exception:
        body = {}
    aliases = body.get("aliases") or []
    if not isinstance(aliases, list) or any(not isinstance(a, str) for a in aliases):
        return JSONResponse({"error": "aliases must be a list of strings"}, status_code=400)
    display_name = body.get("display_name")
    if display_name is not None and not isinstance(display_name, str):
        return JSONResponse({"error": "display_name must be a string"}, status_code=400)
    try:
        upsert_alias(username, handle, aliases=aliases, display_name=display_name)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"ok": True})


async def _api_set_pin(request: Request):
    """PUT /api/agents/{handle}/pin — toggle pinned flag."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    handle = request.path_params["handle"]
    try:
        body = await request.json()
    except Exception:
        body = {}
    pinned = bool(body.get("pinned", False))
    try:
        set_flag(username, handle, "pinned", pinned)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"ok": True, "pinned": pinned})


async def _api_set_hide(request: Request):
    """PUT /api/agents/{handle}/hide — toggle hidden flag."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    handle = request.path_params["handle"]
    try:
        body = await request.json()
    except Exception:
        body = {}
    hidden = bool(body.get("hidden", False))
    try:
        set_flag(username, handle, "hidden", hidden)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"ok": True, "hidden": hidden})


def get_agent_management_routes() -> list:
    """Return Starlette routes for agent management."""
    return [
        Route("/api/agents/mention-targets", endpoint=_api_mention_targets, methods=["GET"]),
        Route("/api/agents/{handle}/alias", endpoint=_api_set_alias, methods=["PUT"]),
        Route("/api/agents/{handle}/pin", endpoint=_api_set_pin, methods=["PUT"]),
        Route("/api/agents/{handle}/hide", endpoint=_api_set_hide, methods=["PUT"]),
    ]
