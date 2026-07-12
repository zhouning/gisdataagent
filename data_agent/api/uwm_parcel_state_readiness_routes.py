from __future__ import annotations

import asyncio
import os
from pathlib import Path

from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context
from ..uwm.parcel_state_readiness_service import ParcelStateReadinessService


ROOT = Path(__file__).resolve().parents[2]; DEFAULT = ROOT / "data/uwm_public_proxy/chongqing_central/parcel_state_readiness_chongqing"; CACHE = None


def _service():
    global CACHE
    path = Path(os.environ.get("UWM_PARCEL_STATE_READINESS_PATH") or DEFAULT)
    if CACHE is None or CACHE[0] != path: CACHE = (path, ParcelStateReadinessService(path))
    return CACHE[1]


def _auth(request):
    user = _get_user_from_request(request)
    if not user: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user); return None


async def _endpoint(request, method):
    if response := _auth(request): return response
    try: return JSONResponse(await asyncio.to_thread(getattr(_service(), method)))
    except (FileNotFoundError, ValueError) as exc: return JSONResponse({"error": str(exc)}, status_code=503)


def get_uwm_parcel_state_readiness_routes():
    base = "/api/uwm/parcel-state-readiness"
    return [Route(base + "/overview", lambda request: _endpoint(request, "overview")), Route(base + "/source-assets", lambda request: _endpoint(request, "source_assets")), Route(base + "/state-channels", lambda request: _endpoint(request, "state_channels")), Route(base + "/data-contracts", lambda request: _endpoint(request, "data_contracts")), Route(base + "/state-gate", lambda request: _endpoint(request, "state_gate")), Route(base + "/map", lambda request: _endpoint(request, "map_payload"))]
