"""Authenticated API for interactive Abu Dhabi EPA SWMM scenarios."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context


async def get_abu_dhabi_customer_hotspots_bootstrap(request: Request) -> JSONResponse:
    """Serve the validated 506-point static customer hotspot reference layer."""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        from ..abu_dhabi_customer_hotspots_service import customer_hotspots_bootstrap_payload

        return JSONResponse(
            customer_hotspots_bootstrap_payload(),
            headers={"Cache-Control": "private, max-age=300"},
        )
    except FileNotFoundError as error:
        return JSONResponse({"error": "customer_hotspots_not_found", "detail": str(error)}, status_code=404)
    except ValueError as error:
        return JSONResponse({"error": "customer_hotspots_invalid", "detail": str(error)}, status_code=409)


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

        raw_period = request.query_params.get("return_period_years")
        return_period = int(raw_period) if raw_period not in (None, "") else None
        result_source = request.query_params.get("result_source")

        return JSONResponse(
            public_citywide_2d_bootstrap_payload(return_period, result_source)
        )
    except (TypeError, ValueError) as error:
        return JSONResponse({"error": str(error)}, status_code=409)


async def get_abu_dhabi_public_citywide_2d_timeseries(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    raw_index = request.query_params.get("time_index", "0")
    raw_period = request.query_params.get("return_period_years")
    result_source = request.query_params.get("result_source")
    try:
        time_index = int(raw_index)
    except (TypeError, ValueError):
        return JSONResponse({"error": "time_index_invalid"}, status_code=400)
    try:
        from ..abu_dhabi_flood_scenario_service import public_citywide_2d_timeseries_payload
        return_period = int(raw_period) if raw_period not in (None, "") else None

        return JSONResponse(
            public_citywide_2d_timeseries_payload(
                time_index, return_period, result_source
            )
        )
    except (TypeError, ValueError) as error:
        return JSONResponse({"error": str(error)}, status_code=409)


async def create_abu_dhabi_surface_run(request: Request) -> JSONResponse:
    """Start a new private ANUGA phase-3 job without touching registered results."""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "surface_json_required"}, status_code=400)
    try:
        from ..abu_dhabi_surface_run_service import start_surface_run

        return JSONResponse(start_surface_run(payload), status_code=202)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    except Exception as error:
        return JSONResponse({"error": "surface_run_start_failed", "detail": str(error)[:500]}, status_code=500)


async def get_abu_dhabi_surface_run(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    run_id = str(request.path_params.get("run_id") or "")
    try:
        from ..abu_dhabi_surface_run_service import public_surface_run

        return JSONResponse(public_surface_run(run_id))
    except KeyError:
        return JSONResponse({"error": "surface_run_not_found"}, status_code=404)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)


async def get_abu_dhabi_surface_run_map(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    run_id = str(request.path_params.get("run_id") or "")
    try:
        from ..abu_dhabi_surface_run_service import surface_map_bootstrap

        return JSONResponse(surface_map_bootstrap(run_id))
    except KeyError:
        return JSONResponse({"error": "surface_run_not_found"}, status_code=404)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)


async def get_abu_dhabi_surface_run_timeseries(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    run_id = str(request.path_params.get("run_id") or "")
    try:
        time_index = int(request.query_params.get("time_index", "0"))
    except (TypeError, ValueError):
        return JSONResponse({"error": "time_index_invalid"}, status_code=400)
    try:
        from ..abu_dhabi_surface_run_service import surface_map_timeseries

        return JSONResponse(surface_map_timeseries(run_id, time_index))
    except KeyError:
        return JSONResponse({"error": "surface_run_not_found"}, status_code=404)
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


async def get_abu_dhabi_april_2024_sentinel_observation(request: Request) -> JSONResponse:
    """Serve audited, non-spatial Sentinel-2 holdout metadata for the UI."""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        from ..abu_dhabi_sentinel_observation_service import observed_flood_dashboard_payload

        return JSONResponse(observed_flood_dashboard_payload())
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)
    except Exception as error:
        return JSONResponse({"error": "sentinel_observation_dashboard_failed", "detail": str(error)[:500]}, status_code=500)


async def get_abu_dhabi_april_2024_sentinel_observation_map(request: Request) -> JSONResponse:
    """Serve the cloud-screened 250 m observed-water cells in WGS84."""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        from ..abu_dhabi_sentinel_observation_service import observed_flood_map_payload

        return JSONResponse(observed_flood_map_payload())
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)
    except Exception as error:
        return JSONResponse({"error": "sentinel_observation_map_failed", "detail": str(error)[:500]}, status_code=500)


async def create_abu_dhabi_flood_gwm_rollout(request: Request) -> JSONResponse:
    """Run the isolated phase-4 GWM rapid rollout over phase-3 results."""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "gwm_json_required"}, status_code=400)
    try:
        from ..abu_dhabi_flood_gwm_service import start_gwm_rollout

        return JSONResponse(start_gwm_rollout(payload), status_code=202)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)
    except Exception as error:
        return JSONResponse({"error": "gwm_rollout_failed", "detail": str(error)[:500]}, status_code=500)


async def get_abu_dhabi_flood_gwm_run(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    run_id = str(request.path_params.get("run_id") or "")
    try:
        from ..abu_dhabi_flood_gwm_service import public_run

        return JSONResponse(public_run(run_id))
    except KeyError:
        return JSONResponse({"error": "gwm_run_not_found"}, status_code=404)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)


async def get_abu_dhabi_flood_gwm_map(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    run_id = str(request.path_params.get("run_id") or "")
    try:
        from ..abu_dhabi_flood_gwm_service import map_bootstrap

        return JSONResponse(map_bootstrap(run_id))
    except KeyError:
        return JSONResponse({"error": "gwm_run_not_found"}, status_code=404)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)


async def get_abu_dhabi_flood_gwm_map_timeseries(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    run_id = str(request.path_params.get("run_id") or "")
    try:
        time_index = int(request.query_params.get("time_index", "0"))
    except (TypeError, ValueError):
        return JSONResponse({"error": "time_index_invalid"}, status_code=400)
    try:
        from ..abu_dhabi_flood_gwm_service import map_timeseries

        return JSONResponse(map_timeseries(run_id, time_index))
    except KeyError:
        return JSONResponse({"error": "gwm_run_not_found"}, status_code=404)


async def get_abu_dhabi_historical_replay_validation_bootstrap(request: Request) -> JSONResponse:
    """Return the isolated phase-5 historical replay and validation contract."""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        from ..abu_dhabi_flood_validation_service import historical_replay_bootstrap_payload

        return JSONResponse(historical_replay_bootstrap_payload())
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)


async def get_abu_dhabi_trained_gwm_events(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        from ..abu_dhabi_trained_gwm_service import available_events

        return JSONResponse(available_events())
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)
    except Exception as error:
        return JSONResponse({"error": "trained_gwm_events_failed", "detail": str(error)[:500]}, status_code=500)


async def create_abu_dhabi_trained_gwm_rollout(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "trained_gwm_json_required"}, status_code=400)
    try:
        from ..abu_dhabi_trained_gwm_service import start_rollout

        return JSONResponse(start_rollout(payload), status_code=202)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)
    except Exception as error:
        return JSONResponse({"error": "trained_gwm_rollout_failed", "detail": str(error)[:500]}, status_code=500)


async def get_abu_dhabi_trained_gwm_run(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    run_id = str(request.path_params.get("run_id") or "")
    try:
        from ..abu_dhabi_trained_gwm_service import public_run

        return JSONResponse(public_run(run_id))
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)


async def get_abu_dhabi_trained_gwm_map(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    run_id = str(request.path_params.get("run_id") or "")
    try:
        from ..abu_dhabi_trained_gwm_service import map_bootstrap

        return JSONResponse(map_bootstrap(run_id))
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)


async def get_abu_dhabi_trained_gwm_map_timeseries(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    run_id = str(request.path_params.get("run_id") or "")
    try:
        time_index = int(request.query_params.get("time_index", "0"))
    except (TypeError, ValueError):
        return JSONResponse({"error": "trained_gwm_time_index_invalid"}, status_code=400)
    try:
        from ..abu_dhabi_trained_gwm_service import map_timeseries

        return JSONResponse(map_timeseries(run_id, time_index))
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)
    except Exception as error:
        return JSONResponse({"error": "historical_replay_validation_failed", "detail": str(error)[:500]}, status_code=500)


async def get_abu_dhabi_historical_replay_validation_timeseries(request: Request) -> JSONResponse:
    """Return one phase-5 ANUGA surface-depth frame by index."""

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
        from ..abu_dhabi_flood_validation_service import historical_replay_timeseries_payload

        return JSONResponse(historical_replay_timeseries_payload(time_index))
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)
    except Exception as error:
        return JSONResponse({"error": "historical_replay_timeseries_failed", "detail": str(error)[:500]}, status_code=500)


async def get_abu_dhabi_historical_replay_validation_report(request: Request) -> HTMLResponse | JSONResponse:
    """Return a self-contained, printable customer delivery report for phase 5."""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        from ..abu_dhabi_flood_validation_service import historical_replay_report_html
        from ..i18n import get_language

        return HTMLResponse(
            historical_replay_report_html(get_language()),
            headers={"Content-Disposition": 'inline; filename="abu_dhabi_flood_phase5_delivery_report.html"'},
        )
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)
    except Exception as error:
        return JSONResponse({"error": "historical_replay_report_failed", "detail": str(error)[:500]}, status_code=500)


async def get_abu_dhabi_flood_simulation_report(request: Request) -> HTMLResponse | JSONResponse:
    """Render a decision-support report for any simulation type.

    ``report_type`` is deliberately explicit so a customer can bookmark or
    archive the exact report contract (design storm, SWMM, citywide 2D, GWM,
    historical replay or data admission).
    """

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    report_type = str(request.path_params.get("report_type") or "")
    run_id = request.query_params.get("run_id")
    raw_period = request.query_params.get("return_period_years")
    try:
        return_period = int(raw_period) if raw_period not in (None, "") else None
        from ..abu_dhabi_flood_report_service import simulation_report_html
        from ..i18n import get_language

        filename = f"abu_dhabi_flood_{report_type}_report.html"
        return HTMLResponse(
            simulation_report_html(report_type, get_language(), run_id, return_period),
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)
    except Exception as error:
        return JSONResponse({"error": "simulation_report_failed", "detail": str(error)[:500]}, status_code=500)


async def get_abu_dhabi_flood_simulation_report_json(request: Request) -> JSONResponse:
    """Return the machine-readable decision-support report payload."""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    report_type = str(request.path_params.get("report_type") or "")
    run_id = request.query_params.get("run_id")
    raw_period = request.query_params.get("return_period_years")
    try:
        return_period = int(raw_period) if raw_period not in (None, "") else None
        from ..abu_dhabi_flood_report_service import simulation_report_payload

        return JSONResponse(simulation_report_payload(report_type, run_id, return_period))
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)
    except Exception as error:
        return JSONResponse({"error": "simulation_report_failed", "detail": str(error)[:500]}, status_code=500)


def get_abu_dhabi_flood_routes() -> list[Route]:
    return [
        Route("/api/abu-dhabi/flood/customer-hotspots/bootstrap", endpoint=get_abu_dhabi_customer_hotspots_bootstrap, methods=["GET"]),
        Route("/api/abu-dhabi/flood/scenarios", endpoint=create_abu_dhabi_flood_scenario, methods=["POST"]),
        Route("/api/abu-dhabi/flood/scenarios/latest", endpoint=get_latest_abu_dhabi_flood_scenario, methods=["GET"]),
        Route("/api/abu-dhabi/flood/design-storms/latest", endpoint=get_latest_zone_b_design_storm_batch, methods=["GET"]),
        Route("/api/abu-dhabi/flood/scenarios/{run_id}", endpoint=get_abu_dhabi_flood_scenario, methods=["GET"]),
        Route("/api/abu-dhabi/flood/scenarios/{run_id}/map/bootstrap", endpoint=get_abu_dhabi_flood_scenario_map_bootstrap, methods=["GET"]),
        Route("/api/abu-dhabi/flood/scenarios/{run_id}/map", endpoint=get_abu_dhabi_flood_scenario_map, methods=["GET"]),
        Route("/api/abu-dhabi/flood/scenarios/{run_id}/map/timeseries", endpoint=get_abu_dhabi_flood_scenario_map_timeseries, methods=["GET"]),
        Route("/api/abu-dhabi/flood/dtm-diagnostic/bootstrap", endpoint=get_abu_dhabi_dtm_diagnostic_bootstrap, methods=["GET"]),
        Route("/api/abu-dhabi/flood/dtm-diagnostic/timeseries", endpoint=get_abu_dhabi_dtm_diagnostic_timeseries, methods=["GET"]),
        Route("/api/abu-dhabi/flood/public-citywide-2d/bootstrap", endpoint=get_abu_dhabi_public_citywide_2d_bootstrap, methods=["GET"]),
        Route("/api/abu-dhabi/flood/public-citywide-2d/timeseries", endpoint=get_abu_dhabi_public_citywide_2d_timeseries, methods=["GET"]),
        Route("/api/abu-dhabi/flood/surface/runs", endpoint=create_abu_dhabi_surface_run, methods=["POST"]),
        Route("/api/abu-dhabi/flood/surface/runs/{run_id}", endpoint=get_abu_dhabi_surface_run, methods=["GET"]),
        Route("/api/abu-dhabi/flood/surface/runs/{run_id}/map/bootstrap", endpoint=get_abu_dhabi_surface_run_map, methods=["GET"]),
        Route("/api/abu-dhabi/flood/surface/runs/{run_id}/map/timeseries", endpoint=get_abu_dhabi_surface_run_timeseries, methods=["GET"]),
        Route("/api/abu-dhabi/flood/events/april-2024/evidence", endpoint=get_abu_dhabi_april_2024_event_evidence, methods=["GET"]),
        Route("/api/abu-dhabi/flood/validation/april-2024/sentinel-observation", endpoint=get_abu_dhabi_april_2024_sentinel_observation, methods=["GET"]),
        Route("/api/abu-dhabi/flood/validation/april-2024/sentinel-observation/map", endpoint=get_abu_dhabi_april_2024_sentinel_observation_map, methods=["GET"]),
        Route("/api/abu-dhabi/flood/gwm/rollout", endpoint=create_abu_dhabi_flood_gwm_rollout, methods=["POST"]),
        Route("/api/abu-dhabi/flood/gwm/runs/{run_id}", endpoint=get_abu_dhabi_flood_gwm_run, methods=["GET"]),
        Route("/api/abu-dhabi/flood/gwm/runs/{run_id}/map", endpoint=get_abu_dhabi_flood_gwm_map, methods=["GET"]),
        Route("/api/abu-dhabi/flood/gwm/runs/{run_id}/map/timeseries", endpoint=get_abu_dhabi_flood_gwm_map_timeseries, methods=["GET"]),
        Route("/api/abu-dhabi/flood/gwm/trained/events", endpoint=get_abu_dhabi_trained_gwm_events, methods=["GET"]),
        Route("/api/abu-dhabi/flood/gwm/trained/rollout", endpoint=create_abu_dhabi_trained_gwm_rollout, methods=["POST"]),
        Route("/api/abu-dhabi/flood/gwm/trained/runs/{run_id}", endpoint=get_abu_dhabi_trained_gwm_run, methods=["GET"]),
        Route("/api/abu-dhabi/flood/gwm/trained/runs/{run_id}/map", endpoint=get_abu_dhabi_trained_gwm_map, methods=["GET"]),
        Route("/api/abu-dhabi/flood/gwm/trained/runs/{run_id}/map/timeseries", endpoint=get_abu_dhabi_trained_gwm_map_timeseries, methods=["GET"]),
        Route("/api/abu-dhabi/flood/validation/historical-replay/bootstrap", endpoint=get_abu_dhabi_historical_replay_validation_bootstrap, methods=["GET"]),
        Route("/api/abu-dhabi/flood/validation/historical-replay/timeseries", endpoint=get_abu_dhabi_historical_replay_validation_timeseries, methods=["GET"]),
        Route("/api/abu-dhabi/flood/validation/historical-replay/report", endpoint=get_abu_dhabi_historical_replay_validation_report, methods=["GET"]),
        Route("/api/abu-dhabi/flood/reports/{report_type}", endpoint=get_abu_dhabi_flood_simulation_report, methods=["GET"]),
        Route("/api/abu-dhabi/flood/reports/{report_type}/json", endpoint=get_abu_dhabi_flood_simulation_report_json, methods=["GET"]),
    ]
