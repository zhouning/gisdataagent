from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from data_agent.uwm.geospatial_kernel_v2.prospective_wwm_candidate import (
    ProspectiveWwmCandidateRunner,
    ProspectiveWwmCandidateState,
    ProspectiveWwmMaturedFeedback,
    advance_prospective_wwm_candidate_state,
    algorithm_contract,
)

START = datetime(2026, 8, 1, tzinfo=UTC)
PHYSICAL = {1: 101.0, 3: 103.0, 6: 106.0, 12: 112.0}
ACTION_WWM = {1: 111.0, 3: 113.0, 6: 116.0, 12: 122.0}


def _predictions(
    state: ProspectiveWwmCandidateState,
    *,
    issue_time: datetime = START,
    prefix: str = "issue-0",
):
    return ProspectiveWwmCandidateRunner(state).predict_issue(
        issue_time=issue_time,
        physical_at_latest_observation_m3s=100.0,
        physical_predictions_by_horizon=PHYSICAL,
        action_innovation_predictions_by_horizon=ACTION_WWM,
        forecast_id_prefix=prefix,
    )


def test_empty_state_generates_v4_at_issue_time_and_falls_back_to_physics() -> None:
    state = ProspectiveWwmCandidateState.empty(
        system_id="j_percy_priest",
        state_as_of=START,
    )

    predictions = _predictions(state)

    assert len(predictions) == 4
    for prediction in predictions:
        encoded = prediction.as_dict()
        assert prediction.v4_step.corrected_prediction_m3s == (
            prediction.v4_step.physical_target_m3s
        )
        assert encoded["physical_online_residual_adaptation_v4_m3s"] == encoded[
            "physical_open_loop_m3s"
        ]
        assert encoded["physical_online_expert_blend_v5_m3s"] == encoded[
            "physical_online_residual_adaptation_v4_m3s"
        ]
        assert encoded["v4_state_generated_at_issue_time"] is True
        assert encoded["current_or_future_target_used_for_prediction"] is False


def test_one_issue_update_advances_both_states_without_raw_outcomes() -> None:
    state = ProspectiveWwmCandidateState.empty(
        system_id="j_percy_priest",
        state_as_of=START,
    )
    predictions = _predictions(state)
    update_time = START + timedelta(hours=13)
    feedbacks = tuple(
        ProspectiveWwmMaturedFeedback(
            prediction=prediction,
            observed_discharge_m3s=(
                prediction.v4_step.physical_target_m3s + 5.0
            ),
            observation_available_at=(
                prediction.target_support_end + timedelta(minutes=30)
            ),
        )
        for prediction in predictions
    )

    updated = advance_prospective_wwm_candidate_state(
        state,
        feedbacks,
        update_time=update_time,
    )

    assert updated.state_as_of == update_time
    assert updated.physical_residual_state.sample_count_by_horizon() == {
        1: 1,
        3: 1,
        6: 1,
        12: 1,
    }
    assert updated.expert_pair_state.sample_count_by_horizon() == {
        1: 1,
        3: 1,
        6: 1,
        12: 1,
    }
    restored = ProspectiveWwmCandidateState.from_dict(updated.as_dict())
    assert restored == updated
    assert "observed_discharge_m3s" not in str(restored.as_dict())


def test_repeated_causal_updates_activate_v4_from_restored_state() -> None:
    state = ProspectiveWwmCandidateState.empty(
        system_id="j_percy_priest",
        state_as_of=START,
    )
    for index in range(48):
        issue_time = START + timedelta(hours=index * 13)
        predictions = _predictions(
            state,
            issue_time=issue_time,
            prefix=f"issue-{index}",
        )
        feedbacks = tuple(
            ProspectiveWwmMaturedFeedback(
                prediction=prediction,
                observed_discharge_m3s=(
                    prediction.v4_step.physical_target_m3s
                    + 0.5
                    * (prediction.v4_step.physical_trajectory_change_m3s or 10.0)
                ),
                observation_available_at=(
                    prediction.target_support_end + timedelta(minutes=30)
                ),
            )
            for prediction in predictions
        )
        state = advance_prospective_wwm_candidate_state(
            state,
            feedbacks,
            update_time=issue_time + timedelta(hours=13),
        )
        state = ProspectiveWwmCandidateState.from_dict(state.as_dict())

    next_issue = START + timedelta(hours=48 * 13)
    predictions = _predictions(state, issue_time=next_issue, prefix="active")
    by_horizon = {
        value.v4_step.forecast_horizon_hours: value for value in predictions
    }

    assert by_horizon[1].v4_step.matured_sample_count == 48
    assert by_horizon[1].v4_step.evidence_gate_passed is True
    assert by_horizon[1].v4_step.shadow_performance_gate_passed is True
    assert by_horizon[1].v4_step.application_gate_passed is True


def test_future_feedback_duplicate_update_and_incomplete_axis_fail_closed() -> None:
    state = ProspectiveWwmCandidateState.empty(
        system_id="center_hill",
        state_as_of=START,
    )
    predictions = _predictions(state)
    feedback = ProspectiveWwmMaturedFeedback(
        prediction=predictions[0],
        observed_discharge_m3s=105.0,
        observation_available_at=START + timedelta(hours=2),
    )
    with pytest.raises(ValueError, match="state_update_invalid"):
        advance_prospective_wwm_candidate_state(
            state,
            (feedback,),
            update_time=START + timedelta(hours=1),
        )

    updated = advance_prospective_wwm_candidate_state(
        state,
        (feedback,),
        update_time=START + timedelta(hours=2),
    )
    with pytest.raises(ValueError, match="update_invalid"):
        advance_prospective_wwm_candidate_state(
            updated,
            (feedback,),
            update_time=START + timedelta(hours=3),
        )

    with pytest.raises(ValueError, match="horizon_axis_invalid"):
        ProspectiveWwmCandidateRunner(state).predict_issue(
            issue_time=START,
            physical_at_latest_observation_m3s=100.0,
            physical_predictions_by_horizon={1: 101.0},
            action_innovation_predictions_by_horizon=ACTION_WWM,
            forecast_id_prefix="incomplete",
        )


def test_prediction_api_cannot_accept_outcomes_and_contract_is_not_admitted() -> None:
    parameters = set(
        inspect.signature(ProspectiveWwmCandidateRunner.predict_issue).parameters
    )
    contract = algorithm_contract()

    assert "observed_discharge_m3s" not in parameters
    assert not any("outcome" in value or "target_observation" in value for value in parameters)
    assert contract["v4_generated_from_matured_state_at_issue_time"] is True
    assert contract["precomputed_v4_prediction_accepted"] is False
    assert contract["candidate_admitted"] is False
    assert contract["runtime_default_enabled"] is False
