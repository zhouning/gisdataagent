"""Model-based RL training evidence for UWM livability Graph-MDP."""

from __future__ import annotations

import random
from typing import Any

from .livability_graph_mdp_env import LivabilityGraphMDPEnv


UWM_LIVABILITY_RL_TRAINING_REPORT_SCHEMA = "uwm.livability_rl_training_report.v1"


def train_livability_model_based_q_agent(
    env: LivabilityGraphMDPEnv,
    *,
    report_id: str,
    created_at: str,
    episodes: int = 160,
    seed: int = 20260707,
    learning_rate: float = 0.35,
    discount_factor: float = 0.9,
    epsilon_start: float = 0.75,
    epsilon_end: float = 0.05,
    planning_updates_per_step: int = 8,
    final_model_backup_sweeps: int = 2,
) -> dict[str, Any]:
    """Train a tabular Dyna-Q agent against the real-data UWM simulator env."""

    if episodes <= 0:
        raise ValueError("episodes must be positive")
    if not 0.0 <= epsilon_end <= epsilon_start <= 1.0:
        raise ValueError("epsilon values must satisfy 0 <= end <= start <= 1")
    if planning_updates_per_step < 0:
        raise ValueError("planning_updates_per_step must be non-negative")

    rng = random.Random(seed)
    q_values: dict[tuple[int, tuple[int, ...]], dict[int, float]] = {}
    replay_model: dict[tuple[tuple[int, tuple[int, ...]], int], dict[str, Any]] = {}
    episode_rewards: list[float] = []
    episode_lengths: list[int] = []
    planning_update_count = 0

    for episode_index in range(episodes):
        env.reset()
        done = False
        total_reward = 0.0
        step_count = 0
        epsilon = _linear_epsilon(
            episode_index,
            total_episodes=episodes,
            epsilon_start=epsilon_start,
            epsilon_end=epsilon_end,
        )
        while not done:
            state_key = env.state_key()
            valid_actions = env.valid_action_indices()
            action_index = _select_epsilon_greedy_action(
                q_values,
                state_key,
                valid_actions,
                epsilon=epsilon,
                rng=rng,
            )
            result = env.step(action_index)
            next_state_key = env.state_key()
            reward = float(result["reward"])
            done = bool(result["done"])
            total_reward += reward
            step_count += 1

            _q_update(
                q_values,
                state_key,
                action_index,
                reward,
                next_state_key,
                done=done,
                next_valid_actions=env.valid_action_indices(),
                learning_rate=learning_rate,
                discount_factor=discount_factor,
            )
            replay_model[(state_key, action_index)] = {
                "reward": reward,
                "next_state_key": next_state_key,
                "done": done,
                "next_valid_actions": list(env.valid_action_indices()),
                "transition": result["transition"],
            }
            planning_update_count += _planning_updates(
                q_values,
                replay_model,
                rng=rng,
                update_count=planning_updates_per_step,
                learning_rate=learning_rate,
                discount_factor=discount_factor,
            )

        episode_rewards.append(round(total_reward, 9))
        episode_lengths.append(step_count)

    model_backup_count = _final_model_backups(
        env,
        q_values,
        sweeps=final_model_backup_sweeps,
        discount_factor=discount_factor,
    )
    learned_policy = _evaluate_greedy_policy(env, q_values)
    static_baseline = _evaluate_traditional_static_baseline(env)
    first_20_mean = _mean(episode_rewards[:20])
    last_20_mean = _mean(episode_rewards[-20:])
    advantage = learned_policy["cumulative_reward"] - static_baseline["cumulative_reward"]
    supported_claim = (
        "trained_model_based_q_agent_improves_same_scene_static_livability_baseline"
        if advantage > 0.0 and len(learned_policy["action_sequence"]) == env.config.horizon
        else "no_trained_model_based_q_agent_advantage_claim_supported"
    )
    return {
        "schema": UWM_LIVABILITY_RL_TRAINING_REPORT_SCHEMA,
        "report_id": report_id,
        "created_at": created_at,
        "source_environment_schema": env.metadata["schema"],
        "source_observation_id": env.metadata["source_observation_id"],
        "rl_algorithm": {
            "algorithm": "dyna_q_tabular_model_based_rl",
            "world_model_backend": env.metadata["environment_backend"],
            "uses_simulator_model_for_planning": True,
            "uses_final_full_model_backup": final_model_backup_sweeps > 0,
            "state_key": "step_index_plus_ordered_selected_action_indices",
            "action_space": "masked_admin_unit_intervention_actions",
        },
        "training_summary": {
            "episode_count": episodes,
            "seed": seed,
            "learning_rate": learning_rate,
            "discount_factor": discount_factor,
            "epsilon_start": epsilon_start,
            "epsilon_end": epsilon_end,
            "planning_updates_per_step": planning_updates_per_step,
            "planning_update_count": planning_update_count,
            "final_model_backup_sweeps": final_model_backup_sweeps,
            "final_model_backup_transition_count": model_backup_count,
            "q_state_count": len(q_values),
            "learned_replay_transition_count": len(replay_model),
            "real_data_graph_node_count": env.metadata["real_data_sources"]["admin_unit_count"],
            "real_data_graph_edge_count": env.metadata["real_data_sources"]["admin_spatial_edge_count"],
            "real_data_available_action_count": env.metadata["real_data_sources"][
                "available_action_count"
            ],
            "spatial_spillover_directional_edge_count": env.metadata["real_data_sources"][
                "spatial_spillover_directional_edge_count"
            ],
        },
        "training_curve": {
            "curve_metric": "behavior_policy_episode_risk_adjusted_reward",
            "first_20_mean_reward": round(first_20_mean, 9),
            "last_20_mean_reward": round(last_20_mean, 9),
            "improvement_last20_minus_first20": round(last_20_mean - first_20_mean, 9),
            "best_episode_reward": round(max(episode_rewards), 9),
            "episode_rewards_head": episode_rewards[:10],
            "episode_rewards_tail": episode_rewards[-10:],
            "episode_lengths_head": episode_lengths[:10],
            "episode_lengths_tail": episode_lengths[-10:],
        },
        "learned_policy_evaluation": {
            "policy": "greedy_policy_from_trained_q_values",
            "action_count": len(learned_policy["action_sequence"]),
            "action_sequence": learned_policy["action_sequence"],
            "learned_policy_cumulative_reward": round(
                learned_policy["cumulative_reward"],
                9,
            ),
            "advantage_over_traditional_static": round(advantage, 9),
            "uses_spatial_spillover_kernel": bool(
                env.metadata["real_data_sources"]["spatial_spillover_directional_edge_count"]
            ),
            "rollout_trace_steps": learned_policy["rollout_trace_steps"],
            "simulator_mechanism_sources": learned_policy["simulator_mechanism_sources"],
        },
        "baseline_evaluation": {
            "baseline": "traditional_static_priority_single_step_same_graph_mdp",
            "action_sequence": static_baseline["action_sequence"],
            "traditional_static_cumulative_reward": round(
                static_baseline["cumulative_reward"],
                9,
            ),
            "rollout_trace_steps": static_baseline["rollout_trace_steps"],
        },
        "supported_claim": supported_claim,
        "claim_boundary": {
            "max_claim_level": "bounded_support"
            if supported_claim
            == "trained_model_based_q_agent_improves_same_scene_static_livability_baseline"
            else "not_for_claim",
            "reason": (
                "Dyna-Q agent trains on the same real-data Graph-MDP simulator, mechanism table, "
                "spatial spillover kernel and PM2.5 uncertainty context as the static baseline; "
                "this is simulator-grounded planning evidence, not observed policy-outcome evidence"
            ),
        },
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "remaining_gates": [
            "observed_policy_outcome_holdout_required",
            "off_policy_evaluation_on_real_intervention_logs_required",
            "causal_policy_effect_validation_required",
            "larger_city_scale_rl_training_required",
        ],
    }


def _q_update(
    q_values: dict[tuple[int, tuple[int, ...]], dict[int, float]],
    state_key: tuple[int, tuple[int, ...]],
    action_index: int,
    reward: float,
    next_state_key: tuple[int, tuple[int, ...]],
    *,
    done: bool,
    next_valid_actions: list[int],
    learning_rate: float,
    discount_factor: float,
) -> None:
    state_values = q_values.setdefault(state_key, {})
    old_value = state_values.get(action_index, 0.0)
    next_best = 0.0 if done else _max_q(q_values, next_state_key, next_valid_actions)
    target = reward + discount_factor * next_best
    state_values[action_index] = old_value + learning_rate * (target - old_value)


def _planning_updates(
    q_values: dict[tuple[int, tuple[int, ...]], dict[int, float]],
    replay_model: dict[tuple[tuple[int, tuple[int, ...]], int], dict[str, Any]],
    *,
    rng: random.Random,
    update_count: int,
    learning_rate: float,
    discount_factor: float,
) -> int:
    if not replay_model or update_count <= 0:
        return 0
    keys = list(replay_model)
    applied = 0
    for _ in range(update_count):
        state_key, action_index = rng.choice(keys)
        transition = replay_model[(state_key, action_index)]
        _q_update(
            q_values,
            state_key,
            action_index,
            float(transition["reward"]),
            transition["next_state_key"],
            done=bool(transition["done"]),
            next_valid_actions=list(transition["next_valid_actions"]),
            learning_rate=learning_rate,
            discount_factor=discount_factor,
        )
        applied += 1
    return applied


def _final_model_backups(
    env: LivabilityGraphMDPEnv,
    q_values: dict[tuple[int, tuple[int, ...]], dict[int, float]],
    *,
    sweeps: int,
    discount_factor: float,
) -> int:
    if sweeps <= 0:
        return 0
    transition_count = 0
    for _ in range(sweeps):
        for first_action_index in range(len(env.available_actions)):
            env.reset()
            root_key = env.state_key()
            first = env.step(first_action_index)
            first_reward = float(first["reward"])
            first_done = bool(first["done"])
            first_next_key = env.state_key()
            transition_count += 1
            second_values = []
            if not first_done:
                for second_action_index in env.valid_action_indices():
                    env.reset()
                    env.step(first_action_index)
                    second_state_key = env.state_key()
                    second = env.step(second_action_index)
                    q_values.setdefault(second_state_key, {})[second_action_index] = float(
                        second["reward"]
                    )
                    second_values.append(float(second["reward"]))
                    transition_count += 1
            q_values.setdefault(root_key, {})[first_action_index] = first_reward + (
                0.0 if first_done or not second_values else discount_factor * max(second_values)
            )
    env.reset()
    return transition_count


def _evaluate_greedy_policy(
    env: LivabilityGraphMDPEnv,
    q_values: dict[tuple[int, tuple[int, ...]], dict[int, float]],
) -> dict[str, Any]:
    env.reset()
    done = False
    while not done:
        state_key = env.state_key()
        valid_actions = env.valid_action_indices()
        action_index = _select_greedy_action(q_values, state_key, valid_actions)
        result = env.step(action_index)
        done = bool(result["done"])
    rollout = env.last_rollout() or {}
    return {
        "action_sequence": env.action_sequence(),
        "cumulative_reward": env.cumulative_reward(),
        "rollout_trace_steps": [
            str(step.get("step")) for step in rollout.get("simulator_trace") or []
        ],
        "simulator_mechanism_sources": sorted(
            {
                str(step.get("mechanism_source"))
                for step in rollout.get("simulator_trace") or []
                if step.get("mechanism_source")
            }
        ),
    }


def _evaluate_traditional_static_baseline(env: LivabilityGraphMDPEnv) -> dict[str, Any]:
    env.reset()
    action_index = _static_action_index(env.available_actions)
    env.step(action_index)
    rollout = env.last_rollout() or {}
    env.reset()
    return {
        "action_sequence": [dict(env.available_actions[action_index])],
        "cumulative_reward": _score_rollout_with_env(env, rollout),
        "rollout_trace_steps": [
            str(step.get("step")) for step in rollout.get("simulator_trace") or []
        ],
    }


def _score_rollout_with_env(env: LivabilityGraphMDPEnv, rollout: dict[str, Any]) -> float:
    score, _components = env._risk_adjusted_score(rollout)
    return round(score, 9)


def _static_action_index(actions: list[dict[str, Any]]) -> int:
    ranked = [
        (index, _static_priority_score(action), str(action.get("action_id") or ""))
        for index, action in enumerate(actions)
    ]
    ranked.sort(key=lambda item: (item[1], item[2]), reverse=True)
    return ranked[0][0]


def _static_priority_score(action: dict[str, Any]) -> float:
    reason_weight = {
        "heat_risk_above_threshold": 3.0,
        "air_pollution_exposure_above_threshold": 2.0,
        "service_accessibility_below_threshold": 1.0,
        "generic_action_allowed": 0.0,
    }
    return reason_weight.get(str(action.get("mask_reason")), 0.0)


def _select_epsilon_greedy_action(
    q_values: dict[tuple[int, tuple[int, ...]], dict[int, float]],
    state_key: tuple[int, tuple[int, ...]],
    valid_actions: list[int],
    *,
    epsilon: float,
    rng: random.Random,
) -> int:
    if not valid_actions:
        raise ValueError("no valid actions available")
    if rng.random() < epsilon:
        return rng.choice(valid_actions)
    return _select_greedy_action(q_values, state_key, valid_actions)


def _select_greedy_action(
    q_values: dict[tuple[int, tuple[int, ...]], dict[int, float]],
    state_key: tuple[int, tuple[int, ...]],
    valid_actions: list[int],
) -> int:
    if not valid_actions:
        raise ValueError("no valid actions available")
    values = q_values.get(state_key) or {}
    return max(valid_actions, key=lambda action_index: (values.get(action_index, 0.0), -action_index))


def _max_q(
    q_values: dict[tuple[int, tuple[int, ...]], dict[int, float]],
    state_key: tuple[int, tuple[int, ...]],
    valid_actions: list[int],
) -> float:
    if not valid_actions:
        return 0.0
    values = q_values.get(state_key) or {}
    return max(values.get(action_index, 0.0) for action_index in valid_actions)


def _linear_epsilon(
    episode_index: int,
    *,
    total_episodes: int,
    epsilon_start: float,
    epsilon_end: float,
) -> float:
    if total_episodes <= 1:
        return epsilon_end
    ratio = episode_index / float(total_episodes - 1)
    return epsilon_start + ratio * (epsilon_end - epsilon_start)


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
