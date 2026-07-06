"""TAP gridded temporal state-prediction benchmark for UWM."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import defaultdict
from math import comb
from pathlib import Path
from statistics import fmean
from typing import Any


TAP_GRIDDED_TEMPORAL_BENCHMARK_SCHEMA = "uwm.tap_gridded_temporal_benchmark.v1"
TRADITIONAL_STATIC_BASELINE_SUITE = [
    "static_train_mean",
    "static_last_train_observation",
    "period_static_mean",
]
UWM_STATE_UPDATE_SUITE = [
    "online_persistence_state_update",
    "adaptive_online_state_update",
]


def build_tap_gridded_temporal_benchmark(
    *,
    tap_root: str | Path,
    benchmark_id: str,
    created_at: str,
    train_days: int = 3,
    max_grid_series_per_period: int = 5000,
) -> dict[str, Any]:
    root = Path(tap_root)
    if not root.exists():
        raise FileNotFoundError(f"TAP root not found: {root}")
    period_results = [
        _benchmark_period(path, train_days=train_days, max_series=max_grid_series_per_period)
        for path in _period_dirs(root)
    ]
    period_results = [result for result in period_results if result["series_count"] > 0]
    if not period_results:
        raise ValueError("no benchmarkable TAP grid series found")
    overall = _overall_results(period_results)
    return {
        "schema": TAP_GRIDDED_TEMPORAL_BENCHMARK_SCHEMA,
        "version": "0.1",
        "benchmark_id": benchmark_id,
        "created_at": created_at,
        "source_dataset_ids": ["tap_pm25_observed_gridded_chongqing_2018_2024"],
        "traditional_baseline_suite": TRADITIONAL_STATIC_BASELINE_SUITE,
        "uwm_state_update_suite": UWM_STATE_UPDATE_SUITE,
        "state_update_parameters": {"adaptive_online_state_update_alpha": 0.7},
        "period_results": period_results,
        "overall_results": overall,
        "overall_sign_tests": _overall_sign_tests(period_results),
        "temporal_order_negative_control_summary": _negative_control_summary(period_results),
        "supported_claim": (
            "tap_gridded_temporal_state_prediction_advantage_over_static_baseline"
            if overall["beats_all_traditional_static_baselines"]
            else "no_tap_gridded_temporal_state_prediction_advantage_claim"
        ),
        "claim_boundary": {
            "max_claim_level": "bounded_support" if overall["beats_all_traditional_static_baselines"] else "not_for_claim",
            "reason": (
                "TAP gridded PM2.5 supports temporal state-prediction comparison over static baselines; "
                "it is not a station-observed policy intervention outcome benchmark."
            ),
        },
        "limitations": [
            "tap_gridded_product_not_station_observation",
            "not_policy_intervention_outcome",
            "short_daily_holdout_window",
            "sampled_grid_series_for_runtime_control",
        ],
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def validate_tap_gridded_temporal_benchmark(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != TAP_GRIDDED_TEMPORAL_BENCHMARK_SCHEMA:
        errors.append(f"schema must be {TAP_GRIDDED_TEMPORAL_BENCHMARK_SCHEMA}")
    for key in ["benchmark_id", "period_results", "overall_results", "claim_boundary", "limitations"]:
        if key not in payload:
            errors.append(f"{key} is required")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim must stay false for TAP temporal benchmark")
    if payload.get("observed_policy_outcome_superiority_claim") is not False:
        errors.append("observed_policy_outcome_superiority_claim must stay false")
    if "not_policy_intervention_outcome" not in (payload.get("limitations") or []):
        errors.append("limitations must include not_policy_intervention_outcome")
    claim = payload.get("claim_boundary") or {}
    if not isinstance(claim, dict) or not claim.get("max_claim_level"):
        errors.append("claim_boundary.max_claim_level is required")
    return {"valid": not errors, "errors": errors}


def _benchmark_period(path: Path, *, train_days: int, max_series: int) -> dict[str, Any]:
    series = _load_period_series(path)
    selected_keys = sorted(series)[:max_series]
    selected = {key: series[key] for key in selected_keys}
    period_train_values = [
        row["value"]
        for rows in selected.values()
        for row in sorted(rows, key=lambda item: item["doy"])[:train_days]
    ]
    period_train_mean = fmean(period_train_values) if period_train_values else 0.0
    series_results = []
    for key, rows in selected.items():
        result = _benchmark_series(key, sorted(rows, key=lambda item: item["doy"]), train_days, period_train_mean)
        if result:
            series_results.append(result)
    return _period_result(path.name, series_results)


def _load_period_series(path: Path) -> dict[tuple[str, str], list[dict[str, Any]]]:
    downloaded = path / "downloaded"
    series: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for pm_file in sorted(downloaded.glob("China_PM25_1km_*.csv.zip")):
        year, doy, tile_id = _parse_pm25_filename(pm_file)
        for row in _read_single_csv_zip(pm_file):
            grid_id = str(row.get("GridID") or "").strip()
            value = _float(row.get("PM2.5"))
            if not grid_id or value is None:
                continue
            series[(tile_id, grid_id)].append({"year": year, "doy": doy, "value": value})
    return series


def _benchmark_series(
    key: tuple[str, str],
    rows: list[dict[str, Any]],
    train_days: int,
    period_train_mean: float,
) -> dict[str, Any]:
    if len(rows) <= train_days:
        return {}
    train = rows[:train_days]
    holdout = rows[train_days:]
    train_values = [row["value"] for row in train]
    holdout_values = [row["value"] for row in holdout]
    online_predictions = [train_values[-1]] + holdout_values[:-1]
    adaptive_predictions = _adaptive_predictions(train_values, holdout_values, alpha=0.7)
    online_errors = _errors(holdout_values, online_predictions)
    adaptive_errors = _errors(holdout_values, adaptive_predictions)
    baselines = _baseline_suite(train_values, holdout_values, period_train_mean, online_errors)
    online_mae = _mean(online_errors)
    adaptive_mae = _mean(adaptive_errors)
    best_uwm_method = "online_persistence_state_update" if online_mae <= adaptive_mae else "adaptive_online_state_update"
    best_uwm_errors = online_errors if best_uwm_method == "online_persistence_state_update" else adaptive_errors
    best_static = min(baselines.values(), key=lambda item: item["mae"])
    return {
        "tile_id": key[0],
        "grid_id": key[1],
        "observation_count": len(rows),
        "train_count": len(train),
        "holdout_count": len(holdout),
        "time_range": {"start_doy": rows[0]["doy"], "end_doy": rows[-1]["doy"]},
        "uwm_state_updates": {
            "online_persistence_state_update": {
                "mae": _round(online_mae),
                "uses_prior_holdout_observations_online": True,
                "uses_current_or_future_holdout_labels": False,
            },
            "adaptive_online_state_update": {
                "mae": _round(adaptive_mae),
                "alpha": 0.7,
                "uses_prior_holdout_observations_online": True,
                "uses_current_or_future_holdout_labels": False,
            },
        },
        "best_uwm_method": best_uwm_method,
        "best_uwm_mae": _round(_mean(best_uwm_errors)),
        "traditional_static_baseline_suite": baselines,
        "best_traditional_static_baseline": best_static,
        "best_uwm_mae_reduction": _round(best_static["mae"] - _mean(best_uwm_errors)),
        "beats_all_traditional_static_baselines": all(_mean(best_uwm_errors) < row["mae"] for row in baselines.values()),
        "dynamic_sign_tests": {name: _dynamic_sign_test(row["errors"], best_uwm_errors) for name, row in baselines.items()},
        "temporal_order_negative_control": _negative_control(train_values, holdout_values, _mean(best_uwm_errors)),
    }


def _period_result(period_id: str, series_results: list[dict[str, Any]]) -> dict[str, Any]:
    holdout_count = sum(row["holdout_count"] for row in series_results)
    best_uwm_errors = [row["best_uwm_mae"] for row in series_results]
    best_static_errors = [row["best_traditional_static_baseline"]["mae"] for row in series_results]
    return {
        "period_id": period_id,
        "series_count": len(series_results),
        "holdout_count": holdout_count,
        "series_results": series_results,
        "best_uwm_mae": _round(fmean(best_uwm_errors)) if best_uwm_errors else None,
        "best_static_baseline_mae": _round(fmean(best_static_errors)) if best_static_errors else None,
        "beats_all_traditional_static_baselines": bool(series_results) and all(row["beats_all_traditional_static_baselines"] for row in series_results),
    }


def _baseline_suite(train_values: list[float], holdout_values: list[float], period_train_mean: float, dynamic_errors: list[float]) -> dict[str, dict[str, Any]]:
    predictions = {
        "static_train_mean": [fmean(train_values)] * len(holdout_values),
        "static_last_train_observation": [train_values[-1]] * len(holdout_values),
        "period_static_mean": [period_train_mean] * len(holdout_values),
    }
    suite = {}
    for method in TRADITIONAL_STATIC_BASELINE_SUITE:
        errors = _errors(holdout_values, predictions[method])
        suite[method] = {
            "method": method,
            "mae": _round(_mean(errors)),
            "errors": errors,
            "dynamic_mae_reduction": _round(_mean(errors) - _mean(dynamic_errors)),
            "dynamic_win_count": len([1 for static_error, dynamic_error in zip(errors, dynamic_errors) if dynamic_error < static_error]),
        }
    return suite


def _overall_results(period_results: list[dict[str, Any]]) -> dict[str, Any]:
    series_results = [series for period in period_results for series in period["series_results"]]
    best_uwm_method_counts: dict[str, int] = defaultdict(int)
    for series in series_results:
        best_uwm_method_counts[series["best_uwm_method"]] += 1
    best_method = max(best_uwm_method_counts, key=best_uwm_method_counts.get) if best_uwm_method_counts else ""
    best_uwm_maes = [series["best_uwm_mae"] for series in series_results]
    best_static_maes = [series["best_traditional_static_baseline"]["mae"] for series in series_results]
    best_uwm_mae = _round(fmean(best_uwm_maes)) if best_uwm_maes else None
    best_static_mae = _round(fmean(best_static_maes)) if best_static_maes else None
    return {
        "series_count": len(series_results),
        "holdout_count": sum(series["holdout_count"] for series in series_results),
        "best_uwm_method": best_method,
        "best_uwm_mae": best_uwm_mae,
        "best_static_baseline_mae": best_static_mae,
        "best_uwm_mae_reduction": _round(best_static_mae - best_uwm_mae) if best_uwm_mae is not None and best_static_mae is not None else None,
        "beats_all_traditional_static_baselines": bool(series_results) and all(series["beats_all_traditional_static_baselines"] for series in series_results),
    }


def _overall_sign_tests(period_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    series_results = [series for period in period_results for series in period["series_results"]]
    return {
        method: _aggregate_sign_tests([series["dynamic_sign_tests"][method] for series in series_results])
        for method in TRADITIONAL_STATIC_BASELINE_SUITE
    }


def _negative_control_summary(period_results: list[dict[str, Any]]) -> dict[str, Any]:
    controls = [
        series["temporal_order_negative_control"]
        for period in period_results
        for series in period["series_results"]
    ]
    advantage_count = len([control for control in controls if control["ordered_temporal_state_advantage"]])
    return {
        "series_count": len(controls),
        "ordered_advantage_count": advantage_count,
        "ordered_advantage_rate": _round(advantage_count / len(controls)) if controls else 0.0,
    }


def _adaptive_predictions(train_values: list[float], holdout_values: list[float], *, alpha: float) -> list[float]:
    anchor = fmean(train_values)
    previous = train_values[-1]
    predictions = []
    for value in holdout_values:
        prediction = alpha * previous + (1.0 - alpha) * anchor
        predictions.append(prediction)
        previous = value
    return predictions


def _negative_control(train_values: list[float], holdout_values: list[float], ordered_mae: float) -> dict[str, Any]:
    rotated = _rotate(holdout_values)
    predictions = [train_values[-1]] + rotated[:-1]
    rotated_mae = _mean(_errors(rotated, predictions))
    return {
        "method": "deterministic_holdout_order_rotation",
        "rotated_dynamic_mae": _round(rotated_mae),
        "ordered_dynamic_mae": _round(ordered_mae),
        "ordered_mae_advantage": _round(rotated_mae - ordered_mae),
        "ordered_temporal_state_advantage": rotated_mae > ordered_mae,
    }


def _rotate(values: list[float]) -> list[float]:
    if not values:
        return []
    offset = len(values) // 2
    if offset == 0:
        return list(reversed(values))
    return values[offset:] + values[:offset]


def _errors(values: list[float], predictions: list[float]) -> list[float]:
    return [abs(value - prediction) for value, prediction in zip(values, predictions)]


def _dynamic_sign_test(static_errors: list[float], dynamic_errors: list[float]) -> dict[str, Any]:
    wins = losses = ties = 0
    for static_error, dynamic_error in zip(static_errors, dynamic_errors):
        if dynamic_error < static_error:
            wins += 1
        elif dynamic_error > static_error:
            losses += 1
        else:
            ties += 1
    return _sign_test_result(wins=wins, losses=losses, ties=ties)


def _aggregate_sign_tests(sign_tests: list[dict[str, Any]]) -> dict[str, Any]:
    return _sign_test_result(
        wins=sum(int(test.get("wins", 0)) for test in sign_tests),
        losses=sum(int(test.get("losses", 0)) for test in sign_tests),
        ties=sum(int(test.get("ties", 0)) for test in sign_tests),
    )


def _sign_test_result(*, wins: int, losses: int, ties: int) -> dict[str, Any]:
    effective_n = wins + losses
    return {
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "effective_n": effective_n,
        "one_sided_p_value": _one_sided_sign_test_p_value(wins, effective_n),
    }


def _one_sided_sign_test_p_value(wins: int, effective_n: int) -> float:
    if effective_n <= 0:
        return 1.0
    favorable = sum(comb(effective_n, k) for k in range(wins, effective_n + 1))
    return favorable / (2**effective_n)


def _period_dirs(root: Path) -> list[Path]:
    return sorted(path for path in root.iterdir() if path.is_dir() and path.name.startswith("chongqing_pm25_"))


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


def _mean(values: list[float]) -> float:
    return fmean(values) if values else 0.0


def _round(value: Any) -> float:
    return round(float(value), 6)
