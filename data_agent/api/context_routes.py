"""Context Engine REST API routes (v19.0)."""

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request


async def _api_context_prepare(request: Request):
    """GET /api/v2/context/prepare?query=...&task_type=...&budget=..."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    query = request.query_params.get("query", "")
    task_type = request.query_params.get("task_type", "general")
    budget = int(request.query_params.get("budget", "0")) or None
    try:
        from ..context_engine import get_context_engine
        engine = get_context_engine()
        blocks = engine.prepare(query, task_type, {"user_id": user.get("username", "")}, budget)
        return JSONResponse([
            {
                "provider": b.provider,
                "source": b.source,
                "content": b.content[:500],
                "token_count": b.token_count,
                "relevance_score": round(b.relevance_score, 4),
                "metadata": b.metadata,
            }
            for b in blocks
        ])
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def _api_context_providers(request: Request):
    """GET /api/v2/context/providers — list registered providers."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        from ..context_engine import get_context_engine
        engine = get_context_engine()
        return JSONResponse(engine.list_providers())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def get_context_routes() -> list[Route]:
    return [
        Route("/api/v2/context/prepare", endpoint=_api_context_prepare, methods=["GET"]),
        Route("/api/v2/context/providers", endpoint=_api_context_providers, methods=["GET"]),
    ]
