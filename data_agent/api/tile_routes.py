"""Private user-layer tiles and retired legacy Martin endpoint shims.

The user-layer endpoints serve short-lived, owner-scoped work products.  They
are distinct from governed GIS service tiles, which are only served by the
release-bound Platform Gateway route.  The former generic Martin table proxy is
kept only long enough to return a stable retirement response; it never reaches
the provider.
"""

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context

_PRIVATE_TILE_HEADERS = {
    "Cache-Control": "private, no-store",
    "Pragma": "no-cache",
    "Vary": "Authorization, Cookie, Accept-Encoding",
    "X-Content-Type-Options": "nosniff",
}
_RETIRED_MARTIN_PROXY = {
    "error": "Legacy Martin table proxy is retired",
    "code": "legacy_martin_proxy_retired",
    "replacement": "/api/platform/v1/gis/tiles/{release_key}/{z}/{x}/{y}.pbf",
}


async def _api_tile(request: Request):
    """GET /api/tiles/{layer_id}/{z}/{x}/{y}.pbf — serve MVT tile."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)

    layer_id = request.path_params["layer_id"]
    z = int(request.path_params["z"])
    x = int(request.path_params["x"])
    y = int(request.path_params["y"])

    from ..tile_server import generate_tile, get_layer_metadata

    # Verify ownership
    meta = get_layer_metadata(layer_id)
    if not meta:
        return JSONResponse({"error": "Layer not found"}, status_code=404)
    if meta["owner_username"] != username:
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    tile_bytes = generate_tile(layer_id, z, x, y)
    if not tile_bytes:
        return Response(status_code=204)

    return Response(
        content=tile_bytes,
        media_type="application/vnd.mapbox-vector-tile",
        headers=_PRIVATE_TILE_HEADERS,
    )


async def _api_tile_metadata(request: Request):
    """GET /api/tiles/{layer_id}/metadata.json — TileJSON metadata."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)

    layer_id = request.path_params["layer_id"]

    from ..tile_server import get_layer_metadata

    meta = get_layer_metadata(layer_id)
    if not meta:
        return JSONResponse({"error": "Layer not found"}, status_code=404)
    if meta["owner_username"] != username:
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    tilejson = {
        "tilejson": "3.0.0",
        "name": meta["layer_name"],
        "tiles": [f"/api/tiles/{layer_id}/{{z}}/{{x}}/{{y}}.pbf"],
        "minzoom": 0,
        "maxzoom": 16,
        "bounds": meta["bounds"],
        "center": [
            (meta["bounds"][0] + meta["bounds"][2]) / 2,
            (meta["bounds"][1] + meta["bounds"][3]) / 2,
            10,
        ],
        "vector_layers": [
            {
                "id": meta["layer_name"] or "default",
                "fields": {c: "String" for c in meta.get("columns", [])},
            }
        ],
        "feature_count": meta["feature_count"],
    }
    return JSONResponse(tilejson, headers=_PRIVATE_TILE_HEADERS)


async def _api_tile_delete(request: Request):
    """DELETE /api/tiles/{layer_id} — cleanup tile layer and PostGIS table."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)

    layer_id = request.path_params["layer_id"]

    from ..tile_server import cleanup_tile_layer, get_layer_metadata

    meta = get_layer_metadata(layer_id)
    if not meta:
        return JSONResponse({"error": "Layer not found"}, status_code=404)
    if meta["owner_username"] != username:
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    cleanup_tile_layer(layer_id)
    return JSONResponse(
        {"status": "deleted", "layer_id": layer_id},
        headers=_PRIVATE_TILE_HEADERS,
    )


async def _api_martin_tile(request: Request):
    """Return a stable retirement response for the unsafe generic proxy."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return JSONResponse(
        _RETIRED_MARTIN_PROXY,
        status_code=410,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


async def _api_martin_catalog(request: Request):
    """Return a stable retirement response for the provider catalog endpoint."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return JSONResponse(
        _RETIRED_MARTIN_PROXY,
        status_code=410,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def get_tile_routes() -> list:
    """Export tile serving routes for registration in frontend_api.py."""
    return [
        Route("/api/tiles/martin/catalog", endpoint=_api_martin_catalog, methods=["GET"]),
        Route(
            "/api/tiles/martin/{table}/{z:int}/{x:int}/{y:int}.pbf",
            endpoint=_api_martin_tile,
            methods=["GET"],
        ),
        Route(
            "/api/tiles/{layer_id}/{z:int}/{x:int}/{y:int}.pbf", endpoint=_api_tile, methods=["GET"]
        ),
        Route("/api/tiles/{layer_id}/metadata.json", endpoint=_api_tile_metadata, methods=["GET"]),
        Route("/api/tiles/{layer_id}", endpoint=_api_tile_delete, methods=["DELETE"]),
    ]
