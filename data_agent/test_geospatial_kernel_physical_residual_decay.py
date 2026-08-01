from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from data_agent.uwm.geospatial_kernel_v2.physical_residual_decay import (
    PhysicalResidualDecayParameters,
    fit_physical_residual_decay,
    physical_residual_decay_parameters_from_dict,
)

START = datetime(2024, 1, 1, tzinfo=UTC)


def _fit() -> PhysicalResidualDecayParameters:
    times = tuple(START + timedelta(hours=index) for index in range(20))
    physical = tuple(50.0 for _ in times)
    residuals = tuple(20.0 * 0.8**index for index in range(len(times)))
    observed = tuple(
        prediction + residual for prediction, residual in zip(physical, residuals, strict=True)
    )
    return fit_physical_residual_decay(
        valid_times=times,
        physical_discharge_m3s=physical,
        observed_discharge_m3s=observed,
        observation_latency_hours=1,
        supported_forecast_horizons_hours=(1, 3, 6, 12),
        source_system_id="source",
        source_operator="sealed-physical-router",
        source_prediction_sha256="a" * 64,
        source_outcome_sha256="b" * 64,
        provenance_id="synthetic-residual-decay",
    )


def test_physical_residual_decay_recovers_known_zero_intercept_memory() -> None:
    parameters = _fit()

    assert parameters.residual_decay_coefficient == pytest.approx(0.8)
    assert parameters.training_pair_count == 19
    assert parameters.admitted is False
    assert parameters.source_outcome_calibrated is True


def test_physical_residual_decay_uses_full_state_to_target_elapsed_time() -> None:
    step = _fit().correct(
        latest_observed_discharge_m3s=70.0,
        physical_at_latest_observation_m3s=50.0,
        physical_target_m3s=40.0,
        forecast_horizon_hours=3,
    )

    assert step.elapsed_from_latest_observation_hours == 4
    assert step.decay_weight == pytest.approx(0.8**4)
    assert step.latest_observation_residual_m3s == pytest.approx(20.0)
    assert step.corrected_prediction_m3s == pytest.approx(40.0 + 0.8**4 * 20.0)
    assert step.clipped is False


def test_physical_residual_decay_parameter_document_round_trips() -> None:
    original = _fit()

    loaded = physical_residual_decay_parameters_from_dict(original.as_dict())

    assert loaded == original
    assert loaded.as_dict() == original.as_dict()


def test_physical_residual_decay_loader_rejects_target_fit_claim() -> None:
    payload = deepcopy(_fit().as_dict())
    payload["target_outcomes_used_for_fit"] = True

    with pytest.raises(ValueError, match="document_claims_invalid"):
        physical_residual_decay_parameters_from_dict(payload)


def test_physical_residual_decay_rejects_noncausal_or_nonphysical_inputs() -> None:
    with pytest.raises(ValueError, match="forecast_inputs_invalid"):
        _fit().correct(
            latest_observed_discharge_m3s=-1.0,
            physical_at_latest_observation_m3s=50.0,
            physical_target_m3s=40.0,
            forecast_horizon_hours=3,
        )
