"""Authenticated API for interactive Abu Dhabi EPA SWMM scenarios."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
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
    except Exception as error:
        return JSONResponse({"error": "scenario_start_failed", "detail": str(error)[:500]}, status_code=500)


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


async def get_abu_dhabi_flood_pipeline_status(request: Request) -> JSONResponse:
    """Return the five-stage receipt assembled from derived model outputs."""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        from ..abu_dhabi_flood_scenario_service import pipeline_status_payload

        return JSONResponse(pipeline_status_payload())
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)
    except Exception as error:
        return JSONResponse(
            {"error": "pipeline_status_failed", "detail": str(error)[:500]},
            status_code=500,
        )


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
        from ..abu_dhabi_flood_scenario_service import (
            scenario_map_timeseries_columns_payload,
            scenario_map_timeseries_payload,
        )

        if request.query_params.get("format") == "columns":
            return JSONResponse(scenario_map_timeseries_columns_payload(run_id, time_index))
        return JSONResponse(scenario_map_timeseries_payload(run_id, time_index))
    except KeyError:
        return JSONResponse({"error": "run_not_found"}, status_code=404)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)


async def get_abu_dhabi_dtm_diagnostic_bootstrap(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        from ..abu_dhabi_flood_scenario_service import dtm_diagnostic_bootstrap_payload

        return JSONResponse(dtm_diagnostic_bootstrap_payload())
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)


async def get_abu_dhabi_dtm_diagnostic_timeseries(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    raw_index = request.query_params.get("time_index", "0")
    try:
        time_index = int(raw_index)
    except (TypeError, ValueError):
        return JSONResponse({"error": "time_index_invalid"}, status_code=400)
    try:
        from ..abu_dhabi_flood_scenario_service import dtm_diagnostic_timeseries_payload

        return JSONResponse(dtm_diagnostic_timeseries_payload(time_index))
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)


async def get_abu_dhabi_public_citywide_2d_bootstrap(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        from ..abu_dhabi_flood_scenario_service import public_citywide_2d_bootstrap_payload

        return JSONResponse(public_citywide_2d_bootstrap_payload())
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)


async def get_abu_dhabi_public_citywide_2d_timeseries(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    raw_index = request.query_params.get("time_index", "0")
    try:
        time_index = int(raw_index)
    except (TypeError, ValueError):
        return JSONResponse({"error": "time_index_invalid"}, status_code=400)
    try:
        from ..abu_dhabi_flood_scenario_service import public_citywide_2d_timeseries_payload

        return JSONResponse(public_citywide_2d_timeseries_payload(time_index))
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)


async def get_abu_dhabi_april_2024_event_evidence(request: Request) -> JSONResponse:
    """Serve public, non-spatial evidence for the April 2024 replay tab."""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    from ..uwm.abu_dhabi_flood.event_reconstruction import (
        build_april_2024_event_evidence,
    )

    return JSONResponse(build_april_2024_event_evidence())


async def get_abu_dhabi_hotspot_catalog(request: Request) -> JSONResponse:
    """Serve aggregate metadata from the private Origen-derived bundle."""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        from ..uwm.abu_dhabi_flood.hotspot_inventory import hotspot_catalog_payload

        return JSONResponse(hotspot_catalog_payload())
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)


async def get_abu_dhabi_hotspot_map(request: Request) -> JSONResponse:
    """Serve normalized hotspot points; raw workbook rows are never exposed."""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    inventory = str(request.query_params.get("inventory") or "current")
    try:
        from ..uwm.abu_dhabi_flood.hotspot_inventory import hotspot_geojson_payload

        return JSONResponse(hotspot_geojson_payload(inventory))
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)


async def get_abu_dhabi_phase5_delivery_report(
    request: Request,
) -> HTMLResponse | JSONResponse:
    """Return the printable phase-5 report in the active UI language."""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        from ..abu_dhabi_flood_delivery_report import phase5_report_html
        from ..i18n import get_language

        return HTMLResponse(
            phase5_report_html(get_language()),
            headers={
                "Content-Disposition": (
                    'inline; filename="abu_dhabi_flood_phase5_delivery_report.html"'
                )
            },
        )
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)


async def get_abu_dhabi_gwm_status(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        from ..uwm.abu_dhabi_flood.gwm_surrogate import gwm_store

        return JSONResponse(gwm_store().status())
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)


async def train_abu_dhabi_gwm(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        return JSONResponse({"error": "gwm_train_payload_invalid"}, status_code=400)
    try:
        from ..uwm.abu_dhabi_flood.gwm_surrogate import gwm_store

        return JSONResponse(gwm_store().train(ridge=payload.get("ridge", 1e-4)))
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)
    except Exception as error:
        return JSONResponse({"error": "gwm_train_failed", "detail": str(error)[:500]}, status_code=500)


async def run_abu_dhabi_gwm(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "gwm_rollout_payload_required"}, status_code=400)
    try:
        from ..uwm.abu_dhabi_flood.gwm_surrogate import gwm_store

        return JSONResponse(gwm_store().rollout(payload))
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)
    except Exception as error:
        return JSONResponse({"error": "gwm_rollout_failed", "detail": str(error)[:500]}, status_code=500)


async def get_abu_dhabi_gwm_run(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    run_id = str(request.path_params.get("run_id") or "")
    try:
        from ..uwm.abu_dhabi_flood.gwm_surrogate import gwm_store

        return JSONResponse(gwm_store().get_run(run_id))
    except KeyError:
        return JSONResponse({"error": "gwm_run_not_found"}, status_code=404)


async def get_abu_dhabi_gwm_bootstrap(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    run_id = str(request.path_params.get("run_id") or "")
    try:
        from ..uwm.abu_dhabi_flood.gwm_surrogate import gwm_store

        return JSONResponse(gwm_store().bootstrap(run_id))
    except KeyError:
        return JSONResponse({"error": "gwm_run_not_found"}, status_code=404)


async def get_abu_dhabi_gwm_timeseries(request: Request) -> JSONResponse:
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
        from ..uwm.abu_dhabi_flood.gwm_surrogate import gwm_store

        return JSONResponse(gwm_store().timeseries(run_id, time_index))
    except KeyError:
        return JSONResponse({"error": "gwm_run_not_found"}, status_code=404)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)


def get_abu_dhabi_flood_routes() -> list[Route]:
    return [
        Route("/api/abu-dhabi/flood/scenarios", endpoint=create_abu_dhabi_flood_scenario, methods=["POST"]),
        Route("/api/abu-dhabi/flood/scenarios/latest", endpoint=get_latest_abu_dhabi_flood_scenario, methods=["GET"]),
        Route("/api/abu-dhabi/flood/design-storms/latest", endpoint=get_latest_zone_b_design_storm_batch, methods=["GET"]),
        Route("/api/abu-dhabi/flood/pipeline-status", endpoint=get_abu_dhabi_flood_pipeline_status, methods=["GET"]),
        Route("/api/abu-dhabi/flood/scenarios/{run_id}", endpoint=get_abu_dhabi_flood_scenario, methods=["GET"]),
        Route("/api/abu-dhabi/flood/scenarios/{run_id}/map/bootstrap", endpoint=get_abu_dhabi_flood_scenario_map_bootstrap, methods=["GET"]),
        Route("/api/abu-dhabi/flood/scenarios/{run_id}/map", endpoint=get_abu_dhabi_flood_scenario_map, methods=["GET"]),
        Route("/api/abu-dhabi/flood/scenarios/{run_id}/map/timeseries", endpoint=get_abu_dhabi_flood_scenario_map_timeseries, methods=["GET"]),
        Route("/api/abu-dhabi/flood/dtm-diagnostic/bootstrap", endpoint=get_abu_dhabi_dtm_diagnostic_bootstrap, methods=["GET"]),
        Route("/api/abu-dhabi/flood/dtm-diagnostic/timeseries", endpoint=get_abu_dhabi_dtm_diagnostic_timeseries, methods=["GET"]),
        Route("/api/abu-dhabi/flood/public-citywide-2d/bootstrap", endpoint=get_abu_dhabi_public_citywide_2d_bootstrap, methods=["GET"]),
        Route("/api/abu-dhabi/flood/public-citywide-2d/timeseries", endpoint=get_abu_dhabi_public_citywide_2d_timeseries, methods=["GET"]),
        Route("/api/abu-dhabi/flood/events/april-2024/evidence", endpoint=get_abu_dhabi_april_2024_event_evidence, methods=["GET"]),
        Route("/api/abu-dhabi/flood/hotspots/catalog", endpoint=get_abu_dhabi_hotspot_catalog, methods=["GET"]),
        Route("/api/abu-dhabi/flood/hotspots/map", endpoint=get_abu_dhabi_hotspot_map, methods=["GET"]),
        Route("/api/abu-dhabi/flood/validation/report", endpoint=get_abu_dhabi_phase5_delivery_report, methods=["GET"]),
        Route("/api/abu-dhabi/flood/gwm/status", endpoint=get_abu_dhabi_gwm_status, methods=["GET"]),
        Route("/api/abu-dhabi/flood/gwm/train", endpoint=train_abu_dhabi_gwm, methods=["POST"]),
        Route("/api/abu-dhabi/flood/gwm/rollout", endpoint=run_abu_dhabi_gwm, methods=["POST"]),
        Route("/api/abu-dhabi/flood/gwm/runs/{run_id}", endpoint=get_abu_dhabi_gwm_run, methods=["GET"]),
        Route("/api/abu-dhabi/flood/gwm/runs/{run_id}/map/bootstrap", endpoint=get_abu_dhabi_gwm_bootstrap, methods=["GET"]),
        Route("/api/abu-dhabi/flood/gwm/runs/{run_id}/timeseries", endpoint=get_abu_dhabi_gwm_timeseries, methods=["GET"]),
    ]
