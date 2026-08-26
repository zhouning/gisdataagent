"""Authenticated API for interactive Abu Dhabi EPA SWMM scenarios."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context


async def create_abu_dhabi_flood_scenario(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "scenario_json_required"}, status_code=400)
    try:
        from ..abu_dhabi_flood_scenario_service import start_scenario

        return JSONResponse(start_scenario(payload), status_code=202)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    except Exception:
        return JSONResponse({"error": "scenario_start_failed"}, status_code=500)


async def get_abu_dhabi_flood_scenario(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    run_id = str(request.path_params.get("run_id") or "")
    try:
        from ..abu_dhabi_flood_scenario_service import public_run

        return JSONResponse(public_run(run_id))
    except KeyError:
        return JSONResponse({"error": "run_not_found"}, status_code=404)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)


async def get_latest_abu_dhabi_flood_scenario(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        from ..abu_dhabi_flood_scenario_service import latest_completed_run

        return JSONResponse(latest_completed_run())
    except KeyError:
        return JSONResponse({"error": "run_not_found"}, status_code=404)


async def get_latest_zone_b_design_storm_batch(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        from ..abu_dhabi_flood_scenario_service import latest_zone_b_design_storm_batch

        return JSONResponse(latest_zone_b_design_storm_batch())
    except KeyError:
        return JSONResponse({"error": "design_storm_batch_not_found"}, status_code=404)


async def get_abu_dhabi_flood_scenario_map(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    run_id = str(request.path_params.get("run_id") or "")
    try:
        from ..abu_dhabi_flood_scenario_service import scenario_map_payload

        return JSONResponse(scenario_map_payload(run_id))
    except KeyError:
        return JSONResponse({"error": "run_not_found"}, status_code=404)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)


async def get_abu_dhabi_flood_scenario_map_bootstrap(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    run_id = str(request.path_params.get("run_id") or "")
    try:
        from ..abu_dhabi_flood_scenario_service import scenario_map_bootstrap_payload

        return JSONResponse(scenario_map_bootstrap_payload(run_id))
    except KeyError:
        return JSONResponse({"error": "run_not_found"}, status_code=404)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)


async def get_abu_dhabi_flood_scenario_map_timeseries(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    run_id = str(request.path_params.get("run_id") or "")
    raw_index = request.query_params.get("time_index", "0")
    try:
        time_index = int(raw_index)
    except (TypeError, ValueError):
        return JSONResponse({"error": "time_index_invalid"}, status_code=400)
    try:
        from ..abu_dhabi_flood_scenario_service import scenario_map_timeseries_payload

        return JSONResponse(scenario_map_timeseries_payload(run_id, time_index))
    except KeyError:
        return JSONResponse({"error": "run_not_found"}, status_code=404)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)


def get_abu_dhabi_flood_routes() -> list[Route]:
    return [
        Route("/api/abu-dhabi/flood/scenarios", endpoint=create_abu_dhabi_flood_scenario, methods=["POST"]),
        Route("/api/abu-dhabi/flood/scenarios/latest", endpoint=get_latest_abu_dhabi_flood_scenario, methods=["GET"]),
        Route("/api/abu-dhabi/flood/design-storms/latest", endpoint=get_latest_zone_b_design_storm_batch, methods=["GET"]),
        Route("/api/abu-dhabi/flood/scenarios/{run_id}", endpoint=get_abu_dhabi_flood_scenario, methods=["GET"]),
        Route("/api/abu-dhabi/flood/scenarios/{run_id}/map/bootstrap", endpoint=get_abu_dhabi_flood_scenario_map_bootstrap, methods=["GET"]),
        Route("/api/abu-dhabi/flood/scenarios/{run_id}/map", endpoint=get_abu_dhabi_flood_scenario_map, methods=["GET"]),
        Route("/api/abu-dhabi/flood/scenarios/{run_id}/map/timeseries", endpoint=get_abu_dhabi_flood_scenario_map_timeseries, methods=["GET"]),
    ]
