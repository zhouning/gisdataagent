"""Authenticated map publication and vector-tile routes."""

from __future__ import annotations

import asyncio
import os
from uuid import UUID

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..map_publications import (
    MapPublicationForbidden,
    MapPublicationInvalid,
    MapPublicationMaterializationRequired,
    MapPublicationNotFound,
    MapPublicationService,
    MapPublicationUnavailable,
)
from .helpers import _get_user_from_request, _set_user_context


def _service() -> MapPublicationService:
    return MapPublicationService()


def _error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, MapPublicationNotFound):
        return JSONResponse({"error": str(exc)}, status_code=404)
    if isinstance(exc, MapPublicationForbidden):
        return JSONResponse({"error": str(exc)}, status_code=403)
    if isinstance(exc, MapPublicationMaterializationRequired):
        return JSONResponse(
            {
                "error": str(exc),
                "code": "serving_projection_required",
            },
            status_code=409,
        )
    if isinstance(exc, MapPublicationInvalid):
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"error": "Map publication service is unavailable"}, status_code=503)


def _authenticated(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return None, JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    return user, None


async def create_map_publication(request: Request) -> JSONResponse:
    _, error = _authenticated(request)
    if error:
        return error
    try:
        config = await request.json()
    except Exception:
        config = {}
    if not isinstance(config, dict):
        return JSONResponse({"error": "Request body must be an object"}, status_code=400)
    try:
        publication = await asyncio.to_thread(
            _service().publish,
            int(request.path_params["asset_id"]),
            config,
        )
    except (
        MapPublicationForbidden,
        MapPublicationInvalid,
        MapPublicationMaterializationRequired,
        MapPublicationNotFound,
        MapPublicationUnavailable,
    ) as exc:
        return _error_response(exc)
    return JSONResponse(
        {"publication": publication, "layer": publication["layer"]},
        status_code=201,
    )


async def current_map_publication(request: Request) -> JSONResponse:
    user, error = _authenticated(request)
    if error:
        return error
    try:
        publication = await asyncio.to_thread(
            _service().current,
            int(request.path_params["asset_id"]),
        )
    except (MapPublicationNotFound, MapPublicationUnavailable) as exc:
        return _error_response(exc)
    try:
        from ..data_distribution import log_access

        await asyncio.to_thread(
            log_access,
            int(publication["asset_id"]),
            str(user.identifier),
            "map",
        )
    except Exception:
        pass
    return JSONResponse({"publication": publication, "layer": publication["layer"]})


async def map_publication_metadata(request: Request) -> JSONResponse:
    _, error = _authenticated(request)
    if error:
        return error
    try:
        publication = await asyncio.to_thread(
            _service().get,
            request.path_params["publication_id"],
        )
    except (MapPublicationNotFound, MapPublicationUnavailable) as exc:
        return _error_response(exc)
    return JSONResponse({"publication": publication, "layer": publication["layer"]})


async def map_publication_feature(request: Request) -> JSONResponse:
    _, error = _authenticated(request)
    if error:
        return error
    try:
        result = await asyncio.to_thread(
            _service().feature,
            request.path_params["publication_id"],
            str(request.path_params["feature_id"]),
        )
    except (MapPublicationNotFound, MapPublicationUnavailable) as exc:
        return _error_response(exc)
    return JSONResponse(result)


async def _fetch_martin_tile(publication_id: UUID, z: int, x: int, y: int) -> httpx.Response:
    martin_url = os.environ.get("MARTIN_URL", "http://martin:3000").rstrip("/")
    url = f"{martin_url}/map_publication/{z}/{x}/{y}"
    async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
        return await client.get(
            url,
            params={"publication_id": str(publication_id)},
            headers={"Accept-Encoding": "identity"},
        )


async def map_publication_tile(request: Request) -> Response:
    _, error = _authenticated(request)
    if error:
        return error
    publication_id = request.path_params["publication_id"]
    z = int(request.path_params["z"])
    x = int(request.path_params["x"])
    y = int(request.path_params["y"])
    if z < 0 or z > 30 or x < 0 or y < 0 or x >= 2**z or y >= 2**z:
        return JSONResponse({"error": "Invalid tile coordinate"}, status_code=400)

    try:
        publication = await asyncio.to_thread(_service().get, publication_id)
    except (MapPublicationNotFound, MapPublicationUnavailable) as exc:
        return _error_response(exc)
    if publication["status"] != "ready":
        return JSONResponse({"error": "Map publication is not ready"}, status_code=409)
    if z < publication["min_zoom"] or z > publication["max_zoom"]:
        return Response(
            b"",
            media_type="application/vnd.mapbox-vector-tile",
            headers={"Cache-Control": "private, max-age=60"},
        )

    try:
        upstream = await _fetch_martin_tile(publication_id, z, x, y)
    except (httpx.HTTPError, OSError):
        return JSONResponse({"error": "Vector tile service is unavailable"}, status_code=503)
    if upstream.status_code != 200:
        return JSONResponse(
            {"error": "Vector tile service rejected the tile"},
            status_code=503 if upstream.status_code >= 500 else upstream.status_code,
        )

    headers = {
        "Cache-Control": "private, max-age=300, stale-while-revalidate=60",
        "Vary": "Cookie, Accept-Encoding",
        "X-Content-Type-Options": "nosniff",
    }
    if upstream.headers.get("etag"):
        headers["ETag"] = upstream.headers["etag"]
    return Response(
        upstream.content,
        media_type="application/vnd.mapbox-vector-tile",
        headers=headers,
    )


def get_map_publication_routes() -> list[Route]:
    return [
        Route(
            "/api/catalog/{asset_id:int}/map-publications",
            create_map_publication,
            methods=["POST"],
        ),
        Route(
            "/api/catalog/{asset_id:int}/map-publications/current",
            current_map_publication,
            methods=["GET"],
        ),
        Route(
            "/api/map-publications/{publication_id:uuid}",
            map_publication_metadata,
            methods=["GET"],
        ),
        Route(
            "/api/map-publications/{publication_id:uuid}/tiles/{z:int}/{x:int}/{y:int}.pbf",
            map_publication_tile,
            methods=["GET"],
        ),
        Route(
            "/api/map-publications/{publication_id:uuid}/features/{feature_id}",
            map_publication_feature,
            methods=["GET"],
        ),
    ]
