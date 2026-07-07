"""Final endpoint suite for claim-safe UWM livability analysis."""

from __future__ import annotations

from typing import Any

import numpy as np


UWM_LIVABILITY_ENDPOINT_SUITE_SCHEMA = "uwm.livability_endpoint_suite.v1"


def build_uwm_livability_endpoint_suite(
    *,
    suite_id: str,
    created_at: str,
    multisource_livability_scene: dict[str, Any],
    building_floor_morphology: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate final livability endpoints against traditional baselines."""

    building_floor_morphology = building_floor_morphology or {}
    scene_rows = multisource_livability_scene.get("admin_unit_states") or []
    building_rows_by_key = _building_morphology_by_key(building_floor_morphology)
    rows, matched_building_units = _state_rows_with_building_morphology(
        scene_rows,
        building_rows_by_key,
    )
    building_floor_projected = (
        bool(rows)
        and matched_building_units == len(rows)
        and building_floor_morphology.get("supported_claim")
        == "building_floor_25d_morphology_service_endpoint_head_beats_2d_baselines"
        and building_floor_morphology.get("true_3d_claim") is False
    )
    endpoint_evaluations = [
        _evaluate_endpoint(rows, spec)
        for spec in _endpoint_specs(
            building_floor_projected=building_floor_projected
        )
    ]
    ready_endpoint_count = sum(
        endpoint.get("beats_traditional_baselines") is True
        for endpoint in endpoint_evaluations
    )
    relative_reductions = [
        _float(endpoint.get("relative_mae_reduction_vs_best_traditional"))
        for endpoint in endpoint_evaluations
        if endpoint.get("beats_traditional_baselines") is True
    ]
    all_endpoints_ready = (
        len(endpoint_evaluations) >= 3
        and ready_endpoint_count == len(endpoint_evaluations)
        and bool(relative_reductions)
    )
    supported_claim = (
        "uwm_final_livability_endpoint_suite_beats_traditional_baselines"
        if all_endpoints_ready
        else "no_final_livability_endpoint_suite_superiority_claim_supported"
    )
    return {
        "schema": UWM_LIVABILITY_ENDPOINT_SUITE_SCHEMA,
        "suite_id": suite_id,
        "created_at": created_at,
        "source_scene_id": multisource_livability_scene.get("scene_id"),
        "admin_unit_count": len(rows),
        "source_modalities_used": [
            "multisource_livability_scene",
            *(
                ["building_floor_25d_morphology"]
                if building_floor_projected
                else []
            ),
        ],
        "building_floor_morphology_projected": building_floor_projected,
        "building_floor_matched_admin_units": matched_building_units,
        "endpoint_count": len(endpoint_evaluations),
        "ready_endpoint_count": ready_endpoint_count,
        "endpoint_domains": sorted(
            {str(endpoint.get("domain")) for endpoint in endpoint_evaluations}
        ),
        "endpoint_evaluations": endpoint_evaluations,
        "all_endpoints_beat_traditional_baselines": all_endpoints_ready,
        "mean_relative_mae_reduction_vs_best_traditional": round(
            _mean(relative_reductions),
            6,
        ),
        "min_relative_mae_reduction_vs_best_traditional": round(
            min(relative_reductions) if relative_reductions else 0.0,
            6,
        ),
        "supported_claim": supported_claim,
        "claim_boundary": {
            "max_claim_level": "bounded_support" if all_endpoints_ready else "not_for_claim",
            "reason": (
                "final endpoint suite uses leave-one-admin-out validation on real prepared "
                "multisource scene endpoints; it is not an observed policy outcome test"
            ),
        },
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def _endpoint_specs(*, building_floor_projected: bool = False) -> list[dict[str, Any]]:
    service_point_spec = {
        "endpoint_id": "service_point_accessibility",
        "domain": "service_accessibility",
        "target": "service_point_count",
        "uwm_model": "osm_road_segment_count_standardized_ridge",
        "uwm_features": ["osm_road_segment_count"],
        "ridge": 1.0,
        "traditional_baselines": [
            {
                "baseline_id": "ghsl_population_proxy",
                "features": ["ghsl_population_proxy_sum"],
            },
            {
                "baseline_id": "ghsl_built_surface_proxy",
                "features": ["ghsl_built_surface_proxy_sum"],
            },
            {"baseline_id": "city_mean", "features": None},
        ],
    }
    essential_service_spec = {
        "endpoint_id": "essential_service_accessibility",
        "domain": "service_accessibility",
        "target": "essential_service_count",
        "uwm_model": "osm_road_length_degrees_proxy_standardized_ridge",
        "uwm_features": ["osm_road_length_degrees_proxy"],
        "ridge": 1.0,
        "traditional_baselines": [
            {
                "baseline_id": "ghsl_population_proxy",
                "features": ["ghsl_population_proxy_sum"],
            },
            {
                "baseline_id": "ghsl_built_surface_proxy",
                "features": ["ghsl_built_surface_proxy_sum"],
            },
            {"baseline_id": "city_mean", "features": None},
        ],
    }
    if building_floor_projected:
        service_point_spec = {
            **service_point_spec,
            "uwm_model": "osm_road_floor_25d_standardized_ridge",
            "uwm_features": [
                "osm_road_segment_count",
                "osm_road_length_degrees_proxy",
                "building_max_floor",
            ],
        }
        essential_service_spec = {
            **essential_service_spec,
            "uwm_model": "osm_road_length_floor_25d_standardized_ridge",
            "uwm_features": [
                "osm_road_length_degrees_proxy",
                "building_max_floor",
            ],
        }
    return [
        {
            "endpoint_id": "air_quality_pm25",
            "domain": "air_quality",
            "target": "tap_scene_pm25_mean_ugm3",
            "uwm_model": "chap_cams_standardized_ridge",
            "uwm_features": ["chap_pm25_ugm3", "gee_cams_pm25_ugm3"],
            "ridge": 0.1,
            "traditional_baselines": [
                {
                    "baseline_id": "chap_monthly_anchor_ridge",
                    "features": ["chap_pm25_ugm3"],
                },
                {
                    "baseline_id": "gee_cams_pm25_ridge",
                    "features": ["gee_cams_pm25_ugm3"],
                },
                {"baseline_id": "city_mean", "features": None},
            ],
        },
        service_point_spec,
        essential_service_spec,
    ]


def _state_rows_with_building_morphology(
    scene_rows: list[dict[str, Any]],
    building_rows_by_key: dict[tuple[str, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    rows = []
    matched = 0
    for scene_row in scene_rows:
        state_vector = dict(scene_row.get("state_vector") or {})
        building_row = building_rows_by_key.get(_county_township_key(scene_row))
        if building_row is not None:
            state_vector.update(
                {
                    "building_count": _float(building_row.get("building_count")),
                    "building_floor_count_sum": _float(
                        building_row.get("floor_count_sum")
                    ),
                    "building_average_floor": _float(
                        building_row.get("average_floor")
                    ),
                    "building_max_floor": _float(building_row.get("max_floor")),
                }
            )
            matched += 1
        rows.append(state_vector)
    return rows, matched


def _building_morphology_by_key(
    building_floor_morphology: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        _county_township_key(row): row
        for row in building_floor_morphology.get("admin_morphology_rows") or []
    }


def _county_township_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("county") or ""), str(row.get("township") or ""))


def _evaluate_endpoint(
    rows: list[dict[str, Any]],
    spec: dict[str, Any],
) -> dict[str, Any]:
    target = str(spec["target"])
    ridge = _float(spec.get("ridge"), default=1.0)
    uwm_errors = _loo_ridge_abs_errors(
        rows,
        target=target,
        columns=list(spec["uwm_features"]),
        ridge=ridge,
    )
    baseline_errors = {}
    baseline_maes = {}
    for baseline in spec["traditional_baselines"]:
        baseline_id = str(baseline["baseline_id"])
        features = baseline.get("features")
        errors = (
            _loo_city_mean_abs_errors(rows, target=target)
            if features is None
            else _loo_ridge_abs_errors(
                rows,
                target=target,
                columns=list(features),
                ridge=ridge,
            )
        )
        baseline_errors[baseline_id] = errors
        baseline_maes[baseline_id] = _mean(errors)

    uwm_mae = _mean(uwm_errors)
    rounded_baseline_maes = {
        key: round(value, 6) for key, value in baseline_maes.items()
    }
    best_baseline_id = min(rounded_baseline_maes, key=rounded_baseline_maes.get)
    best_baseline_mae = rounded_baseline_maes[best_baseline_id]
    rounded_uwm_mae = round(uwm_mae, 6)
    reduction = best_baseline_mae - rounded_uwm_mae
    best_baseline_errors = baseline_errors[best_baseline_id]
    return {
        "endpoint_id": spec["endpoint_id"],
        "domain": spec["domain"],
        "target": target,
        "uwm_model": spec["uwm_model"],
        "uwm_features": list(spec["uwm_features"]),
        "ridge": ridge,
        "holdout_admin_unit_count": len(rows),
        "target_range": round(
            max(_float(row.get(target)) for row in rows)
            - min(_float(row.get(target)) for row in rows),
            6,
        )
        if rows
        else 0.0,
        "uwm_mae": rounded_uwm_mae,
        "traditional_baseline_maes": rounded_baseline_maes,
        "best_traditional_baseline": best_baseline_id,
        "best_traditional_baseline_mae": round(best_baseline_mae, 6),
        "mae_reduction_vs_best_traditional": round(reduction, 6),
        "relative_mae_reduction_vs_best_traditional": round(
            reduction / best_baseline_mae if best_baseline_mae else 0.0,
            6,
        ),
        "paired_win_count_vs_best_traditional": sum(
            uwm < baseline
            for uwm, baseline in zip(uwm_errors, best_baseline_errors)
        ),
        "paired_loss_count_vs_best_traditional": sum(
            uwm > baseline
            for uwm, baseline in zip(uwm_errors, best_baseline_errors)
        ),
        "beats_traditional_baselines": uwm_mae < best_baseline_mae,
        "policy_outcome_claim": False,
    }


def _loo_ridge_abs_errors(
    rows: list[dict[str, Any]],
    *,
    target: str,
    columns: list[str],
    ridge: float,
) -> list[float]:
    errors = []
    for index, test in enumerate(rows):
        train = [row for item, row in enumerate(rows) if item != index]
        prediction = _standardized_ridge_predict(
            train,
            test,
            target=target,
            columns=columns,
            ridge=ridge,
        )
        errors.append(abs(prediction - _float(test.get(target))))
    return errors


def _loo_city_mean_abs_errors(
    rows: list[dict[str, Any]],
    *,
    target: str,
) -> list[float]:
    errors = []
    for index, test in enumerate(rows):
        train = [row for item, row in enumerate(rows) if item != index]
        prediction = _mean([_float(row.get(target)) for row in train])
        errors.append(abs(prediction - _float(test.get(target))))
    return errors


def _standardized_ridge_predict(
    train: list[dict[str, Any]],
    test: dict[str, Any],
    *,
    target: str,
    columns: list[str],
    ridge: float,
) -> float:
    x_train = np.array(
        [[_float(record.get(column)) for column in columns] for record in train]
    )
    y_train = np.array([_float(record.get(target)) for record in train])
    x_test = np.array([_float(test.get(column)) for column in columns])
    mean = x_train.mean(axis=0)
    scale = x_train.std(axis=0)
    scale[scale == 0.0] = 1.0
    design = np.column_stack([np.ones(len(train)), (x_train - mean) / scale])
    penalty = ridge * np.eye(design.shape[1])
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ y_train)
    return float(np.r_[1.0, (x_test - mean) / scale] @ coefficients)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _float(value: Any, default: float = 0.0) -> float:
    if value in {None, ""}:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
