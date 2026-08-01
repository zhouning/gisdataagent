from copy import deepcopy
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from data_agent.uwm.geospatial_kernel_v2.classical_arx_baseline import (
    ClassicalCausalARXParameters,
    classical_causal_arx_parameters_from_dict,
    fit_classical_causal_arx,
)

START = datetime(2024, 1, 1, tzinfo=UTC)
SOURCE_SHA = "a" * 64
LAGS = (2, 3)
WEIGHTS = (0.4, 0.6)


def _training_series():
    count = 80
    times = tuple(START + timedelta(hours=index) for index in range(count))
    action = np.asarray(
        [20.0 + 4.0 * np.sin(index / 3.0) + float(index % 5) for index in range(count)]
    )
    forcing = np.asarray(
        [3.0 + 0.5 * np.cos(index / 4.0) + 0.1 * (index % 7) for index in range(count)]
    )
    observed = np.zeros(count, dtype=float)
    observed[: max(LAGS)] = (40.0, 41.0, 42.0)
    for index in range(max(LAGS), count):
        action_level = sum(
            weight * action[index - lag]
            for lag, weight in zip(LAGS, WEIGHTS, strict=True)
        )
        observed[index] = (
            2.5
            + 0.82 * observed[index - 1]
            + 0.17 * action_level
            + 0.63 * forcing[index]
        )
    return times, tuple(observed), tuple(action), tuple(forcing)


def _fit() -> ClassicalCausalARXParameters:
    times, observed, action, forcing = _training_series()
    return fit_classical_causal_arx(
        valid_times=times,
        observed_discharge_m3s=observed,
        action_release_m3s=action,
        lateral_forcing_m3s=forcing,
        lag_hours=LAGS,
        lag_weights=WEIGHTS,
        supported_forecast_horizons_hours=(1, 3, 6, 12),
        maximum_discharge_m3s=1000.0,
        source_artifact_sha256=SOURCE_SHA,
        provenance_id="synthetic-exact-arx-fit",
    )


def test_classical_arx_fit_recovers_known_transfer_function() -> None:
    parameters = _fit()

    assert parameters.intercept_m3s == pytest.approx(2.5)
    assert parameters.autoregressive_coefficient == pytest.approx(0.82)
    assert parameters.action_level_coefficient == pytest.approx(0.17)
    assert parameters.forcing_coefficient == pytest.approx(0.63)
    assert parameters.training_sample_count == 77
    assert parameters.asymptotically_stable is True
    assert parameters.admitted is False


def test_classical_arx_forecast_is_recursive_and_causal() -> None:
    parameters = _fit()
    _, observed, action, forcing = _training_series()

    predicted, clipped = parameters.forecast(
        initial_discharge_m3s=observed[19],
        issue_index=20,
        target_indices=(20, 22, 25),
        action_release_m3s=action,
        lateral_forcing_m3s=forcing,
    )

    assert predicted == pytest.approx((observed[20], observed[22], observed[25]))
    assert clipped == 0


def test_classical_arx_parameter_document_round_trips() -> None:
    original = _fit()

    loaded = classical_causal_arx_parameters_from_dict(original.as_dict())

    assert loaded == original
    assert loaded.as_dict() == original.as_dict()


def test_classical_arx_loader_rejects_target_outcome_claim_inflation() -> None:
    payload = deepcopy(_fit().as_dict())
    payload["target_outcomes_used_for_fit"] = True

    with pytest.raises(ValueError, match="document_claims_invalid"):
        classical_causal_arx_parameters_from_dict(payload)


def test_classical_arx_rejects_invalid_forecast_axis() -> None:
    parameters = _fit()
    _, observed, action, forcing = _training_series()

    with pytest.raises(ValueError, match="forecast_inputs_invalid"):
        parameters.forecast(
            initial_discharge_m3s=observed[19],
            issue_index=20,
            target_indices=(22, 21),
            action_release_m3s=action,
            lateral_forcing_m3s=forcing,
        )
