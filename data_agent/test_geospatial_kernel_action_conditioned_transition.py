import math
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from data_agent.uwm.geospatial_kernel_v2.action_conditioned_transition import (
    CausalActionConditionedGeospatialKernel,
    GeographicResponseSupport,
    HourlyActionForcingSeries,
    OutletTransitionState,
    action_conditioned_transition_parameters_from_dict,
    fit_action_conditioned_transition,
)

UTC = UTC
START = datetime(2020, 12, 28, tzinfo=UTC)


def _support() -> GeographicResponseSupport:
    return GeographicResponseSupport(
        network_id="synthetic-river",
        action_entry_feature_id=10,
        outlet_feature_id=40,
        path_feature_ids=(10, 20, 30, 40),
        lag_hours=(2, 3),
        lag_weights=(0.6, 0.4),
        provenance_id="synthetic-directed-path-and-response-support",
        evidence_level="candidate",
        admitted=False,
    )


def _inputs(hour_count: int = 240) -> HourlyActionForcingSeries:
    times = tuple(START + timedelta(hours=index) for index in range(hour_count))
    return HourlyActionForcingSeries(
        valid_times=times,
        action_release_m3s=tuple(
            40.0 + 10.0 * math.sin(index / 5.0) + float(index % 7) for index in range(hour_count)
        ),
        nwm_lateral_inflow_m3s=tuple(
            2.0 + 0.5 * math.cos(index / 11.0) + float(index % 3) / 10.0
            for index in range(hour_count)
        ),
        action_provenance_id="synthetic-action-plan",
        forcing_provenance_id="synthetic-nwm-forcing",
        action_plan_vintage_verified=False,
        forcing_vintage_verified=False,
    )


def _training_series() -> tuple[tuple[datetime, ...], tuple[float, ...]]:
    inputs = _inputs()
    action = dict(zip(inputs.valid_times, inputs.action_release_m3s, strict=True))
    forcing = dict(zip(inputs.valid_times, inputs.nwm_lateral_inflow_m3s, strict=True))
    times = inputs.valid_times[3:163]
    values = [25.0]
    for valid_at in times[1:]:
        effective_action = (
            0.6 * action[valid_at - timedelta(hours=2)]
            + 0.4 * action[valid_at - timedelta(hours=3)]
        )
        values.append(3.0 + 0.8 * values[-1] + 0.12 * effective_action + 0.5 * forcing[valid_at])
    return times, tuple(values)


def _fit():
    times, values = _training_series()
    return fit_action_conditioned_transition(
        support=_support(),
        observed_valid_times=times,
        observed_discharge_m3s=values,
        inputs=_inputs(),
        maximum_discharge_m3s=1_000.0,
        provenance_id="synthetic-training-fit",
    )


def test_fit_recovers_stable_low_dimensional_transition() -> None:
    result = _fit()

    assert result.design_rank == 4
    assert result.parameters.training_sample_count == 159
    assert result.training_rmse_m3s < 1e-10
    assert result.parameters.intercept_m3s == pytest.approx(3.0)
    assert result.parameters.autoregressive_coefficient == pytest.approx(0.8)
    assert result.parameters.action_coefficient == pytest.approx(0.12)
    assert result.parameters.forcing_coefficient == pytest.approx(0.5)
    assert result.parameters.outcome_calibrated is True
    assert result.parameters.admitted is False


def test_forecast_is_causal_and_returns_issue_and_final_writeback_states() -> None:
    fit = _fit()
    kernel = CausalActionConditionedGeospatialKernel(fit.parameters)
    issue = fit.parameters.training_data_end + timedelta(hours=1)
    state = OutletTransitionState(
        valid_at=issue - timedelta(hours=1),
        available_at=issue,
        discharge_m3s=_training_series()[1][-1],
        provenance_id="synthetic-latest-observation",
        evidence_level="candidate",
        observed=True,
    )
    targets = (issue + timedelta(hours=1), issue + timedelta(hours=4))

    result = kernel.forecast(
        state,
        _inputs(),
        issue_time=issue,
        target_valid_times=targets,
    )

    assert result.issue_state.valid_at == issue
    assert result.issue_state.observed is False
    assert result.final_state.valid_at == targets[-1]
    assert result.target_valid_times == targets
    assert len(result.steps) == 5
    assert result.future_observations_used is False
    assert result.operational_vintages_verified is False
    assert result.admitted is False


def test_no_action_counterfactual_changes_only_after_supported_lag() -> None:
    fit = _fit()
    kernel = CausalActionConditionedGeospatialKernel(fit.parameters)
    issue = fit.parameters.training_data_end + timedelta(hours=1)
    state = OutletTransitionState(
        valid_at=issue - timedelta(hours=1),
        available_at=issue,
        discharge_m3s=_training_series()[1][-1],
        provenance_id="synthetic-latest-observation",
        evidence_level="candidate",
        observed=True,
    )
    targets = tuple(issue + timedelta(hours=value) for value in (1, 3, 5))
    baseline = kernel.forecast(state, _inputs(), issue_time=issue, target_valid_times=targets)
    no_action = kernel.forecast(
        state,
        _inputs().counterfactual(issue_time=issue, zero_future_action=True),
        issue_time=issue,
        target_valid_times=targets,
    )

    assert no_action.target_discharge_m3s[0] == pytest.approx(baseline.target_discharge_m3s[0])
    assert no_action.target_discharge_m3s[-1] != pytest.approx(baseline.target_discharge_m3s[-1])


def test_forecast_rejects_unavailable_state_and_missing_lagged_action() -> None:
    fit = _fit()
    kernel = CausalActionConditionedGeospatialKernel(fit.parameters)
    issue = fit.parameters.training_data_end + timedelta(hours=1)
    unavailable = OutletTransitionState(
        valid_at=issue - timedelta(hours=1),
        available_at=issue + timedelta(hours=1),
        discharge_m3s=10.0,
        provenance_id="synthetic-unavailable-observation",
        evidence_level="candidate",
        observed=True,
    )
    with pytest.raises(ValueError, match="not_available_at_issue"):
        kernel.forecast(
            unavailable,
            _inputs(),
            issue_time=issue,
            target_valid_times=(issue + timedelta(hours=1),),
        )

    available = OutletTransitionState(
        valid_at=START + timedelta(hours=1),
        available_at=issue,
        discharge_m3s=10.0,
        provenance_id="synthetic-available-observation",
        evidence_level="candidate",
        observed=True,
    )
    with pytest.raises(ValueError, match="required_input_missing"):
        kernel.forecast(
            available,
            _inputs(),
            issue_time=issue,
            target_valid_times=(issue + timedelta(hours=1),),
        )


def test_response_support_rejects_path_or_weight_misrepresentation() -> None:
    values = _support().__dict__
    with pytest.raises(ValueError, match="response_path_invalid"):
        GeographicResponseSupport(**{**values, "path_feature_ids": (20, 40)})
    with pytest.raises(ValueError, match="lag_weights_invalid"):
        GeographicResponseSupport(**{**values, "lag_weights": (0.7, 0.4)})


def test_serialized_parameters_round_trip_without_refitting() -> None:
    original = _fit().parameters

    loaded = action_conditioned_transition_parameters_from_dict(original.as_dict())

    assert loaded == original
    assert loaded.as_dict() == original.as_dict()


@pytest.mark.parametrize(
    ("mutation", "error"),
    (
        (lambda value: value.update({"unknown": True}), "document_fields_invalid"),
        (lambda value: value.update({"schema": "wrong"}), "document_schema_invalid"),
        (
            lambda value: value.update({"mass_conserving_network_routing_replacement": True}),
            "document_claims_invalid",
        ),
        (
            lambda value: value["support"].update({"empirical_lag_is_physical_travel_time": True}),
            "support_document_claims_invalid",
        ),
    ),
)
def test_parameter_loader_rejects_schema_or_claim_drift(mutation, error) -> None:
    payload = deepcopy(_fit().parameters.as_dict())
    mutation(payload)

    with pytest.raises(ValueError, match=error):
        action_conditioned_transition_parameters_from_dict(payload)
