"""Authenticated map publication and vector-tile routes."""

from __future__ import annotations

import asyncio
import os
from uuid import UUID

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..governed_query_result_access_security import (
    GOVERNED_QUERY_RESULT_ACCESS_SECURITY_PURPOSE,
)
from ..governed_query_result_delivery import (
    GovernedQueryResultDeliveryForbidden,
    GovernedQueryResultDeliveryService,
    GovernedQueryResultDeliveryUnavailable,
)
from ..governed_query_security import (
    GovernedQuerySecurityError,
    resolve_governed_query_security_ports,
)
from ..map_publications import (
    MapPublicationForbidden,
    MapPublicationInvalid,
    MapPublicationMaterializationRequired,
    MapPublicationNotFound,
    MapPublicationService,
    MapPublicationUnavailable,
)
from .helpers import _get_user_from_request, _set_user_context

MAP_FEATURE_RESULT_ACCESS_ACTION = "map.publication.feature.access"
MAP_TILE_RESULT_ACCESS_ACTION = "map.publication.tile.access"


class _MapTileProviderRejected(RuntimeError):
    def __init__(self, status_code: int):
        super().__init__("vector tile provider rejected the request")
        self.status_code = status_code


def _service() -> MapPublicationService:
    return MapPublicationService()


def _result_delivery() -> GovernedQueryResultDeliveryService:
    return GovernedQueryResultDeliveryService()


def _result_identity(user) -> tuple[str, str, str]:
    metadata = user.metadata if isinstance(getattr(user, "metadata", None), dict) else {}
    tenant_id = str(metadata.get("tenant_id") or "local-dev").strip()
    role = str(metadata.get("role") or "analyst").strip()
    return tenant_id, f"human:{user.identifier}", role


def _result_security_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, GovernedQueryResultDeliveryForbidden):
        return JSONResponse(
            {"error": "Map result access was denied by current policy"},
            status_code=403,
        )
    return JSONResponse(
        {"error": "Map result security is unavailable"},
        status_code=503,
    )


def _publication_ref(tenant_id: str, publication_id: UUID | str) -> str:
    return f"gda://{tenant_id}/map_publication/{publication_id}"


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
    user, error = _authenticated(request)
    if error:
        return error
    publication_id = request.path_params["publication_id"]
    feature_id = str(request.path_params["feature_id"])
    try:
        service = _service()
        publication = await asyncio.to_thread(service.get, publication_id)
        tenant_id, actor_subject, role = _result_identity(user)
        if publication.get("tenant_id") not in {None, tenant_id}:
            raise MapPublicationNotFound("Map publication was not found")
        security_ports = resolve_governed_query_security_ports(tenant_id)
        result = await asyncio.to_thread(
            _result_delivery().execute,
            tenant_id=tenant_id,
            actor_subject=actor_subject,
            roles=(role,),
            purpose_code=GOVERNED_QUERY_RESULT_ACCESS_SECURITY_PURPOSE,
            channel="map_result",
            adapter_id="gda.map-publication.feature.v1",
            consumption_mode="map",
            resource_refs=(_publication_ref(tenant_id, publication_id),),
            request_payload={
                "publication_id": str(publication_id),
                "feature_id": feature_id,
            },
            action=MAP_FEATURE_RESULT_ACCESS_ACTION,
            operation=lambda: service.feature(publication_id, feature_id),
            security_reader=None if security_ports is None else security_ports[0],
        )
    except (MapPublicationNotFound, MapPublicationUnavailable) as exc:
        return _error_response(exc)
    except (
        GovernedQueryResultDeliveryForbidden,
        GovernedQueryResultDeliveryUnavailable,
        GovernedQuerySecurityError,
    ) as exc:
        return _result_security_error(exc)
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


def _fetch_martin_tile_result(
    publication_id: UUID,
    z: int,
    x: int,
    y: int,
) -> httpx.Response:
    upstream = asyncio.run(_fetch_martin_tile(publication_id, z, x, y))
    if upstream.status_code != 200:
        raise _MapTileProviderRejected(upstream.status_code)
    return upstream


async def map_publication_tile(request: Request) -> Response:
    user, error = _authenticated(request)
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
        tenant_id, actor_subject, role = _result_identity(user)
        if publication.get("tenant_id") not in {None, tenant_id}:
            raise MapPublicationNotFound("Map publication was not found")
        security_ports = resolve_governed_query_security_ports(tenant_id)
        upstream = await asyncio.to_thread(
            _result_delivery().execute,
            tenant_id=tenant_id,
            actor_subject=actor_subject,
            roles=(role,),
            purpose_code=GOVERNED_QUERY_RESULT_ACCESS_SECURITY_PURPOSE,
            channel="map_result",
            adapter_id="gda.map-publication.tile.v1",
            consumption_mode="map",
            resource_refs=(_publication_ref(tenant_id, publication_id),),
            request_payload={
                "publication_id": str(publication_id),
                "z": z,
                "x": x,
                "y": y,
            },
            action=MAP_TILE_RESULT_ACCESS_ACTION,
            operation=lambda: _fetch_martin_tile_result(publication_id, z, x, y),
            security_reader=None if security_ports is None else security_ports[0],
        )
    except MapPublicationNotFound as exc:
        return _error_response(exc)
    except (
        GovernedQueryResultDeliveryForbidden,
        GovernedQueryResultDeliveryUnavailable,
        GovernedQuerySecurityError,
    ) as exc:
        return _result_security_error(exc)
    except (httpx.HTTPError, OSError):
        return JSONResponse({"error": "Vector tile service is unavailable"}, status_code=503)
    except _MapTileProviderRejected as exc:
        return JSONResponse(
            {"error": "Vector tile service rejected the tile"},
            status_code=503 if exc.status_code >= 500 else exc.status_code,
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
