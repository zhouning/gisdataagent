"""Quality audit for the full-admin service accessibility surface."""

from __future__ import annotations

from statistics import mean
from typing import Any

import numpy as np


UWM_FULL_ADMIN_SERVICE_SURFACE_QUALITY_AUDIT_SCHEMA = (
    "uwm.full_admin_service_surface_quality_audit.v1"
)

NON_ESSENTIAL_SERVICE_COLUMNS = [
    "food_retail_count",
    "finance_count",
    "mobility_transport_count",
    "civic_public_count",
    "recreation_count",
    "lodging_count",
    "other_service_count",
]


def build_full_admin_service_surface_quality_audit(
    *,
    service_surface: dict[str, Any],
    audit_id: str,
    created_at: str,
    source_surface_path: str = "",
) -> dict[str, Any]:
    """Evaluate proxy coherence of the full service surface without policy claims."""

    rows = [_audit_row(row) for row in service_surface.get("admin_service_rows") or []]
    endpoints = [
        _evaluate_endpoint(
            rows,
            endpoint_id="essential_service_count_proxy",
            target="essential_service_count",
            model_features=["non_essential_service_count"],
            baselines={
                "city_mean": None,
                "road_context_only": [
                    "road_segment_count",
                    "road_length_km",
                    "mean_road_speed_kmh",
                ],
            },
            model_name="non_essential_poi_context_standardized_ridge",
        ),
        _evaluate_endpoint(
            rows,
            endpoint_id="estimated_nearest_essential_travel_time_proxy",
            target="estimated_nearest_essential_travel_time_min",
            model_features=[
                "non_essential_service_count",
                "road_segment_count",
                "road_length_km",
                "mean_road_speed_kmh",
            ],
            baselines={
                "city_mean": None,
                "road_context_only": [
                    "road_segment_count",
                    "road_length_km",
                    "mean_road_speed_kmh",
                ],
                "non_essential_poi_only": ["non_essential_service_count"],
            },
            model_name="non_essential_poi_plus_road_context_standardized_ridge",
        ),
    ]
    ready_endpoint_count = sum(
        endpoint.get("beats_best_baseline") is True
        and endpoint.get("target_rotation_negative_control_passed") is True
        for endpoint in endpoints
    )
    ready = bool(endpoints) and ready_endpoint_count == len(endpoints)
    supported_claim = (
        "full_admin_service_surface_proxy_quality_beats_static_and_negative_controls"
        if ready
        else "no_full_admin_service_surface_proxy_quality_claim_supported"
    )
    return {
        "schema": UWM_FULL_ADMIN_SERVICE_SURFACE_QUALITY_AUDIT_SCHEMA,
        "version": "0.1",
        "audit_id": audit_id,
        "created_at": created_at,
        "source_surface_id": service_surface.get("surface_id"),
        "source_surface_path": source_surface_path,
        "source_surface_schema": service_surface.get("schema"),
        "experiment_scope": service_surface.get("experiment_scope"),
        "source_feature_counts": service_surface.get("source_feature_counts") or {},
        "coverage": service_surface.get("coverage") or {},
        "admin_unit_count": len(rows),
        "endpoint_count": len(endpoints),
        "ready_endpoint_count": ready_endpoint_count,
        "endpoint_evaluations": endpoints,
        "full_admin_service_surface_quality_audit_ready": ready,
        "supported_claim": supported_claim,
        "claim_boundary": {
            "max_claim_level": "bounded_support" if ready else "not_for_claim",
            "reason": (
                "Quality audit uses full-admin proxy surface leave-one-admin-out "
                "tests and target-rotation negative controls; it does not validate "
                "observed trips, authoritative service inventory, or policy outcomes."
            ),
        },
        "observed_trip_time_claim": False,
        "authoritative_service_inventory_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "limitations": [
            "service_targets_are_poi_road_proxy_outputs_not_observed_trip_times",
            "poi_category_coherence_is_not_authoritative_service_inventory_validation",
            "target_rotation_negative_control_is_diagnostic_not_policy_validation",
            "not_observed_policy_outcome",
        ],
    }


def validate_full_admin_service_surface_quality_audit(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Validate the full-admin service surface quality audit contract."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != UWM_FULL_ADMIN_SERVICE_SURFACE_QUALITY_AUDIT_SCHEMA:
        errors.append(
            f"schema must be {UWM_FULL_ADMIN_SERVICE_SURFACE_QUALITY_AUDIT_SCHEMA}"
        )
    for key in [
        "audit_id",
        "source_surface_schema",
        "admin_unit_count",
        "endpoint_count",
        "ready_endpoint_count",
        "endpoint_evaluations",
        "full_admin_service_surface_quality_audit_ready",
        "supported_claim",
        "claim_boundary",
        "limitations",
    ]:
        if key not in payload:
            errors.append(f"{key} is required")
    endpoints = payload.get("endpoint_evaluations") or []
    if isinstance(endpoints, list):
        if _int(payload.get("endpoint_count")) != len(endpoints):
            errors.append("endpoint_count must equal endpoint_evaluations length")
        for endpoint in endpoints:
            for key in [
                "endpoint_id",
                "target",
                "holdout_admin_unit_count",
                "model_mae",
                "best_baseline_mae",
                "target_rotation_negative_control_mae",
                "beats_best_baseline",
                "target_rotation_negative_control_passed",
            ]:
                if key not in endpoint:
                    errors.append(f"endpoint_evaluations[].{key} is required")
                    break
    if payload.get("observed_trip_time_claim") is not False:
        errors.append("observed_trip_time_claim must be false")
    if payload.get("authoritative_service_inventory_claim") is not False:
        errors.append("authoritative_service_inventory_claim must be false")
    if payload.get("observed_policy_outcome_superiority_claim") is not False:
        errors.append("observed_policy_outcome_superiority_claim must be false")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim must be false")
    return {"valid": not errors, "errors": errors}


def _audit_row(row: dict[str, Any]) -> dict[str, float | str]:
    non_essential = sum(_float(row.get(column)) for column in NON_ESSENTIAL_SERVICE_COLUMNS)
    return {
        "admin_unit_id": str(row.get("admin_unit_id") or ""),
        "essential_service_count": _float(row.get("essential_service_count")),
        "estimated_nearest_essential_travel_time_min": _float(
            row.get("estimated_nearest_essential_travel_time_min")
        ),
        "non_essential_service_count": non_essential,
        "road_segment_count": _float(row.get("road_segment_count")),
        "road_length_km": _float(row.get("road_length_km")),
        "mean_road_speed_kmh": _float(row.get("mean_road_speed_kmh")),
    }


def _evaluate_endpoint(
    rows: list[dict[str, float | str]],
    *,
    endpoint_id: str,
    target: str,
    model_features: list[str],
    baselines: dict[str, list[str] | None],
    model_name: str,
) -> dict[str, Any]:
    model_errors = _loo_ridge_abs_errors(rows, target=target, columns=model_features)
    baseline_errors = {
        baseline_id: (
            _loo_city_mean_abs_errors(rows, target=target)
            if columns is None
            else _loo_ridge_abs_errors(rows, target=target, columns=columns)
        )
        for baseline_id, columns in baselines.items()
    }
    baseline_maes = {
        key: round(_mean(errors), 6) for key, errors in baseline_errors.items()
    }
    best_baseline_id = min(baseline_maes, key=baseline_maes.get)
    best_baseline_errors = baseline_errors[best_baseline_id]
    model_mae = _mean(model_errors)
    best_baseline_mae = baseline_maes[best_baseline_id]
    negative_errors = _target_rotation_negative_control_errors(
        rows,
        target=target,
        columns=model_features,
    )
    negative_mae = _mean(negative_errors)
    return {
        "endpoint_id": endpoint_id,
        "target": target,
        "model": model_name,
        "model_features": model_features,
        "ridge": 1.0,
        "holdout_admin_unit_count": len(rows),
        "model_mae": round(model_mae, 6),
        "baseline_maes": baseline_maes,
        "best_baseline_id": best_baseline_id,
        "best_baseline_mae": round(best_baseline_mae, 6),
        "mae_reduction_vs_best_baseline": round(best_baseline_mae - model_mae, 6),
        "paired_win_count_vs_best_baseline": int(sum(
            model < baseline
            for model, baseline in zip(model_errors, best_baseline_errors)
        )),
        "paired_loss_count_vs_best_baseline": int(sum(
            model > baseline
            for model, baseline in zip(model_errors, best_baseline_errors)
        )),
        "target_rotation_negative_control_mae": round(negative_mae, 6),
        "target_rotation_negative_control_margin": round(negative_mae - model_mae, 6),
        "beats_best_baseline": model_mae < best_baseline_mae,
        "target_rotation_negative_control_passed": (
            negative_mae > model_mae and negative_mae > best_baseline_mae
        ),
    }


def _loo_ridge_abs_errors(
    rows: list[dict[str, float | str]],
    *,
    target: str,
    columns: list[str],
    target_values: np.ndarray | None = None,
    ridge: float = 1.0,
) -> list[float]:
    if len(rows) < 3:
        return []
    x = np.array([[_float(row.get(column)) for column in columns] for row in rows])
    y = np.array([_float(row.get(target)) for row in rows])
    train_y_values = target_values if target_values is not None else y
    errors = []
    for index, observed in enumerate(y):
        mask = np.ones(len(y), dtype=bool)
        mask[index] = False
        prediction = _standardized_ridge_predict(
            x[mask],
            train_y_values[mask],
            x[index],
            ridge=ridge,
        )
        errors.append(abs(prediction - observed))
    return errors


def _loo_city_mean_abs_errors(
    rows: list[dict[str, float | str]],
    *,
    target: str,
) -> list[float]:
    values = np.array([_float(row.get(target)) for row in rows])
    if len(values) < 3:
        return []
    errors = []
    total = float(values.sum())
    for value in values:
        prediction = (total - value) / (len(values) - 1)
        errors.append(abs(prediction - value))
    return errors


def _target_rotation_negative_control_errors(
    rows: list[dict[str, float | str]],
    *,
    target: str,
    columns: list[str],
) -> list[float]:
    target_values = np.array([_float(row.get(target)) for row in rows])
    if len(target_values) < 3:
        return []
    rotated = np.roll(target_values, max(1, len(target_values) // 3))
    return _loo_ridge_abs_errors(
        rows,
        target=target,
        columns=columns,
        target_values=rotated,
    )


def _standardized_ridge_predict(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_test: np.ndarray,
    *,
    ridge: float,
) -> float:
    feature_mean = x_train.mean(axis=0)
    feature_scale = x_train.std(axis=0)
    feature_scale[feature_scale == 0.0] = 1.0
    design = np.column_stack(
        [np.ones(len(y_train)), (x_train - feature_mean) / feature_scale]
    )
    penalty = ridge * np.eye(design.shape[1])
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(
        design.T @ design + penalty,
        design.T @ y_train,
    )
    test = np.concatenate(
        [
            np.array([1.0]),
            (x_test - feature_mean) / feature_scale,
        ]
    )
    return float(test @ coefficients)


def _mean(values: list[float]) -> float:
    return float(mean(values)) if values else 0.0


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
