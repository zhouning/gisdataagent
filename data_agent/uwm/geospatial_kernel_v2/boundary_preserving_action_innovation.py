"""Boundary-preserving state updates for frozen action-innovation increments."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from data_agent.uwm.geospatial_kernel_v2.action_conditioned_transition import (
    HourlyActionForcingSeries,
    OutletTransitionState,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    ActionInnovationTransitionParameters,
)

BOUNDARY_PRESERVING_INCREMENT_SCHEMA = "gwm.geospatial_kernel.boundary_preserving_increment.v1"
BOUNDARY_PRESERVING_FORECAST_SCHEMA = (
    "gwm.geospatial_kernel.boundary_preserving_action_innovation_forecast.v1"
)
BOUNDARY_PRESERVING_FORMULA = (
    "increment<0: q_next=q+q*expm1(increment/q); "
    "increment>0: q_next=q+(q_max-q)*(-expm1(-increment/(q_max-q)))"
)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True)
class BoundaryPreservingIncrement:
    previous_discharge_m3s: float
    requested_increment_m3s: float
    unbounded_discharge_m3s: float
    applied_increment_m3s: float
    discharge_m3s: float
    local_increment_retention: float
    boundary_adjusted: bool
    hard_clip_would_apply: bool
    at_lower_boundary: bool
    at_upper_boundary: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": BOUNDARY_PRESERVING_INCREMENT_SCHEMA,
            "formula": BOUNDARY_PRESERVING_FORMULA,
            "previous_discharge_m3s": self.previous_discharge_m3s,
            "requested_increment_m3s": self.requested_increment_m3s,
            "unbounded_discharge_m3s": self.unbounded_discharge_m3s,
            "applied_increment_m3s": self.applied_increment_m3s,
            "discharge_m3s": self.discharge_m3s,
            "local_increment_retention": self.local_increment_retention,
            "boundary_adjusted": self.boundary_adjusted,
            "hard_clip_would_apply": self.hard_clip_would_apply,
            "at_lower_boundary": self.at_lower_boundary,
            "at_upper_boundary": self.at_upper_boundary,
            "adds_fitted_parameter": False,
        }


def apply_boundary_preserving_increment(
    *,
    previous_discharge_m3s: float,
    requested_increment_m3s: float,
    maximum_discharge_m3s: float,
) -> BoundaryPreservingIncrement:
    """Map an additive increment into the closed physical discharge interval."""

    previous = float(previous_discharge_m3s)
    increment = float(requested_increment_m3s)
    maximum = float(maximum_discharge_m3s)
    if (
        not math.isfinite(previous)
        or not math.isfinite(increment)
        or not math.isfinite(maximum)
        or maximum <= 0.0
        or previous < 0.0
        or previous > maximum
    ):
        raise ValueError("boundary_preserving_increment_inputs_invalid")

    raw = previous + increment
    if increment < 0.0:
        if previous == 0.0:
            predicted = 0.0
        else:
            predicted = previous + previous * math.expm1(increment / previous)
            if predicted <= 0.0:
                predicted = math.nextafter(0.0, 1.0)
    elif increment > 0.0:
        headroom = maximum - previous
        if headroom == 0.0:
            predicted = maximum
        else:
            predicted = previous + headroom * (-math.expm1(-increment / headroom))
            if predicted >= maximum:
                predicted = math.nextafter(maximum, 0.0)
    else:
        predicted = previous
    applied = predicted - previous
    retention = 1.0 if increment == 0.0 else applied / increment
    return BoundaryPreservingIncrement(
        previous_discharge_m3s=previous,
        requested_increment_m3s=increment,
        unbounded_discharge_m3s=raw,
        applied_increment_m3s=applied,
        discharge_m3s=predicted,
        local_increment_retention=retention,
        boundary_adjusted=not math.isclose(predicted, raw, rel_tol=0.0, abs_tol=1e-12),
        hard_clip_would_apply=raw < 0.0 or raw > maximum,
        at_lower_boundary=predicted == 0.0,
        at_upper_boundary=predicted == maximum,
    )


@dataclass(frozen=True)
class BoundaryPreservingActionInnovationStep:
    valid_at: datetime
    previous_discharge_m3s: float
    effective_action_release_m3s: float
    previous_effective_action_release_m3s: float
    effective_action_change_m3s: float
    nwm_lateral_inflow_m3s: float
    predicted_increment_m3s: float
    applied_increment_m3s: float
    predicted_discharge_m3s: float
    local_increment_retention: float
    boundary_adjusted: bool
    hard_clip_would_apply: bool
    clipped: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "valid_at": self.valid_at.isoformat(),
            "previous_discharge_m3s": self.previous_discharge_m3s,
            "effective_action_release_m3s": self.effective_action_release_m3s,
            "previous_effective_action_release_m3s": (self.previous_effective_action_release_m3s),
            "effective_action_change_m3s": self.effective_action_change_m3s,
            "nwm_lateral_inflow_m3s": self.nwm_lateral_inflow_m3s,
            "predicted_increment_m3s": self.predicted_increment_m3s,
            "applied_increment_m3s": self.applied_increment_m3s,
            "predicted_discharge_m3s": self.predicted_discharge_m3s,
            "local_increment_retention": self.local_increment_retention,
            "boundary_adjusted": self.boundary_adjusted,
            "hard_clip_would_apply": self.hard_clip_would_apply,
            "clipped": self.clipped,
        }


@dataclass(frozen=True)
class BoundaryPreservingActionInnovationForecast:
    issue_time: datetime
    initial_state: OutletTransitionState
    issue_state: OutletTransitionState
    final_state: OutletTransitionState
    target_valid_times: tuple[datetime, ...]
    target_discharge_m3s: tuple[float, ...]
    steps: tuple[BoundaryPreservingActionInnovationStep, ...]
    parameters: ActionInnovationTransitionParameters
    future_observations_used: bool
    operational_vintages_verified: bool
    admitted: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": BOUNDARY_PRESERVING_FORECAST_SCHEMA,
            "issue_time": self.issue_time.isoformat(),
            "initial_state": self.initial_state.as_dict(),
            "issue_state": self.issue_state.as_dict(),
            "final_state": self.final_state.as_dict(),
            "target_valid_times": [value.isoformat() for value in self.target_valid_times],
            "target_discharge_m3s": list(self.target_discharge_m3s),
            "steps": [value.as_dict() for value in self.steps],
            "future_observations_used": self.future_observations_used,
            "operational_vintages_verified": self.operational_vintages_verified,
            "admitted": self.admitted,
            "parameters": self.parameters.as_dict(),
            "boundary_update_formula": BOUNDARY_PRESERVING_FORMULA,
            "adds_fitted_parameter": False,
            "replaces_frozen_candidate": False,
        }


class BoundaryPreservingActionInnovationGeospatialKernel:
    """Apply frozen increments through a smooth, bounded state map."""

    def __init__(self, parameters: ActionInnovationTransitionParameters) -> None:
        if not isinstance(parameters, ActionInnovationTransitionParameters):
            raise TypeError("action_innovation_transition_parameters_required")
        self.parameters = parameters

    def forecast(
        self,
        state: OutletTransitionState,
        inputs: HourlyActionForcingSeries,
        *,
        issue_time: datetime,
        target_valid_times: tuple[datetime, ...],
    ) -> BoundaryPreservingActionInnovationForecast:
        if not isinstance(state, OutletTransitionState):
            raise TypeError("outlet_transition_state_required")
        if not isinstance(inputs, HourlyActionForcingSeries):
            raise TypeError("hourly_action_forcing_series_required")
        if not _aware(issue_time) or state.available_at > issue_time:
            raise ValueError("outlet_transition_state_not_available_at_issue")
        if state.valid_at > issue_time:
            raise ValueError("future_outlet_transition_state_forbidden")
        if state.discharge_m3s > self.parameters.maximum_discharge_m3s:
            raise ValueError("outlet_transition_state_above_maximum")
        if self.parameters.training_data_end >= issue_time:
            raise ValueError("action_innovation_training_must_precede_issue_time")
        targets = tuple(target_valid_times)
        if (
            not targets
            or any(not _aware(value) for value in targets)
            or tuple(sorted(set(targets))) != targets
            or targets[0] <= issue_time
        ):
            raise ValueError("action_innovation_target_times_invalid")
        timestep = timedelta(seconds=self.parameters.timestep_seconds)
        offsets = [
            (value - state.valid_at).total_seconds() / self.parameters.timestep_seconds
            for value in targets
        ]
        if any(not value.is_integer() or value <= 0 for value in offsets):
            raise ValueError("action_innovation_targets_must_align_to_timestep")
        issue_offsets = tuple(
            (value - issue_time).total_seconds() / self.parameters.timestep_seconds
            for value in targets
        )
        if any(
            not value.is_integer()
            or int(value) not in self.parameters.supported_forecast_horizons_hours
            for value in issue_offsets
        ):
            raise ValueError("action_innovation_target_horizon_not_supported")

        action, forcing = inputs._maps()
        support = self.parameters.support
        cursor = state.valid_at
        previous = state.discharge_m3s
        step_rows: list[BoundaryPreservingActionInnovationStep] = []
        states: dict[datetime, OutletTransitionState] = {}
        while cursor < targets[-1]:
            cursor += timestep
            lag_times = tuple(cursor - timedelta(hours=lag) for lag in support.lag_hours)
            previous_lag_times = tuple(value - timedelta(hours=1) for value in lag_times)
            if (
                cursor not in forcing
                or any(value not in action for value in lag_times)
                or any(value not in action for value in previous_lag_times)
            ):
                raise ValueError("action_innovation_required_input_missing")
            effective_action = _weighted_action(action, lag_times, support.lag_weights)
            previous_effective_action = _weighted_action(
                action, previous_lag_times, support.lag_weights
            )
            action_change = effective_action - previous_effective_action
            increment = (
                self.parameters.baseline_drift_m3s_per_hour
                + self.parameters.action_change_coefficient * action_change
                + self.parameters.forcing_coefficient * forcing[cursor]
            )
            bounded = apply_boundary_preserving_increment(
                previous_discharge_m3s=previous,
                requested_increment_m3s=increment,
                maximum_discharge_m3s=self.parameters.maximum_discharge_m3s,
            )
            step_rows.append(
                BoundaryPreservingActionInnovationStep(
                    valid_at=cursor,
                    previous_discharge_m3s=previous,
                    effective_action_release_m3s=effective_action,
                    previous_effective_action_release_m3s=previous_effective_action,
                    effective_action_change_m3s=action_change,
                    nwm_lateral_inflow_m3s=forcing[cursor],
                    predicted_increment_m3s=increment,
                    applied_increment_m3s=bounded.applied_increment_m3s,
                    predicted_discharge_m3s=bounded.discharge_m3s,
                    local_increment_retention=bounded.local_increment_retention,
                    boundary_adjusted=bounded.boundary_adjusted,
                    hard_clip_would_apply=bounded.hard_clip_would_apply,
                    clipped=False,
                )
            )
            states[cursor] = OutletTransitionState(
                valid_at=cursor,
                available_at=issue_time,
                discharge_m3s=bounded.discharge_m3s,
                provenance_id=(
                    f"{self.parameters.provenance_id}|boundary-preserving-forecast:"
                    f"issue={issue_time.isoformat()}:valid={cursor.isoformat()}"
                ),
                evidence_level="candidate",
                observed=False,
            )
            previous = bounded.discharge_m3s
        if issue_time == state.valid_at:
            issue_state = state
        else:
            try:
                issue_state = states[issue_time]
            except KeyError as exc:
                raise ValueError("action_innovation_issue_time_not_on_state_axis") from exc
        target_states = tuple(states[value] for value in targets)
        operational = (
            inputs.action_plan_vintage_verified
            and inputs.forcing_vintage_verified
            and state.evidence_level == "authoritative"
        )
        return BoundaryPreservingActionInnovationForecast(
            issue_time=issue_time,
            initial_state=state,
            issue_state=issue_state,
            final_state=target_states[-1],
            target_valid_times=targets,
            target_discharge_m3s=tuple(value.discharge_m3s for value in target_states),
            steps=tuple(step_rows),
            parameters=self.parameters,
            future_observations_used=False,
            operational_vintages_verified=operational,
            admitted=False,
        )


def _weighted_action(
    action: dict[datetime, float],
    times: tuple[datetime, ...],
    weights: tuple[float, ...],
) -> float:
    return sum(weight * action[valid_at] for weight, valid_at in zip(weights, times, strict=True))
