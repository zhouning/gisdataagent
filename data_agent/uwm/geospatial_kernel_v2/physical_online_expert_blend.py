"""Causal online blending between a physical-first baseline and one expert."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

PHYSICAL_ONLINE_EXPERT_BLEND_SCHEMA = "gwm.geospatial_kernel.physical_online_expert_blend.v1"
PHYSICAL_ONLINE_EXPERT_BLEND_FORMULA = (
    "max(0, baseline + admitted_weight_h * (alternative - baseline))"
)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True)
class PhysicalOnlineExpertBlendConfig:
    """Fixed causal controls shared by every system and evaluation window."""

    supported_forecast_horizons_hours: tuple[int, ...] = (1, 3, 6, 12)
    minimum_matured_sample_count: int = 24
    evidence_z_threshold: float = 1.96
    weight_lower_bound: float = 0.0
    weight_upper_bound: float = 1.0

    def __post_init__(self) -> None:
        horizons = self.supported_forecast_horizons_hours
        if (
            not horizons
            or tuple(sorted(set(horizons))) != horizons
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
                for value in horizons
            )
            or not isinstance(self.minimum_matured_sample_count, int)
            or isinstance(self.minimum_matured_sample_count, bool)
            or self.minimum_matured_sample_count < 2
            or not math.isfinite(float(self.evidence_z_threshold))
            or self.evidence_z_threshold <= 0.0
            or not math.isfinite(float(self.weight_lower_bound))
            or not math.isfinite(float(self.weight_upper_bound))
            or self.weight_lower_bound < 0.0
            or self.weight_upper_bound > 1.0
            or self.weight_lower_bound >= self.weight_upper_bound
        ):
            raise ValueError("physical_online_expert_blend_config_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": PHYSICAL_ONLINE_EXPERT_BLEND_SCHEMA,
            "formula": PHYSICAL_ONLINE_EXPERT_BLEND_FORMULA,
            "estimator": "expanding_horizon_specialized_zero_intercept_error_regression",
            "baseline_expert": "physical_online_residual_adaptation_v4",
            "alternative_expert": "action_innovation_wwm",
            "supported_forecast_horizons_hours": list(self.supported_forecast_horizons_hours),
            "minimum_matured_sample_count": self.minimum_matured_sample_count,
            "evidence_z_threshold": self.evidence_z_threshold,
            "weight_lower_bound": self.weight_lower_bound,
            "weight_upper_bound": self.weight_upper_bound,
            "target_outcome_used_before_declared_availability": False,
            "finite_signed_observed_target_supported": True,
            "insufficient_evidence_fallback": "physical_first_baseline",
            "cross_system_parameter_transfer_required": False,
            "statistical_coverage_guarantee_claimed": False,
            "admitted": False,
        }


@dataclass(frozen=True)
class PhysicalOnlineExpertBlendStep:
    forecast_horizon_hours: int
    baseline_prediction_m3s: float
    alternative_prediction_m3s: float
    alternative_delta_m3s: float
    matured_sample_count: int
    raw_weight: float
    weight_standard_error: float | None
    evidence_threshold: float | None
    evidence_gate_passed: bool
    shadow_validation_sample_count: int
    shadow_rmse_m3s: float | None
    baseline_rmse_m3s: float | None
    shadow_mean_squared_error_improvement_m6s2: float | None
    shadow_improvement_standard_error_m6s2: float | None
    shadow_improvement_threshold_m6s2: float | None
    shadow_performance_gate_passed: bool
    shadow_weight: float
    shadow_prediction_m3s: float
    application_gate_passed: bool
    applied_weight: float
    unbounded_prediction_m3s: float
    blended_prediction_m3s: float
    clipped: bool


class PhysicalOnlineExpertBlender:
    """Admit an alternative expert only after causal paired-loss evidence."""

    def __init__(
        self,
        config: PhysicalOnlineExpertBlendConfig | None = None,
    ) -> None:
        self.config = config or PhysicalOnlineExpertBlendConfig()
        self._samples: dict[int, list[tuple[float, float]]] = {
            horizon: [] for horizon in self.config.supported_forecast_horizons_hours
        }
        self._shadow_squared_errors: dict[int, list[tuple[float, float]]] = {
            horizon: [] for horizon in self.config.supported_forecast_horizons_hours
        }
        self._sample_ids: set[str] = set()
        self._latest_update_time: datetime | None = None

    def update(
        self,
        *,
        sample_id: str,
        forecast_horizon_hours: int,
        baseline_prediction_m3s: float,
        alternative_prediction_m3s: float,
        candidate_shadow_prediction_m3s: float,
        candidate_evidence_gate_passed: bool,
        observed_target_m3s: float,
        target_observation_available_at: datetime,
        update_time: datetime,
    ) -> None:
        """Reveal one matured paired expert outcome; reject future outcomes."""

        if (
            not isinstance(sample_id, str)
            or not sample_id.strip()
            or sample_id in self._sample_ids
            or forecast_horizon_hours not in self._samples
            or not isinstance(candidate_evidence_gate_passed, bool)
            or not _aware(target_observation_available_at)
            or not _aware(update_time)
            or target_observation_available_at > update_time
            or (self._latest_update_time is not None and update_time < self._latest_update_time)
        ):
            raise ValueError("physical_online_expert_blend_update_invalid")
        values = (
            baseline_prediction_m3s,
            alternative_prediction_m3s,
            candidate_shadow_prediction_m3s,
            observed_target_m3s,
        )
        if (
            any(not math.isfinite(float(value)) for value in values)
            or float(baseline_prediction_m3s) < 0.0
            or float(alternative_prediction_m3s) < 0.0
            or float(candidate_shadow_prediction_m3s) < 0.0
        ):
            raise ValueError("physical_online_expert_blend_update_invalid")
        baseline = float(baseline_prediction_m3s)
        alternative_delta = float(alternative_prediction_m3s) - baseline
        target_error = float(observed_target_m3s) - baseline
        self._samples[forecast_horizon_hours].append((alternative_delta, target_error))
        self._sample_ids.add(sample_id)
        self._latest_update_time = update_time
        if candidate_evidence_gate_passed:
            shadow_error = float(observed_target_m3s) - float(candidate_shadow_prediction_m3s)
            self._shadow_squared_errors[forecast_horizon_hours].append(
                (shadow_error**2, target_error**2)
            )

    def predict(
        self,
        *,
        forecast_horizon_hours: int,
        baseline_prediction_m3s: float,
        alternative_prediction_m3s: float,
        issue_time: datetime,
    ) -> PhysicalOnlineExpertBlendStep:
        """Blend only when coefficient and shadow performance gates pass."""

        if (
            forecast_horizon_hours not in self._samples
            or not _aware(issue_time)
            or (self._latest_update_time is not None and issue_time < self._latest_update_time)
            or not math.isfinite(float(baseline_prediction_m3s))
            or not math.isfinite(float(alternative_prediction_m3s))
            or baseline_prediction_m3s < 0.0
            or alternative_prediction_m3s < 0.0
        ):
            raise ValueError("physical_online_expert_blend_forecast_invalid")
        baseline = float(baseline_prediction_m3s)
        alternative_delta = float(alternative_prediction_m3s) - baseline
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
        evidence_gate_passed = (
            sample_count >= self.config.minimum_matured_sample_count
            and evidence_threshold is not None
            and raw_weight > evidence_threshold
        )
        shadow_weight = (
            min(
                self.config.weight_upper_bound,
                max(self.config.weight_lower_bound, raw_weight),
            )
            if evidence_gate_passed
            else 0.0
        )
        shadow_prediction = max(
            0.0,
            baseline + shadow_weight * alternative_delta,
        )
        shadow_errors = self._shadow_squared_errors[forecast_horizon_hours]
        shadow_count = len(shadow_errors)
        shadow_rmse = (
            math.sqrt(sum(value[0] for value in shadow_errors) / shadow_count)
            if shadow_count
            else None
        )
        baseline_rmse = (
            math.sqrt(sum(value[1] for value in shadow_errors) / shadow_count)
            if shadow_count
            else None
        )
        improvements = [baseline_error - shadow for shadow, baseline_error in shadow_errors]
        mean_improvement = sum(improvements) / shadow_count if shadow_count else None
        improvement_standard_error: float | None = None
        improvement_threshold: float | None = None
        if shadow_count >= 2 and mean_improvement is not None:
            improvement_variance = sum(
                (value - mean_improvement) ** 2 for value in improvements
            ) / (shadow_count - 1)
            improvement_standard_error = math.sqrt(max(0.0, improvement_variance) / shadow_count)
            improvement_threshold = self.config.evidence_z_threshold * improvement_standard_error
        performance_gate_passed = (
            shadow_count >= self.config.minimum_matured_sample_count
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
            alternative_prediction_m3s=float(alternative_prediction_m3s),
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
            shadow_improvement_standard_error_m6s2=(improvement_standard_error),
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

    def sample_count_by_horizon(self) -> dict[int, int]:
        return {horizon: len(samples) for horizon, samples in self._samples.items()}
