#!/usr/bin/env python3
"""Compile outcome-free subcritical characteristic-boundary gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_boundaries import (
    CharacteristicDynamicWaveBoundary,
    dynamic_wave_characteristic_potential_mps,
    resolve_characteristic_dynamic_wave_boundary,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_coupled import (
    advance_coupled_dynamic_wave_open,
    maximum_open_stable_timestep_seconds,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_flux import (
    STANDARD_GRAVITY_MPS2,
    DynamicWaveCellState,
    PrismaticDynamicWaveState,
    TrapezoidalChannelSection,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_sources import (
    manning_uniform_discharge_m3s,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "dynamic_wave_characteristic_boundary_gates.json"
)
SCHEMA = "gwm.geotransport.dynamic_wave_characteristic_boundary_gates.v1"

PHYSICAL_LENGTH_M = 2_400.0
DURATION_SECONDS = 1_800.0
CELL_COUNTS = (24, 48, 96)
COURANT_NUMBER = 0.45
AREA_M2 = 20.0
BED_SLOPE = 0.002
MANNING_N = 0.035
REFINEMENT_ERROR_RATIO_LIMIT = 0.6
FINE_RELATIVE_DRIFT_LIMIT = 0.02
INVARIANT_ABSOLUTE_TOLERANCE_MPS = 2e-12
LEDGER_ABSOLUTE_TOLERANCE = 1e-8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    return parser.parse_args()


def _run_flat_lake(
    section: TrapezoidalChannelSection,
) -> dict[str, Any]:
    depth = 2.0
    area = section.area_m2(depth)
    cell_count = 6
    length = 100.0
    state = PrismaticDynamicWaveState((area,) * cell_count, (0.0,) * cell_count)
    initial = state
    left = CharacteristicDynamicWaveBoundary(
        "left", "area_m2", area, 0.0
    )
    right = CharacteristicDynamicWaveBoundary(
        "right", "free_surface_elevation_m", depth, 0.0
    )
    elapsed = 0.0
    maximum_volume_residual = 0.0
    maximum_momentum_residual = 0.0
    maximum_invariant_residual = 0.0
    for _ in range(100):
        timestep = maximum_open_stable_timestep_seconds(
            state,
            section,
            left_boundary=left,
            right_boundary=right,
            cell_length_m=length,
            courant_number=COURANT_NUMBER,
        )
        if timestep is None:
            raise RuntimeError("characteristic_lake_timestep_undefined")
        step = advance_coupled_dynamic_wave_open(
            state,
            (0.0,) * cell_count,
            section,
            left_boundary=left,
            right_boundary=right,
            manning_n=(MANNING_N,) * cell_count,
            lateral_inflow_m2s=(0.0,) * cell_count,
            lateral_momentum_convention="zero_longitudinal_momentum",
            cell_length_m=length,
            timestep_seconds=timestep,
            maximum_courant_number=COURANT_NUMBER,
        )
        if (
            step.left_characteristic_boundary is None
            or step.right_characteristic_boundary is None
        ):
            raise RuntimeError("characteristic_lake_boundary_not_resolved")
        state = step.state
        elapsed += timestep
        maximum_volume_residual = max(
            maximum_volume_residual, abs(step.volume_balance_error_m3)
        )
        maximum_momentum_residual = max(
            maximum_momentum_residual, abs(step.momentum_ledger_error_m4s)
        )
        maximum_invariant_residual = max(
            maximum_invariant_residual,
            abs(
                step.left_characteristic_boundary.outgoing_invariant_residual_mps
            ),
            abs(
                step.right_characteristic_boundary.outgoing_invariant_residual_mps
            ),
        )
    return {
        "step_count": 100,
        "elapsed_seconds": elapsed,
        "maximum_area_drift_m2": max(
            abs(after - before)
            for after, before in zip(state.area_m2, initial.area_m2, strict=True)
        ),
        "maximum_absolute_discharge_m3s": max(
            abs(value) for value in state.discharge_m3s
        ),
        "maximum_absolute_outgoing_invariant_residual_mps": (
            maximum_invariant_residual
        ),
        "maximum_absolute_step_volume_ledger_error_m3": (
            maximum_volume_residual
        ),
        "maximum_absolute_step_momentum_ledger_error_m4s": (
            maximum_momentum_residual
        ),
    }


def _run_moving_uniform_flow(
    section: TrapezoidalChannelSection,
    *,
    cell_count: int,
    equilibrium_discharge_m3s: float,
) -> dict[str, Any]:
    cell_length = PHYSICAL_LENGTH_M / cell_count
    depth = section.depth_m(AREA_M2)
    bed = tuple(
        -BED_SLOPE * (index + 0.5) * cell_length
        for index in range(cell_count)
    )
    left_bed = 0.5 * BED_SLOPE * cell_length
    right_bed = -BED_SLOPE * (cell_count + 0.5) * cell_length
    left = CharacteristicDynamicWaveBoundary(
        "left", "discharge_m3s", equilibrium_discharge_m3s, left_bed
    )
    right = CharacteristicDynamicWaveBoundary(
        "right",
        "free_surface_elevation_m",
        right_bed + depth,
        right_bed,
    )
    state = PrismaticDynamicWaveState(
        (AREA_M2,) * cell_count,
        (equilibrium_discharge_m3s,) * cell_count,
    )
    initial_volume = sum(state.area_m2) * cell_length
    initial_momentum = sum(state.discharge_m3s) * cell_length
    elapsed = 0.0
    step_count = 0
    boundary_volume = 0.0
    lateral_volume = 0.0
    lateral_momentum = 0.0
    friction_momentum = 0.0
    boundary_and_bed_momentum = 0.0
    maximum_volume_residual = 0.0
    maximum_momentum_residual = 0.0
    maximum_invariant_residual = 0.0
    maximum_courant = 0.0
    minimum_area = AREA_M2
    while elapsed < DURATION_SECONDS:
        stable_timestep = maximum_open_stable_timestep_seconds(
            state,
            section,
            left_boundary=left,
            right_boundary=right,
            cell_length_m=cell_length,
            courant_number=COURANT_NUMBER,
        )
        if stable_timestep is None:
            raise RuntimeError("characteristic_moving_timestep_undefined")
        timestep = min(stable_timestep, DURATION_SECONDS - elapsed)
        step = advance_coupled_dynamic_wave_open(
            state,
            bed,
            section,
            left_boundary=left,
            right_boundary=right,
            manning_n=(MANNING_N,) * cell_count,
            lateral_inflow_m2s=(0.0,) * cell_count,
            lateral_momentum_convention="zero_longitudinal_momentum",
            cell_length_m=cell_length,
            timestep_seconds=timestep,
            maximum_courant_number=COURANT_NUMBER,
        )
        if (
            step.left_characteristic_boundary is None
            or step.right_characteristic_boundary is None
        ):
            raise RuntimeError("characteristic_moving_boundary_not_resolved")
        state = step.state
        elapsed += timestep
        step_count += 1
        boundary_volume += step.boundary_volume_change_m3
        lateral_volume += step.lateral_volume_change_m3
        lateral_momentum += step.lateral_momentum_change_m4s
        friction_momentum += step.friction_momentum_change_m4s
        boundary_and_bed_momentum += step.boundary_and_bed_momentum_change_m4s
        maximum_volume_residual = max(
            maximum_volume_residual, abs(step.volume_balance_error_m3)
        )
        maximum_momentum_residual = max(
            maximum_momentum_residual, abs(step.momentum_ledger_error_m4s)
        )
        maximum_invariant_residual = max(
            maximum_invariant_residual,
            abs(
                step.left_characteristic_boundary.outgoing_invariant_residual_mps
            ),
            abs(
                step.right_characteristic_boundary.outgoing_invariant_residual_mps
            ),
        )
        maximum_courant = max(maximum_courant, step.maximum_courant_number)
        minimum_area = min(minimum_area, step.minimum_area_m2)

    final_volume = sum(state.area_m2) * cell_length
    final_momentum = sum(state.discharge_m3s) * cell_length
    area_errors = [abs(value - AREA_M2) for value in state.area_m2]
    discharge_errors = [
        abs(value - equilibrium_discharge_m3s)
        for value in state.discharge_m3s
    ]
    return {
        "cell_count": cell_count,
        "cell_length_m": cell_length,
        "step_count": step_count,
        "elapsed_seconds": elapsed,
        "maximum_reported_courant_number": maximum_courant,
        "minimum_area_m2": minimum_area,
        "maximum_relative_area_drift": max(area_errors) / AREA_M2,
        "mean_relative_area_drift": sum(area_errors)
        / (cell_count * AREA_M2),
        "maximum_relative_discharge_drift": max(discharge_errors)
        / equilibrium_discharge_m3s,
        "mean_relative_discharge_drift": sum(discharge_errors)
        / (cell_count * equilibrium_discharge_m3s),
        "maximum_absolute_outgoing_invariant_residual_mps": (
            maximum_invariant_residual
        ),
        "maximum_absolute_step_volume_ledger_error_m3": (
            maximum_volume_residual
        ),
        "maximum_absolute_step_momentum_ledger_error_m4s": (
            maximum_momentum_residual
        ),
        "cumulative_volume_ledger_error_m3": (
            final_volume - initial_volume - boundary_volume - lateral_volume
        ),
        "cumulative_momentum_ledger_error_m4s": (
            final_momentum
            - initial_momentum
            - lateral_momentum
            - friction_momentum
            - boundary_and_bed_momentum
        ),
    }


def compile_gates() -> dict[str, Any]:
    section = TrapezoidalChannelSection(10.0, 2.0)
    rectangular = TrapezoidalChannelSection(10.0, 0.0)
    rectangular_depth = 2.0
    rectangular_area = rectangular.area_m2(rectangular_depth)
    rectangular_potential = dynamic_wave_characteristic_potential_mps(
        rectangular_area, rectangular
    )
    rectangular_expected = 2.0 * (
        STANDARD_GRAVITY_MPS2 * rectangular_depth
    ) ** 0.5
    rectangular_error = abs(rectangular_potential - rectangular_expected)

    epsilon = 1e-4
    plus = dynamic_wave_characteristic_potential_mps(AREA_M2 + epsilon, section)
    minus = dynamic_wave_characteristic_potential_mps(AREA_M2 - epsilon, section)
    derivative = (plus - minus) / (2.0 * epsilon)
    expected_derivative = section.gravity_wave_celerity_mps(AREA_M2) / AREA_M2
    derivative_relative_error = abs(derivative - expected_derivative) / (
        expected_derivative
    )

    equilibrium_discharge = manning_uniform_discharge_m3s(
        area_m2=AREA_M2,
        bed_slope=BED_SLOPE,
        manning_n=MANNING_N,
        section=section,
    )
    interior = DynamicWaveCellState(AREA_M2, equilibrium_discharge)
    left_discharge = resolve_characteristic_dynamic_wave_boundary(
        CharacteristicDynamicWaveBoundary(
            "left", "discharge_m3s", equilibrium_discharge, 0.0
        ),
        interior,
        section,
    )
    right_stage = resolve_characteristic_dynamic_wave_boundary(
        CharacteristicDynamicWaveBoundary(
            "right",
            "free_surface_elevation_m",
            section.depth_m(AREA_M2),
            0.0,
        ),
        interior,
        section,
    )
    supercritical_rejected = False
    try:
        resolve_characteristic_dynamic_wave_boundary(
            CharacteristicDynamicWaveBoundary(
                "left", "discharge_m3s", 40.0, 0.0
            ),
            DynamicWaveCellState(5.0, 40.0),
            section,
        )
    except ValueError as exc:
        supercritical_rejected = str(exc) == (
            "dynamic_wave_characteristic_boundary_interior_not_subcritical"
        )

    lake = _run_flat_lake(section)
    refinements = [
        _run_moving_uniform_flow(
            section,
            cell_count=cell_count,
            equilibrium_discharge_m3s=equilibrium_discharge,
        )
        for cell_count in CELL_COUNTS
    ]
    area_drifts = [item["maximum_relative_area_drift"] for item in refinements]
    discharge_drifts = [
        item["maximum_relative_discharge_drift"] for item in refinements
    ]
    area_ratios = [
        finer / coarser
        for coarser, finer in zip(area_drifts, area_drifts[1:])
    ]
    discharge_ratios = [
        finer / coarser
        for coarser, finer in zip(discharge_drifts, discharge_drifts[1:])
    ]
    diagnostic_cases = [lake, *refinements]
    gates = {
        "rectangular_potential_equals_two_c": rectangular_error <= 1e-12,
        "trapezoidal_potential_derivative_equals_c_over_a": (
            derivative_relative_error <= 1e-9
        ),
        "upstream_discharge_boundary_recovers_uniform_state": (
            abs(left_discharge.state.area_m2 - AREA_M2) <= 1e-10
            and left_discharge.state.discharge_m3s == equilibrium_discharge
        ),
        "downstream_stage_boundary_recovers_uniform_state": (
            abs(right_stage.state.area_m2 - AREA_M2) <= 1e-12
            and abs(
                right_stage.state.discharge_m3s - equilibrium_discharge
            )
            <= 1e-10
        ),
        "supercritical_interior_fails_closed": supercritical_rejected,
        "characteristic_flat_lake_identity_100_steps": (
            lake["maximum_area_drift_m2"] <= 1e-12
            and lake["maximum_absolute_discharge_m3s"] <= 1e-12
        ),
        "outgoing_invariant_residual_bounded": all(
            item["maximum_absolute_outgoing_invariant_residual_mps"]
            <= INVARIANT_ABSOLUTE_TOLERANCE_MPS
            for item in diagnostic_cases
        ),
        "all_step_volume_ledgers_close": all(
            item["maximum_absolute_step_volume_ledger_error_m3"]
            <= LEDGER_ABSOLUTE_TOLERANCE
            for item in diagnostic_cases
        ),
        "all_step_momentum_ledgers_close": all(
            item["maximum_absolute_step_momentum_ledger_error_m4s"]
            <= LEDGER_ABSOLUTE_TOLERANCE
            for item in diagnostic_cases
        ),
        "moving_flow_area_refinement_ratio_below_limit": all(
            ratio <= REFINEMENT_ERROR_RATIO_LIMIT for ratio in area_ratios
        ),
        "moving_flow_discharge_refinement_ratio_below_limit": all(
            ratio <= REFINEMENT_ERROR_RATIO_LIMIT
            for ratio in discharge_ratios
        ),
        "fine_grid_area_drift_below_two_percent": (
            area_drifts[-1] <= FINE_RELATIVE_DRIFT_LIMIT
        ),
        "fine_grid_discharge_drift_below_two_percent": (
            discharge_drifts[-1] <= FINE_RELATIVE_DRIFT_LIMIT
        ),
        "moving_flow_cumulative_volume_ledgers_close": all(
            abs(item["cumulative_volume_ledger_error_m3"])
            <= LEDGER_ABSOLUTE_TOLERANCE
            for item in refinements
        ),
        "moving_flow_cumulative_momentum_ledgers_close": all(
            abs(item["cumulative_momentum_ledger_error_m4s"])
            <= LEDGER_ABSOLUTE_TOLERANCE
            for item in refinements
        ),
        "moving_flow_states_remain_wet_and_cfl_compliant": all(
            item["minimum_area_m2"] > 0.0
            and item["maximum_reported_courant_number"]
            <= COURANT_NUMBER + 2.0 * 2.220446049250313e-16
            for item in refinements
        ),
    }
    return {
        "schema": SCHEMA,
        "status": "subcritical_characteristic_boundary_diagnostic_gated",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_isolation": {
            "public_or_user_data_read": False,
            "action_values_read": False,
            "observation_values_read": False,
            "saved_prediction_values_read": False,
        },
        "boundary_contract": {
            "left_outgoing_invariant": "u - integral_0^A c(a)/a da",
            "right_outgoing_invariant": "u + integral_0^A c(a)/a da",
            "prescribed_quantities": [
                "area_m2",
                "discharge_m3s",
                "free_surface_elevation_m",
            ],
            "incoming_characteristics_per_boundary": 1,
            "subcritical_only": True,
            "dry_boundary_supported": False,
            "supercritical_boundary_supported": False,
            "transcritical_boundary_supported": False,
            "discharge_root_policy": (
                "nearest_subcritical_root_to_adjacent_interior_area"
            ),
        },
        "analytic_diagnostics": {
            "rectangular_potential_absolute_error_mps": rectangular_error,
            "trapezoidal_potential_derivative_relative_error": (
                derivative_relative_error
            ),
            "upstream_discharge_boundary": left_discharge.as_dict(),
            "downstream_stage_boundary": right_stage.as_dict(),
            "supercritical_interior_rejected": supercritical_rejected,
        },
        "flat_lake_at_rest": lake,
        "moving_uniform_flow": {
            "physical_length_m": PHYSICAL_LENGTH_M,
            "duration_seconds": DURATION_SECONDS,
            "cell_counts": list(CELL_COUNTS),
            "constant_area_m2": AREA_M2,
            "bed_slope": BED_SLOPE,
            "manning_n": MANNING_N,
            "manning_equilibrium_discharge_m3s": equilibrium_discharge,
            "upstream_boundary": "prescribed_discharge",
            "downstream_boundary": "prescribed_free_surface_elevation",
            "refinement_error_ratio_limit": REFINEMENT_ERROR_RATIO_LIMIT,
            "fine_relative_drift_limit": FINE_RELATIVE_DRIFT_LIMIT,
            "area_refinement_error_ratios": area_ratios,
            "discharge_refinement_error_ratios": discharge_ratios,
            "refinements": refinements,
        },
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "claim_boundary": {
            "subcritical_characteristic_boundaries_implemented": True,
            "upstream_discharge_boundary_implemented": True,
            "downstream_stage_boundary_implemented": True,
            "supercritical_characteristic_boundaries_implemented": False,
            "dry_characteristic_boundaries_implemented": False,
            "time_series_boundary_adapter_implemented": False,
            "variable_geometry_operator_implemented": False,
            "network_operator_implemented": False,
            "candidate_operator_admitted": False,
            "predictive_validation_complete": False,
            "geospatial_kernel_validated": False,
        },
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    report = compile_gates()
    _write_json(args.report, report)
    print(args.report)
    print(f"gate_count={len(report['gates'])}")
    print(f"all_gates_passed={report['all_gates_passed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
