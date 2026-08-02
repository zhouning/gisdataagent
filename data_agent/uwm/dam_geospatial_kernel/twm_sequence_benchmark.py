"""Multi-step recursive TWM benchmark with strict state-writeback ablations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import torch
from torch.nn import functional as functional

from .contracts import DAMGKBatch, DAMGKConfig
from .twm_adapter import TWM_CLASS_COUNT, TWM_REGION_CONTEXT_DIM
from .twm_sequence_adapter import (
    TWM_SEQUENCE_CONTEXT_DIM,
    TWMDAMGKSequence,
    build_twm_dynamic_world_sequence,
)
from .twm_transition_head import TWMLandTransitionModel, TWMLandTransitionOutput


TWM_SEQUENCE_BENCHMARK_SCHEMA = "gwm.dam_gk.twm_recursive_benchmark.v1"


@dataclass(frozen=True)
class _StackedSequence:
    batch: DAMGKBatch
    target_delta: torch.Tensor
    initial_class: torch.Tensor
    future_class: torch.Tensor
    fine_node_mask: torch.Tensor


def run_twm_recursive_benchmark(
    *,
    data_root: Path,
    region_ids: list[str],
    seed: int = 31,
    sample_stride: int = 24,
    coarse_block_size: int = 3,
    epochs: int = 80,
    use_temporal_history_context: bool = True,
    annual_viirs_context_mode: str = "none",
) -> dict[str, Any]:
    """Train on 2017-2020 and test recursive 2020-2023 prediction."""

    if not region_ids:
        raise ValueError("region_ids_required")
    train = _stack_sequences(
        [
            build_twm_dynamic_world_sequence(
                region_dir=data_root / region_id,
                region_id=region_id,
                years=(2017, 2018, 2019, 2020),
                sample_stride=sample_stride,
                coarse_block_size=coarse_block_size,
                terrain_similarity_scope="local_spatial_window",
                use_temporal_history_context=use_temporal_history_context,
                annual_viirs_context_mode=annual_viirs_context_mode,
            )
            for region_id in region_ids
        ]
    )
    test = _stack_sequences(
        [
            build_twm_dynamic_world_sequence(
                region_dir=data_root / region_id,
                region_id=region_id,
                years=(2020, 2021, 2022, 2023),
                sample_stride=sample_stride,
                coarse_block_size=coarse_block_size,
                terrain_similarity_scope="local_spatial_window",
                use_temporal_history_context=use_temporal_history_context,
                annual_viirs_context_mode=annual_viirs_context_mode,
            )
            for region_id in region_ids
        ]
    )
    reports = _fit_variants(
        train=train,
        validation=train,
        test=test,
        seed=seed,
        epochs=epochs,
        threshold_source="training_data_smoke_only",
    )
    reports["independent_one_step_chain"] = _run_one_step_chain_baseline(
        train=train,
        validation=train,
        test=test,
        seed=seed,
        epochs=epochs,
    )
    reports["markov_transition"] = _markov_metrics(train, test)
    reports["persistence"] = _persistence_metrics(test)
    recursive_final = reports["recursive_writeback"]["final_horizon"]
    frozen_final = reports["no_state_writeback"]["final_horizon"]
    return {
        "schema": TWM_SEQUENCE_BENCHMARK_SCHEMA,
        "seed": seed,
        "regions": region_ids,
        "train_years": [2017, 2018, 2019, 2020],
        "test_years": [2020, 2021, 2022, 2023],
        "sample_stride": sample_stride,
        "epochs": epochs,
        "annual_viirs_context_mode": annual_viirs_context_mode,
        "forecast_protocol": (
            "rolling_observed_current_year_covariates"
            if annual_viirs_context_mode == "rolling"
            else "sequence_initial_year_covariates_only"
            if annual_viirs_context_mode == "initial_only"
            else "static_period_composite_covariates"
        ),
        "reports": reports,
        "hypothesis_checks": {
            "recursive_writeback_improves_final_change_f1": recursive_final[
                "change_f1"
            ]
            > frozen_final["change_f1"],
            "recursive_writeback_improves_final_class_macro_f1": recursive_final[
                "next_class_macro_f1"
            ]
            > frozen_final["next_class_macro_f1"],
            "recursive_writeback_beats_one_step_chain_final_change_f1": recursive_final[
                "change_f1"
            ]
            > reports["independent_one_step_chain"]["final_horizon"]["change_f1"],
            "recursive_writeback_beats_persistence_final_class_macro_f1": recursive_final[
                "next_class_macro_f1"
            ]
            > reports["persistence"]["final_horizon"]["next_class_macro_f1"],
        },
        "claim_boundary": {
            "max_claim_level": "bounded_observed_multiyear_land_state_prediction",
            "teacher_forced_oracle_is_deployable": False,
            "action_conditioning_claim": False,
            "policy_effect_claim": False,
            "recursive_value_requires_outperforming_no_writeback": True,
        },
    }


def run_twm_recursive_region_holdout(
    *,
    data_root: Path,
    training_region_ids: list[str],
    validation_region_ids: list[str],
    test_region_ids: list[str],
    seed: int = 31,
    sample_stride: int = 24,
    coarse_block_size: int = 3,
    epochs: int = 80,
    use_temporal_history_context: bool = True,
    annual_viirs_context_mode: str = "none",
) -> dict[str, Any]:
    """Evaluate unseen-region recursion with validation-only threshold selection."""

    region_sets = [
        set(training_region_ids),
        set(validation_region_ids),
        set(test_region_ids),
    ]
    if any(not region_set for region_set in region_sets):
        raise ValueError("training_validation_and_test_regions_required")
    if any(
        region_sets[left] & region_sets[right]
        for left, right in ((0, 1), (0, 2), (1, 2))
    ):
        raise ValueError("region_splits_must_be_disjoint")

    train = _build_stacked_region_sequences(
        data_root=data_root,
        region_ids=training_region_ids,
        years=(2017, 2018, 2019, 2020),
        sample_stride=sample_stride,
        coarse_block_size=coarse_block_size,
        use_temporal_history_context=use_temporal_history_context,
        annual_viirs_context_mode=annual_viirs_context_mode,
    )
    validation = _build_stacked_region_sequences(
        data_root=data_root,
        region_ids=validation_region_ids,
        years=(2017, 2018, 2019, 2020),
        sample_stride=sample_stride,
        coarse_block_size=coarse_block_size,
        use_temporal_history_context=use_temporal_history_context,
        annual_viirs_context_mode=annual_viirs_context_mode,
    )
    test = _build_stacked_region_sequences(
        data_root=data_root,
        region_ids=test_region_ids,
        years=(2020, 2021, 2022, 2023),
        sample_stride=sample_stride,
        coarse_block_size=coarse_block_size,
        use_temporal_history_context=use_temporal_history_context,
        annual_viirs_context_mode=annual_viirs_context_mode,
    )
    reports = _fit_variants(
        train=train,
        validation=validation,
        test=test,
        seed=seed,
        epochs=epochs,
        threshold_source="validation_regions_only",
    )
    reports["independent_one_step_chain"] = _run_one_step_chain_baseline(
        train=train,
        validation=validation,
        test=test,
        seed=seed,
        epochs=epochs,
    )
    reports["markov_transition"] = _markov_metrics(train, test)
    reports["persistence"] = _persistence_metrics(test)
    recursive_final = reports["recursive_writeback"]["final_horizon"]
    frozen_final = reports["no_state_writeback"]["final_horizon"]
    return {
        "schema": TWM_SEQUENCE_BENCHMARK_SCHEMA,
        "protocol": "disjoint_region_validation_and_unseen_region_test",
        "seed": seed,
        "training_regions": training_region_ids,
        "validation_regions": validation_region_ids,
        "test_regions": test_region_ids,
        "train_validation_years": [2017, 2018, 2019, 2020],
        "test_years": [2020, 2021, 2022, 2023],
        "sample_stride": sample_stride,
        "epochs": epochs,
        "annual_viirs_context_mode": annual_viirs_context_mode,
        "forecast_protocol": (
            "rolling_observed_current_year_covariates"
            if annual_viirs_context_mode == "rolling"
            else "sequence_initial_year_covariates_only"
            if annual_viirs_context_mode == "initial_only"
            else "static_period_composite_covariates"
        ),
        "reports": reports,
        "hypothesis_checks": {
            "recursive_writeback_improves_final_change_f1": recursive_final[
                "change_f1"
            ]
            > frozen_final["change_f1"],
            "recursive_writeback_improves_final_class_macro_f1": recursive_final[
                "next_class_macro_f1"
            ]
            > frozen_final["next_class_macro_f1"],
            "recursive_writeback_beats_one_step_chain_final_change_f1": recursive_final[
                "change_f1"
            ]
            > reports["independent_one_step_chain"]["final_horizon"]["change_f1"],
            "recursive_writeback_beats_persistence_final_class_macro_f1": recursive_final[
                "next_class_macro_f1"
            ]
            > reports["persistence"]["final_horizon"]["next_class_macro_f1"],
        },
        "claim_boundary": {
            "max_claim_level": "unseen_region_multiyear_land_state_prediction",
            "validation_labels_used_for_test_thresholds": True,
            "test_labels_used_for_thresholds": False,
            "teacher_forced_oracle_is_deployable": False,
            "action_conditioning_claim": False,
            "policy_effect_claim": False,
        },
    }


def _fit_variants(
    *,
    train: _StackedSequence,
    validation: _StackedSequence,
    test: _StackedSequence,
    seed: int,
    epochs: int,
    threshold_source: str,
) -> dict[str, Any]:
    variants = {
        "recursive_writeback": "categorical_mixture",
        "no_state_writeback": "categorical_no_writeback",
        "teacher_forced_oracle": "categorical_teacher_forced",
    }
    reports = {}
    for name, writeback_mode in variants.items():
        model = _fit_model(
            train=train,
            state_writeback_mode=writeback_mode,
            seed=seed,
            epochs=epochs,
        )
        model.eval()
        with torch.no_grad():
            validation_output = model(validation.batch)
            thresholds = _select_change_thresholds(validation_output, validation)
            reports[name] = _sequence_metrics(
                model(test.batch), test, change_thresholds=thresholds
            )
            reports[name]["change_thresholds"] = thresholds
            reports[name]["threshold_source"] = threshold_source
    return reports


def _fit_model(
    *,
    train: _StackedSequence,
    state_writeback_mode: str,
    seed: int,
    epochs: int,
) -> TWMLandTransitionModel:
    torch.manual_seed(seed)
    model = TWMLandTransitionModel(
        _kernel_config(
            state_writeback_mode=state_writeback_mode,
            context_dim=train.batch.node_context.shape[1],
        )
    )
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.003, weight_decay=2e-4)
    for _ in range(epochs):
        model.train()
        optimizer.zero_grad()
        output = model(train.batch)
        loss = _sequence_loss(output, train)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optimizer.step()
    return model


def _build_stacked_region_sequences(
    *,
    data_root: Path,
    region_ids: list[str],
    years: tuple[int, ...],
    sample_stride: int,
    coarse_block_size: int,
    use_temporal_history_context: bool,
    annual_viirs_context_mode: str,
) -> _StackedSequence:
    return _stack_sequences(
        [
            build_twm_dynamic_world_sequence(
                region_dir=data_root / region_id,
                region_id=region_id,
                years=years,
                sample_stride=sample_stride,
                coarse_block_size=coarse_block_size,
                terrain_similarity_scope="local_spatial_window",
                use_temporal_history_context=use_temporal_history_context,
                annual_viirs_context_mode=annual_viirs_context_mode,
            )
            for region_id in region_ids
        ]
    )


def _kernel_config(
    *, state_writeback_mode: str, context_dim: int, horizon: int = 3
) -> DAMGKConfig:
    return DAMGKConfig(
        node_state_dim=12,
        action_dim=1,
        edge_feature_dim=7,
        relation_type_count=4,
        context_dim=context_dim,
        region_context_dim=TWM_REGION_CONTEXT_DIM,
        hidden_dim=48,
        horizon=horizon,
        state_output_dim=9,
        mutable_state_dim=9,
        state_writeback_mode=state_writeback_mode,
        normalize_propagation_mass=True,
        edge_geometry_start_index=4,
        use_edge_geometry=False,
        use_region_conditioning=False,
        use_multiscale_consistency=True,
    )


def _stack_sequences(sequences: list[TWMDAMGKSequence]) -> _StackedSequence:
    node_offset = 0
    edge_indices = []
    fine_masks = []
    initial_classes = []
    future_classes = []
    for sequence in sequences:
        node_count = sequence.batch.node_state.shape[0]
        fine_count = sequence.metadata["fine_node_count"]
        edge_indices.append(sequence.batch.edge_index + node_offset)
        fine_mask = torch.zeros(node_count, dtype=torch.bool)
        fine_mask[:fine_count] = True
        fine_masks.append(fine_mask)
        initial_classes.append(sequence.initial_class)
        future_classes.append(sequence.future_class)
        node_offset += node_count
    batch = DAMGKBatch(
        node_state=torch.cat([sequence.batch.node_state for sequence in sequences]),
        node_action=torch.cat([sequence.batch.node_action for sequence in sequences]),
        node_context=torch.cat([sequence.batch.node_context for sequence in sequences]),
        node_context_by_step=torch.cat(
            [sequence.batch.node_context_by_step for sequence in sequences]
        ),
        teacher_state_by_step=torch.cat(
            [sequence.batch.teacher_state_by_step for sequence in sequences]
        ),
        region_context=torch.cat(
            [sequence.batch.region_context for sequence in sequences]
        ),
        edge_index=torch.cat(edge_indices, dim=1),
        edge_features=torch.cat(
            [sequence.batch.edge_features for sequence in sequences]
        ),
        edge_types=torch.cat([sequence.batch.edge_types for sequence in sequences]),
        edge_valid_mask=torch.cat(
            [sequence.batch.edge_valid_mask for sequence in sequences]
        )
        if sequences[0].batch.edge_valid_mask is not None
        else None,
    )
    return _StackedSequence(
        batch=batch,
        target_delta=torch.cat([sequence.target_delta for sequence in sequences]),
        initial_class=torch.cat(initial_classes),
        future_class=torch.cat(future_classes),
        fine_node_mask=torch.cat(fine_masks),
    )


def _sequence_loss(
    output: TWMLandTransitionOutput, sequence: _StackedSequence
) -> torch.Tensor:
    change_logits = output.change_logit[sequence.fine_node_mask]
    destination_logits = output.destination_logits[sequence.fine_node_mask]
    previous_class = torch.cat(
        [sequence.initial_class[:, None], sequence.future_class[:, :-1]], dim=1
    )
    changed = sequence.future_class != previous_class
    change_target = changed.float()
    change_probability = torch.sigmoid(change_logits)
    binary_ce = functional.binary_cross_entropy_with_logits(
        change_logits, change_target, reduction="none"
    )
    positive_count = change_target.sum(dim=0).clamp_min(1.0)
    negative_count = (1.0 - change_target).sum(dim=0).clamp_min(1.0)
    class_weight = torch.where(
        changed,
        (negative_count / positive_count).unsqueeze(0),
        torch.ones_like(change_target),
    )
    focal_weight = torch.where(
        changed, (1.0 - change_probability).square(), change_probability.square()
    )
    change_loss = torch.mean(class_weight * focal_weight * binary_ce)
    if torch.any(changed):
        destination_loss = functional.cross_entropy(
            destination_logits[changed], sequence.future_class[changed]
        )
    else:
        destination_loss = destination_logits.sum() * 0.0
    delta_loss = functional.smooth_l1_loss(
        output.kernel_output.state_delta_mean, sequence.target_delta
    )
    return change_loss + destination_loss + 0.05 * delta_loss


def _run_one_step_chain_baseline(
    *,
    train: _StackedSequence,
    validation: _StackedSequence,
    test: _StackedSequence,
    seed: int,
    epochs: int,
) -> dict[str, Any]:
    torch.manual_seed(seed)
    model = TWMLandTransitionModel(
        _kernel_config(
            state_writeback_mode="categorical_mixture",
            context_dim=train.batch.node_context.shape[1],
            horizon=1,
        )
    )
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.003, weight_decay=2e-4)
    for _ in range(epochs):
        model.train()
        optimizer.zero_grad()
        losses = []
        for step_index in range(train.future_class.shape[1]):
            current_state = (
                train.batch.node_state
                if step_index == 0
                else train.batch.teacher_state_by_step[:, step_index - 1]
            )
            output = model(_single_step_batch(train.batch, current_state, step_index))
            losses.append(_one_step_loss(output, train, step_index))
        loss = torch.stack(losses).mean()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optimizer.step()
    model.eval()
    with torch.no_grad():
        validation_probability, _ = _roll_one_step_model(model, validation)
        thresholds = _select_probability_thresholds(
            validation_probability, validation
        )
        probability, destination = _roll_one_step_model(model, test)
    report = _prediction_metrics(
        change_probability=probability,
        destination=destination,
        sequence=test,
        change_thresholds=thresholds,
    )
    report["change_thresholds"] = thresholds
    report["threshold_source"] = "validation_regions_only"
    report["training_mode"] = "observed_one_step_teacher_states"
    report["test_mode"] = "recursive_predicted_state_chain"
    return report


def _single_step_batch(
    batch: DAMGKBatch, current_state: torch.Tensor, step_index: int
) -> DAMGKBatch:
    return replace(
        batch,
        node_state=current_state,
        node_context=batch.node_context_by_step[:, step_index],
        node_context_by_step=None,
        teacher_state_by_step=None,
    )


def _one_step_loss(
    output: TWMLandTransitionOutput,
    sequence: _StackedSequence,
    step_index: int,
) -> torch.Tensor:
    logits = output.change_logit[sequence.fine_node_mask]
    destination_logits = output.destination_logits[sequence.fine_node_mask]
    previous_class = (
        sequence.initial_class
        if step_index == 0
        else sequence.future_class[:, step_index - 1]
    )
    changed = sequence.future_class[:, step_index] != previous_class
    probability = torch.sigmoid(logits)
    binary_ce = functional.binary_cross_entropy_with_logits(
        logits, changed.float(), reduction="none"
    )
    positive_count = changed.sum().clamp_min(1)
    negative_count = (~changed).sum().clamp_min(1)
    class_weight = torch.where(
        changed,
        negative_count.float() / positive_count.float(),
        torch.ones_like(probability),
    )
    focal_weight = torch.where(
        changed, (1.0 - probability).square(), probability.square()
    )
    change_loss = torch.mean(class_weight * focal_weight * binary_ce)
    destination_loss = (
        functional.cross_entropy(
            destination_logits[changed], sequence.future_class[:, step_index][changed]
        )
        if torch.any(changed)
        else destination_logits.sum() * 0.0
    )
    delta_loss = functional.smooth_l1_loss(
        output.kernel_output.state_delta_mean[:, 0],
        sequence.target_delta[:, step_index],
    )
    return change_loss + destination_loss + 0.05 * delta_loss


def _roll_one_step_model(
    model: TWMLandTransitionModel, sequence: _StackedSequence
) -> tuple[torch.Tensor, torch.Tensor]:
    current_state = sequence.batch.node_state
    probabilities = []
    destinations = []
    for step_index in range(sequence.future_class.shape[1]):
        output = model(_single_step_batch(sequence.batch, current_state, step_index))
        probability = torch.sigmoid(output.change_logit[sequence.fine_node_mask])
        destination = torch.argmax(
            output.destination_logits[sequence.fine_node_mask], dim=-1
        )
        probabilities.append(probability)
        destinations.append(destination)
        current_state = output.kernel_output.rolled_state[:, 0]
    return (
        torch.stack(probabilities, dim=1),
        torch.stack(destinations, dim=1),
    )


def _markov_metrics(
    train: _StackedSequence, test: _StackedSequence
) -> dict[str, Any]:
    counts = torch.ones((TWM_CLASS_COUNT, TWM_CLASS_COUNT), dtype=torch.float32)
    previous = torch.cat(
        [train.initial_class[:, None], train.future_class[:, :-1]], dim=1
    )
    for source_class, target_class in zip(
        previous.flatten().tolist(), train.future_class.flatten().tolist()
    ):
        counts[source_class, target_class] += 1.0
    transition_probability = counts / counts.sum(dim=1, keepdim=True)
    predicted_previous = test.initial_class
    predicted_classes = []
    predicted_changes = []
    for _ in range(test.future_class.shape[1]):
        predicted_next = torch.argmax(transition_probability[predicted_previous], dim=1)
        predicted_changes.append(predicted_next != predicted_previous)
        predicted_classes.append(predicted_next)
        predicted_previous = predicted_next
    predicted_class = torch.stack(predicted_classes, dim=1)
    predicted_change = torch.stack(predicted_changes, dim=1)
    observed_previous = torch.cat(
        [test.initial_class[:, None], test.future_class[:, :-1]], dim=1
    )
    observed_change = test.future_class != observed_previous
    by_horizon = [
        _horizon_metrics(
            predicted_change[:, step],
            observed_change[:, step],
            predicted_class[:, step],
            test.future_class[:, step],
            step + 1,
        )
        for step in range(test.future_class.shape[1])
    ]
    return {
        "by_horizon": by_horizon,
        "final_horizon": by_horizon[-1],
        "laplace_smoothing": 1.0,
    }


def _sequence_metrics(
    output: TWMLandTransitionOutput,
    sequence: _StackedSequence,
    *,
    change_thresholds: list[float] | None = None,
) -> dict[str, Any]:
    change_probability = torch.sigmoid(output.change_logit[sequence.fine_node_mask])
    if change_thresholds is None:
        change_thresholds = [0.5] * change_probability.shape[1]
    threshold_tensor = change_probability.new_tensor(change_thresholds).unsqueeze(0)
    predicted_change = change_probability >= threshold_tensor
    destination = torch.argmax(
        output.destination_logits[sequence.fine_node_mask], dim=-1
    )
    observed_previous_class = torch.cat(
        [sequence.initial_class[:, None], sequence.future_class[:, :-1]], dim=1
    )
    observed_change = sequence.future_class != observed_previous_class
    predicted_classes = []
    predicted_previous_class = sequence.initial_class
    for horizon_index in range(sequence.future_class.shape[1]):
        predicted_previous_class = torch.where(
            predicted_change[:, horizon_index],
            destination[:, horizon_index],
            predicted_previous_class,
        )
        predicted_classes.append(predicted_previous_class)
    predicted_class = torch.stack(predicted_classes, dim=1)
    by_horizon = []
    for horizon_index in range(sequence.future_class.shape[1]):
        by_horizon.append(
            _horizon_metrics(
                predicted_change[:, horizon_index],
                observed_change[:, horizon_index],
                predicted_class[:, horizon_index],
                sequence.future_class[:, horizon_index],
                horizon_index + 1,
                change_probability=change_probability[:, horizon_index],
                predicted_destination=destination[:, horizon_index],
            )
        )
    return {
        "by_horizon": by_horizon,
        "final_horizon": by_horizon[-1],
        "change_f1_degradation_slope": round(
            (by_horizon[-1]["change_f1"] - by_horizon[0]["change_f1"])
            / max(1, len(by_horizon) - 1),
            6,
        ),
        "edge_gate_step_drift": [
            round(
                float(
                    torch.mean(
                        torch.abs(
                            output.kernel_output.edge_gate_by_step[:, step]
                            - output.kernel_output.edge_gate_by_step[:, 0]
                        )
                    )
                ),
                6,
            )
            for step in range(output.kernel_output.edge_gate_by_step.shape[1])
        ],
        "topology_step_drift": [
            round(
                float(
                    torch.mean(
                        torch.abs(
                            output.kernel_output.topology_probability_by_step[:, step]
                            - output.kernel_output.topology_probability_by_step[:, 0]
                        )
                    )
                ),
                6,
            )
            for step in range(
                output.kernel_output.topology_probability_by_step.shape[1]
            )
        ],
    }


def _select_change_thresholds(
    output: TWMLandTransitionOutput, sequence: _StackedSequence
) -> list[float]:
    probability = torch.sigmoid(output.change_logit[sequence.fine_node_mask])
    return _select_probability_thresholds(probability, sequence)


def _select_probability_thresholds(
    probability: torch.Tensor, sequence: _StackedSequence
) -> list[float]:
    previous_class = torch.cat(
        [sequence.initial_class[:, None], sequence.future_class[:, :-1]], dim=1
    )
    observed_change = sequence.future_class != previous_class
    candidates = torch.linspace(0.05, 0.95, 19)
    thresholds = []
    for horizon_index in range(probability.shape[1]):
        best_threshold = 0.5
        best_f1 = -1.0
        for threshold in candidates:
            predicted = probability[:, horizon_index] >= threshold
            f1 = _binary_f1(predicted, observed_change[:, horizon_index])
            if f1 > best_f1:
                best_f1 = f1
                best_threshold = float(threshold)
        thresholds.append(round(best_threshold, 4))
    return thresholds


def _prediction_metrics(
    *,
    change_probability: torch.Tensor,
    destination: torch.Tensor,
    sequence: _StackedSequence,
    change_thresholds: list[float],
) -> dict[str, Any]:
    threshold_tensor = change_probability.new_tensor(change_thresholds).unsqueeze(0)
    predicted_change = change_probability >= threshold_tensor
    observed_previous = torch.cat(
        [sequence.initial_class[:, None], sequence.future_class[:, :-1]], dim=1
    )
    observed_change = sequence.future_class != observed_previous
    predicted_previous = sequence.initial_class
    predicted_classes = []
    for step_index in range(sequence.future_class.shape[1]):
        predicted_previous = torch.where(
            predicted_change[:, step_index],
            destination[:, step_index],
            predicted_previous,
        )
        predicted_classes.append(predicted_previous)
    predicted_class = torch.stack(predicted_classes, dim=1)
    by_horizon = [
        _horizon_metrics(
            predicted_change[:, step],
            observed_change[:, step],
            predicted_class[:, step],
            sequence.future_class[:, step],
            step + 1,
            change_probability=change_probability[:, step],
            predicted_destination=destination[:, step],
        )
        for step in range(sequence.future_class.shape[1])
    ]
    return {
        "by_horizon": by_horizon,
        "final_horizon": by_horizon[-1],
        "change_f1_degradation_slope": round(
            (by_horizon[-1]["change_f1"] - by_horizon[0]["change_f1"])
            / max(1, len(by_horizon) - 1),
            6,
        ),
    }


def _persistence_metrics(sequence: _StackedSequence) -> dict[str, Any]:
    by_horizon = []
    observed_previous_class = sequence.initial_class
    for horizon_index in range(sequence.future_class.shape[1]):
        predicted_class = sequence.initial_class
        observed_change = (
            sequence.future_class[:, horizon_index] != observed_previous_class
        )
        by_horizon.append(
            _horizon_metrics(
                torch.zeros_like(observed_change),
                observed_change,
                predicted_class,
                sequence.future_class[:, horizon_index],
                horizon_index + 1,
            )
        )
        observed_previous_class = sequence.future_class[:, horizon_index]
    return {"by_horizon": by_horizon, "final_horizon": by_horizon[-1]}


def _horizon_metrics(
    predicted_change: torch.Tensor,
    observed_change: torch.Tensor,
    predicted_class: torch.Tensor,
    observed_class: torch.Tensor,
    horizon: int,
    change_probability: torch.Tensor | None = None,
    predicted_destination: torch.Tensor | None = None,
) -> dict[str, Any]:
    true_positive = torch.sum(predicted_change & observed_change).item()
    false_positive = torch.sum(predicted_change & ~observed_change).item()
    false_negative = torch.sum(~predicted_change & observed_change).item()
    denominator = 2 * true_positive + false_positive + false_negative
    true_negative = torch.sum(~predicted_change & ~observed_change).item()
    positive_count = true_positive + false_negative
    negative_count = true_negative + false_positive
    result = {
        "horizon": horizon,
        "change_f1": round(_binary_f1(predicted_change, observed_change), 6),
        "balanced_change_accuracy": round(
            0.5
            * (
                true_positive / positive_count if positive_count else 1.0
            )
            + 0.5
            * (
                true_negative / negative_count if negative_count else 1.0
            ),
            6,
        ),
        "next_class_accuracy": round(
            float(torch.mean((predicted_class == observed_class).float())), 6
        ),
        "next_class_macro_f1": round(
            _macro_f1(predicted_class, observed_class), 6
        ),
        "observed_changed_count": int(torch.count_nonzero(observed_change)),
        "predicted_changed_count": int(torch.count_nonzero(predicted_change)),
    }
    if change_probability is not None:
        result["change_brier"] = round(
            float(
                torch.mean(
                    (change_probability - observed_change.float()).square()
                )
            ),
            6,
        )
    if predicted_destination is not None:
        changed_count = int(torch.count_nonzero(observed_change))
        result["changed_destination_accuracy"] = (
            round(
                float(
                    torch.mean(
                        (
                            predicted_destination[observed_change]
                            == observed_class[observed_change]
                        ).float()
                    )
                ),
                6,
            )
            if changed_count
            else 1.0
        )
        result["changed_destination_macro_f1"] = (
            round(
                _macro_f1(
                    predicted_destination[observed_change],
                    observed_class[observed_change],
                ),
                6,
            )
            if changed_count
            else 1.0
        )
    return result


def _binary_f1(predicted: torch.Tensor, observed: torch.Tensor) -> float:
    true_positive = torch.sum(predicted & observed).item()
    false_positive = torch.sum(predicted & ~observed).item()
    false_negative = torch.sum(~predicted & observed).item()
    denominator = 2 * true_positive + false_positive + false_negative
    return 2 * true_positive / denominator if denominator else 1.0


def _macro_f1(predicted: torch.Tensor, observed: torch.Tensor) -> float:
    scores = []
    for class_index in range(TWM_CLASS_COUNT):
        predicted_class = predicted == class_index
        observed_class = observed == class_index
        true_positive = torch.sum(predicted_class & observed_class).item()
        false_positive = torch.sum(predicted_class & ~observed_class).item()
        false_negative = torch.sum(~predicted_class & observed_class).item()
        denominator = 2 * true_positive + false_positive + false_negative
        if denominator:
            scores.append(2 * true_positive / denominator)
    return sum(scores) / len(scores) if scores else 1.0
