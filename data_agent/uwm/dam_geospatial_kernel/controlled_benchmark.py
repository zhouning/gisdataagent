"""Controlled geographic dynamics benchmark with known causal mechanisms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch

from .contracts import DAMGKBatch, DAMGKConfig
from .losses import dam_gk_objective
from .model import DynamicActionConditionedMultiscaleKernel
from .negative_controls import (
    rewire_edge_targets,
    shuffle_action_assignments,
    shuffle_relation_types,
)


CONTROLLED_BENCHMARK_SCHEMA = "gwm.dam_gk.controlled_benchmark.v1"


@dataclass(frozen=True)
class ControlledSample:
    batch: DAMGKBatch
    target_delta: torch.Tensor
    target_effective_gate: torch.Tensor
    target_topology_probability: torch.Tensor
    target_lag_distribution: torch.Tensor
    affected_node_mask: torch.Tensor


def generate_controlled_sample(*, grid_size: int, seed: int) -> ControlledSample:
    generator = torch.Generator().manual_seed(seed)
    node_count = grid_size * grid_size
    coordinates = torch.tensor(
        [(x, y) for y in range(grid_size) for x in range(grid_size)],
        dtype=torch.float32,
    )
    normalized_coordinates = coordinates / max(1.0, float(grid_size - 1))
    coarse_region = (
        (coordinates[:, 0] >= grid_size / 2).float()
        + 2.0 * (coordinates[:, 1] >= grid_size / 2).float()
    ).unsqueeze(-1) / 3.0
    node_context = torch.cat([normalized_coordinates, coarse_region], dim=-1)
    node_state = torch.rand((node_count, 3), generator=generator)
    action_type = int(torch.randint(0, 3, (1,), generator=generator).item())
    action_source = int(torch.randint(0, node_count, (1,), generator=generator).item())
    intensity = 0.5 + 0.5 * float(torch.rand((1,), generator=generator).item())
    node_action = torch.zeros((node_count, 4), dtype=torch.float32)
    node_action[action_source, action_type] = 1.0
    node_action[action_source, 3] = intensity
    edge_index, edge_features, edge_types = _candidate_graph(
        grid_size=grid_size,
        coordinates=coordinates,
    )
    source, target = edge_index
    source_is_action = (source == action_source).float()
    relation_affinity = torch.tensor(
        [
            [0.95, 0.20, 0.10],
            [0.15, 0.95, 0.25],
            [0.20, 0.30, 0.90],
        ],
        dtype=torch.float32,
    )[action_type, edge_types]
    permeability = edge_features[:, 1]
    barrier = edge_features[:, 3]
    state_contrast = torch.mean(torch.abs(node_state[source] - node_state[target]), dim=1)
    gate_logits = (
        4.0 * relation_affinity
        + 1.5 * permeability
        - 2.5 * barrier
        + 0.7 * state_contrast
        - 3.0
    )
    target_gate = torch.sigmoid(gate_logits) * source_is_action
    topology_logits = (
        2.5 * permeability
        + 1.5 * relation_affinity
        - 3.5 * barrier
        + 0.5 * (1.0 - state_contrast)
        - 1.0
    )
    target_topology = torch.sigmoid(topology_logits)
    lag_templates = torch.tensor(
        [
            [0.70, 0.22, 0.08],
            [0.18, 0.52, 0.30],
            [0.08, 0.27, 0.65],
        ],
        dtype=torch.float32,
    )
    target_lag = lag_templates[edge_types]
    target_delta = torch.zeros((node_count, 3, 3), dtype=torch.float32)
    autonomous = 0.015 * (0.5 - node_state)
    target_delta += autonomous.unsqueeze(1) * torch.tensor([1.0, 0.7, 0.4]).view(1, 3, 1)
    direct_profile = torch.tensor([0.70, 0.22, 0.08])
    direct_effect = torch.zeros(3)
    direct_effect[action_type] = 0.28 * intensity
    target_delta[action_source] += direct_profile.view(3, 1) * direct_effect.view(1, 3)
    edge_strength = target_gate * target_topology * intensity
    for edge_id in range(edge_index.shape[1]):
        if source[edge_id].item() != action_source:
            continue
        target_id = int(target[edge_id].item())
        channel_effect = torch.zeros(3)
        channel_effect[action_type] = 0.22 * edge_strength[edge_id]
        cross_channel = (action_type + 1) % 3
        channel_effect[cross_channel] = 0.05 * edge_strength[edge_id]
        target_delta[target_id] += target_lag[edge_id].view(3, 1) * channel_effect.view(1, 3)
    return ControlledSample(
        batch=DAMGKBatch(
            node_state=node_state,
            node_action=node_action,
            edge_index=edge_index,
            edge_features=edge_features,
            edge_types=edge_types,
            node_context=node_context,
            edge_valid_mask=torch.ones(edge_index.shape[1], dtype=torch.bool),
        ),
        target_delta=target_delta,
        target_effective_gate=target_gate,
        target_topology_probability=target_topology,
        target_lag_distribution=target_lag,
        affected_node_mask=torch.any(torch.abs(target_delta - autonomous.unsqueeze(1) * torch.tensor([1.0, 0.7, 0.4]).view(1, 3, 1)) > 1e-8, dim=(1, 2)),
    )


def stack_controlled_samples(samples: list[ControlledSample]) -> ControlledSample:
    if not samples:
        raise ValueError("samples_required")
    node_offset = 0
    batches = []
    for sample in samples:
        batches.append(sample.batch.edge_index + node_offset)
        node_offset += sample.batch.node_state.shape[0]
    return ControlledSample(
        batch=DAMGKBatch(
            node_state=torch.cat([sample.batch.node_state for sample in samples]),
            node_action=torch.cat([sample.batch.node_action for sample in samples]),
            edge_index=torch.cat(batches, dim=1),
            edge_features=torch.cat([sample.batch.edge_features for sample in samples]),
            edge_types=torch.cat([sample.batch.edge_types for sample in samples]),
            node_context=torch.cat([sample.batch.node_context for sample in samples]),
            edge_valid_mask=torch.cat([sample.batch.edge_valid_mask for sample in samples]),
        ),
        target_delta=torch.cat([sample.target_delta for sample in samples]),
        target_effective_gate=torch.cat(
            [sample.target_effective_gate for sample in samples]
        ),
        target_topology_probability=torch.cat(
            [sample.target_topology_probability for sample in samples]
        ),
        target_lag_distribution=torch.cat(
            [sample.target_lag_distribution for sample in samples]
        ),
        affected_node_mask=torch.cat([sample.affected_node_mask for sample in samples]),
    )


def run_controlled_benchmark(
    *,
    seed: int = 17,
    grid_size: int = 4,
    train_sample_count: int = 96,
    test_sample_count: int = 32,
    epochs: int = 180,
) -> dict[str, Any]:
    torch.manual_seed(seed)
    train = stack_controlled_samples(
        [
            generate_controlled_sample(grid_size=grid_size, seed=seed + index)
            for index in range(train_sample_count)
        ]
    )
    test = stack_controlled_samples(
        [
            generate_controlled_sample(
                grid_size=grid_size,
                seed=seed + 10_000 + index,
            )
            for index in range(test_sample_count)
        ]
    )
    variants = {
        "dam_gk_full": {},
        "no_action_conditioning": {"use_action_conditioning": False},
        "single_relation": {"use_relation_types": False},
        "frozen_topology": {"use_topology_rewrite": False},
        "no_lag_structure": {"use_lag_structure": False},
    }
    reports = {}
    trained_models = {}
    for name, overrides in variants.items():
        torch.manual_seed(seed + 1_000)
        config = DAMGKConfig(
            node_state_dim=3,
            action_dim=4,
            edge_feature_dim=4,
            relation_type_count=3,
            context_dim=3,
            hidden_dim=32,
            horizon=3,
            **overrides,
        )
        model = DynamicActionConditionedMultiscaleKernel(config)
        optimizer = torch.optim.AdamW(model.parameters(), lr=0.008, weight_decay=1e-4)
        for _ in range(epochs):
            optimizer.zero_grad()
            output = model(train.batch)
            losses = dam_gk_objective(
                output,
                train.target_delta,
                target_effective_gate=train.target_effective_gate,
                target_topology_probability=train.target_topology_probability,
                target_lag_distribution=train.target_lag_distribution,
                sparsity_weight=0.002,
                gate_supervision_weight=0.25,
                topology_supervision_weight=0.15,
                lag_supervision_weight=0.10,
            )
            losses["total"].backward()
            optimizer.step()
        reports[name] = _evaluate(model, test)
        trained_models[name] = model
    full_model = trained_models["dam_gk_full"]
    reports["dam_gk_full"]["negative_controls"] = {
        "action_assignment_shuffle": _prediction_mae(
            full_model,
            shuffle_action_assignments(
                test.batch,
                torch.roll(torch.arange(test.batch.node_state.shape[0]), shifts=7),
            ),
            test.target_delta,
        ),
        "relation_type_shuffle": _prediction_mae(
            full_model,
            shuffle_relation_types(
                test.batch,
                torch.roll(torch.arange(test.batch.edge_types.shape[0]), shifts=11),
            ),
            test.target_delta,
        ),
        "spatial_target_rewire": _prediction_mae(
            full_model,
            rewire_edge_targets(
                test.batch,
                torch.roll(torch.arange(test.batch.edge_types.shape[0]), shifts=13),
            ),
            test.target_delta,
        ),
    }
    full_mae = reports["dam_gk_full"]["state_delta_mae"]
    full_affected_mae = reports["dam_gk_full"]["affected_node_mae"]
    return {
        "schema": CONTROLLED_BENCHMARK_SCHEMA,
        "seed": seed,
        "grid_size": grid_size,
        "train_sample_count": train_sample_count,
        "test_sample_count": test_sample_count,
        "epochs": epochs,
        "variant_metrics": reports,
        "hypothesis_checks": {
            "beats_no_action_conditioning": full_affected_mae
            < reports["no_action_conditioning"]["affected_node_mae"],
            "multi_relation_improves_state_prediction": full_affected_mae
            < reports["single_relation"]["affected_node_mae"],
            "multi_relation_improves_relation_mechanism_recovery": (
                reports["dam_gk_full"]["effective_gate_mae"]
                < reports["single_relation"]["effective_gate_mae"]
                and reports["dam_gk_full"]["lag_distribution_mae"]
                < reports["single_relation"]["lag_distribution_mae"]
            ),
            "beats_frozen_topology": (
                full_affected_mae < reports["frozen_topology"]["affected_node_mae"]
                or reports["dam_gk_full"]["topology_probability_mae"]
                < reports["frozen_topology"]["topology_probability_mae"]
            ),
            "beats_no_lag_structure": (
                full_affected_mae < reports["no_lag_structure"]["affected_node_mae"]
                or reports["dam_gk_full"]["lag_distribution_mae"]
                < reports["no_lag_structure"]["lag_distribution_mae"]
            ),
            "action_shuffle_degrades": reports["dam_gk_full"]["negative_controls"][
                "action_assignment_shuffle"
            ]
            > full_mae,
            "relation_shuffle_degrades": reports["dam_gk_full"]["negative_controls"][
                "relation_type_shuffle"
            ]
            > full_mae,
            "spatial_rewire_degrades": reports["dam_gk_full"]["negative_controls"][
                "spatial_target_rewire"
            ]
            > full_mae,
        },
        "claim_boundary": {
            "max_claim_level": "controlled_mechanism_recovery",
            "observed_policy_effect_claim": False,
            "multi_relational_state_prediction_claim": False,
        },
    }


def _candidate_graph(
    *, grid_size: int, coordinates: torch.Tensor
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    edges = []
    features = []
    relation_types = []
    node_count = grid_size * grid_size
    for source in range(node_count):
        sx, sy = coordinates[source].tolist()
        for target in range(node_count):
            if source == target:
                continue
            tx, ty = coordinates[target].tolist()
            manhattan = abs(sx - tx) + abs(sy - ty)
            same_row = sy == ty
            same_quadrant = (sx >= grid_size / 2) == (tx >= grid_size / 2) and (
                (sy >= grid_size / 2) == (ty >= grid_size / 2)
            )
            relation_type = None
            if manhattan == 1:
                relation_type = 0
            elif same_row and abs(sx - tx) == 2:
                relation_type = 1
            elif same_quadrant and manhattan >= 2 and (source + target) % 3 == 0:
                relation_type = 2
            if relation_type is None:
                continue
            distance = (manhattan / max(1.0, 2.0 * (grid_size - 1)))
            permeability = 1.0 - 0.45 * distance
            barrier = 1.0 if (sx < grid_size / 2 <= tx or tx < grid_size / 2 <= sx) else 0.0
            edges.append((source, target))
            features.append(
                [
                    distance,
                    permeability,
                    1.0 if same_quadrant else 0.0,
                    barrier,
                ]
            )
            relation_types.append(relation_type)
    return (
        torch.tensor(edges, dtype=torch.long).t().contiguous(),
        torch.tensor(features, dtype=torch.float32),
        torch.tensor(relation_types, dtype=torch.long),
    )


@torch.no_grad()
def _evaluate(
    model: DynamicActionConditionedMultiscaleKernel,
    sample: ControlledSample,
) -> dict[str, float]:
    output = model(sample.batch)
    affected = sample.affected_node_mask
    affected_mae = torch.mean(
        torch.abs(output.state_delta_mean[affected] - sample.target_delta[affected])
    )
    return {
        "state_delta_mae": round(
            torch.mean(torch.abs(output.state_delta_mean - sample.target_delta)).item(), 8
        ),
        "affected_node_mae": round(affected_mae.item(), 8),
        "affected_node_count": int(torch.count_nonzero(affected).item()),
        "effective_gate_mae": round(
            torch.mean(
                torch.abs(output.effective_edge_gate - sample.target_effective_gate)
            ).item(),
            8,
        ),
        "topology_probability_mae": round(
            torch.mean(
                torch.abs(
                    output.topology_rewrite_probability
                    - sample.target_topology_probability
                )
            ).item(),
            8,
        ),
        "lag_distribution_mae": round(
            torch.mean(
                torch.abs(output.lag_distribution - sample.target_lag_distribution)
            ).item(),
            8,
        ),
    }


@torch.no_grad()
def _prediction_mae(
    model: DynamicActionConditionedMultiscaleKernel,
    batch: DAMGKBatch,
    target: torch.Tensor,
) -> float:
    return round(torch.mean(torch.abs(model(batch).state_delta_mean - target)).item(), 8)
