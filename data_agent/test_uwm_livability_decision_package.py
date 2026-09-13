import json
from pathlib import Path

from data_agent.uwm.data_foundation_evidence_gate import (
    build_uwm_data_foundation_evidence_gate,
)
from data_agent.uwm.livability_decision_package import (
    UWM_LIVABILITY_DECISION_PACKAGE_SCHEMA,
    build_uwm_livability_decision_package,
)
from data_agent.uwm.spatial_spillover_kernel import (
    build_uwm_data_calibrated_spatial_spillover_kernel,
)
from data_agent.uwm.world_model_evidence_readiness import (
    build_world_model_evidence_readiness,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_package() -> dict:
    return build_uwm_livability_decision_package(
        package_id="uwm-livability-decision-package-real-data-test",
        created_at="2026-07-07T13:30:00Z",
        data_calibrated_planner_replay=_read_json(
            DATA_ROOT
            / "data_calibrated_planner_replay_2026_07_06/uwm_data_calibrated_model_based_graph_search.json"
        ),
        livability_endpoint_suite=_read_json(
            DATA_ROOT
            / "livability_endpoint_suite_2026_07_07/uwm_livability_endpoint_suite.json"
        ),
        endpoint_aligned_planner_evaluator=_read_json(
            DATA_ROOT
            / "endpoint_aligned_planner_evaluator_2026_07_07/uwm_endpoint_aligned_planner_evaluator.json"
        ),
        spatial_spillover_planner_evaluator=_read_json(
            DATA_ROOT
            / "spatial_spillover_planner_evaluator_2026_07_07/uwm_spatial_spillover_planner_evaluator.json"
        ),
        spatial_spillover_kernel=_build_spatial_kernel(),
        rl_training_report=_read_json(
            DATA_ROOT
            / "livability_rl_training_2026_07_07/uwm_livability_rl_training_report.json"
        ),
        graph_drl_training_report=_read_json(
            DATA_ROOT
            / "livability_graph_drl_training_2026_07_07/uwm_livability_graph_drl_training_report.json"
        ),
    )


def _build_spatial_kernel() -> dict:
    return build_uwm_data_calibrated_spatial_spillover_kernel(
        admin_spatial_graph=_read_json(
            DATA_ROOT
            / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
        ),
        admin_livability_panel=_read_json(
            DATA_ROOT
            / "admin_livability_target_2024_07_2026_07_05/uwm_admin_livability_target_panel.json"
        ),
        kernel_id="uwm-data-calibrated-spatial-spillover-kernel-decision-test",
        created_at="2026-07-07T18:30:00Z",
    )


def test_livability_decision_package_collects_final_real_data_decision_evidence():
    package = _build_package()

    assert package["schema"] == UWM_LIVABILITY_DECISION_PACKAGE_SCHEMA
    assert package["decision_package_ready"] is True
    assert package["supported_claim"] == (
        "uwm_livability_decision_package_beats_static_heuristic_on_validated_endpoints_spillover_and_risk"
    )
    assert package["action_portfolio"]["action_count"] == 2
    assert package["action_portfolio"]["target_units"] == [
        "江北区|观音桥街道|653",
        "九龙坡区|九龙镇|77",
    ]

    comparison = package["comparison_against_traditional_static_heuristic"]
    assert comparison["endpoint_aligned_advantage_over_static"] == 0.0007457
    assert comparison["endpoint_aligned_advantage_ratio"] == 2.127273
    assert comparison["risk_adjusted_advantage_over_static"] == 0.012777213
    assert comparison["neighbor_livability_delta_advantage"] == 0.272680076
    assert comparison["planner_benefited_unit_count"] == 13
    assert comparison["static_benefited_unit_count"] == 6
    assert comparison["planner_positive_livability_delta_sum"] == 0.759608782
    assert comparison["static_positive_livability_delta_sum"] == 0.357081051
    assert comparison["planner_positive_equity_delta_sum"] == 0.293802795
    assert comparison["static_positive_equity_delta_sum"] == 0.138112425

    replay_baselines = package["replay_baseline_suite"]
    assert replay_baselines["single_action_transition_count"] == 355
    assert replay_baselines["best_sequence_reward"] == 0.017180838
    assert replay_baselines["best_single_action_reward"] == 0.013343692
    assert replay_baselines["advantage_vs_best_single_action"] == 0.003837146
    assert replay_baselines["single_action_win_rate"] == 1.0
    assert replay_baselines["best_sequence_percentile_vs_single_actions"] == 1.0
    assert replay_baselines["empirical_one_sided_p_value"] == 0.002809
    assert replay_baselines["mean_single_action_reward"] == 0.006456155
    assert replay_baselines["median_single_action_reward"] == 0.006948566

    sensitivity = package["endpoint_weight_sensitivity"]
    assert sensitivity["profile_count"] == 5
    assert sensitivity["all_profiles_advantage_positive"] is True
    assert sensitivity["min_advantage_over_static"] == 0.0007457
    assert sensitivity["profiles"]["equal_weights"]["advantage_over_static"] == 0.010914153
    assert sensitivity["profiles"]["air_only"]["advantage_over_static"] == 0.006684375
    assert sensitivity["profiles"]["service_point_only"]["advantage_over_static"] == 0.002114889

    endpoint_evidence = package["validated_endpoint_evidence"]
    assert endpoint_evidence["building_floor_morphology_projected"] is True
    assert endpoint_evidence["mean_relative_mae_reduction_vs_best_traditional"] == 0.115337
    assert package["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert package["observed_policy_outcome_superiority_claim"] is False
    assert package["empirical_superiority_claim"] is False

    rl_evidence = package["rl_training_evidence"]
    assert rl_evidence["ready"] is True
    assert rl_evidence["algorithm"] == "dyna_q_tabular_model_based_rl"
    assert rl_evidence["episode_count"] == 160
    assert rl_evidence["real_data_graph_node_count"] == 36
    assert rl_evidence["available_action_count"] == 60
    assert rl_evidence["spatial_spillover_directional_edge_count"] == 227
    assert rl_evidence["advantage_over_traditional_static"] > 0
    assert rl_evidence["observed_policy_outcome_superiority_claim"] is False
    assert "trained_model_based_rl_policy" in package["final_outputs"]["decision_basis"]

    graph_drl = package["graph_drl_training_evidence"]
    assert graph_drl["ready"] is True
    assert graph_drl["algorithm"] == "graph_dqn_fitted_q_model_based_rl"
    assert graph_drl["is_deep_rl"] is True
    assert graph_drl["uses_graph_message_passing"] is True
    assert graph_drl["policy_or_value_network_trained"] is True
    assert graph_drl["advantage_over_traditional_static"] > 0
    assert graph_drl["observed_policy_outcome_superiority_claim"] is False
    assert "trained_graph_dqn_value_network" in package["final_outputs"][
        "decision_basis"
    ]


def test_livability_decision_package_exposes_data_calibrated_spatial_kernel_evidence():
    kernel = _build_spatial_kernel()
    package = build_uwm_livability_decision_package(
        package_id="uwm-livability-decision-package-spatial-kernel-test",
        created_at="2026-07-07T18:35:00Z",
        data_calibrated_planner_replay=_read_json(
            DATA_ROOT
            / "data_calibrated_planner_replay_2026_07_06/uwm_data_calibrated_model_based_graph_search.json"
        ),
        livability_endpoint_suite=_read_json(
            DATA_ROOT
            / "livability_endpoint_suite_2026_07_07/uwm_livability_endpoint_suite.json"
        ),
        endpoint_aligned_planner_evaluator=_read_json(
            DATA_ROOT
            / "endpoint_aligned_planner_evaluator_2026_07_07/uwm_endpoint_aligned_planner_evaluator.json"
        ),
        spatial_spillover_planner_evaluator=_read_json(
            DATA_ROOT
            / "spatial_spillover_planner_evaluator_2026_07_07/uwm_spatial_spillover_planner_evaluator.json"
        ),
        spatial_spillover_kernel=kernel,
        rl_training_report=_read_json(
            DATA_ROOT
            / "livability_rl_training_2026_07_07/uwm_livability_rl_training_report.json"
        ),
        graph_drl_training_report=_read_json(
            DATA_ROOT
            / "livability_graph_drl_training_2026_07_07/uwm_livability_graph_drl_training_report.json"
        ),
    )

    evidence = package["spatial_spillover_kernel_evidence"]
    assert evidence["kernel_id"] == kernel["kernel_id"]
    assert evidence["ready"] is True
    assert evidence["directional_edge_count"] == kernel["summary"]["directional_edge_count"]
    assert evidence["max_spillover_factor"] == kernel["summary"]["max_spillover_factor"]
    assert evidence["uses_shared_boundary_length"] is True
    assert evidence["uses_admin_livability_need"] is True
    assert evidence["observed_policy_outcome_superiority_claim"] is False
    assert "data_calibrated_spatial_spillover_kernel" in package["final_outputs"][
        "decision_basis"
    ]


def test_evidence_gate_and_readiness_track_final_livability_decision_package(
    tmp_path: Path,
):
    package = _build_package()
    package_path = tmp_path / "uwm_livability_decision_package.json"
    package_path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")

    gate = build_uwm_data_foundation_evidence_gate(
        manifest_path=ROOT / "docs/reports/uwm_data_foundation_manifest.csv",
        openaq_temporal_benchmark_path=DATA_ROOT
        / "openaq_temporal_benchmark_2018_10/uwm_openaq_observed_temporal_benchmark.json",
        tap_external_dynamics_path=DATA_ROOT
        / "tap_pm25_external_dynamics_2026_07_06/tap_external_dynamics_report.json",
        learned_rollout_path=DATA_ROOT
        / "model_based_rl_graph_search_2026_07_05/uwm_offline_world_model_rollout_planner_admin_livability_spatial_graph_proxy.json",
        livability_intervention_package_path=DATA_ROOT
        / "model_based_rl_graph_search_2026_07_05/uwm_livability_intervention_package_admin_livability_spatial_graph.json",
        local_planning_inventory_path=DATA_ROOT
        / "local_planning_zip_audit_2026_07_05/uwm_local_planning_zip_inventory.csv",
        admin_spatial_graph_path=DATA_ROOT
        / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json",
        livability_decision_package_path=package_path,
        livability_rl_training_report_path=DATA_ROOT
        / "livability_rl_training_2026_07_07/uwm_livability_rl_training_report.json",
        livability_graph_drl_training_report_path=DATA_ROOT
        / "livability_graph_drl_training_2026_07_07/uwm_livability_graph_drl_training_report.json",
        gate_id="uwm-data-foundation-evidence-gate-livability-decision-test",
        created_at="2026-07-07T13:45:00Z",
    )

    decision_slice = gate["evidence_slices"]["livability_decision_package"]
    assert decision_slice["source_artifact_exists"] is True
    assert decision_slice["livability_decision_package_ready"] is True
    assert decision_slice["action_count"] == 2
    assert decision_slice["target_unit_count"] == 2
    assert decision_slice["endpoint_aligned_advantage_over_static"] == 0.0007457
    assert decision_slice["advantage_vs_best_single_action"] == 0.003837146
    assert decision_slice["empirical_p_value_vs_single_action_baselines"] == 0.002809
    assert decision_slice["endpoint_weight_sensitivity_profile_count"] == 5
    assert decision_slice["endpoint_weight_sensitivity_min_advantage"] == 0.0007457
    assert decision_slice["risk_adjusted_advantage_over_static"] == 0.012777213
    assert decision_slice["neighbor_livability_delta_advantage"] == 0.272680076
    assert decision_slice["spatial_spillover_kernel_ready"] is True
    assert decision_slice["spatial_spillover_kernel_directional_edge_count"] == 227
    assert decision_slice["spatial_spillover_kernel_uses_shared_boundary_length"] is True
    assert decision_slice["rl_training_ready"] is True
    assert decision_slice["rl_training_advantage_over_traditional_static"] > 0
    assert decision_slice["graph_drl_training_ready"] is True
    assert decision_slice["graph_drl_algorithm"] == "graph_dqn_fitted_q_model_based_rl"
    assert decision_slice["graph_drl_training_sample_count"] == 3600
    assert decision_slice["graph_policy_or_value_network_trained"] is True
    assert decision_slice["graph_drl_advantage_over_traditional_static"] > 0
    assert decision_slice["observed_policy_outcome_superiority_claim"] is False
    rl_slice = gate["evidence_slices"]["livability_rl_training"]
    assert rl_slice["livability_rl_training_ready"] is True
    assert rl_slice["algorithm"] == "dyna_q_tabular_model_based_rl"
    assert rl_slice["episode_count"] == 160
    assert rl_slice["advantage_over_traditional_static"] > 0
    assert rl_slice["policy_or_value_network_trained"] is False
    graph_drl_slice = gate["evidence_slices"]["livability_graph_drl_training"]
    assert graph_drl_slice["livability_graph_drl_training_ready"] is True
    assert graph_drl_slice["algorithm"] == "graph_dqn_fitted_q_model_based_rl"
    assert graph_drl_slice["is_deep_rl"] is True
    assert graph_drl_slice["uses_graph_message_passing"] is True
    assert graph_drl_slice["policy_or_value_network_trained"] is True
    assert graph_drl_slice["training_sample_count"] == 3600
    assert graph_drl_slice["q_return_mae"] < graph_drl_slice["train_mean_return_mae"]
    assert graph_drl_slice["advantage_over_traditional_static"] > 0
    assert package["supported_claim"] in {
        claim["claim"] for claim in gate["supported_claims"]
    }
    assert "trained_model_based_q_agent_improves_same_scene_static_livability_baseline" in {
        claim["claim"] for claim in gate["supported_claims"]
    }

    readiness = build_world_model_evidence_readiness(gate)
    final_decision = readiness["architecture_evidence"][
        "final_livability_decision_package"
    ]
    assert final_decision["ready"] is True
    assert final_decision["action_count"] == 2
    assert final_decision["target_unit_count"] == 2
    assert final_decision["endpoint_aligned_advantage_over_static"] == 0.0007457
    assert final_decision["advantage_vs_best_single_action"] == 0.003837146
    assert final_decision["empirical_p_value_vs_single_action_baselines"] == 0.002809
    assert final_decision["endpoint_weight_sensitivity_profile_count"] == 5
    assert final_decision["endpoint_weight_sensitivity_min_advantage"] == 0.0007457
    assert final_decision["spatial_spillover_kernel_ready"] is True
    assert final_decision["spatial_spillover_kernel_directional_edge_count"] == 227
    assert final_decision["rl_training_ready"] is True
    assert final_decision["rl_training_advantage_over_traditional_static"] > 0
    assert final_decision["graph_drl_training_ready"] is True
    assert final_decision["graph_drl_algorithm"] == "graph_dqn_fitted_q_model_based_rl"
    assert final_decision["graph_drl_training_sample_count"] == 3600
    assert final_decision["graph_policy_or_value_network_trained"] is True
    assert final_decision["graph_drl_advantage_over_traditional_static"] > 0
    rl_training = readiness["architecture_evidence"]["rl_training"]
    assert rl_training["ready"] is True
    assert rl_training["algorithm"] == "dyna_q_tabular_model_based_rl"
    assert rl_training["policy_or_value_network_trained"] is False
    graph_drl_training = readiness["architecture_evidence"]["graph_drl_training"]
    assert graph_drl_training["ready"] is True
    assert graph_drl_training["algorithm"] == "graph_dqn_fitted_q_model_based_rl"
    assert graph_drl_training["is_deep_rl"] is True
    assert graph_drl_training["policy_or_value_network_trained"] is True
    assert readiness["policy_outcome_superiority_ready"] is False
