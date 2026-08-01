from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_flux import (
    DynamicWaveCellState,
    PrismaticDynamicWaveState,
    TrapezoidalChannelSection,
    maximum_stable_timestep_seconds,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_sources import (
    advance_hydrostatic_reconstruction_periodic,
    apply_lateral_inflow_source,
    apply_manning_slope_friction_source,
    hydrostatic_reconstruction_hll_flux,
    manning_friction_slope,
    manning_uniform_discharge_m3s,
)


def _section() -> TrapezoidalChannelSection:
    return TrapezoidalChannelSection(10.0, 2.0)


def _lake_at_rest():
    section = _section()
    bed = (0.0, 0.2, 0.5, 0.8, 0.5, 0.2)
    surface = 2.0
    state = PrismaticDynamicWaveState(
        area_m2=tuple(section.area_m2(surface - value) for value in bed),
        discharge_m3s=(0.0,) * len(bed),
    )
    return section, bed, state


def test_hydrostatic_interface_reconstructs_common_water_column():
    section = _section()
    left = DynamicWaveCellState(section.area_m2(2.0), 0.0)
    right = DynamicWaveCellState(section.area_m2(1.5), 0.0)
    result = hydrostatic_reconstruction_hll_flux(
        left,
        right,
        left_bed_elevation_m=0.0,
        right_bed_elevation_m=0.5,
        section=section,
    )

    assert result.reconstructed_left_state.area_m2 == pytest.approx(
        result.reconstructed_right_state.area_m2
    )
    assert result.hll.flux.area_flux_m3s == pytest.approx(0.0, abs=1e-14)


def test_lake_at_rest_is_well_balanced_for_one_periodic_step():
    section, bed, state = _lake_at_rest()
    timestep = maximum_stable_timestep_seconds(
        state, section, cell_length_m=100.0, courant_number=0.5
    )
    result = advance_hydrostatic_reconstruction_periodic(
        state,
        bed,
        section,
        cell_length_m=100.0,
        timestep_seconds=timestep,
        maximum_courant_number=0.5,
    )

    assert result.volume_balance_error_m3 == pytest.approx(0.0, abs=1e-10)
    assert result.maximum_absolute_discharge_m3s == pytest.approx(0.0, abs=1e-12)
    assert result.maximum_free_surface_change_m == pytest.approx(0.0, abs=1e-12)
    assert result.state.area_m2 == pytest.approx(state.area_m2)


def test_lake_at_rest_remains_well_balanced_for_100_steps():
    section, bed, state = _lake_at_rest()
    initial = state
    for _ in range(100):
        timestep = maximum_stable_timestep_seconds(
            state, section, cell_length_m=100.0, courant_number=0.5
        )
        result = advance_hydrostatic_reconstruction_periodic(
            state,
            bed,
            section,
            cell_length_m=100.0,
            timestep_seconds=timestep,
            maximum_courant_number=0.5,
        )
        state = result.state

    assert state.area_m2 == pytest.approx(initial.area_m2, abs=1e-12)
    assert state.discharge_m3s == pytest.approx(initial.discharge_m3s, abs=1e-12)


def test_manning_uniform_flow_is_exact_source_equilibrium():
    section = _section()
    area = 20.0
    slope = 0.002
    roughness = 0.035
    discharge = manning_uniform_discharge_m3s(
        area_m2=area,
        bed_slope=slope,
        manning_n=roughness,
        section=section,
    )
    state = PrismaticDynamicWaveState(
        area_m2=(area,) * 4,
        discharge_m3s=(discharge,) * 4,
    )
    result = apply_manning_slope_friction_source(
        state,
        section,
        bed_slope=(slope,) * 4,
        manning_n=(roughness,) * 4,
        timestep_seconds=300.0,
        cell_length_m=100.0,
    )

    assert manning_friction_slope(
        DynamicWaveCellState(area, discharge),
        section,
        manning_n=roughness,
    ) == pytest.approx(slope)
    assert result.state == state
    assert result.volume_balance_error_m3 == 0.0


def test_flat_bed_friction_dissipates_without_reversing_flow():
    section = _section()
    state = PrismaticDynamicWaveState(
        area_m2=(20.0, 20.0),
        discharge_m3s=(30.0, 5.0),
    )
    result = apply_manning_slope_friction_source(
        state,
        section,
        bed_slope=(0.0, 0.0),
        manning_n=(0.035, 0.035),
        timestep_seconds=3_600.0,
        cell_length_m=100.0,
    )

    assert result.state.area_m2 == state.area_m2
    assert 0.0 < result.state.discharge_m3s[0] < state.discharge_m3s[0]
    assert 0.0 < result.state.discharge_m3s[1] < state.discharge_m3s[1]
    assert result.flow_direction_preserved is True
    assert result.volume_balance_error_m3 == 0.0


def test_slope_source_moves_flow_monotonically_toward_manning_equilibrium():
    section = _section()
    area = 20.0
    slope = 0.002
    roughness = 0.035
    equilibrium = manning_uniform_discharge_m3s(
        area_m2=area,
        bed_slope=slope,
        manning_n=roughness,
        section=section,
    )
    state = PrismaticDynamicWaveState(
        area_m2=(area, area),
        discharge_m3s=(0.5 * equilibrium, 2.0 * equilibrium),
    )
    result = apply_manning_slope_friction_source(
        state,
        section,
        bed_slope=(slope, slope),
        manning_n=(roughness, roughness),
        timestep_seconds=600.0,
        cell_length_m=100.0,
    )

    assert state.discharge_m3s[0] < result.state.discharge_m3s[0] < equilibrium
    assert equilibrium < result.state.discharge_m3s[1] < state.discharge_m3s[1]


def test_lateral_inflow_closes_volume_with_zero_momentum_injection():
    state = PrismaticDynamicWaveState(
        area_m2=(10.0, 20.0),
        discharge_m3s=(5.0, 8.0),
    )
    result = apply_lateral_inflow_source(
        state,
        lateral_inflow_m2s=(0.1, 0.2),
        timestep_seconds=10.0,
        cell_length_m=100.0,
        momentum_convention="zero_longitudinal_momentum",
    )

    assert result.state.area_m2 == pytest.approx((11.0, 22.0))
    assert result.state.discharge_m3s == state.discharge_m3s
    assert result.prescribed_lateral_volume_m3 == pytest.approx(300.0)
    assert result.volume_balance_error_m3 == pytest.approx(0.0, abs=1e-12)


def test_matched_velocity_lateral_inflow_preserves_local_velocity():
    state = PrismaticDynamicWaveState(
        area_m2=(10.0, 20.0),
        discharge_m3s=(5.0, 8.0),
    )
    result = apply_lateral_inflow_source(
        state,
        lateral_inflow_m2s=(0.1, 0.2),
        timestep_seconds=10.0,
        cell_length_m=100.0,
        momentum_convention="matched_local_velocity",
    )

    assert result.state.discharge_m3s[0] / result.state.area_m2[0] == pytest.approx(
        state.discharge_m3s[0] / state.area_m2[0]
    )
    assert result.state.discharge_m3s[1] / result.state.area_m2[1] == pytest.approx(
        state.discharge_m3s[1] / state.area_m2[1]
    )
    assert result.volume_balance_error_m3 == pytest.approx(0.0, abs=1e-12)


def test_lateral_inflow_rejects_negative_values_and_implicit_momentum_semantics():
    state = PrismaticDynamicWaveState(
        area_m2=(10.0, 20.0),
        discharge_m3s=(5.0, 8.0),
    )
    with pytest.raises(ValueError, match="lateral_source_contract_invalid"):
        apply_lateral_inflow_source(
            state,
            lateral_inflow_m2s=(-0.1, 0.2),
            timestep_seconds=10.0,
            cell_length_m=100.0,
            momentum_convention="unspecified",
        )


def test_compiled_source_protocol_passes_without_claiming_coupled_operator():
    from scripts.compile_geotransport_dynamic_wave_source_gates import (
        compile_gates,
    )

    report = compile_gates()

    assert report["all_gates_passed"] is True
    assert report["claim_boundary"][
        "hydrostatic_bed_primitive_implemented"
    ] is True
    assert report["claim_boundary"][
        "manning_slope_friction_primitive_implemented"
    ] is True
    assert report["claim_boundary"]["lateral_volume_source_implemented"] is True
    assert report["claim_boundary"][
        "source_primitives_coupled_with_homogeneous_flux"
    ] is False
    assert report["claim_boundary"]["candidate_operator_admitted"] is False
