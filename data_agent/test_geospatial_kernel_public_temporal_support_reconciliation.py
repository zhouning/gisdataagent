from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    public_temporal_support_reconciliation as evidence,
)


def _ledger():
    return evidence.compile_public_temporal_support_reconciliation()


def test_stage33_verifies_operator_plan_and_nine_public_artifacts():
    ledger = _ledger()

    assert ledger.operator_artifact["sha256"] == (
        "62bda56dedfb65995556aa4964ea220c4ea8a9976738694f2e784cd664b360d1"
    )
    assert ledger.acquisition_plan_artifact["sha256"] == (
        "55f2618d7d6508a0b6e0ef4556d934514f8f42ea20a208e4272d53e27d0f76b8"
    )
    assert len(ledger.source_artifacts) == 9
    assert all(
        len(str(value["sha256"])) == 64
        and int(value["size_bytes"]) > 0
        for value in ledger.source_artifacts
    )


def test_stage33_admits_linear_referenced_source_to_target_path():
    path = _ledger().path_binding

    assert path.feature_ids[0] == 18421761
    assert path.feature_ids[-1] == 18421703
    assert len(path.feature_ids) == 24
    assert path.full_geometry_length_m == pytest.approx(
        25351.899363776225
    )
    assert path.linear_referenced_length_m == pytest.approx(
        25144.549659527587
    )
    assert path.source_snap_distance_m == pytest.approx(
        16.742899119724644
    )
    assert path.target_snap_distance_m == pytest.approx(
        54.3838523478399
    )
    assert path.maximum_connection_gap_m == 0.0
    assert path.physics_path_extra_upstream_length_m == pytest.approx(
        28.209821168027702
    )
    assert path.physics_path_suffix_matches is True
    assert path.spatial_path_admitted is True
    assert path.require_spatial_path() == path.feature_ids


def test_stage33_preserves_stage32_local_sets_without_inventing_common_set():
    ledger = _ledger()

    assert ledger.stage32_event_support_sets == (
        (5, 6, 7),
        (6, 7),
        (7,),
        (),
    )
    assert ledger.stage32_detectable_relation_count == 3
    assert ledger.reconciliation.empirical.supported_hours == (5, 6, 7)
    assert ledger.reconciliation.all_event_common_empirical_support is False


def test_stage33_compiles_three_typed_physics_support_candidates():
    values = [
        value.physics for value in _ledger().reconciliation.compatibilities
    ]

    assert [value.quantity for value in values] == [
        "gravity_wave_time",
        "manning_kinematic_centroid_time",
        "advective_residence_time",
    ]
    intervals = [
        (value.lower_hours, value.central_hours, value.upper_hours)
        for value in values
    ]
    expected = [
        (
            1.1636556564598701,
            1.2017945393393767,
            1.2434852223876611,
        ),
        (
            15.582960350766653,
            16.144952135344774,
            16.802247333679684,
        ),
        (
            18.329537115520722,
            22.90774300295677,
            24.170511891777153,
        ),
    ]
    assert all(
        actual == pytest.approx(reference)
        for actual, reference in zip(intervals, expected, strict=True)
    )
    assert all(value.state_dependent for value in values)
    assert all(value.outcome_calibrated is False for value in values)
    assert all(value.admitted_as_physical_time is False for value in values)


def test_stage33_finds_no_numerical_temporal_overlap():
    values = _ledger().reconciliation.compatibilities

    assert [value.overlapping_empirical_hours for value in values] == [
        (),
        (),
        (),
    ]
    assert [value.numerical_overlap for value in values] == [
        False,
        False,
        False,
    ]
    assert [value.minimum_separation_hours for value in values] == (
        pytest.approx(
            [
                3.756514777612339,
                8.582960350766653,
                11.329537115520722,
            ]
        )
    )


def test_stage33_refuses_physics_consistency_and_runtime_transition():
    ledger = _ledger()

    assert ledger.reconciliation.physics_consistency_admitted is False
    with pytest.raises(ValueError, match="physics_consistency_unadmitted"):
        ledger.require_physics_consistent_support()
    with pytest.raises(ValueError, match="runtime_transition_unadmitted"):
        ledger.promote_to_runtime_transition()


def test_stage33_decision_separates_spatial_path_from_temporal_admission():
    report = _ledger().as_dict()
    decision = report["decision"]

    assert decision["spatial_path_admitted"] is True
    assert decision["physics_support_candidates_admitted"] is True
    assert decision["any_numerical_temporal_overlap"] is False
    assert decision["physics_consistency_admitted"] is False
    assert decision["runtime_transition_admitted"] is False


def test_compiled_stage33_report_admits_path_and_rejects_temporal_support():
    from scripts import (
        compile_geotransport_stage33_temporal_support_gates as gates,
    )

    report = gates.compile_report()

    assert report["all_gates_passed"] is True
    assert len(report["gates"]) == 33
    assert all(report["gates"].values())
    assert report["status"] == (
        "spatial_path_admitted_temporal_reconciliation_rejected"
    )
    assert report["decision"]["spatial_path_admitted"] is True
    assert report["decision"]["physics_consistency_admitted"] is False
    assert report["decision"]["runtime_transition_admitted"] is False
