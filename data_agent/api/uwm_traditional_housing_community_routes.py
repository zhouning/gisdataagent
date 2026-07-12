from __future__ import annotations
import asyncio,os
from pathlib import Path
from starlette.responses import JSONResponse
from starlette.routing import Route
from .helpers import _get_user_from_request,_set_user_context
from ..uwm.traditional_housing_community_service import TraditionalHousingCommunityService
ROOT=Path(__file__).resolve().parents[2];DEFAULT_PRODUCT_DIR=ROOT/'data/uwm_public_proxy/chongqing_central/traditional_housing_community_chongqing';_SERVICE_CACHE=None
def _path():
 p=os.environ.get('UWM_TRADITIONAL_HOUSING_COMMUNITY_PATH','').strip();return Path(p).expanduser() if p else DEFAULT_PRODUCT_DIR
def _service():
 global _SERVICE_CACHE
 p=_path()
 if _SERVICE_CACHE is None or _SERVICE_CACHE[0]!=p:_SERVICE_CACHE=(p,TraditionalHousingCommunityService(p))
 return _SERVICE_CACHE[1]
def _reset_service_cache():
 global _SERVICE_CACHE;_SERVICE_CACHE=None
def _auth(r):
 u=_get_user_from_request(r)
 if not u:return JSONResponse({'error':'Unauthorized'},status_code=401)
 _set_user_context(u);return None
def _bad(e):return JSONResponse({'error':str(e)},status_code=400)
def _unavailable(e):return JSONResponse({'ready':False,'error':str(e),'blockers':['traditional_housing_community_product_unavailable']},status_code=503)
async def overview(r):
 if (x:=_auth(r)):return x
 try:return JSONResponse(await asyncio.to_thread(_service().overview))
 except Exception as e:return _unavailable(e)
async def admin_units(r):
 if (x:=_auth(r)):return x
 try:return JSONResponse(await asyncio.to_thread(_service().admin_units,r.query_params.get('view')))
 except ValueError as e:return _bad(e)
 except Exception as e:return _unavailable(e)
async def admin_unit(r):
 if (x:=_auth(r)):return x
 try:return JSONResponse(await asyncio.to_thread(_service().admin_unit,str(r.path_params.get('admin_unit_id') or '')))
 except KeyError as e:return JSONResponse({'error':str(e)},status_code=404)
 except Exception as e:return _unavailable(e)
async def readiness(r):
 if (x:=_auth(r)):return x
 try:return JSONResponse(await asyncio.to_thread(_service().readiness))
 except Exception as e:return _unavailable(e)
async def map_payload(r):
 if (x:=_auth(r)):return x
 try:return JSONResponse(await asyncio.to_thread(_service().map_payload,r.query_params.get('view')))
 except ValueError as e:return _bad(e)
 except Exception as e:return _unavailable(e)
def get_uwm_traditional_housing_community_routes():return [Route('/api/uwm/traditional-livability/housing-community/overview',overview,methods=['GET']),Route('/api/uwm/traditional-livability/housing-community/admin-units',admin_units,methods=['GET']),Route('/api/uwm/traditional-livability/housing-community/admin-units/{admin_unit_id}',admin_unit,methods=['GET']),Route('/api/uwm/traditional-livability/housing-community/readiness',readiness,methods=['GET']),Route('/api/uwm/traditional-livability/housing-community/map',map_payload,methods=['GET'])]
