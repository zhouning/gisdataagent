"""Data-calibrated simulator mechanism table for UWM.

The table replaces hard-coded simulator coefficients with values scaled from
prepared real/proxy evidence. It is not an observed policy outcome model.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


UWM_DATA_CALIBRATED_MECHANISM_TABLE_SCHEMA = "uwm.data_calibrated_mechanism_table.v1"

BASE_MECHANISM_COEFFICIENTS = {
    "increase_green_infrastructure": {
        "heat_risk_delta": -0.18,
        "air_pollution_exposure_delta": -0.05,
        "service_accessibility_delta": 0.02,
        "equity_delta": 0.04,
    },
    "cool_roofs": {
        "heat_risk_delta": -0.12,
        "air_pollution_exposure_delta": 0.0,
        "service_accessibility_delta": 0.0,
        "equity_delta": 0.02,
    },
    "traffic_emission_control": {
        "heat_risk_delta": 0.0,
        "air_pollution_exposure_delta": -0.16,
        "service_accessibility_delta": 0.0,
        "equity_delta": 0.03,
    },
    "add_community_service": {
        "heat_risk_delta": 0.0,
        "air_pollution_exposure_delta": 0.0,
        "service_accessibility_delta": 0.18,
        "equity_delta": 0.06,
    },
}


def build_uwm_data_calibrated_mechanism_table(
    *,
    evidence_gate_path: str | Path,
    noaa_weather_path: str | Path,
    admin_livability_panel_path: str | Path,
    table_id: str,
    created_at: str,
) -> dict[str, Any]:
    """Build a claim-gated mechanism table from prepared real evidence artifacts."""

    evidence_gate = _read_json(evidence_gate_path)
    noaa_weather = _read_json(noaa_weather_path)
    admin_panel = _read_json(admin_livability_panel_path)
    evidence_slices = evidence_gate.get("evidence_slices") or {}
    openaq = evidence_slices.get("openaq_observed_temporal_state") or {}
    tap = evidence_slices.get("tap_external_temporal_transition") or {}
    station = evidence_slices.get("station_aligned_air_quality_holdout") or {}
    noaa_counts = noaa_weather.get("record_counts") or {}
    noaa_summary = noaa_weather.get("summary") or {}
    admin_rows = list(admin_panel.get("admin_livability_target_rows") or [])

    air_scale = _air_quality_scale(openaq, tap, station)
    heat_scale = _heat_scale(noaa_summary)
    service_scale = _service_scale(admin_rows)
    equity_scale = _equity_scale(admin_rows)
    coefficients = _scaled_mechanism_coefficients(
        air_scale=air_scale,
        heat_scale=heat_scale,
        service_scale=service_scale,
        equity_scale=equity_scale,
    )
    ready = (
        bool(openaq.get("source_artifact_exists"))
        and bool(tap.get("source_artifact_exists"))
        and bool(station.get("source_artifact_exists"))
        and _int(noaa_counts.get("records_in_time_window")) > 0
        and len(admin_rows) > 0
        and bool(openaq.get("temporal_order_negative_control_passed"))
        and bool(tap.get("temporal_order_negative_control_passed"))
        and station.get("historical_station_aligned_holdout_ready") is True
        and evidence_gate.get("observed_policy_outcome_superiority_claim") is False
    )
    return {
        "schema": UWM_DATA_CALIBRATED_MECHANISM_TABLE_SCHEMA,
        "table_id": table_id,
        "created_at": created_at,
        "source_artifacts": {
            "data_foundation_evidence_gate": str(evidence_gate_path),
            "noaa_weather": str(noaa_weather_path),
            "admin_livability_panel": str(admin_livability_panel_path),
        },
        "source_dataset_ids": [
            "openaq_air_quality_station_observation_proxy",
            "tap_pm25_observed_gridded_chongqing_2018_2024",
            "noaa_isd_chongqing_weather_observation_2024_07",
            "admin_livability_target_complete_bbox_2024_07",
        ],
        "calibration_evidence": {
            "openaq_observation_count": _int(openaq.get("observation_count")),
            "openaq_holdout_count": _int(openaq.get("holdout_count")),
            "openaq_pm25_dynamic_mae": _round(openaq.get("pm25_dynamic_mae")),
            "openaq_pm25_best_static_mae": _round(openaq.get("pm25_best_static_mae")),
            "tap_holdout_count": _int(tap.get("holdout_count")),
            "tap_best_transition_mae": _round(tap.get("best_transition_mae")),
            "tap_best_static_mae": _round(tap.get("best_traditional_static_mae")),
            "tap_best_non_spatial_dynamic_mae": _round(
                tap.get("best_non_spatial_dynamic_mae")
            ),
            "station_aligned_observation_count": _int(
                station.get("station_observation_count")
            ),
            "station_aligned_raw_tap_mae": _round(station.get("raw_tap_mae")),
            "station_aligned_best_static_mae": _round(
                min(
                    _float(station.get("static_train_mean_mae"), default=0.0),
                    _float(station.get("static_last_observation_mae"), default=0.0),
                )
            ),
            "noaa_scene_observation_count": _int(noaa_counts.get("records_in_time_window")),
            "noaa_temperature_range_c": _round(
                _float(noaa_summary.get("air_temperature_max_c"))
                - _float(noaa_summary.get("air_temperature_min_c"))
            ),
            "admin_livability_row_count": len(admin_rows),
            "admin_service_gap_mean": _round(_mean_score_component(admin_rows, "service_gap_norm")),
            "admin_livability_need_mean": _round(_mean_field(admin_rows, "livability_need_score")),
            "air_quality_observed_advantage_over_static": bool(
                openaq.get("pm25_dynamic_mae")
                and _float(openaq.get("pm25_dynamic_mae"))
                < _float(openaq.get("pm25_best_static_mae"))
            ),
            "external_temporal_transition_claim": bool(
                evidence_gate.get("external_temporal_transition_superiority_claim")
            ),
            "observed_policy_outcome_ready": bool(
                evidence_gate.get("observed_policy_outcome_superiority_claim")
            ),
        },
        "calibration_scales": {
            "air_pollution_scale": _round(air_scale),
            "heat_scale": _round(heat_scale),
            "service_scale": _round(service_scale),
            "equity_scale": _round(equity_scale),
        },
        "mechanism_coefficients": coefficients,
        "traditional_baseline_comparison": {
            "traditional_baseline": "static_indicator_overlay_and_hardcoded_simulator_coefficients",
            "observed_state_prediction_superiority_claim": bool(
                evidence_gate.get("observed_state_prediction_superiority_claim")
            ),
            "external_temporal_transition_superiority_claim": bool(
                evidence_gate.get("external_temporal_transition_superiority_claim")
            ),
            "mechanism_policy_outcome_superiority_claim": False,
            "comparison_boundary": (
                "Real observed state and transition holdouts calibrate mechanism scales; "
                "they do not observe implemented policy effects."
            ),
        },
        "data_calibrated_mechanism_ready": ready,
        "hardcoded_mechanism_replacement_ready": ready,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "supported_claims": [
            {
                "claim": "data_calibrated_simulator_mechanism_replaces_hardcoded_coefficients",
                "scope": "simulator_mechanism_table_calibrated_from_real_state_transition_evidence_not_policy_outcome",
                "claim_level": "bounded_support" if ready else "not_for_claim",
                "policy_outcome_claim": False,
                "spatial_attribution_claim": False,
            }
        ]
        if ready
        else [],
        "claim_boundary": {
            "max_claim_level": "bounded_support" if ready else "not_for_claim",
            "policy_outcome_claim": False,
            "reason": (
                "Mechanism coefficients are calibrated from observed state/transition evidence "
                "and public/local proxy panels; observed policy outcome gates remain open."
            ),
        },
        "limitations": [
            "not_observed_policy_intervention_outcome",
            "action_effects_are_scaled_mechanism_priors_not_causal_policy_effects",
            "air_quality_evidence_is_observed_state_transition_not_intervention",
            "service_and_equity_scales_use_proxy_admin_livability_panel",
        ],
        "remaining_gates": [
            "observed_policy_outcome_required",
            "scene_aligned_station_calibrated_air_quality_holdout_required",
            "synthetic_proxy_boundary_must_remain_visible",
        ],
    }


def validate_uwm_data_calibrated_mechanism_table(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate mechanism table schema and claim boundaries."""

    errors: list[str] = []
    if payload.get("schema") != UWM_DATA_CALIBRATED_MECHANISM_TABLE_SCHEMA:
        errors.append("schema_mismatch")
    if payload.get("observed_policy_outcome_superiority_claim") is not False:
        errors.append("observed_policy_outcome_superiority_claim_must_be_false")
    if payload.get("empirical_superiority_claim") is not False:
        errors.append("empirical_superiority_claim_must_be_false")
    coefficients = payload.get("mechanism_coefficients") or {}
    for action_type in [
        "increase_green_infrastructure",
        "cool_roofs",
        "traffic_emission_control",
        "add_community_service",
    ]:
        action_coefficients = coefficients.get(action_type) or {}
        for key in [
            "heat_risk_delta",
            "air_pollution_exposure_delta",
            "service_accessibility_delta",
            "equity_delta",
        ]:
            if key not in action_coefficients:
                errors.append(f"{action_type}_{key}_missing")
    if payload.get("data_calibrated_mechanism_ready"):
        if (payload.get("claim_boundary") or {}).get("max_claim_level") != "bounded_support":
            errors.append("ready_table_requires_bounded_support_claim_level")
        if not (payload.get("supported_claims") or []):
            errors.append("ready_table_requires_supported_claim")
    for claim in payload.get("supported_claims") or []:
        if claim.get("policy_outcome_claim") is not False:
            errors.append("supported_claim_policy_outcome_must_be_false")
    return {"valid": not errors, "errors": errors}


def _scaled_mechanism_coefficients(
    *,
    air_scale: float,
    heat_scale: float,
    service_scale: float,
    equity_scale: float,
) -> dict[str, dict[str, float]]:
    table: dict[str, dict[str, float]] = {}
    for action_type, coefficients in BASE_MECHANISM_COEFFICIENTS.items():
        table[action_type] = {
            "heat_risk_delta": _round(coefficients["heat_risk_delta"] * heat_scale),
            "air_pollution_exposure_delta": _round(
                coefficients["air_pollution_exposure_delta"] * air_scale
            ),
            "service_accessibility_delta": _round(
                coefficients["service_accessibility_delta"] * service_scale
            ),
            "equity_delta": _round(coefficients["equity_delta"] * equity_scale),
        }
    return table


def _air_quality_scale(
    openaq: dict[str, Any],
    tap: dict[str, Any],
    station: dict[str, Any],
) -> float:
    improvements = [
        _reduction_fraction(openaq.get("pm25_best_static_mae"), openaq.get("pm25_dynamic_mae")),
        _reduction_fraction(tap.get("best_traditional_static_mae"), tap.get("best_transition_mae")),
        _reduction_fraction(
            min(
                _float(station.get("static_train_mean_mae"), default=0.0),
                _float(station.get("static_last_observation_mae"), default=0.0),
            ),
            station.get("raw_tap_mae"),
        ),
    ]
    improvements = [value for value in improvements if value > 0]
    return 1.0 + min(0.35, sum(improvements) / len(improvements) if improvements else 0.0)


def _heat_scale(noaa_summary: dict[str, Any]) -> float:
    temperature_range = _float(noaa_summary.get("air_temperature_max_c")) - _float(
        noaa_summary.get("air_temperature_min_c")
    )
    return 1.0 + min(0.30, max(0.0, (temperature_range - 8.0) / 20.0))


def _service_scale(admin_rows: list[dict[str, Any]]) -> float:
    return 1.0 + min(0.30, max(0.0, _mean_score_component(admin_rows, "service_gap_norm") * 0.30))


def _equity_scale(admin_rows: list[dict[str, Any]]) -> float:
    return 1.0 + min(0.25, max(0.0, _mean_field(admin_rows, "livability_need_score") * 0.25))


def _reduction_fraction(baseline: Any, candidate: Any) -> float:
    baseline_value = _float(baseline)
    candidate_value = _float(candidate)
    if baseline_value <= 0:
        return 0.0
    return max(0.0, (baseline_value - candidate_value) / baseline_value)


def _mean_score_component(rows: list[dict[str, Any]], key: str) -> float:
    values = [
        _float((row.get("score_components") or {}).get(key))
        for row in rows
        if isinstance(row, dict)
    ]
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else 0.0


def _mean_field(rows: list[dict[str, Any]], key: str) -> float:
    values = [_float(row.get(key)) for row in rows if isinstance(row, dict)]
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else 0.0


def _read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _float(value: Any, default: float | None = 0.0) -> float:
    if value in {None, ""}:
        return float(default or 0.0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default or 0.0)


def _int(value: Any, default: int = 0) -> int:
    if value in {None, ""}:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _round(value: Any, digits: int = 6) -> float:
    return round(_float(value), digits)
