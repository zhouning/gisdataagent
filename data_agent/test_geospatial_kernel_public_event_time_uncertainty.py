from __future__ import annotations

import json

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    public_event_time_uncertainty as evidence,
)


def _ledger():
    return evidence.compile_public_event_time_uncertainty()


def test_stage35_verifies_protocol_operator_and_stage34_artifacts():
    value = _ledger()

    assert value.operator_artifact["sha256"] == (
        "660d596341eea9a54c96332834e58d1418953cc4838589ac4826aba35ce4600d"
    )
    assert value.stage34_ledger_artifact["sha256"] == (
        "45b5a51d4ec0500e9288dd97b1a41a9632c9c95d45c7a959a65ffc4cab8a101c"
    )
    assert value.stage34_gates_artifact["sha256"] == (
        "482024d6517f1da7a4f5cd4ee793515e97d7eb39269db03a343f90c3c273fba7"
    )


def test_stage35_compiles_one_hour_end_labeled_support_uncertainty():
    support = _ledger().support_uncertainty

    assert support.source_duration_hours == 1.0
    assert support.target_duration_hours == 1.0
    assert support.source_event_offset_hours == (-1.0, 0.0)
    assert support.target_event_offset_hours == (-1.0, 0.0)
    assert support.conservative_closure_used is True


def test_stage35_binds_all_four_real_stage32_event_supports():
    value = _ledger()

    assert value.event_ids == evidence.EVENT_IDS
    assert value.event_label_shift_sets == (
        (5, 6, 7),
        (6, 7),
        (7,),
        (),
    )


def test_stage35_dilates_discrete_lags_without_filling_empty_event():
    reconciliation = _ledger().reconciliation

    assert [
        tuple((item.lower_hours, item.upper_hours) for item in value.intervals)
        for value in reconciliation.event_envelopes
    ] == [((4.0, 8.0),), ((5.0, 8.0),), ((6.0, 8.0),), ()]
    assert reconciliation.event_envelopes[-1].nonempty is False


def test_stage35_empty_event_blocks_cross_event_delay_intersection():
    reconciliation = _ledger().reconciliation

    assert reconciliation.all_events_have_nonempty_support is False
    assert reconciliation.common_event_delay_intervals == ()
    with pytest.raises(ValueError, match="common_delay_unadmitted"):
        reconciliation.require_common_event_delay_intervals()


def test_stage35_compares_maximum_union_envelope_to_three_physics_supports():
    values = _ledger().reconciliation.compatibilities

    assert [value.physics_quantity for value in values] == [
        "gravity_wave_time",
        "manning_kinematic_centroid_time",
        "advective_residence_time",
    ]
    assert [value.minimum_separation_hours for value in values] == pytest.approx(
        [
            2.756514777612339,
            7.582960350766653,
            10.329537115520722,
        ]
    )


def test_stage35_uncertainty_does_not_create_numerical_or_semantic_overlap():
    values = _ledger().reconciliation.compatibilities

    assert all(value.same_spatial_path for value in values)
    assert all(not value.measurement_support_overlap for value in values)
    assert all(not value.semantic_equivalence_admitted for value in values)
    assert all(not value.physical_comparison_admitted for value in values)


def test_stage35_physical_and_runtime_promotions_fail_closed():
    value = _ledger()

    with pytest.raises(ValueError, match="physical_response_unadmitted"):
        value.require_physical_response_time()
    with pytest.raises(ValueError, match="runtime_transition_unadmitted"):
        value.promote_to_runtime_transition()


def test_stage35_decision_admits_only_uncertainty_propagation():
    report = _ledger().as_dict()
    decision = report["decision"]

    assert decision == {
        "hash_bound_prior_evidence_verified": True,
        "event_time_uncertainty_propagation_admitted": True,
        "all_events_have_nonempty_support": False,
        "common_event_delay_intervals_admitted": False,
        "any_measurement_support_physics_overlap": False,
        "semantic_equivalence_admitted": False,
        "physical_response_time_admitted": False,
        "runtime_transition_admitted": False,
    }
    assert report["claim_boundary"][
        "uncertainty_envelope_is_physical_delay"
    ] is False


def test_stage35_protocol_tampering_fails_closed(tmp_path):
    source = evidence.DEFAULT_SOURCE_ROOT / "protocol.json"
    protocol = json.loads(source.read_bytes())
    protocol["data_boundary"]["network_requests_allowed"] = True
    (tmp_path / "protocol.json").write_text(
        json.dumps(protocol), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="protocol_data_boundary_invalid"):
        evidence.compile_public_event_time_uncertainty(source_root=tmp_path)


def test_compiled_stage35_report_passes_all_thirty_five_gates():
    from scripts import (
        compile_geotransport_stage35_event_time_uncertainty_gates as gates,
    )

    report = gates.compile_report(ledger=_ledger())

    assert report["status"] == gates.STATUS
    assert len(report["gates"]) == 35
    assert sum(report["gates"].values()) == 35
    assert report["all_gates_passed"] is True
