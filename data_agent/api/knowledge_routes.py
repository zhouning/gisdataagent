"""Knowledge Layer REST routes — semantic vocab, standard rules, model repo."""

import logging
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context

logger = logging.getLogger("data_agent.api.knowledge_routes")

# Lazy singleton
_vocab = None


def _get_vocab():
    global _vocab
    if _vocab is None:
        from ..knowledge.semantic_vocab import SemanticVocab
        _vocab = SemanticVocab()
    return _vocab


async def vocab_list(request: Request):
    """GET /api/knowledge/vocab — list all semantic equivalence groups."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    vocab = _get_vocab()
    groups = [
        {"group_id": gid, "fields": fields, "field_count": len(fields)}
        for gid, fields in vocab._groups.items()
    ]
    return JSONResponse({
        "groups": groups,
        "total_groups": vocab.group_count,
        "total_fields": vocab.field_count,
    })


async def vocab_detail(request: Request):
    """GET /api/knowledge/vocab/{group_id} — fields in a group."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    group_id = request.path_params.get("group_id", "")
    vocab = _get_vocab()
    fields = vocab.get_group_fields(group_id)
    if not fields:
        return JSONResponse({"error": "Group not found"}, status_code=404)
    return JSONResponse({"group_id": group_id, "fields": fields})


async def standards_list(request: Request):
    """GET /api/knowledge/standards — list loaded standard documents."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        from ..standard_registry import get_registry
        registry = get_registry()
        standards = []
        for name, std in registry._standards.items():
            standards.append({
                "name": name,
                "description": std.get("description", ""),
                "table_count": len(std.get("tables", [])),
                "field_count": sum(
                    len(t.get("fields", [])) for t in std.get("tables", [])
                ),
            })
        return JSONResponse({"standards": standards})
    except Exception as e:
        logger.warning("Failed to load standards: %s", e)
        return JSONResponse({"standards": [], "warning": str(e)})


async def standards_detail(request: Request):
    """GET /api/knowledge/standards/{name} — standard detail with tables."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    name = request.path_params.get("name", "")
    try:
        from ..standard_registry import get_registry
        registry = get_registry()
        std = registry._standards.get(name)
        if not std:
            return JSONResponse({"error": "Standard not found"}, status_code=404)
        return JSONResponse(std)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def models_list(request: Request):
    """GET /api/knowledge/models — list parsed domain models (if any)."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    # Model repo requires XMI files to be loaded; return empty if none
    return JSONResponse({
        "models": [],
        "hint": "Upload EA XMI files via knowledge management to populate.",
    })


def get_knowledge_routes() -> list:
    return [
        Route("/api/knowledge/vocab", vocab_list, methods=["GET"]),
        Route("/api/knowledge/vocab/{group_id:str}", vocab_detail, methods=["GET"]),
        Route("/api/knowledge/standards", standards_list, methods=["GET"]),
        Route("/api/knowledge/standards/{name:str}", standards_detail, methods=["GET"]),
        Route("/api/knowledge/models", models_list, methods=["GET"]),
    ]
