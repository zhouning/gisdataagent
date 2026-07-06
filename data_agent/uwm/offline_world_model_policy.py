"""Offline action-conditioned world model and policy improvement for UWM replay."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np


OFFLINE_WORLD_MODEL_POLICY_REPORT_SCHEMA = "uwm.offline_world_model_policy_report.v1"
OFFLINE_WORLD_MODEL_ROLLOUT_PLANNER_REPORT_SCHEMA = "uwm.offline_world_model_rollout_planner_report.v1"
DEFAULT_OFFLINE_WORLD_MODEL_POLICY_BACKEND = "ridge_action_conditioned_world_model_policy_v0"
DEFAULT_OFFLINE_WORLD_MODEL_ROLLOUT_PLANNER_BACKEND = "multi_step_action_conditioned_learned_rollout_v0"

FEATURE_NAMES = [
    "bias",
    "action_increase_green_infrastructure",
    "action_traffic_emission_control",
    "action_add_community_service",
    "action_other",
    "intensity",
    "target_heat_risk",
    "target_air_pollution_exposure",
    "target_service_gap",
    "target_equity",
    "target_livability_gap",
    "target_degree_norm",
    "mask_heat_risk",
    "mask_air_pollution",
    "mask_service_gap",
    "step_index_norm",
]

TARGET_NAMES = [
    "reward",
    "heat_risk_delta",
    "air_pollution_exposure_delta",
    "service_accessibility_delta",
    "equity_delta",
    "livability_delta",
]


def train_offline_world_model_policy(
    search_report: dict[str, Any],
    *,
    model_id: str,
    created_at: str,
    holdout_stride: int = 5,
    ridge: float = 0.001,
    uncertainty_penalty: float = 0.5,
) -> dict[str, Any]:
    """Fit a replay world model and derive a conservative one-step policy."""

    if holdout_stride < 2:
        raise ValueError("holdout_stride must be at least 2")
    graph_state = search_report.get("graph_mdp_state") or {}
    transitions = list((search_report.get("trajectory_dataset") or {}).get("transitions") or [])
    if len(transitions) < 3:
        raise ValueError("offline world model policy requires at least three replay transitions")

    node_features = _node_features_by_unit(graph_state)
    degree_by_unit = _degree_by_unit(graph_state)
    node_count = max(1, len(node_features))
    rows = [
        _training_row(
            transition,
            node_features=node_features,
            degree_by_unit=degree_by_unit,
            node_count=node_count,
        )
        for transition in transitions
    ]
    feature_matrix = np.array([row["features"] for row in rows], dtype=float)
    targets = np.array([row["targets"] for row in rows], dtype=float)
    holdout_indices = _holdout_indices(len(rows), holdout_stride)
    holdout_set = set(holdout_indices)
    train_indices = [index for index in range(len(rows)) if index not in holdout_set]
    if not train_indices:
        train_indices = [index for index in range(len(rows)) if index != holdout_indices[-1]]
        holdout_indices = [holdout_indices[-1]]

    x_train = feature_matrix[train_indices]
    y_train = targets[train_indices]
    x_holdout = feature_matrix[holdout_indices]
    y_holdout = targets[holdout_indices]

    coefficients = _fit_ridge_multi_output(x_train, y_train, ridge)
    train_predictions = x_train @ coefficients
    holdout_predictions = x_holdout @ coefficients
    train_mean = np.mean(y_train, axis=0)
    baseline_predictions = np.tile(train_mean, (len(holdout_indices), 1))
    holdout_mae_by_target = _mae_by_target(y_holdout, holdout_predictions)
    baseline_mae_by_target = _mae_by_target(y_holdout, baseline_predictions)
    reward_holdout_errors = np.abs(y_holdout[:, 0] - holdout_predictions[:, 0])
    reward_baseline_errors = np.abs(y_holdout[:, 0] - baseline_predictions[:, 0])

    residuals = y_train[:, 0] - train_predictions[:, 0]
    residual_std_by_action_type = _reward_residual_std_by_action_type(
        [rows[index] for index in train_indices],
        residuals,
    )
    global_reward_residual_std = float(np.std(residuals)) if residuals.size else 0.0
    ranking = _candidate_policy_ranking(
        graph_state,
        coefficients,
        residual_std_by_action_type=residual_std_by_action_type,
        global_reward_residual_std=global_reward_residual_std,
        uncertainty_penalty=uncertainty_penalty,
        node_features=node_features,
        degree_by_unit=degree_by_unit,
        node_count=node_count,
    )
    static_action = _normalise_static_action(
        ((search_report.get("static_single_step_baseline") or {}).get("action_sequence") or [{}])[0]
    )
    actual_replay_evaluation = _actual_replay_policy_evaluation(
        selected_action=(ranking[0] if ranking else {}),
        static_action=static_action,
        transitions=transitions,
    )
    reward_mae = holdout_mae_by_target["reward"]
    reward_baseline_mae = baseline_mae_by_target["reward"]
    replay_advantage = _float(actual_replay_evaluation.get("replay_reward_advantage"))
    supported_claim = (
        "offline_world_model_policy_improves_replay_static_baseline"
        if reward_mae < reward_baseline_mae
        and actual_replay_evaluation.get("comparable") is True
        and replay_advantage > 0
        else "no_offline_world_model_policy_advantage_claim_supported"
    )
    return {
        "schema": OFFLINE_WORLD_MODEL_POLICY_REPORT_SCHEMA,
        "model_id": model_id,
        "created_at": created_at,
        "backend": DEFAULT_OFFLINE_WORLD_MODEL_POLICY_BACKEND,
        "source_report_schema": search_report.get("schema"),
        "world_model": {
            "model_class": "linear_ridge_action_conditioned_dynamics",
            "feature_names": FEATURE_NAMES,
            "target_names": TARGET_NAMES,
            "coefficients": _coefficient_table(coefficients),
            "reward_residual_std_by_action_type": {
                key: round(float(value), 9)
                for key, value in sorted(residual_std_by_action_type.items())
            },
            "global_reward_residual_std": round(global_reward_residual_std, 9),
        },
        "training_summary": {
            "transition_count": len(transitions),
            "train_count": len(train_indices),
            "holdout_count": len(holdout_indices),
            "holdout_stride": holdout_stride,
            "ridge": ridge,
            "uncertainty_penalty": uncertainty_penalty,
        },
        "holdout_metrics": {
            "reward_mae": round(reward_mae, 9),
            "reward_win_count_vs_train_mean": int(np.sum(reward_holdout_errors < reward_baseline_errors)),
            "case_count": len(holdout_indices),
            "dynamics_mae_by_target": {
                key: round(value, 9)
                for key, value in holdout_mae_by_target.items()
                if key != "reward"
            },
        },
        "baseline_metrics": {
            "baseline": "train_mean_dynamics_and_reward",
            "train_mean_reward": round(float(train_mean[0]), 9),
            "train_mean_reward_mae": round(reward_baseline_mae, 9),
            "train_mean_mae_by_target": {
                key: round(value, 9)
                for key, value in baseline_mae_by_target.items()
            },
        },
        "conservative_policy": {
            "policy_backend": "one_step_conservative_model_policy_ranking_v0",
            "uncertainty_penalty": uncertainty_penalty,
            "candidate_ranking": ranking,
            "selected_action": ranking[0] if ranking else {},
            "static_single_step_action": static_action,
            "actual_replay_evaluation": actual_replay_evaluation,
        },
        "supported_claim": supported_claim,
        "empirical_superiority_claim": False,
        "claim_boundary": {
            "max_claim_level": "bounded_support"
            if supported_claim == "offline_world_model_policy_improves_replay_static_baseline"
            else "not_for_claim",
            "reason": (
                "offline world model policy is evaluated on simulator replay holdout and replay rewards; "
                "observed policy outcome gates remain open"
            ),
        },
        "remaining_gates": [
            "observed_policy_outcome_holdout_required",
            "off_policy_evaluation_on_observed_or_counterfactual_policy_data_required",
            "causal_policy_effect_validation_required",
            "external_air_pollution_holdout_required",
        ],
    }


def plan_with_offline_world_model_rollouts(
    search_report: dict[str, Any],
    *,
    model_id: str,
    created_at: str,
    horizon: int = 2,
    beam_width: int = 5,
    holdout_stride: int = 5,
    ridge: float = 0.001,
    uncertainty_penalty: float = 0.5,
) -> dict[str, Any]:
    """Train a replay world model and use it for multi-step imagined planning."""

    if horizon <= 0:
        raise ValueError("horizon must be positive")
    if beam_width <= 0:
        raise ValueError("beam_width must be positive")
    if holdout_stride < 2:
        raise ValueError("holdout_stride must be at least 2")

    graph_state = search_report.get("graph_mdp_state") or {}
    transitions = list((search_report.get("trajectory_dataset") or {}).get("transitions") or [])
    if len(transitions) < 3:
        raise ValueError("offline world model rollout planner requires at least three replay transitions")

    node_features = _node_features_by_unit(graph_state)
    degree_by_unit = _degree_by_unit(graph_state)
    node_count = max(1, len(node_features))
    rows = [
        _training_row(
            transition,
            node_features=node_features,
            degree_by_unit=degree_by_unit,
            node_count=node_count,
        )
        for transition in transitions
    ]
    feature_matrix = np.array([row["features"] for row in rows], dtype=float)
    targets = np.array([row["targets"] for row in rows], dtype=float)
    holdout_indices = _holdout_indices(len(rows), holdout_stride)
    holdout_set = set(holdout_indices)
    train_indices = [index for index in range(len(rows)) if index not in holdout_set]
    if not train_indices:
        train_indices = [index for index in range(len(rows)) if index != holdout_indices[-1]]
        holdout_indices = [holdout_indices[-1]]

    x_train = feature_matrix[train_indices]
    y_train = targets[train_indices]
    x_holdout = feature_matrix[holdout_indices]
    y_holdout = targets[holdout_indices]

    coefficients = _fit_ridge_multi_output(x_train, y_train, ridge)
    train_predictions = x_train @ coefficients
    holdout_predictions = x_holdout @ coefficients
    train_mean = np.mean(y_train, axis=0)
    baseline_predictions = np.tile(train_mean, (len(holdout_indices), 1))
    holdout_mae_by_target = _mae_by_target(y_holdout, holdout_predictions)
    baseline_mae_by_target = _mae_by_target(y_holdout, baseline_predictions)
    reward_holdout_errors = np.abs(y_holdout[:, 0] - holdout_predictions[:, 0])
    reward_baseline_errors = np.abs(y_holdout[:, 0] - baseline_predictions[:, 0])

    residuals = y_train[:, 0] - train_predictions[:, 0]
    residual_std_by_action_type = _reward_residual_std_by_action_type(
        [rows[index] for index in train_indices],
        residuals,
    )
    global_reward_residual_std = float(np.std(residuals)) if residuals.size else 0.0
    one_step_ranking = _candidate_policy_ranking(
        graph_state,
        coefficients,
        residual_std_by_action_type=residual_std_by_action_type,
        global_reward_residual_std=global_reward_residual_std,
        uncertainty_penalty=uncertainty_penalty,
        node_features=node_features,
        degree_by_unit=degree_by_unit,
        node_count=node_count,
    )
    static_action = _normalise_static_action(
        ((search_report.get("static_single_step_baseline") or {}).get("action_sequence") or [{}])[0]
    )
    action_by_id = _action_by_id(graph_state)
    one_step_action = action_by_id.get(str((one_step_ranking[0] if one_step_ranking else {}).get("action_id") or ""))
    static_candidate = action_by_id.get(str(static_action.get("action_id") or ""), static_action)
    sequence_ranking = _learned_rollout_sequence_ranking(
        graph_state,
        coefficients,
        horizon=horizon,
        beam_width=beam_width,
        residual_std_by_action_type=residual_std_by_action_type,
        global_reward_residual_std=global_reward_residual_std,
        uncertainty_penalty=uncertainty_penalty,
        node_features=node_features,
        degree_by_unit=degree_by_unit,
        node_count=node_count,
    )
    selected_sequence = sequence_ranking[0] if sequence_ranking else {}
    static_baseline = _imagine_fixed_sequence(
        [static_candidate],
        coefficients=coefficients,
        residual_std_by_action_type=residual_std_by_action_type,
        global_reward_residual_std=global_reward_residual_std,
        uncertainty_penalty=uncertainty_penalty,
        node_features=node_features,
        degree_by_unit=degree_by_unit,
        node_count=node_count,
    )
    one_step_baseline = _imagine_fixed_sequence(
        [one_step_action] if one_step_action else [],
        coefficients=coefficients,
        residual_std_by_action_type=residual_std_by_action_type,
        global_reward_residual_std=global_reward_residual_std,
        uncertainty_penalty=uncertainty_penalty,
        node_features=node_features,
        degree_by_unit=degree_by_unit,
        node_count=node_count,
    )
    reward_mae = holdout_mae_by_target["reward"]
    reward_baseline_mae = baseline_mae_by_target["reward"]
    selected_score = _float(selected_sequence.get("imagined_cumulative_conservative_reward"))
    static_score = _float(static_baseline.get("imagined_cumulative_conservative_reward"))
    one_step_score = _float(one_step_baseline.get("imagined_cumulative_conservative_reward"))
    supported_claim = (
        "learned_world_model_rollout_improves_imagined_static_and_one_step_baselines"
        if reward_mae < reward_baseline_mae and selected_score > static_score and selected_score > one_step_score
        else "no_learned_world_model_rollout_advantage_claim_supported"
    )
    return {
        "schema": OFFLINE_WORLD_MODEL_ROLLOUT_PLANNER_REPORT_SCHEMA,
        "model_id": model_id,
        "created_at": created_at,
        "backend": DEFAULT_OFFLINE_WORLD_MODEL_ROLLOUT_PLANNER_BACKEND,
        "source_report_schema": search_report.get("schema"),
        "world_model": {
            "model_class": "linear_ridge_action_conditioned_dynamics",
            "feature_names": FEATURE_NAMES,
            "target_names": TARGET_NAMES,
            "coefficients": _coefficient_table(coefficients),
            "reward_residual_std_by_action_type": {
                key: round(float(value), 9)
                for key, value in sorted(residual_std_by_action_type.items())
            },
            "global_reward_residual_std": round(global_reward_residual_std, 9),
        },
        "training_summary": {
            "transition_count": len(transitions),
            "train_count": len(train_indices),
            "holdout_count": len(holdout_indices),
            "holdout_stride": holdout_stride,
            "ridge": ridge,
            "uncertainty_penalty": uncertainty_penalty,
        },
        "holdout_metrics": {
            "reward_mae": round(reward_mae, 9),
            "reward_win_count_vs_train_mean": int(np.sum(reward_holdout_errors < reward_baseline_errors)),
            "case_count": len(holdout_indices),
            "dynamics_mae_by_target": {
                key: round(value, 9)
                for key, value in holdout_mae_by_target.items()
                if key != "reward"
            },
        },
        "baseline_metrics": {
            "baseline": "train_mean_dynamics_and_reward",
            "train_mean_reward": round(float(train_mean[0]), 9),
            "train_mean_reward_mae": round(reward_baseline_mae, 9),
            "train_mean_mae_by_target": {
                key: round(value, 9)
                for key, value in baseline_mae_by_target.items()
            },
        },
        "learned_rollout_planner": {
            "policy_backend": DEFAULT_OFFLINE_WORLD_MODEL_ROLLOUT_PLANNER_BACKEND,
            "search_config": {
                "horizon": horizon,
                "beam_width": beam_width,
                "candidate_action_count": len(action_by_id),
                "uncertainty_penalty": uncertainty_penalty,
                "state_update": "apply_predicted_dynamics_to_target_unit_latent_features",
            },
            "sequence_ranking": sequence_ranking,
            "selected_sequence": selected_sequence,
            "one_step_policy_baseline": one_step_baseline,
            "static_single_step_baseline": static_baseline,
            "imagined_advantage_over_one_step_policy": round(selected_score - one_step_score, 9),
            "imagined_advantage_over_static_single_step": round(selected_score - static_score, 9),
        },
        "supported_claim": supported_claim,
        "empirical_superiority_claim": False,
        "claim_boundary": {
            "max_claim_level": "bounded_support"
            if supported_claim == "learned_world_model_rollout_improves_imagined_static_and_one_step_baselines"
            else "not_for_claim",
            "reason": (
                "multi-step planner uses learned replay dynamics for imagined rollouts; "
                "observed policy outcome gates remain open"
            ),
        },
        "remaining_gates": [
            "observed_policy_outcome_holdout_required",
            "off_policy_evaluation_on_observed_or_counterfactual_policy_data_required",
            "causal_policy_effect_validation_required",
            "external_air_pollution_holdout_required",
        ],
    }


def _action_by_id(graph_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(action.get("action_id")): dict(action)
        for action in graph_state.get("available_actions") or []
        if action.get("action_id") is not None
    }


def _learned_rollout_sequence_ranking(
    graph_state: dict[str, Any],
    coefficients: np.ndarray,
    *,
    horizon: int,
    beam_width: int,
    residual_std_by_action_type: dict[str, float],
    global_reward_residual_std: float,
    uncertainty_penalty: float,
    node_features: dict[str, dict[str, float]],
    degree_by_unit: dict[str, int],
    node_count: int,
) -> list[dict[str, Any]]:
    candidates = list(_action_by_id(graph_state).values())
    if not candidates:
        raise ValueError("offline world model rollout planner requires at least one candidate action")
    beams = [
        {
            "action_sequence": [],
            "imagined_steps": [],
            "state_features": _clone_node_features(node_features),
            "imagined_cumulative_predicted_reward": 0.0,
            "imagined_cumulative_conservative_reward": 0.0,
        }
    ]
    for step_index in range(horizon):
        expanded = []
        for beam in beams:
            used_action_ids = {str(action.get("action_id")) for action in beam["action_sequence"]}
            for action in candidates:
                if str(action.get("action_id")) in used_action_ids:
                    continue
                step, next_state = _imagine_action_step(
                    action,
                    coefficients=coefficients,
                    residual_std_by_action_type=residual_std_by_action_type,
                    global_reward_residual_std=global_reward_residual_std,
                    uncertainty_penalty=uncertainty_penalty,
                    state_features=beam["state_features"],
                    degree_by_unit=degree_by_unit,
                    node_count=node_count,
                    step_index=float(step_index),
                )
                expanded.append(
                    {
                        "action_sequence": [*beam["action_sequence"], dict(action)],
                        "imagined_steps": [*beam["imagined_steps"], step],
                        "state_features": next_state,
                        "imagined_cumulative_predicted_reward": float(
                            beam["imagined_cumulative_predicted_reward"]
                        )
                        + step["predicted_reward"],
                        "imagined_cumulative_conservative_reward": float(
                            beam["imagined_cumulative_conservative_reward"]
                        )
                        + step["conservative_reward"],
                    }
                )
        if not expanded:
            break
        expanded.sort(
            key=lambda item: (
                item["imagined_cumulative_conservative_reward"],
                item["imagined_cumulative_predicted_reward"],
            ),
            reverse=True,
        )
        beams = expanded[:beam_width]
    return [_public_sequence(beam) for beam in beams]


def _imagine_fixed_sequence(
    actions: list[dict[str, Any]],
    *,
    coefficients: np.ndarray,
    residual_std_by_action_type: dict[str, float],
    global_reward_residual_std: float,
    uncertainty_penalty: float,
    node_features: dict[str, dict[str, float]],
    degree_by_unit: dict[str, int],
    node_count: int,
) -> dict[str, Any]:
    state_features = _clone_node_features(node_features)
    beam = {
        "action_sequence": [],
        "imagined_steps": [],
        "state_features": state_features,
        "imagined_cumulative_predicted_reward": 0.0,
        "imagined_cumulative_conservative_reward": 0.0,
    }
    for step_index, action in enumerate(action for action in actions if action):
        step, state_features = _imagine_action_step(
            action,
            coefficients=coefficients,
            residual_std_by_action_type=residual_std_by_action_type,
            global_reward_residual_std=global_reward_residual_std,
            uncertainty_penalty=uncertainty_penalty,
            state_features=state_features,
            degree_by_unit=degree_by_unit,
            node_count=node_count,
            step_index=float(step_index),
        )
        beam["action_sequence"].append(dict(action))
        beam["imagined_steps"].append(step)
        beam["state_features"] = state_features
        beam["imagined_cumulative_predicted_reward"] = float(
            beam["imagined_cumulative_predicted_reward"]
        ) + step["predicted_reward"]
        beam["imagined_cumulative_conservative_reward"] = float(
            beam["imagined_cumulative_conservative_reward"]
        ) + step["conservative_reward"]
    return _public_sequence(beam)


def _imagine_action_step(
    action: dict[str, Any],
    *,
    coefficients: np.ndarray,
    residual_std_by_action_type: dict[str, float],
    global_reward_residual_std: float,
    uncertainty_penalty: float,
    state_features: dict[str, dict[str, float]],
    degree_by_unit: dict[str, int],
    node_count: int,
    step_index: float,
) -> tuple[dict[str, Any], dict[str, dict[str, float]]]:
    feature_vector = np.array(
        _features_for_action(
            action,
            node_features=state_features,
            degree_by_unit=degree_by_unit,
            node_count=node_count,
            step_index=step_index,
        ),
        dtype=float,
    )
    prediction = feature_vector @ coefficients
    action_type = str(action.get("action_type") or "unknown")
    residual_std = residual_std_by_action_type.get(action_type, global_reward_residual_std)
    conservative_reward = float(prediction[0]) - uncertainty_penalty * float(residual_std)
    predicted_dynamics = {
        name: round(float(value), 9)
        for name, value in zip(TARGET_NAMES[1:], prediction[1:])
    }
    next_state = _apply_predicted_dynamics_to_state(state_features, action, predicted_dynamics)
    target_units = _target_units(action)
    return (
        {
            "step_index": int(step_index),
            "action": dict(action),
            "predicted_reward": round(float(prediction[0]), 9),
            "reward_uncertainty": round(float(residual_std), 9),
            "conservative_reward": round(conservative_reward, 9),
            "predicted_dynamics": predicted_dynamics,
            "post_state_features": _state_features_for_units(next_state, target_units),
        },
        next_state,
    )


def _apply_predicted_dynamics_to_state(
    state_features: dict[str, dict[str, float]],
    action: dict[str, Any],
    predicted_dynamics: dict[str, float],
) -> dict[str, dict[str, float]]:
    next_state = _clone_node_features(state_features)
    for unit_id in _target_units(action):
        features = next_state.setdefault(
            unit_id,
            {
                "heat_risk": 0.0,
                "air_pollution_exposure": 0.0,
                "service_accessibility": 0.0,
                "equity": 0.0,
                "livability": 0.0,
            },
        )
        features["heat_risk"] = _clamp01(features["heat_risk"] + predicted_dynamics["heat_risk_delta"])
        features["air_pollution_exposure"] = _clamp01(
            features["air_pollution_exposure"] + predicted_dynamics["air_pollution_exposure_delta"]
        )
        features["service_accessibility"] = _clamp01(
            features["service_accessibility"] + predicted_dynamics["service_accessibility_delta"]
        )
        features["equity"] = _clamp01(features["equity"] + predicted_dynamics["equity_delta"])
        features["livability"] = _clamp01(features["livability"] + predicted_dynamics["livability_delta"])
    return next_state


def _public_sequence(beam: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_count": len(beam["action_sequence"]),
        "action_sequence": beam["action_sequence"],
        "imagined_cumulative_predicted_reward": round(
            float(beam["imagined_cumulative_predicted_reward"]),
            9,
        ),
        "imagined_cumulative_conservative_reward": round(
            float(beam["imagined_cumulative_conservative_reward"]),
            9,
        ),
        "imagined_steps": beam["imagined_steps"],
    }


def _clone_node_features(node_features: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    return {
        str(unit_id): {
            "heat_risk": _float(features.get("heat_risk")),
            "air_pollution_exposure": _float(features.get("air_pollution_exposure")),
            "service_accessibility": _float(features.get("service_accessibility")),
            "equity": _float(features.get("equity")),
            "livability": _float(features.get("livability")),
        }
        for unit_id, features in node_features.items()
    }


def _state_features_for_units(
    state_features: dict[str, dict[str, float]],
    unit_ids: list[str],
) -> dict[str, dict[str, float]]:
    selected = unit_ids or list(state_features)
    return {
        unit_id: {
            key: round(_float(value), 9)
            for key, value in (state_features.get(unit_id) or {}).items()
        }
        for unit_id in selected
        if unit_id in state_features
    }


def _target_units(action: dict[str, Any]) -> list[str]:
    targets = action.get("target_units")
    if isinstance(targets, list) and targets:
        return [str(unit_id) for unit_id in targets]
    if action.get("target_unit") is not None:
        return [str(action.get("target_unit"))]
    return []


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _training_row(
    transition: dict[str, Any],
    *,
    node_features: dict[str, dict[str, float]],
    degree_by_unit: dict[str, int],
    node_count: int,
) -> dict[str, Any]:
    action = transition.get("action") or {}
    step_index = _float((transition.get("transition") or {}).get("step_index"))
    return {
        "features": _features_for_action(
            action,
            node_features=node_features,
            degree_by_unit=degree_by_unit,
            node_count=node_count,
            step_index=step_index,
        ),
        "targets": _targets_for_transition(transition),
        "action_type": str(action.get("action_type") or "unknown"),
        "action_id": str(action.get("action_id") or ""),
    }


def _features_for_action(
    action: dict[str, Any],
    *,
    node_features: dict[str, dict[str, float]],
    degree_by_unit: dict[str, int],
    node_count: int,
    step_index: float,
) -> list[float]:
    action_type = str(action.get("action_type") or "").lower()
    mask_reason = str(action.get("mask_reason") or "").lower()
    target_unit = _first_target_unit(action)
    features = node_features.get(target_unit) or {}
    is_green = action_type in {"increase_green", "increase_green_infrastructure", "urban_greening"}
    is_traffic = action_type in {"traffic_emission_control", "low_emission_zone"}
    is_service = action_type in {"add_community_service", "service_accessibility_improvement"}
    return [
        1.0,
        1.0 if is_green else 0.0,
        1.0 if is_traffic else 0.0,
        1.0 if is_service else 0.0,
        0.0 if (is_green or is_traffic or is_service) else 1.0,
        _float(action.get("intensity"), default=1.0),
        _float(features.get("heat_risk")),
        _float(features.get("air_pollution_exposure")),
        max(0.0, 1.0 - _float(features.get("service_accessibility"))),
        _float(features.get("equity")),
        max(0.0, 1.0 - _float(features.get("livability"))),
        _float(degree_by_unit.get(target_unit)) / max(1.0, float(node_count - 1)),
        1.0 if "heat" in mask_reason else 0.0,
        1.0 if "air_pollution" in mask_reason else 0.0,
        1.0 if "service" in mask_reason else 0.0,
        step_index / 10.0,
    ]


def _targets_for_transition(transition: dict[str, Any]) -> list[float]:
    aggregate = _aggregate_delta(transition.get("next_state_delta") or {})
    return [
        _float(transition.get("reward")),
        aggregate["heat_risk_delta"],
        aggregate["air_pollution_exposure_delta"],
        aggregate["service_accessibility_delta"],
        aggregate["equity_delta"],
        aggregate["livability_delta"],
    ]


def _aggregate_delta(next_state_delta: dict[str, Any]) -> dict[str, float]:
    totals = {
        "heat_risk_delta": 0.0,
        "air_pollution_exposure_delta": 0.0,
        "service_accessibility_delta": 0.0,
        "equity_delta": 0.0,
        "livability_delta": 0.0,
    }
    per_unit = next_state_delta.get("per_unit") or {}
    for row in per_unit.values():
        if not isinstance(row, dict):
            continue
        for key in totals:
            totals[key] += _float(row.get(key))
    return {key: round(value, 9) for key, value in totals.items()}


def _node_features_by_unit(graph_state: dict[str, Any]) -> dict[str, dict[str, float]]:
    nodes = {}
    for node in graph_state.get("nodes") or []:
        unit_id = str(node.get("unit_id") or node.get("node_id") or "")
        features = node.get("features") or {}
        if unit_id:
            nodes[unit_id] = {
                "heat_risk": _float(features.get("heat_risk")),
                "air_pollution_exposure": _float(features.get("air_pollution_exposure")),
                "service_accessibility": _float(features.get("service_accessibility")),
                "equity": _float(features.get("equity")),
                "livability": _float(features.get("livability")),
            }
    return nodes


def _degree_by_unit(graph_state: dict[str, Any]) -> dict[str, int]:
    degree: dict[str, int] = {}
    for edge in graph_state.get("edges") or []:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source:
            degree[source] = degree.get(source, 0) + 1
        if target:
            degree[target] = degree.get(target, 0) + 1
    return degree


def _fit_ridge_multi_output(x_train: np.ndarray, y_train: np.ndarray, ridge: float) -> np.ndarray:
    penalty = np.eye(x_train.shape[1]) * ridge
    penalty[0, 0] = 0.0
    xtx = x_train.T @ x_train + penalty
    xty = x_train.T @ y_train
    try:
        return np.linalg.solve(xtx, xty)
    except np.linalg.LinAlgError:
        return np.linalg.pinv(xtx) @ xty


def _holdout_indices(row_count: int, holdout_stride: int) -> list[int]:
    indices = [index for index in range(row_count) if (index + 1) % holdout_stride == 0]
    if not indices:
        return [row_count - 1]
    if len(indices) == row_count:
        return [row_count - 1]
    return indices


def _mae_by_target(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    if actual.size == 0:
        return {name: 0.0 for name in TARGET_NAMES}
    errors = np.mean(np.abs(actual - predicted), axis=0)
    return {name: float(value) for name, value in zip(TARGET_NAMES, errors)}


def _reward_residual_std_by_action_type(
    train_rows: list[dict[str, Any]],
    residuals: np.ndarray,
) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row, residual in zip(train_rows, residuals):
        grouped[str(row.get("action_type") or "unknown")].append(float(residual))
    return {
        action_type: float(np.std(values)) if len(values) > 1 else 0.0
        for action_type, values in grouped.items()
    }


def _candidate_policy_ranking(
    graph_state: dict[str, Any],
    coefficients: np.ndarray,
    *,
    residual_std_by_action_type: dict[str, float],
    global_reward_residual_std: float,
    uncertainty_penalty: float,
    node_features: dict[str, dict[str, float]],
    degree_by_unit: dict[str, int],
    node_count: int,
) -> list[dict[str, Any]]:
    scored = []
    for action in graph_state.get("available_actions") or []:
        features = np.array(
            _features_for_action(
                action,
                node_features=node_features,
                degree_by_unit=degree_by_unit,
                node_count=node_count,
                step_index=0.0,
            ),
            dtype=float,
        )
        prediction = features @ coefficients
        action_type = str(action.get("action_type") or "unknown")
        residual_std = residual_std_by_action_type.get(action_type, global_reward_residual_std)
        scored.append(
            {
                "action_id": action.get("action_id"),
                "action_type": action.get("action_type"),
                "target_units": action.get("target_units"),
                "predicted_reward": round(float(prediction[0]), 9),
                "reward_uncertainty": round(float(residual_std), 9),
                "conservative_score": round(
                    float(prediction[0]) - uncertainty_penalty * float(residual_std),
                    9,
                ),
                "predicted_dynamics": {
                    name: round(float(value), 9)
                    for name, value in zip(TARGET_NAMES[1:], prediction[1:])
                },
            }
        )
    scored.sort(key=lambda row: (row["conservative_score"], row["predicted_reward"]), reverse=True)
    return scored


def _actual_replay_policy_evaluation(
    *,
    selected_action: dict[str, Any],
    static_action: dict[str, Any],
    transitions: list[dict[str, Any]],
) -> dict[str, Any]:
    selected_rewards = _replay_rewards_for_action(transitions, str(selected_action.get("action_id") or ""))
    static_rewards = _replay_rewards_for_action(transitions, str(static_action.get("action_id") or ""))
    comparable = bool(selected_rewards and static_rewards)
    selected_mean = _mean(selected_rewards)
    static_mean = _mean(static_rewards)
    return {
        "comparable": comparable,
        "selected_action_id": selected_action.get("action_id"),
        "static_action_id": static_action.get("action_id"),
        "selected_action_mean_reward": round(selected_mean, 9),
        "static_action_mean_reward": round(static_mean, 9),
        "replay_reward_advantage": round(selected_mean - static_mean, 9) if comparable else 0.0,
        "selected_action_replay_count": len(selected_rewards),
        "static_action_replay_count": len(static_rewards),
    }


def _replay_rewards_for_action(transitions: list[dict[str, Any]], action_id: str) -> list[float]:
    rewards = []
    for transition in transitions:
        action = transition.get("action") or {}
        if str(action.get("action_id") or "") == action_id:
            rewards.append(_float(transition.get("reward")))
    return rewards


def _normalise_static_action(action: dict[str, Any]) -> dict[str, Any]:
    normalised = dict(action)
    action_id = str(normalised.get("action_id") or "")
    if action_id.startswith("static-"):
        normalised["action_id"] = action_id.removeprefix("static-")
    return normalised


def _coefficient_table(coefficients: np.ndarray) -> dict[str, dict[str, float]]:
    table: dict[str, dict[str, float]] = {}
    for target_index, target_name in enumerate(TARGET_NAMES):
        table[target_name] = {
            feature_name: round(float(coefficients[feature_index, target_index]), 9)
            for feature_index, feature_name in enumerate(FEATURE_NAMES)
        }
    return table


def _first_target_unit(action: dict[str, Any]) -> str:
    targets = action.get("target_units")
    if isinstance(targets, list) and targets:
        return str(targets[0])
    if action.get("target_unit") is not None:
        return str(action.get("target_unit"))
    return ""


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
