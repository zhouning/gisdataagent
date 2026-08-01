"""Temporal-support-aware statistical phase diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from .contracts import TemporalSupport


TEMPORAL_PHASE_ALIGNMENT_SCHEMA = (
    "gwm.geospatial_kernel.temporal_phase_alignment_diagnostic.v1"
)


@dataclass(frozen=True)
class TemporalAlignmentSeries:
    """A labeled series whose timestamp is distinct from its value support."""

    timestamps_utc: tuple[datetime, ...]
    values: tuple[float | None, ...]
    temporal_support: TemporalSupport
    unit: str
    role: str
    provenance_id: str

    def __post_init__(self) -> None:
        if (
            not self.timestamps_utc
            or len(self.timestamps_utc) != len(self.values)
            or not self.unit.strip()
            or not self.role.strip()
            or not self.provenance_id.strip()
        ):
            raise ValueError("temporal_alignment_series_identity_or_axis_invalid")
        normalized: list[datetime] = []
        previous: datetime | None = None
        for timestamp in self.timestamps_utc:
            if timestamp.tzinfo is None:
                raise ValueError("temporal_alignment_timezone_required")
            value = timestamp.astimezone(timezone.utc)
            if previous is not None and value <= previous:
                raise ValueError("temporal_alignment_timestamps_must_increase")
            normalized.append(value)
            previous = value
        numeric = [value for value in self.values if value is not None]
        if not numeric or not np.isfinite(np.asarray(numeric, dtype=float)).all():
            raise ValueError("temporal_alignment_values_must_have_finite_sample")
        object.__setattr__(self, "timestamps_utc", tuple(normalized))
        object.__setattr__(
            self,
            "values",
            tuple(None if value is None else float(value) for value in self.values),
        )

    @property
    def support_center_timestamps_utc(self) -> tuple[datetime, ...]:
        result: list[datetime] = []
        for timestamp in self.timestamps_utc:
            start, end = self.temporal_support.bounds(timestamp)
            result.append(start + (end - start) / 2)
        return tuple(result)


@dataclass(frozen=True)
class PhaseAlignmentCandidate:
    candidate_time_shift_steps: int
    candidate_time_shift_seconds: float
    complete_pair_count: int
    rmse: float
    mae: float
    bias: float
    pearson_correlation: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_time_shift_steps": self.candidate_time_shift_steps,
            "candidate_time_shift_seconds": self.candidate_time_shift_seconds,
            "complete_pair_count": self.complete_pair_count,
            "rmse": self.rmse,
            "mae": self.mae,
            "bias": self.bias,
            "pearson_correlation": self.pearson_correlation,
        }


@dataclass(frozen=True)
class TemporalPhaseAlignmentResult:
    reference_role: str
    candidate_role: str
    unit: str
    timestep_seconds: float
    maximum_shift_steps: int
    minimum_complete_pairs: int
    timestamp_label_support_center_offset_seconds: float
    zero_shift: PhaseAlignmentCandidate
    best_rmse: PhaseAlignmentCandidate
    best_correlation: PhaseAlignmentCandidate
    candidates: tuple[PhaseAlignmentCandidate, ...]
    outcome_visible_diagnostic: bool
    statistical_alignment_only: bool
    admitted_as_flood_wave_lag: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": TEMPORAL_PHASE_ALIGNMENT_SCHEMA,
            "reference_role": self.reference_role,
            "candidate_role": self.candidate_role,
            "unit": self.unit,
            "timestep_seconds": self.timestep_seconds,
            "maximum_shift_steps": self.maximum_shift_steps,
            "minimum_complete_pairs": self.minimum_complete_pairs,
            "timestamp_label_support_center_offset_seconds": (
                self.timestamp_label_support_center_offset_seconds
            ),
            "candidate_time_shift_definition": (
                "positive moves candidate support to a later reference time"
            ),
            "zero_shift": self.zero_shift.as_dict(),
            "best_rmse": self.best_rmse.as_dict(),
            "best_correlation": self.best_correlation.as_dict(),
            "candidates": [value.as_dict() for value in self.candidates],
            "outcome_visible_diagnostic": self.outcome_visible_diagnostic,
            "statistical_alignment_only": self.statistical_alignment_only,
            "admitted_as_flood_wave_lag": self.admitted_as_flood_wave_lag,
        }


class TemporalPhaseAlignmentAuditor:
    """Compare series after normalizing labels to temporal-support centers."""

    def analyze(
        self,
        reference: TemporalAlignmentSeries,
        candidate: TemporalAlignmentSeries,
        *,
        timestep_seconds: float,
        maximum_shift_steps: int,
        minimum_complete_pairs: int,
        outcome_visible_diagnostic: bool,
    ) -> TemporalPhaseAlignmentResult:
        if reference.unit != candidate.unit:
            raise ValueError("temporal_alignment_units_must_match")
        if not np.isfinite(timestep_seconds) or timestep_seconds <= 0.0:
            raise ValueError("temporal_alignment_timestep_must_be_positive")
        if (
            not isinstance(maximum_shift_steps, int)
            or isinstance(maximum_shift_steps, bool)
            or maximum_shift_steps < 0
        ):
            raise ValueError("temporal_alignment_maximum_shift_invalid")
        if (
            not isinstance(minimum_complete_pairs, int)
            or isinstance(minimum_complete_pairs, bool)
            or minimum_complete_pairs < 2
        ):
            raise ValueError("temporal_alignment_minimum_pairs_invalid")
        if not isinstance(outcome_visible_diagnostic, bool):
            raise ValueError("temporal_alignment_outcome_flag_must_be_boolean")

        reference_values = _center_value_map(reference)
        candidate_values = _center_value_map(candidate)
        candidates = tuple(
            _alignment_candidate(
                reference_values,
                candidate_values,
                shift_steps=shift,
                timestep_seconds=float(timestep_seconds),
                minimum_complete_pairs=minimum_complete_pairs,
            )
            for shift in range(-maximum_shift_steps, maximum_shift_steps + 1)
        )
        zero = next(
            value for value in candidates if value.candidate_time_shift_steps == 0
        )
        best_rmse = min(
            candidates,
            key=lambda value: (
                value.rmse,
                abs(value.candidate_time_shift_steps),
                value.candidate_time_shift_steps,
            ),
        )
        correlation_candidates = tuple(
            value for value in candidates if value.pearson_correlation is not None
        )
        if not correlation_candidates:
            raise ValueError("temporal_alignment_correlation_requires_variation")
        best_correlation = max(
            correlation_candidates,
            key=lambda value: (
                float(value.pearson_correlation),
                -abs(value.candidate_time_shift_steps),
                -value.candidate_time_shift_steps,
            ),
        )
        probe = datetime(2000, 1, 1, tzinfo=timezone.utc)
        reference_start, reference_end = reference.temporal_support.bounds(probe)
        candidate_start, candidate_end = candidate.temporal_support.bounds(probe)
        reference_center = reference_start + (reference_end - reference_start) / 2
        candidate_center = candidate_start + (candidate_end - candidate_start) / 2
        return TemporalPhaseAlignmentResult(
            reference_role=reference.role,
            candidate_role=candidate.role,
            unit=reference.unit,
            timestep_seconds=float(timestep_seconds),
            maximum_shift_steps=maximum_shift_steps,
            minimum_complete_pairs=minimum_complete_pairs,
            timestamp_label_support_center_offset_seconds=float(
                (candidate_center - reference_center).total_seconds()
            ),
            zero_shift=zero,
            best_rmse=best_rmse,
            best_correlation=best_correlation,
            candidates=candidates,
            outcome_visible_diagnostic=outcome_visible_diagnostic,
            statistical_alignment_only=True,
            admitted_as_flood_wave_lag=False,
        )


def _center_value_map(
    series: TemporalAlignmentSeries,
) -> dict[datetime, float | None]:
    return dict(
        zip(
            series.support_center_timestamps_utc,
            series.values,
            strict=True,
        )
    )


def _alignment_candidate(
    reference: dict[datetime, float | None],
    candidate: dict[datetime, float | None],
    *,
    shift_steps: int,
    timestep_seconds: float,
    minimum_complete_pairs: int,
) -> PhaseAlignmentCandidate:
    shift = timedelta(seconds=shift_steps * timestep_seconds)
    pairs: list[tuple[float, float]] = []
    for timestamp, candidate_value in candidate.items():
        reference_value = reference.get(timestamp + shift)
        if candidate_value is not None and reference_value is not None:
            pairs.append((float(reference_value), float(candidate_value)))
    if len(pairs) < minimum_complete_pairs:
        raise ValueError(
            f"temporal_alignment_insufficient_pairs_at_shift:{shift_steps}"
        )
    values = np.asarray(pairs, dtype=float)
    reference_values = values[:, 0]
    candidate_values = values[:, 1]
    error = candidate_values - reference_values
    reference_std = float(reference_values.std())
    candidate_std = float(candidate_values.std())
    correlation = (
        None
        if reference_std == 0.0 or candidate_std == 0.0
        else float(np.corrcoef(reference_values, candidate_values)[0, 1])
    )
    return PhaseAlignmentCandidate(
        candidate_time_shift_steps=shift_steps,
        candidate_time_shift_seconds=float(shift.total_seconds()),
        complete_pair_count=len(pairs),
        rmse=float(np.sqrt(np.mean(error**2))),
        mae=float(np.mean(np.abs(error))),
        bias=float(np.mean(error)),
        pearson_correlation=correlation,
    )
