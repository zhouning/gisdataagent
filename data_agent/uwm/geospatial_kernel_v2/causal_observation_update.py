"""Causal discharge-to-storage analysis updates for nonlinear reach state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
from scipy.optimize import brentq

from .contracts import (
    LinearReferencedPath,
    ReachHydraulicGeometry,
    StockState,
)


CAUSAL_DISCHARGE_OBSERVATION_SCHEMA = (
    "gwm.geospatial_kernel.causal_discharge_observation.v1"
)
CAUSAL_MANNING_STATE_UPDATE_SCHEMA = (
    "gwm.geospatial_kernel.causal_manning_state_update.v1"
)

_QUALITY_STATUSES = {"approved", "provisional", "rejected"}
_EVIDENCE_LEVELS = {"authoritative", "derived", "candidate"}


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True)
class CausalDischargeObservation:
    """A gauge observation with separate valid and online-availability times."""

    feature_id: int
    discharge_m3s: float
    valid_at: datetime
    available_at: datetime
    quality_status: str
    provenance_id: str
    evidence_level: str
    role: str = "historical_state_update"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.feature_id, int)
            or isinstance(self.feature_id, bool)
            or self.feature_id <= 0
        ):
            raise ValueError("causal_observation_feature_id_must_be_positive_integer")
        value = float(self.discharge_m3s)
        if not np.isfinite(value) or value < 0.0:
            raise ValueError("causal_observation_discharge_must_be_finite_nonnegative")
        object.__setattr__(self, "discharge_m3s", value)
        if not _aware(self.valid_at) or not _aware(self.available_at):
            raise ValueError("causal_observation_timestamps_must_be_timezone_aware")
        if self.available_at < self.valid_at:
            raise ValueError("causal_observation_available_before_valid_time")
        if self.quality_status not in _QUALITY_STATUSES:
            raise ValueError("unsupported_causal_observation_quality_status")
        if not self.provenance_id.strip():
            raise ValueError("causal_observation_provenance_required")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("unsupported_causal_observation_evidence_level")
        if self.role != "historical_state_update":
            raise ValueError("causal_observation_role_must_be_historical_state_update")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": CAUSAL_DISCHARGE_OBSERVATION_SCHEMA,
            "feature_id": self.feature_id,
            "discharge_m3s": self.discharge_m3s,
            "valid_at": self.valid_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "quality_status": self.quality_status,
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
            "role": self.role,
        }


@dataclass(frozen=True)
class CausalObservationUpdateConfig:
    analysis_gain: float
    maximum_observation_age_seconds: float
    accepted_quality_statuses: tuple[str, ...] = ("approved",)
    require_authoritative_evidence: bool = True
    allow_unadmitted_components_for_diagnostics: bool = False
    root_relative_tolerance: float = 1e-12
    root_absolute_tolerance_m3: float = 1e-10
    maximum_bracket_expansions: int = 128

    def __post_init__(self) -> None:
        gain = float(self.analysis_gain)
        if not np.isfinite(gain) or gain < 0.0 or gain > 1.0:
            raise ValueError("causal_observation_analysis_gain_outside_unit_interval")
        object.__setattr__(self, "analysis_gain", gain)
        age = float(self.maximum_observation_age_seconds)
        if not np.isfinite(age) or age < 0.0:
            raise ValueError("causal_observation_maximum_age_must_be_nonnegative")
        object.__setattr__(self, "maximum_observation_age_seconds", age)
        statuses = tuple(self.accepted_quality_statuses)
        if (
            not statuses
            or len(statuses) != len(set(statuses))
            or any(value not in _QUALITY_STATUSES for value in statuses)
            or "rejected" in statuses
        ):
            raise ValueError("causal_observation_accepted_quality_statuses_invalid")
        object.__setattr__(self, "accepted_quality_statuses", statuses)
        if not isinstance(self.require_authoritative_evidence, bool) or not isinstance(
            self.allow_unadmitted_components_for_diagnostics, bool
        ):
            raise ValueError("causal_observation_admission_flags_must_be_boolean")
        if (
            not np.isfinite(self.root_relative_tolerance)
            or self.root_relative_tolerance <= 0.0
        ):
            raise ValueError("causal_observation_root_rtol_must_be_positive")
        if (
            not np.isfinite(self.root_absolute_tolerance_m3)
            or self.root_absolute_tolerance_m3 <= 0.0
        ):
            raise ValueError("causal_observation_root_atol_must_be_positive")
        if (
            not isinstance(self.maximum_bracket_expansions, int)
            or isinstance(self.maximum_bracket_expansions, bool)
            or self.maximum_bracket_expansions <= 0
        ):
            raise ValueError(
                "causal_observation_maximum_bracket_expansions_must_be_positive_integer"
            )


@dataclass(frozen=True)
class CausalObservationUpdateResult:
    updated_stock: StockState
    analysis_time: datetime
    observation: CausalDischargeObservation
    observation_age_seconds: float
    forecast_discharge_m3s: float
    observed_discharge_m3s: float
    analysis_discharge_m3s: float
    forecast_storage_m3: float
    observation_equivalent_storage_m3: float
    analysis_storage_m3: float
    analysis_increment_m3: float
    analysis_gain: float
    geometry_admitted: bool
    observation_admitted: bool
    causal_state_update_admitted: bool
    diagnostic_only: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": CAUSAL_MANNING_STATE_UPDATE_SCHEMA,
            "updated_stock_m3": list(self.updated_stock.values),
            "analysis_time": self.analysis_time.isoformat(),
            "observation": self.observation.as_dict(),
            "observation_age_seconds": self.observation_age_seconds,
            "forecast_discharge_m3s": self.forecast_discharge_m3s,
            "observed_discharge_m3s": self.observed_discharge_m3s,
            "analysis_discharge_m3s": self.analysis_discharge_m3s,
            "forecast_storage_m3": self.forecast_storage_m3,
            "observation_equivalent_storage_m3": (
                self.observation_equivalent_storage_m3
            ),
            "analysis_storage_m3": self.analysis_storage_m3,
            "analysis_increment_m3": self.analysis_increment_m3,
            "mass_accounting_role": "external_analysis_increment_not_transition_flux",
            "analysis_gain": self.analysis_gain,
            "geometry_admitted": self.geometry_admitted,
            "observation_admitted": self.observation_admitted,
            "causal_state_update_admitted": self.causal_state_update_admitted,
            "diagnostic_only": self.diagnostic_only,
        }


class CausalManningDischargeStateUpdater:
    """Map an available historical discharge to one local Manning storage state."""

    def __init__(
        self,
        path: LinearReferencedPath,
        config: CausalObservationUpdateConfig,
        *,
        zero_effective_length_tolerance_m: float = 1e-6,
    ) -> None:
        self.path = path
        self.config = config
        effective = np.asarray(path.effective_lengths_m, dtype=float)
        active_mask = effective > zero_effective_length_tolerance_m
        if not bool(active_mask.any()):
            raise ValueError("causal_observation_active_path_required")
        self.active_indices = tuple(int(value) for value in np.flatnonzero(active_mask))
        self.active_feature_ids = tuple(
            path.feature_ids[index] for index in self.active_indices
        )
        self.effective_lengths_m = tuple(
            float(effective[index]) for index in self.active_indices
        )

    def update(
        self,
        stock: StockState,
        geometry: ReachHydraulicGeometry,
        observation: CausalDischargeObservation,
        *,
        analysis_time: datetime,
    ) -> CausalObservationUpdateResult:
        self._validate_inputs(stock, geometry, observation, analysis_time)
        feature_index = self.active_feature_ids.index(observation.feature_id)
        length = self.effective_lengths_m[feature_index]
        geometry_values = (
            geometry.bottom_width_m[feature_index],
            geometry.side_slope_horizontal_per_vertical[feature_index],
            geometry.bed_slope[feature_index],
            geometry.manning_n[feature_index],
        )
        forecast_storage = float(stock.values[feature_index])
        forecast_discharge = _manning_discharge(
            forecast_storage, length, *geometry_values
        )
        target_storage = self._storage_for_discharge(
            observation.discharge_m3s,
            length=length,
            geometry_values=geometry_values,
            forecast_storage_m3=forecast_storage,
        )
        analysis_storage = float(
            forecast_storage
            + self.config.analysis_gain * (target_storage - forecast_storage)
        )
        updated_values = list(stock.values)
        updated_values[feature_index] = analysis_storage
        increment = analysis_storage - forecast_storage
        observation_admitted = (
            observation.quality_status in self.config.accepted_quality_statuses
            and (
                not self.config.require_authoritative_evidence
                or observation.evidence_level == "authoritative"
            )
        )
        admitted = geometry.admitted_as_hydraulic_geometry and observation_admitted
        provenance = (
            f"causal_manning_discharge_update|{stock.provenance_id}|"
            f"{geometry.provenance_id}|{observation.provenance_id}|"
            f"analysis={analysis_time.isoformat()}"
        )
        return CausalObservationUpdateResult(
            updated_stock=StockState(tuple(updated_values), "m3", provenance),
            analysis_time=analysis_time,
            observation=observation,
            observation_age_seconds=float(
                (analysis_time - observation.valid_at).total_seconds()
            ),
            forecast_discharge_m3s=forecast_discharge,
            observed_discharge_m3s=observation.discharge_m3s,
            analysis_discharge_m3s=_manning_discharge(
                analysis_storage, length, *geometry_values
            ),
            forecast_storage_m3=forecast_storage,
            observation_equivalent_storage_m3=target_storage,
            analysis_storage_m3=analysis_storage,
            analysis_increment_m3=increment,
            analysis_gain=self.config.analysis_gain,
            geometry_admitted=geometry.admitted_as_hydraulic_geometry,
            observation_admitted=observation_admitted,
            causal_state_update_admitted=admitted,
            diagnostic_only=not admitted,
        )

    def _validate_inputs(
        self,
        stock: StockState,
        geometry: ReachHydraulicGeometry,
        observation: CausalDischargeObservation,
        analysis_time: datetime,
    ) -> None:
        if not isinstance(stock, StockState):
            raise TypeError("stock_state_required")
        if not isinstance(geometry, ReachHydraulicGeometry):
            raise TypeError("reach_hydraulic_geometry_required")
        if not isinstance(observation, CausalDischargeObservation):
            raise TypeError("causal_discharge_observation_required")
        if not _aware(analysis_time):
            raise ValueError("causal_observation_analysis_time_must_be_timezone_aware")
        if observation.valid_at > analysis_time:
            raise ValueError("future_observation_valid_time_forbidden")
        if observation.available_at > analysis_time:
            raise ValueError("observation_not_yet_available_at_analysis_time")
        age = float((analysis_time - observation.valid_at).total_seconds())
        if age > self.config.maximum_observation_age_seconds:
            raise ValueError("causal_observation_exceeds_maximum_age")
        if stock.unit != "m3" or len(stock.values) != len(self.active_feature_ids):
            raise ValueError("causal_observation_stock_contract_mismatch")
        if geometry.feature_ids != self.active_feature_ids:
            raise ValueError("causal_observation_geometry_feature_order_mismatch")
        if observation.feature_id not in self.active_feature_ids:
            raise ValueError("causal_observation_feature_not_on_active_path")
        observation_admitted = (
            observation.quality_status in self.config.accepted_quality_statuses
            and (
                not self.config.require_authoritative_evidence
                or observation.evidence_level == "authoritative"
            )
        )
        if (
            not geometry.admitted_as_hydraulic_geometry or not observation_admitted
        ) and not self.config.allow_unadmitted_components_for_diagnostics:
            raise ValueError(
                "unadmitted_causal_observation_components_require_explicit_diagnostic_mode"
            )

    def _storage_for_discharge(
        self,
        discharge_m3s: float,
        *,
        length: float,
        geometry_values: tuple[float, float, float, float],
        forecast_storage_m3: float,
    ) -> float:
        if discharge_m3s == 0.0:
            return 0.0
        bottom_width = geometry_values[0]
        upper = max(forecast_storage_m3, length * bottom_width * 0.01, 1.0)
        for _ in range(self.config.maximum_bracket_expansions):
            if _manning_discharge(upper, length, *geometry_values) >= discharge_m3s:
                break
            upper *= 2.0
            if not np.isfinite(upper):
                raise RuntimeError("causal_observation_storage_bracket_nonfinite")
        else:
            raise RuntimeError("causal_observation_storage_bracket_not_found")
        return float(
            brentq(
                lambda value: (
                    _manning_discharge(value, length, *geometry_values)
                    - discharge_m3s
                ),
                0.0,
                upper,
                xtol=self.config.root_absolute_tolerance_m3,
                rtol=self.config.root_relative_tolerance,
            )
        )


def _manning_discharge(
    storage_m3: float,
    length_m: float,
    bottom_width_m: float,
    side_slope_horizontal_per_vertical: float,
    bed_slope: float,
    manning_n: float,
) -> float:
    if storage_m3 == 0.0:
        return 0.0
    area = storage_m3 / length_m
    depth = (
        -bottom_width_m
        + np.sqrt(
            bottom_width_m**2
            + 4.0 * side_slope_horizontal_per_vertical * area
        )
    ) / (2.0 * side_slope_horizontal_per_vertical)
    wetted_perimeter = bottom_width_m + 2.0 * depth * np.sqrt(
        1.0 + side_slope_horizontal_per_vertical**2
    )
    hydraulic_radius = area / wetted_perimeter
    return float(
        area * hydraulic_radius ** (2.0 / 3.0) * np.sqrt(bed_slope) / manning_n
    )
