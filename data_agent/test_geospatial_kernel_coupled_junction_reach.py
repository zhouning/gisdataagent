from __future__ import annotations

from dataclasses import replace
import math

import pytest

from data_agent.uwm.geospatial_kernel_v2.conservative_vector_junction import (
    ConservativeVectorJunctionContract,
)
from data_agent.uwm.geospatial_kernel_v2.coupled_junction_reach import (
    ReachTerminalTransverseMomentum,
    advance_coupled_junction_reaches,
    maximum_coupled_junction_reach_timestep_seconds,
    zero_terminal_transverse_momentum,
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
                "opening-a",
                "branch_opening",
                width,
                azimuth(225.0),
                "up-a",
                "upstream",
            ),
            JunctionCellBoundaryFace(
                "opening-b",
                "branch_opening",
                width,
                azimuth(135.0),
                "up-b",
                "upstream",
            ),
            JunctionCellBoundaryFace(
                "opening-down",
                "branch_opening",
                width,
                azimuth(0.0),
                "down",
                "downstream",
            ),
            JunctionCellBoundaryFace(
                "wall-north",
                "solid_wall",
                width * (math.sqrt(2.0) - 1.0),
                azimuth(0.0),
            ),
            JunctionCellBoundaryFace(
                "wall-east", "solid_wall", 15.0, azimuth(90.0)
            ),
            JunctionCellBoundaryFace(
                "wall-west", "solid_wall", 15.0, azimuth(270.0)
            ),
        ),
        "manufactured:stage15-closed-y-cell",
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
        "manufactured:stage15",
    )


def _reach(branch_id: str, discharge_m3s: float):
    section = TrapezoidalChannelSection(10.0, 0.0)
    area = section.area_m2(2.0)
    return DynamicWaveNetworkReach(
        branch_id,
        PrismaticDynamicWaveState(
            (area,) * 4, (discharge_m3s,) * 4
        ),
        (0.0,) * 4,
        (section,) * 4,
        100.0,
        (0.035,) * 4,
        (0.0,) * 4,
    )


def _network(*, discharges: tuple[float, float, float] = (5.0, 7.0, 12.0)):
    upstream = (
        _reach("up-a", discharges[0]),
        _reach("up-b", discharges[1]),
    )
    downstream = _reach("down", discharges[2])
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
    state: ShallowWaterJunctionCellState,
    geometry: ShallowWaterJunctionCellGeometry,
    contract: ConservativeVectorJunctionContract,
    upstream: tuple[DynamicWaveNetworkReach, ...],
    downstream: DynamicWaveNetworkReach,
    upstream_external: tuple[FixedDynamicWaveBoundary, ...],
    downstream_external: FixedDynamicWaveBoundary,
    reservoirs: tuple[ReachTerminalTransverseMomentum, ...],
    *,
    timestep_fraction: float = 0.5,
):
    stable = maximum_coupled_junction_reach_timestep_seconds(
        state,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        transverse_momentum=reservoirs,
        courant_number=COURANT_NUMBER,
    )
    result = advance_coupled_junction_reaches(
        state,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        transverse_momentum=reservoirs,
        timestep_seconds=timestep_fraction * stable,
        maximum_courant_number=COURANT_NUMBER,
    )
    return stable, result


def _rotate_vector(
    east: float, north: float, angle_degrees: float
) -> tuple[float, float]:
    angle = math.radians(angle_degrees)
    return (
        east * math.cos(angle) + north * math.sin(angle),
        north * math.cos(angle) - east * math.sin(angle),
    )


def test_synchronous_opening_flux_closes_whole_system_ledgers():
    geometry = _geometry()
    contract = _contract()
    upstream, downstream, upstream_external, downstream_external = _network()
    state = ShallowWaterJunctionCellState(200.0, 12.0, -4.0)
    reservoirs = zero_terminal_transverse_momentum(contract)

    stable, result = _advance(
        state,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external,
        downstream_external,
        reservoirs,
    )
    report = result.as_dict()

    assert stable > 0.0
    assert result.total_volume_ledger_error_m3 == pytest.approx(
        0.0, abs=1e-9
    )
    assert result.geographic_momentum_ledger_error_magnitude_m4s <= 1e-10
    assert result.maximum_opening_mass_cancellation_error_m3 == 0.0
    assert result.maximum_opening_momentum_cancellation_error_m4s <= 1e-13
    assert result.junction_cell_step.state_after != state
    assert result.upstream_states != tuple(value.state for value in upstream)
    assert result.downstream_state != downstream.state
    for reach_step, exchange in zip(
        result.upstream_reach_steps,
        result.opening_exchanges[:2],
        strict=True,
    ):
        assert reach_step.right_boundary_area_flux_m3s == pytest.approx(
            -exchange.outward_mass_flux_m3s
        )
    assert result.downstream_reach_step.left_boundary_area_flux_m3s == (
        pytest.approx(result.opening_exchanges[-1].outward_mass_flux_m3s)
    )
    assert report["complete_vector_opening_flux_retained"] is True
    assert report["transverse_reservoir_feedback_to_flux"] is False
    assert report["operator_admitted"] is False


def test_coupled_lake_at_rest_is_identity_for_cell_reaches_and_reservoirs():
    geometry = _geometry()
    contract = _contract()
    upstream, downstream, upstream_external, downstream_external = _network(
        discharges=(0.0, 0.0, 0.0)
    )
    state = ShallowWaterJunctionCellState(200.0, 0.0, 0.0)
    reservoirs = zero_terminal_transverse_momentum(contract)

    _, result = _advance(
        state,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external,
        downstream_external,
        reservoirs,
        timestep_fraction=1.0,
    )

    assert result.upstream_states == pytest.approx(
        tuple(value.state for value in upstream), abs=1e-12
    )
    assert result.downstream_state.area_m2 == pytest.approx(
        downstream.state.area_m2, abs=1e-12
    )
    assert result.downstream_state.discharge_m3s == pytest.approx(
        downstream.state.discharge_m3s, abs=1e-12
    )
    assert result.junction_cell_step.state_after.volume_m3 == pytest.approx(
        state.volume_m3, abs=1e-12
    )
    assert result.junction_cell_step.state_after.momentum_east_m4s == (
        pytest.approx(0.0, abs=1e-12)
    )
    assert result.junction_cell_step.state_after.momentum_north_m4s == (
        pytest.approx(0.0, abs=1e-12)
    )
    assert max(
        value.magnitude_m4s for value in result.transverse_momentum_after
    ) <= 1e-12
    assert abs(result.total_volume_ledger_error_m3) <= 1e-9
    assert result.geographic_momentum_ledger_error_magnitude_m4s <= 1e-10


def test_coupled_step_is_rotation_covariant_without_changing_scalar_reaches():
    rotation = 37.0
    geometry = _geometry()
    rotated_geometry = _geometry(rotation_degrees=rotation)
    contract = _contract()
    rotated_contract = _contract(rotation_degrees=rotation)
    upstream, downstream, upstream_external, downstream_external = _network()
    state = ShallowWaterJunctionCellState(200.0, 12.0, -4.0)
    rotated_momentum = _rotate_vector(12.0, -4.0, rotation)
    rotated_state = ShallowWaterJunctionCellState(
        200.0, *rotated_momentum
    )
    reservoirs = zero_terminal_transverse_momentum(contract)
    rotated_reservoirs = zero_terminal_transverse_momentum(rotated_contract)
    baseline_stable = maximum_coupled_junction_reach_timestep_seconds(
        state,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        transverse_momentum=reservoirs,
        courant_number=COURANT_NUMBER,
    )
    rotated_stable = maximum_coupled_junction_reach_timestep_seconds(
        rotated_state,
        rotated_geometry,
        rotated_contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        transverse_momentum=rotated_reservoirs,
        courant_number=COURANT_NUMBER,
    )
    timestep = 0.5 * min(baseline_stable, rotated_stable)

    baseline = advance_coupled_junction_reaches(
        state,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        transverse_momentum=reservoirs,
        timestep_seconds=timestep,
        maximum_courant_number=COURANT_NUMBER,
    )
    rotated = advance_coupled_junction_reaches(
        rotated_state,
        rotated_geometry,
        rotated_contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        transverse_momentum=rotated_reservoirs,
        timestep_seconds=timestep,
        maximum_courant_number=COURANT_NUMBER,
    )

    assert rotated_stable == pytest.approx(baseline_stable, abs=1e-12)
    for actual, expected in zip(
        (*rotated.upstream_states, rotated.downstream_state),
        (*baseline.upstream_states, baseline.downstream_state),
        strict=True,
    ):
        assert actual.area_m2 == pytest.approx(expected.area_m2, abs=1e-12)
        assert actual.discharge_m3s == pytest.approx(
            expected.discharge_m3s, abs=1e-12
        )
    expected_cell = _rotate_vector(
        baseline.junction_cell_step.state_after.momentum_east_m4s,
        baseline.junction_cell_step.state_after.momentum_north_m4s,
        rotation,
    )
    assert (
        rotated.junction_cell_step.state_after.momentum_east_m4s,
        rotated.junction_cell_step.state_after.momentum_north_m4s,
    ) == pytest.approx(expected_cell, abs=1e-12)
    for actual, expected in zip(
        rotated.transverse_momentum_after,
        baseline.transverse_momentum_after,
        strict=True,
    ):
        expected_vector = _rotate_vector(
            expected.momentum_east_m4s,
            expected.momentum_north_m4s,
            rotation,
        )
        assert (
            actual.momentum_east_m4s,
            actual.momentum_north_m4s,
        ) == pytest.approx(expected_vector, abs=1e-12)


def test_multistep_asymmetric_evolution_retains_transverse_momentum():
    geometry = _geometry()
    contract = _contract()
    upstream, downstream, upstream_external, downstream_external = _network()
    cell_state = ShallowWaterJunctionCellState(190.0, 0.0, 0.0)
    reservoirs = zero_terminal_transverse_momentum(contract)
    maximum_mass_error = 0.0
    maximum_momentum_error = 0.0
    minimum_area = min(
        min(value.state.area_m2) for value in (*upstream, downstream)
    )
    minimum_volume = cell_state.volume_m3

    for _ in range(25):
        _, result = _advance(
            cell_state,
            geometry,
            contract,
            upstream,
            downstream,
            upstream_external,
            downstream_external,
            reservoirs,
        )
        upstream = tuple(
            replace(reach, state=state)
            for reach, state in zip(
                upstream, result.upstream_states, strict=True
            )
        )
        downstream = replace(downstream, state=result.downstream_state)
        cell_state = result.junction_cell_step.state_after
        reservoirs = result.transverse_momentum_after
        maximum_mass_error = max(
            maximum_mass_error, abs(result.total_volume_ledger_error_m3)
        )
        maximum_momentum_error = max(
            maximum_momentum_error,
            result.geographic_momentum_ledger_error_magnitude_m4s,
        )
        minimum_area = min(minimum_area, result.minimum_reach_area_m2)
        minimum_volume = min(minimum_volume, cell_state.volume_m3)

    assert minimum_area > 0.0
    assert minimum_volume > 0.0
    assert maximum_mass_error <= 1e-8
    assert maximum_momentum_error <= 1e-9
    assert max(value.magnitude_m4s for value in reservoirs) > 1e-6


def test_coupling_rejects_cfl_branch_geometry_and_reservoir_violations():
    geometry = _geometry()
    contract = _contract()
    upstream, downstream, upstream_external, downstream_external = _network()
    state = ShallowWaterJunctionCellState(200.0, 0.0, 0.0)
    reservoirs = zero_terminal_transverse_momentum(contract)
    stable = maximum_coupled_junction_reach_timestep_seconds(
        state,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        transverse_momentum=reservoirs,
        courant_number=COURANT_NUMBER,
    )
    with pytest.raises(
        ValueError, match="coupled_junction_reach_cfl_exceeded"
    ):
        advance_coupled_junction_reaches(
            state,
            geometry,
            contract,
            upstream,
            downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=downstream_external,
            transverse_momentum=reservoirs,
            timestep_seconds=stable * 1.01,
            maximum_courant_number=COURANT_NUMBER,
        )

    with pytest.raises(
        ValueError, match="coupled_junction_reach_branch_binding_mismatch"
    ):
        maximum_coupled_junction_reach_timestep_seconds(
            state,
            geometry,
            contract,
            (replace(upstream[0], reach_id="wrong"), upstream[1]),
            downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=downstream_external,
            transverse_momentum=reservoirs,
            courant_number=COURANT_NUMBER,
        )

    invalid_section = TrapezoidalChannelSection(9.0, 0.0)
    with pytest.raises(
        ValueError,
        match=(
            "coupled_junction_reach_uniform_rectangular_flat_contract_required"
        ),
    ):
        maximum_coupled_junction_reach_timestep_seconds(
            state,
            geometry,
            contract,
            (replace(upstream[0], sections=(invalid_section,) * 4), upstream[1]),
            downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=downstream_external,
            transverse_momentum=reservoirs,
            courant_number=COURANT_NUMBER,
        )

    invalid_reservoirs = (
        ReachTerminalTransverseMomentum("up-a", 1.0, 1.0),
        *reservoirs[1:],
    )
    with pytest.raises(
        ValueError,
        match="coupled_junction_reach_transverse_reservoir_not_perpendicular",
    ):
        maximum_coupled_junction_reach_timestep_seconds(
            state,
            geometry,
            contract,
            upstream,
            downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=downstream_external,
            transverse_momentum=invalid_reservoirs,
            courant_number=COURANT_NUMBER,
        )


def test_compiled_stage15_protocol_passes_without_admission():
    from scripts import compile_geotransport_stage15_coupled_junction_gates

    report = (
        compile_geotransport_stage15_coupled_junction_gates.compile_report()
    )

    assert report["all_gates_passed"] is True
    assert report["claim_boundary"][
        "synchronous_junction_reach_coupling_implemented"
    ] is True
    assert report["claim_boundary"][
        "complete_opening_vector_flux_retained"
    ] is True
    assert report["claim_boundary"][
        "friction_and_lateral_source_splitting_implemented"
    ] is False
    assert report["claim_boundary"]["candidate_operator_admitted"] is False
