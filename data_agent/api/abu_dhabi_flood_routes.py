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
        return JSONResponse(
            {"error": "scenario_start_failed", "detail": str(error)[:500]}, status_code=500
        )


async def create_abu_dhabi_hydro_run(request: Request) -> JSONResponse:
    """Submit a manifest-backed Kubernetes hydro Job from the GIS app."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    from ..hydro_workbench.api import create_hydro_run

    return await create_hydro_run(request)


async def preflight_abu_dhabi_hydro_run(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    from ..hydro_workbench.api import preflight_hydro_run

    return await preflight_hydro_run(request)


async def get_abu_dhabi_hydro_run(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    from ..hydro_workbench.api import get_hydro_run

    return await get_hydro_run(request)


async def cancel_abu_dhabi_hydro_run(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    from ..hydro_workbench.api import cancel_hydro_run

    return await cancel_hydro_run(request)


async def get_abu_dhabi_hydro_result(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    from ..hydro_workbench.api import get_hydro_result

    return await get_hydro_result(request)


async def get_abu_dhabi_hydro_logs(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    from ..hydro_workbench.api import get_hydro_logs

    return await get_hydro_logs(request)


async def get_abu_dhabi_hydro_map(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    from ..hydro_workbench.api import get_hydro_map

    return await get_hydro_map(request)


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
    """Serve aggregate metadata from the private customer hotspot bundle."""

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


async def get_abu_dhabi_gwm_external_validation(request: Request) -> JSONResponse:
    """Serve a sanitized audit ledger for the frozen external-validation cohorts."""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        from ..uwm.abu_dhabi_flood.external_validation import (
            external_validation_payload,
        )

        return JSONResponse(external_validation_payload())
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
        return JSONResponse(
            {"error": "gwm_train_failed", "detail": str(error)[:500]}, status_code=500
        )


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
        return JSONResponse(
            {"error": "gwm_rollout_failed", "detail": str(error)[:500]}, status_code=500
        )


async def get_latest_abu_dhabi_gwm_run(request: Request) -> JSONResponse:
    """Restore the latest GWM result or build the standard offline demo run."""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        from ..uwm.abu_dhabi_flood.gwm_surrogate import gwm_store

        return JSONResponse(gwm_store().latest_or_default())
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)
    except Exception as error:
        return JSONResponse(
            {"error": "gwm_latest_restore_failed", "detail": str(error)[:500]},
            status_code=500,
        )


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


async def get_abu_dhabi_trained_gwm_events(request: Request) -> JSONResponse:
    """List the admitted historical events for the frozen citywide GWM."""

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
        return JSONResponse(
            {"error": "trained_gwm_events_failed", "detail": str(error)[:500]}, status_code=500
        )


async def create_abu_dhabi_trained_gwm_rollout(request: Request) -> JSONResponse:
    """Run the frozen GWM with an admitted event and bounded dynamic forcing."""

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
        return JSONResponse(
            {"error": "trained_gwm_rollout_failed", "detail": str(error)[:500]}, status_code=500
        )


async def create_abu_dhabi_trained_gwm_rainfall_scenario(request: Request) -> JSONResponse:
    """Create a frozen-GWM scenario from a customer-facing rainfall total in mm."""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "trained_gwm_json_required"}, status_code=400)
    try:
        from ..abu_dhabi_trained_gwm_service import start_rainfall_amount_rollout

        return JSONResponse(start_rainfall_amount_rollout(payload), status_code=202)
    except ValueError as error:
        code = str(error)
        validation_errors = {
            "trained_gwm_payload_invalid",
            "trained_gwm_event_id_required",
            "trained_gwm_event_not_admitted",
            "trained_gwm_total_rainfall_invalid",
            "trained_gwm_total_rainfall_out_of_supported_range",
            "trained_gwm_rainfall_duration_invalid",
            "trained_gwm_rainfall_duration_out_of_supported_range",
        }
        return JSONResponse(
            {"error": code},
            status_code=422 if code in validation_errors else 409,
        )
    except Exception as error:
        return JSONResponse(
            {
                "error": "trained_gwm_rainfall_scenario_failed",
                "detail": str(error)[:500],
            },
            status_code=500,
        )


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
        return JSONResponse(
            {"error": "trained_gwm_timeseries_failed", "detail": str(error)[:500]}, status_code=500
        )


def get_abu_dhabi_flood_routes() -> list[Route]:
    return [
        Route(
            "/api/abu-dhabi/flood/scenarios",
            endpoint=create_abu_dhabi_flood_scenario,
            methods=["POST"],
        ),
        Route(
            "/api/abu-dhabi/flood/hydro-runs", endpoint=create_abu_dhabi_hydro_run, methods=["POST"]
        ),
        Route(
            "/api/abu-dhabi/flood/hydro-runs/preflight",
            endpoint=preflight_abu_dhabi_hydro_run,
            methods=["POST"],
        ),
        Route(
            "/api/abu-dhabi/flood/hydro-runs/{run_id}",
            endpoint=get_abu_dhabi_hydro_run,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/hydro-runs/{run_id}",
            endpoint=cancel_abu_dhabi_hydro_run,
            methods=["DELETE"],
        ),
        Route(
            "/api/abu-dhabi/flood/hydro-runs/{run_id}/result",
            endpoint=get_abu_dhabi_hydro_result,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/hydro-runs/{run_id}/logs",
            endpoint=get_abu_dhabi_hydro_logs,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/hydro-runs/{run_id}/map",
            endpoint=get_abu_dhabi_hydro_map,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/scenarios/latest",
            endpoint=get_latest_abu_dhabi_flood_scenario,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/design-storms/latest",
            endpoint=get_latest_zone_b_design_storm_batch,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/pipeline-status",
            endpoint=get_abu_dhabi_flood_pipeline_status,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/scenarios/{run_id}",
            endpoint=get_abu_dhabi_flood_scenario,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/scenarios/{run_id}/map/bootstrap",
            endpoint=get_abu_dhabi_flood_scenario_map_bootstrap,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/scenarios/{run_id}/map",
            endpoint=get_abu_dhabi_flood_scenario_map,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/scenarios/{run_id}/map/timeseries",
            endpoint=get_abu_dhabi_flood_scenario_map_timeseries,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/dtm-diagnostic/bootstrap",
            endpoint=get_abu_dhabi_dtm_diagnostic_bootstrap,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/dtm-diagnostic/timeseries",
            endpoint=get_abu_dhabi_dtm_diagnostic_timeseries,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/public-citywide-2d/bootstrap",
            endpoint=get_abu_dhabi_public_citywide_2d_bootstrap,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/public-citywide-2d/timeseries",
            endpoint=get_abu_dhabi_public_citywide_2d_timeseries,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/events/april-2024/evidence",
            endpoint=get_abu_dhabi_april_2024_event_evidence,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/hotspots/catalog",
            endpoint=get_abu_dhabi_hotspot_catalog,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/hotspots/map", endpoint=get_abu_dhabi_hotspot_map, methods=["GET"]
        ),
        Route(
            "/api/abu-dhabi/flood/gwm/external-validation",
            endpoint=get_abu_dhabi_gwm_external_validation,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/validation/report",
            endpoint=get_abu_dhabi_phase5_delivery_report,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/gwm/status", endpoint=get_abu_dhabi_gwm_status, methods=["GET"]
        ),
        Route("/api/abu-dhabi/flood/gwm/train", endpoint=train_abu_dhabi_gwm, methods=["POST"]),
        Route("/api/abu-dhabi/flood/gwm/rollout", endpoint=run_abu_dhabi_gwm, methods=["POST"]),
        Route(
            "/api/abu-dhabi/flood/gwm/latest",
            endpoint=get_latest_abu_dhabi_gwm_run,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/gwm/runs/{run_id}",
            endpoint=get_abu_dhabi_gwm_run,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/gwm/runs/{run_id}/map/bootstrap",
            endpoint=get_abu_dhabi_gwm_bootstrap,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/gwm/runs/{run_id}/timeseries",
            endpoint=get_abu_dhabi_gwm_timeseries,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/gwm/trained/events",
            endpoint=get_abu_dhabi_trained_gwm_events,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/gwm/trained/rollout",
            endpoint=create_abu_dhabi_trained_gwm_rollout,
            methods=["POST"],
        ),
        Route(
            "/api/abu-dhabi/flood/gwm/trained/rainfall-scenarios",
            endpoint=create_abu_dhabi_trained_gwm_rainfall_scenario,
            methods=["POST"],
        ),
        Route(
            "/api/abu-dhabi/flood/gwm/trained/runs/{run_id}",
            endpoint=get_abu_dhabi_trained_gwm_run,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/gwm/trained/runs/{run_id}/map",
            endpoint=get_abu_dhabi_trained_gwm_map,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/flood/gwm/trained/runs/{run_id}/map/timeseries",
            endpoint=get_abu_dhabi_trained_gwm_map_timeseries,
            methods=["GET"],
        ),
    ]
