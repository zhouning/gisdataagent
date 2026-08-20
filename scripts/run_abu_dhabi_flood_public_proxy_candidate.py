#!/usr/bin/env python3
"""Run an Open-Meteo forcing candidate through the synthetic flood operator.

The rainfall is a public reanalysis/model point proxy.  The hydraulic graph and
exposure values remain synthetic fixtures, so this runner is useful for
testing forcing ingestion, time-step conversion, conservation and action
conditioning only.  It does not compile customer assets, DEMs or train GWM.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from data_agent.uwm.abu_dhabi_flood import (
    AbuDhabiFloodWorldModel,
    DrainageLink,
    ExposureImpactUnit,
    FloodAction,
    FloodImpactAssessmentPolicy,
    FloodImpactAssessmentWindow,
    FloodModelConfig,
    FloodNetwork,
    InundationImpactUnit,
    RainfallForcing,
    SurfacePatch,
    build_flood_impact_receipt,
    verify_flood_impact_receipt,
)

SCENARIO_SCHEMA = "gwm.abu_dhabi_flood.public_proxy_candidate_receipt.v1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FORCING = (
    REPOSITORY_ROOT
    / "benchmarks/abu_dhabi_stormwater_data_v1/online/weather/"
    / "openmeteo_archive_abu_dhabi_20240415_20240417.json"
)
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs/customer/abu_dhabi_liveability_site_validation/technical_validation/"
    / "flood_public_proxy_candidate_receipt.json"
)
EXPECTED_FORCING_SHA256 = "c03e452277ef944918a0ef2fa7ca046a78a614ab8f1f5a88bcdb213e8bb3c7ff"
MODEL_TIMESTEP_SECONDS = 300.0
EXPECTED_HOURLY_INTERVALS = 72
EXPECTED_START = datetime(2024, 4, 15, tzinfo=UTC)
EXPECTED_END_EXCLUSIVE = datetime(2024, 4, 18, tzinfo=UTC)
OPEN_METEO_SOURCE_URL = (
    "https://archive-api.open-meteo.com/v1/archive?"
    "latitude=24.429&longitude=54.377&start_date=2024-04-15&"
    "end_date=2024-04-17&hourly=precipitation,rain&timezone=GMT"
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: dict[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return _sha256_bytes(encoded)


def _finite_nonnegative(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field}_must_be_numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(f"{field}_must_be_finite_and_nonnegative")
    return result


def _parse_utc_hour(value: Any, index: int) -> datetime:
    if not isinstance(value, str):
        raise ValueError("openmeteo_timestamp_must_be_text")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("openmeteo_timestamp_invalid") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC)
    else:
        parsed = parsed.replace(tzinfo=UTC)
    expected = EXPECTED_START + timedelta(hours=index)
    if parsed != expected:
        raise ValueError("openmeteo_timestamp_window_or_cadence_invalid")
    return parsed


def load_openmeteo_hourly(path: Path = DEFAULT_FORCING) -> dict[str, object]:
    """Validate the frozen Open-Meteo payload and return normalized hourly data."""

    raw_bytes = path.read_bytes()
    file_sha256 = _sha256_bytes(raw_bytes)
    if file_sha256 != EXPECTED_FORCING_SHA256:
        raise ValueError("openmeteo_forcing_sha256_mismatch")
    payload = json.loads(raw_bytes.decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("hourly"), dict):
        raise ValueError("openmeteo_hourly_payload_required")
    hourly = payload["hourly"]
    units = payload.get("hourly_units")
    if not isinstance(units, dict):
        raise ValueError("openmeteo_hourly_units_required")
    if units.get("precipitation") != "mm" or units.get("rain") != "mm":
        raise ValueError("openmeteo_precipitation_units_must_be_mm")
    times = hourly.get("time")
    precipitation = hourly.get("precipitation")
    rain = hourly.get("rain")
    if (
        not isinstance(times, list)
        or not isinstance(precipitation, list)
        or not isinstance(rain, list)
    ):
        raise ValueError("openmeteo_time_precipitation_and_rain_lists_required")
    if (
        len(times) != EXPECTED_HOURLY_INTERVALS
        or len(precipitation) != len(times)
        or len(rain) != len(times)
    ):
        raise ValueError("openmeteo_expected_72_aligned_hourly_intervals")
    parsed_times = tuple(_parse_utc_hour(value, index) for index, value in enumerate(times))
    precipitation_mm = tuple(
        _finite_nonnegative(value, "openmeteo_precipitation_mm") for value in precipitation
    )
    rain_mm = tuple(_finite_nonnegative(value, "openmeteo_rain_mm") for value in rain)
    if any(
        abs(left - right) > 1.0e-9 for left, right in zip(precipitation_mm, rain_mm, strict=True)
    ):
        raise ValueError("openmeteo_precipitation_and_rain_disagree")
    if (
        parsed_times[0] != EXPECTED_START
        or parsed_times[-1] + timedelta(hours=1) != EXPECTED_END_EXCLUSIVE
    ):
        raise ValueError("openmeteo_event_window_invalid")
    return {
        "payload": payload,
        "file_sha256": file_sha256,
        "times": parsed_times,
        "precipitation_mm": precipitation_mm,
        "total_precipitation_mm": float(sum(precipitation_mm)),
        "maximum_hourly_precipitation_mm": max(precipitation_mm, default=0.0),
    }


def expand_to_model_timestep(
    hourly: dict[str, object],
    *,
    timestep_seconds: float = MODEL_TIMESTEP_SECONDS,
    provenance_prefix: str = "public:openmeteo",
) -> tuple[RainfallForcing, ...]:
    """Repeat normalized hourly interval depths over model time steps.

    ``precipitation_mm`` must already contain one depth for each hourly
    interval. Repeating the same numeric value as mm/h for 12 five-minute
    steps preserves that interval depth; treating it as a five-minute depth
    would multiply rainfall by twelve.
    """

    if timestep_seconds <= 0.0 or 3600.0 % timestep_seconds != 0.0:
        raise ValueError("model_timestep_must_partition_one_hour")
    if not isinstance(provenance_prefix, str) or not provenance_prefix.strip():
        raise ValueError("forcing_provenance_prefix_required")
    precipitation_mm = hourly.get("precipitation_mm")
    if (
        not isinstance(precipitation_mm, tuple)
        or len(precipitation_mm) != EXPECTED_HOURLY_INTERVALS
    ):
        raise ValueError("normalized_hourly_precipitation_required")
    steps_per_hour = int(3600.0 / timestep_seconds)
    forcing: list[RainfallForcing] = []
    step = 0
    for hour_index, amount_mm in enumerate(precipitation_mm):
        for _ in range(steps_per_hour):
            forcing.append(
                RainfallForcing(
                    (amount_mm, amount_mm),
                    duration_seconds=timestep_seconds,
                    timestamp_s=step * timestep_seconds,
                    provenance_id=f"{provenance_prefix.strip()}:hour-{hour_index:03d}",
                    evidence_level="candidate",
                    is_forecast=False,
                )
            )
            step += 1
    return tuple(forcing)


def build_model() -> AbuDhabiFloodWorldModel:
    """Build the same two-patch synthetic network used by the baseline candidate."""

    network = FloodNetwork(
        network_id="abu-dhabi-synthetic-stormwater-catchments",
        patches=(
            SurfacePatch("catchment-a", 10_000.0, 0.85, 0.0, 2.0, "fixture:patch-a"),
            SurfacePatch("catchment-b", 8_000.0, 0.75, 0.0, 1.0, "fixture:patch-b"),
        ),
        links=(
            DrainageLink(
                "pipe-a-to-b", "catchment-a", "catchment-b", 0.05, 600.0, "fixture:pipe-a-to-b"
            ),
            DrainageLink("outfall-b", "catchment-b", None, 0.03, 900.0, "fixture:outfall-b"),
        ),
        crs="EPSG:32640",
        provenance_id="fixture:abu-dhabi-flood-network",
    )
    return AbuDhabiFloodWorldModel(network, FloodModelConfig(MODEL_TIMESTEP_SECONDS))


def _actions(model: AbuDhabiFloodWorldModel, count: int) -> dict[str, tuple[FloodAction, ...]]:
    baseline = FloodAction("baseline", (1.0, 1.0), (0.0, 0.0), "fixture:baseline")
    intervention = FloodAction(
        "synthetic-pumping-sensitivity",
        (2.0, 2.0),
        (0.05, 0.04),
        "fixture:public-proxy-intervention",
    )
    del model
    return {"baseline": (baseline,) * count, "intervention": (intervention,) * count}


def _impact_receipt(
    scenario_name: str,
    model: AbuDhabiFloodWorldModel,
    rollout: object,
    window_end_seconds: float,
) -> dict[str, object]:
    units = []
    for index, (patch, peak_depth) in enumerate(
        zip(model.network.patches, rollout.peak_depth_by_patch_m, strict=True)
    ):
        duration = sum(
            model.config.timestep_seconds
            for trace in rollout.traces
            if trace.surface_depth_m[index] >= 0.10
        )
        units.append(
            InundationImpactUnit(
                overlay_unit_id=patch.patch_id,
                maximum_depth_m=peak_depth,
                inundation_duration_seconds=duration,
                inundated_area_m2=patch.area_m2 if peak_depth > 0.0 else 0.0,
                provenance_id=f"fixture:{scenario_name}-hydraulic-{index}",
            )
        )
    exposures = (
        ExposureImpactUnit(
            "catchment-a", 1000.0, 2, 1500.0, 40, f"fixture:{scenario_name}-exposure-a"
        ),
        ExposureImpactUnit(
            "catchment-b", 600.0, 1, 800.0, 20, f"fixture:{scenario_name}-exposure-b"
        ),
    )
    window = FloodImpactAssessmentWindow(
        run_id=f"abu-dhabi-public-proxy-{scenario_name}",
        window_start_seconds=0.0,
        window_end_seconds=window_end_seconds,
        crs="EPSG:32640",
        overlay_method="synthetic_partition_fixture",
        hydraulic_result_reference_id=f"fixture:{scenario_name}-rollout",
        exposure_snapshot_reference_id=f"fixture:{scenario_name}-exposure",
        inundation_units=tuple(units),
        exposure_units=exposures,
    )
    receipt = build_flood_impact_receipt(window, FloodImpactAssessmentPolicy())
    verify_flood_impact_receipt(receipt)
    return receipt


def _rollout_summary(rollout: object) -> dict[str, object]:
    return {
        "peak_depth_by_patch_m": list(rollout.peak_depth_by_patch_m),
        "maximum_peak_depth_m": max(rollout.peak_depth_by_patch_m, default=0.0),
        "final_storage_m3": rollout.final_state.total_storage_m3,
        "total_rainfall_input_m3": rollout.total_rainfall_input_m3,
        "total_infiltration_loss_m3": rollout.total_infiltration_loss_m3,
        "total_pump_outflow_m3": rollout.total_pump_outflow_m3,
        "total_outfall_outflow_m3": rollout.total_outfall_outflow_m3,
        "maximum_abs_mass_balance_residual_m3": rollout.maximum_abs_mass_balance_residual_m3,
    }


def _hourly_rollout_windows(rollout: object) -> list[dict[str, object]]:
    """Compact 5-minute traces into auditable hourly water ledgers."""

    steps_per_hour = int(3600.0 / MODEL_TIMESTEP_SECONDS)
    if len(rollout.traces) % steps_per_hour != 0:
        raise ValueError("rollout_steps_do_not_partition_into_hours")
    windows = []
    for hour_index in range(len(rollout.traces) // steps_per_hour):
        start = hour_index * steps_per_hour
        traces = rollout.traces[start : start + steps_per_hour]
        final_trace = traces[-1]
        windows.append(
            {
                "hour_index": hour_index,
                "window_start_seconds": traces[0].timestamp_s,
                "window_end_seconds": final_trace.state_after.timestamp_s,
                "rainfall_input_m3": sum(item.rainfall_input_m3 for item in traces),
                "infiltration_loss_m3": sum(item.infiltration_loss_m3 for item in traces),
                "pump_outflow_m3": sum(item.pump_outflow_m3 for item in traces),
                "outfall_outflow_m3": sum(item.outfall_outflow_m3 for item in traces),
                "peak_depth_by_patch_m": [
                    max(item.surface_depth_m[index] for item in traces)
                    for index in range(len(final_trace.surface_depth_m))
                ],
                "end_surface_depth_by_patch_m": list(final_trace.surface_depth_m),
                "end_link_storage_m3": list(final_trace.state_after.link_storage_m3),
                "maximum_abs_mass_balance_residual_m3": max(
                    abs(item.mass_balance_residual_m3) for item in traces
                ),
            }
        )
    return windows


def run(forcing_path: Path = DEFAULT_FORCING) -> dict[str, object]:
    forcing_path = forcing_path.resolve()
    hourly = load_openmeteo_hourly(forcing_path)
    rainfall = expand_to_model_timestep(hourly)
    model = build_model()
    rollouts = model.counterfactual(
        model.initial_state(),
        rainfall,
        _actions(model, len(rainfall)),
    )
    if any(
        rollout.maximum_abs_mass_balance_residual_m3 > model.config.mass_tolerance_m3
        for rollout in rollouts.values()
    ):
        raise RuntimeError("public_proxy_candidate_mass_quality_gate_failed")
    window_end_seconds = len(rainfall) * MODEL_TIMESTEP_SECONDS
    impact_receipts = {
        name: _impact_receipt(name, model, rollout, window_end_seconds)
        for name, rollout in rollouts.items()
    }
    hourly_depth = float(hourly["total_precipitation_mm"])
    expanded_depth = float(
        sum(item.intensity_mm_per_h[0] * item.duration_seconds / 3600.0 for item in rainfall)
    )
    # The two synthetic patches receive the same point forcing but have distinct
    # runoff coefficients; calculate the exact volume ledger explicitly.
    expected_model_volume = sum(
        amount_mm
        * 1.0e-3
        * sum(patch.area_m2 * patch.runoff_coefficient for patch in model.network.patches)
        for amount_mm in hourly["precipitation_mm"]
    )
    actual_model_volume = rollouts["baseline"].total_rainfall_input_m3
    payload: dict[str, object] = {
        "schema": SCENARIO_SCHEMA,
        "status": "completed_public_proxy_forcing_on_synthetic_network_not_calibrated",
        "scenario_id": "abu-dhabi-flood-public-proxy-candidate-v1",
        "forcing": {
            "source": "Open-Meteo Historical API archive point product",
            "source_url": OPEN_METEO_SOURCE_URL,
            "source_file": str(forcing_path.relative_to(REPOSITORY_ROOT)),
            "file_sha256": hourly["file_sha256"],
            "evidence_class": "reanalysis_candidate",
            "calibration_admission": "not_admitted_for_calibration",
            "timestamp_timezone": "UTC",
            "event_window_start": EXPECTED_START.isoformat().replace("+00:00", "Z"),
            "event_window_end_exclusive": EXPECTED_END_EXCLUSIVE.isoformat().replace("+00:00", "Z"),
            "hourly_interval_count": EXPECTED_HOURLY_INTERVALS,
            "expanded_interval_count": len(rainfall),
            "model_timestep_seconds": MODEL_TIMESTEP_SECONDS,
            "precipitation_field_semantics": (
                "hourly_interval_depth_mm_repeated_as_mm_per_h_over_12_five_minute_steps"
            ),
            "hourly_total_precipitation_mm": hourly_depth,
            "expanded_total_precipitation_mm": expanded_depth,
            "maximum_hourly_precipitation_mm": hourly["maximum_hourly_precipitation_mm"],
            "conservation": {
                "depth_residual_mm": expanded_depth - hourly_depth,
                "expected_model_rainfall_input_m3": expected_model_volume,
                "actual_model_rainfall_input_m3": actual_model_volume,
                "model_rainfall_volume_residual_m3": actual_model_volume - expected_model_volume,
            },
        },
        "network": model.network.as_dict(),
        "rollouts": {
            name: {
                "summary": _rollout_summary(rollout),
                "hourly_windows": _hourly_rollout_windows(rollout),
            }
            for name, rollout in rollouts.items()
        },
        "rollout_summaries": {
            name: _rollout_summary(rollout) for name, rollout in rollouts.items()
        },
        "impact_receipts": impact_receipts,
        "action_comparison": {
            "baseline": "baseline",
            "intervention": "synthetic-pumping-sensitivity",
            "peak_depth_delta_intervention_minus_baseline_m": (
                _rollout_summary(rollouts["intervention"])["maximum_peak_depth_m"]
                - _rollout_summary(rollouts["baseline"])["maximum_peak_depth_m"]
            ),
            "interpretation": (
                "public forcing on a synthetic network; intervention is a "
                "sensitivity case, not an engineering recommendation"
            ),
        },
        "execution": {
            "customer_rows_consumed": False,
            "public_proxy_rows_consumed": True,
            "public_forcing_file_hash_validated": True,
            "database_rows_consumed": False,
            "dem_consumed": False,
            "traditional_solver_invoked": False,
            "gwm_training_invoked": False,
            "gwm_prediction_claim_allowed": False,
            "impact_contract_consumed": True,
            "synthetic_network": True,
            "synthetic_exposure_values": True,
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
            "public_proxy_forcing_only",
            "synthetic_network_only",
            "conservative_control_volume_operator_not_traditional_hydraulic_solver",
            "synthetic_exposure_values_not_customer_liveability_rows",
            "reanalysis_candidate_not_calibration_evidence",
            "not_a_calibrated_or_real_city_prediction",
        ],
    }
    payload["receipt_sha256"] = _sha256_json(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--forcing", type=Path, default=DEFAULT_FORCING)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    forcing = args.forcing if args.forcing.is_absolute() else REPOSITORY_ROOT / args.forcing
    output = args.output if args.output.is_absolute() else REPOSITORY_ROOT / args.output
    os.chdir(REPOSITORY_ROOT)
    payload = run(forcing)
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
