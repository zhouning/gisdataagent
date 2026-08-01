#!/usr/bin/env python3
"""Compile outcome-free coupled single-reach dynamic-wave gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Mapping

from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_coupled import (
    FixedDynamicWaveBoundary,
    advance_coupled_dynamic_wave_open,
    maximum_open_stable_timestep_seconds,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_flux import (
    DynamicWaveCellState,
    PrismaticDynamicWaveState,
    TrapezoidalChannelSection,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_sources import (
    manning_uniform_discharge_m3s,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/dynamic_wave_coupled_gates.json"
)
SCHEMA = "gwm.geotransport.dynamic_wave_coupled_gates.v1"

PHYSICAL_LENGTH_M = 2_400.0
MOVING_FLOW_DURATION_SECONDS = 1_800.0
MOVING_FLOW_CELL_COUNTS = (24, 48, 96)
COURANT_NUMBER = 0.45
UNIFORM_AREA_M2 = 20.0
BED_SLOPE = 0.002
MANNING_N = 0.035
FINE_AREA_RELATIVE_DRIFT_LIMIT = 0.01
FINE_DISCHARGE_RELATIVE_DRIFT_LIMIT = 0.005
LEDGER_ABSOLUTE_TOLERANCE = 1e-8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    return parser.parse_args()


def _fixed_boundary(
    *, area_m2: float, discharge_m3s: float, bed_elevation_m: float
) -> FixedDynamicWaveBoundary:
    return FixedDynamicWaveBoundary(
        state=DynamicWaveCellState(area_m2, discharge_m3s),
        bed_elevation_m=bed_elevation_m,
    )


def _run_open_lake_at_rest(
    section: TrapezoidalChannelSection,
) -> dict[str, Any]:
    bed = (0.2, 0.5, 0.8, 0.5)
    surface = 2.0
    length = 100.0
    state = PrismaticDynamicWaveState(
        area_m2=tuple(section.area_m2(surface - value) for value in bed),
        discharge_m3s=(0.0,) * len(bed),
    )
    initial = state
    left = _fixed_boundary(
        area_m2=section.area_m2(surface),
        discharge_m3s=0.0,
        bed_elevation_m=0.0,
    )
    right = _fixed_boundary(
        area_m2=section.area_m2(surface - 0.2),
        discharge_m3s=0.0,
        bed_elevation_m=0.2,
    )
    elapsed = 0.0
    maximum_volume_ledger_error = 0.0
    maximum_momentum_ledger_error = 0.0
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
            raise RuntimeError("dynamic_wave_lake_timestep_undefined")
        step = advance_coupled_dynamic_wave_open(
            state,
            bed,
            section,
            left_boundary=left,
            right_boundary=right,
            manning_n=(MANNING_N,) * len(bed),
            lateral_inflow_m2s=(0.0,) * len(bed),
            lateral_momentum_convention="zero_longitudinal_momentum",
            cell_length_m=length,
            timestep_seconds=timestep,
            maximum_courant_number=COURANT_NUMBER,
        )
        state = step.state
        elapsed += timestep
        maximum_volume_ledger_error = max(
            maximum_volume_ledger_error, abs(step.volume_balance_error_m3)
        )
        maximum_momentum_ledger_error = max(
            maximum_momentum_ledger_error,
            abs(step.momentum_ledger_error_m4s),
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
        "maximum_absolute_step_volume_ledger_error_m3": (
            maximum_volume_ledger_error
        ),
        "maximum_absolute_step_momentum_ledger_error_m4s": (
            maximum_momentum_ledger_error
        ),
    }


def _run_ledger_probe(
    section: TrapezoidalChannelSection,
) -> dict[str, Any]:
    cell_count = 6
    length = 100.0
    state = PrismaticDynamicWaveState(
        area_m2=(UNIFORM_AREA_M2,) * cell_count,
        discharge_m3s=(5.0,) * cell_count,
    )
    boundary = _fixed_boundary(
        area_m2=UNIFORM_AREA_M2,
        discharge_m3s=5.0,
        bed_elevation_m=0.0,
    )
    step = advance_coupled_dynamic_wave_open(
        state,
        (0.0,) * cell_count,
        section,
        left_boundary=boundary,
        right_boundary=boundary,
        manning_n=(MANNING_N,) * cell_count,
        lateral_inflow_m2s=(0.01,) * cell_count,
        lateral_momentum_convention="matched_local_velocity",
        cell_length_m=length,
        timestep_seconds=1.0,
        maximum_courant_number=COURANT_NUMBER,
    )
    payload = step.as_dict()
    payload["maximum_absolute_step_volume_ledger_error_m3"] = abs(
        step.volume_balance_error_m3
    )
    payload["maximum_absolute_step_momentum_ledger_error_m4s"] = abs(
        step.momentum_ledger_error_m4s
    )
    return payload


def _run_moving_uniform_flow(
    section: TrapezoidalChannelSection,
    *,
    cell_count: int,
    equilibrium_discharge_m3s: float,
) -> dict[str, Any]:
    cell_length = PHYSICAL_LENGTH_M / cell_count
    bed = tuple(
        -BED_SLOPE * (index + 0.5) * cell_length
        for index in range(cell_count)
    )
    state = PrismaticDynamicWaveState(
        area_m2=(UNIFORM_AREA_M2,) * cell_count,
        discharge_m3s=(equilibrium_discharge_m3s,) * cell_count,
    )
    initial_volume = sum(state.area_m2) * cell_length
    initial_discharge_integral = sum(state.discharge_m3s) * cell_length
    left = _fixed_boundary(
        area_m2=UNIFORM_AREA_M2,
        discharge_m3s=equilibrium_discharge_m3s,
        bed_elevation_m=0.5 * BED_SLOPE * cell_length,
    )
    right = _fixed_boundary(
        area_m2=UNIFORM_AREA_M2,
        discharge_m3s=equilibrium_discharge_m3s,
        bed_elevation_m=-BED_SLOPE * (cell_count + 0.5) * cell_length,
    )
    elapsed = 0.0
    step_count = 0
    boundary_volume = 0.0
    lateral_volume = 0.0
    lateral_momentum = 0.0
    friction_momentum = 0.0
    boundary_and_bed_momentum = 0.0
    maximum_step_volume_ledger_error = 0.0
    maximum_step_momentum_ledger_error = 0.0
    maximum_courant = 0.0
    minimum_area = UNIFORM_AREA_M2
    while elapsed < MOVING_FLOW_DURATION_SECONDS:
        stable_timestep = maximum_open_stable_timestep_seconds(
            state,
            section,
            left_boundary=left,
            right_boundary=right,
            cell_length_m=cell_length,
            courant_number=COURANT_NUMBER,
        )
        if stable_timestep is None:
            raise RuntimeError("dynamic_wave_moving_timestep_undefined")
        timestep = min(
            stable_timestep, MOVING_FLOW_DURATION_SECONDS - elapsed
        )
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
        state = step.state
        elapsed += timestep
        step_count += 1
        boundary_volume += step.boundary_volume_change_m3
        lateral_volume += step.lateral_volume_change_m3
        lateral_momentum += step.lateral_momentum_change_m4s
        friction_momentum += step.friction_momentum_change_m4s
        boundary_and_bed_momentum += step.boundary_and_bed_momentum_change_m4s
        maximum_step_volume_ledger_error = max(
            maximum_step_volume_ledger_error, abs(step.volume_balance_error_m3)
        )
        maximum_step_momentum_ledger_error = max(
            maximum_step_momentum_ledger_error,
            abs(step.momentum_ledger_error_m4s),
        )
        maximum_courant = max(
            maximum_courant, step.maximum_courant_number
        )
        minimum_area = min(minimum_area, step.minimum_area_m2)

    final_volume = sum(state.area_m2) * cell_length
    final_discharge_integral = sum(state.discharge_m3s) * cell_length
    area_absolute_errors = [
        abs(value - UNIFORM_AREA_M2) for value in state.area_m2
    ]
    discharge_absolute_errors = [
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
        "maximum_absolute_area_drift_m2": max(area_absolute_errors),
        "mean_absolute_area_drift_m2": sum(area_absolute_errors) / cell_count,
        "maximum_relative_area_drift": max(area_absolute_errors)
        / UNIFORM_AREA_M2,
        "mean_relative_area_drift": sum(area_absolute_errors)
        / (cell_count * UNIFORM_AREA_M2),
        "maximum_absolute_discharge_drift_m3s": max(
            discharge_absolute_errors
        ),
        "mean_absolute_discharge_drift_m3s": sum(
            discharge_absolute_errors
        )
        / cell_count,
        "maximum_relative_discharge_drift": max(discharge_absolute_errors)
        / equilibrium_discharge_m3s,
        "mean_relative_discharge_drift": sum(discharge_absolute_errors)
        / (cell_count * equilibrium_discharge_m3s),
        "volume_before_m3": initial_volume,
        "boundary_volume_change_m3": boundary_volume,
        "lateral_volume_change_m3": lateral_volume,
        "volume_after_m3": final_volume,
        "cumulative_volume_ledger_error_m3": (
            final_volume - initial_volume - boundary_volume - lateral_volume
        ),
        "discharge_integral_before_m4s": initial_discharge_integral,
        "lateral_momentum_change_m4s": lateral_momentum,
        "friction_momentum_change_m4s": friction_momentum,
        "boundary_and_bed_momentum_change_m4s": boundary_and_bed_momentum,
        "discharge_integral_after_m4s": final_discharge_integral,
        "cumulative_momentum_ledger_error_m4s": (
            final_discharge_integral
            - initial_discharge_integral
            - lateral_momentum
            - friction_momentum
            - boundary_and_bed_momentum
        ),
        "maximum_absolute_step_volume_ledger_error_m3": (
            maximum_step_volume_ledger_error
        ),
        "maximum_absolute_step_momentum_ledger_error_m4s": (
            maximum_step_momentum_ledger_error
        ),
    }


def compile_gates() -> dict[str, Any]:
    section = TrapezoidalChannelSection(10.0, 2.0)
    equilibrium_discharge = manning_uniform_discharge_m3s(
        area_m2=UNIFORM_AREA_M2,
        bed_slope=BED_SLOPE,
        manning_n=MANNING_N,
        section=section,
    )
    lake = _run_open_lake_at_rest(section)
    ledger_probe = _run_ledger_probe(section)
    refinements = [
        _run_moving_uniform_flow(
            section,
            cell_count=cell_count,
            equilibrium_discharge_m3s=equilibrium_discharge,
        )
        for cell_count in MOVING_FLOW_CELL_COUNTS
    ]
    area_drifts = [item["maximum_relative_area_drift"] for item in refinements]
    discharge_drifts = [
        item["maximum_relative_discharge_drift"] for item in refinements
    ]
    all_ledger_cases = [lake, ledger_probe, *refinements]
    gates = {
        "open_lake_at_rest_area_preserved_100_steps": (
            lake["maximum_area_drift_m2"] <= 1e-12
        ),
        "open_lake_at_rest_no_spurious_discharge_100_steps": (
            lake["maximum_absolute_discharge_m3s"] <= 1e-12
        ),
        "all_step_volume_ledgers_close": all(
            item["maximum_absolute_step_volume_ledger_error_m3"]
            <= LEDGER_ABSOLUTE_TOLERANCE
            for item in all_ledger_cases
        ),
        "all_step_momentum_ledgers_close": all(
            item["maximum_absolute_step_momentum_ledger_error_m4s"]
            <= LEDGER_ABSOLUTE_TOLERANCE
            for item in all_ledger_cases
        ),
        "lateral_volume_is_explicit": math.isclose(
            ledger_probe["lateral_volume_change_m3"],
            6.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        ),
        "friction_contribution_is_dissipative": (
            ledger_probe["friction_momentum_change_m4s"] < 0.0
        ),
        "moving_flow_area_drift_decreases": all(
            finer < coarser
            for coarser, finer in zip(area_drifts, area_drifts[1:])
        ),
        "moving_flow_discharge_drift_decreases": all(
            finer < coarser
            for coarser, finer in zip(
                discharge_drifts, discharge_drifts[1:]
            )
        ),
        "fine_grid_area_drift_below_one_percent": (
            area_drifts[-1] <= FINE_AREA_RELATIVE_DRIFT_LIMIT
        ),
        "fine_grid_discharge_drift_below_half_percent": (
            discharge_drifts[-1] <= FINE_DISCHARGE_RELATIVE_DRIFT_LIMIT
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
        "moving_flow_states_remain_wet": all(
            item["minimum_area_m2"] > 0.0 for item in refinements
        ),
        "moving_flow_cfl_respected": all(
            item["maximum_reported_courant_number"]
            <= COURANT_NUMBER + 2.0 * 2.220446049250313e-16
            for item in refinements
        ),
    }
    return {
        "schema": SCHEMA,
        "status": "coupled_single_reach_dynamic_wave_diagnostic_gated",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_isolation": {
            "public_or_user_data_read": False,
            "action_values_read": False,
            "observation_values_read": False,
            "saved_prediction_values_read": False,
        },
        "equation_contract": {
            "state": ["wetted_area_A_m2", "discharge_Q_m3s"],
            "source_split_order": [
                "lateral_half",
                "friction_half",
                "hydrostatic_flux_full",
                "friction_half",
                "lateral_half",
            ],
            "bed_acceleration_source": "hydrostatic_reconstruction_only",
            "friction_source": "fixed_area_minus_gA_Sf_only",
            "boundary_semantics": "fixed_ghost_state",
            "lateral_momentum_convention": "explicit_per_call",
        },
        "open_lake_at_rest": lake,
        "coupled_ledger_probe": ledger_probe,
        "moving_uniform_flow": {
            "physical_length_m": PHYSICAL_LENGTH_M,
            "duration_seconds": MOVING_FLOW_DURATION_SECONDS,
            "cell_counts": list(MOVING_FLOW_CELL_COUNTS),
            "constant_area_m2": UNIFORM_AREA_M2,
            "constant_depth_m": section.depth_m(UNIFORM_AREA_M2),
            "bed_slope": BED_SLOPE,
            "manning_n": MANNING_N,
            "manning_equilibrium_discharge_m3s": equilibrium_discharge,
            "courant_number": COURANT_NUMBER,
            "ghost_bed_semantics": "same_center_spacing_and_constant_slope",
            "fine_area_relative_drift_limit": (
                FINE_AREA_RELATIVE_DRIFT_LIMIT
            ),
            "fine_discharge_relative_drift_limit": (
                FINE_DISCHARGE_RELATIVE_DRIFT_LIMIT
            ),
            "refinements": refinements,
            "exact_moving_water_balance_required": False,
            "diagnostic": "grid_refined_fixed_duration_equilibrium_drift",
        },
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "claim_boundary": {
            "source_primitives_coupled_with_homogeneous_flux": True,
            "fixed_ghost_open_boundaries": True,
            "source_inclusive_mass_and_momentum_ledgers": True,
            "moving_uniform_flow_convergence_gate_passed": all(
                gates[key]
                for key in (
                    "moving_flow_area_drift_decreases",
                    "moving_flow_discharge_drift_decreases",
                    "fine_grid_area_drift_below_one_percent",
                    "fine_grid_discharge_drift_below_half_percent",
                )
            ),
            "characteristic_boundary_conditions_implemented": False,
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
