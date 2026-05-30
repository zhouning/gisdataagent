"""World Model v2 API routes — Bishan county farmland optimization endpoints."""

import asyncio
import json
import os

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context


async def wm_v2_status(request: Request):
    """GET /api/world-model-v2/status"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    from ..world_model_v2 import get_world_model_v2_service
    try:
        svc = get_world_model_v2_service()
        return JSONResponse(svc.status())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def wm_v2_run(request: Request):
    """POST /api/world-model-v2/run"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    try:
        body = await request.json()
    except Exception:
        body = {}

    n_episodes = int(body.get("n_episodes", 10))
    if n_episodes < 1 or n_episodes > 50:
        return JSONResponse(
            {"error": "n_episodes must be between 1 and 50"}, status_code=400
        )

    mode = str(body.get("mode", "ppo")).strip().lower()
    if mode not in {"ppo", "dream_v5", "mpc"}:
        return JSONResponse(
            {"error": "mode must be 'ppo', 'dream_v5', or 'mpc'"}, status_code=400
        )

    from ..world_model_v2 import get_world_model_v2_service
    try:
        svc = get_world_model_v2_service()
        result = await asyncio.to_thread(svc.run_optimization, n_episodes, mode)

        if result.get("status") == "error":
            return JSONResponse(result, status_code=503)

        map_config = result.get("map_config")
        if map_config:
            try:
                from ..user_context import current_user_id
                from ..frontend_api import pending_map_updates, _pending_lock
                uid = current_user_id.get("admin")
                with _pending_lock:
                    pending_map_updates[uid] = map_config
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    "Failed to push map update: %s", e
                )

        summary = {k: v for k, v in result.items() if k != "map_config"}
        return JSONResponse(summary)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def get_world_model_v2_routes() -> list:
    """Return Route objects for world model v2 endpoints."""
    return [
        Route("/api/world-model-v2/status", wm_v2_status, methods=["GET"]),
        Route("/api/world-model-v2/run", wm_v2_run, methods=["POST"]),
    ]
