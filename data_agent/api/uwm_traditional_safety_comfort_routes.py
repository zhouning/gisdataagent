from __future__ import annotations
import asyncio,os
from pathlib import Path
from starlette.responses import JSONResponse
from starlette.routing import Route
from .helpers import _get_user_from_request,_set_user_context
from ..uwm.traditional_safety_comfort_service import TraditionalSafetyComfortService
ROOT=Path(__file__).resolve().parents[2];DEFAULT_PRODUCT_DIR=ROOT/'data/uwm_public_proxy/chongqing_central/traditional_safety_comfort_chongqing';_SERVICE_CACHE=None
def _path():
 p=os.environ.get('UWM_TRADITIONAL_SAFETY_COMFORT_PATH','').strip();return Path(p).expanduser() if p else DEFAULT_PRODUCT_DIR
def _service():
 global _SERVICE_CACHE
 p=_path()
 if _SERVICE_CACHE is None or _SERVICE_CACHE[0]!=p:_SERVICE_CACHE=(p,TraditionalSafetyComfortService(p))
 return _SERVICE_CACHE[1]
def _reset_service_cache():
 global _SERVICE_CACHE;_SERVICE_CACHE=None
def _auth(r):
 u=_get_user_from_request(r)
 if not u:return JSONResponse({'error':'Unauthorized'},status_code=401)
 _set_user_context(u);return None
def _unavailable(e):return JSONResponse({'ready':False,'error':str(e),'blockers':['traditional_safety_comfort_product_unavailable']},status_code=503)
async def safety_comfort_overview(r):
 if (x:=_auth(r)):return x
 try:return JSONResponse(await asyncio.to_thread(_service().overview))
 except Exception as e:return _unavailable(e)
async def safety_comfort_admin_units(r):
 if (x:=_auth(r)):return x
 try:return JSONResponse(await asyncio.to_thread(_service().admin_units))
 except Exception as e:return _unavailable(e)
async def safety_comfort_admin_unit(r):
 if (x:=_auth(r)):return x
 try:return JSONResponse(await asyncio.to_thread(_service().admin_unit,str(r.path_params.get('admin_unit_id') or '')))
 except KeyError as e:return JSONResponse({'error':str(e)},status_code=404)
 except Exception as e:return _unavailable(e)
async def safety_comfort_evidence_sources(r):
 if (x:=_auth(r)):return x
 try:return JSONResponse(await asyncio.to_thread(_service().evidence_sources))
 except Exception as e:return _unavailable(e)
async def safety_comfort_map(r):
 if (x:=_auth(r)):return x
 try:return JSONResponse(await asyncio.to_thread(_service().map_payload))
 except Exception as e:return _unavailable(e)
def get_uwm_traditional_safety_comfort_routes():return [Route('/api/uwm/traditional-livability/safety-comfort/overview',safety_comfort_overview,methods=['GET']),Route('/api/uwm/traditional-livability/safety-comfort/admin-units',safety_comfort_admin_units,methods=['GET']),Route('/api/uwm/traditional-livability/safety-comfort/admin-units/{admin_unit_id}',safety_comfort_admin_unit,methods=['GET']),Route('/api/uwm/traditional-livability/safety-comfort/evidence-sources',safety_comfort_evidence_sources,methods=['GET']),Route('/api/uwm/traditional-livability/safety-comfort/map',safety_comfort_map,methods=['GET'])]
