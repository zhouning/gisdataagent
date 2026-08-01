#!/usr/bin/env python3
"""Compile outcome-free dynamic-wave bed, friction, and lateral source gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_flux import (
    DynamicWaveCellState,
    PrismaticDynamicWaveState,
    TrapezoidalChannelSection,
    maximum_stable_timestep_seconds,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_sources import (
    advance_hydrostatic_reconstruction_periodic,
    apply_lateral_inflow_source,
    apply_manning_slope_friction_source,
    manning_friction_slope,
    manning_uniform_discharge_m3s,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/dynamic_wave_source_gates.json"
)
SCHEMA = "gwm.geotransport.dynamic_wave_source_gates.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    return parser.parse_args()


def compile_gates() -> dict[str, Any]:
    section = TrapezoidalChannelSection(10.0, 2.0)
    bed = (0.0, 0.2, 0.5, 0.8, 0.5, 0.2)
    surface_elevation_m = 2.0
    lake_initial = PrismaticDynamicWaveState(
        area_m2=tuple(
            section.area_m2(surface_elevation_m - value) for value in bed
        ),
        discharge_m3s=(0.0,) * len(bed),
    )
    lake_state = lake_initial
    lake_maximum_discharge = 0.0
    lake_maximum_surface_change = 0.0
    lake_maximum_volume_error = 0.0
    lake_elapsed_seconds = 0.0
    for _ in range(100):
        timestep = maximum_stable_timestep_seconds(
            lake_state, section, cell_length_m=100.0, courant_number=0.5
        )
        step = advance_hydrostatic_reconstruction_periodic(
            lake_state,
            bed,
            section,
            cell_length_m=100.0,
            timestep_seconds=timestep,
            maximum_courant_number=0.5,
        )
        lake_state = step.state
        lake_elapsed_seconds += timestep
        lake_maximum_discharge = max(
            lake_maximum_discharge, step.maximum_absolute_discharge_m3s
        )
        lake_maximum_surface_change = max(
            lake_maximum_surface_change, step.maximum_free_surface_change_m
        )
        lake_maximum_volume_error = max(
            lake_maximum_volume_error, abs(step.volume_balance_error_m3)
        )

    area = 20.0
    slope = 0.002
    roughness = 0.035
    equilibrium_discharge = manning_uniform_discharge_m3s(
        area_m2=area,
        bed_slope=slope,
        manning_n=roughness,
        section=section,
    )
    equilibrium_state = PrismaticDynamicWaveState(
        area_m2=(area,) * 4,
        discharge_m3s=(equilibrium_discharge,) * 4,
    )
    equilibrium_step = apply_manning_slope_friction_source(
        equilibrium_state,
        section,
        bed_slope=(slope,) * 4,
        manning_n=(roughness,) * 4,
        timestep_seconds=300.0,
        cell_length_m=100.0,
    )
    equilibrium_friction_slope = manning_friction_slope(
        DynamicWaveCellState(area, equilibrium_discharge),
        section,
        manning_n=roughness,
    )

    friction_initial = PrismaticDynamicWaveState(
        area_m2=(20.0, 20.0),
        discharge_m3s=(30.0, 5.0),
    )
    friction_step = apply_manning_slope_friction_source(
        friction_initial,
        section,
        bed_slope=(0.0, 0.0),
        manning_n=(roughness, roughness),
        timestep_seconds=3_600.0,
        cell_length_m=100.0,
    )

    lateral_initial = PrismaticDynamicWaveState(
        area_m2=(10.0, 20.0),
        discharge_m3s=(5.0, 8.0),
    )
    lateral_zero_momentum = apply_lateral_inflow_source(
        lateral_initial,
        lateral_inflow_m2s=(0.1, 0.2),
        timestep_seconds=10.0,
        cell_length_m=100.0,
        momentum_convention="zero_longitudinal_momentum",
    )
    lateral_matched_velocity = apply_lateral_inflow_source(
        lateral_initial,
        lateral_inflow_m2s=(0.1, 0.2),
        timestep_seconds=10.0,
        cell_length_m=100.0,
        momentum_convention="matched_local_velocity",
    )
    initial_velocity = tuple(
        discharge / cell_area
        for cell_area, discharge in zip(
            lateral_initial.area_m2,
            lateral_initial.discharge_m3s,
            strict=True,
        )
    )
    matched_velocity = tuple(
        discharge / cell_area
        for cell_area, discharge in zip(
            lateral_matched_velocity.state.area_m2,
            lateral_matched_velocity.state.discharge_m3s,
            strict=True,
        )
    )

    gates = {
        "lake_at_rest_area_identity_100_steps": lake_state.area_m2
        == lake_initial.area_m2,
        "lake_at_rest_discharge_identity_100_steps": max(
            abs(value) for value in lake_state.discharge_m3s
        )
        <= 1e-12,
        "lake_at_rest_no_spurious_discharge": lake_maximum_discharge <= 1e-12,
        "lake_at_rest_surface_unchanged": lake_maximum_surface_change <= 1e-12,
        "lake_at_rest_volume_closed": lake_maximum_volume_error <= 1e-10,
        "manning_uniform_friction_equals_bed_slope": abs(
            equilibrium_friction_slope - slope
        )
        <= 1e-14,
        "manning_uniform_source_is_exact_identity": equilibrium_step.state
        == equilibrium_state,
        "flat_bed_friction_preserves_area": friction_step.state.area_m2
        == friction_initial.area_m2,
        "flat_bed_friction_dissipates_discharge": all(
            0.0 < after < before
            for after, before in zip(
                friction_step.state.discharge_m3s,
                friction_initial.discharge_m3s,
                strict=True,
            )
        ),
        "flat_bed_friction_preserves_direction": (
            friction_step.flow_direction_preserved
        ),
        "lateral_zero_momentum_volume_closed": abs(
            lateral_zero_momentum.volume_balance_error_m3
        )
        <= 1e-12,
        "lateral_zero_momentum_discharge_unchanged": (
            lateral_zero_momentum.state.discharge_m3s
            == lateral_initial.discharge_m3s
        ),
        "lateral_matched_velocity_volume_closed": abs(
            lateral_matched_velocity.volume_balance_error_m3
        )
        <= 1e-12,
        "lateral_matched_velocity_preserves_velocity": all(
            abs(after - before) <= 1e-14
            for after, before in zip(
                matched_velocity, initial_velocity, strict=True
            )
        ),
    }
    return {
        "schema": SCHEMA,
        "status": "separate_dynamic_wave_source_primitives_gated",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_isolation": {
            "public_or_user_data_read": False,
            "action_values_read": False,
            "observation_values_read": False,
            "saved_prediction_values_read": False,
        },
        "hydrostatic_reconstruction": {
            "method": "Audusse-style interface bed maximum and pressure correction",
            "step_count": 100,
            "elapsed_seconds": lake_elapsed_seconds,
            "bed_elevation_m": list(bed),
            "free_surface_elevation_m": surface_elevation_m,
            "maximum_absolute_discharge_m3s": lake_maximum_discharge,
            "maximum_free_surface_change_m": lake_maximum_surface_change,
            "maximum_absolute_step_volume_error_m3": lake_maximum_volume_error,
        },
        "manning_source": {
            "integration": (
                "analytic fixed-area solution of dQ/dt = g A (S0-Sf) "
                "for nonnegative Q"
            ),
            "equilibrium_area_m2": area,
            "equilibrium_bed_slope": slope,
            "equilibrium_manning_n": roughness,
            "equilibrium_discharge_m3s": equilibrium_discharge,
            "computed_friction_slope": equilibrium_friction_slope,
            "equilibrium_step": equilibrium_step.as_dict(),
            "flat_bed_friction_step": friction_step.as_dict(),
        },
        "lateral_inflow_source": {
            "negative_lateral_inflow_supported": False,
            "zero_longitudinal_momentum": lateral_zero_momentum.as_dict(),
            "matched_local_velocity": lateral_matched_velocity.as_dict(),
        },
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "claim_boundary": {
            "hydrostatic_bed_primitive_implemented": True,
            "manning_slope_friction_primitive_implemented": True,
            "lateral_volume_source_implemented": True,
            "source_primitives_coupled_with_homogeneous_flux": False,
            "variable_geometry_operator_implemented": False,
            "network_operator_implemented": False,
            "candidate_operator_admitted": False,
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
