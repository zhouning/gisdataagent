"""Offline value-model scaffold over UWM Graph-MDP replay datasets."""

from __future__ import annotations

from typing import Any

import numpy as np


OFFLINE_GRAPH_VALUE_MODEL_REPORT_SCHEMA = "uwm.offline_graph_value_model_report.v1"
DEFAULT_OFFLINE_VALUE_MODEL_BACKEND = "ridge_graph_replay_value_v0"

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
    "step_index_norm",
]


def train_offline_graph_value_model(
    search_report: dict[str, Any],
    *,
    model_id: str,
    created_at: str,
    holdout_stride: int = 5,
    ridge: float = 0.001,
) -> dict[str, Any]:
    """Fit a small value model on Graph-MDP replay and report holdout metrics."""

    if holdout_stride < 2:
        raise ValueError("holdout_stride must be at least 2")
    graph_state = search_report.get("graph_mdp_state") or {}
    transitions = list((search_report.get("trajectory_dataset") or {}).get("transitions") or [])
    if len(transitions) < 3:
        raise ValueError("offline value model requires at least three replay transitions")

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
    targets = np.array([row["target_reward"] for row in rows], dtype=float)
    holdout_indices = _holdout_indices(len(rows), holdout_stride)
    train_indices = [index for index in range(len(rows)) if index not in set(holdout_indices)]

    x_train = feature_matrix[train_indices]
    y_train = targets[train_indices]
    x_holdout = feature_matrix[holdout_indices]
    y_holdout = targets[holdout_indices]

    coefficients = _fit_ridge(x_train, y_train, ridge)
    holdout_predictions = x_holdout @ coefficients
    train_mean = float(np.mean(y_train))
    baseline_predictions = np.full_like(y_holdout, train_mean)
    holdout_mae = _mae(y_holdout, holdout_predictions)
    baseline_mae = _mae(y_holdout, baseline_predictions)
    holdout_win_count = int(np.sum(np.abs(y_holdout - holdout_predictions) < np.abs(y_holdout - baseline_predictions)))

    candidate_value_ranking = _candidate_value_ranking(
        graph_state,
        coefficients,
        node_features=node_features,
        degree_by_unit=degree_by_unit,
        node_count=node_count,
    )
    supported_claim = (
        "offline_replay_value_model_beats_train_mean_baseline"
        if holdout_mae < baseline_mae
        else "no_offline_value_model_baseline_advantage"
    )
    return {
        "schema": OFFLINE_GRAPH_VALUE_MODEL_REPORT_SCHEMA,
        "model_id": model_id,
        "created_at": created_at,
        "backend": DEFAULT_OFFLINE_VALUE_MODEL_BACKEND,
        "source_report_schema": search_report.get("schema"),
        "source_replay_transition_count": len(transitions),
        "feature_names": FEATURE_NAMES,
        "coefficients": {name: round(float(value), 9) for name, value in zip(FEATURE_NAMES, coefficients)},
        "training_summary": {
            "train_count": len(train_indices),
            "holdout_count": len(holdout_indices),
            "holdout_stride": holdout_stride,
            "ridge": ridge,
            "target": "transition.reward",
        },
        "holdout_metrics": {
            "mae": round(holdout_mae, 9),
            "win_count_vs_train_mean": holdout_win_count,
            "case_count": len(holdout_indices),
        },
        "baseline_metrics": {
            "baseline": "train_mean_reward",
            "train_mean_reward": round(train_mean, 9),
            "train_mean_mae": round(baseline_mae, 9),
        },
        "candidate_value_ranking": candidate_value_ranking,
        "supported_claim": supported_claim,
        "empirical_superiority_claim": False,
        "claim_boundary": {
            "max_claim_level": "bounded_support" if supported_claim == "offline_replay_value_model_beats_train_mean_baseline" else "not_for_claim",
            "reason": "offline value model is trained on simulator replay and is not an observed policy outcome model",
        },
        "remaining_gates": [
            "observed_policy_outcome_holdout_required",
            "learned_dynamics_model_required",
            "offline_policy_evaluation_required",
            "causal_policy_effect_validation_required",
        ],
    }


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


def _training_row(
    transition: dict[str, Any],
    *,
    node_features: dict[str, dict[str, float]],
    degree_by_unit: dict[str, int],
    node_count: int,
) -> dict[str, Any]:
    action = transition.get("action") or {}
    return {
        "features": _features_for_action(
            action,
            node_features=node_features,
            degree_by_unit=degree_by_unit,
            node_count=node_count,
            step_index=_float((transition.get("transition") or {}).get("step_index")),
        ),
        "target_reward": _float(transition.get("reward")),
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
        step_index / 10.0,
    ]


def _first_target_unit(action: dict[str, Any]) -> str:
    targets = action.get("target_units")
    if isinstance(targets, list) and targets:
        return str(targets[0])
    if action.get("target_unit") is not None:
        return str(action.get("target_unit"))
    return ""


def _holdout_indices(row_count: int, holdout_stride: int) -> list[int]:
    indices = [index for index in range(row_count) if (index + 1) % holdout_stride == 0]
    if not indices:
        return [row_count - 1]
    if len(indices) == row_count:
        return [row_count - 1]
    return indices


def _fit_ridge(x_train: np.ndarray, y_train: np.ndarray, ridge: float) -> np.ndarray:
    penalty = np.eye(x_train.shape[1]) * ridge
    penalty[0, 0] = 0.0
    xtx = x_train.T @ x_train + penalty
    xty = x_train.T @ y_train
    try:
        return np.linalg.solve(xtx, xty)
    except np.linalg.LinAlgError:
        return np.linalg.pinv(xtx) @ xty


def _candidate_value_ranking(
    graph_state: dict[str, Any],
    coefficients: np.ndarray,
    *,
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
        scored.append(
            {
                "action_id": action.get("action_id"),
                "action_type": action.get("action_type"),
                "target_units": action.get("target_units"),
                "predicted_value": round(float(features @ coefficients), 9),
            }
        )
    scored.sort(key=lambda row: row["predicted_value"], reverse=True)
    return scored


def _mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    if actual.size == 0:
        return 0.0
    return float(np.mean(np.abs(actual - predicted)))


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
