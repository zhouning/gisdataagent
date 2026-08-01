"""Graph-bound, action-conditioned outlet state transitions."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

GEOGRAPHIC_RESPONSE_SUPPORT_SCHEMA = "gwm.geospatial_kernel.geographic_response_support.v1"
HOURLY_ACTION_FORCING_SERIES_SCHEMA = "gwm.geospatial_kernel.hourly_action_forcing_series.v1"
ACTION_CONDITIONED_TRANSITION_PARAMETERS_SCHEMA = (
    "gwm.geospatial_kernel.action_conditioned_transition_parameters.v1"
)
ACTION_CONDITIONED_TRANSITION_FORECAST_SCHEMA = (
    "gwm.geospatial_kernel.action_conditioned_transition_forecast.v1"
)
ACTION_CONDITIONED_TRANSITION_FORMULA = (
    "q[t] = intercept + ar*q[t-1] + action_beta*"
    "sum(w_lag*action[t-lag]) + forcing_beta*nwm_lateral[t]"
)

_EVIDENCE_LEVELS = {"authoritative", "derived", "candidate"}


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _positive_feature_id(value: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name}_must_be_positive_integer")
    return value


@dataclass(frozen=True)
class GeographicResponseSupport:
    """A directed action-to-outlet path and its discrete response support."""

    network_id: str
    action_entry_feature_id: int
    outlet_feature_id: int
    path_feature_ids: tuple[int, ...]
    lag_hours: tuple[int, ...]
    lag_weights: tuple[float, ...]
    provenance_id: str
    evidence_level: str
    admitted: bool

    def __post_init__(self) -> None:
        if not self.network_id.strip() or not self.provenance_id.strip():
            raise ValueError("geographic_response_support_provenance_required")
        action_id = _positive_feature_id(self.action_entry_feature_id, "action_entry_feature_id")
        outlet_id = _positive_feature_id(self.outlet_feature_id, "outlet_feature_id")
        path = tuple(
            _positive_feature_id(value, "response_path_feature_id")
            for value in self.path_feature_ids
        )
        if (
            len(path) < 2
            or len(set(path)) != len(path)
            or path[0] != action_id
            or path[-1] != outlet_id
        ):
            raise ValueError("geographic_response_path_invalid")
        lags = tuple(self.lag_hours)
        if (
            not lags
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
                for value in lags
            )
            or tuple(sorted(set(lags))) != lags
        ):
            raise ValueError("geographic_response_lags_must_be_unique_positive_hours")
        weights = tuple(float(value) for value in self.lag_weights)
        if (
            len(weights) != len(lags)
            or not np.isfinite(np.asarray(weights, dtype=float)).all()
            or any(value < 0.0 for value in weights)
            or not math.isclose(sum(weights), 1.0, rel_tol=0.0, abs_tol=1e-12)
        ):
            raise ValueError("geographic_response_lag_weights_invalid")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("geographic_response_evidence_level_invalid")
        if not isinstance(self.admitted, bool):
            raise ValueError("geographic_response_admitted_flag_must_be_boolean")
        if self.admitted and self.evidence_level == "candidate":
            raise ValueError("candidate_geographic_response_cannot_be_admitted")
        object.__setattr__(self, "path_feature_ids", path)
        object.__setattr__(self, "lag_hours", lags)
        object.__setattr__(self, "lag_weights", weights)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": GEOGRAPHIC_RESPONSE_SUPPORT_SCHEMA,
            "network_id": self.network_id,
            "action_entry_feature_id": self.action_entry_feature_id,
            "outlet_feature_id": self.outlet_feature_id,
            "path_feature_ids": list(self.path_feature_ids),
            "lag_hours": list(self.lag_hours),
            "lag_weights": list(self.lag_weights),
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
            "admitted": self.admitted,
            "empirical_lag_is_physical_travel_time": False,
        }


@dataclass(frozen=True)
class HourlyActionForcingSeries:
    """Hourly scenario action and NWM forcing values on one shared time axis."""

    valid_times: tuple[datetime, ...]
    action_release_m3s: tuple[float, ...]
    nwm_lateral_inflow_m3s: tuple[float, ...]
    action_provenance_id: str
    forcing_provenance_id: str
    action_plan_vintage_verified: bool
    forcing_vintage_verified: bool

    def __post_init__(self) -> None:
        times = tuple(self.valid_times)
        action = tuple(float(value) for value in self.action_release_m3s)
        forcing = tuple(float(value) for value in self.nwm_lateral_inflow_m3s)
        if (
            not times
            or len(action) != len(times)
            or len(forcing) != len(times)
            or any(not _aware(value) for value in times)
            or tuple(sorted(set(times))) != times
            or any(
                second - first != timedelta(hours=1)
                for first, second in zip(times, times[1:], strict=False)
            )
        ):
            raise ValueError("hourly_action_forcing_axis_invalid")
        values = np.asarray(action + forcing, dtype=float)
        if not np.isfinite(values).all() or (values < 0.0).any():
            raise ValueError("hourly_action_forcing_values_must_be_nonnegative_finite")
        if not self.action_provenance_id.strip() or not self.forcing_provenance_id.strip():
            raise ValueError("hourly_action_forcing_provenance_required")
        if not isinstance(self.action_plan_vintage_verified, bool) or not isinstance(
            self.forcing_vintage_verified, bool
        ):
            raise ValueError("hourly_action_forcing_vintage_flags_must_be_boolean")
        object.__setattr__(self, "valid_times", times)
        object.__setattr__(self, "action_release_m3s", action)
        object.__setattr__(self, "nwm_lateral_inflow_m3s", forcing)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": HOURLY_ACTION_FORCING_SERIES_SCHEMA,
            "valid_times": [value.isoformat() for value in self.valid_times],
            "action_release_m3s": list(self.action_release_m3s),
            "nwm_lateral_inflow_m3s": list(self.nwm_lateral_inflow_m3s),
            "action_provenance_id": self.action_provenance_id,
            "forcing_provenance_id": self.forcing_provenance_id,
            "action_plan_vintage_verified": self.action_plan_vintage_verified,
            "forcing_vintage_verified": self.forcing_vintage_verified,
        }

    def counterfactual(
        self,
        *,
        issue_time: datetime,
        zero_future_action: bool = False,
        zero_future_forcing: bool = False,
    ) -> HourlyActionForcingSeries:
        if not _aware(issue_time):
            raise ValueError("counterfactual_issue_time_must_be_aware")
        if not isinstance(zero_future_action, bool) or not isinstance(zero_future_forcing, bool):
            raise ValueError("counterfactual_zero_flags_must_be_boolean")
        action = tuple(
            0.0 if zero_future_action and valid_at > issue_time else value
            for valid_at, value in zip(self.valid_times, self.action_release_m3s, strict=True)
        )
        forcing = tuple(
            0.0 if zero_future_forcing and valid_at > issue_time else value
            for valid_at, value in zip(self.valid_times, self.nwm_lateral_inflow_m3s, strict=True)
        )
        suffix = (
            f"counterfactual:issue={issue_time.isoformat()}:"
            f"zero_action={zero_future_action}:zero_forcing={zero_future_forcing}"
        )
        return HourlyActionForcingSeries(
            valid_times=self.valid_times,
            action_release_m3s=action,
            nwm_lateral_inflow_m3s=forcing,
            action_provenance_id=f"{self.action_provenance_id}|{suffix}",
            forcing_provenance_id=f"{self.forcing_provenance_id}|{suffix}",
            action_plan_vintage_verified=self.action_plan_vintage_verified,
            forcing_vintage_verified=self.forcing_vintage_verified,
        )

    def _maps(self) -> tuple[dict[datetime, float], dict[datetime, float]]:
        return (
            dict(zip(self.valid_times, self.action_release_m3s, strict=True)),
            dict(zip(self.valid_times, self.nwm_lateral_inflow_m3s, strict=True)),
        )


@dataclass(frozen=True)
class OutletTransitionState:
    valid_at: datetime
    available_at: datetime
    discharge_m3s: float
    provenance_id: str
    evidence_level: str
    observed: bool

    def __post_init__(self) -> None:
        if (
            not _aware(self.valid_at)
            or not _aware(self.available_at)
            or (self.observed and self.available_at < self.valid_at)
        ):
            raise ValueError("outlet_transition_state_time_invalid")
        discharge = float(self.discharge_m3s)
        if not math.isfinite(discharge) or discharge < 0.0:
            raise ValueError("outlet_transition_state_discharge_invalid")
        if not self.provenance_id.strip():
            raise ValueError("outlet_transition_state_provenance_required")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("outlet_transition_state_evidence_level_invalid")
        if not isinstance(self.observed, bool):
            raise ValueError("outlet_transition_state_observed_flag_must_be_boolean")
        object.__setattr__(self, "discharge_m3s", discharge)

    def as_dict(self) -> dict[str, object]:
        return {
            "valid_at": self.valid_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "discharge_m3s": self.discharge_m3s,
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
            "observed": self.observed,
        }


@dataclass(frozen=True)
class ActionConditionedTransitionParameters:
    support: GeographicResponseSupport
    intercept_m3s: float
    autoregressive_coefficient: float
    action_coefficient: float
    forcing_coefficient: float
    timestep_seconds: int
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
            [
                self.intercept_m3s,
                self.autoregressive_coefficient,
                self.action_coefficient,
                self.forcing_coefficient,
            ],
            dtype=float,
        )
        if not np.isfinite(coefficients).all():
            raise ValueError("action_conditioned_coefficients_must_be_finite")
        if (
            self.intercept_m3s < 0.0
            or not 0.0 <= self.autoregressive_coefficient < 1.0
            or self.action_coefficient < 0.0
            or self.forcing_coefficient < 0.0
        ):
            raise ValueError("action_conditioned_coefficients_violate_stability")
        if (
            not isinstance(self.timestep_seconds, int)
            or isinstance(self.timestep_seconds, bool)
            or self.timestep_seconds != 3600
        ):
            raise ValueError("action_conditioned_transition_requires_hourly_timestep")
        maximum = float(self.maximum_discharge_m3s)
        if not math.isfinite(maximum) or maximum <= 0.0:
            raise ValueError("action_conditioned_maximum_discharge_invalid")
        object.__setattr__(self, "maximum_discharge_m3s", maximum)
        if (
            not _aware(self.training_data_start)
            or not _aware(self.training_data_end)
            or self.training_data_end <= self.training_data_start
        ):
            raise ValueError("action_conditioned_training_window_invalid")
        if (
            not isinstance(self.training_sample_count, int)
            or isinstance(self.training_sample_count, bool)
            or self.training_sample_count < 4
        ):
            raise ValueError("action_conditioned_training_sample_count_invalid")
        if not self.provenance_id.strip():
            raise ValueError("action_conditioned_parameter_provenance_required")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("action_conditioned_parameter_evidence_level_invalid")
        if not isinstance(self.admitted, bool) or not isinstance(self.outcome_calibrated, bool):
            raise ValueError("action_conditioned_parameter_flags_must_be_boolean")
        if self.admitted and (self.evidence_level == "candidate" or not self.support.admitted):
            raise ValueError("unadmitted_action_conditioned_support_cannot_be_admitted")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": ACTION_CONDITIONED_TRANSITION_PARAMETERS_SCHEMA,
            "support": self.support.as_dict(),
            "formula": ACTION_CONDITIONED_TRANSITION_FORMULA,
            "intercept_m3s": self.intercept_m3s,
            "autoregressive_coefficient": self.autoregressive_coefficient,
            "action_coefficient": self.action_coefficient,
            "forcing_coefficient": self.forcing_coefficient,
            "timestep_seconds": self.timestep_seconds,
            "maximum_discharge_m3s": self.maximum_discharge_m3s,
            "training_data_start": self.training_data_start.isoformat(),
            "training_data_end": self.training_data_end.isoformat(),
            "training_sample_count": self.training_sample_count,
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
            "admitted": self.admitted,
            "outcome_calibrated": self.outcome_calibrated,
            "mass_conserving_network_routing_replacement": False,
        }


def action_conditioned_transition_parameters_from_dict(
    payload: Mapping[str, object],
) -> ActionConditionedTransitionParameters:
    """Load a serialized parameter document without weakening its claim boundary."""

    if not isinstance(payload, Mapping):
        raise TypeError("action_conditioned_parameter_document_mapping_required")
    expected_fields = {
        "schema",
        "support",
        "formula",
        "intercept_m3s",
        "autoregressive_coefficient",
        "action_coefficient",
        "forcing_coefficient",
        "timestep_seconds",
        "maximum_discharge_m3s",
        "training_data_start",
        "training_data_end",
        "training_sample_count",
        "provenance_id",
        "evidence_level",
        "admitted",
        "outcome_calibrated",
        "mass_conserving_network_routing_replacement",
    }
    if set(payload) != expected_fields:
        raise ValueError("action_conditioned_parameter_document_fields_invalid")
    if payload["schema"] != ACTION_CONDITIONED_TRANSITION_PARAMETERS_SCHEMA:
        raise ValueError("action_conditioned_parameter_document_schema_invalid")
    if (
        payload["formula"] != ACTION_CONDITIONED_TRANSITION_FORMULA
        or payload["mass_conserving_network_routing_replacement"] is not False
    ):
        raise ValueError("action_conditioned_parameter_document_claims_invalid")

    support = geographic_response_support_from_dict(payload["support"])
    return ActionConditionedTransitionParameters(
        support=support,
        intercept_m3s=_document_float(payload["intercept_m3s"], "parameter_intercept"),
        autoregressive_coefficient=_document_float(
            payload["autoregressive_coefficient"], "parameter_autoregressive_coefficient"
        ),
        action_coefficient=_document_float(
            payload["action_coefficient"], "parameter_action_coefficient"
        ),
        forcing_coefficient=_document_float(
            payload["forcing_coefficient"], "parameter_forcing_coefficient"
        ),
        timestep_seconds=_document_int(payload["timestep_seconds"], "parameter_timestep_seconds"),
        maximum_discharge_m3s=_document_float(
            payload["maximum_discharge_m3s"], "parameter_maximum_discharge"
        ),
        training_data_start=_document_time(
            payload["training_data_start"], "parameter_training_data_start"
        ),
        training_data_end=_document_time(
            payload["training_data_end"], "parameter_training_data_end"
        ),
        training_sample_count=_document_int(
            payload["training_sample_count"], "parameter_training_sample_count"
        ),
        provenance_id=_document_text(payload["provenance_id"], "parameter_provenance_id"),
        evidence_level=_document_text(payload["evidence_level"], "parameter_evidence_level"),
        admitted=_document_bool(payload["admitted"], "parameter_admitted"),
        outcome_calibrated=_document_bool(
            payload["outcome_calibrated"], "parameter_outcome_calibrated"
        ),
    )


def geographic_response_support_from_dict(payload: object) -> GeographicResponseSupport:
    """Load a geographic response support document with strict claim checks."""

    if not isinstance(payload, Mapping):
        raise TypeError("geographic_response_support_document_mapping_required")
    support_fields = {
        "schema",
        "network_id",
        "action_entry_feature_id",
        "outlet_feature_id",
        "path_feature_ids",
        "lag_hours",
        "lag_weights",
        "provenance_id",
        "evidence_level",
        "admitted",
        "empirical_lag_is_physical_travel_time",
    }
    if set(payload) != support_fields:
        raise ValueError("geographic_response_support_document_fields_invalid")
    if payload["schema"] != GEOGRAPHIC_RESPONSE_SUPPORT_SCHEMA:
        raise ValueError("geographic_response_support_document_schema_invalid")
    if payload["empirical_lag_is_physical_travel_time"] is not False:
        raise ValueError("geographic_response_support_document_claims_invalid")

    path = _document_list(payload["path_feature_ids"], "response_path_feature_ids")
    lags = _document_list(payload["lag_hours"], "response_lag_hours")
    weights = _document_list(payload["lag_weights"], "response_lag_weights")
    return GeographicResponseSupport(
        network_id=_document_text(payload["network_id"], "support_network_id"),
        action_entry_feature_id=_document_int(
            payload["action_entry_feature_id"], "support_action_entry_feature_id"
        ),
        outlet_feature_id=_document_int(payload["outlet_feature_id"], "support_outlet_feature_id"),
        path_feature_ids=tuple(_document_int(value, "support_path_feature_id") for value in path),
        lag_hours=tuple(_document_int(value, "support_lag_hour") for value in lags),
        lag_weights=tuple(_document_float(value, "support_lag_weight") for value in weights),
        provenance_id=_document_text(payload["provenance_id"], "support_provenance_id"),
        evidence_level=_document_text(payload["evidence_level"], "support_evidence_level"),
        admitted=_document_bool(payload["admitted"], "support_admitted"),
    )


def _document_list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{name}_must_be_list")
    return value


def _document_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{name}_must_be_nonempty_string")
    return value


def _document_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name}_must_be_integer")
    return value


def _document_float(value: object, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"{name}_must_be_number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name}_must_be_finite")
    return result


def _document_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{name}_must_be_boolean")
    return value


def _document_time(value: object, name: str) -> datetime:
    text = _document_text(value, name)
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name}_must_be_iso8601") from exc
    if not _aware(result):
        raise ValueError(f"{name}_must_be_aware")
    return result


@dataclass(frozen=True)
class ActionConditionedFitResult:
    parameters: ActionConditionedTransitionParameters
    design_rank: int
    design_condition_number: float
    design_singular_values: tuple[float, ...]
    training_rmse_m3s: float

    def as_dict(self) -> dict[str, object]:
        return {
            "parameters": self.parameters.as_dict(),
            "design_rank": self.design_rank,
            "design_condition_number": self.design_condition_number,
            "design_singular_values": list(self.design_singular_values),
            "training_rmse_m3s": self.training_rmse_m3s,
        }


@dataclass(frozen=True)
class ActionConditionedTransitionStep:
    valid_at: datetime
    previous_discharge_m3s: float
    effective_action_release_m3s: float
    nwm_lateral_inflow_m3s: float
    predicted_discharge_m3s: float
    clipped: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "valid_at": self.valid_at.isoformat(),
            "previous_discharge_m3s": self.previous_discharge_m3s,
            "effective_action_release_m3s": self.effective_action_release_m3s,
            "nwm_lateral_inflow_m3s": self.nwm_lateral_inflow_m3s,
            "predicted_discharge_m3s": self.predicted_discharge_m3s,
            "clipped": self.clipped,
        }


@dataclass(frozen=True)
class ActionConditionedTransitionForecast:
    issue_time: datetime
    initial_state: OutletTransitionState
    issue_state: OutletTransitionState
    final_state: OutletTransitionState
    target_valid_times: tuple[datetime, ...]
    target_discharge_m3s: tuple[float, ...]
    steps: tuple[ActionConditionedTransitionStep, ...]
    parameters: ActionConditionedTransitionParameters
    future_observations_used: bool
    operational_vintages_verified: bool
    admitted: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": ACTION_CONDITIONED_TRANSITION_FORECAST_SCHEMA,
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


def fit_action_conditioned_transition(
    *,
    support: GeographicResponseSupport,
    observed_valid_times: tuple[datetime, ...],
    observed_discharge_m3s: tuple[float, ...],
    inputs: HourlyActionForcingSeries,
    maximum_discharge_m3s: float,
    provenance_id: str,
) -> ActionConditionedFitResult:
    """Fit four shared coefficients while keeping path and lag weights frozen."""

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
        raise ValueError("action_conditioned_training_axis_invalid")
    observed_array = np.asarray(observed, dtype=float)
    if not np.isfinite(observed_array).all() or (observed_array < 0.0).any():
        raise ValueError("action_conditioned_training_values_invalid")
    action, forcing = inputs._maps()
    rows: list[list[float]] = []
    targets: list[float] = []
    for index, valid_at in enumerate(times[1:], start=1):
        lag_times = tuple(valid_at - timedelta(hours=lag) for lag in support.lag_hours)
        if valid_at not in forcing or any(value not in action for value in lag_times):
            continue
        effective_action = sum(
            weight * action[lag_time]
            for weight, lag_time in zip(support.lag_weights, lag_times, strict=True)
        )
        rows.append([1.0, observed[index - 1], effective_action, forcing[valid_at]])
        targets.append(observed[index])
    design = np.asarray(rows, dtype=float)
    target = np.asarray(targets, dtype=float)
    if design.shape[0] < 100 or design.shape[1] != 4:
        raise ValueError("action_conditioned_training_support_insufficient")
    coefficients, _, rank, singular = np.linalg.lstsq(design, target, rcond=None)
    if rank != 4:
        raise ValueError("action_conditioned_training_design_rank_deficient")
    predicted = design @ coefficients
    parameters = ActionConditionedTransitionParameters(
        support=support,
        intercept_m3s=float(coefficients[0]),
        autoregressive_coefficient=float(coefficients[1]),
        action_coefficient=float(coefficients[2]),
        forcing_coefficient=float(coefficients[3]),
        timestep_seconds=3600,
        maximum_discharge_m3s=maximum_discharge_m3s,
        training_data_start=times[0],
        training_data_end=times[-1],
        training_sample_count=int(design.shape[0]),
        provenance_id=provenance_id,
        evidence_level="candidate",
        admitted=False,
        outcome_calibrated=True,
    )
    return ActionConditionedFitResult(
        parameters=parameters,
        design_rank=int(rank),
        design_condition_number=float(np.linalg.cond(design)),
        design_singular_values=tuple(float(value) for value in singular),
        training_rmse_m3s=float(np.sqrt(np.mean((predicted - target) ** 2))),
    )


class CausalActionConditionedGeospatialKernel:
    """Roll an outlet state using a graph-bound action response and NWM forcing."""

    def __init__(self, parameters: ActionConditionedTransitionParameters) -> None:
        if not isinstance(parameters, ActionConditionedTransitionParameters):
            raise TypeError("action_conditioned_transition_parameters_required")
        self.parameters = parameters

    def forecast(
        self,
        state: OutletTransitionState,
        inputs: HourlyActionForcingSeries,
        *,
        issue_time: datetime,
        target_valid_times: tuple[datetime, ...],
    ) -> ActionConditionedTransitionForecast:
        if not isinstance(state, OutletTransitionState):
            raise TypeError("outlet_transition_state_required")
        if not isinstance(inputs, HourlyActionForcingSeries):
            raise TypeError("hourly_action_forcing_series_required")
        if not _aware(issue_time) or state.available_at > issue_time:
            raise ValueError("outlet_transition_state_not_available_at_issue")
        if state.valid_at > issue_time:
            raise ValueError("future_outlet_transition_state_forbidden")
        if self.parameters.training_data_end >= issue_time:
            raise ValueError("action_conditioned_training_must_precede_issue_time")
        targets = tuple(target_valid_times)
        if (
            not targets
            or any(not _aware(value) for value in targets)
            or tuple(sorted(set(targets))) != targets
            or targets[0] <= issue_time
        ):
            raise ValueError("action_conditioned_target_times_invalid")
        step = timedelta(seconds=self.parameters.timestep_seconds)
        offsets = [
            (value - state.valid_at).total_seconds() / self.parameters.timestep_seconds
            for value in targets
        ]
        if any(not value.is_integer() or value <= 0 for value in offsets):
            raise ValueError("action_conditioned_targets_must_align_to_timestep")

        action, forcing = inputs._maps()
        support = self.parameters.support
        cursor = state.valid_at
        previous = state.discharge_m3s
        step_rows: list[ActionConditionedTransitionStep] = []
        states: dict[datetime, OutletTransitionState] = {}
        maximum_target = targets[-1]
        while cursor < maximum_target:
            cursor += step
            lag_times = tuple(cursor - timedelta(hours=value) for value in support.lag_hours)
            if cursor not in forcing or any(value not in action for value in lag_times):
                raise ValueError("action_conditioned_required_input_missing")
            effective_action = sum(
                weight * action[lag_time]
                for weight, lag_time in zip(support.lag_weights, lag_times, strict=True)
            )
            raw = (
                self.parameters.intercept_m3s
                + self.parameters.autoregressive_coefficient * previous
                + self.parameters.action_coefficient * effective_action
                + self.parameters.forcing_coefficient * forcing[cursor]
            )
            predicted = min(self.parameters.maximum_discharge_m3s, max(0.0, float(raw)))
            clipped = not math.isclose(predicted, raw, rel_tol=0.0, abs_tol=1e-12)
            step_rows.append(
                ActionConditionedTransitionStep(
                    valid_at=cursor,
                    previous_discharge_m3s=previous,
                    effective_action_release_m3s=effective_action,
                    nwm_lateral_inflow_m3s=forcing[cursor],
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
                raise ValueError("action_conditioned_issue_time_not_on_state_axis") from exc
        target_states = tuple(states[value] for value in targets)
        operational = (
            inputs.action_plan_vintage_verified
            and inputs.forcing_vintage_verified
            and state.evidence_level == "authoritative"
        )
        admitted = self.parameters.admitted and operational
        return ActionConditionedTransitionForecast(
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
            admitted=admitted,
        )
