"""Counterfactual release-step responses for the action-innovation kernel."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from data_agent.uwm.geospatial_kernel_v2.action_conditioned_transition import (
    HourlyActionForcingSeries,
    OutletTransitionState,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    ActionInnovationTransitionParameters,
    CausalActionInnovationGeospatialKernel,
)

COUNTERFACTUAL_ACTION_RESPONSE_SCHEMA = "gwm.geospatial_kernel.counterfactual_action_response.v1"
DEFAULT_RELEASE_STEP_DELTAS_M3S = (-50.0, -10.0, 10.0, 50.0)
DEFAULT_RESPONSE_HORIZONS_HOURS = (1, 3, 6, 12)
RESPONSE_TOLERANCE_M3S = 1e-9


class ActionInnovationForecastStepProtocol(Protocol):
    valid_at: datetime
    effective_action_release_m3s: float
    clipped: bool


class ActionInnovationForecastProtocol(Protocol):
    target_discharge_m3s: tuple[float, ...]
    steps: tuple[ActionInnovationForecastStepProtocol, ...]


class ActionInnovationKernelProtocol(Protocol):
    parameters: ActionInnovationTransitionParameters

    def forecast(
        self,
        state: OutletTransitionState,
        inputs: HourlyActionForcingSeries,
        *,
        issue_time: datetime,
        target_valid_times: tuple[datetime, ...],
    ) -> ActionInnovationForecastProtocol: ...


@dataclass(frozen=True)
class ReleaseStepScenario:
    requested_release_delta_m3s: float
    inputs: HourlyActionForcingSeries
    forecast: ActionInnovationForecastProtocol
    action_floor_step_count: int
    action_step_count: int


@dataclass(frozen=True)
class CounterfactualActionResponse:
    requested_release_delta_m3s: float
    horizon_hours: int
    baseline_discharge_m3s: float
    scenario_discharge_m3s: float
    discharge_response_m3s: float
    effective_release_delta_m3s: float
    response_per_effective_release_unit: float | None
    zero_response_required_before_lag: bool
    zero_response_before_lag_passed: bool
    signed_response_passed: bool
    response_collapsed_after_lag: bool
    baseline_clipped_at_target: bool
    scenario_clipped_at_target: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": COUNTERFACTUAL_ACTION_RESPONSE_SCHEMA,
            "requested_release_delta_m3s": self.requested_release_delta_m3s,
            "horizon_hours": self.horizon_hours,
            "baseline_discharge_m3s": self.baseline_discharge_m3s,
            "scenario_discharge_m3s": self.scenario_discharge_m3s,
            "discharge_response_m3s": self.discharge_response_m3s,
            "effective_release_delta_m3s": self.effective_release_delta_m3s,
            "response_per_effective_release_unit": (
                ""
                if self.response_per_effective_release_unit is None
                else self.response_per_effective_release_unit
            ),
            "zero_response_required_before_lag": self.zero_response_required_before_lag,
            "zero_response_before_lag_passed": self.zero_response_before_lag_passed,
            "signed_response_passed": self.signed_response_passed,
            "response_collapsed_after_lag": self.response_collapsed_after_lag,
            "baseline_clipped_at_target": self.baseline_clipped_at_target,
            "scenario_clipped_at_target": self.scenario_clipped_at_target,
        }


@dataclass(frozen=True)
class CounterfactualActionResponseAudit:
    issue_time: datetime
    baseline_forecast: ActionInnovationForecastProtocol
    scenarios: tuple[ReleaseStepScenario, ...]
    responses: tuple[CounterfactualActionResponse, ...]


def apply_release_step(
    inputs: HourlyActionForcingSeries,
    *,
    issue_time: datetime,
    release_delta_m3s: float,
    through_time: datetime,
) -> tuple[HourlyActionForcingSeries, int, int]:
    """Apply a persistent release delta strictly after issue time.

    Negative releases are floored at zero. The returned counts cover only the
    intervention support through the last requested target.
    """

    if issue_time.tzinfo is None or issue_time.utcoffset() is None:
        raise ValueError("counterfactual_release_step_issue_time_invalid")
    if through_time.tzinfo is None or through_time.utcoffset() is None:
        raise ValueError("counterfactual_release_step_through_time_invalid")
    if through_time <= issue_time:
        raise ValueError("counterfactual_release_step_support_invalid")
    delta = float(release_delta_m3s)
    if not math.isfinite(delta) or math.isclose(delta, 0.0, abs_tol=0.0):
        raise ValueError("counterfactual_release_step_delta_invalid")

    action: list[float] = []
    floor_count = 0
    step_count = 0
    for valid_at, value in zip(inputs.valid_times, inputs.action_release_m3s, strict=True):
        if valid_at > issue_time:
            raw = value + delta
            updated = max(0.0, raw)
            if valid_at <= through_time:
                step_count += 1
                floor_count += int(raw < 0.0)
            action.append(updated)
        else:
            action.append(value)
    if step_count == 0:
        raise ValueError("counterfactual_release_step_axis_missing")
    scenario = HourlyActionForcingSeries(
        valid_times=inputs.valid_times,
        action_release_m3s=tuple(action),
        nwm_lateral_inflow_m3s=inputs.nwm_lateral_inflow_m3s,
        action_provenance_id=(
            f"{inputs.action_provenance_id}|counterfactual-release-step:"
            f"issue={issue_time.isoformat()}:delta_m3s={delta}"
        ),
        forcing_provenance_id=inputs.forcing_provenance_id,
        action_plan_vintage_verified=inputs.action_plan_vintage_verified,
        forcing_vintage_verified=inputs.forcing_vintage_verified,
    )
    return scenario, floor_count, step_count


def audit_counterfactual_release_steps(
    *,
    parameters: ActionInnovationTransitionParameters,
    state: OutletTransitionState,
    inputs: HourlyActionForcingSeries,
    issue_time: datetime,
    release_deltas_m3s: tuple[float, ...] = DEFAULT_RELEASE_STEP_DELTAS_M3S,
    horizons_hours: tuple[int, ...] = DEFAULT_RESPONSE_HORIZONS_HOURS,
    tolerance_m3s: float = RESPONSE_TOLERANCE_M3S,
    kernel: ActionInnovationKernelProtocol | None = None,
) -> CounterfactualActionResponseAudit:
    """Compare release-step scenarios with the unchanged historical action plan."""

    deltas = tuple(float(value) for value in release_deltas_m3s)
    horizons = tuple(horizons_hours)
    if (
        not deltas
        or tuple(sorted(set(deltas))) != deltas
        or any(not math.isfinite(value) or value == 0.0 for value in deltas)
    ):
        raise ValueError("counterfactual_release_step_deltas_invalid")
    if (
        not horizons
        or tuple(sorted(set(horizons))) != horizons
        or any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value not in parameters.supported_forecast_horizons_hours
            for value in horizons
        )
    ):
        raise ValueError("counterfactual_release_step_horizons_invalid")
    tolerance = float(tolerance_m3s)
    if not math.isfinite(tolerance) or tolerance < 0.0:
        raise ValueError("counterfactual_release_step_tolerance_invalid")

    targets = tuple(issue_time + timedelta(hours=value) for value in horizons)
    active_kernel = kernel or CausalActionInnovationGeospatialKernel(parameters)
    if active_kernel.parameters != parameters:
        raise ValueError("counterfactual_release_step_kernel_parameters_mismatch")
    baseline = active_kernel.forecast(
        state,
        inputs,
        issue_time=issue_time,
        target_valid_times=targets,
    )
    baseline_steps = {step.valid_at: step for step in baseline.steps}
    first_possible_response_horizon = min(parameters.support.lag_hours) + 1
    scenarios: list[ReleaseStepScenario] = []
    responses: list[CounterfactualActionResponse] = []
    for delta in deltas:
        scenario_inputs, floor_count, step_count = apply_release_step(
            inputs,
            issue_time=issue_time,
            release_delta_m3s=delta,
            through_time=targets[-1],
        )
        forecast = active_kernel.forecast(
            state,
            scenario_inputs,
            issue_time=issue_time,
            target_valid_times=targets,
        )
        scenarios.append(
            ReleaseStepScenario(
                requested_release_delta_m3s=delta,
                inputs=scenario_inputs,
                forecast=forecast,
                action_floor_step_count=floor_count,
                action_step_count=step_count,
            )
        )
        scenario_steps = {step.valid_at: step for step in forecast.steps}
        for offset, (horizon, target) in enumerate(zip(horizons, targets, strict=True)):
            baseline_value = baseline.target_discharge_m3s[offset]
            scenario_value = forecast.target_discharge_m3s[offset]
            response = scenario_value - baseline_value
            baseline_step = baseline_steps[target]
            scenario_step = scenario_steps[target]
            effective_delta = (
                scenario_step.effective_action_release_m3s
                - baseline_step.effective_action_release_m3s
            )
            ratio = (
                None
                if math.isclose(effective_delta, 0.0, abs_tol=tolerance)
                else response / effective_delta
            )
            before_lag = horizon < first_possible_response_horizon
            zero_passed = not before_lag or math.isclose(
                response, 0.0, rel_tol=0.0, abs_tol=tolerance
            )
            if effective_delta > tolerance:
                signed_passed = response >= -tolerance
            elif effective_delta < -tolerance:
                signed_passed = response <= tolerance
            else:
                signed_passed = True
            collapsed = (
                not before_lag
                and not math.isclose(effective_delta, 0.0, abs_tol=tolerance)
                and math.isclose(response, 0.0, rel_tol=0.0, abs_tol=tolerance)
            )
            responses.append(
                CounterfactualActionResponse(
                    requested_release_delta_m3s=delta,
                    horizon_hours=horizon,
                    baseline_discharge_m3s=baseline_value,
                    scenario_discharge_m3s=scenario_value,
                    discharge_response_m3s=response,
                    effective_release_delta_m3s=effective_delta,
                    response_per_effective_release_unit=ratio,
                    zero_response_required_before_lag=before_lag,
                    zero_response_before_lag_passed=zero_passed,
                    signed_response_passed=signed_passed,
                    response_collapsed_after_lag=collapsed,
                    baseline_clipped_at_target=baseline_step.clipped,
                    scenario_clipped_at_target=scenario_step.clipped,
                )
            )
    return CounterfactualActionResponseAudit(
        issue_time=issue_time,
        baseline_forecast=baseline,
        scenarios=tuple(scenarios),
        responses=tuple(responses),
    )
