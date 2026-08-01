from __future__ import annotations

from dataclasses import replace
import math

import pytest

from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_flux import (
    STANDARD_GRAVITY_MPS2,
    DynamicWaveCellState,
    TrapezoidalChannelSection,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_junction import (
    DynamicWaveJunctionTerminal,
)
from data_agent.uwm.geospatial_kernel_v2.dynamic_wave_junction_momentum import (
    ProjectedMomentumJunctionContract,
    dynamic_wave_specific_force_m3,
    evaluate_projected_momentum_balance,
    manning_friction_slope,
    solve_subcritical_projected_momentum_junction,
)
from scripts.compile_geotransport_dynamic_wave_momentum_junction_gates import (
    compile_gates,
)


def _aligned_manufactured_junction() -> tuple[
    tuple[DynamicWaveJunctionTerminal, ...],
    DynamicWaveJunctionTerminal,
    ProjectedMomentumJunctionContract,
]:
    sections = (
        TrapezoidalChannelSection(4.0, 0.0),
        TrapezoidalChannelSection(6.0, 0.0),
        TrapezoidalChannelSection(10.0, 0.0),
    )
    states = (
        DynamicWaveCellState(8.0, 2.0),
        DynamicWaveCellState(12.0, 3.0),
        DynamicWaveCellState(20.0, 5.0),
    )
    upstream = tuple(
        DynamicWaveJunctionTerminal(branch_id, state, section, 1.0)
        for branch_id, state, section in zip(
            ("A", "B"), states[:2], sections[:2], strict=True
        )
    )
    downstream = DynamicWaveJunctionTerminal(
        "C", states[2], sections[2], 1.0
    )
    contract = ProjectedMomentumJunctionContract(
        upstream_branch_ids=("A", "B"),
        downstream_branch_id="C",
        upstream_deflection_degrees=(0.0, 0.0),
        section_spacing_m=(0.0, 0.0),
        upstream_manning_n=(0.03, 0.03),
        downstream_manning_n=0.03,
        upstream_bed_slopes=(0.0, 0.0),
        downstream_bed_slope=0.0,
        upstream_momentum_coefficients=(1.0, 1.0),
        downstream_momentum_coefficient=1.0,
        provenance_id="manufactured:aligned_rectangular_sections",
    )
    return upstream, downstream, contract


def _angled_force_manufactured_junction() -> tuple[
    tuple[DynamicWaveJunctionTerminal, ...],
    DynamicWaveJunctionTerminal,
    ProjectedMomentumJunctionContract,
]:
    upstream, _, base_contract = _aligned_manufactured_junction()
    downstream = DynamicWaveJunctionTerminal(
        "C",
        DynamicWaveCellState(10.0, 5.0),
        TrapezoidalChannelSection(10.0, 0.0),
        2.0,
    )
    contract = replace(
        base_contract,
        upstream_deflection_degrees=(20.0, 35.0),
        section_spacing_m=(60.0, 60.0),
        upstream_manning_n=(0.03, 0.04),
        downstream_manning_n=0.035,
        upstream_bed_slopes=(0.001, 0.002),
        downstream_bed_slope=0.0015,
        upstream_momentum_coefficients=(1.1, 1.2),
        provenance_id="manufactured:angled_full_force_balance",
    )
    provisional = evaluate_projected_momentum_balance(
        upstream,
        downstream,
        tuple(value.interior_state for value in upstream),
        downstream.interior_state,
        contract,
    )
    downstream_hydrostatic = (
        downstream.section.hydrostatic_pressure_integral_m3(
            downstream.interior_state.area_m2
        )
    )
    downstream_convective_per_beta = (
        downstream.interior_state.discharge_m3s**2
        / (
            STANDARD_GRAVITY_MPS2
            * downstream.interior_state.area_m2
        )
    )
    required_beta = (
        provisional.upstream_contribution_sum_m3 - downstream_hydrostatic
    ) / downstream_convective_per_beta
    return (
        upstream,
        downstream,
        replace(contract, downstream_momentum_coefficient=required_beta),
    )


def test_projected_momentum_junction_recovers_manufactured_aligned_state():
    upstream, downstream, contract = _aligned_manufactured_junction()

    result = solve_subcritical_projected_momentum_junction(
        upstream, downstream, contract
    )

    assert result.common_upstream_free_surface_elevation_m == pytest.approx(3.0)
    assert result.total_upstream_discharge_m3s == pytest.approx(5.0)
    assert result.downstream_discharge_m3s == pytest.approx(5.0)
    assert result.junction_mass_balance_residual_m3s == pytest.approx(0.0)
    assert result.momentum_balance.residual_m3 == pytest.approx(0.0)
    assert result.maximum_absolute_outgoing_invariant_residual_mps <= 1e-12
    assert result.momentum_balance.friction_forces_m3 == (0.0, 0.0)
    assert result.momentum_balance.water_weight_forces_m3 == (0.0, 0.0)
    assert tuple(
        value.state.area_m2 for value in result.upstream_boundaries
    ) == pytest.approx((8.0, 12.0))
    assert result.downstream_boundary.state.area_m2 == pytest.approx(20.0)


def test_projected_momentum_junction_closes_angles_friction_and_weight():
    upstream, downstream, contract = _angled_force_manufactured_junction()

    result = solve_subcritical_projected_momentum_junction(
        upstream, downstream, contract
    )
    balance = result.momentum_balance

    assert result.common_upstream_free_surface_elevation_m == pytest.approx(3.0)
    assert balance.residual_m3 == pytest.approx(0.0, abs=1e-11)
    assert balance.downstream_area_fractions == pytest.approx((0.4, 0.6))
    assert all(value > 0.0 for value in balance.friction_forces_m3)
    assert all(value > 0.0 for value in balance.water_weight_forces_m3)
    assert all(
        projected < unprojected
        for projected, unprojected in zip(
            balance.upstream_projected_specific_forces_m3,
            balance.upstream_specific_forces_m3,
            strict=True,
        )
    )
    downstream_force = dynamic_wave_specific_force_m3(
        downstream.interior_state,
        downstream.section,
        contract.downstream_momentum_coefficient,
    )
    assert balance.downstream_specific_force_m3 == pytest.approx(
        downstream_force
    )


def test_full_force_terms_use_arithmetic_endpoint_manning_and_bed_slopes():
    upstream, downstream, contract = _angled_force_manufactured_junction()
    states = tuple(value.interior_state for value in upstream)

    balance = evaluate_projected_momentum_balance(
        upstream, downstream, states, downstream.interior_state, contract
    )

    downstream_sf = manning_friction_slope(
        downstream.interior_state,
        downstream.section,
        contract.downstream_manning_n,
    )
    for index, (state, terminal) in enumerate(
        zip(states, upstream, strict=True)
    ):
        upstream_sf = manning_friction_slope(
            state, terminal.section, contract.upstream_manning_n[index]
        )
        cosine = math.cos(
            math.radians(contract.upstream_deflection_degrees[index])
        )
        projected_control_area = (
            state.area_m2 * cosine
            + downstream.interior_state.area_m2
            * balance.downstream_area_fractions[index]
        )
        expected_friction = (
            0.5
            * (upstream_sf + downstream_sf)
            * 0.5
            * contract.section_spacing_m[index]
            * projected_control_area
        )
        expected_weight = (
            0.5
            * (
                contract.upstream_bed_slopes[index]
                + contract.downstream_bed_slope
            )
            * 0.5
            * contract.section_spacing_m[index]
            * projected_control_area
        )
        assert balance.friction_forces_m3[index] == pytest.approx(
            expected_friction
        )
        assert balance.water_weight_forces_m3[index] == pytest.approx(
            expected_weight
        )


def test_projected_momentum_contract_requires_beta_and_supported_angles():
    _, _, contract = _aligned_manufactured_junction()

    with pytest.raises(
        ValueError, match="projected_momentum_junction_contract_invalid"
    ):
        replace(contract, upstream_momentum_coefficients=(1.0, 0.0))
    with pytest.raises(
        ValueError, match="projected_momentum_junction_angle_not_supported"
    ):
        replace(contract, upstream_deflection_degrees=(0.0, 90.01))


def test_projected_momentum_balance_requires_mass_and_combining_flow():
    upstream, downstream, contract = _aligned_manufactured_junction()
    states = tuple(value.interior_state for value in upstream)

    with pytest.raises(
        ValueError, match="projected_momentum_junction_mass_balance_required"
    ):
        evaluate_projected_momentum_balance(
            upstream,
            downstream,
            states,
            DynamicWaveCellState(20.0, 5.1),
            contract,
        )
    with pytest.raises(
        ValueError, match="projected_momentum_junction_state_not_supported"
    ):
        evaluate_projected_momentum_balance(
            upstream,
            downstream,
            (DynamicWaveCellState(8.0, -1.0), states[1]),
            DynamicWaveCellState(20.0, 2.0),
            contract,
        )


def test_projected_momentum_solver_rejects_supercritical_interior_state():
    upstream, downstream, contract = _aligned_manufactured_junction()
    invalid_upstream = (
        DynamicWaveJunctionTerminal(
            "A",
            DynamicWaveCellState(0.1, 10.0),
            upstream[0].section,
            upstream[0].bed_elevation_m,
        ),
        upstream[1],
    )

    with pytest.raises(
        ValueError,
        match="projected_momentum_junction_terminal_not_supported",
    ):
        solve_subcritical_projected_momentum_junction(
            invalid_upstream, downstream, contract
        )


def test_ninety_degree_branches_fail_when_no_projected_momentum_root_exists():
    upstream, downstream, contract = _aligned_manufactured_junction()
    orthogonal = replace(
        contract,
        upstream_deflection_degrees=(90.0, 90.0),
    )

    with pytest.raises(
        ValueError, match="projected_momentum_junction_no_momentum_root"
    ):
        solve_subcritical_projected_momentum_junction(
            upstream, downstream, orthogonal
        )


def test_projected_momentum_serialization_states_one_dimensional_claim_boundary():
    upstream, downstream, contract = _angled_force_manufactured_junction()

    payload = solve_subcritical_projected_momentum_junction(
        upstream, downstream, contract
    ).as_dict()

    assert payload["contract"]["projection_axis"] == "downstream_flow_direction"
    assert payload["contract"]["momentum_coefficient_beta_required"] is True
    assert payload["contract"]["downstream_area_partition"] == (
        "upstream_discharge_fraction"
    )
    assert payload["vector_momentum_closure"] is False
    assert payload["operator_admitted"] is False


def test_public_center_hill_projected_momentum_case_fails_admission_closed():
    report = compile_gates()
    public = report["public_case"]

    assert report["gate_summary"] == {
        "passed": 19,
        "total": 19,
        "all_passed": True,
    }
    assert public["initial_state_diagnostic"][
        "raw_junction_mass_balance_residual_m3s"
    ] == pytest.approx(4.12, abs=2e-6)
    assert public["root_scan"]["admissible_candidate_count"] >= 20
    assert public["root_scan"]["minimum_residual_m3"] > 3000.0
    assert public["root_scan"]["root_bracket_found"] is False
    assert public["solver"]["error"] == (
        "projected_momentum_junction_no_momentum_root"
    )
    assert public["momentum_coefficient_evidence"][
        "RouteLink_beta_field_present"
    ] is False
    assert public["admission"]["operator_admitted"] is False
