"""Cross-system lineage REST API routes (v21.0)."""
from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request


async def _api_add_lineage(request: Request):
    """POST /api/catalog/{id}/lineage — add a lineage edge."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    asset_id = int(request.path_params["id"])
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    from ..data_catalog import add_lineage_edge

    # Determine source/target based on direction
    direction = body.get("direction", "upstream")  # upstream = this asset derives from source
    target_asset_id = body.get("target_asset_id")
    target_external = None
    if body.get("target_external_system"):
        target_external = (body["target_external_system"], body.get("target_external_id", ""))

    if direction == "upstream":
        edge_id = add_lineage_edge(
            source_asset_id=target_asset_id,
            target_asset_id=asset_id,
            source_external=target_external,
            relationship=body.get("relationship", "derives_from"),
            tool_name=body.get("tool_name", ""),
            created_by=user.get("username", ""),
        )
    else:
        edge_id = add_lineage_edge(
            source_asset_id=asset_id,
            target_asset_id=target_asset_id,
            target_external=target_external,
            relationship=body.get("relationship", "feeds_into"),
            tool_name=body.get("tool_name", ""),
            created_by=user.get("username", ""),
        )

    if edge_id is None:
        return JSONResponse({"error": "failed to add"}, status_code=500)
    return JSONResponse({"id": edge_id, "status": "created"})


async def _api_cross_system_lineage(request: Request):
    """GET /api/catalog/{id}/cross-system-lineage — full lineage graph."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    asset_id = int(request.path_params["id"])
    depth = int(request.query_params.get("depth", "5"))

    from ..data_catalog import get_cross_system_lineage

    result = get_cross_system_lineage(asset_id, depth=depth)
    return JSONResponse(result)


async def _api_register_external_asset(request: Request):
    """POST /api/external-assets — register an external system asset."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    system = body.get("system", "")
    external_id = body.get("external_id", "")
    name = body.get("name", "")
    if not system or not name:
        return JSONResponse({"error": "system and name required"}, status_code=400)

    from ..data_catalog import register_external_asset

    asset_id = register_external_asset(
        system=system,
        external_id=external_id,
        name=name,
        url=body.get("url", ""),
        description=body.get("description", ""),
        external_metadata=body.get("metadata"),
        owner=user.get("username", ""),
    )
    if asset_id is None:
        return JSONResponse({"error": "failed to register"}, status_code=500)
    return JSONResponse({"id": asset_id, "status": "registered"})


async def _api_list_external_systems(request: Request):
    """GET /api/external-systems — list registered external systems."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    from ..data_catalog import list_external_systems

    return JSONResponse(list_external_systems())


async def _api_delete_lineage(request: Request):
    """DELETE /api/lineage/{id} — delete a lineage edge."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    edge_id = int(request.path_params["id"])

    from ..data_catalog import delete_lineage_edge

    ok = delete_lineage_edge(edge_id)
    if not ok:
        return JSONResponse({"error": "delete failed"}, status_code=500)
    return JSONResponse({"status": "deleted"})


def get_lineage_routes() -> list[Route]:
    return [
        Route("/api/catalog/{id:int}/lineage", endpoint=_api_add_lineage, methods=["POST"]),
        Route("/api/catalog/{id:int}/cross-system-lineage", endpoint=_api_cross_system_lineage, methods=["GET"]),
        Route("/api/external-assets", endpoint=_api_register_external_asset, methods=["POST"]),
        Route("/api/external-systems", endpoint=_api_list_external_systems, methods=["GET"]),
        Route("/api/lineage/{id:int}", endpoint=_api_delete_lineage, methods=["DELETE"]),
    ]
