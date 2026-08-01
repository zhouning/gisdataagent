"""Source-fitted residual decay for sealed physical-routing predictions."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

PHYSICAL_RESIDUAL_DECAY_SCHEMA = "gwm.geospatial_kernel.physical_residual_decay_parameters.v1"
PHYSICAL_RESIDUAL_DECAY_FORMULA = (
    "max(0, physical(target) + rho^(horizon + observation_latency) "
    "* (observed(latest) - physical(latest)))"
)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


@dataclass(frozen=True)
class PhysicalResidualDecayStep:
    """One causal correction applied to an immutable physical prediction."""

    physical_target_m3s: float
    physical_at_latest_observation_m3s: float
    latest_observed_discharge_m3s: float
    latest_observation_residual_m3s: float
    forecast_horizon_hours: int
    elapsed_from_latest_observation_hours: int
    decay_weight: float
    unbounded_prediction_m3s: float
    corrected_prediction_m3s: float
    clipped: bool


@dataclass(frozen=True)
class PhysicalResidualDecayParameters:
    """A bounded, zero-intercept AR(1) memory for physical-model residuals."""

    residual_decay_coefficient: float
    timestep_seconds: int
    observation_latency_hours: int
    supported_forecast_horizons_hours: tuple[int, ...]
    training_data_start: datetime
    training_data_end: datetime
    training_pair_count: int
    source_system_id: str
    source_operator: str
    source_prediction_sha256: str
    source_outcome_sha256: str
    provenance_id: str
    admitted: bool
    source_outcome_calibrated: bool

    def __post_init__(self) -> None:
        coefficient = float(self.residual_decay_coefficient)
        if not math.isfinite(coefficient) or not 0.0 <= coefficient <= 1.0:
            raise ValueError("physical_residual_decay_coefficient_invalid")
        if self.timestep_seconds != 3600:
            raise ValueError("physical_residual_decay_hourly_timestep_required")
        if (
            not isinstance(self.observation_latency_hours, int)
            or isinstance(self.observation_latency_hours, bool)
            or self.observation_latency_hours < 0
        ):
            raise ValueError("physical_residual_decay_latency_invalid")
        horizons = self.supported_forecast_horizons_hours
        if (
            not horizons
            or tuple(sorted(set(horizons))) != horizons
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
                for value in horizons
            )
        ):
            raise ValueError("physical_residual_decay_horizons_invalid")
        if (
            not _aware(self.training_data_start)
            or not _aware(self.training_data_end)
            or self.training_data_end <= self.training_data_start
            or not isinstance(self.training_pair_count, int)
            or isinstance(self.training_pair_count, bool)
            or self.training_pair_count < 2
        ):
            raise ValueError("physical_residual_decay_training_support_invalid")
        if (
            not isinstance(self.source_system_id, str)
            or not self.source_system_id.strip()
            or not isinstance(self.source_operator, str)
            or not self.source_operator.strip()
            or not isinstance(self.provenance_id, str)
            or not self.provenance_id.strip()
        ):
            raise ValueError("physical_residual_decay_provenance_invalid")
        if not _valid_sha256(self.source_prediction_sha256) or not _valid_sha256(
            self.source_outcome_sha256
        ):
            raise ValueError("physical_residual_decay_source_sha256_invalid")
        if not isinstance(self.admitted, bool) or not isinstance(
            self.source_outcome_calibrated, bool
        ):
            raise ValueError("physical_residual_decay_claim_flags_invalid")
        if self.admitted or not self.source_outcome_calibrated:
            raise ValueError("physical_residual_decay_candidate_claims_invalid")
        object.__setattr__(self, "residual_decay_coefficient", coefficient)

    def correct(
        self,
        *,
        latest_observed_discharge_m3s: float,
        physical_at_latest_observation_m3s: float,
        physical_target_m3s: float,
        forecast_horizon_hours: int,
    ) -> PhysicalResidualDecayStep:
        """Decay the latest available residual over the full state-to-target gap."""

        values = (
            latest_observed_discharge_m3s,
            physical_at_latest_observation_m3s,
            physical_target_m3s,
        )
        if (
            not isinstance(forecast_horizon_hours, int)
            or isinstance(forecast_horizon_hours, bool)
            or forecast_horizon_hours not in self.supported_forecast_horizons_hours
            or any(not math.isfinite(float(value)) or value < 0.0 for value in values)
        ):
            raise ValueError("physical_residual_decay_forecast_inputs_invalid")
        elapsed = forecast_horizon_hours + self.observation_latency_hours
        residual = float(latest_observed_discharge_m3s) - float(physical_at_latest_observation_m3s)
        weight = self.residual_decay_coefficient**elapsed
        unbounded = float(physical_target_m3s) + weight * residual
        corrected = max(0.0, unbounded)
        return PhysicalResidualDecayStep(
            physical_target_m3s=float(physical_target_m3s),
            physical_at_latest_observation_m3s=float(physical_at_latest_observation_m3s),
            latest_observed_discharge_m3s=float(latest_observed_discharge_m3s),
            latest_observation_residual_m3s=residual,
            forecast_horizon_hours=forecast_horizon_hours,
            elapsed_from_latest_observation_hours=elapsed,
            decay_weight=weight,
            unbounded_prediction_m3s=unbounded,
            corrected_prediction_m3s=corrected,
            clipped=unbounded < 0.0,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": PHYSICAL_RESIDUAL_DECAY_SCHEMA,
            "formula": PHYSICAL_RESIDUAL_DECAY_FORMULA,
            "estimator": "bounded_zero_intercept_residual_AR1_least_squares",
            "free_parameter_count": 1,
            "residual_decay_coefficient": self.residual_decay_coefficient,
            "coefficient_lower_bound": 0.0,
            "coefficient_upper_bound": 1.0,
            "zero_intercept": True,
            "timestep_seconds": self.timestep_seconds,
            "observation_latency_hours": self.observation_latency_hours,
            "supported_forecast_horizons_hours": list(self.supported_forecast_horizons_hours),
            "training_data_start": self.training_data_start.isoformat(),
            "training_data_end": self.training_data_end.isoformat(),
            "training_pair_count": self.training_pair_count,
            "source_system_id": self.source_system_id,
            "source_operator": self.source_operator,
            "source_prediction_sha256": self.source_prediction_sha256,
            "source_outcome_sha256": self.source_outcome_sha256,
            "provenance_id": self.provenance_id,
            "source_outcomes_used_for_fit": True,
            "target_outcomes_used_for_fit": False,
            "admitted": self.admitted,
            "source_outcome_calibrated": self.source_outcome_calibrated,
        }


def fit_physical_residual_decay(
    *,
    valid_times: tuple[datetime, ...],
    physical_discharge_m3s: tuple[float, ...],
    observed_discharge_m3s: tuple[float | None, ...],
    observation_latency_hours: int,
    supported_forecast_horizons_hours: tuple[int, ...],
    source_system_id: str,
    source_operator: str,
    source_prediction_sha256: str,
    source_outcome_sha256: str,
    provenance_id: str,
) -> PhysicalResidualDecayParameters:
    """Fit one residual-memory coefficient on an aligned hourly source series."""

    times = tuple(valid_times)
    physical = tuple(float(value) for value in physical_discharge_m3s)
    observed = tuple(None if value is None else float(value) for value in observed_discharge_m3s)
    if (
        len(times) < 3
        or len(physical) != len(times)
        or len(observed) != len(times)
        or any(not _aware(value) for value in times)
        or tuple(sorted(set(times))) != times
        or any(
            second - first != timedelta(hours=1)
            for first, second in zip(times, times[1:], strict=False)
        )
        or any(not math.isfinite(value) or value < 0.0 for value in physical)
        or any(
            value is not None and (not math.isfinite(value) or value < 0.0) for value in observed
        )
    ):
        raise ValueError("physical_residual_decay_training_inputs_invalid")
    residuals = tuple(
        None if outcome is None else outcome - prediction
        for prediction, outcome in zip(physical, observed, strict=True)
    )
    pairs = tuple(
        (previous, current)
        for previous, current in zip(residuals, residuals[1:], strict=False)
        if previous is not None and current is not None
    )
    denominator = sum(previous**2 for previous, _ in pairs)
    if len(pairs) < 2 or not math.isfinite(denominator) or denominator <= 0.0:
        raise ValueError("physical_residual_decay_training_design_invalid")
    unconstrained = sum(previous * current for previous, current in pairs) / denominator
    if not math.isfinite(unconstrained):
        raise ValueError("physical_residual_decay_training_design_invalid")
    coefficient = min(max(unconstrained, 0.0), 1.0)
    available_indices = [index for index, value in enumerate(residuals) if value is not None]
    return PhysicalResidualDecayParameters(
        residual_decay_coefficient=coefficient,
        timestep_seconds=3600,
        observation_latency_hours=observation_latency_hours,
        supported_forecast_horizons_hours=supported_forecast_horizons_hours,
        training_data_start=times[min(available_indices)],
        training_data_end=times[max(available_indices)],
        training_pair_count=len(pairs),
        source_system_id=source_system_id,
        source_operator=source_operator,
        source_prediction_sha256=source_prediction_sha256,
        source_outcome_sha256=source_outcome_sha256,
        provenance_id=provenance_id,
        admitted=False,
        source_outcome_calibrated=True,
    )


def physical_residual_decay_parameters_from_dict(
    value: Mapping[str, Any],
) -> PhysicalResidualDecayParameters:
    """Load a parameter document while enforcing its information boundary."""

    expected_claims = {
        "schema": PHYSICAL_RESIDUAL_DECAY_SCHEMA,
        "formula": PHYSICAL_RESIDUAL_DECAY_FORMULA,
        "estimator": "bounded_zero_intercept_residual_AR1_least_squares",
        "free_parameter_count": 1,
        "coefficient_lower_bound": 0.0,
        "coefficient_upper_bound": 1.0,
        "zero_intercept": True,
        "source_outcomes_used_for_fit": True,
        "target_outcomes_used_for_fit": False,
        "admitted": False,
        "source_outcome_calibrated": True,
    }
    if any(value.get(name) != expected for name, expected in expected_claims.items()):
        raise ValueError("physical_residual_decay_document_claims_invalid")
    if any(
        isinstance(value.get(name), bool)
        for name in (
            "residual_decay_coefficient",
            "timestep_seconds",
            "observation_latency_hours",
            "training_pair_count",
        )
    ):
        raise ValueError("physical_residual_decay_document_invalid")
    try:
        return PhysicalResidualDecayParameters(
            residual_decay_coefficient=float(value["residual_decay_coefficient"]),
            timestep_seconds=int(value["timestep_seconds"]),
            observation_latency_hours=int(value["observation_latency_hours"]),
            supported_forecast_horizons_hours=tuple(
                int(item) for item in value["supported_forecast_horizons_hours"]
            ),
            training_data_start=datetime.fromisoformat(str(value["training_data_start"])),
            training_data_end=datetime.fromisoformat(str(value["training_data_end"])),
            training_pair_count=int(value["training_pair_count"]),
            source_system_id=str(value["source_system_id"]),
            source_operator=str(value["source_operator"]),
            source_prediction_sha256=str(value["source_prediction_sha256"]),
            source_outcome_sha256=str(value["source_outcome_sha256"]),
            provenance_id=str(value["provenance_id"]),
            admitted=bool(value["admitted"]),
            source_outcome_calibrated=bool(value["source_outcome_calibrated"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("physical_residual_decay_document_invalid") from exc
