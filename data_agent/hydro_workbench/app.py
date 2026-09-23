"""Standalone web entry point for the Docker Desktop development namespace."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from .api import (
    cancel_hydro_run,
    create_hydro_run,
    get_hydro_logs,
    get_hydro_map,
    get_hydro_result,
    get_hydro_run,
    preflight_hydro_run,
    workbench_page,
)


async def health(request):
    return JSONResponse(
        {
            "status": "ok",
            "service": "abu-dhabi-hydro-workbench",
            "contract": "hydro_run_manifest.v1",
        }
    )


routes = [
    Route("/", workbench_page, methods=["GET"]),
    Route("/health", health, methods=["GET"]),
    Route(
        "/api/abu-dhabi/flood/hydro-runs/preflight",
        preflight_hydro_run,
        methods=["POST"],
    ),
    Route("/api/abu-dhabi/flood/hydro-runs", create_hydro_run, methods=["POST"]),
    Route("/api/abu-dhabi/flood/hydro-runs/{run_id}", get_hydro_run, methods=["GET"]),
    Route("/api/abu-dhabi/flood/hydro-runs/{run_id}", cancel_hydro_run, methods=["DELETE"]),
    Route("/api/abu-dhabi/flood/hydro-runs/{run_id}/result", get_hydro_result, methods=["GET"]),
    Route("/api/abu-dhabi/flood/hydro-runs/{run_id}/logs", get_hydro_logs, methods=["GET"]),
    Route("/api/abu-dhabi/flood/hydro-runs/{run_id}/map", get_hydro_map, methods=["GET"]),
]
app = Starlette(debug=False, routes=routes)
