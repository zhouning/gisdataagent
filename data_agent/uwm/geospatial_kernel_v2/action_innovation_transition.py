"""State-anchored action-innovation transitions over a fixed geographic path."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from data_agent.uwm.geospatial_kernel_v2.action_conditioned_transition import (
    GeographicResponseSupport,
    HourlyActionForcingSeries,
    OutletTransitionState,
    _document_bool,
    _document_float,
    _document_int,
    _document_text,
    _document_time,
    geographic_response_support_from_dict,
)

ACTION_INNOVATION_PARAMETERS_SCHEMA = (
    "gwm.geospatial_kernel.action_innovation_transition_parameters.v1"
)
ACTION_INNOVATION_FORECAST_SCHEMA = "gwm.geospatial_kernel.action_innovation_transition_forecast.v1"
ACTION_INNOVATION_FORMULA = (
    "q[t] = q[t-1] + drift + action_change_beta*"
    "(sum(w_lag*action[t-lag]) - sum(w_lag*action[t-1-lag])) + "
    "forcing_beta*nwm_lateral[t]"
)
ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS = (1, 3, 6, 12)
_EVIDENCE_LEVELS = {"authoritative", "derived", "candidate"}


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True)
class ActionInnovationTransitionParameters:
    support: GeographicResponseSupport
    baseline_drift_m3s_per_hour: float
    action_change_coefficient: float
    forcing_coefficient: float
    timestep_seconds: int
    supported_forecast_horizons_hours: tuple[int, ...]
    maximum_discharge_m3s: float
    training_data_start: datetime
    training_data_end: datetime
    training_sample_count: int
    provenance_id: str
    evidence_level: str
    admitted: bool
    outcome_calibrated: bool

    def __post_init__(self) -> None:
        if not isinstance(self.support, GeographicResponseSupport):
            raise TypeError("geographic_response_support_required")
        coefficients = np.asarray(
            (
                self.baseline_drift_m3s_per_hour,
                self.action_change_coefficient,
                self.forcing_coefficient,
            ),
            dtype=float,
        )
        if not np.isfinite(coefficients).all():
            raise ValueError("action_innovation_coefficients_must_be_finite")
        if self.action_change_coefficient < 0.0 or self.forcing_coefficient < 0.0:
            raise ValueError("action_innovation_response_coefficients_must_be_nonnegative")
        if (
            not isinstance(self.timestep_seconds, int)
            or isinstance(self.timestep_seconds, bool)
            or self.timestep_seconds != 3600
        ):
            raise ValueError("action_innovation_transition_requires_hourly_timestep")
        horizons = tuple(self.supported_forecast_horizons_hours)
        if horizons != ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS:
            raise ValueError("action_innovation_supported_forecast_horizons_invalid")
        object.__setattr__(self, "supported_forecast_horizons_hours", horizons)
        maximum = float(self.maximum_discharge_m3s)
        if not math.isfinite(maximum) or maximum <= 0.0:
            raise ValueError("action_innovation_maximum_discharge_invalid")
        object.__setattr__(self, "maximum_discharge_m3s", maximum)
        if (
            not _aware(self.training_data_start)
            or not _aware(self.training_data_end)
            or self.training_data_end <= self.training_data_start
        ):
            raise ValueError("action_innovation_training_window_invalid")
        if (
            not isinstance(self.training_sample_count, int)
            or isinstance(self.training_sample_count, bool)
            or self.training_sample_count < 3
        ):
            raise ValueError("action_innovation_training_sample_count_invalid")
        if not self.provenance_id.strip():
            raise ValueError("action_innovation_parameter_provenance_required")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("action_innovation_parameter_evidence_level_invalid")
        if not isinstance(self.admitted, bool) or not isinstance(self.outcome_calibrated, bool):
            raise ValueError("action_innovation_parameter_flags_must_be_boolean")
        if self.admitted and (self.evidence_level == "candidate" or not self.support.admitted):
            raise ValueError("unadmitted_action_innovation_support_cannot_be_admitted")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": ACTION_INNOVATION_PARAMETERS_SCHEMA,
            "support": self.support.as_dict(),
            "formula": ACTION_INNOVATION_FORMULA,
            "baseline_drift_m3s_per_hour": self.baseline_drift_m3s_per_hour,
            "state_persistence_coefficient_fixed": 1.0,
            "action_change_coefficient": self.action_change_coefficient,
            "forcing_coefficient": self.forcing_coefficient,
            "timestep_seconds": self.timestep_seconds,
            "supported_forecast_horizons_hours": list(self.supported_forecast_horizons_hours),
            "maximum_discharge_m3s": self.maximum_discharge_m3s,
            "training_data_start": self.training_data_start.isoformat(),
            "training_data_end": self.training_data_end.isoformat(),
            "training_sample_count": self.training_sample_count,
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
            "admitted": self.admitted,
            "outcome_calibrated": self.outcome_calibrated,
            "asymptotic_stability_claimed": False,
            "mass_conserving_network_routing_replacement": False,
        }


def action_innovation_transition_parameters_from_dict(
    payload: Mapping[str, object],
) -> ActionInnovationTransitionParameters:
    """Load serialized innovation parameters without weakening their claims."""

    if not isinstance(payload, Mapping):
        raise TypeError("action_innovation_parameter_document_mapping_required")
    expected_fields = {
        "schema",
        "support",
        "formula",
        "baseline_drift_m3s_per_hour",
        "state_persistence_coefficient_fixed",
        "action_change_coefficient",
        "forcing_coefficient",
        "timestep_seconds",
        "supported_forecast_horizons_hours",
        "maximum_discharge_m3s",
        "training_data_start",
        "training_data_end",
        "training_sample_count",
        "provenance_id",
        "evidence_level",
        "admitted",
        "outcome_calibrated",
        "asymptotic_stability_claimed",
        "mass_conserving_network_routing_replacement",
    }
    if set(payload) != expected_fields:
        raise ValueError("action_innovation_parameter_document_fields_invalid")
    if payload["schema"] != ACTION_INNOVATION_PARAMETERS_SCHEMA:
        raise ValueError("action_innovation_parameter_document_schema_invalid")
    serialized_horizons = payload["supported_forecast_horizons_hours"]
    if (
        payload["formula"] != ACTION_INNOVATION_FORMULA
        or payload["state_persistence_coefficient_fixed"] != 1.0
        or isinstance(payload["state_persistence_coefficient_fixed"], bool)
        or payload["asymptotic_stability_claimed"] is not False
        or payload["mass_conserving_network_routing_replacement"] is not False
        or not isinstance(serialized_horizons, list)
        or tuple(serialized_horizons) != ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS
        or any(
            not isinstance(value, int) or isinstance(value, bool) for value in serialized_horizons
        )
    ):
        raise ValueError("action_innovation_parameter_document_claims_invalid")
    return ActionInnovationTransitionParameters(
        support=geographic_response_support_from_dict(payload["support"]),
        baseline_drift_m3s_per_hour=_document_float(
            payload["baseline_drift_m3s_per_hour"], "innovation_parameter_baseline_drift"
        ),
        action_change_coefficient=_document_float(
            payload["action_change_coefficient"], "innovation_parameter_action_change"
        ),
        forcing_coefficient=_document_float(
            payload["forcing_coefficient"], "innovation_parameter_forcing"
        ),
        timestep_seconds=_document_int(
            payload["timestep_seconds"], "innovation_parameter_timestep_seconds"
        ),
        supported_forecast_horizons_hours=tuple(serialized_horizons),
        maximum_discharge_m3s=_document_float(
            payload["maximum_discharge_m3s"], "innovation_parameter_maximum_discharge"
        ),
        training_data_start=_document_time(
            payload["training_data_start"], "innovation_parameter_training_data_start"
        ),
        training_data_end=_document_time(
            payload["training_data_end"], "innovation_parameter_training_data_end"
        ),
        training_sample_count=_document_int(
            payload["training_sample_count"], "innovation_parameter_training_sample_count"
        ),
        provenance_id=_document_text(
            payload["provenance_id"], "innovation_parameter_provenance_id"
        ),
        evidence_level=_document_text(
            payload["evidence_level"], "innovation_parameter_evidence_level"
        ),
        admitted=_document_bool(payload["admitted"], "innovation_parameter_admitted"),
        outcome_calibrated=_document_bool(
            payload["outcome_calibrated"], "innovation_parameter_outcome_calibrated"
        ),
    )


@dataclass(frozen=True)
class ActionInnovationFitResult:
    parameters: ActionInnovationTransitionParameters
    design_rank: int
    design_condition_number: float
    design_singular_values: tuple[float, ...]
    training_increment_rmse_m3s: float

    def as_dict(self) -> dict[str, object]:
        return {
            "parameters": self.parameters.as_dict(),
            "design_rank": self.design_rank,
            "design_condition_number": self.design_condition_number,
            "design_singular_values": list(self.design_singular_values),
            "training_increment_rmse_m3s": self.training_increment_rmse_m3s,
        }


@dataclass(frozen=True)
class ActionInnovationTransitionStep:
    valid_at: datetime
    previous_discharge_m3s: float
    effective_action_release_m3s: float
    previous_effective_action_release_m3s: float
    effective_action_change_m3s: float
    nwm_lateral_inflow_m3s: float
    predicted_increment_m3s: float
    predicted_discharge_m3s: float
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
            "predicted_discharge_m3s": self.predicted_discharge_m3s,
            "clipped": self.clipped,
        }


@dataclass(frozen=True)
class ActionInnovationTransitionForecast:
    issue_time: datetime
    initial_state: OutletTransitionState
    issue_state: OutletTransitionState
    final_state: OutletTransitionState
    target_valid_times: tuple[datetime, ...]
    target_discharge_m3s: tuple[float, ...]
    steps: tuple[ActionInnovationTransitionStep, ...]
    parameters: ActionInnovationTransitionParameters
    future_observations_used: bool
    operational_vintages_verified: bool
    admitted: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": ACTION_INNOVATION_FORECAST_SCHEMA,
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
        }


def fit_action_innovation_transition(
    *,
    support: GeographicResponseSupport,
    observed_valid_times: tuple[datetime, ...],
    observed_discharge_m3s: tuple[float, ...],
    inputs: HourlyActionForcingSeries,
    maximum_discharge_m3s: float,
    provenance_id: str,
) -> ActionInnovationFitResult:
    """Fit discharge increments while keeping the path and lag weights frozen."""

    if not isinstance(support, GeographicResponseSupport):
        raise TypeError("geographic_response_support_required")
    times = tuple(observed_valid_times)
    observed = tuple(float(value) for value in observed_discharge_m3s)
    if (
        len(times) < 8
        or len(observed) != len(times)
        or any(not _aware(value) for value in times)
        or tuple(sorted(set(times))) != times
        or any(
            second - first != timedelta(hours=1)
            for first, second in zip(times, times[1:], strict=False)
        )
    ):
        raise ValueError("action_innovation_training_axis_invalid")
    observed_array = np.asarray(observed, dtype=float)
    if not np.isfinite(observed_array).all() or (observed_array < 0.0).any():
        raise ValueError("action_innovation_training_values_invalid")
    action, forcing = inputs._maps()
    rows: list[list[float]] = []
    targets: list[float] = []
    for index, valid_at in enumerate(times[1:], start=1):
        lag_times = tuple(valid_at - timedelta(hours=lag) for lag in support.lag_hours)
        previous_lag_times = tuple(value - timedelta(hours=1) for value in lag_times)
        if (
            valid_at not in forcing
            or any(value not in action for value in lag_times)
            or any(value not in action for value in previous_lag_times)
        ):
            continue
        effective_action = _weighted_action(action, lag_times, support.lag_weights)
        previous_effective_action = _weighted_action(
            action, previous_lag_times, support.lag_weights
        )
        rows.append([1.0, effective_action - previous_effective_action, forcing[valid_at]])
        targets.append(observed[index] - observed[index - 1])
    design = np.asarray(rows, dtype=float)
    target = np.asarray(targets, dtype=float)
    if design.shape[0] < 100 or design.shape[1] != 3:
        raise ValueError("action_innovation_training_support_insufficient")
    coefficients, _, rank, singular = np.linalg.lstsq(design, target, rcond=None)
    if rank != 3:
        raise ValueError("action_innovation_training_design_rank_deficient")
    predicted = design @ coefficients
    parameters = ActionInnovationTransitionParameters(
        support=support,
        baseline_drift_m3s_per_hour=float(coefficients[0]),
        action_change_coefficient=float(coefficients[1]),
        forcing_coefficient=float(coefficients[2]),
        timestep_seconds=3600,
        supported_forecast_horizons_hours=ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS,
        maximum_discharge_m3s=maximum_discharge_m3s,
        training_data_start=times[0],
        training_data_end=times[-1],
        training_sample_count=int(design.shape[0]),
        provenance_id=provenance_id,
        evidence_level="candidate",
        admitted=False,
        outcome_calibrated=True,
    )
    return ActionInnovationFitResult(
        parameters=parameters,
        design_rank=int(rank),
        design_condition_number=float(np.linalg.cond(design)),
        design_singular_values=tuple(float(value) for value in singular),
        training_increment_rmse_m3s=float(np.sqrt(np.mean((predicted - target) ** 2))),
    )


class CausalActionInnovationGeospatialKernel:
    """Roll discharge changes from the latest causal outlet state."""

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
    ) -> ActionInnovationTransitionForecast:
        if not isinstance(state, OutletTransitionState):
            raise TypeError("outlet_transition_state_required")
        if not isinstance(inputs, HourlyActionForcingSeries):
            raise TypeError("hourly_action_forcing_series_required")
        if not _aware(issue_time) or state.available_at > issue_time:
            raise ValueError("outlet_transition_state_not_available_at_issue")
        if state.valid_at > issue_time:
            raise ValueError("future_outlet_transition_state_forbidden")
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
        step_rows: list[ActionInnovationTransitionStep] = []
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
            raw = previous + increment
            predicted = min(self.parameters.maximum_discharge_m3s, max(0.0, float(raw)))
            clipped = not math.isclose(predicted, raw, rel_tol=0.0, abs_tol=1e-12)
            step_rows.append(
                ActionInnovationTransitionStep(
                    valid_at=cursor,
                    previous_discharge_m3s=previous,
                    effective_action_release_m3s=effective_action,
                    previous_effective_action_release_m3s=previous_effective_action,
                    effective_action_change_m3s=action_change,
                    nwm_lateral_inflow_m3s=forcing[cursor],
                    predicted_increment_m3s=increment,
                    predicted_discharge_m3s=predicted,
                    clipped=clipped,
                )
            )
            states[cursor] = OutletTransitionState(
                valid_at=cursor,
                available_at=issue_time,
                discharge_m3s=predicted,
                provenance_id=(
                    f"{self.parameters.provenance_id}|forecast:issue={issue_time.isoformat()}:"
                    f"valid={cursor.isoformat()}"
                ),
                evidence_level="candidate",
                observed=False,
            )
            previous = predicted
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
        return ActionInnovationTransitionForecast(
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
            admitted=self.parameters.admitted and operational,
        )


def _weighted_action(
    action: dict[datetime, float],
    times: tuple[datetime, ...],
    weights: tuple[float, ...],
) -> float:
    return sum(weight * action[valid_at] for weight, valid_at in zip(weights, times, strict=True))
