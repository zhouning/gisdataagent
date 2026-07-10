"""Read-only API for canonical customer AI demand ownership readiness."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context
from data_agent.uwm.livability_requirement_registry import (
    build_livability_requirement_registry,
    validate_livability_requirement_registry,
)


UWM_AI_DEMAND_READINESS_API_SCHEMA = "uwm.ai_demand_readiness_api.v2"


def load_uwm_ai_demand_readiness_payload() -> dict[str, Any]:
    """Build readiness directly from the canonical ownership registry."""

    registry = build_livability_requirement_registry()
    validation = validate_livability_requirement_registry(registry)
    if not validation["valid"]:
        raise ValueError(
            "invalid canonical registry: " + "; ".join(validation["errors"])
        )
    registry = deepcopy(registry)
    requirement_rows = (
        registry["livability_scenarios"] + registry["customer_ai_demands"]
    )
    route_rows = []
    for route in registry["primary_routes"]:
        availability_values = {
            row["route_availability"]
            for row in requirement_rows
            if row["primary_route"] == route
        }
        if not availability_values:
            raise ValueError(f"{route} has no canonical requirement rows")
        if len(availability_values) != 1:
            raise ValueError(f"{route} has conflicting route_availability values")
        availability = next(iter(availability_values))
        if availability not in {"existing", "planned"}:
            raise ValueError(f"{route} has invalid route_availability: {availability}")
        route_rows.append({"route": route, "availability": availability})

    return {
        "schema": UWM_AI_DEMAND_READINESS_API_SCHEMA,
        "source_documents": registry["source_documents"],
        "source_provenance_server_side": registry[
            "source_provenance_server_side"
        ],
        "livability_scenarios": registry["livability_scenarios"],
        "customer_ai_demands": registry["customer_ai_demands"],
        "primary_routes": route_rows,
        "summary": {
            "registered_requirement_count": len(requirement_rows),
            "existing_route_count": sum(
                row["availability"] == "existing" for row in route_rows
            ),
            "planned_route_count": sum(
                row["availability"] == "planned" for row in route_rows
            ),
            "production_complete_count": sum(
                row["implementation_level"] == "production_complete"
                for row in requirement_rows
            ),
        },
        "claim_boundary": registry["claim_boundary"],
    }


async def uwm_ai_demand_readiness(request: Request):
    """GET /api/uwm/ai-demand-readiness"""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        payload = load_uwm_ai_demand_readiness_payload()
    except ValueError:
        return JSONResponse(
            {"error": "AI demand readiness registry validation failed"},
            status_code=503,
        )
    return JSONResponse(payload)


def get_uwm_ai_demand_readiness_routes() -> list:
    """Return Route objects for customer AI demand readiness."""

    return [
        Route(
            "/api/uwm/ai-demand-readiness",
            uwm_ai_demand_readiness,
            methods=["GET"],
        )
    ]
