from __future__ import annotations
import asyncio,os
from pathlib import Path
from starlette.responses import JSONResponse
from starlette.routing import Route
from .helpers import _get_user_from_request,_set_user_context
from ..uwm.traditional_cultural_heritage_service import TraditionalCulturalHeritageService
ROOT=Path(__file__).resolve().parents[2];DEFAULT_PRODUCT_DIR=ROOT/'data/uwm_public_proxy/chongqing_central/traditional_cultural_heritage_chongqing';_SERVICE_CACHE=None
def _path():
 p=os.environ.get('UWM_TRADITIONAL_CULTURAL_HERITAGE_PATH','').strip();return Path(p).expanduser() if p else DEFAULT_PRODUCT_DIR
def _service():
 global _SERVICE_CACHE
 p=_path()
 if _SERVICE_CACHE is None or _SERVICE_CACHE[0]!=p:_SERVICE_CACHE=(p,TraditionalCulturalHeritageService(p))
 return _SERVICE_CACHE[1]
def _auth(r):
 u=_get_user_from_request(r)
 if not u:return JSONResponse({'error':'Unauthorized'},status_code=401)
 _set_user_context(u);return None
def _unavailable(e):return JSONResponse({'ready':False,'error':str(e),'blockers':['traditional_cultural_heritage_product_unavailable']},status_code=503)
async def overview(r):
 if (x:=_auth(r)):return x
 try:return JSONResponse(await asyncio.to_thread(_service().overview))
 except Exception as e:return _unavailable(e)
async def places(r):
 if (x:=_auth(r)):return x
 try:return JSONResponse(await asyncio.to_thread(_service().places,r.query_params.get('tier'),r.query_params.get('category')))
 except ValueError as e:return JSONResponse({'error':str(e)},status_code=400)
 except Exception as e:return _unavailable(e)
async def admins(r):
 if (x:=_auth(r)):return x
 try:return JSONResponse(await asyncio.to_thread(_service().admin_units))
 except Exception as e:return _unavailable(e)
async def admin(r):
 if (x:=_auth(r)):return x
 try:return JSONResponse(await asyncio.to_thread(_service().admin_unit,str(r.path_params.get('admin_unit_id') or '')))
 except KeyError as e:return JSONResponse({'error':str(e)},status_code=404)
 except Exception as e:return _unavailable(e)
async def map_payload(r):
 if (x:=_auth(r)):return x
 try:return JSONResponse(await asyncio.to_thread(_service().map_payload,r.query_params.get('tier')))
 except ValueError as e:return JSONResponse({'error':str(e)},status_code=400)
 except Exception as e:return _unavailable(e)
def get_uwm_traditional_cultural_heritage_routes():return [Route('/api/uwm/traditional-livability/cultural-heritage/overview',overview,methods=['GET']),Route('/api/uwm/traditional-livability/cultural-heritage/places',places,methods=['GET']),Route('/api/uwm/traditional-livability/cultural-heritage/admin-units',admins,methods=['GET']),Route('/api/uwm/traditional-livability/cultural-heritage/admin-units/{admin_unit_id}',admin,methods=['GET']),Route('/api/uwm/traditional-livability/cultural-heritage/map',map_payload,methods=['GET'])]
