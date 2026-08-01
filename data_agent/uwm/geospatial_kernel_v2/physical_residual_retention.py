"""Source-fitted horizon-specific residual retention for physical routing."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

PHYSICAL_RESIDUAL_RETENTION_SCHEMA = (
    "gwm.geospatial_kernel.physical_residual_retention_parameters.v1"
)
PHYSICAL_RESIDUAL_RETENTION_FORMULA = (
    "max(0, physical(target) + w_horizon * (observed(latest) - physical(latest)))"
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
class PhysicalResidualRetentionWeight:
    """One source-fitted residual weight for a fixed forecast horizon."""

    forecast_horizon_hours: int
    elapsed_from_latest_observation_hours: int
    weight: float
    training_pair_count: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.forecast_horizon_hours, int)
            or isinstance(self.forecast_horizon_hours, bool)
            or self.forecast_horizon_hours <= 0
            or not isinstance(self.elapsed_from_latest_observation_hours, int)
            or isinstance(self.elapsed_from_latest_observation_hours, bool)
            or self.elapsed_from_latest_observation_hours <= 0
            or not math.isfinite(float(self.weight))
            or not isinstance(self.training_pair_count, int)
            or isinstance(self.training_pair_count, bool)
            or self.training_pair_count < 2
        ):
            raise ValueError("physical_residual_retention_weight_invalid")
        object.__setattr__(self, "weight", float(self.weight))


@dataclass(frozen=True)
class PhysicalResidualRetentionStep:
    """One causal horizon-specific correction of a physical prediction."""

    physical_target_m3s: float
    physical_at_latest_observation_m3s: float
    latest_observed_discharge_m3s: float
    latest_observation_residual_m3s: float
    forecast_horizon_hours: int
    elapsed_from_latest_observation_hours: int
    retention_weight: float
    unbounded_prediction_m3s: float
    corrected_prediction_m3s: float
    clipped: bool


@dataclass(frozen=True)
class PhysicalResidualRetentionParameters:
    """Frozen horizon-specific residual weights fitted on one source system."""

    weights: tuple[PhysicalResidualRetentionWeight, ...]
    timestep_seconds: int
    observation_latency_hours: int
    training_data_start: datetime
    training_data_end: datetime
    source_system_id: str
    source_operator: str
    source_prediction_sha256: str
    source_outcome_sha256: str
    provenance_id: str
    admitted: bool
    source_outcome_calibrated: bool

    def __post_init__(self) -> None:
        if not self.weights or any(
            not isinstance(item, PhysicalResidualRetentionWeight) for item in self.weights
        ):
            raise ValueError("physical_residual_retention_horizons_invalid")
        if self.timestep_seconds != 3600:
            raise ValueError("physical_residual_retention_hourly_timestep_required")
        if (
            not isinstance(self.observation_latency_hours, int)
            or isinstance(self.observation_latency_hours, bool)
            or self.observation_latency_hours < 0
        ):
            raise ValueError("physical_residual_retention_latency_invalid")
        horizons = tuple(item.forecast_horizon_hours for item in self.weights)
        if (
            not horizons
            or tuple(sorted(set(horizons))) != horizons
            or any(
                item.elapsed_from_latest_observation_hours
                != item.forecast_horizon_hours + self.observation_latency_hours
                for item in self.weights
            )
        ):
            raise ValueError("physical_residual_retention_horizons_invalid")
        if (
            not _aware(self.training_data_start)
            or not _aware(self.training_data_end)
            or self.training_data_end <= self.training_data_start
        ):
            raise ValueError("physical_residual_retention_training_support_invalid")
        if (
            not isinstance(self.source_system_id, str)
            or not self.source_system_id.strip()
            or not isinstance(self.source_operator, str)
            or not self.source_operator.strip()
            or not isinstance(self.provenance_id, str)
            or not self.provenance_id.strip()
        ):
            raise ValueError("physical_residual_retention_provenance_invalid")
        if not _valid_sha256(self.source_prediction_sha256) or not _valid_sha256(
            self.source_outcome_sha256
        ):
            raise ValueError("physical_residual_retention_source_sha256_invalid")
        if not isinstance(self.admitted, bool) or not isinstance(
            self.source_outcome_calibrated, bool
        ):
            raise ValueError("physical_residual_retention_claim_flags_invalid")
        if self.admitted or not self.source_outcome_calibrated:
            raise ValueError("physical_residual_retention_candidate_claims_invalid")

    @property
    def supported_forecast_horizons_hours(self) -> tuple[int, ...]:
        return tuple(item.forecast_horizon_hours for item in self.weights)

    def correct(
        self,
        *,
        latest_observed_discharge_m3s: float,
        physical_at_latest_observation_m3s: float,
        physical_target_m3s: float,
        forecast_horizon_hours: int,
    ) -> PhysicalResidualRetentionStep:
        """Apply the frozen source weight for the requested forecast horizon."""

        values = (
            latest_observed_discharge_m3s,
            physical_at_latest_observation_m3s,
            physical_target_m3s,
        )
        if (
            not isinstance(forecast_horizon_hours, int)
            or isinstance(forecast_horizon_hours, bool)
            or any(not math.isfinite(float(value)) or value < 0.0 for value in values)
        ):
            raise ValueError("physical_residual_retention_forecast_inputs_invalid")
        by_horizon = {item.forecast_horizon_hours: item for item in self.weights}
        retained = by_horizon.get(forecast_horizon_hours)
        if retained is None:
            raise ValueError("physical_residual_retention_forecast_inputs_invalid")
        residual = float(latest_observed_discharge_m3s) - float(physical_at_latest_observation_m3s)
        unbounded = float(physical_target_m3s) + retained.weight * residual
        corrected = max(0.0, unbounded)
        return PhysicalResidualRetentionStep(
            physical_target_m3s=float(physical_target_m3s),
            physical_at_latest_observation_m3s=float(physical_at_latest_observation_m3s),
            latest_observed_discharge_m3s=float(latest_observed_discharge_m3s),
            latest_observation_residual_m3s=residual,
            forecast_horizon_hours=forecast_horizon_hours,
            elapsed_from_latest_observation_hours=(retained.elapsed_from_latest_observation_hours),
            retention_weight=retained.weight,
            unbounded_prediction_m3s=unbounded,
            corrected_prediction_m3s=corrected,
            clipped=unbounded < 0.0,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": PHYSICAL_RESIDUAL_RETENTION_SCHEMA,
            "formula": PHYSICAL_RESIDUAL_RETENTION_FORMULA,
            "estimator": "unconstrained_zero_intercept_residual_least_squares_by_horizon",
            "free_parameter_count": len(self.weights),
            "zero_intercept": True,
            "weight_bounds_applied": False,
            "timestep_seconds": self.timestep_seconds,
            "observation_latency_hours": self.observation_latency_hours,
            "supported_forecast_horizons_hours": list(self.supported_forecast_horizons_hours),
            "weights_by_horizon": {
                str(item.forecast_horizon_hours): {
                    "elapsed_from_latest_observation_hours": (
                        item.elapsed_from_latest_observation_hours
                    ),
                    "weight": item.weight,
                    "training_pair_count": item.training_pair_count,
                }
                for item in self.weights
            },
            "training_data_start": self.training_data_start.isoformat(),
            "training_data_end": self.training_data_end.isoformat(),
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


def fit_physical_residual_retention(
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
) -> PhysicalResidualRetentionParameters:
    """Fit one direct residual-regression weight for each elapsed target gap."""

    times = tuple(valid_times)
    physical = tuple(float(value) for value in physical_discharge_m3s)
    observed = tuple(None if value is None else float(value) for value in observed_discharge_m3s)
    horizons = tuple(supported_forecast_horizons_hours)
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
        or not isinstance(observation_latency_hours, int)
        or isinstance(observation_latency_hours, bool)
        or observation_latency_hours < 0
        or not horizons
        or tuple(sorted(set(horizons))) != horizons
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in horizons
        )
    ):
        raise ValueError("physical_residual_retention_training_inputs_invalid")
    residuals = tuple(
        None if outcome is None else outcome - prediction
        for prediction, outcome in zip(physical, observed, strict=True)
    )
    fitted_weights: list[PhysicalResidualRetentionWeight] = []
    for horizon in horizons:
        elapsed = horizon + observation_latency_hours
        pairs = tuple(
            (residuals[index], residuals[index + elapsed])
            for index in range(len(residuals) - elapsed)
            if residuals[index] is not None and residuals[index + elapsed] is not None
        )
        denominator = sum(previous**2 for previous, _ in pairs)
        if len(pairs) < 2 or not math.isfinite(denominator) or denominator <= 0.0:
            raise ValueError("physical_residual_retention_training_design_invalid")
        weight = sum(previous * current for previous, current in pairs) / denominator
        if not math.isfinite(weight):
            raise ValueError("physical_residual_retention_training_design_invalid")
        fitted_weights.append(
            PhysicalResidualRetentionWeight(
                forecast_horizon_hours=horizon,
                elapsed_from_latest_observation_hours=elapsed,
                weight=weight,
                training_pair_count=len(pairs),
            )
        )
    available_indices = [index for index, value in enumerate(residuals) if value is not None]
    return PhysicalResidualRetentionParameters(
        weights=tuple(fitted_weights),
        timestep_seconds=3600,
        observation_latency_hours=observation_latency_hours,
        training_data_start=times[min(available_indices)],
        training_data_end=times[max(available_indices)],
        source_system_id=source_system_id,
        source_operator=source_operator,
        source_prediction_sha256=source_prediction_sha256,
        source_outcome_sha256=source_outcome_sha256,
        provenance_id=provenance_id,
        admitted=False,
        source_outcome_calibrated=True,
    )


def physical_residual_retention_parameters_from_dict(
    value: Mapping[str, Any],
) -> PhysicalResidualRetentionParameters:
    """Load a frozen parameter document and enforce its information claims."""

    expected_claims = {
        "schema": PHYSICAL_RESIDUAL_RETENTION_SCHEMA,
        "formula": PHYSICAL_RESIDUAL_RETENTION_FORMULA,
        "estimator": "unconstrained_zero_intercept_residual_least_squares_by_horizon",
        "zero_intercept": True,
        "weight_bounds_applied": False,
        "source_outcomes_used_for_fit": True,
        "target_outcomes_used_for_fit": False,
        "admitted": False,
        "source_outcome_calibrated": True,
    }
    if any(
        (value.get(name) is not expected)
        if isinstance(expected, bool)
        else (value.get(name) != expected)
        for name, expected in expected_claims.items()
    ):
        raise ValueError("physical_residual_retention_document_claims_invalid")
    numeric_names = (
        "free_parameter_count",
        "timestep_seconds",
        "observation_latency_hours",
    )
    if any(isinstance(value.get(name), bool) for name in numeric_names):
        raise ValueError("physical_residual_retention_document_invalid")
    try:
        raw_horizons = value["supported_forecast_horizons_hours"]
        raw_weights = value["weights_by_horizon"]
        if (
            not isinstance(raw_horizons, list)
            or any(isinstance(item, bool) for item in raw_horizons)
            or not isinstance(raw_weights, Mapping)
        ):
            raise ValueError
        horizons = tuple(int(item) for item in raw_horizons)
        if int(value["free_parameter_count"]) != len(horizons):
            raise ValueError
        for horizon in horizons:
            raw = raw_weights[str(horizon)]
            if not isinstance(raw, Mapping) or any(
                isinstance(raw.get(name), bool)
                for name in (
                    "elapsed_from_latest_observation_hours",
                    "weight",
                    "training_pair_count",
                )
            ):
                raise ValueError
        weights = tuple(
            PhysicalResidualRetentionWeight(
                forecast_horizon_hours=horizon,
                elapsed_from_latest_observation_hours=int(
                    raw_weights[str(horizon)]["elapsed_from_latest_observation_hours"]
                ),
                weight=float(raw_weights[str(horizon)]["weight"]),
                training_pair_count=int(raw_weights[str(horizon)]["training_pair_count"]),
            )
            for horizon in horizons
        )
        if set(raw_weights) != {str(horizon) for horizon in horizons}:
            raise ValueError
        return PhysicalResidualRetentionParameters(
            weights=weights,
            timestep_seconds=int(value["timestep_seconds"]),
            observation_latency_hours=int(value["observation_latency_hours"]),
            training_data_start=datetime.fromisoformat(str(value["training_data_start"])),
            training_data_end=datetime.fromisoformat(str(value["training_data_end"])),
            source_system_id=str(value["source_system_id"]),
            source_operator=str(value["source_operator"]),
            source_prediction_sha256=str(value["source_prediction_sha256"]),
            source_outcome_sha256=str(value["source_outcome_sha256"]),
            provenance_id=str(value["provenance_id"]),
            admitted=bool(value["admitted"]),
            source_outcome_calibrated=bool(value["source_outcome_calibrated"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("physical_residual_retention_document_invalid") from exc
