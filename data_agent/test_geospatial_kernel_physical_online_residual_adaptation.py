from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from data_agent.uwm.geospatial_kernel_v2.physical_online_residual_adaptation import (
    PhysicalOnlineResidualAdaptationConfig,
    PhysicalOnlineResidualAdaptationState,
    PhysicalOnlineResidualAdapter,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


def test_adapter_falls_back_to_raw_physical_before_evidence_gate() -> None:
    adapter = PhysicalOnlineResidualAdapter()

    step = adapter.predict(
        forecast_horizon_hours=3,
        physical_at_latest_observation_m3s=80.0,
        predictor_physical_target_m3s=100.0,
        physical_target_m3s=100.0,
        issue_time=START,
    )

    assert step.matured_sample_count == 0
    assert step.evidence_gate_passed is False
    assert step.applied_weight == 0.0
    assert step.corrected_prediction_m3s == 100.0


def test_adapter_learns_significant_matured_residual_relationship() -> None:
    adapter = PhysicalOnlineResidualAdapter()
    for index in range(24):
        update_time = START + timedelta(hours=index + 1)
        trajectory_change = 10.0 + index
        adapter.update(
            sample_id=f"sample-{index}",
            forecast_horizon_hours=3,
            physical_trajectory_change_m3s=trajectory_change,
            physical_target_m3s=100.0,
            candidate_shadow_prediction_m3s=100.0 + 0.5 * trajectory_change,
            candidate_evidence_gate_passed=True,
            observed_target_m3s=100.0 + 0.5 * trajectory_change,
            target_observation_available_at=update_time,
            update_time=update_time,
        )

    step = adapter.predict(
        forecast_horizon_hours=3,
        physical_at_latest_observation_m3s=80.0,
        predictor_physical_target_m3s=100.0,
        physical_target_m3s=100.0,
        issue_time=START + timedelta(hours=25),
    )

    assert step.matured_sample_count == 24
    assert step.raw_weight == pytest.approx(0.5)
    assert step.weight_standard_error == pytest.approx(0.0)
    assert step.evidence_gate_passed is True
    assert step.shadow_performance_gate_passed is True
    assert step.shadow_mean_squared_error_improvement_m6s2 is not None
    assert (
        step.shadow_mean_squared_error_improvement_m6s2
        > step.shadow_improvement_threshold_m6s2
    )
    assert step.application_gate_passed is True
    assert step.applied_weight == pytest.approx(0.5)
    assert step.corrected_prediction_m3s == pytest.approx(110.0)


def test_adapter_rejects_outcome_before_declared_availability() -> None:
    adapter = PhysicalOnlineResidualAdapter()

    with pytest.raises(ValueError, match="update_invalid"):
        adapter.update(
            sample_id="future",
            forecast_horizon_hours=1,
            physical_trajectory_change_m3s=5.0,
            physical_target_m3s=100.0,
            candidate_shadow_prediction_m3s=102.0,
            candidate_evidence_gate_passed=True,
            observed_target_m3s=102.0,
            target_observation_available_at=START + timedelta(hours=2),
            update_time=START + timedelta(hours=1),
        )


def test_adapter_rejects_duplicate_matured_sample() -> None:
    adapter = PhysicalOnlineResidualAdapter()
    arguments = {
        "sample_id": "duplicate",
        "forecast_horizon_hours": 1,
        "physical_trajectory_change_m3s": 5.0,
        "physical_target_m3s": 100.0,
        "candidate_shadow_prediction_m3s": 102.0,
        "candidate_evidence_gate_passed": True,
        "observed_target_m3s": 102.0,
        "target_observation_available_at": START,
        "update_time": START,
    }
    adapter.update(**arguments)

    with pytest.raises(ValueError, match="update_invalid"):
        adapter.update(**arguments)


def test_adapter_accepts_finite_signed_observed_target() -> None:
    adapter = PhysicalOnlineResidualAdapter()

    adapter.update(
        sample_id="approved-negative-observation",
        forecast_horizon_hours=1,
        physical_trajectory_change_m3s=-2.0,
        physical_target_m3s=1.0,
        candidate_shadow_prediction_m3s=0.0,
        candidate_evidence_gate_passed=True,
        observed_target_m3s=-0.5,
        target_observation_available_at=START,
        update_time=START,
    )

    assert adapter.sample_count_by_horizon()[1] == 1


def test_adapter_clamps_admitted_weight_and_nonnegative_prediction() -> None:
    config = PhysicalOnlineResidualAdaptationConfig(
        supported_forecast_horizons_hours=(1, 3),
        adaptive_forecast_horizons_hours=(1,),
        bias_adaptive_forecast_horizons_hours=(),
        trajectory_predictor_horizon_pairs=((1, 3),),
        minimum_matured_sample_count=2,
    )
    adapter = PhysicalOnlineResidualAdapter(config)
    for index, trajectory_change in enumerate((-10.0, -10.0)):
        adapter.update(
            sample_id=f"sample-{index}",
            forecast_horizon_hours=1,
            physical_trajectory_change_m3s=trajectory_change,
            physical_target_m3s=100.0,
            candidate_shadow_prediction_m3s=100.0 + 2.0 * trajectory_change,
            candidate_evidence_gate_passed=True,
            observed_target_m3s=100.0 + 2.0 * trajectory_change,
            target_observation_available_at=START + timedelta(hours=index),
            update_time=START + timedelta(hours=index),
        )

    step = adapter.predict(
        forecast_horizon_hours=1,
        physical_at_latest_observation_m3s=250.0,
        predictor_physical_target_m3s=50.0,
        physical_target_m3s=50.0,
        issue_time=START + timedelta(hours=2),
    )

    assert step.raw_weight == pytest.approx(2.0)
    assert step.applied_weight == 1.0
    assert step.unbounded_prediction_m3s == -150.0
    assert step.corrected_prediction_m3s == 0.0
    assert step.clipped is True


def test_adapter_keeps_significant_but_unskilled_correction_in_shadow() -> None:
    config = PhysicalOnlineResidualAdaptationConfig(
        supported_forecast_horizons_hours=(1, 3),
        adaptive_forecast_horizons_hours=(1,),
        bias_adaptive_forecast_horizons_hours=(),
        trajectory_predictor_horizon_pairs=((1, 3),),
        minimum_matured_sample_count=2,
    )
    adapter = PhysicalOnlineResidualAdapter(config)
    for index, trajectory_change in enumerate((10.0, 20.0)):
        adapter.update(
            sample_id=f"bad-shadow-{index}",
            forecast_horizon_hours=1,
            physical_trajectory_change_m3s=trajectory_change,
            physical_target_m3s=100.0,
            candidate_shadow_prediction_m3s=100.0 + 2.0 * trajectory_change,
            candidate_evidence_gate_passed=True,
            observed_target_m3s=100.0 + 0.5 * trajectory_change,
            target_observation_available_at=START + timedelta(hours=index),
            update_time=START + timedelta(hours=index),
        )

    step = adapter.predict(
        forecast_horizon_hours=1,
        physical_at_latest_observation_m3s=90.0,
        predictor_physical_target_m3s=100.0,
        physical_target_m3s=100.0,
        issue_time=START + timedelta(hours=2),
    )

    assert step.evidence_gate_passed is True
    assert step.shadow_performance_gate_passed is False
    assert step.shadow_mean_squared_error_improvement_m6s2 < 0.0
    assert step.application_gate_passed is False
    assert step.shadow_prediction_m3s == pytest.approx(105.0)
    assert step.corrected_prediction_m3s == 100.0


def test_configuration_exposes_non_admitted_raw_fallback_contract() -> None:
    payload = PhysicalOnlineResidualAdaptationConfig().as_dict()

    assert payload["insufficient_evidence_fallback"] == "raw_physical"
    assert payload["target_outcome_used_before_declared_availability"] is False
    assert payload["finite_signed_observed_target_supported"] is True
    assert payload["adaptive_forecast_horizons_hours"] == [1, 3, 6]
    assert payload["bias_adaptive_forecast_horizons_hours"] == [12]
    assert payload["short_horizon_predictor"] == (
        "physical(predictor_h) - physical(latest_observation_time)"
    )
    assert payload["trajectory_predictor_horizon_by_target_horizon"] == {
        "1": 3,
        "3": 6,
        "6": 12,
    }
    assert payload["cross_system_parameter_transfer_required"] is False
    assert payload["statistical_coverage_guarantee_claimed"] is False
    assert payload["admitted"] is False


def test_default_contract_uses_mean_physical_error_at_twelve_hours() -> None:
    adapter = PhysicalOnlineResidualAdapter()
    for index in range(24):
        update_time = START + timedelta(hours=index)
        adapter.update(
            sample_id=f"long-horizon-{index}",
            forecast_horizon_hours=12,
            physical_trajectory_change_m3s=10.0 + index,
            physical_target_m3s=100.0,
            candidate_shadow_prediction_m3s=105.0,
            candidate_evidence_gate_passed=True,
            observed_target_m3s=105.0,
            target_observation_available_at=update_time,
            update_time=update_time,
        )

    step = adapter.predict(
        forecast_horizon_hours=12,
        physical_at_latest_observation_m3s=80.0,
        predictor_physical_target_m3s=None,
        physical_target_m3s=100.0,
        issue_time=START + timedelta(hours=24),
    )

    assert step.correction_mode == "mean_physical_error"
    assert step.raw_bias_m3s == pytest.approx(5.0)
    assert step.evidence_gate_passed is True
    assert step.application_gate_passed is True
    assert step.applied_weight == 0.0
    assert step.applied_bias_m3s == pytest.approx(5.0)
    assert step.corrected_prediction_m3s == pytest.approx(105.0)


def test_state_round_trip_replays_identical_prediction_without_raw_observations() -> None:
    adapter = PhysicalOnlineResidualAdapter()
    for index in range(24):
        update_time = START + timedelta(hours=index)
        trajectory_change = 10.0 + index
        adapter.update(
            sample_id=f"state-{index}",
            forecast_horizon_hours=3,
            physical_trajectory_change_m3s=trajectory_change,
            physical_target_m3s=100.0,
            candidate_shadow_prediction_m3s=100.0 + 0.5 * trajectory_change,
            candidate_evidence_gate_passed=True,
            observed_target_m3s=100.0 + 0.5 * trajectory_change,
            target_observation_available_at=update_time,
            update_time=update_time,
        )
    state = adapter.export_state(
        system_id="j_percy_priest",
        state_as_of=START + timedelta(hours=24),
    )
    restored_state = PhysicalOnlineResidualAdaptationState.from_dict(state.as_dict())
    restored = PhysicalOnlineResidualAdapter.from_state(restored_state)
    arguments = {
        "forecast_horizon_hours": 3,
        "physical_at_latest_observation_m3s": 80.0,
        "predictor_physical_target_m3s": 100.0,
        "physical_target_m3s": 100.0,
        "issue_time": START + timedelta(hours=25),
    }

    assert restored_state == state
    assert restored.predict(**arguments) == adapter.predict(**arguments)
    encoded = restored_state.as_dict()
    assert encoded["raw_observations_included"] is False
    assert "observed_target_m3s" not in str(encoded)


def test_state_rejects_prediction_before_snapshot_time() -> None:
    state = PhysicalOnlineResidualAdaptationState.empty(
        system_id="center_hill",
        state_as_of=START + timedelta(hours=1),
    )

    with pytest.raises(ValueError, match="forecast_invalid"):
        PhysicalOnlineResidualAdapter.from_state(state).predict(
            forecast_horizon_hours=1,
            physical_at_latest_observation_m3s=80.0,
            predictor_physical_target_m3s=100.0,
            physical_target_m3s=90.0,
            issue_time=START,
        )
