"""
World Model API routes — REST endpoints for geospatial world model (Plan D Tech Preview).
"""

import asyncio
import json
import os

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context


# LULC color scheme for map styling
_LULC_COLORS = {
    "水体": "#4169E1", "树木": "#228B22", "草地": "#90EE90", "灌木": "#DEB887",
    "耕地": "#FFD700", "建设用地": "#DC143C", "裸地": "#D2B48C", "湿地": "#20B2AA",
}


# ====================================================================
#  Handlers
# ====================================================================


async def wm_status(request: Request):
    """GET /api/world-model/status — model readiness info."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    from ..world_model import get_model_info

    try:
        info = get_model_info()
        return JSONResponse(info)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def wm_scenarios(request: Request):
    """GET /api/world-model/scenarios — list simulation scenarios."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    from ..world_model import list_scenarios

    scenarios = list_scenarios()
    return JSONResponse({"scenarios": scenarios})


async def wm_predict(request: Request):
    """POST /api/world-model/predict — run world model prediction."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    bbox = body.get("bbox")
    scenario = body.get("scenario", "baseline")
    start_year = body.get("start_year", 2023)
    n_years = body.get("n_years", 5)

    if not bbox or not isinstance(bbox, list) or len(bbox) != 4:
        return JSONResponse(
            {"error": "bbox is required as [minx, miny, maxx, maxy]"},
            status_code=400,
        )

    try:
        start_year = int(start_year)
        n_years = int(n_years)
    except (ValueError, TypeError):
        return JSONResponse(
            {"error": "start_year and n_years must be integers"},
            status_code=400,
        )

    if n_years < 1 or n_years > 50:
        return JSONResponse(
            {"error": "n_years must be between 1 and 50"}, status_code=400
        )

    from ..world_model import predict_sequence

    try:
        result = await asyncio.to_thread(
            predict_sequence, bbox, scenario, start_year, n_years
        )
        if result.get("status") == "error":
            return JSONResponse(result, status_code=503)

        # --- Push GeoJSON layers to map panel ---
        geojson_layers = result.get("geojson_layers", {})
        if geojson_layers:
            try:
                from ..user_context import current_user_id
                from ..frontend_api import pending_map_updates, _pending_lock

                uid = current_user_id.get("admin")
                upload_dir = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)),
                    "uploads", uid,
                )
                os.makedirs(upload_dir, exist_ok=True)

                map_layers = []
                # Use the last predicted year for the primary map layer
                years_sorted = sorted(geojson_layers.keys())
                last_year = years_sorted[-1] if years_sorted else None
                first_year = years_sorted[0] if years_sorted else None

                for yr_key in years_sorted:
                    geojson_data = geojson_layers[yr_key]
                    fname = f"wm_lulc_{yr_key}.geojson"
                    fpath = os.path.join(upload_dir, fname)
                    with open(fpath, "w", encoding="utf-8") as f:
                        json.dump(geojson_data, f, ensure_ascii=False)

                    # Build categorized layer with LULC colors
                    is_last = (yr_key == last_year)
                    style_map = {}
                    for feat in geojson_data.get("features", []):
                        cls_name = feat.get("properties", {}).get("class_name", "")
                        color = feat.get("properties", {}).get("color", "#808080")
                        style_map[cls_name] = {
                            "fillColor": color, "color": color,
                            "fillOpacity": 0.7, "weight": 0.3,
                        }
                    map_layers.append({
                        "name": f"LULC {yr_key} ({scenario})",
                        "type": "categorized",
                        "geojson": fname,
                        "category_column": "class_name",
                        "style_map": style_map,
                        "visible": is_last,  # only show last year by default
                    })

                # Compute map center from bbox
                center_lat = (bbox[1] + bbox[3]) / 2
                center_lng = (bbox[0] + bbox[2]) / 2
                map_config = {
                    "layers": map_layers,
                    "center": [center_lat, center_lng],
                    "zoom": 14,
                }
                with _pending_lock:
                    pending_map_updates[uid] = map_config
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    "Failed to push map update: %s", e
                )

        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def wm_history(request: Request):
    """GET /api/world-model/history — past predictions (placeholder for v1)."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    return JSONResponse({"predictions": []})


async def wm_embedding_coverage(request: Request):
    """GET /api/world-model/embeddings/coverage — cached embedding coverage summary."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    from ..embedding_store import get_coverage
    return JSONResponse(get_coverage())


async def wm_embedding_search(request: Request):
    """POST /api/world-model/embeddings/search — similarity search in embedding space."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    import numpy as np
    embedding = body.get("embedding")
    k = body.get("k", 10)
    radius_km = body.get("radius_km")
    center = body.get("center")  # [lng, lat]

    if not embedding or len(embedding) != 64:
        return JSONResponse({"error": "embedding must be a 64-dim array"}, status_code=400)

    from ..embedding_store import find_similar_embeddings
    results = find_similar_embeddings(
        target_embedding=np.array(embedding, dtype=np.float32),
        k=k,
        spatial_radius_km=radius_km,
        center_point=tuple(center) if center else None,
    )
    return JSONResponse({"results": results, "count": len(results)})


async def wm_embedding_import(request: Request):
    """POST /api/world-model/embeddings/import — import .npy cache into pgvector."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    from ..embedding_store import import_npy_cache
    result = await asyncio.to_thread(import_npy_cache)
    return JSONResponse(result)


# ====================================================================
#  Route factory
# ====================================================================


def get_world_model_routes() -> list:
    """Return Route objects for world model endpoints."""
    return [
        Route("/api/world-model/status", wm_status, methods=["GET"]),
        Route("/api/world-model/scenarios", wm_scenarios, methods=["GET"]),
        Route("/api/world-model/predict", wm_predict, methods=["POST"]),
        Route("/api/world-model/history", wm_history, methods=["GET"]),
        Route("/api/world-model/embeddings/coverage", wm_embedding_coverage, methods=["GET"]),
        Route("/api/world-model/embeddings/search", wm_embedding_search, methods=["POST"]),
        Route("/api/world-model/embeddings/import", wm_embedding_import, methods=["POST"]),
    ]
