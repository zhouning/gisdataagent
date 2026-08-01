from __future__ import annotations

from datetime import datetime

import pytest

from scripts import compile_geotransport_stage41_component_discharge_events as compile_stage41


@pytest.fixture(scope="module")
def compiled():
    return compile_stage41.compile_selection()


def test_stage41_derives_complete_synchronized_total_without_fill(compiled):
    assert compiled.total_value_count == 43_825
    assert compiled.synchronized_total_derivation_admissible is True
    assert compiled.support.synchronized_support_complete is True
    assert compiled.as_dict()["total_derivation"]["missing_value_policy"] == (
        "reject_without_filling"
    )


def test_stage41_preserves_all_four_source_event_strata(compiled):
    assert compiled.candidate_counts_by_stratum == (
        ("high_increase", 51),
        ("high_decrease", 77),
        ("low_increase", 1_262),
        ("low_decrease", 1_157),
    )
    assert len(compiled.candidates) == 2_547


def test_stage41_selects_exact_independent_events(compiled):
    assert [value["step_time_utc"] for value in compiled.selected_events] == [
        "2025-04-15T16:00:00Z",
        "2023-03-11T20:00:00Z",
        "2021-01-12T16:00:00Z",
        "2021-07-27T03:00:00Z",
    ]
    event_times = [
        datetime.fromisoformat(str(value["step_time_utc"]).replace("Z", "+00:00"))
        for value in compiled.selected_events
    ]
    assert all(
        abs(left - right).days >= 180
        for index, left in enumerate(event_times)
        for right in event_times[index + 1 :]
    )


def test_stage41_selected_events_pass_frozen_excitation_gate(compiled):
    assert compiled.total_discharge_events_admissible is True
    assert all(
        value["release_excitation_identifiability"][
            "blind_response_test_admissible"
        ]
        is True
        for value in compiled.selected_events
    )


def test_stage41_component_specific_gate_finds_only_turbine_support(compiled):
    assert compiled.component_gate_candidate_counts == (
        ("orifice", 0),
        ("sluice", 0),
        ("spillway", 0),
        ("turbine", 2_542),
    )
    assert compiled.selected_dominant_components == ("turbine",) * 4
    assert compiled.non_turbine_component_contrast_admissible is False


def test_stage41_selected_steps_sum_exact_component_steps(compiled):
    for event in compiled.selected_events:
        assert sum(event["component_signed_steps_m3s"].values()) == pytest.approx(
            event["signed_total_step_m3s"], abs=1e-12
        )
        assert event["active_step_components"] == ["turbine"]


def test_stage41_quality_codes_are_preserved_without_approval_semantics(compiled):
    low_decrease = compiled.selected_events[-1]

    assert low_decrease["component_quality_codes_in_window"]["turbine"] == [
        -2_147_478_653,
        0,
    ]
    assert low_decrease["quality_codes_interpreted_as_approval"] is False


def test_stage41_typed_refusals_block_unsupported_promotions(compiled):
    calls = (
        (compiled.require_quality_approval_semantics, "approval_semantics"),
        (compiled.require_non_turbine_component_contrast, "contrast"),
        (compiled.require_gate_command, "gate_command"),
        (compiled.require_human_action, "human_action"),
        (compiled.require_observed_downstream_response, "downstream_response"),
        (compiled.require_causal_intervention, "causal_intervention"),
        (compiled.require_physical_response_time, "physical_response_time"),
        (compiled.promote_to_runtime_operator, "runtime_operator"),
    )
    for call, message in calls:
        with pytest.raises(ValueError, match=message):
            call()
