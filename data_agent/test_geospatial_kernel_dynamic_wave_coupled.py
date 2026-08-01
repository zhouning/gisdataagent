from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_coupled import (
    FixedDynamicWaveBoundary,
    advance_coupled_dynamic_wave_open,
    maximum_open_stable_timestep_seconds,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_flux import (
    DynamicWaveCellState,
    PrismaticDynamicWaveState,
    TrapezoidalChannelSection,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_sources import (
    advance_hydrostatic_reconstruction_open,
    apply_manning_friction_only_source,
)


def _section() -> TrapezoidalChannelSection:
    return TrapezoidalChannelSection(10.0, 2.0)


def _boundary(
    section: TrapezoidalChannelSection,
    *,
    bed: float,
    surface: float,
    discharge: float = 0.0,
) -> FixedDynamicWaveBoundary:
    return FixedDynamicWaveBoundary(
        state=DynamicWaveCellState(
            section.area_m2(surface - bed), discharge
        ),
        bed_elevation_m=bed,
    )


def test_open_hydrostatic_lake_at_rest_closes_boundary_mass():
    section = _section()
    bed = (0.2, 0.5, 0.8, 0.5)
    surface = 2.0
    state = PrismaticDynamicWaveState(
        area_m2=tuple(section.area_m2(surface - value) for value in bed),
        discharge_m3s=(0.0,) * len(bed),
    )
    left = _boundary(section, bed=0.0, surface=surface)
    right = _boundary(section, bed=0.2, surface=surface)
    timestep = maximum_open_stable_timestep_seconds(
        state,
        section,
        left_boundary=left,
        right_boundary=right,
        cell_length_m=100.0,
        courant_number=0.5,
    )
    result = advance_hydrostatic_reconstruction_open(
        state,
        bed,
        section,
        left_boundary_state=left.state,
        right_boundary_state=right.state,
        left_boundary_bed_elevation_m=left.bed_elevation_m,
        right_boundary_bed_elevation_m=right.bed_elevation_m,
        cell_length_m=100.0,
        timestep_seconds=timestep,
        maximum_courant_number=0.5,
    )

    assert result.volume_balance_error_m3 == pytest.approx(0.0, abs=1e-10)
    assert result.prescribed_boundary_volume_change_m3 == pytest.approx(
        0.0, abs=1e-12
    )
    assert result.maximum_free_surface_change_m == pytest.approx(0.0, abs=1e-12)
    assert result.state.discharge_m3s == pytest.approx((0.0,) * len(bed), abs=1e-12)


def test_open_flat_uniform_flow_is_homogeneous_identity():
    section = _section()
    state = PrismaticDynamicWaveState(
        area_m2=(20.0,) * 6,
        discharge_m3s=(5.0,) * 6,
    )
    boundary = FixedDynamicWaveBoundary(
        DynamicWaveCellState(20.0, 5.0), 0.0
    )
    timestep = maximum_open_stable_timestep_seconds(
        state,
        section,
        left_boundary=boundary,
        right_boundary=boundary,
        cell_length_m=100.0,
        courant_number=0.5,
    )
    result = advance_hydrostatic_reconstruction_open(
        state,
        (0.0,) * 6,
        section,
        left_boundary_state=boundary.state,
        right_boundary_state=boundary.state,
        left_boundary_bed_elevation_m=0.0,
        right_boundary_bed_elevation_m=0.0,
        cell_length_m=100.0,
        timestep_seconds=timestep,
        maximum_courant_number=0.5,
    )

    assert result.state == state
    assert result.volume_balance_error_m3 == 0.0
    assert result.discharge_integral_change_m4s == 0.0


def test_friction_only_source_supports_reverse_flow_without_sign_change():
    section = _section()
    state = PrismaticDynamicWaveState(
        area_m2=(20.0, 20.0, 20.0),
        discharge_m3s=(-30.0, 0.0, 5.0),
    )
    result = apply_manning_friction_only_source(
        state,
        section,
        manning_n=(0.035,) * 3,
        timestep_seconds=3_600.0,
        cell_length_m=100.0,
    )

    assert state.discharge_m3s[0] < result.state.discharge_m3s[0] < 0.0
    assert result.state.discharge_m3s[1] == 0.0
    assert 0.0 < result.state.discharge_m3s[2] < state.discharge_m3s[2]
    assert result.flow_direction_preserved is True


def test_coupled_lake_at_rest_remains_balanced_and_ledgers_close():
    section = _section()
    bed = (0.2, 0.5, 0.8, 0.5)
    surface = 2.0
    state = PrismaticDynamicWaveState(
        area_m2=tuple(section.area_m2(surface - value) for value in bed),
        discharge_m3s=(0.0,) * len(bed),
    )
    left = _boundary(section, bed=0.0, surface=surface)
    right = _boundary(section, bed=0.2, surface=surface)
    timestep = maximum_open_stable_timestep_seconds(
        state,
        section,
        left_boundary=left,
        right_boundary=right,
        cell_length_m=100.0,
        courant_number=0.5,
    )
    result = advance_coupled_dynamic_wave_open(
        state,
        bed,
        section,
        left_boundary=left,
        right_boundary=right,
        manning_n=(0.035,) * len(bed),
        lateral_inflow_m2s=(0.0,) * len(bed),
        lateral_momentum_convention="zero_longitudinal_momentum",
        cell_length_m=100.0,
        timestep_seconds=timestep,
        maximum_courant_number=0.5,
    )

    assert result.volume_balance_error_m3 == pytest.approx(0.0, abs=1e-10)
    assert result.momentum_ledger_error_m4s == pytest.approx(0.0, abs=1e-10)
    assert result.state.area_m2 == pytest.approx(state.area_m2, abs=1e-12)
    assert result.state.discharge_m3s == pytest.approx(
        state.discharge_m3s, abs=1e-12
    )


def test_coupled_lateral_and_boundary_volume_ledger_is_explicit():
    section = _section()
    state = PrismaticDynamicWaveState(
        area_m2=(20.0,) * 6,
        discharge_m3s=(5.0,) * 6,
    )
    boundary = FixedDynamicWaveBoundary(
        DynamicWaveCellState(20.0, 5.0), 0.0
    )
    timestep = 1.0
    result = advance_coupled_dynamic_wave_open(
        state,
        (0.0,) * 6,
        section,
        left_boundary=boundary,
        right_boundary=boundary,
        manning_n=(0.035,) * 6,
        lateral_inflow_m2s=(0.01,) * 6,
        lateral_momentum_convention="matched_local_velocity",
        cell_length_m=100.0,
        timestep_seconds=timestep,
        maximum_courant_number=0.5,
    )

    assert result.lateral_volume_change_m3 == pytest.approx(6.0)
    assert result.volume_after_m3 == pytest.approx(
        result.volume_before_m3
        + result.lateral_volume_change_m3
        + result.boundary_volume_change_m3
    )
    assert result.volume_balance_error_m3 == pytest.approx(0.0, abs=1e-9)
    assert result.momentum_ledger_error_m4s == pytest.approx(0.0, abs=1e-9)
    assert result.minimum_area_m2 >= 0.0


def test_compiled_coupled_protocol_has_grid_refined_moving_flow_gate():
    from scripts.compile_geotransport_dynamic_wave_coupled_gates import (
        compile_gates,
    )

    report = compile_gates()

    assert report["all_gates_passed"] is True
    assert report["moving_uniform_flow"]["cell_counts"] == [24, 48, 96]
    assert report["gates"]["moving_flow_area_drift_decreases"] is True
    assert report["gates"]["moving_flow_discharge_drift_decreases"] is True
    assert report["claim_boundary"][
        "source_primitives_coupled_with_homogeneous_flux"
    ] is True
    assert report["claim_boundary"]["fixed_ghost_open_boundaries"] is True
    assert report["claim_boundary"]["variable_geometry_operator_implemented"] is False
    assert report["claim_boundary"]["network_operator_implemented"] is False
    assert report["claim_boundary"]["candidate_operator_admitted"] is False
