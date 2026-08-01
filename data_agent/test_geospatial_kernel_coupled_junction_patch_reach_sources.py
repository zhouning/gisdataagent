from __future__ import annotations

from dataclasses import replace

import pytest

from data_agent.uwm.geospatial_kernel_v2.coupled_junction_patch_reach_sources import (
    advance_source_split_coupled_junction_patch_reaches,
    maximum_source_split_coupled_junction_patch_timestep_seconds,
)
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
)
from scripts.compile_geotransport_stage18_coupled_patch_reach_gates import (
    _contract,
    _geometry,
    _rotate_vector,
    _state,
)


COURANT_NUMBER = 0.4


def _reach(branch_id: str, discharge: float, lateral: float):
    section = TrapezoidalChannelSection(10.0, 0.0)
    return DynamicWaveNetworkReach(
        branch_id,
        PrismaticDynamicWaveState((20.0,) * 4, (discharge,) * 4),
        (0.0,) * 4,
        (section,) * 4,
        100.0,
        (0.035,) * 4,
        (lateral,) * 4,
    )


def _network(
    *,
    discharges=(5.0, 7.0, 12.0),
    lateral=(0.01, 0.02, 0.005),
):
    upstream = (
        _reach("up-a", discharges[0], lateral[0]),
        _reach("up-b", discharges[1], lateral[1]),
    )
    downstream = _reach("down", discharges[2], lateral[2])
    upstream_external = tuple(
        FixedDynamicWaveBoundary(DynamicWaveCellState(20.0, value), 0.0)
        for value in discharges[:2]
    )
    downstream_external = FixedDynamicWaveBoundary(
        DynamicWaveCellState(20.0, discharges[2]), 0.0
    )
    return upstream, downstream, upstream_external, downstream_external


def _advance(
    state,
    geometry,
    contract,
    network,
    *,
    convention="zero_longitudinal_momentum",
    fraction=0.5,
):
    upstream, downstream, upstream_external, downstream_external = network
    stable = maximum_source_split_coupled_junction_patch_timestep_seconds(
        state,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        lateral_momentum_convention=convention,
        courant_number=COURANT_NUMBER,
    )
    result = advance_source_split_coupled_junction_patch_reaches(
        state,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        lateral_momentum_convention=convention,
        timestep_seconds=fraction * stable,
        maximum_courant_number=COURANT_NUMBER,
    )
    return stable, result


def test_source_split_patch_step_closes_mass_and_momentum_ledgers():
    geometry = _geometry()
    contract = _contract()
    state = _state()
    network = _network()

    stable, result = _advance(state, geometry, contract, network)
    traces = (*result.upstream_source_traces, result.downstream_source_trace)
    report = result.as_dict()

    assert stable > 0.0
    assert result.lateral_volume_change_m3 > 0.0
    assert result.lateral_momentum_change_magnitude_m4s == pytest.approx(
        0.0, abs=1e-13
    )
    assert all(
        value.friction_longitudinal_momentum_change_m4s < 0.0
        for value in traces
    )
    assert abs(result.total_volume_ledger_error_m3) <= 1e-8
    assert result.geographic_momentum_ledger_error_magnitude_m4s <= 1e-9
    assert (
        result.conservative_core_step
        .maximum_opening_momentum_closure_error_m4s
        <= 1e-12
    )
    assert report["stage18_opening_exchange_preserved"] is True
    assert report["transition_reaction_preserved"] is True
    assert report["persistent_transverse_momentum_reservoir"] is False
    assert report["operator_admitted"] is False


def test_matched_velocity_lateral_source_adds_explicit_momentum():
    _, result = _advance(
        _state(),
        _geometry(),
        _contract(),
        _network(),
        convention="matched_local_velocity",
    )

    assert result.lateral_volume_change_m3 > 0.0
    assert result.lateral_momentum_change_magnitude_m4s > 0.0
    assert abs(result.total_volume_ledger_error_m3) <= 1e-8
    assert result.geographic_momentum_ledger_error_magnitude_m4s <= 1e-9


def test_source_split_patch_lake_at_rest_is_identity_without_lateral_source():
    state = _state(lake=True)
    network = _network(
        discharges=(0.0, 0.0, 0.0),
        lateral=(0.0, 0.0, 0.0),
    )
    _, result = _advance(
        state, _geometry(), _contract(), network, fraction=1.0
    )
    upstream, downstream, _, _ = network

    assert result.upstream_states == tuple(value.state for value in upstream)
    assert result.downstream_state == downstream.state
    assert result.conservative_core_step.junction_patch_step.state_after == (
        state
    )
    assert result.friction_momentum_change_magnitude_m4s == 0.0
    assert result.lateral_volume_change_m3 == 0.0
    assert abs(result.total_volume_ledger_error_m3) <= 1e-9
    assert result.geographic_momentum_ledger_error_magnitude_m4s <= 1e-10


def test_source_split_patch_step_is_rotation_covariant():
    rotation = 37.0
    geometry = _geometry()
    rotated_geometry = _geometry(rotation_degrees=rotation)
    contract = _contract()
    rotated_contract = _contract(rotation_degrees=rotation)
    state = _state()
    rotated_state = _state(rotation_degrees=rotation)
    network = _network()
    upstream, downstream, upstream_external, downstream_external = network
    common = {
        "upstream_external_boundaries": upstream_external,
        "downstream_external_boundary": downstream_external,
        "lateral_momentum_convention": "matched_local_velocity",
        "courant_number": COURANT_NUMBER,
    }
    stable = maximum_source_split_coupled_junction_patch_timestep_seconds(
        state, geometry, contract, upstream, downstream, **common
    )
    rotated_stable = (
        maximum_source_split_coupled_junction_patch_timestep_seconds(
            rotated_state,
            rotated_geometry,
            rotated_contract,
            upstream,
            downstream,
            **common,
        )
    )
    timestep = 0.5 * min(stable, rotated_stable)
    advance_common = {
        key: value for key, value in common.items() if key != "courant_number"
    }
    baseline = advance_source_split_coupled_junction_patch_reaches(
        state,
        geometry,
        contract,
        upstream,
        downstream,
        timestep_seconds=timestep,
        maximum_courant_number=COURANT_NUMBER,
        **advance_common,
    )
    rotated = advance_source_split_coupled_junction_patch_reaches(
        rotated_state,
        rotated_geometry,
        rotated_contract,
        upstream,
        downstream,
        timestep_seconds=timestep,
        maximum_courant_number=COURANT_NUMBER,
        **advance_common,
    )

    assert rotated_stable == pytest.approx(stable, abs=1e-12)
    for actual, expected in zip(
        (*rotated.upstream_states, rotated.downstream_state),
        (*baseline.upstream_states, baseline.downstream_state),
        strict=True,
    ):
        assert actual.area_m2 == pytest.approx(expected.area_m2, abs=1e-12)
        assert actual.discharge_m3s == pytest.approx(
            expected.discharge_m3s, abs=1e-12
        )
    for names in (
        ("lateral_momentum_change_east_m4s", "lateral_momentum_change_north_m4s"),
        ("friction_momentum_change_east_m4s", "friction_momentum_change_north_m4s"),
        (
            "transition_wall_fluid_impulse_east_m4s",
            "transition_wall_fluid_impulse_north_m4s",
        ),
    ):
        expected = _rotate_vector(
            getattr(baseline, names[0]), getattr(baseline, names[1]), rotation
        )
        assert (
            getattr(rotated, names[0]),
            getattr(rotated, names[1]),
        ) == pytest.approx(expected, abs=1e-12)


def test_source_split_patch_multistep_remains_positive_without_reservoir():
    geometry = _geometry()
    contract = _contract()
    state = _state()
    upstream, downstream, upstream_external, downstream_external = _network()
    maximum_mass_error = 0.0
    maximum_momentum_error = 0.0
    maximum_transition = 0.0
    minimum_area = 20.0
    minimum_volume = min(value.volume_m3 for value in state.cells)

    for _ in range(20):
        network = (
            upstream,
            downstream,
            upstream_external,
            downstream_external,
        )
        _, result = _advance(
            state,
            geometry,
            contract,
            network,
            convention="matched_local_velocity",
        )
        upstream = tuple(
            replace(reach, state=next_state)
            for reach, next_state in zip(
                upstream, result.upstream_states, strict=True
            )
        )
        downstream = replace(downstream, state=result.downstream_state)
        state = result.conservative_core_step.junction_patch_step.state_after
        maximum_mass_error = max(
            maximum_mass_error, abs(result.total_volume_ledger_error_m3)
        )
        maximum_momentum_error = max(
            maximum_momentum_error,
            result.geographic_momentum_ledger_error_magnitude_m4s,
        )
        maximum_transition = max(
            maximum_transition,
            max(
                value.transverse_momentum_flux_magnitude_m4s2
                for value in result.conservative_core_step.opening_exchanges
            ),
        )
        minimum_area = min(minimum_area, result.minimum_reach_area_m2)
        minimum_volume = min(
            minimum_volume,
            result.conservative_core_step
            .junction_patch_step.minimum_cell_volume_m3,
        )
        assert "transverse_momentum_after" not in result.as_dict()

    assert minimum_area > 0.0
    assert minimum_volume > 0.0
    assert maximum_mass_error <= 1e-8
    assert maximum_momentum_error <= 1e-9
    assert maximum_transition > 1e-6


def test_source_split_patch_rejects_cfl_and_implicit_momentum_semantics():
    state = _state()
    geometry = _geometry()
    contract = _contract()
    upstream, downstream, upstream_external, downstream_external = _network()
    stable = maximum_source_split_coupled_junction_patch_timestep_seconds(
        state,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        lateral_momentum_convention="zero_longitudinal_momentum",
        courant_number=COURANT_NUMBER,
    )
    with pytest.raises(
        ValueError, match="source_split_coupled_junction_patch_cfl_exceeded"
    ):
        advance_source_split_coupled_junction_patch_reaches(
            state,
            geometry,
            contract,
            upstream,
            downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=downstream_external,
            lateral_momentum_convention="zero_longitudinal_momentum",
            timestep_seconds=stable * 1.01,
            maximum_courant_number=COURANT_NUMBER,
        )
    with pytest.raises(
        ValueError,
        match="source_split_coupled_junction_patch_lateral_momentum_invalid",
    ):
        maximum_source_split_coupled_junction_patch_timestep_seconds(
            state,
            geometry,
            contract,
            upstream,
            downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=downstream_external,
            lateral_momentum_convention="implicit",
            courant_number=COURANT_NUMBER,
        )


def test_compiled_stage19_protocol_passes_without_admission():
    from scripts import (
        compile_geotransport_stage19_source_split_patch_reach_gates,
    )

    report = (
        compile_geotransport_stage19_source_split_patch_reach_gates
        .compile_report()
    )

    assert report["all_gates_passed"] is True
    assert report["claim_boundary"][
        "source_split_patch_reach_coupling_implemented"
    ] is True
    assert report["claim_boundary"][
        "persistent_transverse_momentum_reservoir"
    ] is False
    assert report["claim_boundary"]["patch_bed_friction_implemented"] is False
    assert report["claim_boundary"]["candidate_operator_admitted"] is False
