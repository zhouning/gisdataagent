#!/usr/bin/env python3
"""Compile outcome-free dynamic-wave confluence gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
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
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_junction import (
    DynamicWaveJunctionTerminal,
    DynamicWaveNetworkReach,
    advance_subcritical_confluence_network_open,
    maximum_subcritical_confluence_stable_timestep_seconds,
    solve_subcritical_dynamic_wave_confluence,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/dynamic_wave_junction_gates.json"
)
SCHEMA = "gwm.geotransport.dynamic_wave_junction_gates.v1"

COURANT_NUMBER = 0.4
LEDGER_ABSOLUTE_TOLERANCE = 1e-8
NODE_MASS_RATE_TOLERANCE_M3S = 2e-12
INVARIANT_ABSOLUTE_TOLERANCE_MPS = 2e-12
DYNAMIC_REACH_LENGTH_M = 800.0
DYNAMIC_DURATION_SECONDS = 120.0
DYNAMIC_CELL_COUNTS = (16, 32, 64)
SELF_CONVERGENCE_RATIO_LIMIT = 0.85
BASE_DEPTH_M = 2.0
UPSTREAM_A_BASE_DISCHARGE_M3S = 3.0
UPSTREAM_B_BASE_DISCHARGE_M3S = 2.0
DOWNSTREAM_BASE_DISCHARGE_M3S = 5.0
PERTURBATION_AMPLITUDE_M = 0.05
PERTURBATION_CENTER_M = 500.0
PERTURBATION_SIGMA_M = 90.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    return parser.parse_args()


def _terminal(
    branch_id: str,
    *,
    section: TrapezoidalChannelSection,
    bed: float,
    surface: float,
    discharge: float,
) -> DynamicWaveJunctionTerminal:
    return DynamicWaveJunctionTerminal(
        branch_id=branch_id,
        interior_state=DynamicWaveCellState(
            section.area_m2(surface - bed), discharge
        ),
        section=section,
        bed_elevation_m=bed,
    )


def _replace_state(
    reach: DynamicWaveNetworkReach,
    state: PrismaticDynamicWaveState,
) -> DynamicWaveNetworkReach:
    return DynamicWaveNetworkReach(
        reach_id=reach.reach_id,
        state=state,
        bed_elevation_m=reach.bed_elevation_m,
        sections=reach.sections,
        cell_length_m=reach.cell_length_m,
        manning_n=reach.manning_n,
        lateral_inflow_m2s=reach.lateral_inflow_m2s,
    )


def _run_variable_geometry_lake_network() -> dict[str, Any]:
    surface = 3.0
    cell_length = 100.0
    section_axes = (
        tuple(
            TrapezoidalChannelSection(width, 1.0)
            for width in (8.0, 9.0, 10.0, 11.0)
        ),
        tuple(
            TrapezoidalChannelSection(width, 0.5)
            for width in (6.0, 7.0, 8.0, 9.0)
        ),
        tuple(
            TrapezoidalChannelSection(width, 2.0)
            for width in (12.0, 11.0, 10.0, 9.0)
        ),
    )
    bed_axes = (
        (0.4, 0.3, 0.2, 0.1),
        (0.7, 0.5, 0.3, 0.1),
        (0.1, 0.05, 0.0, -0.05),
    )
    reaches = []
    for reach_id, sections, bed in zip(
        ("up-a", "up-b", "down"), section_axes, bed_axes, strict=True
    ):
        reaches.append(
            DynamicWaveNetworkReach(
                reach_id=reach_id,
                state=PrismaticDynamicWaveState(
                    tuple(
                        section.area_m2(surface - elevation)
                        for section, elevation in zip(
                            sections, bed, strict=True
                        )
                    ),
                    (0.0,) * len(sections),
                ),
                bed_elevation_m=bed,
                sections=sections,
                cell_length_m=cell_length,
                manning_n=(0.035,) * len(sections),
                lateral_inflow_m2s=(0.0,) * len(sections),
            )
        )
    initial_states = tuple(value.state for value in reaches)
    left_boundaries = tuple(
        FixedDynamicWaveBoundary(
            DynamicWaveCellState(
                reach.sections[0].area_m2(
                    surface - reach.bed_elevation_m[0]
                ),
                0.0,
            ),
            reach.bed_elevation_m[0],
        )
        for reach in reaches[:2]
    )
    downstream_right = FixedDynamicWaveBoundary(
        DynamicWaveCellState(
            reaches[2].sections[-1].area_m2(
                surface - reaches[2].bed_elevation_m[-1]
            ),
            0.0,
        ),
        reaches[2].bed_elevation_m[-1],
    )
    initial_volume = sum(
        sum(reach.state.area_m2) * reach.cell_length_m for reach in reaches
    )
    elapsed = 0.0
    external_volume = 0.0
    lateral_volume = 0.0
    junction_residual_volume = 0.0
    maximum_node_residual = 0.0
    maximum_network_residual = 0.0
    maximum_reach_volume_residual = 0.0
    maximum_reach_momentum_residual = 0.0
    maximum_invariant_residual = 0.0
    for _ in range(100):
        timestep = maximum_subcritical_confluence_stable_timestep_seconds(
            tuple(reaches[:2]),
            reaches[2],
            upstream_left_boundaries=left_boundaries,
            downstream_right_boundary=downstream_right,
            courant_number=COURANT_NUMBER,
        )
        step = advance_subcritical_confluence_network_open(
            tuple(reaches[:2]),
            reaches[2],
            upstream_left_boundaries=left_boundaries,
            downstream_right_boundary=downstream_right,
            lateral_momentum_convention="zero_longitudinal_momentum",
            timestep_seconds=timestep,
            maximum_courant_number=COURANT_NUMBER,
        )
        reaches = [
            _replace_state(reaches[0], step.upstream_states[0]),
            _replace_state(reaches[1], step.upstream_states[1]),
            _replace_state(reaches[2], step.downstream_state),
        ]
        elapsed += timestep
        external_volume += step.external_boundary_volume_change_m3
        lateral_volume += step.lateral_volume_change_m3
        junction_residual_volume += (
            step.junction_mass_balance_residual_volume_m3
        )
        maximum_node_residual = max(
            maximum_node_residual,
            abs(step.junction.junction_mass_balance_residual_m3s),
        )
        maximum_network_residual = max(
            maximum_network_residual,
            abs(step.network_volume_balance_error_m3),
        )
        maximum_reach_volume_residual = max(
            maximum_reach_volume_residual,
            step.maximum_absolute_reach_volume_ledger_error_m3,
        )
        maximum_reach_momentum_residual = max(
            maximum_reach_momentum_residual,
            step.maximum_absolute_reach_momentum_ledger_error_m4s,
        )
        maximum_invariant_residual = max(
            maximum_invariant_residual,
            step.junction.maximum_absolute_outgoing_invariant_residual_mps,
        )
    final_volume = sum(
        sum(reach.state.area_m2) * reach.cell_length_m for reach in reaches
    )
    return {
        "step_count": 100,
        "elapsed_seconds": elapsed,
        "maximum_area_drift_m2": max(
            abs(after - before)
            for reach, initial in zip(reaches, initial_states, strict=True)
            for after, before in zip(
                reach.state.area_m2, initial.area_m2, strict=True
            )
        ),
        "maximum_absolute_discharge_m3s": max(
            abs(value)
            for reach in reaches
            for value in reach.state.discharge_m3s
        ),
        "maximum_node_mass_balance_residual_m3s": maximum_node_residual,
        "maximum_outgoing_invariant_residual_mps": (
            maximum_invariant_residual
        ),
        "maximum_network_volume_balance_error_m3": maximum_network_residual,
        "maximum_reach_volume_ledger_error_m3": (
            maximum_reach_volume_residual
        ),
        "maximum_reach_momentum_ledger_error_m4s": (
            maximum_reach_momentum_residual
        ),
        "cumulative_network_volume_balance_error_m3": (
            final_volume
            - initial_volume
            - lateral_volume
            - external_volume
            + junction_residual_volume
        ),
    }


def _dynamic_reaches(
    cell_count: int,
) -> tuple[
    list[DynamicWaveNetworkReach],
    tuple[FixedDynamicWaveBoundary, ...],
    FixedDynamicWaveBoundary,
    np.ndarray,
]:
    section = TrapezoidalChannelSection(10.0, 2.0)
    base_area = section.area_m2(BASE_DEPTH_M)
    cell_length = DYNAMIC_REACH_LENGTH_M / cell_count
    centers = np.asarray(
        [(index + 0.5) * cell_length for index in range(cell_count)],
        dtype=float,
    )
    upstream_a_depth = BASE_DEPTH_M + PERTURBATION_AMPLITUDE_M * np.exp(
        -0.5
        * ((centers - PERTURBATION_CENTER_M) / PERTURBATION_SIGMA_M) ** 2
    )
    states = (
        PrismaticDynamicWaveState(
            tuple(section.area_m2(float(value)) for value in upstream_a_depth),
            (UPSTREAM_A_BASE_DISCHARGE_M3S,) * cell_count,
        ),
        PrismaticDynamicWaveState(
            (base_area,) * cell_count,
            (UPSTREAM_B_BASE_DISCHARGE_M3S,) * cell_count,
        ),
        PrismaticDynamicWaveState(
            (base_area,) * cell_count,
            (DOWNSTREAM_BASE_DISCHARGE_M3S,) * cell_count,
        ),
    )
    reaches = [
        DynamicWaveNetworkReach(
            reach_id=reach_id,
            state=state,
            bed_elevation_m=(0.0,) * cell_count,
            sections=(section,) * cell_count,
            cell_length_m=cell_length,
            manning_n=(1e-6,) * cell_count,
            lateral_inflow_m2s=(0.0,) * cell_count,
        )
        for reach_id, state in zip(
            ("up-a", "up-b", "down"), states, strict=True
        )
    ]
    left_boundaries = (
        FixedDynamicWaveBoundary(
            DynamicWaveCellState(
                base_area, UPSTREAM_A_BASE_DISCHARGE_M3S
            ),
            0.0,
        ),
        FixedDynamicWaveBoundary(
            DynamicWaveCellState(
                base_area, UPSTREAM_B_BASE_DISCHARGE_M3S
            ),
            0.0,
        ),
    )
    downstream_right = FixedDynamicWaveBoundary(
        DynamicWaveCellState(base_area, DOWNSTREAM_BASE_DISCHARGE_M3S),
        0.0,
    )
    return reaches, left_boundaries, downstream_right, centers


def _run_dynamic_network(cell_count: int) -> dict[str, Any]:
    reaches, left_boundaries, downstream_right, centers = _dynamic_reaches(
        cell_count
    )
    initial_volume = sum(
        sum(reach.state.area_m2) * reach.cell_length_m for reach in reaches
    )
    elapsed = 0.0
    step_count = 0
    external_volume = 0.0
    lateral_volume = 0.0
    junction_residual_volume = 0.0
    maximum_node_residual = 0.0
    maximum_network_residual = 0.0
    maximum_reach_volume_residual = 0.0
    maximum_reach_momentum_residual = 0.0
    maximum_invariant_residual = 0.0
    maximum_courant = 0.0
    minimum_area = min(
        value for reach in reaches for value in reach.state.area_m2
    )
    final_junction_surface = None
    while elapsed < DYNAMIC_DURATION_SECONDS:
        stable_timestep = (
            maximum_subcritical_confluence_stable_timestep_seconds(
                tuple(reaches[:2]),
                reaches[2],
                upstream_left_boundaries=left_boundaries,
                downstream_right_boundary=downstream_right,
                courant_number=COURANT_NUMBER,
            )
        )
        timestep = min(
            stable_timestep, DYNAMIC_DURATION_SECONDS - elapsed
        )
        step = advance_subcritical_confluence_network_open(
            tuple(reaches[:2]),
            reaches[2],
            upstream_left_boundaries=left_boundaries,
            downstream_right_boundary=downstream_right,
            lateral_momentum_convention="zero_longitudinal_momentum",
            timestep_seconds=timestep,
            maximum_courant_number=COURANT_NUMBER,
        )
        reaches = [
            _replace_state(reaches[0], step.upstream_states[0]),
            _replace_state(reaches[1], step.upstream_states[1]),
            _replace_state(reaches[2], step.downstream_state),
        ]
        elapsed += timestep
        step_count += 1
        external_volume += step.external_boundary_volume_change_m3
        lateral_volume += step.lateral_volume_change_m3
        junction_residual_volume += (
            step.junction_mass_balance_residual_volume_m3
        )
        maximum_node_residual = max(
            maximum_node_residual,
            abs(step.junction.junction_mass_balance_residual_m3s),
        )
        maximum_network_residual = max(
            maximum_network_residual,
            abs(step.network_volume_balance_error_m3),
        )
        maximum_reach_volume_residual = max(
            maximum_reach_volume_residual,
            step.maximum_absolute_reach_volume_ledger_error_m3,
        )
        maximum_reach_momentum_residual = max(
            maximum_reach_momentum_residual,
            step.maximum_absolute_reach_momentum_ledger_error_m4s,
        )
        maximum_invariant_residual = max(
            maximum_invariant_residual,
            step.junction.maximum_absolute_outgoing_invariant_residual_mps,
        )
        maximum_courant = max(maximum_courant, step.maximum_courant_number)
        minimum_area = min(minimum_area, step.minimum_area_m2)
        final_junction_surface = (
            step.junction.common_free_surface_elevation_m
        )
    final_volume = sum(
        sum(reach.state.area_m2) * reach.cell_length_m for reach in reaches
    )
    section = reaches[0].sections[0]
    depth_profiles = [
        [section.depth_m(value) for value in reach.state.area_m2]
        for reach in reaches
    ]
    discharge_profiles = [
        list(reach.state.discharge_m3s) for reach in reaches
    ]
    return {
        "cell_count_per_reach": cell_count,
        "cell_length_m": reaches[0].cell_length_m,
        "step_count": step_count,
        "elapsed_seconds": elapsed,
        "cell_center_m": [float(value) for value in centers],
        "final_depth_profiles_m": depth_profiles,
        "final_discharge_profiles_m3s": discharge_profiles,
        "final_junction_surface_elevation_m": final_junction_surface,
        "maximum_downstream_discharge_change_m3s": max(
            abs(value - DOWNSTREAM_BASE_DISCHARGE_M3S)
            for value in reaches[2].state.discharge_m3s
        ),
        "maximum_node_mass_balance_residual_m3s": maximum_node_residual,
        "maximum_outgoing_invariant_residual_mps": (
            maximum_invariant_residual
        ),
        "maximum_network_volume_balance_error_m3": maximum_network_residual,
        "maximum_reach_volume_ledger_error_m3": (
            maximum_reach_volume_residual
        ),
        "maximum_reach_momentum_ledger_error_m4s": (
            maximum_reach_momentum_residual
        ),
        "cumulative_network_volume_balance_error_m3": (
            final_volume
            - initial_volume
            - lateral_volume
            - external_volume
            + junction_residual_volume
        ),
        "maximum_reported_courant_number": maximum_courant,
        "minimum_area_m2": minimum_area,
    }


def _compare_refinements(
    coarse: Mapping[str, Any], fine: Mapping[str, Any]
) -> dict[str, Any]:
    coarse_x = np.asarray(coarse["cell_center_m"], dtype=float)
    fine_x = np.asarray(fine["cell_center_m"], dtype=float)
    depth_errors = []
    discharge_errors = []
    for coarse_depth, fine_depth, coarse_flow, fine_flow in zip(
        coarse["final_depth_profiles_m"],
        fine["final_depth_profiles_m"],
        coarse["final_discharge_profiles_m3s"],
        fine["final_discharge_profiles_m3s"],
        strict=True,
    ):
        depth_errors.extend(
            np.abs(
                np.asarray(coarse_depth)
                - np.interp(coarse_x, fine_x, np.asarray(fine_depth))
            )
        )
        discharge_errors.extend(
            np.abs(
                np.asarray(coarse_flow)
                - np.interp(coarse_x, fine_x, np.asarray(fine_flow))
            )
        )
    depth = np.asarray(depth_errors, dtype=float)
    discharge = np.asarray(discharge_errors, dtype=float)
    return {
        "coarse_cell_count_per_reach": coarse["cell_count_per_reach"],
        "fine_cell_count_per_reach": fine["cell_count_per_reach"],
        "depth_l1_difference_m": float(depth.mean()),
        "depth_linf_difference_m": float(depth.max()),
        "discharge_l1_difference_m3s": float(discharge.mean()),
        "discharge_linf_difference_m3s": float(discharge.max()),
    }


def compile_gates() -> dict[str, Any]:
    section = TrapezoidalChannelSection(10.0, 2.0)
    symmetric = solve_subcritical_dynamic_wave_confluence(
        (
            _terminal(
                "up-a",
                section=section,
                bed=0.0,
                surface=2.0,
                discharge=5.0,
            ),
            _terminal(
                "up-b",
                section=section,
                bed=0.0,
                surface=2.0,
                discharge=5.0,
            ),
        ),
        _terminal(
            "down",
            section=section,
            bed=0.0,
            surface=2.0,
            discharge=10.0,
        ),
    )
    manufactured = solve_subcritical_dynamic_wave_confluence(
        (
            _terminal(
                "up-a",
                section=TrapezoidalChannelSection(8.0, 1.0),
                bed=0.2,
                surface=3.0,
                discharge=3.0,
            ),
            _terminal(
                "up-b",
                section=TrapezoidalChannelSection(6.0, 0.5),
                bed=0.5,
                surface=3.0,
                discharge=4.0,
            ),
        ),
        _terminal(
            "down",
            section=TrapezoidalChannelSection(12.0, 2.0),
            bed=0.1,
            surface=3.0,
            discharge=7.0,
        ),
    )
    supercritical_rejected = False
    try:
        solve_subcritical_dynamic_wave_confluence(
            (
                DynamicWaveJunctionTerminal(
                    "up-a",
                    DynamicWaveCellState(5.0, 40.0),
                    section,
                    0.0,
                ),
                _terminal(
                    "up-b",
                    section=section,
                    bed=0.0,
                    surface=2.0,
                    discharge=5.0,
                ),
            ),
            _terminal(
                "down",
                section=section,
                bed=0.0,
                surface=2.0,
                discharge=10.0,
            ),
        )
    except ValueError as exc:
        supercritical_rejected = str(exc) == (
            "dynamic_wave_confluence_no_subcritical_root"
        )
    lake = _run_variable_geometry_lake_network()
    refinements = [
        _run_dynamic_network(value) for value in DYNAMIC_CELL_COUNTS
    ]
    comparisons = [
        _compare_refinements(coarse, fine)
        for coarse, fine in zip(refinements, refinements[1:])
    ]
    difference_keys = (
        "depth_l1_difference_m",
        "depth_linf_difference_m",
        "discharge_l1_difference_m3s",
        "discharge_linf_difference_m3s",
    )
    ratios = {
        key: comparisons[1][key] / comparisons[0][key]
        for key in difference_keys
    }
    network_cases = [lake, *refinements]
    gates = {
        "symmetric_junction_recovers_stage_and_discharge_sum": (
            abs(symmetric.common_free_surface_elevation_m - 2.0) <= 1e-12
            and abs(symmetric.downstream_discharge_m3s - 10.0) <= 1e-12
        ),
        "variable_geometry_manufactured_junction_recovered": (
            abs(manufactured.common_free_surface_elevation_m - 3.0) <= 1e-12
            and abs(manufactured.downstream_discharge_m3s - 7.0) <= 1e-12
        ),
        "supercritical_terminal_fails_closed": supercritical_rejected,
        "network_lake_area_identity_100_steps": (
            lake["maximum_area_drift_m2"] <= 1e-12
        ),
        "network_lake_no_spurious_flow_100_steps": (
            lake["maximum_absolute_discharge_m3s"] <= 1e-12
        ),
        "all_node_mass_rate_residuals_bounded": all(
            item["maximum_node_mass_balance_residual_m3s"]
            <= NODE_MASS_RATE_TOLERANCE_M3S
            for item in network_cases
        ),
        "all_node_invariant_residuals_bounded": all(
            item["maximum_outgoing_invariant_residual_mps"]
            <= INVARIANT_ABSOLUTE_TOLERANCE_MPS
            for item in network_cases
        ),
        "all_step_network_volume_ledgers_close": all(
            item["maximum_network_volume_balance_error_m3"]
            <= LEDGER_ABSOLUTE_TOLERANCE
            for item in network_cases
        ),
        "all_step_reach_volume_ledgers_close": all(
            item["maximum_reach_volume_ledger_error_m3"]
            <= LEDGER_ABSOLUTE_TOLERANCE
            for item in network_cases
        ),
        "all_step_reach_momentum_ledgers_close": all(
            item["maximum_reach_momentum_ledger_error_m4s"]
            <= LEDGER_ABSOLUTE_TOLERANCE
            for item in network_cases
        ),
        "all_cumulative_network_volume_ledgers_close": all(
            abs(item["cumulative_network_volume_balance_error_m3"])
            <= LEDGER_ABSOLUTE_TOLERANCE
            for item in network_cases
        ),
        "perturbation_crosses_junction_into_downstream": all(
            item["maximum_downstream_discharge_change_m3s"] > 0.01
            for item in refinements
        ),
        "network_depth_and_discharge_self_converge": all(
            value <= SELF_CONVERGENCE_RATIO_LIMIT
            for value in ratios.values()
        ),
        "dynamic_network_states_remain_wet_and_cfl_compliant": all(
            item["minimum_area_m2"] > 0.0
            and item["maximum_reported_courant_number"]
            <= COURANT_NUMBER + 2.0 * 2.220446049250313e-16
            for item in refinements
        ),
    }
    return {
        "schema": SCHEMA,
        "status": "subcritical_confluence_dynamic_wave_diagnostic_gated",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_isolation": {
            "public_or_user_data_read": False,
            "action_values_read": False,
            "observation_values_read": False,
            "saved_prediction_values_read": False,
        },
        "junction_contract": {
            "topology": "two_or_more_upstream_reaches_to_one_downstream_reach",
            "common_node_state": "free_surface_elevation",
            "mass_closure": "sum_Q_upstream_equals_Q_downstream",
            "branch_compatibility": (
                "one_outgoing_subcritical_characteristic_per_branch"
            ),
            "junction_storage_m3": 0.0,
            "junction_momentum_or_energy_closure": None,
            "bifurcation_supported": False,
            "supercritical_supported": False,
            "external_boundary_type": "fixed_ghost_state",
        },
        "analytic_diagnostics": {
            "symmetric_confluence": symmetric.as_dict(),
            "variable_geometry_manufactured_confluence": (
                manufactured.as_dict()
            ),
            "supercritical_terminal_rejected": supercritical_rejected,
        },
        "variable_geometry_lake_network": lake,
        "dynamic_refinement": {
            "reach_length_m": DYNAMIC_REACH_LENGTH_M,
            "duration_seconds": DYNAMIC_DURATION_SECONDS,
            "cell_counts_per_reach": list(DYNAMIC_CELL_COUNTS),
            "base_discharge_m3s": {
                "up-a": UPSTREAM_A_BASE_DISCHARGE_M3S,
                "up-b": UPSTREAM_B_BASE_DISCHARGE_M3S,
                "down": DOWNSTREAM_BASE_DISCHARGE_M3S,
            },
            "upstream_a_surface_perturbation": {
                "amplitude_m": PERTURBATION_AMPLITUDE_M,
                "center_m": PERTURBATION_CENTER_M,
                "sigma_m": PERTURBATION_SIGMA_M,
            },
            "self_convergence_ratio_limit": SELF_CONVERGENCE_RATIO_LIMIT,
            "comparisons": comparisons,
            "self_convergence_ratios": ratios,
            "refinements": refinements,
            "analytic_solution_available": False,
        },
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "claim_boundary": {
            "subcritical_multi_in_one_out_junction_implemented": True,
            "junction_common_stage_closure_implemented": True,
            "junction_mass_ledger_implemented": True,
            "synchronous_multi_reach_step_implemented": True,
            "junction_dynamic_self_convergence_gate_passed": (
                gates["network_depth_and_discharge_self_converge"]
            ),
            "junction_momentum_or_energy_closure_implemented": False,
            "bifurcation_junction_implemented": False,
            "general_dag_network_operator_implemented": False,
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
