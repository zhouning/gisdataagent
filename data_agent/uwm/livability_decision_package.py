"""Final decision package for UWM livability analysis."""

from __future__ import annotations

import statistics
from typing import Any

from .spatial_spillover_kernel import (
    validate_uwm_data_calibrated_spatial_spillover_kernel,
)


UWM_LIVABILITY_DECISION_PACKAGE_SCHEMA = "uwm.livability_decision_package.v1"


def build_uwm_livability_decision_package(
    *,
    package_id: str,
    created_at: str,
    data_calibrated_planner_replay: dict[str, Any],
    livability_endpoint_suite: dict[str, Any],
    endpoint_aligned_planner_evaluator: dict[str, Any],
    spatial_spillover_planner_evaluator: dict[str, Any],
    spatial_spillover_kernel: dict[str, Any] | None = None,
    rl_training_report: dict[str, Any] | None = None,
    graph_drl_training_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect final UWM decision evidence into a claim-safe package."""

    best_sequence = data_calibrated_planner_replay.get("best_sequence") or {}
    static_sequence = (
        data_calibrated_planner_replay.get("static_single_step_baseline") or {}
    )
    risk = data_calibrated_planner_replay.get(
        "risk_adjusted_planner_evaluation"
    ) or {}
    planner_outcome = _sequence_outcome_summary(best_sequence)
    static_outcome = _sequence_outcome_summary(static_sequence)
    action_portfolio = _action_portfolio(best_sequence)
    replay_baseline_suite = _replay_baseline_suite(data_calibrated_planner_replay)
    endpoint_weight_sensitivity = _endpoint_weight_sensitivity(
        best_sequence,
        static_sequence,
        livability_endpoint_suite,
    )
    spatial_kernel_evidence = _spatial_spillover_kernel_evidence(
        spatial_spillover_kernel
    )
    rl_training_evidence = _rl_training_evidence(rl_training_report)
    graph_drl_training_evidence = _graph_drl_training_evidence(
        graph_drl_training_report
    )
    comparison = {
        "traditional_static_method": static_sequence.get("method"),
        "planner_endpoint_aligned_score": _float(
            endpoint_aligned_planner_evaluator.get("planner_endpoint_aligned_score")
        ),
        "static_endpoint_aligned_score": _float(
            endpoint_aligned_planner_evaluator.get("static_endpoint_aligned_score")
        ),
        "endpoint_aligned_advantage_over_static": _float(
            endpoint_aligned_planner_evaluator.get(
                "endpoint_aligned_advantage_over_static"
            )
        ),
        "endpoint_aligned_advantage_ratio": _float(
            endpoint_aligned_planner_evaluator.get("endpoint_aligned_advantage_ratio")
        ),
        "best_sequence_risk_adjusted_reward": _float(
            risk.get("best_sequence_risk_adjusted_reward")
        ),
        "static_single_step_risk_adjusted_reward": _float(
            risk.get("static_single_step_risk_adjusted_reward")
        ),
        "risk_adjusted_advantage_over_static": _float(
            risk.get("risk_adjusted_advantage_over_static_single_step")
        ),
        "planner_neighbor_benefited_unit_count": _int(
            spatial_spillover_planner_evaluator.get(
                "planner_neighbor_benefited_unit_count"
            )
        ),
        "static_neighbor_benefited_unit_count": _int(
            spatial_spillover_planner_evaluator.get(
                "static_neighbor_benefited_unit_count"
            )
        ),
        "neighbor_livability_delta_advantage": _float(
            spatial_spillover_planner_evaluator.get(
                "neighbor_livability_delta_advantage"
            )
        ),
        "neighbor_livability_delta_advantage_ratio": _float(
            spatial_spillover_planner_evaluator.get(
                "neighbor_livability_delta_advantage_ratio"
            )
        ),
        "planner_benefited_unit_count": planner_outcome[
            "positive_livability_unit_count"
        ],
        "static_benefited_unit_count": static_outcome[
            "positive_livability_unit_count"
        ],
        "planner_positive_livability_delta_sum": planner_outcome[
            "positive_livability_delta_sum"
        ],
        "static_positive_livability_delta_sum": static_outcome[
            "positive_livability_delta_sum"
        ],
        "planner_positive_equity_delta_sum": planner_outcome[
            "positive_equity_delta_sum"
        ],
        "static_positive_equity_delta_sum": static_outcome[
            "positive_equity_delta_sum"
        ],
    }
    ready = _decision_package_ready(
        livability_endpoint_suite,
        endpoint_aligned_planner_evaluator,
        spatial_spillover_planner_evaluator,
        risk,
        comparison,
        endpoint_weight_sensitivity,
    )
    supported_claim = (
        "uwm_livability_decision_package_beats_static_heuristic_on_validated_endpoints_spillover_and_risk"
        if ready
        else "no_livability_decision_package_superiority_claim_supported"
    )
    return {
        "schema": UWM_LIVABILITY_DECISION_PACKAGE_SCHEMA,
        "package_id": package_id,
        "created_at": created_at,
        "decision_package_ready": ready,
        "source_schemas": {
            "data_calibrated_planner_replay": data_calibrated_planner_replay.get(
                "schema"
            ),
            "livability_endpoint_suite": livability_endpoint_suite.get("schema"),
            "endpoint_aligned_planner_evaluator": (
                endpoint_aligned_planner_evaluator.get("schema")
            ),
            "spatial_spillover_planner_evaluator": (
                spatial_spillover_planner_evaluator.get("schema")
            ),
            "rl_training_report": (rl_training_report or {}).get("schema"),
            "graph_drl_training_report": (
                graph_drl_training_report or {}
            ).get("schema"),
        },
        "action_portfolio": action_portfolio,
        "validated_endpoint_evidence": {
            "endpoint_count": _int(livability_endpoint_suite.get("endpoint_count")),
            "ready_endpoint_count": _int(
                livability_endpoint_suite.get("ready_endpoint_count")
            ),
            "building_floor_morphology_projected": bool(
                livability_endpoint_suite.get("building_floor_morphology_projected")
            ),
            "mean_relative_mae_reduction_vs_best_traditional": _float(
                livability_endpoint_suite.get(
                    "mean_relative_mae_reduction_vs_best_traditional"
                )
            ),
            "min_relative_mae_reduction_vs_best_traditional": _float(
                livability_endpoint_suite.get(
                    "min_relative_mae_reduction_vs_best_traditional"
                )
            ),
        },
        "comparison_against_traditional_static_heuristic": comparison,
        "replay_baseline_suite": replay_baseline_suite,
        "endpoint_weight_sensitivity": endpoint_weight_sensitivity,
        "spatial_spillover_kernel_evidence": spatial_kernel_evidence,
        "rl_training_evidence": rl_training_evidence,
        "graph_drl_training_evidence": graph_drl_training_evidence,
        "planner_outcome_summary": planner_outcome,
        "static_outcome_summary": static_outcome,
        "final_outputs": {
            "recommended_action_sequence": action_portfolio["actions"],
            "priority_admin_units": _priority_admin_units(best_sequence),
            "decision_basis": [
                "validated_final_livability_endpoint_suite",
                "endpoint_aligned_model_based_planner_replay",
                "risk_adjusted_planner_replay",
                "first_order_admin_neighbor_spillover",
                *(
                    ["data_calibrated_spatial_spillover_kernel"]
                    if spatial_kernel_evidence.get("ready") is True
                    else []
                ),
                *(
                    ["trained_model_based_rl_policy"]
                    if rl_training_evidence.get("ready") is True
                    else []
                ),
                *(
                    ["trained_graph_dqn_value_network"]
                    if graph_drl_training_evidence.get("ready") is True
                    else []
                ),
            ],
        },
        "supported_claim": supported_claim,
        "claim_boundary": {
            "max_claim_level": "bounded_support" if ready else "not_for_claim",
            "reason": (
                "decision package compares model-based replay to a static heuristic "
                "using validated endpoints, same uncertainty penalty and admin "
                "neighbor spillover, optional trained tabular model-based RL "
                "evidence and optional trained graph neural Q/value evidence; it "
                "is not observed policy outcome evidence"
            ),
        },
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _decision_package_ready(
    livability_endpoint_suite: dict[str, Any],
    endpoint_aligned_planner_evaluator: dict[str, Any],
    spatial_spillover_planner_evaluator: dict[str, Any],
    risk: dict[str, Any],
    comparison: dict[str, Any],
    endpoint_weight_sensitivity: dict[str, Any],
) -> bool:
    return (
        livability_endpoint_suite.get("supported_claim")
        == "uwm_final_livability_endpoint_suite_beats_traditional_baselines"
        and endpoint_aligned_planner_evaluator.get("supported_claim")
        == "endpoint_aligned_planner_replay_advantage_over_static_heuristic"
        and spatial_spillover_planner_evaluator.get("supported_claim")
        == "spatial_spillover_planner_replay_advantage_over_static_heuristic"
        and risk.get("risk_calibrated_planner_replay_ready") is True
        and comparison["endpoint_aligned_advantage_over_static"] > 0.0
        and comparison["risk_adjusted_advantage_over_static"] > 0.0
        and comparison["neighbor_livability_delta_advantage"] > 0.0
        and endpoint_weight_sensitivity.get("all_profiles_advantage_positive")
        is True
        and not bool(livability_endpoint_suite.get("observed_policy_outcome_superiority_claim"))
        and not bool(
            endpoint_aligned_planner_evaluator.get(
                "observed_policy_outcome_superiority_claim"
            )
        )
        and not bool(
            spatial_spillover_planner_evaluator.get(
                "observed_policy_outcome_superiority_claim"
            )
        )
    )


def _action_portfolio(sequence: dict[str, Any]) -> dict[str, Any]:
    actions = list(sequence.get("action_sequence") or [])
    target_units = [
        str(unit)
        for action in actions
        for unit in action.get("target_units") or []
    ]
    return {
        "action_count": len(actions),
        "actions": actions,
        "target_units": target_units,
        "target_unit_count": len(set(target_units)),
        "action_types": sorted({str(action.get("action_type")) for action in actions}),
    }


def _replay_baseline_suite(
    data_calibrated_planner_replay: dict[str, Any],
) -> dict[str, Any]:
    transitions = (
        (data_calibrated_planner_replay.get("trajectory_dataset") or {}).get(
            "transitions"
        )
        or []
    )
    rewards = [_float(transition.get("reward")) for transition in transitions]
    best_sequence = data_calibrated_planner_replay.get("best_sequence") or {}
    best_sequence_reward = _float(best_sequence.get("cumulative_reward"))
    best_single_action_reward = max(rewards) if rewards else 0.0
    win_count = sum(best_sequence_reward > reward for reward in rewards)
    greater_or_equal_count = sum(best_sequence_reward <= reward for reward in rewards)
    return {
        "baseline_family": "single_action_replay_baselines",
        "single_action_transition_count": len(rewards),
        "positive_single_action_count": sum(1 for reward in rewards if reward > 0.0),
        "best_sequence_reward": round(best_sequence_reward, 9),
        "best_single_action_reward": round(best_single_action_reward, 9),
        "advantage_vs_best_single_action": round(
            best_sequence_reward - best_single_action_reward,
            9,
        ),
        "mean_single_action_reward": round(_mean(rewards), 9),
        "median_single_action_reward": round(
            statistics.median(rewards) if rewards else 0.0,
            9,
        ),
        "best_sequence_percentile_vs_single_actions": round(
            win_count / len(rewards) if rewards else 0.0,
            6,
        ),
        "empirical_one_sided_p_value": round(
            (greater_or_equal_count + 1) / (len(rewards) + 1)
            if rewards
            else 1.0,
            6,
        ),
        "single_action_win_rate": round(
            win_count / len(rewards) if rewards else 0.0,
            6,
        ),
    }


def _endpoint_weight_sensitivity(
    best_sequence: dict[str, Any],
    static_sequence: dict[str, Any],
    livability_endpoint_suite: dict[str, Any],
) -> dict[str, Any]:
    endpoint_weights = {
        str(endpoint.get("endpoint_id")): _float(
            endpoint.get("relative_mae_reduction_vs_best_traditional")
        )
        for endpoint in livability_endpoint_suite.get("endpoint_evaluations") or []
    }
    profiles = {
        "validation_weighted": endpoint_weights,
        "equal_weights": {
            endpoint_id: 1.0 for endpoint_id in endpoint_weights
        },
        "air_only": {
            "air_quality_pm25": 1.0,
            "service_point_accessibility": 0.0,
            "essential_service_accessibility": 0.0,
        },
        "service_point_only": {
            "air_quality_pm25": 0.0,
            "service_point_accessibility": 1.0,
            "essential_service_accessibility": 0.0,
        },
        "essential_service_only": {
            "air_quality_pm25": 0.0,
            "service_point_accessibility": 0.0,
            "essential_service_accessibility": 1.0,
        },
    }
    admin_unit_count = max(1, _int(livability_endpoint_suite.get("admin_unit_count")))
    profile_results = {}
    for profile_id, weights in profiles.items():
        planner_score = _endpoint_weighted_sequence_score(
            best_sequence,
            weights,
            admin_unit_count=admin_unit_count,
        )
        static_score = _endpoint_weighted_sequence_score(
            static_sequence,
            weights,
            admin_unit_count=admin_unit_count,
        )
        advantage = planner_score - static_score
        profile_results[profile_id] = {
            "planner_score": round(planner_score, 9),
            "static_score": round(static_score, 9),
            "advantage_over_static": round(advantage, 9),
            "advantage_ratio": round(
                planner_score / static_score if static_score else 0.0,
                6,
            ),
        }
    advantages = [
        _float(result.get("advantage_over_static"))
        for result in profile_results.values()
    ]
    return {
        "profile_count": len(profile_results),
        "profiles": profile_results,
        "all_profiles_advantage_positive": all(
            advantage > 0.0 for advantage in advantages
        ),
        "min_advantage_over_static": round(min(advantages) if advantages else 0.0, 9),
        "max_advantage_over_static": round(max(advantages) if advantages else 0.0, 9),
    }


def _endpoint_weighted_sequence_score(
    sequence: dict[str, Any],
    weights: dict[str, float],
    *,
    admin_unit_count: int,
) -> float:
    per_unit = (
        ((sequence.get("rollout_trace") or {}).get("future_state_delta") or {}).get(
            "per_unit"
        )
        or {}
    )
    score = 0.0
    for delta in per_unit.values():
        air_improvement = max(
            0.0,
            -_float(delta.get("air_pollution_exposure_delta")),
        )
        service_improvement = max(
            0.0,
            _float(delta.get("service_accessibility_delta")),
        )
        score += air_improvement * weights.get("air_quality_pm25", 0.0)
        score += service_improvement * weights.get(
            "service_point_accessibility",
            0.0,
        )
        score += service_improvement * weights.get(
            "essential_service_accessibility",
            0.0,
        )
    return score / admin_unit_count


def _spatial_spillover_kernel_evidence(
    spatial_spillover_kernel: dict[str, Any] | None,
) -> dict[str, Any]:
    if spatial_spillover_kernel is None:
        return {
            "ready": False,
            "kernel_id": None,
            "directional_edge_count": 0,
            "kernel_source_unit_count": 0,
            "uses_shared_boundary_length": False,
            "uses_admin_livability_need": False,
            "uses_admin_exposure_priority": False,
            "observed_policy_outcome_superiority_claim": False,
        }
    validation = validate_uwm_data_calibrated_spatial_spillover_kernel(
        spatial_spillover_kernel
    )
    ready = (
        validation.get("valid") is True
        and spatial_spillover_kernel.get(
            "data_calibrated_spatial_spillover_kernel_ready"
        )
        is True
        and spatial_spillover_kernel.get("observed_policy_outcome_superiority_claim")
        is False
    )
    summary = spatial_spillover_kernel.get("summary") or {}
    features = spatial_spillover_kernel.get("calibration_features") or {}
    return {
        "ready": ready,
        "kernel_id": spatial_spillover_kernel.get("kernel_id"),
        "validation_errors": validation.get("errors") or [],
        "directional_edge_count": _int(summary.get("directional_edge_count")),
        "kernel_source_unit_count": _int(summary.get("kernel_source_unit_count")),
        "min_spillover_factor": _float(summary.get("min_spillover_factor")),
        "max_spillover_factor": _float(summary.get("max_spillover_factor")),
        "mean_spillover_factor": _float(summary.get("mean_spillover_factor")),
        "uses_shared_boundary_length": bool(
            features.get("uses_shared_boundary_length")
        ),
        "uses_admin_livability_need": bool(features.get("uses_admin_livability_need")),
        "uses_admin_exposure_priority": bool(
            features.get("uses_admin_exposure_priority")
        ),
        "observed_policy_outcome_superiority_claim": False,
        "claim_boundary": spatial_spillover_kernel.get("claim_boundary") or {},
    }


def _rl_training_evidence(
    rl_training_report: dict[str, Any] | None,
) -> dict[str, Any]:
    if not rl_training_report:
        return {
            "ready": False,
            "report_id": None,
            "algorithm": None,
            "episode_count": 0,
            "real_data_graph_node_count": 0,
            "available_action_count": 0,
            "spatial_spillover_directional_edge_count": 0,
            "advantage_over_traditional_static": 0.0,
            "observed_policy_outcome_superiority_claim": False,
        }
    training_summary = rl_training_report.get("training_summary") or {}
    learned = rl_training_report.get("learned_policy_evaluation") or {}
    algorithm = rl_training_report.get("rl_algorithm") or {}
    ready = (
        rl_training_report.get("schema") == "uwm.livability_rl_training_report.v1"
        and rl_training_report.get("supported_claim")
        == "trained_model_based_q_agent_improves_same_scene_static_livability_baseline"
        and _float(learned.get("advantage_over_traditional_static")) > 0.0
        and rl_training_report.get("observed_policy_outcome_superiority_claim") is False
    )
    return {
        "ready": ready,
        "report_id": rl_training_report.get("report_id"),
        "algorithm": algorithm.get("algorithm"),
        "episode_count": _int(training_summary.get("episode_count")),
        "real_data_graph_node_count": _int(
            training_summary.get("real_data_graph_node_count")
        ),
        "real_data_graph_edge_count": _int(
            training_summary.get("real_data_graph_edge_count")
        ),
        "available_action_count": _int(
            training_summary.get("real_data_available_action_count")
        ),
        "spatial_spillover_directional_edge_count": _int(
            training_summary.get("spatial_spillover_directional_edge_count")
        ),
        "learned_policy_cumulative_reward": _float(
            learned.get("learned_policy_cumulative_reward")
        ),
        "advantage_over_traditional_static": _float(
            learned.get("advantage_over_traditional_static")
        ),
        "supported_claim": rl_training_report.get("supported_claim"),
        "claim_boundary": rl_training_report.get("claim_boundary") or {},
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _graph_drl_training_evidence(
    graph_drl_training_report: dict[str, Any] | None,
) -> dict[str, Any]:
    if not graph_drl_training_report:
        return {
            "ready": False,
            "report_id": None,
            "algorithm": None,
            "is_deep_rl": False,
            "is_model_based": False,
            "is_model_free": False,
            "uses_graph_message_passing": False,
            "policy_or_value_network_trained": False,
            "training_sample_count": 0,
            "holdout_count": 0,
            "q_return_mae": 0.0,
            "train_mean_return_mae": 0.0,
            "advantage_over_traditional_static": 0.0,
            "observed_policy_outcome_superiority_claim": False,
        }
    training = graph_drl_training_report.get("training_summary") or {}
    holdout = graph_drl_training_report.get("holdout_metrics") or {}
    learned = graph_drl_training_report.get("learned_policy_evaluation") or {}
    algorithm = graph_drl_training_report.get("drl_algorithm") or {}
    ready = (
        graph_drl_training_report.get("schema")
        == "uwm.livability_graph_drl_training_report.v1"
        and algorithm.get("algorithm") == "graph_dqn_fitted_q_model_based_rl"
        and algorithm.get("is_deep_rl") is True
        and algorithm.get("is_model_based") is True
        and algorithm.get("is_model_free") is False
        and algorithm.get("uses_graph_message_passing") is True
        and algorithm.get("policy_or_value_network_trained") is True
        and _int(training.get("training_sample_count")) > 0
        and _float(holdout.get("q_return_mae")) < _float(
            holdout.get("train_mean_return_mae")
        )
        and _float(learned.get("advantage_over_traditional_static")) > 0.0
        and graph_drl_training_report.get("supported_claim")
        == "graph_dqn_value_network_improves_same_scene_static_livability_baseline"
        and graph_drl_training_report.get(
            "observed_policy_outcome_superiority_claim"
        )
        is False
    )
    return {
        "ready": ready,
        "report_id": graph_drl_training_report.get("report_id"),
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
        "training_sample_count": _int(training.get("training_sample_count")),
        "train_count": _int(training.get("train_count")),
        "holdout_count": _int(training.get("holdout_count")),
        "real_data_graph_node_count": _int(
            training.get("real_data_graph_node_count")
        ),
        "real_data_graph_edge_count": _int(
            training.get("real_data_graph_edge_count")
        ),
        "available_action_count": _int(
            training.get("real_data_available_action_count")
        ),
        "spatial_spillover_directional_edge_count": _int(
            training.get("spatial_spillover_directional_edge_count")
        ),
        "q_return_mae": _float(holdout.get("q_return_mae")),
        "train_mean_return_mae": _float(holdout.get("train_mean_return_mae")),
        "q_return_rmse": _float(holdout.get("q_return_rmse")),
        "train_mean_return_rmse": _float(holdout.get("train_mean_return_rmse")),
        "graph_dqn_policy_cumulative_reward": _float(
            learned.get("graph_dqn_policy_cumulative_reward")
        ),
        "advantage_over_traditional_static": _float(
            learned.get("advantage_over_traditional_static")
        ),
        "supported_claim": graph_drl_training_report.get("supported_claim"),
        "claim_boundary": graph_drl_training_report.get("claim_boundary") or {},
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _sequence_outcome_summary(sequence: dict[str, Any]) -> dict[str, Any]:
    per_unit = (
        ((sequence.get("rollout_trace") or {}).get("future_state_delta") or {}).get(
            "per_unit"
        )
        or {}
    )
    return {
        "changed_unit_count": _int(
            ((sequence.get("rollout_trace") or {}).get("future_state_delta") or {}).get(
                "changed_units"
            )
        ),
        "positive_livability_unit_count": sum(
            1
            for delta in per_unit.values()
            if _float(delta.get("livability_delta")) > 0.0
        ),
        "positive_equity_unit_count": sum(
            1 for delta in per_unit.values() if _float(delta.get("equity_delta")) > 0.0
        ),
        "positive_livability_delta_sum": round(
            sum(
                max(0.0, _float(delta.get("livability_delta")))
                for delta in per_unit.values()
            ),
            9,
        ),
        "positive_equity_delta_sum": round(
            sum(
                max(0.0, _float(delta.get("equity_delta")))
                for delta in per_unit.values()
            ),
            9,
        ),
    }


def _priority_admin_units(sequence: dict[str, Any]) -> list[dict[str, Any]]:
    per_unit = (
        ((sequence.get("rollout_trace") or {}).get("future_state_delta") or {}).get(
            "per_unit"
        )
        or {}
    )
    rows = [
        {
            "admin_unit_id": unit_id,
            "livability_delta": round(_float(delta.get("livability_delta")), 9),
            "equity_delta": round(_float(delta.get("equity_delta")), 9),
            "air_pollution_exposure_delta": round(
                _float(delta.get("air_pollution_exposure_delta")),
                9,
            ),
            "service_accessibility_delta": round(
                _float(delta.get("service_accessibility_delta")),
                9,
            ),
        }
        for unit_id, delta in per_unit.items()
        if _float(delta.get("livability_delta")) > 0.0
    ]
    rows.sort(key=lambda row: (-row["livability_delta"], row["admin_unit_id"]))
    return rows


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    if value in {None, ""}:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
