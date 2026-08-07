"""Strict multi-geometry benchmark for geospatial state-prior reconstruction."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import numpy as np

UWM_GEOSPATIAL_STATE_PRIOR_DATASET_SCHEMA = "uwm.geospatial_state_prior_dataset.v1"
UWM_GEOSPATIAL_STATE_PRIOR_BENCHMARK_SCHEMA = "uwm.geospatial_state_prior_benchmark.v1"

REQUIRED_GEOMETRY_ROUTES = ("raster", "admin", "graph_object")
REQUIRED_SPLITS = ("spatial_block", "whole_admin", "future_temporal")
SOURCE_EVIDENCE_KINDS = {"observed_holdout", "public_proxy", "synthetic_fixture"}

_ROUTE_GEOMETRY_TYPES = {
    "raster": {"raster"},
    "admin": {"polygon"},
    "graph_object": {"network", "point", "polygon"},
}
_ROUTE_SUPPORT_TYPES = {
    "raster": {"grid_cell"},
    "admin": {"admin_unit"},
    "graph_object": {"network_edge", "network_node", "parcel", "spatial_object"},
}

_CANDIDATE = "multi_geometry_soft_alignment_ridge"
_REQUIRED_BASELINES = (
    "spatial_idw",
    "hard_admin_mean",
    "raster_only_ridge",
    "raster_admin_soft_alignment_ridge",
)
_NEGATIVE_CONTROLS = (
    "shuffled_admin_alignment_ridge",
    "shuffled_graph_alignment_ridge",
)
_SUPPORTED_CLAIM = "multi_geometry_state_reconstruction_advantage_under_strict_holdout"
_NO_CLAIM = "no_multi_geometry_state_reconstruction_claim_supported"
_EXECUTION_CLAIM = "multi_geometry_benchmark_execution_only"


def build_uwm_geospatial_state_prior_benchmark(
    *,
    dataset: dict[str, Any],
    benchmark_id: str,
    created_at: str,
    confidence_level: float = 0.9,
    coverage_tolerance: float = 0.05,
    ridge: float = 1e-6,
    idw_neighbors: int = 8,
    negative_control_seed: int = 37,
    minimum_relative_improvement: float = 0.01,
    minimum_time_groups_per_dynamic_feature: float = 3.0,
) -> dict[str, Any]:
    """Evaluate bounded state reconstruction without claiming transition dynamics."""

    validation = validate_uwm_geospatial_state_prior_dataset(dataset)
    if not validation["valid"]:
        raise ValueError("; ".join(validation["errors"]))
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between 0 and 1")
    if not 0.0 <= coverage_tolerance < 1.0:
        raise ValueError("coverage_tolerance must be between 0 and 1")
    if ridge < 0.0:
        raise ValueError("ridge must be non-negative")
    if idw_neighbors < 1:
        raise ValueError("idw_neighbors must be positive")
    if not 0.0 <= minimum_relative_improvement < 1.0:
        raise ValueError("minimum_relative_improvement must be between 0 and 1")
    if minimum_time_groups_per_dynamic_feature <= 0.0:
        raise ValueError("minimum_time_groups_per_dynamic_feature must be positive")

    rows = list(dataset["rows"])
    route_features = {
        route: list(dataset["geometry_routes"][route]["feature_names"])
        for route in REQUIRED_GEOMETRY_ROUTES
    }
    dynamic_context = dataset.get("dynamic_context") or {}
    dynamic_context_features = list(dynamic_context.get("feature_names") or [])
    split_indices = _strict_split_indices(rows)
    split_results: dict[str, dict[str, Any]] = {}
    calibration_records: list[dict[str, Any]] = []
    for split_offset, split_name in enumerate(REQUIRED_SPLITS):
        result, calibration_record = _evaluate_split(
            rows=rows,
            route_features=route_features,
            dynamic_context_features=dynamic_context_features,
            split_name=split_name,
            indices=split_indices[split_name],
            confidence_level=confidence_level,
            ridge=ridge,
            idw_neighbors=idw_neighbors,
            negative_control_seed=negative_control_seed + split_offset,
        )
        split_results[split_name] = result
        calibration_records.append(calibration_record)

    aggregate_results = _aggregate_method_metrics(split_results)
    dynamic_context_audit = _dynamic_context_audit(
        dataset=dataset,
        rows=rows,
        split_results=split_results,
        minimum_time_groups_per_feature=minimum_time_groups_per_dynamic_feature,
    )
    calibration = _aggregate_calibration(
        calibration_records,
        confidence_level=confidence_level,
        coverage_tolerance=coverage_tolerance,
    )
    gates = _readiness_gates(
        dataset=dataset,
        split_results=split_results,
        aggregate_results=aggregate_results,
        calibration=calibration,
        minimum_relative_improvement=minimum_relative_improvement,
        dynamic_context_audit=dynamic_context_audit,
    )
    ready = all(gates.values())
    evidence_kind = str(dataset["source_evidence_kind"])
    if ready:
        supported_claim = _SUPPORTED_CLAIM
        max_claim_level = "bounded_support"
    elif evidence_kind != "observed_holdout":
        supported_claim = _EXECUTION_CLAIM
        max_claim_level = "exploratory_only"
    else:
        supported_claim = _NO_CLAIM
        max_claim_level = "not_for_claim"

    return {
        "schema": UWM_GEOSPATIAL_STATE_PRIOR_BENCHMARK_SCHEMA,
        "version": "0.1",
        "benchmark_id": str(benchmark_id),
        "created_at": str(created_at),
        "dataset_id": dataset["dataset_id"],
        "source_evidence_kind": evidence_kind,
        "source_dataset_ids": list(dataset["source_dataset_ids"]),
        "evidence_refs": list(dataset["evidence_refs"]),
        "target": dict(dataset["target"]),
        "geometry_routes": {
            route: dict(dataset["geometry_routes"][route]) for route in REQUIRED_GEOMETRY_ROUTES
        },
        "dynamic_context": dict(dynamic_context) if dynamic_context else None,
        "benchmark_protocol": {
            "split_names": list(REQUIRED_SPLITS),
            "candidate_method": _CANDIDATE,
            "required_baselines": list(_REQUIRED_BASELINES),
            "negative_controls": list(_NEGATIVE_CONTROLS),
            "model_class": "deterministic_standardized_ridge",
            "query_context_features": [
                "x",
                "y",
                "ordered_time_index",
                *dynamic_context_features,
            ],
            "dynamic_context_shared_by_all_primary_ridge_variants": True,
            "dynamic_context_ablation_method": ("multi_geometry_no_dynamic_context_ridge"),
            "geometry_alignment": (
                "learned linear feature fusion without hard cross-support equality"
            ),
            "ridge": ridge,
            "idw_neighbors": idw_neighbors,
            "negative_control_seed": negative_control_seed,
            "minimum_relative_improvement": minimum_relative_improvement,
            "minimum_time_groups_per_dynamic_feature": (minimum_time_groups_per_dynamic_feature),
        },
        "split_results": split_results,
        "aggregate_results": aggregate_results,
        "dynamic_context_audit": dynamic_context_audit,
        "uncertainty_calibration": calibration,
        "readiness_gates": gates,
        "remaining_gates": [name for name, passed in gates.items() if not passed],
        "geospatial_state_prior_benchmark_ready": ready,
        "supported_claim": supported_claim,
        "claim_boundary": {
            "max_claim_level": max_claim_level,
            "reason": _claim_reason(ready=ready, evidence_kind=evidence_kind),
        },
        "policy_causal_effect_claim": False,
        "action_conditioned_dynamics_claim": False,
        "general_geospatial_world_model_validation_claim": False,
        "limitations": [
            "state_reconstruction_only_not_action_conditioned_dynamics",
            "linear_fusion_candidate_not_foundation_scale_pretraining",
            "strict_holdout_does_not_establish_policy_causality",
            "observed_holdout_evidence_required_for_bounded_reconstruction_claim",
        ],
    }


def validate_uwm_geospatial_state_prior_dataset(
    dataset: Any,
) -> dict[str, Any]:
    """Validate native geometry routes and observed reconstruction targets."""

    if not isinstance(dataset, dict):
        return {"valid": False, "errors": ["dataset must be a dictionary"]}
    errors: list[str] = []
    if dataset.get("schema") != UWM_GEOSPATIAL_STATE_PRIOR_DATASET_SCHEMA:
        errors.append(f"schema must be {UWM_GEOSPATIAL_STATE_PRIOR_DATASET_SCHEMA}")
    if not str(dataset.get("dataset_id") or "").strip():
        errors.append("dataset_id is required")
    evidence_kind = dataset.get("source_evidence_kind")
    if evidence_kind not in SOURCE_EVIDENCE_KINDS:
        errors.append(f"source_evidence_kind must be one of {sorted(SOURCE_EVIDENCE_KINDS)}")
    source_dataset_ids = dataset.get("source_dataset_ids")
    if not isinstance(source_dataset_ids, list) or not source_dataset_ids:
        errors.append("source_dataset_ids must be a non-empty list")
    evidence_refs = dataset.get("evidence_refs")
    if not isinstance(evidence_refs, list):
        errors.append("evidence_refs must be a list")
    elif evidence_kind == "observed_holdout" and not evidence_refs:
        errors.append("observed_holdout requires evidence_refs")

    target = dataset.get("target")
    if not isinstance(target, dict):
        errors.append("target must be an object")
    else:
        if target.get("observation_semantics") != "observed":
            errors.append("target.observation_semantics must be observed")
        if not str(target.get("geometry_type") or "").strip():
            errors.append("target.geometry_type is required")
        target_support = target.get("spatial_support")
        if not isinstance(target_support, dict) or not target_support.get("support_type"):
            errors.append("target.spatial_support.support_type is required")

    routes = dataset.get("geometry_routes")
    route_features: dict[str, list[str]] = {}
    if not isinstance(routes, dict):
        errors.append("geometry_routes must be an object")
    else:
        for route in REQUIRED_GEOMETRY_ROUTES:
            route_payload = routes.get(route)
            if not isinstance(route_payload, dict):
                errors.append(f"geometry_routes.{route} must be an object")
                continue
            geometry_type = route_payload.get("geometry_type")
            if geometry_type not in _ROUTE_GEOMETRY_TYPES[route]:
                errors.append(
                    f"geometry_routes.{route}.geometry_type must be one of "
                    f"{sorted(_ROUTE_GEOMETRY_TYPES[route])}"
                )
            spatial_support = route_payload.get("spatial_support")
            if not isinstance(spatial_support, dict) or not spatial_support.get("support_type"):
                errors.append(f"geometry_routes.{route}.spatial_support.support_type is required")
            elif spatial_support.get("support_type") not in _ROUTE_SUPPORT_TYPES[route]:
                errors.append(
                    f"geometry_routes.{route}.spatial_support.support_type must be one of "
                    f"{sorted(_ROUTE_SUPPORT_TYPES[route])}"
                )
            feature_names = route_payload.get("feature_names")
            if (
                not isinstance(feature_names, list)
                or not feature_names
                or any(not str(name).strip() for name in feature_names)
                or len(set(feature_names)) != len(feature_names)
            ):
                errors.append(
                    f"geometry_routes.{route}.feature_names must be unique non-empty names"
                )
            else:
                route_features[route] = [str(name) for name in feature_names]

    dynamic_context = dataset.get("dynamic_context")
    dynamic_context_features: list[str] = []
    if dynamic_context is not None:
        if not isinstance(dynamic_context, dict):
            errors.append("dynamic_context must be an object")
        else:
            feature_names = dynamic_context.get("feature_names")
            if (
                not isinstance(feature_names, list)
                or not feature_names
                or any(not str(name).strip() for name in feature_names)
                or len(set(feature_names)) != len(feature_names)
            ):
                errors.append("dynamic_context.feature_names must be unique non-empty names")
            else:
                dynamic_context_features = [str(name) for name in feature_names]
            if dynamic_context.get("uses_target_values") is not False:
                errors.append("dynamic_context.uses_target_values must be false")

    rows = dataset.get("rows")
    if not isinstance(rows, list) or len(rows) < 18:
        errors.append("rows must contain at least 18 samples")
        rows = []
    sample_ids: set[str] = set()
    spatial_x: set[float] = set()
    admin_ids: set[str] = set()
    time_ids: set[str] = set()
    for index, row in enumerate(rows):
        prefix = f"rows[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{prefix} must be an object")
            continue
        sample_id = str(row.get("sample_id") or "").strip()
        if not sample_id:
            errors.append(f"{prefix}.sample_id is required")
        elif sample_id in sample_ids:
            errors.append(f"{prefix}.sample_id must be unique")
        sample_ids.add(sample_id)
        if not _is_finite_number(row.get("x")) or not _is_finite_number(row.get("y")):
            errors.append(f"{prefix}.x and y must be finite numbers")
        else:
            spatial_x.add(float(row["x"]))
        admin_id = str(row.get("admin_unit_id") or "").strip()
        time_id = str(row.get("time_id") or "").strip()
        if not admin_id:
            errors.append(f"{prefix}.admin_unit_id is required")
        else:
            admin_ids.add(admin_id)
        if not time_id:
            errors.append(f"{prefix}.time_id is required")
        else:
            time_ids.add(time_id)
        if not _is_finite_number(row.get("target")):
            errors.append(f"{prefix}.target must be a finite number")
        for route, feature_names in route_features.items():
            values = row.get(f"{route}_features")
            if not isinstance(values, dict):
                errors.append(f"{prefix}.{route}_features must be an object")
                continue
            if set(values) != set(feature_names):
                errors.append(f"{prefix}.{route}_features must match declared feature_names")
                continue
            if any(not _is_finite_number(values[name]) for name in feature_names):
                errors.append(f"{prefix}.{route}_features must contain finite numbers")
        if dynamic_context_features:
            values = row.get("dynamic_context_features")
            if not isinstance(values, dict):
                errors.append(f"{prefix}.dynamic_context_features must be an object")
            elif set(values) != set(dynamic_context_features):
                errors.append(
                    f"{prefix}.dynamic_context_features must match declared feature_names"
                )
            elif any(not _is_finite_number(values[name]) for name in dynamic_context_features):
                errors.append(f"{prefix}.dynamic_context_features must contain finite numbers")

    if rows and len(spatial_x) < 5:
        errors.append("rows require at least five distinct x bands for spatial holdout")
    if rows and len(admin_ids) < 5:
        errors.append("rows require at least five admin units for group holdout")
    if rows and len(time_ids) < 5:
        errors.append("rows require at least five time periods for temporal holdout")
    if (
        rows
        and dynamic_context_features
        and isinstance(dynamic_context, dict)
        and dynamic_context.get("shared_across_spatial_units") is True
    ):
        values_by_time: dict[str, set[tuple[float, ...]]] = defaultdict(set)
        for row in rows:
            values = row.get("dynamic_context_features") or {}
            if all(name in values for name in dynamic_context_features):
                values_by_time[str(row.get("time_id"))].add(
                    tuple(float(values[name]) for name in dynamic_context_features)
                )
        if any(len(values) != 1 for values in values_by_time.values()):
            errors.append("shared dynamic_context_features must be identical within each time_id")
    return {"valid": not errors, "errors": errors}


def validate_uwm_geospatial_state_prior_benchmark(
    benchmark: Any,
) -> dict[str, Any]:
    """Validate benchmark evidence gates and prohibit claim escalation."""

    if not isinstance(benchmark, dict):
        return {"valid": False, "errors": ["benchmark must be a dictionary"]}
    errors: list[str] = []
    if benchmark.get("schema") != UWM_GEOSPATIAL_STATE_PRIOR_BENCHMARK_SCHEMA:
        errors.append(f"schema must be {UWM_GEOSPATIAL_STATE_PRIOR_BENCHMARK_SCHEMA}")
    for key in (
        "benchmark_id",
        "geometry_routes",
        "split_results",
        "aggregate_results",
        "dynamic_context_audit",
        "uncertainty_calibration",
        "readiness_gates",
        "remaining_gates",
        "claim_boundary",
    ):
        if key not in benchmark:
            errors.append(f"{key} is required")
    split_results = benchmark.get("split_results") or {}
    if set(split_results) != set(REQUIRED_SPLITS):
        errors.append("split_results must contain all required strict splits")
    for split_name in REQUIRED_SPLITS:
        leakage = (split_results.get(split_name) or {}).get("leakage_audit") or {}
        if leakage.get("passed") is not True:
            errors.append(f"{split_name} leakage audit must pass")
    if benchmark.get("policy_causal_effect_claim") is not False:
        errors.append("policy_causal_effect_claim must be false")
    if benchmark.get("action_conditioned_dynamics_claim") is not False:
        errors.append("action_conditioned_dynamics_claim must be false")
    if benchmark.get("general_geospatial_world_model_validation_claim") is not False:
        errors.append("general_geospatial_world_model_validation_claim must be false")
    routes = benchmark.get("geometry_routes") or {}
    if not isinstance(routes, dict) or not set(REQUIRED_GEOMETRY_ROUTES).issubset(routes):
        errors.append("benchmark must preserve all required geometry routes")
    dynamic_context = benchmark.get("dynamic_context")
    dynamic_audit = benchmark.get("dynamic_context_audit") or {}
    if dynamic_context:
        if not isinstance(dynamic_context, dict):
            errors.append("dynamic_context must be an object or null")
        elif dynamic_context.get("uses_target_values") is not False:
            errors.append("dynamic_context.uses_target_values must be false")
        if dynamic_audit.get("declared") is not True:
            errors.append("declared dynamic_context requires a dynamic_context_audit")
    elif dynamic_audit.get("declared") is not False:
        errors.append("absent dynamic_context requires an undeclared audit")

    ready = benchmark.get("geospatial_state_prior_benchmark_ready") is True
    claim_level = (benchmark.get("claim_boundary") or {}).get("max_claim_level")
    if ready:
        gates = benchmark.get("readiness_gates") or {}
        if not gates or not all(value is True for value in gates.values()):
            errors.append("ready benchmark requires every readiness gate")
        if benchmark.get("source_evidence_kind") != "observed_holdout":
            errors.append("ready benchmark requires observed_holdout evidence")
        if not benchmark.get("evidence_refs"):
            errors.append("ready benchmark requires evidence_refs")
        if benchmark.get("supported_claim") != _SUPPORTED_CLAIM:
            errors.append("ready benchmark has unsupported claim")
        if claim_level != "bounded_support":
            errors.append("ready benchmark requires bounded_support")
    else:
        if claim_level == "bounded_support":
            errors.append("non-ready benchmark cannot use bounded_support")
        if benchmark.get("supported_claim") == _SUPPORTED_CLAIM:
            errors.append("non-ready benchmark cannot use supported reconstruction claim")
    return {"valid": not errors, "errors": errors}


def _strict_split_indices(rows: list[dict[str, Any]]) -> dict[str, dict[str, list[int]]]:
    split_keys = {
        "spatial_block": [float(row["x"]) for row in rows],
        "whole_admin": [str(row["admin_unit_id"]) for row in rows],
        "future_temporal": [str(row["time_id"]) for row in rows],
    }
    return {split_name: _partition_by_group(keys) for split_name, keys in split_keys.items()}


def _partition_by_group(keys: list[Any]) -> dict[str, list[int]]:
    groups = sorted(set(keys))
    calibration_count = max(1, int(len(groups) * 0.2))
    holdout_count = max(1, int(len(groups) * 0.2))
    train_count = len(groups) - calibration_count - holdout_count
    if train_count < 1:
        raise ValueError("strict split requires at least one train group")
    train_groups = set(groups[:train_count])
    calibration_groups = set(groups[train_count : train_count + calibration_count])
    holdout_groups = set(groups[train_count + calibration_count :])
    return {
        "train": [index for index, key in enumerate(keys) if key in train_groups],
        "calibration": [index for index, key in enumerate(keys) if key in calibration_groups],
        "holdout": [index for index, key in enumerate(keys) if key in holdout_groups],
    }


def _evaluate_split(
    *,
    rows: list[dict[str, Any]],
    route_features: dict[str, list[str]],
    dynamic_context_features: list[str],
    split_name: str,
    indices: dict[str, list[int]],
    confidence_level: float,
    ridge: float,
    idw_neighbors: int,
    negative_control_seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    y = np.array([float(row["target"]) for row in rows], dtype=float)
    matrices = {
        route: _feature_matrix(rows, route, route_features[route])
        for route in REQUIRED_GEOMETRY_ROUTES
    }
    base_context = _query_context_matrix(rows)
    context = base_context
    if dynamic_context_features:
        context = np.column_stack(
            (
                context,
                _feature_matrix(rows, "dynamic_context", dynamic_context_features),
            )
        )
    train = indices["train"]
    calibration = indices["calibration"]
    holdout = indices["holdout"]
    method_predictions: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    train_mean = float(np.mean(y[train]))
    method_predictions["train_mean"] = (
        np.full(len(calibration), train_mean),
        np.full(len(holdout), train_mean),
    )
    method_predictions["spatial_idw"] = (
        _idw_predict(rows, y, train, calibration, idw_neighbors),
        _idw_predict(rows, y, train, holdout, idw_neighbors),
    )
    method_predictions["hard_admin_mean"] = (
        _hard_admin_predict(rows, y, train, calibration),
        _hard_admin_predict(rows, y, train, holdout),
    )

    raster = matrices["raster"]
    admin = matrices["admin"]
    graph = matrices["graph_object"]
    method_predictions["raster_only_ridge"] = _ridge_predictions(
        np.column_stack((context, raster)),
        y,
        train,
        calibration,
        holdout,
        ridge,
    )
    method_predictions["raster_admin_soft_alignment_ridge"] = _ridge_predictions(
        np.column_stack((context, raster, admin)),
        y,
        train,
        calibration,
        holdout,
        ridge,
    )
    full = np.column_stack((context, raster, admin, graph))
    method_predictions[_CANDIDATE] = _ridge_predictions(full, y, train, calibration, holdout, ridge)
    method_predictions["multi_geometry_no_dynamic_context_ridge"] = _ridge_predictions(
        np.column_stack((base_context, raster, admin, graph)),
        y,
        train,
        calibration,
        holdout,
        ridge,
    )
    method_predictions["shuffled_admin_alignment_ridge"] = _shuffled_route_predictions(
        stable_blocks=(context, raster, graph),
        shuffled_block=admin,
        y=y,
        train=train,
        calibration=calibration,
        holdout=holdout,
        ridge=ridge,
        seed=negative_control_seed,
    )
    method_predictions["shuffled_graph_alignment_ridge"] = _shuffled_route_predictions(
        stable_blocks=(context, raster, admin),
        shuffled_block=graph,
        y=y,
        train=train,
        calibration=calibration,
        holdout=holdout,
        ridge=ridge,
        seed=negative_control_seed + 1000,
    )

    metrics = {
        method: _regression_metrics(y[holdout], predictions[1])
        for method, predictions in method_predictions.items()
    }
    candidate_calibration_errors = np.abs(y[calibration] - method_predictions[_CANDIDATE][0])
    candidate_holdout_errors = np.abs(y[holdout] - method_predictions[_CANDIDATE][1])
    radius = _conformal_radius(
        candidate_calibration_errors,
        confidence_level,
        target_scale=float(np.max(np.abs(y[calibration]))),
    )
    interval_scores = _interval_scores(
        candidate_holdout_errors,
        radius,
        alpha=1.0 - confidence_level,
    )
    coverage = float(np.mean(candidate_holdout_errors <= radius))
    split_calibration = {
        "method": "split_conformal_absolute_residual",
        "confidence_level": confidence_level,
        "calibration_count": len(calibration),
        "holdout_count": len(holdout),
        "interval_radius": _round(radius),
        "empirical_coverage": _round(coverage),
        "mean_interval_width": _round(2.0 * radius),
        "interval_score": _round(float(np.mean(interval_scores))),
    }
    leakage_audit = _leakage_audit(rows, split_name, indices)
    return (
        {
            "split_name": split_name,
            "train_count": len(train),
            "calibration_count": len(calibration),
            "holdout_count": len(holdout),
            "leakage_audit": leakage_audit,
            "method_metrics": metrics,
            "uncertainty_calibration": split_calibration,
        },
        {
            **split_calibration,
            "covered_count": int(np.sum(candidate_holdout_errors <= radius)),
            "interval_score_sum": float(np.sum(interval_scores)),
        },
    )


def _feature_matrix(
    rows: list[dict[str, Any]],
    route: str,
    feature_names: list[str],
) -> np.ndarray:
    return np.array(
        [[float(row[f"{route}_features"][name]) for name in feature_names] for row in rows],
        dtype=float,
    )


def _query_context_matrix(rows: list[dict[str, Any]]) -> np.ndarray:
    ordered_times = {
        time_id: index
        for index, time_id in enumerate(sorted({str(row["time_id"]) for row in rows}))
    }
    return np.array(
        [
            [
                float(row["x"]),
                float(row["y"]),
                float(ordered_times[str(row["time_id"])]),
            ]
            for row in rows
        ],
        dtype=float,
    )


def _ridge_predictions(
    matrix: np.ndarray,
    y: np.ndarray,
    train: list[int],
    calibration: list[int],
    holdout: list[int],
    ridge: float,
) -> tuple[np.ndarray, np.ndarray]:
    mean = np.mean(matrix[train], axis=0)
    std = np.std(matrix[train], axis=0)
    std = np.where(std > 1e-12, std, 1.0)
    train_x = (matrix[train] - mean) / std
    calibration_x = (matrix[calibration] - mean) / std
    holdout_x = (matrix[holdout] - mean) / std
    train_design = np.column_stack((np.ones(len(train)), train_x))
    penalty = np.eye(train_design.shape[1]) * ridge
    penalty[0, 0] = 0.0
    coefficients = (
        np.linalg.pinv(train_design.T @ train_design + penalty) @ train_design.T @ y[train]
    )
    return (
        np.column_stack((np.ones(len(calibration)), calibration_x)) @ coefficients,
        np.column_stack((np.ones(len(holdout)), holdout_x)) @ coefficients,
    )


def _shuffled_route_predictions(
    *,
    stable_blocks: tuple[np.ndarray, ...],
    shuffled_block: np.ndarray,
    y: np.ndarray,
    train: list[int],
    calibration: list[int],
    holdout: list[int],
    ridge: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    matrix = np.column_stack((*stable_blocks, shuffled_block))
    shuffled = matrix.copy()
    block_width = shuffled_block.shape[1]
    for offset, subset in enumerate((train, calibration, holdout)):
        rng = np.random.default_rng(seed + offset)
        permutation = rng.permutation(len(subset))
        shuffled[np.ix_(subset, range(matrix.shape[1] - block_width, matrix.shape[1]))] = (
            shuffled_block[np.array(subset)[permutation]]
        )
    return _ridge_predictions(shuffled, y, train, calibration, holdout, ridge)


def _idw_predict(
    rows: list[dict[str, Any]],
    y: np.ndarray,
    train: list[int],
    target_indices: list[int],
    neighbors: int,
) -> np.ndarray:
    predictions = []
    for target_index in target_indices:
        target = rows[target_index]
        distances = sorted(
            (
                (
                    (float(rows[index]["x"]) - float(target["x"])) ** 2
                    + (float(rows[index]["y"]) - float(target["y"])) ** 2
                )
                ** 0.5,
                index,
            )
            for index in train
        )[:neighbors]
        weights = np.array([1.0 / (distance + 1e-6) for distance, _ in distances])
        values = np.array([y[index] for _, index in distances])
        predictions.append(float(np.sum(weights * values) / np.sum(weights)))
    return np.array(predictions, dtype=float)


def _hard_admin_predict(
    rows: list[dict[str, Any]],
    y: np.ndarray,
    train: list[int],
    target_indices: list[int],
) -> np.ndarray:
    values_by_admin: dict[str, list[float]] = defaultdict(list)
    for index in train:
        values_by_admin[str(rows[index]["admin_unit_id"])].append(float(y[index]))
    global_mean = float(np.mean(y[train]))
    admin_means = {admin_id: float(np.mean(values)) for admin_id, values in values_by_admin.items()}
    return np.array(
        [
            admin_means.get(str(rows[index]["admin_unit_id"]), global_mean)
            for index in target_indices
        ],
        dtype=float,
    )


def _regression_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    errors = actual - predicted
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors**2)))
    denominator = float(np.sum((actual - np.mean(actual)) ** 2))
    r2 = 1.0 - float(np.sum(errors**2)) / denominator if denominator > 1e-12 else 0.0
    return {"mae": _round(mae), "rmse": _round(rmse), "r2": _round(r2)}


def _leakage_audit(
    rows: list[dict[str, Any]],
    split_name: str,
    indices: dict[str, list[int]],
) -> dict[str, Any]:
    groups = {
        partition: {_leakage_group_value(rows[index], split_name) for index in partition_indices}
        for partition, partition_indices in indices.items()
    }
    overlap_count = sum(
        len(groups[left].intersection(groups[right]))
        for left, right in (
            ("train", "calibration"),
            ("train", "holdout"),
            ("calibration", "holdout"),
        )
    )
    return {
        "group_dimension": split_name,
        "train_group_count": len(groups["train"]),
        "calibration_group_count": len(groups["calibration"]),
        "holdout_group_count": len(groups["holdout"]),
        "cross_partition_group_overlap_count": overlap_count,
        "passed": overlap_count == 0,
    }


def _leakage_group_value(row: dict[str, Any], split_name: str) -> float | str:
    if split_name == "spatial_block":
        return float(row["x"])
    if split_name == "whole_admin":
        return str(row["admin_unit_id"])
    return str(row["time_id"])


def _aggregate_method_metrics(
    split_results: dict[str, dict[str, Any]],
) -> dict[str, dict[str, float]]:
    methods = split_results[REQUIRED_SPLITS[0]]["method_metrics"]
    return {
        method: {
            f"mean_{metric}": _round(
                float(
                    np.mean(
                        [
                            split_results[split]["method_metrics"][method][metric]
                            for split in REQUIRED_SPLITS
                        ]
                    )
                )
            )
            for metric in ("mae", "rmse", "r2")
        }
        for method in methods
    }


def _dynamic_context_audit(
    *,
    dataset: dict[str, Any],
    rows: list[dict[str, Any]],
    split_results: dict[str, dict[str, Any]],
    minimum_time_groups_per_feature: float,
) -> dict[str, Any]:
    dynamic_context = dataset.get("dynamic_context") or {}
    feature_names = list(dynamic_context.get("feature_names") or [])
    if not feature_names:
        return {
            "declared": False,
            "feature_count": 0,
            "sample_support_gate_passed": True,
        }
    representative_by_time: dict[str, dict[str, Any]] = {}
    for row in rows:
        representative_by_time.setdefault(str(row["time_id"]), row)
    matrix = _feature_matrix(
        list(representative_by_time.values()),
        "dynamic_context",
        feature_names,
    )
    centered = matrix - np.mean(matrix, axis=0)
    train_time_groups = split_results["future_temporal"]["leakage_audit"]["train_group_count"]
    minimum_required = math.ceil(len(feature_names) * minimum_time_groups_per_feature)
    return {
        "declared": True,
        "feature_count": len(feature_names),
        "unique_time_group_count": len(representative_by_time),
        "future_split_train_time_group_count": train_time_groups,
        "centered_dynamic_feature_rank": int(np.linalg.matrix_rank(centered)),
        "minimum_time_groups_per_feature": minimum_time_groups_per_feature,
        "minimum_required_train_time_groups": minimum_required,
        "observed_train_time_groups_per_feature": _round(train_time_groups / len(feature_names)),
        "sample_support_gate_passed": train_time_groups >= minimum_required,
    }


def _aggregate_calibration(
    records: list[dict[str, Any]],
    *,
    confidence_level: float,
    coverage_tolerance: float,
) -> dict[str, Any]:
    holdout_count = sum(record["holdout_count"] for record in records)
    covered_count = sum(record["covered_count"] for record in records)
    interval_score_sum = sum(record["interval_score_sum"] for record in records)
    threshold = confidence_level - coverage_tolerance
    by_split = {
        split: {
            key: value
            for key, value in record.items()
            if key not in {"covered_count", "interval_score_sum"}
        }
        for split, record in zip(REQUIRED_SPLITS, records, strict=True)
    }
    return {
        "method": "split_conformal_absolute_residual",
        "confidence_level": confidence_level,
        "coverage_tolerance": coverage_tolerance,
        "minimum_coverage_threshold": _round(threshold),
        "calibration_count": sum(record["calibration_count"] for record in records),
        "holdout_count": holdout_count,
        "empirical_coverage": _round(covered_count / holdout_count),
        "mean_interval_score": _round(interval_score_sum / holdout_count),
        "by_split": by_split,
        "coverage_gate_passed": all(
            record["empirical_coverage"] >= threshold for record in records
        ),
    }


def _readiness_gates(
    *,
    dataset: dict[str, Any],
    split_results: dict[str, dict[str, Any]],
    aggregate_results: dict[str, dict[str, float]],
    calibration: dict[str, Any],
    minimum_relative_improvement: float,
    dynamic_context_audit: dict[str, Any],
) -> dict[str, bool]:
    candidate_mae = aggregate_results[_CANDIDATE]["mean_mae"]
    return {
        "three_native_geometry_routes_present": set(dataset["geometry_routes"])
        >= set(REQUIRED_GEOMETRY_ROUTES),
        "strict_holdout_leakage_audits_passed": all(
            split_results[split]["leakage_audit"]["passed"] is True for split in REQUIRED_SPLITS
        ),
        "candidate_beats_required_baselines_on_every_split": all(
            _beats_with_margin(
                split_results[split]["method_metrics"][_CANDIDATE]["mae"],
                split_results[split]["method_metrics"][baseline]["mae"],
                minimum_relative_improvement,
            )
            for split in REQUIRED_SPLITS
            for baseline in _REQUIRED_BASELINES
        ),
        "geometry_shuffle_negative_controls_passed": all(
            _beats_with_margin(
                candidate_mae,
                aggregate_results[control]["mean_mae"],
                minimum_relative_improvement,
            )
            for control in _NEGATIVE_CONTROLS
        ),
        "dynamic_context_ablation_gate_passed": not dataset.get("dynamic_context")
        or _beats_with_margin(
            candidate_mae,
            aggregate_results["multi_geometry_no_dynamic_context_ridge"]["mean_mae"],
            minimum_relative_improvement,
        ),
        "dynamic_context_sample_support_gate_passed": dynamic_context_audit[
            "sample_support_gate_passed"
        ]
        is True,
        "split_conformal_coverage_passed": calibration["coverage_gate_passed"] is True,
        "observed_holdout_evidence_present": dataset["source_evidence_kind"] == "observed_holdout"
        and bool(dataset["evidence_refs"]),
    }


def _beats_with_margin(candidate: float, comparator: float, margin: float) -> bool:
    if comparator <= 0.0:
        return candidate < comparator
    return candidate <= comparator * (1.0 - margin)


def _conformal_radius(
    errors: np.ndarray,
    confidence_level: float,
    *,
    target_scale: float,
) -> float:
    ordered = np.sort(errors)
    index = min(
        len(ordered) - 1,
        max(0, math.ceil((len(ordered) + 1) * confidence_level) - 1),
    )
    numerical_floor = 1e-9 * max(1.0, target_scale)
    return max(float(ordered[index]), numerical_floor)


def _interval_scores(errors: np.ndarray, radius: float, *, alpha: float) -> np.ndarray:
    width = 2.0 * radius
    return width + (2.0 / alpha) * np.maximum(errors - radius, 0.0)


def _claim_reason(*, ready: bool, evidence_kind: str) -> str:
    if ready:
        return (
            "Observed targets pass spatial-block, whole-admin and future-temporal holdout, "
            "required baseline, geometry-shuffle and conformal coverage gates."
        )
    if evidence_kind != "observed_holdout":
        return (
            "The evaluator can be exercised, but bounded reconstruction claims require "
            "an observed holdout dataset with evidence references."
        )
    return "One or more reconstruction, negative-control or calibration gates did not pass."


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _round(value: float) -> float:
    return round(float(value), 9)
