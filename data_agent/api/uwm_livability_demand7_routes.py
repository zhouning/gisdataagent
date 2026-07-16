"""API routes for demand-7 UWM livability intervention planning."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context
from ..uwm.livability_demand7.service import Demand7ProductInvalid, Demand7Service


ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
DEFAULT_PANEL = DATA_ROOT / "admin_livability_target_full_admin_graph_2024_07_2026_07_08/uwm_admin_livability_target_full_admin_graph_panel.json"
DEFAULT_PLANNER = DATA_ROOT / "data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json"
DEFAULT_GEOMETRY = DATA_ROOT / "admin_units/chongqing_township_admin_units.geojson"
_SERVICE_CACHE: tuple[Path, Path, Path, Demand7Service] | None = None


def _path(name: str, default: Path) -> Path:
    configured = os.environ.get(name, "").strip()
    return Path(configured).expanduser() if configured else default


def _service() -> Demand7Service:
    global _SERVICE_CACHE
    paths = (
        _path("UWM_LIVABILITY_DEMAND7_PANEL_PATH", DEFAULT_PANEL),
        _path("UWM_LIVABILITY_DEMAND7_PLANNER_PATH", DEFAULT_PLANNER),
        _path("UWM_LIVABILITY_DEMAND7_GEOMETRY_PATH", DEFAULT_GEOMETRY),
    )
    if _SERVICE_CACHE is None or _SERVICE_CACHE[:3] != paths:
        _SERVICE_CACHE = (*paths, Demand7Service(*paths))
    return _SERVICE_CACHE[3]


def _reset_service_cache() -> None:
    global _SERVICE_CACHE
    _SERVICE_CACHE = None


def _authorized(request: Request) -> JSONResponse | None:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    return None


def _unavailable(error: Exception) -> JSONResponse:
    return JSONResponse(
        {
            "schema": "uwm.livability.demand7.unavailable.v1",
            "ready": False,
            "blockers": [str(error)],
            "claim_boundary": "fail_closed",
        },
        status_code=503,
    )


async def demand7_overview(request: Request):
    if unauthorized := _authorized(request):
        return unauthorized
    try:
        return JSONResponse(await asyncio.to_thread(_service().overview))
    except Demand7ProductInvalid as error:
        return _unavailable(error)


async def demand7_units(request: Request):
    if unauthorized := _authorized(request):
        return unauthorized
    try:
        query = request.query_params
        result = await asyncio.to_thread(
            _service().list_units,
            query.get("search", ""),
            query.get("county", ""),
            int(query.get("limit", "100")),
        )
        return JSONResponse(result)
    except (Demand7ProductInvalid, ValueError) as error:
        return _unavailable(error) if isinstance(error, Demand7ProductInvalid) else JSONResponse({"error": str(error)}, status_code=400)


async def demand7_unit(request: Request):
    if unauthorized := _authorized(request):
        return unauthorized
    try:
        return JSONResponse(await asyncio.to_thread(_service().unit_detail, str(request.path_params.get("unit_id") or "")))
    except Demand7ProductInvalid as error:
        return _unavailable(error)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=404)


async def demand7_plan(request: Request):
    if unauthorized := _authorized(request):
        return unauthorized
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON payload"}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"error": "Request object required"}, status_code=400)
    try:
        result = await asyncio.to_thread(
            _service().plan,
            str(payload.get("unit_id") or ""),
            str(payload.get("target_profile") or "balanced"),
            str(payload.get("horizon") or "simulator_step"),
        )
        return JSONResponse(result)
    except Demand7ProductInvalid as error:
        return _unavailable(error)
    except ValueError as error:
        status = 404 if str(error) == "unit_not_found" else 400
        return JSONResponse({"error": str(error)}, status_code=status)


def get_uwm_livability_demand7_routes() -> list:
    return [
        Route("/api/uwm/livability/demand7/overview", demand7_overview, methods=["GET"]),
        Route("/api/uwm/livability/demand7/units", demand7_units, methods=["GET"]),
        Route("/api/uwm/livability/demand7/units/{unit_id}", demand7_unit, methods=["GET"]),
        Route("/api/uwm/livability/demand7/plan", demand7_plan, methods=["POST"]),
    ]
