"""Authenticated catalog asset lifecycle routes."""

from __future__ import annotations

import asyncio

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..asset_lifecycle import AssetLifecycleRepositoryError, get_asset_lifecycle
from .helpers import _get_user_from_request, _set_user_context


async def catalog_asset_lifecycle(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    asset_id = int(request.path_params["asset_id"])
    try:
        lifecycle = await asyncio.to_thread(get_asset_lifecycle, asset_id)
    except AssetLifecycleRepositoryError:
        return JSONResponse(
            {"error": "Asset lifecycle is unavailable"},
            status_code=503,
        )

    if lifecycle is None:
        return JSONResponse({"error": "Asset not found"}, status_code=404)
    return JSONResponse(lifecycle)


def get_catalog_lifecycle_routes() -> list[Route]:
    return [
        Route(
            "/api/catalog/{asset_id:int}/lifecycle",
            catalog_asset_lifecycle,
            methods=["GET"],
        )
    ]
