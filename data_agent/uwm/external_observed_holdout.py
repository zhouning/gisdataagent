"""External observed holdout suite for UWM state-prediction claims."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .openaq_temporal_benchmark import validate_openaq_observed_temporal_benchmark
from .tap_temporal_benchmark import validate_tap_gridded_temporal_benchmark


UWM_EXTERNAL_OBSERVED_HOLDOUT_SUITE_SCHEMA = "uwm.external_observed_holdout_suite.v1"


def build_uwm_external_observed_holdout_suite(
    *,
    openaq_temporal_benchmark_path: str | Path,
    tap_gridded_temporal_benchmark_path: str | Path,
    suite_id: str,
    created_at: str,
) -> dict[str, Any]:
    """Build an external observed holdout suite from real OpenAQ and TAP benchmarks."""

    openaq_path = Path(openaq_temporal_benchmark_path)
    tap_path = Path(tap_gridded_temporal_benchmark_path)
    openaq_benchmark = _read_json(openaq_path)
    tap_benchmark = _read_json(tap_path)
    openaq_slice = _openaq_station_temporal_holdout_slice(
        openaq_benchmark,
        source_artifact_exists=openaq_path.exists(),
    )
    tap_slice = _tap_gridded_temporal_holdout_slice(
        tap_benchmark,
        source_artifact_exists=tap_path.exists(),
    )
    external_ready = (
        bool(openaq_slice.get("external_holdout_ready"))
        and bool(tap_slice.get("external_holdout_ready"))
    )
    return {
        "schema": UWM_EXTERNAL_OBSERVED_HOLDOUT_SUITE_SCHEMA,
        "suite_id": suite_id,
        "created_at": created_at,
        "source_artifacts": {
            "openaq_temporal_benchmark": str(openaq_path),
            "tap_gridded_temporal_benchmark": str(tap_path),
        },
        "source_dataset_ids": sorted(
            set(openaq_slice.get("source_dataset_ids") or [])
            | set(tap_slice.get("source_dataset_ids") or [])
        ),
        "holdout_sources": {
            "openaq_station_temporal_holdout": openaq_slice,
            "tap_gridded_temporal_holdout": tap_slice,
        },
        "external_observed_holdout_ready": external_ready,
        "external_observed_state_prediction_superiority_claim": external_ready,
        "scene_aligned_station_calibrated_air_quality_holdout_ready": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "supported_claims": _supported_claims(external_ready),
        "claim_boundary": {
            "max_claim_level": "bounded_support" if external_ready else "not_for_claim",
            "policy_outcome_claim": False,
            "rule": (
                "OpenAQ station and TAP gridded holdouts can support external observed "
                "state-prediction superiority over static baselines, but they do not form "
                "a scene-aligned station-calibrated policy outcome holdout."
            ),
        },
        "limitations": [
            "not_policy_intervention_outcome",
            "openaq_not_scene_aligned_to_2024_policy_window",
            "tap_gridded_product_not_station_observation",
            "state_prediction_not_policy_outcome",
            "dynamic_state_update_uses_prior_holdout_observations_online",
        ],
        "remaining_gates": [
            "observed_policy_outcome_required",
            "scene_aligned_station_calibrated_air_quality_holdout_required",
        ],
    }


def validate_uwm_external_observed_holdout_suite(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate claim-safety and minimum evidence conditions."""

    errors: list[str] = []
    if payload.get("schema") != UWM_EXTERNAL_OBSERVED_HOLDOUT_SUITE_SCHEMA:
        errors.append("schema_mismatch")
    if payload.get("observed_policy_outcome_superiority_claim") is not False:
        errors.append("observed_policy_outcome_superiority_claim_must_be_false")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim_must_be_false")
    if payload.get("scene_aligned_station_calibrated_air_quality_holdout_ready") is not False:
        errors.append("scene_aligned_station_calibrated_ready_must_be_false")
    sources = payload.get("holdout_sources") or {}
    openaq = sources.get("openaq_station_temporal_holdout") or {}
    tap = sources.get("tap_gridded_temporal_holdout") or {}
    if payload.get("external_observed_holdout_ready"):
        if not openaq.get("external_holdout_ready"):
            errors.append("openaq_external_holdout_required")
        if not tap.get("external_holdout_ready"):
            errors.append("tap_external_holdout_required")
    for claim in payload.get("supported_claims") or []:
        if claim.get("policy_outcome_claim") is not False:
            errors.append("supported_claim_policy_outcome_must_be_false")
    if "not_policy_intervention_outcome" not in (payload.get("limitations") or []):
        errors.append("not_policy_intervention_outcome_limitation_required")
    return {"valid": not errors, "errors": errors}


def _openaq_station_temporal_holdout_slice(
    benchmark: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    validation = (
        validate_openaq_observed_temporal_benchmark(benchmark)
        if source_artifact_exists
        else {"valid": False, "errors": ["source_artifact_missing"]}
    )
    pm25 = _pollutant_result(benchmark, "pm25")
    best_static = pm25.get("best_traditional_static_baseline") or {}
    sign_tests = benchmark.get("overall_sign_tests") or {}
    temporal_control = benchmark.get("temporal_order_negative_control_summary") or {}
    p_values = [
        _safe_float((sign_tests.get(method) or {}).get("one_sided_p_value"), default=1.0)
        for method in ("static_train_mean", "static_last_train_observation")
    ]
    ready = (
        source_artifact_exists
        and validation.get("valid") is True
        and (benchmark.get("claim_boundary") or {}).get("max_claim_level") == "bounded_support"
        and _safe_int(benchmark.get("observation_count")) >= 100
        and _safe_int(benchmark.get("holdout_count")) >= 30
        and _safe_float(benchmark.get("overall_holdout_win_rate")) > 0.5
        and all(p_value < 0.05 for p_value in p_values)
        and temporal_control.get("all_pollutants_ordered_temporal_state_advantage") is True
    )
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": benchmark.get("schema"),
        "scope": "openaq_station_observed_temporal_holdout_not_scene_policy",
        "source_dataset_ids": benchmark.get("source_dataset_ids") or [],
        "pollutant_count": _safe_int(benchmark.get("pollutant_count")),
        "observation_count": _safe_int(benchmark.get("observation_count")),
        "holdout_count": _safe_int(benchmark.get("holdout_count")),
        "overall_holdout_win_count": _safe_int(benchmark.get("overall_holdout_win_count")),
        "overall_holdout_win_rate": _safe_float(benchmark.get("overall_holdout_win_rate")),
        "overall_sign_tests": sign_tests,
        "best_dynamic_pm25_mae": _safe_float(pm25.get("uwm_dynamic_persistence_mae")),
        "best_static_pm25_mae": _safe_float(best_static.get("mae")),
        "temporal_order_negative_control_passed": bool(
            temporal_control.get("all_pollutants_ordered_temporal_state_advantage")
        ),
        "external_holdout_ready": ready,
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "policy_outcome_claim": False,
        "limitations": benchmark.get("limitations") or [],
        "validation": validation,
    }


def _tap_gridded_temporal_holdout_slice(
    benchmark: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    validation = (
        validate_tap_gridded_temporal_benchmark(benchmark)
        if source_artifact_exists
        else {"valid": False, "errors": ["source_artifact_missing"]}
    )
    overall = benchmark.get("overall_results") or {}
    sign_tests = benchmark.get("overall_sign_tests") or {}
    temporal_control = benchmark.get("temporal_order_negative_control_summary") or {}
    p_values = [
        _safe_float((sign_tests.get(method) or {}).get("one_sided_p_value"), default=1.0)
        for method in ("static_train_mean", "static_last_train_observation", "period_static_mean")
    ]
    ready = (
        source_artifact_exists
        and validation.get("valid") is True
        and (benchmark.get("claim_boundary") or {}).get("max_claim_level") == "bounded_support"
        and _safe_int(overall.get("series_count")) >= 1000
        and _safe_int(overall.get("holdout_count")) >= 1000
        and overall.get("beats_all_traditional_static_baselines") is True
        and _safe_float(overall.get("best_uwm_mae"), default=float("inf"))
        < _safe_float(overall.get("best_static_baseline_mae"), default=0.0)
        and _safe_float(overall.get("series_beats_all_traditional_static_baselines_rate")) > 0.5
        and all(p_value < 0.05 for p_value in p_values)
        and _safe_float(temporal_control.get("ordered_advantage_rate")) > 0.5
    )
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": benchmark.get("schema"),
        "scope": "tap_gridded_observed_temporal_holdout_not_station_policy",
        "source_dataset_ids": benchmark.get("source_dataset_ids") or [],
        "series_count": _safe_int(overall.get("series_count")),
        "holdout_count": _safe_int(overall.get("holdout_count")),
        "best_uwm_method": overall.get("best_uwm_method"),
        "best_static_baseline_method": overall.get("best_static_baseline_method"),
        "best_uwm_mae": _safe_float(overall.get("best_uwm_mae")),
        "best_static_baseline_mae": _safe_float(overall.get("best_static_baseline_mae")),
        "best_uwm_mae_reduction": _safe_float(overall.get("best_uwm_mae_reduction")),
        "series_beats_all_traditional_static_baselines_rate": _safe_float(
            overall.get("series_beats_all_traditional_static_baselines_rate")
        ),
        "overall_sign_tests": sign_tests,
        "temporal_order_negative_control_passed": _safe_float(
            temporal_control.get("ordered_advantage_rate")
        )
        > 0.5,
        "external_holdout_ready": ready,
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "policy_outcome_claim": False,
        "limitations": benchmark.get("limitations") or [],
        "validation": validation,
    }


def _supported_claims(external_ready: bool) -> list[dict[str, Any]]:
    if not external_ready:
        return []
    return [
        {
            "claim": "external_observed_state_prediction_advantage_over_static_baseline_suite",
            "scope": "two_source_external_observed_state_holdout_not_policy_outcome",
            "claim_level": "bounded_support",
            "policy_outcome_claim": False,
            "spatial_attribution_claim": False,
        }
    ]


def _pollutant_result(benchmark: dict[str, Any], pollutant: str) -> dict[str, Any]:
    for result in benchmark.get("per_pollutant_results") or []:
        if result.get("pollutant") == pollutant:
            return result
    return {}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _safe_int(value: Any, default: int = 0) -> int:
    if value in {None, ""}:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value in {None, ""}:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
