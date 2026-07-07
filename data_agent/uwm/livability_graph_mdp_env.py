"""Real-data Graph-MDP environment for UWM livability RL training."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .model_based_rl import build_graph_mdp_state
from .simulator import simulate_livability_rollout


LIVABILITY_GRAPH_MDP_ENV_SCHEMA = "uwm.livability_graph_mdp_env.v1"


@dataclass(frozen=True)
class LivabilityGraphMDPConfig:
    action_types: list[str]
    scenario: dict[str, Any]
    horizon: int
    thresholds: dict[str, float]


class LivabilityGraphMDPEnv:
    """Small deterministic Graph-MDP wrapper over the UWM livability simulator."""

    def __init__(
        self,
        observation: dict[str, Any],
        *,
        action_types: list[str],
        scenario: dict[str, Any],
        horizon: int,
        thresholds: dict[str, float] | None = None,
        mechanism_table: dict[str, Any] | None = None,
        spatial_spillover_kernel: dict[str, Any] | None = None,
        air_quality_uncertainty_context: dict[str, Any] | None = None,
    ) -> None:
        if horizon <= 0:
            raise ValueError("horizon must be positive")
        self.observation = observation
        self.config = LivabilityGraphMDPConfig(
            action_types=list(action_types),
            scenario=dict(scenario),
            horizon=int(horizon),
            thresholds=dict(thresholds or {}),
        )
        self.mechanism_table = mechanism_table
        self.spatial_spillover_kernel = spatial_spillover_kernel
        self.air_quality_uncertainty_context = air_quality_uncertainty_context
        self.graph_state = build_graph_mdp_state(
            observation,
            action_types=self.config.action_types,
            thresholds=self.config.thresholds,
        )
        self.available_actions = [
            dict(action) for action in self.graph_state.get("available_actions") or []
        ]
        if not self.available_actions:
            raise ValueError("livability Graph-MDP environment requires at least one available action")
        self._rollout_cache: dict[tuple[int, ...], dict[str, Any]] = {}
        self.metadata = self._metadata()
        self.reset()

    def reset(self) -> dict[str, Any]:
        self._selected_indices: list[int] = []
        self._used_indices: set[int] = set()
        self._step_index = 0
        self._last_score = 0.0
        self._last_rollout: dict[str, Any] | None = None
        return self._public_observation()

    def state_key(self) -> tuple[int, tuple[int, ...]]:
        return (self._step_index, tuple(self._selected_indices))

    def valid_action_indices(self) -> list[int]:
        if self._step_index >= self.config.horizon:
            return []
        return [
            index
            for index in range(len(self.available_actions))
            if index not in self._used_indices
        ]

    def action_mask(self) -> list[int]:
        valid = set(self.valid_action_indices())
        return [1 if index in valid else 0 for index in range(len(self.available_actions))]

    def step(self, action_index: int) -> dict[str, Any]:
        if action_index not in self.valid_action_indices():
            raise ValueError(f"action_index {action_index} is not valid for current state")

        previous_score = self._last_score
        self._selected_indices.append(int(action_index))
        self._used_indices.add(int(action_index))
        self._step_index += 1

        rollout = self._simulate_selected_sequence()
        score, components = self._risk_adjusted_score(rollout)
        reward = score - previous_score
        self._last_score = score
        self._last_rollout = rollout
        done = self._step_index >= self.config.horizon or not self.valid_action_indices()
        transition = self._transition(action_index, rollout, reward, score, components, done)
        return {
            "state": self._state(),
            "action_mask": self.action_mask(),
            "reward": round(reward, 9),
            "done": done,
            "transition": transition,
        }

    def action_sequence(self) -> list[dict[str, Any]]:
        return [dict(self.available_actions[index]) for index in self._selected_indices]

    def cumulative_reward(self) -> float:
        return round(self._last_score, 9)

    def last_rollout(self) -> dict[str, Any] | None:
        return self._last_rollout

    def _public_observation(self) -> dict[str, Any]:
        return {
            "schema": LIVABILITY_GRAPH_MDP_ENV_SCHEMA,
            "metadata": self.metadata,
            "state": self._state(),
            "action_mask": self.action_mask(),
        }

    def _state(self) -> dict[str, Any]:
        aggregates = self._aggregate_node_features()
        return {
            "step_index": self._step_index,
            "remaining_horizon": max(0, self.config.horizon - self._step_index),
            "selected_action_indices": list(self._selected_indices),
            "selected_action_count": len(self._selected_indices),
            "cumulative_reward": round(self._last_score, 9),
            "graph_aggregate_features": aggregates,
            "state_vector": [
                float(self._step_index) / max(1.0, float(self.config.horizon)),
                float(self.config.horizon - self._step_index) / max(1.0, float(self.config.horizon)),
                aggregates["mean_heat_risk"],
                aggregates["mean_air_pollution_exposure"],
                aggregates["mean_service_accessibility"],
                aggregates["mean_equity"],
                aggregates["mean_livability"],
                float(len(self.valid_action_indices())) / max(1.0, float(len(self.available_actions))),
            ],
        }

    def _metadata(self) -> dict[str, Any]:
        spatial_summary = (self.spatial_spillover_kernel or {}).get("summary") or {}
        return {
            "schema": LIVABILITY_GRAPH_MDP_ENV_SCHEMA,
            "environment_backend": "real_data_uwm_livability_graph_mdp_env_v1",
            "source_observation_id": self.observation.get("observation_id"),
            "scenario_id": self.config.scenario.get("scenario_id"),
            "horizon": self.config.horizon,
            "real_data_sources": {
                "admin_unit_count": len(self.graph_state.get("nodes") or []),
                "admin_spatial_edge_count": len(self.graph_state.get("edges") or []),
                "available_action_count": len(self.available_actions),
                "mechanism_table_id": (self.mechanism_table or {}).get("table_id"),
                "spatial_spillover_kernel_id": (self.spatial_spillover_kernel or {}).get("kernel_id"),
                "spatial_spillover_directional_edge_count": _int(
                    spatial_summary.get("directional_edge_count")
                ),
                "air_quality_holdout_id": (self.air_quality_uncertainty_context or {}).get("benchmark_id"),
            },
            "observed_policy_outcome_superiority_claim": False,
            "empirical_superiority_claim": False,
        }

    def _simulate_selected_sequence(self) -> dict[str, Any]:
        key = tuple(self._selected_indices)
        cached = self._rollout_cache.get(key)
        if cached is not None:
            return cached
        actions = [self.available_actions[index] for index in key]
        rollout = simulate_livability_rollout(
            self.observation,
            actions,
            scenario=self.config.scenario,
            mechanism_table=self.mechanism_table,
            spatial_spillover_kernel=self.spatial_spillover_kernel,
        )
        self._rollout_cache[key] = rollout
        return rollout

    def _risk_adjusted_score(self, rollout: dict[str, Any]) -> tuple[float, dict[str, float]]:
        interval = rollout.get("uncertainty_interval") or {}
        interval_width = _float(interval.get("high")) - _float(interval.get("low"))
        livability_delta = _float(rollout.get("livability_delta"))
        equity_delta = _float(rollout.get("equity_delta"))
        uncertainty_penalty = self._air_quality_uncertainty_penalty(rollout)
        score = livability_delta + 0.50 * equity_delta - 0.10 * interval_width - uncertainty_penalty
        return (
            float(score),
            {
                "livability_delta": round(livability_delta, 9),
                "equity_delta": round(equity_delta, 9),
                "air_pollution_exposure_delta": round(
                    _float(rollout.get("air_pollution_exposure_delta")),
                    9,
                ),
                "heat_risk_delta": round(_float(rollout.get("heat_risk_delta")), 9),
                "service_accessibility_delta": round(
                    _float(rollout.get("service_accessibility_delta")),
                    9,
                ),
                "uncertainty_interval_width": round(interval_width, 9),
                "uncertainty_penalty": round(uncertainty_penalty, 9),
                "risk_adjusted_score": round(score, 9),
            },
        )

    def _air_quality_uncertainty_penalty(self, rollout: dict[str, Any]) -> float:
        context = self.air_quality_uncertainty_context or {}
        calibration = context.get("uncertainty_calibration") or context
        interval_score = _float(calibration.get("uwm_interval_score"))
        pm25_values = _scene_pm25_values(context)
        pm25_range = max(pm25_values) - min(pm25_values) if pm25_values else 0.0
        if interval_score <= 0.0 or pm25_range <= 0.0:
            return 0.0
        air_dependency = 0.25 * abs(_float(rollout.get("air_pollution_exposure_delta")))
        return air_dependency * (interval_score / pm25_range)

    def _transition(
        self,
        action_index: int,
        rollout: dict[str, Any],
        reward: float,
        score: float,
        components: dict[str, float],
        done: bool,
    ) -> dict[str, Any]:
        trace = rollout.get("simulator_trace") or []
        mechanism_sources = sorted(
            {
                str(step.get("mechanism_source"))
                for step in trace
                if step.get("mechanism_source")
            }
        )
        return {
            "state_key": self.state_key(),
            "action_index": int(action_index),
            "action": dict(self.available_actions[action_index]),
            "reward": round(reward, 9),
            "done": done,
            "cumulative_reward": round(score, 9),
            "reward_components": components,
            "future_state_delta": rollout.get("future_state_delta"),
            "simulator_trace_steps": [str(step.get("step")) for step in trace],
            "simulator_mechanism_sources": mechanism_sources,
            "claim_boundary": rollout.get("claim_boundary"),
        }

    def _aggregate_node_features(self) -> dict[str, float]:
        totals = {
            "heat_risk": 0.0,
            "air_pollution_exposure": 0.0,
            "service_accessibility": 0.0,
            "equity": 0.0,
            "livability": 0.0,
        }
        nodes = self.graph_state.get("nodes") or []
        for node in nodes:
            features = node.get("features") or {}
            for key in totals:
                totals[key] += _float(features.get(key))
        count = max(1, len(nodes))
        return {
            "mean_heat_risk": round(totals["heat_risk"] / count, 9),
            "mean_air_pollution_exposure": round(totals["air_pollution_exposure"] / count, 9),
            "mean_service_accessibility": round(totals["service_accessibility"] / count, 9),
            "mean_equity": round(totals["equity"] / count, 9),
            "mean_livability": round(totals["livability"] / count, 9),
        }


def build_livability_graph_mdp_env(
    observation: dict[str, Any],
    *,
    action_types: list[str],
    scenario: dict[str, Any],
    horizon: int = 2,
    thresholds: dict[str, float] | None = None,
    mechanism_table: dict[str, Any] | None = None,
    spatial_spillover_kernel: dict[str, Any] | None = None,
    air_quality_uncertainty_context: dict[str, Any] | None = None,
) -> LivabilityGraphMDPEnv:
    return LivabilityGraphMDPEnv(
        observation,
        action_types=action_types,
        scenario=scenario,
        horizon=horizon,
        thresholds=thresholds,
        mechanism_table=mechanism_table,
        spatial_spillover_kernel=spatial_spillover_kernel,
        air_quality_uncertainty_context=air_quality_uncertainty_context,
    )


def _scene_pm25_values(context: dict[str, Any]) -> list[float]:
    values: list[float] = []
    for series in context.get("series_results") or []:
        if not isinstance(series, dict):
            continue
        for record in series.get("daily_pm25") or []:
            if isinstance(record, dict):
                values.append(_float(record.get("pm25_ugm3")))
    return values


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    if value in {None, ""}:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default
