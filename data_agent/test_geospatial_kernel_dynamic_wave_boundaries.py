from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_boundaries import (
    CharacteristicDynamicWaveBoundary,
    dynamic_wave_characteristic_potential_mps,
    resolve_characteristic_dynamic_wave_boundary,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_coupled import (
    advance_coupled_dynamic_wave_open,
    maximum_open_stable_timestep_seconds,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_flux import (
    STANDARD_GRAVITY_MPS2,
    DynamicWaveCellState,
    PrismaticDynamicWaveState,
    TrapezoidalChannelSection,
)


def _section() -> TrapezoidalChannelSection:
    return TrapezoidalChannelSection(10.0, 2.0)


def test_rectangular_characteristic_potential_is_two_c():
    section = TrapezoidalChannelSection(10.0, 0.0)
    depth = 2.0
    area = section.area_m2(depth)

    potential = dynamic_wave_characteristic_potential_mps(area, section)

    assert potential == pytest.approx(
        2.0 * (STANDARD_GRAVITY_MPS2 * depth) ** 0.5
    )


def test_trapezoidal_characteristic_potential_derivative_is_c_over_a():
    section = _section()
    area = 20.0
    epsilon = 1e-4
    derivative = (
        dynamic_wave_characteristic_potential_mps(area + epsilon, section)
        - dynamic_wave_characteristic_potential_mps(area - epsilon, section)
    ) / (2.0 * epsilon)
    expected = section.gravity_wave_celerity_mps(area) / area

    assert derivative == pytest.approx(expected, rel=1e-9)


@pytest.mark.parametrize("side", ["left", "right"])
def test_area_boundary_preserves_outgoing_invariant(side):
    section = _section()
    interior = DynamicWaveCellState(20.0, 5.0)
    boundary = CharacteristicDynamicWaveBoundary(
        side=side,
        prescribed_quantity="area_m2",
        prescribed_value=21.0,
        bed_elevation_m=0.0,
    )

    resolved = resolve_characteristic_dynamic_wave_boundary(
        boundary, interior, section
    )

    assert resolved.state.area_m2 == 21.0
    assert resolved.outgoing_invariant_residual_mps == pytest.approx(
        0.0, abs=1e-12
    )
    assert resolved.boundary_characteristic_speeds_mps[0] < 0.0
    assert resolved.boundary_characteristic_speeds_mps[1] > 0.0


@pytest.mark.parametrize("side", ["left", "right"])
def test_discharge_boundary_recovers_uniform_subcritical_state(side):
    section = _section()
    interior = DynamicWaveCellState(20.0, 5.0)
    boundary = CharacteristicDynamicWaveBoundary(
        side=side,
        prescribed_quantity="discharge_m3s",
        prescribed_value=5.0,
        bed_elevation_m=0.0,
    )

    resolved = resolve_characteristic_dynamic_wave_boundary(
        boundary, interior, section
    )

    assert resolved.state.area_m2 == pytest.approx(20.0, rel=1e-12)
    assert resolved.state.discharge_m3s == 5.0
    assert resolved.outgoing_invariant_residual_mps == pytest.approx(
        0.0, abs=1e-12
    )


def test_free_surface_boundary_converts_stage_using_boundary_bed():
    section = _section()
    interior = DynamicWaveCellState(20.0, 5.0)
    boundary = CharacteristicDynamicWaveBoundary(
        side="right",
        prescribed_quantity="free_surface_elevation_m",
        prescribed_value=2.5,
        bed_elevation_m=0.5,
    )

    resolved = resolve_characteristic_dynamic_wave_boundary(
        boundary, interior, section
    )

    assert resolved.state.area_m2 == pytest.approx(section.area_m2(2.0))
    assert resolved.outgoing_invariant_residual_mps == pytest.approx(
        0.0, abs=1e-12
    )


def test_boundary_section_can_differ_from_interior_section():
    interior_section = _section()
    boundary_section = TrapezoidalChannelSection(8.0, 1.0)
    interior = DynamicWaveCellState(20.0, 5.0)
    boundary = CharacteristicDynamicWaveBoundary(
        side="right",
        prescribed_quantity="free_surface_elevation_m",
        prescribed_value=2.5,
        bed_elevation_m=0.5,
    )

    resolved = resolve_characteristic_dynamic_wave_boundary(
        boundary,
        interior,
        interior_section,
        boundary_section=boundary_section,
    )

    assert resolved.state.area_m2 == pytest.approx(boundary_section.area_m2(2.0))
    assert resolved.outgoing_invariant_residual_mps == pytest.approx(
        0.0, abs=1e-12
    )


def test_characteristic_boundary_rejects_supercritical_interior():
    section = _section()
    boundary = CharacteristicDynamicWaveBoundary(
        side="left",
        prescribed_quantity="discharge_m3s",
        prescribed_value=40.0,
        bed_elevation_m=0.0,
    )

    with pytest.raises(
        ValueError,
        match="dynamic_wave_characteristic_boundary_interior_not_subcritical",
    ):
        resolve_characteristic_dynamic_wave_boundary(
            boundary, DynamicWaveCellState(5.0, 40.0), section
        )


def test_coupled_flat_lake_is_identity_with_characteristic_boundaries():
    section = _section()
    area = section.area_m2(2.0)
    state = PrismaticDynamicWaveState(
        area_m2=(area,) * 6,
        discharge_m3s=(0.0,) * 6,
    )
    left = CharacteristicDynamicWaveBoundary(
        "left", "area_m2", area, 0.0
    )
    right = CharacteristicDynamicWaveBoundary(
        "right", "free_surface_elevation_m", 2.0, 0.0
    )
    timestep = maximum_open_stable_timestep_seconds(
        state,
        section,
        left_boundary=left,
        right_boundary=right,
        cell_length_m=100.0,
        courant_number=0.45,
    )
    result = advance_coupled_dynamic_wave_open(
        state,
        (0.0,) * 6,
        section,
        left_boundary=left,
        right_boundary=right,
        manning_n=(0.035,) * 6,
        lateral_inflow_m2s=(0.0,) * 6,
        lateral_momentum_convention="zero_longitudinal_momentum",
        cell_length_m=100.0,
        timestep_seconds=timestep,
        maximum_courant_number=0.45,
    )

    assert result.state == state
    assert result.boundary_semantics == "characteristic_ghost_state"
    assert result.volume_balance_error_m3 == 0.0
    assert result.momentum_ledger_error_m4s == 0.0
    assert result.left_characteristic_boundary is not None
    assert result.right_characteristic_boundary is not None


def test_coupled_boundary_rejects_side_mismatch():
    section = _section()
    state = PrismaticDynamicWaveState((20.0, 20.0), (5.0, 5.0))
    wrong_left = CharacteristicDynamicWaveBoundary(
        "right", "area_m2", 20.0, 0.0
    )
    right = CharacteristicDynamicWaveBoundary(
        "right", "area_m2", 20.0, 0.0
    )

    with pytest.raises(
        ValueError, match="dynamic_wave_characteristic_boundary_side_mismatch"
    ):
        maximum_open_stable_timestep_seconds(
            state,
            section,
            left_boundary=wrong_left,
            right_boundary=right,
            cell_length_m=100.0,
            courant_number=0.45,
        )


def test_compiled_characteristic_boundary_protocol_passes_without_admission():
    from scripts import (
        compile_geotransport_dynamic_wave_characteristic_boundary_gates as gates,
    )

    report = gates.compile_gates()

    assert report["all_gates_passed"] is True
    assert report["moving_uniform_flow"]["cell_counts"] == [24, 48, 96]
    assert report["claim_boundary"][
        "subcritical_characteristic_boundaries_implemented"
    ] is True
    assert report["claim_boundary"][
        "supercritical_characteristic_boundaries_implemented"
    ] is False
    assert report["claim_boundary"]["candidate_operator_admitted"] is False
