import json
from pathlib import Path

from data_agent.uwm.production_action_catalog import (
    UWM_PRODUCTION_ACTION_CATALOG_SCHEMA,
    build_uwm_production_action_catalog,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
ARTIFACT_PATH = (
    DATA_ROOT
    / "production_action_catalog_2026_07_08/uwm_production_action_catalog.json"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_catalog() -> dict:
    return build_uwm_production_action_catalog(
        catalog_id="uwm-production-action-catalog-test",
        created_at="2026-07-08T23:40:00Z",
        production_state_action_space_assessment=_read_json(
            DATA_ROOT
            / "production_state_action_space_assessment_2026_07_08/uwm_production_state_action_space_assessment.json"
        ),
        full_admin_action_inventory=_read_json(
            DATA_ROOT
            / "full_admin_action_inventory_2026_07_08/uwm_full_admin_action_inventory.json"
        ),
    )


def test_production_action_catalog_defines_extendable_action_contracts():
    catalog = _build_catalog()

    assert catalog["schema"] == UWM_PRODUCTION_ACTION_CATALOG_SCHEMA
    assert catalog["experiment_scope"] == "full_admin_graph"
    assert catalog["action_catalog_contract_ready"] is True
    assert catalog["future_authoritative_data_extension_ready"] is True
    assert catalog["planner_production_action_ready"] is False
    assert catalog["policy_project_history_ready"] is False
    assert catalog["constraint_cost_model_ready"] is False
    assert catalog["observed_policy_outcome_panel_ready"] is False
    assert catalog["production_readiness_claim"] is False
    assert catalog["observed_policy_outcome_superiority_claim"] is False
    assert catalog["empirical_superiority_claim"] is False

    summary = catalog["summary"]
    assert summary["production_action_family_count"] == 8
    assert summary["production_action_type_count"] == 57
    assert summary["currently_bound_action_type_count"] == 3
    assert summary["currently_bound_feasible_action_count"] == 1137
    assert summary["unbound_production_action_type_count"] == 54
    assert summary["raw_candidate_action_count"] == 3051
    assert summary["current_feasible_action_counts"] == {
        "increase_green_infrastructure": 81,
        "traffic_emission_control": 77,
        "add_community_service": 979,
    }

    assert catalog["required_parameter_fields"] == [
        "target_geometry",
        "intensity",
        "capacity_change",
        "budget_cost",
        "implementation_time",
        "maintenance_cost",
        "responsible_department",
        "legal_feasibility",
        "land_constraint",
        "population_served",
        "expected_mechanism",
        "uncertainty",
        "evidence_level",
    ]
    assert catalog["required_evidence_layers"] == [
        "state_variable_support",
        "constraint_cost_model",
        "historical_policy_project_log",
        "observed_outcome_panel",
        "causal_effect_calibration",
        "human_governance_review",
    ]

    contracts = {
        contract["action_type"]: contract
        for contract in catalog["action_type_contracts"]
    }
    assert len(contracts) == 57
    assert contracts["increase_green_infrastructure"]["current_binding_status"] == (
        "implemented_bounded_support"
    )
    assert contracts["increase_green_infrastructure"][
        "current_feasible_action_count"
    ] == 81
    assert contracts["increase_green_infrastructure"]["planner_binding_level"] == (
        "bounded_abstract_single_unit"
    )
    assert contracts["increase_green_infrastructure"]["existing_state_trigger"] == (
        "heat_risk >= 0.7"
    )
    assert contracts["traffic_emission_control"]["existing_state_trigger"] == (
        "air_pollution_exposure >= 0.6"
    )
    assert contracts["add_community_service"]["existing_state_trigger"] == (
        "service_accessibility <= 0.5"
    )
    assert contracts["bus_route_adjustment"]["current_binding_status"] == (
        "production_target_unbound"
    )
    assert contracts["bus_route_adjustment"]["current_feasible_action_count"] == 0
    assert "transit_authoritative_route_and_frequency_required" in contracts[
        "bus_route_adjustment"
    ]["missing_evidence_for_planner"]
    assert contracts["floor_area_ratio_control"]["current_binding_status"] == (
        "production_target_unbound"
    )
    assert "statutory_planning_control_required" in contracts[
        "floor_area_ratio_control"
    ]["missing_evidence_for_planner"]

    bindings = catalog["current_candidate_bindings"]
    assert len(bindings) == 1137
    assert bindings[0] == {
        "source_action_id": "increase_green_infrastructure-涪陵区|蔺市镇|498",
        "action_type": "increase_green_infrastructure",
        "target_unit_id": "涪陵区|蔺市镇|498",
        "target_geometry_level": "admin_unit",
        "intensity": 1.0,
        "catalog_binding_status": "implemented_bounded_support",
        "planner_binding_level": "bounded_abstract_single_unit",
        "evidence_level": "full_admin_graph_mdp_threshold_mask",
    }

    ingestion = catalog["future_data_ingestion_contract"]
    assert ingestion["schema_evolution_rule"] == "versioned_additive_no_rewrite"
    assert set(ingestion["adapter_slots"]) == {
        "authoritative_state_layer_adapter",
        "planning_constraint_adapter",
        "budget_cost_adapter",
        "policy_project_history_adapter",
        "observed_outcome_panel_adapter",
        "causal_effect_calibration_adapter",
    }
    assert "validate_action_contract_before_planner_binding" in ingestion[
        "planner_binding_gates"
    ]
    assert catalog["claim_boundary"]["max_claim_level"] == (
        "contract_and_current_bounded_action_binding"
    )


def test_production_action_catalog_artifact_is_rebuilt_from_full_action_inventory():
    catalog = _read_json(ARTIFACT_PATH)

    assert catalog["schema"] == UWM_PRODUCTION_ACTION_CATALOG_SCHEMA
    assert catalog["summary"]["production_action_type_count"] == 57
    assert catalog["summary"]["currently_bound_feasible_action_count"] == 1137
    assert len(catalog["current_candidate_bindings"]) == 1137
    assert catalog["production_readiness_claim"] is False
    assert catalog["observed_policy_outcome_superiority_claim"] is False
