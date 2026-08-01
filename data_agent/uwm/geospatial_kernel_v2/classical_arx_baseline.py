"""Classical causal ARX baseline for action-conditioned outlet discharge."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

CLASSICAL_ARX_SCHEMA = "gwm.geospatial_kernel.classical_causal_arx_parameters.v1"
CLASSICAL_ARX_FORMULA = (
    "q[t] = intercept + phi*q[t-1] + "
    "action_beta*sum(w_lag*action[t-lag]) + forcing_beta*forcing[t]"
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
class ClassicalCausalARXParameters:
    """A frozen ARX(1) transfer function with a fixed distributed action lag."""

    intercept_m3s: float
    autoregressive_coefficient: float
    action_level_coefficient: float
    forcing_coefficient: float
    lag_hours: tuple[int, ...]
    lag_weights: tuple[float, ...]
    timestep_seconds: int
    supported_forecast_horizons_hours: tuple[int, ...]
    maximum_discharge_m3s: float
    training_data_start: datetime
    training_data_end: datetime
    training_sample_count: int
    source_artifact_sha256: str
    provenance_id: str
    admitted: bool
    outcome_calibrated: bool

    def __post_init__(self) -> None:
        coefficients = np.asarray(
            (
                self.intercept_m3s,
                self.autoregressive_coefficient,
                self.action_level_coefficient,
                self.forcing_coefficient,
                self.maximum_discharge_m3s,
            ),
            dtype=float,
        )
        if not np.isfinite(coefficients).all() or self.maximum_discharge_m3s <= 0.0:
            raise ValueError("classical_arx_coefficients_invalid")
        if (
            not self.lag_hours
            or len(self.lag_hours) != len(self.lag_weights)
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
                for value in self.lag_hours
            )
            or tuple(sorted(set(self.lag_hours))) != self.lag_hours
        ):
            raise ValueError("classical_arx_lag_support_invalid")
        weights = np.asarray(self.lag_weights, dtype=float)
        if (
            not np.isfinite(weights).all()
            or bool((weights < 0.0).any())
            or not math.isclose(float(weights.sum()), 1.0, abs_tol=1e-12)
        ):
            raise ValueError("classical_arx_lag_weights_invalid")
        if self.timestep_seconds != 3600:
            raise ValueError("classical_arx_hourly_timestep_required")
        horizons = self.supported_forecast_horizons_hours
        if (
            not horizons
            or tuple(sorted(set(horizons))) != horizons
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
                for value in horizons
            )
        ):
            raise ValueError("classical_arx_horizons_invalid")
        if (
            not _aware(self.training_data_start)
            or not _aware(self.training_data_end)
            or self.training_data_end < self.training_data_start
            or not isinstance(self.training_sample_count, int)
            or isinstance(self.training_sample_count, bool)
            or self.training_sample_count < 8
        ):
            raise ValueError("classical_arx_training_support_invalid")
        if not _valid_sha256(self.source_artifact_sha256):
            raise ValueError("classical_arx_source_sha256_invalid")
        if not isinstance(self.provenance_id, str) or not self.provenance_id.strip():
            raise ValueError("classical_arx_provenance_required")
        if not isinstance(self.admitted, bool) or not isinstance(
            self.outcome_calibrated, bool
        ):
            raise ValueError("classical_arx_claim_flags_invalid")
        if self.admitted or not self.outcome_calibrated:
            raise ValueError("classical_arx_candidate_claims_invalid")
        object.__setattr__(self, "lag_weights", tuple(float(value) for value in weights))

    @property
    def asymptotically_stable(self) -> bool:
        return abs(self.autoregressive_coefficient) < 1.0

    def forecast(
        self,
        *,
        initial_discharge_m3s: float,
        issue_index: int,
        target_indices: tuple[int, ...],
        action_release_m3s: tuple[float, ...],
        lateral_forcing_m3s: tuple[float, ...],
    ) -> tuple[tuple[float, ...], int]:
        """Recursively forecast from the latest issue-time-available outlet state."""

        action = np.asarray(action_release_m3s, dtype=float)
        forcing = np.asarray(lateral_forcing_m3s, dtype=float)
        if (
            not isinstance(issue_index, int)
            or isinstance(issue_index, bool)
            or issue_index < max(self.lag_hours)
            or not target_indices
            or tuple(sorted(set(target_indices))) != target_indices
            or target_indices[0] < issue_index
            or target_indices[-1] >= len(action)
            or action.shape != forcing.shape
            or not np.isfinite(action).all()
            or not np.isfinite(forcing).all()
            or bool((action < 0.0).any())
            or bool((forcing < 0.0).any())
            or not math.isfinite(float(initial_discharge_m3s))
            or initial_discharge_m3s < 0.0
        ):
            raise ValueError("classical_arx_forecast_inputs_invalid")
        state = float(initial_discharge_m3s)
        predictions: dict[int, float] = {}
        clipped_count = 0
        targets = set(target_indices)
        for index in range(issue_index, target_indices[-1] + 1):
            action_level = sum(
                weight * action[index - lag]
                for lag, weight in zip(
                    self.lag_hours, self.lag_weights, strict=True
                )
            )
            raw = (
                self.intercept_m3s
                + self.autoregressive_coefficient * state
                + self.action_level_coefficient * action_level
                + self.forcing_coefficient * forcing[index]
            )
            state = min(max(float(raw), 0.0), self.maximum_discharge_m3s)
            clipped_count += int(state != raw)
            if index in targets:
                predictions[index] = state
        return tuple(predictions[index] for index in target_indices), clipped_count

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": CLASSICAL_ARX_SCHEMA,
            "formula": CLASSICAL_ARX_FORMULA,
            "free_parameter_count": 4,
            "intercept_m3s": self.intercept_m3s,
            "autoregressive_coefficient": self.autoregressive_coefficient,
            "action_level_coefficient": self.action_level_coefficient,
            "forcing_coefficient": self.forcing_coefficient,
            "lag_hours": list(self.lag_hours),
            "lag_weights": list(self.lag_weights),
            "timestep_seconds": self.timestep_seconds,
            "supported_forecast_horizons_hours": list(
                self.supported_forecast_horizons_hours
            ),
            "maximum_discharge_m3s": self.maximum_discharge_m3s,
            "training_data_start": self.training_data_start.isoformat(),
            "training_data_end": self.training_data_end.isoformat(),
            "training_sample_count": self.training_sample_count,
            "source_artifact_sha256": self.source_artifact_sha256,
            "provenance_id": self.provenance_id,
            "asymptotically_stable": self.asymptotically_stable,
            "target_outcomes_used_for_fit": False,
            "admitted": self.admitted,
            "outcome_calibrated": self.outcome_calibrated,
        }


def fit_classical_causal_arx(
    *,
    valid_times: tuple[datetime, ...],
    observed_discharge_m3s: tuple[float, ...],
    action_release_m3s: tuple[float, ...],
    lateral_forcing_m3s: tuple[float, ...],
    lag_hours: tuple[int, ...],
    lag_weights: tuple[float, ...],
    supported_forecast_horizons_hours: tuple[int, ...],
    maximum_discharge_m3s: float,
    source_artifact_sha256: str,
    provenance_id: str,
) -> ClassicalCausalARXParameters:
    """Fit a four-parameter ARX(1) baseline on one locked hourly source window."""

    times = tuple(valid_times)
    observed = np.asarray(observed_discharge_m3s, dtype=float)
    action = np.asarray(action_release_m3s, dtype=float)
    forcing = np.asarray(lateral_forcing_m3s, dtype=float)
    if (
        len(times) < max(lag_hours) + 8
        or observed.shape != (len(times),)
        or action.shape != observed.shape
        or forcing.shape != observed.shape
        or any(not _aware(value) for value in times)
        or tuple(sorted(set(times))) != times
        or any(
            second - first != timedelta(hours=1)
            for first, second in zip(times, times[1:], strict=False)
        )
        or not np.isfinite(observed).all()
        or not np.isfinite(action).all()
        or not np.isfinite(forcing).all()
        or bool((observed < 0.0).any())
        or bool((action < 0.0).any())
        or bool((forcing < 0.0).any())
    ):
        raise ValueError("classical_arx_training_inputs_invalid")
    if len(lag_hours) != len(lag_weights):
        raise ValueError("classical_arx_training_lag_axis_invalid")
    first_index = max(lag_hours)
    design = np.asarray(
        [
            [
                1.0,
                observed[index - 1],
                sum(
                    weight * action[index - lag]
                    for lag, weight in zip(lag_hours, lag_weights, strict=True)
                ),
                forcing[index],
            ]
            for index in range(first_index, len(times))
        ],
        dtype=float,
    )
    target = observed[first_index:]
    coefficients, _, rank, _ = np.linalg.lstsq(design, target, rcond=None)
    if rank != design.shape[1] or not np.isfinite(coefficients).all():
        raise ValueError("classical_arx_training_design_rank_invalid")
    return ClassicalCausalARXParameters(
        intercept_m3s=float(coefficients[0]),
        autoregressive_coefficient=float(coefficients[1]),
        action_level_coefficient=float(coefficients[2]),
        forcing_coefficient=float(coefficients[3]),
        lag_hours=lag_hours,
        lag_weights=lag_weights,
        timestep_seconds=3600,
        supported_forecast_horizons_hours=supported_forecast_horizons_hours,
        maximum_discharge_m3s=maximum_discharge_m3s,
        training_data_start=times[first_index],
        training_data_end=times[-1],
        training_sample_count=len(target),
        source_artifact_sha256=source_artifact_sha256,
        provenance_id=provenance_id,
        admitted=False,
        outcome_calibrated=True,
    )


def classical_causal_arx_parameters_from_dict(
    payload: Mapping[str, object],
) -> ClassicalCausalARXParameters:
    if not isinstance(payload, Mapping):
        raise TypeError("classical_arx_parameter_document_mapping_required")
    expected = {
        "schema",
        "formula",
        "free_parameter_count",
        "intercept_m3s",
        "autoregressive_coefficient",
        "action_level_coefficient",
        "forcing_coefficient",
        "lag_hours",
        "lag_weights",
        "timestep_seconds",
        "supported_forecast_horizons_hours",
        "maximum_discharge_m3s",
        "training_data_start",
        "training_data_end",
        "training_sample_count",
        "source_artifact_sha256",
        "provenance_id",
        "asymptotically_stable",
        "target_outcomes_used_for_fit",
        "admitted",
        "outcome_calibrated",
    }
    if set(payload) != expected:
        raise ValueError("classical_arx_parameter_document_keys_invalid")
    if (
        payload["schema"] != CLASSICAL_ARX_SCHEMA
        or payload["formula"] != CLASSICAL_ARX_FORMULA
        or payload["free_parameter_count"] != 4
        or payload["target_outcomes_used_for_fit"] is not False
    ):
        raise ValueError("classical_arx_parameter_document_claims_invalid")
    value = ClassicalCausalARXParameters(
        intercept_m3s=float(payload["intercept_m3s"]),
        autoregressive_coefficient=float(payload["autoregressive_coefficient"]),
        action_level_coefficient=float(payload["action_level_coefficient"]),
        forcing_coefficient=float(payload["forcing_coefficient"]),
        lag_hours=tuple(int(item) for item in payload["lag_hours"]),
        lag_weights=tuple(float(item) for item in payload["lag_weights"]),
        timestep_seconds=int(payload["timestep_seconds"]),
        supported_forecast_horizons_hours=tuple(
            int(item) for item in payload["supported_forecast_horizons_hours"]
        ),
        maximum_discharge_m3s=float(payload["maximum_discharge_m3s"]),
        training_data_start=datetime.fromisoformat(str(payload["training_data_start"])),
        training_data_end=datetime.fromisoformat(str(payload["training_data_end"])),
        training_sample_count=int(payload["training_sample_count"]),
        source_artifact_sha256=str(payload["source_artifact_sha256"]),
        provenance_id=str(payload["provenance_id"]),
        admitted=payload["admitted"],
        outcome_calibrated=payload["outcome_calibrated"],
    )
    if payload["asymptotically_stable"] is not value.asymptotically_stable:
        raise ValueError("classical_arx_parameter_document_derived_values_invalid")
    return value
