from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from data_agent.uwm.geospatial_kernel_v2.physical_online_expert_blend import (
    PhysicalOnlineExpertBlendConfig,
    PhysicalOnlineExpertBlender,
)

START = datetime(2026, 7, 31, tzinfo=UTC)


def test_blender_falls_back_before_evidence() -> None:
    step = PhysicalOnlineExpertBlender().predict(
        forecast_horizon_hours=1,
        baseline_prediction_m3s=100.0,
        alternative_prediction_m3s=120.0,
        issue_time=START,
    )

    assert step.matured_sample_count == 0
    assert step.application_gate_passed is False
    assert step.applied_weight == 0.0
    assert step.blended_prediction_m3s == 100.0


def test_blender_admits_supported_alternative_weight() -> None:
    blender = PhysicalOnlineExpertBlender()
    for index in range(24):
        update_time = START + timedelta(hours=index)
        blender.update(
            sample_id=f"sample-{index}",
            forecast_horizon_hours=1,
            baseline_prediction_m3s=100.0,
            alternative_prediction_m3s=120.0,
            candidate_shadow_prediction_m3s=110.0,
            candidate_evidence_gate_passed=True,
            observed_target_m3s=110.0,
            target_observation_available_at=update_time,
            update_time=update_time,
        )

    step = blender.predict(
        forecast_horizon_hours=1,
        baseline_prediction_m3s=100.0,
        alternative_prediction_m3s=120.0,
        issue_time=START + timedelta(hours=24),
    )

    assert step.raw_weight == pytest.approx(0.5)
    assert step.weight_standard_error == pytest.approx(0.0)
    assert step.evidence_gate_passed is True
    assert step.shadow_performance_gate_passed is True
    assert step.application_gate_passed is True
    assert step.applied_weight == pytest.approx(0.5)
    assert step.blended_prediction_m3s == pytest.approx(110.0)


def test_blender_rejects_future_or_duplicate_outcome() -> None:
    blender = PhysicalOnlineExpertBlender()
    arguments = {
        "sample_id": "sample",
        "forecast_horizon_hours": 1,
        "baseline_prediction_m3s": 100.0,
        "alternative_prediction_m3s": 120.0,
        "candidate_shadow_prediction_m3s": 110.0,
        "candidate_evidence_gate_passed": True,
        "observed_target_m3s": 110.0,
        "target_observation_available_at": START,
        "update_time": START,
    }
    blender.update(**arguments)

    with pytest.raises(ValueError, match="update_invalid"):
        blender.update(**arguments)
    with pytest.raises(ValueError, match="update_invalid"):
        blender.update(
            **{
                **arguments,
                "sample_id": "future",
                "target_observation_available_at": START + timedelta(hours=2),
                "update_time": START + timedelta(hours=1),
            }
        )


def test_blender_accepts_signed_observation_but_rejects_negative_prediction() -> None:
    blender = PhysicalOnlineExpertBlender()
    blender.update(
        sample_id="signed",
        forecast_horizon_hours=1,
        baseline_prediction_m3s=1.0,
        alternative_prediction_m3s=0.0,
        candidate_shadow_prediction_m3s=0.5,
        candidate_evidence_gate_passed=True,
        observed_target_m3s=-0.5,
        target_observation_available_at=START,
        update_time=START,
    )
    assert blender.sample_count_by_horizon()[1] == 1

    with pytest.raises(ValueError, match="forecast_invalid"):
        blender.predict(
            forecast_horizon_hours=1,
            baseline_prediction_m3s=-1.0,
            alternative_prediction_m3s=0.0,
            issue_time=START,
        )


def test_configuration_exposes_non_admitted_physical_fallback() -> None:
    payload = PhysicalOnlineExpertBlendConfig().as_dict()

    assert payload["baseline_expert"] == ("physical_online_residual_adaptation_v4")
    assert payload["alternative_expert"] == "action_innovation_wwm"
    assert payload["weight_lower_bound"] == 0.0
    assert payload["weight_upper_bound"] == 1.0
    assert payload["insufficient_evidence_fallback"] == ("physical_first_baseline")
    assert payload["cross_system_parameter_transfer_required"] is False
    assert payload["admitted"] is False
