#!/usr/bin/env python3
"""Compare two frozen public rainfall forcings on one synthetic flood graph.

Open-Meteo and NASA POWER/MERRA2 use different source clocks and are not local
gauge or radar observations. This runner preserves those limitations while
quantifying how product choice changes the same diagnostic flood rollouts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

if __package__:
    from scripts.run_abu_dhabi_flood_public_proxy_candidate import (
        EXPECTED_HOURLY_INTERVALS,
        MODEL_TIMESTEP_SECONDS,
        REPOSITORY_ROOT,
        _actions,
        _hourly_rollout_windows,
        _impact_receipt,
        _rollout_summary,
        _sha256_json,
        build_model,
        expand_to_model_timestep,
        load_openmeteo_hourly,
    )
else:
    from run_abu_dhabi_flood_public_proxy_candidate import (
        EXPECTED_HOURLY_INTERVALS,
        MODEL_TIMESTEP_SECONDS,
        REPOSITORY_ROOT,
        _actions,
        _hourly_rollout_windows,
        _impact_receipt,
        _rollout_summary,
        _sha256_json,
        build_model,
        expand_to_model_timestep,
        load_openmeteo_hourly,
    )

COMPARISON_SCHEMA = "gwm.abu_dhabi_flood.public_forcing_comparison_receipt.v1"
DEFAULT_OPENMETEO_FORCING = (
    REPOSITORY_ROOT
    / "benchmarks/abu_dhabi_stormwater_data_v1/online/weather/"
    / "openmeteo_archive_abu_dhabi_20240415_20240417.json"
)
DEFAULT_NASA_HOURLY_FORCING = (
    REPOSITORY_ROOT
    / "benchmarks/abu_dhabi_stormwater_data_v1/online/weather/"
    / "nasa_power_hourly_prectotcorr_abu_dhabi_20240415_20240417.json"
)
DEFAULT_NASA_DAILY_FORCING = (
    REPOSITORY_ROOT
    / "benchmarks/abu_dhabi_stormwater_data_v1/online/weather/"
    / "nasa_power_daily_prectotcorr_abu_dhabi_20240415_20240417.json"
)
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs/customer/abu_dhabi_liveability_site_validation/technical_validation/"
    / "flood_public_forcing_comparison_receipt.json"
)
EXPECTED_NASA_HOURLY_SHA256 = "36916d04ee30ea5e16f3c2bde221a3c545081461d5c18f37d4197eb69dc973b2"
EXPECTED_NASA_DAILY_SHA256 = "7607ed1e634126524034fcbfa4d69d453d539b280250c6da4f04ccf1ea594677"
NASA_POWER_HOURLY_SOURCE_URL = (
    "https://power.larc.nasa.gov/api/temporal/hourly/point?"
    "parameters=PRECTOTCORR&community=RE&longitude=54.377&latitude=24.429&"
    "start=20240415&end=20240417&format=JSON"
)
NASA_POWER_DAILY_SOURCE_URL = NASA_POWER_HOURLY_SOURCE_URL.replace("/hourly/", "/daily/")
SOURCE_START_LABEL = datetime(2024, 4, 15)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _finite_nonnegative(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field}_must_be_numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(f"{field}_must_be_finite_and_nonnegative")
    return result


def _load_frozen_json(path: Path, expected_sha256: str, label: str) -> tuple[dict, str]:
    raw = path.read_bytes()
    actual_sha256 = _sha256_bytes(raw)
    if actual_sha256 != expected_sha256:
        raise ValueError(f"{label}_sha256_mismatch")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label}_json_object_required")
    return payload, actual_sha256


def _validate_nasa_common(payload: dict, label: str) -> tuple[dict, dict]:
    header = payload.get("header")
    parameters = payload.get("parameters")
    properties = payload.get("properties")
    if not isinstance(header, dict) or not isinstance(parameters, dict):
        raise ValueError(f"{label}_header_and_parameters_required")
    if not isinstance(properties, dict):
        raise ValueError(f"{label}_properties_required")
    if header.get("time_standard") != "LST":
        raise ValueError(f"{label}_time_standard_must_be_lst")
    if header.get("start") != "20240415" or header.get("end") != "20240417":
        raise ValueError(f"{label}_event_window_invalid")
    sources = header.get("sources")
    if not isinstance(sources, list) or "MERRA2" not in sources:
        raise ValueError(f"{label}_merra2_source_required")
    parameter_metadata = parameters.get("PRECTOTCORR")
    if not isinstance(parameter_metadata, dict):
        raise ValueError(f"{label}_prectotcorr_metadata_required")
    if parameter_metadata.get("units") != "mm/day":
        raise ValueError(f"{label}_prectotcorr_units_must_be_mm_per_day")
    parameter = properties.get("parameter")
    if not isinstance(parameter, dict) or not isinstance(parameter.get("PRECTOTCORR"), dict):
        raise ValueError(f"{label}_prectotcorr_values_required")
    return header, parameter["PRECTOTCORR"]


def load_nasa_power_hourly(
    path: Path = DEFAULT_NASA_HOURLY_FORCING,
) -> dict[str, object]:
    """Validate and normalize POWER hourly rates from mm/day to hourly depth."""

    payload, file_sha256 = _load_frozen_json(path, EXPECTED_NASA_HOURLY_SHA256, "nasa_power_hourly")
    header, values = _validate_nasa_common(payload, "nasa_power_hourly")
    expected_keys = tuple(
        (SOURCE_START_LABEL + timedelta(hours=index)).strftime("%Y%m%d%H")
        for index in range(EXPECTED_HOURLY_INTERVALS)
    )
    if tuple(sorted(values)) != expected_keys:
        raise ValueError("nasa_power_hourly_keys_or_cadence_invalid")
    source_rates_mm_per_day = tuple(
        _finite_nonnegative(values[key], "nasa_power_hourly_rate") for key in expected_keys
    )
    precipitation_mm = tuple(value / 24.0 for value in source_rates_mm_per_day)
    return {
        "payload": payload,
        "file_sha256": file_sha256,
        "time_standard": header["time_standard"],
        "time_labels": expected_keys,
        "source_rates_mm_per_day": source_rates_mm_per_day,
        "precipitation_mm": precipitation_mm,
        "raw_rate_sum_not_a_depth": float(sum(source_rates_mm_per_day)),
        "total_precipitation_mm": float(sum(precipitation_mm)),
        "maximum_hourly_precipitation_mm": max(precipitation_mm, default=0.0),
    }


def load_nasa_power_daily(
    path: Path = DEFAULT_NASA_DAILY_FORCING,
) -> dict[str, object]:
    """Validate the independent daily POWER product used as an aggregate check."""

    payload, file_sha256 = _load_frozen_json(path, EXPECTED_NASA_DAILY_SHA256, "nasa_power_daily")
    header, values = _validate_nasa_common(payload, "nasa_power_daily")
    expected_keys = ("20240415", "20240416", "20240417")
    if tuple(sorted(values)) != expected_keys:
        raise ValueError("nasa_power_daily_keys_invalid")
    precipitation_mm = tuple(
        _finite_nonnegative(values[key], "nasa_power_daily_depth") for key in expected_keys
    )
    return {
        "payload": payload,
        "file_sha256": file_sha256,
        "time_standard": header["time_standard"],
        "time_labels": expected_keys,
        "precipitation_mm": precipitation_mm,
        "total_precipitation_mm": float(sum(precipitation_mm)),
    }


def _expected_rainfall_volume_m3(model: object, total_depth_mm: float) -> float:
    effective_area_m2 = sum(
        patch.area_m2 * patch.runoff_coefficient for patch in model.network.patches
    )
    return total_depth_mm * 1.0e-3 * effective_area_m2


def _run_source(
    source_id: str,
    hourly: dict[str, object],
) -> dict[str, object]:
    model = build_model()
    rainfall = expand_to_model_timestep(
        hourly,
        provenance_prefix=f"public:{source_id}",
    )
    rollouts = model.counterfactual(
        model.initial_state(),
        rainfall,
        _actions(model, len(rainfall)),
    )
    if any(
        rollout.maximum_abs_mass_balance_residual_m3 > model.config.mass_tolerance_m3
        for rollout in rollouts.values()
    ):
        raise RuntimeError(f"{source_id}_mass_quality_gate_failed")
    window_end_seconds = len(rainfall) * MODEL_TIMESTEP_SECONDS
    impact_receipts = {
        name: _impact_receipt(f"{source_id}-{name}", model, rollout, window_end_seconds)
        for name, rollout in rollouts.items()
    }
    total_depth_mm = float(hourly["total_precipitation_mm"])
    expanded_depth_mm = sum(
        item.intensity_mm_per_h[0] * item.duration_seconds / 3600.0 for item in rainfall
    )
    expected_volume_m3 = _expected_rainfall_volume_m3(model, total_depth_mm)
    actual_volume_m3 = rollouts["baseline"].total_rainfall_input_m3
    return {
        "normalized_forcing": {
            "hourly_interval_count": len(hourly["precipitation_mm"]),
            "expanded_interval_count": len(rainfall),
            "model_timestep_seconds": MODEL_TIMESTEP_SECONDS,
            "total_precipitation_mm": total_depth_mm,
            "expanded_total_precipitation_mm": expanded_depth_mm,
            "maximum_hourly_precipitation_mm": hourly["maximum_hourly_precipitation_mm"],
            "depth_residual_mm": expanded_depth_mm - total_depth_mm,
            "expected_model_rainfall_input_m3": expected_volume_m3,
            "actual_model_rainfall_input_m3": actual_volume_m3,
            "model_rainfall_volume_residual_m3": (actual_volume_m3 - expected_volume_m3),
        },
        "rollouts": {
            name: {
                "summary": _rollout_summary(rollout),
                "hourly_windows": _hourly_rollout_windows(rollout),
            }
            for name, rollout in rollouts.items()
        },
        "impact_receipts": impact_receipts,
    }


def _percent_change(new: float, reference: float) -> float | None:
    if reference == 0.0:
        return None
    return 100.0 * (new - reference) / reference


def run(
    openmeteo_path: Path = DEFAULT_OPENMETEO_FORCING,
    nasa_hourly_path: Path = DEFAULT_NASA_HOURLY_FORCING,
    nasa_daily_path: Path = DEFAULT_NASA_DAILY_FORCING,
) -> dict[str, object]:
    openmeteo_path = openmeteo_path.resolve()
    nasa_hourly_path = nasa_hourly_path.resolve()
    nasa_daily_path = nasa_daily_path.resolve()
    openmeteo = load_openmeteo_hourly(openmeteo_path)
    nasa_hourly = load_nasa_power_hourly(nasa_hourly_path)
    nasa_daily = load_nasa_power_daily(nasa_daily_path)
    source_runs = {
        "openmeteo": _run_source("openmeteo", openmeteo),
        "nasa_power_merra2": _run_source("nasa-power-merra2", nasa_hourly),
    }
    open_forcing = source_runs["openmeteo"]["normalized_forcing"]
    nasa_forcing = source_runs["nasa_power_merra2"]["normalized_forcing"]
    open_baseline = source_runs["openmeteo"]["rollouts"]["baseline"]["summary"]
    nasa_baseline = source_runs["nasa_power_merra2"]["rollouts"]["baseline"]["summary"]
    open_intervention = source_runs["openmeteo"]["rollouts"]["intervention"]["summary"]
    nasa_intervention = source_runs["nasa_power_merra2"]["rollouts"]["intervention"]["summary"]
    payload: dict[str, object] = {
        "schema": COMPARISON_SCHEMA,
        "status": "completed_public_forcing_source_sensitivity_not_calibrated",
        "scenario_id": "abu-dhabi-flood-public-forcing-comparison-v1",
        "comparison_mode": ("source_native_72_hour_sequence_sensitivity_not_event_time_aligned"),
        "source_inputs": {
            "openmeteo": {
                "source": "Open-Meteo Historical API archive point product",
                "source_file": str(openmeteo_path.relative_to(REPOSITORY_ROOT)),
                "file_sha256": openmeteo["file_sha256"],
                "time_standard": openmeteo["payload"]["timezone"],
                "source_unit": "mm_per_hour_interval_depth",
                "conversion_to_interval_depth": "identity",
                "evidence_class": "reanalysis_candidate",
                "calibration_admission": "not_admitted_for_calibration",
            },
            "nasa_power_merra2_hourly": {
                "source": "NASA POWER Hourly API MERRA2 point product",
                "source_url": NASA_POWER_HOURLY_SOURCE_URL,
                "source_file": str(nasa_hourly_path.relative_to(REPOSITORY_ROOT)),
                "file_sha256": nasa_hourly["file_sha256"],
                "time_standard": nasa_hourly["time_standard"],
                "source_unit": "mm/day",
                "source_unit_semantics": "hourly_rate_expressed_as_mm_per_day",
                "conversion_to_interval_depth": "interval_depth_mm=source_rate/24",
                "raw_rate_sum_not_a_depth": nasa_hourly["raw_rate_sum_not_a_depth"],
                "direct_raw_sum_forcing_forbidden": True,
                "evidence_class": "reanalysis_candidate",
                "calibration_admission": "not_admitted_for_calibration",
            },
            "nasa_power_merra2_daily_crosscheck": {
                "source": "NASA POWER Daily API MERRA2 point product",
                "source_url": NASA_POWER_DAILY_SOURCE_URL,
                "source_file": str(nasa_daily_path.relative_to(REPOSITORY_ROOT)),
                "file_sha256": nasa_daily["file_sha256"],
                "time_standard": nasa_daily["time_standard"],
                "total_precipitation_mm": nasa_daily["total_precipitation_mm"],
                "hourly_minus_daily_total_mm": (
                    nasa_hourly["total_precipitation_mm"] - nasa_daily["total_precipitation_mm"]
                ),
                "used_as_model_forcing": False,
            },
        },
        "source_runs": source_runs,
        "source_disagreement": {
            "nasa_minus_openmeteo_total_precipitation_mm": (
                nasa_forcing["total_precipitation_mm"] - open_forcing["total_precipitation_mm"]
            ),
            "nasa_total_precipitation_percent_change_from_openmeteo": _percent_change(
                nasa_forcing["total_precipitation_mm"],
                open_forcing["total_precipitation_mm"],
            ),
            "nasa_minus_openmeteo_maximum_hourly_precipitation_mm": (
                nasa_forcing["maximum_hourly_precipitation_mm"]
                - open_forcing["maximum_hourly_precipitation_mm"]
            ),
            "nasa_minus_openmeteo_baseline_peak_depth_m": (
                nasa_baseline["maximum_peak_depth_m"] - open_baseline["maximum_peak_depth_m"]
            ),
            "nasa_baseline_peak_depth_percent_change_from_openmeteo": _percent_change(
                nasa_baseline["maximum_peak_depth_m"],
                open_baseline["maximum_peak_depth_m"],
            ),
            "openmeteo_intervention_peak_reduction_m": (
                open_baseline["maximum_peak_depth_m"] - open_intervention["maximum_peak_depth_m"]
            ),
            "nasa_intervention_peak_reduction_m": (
                nasa_baseline["maximum_peak_depth_m"] - nasa_intervention["maximum_peak_depth_m"]
            ),
            "source_time_standards_differ": True,
            "hourly_pointwise_difference_admitted": False,
            "forcing_source_selection_admitted": False,
            "direct_source_averaging_allowed": False,
            "interpretation": (
                "forcing product choice materially changes this synthetic-network "
                "response; customer gauge/radar forcing and an approved common "
                "time standard are required before event calibration"
            ),
        },
        "execution": {
            "customer_rows_consumed": False,
            "database_rows_consumed": False,
            "public_proxy_files_consumed": 3,
            "public_forcing_file_hashes_validated": True,
            "dem_consumed": False,
            "synthetic_network": True,
            "synthetic_actions": True,
            "synthetic_exposure_values": True,
            "traditional_solver_invoked": False,
            "gwm_training_invoked": False,
            "city_scale_prediction_claim_allowed": False,
        },
        "admission": {
            "k0_status": "closed_not_admitted",
            "traditional_model_admitted": False,
            "gwm_training_admitted": False,
            "hybrid_planner_admitted": False,
            "aggregate_impact_overlay_admitted": False,
            "per_asset_identity_admitted": False,
            "city_scale_prediction_claim_allowed": False,
        },
        "claim_boundary": [
            "public_reanalysis_candidates_not_local_gauge_or_radar_observations",
            "openmeteo_gmt_and_nasa_power_lst_not_hourly_event_aligned",
            "synthetic_network_actions_and_exposure_only",
            "conservative_control_volume_operator_not_traditional_hydraulic_solver",
            "forcing_source_sensitivity_not_calibration_or_accuracy_validation",
            "not_a_real_city_prediction_or_engineering_action_recommendation",
        ],
    }
    payload["receipt_sha256"] = _sha256_json(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openmeteo", type=Path, default=DEFAULT_OPENMETEO_FORCING)
    parser.add_argument("--nasa-hourly", type=Path, default=DEFAULT_NASA_HOURLY_FORCING)
    parser.add_argument("--nasa-daily", type=Path, default=DEFAULT_NASA_DAILY_FORCING)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    openmeteo = args.openmeteo if args.openmeteo.is_absolute() else REPOSITORY_ROOT / args.openmeteo
    nasa_hourly = (
        args.nasa_hourly if args.nasa_hourly.is_absolute() else REPOSITORY_ROOT / args.nasa_hourly
    )
    nasa_daily = (
        args.nasa_daily if args.nasa_daily.is_absolute() else REPOSITORY_ROOT / args.nasa_daily
    )
    output = args.output if args.output.is_absolute() else REPOSITORY_ROOT / args.output
    os.chdir(REPOSITORY_ROOT)
    payload = run(openmeteo, nasa_hourly, nasa_daily)
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("ascii")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    os.replace(temporary, output)
    print(json.dumps({"output": str(output), "receipt_sha256": payload["receipt_sha256"]}))


if __name__ == "__main__":
    main()
