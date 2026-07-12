from __future__ import annotations

import asyncio
import os
from pathlib import Path

from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context
from ..uwm.development_control_service import DevelopmentControlService


ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / "data/uwm_public_proxy/chongqing_central/development_control_chongqing"
CACHE = None


def _service():
    global CACHE
    path = Path(os.environ.get("UWM_DEVELOPMENT_CONTROL_PATH") or DEFAULT)
    if CACHE is None or CACHE[0] != path:
        CACHE = (path, DevelopmentControlService(path))
    return CACHE[1]


def _auth(request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    return None


async def _endpoint(request, method):
    if response := _auth(request):
        return response
    try:
        return JSONResponse(await asyncio.to_thread(getattr(_service(), method)))
    except (FileNotFoundError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)


def get_uwm_development_control_routes():
    base = "/api/uwm/development-control"
    return [
        Route(base + "/overview", lambda request: _endpoint(request, "overview")),
        Route(base + "/rule-assets", lambda request: _endpoint(request, "rule_assets")),
        Route(base + "/dcr-channels", lambda request: _endpoint(request, "dcr_channels")),
        Route(base + "/data-contracts", lambda request: _endpoint(request, "data_contracts")),
        Route(base + "/execution-gate", lambda request: _endpoint(request, "execution_gate")),
        Route(base + "/map", lambda request: _endpoint(request, "map_payload")),
    ]
