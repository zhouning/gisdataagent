"""Workspace navigation discovery and administrator policy routes."""

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _require_admin, _set_user_context
from ..navigation_registry import (
    get_admin_navigation,
    get_effective_navigation,
    save_navigation_policies,
)
from ..user_context import current_tenant_id


async def _workspace_navigation(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _username, role = _set_user_context(user)
    return JSONResponse(get_effective_navigation(role, current_tenant_id.get()))


async def _admin_navigation_get(request: Request):
    _user, _username, _role, error = _require_admin(request)
    if error:
        return error
    return JSONResponse(get_admin_navigation())


async def _admin_navigation_put(request: Request):
    _user, username, _role, error = _require_admin(request)
    if error:
        return error
    try:
        body = await request.json()
        if not isinstance(body, dict):
            return JSONResponse({"error": "request body must be an object"}, status_code=400)
        changes = body.get("items")
        if not isinstance(changes, list):
            return JSONResponse({"error": "items must be a list"}, status_code=400)
        result = save_navigation_policies(changes, username)
        return JSONResponse(result)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)


def get_navigation_routes() -> list[Route]:
    return [
        Route("/api/workspace/navigation", _workspace_navigation, methods=["GET"]),
        Route("/api/admin/navigation", _admin_navigation_get, methods=["GET"]),
        Route("/api/admin/navigation", _admin_navigation_put, methods=["PUT"]),
    ]
