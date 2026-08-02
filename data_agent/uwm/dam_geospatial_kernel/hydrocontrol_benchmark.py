"""Frozen real-action HydroControl evaluation for DAM-GK H1 and H5."""

from __future__ import annotations

import copy
import random
from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.nn import functional

from data_agent.uwm.geospatial_kernel import (
    GEOSPATIAL_KERNEL_RUNTIME_SCHEMA,
    GeospatialKernelRuntime,
    KernelAction,
    build_kernel_capability_report,
    summarize_kernel_steps,
)

from .contracts import DAMGKBatch, DAMGKConfig
from .hydrocontrol_adapter import (
    HYDROCONTROL_ELIGIBLE_HORIZONS,
    HydroControlDAMGKDataset,
    build_hydrocontrol_dam_gk_dataset,
    inverse_signed_log_state,
    select_hydrocontrol_samples,
)
from .model import DynamicActionConditionedMultiscaleKernel
from .runtime_adapter import (
    DAM_GK_RUNTIME_ADAPTER,
    DAMGKRuntimeAdapter,
    dam_gk_runtime_state,
)

HYDROCONTROL_DAM_GK_BENCHMARK_SCHEMA = "gwm.dam_gk.hydrocontrol_h1_h5_benchmark.v1"


def run_hydrocontrol_dam_gk_benchmark(
    panel: pd.DataFrame,
    *,
    horizons: Iterable[int] = HYDROCONTROL_ELIGIBLE_HORIZONS,
    seed: int = 31,
    epochs: int = 12,
    batch_size: int = 4096,
    learning_rate: float = 0.003,
    weight_decay: float = 0.0001,
) -> dict[str, Any]:
    _seed_everything(seed)
    systems = sorted(panel["system_id"].astype(str).unique())
    if len(systems) < 3:
        raise ValueError("at_least_three_hydrocontrol_systems_required")
    horizon_reports = []
    for horizon in horizons:
        folds = []
        for held_out in systems:
            train_systems = [system for system in systems if system != held_out]
            train = build_hydrocontrol_dam_gk_dataset(
                panel,
                horizon_hours=int(horizon),
                systems=train_systems,
                temporal_split="train",
                target_before="2025-01-01",
            )
            test = build_hydrocontrol_dam_gk_dataset(
                panel,
                horizon_hours=int(horizon),
                systems=[held_out],
                temporal_split="development_test",
                target_before="2026-01-01",
            )
            fold_seed = seed + int(horizon) * 100 + systems.index(held_out)
            folds.append(
                _run_fold(
                    train=train,
                    test=test,
                    held_out=held_out,
                    train_systems=train_systems,
                    seed=fold_seed,
                    epochs=epochs,
                    batch_size=batch_size,
                    learning_rate=learning_rate,
                    weight_decay=weight_decay,
                )
            )
        horizon_reports.append(_summarize_horizon(int(horizon), folds))
    return _build_report(
        horizon_reports,
        seed=seed,
        epochs=epochs,
        batch_size=batch_size,
        learning_rate=learning_rate,
        weight_decay=weight_decay,
    )


def _run_fold(
    *,
    train: HydroControlDAMGKDataset,
    test: HydroControlDAMGKDataset,
    held_out: str,
    train_systems: list[str],
    seed: int,
    epochs: int,
    batch_size: int,
    learning_rate: float,
    weight_decay: float,
) -> dict[str, Any]:
    context_dim = int(train.batch.node_context.shape[1])
    if test.batch.node_context.shape[1] != context_dim:
        raise ValueError("hydrocontrol_context_dim_mismatch")
    full_model = _new_model(use_action_conditioning=True, context_dim=context_dim)
    initial_state = copy.deepcopy(full_model.state_dict())
    no_action_model = _new_model(use_action_conditioning=False, context_dim=context_dim)
    no_action_model.load_state_dict(initial_state)
    _train_model(
        full_model,
        train,
        seed=seed,
        epochs=epochs,
        batch_size=batch_size,
        learning_rate=learning_rate,
        weight_decay=weight_decay,
    )
    _train_model(
        no_action_model,
        train,
        seed=seed,
        epochs=epochs,
        batch_size=batch_size,
        learning_rate=learning_rate,
        weight_decay=weight_decay,
    )

    full_prediction, observed_gate, full_runtime = _predict(
        full_model,
        test,
        batch_size,
        parameter_ref=f"in-memory-trained:fold-seed-{seed}:full",
    )
    no_action_prediction, _, no_action_runtime = _predict(
        no_action_model,
        test,
        batch_size,
        parameter_ref=f"in-memory-trained:fold-seed-{seed}:no-action-model",
    )
    zero_action_prediction, zero_gate, zero_action_runtime = _predict(
        full_model,
        _with_action_control(test, "zero", seed),
        batch_size,
        parameter_ref=f"in-memory-trained:fold-seed-{seed}:zero-action-control",
    )
    shuffled_prediction, _, shuffled_runtime = _predict(
        full_model,
        _with_action_control(test, "shuffle", seed),
        batch_size,
        parameter_ref=f"in-memory-trained:fold-seed-{seed}:action-shuffle-control",
    )
    shifted_prediction, _, shifted_runtime = _predict(
        full_model,
        _with_action_control(test, "shift_168", seed),
        batch_size,
        parameter_ref=f"in-memory-trained:fold-seed-{seed}:time-shift-control",
    )
    statistical = _statistical_predictions(train, test)

    predictions = {
        "dam_gk": full_prediction,
        "dam_gk_no_action": no_action_prediction,
        "action_shuffle": shuffled_prediction,
        "temporal_shift_168": shifted_prediction,
        **statistical,
    }
    metrics = {
        name: _flow_metrics(test.target_flow_cfs, prediction)
        for name, prediction in predictions.items()
    }
    return {
        "held_out_system": held_out,
        "train_systems": train_systems,
        "train_sample_count": train.sample_count,
        "test_sample_count": test.sample_count,
        "seed": seed,
        "kernel_runtime_adapter": DAM_GK_RUNTIME_ADAPTER.adapter_id,
        "kernel_runtime_execution": {
            "observed_action": full_runtime,
            "no_action_model": no_action_runtime,
            "zero_action_control": zero_action_runtime,
            "action_shuffle_control": shuffled_runtime,
            "time_shift_control": shifted_runtime,
        },
        "metrics": metrics,
        "mechanism_sensitivity": {
            "mean_absolute_edge_gate_change_observed_vs_zero_action": round(
                float(torch.mean(torch.abs(observed_gate - zero_gate))), 9
            ),
            "mean_absolute_prediction_state_change_observed_vs_zero_action": round(
                float(
                    torch.mean(
                        torch.abs(
                            _flow_to_state(full_prediction) - _flow_to_state(zero_action_prediction)
                        )
                    )
                ),
                9,
            ),
        },
    }


def _new_model(
    *, use_action_conditioning: bool, context_dim: int = 2
) -> DynamicActionConditionedMultiscaleKernel:
    return DynamicActionConditionedMultiscaleKernel(
        DAMGKConfig(
            node_state_dim=2,
            action_dim=2,
            edge_feature_dim=1,
            relation_type_count=1,
            context_dim=context_dim,
            hidden_dim=16,
            horizon=1,
            state_output_dim=1,
            mutable_state_dim=1,
            state_writeback_mode="additive",
            use_action_conditioning=use_action_conditioning,
        )
    )


def _train_model(
    model: nn.Module,
    dataset: HydroControlDAMGKDataset,
    *,
    seed: int,
    epochs: int,
    batch_size: int,
    learning_rate: float,
    weight_decay: float,
) -> None:
    generator = torch.Generator().manual_seed(seed)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    model.train()
    for _ in range(epochs):
        order = torch.randperm(dataset.sample_count, generator=generator)
        for start in range(0, dataset.sample_count, batch_size):
            sample = select_hydrocontrol_samples(dataset, order[start : start + batch_size])
            output = model(sample.batch)
            prediction = output.predicted_state[sample.target_node_index, 0, 0]
            loss = functional.mse_loss(prediction, sample.target_flow_state)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()


def _predict(
    model: DynamicActionConditionedMultiscaleKernel,
    dataset: HydroControlDAMGKDataset,
    batch_size: int,
    *,
    parameter_ref: str = "in-memory-trained:hydrocontrol-benchmark",
) -> tuple[torch.Tensor, torch.Tensor, dict[str, Any]]:
    predictions = []
    gates = []
    step_results = []
    runtime = GeospatialKernelRuntime(DAMGKRuntimeAdapter(model, parameter_ref=parameter_ref))
    for start in range(0, dataset.sample_count, batch_size):
        stop = min(start + batch_size, dataset.sample_count)
        indices = torch.arange(start, stop)
        sample = select_hydrocontrol_samples(dataset, indices)
        source_time = f"evaluation-batch-{start}-{stop}:source"
        target_time = f"evaluation-batch-{start}-{stop}:h{dataset.horizon_hours}"
        state = dam_gk_runtime_state(
            sample.batch,
            time_id=source_time,
            state_ref=f"{dataset.schema}:{dataset.horizon_hours}:{start}:{stop}",
        )
        action = KernelAction(
            action_id=f"hydrocontrol-action:{dataset.horizon_hours}:{start}:{stop}",
            domain=DAM_GK_RUNTIME_ADAPTER.domain,
            source_time=source_time,
            target_time=target_time,
            payload=sample.batch.node_action,
        )
        result = runtime.step(state=state, action=action, context=None)
        output = result.candidate.payload
        step_results.append(result)
        predictions.append(
            inverse_signed_log_state(output.predicted_state[sample.target_node_index, 0, 0]).clamp(
                min=0.0, max=1_000_000.0
            )
        )
        gates.append(output.effective_edge_gate)
    return (
        torch.cat(predictions),
        torch.cat(gates),
        {
            "schema": "gwm.dam_gk.runtime_prediction.v1",
            "adapter_id": DAM_GK_RUNTIME_ADAPTER.adapter_id,
            "parameter_ref": parameter_ref,
            "batch_count": len(step_results),
            "execution_summary": summarize_kernel_steps(
                adapter=DAM_GK_RUNTIME_ADAPTER,
                expected_step_count=len(range(0, dataset.sample_count, batch_size)),
                steps=step_results,
            ),
            "steps": [result.audit() for result in step_results],
        },
    )


def _with_action_control(
    dataset: HydroControlDAMGKDataset, mode: str, seed: int
) -> HydroControlDAMGKDataset:
    batch = dataset.batch
    controlled_action = batch.node_action.clone()
    source_nodes = torch.arange(0, dataset.sample_count * 2, 2)
    source_action = controlled_action[source_nodes].clone()
    if mode == "zero":
        source_action.zero_()
    elif mode == "shuffle":
        permutation = torch.randperm(
            dataset.sample_count, generator=torch.Generator().manual_seed(seed)
        )
        source_action = source_action[permutation]
    elif mode == "shift_168":
        source_action = torch.roll(source_action, shifts=168, dims=0)
    else:
        raise ValueError("unsupported_action_control")
    controlled_action[source_nodes] = source_action
    controlled_batch = DAMGKBatch(
        node_state=batch.node_state,
        node_action=controlled_action,
        node_context=batch.node_context,
        node_context_by_step=batch.node_context_by_step,
        teacher_state_by_step=batch.teacher_state_by_step,
        edge_index=batch.edge_index,
        edge_features=batch.edge_features,
        edge_types=batch.edge_types,
        region_context=batch.region_context,
        edge_valid_mask=batch.edge_valid_mask,
    )
    return HydroControlDAMGKDataset(
        schema=dataset.schema,
        horizon_hours=dataset.horizon_hours,
        batch=controlled_batch,
        target_node_index=dataset.target_node_index,
        target_flow_state=dataset.target_flow_state,
        current_flow_cfs=dataset.current_flow_cfs,
        target_flow_cfs=dataset.target_flow_cfs,
        system_ids=dataset.system_ids,
        input_timestamps=dataset.input_timestamps,
        target_timestamps=dataset.target_timestamps,
        context_feature_names=dataset.context_feature_names,
        context_audit=dataset.context_audit,
    )


def _statistical_predictions(
    train: HydroControlDAMGKDataset,
    test: HydroControlDAMGKDataset,
) -> dict[str, torch.Tensor]:
    train_target = train.target_flow_state.numpy()
    test_batch = test.batch
    train_batch = train.batch
    train_source = torch.arange(0, train.sample_count * 2, 2)
    train_target_nodes = train.target_node_index
    test_source = torch.arange(0, test.sample_count * 2, 2)
    test_target_nodes = test.target_node_index
    target_only_train = np.column_stack(
        [
            np.ones(train.sample_count),
            train_batch.node_state[train_target_nodes, 0].numpy(),
            train_batch.node_context[train_target_nodes].numpy(),
        ]
    )
    target_only_test = np.column_stack(
        [
            np.ones(test.sample_count),
            test_batch.node_state[test_target_nodes, 0].numpy(),
            test_batch.node_context[test_target_nodes].numpy(),
        ]
    )
    action_train = np.column_stack(
        [target_only_train, train_batch.node_action[train_source].numpy()]
    )
    action_test = np.column_stack([target_only_test, test_batch.node_action[test_source].numpy()])
    target_only = _ridge_predict(target_only_train, train_target, target_only_test)
    action_no_graph = _ridge_predict(action_train, train_target, action_test)
    historical_mean_state = float(np.mean(train_target))
    return {
        "persistence": test.current_flow_cfs.clone(),
        "historical_mean": inverse_signed_log_state(
            torch.full((test.sample_count,), historical_mean_state)
        ),
        "target_only_ridge": inverse_signed_log_state(
            torch.tensor(target_only, dtype=torch.float32)
        ).clamp(min=0.0, max=1_000_000.0),
        "action_conditioned_no_graph_ridge": inverse_signed_log_state(
            torch.tensor(action_no_graph, dtype=torch.float32)
        ).clamp(min=0.0, max=1_000_000.0),
    }


def _ridge_predict(
    train_x: np.ndarray,
    train_y: np.ndarray,
    test_x: np.ndarray,
    penalty: float = 1e-4,
) -> np.ndarray:
    gram = train_x.T @ train_x
    regularizer = np.eye(gram.shape[0]) * penalty
    regularizer[0, 0] = 0.0
    coefficients = np.linalg.solve(gram + regularizer, train_x.T @ train_y)
    return test_x @ coefficients


def _flow_metrics(truth: torch.Tensor, prediction: torch.Tensor) -> dict[str, float]:
    truth_np = truth.numpy().astype(float)
    prediction_np = prediction.numpy().astype(float)
    error = prediction_np - truth_np
    scale = float(np.quantile(truth_np, 0.95) - np.quantile(truth_np, 0.05))
    if scale <= 0:
        raise ValueError("nonpositive_target_scale")
    return {
        "mae_cfs": round(float(np.mean(np.abs(error))), 6),
        "rmse_cfs": round(float(np.sqrt(np.mean(np.square(error)))), 6),
        "nmae_p95_p05": round(float(np.mean(np.abs(error))) / scale, 9),
    }


def _flow_to_state(flow: torch.Tensor) -> torch.Tensor:
    return torch.log1p(flow.clamp_min(0.0)) / 10.0


def _summarize_horizon(horizon: int, folds: list[dict[str, Any]]) -> dict[str, Any]:
    metric_names = tuple(folds[0]["metrics"])
    macro = {
        name: round(
            float(np.mean([fold["metrics"][name]["nmae_p95_p05"] for fold in folds])),
            9,
        )
        for name in metric_names
    }
    full = macro["dam_gk"]
    improved_over_no_action = sum(
        fold["metrics"]["dam_gk"]["nmae_p95_p05"]
        < fold["metrics"]["dam_gk_no_action"]["nmae_p95_p05"]
        for fold in folds
    )
    minimum_gate_change = min(
        fold["mechanism_sensitivity"]["mean_absolute_edge_gate_change_observed_vs_zero_action"]
        for fold in folds
    )
    minimum_prediction_change = min(
        fold["mechanism_sensitivity"][
            "mean_absolute_prediction_state_change_observed_vs_zero_action"
        ]
        for fold in folds
    )
    return {
        "horizon_hours": horizon,
        "folds": folds,
        "macro_nmae": macro,
        "checks": {
            "dam_gk_beats_no_action_macro": full < macro["dam_gk_no_action"],
            "dam_gk_beats_no_action_in_at_least_two_folds": (improved_over_no_action >= 2),
            "action_shuffle_degrades_macro": macro["action_shuffle"] > full,
            "temporal_shift_degrades_macro": macro["temporal_shift_168"] > full,
            "mechanism_gate_change_above_1e_4_in_all_folds": (minimum_gate_change > 1e-4),
            "mechanism_prediction_change_above_1e_4_in_all_folds": (
                minimum_prediction_change > 1e-4
            ),
        },
    }


def _build_report(
    horizons: list[dict[str, Any]],
    *,
    seed: int,
    epochs: int,
    batch_size: int,
    learning_rate: float,
    weight_decay: float,
) -> dict[str, Any]:
    predictive_pass_count = sum(
        row["checks"]["dam_gk_beats_no_action_macro"]
        and row["checks"]["dam_gk_beats_no_action_in_at_least_two_folds"]
        for row in horizons
    )
    action_control_pass_count = sum(
        row["checks"]["action_shuffle_degrades_macro"] for row in horizons
    )
    temporal_control_pass_count = sum(
        row["checks"]["temporal_shift_degrades_macro"] for row in horizons
    )
    mechanism_passed = all(
        row["checks"]["mechanism_gate_change_above_1e_4_in_all_folds"]
        and row["checks"]["mechanism_prediction_change_above_1e_4_in_all_folds"]
        for row in horizons
    )
    h1_supported = (
        mechanism_passed and predictive_pass_count >= 3 and action_control_pass_count >= 3
    )
    return {
        "schema": HYDROCONTROL_DAM_GK_BENCHMARK_SCHEMA,
        "protocol_id": "dam-gk-hydro-h1-h5-v0.1",
        "kernel_runtime_schema": GEOSPATIAL_KERNEL_RUNTIME_SCHEMA,
        "kernel_capabilities": build_kernel_capability_report([DAM_GK_RUNTIME_ADAPTER]),
        "training": {
            "seed": seed,
            "epochs": epochs,
            "batch_size": batch_size,
            "learning_rate": learning_rate,
            "weight_decay": weight_decay,
        },
        "horizons": horizons,
        "adjudication": {
            "h1": {
                "disposition": (
                    "supported" if h1_supported else "rejected_for_this_frozen_adapter_and_model"
                ),
                "mechanism_gate_passed": mechanism_passed,
                "predictive_horizon_pass_count": predictive_pass_count,
                "required_predictive_horizon_pass_count": 3,
                "action_control_horizon_pass_count": action_control_pass_count,
                "required_action_control_horizon_pass_count": 3,
            },
            "h5_action_time_partial": {
                "action_control_horizon_pass_count": action_control_pass_count,
                "time_control_horizon_pass_count": temporal_control_pass_count,
                "required_each": 3,
                "passed": action_control_pass_count >= 3 and temporal_control_pass_count >= 3,
            },
        },
        "claim_boundary": {
            "real_executed_actions_used": True,
            "internal_retrospective_research": True,
            "identified_causal_release_effect": False,
            "prospective_operational_forecast": False,
            "public_benchmark_activated": False,
            "h2_h3_h6_evaluated": False,
            "shared_runtime_contract_executed": True,
        },
    }


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
