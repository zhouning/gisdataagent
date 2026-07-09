"""Full-admin energy-regularized planner for UWM livability."""

from __future__ import annotations

from typing import Any

from .energy_regularized_planner import (
    plan_with_energy_regularized_action_sequences,
)
from .geographic_similarity_kernel import validate_uwm_geographic_similarity_kernel
from .livability_graph_mdp_env import LivabilityGraphMDPEnv


UWM_FULL_ADMIN_ENERGY_REGULARIZED_ACTION_SEQUENCE_PLANNER_SCHEMA = (
    "uwm.full_admin_energy_regularized_action_sequence_planner.v1"
)

_SUPPORTED_CLAIM = (
    "full_admin_energy_regularized_model_based_action_sequence_planner_advantage_over_traditional_static"
)


def plan_full_admin_energy_regularized_action_sequences(
    env: LivabilityGraphMDPEnv,
    *,
    graph_drl_training_report: dict[str, Any],
    geographic_similarity_kernel: dict[str, Any],
    report_id: str,
    created_at: str,
    top_k_per_step: int = 16,
    energy_weight: float = 0.00035,
    ood_penalty_weight: float = 0.00055,
) -> dict[str, Any]:
    """Run conservative action-sequence search over the full-admin Graph-MDP."""

    base = plan_with_energy_regularized_action_sequences(
        env,
        graph_drl_training_report=graph_drl_training_report,
        report_id=report_id,
        created_at=created_at,
        top_k_per_step=top_k_per_step,
        energy_weight=energy_weight,
        ood_penalty_weight=ood_penalty_weight,
    )
    similarity_evidence = _geographic_similarity_evidence(geographic_similarity_kernel)
    full_data_guard = _full_data_guard(base, similarity_evidence)
    graph_alignment_ready = _full_admin_graph_dqn_alignment_ready(
        graph_drl_training_report,
        base,
    )
    ready = (
        full_data_guard["passed"] is True
        and similarity_evidence["geographic_similarity_kernel_ready"] is True
        and graph_alignment_ready is True
        and base["conservative_search_audit"][
            "planner_exploitation_guard_passed"
        ]
        is True
        and base["selected_sequence"]["advantage_over_traditional_static"] > 0.0
        and base.get("observed_policy_outcome_superiority_claim") is False
        and base.get("empirical_superiority_claim") is False
    )

    report = dict(base)
    report["schema"] = UWM_FULL_ADMIN_ENERGY_REGULARIZED_ACTION_SEQUENCE_PLANNER_SCHEMA
    report["base_planner_schema"] = base.get("schema")
    report["experiment_scope"] = "full_admin_graph"
    report["full_admin_energy_regularized_planner_ready"] = ready
    report["full_data_guard"] = full_data_guard
    report["geographic_similarity_evidence"] = similarity_evidence
    report["behavior_prior"] = {
        **(base.get("behavior_prior") or {}),
        "source": "full_admin_graph_available_actions_boundary_and_similarity_edges",
        "observed_intervention_log_prior": False,
        "historical_policy_prior_claim": False,
    }
    report["search_value_alignment"] = {
        **(base.get("search_value_alignment") or {}),
        "full_admin_graph_dqn_alignment_ready": graph_alignment_ready,
        "full_admin_graph_node_count": _int(
            (graph_drl_training_report.get("training_summary") or {}).get(
                "real_data_graph_node_count"
            )
        ),
        "full_admin_graph_edge_count": _int(
            (graph_drl_training_report.get("training_summary") or {}).get(
                "real_data_graph_edge_count"
            )
        ),
    }
    report["supported_claim"] = (
        _SUPPORTED_CLAIM if ready else "no_full_admin_energy_regularized_planner_claim_supported"
    )
    report["claim_boundary"] = {
        "max_claim_level": "bounded_support" if ready else "not_for_claim",
        "reason": (
            "Full-admin energy-regularized planner compares simulator rollouts "
            "over the 1017-node Graph-MDP with boundary and geographic-similarity "
            "edges, feasible-action geometry prior and full-admin GraphDQN "
            "holdout evidence; it is not observed policy-outcome evidence and "
            "does not use historical intervention logs."
        ),
    }
    report["observed_policy_outcome_superiority_claim"] = False
    report["empirical_superiority_claim"] = False
    report["remaining_gates"] = [
        "observed_policy_outcome_holdout_required",
        "off_policy_evaluation_on_real_intervention_logs_required",
        "causal_policy_effect_validation_required",
        "historical_policy_intervention_log_required",
        "cross_time_or_cross_city_conservative_planner_validation_required",
    ]
    return report


def _full_data_guard(
    report: dict[str, Any],
    similarity_evidence: dict[str, Any],
) -> dict[str, Any]:
    summary = report.get("real_data_graph_mdp_summary") or {}
    search = report.get("search_config") or {}
    passed = (
        _int(summary.get("real_data_graph_node_count")) == 1017
        and _int(summary.get("real_data_graph_edge_count")) == 7932
        and _int(summary.get("real_data_available_action_count")) == 1137
        and _int(similarity_evidence.get("similarity_edge_count")) == 5085
        and _int(similarity_evidence.get("non_adjacent_similarity_edge_count"))
        == 4835
        and _int(search.get("candidate_action_count")) == 1137
        and _int(search.get("evaluated_sequence_count")) > 1000
    )
    return {
        "passed": passed,
        "required_scope": "full_admin_graph",
        "graph_node_count": _int(summary.get("real_data_graph_node_count")),
        "graph_edge_count": _int(summary.get("real_data_graph_edge_count")),
        "available_action_count": _int(
            summary.get("real_data_available_action_count")
        ),
        "geographic_similarity_edge_count": _int(
            similarity_evidence.get("similarity_edge_count")
        ),
        "non_adjacent_similarity_edge_count": _int(
            similarity_evidence.get("non_adjacent_similarity_edge_count")
        ),
        "evaluated_sequence_count": _int(search.get("evaluated_sequence_count")),
    }


def _geographic_similarity_evidence(kernel: dict[str, Any]) -> dict[str, Any]:
    validation = validate_uwm_geographic_similarity_kernel(kernel)
    summary = kernel.get("summary") or {}
    controls = kernel.get("negative_controls") or {}
    ready = (
        validation.get("valid") is True
        and kernel.get("schema") == "uwm.geographic_similarity_kernel.v1"
        and kernel.get("geographic_similarity_kernel_ready") is True
        and _int(summary.get("panel_unit_count")) == 1017
        and _int(summary.get("similarity_edge_count")) == 5085
        and _int(summary.get("non_adjacent_similarity_edge_count")) == 4835
        and controls.get("rotated_target_similarity_control_passed") is True
        and kernel.get("observed_policy_outcome_superiority_claim") is False
    )
    return {
        "geographic_similarity_kernel_ready": ready,
        "kernel_id": kernel.get("kernel_id"),
        "validation_errors": validation.get("errors") or [],
        "panel_unit_count": _int(summary.get("panel_unit_count")),
        "similarity_edge_count": _int(summary.get("similarity_edge_count")),
        "non_adjacent_similarity_edge_count": _int(
            summary.get("non_adjacent_similarity_edge_count")
        ),
        "mean_configuration_similarity": _float(
            summary.get("mean_configuration_similarity")
        ),
        "rotated_target_similarity_control_passed": bool(
            controls.get("rotated_target_similarity_control_passed")
        ),
        "observed_policy_outcome_superiority_claim": False,
    }


def _full_admin_graph_dqn_alignment_ready(
    graph_drl_training_report: dict[str, Any],
    planner_report: dict[str, Any],
) -> bool:
    training = graph_drl_training_report.get("training_summary") or {}
    holdout = graph_drl_training_report.get("holdout_metrics") or {}
    learned = graph_drl_training_report.get("learned_policy_evaluation") or {}
    alignment = planner_report.get("search_value_alignment") or {}
    return (
        graph_drl_training_report.get("schema")
        == "uwm.livability_graph_drl_training_report.v1"
        and graph_drl_training_report.get("experiment_scope") == "full_admin_graph"
        and (graph_drl_training_report.get("full_data_guard") or {}).get("passed")
        is True
        and _int(training.get("real_data_graph_node_count")) == 1017
        and _int(training.get("real_data_graph_edge_count")) == 7932
        and _int(training.get("real_data_available_action_count")) == 1137
        and _int(training.get("training_sample_count")) == 1248
        and _float(holdout.get("q_return_mae"))
        < _float(holdout.get("train_mean_return_mae"))
        and _float(learned.get("advantage_over_traditional_static")) > 0.0
        and alignment.get("search_value_alignment_ready") is True
        and graph_drl_training_report.get("observed_policy_outcome_superiority_claim")
        is False
    )


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
