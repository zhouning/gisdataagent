from __future__ import annotations
import asyncio, os
from pathlib import Path
from starlette.responses import JSONResponse
from starlette.routing import Route
from .helpers import _get_user_from_request, _set_user_context
from ..uwm.asset_lifecycle_readiness_service import AssetLifecycleReadinessService

ROOT=Path(__file__).resolve().parents[2]; DEFAULT=ROOT/"data/uwm_public_proxy/chongqing_central/asset_lifecycle_readiness_chongqing"; CACHE=None
def _service():
    global CACHE
    path=Path(os.environ.get("UWM_ASSET_LIFECYCLE_READINESS_PATH") or DEFAULT)
    if CACHE is None or CACHE[0]!=path: CACHE=(path,AssetLifecycleReadinessService(path))
    return CACHE[1]
def _auth(request):
    user=_get_user_from_request(request)
    if not user:return JSONResponse({"error":"Unauthorized"},status_code=401)
    _set_user_context(user);return None
async def _endpoint(request,method):
    if response:=_auth(request):return response
    try:return JSONResponse(await asyncio.to_thread(getattr(_service(),method)))
    except (FileNotFoundError,ValueError) as exc:return JSONResponse({"error":str(exc)},status_code=503)
def get_uwm_asset_lifecycle_readiness_routes():
    base="/api/uwm/asset-lifecycle-readiness"
    return [Route(base+path,lambda request,m=method:_endpoint(request,m)) for path,method in (("/overview","overview"),("/source-products","source_products"),("/lifecycle-channels","lifecycle_channels"),("/data-contracts","data_contracts"),("/lifecycle-gate","lifecycle_gate"),("/map","map_payload"))]
