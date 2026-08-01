"""Causal online residual adaptation for a sealed physical flow forecast."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

PHYSICAL_ONLINE_RESIDUAL_ADAPTATION_SCHEMA = (
    "gwm.geospatial_kernel.physical_online_residual_adaptation.v4"
)
PHYSICAL_ONLINE_RESIDUAL_ADAPTATION_FORMULA = (
    "max(0, physical(target) + admitted_bias_h + "
    "admitted_weight_h * (physical(predictor_h) - "
    "physical(latest_observation_time)))"
)
PHYSICAL_ONLINE_RESIDUAL_ADAPTATION_STATE_SCHEMA = (
    "gwm.geospatial_kernel.physical_online_residual_adaptation_state.v1"
)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("physical_online_residual_adaptation_state_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("physical_online_residual_adaptation_state_invalid") from exc
    if not _aware(parsed):
        raise ValueError("physical_online_residual_adaptation_state_invalid")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class PhysicalOnlineResidualAdaptationConfig:
    """Fixed online-learning controls, shared across systems and windows."""

    supported_forecast_horizons_hours: tuple[int, ...] = (1, 3, 6, 12)
    adaptive_forecast_horizons_hours: tuple[int, ...] = (1, 3, 6)
    bias_adaptive_forecast_horizons_hours: tuple[int, ...] = (12,)
    trajectory_predictor_horizon_pairs: tuple[tuple[int, int], ...] = (
        (1, 3),
        (3, 6),
        (6, 12),
    )
    minimum_matured_sample_count: int = 24
    evidence_z_threshold: float = 1.96
    weight_lower_bound: float = -1.0
    weight_upper_bound: float = 1.0

    def __post_init__(self) -> None:
        horizons = self.supported_forecast_horizons_hours
        adaptive_horizons = self.adaptive_forecast_horizons_hours
        bias_adaptive_horizons = self.bias_adaptive_forecast_horizons_hours
        predictor_pairs = self.trajectory_predictor_horizon_pairs
        if (
            not horizons
            or tuple(sorted(set(horizons))) != horizons
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
                for value in horizons
            )
            or not adaptive_horizons
            or tuple(sorted(set(adaptive_horizons))) != adaptive_horizons
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
                for value in adaptive_horizons
            )
            or not set(adaptive_horizons).issubset(horizons)
            or tuple(sorted(set(bias_adaptive_horizons)))
            != bias_adaptive_horizons
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
                for value in bias_adaptive_horizons
            )
            or not set(bias_adaptive_horizons).issubset(horizons)
            or not set(adaptive_horizons).isdisjoint(bias_adaptive_horizons)
            or len(predictor_pairs) != len(adaptive_horizons)
            or any(
                not isinstance(pair, tuple)
                or len(pair) != 2
                or any(
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or value <= 0
                    for value in pair
                )
                for pair in predictor_pairs
            )
            or tuple(target for target, _ in predictor_pairs)
            != adaptive_horizons
            or any(
                predictor not in horizons or predictor <= target
                for target, predictor in predictor_pairs
            )
            or not isinstance(self.minimum_matured_sample_count, int)
            or isinstance(self.minimum_matured_sample_count, bool)
            or self.minimum_matured_sample_count < 2
            or not math.isfinite(float(self.evidence_z_threshold))
            or self.evidence_z_threshold <= 0.0
            or not math.isfinite(float(self.weight_lower_bound))
            or not math.isfinite(float(self.weight_upper_bound))
            or self.weight_lower_bound >= self.weight_upper_bound
            or self.weight_lower_bound > 0.0
            or self.weight_upper_bound < 0.0
        ):
            raise ValueError("physical_online_residual_adaptation_config_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": PHYSICAL_ONLINE_RESIDUAL_ADAPTATION_SCHEMA,
            "formula": PHYSICAL_ONLINE_RESIDUAL_ADAPTATION_FORMULA,
            "estimator": (
                "expanding_horizon_specialized_physical_error_regression"
            ),
            "short_horizon_predictor": (
                "physical(predictor_h) - physical(latest_observation_time)"
            ),
            "trajectory_predictor_horizon_by_target_horizon": {
                str(target): predictor
                for target, predictor in self.trajectory_predictor_horizon_pairs
            },
            "shadow_performance_gate": (
                "paired_mean_squared_error_improvement_exceeds_z_times_standard_error"
            ),
            "supported_forecast_horizons_hours": list(
                self.supported_forecast_horizons_hours
            ),
            "adaptive_forecast_horizons_hours": list(
                self.adaptive_forecast_horizons_hours
            ),
            "bias_adaptive_forecast_horizons_hours": list(
                self.bias_adaptive_forecast_horizons_hours
            ),
            "minimum_matured_sample_count": self.minimum_matured_sample_count,
            "evidence_z_threshold": self.evidence_z_threshold,
            "weight_lower_bound": self.weight_lower_bound,
            "weight_upper_bound": self.weight_upper_bound,
            "target_outcome_used_before_declared_availability": False,
            "finite_signed_observed_target_supported": True,
            "cross_system_parameter_transfer_required": False,
            "insufficient_evidence_fallback": "raw_physical",
            "statistical_coverage_guarantee_claimed": False,
            "admitted": False,
        }


@dataclass(frozen=True)
class PhysicalOnlineResidualMaturedSample:
    """One outcome-derived update, reduced to the statistics used by v4."""

    sample_id: str
    matured_at: datetime
    physical_trajectory_change_m3s: float
    physical_target_error_m3s: float
    shadow_squared_error_m6s2: float | None

    def __post_init__(self) -> None:
        values = (
            self.physical_trajectory_change_m3s,
            self.physical_target_error_m3s,
        )
        shadow = self.shadow_squared_error_m6s2
        if (
            not isinstance(self.sample_id, str)
            or not self.sample_id.strip()
            or not _aware(self.matured_at)
            or any(isinstance(value, bool) for value in values)
            or any(not math.isfinite(float(value)) for value in values)
            or (
                shadow is not None
                and (
                    isinstance(shadow, bool)
                    or not math.isfinite(float(shadow))
                    or float(shadow) < 0.0
                )
            )
        ):
            raise ValueError("physical_online_residual_adaptation_sample_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "sample_id": self.sample_id,
            "matured_at_utc": _iso(self.matured_at),
            "physical_trajectory_change_m3s": float(
                self.physical_trajectory_change_m3s
            ),
            "physical_target_error_m3s": float(self.physical_target_error_m3s),
            "shadow_squared_error_m6s2": (
                None
                if self.shadow_squared_error_m6s2 is None
                else float(self.shadow_squared_error_m6s2)
            ),
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> PhysicalOnlineResidualMaturedSample:
        if set(payload) != {
            "sample_id",
            "matured_at_utc",
            "physical_trajectory_change_m3s",
            "physical_target_error_m3s",
            "shadow_squared_error_m6s2",
        }:
            raise ValueError("physical_online_residual_adaptation_sample_invalid")
        try:
            trajectory_change = float(payload["physical_trajectory_change_m3s"])
            target_error = float(payload["physical_target_error_m3s"])
            raw_shadow = payload["shadow_squared_error_m6s2"]
            shadow = None if raw_shadow is None else float(raw_shadow)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "physical_online_residual_adaptation_sample_invalid"
            ) from exc
        return cls(
            sample_id=payload["sample_id"],  # type: ignore[arg-type]
            matured_at=_parse_datetime(payload["matured_at_utc"]),
            physical_trajectory_change_m3s=trajectory_change,
            physical_target_error_m3s=target_error,
            shadow_squared_error_m6s2=shadow,
        )


@dataclass(frozen=True)
class PhysicalOnlineResidualAdaptationState:
    """Serializable causal state for an independent system-level v4 adapter."""

    system_id: str
    state_as_of: datetime
    config: PhysicalOnlineResidualAdaptationConfig
    samples_by_horizon: tuple[
        tuple[PhysicalOnlineResidualMaturedSample, ...], ...
    ]

    def __post_init__(self) -> None:
        horizons = self.config.supported_forecast_horizons_hours
        if (
            not isinstance(self.system_id, str)
            or not self.system_id.strip()
            or not _aware(self.state_as_of)
            or len(self.samples_by_horizon) != len(horizons)
        ):
            raise ValueError("physical_online_residual_adaptation_state_invalid")
        sample_ids: set[str] = set()
        for samples in self.samples_by_horizon:
            if tuple(
                sorted(samples, key=lambda value: (value.matured_at, value.sample_id))
            ) != samples:
                raise ValueError("physical_online_residual_adaptation_state_invalid")
            for sample in samples:
                if sample.sample_id in sample_ids or sample.matured_at > self.state_as_of:
                    raise ValueError(
                        "physical_online_residual_adaptation_state_invalid"
                    )
                sample_ids.add(sample.sample_id)

    @classmethod
    def empty(
        cls,
        *,
        system_id: str,
        state_as_of: datetime,
        config: PhysicalOnlineResidualAdaptationConfig | None = None,
    ) -> PhysicalOnlineResidualAdaptationState:
        fixed = config or PhysicalOnlineResidualAdaptationConfig()
        return cls(
            system_id=system_id,
            state_as_of=state_as_of,
            config=fixed,
            samples_by_horizon=tuple(
                () for _ in fixed.supported_forecast_horizons_hours
            ),
        )

    def samples_for_horizon(
        self,
        forecast_horizon_hours: int,
    ) -> tuple[PhysicalOnlineResidualMaturedSample, ...]:
        try:
            index = self.config.supported_forecast_horizons_hours.index(
                forecast_horizon_hours
            )
        except ValueError as exc:
            raise ValueError(
                "physical_online_residual_adaptation_horizon_invalid"
            ) from exc
        return self.samples_by_horizon[index]

    def sample_count_by_horizon(self) -> dict[int, int]:
        return {
            horizon: len(self.samples_by_horizon[index])
            for index, horizon in enumerate(
                self.config.supported_forecast_horizons_hours
            )
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": PHYSICAL_ONLINE_RESIDUAL_ADAPTATION_STATE_SCHEMA,
            "system_id": self.system_id,
            "state_as_of_utc": _iso(self.state_as_of),
            "config": _config_dict(self.config),
            "samples_by_horizon": {
                str(horizon): [
                    sample.as_dict() for sample in self.samples_by_horizon[index]
                ]
                for index, horizon in enumerate(
                    self.config.supported_forecast_horizons_hours
                )
            },
            "raw_observations_included": False,
            "current_or_future_target_information_included": False,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> PhysicalOnlineResidualAdaptationState:
        if set(payload) != {
            "schema",
            "system_id",
            "state_as_of_utc",
            "config",
            "samples_by_horizon",
            "raw_observations_included",
            "current_or_future_target_information_included",
        } or (
            payload.get("schema")
            != PHYSICAL_ONLINE_RESIDUAL_ADAPTATION_STATE_SCHEMA
            or payload.get("raw_observations_included") is not False
            or payload.get("current_or_future_target_information_included") is not False
            or not isinstance(payload.get("config"), Mapping)
            or not isinstance(payload.get("samples_by_horizon"), Mapping)
        ):
            raise ValueError("physical_online_residual_adaptation_state_invalid")
        config = _config_from_dict(payload["config"])
        encoded = payload["samples_by_horizon"]
        expected = {
            str(value) for value in config.supported_forecast_horizons_hours
        }
        if set(encoded) != expected:
            raise ValueError("physical_online_residual_adaptation_state_invalid")
        groups = []
        for horizon in config.supported_forecast_horizons_hours:
            values = encoded[str(horizon)]
            if not isinstance(values, list) or any(
                not isinstance(value, Mapping) for value in values
            ):
                raise ValueError(
                    "physical_online_residual_adaptation_state_invalid"
                )
            groups.append(
                tuple(
                    PhysicalOnlineResidualMaturedSample.from_dict(value)
                    for value in values
                )
            )
        return cls(
            system_id=payload["system_id"],  # type: ignore[arg-type]
            state_as_of=_parse_datetime(payload["state_as_of_utc"]),
            config=config,
            samples_by_horizon=tuple(groups),
        )


@dataclass(frozen=True)
class PhysicalOnlineResidualAdaptationStep:
    physical_target_m3s: float
    physical_at_latest_observation_m3s: float
    predictor_forecast_horizon_hours: int | None
    predictor_physical_target_m3s: float | None
    physical_trajectory_change_m3s: float | None
    forecast_horizon_hours: int
    matured_sample_count: int
    raw_weight: float
    weight_standard_error: float | None
    evidence_threshold: float | None
    correction_mode: str
    raw_bias_m3s: float
    bias_standard_error_m3s: float | None
    bias_evidence_threshold_m3s: float | None
    evidence_gate_passed: bool
    shadow_validation_sample_count: int
    shadow_rmse_m3s: float | None
    raw_physical_rmse_m3s: float | None
    shadow_mean_squared_error_improvement_m6s2: float | None
    shadow_improvement_standard_error_m6s2: float | None
    shadow_improvement_threshold_m6s2: float | None
    shadow_performance_gate_passed: bool
    shadow_weight: float
    shadow_bias_m3s: float
    shadow_prediction_m3s: float
    application_gate_passed: bool
    applied_weight: float
    applied_bias_m3s: float
    unbounded_prediction_m3s: float
    corrected_prediction_m3s: float
    clipped: bool


class PhysicalOnlineResidualAdapter:
    """Learn physical-error corrections only from causally mature outcomes."""

    def __init__(
        self,
        config: PhysicalOnlineResidualAdaptationConfig | None = None,
    ) -> None:
        self.config = config or PhysicalOnlineResidualAdaptationConfig()
        self._samples: dict[int, list[tuple[float, float]]] = {
            horizon: [] for horizon in self.config.supported_forecast_horizons_hours
        }
        self._sample_ids: set[str] = set()
        self._latest_update_time: datetime | None = None
        self._shadow_squared_errors: dict[int, list[tuple[float, float]]] = {
            horizon: [] for horizon in self.config.supported_forecast_horizons_hours
        }
        self._matured_samples: dict[
            int, list[PhysicalOnlineResidualMaturedSample]
        ] = {
            horizon: [] for horizon in self.config.supported_forecast_horizons_hours
        }

    @classmethod
    def from_state(
        cls,
        state: PhysicalOnlineResidualAdaptationState,
    ) -> PhysicalOnlineResidualAdapter:
        """Restore the exact sufficient statistics without replaying raw outcomes."""

        if not isinstance(state, PhysicalOnlineResidualAdaptationState):
            raise TypeError("physical_online_residual_adaptation_state_required")
        adapter = cls(state.config)
        for index, horizon in enumerate(
            state.config.supported_forecast_horizons_hours
        ):
            samples = list(state.samples_by_horizon[index])
            adapter._matured_samples[horizon] = samples
            adapter._samples[horizon] = [
                (
                    sample.physical_trajectory_change_m3s,
                    sample.physical_target_error_m3s,
                )
                for sample in samples
            ]
            adapter._shadow_squared_errors[horizon] = [
                (
                    float(sample.shadow_squared_error_m6s2),
                    sample.physical_target_error_m3s**2,
                )
                for sample in samples
                if sample.shadow_squared_error_m6s2 is not None
            ]
            adapter._sample_ids.update(sample.sample_id for sample in samples)
        adapter._latest_update_time = state.state_as_of.astimezone(UTC)
        return adapter

    def export_state(
        self,
        *,
        system_id: str,
        state_as_of: datetime,
    ) -> PhysicalOnlineResidualAdaptationState:
        """Export only causal sufficient statistics, never raw observations."""

        if (
            not isinstance(system_id, str)
            or not system_id.strip()
            or not _aware(state_as_of)
            or (
                self._latest_update_time is not None
                and state_as_of < self._latest_update_time
            )
        ):
            raise ValueError("physical_online_residual_adaptation_state_invalid")
        return PhysicalOnlineResidualAdaptationState(
            system_id=system_id,
            state_as_of=state_as_of.astimezone(UTC),
            config=self.config,
            samples_by_horizon=tuple(
                tuple(
                    sorted(
                        self._matured_samples[horizon],
                        key=lambda value: (value.matured_at, value.sample_id),
                    )
                )
                for horizon in self.config.supported_forecast_horizons_hours
            ),
        )

    def update(
        self,
        *,
        sample_id: str,
        forecast_horizon_hours: int,
        physical_trajectory_change_m3s: float,
        physical_target_m3s: float,
        candidate_shadow_prediction_m3s: float,
        candidate_evidence_gate_passed: bool,
        observed_target_m3s: float,
        target_observation_available_at: datetime,
        update_time: datetime,
    ) -> None:
        """Reveal one matured forecast error; future outcomes are rejected."""

        available_at = target_observation_available_at
        if (
            not isinstance(sample_id, str)
            or not sample_id.strip()
            or sample_id in self._sample_ids
            or forecast_horizon_hours not in self._samples
            or not isinstance(candidate_evidence_gate_passed, bool)
            or not _aware(available_at)
            or not _aware(update_time)
            or available_at > update_time
            or (
                self._latest_update_time is not None
                and update_time < self._latest_update_time
            )
        ):
            raise ValueError("physical_online_residual_adaptation_update_invalid")
        values = (
            physical_trajectory_change_m3s,
            physical_target_m3s,
            candidate_shadow_prediction_m3s,
            observed_target_m3s,
        )
        if (
            any(not math.isfinite(float(value)) for value in values)
            or float(physical_target_m3s) < 0.0
            or float(candidate_shadow_prediction_m3s) < 0.0
        ):
            raise ValueError("physical_online_residual_adaptation_update_invalid")
        target_error = float(observed_target_m3s) - float(physical_target_m3s)
        self._samples[forecast_horizon_hours].append(
            (float(physical_trajectory_change_m3s), target_error)
        )
        shadow_squared_error = (
            (
                float(observed_target_m3s)
                - float(candidate_shadow_prediction_m3s)
            )
            ** 2
            if candidate_evidence_gate_passed
            else None
        )
        self._matured_samples[forecast_horizon_hours].append(
            PhysicalOnlineResidualMaturedSample(
                sample_id=sample_id,
                matured_at=available_at.astimezone(UTC),
                physical_trajectory_change_m3s=float(
                    physical_trajectory_change_m3s
                ),
                physical_target_error_m3s=target_error,
                shadow_squared_error_m6s2=shadow_squared_error,
            )
        )
        self._sample_ids.add(sample_id)
        self._latest_update_time = update_time
        if candidate_evidence_gate_passed:
            self._shadow_squared_errors[forecast_horizon_hours].append(
                (float(shadow_squared_error), target_error**2)
            )

    def predict(
        self,
        *,
        forecast_horizon_hours: int,
        physical_at_latest_observation_m3s: float,
        predictor_physical_target_m3s: float | None,
        physical_target_m3s: float,
        issue_time: datetime,
    ) -> PhysicalOnlineResidualAdaptationStep:
        """Correct a forecast only after the online evidence gate passes."""

        if (
            forecast_horizon_hours not in self._samples
            or not _aware(issue_time)
            or (
                self._latest_update_time is not None
                and issue_time < self._latest_update_time
            )
            or not math.isfinite(float(physical_at_latest_observation_m3s))
            or not math.isfinite(float(physical_target_m3s))
            or (
                predictor_physical_target_m3s is not None
                and (
                    not math.isfinite(float(predictor_physical_target_m3s))
                    or predictor_physical_target_m3s < 0.0
                )
            )
            or physical_at_latest_observation_m3s < 0.0
            or physical_target_m3s < 0.0
        ):
            raise ValueError("physical_online_residual_adaptation_forecast_invalid")
        predictor_horizon = dict(
            self.config.trajectory_predictor_horizon_pairs
        ).get(forecast_horizon_hours)
        trajectory_change = (
            float(predictor_physical_target_m3s)
            - float(physical_at_latest_observation_m3s)
            if predictor_horizon is not None
            and predictor_physical_target_m3s is not None
            else None
        )
        samples = self._samples[forecast_horizon_hours]
        sample_count = len(samples)
        denominator = sum(source**2 for source, _ in samples)
        raw_weight = (
            sum(source * target for source, target in samples) / denominator
            if denominator > 0.0
            else 0.0
        )
        standard_error: float | None = None
        evidence_threshold: float | None = None
        if sample_count >= 2 and denominator > 0.0:
            residual_sum_squares = sum(
                (target - raw_weight * source) ** 2 for source, target in samples
            )
            variance = residual_sum_squares / (sample_count - 1)
            standard_error = math.sqrt(max(0.0, variance) / denominator)
            evidence_threshold = self.config.evidence_z_threshold * standard_error
        residual_evidence_gate_passed = (
            forecast_horizon_hours in self.config.adaptive_forecast_horizons_hours
            and trajectory_change is not None
            and sample_count >= self.config.minimum_matured_sample_count
            and evidence_threshold is not None
            and abs(raw_weight) > evidence_threshold
        )
        target_errors = [target for _, target in samples]
        raw_bias = sum(target_errors) / sample_count if sample_count else 0.0
        bias_standard_error: float | None = None
        bias_evidence_threshold: float | None = None
        if sample_count >= 2:
            bias_variance = sum(
                (target - raw_bias) ** 2 for target in target_errors
            ) / (sample_count - 1)
            bias_standard_error = math.sqrt(
                max(0.0, bias_variance) / sample_count
            )
            bias_evidence_threshold = (
                self.config.evidence_z_threshold * bias_standard_error
            )
        bias_evidence_gate_passed = (
            forecast_horizon_hours
            in self.config.bias_adaptive_forecast_horizons_hours
            and sample_count >= self.config.minimum_matured_sample_count
            and bias_evidence_threshold is not None
            and abs(raw_bias) > bias_evidence_threshold
        )
        evidence_gate_passed = (
            residual_evidence_gate_passed or bias_evidence_gate_passed
        )
        correction_mode = (
            "phase_lead_physical_trajectory_change"
            if forecast_horizon_hours
            in self.config.adaptive_forecast_horizons_hours
            else "mean_physical_error"
            if forecast_horizon_hours
            in self.config.bias_adaptive_forecast_horizons_hours
            else "raw_physical"
        )
        shadow_weight = (
            min(
                self.config.weight_upper_bound,
                max(self.config.weight_lower_bound, raw_weight),
            )
            if residual_evidence_gate_passed
            else 0.0
        )
        shadow_bias = raw_bias if bias_evidence_gate_passed else 0.0
        shadow_prediction = max(
            0.0,
            float(physical_target_m3s)
            + shadow_bias
            + shadow_weight * (trajectory_change or 0.0),
        )
        shadow_errors = self._shadow_squared_errors[forecast_horizon_hours]
        shadow_count = len(shadow_errors)
        shadow_rmse = (
            math.sqrt(sum(value[0] for value in shadow_errors) / shadow_count)
            if shadow_count
            else None
        )
        raw_rmse = (
            math.sqrt(sum(value[1] for value in shadow_errors) / shadow_count)
            if shadow_count
            else None
        )
        improvements = [raw - shadow for shadow, raw in shadow_errors]
        mean_improvement = (
            sum(improvements) / shadow_count if shadow_count else None
        )
        improvement_standard_error: float | None = None
        improvement_threshold: float | None = None
        if shadow_count >= 2 and mean_improvement is not None:
            improvement_variance = sum(
                (value - mean_improvement) ** 2 for value in improvements
            ) / (shadow_count - 1)
            improvement_standard_error = math.sqrt(
                max(0.0, improvement_variance) / shadow_count
            )
            improvement_threshold = (
                self.config.evidence_z_threshold * improvement_standard_error
            )
        performance_gate_passed = (
            shadow_count >= self.config.minimum_matured_sample_count
            and mean_improvement is not None
            and improvement_threshold is not None
            and mean_improvement > improvement_threshold
        )
        application_gate_passed = evidence_gate_passed and performance_gate_passed
        applied_weight = shadow_weight if application_gate_passed else 0.0
        applied_bias = shadow_bias if application_gate_passed else 0.0
        unbounded = (
            float(physical_target_m3s)
            + applied_bias
            + applied_weight * (trajectory_change or 0.0)
        )
        corrected = max(0.0, unbounded)
        return PhysicalOnlineResidualAdaptationStep(
            physical_target_m3s=float(physical_target_m3s),
            physical_at_latest_observation_m3s=float(
                physical_at_latest_observation_m3s
            ),
            predictor_forecast_horizon_hours=predictor_horizon,
            predictor_physical_target_m3s=(
                None
                if predictor_physical_target_m3s is None
                else float(predictor_physical_target_m3s)
            ),
            physical_trajectory_change_m3s=trajectory_change,
            forecast_horizon_hours=forecast_horizon_hours,
            matured_sample_count=sample_count,
            raw_weight=raw_weight,
            weight_standard_error=standard_error,
            evidence_threshold=evidence_threshold,
            correction_mode=correction_mode,
            raw_bias_m3s=raw_bias,
            bias_standard_error_m3s=bias_standard_error,
            bias_evidence_threshold_m3s=bias_evidence_threshold,
            evidence_gate_passed=evidence_gate_passed,
            shadow_validation_sample_count=shadow_count,
            shadow_rmse_m3s=shadow_rmse,
            raw_physical_rmse_m3s=raw_rmse,
            shadow_mean_squared_error_improvement_m6s2=mean_improvement,
            shadow_improvement_standard_error_m6s2=(
                improvement_standard_error
            ),
            shadow_improvement_threshold_m6s2=improvement_threshold,
            shadow_performance_gate_passed=performance_gate_passed,
            shadow_weight=shadow_weight,
            shadow_bias_m3s=shadow_bias,
            shadow_prediction_m3s=shadow_prediction,
            application_gate_passed=application_gate_passed,
            applied_weight=applied_weight,
            applied_bias_m3s=applied_bias,
            unbounded_prediction_m3s=unbounded,
            corrected_prediction_m3s=corrected,
            clipped=unbounded < 0.0,
        )

    def sample_count_by_horizon(self) -> dict[int, int]:
        return {horizon: len(samples) for horizon, samples in self._samples.items()}


def _config_dict(
    config: PhysicalOnlineResidualAdaptationConfig,
) -> dict[str, object]:
    return {
        "supported_forecast_horizons_hours": list(
            config.supported_forecast_horizons_hours
        ),
        "adaptive_forecast_horizons_hours": list(
            config.adaptive_forecast_horizons_hours
        ),
        "bias_adaptive_forecast_horizons_hours": list(
            config.bias_adaptive_forecast_horizons_hours
        ),
        "trajectory_predictor_horizon_pairs": [
            list(value) for value in config.trajectory_predictor_horizon_pairs
        ],
        "minimum_matured_sample_count": config.minimum_matured_sample_count,
        "evidence_z_threshold": config.evidence_z_threshold,
        "weight_lower_bound": config.weight_lower_bound,
        "weight_upper_bound": config.weight_upper_bound,
    }


def _config_from_dict(
    payload: Mapping[str, object],
) -> PhysicalOnlineResidualAdaptationConfig:
    if set(payload) != {
        "supported_forecast_horizons_hours",
        "adaptive_forecast_horizons_hours",
        "bias_adaptive_forecast_horizons_hours",
        "trajectory_predictor_horizon_pairs",
        "minimum_matured_sample_count",
        "evidence_z_threshold",
        "weight_lower_bound",
        "weight_upper_bound",
    }:
        raise ValueError("physical_online_residual_adaptation_config_invalid")
    supported = payload["supported_forecast_horizons_hours"]
    adaptive = payload["adaptive_forecast_horizons_hours"]
    bias_adaptive = payload["bias_adaptive_forecast_horizons_hours"]
    predictor_pairs = payload["trajectory_predictor_horizon_pairs"]
    if (
        not isinstance(supported, list)
        or not isinstance(adaptive, list)
        or not isinstance(bias_adaptive, list)
        or not isinstance(predictor_pairs, list)
        or any(not isinstance(value, list) for value in predictor_pairs)
    ):
        raise ValueError("physical_online_residual_adaptation_config_invalid")
    try:
        return PhysicalOnlineResidualAdaptationConfig(
            supported_forecast_horizons_hours=tuple(supported),  # type: ignore[arg-type]
            adaptive_forecast_horizons_hours=tuple(adaptive),  # type: ignore[arg-type]
            bias_adaptive_forecast_horizons_hours=tuple(  # type: ignore[arg-type]
                bias_adaptive
            ),
            trajectory_predictor_horizon_pairs=tuple(
                tuple(value) for value in predictor_pairs  # type: ignore[arg-type]
            ),
            minimum_matured_sample_count=payload[  # type: ignore[arg-type]
                "minimum_matured_sample_count"
            ],
            evidence_z_threshold=float(payload["evidence_z_threshold"]),
            weight_lower_bound=float(payload["weight_lower_bound"]),
            weight_upper_bound=float(payload["weight_upper_bound"]),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "physical_online_residual_adaptation_config_invalid"
        ) from exc
