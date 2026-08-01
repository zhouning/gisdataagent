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
from data_agent.uwm.geospatial_kernel_v2.shallow_water_junction_cell import (
    JunctionCellBoundaryFace,
    ShallowWaterJunctionCellGeometry,
    ShallowWaterJunctionCellState,
    advance_shallow_water_junction_cell,
    maximum_shallow_water_junction_cell_timestep_seconds,
)


def _terminal(
    branch_id: str,
    *,
    section: TrapezoidalChannelSection,
    bed: float,
    surface: float,
    discharge: float,
) -> DynamicWaveJunctionTerminal:
    return DynamicWaveJunctionTerminal(
        branch_id,
        DynamicWaveCellState(
            section.area_m2(surface - bed), discharge
        ),
        section,
        bed,
    )


def _geometry(*, rotation_degrees: float = 0.0):
    width = 10.0
    closing_north_length = width * (math.sqrt(2.0) - 1.0)

    def azimuth(value: float) -> float:
        return (value + rotation_degrees) % 360.0

    return ShallowWaterJunctionCellGeometry(
        junction_id="junction-y",
        plan_area_m2=100.0,
        bed_elevation_m=0.0,
        faces=(
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
                closing_north_length,
                azimuth(0.0),
            ),
            JunctionCellBoundaryFace(
                "wall-east",
                "solid_wall",
                15.0,
                azimuth(90.0),
            ),
            JunctionCellBoundaryFace(
                "wall-west",
                "solid_wall",
                15.0,
                azimuth(270.0),
            ),
        ),
        provenance_id="manufactured:closed-y-cell",
    )


def _junction(
    *,
    discharges: tuple[float, float, float] = (5.0, 7.0, 12.0),
    rotation_degrees: float = 0.0,
    upstream_sections: tuple[
        TrapezoidalChannelSection, TrapezoidalChannelSection
    ]
    | None = None,
    upstream_beds: tuple[float, float] = (0.0, 0.0),
):
    surface = 2.0
    if upstream_sections is None:
        upstream_sections = (
            TrapezoidalChannelSection(10.0, 0.0),
            TrapezoidalChannelSection(10.0, 0.0),
        )
    downstream_section = TrapezoidalChannelSection(10.0, 0.0)
    upstream = tuple(
        _terminal(
            branch_id,
            section=section,
            bed=bed,
            surface=surface,
            discharge=discharge,
        )
        for branch_id, section, bed, discharge in zip(
            ("up-a", "up-b"),
            upstream_sections,
            upstream_beds,
            discharges[:2],
            strict=True,
        )
    )
    downstream = _terminal(
        "down",
        section=downstream_section,
        bed=0.0,
        surface=surface,
        discharge=discharges[2],
    )
    contract = ConservativeVectorJunctionContract(
        "junction-y",
        ("up-a", "up-b"),
        "down",
        tuple(
            (value + rotation_degrees) % 360.0
            for value in (45.0, 315.0)
        ),
        rotation_degrees % 360.0,
        "manufactured:stage14",
    )
    junction = solve_conservative_vector_junction(
        upstream, downstream, contract
    )
    return upstream, downstream, junction


def _rotate_vector(
    east: float,
    north: float,
    angle_degrees: float,
) -> tuple[float, float]:
    angle = math.radians(angle_degrees)
    return (
        east * math.cos(angle) + north * math.sin(angle),
        north * math.cos(angle) - east * math.sin(angle),
    )


def test_closed_boundary_measure_and_finite_cell_state_are_explicit():
    geometry = _geometry()
    state = ShallowWaterJunctionCellState(200.0, 10.0, -5.0)

    assert geometry.closure_residual_east_north_m == pytest.approx(
        (0.0, 0.0), abs=1e-12
    )
    assert geometry.upstream_branch_ids == ("up-a", "up-b")
    assert geometry.downstream_branch_id == "down"
    assert state.depth_m(geometry) == 2.0
    assert state.free_surface_elevation_m(geometry) == 2.0
    assert state.velocity_east_mps == 0.05
    assert state.velocity_north_mps == -0.025


def test_hll_cell_step_closes_mass_and_two_component_momentum_ledgers():
    geometry = _geometry()
    state = ShallowWaterJunctionCellState(200.0, 0.0, 0.0)
    upstream, downstream, junction = _junction()
    stable = maximum_shallow_water_junction_cell_timestep_seconds(
        state,
        geometry,
        upstream,
        downstream,
        junction,
        courant_number=0.4,
    )

    step = advance_shallow_water_junction_cell(
        state,
        geometry,
        upstream,
        downstream,
        junction,
        timestep_seconds=0.5 * stable,
        maximum_courant_number=0.4,
    )
    report = step.as_dict()

    assert len(step.opening_fluxes) == 3
    assert len(step.wall_pressure_fluxes) == 3
    assert step.mass_ledger_error_m3 == pytest.approx(0.0, abs=1e-13)
    assert step.momentum_ledger_error_magnitude_m4s == pytest.approx(
        0.0, abs=1e-13
    )
    assert step.state_after != state
    assert step.state_after.volume_m3 > 0.0
    assert report["opening_flux_solver"] == "two_dimensional_rotated_HLL"
    assert report["stage13_inferred_reaction_used"] is False
    assert report["finite_storage_state"] is True
    assert report["branch_reach_states_updated"] is False
    assert report["operator_admitted"] is False


def test_cell_state_feeds_back_into_multistep_hll_exchange():
    geometry = _geometry()
    initial = ShallowWaterJunctionCellState(190.0, 0.0, 0.0)
    state = initial
    upstream, downstream, junction = _junction()
    maximum_mass_error = 0.0
    maximum_momentum_error = 0.0
    opening_mass_fluxes = []

    for _ in range(25):
        stable = maximum_shallow_water_junction_cell_timestep_seconds(
            state,
            geometry,
            upstream,
            downstream,
            junction,
            courant_number=0.4,
        )
        step = advance_shallow_water_junction_cell(
            state,
            geometry,
            upstream,
            downstream,
            junction,
            timestep_seconds=0.5 * stable,
            maximum_courant_number=0.4,
        )
        state = step.state_after
        opening_mass_fluxes.append(step.net_outward_opening_mass_flux_m3s)
        maximum_mass_error = max(
            maximum_mass_error, abs(step.mass_ledger_error_m3)
        )
        maximum_momentum_error = max(
            maximum_momentum_error,
            step.momentum_ledger_error_magnitude_m4s,
        )

    assert state.volume_m3 > 0.0
    assert state != initial
    assert opening_mass_fluxes[-1] != pytest.approx(
        opening_mass_fluxes[0], abs=1e-8
    )
    assert maximum_mass_error <= 1e-12
    assert maximum_momentum_error <= 1e-12


def test_lake_at_rest_is_identity_on_closed_cell_boundary():
    geometry = _geometry()
    state = ShallowWaterJunctionCellState(200.0, 0.0, 0.0)
    upstream, downstream, junction = _junction(
        discharges=(0.0, 0.0, 0.0)
    )
    stable = maximum_shallow_water_junction_cell_timestep_seconds(
        state,
        geometry,
        upstream,
        downstream,
        junction,
        courant_number=0.4,
    )

    step = advance_shallow_water_junction_cell(
        state,
        geometry,
        upstream,
        downstream,
        junction,
        timestep_seconds=stable,
        maximum_courant_number=0.4,
    )

    assert step.net_outward_opening_mass_flux_m3s == pytest.approx(
        0.0, abs=1e-14
    )
    assert step.state_after.volume_m3 == pytest.approx(200.0, abs=1e-12)
    assert step.state_after.momentum_east_m4s == pytest.approx(
        0.0, abs=1e-12
    )
    assert step.state_after.momentum_north_m4s == pytest.approx(
        0.0, abs=1e-12
    )
    assert step.mass_ledger_error_m3 == pytest.approx(0.0, abs=1e-14)
    assert step.momentum_ledger_error_magnitude_m4s == pytest.approx(
        0.0, abs=1e-12
    )


def test_cell_flux_and_state_update_are_rotation_covariant():
    rotation = 37.0
    state = ShallowWaterJunctionCellState(200.0, 0.0, 0.0)
    upstream, downstream, junction = _junction()
    rotated_upstream, rotated_downstream, rotated_junction = _junction(
        rotation_degrees=rotation
    )
    geometry = _geometry()
    rotated_geometry = _geometry(rotation_degrees=rotation)
    stable = maximum_shallow_water_junction_cell_timestep_seconds(
        state,
        geometry,
        upstream,
        downstream,
        junction,
        courant_number=0.4,
    )
    rotated_stable = maximum_shallow_water_junction_cell_timestep_seconds(
        state,
        rotated_geometry,
        rotated_upstream,
        rotated_downstream,
        rotated_junction,
        courant_number=0.4,
    )
    timestep = 0.5 * min(stable, rotated_stable)

    baseline = advance_shallow_water_junction_cell(
        state,
        geometry,
        upstream,
        downstream,
        junction,
        timestep_seconds=timestep,
        maximum_courant_number=0.4,
    )
    rotated = advance_shallow_water_junction_cell(
        state,
        rotated_geometry,
        rotated_upstream,
        rotated_downstream,
        rotated_junction,
        timestep_seconds=timestep,
        maximum_courant_number=0.4,
    )
    expected_momentum = _rotate_vector(
        baseline.state_after.momentum_east_m4s,
        baseline.state_after.momentum_north_m4s,
        rotation,
    )

    assert rotated.net_outward_opening_mass_flux_m3s == pytest.approx(
        baseline.net_outward_opening_mass_flux_m3s, abs=1e-12
    )
    assert rotated.state_after.volume_m3 == pytest.approx(
        baseline.state_after.volume_m3, abs=1e-12
    )
    assert rotated.state_after.momentum_east_m4s == pytest.approx(
        expected_momentum[0], abs=1e-12
    )
    assert rotated.state_after.momentum_north_m4s == pytest.approx(
        expected_momentum[1], abs=1e-12
    )


def test_cell_rejects_nonclosed_geometry_and_excessive_timestep():
    geometry = _geometry()
    with pytest.raises(
        ValueError,
        match="shallow_water_junction_cell_boundary_not_closed",
    ):
        replace(
            geometry,
            faces=(
                *geometry.faces[:-1],
                replace(geometry.faces[-1], length_m=16.0),
            ),
        )

    state = ShallowWaterJunctionCellState(200.0, 0.0, 0.0)
    upstream, downstream, junction = _junction()
    stable = maximum_shallow_water_junction_cell_timestep_seconds(
        state,
        geometry,
        upstream,
        downstream,
        junction,
        courant_number=0.4,
    )
    with pytest.raises(
        ValueError, match="shallow_water_junction_cell_cfl_exceeded"
    ):
        advance_shallow_water_junction_cell(
            state,
            geometry,
            upstream,
            downstream,
            junction,
            timestep_seconds=stable * 1.01,
            maximum_courant_number=0.4,
        )


def test_cell_rejects_rectangular_and_flat_bed_contract_violations():
    geometry = _geometry()
    state = ShallowWaterJunctionCellState(190.0, 0.0, 0.0)
    upstream, downstream, junction = _junction()
    assert maximum_shallow_water_junction_cell_timestep_seconds(
        state,
        geometry,
        upstream,
        downstream,
        junction,
        courant_number=0.4,
    ) > 0.0

    trapezoidal = (
        TrapezoidalChannelSection(10.0, 1.0),
        TrapezoidalChannelSection(10.0, 0.0),
    )
    upstream, downstream, junction = _junction(
        upstream_sections=trapezoidal
    )
    with pytest.raises(
        ValueError,
        match="shallow_water_junction_cell_rectangular_opening_required",
    ):
        maximum_shallow_water_junction_cell_timestep_seconds(
            state,
            geometry,
            upstream,
            downstream,
            junction,
            courant_number=0.4,
        )

    upstream, downstream, junction = _junction(
        upstream_beds=(0.1, 0.0)
    )
    with pytest.raises(
        ValueError, match="shallow_water_junction_cell_flat_bed_required"
    ):
        maximum_shallow_water_junction_cell_timestep_seconds(
            state,
            geometry,
            upstream,
            downstream,
            junction,
            courant_number=0.4,
        )


def test_stage14_compiler_passes_without_overclaiming_network_coupling():
    from scripts import compile_geotransport_stage14_junction_cell_gates

    report = compile_geotransport_stage14_junction_cell_gates.compile_report()

    assert report["all_gates_passed"] is True
    assert len(report["gates"]) == 16
    assert report["status"] == (
        "explicit_2d_junction_cell_manufactured_invariants_pass_"
        "coupled_reach_update_and_public_validation_pending"
    )
    assert report["claim_boundary"][
        "two_component_junction_momentum_state_implemented"
    ] is True
    assert report["claim_boundary"][
        "stage13_inferred_reaction_used"
    ] is False
    assert report["claim_boundary"][
        "branch_reach_states_updated_conservatively"
    ] is False
    assert report["claim_boundary"]["candidate_operator_admitted"] is False
