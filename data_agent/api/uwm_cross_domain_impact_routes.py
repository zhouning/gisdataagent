from __future__ import annotations
import asyncio,os
from pathlib import Path
from starlette.responses import JSONResponse
from starlette.routing import Route
from .helpers import _get_user_from_request,_set_user_context
from ..uwm.cross_domain_impact_service import CrossDomainImpactService
ROOT=Path(__file__).resolve().parents[2];DEFAULT=ROOT/'data/uwm_public_proxy/chongqing_central/cross_domain_impact_chongqing';CACHE=None
def _service():
 global CACHE
 p=Path(os.environ.get('UWM_CROSS_DOMAIN_IMPACT_PATH') or DEFAULT)
 if CACHE is None or CACHE[0]!=p:CACHE=(p,CrossDomainImpactService(p))
 return CACHE[1]
def _auth(r):
 u=_get_user_from_request(r)
 if not u:return JSONResponse({'error':'Unauthorized'},status_code=401)
 _set_user_context(u);return None
def handler(method):
 async def endpoint(r):
  if (x:=_auth(r)):return x
  try:return JSONResponse(await asyncio.to_thread(getattr(_service(),method)))
  except Exception as e:return JSONResponse({'ready':False,'error':str(e),'blockers':['cross_domain_impact_product_unavailable']},status_code=503)
 return endpoint
def get_uwm_cross_domain_impact_routes():
 base='/api/uwm/cross-domain-impact';return [Route(base+'/overview',handler('overview'),methods=['GET']),Route(base+'/source-products',handler('source_products'),methods=['GET']),Route(base+'/comparability',handler('comparability'),methods=['GET']),Route(base+'/priority-units',handler('priority_units'),methods=['GET']),Route(base+'/dependencies',handler('dependencies'),methods=['GET']),Route(base+'/map',handler('map_payload'),methods=['GET'])]
