from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    public_reach_geometry_stability as stability,
)


def _audit():
    return stability.compile_public_reach_geometry_stability_audit()


def test_stage24_partitions_all_source_measurements_without_leakage():
    value = _audit()
    counts = value.as_dict()["cohort_counts"]

    assert counts == {
        "development": 55,
        "temporal_holdout": 20,
        "method_spatial_holdout": 25,
        "provisional_primary": 1,
        "simultaneous_component_channels": 2,
        "other_retained": 7,
    }
    assert value.method_spatial_holdout.measurement_count == 17
    assert len(value.method_holdout_outside_stage_support_ids) == 8


def test_stage24_fits_physical_trapezoid_with_exact_structural_identity():
    value = _audit()
    candidate = value.candidate

    assert candidate.reference_gage_height_m == pytest.approx(4.041648)
    assert candidate.area_at_reference_m2 == pytest.approx(255.80389191)
    assert candidate.top_width_at_reference_m == pytest.approx(71.28849890)
    assert candidate.section.bottom_width_m == pytest.approx(45.42405603)
    assert candidate.side_slope_horizontal_per_vertical == pytest.approx(
        2.95021431
    )
    assert candidate.zero_area_gage_height_m == pytest.approx(-0.34183743)
    for stage in candidate.training_stage_range_m:
        area, width = candidate.predict(stage)
        assert candidate.derivative_width_m(stage) == pytest.approx(
            width, abs=1e-12
        )
        assert candidate.section.area_m2(candidate.depth_m(stage)) == pytest.approx(
            area, abs=1e-12
        )


def test_stage24_area_only_derivative_is_independent_of_observed_width_fit():
    value = _audit()
    model = value.independent_area_model

    assert model.area_intercept_m2 == pytest.approx(253.90385498)
    assert model.area_linear_m == pytest.approx(70.16553666)
    assert model.area_quadratic == pytest.approx(3.73947733)
    assert value.as_dict()["independent_area_derivative_audit"][
        "observed_width_used_during_fit"
    ] is False


def test_stage24_temporal_holdout_passes_but_method_spatial_transfer_fails():
    value = _audit()

    assert value.development.accuracy_passed is True
    assert value.temporal_holdout.accuracy_passed is True
    assert value.method_spatial_holdout.accuracy_passed is False
    assert (
        value.temporal_holdout.area_p90_absolute_percentage_error < 0.04
    )
    assert (
        value.temporal_holdout.width_p90_absolute_percentage_error < 0.07
    )
    assert (
        value.temporal_holdout.derivative_width_p90_absolute_percentage_error
        < 0.14
    )
    assert (
        value.method_spatial_holdout.area_median_absolute_percentage_error
        > 2.0
    )
    assert (
        value.method_spatial_holdout.width_median_absolute_percentage_error
        > 0.15
    )


def test_stage24_component_channels_and_provisional_stage_are_not_training_data():
    report = _audit().as_dict()
    cohorts = report["cohort_measurement_ids"]
    candidate_ids = set(report["candidate"]["training_measurement_ids"])

    assert len(cohorts["simultaneous_component_channels"]) == 2
    assert len(cohorts["provisional_primary"]) == 1
    assert not candidate_ids.intersection(
        cohorts["simultaneous_component_channels"]
    )
    assert not candidate_ids.intersection(cohorts["provisional_primary"])


def test_stage24_reach_wide_runtime_and_confluence_claims_fail_closed():
    value = _audit()
    report = value.as_dict()

    with pytest.raises(
        ValueError, match="public_reach_geometry_method_spatial_holdout_failed"
    ):
        value.require_reach_wide_fixed_geometry()
    with pytest.raises(
        ValueError, match="public_reach_geometry_candidate_diagnostic_only"
    ):
        value.require_runtime_hydraulic_geometry()
    with pytest.raises(
        ValueError,
        match="public_reach_geometry_candidate_not_confluence_patch_bathymetry",
    ):
        value.require_confluence_patch_bathymetry()
    assert report["decision"][
        "bridge_location_candidate_temporally_supported"
    ] is True
    assert report["decision"]["method_spatial_transfer_supported"] is False
    assert report["decision"]["reach_wide_fixed_geometry_admitted"] is False
    assert report["decision"]["operator_admitted"] is False


def test_stage24_candidate_refuses_stage_below_inferred_zero_area_level():
    candidate = _audit().candidate

    with pytest.raises(
        ValueError,
        match="public_reach_geometry_stage_outside_physical_domain",
    ):
        candidate.predict(candidate.zero_area_gage_height_m - 0.01)


def test_compiled_stage24_report_passes_while_runtime_geometry_stays_closed():
    from scripts import (
        compile_geotransport_stage24_public_reach_geometry_gates as gates,
    )

    report = gates.compile_report()

    assert report["all_gates_passed"] is True
    assert len(report["gates"]) == 20
    assert all(report["gates"].values())
    assert report["decision"][
        "bridge_location_candidate_temporally_supported"
    ] is True
    assert report["decision"]["method_spatial_transfer_supported"] is False
    assert report["decision"]["reach_wide_fixed_geometry_admitted"] is False
    assert report["decision"]["runtime_hydraulic_geometry_admitted"] is False
    assert report["decision"]["operator_admitted"] is False
