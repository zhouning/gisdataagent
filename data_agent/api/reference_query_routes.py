"""Reference Query Library REST API routes (v19.0)."""
from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request


async def _api_refq_list(request: Request):
    """GET /api/reference-queries?pipeline_type=...&source=...&limit=50"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from ..reference_queries import ReferenceQueryStore

    pipeline_type = request.query_params.get("pipeline_type")
    source = request.query_params.get("source")
    limit = int(request.query_params.get("limit", "50"))
    offset = int(request.query_params.get("offset", "0"))

    items = ReferenceQueryStore().list(
        pipeline_type=pipeline_type, source=source, limit=limit, offset=offset
    )
    return JSONResponse(items)


async def _api_refq_create(request: Request):
    """POST /api/reference-queries — create a reference query."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    query_text = body.get("query_text", "")
    if not query_text:
        return JSONResponse({"error": "query_text required"}, status_code=400)

    from ..reference_queries import ReferenceQueryStore

    ref_id = ReferenceQueryStore().add(
        query_text=query_text,
        description=body.get("description", ""),
        response_summary=body.get("response_summary", ""),
        tags=body.get("tags"),
        pipeline_type=body.get("pipeline_type"),
        task_type=body.get("task_type"),
        source="manual",
        created_by=user.get("username", ""),
    )
    if ref_id is None:
        return JSONResponse({"error": "failed to create"}, status_code=500)
    return JSONResponse({"id": ref_id, "status": "created"})


async def _api_refq_detail(request: Request):
    """GET /api/reference-queries/{id}"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    ref_id = int(request.path_params["id"])

    from ..reference_queries import ReferenceQueryStore

    item = ReferenceQueryStore().get(ref_id)
    if not item:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(item)


async def _api_refq_update(request: Request):
    """PUT /api/reference-queries/{id}"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    ref_id = int(request.path_params["id"])
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    from ..reference_queries import ReferenceQueryStore

    ok = ReferenceQueryStore().update(ref_id, **body)
    if not ok:
        return JSONResponse({"error": "update failed"}, status_code=500)
    return JSONResponse({"status": "updated"})


async def _api_refq_delete(request: Request):
    """DELETE /api/reference-queries/{id}"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    ref_id = int(request.path_params["id"])

    from ..reference_queries import ReferenceQueryStore

    ok = ReferenceQueryStore().delete(ref_id)
    if not ok:
        return JSONResponse({"error": "delete failed"}, status_code=500)
    return JSONResponse({"status": "deleted"})


async def _api_refq_search(request: Request):
    """POST /api/reference-queries/search — embedding-based search."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    query = body.get("query", "")
    if not query:
        return JSONResponse({"error": "query required"}, status_code=400)

    from ..reference_queries import ReferenceQueryStore

    results = ReferenceQueryStore().search(
        query=query,
        top_k=int(body.get("top_k", 5)),
        pipeline_type=body.get("pipeline_type"),
        task_type=body.get("task_type"),
    )
    return JSONResponse(results)


def get_reference_query_routes() -> list[Route]:
    return [
        Route("/api/reference-queries", endpoint=_api_refq_list, methods=["GET"]),
        Route("/api/reference-queries", endpoint=_api_refq_create, methods=["POST"]),
        Route("/api/reference-queries/search", endpoint=_api_refq_search, methods=["POST"]),
        Route("/api/reference-queries/{id:int}", endpoint=_api_refq_detail, methods=["GET"]),
        Route("/api/reference-queries/{id:int}", endpoint=_api_refq_update, methods=["PUT"]),
        Route("/api/reference-queries/{id:int}", endpoint=_api_refq_delete, methods=["DELETE"]),
    ]
