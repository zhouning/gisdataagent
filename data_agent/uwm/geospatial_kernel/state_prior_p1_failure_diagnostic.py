"""Fail-closed diagnostics for an unsuccessful P1 state-prior benchmark."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import numpy as np

from ..geospatial_state_prior_benchmark import (
    REQUIRED_GEOMETRY_ROUTES,
    REQUIRED_SPLITS,
    validate_uwm_geospatial_state_prior_benchmark,
    validate_uwm_geospatial_state_prior_dataset,
)

STATE_PRIOR_P1_FAILURE_DIAGNOSTIC_SCHEMA = (
    "uwm.geospatial_kernel.state_prior_p1_failure_diagnostic.v1"
)

_CANDIDATE = "multi_geometry_soft_alignment_ridge"
_PARTITIONS = ("train", "calibration", "holdout")
_CLAIM_BOUNDARY = {
    "max_claim_level": "not_for_claim",
    "scope": "posthoc_p1_failure_diagnosis_only",
    "opened_holdout_reuse": True,
    "feature_target_correlations_descriptive_only": True,
    "feature_selection_authorized": False,
    "threshold_tuning_authorized": False,
    "p1_readiness_change_authorized": False,
    "p2_admission_permitted": False,
    "scientific_result_claim": False,
    "transition_skill_improvement_claim": False,
    "policy_causal_effect_claim": False,
    "general_geospatial_world_model_validation_claim": False,
}
_PROHIBITED_USES = [
    "p1_gate_override",
    "p2_state_prior_admission",
    "posthoc_holdout_feature_selection",
    "posthoc_holdout_threshold_tuning",
    "scientific_advantage_claim",
    "transition_or_policy_claim",
]


def build_state_prior_p1_failure_diagnostic(
    *,
    diagnostic_id: str,
    created_at: str,
    dataset: Mapping[str, Any],
    benchmark: Mapping[str, Any],
) -> dict[str, Any]:
    """Describe a failed P1 result without changing any scientific gate."""

    if not _nonempty_string(diagnostic_id):
        raise ValueError("state_prior_p1_failure_diagnostic_id_required")
    _require_aware_timestamp(created_at)
    dataset_payload = copy.deepcopy(dict(dataset))
    benchmark_payload = copy.deepcopy(dict(benchmark))
    dataset_validation = validate_uwm_geospatial_state_prior_dataset(dataset_payload)
    if not dataset_validation["valid"]:
        raise ValueError(
            "state_prior_p1_failure_diagnostic_dataset_invalid:"
            + ";".join(dataset_validation["errors"])
        )
    benchmark_validation = validate_uwm_geospatial_state_prior_benchmark(benchmark_payload)
    if not benchmark_validation["valid"]:
        raise ValueError(
            "state_prior_p1_failure_diagnostic_benchmark_invalid:"
            + ";".join(benchmark_validation["errors"])
        )
    if benchmark_payload.get("dataset_id") != dataset_payload.get("dataset_id"):
        raise ValueError("state_prior_p1_failure_diagnostic_dataset_id_mismatch")
    if benchmark_payload.get("geospatial_state_prior_benchmark_ready") is not False:
        raise ValueError("state_prior_p1_failure_diagnostic_requires_failed_benchmark")

    rows = list(dataset_payload["rows"])
    split_indices = _strict_split_indices(rows)
    _verify_split_counts(split_indices, benchmark_payload)
    feature_diagnostics = _feature_diagnostics(rows, dataset_payload, split_indices)
    distribution_shift = _distribution_shift(rows, dataset_payload, split_indices)
    performance_deltas = _performance_deltas(benchmark_payload)
    coverage_deficits = _coverage_deficits(benchmark_payload)
    failed_gates = list(benchmark_payload.get("remaining_gates") or [])
    aggregate = benchmark_payload["aggregate_results"]
    required_baselines = list(benchmark_payload["benchmark_protocol"]["required_baselines"])
    strongest_baseline = min(
        required_baselines,
        key=lambda method: float(aggregate[method]["mean_mae"]),
    )
    candidate_mae = float(aggregate[_CANDIDATE]["mean_mae"])
    strongest_baseline_mae = float(aggregate[strongest_baseline]["mean_mae"])
    primary_failure_modes = [
        name
        for name, failed in (
            (
                "required_baseline_advantage_not_stable_across_splits",
                "candidate_beats_required_baselines_on_every_split" in failed_gates,
            ),
            (
                "geometry_negative_controls_not_consistently_worse",
                "geometry_shuffle_negative_controls_passed" in failed_gates,
            ),
            (
                "split_conformal_coverage_below_threshold",
                "split_conformal_coverage_passed" in failed_gates,
            ),
        )
        if failed
    ]
    diagnostic = {
        "schema": STATE_PRIOR_P1_FAILURE_DIAGNOSTIC_SCHEMA,
        "version": "0.1",
        "diagnostic_id": str(diagnostic_id),
        "created_at": str(created_at),
        "dataset_id": str(dataset_payload["dataset_id"]),
        "benchmark_id": str(benchmark_payload["benchmark_id"]),
        "input_artifact_sha256": {
            "dataset_sha256": _canonical_sha256(dataset_payload),
            "benchmark_sha256": _canonical_sha256(benchmark_payload),
        },
        "diagnostic_summary": {
            "benchmark_ready": False,
            "failed_readiness_gates": failed_gates,
            "candidate_method": _CANDIDATE,
            "candidate_mean_mae": _round(candidate_mae),
            "strongest_required_baseline": strongest_baseline,
            "strongest_required_baseline_mean_mae": _round(strongest_baseline_mae),
            "candidate_minus_strongest_baseline_mean_mae": _round(
                candidate_mae - strongest_baseline_mae
            ),
            "primary_failure_modes": primary_failure_modes,
        },
        "feature_diagnostics": feature_diagnostics,
        "distribution_shift": distribution_shift,
        "performance_deltas": performance_deltas,
        "conformal_coverage_deficits": coverage_deficits,
        "analysis_boundary": copy.deepcopy(_CLAIM_BOUNDARY),
        "prohibited_uses": list(_PROHIBITED_USES),
        "p1_benchmark_ready": False,
        "p2_admission_permitted": False,
        "supported_claim": "posthoc_p1_failure_diagnostic_only",
        "policy_causal_effect_claim": False,
        "action_conditioned_dynamics_claim": False,
        "general_geospatial_world_model_validation_claim": False,
    }
    diagnostic["diagnostic_sha256"] = compute_state_prior_p1_failure_diagnostic_sha256(diagnostic)
    validation = validate_state_prior_p1_failure_diagnostic(diagnostic)
    if not validation["valid"]:
        raise ValueError(
            "invalid_state_prior_p1_failure_diagnostic:" + ";".join(validation["errors"])
        )
    return diagnostic


def validate_state_prior_p1_failure_diagnostic(payload: Any) -> dict[str, Any]:
    """Validate the diagnostic contract and its non-promotion boundary."""

    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["p1_failure_diagnostic_must_be_dictionary"]}
    errors: list[str] = []
    expected_fields = {
        "schema",
        "version",
        "diagnostic_id",
        "created_at",
        "dataset_id",
        "benchmark_id",
        "input_artifact_sha256",
        "diagnostic_summary",
        "feature_diagnostics",
        "distribution_shift",
        "performance_deltas",
        "conformal_coverage_deficits",
        "analysis_boundary",
        "prohibited_uses",
        "p1_benchmark_ready",
        "p2_admission_permitted",
        "supported_claim",
        "policy_causal_effect_claim",
        "action_conditioned_dynamics_claim",
        "general_geospatial_world_model_validation_claim",
        "diagnostic_sha256",
    }
    if set(payload) != expected_fields:
        errors.append("p1_failure_diagnostic_field_set_mismatch")
    if payload.get("schema") != STATE_PRIOR_P1_FAILURE_DIAGNOSTIC_SCHEMA:
        errors.append("p1_failure_diagnostic_schema_mismatch")
    if payload.get("version") != "0.1":
        errors.append("p1_failure_diagnostic_version_mismatch")
    for field in ("diagnostic_id", "created_at", "dataset_id", "benchmark_id"):
        if not _nonempty_string(payload.get(field)):
            errors.append(f"p1_failure_diagnostic_{field}_required")
    if _parse_aware_timestamp(payload.get("created_at")) is None:
        errors.append("p1_failure_diagnostic_created_at_invalid")
    hashes = payload.get("input_artifact_sha256")
    if not isinstance(hashes, dict) or set(hashes) != {
        "dataset_sha256",
        "benchmark_sha256",
    }:
        errors.append("p1_failure_diagnostic_input_hashes_invalid")
    elif any(not _valid_sha256(value) for value in hashes.values()):
        errors.append("p1_failure_diagnostic_input_hash_invalid")
    summary = payload.get("diagnostic_summary")
    if not isinstance(summary, dict) or summary.get("benchmark_ready") is not False:
        errors.append("p1_failure_diagnostic_summary_must_preserve_failure")
    routes = payload.get("feature_diagnostics")
    if not isinstance(routes, dict) or tuple(routes) != REQUIRED_GEOMETRY_ROUTES:
        errors.append("p1_failure_diagnostic_geometry_routes_invalid")
    shift = payload.get("distribution_shift")
    if not isinstance(shift, dict) or tuple(shift.get("by_split") or {}) != REQUIRED_SPLITS:
        errors.append("p1_failure_diagnostic_distribution_splits_invalid")
    deltas = payload.get("performance_deltas")
    if (
        not isinstance(deltas, dict)
        or tuple(deltas.get("candidate_minus_required_baseline_mae_by_split") or {})
        != REQUIRED_SPLITS
    ):
        errors.append("p1_failure_diagnostic_performance_splits_invalid")
    coverage = payload.get("conformal_coverage_deficits")
    if not isinstance(coverage, dict) or tuple(coverage.get("by_split") or {}) != REQUIRED_SPLITS:
        errors.append("p1_failure_diagnostic_coverage_splits_invalid")
    if payload.get("analysis_boundary") != _CLAIM_BOUNDARY:
        errors.append("p1_failure_diagnostic_analysis_boundary_invalid")
    if payload.get("prohibited_uses") != _PROHIBITED_USES:
        errors.append("p1_failure_diagnostic_prohibited_uses_invalid")
    if payload.get("p1_benchmark_ready") is not False:
        errors.append("p1_failure_diagnostic_cannot_change_p1_readiness")
    if payload.get("p2_admission_permitted") is not False:
        errors.append("p1_failure_diagnostic_cannot_permit_p2_admission")
    if payload.get("supported_claim") != "posthoc_p1_failure_diagnostic_only":
        errors.append("p1_failure_diagnostic_supported_claim_invalid")
    for field in (
        "policy_causal_effect_claim",
        "action_conditioned_dynamics_claim",
        "general_geospatial_world_model_validation_claim",
    ):
        if payload.get(field) is not False:
            errors.append(f"p1_failure_diagnostic_{field}_must_be_false")
    digest = payload.get("diagnostic_sha256")
    if not _valid_sha256(digest):
        errors.append("p1_failure_diagnostic_sha256_invalid")
    elif digest != compute_state_prior_p1_failure_diagnostic_sha256(payload):
        errors.append("p1_failure_diagnostic_sha256_mismatch")
    return {"valid": not errors, "errors": errors}


def compute_state_prior_p1_failure_diagnostic_sha256(
    payload: Mapping[str, Any],
) -> str:
    """Compute the canonical digest for a P1 failure diagnostic."""

    values = copy.deepcopy(dict(payload))
    values.pop("diagnostic_sha256", None)
    return _canonical_sha256(values)


def _feature_diagnostics(
    rows: list[dict[str, Any]],
    dataset: Mapping[str, Any],
    split_indices: Mapping[str, Mapping[str, list[int]]],
) -> dict[str, Any]:
    target = np.array([float(row["target"]) for row in rows], dtype=float)
    diagnostics: dict[str, Any] = {}
    for route in REQUIRED_GEOMETRY_ROUTES:
        names = list(dataset["geometry_routes"][route]["feature_names"])
        matrix = _feature_matrix(rows, route, names)
        diagnostics[route] = {
            "feature_names": names,
            "row_count": len(rows),
            "overall_centered_rank": _centered_rank(matrix),
            "per_feature": {
                name: _feature_stats(matrix[:, index], target) for index, name in enumerate(names)
            },
            "by_split": {
                split_name: {
                    partition: _partition_feature_summary(matrix, names, indices[partition])
                    for partition in _PARTITIONS
                }
                for split_name, indices in split_indices.items()
            },
        }
    return diagnostics


def _distribution_shift(
    rows: list[dict[str, Any]],
    dataset: Mapping[str, Any],
    split_indices: Mapping[str, Mapping[str, list[int]]],
) -> dict[str, Any]:
    target = np.array([float(row["target"]) for row in rows], dtype=float)
    matrices: dict[str, tuple[list[str], np.ndarray]] = {}
    for route in REQUIRED_GEOMETRY_ROUTES:
        names = list(dataset["geometry_routes"][route]["feature_names"])
        matrices[route] = (names, _feature_matrix(rows, route, names))
    return {
        "reference_partition": "train",
        "standardization": "train_mean_and_population_standard_deviation",
        "zero_train_variance_shift_semantics": "null",
        "by_split": {
            split_name: {
                partition: {
                    "row_count": len(indices[partition]),
                    "target": _standardized_shift(target, indices["train"], indices[partition]),
                    "geometry_routes": {
                        route: {
                            "per_feature": {
                                name: _standardized_shift(
                                    matrix[:, feature_index],
                                    indices["train"],
                                    indices[partition],
                                )
                                for feature_index, name in enumerate(names)
                            },
                            "max_abs_standardized_mean_shift": _max_abs_shift(
                                matrix,
                                indices["train"],
                                indices[partition],
                            ),
                        }
                        for route, (names, matrix) in matrices.items()
                    },
                }
                for partition in ("calibration", "holdout")
            }
            for split_name, indices in split_indices.items()
        },
    }


def _performance_deltas(benchmark: Mapping[str, Any]) -> dict[str, Any]:
    protocol = benchmark["benchmark_protocol"]
    required_baselines = list(protocol["required_baselines"])
    negative_controls = list(protocol["negative_controls"])
    split_results = benchmark["split_results"]
    aggregate = benchmark["aggregate_results"]
    return {
        "candidate_method": _CANDIDATE,
        "delta_semantics": "candidate_mae_minus_comparator_mae_negative_is_favorable",
        "candidate_minus_required_baseline_mae_by_split": {
            split_name: {
                baseline: _round(
                    float(result["method_metrics"][_CANDIDATE]["mae"])
                    - float(result["method_metrics"][baseline]["mae"])
                )
                for baseline in required_baselines
            }
            for split_name, result in split_results.items()
        },
        "candidate_minus_negative_control_mae_by_split": {
            split_name: {
                control: _round(
                    float(result["method_metrics"][_CANDIDATE]["mae"])
                    - float(result["method_metrics"][control]["mae"])
                )
                for control in negative_controls
            }
            for split_name, result in split_results.items()
        },
        "aggregate_candidate_minus_required_baseline_mean_mae": {
            baseline: _round(
                float(aggregate[_CANDIDATE]["mean_mae"]) - float(aggregate[baseline]["mean_mae"])
            )
            for baseline in required_baselines
        },
        "aggregate_candidate_minus_negative_control_mean_mae": {
            control: _round(
                float(aggregate[_CANDIDATE]["mean_mae"]) - float(aggregate[control]["mean_mae"])
            )
            for control in negative_controls
        },
    }


def _coverage_deficits(benchmark: Mapping[str, Any]) -> dict[str, Any]:
    calibration = benchmark["uncertainty_calibration"]
    threshold = float(calibration["minimum_coverage_threshold"])
    empirical = float(calibration["empirical_coverage"])
    return {
        "minimum_coverage_threshold": _round(threshold),
        "deficit_semantics": "max_zero_threshold_minus_empirical_coverage",
        "aggregate": {
            "empirical_coverage": _round(empirical),
            "coverage_deficit": _round(max(0.0, threshold - empirical)),
        },
        "by_split": {
            split_name: {
                "empirical_coverage": _round(float(values["empirical_coverage"])),
                "coverage_deficit": _round(
                    max(0.0, threshold - float(values["empirical_coverage"]))
                ),
            }
            for split_name, values in calibration["by_split"].items()
        },
    }


def _strict_split_indices(
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, list[int]]]:
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
    train_groups = set(groups[:train_count])
    calibration_groups = set(groups[train_count : train_count + calibration_count])
    holdout_groups = set(groups[train_count + calibration_count :])
    return {
        "train": [index for index, key in enumerate(keys) if key in train_groups],
        "calibration": [index for index, key in enumerate(keys) if key in calibration_groups],
        "holdout": [index for index, key in enumerate(keys) if key in holdout_groups],
    }


def _verify_split_counts(
    indices: Mapping[str, Mapping[str, list[int]]], benchmark: Mapping[str, Any]
) -> None:
    for split_name in REQUIRED_SPLITS:
        result = benchmark["split_results"][split_name]
        for partition in _PARTITIONS:
            if len(indices[split_name][partition]) != int(result[f"{partition}_count"]):
                raise ValueError(
                    "state_prior_p1_failure_diagnostic_split_partition_mismatch:"
                    f"{split_name}:{partition}"
                )


def _feature_matrix(rows: list[dict[str, Any]], route: str, names: list[str]) -> np.ndarray:
    return np.array(
        [[float(row[f"{route}_features"][name]) for name in names] for row in rows],
        dtype=float,
    )


def _feature_stats(values: np.ndarray, target: np.ndarray) -> dict[str, Any]:
    return {
        "variance": _round(float(np.var(values))),
        "standard_deviation": _round(float(np.std(values))),
        "minimum": _round(float(np.min(values))),
        "maximum": _round(float(np.max(values))),
        "distinct_value_count": len(set(float(value) for value in values)),
        "target_pearson_correlation": _pearson(values, target),
        "correlation_interpretation": "descriptive_only_not_feature_evidence",
    }


def _partition_feature_summary(
    matrix: np.ndarray, names: list[str], indices: list[int]
) -> dict[str, Any]:
    partition = matrix[indices]
    variances = np.var(partition, axis=0)
    return {
        "row_count": len(indices),
        "centered_rank": _centered_rank(partition),
        "zero_variance_features": [
            name
            for name, variance in zip(names, variances, strict=True)
            if float(variance) <= 1e-12
        ],
        "per_feature_variance": {
            name: _round(float(variance)) for name, variance in zip(names, variances, strict=True)
        },
    }


def _centered_rank(matrix: np.ndarray) -> int:
    centered = matrix - np.mean(matrix, axis=0)
    return int(np.linalg.matrix_rank(centered, tol=1e-10))


def _pearson(left: np.ndarray, right: np.ndarray) -> float | None:
    if float(np.std(left)) <= 1e-12 or float(np.std(right)) <= 1e-12:
        return None
    return _round(float(np.corrcoef(left, right)[0, 1]))


def _standardized_shift(
    values: np.ndarray, train: list[int], comparison: list[int]
) -> dict[str, Any]:
    train_values = values[train]
    comparison_values = values[comparison]
    train_mean = float(np.mean(train_values))
    train_std = float(np.std(train_values))
    comparison_mean = float(np.mean(comparison_values))
    return {
        "train_mean": _round(train_mean),
        "train_standard_deviation": _round(train_std),
        "partition_mean": _round(comparison_mean),
        "standardized_mean_shift": (
            _round((comparison_mean - train_mean) / train_std) if train_std > 1e-12 else None
        ),
    }


def _max_abs_shift(matrix: np.ndarray, train: list[int], comparison: list[int]) -> float | None:
    shifts = [
        _standardized_shift(matrix[:, index], train, comparison)["standardized_mean_shift"]
        for index in range(matrix.shape[1])
    ]
    finite = [abs(float(value)) for value in shifts if value is not None]
    return _round(max(finite)) if finite else None


def _round(value: float) -> float:
    return round(float(value), 9)


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _parse_aware_timestamp(value: Any) -> datetime | None:
    if not _nonempty_string(value):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _require_aware_timestamp(value: Any) -> datetime:
    parsed = _parse_aware_timestamp(value)
    if parsed is None:
        raise ValueError("state_prior_p1_failure_diagnostic_created_at_invalid")
    if not math.isfinite(parsed.timestamp()):
        raise ValueError("state_prior_p1_failure_diagnostic_created_at_invalid")
    return parsed
