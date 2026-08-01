from datetime import UTC, datetime, timedelta

import pytest

from data_agent.uwm.geospatial_kernel_v2.action_conditioned_transition import (
    GeographicResponseSupport,
    HourlyActionForcingSeries,
    OutletTransitionState,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    ActionInnovationTransitionParameters,
)
from data_agent.uwm.geospatial_kernel_v2.counterfactual_action_response import (
    apply_release_step,
    audit_counterfactual_release_steps,
)

START = datetime(2022, 1, 1, tzinfo=UTC)
ISSUE = START + timedelta(hours=20)


def _parameters(*, drift: float = 0.0, maximum: float = 1_000.0):
    support = GeographicResponseSupport(
        network_id="synthetic-reservoir-path",
        action_entry_feature_id=1,
        outlet_feature_id=4,
        path_feature_ids=(1, 2, 3, 4),
        lag_hours=(5, 6, 7),
        lag_weights=(1 / 3, 1 / 3, 1 / 3),
        provenance_id="synthetic-response-support",
        evidence_level="candidate",
        admitted=False,
    )
    return ActionInnovationTransitionParameters(
        support=support,
        baseline_drift_m3s_per_hour=drift,
        action_change_coefficient=0.25,
        forcing_coefficient=0.0,
        timestep_seconds=3600,
        supported_forecast_horizons_hours=(1, 3, 6, 12),
        maximum_discharge_m3s=maximum,
        training_data_start=START - timedelta(days=10),
        training_data_end=START - timedelta(days=1),
        training_sample_count=200,
        provenance_id="synthetic-action-innovation",
        evidence_level="candidate",
        admitted=False,
        outcome_calibrated=True,
    )


def _inputs(*, action: float = 100.0):
    times = tuple(START + timedelta(hours=value) for value in range(48))
    return HourlyActionForcingSeries(
        valid_times=times,
        action_release_m3s=(action,) * len(times),
        nwm_lateral_inflow_m3s=(0.0,) * len(times),
        action_provenance_id="synthetic-action",
        forcing_provenance_id="synthetic-forcing",
        action_plan_vintage_verified=False,
        forcing_vintage_verified=False,
    )


def _state(*, discharge: float = 100.0):
    return OutletTransitionState(
        valid_at=ISSUE - timedelta(hours=1),
        available_at=ISSUE,
        discharge_m3s=discharge,
        provenance_id="synthetic-outlet-state",
        evidence_level="candidate",
        observed=True,
    )


def test_release_step_preserves_history_and_reports_negative_floor() -> None:
    inputs = _inputs(action=5.0)
    scenario, floor_count, step_count = apply_release_step(
        inputs,
        issue_time=ISSUE,
        release_delta_m3s=-10.0,
        through_time=ISSUE + timedelta(hours=12),
    )

    assert scenario.action_release_m3s[:21] == inputs.action_release_m3s[:21]
    assert set(scenario.action_release_m3s[21:]) == {0.0}
    assert floor_count == 12
    assert step_count == 12


def test_counterfactual_response_has_fixed_lag_sign_and_unit_gain() -> None:
    audit = audit_counterfactual_release_steps(
        parameters=_parameters(),
        state=_state(),
        inputs=_inputs(),
        issue_time=ISSUE,
        release_deltas_m3s=(-20.0, 20.0),
    )
    indexed = {(row.requested_release_delta_m3s, row.horizon_hours): row for row in audit.responses}

    for delta in (-20.0, 20.0):
        assert indexed[(delta, 1)].discharge_response_m3s == pytest.approx(0.0)
        assert indexed[(delta, 3)].discharge_response_m3s == pytest.approx(0.0)
        assert indexed[(delta, 6)].response_per_effective_release_unit == pytest.approx(0.25)
        assert indexed[(delta, 12)].response_per_effective_release_unit == pytest.approx(0.25)
    assert indexed[(-20.0, 12)].discharge_response_m3s == pytest.approx(-5.0)
    assert indexed[(20.0, 12)].discharge_response_m3s == pytest.approx(5.0)
    assert all(row.zero_response_before_lag_passed for row in audit.responses)
    assert all(row.signed_response_passed for row in audit.responses)
    assert not any(row.response_collapsed_after_lag for row in audit.responses)


def test_discharge_floor_exposes_post_lag_response_collapse() -> None:
    audit = audit_counterfactual_release_steps(
        parameters=_parameters(drift=-100.0),
        state=_state(discharge=0.0),
        inputs=_inputs(),
        issue_time=ISSUE,
        release_deltas_m3s=(10.0,),
    )

    post_lag = [row for row in audit.responses if row.horizon_hours in (6, 12)]
    assert all(row.effective_release_delta_m3s > 0.0 for row in post_lag)
    assert all(row.response_collapsed_after_lag for row in post_lag)
    assert all(row.scenario_clipped_at_target for row in post_lag)


def test_signed_response_tolerates_machine_precision_noise() -> None:
    audit = audit_counterfactual_release_steps(
        parameters=_parameters(),
        state=_state(),
        inputs=_inputs(action=10.1),
        issue_time=ISSUE,
        release_deltas_m3s=(-10.0, 10.0),
    )

    assert all(row.signed_response_passed for row in audit.responses)
