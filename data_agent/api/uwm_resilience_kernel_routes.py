from __future__ import annotations

import asyncio
import os
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context
from ..uwm.resilience_kernel_service import ResilienceKernelService

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / 'data/uwm_public_proxy/chongqing_central/resilience_kernel_chongqing'
CACHE = None


def _service():
    global CACHE
    path = Path(os.environ.get('UWM_RESILIENCE_KERNEL_PATH') or DEFAULT)
    if CACHE is None or CACHE[0] != path:
        CACHE = (path, ResilienceKernelService(path))
    return CACHE[1]


def _reset_service_cache():
    global CACHE
    CACHE = None


def _auth(request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({'error': 'Unauthorized'}, status_code=401)
    _set_user_context(user)
    return None


async def endpoint(request, method):
    if unauthorized := _auth(request):
        return unauthorized
    try:
        return JSONResponse(await asyncio.to_thread(getattr(_service(), method)))
    except Exception as error:
        return JSONResponse({'ready': False, 'error': str(error), 'blockers': ['resilience_kernel_product_unavailable']}, status_code=503)


async def nodes(request: Request):
    if unauthorized := _auth(request):
        return unauthorized
    try:
        return JSONResponse(await asyncio.to_thread(_service().list_nodes, request.query_params.get('search', ''), int(request.query_params.get('limit', '100'))))
    except Exception as error:
        return JSONResponse({'error': str(error)}, status_code=400)


async def node_detail(request: Request):
    if unauthorized := _auth(request):
        return unauthorized
    try:
        return JSONResponse(await asyncio.to_thread(_service().node_detail, str(request.path_params.get('node_id') or '')))
    except ValueError as error:
        return JSONResponse({'error': str(error)}, status_code=404)


async def scenario_readiness(request: Request):
    if unauthorized := _auth(request):
        return unauthorized
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({'error': 'Invalid JSON payload'}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({'error': 'Request object required'}, status_code=400)
    try:
        result = await asyncio.to_thread(_service().scenario_readiness, node_id=str(payload.get('node_id') or ''), hazard_type=str(payload.get('hazard_type') or ''), intervention_type=str(payload.get('intervention_type') or ''))
        return JSONResponse(result)
    except ValueError as error:
        return JSONResponse({'error': str(error)}, status_code=400 if str(error) != 'resilience_node_not_found' else 404)


def get_uwm_resilience_kernel_routes():
    base = '/api/uwm/resilience-kernel'
    def read_route(method):
        async def handler(request):
            return await endpoint(request, method)
        return handler
    routes = [Route(f'{base}/{path}', read_route(method), methods=['GET']) for path, method in [('overview', 'overview'), ('state', 'state'), ('graph', 'graph'), ('gates', 'gates'), ('rollout', 'rollout'), ('dependencies', 'dependencies'), ('map', 'map_payload')]]
    return routes + [
        Route(f'{base}/nodes', nodes, methods=['GET']),
        Route(f'{base}/nodes/{{node_id}}', node_detail, methods=['GET']),
        Route(f'{base}/scenario-readiness', scenario_readiness, methods=['POST']),
    ]
