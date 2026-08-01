from datetime import timedelta

import pytest

from data_agent.test_geospatial_kernel_counterfactual_action_response import (
    ISSUE,
    _inputs,
    _parameters,
    _state,
)
from data_agent.uwm.geospatial_kernel_v2.boundary_preserving_action_innovation import (
    BoundaryPreservingActionInnovationGeospatialKernel,
    apply_boundary_preserving_increment,
)
from data_agent.uwm.geospatial_kernel_v2.counterfactual_action_response import (
    audit_counterfactual_release_steps,
)


@pytest.mark.parametrize(
    ("previous", "increment", "maximum"),
    (
        (10.0, -100.0, 1_000.0),
        (990.0, 100.0, 1_000.0),
        (100.0, -5.0, 1_000.0),
        (100.0, 5.0, 1_000.0),
    ),
)
def test_boundary_map_stays_bounded_without_hard_clipping(previous, increment, maximum) -> None:
    result = apply_boundary_preserving_increment(
        previous_discharge_m3s=previous,
        requested_increment_m3s=increment,
        maximum_discharge_m3s=maximum,
    )

    assert 0.0 < result.discharge_m3s < maximum
    assert result.local_increment_retention > 0.0
    assert result.local_increment_retention <= 1.0
    assert result.at_lower_boundary is False
    assert result.at_upper_boundary is False


@pytest.mark.parametrize("increment", (-1e-5, 1e-5))
def test_boundary_map_is_locally_first_order_equivalent_to_addition(increment) -> None:
    result = apply_boundary_preserving_increment(
        previous_discharge_m3s=100.0,
        requested_increment_m3s=increment,
        maximum_discharge_m3s=1_000.0,
    )

    assert result.local_increment_retention == pytest.approx(1.0, rel=1e-6)


def test_boundary_preserving_forecast_uses_frozen_increment_without_clip() -> None:
    parameters = _parameters(drift=-100.0)
    forecast = BoundaryPreservingActionInnovationGeospatialKernel(parameters).forecast(
        _state(discharge=10.0),
        _inputs(),
        issue_time=ISSUE,
        target_valid_times=(ISSUE + timedelta(hours=1), ISSUE + timedelta(hours=12)),
    )

    assert all(
        0.0 < value < parameters.maximum_discharge_m3s for value in forecast.target_discharge_m3s
    )
    assert any(step.hard_clip_would_apply for step in forecast.steps)
    assert all(step.clipped is False for step in forecast.steps)
    assert forecast.future_observations_used is False
    assert forecast.admitted is False


def test_boundary_preserving_kernel_can_use_common_counterfactual_audit() -> None:
    parameters = _parameters(drift=-100.0)
    kernel = BoundaryPreservingActionInnovationGeospatialKernel(parameters)
    audit = audit_counterfactual_release_steps(
        parameters=parameters,
        state=_state(discharge=10.0),
        inputs=_inputs(),
        issue_time=ISSUE,
        release_deltas_m3s=(-10.0, 10.0),
        kernel=kernel,
    )

    assert all(row.zero_response_before_lag_passed for row in audit.responses)
    assert all(row.signed_response_passed for row in audit.responses)
    assert not any(step.clipped for scenario in audit.scenarios for step in scenario.forecast.steps)
