"""Strict outcome contract and scoring for action-innovation shadow forecasts."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS,
)

ACTION_INNOVATION_PROSPECTIVE_OUTCOMES_SCHEMA = (
    "gwm.geospatial_kernel.action_innovation_prospective_outcomes.v1"
)
ACTION_INNOVATION_AUTHORITATIVE_OBSERVATION_BATCH_SCHEMA = (
    "gwm.geospatial_kernel.action_innovation_authoritative_observation_batch.v1"
)
ACTION_INNOVATION_PROSPECTIVE_SCORE_SCHEMA = (
    "gwm.geospatial_kernel.action_innovation_prospective_score.v1"
)


@dataclass(frozen=True)
class ProspectiveOutletObservation:
    target_valid_time: datetime
    observed_discharge_m3s: float
    observation_available_at: datetime

    def __post_init__(self) -> None:
        if isinstance(self.observed_discharge_m3s, bool) or not isinstance(
            self.observed_discharge_m3s, (int, float)
        ):
            raise ValueError("action_innovation_prospective_observation_invalid")
        value = float(self.observed_discharge_m3s)
        if (
            not _aware(self.target_valid_time)
            or not _aware(self.observation_available_at)
            or self.observation_available_at < self.target_valid_time
            or not math.isfinite(value)
            or value < 0.0
        ):
            raise ValueError("action_innovation_prospective_observation_invalid")
        object.__setattr__(self, "observed_discharge_m3s", value)

    def as_dict(self) -> dict[str, object]:
        return {
            "target_valid_time": self.target_valid_time.isoformat(),
            "observed_discharge_m3s": self.observed_discharge_m3s,
            "observation_available_at": self.observation_available_at.isoformat(),
        }


@dataclass(frozen=True)
class ActionInnovationAuthoritativeObservationBatch:
    network_id: str
    retrieved_at: datetime
    outlet_observation_provenance_id: str
    outlet_observation_evidence_level: str
    observations: tuple[ProspectiveOutletObservation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.network_id, str) or not self.network_id.strip():
            raise ValueError("action_innovation_observation_batch_network_required")
        if not _aware(self.retrieved_at):
            raise ValueError("action_innovation_observation_batch_retrieved_time_invalid")
        if (
            not isinstance(self.outlet_observation_provenance_id, str)
            or not self.outlet_observation_provenance_id.strip()
            or self.outlet_observation_evidence_level != "authoritative"
        ):
            raise ValueError("action_innovation_observation_batch_provenance_invalid")
        observations = tuple(self.observations)
        if not observations or any(
            not isinstance(value, ProspectiveOutletObservation) for value in observations
        ):
            raise ValueError("action_innovation_observation_batch_axis_invalid")
        targets = tuple(value.target_valid_time for value in observations)
        if len(set(targets)) != len(targets):
            raise ValueError("action_innovation_observation_batch_duplicate_target")
        if self.retrieved_at < max(targets):
            raise ValueError("action_innovation_observation_batch_retrieval_precedes_target")
        if self.retrieved_at < max(
            value.observation_available_at for value in observations
        ):
            raise ValueError("action_innovation_observation_batch_availability_invalid")
        object.__setattr__(self, "observations", observations)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": ACTION_INNOVATION_AUTHORITATIVE_OBSERVATION_BATCH_SCHEMA,
            "network_id": self.network_id,
            "outlet_observation_provenance_id": (
                self.outlet_observation_provenance_id
            ),
            "outlet_observation_evidence_level": (
                self.outlet_observation_evidence_level
            ),
            "retrieved_at": self.retrieved_at.isoformat(),
            "observations": [value.as_dict() for value in self.observations],
            "values_imputed": False,
        }


def action_innovation_authoritative_observation_batch_from_dict(
    payload: Mapping[str, object],
) -> ActionInnovationAuthoritativeObservationBatch:
    if not isinstance(payload, Mapping):
        raise TypeError("action_innovation_observation_batch_mapping_required")
    if set(payload) != {
        "schema",
        "network_id",
        "outlet_observation_provenance_id",
        "outlet_observation_evidence_level",
        "retrieved_at",
        "observations",
        "values_imputed",
    }:
        raise ValueError("action_innovation_observation_batch_fields_invalid")
    if (
        payload["schema"]
        != ACTION_INNOVATION_AUTHORITATIVE_OBSERVATION_BATCH_SCHEMA
        or payload["values_imputed"] is not False
    ):
        raise ValueError("action_innovation_observation_batch_claims_invalid")
    raw_observations = payload["observations"]
    if not isinstance(raw_observations, list):
        raise ValueError("action_innovation_observation_batch_list_required")
    observations: list[ProspectiveOutletObservation] = []
    for value in raw_observations:
        if not isinstance(value, Mapping) or set(value) != {
            "target_valid_time",
            "observed_discharge_m3s",
            "observation_available_at",
        }:
            raise ValueError("action_innovation_observation_batch_row_fields_invalid")
        observations.append(
            ProspectiveOutletObservation(
                target_valid_time=_time(value["target_valid_time"], "observation_target"),
                observed_discharge_m3s=_number(
                    value["observed_discharge_m3s"], "observation_discharge"
                ),
                observation_available_at=_time(
                    value["observation_available_at"], "observation_available"
                ),
            )
        )
    return ActionInnovationAuthoritativeObservationBatch(
        network_id=_text(payload["network_id"], "observation_batch_network"),
        retrieved_at=_time(payload["retrieved_at"], "observation_retrieved"),
        outlet_observation_provenance_id=_text(
            payload["outlet_observation_provenance_id"],
            "observation_batch_provenance",
        ),
        outlet_observation_evidence_level=_text(
            payload["outlet_observation_evidence_level"],
            "observation_batch_evidence_level",
        ),
        observations=tuple(observations),
    )


@dataclass(frozen=True)
class ActionInnovationProspectiveOutcomeDocument:
    request_id: str
    forecast_receipt_sha256: str
    source_observation_artifact_sha256: str
    source_observation_artifact_size_bytes: int
    outcomes_available_at: datetime
    outlet_observation_provenance_id: str
    outlet_observation_evidence_level: str
    observations: tuple[ProspectiveOutletObservation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise ValueError("action_innovation_prospective_request_id_required")
        if not _valid_sha256(self.forecast_receipt_sha256):
            raise ValueError("action_innovation_prospective_forecast_hash_invalid")
        if not _valid_sha256(self.source_observation_artifact_sha256) or (
            not isinstance(self.source_observation_artifact_size_bytes, int)
            or isinstance(self.source_observation_artifact_size_bytes, bool)
            or self.source_observation_artifact_size_bytes <= 0
        ):
            raise ValueError("action_innovation_prospective_observation_artifact_invalid")
        if not _aware(self.outcomes_available_at):
            raise ValueError("action_innovation_prospective_outcome_time_invalid")
        if (
            not isinstance(self.outlet_observation_provenance_id, str)
            or not self.outlet_observation_provenance_id.strip()
            or self.outlet_observation_evidence_level != "authoritative"
        ):
            raise ValueError("action_innovation_prospective_outcome_provenance_invalid")
        observations = tuple(self.observations)
        if not observations or any(
            not isinstance(value, ProspectiveOutletObservation) for value in observations
        ):
            raise ValueError("action_innovation_prospective_outcome_axis_invalid")
        times = tuple(value.target_valid_time for value in observations)
        if tuple(sorted(set(times))) != times or self.outcomes_available_at < max(
            value.observation_available_at for value in observations
        ):
            raise ValueError("action_innovation_prospective_outcome_axis_invalid")
        object.__setattr__(self, "observations", observations)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": ACTION_INNOVATION_PROSPECTIVE_OUTCOMES_SCHEMA,
            "request_id": self.request_id,
            "forecast_receipt_sha256": self.forecast_receipt_sha256,
            "source_observation_artifact_sha256": (
                self.source_observation_artifact_sha256
            ),
            "source_observation_artifact_size_bytes": (
                self.source_observation_artifact_size_bytes
            ),
            "outcomes_available_at": self.outcomes_available_at.isoformat(),
            "outlet_observation_provenance_id": (self.outlet_observation_provenance_id),
            "outlet_observation_evidence_level": (self.outlet_observation_evidence_level),
            "observations": [value.as_dict() for value in self.observations],
            "outcome_accessed_after_forecast_seal": True,
            "values_imputed": False,
            "forecast_or_interval_changed_after_outcome_access": False,
        }


def action_innovation_prospective_outcomes_from_dict(
    payload: Mapping[str, object],
) -> ActionInnovationProspectiveOutcomeDocument:
    if not isinstance(payload, Mapping):
        raise TypeError("action_innovation_prospective_outcome_mapping_required")
    expected = {
        "schema",
        "request_id",
        "forecast_receipt_sha256",
        "source_observation_artifact_sha256",
        "source_observation_artifact_size_bytes",
        "outcomes_available_at",
        "outlet_observation_provenance_id",
        "outlet_observation_evidence_level",
        "observations",
        "outcome_accessed_after_forecast_seal",
        "values_imputed",
        "forecast_or_interval_changed_after_outcome_access",
    }
    if set(payload) != expected:
        raise ValueError("action_innovation_prospective_outcome_fields_invalid")
    if (
        payload["schema"] != ACTION_INNOVATION_PROSPECTIVE_OUTCOMES_SCHEMA
        or payload["outcome_accessed_after_forecast_seal"] is not True
        or payload["values_imputed"] is not False
        or payload["forecast_or_interval_changed_after_outcome_access"] is not False
    ):
        raise ValueError("action_innovation_prospective_outcome_claims_invalid")
    raw_observations = payload["observations"]
    if not isinstance(raw_observations, list):
        raise ValueError("action_innovation_prospective_observations_list_required")
    observations: list[ProspectiveOutletObservation] = []
    for value in raw_observations:
        if not isinstance(value, Mapping) or set(value) != {
            "target_valid_time",
            "observed_discharge_m3s",
            "observation_available_at",
        }:
            raise ValueError("action_innovation_prospective_observation_fields_invalid")
        observations.append(
            ProspectiveOutletObservation(
                target_valid_time=_time(value["target_valid_time"], "observation_target"),
                observed_discharge_m3s=_number(
                    value["observed_discharge_m3s"], "observation_discharge"
                ),
                observation_available_at=_time(
                    value["observation_available_at"], "observation_available"
                ),
            )
        )
    return ActionInnovationProspectiveOutcomeDocument(
        request_id=_text(payload["request_id"], "request_id"),
        forecast_receipt_sha256=_text(
            payload["forecast_receipt_sha256"], "forecast_receipt_sha256"
        ),
        source_observation_artifact_sha256=_text(
            payload["source_observation_artifact_sha256"],
            "source_observation_artifact_sha256",
        ),
        source_observation_artifact_size_bytes=_positive_int(
            payload["source_observation_artifact_size_bytes"],
            "source_observation_artifact_size_bytes",
        ),
        outcomes_available_at=_time(payload["outcomes_available_at"], "outcomes_available_at"),
        outlet_observation_provenance_id=_text(
            payload["outlet_observation_provenance_id"], "outcome_provenance"
        ),
        outlet_observation_evidence_level=_text(
            payload["outlet_observation_evidence_level"], "outcome_evidence_level"
        ),
        observations=tuple(observations),
    )


def score_action_innovation_prospective_forecast(
    *,
    issue_time: datetime,
    target_valid_times: tuple[datetime, ...],
    point_discharge_m3s: tuple[float, ...],
    lower_discharge_m3s: tuple[float, ...],
    upper_discharge_m3s: tuple[float, ...],
    outcomes: ActionInnovationProspectiveOutcomeDocument,
    target_marginal_coverage: float,
) -> dict[str, object]:
    if not _aware(issue_time):
        raise ValueError("action_innovation_prospective_issue_time_invalid")
    targets = tuple(target_valid_times)
    horizons = ACTION_INNOVATION_SUPPORTED_HORIZONS_HOURS
    if len(targets) != len(horizons) or any(not _aware(target) for target in targets):
        raise ValueError("action_innovation_prospective_forecast_axis_invalid")
    durations = tuple(target - issue_time for target in targets)
    expected_durations = tuple(timedelta(hours=horizon) for horizon in horizons)
    if durations != expected_durations:
        raise ValueError("action_innovation_prospective_forecast_axis_invalid")
    point = _finite_vector(point_discharge_m3s, len(targets), "point")
    lower = _finite_vector(lower_discharge_m3s, len(targets), "lower")
    upper = _finite_vector(upper_discharge_m3s, len(targets), "upper")
    if np.any(lower < 0.0) or np.any(lower > point) or np.any(point > upper):
        raise ValueError("action_innovation_prospective_interval_invalid")
    outcome_times = tuple(value.target_valid_time for value in outcomes.observations)
    if outcome_times != targets:
        raise ValueError("action_innovation_prospective_outcome_axis_mismatch")
    observed = np.asarray(
        [value.observed_discharge_m3s for value in outcomes.observations],
        dtype=float,
    )
    coverage = float(target_marginal_coverage)
    if not math.isfinite(coverage) or not 0.5 < coverage < 1.0:
        raise ValueError("action_innovation_prospective_target_coverage_invalid")
    alpha = 1.0 - coverage
    errors = point - observed
    absolute_errors = np.abs(errors)
    contained = (lower <= observed) & (observed <= upper)
    widths = upper - lower
    interval_scores = widths.copy()
    interval_scores += np.where(observed < lower, 2.0 / alpha * (lower - observed), 0.0)
    interval_scores += np.where(observed > upper, 2.0 / alpha * (observed - upper), 0.0)
    rows: list[dict[str, object]] = []
    combined = zip(
        horizons,
        targets,
        point,
        lower,
        upper,
        observed,
        errors,
        absolute_errors,
        contained,
        widths,
        interval_scores,
        strict=True,
    )
    for (
        horizon,
        target,
        center,
        low,
        high,
        observation,
        error,
        absolute_error,
        inside,
        width,
        interval_score,
    ) in combined:
        rows.append(
            {
                "horizon_hours": horizon,
                "target_valid_time": target.isoformat(),
                "point_discharge_m3s": float(center),
                "lower_discharge_m3s": float(low),
                "upper_discharge_m3s": float(high),
                "observed_discharge_m3s": float(observation),
                "error_m3s": float(error),
                "absolute_error_m3s": float(absolute_error),
                "interval_contains_observation": bool(inside),
                "interval_width_m3s": float(width),
                "interval_score": float(interval_score),
            }
        )
    return {
        "schema": ACTION_INNOVATION_PROSPECTIVE_SCORE_SCHEMA,
        "target_marginal_coverage": coverage,
        "rows": rows,
        "aggregate": {
            "sample_count": len(rows),
            "mae_m3s": float(np.mean(absolute_errors)),
            "rmse_m3s": float(np.sqrt(np.mean(np.square(errors)))),
            "bias_m3s": float(np.mean(errors)),
            "empirical_marginal_coverage": float(np.mean(contained)),
            "mean_interval_width_m3s": float(np.mean(widths)),
            "mean_interval_score": float(np.mean(interval_scores)),
        },
        "single_issue_only": True,
        "finite_sample_coverage_guarantee_claimed": False,
        "conditional_coverage_guarantee_claimed": False,
        "admitted": False,
    }


def _finite_vector(values: tuple[float, ...], count: int, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.shape != (count,) or not np.isfinite(array).all():
        raise ValueError(f"action_innovation_prospective_{name}_values_invalid")
    return array


def _aware(value: datetime) -> bool:
    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    )


def _valid_sha256(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _time(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"action_innovation_prospective_{name}_time_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"action_innovation_prospective_{name}_time_invalid") from exc
    if not _aware(parsed):
        raise ValueError(f"action_innovation_prospective_{name}_time_invalid")
    return parsed


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"action_innovation_prospective_{name}_text_invalid")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"action_innovation_prospective_{name}_number_invalid")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"action_innovation_prospective_{name}_number_invalid")
    return result


def _positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"action_innovation_prospective_{name}_integer_invalid")
    return value
