"""Observed OpenAQ temporal holdout benchmark for UWM state dynamics."""

from __future__ import annotations

from math import comb
from statistics import mean
from typing import Any


OPENAQ_OBSERVED_TEMPORAL_BENCHMARK_SCHEMA = "uwm.openaq_observed_temporal_benchmark.v1"
TRADITIONAL_STATIC_BASELINE_SUITE = [
    "static_train_mean",
    "static_last_train_observation",
]


def build_openaq_observed_temporal_benchmark(
    *,
    sensor_measurement_payloads: dict[str, dict[str, Any]],
    benchmark_id: str,
    created_at: str,
    train_fraction: float = 0.7,
) -> dict[str, Any]:
    """Compare dynamic persistence with a static mean baseline on observed station time series."""

    series_by_pollutant = _series_by_pollutant(sensor_measurement_payloads)
    per_pollutant = []
    for pollutant, rows in sorted(series_by_pollutant.items()):
        result = _benchmark_series(pollutant, rows, train_fraction)
        if result:
            per_pollutant.append(result)
    observation_count = sum(result["observation_count"] for result in per_pollutant)
    holdout_count = sum(result["holdout_count"] for result in per_pollutant)
    holdout_win_count = sum(result["holdout_win_count"] for result in per_pollutant)
    advantage = bool(per_pollutant) and all(result["dynamic_advantage_over_static_mean"] for result in per_pollutant)
    suite_advantage = bool(per_pollutant) and all(
        result["beats_all_traditional_static_baselines"] for result in per_pollutant
    )
    return {
        "schema": OPENAQ_OBSERVED_TEMPORAL_BENCHMARK_SCHEMA,
        "version": "0.1",
        "benchmark_id": benchmark_id,
        "created_at": created_at,
        "source_dataset_ids": ["openaq_air_quality_station_observation_proxy"],
        "traditional_baseline_suite": TRADITIONAL_STATIC_BASELINE_SUITE,
        "pollutant_count": len(per_pollutant),
        "observation_count": observation_count,
        "holdout_count": holdout_count,
        "overall_holdout_win_rate": round(holdout_win_count / holdout_count, 6) if holdout_count else 0.0,
        "overall_holdout_win_count": holdout_win_count,
        "overall_sign_tests": _overall_sign_tests(per_pollutant),
        "temporal_order_negative_control_summary": _temporal_order_negative_control_summary(per_pollutant),
        "per_pollutant_results": per_pollutant,
        "observed_temporal_state_advantage_over_static_baseline": advantage,
        "observed_temporal_state_advantage_over_static_baseline_suite": suite_advantage,
        "supported_claim": (
            "observed_temporal_state_prediction_advantage_over_static_baseline_suite"
            if suite_advantage
            else "observed_temporal_state_prediction_advantage_over_static_mean_baseline"
            if advantage
            else "no_observed_temporal_state_advantage_claim"
        ),
        "claim_boundary": {
            "max_claim_level": "bounded_support" if advantage else "not_for_claim",
            "reason": (
                "OpenAQ observed holdout supports temporal state-prediction comparison only; "
                "it is not a policy intervention outcome benchmark."
            ),
        },
        "limitations": [
            "not_policy_intervention_outcome",
            "single_station_sensor_sample",
            "short_historical_holdout_window",
            "dynamic_persistence_is_baseline_world_model_state_update",
        ],
        "empirical_superiority_claim": False,
    }


def validate_openaq_observed_temporal_benchmark(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate OpenAQ temporal benchmark payload."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != OPENAQ_OBSERVED_TEMPORAL_BENCHMARK_SCHEMA:
        errors.append(f"schema must be {OPENAQ_OBSERVED_TEMPORAL_BENCHMARK_SCHEMA}")
    for key in [
        "benchmark_id",
        "pollutant_count",
        "observation_count",
        "holdout_count",
        "per_pollutant_results",
        "observed_temporal_state_advantage_over_static_baseline",
        "claim_boundary",
        "limitations",
    ]:
        if key not in payload:
            errors.append(f"{key} is required")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim must stay false for non-policy temporal benchmark")
    claim = payload.get("claim_boundary") or {}
    if not isinstance(claim, dict) or not claim.get("max_claim_level"):
        errors.append("claim_boundary.max_claim_level is required")
    return {"valid": not errors, "errors": errors}


def _series_by_pollutant(payloads: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for payload in payloads.values():
        for row in payload.get("results") or []:
            parameter = row.get("parameter") or {}
            pollutant = str(parameter.get("name") or "").lower()
            value = _float(row.get("value"))
            timestamp = _timestamp(row)
            if not pollutant or value is None or not timestamp:
                continue
            grouped.setdefault(pollutant, []).append({"timestamp": timestamp, "value": value})
    for rows in grouped.values():
        rows.sort(key=lambda item: item["timestamp"])
    return grouped


def _benchmark_series(
    pollutant: str,
    rows: list[dict[str, Any]],
    train_fraction: float,
) -> dict[str, Any]:
    if len(rows) < 4:
        return {}
    split = max(2, min(len(rows) - 1, int(len(rows) * train_fraction)))
    train = rows[:split]
    holdout = rows[split:]
    if not holdout:
        return {}
    train_values = [row["value"] for row in train]
    holdout_values = [row["value"] for row in holdout]
    static_prediction = mean(train_values)
    dynamic_predictions = [train_values[-1]] + holdout_values[:-1]
    dynamic_errors = [abs(value - prediction) for value, prediction in zip(holdout_values, dynamic_predictions)]
    dynamic_mae = round(mean(dynamic_errors), 6)
    baseline_suite = _traditional_static_baseline_suite(
        train_values=train_values,
        holdout_values=holdout_values,
        dynamic_errors=dynamic_errors,
    )
    best_baseline = min(
        (baseline_suite[method] for method in TRADITIONAL_STATIC_BASELINE_SUITE),
        key=lambda item: item["mae"],
    )
    static_mae = baseline_suite["static_train_mean"]["mae"]
    mae_reduction = round(static_mae - dynamic_mae, 6)
    win_count = baseline_suite["static_train_mean"]["dynamic_win_count"]
    return {
        "pollutant": pollutant,
        "observation_count": len(rows),
        "train_count": len(train),
        "holdout_count": len(holdout),
        "time_range": {"start": rows[0]["timestamp"], "end": rows[-1]["timestamp"]},
        "static_mean_baseline_mae": static_mae,
        "uwm_dynamic_persistence_mae": dynamic_mae,
        "mae_reduction": mae_reduction,
        "mae_reduction_fraction": round(mae_reduction / static_mae, 6) if static_mae else 0.0,
        "holdout_win_count": win_count,
        "holdout_win_rate": round(win_count / len(holdout_values), 6) if holdout_values else 0.0,
        "dynamic_advantage_over_static_mean": mae_reduction > 0,
        "traditional_static_baseline_suite": baseline_suite,
        "best_traditional_static_baseline": best_baseline,
        "uwm_dynamic_state_update": {
            "method": "online_persistence_state_update",
            "mae": dynamic_mae,
            "uses_prior_holdout_observations_online": True,
            "uses_current_or_future_holdout_labels": False,
        },
        "temporal_order_negative_control": _temporal_order_negative_control(
            train_values=train_values,
            holdout_values=holdout_values,
            ordered_dynamic_mae=dynamic_mae,
        ),
        "beats_all_traditional_static_baselines": all(
            dynamic_mae < baseline_suite[method]["mae"] for method in TRADITIONAL_STATIC_BASELINE_SUITE
        ),
    }


def _traditional_static_baseline_suite(
    *,
    train_values: list[float],
    holdout_values: list[float],
    dynamic_errors: list[float],
) -> dict[str, dict[str, Any]]:
    predictions_by_method = {
        "static_train_mean": [mean(train_values)] * len(holdout_values),
        "static_last_train_observation": [train_values[-1]] * len(holdout_values),
    }
    suite = {}
    for method in TRADITIONAL_STATIC_BASELINE_SUITE:
        predictions = predictions_by_method[method]
        errors = [abs(value - prediction) for value, prediction in zip(holdout_values, predictions)]
        mae = round(mean(errors), 6)
        win_count = len(
            [
                1
                for static_error, dynamic_error in zip(errors, dynamic_errors)
                if dynamic_error < static_error
            ]
        )
        suite[method] = {
            "method": method,
            "mae": mae,
            "dynamic_mae_reduction": round(mae - mean(dynamic_errors), 6),
            "dynamic_win_count": win_count,
            "dynamic_win_rate": round(win_count / len(holdout_values), 6) if holdout_values else 0.0,
            "dynamic_sign_test": _dynamic_sign_test(errors, dynamic_errors),
        }
    return suite


def _overall_sign_tests(per_pollutant: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        method: _aggregate_sign_tests(
            [
                result["traditional_static_baseline_suite"][method]["dynamic_sign_test"]
                for result in per_pollutant
            ]
        )
        for method in TRADITIONAL_STATIC_BASELINE_SUITE
    }


def _temporal_order_negative_control_summary(per_pollutant: list[dict[str, Any]]) -> dict[str, Any]:
    controls = [result["temporal_order_negative_control"] for result in per_pollutant]
    ordered_advantage_count = len(
        [control for control in controls if control["ordered_temporal_state_advantage"]]
    )
    advantages = [float(control["ordered_mae_advantage"]) for control in controls]
    return {
        "pollutant_count": len(controls),
        "ordered_advantage_count": ordered_advantage_count,
        "ordered_advantage_rate": round(ordered_advantage_count / len(controls), 6) if controls else 0.0,
        "mean_ordered_mae_advantage": round(mean(advantages), 6) if advantages else 0.0,
        "all_pollutants_ordered_temporal_state_advantage": bool(controls)
        and ordered_advantage_count == len(controls),
    }


def _temporal_order_negative_control(
    *,
    train_values: list[float],
    holdout_values: list[float],
    ordered_dynamic_mae: float,
) -> dict[str, Any]:
    rotation = len(holdout_values) // 2
    shuffled_holdout = _rotate_values(holdout_values, rotation)
    shuffled_predictions = [train_values[-1]] + shuffled_holdout[:-1]
    shuffled_errors = [
        abs(value - prediction)
        for value, prediction in zip(shuffled_holdout, shuffled_predictions)
    ]
    shuffled_dynamic_mae = round(mean(shuffled_errors), 6)
    ordered_mae_advantage = round(shuffled_dynamic_mae - ordered_dynamic_mae, 6)
    return {
        "method": "deterministic_holdout_order_rotation",
        "rotation": rotation,
        "shuffled_dynamic_mae": shuffled_dynamic_mae,
        "ordered_dynamic_mae": ordered_dynamic_mae,
        "ordered_mae_advantage": ordered_mae_advantage,
        "ordered_temporal_state_advantage": ordered_mae_advantage > 0,
    }


def _rotate_values(values: list[float], rotation: int) -> list[float]:
    if not values:
        return []
    offset = rotation % len(values)
    if offset == 0:
        return list(reversed(values))
    return values[offset:] + values[:offset]


def _dynamic_sign_test(static_errors: list[float], dynamic_errors: list[float]) -> dict[str, Any]:
    wins = 0
    losses = 0
    ties = 0
    for static_error, dynamic_error in zip(static_errors, dynamic_errors):
        if dynamic_error < static_error:
            wins += 1
        elif dynamic_error > static_error:
            losses += 1
        else:
            ties += 1
    return _sign_test_result(wins=wins, losses=losses, ties=ties)


def _aggregate_sign_tests(sign_tests: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(int(test.get("wins", 0)) for test in sign_tests)
    losses = sum(int(test.get("losses", 0)) for test in sign_tests)
    ties = sum(int(test.get("ties", 0)) for test in sign_tests)
    return _sign_test_result(wins=wins, losses=losses, ties=ties)


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


def _timestamp(row: dict[str, Any]) -> str:
    period = row.get("period") or {}
    datetime_from = period.get("datetimeFrom") or {}
    if datetime_from.get("utc"):
        return str(datetime_from["utc"])
    datetime_row = row.get("datetime") or {}
    return str(datetime_row.get("utc") or "")


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
