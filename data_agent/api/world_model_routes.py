"""
World Model API routes — REST endpoints for geospatial world model (Plan D Tech Preview).
"""

import asyncio

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context


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
    ]
