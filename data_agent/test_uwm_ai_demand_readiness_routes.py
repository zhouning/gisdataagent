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
