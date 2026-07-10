from data_agent.uwm.livability_requirement_registry import (
    CUSTOMER_DEMAND_PRIMARY_ROUTES,
    EVIDENCE_LEVELS,
    LIVABILITY_SCENARIO_PRIMARY_ROUTES,
    MAX_CLAIM_LEVELS,
    PRIMARY_ROUTES,
    SOURCE_DOCUMENTS,
    UNCERTAINTY_LEVELS,
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
    assert demands["23"]["evidence_level"] == "unsupported"
    assert demands["23"]["uncertainty"] == "not_assessed"
    assert demands["23"]["max_claim_level"] == "unsupported"
    assert demands["23"]["implemented_outputs"] == []
    assert registry["source_documents"] == [
        "宜居性专项分析.docx",
        "客户侧25个AI应用需求的回复.docx",
    ]
    assert all(not source.startswith("/") for source in SOURCE_DOCUMENTS)
    assert registry["source_provenance_server_side"] is True
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
    registry["customer_ai_demands"][5]["evidence_level"] = "invented"
    registry["customer_ai_demands"][6]["uncertainty"] = "certain"
    registry["customer_ai_demands"][7]["max_claim_level"] = "policy_proven"

    validation = validate_livability_requirement_registry(registry)

    assert validation["valid"] is False
    assert validation["errors"]


def test_validator_rejects_metadata_drift_with_specific_errors():
    mutations = [
        ("source_documents", [], "source_documents must exactly match canonical source documents"),
        ("primary_routes", ["uwm_livability"], "primary_routes must exactly match canonical primary routes"),
        (
            "source_provenance_server_side",
            False,
            "source_provenance_server_side must be true",
        ),
        ("claim_boundary", {}, "claim_boundary.registration_is_not_implementation must be true"),
        (
            "claim_boundary",
            {
                "registration_is_not_implementation": True,
                "observed_policy_outcome_superiority_claim": True,
            },
            "claim_boundary.observed_policy_outcome_superiority_claim must be false",
        ),
    ]

    for field, value, expected_error in mutations:
        registry = build_livability_requirement_registry()
        registry[field] = value

        validation = validate_livability_requirement_registry(registry)

        assert validation["valid"] is False
        assert expected_error in validation["errors"]

    registry = build_livability_requirement_registry()
    registry["source_documents"] = list(reversed(SOURCE_DOCUMENTS))
    validation = validate_livability_requirement_registry(registry)
    assert "source_documents must exactly match canonical source documents" in validation["errors"]


def test_validator_rejects_required_row_field_and_canonical_drift():
    required_fields = [
        "title",
        "primary_route",
        "required_method",
        "implementation_level",
        "data_support",
        "evidence_level",
        "uncertainty",
        "max_claim_level",
        "route_availability",
        "implemented_outputs",
        "production_blockers",
    ]
    for field in required_fields:
        registry = build_livability_requirement_registry()
        del registry["livability_scenarios"][0][field]

        validation = validate_livability_requirement_registry(registry)

        assert validation["valid"] is False
        assert f"scenario S1 missing required field: {field}" in validation["errors"]

    drift_cases = [
        ("livability_scenarios", "S2", "title", "漂移标题", "scenario S2 title does not match canonical definition"),
        ("livability_scenarios", "S7", "required_method", "fixed_score", "scenario S7 required_method does not match canonical definition"),
        ("customer_ai_demands", "7", "implementation_level", "complete", "demand 7 implementation_level does not match canonical definition"),
        ("customer_ai_demands", "11", "data_support", "observed", "demand 11 data_support does not match canonical definition"),
        ("customer_ai_demands", "11", "evidence_level", "simulated", "demand 11 evidence_level does not match canonical definition"),
        ("customer_ai_demands", "11", "uncertainty", "low", "demand 11 uncertainty does not match canonical definition"),
        ("customer_ai_demands", "11", "max_claim_level", "model_counterfactual", "demand 11 max_claim_level does not match canonical definition"),
        ("customer_ai_demands", "23", "implemented_outputs", ["fabricated_roi"], "demand 23 implemented_outputs does not match canonical definition"),
        ("customer_ai_demands", "23", "production_blockers", [], "demand 23 production_blockers does not match canonical definition"),
    ]
    for collection, requirement_id, field, value, expected_error in drift_cases:
        registry = build_livability_requirement_registry()
        row = next(row for row in registry[collection] if row["id"] == requirement_id)
        row[field] = value

        validation = validate_livability_requirement_registry(registry)

        assert validation["valid"] is False
        assert expected_error in validation["errors"]


def test_route_filtered_view_is_deep_copy_isolated():
    registry = build_livability_requirement_registry()
    coverage = requirement_coverage_for_route(registry, "economy_investment")
    filtered_demand = next(
        row for row in coverage["customer_ai_demands"] if row["id"] == "23"
    )
    original_demand = next(
        row for row in registry["customer_ai_demands"] if row["id"] == "23"
    )

    filtered_demand["production_blockers"].append("mutated_blocker")
    coverage["claim_boundary"]["registration_is_not_implementation"] = False

    assert "mutated_blocker" not in original_demand["production_blockers"]
    assert registry["claim_boundary"]["registration_is_not_implementation"] is True


def test_route_filter_rejects_unknown_route():
    registry = build_livability_requirement_registry()

    try:
        requirement_coverage_for_route(registry, "not_a_route")
    except ValueError as exc:
        assert "not_a_route" in str(exc)
    else:
        raise AssertionError("unknown routes must be rejected")


def test_registry_evidence_fields_use_controlled_enums():
    registry = build_livability_requirement_registry()
    rows = registry["livability_scenarios"] + registry["customer_ai_demands"]

    assert {"observed", "proxy", "simulated", "contract_only", "unsupported"} <= EVIDENCE_LEVELS
    assert all(row["evidence_level"] in EVIDENCE_LEVELS for row in rows)
    assert all(row["uncertainty"] in UNCERTAINTY_LEVELS for row in rows)
    assert all(row["max_claim_level"] in MAX_CLAIM_LEVELS for row in rows)
