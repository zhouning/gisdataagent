from __future__ import annotations
import asyncio,os
from pathlib import Path
from starlette.responses import JSONResponse
from starlette.routing import Route
from .helpers import _get_user_from_request,_set_user_context
from ..uwm.digital_readiness_service import DigitalReadinessService
ROOT=Path(__file__).resolve().parents[2];DEFAULT=ROOT/'data/uwm_public_proxy/chongqing_central/digital_readiness_chongqing';CACHE=None
def _service():
 global CACHE
 p=Path(os.environ.get('UWM_DIGITAL_READINESS_PATH') or DEFAULT)
 if CACHE is None or CACHE[0]!=p:CACHE=(p,DigitalReadinessService(p))
 return CACHE[1]
def _auth(r):
 u=_get_user_from_request(r)
 if not u:return JSONResponse({'error':'Unauthorized'},status_code=401)
 _set_user_context(u);return None
async def endpoint(r,m):
 if (x:=_auth(r)):return x
 try:return JSONResponse(await asyncio.to_thread(getattr(_service(),m)))
 except Exception as e:return JSONResponse({'ready':False,'error':str(e),'blockers':['digital_readiness_product_unavailable']},status_code=503)
def get_uwm_digital_readiness_routes():
 b='/api/uwm/digital-readiness';return [Route(b+'/'+p,lambda r,m=m:endpoint(r,m),methods=['GET']) for p,m in [('overview','overview'),('platform-capabilities','platform_capabilities'),('infrastructure-channels','infrastructure_channels'),('data-contracts','data_contracts'),('uwm-gate','uwm_gate'),('map','map_payload')]]
