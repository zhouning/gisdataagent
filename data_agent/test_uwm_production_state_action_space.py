import json
from pathlib import Path

from data_agent.uwm.production_state_action_space import (
    UWM_PRODUCTION_STATE_ACTION_SPACE_ASSESSMENT_SCHEMA,
    build_uwm_production_state_action_space_assessment,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
ARTIFACT_PATH = (
    DATA_ROOT
    / "production_state_action_space_assessment_2026_07_08/uwm_production_state_action_space_assessment.json"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_assessment() -> dict:
    return build_uwm_production_state_action_space_assessment(
        assessment_id="uwm-production-state-action-space-assessment-test",
        created_at="2026-07-08T22:30:00Z",
        data_foundation_evidence_gate=_read_json(
            DATA_ROOT
            / "data_foundation_evidence_gate_2026_07_05/uwm_data_foundation_evidence_gate.json"
        ),
        full_admin_action_inventory=_read_json(
            DATA_ROOT
            / "full_admin_action_inventory_2026_07_08/uwm_full_admin_action_inventory.json"
        ),
        full_admin_livability_decision_package=_read_json(
            DATA_ROOT
            / "full_admin_livability_decision_package_2026_07_08/uwm_full_admin_livability_decision_package.json"
        ),
    )


def test_production_state_action_space_assessment_exposes_current_scope_and_gaps():
    assessment = _build_assessment()

    assert assessment["schema"] == UWM_PRODUCTION_STATE_ACTION_SPACE_ASSESSMENT_SCHEMA
    assert assessment["experiment_scope"] == "full_admin_graph"
    assert assessment["production_readiness_claim"] is False
    assert assessment["observed_policy_outcome_superiority_claim"] is False
    assert assessment["empirical_superiority_claim"] is False

    current = assessment["current_implemented_scope"]
    assert current["graph_node_count"] == 1017
    assert current["graph_edge_count"] == 7932
    assert current["admin_boundary_edge_count"] == 2847
    assert current["geographic_similarity_edge_count"] == 5085
    assert current["available_action_count"] == 1137
    assert current["raw_candidate_action_count"] == 3051
    assert current["source_poi_point_count"] == 1194351
    assert current["source_road_count"] == 50366
    assert current["source_building_record_count"] == 107452
    assert current["source_unicom_commuting_row_count"] == 2120
    assert current["core_node_state_variables"] == [
        "heat_risk",
        "air_pollution_exposure",
        "service_accessibility",
        "equity",
        "livability",
    ]

    state_layers = {
        layer["layer_id"]: layer for layer in assessment["production_state_layers"]
    }
    assert set(state_layers) == {
        "spatial_objects",
        "environmental_exposure",
        "service_accessibility",
        "population_equity",
        "urban_form_activity",
        "governance_constraints",
        "temporal_policy_outcomes",
    }
    assert state_layers["spatial_objects"]["current_coverage_level"] == (
        "full_admin_graph_plus_local_assets_not_multiscale_state_graph"
    )
    assert state_layers["service_accessibility"]["current_evidence_counts"][
        "poi_points"
    ] == 1194351
    assert state_layers["service_accessibility"]["current_evidence_counts"][
        "roads"
    ] == 50366
    assert state_layers["governance_constraints"]["production_blocking_gap"] is True
    assert (
        "legal_feasibility_and_cost_constraints_required"
        in state_layers["governance_constraints"]["missing_for_production"]
    )
    assert (
        "observed_intervention_outcome_panel_required"
        in state_layers["temporal_policy_outcomes"]["missing_for_production"]
    )

    action_space = assessment["current_action_space"]
    assert action_space["implemented_action_type_count"] == 3
    assert action_space["implemented_feasible_action_count"] == 1137
    assert action_space["raw_candidate_action_count"] == 3051
    assert action_space["action_type_counts"] == {
        "increase_green_infrastructure": 81,
        "traffic_emission_control": 77,
        "add_community_service": 979,
    }
    assert action_space["parameterized_action_claim"] is False
    assert action_space["historical_policy_log_claim"] is False

    action_families = {
        family["family_id"]: family
        for family in assessment["production_action_families"]
    }
    assert len(action_families) == 8
    assert action_families["blue_green_heat_mitigation"]["implemented_action_types"] == [
        "increase_green_infrastructure"
    ]
    assert "cool_roof_retrofit" in action_families[
        "blue_green_heat_mitigation"
    ]["required_action_types"]
    assert action_families["mobility_accessibility"]["implemented_action_types"] == []
    assert action_families["planning_controls"]["implemented_action_types"] == []
    assert assessment["production_action_type_target_count"] >= 30
    assert assessment["implemented_action_family_count"] == 3
    assert assessment["missing_action_family_count"] == 5
    assert assessment["action_space_expansion_factor_vs_current_types"] >= 10

    assert assessment["production_gap_summary"]["state_space_blocking_gap_count"] >= 4
    assert assessment["production_gap_summary"]["action_space_blocking_gap_count"] >= 5
    assert "parameterized_action_catalog_required" in assessment[
        "next_required_artifacts"
    ]
    assert "policy_project_history_schema_required" in assessment[
        "next_required_artifacts"
    ]
    assert "constraint_and_cost_model_required" in assessment[
        "next_required_artifacts"
    ]
    assert "causal_effect_calibration_layer_required" in assessment[
        "next_required_artifacts"
    ]


def test_production_state_action_space_assessment_artifact_is_rebuilt_from_real_scope():
    assessment = _read_json(ARTIFACT_PATH)

    assert assessment["schema"] == UWM_PRODUCTION_STATE_ACTION_SPACE_ASSESSMENT_SCHEMA
    assert assessment["current_implemented_scope"]["graph_node_count"] == 1017
    assert assessment["current_action_space"]["implemented_feasible_action_count"] == 1137
    assert assessment["production_readiness_claim"] is False
    assert assessment["claim_boundary"]["max_claim_level"] == "gap_analysis_only"
