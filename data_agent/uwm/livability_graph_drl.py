"""Graph-aware deep Q training evidence for UWM livability Graph-MDP."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

import torch
from torch import nn

from .livability_graph_mdp_env import LivabilityGraphMDPEnv
from .model_based_rl import BASE_NODE_FEATURE_NAMES, MOBILITY_NODE_FEATURE_NAMES


UWM_LIVABILITY_GRAPH_DRL_TRAINING_REPORT_SCHEMA = (
    "uwm.livability_graph_drl_training_report.v1"
)


ACTION_TYPES = [
    "increase_green_infrastructure",
    "traffic_emission_control",
    "add_community_service",
]
MASK_REASONS = [
    "heat_risk_above_threshold",
    "air_pollution_exposure_above_threshold",
    "service_accessibility_below_threshold",
]
TARGET_SCALE = 1000.0
GRAPH_NODE_FEATURE_NAMES = [
    *BASE_NODE_FEATURE_NAMES,
    *MOBILITY_NODE_FEATURE_NAMES,
    "degree_norm",
]
GRAPH_NODE_FEATURE_TRANSFORMS = {
    "heat_risk": "clamped_0_1",
    "air_pollution_exposure": "clamped_0_1",
    "service_accessibility": "clamped_0_1",
    "equity": "clamped_0_1",
    "livability": "clamped_0_1",
    "estimated_nearest_essential_travel_time_min": "max_abs_scaled_by_observed_graph_nodes",
    "road_segment_count": "max_abs_scaled_by_observed_graph_nodes",
    "road_length_km": "max_abs_scaled_by_observed_graph_nodes",
    "mean_road_speed_kmh": "max_abs_scaled_by_observed_graph_nodes",
    "capacity_norm": "clamped_0_1",
    "essential_norm": "clamped_0_1",
    "travel_time_inverse_norm": "clamped_0_1_or_derived_from_observed_travel_time",
    "service_gap": "clamped_0_1",
    "degree_norm": "degree_divided_by_graph_node_count_minus_one",
}


@dataclass(frozen=True)
class GraphDrlTensors:
    node_features: torch.Tensor
    adjacency: torch.Tensor
    action_features: torch.Tensor
    target_node_indices: torch.Tensor
    targets: torch.Tensor
    train_indices: list[int]
    holdout_indices: list[int]


@dataclass(frozen=True)
class GraphDrlActionSamplePlan:
    strategy: str
    first_action_indices: list[int]
    second_action_indices_by_first: dict[int, list[int]]
    policy_action_indices: list[int] | None
    exhaustive_action_pair_training: bool
    sampled_second_action_limit: int | None


class GraphDQNValueNetwork(nn.Module):
    """Minimal message-passing Q network over fixed UWM admin graph state."""

    def __init__(self, *, node_feature_dim: int, action_feature_dim: int, hidden_dim: int) -> None:
        super().__init__()
        self.node_encoder = nn.Linear(node_feature_dim, hidden_dim)
        self.self_linear = nn.Linear(hidden_dim, hidden_dim)
        self.neighbour_linear = nn.Linear(hidden_dim, hidden_dim)
        self.action_encoder = nn.Linear(action_feature_dim, hidden_dim)
        self.head = nn.Sequential(
            nn.Linear(hidden_dim * 3, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )

    def forward(
        self,
        node_features: torch.Tensor,
        adjacency: torch.Tensor,
        target_node_indices: torch.Tensor,
        action_features: torch.Tensor,
    ) -> torch.Tensor:
        node_hidden = torch.relu(self.node_encoder(node_features))
        neighbour_message = adjacency @ node_hidden
        node_hidden = torch.relu(
            self.self_linear(node_hidden) + self.neighbour_linear(neighbour_message)
        )
        graph_embedding = node_hidden.mean(dim=0, keepdim=True).expand(
            action_features.shape[0],
            -1,
        )
        target_embedding = node_hidden[target_node_indices]
        action_embedding = torch.relu(self.action_encoder(action_features))
        return self.head(
            torch.cat([graph_embedding, target_embedding, action_embedding], dim=1)
        ).squeeze(1)


def train_livability_graph_dqn_agent(
    env: LivabilityGraphMDPEnv,
    *,
    report_id: str,
    created_at: str,
    seed: int = 20260707,
    epochs: int = 160,
    hidden_dim: int = 32,
    learning_rate: float = 0.01,
    discount_factor: float = 0.9,
    holdout_stride: int = 7,
    experiment_scope: str = "candidate_admin_graph",
    required_graph_node_count: int | None = None,
    max_first_actions: int | None = None,
    max_second_actions_per_first: int | None = None,
    action_sampling_strategy: str = "exhaustive",
    policy_action_scope: str = "all_available_actions",
) -> dict[str, Any]:
    """Train graph-aware fitted Q network from simulator-generated returns."""

    if epochs <= 0:
        raise ValueError("epochs must be positive")
    if hidden_dim <= 0:
        raise ValueError("hidden_dim must be positive")
    if holdout_stride < 2:
        raise ValueError("holdout_stride must be at least 2")
    if max_first_actions is not None and max_first_actions <= 0:
        raise ValueError("max_first_actions must be positive when provided")
    if (
        max_second_actions_per_first is not None
        and max_second_actions_per_first <= 0
    ):
        raise ValueError(
            "max_second_actions_per_first must be positive when provided"
        )
    if action_sampling_strategy not in {"exhaustive", "stratified_priority"}:
        raise ValueError(
            "action_sampling_strategy must be 'exhaustive' or 'stratified_priority'"
        )
    if policy_action_scope not in {
        "all_available_actions",
        "sampled_training_candidate_pool",
    }:
        raise ValueError(
            "policy_action_scope must be 'all_available_actions' or "
            "'sampled_training_candidate_pool'"
        )

    graph_node_count = int(env.metadata["real_data_sources"]["admin_unit_count"])
    full_data_guard = {
        "required_scope": experiment_scope,
        "required_graph_node_count": required_graph_node_count,
        "observed_graph_node_count": graph_node_count,
        "passed": (
            True
            if required_graph_node_count is None
            else graph_node_count == required_graph_node_count
        ),
    }
    if full_data_guard["passed"] is not True:
        raise ValueError(
            "required_graph_node_count guard failed: "
            f"required_graph_node_count={required_graph_node_count}, "
            f"observed_graph_node_count={graph_node_count}"
        )

    random.seed(seed)
    torch.manual_seed(seed)

    action_sample_plan = _build_action_sample_plan(
        env,
        strategy=action_sampling_strategy,
        max_first_actions=max_first_actions,
        max_second_actions_per_first=max_second_actions_per_first,
        policy_action_scope=policy_action_scope,
    )
    samples = _generate_two_step_q_samples(
        env,
        discount_factor=discount_factor,
        action_sample_plan=action_sample_plan,
    )
    tensors, node_index_by_unit = _build_training_tensors(
        env,
        samples,
        holdout_stride=holdout_stride,
    )
    model = GraphDQNValueNetwork(
        node_feature_dim=tensors.node_features.shape[1],
        action_feature_dim=tensors.action_features.shape[1],
        hidden_dim=hidden_dim,
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    loss_fn = nn.MSELoss()

    train_index_tensor = torch.tensor(tensors.train_indices, dtype=torch.long)
    holdout_index_tensor = torch.tensor(tensors.holdout_indices, dtype=torch.long)
    loss_curve: list[float] = []
    for _epoch in range(epochs):
        model.train()
        optimizer.zero_grad()
        prediction = model(
            tensors.node_features,
            tensors.adjacency,
            tensors.target_node_indices[train_index_tensor],
            tensors.action_features[train_index_tensor],
        )
        loss = loss_fn(prediction, tensors.targets[train_index_tensor])
        loss.backward()
        optimizer.step()
        loss_curve.append(round(float(loss.detach().item()), 9))

    model.eval()
    with torch.no_grad():
        predictions = model(
            tensors.node_features,
            tensors.adjacency,
            tensors.target_node_indices,
            tensors.action_features,
        )
    unscaled_predictions = predictions / TARGET_SCALE
    unscaled_targets = tensors.targets / TARGET_SCALE
    holdout_metrics = _holdout_metrics(
        unscaled_targets,
        unscaled_predictions,
        train_indices=tensors.train_indices,
        holdout_indices=tensors.holdout_indices,
    )
    learned_policy = _evaluate_graph_dqn_policy(
        env,
        model,
        node_index_by_unit=node_index_by_unit,
        node_features=tensors.node_features,
        adjacency=tensors.adjacency,
        policy_action_indices=action_sample_plan.policy_action_indices,
        policy_action_scope=policy_action_scope,
    )
    static_baseline = _evaluate_traditional_static_baseline(env)
    advantage = (
        learned_policy["cumulative_reward"] - static_baseline["cumulative_reward"]
    )
    ready = (
        full_data_guard["passed"] is True
        and advantage > 0.0
        and holdout_metrics["q_return_mae"] < holdout_metrics["train_mean_return_mae"]
        and holdout_metrics["q_return_rmse"] < holdout_metrics["train_mean_return_rmse"]
    )
    sampled_unique_actions = sorted(
        {
            *action_sample_plan.first_action_indices,
            *[
                action_index
                for indices in action_sample_plan.second_action_indices_by_first.values()
                for action_index in indices
            ],
        }
    )
    return {
        "schema": UWM_LIVABILITY_GRAPH_DRL_TRAINING_REPORT_SCHEMA,
        "report_id": report_id,
        "created_at": created_at,
        "experiment_scope": experiment_scope,
        "full_data_guard": full_data_guard,
        "source_environment_schema": env.metadata["schema"],
        "source_observation_id": env.metadata["source_observation_id"],
        "drl_algorithm": {
            "algorithm": "graph_dqn_fitted_q_model_based_rl",
            "is_deep_rl": True,
            "is_model_based": True,
            "is_model_free": False,
            "uses_graph_message_passing": True,
            "policy_or_value_network_trained": True,
            "world_model_backend": env.metadata["environment_backend"],
            "training_target": "simulator_generated_discounted_two_step_q_return",
        },
        "network_architecture": {
            "model_class": "GraphDQNValueNetwork",
            "node_feature_dim": tensors.node_features.shape[1],
            "node_feature_names": GRAPH_NODE_FEATURE_NAMES,
            "node_feature_transforms": GRAPH_NODE_FEATURE_TRANSFORMS,
            "action_feature_dim": tensors.action_features.shape[1],
            "hidden_dim": hidden_dim,
            "message_passing_layers": 1,
            "readout": "graph_mean_embedding_plus_target_node_embedding_plus_action_embedding",
        },
        "training_summary": {
            "seed": seed,
            "epochs": epochs,
            "learning_rate": learning_rate,
            "discount_factor": discount_factor,
            "holdout_stride": holdout_stride,
            "training_sample_count": len(samples),
            "train_count": len(tensors.train_indices),
            "holdout_count": len(tensors.holdout_indices),
            "final_train_loss_scaled": loss_curve[-1],
            "first_train_loss_scaled": loss_curve[0],
            "real_data_graph_node_count": env.metadata["real_data_sources"]["admin_unit_count"],
            "real_data_graph_edge_count": env.metadata["real_data_sources"]["admin_spatial_edge_count"],
            "real_data_available_action_count": env.metadata["real_data_sources"][
                "available_action_count"
            ],
            "action_sampling_strategy": action_sample_plan.strategy,
            "exhaustive_action_pair_training": action_sample_plan.exhaustive_action_pair_training,
            "sampled_first_action_count": len(action_sample_plan.first_action_indices),
            "sampled_second_action_limit": action_sample_plan.sampled_second_action_limit,
            "sampled_unique_action_count": len(sampled_unique_actions),
            "sampled_unique_action_indices": sampled_unique_actions[:200],
            "policy_action_scope": policy_action_scope,
            "spatial_spillover_directional_edge_count": env.metadata["real_data_sources"][
                "spatial_spillover_directional_edge_count"
            ],
        },
        "holdout_metrics": holdout_metrics,
        "learned_policy_evaluation": {
            "policy": "greedy_policy_from_trained_graph_q_network",
            "policy_action_scope": policy_action_scope,
            "action_count": len(learned_policy["action_sequence"]),
            "action_sequence": learned_policy["action_sequence"],
            "predicted_q_values": learned_policy["predicted_q_values"],
            "graph_dqn_policy_cumulative_reward": round(
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
        },
        "supported_claim": (
            "graph_dqn_value_network_improves_same_scene_static_livability_baseline"
            if ready
            else "no_graph_dqn_value_network_advantage_claim_supported"
        ),
        "claim_boundary": {
            "max_claim_level": "bounded_support" if ready else "not_for_claim",
            "reason": (
                "graph Q network is trained on simulator-generated returns over the same real-data "
                "Graph-MDP, calibrated mechanism table, spatial spillover kernel and uncertainty "
                "context as the static baseline; it is not observed policy-outcome evidence"
            ),
        },
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "remaining_gates": [
            "observed_policy_outcome_holdout_required",
            "off_policy_evaluation_on_real_intervention_logs_required",
            "causal_policy_effect_validation_required",
            "larger_city_scale_deep_rl_training_required",
        ],
    }


def _build_action_sample_plan(
    env: LivabilityGraphMDPEnv,
    *,
    strategy: str,
    max_first_actions: int | None,
    max_second_actions_per_first: int | None,
    policy_action_scope: str,
) -> GraphDrlActionSamplePlan:
    action_count = len(env.available_actions)
    if max_first_actions is None and max_second_actions_per_first is None:
        first_action_indices = list(range(action_count))
        second_action_indices_by_first = {
            first_index: [
                second_index
                for second_index in range(action_count)
                if second_index != first_index
            ]
            for first_index in first_action_indices
        }
        return GraphDrlActionSamplePlan(
            strategy=strategy,
            first_action_indices=first_action_indices,
            second_action_indices_by_first=second_action_indices_by_first,
            policy_action_indices=None,
            exhaustive_action_pair_training=True,
            sampled_second_action_limit=None,
        )

    first_limit = min(max_first_actions or action_count, action_count)
    first_action_indices = _ranked_action_indices(
        env,
        strategy=strategy,
        max_count=first_limit,
    )
    if len(first_action_indices) < 2 and action_count > 1:
        raise ValueError("sampled action training requires at least two actions")

    second_limit = max_second_actions_per_first
    if second_limit is None:
        second_limit = max(0, len(first_action_indices) - 1)
    second_limit = min(second_limit, max(0, len(first_action_indices) - 1))

    second_action_indices_by_first = {}
    for first_index in first_action_indices:
        second_action_indices_by_first[first_index] = [
            action_index
            for action_index in first_action_indices
            if action_index != first_index
        ][:second_limit]

    policy_action_indices = (
        first_action_indices
        if policy_action_scope == "sampled_training_candidate_pool"
        else None
    )
    return GraphDrlActionSamplePlan(
        strategy=strategy,
        first_action_indices=first_action_indices,
        second_action_indices_by_first=second_action_indices_by_first,
        policy_action_indices=policy_action_indices,
        exhaustive_action_pair_training=False,
        sampled_second_action_limit=second_limit,
    )


def _ranked_action_indices(
    env: LivabilityGraphMDPEnv,
    *,
    strategy: str,
    max_count: int,
) -> list[int]:
    if strategy == "exhaustive":
        ranked = [
            (index, _action_sampling_score(env, env.available_actions[index]))
            for index in range(len(env.available_actions))
        ]
        ranked.sort(key=lambda item: (item[1], -item[0]), reverse=True)
        return [index for index, _score in ranked[:max_count]]

    grouped: dict[str, list[tuple[int, float]]] = {}
    for index, action in enumerate(env.available_actions):
        action_type = str(action.get("action_type") or "unknown")
        grouped.setdefault(action_type, []).append(
            (index, _action_sampling_score(env, action))
        )
    for rows in grouped.values():
        rows.sort(key=lambda item: (item[1], -item[0]), reverse=True)

    action_type_order = [
        action_type
        for action_type in ACTION_TYPES
        if grouped.get(action_type)
    ] + sorted(
        action_type
        for action_type in grouped
        if action_type not in set(ACTION_TYPES)
    )
    selected: list[int] = []
    cursor = 0
    while len(selected) < max_count and action_type_order:
        action_type = action_type_order[cursor % len(action_type_order)]
        rows = grouped.get(action_type) or []
        if rows:
            selected.append(rows.pop(0)[0])
        action_type_order = [
            item for item in action_type_order if grouped.get(item)
        ]
        cursor += 1
    return selected


def _action_sampling_score(env: LivabilityGraphMDPEnv, action: dict[str, Any]) -> float:
    unit_features = _unit_feature_lookup(env).get(_target_unit(action), {})
    heat = _float(unit_features.get("heat_risk"))
    air = _float(unit_features.get("air_pollution_exposure"))
    service_gap = 1.0 - _float(unit_features.get("service_accessibility"))
    equity_gap = 1.0 - _float(unit_features.get("equity"))
    livability_gap = 1.0 - _float(unit_features.get("livability"))
    degree = _degree_by_unit(env).get(_target_unit(action), 0)
    degree_score = float(degree) / max(1.0, float(len(env.graph_state.get("nodes") or [])))
    action_type = str(action.get("action_type") or "")
    if action_type == "increase_green_infrastructure":
        action_need = heat + 0.35 * air + 0.20 * livability_gap
    elif action_type == "traffic_emission_control":
        action_need = air + 0.25 * equity_gap + 0.15 * livability_gap
    elif action_type == "add_community_service":
        action_need = service_gap + 0.35 * equity_gap + 0.20 * livability_gap
    else:
        action_need = livability_gap
    return (
        _static_priority_score(action)
        + action_need
        + 0.10 * degree_score
        + 0.01 * _float(action.get("intensity"), default=1.0)
    )


def _generate_two_step_q_samples(
    env: LivabilityGraphMDPEnv,
    *,
    discount_factor: float,
    action_sample_plan: GraphDrlActionSamplePlan,
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for first_index in action_sample_plan.first_action_indices:
        env.reset()
        first_result = env.step(first_index)
        first_reward = float(first_result["reward"])
        second_rewards: list[float] = []
        for second_index in action_sample_plan.second_action_indices_by_first.get(
            first_index,
            [],
        ):
            if second_index == first_index:
                continue
            env.reset()
            env.step(first_index)
            second_result = env.step(second_index)
            second_reward = float(second_result["reward"])
            second_rewards.append(second_reward)
            samples.append(
                {
                    "step_index": 1,
                    "selected_action_index": first_index,
                    "action_index": second_index,
                    "target_return": second_reward,
                }
            )
        samples.append(
            {
                "step_index": 0,
                "selected_action_index": -1,
                "action_index": first_index,
                "target_return": first_reward
                + discount_factor * (max(second_rewards) if second_rewards else 0.0),
            }
        )
    env.reset()
    return samples


def _build_training_tensors(
    env: LivabilityGraphMDPEnv,
    samples: list[dict[str, Any]],
    *,
    holdout_stride: int,
) -> tuple[GraphDrlTensors, dict[str, int]]:
    node_index_by_unit = _node_index_by_unit(env)
    node_feature_rows = _node_feature_rows(env)
    node_features_by_unit = _node_features_by_unit(env, node_feature_rows)
    node_features = torch.tensor(node_feature_rows, dtype=torch.float32)
    adjacency = torch.tensor(_normalised_adjacency(env, node_index_by_unit), dtype=torch.float32)
    action_features = torch.tensor(
        [
            _action_feature_row(
                env,
                sample,
                node_index_by_unit=node_index_by_unit,
                node_features_by_unit=node_features_by_unit,
            )
            for sample in samples
        ],
        dtype=torch.float32,
    )
    target_node_indices = torch.tensor(
        [
            _target_node_index(
                env.available_actions[int(sample["action_index"])],
                node_index_by_unit,
            )
            for sample in samples
        ],
        dtype=torch.long,
    )
    targets = torch.tensor(
        [float(sample["target_return"]) * TARGET_SCALE for sample in samples],
        dtype=torch.float32,
    )
    holdout_indices = [
        index for index in range(len(samples)) if (index + 1) % holdout_stride == 0
    ]
    if not holdout_indices:
        holdout_indices = [len(samples) - 1]
    holdout_set = set(holdout_indices)
    train_indices = [index for index in range(len(samples)) if index not in holdout_set]
    return (
        GraphDrlTensors(
            node_features=node_features,
            adjacency=adjacency,
            action_features=action_features,
            target_node_indices=target_node_indices,
            targets=targets,
            train_indices=train_indices,
            holdout_indices=holdout_indices,
        ),
        node_index_by_unit,
    )


def _evaluate_graph_dqn_policy(
    env: LivabilityGraphMDPEnv,
    model: GraphDQNValueNetwork,
    *,
    node_index_by_unit: dict[str, int],
    node_features: torch.Tensor,
    adjacency: torch.Tensor,
    policy_action_indices: list[int] | None,
    policy_action_scope: str,
) -> dict[str, Any]:
    env.reset()
    predicted_q_values: list[dict[str, Any]] = []
    done = False
    selected_action_index = -1
    policy_action_set = (
        set(policy_action_indices) if policy_action_indices is not None else None
    )
    while not done:
        valid_indices = env.valid_action_indices()
        if policy_action_set is not None:
            valid_indices = [
                index for index in valid_indices if index in policy_action_set
            ]
        if not valid_indices:
            break
        scored = _predict_q_for_actions(
            env,
            model,
            valid_indices,
            selected_action_index=selected_action_index,
            node_index_by_unit=node_index_by_unit,
            node_features=node_features,
            adjacency=adjacency,
        )
        best = max(scored, key=lambda row: (row["predicted_q_return"], -row["action_index"]))
        selected_action_index = int(best["action_index"])
        predicted_q_values.append(best)
        result = env.step(selected_action_index)
        done = bool(result["done"])
    rollout = env.last_rollout() or {}
    return {
        "action_sequence": env.action_sequence(),
        "cumulative_reward": env.cumulative_reward(),
        "predicted_q_values": predicted_q_values,
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


def _predict_q_for_actions(
    env: LivabilityGraphMDPEnv,
    model: GraphDQNValueNetwork,
    action_indices: list[int],
    *,
    selected_action_index: int,
    node_index_by_unit: dict[str, int],
    node_features: torch.Tensor,
    adjacency: torch.Tensor,
) -> list[dict[str, Any]]:
    node_features_by_unit = _node_features_by_unit(env, _node_feature_rows(env))
    samples = [
        {
            "step_index": len(env.action_sequence()),
            "selected_action_index": selected_action_index,
            "action_index": action_index,
            "target_return": 0.0,
        }
        for action_index in action_indices
    ]
    action_features = torch.tensor(
        [
            _action_feature_row(
                env,
                sample,
                node_index_by_unit=node_index_by_unit,
                node_features_by_unit=node_features_by_unit,
            )
            for sample in samples
        ],
        dtype=torch.float32,
    )
    target_node_indices = torch.tensor(
        [
            _target_node_index(env.available_actions[action_index], node_index_by_unit)
            for action_index in action_indices
        ],
        dtype=torch.long,
    )
    with torch.no_grad():
        predictions = (
            model(node_features, adjacency, target_node_indices, action_features)
            / TARGET_SCALE
        )
    return [
        {
            "action_index": int(action_index),
            "action_id": env.available_actions[action_index].get("action_id"),
            "predicted_q_return": round(float(prediction), 9),
        }
        for action_index, prediction in zip(action_indices, predictions)
    ]


def _evaluate_traditional_static_baseline(env: LivabilityGraphMDPEnv) -> dict[str, Any]:
    env.reset()
    action_index = _static_action_index(env.available_actions)
    env.step(action_index)
    rollout = env.last_rollout() or {}
    cumulative_reward = env.cumulative_reward()
    action_sequence = env.action_sequence()
    env.reset()
    return {
        "action_sequence": action_sequence,
        "cumulative_reward": cumulative_reward,
        "rollout_trace_steps": [
            str(step.get("step")) for step in rollout.get("simulator_trace") or []
        ],
    }


def _holdout_metrics(
    targets: torch.Tensor,
    predictions: torch.Tensor,
    *,
    train_indices: list[int],
    holdout_indices: list[int],
) -> dict[str, Any]:
    holdout = torch.tensor(holdout_indices, dtype=torch.long)
    train = torch.tensor(train_indices, dtype=torch.long)
    actual = targets[holdout]
    predicted = predictions[holdout]
    train_mean = torch.mean(targets[train])
    baseline = torch.full_like(actual, float(train_mean))
    error = torch.abs(actual - predicted)
    baseline_error = torch.abs(actual - baseline)
    squared_error = torch.square(actual - predicted)
    baseline_squared_error = torch.square(actual - baseline)
    return {
        "q_return_mae": round(float(torch.mean(error)), 9),
        "train_mean_return_mae": round(float(torch.mean(baseline_error)), 9),
        "q_return_rmse": round(float(torch.sqrt(torch.mean(squared_error))), 9),
        "train_mean_return_rmse": round(
            float(torch.sqrt(torch.mean(baseline_squared_error))),
            9,
        ),
        "holdout_win_count_vs_train_mean": int(torch.sum(error < baseline_error).item()),
        "case_count": len(holdout_indices),
    }


def _node_index_by_unit(env: LivabilityGraphMDPEnv) -> dict[str, int]:
    return {
        str(node.get("unit_id") or node.get("node_id")): index
        for index, node in enumerate(env.graph_state.get("nodes") or [])
    }


def _node_feature_rows(env: LivabilityGraphMDPEnv) -> list[list[float]]:
    degree_by_unit = _degree_by_unit(env)
    node_count = max(1, len(env.graph_state.get("nodes") or []))
    scalers = _node_feature_scalers(env)
    rows = []
    for node in env.graph_state.get("nodes") or []:
        features = node.get("features") or {}
        unit_id = str(node.get("unit_id") or node.get("node_id"))
        rows.append(
            [
                _clamp01(_float(features.get("heat_risk"))),
                _clamp01(_float(features.get("air_pollution_exposure"))),
                _clamp01(_float(features.get("service_accessibility"))),
                _clamp01(_float(features.get("equity"))),
                _clamp01(_float(features.get("livability"))),
                _scale_observed(
                    features.get("estimated_nearest_essential_travel_time_min"),
                    scalers["estimated_nearest_essential_travel_time_min"],
                ),
                _scale_observed(
                    features.get("road_segment_count"),
                    scalers["road_segment_count"],
                ),
                _scale_observed(
                    features.get("road_length_km"),
                    scalers["road_length_km"],
                ),
                _scale_observed(
                    features.get("mean_road_speed_kmh"),
                    scalers["mean_road_speed_kmh"],
                ),
                _clamp01(_float(features.get("capacity_norm"))),
                _clamp01(_float(features.get("essential_norm"))),
                _travel_time_inverse_feature(features, scalers),
                _clamp01(_float(features.get("service_gap"))),
                _float(degree_by_unit.get(unit_id)) / max(1.0, float(node_count - 1)),
            ]
        )
    return rows


def _node_feature_scalers(env: LivabilityGraphMDPEnv) -> dict[str, float]:
    raw_feature_names = [
        "estimated_nearest_essential_travel_time_min",
        "road_segment_count",
        "road_length_km",
        "mean_road_speed_kmh",
    ]
    scalers: dict[str, float] = {}
    for feature_name in raw_feature_names:
        values = [
            abs(_float((node.get("features") or {}).get(feature_name)))
            for node in env.graph_state.get("nodes") or []
        ]
        scalers[feature_name] = max([value for value in values if value > 0.0] or [1.0])
    return scalers


def _scale_observed(value: Any, scale: float) -> float:
    if scale <= 0.0:
        return 0.0
    return _clamp01(_float(value) / scale)


def _travel_time_inverse_feature(
    features: dict[str, Any],
    scalers: dict[str, float],
) -> float:
    explicit = _float(features.get("travel_time_inverse_norm"))
    if explicit > 0.0:
        return _clamp01(explicit)
    travel_time = _float(features.get("estimated_nearest_essential_travel_time_min"))
    max_travel_time = scalers.get("estimated_nearest_essential_travel_time_min", 1.0)
    if travel_time <= 0.0 or max_travel_time <= 0.0:
        return 0.0
    return _clamp01(1.0 - (travel_time / max_travel_time))


def _node_features_by_unit(
    env: LivabilityGraphMDPEnv,
    node_feature_rows: list[list[float]],
) -> dict[str, list[float]]:
    return {
        str(node.get("unit_id") or node.get("node_id")): node_feature_rows[index]
        for index, node in enumerate(env.graph_state.get("nodes") or [])
    }


def _normalised_adjacency(
    env: LivabilityGraphMDPEnv,
    node_index_by_unit: dict[str, int],
) -> list[list[float]]:
    node_count = len(node_index_by_unit)
    adjacency = [[0.0 for _ in range(node_count)] for _ in range(node_count)]
    for index in range(node_count):
        adjacency[index][index] = 1.0
    for edge in env.graph_state.get("edges") or []:
        source = node_index_by_unit.get(str(edge.get("source") or ""))
        target = node_index_by_unit.get(str(edge.get("target") or ""))
        if source is None or target is None:
            continue
        weight = _float(edge.get("weight"), default=1.0)
        adjacency[source][target] += weight
        adjacency[target][source] += weight
    for row in adjacency:
        total = sum(row)
        if total > 0.0:
            for index, value in enumerate(row):
                row[index] = value / total
    return adjacency


def _action_feature_row(
    env: LivabilityGraphMDPEnv,
    sample: dict[str, Any],
    *,
    node_index_by_unit: dict[str, int],
    node_features_by_unit: dict[str, list[float]],
) -> list[float]:
    action = env.available_actions[int(sample["action_index"])]
    selected_index = int(sample.get("selected_action_index", -1))
    selected_action = (
        env.available_actions[selected_index]
        if selected_index >= 0
        else {}
    )
    action_type = str(action.get("action_type") or "")
    mask_reason = str(action.get("mask_reason") or "")
    selected_action_type = str(selected_action.get("action_type") or "")
    target_node_features = _node_features_for_action(
        action,
        node_features_by_unit,
    )
    selected_node_features = (
        _node_features_for_action(selected_action, node_features_by_unit)
        if selected_action
        else [0.0] * len(GRAPH_NODE_FEATURE_NAMES)
    )
    step_index = _float(sample.get("step_index"))
    horizon = max(1.0, float(env.config.horizon))
    return [
        *[1.0 if action_type == item else 0.0 for item in ACTION_TYPES],
        *[1.0 if mask_reason == item else 0.0 for item in MASK_REASONS],
        _float(action.get("intensity"), default=1.0),
        step_index / horizon,
        max(0.0, horizon - step_index) / horizon,
        *[1.0 if selected_action_type == item else 0.0 for item in ACTION_TYPES],
        *target_node_features,
        *selected_node_features,
    ]


def _node_features_for_action(
    action: dict[str, Any],
    node_features_by_unit: dict[str, list[float]],
) -> list[float]:
    unit_id = _target_unit(action)
    return list(node_features_by_unit.get(unit_id) or [0.0] * len(GRAPH_NODE_FEATURE_NAMES))


def _target_node_index(action: dict[str, Any], node_index_by_unit: dict[str, int]) -> int:
    return int(node_index_by_unit.get(_target_unit(action), 0))


def _target_unit(action: dict[str, Any]) -> str:
    targets = action.get("target_units")
    if isinstance(targets, list) and targets:
        return str(targets[0])
    if action.get("target_unit") is not None:
        return str(action.get("target_unit"))
    return ""


def _degree_by_unit(env: LivabilityGraphMDPEnv) -> dict[str, int]:
    degree: dict[str, int] = {}
    for edge in env.graph_state.get("edges") or []:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source:
            degree[source] = degree.get(source, 0) + 1
        if target:
            degree[target] = degree.get(target, 0) + 1
    return degree


def _unit_feature_lookup(env: LivabilityGraphMDPEnv) -> dict[str, dict[str, Any]]:
    return {
        str(node.get("unit_id") or node.get("node_id")): dict(node.get("features") or {})
        for node in env.graph_state.get("nodes") or []
    }


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


def _float(value: Any, default: float = 0.0) -> float:
    if value in {None, ""}:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
