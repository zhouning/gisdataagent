from __future__ import annotations

import asyncio
import os
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context
from ..uwm.environmental_kernel.service import EnvironmentalKernelConflict, EnvironmentalKernelService


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRODUCT_DIR = ROOT / "data/uwm_public_proxy/chongqing_central/uwm_environmental_kernel_chongqing"
_SERVICE_CACHE: tuple[Path, EnvironmentalKernelService] | None = None


def _product_dir() -> Path:
    configured = os.environ.get("UWM_ENVIRONMENTAL_KERNEL_PATH", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_PRODUCT_DIR


def _service() -> EnvironmentalKernelService:
    global _SERVICE_CACHE
    path = _product_dir()
    if _SERVICE_CACHE is None or _SERVICE_CACHE[0] != path:
        _SERVICE_CACHE = (path, EnvironmentalKernelService(path))
    return _SERVICE_CACHE[1]


def _reset_service_cache():
    global _SERVICE_CACHE
    _SERVICE_CACHE = None


def _authorized(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return None, JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    return username, None


async def environmental_kernel_scene(request: Request):
    _, unauthorized = _authorized(request)
    if unauthorized:
        return unauthorized
    try:
        return JSONResponse(await asyncio.to_thread(_service().scene))
    except Exception as error:
        return JSONResponse({"error": str(error), "ready": False}, status_code=503)


async def environmental_kernel_evidence_gate(request: Request):
    _, unauthorized = _authorized(request)
    if unauthorized:
        return unauthorized
    try:
        return JSONResponse(await asyncio.to_thread(_service().evidence_gate))
    except Exception as error:
        return JSONResponse({"error": str(error), "ready": False}, status_code=503)


async def environmental_kernel_map(request: Request):
    _, unauthorized = _authorized(request)
    if unauthorized:
        return unauthorized
    try:
        return JSONResponse(await asyncio.to_thread(_service().map_payload))
    except Exception as error:
        return JSONResponse({"error": str(error), "ready": False}, status_code=503)


async def environmental_kernel_nodes(request: Request):
    _, unauthorized = _authorized(request)
    if unauthorized:
        return unauthorized
    try:
        return JSONResponse(await asyncio.to_thread(_service().list_nodes, request.query_params.get("search", "")))
    except Exception as error:
        return JSONResponse({"error": str(error), "ready": False}, status_code=503)


async def environmental_kernel_temporal_replay(request: Request):
    _, unauthorized = _authorized(request)
    if unauthorized:
        return unauthorized
    try:
        return JSONResponse(await asyncio.to_thread(_service().temporal_replay, str(request.path_params.get("node_id") or "")))
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=404)
    except Exception as error:
        return JSONResponse({"error": str(error), "ready": False}, status_code=503)


async def environmental_kernel_rollout(request: Request):
    actor, unauthorized = _authorized(request)
    if unauthorized:
        return unauthorized
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            return JSONResponse({"error": "Request object required"}, status_code=400)
    except Exception:
        return JSONResponse({"error": "Invalid JSON payload"}, status_code=400)
    try:
        return JSONResponse(await asyncio.to_thread(_service().run, request=payload, actor=str(actor)))
    except EnvironmentalKernelConflict as error:
        return JSONResponse({"error": error.code, "actor": error.actor, "not_a_causal_effect_estimate": True}, status_code=409)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    except Exception as error:
        return JSONResponse({"error": str(error), "ready": False}, status_code=503)


def get_uwm_environmental_kernel_routes() -> list:
    return [
        Route("/api/uwm/livability/environmental-kernel/scene", environmental_kernel_scene, methods=["GET"]),
        Route("/api/uwm/livability/environmental-kernel/evidence-gate", environmental_kernel_evidence_gate, methods=["GET"]),
        Route("/api/uwm/livability/environmental-kernel/rollout", environmental_kernel_rollout, methods=["POST"]),
        Route("/api/uwm/livability/environmental-kernel/map", environmental_kernel_map, methods=["GET"]),
        Route("/api/uwm/livability/environmental-kernel/nodes", environmental_kernel_nodes, methods=["GET"]),
        Route("/api/uwm/livability/environmental-kernel/temporal-replay/{node_id}", environmental_kernel_temporal_replay, methods=["GET"]),
    ]
