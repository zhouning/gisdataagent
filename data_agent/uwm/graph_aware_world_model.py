"""Graph-aware action-conditioned world model for UWM spatial replay."""

from __future__ import annotations

from typing import Any

import numpy as np


GRAPH_AWARE_WORLD_MODEL_REPORT_SCHEMA = "uwm.graph_aware_world_model_report.v1"
DEFAULT_GRAPH_AWARE_WORLD_MODEL_BACKEND = "ridge_graph_aware_action_conditioned_dynamics_v0"

TARGET_NAMES = [
    "reward",
    "heat_risk_delta",
    "air_pollution_exposure_delta",
    "service_accessibility_delta",
    "equity_delta",
    "livability_delta",
]

TARGET_ONLY_FEATURE_NAMES = [
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
    "mask_heat_risk",
    "mask_air_pollution",
    "mask_service_gap",
    "step_index_norm",
]

GRAPH_AWARE_FEATURE_NAMES = [
    *TARGET_ONLY_FEATURE_NAMES,
    "target_degree_norm",
    "neighbor_count_norm",
    "neighbor_mean_heat_risk",
    "neighbor_mean_air_pollution_exposure",
    "neighbor_mean_service_gap",
    "neighbor_mean_equity",
    "neighbor_mean_livability_gap",
    "target_neighbor_heat_contrast",
    "target_neighbor_air_contrast",
    "target_neighbor_service_gap_contrast",
    "target_neighbor_livability_gap_contrast",
    "green_action_neighbor_heat_pressure",
    "traffic_action_neighbor_air_pressure",
    "service_action_neighbor_service_gap_pressure",
]


def train_graph_aware_world_model(
    search_report: dict[str, Any],
    *,
    model_id: str,
    created_at: str,
    holdout_stride: int = 5,
    ridge: float = 0.001,
) -> dict[str, Any]:
    """Fit graph-aware dynamics and compare against target-only dynamics."""

    if holdout_stride < 2:
        raise ValueError("holdout_stride must be at least 2")
    graph_state = search_report.get("graph_mdp_state") or {}
    transitions = list((search_report.get("trajectory_dataset") or {}).get("transitions") or [])
    if len(transitions) < 3:
        raise ValueError("graph-aware world model requires at least three replay transitions")

    node_features = _node_features_by_unit(graph_state)
    neighbors_by_unit = _neighbors_by_unit(graph_state)
    node_count = max(1, len(node_features))
    rows = [
        _training_row(
            transition,
            node_features=node_features,
            neighbors_by_unit=neighbors_by_unit,
            node_count=node_count,
        )
        for transition in transitions
    ]
    graph_x = np.array([row["graph_features"] for row in rows], dtype=float)
    target_x = np.array([row["target_only_features"] for row in rows], dtype=float)
    targets = np.array([row["targets"] for row in rows], dtype=float)

    holdout_indices = _holdout_indices(len(rows), holdout_stride)
    holdout_set = set(holdout_indices)
    train_indices = [index for index in range(len(rows)) if index not in holdout_set]
    if not train_indices:
        train_indices = [index for index in range(len(rows)) if index != holdout_indices[-1]]
        holdout_indices = [holdout_indices[-1]]

    y_train = targets[train_indices]
    y_holdout = targets[holdout_indices]
    graph_coefficients = _fit_ridge_multi_output(graph_x[train_indices], y_train, ridge)
    target_coefficients = _fit_ridge_multi_output(target_x[train_indices], y_train, ridge)
    graph_predictions = graph_x[holdout_indices] @ graph_coefficients
    target_predictions = target_x[holdout_indices] @ target_coefficients
    train_mean = np.mean(y_train, axis=0)
    train_mean_predictions = np.tile(train_mean, (len(holdout_indices), 1))

    graph_mae = _mae_by_target(y_holdout, graph_predictions)
    target_mae = _mae_by_target(y_holdout, target_predictions)
    train_mean_mae = _mae_by_target(y_holdout, train_mean_predictions)
    graph_reward_errors = np.abs(y_holdout[:, 0] - graph_predictions[:, 0])
    target_reward_errors = np.abs(y_holdout[:, 0] - target_predictions[:, 0])
    train_mean_reward_errors = np.abs(y_holdout[:, 0] - train_mean_predictions[:, 0])
    reward_win_count_vs_target = int(np.sum(graph_reward_errors < target_reward_errors))
    reward_win_count_vs_train_mean = int(np.sum(graph_reward_errors < train_mean_reward_errors))
    dynamics_mean_mae = _dynamics_mean_mae(graph_mae)
    target_dynamics_mean_mae = _dynamics_mean_mae(target_mae)
    reward_mae = graph_mae["reward"]
    supported = (
        reward_mae < target_mae["reward"]
        and reward_mae < train_mean_mae["reward"]
        and reward_win_count_vs_target > len(holdout_indices) / 2
        and dynamics_mean_mae < target_dynamics_mean_mae
    )
    return {
        "schema": GRAPH_AWARE_WORLD_MODEL_REPORT_SCHEMA,
        "model_id": model_id,
        "created_at": created_at,
        "backend": DEFAULT_GRAPH_AWARE_WORLD_MODEL_BACKEND,
        "source_report_schema": search_report.get("schema"),
        "source_graph_summary": {
            "node_count": _int((graph_state.get("graph_statistics") or {}).get("node_count"), len(node_features)),
            "edge_count": _int((graph_state.get("graph_statistics") or {}).get("edge_count"), _edge_count(graph_state)),
            "available_action_count": _int(
                (graph_state.get("graph_statistics") or {}).get("available_action_count"),
                len(graph_state.get("available_actions") or []),
            ),
        },
        "world_model": {
            "model_class": "linear_ridge_graph_aware_action_conditioned_dynamics",
            "feature_names": GRAPH_AWARE_FEATURE_NAMES,
            "target_names": TARGET_NAMES,
            "graph_message_features": [
                "target_degree_norm",
                "neighbor_count_norm",
                "neighbor_mean_heat_risk",
                "neighbor_mean_air_pollution_exposure",
                "neighbor_mean_service_gap",
                "neighbor_mean_equity",
                "neighbor_mean_livability_gap",
                "target_neighbor_*_contrast",
                "action_neighbor_pressure",
            ],
            "coefficients": _coefficient_table(graph_coefficients, GRAPH_AWARE_FEATURE_NAMES),
        },
        "target_only_baseline_model": {
            "model_class": "linear_ridge_target_only_action_conditioned_dynamics",
            "feature_names": TARGET_ONLY_FEATURE_NAMES,
            "target_names": TARGET_NAMES,
        },
        "training_summary": {
            "transition_count": len(transitions),
            "train_count": len(train_indices),
            "holdout_count": len(holdout_indices),
            "holdout_stride": holdout_stride,
            "ridge": ridge,
        },
        "holdout_metrics": {
            "reward_mae": round(reward_mae, 9),
            "reward_win_count_vs_target_only": reward_win_count_vs_target,
            "reward_win_rate_vs_target_only": round(
                reward_win_count_vs_target / len(holdout_indices),
                9,
            ),
            "reward_win_count_vs_train_mean": reward_win_count_vs_train_mean,
            "reward_win_rate_vs_train_mean": round(
                reward_win_count_vs_train_mean / len(holdout_indices),
                9,
            ),
            "dynamics_mae_by_target": {
                key: round(value, 9)
                for key, value in graph_mae.items()
                if key != "reward"
            },
            "dynamics_mean_mae": round(dynamics_mean_mae, 9),
        },
        "baseline_metrics": {
            "target_only_reward_mae": round(target_mae["reward"], 9),
            "target_only_dynamics_mae_by_target": {
                key: round(value, 9)
                for key, value in target_mae.items()
                if key != "reward"
            },
            "target_only_dynamics_mean_mae": round(target_dynamics_mean_mae, 9),
            "train_mean_reward_mae": round(train_mean_mae["reward"], 9),
            "train_mean_mae_by_target": {
                key: round(value, 9)
                for key, value in train_mean_mae.items()
            },
        },
        "supported_claim": (
            "graph_aware_world_model_beats_target_only_and_train_mean_baselines"
            if supported
            else "no_graph_aware_world_model_advantage_claim_supported"
        ),
        "empirical_superiority_claim": False,
        "claim_boundary": {
            "max_claim_level": "bounded_support" if supported else "not_for_claim",
            "reason": (
                "graph-aware dynamics are evaluated on prepared spatial Graph-MDP replay holdout; "
                "observed policy outcome gates remain open"
            ),
        },
        "remaining_gates": [
            "observed_policy_outcome_required",
            "off_policy_evaluation_on_observed_or_quasi_observed_data_required",
            "causal_policy_effect_validation_required",
            "external_scene_aligned_holdout_required",
        ],
    }


def _training_row(
    transition: dict[str, Any],
    *,
    node_features: dict[str, dict[str, float]],
    neighbors_by_unit: dict[str, set[str]],
    node_count: int,
) -> dict[str, Any]:
    action = transition.get("action") or {}
    step_index = _float((transition.get("transition") or {}).get("step_index"))
    target_only = _target_only_features_for_action(
        action,
        node_features=node_features,
        step_index=step_index,
    )
    graph_features = _graph_aware_features_for_action(
        action,
        node_features=node_features,
        neighbors_by_unit=neighbors_by_unit,
        node_count=node_count,
        target_only_features=target_only,
    )
    return {
        "target_only_features": target_only,
        "graph_features": graph_features,
        "targets": _targets_for_transition(transition),
    }


def _target_only_features_for_action(
    action: dict[str, Any],
    *,
    node_features: dict[str, dict[str, float]],
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
        1.0 if "heat" in mask_reason else 0.0,
        1.0 if "air_pollution" in mask_reason else 0.0,
        1.0 if "service" in mask_reason else 0.0,
        step_index / 10.0,
    ]


def _graph_aware_features_for_action(
    action: dict[str, Any],
    *,
    node_features: dict[str, dict[str, float]],
    neighbors_by_unit: dict[str, set[str]],
    node_count: int,
    target_only_features: list[float],
) -> list[float]:
    target_unit = _first_target_unit(action)
    target = node_features.get(target_unit) or {}
    neighbor_units = sorted(neighbors_by_unit.get(target_unit) or [])
    neighbor_features = [node_features[unit] for unit in neighbor_units if unit in node_features]
    neighbor = _mean_features(neighbor_features)
    target_heat = _float(target.get("heat_risk"))
    target_air = _float(target.get("air_pollution_exposure"))
    target_service_gap = max(0.0, 1.0 - _float(target.get("service_accessibility")))
    target_livability_gap = max(0.0, 1.0 - _float(target.get("livability")))
    neighbor_heat = neighbor["heat_risk"]
    neighbor_air = neighbor["air_pollution_exposure"]
    neighbor_service_gap = max(0.0, 1.0 - neighbor["service_accessibility"])
    neighbor_livability_gap = max(0.0, 1.0 - neighbor["livability"])
    degree_norm = len(neighbor_units) / max(1.0, float(node_count - 1))
    neighbor_count_norm = len(neighbor_features) / max(1.0, float(node_count - 1))
    is_green = target_only_features[1]
    is_traffic = target_only_features[2]
    is_service = target_only_features[3]
    return [
        *target_only_features,
        degree_norm,
        neighbor_count_norm,
        neighbor_heat,
        neighbor_air,
        neighbor_service_gap,
        neighbor["equity"],
        neighbor_livability_gap,
        target_heat - neighbor_heat,
        target_air - neighbor_air,
        target_service_gap - neighbor_service_gap,
        target_livability_gap - neighbor_livability_gap,
        is_green * neighbor_heat * neighbor_count_norm,
        is_traffic * neighbor_air * neighbor_count_norm,
        is_service * neighbor_service_gap * neighbor_count_norm,
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
    for row in (next_state_delta.get("per_unit") or {}).values():
        if not isinstance(row, dict):
            continue
        for key in totals:
            totals[key] += _float(row.get(key))
    return totals


def _node_features_by_unit(graph_state: dict[str, Any]) -> dict[str, dict[str, float]]:
    nodes = {}
    for node in graph_state.get("nodes") or []:
        unit_id = str(node.get("unit_id") or node.get("node_id") or "")
        features = node.get("features") or {}
        if not unit_id:
            continue
        nodes[unit_id] = {
            "heat_risk": _float(features.get("heat_risk")),
            "air_pollution_exposure": _float(features.get("air_pollution_exposure")),
            "service_accessibility": _float(features.get("service_accessibility")),
            "equity": _float(features.get("equity")),
            "livability": _float(features.get("livability")),
        }
    return nodes


def _neighbors_by_unit(graph_state: dict[str, Any]) -> dict[str, set[str]]:
    neighbors: dict[str, set[str]] = {}
    for edge in graph_state.get("edges") or []:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source and target:
            neighbors.setdefault(source, set()).add(target)
            neighbors.setdefault(target, set()).add(source)
    return neighbors


def _mean_features(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {
            "heat_risk": 0.0,
            "air_pollution_exposure": 0.0,
            "service_accessibility": 0.0,
            "equity": 0.0,
            "livability": 0.0,
        }
    return {
        key: sum(_float(row.get(key)) for row in rows) / len(rows)
        for key in [
            "heat_risk",
            "air_pollution_exposure",
            "service_accessibility",
            "equity",
            "livability",
        ]
    }


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


def _dynamics_mean_mae(mae_by_target: dict[str, float]) -> float:
    values = [mae_by_target[name] for name in TARGET_NAMES[1:]]
    return float(sum(values) / len(values)) if values else 0.0


def _coefficient_table(
    coefficients: np.ndarray,
    feature_names: list[str],
) -> dict[str, dict[str, float]]:
    table: dict[str, dict[str, float]] = {}
    for target_index, target_name in enumerate(TARGET_NAMES):
        table[target_name] = {
            feature_name: round(float(coefficients[feature_index, target_index]), 9)
            for feature_index, feature_name in enumerate(feature_names)
        }
    return table


def _first_target_unit(action: dict[str, Any]) -> str:
    targets = action.get("target_units")
    if isinstance(targets, list) and targets:
        return str(targets[0])
    if action.get("target_unit") is not None:
        return str(action.get("target_unit"))
    return ""


def _edge_count(graph_state: dict[str, Any]) -> int:
    return len(graph_state.get("edges") or [])


def _int(value: Any, default: int = 0) -> int:
    if value in {None, ""}:
        return default
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
