from __future__ import annotations

from dataclasses import replace
import math

import pytest

from data_agent.uwm.geospatial_kernel_v2.conservative_vector_junction import (
    ConservativeVectorJunctionContract,
    solve_conservative_vector_junction,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_flux import (
    DynamicWaveCellState,
    TrapezoidalChannelSection,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_junction import (
    DynamicWaveJunctionTerminal,
)
from data_agent.uwm.geospatial_kernel_v2.shallow_water_junction_patch import (
    JunctionPatchCellGeometry,
    JunctionPatchCellState,
    JunctionPatchFace,
    JunctionPatchVertex,
    ShallowWaterJunctionPatchGeometry,
    ShallowWaterJunctionPatchState,
    advance_shallow_water_junction_patch,
    maximum_shallow_water_junction_patch_timestep_seconds,
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
                "opening-up-a", "nw", "v02", "v01",
                "branch_opening", branch_id="up-a", branch_role="upstream"
            ),
            JunctionPatchFace(
                "opening-up-b", "sw", "v00", "v10",
                "branch_opening", branch_id="up-b", branch_role="upstream"
            ),
            JunctionPatchFace(
                "opening-down", "se", "v20", "v21",
                "branch_opening", branch_id="down", branch_role="downstream"
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
        "manufactured:stage17-conforming-four-cell-grid",
    )


def _terminal(branch_id, discharge):
    section = TrapezoidalChannelSection(10.0, 0.0)
    return DynamicWaveJunctionTerminal(
        branch_id,
        DynamicWaveCellState(section.area_m2(2.0), discharge),
        section,
        0.0,
    )


def _junction(
    *,
    discharges=(5.0, 7.0, 12.0),
    rotation_degrees: float = 0.0,
):
    upstream = (
        _terminal("up-a", discharges[0]),
        _terminal("up-b", discharges[1]),
    )
    downstream = _terminal("down", discharges[2])
    contract = ConservativeVectorJunctionContract(
        "junction-grid",
        ("up-a", "up-b"),
        "down",
        (
            (90.0 + rotation_degrees) % 360.0,
            rotation_degrees % 360.0,
        ),
        (90.0 + rotation_degrees) % 360.0,
        "manufactured:stage17",
    )
    return (
        upstream,
        downstream,
        solve_conservative_vector_junction(upstream, downstream, contract),
    )


def _state(*, lake: bool = False, rotation_degrees: float = 0.0):
    values = (
        ("sw", 200.0, 0.0, 0.0),
        ("se", 200.0, 5.0, 0.0),
        ("nw", 190.0, 0.0, 0.0),
        ("ne", 210.0, 0.0, -3.0),
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


def test_patch_geometry_verifies_conforming_polygon_edge_topology():
    geometry = _geometry()
    report = geometry.as_dict()

    assert geometry.cell_areas_m2 == pytest.approx(
        {"sw": 100.0, "se": 100.0, "nw": 100.0, "ne": 100.0}
    )
    assert geometry.total_plan_area_m2 == 400.0
    assert geometry.external_closure_east_north_m == pytest.approx(
        (0.0, 0.0), abs=1e-12
    )
    assert geometry.upstream_branch_ids == ("up-a", "up-b")
    assert geometry.downstream_branch_id == "down"
    assert report["conforming_internal_edge_pairs_verified"] is True
    assert report["complete_cell_edge_coverage_verified"] is True
    assert report["connected_cell_graph_verified"] is True


def test_patch_internal_hll_flux_closes_cell_and_global_ledgers():
    geometry = _geometry()
    state = _state()
    upstream, downstream, junction = _junction()
    stable = maximum_shallow_water_junction_patch_timestep_seconds(
        state,
        geometry,
        upstream,
        downstream,
        junction,
        courant_number=COURANT_NUMBER,
    )

    result = advance_shallow_water_junction_patch(
        state,
        geometry,
        upstream,
        downstream,
        junction,
        timestep_seconds=0.5 * stable,
        maximum_courant_number=COURANT_NUMBER,
    )
    internal = tuple(
        value for value in result.face_fluxes
        if value.boundary_type == "internal"
    )

    assert len(internal) == 4
    assert any(abs(value.outward_mass_flux_m3s) > 1e-6 for value in internal)
    assert result.state_after != state
    assert abs(result.mass_ledger_error_m3) <= 1e-12
    assert result.momentum_ledger_error_magnitude_m4s <= 1e-12
    assert result.maximum_internal_mass_cancellation_error_m3 == 0.0
    assert result.maximum_internal_momentum_cancellation_error_m4s == 0.0
    assert result.maximum_cell_mass_ledger_error_m3 <= 1e-13
    assert result.maximum_cell_momentum_ledger_error_m4s <= 1e-13
    assert result.minimum_cell_volume_m3 > 0.0


def test_patch_lake_at_rest_preserves_every_cell():
    geometry = _geometry()
    state = _state(lake=True)
    upstream, downstream, junction = _junction(discharges=(0.0, 0.0, 0.0))
    stable = maximum_shallow_water_junction_patch_timestep_seconds(
        state,
        geometry,
        upstream,
        downstream,
        junction,
        courant_number=COURANT_NUMBER,
    )

    result = advance_shallow_water_junction_patch(
        state,
        geometry,
        upstream,
        downstream,
        junction,
        timestep_seconds=stable,
        maximum_courant_number=COURANT_NUMBER,
    )

    for actual, expected in zip(
        result.state_after.cells, state.cells, strict=True
    ):
        assert actual.volume_m3 == pytest.approx(expected.volume_m3, abs=1e-12)
        assert actual.momentum_east_m4s == pytest.approx(0.0, abs=1e-12)
        assert actual.momentum_north_m4s == pytest.approx(0.0, abs=1e-12)
    assert abs(result.mass_ledger_error_m3) <= 1e-12
    assert result.momentum_ledger_error_magnitude_m4s <= 1e-12


def test_patch_state_and_fluxes_are_rotation_covariant():
    rotation = 37.0
    geometry = _geometry()
    rotated_geometry = _geometry(rotation_degrees=rotation)
    state = _state()
    rotated_state = _state(rotation_degrees=rotation)
    upstream, downstream, junction = _junction()
    rotated_upstream, rotated_downstream, rotated_junction = _junction(
        rotation_degrees=rotation
    )
    stable = maximum_shallow_water_junction_patch_timestep_seconds(
        state, geometry, upstream, downstream, junction,
        courant_number=COURANT_NUMBER
    )
    rotated_stable = maximum_shallow_water_junction_patch_timestep_seconds(
        rotated_state,
        rotated_geometry,
        rotated_upstream,
        rotated_downstream,
        rotated_junction,
        courant_number=COURANT_NUMBER,
    )
    timestep = 0.5 * min(stable, rotated_stable)
    baseline = advance_shallow_water_junction_patch(
        state, geometry, upstream, downstream, junction,
        timestep_seconds=timestep,
        maximum_courant_number=COURANT_NUMBER,
    )
    rotated = advance_shallow_water_junction_patch(
        rotated_state,
        rotated_geometry,
        rotated_upstream,
        rotated_downstream,
        rotated_junction,
        timestep_seconds=timestep,
        maximum_courant_number=COURANT_NUMBER,
    )

    assert rotated_stable == pytest.approx(stable, abs=1e-12)
    for actual, expected in zip(
        rotated.state_after.cells, baseline.state_after.cells, strict=True
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


def test_patch_multistep_internal_state_propagates_and_stays_positive():
    geometry = _geometry()
    state = _state()
    upstream, downstream, junction = _junction()
    initial = state
    first_internal_flux = None
    last_internal_flux = None
    maximum_mass_error = 0.0
    maximum_momentum_error = 0.0

    for _ in range(25):
        stable = maximum_shallow_water_junction_patch_timestep_seconds(
            state,
            geometry,
            upstream,
            downstream,
            junction,
            courant_number=COURANT_NUMBER,
        )
        result = advance_shallow_water_junction_patch(
            state,
            geometry,
            upstream,
            downstream,
            junction,
            timestep_seconds=0.5 * stable,
            maximum_courant_number=COURANT_NUMBER,
        )
        internal_flux = next(
            value.outward_mass_flux_m3s for value in result.face_fluxes
            if value.face_id == "internal-sw-nw"
        )
        if first_internal_flux is None:
            first_internal_flux = internal_flux
        last_internal_flux = internal_flux
        state = result.state_after
        maximum_mass_error = max(
            maximum_mass_error, abs(result.mass_ledger_error_m3)
        )
        maximum_momentum_error = max(
            maximum_momentum_error,
            result.momentum_ledger_error_magnitude_m4s,
        )

    assert state != initial
    assert min(value.volume_m3 for value in state.cells) > 0.0
    assert last_internal_flux != pytest.approx(first_internal_flux, abs=1e-8)
    assert maximum_mass_error <= 1e-11
    assert maximum_momentum_error <= 1e-11


def test_patch_rejects_topology_opening_and_cfl_violations():
    geometry = _geometry()
    state = _state()
    upstream, downstream, junction = _junction()
    internal_index = next(
        index for index, value in enumerate(geometry.faces)
        if value.face_id == "internal-sw-se"
    )
    invalid_faces = list(geometry.faces)
    invalid_faces[internal_index] = replace(
        invalid_faces[internal_index], right_cell_id="ne"
    )
    with pytest.raises(
        ValueError, match="junction_patch_internal_face_pair_mismatch"
    ):
        replace(geometry, faces=tuple(invalid_faces))

    invalid_cells = list(geometry.cells)
    invalid_cells[0] = JunctionPatchCellGeometry(
        "sw", ("v00", "v11", "v10", "v01")
    )
    with pytest.raises(ValueError, match="junction_patch_cell_"):
        replace(geometry, cells=tuple(invalid_cells))

    stable = maximum_shallow_water_junction_patch_timestep_seconds(
        state,
        geometry,
        upstream,
        downstream,
        junction,
        courant_number=COURANT_NUMBER,
    )
    with pytest.raises(ValueError, match="junction_patch_cfl_exceeded"):
        advance_shallow_water_junction_patch(
            state,
            geometry,
            upstream,
            downstream,
            junction,
            timestep_seconds=stable * 1.01,
            maximum_courant_number=COURANT_NUMBER,
        )

    wrong_contract = replace(
        junction.contract,
        downstream_flow_azimuth_degrees=0.0,
    )
    wrong_junction = replace(junction, contract=wrong_contract)
    with pytest.raises(
        ValueError, match="junction_patch_opening_contract_not_supported"
    ):
        maximum_shallow_water_junction_patch_timestep_seconds(
            state,
            geometry,
            upstream,
            downstream,
            wrong_junction,
            courant_number=COURANT_NUMBER,
        )


def test_compiled_stage17_protocol_passes_without_admission():
    from scripts import compile_geotransport_stage17_junction_patch_gates

    report = compile_geotransport_stage17_junction_patch_gates.compile_report()

    assert report["all_gates_passed"] is True
    assert report["claim_boundary"][
        "multi_cell_finite_area_patch_implemented"
    ] is True
    assert report["claim_boundary"][
        "conforming_polygon_edge_topology_verified"
    ] is True
    assert report["claim_boundary"][
        "branch_reach_states_updated_conservatively"
    ] is False
    assert report["claim_boundary"]["candidate_operator_admitted"] is False
