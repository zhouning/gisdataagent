"""
Skill Bundles API routes — CRUD for user-defined toolset+skill combinations.

Extracted from frontend_api.py (S-4 refactoring).
"""
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context


async def bundles_list(request: Request):
    """GET /api/bundles — list user's bundles + shared."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    from ..custom_skill_bundles import list_skill_bundles
    bundles = list_skill_bundles()
    return JSONResponse({"bundles": bundles, "count": len(bundles)})


async def bundles_create(request: Request):
    """POST /api/bundles — create a new skill bundle."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    bundle_name = (body.get("bundle_name") or "").strip()
    if not bundle_name:
        return JSONResponse({"error": "bundle_name required"}, status_code=400)

    from ..custom_skill_bundles import create_skill_bundle, validate_bundle_name
    err = validate_bundle_name(bundle_name)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    bundle_id = create_skill_bundle(
        bundle_name=bundle_name,
        description=body.get("description", ""),
        toolset_names=body.get("toolset_names", []),
        skill_names=body.get("skill_names", []),
        intent_triggers=body.get("intent_triggers", []),
        is_shared=body.get("is_shared", False),
    )
    if bundle_id is None:
        return JSONResponse({"error": "Failed to create bundle"}, status_code=400)

    return JSONResponse({"id": bundle_id, "bundle_name": bundle_name}, status_code=201)


async def bundles_detail(request: Request):
    """GET /api/bundles/{id} — get bundle detail."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    bundle_id = int(request.path_params.get("id", 0))
    from ..custom_skill_bundles import get_skill_bundle
    bundle = get_skill_bundle(bundle_id)
    if not bundle:
        return JSONResponse({"error": "Bundle not found"}, status_code=404)
    return JSONResponse(bundle)


async def bundles_update(request: Request):
    """PUT /api/bundles/{id} — update a bundle (owner only)."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    bundle_id = int(request.path_params.get("id", 0))
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    from ..custom_skill_bundles import update_skill_bundle
    ok = update_skill_bundle(bundle_id, **body)
    if not ok:
        return JSONResponse({"error": "Failed to update bundle"}, status_code=400)
    return JSONResponse({"status": "ok"})


async def bundles_delete(request: Request):
    """DELETE /api/bundles/{id} — delete a bundle (owner only)."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    bundle_id = int(request.path_params.get("id", 0))
    from ..custom_skill_bundles import delete_skill_bundle
    ok = delete_skill_bundle(bundle_id)
    if not ok:
        return JSONResponse({"error": "Failed to delete bundle"}, status_code=404)
    return JSONResponse({"status": "ok"})


async def bundles_available_tools(request: Request):
    """GET /api/bundles/available-tools — list toolset names + skill names for composition."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    from ..custom_skill_bundles import get_available_tools
    return JSONResponse(get_available_tools())


def get_bundle_routes() -> list:
    """Return Starlette routes for Skill Bundles API."""
    return [
        Route("/api/bundles", endpoint=bundles_list, methods=["GET"]),
        Route("/api/bundles", endpoint=bundles_create, methods=["POST"]),
        Route("/api/bundles/available-tools", endpoint=bundles_available_tools, methods=["GET"]),
        Route("/api/bundles/{id:int}", endpoint=bundles_detail, methods=["GET"]),
        Route("/api/bundles/{id:int}", endpoint=bundles_update, methods=["PUT"]),
        Route("/api/bundles/{id:int}", endpoint=bundles_delete, methods=["DELETE"]),
    ]
