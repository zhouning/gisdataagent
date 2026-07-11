import asyncio
import json

import pytest
from starlette.requests import Request

from data_agent.api import uwm_ai_demand_readiness_routes as routes
from data_agent.uwm.livability_requirement_registry import (
    build_livability_requirement_registry,
)
from data_agent.uwm.ai_demand_implementation_ledger import IMPLEMENTATION_STATUSES


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
    for payload_rows, registry_rows in [
        (payload["livability_scenarios"], registry["livability_scenarios"]),
        (payload["customer_ai_demands"], registry["customer_ai_demands"]),
    ]:
        canonical = {row["id"]: row for row in registry_rows}
        assert {row["id"] for row in payload_rows} == set(canonical)
        for row in payload_rows:
            assert row["primary_route"] == canonical[row["id"]]["primary_route"]
            assert row["required_method"] == canonical[row["id"]]["required_method"]
    assert payload["claim_boundary"]["registration_is_not_implementation"] is True
    assert payload["claim_boundary"]["product_presence_is_not_full_requirement_completion"] is True
    assert payload["source_provenance_server_side"] is True
    assert all(not source.startswith("/") for source in payload["source_documents"])


def test_ai_demand_readiness_payload_validates_registry_before_publishing(monkeypatch):
    validation_calls = []
    monkeypatch.setattr(
        routes,
        "validate_livability_requirement_registry",
        lambda registry: validation_calls.append(registry) or {
            "valid": False,
            "errors": ["canonical drift"],
        },
    )

    with pytest.raises(ValueError, match="canonical drift"):
        routes.load_uwm_ai_demand_readiness_payload()

    assert len(validation_calls) == 1


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
    assert payload["summary"]["registered_requirement_count"] == 30
    assert payload["summary"]["existing_route_count"] == 2
    assert payload["summary"]["planned_route_count"] == 5
    assert payload["summary"]["production_complete_count"] == 0
    assert set(payload["summary"]["implementation_status_counts"]) == IMPLEMENTATION_STATUSES
    assert sum(payload["summary"]["implementation_status_counts"].values()) == 30
    assert payload["summary"]["verified_or_bounded_count"] > 0
    assert payload["claim_boundary"]["registration_is_not_implementation"] is True
    assert (
        payload["claim_boundary"]["observed_policy_outcome_superiority_claim"]
        is False
    )
    assert "phase_counts" not in payload


def test_ai_demand_readiness_exposes_real_implementation_ledger_fields():
    payload = routes.load_uwm_ai_demand_readiness_payload()
    rows = payload["livability_scenarios"] + payload["customer_ai_demands"]
    for row in rows:
        assert row["implementation_status"] in IMPLEMENTATION_STATUSES
        assert row["status_basis"]
        assert isinstance(row["evidence_artifacts"], list)
        assert isinstance(row["evidence_artifact_checks"], list)
        assert isinstance(row["next_actions"], list)
        assert row["max_supported_claim"]
    demand11 = next(row for row in payload["customer_ai_demands"] if row["id"] == "11")
    assert demand11["implementation_status"] == "implemented_evidence_bounded"
    assert "environmental_action_response_closed" in demand11["production_blockers"]


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
    monkeypatch.setattr(
        routes,
        "validate_livability_requirement_registry",
        lambda payload: {"valid": True, "errors": []},
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
    monkeypatch.setattr(
        routes,
        "validate_livability_requirement_registry",
        lambda payload: {"valid": True, "errors": []},
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


def test_ai_demand_readiness_endpoint_requires_auth(monkeypatch):
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: None)
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

    assert response.status_code == 401
    assert json.loads(response.body) == {"error": "Unauthorized"}


def test_ai_demand_readiness_endpoint_fails_closed_on_invalid_registry(monkeypatch):
    user = object()
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda authenticated_user: None)
    monkeypatch.setattr(
        routes,
        "load_uwm_ai_demand_readiness_payload",
        lambda: (_ for _ in ()).throw(ValueError("invalid canonical registry: drift")),
    )
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

    assert response.status_code == 503
    assert payload == {"error": "AI demand readiness registry validation failed"}
