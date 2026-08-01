#!/usr/bin/env python3
"""Compile outcome-free dynamic-wave energy-junction gates."""

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
    STANDARD_GRAVITY_MPS2,
    DynamicWaveCellState,
    PrismaticDynamicWaveState,
    TrapezoidalChannelSection,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_junction import (
    DynamicWaveJunctionTerminal,
    DynamicWaveNetworkReach,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_junction_energy import (
    DynamicWaveJunctionEnergyLoss,
    SubcriticalEnergyJunctionSolution,
    solve_subcritical_dynamic_wave_energy_junction,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/dynamic_wave_energy_junction_gates.json"
)
SCHEMA = "gwm.geotransport.dynamic_wave_energy_junction_gates.v1"

TOPOLOGY = DynamicWaveDendriticTopology(
    ("A", "B", "C", "D", "E"), ("C", "C", "E", "E", None)
)
BASE_DISCHARGE_M3S = {"A": 2.0, "B": 3.0, "C": 5.0, "D": 4.0, "E": 9.0}
ENERGY_LOSSES = {
    "C": DynamicWaveJunctionEnergyLoss(("A", "B"), (0.2, 0.3), 0.1),
    "E": DynamicWaveJunctionEnergyLoss(("C", "D"), (0.15, 0.25), 0.1),
}
NODE_HEADS_M = {"C": 3.0, "E": 2.8}
COURANT_NUMBER = 0.4
LEDGER_ABSOLUTE_TOLERANCE = 1e-8
NODE_MASS_RATE_TOLERANCE_M3S = 2e-12
ENERGY_HEAD_TOLERANCE_M = 2e-12
INVARIANT_ABSOLUTE_TOLERANCE_MPS = 2e-12
DYNAMIC_REACH_LENGTH_M = 400.0
DYNAMIC_DURATION_SECONDS = 180.0
DYNAMIC_CELL_COUNTS = (16, 32, 64)
SELF_CONVERGENCE_RATIO_LIMIT = 0.85
BASE_DEPTH_M = 2.0
PERTURBATION_AMPLITUDE_M = 0.03
PERTURBATION_CENTER_M = 250.0
PERTURBATION_SIGMA_M = 90.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    return parser.parse_args()


def _bed_for_manufactured_head(
    *,
    node_head: float,
    depth: float,
    area: float,
    discharge: float,
    loss_coefficient: float,
    side: str,
) -> float:
    velocity_head = (discharge / area) ** 2 / (
        2.0 * STANDARD_GRAVITY_MPS2
    )
    if side == "upstream":
        return node_head - depth + (loss_coefficient - 1.0) * velocity_head
    return node_head - depth - (loss_coefficient + 1.0) * velocity_head


def _manufactured_junction(
    upstream_coefficients: tuple[float, float],
    downstream_coefficient: float,
) -> tuple[
    tuple[DynamicWaveJunctionTerminal, ...],
    DynamicWaveJunctionTerminal,
    DynamicWaveJunctionEnergyLoss,
]:
    section = TrapezoidalChannelSection(10.0, 2.0)
    area = section.area_m2(BASE_DEPTH_M)
    upstream = tuple(
        DynamicWaveJunctionTerminal(
            branch_id,
            DynamicWaveCellState(area, discharge),
            section,
            _bed_for_manufactured_head(
                node_head=3.0,
                depth=BASE_DEPTH_M,
                area=area,
                discharge=discharge,
                loss_coefficient=coefficient,
                side="upstream",
            ),
        )
        for branch_id, discharge, coefficient in zip(
            ("A", "B"),
            (2.0, 3.0),
            upstream_coefficients,
            strict=True,
        )
    )
    downstream = DynamicWaveJunctionTerminal(
        "C",
        DynamicWaveCellState(area, 5.0),
        section,
        _bed_for_manufactured_head(
            node_head=3.0,
            depth=BASE_DEPTH_M,
            area=area,
            discharge=5.0,
            loss_coefficient=downstream_coefficient,
            side="downstream",
        ),
    )
    return (
        upstream,
        downstream,
        DynamicWaveJunctionEnergyLoss(
            ("A", "B"), upstream_coefficients, downstream_coefficient
        ),
    )


def _endpoint_beds() -> dict[str, tuple[float, float]]:
    section = TrapezoidalChannelSection(10.0, 2.0)
    area = section.area_m2(BASE_DEPTH_M)
    node_beds = {
        ("A", "right"): _bed_for_manufactured_head(
            node_head=NODE_HEADS_M["C"],
            depth=BASE_DEPTH_M,
            area=area,
            discharge=BASE_DISCHARGE_M3S["A"],
            loss_coefficient=0.2,
            side="upstream",
        ),
        ("B", "right"): _bed_for_manufactured_head(
            node_head=NODE_HEADS_M["C"],
            depth=BASE_DEPTH_M,
            area=area,
            discharge=BASE_DISCHARGE_M3S["B"],
            loss_coefficient=0.3,
            side="upstream",
        ),
        ("C", "left"): _bed_for_manufactured_head(
            node_head=NODE_HEADS_M["C"],
            depth=BASE_DEPTH_M,
            area=area,
            discharge=BASE_DISCHARGE_M3S["C"],
            loss_coefficient=0.1,
            side="downstream",
        ),
        ("C", "right"): _bed_for_manufactured_head(
            node_head=NODE_HEADS_M["E"],
            depth=BASE_DEPTH_M,
            area=area,
            discharge=BASE_DISCHARGE_M3S["C"],
            loss_coefficient=0.15,
            side="upstream",
        ),
        ("D", "right"): _bed_for_manufactured_head(
            node_head=NODE_HEADS_M["E"],
            depth=BASE_DEPTH_M,
            area=area,
            discharge=BASE_DISCHARGE_M3S["D"],
            loss_coefficient=0.25,
            side="upstream",
        ),
        ("E", "left"): _bed_for_manufactured_head(
            node_head=NODE_HEADS_M["E"],
            depth=BASE_DEPTH_M,
            area=area,
            discharge=BASE_DISCHARGE_M3S["E"],
            loss_coefficient=0.1,
            side="downstream",
        ),
    }
    return {
        "A": (node_beds[("A", "right")] + 0.05, node_beds[("A", "right")]),
        "B": (node_beds[("B", "right")] + 0.05, node_beds[("B", "right")]),
        "C": (node_beds[("C", "left")], node_beds[("C", "right")]),
        "D": (node_beds[("D", "right")] + 0.05, node_beds[("D", "right")]),
        "E": (node_beds[("E", "left")], node_beds[("E", "left")] - 0.05),
    }


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
        sum(value.state.area_m2) * value.cell_length_m for value in reaches
    )


def _dynamic_network(
    cell_count: int,
    *,
    perturbed: bool,
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
    perturbation = PERTURBATION_AMPLITUDE_M * np.exp(
        -0.5
        * ((centers - PERTURBATION_CENTER_M) / PERTURBATION_SIGMA_M) ** 2
    )
    endpoint_beds = _endpoint_beds()
    reaches = []
    for reach_id in TOPOLOGY.reach_ids:
        left_bed, right_bed = endpoint_beds[reach_id]
        depths = (
            BASE_DEPTH_M + perturbation
            if reach_id == "A" and perturbed
            else np.full(cell_count, BASE_DEPTH_M)
        )
        reaches.append(
            DynamicWaveNetworkReach(
                reach_id=reach_id,
                state=PrismaticDynamicWaveState(
                    tuple(section.area_m2(float(value)) for value in depths),
                    (BASE_DISCHARGE_M3S[reach_id],) * cell_count,
                ),
                bed_elevation_m=tuple(
                    float(value)
                    for value in np.linspace(left_bed, right_bed, cell_count)
                ),
                sections=(section,) * cell_count,
                cell_length_m=cell_length,
                manning_n=(1e-6,) * cell_count,
                lateral_inflow_m2s=(0.0,) * cell_count,
            )
        )
    source_boundaries = {
        reach_id: FixedDynamicWaveBoundary(
            DynamicWaveCellState(base_area, BASE_DISCHARGE_M3S[reach_id]),
            reaches[TOPOLOGY.reach_ids.index(reach_id)].bed_elevation_m[0],
        )
        for reach_id in TOPOLOGY.source_reach_ids
    }
    outlet = FixedDynamicWaveBoundary(
        DynamicWaveCellState(base_area, BASE_DISCHARGE_M3S["E"]),
        reaches[-1].bed_elevation_m[-1],
    )
    return reaches, source_boundaries, outlet, centers


def _run_dynamic_network(cell_count: int, *, perturbed: bool) -> dict[str, Any]:
    reaches, source_boundaries, outlet, centers = _dynamic_network(
        cell_count, perturbed=perturbed
    )
    initial_volume = _volume(reaches)
    totals = {"lateral": 0.0, "source": 0.0, "outlet": 0.0, "junction": 0.0}
    maxima = {
        "node": 0.0,
        "energy": 0.0,
        "invariant": 0.0,
        "network": 0.0,
        "reach_volume": 0.0,
        "reach_momentum": 0.0,
        "courant": 0.0,
    }
    minimum_area = min(
        value for reach in reaches for value in reach.state.area_m2
    )
    elapsed = 0.0
    step_count = 0
    final_node_heads: dict[str, float] = {}
    while elapsed < DYNAMIC_DURATION_SECONDS:
        stable = maximum_dendritic_dynamic_wave_stable_timestep_seconds(
            TOPOLOGY,
            tuple(reaches),
            source_left_boundaries=source_boundaries,
            outlet_right_boundary=outlet,
            courant_number=COURANT_NUMBER,
            junction_energy_losses=ENERGY_LOSSES,
        )
        timestep = min(stable, DYNAMIC_DURATION_SECONDS - elapsed)
        step = advance_dendritic_dynamic_wave_network_open(
            TOPOLOGY,
            tuple(reaches),
            source_left_boundaries=source_boundaries,
            outlet_right_boundary=outlet,
            timestep_seconds=timestep,
            maximum_courant_number=COURANT_NUMBER,
            lateral_momentum_convention="zero_longitudinal_momentum",
            junction_energy_losses=ENERGY_LOSSES,
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
        maxima["energy"] = max(
            maxima["energy"],
            max(
                value.maximum_absolute_energy_equation_residual_m
                for value in step.junctions
                if isinstance(value, SubcriticalEnergyJunctionSolution)
            ),
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
        maxima["courant"] = max(maxima["courant"], step.maximum_courant_number)
        minimum_area = min(minimum_area, step.minimum_area_m2)
        final_node_heads = {
            value.downstream_branch_id: value.node_reference_total_head_m
            for value in step.junctions
            if isinstance(value, SubcriticalEnergyJunctionSolution)
        }
    final_volume = _volume(reaches)
    return {
        "cell_count_per_reach": cell_count,
        "perturbed": perturbed,
        "cell_length_m": reaches[0].cell_length_m,
        "step_count": step_count,
        "elapsed_seconds": elapsed,
        "cell_center_m": [float(value) for value in centers],
        "final_depth_profiles_m": [
            [
                section.depth_m(area)
                for area, section in zip(
                    reach.state.area_m2, reach.sections, strict=True
                )
            ]
            for reach in reaches
        ],
        "final_discharge_profiles_m3s": [
            list(reach.state.discharge_m3s) for reach in reaches
        ],
        "final_node_reference_total_heads_m": final_node_heads,
        "maximum_node_mass_balance_residual_m3s": maxima["node"],
        "maximum_energy_equation_residual_m": maxima["energy"],
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


def _response_pair(cell_count: int) -> dict[str, Any]:
    control = _run_dynamic_network(cell_count, perturbed=False)
    perturbed = _run_dynamic_network(cell_count, perturbed=True)
    depth_response = [
        [after - before for after, before in zip(p, c, strict=True)]
        for p, c in zip(
            perturbed["final_depth_profiles_m"],
            control["final_depth_profiles_m"],
            strict=True,
        )
    ]
    discharge_response = [
        [after - before for after, before in zip(p, c, strict=True)]
        for p, c in zip(
            perturbed["final_discharge_profiles_m3s"],
            control["final_discharge_profiles_m3s"],
            strict=True,
        )
    ]
    return {
        "cell_count_per_reach": cell_count,
        "cell_center_m": control["cell_center_m"],
        "control": control,
        "perturbed": perturbed,
        "depth_response_profiles_m": depth_response,
        "discharge_response_profiles_m3s": discharge_response,
        "maximum_outlet_reach_discharge_response_m3s": max(
            abs(value) for value in discharge_response[TOPOLOGY.reach_ids.index("E")]
        ),
    }


def _compare_response_refinements(
    coarse: Mapping[str, Any], fine: Mapping[str, Any]
) -> dict[str, Any]:
    coarse_x = np.asarray(coarse["cell_center_m"], dtype=float)
    fine_x = np.asarray(fine["cell_center_m"], dtype=float)
    depth_errors = []
    discharge_errors = []
    for coarse_depth, fine_depth, coarse_flow, fine_flow in zip(
        coarse["depth_response_profiles_m"],
        fine["depth_response_profiles_m"],
        coarse["discharge_response_profiles_m3s"],
        fine["discharge_response_profiles_m3s"],
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
    depth = np.asarray(depth_errors)
    discharge = np.asarray(discharge_errors)
    return {
        "coarse_cell_count_per_reach": coarse["cell_count_per_reach"],
        "fine_cell_count_per_reach": fine["cell_count_per_reach"],
        "depth_l1_difference_m": float(depth.mean()),
        "depth_linf_difference_m": float(depth.max()),
        "discharge_l1_difference_m3s": float(discharge.mean()),
        "discharge_linf_difference_m3s": float(discharge.max()),
    }


def _run_lake_network() -> dict[str, Any]:
    surface = 3.5
    endpoint_beds = _endpoint_beds()
    section = TrapezoidalChannelSection(10.0, 2.0)
    reaches = []
    for reach_id in TOPOLOGY.reach_ids:
        left_bed, right_bed = endpoint_beds[reach_id]
        beds = tuple(float(value) for value in np.linspace(left_bed, right_bed, 4))
        reaches.append(
            DynamicWaveNetworkReach(
                reach_id=reach_id,
                state=PrismaticDynamicWaveState(
                    tuple(section.area_m2(surface - value) for value in beds),
                    (0.0,) * 4,
                ),
                bed_elevation_m=beds,
                sections=(section,) * 4,
                cell_length_m=100.0,
                manning_n=(0.035,) * 4,
                lateral_inflow_m2s=(0.0,) * 4,
            )
        )
    initial_states = tuple(value.state for value in reaches)
    source_boundaries = {
        reach_id: FixedDynamicWaveBoundary(
            DynamicWaveCellState(
                reach.sections[0].area_m2(surface - reach.bed_elevation_m[0]),
                0.0,
            ),
            reach.bed_elevation_m[0],
        )
        for reach_id, reach in zip(TOPOLOGY.reach_ids, reaches, strict=True)
        if reach_id in TOPOLOGY.source_reach_ids
    }
    outlet_reach = reaches[-1]
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
    totals = {"lateral": 0.0, "source": 0.0, "outlet": 0.0, "junction": 0.0}
    maxima = {"node": 0.0, "energy": 0.0, "network": 0.0}
    elapsed = 0.0
    for _ in range(100):
        timestep = maximum_dendritic_dynamic_wave_stable_timestep_seconds(
            TOPOLOGY,
            tuple(reaches),
            source_left_boundaries=source_boundaries,
            outlet_right_boundary=outlet,
            courant_number=COURANT_NUMBER,
            junction_energy_losses=ENERGY_LOSSES,
        )
        step = advance_dendritic_dynamic_wave_network_open(
            TOPOLOGY,
            tuple(reaches),
            source_left_boundaries=source_boundaries,
            outlet_right_boundary=outlet,
            timestep_seconds=timestep,
            maximum_courant_number=COURANT_NUMBER,
            lateral_momentum_convention="zero_longitudinal_momentum",
            junction_energy_losses=ENERGY_LOSSES,
        )
        reaches = _replace_states(reaches, step.states)
        elapsed += timestep
        totals["lateral"] += step.lateral_volume_change_m3
        totals["source"] += step.source_boundary_inflow_volume_m3
        totals["outlet"] += step.outlet_boundary_outflow_volume_m3
        totals["junction"] += step.junction_mass_balance_residual_volume_m3
        maxima["node"] = max(
            maxima["node"], step.maximum_absolute_node_mass_balance_residual_m3s
        )
        maxima["energy"] = max(
            maxima["energy"],
            max(
                value.maximum_absolute_energy_equation_residual_m
                for value in step.junctions
                if isinstance(value, SubcriticalEnergyJunctionSolution)
            ),
        )
        maxima["network"] = max(
            maxima["network"], abs(step.network_volume_balance_error_m3)
        )
    final_volume = _volume(reaches)
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
        "maximum_node_mass_balance_residual_m3s": maxima["node"],
        "maximum_energy_equation_residual_m": maxima["energy"],
        "maximum_network_volume_balance_error_m3": maxima["network"],
        "cumulative_network_volume_balance_error_m3": (
            final_volume
            - initial_volume
            - totals["lateral"]
            - totals["source"]
            + totals["outlet"]
            + totals["junction"]
        ),
    }


def _failure_gates() -> dict[str, bool]:
    upstream, downstream, loss = _manufactured_junction((0.2, 0.4), 0.1)
    reverse_rejected = False
    no_root_rejected = False
    negative_loss_rejected = False
    try:
        reverse = DynamicWaveJunctionTerminal(
            "A",
            DynamicWaveCellState(upstream[0].interior_state.area_m2, -1.0),
            upstream[0].section,
            upstream[0].bed_elevation_m,
        )
        solve_subcritical_dynamic_wave_energy_junction(
            (reverse, upstream[1]), downstream, loss
        )
    except ValueError as exc:
        reverse_rejected = str(exc) == (
            "dynamic_wave_energy_junction_terminal_not_supported"
        )
    try:
        section = TrapezoidalChannelSection(10.0, 2.0)
        area = section.area_m2(2.0)
        flat_upstream = tuple(
            DynamicWaveJunctionTerminal(
                branch_id, DynamicWaveCellState(area, discharge), section, 0.0
            )
            for branch_id, discharge in (("A", 2.0), ("B", 3.0))
        )
        incompatible_downstream = DynamicWaveJunctionTerminal(
            "C", DynamicWaveCellState(area, 5.0), section, 100.0
        )
        solve_subcritical_dynamic_wave_energy_junction(
            flat_upstream,
            incompatible_downstream,
            DynamicWaveJunctionEnergyLoss(("A", "B"), (0.1, 0.1), 0.1),
        )
    except ValueError as exc:
        no_root_rejected = str(exc) == (
            "dynamic_wave_energy_junction_no_common_head_range"
        )
    try:
        DynamicWaveJunctionEnergyLoss(("A", "B"), (-0.1, 0.0), 0.0)
    except ValueError as exc:
        negative_loss_rejected = str(exc) == (
            "dynamic_wave_junction_energy_loss_invalid"
        )
    return {
        "reverse_flow_rejected": reverse_rejected,
        "incompatible_head_ranges_rejected": no_root_rejected,
        "negative_loss_rejected": negative_loss_rejected,
    }


def compile_gates() -> dict[str, Any]:
    zero_args = _manufactured_junction((0.0, 0.0), 0.0)
    positive_args = _manufactured_junction((0.2, 0.4), 0.1)
    zero_loss = solve_subcritical_dynamic_wave_energy_junction(*zero_args)
    positive_loss = solve_subcritical_dynamic_wave_energy_junction(*positive_args)
    failures = _failure_gates()
    lake = _run_lake_network()
    responses = [_response_pair(value) for value in DYNAMIC_CELL_COUNTS]
    comparisons = [
        _compare_response_refinements(coarse, fine)
        for coarse, fine in zip(responses, responses[1:])
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
    dynamic_runs = [
        run
        for response in responses
        for run in (response["control"], response["perturbed"])
    ]
    gates = {
        "zero_loss_total_head_manufactured_state_recovered": (
            abs(zero_loss.node_reference_total_head_m - 3.0) <= 1e-12
            and abs(zero_loss.downstream_discharge_m3s - 5.0) <= 1e-12
        ),
        "positive_loss_manufactured_state_recovered": (
            abs(positive_loss.node_reference_total_head_m - 3.0) <= 1e-12
            and abs(positive_loss.downstream_discharge_m3s - 5.0) <= 1e-12
        ),
        "positive_branch_head_losses_are_nonnegative_and_closed": (
            positive_loss.maximum_absolute_energy_equation_residual_m
            <= ENERGY_HEAD_TOLERANCE_M
            and all(
                value >= positive_loss.node_reference_total_head_m
                for value in positive_loss.upstream_boundary_total_heads_m
            )
            and positive_loss.node_reference_total_head_m
            >= positive_loss.downstream_boundary_total_head_m
        ),
        "reverse_flow_fails_closed": failures["reverse_flow_rejected"],
        "incompatible_energy_head_ranges_fail_closed": failures[
            "incompatible_head_ranges_rejected"
        ],
        "negative_loss_coefficient_fails_closed": failures[
            "negative_loss_rejected"
        ],
        "positive_loss_lake_area_identity_100_steps": (
            lake["maximum_area_drift_m2"] <= 1e-12
        ),
        "positive_loss_lake_no_spurious_flow_100_steps": (
            lake["maximum_absolute_discharge_m3s"] <= 1e-12
        ),
        "all_energy_equation_residuals_bounded": (
            lake["maximum_energy_equation_residual_m"]
            <= ENERGY_HEAD_TOLERANCE_M
            and all(
                run["maximum_energy_equation_residual_m"]
                <= ENERGY_HEAD_TOLERANCE_M
                for run in dynamic_runs
            )
        ),
        "all_node_mass_rate_residuals_bounded": (
            lake["maximum_node_mass_balance_residual_m3s"]
            <= NODE_MASS_RATE_TOLERANCE_M3S
            and all(
                run["maximum_node_mass_balance_residual_m3s"]
                <= NODE_MASS_RATE_TOLERANCE_M3S
                for run in dynamic_runs
            )
        ),
        "all_node_invariant_residuals_bounded": all(
            run["maximum_outgoing_invariant_residual_mps"]
            <= INVARIANT_ABSOLUTE_TOLERANCE_MPS
            for run in dynamic_runs
        ),
        "all_step_and_cumulative_network_volume_ledgers_close": (
            lake["maximum_network_volume_balance_error_m3"]
            <= LEDGER_ABSOLUTE_TOLERANCE
            and abs(lake["cumulative_network_volume_balance_error_m3"])
            <= LEDGER_ABSOLUTE_TOLERANCE
            and all(
                run["maximum_network_volume_balance_error_m3"]
                <= LEDGER_ABSOLUTE_TOLERANCE
                and abs(run["cumulative_network_volume_balance_error_m3"])
                <= LEDGER_ABSOLUTE_TOLERANCE
                for run in dynamic_runs
            )
        ),
        "all_reach_numerical_ledgers_close": all(
            run["maximum_reach_volume_ledger_error_m3"]
            <= LEDGER_ABSOLUTE_TOLERANCE
            and run["maximum_reach_momentum_ledger_error_m4s"]
            <= LEDGER_ABSOLUTE_TOLERANCE
            for run in dynamic_runs
        ),
        "perturbation_crosses_two_loss_nodes_into_outlet_reach": all(
            response["maximum_outlet_reach_discharge_response_m3s"] > 0.005
            for response in responses
        ),
        "loss_aware_response_self_converges": all(
            value <= SELF_CONVERGENCE_RATIO_LIMIT for value in ratios.values()
        ),
        "dynamic_states_remain_wet_and_cfl_compliant": all(
            run["minimum_area_m2"] > 0.0
            and run["maximum_reported_courant_number"]
            <= COURANT_NUMBER + 2.0 * np.finfo(float).eps
            for run in dynamic_runs
        ),
    }
    return {
        "schema": SCHEMA,
        "status": "subcritical_energy_loss_junction_diagnostic_gated",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_isolation": {
            "public_or_user_data_read": False,
            "action_values_read": False,
            "observation_values_read": False,
            "saved_prediction_values_read": False,
        },
        "junction_contract": {
            "unknown": "node_reference_total_head_m",
            "mass_closure": "sum_Q_upstream_equals_Q_downstream",
            "upstream_energy_equation": (
                "H_branch-H_node=K_branch*u_branch^2/(2g)"
            ),
            "downstream_energy_equation": (
                "H_node-H_branch=K_branch*u_branch^2/(2g)"
            ),
            "branch_compatibility": (
                "one_outgoing_subcritical_characteristic_per_branch"
            ),
            "loss_coefficient_units": "dimensionless_velocity_head_multiplier",
            "flow_direction": (
                "downstream_oriented_with_1e-12_m3s_numerical_tolerance"
            ),
            "junction_storage_m3": 0.0,
            "junction_momentum_closure": None,
        },
        "analytic_diagnostics": {
            "zero_loss": zero_loss.as_dict(),
            "positive_loss": positive_loss.as_dict(),
            "failure_controls": failures,
        },
        "positive_loss_lake_network": lake,
        "dynamic_response_refinement": {
            "topology": TOPOLOGY.as_dict(),
            "energy_losses": {
                key: value.as_dict() for key, value in ENERGY_LOSSES.items()
            },
            "reach_length_m": DYNAMIC_REACH_LENGTH_M,
            "duration_seconds": DYNAMIC_DURATION_SECONDS,
            "cell_counts_per_reach": list(DYNAMIC_CELL_COUNTS),
            "base_discharge_m3s": BASE_DISCHARGE_M3S,
            "upstream_a_surface_perturbation": {
                "amplitude_m": PERTURBATION_AMPLITUDE_M,
                "center_m": PERTURBATION_CENTER_M,
                "sigma_m": PERTURBATION_SIGMA_M,
            },
            "response_definition": "perturbed_run_minus_unperturbed_control",
            "self_convergence_ratio_limit": SELF_CONVERGENCE_RATIO_LIMIT,
            "comparisons": comparisons,
            "self_convergence_ratios": ratios,
            "responses": responses,
            "analytic_solution_available": False,
        },
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "claim_boundary": {
            "subcritical_total_head_junction_closure_implemented": True,
            "dimensionless_branch_energy_losses_implemented": True,
            "loss_aware_dendritic_dag_scheduling_implemented": True,
            "loss_aware_dynamic_self_convergence_gate_passed": gates[
                "loss_aware_response_self_converges"
            ],
            "junction_vector_momentum_closure_implemented": False,
            "reverse_flow_energy_junction_implemented": False,
            "dry_or_supercritical_energy_junction_implemented": False,
            "structure_specific_loss_model_implemented": False,
            "loss_coefficients_calibrated_from_observations": False,
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
