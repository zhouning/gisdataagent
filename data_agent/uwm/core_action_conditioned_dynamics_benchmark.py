"""Core UWM action-conditioned dynamics benchmark over full-admin replay."""

from __future__ import annotations

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


UWM_CORE_ACTION_CONDITIONED_DYNAMICS_BENCHMARK_SCHEMA = (
    "uwm.core_action_conditioned_dynamics_benchmark.v1"
)

_SUPPORTED_CLAIM = "core_action_conditioned_dynamics_beats_static_and_no_action_baselines"
_NO_CLAIM = "no_core_action_conditioned_dynamics_claim_supported"

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


def build_uwm_core_action_conditioned_dynamics_benchmark(
    *,
    full_admin_graph_planner_replay: dict[str, Any],
    benchmark_id: str,
    created_at: str,
    source_artifact_path: str | None = None,
    holdout_stride: int = 7,
    ridge: float = 0.001,
    shuffle_offset: int = 137,
) -> dict[str, Any]:
    """Evaluate the action-conditioned dynamics core against ablation baselines."""

    if not isinstance(full_admin_graph_planner_replay, dict):
        raise TypeError("full_admin_graph_planner_replay must be a dictionary")
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
            "core action-conditioned dynamics benchmark requires at least three transitions"
        )

    feature_matrix, targets = _training_matrices(
        graph_state=graph_state,
        transitions=transitions,
    )
    holdout_indices = _holdout_indices(len(transitions), holdout_stride)
    holdout_set = set(holdout_indices)
    train_indices = [index for index in range(len(transitions)) if index not in holdout_set]
    if not train_indices:
        train_indices = [index for index in range(len(transitions)) if index != holdout_indices[-1]]
        holdout_indices = [holdout_indices[-1]]

    action_columns = _action_signal_columns()
    graph_degree_columns = _feature_columns(["target_degree_norm"])
    variant_metrics = _variant_metrics(
        feature_matrix=feature_matrix,
        targets=targets,
        train_indices=train_indices,
        holdout_indices=holdout_indices,
        action_columns=action_columns,
        graph_degree_columns=graph_degree_columns,
        ridge=ridge,
        shuffle_offset=shuffle_offset,
    )
    action_gate = _action_conditioning_gate(variant_metrics)
    scope_guard = _full_admin_scope_guard(
        full_admin_graph_planner_replay,
        transition_row_count=len(transitions),
    )
    ready = scope_guard["passed"] is True and action_gate["passed"] is True
    remaining_gates = _remaining_gates(scope_guard, action_gate)

    return {
        "schema": UWM_CORE_ACTION_CONDITIONED_DYNAMICS_BENCHMARK_SCHEMA,
        "benchmark_id": benchmark_id,
        "created_at": created_at,
        "experiment_scope": "full_admin_graph",
        "feature_names": list(FEATURE_NAMES),
        "target_names": list(TARGET_NAMES),
        "full_admin_scope_guard": scope_guard,
        "holdout_summary": {
            "holdout_stride": holdout_stride,
            "ridge": ridge,
            "row_count": len(transitions),
            "train_count": len(train_indices),
            "holdout_count": len(holdout_indices),
            "first_holdout_index": int(holdout_indices[0]),
            "last_holdout_index": int(holdout_indices[-1]),
        },
        "variant_metrics": variant_metrics,
        "action_conditioning_gate": action_gate,
        "supported_claim": _SUPPORTED_CLAIM if ready else _NO_CLAIM,
        "claim_boundary": {
            "max_claim_level": "bounded_support" if ready else "not_for_claim",
            "reason": (
                "The benchmark tests same-scene full-admin replay dynamics prediction: "
                "an action-conditioned graph-state model must beat static, no-action, "
                "and shuffled-action baselines on every modeled target. It does not "
                "claim observed intervention or policy-outcome superiority."
            ),
        },
        "remaining_gates": remaining_gates,
        "audit_trace": {
            "source_artifact_path": source_artifact_path,
            "model_class": "linear_ridge_action_conditioned_graph_dynamics",
            "action_signal_feature_names": [
                FEATURE_NAMES[index] for index in action_columns
            ],
            "graph_degree_feature_names": [
                FEATURE_NAMES[index] for index in graph_degree_columns
            ],
            "shuffled_action_signal_roll_offset": shuffle_offset,
        },
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def validate_uwm_core_action_conditioned_dynamics_benchmark(
    benchmark: dict[str, Any],
) -> dict[str, Any]:
    """Validate the core dynamics benchmark contract without forcing a claim."""

    errors: list[str] = []
    if not isinstance(benchmark, dict):
        return {"valid": False, "errors": ["benchmark must be a dictionary"]}
    if benchmark.get("schema") != UWM_CORE_ACTION_CONDITIONED_DYNAMICS_BENCHMARK_SCHEMA:
        errors.append(
            "schema must be uwm.core_action_conditioned_dynamics_benchmark.v1"
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
        if (benchmark.get("action_conditioning_gate") or {}).get("passed") is not True:
            errors.append("supported claim requires action_conditioning_gate.passed")
        if (benchmark.get("claim_boundary") or {}).get("max_claim_level") != "bounded_support":
            errors.append("supported claim requires bounded_support claim boundary")
        _validate_metric_dominance(benchmark, errors)
    elif supported == _NO_CLAIM:
        if (benchmark.get("claim_boundary") or {}).get("max_claim_level") != "not_for_claim":
            errors.append("no-claim benchmark must use not_for_claim boundary")
    else:
        errors.append("supported_claim has unknown value")

    return {"valid": not errors, "errors": errors}


def _training_matrices(
    *,
    graph_state: dict[str, Any],
    transitions: list[dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray]:
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
    return (
        np.array([row["features"] for row in rows], dtype=float),
        np.array([row["targets"] for row in rows], dtype=float),
    )


def _variant_metrics(
    *,
    feature_matrix: np.ndarray,
    targets: np.ndarray,
    train_indices: list[int],
    holdout_indices: list[int],
    action_columns: list[int],
    graph_degree_columns: list[int],
    ridge: float,
    shuffle_offset: int,
) -> dict[str, dict[str, Any]]:
    x_train = feature_matrix[train_indices]
    y_train = targets[train_indices]
    x_holdout = feature_matrix[holdout_indices]
    y_holdout = targets[holdout_indices]
    train_mean = np.mean(y_train, axis=0)

    variants = {
        "full_action_state_graph": _fit_predict_variant(
            x_train,
            y_train,
            x_holdout,
            y_holdout,
            ridge=ridge,
            feature_policy="all_action_state_graph_features",
        ),
        "train_mean_static": {
            "feature_policy": "train_target_mean_static_baseline",
            "mae_by_target": _round_mae(
                _mae_by_target(
                    y_holdout,
                    np.tile(train_mean, (len(holdout_indices), 1)),
                )
            ),
            "target_mean_by_target": _rounded_target_values(train_mean),
        },
        "no_action_signal": _fit_predict_variant(
            _zero_columns(x_train, action_columns),
            y_train,
            _zero_columns(x_holdout, action_columns),
            y_holdout,
            ridge=ridge,
            feature_policy="action_type_intensity_and_mask_signal_zeroed",
        ),
        "shuffled_action_signal": _fit_predict_variant(
            _shuffle_columns(feature_matrix, action_columns, shuffle_offset)[train_indices],
            y_train,
            _shuffle_columns(feature_matrix, action_columns, shuffle_offset)[holdout_indices],
            y_holdout,
            ridge=ridge,
            feature_policy="action_type_intensity_and_mask_signal_roll_shuffled",
        ),
        "no_graph_degree": _fit_predict_variant(
            _zero_columns(x_train, graph_degree_columns),
            y_train,
            _zero_columns(x_holdout, graph_degree_columns),
            y_holdout,
            ridge=ridge,
            feature_policy="target_graph_degree_zeroed_diagnostic",
        ),
    }
    return variants


def _fit_predict_variant(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_holdout: np.ndarray,
    y_holdout: np.ndarray,
    *,
    ridge: float,
    feature_policy: str,
) -> dict[str, Any]:
    coefficients = _fit_ridge_multi_output(x_train, y_train, ridge)
    predictions = x_holdout @ coefficients
    return {
        "model_class": "linear_ridge_multi_output_dynamics",
        "feature_policy": feature_policy,
        "mae_by_target": _round_mae(_mae_by_target(y_holdout, predictions)),
    }


def _action_conditioning_gate(
    variant_metrics: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    full = variant_metrics["full_action_state_graph"]["mae_by_target"]
    train_mean = variant_metrics["train_mean_static"]["mae_by_target"]
    no_action = variant_metrics["no_action_signal"]["mae_by_target"]
    shuffled = variant_metrics["shuffled_action_signal"]["mae_by_target"]
    target_rows = []
    for target in TARGET_NAMES:
        full_mae = full[target]
        train_mean_mae = train_mean[target]
        no_action_mae = no_action[target]
        shuffled_mae = shuffled[target]
        target_rows.append(
            {
                "target": target,
                "full_action_state_graph_mae": full_mae,
                "train_mean_static_mae": train_mean_mae,
                "no_action_signal_mae": no_action_mae,
                "shuffled_action_signal_mae": shuffled_mae,
                "beats_train_mean_static": full_mae < train_mean_mae,
                "beats_no_action_signal": full_mae < no_action_mae,
                "beats_shuffled_action_signal": full_mae < shuffled_mae,
                "relative_mae_reduction_vs_no_action_signal": _relative_reduction(
                    full_mae, no_action_mae
                ),
                "relative_mae_reduction_vs_shuffled_action_signal": _relative_reduction(
                    full_mae, shuffled_mae
                ),
            }
        )
    passed = all(
        row["beats_train_mean_static"]
        and row["beats_no_action_signal"]
        and row["beats_shuffled_action_signal"]
        for row in target_rows
    )
    return {
        "passed": passed,
        "required_baselines": [
            "train_mean_static",
            "no_action_signal",
            "shuffled_action_signal",
        ],
        "diagnostic_only_variants": ["no_graph_degree"],
        "target_rows": target_rows,
    }


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
    return {
        "passed": not failures,
        "required_scope": "full_admin_graph",
        "required_counts": dict(_REQUIRED_FULL_ADMIN_COUNTS),
        **counts,
        "failed_count_fields": failures,
    }


def _remaining_gates(
    scope_guard: dict[str, Any],
    action_gate: dict[str, Any],
) -> list[str]:
    gates = [
        "observed_policy_outcome_holdout_required",
        "causal_policy_effect_validation_required",
        "external_cross_city_or_cross_time_holdout_required",
        "authoritative_operational_data_closure_required",
    ]
    if scope_guard.get("passed") is not True:
        gates.insert(0, "full_admin_scope_guard_failed")
    if action_gate.get("passed") is not True:
        gates.insert(0, "action_conditioning_gate_failed")
    return gates


def _validate_metric_dominance(
    benchmark: dict[str, Any],
    errors: list[str],
) -> None:
    metrics = benchmark.get("variant_metrics") or {}
    full = (metrics.get("full_action_state_graph") or {}).get("mae_by_target") or {}
    train_mean = (metrics.get("train_mean_static") or {}).get("mae_by_target") or {}
    no_action = (metrics.get("no_action_signal") or {}).get("mae_by_target") or {}
    shuffled = (metrics.get("shuffled_action_signal") or {}).get("mae_by_target") or {}
    for target in TARGET_NAMES:
        try:
            full_mae = float(full[target])
            if not (
                full_mae < float(train_mean[target])
                and full_mae < float(no_action[target])
                and full_mae < float(shuffled[target])
            ):
                errors.append(f"full model does not beat all required baselines for {target}")
        except (KeyError, TypeError, ValueError):
            errors.append(f"missing comparable mae metrics for {target}")


def _action_signal_columns() -> list[int]:
    return [
        index
        for index, name in enumerate(FEATURE_NAMES)
        if name.startswith("action_") or name in _ACTION_SIGNAL_FEATURES
    ]


def _feature_columns(names: list[str]) -> list[int]:
    wanted = set(names)
    return [index for index, name in enumerate(FEATURE_NAMES) if name in wanted]


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


def _rounded_target_values(values: np.ndarray) -> dict[str, float]:
    return {
        name: round(float(value), 9)
        for name, value in zip(TARGET_NAMES, values)
    }


def _relative_reduction(candidate: float, baseline: float) -> float:
    if baseline == 0:
        return 0.0
    return round((baseline - candidate) / baseline, 9)


def _int_or_count(value: Any, rows: Any) -> int:
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    if isinstance(rows, list):
        return len(rows)
    return 0
