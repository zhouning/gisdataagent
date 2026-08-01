from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    public_hydraulic_boundary_falsification as evidence,
)


def _ledger():
    return evidence.compile_public_hydraulic_boundary_falsification()


def test_stage37_reproduces_and_binds_stage36_negative_evidence():
    ledger = _ledger()

    assert ledger.stage36_ledger_artifact["sha256"] == (
        "81d981243976d147c2a6b2fba78bef2f478095c21fde118d24f57eab88250689"
    )
    assert ledger.stage36_gates_artifact["sha256"] == (
        "a48cdfbe0d808dd1e409c4676f75caf92665cef3d7a037c89bde611d8f752e58"
    )
    assert len(ledger.attribution_operator_artifact["sha256"]) == 64


def test_stage37_separates_support_and_frozen_threshold_failures():
    ledger = _ledger()

    assert [value.failure_class for value in ledger.events] == [
        evidence.SUPPORT_FAILURE,
        evidence.THRESHOLD_FAILURE,
        evidence.THRESHOLD_FAILURE,
        evidence.THRESHOLD_FAILURE,
    ]
    assert ledger.measurement_support_failure_count == 1
    assert ledger.frozen_threshold_failure_count == 3


def test_stage37_preserves_stage36_grid_support_without_fill():
    events = _ledger().events

    assert [value.grid_real_sample_count for value in events] == [48, 97, 97, 97]
    assert [value.grid_missing_sample_count for value in events] == [49, 0, 0, 0]
    assert [value.baseline_real_sample_count for value in events] == [18, 36, 36, 36]
    assert events[0].attribution is None


def test_stage37_attributes_all_assessable_failures_to_frozen_gate_margin():
    attributions = tuple(
        value.attribution
        for value in _ledger().events
        if value.attribution is not None
    )

    assert len(attributions) == 3
    assert all(
        value.dominant_threshold_component == "robust_mad"
        for value in attributions
    )
    assert all(not value.frozen_gate_detected for value in attributions)
    assert all(
        value.failure_mode == "persistent_departure_below_frozen_threshold"
        for value in attributions
    )
    assert [value.direction_concordant for value in _ledger().events] == [
        None,
        False,
        False,
        False,
    ]
    assert _ledger().direction_concordant_event_count == 0
    assert _ledger().single_sample_threshold_crossing_count == 0
    assert _ledger().persistence_only_failure_count == 0


def test_stage37_decision_is_diagnostic_only_and_preserves_rejection():
    decision = _ledger().as_dict()["decision"]

    assert decision == {
        "stage36_negative_result_preserved": True,
        "failure_attribution_admitted": True,
        "measurement_support_failure_count": 1,
        "frozen_threshold_failure_count": 3,
        "any_assessable_event_detected": False,
        "directional_response_support_admitted": False,
        "alternative_detector_admitted": False,
        "causal_response_admitted": False,
        "physical_response_time_admitted": False,
        "runtime_operator_admitted": False,
    }


def test_stage37_refuses_alternative_detector_physical_and_runtime_promotions():
    ledger = _ledger()
    calls = (
        (ledger.require_alternative_detector, "alternative_detector"),
        (ledger.require_causal_response, "causal_response"),
        (ledger.require_physical_response_time, "physical_time"),
        (ledger.promote_to_runtime_operator, "runtime_operator_unadmitted"),
    )
    for call, message in calls:
        with pytest.raises(ValueError, match=message):
            call()


def test_compiled_stage37_report_passes_with_no_alternative_admission():
    from scripts import (
        compile_geotransport_stage37_hydraulic_boundary_falsification_gates as gates,
    )

    report = gates.compile_report(ledger=_ledger())

    assert report["status"] == gates.STATUS
    assert len(report["gates"]) == 31
    assert sum(report["gates"].values()) == 31
    assert report["all_gates_passed"] is True
    assert report["decision"]["failure_attribution_admitted"] is True
    assert report["decision"]["alternative_detector_admitted"] is False
