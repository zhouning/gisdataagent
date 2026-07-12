from pathlib import Path

from data_agent.uwm.ai_demand_implementation_ledger import (
    IMPLEMENTATION_STATUSES,
    build_ai_demand_implementation_ledger,
)
from data_agent.uwm.livability_requirement_registry import build_livability_requirement_registry


ROOT = Path(__file__).resolve().parents[1]


def rows_by_id(rows):
    return {row["id"]: row for row in rows}


def test_ledger_defines_non_overlapping_real_implementation_statuses():
    assert IMPLEMENTATION_STATUSES == {
        "production_verified",
        "implemented_evidence_bounded",
        "data_query_only",
        "contract_only",
        "not_implemented",
    }


def test_ledger_preserves_canonical_ownership_and_adds_evidence_overlay():
    registry = build_livability_requirement_registry()
    ledger = build_ai_demand_implementation_ledger(repo_root=ROOT, registry=registry)

    canonical = rows_by_id(registry["customer_ai_demands"])
    actual = rows_by_id(ledger["customer_ai_demands"])
    assert set(actual) == set(canonical)
    for demand_id, row in actual.items():
        assert row["primary_route"] == canonical[demand_id]["primary_route"]
        assert row["required_method"] == canonical[demand_id]["required_method"]
        assert row["implementation_status"] in IMPLEMENTATION_STATUSES
        assert row["status_basis"]
        assert isinstance(row["evidence_artifacts"], list)
        assert isinstance(row["next_actions"], list)


def test_livability_scenarios_reflect_verified_products_without_claiming_full_customer_completion():
    ledger = build_ai_demand_implementation_ledger(repo_root=ROOT)
    scenarios = rows_by_id(ledger["livability_scenarios"])

    assert scenarios["S1"]["implementation_status"] == "implemented_evidence_bounded"
    assert scenarios["S2"]["implementation_status"] == "production_verified"
    assert scenarios["S4"]["implementation_status"] == "implemented_evidence_bounded"
    assert scenarios["S6"]["implementation_status"] == "production_verified"
    assert scenarios["S7"]["implementation_status"] == "implemented_evidence_bounded"
    assert "need_unresolved" in scenarios["S7"]["production_blockers"]


def test_demand_11_is_real_kernel_but_closed_action_effect_is_visible():
    ledger = build_ai_demand_implementation_ledger(repo_root=ROOT)
    demands = rows_by_id(ledger["customer_ai_demands"])
    demand = demands["11"]

    assert demand["implementation_status"] == "implemented_evidence_bounded"
    assert "environmental_kernel" in " ".join(demand["implemented_outputs"])
    assert "environmental_action_response_closed" in demand["production_blockers"]
    assert demand["max_supported_claim"] == "observed_environmental_state_and_calibrated_pm25_temporal_dynamics"


def test_non_livability_demands_are_not_promoted_by_generic_platform_capabilities():
    ledger = build_ai_demand_implementation_ledger(repo_root=ROOT)
    demands = rows_by_id(ledger["customer_ai_demands"])

    assert demands["1"]["implementation_status"] == "data_query_only"
    assert demands["4"]["implementation_status"] == "data_query_only"
    assert demands["19"]["implementation_status"] == "contract_only"
    assert demands["23"]["implementation_status"] == "contract_only"
    assert demands["24"]["implementation_status"] == "implemented_evidence_bounded"
    assert demands["24"]["max_supported_claim"] == "cross_domain_evidence_compatibility_priority_and_dynamic_channel_readiness"
    assert demands["25"]["implementation_status"] == "implemented_evidence_bounded"
    assert demands["25"]["max_supported_claim"] == "evidence_dependency_and_verification_gated_implementation_roadmap"


def test_demand8_is_verified_but_remains_evidence_bounded():
    ledger = build_ai_demand_implementation_ledger(repo_root=ROOT)
    demand = rows_by_id(ledger["customer_ai_demands"])["8"]

    assert demand["implementation_status"] == "implemented_evidence_bounded"
    assert "traditional_mobility_accessibility_product" in demand["implemented_outputs"]
    assert demand["max_supported_claim"] == "administrative_service_accessibility_and_network_proxy_gap_diagnostic"
    for blocker in ["public_transport_missing", "road_safety_missing", "shaded_routes_missing", "universal_accessibility_missing", "cycling_routes_missing", "parking_pressure_missing", "pedestrian_crossings_missing"]:
        assert blocker in demand["production_blockers"]


def test_ledger_summary_counts_all_thirty_requirements():
    ledger = build_ai_demand_implementation_ledger(repo_root=ROOT)
    assert sum(ledger["summary"]["implementation_status_counts"].values()) == 30
    assert ledger["summary"]["verified_or_bounded_count"] > 0
    assert ledger["claim_boundary"]["product_presence_is_not_full_requirement_completion"] is True

def test_demands12_and21_use_verified_shared_product_with_distinct_boundaries():
    demands=rows_by_id(build_ai_demand_implementation_ledger(repo_root=ROOT)['customer_ai_demands'])
    d12,d21=demands['12'],demands['21']
    assert d12['implementation_status']=='implemented_evidence_bounded'
    assert d21['implementation_status']=='implemented_evidence_bounded'
    assert 'traditional_social_public_service_product' in d12['implemented_outputs']
    assert 'traditional_social_public_service_product' in d21['implemented_outputs']
    assert d12['max_supported_claim']=='social_infrastructure_inventory_and_relative_evidence_gap'
    assert d21['max_supported_claim']=='government_public_service_inventory_and_relative_evidence_gap'
    for demand in (d12,d21):
        assert 'township_accessibility_not_joined_to_county_facilities' in demand['production_blockers']
        assert all(check['exists'] for check in demand['evidence_artifact_checks'])

def test_demand9_uses_verified_public_space_product_but_keeps_quality_channels_closed():
 demand=rows_by_id(build_ai_demand_implementation_ledger(repo_root=ROOT)['customer_ai_demands'])['9']
 assert demand['implementation_status']=='implemented_evidence_bounded'
 assert 'traditional_public_space_product' in demand['implemented_outputs']
 assert demand['max_supported_claim']=='public_space_inventory_distribution_and_relative_evidence_gap'
 for blocker in ['public_access_and_opening_hours_missing','quality_vitality_and_actual_use_missing','shade_seating_furniture_missing','waterfront_accessibility_missing','safety_and_universal_accessibility_missing','intervention_effect_evidence_missing']:
  assert blocker in demand['production_blockers']
 assert all(x['exists'] for x in demand['evidence_artifact_checks'])

def test_demand10_uses_verified_evidence_product_without_safety_outcome_claims():
 demand=rows_by_id(build_ai_demand_implementation_ledger(repo_root=ROOT)['customer_ai_demands'])['10']
 assert demand['implementation_status']=='implemented_evidence_bounded'
 assert 'traditional_safety_comfort_evidence_product' in demand['implemented_outputs']
 assert demand['max_supported_claim']=='mobility_environment_context_and_safety_comfort_evidence_readiness'
 for blocker in ['crash_conflict_observations_missing','crime_security_observations_missing','lighting_crossing_data_missing','shade_corridor_data_missing','universal_accessibility_assets_missing','observed_thermal_comfort_missing','emergency_response_time_missing','intervention_effect_evidence_missing']:
  assert blocker in demand['production_blockers']
 assert all(x['exists'] for x in demand['evidence_artifact_checks'])

def test_demand14_uses_verified_daily_convenience_product_without_economic_claims():
 demand=rows_by_id(build_ai_demand_implementation_ledger(repo_root=ROOT)['customer_ai_demands'])['14']
 assert demand['implementation_status']=='implemented_evidence_bounded'
 assert 'traditional_daily_convenience_business_evidence_product' in demand['implemented_outputs']
 assert demand['max_supported_claim']=='daily_service_inventory_accessibility_context_and_business_activity_evidence'
 for blocker in ['business_operation_and_opening_hours_missing','business_licence_missing','employment_data_missing','revenue_transactions_visits_missing','market_demand_missing','entrepreneurship_evidence_missing','causal_activation_effect_missing']:
  assert blocker in demand['production_blockers']
 assert all(x['exists'] for x in demand['evidence_artifact_checks'])
