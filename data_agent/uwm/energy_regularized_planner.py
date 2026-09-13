"""Energy-regularized action-sequence planning for UWM livability Graph-MDP.

This planner addresses the search/value mismatch risk that appears once a
learned value model is available: the selected sequence must still stay inside
the observed feasible-action geometry of the real-data Graph-MDP.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .livability_graph_mdp_env import LivabilityGraphMDPEnv


UWM_ENERGY_REGULARIZED_ACTION_SEQUENCE_PLANNER_SCHEMA = (
    "uwm.energy_regularized_action_sequence_planner.v1"
)


def plan_with_energy_regularized_action_sequences(
    env: LivabilityGraphMDPEnv,
    *,
    graph_drl_training_report: dict[str, Any] | None,
    report_id: str,
    created_at: str,
    top_k_per_step: int = 12,
    energy_weight: float = 0.00035,
    ood_penalty_weight: float = 0.00055,
) -> dict[str, Any]:
    """Evaluate conservative two-step action sequences over a real Graph-MDP.

    The function uses the existing simulator through ``LivabilityGraphMDPEnv``.
    It does not use observed intervention outcomes and must not be interpreted
    as a policy-outcome superiority claim.
    """

    if top_k_per_step <= 0:
        raise ValueError("top_k_per_step must be positive")
    if energy_weight < 0.0:
        raise ValueError("energy_weight must be non-negative")
    if ood_penalty_weight < 0.0:
        raise ValueError("ood_penalty_weight must be non-negative")

    action_profiles = _action_profiles(env)
    energy_threshold = _energy_threshold(action_profiles)
    static_baseline = _traditional_static_baseline(env)
    candidate_indices = _candidate_action_indices(
        action_profiles,
        top_k_per_step=top_k_per_step,
    )
    evaluated = _evaluate_candidate_sequences(
        env,
        candidate_indices,
        action_profiles=action_profiles,
        energy_threshold=energy_threshold,
        energy_weight=energy_weight,
        ood_penalty_weight=ood_penalty_weight,
    )
    if not evaluated:
        raise ValueError("energy-regularized planner requires at least one evaluated sequence")

    raw_best = max(
        evaluated,
        key=lambda row: (row["raw_cumulative_reward"], row["regularized_score"]),
    )
    selected = max(
        evaluated,
        key=lambda row: (
            row["regularized_score"],
            row["raw_cumulative_reward"],
            -row["mean_behavior_energy"],
        ),
    )
    advantage = selected["raw_cumulative_reward"] - static_baseline["cumulative_reward"]
    alignment = _search_value_alignment(
        graph_drl_training_report or {},
        selected_sequence=selected,
        static_baseline=static_baseline,
    )
    ready = (
        advantage > 0.0
        and selected["mean_behavior_energy"] <= energy_threshold
        and selected["ood_action_drift"] <= 0.0
        and alignment["search_value_alignment_ready"] is True
    )
    return {
        "schema": UWM_ENERGY_REGULARIZED_ACTION_SEQUENCE_PLANNER_SCHEMA,
        "report_id": report_id,
        "created_at": created_at,
        "source_environment_schema": env.metadata["schema"],
        "source_observation_id": env.metadata["source_observation_id"],
        "planner_algorithm": {
            "algorithm": "energy_regularized_model_based_action_sequence_planner",
            "is_model_based": True,
            "is_model_free": False,
            "uses_behavior_prior_energy": True,
            "uses_ood_action_drift_guard": True,
            "uses_graph_dqn_alignment_evidence": bool(graph_drl_training_report),
            "world_model_backend": env.metadata["environment_backend"],
            "selection_objective": (
                "simulator_rollout_return_minus_behavior_energy_and_ood_drift_penalties"
            ),
        },
        "real_data_graph_mdp_summary": _real_data_summary(env),
        "search_config": {
            "horizon": env.config.horizon,
            "top_k_per_step": top_k_per_step,
            "candidate_action_count": len(env.available_actions),
            "candidate_action_index_count": len(candidate_indices),
            "evaluated_sequence_count": len(evaluated),
            "energy_weight": energy_weight,
            "ood_penalty_weight": ood_penalty_weight,
        },
        "behavior_prior": _behavior_prior_summary(action_profiles, energy_threshold),
        "selected_sequence": _sequence_output(selected, static_baseline),
        "raw_best_sequence": _sequence_output(raw_best, static_baseline),
        "traditional_static_baseline": static_baseline,
        "conservative_search_audit": {
            "evaluated_sequence_count": len(evaluated),
            "raw_best_sequence_raw_reward": round(raw_best["raw_cumulative_reward"], 9),
            "raw_best_sequence_mean_behavior_energy": round(
                raw_best["mean_behavior_energy"],
                9,
            ),
            "raw_best_sequence_ood_action_drift": round(raw_best["ood_action_drift"], 9),
            "selected_sequence_regularized_score": round(
                selected["regularized_score"],
                9,
            ),
            "selected_sequence_energy": round(selected["mean_behavior_energy"], 9),
            "selected_sequence_ood_action_drift": round(selected["ood_action_drift"], 9),
            "energy_threshold": round(energy_threshold, 9),
            "planner_exploitation_guard_passed": bool(
                selected["mean_behavior_energy"] <= energy_threshold
                and selected["ood_action_drift"] <= 0.0
            ),
            "top_candidate_audit": [
                _candidate_audit(row, static_baseline)
                for row in sorted(
                    evaluated,
                    key=lambda item: item["regularized_score"],
                    reverse=True,
                )[:5]
            ],
        },
        "search_value_alignment": alignment,
        "supported_claim": (
            "energy_regularized_model_based_action_sequence_planner_advantage_over_traditional_static"
            if ready
            else "no_energy_regularized_planner_advantage_claim_supported"
        ),
        "claim_boundary": {
            "max_claim_level": "bounded_support" if ready else "not_for_claim",
            "reason": (
                "energy-regularized planner compares simulator rollouts over the same "
                "real-data Graph-MDP, behavior-prior feasible action geometry and "
                "GraphDQN holdout evidence; it is not observed policy-outcome evidence"
            ),
        },
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "remaining_gates": [
            "observed_policy_outcome_holdout_required",
            "off_policy_evaluation_on_real_intervention_logs_required",
            "causal_policy_effect_validation_required",
            "larger_city_scale_conservative_planner_validation_required",
        ],
    }


def _evaluate_candidate_sequences(
    env: LivabilityGraphMDPEnv,
    candidate_indices: list[int],
    *,
    action_profiles: dict[int, dict[str, float]],
    energy_threshold: float,
    energy_weight: float,
    ood_penalty_weight: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for first_index in candidate_indices:
        for second_index in candidate_indices:
            if second_index == first_index:
                continue
            env.reset()
            first = env.step(first_index)
            second = env.step(second_index)
            actions = env.action_sequence()
            raw_reward = env.cumulative_reward()
            mean_energy = _mean(
                [
                    action_profiles[first_index]["behavior_energy"],
                    action_profiles[second_index]["behavior_energy"],
                ]
            )
            action_drift = max(0.0, mean_energy - energy_threshold)
            type_repeat_penalty = 0.0
            if actions[0].get("action_type") == actions[1].get("action_type"):
                type_repeat_penalty = 0.5
            target_distance = abs(
                action_profiles[first_index]["priority_rank_norm"]
                - action_profiles[second_index]["priority_rank_norm"]
            )
            diversity_bonus = 0.0001 * target_distance
            regularized_score = (
                raw_reward
                - energy_weight * (mean_energy + type_repeat_penalty)
                - ood_penalty_weight * action_drift
                + diversity_bonus
            )
            rollout = env.last_rollout() or {}
            rows.append(
                {
                    "action_indices": [first_index, second_index],
                    "action_sequence": actions,
                    "action_count": len(actions),
                    "raw_cumulative_reward": raw_reward,
                    "regularized_score": round(regularized_score, 12),
                    "mean_behavior_energy": round(mean_energy, 9),
                    "ood_action_drift": round(mean_energy - energy_threshold, 9),
                    "positive_ood_action_drift": round(action_drift, 9),
                    "type_repeat_penalty": round(type_repeat_penalty, 9),
                    "target_priority_distance": round(target_distance, 9),
                    "transition_rewards": [
                        float(first["reward"]),
                        float(second["reward"]),
                    ],
                    "rollout_trace_steps": [
                        str(step.get("step"))
                        for step in rollout.get("simulator_trace") or []
                    ],
                    "simulator_mechanism_sources": sorted(
                        {
                            str(step.get("mechanism_source"))
                            for step in rollout.get("simulator_trace") or []
                            if step.get("mechanism_source")
                        }
                    ),
                }
            )
    env.reset()
    return rows


def _candidate_action_indices(
    action_profiles: dict[int, dict[str, float]],
    *,
    top_k_per_step: int,
) -> list[int]:
    by_reason: dict[str, list[tuple[float, int]]] = {}
    for index, profile in action_profiles.items():
        reason = str(profile["mask_reason"])
        by_reason.setdefault(reason, []).append((profile["priority_score"], index))

    selected: set[int] = set()
    for rows in by_reason.values():
        rows.sort(reverse=True)
        selected.update(index for _score, index in rows[:top_k_per_step])
    if len(selected) < min(top_k_per_step, len(action_profiles)):
        ranked = sorted(
            (
                (profile["priority_score"], index)
                for index, profile in action_profiles.items()
            ),
            reverse=True,
        )
        selected.update(index for _score, index in ranked[:top_k_per_step])
    return sorted(selected)


def _action_profiles(env: LivabilityGraphMDPEnv) -> dict[int, dict[str, Any]]:
    node_by_unit = {
        str(node.get("unit_id") or node.get("node_id")): node
        for node in env.graph_state.get("nodes") or []
    }
    degree_by_unit = _degree_by_unit(env)
    action_count = max(1, len(env.available_actions))
    profiles: dict[int, dict[str, Any]] = {}
    ranked_priority: list[tuple[float, int]] = []
    for index, action in enumerate(env.available_actions):
        unit_id = _target_unit(action)
        node = node_by_unit.get(unit_id) or {}
        features = node.get("features") or {}
        action_type = str(action.get("action_type") or "")
        mask_reason = str(action.get("mask_reason") or "")
        priority_score = _action_need_score(features, action_type, mask_reason)
        ranked_priority.append((priority_score, index))
        profiles[index] = {
            "action_type": action_type,
            "mask_reason": mask_reason,
            "target_unit": unit_id,
            "priority_score": priority_score,
            "degree": float(degree_by_unit.get(unit_id, 0)),
            "heat_risk": _float(features.get("heat_risk")),
            "air_pollution_exposure": _float(features.get("air_pollution_exposure")),
            "service_accessibility": _float(features.get("service_accessibility")),
            "equity": _float(features.get("equity")),
            "livability": _float(features.get("livability")),
        }

    ranked_priority.sort(reverse=True)
    rank_by_index = {index: rank for rank, (_score, index) in enumerate(ranked_priority)}
    max_degree = max([profile["degree"] for profile in profiles.values()] or [1.0])
    type_counts = Counter(str(action.get("action_type") or "") for action in env.available_actions)
    reason_counts = Counter(str(action.get("mask_reason") or "") for action in env.available_actions)
    for index, profile in profiles.items():
        priority_rank_norm = rank_by_index[index] / max(1.0, float(action_count - 1))
        degree_norm = profile["degree"] / max(1.0, max_degree)
        rarity_penalty = 1.0 - (
            type_counts[str(profile["action_type"])] / float(action_count)
        )
        reason_rarity_penalty = 1.0 - (
            reason_counts[str(profile["mask_reason"])] / float(action_count)
        )
        behavior_energy = (
            0.55 * priority_rank_norm
            + 0.20 * (1.0 - degree_norm)
            + 0.15 * rarity_penalty
            + 0.10 * reason_rarity_penalty
        )
        profile["priority_rank_norm"] = round(priority_rank_norm, 9)
        profile["degree_norm"] = round(degree_norm, 9)
        profile["behavior_energy"] = round(behavior_energy, 9)
    return profiles


def _action_need_score(
    features: dict[str, Any],
    action_type: str,
    mask_reason: str,
) -> float:
    reason_weight = {
        "heat_risk_above_threshold": 3.0,
        "air_pollution_exposure_above_threshold": 2.0,
        "service_accessibility_below_threshold": 1.0,
        "generic_action_allowed": 0.0,
    }.get(mask_reason, 0.0)
    if action_type == "increase_green_infrastructure":
        need = _float(features.get("heat_risk")) + 0.25 * _float(features.get("equity"))
    elif action_type == "traffic_emission_control":
        need = _float(features.get("air_pollution_exposure")) + 0.20 * _float(
            features.get("equity")
        )
    elif action_type == "add_community_service":
        need = (1.0 - _float(features.get("service_accessibility"))) + 0.20 * _float(
            features.get("equity")
        )
    else:
        need = _float(features.get("equity"))
    return float(reason_weight + need)


def _energy_threshold(action_profiles: dict[int, dict[str, Any]]) -> float:
    energies = sorted(_float(profile.get("behavior_energy")) for profile in action_profiles.values())
    if not energies:
        return 0.0
    index = min(len(energies) - 1, max(0, int(round(0.70 * (len(energies) - 1)))))
    return round(energies[index], 9)


def _behavior_prior_summary(
    action_profiles: dict[int, dict[str, Any]],
    energy_threshold: float,
) -> dict[str, Any]:
    energies = [_float(profile.get("behavior_energy")) for profile in action_profiles.values()]
    return {
        "prior": "feasible_action_geometry_priority_degree_type_prior",
        "source": "real_data_graph_mdp_available_actions_and_admin_boundary_adjacency",
        "action_count": len(action_profiles),
        "mean_behavior_energy": round(_mean(energies), 9),
        "min_behavior_energy": round(min(energies) if energies else 0.0, 9),
        "max_behavior_energy": round(max(energies) if energies else 0.0, 9),
        "energy_threshold": round(energy_threshold, 9),
        "threshold_quantile": 0.70,
    }


def _traditional_static_baseline(env: LivabilityGraphMDPEnv) -> dict[str, Any]:
    action_index = _static_action_index(env.available_actions)
    env.reset()
    env.step(action_index)
    rollout = env.last_rollout() or {}
    output = {
        "baseline": "traditional_static_priority_single_step_same_graph_mdp",
        "action_index": action_index,
        "action_sequence": env.action_sequence(),
        "action_count": 1,
        "cumulative_reward": env.cumulative_reward(),
        "rollout_trace_steps": [
            str(step.get("step")) for step in rollout.get("simulator_trace") or []
        ],
    }
    env.reset()
    return output


def _static_action_index(actions: list[dict[str, Any]]) -> int:
    ranked = [
        (index, _static_priority_score(action), str(action.get("action_id") or ""))
        for index, action in enumerate(actions)
    ]
    ranked.sort(key=lambda item: (item[1], item[2]), reverse=True)
    return ranked[0][0]


def _static_priority_score(action: dict[str, Any]) -> float:
    reason_weight = {
        "heat_risk_above_threshold": 3.0,
        "air_pollution_exposure_above_threshold": 2.0,
        "service_accessibility_below_threshold": 1.0,
        "generic_action_allowed": 0.0,
    }
    return reason_weight.get(str(action.get("mask_reason")), 0.0)


def _real_data_summary(env: LivabilityGraphMDPEnv) -> dict[str, Any]:
    sources = env.metadata["real_data_sources"]
    return {
        "real_data_graph_node_count": _int(sources.get("admin_unit_count")),
        "real_data_graph_edge_count": _int(sources.get("admin_spatial_edge_count")),
        "real_data_available_action_count": _int(sources.get("available_action_count")),
        "mechanism_table_id": sources.get("mechanism_table_id"),
        "spatial_spillover_kernel_id": sources.get("spatial_spillover_kernel_id"),
        "spatial_spillover_directional_edge_count": _int(
            sources.get("spatial_spillover_directional_edge_count")
        ),
        "air_quality_holdout_id": sources.get("air_quality_holdout_id"),
    }


def _sequence_output(
    sequence: dict[str, Any],
    static_baseline: dict[str, Any],
) -> dict[str, Any]:
    reward = _float(sequence.get("raw_cumulative_reward"))
    return {
        "action_count": _int(sequence.get("action_count")),
        "action_indices": list(sequence.get("action_indices") or []),
        "action_sequence": list(sequence.get("action_sequence") or []),
        "raw_cumulative_reward": round(reward, 9),
        "regularized_score": round(_float(sequence.get("regularized_score")), 9),
        "mean_behavior_energy": round(_float(sequence.get("mean_behavior_energy")), 9),
        "ood_action_drift": round(_float(sequence.get("ood_action_drift")), 9),
        "advantage_over_traditional_static": round(
            reward - _float(static_baseline.get("cumulative_reward")),
            9,
        ),
        "transition_rewards": list(sequence.get("transition_rewards") or []),
        "simulator_mechanism_sources": list(
            sequence.get("simulator_mechanism_sources") or []
        ),
        "rollout_trace_steps": list(sequence.get("rollout_trace_steps") or []),
    }


def _candidate_audit(
    row: dict[str, Any],
    static_baseline: dict[str, Any],
) -> dict[str, Any]:
    return {
        "action_indices": list(row.get("action_indices") or []),
        "action_ids": [
            str(action.get("action_id") or "")
            for action in row.get("action_sequence") or []
        ],
        "raw_cumulative_reward": round(_float(row.get("raw_cumulative_reward")), 9),
        "regularized_score": round(_float(row.get("regularized_score")), 9),
        "mean_behavior_energy": round(_float(row.get("mean_behavior_energy")), 9),
        "ood_action_drift": round(_float(row.get("ood_action_drift")), 9),
        "advantage_over_traditional_static": round(
            _float(row.get("raw_cumulative_reward"))
            - _float(static_baseline.get("cumulative_reward")),
            9,
        ),
    }


def _search_value_alignment(
    graph_drl_training_report: dict[str, Any],
    *,
    selected_sequence: dict[str, Any],
    static_baseline: dict[str, Any],
) -> dict[str, Any]:
    holdout = graph_drl_training_report.get("holdout_metrics") or {}
    training = graph_drl_training_report.get("training_summary") or {}
    learned = graph_drl_training_report.get("learned_policy_evaluation") or {}
    algorithm = graph_drl_training_report.get("drl_algorithm") or {}
    case_count = _int(holdout.get("case_count"))
    win_count = _int(holdout.get("holdout_win_count_vs_train_mean"))
    win_rate = win_count / case_count if case_count else 0.0
    graph_available = (
        graph_drl_training_report.get("schema")
        == "uwm.livability_graph_drl_training_report.v1"
        and algorithm.get("algorithm") == "graph_dqn_fitted_q_model_based_rl"
    )
    reward_advantage = _float(selected_sequence.get("raw_cumulative_reward")) - _float(
        static_baseline.get("cumulative_reward")
    )
    ready = (
        graph_available
        and _float(holdout.get("q_return_mae")) < _float(
            holdout.get("train_mean_return_mae")
        )
        and win_rate > 0.9
        and _float(learned.get("advantage_over_traditional_static")) > 0.0
        and reward_advantage > 0.0
        and graph_drl_training_report.get("observed_policy_outcome_superiority_claim")
        is False
    )
    return {
        "graph_dqn_report_available": graph_available,
        "graph_dqn_training_sample_count": _int(training.get("training_sample_count")),
        "graph_dqn_holdout_case_count": case_count,
        "graph_dqn_holdout_win_rate_vs_train_mean": round(win_rate, 9),
        "graph_dqn_q_return_mae": _float(holdout.get("q_return_mae")),
        "graph_dqn_train_mean_return_mae": _float(
            holdout.get("train_mean_return_mae")
        ),
        "graph_dqn_advantage_over_traditional_static": _float(
            learned.get("advantage_over_traditional_static")
        ),
        "selected_sequence_reward_beats_traditional_static": reward_advantage > 0.0,
        "selected_sequence_reward_advantage_over_traditional_static": round(
            reward_advantage,
            9,
        ),
        "search_value_alignment_ready": ready,
        "observed_policy_outcome_superiority_claim": False,
    }


def _degree_by_unit(env: LivabilityGraphMDPEnv) -> dict[str, int]:
    degree: dict[str, int] = {}
    for edge in env.graph_state.get("edges") or []:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source:
            degree[source] = degree.get(source, 0) + 1
        if target:
            degree[target] = degree.get(target, 0) + 1
    return degree


def _target_unit(action: dict[str, Any]) -> str:
    targets = action.get("target_units")
    if isinstance(targets, list) and targets:
        return str(targets[0])
    return str(action.get("target_unit") or "")


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _float(value: Any, default: float = 0.0) -> float:
    if value in {None, ""}:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    if value in {None, ""}:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default
