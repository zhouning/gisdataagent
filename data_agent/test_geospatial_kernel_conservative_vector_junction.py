from __future__ import annotations

from dataclasses import replace
import math

import pytest

from data_agent.uwm.geospatial_kernel_v2.conservative_vector_junction import (
    ConservativeVectorJunctionContract,
    advance_conservative_vector_confluence_network_open,
    solve_conservative_vector_junction,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_coupled import (
    FixedDynamicWaveBoundary,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_flux import (
    STANDARD_GRAVITY_MPS2,
    DynamicWaveCellState,
    PrismaticDynamicWaveState,
    TrapezoidalChannelSection,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_junction import (
    DynamicWaveJunctionTerminal,
    DynamicWaveNetworkReach,
    maximum_subcritical_confluence_stable_timestep_seconds,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_junction_geometry import (
    GeographicJunctionBranchSource,
    compile_geographic_junction_geometry,
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
        branch_id=branch_id,
        interior_state=DynamicWaveCellState(
            section.area_m2(surface - bed), discharge
        ),
        section=section,
        bed_elevation_m=bed,
    )


def _manufactured_junction():
    surface = 3.0
    upstream = (
        _terminal(
            "up-a",
            section=TrapezoidalChannelSection(8.0, 1.0),
            bed=0.2,
            surface=surface,
            discharge=3.0,
        ),
        _terminal(
            "up-b",
            section=TrapezoidalChannelSection(6.0, 0.5),
            bed=0.5,
            surface=surface,
            discharge=4.0,
        ),
    )
    downstream = _terminal(
        "down",
        section=TrapezoidalChannelSection(12.0, 2.0),
        bed=0.1,
        surface=surface,
        discharge=7.0,
    )
    contract = ConservativeVectorJunctionContract(
        junction_id="manufactured-y",
        upstream_branch_ids=("up-a", "up-b"),
        downstream_branch_id="down",
        upstream_flow_azimuth_degrees=(35.0, 315.0),
        downstream_flow_azimuth_degrees=5.0,
        provenance_id="manufactured:stage13",
    )
    return upstream, downstream, contract


def _rotate_vector_clockwise_from_north(
    east: float,
    north: float,
    angle_degrees: float,
) -> tuple[float, float]:
    angle = math.radians(angle_degrees)
    return (
        east * math.cos(angle) + north * math.sin(angle),
        north * math.cos(angle) - east * math.sin(angle),
    )


def test_native_junction_closes_mass_and_explicit_vector_reaction_ledgers():
    upstream, downstream, contract = _manufactured_junction()

    result = solve_conservative_vector_junction(
        upstream, downstream, contract
    )

    assert result.net_outward_mass_flux_m3s == pytest.approx(0.0, abs=1e-12)
    assert result.momentum_ledger_residual_magnitude_m4s2 == 0.0
    assert result.junction_reaction_magnitude_m4s2 > 0.0
    assert result.junction_on_fluid_reaction_east_m4s2 == pytest.approx(
        result.boundary_total_flux_east_m4s2
    )
    assert result.junction_on_fluid_reaction_north_m4s2 == pytest.approx(
        result.boundary_total_flux_north_m4s2
    )
    for flux, terminal in zip(
        result.upstream_fluxes, upstream, strict=True
    ):
        state = terminal.interior_state
        expected_pressure = (
            STANDARD_GRAVITY_MPS2
            * terminal.section.hydrostatic_pressure_integral_m3(
                state.area_m2
            )
        )
        assert flux.convective_flux_m4s2 == pytest.approx(
            state.discharge_m3s**2 / state.area_m2
        )
        assert flux.hydrostatic_flux_m4s2 == pytest.approx(
            expected_pressure
        )


def test_native_junction_vector_ledger_is_rotation_invariant():
    upstream, downstream, contract = _manufactured_junction()
    baseline = solve_conservative_vector_junction(
        upstream, downstream, contract
    )
    rotation = 73.0
    rotated_contract = replace(
        contract,
        upstream_flow_azimuth_degrees=tuple(
            (value + rotation) % 360.0
            for value in contract.upstream_flow_azimuth_degrees
        ),
        downstream_flow_azimuth_degrees=(
            contract.downstream_flow_azimuth_degrees + rotation
        )
        % 360.0,
    )

    rotated = solve_conservative_vector_junction(
        upstream, downstream, rotated_contract
    )
    expected = _rotate_vector_clockwise_from_north(
        baseline.junction_on_fluid_reaction_east_m4s2,
        baseline.junction_on_fluid_reaction_north_m4s2,
        rotation,
    )

    assert rotated.junction_on_fluid_reaction_east_m4s2 == pytest.approx(
        expected[0], abs=1e-12
    )
    assert rotated.junction_on_fluid_reaction_north_m4s2 == pytest.approx(
        expected[1], abs=1e-12
    )
    assert rotated.junction_reaction_magnitude_m4s2 == pytest.approx(
        baseline.junction_reaction_magnitude_m4s2, abs=1e-12
    )
    assert rotated.hydraulic_solution == baseline.hydraulic_solution


def test_native_junction_is_invariant_to_consistent_upstream_reordering():
    upstream, downstream, contract = _manufactured_junction()
    baseline = solve_conservative_vector_junction(
        upstream, downstream, contract
    )
    reordered_contract = replace(
        contract,
        upstream_branch_ids=tuple(reversed(contract.upstream_branch_ids)),
        upstream_flow_azimuth_degrees=tuple(
            reversed(contract.upstream_flow_azimuth_degrees)
        ),
    )

    reordered = solve_conservative_vector_junction(
        tuple(reversed(upstream)), downstream, reordered_contract
    )

    assert reordered.net_outward_mass_flux_m3s == pytest.approx(
        baseline.net_outward_mass_flux_m3s, abs=1e-12
    )
    assert reordered.boundary_total_flux_east_m4s2 == pytest.approx(
        baseline.boundary_total_flux_east_m4s2, abs=1e-12
    )
    assert reordered.boundary_total_flux_north_m4s2 == pytest.approx(
        baseline.boundary_total_flux_north_m4s2, abs=1e-12
    )


def test_symmetric_lake_at_rest_retains_state_and_balances_wall_reaction():
    section = TrapezoidalChannelSection(10.0, 2.0)
    surface = 2.0
    upstream = (
        _terminal(
            "up-left",
            section=section,
            bed=0.0,
            surface=surface,
            discharge=0.0,
        ),
        _terminal(
            "up-right",
            section=section,
            bed=0.0,
            surface=surface,
            discharge=0.0,
        ),
    )
    downstream = _terminal(
        "down",
        section=section,
        bed=0.0,
        surface=surface,
        discharge=0.0,
    )
    contract = ConservativeVectorJunctionContract(
        "symmetric-lake",
        ("up-left", "up-right"),
        "down",
        (45.0, 315.0),
        0.0,
        "manufactured:lake-at-rest",
    )

    result = solve_conservative_vector_junction(
        upstream, downstream, contract
    )

    assert result.hydraulic_solution.common_free_surface_elevation_m == pytest.approx(
        surface
    )
    assert all(
        value.state.discharge_m3s == 0.0
        for value in result.hydraulic_solution.upstream_boundaries
    )
    assert result.hydraulic_solution.downstream_boundary.state.discharge_m3s == 0.0
    assert result.junction_on_fluid_reaction_east_m4s2 == pytest.approx(
        0.0, abs=1e-12
    )
    assert result.momentum_ledger_residual_magnitude_m4s2 == 0.0


def test_native_junction_rejects_branch_mismatch_and_reverse_flow():
    upstream, downstream, contract = _manufactured_junction()
    with pytest.raises(
        ValueError, match="conservative_vector_junction_branch_mismatch"
    ):
        solve_conservative_vector_junction(
            tuple(reversed(upstream)), downstream, contract
        )

    reverse_upstream = (
        replace(
            upstream[0],
            interior_state=replace(
                upstream[0].interior_state, discharge_m3s=-1.0
            ),
        ),
        replace(
            upstream[1],
            interior_state=replace(
                upstream[1].interior_state, discharge_m3s=8.0
            ),
        ),
    )
    with pytest.raises(
        ValueError,
        match="conservative_vector_junction_flow_direction_not_supported",
    ):
        solve_conservative_vector_junction(
            reverse_upstream, downstream, contract
        )


def test_native_junction_serialization_does_not_overclaim_admission():
    upstream, downstream, contract = _manufactured_junction()

    report = solve_conservative_vector_junction(
        upstream, downstream, contract
    ).as_dict()

    assert report["operator_admitted"] is False
    assert report["reaction_is_inferred_not_observed"] is True
    assert report["multidimensional_junction_state_solved"] is False
    assert report["zero_reaction_assumed"] is False
    assert report[
        "vector_momentum_ledger_closed_with_explicit_reaction"
    ] is True
    assert report["contract"]["azimuth_reference"] == (
        "degrees_clockwise_from_true_north"
    )


def test_native_network_step_retains_node_reaction_and_mass_ledgers():
    section = TrapezoidalChannelSection(10.0, 2.0)
    area = section.area_m2(2.0)

    def reach(reach_id: str, discharge: float) -> DynamicWaveNetworkReach:
        return DynamicWaveNetworkReach(
            reach_id=reach_id,
            state=PrismaticDynamicWaveState(
                (area,) * 4, (discharge,) * 4
            ),
            bed_elevation_m=(0.0,) * 4,
            sections=(section,) * 4,
            cell_length_m=100.0,
            manning_n=(1e-6,) * 4,
            lateral_inflow_m2s=(0.0,) * 4,
        )

    upstream = (reach("up-a", 5.0), reach("up-b", 7.0))
    downstream = reach("down", 12.0)
    left_boundaries = tuple(
        FixedDynamicWaveBoundary(
            DynamicWaveCellState(area, discharge), 0.0
        )
        for discharge in (5.0, 7.0)
    )
    right_boundary = FixedDynamicWaveBoundary(
        DynamicWaveCellState(area, 12.0), 0.0
    )
    contract = ConservativeVectorJunctionContract(
        "network-y",
        ("up-a", "up-b"),
        "down",
        (45.0, 315.0),
        0.0,
        "manufactured:network-step",
    )
    timestep = maximum_subcritical_confluence_stable_timestep_seconds(
        upstream,
        downstream,
        upstream_left_boundaries=left_boundaries,
        downstream_right_boundary=right_boundary,
        courant_number=0.4,
    )

    result = advance_conservative_vector_confluence_network_open(
        upstream,
        downstream,
        contract,
        upstream_left_boundaries=left_boundaries,
        downstream_right_boundary=right_boundary,
        lateral_momentum_convention="zero_longitudinal_momentum",
        timestep_seconds=timestep,
        maximum_courant_number=0.4,
    )
    report = result.as_dict()

    assert result.hydraulic_step.network_volume_balance_error_m3 == pytest.approx(
        0.0, abs=1e-8
    )
    assert result.vector_junction.net_outward_mass_flux_m3s == pytest.approx(
        0.0, abs=1e-12
    )
    assert result.vector_junction.momentum_ledger_residual_magnitude_m4s2 == 0.0
    assert result.vector_junction.junction_reaction_magnitude_m4s2 > 0.0
    assert report["junction_reaction_retained_as_node_state"] is True
    assert report[
        "junction_reaction_applied_as_one_dimensional_branch_source"
    ] is False
    assert report["operator_admitted"] is False


def test_native_junction_contract_rejects_noncanonical_azimuth():
    _, _, contract = _manufactured_junction()

    with pytest.raises(
        ValueError, match="conservative_vector_junction_contract_invalid"
    ):
        replace(contract, downstream_flow_azimuth_degrees=360.0)


def test_native_contract_binds_admitted_wgs84_centerline_directions():
    sources = (
        GeographicJunctionBranchSource(
            "A",
            "upstream",
            "A",
            ((-0.002, 0.0), (0.0, 0.0)),
            "https://example.test/centerlines.geojson",
            "a" * 64,
        ),
        GeographicJunctionBranchSource(
            "B",
            "upstream",
            "B",
            ((0.0, 0.002), (0.0, 0.0)),
            "https://example.test/centerlines.geojson",
            "a" * 64,
        ),
        GeographicJunctionBranchSource(
            "C",
            "downstream",
            "C",
            ((0.0, 0.0), (0.002, 0.0)),
            "https://example.test/centerlines.geojson",
            "a" * 64,
        ),
    )
    geometry = compile_geographic_junction_geometry(
        "C",
        (0.0, 0.0),
        sources,
        geometry_window_length_m=100.0,
        terminal_snap_tolerance_m=1.0,
        minimum_terminal_path_length_m=20.0,
    )

    contract = ConservativeVectorJunctionContract.from_geographic_geometry(
        geometry
    )

    assert contract.upstream_branch_ids == ("A", "B")
    assert contract.downstream_branch_id == "C"
    assert contract.upstream_flow_azimuth_degrees == pytest.approx(
        (90.0, 180.0), abs=1e-8
    )
    assert contract.downstream_flow_azimuth_degrees == pytest.approx(
        90.0, abs=1e-8
    )
    assert contract.provenance_id == "geographic_junction_geometry:C"


def test_stage13_compiler_passes_invariants_without_admitting_operator():
    from scripts import (
        compile_geotransport_stage13_vector_junction_gates as compiler,
    )

    report = compiler.compile_report()

    assert report["all_gates_passed"] is True
    assert len(report["gates"]) == 14
    assert report["status"] == (
        "native_candidate_manufactured_invariants_pass_"
        "public_validation_pending"
    )
    assert report["claim_boundary"][
        "native_junction_law_fully_specified"
    ] is True
    assert report["claim_boundary"][
        "reaction_independently_observed"
    ] is False
    assert report["claim_boundary"][
        "public_confluence_validation_completed"
    ] is False
    assert report["claim_boundary"]["candidate_operator_admitted"] is False
    assert report["public_validation_evidence_audit"][
        "admitted_dataset"
    ] is None
