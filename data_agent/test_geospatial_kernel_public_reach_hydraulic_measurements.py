from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    public_reach_hydraulic_measurements as measurements,
)


def _compiled():
    return measurements.compile_public_reach_hydraulic_measurements()


def test_public_channel_measurements_compile_all_observed_states():
    value = _compiled()
    report = value.as_dict()

    assert value.monitoring_location_id == "USGS-03424860"
    assert value.reach_id == "18421703"
    assert len(value.measurements) == 110
    assert len({item.measurement_id for item in value.measurements}) == 110
    assert value.measurements[0].time == "2011-01-25T18:37:30+00:00"
    assert value.measurements[-1].time == "2026-05-20T15:54:29+00:00"
    assert report["subcritical_observation_count"] == 110
    assert report["claim_boundary"][
        "public_downstream_reach_hydraulic_states_compiled"
    ] is True


def test_source_record_without_measurement_number_is_retained_by_uuid():
    value = _compiled()
    unnumbered = [
        item for item in value.measurements if item.measurement_number == ""
    ]

    assert len(unnumbered) == 1
    assert (
        unnumbered[0].measurement_id
        == "cedaf1eb-8de6-4829-8c65-304423fe0af9"
    )
    assert unnumbered[0].time == "2019-10-15T17:04:04+00:00"


def test_observed_measurements_bind_dynamic_wave_state_and_equivalent_section():
    value = _compiled()

    for item in value.measurements:
        state = item.dynamic_wave_state
        section = item.equivalent_section
        assert state.area_m2 == item.flow_area_m2
        assert state.discharge_m3s == item.flow_m3s
        assert state.mean_velocity_mps == pytest.approx(
            item.kernel_mean_velocity_mps
        )
        assert section.area_m2(item.equivalent_mean_depth_m) == pytest.approx(
            item.flow_area_m2, abs=1e-12
        )
        assert section.top_width_m(item.flow_area_m2) == pytest.approx(
            item.top_width_m, abs=1e-12
        )
        assert item.froude_number < 1.0
        assert item.characteristic_speeds_mps[0] < 0.0
        assert item.characteristic_speeds_mps[1] > 0.0


def test_observed_flow_area_velocity_identity_closes_with_source_rounding():
    value = _compiled()

    assert max(
        item.flow_closure_relative_error for item in value.measurements
    ) == pytest.approx(0.01261261261261258)
    assert all(
        item.flow_closure_relative_error
        <= measurements.FLOW_CLOSURE_TOLERANCE
        for item in value.measurements
    )
    assert value.as_dict()["maximum_flow_closure_relative_error"] < 0.02


def test_field_visit_join_selects_nearest_mean_gage_height():
    value = _compiled()
    measurement = next(
        item for item in value.measurements if item.measurement_number == "42"
    )

    assert measurement.time == "2015-11-30T17:19:17+00:00"
    assert measurement.gage_height_m == pytest.approx(21.40 * 0.3048)
    assert measurement.gage_height_approval_status == "Approved"
    assert measurement.as_dict()["field_context"][
        "gage_height_is_bed_referenced_depth"
    ] is False


def test_measurement_ranges_are_real_and_method_diverse():
    report = _compiled().as_dict()
    ranges = report["observed_ranges_and_quantiles"]

    assert ranges["flow_m3s"]["minimum"] == pytest.approx(
        272.0 * measurements.CUBIC_FOOT_PER_SECOND_TO_M3S
    )
    assert ranges["flow_m3s"]["maximum"] == pytest.approx(
        26200.0 * measurements.CUBIC_FOOT_PER_SECOND_TO_M3S
    )
    assert ranges["top_width_m"]["minimum"] == pytest.approx(79.0 * 0.3048)
    assert ranges["top_width_m"]["maximum"] == pytest.approx(367.0 * 0.3048)
    assert report["method_counts"]["BridgeDownstreamSide"] == 81
    assert report["method_counts"]["Wading"] == 25
    assert report["channel_measurement_type_counts"]["adcp"] == 82


def test_downstream_measurements_do_not_unlock_fixed_or_patch_geometry():
    value = _compiled()
    report = value.as_dict()

    with pytest.raises(
        ValueError,
        match="public_reach_measurements_state_conditioned_not_fixed_geometry",
    ):
        value.require_fixed_reach_geometry()
    with pytest.raises(
        ValueError,
        match="public_reach_measurement_not_confluence_patch_bathymetry",
    ):
        value.require_confluence_patch_bathymetry()
    assert report["kernel_binding"]["fixed_reach_geometry_admitted"] is False
    assert report["kernel_binding"][
        "confluence_patch_bathymetry_admitted"
    ] is False
    assert report["claim_boundary"]["operator_admitted"] is False


def test_compiled_stage23_report_passes_without_geometry_or_operator_admission():
    from scripts import (
        compile_geotransport_stage23_public_reach_hydraulic_gates as gates,
    )

    report = gates.compile_report()

    assert report["all_gates_passed"] is True
    assert len(report["gates"]) == 18
    assert all(report["gates"].values())
    assert report["observation_summary"]["subcritical_observation_count"] == 110
    assert report["claim_boundary"][
        "public_downstream_reach_hydraulic_states_compiled"
    ] is True
    assert report["claim_boundary"]["fixed_reach_geometry_admitted"] is False
    assert report["claim_boundary"]["confluence_bathymetry_completed"] is False
    assert report["claim_boundary"]["operator_admitted"] is False
