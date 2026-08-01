#!/usr/bin/env python3
"""Compile outcome-free dendritic dynamic-wave DAG gates."""

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
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_dag import (
    DynamicWaveDendriticTopology,
    advance_dendritic_dynamic_wave_network_open,
    maximum_dendritic_dynamic_wave_stable_timestep_seconds,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_flux import (
    DynamicWaveCellState,
    PrismaticDynamicWaveState,
    TrapezoidalChannelSection,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_junction import (
    DynamicWaveNetworkReach,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/dynamic_wave_dag_gates.json"
)
SCHEMA = "gwm.geotransport.dynamic_wave_dag_gates.v1"

TOPOLOGY = DynamicWaveDendriticTopology(
    reach_ids=("A", "B", "C", "D", "E"),
    downstream_reach_ids=("C", "C", "E", "E", None),
)
BASE_DISCHARGE_M3S = {"A": 2.0, "B": 3.0, "C": 5.0, "D": 4.0, "E": 9.0}
COURANT_NUMBER = 0.4
LEDGER_ABSOLUTE_TOLERANCE = 1e-8
NODE_MASS_RATE_TOLERANCE_M3S = 2e-12
INVARIANT_ABSOLUTE_TOLERANCE_MPS = 2e-12
DYNAMIC_REACH_LENGTH_M = 400.0
DYNAMIC_DURATION_SECONDS = 180.0
DYNAMIC_CELL_COUNTS = (16, 32, 64)
SELF_CONVERGENCE_RATIO_LIMIT = 0.85
BASE_DEPTH_M = 2.0
PERTURBATION_AMPLITUDE_M = 0.05
PERTURBATION_CENTER_M = 250.0
PERTURBATION_SIGMA_M = 90.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    return parser.parse_args()


def _replace_states(
    reaches: list[DynamicWaveNetworkReach],
    states: tuple[PrismaticDynamicWaveState, ...],
) -> list[DynamicWaveNetworkReach]:
    return [
        DynamicWaveNetworkReach(
            reach_id=reach.reach_id,
            state=state,
            bed_elevation_m=reach.bed_elevation_m,
            sections=reach.sections,
            cell_length_m=reach.cell_length_m,
            manning_n=reach.manning_n,
            lateral_inflow_m2s=reach.lateral_inflow_m2s,
        )
        for reach, state in zip(reaches, states, strict=True)
    ]


def _volume(reaches: list[DynamicWaveNetworkReach]) -> float:
    return sum(
        sum(reach.state.area_m2) * reach.cell_length_m for reach in reaches
    )


def _run_variable_geometry_lake_network() -> dict[str, Any]:
    surface = 3.0
    cell_length = 100.0
    section_axes = (
        tuple(TrapezoidalChannelSection(value, 1.0) for value in (8, 9, 10, 11)),
        tuple(TrapezoidalChannelSection(value, 0.5) for value in (6, 7, 8, 9)),
        tuple(TrapezoidalChannelSection(value, 2.0) for value in (12, 11, 10, 9)),
        tuple(TrapezoidalChannelSection(value, 1.5) for value in (7, 8, 9, 10)),
        tuple(TrapezoidalChannelSection(value, 2.5) for value in (14, 13, 12, 11)),
    )
    bed_axes = (
        (0.4, 0.3, 0.2, 0.1),
        (0.7, 0.5, 0.3, 0.1),
        (0.1, 0.05, 0.0, -0.05),
        (0.5, 0.35, 0.2, 0.0),
        (-0.05, -0.1, -0.15, -0.2),
    )
    reaches = [
        DynamicWaveNetworkReach(
            reach_id=reach_id,
            state=PrismaticDynamicWaveState(
                area_m2=tuple(
                    section.area_m2(surface - bed)
                    for section, bed in zip(sections, beds, strict=True)
                ),
                discharge_m3s=(0.0,) * len(sections),
            ),
            bed_elevation_m=beds,
            sections=sections,
            cell_length_m=cell_length,
            manning_n=(0.035,) * len(sections),
            lateral_inflow_m2s=(0.0,) * len(sections),
        )
        for reach_id, sections, beds in zip(
            TOPOLOGY.reach_ids, section_axes, bed_axes, strict=True
        )
    ]
    initial_states = tuple(value.state for value in reaches)
    source_boundaries = {
        reach_id: FixedDynamicWaveBoundary(
            DynamicWaveCellState(
                reach.sections[0].area_m2(
                    surface - reach.bed_elevation_m[0]
                ),
                0.0,
            ),
            reach.bed_elevation_m[0],
        )
        for reach_id, reach in zip(TOPOLOGY.reach_ids, reaches, strict=True)
        if reach_id in TOPOLOGY.source_reach_ids
    }
    outlet_reach = reaches[TOPOLOGY.reach_ids.index(TOPOLOGY.outlet_reach_id)]
    outlet = FixedDynamicWaveBoundary(
        DynamicWaveCellState(
            outlet_reach.sections[-1].area_m2(
                surface - outlet_reach.bed_elevation_m[-1]
            ),
            0.0,
        ),
        outlet_reach.bed_elevation_m[-1],
    )
    initial_volume = _volume(reaches)
    totals = {
        "lateral": 0.0,
        "source": 0.0,
        "outlet": 0.0,
        "junction": 0.0,
    }
    maxima = {
        "node": 0.0,
        "invariant": 0.0,
        "network": 0.0,
        "reach_volume": 0.0,
        "reach_momentum": 0.0,
        "courant": 0.0,
    }
    elapsed = 0.0
    final_junction_surfaces: dict[str, float] = {}
    for _ in range(100):
        timestep = maximum_dendritic_dynamic_wave_stable_timestep_seconds(
            TOPOLOGY,
            tuple(reaches),
            source_left_boundaries=source_boundaries,
            outlet_right_boundary=outlet,
            courant_number=COURANT_NUMBER,
        )
        step = advance_dendritic_dynamic_wave_network_open(
            TOPOLOGY,
            tuple(reaches),
            source_left_boundaries=source_boundaries,
            outlet_right_boundary=outlet,
            timestep_seconds=timestep,
            maximum_courant_number=COURANT_NUMBER,
            lateral_momentum_convention="zero_longitudinal_momentum",
        )
        reaches = _replace_states(reaches, step.states)
        elapsed += timestep
        totals["lateral"] += step.lateral_volume_change_m3
        totals["source"] += step.source_boundary_inflow_volume_m3
        totals["outlet"] += step.outlet_boundary_outflow_volume_m3
        totals["junction"] += step.junction_mass_balance_residual_volume_m3
        maxima["node"] = max(
            maxima["node"],
            step.maximum_absolute_node_mass_balance_residual_m3s,
        )
        maxima["invariant"] = max(
            maxima["invariant"],
            step.maximum_absolute_outgoing_invariant_residual_mps,
        )
        maxima["network"] = max(
            maxima["network"], abs(step.network_volume_balance_error_m3)
        )
        maxima["reach_volume"] = max(
            maxima["reach_volume"],
            step.maximum_absolute_reach_volume_ledger_error_m3,
        )
        maxima["reach_momentum"] = max(
            maxima["reach_momentum"],
            step.maximum_absolute_reach_momentum_ledger_error_m4s,
        )
        maxima["courant"] = max(
            maxima["courant"], step.maximum_courant_number
        )
        final_junction_surfaces = {
            value.downstream_branch_id: value.common_free_surface_elevation_m
            for value in step.junctions
        }
    final_volume = _volume(reaches)
    return {
        "step_count": 100,
        "elapsed_seconds": elapsed,
        "final_junction_surface_elevation_m": final_junction_surfaces,
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
        "maximum_node_mass_balance_residual_m3s": maxima["node"],
        "maximum_outgoing_invariant_residual_mps": maxima["invariant"],
        "maximum_network_volume_balance_error_m3": maxima["network"],
        "maximum_reach_volume_ledger_error_m3": maxima["reach_volume"],
        "maximum_reach_momentum_ledger_error_m4s": maxima["reach_momentum"],
        "cumulative_network_volume_balance_error_m3": (
            final_volume
            - initial_volume
            - totals["lateral"]
            - totals["source"]
            + totals["outlet"]
            + totals["junction"]
        ),
        "maximum_reported_courant_number": maxima["courant"],
    }


def _dynamic_reaches(
    cell_count: int,
) -> tuple[
    list[DynamicWaveNetworkReach],
    dict[str, FixedDynamicWaveBoundary],
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
    perturbed_depth = BASE_DEPTH_M + PERTURBATION_AMPLITUDE_M * np.exp(
        -0.5
        * ((centers - PERTURBATION_CENTER_M) / PERTURBATION_SIGMA_M) ** 2
    )
    reaches = [
        DynamicWaveNetworkReach(
            reach_id=reach_id,
            state=PrismaticDynamicWaveState(
                area_m2=(
                    tuple(section.area_m2(float(value)) for value in perturbed_depth)
                    if reach_id == "A"
                    else (base_area,) * cell_count
                ),
                discharge_m3s=(BASE_DISCHARGE_M3S[reach_id],) * cell_count,
            ),
            bed_elevation_m=(0.0,) * cell_count,
            sections=(section,) * cell_count,
            cell_length_m=cell_length,
            manning_n=(1e-6,) * cell_count,
            lateral_inflow_m2s=(0.0,) * cell_count,
        )
        for reach_id in TOPOLOGY.reach_ids
    ]
    source_boundaries = {
        reach_id: FixedDynamicWaveBoundary(
            DynamicWaveCellState(base_area, BASE_DISCHARGE_M3S[reach_id]),
            0.0,
        )
        for reach_id in TOPOLOGY.source_reach_ids
    }
    outlet = FixedDynamicWaveBoundary(
        DynamicWaveCellState(base_area, BASE_DISCHARGE_M3S["E"]), 0.0
    )
    return reaches, source_boundaries, outlet, centers


def _run_dynamic_network(cell_count: int) -> dict[str, Any]:
    reaches, source_boundaries, outlet, centers = _dynamic_reaches(cell_count)
    initial_volume = _volume(reaches)
    elapsed = 0.0
    step_count = 0
    totals = {
        "lateral": 0.0,
        "source": 0.0,
        "outlet": 0.0,
        "junction": 0.0,
    }
    maxima = {
        "node": 0.0,
        "invariant": 0.0,
        "network": 0.0,
        "reach_volume": 0.0,
        "reach_momentum": 0.0,
        "courant": 0.0,
    }
    minimum_area = min(
        value for reach in reaches for value in reach.state.area_m2
    )
    final_junction_surfaces: dict[str, float] = {}
    while elapsed < DYNAMIC_DURATION_SECONDS:
        stable_timestep = maximum_dendritic_dynamic_wave_stable_timestep_seconds(
            TOPOLOGY,
            tuple(reaches),
            source_left_boundaries=source_boundaries,
            outlet_right_boundary=outlet,
            courant_number=COURANT_NUMBER,
        )
        timestep = min(stable_timestep, DYNAMIC_DURATION_SECONDS - elapsed)
        step = advance_dendritic_dynamic_wave_network_open(
            TOPOLOGY,
            tuple(reaches),
            source_left_boundaries=source_boundaries,
            outlet_right_boundary=outlet,
            timestep_seconds=timestep,
            maximum_courant_number=COURANT_NUMBER,
            lateral_momentum_convention="zero_longitudinal_momentum",
        )
        reaches = _replace_states(reaches, step.states)
        elapsed += timestep
        step_count += 1
        totals["lateral"] += step.lateral_volume_change_m3
        totals["source"] += step.source_boundary_inflow_volume_m3
        totals["outlet"] += step.outlet_boundary_outflow_volume_m3
        totals["junction"] += step.junction_mass_balance_residual_volume_m3
        maxima["node"] = max(
            maxima["node"], step.maximum_absolute_node_mass_balance_residual_m3s
        )
        maxima["invariant"] = max(
            maxima["invariant"],
            step.maximum_absolute_outgoing_invariant_residual_mps,
        )
        maxima["network"] = max(
            maxima["network"], abs(step.network_volume_balance_error_m3)
        )
        maxima["reach_volume"] = max(
            maxima["reach_volume"],
            step.maximum_absolute_reach_volume_ledger_error_m3,
        )
        maxima["reach_momentum"] = max(
            maxima["reach_momentum"],
            step.maximum_absolute_reach_momentum_ledger_error_m4s,
        )
        maxima["courant"] = max(
            maxima["courant"], step.maximum_courant_number
        )
        minimum_area = min(minimum_area, step.minimum_area_m2)
        final_junction_surfaces = {
            value.downstream_branch_id: value.common_free_surface_elevation_m
            for value in step.junctions
        }
    final_volume = _volume(reaches)
    depth_profiles = [
        [
            section.depth_m(area)
            for area, section in zip(
                reach.state.area_m2, reach.sections, strict=True
            )
        ]
        for reach in reaches
    ]
    discharge_profiles = [list(reach.state.discharge_m3s) for reach in reaches]
    outlet_reach = reaches[TOPOLOGY.reach_ids.index("E")]
    return {
        "cell_count_per_reach": cell_count,
        "cell_length_m": reaches[0].cell_length_m,
        "step_count": step_count,
        "elapsed_seconds": elapsed,
        "cell_center_m": [float(value) for value in centers],
        "final_depth_profiles_m": depth_profiles,
        "final_discharge_profiles_m3s": discharge_profiles,
        "final_junction_surface_elevation_m": final_junction_surfaces,
        "maximum_outlet_reach_discharge_change_m3s": max(
            abs(value - BASE_DISCHARGE_M3S["E"])
            for value in outlet_reach.state.discharge_m3s
        ),
        "maximum_node_mass_balance_residual_m3s": maxima["node"],
        "maximum_outgoing_invariant_residual_mps": maxima["invariant"],
        "maximum_network_volume_balance_error_m3": maxima["network"],
        "maximum_reach_volume_ledger_error_m3": maxima["reach_volume"],
        "maximum_reach_momentum_ledger_error_m4s": maxima["reach_momentum"],
        "cumulative_network_volume_balance_error_m3": (
            final_volume
            - initial_volume
            - totals["lateral"]
            - totals["source"]
            + totals["outlet"]
            + totals["junction"]
        ),
        "maximum_reported_courant_number": maxima["courant"],
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


def _invalid_topology_gates() -> dict[str, bool]:
    results = {"multiple_outlet_rejected": False, "cycle_rejected": False}
    try:
        DynamicWaveDendriticTopology(("A", "B"), (None, None))
    except ValueError as exc:
        results["multiple_outlet_rejected"] = str(exc) == (
            "dynamic_wave_dendritic_topology_invalid"
        )
    try:
        DynamicWaveDendriticTopology(("A", "B", "C"), ("B", "A", None))
    except ValueError as exc:
        results["cycle_rejected"] = str(exc) == (
            "dynamic_wave_dendritic_topology_cycle"
        )
    return results


def _supercritical_terminal_rejected() -> bool:
    reaches, source_boundaries, outlet, _ = _dynamic_reaches(4)
    section = reaches[0].sections[0]
    reaches[0] = DynamicWaveNetworkReach(
        reach_id="A",
        state=PrismaticDynamicWaveState((5.0,) * 4, (40.0,) * 4),
        bed_elevation_m=(0.0,) * 4,
        sections=(section,) * 4,
        cell_length_m=reaches[0].cell_length_m,
        manning_n=(1e-6,) * 4,
        lateral_inflow_m2s=(0.0,) * 4,
    )
    try:
        maximum_dendritic_dynamic_wave_stable_timestep_seconds(
            TOPOLOGY,
            tuple(reaches),
            source_left_boundaries=source_boundaries,
            outlet_right_boundary=outlet,
            courant_number=COURANT_NUMBER,
        )
    except ValueError as exc:
        return str(exc) == "dynamic_wave_confluence_no_subcritical_root"
    return False


def compile_gates() -> dict[str, Any]:
    invalid_topologies = _invalid_topology_gates()
    lake = _run_variable_geometry_lake_network()
    refinements = [_run_dynamic_network(value) for value in DYNAMIC_CELL_COUNTS]
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
        "single_outlet_tree_topology_recognized": (
            TOPOLOGY.source_reach_ids == ("A", "B", "D")
            and TOPOLOGY.junction_reach_ids == ("C", "E")
            and TOPOLOGY.outlet_reach_id == "E"
        ),
        "multiple_outlet_topology_fails_closed": invalid_topologies[
            "multiple_outlet_rejected"
        ],
        "cyclic_topology_fails_closed": invalid_topologies["cycle_rejected"],
        "two_common_stage_nodes_recovered": all(
            abs(value - 3.0) <= 1e-12
            for value in lake["final_junction_surface_elevation_m"].values()
        ),
        "two_junction_lake_area_identity_100_steps": (
            lake["maximum_area_drift_m2"] <= 1e-12
        ),
        "two_junction_lake_no_spurious_flow_100_steps": (
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
        "perturbation_crosses_both_nodes_into_outlet_reach": all(
            item["maximum_outlet_reach_discharge_change_m3s"] > 0.01
            for item in refinements
        ),
        "network_depth_and_discharge_self_converge": all(
            value <= SELF_CONVERGENCE_RATIO_LIMIT for value in ratios.values()
        ),
        "dynamic_network_states_remain_wet_and_cfl_compliant": all(
            item["minimum_area_m2"] > 0.0
            and item["maximum_reported_courant_number"]
            <= COURANT_NUMBER + 2.0 * np.finfo(float).eps
            for item in refinements
        ),
        "supercritical_terminal_fails_closed": (
            _supercritical_terminal_rejected()
        ),
    }
    return {
        "schema": SCHEMA,
        "status": "dendritic_dynamic_wave_dag_diagnostic_gated",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_isolation": {
            "public_or_user_data_read": False,
            "action_values_read": False,
            "observation_values_read": False,
            "saved_prediction_values_read": False,
        },
        "topology_contract": TOPOLOGY.as_dict(),
        "scheduling_contract": {
            "time_level": "synchronous_after_first_source_half_step",
            "node_solver": "common_stage_subcritical_characteristics",
            "internal_endpoint_flux_use_count": 1,
            "external_boundary_type": "fixed_ghost_state",
            "junction_storage_m3": 0.0,
            "junction_momentum_or_energy_closure": None,
        },
        "variable_geometry_lake_network": lake,
        "dynamic_refinement": {
            "reach_length_m": DYNAMIC_REACH_LENGTH_M,
            "duration_seconds": DYNAMIC_DURATION_SECONDS,
            "cell_counts_per_reach": list(DYNAMIC_CELL_COUNTS),
            "base_discharge_m3s": BASE_DISCHARGE_M3S,
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
            "single_outlet_dendritic_dag_implemented": True,
            "serial_and_multi_in_one_out_nodes_implemented": True,
            "synchronous_multi_node_step_implemented": True,
            "source_aware_whole_network_cfl_implemented": True,
            "whole_network_mass_ledger_implemented": True,
            "dynamic_dag_self_convergence_gate_passed": gates[
                "network_depth_and_discharge_self_converge"
            ],
            "junction_momentum_or_energy_closure_implemented": False,
            "bifurcation_junction_implemented": False,
            "general_arbitrary_dag_implemented": False,
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
