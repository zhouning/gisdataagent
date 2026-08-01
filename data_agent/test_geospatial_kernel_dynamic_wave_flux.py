from __future__ import annotations

import numpy as np
import pytest

from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_flux import (
    STANDARD_GRAVITY_MPS2,
    DynamicWaveCellState,
    PrismaticDynamicWaveState,
    TrapezoidalChannelSection,
    advance_prismatic_dynamic_wave_periodic,
    dynamic_wave_characteristic_speeds_mps,
    dynamic_wave_physical_flux,
    hll_dynamic_wave_flux,
    local_inertial_physical_flux,
    maximum_stable_timestep_seconds,
)


def _section() -> TrapezoidalChannelSection:
    return TrapezoidalChannelSection(
        bottom_width_m=10.0,
        side_slope_horizontal_per_vertical=2.0,
    )


def test_pressure_flux_derivative_matches_gravity_characteristic():
    section = _section()
    area = 20.0
    epsilon = 1e-5
    plus = dynamic_wave_physical_flux(DynamicWaveCellState(area + epsilon, 0.0), section)
    minus = dynamic_wave_physical_flux(DynamicWaveCellState(area - epsilon, 0.0), section)
    derivative = (plus.momentum_flux_m4s2 - minus.momentum_flux_m4s2) / (
        2.0 * epsilon
    )
    expected = STANDARD_GRAVITY_MPS2 * area / section.top_width_m(area)

    assert derivative == pytest.approx(expected, rel=1e-9)


def test_dynamic_flux_decomposes_into_local_inertial_and_convective_terms():
    section = _section()
    state = DynamicWaveCellState(20.0, 30.0)
    dynamic = dynamic_wave_physical_flux(state, section)
    inertial = local_inertial_physical_flux(state, section)

    assert dynamic.area_flux_m3s == inertial.area_flux_m3s
    assert dynamic.momentum_flux_m4s2 - inertial.momentum_flux_m4s2 == pytest.approx(
        state.discharge_m3s**2 / state.area_m2
    )


def test_identical_state_hll_flux_equals_physical_flux():
    section = _section()
    state = DynamicWaveCellState(20.0, 5.0)
    result = hll_dynamic_wave_flux(state, state, section)
    physical = dynamic_wave_physical_flux(state, section)

    assert result.flux.area_flux_m3s == pytest.approx(physical.area_flux_m3s)
    assert result.flux.momentum_flux_m4s2 == pytest.approx(
        physical.momentum_flux_m4s2
    )
    assert result.wave_regime == "subcritical_or_transcritical"


def test_hll_uses_upstream_physical_flux_when_both_waves_move_downstream():
    section = _section()
    left = DynamicWaveCellState(5.0, 40.0)
    right = DynamicWaveCellState(4.0, 32.0)
    assert dynamic_wave_characteristic_speeds_mps(left, section)[0] > 0.0
    result = hll_dynamic_wave_flux(left, right, section)

    assert result.wave_regime == "right_going_supercritical"
    assert result.flux == dynamic_wave_physical_flux(left, section)


def test_uniform_periodic_state_is_an_exact_identity():
    section = _section()
    state = PrismaticDynamicWaveState(
        area_m2=(20.0,) * 8,
        discharge_m3s=(5.0,) * 8,
    )
    timestep = maximum_stable_timestep_seconds(
        state, section, cell_length_m=100.0, courant_number=0.8
    )
    result = advance_prismatic_dynamic_wave_periodic(
        state,
        section,
        cell_length_m=100.0,
        timestep_seconds=timestep,
        maximum_courant_number=0.8,
    )

    assert result.state == state
    assert result.volume_balance_error_m3 == 0.0
    assert result.discharge_integral_balance_error_m4s == 0.0


def test_wet_dam_break_step_preserves_volume_momentum_and_nonnegative_area():
    section = _section()
    state = PrismaticDynamicWaveState(
        area_m2=(30.0, 30.0, 30.0, 30.0, 5.0, 5.0, 5.0, 5.0),
        discharge_m3s=(0.0,) * 8,
    )
    timestep = maximum_stable_timestep_seconds(
        state, section, cell_length_m=100.0, courant_number=0.5
    )
    result = advance_prismatic_dynamic_wave_periodic(
        state,
        section,
        cell_length_m=100.0,
        timestep_seconds=timestep,
        maximum_courant_number=0.5,
    )

    assert result.finite_state is True
    assert result.nonnegative_area is True
    assert result.minimum_area_m2 >= 0.0
    assert result.volume_balance_error_m3 == pytest.approx(0.0, abs=1e-10)
    assert result.discharge_integral_balance_error_m4s == pytest.approx(
        0.0, abs=1e-10
    )


def test_step_rejects_cfl_violation():
    section = _section()
    state = PrismaticDynamicWaveState(
        area_m2=(20.0, 25.0),
        discharge_m3s=(0.0, 0.0),
    )
    stable = maximum_stable_timestep_seconds(
        state, section, cell_length_m=100.0, courant_number=0.8
    )

    with pytest.raises(ValueError, match="dynamic_wave_step_cfl_exceeded"):
        advance_prismatic_dynamic_wave_periodic(
            state,
            section,
            cell_length_m=100.0,
            timestep_seconds=stable * 1.01,
            maximum_courant_number=0.8,
        )


def test_dry_bed_pressure_wave_remains_positive_and_conservative_for_100_steps():
    section = _section()
    state = PrismaticDynamicWaveState(
        area_m2=(30.0,) * 32 + (0.0,) * 32,
        discharge_m3s=(0.0,) * 64,
    )
    initial_volume = sum(state.area_m2) * 100.0
    initial_momentum = sum(state.discharge_m3s) * 100.0

    for _ in range(100):
        timestep = maximum_stable_timestep_seconds(
            state, section, cell_length_m=100.0, courant_number=0.5
        )
        result = advance_prismatic_dynamic_wave_periodic(
            state,
            section,
            cell_length_m=100.0,
            timestep_seconds=timestep,
            maximum_courant_number=0.5,
        )
        state = result.state

    assert min(state.area_m2) >= 0.0
    assert sum(state.area_m2) * 100.0 == pytest.approx(
        initial_volume, abs=1e-9
    )
    assert sum(state.discharge_m3s) * 100.0 == pytest.approx(
        initial_momentum, abs=1e-9
    )


@pytest.mark.parametrize(
    "state",
    [
        DynamicWaveCellState(0.0, 0.0),
        DynamicWaveCellState(10.0, -2.0),
    ],
)
def test_fluxes_remain_finite_for_dry_and_reverse_flow_states(state):
    section = _section()
    flux = dynamic_wave_physical_flux(state, section)

    assert np.isfinite(flux.as_array()).all()


def test_compiled_homogeneous_protocol_passes_without_admitting_operator():
    from scripts.compile_geotransport_dynamic_wave_homogeneous_gates import (
        compile_gates,
    )

    report = compile_gates()

    assert report["all_gates_passed"] is True
    assert report["claim_boundary"][
        "homogeneous_prismatic_flux_implemented"
    ] is True
    assert report["claim_boundary"][
        "well_balanced_source_operator_implemented"
    ] is False
    assert report["claim_boundary"]["network_operator_implemented"] is False
    assert report["claim_boundary"]["candidate_operator_admitted"] is False
