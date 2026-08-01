from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from data_agent.uwm.geospatial_kernel_v2.contracts import TemporalSupport
from data_agent.uwm.geospatial_kernel_v2.phase_alignment import (
    TemporalAlignmentSeries,
    TemporalPhaseAlignmentAuditor,
)


def _timestamps(count: int, *, start_hour: int = 0) -> tuple[datetime, ...]:
    start = datetime(2022, 3, 1, start_hour, tzinfo=timezone.utc)
    return tuple(start + timedelta(hours=index) for index in range(count))


def _support(position: str) -> TemporalSupport:
    return TemporalSupport(
        kind="interval_mean",
        duration_seconds=3600.0,
        timestamp_position=position,
        provenance_id=f"phase-test:{position}",
        evidence_level="authoritative",
    )


def _series(
    values: tuple[float | None, ...],
    *,
    role: str,
    position: str = "end",
    start_hour: int = 0,
) -> TemporalAlignmentSeries:
    return TemporalAlignmentSeries(
        timestamps_utc=_timestamps(len(values), start_hour=start_hour),
        values=values,
        temporal_support=_support(position),
        unit="m3 s-1",
        role=role,
        provenance_id=f"phase-test:{role}",
    )


def test_phase_alignment_recovers_known_two_step_shift() -> None:
    reference = _series(
        (3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0),
        role="observation",
    )
    candidate = _series(
        (4.0, 1.0, 5.0, 9.0, 2.0, 6.0),
        role="prediction",
    )

    result = TemporalPhaseAlignmentAuditor().analyze(
        reference,
        candidate,
        timestep_seconds=3600.0,
        maximum_shift_steps=2,
        minimum_complete_pairs=3,
        outcome_visible_diagnostic=True,
    )

    assert result.best_rmse.candidate_time_shift_steps == 2
    assert result.best_rmse.candidate_time_shift_seconds == 7200.0
    assert result.best_rmse.rmse == pytest.approx(0.0)
    assert result.statistical_alignment_only is True
    assert result.admitted_as_flood_wave_lag is False
    assert result.as_dict()["admitted_as_flood_wave_lag"] is False


def test_phase_alignment_normalizes_beginning_and_end_labels_to_centers() -> None:
    values = (2.0, 5.0, 1.0, 4.0, 3.0, 8.0)
    reference = _series(
        values,
        role="end-labeled-observation",
        position="end",
        start_hour=1,
    )
    candidate = _series(
        values,
        role="beginning-labeled-action",
        position="beginning",
        start_hour=0,
    )

    result = TemporalPhaseAlignmentAuditor().analyze(
        reference,
        candidate,
        timestep_seconds=3600.0,
        maximum_shift_steps=1,
        minimum_complete_pairs=3,
        outcome_visible_diagnostic=True,
    )

    assert reference.support_center_timestamps_utc == (
        candidate.support_center_timestamps_utc
    )
    assert result.timestamp_label_support_center_offset_seconds == 3600.0
    assert result.zero_shift.rmse == pytest.approx(0.0)
    assert result.best_rmse.candidate_time_shift_steps == 0


def test_phase_alignment_preserves_missing_and_finite_negative_values() -> None:
    values = (-2.0, None, 0.0, 3.0, -1.0, 5.0)
    reference = _series(values, role="approved-observation")
    candidate = _series(values, role="prediction")

    result = TemporalPhaseAlignmentAuditor().analyze(
        reference,
        candidate,
        timestep_seconds=3600.0,
        maximum_shift_steps=1,
        minimum_complete_pairs=3,
        outcome_visible_diagnostic=True,
    )

    assert result.zero_shift.complete_pair_count == 5
    assert result.zero_shift.rmse == pytest.approx(0.0)
    assert result.zero_shift.bias == pytest.approx(0.0)


def test_phase_alignment_uses_deterministic_negative_shift_tie_break() -> None:
    reference = _series((0.0, 1.0, 0.0, 1.0, 0.0, 1.0), role="reference")
    candidate = _series((1.0, 0.0, 1.0, 0.0, 1.0, 0.0), role="candidate")

    result = TemporalPhaseAlignmentAuditor().analyze(
        reference,
        candidate,
        timestep_seconds=3600.0,
        maximum_shift_steps=1,
        minimum_complete_pairs=3,
        outcome_visible_diagnostic=False,
    )

    assert result.best_rmse.candidate_time_shift_steps == -1
    assert result.best_correlation.candidate_time_shift_steps == -1
    assert result.best_rmse.rmse == pytest.approx(0.0)
    assert result.outcome_visible_diagnostic is False


def test_phase_alignment_rejects_nonfinite_values() -> None:
    with pytest.raises(
        ValueError, match="temporal_alignment_values_must_have_finite_sample"
    ):
        _series((1.0, float("nan")), role="invalid")
