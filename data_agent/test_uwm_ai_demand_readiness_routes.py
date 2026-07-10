import asyncio
import json

import pytest
from starlette.requests import Request

from data_agent.api import uwm_ai_demand_readiness_routes as routes
from data_agent.uwm.livability_requirement_registry import (
    build_livability_requirement_registry,
)


def _route_methods(route_list, path):
    for route in route_list:
        if route.path == path:
            return set(route.methods or [])
    return set()


def test_ai_demand_readiness_route_is_registered_in_frontend_api():
    from data_agent.frontend_api import get_frontend_api_routes

    route_list = routes.get_uwm_ai_demand_readiness_routes()
    frontend_route_list = get_frontend_api_routes()

    assert "GET" in _route_methods(route_list, "/api/uwm/ai-demand-readiness")
    assert "GET" in _route_methods(
        frontend_route_list, "/api/uwm/ai-demand-readiness"
    )


def test_ai_demand_readiness_payload_is_built_from_canonical_registry():
    registry = build_livability_requirement_registry()
    payload = routes.load_uwm_ai_demand_readiness_payload()

    assert payload["schema"] == routes.UWM_AI_DEMAND_READINESS_API_SCHEMA
    assert payload["source_documents"] == registry["source_documents"]
    assert payload["livability_scenarios"] == registry["livability_scenarios"]
    assert payload["customer_ai_demands"] == registry["customer_ai_demands"]
    assert payload["claim_boundary"] == registry["claim_boundary"]


def test_ai_demand_readiness_payload_exposes_routes_counts_and_safe_claims():
    payload = routes.load_uwm_ai_demand_readiness_payload()

    assert len(payload["livability_scenarios"]) == 5
    assert len(payload["customer_ai_demands"]) == 25
    assert len(payload["primary_routes"]) == 7
    assert {row["route"] for row in payload["primary_routes"]} == {
        "traditional_livability",
        "uwm_livability",
        "planning_land",
        "infrastructure_assets",
        "population_demand",
        "economy_investment",
        "impact_implementation",
    }
    assert payload["summary"] == {
        "registered_requirement_count": 30,
        "existing_route_count": 2,
        "planned_route_count": 5,
        "production_complete_count": 0,
    }
    assert payload["claim_boundary"]["registration_is_not_implementation"] is True
    assert (
        payload["claim_boundary"]["observed_policy_outcome_superiority_claim"]
        is False
    )
    assert "phase_counts" not in payload


def test_ai_demand_readiness_payload_derives_statuses_and_completion(monkeypatch):
    registry = build_livability_requirement_registry()
    all_rows = registry["livability_scenarios"] + registry["customer_ai_demands"]
    for row in all_rows:
        if row["primary_route"] == "planning_land":
            row["route_availability"] = "existing"
    all_rows[0]["implementation_level"] = "production_complete"
    monkeypatch.setattr(
        routes,
        "build_livability_requirement_registry",
        lambda: registry,
    )

    payload = routes.load_uwm_ai_demand_readiness_payload()
    route_availability = {
        row["route"]: row["availability"] for row in payload["primary_routes"]
    }

    assert route_availability["planning_land"] == "existing"
    assert payload["summary"]["existing_route_count"] == 3
    assert payload["summary"]["planned_route_count"] == 4
    assert payload["summary"]["production_complete_count"] == 1


def test_ai_demand_readiness_payload_rejects_conflicting_route_availability(
    monkeypatch,
):
    registry = build_livability_requirement_registry()
    planning_rows = [
        row
        for row in registry["customer_ai_demands"]
        if row["primary_route"] == "planning_land"
    ]
    planning_rows[0]["route_availability"] = "existing"
    monkeypatch.setattr(
        routes,
        "build_livability_requirement_registry",
        lambda: registry,
    )

    with pytest.raises(ValueError, match="planning_land.*route_availability"):
        routes.load_uwm_ai_demand_readiness_payload()


def test_ai_demand_readiness_payload_is_deeply_isolated_across_calls(monkeypatch):
    registry = build_livability_requirement_registry()
    monkeypatch.setattr(
        routes,
        "build_livability_requirement_registry",
        lambda: registry,
    )
    first_payload = routes.load_uwm_ai_demand_readiness_payload()
    first_payload["livability_scenarios"][0]["implemented_outputs"].append(
        "mutated-output"
    )
    first_payload["claim_boundary"]["registration_is_not_implementation"] = False

    second_payload = routes.load_uwm_ai_demand_readiness_payload()

    assert (
        "mutated-output"
        not in second_payload["livability_scenarios"][0]["implemented_outputs"]
    )
    assert (
        second_payload["claim_boundary"]["registration_is_not_implementation"]
        is True
    )


def test_ai_demand_readiness_endpoint_returns_payload(monkeypatch):
    user = object()
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda authenticated_user: None)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/uwm/ai-demand-readiness",
            "headers": [],
            "query_string": b"",
        }
    )

    response = asyncio.run(routes.uwm_ai_demand_readiness(request))
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["schema"] == routes.UWM_AI_DEMAND_READINESS_API_SCHEMA
    assert payload["summary"]["registered_requirement_count"] == 30
    assert payload["claim_boundary"]["registration_is_not_implementation"] is True
