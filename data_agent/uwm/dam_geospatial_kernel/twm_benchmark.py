"""Strict temporal benchmark for DAM-GK on observed land-state transitions."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from torch import nn
from torch.nn import functional as functional

from .contracts import DAMGKBatch, DAMGKConfig
from .negative_controls import (
    permute_coordinate_context,
    permute_edge_geometry,
    rewire_edge_targets,
    shuffle_relation_types,
)
from .twm_adapter import (
    TWM_CLASS_COUNT,
    TWM_REGION_CONTEXT_DIM,
    TWMDAMGKTransition,
    build_twm_dynamic_world_transition,
)
from .twm_transition_head import TWMLandTransitionModel, TWMLandTransitionOutput


TWM_BENCHMARK_SCHEMA = "gwm.dam_gk.twm_cross_region_benchmark.v2"


@dataclass(frozen=True)
class _TaskOutput:
    change_logit: torch.Tensor
    destination_logits: torch.Tensor
    state_delta_mean: torch.Tensor | None = None
    topology_probability: torch.Tensor | None = None
    coarse_state_logits: torch.Tensor | None = None
    use_multiscale_consistency: bool = False


class _TargetOnlyLandTransitionModel(nn.Module):
    def __init__(self, state_dim: int, context_dim: int, hidden_dim: int) -> None:
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(state_dim + context_dim, hidden_dim),
            nn.SiLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.SiLU(),
        )
        self.change_head = nn.Linear(hidden_dim, 1)
        self.destination_head = nn.Linear(hidden_dim, TWM_CLASS_COUNT)

    def forward(self, batch: DAMGKBatch) -> _TaskOutput:
        context = batch.node_context
        if context is None:
            context = batch.node_state.new_zeros((batch.node_state.shape[0], 0))
        latent = self.encoder(torch.cat([batch.node_state, context], dim=1))
        return _TaskOutput(
            change_logit=self.change_head(latent).squeeze(1),
            destination_logits=self.destination_head(latent),
        )


class _StackedTransition:
    def __init__(
        self,
        *,
        batch: DAMGKBatch,
        target_delta: torch.Tensor,
        current_class: torch.Tensor,
        next_class: torch.Tensor,
        fine_node_mask: torch.Tensor,
        changed_fine_node_mask: torch.Tensor,
        node_component: torch.Tensor,
        edge_component: torch.Tensor,
        coarse_node_mask: torch.Tensor,
        fine_to_coarse: torch.Tensor,
    ) -> None:
        self.batch = batch
        self.target_delta = target_delta
        self.current_class = current_class
        self.next_class = next_class
        self.fine_node_mask = fine_node_mask
        self.changed_fine_node_mask = changed_fine_node_mask
        self.node_component = node_component
        self.edge_component = edge_component
        self.coarse_node_mask = coarse_node_mask
        self.fine_to_coarse = fine_to_coarse


def run_twm_cross_region_benchmark(
    *,
    data_root: Path,
    seed: int = 31,
    sample_stride: int = 16,
    coarse_block_size: int = 3,
    epochs: int = 120,
    region_limit: int | None = None,
    held_out_region_count: int = 0,
    held_out_region_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Evaluate strict 2017-2023 temporal generalization without action claims."""

    region_ids = sorted(
        path.name
        for path in data_root.iterdir()
        if path.is_dir()
        and (path / f"{path.name}_dynamic_world_2017_100m.tif").exists()
        and (path / f"{path.name}_dynamic_world_2023_100m.tif").exists()
    )
    if region_limit is not None:
        region_ids = region_ids[:region_limit]
    if len(region_ids) < 2:
        raise ValueError("at_least_two_regions_required")
    if held_out_region_count and held_out_region_ids:
        raise ValueError("choose_count_or_explicit_held_out_regions")
    if held_out_region_count < 0 or held_out_region_count >= len(region_ids):
        raise ValueError("held_out_region_count_must_leave_training_regions")
    if held_out_region_ids:
        unknown_regions = sorted(set(held_out_region_ids) - set(region_ids))
        if unknown_regions:
            raise ValueError(f"unknown_held_out_regions:{','.join(unknown_regions)}")
        if len(set(held_out_region_ids)) >= len(region_ids):
            raise ValueError("held_out_regions_must_leave_training_regions")
        held_out = set(held_out_region_ids)
        training_region_ids = [region for region in region_ids if region not in held_out]
        test_region_ids = [region for region in region_ids if region in held_out]
    elif held_out_region_count:
        training_region_ids = region_ids[:-held_out_region_count]
        test_region_ids = region_ids[-held_out_region_count:]
    else:
        training_region_ids = region_ids
        test_region_ids = region_ids

    split_years = {
        "train": [(2017, 2018), (2018, 2019), (2019, 2020), (2020, 2021)],
        "validation": [(2021, 2022)],
        "test": [(2022, 2023)],
    }
    split_regions = {
        "train": training_region_ids,
        "validation": training_region_ids,
        "test": test_region_ids,
    }
    raw = {
        split: _build_transitions(
            data_root,
            split_regions[split],
            years=years,
            sample_stride=sample_stride,
            coarse_block_size=coarse_block_size,
        )
        for split, years in split_years.items()
    }
    train = _stack_transitions(raw["train"])
    validation = _stack_transitions(raw["validation"])
    test = _stack_transitions(raw["test"])
    training_mask = _balanced_training_mask(train, seed=seed, unchanged_per_changed=3)

    variants: dict[str, dict[str, bool]] = {
        "dam_gk_multirelational": {
            "use_relation_channel_fusion": False,
            "use_region_conditioning": False,
            "use_edge_geometry": False,
        },
        "relative_edge_geometry": {
            "use_relation_channel_fusion": False,
            "use_region_conditioning": False,
            "use_edge_geometry": True,
        },
        "no_multiscale_consistency": {
            "use_relation_channel_fusion": False,
            "use_region_conditioning": False,
            "use_edge_geometry": False,
            "use_multiscale_consistency": False,
        },
        "region_conditioned": {
            "use_relation_channel_fusion": False,
            "use_region_conditioning": True,
            "use_edge_geometry": False,
        },
        "relation_channel_residual": {"use_relation_channel_fusion": True},
        "single_relation": {
            "use_relation_types": False,
            "use_relation_channel_fusion": False,
        },
        "frozen_topology": {
            "use_topology_rewrite": False,
            "use_relation_channel_fusion": False,
        },
        "single_relation_frozen_topology": {
            "use_relation_types": False,
            "use_topology_rewrite": False,
            "use_relation_channel_fusion": False,
        },
    }
    reports: dict[str, Any] = {}
    for variant_name, overrides in variants.items():
        torch.manual_seed(seed)
        model = TWMLandTransitionModel(_kernel_config(**overrides))
        reports[variant_name] = _fit_and_evaluate(
            model,
            train,
            validation,
            test,
            training_mask=training_mask,
            epochs=epochs,
            negative_control_seed=seed + 1000
            if variant_name in {"dam_gk_multirelational", "relative_edge_geometry"}
            else None,
        )

    torch.manual_seed(seed)
    target_only = _TargetOnlyLandTransitionModel(12, 4, 48)
    reports["target_only_mlp"] = _fit_and_evaluate(
        target_only,
        train,
        validation,
        test,
        training_mask=training_mask,
        epochs=epochs,
    )

    baselines = {
        "persistence": _persistence_metrics(test),
        "transition_frequency_markov": _fit_markov_baseline(train, validation, test),
        "local_neighborhood_markov": _fit_markov_baseline(
            train, validation, test, use_neighborhood=True
        ),
    }
    full = reports["dam_gk_multirelational"]["test"]
    geographic_controls = reports["dam_gk_multirelational"].get(
        "geographic_negative_controls", {}
    )
    geometry_controls = reports["relative_edge_geometry"].get(
        "geographic_negative_controls", {}
    )
    strongest_baseline_f1 = max(
        baseline["test"]["change_f1"]
        for name, baseline in baselines.items()
        if name != "persistence"
    )
    return {
        "schema": TWM_BENCHMARK_SCHEMA,
        "seed": seed,
        "region_count": len(region_ids),
        "region_ids": region_ids,
        "training_region_ids": training_region_ids,
        "test_region_ids": test_region_ids,
        "geographic_split": "leave_region_out"
        if test_region_ids != training_region_ids
        else "same_regions_strict_future_year",
        "sample_stride": sample_stride,
        "coarse_block_size": coarse_block_size,
        "temporal_split": {
            "train": "2017-2018 through 2020-2021",
            "validation": "2021-2022",
            "test": "2022-2023",
            "leakage_control": "sampling weights use training labels only; threshold uses validation only",
        },
        "transition_audit": {
            split: _transition_audit(transitions) for split, transitions in raw.items()
        },
        "training_sampling": {
            "strategy": "all changed fine cells plus up to three matched unchanged controls",
            "selected_fine_nodes": int(training_mask.sum()),
            "selected_changed_nodes": int((training_mask & train.changed_fine_node_mask).sum()),
            "selected_unchanged_nodes": int((training_mask & ~train.changed_fine_node_mask).sum()),
        },
        "baselines": baselines,
        "variant_metrics": reports,
        "hypothesis_checks": {
            "detects_any_changed_cells": full["predicted_changed_count"] > 0,
            "beats_persistence_on_changed_destination": full["changed_destination_accuracy"]
            > baselines["persistence"]["changed_destination_accuracy"],
            "beats_strongest_statistical_baseline_change_f1": full["change_f1"]
            > strongest_baseline_f1,
            "beats_target_only_mlp_change_f1": full["change_f1"]
            > reports["target_only_mlp"]["test"]["change_f1"],
            "region_conditioning_improves_change_f1": reports[
                "region_conditioned"
            ]["test"]["change_f1"]
            > full["change_f1"],
            "multi_relation_improves_change_f1": full["change_f1"]
            > reports["single_relation"]["test"]["change_f1"],
            "dynamic_topology_improves_change_f1": full["change_f1"]
            > reports["frozen_topology"]["test"]["change_f1"],
            "relation_shuffle_degrades_change_f1": geographic_controls.get(
                "relation_type_shuffle", {}
            ).get("change_f1", full["change_f1"])
            < full["change_f1"],
            "spatial_rewire_degrades_change_f1": geographic_controls.get(
                "edge_target_rewire", {}
            ).get("change_f1", full["change_f1"])
            < full["change_f1"],
            "coordinate_permutation_degrades_change_f1": geographic_controls.get(
                "coordinate_permutation", {}
            ).get("change_f1", full["change_f1"])
            < full["change_f1"],
            "edge_geometry_permutation_degrades_change_f1": geometry_controls.get(
                "edge_geometry_permutation", {}
            ).get("change_f1", reports["relative_edge_geometry"]["test"]["change_f1"])
            < reports["relative_edge_geometry"]["test"]["change_f1"],
            "relative_edge_geometry_improves_change_f1": reports[
                "relative_edge_geometry"
            ]["test"]["change_f1"]
            > full["change_f1"],
            "multiscale_consistency_reduces_error": full[
                "fine_coarse_consistency_mae"
            ]
            < reports["no_multiscale_consistency"]["test"][
                "fine_coarse_consistency_mae"
            ],
        },
        "claim_boundary": {
            "max_claim_level": "unseen_region_land_state_transfer"
            if test_region_ids != training_region_ids
            else "multi_region_future_land_state_prediction",
            "action_conditioning_claim": False,
            "policy_effect_claim": False,
            "scientific_success_requires_strong_baseline_improvement": True,
        },
    }


def _kernel_config(**overrides: bool) -> DAMGKConfig:
    use_relation_channel_fusion = overrides.pop(
        "use_relation_channel_fusion", False
    )
    use_region_conditioning = overrides.pop("use_region_conditioning", False)
    use_edge_geometry = overrides.pop("use_edge_geometry", False)
    use_multiscale_consistency = overrides.pop(
        "use_multiscale_consistency", True
    )
    return DAMGKConfig(
        node_state_dim=12,
        action_dim=1,
        edge_feature_dim=7,
        relation_type_count=4,
        context_dim=4,
        region_context_dim=TWM_REGION_CONTEXT_DIM,
        hidden_dim=48,
        horizon=1,
        state_output_dim=9,
        mutable_state_dim=9,
        state_writeback_mode="simplex_additive",
        normalize_propagation_mass=True,
        use_relation_channel_fusion=use_relation_channel_fusion,
        use_region_conditioning=use_region_conditioning,
        use_edge_geometry=use_edge_geometry,
        edge_geometry_start_index=4,
        use_multiscale_consistency=use_multiscale_consistency,
        **overrides,
    )


def _fit_and_evaluate(
    model: nn.Module,
    train: _StackedTransition,
    validation: _StackedTransition,
    test: _StackedTransition,
    *,
    training_mask: torch.Tensor,
    epochs: int,
    negative_control_seed: int | None = None,
) -> dict[str, Any]:
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.003, weight_decay=2e-4)
    best_state = None
    best_validation_loss = float("inf")
    patience = 0
    epochs_completed = 0
    for epoch_index in range(epochs):
        model.train()
        optimizer.zero_grad()
        output = _normalize_output(model(train.batch))
        loss = _transition_loss(output, train, training_mask)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optimizer.step()
        epochs_completed = epoch_index + 1

        model.eval()
        with torch.no_grad():
            validation_output = _normalize_output(model(validation.batch))
            validation_loss = float(
                _transition_loss(
                    validation_output,
                    validation,
                    torch.ones_like(validation.changed_fine_node_mask),
                )
            )
        if validation_loss + 1e-6 < best_validation_loss:
            best_validation_loss = validation_loss
            best_state = {
                key: value.detach().clone() for key, value in model.state_dict().items()
            }
            patience = 0
        else:
            patience += 1
        if patience >= 30:
            break
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        validation_output = _normalize_output(model(validation.batch))
        threshold = _select_change_threshold(validation_output, validation)
        report = {
            "epochs_completed": epochs_completed,
            "selected_change_threshold": threshold,
            "validation": _evaluate_output(validation_output, validation, threshold),
            "test": _evaluate_output(
                _normalize_output(model(test.batch)), test, threshold
            ),
        }
        if negative_control_seed is not None:
            report["geographic_negative_controls"] = _evaluate_geographic_controls(
                model,
                test,
                threshold,
                seed=negative_control_seed,
            )
        return report


@torch.no_grad()
def _evaluate_geographic_controls(
    model: nn.Module,
    transition: _StackedTransition,
    threshold: float,
    *,
    seed: int,
) -> dict[str, dict[str, float | int]]:
    generator = torch.Generator().manual_seed(seed)
    relation_permutation = _grouped_permutation(
        transition.edge_component, generator=generator
    )
    target_permutation = _grouped_permutation(
        transition.edge_component, generator=generator
    )
    node_scale = (~transition.fine_node_mask).long()
    coordinate_groups = transition.node_component * 2 + node_scale
    coordinate_permutation = _grouped_permutation(
        coordinate_groups, generator=generator
    )
    edge_geometry_permutation = _grouped_permutation(
        transition.edge_component, generator=generator
    )
    controlled_batches = {
        "relation_type_shuffle": shuffle_relation_types(
            transition.batch,
            relation_permutation,
        ),
        "edge_target_rewire": rewire_edge_targets(
            transition.batch,
            target_permutation,
        ),
        "coordinate_permutation": permute_coordinate_context(
            transition.batch,
            coordinate_permutation,
        ),
        "edge_geometry_permutation": permute_edge_geometry(
            transition.batch,
            edge_geometry_permutation,
            geometry_start_index=4,
        ),
    }
    return {
        name: _evaluate_output(
            _normalize_output(model(controlled_batch)), transition, threshold
        )
        for name, controlled_batch in controlled_batches.items()
    }


def _grouped_permutation(
    group_ids: torch.Tensor, *, generator: torch.Generator
) -> torch.Tensor:
    permutation = torch.arange(group_ids.numel(), dtype=torch.long)
    for group_id in torch.unique(group_ids).tolist():
        indices = torch.where(group_ids == group_id)[0]
        permutation[indices] = indices[
            torch.randperm(indices.numel(), generator=generator)
        ]
    return permutation


def _normalize_output(output: TWMLandTransitionOutput | _TaskOutput) -> _TaskOutput:
    if isinstance(output, TWMLandTransitionOutput):
        return _TaskOutput(
            change_logit=output.change_logit,
            destination_logits=output.destination_logits,
            state_delta_mean=output.kernel_output.state_delta_mean,
            topology_probability=output.kernel_output.topology_rewrite_probability,
            coarse_state_logits=output.coarse_state_logits,
            use_multiscale_consistency=output.use_multiscale_consistency,
        )
    return output


def _transition_loss(
    output: _TaskOutput,
    transition: _StackedTransition,
    selected_fine_mask: torch.Tensor,
) -> torch.Tensor:
    fine_change_logit = output.change_logit[transition.fine_node_mask]
    fine_destination_logits = output.destination_logits[transition.fine_node_mask]
    change_target = transition.changed_fine_node_mask.float()
    selected_logits = fine_change_logit[selected_fine_mask]
    selected_target = change_target[selected_fine_mask]
    probability = torch.sigmoid(selected_logits)
    binary_ce = functional.binary_cross_entropy_with_logits(
        selected_logits, selected_target, reduction="none"
    )
    focal_weight = torch.where(
        selected_target > 0,
        (1.0 - probability).square(),
        probability.square(),
    )
    change_loss = torch.mean(focal_weight * binary_ce)

    changed = transition.changed_fine_node_mask
    if torch.any(changed):
        destination_loss = functional.cross_entropy(
            fine_destination_logits[changed], transition.next_class[changed]
        )
    else:
        destination_loss = fine_destination_logits.sum() * 0.0

    auxiliary = fine_destination_logits.sum() * 0.0
    if output.state_delta_mean is not None:
        auxiliary = functional.smooth_l1_loss(
            output.state_delta_mean, transition.target_delta
        )
    coarse_supervision, multiscale_consistency = _multiscale_losses(
        output, transition
    )
    consistency_weight = 0.2 if output.coarse_state_logits is not None else 0.0
    return (
        change_loss
        + destination_loss
        + 0.05 * auxiliary
        + 0.25 * coarse_supervision
        + consistency_weight * multiscale_consistency
    )


def _multiscale_losses(
    output: _TaskOutput, transition: _StackedTransition
) -> tuple[torch.Tensor, torch.Tensor]:
    zero = output.destination_logits.sum() * 0.0
    if output.coarse_state_logits is None:
        return zero, zero
    coarse_logits = output.coarse_state_logits[transition.coarse_node_mask]
    current_coarse = transition.batch.node_state[
        transition.coarse_node_mask, :TWM_CLASS_COUNT
    ]
    target_coarse = current_coarse + transition.target_delta[
        transition.coarse_node_mask, 0
    ]
    coarse_log_probability = functional.log_softmax(coarse_logits, dim=1)
    coarse_supervision = functional.kl_div(
        coarse_log_probability,
        target_coarse.clamp_min(1e-8),
        reduction="batchmean",
    )
    fine_distribution = _predicted_fine_distribution(output, transition)
    aggregation_mass = transition.fine_to_coarse.sum(dim=1, keepdim=True).clamp_min(1.0)
    aggregated_fine = (transition.fine_to_coarse / aggregation_mass) @ fine_distribution
    predicted_coarse = torch.softmax(coarse_logits, dim=1)
    consistency = functional.smooth_l1_loss(predicted_coarse, aggregated_fine)
    if not output.use_multiscale_consistency:
        consistency = consistency * 0.0
    return coarse_supervision, consistency


def _predicted_fine_distribution(
    output: _TaskOutput, transition: _StackedTransition
) -> torch.Tensor:
    change_probability = torch.sigmoid(
        output.change_logit[transition.fine_node_mask]
    ).unsqueeze(1)
    destination_probability = torch.softmax(
        output.destination_logits[transition.fine_node_mask], dim=1
    )
    current_one_hot = functional.one_hot(
        transition.current_class, num_classes=TWM_CLASS_COUNT
    ).float()
    return (
        (1.0 - change_probability) * current_one_hot
        + change_probability * destination_probability
    )


def _balanced_training_mask(
    transition: _StackedTransition,
    *,
    seed: int,
    unchanged_per_changed: int,
) -> torch.Tensor:
    changed = transition.changed_fine_node_mask
    changed_indices = torch.where(changed)[0]
    unchanged_indices = torch.where(~changed)[0]
    generator = torch.Generator().manual_seed(seed)
    maximum_unchanged = min(
        unchanged_indices.numel(), changed_indices.numel() * unchanged_per_changed
    )
    selected_unchanged = unchanged_indices[
        torch.randperm(unchanged_indices.numel(), generator=generator)[:maximum_unchanged]
    ]
    selected = torch.zeros_like(changed)
    selected[changed_indices] = True
    selected[selected_unchanged] = True
    return selected


def _select_change_threshold(
    output: _TaskOutput,
    transition: _StackedTransition,
) -> float:
    probability = torch.sigmoid(output.change_logit[transition.fine_node_mask])
    best_threshold = 0.5
    best_score = (-1.0, -1.0, -1.0)
    for threshold in torch.linspace(0.05, 0.95, 37).tolist():
        metrics = _binary_change_metrics(
            probability >= threshold, transition.changed_fine_node_mask
        )
        score = (
            metrics["change_f1"],
            metrics["balanced_change_accuracy"],
            metrics["change_precision"],
        )
        if score > best_score:
            best_score = score
            best_threshold = threshold
    return round(float(best_threshold), 4)


@torch.no_grad()
def _evaluate_output(
    output: _TaskOutput,
    transition: _StackedTransition,
    threshold: float,
) -> dict[str, float | int]:
    change_probability = torch.sigmoid(output.change_logit[transition.fine_node_mask])
    predicted_change = change_probability >= threshold
    destination_logits = output.destination_logits[transition.fine_node_mask].clone()
    destination_logits.scatter_(
        1, transition.current_class.unsqueeze(1), torch.finfo(destination_logits.dtype).min
    )
    predicted_destination = torch.argmax(destination_logits, dim=1)
    predicted_class = torch.where(
        predicted_change, predicted_destination, transition.current_class
    )
    changed = transition.changed_fine_node_mask
    metrics: dict[str, float | int] = _binary_change_metrics(predicted_change, changed)
    metrics.update(
        {
            "fine_accuracy": _round_mean(predicted_class == transition.next_class),
            "next_class_macro_f1": _macro_f1(
                predicted_class, transition.next_class, TWM_CLASS_COUNT
            ),
            "changed_destination_accuracy": _round_mean(
                predicted_destination[changed] == transition.next_class[changed]
            )
            if torch.any(changed)
            else 1.0,
            "changed_destination_macro_f1": _macro_f1(
                predicted_destination[changed],
                transition.next_class[changed],
                TWM_CLASS_COUNT,
            )
            if torch.any(changed)
            else 1.0,
            "predicted_changed_count": int(predicted_change.sum()),
            "observed_changed_count": int(changed.sum()),
        }
    )
    if output.coarse_state_logits is not None:
        fine_distribution = _predicted_fine_distribution(output, transition)
        mass = transition.fine_to_coarse.sum(dim=1, keepdim=True).clamp_min(1.0)
        aggregated_fine = (transition.fine_to_coarse / mass) @ fine_distribution
        predicted_coarse = torch.softmax(
            output.coarse_state_logits[transition.coarse_node_mask], dim=1
        )
        metrics["fine_coarse_consistency_mae"] = round(
            float(torch.mean(torch.abs(predicted_coarse - aggregated_fine))), 8
        )
    if output.state_delta_mean is not None:
        metrics["delta_mae"] = round(
            float(torch.mean(torch.abs(output.state_delta_mean - transition.target_delta))),
            8,
        )
    return metrics


def _binary_change_metrics(
    predicted_change: torch.Tensor, changed: torch.Tensor
) -> dict[str, float]:
    true_positive = torch.sum(predicted_change & changed).float()
    false_positive = torch.sum(predicted_change & ~changed).float()
    false_negative = torch.sum(~predicted_change & changed).float()
    true_negative = torch.sum(~predicted_change & ~changed).float()
    precision = true_positive / (true_positive + false_positive).clamp_min(1)
    recall = true_positive / (true_positive + false_negative).clamp_min(1)
    specificity = true_negative / (true_negative + false_positive).clamp_min(1)
    f1 = 2.0 * precision * recall / (precision + recall).clamp_min(1e-8)
    return {
        "change_precision": round(float(precision), 8),
        "change_recall": round(float(recall), 8),
        "change_f1": round(float(f1), 8),
        "balanced_change_accuracy": round(float((recall + specificity) / 2.0), 8),
    }


def _persistence_metrics(transition: _StackedTransition) -> dict[str, Any]:
    predicted_change = torch.zeros_like(transition.changed_fine_node_mask)
    metrics: dict[str, Any] = _binary_change_metrics(
        predicted_change, transition.changed_fine_node_mask
    )
    metrics.update(
        {
            "fine_accuracy": _round_mean(
                transition.current_class == transition.next_class
            ),
            "next_class_macro_f1": _macro_f1(
                transition.current_class, transition.next_class, TWM_CLASS_COUNT
            ),
            "changed_destination_accuracy": 0.0,
            "changed_destination_macro_f1": 0.0,
            "predicted_changed_count": 0,
            "observed_changed_count": int(transition.changed_fine_node_mask.sum()),
        }
    )
    return metrics


def _fit_markov_baseline(
    train: _StackedTransition,
    validation: _StackedTransition,
    test: _StackedTransition,
    *,
    use_neighborhood: bool = False,
) -> dict[str, Any]:
    train_keys = _markov_keys(train, use_neighborhood)
    counts: dict[tuple[int, ...], torch.Tensor] = defaultdict(
        lambda: torch.ones(TWM_CLASS_COUNT, dtype=torch.float32)
    )
    for key, next_class in zip(train_keys, train.next_class.tolist()):
        counts[key][next_class] += 1.0

    validation_probability, validation_destination = _markov_predictions(
        counts, validation, use_neighborhood
    )
    threshold = _select_probability_threshold(
        validation_probability, validation.changed_fine_node_mask
    )
    return {
        "selected_change_threshold": threshold,
        "validation": _evaluate_discrete_predictions(
            validation_probability,
            validation_destination,
            validation,
            threshold,
        ),
        "test": _evaluate_discrete_predictions(
            *_markov_predictions(counts, test, use_neighborhood), test, threshold
        ),
    }


def _markov_keys(
    transition: _StackedTransition, use_neighborhood: bool
) -> list[tuple[int, ...]]:
    if not use_neighborhood:
        return [(value,) for value in transition.current_class.tolist()]
    neighbor_class = _dominant_neighbor_class(transition)
    return list(zip(transition.current_class.tolist(), neighbor_class.tolist()))


def _dominant_neighbor_class(transition: _StackedTransition) -> torch.Tensor:
    fine_global = torch.where(transition.fine_node_mask)[0]
    global_to_fine = torch.full(
        (transition.batch.node_state.shape[0],), -1, dtype=torch.long
    )
    global_to_fine[fine_global] = torch.arange(fine_global.numel())
    histogram = torch.zeros((fine_global.numel(), TWM_CLASS_COUNT))
    source, target = transition.batch.edge_index
    spatial = transition.batch.edge_types == 0
    source_fine = global_to_fine[source[spatial]]
    target_fine = global_to_fine[target[spatial]]
    valid = (source_fine >= 0) & (target_fine >= 0)
    if torch.any(valid):
        histogram.index_put_(
            (target_fine[valid], transition.current_class[source_fine[valid]]),
            torch.ones(int(valid.sum())),
            accumulate=True,
        )
    empty = histogram.sum(dim=1) == 0
    dominant = torch.argmax(histogram, dim=1)
    dominant[empty] = transition.current_class[empty]
    return dominant


def _markov_predictions(
    counts: dict[tuple[int, ...], torch.Tensor],
    transition: _StackedTransition,
    use_neighborhood: bool,
) -> tuple[torch.Tensor, torch.Tensor]:
    probabilities = []
    destinations = []
    for key, current_class in zip(
        _markov_keys(transition, use_neighborhood), transition.current_class.tolist()
    ):
        row = counts.get(key, torch.ones(TWM_CLASS_COUNT))
        distribution = row / row.sum()
        probabilities.append(1.0 - float(distribution[current_class]))
        changed_row = row.clone()
        changed_row[current_class] = -1.0
        destinations.append(int(torch.argmax(changed_row)))
    return torch.tensor(probabilities), torch.tensor(destinations)


def _select_probability_threshold(
    probability: torch.Tensor, changed: torch.Tensor
) -> float:
    best_threshold = 0.5
    best_score = (-1.0, -1.0)
    for threshold in torch.linspace(0.01, 0.99, 99).tolist():
        metrics = _binary_change_metrics(probability >= threshold, changed)
        score = (metrics["change_f1"], metrics["balanced_change_accuracy"])
        if score > best_score:
            best_score = score
            best_threshold = threshold
    return round(float(best_threshold), 4)


def _evaluate_discrete_predictions(
    change_probability: torch.Tensor,
    predicted_destination: torch.Tensor,
    transition: _StackedTransition,
    threshold: float,
) -> dict[str, Any]:
    predicted_change = change_probability >= threshold
    predicted_class = torch.where(
        predicted_change, predicted_destination, transition.current_class
    )
    changed = transition.changed_fine_node_mask
    metrics: dict[str, Any] = _binary_change_metrics(predicted_change, changed)
    metrics.update(
        {
            "fine_accuracy": _round_mean(predicted_class == transition.next_class),
            "next_class_macro_f1": _macro_f1(
                predicted_class, transition.next_class, TWM_CLASS_COUNT
            ),
            "changed_destination_accuracy": _round_mean(
                predicted_destination[changed] == transition.next_class[changed]
            )
            if torch.any(changed)
            else 1.0,
            "changed_destination_macro_f1": _macro_f1(
                predicted_destination[changed],
                transition.next_class[changed],
                TWM_CLASS_COUNT,
            )
            if torch.any(changed)
            else 1.0,
            "predicted_changed_count": int(predicted_change.sum()),
            "observed_changed_count": int(changed.sum()),
        }
    )
    return metrics


def _transition_audit(transitions: list[TWMDAMGKTransition]) -> dict[str, Any]:
    matrix = torch.zeros((TWM_CLASS_COUNT, TWM_CLASS_COUNT), dtype=torch.long)
    by_region: dict[str, dict[str, int | float]] = {}
    for transition in transitions:
        for current_class, next_class in zip(
            transition.current_class.tolist(), transition.next_class.tolist()
        ):
            matrix[current_class, next_class] += 1
        region = transition.metadata["region_id"]
        entry = by_region.setdefault(region, {"fine_cells": 0, "changed_cells": 0})
        entry["fine_cells"] += int(transition.current_class.numel())
        entry["changed_cells"] += int(
            torch.sum(transition.current_class != transition.next_class)
        )
    for entry in by_region.values():
        entry["change_rate"] = round(
            entry["changed_cells"] / max(1, entry["fine_cells"]), 8
        )
    total = int(matrix.sum())
    changed = int(matrix.sum() - matrix.diag().sum())
    return {
        "fine_cell_count": total,
        "changed_cell_count": changed,
        "change_rate": round(changed / max(1, total), 8),
        "transition_matrix": matrix.tolist(),
        "region_summary": by_region,
    }


def _build_transitions(
    data_root: Path,
    region_ids: list[str],
    *,
    years: list[tuple[int, int]],
    sample_stride: int,
    coarse_block_size: int,
) -> list[TWMDAMGKTransition]:
    return [
        build_twm_dynamic_world_transition(
            region_dir=data_root / region_id,
            region_id=region_id,
            current_year=current_year,
            next_year=next_year,
            sample_stride=sample_stride,
            coarse_block_size=coarse_block_size,
        )
        for region_id in region_ids
        for current_year, next_year in years
    ]


def _stack_transitions(transitions: list[TWMDAMGKTransition]) -> _StackedTransition:
    node_offset = 0
    edge_indices = []
    fine_masks = []
    current_classes = []
    next_classes = []
    changed_masks = []
    node_components = []
    edge_components = []
    coarse_masks = []
    fine_to_coarse_blocks = []
    fine_offset = 0
    coarse_offset = 0
    for component_index, transition in enumerate(transitions):
        edge_indices.append(transition.batch.edge_index + node_offset)
        node_count = transition.batch.node_state.shape[0]
        fine_count = transition.current_class.shape[0]
        fine_mask = torch.zeros(node_count, dtype=torch.bool)
        fine_mask[:fine_count] = True
        fine_masks.append(fine_mask)
        coarse_masks.append(~fine_mask)
        current_classes.append(transition.current_class)
        next_classes.append(transition.next_class)
        changed_masks.append(transition.current_class != transition.next_class)
        node_components.append(
            torch.full((node_count,), component_index, dtype=torch.long)
        )
        edge_components.append(
            torch.full(
                (transition.batch.edge_index.shape[1],),
                component_index,
                dtype=torch.long,
            )
        )
        block = torch.zeros(
            (
                coarse_offset + transition.fine_to_coarse.shape[0],
                fine_offset + transition.fine_to_coarse.shape[1],
            ),
            dtype=torch.float32,
        )
        if fine_to_coarse_blocks:
            previous = fine_to_coarse_blocks[-1]
            block[: previous.shape[0], : previous.shape[1]] = previous
        block[
            coarse_offset:,
            fine_offset:,
        ] = transition.fine_to_coarse
        fine_to_coarse_blocks.append(block)
        fine_offset += transition.fine_to_coarse.shape[1]
        coarse_offset += transition.fine_to_coarse.shape[0]
        node_offset += node_count
    return _StackedTransition(
        batch=DAMGKBatch(
            node_state=torch.cat([row.batch.node_state for row in transitions]),
            node_action=torch.cat([row.batch.node_action for row in transitions]),
            edge_index=torch.cat(edge_indices, dim=1),
            edge_features=torch.cat([row.batch.edge_features for row in transitions]),
            edge_types=torch.cat([row.batch.edge_types for row in transitions]),
            node_context=torch.cat([row.batch.node_context for row in transitions]),
            region_context=torch.cat(
                [row.batch.region_context for row in transitions]
            ),
            edge_valid_mask=torch.cat([row.batch.edge_valid_mask for row in transitions]),
        ),
        target_delta=torch.cat([row.target_delta for row in transitions]),
        current_class=torch.cat(current_classes),
        next_class=torch.cat(next_classes),
        fine_node_mask=torch.cat(fine_masks),
        changed_fine_node_mask=torch.cat(changed_masks),
        node_component=torch.cat(node_components),
        edge_component=torch.cat(edge_components),
        coarse_node_mask=torch.cat(coarse_masks),
        fine_to_coarse=fine_to_coarse_blocks[-1],
    )


def _macro_f1(
    predicted: torch.Tensor, target: torch.Tensor, class_count: int
) -> float:
    scores = []
    for class_index in range(class_count):
        present = (target == class_index) | (predicted == class_index)
        if not torch.any(present):
            continue
        true_positive = torch.sum(
            (predicted == class_index) & (target == class_index)
        ).float()
        false_positive = torch.sum(
            (predicted == class_index) & (target != class_index)
        ).float()
        false_negative = torch.sum(
            (predicted != class_index) & (target == class_index)
        ).float()
        score = 2.0 * true_positive / (
            2.0 * true_positive + false_positive + false_negative
        ).clamp_min(1)
        scores.append(score)
    if not scores:
        return 0.0
    return round(float(torch.stack(scores).mean()), 8)


def _round_mean(values: torch.Tensor) -> float:
    if values.numel() == 0:
        return 0.0
    return round(float(values.float().mean()), 8)
