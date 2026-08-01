"""Causal prospective runtime for the physical-first WWM candidate."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from data_agent.uwm.geospatial_kernel_v2.physical_online_residual_adaptation import (
    PhysicalOnlineResidualAdaptationConfig,
    PhysicalOnlineResidualAdaptationState,
    PhysicalOnlineResidualAdaptationStep,
    PhysicalOnlineResidualAdapter,
)
from data_agent.uwm.geospatial_kernel_v2.prospective_online_expert_pair import (
    ProspectiveOnlineExpertMaturedFeedback,
    ProspectiveOnlineExpertPairRunner,
    ProspectiveOnlineExpertPairState,
    ProspectiveOnlineExpertPairStep,
    advance_prospective_online_expert_pair_state,
)

PROSPECTIVE_WWM_CANDIDATE_STATE_SCHEMA = (
    "gwm.geospatial_kernel.prospective_wwm_candidate_state.v1"
)
PROSPECTIVE_WWM_CANDIDATE_PREDICTION_SCHEMA = (
    "gwm.geospatial_kernel.prospective_wwm_candidate_prediction.v1"
)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("prospective_wwm_candidate_datetime_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("prospective_wwm_candidate_datetime_invalid") from exc
    if not _aware(parsed):
        raise ValueError("prospective_wwm_candidate_datetime_invalid")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ProspectiveWwmCandidateState:
    """Synchronized v4-learning and v5-comparison state for one system."""

    physical_residual_state: PhysicalOnlineResidualAdaptationState
    expert_pair_state: ProspectiveOnlineExpertPairState

    def __post_init__(self) -> None:
        if (
            not isinstance(
                self.physical_residual_state,
                PhysicalOnlineResidualAdaptationState,
            )
            or not isinstance(
                self.expert_pair_state,
                ProspectiveOnlineExpertPairState,
            )
            or self.physical_residual_state.system_id
            != self.expert_pair_state.system_id
            or self.physical_residual_state.state_as_of
            != self.expert_pair_state.state_as_of
            or self.physical_residual_state.config.supported_forecast_horizons_hours
            != self.expert_pair_state.config.supported_forecast_horizons_hours
        ):
            raise ValueError("prospective_wwm_candidate_state_invalid")

    @property
    def system_id(self) -> str:
        return self.physical_residual_state.system_id

    @property
    def state_as_of(self) -> datetime:
        return self.physical_residual_state.state_as_of

    @classmethod
    def empty(
        cls,
        *,
        system_id: str,
        state_as_of: datetime,
    ) -> ProspectiveWwmCandidateState:
        return cls(
            physical_residual_state=(
                PhysicalOnlineResidualAdaptationState.empty(
                    system_id=system_id,
                    state_as_of=state_as_of,
                )
            ),
            expert_pair_state=ProspectiveOnlineExpertPairState.empty(
                system_id=system_id,
                state_as_of=state_as_of,
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": PROSPECTIVE_WWM_CANDIDATE_STATE_SCHEMA,
            "system_id": self.system_id,
            "state_as_of_utc": _iso(self.state_as_of),
            "physical_online_residual_adaptation_v4_state": (
                self.physical_residual_state.as_dict()
            ),
            "online_expert_pair_state": self.expert_pair_state.as_dict(),
            "raw_observations_included": False,
            "current_or_future_target_information_included": False,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> ProspectiveWwmCandidateState:
        if set(payload) != {
            "schema",
            "system_id",
            "state_as_of_utc",
            "physical_online_residual_adaptation_v4_state",
            "online_expert_pair_state",
            "raw_observations_included",
            "current_or_future_target_information_included",
        } or (
            payload.get("schema") != PROSPECTIVE_WWM_CANDIDATE_STATE_SCHEMA
            or payload.get("raw_observations_included") is not False
            or payload.get("current_or_future_target_information_included") is not False
            or not isinstance(
                payload.get("physical_online_residual_adaptation_v4_state"),
                Mapping,
            )
            or not isinstance(payload.get("online_expert_pair_state"), Mapping)
        ):
            raise ValueError("prospective_wwm_candidate_state_invalid")
        state = cls(
            physical_residual_state=(
                PhysicalOnlineResidualAdaptationState.from_dict(
                    payload["physical_online_residual_adaptation_v4_state"]
                )
            ),
            expert_pair_state=ProspectiveOnlineExpertPairState.from_dict(
                payload["online_expert_pair_state"]
            ),
        )
        if (
            payload.get("system_id") != state.system_id
            or _parse_datetime(payload.get("state_as_of_utc")) != state.state_as_of
        ):
            raise ValueError("prospective_wwm_candidate_state_invalid")
        return state


@dataclass(frozen=True)
class ProspectiveWwmCandidatePrediction:
    """One sealed forecast with sufficient fields for later causal updates."""

    forecast_id: str
    target_support_end: datetime
    v4_step: PhysicalOnlineResidualAdaptationStep
    expert_pair_step: ProspectiveOnlineExpertPairStep

    def __post_init__(self) -> None:
        if (
            not isinstance(self.forecast_id, str)
            or not self.forecast_id.strip()
            or not _aware(self.target_support_end)
            or not isinstance(
                self.v4_step,
                PhysicalOnlineResidualAdaptationStep,
            )
            or not isinstance(
                self.expert_pair_step,
                ProspectiveOnlineExpertPairStep,
            )
            or self.v4_step.forecast_horizon_hours
            != self.expert_pair_step.forecast_horizon_hours
            or self.target_support_end
            != self.expert_pair_step.issue_time
            + timedelta(hours=self.v4_step.forecast_horizon_hours)
            or self.v4_step.corrected_prediction_m3s
            != self.expert_pair_step.primary_candidate.baseline_prediction_m3s
        ):
            raise ValueError("prospective_wwm_candidate_prediction_invalid")

    def as_dict(self) -> dict[str, object]:
        pair = self.expert_pair_step.as_dict()
        pair.pop("schema")
        step = self.v4_step
        return {
            "schema": PROSPECTIVE_WWM_CANDIDATE_PREDICTION_SCHEMA,
            "forecast_id": self.forecast_id,
            "target_support_end_utc": _iso(self.target_support_end),
            **pair,
            "physical_open_loop_m3s": step.physical_target_m3s,
            "physical_at_latest_observation_m3s": (
                step.physical_at_latest_observation_m3s
            ),
            "v4_predictor_forecast_horizon_hours": (
                step.predictor_forecast_horizon_hours
            ),
            "v4_predictor_physical_target_m3s": (
                step.predictor_physical_target_m3s
            ),
            "v4_physical_trajectory_change_m3s": (
                step.physical_trajectory_change_m3s
            ),
            "v4_correction_mode": step.correction_mode,
            "v4_evidence_gate_passed": step.evidence_gate_passed,
            "v4_shadow_performance_gate_passed": (
                step.shadow_performance_gate_passed
            ),
            "v4_application_gate_passed": step.application_gate_passed,
            "v4_shadow_prediction_m3s": step.shadow_prediction_m3s,
            "v4_applied_weight": step.applied_weight,
            "v4_applied_bias_m3s": step.applied_bias_m3s,
            "v4_state_generated_at_issue_time": True,
        }


class ProspectiveWwmCandidateRunner:
    """Generate v4, v5, and the traditional selector from one causal state."""

    def __init__(self, state: ProspectiveWwmCandidateState) -> None:
        if not isinstance(state, ProspectiveWwmCandidateState):
            raise TypeError("prospective_wwm_candidate_state_required")
        self.state = state

    def predict_issue(
        self,
        *,
        issue_time: datetime,
        physical_at_latest_observation_m3s: float,
        physical_predictions_by_horizon: Mapping[int, float],
        action_innovation_predictions_by_horizon: Mapping[int, float],
        forecast_id_prefix: str,
    ) -> tuple[ProspectiveWwmCandidatePrediction, ...]:
        if (
            not _aware(issue_time)
            or issue_time < self.state.state_as_of
            or not isinstance(forecast_id_prefix, str)
            or not forecast_id_prefix.strip()
            or isinstance(physical_at_latest_observation_m3s, bool)
            or not math.isfinite(float(physical_at_latest_observation_m3s))
            or float(physical_at_latest_observation_m3s) < 0.0
        ):
            raise ValueError("prospective_wwm_candidate_issue_invalid")
        horizons = self.state.physical_residual_state.config.supported_forecast_horizons_hours
        if (
            set(physical_predictions_by_horizon) != set(horizons)
            or set(action_innovation_predictions_by_horizon) != set(horizons)
        ):
            raise ValueError("prospective_wwm_candidate_horizon_axis_invalid")
        physical = _finite_nonnegative_horizon_values(
            physical_predictions_by_horizon,
            horizons,
        )
        action = _finite_nonnegative_horizon_values(
            action_innovation_predictions_by_horizon,
            horizons,
        )
        residual_adapter = PhysicalOnlineResidualAdapter.from_state(
            self.state.physical_residual_state
        )
        pair_runner = ProspectiveOnlineExpertPairRunner(self.state.expert_pair_state)
        predictor_by_target = dict(
            self.state.physical_residual_state.config.trajectory_predictor_horizon_pairs
        )
        predictions = []
        for horizon in horizons:
            predictor_horizon = predictor_by_target.get(horizon)
            v4_step = residual_adapter.predict(
                forecast_horizon_hours=horizon,
                physical_at_latest_observation_m3s=float(
                    physical_at_latest_observation_m3s
                ),
                predictor_physical_target_m3s=(
                    physical[predictor_horizon]
                    if predictor_horizon is not None
                    else None
                ),
                physical_target_m3s=physical[horizon],
                issue_time=issue_time,
            )
            pair_step = pair_runner.predict(
                forecast_horizon_hours=horizon,
                baseline_prediction_m3s=v4_step.corrected_prediction_m3s,
                alternative_prediction_m3s=action[horizon],
                issue_time=issue_time,
            )
            predictions.append(
                ProspectiveWwmCandidatePrediction(
                    forecast_id=f"{forecast_id_prefix}:{horizon}h",
                    target_support_end=(
                        issue_time.astimezone(UTC) + timedelta(hours=horizon)
                    ),
                    v4_step=v4_step,
                    expert_pair_step=pair_step,
                )
            )
        return tuple(predictions)


@dataclass(frozen=True)
class ProspectiveWwmMaturedFeedback:
    """Transient authoritative outcome joined to one sealed prediction."""

    prediction: ProspectiveWwmCandidatePrediction
    observed_discharge_m3s: float
    observation_available_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.prediction, ProspectiveWwmCandidatePrediction)
            or isinstance(self.observed_discharge_m3s, bool)
            or not math.isfinite(float(self.observed_discharge_m3s))
            or not _aware(self.observation_available_at)
            or self.observation_available_at < self.prediction.target_support_end
        ):
            raise ValueError("prospective_wwm_candidate_feedback_invalid")


def advance_prospective_wwm_candidate_state(
    state: ProspectiveWwmCandidateState,
    feedbacks: tuple[ProspectiveWwmMaturedFeedback, ...],
    *,
    update_time: datetime,
) -> ProspectiveWwmCandidateState:
    """Advance both learning layers from the same newly matured outcomes."""

    if (
        not isinstance(state, ProspectiveWwmCandidateState)
        or not feedbacks
        or any(
            not isinstance(value, ProspectiveWwmMaturedFeedback)
            for value in feedbacks
        )
        or not _aware(update_time)
        or update_time < state.state_as_of
    ):
        raise ValueError("prospective_wwm_candidate_state_update_invalid")
    ordered = tuple(
        sorted(
            feedbacks,
            key=lambda value: (
                value.observation_available_at,
                value.prediction.forecast_id,
            ),
        )
    )
    if any(value.observation_available_at > update_time for value in ordered):
        raise ValueError("prospective_wwm_candidate_state_update_invalid")
    residual_adapter = PhysicalOnlineResidualAdapter.from_state(
        state.physical_residual_state
    )
    pair_feedbacks = []
    for feedback in ordered:
        prediction = feedback.prediction
        v4 = prediction.v4_step
        pair = prediction.expert_pair_step
        if pair.system_id != state.system_id:
            raise ValueError("prospective_wwm_candidate_state_update_invalid")
        residual_adapter.update(
            sample_id=prediction.forecast_id,
            forecast_horizon_hours=v4.forecast_horizon_hours,
            physical_trajectory_change_m3s=(
                v4.physical_trajectory_change_m3s or 0.0
            ),
            physical_target_m3s=v4.physical_target_m3s,
            candidate_shadow_prediction_m3s=v4.shadow_prediction_m3s,
            candidate_evidence_gate_passed=v4.evidence_gate_passed,
            observed_target_m3s=feedback.observed_discharge_m3s,
            target_observation_available_at=feedback.observation_available_at,
            update_time=update_time,
        )
        candidate = pair.primary_candidate
        pair_feedbacks.append(
            ProspectiveOnlineExpertMaturedFeedback(
                sample_id=prediction.forecast_id,
                forecast_horizon_hours=v4.forecast_horizon_hours,
                target_support_end=prediction.target_support_end,
                observed_discharge_m3s=feedback.observed_discharge_m3s,
                observation_available_at=feedback.observation_available_at,
                baseline_prediction_m3s=(candidate.baseline_prediction_m3s),
                alternative_prediction_m3s=(candidate.alternative_prediction_m3s),
                coefficient_gate_shadow_prediction_m3s=(
                    candidate.shadow_prediction_m3s
                ),
                coefficient_gate_passed=candidate.evidence_gate_passed,
            )
        )
    residual_state = residual_adapter.export_state(
        system_id=state.system_id,
        state_as_of=update_time,
    )
    pair_state = advance_prospective_online_expert_pair_state(
        state.expert_pair_state,
        tuple(pair_feedbacks),
        update_time=update_time,
    )
    return ProspectiveWwmCandidateState(
        physical_residual_state=residual_state,
        expert_pair_state=pair_state,
    )


def algorithm_contract() -> dict[str, object]:
    """Describe the fixed candidate chain without making an admission claim."""

    return {
        "candidate": "physical_first_online_wwm_v1",
        "prediction_chain": [
            "physical_open_loop",
            "physical_online_residual_adaptation_v4",
            "physical_online_expert_blend_v5",
        ],
        "traditional_baseline": "evidence_gated_follow_the_leader",
        "v4_config": PhysicalOnlineResidualAdaptationConfig().as_dict(),
        "v4_generated_from_matured_state_at_issue_time": True,
        "precomputed_v4_prediction_accepted": False,
        "prediction_api_accepts_observation_or_outcome": False,
        "one_independent_state_per_system_and_horizon": True,
        "candidate_admitted": False,
        "runtime_default_enabled": False,
    }


def _finite_nonnegative_horizon_values(
    values: Mapping[int, float],
    horizons: tuple[int, ...],
) -> dict[int, float]:
    parsed = {}
    for horizon in horizons:
        raw = values[horizon]
        if (
            isinstance(raw, bool)
            or not math.isfinite(float(raw))
            or float(raw) < 0.0
        ):
            raise ValueError("prospective_wwm_candidate_forecast_invalid")
        parsed[horizon] = float(raw)
    return parsed
