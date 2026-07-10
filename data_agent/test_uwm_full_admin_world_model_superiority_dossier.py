import copy
import json
from pathlib import Path

from data_agent.uwm.full_admin_world_model_superiority_dossier import (
    UWM_FULL_ADMIN_WORLD_MODEL_SUPERIORITY_DOSSIER_SCHEMA,
    build_uwm_full_admin_world_model_superiority_dossier,
    validate_uwm_full_admin_world_model_superiority_dossier,
)
from data_agent.uwm.livability_graph_drl import GRAPH_NODE_FEATURE_NAMES
from data_agent.uwm.offline_world_model_policy import FEATURE_NAMES


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
ARTIFACT_PATH = (
    DATA_ROOT
    / "full_admin_world_model_superiority_dossier_2026_07_09/uwm_full_admin_world_model_superiority_dossier.json"
)

SOURCE_PATHS = {
    "full_admin_graph_planner_replay": DATA_ROOT
    / "data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json",
    "full_admin_graph_drl_training_report": DATA_ROOT
    / "livability_graph_drl_training_full_admin_graph_2026_07_08/uwm_full_admin_graph_livability_graph_drl_training_report.json",
    "full_admin_learned_world_model_rollout": DATA_ROOT
    / "learned_world_model_rollout_full_admin_graph_2026_07_08/uwm_full_admin_graph_learned_world_model_rollout.json",
    "full_admin_energy_regularized_planner_report": DATA_ROOT
    / "energy_regularized_planner_full_admin_graph_2026_07_08/uwm_full_admin_graph_energy_regularized_planner_report.json",
    "full_admin_livability_decision_package": DATA_ROOT
    / "full_admin_livability_decision_package_2026_07_08/uwm_full_admin_livability_decision_package.json",
    "livability_endpoint_suite": DATA_ROOT
    / "livability_endpoint_suite_2026_07_07/uwm_livability_endpoint_suite.json",
    "full_admin_service_accessibility_surface": DATA_ROOT
    / "full_admin_service_accessibility_surface_2026_07_08/uwm_full_admin_service_accessibility_surface.json",
    "geographic_similarity_kernel": DATA_ROOT
    / "geographic_similarity_kernel_2026_07_08/uwm_geographic_similarity_kernel.json",
    "spatial_causal_question_registry": DATA_ROOT
    / "spatial_causal_question_registry_2026_07_09/uwm_spatial_causal_question_registry.json",
    "production_governance_planner_binding_gate": DATA_ROOT
    / "production_governance_planner_binding_gate_2026_07_08/uwm_production_governance_planner_binding_gate.json",
}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_payloads() -> dict:
    return {name: _read_json(path) for name, path in SOURCE_PATHS.items()}


def _build_dossier(**overrides) -> dict:
    payloads = _source_payloads()
    payloads.update(overrides)
    return build_uwm_full_admin_world_model_superiority_dossier(
        dossier_id="uwm-full-admin-world-model-superiority-dossier-test",
        created_at="2026-07-09T13:00:00Z",
        source_artifact_paths={
            name: str(path.relative_to(ROOT)) for name, path in SOURCE_PATHS.items()
        },
        **payloads,
    )


def test_full_admin_world_model_superiority_dossier_proves_bounded_system_advantage():
    dossier = _build_dossier()

    assert dossier["schema"] == UWM_FULL_ADMIN_WORLD_MODEL_SUPERIORITY_DOSSIER_SCHEMA
    assert dossier["experiment_scope"] == "full_admin_graph"
    assert dossier["supported_claim"] == (
        "bounded_full_admin_world_model_advantage_over_traditional_methods"
    )
    assert dossier["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert dossier["observed_policy_outcome_superiority_claim"] is False
    assert dossier["empirical_superiority_claim"] is False

    guard = dossier["full_admin_scope_guard"]
    assert guard["passed"] is True
    assert guard["graph_node_count"] == 1017
    assert guard["graph_edge_count"] == 7932
    assert guard["admin_boundary_edge_count"] == 2847
    assert guard["geographic_similarity_edge_count"] == 5085
    assert guard["available_action_count"] == 1137
    assert guard["transition_count"] == 6817
    assert guard["service_surface_admin_unit_count"] == 1017
    assert guard["local_poi_point_count"] == 1194351
    assert guard["local_road_count"] == 50366
    assert guard["service_missing_admin_count"] == 0

    endpoint = dossier["endpoint_superiority_matrix"]
    assert endpoint["endpoint_suite_ready"] is True
    assert endpoint["endpoint_count"] == 3
    assert endpoint["ready_endpoint_count"] == 3
    assert endpoint["all_endpoints_beat_best_traditional"] is True
    assert endpoint["mean_relative_mae_reduction_vs_best_traditional"] == 0.115337
    assert endpoint["min_relative_mae_reduction_vs_best_traditional"] == 0.003047
    assert {row["endpoint_id"] for row in endpoint["endpoint_rows"]} == {
        "air_quality_pm25",
        "service_point_accessibility",
        "essential_service_accessibility",
    }
    assert all(
        row["policy_outcome_claim"] is False for row in endpoint["endpoint_rows"]
    )

    world = dossier["world_model_system_matrix"]
    assert world["all_required_world_model_advantages_positive"] is True
    assert (
        world["components"]["planner_replay"]["advantage_over_static"]
        == 0.001436437
    )
    assert (
        world["components"]["risk_adjusted_planner"]["advantage_over_static"]
        == 0.0013756
    )
    assert (
        world["components"]["graph_dqn"]["advantage_over_traditional_static"]
        > 0.0
    )
    assert (
        world["components"]["graph_dqn"]["node_feature_names"]
        == GRAPH_NODE_FEATURE_NAMES
    )
    assert "estimated_nearest_essential_travel_time_min" in world["components"][
        "graph_dqn"
    ]["node_feature_names"]
    assert (
        world["components"]["learned_rollout_static"]["advantage_over_static"]
        > 0.0
    )
    assert (
        world["components"]["learned_rollout_static"]["world_model_feature_names"]
        == FEATURE_NAMES
    )
    assert "target_travel_time_min_norm" in world["components"][
        "learned_rollout_static"
    ]["world_model_feature_names"]
    assert (
        world["components"]["learned_rollout_one_step"][
            "advantage_over_one_step_policy"
        ]
        > 0.0
    )
    assert (
        world["components"]["energy_regularized_planner"][
            "advantage_over_traditional_static"
        ]
        == 0.001073357
    )
    assert world["components"]["full_admin_decision_package"]["ready"] is True

    baselines = dossier["traditional_baseline_matrix"]
    assert baselines["baseline_family_count"] >= 5
    assert "final_endpoint_best_traditional_baselines" in baselines[
        "baseline_families"
    ]
    assert "same_scene_static_heuristic" in baselines["baseline_families"]
    assert "traditional_static_graph_mdp_policy" in baselines["baseline_families"]

    causal = dossier["causal_and_governance_gate"]
    assert causal["causal_governance_gate_ready_for_bounded_claim"] is True
    assert causal["planner_candidate_causal_binding_ready"] is True
    assert causal["planner_feasible_action_count"] == 1137
    assert causal["planner_attached_action_count"] == 1137
    assert causal["planner_missing_contract_action_count"] == 0
    assert causal["planner_policy_outcome_claim_allowed_action_count"] == 0
    assert causal["final_output_causal_binding_ready"] is True
    assert causal["final_recommended_action_count"] == 6
    assert causal["production_governance_gate_ready"] is True
    assert causal["authoritative_governance_data_closure_ready"] is False
    assert causal["production_deployment_ready"] is False
    assert causal["missing_authoritative_table_count"] == 5
    assert causal["observed_policy_outcome_superiority_claim"] is False

    claim = dossier["claim_ladder"][0]
    assert claim["claim"] == (
        "bounded_full_admin_world_model_advantage_over_traditional_methods"
    )
    assert claim["claim_level"] == "bounded_support"
    assert claim["allowed_in_report"] is True
    assert claim["policy_outcome_claim"] is False

    assert "observed_policy_outcome_superiority" in dossier["forbidden_claims"]
    assert "empirical_policy_superiority" in dossier["forbidden_claims"]
    assert "observed_policy_outcome_holdout_required" in dossier["remaining_gates"]
    assert "authoritative_governance_data_closure_required" in dossier[
        "remaining_gates"
    ]

    validation = validate_uwm_full_admin_world_model_superiority_dossier(dossier)
    assert validation["valid"] is True
    assert validation["errors"] == []


def test_full_admin_world_model_superiority_dossier_rejects_smoke_sized_scope():
    payloads = _source_payloads()
    planner = copy.deepcopy(payloads["full_admin_graph_planner_replay"])
    planner["graph_mdp_state"]["graph_statistics"]["node_count"] = 36
    planner["full_data_guard"]["rendered_node_count"] = 36
    dossier = _build_dossier(full_admin_graph_planner_replay=planner)

    assert dossier["full_admin_scope_guard"]["passed"] is False
    assert dossier["supported_claim"] == (
        "no_full_admin_world_model_superiority_claim_supported"
    )
    assert dossier["claim_boundary"]["max_claim_level"] == "not_for_claim"
    assert "full_admin_scope_guard_failed" in dossier["remaining_gates"]
    assert dossier["observed_policy_outcome_superiority_claim"] is False
    assert dossier["empirical_superiority_claim"] is False

    validation = validate_uwm_full_admin_world_model_superiority_dossier(dossier)
    assert validation["valid"] is True


def test_full_admin_world_model_superiority_dossier_artifact_is_full_scope_and_claim_safe():
    assert ARTIFACT_PATH.exists()
    dossier = _read_json(ARTIFACT_PATH)

    assert dossier["schema"] == UWM_FULL_ADMIN_WORLD_MODEL_SUPERIORITY_DOSSIER_SCHEMA
    assert dossier["experiment_scope"] == "full_admin_graph"
    assert dossier["full_admin_scope_guard"]["passed"] is True
    assert dossier["full_admin_scope_guard"]["graph_node_count"] == 1017
    assert dossier["full_admin_scope_guard"]["available_action_count"] == 1137
    assert dossier["full_admin_scope_guard"]["transition_count"] == 6817
    assert dossier["full_admin_scope_guard"]["local_poi_point_count"] == 1194351
    assert (
        dossier["world_model_system_matrix"][
            "all_required_world_model_advantages_positive"
        ]
        is True
    )
    assert (
        dossier["causal_and_governance_gate"]["planner_attached_action_count"]
        == 1137
    )
    assert (
        dossier["causal_and_governance_gate"][
            "planner_policy_outcome_claim_allowed_action_count"
        ]
        == 0
    )
    assert dossier["supported_claim"] == (
        "bounded_full_admin_world_model_advantage_over_traditional_methods"
    )
    assert dossier["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert dossier["observed_policy_outcome_superiority_claim"] is False
    assert dossier["empirical_superiority_claim"] is False
    assert all(
        path.startswith("data/uwm_public_proxy/chongqing_central/")
        for path in dossier["audit_trace"]["source_artifact_paths"].values()
    )

    validation = validate_uwm_full_admin_world_model_superiority_dossier(dossier)
    assert validation["valid"] is True
    assert validation["errors"] == []
