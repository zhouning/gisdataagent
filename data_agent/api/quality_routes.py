"""Quality Rules + Trends + Resource Overview REST routes (v14.5)."""

import logging
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context

logger = logging.getLogger("data_agent.api.quality_routes")


async def qrule_list(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    from ..quality_rules import list_rules
    rules = list_rules(username, include_shared=True)
    return JSONResponse({"rules": rules})


async def qrule_create(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    from ..quality_rules import create_rule
    result = create_rule(
        rule_name=body.get("rule_name", ""),
        rule_type=body.get("rule_type", ""),
        config=body.get("config", {}),
        owner=username,
        standard_id=body.get("standard_id"),
        severity=body.get("severity", "HIGH"),
        is_shared=body.get("is_shared", False),
    )
    if result.get("status") == "error":
        return JSONResponse({"error": result["message"]}, status_code=400)
    return JSONResponse(result, status_code=201)


async def qrule_detail(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    rule_id = int(request.path_params.get("id", 0))
    from ..quality_rules import get_rule
    rule = get_rule(rule_id, username)
    if not rule:
        return JSONResponse({"error": "Rule not found"}, status_code=404)
    return JSONResponse(rule)


async def qrule_update(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    rule_id = int(request.path_params.get("id", 0))
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    from ..quality_rules import update_rule
    result = update_rule(rule_id, username, **body)
    if result.get("status") == "error":
        return JSONResponse({"error": result["message"]}, status_code=400)
    return JSONResponse({"ok": True})


async def qrule_delete(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    rule_id = int(request.path_params.get("id", 0))
    from ..quality_rules import delete_rule
    result = delete_rule(rule_id, username)
    if result.get("status") == "error":
        return JSONResponse({"error": result["message"]}, status_code=404)
    return JSONResponse({"ok": True})


async def qrule_execute(request: Request):
    """POST /api/quality-rules/execute — execute rules against a file."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    file_path = body.get("file_path", "")
    rule_ids = body.get("rule_ids")
    if not file_path:
        return JSONResponse({"error": "file_path required"}, status_code=400)
    from ..quality_rules import execute_rules_batch
    result = execute_rules_batch(file_path, rule_ids=rule_ids, owner=username)
    return JSONResponse(result)


async def quality_trends(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    asset_name = request.query_params.get("asset_name")
    days = int(request.query_params.get("days", "30"))
    from ..quality_rules import get_trends
    trends = get_trends(asset_name=asset_name, days=days)
    return JSONResponse({"trends": trends})


async def resource_overview(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    from ..quality_rules import get_resource_overview
    result = get_resource_overview()
    return JSONResponse(result)


def get_quality_routes() -> list:
    return [
        Route("/api/quality-rules", qrule_list, methods=["GET"]),
        Route("/api/quality-rules", qrule_create, methods=["POST"]),
        Route("/api/quality-rules/execute", qrule_execute, methods=["POST"]),
        Route("/api/quality-rules/{id:int}", qrule_detail, methods=["GET"]),
        Route("/api/quality-rules/{id:int}", qrule_update, methods=["PUT"]),
        Route("/api/quality-rules/{id:int}", qrule_delete, methods=["DELETE"]),
        Route("/api/quality-trends", quality_trends, methods=["GET"]),
        Route("/api/resource-overview", resource_overview, methods=["GET"]),
    ]
