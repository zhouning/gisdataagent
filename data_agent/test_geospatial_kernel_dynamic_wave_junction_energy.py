from __future__ import annotations

import pytest

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
    depth = 2.0
    area = section.area_m2(depth)
    node_head = 3.0
    upstream = tuple(
        DynamicWaveJunctionTerminal(
            branch_id,
            DynamicWaveCellState(area, discharge),
            section,
            _bed_for_manufactured_head(
                node_head=node_head,
                depth=depth,
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
            node_head=node_head,
            depth=depth,
            area=area,
            discharge=5.0,
            loss_coefficient=downstream_coefficient,
            side="downstream",
        ),
    )
    loss = DynamicWaveJunctionEnergyLoss(
        ("A", "B"), upstream_coefficients, downstream_coefficient
    )
    return upstream, downstream, loss


@pytest.mark.parametrize(
    ("upstream_coefficients", "downstream_coefficient"),
    (((0.0, 0.0), 0.0), ((0.2, 0.4), 0.1)),
)
def test_energy_junction_recovers_manufactured_total_head_and_losses(
    upstream_coefficients: tuple[float, float],
    downstream_coefficient: float,
):
    upstream, downstream, loss = _manufactured_junction(
        upstream_coefficients, downstream_coefficient
    )

    result = solve_subcritical_dynamic_wave_energy_junction(
        upstream, downstream, loss
    )

    assert result.node_reference_total_head_m == pytest.approx(3.0, abs=1e-12)
    assert result.total_upstream_discharge_m3s == pytest.approx(5.0, abs=1e-12)
    assert result.downstream_discharge_m3s == pytest.approx(5.0, abs=1e-12)
    assert result.junction_mass_balance_residual_m3s == pytest.approx(
        0.0, abs=1e-12
    )
    assert result.maximum_absolute_energy_equation_residual_m <= 1e-12
    assert result.maximum_absolute_outgoing_invariant_residual_mps <= 1e-12
    assert [value.state.area_m2 for value in result.upstream_boundaries] == (
        pytest.approx([value.interior_state.area_m2 for value in upstream])
    )
    assert [value.state.discharge_m3s for value in result.upstream_boundaries] == (
        pytest.approx(
            [value.interior_state.discharge_m3s for value in upstream],
            abs=1e-12,
        )
    )
    assert result.downstream_boundary.state.area_m2 == pytest.approx(
        downstream.interior_state.area_m2
    )
    assert result.downstream_boundary.state.discharge_m3s == pytest.approx(
        downstream.interior_state.discharge_m3s, abs=1e-12
    )


def _energy_dag_network() -> tuple[
    DynamicWaveDendriticTopology,
    tuple[DynamicWaveNetworkReach, ...],
    dict[str, FixedDynamicWaveBoundary],
    FixedDynamicWaveBoundary,
    dict[str, DynamicWaveJunctionEnergyLoss],
]:
    topology = DynamicWaveDendriticTopology(
        ("A", "B", "C", "D", "E"), ("C", "C", "E", "E", None)
    )
    section = TrapezoidalChannelSection(10.0, 2.0)
    depth = 2.0
    area = section.area_m2(depth)
    flows = {"A": 2.0, "B": 3.0, "C": 5.0, "D": 4.0, "E": 9.0}
    losses = {
        "C": DynamicWaveJunctionEnergyLoss(("A", "B"), (0.2, 0.3), 0.1),
        "E": DynamicWaveJunctionEnergyLoss(("C", "D"), (0.15, 0.25), 0.1),
    }
    node_heads = {"C": 3.0, "E": 2.8}
    node_beds = {
        ("A", "right"): _bed_for_manufactured_head(
            node_head=node_heads["C"],
            depth=depth,
            area=area,
            discharge=flows["A"],
            loss_coefficient=0.2,
            side="upstream",
        ),
        ("B", "right"): _bed_for_manufactured_head(
            node_head=node_heads["C"],
            depth=depth,
            area=area,
            discharge=flows["B"],
            loss_coefficient=0.3,
            side="upstream",
        ),
        ("C", "left"): _bed_for_manufactured_head(
            node_head=node_heads["C"],
            depth=depth,
            area=area,
            discharge=flows["C"],
            loss_coefficient=0.1,
            side="downstream",
        ),
        ("C", "right"): _bed_for_manufactured_head(
            node_head=node_heads["E"],
            depth=depth,
            area=area,
            discharge=flows["C"],
            loss_coefficient=0.15,
            side="upstream",
        ),
        ("D", "right"): _bed_for_manufactured_head(
            node_head=node_heads["E"],
            depth=depth,
            area=area,
            discharge=flows["D"],
            loss_coefficient=0.25,
            side="upstream",
        ),
        ("E", "left"): _bed_for_manufactured_head(
            node_head=node_heads["E"],
            depth=depth,
            area=area,
            discharge=flows["E"],
            loss_coefficient=0.1,
            side="downstream",
        ),
    }
    endpoint_beds = {
        "A": (node_beds[("A", "right")] + 0.05, node_beds[("A", "right")]),
        "B": (node_beds[("B", "right")] + 0.05, node_beds[("B", "right")]),
        "C": (node_beds[("C", "left")], node_beds[("C", "right")]),
        "D": (node_beds[("D", "right")] + 0.05, node_beds[("D", "right")]),
        "E": (node_beds[("E", "left")], node_beds[("E", "left")] - 0.05),
    }
    reaches = []
    for reach_id in topology.reach_ids:
        left_bed, right_bed = endpoint_beds[reach_id]
        beds = tuple(
            left_bed + index * (right_bed - left_bed) / 3.0
            for index in range(4)
        )
        reaches.append(
            DynamicWaveNetworkReach(
                reach_id=reach_id,
                state=PrismaticDynamicWaveState(
                    (area,) * 4, (flows[reach_id],) * 4
                ),
                bed_elevation_m=beds,
                sections=(section,) * 4,
                cell_length_m=100.0,
                manning_n=(1e-8,) * 4,
                lateral_inflow_m2s=(0.0,) * 4,
            )
        )
    source_boundaries = {
        reach_id: FixedDynamicWaveBoundary(
            DynamicWaveCellState(area, flows[reach_id]),
            reaches[topology.reach_ids.index(reach_id)].bed_elevation_m[0],
        )
        for reach_id in topology.source_reach_ids
    }
    outlet = FixedDynamicWaveBoundary(
        DynamicWaveCellState(area, flows["E"]), reaches[-1].bed_elevation_m[-1]
    )
    return topology, tuple(reaches), source_boundaries, outlet, losses


def test_energy_loss_junctions_run_synchronously_in_dendritic_dag():
    topology, reaches, source_boundaries, outlet, losses = _energy_dag_network()
    timestep = maximum_dendritic_dynamic_wave_stable_timestep_seconds(
        topology,
        reaches,
        source_left_boundaries=source_boundaries,
        outlet_right_boundary=outlet,
        courant_number=0.4,
        junction_energy_losses=losses,
    )

    step = advance_dendritic_dynamic_wave_network_open(
        topology,
        reaches,
        source_left_boundaries=source_boundaries,
        outlet_right_boundary=outlet,
        timestep_seconds=timestep,
        maximum_courant_number=0.4,
        lateral_momentum_convention="zero_longitudinal_momentum",
        junction_energy_losses=losses,
    )

    assert all(
        isinstance(value, SubcriticalEnergyJunctionSolution)
        for value in step.junctions
    )
    assert max(
        value.maximum_absolute_energy_equation_residual_m
        for value in step.junctions
    ) <= 1e-12
    assert step.maximum_absolute_node_mass_balance_residual_m3s <= 2e-12
    assert step.network_volume_balance_error_m3 == pytest.approx(0.0, abs=1e-8)
    assert step.maximum_courant_number <= 0.4 + 5e-16


def test_energy_junction_lake_at_rest_remains_exact_with_positive_losses():
    topology, reaches, source_boundaries, outlet, losses = _energy_dag_network()
    lake_reaches = tuple(
        DynamicWaveNetworkReach(
            reach_id=reach.reach_id,
            state=PrismaticDynamicWaveState(
                tuple(
                    section.area_m2(3.5 - bed)
                    for section, bed in zip(
                        reach.sections, reach.bed_elevation_m, strict=True
                    )
                ),
                (0.0,) * reach.state.cell_count,
            ),
            bed_elevation_m=reach.bed_elevation_m,
            sections=reach.sections,
            cell_length_m=reach.cell_length_m,
            manning_n=reach.manning_n,
            lateral_inflow_m2s=reach.lateral_inflow_m2s,
        )
        for reach in reaches
    )
    source_boundaries = {
        reach_id: FixedDynamicWaveBoundary(
            DynamicWaveCellState(
                reach.sections[0].area_m2(3.5 - reach.bed_elevation_m[0]), 0.0
            ),
            reach.bed_elevation_m[0],
        )
        for reach_id, reach in zip(topology.reach_ids, lake_reaches, strict=True)
        if reach_id in topology.source_reach_ids
    }
    outlet_reach = lake_reaches[-1]
    outlet = FixedDynamicWaveBoundary(
        DynamicWaveCellState(
            outlet_reach.sections[-1].area_m2(
                3.5 - outlet_reach.bed_elevation_m[-1]
            ),
            0.0,
        ),
        outlet_reach.bed_elevation_m[-1],
    )
    timestep = maximum_dendritic_dynamic_wave_stable_timestep_seconds(
        topology,
        lake_reaches,
        source_left_boundaries=source_boundaries,
        outlet_right_boundary=outlet,
        courant_number=0.4,
        junction_energy_losses=losses,
    )

    step = advance_dendritic_dynamic_wave_network_open(
        topology,
        lake_reaches,
        source_left_boundaries=source_boundaries,
        outlet_right_boundary=outlet,
        timestep_seconds=timestep,
        maximum_courant_number=0.4,
        lateral_momentum_convention="zero_longitudinal_momentum",
        junction_energy_losses=losses,
    )

    assert max(
        abs(after - before)
        for state, reach in zip(step.states, lake_reaches, strict=True)
        for after, before in zip(
            state.area_m2, reach.state.area_m2, strict=True
        )
    ) <= 1e-12
    assert max(
        abs(value) for state in step.states for value in state.discharge_m3s
    ) <= 1e-12
    assert step.network_volume_balance_error_m3 == pytest.approx(0.0, abs=1e-8)


def test_energy_junction_rejects_reverse_flow_and_inconsistent_loss_mapping():
    upstream, downstream, loss = _manufactured_junction((0.2, 0.4), 0.1)
    reverse = DynamicWaveJunctionTerminal(
        upstream[0].branch_id,
        DynamicWaveCellState(upstream[0].interior_state.area_m2, -1.0),
        upstream[0].section,
        upstream[0].bed_elevation_m,
    )
    with pytest.raises(
        ValueError, match="dynamic_wave_energy_junction_terminal_not_supported"
    ):
        solve_subcritical_dynamic_wave_energy_junction(
            (reverse, upstream[1]), downstream, loss
        )

    topology, reaches, source_boundaries, outlet, losses = _energy_dag_network()
    with pytest.raises(
        ValueError, match="dynamic_wave_dendritic_energy_loss_contract_invalid"
    ):
        maximum_dendritic_dynamic_wave_stable_timestep_seconds(
            topology,
            reaches,
            source_left_boundaries=source_boundaries,
            outlet_right_boundary=outlet,
            courant_number=0.4,
            junction_energy_losses={"C": losses["C"]},
        )


def test_low_froude_energy_root_is_not_truncated_by_area_scan():
    section = TrapezoidalChannelSection(10.0, 2.0)
    area = section.area_m2(2.0)
    upstream = tuple(
        DynamicWaveJunctionTerminal(
            branch_id, DynamicWaveCellState(area, discharge), section, 0.0
        )
        for branch_id, discharge in (("A", 2.0), ("B", 3.0))
    )
    downstream = DynamicWaveJunctionTerminal(
        "C", DynamicWaveCellState(area, 5.0), section, 0.0
    )

    result = solve_subcritical_dynamic_wave_energy_junction(
        upstream,
        downstream,
        DynamicWaveJunctionEnergyLoss(("A", "B"), (0.1, 0.1), 0.1),
    )

    assert result.junction_mass_balance_residual_m3s == pytest.approx(
        0.0, abs=1e-12
    )
    assert result.maximum_absolute_energy_equation_residual_m <= 1e-12
    assert all(value.state.discharge_m3s > 0.0 for value in result.upstream_boundaries)
    assert result.downstream_boundary.state.discharge_m3s > 0.0


def test_compiled_energy_junction_protocol_passes_without_admission():
    from scripts import (
        compile_geotransport_dynamic_wave_energy_junction_gates as gates,
    )

    report = gates.compile_gates()

    assert report["all_gates_passed"] is True
    assert report["dynamic_response_refinement"]["cell_counts_per_reach"] == [
        16,
        32,
        64,
    ]
    assert report["claim_boundary"][
        "subcritical_total_head_junction_closure_implemented"
    ] is True
    assert report["claim_boundary"][
        "junction_vector_momentum_closure_implemented"
    ] is False
    assert report["claim_boundary"]["candidate_operator_admitted"] is False
