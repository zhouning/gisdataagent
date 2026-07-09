"""Full-admin UWM livability decision package."""

from __future__ import annotations

from typing import Any

from .full_admin_service_accessibility_surface import (
    validate_full_admin_service_accessibility_surface,
)
from .full_admin_service_surface_quality import (
    validate_full_admin_service_surface_quality_audit,
)
from .geographic_similarity_kernel import validate_uwm_geographic_similarity_kernel
from .spatial_causal_question_registry import (
    validate_uwm_spatial_causal_question_registry,
)


UWM_FULL_ADMIN_LIVABILITY_DECISION_PACKAGE_SCHEMA = (
    "uwm.full_admin_livability_decision_package.v1"
)

_SUPPORTED_CLAIM = (
    "full_admin_livability_decision_package_supports_world_model_advantage_over_static_baselines"
)


def build_uwm_full_admin_livability_decision_package(
    *,
    package_id: str,
    created_at: str,
    full_admin_graph_planner_replay: dict[str, Any],
    full_admin_graph_drl_training_report: dict[str, Any],
    full_admin_learned_world_model_rollout: dict[str, Any],
    geographic_similarity_kernel: dict[str, Any],
    full_admin_service_accessibility_surface: dict[str, Any],
    full_admin_service_surface_quality_audit: dict[str, Any],
    production_governance_planner_binding_gate: dict[str, Any] | None = None,
    spatial_causal_question_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Combine full-admin renderer, simulator, planner and learned-policy evidence."""

    governance_gate = production_governance_planner_binding_gate or {}
    full_data_guard = _full_data_guard(
        full_admin_graph_planner_replay,
        full_admin_graph_drl_training_report,
        full_admin_learned_world_model_rollout,
        geographic_similarity_kernel,
        full_admin_service_accessibility_surface,
        full_admin_service_surface_quality_audit,
    )
    planner_evidence = _planner_replay_evidence(full_admin_graph_planner_replay)
    graph_dqn_evidence = _graph_dqn_training_evidence(
        full_admin_graph_drl_training_report
    )
    learned_rollout_evidence = _learned_world_model_rollout_evidence(
        full_admin_learned_world_model_rollout
    )
    similarity_evidence = _geographic_similarity_evidence(geographic_similarity_kernel)
    service_evidence = _service_accessibility_evidence(
        full_admin_service_accessibility_surface,
        full_admin_service_surface_quality_audit,
    )
    governance_evidence = _production_governance_binding_evidence(governance_gate)
    final_outputs = _final_outputs(
        planner_evidence,
        graph_dqn_evidence,
        learned_rollout_evidence,
        similarity_evidence,
        service_evidence,
        spatial_causal_question_registry or {},
    )
    spatial_causal_binding = _spatial_causal_contract_binding_evidence(
        spatial_causal_question_registry or {},
        final_outputs,
    )
    comparison = _comparison_against_traditional_static_baselines(
        planner_evidence,
        graph_dqn_evidence,
        learned_rollout_evidence,
    )
    remaining_gates = [
        "observed_policy_outcome_holdout_required",
        "off_policy_evaluation_on_real_intervention_logs_required",
        "causal_policy_effect_validation_required",
        "authoritative_service_inventory_and_trip_time_validation_required",
    ]
    if governance_evidence["planner_governance_binding_ready"] is False:
        remaining_gates.append("production_governance_planner_binding_gate_required")
    if spatial_causal_binding["binding_ready"] is False:
        remaining_gates.append("spatial_causal_question_registry_binding_required")
    ready = (
        full_data_guard["passed"] is True
        and planner_evidence["planner_replay_ready"] is True
        and graph_dqn_evidence["graph_dqn_training_ready"] is True
        and learned_rollout_evidence["learned_world_model_rollout_ready"] is True
        and similarity_evidence["geographic_similarity_kernel_ready"] is True
        and service_evidence["service_accessibility_surface_ready"] is True
        and service_evidence["service_surface_quality_audit_ready"] is True
        and spatial_causal_binding["binding_ready"] is True
        and comparison["all_world_model_advantages_positive"] is True
    )
    return {
        "schema": UWM_FULL_ADMIN_LIVABILITY_DECISION_PACKAGE_SCHEMA,
        "package_id": package_id,
        "created_at": created_at,
        "experiment_scope": "full_admin_graph",
        "full_admin_decision_package_ready": ready,
        "source_schemas": {
            "full_admin_graph_planner_replay": full_admin_graph_planner_replay.get(
                "schema"
            ),
            "full_admin_graph_drl_training_report": (
                full_admin_graph_drl_training_report.get("schema")
            ),
            "full_admin_learned_world_model_rollout": (
                full_admin_learned_world_model_rollout.get("schema")
            ),
            "geographic_similarity_kernel": geographic_similarity_kernel.get(
                "schema"
            ),
            "full_admin_service_accessibility_surface": (
                full_admin_service_accessibility_surface.get("schema")
            ),
            "full_admin_service_surface_quality_audit": (
                full_admin_service_surface_quality_audit.get("schema")
            ),
            "production_governance_planner_binding_gate": governance_gate.get(
                "schema"
            ),
            "spatial_causal_question_registry": (
                spatial_causal_question_registry or {}
            ).get("schema"),
        },
        "full_data_guard": full_data_guard,
        "service_accessibility_evidence": service_evidence,
        "geographic_similarity_evidence": similarity_evidence,
        "planner_replay_evidence": planner_evidence,
        "graph_dqn_training_evidence": graph_dqn_evidence,
        "learned_world_model_rollout_evidence": learned_rollout_evidence,
        "production_governance_binding_evidence": governance_evidence,
        "spatial_causal_contract_binding": spatial_causal_binding,
        "planner_governance_binding_ready": governance_evidence[
            "planner_governance_binding_ready"
        ],
        "comparison_against_traditional_static_baselines": comparison,
        "final_outputs": final_outputs,
        "supported_claim": _SUPPORTED_CLAIM if ready else "no_full_admin_livability_decision_package_claim_supported",
        "claim_boundary": {
            "max_claim_level": "bounded_support" if ready else "not_for_claim",
            "reason": (
                "Full-admin decision package aggregates real local full-admin graph "
                "state, service surface, geographic similarity edges, simulator "
                "planner replay, GraphDQN value training and learned rollout "
                "evidence. It supports bounded same-scene advantage over static "
                "baselines, not observed policy-outcome superiority."
            ),
        },
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "remaining_gates": remaining_gates,
    }


def _full_data_guard(
    planner: dict[str, Any],
    graph_dqn: dict[str, Any],
    learned_rollout: dict[str, Any],
    similarity_kernel: dict[str, Any],
    service_surface: dict[str, Any],
    service_quality: dict[str, Any],
) -> dict[str, Any]:
    planner_graph = (planner.get("graph_mdp_state") or {}).get("graph_statistics") or {}
    planner_guard = planner.get("full_data_guard") or {}
    planner_similarity = planner.get("source_geographic_similarity_kernel_summary") or {}
    kernel_summary = similarity_kernel.get("summary") or {}
    service_counts = service_surface.get("source_feature_counts") or {}
    service_coverage = service_surface.get("coverage") or {}
    graph_training = graph_dqn.get("training_summary") or {}
    graph_guard = graph_dqn.get("full_data_guard") or {}
    learned_training = learned_rollout.get("training_summary") or {}
    learned_guard = learned_rollout.get("full_data_guard") or {}
    passed = (
        planner.get("experiment_scope") == "full_admin_graph"
        and graph_dqn.get("experiment_scope") == "full_admin_graph"
        and learned_rollout.get("experiment_scope") == "full_admin_graph"
        and service_surface.get("experiment_scope") == "full_admin_graph"
        and service_quality.get("experiment_scope") == "full_admin_graph"
        and planner_guard.get("passed") is True
        and graph_guard.get("passed") is True
        and learned_guard.get("passed") is True
        and _int(planner_graph.get("node_count")) == 1017
        and _int(planner_graph.get("edge_count")) == 7932
        and _int(planner_guard.get("source_admin_boundary_edge_count")) == 2847
        and _int(planner_similarity.get("similarity_edge_count")) == 5085
        and _int(kernel_summary.get("similarity_edge_count")) == 5085
        and _int(planner_similarity.get("non_adjacent_similarity_edge_count")) == 4835
        and _int(kernel_summary.get("non_adjacent_similarity_edge_count")) == 4835
        and _int(planner_graph.get("available_action_count")) == 1137
        and _int((planner.get("trajectory_dataset") or {}).get("transition_count"))
        == 6817
        and _int(graph_training.get("real_data_graph_node_count")) == 1017
        and _int(graph_training.get("real_data_graph_edge_count")) == 7932
        and _int(graph_training.get("real_data_available_action_count")) == 1137
        and _int(learned_training.get("source_graph_node_count")) == 1017
        and _int(learned_training.get("source_graph_edge_count")) == 7932
        and _int(learned_training.get("source_available_action_count")) == 1137
        and _int(learned_training.get("transition_count")) == 6817
        and _int(service_surface.get("admin_unit_count")) == 1017
        and _int(service_counts.get("admin_units")) == 1017
        and _int(service_counts.get("poi_points")) == 1194351
        and _int(service_counts.get("roads")) == 50366
        and _int(service_coverage.get("service_missing_admin_count")) == 0
        and _int(service_coverage.get("admin_units_with_accessibility_score")) == 1017
    )
    return {
        "passed": passed,
        "required_scope": "full_admin_graph",
        "graph_node_count": _int(planner_graph.get("node_count")),
        "graph_edge_count": _int(planner_graph.get("edge_count")),
        "admin_boundary_edge_count": _int(
            planner_guard.get("source_admin_boundary_edge_count")
        ),
        "geographic_similarity_edge_count": _int(
            planner_similarity.get("similarity_edge_count")
        ),
        "non_adjacent_similarity_edge_count": _int(
            planner_similarity.get("non_adjacent_similarity_edge_count")
        ),
        "available_action_count": _int(planner_graph.get("available_action_count")),
        "transition_count": _int(
            (planner.get("trajectory_dataset") or {}).get("transition_count")
        ),
        "graph_dqn_node_count": _int(
            graph_training.get("real_data_graph_node_count")
        ),
        "graph_dqn_edge_count": _int(
            graph_training.get("real_data_graph_edge_count")
        ),
        "graph_dqn_available_action_count": _int(
            graph_training.get("real_data_available_action_count")
        ),
        "learned_rollout_node_count": _int(
            learned_training.get("source_graph_node_count")
        ),
        "learned_rollout_edge_count": _int(
            learned_training.get("source_graph_edge_count")
        ),
        "learned_rollout_available_action_count": _int(
            learned_training.get("source_available_action_count")
        ),
        "learned_rollout_transition_count": _int(
            learned_training.get("transition_count")
        ),
        "service_surface_admin_unit_count": _int(service_surface.get("admin_unit_count")),
        "source_poi_point_count": _int(service_counts.get("poi_points")),
        "source_road_count": _int(service_counts.get("roads")),
        "service_surface_missing_admin_count": _int(
            service_coverage.get("service_missing_admin_count")
        ),
        "service_surface_accessibility_score_count": _int(
            service_coverage.get("admin_units_with_accessibility_score")
        ),
    }


def _planner_replay_evidence(report: dict[str, Any]) -> dict[str, Any]:
    graph = (report.get("graph_mdp_state") or {}).get("graph_statistics") or {}
    best = report.get("best_sequence") or {}
    static = report.get("static_single_step_baseline") or {}
    risk = report.get("risk_adjusted_planner_evaluation") or {}
    similarity = report.get("source_geographic_similarity_kernel_summary") or {}
    actions = list(best.get("action_sequence") or [])
    target_units = _target_units(actions)
    ready = (
        report.get("schema") == "uwm.model_based_graph_search_report.v1"
        and report.get("experiment_scope") == "full_admin_graph"
        and (report.get("full_data_guard") or {}).get("passed") is True
        and _int(graph.get("node_count")) == 1017
        and _int(graph.get("edge_count")) == 7932
        and _int(similarity.get("similarity_edge_count")) == 5085
        and _int(graph.get("available_action_count")) == 1137
        and _int((report.get("trajectory_dataset") or {}).get("transition_count"))
        == 6817
        and _float(report.get("advantage_over_static_single_step")) > 0.0
        and risk.get("risk_calibrated_planner_replay_ready") is True
        and _float(risk.get("risk_adjusted_advantage_over_static_single_step")) > 0.0
        and report.get("observed_policy_outcome_superiority_claim") is False
        and report.get("empirical_superiority_claim") is False
    )
    return {
        "planner_replay_ready": ready,
        "schema": report.get("schema"),
        "experiment_scope": report.get("experiment_scope"),
        "graph_node_count": _int(graph.get("node_count")),
        "graph_edge_count": _int(graph.get("edge_count")),
        "available_action_count": _int(graph.get("available_action_count")),
        "transition_count": _int(
            (report.get("trajectory_dataset") or {}).get("transition_count")
        ),
        "transition_storage": (report.get("search_config") or {}).get(
            "transition_storage"
        ),
        "geographic_similarity_edge_count": _int(
            similarity.get("similarity_edge_count")
        ),
        "best_sequence_reward": _float(best.get("cumulative_reward")),
        "static_single_step_reward": _float(static.get("cumulative_reward")),
        "advantage_over_static_single_step": _float(
            report.get("advantage_over_static_single_step")
        ),
        "risk_adjusted_best_sequence_reward": _float(
            risk.get("best_sequence_risk_adjusted_reward")
        ),
        "risk_adjusted_static_single_step_reward": _float(
            risk.get("static_single_step_risk_adjusted_reward")
        ),
        "risk_adjusted_advantage_over_static_single_step": _float(
            risk.get("risk_adjusted_advantage_over_static_single_step")
        ),
        "action_count": len(actions),
        "action_sequence": actions,
        "target_units": target_units,
        "rollout_delta": (
            ((best.get("rollout_trace") or {}).get("future_state_delta") or {}).get(
                "aggregate"
            )
            or {}
        ),
        "supported_claim": "full_admin_graph_planner_replay_advantage_over_static_heuristic"
        if ready
        else "no_full_admin_graph_planner_replay_claim_supported",
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _graph_dqn_training_evidence(report: dict[str, Any]) -> dict[str, Any]:
    training = report.get("training_summary") or {}
    holdout = report.get("holdout_metrics") or {}
    learned = report.get("learned_policy_evaluation") or {}
    baseline = report.get("baseline_evaluation") or {}
    algorithm = report.get("drl_algorithm") or {}
    similarity = report.get("source_geographic_similarity_kernel_summary") or {}
    actions = list(learned.get("action_sequence") or [])
    ready = (
        report.get("schema") == "uwm.livability_graph_drl_training_report.v1"
        and report.get("experiment_scope") == "full_admin_graph"
        and (report.get("full_data_guard") or {}).get("passed") is True
        and algorithm.get("algorithm") == "graph_dqn_fitted_q_model_based_rl"
        and algorithm.get("is_deep_rl") is True
        and algorithm.get("is_model_based") is True
        and algorithm.get("is_model_free") is False
        and algorithm.get("uses_graph_message_passing") is True
        and algorithm.get("policy_or_value_network_trained") is True
        and _int(training.get("real_data_graph_node_count")) == 1017
        and _int(training.get("real_data_graph_edge_count")) == 7932
        and _int(training.get("real_data_available_action_count")) == 1137
        and _int(similarity.get("similarity_edge_count")) == 5085
        and _int(training.get("training_sample_count")) > 0
        and _float(holdout.get("q_return_mae"))
        < _float(holdout.get("train_mean_return_mae"))
        and _float(learned.get("advantage_over_traditional_static")) > 0.0
        and report.get("observed_policy_outcome_superiority_claim") is False
        and report.get("empirical_superiority_claim") is False
    )
    return {
        "graph_dqn_training_ready": ready,
        "schema": report.get("schema"),
        "experiment_scope": report.get("experiment_scope"),
        "algorithm": algorithm.get("algorithm"),
        "is_deep_rl": bool(algorithm.get("is_deep_rl")),
        "is_model_based": bool(algorithm.get("is_model_based")),
        "is_model_free": bool(algorithm.get("is_model_free")),
        "uses_graph_message_passing": bool(
            algorithm.get("uses_graph_message_passing")
        ),
        "policy_or_value_network_trained": bool(
            algorithm.get("policy_or_value_network_trained")
        ),
        "graph_node_count": _int(training.get("real_data_graph_node_count")),
        "graph_edge_count": _int(training.get("real_data_graph_edge_count")),
        "available_action_count": _int(
            training.get("real_data_available_action_count")
        ),
        "geographic_similarity_edge_count": _int(
            similarity.get("similarity_edge_count")
        ),
        "training_sample_count": _int(training.get("training_sample_count")),
        "train_count": _int(training.get("train_count")),
        "holdout_count": _int(training.get("holdout_count")),
        "action_sampling_strategy": training.get("action_sampling_strategy"),
        "exhaustive_action_pair_training": bool(
            training.get("exhaustive_action_pair_training")
        ),
        "sampled_first_action_count": _int(training.get("sampled_first_action_count")),
        "sampled_second_action_limit": _int(
            training.get("sampled_second_action_limit")
        ),
        "q_return_mae": _float(holdout.get("q_return_mae")),
        "train_mean_return_mae": _float(holdout.get("train_mean_return_mae")),
        "graph_dqn_policy_cumulative_reward": _float(
            learned.get("graph_dqn_policy_cumulative_reward")
        ),
        "traditional_static_cumulative_reward": _float(
            baseline.get("traditional_static_cumulative_reward")
        ),
        "advantage_over_traditional_static": _float(
            learned.get("advantage_over_traditional_static")
        ),
        "action_count": len(actions),
        "action_sequence": actions,
        "target_units": _target_units(actions),
        "policy_action_scope": learned.get("policy_action_scope"),
        "supported_claim": "full_admin_graph_dqn_value_network_improves_same_scene_static_livability_baseline"
        if ready
        else "no_full_admin_graph_dqn_claim_supported",
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _learned_world_model_rollout_evidence(report: dict[str, Any]) -> dict[str, Any]:
    training = report.get("training_summary") or {}
    holdout = report.get("holdout_metrics") or {}
    baseline = report.get("baseline_metrics") or {}
    planner = report.get("learned_rollout_planner") or {}
    selected = planner.get("selected_sequence") or {}
    actions = list(selected.get("action_sequence") or [])
    dynamics = holdout.get("dynamics_mae_by_target") or {}
    train_mean = baseline.get("train_mean_mae_by_target") or {}
    ready = (
        report.get("schema") == "uwm.offline_world_model_rollout_planner_report.v1"
        and report.get("experiment_scope") == "full_admin_graph"
        and (report.get("full_data_guard") or {}).get("passed") is True
        and _int(training.get("source_graph_node_count")) == 1017
        and _int(training.get("source_graph_edge_count")) == 7932
        and _int(training.get("source_available_action_count")) == 1137
        and _int(training.get("transition_count")) == 6817
        and _float(holdout.get("reward_mae"))
        < _float(baseline.get("train_mean_reward_mae"))
        and all(
            _float(dynamics.get(name), default=float("inf"))
            < _float(train_mean.get(name), default=0.0)
            for name in [
                "heat_risk_delta",
                "air_pollution_exposure_delta",
                "service_accessibility_delta",
                "equity_delta",
                "livability_delta",
            ]
        )
        and _float(planner.get("imagined_advantage_over_static_single_step")) > 0.0
        and _float(planner.get("imagined_advantage_over_one_step_policy")) > 0.0
        and report.get("observed_policy_outcome_superiority_claim") is False
        and report.get("empirical_superiority_claim") is False
    )
    return {
        "learned_world_model_rollout_ready": ready,
        "schema": report.get("schema"),
        "experiment_scope": report.get("experiment_scope"),
        "backend": report.get("backend"),
        "world_model_class": (report.get("world_model") or {}).get("model_class"),
        "graph_node_count": _int(training.get("source_graph_node_count")),
        "graph_edge_count": _int(training.get("source_graph_edge_count")),
        "available_action_count": _int(training.get("source_available_action_count")),
        "transition_count": _int(training.get("transition_count")),
        "train_count": _int(training.get("train_count")),
        "holdout_count": _int(training.get("holdout_count")),
        "reward_mae": _float(holdout.get("reward_mae")),
        "train_mean_reward_mae": _float(baseline.get("train_mean_reward_mae")),
        "dynamics_mae_by_target": dynamics,
        "train_mean_mae_by_target": train_mean,
        "imagined_selected_sequence_predicted_reward": _float(
            selected.get("imagined_cumulative_predicted_reward")
        ),
        "imagined_selected_sequence_conservative_reward": _float(
            selected.get("imagined_cumulative_conservative_reward")
        ),
        "imagined_advantage_over_static_single_step": _float(
            planner.get("imagined_advantage_over_static_single_step")
        ),
        "imagined_advantage_over_one_step_policy": _float(
            planner.get("imagined_advantage_over_one_step_policy")
        ),
        "action_count": len(actions),
        "action_sequence": actions,
        "target_units": _target_units(actions),
        "supported_claim": report.get("supported_claim"),
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _geographic_similarity_evidence(kernel: dict[str, Any]) -> dict[str, Any]:
    validation = validate_uwm_geographic_similarity_kernel(kernel)
    summary = kernel.get("summary") or {}
    features = kernel.get("configuration_features") or {}
    controls = kernel.get("negative_controls") or {}
    ready = (
        validation.get("valid") is True
        and kernel.get("schema") == "uwm.geographic_similarity_kernel.v1"
        and kernel.get("geographic_similarity_kernel_ready") is True
        and _int(summary.get("panel_unit_count")) == 1017
        and _int(summary.get("kernel_source_unit_count")) == 1017
        and _int(summary.get("similarity_edge_count")) == 5085
        and _int(summary.get("non_adjacent_similarity_edge_count")) == 4835
        and features.get("uses_coordinates_as_similarity_features") is False
        and controls.get("rotated_target_similarity_control_passed") is True
        and kernel.get("observed_policy_outcome_superiority_claim") is False
        and kernel.get("empirical_superiority_claim") is False
    )
    return {
        "geographic_similarity_kernel_ready": ready,
        "kernel_id": kernel.get("kernel_id"),
        "validation_errors": validation.get("errors") or [],
        "panel_unit_count": _int(summary.get("panel_unit_count")),
        "kernel_source_unit_count": _int(summary.get("kernel_source_unit_count")),
        "top_k": _int(summary.get("top_k")),
        "similarity_edge_count": _int(summary.get("similarity_edge_count")),
        "adjacent_similarity_edge_count": _int(
            summary.get("adjacent_similarity_edge_count")
        ),
        "non_adjacent_similarity_edge_count": _int(
            summary.get("non_adjacent_similarity_edge_count")
        ),
        "mean_configuration_similarity": _float(
            summary.get("mean_configuration_similarity")
        ),
        "uses_coordinates_as_similarity_features": bool(
            features.get("uses_coordinates_as_similarity_features")
        ),
        "uses_admin_boundary_adjacency_as_similarity_feature": bool(
            features.get("uses_admin_boundary_adjacency_as_similarity_feature")
        ),
        "rotated_target_similarity_control_passed": bool(
            controls.get("rotated_target_similarity_control_passed")
        ),
        "real_minus_rotated_similarity": _float(
            controls.get("real_minus_rotated_similarity")
        ),
        "supported_claim": kernel.get("supported_claim"),
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _service_accessibility_evidence(
    surface: dict[str, Any],
    quality: dict[str, Any],
) -> dict[str, Any]:
    surface_validation = validate_full_admin_service_accessibility_surface(surface)
    quality_validation = validate_full_admin_service_surface_quality_audit(quality)
    counts = surface.get("source_feature_counts") or {}
    coverage = surface.get("coverage") or {}
    endpoints = {
        str(endpoint.get("endpoint_id")): endpoint
        for endpoint in quality.get("endpoint_evaluations") or []
        if isinstance(endpoint, dict)
    }
    essential = endpoints.get("essential_service_count_proxy") or {}
    travel = endpoints.get("estimated_nearest_essential_travel_time_proxy") or {}
    controls_passed = bool(endpoints) and all(
        endpoint.get("target_rotation_negative_control_passed") is True
        for endpoint in endpoints.values()
    )
    beats_baselines = bool(endpoints) and all(
        endpoint.get("beats_best_baseline") is True for endpoint in endpoints.values()
    )
    surface_ready = (
        surface_validation.get("valid") is True
        and surface.get("schema") == "uwm.full_admin_service_accessibility_surface.v1"
        and surface.get("experiment_scope") == "full_admin_graph"
        and _int(surface.get("admin_unit_count")) == 1017
        and _int(counts.get("poi_points")) == 1194351
        and _int(counts.get("roads")) == 50366
        and _int(coverage.get("service_missing_admin_count")) == 0
        and _int(coverage.get("admin_units_with_accessibility_score")) == 1017
        and surface.get("observed_policy_outcome_superiority_claim") is False
        and surface.get("empirical_superiority_claim") is False
    )
    quality_ready = (
        quality_validation.get("valid") is True
        and quality.get("schema") == "uwm.full_admin_service_surface_quality_audit.v1"
        and quality.get("experiment_scope") == "full_admin_graph"
        and _int(quality.get("admin_unit_count")) == 1017
        and _int(quality.get("endpoint_count")) == 2
        and _int(quality.get("ready_endpoint_count")) == 2
        and quality.get("full_admin_service_surface_quality_audit_ready") is True
        and beats_baselines
        and controls_passed
        and quality.get("observed_trip_time_claim") is False
        and quality.get("authoritative_service_inventory_claim") is False
        and quality.get("observed_policy_outcome_superiority_claim") is False
        and quality.get("empirical_superiority_claim") is False
    )
    return {
        "service_accessibility_surface_ready": surface_ready,
        "service_surface_quality_audit_ready": quality_ready,
        "surface_validation_errors": surface_validation.get("errors") or [],
        "quality_validation_errors": quality_validation.get("errors") or [],
        "admin_unit_count": _int(surface.get("admin_unit_count")),
        "source_poi_point_count": _int(counts.get("poi_points")),
        "source_road_count": _int(counts.get("roads")),
        "service_missing_admin_count": _int(
            coverage.get("service_missing_admin_count")
        ),
        "admin_units_with_accessibility_score": _int(
            coverage.get("admin_units_with_accessibility_score")
        ),
        "total_service_point_count": _int(surface.get("total_service_point_count")),
        "total_essential_service_count": _int(
            surface.get("total_essential_service_count")
        ),
        "endpoint_count": _int(quality.get("endpoint_count")),
        "ready_endpoint_count": _int(quality.get("ready_endpoint_count")),
        "essential_service_model_mae": _float(essential.get("model_mae")),
        "essential_service_best_baseline_mae": _float(
            essential.get("best_baseline_mae")
        ),
        "travel_time_model_mae": _float(travel.get("model_mae")),
        "travel_time_best_baseline_mae": _float(travel.get("best_baseline_mae")),
        "beats_best_baselines": beats_baselines,
        "target_rotation_negative_controls_passed": controls_passed,
        "observed_trip_time_claim": False,
        "authoritative_service_inventory_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _comparison_against_traditional_static_baselines(
    planner: dict[str, Any],
    graph_dqn: dict[str, Any],
    learned_rollout: dict[str, Any],
) -> dict[str, Any]:
    planner_advantage = _float(planner.get("advantage_over_static_single_step"))
    planner_risk_advantage = _float(
        planner.get("risk_adjusted_advantage_over_static_single_step")
    )
    graph_advantage = _float(graph_dqn.get("advantage_over_traditional_static"))
    learned_static_advantage = _float(
        learned_rollout.get("imagined_advantage_over_static_single_step")
    )
    learned_one_step_advantage = _float(
        learned_rollout.get("imagined_advantage_over_one_step_policy")
    )
    return {
        "baseline_family": "same_scene_traditional_static_priority_baselines",
        "planner_advantage_over_static": planner_advantage,
        "planner_risk_adjusted_advantage_over_static": planner_risk_advantage,
        "graph_dqn_advantage_over_static": graph_advantage,
        "learned_rollout_advantage_over_static": learned_static_advantage,
        "learned_rollout_advantage_over_one_step_policy": learned_one_step_advantage,
        "all_world_model_advantages_positive": all(
            value > 0.0
            for value in [
                planner_advantage,
                planner_risk_advantage,
                graph_advantage,
                learned_static_advantage,
                learned_one_step_advantage,
            ]
        ),
        "comparison_scope": (
            "full_admin_graph_simulator_replay_and_learned_rollout_not_observed_policy_outcome"
        ),
    }


def _production_governance_binding_evidence(gate: dict[str, Any]) -> dict[str, Any]:
    summary = gate.get("summary") or {}
    gate_ready = (
        gate.get("schema") == "uwm.production_governance_planner_binding_gate.v1"
        and gate.get("experiment_scope") == "full_admin_graph"
        and gate.get("binding_gate_ready") is True
        and _int(summary.get("required_gate_count")) == 9
    )
    planner_binding_ready = (
        gate_ready and gate.get("planner_governance_binding_ready") is True
    )
    return {
        "production_governance_binding_gate_ready": gate_ready,
        "schema": gate.get("schema"),
        "authoritative_governance_data_closure_ready": bool(
            gate.get("authoritative_governance_data_closure_ready")
        ),
        "planner_governance_binding_ready": planner_binding_ready,
        "production_planner_binding_blocked": not planner_binding_ready,
        "required_gate_count": _int(summary.get("required_gate_count")),
        "passed_gate_count": _int(summary.get("passed_gate_count")),
        "blocking_gate_count": _int(summary.get("blocking_gate_count")),
        "missing_table_count": _int(summary.get("missing_table_count")),
        "accepted_authoritative_row_count": _int(
            summary.get("accepted_authoritative_row_count")
        ),
        "linked_project_count": _int(summary.get("linked_project_count")),
        "blocking_gate_ids": list(gate.get("blocking_gate_ids") or []),
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _final_outputs(
    planner: dict[str, Any],
    graph_dqn: dict[str, Any],
    learned_rollout: dict[str, Any],
    similarity: dict[str, Any],
    service: dict[str, Any],
    spatial_causal_question_registry: dict[str, Any],
) -> dict[str, Any]:
    causal_contracts = _causal_contracts_by_action_type(
        spatial_causal_question_registry
    )
    planner_sequence = _sequence_output(planner, causal_contracts)
    graph_sequence = _sequence_output(graph_dqn, causal_contracts)
    learned_sequence = _sequence_output(learned_rollout, causal_contracts)
    return {
        "planner_recommended_sequence": planner_sequence,
        "graph_dqn_recommended_sequence": graph_sequence,
        "learned_rollout_recommended_sequence": learned_sequence,
        "priority_admin_units": _priority_admin_units(
            [
                ("planner_replay", planner_sequence),
                ("graph_dqn", graph_sequence),
                ("learned_rollout", learned_sequence),
            ]
        ),
        "decision_basis": [
            "full_admin_service_accessibility_surface",
            "full_admin_service_surface_quality_audit",
            *(
                ["full_admin_geographic_similarity_kernel"]
                if similarity.get("geographic_similarity_kernel_ready") is True
                else []
            ),
            *(
                ["full_admin_graph_model_based_planner_replay"]
                if planner.get("planner_replay_ready") is True
                else []
            ),
            *(
                ["full_admin_graph_trained_graph_dqn_value_network"]
                if graph_dqn.get("graph_dqn_training_ready") is True
                else []
            ),
            *(
                ["full_admin_graph_learned_world_model_rollout"]
                if learned_rollout.get("learned_world_model_rollout_ready") is True
                else []
            ),
            *(
                ["full_admin_service_surface_proxy_quality_controls"]
                if service.get("service_surface_quality_audit_ready") is True
                else []
            ),
        ],
    }


def _sequence_output(
    evidence: dict[str, Any],
    causal_contracts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "action_count": _int(evidence.get("action_count")),
        "action_sequence": [
            _action_with_causal_contract(action, causal_contracts)
            for action in evidence.get("action_sequence") or []
            if isinstance(action, dict)
        ],
        "target_units": list(evidence.get("target_units") or []),
    }


def _causal_contracts_by_action_type(
    spatial_causal_question_registry: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        str(contract.get("action_type")): contract
        for contract in spatial_causal_question_registry.get(
            "causal_question_contracts"
        )
        or []
        if isinstance(contract, dict) and contract.get("action_type")
    }


def _action_with_causal_contract(
    action: dict[str, Any],
    causal_contracts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    enriched = dict(action)
    action_type = str(action.get("action_type") or "")
    contract = causal_contracts.get(action_type)
    if not contract:
        enriched.update(
            {
                "causal_question_id": None,
                "causal_query": None,
                "primary_outcome": None,
                "identification_status": "missing_spatial_causal_contract",
                "required_authoritative_tables": [],
                "policy_outcome_claim_allowed": False,
                "observed_policy_outcome_superiority_claim": False,
                "empirical_superiority_claim": False,
            }
        )
        return enriched

    outcomes = contract.get("outcomes") or {}
    identification = contract.get("identification") or {}
    enriched.update(
        {
            "causal_question_id": contract.get("question_id"),
            "causal_query": contract.get("causal_query"),
            "primary_outcome": outcomes.get("primary_outcome"),
            "identification_status": identification.get("status"),
            "allowed_current_query_level": identification.get(
                "allowed_current_query_level"
            ),
            "causal_blocked_reason": identification.get("blocked_reason"),
            "required_authoritative_tables": list(
                contract.get("required_authoritative_tables") or []
            ),
            "policy_outcome_claim_allowed": bool(
                contract.get("policy_outcome_claim_allowed")
            ),
            "causal_claim_level": contract.get("claim_level"),
            "observed_policy_outcome_superiority_claim": False,
            "empirical_superiority_claim": False,
        }
    )
    return enriched


def _spatial_causal_contract_binding_evidence(
    spatial_causal_question_registry: dict[str, Any],
    final_outputs: dict[str, Any],
) -> dict[str, Any]:
    validation = validate_uwm_spatial_causal_question_registry(
        spatial_causal_question_registry
    )
    summary = spatial_causal_question_registry.get("summary") or {}
    registry_ready = (
        spatial_causal_question_registry.get("registry_ready") is True
        and validation.get("valid") is True
    )
    contracts = _causal_contracts_by_action_type(spatial_causal_question_registry)
    actions = _final_output_actions(final_outputs)
    missing_actions = [
        action
        for action in actions
        if not action.get("causal_question_id")
        or not action.get("causal_query")
        or not action.get("primary_outcome")
        or not action.get("identification_status")
        or not action.get("required_authoritative_tables")
    ]
    policy_outcome_allowed = [
        action for action in actions if action.get("policy_outcome_claim_allowed")
    ]
    return {
        "binding_ready": (
            registry_ready
            and bool(actions)
            and not missing_actions
            and not policy_outcome_allowed
        ),
        "schema": spatial_causal_question_registry.get("schema"),
        "registry_ready": registry_ready,
        "validation_errors": validation.get("errors") or [],
        "active_causal_question_count": _int(
            summary.get("active_causal_question_count")
        ),
        "active_action_types": sorted(contracts),
        "recommended_action_count": len(actions),
        "attached_action_count": len(actions) - len(missing_actions),
        "missing_contract_action_count": len(missing_actions),
        "missing_contract_action_types": sorted(
            {
                str(action.get("action_type") or "unknown_action")
                for action in missing_actions
            }
        ),
        "underidentified_policy_effect_action_count": sum(
            1
            for action in actions
            if action.get("identification_status")
            == "underidentified_for_observed_policy_effect"
        ),
        "identified_policy_effect_action_count": sum(
            1
            for action in actions
            if action.get("identification_status") == "identified"
        ),
        "policy_outcome_claim_allowed_action_count": len(policy_outcome_allowed),
        "required_authoritative_tables": list(
            next(iter(contracts.values()), {}).get("required_authoritative_tables")
            or []
        ),
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _final_output_actions(final_outputs: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for sequence_key in [
        "planner_recommended_sequence",
        "graph_dqn_recommended_sequence",
        "learned_rollout_recommended_sequence",
    ]:
        sequence = final_outputs.get(sequence_key) or {}
        actions.extend(
            action
            for action in sequence.get("action_sequence") or []
            if isinstance(action, dict)
        )
    return actions


def _priority_admin_units(
    named_sequences: list[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    by_unit: dict[str, dict[str, Any]] = {}
    order = 0
    for source, sequence in named_sequences:
        actions = sequence.get("action_sequence") or []
        for action in actions:
            action_type = str(action.get("action_type") or "")
            for unit_id in action.get("target_units") or []:
                unit_key = str(unit_id)
                if unit_key not in by_unit:
                    by_unit[unit_key] = {
                        "unit_id": unit_key,
                        "sources": [],
                        "recommended_action_types": [],
                        "_order": order,
                    }
                    order += 1
                record = by_unit[unit_key]
                if source not in record["sources"]:
                    record["sources"].append(source)
                if action_type and action_type not in record["recommended_action_types"]:
                    record["recommended_action_types"].append(action_type)
    ranked = sorted(
        by_unit.values(),
        key=lambda item: (-len(item["sources"]), item["_order"]),
    )
    for item in ranked:
        item["source_count"] = len(item["sources"])
        del item["_order"]
    return ranked


def _target_units(actions: list[dict[str, Any]]) -> list[str]:
    units: list[str] = []
    for action in actions:
        for unit in action.get("target_units") or []:
            units.append(str(unit))
    return units


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return round(float(value), 9)
    except (TypeError, ValueError):
        return default
