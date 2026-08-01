from __future__ import annotations

from dataclasses import replace
import math

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    public_confluence_roughness_ensemble as uncertainty,
)


def _ensemble():
    return uncertainty.compile_public_confluence_roughness_ensemble()


def test_public_roughness_ensemble_compiles_two_support_rules_and_eight_members():
    value = _ensemble()
    report = value.as_dict()

    assert len(value.cells) == 6
    assert tuple(value.member_by_id) == uncertainty.ENSEMBLE_MEMBER_ORDER
    assert report["spatial_support_rules"] == [
        uncertainty.SPATIAL_SUPPORT_RULE_POINT,
        uncertainty.SPATIAL_SUPPORT_RULE_FOOTPRINT,
    ]
    assert value.land_cover_pixel_width_m > 25.0
    assert value.land_cover_pixel_height_m > 25.0
    assert value.land_cover_pixel_area_m2 > 800.0
    assert report["roughness_calibrated"] is False
    assert report["runtime_hydraulic_geometry_admitted"] is False
    assert report["operator_admitted"] is False


def test_pixel_footprints_cover_every_cell_and_expose_resolution_sensitivity():
    value = _ensemble()

    assert sum(cell.point_nearest_fallback for cell in value.cells) == 5
    assert all(
        cell.footprint_coverage_fraction == pytest.approx(1.0, abs=1e-9)
        for cell in value.cells
    )
    changed = [
        cell
        for cell in value.cells
        if abs(cell.support_rule_center_difference) > 1e-12
    ]
    assert {cell.cell_id for cell in changed} == {
        "cell-00",
        "cell-04",
        "cell-05",
    }
    assert any(
        len(cell.footprint_class_area_fractions) > 1 for cell in value.cells
    )
    assert all(
        sum(fraction for _, fraction in cell.footprint_class_area_fractions)
        == pytest.approx(1.0, abs=1e-9)
        for cell in value.cells
    )


def test_joint_intervals_envelope_parameter_and_support_uncertainty():
    value = _ensemble()

    for cell in value.cells:
        assert cell.joint_lower == min(
            cell.point_lower, cell.footprint_lower
        )
        assert cell.joint_upper == max(
            cell.point_upper, cell.footprint_upper
        )
        assert cell.joint_interval_width > 0.0
        member_values = [
            field.cell_by_id[cell.cell_id].manning_n
            for field in value.members
        ]
        assert min(member_values) == cell.joint_lower
        assert max(member_values) == cell.joint_upper
        assert all(
            cell.joint_lower <= item <= cell.joint_upper
            for item in member_values
        )


def test_every_member_preserves_exact_stage20_spatial_binding():
    value = _ensemble()
    geometry = value.fixture.diagnostic_horizontal_geometry

    for member in value.members:
        assert member.geometry_provenance_id == geometry.provenance_id
        assert tuple(cell.cell_id for cell in member.cells) == tuple(
            cell.cell_id for cell in geometry.cells
        )
        for cell in member.cells:
            assert cell.support_area_m2 == pytest.approx(
                geometry.cell_areas_m2[cell.cell_id], abs=1e-9
            )


def test_roughness_ensemble_propagation_closes_ledgers_and_is_monotone():
    value = _ensemble()
    propagation = uncertainty.propagate_public_confluence_roughness_ensemble(
        value
    )
    members = {item.member_id: item.step for item in propagation.members}
    lower = members["joint_lower"]
    upper = members["joint_upper"]

    assert all(
        step.volume_ledger_error_m3 == 0.0
        and step.momentum_ledger_error_magnitude_m4s < 1e-10
        and step.kinetic_energy_dissipation_m5s2 > 0.0
        for step in members.values()
    )
    assert lower.kinetic_energy_dissipation_m5s2 == min(
        item.kinetic_energy_dissipation_m5s2 for item in members.values()
    )
    assert upper.kinetic_energy_dissipation_m5s2 == max(
        item.kinetic_energy_dissipation_m5s2 for item in members.values()
    )
    for cell_id in value.fixture.diagnostic_horizontal_geometry.cell_by_id:
        lower_trace = next(
            item for item in lower.cell_traces if item.cell_id == cell_id
        )
        upper_trace = next(
            item for item in upper.cell_traces if item.cell_id == cell_id
        )
        assert lower_trace.damping_factor >= upper_trace.damping_factor
        assert (
            lower_trace.kinetic_energy_dissipation_m5s2
            <= upper_trace.kinetic_energy_dissipation_m5s2
        )
    assert propagation.as_dict()["diagnostic_state_is_observed"] is False
    assert propagation.as_dict()["runtime_hydraulic_rollout"] is False


def test_support_aggregation_difference_propagates_into_friction_response():
    value = _ensemble()
    propagation = uncertainty.propagate_public_confluence_roughness_ensemble(
        value
    )
    members = {item.member_id: item.step for item in propagation.members}

    assert members["point_center"].kinetic_energy_dissipation_m5s2 != (
        members["footprint_center"].kinetic_energy_dissipation_m5s2
    )
    point_traces = {
        item.cell_id: item for item in members["point_center"].cell_traces
    }
    footprint_traces = {
        item.cell_id: item
        for item in members["footprint_center"].cell_traces
    }
    changed = {
        cell_id
        for cell_id in point_traces
        if point_traces[cell_id].damping_factor
        != footprint_traces[cell_id].damping_factor
    }
    assert changed == {"cell-00", "cell-04", "cell-05"}


def test_entire_roughness_ensemble_is_rotation_covariant():
    value = _ensemble()
    angle = math.radians(37.0)
    cosine = math.cos(angle)
    sine = math.sin(angle)

    def rotate(east, north):
        return (
            east * cosine - north * sine,
            east * sine + north * cosine,
        )

    geometry = value.fixture.diagnostic_horizontal_geometry
    rotated_geometry = replace(
        geometry,
        vertices=tuple(
            replace(
                vertex,
                east_m=rotate(vertex.east_m, vertex.north_m)[0],
                north_m=rotate(vertex.east_m, vertex.north_m)[1],
            )
            for vertex in geometry.vertices
        ),
        provenance_id=f"{geometry.provenance_id}:rotated-37",
    )
    rotated_fixture = replace(
        value.fixture, diagnostic_horizontal_geometry=rotated_geometry
    )
    rotated_members = tuple(
        replace(
            member, geometry_provenance_id=rotated_geometry.provenance_id
        )
        for member in value.members
    )
    rotated_ensemble = replace(
        value, fixture=rotated_fixture, members=rotated_members
    )
    state = uncertainty.diagnostic_patch_state(value)
    rotated_state = replace(
        state,
        cells=tuple(
            replace(
                cell,
                momentum_east_m4s=rotate(
                    cell.momentum_east_m4s, cell.momentum_north_m4s
                )[0],
                momentum_north_m4s=rotate(
                    cell.momentum_east_m4s, cell.momentum_north_m4s
                )[1],
            )
            for cell in state.cells
        ),
    )
    baseline = uncertainty.propagate_public_confluence_roughness_ensemble(
        value, state=state
    )
    rotated = uncertainty.propagate_public_confluence_roughness_ensemble(
        rotated_ensemble, state=rotated_state
    )

    for before, actual in zip(baseline.members, rotated.members, strict=True):
        assert actual.member_id == before.member_id
        assert actual.step.kinetic_energy_dissipation_m5s2 == pytest.approx(
            before.step.kinetic_energy_dissipation_m5s2, abs=1e-10
        )
        for expected_cell, actual_cell in zip(
            before.step.state_after.cells,
            actual.step.state_after.cells,
            strict=True,
        ):
            expected = rotate(
                expected_cell.momentum_east_m4s,
                expected_cell.momentum_north_m4s,
            )
            assert (
                actual_cell.momentum_east_m4s,
                actual_cell.momentum_north_m4s,
            ) == pytest.approx(expected, abs=1e-10)


def test_unknown_class_and_invalid_propagation_state_fail_closed():
    with pytest.raises(
        ValueError, match="public_roughness_land_cover_class_unmapped:999"
    ):
        uncertainty._roughness_interval(((999, 1.0),))

    value = _ensemble()
    state = uncertainty.diagnostic_patch_state(value)
    wrong_state = replace(state, cells=tuple(reversed(state.cells)))
    with pytest.raises(
        ValueError, match="public_roughness_propagation_state_mismatch"
    ):
        uncertainty.propagate_public_confluence_roughness_ensemble(
            value, state=wrong_state
        )


def test_compiled_stage22_report_passes_without_hydraulic_admission():
    from scripts import (
        compile_geotransport_stage22_public_roughness_ensemble_gates as gates,
    )

    report = gates.compile_report()

    assert report["all_gates_passed"] is True
    assert all(report["gates"].values())
    assert report["claim_boundary"][
        "public_land_cover_support_uncertainty_propagated"
    ] is True
    assert report["claim_boundary"][
        "roughness_lookup_uncertainty_propagated"
    ] is True
    assert report["claim_boundary"][
        "runtime_hydraulic_geometry_admitted"
    ] is False
    assert report["claim_boundary"]["operator_admitted"] is False

