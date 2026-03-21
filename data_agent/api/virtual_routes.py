"""Virtual Data Sources CRUD + health-check routes (v13.0)."""

import logging
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context

logger = logging.getLogger("data_agent.api.virtual_routes")


async def vsource_list(request: Request):
    """GET /api/virtual-sources — list virtual sources visible to current user."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    from ..virtual_sources import list_virtual_sources
    sources = list_virtual_sources(username, include_shared=True)
    return JSONResponse({"sources": sources})


async def vsource_create(request: Request):
    """POST /api/virtual-sources — register a new virtual data source."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    from ..virtual_sources import create_virtual_source, VALID_SOURCE_TYPES
    stype = body.get("source_type", "")
    if stype not in VALID_SOURCE_TYPES:
        return JSONResponse({"error": f"source_type must be one of {sorted(VALID_SOURCE_TYPES)}"}, status_code=400)

    result = create_virtual_source(
        source_name=body.get("source_name", ""),
        source_type=stype,
        endpoint_url=body.get("endpoint_url", ""),
        owner_username=username,
        auth_config=body.get("auth_config"),
        query_config=body.get("query_config"),
        schema_mapping=body.get("schema_mapping"),
        default_crs=body.get("default_crs", "EPSG:4326"),
        spatial_extent=body.get("spatial_extent"),
        refresh_policy=body.get("refresh_policy", "on_demand"),
        is_shared=body.get("is_shared", False),
    )
    if result.get("status") == "error":
        return JSONResponse({"error": result["message"]}, status_code=400)
    return JSONResponse(result, status_code=201)


async def vsource_detail(request: Request):
    """GET /api/virtual-sources/{id} — get virtual source detail."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    source_id = int(request.path_params.get("id", 0))
    from ..virtual_sources import get_virtual_source
    source = get_virtual_source(source_id, username)
    if not source:
        return JSONResponse({"error": "Source not found"}, status_code=404)
    # Redact auth_config secrets in response
    if source.get("auth_config"):
        auth = source["auth_config"]
        if auth.get("token"):
            auth["token"] = "***"
        if auth.get("password"):
            auth["password"] = "***"
        if auth.get("key"):
            auth["key"] = "***"
    return JSONResponse(source)


async def vsource_update(request: Request):
    """PUT /api/virtual-sources/{id} — update a virtual source."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    source_id = int(request.path_params.get("id", 0))
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    from ..virtual_sources import update_virtual_source
    result = update_virtual_source(source_id, username, **body)
    if result.get("status") == "error":
        code = 404 if "not found" in result.get("message", "").lower() else 400
        return JSONResponse({"error": result["message"]}, status_code=code)
    return JSONResponse({"ok": True})


async def vsource_delete(request: Request):
    """DELETE /api/virtual-sources/{id} — delete a virtual source."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    source_id = int(request.path_params.get("id", 0))
    from ..virtual_sources import delete_virtual_source
    result = delete_virtual_source(source_id, username)
    if result.get("status") == "error":
        return JSONResponse({"error": result["message"]}, status_code=404)
    return JSONResponse({"ok": True})


async def vsource_test(request: Request):
    """POST /api/virtual-sources/{id}/test — test connectivity to a virtual source."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    source_id = int(request.path_params.get("id", 0))
    from ..virtual_sources import check_source_health
    result = await check_source_health(source_id, username)
    if result.get("status") == "error":
        return JSONResponse({"error": result["message"]}, status_code=404)
    return JSONResponse(result)


async def vsource_discover(request: Request):
    """POST /api/virtual-sources/discover — discover layers/collections from a remote service."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    source_type = body.get("source_type", "")
    endpoint_url = body.get("endpoint_url", "")
    auth_config = body.get("auth_config") or {}

    if not source_type or not endpoint_url:
        return JSONResponse({"error": "source_type and endpoint_url required"}, status_code=400)

    from ..connectors import ConnectorRegistry
    connector = ConnectorRegistry.get(source_type)
    if not connector:
        return JSONResponse({"error": f"Unknown source type: {source_type}"}, status_code=400)

    try:
        caps = await connector.get_capabilities(endpoint_url, auth_config)
        return JSONResponse(caps)
    except Exception as e:
        logger.warning("Discover failed for %s %s: %s", source_type, endpoint_url, e)
        return JSONResponse({"error": str(e)[:300]}, status_code=502)


def get_virtual_source_routes() -> list:
    """Return Route objects for virtual source endpoints."""
    return [
        Route("/api/virtual-sources", vsource_list, methods=["GET"]),
        Route("/api/virtual-sources", vsource_create, methods=["POST"]),
        Route("/api/virtual-sources/discover", vsource_discover, methods=["POST"]),
        Route("/api/virtual-sources/{id:int}", vsource_detail, methods=["GET"]),
        Route("/api/virtual-sources/{id:int}", vsource_update, methods=["PUT"]),
        Route("/api/virtual-sources/{id:int}", vsource_delete, methods=["DELETE"]),
        Route("/api/virtual-sources/{id:int}/test", vsource_test, methods=["POST"]),
    ]
