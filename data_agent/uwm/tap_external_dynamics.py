"""TAP external spatiotemporal dynamics holdout for UWM."""

from __future__ import annotations

import csv
import io
import math
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from statistics import fmean, median
from typing import Any

import numpy as np


TAP_EXTERNAL_DYNAMICS_SCHEMA = "uwm.tap_external_spatiotemporal_dynamics_report.v1"
TAP_EXTERNAL_DATASET_ID = "tap_pm25_observed_gridded_chongqing_2018_2024"
STATIC_BASELINES = [
    "static_train_mean",
    "static_last_train_observation",
    "period_static_mean",
    "tile_static_mean",
]
NON_SPATIAL_DYNAMIC_BASELINES = [
    "online_persistence_state_update",
    "adaptive_online_state_update",
]
SPATIAL_METHODS = ["spatial_message_ridge"]
FEATURE_NAMES = [
    "bias",
    "target_previous_pm25",
    "target_train_mean",
    "tile_train_mean",
    "neighbor_previous_mean",
    "neighbor_previous_median",
    "target_neighbor_previous_contrast",
    "tile_previous_anomaly",
    "day_index_norm",
]


def build_tap_external_dynamics_report(
    *,
    tap_root: str | Path,
    model_id: str,
    created_at: str,
    train_days: int = 3,
    max_grid_series_per_period: int = 5000,
    neighbor_count: int = 4,
    ridge: float = 0.001,
    include_feature_audit: bool = False,
) -> dict[str, Any]:
    root = Path(tap_root)
    if not root.exists():
        raise FileNotFoundError(f"TAP root not found: {root}")
    period_reports = [
        _build_period_report(
            period_dir,
            train_days=train_days,
            max_series=max_grid_series_per_period,
            neighbor_count=neighbor_count,
            ridge=ridge,
            include_feature_audit=include_feature_audit,
        )
        for period_dir in _period_dirs(root)
    ]
    period_reports = [report for report in period_reports if report["training_summary"]["series_count"] > 0]
    if not period_reports:
        raise ValueError("no TAP periods with enough external dynamics series")
    overall = _combine_overall(period_reports)
    supported_claim = _supported_claim(overall)
    payload = {
        "schema": TAP_EXTERNAL_DYNAMICS_SCHEMA,
        "version": "0.1",
        "model_id": model_id,
        "created_at": created_at,
        "source_dataset_ids": [TAP_EXTERNAL_DATASET_ID],
        "sampling_config": {
            "train_days": train_days,
            "max_grid_series_per_period": max_grid_series_per_period,
            "neighbor_count": neighbor_count,
            "neighbor_mode": "lonlat_nearest_neighbors_v1",
            "ridge": ridge,
        },
        "feature_schema": {
            "feature_names": FEATURE_NAMES,
            "target": "next_day_pm25_ugm3",
            "feature_time_rule": "features_for_day_t_use_only_values_strictly_before_day_t",
        },
        "training_summary": overall["training_summary"],
        "baseline_results": overall["baseline_results"],
        "spatial_world_model_results": overall["spatial_world_model_results"],
        "negative_control_results": overall["negative_control_results"],
        "period_results": period_reports,
        "overall_results": overall["overall_results"],
        "supported_claim": supported_claim,
        "claim_boundary": {
            "max_claim_level": "bounded_support"
            if supported_claim != "no_tap_external_dynamics_advantage_claim_supported"
            else "not_for_claim",
            "reason": (
                "TAP gridded PM2.5 supports external state-dynamics validation. "
                "It is not station-observed policy intervention outcome evidence."
            ),
        },
        "limitations": [
            "tap_gridded_product_not_station_observation",
            "not_policy_intervention_outcome",
            "action_free_exogenous_air_pollution_dynamics_only",
            "short_daily_holdout_window",
            "sampled_grid_series_for_runtime_control",
        ],
        "empirical_superiority_claim": False,
        "observed_policy_outcome_superiority_claim": False,
    }
    if include_feature_audit:
        payload["feature_audit_sample"] = [
            row
            for report in period_reports
            for row in report.get("feature_audit_sample", [])
        ][:50]
    return payload


def validate_tap_external_dynamics_report(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != TAP_EXTERNAL_DYNAMICS_SCHEMA:
        errors.append(f"schema must be {TAP_EXTERNAL_DYNAMICS_SCHEMA}")
    for key in [
        "model_id",
        "sampling_config",
        "feature_schema",
        "training_summary",
        "baseline_results",
        "spatial_world_model_results",
        "negative_control_results",
        "overall_results",
        "claim_boundary",
        "limitations",
    ]:
        if key not in payload:
            errors.append(f"{key} is required")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim must stay false")
    if payload.get("observed_policy_outcome_superiority_claim") is not False:
        errors.append("observed_policy_outcome_superiority_claim must stay false")
    if "not_policy_intervention_outcome" not in (payload.get("limitations") or []):
        errors.append("limitations must include not_policy_intervention_outcome")
    leakage = (payload.get("negative_control_results") or {}).get("future_label_leakage_guard") or {}
    if leakage.get("passed") is not True:
        errors.append("future label leakage guard must pass")
    return {"valid": not errors, "errors": errors}


def _build_period_report(
    period_dir: Path,
    *,
    train_days: int,
    max_series: int,
    neighbor_count: int,
    ridge: float,
    include_feature_audit: bool,
) -> dict[str, Any]:
    all_series = _load_period_series_with_lonlat(period_dir)
    selected_keys = sorted(all_series)[:max_series]
    selected = {key: all_series[key] for key in selected_keys}
    selected = {key: value for key, value in selected.items() if len(value["values_by_doy"]) > train_days}
    if not selected:
        return {
            "period_id": period_dir.name,
            "training_summary": {"series_count": 0, "train_count": 0, "holdout_count": 0},
        }
    neighbors = _nearest_neighbors(selected, neighbor_count)
    rows = _feature_rows_for_period(selected, neighbors, train_days)
    train_rows = [row for row in rows if not row["is_holdout"]]
    holdout_rows = [row for row in rows if row["is_holdout"]]
    if not holdout_rows:
        return {
            "period_id": period_dir.name,
            "training_summary": {"series_count": len(selected), "train_count": len(train_rows), "holdout_count": 0},
        }

    baseline_predictions = _predict_baselines(holdout_rows)
    spatial_predictions, coefficients = _predict_spatial(train_rows, holdout_rows, ridge)
    shuffled_rows = _neighbor_shuffle_rows(holdout_rows)
    shuffled_predictions, _ = _predict_spatial(train_rows, shuffled_rows, ridge)
    ablated_train_rows = _non_spatial_feature_ablation_rows(train_rows)
    ablated_holdout_rows = _non_spatial_feature_ablation_rows(holdout_rows)
    ablated_predictions, _ = _predict_spatial(ablated_train_rows, ablated_holdout_rows, ridge)
    baseline_results = {
        "traditional_static": {
            method: _evaluate_predictions(holdout_rows, predictions)
            for method, predictions in baseline_predictions["traditional_static"].items()
        },
        "non_spatial_dynamic": {
            method: _evaluate_predictions(holdout_rows, predictions)
            for method, predictions in baseline_predictions["non_spatial_dynamic"].items()
        },
    }
    non_spatial_best_method = min(
        baseline_results["non_spatial_dynamic"],
        key=lambda method: baseline_results["non_spatial_dynamic"][method]["mae"],
    )
    non_spatial_best_predictions = baseline_predictions["non_spatial_dynamic"][non_spatial_best_method]
    spatial_eval = _evaluate_predictions(holdout_rows, spatial_predictions)
    spatial_eval.update(_paired_wins(holdout_rows, spatial_predictions, non_spatial_best_predictions))
    shuffled_eval = _evaluate_predictions(holdout_rows, shuffled_predictions)
    ablated_eval = _evaluate_predictions(holdout_rows, ablated_predictions)
    temporal_control = _temporal_order_rotation_control(holdout_rows, spatial_predictions)
    feature_audit_sample = [
        {
            "period_id": period_dir.name,
            "tile_id": row["key"][0],
            "grid_id": row["key"][1],
            "target_doy": row["target_doy"],
            "max_feature_doy": row["max_feature_doy"],
        }
        for row in holdout_rows[:25]
    ]
    result = {
        "period_id": period_dir.name,
        "training_summary": {
            "series_count": len(selected),
            "train_count": len(train_rows),
            "holdout_count": len(holdout_rows),
        },
        "baseline_results": baseline_results,
        "spatial_world_model_results": {
            "spatial_message_ridge": {
                **spatial_eval,
                "coefficient_count": int(len(coefficients)),
            }
        },
        "negative_control_results": {
            "neighbor_shuffle_control": {
                **shuffled_eval,
                "real_spatial_advantage": _round(shuffled_eval["mae"] - spatial_eval["mae"]),
            },
            "non_spatial_feature_ablation_control": {
                **ablated_eval,
                "real_spatial_advantage": _round(ablated_eval["mae"] - spatial_eval["mae"]),
            },
            "temporal_order_rotation_control": temporal_control,
            "future_label_leakage_guard": _future_label_leakage_guard(rows),
        },
    }
    if include_feature_audit:
        result["feature_audit_sample"] = feature_audit_sample
    return result


def _period_dirs(root: Path) -> list[Path]:
    return sorted(path for path in root.iterdir() if path.is_dir() and path.name.startswith("chongqing_pm25_"))


def _load_period_series_with_lonlat(period_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    downloaded = period_dir / "downloaded"
    tile_xy = _load_tile_lonlat(downloaded)
    values: dict[tuple[str, str], dict[str, Any]] = {}
    for pm_file in sorted(downloaded.glob("China_PM25_1km_*.csv.zip")):
        year, doy, tile_id = _parse_pm25_filename(pm_file)
        if tile_id not in tile_xy:
            raise ValueError(f"missing lon/lat tile {tile_id} for {pm_file.name}")
        for row in _read_single_csv_zip(pm_file):
            grid_id = str(row.get("GridID") or "").strip()
            pm25 = _float(row.get("PM2.5"))
            xy = tile_xy[tile_id].get(grid_id)
            if not grid_id or pm25 is None or xy is None:
                continue
            key = (tile_id, grid_id)
            if key not in values:
                values[key] = {
                    "tile_id": tile_id,
                    "grid_id": grid_id,
                    "longitude": xy[0],
                    "latitude": xy[1],
                    "year": year,
                    "values_by_doy": {},
                }
            values[key]["values_by_doy"][doy] = pm25
    return values


def _load_tile_lonlat(downloaded: Path) -> dict[str, dict[str, tuple[float, float]]]:
    tile_xy: dict[str, dict[str, tuple[float, float]]] = {}
    for tile_file in sorted(downloaded.glob("Tile_*_lonlat.csv.zip")):
        match = re.search(r"Tile_(\d{3})_lonlat", tile_file.name)
        if not match:
            continue
        tile_id = match.group(1)
        grid_xy = {}
        for row in _read_single_csv_zip(tile_file):
            grid_id = str(row.get("GridID") or "").strip()
            lon = _float(row.get("Longitude"))
            lat = _float(row.get("Latitude"))
            if grid_id and lon is not None and lat is not None:
                grid_xy[grid_id] = (lon, lat)
        tile_xy[tile_id] = grid_xy
    return tile_xy


def _nearest_neighbors(
    selected_series: dict[tuple[str, str], dict[str, Any]],
    neighbor_count: int,
) -> dict[tuple[str, str], list[tuple[str, str]]]:
    by_tile: dict[str, list[tuple[tuple[str, str], dict[str, Any]]]] = defaultdict(list)
    for key, series in selected_series.items():
        by_tile[key[0]].append((key, series))
    neighbors: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for tile_rows in by_tile.values():
        for key, series in tile_rows:
            ranked = []
            for other_key, other in tile_rows:
                if other_key == key:
                    continue
                distance = math.hypot(
                    float(series["longitude"]) - float(other["longitude"]),
                    float(series["latitude"]) - float(other["latitude"]),
                )
                ranked.append((distance, other_key))
            ranked.sort(key=lambda item: (item[0], item[1]))
            neighbors[key] = [other_key for _, other_key in ranked[:neighbor_count]]
    return neighbors


def _feature_rows_for_period(
    selected_series: dict[tuple[str, str], dict[str, Any]],
    neighbors_by_key: dict[tuple[str, str], list[tuple[str, str]]],
    train_days: int,
) -> list[dict[str, Any]]:
    all_doys = sorted({doy for series in selected_series.values() for doy in series["values_by_doy"]})
    tile_train_means = _tile_train_means(selected_series, all_doys[:train_days])
    rows = []
    for key, series in selected_series.items():
        values = series["values_by_doy"]
        train_values = [values[doy] for doy in all_doys[:train_days] if doy in values]
        if not train_values:
            continue
        target_train_mean = fmean(train_values)
        tile_train_mean = tile_train_means.get(key[0], target_train_mean)
        for day_index in range(1, len(all_doys)):
            target_doy = all_doys[day_index]
            previous_doy = all_doys[day_index - 1]
            if target_doy not in values or previous_doy not in values:
                continue
            neighbor_previous_values = [
                selected_series[neighbor]["values_by_doy"][previous_doy]
                for neighbor in neighbors_by_key.get(key, [])
                if previous_doy in selected_series[neighbor]["values_by_doy"]
            ]
            if not neighbor_previous_values:
                continue
            target_previous = values[previous_doy]
            neighbor_mean = fmean(neighbor_previous_values)
            tile_previous_values = [
                other["values_by_doy"][previous_doy]
                for other_key, other in selected_series.items()
                if other_key[0] == key[0] and previous_doy in other["values_by_doy"]
            ]
            tile_previous_mean = fmean(tile_previous_values) if tile_previous_values else tile_train_mean
            features = [
                1.0,
                target_previous,
                target_train_mean,
                tile_train_mean,
                neighbor_mean,
                median(neighbor_previous_values),
                target_previous - neighbor_mean,
                tile_previous_mean - tile_train_mean,
                day_index / max(1, len(all_doys) - 1),
            ]
            rows.append(
                {
                    "key": key,
                    "target_doy": target_doy,
                    "target_value": values[target_doy],
                    "is_holdout": day_index >= train_days,
                    "features": features,
                    "max_feature_doy": previous_doy,
                    "baselines": {
                        "static_train_mean": target_train_mean,
                        "static_last_train_observation": train_values[-1],
                        "period_static_mean": _period_train_mean(selected_series, all_doys[:train_days]),
                        "tile_static_mean": tile_train_mean,
                        "online_persistence_state_update": target_previous,
                        "adaptive_online_state_update": 0.7 * target_previous + 0.3 * target_train_mean,
                    },
                }
            )
    return rows


def _tile_train_means(
    selected_series: dict[tuple[str, str], dict[str, Any]],
    train_doys: list[str],
) -> dict[str, float]:
    values_by_tile: dict[str, list[float]] = defaultdict(list)
    for key, series in selected_series.items():
        for doy in train_doys:
            if doy in series["values_by_doy"]:
                values_by_tile[key[0]].append(series["values_by_doy"][doy])
    return {tile_id: fmean(values) for tile_id, values in values_by_tile.items() if values}


def _period_train_mean(
    selected_series: dict[tuple[str, str], dict[str, Any]],
    train_doys: list[str],
) -> float:
    values = [
        series["values_by_doy"][doy]
        for series in selected_series.values()
        for doy in train_doys
        if doy in series["values_by_doy"]
    ]
    return fmean(values) if values else 0.0


def _predict_baselines(holdout_rows: list[dict[str, Any]]) -> dict[str, dict[str, list[float]]]:
    return {
        "traditional_static": {
            method: [row["baselines"][method] for row in holdout_rows]
            for method in STATIC_BASELINES
        },
        "non_spatial_dynamic": {
            method: [row["baselines"][method] for row in holdout_rows]
            for method in NON_SPATIAL_DYNAMIC_BASELINES
        },
    }


def _predict_spatial(
    train_rows: list[dict[str, Any]],
    holdout_rows: list[dict[str, Any]],
    ridge: float,
) -> tuple[list[float], np.ndarray]:
    if len(train_rows) < 2:
        return ([
            0.5 * row["features"][1] + 0.5 * row["features"][4]
            for row in holdout_rows
        ], np.array([]))
    x_train = np.array([row["features"] for row in train_rows], dtype=float)
    y_train = np.array([row["target_value"] for row in train_rows], dtype=float)
    x_holdout = np.array([row["features"] for row in holdout_rows], dtype=float)
    coefficients = _fit_ridge(x_train, y_train, ridge)
    predictions = x_holdout @ coefficients
    return ([float(value) for value in predictions], coefficients)


def _fit_ridge(x: np.ndarray, y: np.ndarray, ridge: float) -> np.ndarray:
    penalty = np.eye(x.shape[1]) * ridge
    penalty[0, 0] = 0.0
    return np.linalg.pinv(x.T @ x + penalty) @ x.T @ y


def _evaluate_predictions(rows: list[dict[str, Any]], predictions: list[float]) -> dict[str, Any]:
    errors = [abs(row["target_value"] - prediction) for row, prediction in zip(rows, predictions)]
    return {
        "mae": _round(fmean(errors) if errors else 0.0),
        "case_count": len(errors),
    }


def _paired_wins(
    rows: list[dict[str, Any]],
    spatial_predictions: list[float],
    baseline_predictions: list[float],
) -> dict[str, Any]:
    wins = losses = ties = 0
    for row, spatial, baseline in zip(rows, spatial_predictions, baseline_predictions):
        spatial_error = abs(row["target_value"] - spatial)
        baseline_error = abs(row["target_value"] - baseline)
        if spatial_error < baseline_error:
            wins += 1
        elif spatial_error > baseline_error:
            losses += 1
        else:
            ties += 1
    total = wins + losses + ties
    return {
        "paired_win_count_vs_best_non_spatial_dynamic": wins,
        "paired_loss_count_vs_best_non_spatial_dynamic": losses,
        "paired_tie_count_vs_best_non_spatial_dynamic": ties,
        "paired_win_rate_vs_best_non_spatial_dynamic": _round(wins / total) if total else 0.0,
    }


def _neighbor_shuffle_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    shuffled_neighbor_features = [
        (row["features"][4], row["features"][5])
        for row in rows[1:] + rows[:1]
    ]
    shuffled = []
    for row, (neighbor_mean, neighbor_median) in zip(rows, shuffled_neighbor_features):
        new_row = dict(row)
        features = list(row["features"])
        features[4] = neighbor_mean
        features[5] = neighbor_median
        features[6] = features[1] - neighbor_mean
        new_row["features"] = features
        shuffled.append(new_row)
    return shuffled


def _non_spatial_feature_ablation_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ablated = []
    for row in rows:
        new_row = dict(row)
        features = list(row["features"])
        features[4] = features[1]
        features[5] = features[1]
        features[6] = 0.0
        new_row["features"] = features
        ablated.append(new_row)
    return ablated


def _temporal_order_rotation_control(rows: list[dict[str, Any]], spatial_predictions: list[float]) -> dict[str, Any]:
    if not rows:
        return {"mae": 0.0, "ordered_advantage": 0.0}
    rotated_targets = [row["target_value"] for row in rows[1:] + rows[:1]]
    rotated_errors = [abs(target - prediction) for target, prediction in zip(rotated_targets, spatial_predictions)]
    ordered_errors = [abs(row["target_value"] - prediction) for row, prediction in zip(rows, spatial_predictions)]
    rotated_mae = fmean(rotated_errors) if rotated_errors else 0.0
    ordered_mae = fmean(ordered_errors) if ordered_errors else 0.0
    return {
        "mae": _round(rotated_mae),
        "ordered_mae": _round(ordered_mae),
        "ordered_advantage": _round(rotated_mae - ordered_mae),
    }


def _future_label_leakage_guard(rows: list[dict[str, Any]]) -> dict[str, Any]:
    violations = [
        row
        for row in rows
        if int(row["max_feature_doy"]) >= int(row["target_doy"])
    ]
    return {
        "passed": not violations,
        "audited_feature_rows": len(rows),
        "violation_count": len(violations),
        "feature_time_rule": "features_for_day_t_use_only_values_strictly_before_day_t",
    }


def _combine_overall(period_reports: list[dict[str, Any]]) -> dict[str, Any]:
    train_count = sum(report["training_summary"]["train_count"] for report in period_reports)
    holdout_count = sum(report["training_summary"]["holdout_count"] for report in period_reports)
    series_count = sum(report["training_summary"]["series_count"] for report in period_reports)
    baseline_results = {
        "traditional_static": {
            method: _weighted_metric(period_reports, ["baseline_results", "traditional_static", method])
            for method in STATIC_BASELINES
        },
        "non_spatial_dynamic": {
            method: _weighted_metric(period_reports, ["baseline_results", "non_spatial_dynamic", method])
            for method in NON_SPATIAL_DYNAMIC_BASELINES
        },
    }
    spatial_result = _weighted_metric(period_reports, ["spatial_world_model_results", "spatial_message_ridge"])
    neighbor_shuffle = _weighted_metric(period_reports, ["negative_control_results", "neighbor_shuffle_control"])
    non_spatial_ablation = _weighted_metric(period_reports, ["negative_control_results", "non_spatial_feature_ablation_control"])
    temporal_controls = [
        report["negative_control_results"]["temporal_order_rotation_control"]
        for report in period_reports
    ]
    temporal_control = {
        "mae": _round(fmean([control["mae"] for control in temporal_controls])),
        "ordered_advantage": _round(fmean([control["ordered_advantage"] for control in temporal_controls])),
    }
    leakage_rows = sum(
        report["negative_control_results"]["future_label_leakage_guard"]["audited_feature_rows"]
        for report in period_reports
    )
    leakage_violations = sum(
        report["negative_control_results"]["future_label_leakage_guard"]["violation_count"]
        for report in period_reports
    )
    best_traditional = min(
        baseline_results["traditional_static"],
        key=lambda method: baseline_results["traditional_static"][method]["mae"],
    )
    best_non_spatial = min(
        baseline_results["non_spatial_dynamic"],
        key=lambda method: baseline_results["non_spatial_dynamic"][method]["mae"],
    )
    best_spatial_mae = spatial_result["mae"]
    best_traditional_mae = baseline_results["traditional_static"][best_traditional]["mae"]
    best_non_spatial_mae = baseline_results["non_spatial_dynamic"][best_non_spatial]["mae"]
    neighbor_shuffle["real_spatial_advantage"] = _round(neighbor_shuffle["mae"] - best_spatial_mae)
    non_spatial_ablation["real_spatial_advantage"] = _round(non_spatial_ablation["mae"] - best_spatial_mae)
    spatial_negative_control_passed = (
        neighbor_shuffle["mae"] > best_spatial_mae
        and non_spatial_ablation["mae"] > best_spatial_mae
    )
    paired_counts = _weighted_paired_counts(period_reports)
    spatial_result.update(paired_counts)
    overall_results = {
        "best_spatial_method": "spatial_message_ridge",
        "best_traditional_static_method": best_traditional,
        "best_non_spatial_dynamic_method": best_non_spatial,
        "best_spatial_mae": best_spatial_mae,
        "best_traditional_static_mae": best_traditional_mae,
        "best_non_spatial_dynamic_mae": best_non_spatial_mae,
        "spatial_mae_reduction_vs_best_static": _round(best_traditional_mae - best_spatial_mae),
        "spatial_mae_reduction_vs_best_non_spatial_dynamic": _round(best_non_spatial_mae - best_spatial_mae),
        "paired_win_rate_vs_best_non_spatial_dynamic": paired_counts["paired_win_rate_vs_best_non_spatial_dynamic"],
        "spatial_negative_control_passed": spatial_negative_control_passed,
    }
    return {
        "training_summary": {
            "series_count": series_count,
            "train_count": train_count,
            "holdout_count": holdout_count,
        },
        "baseline_results": baseline_results,
        "spatial_world_model_results": {"spatial_message_ridge": spatial_result},
        "negative_control_results": {
            "neighbor_shuffle_control": neighbor_shuffle,
            "non_spatial_feature_ablation_control": non_spatial_ablation,
            "temporal_order_rotation_control": temporal_control,
            "future_label_leakage_guard": {
                "passed": leakage_violations == 0,
                "audited_feature_rows": leakage_rows,
                "violation_count": leakage_violations,
                "feature_time_rule": "features_for_day_t_use_only_values_strictly_before_day_t",
            },
        },
        "overall_results": overall_results,
    }


def _weighted_metric(period_reports: list[dict[str, Any]], path: list[str]) -> dict[str, Any]:
    weighted_sum = 0.0
    case_count = 0
    merged: dict[str, Any] = {}
    for report in period_reports:
        metric: Any = report
        for key in path:
            metric = metric[key]
        cases = int(metric.get("case_count", report["training_summary"]["holdout_count"]))
        weighted_sum += float(metric["mae"]) * cases
        case_count += cases
        for key, value in metric.items():
            if key not in {"mae", "case_count"}:
                merged[key] = value
    return {"mae": _round(weighted_sum / case_count) if case_count else 0.0, "case_count": case_count, **merged}


def _weighted_paired_counts(period_reports: list[dict[str, Any]]) -> dict[str, Any]:
    wins = losses = ties = total = 0
    for report in period_reports:
        metric = report["spatial_world_model_results"]["spatial_message_ridge"]
        wins += int(metric.get("paired_win_count_vs_best_non_spatial_dynamic", 0))
        losses += int(metric.get("paired_loss_count_vs_best_non_spatial_dynamic", 0))
        ties += int(metric.get("paired_tie_count_vs_best_non_spatial_dynamic", 0))
        total += int(metric.get("case_count", 0))
    return {
        "paired_win_count_vs_best_non_spatial_dynamic": wins,
        "paired_loss_count_vs_best_non_spatial_dynamic": losses,
        "paired_tie_count_vs_best_non_spatial_dynamic": ties,
        "paired_win_rate_vs_best_non_spatial_dynamic": _round(wins / total) if total else 0.0,
    }


def _supported_claim(overall: dict[str, Any]) -> str:
    results = overall["overall_results"]
    beats_static = results["best_spatial_mae"] < results["best_traditional_static_mae"]
    beats_dynamic = results["best_spatial_mae"] < results["best_non_spatial_dynamic_mae"]
    spatial_wins = results["paired_win_rate_vs_best_non_spatial_dynamic"] > 0.5
    negative_control = results["spatial_negative_control_passed"]
    if beats_static and beats_dynamic and spatial_wins and negative_control:
        return "tap_external_spatiotemporal_dynamics_advantage_over_static_and_non_spatial_baselines"
    if beats_static and beats_dynamic:
        return "tap_external_temporal_dynamics_advantage_without_spatial_claim"
    return "no_tap_external_dynamics_advantage_claim_supported"


def _read_single_csv_zip(path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as handle:
        csv_names = [name for name in handle.namelist() if name.lower().endswith(".csv")]
        if len(csv_names) != 1:
            raise ValueError(f"expected one CSV in {path}, found {csv_names}")
        with handle.open(csv_names[0]) as raw:
            return list(csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")))


def _parse_pm25_filename(path: Path) -> tuple[str, str, str]:
    match = re.search(r"China_PM25_1km_(\d{4})_(\d{3})_(\d{3})\.csv\.zip$", path.name)
    if not match:
        raise ValueError(f"unexpected TAP PM2.5 filename: {path.name}")
    return match.group(1), match.group(2), match.group(3)


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: Any) -> float:
    return round(float(value), 6)
