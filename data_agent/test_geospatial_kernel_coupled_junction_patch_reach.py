from __future__ import annotations

from dataclasses import replace
import math

import pytest

from data_agent.uwm.geospatial_kernel_v2.conservative_vector_junction import (
    ConservativeVectorJunctionContract,
)
from data_agent.uwm.geospatial_kernel_v2.coupled_junction_patch_reach import (
    advance_coupled_junction_patch_reaches,
    maximum_coupled_junction_patch_reach_timestep_seconds,
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
from data_agent.uwm.geospatial_kernel_v2.shallow_water_junction_patch import (
    JunctionPatchCellGeometry,
    JunctionPatchCellState,
    JunctionPatchFace,
    JunctionPatchVertex,
    ShallowWaterJunctionPatchGeometry,
    ShallowWaterJunctionPatchState,
)


COURANT_NUMBER = 0.4


def _rotate_vector(east, north, angle_degrees):
    angle = math.radians(angle_degrees)
    return (
        east * math.cos(angle) + north * math.sin(angle),
        north * math.cos(angle) - east * math.sin(angle),
    )


def _geometry(*, rotation_degrees: float = 0.0):
    coordinates = {
        "v00": (0.0, 0.0),
        "v10": (10.0, 0.0),
        "v20": (20.0, 0.0),
        "v01": (0.0, 10.0),
        "v11": (10.0, 10.0),
        "v21": (20.0, 10.0),
        "v02": (0.0, 20.0),
        "v12": (10.0, 20.0),
        "v22": (20.0, 20.0),
    }
    vertices = tuple(
        JunctionPatchVertex(vertex_id, *_rotate_vector(*point, rotation_degrees))
        for vertex_id, point in coordinates.items()
    )
    return ShallowWaterJunctionPatchGeometry(
        "junction-grid",
        0.0,
        vertices,
        (
            JunctionPatchCellGeometry("sw", ("v00", "v10", "v11", "v01")),
            JunctionPatchCellGeometry("se", ("v10", "v20", "v21", "v11")),
            JunctionPatchCellGeometry("nw", ("v01", "v11", "v12", "v02")),
            JunctionPatchCellGeometry("ne", ("v11", "v21", "v22", "v12")),
        ),
        (
            JunctionPatchFace(
                "opening-up-a", "nw", "v02", "v01", "branch_opening",
                branch_id="up-a", branch_role="upstream"
            ),
            JunctionPatchFace(
                "opening-up-b", "sw", "v00", "v10", "branch_opening",
                branch_id="up-b", branch_role="upstream"
            ),
            JunctionPatchFace(
                "opening-down", "se", "v20", "v21", "branch_opening",
                branch_id="down", branch_role="downstream"
            ),
            JunctionPatchFace(
                "internal-sw-se", "sw", "v10", "v11", "internal",
                right_cell_id="se"
            ),
            JunctionPatchFace(
                "internal-sw-nw", "sw", "v11", "v01", "internal",
                right_cell_id="nw"
            ),
            JunctionPatchFace(
                "internal-se-ne", "se", "v21", "v11", "internal",
                right_cell_id="ne"
            ),
            JunctionPatchFace(
                "internal-nw-ne", "nw", "v11", "v12", "internal",
                right_cell_id="ne"
            ),
            JunctionPatchFace("wall-sw-west", "sw", "v01", "v00", "solid_wall"),
            JunctionPatchFace("wall-se-south", "se", "v10", "v20", "solid_wall"),
            JunctionPatchFace("wall-ne-east", "ne", "v21", "v22", "solid_wall"),
            JunctionPatchFace("wall-ne-north", "ne", "v22", "v12", "solid_wall"),
            JunctionPatchFace("wall-nw-north", "nw", "v12", "v02", "solid_wall"),
        ),
        "manufactured:stage18-coupled-four-cell-grid",
    )


def _contract(*, rotation_degrees: float = 0.0):
    return ConservativeVectorJunctionContract(
        "junction-grid",
        ("up-a", "up-b"),
        "down",
        (
            (90.0 + rotation_degrees) % 360.0,
            rotation_degrees % 360.0,
        ),
        (90.0 + rotation_degrees) % 360.0,
        "manufactured:stage18",
    )


def _state(*, lake: bool = False, rotation_degrees: float = 0.0):
    values = (
        ("sw", 200.0, 7.0, 3.0),
        ("se", 200.0, 5.0, -4.0),
        ("nw", 190.0, 6.0, 8.0),
        ("ne", 210.0, -2.0, -3.0),
    )
    if lake:
        values = tuple((cell_id, 200.0, 0.0, 0.0) for cell_id, *_ in values)
    return ShallowWaterJunctionPatchState(
        tuple(
            JunctionPatchCellState(
                cell_id,
                volume,
                *_rotate_vector(east, north, rotation_degrees),
            )
            for cell_id, volume, east, north in values
        )
    )


def _reach(branch_id: str, discharge_m3s: float):
    section = TrapezoidalChannelSection(10.0, 0.0)
    area = section.area_m2(2.0)
    return DynamicWaveNetworkReach(
        branch_id,
        PrismaticDynamicWaveState((area,) * 4, (discharge_m3s,) * 4),
        (0.0,) * 4,
        (section,) * 4,
        100.0,
        (0.035,) * 4,
        (0.0,) * 4,
    )


def _network(*, discharges=(5.0, 7.0, 12.0)):
    upstream = (
        _reach("up-a", discharges[0]),
        _reach("up-b", discharges[1]),
    )
    downstream = _reach("down", discharges[2])
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
    upstream,
    downstream,
    upstream_external,
    downstream_external,
    *,
    timestep_fraction=0.5,
):
    stable = maximum_coupled_junction_patch_reach_timestep_seconds(
        state,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        courant_number=COURANT_NUMBER,
    )
    result = advance_coupled_junction_patch_reaches(
        state,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        timestep_seconds=timestep_fraction * stable,
        maximum_courant_number=COURANT_NUMBER,
    )
    return stable, result


def test_patch_reach_exchange_closes_mass_momentum_and_transition_reaction():
    geometry = _geometry()
    contract = _contract()
    state = _state()
    upstream, downstream, upstream_external, downstream_external = _network()

    stable, result = _advance(
        state,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external,
        downstream_external,
    )
    report = result.as_dict()

    assert stable > 0.0
    assert abs(result.total_volume_ledger_error_m3) <= 1e-9
    assert result.geographic_momentum_ledger_error_magnitude_m4s <= 1e-10
    assert result.maximum_opening_mass_cancellation_error_m3 == 0.0
    assert result.maximum_opening_momentum_closure_error_m4s <= 1e-13
    assert any(
        value.transverse_momentum_flux_magnitude_m4s2 > 1e-6
        for value in result.opening_exchanges
    )
    assert result.junction_patch_step.state_after != state
    assert result.upstream_states != tuple(value.state for value in upstream)
    assert result.downstream_state != downstream.state
    for reach_step, exchange in zip(
        result.upstream_reach_steps, result.opening_exchanges[:2], strict=True
    ):
        assert reach_step.right_boundary_area_flux_m3s == pytest.approx(
            -exchange.outward_mass_flux_m3s
        )
    assert result.downstream_reach_step.left_boundary_area_flux_m3s == (
        pytest.approx(result.opening_exchanges[-1].outward_mass_flux_m3s)
    )
    assert report["transverse_closure"] == (
        "instantaneous_transition_wall_reaction"
    )
    assert report["persistent_transverse_momentum_reservoir"] is False
    assert report["operator_admitted"] is False


def test_coupled_patch_lake_at_rest_preserves_patch_and_reaches():
    geometry = _geometry()
    contract = _contract()
    state = _state(lake=True)
    upstream, downstream, upstream_external, downstream_external = _network(
        discharges=(0.0, 0.0, 0.0)
    )

    _, result = _advance(
        state,
        geometry,
        contract,
        upstream,
        downstream,
        upstream_external,
        downstream_external,
        timestep_fraction=1.0,
    )

    assert result.junction_patch_step.state_after.cells == pytest.approx(
        state.cells, abs=1e-12
    )
    for actual, expected in zip(
        (*result.upstream_states, result.downstream_state),
        (*(value.state for value in upstream), downstream.state),
        strict=True,
    ):
        assert actual.area_m2 == pytest.approx(expected.area_m2, abs=1e-12)
        assert actual.discharge_m3s == pytest.approx(
            expected.discharge_m3s, abs=1e-12
        )
    assert max(
        value.transverse_momentum_flux_magnitude_m4s2
        for value in result.opening_exchanges
    ) <= 1e-12
    assert abs(result.total_volume_ledger_error_m3) <= 1e-9
    assert result.geographic_momentum_ledger_error_magnitude_m4s <= 1e-10


def test_coupled_patch_step_is_rotation_covariant():
    rotation = 37.0
    geometry = _geometry()
    rotated_geometry = _geometry(rotation_degrees=rotation)
    contract = _contract()
    rotated_contract = _contract(rotation_degrees=rotation)
    state = _state()
    rotated_state = _state(rotation_degrees=rotation)
    upstream, downstream, upstream_external, downstream_external = _network()

    baseline_stable = maximum_coupled_junction_patch_reach_timestep_seconds(
        state, geometry, contract, upstream, downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        courant_number=COURANT_NUMBER,
    )
    rotated_stable = maximum_coupled_junction_patch_reach_timestep_seconds(
        rotated_state, rotated_geometry, rotated_contract, upstream, downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        courant_number=COURANT_NUMBER,
    )
    timestep = 0.5 * min(baseline_stable, rotated_stable)
    baseline = advance_coupled_junction_patch_reaches(
        state, geometry, contract, upstream, downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        timestep_seconds=timestep,
        maximum_courant_number=COURANT_NUMBER,
    )
    rotated = advance_coupled_junction_patch_reaches(
        rotated_state, rotated_geometry, rotated_contract, upstream, downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
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
    for actual, expected in zip(
        rotated.junction_patch_step.state_after.cells,
        baseline.junction_patch_step.state_after.cells,
        strict=True,
    ):
        vector = _rotate_vector(
            expected.momentum_east_m4s,
            expected.momentum_north_m4s,
            rotation,
        )
        assert actual.volume_m3 == pytest.approx(expected.volume_m3, abs=1e-12)
        assert (
            actual.momentum_east_m4s,
            actual.momentum_north_m4s,
        ) == pytest.approx(vector, abs=1e-12)
    for actual, expected in zip(
        rotated.opening_exchanges, baseline.opening_exchanges, strict=True
    ):
        vector = _rotate_vector(
            expected.transition_wall_fluid_impulse_east_m4s,
            expected.transition_wall_fluid_impulse_north_m4s,
            rotation,
        )
        assert (
            actual.transition_wall_fluid_impulse_east_m4s,
            actual.transition_wall_fluid_impulse_north_m4s,
        ) == pytest.approx(vector, abs=1e-12)


def test_multistep_coupling_has_no_persistent_transverse_state():
    geometry = _geometry()
    contract = _contract()
    state = _state()
    upstream, downstream, upstream_external, downstream_external = _network()
    maximum_mass_error = 0.0
    maximum_momentum_error = 0.0
    maximum_transition_reaction = 0.0
    minimum_area = 20.0
    minimum_volume = min(value.volume_m3 for value in state.cells)

    for _ in range(25):
        _, result = _advance(
            state,
            geometry,
            contract,
            upstream,
            downstream,
            upstream_external,
            downstream_external,
        )
        upstream = tuple(
            replace(reach, state=next_state)
            for reach, next_state in zip(
                upstream, result.upstream_states, strict=True
            )
        )
        downstream = replace(downstream, state=result.downstream_state)
        state = result.junction_patch_step.state_after
        maximum_mass_error = max(
            maximum_mass_error, abs(result.total_volume_ledger_error_m3)
        )
        maximum_momentum_error = max(
            maximum_momentum_error,
            result.geographic_momentum_ledger_error_magnitude_m4s,
        )
        maximum_transition_reaction = max(
            maximum_transition_reaction,
            max(
                value.transverse_momentum_flux_magnitude_m4s2
                for value in result.opening_exchanges
            ),
        )
        minimum_area = min(minimum_area, result.minimum_reach_area_m2)
        minimum_volume = min(
            minimum_volume, result.junction_patch_step.minimum_cell_volume_m3
        )
        assert "transverse_momentum_after" not in result.as_dict()

    assert minimum_area > 0.0
    assert minimum_volume > 0.0
    assert maximum_mass_error <= 1e-8
    assert maximum_momentum_error <= 1e-9
    assert maximum_transition_reaction > 1e-6


def test_patch_reach_coupling_rejects_contract_and_cfl_violations():
    geometry = _geometry()
    contract = _contract()
    state = _state()
    upstream, downstream, upstream_external, downstream_external = _network()
    stable = maximum_coupled_junction_patch_reach_timestep_seconds(
        state, geometry, contract, upstream, downstream,
        upstream_external_boundaries=upstream_external,
        downstream_external_boundary=downstream_external,
        courant_number=COURANT_NUMBER,
    )
    with pytest.raises(
        ValueError, match="coupled_junction_patch_reach_cfl_exceeded"
    ):
        advance_coupled_junction_patch_reaches(
            state, geometry, contract, upstream, downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=downstream_external,
            timestep_seconds=stable * 1.01,
            maximum_courant_number=COURANT_NUMBER,
        )
    with pytest.raises(
        ValueError, match="coupled_junction_patch_reach_branch_binding_mismatch"
    ):
        maximum_coupled_junction_patch_reach_timestep_seconds(
            state,
            geometry,
            contract,
            (replace(upstream[0], reach_id="wrong"), upstream[1]),
            downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=downstream_external,
            courant_number=COURANT_NUMBER,
        )
    invalid_section = TrapezoidalChannelSection(9.0, 0.0)
    with pytest.raises(
        ValueError,
        match=(
            "coupled_junction_patch_reach_uniform_rectangular_flat_contract_required"
        ),
    ):
        maximum_coupled_junction_patch_reach_timestep_seconds(
            state,
            geometry,
            contract,
            (replace(upstream[0], sections=(invalid_section,) * 4), upstream[1]),
            downstream,
            upstream_external_boundaries=upstream_external,
            downstream_external_boundary=downstream_external,
            courant_number=COURANT_NUMBER,
        )


def test_compiled_stage18_protocol_passes_without_admission():
    from scripts import compile_geotransport_stage18_coupled_patch_reach_gates

    report = (
        compile_geotransport_stage18_coupled_patch_reach_gates.compile_report()
    )

    assert report["all_gates_passed"] is True
    assert report["claim_boundary"][
        "synchronous_multi_cell_patch_reach_coupling_implemented"
    ] is True
    assert report["claim_boundary"][
        "persistent_transverse_momentum_reservoir"
    ] is False
    assert report["claim_boundary"]["candidate_operator_admitted"] is False
