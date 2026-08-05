"""Authenticated read-only routes for the natural-resource ontology demo."""

from __future__ import annotations

import json
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..natural_resource_ontology_demo import get_natural_resource_ontology_demo
from .helpers import _get_user_from_request, _set_user_context

logger = logging.getLogger("data_agent.api.ontology_demo_routes")


def _authenticate(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    return None


def _scenario_id(request: Request) -> str:
    return str(request.query_params.get("scenario_id") or "heping_review").strip()


def _handle_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, KeyError):
        return JSONResponse({"error": "demo scenario or evidence item not found"}, status_code=404)
    if isinstance(exc, (ValueError, json.JSONDecodeError)):
        return JSONResponse({"error": str(exc)}, status_code=400)
    logger.exception("natural-resource ontology demo failed")
    return JSONResponse({"error": str(exc)}, status_code=503)


async def demo_overview(request: Request):
    if error := _authenticate(request):
        return error
    try:
        return JSONResponse(get_natural_resource_ontology_demo().overview())
    except Exception as exc:
        return _handle_error(exc)


async def demo_scenarios(request: Request):
    if error := _authenticate(request):
        return error
    try:
        return JSONResponse({"items": get_natural_resource_ontology_demo().scenarios()})
    except Exception as exc:
        return _handle_error(exc)


async def demo_map(request: Request):
    if error := _authenticate(request):
        return error
    try:
        return JSONResponse(get_natural_resource_ontology_demo().map_payload(_scenario_id(request)))
    except Exception as exc:
        return _handle_error(exc)


async def demo_run(request: Request):
    if error := _authenticate(request):
        return error
    try:
        body = await request.json()
        scenario_id = str(body.get("scenario_id") or "heping_review").strip()
        return JSONResponse(get_natural_resource_ontology_demo().run(scenario_id))
    except Exception as exc:
        return _handle_error(exc)


async def demo_evidence(request: Request):
    if error := _authenticate(request):
        return error
    try:
        payload = get_natural_resource_ontology_demo().evidence(
            request.query_params.get("parcel_id")
        )
        if request.query_params.get("download") == "1":
            content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            return Response(
                content,
                media_type="application/json",
                headers={
                    "Content-Disposition": (
                        'attachment; filename="natural-resource-ontology-evidence.json"'
                    )
                },
            )
        return JSONResponse(payload)
    except Exception as exc:
        return _handle_error(exc)


async def demo_governance(request: Request):
    if error := _authenticate(request):
        return error
    try:
        return JSONResponse(get_natural_resource_ontology_demo().governance())
    except Exception as exc:
        return _handle_error(exc)


def get_ontology_demo_routes() -> list[Route]:
    return [
        Route("/api/ontology/demo/overview", demo_overview, methods=["GET"]),
        Route("/api/ontology/demo/scenarios", demo_scenarios, methods=["GET"]),
        Route("/api/ontology/demo/map", demo_map, methods=["GET"]),
        Route("/api/ontology/demo/run", demo_run, methods=["POST"]),
        Route("/api/ontology/demo/evidence", demo_evidence, methods=["GET"]),
        Route("/api/ontology/demo/governance", demo_governance, methods=["GET"]),
    ]
