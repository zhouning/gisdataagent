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
    DynamicWaveCellState,
    PrismaticDynamicWaveState,
    TrapezoidalChannelSection,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_junction import (
    DynamicWaveNetworkReach,
)


def _reach(
    reach_id: str,
    *,
    section: TrapezoidalChannelSection,
    area: float,
    discharge: float,
) -> DynamicWaveNetworkReach:
    return DynamicWaveNetworkReach(
        reach_id=reach_id,
        state=PrismaticDynamicWaveState(
            area_m2=(area,) * 4,
            discharge_m3s=(discharge,) * 4,
        ),
        bed_elevation_m=(0.0,) * 4,
        sections=(section,) * 4,
        cell_length_m=100.0,
        manning_n=(1e-6,) * 4,
        lateral_inflow_m2s=(0.0,) * 4,
    )


def _two_junction_network(
    *,
    discharge_scale: float = 1.0,
) -> tuple[
    DynamicWaveDendriticTopology,
    tuple[DynamicWaveNetworkReach, ...],
    dict[str, FixedDynamicWaveBoundary],
    FixedDynamicWaveBoundary,
]:
    topology = DynamicWaveDendriticTopology(
        reach_ids=("A", "B", "C", "D", "E"),
        downstream_reach_ids=("C", "C", "E", "E", None),
    )
    section = TrapezoidalChannelSection(10.0, 2.0)
    area = section.area_m2(2.0)
    discharges = {
        "A": 2.0 * discharge_scale,
        "B": 3.0 * discharge_scale,
        "C": 5.0 * discharge_scale,
        "D": 4.0 * discharge_scale,
        "E": 9.0 * discharge_scale,
    }
    reaches = tuple(
        _reach(
            reach_id,
            section=section,
            area=area,
            discharge=discharges[reach_id],
        )
        for reach_id in topology.reach_ids
    )
    source_boundaries = {
        reach_id: FixedDynamicWaveBoundary(
            DynamicWaveCellState(area, discharges[reach_id]), 0.0
        )
        for reach_id in topology.source_reach_ids
    }
    outlet = FixedDynamicWaveBoundary(
        DynamicWaveCellState(area, discharges["E"]), 0.0
    )
    return topology, reaches, source_boundaries, outlet


def test_dendritic_topology_exposes_sources_nodes_and_outlet():
    topology, _, _, _ = _two_junction_network()

    assert topology.source_reach_ids == ("A", "B", "D")
    assert topology.junction_reach_ids == ("C", "E")
    assert topology.outlet_reach_id == "E"
    assert topology.upstream_reach_ids("C") == ("A", "B")
    assert topology.upstream_reach_ids("E") == ("C", "D")


@pytest.mark.parametrize(
    ("reach_ids", "downstream_ids", "error"),
    (
        (("A", "B"), (None, None), "dynamic_wave_dendritic_topology_invalid"),
        (
            ("A", "B", "C"),
            ("B", "A", None),
            "dynamic_wave_dendritic_topology_cycle",
        ),
        (("A", "B"), ("missing", None), "dynamic_wave_dendritic_topology_invalid"),
    ),
)
def test_dendritic_topology_fails_closed(
    reach_ids: tuple[str, ...],
    downstream_ids: tuple[str | None, ...],
    error: str,
):
    with pytest.raises(ValueError, match=error):
        DynamicWaveDendriticTopology(reach_ids, downstream_ids)


def test_two_junction_step_closes_every_node_and_global_mass_ledger():
    topology, reaches, source_boundaries, outlet = _two_junction_network()
    timestep = maximum_dendritic_dynamic_wave_stable_timestep_seconds(
        topology,
        reaches,
        source_left_boundaries=source_boundaries,
        outlet_right_boundary=outlet,
        courant_number=0.4,
    )

    step = advance_dendritic_dynamic_wave_network_open(
        topology,
        reaches,
        source_left_boundaries=source_boundaries,
        outlet_right_boundary=outlet,
        timestep_seconds=timestep,
        maximum_courant_number=0.4,
        lateral_momentum_convention="zero_longitudinal_momentum",
    )

    assert len(step.junctions) == 2
    assert [value.downstream_branch_id for value in step.junctions] == ["C", "E"]
    assert [value.common_free_surface_elevation_m for value in step.junctions] == (
        pytest.approx([2.0, 2.0])
    )
    assert step.maximum_absolute_node_mass_balance_residual_m3s <= 2e-12
    assert step.network_volume_balance_error_m3 == pytest.approx(0.0, abs=1e-8)
    assert step.maximum_absolute_reach_volume_ledger_error_m3 == pytest.approx(
        0.0, abs=1e-8
    )
    assert step.maximum_absolute_reach_momentum_ledger_error_m4s == pytest.approx(
        0.0, abs=1e-8
    )
    assert step.minimum_area_m2 > 0.0
    assert step.maximum_courant_number <= 0.4 + 5e-16


def test_dendritic_scheduler_supports_one_in_one_out_serial_node():
    section = TrapezoidalChannelSection(10.0, 2.0)
    area = section.area_m2(2.0)
    topology = DynamicWaveDendriticTopology(("A", "B"), ("B", None))
    reaches = tuple(
        _reach(
            reach_id,
            section=section,
            area=area,
            discharge=4.0,
        )
        for reach_id in topology.reach_ids
    )
    source = {
        "A": FixedDynamicWaveBoundary(DynamicWaveCellState(area, 4.0), 0.0)
    }
    outlet = FixedDynamicWaveBoundary(DynamicWaveCellState(area, 4.0), 0.0)
    timestep = maximum_dendritic_dynamic_wave_stable_timestep_seconds(
        topology,
        reaches,
        source_left_boundaries=source,
        outlet_right_boundary=outlet,
        courant_number=0.4,
    )

    step = advance_dendritic_dynamic_wave_network_open(
        topology,
        reaches,
        source_left_boundaries=source,
        outlet_right_boundary=outlet,
        timestep_seconds=timestep,
        maximum_courant_number=0.4,
        lateral_momentum_convention="zero_longitudinal_momentum",
    )

    assert len(step.junctions) == 1
    assert step.junctions[0].upstream_branch_ids == ("A",)
    assert step.junctions[0].downstream_branch_id == "B"
    assert step.network_volume_balance_error_m3 == pytest.approx(0.0, abs=1e-8)


def test_dendritic_source_split_and_global_lateral_ledger_close():
    topology, reaches, source_boundaries, outlet = _two_junction_network()
    original = reaches[0]
    lateral_rate = 1e-3
    reaches = (
        DynamicWaveNetworkReach(
            reach_id=original.reach_id,
            state=original.state,
            bed_elevation_m=original.bed_elevation_m,
            sections=original.sections,
            cell_length_m=original.cell_length_m,
            manning_n=original.manning_n,
            lateral_inflow_m2s=(lateral_rate,) * original.state.cell_count,
        ),
        *reaches[1:],
    )
    timestep = maximum_dendritic_dynamic_wave_stable_timestep_seconds(
        topology,
        reaches,
        source_left_boundaries=source_boundaries,
        outlet_right_boundary=outlet,
        courant_number=0.4,
    )

    step = advance_dendritic_dynamic_wave_network_open(
        topology,
        reaches,
        source_left_boundaries=source_boundaries,
        outlet_right_boundary=outlet,
        timestep_seconds=timestep,
        maximum_courant_number=0.4,
        lateral_momentum_convention="zero_longitudinal_momentum",
    )

    assert step.lateral_volume_change_m3 == pytest.approx(
        lateral_rate
        * original.state.cell_count
        * original.cell_length_m
        * timestep
    )
    assert step.network_volume_balance_error_m3 == pytest.approx(0.0, abs=1e-8)


def test_dendritic_scheduler_rejects_supercritical_terminal():
    topology, reaches, source_boundaries, outlet = _two_junction_network()
    section = reaches[0].sections[0]
    supercritical = _reach(
        "A", section=section, area=5.0, discharge=40.0
    )
    reaches = (supercritical, *reaches[1:])

    with pytest.raises(
        ValueError, match="dynamic_wave_confluence_no_subcritical_root"
    ):
        maximum_dendritic_dynamic_wave_stable_timestep_seconds(
            topology,
            reaches,
            source_left_boundaries=source_boundaries,
            outlet_right_boundary=outlet,
            courant_number=0.4,
        )


def test_compiled_dendritic_dag_protocol_passes_without_admission():
    from scripts import compile_geotransport_dynamic_wave_dag_gates as gates

    report = gates.compile_gates()

    assert report["all_gates_passed"] is True
    assert report["dynamic_refinement"]["cell_counts_per_reach"] == [16, 32, 64]
    assert report["claim_boundary"][
        "single_outlet_dendritic_dag_implemented"
    ] is True
    assert report["claim_boundary"][
        "whole_network_mass_ledger_implemented"
    ] is True
    assert report["claim_boundary"][
        "junction_momentum_or_energy_closure_implemented"
    ] is False
    assert report["claim_boundary"]["candidate_operator_admitted"] is False
