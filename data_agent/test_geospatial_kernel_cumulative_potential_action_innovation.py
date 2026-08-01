from datetime import timedelta

import pytest

from data_agent.test_geospatial_kernel_counterfactual_action_response import (
    ISSUE,
    _inputs,
    _parameters,
    _state,
)
from data_agent.uwm.geospatial_kernel_v2.counterfactual_action_response import (
    audit_counterfactual_release_steps,
)
from data_agent.uwm.geospatial_kernel_v2.cumulative_potential_action_innovation import (
    CumulativePotentialActionInnovationGeospatialKernel,
    project_cumulative_potential,
)


def test_anchored_projection_is_monotone_and_bounded() -> None:
    projections = [
        project_cumulative_potential(
            anchor_discharge_m3s=100.0,
            cumulative_potential_m3s=potential,
            maximum_discharge_m3s=1_000.0,
        )
        for potential in (-1_000.0, -10.0, 0.0, 10.0, 1_000.0)
    ]

    values = [value.discharge_m3s for value in projections]
    assert values == sorted(values)
    assert all(0.0 < value < 1_000.0 for value in values)
    assert projections[2].discharge_m3s == 100.0


def test_cumulative_state_writeback_makes_split_rollout_equal_one_shot() -> None:
    parameters = _parameters(drift=-0.5)
    kernel = CumulativePotentialActionInnovationGeospatialKernel(parameters)
    one_shot = kernel.forecast(
        _state(),
        _inputs(),
        issue_time=ISSUE,
        target_valid_times=(ISSUE + timedelta(hours=12),),
    )
    first = kernel.forecast(
        _state(),
        _inputs(),
        issue_time=ISSUE,
        target_valid_times=(ISSUE + timedelta(hours=6),),
    )
    second = kernel.forecast(
        first.final_state,
        _inputs(),
        issue_time=ISSUE + timedelta(hours=6),
        target_valid_times=(ISSUE + timedelta(hours=12),),
    )

    assert second.final_state.anchor_discharge_m3s == one_shot.final_state.anchor_discharge_m3s
    assert second.final_state.cumulative_potential_m3s == pytest.approx(
        one_shot.final_state.cumulative_potential_m3s
    )
    assert second.final_state.discharge_m3s == pytest.approx(one_shot.final_state.discharge_m3s)


def test_cumulative_potential_preserves_counterfactual_release_order() -> None:
    parameters = _parameters(drift=-100.0)
    kernel = CumulativePotentialActionInnovationGeospatialKernel(parameters)
    audit = audit_counterfactual_release_steps(
        parameters=parameters,
        state=_state(discharge=10.0),
        inputs=_inputs(),
        issue_time=ISSUE,
        release_deltas_m3s=(-50.0, -10.0, 10.0, 50.0),
        kernel=kernel,
    )

    for horizon in (1, 3, 6, 12):
        selected = sorted(
            (
                row.requested_release_delta_m3s,
                row.scenario_discharge_m3s,
            )
            for row in audit.responses
            if row.horizon_hours == horizon
        )
        values = [value for _, value in selected]
        assert values == sorted(values)
    assert all(row.zero_response_before_lag_passed for row in audit.responses)
    assert all(row.signed_response_passed for row in audit.responses)
