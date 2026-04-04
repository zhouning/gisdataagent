"""
Tile Routes — REST API for vector tile (MVT) serving.

Endpoints:
- GET /api/tiles/{layer_id}/{z}/{x}/{y}.pbf         — serve a single MVT tile
- GET /api/tiles/{layer_id}/metadata.json            — TileJSON metadata
- DELETE /api/tiles/{layer_id}                       — cleanup tile layer
- GET /api/tiles/martin/{table}/{z}/{x}/{y}.pbf      — Martin proxy (Phase 3)
"""
import os

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context
from ..observability import get_logger

logger = get_logger("tile_routes")

# Martin tile server URL (optional, Phase 3)
MARTIN_URL = os.environ.get("MARTIN_URL", "")


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
        headers={
            "Cache-Control": "public, max-age=3600",
            "Access-Control-Allow-Origin": "*",
        },
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
        "vector_layers": [{
            "id": meta["layer_name"] or "default",
            "fields": {c: "String" for c in meta.get("columns", [])},
        }],
        "feature_count": meta["feature_count"],
    }
    return JSONResponse(tilejson)


async def _api_tile_delete(request: Request):
    """DELETE /api/tiles/{layer_id} — cleanup tile layer and PostGIS table."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)

    layer_id = request.path_params["layer_id"]

    from ..tile_server import get_layer_metadata, cleanup_tile_layer

    meta = get_layer_metadata(layer_id)
    if not meta:
        return JSONResponse({"error": "Layer not found"}, status_code=404)
    if meta["owner_username"] != username:
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    cleanup_tile_layer(layer_id)
    return JSONResponse({"status": "deleted", "layer_id": layer_id})


async def _api_martin_tile(request: Request):
    """GET /api/tiles/martin/{table}/{z}/{x}/{y}.pbf — proxy to Martin tile server."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    if not MARTIN_URL:
        return JSONResponse({"error": "Martin tile server not configured"}, status_code=503)

    table = request.path_params["table"]
    z = int(request.path_params["z"])
    x = int(request.path_params["x"])
    y = int(request.path_params["y"])

    # Sanitize table name
    if not table.replace("_", "").isalnum():
        return JSONResponse({"error": "Invalid table name"}, status_code=400)

    try:
        import httpx
        martin_url = f"{MARTIN_URL}/{table}/{z}/{x}/{y}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(martin_url)

        if resp.status_code == 204 or not resp.content:
            return Response(status_code=204)
        if resp.status_code != 200:
            return Response(status_code=resp.status_code)

        return Response(
            content=resp.content,
            media_type="application/vnd.mapbox-vector-tile",
            headers={
                "Cache-Control": "public, max-age=3600",
                "Access-Control-Allow-Origin": "*",
            },
        )
    except Exception as e:
        logger.warning("[MartinProxy] Failed: %s", e)
        return JSONResponse({"error": "Martin proxy failed"}, status_code=502)


async def _api_martin_catalog(request: Request):
    """GET /api/tiles/martin/catalog — list available Martin tile sources."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    if not MARTIN_URL:
        return JSONResponse({"error": "Martin not configured", "sources": []})

    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{MARTIN_URL}/catalog")
        if resp.status_code == 200:
            return JSONResponse(resp.json())
        return JSONResponse({"sources": []})
    except Exception:
        return JSONResponse({"sources": []})


def get_tile_routes() -> list:
    """Export tile serving routes for registration in frontend_api.py."""
    return [
        Route("/api/tiles/martin/catalog",
              endpoint=_api_martin_catalog, methods=["GET"]),
        Route("/api/tiles/martin/{table}/{z:int}/{x:int}/{y:int}.pbf",
              endpoint=_api_martin_tile, methods=["GET"]),
        Route("/api/tiles/{layer_id}/{z:int}/{x:int}/{y:int}.pbf",
              endpoint=_api_tile, methods=["GET"]),
        Route("/api/tiles/{layer_id}/metadata.json",
              endpoint=_api_tile_metadata, methods=["GET"]),
        Route("/api/tiles/{layer_id}",
              endpoint=_api_tile_delete, methods=["DELETE"]),
    ]
