from data_agent.uwm.livability_requirement_registry import (
    CUSTOMER_DEMAND_PRIMARY_ROUTES,
    LIVABILITY_SCENARIO_PRIMARY_ROUTES,
    PRIMARY_ROUTES,
    build_livability_requirement_registry,
    requirement_coverage_for_route,
    validate_livability_requirement_registry,
)


EXPECTED_SCENARIO_ROUTES = {
    "S1": "traditional_livability",
    "S2": "uwm_livability",
    "S4": "traditional_livability",
    "S6": "traditional_livability",
    "S7": "traditional_livability",
}

EXPECTED_DEMAND_ROUTES = {
    "1": "planning_land",
    "2": "planning_land",
    "3": "planning_land",
    "4": "infrastructure_assets",
    "5": "infrastructure_assets",
    "6": "population_demand",
    "7": "uwm_livability",
    "8": "traditional_livability",
    "9": "traditional_livability",
    "10": "traditional_livability",
    "11": "uwm_livability",
    "12": "traditional_livability",
    "13": "traditional_livability",
    "14": "traditional_livability",
    "15": "traditional_livability",
    "16": "traditional_livability",
    "17": "infrastructure_assets",
    "18": "infrastructure_assets",
    "19": "uwm_livability",
    "20": "economy_investment",
    "21": "traditional_livability",
    "22": "planning_land",
    "23": "economy_investment",
    "24": "impact_implementation",
    "25": "impact_implementation",
}


def test_registry_has_canonical_unique_ownership():
    registry = build_livability_requirement_registry()

    assert len(registry["livability_scenarios"]) == 5
    assert len(registry["customer_ai_demands"]) == 25
    assert LIVABILITY_SCENARIO_PRIMARY_ROUTES == EXPECTED_SCENARIO_ROUTES
    assert CUSTOMER_DEMAND_PRIMARY_ROUTES == EXPECTED_DEMAND_ROUTES
    assert validate_livability_requirement_registry(registry) == {
        "valid": True,
        "errors": [],
    }


def test_route_filtered_views_cover_every_requirement_once():
    registry = build_livability_requirement_registry()
    scenario_counts = {scenario_id: 0 for scenario_id in EXPECTED_SCENARIO_ROUTES}
    demand_counts = {demand_id: 0 for demand_id in EXPECTED_DEMAND_ROUTES}

    for route in PRIMARY_ROUTES:
        coverage = requirement_coverage_for_route(registry, route)
        assert coverage["primary_route"] == route
        assert all(row["primary_route"] == route for row in coverage["livability_scenarios"])
        assert all(row["primary_route"] == route for row in coverage["customer_ai_demands"])
        for row in coverage["livability_scenarios"]:
            scenario_counts[row["id"]] += 1
        for row in coverage["customer_ai_demands"]:
            demand_counts[row["id"]] += 1

    assert set(scenario_counts.values()) == {1}
    assert set(demand_counts.values()) == {1}


def test_registry_keeps_financial_and_policy_claim_boundaries_explicit():
    registry = build_livability_requirement_registry()
    demands = {row["id"]: row for row in registry["customer_ai_demands"]}

    assert demands["23"]["data_support"] == "requires_customer_data"
    assert demands["23"]["implemented_outputs"] == []
    assert registry["claim_boundary"]["registration_is_not_implementation"] is True
    assert (
        registry["claim_boundary"]["observed_policy_outcome_superiority_claim"]
        is False
    )


def test_validator_rejects_duplicate_ids_and_invalid_row_contracts():
    registry = build_livability_requirement_registry()
    registry["customer_ai_demands"][1]["id"] = "1"
    registry["livability_scenarios"][0]["primary_route"] = "invalid"
    registry["customer_ai_demands"][2]["route_availability"] = "unknown"
    registry["customer_ai_demands"][3]["implemented_outputs"] = "not-a-list"
    registry["customer_ai_demands"][4]["production_blockers"] = "not-a-list"

    validation = validate_livability_requirement_registry(registry)

    assert validation["valid"] is False
    assert validation["errors"]


def test_route_filter_rejects_unknown_route():
    registry = build_livability_requirement_registry()

    try:
        requirement_coverage_for_route(registry, "not_a_route")
    except ValueError as exc:
        assert "not_a_route" in str(exc)
    else:
        raise AssertionError("unknown routes must be rejected")
