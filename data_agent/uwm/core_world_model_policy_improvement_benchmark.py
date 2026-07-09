"""Core UWM world-model policy improvement benchmark over full-admin replay."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .offline_world_model_policy import (
    FEATURE_NAMES,
    TARGET_NAMES,
    _degree_by_unit,
    _fit_ridge_multi_output,
    _holdout_indices,
    _mae_by_target,
    _node_features_by_unit,
    _training_row,
)


UWM_CORE_WORLD_MODEL_POLICY_IMPROVEMENT_BENCHMARK_SCHEMA = (
    "uwm.core_world_model_policy_improvement_benchmark.v1"
)

_SUPPORTED_CLAIM = (
    "core_world_model_policy_improvement_beats_static_and_action_ablation_baselines"
)
_NO_CLAIM = "no_core_world_model_policy_improvement_claim_supported"

_REQUIRED_FULL_ADMIN_COUNTS = {
    "graph_node_count": 1017,
    "graph_edge_count": 7932,
    "available_action_count": 1137,
    "transition_count": 6817,
    "transition_row_count": 6817,
}

_ACTION_SIGNAL_FEATURES = {
    "intensity",
    "mask_heat_risk",
    "mask_air_pollution",
    "mask_service_gap",
}

_REQUIRED_POLICY_BASELINES = [
    "static_single_step_baseline",
    "one_step_world_model_greedy",
    "no_action_signal_world_model_policy",
    "shuffled_action_signal_world_model_policy",
]
_DIAGNOSTIC_POLICY_BASELINES = ["multi_step_beam_search"]


@dataclass(frozen=True)
class DynamicsVariant:
    variant_id: str
    coefficients: np.ndarray
    train_predictions: np.ndarray
    holdout_predictions: np.ndarray
    train_residuals: np.ndarray
    holdout_mae_by_target: dict[str, float]
    reward_residual_std_by_action_type: dict[str, float]
    global_reward_residual_std: float


def build_uwm_core_world_model_policy_improvement_benchmark(
    *,
    full_admin_graph_planner_replay: dict[str, Any],
    benchmark_id: str,
    created_at: str,
    source_artifact_path: str | None = None,
    horizon: int = 2,
    gamma: float = 0.9,
    beam_width: int = 8,
    holdout_stride: int = 7,
    ridge: float = 0.001,
    uncertainty_penalty: float = 0.5,
    shuffle_offset: int = 137,
) -> dict[str, Any]:
    """Train replay dynamics and evaluate finite-horizon policy improvement."""

    if not isinstance(full_admin_graph_planner_replay, dict):
        raise TypeError("full_admin_graph_planner_replay must be a dictionary")
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    if beam_width <= 0:
        raise ValueError("beam_width must be positive")
    if holdout_stride < 2:
        raise ValueError("holdout_stride must be at least 2")

    graph_state = full_admin_graph_planner_replay.get("graph_mdp_state") or {}
    transitions = list(
        (full_admin_graph_planner_replay.get("trajectory_dataset") or {}).get(
            "transitions"
        )
        or []
    )
    if len(transitions) < 3:
        raise ValueError(
            "core world-model policy improvement requires at least three transitions"
        )

    rows = _training_rows(graph_state, transitions)
    feature_matrix, targets = _matrices_from_rows(rows)
    holdout_indices = _holdout_indices(len(rows), holdout_stride)
    holdout_set = set(holdout_indices)
    train_indices = [index for index in range(len(rows)) if index not in holdout_set]
    if not train_indices:
        train_indices = [index for index in range(len(rows)) if index != holdout_indices[-1]]
        holdout_indices = [holdout_indices[-1]]

    action_columns = _action_signal_columns()
    train_rows = [rows[index] for index in train_indices]
    x_train = feature_matrix[train_indices]
    y_train = targets[train_indices]
    x_holdout = feature_matrix[holdout_indices]
    y_holdout = targets[holdout_indices]

    full_dynamics = _fit_dynamics_variant(
        "full_action_state_graph",
        x_train,
        y_train,
        x_holdout,
        y_holdout,
        ridge,
        train_rows,
    )
    no_action_dynamics = _fit_dynamics_variant(
        "no_action_signal",
        _zero_columns(x_train, action_columns),
        y_train,
        _zero_columns(x_holdout, action_columns),
        y_holdout,
        ridge,
        train_rows,
    )
    shuffled_matrix = _shuffle_columns(feature_matrix, action_columns, shuffle_offset)
    shuffled_dynamics = _fit_dynamics_variant(
        "shuffled_action_signal",
        shuffled_matrix[train_indices],
        y_train,
        shuffled_matrix[holdout_indices],
        y_holdout,
        ridge,
        train_rows,
    )
    train_mean = np.mean(y_train, axis=0)
    train_mean_predictions = np.tile(train_mean, (len(holdout_indices), 1))
    dynamics_holdout_metrics = {
        "full_action_state_graph": _dynamics_metric_row(full_dynamics),
        "train_mean_static": {
            "model_class": "train_target_mean_static_baseline",
            "mae_by_target": _round_mae(_mae_by_target(y_holdout, train_mean_predictions)),
        },
        "no_action_signal": _dynamics_metric_row(no_action_dynamics),
        "shuffled_action_signal": _dynamics_metric_row(shuffled_dynamics),
    }

    node_features = _node_features_by_unit(graph_state)
    degree_by_unit = _degree_by_unit(graph_state)
    node_count = max(1, len(node_features))
    actions = [dict(action) for action in graph_state.get("available_actions") or []]
    if not actions:
        raise ValueError("core policy improvement requires candidate actions")
    static_action = _static_action(full_admin_graph_planner_replay, actions)

    raw_policy_metrics = {
        "world_model_policy_improvement": _policy_improvement_sequence(
            actions,
            node_features,
            degree_by_unit,
            node_count,
            full_dynamics,
            horizon,
            gamma,
            beam_width,
            uncertainty_penalty,
        ),
        "static_single_step_baseline": _static_single_step_sequence(
            static_action,
            node_features,
            degree_by_unit,
            node_count,
            full_dynamics,
            gamma,
            uncertainty_penalty,
        ),
        "one_step_world_model_greedy": _one_step_greedy_sequence(
            actions,
            node_features,
            degree_by_unit,
            node_count,
            full_dynamics,
            gamma,
            uncertainty_penalty,
        ),
        "multi_step_beam_search": _beam_search_sequence(
            actions,
            node_features,
            degree_by_unit,
            node_count,
            full_dynamics,
            horizon,
            gamma,
            beam_width,
            uncertainty_penalty,
        ),
        "no_action_signal_world_model_policy": _policy_improvement_sequence(
            actions,
            node_features,
            degree_by_unit,
            node_count,
            no_action_dynamics,
            horizon,
            gamma,
            beam_width,
            uncertainty_penalty,
        ),
        "shuffled_action_signal_world_model_policy": _policy_improvement_sequence(
            actions,
            node_features,
            degree_by_unit,
            node_count,
            shuffled_dynamics,
            horizon,
            gamma,
            beam_width,
            uncertainty_penalty,
        ),
    }
    policy_variant_metrics = _attach_policy_comparisons(raw_policy_metrics)

    scope_guard = _full_admin_scope_guard(
        full_admin_graph_planner_replay,
        transition_row_count=len(transitions),
    )
    policy_gate = _policy_improvement_gate(
        policy_variant_metrics,
        dynamics_holdout_metrics,
        scope_guard,
        horizon,
    )
    ready = scope_guard["passed"] is True and policy_gate["passed"] is True
    return {
        "schema": UWM_CORE_WORLD_MODEL_POLICY_IMPROVEMENT_BENCHMARK_SCHEMA,
        "benchmark_id": benchmark_id,
        "created_at": created_at,
        "experiment_scope": "full_admin_graph",
        "source_report_schema": full_admin_graph_planner_replay.get("schema"),
        "feature_names": list(FEATURE_NAMES),
        "target_names": list(TARGET_NAMES),
        "full_admin_scope_guard": scope_guard,
        "training_summary": {
            "row_count": len(rows),
            "train_count": len(train_indices),
            "holdout_count": len(holdout_indices),
            "holdout_stride": holdout_stride,
            "ridge": ridge,
            "first_holdout_index": int(holdout_indices[0]),
            "last_holdout_index": int(holdout_indices[-1]),
        },
        "dynamics_holdout_metrics": dynamics_holdout_metrics,
        "policy_improvement_config": {
            "algorithm": "finite_horizon_model_based_value_backup",
            "horizon": horizon,
            "gamma": gamma,
            "beam_width": beam_width,
            "uncertainty_penalty": uncertainty_penalty,
            "shuffle_offset": shuffle_offset,
            "candidate_action_count": len(actions),
            "state_update": "apply_predicted_dynamics_to_target_unit_latent_features",
        },
        "policy_variant_metrics": policy_variant_metrics,
        "policy_improvement_gate": policy_gate,
        "supported_claim": _SUPPORTED_CLAIM if ready else _NO_CLAIM,
        "claim_boundary": {
            "max_claim_level": "bounded_support" if ready else "not_for_claim",
            "reason": (
                "same-scene full-admin learned world-model finite-horizon policy "
                "improvement; observed policy outcome gates remain open"
            ),
        },
        "remaining_gates": _remaining_gates(scope_guard, policy_gate),
        "audit_trace": {
            "source_artifact_path": source_artifact_path,
            "model_class": "linear_ridge_action_conditioned_graph_dynamics",
            "action_signal_feature_names": [
                FEATURE_NAMES[index] for index in action_columns
            ],
            "shuffled_action_signal_roll_offset": shuffle_offset,
            "policy_improvement_uses_observed_policy_outcomes": False,
        },
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def validate_uwm_core_world_model_policy_improvement_benchmark(
    benchmark: dict[str, Any],
) -> dict[str, Any]:
    """Validate the policy-improvement benchmark contract."""

    errors: list[str] = []
    if not isinstance(benchmark, dict):
        return {"valid": False, "errors": ["benchmark must be a dictionary"]}
    if benchmark.get("schema") != UWM_CORE_WORLD_MODEL_POLICY_IMPROVEMENT_BENCHMARK_SCHEMA:
        errors.append(
            "schema must be uwm.core_world_model_policy_improvement_benchmark.v1"
        )
    if benchmark.get("experiment_scope") != "full_admin_graph":
        errors.append("experiment_scope must be full_admin_graph")
    if benchmark.get("observed_policy_outcome_superiority_claim") is not False:
        errors.append("observed_policy_outcome_superiority_claim must be false")
    if benchmark.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim must be false")

    supported = benchmark.get("supported_claim")
    if supported == _SUPPORTED_CLAIM:
        if (benchmark.get("full_admin_scope_guard") or {}).get("passed") is not True:
            errors.append("supported claim requires full_admin_scope_guard.passed")
        if (benchmark.get("policy_improvement_gate") or {}).get("passed") is not True:
            errors.append("supported claim requires policy_improvement_gate.passed")
        if (benchmark.get("claim_boundary") or {}).get("max_claim_level") != "bounded_support":
            errors.append("supported claim requires bounded_support claim boundary")
        _validate_required_policy_advantages(benchmark, errors)
    elif supported == _NO_CLAIM:
        if (benchmark.get("claim_boundary") or {}).get("max_claim_level") != "not_for_claim":
            errors.append("no-claim benchmark must use not_for_claim boundary")
    else:
        errors.append("supported_claim has unknown value")
    return {"valid": not errors, "errors": errors}


def _training_rows(
    graph_state: dict[str, Any],
    transitions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    node_features = _node_features_by_unit(graph_state)
    degree_by_unit = _degree_by_unit(graph_state)
    node_count = max(1, len(node_features))
    return [
        _training_row(
            transition,
            node_features=node_features,
            degree_by_unit=degree_by_unit,
            node_count=node_count,
        )
        for transition in transitions
    ]


def _training_matrices(
    graph_state: dict[str, Any],
    transitions: list[dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray]:
    return _matrices_from_rows(_training_rows(graph_state, transitions))


def _matrices_from_rows(rows: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    return (
        np.array([row["features"] for row in rows], dtype=float),
        np.array([row["targets"] for row in rows], dtype=float),
    )


def _fit_dynamics_variant(
    variant_id: str,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_holdout: np.ndarray,
    y_holdout: np.ndarray,
    ridge: float,
    train_rows: list[dict[str, Any]],
) -> DynamicsVariant:
    coefficients = _fit_ridge_multi_output(x_train, y_train, ridge)
    train_predictions = x_train @ coefficients
    holdout_predictions = x_holdout @ coefficients
    train_residuals = y_train[:, 0] - train_predictions[:, 0]
    return DynamicsVariant(
        variant_id=variant_id,
        coefficients=coefficients,
        train_predictions=train_predictions,
        holdout_predictions=holdout_predictions,
        train_residuals=train_residuals,
        holdout_mae_by_target=_mae_by_target(y_holdout, holdout_predictions),
        reward_residual_std_by_action_type=_reward_residual_std_by_action_type(
            train_rows,
            train_residuals,
        ),
        global_reward_residual_std=float(np.std(train_residuals))
        if train_residuals.size
        else 0.0,
    )


def _policy_improvement_sequence(
    actions: list[dict[str, Any]],
    initial_state_features: dict[str, dict[str, float]],
    degree_by_unit: dict[str, int],
    node_count: int,
    dynamics: DynamicsVariant,
    horizon: int,
    gamma: float,
    beam_width: int,
    uncertainty_penalty: float,
) -> dict[str, Any]:
    return _tree_sequence(
        "world_model_policy_improvement",
        actions,
        initial_state_features,
        degree_by_unit,
        node_count,
        dynamics,
        horizon=horizon,
        gamma=gamma,
        beam_width=beam_width,
        uncertainty_penalty=uncertainty_penalty,
        ranking="discounted_conservative_return",
    )


def _one_step_greedy_sequence(
    actions: list[dict[str, Any]],
    initial_state_features: dict[str, dict[str, float]],
    degree_by_unit: dict[str, int],
    node_count: int,
    dynamics: DynamicsVariant,
    gamma: float,
    uncertainty_penalty: float,
) -> dict[str, Any]:
    return _tree_sequence(
        "one_step_world_model_greedy",
        actions,
        initial_state_features,
        degree_by_unit,
        node_count,
        dynamics,
        horizon=1,
        gamma=gamma,
        beam_width=1,
        uncertainty_penalty=uncertainty_penalty,
        ranking="immediate_conservative_reward",
    )


def _static_single_step_sequence(
    static_action: dict[str, Any],
    initial_state_features: dict[str, dict[str, float]],
    degree_by_unit: dict[str, int],
    node_count: int,
    dynamics: DynamicsVariant,
    gamma: float,
    uncertainty_penalty: float,
) -> dict[str, Any]:
    return _evaluate_fixed_sequence(
        [static_action],
        initial_state_features,
        degree_by_unit,
        node_count,
        dynamics,
        gamma=gamma,
        uncertainty_penalty=uncertainty_penalty,
        policy_variant="static_single_step_baseline",
    )


def _beam_search_sequence(
    actions: list[dict[str, Any]],
    initial_state_features: dict[str, dict[str, float]],
    degree_by_unit: dict[str, int],
    node_count: int,
    dynamics: DynamicsVariant,
    horizon: int,
    gamma: float,
    beam_width: int,
    uncertainty_penalty: float,
) -> dict[str, Any]:
    return _tree_sequence(
        "multi_step_beam_search",
        actions,
        initial_state_features,
        degree_by_unit,
        node_count,
        dynamics,
        horizon=horizon,
        gamma=gamma,
        beam_width=max(1, min(beam_width, 5)),
        uncertainty_penalty=uncertainty_penalty,
        ranking="discounted_conservative_return",
    )


def _evaluate_fixed_sequence(
    actions: list[dict[str, Any]],
    initial_state_features: dict[str, dict[str, float]],
    degree_by_unit: dict[str, int],
    node_count: int,
    dynamics: DynamicsVariant,
    gamma: float,
    uncertainty_penalty: float,
    *,
    policy_variant: str,
) -> dict[str, Any]:
    state_features = _clone_node_features(initial_state_features)
    action_sequence = []
    imagined_steps = []
    predicted_return = 0.0
    conservative_return = 0.0
    for step_index, action in enumerate(action for action in actions if action):
        step, state_features = _imagine_action_step(
            action,
            state_features,
            degree_by_unit,
            node_count,
            dynamics,
            step_index,
            uncertainty_penalty,
        )
        action_sequence.append(_public_action(action))
        imagined_steps.append(step)
        discount = gamma ** step_index
        predicted_return += discount * step["predicted_reward"]
        conservative_return += discount * step["conservative_reward"]
    return _policy_metric_row(
        policy_variant,
        dynamics.variant_id,
        action_sequence,
        imagined_steps,
        predicted_return,
        conservative_return,
        gamma,
    )


def _tree_sequence(
    policy_variant: str,
    actions: list[dict[str, Any]],
    initial_state_features: dict[str, dict[str, float]],
    degree_by_unit: dict[str, int],
    node_count: int,
    dynamics: DynamicsVariant,
    *,
    horizon: int,
    gamma: float,
    beam_width: int,
    uncertainty_penalty: float,
    ranking: str,
) -> dict[str, Any]:
    beams = [
        {
            "action_sequence": [],
            "imagined_steps": [],
            "state_features": _clone_node_features(initial_state_features),
            "predicted_return": 0.0,
            "conservative_return": 0.0,
            "ranking_score": 0.0,
        }
    ]
    for step_index in range(horizon):
        expanded = []
        for beam in beams:
            used_action_ids = {
                str(action.get("action_id") or "")
                for action in beam["action_sequence"]
            }
            for action in actions:
                if str(action.get("action_id") or "") in used_action_ids:
                    continue
                step, next_state = _imagine_action_step(
                    action,
                    beam["state_features"],
                    degree_by_unit,
                    node_count,
                    dynamics,
                    step_index,
                    uncertainty_penalty,
                )
                discount = gamma ** step_index
                predicted_return = float(beam["predicted_return"]) + (
                    discount * step["predicted_reward"]
                )
                conservative_return = float(beam["conservative_return"]) + (
                    discount * step["conservative_reward"]
                )
                if ranking == "immediate_conservative_reward":
                    ranking_score = step["conservative_reward"]
                elif ranking == "undiscounted_conservative_return":
                    ranking_score = float(beam["ranking_score"]) + step["conservative_reward"]
                else:
                    ranking_score = conservative_return
                expanded.append(
                    {
                        "action_sequence": [*beam["action_sequence"], dict(action)],
                        "imagined_steps": [*beam["imagined_steps"], step],
                        "state_features": next_state,
                        "predicted_return": predicted_return,
                        "conservative_return": conservative_return,
                        "ranking_score": ranking_score,
                    }
                )
        if not expanded:
            break
        expanded.sort(
            key=lambda row: (
                row["ranking_score"],
                row["conservative_return"],
                row["predicted_return"],
            ),
            reverse=True,
        )
        beams = expanded[:beam_width]
    best = max(
        beams,
        key=lambda row: (
            row["conservative_return"],
            row["predicted_return"],
            row["ranking_score"],
        ),
    )
    return _policy_metric_row(
        policy_variant,
        dynamics.variant_id,
        [_public_action(action) for action in best["action_sequence"]],
        best["imagined_steps"],
        float(best["predicted_return"]),
        float(best["conservative_return"]),
        gamma,
    )


def _imagine_action_step(
    action: dict[str, Any],
    state_features: dict[str, dict[str, float]],
    degree_by_unit: dict[str, int],
    node_count: int,
    dynamics: DynamicsVariant,
    step_index: int,
    uncertainty_penalty: float,
) -> tuple[dict[str, Any], dict[str, dict[str, float]]]:
    features = np.array(
        _features_for_action(
            action,
            node_features=state_features,
            degree_by_unit=degree_by_unit,
            node_count=node_count,
            step_index=float(step_index),
        ),
        dtype=float,
    )
    prediction = features @ dynamics.coefficients
    action_type = str(action.get("action_type") or "unknown")
    residual_std = dynamics.reward_residual_std_by_action_type.get(
        action_type,
        dynamics.global_reward_residual_std,
    )
    conservative_reward = float(prediction[0]) - uncertainty_penalty * float(residual_std)
    predicted_dynamics = {
        name: round(float(value), 9)
        for name, value in zip(TARGET_NAMES[1:], prediction[1:])
    }
    next_state = _apply_predicted_dynamics_to_state(
        state_features,
        action,
        predicted_dynamics,
    )
    target_units = _target_units(action)
    return (
        {
            "step_index": int(step_index),
            "action": _public_action(action),
            "predicted_reward": round(float(prediction[0]), 9),
            "reward_uncertainty": round(float(residual_std), 9),
            "conservative_reward": round(conservative_reward, 9),
            "predicted_dynamics": predicted_dynamics,
            "post_state_features": _state_features_for_units(next_state, target_units),
        },
        next_state,
    )


def _policy_improvement_gate(
    policy_variant_metrics: dict[str, Any],
    dynamics_holdout_metrics: dict[str, Any],
    scope_guard: dict[str, Any],
    horizon: int,
) -> dict[str, Any]:
    full_reward_mae = dynamics_holdout_metrics["full_action_state_graph"][
        "mae_by_target"
    ]["reward"]
    train_mean_reward_mae = dynamics_holdout_metrics["train_mean_static"][
        "mae_by_target"
    ]["reward"]
    no_action_reward_mae = dynamics_holdout_metrics["no_action_signal"][
        "mae_by_target"
    ]["reward"]
    shuffled_reward_mae = dynamics_holdout_metrics["shuffled_action_signal"][
        "mae_by_target"
    ]["reward"]
    improved = policy_variant_metrics["world_model_policy_improvement"]
    improved_return = improved["imagined_cumulative_conservative_return"]
    baseline_rows = []
    for baseline_id in _REQUIRED_POLICY_BASELINES:
        baseline_return = policy_variant_metrics[baseline_id][
            "imagined_cumulative_conservative_return"
        ]
        baseline_rows.append(
            {
                "policy_baseline": baseline_id,
                "baseline_conservative_return": baseline_return,
                "world_model_policy_improvement_conservative_return": improved_return,
                "world_model_policy_improvement_advantage": round(
                    improved_return - baseline_return,
                    9,
                ),
                "passed": improved_return > baseline_return,
            }
        )
    dynamics_gate = {
        "full_reward_mae": full_reward_mae,
        "train_mean_reward_mae": train_mean_reward_mae,
        "no_action_signal_reward_mae": no_action_reward_mae,
        "shuffled_action_signal_reward_mae": shuffled_reward_mae,
        "beats_train_mean_static": full_reward_mae < train_mean_reward_mae,
        "beats_no_action_signal": full_reward_mae < no_action_reward_mae,
        "beats_shuffled_action_signal": full_reward_mae < shuffled_reward_mae,
    }
    passed = (
        scope_guard.get("passed") is True
        and dynamics_gate["beats_train_mean_static"]
        and dynamics_gate["beats_no_action_signal"]
        and dynamics_gate["beats_shuffled_action_signal"]
        and improved["action_count"] == horizon
        and all(row["passed"] for row in baseline_rows)
    )
    return {
        "passed": passed,
        "required_policy_baselines": list(_REQUIRED_POLICY_BASELINES),
        "diagnostic_policy_baselines": list(_DIAGNOSTIC_POLICY_BASELINES),
        "dynamics_reward_gate": dynamics_gate,
        "baseline_rows": baseline_rows,
        "required_sequence_action_count": horizon,
        "observed_policy_outcome_superiority_claim": False,
    }


def _dynamics_metric_row(dynamics: DynamicsVariant) -> dict[str, Any]:
    return {
        "model_class": "linear_ridge_multi_output_dynamics",
        "dynamics_variant": dynamics.variant_id,
        "mae_by_target": _round_mae(dynamics.holdout_mae_by_target),
        "global_reward_residual_std": round(dynamics.global_reward_residual_std, 9),
        "reward_residual_std_by_action_type": {
            key: round(float(value), 9)
            for key, value in sorted(
                dynamics.reward_residual_std_by_action_type.items()
            )
        },
    }


def _policy_metric_row(
    policy_variant: str,
    dynamics_variant: str,
    action_sequence: list[dict[str, Any]],
    imagined_steps: list[dict[str, Any]],
    predicted_return: float,
    conservative_return: float,
    gamma: float,
) -> dict[str, Any]:
    return {
        "policy_variant": policy_variant,
        "dynamics_variant": dynamics_variant,
        "action_count": len(action_sequence),
        "action_sequence": action_sequence,
        "imagined_steps": imagined_steps,
        "imagined_cumulative_predicted_return": round(float(predicted_return), 9),
        "imagined_cumulative_conservative_return": round(
            float(conservative_return),
            9,
        ),
        "return_convention": {
            "discount": "gamma",
            "gamma": gamma,
        },
    }


def _attach_policy_comparisons(
    policy_variant_metrics: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    improved_return = policy_variant_metrics["world_model_policy_improvement"][
        "imagined_cumulative_conservative_return"
    ]
    rows = {}
    for policy_id, row in policy_variant_metrics.items():
        copied = dict(row)
        copied["relative_to_world_model_policy_improvement"] = {
            "world_model_policy_improvement_advantage": round(
                improved_return - row["imagined_cumulative_conservative_return"],
                9,
            )
        }
        rows[policy_id] = copied
    return rows


def _static_action(
    report: dict[str, Any],
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    static = dict(
        ((report.get("static_single_step_baseline") or {}).get("action_sequence") or [{}])[0]
    )
    action_id = str(static.get("action_id") or "")
    if action_id.startswith("static-"):
        static["action_id"] = action_id.removeprefix("static-")
    action_by_id = {
        str(action.get("action_id") or ""): action
        for action in actions
    }
    return dict(action_by_id.get(str(static.get("action_id") or ""), static or actions[0]))


def _full_admin_scope_guard(
    replay: dict[str, Any],
    *,
    transition_row_count: int,
) -> dict[str, Any]:
    graph_state = replay.get("graph_mdp_state") or {}
    graph_statistics = graph_state.get("graph_statistics") or {}
    trajectory = replay.get("trajectory_dataset") or {}
    counts = {
        "graph_node_count": _int_or_count(
            graph_statistics.get("node_count"),
            graph_state.get("nodes"),
        ),
        "graph_edge_count": _int_or_count(
            graph_statistics.get("edge_count"),
            graph_state.get("edges"),
        ),
        "available_action_count": _int_or_count(
            graph_statistics.get("available_action_count"),
            graph_state.get("available_actions"),
        ),
        "transition_count": _int_or_count(
            trajectory.get("transition_count"),
            trajectory.get("transitions"),
        ),
        "transition_row_count": int(transition_row_count),
    }
    failures = [
        key
        for key, expected in _REQUIRED_FULL_ADMIN_COUNTS.items()
        if counts.get(key) != expected
    ]
    if replay.get("experiment_scope") != "full_admin_graph":
        failures.append("experiment_scope")
    return {
        "passed": not failures,
        "required_scope": "full_admin_graph",
        "required_counts": dict(_REQUIRED_FULL_ADMIN_COUNTS),
        "experiment_scope": replay.get("experiment_scope"),
        **counts,
        "failed_count_fields": failures,
    }


def _remaining_gates(
    scope_guard: dict[str, Any],
    policy_gate: dict[str, Any],
) -> list[str]:
    gates = [
        "observed_policy_outcome_holdout_required",
        "off_policy_evaluation_on_real_intervention_logs_required",
        "causal_policy_effect_validation_required",
        "external_cross_city_or_cross_time_policy_holdout_required",
    ]
    if scope_guard.get("passed") is not True:
        gates.insert(0, "full_admin_scope_guard_failed")
    if policy_gate.get("passed") is not True:
        gates.insert(0, "policy_improvement_gate_failed")
    return gates


def _validate_required_policy_advantages(
    benchmark: dict[str, Any],
    errors: list[str],
) -> None:
    metrics = benchmark.get("policy_variant_metrics") or {}
    improved = metrics.get("world_model_policy_improvement") or {}
    try:
        improved_return = float(improved["imagined_cumulative_conservative_return"])
    except (KeyError, TypeError, ValueError):
        errors.append("world_model_policy_improvement conservative return missing")
        return
    for baseline_id in _REQUIRED_POLICY_BASELINES:
        try:
            baseline_return = float(
                metrics[baseline_id]["imagined_cumulative_conservative_return"]
            )
            if not improved_return > baseline_return:
                errors.append(
                    f"world_model_policy_improvement does not beat {baseline_id}"
                )
        except (KeyError, TypeError, ValueError):
            errors.append(f"missing comparable policy metric for {baseline_id}")


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
    is_green = action_type in {
        "increase_green",
        "increase_green_infrastructure",
        "urban_greening",
    }
    is_traffic = action_type in {"traffic_emission_control", "low_emission_zone"}
    is_service = action_type in {
        "add_community_service",
        "service_accessibility_improvement",
    }
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
        features["heat_risk"] = _clamp01(
            features["heat_risk"] + predicted_dynamics["heat_risk_delta"]
        )
        features["air_pollution_exposure"] = _clamp01(
            features["air_pollution_exposure"]
            + predicted_dynamics["air_pollution_exposure_delta"]
        )
        features["service_accessibility"] = _clamp01(
            features["service_accessibility"]
            + predicted_dynamics["service_accessibility_delta"]
        )
        features["equity"] = _clamp01(features["equity"] + predicted_dynamics["equity_delta"])
        features["livability"] = _clamp01(
            features["livability"] + predicted_dynamics["livability_delta"]
        )
    return next_state


def _clone_node_features(
    node_features: dict[str, dict[str, float]]
) -> dict[str, dict[str, float]]:
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


def _public_action(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": action.get("action_id"),
        "action_type": action.get("action_type"),
        "target_units": _target_units(action),
        "intensity": _float(action.get("intensity"), default=1.0),
        "mask_reason": action.get("mask_reason"),
    }


def _first_target_unit(action: dict[str, Any]) -> str:
    units = _target_units(action)
    return units[0] if units else ""


def _target_units(action: dict[str, Any]) -> list[str]:
    targets = action.get("target_units")
    if isinstance(targets, list) and targets:
        return [str(unit_id) for unit_id in targets]
    if action.get("target_unit") is not None:
        return [str(action.get("target_unit"))]
    return []


def _reward_residual_std_by_action_type(
    train_rows: list[dict[str, Any]],
    residuals: np.ndarray,
) -> dict[str, float]:
    grouped: dict[str, list[float]] = {}
    for row, residual in zip(train_rows, residuals):
        key = str(row.get("action_type") or "unknown")
        grouped.setdefault(key, []).append(float(residual))
    return {
        key: float(np.std(values)) if len(values) > 1 else 0.0
        for key, values in grouped.items()
    }


def _action_signal_columns() -> list[int]:
    return [
        index
        for index, name in enumerate(FEATURE_NAMES)
        if name.startswith("action_") or name in _ACTION_SIGNAL_FEATURES
    ]


def _zero_columns(matrix: np.ndarray, columns: list[int]) -> np.ndarray:
    zeroed = np.array(matrix, copy=True)
    if columns:
        zeroed[:, columns] = 0.0
    return zeroed


def _shuffle_columns(matrix: np.ndarray, columns: list[int], offset: int) -> np.ndarray:
    shuffled = np.array(matrix, copy=True)
    if columns and len(shuffled) > 1:
        shuffled[:, columns] = np.roll(shuffled[:, columns], shift=offset, axis=0)
    return shuffled


def _round_mae(values: dict[str, float]) -> dict[str, float]:
    return {name: round(float(values[name]), 9) for name in TARGET_NAMES}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _float(value: Any, default: float = 0.0) -> float:
    if value in {None, ""}:
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _int_or_count(value: Any, rows: Any) -> int:
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    if isinstance(rows, list):
        return len(rows)
    return 0
