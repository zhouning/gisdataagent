#!/usr/bin/env python3
"""Materialize the frozen GWM Benchmark V3 CONTROLLED-C2 track."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import resource
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.uwm.dam_geospatial_kernel.contracts import DAMGKBatch, DAMGKConfig
from data_agent.uwm.dam_geospatial_kernel.losses import dam_gk_objective
from data_agent.uwm.dam_geospatial_kernel.model import (
    DynamicActionConditionedMultiscaleKernel,
)
from data_agent.uwm.dam_geospatial_kernel.negative_controls import (
    rewire_edge_targets,
    shuffle_action_assignments,
    shuffle_relation_types,
)


DRAFT_ROOT = Path(__file__).resolve().parent
CONTRACT_PATH = DRAFT_ROOT / "controlled_c2_contract.json"
OUTPUT_ROOT = DRAFT_ROOT / "controlled_c2"
SEED_ROOT = OUTPUT_ROOT / "seed_runs"
FINAL_PATH = OUTPUT_ROOT / "controlled_c2_results.json"
CORPUS_MANIFEST_PATH = OUTPUT_ROOT / "corpus_manifest.json"
SCHEMA = "gwm_bench.foundation_v3_controlled_c2_seed_result.v1"
FINAL_SCHEMA = "gwm_bench.foundation_v3_controlled_c2_results.v1"


@dataclass(frozen=True)
class ControlledC2Sample:
    batch: DAMGKBatch
    target_delta: torch.Tensor
    target_effective_gate: torch.Tensor
    target_topology_probability: torch.Tensor
    target_lag_distribution: torch.Tensor
    affected_node_mask: torch.Tensor
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ControlledC2Corpus:
    sample: ControlledC2Sample
    node_slices: tuple[tuple[int, int], ...]
    edge_slices: tuple[tuple[int, int], ...]
    sample_metadata: tuple[dict[str, Any], ...]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tensor_digest(tensor: torch.Tensor) -> str:
    value = tensor.detach().cpu().contiguous()
    digest = hashlib.sha256()
    digest.update(str(value.dtype).encode("utf-8"))
    digest.update(json.dumps(list(value.shape)).encode("utf-8"))
    digest.update(value.numpy().tobytes(order="C"))
    return digest.hexdigest()


def _sample_coordinates(
    *,
    side: int,
    generator: torch.Generator,
    irregular: bool,
    retention_range: tuple[float, float],
) -> torch.Tensor:
    coordinates = torch.tensor(
        [(x, y) for y in range(side) for x in range(side)],
        dtype=torch.float32,
    )
    if not irregular:
        return coordinates
    low, high = retention_range
    retention = low + (high - low) * float(torch.rand((), generator=generator))
    desired = int(round(side * side * retention))
    desired = max(18, desired)
    desired = min(side * side - 2, desired)
    order = torch.randperm(side * side, generator=generator)
    selected = torch.sort(order[:desired]).values
    return coordinates[selected]


def _candidate_graph(
    *,
    coordinates: torch.Tensor,
    side: int,
    generator: torch.Generator,
    relation_choices: tuple[int, ...],
    test_mixture: bool,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    edges: list[tuple[int, int]] = []
    features: list[list[float]] = []
    for source in range(coordinates.shape[0]):
        sx, sy = coordinates[source].tolist()
        for target in range(coordinates.shape[0]):
            if source == target:
                continue
            tx, ty = coordinates[target].tolist()
            dx = abs(sx - tx)
            dy = abs(sy - ty)
            manhattan = dx + dy
            local = manhattan == 1
            axial_skip = (dx == 2 and dy == 0) or (dx == 0 and dy == 2)
            diagonal = dx == 1 and dy == 1
            if not (local or axial_skip or diagonal):
                continue
            euclidean = math.sqrt(dx * dx + dy * dy)
            distance = euclidean / max(1.0, math.sqrt(2.0) * (side - 1))
            noise = 0.08 * (float(torch.rand((), generator=generator)) - 0.5)
            permeability = min(1.0, max(0.05, 0.98 - 0.75 * distance + noise))
            same_zone = float(
                ((sx >= side / 2) == (tx >= side / 2))
                and ((sy >= side / 2) == (ty >= side / 2))
            )
            barrier = float(
                (sx < side / 2 <= tx)
                or (tx < side / 2 <= sx)
                or (sy < side / 2 <= ty)
                or (ty < side / 2 <= sy)
            )
            edges.append((source, target))
            features.append([distance, permeability, same_zone, barrier])
    if not edges:
        raise ValueError("controlled_c2_graph_has_no_edges")
    edge_index = torch.tensor(edges, dtype=torch.long).t().contiguous()
    edge_features = torch.tensor(features, dtype=torch.float32)
    edge_count = edge_index.shape[1]
    if test_mixture:
        mixture_bank = torch.tensor(
            [
                [0.55, 0.30, 0.15],
                [0.20, 0.55, 0.25],
                [0.20, 0.25, 0.55],
                [0.34, 0.33, 0.33],
            ],
            dtype=torch.float32,
        )
        mixture_index = int(torch.randint(0, 4, (), generator=generator))
        probabilities = mixture_bank[mixture_index]
        edge_types = torch.multinomial(
            probabilities,
            edge_count,
            replacement=True,
            generator=generator,
        ).to(dtype=torch.long)
        if edge_count >= 3:
            edge_types[:3] = torch.tensor([0, 1, 2], dtype=torch.long)
    else:
        choices = torch.tensor(relation_choices, dtype=torch.long)
        positions = torch.randint(
            0,
            len(relation_choices),
            (edge_count,),
            generator=generator,
        )
        edge_types = choices[positions]
        if edge_count >= len(relation_choices):
            edge_types[: len(relation_choices)] = choices
    return edge_index, edge_features, edge_types


def _choose_action_sources(
    *,
    coordinates: torch.Tensor,
    side: int,
    generator: torch.Generator,
    source_count: int,
    interior_only: bool,
) -> torch.Tensor:
    if interior_only:
        candidates = torch.nonzero(
            (coordinates[:, 0] > 0)
            & (coordinates[:, 0] < side - 1)
            & (coordinates[:, 1] > 0)
            & (coordinates[:, 1] < side - 1),
            as_tuple=False,
        ).squeeze(-1)
        if len(candidates) < source_count:
            candidates = torch.arange(coordinates.shape[0])
    else:
        candidates = torch.arange(coordinates.shape[0])
    order = torch.randperm(len(candidates), generator=generator)
    return candidates[order[:source_count]]


def generate_controlled_c2_sample(
    *,
    seed: int,
    sample_index: int,
    split: str,
    contract: dict[str, Any],
) -> ControlledC2Sample:
    generator = torch.Generator().manual_seed(seed)
    horizon = int(contract["model"]["horizon"])
    if split == "fit":
        side = 4
        irregular = False
        source_count = 1
        relation_mixtures = contract["source_fit_corpus"]["relation_mixtures"]
        relation_choices = tuple(
            int(value) for value in relation_mixtures[sample_index % len(relation_mixtures)]
        )
        retention_range = (1.0, 1.0)
    elif split == "ood":
        sides = contract["out_of_distribution_corpus"]["grid_side_lengths"]
        side = int(sides[sample_index % len(sides)])
        irregular = True
        source_count = 1 + (sample_index % 2)
        relation_choices = (0, 1, 2)
        retention_range = tuple(
            float(value)
            for value in contract["out_of_distribution_corpus"][
                "node_retention_range"
            ]
        )
    else:
        raise ValueError(f"unknown_controlled_c2_split:{split}")

    coordinates = _sample_coordinates(
        side=side,
        generator=generator,
        irregular=irregular,
        retention_range=retention_range,
    )
    node_count = int(coordinates.shape[0])
    normalized_coordinates = coordinates / max(1.0, float(side - 1))
    coarse_region = (
        (coordinates[:, 0] >= side / 2).float()
        + 2.0 * (coordinates[:, 1] >= side / 2).float()
    ).unsqueeze(-1) / 3.0
    node_context = torch.cat([normalized_coordinates, coarse_region], dim=-1)
    node_state = 0.15 + 0.70 * torch.rand((node_count, 3), generator=generator)
    node_action = torch.zeros((node_count, 4), dtype=torch.float32)
    action_sources = _choose_action_sources(
        coordinates=coordinates,
        side=side,
        generator=generator,
        source_count=source_count,
        interior_only=split == "fit",
    )
    action_types: list[int] = []
    for position, action_source in enumerate(action_sources.tolist()):
        action_type = int(
            torch.randint(0, 3, (), generator=generator).item()
        )
        if position and action_type == action_types[0]:
            action_type = (action_type + 1) % 3
        intensity = 0.55 + 0.45 * float(torch.rand((), generator=generator))
        node_action[action_source, action_type] = 1.0
        node_action[action_source, 3] = intensity
        action_types.append(action_type)

    edge_index, edge_features, edge_types = _candidate_graph(
        coordinates=coordinates,
        side=side,
        generator=generator,
        relation_choices=relation_choices,
        test_mixture=split == "ood",
    )
    source, target = edge_index
    source_action_present = (node_action[source, 3] > 0).float()
    source_action_type = torch.argmax(node_action[source, :3], dim=1)
    relation_affinity = torch.tensor(
        [
            [0.98, 0.36, 0.12],
            [0.18, 0.96, 0.40],
            [0.42, 0.16, 0.94],
        ],
        dtype=torch.float32,
    )[source_action_type, edge_types]
    permeability = edge_features[:, 1]
    same_zone = edge_features[:, 2]
    barrier = edge_features[:, 3]
    distance = edge_features[:, 0]
    state_contrast = torch.mean(
        torch.abs(node_state[source] - node_state[target]), dim=1
    )
    gate_logits = (
        5.0 * relation_affinity
        + 1.2 * permeability
        - 2.6 * barrier
        + 0.5 * state_contrast
        - 3.4
    )
    target_gate = torch.sigmoid(gate_logits) * source_action_present
    relation_topology_bias = torch.tensor([-0.55, 0.10, 0.65])[edge_types]
    topology_logits = (
        2.3 * permeability
        + 0.8 * same_zone
        - 2.8 * barrier
        + relation_topology_bias
        + 0.35 * (1.0 - state_contrast)
        - 1.55
    )
    target_topology = torch.sigmoid(topology_logits)
    lag_positions = torch.arange(1, horizon + 1, dtype=torch.float32)
    lag_center = (
        1.0
        + 1.35 * edge_types.float()
        + 2.8 * distance
        + 0.80 * barrier
    ).clamp(1.0, float(horizon))
    lag_width = 0.48 + 0.20 * (1.0 - permeability)
    lag_logits = -0.5 * (
        (lag_positions.unsqueeze(0) - lag_center.unsqueeze(1))
        / lag_width.unsqueeze(1)
    ).square()
    target_lag = torch.softmax(lag_logits, dim=1)

    target_delta = torch.zeros((node_count, horizon, 3), dtype=torch.float32)
    affected = torch.zeros(node_count, dtype=torch.bool)
    current_state = node_state.clone()
    for step_index in range(horizon):
        delta = 0.012 * (0.5 - current_state)
        for action_source in action_sources.tolist():
            action_type = int(torch.argmax(node_action[action_source, :3]).item())
            intensity = float(node_action[action_source, 3].item())
            delta[action_source, action_type] += 0.115 * intensity
            delta[action_source, (action_type + 1) % 3] += 0.020 * intensity
            affected[action_source] = True
        edge_strength = (
            target_gate
            * target_topology
            * node_action[source, 3]
            * target_lag[:, step_index]
        )
        active_edges = torch.nonzero(edge_strength > 1e-8, as_tuple=False).squeeze(-1)
        for edge_id in active_edges.tolist():
            target_id = int(target[edge_id].item())
            action_type = int(source_action_type[edge_id].item())
            strength = float(edge_strength[edge_id].item())
            delta[target_id, action_type] += 0.24 * strength
            delta[target_id, (action_type + 1) % 3] += 0.055 * strength
            affected[target_id] = True
        target_delta[:, step_index] = delta
        current_state = current_state + delta

    relation_counts = torch.bincount(edge_types, minlength=3).tolist()
    lag_peak_counts = torch.bincount(
        torch.argmax(target_lag, dim=1), minlength=horizon
    ).tolist()
    metadata = {
        "sample_id": f"{split}-{sample_index:04d}",
        "split": split,
        "seed": seed,
        "grid_side": side,
        "node_count": node_count,
        "full_grid_node_count": side * side,
        "irregular": irregular and node_count < side * side,
        "edge_count": int(edge_index.shape[1]),
        "action_source_count": source_count,
        "action_types": action_types,
        "relation_counts": relation_counts,
        "relation_types_present": [
            index for index, count in enumerate(relation_counts) if count
        ],
        "lag_peak_counts": lag_peak_counts,
    }
    return ControlledC2Sample(
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
        affected_node_mask=affected,
        metadata=metadata,
    )


def _stack_samples(samples: list[ControlledC2Sample]) -> ControlledC2Corpus:
    if not samples:
        raise ValueError("controlled_c2_samples_required")
    node_offset = 0
    edge_offset = 0
    edge_indices = []
    node_slices = []
    edge_slices = []
    for sample in samples:
        node_count = sample.batch.node_state.shape[0]
        edge_count = sample.batch.edge_index.shape[1]
        edge_indices.append(sample.batch.edge_index + node_offset)
        node_slices.append((node_offset, node_offset + node_count))
        edge_slices.append((edge_offset, edge_offset + edge_count))
        node_offset += node_count
        edge_offset += edge_count
    stacked = ControlledC2Sample(
        batch=DAMGKBatch(
            node_state=torch.cat([sample.batch.node_state for sample in samples]),
            node_action=torch.cat([sample.batch.node_action for sample in samples]),
            edge_index=torch.cat(edge_indices, dim=1),
            edge_features=torch.cat(
                [sample.batch.edge_features for sample in samples]
            ),
            edge_types=torch.cat([sample.batch.edge_types for sample in samples]),
            node_context=torch.cat([sample.batch.node_context for sample in samples]),
            edge_valid_mask=torch.cat(
                [sample.batch.edge_valid_mask for sample in samples]
            ),
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
        affected_node_mask=torch.cat(
            [sample.affected_node_mask for sample in samples]
        ),
        metadata={"sample_count": len(samples)},
    )
    return ControlledC2Corpus(
        sample=stacked,
        node_slices=tuple(node_slices),
        edge_slices=tuple(edge_slices),
        sample_metadata=tuple(sample.metadata for sample in samples),
    )


def generate_corpus(*, split: str, contract: dict[str, Any]) -> ControlledC2Corpus:
    if split == "fit":
        corpus_contract = contract["source_fit_corpus"]
    elif split == "ood":
        corpus_contract = contract["out_of_distribution_corpus"]
    else:
        raise ValueError(f"unknown_controlled_c2_split:{split}")
    base_seed = int(corpus_contract["generator_seed"])
    sample_count = int(corpus_contract["sample_count"])
    samples = [
        generate_controlled_c2_sample(
            seed=base_seed + 1009 * sample_index,
            sample_index=sample_index,
            split=split,
            contract=contract,
        )
        for sample_index in range(sample_count)
    ]
    return _stack_samples(samples)


def _corpus_summary(corpus: ControlledC2Corpus) -> dict[str, Any]:
    sample = corpus.sample
    metadata = corpus.sample_metadata
    node_counts = [int(row["node_count"]) for row in metadata]
    edge_counts = [int(row["edge_count"]) for row in metadata]
    grid_histogram: dict[str, int] = {}
    action_histogram: dict[str, int] = {}
    relation_presence_histogram: dict[str, int] = {}
    lag_peak_counts = np.zeros(sample.target_lag_distribution.shape[1], dtype=np.int64)
    for row in metadata:
        side_key = str(row["grid_side"])
        grid_histogram[side_key] = grid_histogram.get(side_key, 0) + 1
        action_key = str(row["action_source_count"])
        action_histogram[action_key] = action_histogram.get(action_key, 0) + 1
        relation_key = "-".join(str(value) for value in row["relation_types_present"])
        relation_presence_histogram[relation_key] = (
            relation_presence_histogram.get(relation_key, 0) + 1
        )
        lag_peak_counts += np.asarray(row["lag_peak_counts"], dtype=np.int64)
    topology = sample.target_topology_probability
    tensor_hashes = {
        "node_state": _tensor_digest(sample.batch.node_state),
        "node_action": _tensor_digest(sample.batch.node_action),
        "edge_index": _tensor_digest(sample.batch.edge_index),
        "edge_features": _tensor_digest(sample.batch.edge_features),
        "edge_types": _tensor_digest(sample.batch.edge_types),
        "node_context": _tensor_digest(sample.batch.node_context),
        "target_delta": _tensor_digest(sample.target_delta),
        "target_effective_gate": _tensor_digest(sample.target_effective_gate),
        "target_topology_probability": _tensor_digest(
            sample.target_topology_probability
        ),
        "target_lag_distribution": _tensor_digest(
            sample.target_lag_distribution
        ),
        "affected_node_mask": _tensor_digest(sample.affected_node_mask),
    }
    identity = {
        "sample_count": len(metadata),
        "node_count": int(sample.batch.node_state.shape[0]),
        "edge_count": int(sample.batch.edge_index.shape[1]),
        "node_count_min": min(node_counts),
        "node_count_max": max(node_counts),
        "node_count_mean": float(np.mean(node_counts)),
        "edge_count_min": min(edge_counts),
        "edge_count_max": max(edge_counts),
        "grid_side_histogram": grid_histogram,
        "action_source_count_histogram": action_histogram,
        "relation_presence_histogram": relation_presence_histogram,
        "lag_peak_counts": lag_peak_counts.tolist(),
        "irregular_sample_count": sum(bool(row["irregular"]) for row in metadata),
        "topology_probability_min": float(topology.min().item()),
        "topology_probability_max": float(topology.max().item()),
        "topology_probability_std": float(topology.std().item()),
        "affected_node_count": int(sample.affected_node_mask.sum().item()),
        "tensor_sha256": tensor_hashes,
    }
    identity["corpus_fingerprint"] = _fingerprint(identity)
    return identity


def build_corpus_manifest(contract: dict[str, Any]) -> dict[str, Any]:
    fit = generate_corpus(split="fit", contract=contract)
    ood = generate_corpus(split="ood", contract=contract)
    fit_summary = _corpus_summary(fit)
    ood_summary = _corpus_summary(ood)
    hidden_factor_checks = {
        "minimum_512_ood_samples": ood_summary["sample_count"]
        >= int(contract["minimum_sample_count"]),
        "ood_graphs_are_larger_than_fit_graphs": ood_summary["node_count_min"]
        > fit_summary["node_count_max"],
        "all_ood_graphs_are_irregular": ood_summary["irregular_sample_count"]
        == ood_summary["sample_count"],
        "fit_never_contains_all_three_relations": fit_summary[
            "relation_presence_histogram"
        ].get("0-1-2", 0)
        == 0,
        "ood_contains_all_three_relations_per_sample": ood_summary[
            "relation_presence_histogram"
        ].get("0-1-2", 0)
        == ood_summary["sample_count"],
        "all_one_to_five_lag_peaks_present": all(
            count > 0 for count in ood_summary["lag_peak_counts"]
        ),
        "soft_topology_is_non_degenerate": (
            ood_summary["topology_probability_min"] < 0.25
            and ood_summary["topology_probability_max"] > 0.75
            and ood_summary["topology_probability_std"] > 0.10
        ),
        "one_and_two_action_assignments_present": set(
            ood_summary["action_source_count_histogram"]
        )
        == {"1", "2"},
    }
    identity = {
        "schema": "gwm_bench.foundation_v3_controlled_c2_corpus_manifest.v1",
        "suite_id": contract["suite_id"],
        "track_id": contract["track_id"],
        "contract_sha256": _sha256_file(CONTRACT_PATH),
        "fit": fit_summary,
        "ood": ood_summary,
        "hidden_factor_checks": hidden_factor_checks,
    }
    identity["manifest_fingerprint"] = _fingerprint(identity)
    return identity


def _model_config(contract: dict[str, Any], overrides: dict[str, Any]) -> DAMGKConfig:
    model = contract["model"]
    return DAMGKConfig(
        node_state_dim=int(model["node_state_dim"]),
        action_dim=int(model["action_dim"]),
        edge_feature_dim=int(model["edge_feature_dim"]),
        relation_type_count=int(model["relation_type_count"]),
        context_dim=int(model["context_dim"]),
        hidden_dim=int(model["hidden_dim"]),
        horizon=int(model["horizon"]),
        **overrides,
    )


def _train_model(
    *,
    corpus: ControlledC2Corpus,
    contract: dict[str, Any],
    fit_seed: int,
    overrides: dict[str, Any],
    epochs: int,
) -> DynamicActionConditionedMultiscaleKernel:
    torch.manual_seed(fit_seed + 1000)
    config = _model_config(contract, overrides)
    model = DynamicActionConditionedMultiscaleKernel(config)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(contract["model"]["learning_rate"]),
        weight_decay=float(contract["model"]["weight_decay"]),
    )
    weights = contract["model"]["loss_weights"]
    for _ in range(epochs):
        optimizer.zero_grad(set_to_none=True)
        output = model(corpus.sample.batch)
        losses = dam_gk_objective(
            output,
            corpus.sample.target_delta,
            target_effective_gate=corpus.sample.target_effective_gate,
            target_topology_probability=corpus.sample.target_topology_probability,
            target_lag_distribution=corpus.sample.target_lag_distribution,
            sparsity_weight=float(weights["sparsity"]),
            gate_supervision_weight=float(weights["effective_gate_supervision"]),
            topology_supervision_weight=float(weights["soft_topology_supervision"]),
            lag_supervision_weight=float(weights["lag_supervision"]),
        )
        losses["total"].backward()
        torch.nn.utils.clip_grad_norm_(
            model.parameters(),
            float(contract["model"]["gradient_clip_norm"]),
        )
        optimizer.step()
    return model


@torch.no_grad()
def _evaluate(
    model: DynamicActionConditionedMultiscaleKernel,
    sample: ControlledC2Sample,
) -> dict[str, Any]:
    output = model(sample.batch)
    state_error = torch.abs(output.state_delta_mean - sample.target_delta)
    affected = sample.affected_node_mask
    mechanism = torch.stack(
        [
            torch.mean(
                torch.abs(
                    output.effective_edge_gate - sample.target_effective_gate
                )
            ),
            torch.mean(
                torch.abs(
                    output.topology_rewrite_probability
                    - sample.target_topology_probability
                )
            ),
            torch.mean(
                torch.abs(
                    output.lag_distribution - sample.target_lag_distribution
                )
            ),
        ]
    )
    return {
        "state_delta_mae": float(state_error.mean().item()),
        "affected_node_state_delta_mae": float(state_error[affected].mean().item()),
        "unaffected_node_state_delta_mae": float(state_error[~affected].mean().item()),
        "effective_gate_mae": float(mechanism[0].item()),
        "topology_probability_mae": float(mechanism[1].item()),
        "lag_distribution_mae": float(mechanism[2].item()),
        "mechanism_macro_mae": float(mechanism.mean().item()),
        "affected_node_count": int(affected.sum().item()),
    }


def _within_sample_roll_permutation(
    slices: tuple[tuple[int, int], ...], *, shift_base: int
) -> torch.Tensor:
    total = slices[-1][1]
    permutation = torch.arange(total, dtype=torch.long)
    for sample_index, (start, end) in enumerate(slices):
        length = end - start
        shift = 1 + ((shift_base + sample_index) % max(1, length - 1))
        local = torch.arange(start, end, dtype=torch.long)
        permutation[start:end] = torch.roll(local, shifts=shift)
    return permutation


@torch.no_grad()
def _evaluate_corrupted_input(
    *,
    model: DynamicActionConditionedMultiscaleKernel,
    corpus: ControlledC2Corpus,
    kind: str,
) -> dict[str, float]:
    if kind == "action_assignment_shuffle":
        permutation = _within_sample_roll_permutation(
            corpus.node_slices, shift_base=7
        )
        batch = shuffle_action_assignments(corpus.sample.batch, permutation)
    elif kind == "relation_type_shuffle":
        permutation = _within_sample_roll_permutation(
            corpus.edge_slices, shift_base=11
        )
        batch = shuffle_relation_types(corpus.sample.batch, permutation)
    elif kind == "spatial_target_rewire":
        permutation = _within_sample_roll_permutation(
            corpus.edge_slices, shift_base=13
        )
        batch = rewire_edge_targets(corpus.sample.batch, permutation)
    else:
        raise ValueError(f"unknown_controlled_c2_corruption:{kind}")
    prediction = model(batch).state_delta_mean
    error = torch.abs(prediction - corpus.sample.target_delta)
    affected = corpus.sample.affected_node_mask
    return {
        "state_delta_mae": float(error.mean().item()),
        "affected_node_state_delta_mae": float(error[affected].mean().item()),
    }


def _control_direction_checks(
    *, variants: dict[str, dict[str, Any]], corruptions: dict[str, dict[str, float]]
) -> dict[str, bool]:
    full = variants["dam_gk_full"]
    return {
        "no_action_conditioning_degrades": variants["no_action_conditioning"]
        ["affected_node_state_delta_mae"]
        > full["affected_node_state_delta_mae"],
        "fixed_topology_degrades": variants["fixed_topology"]
        ["topology_probability_mae"]
        > full["topology_probability_mae"],
        "single_relation_degrades": variants["single_relation"]
        ["mechanism_macro_mae"]
        > full["mechanism_macro_mae"],
        "no_lag_structure_degrades": variants["no_lag_structure"]
        ["lag_distribution_mae"]
        > full["lag_distribution_mae"],
        "action_assignment_shuffle_degrades": corruptions[
            "action_assignment_shuffle"
        ]["affected_node_state_delta_mae"]
        > full["affected_node_state_delta_mae"],
        "relation_type_shuffle_degrades": corruptions["relation_type_shuffle"]
        ["affected_node_state_delta_mae"]
        > full["affected_node_state_delta_mae"],
        "spatial_target_rewire_degrades": corruptions["spatial_target_rewire"]
        ["affected_node_state_delta_mae"]
        > full["affected_node_state_delta_mae"],
    }


def _stability_checks(
    *,
    contract: dict[str, Any],
    variants: dict[str, dict[str, Any]],
    control_checks: dict[str, bool],
) -> tuple[dict[str, bool], bool]:
    full = variants["dam_gk_full"]
    gate = contract["stability_gate_per_seed"]
    checks = {
        "affected_node_state_delta_mae_within_limit": full[
            "affected_node_state_delta_mae"
        ]
        <= float(gate["maximum_affected_node_state_delta_mae"]),
        "effective_gate_mae_within_limit": full["effective_gate_mae"]
        <= float(gate["maximum_effective_gate_mae"]),
        "topology_probability_mae_within_limit": full[
            "topology_probability_mae"
        ]
        <= float(gate["maximum_topology_probability_mae"]),
        "lag_distribution_mae_within_limit": full["lag_distribution_mae"]
        <= float(gate["maximum_lag_distribution_mae"]),
        "minimum_control_direction_count_passed": sum(control_checks.values())
        >= int(gate["minimum_control_direction_pass_count"]),
    }
    critical = gate["critical_control_direction_checks"]
    checks["all_critical_control_directions_passed"] = all(
        control_checks[name] for name in critical
    )
    return checks, all(checks.values())


def _code_artifacts() -> dict[str, dict[str, Any]]:
    paths = {
        "contract": CONTRACT_PATH,
        "runner": Path(__file__).resolve(),
        "dam_gk_model": REPO_ROOT
        / "data_agent/uwm/dam_geospatial_kernel/model.py",
        "dam_gk_contracts": REPO_ROOT
        / "data_agent/uwm/dam_geospatial_kernel/contracts.py",
        "dam_gk_losses": REPO_ROOT
        / "data_agent/uwm/dam_geospatial_kernel/losses.py",
        "dam_gk_negative_controls": REPO_ROOT
        / "data_agent/uwm/dam_geospatial_kernel/negative_controls.py",
    }
    return {
        name: {
            "path": str(path.relative_to(REPO_ROOT)),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        for name, path in paths.items()
    }


def run_seed(
    *,
    contract: dict[str, Any],
    fit_seed: int,
    epochs: int,
    formal: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    fit = generate_corpus(split="fit", contract=contract)
    ood = generate_corpus(split="ood", contract=contract)
    corpus_manifest = build_corpus_manifest(contract)
    if not all(corpus_manifest["hidden_factor_checks"].values()):
        raise RuntimeError("controlled_c2_hidden_factor_coverage_failed")
    variants_spec = {
        "dam_gk_full": {},
        "no_action_conditioning": {"use_action_conditioning": False},
        "fixed_topology": {"use_topology_rewrite": False},
        "single_relation": {"use_relation_types": False},
        "no_lag_structure": {"use_lag_structure": False},
    }
    variants: dict[str, dict[str, Any]] = {}
    trained_full: DynamicActionConditionedMultiscaleKernel | None = None
    for name, overrides in variants_spec.items():
        model = _train_model(
            corpus=fit,
            contract=contract,
            fit_seed=fit_seed,
            overrides=overrides,
            epochs=epochs,
        )
        variants[name] = _evaluate(model, ood.sample)
        if name == "dam_gk_full":
            trained_full = model
    if trained_full is None:
        raise AssertionError("dam_gk_full_model_missing")
    corruptions = {
        name: _evaluate_corrupted_input(model=trained_full, corpus=ood, kind=name)
        for name in (
            "action_assignment_shuffle",
            "relation_type_shuffle",
            "spatial_target_rewire",
        )
    }
    control_checks = _control_direction_checks(
        variants=variants, corruptions=corruptions
    )
    stability_checks, stability_passed = _stability_checks(
        contract=contract,
        variants=variants,
        control_checks=control_checks,
    )
    identity = {
        "schema": SCHEMA,
        "suite_id": contract["suite_id"],
        "track_id": contract["track_id"],
        "formal_component": formal,
        "fit_seed": fit_seed,
        "epochs": epochs,
        "contract_sha256": _sha256_file(CONTRACT_PATH),
        "corpus_manifest_fingerprint": corpus_manifest["manifest_fingerprint"],
        "fit_corpus_fingerprint": corpus_manifest["fit"]["corpus_fingerprint"],
        "ood_corpus_fingerprint": corpus_manifest["ood"]["corpus_fingerprint"],
        "variants": variants,
        "input_corruption_controls": corruptions,
        "control_direction_checks": control_checks,
        "control_direction_pass_count": sum(control_checks.values()),
        "stability_checks": stability_checks,
        "stability_passed": stability_passed,
        "code_artifacts": _code_artifacts(),
    }
    result = {
        **identity,
        "created_at": _utc_now(),
        "wall_time_seconds": time.perf_counter() - started,
        "peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        * (1 if sys.platform == "darwin" else 1024),
        "seed_result_fingerprint": _fingerprint(identity),
    }
    return result


def assemble_results(contract: dict[str, Any]) -> dict[str, Any]:
    expected_seeds = [int(value) for value in contract["fit_seeds"]]
    seed_records = []
    seed_artifacts = {}
    for seed in expected_seeds:
        path = SEED_ROOT / f"seed_{seed}.json"
        if not path.is_file():
            raise FileNotFoundError(f"missing_controlled_c2_seed_result:{path}")
        record = _load_json(path)
        identity = {
            key: value
            for key, value in record.items()
            if key
            not in {
                "created_at",
                "wall_time_seconds",
                "peak_rss_bytes",
                "seed_result_fingerprint",
            }
        }
        if record["seed_result_fingerprint"] != _fingerprint(identity):
            raise ValueError(f"controlled_c2_seed_fingerprint_mismatch:{seed}")
        if record["fit_seed"] != seed or not record["formal_component"]:
            raise ValueError(f"invalid_controlled_c2_seed_component:{seed}")
        if record["epochs"] != int(contract["model"]["epochs"]):
            raise ValueError(f"controlled_c2_epoch_mismatch:{seed}")
        seed_records.append(record)
        seed_artifacts[str(seed)] = {
            "path": str(path.relative_to(REPO_ROOT)),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
            "seed_result_fingerprint": record["seed_result_fingerprint"],
        }
    manifest = build_corpus_manifest(contract)
    _write_json_atomic(manifest, CORPUS_MANIFEST_PATH)
    stability_pass_count = sum(bool(row["stability_passed"]) for row in seed_records)
    full_metric_names = [
        "state_delta_mae",
        "affected_node_state_delta_mae",
        "effective_gate_mae",
        "topology_probability_mae",
        "lag_distribution_mae",
        "mechanism_macro_mae",
    ]
    aggregate = {}
    for metric in full_metric_names:
        values = np.asarray(
            [row["variants"]["dam_gk_full"][metric] for row in seed_records],
            dtype=np.float64,
        )
        aggregate[metric] = {
            "mean": float(values.mean()),
            "median": float(np.median(values)),
            "min": float(values.min()),
            "max": float(values.max()),
        }
    control_pass_counts = {
        name: sum(bool(row["control_direction_checks"][name]) for row in seed_records)
        for name in seed_records[0]["control_direction_checks"]
    }
    completion_checks = {
        "contract_was_frozen": contract["status"]
        == "frozen_before_formal_controlled_c2_run",
        "formal_seed_count_is_ten": len(seed_records)
        == int(contract["required_seed_count"] if "required_seed_count" in contract else 10),
        "minimum_512_samples": manifest["ood"]["sample_count"]
        >= int(contract["minimum_sample_count"]),
        "all_hidden_factor_checks_pass": all(
            manifest["hidden_factor_checks"].values()
        ),
        "all_seven_controls_reported_for_every_seed": all(
            len(row["control_direction_checks"])
            == len(contract["required_controls"])
            for row in seed_records
        ),
        "stability_pass_count_meets_gate": stability_pass_count
        >= int(contract["required_stability_pass_count"]),
        "single_formal_assembly": int(contract["formal_run_count"]) == 1,
    }
    status = (
        "CONTROLLED_C2_COMPLETED_STABILITY_PASS"
        if all(completion_checks.values())
        else "CONTROLLED_C2_COMPLETED_STABILITY_FAIL"
    )
    identity = {
        "schema": FINAL_SCHEMA,
        "suite_id": contract["suite_id"],
        "track_id": contract["track_id"],
        "status": status,
        "formal_run_count": 1,
        "contract_sha256": _sha256_file(CONTRACT_PATH),
        "runner_sha256": _sha256_file(Path(__file__).resolve()),
        "corpus_manifest_fingerprint": manifest["manifest_fingerprint"],
        "fit_corpus_fingerprint": manifest["fit"]["corpus_fingerprint"],
        "ood_corpus_fingerprint": manifest["ood"]["corpus_fingerprint"],
        "sample_count": manifest["ood"]["sample_count"],
        "fit_seeds": expected_seeds,
        "stability_pass_count": stability_pass_count,
        "required_stability_pass_count": int(
            contract["required_stability_pass_count"]
        ),
        "aggregate_dam_gk_full_metrics": aggregate,
        "control_direction_pass_counts": control_pass_counts,
        "completion_checks": completion_checks,
        "seed_artifacts": seed_artifacts,
        "claim_boundary": contract["claim_boundary"],
    }
    result = {
        **identity,
        "created_at": _utc_now(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "torch": torch.__version__,
            "numpy": np.__version__,
            "torch_num_threads": torch.get_num_threads(),
            "pid": os.getpid(),
        },
        "controlled_c2_results_fingerprint": _fingerprint(identity),
    }
    _write_json_atomic(result, FINAL_PATH)
    if status.endswith("FAIL"):
        raise RuntimeError(status)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--inspect-corpus", action="store_true")
    action.add_argument("--fit-seed", type=int)
    action.add_argument("--assemble", action="store_true")
    parser.add_argument("--development", action="store_true")
    parser.add_argument("--epochs", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    contract = _load_json(CONTRACT_PATH)
    torch.use_deterministic_algorithms(True)

    if args.inspect_corpus:
        manifest = build_corpus_manifest(contract)
        if args.output:
            _write_json_atomic(manifest, args.output)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    if args.fit_seed is not None:
        formal_seeds = [int(value) for value in contract["fit_seeds"]]
        if not args.development and args.fit_seed not in formal_seeds:
            raise ValueError("formal_fit_seed_not_in_frozen_contract")
        frozen_epochs = int(contract["model"]["epochs"])
        epochs = args.epochs if args.epochs is not None else frozen_epochs
        if not args.development and epochs != frozen_epochs:
            raise ValueError("formal_epochs_must_match_frozen_contract")
        result = run_seed(
            contract=contract,
            fit_seed=args.fit_seed,
            epochs=epochs,
            formal=not args.development,
        )
        output = args.output
        if output is None:
            output = (
                SEED_ROOT / f"seed_{args.fit_seed}.json"
                if not args.development
                else Path(f"/private/tmp/controlled_c2_dev_seed_{args.fit_seed}.json")
            )
        _write_json_atomic(result, output)
        print(
            json.dumps(
                {
                    "output": str(output),
                    "fit_seed": args.fit_seed,
                    "stability_passed": result["stability_passed"],
                    "control_direction_pass_count": result[
                        "control_direction_pass_count"
                    ],
                    "dam_gk_full": result["variants"]["dam_gk_full"],
                    "wall_time_seconds": result["wall_time_seconds"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.assemble:
        if args.development or args.epochs is not None or args.output is not None:
            raise ValueError("assemble_does_not_accept_development_overrides")
        result = assemble_results(contract)
        print(result["status"])
        print(
            f"stability: {result['stability_pass_count']}/"
            f"{len(result['fit_seeds'])}"
        )
        print(
            "controlled_c2_results_fingerprint: "
            f"{result['controlled_c2_results_fingerprint']}"
        )
        print(f"results: {FINAL_PATH}")
        return 0

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
