"""API routes for real-data UWM multi-stage intervention planning."""

from __future__ import annotations

import asyncio
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from data_agent.uwm.multistage_intervention_planner import (
    MultiStageInterventionPlannerService,
)

from .helpers import _get_user_from_request, _set_user_context


_SERVICE = MultiStageInterventionPlannerService()


def _authorize(request: Request) -> JSONResponse | None:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    return None


async def overview(request: Request):
    denied = _authorize(request)
    if denied:
        return denied
    try:
        return JSONResponse(await asyncio.to_thread(_SERVICE.overview))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def actions(request: Request):
    denied = _authorize(request)
    if denied:
        return denied
    query = request.query_params
    action_types = [value for value in query.get("action_types", "").split(",") if value]
    try:
        payload = await asyncio.to_thread(
            _SERVICE.actions,
            county=query.get("county", ""),
            action_types=action_types or None,
            limit=int(query.get("limit", "100")),
        )
        return JSONResponse(payload)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def plan(request: Request):
    denied = _authorize(request)
    if denied:
        return denied
    try:
        body: dict[str, Any] = await request.json()
        return JSONResponse(await asyncio.to_thread(_SERVICE.plan, body))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def get_run(request: Request):
    denied = _authorize(request)
    if denied:
        return denied
    try:
        return JSONResponse(
            await asyncio.to_thread(_SERVICE.get_run, request.path_params["run_id"])
        )
    except FileNotFoundError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def get_map(request: Request):
    denied = _authorize(request)
    if denied:
        return denied
    try:
        return JSONResponse(
            await asyncio.to_thread(_SERVICE.get_map, request.path_params["run_id"])
        )
    except FileNotFoundError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


def get_uwm_multistage_intervention_routes() -> list:
    return [
        Route("/api/uwm/multistage-intervention/overview", overview, methods=["GET"]),
        Route("/api/uwm/multistage-intervention/actions", actions, methods=["GET"]),
        Route("/api/uwm/multistage-intervention/plan", plan, methods=["POST"]),
        Route("/api/uwm/multistage-intervention/runs/{run_id}", get_run, methods=["GET"]),
        Route("/api/uwm/multistage-intervention/runs/{run_id}/map", get_map, methods=["GET"]),
    ]
