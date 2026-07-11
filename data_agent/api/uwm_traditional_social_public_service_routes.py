from __future__ import annotations
import asyncio,os
from pathlib import Path
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from .helpers import _get_user_from_request,_set_user_context
from ..uwm.traditional_social_public_service_service import TraditionalSocialPublicServiceService
ROOT=Path(__file__).resolve().parents[2];DEFAULT_PRODUCT_DIR=ROOT/'data/uwm_public_proxy/chongqing_central/traditional_social_public_service_chongqing';_SERVICE_CACHE=None
def _product_dir():
 p=os.environ.get('UWM_TRADITIONAL_SOCIAL_PUBLIC_SERVICE_PATH','').strip();return Path(p).expanduser() if p else DEFAULT_PRODUCT_DIR
def _service():
 global _SERVICE_CACHE
 p=_product_dir()
 if _SERVICE_CACHE is None or _SERVICE_CACHE[0]!=p:_SERVICE_CACHE=(p,TraditionalSocialPublicServiceService(p))
 return _SERVICE_CACHE[1]
def _reset_service_cache():
 global _SERVICE_CACHE;_SERVICE_CACHE=None
def _authorized(request):
 u=_get_user_from_request(request)
 if not u:return JSONResponse({'error':'Unauthorized'},status_code=401)
 _set_user_context(u);return None
def _view(request):return request.query_params.get('view','social_infrastructure')
def _unavailable(error):return JSONResponse({'ready':False,'error':str(error),'blockers':['traditional_social_public_service_product_unavailable']},status_code=503)
async def social_public_service_overview(request):
 if (r:=_authorized(request)):return r
 try:return JSONResponse(await asyncio.to_thread(_service().overview))
 except Exception as e:return _unavailable(e)
async def social_public_service_facilities(request):
 if (r:=_authorized(request)):return r
 try:return JSONResponse(await asyncio.to_thread(_service().facilities,_view(request)))
 except ValueError as e:return JSONResponse({'error':str(e)},status_code=400)
 except Exception as e:return _unavailable(e)
async def social_public_service_admin_units(request):
 if (r:=_authorized(request)):return r
 try:return JSONResponse(await asyncio.to_thread(_service().admin_units,_view(request)))
 except ValueError as e:return JSONResponse({'error':str(e)},status_code=400)
 except Exception as e:return _unavailable(e)
async def social_public_service_admin_unit(request):
 if (r:=_authorized(request)):return r
 try:return JSONResponse(await asyncio.to_thread(_service().admin_unit,str(request.path_params.get('admin_unit_id') or ''),_view(request)))
 except KeyError as e:return JSONResponse({'error':str(e)},status_code=404)
 except ValueError as e:return JSONResponse({'error':str(e)},status_code=400)
 except Exception as e:return _unavailable(e)
async def social_public_service_map(request):
 if (r:=_authorized(request)):return r
 try:return JSONResponse(await asyncio.to_thread(_service().map_payload,request.query_params.get('view')))
 except ValueError as e:return JSONResponse({'error':str(e)},status_code=400)
 except Exception as e:return _unavailable(e)
def get_uwm_traditional_social_public_service_routes():return [Route('/api/uwm/traditional-livability/social-public-service/overview',social_public_service_overview,methods=['GET']),Route('/api/uwm/traditional-livability/social-public-service/facilities',social_public_service_facilities,methods=['GET']),Route('/api/uwm/traditional-livability/social-public-service/admin-units',social_public_service_admin_units,methods=['GET']),Route('/api/uwm/traditional-livability/social-public-service/admin-units/{admin_unit_id}',social_public_service_admin_unit,methods=['GET']),Route('/api/uwm/traditional-livability/social-public-service/map',social_public_service_map,methods=['GET'])]
