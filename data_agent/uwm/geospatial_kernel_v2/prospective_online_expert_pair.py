"""Outcome-free prospective comparison of the frozen v5 and FTL experts."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.physical_online_expert_blend import (
    PhysicalOnlineExpertBlendConfig,
    PhysicalOnlineExpertBlendStep,
)

PROSPECTIVE_ONLINE_EXPERT_PAIR_STATE_SCHEMA = (
    "gwm.geospatial_kernel.prospective_online_expert_pair_state.v1"
)
PROSPECTIVE_ONLINE_EXPERT_PAIR_PREDICTION_SCHEMA = (
    "gwm.geospatial_kernel.prospective_online_expert_pair_prediction.v1"
)
PRIMARY_CANDIDATE_ID = "physical_online_expert_blend_v5"
TRADITIONAL_BASELINE_ID = "evidence_gated_follow_the_leader"


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("prospective_online_expert_pair_datetime_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("prospective_online_expert_pair_datetime_invalid") from exc
    if not _aware(parsed):
        raise ValueError("prospective_online_expert_pair_datetime_invalid")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _strict_keys(
    payload: Mapping[str, object],
    expected: set[str],
    error: str,
) -> None:
    if set(payload) != expected:
        raise ValueError(error)


@dataclass(frozen=True)
class ProspectiveOnlineExpertMaturedSample:
    """One matured, outcome-derived state update without the raw observation."""

    sample_id: str
    matured_at: datetime
    alternative_delta_m3s: float
    baseline_target_error_m3s: float
    coefficient_gate_shadow_squared_error_m6s2: float | None

    def __post_init__(self) -> None:
        values = (self.alternative_delta_m3s, self.baseline_target_error_m3s)
        shadow = self.coefficient_gate_shadow_squared_error_m6s2
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
            raise ValueError("prospective_online_expert_pair_sample_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "sample_id": self.sample_id,
            "matured_at_utc": _iso(self.matured_at),
            "alternative_delta_m3s": float(self.alternative_delta_m3s),
            "baseline_target_error_m3s": float(self.baseline_target_error_m3s),
            "coefficient_gate_shadow_squared_error_m6s2": (
                None
                if self.coefficient_gate_shadow_squared_error_m6s2 is None
                else float(self.coefficient_gate_shadow_squared_error_m6s2)
            ),
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> ProspectiveOnlineExpertMaturedSample:
        _strict_keys(
            payload,
            {
                "sample_id",
                "matured_at_utc",
                "alternative_delta_m3s",
                "baseline_target_error_m3s",
                "coefficient_gate_shadow_squared_error_m6s2",
            },
            "prospective_online_expert_pair_sample_invalid",
        )
        try:
            delta = float(payload["alternative_delta_m3s"])
            error = float(payload["baseline_target_error_m3s"])
            shadow_value = payload["coefficient_gate_shadow_squared_error_m6s2"]
            shadow = None if shadow_value is None else float(shadow_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("prospective_online_expert_pair_sample_invalid") from exc
        return cls(
            sample_id=payload["sample_id"],  # type: ignore[arg-type]
            matured_at=_parse_datetime(payload["matured_at_utc"]),
            alternative_delta_m3s=delta,
            baseline_target_error_m3s=error,
            coefficient_gate_shadow_squared_error_m6s2=shadow,
        )


@dataclass(frozen=True)
class ProspectiveOnlineExpertMaturedFeedback:
    """Transient authoritative feedback for one already sealed forecast."""

    sample_id: str
    forecast_horizon_hours: int
    target_support_end: datetime
    observed_discharge_m3s: float
    observation_available_at: datetime
    baseline_prediction_m3s: float
    alternative_prediction_m3s: float
    coefficient_gate_shadow_prediction_m3s: float
    coefficient_gate_passed: bool

    def __post_init__(self) -> None:
        predictions = (
            self.baseline_prediction_m3s,
            self.alternative_prediction_m3s,
            self.coefficient_gate_shadow_prediction_m3s,
        )
        if (
            not isinstance(self.sample_id, str)
            or not self.sample_id.strip()
            or not isinstance(self.forecast_horizon_hours, int)
            or isinstance(self.forecast_horizon_hours, bool)
            or self.forecast_horizon_hours <= 0
            or not _aware(self.target_support_end)
            or not _aware(self.observation_available_at)
            or self.observation_available_at < self.target_support_end
            or isinstance(self.observed_discharge_m3s, bool)
            or not math.isfinite(float(self.observed_discharge_m3s))
            or any(isinstance(value, bool) for value in predictions)
            or any(not math.isfinite(float(value)) or float(value) < 0.0 for value in predictions)
            or not isinstance(self.coefficient_gate_passed, bool)
        ):
            raise ValueError("prospective_online_expert_pair_feedback_invalid")


@dataclass(frozen=True)
class ProspectiveOnlineExpertPairState:
    """Read-only state shared by the candidate and traditional comparator."""

    system_id: str
    state_as_of: datetime
    config: PhysicalOnlineExpertBlendConfig
    samples_by_horizon: tuple[tuple[ProspectiveOnlineExpertMaturedSample, ...], ...]

    def __post_init__(self) -> None:
        horizons = self.config.supported_forecast_horizons_hours
        if (
            not isinstance(self.system_id, str)
            or not self.system_id.strip()
            or not _aware(self.state_as_of)
            or len(self.samples_by_horizon) != len(horizons)
        ):
            raise ValueError("prospective_online_expert_pair_state_invalid")
        sample_ids: set[str] = set()
        for samples in self.samples_by_horizon:
            if (
                tuple(sorted(samples, key=lambda value: (value.matured_at, value.sample_id)))
                != samples
            ):
                raise ValueError("prospective_online_expert_pair_state_invalid")
            for sample in samples:
                if sample.sample_id in sample_ids or sample.matured_at > self.state_as_of:
                    raise ValueError("prospective_online_expert_pair_state_invalid")
                sample_ids.add(sample.sample_id)

    @classmethod
    def empty(
        cls,
        *,
        system_id: str,
        state_as_of: datetime,
        config: PhysicalOnlineExpertBlendConfig | None = None,
    ) -> ProspectiveOnlineExpertPairState:
        fixed_config = config or PhysicalOnlineExpertBlendConfig()
        return cls(
            system_id=system_id,
            state_as_of=state_as_of,
            config=fixed_config,
            samples_by_horizon=tuple(() for _ in fixed_config.supported_forecast_horizons_hours),
        )

    def samples_for_horizon(
        self,
        forecast_horizon_hours: int,
    ) -> tuple[ProspectiveOnlineExpertMaturedSample, ...]:
        try:
            index = self.config.supported_forecast_horizons_hours.index(forecast_horizon_hours)
        except ValueError as exc:
            raise ValueError("prospective_online_expert_pair_horizon_invalid") from exc
        return self.samples_by_horizon[index]

    def sample_count_by_horizon(self) -> dict[int, int]:
        return {
            horizon: len(self.samples_by_horizon[index])
            for index, horizon in enumerate(self.config.supported_forecast_horizons_hours)
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": PROSPECTIVE_ONLINE_EXPERT_PAIR_STATE_SCHEMA,
            "system_id": self.system_id,
            "state_as_of_utc": _iso(self.state_as_of),
            "config": _config_dict(self.config),
            "samples_by_horizon": {
                str(horizon): [sample.as_dict() for sample in self.samples_by_horizon[index]]
                for index, horizon in enumerate(self.config.supported_forecast_horizons_hours)
            },
            "raw_observations_included": False,
            "current_or_future_target_information_included": False,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> ProspectiveOnlineExpertPairState:
        _strict_keys(
            payload,
            {
                "schema",
                "system_id",
                "state_as_of_utc",
                "config",
                "samples_by_horizon",
                "raw_observations_included",
                "current_or_future_target_information_included",
            },
            "prospective_online_expert_pair_state_invalid",
        )
        if (
            payload.get("schema") != PROSPECTIVE_ONLINE_EXPERT_PAIR_STATE_SCHEMA
            or payload.get("raw_observations_included") is not False
            or payload.get("current_or_future_target_information_included") is not False
            or not isinstance(payload.get("config"), Mapping)
            or not isinstance(payload.get("samples_by_horizon"), Mapping)
        ):
            raise ValueError("prospective_online_expert_pair_state_invalid")
        config = _config_from_dict(payload["config"])
        encoded_samples = payload["samples_by_horizon"]
        expected_horizons = {str(value) for value in config.supported_forecast_horizons_hours}
        if set(encoded_samples) != expected_horizons:
            raise ValueError("prospective_online_expert_pair_state_invalid")
        groups = []
        for horizon in config.supported_forecast_horizons_hours:
            values = encoded_samples[str(horizon)]
            if not isinstance(values, list) or any(
                not isinstance(value, Mapping) for value in values
            ):
                raise ValueError("prospective_online_expert_pair_state_invalid")
            groups.append(
                tuple(ProspectiveOnlineExpertMaturedSample.from_dict(value) for value in values)
            )
        return cls(
            system_id=payload["system_id"],  # type: ignore[arg-type]
            state_as_of=_parse_datetime(payload["state_as_of_utc"]),
            config=config,
            samples_by_horizon=tuple(groups),
        )


@dataclass(frozen=True)
class EvidenceGatedFollowTheLeaderStep:
    forecast_horizon_hours: int
    baseline_prediction_m3s: float
    alternative_prediction_m3s: float
    matured_sample_count: int
    baseline_minus_alternative_mean_squared_error_m6s2: float | None
    improvement_standard_error_m6s2: float | None
    improvement_threshold_m6s2: float | None
    alternative_selected: bool
    selected_prediction_m3s: float


@dataclass(frozen=True)
class ProspectiveOnlineExpertPairStep:
    system_id: str
    issue_time: datetime
    state_as_of: datetime
    forecast_horizon_hours: int
    primary_candidate: PhysicalOnlineExpertBlendStep
    traditional_baseline: EvidenceGatedFollowTheLeaderStep

    def as_dict(self) -> dict[str, object]:
        candidate = self.primary_candidate
        baseline = self.traditional_baseline
        return {
            "schema": PROSPECTIVE_ONLINE_EXPERT_PAIR_PREDICTION_SCHEMA,
            "system_id": self.system_id,
            "issue_time_utc": _iso(self.issue_time),
            "state_as_of_utc": _iso(self.state_as_of),
            "forecast_horizon_hours": self.forecast_horizon_hours,
            "physical_online_residual_adaptation_v4_m3s": (candidate.baseline_prediction_m3s),
            "action_innovation_wwm_m3s": candidate.alternative_prediction_m3s,
            "physical_online_expert_blend_v5_m3s": (candidate.blended_prediction_m3s),
            "evidence_gated_follow_the_leader_m3s": (baseline.selected_prediction_m3s),
            "matured_sample_count": candidate.matured_sample_count,
            "v5_raw_weight": candidate.raw_weight,
            "v5_coefficient_gate_passed": candidate.evidence_gate_passed,
            "v5_shadow_validation_sample_count": (candidate.shadow_validation_sample_count),
            "v5_shadow_performance_gate_passed": (candidate.shadow_performance_gate_passed),
            "v5_application_gate_passed": candidate.application_gate_passed,
            "v5_applied_weight": candidate.applied_weight,
            "v5_shadow_prediction_m3s": candidate.shadow_prediction_m3s,
            "traditional_baseline_wwm_selected": baseline.alternative_selected,
            "raw_observation_used_for_prediction": False,
            "current_or_future_target_used_for_prediction": False,
        }


class ProspectiveOnlineExpertPairRunner:
    """Emit both frozen predictions from one pre-issue state snapshot."""

    def __init__(self, state: ProspectiveOnlineExpertPairState) -> None:
        self.state = state

    def predict(
        self,
        *,
        forecast_horizon_hours: int,
        baseline_prediction_m3s: float,
        alternative_prediction_m3s: float,
        issue_time: datetime,
    ) -> ProspectiveOnlineExpertPairStep:
        if (
            not _aware(issue_time)
            or issue_time < self.state.state_as_of
            or not math.isfinite(float(baseline_prediction_m3s))
            or not math.isfinite(float(alternative_prediction_m3s))
            or float(baseline_prediction_m3s) < 0.0
            or float(alternative_prediction_m3s) < 0.0
        ):
            raise ValueError("prospective_online_expert_pair_forecast_invalid")
        samples = self.state.samples_for_horizon(forecast_horizon_hours)
        candidate = _physical_online_expert_blend_step(
            samples=samples,
            config=self.state.config,
            forecast_horizon_hours=forecast_horizon_hours,
            baseline_prediction_m3s=float(baseline_prediction_m3s),
            alternative_prediction_m3s=float(alternative_prediction_m3s),
        )
        traditional = _follow_the_leader_step(
            samples=samples,
            config=self.state.config,
            forecast_horizon_hours=forecast_horizon_hours,
            baseline_prediction_m3s=float(baseline_prediction_m3s),
            alternative_prediction_m3s=float(alternative_prediction_m3s),
        )
        return ProspectiveOnlineExpertPairStep(
            system_id=self.state.system_id,
            issue_time=issue_time.astimezone(UTC),
            state_as_of=self.state.state_as_of.astimezone(UTC),
            forecast_horizon_hours=forecast_horizon_hours,
            primary_candidate=candidate,
            traditional_baseline=traditional,
        )


def advance_prospective_online_expert_pair_state(
    state: ProspectiveOnlineExpertPairState,
    feedbacks: tuple[ProspectiveOnlineExpertMaturedFeedback, ...],
    *,
    update_time: datetime,
) -> ProspectiveOnlineExpertPairState:
    """Append only feedback available by update time; never retain raw outcomes."""

    if (
        not isinstance(state, ProspectiveOnlineExpertPairState)
        or not feedbacks
        or any(not isinstance(value, ProspectiveOnlineExpertMaturedFeedback) for value in feedbacks)
        or not _aware(update_time)
        or update_time < state.state_as_of
    ):
        raise ValueError("prospective_online_expert_pair_state_update_invalid")
    horizons = state.config.supported_forecast_horizons_hours
    existing_ids = {sample.sample_id for samples in state.samples_by_horizon for sample in samples}
    new_ids: set[str] = set()
    groups = [list(samples) for samples in state.samples_by_horizon]
    for feedback in feedbacks:
        if (
            feedback.forecast_horizon_hours not in horizons
            or feedback.sample_id in existing_ids
            or feedback.sample_id in new_ids
            or feedback.observation_available_at > update_time
        ):
            raise ValueError("prospective_online_expert_pair_state_update_invalid")
        baseline = float(feedback.baseline_prediction_m3s)
        alternative = float(feedback.alternative_prediction_m3s)
        observed = float(feedback.observed_discharge_m3s)
        shadow = float(feedback.coefficient_gate_shadow_prediction_m3s)
        sample = ProspectiveOnlineExpertMaturedSample(
            sample_id=feedback.sample_id,
            matured_at=feedback.observation_available_at,
            alternative_delta_m3s=alternative - baseline,
            baseline_target_error_m3s=observed - baseline,
            coefficient_gate_shadow_squared_error_m6s2=(
                (observed - shadow) ** 2 if feedback.coefficient_gate_passed else None
            ),
        )
        index = horizons.index(feedback.forecast_horizon_hours)
        groups[index].append(sample)
        new_ids.add(feedback.sample_id)
    return ProspectiveOnlineExpertPairState(
        system_id=state.system_id,
        state_as_of=update_time.astimezone(UTC),
        config=state.config,
        samples_by_horizon=tuple(
            tuple(sorted(values, key=lambda value: (value.matured_at, value.sample_id)))
            for values in groups
        ),
    )


def algorithm_contract(
    config: PhysicalOnlineExpertBlendConfig | None = None,
) -> dict[str, Any]:
    fixed = config or PhysicalOnlineExpertBlendConfig()
    return {
        "primary_candidate": PRIMARY_CANDIDATE_ID,
        "primary_formula": ("max(0, v4 + admitted_weight_h * (WWM - v4)), 0 <= weight_h <= 1"),
        "traditional_baseline": TRADITIONAL_BASELINE_ID,
        "traditional_baseline_formula": (
            "WWM if matured_mean(v4_squared_error - WWM_squared_error) > z * standard_error else v4"
        ),
        "shared_config": _config_dict(fixed),
        "one_independent_state_per_system_and_horizon": True,
        "state_may_use_only_samples_matured_by_state_as_of": True,
        "prediction_api_accepts_observation_or_outcome": False,
        "candidate_or_baseline_selected_from_current_window_scores": False,
        "primary_candidate_admitted": False,
    }


def _physical_online_expert_blend_step(
    *,
    samples: tuple[ProspectiveOnlineExpertMaturedSample, ...],
    config: PhysicalOnlineExpertBlendConfig,
    forecast_horizon_hours: int,
    baseline_prediction_m3s: float,
    alternative_prediction_m3s: float,
) -> PhysicalOnlineExpertBlendStep:
    baseline = baseline_prediction_m3s
    alternative_delta = alternative_prediction_m3s - baseline
    sample_count = len(samples)
    denominator = sum(sample.alternative_delta_m3s**2 for sample in samples)
    raw_weight = (
        sum(sample.alternative_delta_m3s * sample.baseline_target_error_m3s for sample in samples)
        / denominator
        if denominator > 0.0
        else 0.0
    )
    standard_error: float | None = None
    evidence_threshold: float | None = None
    if sample_count >= 2 and denominator > 0.0:
        residual_sum_squares = sum(
            (sample.baseline_target_error_m3s - raw_weight * sample.alternative_delta_m3s) ** 2
            for sample in samples
        )
        variance = residual_sum_squares / (sample_count - 1)
        standard_error = math.sqrt(max(0.0, variance) / denominator)
        evidence_threshold = config.evidence_z_threshold * standard_error
    evidence_gate_passed = (
        sample_count >= config.minimum_matured_sample_count
        and evidence_threshold is not None
        and raw_weight > evidence_threshold
    )
    shadow_weight = (
        min(config.weight_upper_bound, max(config.weight_lower_bound, raw_weight))
        if evidence_gate_passed
        else 0.0
    )
    shadow_prediction = max(0.0, baseline + shadow_weight * alternative_delta)
    shadow_errors = [
        (
            float(sample.coefficient_gate_shadow_squared_error_m6s2),
            sample.baseline_target_error_m3s**2,
        )
        for sample in samples
        if sample.coefficient_gate_shadow_squared_error_m6s2 is not None
    ]
    shadow_count = len(shadow_errors)
    shadow_rmse = (
        math.sqrt(sum(value[0] for value in shadow_errors) / shadow_count) if shadow_count else None
    )
    baseline_rmse = (
        math.sqrt(sum(value[1] for value in shadow_errors) / shadow_count) if shadow_count else None
    )
    improvements = [baseline_error - shadow for shadow, baseline_error in shadow_errors]
    mean_improvement = sum(improvements) / shadow_count if shadow_count else None
    improvement_standard_error: float | None = None
    improvement_threshold: float | None = None
    if shadow_count >= 2 and mean_improvement is not None:
        improvement_variance = sum((value - mean_improvement) ** 2 for value in improvements) / (
            shadow_count - 1
        )
        improvement_standard_error = math.sqrt(max(0.0, improvement_variance) / shadow_count)
        improvement_threshold = config.evidence_z_threshold * improvement_standard_error
    performance_gate_passed = (
        shadow_count >= config.minimum_matured_sample_count
        and mean_improvement is not None
        and improvement_threshold is not None
        and mean_improvement > improvement_threshold
    )
    application_gate_passed = evidence_gate_passed and performance_gate_passed
    applied_weight = shadow_weight if application_gate_passed else 0.0
    unbounded_prediction = baseline + applied_weight * alternative_delta
    blended_prediction = max(0.0, unbounded_prediction)
    return PhysicalOnlineExpertBlendStep(
        forecast_horizon_hours=forecast_horizon_hours,
        baseline_prediction_m3s=baseline,
        alternative_prediction_m3s=alternative_prediction_m3s,
        alternative_delta_m3s=alternative_delta,
        matured_sample_count=sample_count,
        raw_weight=raw_weight,
        weight_standard_error=standard_error,
        evidence_threshold=evidence_threshold,
        evidence_gate_passed=evidence_gate_passed,
        shadow_validation_sample_count=shadow_count,
        shadow_rmse_m3s=shadow_rmse,
        baseline_rmse_m3s=baseline_rmse,
        shadow_mean_squared_error_improvement_m6s2=mean_improvement,
        shadow_improvement_standard_error_m6s2=improvement_standard_error,
        shadow_improvement_threshold_m6s2=improvement_threshold,
        shadow_performance_gate_passed=performance_gate_passed,
        shadow_weight=shadow_weight,
        shadow_prediction_m3s=shadow_prediction,
        application_gate_passed=application_gate_passed,
        applied_weight=applied_weight,
        unbounded_prediction_m3s=unbounded_prediction,
        blended_prediction_m3s=blended_prediction,
        clipped=blended_prediction != unbounded_prediction,
    )


def _follow_the_leader_step(
    *,
    samples: tuple[ProspectiveOnlineExpertMaturedSample, ...],
    config: PhysicalOnlineExpertBlendConfig,
    forecast_horizon_hours: int,
    baseline_prediction_m3s: float,
    alternative_prediction_m3s: float,
) -> EvidenceGatedFollowTheLeaderStep:
    improvements = [
        sample.baseline_target_error_m3s**2
        - (sample.baseline_target_error_m3s - sample.alternative_delta_m3s) ** 2
        for sample in samples
    ]
    sample_count = len(improvements)
    mean_improvement = sum(improvements) / sample_count if sample_count else None
    standard_error: float | None = None
    threshold: float | None = None
    if sample_count >= 2 and mean_improvement is not None:
        variance = sum((value - mean_improvement) ** 2 for value in improvements) / (
            sample_count - 1
        )
        standard_error = math.sqrt(max(0.0, variance) / sample_count)
        threshold = config.evidence_z_threshold * standard_error
    selected = (
        sample_count >= config.minimum_matured_sample_count
        and mean_improvement is not None
        and threshold is not None
        and mean_improvement > threshold
    )
    return EvidenceGatedFollowTheLeaderStep(
        forecast_horizon_hours=forecast_horizon_hours,
        baseline_prediction_m3s=baseline_prediction_m3s,
        alternative_prediction_m3s=alternative_prediction_m3s,
        matured_sample_count=sample_count,
        baseline_minus_alternative_mean_squared_error_m6s2=mean_improvement,
        improvement_standard_error_m6s2=standard_error,
        improvement_threshold_m6s2=threshold,
        alternative_selected=selected,
        selected_prediction_m3s=(
            alternative_prediction_m3s if selected else baseline_prediction_m3s
        ),
    )


def _config_dict(config: PhysicalOnlineExpertBlendConfig) -> dict[str, object]:
    return {
        "supported_forecast_horizons_hours": list(config.supported_forecast_horizons_hours),
        "minimum_matured_sample_count": config.minimum_matured_sample_count,
        "evidence_z_threshold": config.evidence_z_threshold,
        "weight_lower_bound": config.weight_lower_bound,
        "weight_upper_bound": config.weight_upper_bound,
    }


def _config_from_dict(payload: Mapping[str, object]) -> PhysicalOnlineExpertBlendConfig:
    _strict_keys(
        payload,
        {
            "supported_forecast_horizons_hours",
            "minimum_matured_sample_count",
            "evidence_z_threshold",
            "weight_lower_bound",
            "weight_upper_bound",
        },
        "prospective_online_expert_pair_config_invalid",
    )
    horizons = payload["supported_forecast_horizons_hours"]
    if not isinstance(horizons, list):
        raise ValueError("prospective_online_expert_pair_config_invalid")
    try:
        return PhysicalOnlineExpertBlendConfig(
            supported_forecast_horizons_hours=tuple(horizons),  # type: ignore[arg-type]
            minimum_matured_sample_count=payload["minimum_matured_sample_count"],  # type: ignore[arg-type]
            evidence_z_threshold=float(payload["evidence_z_threshold"]),
            weight_lower_bound=float(payload["weight_lower_bound"]),
            weight_upper_bound=float(payload["weight_upper_bound"]),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("prospective_online_expert_pair_config_invalid") from exc
