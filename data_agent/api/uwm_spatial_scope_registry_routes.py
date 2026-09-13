from __future__ import annotations

import asyncio
import os
from pathlib import Path

from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context
from ..uwm.spatial_scope_registry_service import SpatialScopeRegistryService


ROOT = Path(__file__).resolve().parents[2]; DEFAULT = ROOT / "data/uwm_public_proxy/chongqing_central/spatial_scope_registry_chongqing"; CACHE = None


def _service():
    global CACHE
    path = Path(os.environ.get("UWM_SPATIAL_SCOPE_REGISTRY_PATH") or DEFAULT)
    if CACHE is None or CACHE[0] != path: CACHE = (path, SpatialScopeRegistryService(path))
    return CACHE[1]


def _auth(request):
    user = _get_user_from_request(request)
    if not user: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user); return None


async def _endpoint(request, method):
    if response := _auth(request): return response
    try: return JSONResponse(await asyncio.to_thread(getattr(_service(), method)))
    except (FileNotFoundError, ValueError) as exc: return JSONResponse({"error": str(exc)}, status_code=503)


def get_uwm_spatial_scope_registry_routes():
    base = "/api/uwm/spatial-scope-registry"
    return [Route(base + "/overview", lambda request: _endpoint(request, "overview")), Route(base + "/spatial-units", lambda request: _endpoint(request, "spatial_units")), Route(base + "/scope-registry", lambda request: _endpoint(request, "scope_registry")), Route(base + "/diagnostics", lambda request: _endpoint(request, "diagnostics")), Route(base + "/data-contracts", lambda request: _endpoint(request, "data_contracts")), Route(base + "/map", lambda request: _endpoint(request, "map_payload"))]
