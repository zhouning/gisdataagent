"""HTTP handlers shared by the existing GIS Data Agent and the dev app."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from .contracts import ManifestValidationError, build_preflight
from .coordinator import HydroRunCoordinator
from .storage import DEFAULT_ROOT, read_json, run_dir


def _coordinator() -> HydroRunCoordinator:
    return HydroRunCoordinator()


async def create_hydro_run(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
        response = _coordinator().submit(payload)
        return JSONResponse(response, status_code=202)
    except ManifestValidationError as error:
        return JSONResponse({"error": "manifest_invalid", "issues": error.issues}, status_code=422)
    except Exception as error:
        return JSONResponse(
            {"error": "hydro_run_submit_failed", "detail": str(error)[:500]}, status_code=503
        )


async def preflight_hydro_run(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
        return JSONResponse(build_preflight(payload))
    except ManifestValidationError as error:
        return JSONResponse({"error": "manifest_invalid", "issues": error.issues}, status_code=422)
    except Exception as error:
        return JSONResponse(
            {"error": "hydro_preflight_failed", "detail": str(error)[:500]}, status_code=503
        )


async def get_hydro_run(request: Request) -> JSONResponse:
    run_id = str(request.path_params.get("run_id") or "")
    try:
        return JSONResponse(_coordinator().status(run_id))
    except FileNotFoundError:
        return JSONResponse({"error": "hydro_run_not_found"}, status_code=404)
    except Exception as error:
        return JSONResponse(
            {"error": "hydro_run_status_failed", "detail": str(error)[:500]}, status_code=503
        )


async def cancel_hydro_run(request: Request) -> JSONResponse:
    run_id = str(request.path_params.get("run_id") or "")
    try:
        return JSONResponse(_coordinator().cancel(run_id), status_code=202)
    except FileNotFoundError:
        return JSONResponse({"error": "hydro_run_not_found"}, status_code=404)
    except Exception as error:
        return JSONResponse(
            {"error": "hydro_run_cancel_failed", "detail": str(error)[:500]}, status_code=503
        )


async def get_hydro_result(request: Request) -> JSONResponse:
    run_id = str(request.path_params.get("run_id") or "")
    try:
        result = read_json(run_dir(run_id, DEFAULT_ROOT) / "results" / "result.json")
    except FileNotFoundError:
        return JSONResponse({"error": "hydro_result_not_ready"}, status_code=404)
    return JSONResponse(result)


async def get_hydro_logs(request: Request) -> JSONResponse:
    run_id = str(request.path_params.get("run_id") or "")
    try:
        return JSONResponse(_coordinator().logs(run_id))
    except FileNotFoundError:
        return JSONResponse({"error": "hydro_run_not_found"}, status_code=404)
    except Exception as error:
        return JSONResponse(
            {"error": "hydro_run_logs_failed", "detail": str(error)[:500]}, status_code=503
        )


async def get_hydro_map(request: Request) -> JSONResponse:
    run_id = str(request.path_params.get("run_id") or "")
    requested = str(request.query_params.get("layer") or "")
    directory = run_dir(run_id, DEFAULT_ROOT) / "results"
    candidates = {
        "one_d": directory / "one_d" / "network.geojson",
        "two_d": directory / "two_d" / "depth_points.geojson",
        "coupled": directory / "coupled" / "maximum_depth_wgs84.geojson",
    }
    path = (
        candidates.get(requested)
        if requested
        else next((candidate for candidate in candidates.values() if candidate.exists()), None)
    )
    if path is None or not path.exists():
        return JSONResponse({"error": "hydro_map_not_ready"}, status_code=404)
    return JSONResponse(read_json(path))


def hydro_routes(*, authenticated: bool = False) -> list[Any]:
    from starlette.routing import Route

    if not authenticated:
        return [
            Route(
                "/api/abu-dhabi/flood/hydro-runs/preflight",
                preflight_hydro_run,
                methods=["POST"],
            ),
            Route("/api/abu-dhabi/flood/hydro-runs", create_hydro_run, methods=["POST"]),
            Route("/api/abu-dhabi/flood/hydro-runs/{run_id}", get_hydro_run, methods=["GET"]),
            Route("/api/abu-dhabi/flood/hydro-runs/{run_id}", cancel_hydro_run, methods=["DELETE"]),
            Route(
                "/api/abu-dhabi/flood/hydro-runs/{run_id}/result", get_hydro_result, methods=["GET"]
            ),
            Route(
                "/api/abu-dhabi/flood/hydro-runs/{run_id}/logs",
                get_hydro_logs,
                methods=["GET"],
            ),
            Route("/api/abu-dhabi/flood/hydro-runs/{run_id}/map", get_hydro_map, methods=["GET"]),
        ]
    return []


WORKBENCH_HTML = Path(__file__).with_name("workbench.html").read_text(encoding="utf-8")


async def workbench_page(request: Request) -> HTMLResponse:
    return HTMLResponse(WORKBENCH_HTML)
