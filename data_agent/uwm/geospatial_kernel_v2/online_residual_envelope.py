"""Causal expanding residual envelopes for online point forecasts."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

ONLINE_RESIDUAL_ENVELOPE_SCHEMA = "gwm.geospatial_kernel.online_residual_envelope.v1"
ONLINE_RESIDUAL_INTERVAL_SCHEMA = "gwm.geospatial_kernel.online_residual_interval.v1"


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True)
class OnlineResidualEnvelopeConfig:
    """Fixed interval controls shared across systems and model candidates."""

    supported_forecast_horizons_hours: tuple[int, ...] = (1, 3, 6, 12)
    target_marginal_coverage: float = 0.9
    minimum_matured_sample_count: int = 24

    def __post_init__(self) -> None:
        horizons = self.supported_forecast_horizons_hours
        coverage = float(self.target_marginal_coverage)
        if (
            not horizons
            or tuple(sorted(set(horizons))) != horizons
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
                for value in horizons
            )
            or not math.isfinite(coverage)
            or not 0.5 < coverage < 1.0
            or not isinstance(self.minimum_matured_sample_count, int)
            or isinstance(self.minimum_matured_sample_count, bool)
            or self.minimum_matured_sample_count < 2
        ):
            raise ValueError("online_residual_envelope_config_invalid")
        object.__setattr__(self, "target_marginal_coverage", coverage)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": ONLINE_RESIDUAL_ENVELOPE_SCHEMA,
            "supported_forecast_horizons_hours": list(self.supported_forecast_horizons_hours),
            "target_marginal_coverage": self.target_marginal_coverage,
            "minimum_matured_sample_count": self.minimum_matured_sample_count,
            "quantile_rank": "ceil((matured_sample_count + 1) * target_coverage)",
            "calibration_window": "expanding_horizon_specific_matured_absolute_errors",
            "lower_bound_clipped_to_zero": False,
            "finite_sample_coverage_guarantee_claimed": False,
            "conditional_coverage_guarantee_claimed": False,
        }


@dataclass(frozen=True)
class OnlineResidualInterval:
    forecast_horizon_hours: int
    point_prediction_m3s: float
    matured_sample_count: int
    quantile_rank: int | None
    radius_m3s: float | None
    lower_discharge_m3s: float | None
    upper_discharge_m3s: float | None
    interval_available: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": ONLINE_RESIDUAL_INTERVAL_SCHEMA,
            "forecast_horizon_hours": self.forecast_horizon_hours,
            "point_prediction_m3s": self.point_prediction_m3s,
            "matured_sample_count": self.matured_sample_count,
            "quantile_rank": self.quantile_rank,
            "radius_m3s": self.radius_m3s,
            "lower_discharge_m3s": self.lower_discharge_m3s,
            "upper_discharge_m3s": self.upper_discharge_m3s,
            "interval_available": self.interval_available,
            "lower_bound_clipped_to_zero": False,
            "point_prediction_changed": False,
        }


class ExpandingOnlineResidualEnvelope:
    """Store only matured absolute errors and emit horizon-specific intervals."""

    def __init__(
        self,
        *,
        state_as_of: datetime,
        config: OnlineResidualEnvelopeConfig | None = None,
    ) -> None:
        if not _aware(state_as_of):
            raise ValueError("online_residual_envelope_state_time_invalid")
        self.config = config or OnlineResidualEnvelopeConfig()
        self._state_as_of = state_as_of.astimezone(UTC)
        self._samples: dict[int, list[tuple[datetime, str, float]]] = {
            horizon: [] for horizon in self.config.supported_forecast_horizons_hours
        }
        self._sample_ids: set[str] = set()

    @property
    def state_as_of(self) -> datetime:
        return self._state_as_of

    def update(
        self,
        *,
        sample_id: str,
        forecast_horizon_hours: int,
        absolute_error_m3s: float,
        matured_at: datetime,
        update_time: datetime,
    ) -> None:
        if (
            not isinstance(sample_id, str)
            or not sample_id.strip()
            or sample_id in self._sample_ids
            or forecast_horizon_hours not in self._samples
            or isinstance(absolute_error_m3s, bool)
            or not math.isfinite(float(absolute_error_m3s))
            or float(absolute_error_m3s) < 0.0
            or not _aware(matured_at)
            or not _aware(update_time)
            or matured_at > update_time
            or update_time < self._state_as_of
        ):
            raise ValueError("online_residual_envelope_update_invalid")
        self._samples[forecast_horizon_hours].append(
            (matured_at.astimezone(UTC), sample_id, float(absolute_error_m3s))
        )
        self._samples[forecast_horizon_hours].sort(key=lambda value: (value[0], value[1]))
        self._sample_ids.add(sample_id)
        self._state_as_of = update_time.astimezone(UTC)

    def interval(
        self,
        *,
        forecast_horizon_hours: int,
        point_prediction_m3s: float,
        issue_time: datetime,
    ) -> OnlineResidualInterval:
        if (
            forecast_horizon_hours not in self._samples
            or isinstance(point_prediction_m3s, bool)
            or not math.isfinite(float(point_prediction_m3s))
            or float(point_prediction_m3s) < 0.0
            or not _aware(issue_time)
            or issue_time < self._state_as_of
        ):
            raise ValueError("online_residual_envelope_prediction_invalid")
        values = sorted(value[2] for value in self._samples[forecast_horizon_hours])
        count = len(values)
        rank = math.ceil((count + 1) * self.config.target_marginal_coverage)
        if count < self.config.minimum_matured_sample_count or rank > count:
            return OnlineResidualInterval(
                forecast_horizon_hours=forecast_horizon_hours,
                point_prediction_m3s=float(point_prediction_m3s),
                matured_sample_count=count,
                quantile_rank=None,
                radius_m3s=None,
                lower_discharge_m3s=None,
                upper_discharge_m3s=None,
                interval_available=False,
            )
        radius = values[rank - 1]
        point = float(point_prediction_m3s)
        return OnlineResidualInterval(
            forecast_horizon_hours=forecast_horizon_hours,
            point_prediction_m3s=point,
            matured_sample_count=count,
            quantile_rank=rank,
            radius_m3s=radius,
            lower_discharge_m3s=point - radius,
            upper_discharge_m3s=point + radius,
            interval_available=True,
        )

    def sample_count_by_horizon(self) -> dict[int, int]:
        return {horizon: len(values) for horizon, values in self._samples.items()}


def interval_score(
    *,
    lower: float,
    upper: float,
    observed: float,
    target_coverage: float,
) -> float:
    """Compute the central prediction interval score; lower is better."""

    values = (lower, upper, observed, target_coverage)
    if (
        any(isinstance(value, bool) for value in values)
        or any(not math.isfinite(float(value)) for value in values)
        or upper < lower
        or not 0.5 < target_coverage < 1.0
    ):
        raise ValueError("online_residual_interval_score_invalid")
    alpha = 1.0 - float(target_coverage)
    score = float(upper) - float(lower)
    if observed < lower:
        score += (2.0 / alpha) * (lower - observed)
    elif observed > upper:
        score += (2.0 / alpha) * (observed - upper)
    return score
