from __future__ import annotations
import asyncio,os
from pathlib import Path
from starlette.responses import JSONResponse
from starlette.routing import Route
from .helpers import _get_user_from_request,_set_user_context
from ..uwm.population_demographic_readiness_service import PopulationDemographicReadinessService
ROOT=Path(__file__).resolve().parents[2];DEFAULT=ROOT/"data/uwm_public_proxy/chongqing_central/population_demographic_readiness_chongqing";CACHE=None
def _service():
 global CACHE;path=Path(os.environ.get("UWM_POPULATION_DEMOGRAPHIC_READINESS_PATH") or DEFAULT)
 if CACHE is None or CACHE[0]!=path:CACHE=(path,PopulationDemographicReadinessService(path))
 return CACHE[1]
def _auth(request):
 user=_get_user_from_request(request)
 if not user:return JSONResponse({"error":"Unauthorized"},status_code=401)
 _set_user_context(user);return None
async def _endpoint(request,method):
 if response:=_auth(request):return response
 try:return JSONResponse(await asyncio.to_thread(getattr(_service(),method)))
 except (FileNotFoundError,ValueError) as exc:return JSONResponse({"error":str(exc)},status_code=503)
def get_uwm_population_demographic_readiness_routes():
 base="/api/uwm/population-demographic-readiness"
 return [Route(base+p,lambda request,m=m:_endpoint(request,m)) for p,m in (("/overview","overview"),("/evidence-products","evidence_products"),("/demographic-channels","demographic_channels"),("/data-contracts","data_contracts"),("/population-gate","population_gate"),("/map","map_payload"))]
