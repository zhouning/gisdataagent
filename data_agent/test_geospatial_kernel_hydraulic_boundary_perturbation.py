from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    hydraulic_boundary_perturbation as perturbation,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEVELOPMENT_PROBE = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "stage36_center_hill_hydraulic_boundary_events/development/raw/"
    "cwms_tailwater_stage_20221222T1900Z_20221225T1900Z.json"
)


def test_sustained_stage_rise_admits_blind_target_test_support():
    values = tuple([100.0] * 48 + [101.0] * 97)

    report = perturbation.compile_observed_hydraulic_boundary_perturbation(
        values
    )

    assert report.signed_primary_change_m == 1.0
    assert report.direction == "rise"
    assert report.excursion_support_intervals == 24
    assert report.normalized_excursion_intervals == 24.0
    assert report.blind_target_test_admissible is True
    assert report.rejection_reasons == ()
    report.require_blind_target_test_support()


def test_sustained_stage_fall_preserves_direction_without_action_semantics():
    values = tuple([101.0] * 48 + [100.0] * 97)

    report = perturbation.compile_observed_hydraulic_boundary_perturbation(
        values
    )

    assert report.signed_primary_change_m == -1.0
    assert report.direction == "fall"
    assert report.perturbation_sign == -1
    assert report.blind_target_test_admissible is True
    assert report.as_dict()["release_action_admitted"] is False


def test_single_sample_spike_is_rejected_before_target_observations():
    values = tuple([100.0] * 48 + [101.0] + [100.0] * 96)

    report = perturbation.compile_observed_hydraulic_boundary_perturbation(
        values
    )

    assert report.excursion_support_intervals == 1
    assert report.normalized_excursion_intervals == 1.0
    assert report.blind_target_test_admissible is False
    assert "excursion_support_below_six_half_hours" in report.rejection_reasons
    with pytest.raises(ValueError, match="perturbation_not_admissible"):
        report.require_blind_target_test_support()


def test_small_stable_change_is_rejected_by_magnitude_and_variance():
    values = tuple([100.0] * 48 + [100.1] * 97)

    report = perturbation.compile_observed_hydraulic_boundary_perturbation(
        values
    )

    assert report.blind_target_test_admissible is False
    assert "absolute_primary_change_below_0_25_m" in report.rejection_reasons
    assert (
        "post_event_standard_deviation_below_0_10_m"
        in report.rejection_reasons
    )


def test_approved_development_probe_supports_frozen_source_gate():
    payload = json.loads(DEVELOPMENT_PROBE.read_bytes())
    values = tuple(float(row[1]) for row in payload["values"])

    report = perturbation.compile_observed_hydraulic_boundary_perturbation(
        values
    )

    assert report.signed_primary_change_m == pytest.approx(0.329184)
    assert report.direction == "rise"
    assert report.blind_target_test_admissible is True
    assert report.absolute_primary_change_m >= 0.25
    assert report.excursion_support_intervals >= 6


def test_source_gate_refuses_semantic_and_runtime_promotions():
    report = perturbation.compile_observed_hydraulic_boundary_perturbation(
        tuple([100.0] * 48 + [101.0] * 97)
    )
    calls = (
        (report.require_release_action, "observation_is_not_release_action"),
        (
            report.require_release_discharge,
            "elevation_is_not_release_discharge",
        ),
        (
            report.require_observed_downstream_response,
            "input_support_is_not_downstream_response",
        ),
        (
            report.require_physical_travel_time,
            "source_marker_is_not_physical_travel_time",
        ),
        (
            report.promote_to_runtime_transition,
            "runtime_transition_unadmitted",
        ),
    )
    for call, message in calls:
        with pytest.raises(ValueError, match=message):
            call()


def test_source_gate_requires_exact_finite_window_and_nonzero_change():
    with pytest.raises(ValueError, match="145_finite"):
        perturbation.compile_observed_hydraulic_boundary_perturbation(
            (100.0,) * 144
        )
    invalid = [100.0] * 145
    invalid[5] = math.nan
    with pytest.raises(ValueError, match="145_finite"):
        perturbation.compile_observed_hydraulic_boundary_perturbation(
            tuple(invalid)
        )
    with pytest.raises(ValueError, match="nonzero_primary_change"):
        perturbation.compile_observed_hydraulic_boundary_perturbation(
            (100.0,) * 145
        )


def test_target_functional_detects_first_three_sample_departure():
    values: list[float | None] = [100.0] * 97
    values[51:54] = [108.0, 109.0, 108.0]

    report = perturbation.compile_first_persistent_downstream_departure(
        tuple(values)
    )

    assert report.baseline_median_m3s == 100.0
    assert report.departure_threshold_m3s == 5.0
    assert report.first_departure_offset_minutes == 90
    assert report.direction == "increase"
    assert report.detected is True


def test_target_functional_rejects_spike_and_breaks_run_at_missing_sample():
    values: list[float | None] = [100.0] * 97
    values[49:53] = [108.0, None, 108.0, 108.0]

    report = perturbation.compile_first_persistent_downstream_departure(
        tuple(values)
    )

    assert report.detected is False
    assert report.search_missing_sample_count == 1
    assert report.as_dict()["missing_sample_policy"] == (
        "break_run_without_filling"
    )


def test_target_functional_refuses_causal_and_physical_promotions():
    report = perturbation.compile_first_persistent_downstream_departure(
        tuple([100.0] * 97)
    )

    calls = (
        (report.require_causal_release_response, "not_causal_release_response"),
        (report.require_physical_first_arrival, "not_physical_first_arrival"),
        (report.require_physical_travel_time, "not_physical_travel_time"),
    )
    for call, message in calls:
        with pytest.raises(ValueError, match=message):
            call()


def test_target_functional_requires_baseline_support_and_finite_values():
    values: list[float | None] = [100.0] * 97
    values[:7] = [None] * 7
    with pytest.raises(ValueError, match="baseline_support_insufficient"):
        perturbation.compile_first_persistent_downstream_departure(tuple(values))
    invalid: list[float | None] = [100.0] * 97
    invalid[50] = math.inf
    with pytest.raises(ValueError, match="finite_or_missing"):
        perturbation.compile_first_persistent_downstream_departure(tuple(invalid))
