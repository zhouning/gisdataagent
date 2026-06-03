"""World Model v2.1 REST routes."""

import asyncio

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context
from ..world_model_v21 import (
    WorldModelV21Error,
    WorldModelV21UnavailableError,
    get_world_model_v21_service,
)


async def wm_v21_status(request: Request):
    """GET /api/world-model-v21/status"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    try:
        return JSONResponse(get_world_model_v21_service().status())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def wm_v21_plan(request: Request):
    """POST /api/world-model-v21/plan"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role = _set_user_context(user)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)

    try:
        svc = get_world_model_v21_service()
        result = await asyncio.to_thread(svc.run_plan, body, username)
        map_config = result.pop("map_config", None)
        if map_config:
            _queue_map_update(username, map_config)
            result["map_update_queued"] = True
        return JSONResponse(result)
    except WorldModelV21UnavailableError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    except WorldModelV21Error as exc:
        return JSONResponse(
            {"error": str(exc)}, status_code=getattr(exc, "status_code", 400)
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


def _queue_map_update(user_id: str, map_config: dict):
    from ..frontend_api import _pending_lock, pending_map_updates

    with _pending_lock:
        pending_map_updates[user_id] = map_config


def get_world_model_v21_routes() -> list:
    """Return Route objects for World Model v2.1 endpoints."""
    return [
        Route("/api/world-model-v21/status", wm_v21_status, methods=["GET"]),
        Route("/api/world-model-v21/plan", wm_v21_plan, methods=["POST"]),
    ]
