"""Scene-aligned gridded air-quality holdout for UWM.

This benchmark samples TAP 1 km daily PM2.5 at the CHAP 2024-07 admin
representative points. It is scene-aligned gridded evidence, not a station
calibrated observation and not a policy-outcome benchmark.
"""

from __future__ import annotations

import csv
import io
import math
import re
import zipfile
from collections import defaultdict
from math import comb
from pathlib import Path
from statistics import fmean
from typing import Any


UWM_SCENE_ALIGNED_GRIDDED_AIR_QUALITY_HOLDOUT_SCHEMA = (
    "uwm.scene_aligned_gridded_air_quality_holdout.v1"
)
CHAP_PM25_DATASET_ID = "chap_pm25_monthly_1km_2024_07_proxy"
TAP_PM25_DATASET_ID = "tap_pm25_observed_gridded_chongqing_2018_2024"
UWM_STATE_UPDATE_METHODS = [
    "online_persistence_state_update",
    "adaptive_online_state_update",
    "spatial_scene_mean_message",
    "spatial_idw_message_reconstruction",
]
TRADITIONAL_STATIC_BASELINES = [
    "static_train_mean",
    "static_last_train_observation",
    "scene_static_train_mean",
]
SCENE_ALIGNED_GRIDDED_SPATIAL_MESSAGE_CLAIM = (
    "scene_aligned_gridded_pm25_spatial_message_advantage_over_static_baselines"
)
SCENE_ALIGNED_GRIDDED_CONFORMAL_UNCERTAINTY_CLAIM = (
    "scene_aligned_gridded_pm25_conformal_uncertainty_advantage_over_static_baseline"
)


def build_uwm_scene_aligned_gridded_air_quality_holdout(
    *,
    chap_admin_proxy: dict[str, Any],
    tap_root: str | Path,
    benchmark_id: str,
    created_at: str,
    train_days: int = 3,
    period_dir_name: str = "chongqing_pm25_2024_07_01_07",
) -> dict[str, Any]:
    """Build a scene-aligned admin-point TAP temporal holdout."""

    if train_days < 1:
        raise ValueError("train_days must be positive")
    if chap_admin_proxy.get("schema") != "uwm.chap_pm25_admin_proxy.v1":
        raise ValueError("chap_admin_proxy schema must be uwm.chap_pm25_admin_proxy.v1")
    root = Path(tap_root)
    downloaded = root / period_dir_name / "downloaded"
    if not downloaded.exists():
        raise FileNotFoundError(f"TAP downloaded directory not found: {downloaded}")

    chap_points = _chap_points(chap_admin_proxy)
    if not chap_points:
        raise ValueError("CHAP admin proxy has no valid admin_pm25_rows")
    nearest = _nearest_tap_grids(downloaded, chap_points)
    sampled_series = _sample_tap_daily_series(downloaded, chap_points, nearest)
    scene_train_mean = _scene_train_mean(sampled_series, train_days)
    series_results = [
        _benchmark_admin_series(
            series,
            sampled_series,
            series_index=index,
            train_days=train_days,
            scene_train_mean=scene_train_mean,
        )
        for index, series in enumerate(sampled_series)
        if len(series.get("daily_pm25") or []) > train_days
    ]
    if not series_results:
        raise ValueError("no benchmarkable scene-aligned TAP admin series found")

    overall = _overall_results(series_results)
    negative_control = _spatial_message_negative_control(series_results)
    uncertainty = _uncertainty_calibration(
        series_results,
        train_days=train_days,
        best_uwm_method=overall["best_uwm_method"],
        static_baseline_method=overall["best_static_baseline_method"],
        confidence_level=0.9,
    )
    ready = (
        overall["beats_all_traditional_static_baselines"] is True
        and negative_control["spatial_shuffle_negative_control_passed"] is True
    )
    return {
        "schema": UWM_SCENE_ALIGNED_GRIDDED_AIR_QUALITY_HOLDOUT_SCHEMA,
        "version": "0.1",
        "benchmark_id": benchmark_id,
        "created_at": created_at,
        "source_dataset_ids": [CHAP_PM25_DATASET_ID, TAP_PM25_DATASET_ID],
        "source_chap_schema": chap_admin_proxy.get("schema"),
        "tap_period_id": period_dir_name,
        "scene_period": {
            "start_date": "2024-07-01",
            "end_date": "2024-07-07",
        },
        "train_days": train_days,
        "traditional_static_baseline_suite": TRADITIONAL_STATIC_BASELINES,
        "uwm_state_update_suite": UWM_STATE_UPDATE_METHODS,
        "state_update_parameters": {"adaptive_online_state_update_alpha": 0.7},
        "admin_unit_count": len(series_results),
        "holdout_count": sum(row["holdout_count"] for row in series_results),
        "tap_sampling_summary": _tap_sampling_summary(sampled_series),
        "chap_anchor_summary": _chap_anchor_summary(chap_admin_proxy, sampled_series),
        "series_results": series_results,
        "overall_results": overall,
        "overall_sign_tests": _overall_sign_tests(series_results, overall["best_uwm_method"]),
        "spatial_message_negative_control_summary": negative_control,
        "uncertainty_calibration": uncertainty,
        "scene_aligned_gridded_air_quality_holdout_ready": ready,
        "scene_aligned_station_calibrated_air_quality_holdout_ready": False,
        "supported_claim": SCENE_ALIGNED_GRIDDED_SPATIAL_MESSAGE_CLAIM
        if ready
        else "no_scene_aligned_gridded_air_quality_advantage_claim_supported",
        "claim_boundary": {
            "max_claim_level": "bounded_support" if ready else "not_for_claim",
            "reason": (
                "TAP daily PM2.5 sampled at CHAP admin representative points supports "
                "scene-aligned gridded temporal state-prediction comparison only; it is "
                "not station-calibrated and not an observed policy-outcome benchmark."
            ),
        },
        "limitations": [
            "tap_gridded_product_not_station_observation",
            "chap_monthly_anchor_not_station_observation",
            "scene_aligned_gridded_holdout_not_station_calibrated",
            "not_policy_intervention_outcome",
            "short_seven_day_scene_window",
        ],
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def validate_uwm_scene_aligned_gridded_air_quality_holdout(
    payload: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != UWM_SCENE_ALIGNED_GRIDDED_AIR_QUALITY_HOLDOUT_SCHEMA:
        errors.append(
            f"schema must be {UWM_SCENE_ALIGNED_GRIDDED_AIR_QUALITY_HOLDOUT_SCHEMA}"
        )
    for key in [
        "benchmark_id",
        "source_dataset_ids",
        "series_results",
        "overall_results",
        "claim_boundary",
        "limitations",
    ]:
        if key not in payload:
            errors.append(f"{key} is required")
    if payload.get("observed_policy_outcome_superiority_claim") is not False:
        errors.append("observed_policy_outcome_superiority_claim must be false")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim must be false")
    if payload.get("scene_aligned_station_calibrated_air_quality_holdout_ready") is not False:
        errors.append(
            "scene_aligned_station_calibrated_air_quality_holdout_ready must stay false"
        )
    limitations = payload.get("limitations") or []
    if "not_policy_intervention_outcome" not in limitations:
        errors.append("limitations must include not_policy_intervention_outcome")
    claim = payload.get("claim_boundary") or {}
    if not isinstance(claim, dict) or not claim.get("max_claim_level"):
        errors.append("claim_boundary.max_claim_level is required")
    ready = payload.get("scene_aligned_gridded_air_quality_holdout_ready") is True
    if ready and claim.get("max_claim_level") != "bounded_support":
        errors.append("ready holdout must have bounded_support claim level")
    return {"valid": not errors, "errors": errors}


def _chap_points(chap_admin_proxy: dict[str, Any]) -> list[dict[str, Any]]:
    points = []
    for row in chap_admin_proxy.get("admin_pm25_rows") or []:
        lon = _float(row.get("longitude"))
        lat = _float(row.get("latitude"))
        pm25 = _float(row.get("pm25_ugm3"))
        if lon is None or lat is None or pm25 is None:
            continue
        points.append(
            {
                "admin_unit_id": str(row.get("admin_unit_id")),
                "county": row.get("county"),
                "township": row.get("township"),
                "longitude": lon,
                "latitude": lat,
                "chap_pm25_ugm3": pm25,
            }
        )
    return points


def _nearest_tap_grids(
    downloaded: Path,
    points: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    best = {
        point["admin_unit_id"]: {
            "distance_sq": float("inf"),
            "tile_id": "",
            "grid_id": "",
            "longitude": None,
            "latitude": None,
        }
        for point in points
    }
    for tile_file in sorted(downloaded.glob("Tile_*_lonlat.csv.zip")):
        tile_id = _parse_tile_id(tile_file)
        for row in _read_single_csv_zip(tile_file):
            grid_id = str(row.get("GridID") or "").strip()
            lon = _float(row.get("Longitude"))
            lat = _float(row.get("Latitude"))
            if not grid_id or lon is None or lat is None:
                continue
            for point in points:
                distance_sq = (lon - point["longitude"]) ** 2 + (lat - point["latitude"]) ** 2
                current = best[point["admin_unit_id"]]
                if distance_sq < current["distance_sq"]:
                    current.update(
                        {
                            "distance_sq": distance_sq,
                            "tile_id": tile_id,
                            "grid_id": grid_id,
                            "longitude": lon,
                            "latitude": lat,
                        }
                    )
    return best


def _sample_tap_daily_series(
    downloaded: Path,
    points: list[dict[str, Any]],
    nearest: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    needed_by_tile: dict[str, set[str]] = defaultdict(set)
    for match in nearest.values():
        if match.get("tile_id") and match.get("grid_id"):
            needed_by_tile[str(match["tile_id"])].add(str(match["grid_id"]))

    values: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for pm_file in sorted(downloaded.glob("China_PM25_1km_*.csv.zip")):
        year, doy, tile_id = _parse_pm25_filename(pm_file)
        needed = needed_by_tile.get(tile_id)
        if not needed:
            continue
        for row in _read_single_csv_zip(pm_file):
            grid_id = str(row.get("GridID") or "").strip()
            if grid_id not in needed:
                continue
            pm25 = _float(row.get("PM2.5"))
            if pm25 is None:
                continue
            values[(tile_id, grid_id)].append(
                {"year": year, "doy": doy, "pm25_ugm3": pm25}
            )

    series = []
    for point in points:
        match = nearest.get(point["admin_unit_id"]) or {}
        key = (str(match.get("tile_id") or ""), str(match.get("grid_id") or ""))
        daily = sorted(values.get(key, []), key=lambda row: row["doy"])
        series.append(
            {
                **point,
                "tap_tile_id": key[0],
                "tap_grid_id": key[1],
                "tap_grid_longitude": _round(match.get("longitude")),
                "tap_grid_latitude": _round(match.get("latitude")),
                "tap_nearest_grid_distance_degrees": _round(
                    (float(match.get("distance_sq") or 0.0)) ** 0.5
                ),
                "daily_pm25": [
                    {
                        "date": _date_from_doy(row["year"], row["doy"]),
                        "doy": row["doy"],
                        "pm25_ugm3": _round(row["pm25_ugm3"]),
                    }
                    for row in daily
                ],
            }
        )
    return series


def _scene_train_mean(sampled_series: list[dict[str, Any]], train_days: int) -> float:
    values = [
        day["pm25_ugm3"]
        for series in sampled_series
        for day in (series.get("daily_pm25") or [])[:train_days]
        if _float(day.get("pm25_ugm3")) is not None
    ]
    return fmean(values) if values else 0.0


def _benchmark_admin_series(
    series: dict[str, Any],
    all_series: list[dict[str, Any]],
    *,
    series_index: int,
    train_days: int,
    scene_train_mean: float,
) -> dict[str, Any]:
    days = list(series.get("daily_pm25") or [])
    train = days[:train_days]
    holdout = days[train_days:]
    train_values = [_float(day.get("pm25_ugm3")) for day in train]
    holdout_values = [_float(day.get("pm25_ugm3")) for day in holdout]
    train_values = [value for value in train_values if value is not None]
    holdout_values = [value for value in holdout_values if value is not None]
    online_predictions = [train_values[-1], *holdout_values[:-1]]
    adaptive_predictions = _adaptive_predictions(train_values, holdout_values, alpha=0.7)
    uwm_errors = {
        "online_persistence_state_update": _errors(holdout_values, online_predictions),
        "adaptive_online_state_update": _errors(holdout_values, adaptive_predictions),
    }
    spatial_predictions = _spatial_message_predictions(
        series,
        all_series,
        series_index=series_index,
        train_days=train_days,
    )
    uwm_errors["spatial_scene_mean_message"] = _errors(
        holdout_values,
        spatial_predictions["spatial_scene_mean_message"],
    )
    uwm_errors["spatial_idw_message_reconstruction"] = _errors(
        holdout_values,
        spatial_predictions["spatial_idw_message_reconstruction"],
    )
    static_predictions = {
        "static_train_mean": [fmean(train_values)] * len(holdout_values),
        "static_last_train_observation": [train_values[-1]] * len(holdout_values),
        "scene_static_train_mean": [scene_train_mean] * len(holdout_values),
    }
    static_errors = {
        method: _errors(holdout_values, predictions)
        for method, predictions in static_predictions.items()
    }
    best_uwm_method = min(
        UWM_STATE_UPDATE_METHODS,
        key=lambda method: _mean(uwm_errors[method]),
    )
    best_static_method = min(
        TRADITIONAL_STATIC_BASELINES,
        key=lambda method: _mean(static_errors[method]),
    )
    best_uwm_mae = _mean(uwm_errors[best_uwm_method])
    return {
        "admin_unit_id": series.get("admin_unit_id"),
        "county": series.get("county"),
        "township": series.get("township"),
        "longitude": _round(series.get("longitude")),
        "latitude": _round(series.get("latitude")),
        "chap_pm25_ugm3": _round(series.get("chap_pm25_ugm3")),
        "tap_tile_id": series.get("tap_tile_id"),
        "tap_grid_id": series.get("tap_grid_id"),
        "tap_grid_longitude": series.get("tap_grid_longitude"),
        "tap_grid_latitude": series.get("tap_grid_latitude"),
        "tap_nearest_grid_distance_degrees": series.get(
            "tap_nearest_grid_distance_degrees"
        ),
        "observation_count": len(days),
        "train_count": len(train_values),
        "holdout_count": len(holdout_values),
        "daily_pm25": days,
        "uwm_state_updates": {
            method: {
                "mae": _round(_mean(errors)),
                "errors": [_round(error) for error in errors],
                "uses_prior_holdout_observations_online": True,
                "uses_current_or_future_holdout_labels": False,
            }
            for method, errors in uwm_errors.items()
        },
        "traditional_static_baseline_suite": {
            method: {
                "method": method,
                "mae": _round(_mean(errors)),
                "errors": [_round(error) for error in errors],
                "dynamic_win_count": sum(
                    dynamic_error < static_error
                    for dynamic_error, static_error in zip(
                        uwm_errors[best_uwm_method], errors
                    )
                ),
            }
            for method, errors in static_errors.items()
        },
        "best_uwm_method": best_uwm_method,
        "best_uwm_mae": _round(best_uwm_mae),
        "best_static_baseline_method": best_static_method,
        "best_static_baseline_mae": _round(_mean(static_errors[best_static_method])),
        "beats_all_traditional_static_baselines": all(
            best_uwm_mae < _mean(errors) for errors in static_errors.values()
        ),
        "best_uwm_errors": [_round(error) for error in uwm_errors[best_uwm_method]],
        "best_static_errors_by_method": {
            method: [_round(error) for error in errors]
            for method, errors in static_errors.items()
        },
        "temporal_order_negative_control": _series_temporal_negative_control(
            train_values,
            holdout_values,
            best_uwm_mae,
        ),
        "spatial_shuffle_negative_control": {
            "control": "reverse_coordinate_idw_message",
            "ordered_spatial_idw_mae": _round(
                _mean(uwm_errors["spatial_idw_message_reconstruction"])
            ),
            "shuffled_coordinate_idw_mae": _round(
                _mean(
                    _errors(
                        holdout_values,
                        spatial_predictions["reverse_coordinate_idw_message"],
                    )
                )
            ),
            "ordered_spatial_mae_advantage": _round(
                _mean(
                    _errors(
                        holdout_values,
                        spatial_predictions["reverse_coordinate_idw_message"],
                    )
                )
                - _mean(uwm_errors["spatial_idw_message_reconstruction"])
            ),
        },
    }


def _overall_results(series_results: list[dict[str, Any]]) -> dict[str, Any]:
    uwm_errors = {
        method: [
            error
            for series in series_results
            for error in series["uwm_state_updates"][method]["errors"]
        ]
        for method in UWM_STATE_UPDATE_METHODS
    }
    static_errors = {
        method: [
            error
            for series in series_results
            for error in series["traditional_static_baseline_suite"][method]["errors"]
        ]
        for method in TRADITIONAL_STATIC_BASELINES
    }
    best_uwm_method = min(UWM_STATE_UPDATE_METHODS, key=lambda method: _mean(uwm_errors[method]))
    best_static_method = min(
        TRADITIONAL_STATIC_BASELINES,
        key=lambda method: _mean(static_errors[method]),
    )
    best_uwm_mae = _mean(uwm_errors[best_uwm_method])
    return {
        "best_uwm_method": best_uwm_method,
        "best_static_baseline_method": best_static_method,
        "uwm_mae_by_method": {
            method: _round(_mean(errors)) for method, errors in uwm_errors.items()
        },
        "static_baseline_mae_by_method": {
            method: _round(_mean(errors)) for method, errors in static_errors.items()
        },
        "best_uwm_mae": _round(best_uwm_mae),
        "best_static_baseline_mae": _round(_mean(static_errors[best_static_method])),
        "best_uwm_mae_reduction": _round(
            _mean(static_errors[best_static_method]) - best_uwm_mae
        ),
        "beats_all_traditional_static_baselines": all(
            best_uwm_mae < _mean(errors) for errors in static_errors.values()
        ),
        "admin_units_beating_all_static_baselines": sum(
            series["beats_all_traditional_static_baselines"] for series in series_results
        ),
        "admin_unit_count": len(series_results),
    }


def _overall_sign_tests(
    series_results: list[dict[str, Any]],
    best_uwm_method: str,
) -> dict[str, Any]:
    dynamic_errors = [
        error
        for series in series_results
        for error in series["uwm_state_updates"][best_uwm_method]["errors"]
    ]
    tests = {}
    for method in TRADITIONAL_STATIC_BASELINES:
        static_errors = [
            error
            for series in series_results
            for error in series["traditional_static_baseline_suite"][method]["errors"]
        ]
        tests[method] = _sign_test(static_errors, dynamic_errors)
    return tests


def _spatial_message_predictions(
    target_series: dict[str, Any],
    all_series: list[dict[str, Any]],
    *,
    series_index: int,
    train_days: int,
) -> dict[str, list[float]]:
    target_days = list(target_series.get("daily_pm25") or [])
    target_lon = _float(target_series.get("longitude")) or 0.0
    target_lat = _float(target_series.get("latitude")) or 0.0
    reversed_coords = [
        (
            _float(series.get("longitude")) or 0.0,
            _float(series.get("latitude")) or 0.0,
        )
        for series in reversed(all_series)
    ]
    reverse_target_lon, reverse_target_lat = reversed_coords[series_index]

    scene_mean_predictions: list[float] = []
    idw_predictions: list[float] = []
    reverse_idw_predictions: list[float] = []
    for day_index in range(train_days, len(target_days)):
        values: list[float] = []
        weighted: list[tuple[float, float]] = []
        reverse_weighted: list[tuple[float, float]] = []
        for other_index, other in enumerate(all_series):
            if other_index == series_index:
                continue
            other_days = list(other.get("daily_pm25") or [])
            if len(other_days) <= day_index:
                continue
            value = _float(other_days[day_index].get("pm25_ugm3"))
            other_lon = _float(other.get("longitude"))
            other_lat = _float(other.get("latitude"))
            if value is None or other_lon is None or other_lat is None:
                continue
            distance = ((other_lon - target_lon) ** 2 + (other_lat - target_lat) ** 2) ** 0.5
            weight = 1.0 / (distance + 1e-6)
            values.append(value)
            weighted.append((weight, value))

            reverse_other_lon, reverse_other_lat = reversed_coords[other_index]
            reverse_distance = (
                (reverse_other_lon - reverse_target_lon) ** 2
                + (reverse_other_lat - reverse_target_lat) ** 2
            ) ** 0.5
            reverse_weighted.append((1.0 / (reverse_distance + 1e-6), value))
        scene_mean_predictions.append(_mean(values))
        idw_predictions.append(_weighted_mean(weighted))
        reverse_idw_predictions.append(_weighted_mean(reverse_weighted))
    return {
        "spatial_scene_mean_message": scene_mean_predictions,
        "spatial_idw_message_reconstruction": idw_predictions,
        "reverse_coordinate_idw_message": reverse_idw_predictions,
    }


def _spatial_message_negative_control(series_results: list[dict[str, Any]]) -> dict[str, Any]:
    advantages = [
        row["spatial_shuffle_negative_control"]["ordered_spatial_mae_advantage"]
        for row in series_results
    ]
    passed_count = sum(value > 0 for value in advantages)
    return {
        "admin_unit_count": len(series_results),
        "ordered_spatial_advantage_count": passed_count,
        "ordered_spatial_advantage_rate": _round(passed_count / len(series_results)),
        "mean_ordered_spatial_mae_advantage": _round(fmean(advantages)),
        "spatial_shuffle_negative_control_passed": fmean(advantages) > 0.0,
    }


def _uncertainty_calibration(
    series_results: list[dict[str, Any]],
    *,
    train_days: int,
    best_uwm_method: str,
    static_baseline_method: str,
    confidence_level: float,
) -> dict[str, Any]:
    if best_uwm_method != "spatial_idw_message_reconstruction":
        return {
            "method": "split_conformal_leave_one_train_day",
            "confidence_level": confidence_level,
            "uwm_uncertainty_calibration_ready": False,
            "supported_claim": "no_scene_aligned_gridded_uncertainty_claim_supported",
            "reason": "uncertainty calibration currently supports the spatial IDW message head",
        }

    alpha = 1.0 - confidence_level
    uwm_calibration_errors: list[float] = []
    static_calibration_errors: list[float] = []
    for series_index, series in enumerate(series_results):
        train_values = [
            _float(day.get("pm25_ugm3"))
            for day in (series.get("daily_pm25") or [])[:train_days]
        ]
        train_values = [value for value in train_values if value is not None]
        if len(train_values) < 2:
            continue
        for day_index, actual in enumerate(train_values):
            uwm_prediction = _spatial_idw_prediction_for_day(
                series_results,
                target_index=series_index,
                day_index=day_index,
            )
            uwm_calibration_errors.append(abs(actual - uwm_prediction))
            leave_one_values = [
                value for value_index, value in enumerate(train_values) if value_index != day_index
            ]
            static_calibration_errors.append(abs(actual - fmean(leave_one_values)))

    uwm_holdout_errors = [
        error
        for series in series_results
        for error in series["uwm_state_updates"][best_uwm_method]["errors"]
    ]
    static_holdout_errors = [
        error
        for series in series_results
        for error in series["traditional_static_baseline_suite"][static_baseline_method][
            "errors"
        ]
    ]
    uwm_radius = _conformal_radius(uwm_calibration_errors, confidence_level)
    static_radius = _conformal_radius(static_calibration_errors, confidence_level)
    uwm_scores = _interval_scores(uwm_holdout_errors, uwm_radius, alpha)
    static_scores = _interval_scores(static_holdout_errors, static_radius, alpha)
    uwm_interval_score = _mean(uwm_scores)
    static_interval_score = _mean(static_scores)
    ready = (
        len(uwm_calibration_errors) > 0
        and len(uwm_holdout_errors) > 0
        and _coverage(uwm_holdout_errors, uwm_radius) >= confidence_level
        and uwm_interval_score < static_interval_score
        and _mean(uwm_holdout_errors) < _mean(static_holdout_errors)
    )
    return {
        "method": "split_conformal_leave_one_train_day",
        "confidence_level": confidence_level,
        "calibration_count": len(uwm_calibration_errors),
        "holdout_count": len(uwm_holdout_errors),
        "best_uwm_method": best_uwm_method,
        "static_baseline_method": static_baseline_method,
        "uwm_interval_radius": _round(uwm_radius),
        "static_interval_radius": _round(static_radius),
        "uwm_interval_coverage": _round(_coverage(uwm_holdout_errors, uwm_radius)),
        "static_interval_coverage": _round(
            _coverage(static_holdout_errors, static_radius)
        ),
        "uwm_mean_interval_width": _round(2.0 * uwm_radius),
        "static_mean_interval_width": _round(2.0 * static_radius),
        "uwm_interval_score": _round(uwm_interval_score),
        "static_interval_score": _round(static_interval_score),
        "uwm_interval_score_reduction": _round(
            static_interval_score - uwm_interval_score
        ),
        "uwm_uncertainty_calibration_ready": ready,
        "supported_claim": SCENE_ALIGNED_GRIDDED_CONFORMAL_UNCERTAINTY_CLAIM
        if ready
        else "no_scene_aligned_gridded_uncertainty_claim_supported",
        "limitations": [
            "split_conformal_calibrated_on_short_scene_train_window",
            "gridded_product_not_station_calibrated",
            "not_policy_intervention_outcome",
        ],
    }


def _spatial_idw_prediction_for_day(
    all_series: list[dict[str, Any]],
    *,
    target_index: int,
    day_index: int,
) -> float:
    target = all_series[target_index]
    target_lon = _float(target.get("longitude")) or 0.0
    target_lat = _float(target.get("latitude")) or 0.0
    weighted: list[tuple[float, float]] = []
    for other_index, other in enumerate(all_series):
        if other_index == target_index:
            continue
        other_days = list(other.get("daily_pm25") or [])
        if len(other_days) <= day_index:
            continue
        value = _float(other_days[day_index].get("pm25_ugm3"))
        other_lon = _float(other.get("longitude"))
        other_lat = _float(other.get("latitude"))
        if value is None or other_lon is None or other_lat is None:
            continue
        distance = ((other_lon - target_lon) ** 2 + (other_lat - target_lat) ** 2) ** 0.5
        weighted.append((1.0 / (distance + 1e-6), value))
    return _weighted_mean(weighted)


def _conformal_radius(errors: list[float], confidence_level: float) -> float:
    if not errors:
        return 0.0
    ordered = sorted(errors)
    index = min(
        len(ordered) - 1,
        max(0, math.ceil((len(ordered) + 1) * confidence_level) - 1),
    )
    return ordered[index]


def _coverage(errors: list[float], radius: float) -> float:
    return sum(error <= radius for error in errors) / len(errors) if errors else 0.0


def _interval_scores(errors: list[float], radius: float, alpha: float) -> list[float]:
    width = 2.0 * radius
    return [width + (2.0 / alpha) * max(error - radius, 0.0) for error in errors]


def _temporal_order_negative_control(series_results: list[dict[str, Any]]) -> dict[str, Any]:
    ordered_advantages = [
        row["temporal_order_negative_control"]["ordered_mae_advantage"]
        for row in series_results
    ]
    passed_count = sum(value > 0 for value in ordered_advantages)
    return {
        "admin_unit_count": len(series_results),
        "ordered_advantage_count": passed_count,
        "ordered_advantage_rate": _round(passed_count / len(series_results)),
        "mean_ordered_mae_advantage": _round(fmean(ordered_advantages)),
        "temporal_order_negative_control_passed": passed_count == len(series_results)
        and fmean(ordered_advantages) > 0.0,
    }


def _series_temporal_negative_control(
    train_values: list[float],
    holdout_values: list[float],
    ordered_mae: float,
) -> dict[str, Any]:
    reversed_holdout = list(reversed(holdout_values))
    predictions = [train_values[-1], *reversed_holdout[:-1]]
    shuffled_mae = _mean(_errors(holdout_values, predictions))
    return {
        "control": "reverse_holdout_temporal_order",
        "ordered_mae": _round(ordered_mae),
        "reversed_order_mae": _round(shuffled_mae),
        "ordered_mae_advantage": _round(shuffled_mae - ordered_mae),
    }


def _tap_sampling_summary(sampled_series: list[dict[str, Any]]) -> dict[str, Any]:
    sampled = [row for row in sampled_series if row.get("daily_pm25")]
    missing = [row for row in sampled_series if not row.get("daily_pm25")]
    return {
        "requested_admin_units": len(sampled_series),
        "sampled_admin_units": len(sampled),
        "missing_admin_units": len(missing),
        "daily_record_count": sum(len(row.get("daily_pm25") or []) for row in sampled),
        "grid_resolution": "1 km daily",
        "sampling_geometry": "chap_admin_representative_point_nearest_tap_grid",
    }


def _chap_anchor_summary(
    chap_admin_proxy: dict[str, Any],
    sampled_series: list[dict[str, Any]],
) -> dict[str, Any]:
    counts = chap_admin_proxy.get("record_counts") or {}
    gaps = [
        abs(float(row["chap_pm25_ugm3"]) - fmean(day["pm25_ugm3"] for day in row["daily_pm25"]))
        for row in sampled_series
        if row.get("daily_pm25")
    ]
    return {
        "valid_pm25_admin_units": int(counts.get("valid_pm25_admin_units") or 0),
        "chap_temporal_resolution": "monthly",
        "tap_temporal_resolution": "daily_first_seven_days",
        "mean_abs_chap_tap_scene_gap": _round(fmean(gaps)) if gaps else None,
    }


def _adaptive_predictions(
    train_values: list[float],
    holdout_values: list[float],
    *,
    alpha: float,
) -> list[float]:
    state = train_values[-1]
    predictions = []
    for observed in holdout_values:
        predictions.append(state)
        state = alpha * observed + (1.0 - alpha) * state
    return predictions


def _errors(values: list[float], predictions: list[float]) -> list[float]:
    return [abs(value - prediction) for value, prediction in zip(values, predictions)]


def _sign_test(static_errors: list[float], dynamic_errors: list[float]) -> dict[str, Any]:
    wins = sum(dynamic < static for dynamic, static in zip(dynamic_errors, static_errors))
    losses = sum(dynamic > static for dynamic, static in zip(dynamic_errors, static_errors))
    ties = len(static_errors) - wins - losses
    n = wins + losses
    p_value = _binomial_one_sided_p_value(wins, n) if n else 1.0
    return {
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "effective_n": n,
        "one_sided_p_value": p_value,
    }


def _binomial_one_sided_p_value(wins: int, n: int) -> float:
    if n <= 0:
        return 1.0
    probability = sum(comb(n, k) for k in range(wins, n + 1)) / (2**n)
    return round(float(probability), 12)


def _read_single_csv_zip(path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as handle:
        csv_names = [name for name in handle.namelist() if name.lower().endswith(".csv")]
        if len(csv_names) != 1:
            raise ValueError(f"expected one CSV in {path}, found {csv_names}")
        with handle.open(csv_names[0]) as raw:
            return list(csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")))


def _parse_tile_id(path: Path) -> str:
    match = re.search(r"Tile_(\d{3})_lonlat", path.name)
    if not match:
        raise ValueError(f"unexpected TAP tile filename: {path.name}")
    return match.group(1)


def _parse_pm25_filename(path: Path) -> tuple[str, str, str]:
    match = re.search(r"China_PM25_1km_(\d{4})_(\d{3})_(\d{3})\.csv\.zip$", path.name)
    if not match:
        raise ValueError(f"unexpected TAP PM2.5 filename: {path.name}")
    return match.group(1), match.group(2), match.group(3)


def _date_from_doy(year: str, doy: str) -> str:
    day = int(doy) - 183 + 1
    return f"{year}-07-{day:02d}"


def _mean(values: list[float]) -> float:
    return fmean(values) if values else 0.0


def _weighted_mean(values: list[tuple[float, float]]) -> float:
    weight_sum = sum(weight for weight, _ in values)
    if weight_sum <= 0.0:
        return 0.0
    return sum(weight * value for weight, value in values) / weight_sum


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: Any, digits: int = 6) -> float | None:
    number = _float(value)
    return round(number, digits) if number is not None else None
