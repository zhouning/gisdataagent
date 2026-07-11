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
    assert demands["24"]["implementation_status"] == "not_implemented"
    assert demands["25"]["implementation_status"] == "not_implemented"


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
