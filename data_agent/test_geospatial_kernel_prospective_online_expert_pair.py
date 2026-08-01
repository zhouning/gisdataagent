from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from data_agent.uwm.geospatial_kernel_v2.physical_online_expert_blend import (
    PhysicalOnlineExpertBlender,
)
from data_agent.uwm.geospatial_kernel_v2.prospective_online_expert_pair import (
    ProspectiveOnlineExpertMaturedFeedback,
    ProspectiveOnlineExpertMaturedSample,
    ProspectiveOnlineExpertPairRunner,
    ProspectiveOnlineExpertPairState,
    advance_prospective_online_expert_pair_state,
    algorithm_contract,
)
from scripts.evaluate_geospatial_kernel_online_expert_traditional_baselines import (
    _alternative_gate,
)

START = datetime(2026, 7, 31, tzinfo=UTC)


def _matured_samples(count: int = 24) -> tuple[ProspectiveOnlineExpertMaturedSample, ...]:
    return tuple(
        ProspectiveOnlineExpertMaturedSample(
            sample_id=f"sample-{index}",
            matured_at=START + timedelta(hours=index),
            alternative_delta_m3s=20.0,
            baseline_target_error_m3s=15.0,
            coefficient_gate_shadow_squared_error_m6s2=0.0,
        )
        for index in range(count)
    )


def _state(
    samples: tuple[ProspectiveOnlineExpertMaturedSample, ...],
) -> ProspectiveOnlineExpertPairState:
    return ProspectiveOnlineExpertPairState(
        system_id="center_hill",
        state_as_of=START + timedelta(hours=24),
        config=ProspectiveOnlineExpertPairState.empty(
            system_id="center_hill",
            state_as_of=START,
        ).config,
        samples_by_horizon=(samples, (), (), ()),
    )


def test_empty_state_emits_both_physical_fallbacks() -> None:
    state = ProspectiveOnlineExpertPairState.empty(
        system_id="j_percy_priest",
        state_as_of=START,
    )
    step = ProspectiveOnlineExpertPairRunner(state).predict(
        forecast_horizon_hours=1,
        baseline_prediction_m3s=100.0,
        alternative_prediction_m3s=120.0,
        issue_time=START,
    )

    assert step.primary_candidate.blended_prediction_m3s == 100.0
    assert step.primary_candidate.application_gate_passed is False
    assert step.traditional_baseline.selected_prediction_m3s == 100.0
    assert step.traditional_baseline.alternative_selected is False
    assert step.as_dict()["current_or_future_target_used_for_prediction"] is False


def test_shared_matured_state_activates_v5_and_traditional_selector() -> None:
    step = ProspectiveOnlineExpertPairRunner(_state(_matured_samples())).predict(
        forecast_horizon_hours=1,
        baseline_prediction_m3s=100.0,
        alternative_prediction_m3s=120.0,
        issue_time=START + timedelta(hours=25),
    )

    assert step.primary_candidate.raw_weight == pytest.approx(0.75)
    assert step.primary_candidate.application_gate_passed is True
    assert step.primary_candidate.blended_prediction_m3s == pytest.approx(115.0)
    assert step.traditional_baseline.alternative_selected is True
    assert step.traditional_baseline.selected_prediction_m3s == 120.0


def test_prospective_v5_path_matches_existing_v5_implementation() -> None:
    blender = PhysicalOnlineExpertBlender()
    for index in range(24):
        update_time = START + timedelta(hours=index)
        blender.update(
            sample_id=f"sample-{index}",
            forecast_horizon_hours=1,
            baseline_prediction_m3s=100.0,
            alternative_prediction_m3s=120.0,
            candidate_shadow_prediction_m3s=115.0,
            candidate_evidence_gate_passed=True,
            observed_target_m3s=115.0,
            target_observation_available_at=update_time,
            update_time=update_time,
        )
    issue_time = START + timedelta(hours=25)
    existing = blender.predict(
        forecast_horizon_hours=1,
        baseline_prediction_m3s=100.0,
        alternative_prediction_m3s=120.0,
        issue_time=issue_time,
    )
    prospective = (
        ProspectiveOnlineExpertPairRunner(_state(_matured_samples()))
        .predict(
            forecast_horizon_hours=1,
            baseline_prediction_m3s=100.0,
            alternative_prediction_m3s=120.0,
            issue_time=issue_time,
        )
        .primary_candidate
    )

    assert prospective == existing


def test_prospective_selector_matches_historical_comparator_formula() -> None:
    samples = _matured_samples()
    state = _state(samples)
    step = (
        ProspectiveOnlineExpertPairRunner(state)
        .predict(
            forecast_horizon_hours=1,
            baseline_prediction_m3s=100.0,
            alternative_prediction_m3s=120.0,
            issue_time=START + timedelta(hours=25),
        )
        .traditional_baseline
    )
    losses = [
        (
            sample.baseline_target_error_m3s**2,
            (sample.baseline_target_error_m3s - sample.alternative_delta_m3s) ** 2,
        )
        for sample in samples
    ]
    expected = _alternative_gate(losses, config=state.config)

    assert step.alternative_selected is expected[0]
    assert step.baseline_minus_alternative_mean_squared_error_m6s2 == expected[1]
    assert step.improvement_standard_error_m6s2 == expected[2]
    assert step.improvement_threshold_m6s2 == expected[3]


def test_state_round_trip_preserves_the_frozen_prediction() -> None:
    state = _state(_matured_samples())
    restored = ProspectiveOnlineExpertPairState.from_dict(state.as_dict())

    assert restored == state
    assert restored.sample_count_by_horizon() == {1: 24, 3: 0, 6: 0, 12: 0}


def test_state_rejects_future_matured_sample_and_prediction_rejects_old_issue() -> None:
    future = ProspectiveOnlineExpertMaturedSample(
        sample_id="future",
        matured_at=START + timedelta(hours=25),
        alternative_delta_m3s=1.0,
        baseline_target_error_m3s=1.0,
        coefficient_gate_shadow_squared_error_m6s2=None,
    )
    with pytest.raises(ValueError, match="state_invalid"):
        _state((future,))

    runner = ProspectiveOnlineExpertPairRunner(_state(_matured_samples()))
    with pytest.raises(ValueError, match="forecast_invalid"):
        runner.predict(
            forecast_horizon_hours=1,
            baseline_prediction_m3s=100.0,
            alternative_prediction_m3s=120.0,
            issue_time=START,
        )


def test_prediction_api_and_contract_do_not_accept_outcomes() -> None:
    parameters = set(inspect.signature(ProspectiveOnlineExpertPairRunner.predict).parameters)
    contract = algorithm_contract()

    assert not any("outcome" in value or "observ" in value for value in parameters)
    assert contract["primary_candidate"] == "physical_online_expert_blend_v5"
    assert contract["traditional_baseline"] == "evidence_gated_follow_the_leader"
    assert contract["prediction_api_accepts_observation_or_outcome"] is False
    assert contract["primary_candidate_admitted"] is False


def test_matured_feedback_advances_state_without_retaining_signed_observation() -> None:
    state = ProspectiveOnlineExpertPairState.empty(
        system_id="j_percy_priest",
        state_as_of=START,
    )
    available_at = START + timedelta(hours=2)
    feedback = ProspectiveOnlineExpertMaturedFeedback(
        sample_id="signed-feedback",
        forecast_horizon_hours=1,
        target_support_end=START + timedelta(hours=1),
        observed_discharge_m3s=-5.0,
        observation_available_at=available_at,
        baseline_prediction_m3s=100.0,
        alternative_prediction_m3s=120.0,
        coefficient_gate_shadow_prediction_m3s=100.0,
        coefficient_gate_passed=False,
    )

    updated = advance_prospective_online_expert_pair_state(
        state,
        (feedback,),
        update_time=available_at,
    )
    sample = updated.samples_for_horizon(1)[0]
    encoded = updated.as_dict()

    assert sample.alternative_delta_m3s == 20.0
    assert sample.baseline_target_error_m3s == -105.0
    assert sample.coefficient_gate_shadow_squared_error_m6s2 is None
    assert encoded["raw_observations_included"] is False
    assert "observed_discharge_m3s" not in str(encoded)


def test_matured_feedback_rejects_future_and_duplicate_updates() -> None:
    state = ProspectiveOnlineExpertPairState.empty(
        system_id="center_hill",
        state_as_of=START,
    )
    feedback = ProspectiveOnlineExpertMaturedFeedback(
        sample_id="feedback",
        forecast_horizon_hours=1,
        target_support_end=START + timedelta(hours=1),
        observed_discharge_m3s=110.0,
        observation_available_at=START + timedelta(hours=2),
        baseline_prediction_m3s=100.0,
        alternative_prediction_m3s=120.0,
        coefficient_gate_shadow_prediction_m3s=100.0,
        coefficient_gate_passed=False,
    )
    with pytest.raises(ValueError, match="state_update_invalid"):
        advance_prospective_online_expert_pair_state(
            state,
            (feedback,),
            update_time=START + timedelta(hours=1),
        )

    updated = advance_prospective_online_expert_pair_state(
        state,
        (feedback,),
        update_time=START + timedelta(hours=2),
    )
    with pytest.raises(ValueError, match="state_update_invalid"):
        advance_prospective_online_expert_pair_state(
            updated,
            (feedback,),
            update_time=START + timedelta(hours=3),
        )
