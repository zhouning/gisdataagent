import math
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from data_agent.uwm.geospatial_kernel_v2.action_conditioned_transition import (
    GeographicResponseSupport,
    HourlyActionForcingSeries,
    OutletTransitionState,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    CausalActionInnovationGeospatialKernel,
    action_innovation_transition_parameters_from_dict,
    fit_action_innovation_transition,
)

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
    times = inputs.valid_times[4:164]
    values = [100.0]
    for valid_at in times[1:]:
        current = (
            0.6 * action[valid_at - timedelta(hours=2)]
            + 0.4 * action[valid_at - timedelta(hours=3)]
        )
        previous = (
            0.6 * action[valid_at - timedelta(hours=3)]
            + 0.4 * action[valid_at - timedelta(hours=4)]
        )
        values.append(values[-1] - 0.5 + 0.2 * (current - previous) + 0.7 * forcing[valid_at])
    return times, tuple(values)


def _fit():
    times, values = _training_series()
    return fit_action_innovation_transition(
        support=_support(),
        observed_valid_times=times,
        observed_discharge_m3s=values,
        inputs=_inputs(),
        maximum_discharge_m3s=1_000.0,
        provenance_id="synthetic-innovation-fit",
    )


def test_fit_recovers_state_anchored_action_innovation_transition() -> None:
    result = _fit()

    assert result.design_rank == 3
    assert result.parameters.training_sample_count == 159
    assert result.training_increment_rmse_m3s < 1e-10
    assert result.parameters.baseline_drift_m3s_per_hour == pytest.approx(-0.5)
    assert result.parameters.action_change_coefficient == pytest.approx(0.2)
    assert result.parameters.forcing_coefficient == pytest.approx(0.7)
    assert result.parameters.as_dict()["state_persistence_coefficient_fixed"] == 1.0
    assert result.parameters.supported_forecast_horizons_hours == (1, 3, 6, 12)
    assert result.parameters.as_dict()["asymptotic_stability_claimed"] is False


def test_forecast_writes_issue_and_target_states_without_future_observations() -> None:
    fit = _fit()
    issue = fit.parameters.training_data_end + timedelta(hours=1)
    state = OutletTransitionState(
        valid_at=issue - timedelta(hours=1),
        available_at=issue,
        discharge_m3s=_training_series()[1][-1],
        provenance_id="synthetic-latest-observation",
        evidence_level="candidate",
        observed=True,
    )
    result = CausalActionInnovationGeospatialKernel(fit.parameters).forecast(
        state,
        _inputs(),
        issue_time=issue,
        target_valid_times=(issue + timedelta(hours=1), issue + timedelta(hours=6)),
    )

    assert result.issue_state.valid_at == issue
    assert result.final_state.valid_at == issue + timedelta(hours=6)
    assert len(result.steps) == 7
    assert result.future_observations_used is False
    assert result.operational_vintages_verified is False
    assert result.admitted is False


def test_future_action_ablation_changes_only_after_response_support() -> None:
    fit = _fit()
    issue = fit.parameters.training_data_end + timedelta(hours=1)
    state = OutletTransitionState(
        valid_at=issue - timedelta(hours=1),
        available_at=issue,
        discharge_m3s=_training_series()[1][-1],
        provenance_id="synthetic-latest-observation",
        evidence_level="candidate",
        observed=True,
    )
    targets = tuple(issue + timedelta(hours=value) for value in (1, 3, 6))
    kernel = CausalActionInnovationGeospatialKernel(fit.parameters)
    baseline = kernel.forecast(state, _inputs(), issue_time=issue, target_valid_times=targets)
    no_action = kernel.forecast(
        state,
        _inputs().counterfactual(issue_time=issue, zero_future_action=True),
        issue_time=issue,
        target_valid_times=targets,
    )

    assert no_action.target_discharge_m3s[0] == pytest.approx(baseline.target_discharge_m3s[0])
    assert no_action.target_discharge_m3s[-1] != pytest.approx(baseline.target_discharge_m3s[-1])


def test_forecast_fails_closed_when_previous_lagged_action_is_missing() -> None:
    fit = _fit()
    issue = fit.parameters.training_data_end + timedelta(hours=1)
    state = OutletTransitionState(
        valid_at=START + timedelta(hours=2),
        available_at=issue,
        discharge_m3s=100.0,
        provenance_id="synthetic-available-observation",
        evidence_level="candidate",
        observed=True,
    )

    with pytest.raises(ValueError, match="required_input_missing"):
        CausalActionInnovationGeospatialKernel(fit.parameters).forecast(
            state,
            _inputs(),
            issue_time=issue,
            target_valid_times=(issue + timedelta(hours=1),),
        )


@pytest.mark.parametrize("horizon", (2, 13))
def test_forecast_rejects_unregistered_horizons(horizon) -> None:
    fit = _fit()
    issue = fit.parameters.training_data_end + timedelta(hours=1)
    state = OutletTransitionState(
        valid_at=issue - timedelta(hours=1),
        available_at=issue,
        discharge_m3s=_training_series()[1][-1],
        provenance_id="synthetic-latest-observation",
        evidence_level="candidate",
        observed=True,
    )

    with pytest.raises(ValueError, match="target_horizon_not_supported"):
        CausalActionInnovationGeospatialKernel(fit.parameters).forecast(
            state,
            _inputs(),
            issue_time=issue,
            target_valid_times=(issue + timedelta(hours=horizon),),
        )


def test_forecast_rejects_fractional_hour_target() -> None:
    fit = _fit()
    issue = fit.parameters.training_data_end + timedelta(hours=1)
    state = OutletTransitionState(
        valid_at=issue - timedelta(hours=1),
        available_at=issue,
        discharge_m3s=_training_series()[1][-1],
        provenance_id="synthetic-latest-observation",
        evidence_level="candidate",
        observed=True,
    )

    with pytest.raises(ValueError, match="targets_must_align_to_timestep"):
        CausalActionInnovationGeospatialKernel(fit.parameters).forecast(
            state,
            _inputs(),
            issue_time=issue,
            target_valid_times=(issue + timedelta(minutes=30),),
        )


def test_serialized_innovation_parameters_round_trip_without_refit() -> None:
    original = _fit().parameters

    loaded = action_innovation_transition_parameters_from_dict(original.as_dict())

    assert loaded == original
    assert loaded.as_dict() == original.as_dict()


@pytest.mark.parametrize(
    "field",
    (
        "state_persistence_coefficient_fixed",
        "asymptotic_stability_claimed",
        "mass_conserving_network_routing_replacement",
    ),
)
def test_innovation_parameter_loader_rejects_claim_inflation(field) -> None:
    payload = deepcopy(_fit().parameters.as_dict())
    payload[field] = 0.9 if field == "state_persistence_coefficient_fixed" else True

    with pytest.raises(ValueError, match="document_claims_invalid"):
        action_innovation_transition_parameters_from_dict(payload)
