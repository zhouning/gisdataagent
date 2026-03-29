"""Metadata management API routes."""
import json
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context

logger = logging.getLogger(__name__)


async def _api_metadata_search(request: Request):
    """GET /api/metadata/search?q=...&region=...&domain=...&source_type=..."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    from ..metadata_manager import MetadataManager
    mgr = MetadataManager()

    q = request.query_params.get("q")
    filters = {}
    for key in ("region", "domain", "source_type"):
        val = request.query_params.get(key)
        if val:
            filters[key] = val

    limit = int(request.query_params.get("limit", "50"))
    results = mgr.search_assets(query=q, filters=filters or None, limit=limit)
    return JSONResponse({"assets": results, "total": len(results)})


async def _api_metadata_detail(request: Request):
    """GET /api/metadata/{asset_id}"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    from ..metadata_manager import MetadataManager
    mgr = MetadataManager()

    asset_id = int(request.path_params["asset_id"])
    layers_param = request.query_params.get("layers")
    layers = layers_param.split(",") if layers_param else None
    result = mgr.get_metadata(asset_id, layers=layers)
    if not result:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(result)


async def _api_metadata_update(request: Request):
    """PUT /api/metadata/{asset_id}"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    from ..metadata_manager import MetadataManager
    mgr = MetadataManager()

    asset_id = int(request.path_params["asset_id"])
    body = await request.json()
    ok = mgr.update_metadata(
        asset_id,
        technical=body.get("technical"),
        business=body.get("business"),
        operational=body.get("operational"),
        lineage=body.get("lineage"),
    )
    return JSONResponse({"updated": ok})


async def _api_metadata_lineage(request: Request):
    """GET /api/metadata/{asset_id}/lineage"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    from ..metadata_manager import MetadataManager
    mgr = MetadataManager()

    asset_id = int(request.path_params["asset_id"])
    lineage = mgr.get_lineage(asset_id)
    return JSONResponse(lineage)


def get_metadata_routes():
    return [
        Route("/api/metadata/search", endpoint=_api_metadata_search, methods=["GET"]),
        Route("/api/metadata/{asset_id:int}", endpoint=_api_metadata_detail, methods=["GET"]),
        Route("/api/metadata/{asset_id:int}", endpoint=_api_metadata_update, methods=["PUT"]),
        Route("/api/metadata/{asset_id:int}/lineage", endpoint=_api_metadata_lineage, methods=["GET"]),
    ]
