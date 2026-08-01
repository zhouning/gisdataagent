"""Cumulative latent-potential transitions for frozen action innovations."""

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

CUMULATIVE_POTENTIAL_STATE_SCHEMA = "gwm.geospatial_kernel.cumulative_action_potential_state.v1"
CUMULATIVE_POTENTIAL_FORECAST_SCHEMA = (
    "gwm.geospatial_kernel.cumulative_potential_action_innovation_forecast.v1"
)
CUMULATIVE_POTENTIAL_FORMULA = (
    "potential[t]=potential[t-1]+drift+action_change_beta*delta_effective_action[t]+"
    "forcing_beta*nwm_lateral[t]; discharge[t]=anchored_monotone_saturation("
    "anchor_discharge,potential[t],maximum_discharge)"
)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True)
class AnchoredPotentialProjection:
    anchor_discharge_m3s: float
    cumulative_potential_m3s: float
    unbounded_discharge_m3s: float
    discharge_m3s: float
    potential_retention: float
    boundary_adjusted: bool
    hard_clip_would_apply: bool


def project_cumulative_potential(
    *,
    anchor_discharge_m3s: float,
    cumulative_potential_m3s: float,
    maximum_discharge_m3s: float,
) -> AnchoredPotentialProjection:
    """Project one cumulative latent potential through an anchored monotone map."""

    anchor = float(anchor_discharge_m3s)
    potential = float(cumulative_potential_m3s)
    maximum = float(maximum_discharge_m3s)
    if (
        not math.isfinite(anchor)
        or not math.isfinite(potential)
        or not math.isfinite(maximum)
        or maximum <= 0.0
        or anchor < 0.0
        or anchor > maximum
    ):
        raise ValueError("cumulative_potential_projection_inputs_invalid")
    raw = anchor + potential
    if potential < 0.0:
        if anchor == 0.0:
            discharge = 0.0
        else:
            discharge = anchor * math.exp(potential / anchor)
            if discharge <= 0.0:
                discharge = math.nextafter(0.0, 1.0)
    elif potential > 0.0:
        headroom = maximum - anchor
        if headroom == 0.0:
            discharge = maximum
        else:
            discharge = anchor + headroom * (-math.expm1(-potential / headroom))
            if discharge >= maximum:
                discharge = math.nextafter(maximum, 0.0)
    else:
        discharge = anchor
    retention = 1.0 if potential == 0.0 else (discharge - anchor) / potential
    return AnchoredPotentialProjection(
        anchor_discharge_m3s=anchor,
        cumulative_potential_m3s=potential,
        unbounded_discharge_m3s=raw,
        discharge_m3s=discharge,
        potential_retention=retention,
        boundary_adjusted=not math.isclose(discharge, raw, rel_tol=0.0, abs_tol=1e-12),
        hard_clip_would_apply=raw < 0.0 or raw > maximum,
    )


@dataclass(frozen=True)
class CumulativePotentialState:
    valid_at: datetime
    available_at: datetime
    anchor_discharge_m3s: float
    cumulative_potential_m3s: float
    maximum_discharge_m3s: float
    discharge_m3s: float
    provenance_id: str
    evidence_level: str
    observed_anchor: bool

    def __post_init__(self) -> None:
        if (
            not _aware(self.valid_at)
            or not _aware(self.available_at)
            or not self.provenance_id.strip()
            or self.evidence_level not in {"authoritative", "derived", "candidate"}
            or not isinstance(self.observed_anchor, bool)
        ):
            raise ValueError("cumulative_potential_state_metadata_invalid")
        projection = project_cumulative_potential(
            anchor_discharge_m3s=self.anchor_discharge_m3s,
            cumulative_potential_m3s=self.cumulative_potential_m3s,
            maximum_discharge_m3s=self.maximum_discharge_m3s,
        )
        if not math.isclose(
            float(self.discharge_m3s),
            projection.discharge_m3s,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("cumulative_potential_state_discharge_inconsistent")
        object.__setattr__(self, "anchor_discharge_m3s", projection.anchor_discharge_m3s)
        object.__setattr__(self, "cumulative_potential_m3s", projection.cumulative_potential_m3s)
        object.__setattr__(self, "maximum_discharge_m3s", float(self.maximum_discharge_m3s))
        object.__setattr__(self, "discharge_m3s", projection.discharge_m3s)

    @classmethod
    def from_outlet_state(
        cls,
        state: OutletTransitionState,
        *,
        maximum_discharge_m3s: float,
    ) -> CumulativePotentialState:
        if not isinstance(state, OutletTransitionState):
            raise TypeError("outlet_transition_state_required")
        return cls(
            valid_at=state.valid_at,
            available_at=state.available_at,
            anchor_discharge_m3s=state.discharge_m3s,
            cumulative_potential_m3s=0.0,
            maximum_discharge_m3s=maximum_discharge_m3s,
            discharge_m3s=state.discharge_m3s,
            provenance_id=f"{state.provenance_id}|cumulative-potential-anchor",
            evidence_level=state.evidence_level,
            observed_anchor=state.observed,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": CUMULATIVE_POTENTIAL_STATE_SCHEMA,
            "valid_at": self.valid_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "anchor_discharge_m3s": self.anchor_discharge_m3s,
            "cumulative_potential_m3s": self.cumulative_potential_m3s,
            "maximum_discharge_m3s": self.maximum_discharge_m3s,
            "discharge_m3s": self.discharge_m3s,
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
            "observed_anchor": self.observed_anchor,
        }


@dataclass(frozen=True)
class CumulativePotentialActionInnovationStep:
    valid_at: datetime
    previous_discharge_m3s: float
    effective_action_release_m3s: float
    previous_effective_action_release_m3s: float
    effective_action_change_m3s: float
    nwm_lateral_inflow_m3s: float
    predicted_increment_m3s: float
    previous_cumulative_potential_m3s: float
    cumulative_potential_m3s: float
    predicted_discharge_m3s: float
    potential_retention: float
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
            "previous_cumulative_potential_m3s": self.previous_cumulative_potential_m3s,
            "cumulative_potential_m3s": self.cumulative_potential_m3s,
            "predicted_discharge_m3s": self.predicted_discharge_m3s,
            "potential_retention": self.potential_retention,
            "boundary_adjusted": self.boundary_adjusted,
            "hard_clip_would_apply": self.hard_clip_would_apply,
            "clipped": self.clipped,
        }


@dataclass(frozen=True)
class CumulativePotentialActionInnovationForecast:
    issue_time: datetime
    initial_state: CumulativePotentialState
    issue_state: CumulativePotentialState
    final_state: CumulativePotentialState
    target_valid_times: tuple[datetime, ...]
    target_discharge_m3s: tuple[float, ...]
    target_states: tuple[CumulativePotentialState, ...]
    steps: tuple[CumulativePotentialActionInnovationStep, ...]
    parameters: ActionInnovationTransitionParameters
    future_observations_used: bool
    operational_vintages_verified: bool
    admitted: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": CUMULATIVE_POTENTIAL_FORECAST_SCHEMA,
            "formula": CUMULATIVE_POTENTIAL_FORMULA,
            "issue_time": self.issue_time.isoformat(),
            "initial_state": self.initial_state.as_dict(),
            "issue_state": self.issue_state.as_dict(),
            "final_state": self.final_state.as_dict(),
            "target_valid_times": [value.isoformat() for value in self.target_valid_times],
            "target_discharge_m3s": list(self.target_discharge_m3s),
            "target_states": [value.as_dict() for value in self.target_states],
            "steps": [value.as_dict() for value in self.steps],
            "parameters": self.parameters.as_dict(),
            "future_observations_used": self.future_observations_used,
            "operational_vintages_verified": self.operational_vintages_verified,
            "admitted": self.admitted,
            "adds_fitted_parameter": False,
            "replaces_frozen_candidate": False,
        }


class CumulativePotentialActionInnovationGeospatialKernel:
    """Accumulate frozen innovations before a monotone boundary projection."""

    def __init__(self, parameters: ActionInnovationTransitionParameters) -> None:
        if not isinstance(parameters, ActionInnovationTransitionParameters):
            raise TypeError("action_innovation_transition_parameters_required")
        self.parameters = parameters

    def forecast(
        self,
        state: OutletTransitionState | CumulativePotentialState,
        inputs: HourlyActionForcingSeries,
        *,
        issue_time: datetime,
        target_valid_times: tuple[datetime, ...],
    ) -> CumulativePotentialActionInnovationForecast:
        initial = self._initial_state(state)
        if not isinstance(inputs, HourlyActionForcingSeries):
            raise TypeError("hourly_action_forcing_series_required")
        if not _aware(issue_time) or initial.available_at > issue_time:
            raise ValueError("cumulative_potential_state_not_available_at_issue")
        if initial.valid_at > issue_time:
            raise ValueError("future_cumulative_potential_state_forbidden")
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
            (value - initial.valid_at).total_seconds() / self.parameters.timestep_seconds
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
        cursor = initial.valid_at
        previous = initial.discharge_m3s
        potential = initial.cumulative_potential_m3s
        step_rows: list[CumulativePotentialActionInnovationStep] = []
        states: dict[datetime, CumulativePotentialState] = {}
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
            previous_potential = potential
            potential += increment
            projection = project_cumulative_potential(
                anchor_discharge_m3s=initial.anchor_discharge_m3s,
                cumulative_potential_m3s=potential,
                maximum_discharge_m3s=self.parameters.maximum_discharge_m3s,
            )
            step_rows.append(
                CumulativePotentialActionInnovationStep(
                    valid_at=cursor,
                    previous_discharge_m3s=previous,
                    effective_action_release_m3s=effective_action,
                    previous_effective_action_release_m3s=previous_effective_action,
                    effective_action_change_m3s=action_change,
                    nwm_lateral_inflow_m3s=forcing[cursor],
                    predicted_increment_m3s=increment,
                    previous_cumulative_potential_m3s=previous_potential,
                    cumulative_potential_m3s=potential,
                    predicted_discharge_m3s=projection.discharge_m3s,
                    potential_retention=projection.potential_retention,
                    boundary_adjusted=projection.boundary_adjusted,
                    hard_clip_would_apply=projection.hard_clip_would_apply,
                    clipped=False,
                )
            )
            states[cursor] = CumulativePotentialState(
                valid_at=cursor,
                available_at=issue_time,
                anchor_discharge_m3s=initial.anchor_discharge_m3s,
                cumulative_potential_m3s=potential,
                maximum_discharge_m3s=self.parameters.maximum_discharge_m3s,
                discharge_m3s=projection.discharge_m3s,
                provenance_id=(
                    f"{self.parameters.provenance_id}|cumulative-potential-forecast:"
                    f"issue={issue_time.isoformat()}:valid={cursor.isoformat()}"
                ),
                evidence_level="candidate",
                observed_anchor=initial.observed_anchor,
            )
            previous = projection.discharge_m3s
        issue_state = initial if issue_time == initial.valid_at else states[issue_time]
        target_states = tuple(states[value] for value in targets)
        operational = (
            inputs.action_plan_vintage_verified
            and inputs.forcing_vintage_verified
            and initial.evidence_level == "authoritative"
            and initial.observed_anchor
        )
        return CumulativePotentialActionInnovationForecast(
            issue_time=issue_time,
            initial_state=initial,
            issue_state=issue_state,
            final_state=target_states[-1],
            target_valid_times=targets,
            target_discharge_m3s=tuple(value.discharge_m3s for value in target_states),
            target_states=target_states,
            steps=tuple(step_rows),
            parameters=self.parameters,
            future_observations_used=False,
            operational_vintages_verified=operational,
            admitted=False,
        )

    def _initial_state(
        self, state: OutletTransitionState | CumulativePotentialState
    ) -> CumulativePotentialState:
        if isinstance(state, OutletTransitionState):
            if state.discharge_m3s > self.parameters.maximum_discharge_m3s:
                raise ValueError("outlet_transition_state_above_maximum")
            return CumulativePotentialState.from_outlet_state(
                state,
                maximum_discharge_m3s=self.parameters.maximum_discharge_m3s,
            )
        if isinstance(state, CumulativePotentialState):
            if state.maximum_discharge_m3s != self.parameters.maximum_discharge_m3s:
                raise ValueError("cumulative_potential_state_maximum_mismatch")
            return state
        raise TypeError("outlet_or_cumulative_potential_state_required")


def _weighted_action(
    action: dict[datetime, float],
    times: tuple[datetime, ...],
    weights: tuple[float, ...],
) -> float:
    return sum(weight * action[valid_at] for weight, valid_at in zip(weights, times, strict=True))
