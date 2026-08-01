from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from data_agent.uwm.geospatial_kernel_v2.online_residual_envelope import (
    ExpandingOnlineResidualEnvelope,
    OnlineResidualEnvelopeConfig,
    interval_score,
)


def test_interval_waits_for_matured_support_and_uses_finite_sample_rank() -> None:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    envelope = ExpandingOnlineResidualEnvelope(state_as_of=start)

    for index in range(24):
        update_time = start + timedelta(hours=index + 1)
        envelope.update(
            sample_id=f"sample-{index:02d}",
            forecast_horizon_hours=1,
            absolute_error_m3s=float(index + 1),
            matured_at=update_time,
            update_time=update_time,
        )
        step = envelope.interval(
            forecast_horizon_hours=1,
            point_prediction_m3s=100.0,
            issue_time=update_time,
        )
        assert step.interval_available is (index == 23)

    assert step.matured_sample_count == 24
    assert step.quantile_rank == 23
    assert step.radius_m3s == 23.0
    assert step.lower_discharge_m3s == 77.0
    assert step.upper_discharge_m3s == 123.0
    assert step.as_dict()["point_prediction_changed"] is False


def test_envelope_rejects_unmatured_duplicate_or_time_reversed_updates() -> None:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    envelope = ExpandingOnlineResidualEnvelope(state_as_of=start)

    with pytest.raises(ValueError, match="update_invalid"):
        envelope.update(
            sample_id="future",
            forecast_horizon_hours=1,
            absolute_error_m3s=1.0,
            matured_at=start + timedelta(hours=2),
            update_time=start + timedelta(hours=1),
        )
    envelope.update(
        sample_id="valid",
        forecast_horizon_hours=1,
        absolute_error_m3s=1.0,
        matured_at=start + timedelta(hours=1),
        update_time=start + timedelta(hours=1),
    )
    with pytest.raises(ValueError, match="update_invalid"):
        envelope.update(
            sample_id="valid",
            forecast_horizon_hours=1,
            absolute_error_m3s=1.0,
            matured_at=start + timedelta(hours=1),
            update_time=start + timedelta(hours=1),
        )
    with pytest.raises(ValueError, match="prediction_invalid"):
        envelope.interval(
            forecast_horizon_hours=1,
            point_prediction_m3s=100.0,
            issue_time=start,
        )


def test_interval_score_penalizes_misses_and_signed_lower_is_allowed() -> None:
    covered = interval_score(lower=-2.0, upper=8.0, observed=-1.0, target_coverage=0.9)
    missed = interval_score(lower=-2.0, upper=8.0, observed=-3.0, target_coverage=0.9)

    assert covered == pytest.approx(10.0)
    assert missed == pytest.approx(30.0)
    assert OnlineResidualEnvelopeConfig().as_dict()["lower_bound_clipped_to_zero"] is False
