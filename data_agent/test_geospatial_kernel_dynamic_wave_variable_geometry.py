from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_boundaries import (
    CharacteristicDynamicWaveBoundary,
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
    advance_variable_geometry_hydrostatic_open,
    apply_variable_geometry_manning_friction_only_source,
    maximum_coupled_variable_geometry_open_stable_timestep_seconds,
    maximum_variable_geometry_open_stable_timestep_seconds,
    variable_geometry_hydrostatic_hll_flux,
)


def _sections() -> tuple[TrapezoidalChannelSection, ...]:
    return (
        TrapezoidalChannelSection(8.0, 1.0),
        TrapezoidalChannelSection(12.0, 2.0),
        TrapezoidalChannelSection(6.0, 0.5),
        TrapezoidalChannelSection(10.0, 1.5),
    )


def test_identical_sections_reduce_to_stage_two_hydrostatic_flux():
    section = TrapezoidalChannelSection(10.0, 2.0)
    left = DynamicWaveCellState(20.0, 5.0)
    right = DynamicWaveCellState(18.0, 4.0)
    expected = hydrostatic_reconstruction_hll_flux(
        left,
        right,
        left_bed_elevation_m=0.2,
        right_bed_elevation_m=0.5,
        section=section,
    )
    result = variable_geometry_hydrostatic_hll_flux(
        left,
        right,
        left_bed_elevation_m=0.2,
        right_bed_elevation_m=0.5,
        left_section=section,
        right_section=section,
    )

    assert result.left_cell_flux.area_flux_m3s == pytest.approx(
        expected.left_cell_flux.area_flux_m3s
    )
    assert result.left_cell_flux.momentum_flux_m4s2 == pytest.approx(
        expected.left_cell_flux.momentum_flux_m4s2
    )
    assert result.right_cell_flux.area_flux_m3s == pytest.approx(
        expected.right_cell_flux.area_flux_m3s
    )
    assert result.right_cell_flux.momentum_flux_m4s2 == pytest.approx(
        expected.right_cell_flux.momentum_flux_m4s2
    )


def test_variable_section_lake_at_rest_is_well_balanced_for_100_open_steps():
    sections = _sections()
    bed = (0.2, 0.5, 0.8, 0.4)
    surface = 3.0
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
    left_state = DynamicWaveCellState(
        left_section.area_m2(surface - left_bed), 0.0
    )
    right_state = DynamicWaveCellState(
        right_section.area_m2(surface - right_bed), 0.0
    )
    for _ in range(100):
        timestep = maximum_variable_geometry_open_stable_timestep_seconds(
            state,
            sections,
            left_boundary_state=left_state,
            right_boundary_state=right_state,
            left_boundary_section=left_section,
            right_boundary_section=right_section,
            cell_length_m=100.0,
            courant_number=0.45,
        )
        result = advance_variable_geometry_hydrostatic_open(
            state,
            bed,
            sections,
            left_boundary_state=left_state,
            right_boundary_state=right_state,
            left_boundary_bed_elevation_m=left_bed,
            right_boundary_bed_elevation_m=right_bed,
            left_boundary_section=left_section,
            right_boundary_section=right_section,
            cell_length_m=100.0,
            timestep_seconds=timestep,
            maximum_courant_number=0.45,
        )
        state = result.state
        assert result.volume_balance_error_m3 == pytest.approx(0.0, abs=1e-10)

    assert state.area_m2 == pytest.approx(initial.area_m2, abs=1e-12)
    assert state.discharge_m3s == pytest.approx((0.0,) * len(sections), abs=1e-12)


def test_variable_geometry_open_step_closes_boundary_mass_ledger():
    sections = _sections()
    state = PrismaticDynamicWaveState(
        tuple(section.area_m2(2.0) for section in sections),
        (5.0, 4.0, 3.0, 2.0),
    )
    left_state = DynamicWaveCellState(sections[0].area_m2(2.0), 5.0)
    right_state = DynamicWaveCellState(sections[-1].area_m2(2.0), 2.0)
    timestep = maximum_variable_geometry_open_stable_timestep_seconds(
        state,
        sections,
        left_boundary_state=left_state,
        right_boundary_state=right_state,
        left_boundary_section=sections[0],
        right_boundary_section=sections[-1],
        cell_length_m=100.0,
        courant_number=0.45,
    )
    result = advance_variable_geometry_hydrostatic_open(
        state,
        (0.0,) * len(sections),
        sections,
        left_boundary_state=left_state,
        right_boundary_state=right_state,
        left_boundary_bed_elevation_m=0.0,
        right_boundary_bed_elevation_m=0.0,
        left_boundary_section=sections[0],
        right_boundary_section=sections[-1],
        cell_length_m=100.0,
        timestep_seconds=timestep,
        maximum_courant_number=0.45,
    )

    assert result.volume_after_m3 == pytest.approx(
        result.volume_before_m3 + result.prescribed_boundary_volume_change_m3
    )
    assert result.volume_balance_error_m3 == pytest.approx(0.0, abs=1e-10)
    assert result.minimum_area_m2 >= 0.0


def test_variable_geometry_friction_uses_each_cell_section_and_preserves_sign():
    sections = _sections()
    state = PrismaticDynamicWaveState(
        tuple(section.area_m2(2.0) for section in sections),
        (30.0, -20.0, 5.0, 0.0),
    )

    result = apply_variable_geometry_manning_friction_only_source(
        state,
        sections,
        manning_n=(0.035,) * len(sections),
        timestep_seconds=600.0,
        cell_length_m=100.0,
    )

    assert result.state.area_m2 == state.area_m2
    assert 0.0 < result.state.discharge_m3s[0] < 30.0
    assert -20.0 < result.state.discharge_m3s[1] < 0.0
    assert 0.0 < result.state.discharge_m3s[2] < 5.0
    assert result.state.discharge_m3s[3] == 0.0
    assert result.flow_direction_preserved is True


def test_coupled_variable_geometry_accepts_characteristic_end_conditions():
    sections = _sections()
    depth = 2.0
    state = PrismaticDynamicWaveState(
        tuple(section.area_m2(depth) for section in sections),
        (0.0,) * len(sections),
    )
    left = CharacteristicDynamicWaveBoundary(
        "left", "free_surface_elevation_m", depth, 0.0
    )
    right = CharacteristicDynamicWaveBoundary(
        "right", "free_surface_elevation_m", depth, 0.0
    )
    timestep = maximum_coupled_variable_geometry_open_stable_timestep_seconds(
        state,
        sections,
        left_boundary=left,
        right_boundary=right,
        left_boundary_section=sections[0],
        right_boundary_section=sections[-1],
        cell_length_m=100.0,
        courant_number=0.45,
    )
    result = advance_coupled_variable_geometry_open(
        state,
        (0.0,) * len(sections),
        sections,
        left_boundary=left,
        right_boundary=right,
        left_boundary_section=sections[0],
        right_boundary_section=sections[-1],
        manning_n=(0.035,) * len(sections),
        lateral_inflow_m2s=(0.0,) * len(sections),
        lateral_momentum_convention="zero_longitudinal_momentum",
        cell_length_m=100.0,
        timestep_seconds=timestep,
        maximum_courant_number=0.45,
    )

    assert result.state.area_m2 == pytest.approx(state.area_m2, abs=1e-12)
    assert result.state.discharge_m3s == pytest.approx(
        state.discharge_m3s, abs=1e-12
    )
    assert result.boundary_semantics == "characteristic_ghost_state"
    assert result.volume_balance_error_m3 == 0.0
    assert result.momentum_ledger_error_m4s == 0.0


def test_compiled_variable_geometry_protocol_passes_without_admission():
    from scripts import (
        compile_geotransport_dynamic_wave_variable_geometry_gates as gates,
    )

    report = gates.compile_gates()

    assert report["all_gates_passed"] is True
    assert report["dynamic_refinement"]["cell_counts"] == [24, 48, 96]
    assert report["claim_boundary"][
        "variable_geometry_hydrostatic_flux_implemented"
    ] is True
    assert report["claim_boundary"][
        "variable_geometry_source_coupling_implemented"
    ] is True
    assert report["claim_boundary"]["network_operator_implemented"] is False
    assert report["claim_boundary"]["candidate_operator_admitted"] is False
