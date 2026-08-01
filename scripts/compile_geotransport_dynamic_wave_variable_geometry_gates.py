#!/usr/bin/env python3
"""Compile outcome-free variable-geometry dynamic-wave gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_coupled import (
    FixedDynamicWaveBoundary,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_flux import (
    DynamicWaveCellState,
    PrismaticDynamicWaveState,
    TrapezoidalChannelSection,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_sources import (
    hydrostatic_reconstruction_hll_flux,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_variable_geometry import (
    advance_coupled_variable_geometry_open,
    apply_variable_geometry_manning_friction_only_source,
    arithmetic_interface_section,
    maximum_coupled_variable_geometry_open_stable_timestep_seconds,
    variable_geometry_hydrostatic_hll_flux,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/dynamic_wave_variable_geometry_gates.json"
)
SCHEMA = "gwm.geotransport.dynamic_wave_variable_geometry_gates.v1"

PHYSICAL_LENGTH_M = 2_400.0
DYNAMIC_DURATION_SECONDS = 120.0
CELL_COUNTS = (24, 48, 96)
COURANT_NUMBER = 0.4
BASE_DEPTH_M = 2.0
PERTURBATION_AMPLITUDE_M = 0.1
PERTURBATION_SIGMA_M = 180.0
DYNAMIC_MANNING_N = 1e-6
SELF_CONVERGENCE_RATIO_LIMIT = 0.8
LEDGER_ABSOLUTE_TOLERANCE = 1e-8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    return parser.parse_args()


def _smooth_section_at(x_m: float) -> TrapezoidalChannelSection:
    phase = 2.0 * math.pi * x_m / PHYSICAL_LENGTH_M
    return TrapezoidalChannelSection(
        bottom_width_m=10.0 + 2.0 * math.sin(phase),
        side_slope_horizontal_per_vertical=1.5 + 0.3 * math.cos(phase),
    )


def _run_variable_lake() -> dict[str, Any]:
    sections = (
        TrapezoidalChannelSection(8.0, 1.0),
        TrapezoidalChannelSection(12.0, 2.0),
        TrapezoidalChannelSection(6.0, 0.5),
        TrapezoidalChannelSection(10.0, 1.5),
    )
    bed = (0.2, 0.5, 0.8, 0.4)
    surface = 3.0
    length = 100.0
    state = PrismaticDynamicWaveState(
        tuple(
            section.area_m2(surface - elevation)
            for section, elevation in zip(sections, bed, strict=True)
        ),
        (0.0,) * len(sections),
    )
    initial = state
    left_section = TrapezoidalChannelSection(7.0, 0.8)
    right_section = TrapezoidalChannelSection(11.0, 1.8)
    left_bed = 0.0
    right_bed = 0.3
    left = FixedDynamicWaveBoundary(
        DynamicWaveCellState(
            left_section.area_m2(surface - left_bed), 0.0
        ),
        left_bed,
    )
    right = FixedDynamicWaveBoundary(
        DynamicWaveCellState(
            right_section.area_m2(surface - right_bed), 0.0
        ),
        right_bed,
    )
    elapsed = 0.0
    maximum_volume_residual = 0.0
    maximum_momentum_residual = 0.0
    maximum_surface_change = 0.0
    for _ in range(100):
        timestep = maximum_coupled_variable_geometry_open_stable_timestep_seconds(
            state,
            sections,
            left_boundary=left,
            right_boundary=right,
            left_boundary_section=left_section,
            right_boundary_section=right_section,
            cell_length_m=length,
            courant_number=COURANT_NUMBER,
        )
        if timestep is None:
            raise RuntimeError("variable_geometry_lake_timestep_undefined")
        step = advance_coupled_variable_geometry_open(
            state,
            bed,
            sections,
            left_boundary=left,
            right_boundary=right,
            left_boundary_section=left_section,
            right_boundary_section=right_section,
            manning_n=(0.035,) * len(sections),
            lateral_inflow_m2s=(0.0,) * len(sections),
            lateral_momentum_convention="zero_longitudinal_momentum",
            cell_length_m=length,
            timestep_seconds=timestep,
            maximum_courant_number=COURANT_NUMBER,
        )
        state = step.state
        elapsed += timestep
        maximum_volume_residual = max(
            maximum_volume_residual, abs(step.volume_balance_error_m3)
        )
        maximum_momentum_residual = max(
            maximum_momentum_residual, abs(step.momentum_ledger_error_m4s)
        )
        maximum_surface_change = max(
            maximum_surface_change,
            step.hydrostatic_step.maximum_free_surface_change_m,
        )
    return {
        "step_count": 100,
        "elapsed_seconds": elapsed,
        "cell_sections": [
            {
                "bottom_width_m": section.bottom_width_m,
                "side_slope_horizontal_per_vertical": (
                    section.side_slope_horizontal_per_vertical
                ),
            }
            for section in sections
        ],
        "bed_elevation_m": list(bed),
        "maximum_area_drift_m2": max(
            abs(after - before)
            for after, before in zip(state.area_m2, initial.area_m2, strict=True)
        ),
        "maximum_absolute_discharge_m3s": max(
            abs(value) for value in state.discharge_m3s
        ),
        "maximum_free_surface_change_m": maximum_surface_change,
        "maximum_absolute_step_volume_ledger_error_m3": (
            maximum_volume_residual
        ),
        "maximum_absolute_step_momentum_ledger_error_m4s": (
            maximum_momentum_residual
        ),
    }


def _run_dynamic_perturbation(cell_count: int) -> dict[str, Any]:
    cell_length = PHYSICAL_LENGTH_M / cell_count
    centers = np.asarray(
        [(index + 0.5) * cell_length for index in range(cell_count)],
        dtype=float,
    )
    sections = tuple(_smooth_section_at(float(x)) for x in centers)
    depths = BASE_DEPTH_M + PERTURBATION_AMPLITUDE_M * np.exp(
        -0.5
        * ((centers - 0.5 * PHYSICAL_LENGTH_M) / PERTURBATION_SIGMA_M) ** 2
    )
    state = PrismaticDynamicWaveState(
        tuple(
            section.area_m2(float(depth))
            for section, depth in zip(sections, depths, strict=True)
        ),
        (0.0,) * cell_count,
    )
    initial_volume = sum(state.area_m2) * cell_length
    initial_momentum = 0.0
    left_section = _smooth_section_at(-0.5 * cell_length)
    right_section = _smooth_section_at(
        PHYSICAL_LENGTH_M + 0.5 * cell_length
    )
    left = FixedDynamicWaveBoundary(
        DynamicWaveCellState(left_section.area_m2(BASE_DEPTH_M), 0.0), 0.0
    )
    right = FixedDynamicWaveBoundary(
        DynamicWaveCellState(right_section.area_m2(BASE_DEPTH_M), 0.0), 0.0
    )
    elapsed = 0.0
    step_count = 0
    boundary_volume = 0.0
    lateral_volume = 0.0
    lateral_momentum = 0.0
    friction_momentum = 0.0
    geometry_momentum = 0.0
    maximum_volume_residual = 0.0
    maximum_momentum_residual = 0.0
    maximum_courant = 0.0
    minimum_area = min(state.area_m2)
    while elapsed < DYNAMIC_DURATION_SECONDS:
        stable_timestep = (
            maximum_coupled_variable_geometry_open_stable_timestep_seconds(
                state,
                sections,
                left_boundary=left,
                right_boundary=right,
                left_boundary_section=left_section,
                right_boundary_section=right_section,
                cell_length_m=cell_length,
                courant_number=COURANT_NUMBER,
            )
        )
        if stable_timestep is None:
            raise RuntimeError("variable_geometry_dynamic_timestep_undefined")
        timestep = min(
            stable_timestep, DYNAMIC_DURATION_SECONDS - elapsed
        )
        step = advance_coupled_variable_geometry_open(
            state,
            (0.0,) * cell_count,
            sections,
            left_boundary=left,
            right_boundary=right,
            left_boundary_section=left_section,
            right_boundary_section=right_section,
            manning_n=(DYNAMIC_MANNING_N,) * cell_count,
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
        geometry_momentum += (
            step.boundary_geometry_and_bed_momentum_change_m4s
        )
        maximum_volume_residual = max(
            maximum_volume_residual, abs(step.volume_balance_error_m3)
        )
        maximum_momentum_residual = max(
            maximum_momentum_residual, abs(step.momentum_ledger_error_m4s)
        )
        maximum_courant = max(maximum_courant, step.maximum_courant_number)
        minimum_area = min(minimum_area, step.minimum_area_m2)
    final_volume = sum(state.area_m2) * cell_length
    final_momentum = sum(state.discharge_m3s) * cell_length
    final_depths = [
        section.depth_m(area)
        for section, area in zip(sections, state.area_m2, strict=True)
    ]
    return {
        "cell_count": cell_count,
        "cell_length_m": cell_length,
        "step_count": step_count,
        "elapsed_seconds": elapsed,
        "cell_center_m": [float(value) for value in centers],
        "final_depth_m": final_depths,
        "final_discharge_m3s": list(state.discharge_m3s),
        "minimum_area_m2": minimum_area,
        "maximum_reported_courant_number": maximum_courant,
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
            - geometry_momentum
        ),
    }


def _refinement_comparison(
    coarse: Mapping[str, Any], fine: Mapping[str, Any]
) -> dict[str, Any]:
    coarse_x = np.asarray(coarse["cell_center_m"], dtype=float)
    fine_x = np.asarray(fine["cell_center_m"], dtype=float)
    coarse_depth = np.asarray(coarse["final_depth_m"], dtype=float)
    fine_depth = np.asarray(fine["final_depth_m"], dtype=float)
    coarse_discharge = np.asarray(coarse["final_discharge_m3s"], dtype=float)
    fine_discharge = np.asarray(fine["final_discharge_m3s"], dtype=float)
    depth_error = np.abs(
        coarse_depth - np.interp(coarse_x, fine_x, fine_depth)
    )
    discharge_error = np.abs(
        coarse_discharge - np.interp(coarse_x, fine_x, fine_discharge)
    )
    return {
        "coarse_cell_count": coarse["cell_count"],
        "fine_cell_count": fine["cell_count"],
        "depth_l1_difference_m": float(depth_error.mean()),
        "depth_linf_difference_m": float(depth_error.max()),
        "discharge_l1_difference_m3s": float(discharge_error.mean()),
        "discharge_linf_difference_m3s": float(discharge_error.max()),
    }


def compile_gates() -> dict[str, Any]:
    section = TrapezoidalChannelSection(10.0, 2.0)
    left = DynamicWaveCellState(20.0, 5.0)
    right = DynamicWaveCellState(18.0, 4.0)
    baseline_flux = hydrostatic_reconstruction_hll_flux(
        left,
        right,
        left_bed_elevation_m=0.2,
        right_bed_elevation_m=0.5,
        section=section,
    )
    variable_flux = variable_geometry_hydrostatic_hll_flux(
        left,
        right,
        left_bed_elevation_m=0.2,
        right_bed_elevation_m=0.5,
        left_section=section,
        right_section=section,
    )
    reduction_errors = {
        "left_area_flux_absolute_error_m3s": abs(
            variable_flux.left_cell_flux.area_flux_m3s
            - baseline_flux.left_cell_flux.area_flux_m3s
        ),
        "left_momentum_flux_absolute_error_m4s2": abs(
            variable_flux.left_cell_flux.momentum_flux_m4s2
            - baseline_flux.left_cell_flux.momentum_flux_m4s2
        ),
        "right_area_flux_absolute_error_m3s": abs(
            variable_flux.right_cell_flux.area_flux_m3s
            - baseline_flux.right_cell_flux.area_flux_m3s
        ),
        "right_momentum_flux_absolute_error_m4s2": abs(
            variable_flux.right_cell_flux.momentum_flux_m4s2
            - baseline_flux.right_cell_flux.momentum_flux_m4s2
        ),
    }
    midpoint = arithmetic_interface_section(
        TrapezoidalChannelSection(8.0, 1.0),
        TrapezoidalChannelSection(12.0, 2.0),
    )
    friction_sections = (
        TrapezoidalChannelSection(8.0, 1.0),
        TrapezoidalChannelSection(12.0, 2.0),
    )
    friction_state = PrismaticDynamicWaveState(
        tuple(value.area_m2(2.0) for value in friction_sections),
        (30.0, -20.0),
    )
    friction = apply_variable_geometry_manning_friction_only_source(
        friction_state,
        friction_sections,
        manning_n=(0.035, 0.035),
        timestep_seconds=600.0,
        cell_length_m=100.0,
    )
    lake = _run_variable_lake()
    refinements = [_run_dynamic_perturbation(value) for value in CELL_COUNTS]
    comparisons = [
        _refinement_comparison(coarse, fine)
        for coarse, fine in zip(refinements, refinements[1:])
    ]
    ratio_keys = (
        "depth_l1_difference_m",
        "depth_linf_difference_m",
        "discharge_l1_difference_m3s",
        "discharge_linf_difference_m3s",
    )
    self_convergence_ratios = {
        key: comparisons[1][key] / comparisons[0][key] for key in ratio_keys
    }
    diagnostic_cases = [lake, *refinements]
    gates = {
        "identical_section_reduces_to_stage_two_flux": max(
            reduction_errors.values()
        )
        <= 1e-12,
        "interface_section_is_arithmetic_parameter_midpoint": (
            midpoint.bottom_width_m == 10.0
            and midpoint.side_slope_horizontal_per_vertical == 1.5
        ),
        "variable_geometry_lake_area_identity_100_steps": (
            lake["maximum_area_drift_m2"] <= 1e-12
        ),
        "variable_geometry_lake_no_spurious_flow_100_steps": (
            lake["maximum_absolute_discharge_m3s"] <= 1e-12
        ),
        "variable_geometry_lake_surface_unchanged": (
            lake["maximum_free_surface_change_m"] <= 1e-12
        ),
        "variable_geometry_friction_preserves_area": (
            friction.state.area_m2 == friction_state.area_m2
        ),
        "variable_geometry_friction_dissipates_both_directions": (
            0.0 < friction.state.discharge_m3s[0] < 30.0
            and -20.0 < friction.state.discharge_m3s[1] < 0.0
            and friction.flow_direction_preserved
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
        "dynamic_cumulative_volume_ledgers_close": all(
            abs(item["cumulative_volume_ledger_error_m3"])
            <= LEDGER_ABSOLUTE_TOLERANCE
            for item in refinements
        ),
        "dynamic_cumulative_momentum_ledgers_close": all(
            abs(item["cumulative_momentum_ledger_error_m4s"])
            <= LEDGER_ABSOLUTE_TOLERANCE
            for item in refinements
        ),
        "dynamic_depth_and_discharge_self_converge": all(
            value <= SELF_CONVERGENCE_RATIO_LIMIT
            for value in self_convergence_ratios.values()
        ),
        "dynamic_states_remain_wet": all(
            item["minimum_area_m2"] > 0.0 for item in refinements
        ),
        "dynamic_cfl_respected": all(
            item["maximum_reported_courant_number"]
            <= COURANT_NUMBER + 2.0 * 2.220446049250313e-16
            for item in refinements
        ),
    }
    return {
        "schema": SCHEMA,
        "status": "variable_geometry_dynamic_wave_diagnostic_gated",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_isolation": {
            "public_or_user_data_read": False,
            "action_values_read": False,
            "observation_values_read": False,
            "saved_prediction_values_read": False,
        },
        "geometry_contract": {
            "cell_section": "trapezoidal_section_per_cell",
            "interface_section_rule": "arithmetic_parameter_midpoint",
            "state_projection": "preserve_depth_and_velocity",
            "cell_flux_pressure_correction": (
                "cell_pressure_minus_reconstructed_interface_pressure"
            ),
            "contraction_expansion_loss_model": None,
            "surveyed_cross_section_adapter": None,
        },
        "identical_section_reduction": {
            "errors": reduction_errors,
            "variable_flux": variable_flux.as_dict(),
        },
        "variable_geometry_friction": friction.as_dict(),
        "variable_geometry_lake_at_rest": lake,
        "dynamic_refinement": {
            "physical_length_m": PHYSICAL_LENGTH_M,
            "duration_seconds": DYNAMIC_DURATION_SECONDS,
            "cell_counts": list(CELL_COUNTS),
            "base_depth_m": BASE_DEPTH_M,
            "perturbation_amplitude_m": PERTURBATION_AMPLITUDE_M,
            "perturbation_sigma_m": PERTURBATION_SIGMA_M,
            "bottom_width_range_m": [8.0, 12.0],
            "side_slope_range": [1.2, 1.8],
            "self_convergence_ratio_limit": SELF_CONVERGENCE_RATIO_LIMIT,
            "comparisons": comparisons,
            "self_convergence_ratios": self_convergence_ratios,
            "refinements": refinements,
            "analytic_solution_available": False,
            "comparison_semantics": (
                "fine_solution_linearly_interpolated_to_coarse_cell_centers"
            ),
        },
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "claim_boundary": {
            "variable_geometry_hydrostatic_flux_implemented": True,
            "variable_geometry_source_coupling_implemented": True,
            "variable_geometry_dynamic_self_convergence_gate_passed": (
                gates["dynamic_depth_and_discharge_self_converge"]
            ),
            "contraction_expansion_loss_model_implemented": False,
            "surveyed_cross_section_adapter_implemented": False,
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
