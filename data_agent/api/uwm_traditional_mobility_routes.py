from __future__ import annotations

import asyncio
import os
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request,_set_user_context
from ..uwm.traditional_mobility_accessibility_service import TraditionalMobilityAccessibilityService


ROOT=Path(__file__).resolve().parents[2]; DEFAULT_PRODUCT_DIR=ROOT/"data/uwm_public_proxy/chongqing_central/traditional_mobility_accessibility_chongqing"; _SERVICE_CACHE=None
def _product_dir():
    configured=os.environ.get("UWM_TRADITIONAL_MOBILITY_PATH","").strip(); return Path(configured).expanduser() if configured else DEFAULT_PRODUCT_DIR
def _service():
    global _SERVICE_CACHE
    path=_product_dir()
    if _SERVICE_CACHE is None or _SERVICE_CACHE[0]!=path: _SERVICE_CACHE=(path,TraditionalMobilityAccessibilityService(path))
    return _SERVICE_CACHE[1]
def _reset_service_cache():
    global _SERVICE_CACHE; _SERVICE_CACHE=None
def _authorized(request):
    user=_get_user_from_request(request)
    if not user: return JSONResponse({"error":"Unauthorized"},status_code=401)
    _set_user_context(user); return None
def _unavailable(error): return JSONResponse({"ready":False,"error":str(error),"blockers":["traditional_mobility_product_unavailable"]},status_code=503)

async def mobility_overview(request:Request):
    unauthorized=_authorized(request)
    if unauthorized:return unauthorized
    try:return JSONResponse(await asyncio.to_thread(_service().overview))
    except Exception as error:return _unavailable(error)
async def mobility_admin_units(request:Request):
    unauthorized=_authorized(request)
    if unauthorized:return unauthorized
    try:return JSONResponse(await asyncio.to_thread(_service().admin_units))
    except Exception as error:return _unavailable(error)
async def mobility_admin_unit(request:Request):
    unauthorized=_authorized(request)
    if unauthorized:return unauthorized
    try:return JSONResponse(await asyncio.to_thread(_service().admin_unit,str(request.path_params.get("admin_unit_id") or "")))
    except KeyError as error:return JSONResponse({"error":str(error)},status_code=404)
    except Exception as error:return _unavailable(error)
async def mobility_map(request:Request):
    unauthorized=_authorized(request)
    if unauthorized:return unauthorized
    try:return JSONResponse(await asyncio.to_thread(_service().map_payload))
    except Exception as error:return _unavailable(error)
def get_uwm_traditional_mobility_routes():
    return [Route("/api/uwm/traditional-livability/mobility/overview",mobility_overview,methods=["GET"]),Route("/api/uwm/traditional-livability/mobility/admin-units",mobility_admin_units,methods=["GET"]),Route("/api/uwm/traditional-livability/mobility/admin-units/{admin_unit_id}",mobility_admin_unit,methods=["GET"]),Route("/api/uwm/traditional-livability/mobility/map",mobility_map,methods=["GET"])]
