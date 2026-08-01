from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    public_temporal_response_semantics as evidence,
)


def _ledger():
    return evidence.compile_public_temporal_response_semantics()


def test_stage34_verifies_operator_plan_document_and_nine_sources():
    ledger = _ledger()

    assert ledger.operator_artifact["sha256"] == (
        "8632158a2ecfe194f6419fc6ceab5f7eca7ef958cc694a8719742b97ffd90bdd"
    )
    assert ledger.acquisition_plan_artifact["sha256"] == (
        "86b646f133e705a226afbc079bd1d4d02f814fc0f6b7f05be589c77413f8c043"
    )
    assert ledger.acquisition_manifest_artifact["sha256"] == (
        "82fbf0460344331f25f567b19665ce3883699f8283ed856820fb0fa49901749d"
    )
    assert len(ledger.source_artifacts) == 9
    assert all(
        len(str(value["sha256"])) == 64
        and int(value["size_bytes"]) > 0
        for value in ledger.source_artifacts
    )


def test_stage34_document_admits_cwms_composite_end_of_period_semantics():
    findings = _ledger().document_findings

    assert findings["instantaneous_is_not_composite"] is True
    assert findings["composite_default_timestamp_position"] == "end"
    assert findings["one_hour_duration_is_composite_window_seconds"] == 3600
    assert findings["cwms_storage_time_basis"] == "UTC"


def test_stage34_compiles_distinct_source_and_target_observation_statistics():
    ledger = _ledger()
    source = ledger.source_field
    target = ledger.target_field

    assert source.statistic == "interval_average"
    assert source.temporal_support.kind == "interval_mean"
    assert source.temporal_support.evidence_level == "authoritative"
    assert target.statistic == "instantaneous_sample_mean"
    assert target.temporal_support.kind == "interval_sample_mean"
    assert target.temporal_support.evidence_level == "derived"
    assert target.native_sampling_interval_seconds == 1800.0
    assert target.native_samples_per_compiled_support == 2


def test_stage34_preserves_real_stage32_observation_support_without_fill():
    ledger = _ledger()

    assert ledger.stage32_downstream_complete_hours == (84, 84, 77, 84)
    assert ledger.stage32_downstream_missing_hours == (0, 0, 7, 0)
    report = ledger.as_dict()["stage32_observation_support"]
    assert report["missing_values_filled"] is False
    assert report["all_compiled_samples_approved"] is True


def test_stage34_admits_only_interval_end_label_shift_grid():
    ledger = _ledger()

    assert ledger.require_label_shift_grid_seconds() == 3600.0
    assert ledger.reconciliation.label_shift_diagnostic_admitted is True
    with pytest.raises(ValueError, match="actuation_instant_unadmitted"):
        ledger.require_release_actuation_instant()
    with pytest.raises(ValueError, match="continuous_interval_average_unadmitted"):
        ledger.require_target_continuous_interval_average()
    with pytest.raises(
        ValueError, match="physical_observation_equivalence_unadmitted"
    ):
        ledger.require_physical_observation_equivalence()


def test_stage34_distinguishes_all_three_physics_process_functionals():
    values = _ledger().reconciliation.compatibilities

    assert [value.candidate.carrier for value in values] == [
        "hydraulic_disturbance",
        "discharge_perturbation",
        "water_mass",
    ]
    assert [value.candidate.target_response_functional for value in values] == [
        "first_signal_arrival",
        "response_centroid",
        "material_exit_centroid",
    ]
    assert all(value.same_spatial_path for value in values)
    assert all(value.numerical_overlap is False for value in values)


def test_stage34_same_path_and_hours_do_not_admit_process_substitution():
    values = _ledger().reconciliation.compatibilities

    for value in values:
        assert value.semantic_equivalence_admitted is False
        assert value.physical_response_comparison_admitted is False
        assert value.rejection_reasons == (
            "transport_carrier_mismatch",
            "source_event_marker_mismatch",
            "target_response_functional_mismatch",
            "candidate_physical_response_time_unadmitted",
            "numerical_support_disjoint",
        )


def test_stage34_physical_and_runtime_promotions_fail_closed():
    ledger = _ledger()

    with pytest.raises(ValueError, match="physical_time_unadmitted"):
        ledger.require_physical_response_time()
    with pytest.raises(ValueError, match="runtime_transition_unadmitted"):
        ledger.promote_to_runtime_transition()


def test_stage34_decision_admits_semantics_not_physical_transition():
    decision = _ledger().as_dict()["decision"]

    assert decision["public_temporal_semantics_evidence_admitted"] is True
    assert decision["interval_end_label_shift_diagnostic_admitted"] is True
    assert decision["label_shift_grid_seconds"] == 3600.0
    assert decision["release_actuation_instant_admitted"] is False
    assert decision["target_continuous_interval_average_admitted"] is False
    assert decision["physical_observation_equivalence_admitted"] is False
    assert decision["physical_response_time_admitted"] is False
    assert decision["runtime_transition_admitted"] is False


def test_compiled_stage34_report_admits_label_grid_and_rejects_physics():
    from scripts import compile_geotransport_stage34_temporal_semantics_gates as gates

    report = gates.compile_report()

    assert report["all_gates_passed"] is True
    assert len(report["gates"]) == 34
    assert all(report["gates"].values())
    assert report["status"] == (
        "interval_label_shift_admitted_"
        "physical_response_semantics_rejected"
    )
    assert report["decision"][
        "interval_end_label_shift_diagnostic_admitted"
    ] is True
    assert report["decision"]["physical_response_time_admitted"] is False
