"""Horizon-specific empirical uncertainty for the action-innovation candidate."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS,
    ActionInnovationTransitionForecast,
    ActionInnovationTransitionParameters,
    _document_bool,
    _document_float,
    _document_int,
    _document_text,
    _document_time,
)

ACTION_INNOVATION_UNCERTAINTY_PARAMETERS_SCHEMA = (
    "gwm.geospatial_kernel.action_innovation_uncertainty_parameters.v1"
)
ACTION_INNOVATION_UNCERTAINTY_FORECAST_SCHEMA = (
    "gwm.geospatial_kernel.action_innovation_uncertainty_forecast.v1"
)
ACTION_INNOVATION_UNCERTAINTY_METHOD = (
    "horizon_specific_empirical_absolute_error_finite_sample_rank"
)


def action_innovation_parameter_semantic_sha256(
    parameters: ActionInnovationTransitionParameters,
) -> str:
    if not isinstance(parameters, ActionInnovationTransitionParameters):
        raise TypeError("action_innovation_uncertainty_point_parameters_required")
    body = json.dumps(
        parameters.as_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


@dataclass(frozen=True)
class HorizonResidualEnvelopeParameters:
    point_parameter_artifact_sha256: str
    point_parameter_semantic_sha256: str
    target_marginal_coverage: float
    horizons_hours: tuple[int, ...]
    absolute_error_radius_m3s: tuple[float, ...]
    calibration_sample_count: tuple[int, ...]
    calibration_target_start: datetime
    calibration_target_end: datetime
    provenance_id: str
    evidence_level: str
    admitted: bool

    def __post_init__(self) -> None:
        if not _valid_sha256(self.point_parameter_artifact_sha256) or not _valid_sha256(
            self.point_parameter_semantic_sha256
        ):
            raise ValueError("action_innovation_uncertainty_point_parameter_hash_invalid")
        coverage = float(self.target_marginal_coverage)
        if not math.isfinite(coverage) or not 0.5 < coverage < 1.0:
            raise ValueError("action_innovation_uncertainty_target_coverage_invalid")
        object.__setattr__(self, "target_marginal_coverage", coverage)
        horizons = tuple(self.horizons_hours)
        if horizons != ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS:
            raise ValueError("action_innovation_uncertainty_horizons_invalid")
        object.__setattr__(self, "horizons_hours", horizons)
        radii = tuple(float(value) for value in self.absolute_error_radius_m3s)
        if (
            len(radii) != len(horizons)
            or not np.isfinite(np.asarray(radii, dtype=float)).all()
            or any(value < 0.0 for value in radii)
        ):
            raise ValueError("action_innovation_uncertainty_radii_invalid")
        object.__setattr__(self, "absolute_error_radius_m3s", radii)
        counts = tuple(self.calibration_sample_count)
        if len(counts) != len(horizons) or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 100 for value in counts
        ):
            raise ValueError("action_innovation_uncertainty_calibration_counts_invalid")
        object.__setattr__(self, "calibration_sample_count", counts)
        if (
            not _aware(self.calibration_target_start)
            or not _aware(self.calibration_target_end)
            or self.calibration_target_end <= self.calibration_target_start
        ):
            raise ValueError("action_innovation_uncertainty_calibration_window_invalid")
        if not self.provenance_id.strip():
            raise ValueError("action_innovation_uncertainty_provenance_required")
        if self.evidence_level != "candidate" or self.admitted is not False:
            raise ValueError("action_innovation_uncertainty_claim_boundary_invalid")

    def radius_for_horizon(self, horizon_hours: int) -> float:
        if not isinstance(horizon_hours, int) or isinstance(horizon_hours, bool):
            raise ValueError("action_innovation_uncertainty_horizon_invalid")
        try:
            index = self.horizons_hours.index(horizon_hours)
        except ValueError as exc:
            raise ValueError("action_innovation_uncertainty_horizon_not_supported") from exc
        return self.absolute_error_radius_m3s[index]

    def interval_for_point(
        self,
        *,
        horizon_hours: int,
        point_discharge_m3s: float,
        maximum_discharge_m3s: float,
    ) -> tuple[float, float]:
        point = float(point_discharge_m3s)
        maximum = float(maximum_discharge_m3s)
        if (
            not math.isfinite(point)
            or point < 0.0
            or not math.isfinite(maximum)
            or maximum <= 0.0
            or point > maximum
        ):
            raise ValueError("action_innovation_uncertainty_point_value_invalid")
        radius = self.radius_for_horizon(horizon_hours)
        return max(0.0, point - radius), min(maximum, point + radius)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": ACTION_INNOVATION_UNCERTAINTY_PARAMETERS_SCHEMA,
            "method": ACTION_INNOVATION_UNCERTAINTY_METHOD,
            "point_parameter_artifact_sha256": self.point_parameter_artifact_sha256,
            "point_parameter_semantic_sha256": self.point_parameter_semantic_sha256,
            "target_marginal_coverage": self.target_marginal_coverage,
            "horizons_hours": list(self.horizons_hours),
            "absolute_error_radius_m3s": list(self.absolute_error_radius_m3s),
            "calibration_sample_count": list(self.calibration_sample_count),
            "calibration_target_start": self.calibration_target_start.isoformat(),
            "calibration_target_end": self.calibration_target_end.isoformat(),
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
            "admitted": self.admitted,
            "calibration_outcomes_used": True,
            "time_series_exchangeability_claimed": False,
            "finite_sample_coverage_guarantee_claimed": False,
            "conditional_coverage_guarantee_claimed": False,
        }


def horizon_residual_envelope_parameters_from_dict(
    payload: Mapping[str, object],
) -> HorizonResidualEnvelopeParameters:
    if not isinstance(payload, Mapping):
        raise TypeError("action_innovation_uncertainty_document_mapping_required")
    expected = {
        "schema",
        "method",
        "point_parameter_artifact_sha256",
        "point_parameter_semantic_sha256",
        "target_marginal_coverage",
        "horizons_hours",
        "absolute_error_radius_m3s",
        "calibration_sample_count",
        "calibration_target_start",
        "calibration_target_end",
        "provenance_id",
        "evidence_level",
        "admitted",
        "calibration_outcomes_used",
        "time_series_exchangeability_claimed",
        "finite_sample_coverage_guarantee_claimed",
        "conditional_coverage_guarantee_claimed",
    }
    if set(payload) != expected:
        raise ValueError("action_innovation_uncertainty_document_fields_invalid")
    if (
        payload["schema"] != ACTION_INNOVATION_UNCERTAINTY_PARAMETERS_SCHEMA
        or payload["method"] != ACTION_INNOVATION_UNCERTAINTY_METHOD
        or payload["calibration_outcomes_used"] is not True
        or payload["time_series_exchangeability_claimed"] is not False
        or payload["finite_sample_coverage_guarantee_claimed"] is not False
        or payload["conditional_coverage_guarantee_claimed"] is not False
    ):
        raise ValueError("action_innovation_uncertainty_document_claims_invalid")
    horizons = payload["horizons_hours"]
    radii = payload["absolute_error_radius_m3s"]
    counts = payload["calibration_sample_count"]
    if (
        not isinstance(horizons, list)
        or not isinstance(radii, list)
        or not isinstance(counts, list)
    ):
        raise ValueError("action_innovation_uncertainty_document_arrays_invalid")
    return HorizonResidualEnvelopeParameters(
        point_parameter_artifact_sha256=_document_text(
            payload["point_parameter_artifact_sha256"],
            "uncertainty_point_parameter_artifact_sha256",
        ),
        point_parameter_semantic_sha256=_document_text(
            payload["point_parameter_semantic_sha256"],
            "uncertainty_point_parameter_semantic_sha256",
        ),
        target_marginal_coverage=_document_float(
            payload["target_marginal_coverage"], "uncertainty_target_coverage"
        ),
        horizons_hours=tuple(_document_int(value, "uncertainty_horizon") for value in horizons),
        absolute_error_radius_m3s=tuple(
            _document_float(value, "uncertainty_radius") for value in radii
        ),
        calibration_sample_count=tuple(
            _document_int(value, "uncertainty_calibration_count") for value in counts
        ),
        calibration_target_start=_document_time(
            payload["calibration_target_start"], "uncertainty_calibration_start"
        ),
        calibration_target_end=_document_time(
            payload["calibration_target_end"], "uncertainty_calibration_end"
        ),
        provenance_id=_document_text(payload["provenance_id"], "uncertainty_provenance"),
        evidence_level=_document_text(payload["evidence_level"], "uncertainty_evidence_level"),
        admitted=_document_bool(payload["admitted"], "uncertainty_admitted"),
    )


@dataclass(frozen=True)
class HorizonResidualEnvelopeForecast:
    point_forecast: ActionInnovationTransitionForecast
    lower_discharge_m3s: tuple[float, ...]
    upper_discharge_m3s: tuple[float, ...]
    parameters: HorizonResidualEnvelopeParameters

    def __post_init__(self) -> None:
        count = len(self.point_forecast.target_valid_times)
        if len(self.lower_discharge_m3s) != count or len(self.upper_discharge_m3s) != count:
            raise ValueError("action_innovation_uncertainty_forecast_axis_invalid")
        if self.point_forecast.admitted or self.parameters.admitted:
            raise ValueError("action_innovation_uncertainty_forecast_cannot_be_admitted")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": ACTION_INNOVATION_UNCERTAINTY_FORECAST_SCHEMA,
            "point_forecast": self.point_forecast.as_dict(),
            "lower_discharge_m3s": list(self.lower_discharge_m3s),
            "upper_discharge_m3s": list(self.upper_discharge_m3s),
            "parameters": self.parameters.as_dict(),
            "future_outlet_observations_used": False,
            "finite_sample_coverage_guarantee_claimed": False,
            "conditional_coverage_guarantee_claimed": False,
            "admitted": False,
        }


def fit_horizon_residual_envelope(
    *,
    point_parameters: ActionInnovationTransitionParameters,
    point_parameter_artifact_sha256: str,
    calibration_target_times: tuple[datetime, ...],
    calibration_horizon_hours: tuple[int, ...],
    observed_discharge_m3s: tuple[float, ...],
    predicted_discharge_m3s: tuple[float, ...],
    target_marginal_coverage: float,
    provenance_id: str,
) -> HorizonResidualEnvelopeParameters:
    if not isinstance(point_parameters, ActionInnovationTransitionParameters):
        raise TypeError("action_innovation_uncertainty_point_parameters_required")
    times = tuple(calibration_target_times)
    horizons = tuple(calibration_horizon_hours)
    observed = np.asarray(observed_discharge_m3s, dtype=float)
    predicted = np.asarray(predicted_discharge_m3s, dtype=float)
    if (
        not times
        or len(horizons) != len(times)
        or observed.shape != (len(times),)
        or predicted.shape != (len(times),)
        or any(not _aware(value) for value in times)
        or min(times) <= point_parameters.training_data_end
        or not np.isfinite(observed).all()
        or not np.isfinite(predicted).all()
        or (observed < 0.0).any()
        or (predicted < 0.0).any()
    ):
        raise ValueError("action_innovation_uncertainty_calibration_values_invalid")
    allowed = set(ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS)
    if set(horizons) != allowed or any(
        not isinstance(value, int) or isinstance(value, bool) for value in horizons
    ):
        raise ValueError("action_innovation_uncertainty_calibration_horizons_invalid")
    coverage = float(target_marginal_coverage)
    if not math.isfinite(coverage) or not 0.5 < coverage < 1.0:
        raise ValueError("action_innovation_uncertainty_target_coverage_invalid")
    radii: list[float] = []
    counts: list[int] = []
    absolute_errors = np.abs(observed - predicted)
    for horizon in ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS:
        selected = np.sort(absolute_errors[np.asarray(horizons) == horizon])
        if selected.size < 100:
            raise ValueError("action_innovation_uncertainty_calibration_support_insufficient")
        rank = min(selected.size, math.ceil((selected.size + 1) * coverage))
        radii.append(float(selected[rank - 1]))
        counts.append(int(selected.size))
    return HorizonResidualEnvelopeParameters(
        point_parameter_artifact_sha256=point_parameter_artifact_sha256,
        point_parameter_semantic_sha256=action_innovation_parameter_semantic_sha256(
            point_parameters
        ),
        target_marginal_coverage=coverage,
        horizons_hours=ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS,
        absolute_error_radius_m3s=tuple(radii),
        calibration_sample_count=tuple(counts),
        calibration_target_start=min(times),
        calibration_target_end=max(times),
        provenance_id=provenance_id,
        evidence_level="candidate",
        admitted=False,
    )


def apply_horizon_residual_envelope(
    point_forecast: ActionInnovationTransitionForecast,
    parameters: HorizonResidualEnvelopeParameters,
) -> HorizonResidualEnvelopeForecast:
    if not isinstance(point_forecast, ActionInnovationTransitionForecast):
        raise TypeError("action_innovation_uncertainty_point_forecast_required")
    if not isinstance(parameters, HorizonResidualEnvelopeParameters):
        raise TypeError("action_innovation_uncertainty_parameters_required")
    if (
        action_innovation_parameter_semantic_sha256(point_forecast.parameters)
        != parameters.point_parameter_semantic_sha256
    ):
        raise ValueError("action_innovation_uncertainty_point_parameter_identity_mismatch")
    timestep = point_forecast.parameters.timestep_seconds
    horizons = tuple(
        int((target - point_forecast.issue_time).total_seconds() / timestep)
        for target in point_forecast.target_valid_times
    )
    bounds = tuple(
        parameters.interval_for_point(
            horizon_hours=horizon,
            point_discharge_m3s=point,
            maximum_discharge_m3s=point_forecast.parameters.maximum_discharge_m3s,
        )
        for horizon, point in zip(horizons, point_forecast.target_discharge_m3s, strict=True)
    )
    return HorizonResidualEnvelopeForecast(
        point_forecast=point_forecast,
        lower_discharge_m3s=tuple(value[0] for value in bounds),
        upper_discharge_m3s=tuple(value[1] for value in bounds),
        parameters=parameters,
    )


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _valid_sha256(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )
