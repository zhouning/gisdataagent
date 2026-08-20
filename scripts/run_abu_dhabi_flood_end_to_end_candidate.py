#!/usr/bin/env python3
"""Run a complete synthetic Abu Dhabi flood candidate scenario.

The runner connects the conservative state operator to the impact contract. It
is intentionally synthetic and uncalibrated; no customer or public source rows
are consumed as hydraulic truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

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

SCENARIO_SCHEMA = "gwm.abu_dhabi_flood.end_to_end_candidate_receipt.v1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path(
    "docs/customer/abu_dhabi_liveability_site_validation/technical_validation/"
    "flood_end_to_end_candidate_receipt.json"
)


def build_model() -> AbuDhabiFloodWorldModel:
    network = FloodNetwork(
        network_id="abu-dhabi-synthetic-stormwater-catchments",
        patches=(
            SurfacePatch("catchment-a", 10_000.0, 0.85, 0.0, 2.0, "fixture:patch-a"),
            SurfacePatch("catchment-b", 8_000.0, 0.75, 0.0, 1.0, "fixture:patch-b"),
        ),
        links=(
            DrainageLink(
                "pipe-a-to-b",
                "catchment-a",
                "catchment-b",
                0.05,
                600.0,
                "fixture:pipe-a-to-b",
            ),
            DrainageLink(
                "outfall-b",
                "catchment-b",
                None,
                0.03,
                900.0,
                "fixture:outfall-b",
            ),
        ),
        crs="EPSG:32640",
        provenance_id="fixture:abu-dhabi-flood-network",
    )
    return AbuDhabiFloodWorldModel(network, FloodModelConfig(300.0))


def _rainfall_series(model: AbuDhabiFloodWorldModel) -> tuple[RainfallForcing, ...]:
    del model
    return tuple(
        RainfallForcing(
            (2400.0, 2400.0),
            duration_seconds=300.0,
            timestamp_s=step * 300.0,
            provenance_id="fixture:synthetic-design-storm",
        )
        for step in range(4)
    )


def _actions(model: AbuDhabiFloodWorldModel) -> dict[str, tuple[FloodAction, ...]]:
    baseline = FloodAction(
        "baseline",
        (1.0, 1.0),
        (0.0, 0.0),
        "fixture:baseline",
    )
    intervention = FloodAction(
        "emergency-pumping-and-gate",
        (2.0, 2.0),
        (8.0, 6.0),
        "fixture:intervention",
    )
    return {
        "baseline": (baseline,) * 4,
        "intervention": (intervention,) * 4,
    }


def _impact_receipt(
    scenario_name: str,
    model: AbuDhabiFloodWorldModel,
    rollout: object,
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
                inundated_area_m2=(patch.area_m2 if peak_depth > 0.0 else 0.0),
                provenance_id=f"fixture:{scenario_name}-hydraulic-{index}",
            )
        )
    exposures = (
        ExposureImpactUnit(
            "catchment-a",
            1000.0,
            2,
            1500.0,
            40,
            f"fixture:{scenario_name}-exposure-a",
        ),
        ExposureImpactUnit(
            "catchment-b",
            600.0,
            1,
            800.0,
            20,
            f"fixture:{scenario_name}-exposure-b",
        ),
    )
    window = FloodImpactAssessmentWindow(
        run_id=f"abu-dhabi-end-to-end-{scenario_name}",
        window_start_seconds=0.0,
        window_end_seconds=1200.0,
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


def _delta(baseline: dict[str, object], intervention: dict[str, object]) -> dict[str, float]:
    baseline_metrics = baseline["quality_gates"]["metrics"]
    intervention_metrics = intervention["quality_gates"]["metrics"]
    fields = (
        "affected_overlay_unit_count",
        "severe_overlay_unit_count",
        "affected_inundated_area_m2",
        "affected_population_count",
        "affected_critical_facility_count",
        "affected_road_length_m",
        "affected_plot_count",
    )
    return {
        field: float(intervention_metrics[field] - baseline_metrics[field])
        for field in fields
    }


def run() -> dict[str, object]:
    model = build_model()
    rainfall = _rainfall_series(model)
    initial = model.initial_state()
    action_scenarios = _actions(model)
    rollouts = model.counterfactual(initial, rainfall, action_scenarios)
    impact_receipts = {
        name: _impact_receipt(name, model, rollout)
        for name, rollout in rollouts.items()
    }
    if any(
        rollout.maximum_abs_mass_balance_residual_m3 > model.config.mass_tolerance_m3
        for rollout in rollouts.values()
    ):
        raise RuntimeError("end_to_end_candidate_mass_quality_gate_failed")
    baseline_impact = impact_receipts["baseline"]
    intervention_impact = impact_receipts["intervention"]
    payload: dict[str, object] = {
        "schema": SCENARIO_SCHEMA,
        "status": "completed_synthetic_end_to_end_candidate_not_calibrated",
        "scenario_id": "abu-dhabi-flood-end-to-end-candidate-v1",
        "forcing": {
            "intensity_mm_per_h": 2400.0,
            "duration_seconds": 1200.0,
            "source": "synthetic_fixture",
            "not_an_abu_dhabi_observed_event": True,
        },
        "network": model.network.as_dict(),
        "rollouts": {name: rollout.as_dict() for name, rollout in rollouts.items()},
        "impact_receipts": impact_receipts,
        "action_comparison": {
            "baseline": "baseline",
            "intervention": "emergency-pumping-and-gate",
            "delta_intervention_minus_baseline": _delta(
                baseline_impact, intervention_impact
            ),
            "interpretation": (
                "synthetic conservative-operator comparison; not an engineering "
                "action recommendation"
            ),
        },
        "execution": {
            "customer_rows_consumed": False,
            "public_proxy_rows_consumed": False,
            "traditional_solver_invoked": False,
            "gwm_training_invoked": False,
            "gwm_prediction_claim_allowed": False,
            "impact_contract_consumed": True,
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
            "synthetic_fixture_only",
            "conservative_control_volume_operator_not_traditional_hydraulic_solver",
            "synthetic_exposure_values_not_customer_liveability_rows",
            "not_calibrated_and_not_a_real_city_prediction",
        ],
    }
    payload["receipt_sha256"] = _sha256_json(payload)
    return payload


def _sha256_json(value: dict[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else REPOSITORY_ROOT / args.output
    os.chdir(REPOSITORY_ROOT)
    payload = run()
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        + "\n"
    ).encode("ascii")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    os.replace(temporary, output)
    print(json.dumps({"output": str(output), "receipt_sha256": payload["receipt_sha256"]}))


if __name__ == "__main__":
    main()
