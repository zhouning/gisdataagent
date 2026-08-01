from __future__ import annotations

from dataclasses import replace
import math

import pytest

from data_agent.uwm.geospatial_kernel_v2.conservative_vector_junction import (
    ConservativeVectorJunctionContract,
)
from data_agent.uwm.geospatial_kernel_v2.coupled_junction_reach import (
    zero_terminal_transverse_momentum,
)
from data_agent.uwm.geospatial_kernel_v2.coupled_junction_reach_sources import (
    advance_source_split_coupled_junction_reaches,
    maximum_source_split_coupled_junction_timestep_seconds,
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
from data_agent.uwm.geospatial_kernel_v2.shallow_water_junction_cell import (
    JunctionCellBoundaryFace,
    ShallowWaterJunctionCellGeometry,
    ShallowWaterJunctionCellState,
)


COURANT_NUMBER = 0.4


def _geometry(*, rotation_degrees: float = 0.0):
    width = 10.0

    def azimuth(value: float) -> float:
        return (value + rotation_degrees) % 360.0

    return ShallowWaterJunctionCellGeometry(
        "junction-y",
        100.0,
        0.0,
        (
            JunctionCellBoundaryFace(
                "opening-a", "branch_opening", width, azimuth(225.0),
                "up-a", "upstream"
            ),
            JunctionCellBoundaryFace(
                "opening-b", "branch_opening", width, azimuth(135.0),
                "up-b", "upstream"
            ),
            JunctionCellBoundaryFace(
                "opening-down", "branch_opening", width, azimuth(0.0),
                "down", "downstream"
            ),
            JunctionCellBoundaryFace(
                "wall-north", "solid_wall",
                width * (math.sqrt(2.0) - 1.0), azimuth(0.0)
            ),
            JunctionCellBoundaryFace(
                "wall-east", "solid_wall", 15.0, azimuth(90.0)
            ),
            JunctionCellBoundaryFace(
                "wall-west", "solid_wall", 15.0, azimuth(270.0)
            ),
        ),
        "manufactured:stage16-closed-y-cell",
    )


def _contract(*, rotation_degrees: float = 0.0):
    return ConservativeVectorJunctionContract(
        "junction-y",
        ("up-a", "up-b"),
        "down",
        tuple(
            (value + rotation_degrees) % 360.0
            for value in (45.0, 315.0)
        ),
        rotation_degrees % 360.0,
        "manufactured:stage16",
    )


def _reach(branch_id: str, discharge: float, lateral: float):
    section = TrapezoidalChannelSection(10.0, 0.0)
    return DynamicWaveNetworkReach(
        branch_id,
        PrismaticDynamicWaveState(
            (section.area_m2(2.0),) * 4, (discharge,) * 4
        ),
        (0.0,) * 4,
        (section,) * 4,
        100.0,
        (0.035,) * 4,
        (lateral,) * 4,
    )


def _network(
    *,
    discharges: tuple[float, float, float] = (5.0, 7.0, 12.0),
    lateral: tuple[float, float, float] = (0.01, 0.02, 0.005),
):
    upstream = (
        _reach("up-a", discharges[0], lateral[0]),
        _reach("up-b", discharges[1], lateral[1]),
    )
    downstream = _reach("down", discharges[2], lateral[2])
    upstream_external = tuple(
        FixedDynamicWaveBoundary(
            DynamicWaveCellState(20.0, discharge), 0.0
        )
        for discharge in discharges[:2]
    )
    downstream_external = FixedDynamicWaveBoundary(
        DynamicWaveCellState(20.0, discharges[2]), 0.0
    )
    return upstream, downstream, upstream_external, downstream_external


def _advance(
    cell,
    geometry,
    contract,
    network,
    reservoirs,
    *,
    convention="zero_longitudinal_momentum",
    fraction=0.5,
):
    upstream, downstream, upstream_external, downstream_external = network
    common = {
        "upstream_external_boundaries": upstream_external,
        "downstream_external_boundary": downstream_external,
        "transverse_momentum": reservoirs,
        "lateral_momentum_convention": convention,
        "courant_number": COURANT_NUMBER,
    }
    stable = maximum_source_split_coupled_junction_timestep_seconds(
        cell, geometry, contract, upstream, downstream, **common
    )
    result = advance_source_split_coupled_junction_reaches(
        cell,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        transverse_momentum=reservoirs,
        lateral_momentum_convention=convention,
        timestep_seconds=fraction * stable,
        maximum_courant_number=COURANT_NUMBER,
    )
    return stable, result


def _rotate_vector(east, north, angle_degrees):
    angle = math.radians(angle_degrees)
    return (
        east * math.cos(angle) + north * math.sin(angle),
        north * math.cos(angle) - east * math.sin(angle),
    )


def test_source_split_step_closes_separate_mass_and_momentum_ledgers():
    geometry = _geometry()
    contract = _contract()
    network = _network()
    cell = ShallowWaterJunctionCellState(200.0, 12.0, -4.0)
    reservoirs = zero_terminal_transverse_momentum(contract)

    stable, result = _advance(
        cell, geometry, contract, network, reservoirs
    )
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
        result.conservative_core_step.maximum_opening_momentum_cancellation_error_m4s
        <= 1e-12
    )
    assert report["stage15_opening_exchange_preserved"] is True
    assert report["manning_friction_dissipation_explicit"] is True
    assert report["operator_admitted"] is False


def test_matched_velocity_lateral_source_adds_explicit_momentum():
    geometry = _geometry()
    contract = _contract()
    network = _network()
    cell = ShallowWaterJunctionCellState(200.0, 12.0, -4.0)
    reservoirs = zero_terminal_transverse_momentum(contract)

    _, result = _advance(
        cell,
        geometry,
        contract,
        network,
        reservoirs,
        convention="matched_local_velocity",
    )

    assert result.lateral_volume_change_m3 > 0.0
    assert result.lateral_momentum_change_magnitude_m4s > 0.0
    assert abs(result.total_volume_ledger_error_m3) <= 1e-8
    assert result.geographic_momentum_ledger_error_magnitude_m4s <= 1e-9


def test_source_split_lake_at_rest_is_identity_when_lateral_source_is_zero():
    geometry = _geometry()
    contract = _contract()
    network = _network(
        discharges=(0.0, 0.0, 0.0), lateral=(0.0, 0.0, 0.0)
    )
    cell = ShallowWaterJunctionCellState(200.0, 0.0, 0.0)
    reservoirs = zero_terminal_transverse_momentum(contract)

    _, result = _advance(
        cell, geometry, contract, network, reservoirs, fraction=1.0
    )
    upstream, downstream, _, _ = network

    assert result.upstream_states == tuple(value.state for value in upstream)
    assert result.downstream_state == downstream.state
    assert result.conservative_core_step.junction_cell_step.state_after.volume_m3 == (
        pytest.approx(cell.volume_m3, abs=1e-12)
    )
    assert result.friction_momentum_change_magnitude_m4s == 0.0
    assert result.lateral_volume_change_m3 == 0.0
    assert abs(result.total_volume_ledger_error_m3) <= 1e-9
    assert result.geographic_momentum_ledger_error_magnitude_m4s <= 1e-10


def test_source_split_step_is_rotation_covariant():
    rotation = 37.0
    geometry = _geometry()
    rotated_geometry = _geometry(rotation_degrees=rotation)
    contract = _contract()
    rotated_contract = _contract(rotation_degrees=rotation)
    network = _network()
    cell = ShallowWaterJunctionCellState(200.0, 12.0, -4.0)
    rotated_initial = _rotate_vector(12.0, -4.0, rotation)
    rotated_cell = ShallowWaterJunctionCellState(200.0, *rotated_initial)
    reservoirs = zero_terminal_transverse_momentum(contract)
    rotated_reservoirs = zero_terminal_transverse_momentum(rotated_contract)
    upstream, downstream, upstream_external, downstream_external = network
    common = {
        "upstream_external_boundaries": upstream_external,
        "downstream_external_boundary": downstream_external,
        "lateral_momentum_convention": "matched_local_velocity",
        "courant_number": COURANT_NUMBER,
    }
    stable = maximum_source_split_coupled_junction_timestep_seconds(
        cell,
        geometry,
        contract,
        upstream,
        downstream,
        transverse_momentum=reservoirs,
        **common,
    )
    rotated_stable = maximum_source_split_coupled_junction_timestep_seconds(
        rotated_cell,
        rotated_geometry,
        rotated_contract,
        upstream,
        downstream,
        transverse_momentum=rotated_reservoirs,
        **common,
    )
    timestep = 0.5 * min(stable, rotated_stable)
    advance_common = {
        key: value for key, value in common.items() if key != "courant_number"
    }
    baseline = advance_source_split_coupled_junction_reaches(
        cell,
        geometry,
        contract,
        upstream,
        downstream,
        transverse_momentum=reservoirs,
        timestep_seconds=timestep,
        maximum_courant_number=COURANT_NUMBER,
        **advance_common,
    )
    rotated = advance_source_split_coupled_junction_reaches(
        rotated_cell,
        rotated_geometry,
        rotated_contract,
        upstream,
        downstream,
        transverse_momentum=rotated_reservoirs,
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
    expected_lateral = _rotate_vector(
        baseline.lateral_momentum_change_east_m4s,
        baseline.lateral_momentum_change_north_m4s,
        rotation,
    )
    expected_friction = _rotate_vector(
        baseline.friction_momentum_change_east_m4s,
        baseline.friction_momentum_change_north_m4s,
        rotation,
    )
    assert (
        rotated.lateral_momentum_change_east_m4s,
        rotated.lateral_momentum_change_north_m4s,
    ) == pytest.approx(expected_lateral, abs=1e-12)
    assert (
        rotated.friction_momentum_change_east_m4s,
        rotated.friction_momentum_change_north_m4s,
    ) == pytest.approx(expected_friction, abs=1e-12)


def test_source_split_multistep_states_remain_positive_and_close_ledgers():
    geometry = _geometry()
    contract = _contract()
    upstream, downstream, upstream_external, downstream_external = _network()
    cell = ShallowWaterJunctionCellState(190.0, 0.0, 0.0)
    reservoirs = zero_terminal_transverse_momentum(contract)
    maximum_mass_error = 0.0
    maximum_momentum_error = 0.0
    minimum_area = 20.0

    for _ in range(20):
        network = (
            upstream,
            downstream,
            upstream_external,
            downstream_external,
        )
        _, result = _advance(
            cell,
            geometry,
            contract,
            network,
            reservoirs,
            convention="matched_local_velocity",
        )
        upstream = tuple(
            replace(reach, state=state)
            for reach, state in zip(
                upstream, result.upstream_states, strict=True
            )
        )
        downstream = replace(downstream, state=result.downstream_state)
        cell = result.conservative_core_step.junction_cell_step.state_after
        reservoirs = result.transverse_momentum_after
        maximum_mass_error = max(
            maximum_mass_error, abs(result.total_volume_ledger_error_m3)
        )
        maximum_momentum_error = max(
            maximum_momentum_error,
            result.geographic_momentum_ledger_error_magnitude_m4s,
        )
        minimum_area = min(minimum_area, result.minimum_reach_area_m2)

    assert minimum_area > 0.0
    assert cell.volume_m3 > 0.0
    assert maximum_mass_error <= 1e-8
    assert maximum_momentum_error <= 1e-9
    assert max(value.magnitude_m4s for value in reservoirs) > 1e-6


def test_source_split_rejects_cfl_and_implicit_lateral_momentum_semantics():
    geometry = _geometry()
    contract = _contract()
    network = _network()
    cell = ShallowWaterJunctionCellState(200.0, 0.0, 0.0)
    reservoirs = zero_terminal_transverse_momentum(contract)
    upstream, downstream, upstream_external, downstream_external = network
    stable = maximum_source_split_coupled_junction_timestep_seconds(
        cell,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        transverse_momentum=reservoirs,
        lateral_momentum_convention="zero_longitudinal_momentum",
        courant_number=COURANT_NUMBER,
    )
    with pytest.raises(
        ValueError, match="source_split_coupled_junction_cfl_exceeded"
    ):
        advance_source_split_coupled_junction_reaches(
            cell,
            geometry,
            contract,
            upstream,
            downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=downstream_external,
            transverse_momentum=reservoirs,
            lateral_momentum_convention="zero_longitudinal_momentum",
            timestep_seconds=stable * 1.01,
            maximum_courant_number=COURANT_NUMBER,
        )
    with pytest.raises(
        ValueError,
        match="source_split_coupled_junction_lateral_momentum_invalid",
    ):
        maximum_source_split_coupled_junction_timestep_seconds(
            cell,
            geometry,
            contract,
            upstream,
            downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=downstream_external,
            transverse_momentum=reservoirs,
            lateral_momentum_convention="implicit",
            courant_number=COURANT_NUMBER,
        )


def test_compiled_stage16_protocol_passes_without_admission():
    from scripts import (
        compile_geotransport_stage16_source_split_junction_gates,
    )

    report = (
        compile_geotransport_stage16_source_split_junction_gates.compile_report()
    )

    assert report["all_gates_passed"] is True
    assert report["claim_boundary"][
        "source_split_junction_reach_coupling_implemented"
    ] is True
    assert report["claim_boundary"][
        "stage15_opening_exchange_preserved"
    ] is True
    assert report["claim_boundary"][
        "junction_cell_friction_implemented"
    ] is False
    assert report["claim_boundary"]["candidate_operator_admitted"] is False
