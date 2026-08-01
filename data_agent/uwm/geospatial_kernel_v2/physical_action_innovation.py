"""Physics-first composition of sealed routing and learned action innovation."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

PHYSICAL_ACTION_INNOVATION_SCHEMA = "gwm.geospatial_kernel.physical_action_innovation_parameters.v1"
PHYSICAL_ACTION_INNOVATION_FORMULA = (
    "max(0, physical(target) + alpha * (wwm(target) - persistence(target)))"
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
class PhysicalActionInnovationStep:
    """One target forecast with a learned innovation added to physical routing."""

    physical_target_m3s: float
    action_innovation_wwm_target_m3s: float
    causal_persistence_target_m3s: float
    raw_action_innovation_m3s: float
    innovation_scale_coefficient: float
    scaled_action_innovation_m3s: float
    forecast_horizon_hours: int
    unbounded_prediction_m3s: float
    corrected_prediction_m3s: float
    clipped: bool


@dataclass(frozen=True)
class PhysicalActionInnovationParameters:
    """One source-fitted scale for a WWM innovation around physical routing."""

    innovation_scale_coefficient: float
    timestep_seconds: int
    supported_forecast_horizons_hours: tuple[int, ...]
    training_data_start: datetime
    training_data_end: datetime
    training_pair_count: int
    source_system_id: str
    source_physical_operator: str
    source_physical_prediction_sha256: str
    source_wwm_prediction_sha256: str
    source_wwm_parameter_sha256: str
    source_outcome_sha256: str
    provenance_id: str
    admitted: bool
    source_outcome_calibrated: bool

    def __post_init__(self) -> None:
        coefficient = float(self.innovation_scale_coefficient)
        if not math.isfinite(coefficient):
            raise ValueError("physical_action_innovation_coefficient_invalid")
        if self.timestep_seconds != 3600:
            raise ValueError("physical_action_innovation_hourly_timestep_required")
        horizons = self.supported_forecast_horizons_hours
        if (
            not horizons
            or tuple(sorted(set(horizons))) != horizons
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
                for value in horizons
            )
        ):
            raise ValueError("physical_action_innovation_horizons_invalid")
        if (
            not _aware(self.training_data_start)
            or not _aware(self.training_data_end)
            or self.training_data_end <= self.training_data_start
            or not isinstance(self.training_pair_count, int)
            or isinstance(self.training_pair_count, bool)
            or self.training_pair_count < 2
        ):
            raise ValueError("physical_action_innovation_training_support_invalid")
        if (
            not isinstance(self.source_system_id, str)
            or not self.source_system_id.strip()
            or not isinstance(self.source_physical_operator, str)
            or not self.source_physical_operator.strip()
            or not isinstance(self.provenance_id, str)
            or not self.provenance_id.strip()
        ):
            raise ValueError("physical_action_innovation_provenance_invalid")
        source_hashes = (
            self.source_physical_prediction_sha256,
            self.source_wwm_prediction_sha256,
            self.source_wwm_parameter_sha256,
            self.source_outcome_sha256,
        )
        if any(not _valid_sha256(value) for value in source_hashes):
            raise ValueError("physical_action_innovation_source_sha256_invalid")
        if not isinstance(self.admitted, bool) or not isinstance(
            self.source_outcome_calibrated, bool
        ):
            raise ValueError("physical_action_innovation_claim_flags_invalid")
        if self.admitted or not self.source_outcome_calibrated:
            raise ValueError("physical_action_innovation_candidate_claims_invalid")
        object.__setattr__(self, "innovation_scale_coefficient", coefficient)

    def correct(
        self,
        *,
        physical_target_m3s: float,
        action_innovation_wwm_target_m3s: float,
        causal_persistence_target_m3s: float,
        forecast_horizon_hours: int,
    ) -> PhysicalActionInnovationStep:
        """Add only the WWM departure from persistence to the physical path."""

        values = (
            physical_target_m3s,
            action_innovation_wwm_target_m3s,
            causal_persistence_target_m3s,
        )
        if (
            not isinstance(forecast_horizon_hours, int)
            or isinstance(forecast_horizon_hours, bool)
            or forecast_horizon_hours not in self.supported_forecast_horizons_hours
            or any(not math.isfinite(float(value)) or value < 0.0 for value in values)
        ):
            raise ValueError("physical_action_innovation_forecast_inputs_invalid")
        innovation = float(action_innovation_wwm_target_m3s) - float(causal_persistence_target_m3s)
        scaled = self.innovation_scale_coefficient * innovation
        unbounded = float(physical_target_m3s) + scaled
        corrected = max(0.0, unbounded)
        return PhysicalActionInnovationStep(
            physical_target_m3s=float(physical_target_m3s),
            action_innovation_wwm_target_m3s=float(action_innovation_wwm_target_m3s),
            causal_persistence_target_m3s=float(causal_persistence_target_m3s),
            raw_action_innovation_m3s=innovation,
            innovation_scale_coefficient=self.innovation_scale_coefficient,
            scaled_action_innovation_m3s=scaled,
            forecast_horizon_hours=forecast_horizon_hours,
            unbounded_prediction_m3s=unbounded,
            corrected_prediction_m3s=corrected,
            clipped=unbounded < 0.0,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": PHYSICAL_ACTION_INNOVATION_SCHEMA,
            "formula": PHYSICAL_ACTION_INNOVATION_FORMULA,
            "estimator": "unconstrained_zero_intercept_global_innovation_least_squares",
            "free_parameter_count": 1,
            "innovation_scale_coefficient": self.innovation_scale_coefficient,
            "coefficient_bounds_applied": False,
            "zero_intercept": True,
            "timestep_seconds": self.timestep_seconds,
            "supported_forecast_horizons_hours": list(self.supported_forecast_horizons_hours),
            "training_data_start": self.training_data_start.isoformat(),
            "training_data_end": self.training_data_end.isoformat(),
            "training_pair_count": self.training_pair_count,
            "source_system_id": self.source_system_id,
            "source_physical_operator": self.source_physical_operator,
            "source_physical_prediction_sha256": self.source_physical_prediction_sha256,
            "source_wwm_prediction_sha256": self.source_wwm_prediction_sha256,
            "source_wwm_parameter_sha256": self.source_wwm_parameter_sha256,
            "source_outcome_sha256": self.source_outcome_sha256,
            "provenance_id": self.provenance_id,
            "physical_routing_is_primary_trajectory": True,
            "wwm_absolute_discharge_used_as_primary_trajectory": False,
            "source_outcomes_used_for_fit": True,
            "target_outcomes_used_for_fit": False,
            "admitted": self.admitted,
            "source_outcome_calibrated": self.source_outcome_calibrated,
        }


def fit_physical_action_innovation(
    *,
    issue_times: tuple[datetime, ...],
    forecast_horizons_hours: tuple[int, ...],
    physical_discharge_m3s: tuple[float, ...],
    action_innovation_wwm_m3s: tuple[float, ...],
    causal_persistence_m3s: tuple[float, ...],
    observed_discharge_m3s: tuple[float | None, ...],
    supported_forecast_horizons_hours: tuple[int, ...],
    source_system_id: str,
    source_physical_operator: str,
    source_physical_prediction_sha256: str,
    source_wwm_prediction_sha256: str,
    source_wwm_parameter_sha256: str,
    source_outcome_sha256: str,
    provenance_id: str,
) -> PhysicalActionInnovationParameters:
    """Fit one scale from source physical residuals to source WWM innovations."""

    times = tuple(issue_times)
    row_horizons = tuple(forecast_horizons_hours)
    physical = tuple(float(value) for value in physical_discharge_m3s)
    wwm = tuple(float(value) for value in action_innovation_wwm_m3s)
    persistence = tuple(float(value) for value in causal_persistence_m3s)
    observed = tuple(None if value is None else float(value) for value in observed_discharge_m3s)
    supported = tuple(supported_forecast_horizons_hours)
    row_count = len(times)
    if (
        row_count < 3
        or any(
            len(values) != row_count
            for values in (row_horizons, physical, wwm, persistence, observed)
        )
        or any(not _aware(value) for value in times)
        or tuple(sorted(times)) != times
        or not supported
        or tuple(sorted(set(supported))) != supported
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in supported
        )
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value not in supported
            for value in row_horizons
        )
        or any(
            not math.isfinite(value) or value < 0.0
            for values in (physical, wwm, persistence)
            for value in values
        )
        or any(
            value is not None and (not math.isfinite(value) or value < 0.0) for value in observed
        )
    ):
        raise ValueError("physical_action_innovation_training_inputs_invalid")
    pairs = tuple(
        (candidate - baseline, outcome - routed)
        for routed, candidate, baseline, outcome in zip(
            physical, wwm, persistence, observed, strict=True
        )
        if outcome is not None
    )
    denominator = sum(innovation**2 for innovation, _ in pairs)
    if len(pairs) < 2 or not math.isfinite(denominator) or denominator <= 0.0:
        raise ValueError("physical_action_innovation_training_design_invalid")
    coefficient = sum(innovation * residual for innovation, residual in pairs) / denominator
    if not math.isfinite(coefficient):
        raise ValueError("physical_action_innovation_training_design_invalid")
    return PhysicalActionInnovationParameters(
        innovation_scale_coefficient=coefficient,
        timestep_seconds=3600,
        supported_forecast_horizons_hours=supported,
        training_data_start=min(times),
        training_data_end=max(times),
        training_pair_count=len(pairs),
        source_system_id=source_system_id,
        source_physical_operator=source_physical_operator,
        source_physical_prediction_sha256=source_physical_prediction_sha256,
        source_wwm_prediction_sha256=source_wwm_prediction_sha256,
        source_wwm_parameter_sha256=source_wwm_parameter_sha256,
        source_outcome_sha256=source_outcome_sha256,
        provenance_id=provenance_id,
        admitted=False,
        source_outcome_calibrated=True,
    )


def physical_action_innovation_parameters_from_dict(
    value: Mapping[str, Any],
) -> PhysicalActionInnovationParameters:
    """Load a frozen physics-first parameter document and enforce its claims."""

    expected_claims = {
        "schema": PHYSICAL_ACTION_INNOVATION_SCHEMA,
        "formula": PHYSICAL_ACTION_INNOVATION_FORMULA,
        "estimator": "unconstrained_zero_intercept_global_innovation_least_squares",
        "free_parameter_count": 1,
        "coefficient_bounds_applied": False,
        "zero_intercept": True,
        "physical_routing_is_primary_trajectory": True,
        "wwm_absolute_discharge_used_as_primary_trajectory": False,
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
        raise ValueError("physical_action_innovation_document_claims_invalid")
    numeric_names = (
        "innovation_scale_coefficient",
        "timestep_seconds",
        "training_pair_count",
    )
    raw_horizons = value.get("supported_forecast_horizons_hours")
    if (
        any(isinstance(value.get(name), bool) for name in numeric_names)
        or not isinstance(raw_horizons, list)
        or any(isinstance(item, bool) for item in raw_horizons)
    ):
        raise ValueError("physical_action_innovation_document_invalid")
    try:
        return PhysicalActionInnovationParameters(
            innovation_scale_coefficient=float(value["innovation_scale_coefficient"]),
            timestep_seconds=int(value["timestep_seconds"]),
            supported_forecast_horizons_hours=tuple(int(item) for item in raw_horizons),
            training_data_start=datetime.fromisoformat(str(value["training_data_start"])),
            training_data_end=datetime.fromisoformat(str(value["training_data_end"])),
            training_pair_count=int(value["training_pair_count"]),
            source_system_id=str(value["source_system_id"]),
            source_physical_operator=str(value["source_physical_operator"]),
            source_physical_prediction_sha256=str(value["source_physical_prediction_sha256"]),
            source_wwm_prediction_sha256=str(value["source_wwm_prediction_sha256"]),
            source_wwm_parameter_sha256=str(value["source_wwm_parameter_sha256"]),
            source_outcome_sha256=str(value["source_outcome_sha256"]),
            provenance_id=str(value["provenance_id"]),
            admitted=bool(value["admitted"]),
            source_outcome_calibrated=bool(value["source_outcome_calibrated"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("physical_action_innovation_document_invalid") from exc
