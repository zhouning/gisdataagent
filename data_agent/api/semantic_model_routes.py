"""Semantic Model (MetricFlow) REST API routes (v19.0)."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request


async def _api_sm_list(request: Request):
    """GET /api/semantic/models — list active semantic models."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from ..semantic_model import SemanticModelStore
    items = SemanticModelStore().list_active()
    return JSONResponse(items)


async def _api_sm_create(request: Request):
    """POST /api/semantic/models — create/update a semantic model from YAML."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    yaml_content = body.get("yaml_content", "")
    name = body.get("name", "")
    if not yaml_content or not name:
        return JSONResponse({"error": "name and yaml_content required"}, status_code=400)

    from ..semantic_model import SemanticModelStore
    try:
        model_id = SemanticModelStore().save(
            name=name,
            yaml_text=yaml_content,
            description=body.get("description", ""),
            created_by=user.get("username", ""),
        )
        if model_id is None:
            return JSONResponse({"error": "failed to save"}, status_code=500)
        return JSONResponse({"id": model_id, "status": "saved"})
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


async def _api_sm_detail(request: Request):
    """GET /api/semantic/models/{name}"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    name = request.path_params["name"]
    from ..semantic_model import SemanticModelStore
    item = SemanticModelStore().get(name)
    if not item:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(item)


async def _api_sm_delete(request: Request):
    """DELETE /api/semantic/models/{name}"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    name = request.path_params["name"]
    from ..semantic_model import SemanticModelStore
    ok = SemanticModelStore().delete(name)
    if not ok:
        return JSONResponse({"error": "delete failed"}, status_code=500)
    return JSONResponse({"status": "deleted"})


async def _api_sm_generate(request: Request):
    """POST /api/semantic/models/generate — auto-generate from PostGIS table."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    table_name = body.get("table_name", "")
    if not table_name:
        return JSONResponse({"error": "table_name required"}, status_code=400)

    from ..semantic_model import SemanticModelGenerator
    try:
        yaml_text = SemanticModelGenerator().generate_from_table(table_name)
        return JSONResponse({"yaml_content": yaml_text, "table_name": table_name})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def get_semantic_model_routes() -> list[Route]:
    return [
        Route("/api/semantic/models", endpoint=_api_sm_list, methods=["GET"]),
        Route("/api/semantic/models", endpoint=_api_sm_create, methods=["POST"]),
        Route("/api/semantic/models/generate", endpoint=_api_sm_generate, methods=["POST"]),
        Route("/api/semantic/models/{name:path}", endpoint=_api_sm_detail, methods=["GET"]),
        Route("/api/semantic/models/{name:path}", endpoint=_api_sm_delete, methods=["DELETE"]),
    ]
