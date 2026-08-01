"""Causal hydrograph forecasts for observed internal network boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math

import numpy as np

from .causal_observation_update import CausalDischargeObservation


AUTOREGRESSIVE_LOG_BOUNDARY_PARAMETERS_SCHEMA = (
    "gwm.geospatial_kernel.autoregressive_log_boundary_parameters.v1"
)
BOUNDARY_HYDROGRAPH_FORECAST_SCHEMA = (
    "gwm.geospatial_kernel.boundary_hydrograph_forecast.v1"
)

_EVIDENCE_LEVELS = {"authoritative", "derived", "candidate"}


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True)
class AutoregressiveLogBoundaryParameters:
    """Frozen stationary AR(2) parameters on ``log1p(discharge)``."""

    feature_id: int
    intercept: float
    lag1_coefficient: float
    lag2_coefficient: float
    timestep_seconds: int
    maximum_discharge_m3s: float
    training_data_start: datetime
    training_data_end: datetime
    provenance_id: str
    evidence_level: str
    admitted: bool
    outlet_target_calibrated: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.feature_id, int)
            or isinstance(self.feature_id, bool)
            or self.feature_id <= 0
        ):
            raise ValueError("boundary_hydrograph_feature_id_must_be_positive_integer")
        coefficients = np.asarray(
            [self.intercept, self.lag1_coefficient, self.lag2_coefficient],
            dtype=float,
        )
        if not np.isfinite(coefficients).all():
            raise ValueError("boundary_hydrograph_coefficients_must_be_finite")
        if (
            not isinstance(self.timestep_seconds, int)
            or isinstance(self.timestep_seconds, bool)
            or self.timestep_seconds <= 0
        ):
            raise ValueError("boundary_hydrograph_timestep_must_be_positive_integer")
        maximum = float(self.maximum_discharge_m3s)
        if not math.isfinite(maximum) or maximum <= 0.0:
            raise ValueError("boundary_hydrograph_maximum_discharge_must_be_positive")
        object.__setattr__(self, "maximum_discharge_m3s", maximum)
        if not _aware(self.training_data_start) or not _aware(self.training_data_end):
            raise ValueError("boundary_hydrograph_training_times_must_be_aware")
        if self.training_data_end <= self.training_data_start:
            raise ValueError("boundary_hydrograph_training_window_invalid")
        if not self.provenance_id.strip():
            raise ValueError("boundary_hydrograph_provenance_required")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("boundary_hydrograph_evidence_level_invalid")
        if not isinstance(self.admitted, bool) or not isinstance(
            self.outlet_target_calibrated, bool
        ):
            raise ValueError("boundary_hydrograph_flags_must_be_boolean")
        if self.admitted and self.evidence_level == "candidate":
            raise ValueError("candidate_boundary_hydrograph_cannot_be_admitted")
        if self.outlet_target_calibrated:
            raise ValueError("boundary_hydrograph_outlet_target_calibration_forbidden")

        # Stationarity conditions for y[t] = c + a1*y[t-1] + a2*y[t-2].
        a1 = float(self.lag1_coefficient)
        a2 = float(self.lag2_coefficient)
        if not (-1.0 < a2 < 1.0 and a1 + a2 < 1.0 and a2 - a1 < 1.0):
            raise ValueError("boundary_hydrograph_ar2_must_be_stationary")

    @property
    def characteristic_roots(self) -> tuple[complex, complex]:
        roots = np.roots([1.0, -self.lag1_coefficient, -self.lag2_coefficient])
        return complex(roots[0]), complex(roots[1])

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": AUTOREGRESSIVE_LOG_BOUNDARY_PARAMETERS_SCHEMA,
            "feature_id": self.feature_id,
            "intercept": self.intercept,
            "lag1_coefficient": self.lag1_coefficient,
            "lag2_coefficient": self.lag2_coefficient,
            "characteristic_roots": [
                {"real": value.real, "imaginary": value.imag}
                for value in self.characteristic_roots
            ],
            "timestep_seconds": self.timestep_seconds,
            "maximum_discharge_m3s": self.maximum_discharge_m3s,
            "training_data_start": self.training_data_start.isoformat(),
            "training_data_end": self.training_data_end.isoformat(),
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
            "admitted": self.admitted,
            "outlet_target_calibrated": self.outlet_target_calibrated,
        }


@dataclass(frozen=True)
class BoundaryHydrographForecast:
    feature_id: int
    issue_time: datetime
    latest_observation_valid_at: datetime
    target_valid_times: tuple[datetime, ...]
    discharge_m3s: tuple[float, ...]
    parameters: AutoregressiveLogBoundaryParameters
    future_observations_used: bool
    operational_vintage_verified: bool
    admitted: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": BOUNDARY_HYDROGRAPH_FORECAST_SCHEMA,
            "feature_id": self.feature_id,
            "issue_time": self.issue_time.isoformat(),
            "latest_observation_valid_at": (
                self.latest_observation_valid_at.isoformat()
            ),
            "target_valid_times": [value.isoformat() for value in self.target_valid_times],
            "discharge_m3s": list(self.discharge_m3s),
            "future_observations_used": self.future_observations_used,
            "operational_vintage_verified": self.operational_vintage_verified,
            "admitted": self.admitted,
            "parameters": self.parameters.as_dict(),
        }


class CausalAutoregressiveLogBoundaryHydrograph:
    """Roll a fixed AR(2) boundary state from observations available at issue time."""

    def __init__(self, parameters: AutoregressiveLogBoundaryParameters) -> None:
        if not isinstance(parameters, AutoregressiveLogBoundaryParameters):
            raise TypeError("autoregressive_log_boundary_parameters_required")
        self.parameters = parameters

    def forecast(
        self,
        observations: tuple[CausalDischargeObservation, ...],
        *,
        issue_time: datetime,
        target_valid_times: tuple[datetime, ...],
    ) -> BoundaryHydrographForecast:
        if not _aware(issue_time):
            raise ValueError("boundary_hydrograph_issue_time_must_be_aware")
        if self.parameters.training_data_end >= issue_time:
            raise ValueError("boundary_hydrograph_training_must_precede_issue_time")
        if not target_valid_times or any(not _aware(value) for value in target_valid_times):
            raise ValueError("boundary_hydrograph_target_times_required")
        if tuple(sorted(set(target_valid_times))) != target_valid_times:
            raise ValueError("boundary_hydrograph_target_times_must_be_unique_sorted")

        eligible = tuple(
            sorted(
                (
                    value
                    for value in observations
                    if value.feature_id == self.parameters.feature_id
                    and value.available_at <= issue_time
                    and value.valid_at < issue_time
                    and value.quality_status == "approved"
                ),
                key=lambda value: value.valid_at,
            )
        )
        if len(eligible) < 2:
            raise ValueError("boundary_hydrograph_two_available_observations_required")
        previous, latest = eligible[-2:]
        step = timedelta(seconds=self.parameters.timestep_seconds)
        if latest.valid_at - previous.valid_at != step:
            raise ValueError("boundary_hydrograph_latest_history_must_be_consecutive")
        if target_valid_times[0] <= latest.valid_at or any(
            second - first != step
            for first, second in zip(target_valid_times, target_valid_times[1:])
        ):
            raise ValueError("boundary_hydrograph_target_axis_invalid")
        offsets = [
            (value - latest.valid_at).total_seconds() / self.parameters.timestep_seconds
            for value in target_valid_times
        ]
        if any(not value.is_integer() or value <= 0 for value in offsets):
            raise ValueError("boundary_hydrograph_targets_must_align_to_timestep")

        values_by_time: dict[datetime, float] = {}
        log_previous = math.log1p(previous.discharge_m3s)
        log_latest = math.log1p(latest.discharge_m3s)
        cursor = latest.valid_at
        maximum_target = target_valid_times[-1]
        maximum_log = math.log1p(self.parameters.maximum_discharge_m3s)
        while cursor < maximum_target:
            log_next = (
                self.parameters.intercept
                + self.parameters.lag1_coefficient * log_latest
                + self.parameters.lag2_coefficient * log_previous
            )
            log_next = min(maximum_log, max(0.0, float(log_next)))
            cursor += step
            values_by_time[cursor] = math.expm1(log_next)
            log_previous, log_latest = log_latest, log_next
        predicted = tuple(float(values_by_time[value]) for value in target_valid_times)
        operational = all(
            value.evidence_level == "authoritative" for value in (previous, latest)
        )
        return BoundaryHydrographForecast(
            feature_id=self.parameters.feature_id,
            issue_time=issue_time,
            latest_observation_valid_at=latest.valid_at,
            target_valid_times=target_valid_times,
            discharge_m3s=predicted,
            parameters=self.parameters,
            future_observations_used=False,
            operational_vintage_verified=operational,
            admitted=self.parameters.admitted and operational,
        )
