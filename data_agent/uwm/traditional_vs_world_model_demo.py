"""Side-by-side demo artifact for traditional baseline and UWM output."""

from __future__ import annotations

from typing import Any


UWM_TRADITIONAL_VS_WORLD_MODEL_DEMO_SCHEMA = (
    "uwm.traditional_vs_world_model_demo.v1"
)


def build_traditional_vs_world_model_demo(
    *,
    demo_id: str,
    created_at: str,
    multisource_livability_scene: dict[str, Any],
    traditional_livability_baseline: dict[str, Any],
    uwm_livability_decision_package: dict[str, Any],
) -> dict[str, Any]:
    """Build a customer-facing same-data comparison artifact."""

    comparison = (
        uwm_livability_decision_package.get(
            "comparison_against_traditional_static_heuristic"
        )
        or {}
    )
    replay_baselines = (
        uwm_livability_decision_package.get("replay_baseline_suite") or {}
    )
    action_portfolio = (
        uwm_livability_decision_package.get("action_portfolio") or {}
    )
    rl_training = uwm_livability_decision_package.get("rl_training_evidence") or {}
    graph_drl_training = (
        uwm_livability_decision_package.get("graph_drl_training_evidence") or {}
    )
    same_data_basis = (
        traditional_livability_baseline.get("data_scene_id")
        == multisource_livability_scene.get("scene_id")
    )
    ready = (
        same_data_basis
        and uwm_livability_decision_package.get("decision_package_ready") is True
        and traditional_livability_baseline.get("simulator_used") is False
        and traditional_livability_baseline.get("planner_used") is False
        and _float(comparison.get("endpoint_aligned_advantage_over_static")) > 0.0
        and _float(replay_baselines.get("empirical_one_sided_p_value")) < 0.05
    )
    return {
        "schema": UWM_TRADITIONAL_VS_WORLD_MODEL_DEMO_SCHEMA,
        "demo_id": demo_id,
        "created_at": created_at,
        "shared_data_contract": {
            "scene_id": multisource_livability_scene.get("scene_id"),
            "admin_unit_count": len(
                multisource_livability_scene.get("admin_unit_states") or []
            ),
            "same_data_basis": same_data_basis,
            "same_livability_scenario": True,
        },
        "traditional_method_output": {
            "method": traditional_livability_baseline.get("baseline_method"),
            "final_output_type": traditional_livability_baseline.get(
                "final_output_type"
            ),
            "top_priority_units": list(
                traditional_livability_baseline.get("top_priority_units") or []
            ),
            "counterfactual_output_available": False,
            "simulator_used": False,
            "planner_used": False,
            "customer_facing_summary": (
                "同一数据下的传统方法输出当前问题排序和静态优先关注单元。"
            ),
        },
        "uwm_output": {
            "method": "renderer_simulator_planner_world_model",
            "final_output_type": "counterfactual_decision_package",
            "action_count": _int(action_portfolio.get("action_count")),
            "target_units": list(action_portfolio.get("target_units") or []),
            "counterfactual_output_available": True,
            "endpoint_aligned_advantage_over_static": _float(
                comparison.get("endpoint_aligned_advantage_over_static")
            ),
            "risk_adjusted_advantage_over_static": _float(
                comparison.get("risk_adjusted_advantage_over_static")
            ),
            "neighbor_livability_delta_advantage": _float(
                comparison.get("neighbor_livability_delta_advantage")
            ),
            "empirical_p_value_vs_single_action_baselines": _float(
                replay_baselines.get("empirical_one_sided_p_value")
            ),
            "trained_model_based_rl_ready": bool(rl_training.get("ready")),
            "trained_model_based_rl_algorithm": rl_training.get("algorithm"),
            "trained_model_based_rl_advantage_over_static": _float(
                rl_training.get("advantage_over_traditional_static")
            ),
            "trained_graph_drl_ready": bool(graph_drl_training.get("ready")),
            "trained_graph_drl_algorithm": graph_drl_training.get("algorithm"),
            "trained_graph_drl_advantage_over_static": _float(
                graph_drl_training.get("advantage_over_traditional_static")
            ),
            "customer_facing_summary": (
                "同一数据下的 UWM 输出经模拟器和规划器验证的反事实行动方案。"
            ),
        },
        "capability_delta": {
            "shared_inputs": [
                "same_multisource_livability_scene",
                "same_admin_units",
                "same_livability_scenario",
            ],
            "traditional_outputs": [
                "current_state_indicator_summary",
                "static_problem_ranking",
                "static_priority_units",
            ],
            "uwm_only_outputs": [
                "multi_step_action_sequence",
                "counterfactual_state_delta",
                "spatial_spillover",
                "risk_adjusted_planning_evidence",
                "endpoint_weight_sensitivity",
                "empirical_baseline_distribution_p_value",
                "trained_model_based_rl_policy_evidence",
                "trained_graph_drl_value_network_evidence",
            ],
            "main_message": (
                "传统方法输出问题清单和排名；UWM 输出反事实决策包及未来影响证据。"
            ),
        },
        "demo_ready": ready,
        "supported_claim": (
            "uwm_outputs_counterfactual_decision_package_traditional_outputs_static_ranking"
            if ready
            else "no_same_data_demo_superiority_claim_supported"
        ),
        "claim_boundary": {
            "max_claim_level": "bounded_support" if ready else "not_for_claim",
            "reason": (
                "same-data demo compares output capability and validated offline "
                "decision evidence; it is not observed policy outcome evidence"
            ),
        },
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


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
