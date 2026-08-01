#!/usr/bin/env python3
"""Compile outcome-free homogeneous dynamic-wave finite-volume gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_flux import (
    STANDARD_GRAVITY_MPS2,
    DynamicWaveCellState,
    PrismaticDynamicWaveState,
    TrapezoidalChannelSection,
    advance_prismatic_dynamic_wave_periodic,
    dynamic_wave_characteristic_speeds_mps,
    dynamic_wave_physical_flux,
    hll_dynamic_wave_flux,
    local_inertial_physical_flux,
    maximum_stable_timestep_seconds,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/dynamic_wave_homogeneous_gates.json"
)
SCHEMA = "gwm.geotransport.dynamic_wave_homogeneous_gates.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    return parser.parse_args()


def compile_gates() -> dict[str, Any]:
    section = TrapezoidalChannelSection(
        bottom_width_m=10.0,
        side_slope_horizontal_per_vertical=2.0,
    )
    area = 20.0
    epsilon = 1e-5
    pressure_plus = dynamic_wave_physical_flux(
        DynamicWaveCellState(area + epsilon, 0.0), section
    ).momentum_flux_m4s2
    pressure_minus = dynamic_wave_physical_flux(
        DynamicWaveCellState(area - epsilon, 0.0), section
    ).momentum_flux_m4s2
    pressure_derivative = (pressure_plus - pressure_minus) / (2.0 * epsilon)
    expected_pressure_derivative = (
        STANDARD_GRAVITY_MPS2 * area / section.top_width_m(area)
    )
    pressure_relative_error = abs(
        pressure_derivative - expected_pressure_derivative
    ) / expected_pressure_derivative

    decomposition_state = DynamicWaveCellState(20.0, 30.0)
    dynamic_flux = dynamic_wave_physical_flux(decomposition_state, section)
    inertial_flux = local_inertial_physical_flux(decomposition_state, section)
    expected_convective_flux = (
        decomposition_state.discharge_m3s**2 / decomposition_state.area_m2
    )
    decomposition_error = abs(
        dynamic_flux.momentum_flux_m4s2
        - inertial_flux.momentum_flux_m4s2
        - expected_convective_flux
    )

    subcritical_state = DynamicWaveCellState(20.0, 5.0)
    subcritical_speeds = dynamic_wave_characteristic_speeds_mps(
        subcritical_state, section
    )
    subcritical_flux = hll_dynamic_wave_flux(
        subcritical_state, DynamicWaveCellState(18.0, 4.0), section
    )
    supercritical_left = DynamicWaveCellState(5.0, 40.0)
    supercritical_right = DynamicWaveCellState(4.0, 32.0)
    supercritical_speeds = dynamic_wave_characteristic_speeds_mps(
        supercritical_left, section
    )
    supercritical_flux = hll_dynamic_wave_flux(
        supercritical_left, supercritical_right, section
    )
    supercritical_physical = dynamic_wave_physical_flux(supercritical_left, section)

    uniform = PrismaticDynamicWaveState(
        area_m2=(20.0,) * 8,
        discharge_m3s=(5.0,) * 8,
    )
    uniform_timestep = maximum_stable_timestep_seconds(
        uniform, section, cell_length_m=100.0, courant_number=0.8
    )
    uniform_step = advance_prismatic_dynamic_wave_periodic(
        uniform,
        section,
        cell_length_m=100.0,
        timestep_seconds=uniform_timestep,
        maximum_courant_number=0.8,
    )

    dry_bed = PrismaticDynamicWaveState(
        area_m2=(30.0,) * 32 + (0.0,) * 32,
        discharge_m3s=(0.0,) * 64,
    )
    initial_volume = sum(dry_bed.area_m2) * 100.0
    initial_momentum = sum(dry_bed.discharge_m3s) * 100.0
    state = dry_bed
    elapsed_seconds = 0.0
    minimum_area_m2 = min(state.area_m2)
    maximum_reported_courant = 0.0
    for _ in range(100):
        timestep = maximum_stable_timestep_seconds(
            state, section, cell_length_m=100.0, courant_number=0.5
        )
        step = advance_prismatic_dynamic_wave_periodic(
            state,
            section,
            cell_length_m=100.0,
            timestep_seconds=timestep,
            maximum_courant_number=0.5,
        )
        state = step.state
        elapsed_seconds += timestep
        minimum_area_m2 = min(minimum_area_m2, step.minimum_area_m2)
        maximum_reported_courant = max(
            maximum_reported_courant, step.maximum_courant_number
        )
    final_volume = sum(state.area_m2) * 100.0
    final_momentum = sum(state.discharge_m3s) * 100.0
    volume_error = final_volume - initial_volume
    momentum_error = final_momentum - initial_momentum

    gates = {
        "hydrostatic_pressure_derivative_matches_c_squared": (
            pressure_relative_error <= 1e-9
        ),
        "local_inertial_limit_is_explicit_flux_decomposition": (
            decomposition_error <= 1e-12
        ),
        "subcritical_characteristics_straddle_zero": (
            subcritical_speeds[0] < 0.0 < subcritical_speeds[1]
        ),
        "subcritical_hll_flux_finite": all(
            abs(value) < float("inf") for value in subcritical_flux.flux.as_array()
        ),
        "supercritical_characteristics_are_downstream": (
            supercritical_speeds[0] > 0.0
            and supercritical_speeds[1] > 0.0
        ),
        "supercritical_hll_uses_upstream_physical_flux": (
            supercritical_flux.flux == supercritical_physical
        ),
        "uniform_periodic_state_is_exact_identity": uniform_step.state == uniform,
        "uniform_periodic_volume_conserved": (
            uniform_step.volume_balance_error_m3 == 0.0
        ),
        "uniform_periodic_momentum_conserved": (
            uniform_step.discharge_integral_balance_error_m4s == 0.0
        ),
        "dry_bed_100_step_area_nonnegative": minimum_area_m2 >= 0.0,
        "dry_bed_100_step_volume_conserved": abs(volume_error) <= 1e-9,
        "dry_bed_100_step_momentum_conserved": abs(momentum_error) <= 1e-9,
        "dry_bed_100_step_cfl_respected": maximum_reported_courant <= (
            0.5 + 2.0 * 2.220446049250313e-16
        ),
    }
    return {
        "schema": SCHEMA,
        "status": "homogeneous_dynamic_wave_candidate_gates_compiled",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_isolation": {
            "public_or_user_data_read": False,
            "action_values_read": False,
            "observation_values_read": False,
            "saved_prediction_values_read": False,
        },
        "equation_contract": {
            "state": ["wetted_area_A_m2", "discharge_Q_m3s"],
            "area_flux": "Q",
            "momentum_flux": "Q^2/A + g I1(A)",
            "gravity_characteristics": "u plus_or_minus sqrt(gA/T)",
            "riemann_flux": "HLL",
            "spatial_domain": "periodic_prismatic_single_section",
            "bed_slope_source_included": False,
            "manning_friction_source_included": False,
            "lateral_inflow_source_included": False,
            "network_junction_coupling_included": False,
        },
        "analytic_diagnostics": {
            "pressure_flux_derivative_relative_error": pressure_relative_error,
            "local_inertial_decomposition_absolute_error_m4s2": (
                decomposition_error
            ),
            "subcritical_characteristic_speeds_mps": list(subcritical_speeds),
            "subcritical_hll_flux": subcritical_flux.as_dict(),
            "supercritical_characteristic_speeds_mps": list(
                supercritical_speeds
            ),
            "supercritical_hll_flux": supercritical_flux.as_dict(),
        },
        "uniform_identity_step": uniform_step.as_dict(),
        "dry_bed_100_step": {
            "cell_count": state.cell_count,
            "step_count": 100,
            "elapsed_seconds": elapsed_seconds,
            "minimum_area_m2": minimum_area_m2,
            "final_minimum_area_m2": min(state.area_m2),
            "volume_before_m3": initial_volume,
            "volume_after_m3": final_volume,
            "volume_balance_error_m3": volume_error,
            "discharge_integral_before_m4s": initial_momentum,
            "discharge_integral_after_m4s": final_momentum,
            "discharge_integral_balance_error_m4s": momentum_error,
            "maximum_reported_courant_number": maximum_reported_courant,
        },
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "claim_boundary": {
            "homogeneous_prismatic_flux_implemented": True,
            "subcritical_and_supercritical_riemann_gates_passed": all(
                gates[key]
                for key in (
                    "subcritical_characteristics_straddle_zero",
                    "subcritical_hll_flux_finite",
                    "supercritical_characteristics_are_downstream",
                    "supercritical_hll_uses_upstream_physical_flux",
                )
            ),
            "well_balanced_source_operator_implemented": False,
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
