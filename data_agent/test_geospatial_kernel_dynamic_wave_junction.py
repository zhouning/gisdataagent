from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_coupled import (
    FixedDynamicWaveBoundary,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_flux import (
    DynamicWaveCellState,
    PrismaticDynamicWaveState,
    TrapezoidalChannelSection,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_junction import (
    DynamicWaveNetworkReach,
    DynamicWaveJunctionTerminal,
    advance_subcritical_confluence_network_open,
    maximum_subcritical_confluence_stable_timestep_seconds,
    solve_subcritical_dynamic_wave_confluence,
)


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


def test_symmetric_confluence_recovers_common_stage_and_summed_discharge():
    section = TrapezoidalChannelSection(10.0, 2.0)
    upstream = (
        _terminal(
            "up-a", section=section, bed=0.0, surface=2.0, discharge=5.0
        ),
        _terminal(
            "up-b", section=section, bed=0.0, surface=2.0, discharge=5.0
        ),
    )
    downstream = _terminal(
        "down", section=section, bed=0.0, surface=2.0, discharge=10.0
    )

    result = solve_subcritical_dynamic_wave_confluence(upstream, downstream)

    assert result.common_free_surface_elevation_m == pytest.approx(2.0)
    assert result.total_upstream_discharge_m3s == pytest.approx(10.0)
    assert result.downstream_discharge_m3s == pytest.approx(10.0)
    assert result.junction_mass_balance_residual_m3s == pytest.approx(
        0.0, abs=1e-10
    )


def test_variable_section_and_bed_confluence_recovers_manufactured_state():
    surface = 3.0
    upstream = (
        _terminal(
            "up-a",
            section=TrapezoidalChannelSection(8.0, 1.0),
            bed=0.2,
            surface=surface,
            discharge=3.0,
        ),
        _terminal(
            "up-b",
            section=TrapezoidalChannelSection(6.0, 0.5),
            bed=0.5,
            surface=surface,
            discharge=4.0,
        ),
    )
    downstream = _terminal(
        "down",
        section=TrapezoidalChannelSection(12.0, 2.0),
        bed=0.1,
        surface=surface,
        discharge=7.0,
    )

    result = solve_subcritical_dynamic_wave_confluence(upstream, downstream)

    assert result.common_free_surface_elevation_m == pytest.approx(surface)
    assert result.total_upstream_discharge_m3s == pytest.approx(7.0)
    assert result.downstream_discharge_m3s == pytest.approx(7.0)
    assert result.maximum_absolute_outgoing_invariant_residual_mps == pytest.approx(
        0.0, abs=1e-12
    )


def test_confluence_rejects_supercritical_terminal():
    section = TrapezoidalChannelSection(10.0, 2.0)
    upstream = (
        DynamicWaveJunctionTerminal(
            "up-a", DynamicWaveCellState(5.0, 40.0), section, 0.0
        ),
        _terminal(
            "up-b", section=section, bed=0.0, surface=2.0, discharge=5.0
        ),
    )
    downstream = _terminal(
        "down", section=section, bed=0.0, surface=2.0, discharge=10.0
    )

    with pytest.raises(
        ValueError, match="dynamic_wave_confluence_no_subcritical_root"
    ):
        solve_subcritical_dynamic_wave_confluence(upstream, downstream)


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
            (area,) * 4, (discharge,) * 4
        ),
        bed_elevation_m=(0.0,) * 4,
        sections=(section,) * 4,
        cell_length_m=100.0,
        manning_n=(1e-6,) * 4,
        lateral_inflow_m2s=(0.0,) * 4,
    )


def test_synchronous_confluence_step_closes_node_and_network_mass_ledgers():
    section = TrapezoidalChannelSection(10.0, 2.0)
    area = 20.0
    upstream = (
        _reach("up-a", section=section, area=area, discharge=5.0),
        _reach("up-b", section=section, area=area, discharge=7.0),
    )
    downstream = _reach(
        "down", section=section, area=area, discharge=12.0
    )
    left_boundaries = tuple(
        FixedDynamicWaveBoundary(
            DynamicWaveCellState(area, discharge), 0.0
        )
        for discharge in (5.0, 7.0)
    )
    right_boundary = FixedDynamicWaveBoundary(
        DynamicWaveCellState(area, 12.0), 0.0
    )
    timestep = maximum_subcritical_confluence_stable_timestep_seconds(
        upstream,
        downstream,
        upstream_left_boundaries=left_boundaries,
        downstream_right_boundary=right_boundary,
        courant_number=0.4,
    )
    result = advance_subcritical_confluence_network_open(
        upstream,
        downstream,
        upstream_left_boundaries=left_boundaries,
        downstream_right_boundary=right_boundary,
        lateral_momentum_convention="zero_longitudinal_momentum",
        timestep_seconds=timestep,
        maximum_courant_number=0.4,
    )

    assert result.junction.junction_mass_balance_residual_m3s == pytest.approx(
        0.0, abs=1e-10
    )
    assert result.network_volume_balance_error_m3 == pytest.approx(
        0.0, abs=1e-8
    )
    assert result.maximum_absolute_reach_volume_ledger_error_m3 == pytest.approx(
        0.0, abs=1e-8
    )
    assert result.maximum_absolute_reach_momentum_ledger_error_m4s == pytest.approx(
        0.0, abs=1e-8
    )
    assert result.minimum_area_m2 > 0.0


def test_synchronous_confluence_lake_at_rest_is_identity():
    section = TrapezoidalChannelSection(10.0, 2.0)
    area = section.area_m2(2.0)
    upstream = (
        _reach("up-a", section=section, area=area, discharge=0.0),
        _reach("up-b", section=section, area=area, discharge=0.0),
    )
    downstream = _reach(
        "down", section=section, area=area, discharge=0.0
    )
    left_boundaries = (
        FixedDynamicWaveBoundary(DynamicWaveCellState(area, 0.0), 0.0),
        FixedDynamicWaveBoundary(DynamicWaveCellState(area, 0.0), 0.0),
    )
    right_boundary = FixedDynamicWaveBoundary(
        DynamicWaveCellState(area, 0.0), 0.0
    )
    timestep = maximum_subcritical_confluence_stable_timestep_seconds(
        upstream,
        downstream,
        upstream_left_boundaries=left_boundaries,
        downstream_right_boundary=right_boundary,
        courant_number=0.4,
    )
    result = advance_subcritical_confluence_network_open(
        upstream,
        downstream,
        upstream_left_boundaries=left_boundaries,
        downstream_right_boundary=right_boundary,
        lateral_momentum_convention="zero_longitudinal_momentum",
        timestep_seconds=timestep,
        maximum_courant_number=0.4,
    )

    assert result.upstream_states == tuple(value.state for value in upstream)
    assert result.downstream_state == downstream.state
    assert result.network_volume_balance_error_m3 == 0.0


def test_compiled_confluence_protocol_passes_without_admission():
    from scripts import compile_geotransport_dynamic_wave_junction_gates as gates

    report = gates.compile_gates()

    assert report["all_gates_passed"] is True
    assert report["dynamic_refinement"]["cell_counts_per_reach"] == [16, 32, 64]
    assert report["claim_boundary"][
        "subcritical_multi_in_one_out_junction_implemented"
    ] is True
    assert report["claim_boundary"]["junction_mass_ledger_implemented"] is True
    assert report["claim_boundary"][
        "junction_momentum_or_energy_closure_implemented"
    ] is False
    assert report["claim_boundary"]["candidate_operator_admitted"] is False
