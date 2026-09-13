from __future__ import annotations
import asyncio,os
from pathlib import Path
from starlette.responses import JSONResponse
from starlette.routing import Route
from .helpers import _get_user_from_request,_set_user_context
from ..uwm.operations_quality_service import OperationsQualityService
ROOT=Path(__file__).resolve().parents[2];DEFAULT=ROOT/'data/uwm_public_proxy/chongqing_central/operations_quality_chongqing';CACHE=None
def _service():
 global CACHE
 p=Path(os.environ.get('UWM_OPERATIONS_QUALITY_PATH') or DEFAULT)
 if CACHE is None or CACHE[0]!=p:CACHE=(p,OperationsQualityService(p))
 return CACHE[1]
def _auth(r):
 u=_get_user_from_request(r)
 if not u:return JSONResponse({'error':'Unauthorized'},status_code=401)
 _set_user_context(u);return None
async def endpoint(r,m):
 if (x:=_auth(r)):return x
 try:return JSONResponse(await asyncio.to_thread(getattr(_service(),m)))
 except Exception as e:return JSONResponse({'ready':False,'error':str(e),'blockers':['operations_quality_product_unavailable']},status_code=503)
def get_uwm_operations_quality_routes():
 b='/api/uwm/operations-quality';return [Route(b+'/'+p,lambda r,m=m:endpoint(r,m),methods=['GET']) for p,m in [('overview','overview'),('platform-operations','platform_operations'),('customer-channels','customer_channels'),('data-contracts','data_contracts'),('uwm-gate','uwm_gate'),('map','map_payload')]]
