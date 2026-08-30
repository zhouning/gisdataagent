"""World Model v2.1 REST routes."""

import asyncio

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..world_model_v21 import (
    WorldModelV21Error,
    WorldModelV21UnavailableError,
    get_world_model_v21_service,
)
from .helpers import _get_user_from_request, _set_user_context


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


async def wm_v21_governed_inputs(request: Request):
    """GET /api/world-model-v21/governed-inputs"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    try:
        return JSONResponse(get_world_model_v21_service().list_governed_inputs())
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
        return JSONResponse({"error": str(exc)}, status_code=getattr(exc, "status_code", 400))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def _run_v21_service_method(request: Request, method_name: str):
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
        method = getattr(svc, method_name)
        result = await asyncio.to_thread(method, body, username)
        if method_name == "run_pipeline":
            plan_result = result.get("plan_result") or {}
            map_config = plan_result.pop("map_config", None)
            if map_config:
                _queue_map_update(username, map_config)
                plan_result["map_update_queued"] = True
                result["map_update_queued"] = True
                for step in result.get("steps") or []:
                    if isinstance(step, dict) and step.get("step") == "plan":
                        step.pop("map_config", None)
                        step["map_update_queued"] = True
        return JSONResponse(result)
    except WorldModelV21UnavailableError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    except WorldModelV21Error as exc:
        return JSONResponse({"error": str(exc)}, status_code=getattr(exc, "status_code", 400))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def wm_v21_prepare(request: Request):
    """POST /api/world-model-v21/prepare"""
    return await _run_v21_service_method(request, "run_prepare")


async def wm_v21_sample(request: Request):
    """POST /api/world-model-v21/sample"""
    return await _run_v21_service_method(request, "run_sample")


async def wm_v21_train(request: Request):
    """POST /api/world-model-v21/train"""
    return await _run_v21_service_method(request, "run_train")


async def wm_v21_pipeline(request: Request):
    """POST /api/world-model-v21/pipeline"""
    return await _run_v21_service_method(request, "run_pipeline")


def _queue_map_update(user_id: str, map_config: dict):
    from ..frontend_api import _pending_lock, pending_map_updates

    with _pending_lock:
        pending_map_updates[user_id] = map_config


def get_world_model_v21_routes() -> list:
    """Return Route objects for World Model v2.1 endpoints."""
    return [
        Route("/api/world-model-v21/status", wm_v21_status, methods=["GET"]),
        Route(
            "/api/world-model-v21/governed-inputs",
            wm_v21_governed_inputs,
            methods=["GET"],
        ),
        Route("/api/world-model-v21/prepare", wm_v21_prepare, methods=["POST"]),
        Route("/api/world-model-v21/sample", wm_v21_sample, methods=["POST"]),
        Route("/api/world-model-v21/train", wm_v21_train, methods=["POST"]),
        Route("/api/world-model-v21/plan", wm_v21_plan, methods=["POST"]),
        Route("/api/world-model-v21/pipeline", wm_v21_pipeline, methods=["POST"]),
    ]
