from __future__ import annotations

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    hydraulic_boundary_falsification as falsification,
)


def _values(*, baseline: float = 100.0) -> list[float | None]:
    return [baseline] * 97


def test_falsification_reproduces_a_frozen_positive_gate():
    values = _values()
    values[49:52] = [107.0, 108.0, 109.0]

    report = falsification.compile_persistent_departure_falsification(
        tuple(values)
    )

    assert report.target_report.departure_threshold_m3s == 5.0
    assert report.frozen_gate_detected is True
    assert report.strongest_persistent_start_offset_minutes == 30
    assert report.strongest_persistent_direction == "increase"
    assert report.strongest_persistent_magnitude_m3s == 7.0
    assert report.strongest_persistent_threshold_ratio == 1.4
    assert report.failure_mode == "frozen_gate_passed"


def test_falsification_quantifies_a_below_threshold_persistent_run():
    values = _values()
    values[51:54] = [103.0, 104.0, 105.0]

    report = falsification.compile_persistent_departure_falsification(
        tuple(values)
    )

    assert report.frozen_gate_detected is False
    assert report.strongest_persistent_start_offset_minutes == 90
    assert report.strongest_persistent_direction == "increase"
    assert report.strongest_persistent_magnitude_m3s == 3.0
    assert report.strongest_persistent_threshold_ratio == 0.6
    assert report.persistent_threshold_shortfall_m3s == 2.0
    assert report.failure_mode == "persistent_departure_below_frozen_threshold"


def test_falsification_preserves_missing_samples_that_break_persistence():
    values = _values()
    for index in range(49, 73, 2):
        values[index] = None

    report = falsification.compile_persistent_departure_falsification(
        tuple(values)
    )

    assert report.target_report.search_missing_sample_count == 12
    assert report.strongest_persistent_magnitude_m3s is None
    assert report.failure_mode == "no_complete_same_direction_triplet"


def test_falsification_reports_the_dominant_frozen_threshold_component():
    values = [100.0 + float(index % 2) * 20.0 for index in range(97)]

    report = falsification.compile_persistent_departure_falsification(
        tuple(values)
    )

    assert report.robust_mad_threshold_component_m3s > 5.0
    assert report.dominant_threshold_component == "robust_mad"


def test_falsification_requires_original_baseline_support():
    values = _values()
    values[:7] = [None] * 7

    with pytest.raises(ValueError, match="baseline_support_insufficient"):
        falsification.compile_persistent_departure_falsification(tuple(values))


def test_falsification_refuses_new_detector_physical_and_runtime_claims():
    report = falsification.compile_persistent_departure_falsification(
        tuple(_values())
    )
    calls = (
        (report.require_alternative_detector, "alternative_detector"),
        (report.require_causal_response, "causal_response"),
        (report.require_physical_response_time, "physical_time"),
        (report.promote_to_runtime_operator, "runtime_operator_unadmitted"),
    )
    for call, message in calls:
        with pytest.raises(ValueError, match=message):
            call()
