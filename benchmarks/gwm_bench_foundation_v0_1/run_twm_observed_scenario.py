#!/usr/bin/env python3
"""Run the TWM land-transition candidate on the frozen OBSERVED-O1 bundle."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from torch.nn import functional as functional


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.gwm_bench_foundation_v0_1.observed_evaluator import (
    KEY_COLUMNS,
    PROBABILITY_COLUMNS,
    evaluate_observed_submission,
)
from benchmarks.gwm_bench_foundation_v0_1.build_baselines_and_controls import (
    _fixed_adjacency_probabilities,
    _history_only_probabilities,
    _one_step_probabilities,
)
from data_agent.uwm.dam_geospatial_kernel.contracts import DAMGKBatch
from data_agent.uwm.dam_geospatial_kernel.twm_adapter import (
    TWM_CLASS_COUNT,
    TWM_REGION_CONTEXT_DIM,
    TWM_RELATION_TYPES,
    WEB_MERCATOR_HALF_WORLD_METERS,
    _build_region_descriptor,
    _transform_nightlight,
    _transform_physical_drivers,
)
from data_agent.uwm.dam_geospatial_kernel.twm_sequence_adapter import (
    TWMDAMGKSequence,
)
from data_agent.uwm.dam_geospatial_kernel.twm_sequence_benchmark import (
    _fit_model,
    _kernel_config,
    _sequence_loss,
    _stack_sequences,
)
from data_agent.uwm.dam_geospatial_kernel.twm_transition_head import (
    TWMLandTransitionModel,
)


BENCHMARK_ROOT = Path(__file__).resolve().parent
DEFAULT_BUNDLE_ROOT = BENCHMARK_ROOT / "development"
DEFAULT_OUTPUT_ROOT = DEFAULT_BUNDLE_ROOT / "twm_scenario"
CONTRACT_PATH = BENCHMARK_ROOT / "benchmark_contract.json"
TARGET_YEARS = (2021, 2022, 2023)
TRAIN_YEARS = (2017, 2018, 2019, 2020)
CONTEXT_DIM = 12
SAMPLE_STRIDE = 24
COARSE_BLOCK_SIZE = 3
EDGE_DISTANCE_METERS = 2400.0
CALIBRATION_COARSE_OFFSETS = tuple(np.arange(-1.0, 4.01, 0.5).tolist())
TRAINING_OBJECTIVES = {"legacy_change_focal", "final_distribution"}
KERNEL_VARIANTS = {"full", "fixed_topology", "no_lag", "fixed_topology_no_lag"}
PROBABILITY_BLEND_MODES = {
    "none",
    "validation_selected_prior",
    "validation_selected_fixed_adjacency",
}
PRIOR_BLEND_WEIGHTS = tuple(np.arange(0.0, 1.001, 0.05).tolist())
REGULARIZED_PRIOR_BLEND_WEIGHTS = tuple(np.arange(0.5, 1.001, 0.05).tolist())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _training_region_wide(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert the bundle's long training history to the inference layout."""

    frame = frame.sort_values(["node_id", "year"], kind="mergesort")
    for _, group in frame.groupby("node_id", sort=False):
        if group["year"].tolist() != list(TRAIN_YEARS):
            raise ValueError("training_node_must_have_exact_2017_2020_history")
    stable_columns = [
        "region_id",
        "node_id",
        "raster_row",
        "raster_column",
        "x_3857",
        "y_3857",
        "srtm_elevation",
        "srtm_slope",
    ]
    stable = frame[stable_columns].drop_duplicates("node_id").set_index("node_id")
    if len(stable) != frame["node_id"].nunique():
        raise ValueError("training_node_static_fields_are_not_stable")
    classes = frame.pivot(index="node_id", columns="year", values="land_class")
    viirs = frame.pivot(index="node_id", columns="year", values="viirs_nightlight")
    lag_2016 = (
        frame[frame["year"] == TRAIN_YEARS[0]]
        .set_index("node_id")["viirs_nightlight_lag1"]
        .rename("viirs_nightlight_2016")
    )
    result = stable.join(lag_2016)
    for year in TRAIN_YEARS:
        result[f"land_class_{year}"] = classes[year]
        result[f"viirs_nightlight_{year}"] = viirs[year]
    result = result.reset_index()
    return result.sort_values("node_id", kind="mergesort").reset_index(drop=True)


def _neighbor_indices(
    *, node_ids: list[str], region_edges: pd.DataFrame
) -> list[list[int]]:
    node_index = {node_id: index for index, node_id in enumerate(node_ids)}
    neighbors: list[set[int]] = [set() for _ in node_ids]
    for edge in region_edges.itertuples(index=False):
        source = node_index.get(edge.source_node_id)
        target = node_index.get(edge.target_node_id)
        if source is not None and target is not None:
            neighbors[source].add(target)
    return [sorted(indices) for indices in neighbors]


def _fine_context(
    *,
    frame: pd.DataFrame,
    class_by_year: dict[int, torch.Tensor],
    viirs_by_year: dict[int, torch.Tensor],
    neighbors: list[list[int]],
    feature_year: int,
    clock_year: int,
) -> torch.Tensor:
    known_years = sorted(year for year in class_by_year if year <= feature_year)
    if not known_years or feature_year not in class_by_year:
        raise ValueError("context_feature_year_is_not_available")
    current_class = class_by_year[feature_year]
    history = torch.stack([class_by_year[year] for year in known_years], dim=1)
    if history.shape[1] == 1:
        recent_change = torch.zeros(len(frame), dtype=torch.float32)
        cumulative_change = torch.zeros_like(recent_change)
    else:
        transitions = (history[:, 1:] != history[:, :-1]).float()
        recent_change = transitions[:, -1]
        cumulative_change = transitions.mean(dim=1)

    temporal_rows = []
    for node_index, adjacent in enumerate(neighbors):
        local_indices = [node_index, *adjacent]
        local_classes = current_class[local_indices]
        distribution = torch.bincount(
            local_classes, minlength=TWM_CLASS_COUNT
        ).float()
        distribution /= distribution.sum().clamp_min(1.0)
        entropy = -torch.sum(
            distribution * torch.log(distribution.clamp_min(1e-8))
        ) / np.log(TWM_CLASS_COUNT)
        neighbor_recent = (
            recent_change[adjacent].mean()
            if adjacent
            else recent_change[node_index]
        )
        same_class_share = torch.mean(
            (local_classes == current_class[node_index]).float()
        )
        temporal_rows.append(
            torch.stack(
                [
                    recent_change[node_index],
                    cumulative_change[node_index],
                    neighbor_recent,
                    entropy,
                    distribution[6],
                    same_class_share,
                ]
            )
        )
    temporal = torch.stack(temporal_rows)

    coordinates = torch.tensor(
        frame[["x_3857", "y_3857"]].to_numpy(dtype=np.float32)
    )
    base = torch.zeros((len(frame), 4), dtype=torch.float32)
    base[:, :2] = (
        coordinates / WEB_MERCATOR_HALF_WORLD_METERS
    ).clamp(-1.0, 1.0)
    base[:, 3] = (clock_year - 2017) / 10.0
    viirs_level = _transform_nightlight(viirs_by_year[feature_year])
    preceding_year = max(year for year in viirs_by_year if year < feature_year)
    viirs_lag_change = viirs_level - _transform_nightlight(
        viirs_by_year[preceding_year]
    )
    return torch.cat(
        [base, temporal, viirs_level[:, None], viirs_lag_change[:, None]], dim=1
    )


def _hierarchy(frame: pd.DataFrame) -> tuple[torch.Tensor, list[tuple[int, int]]]:
    coarse_keys = sorted(
        {
            (
                int(row) // (SAMPLE_STRIDE * COARSE_BLOCK_SIZE),
                int(column) // (SAMPLE_STRIDE * COARSE_BLOCK_SIZE),
            )
            for row, column in frame[["raster_row", "raster_column"]].itertuples(
                index=False, name=None
            )
        }
    )
    coarse_index = {key: index for index, key in enumerate(coarse_keys)}
    mapping = torch.zeros((len(coarse_keys), len(frame)), dtype=torch.float32)
    for fine_index, (row, column) in enumerate(
        frame[["raster_row", "raster_column"]].itertuples(index=False, name=None)
    ):
        key = (
            int(row) // (SAMPLE_STRIDE * COARSE_BLOCK_SIZE),
            int(column) // (SAMPLE_STRIDE * COARSE_BLOCK_SIZE),
        )
        mapping[coarse_index[key], fine_index] = 1.0
    return mapping, coarse_keys


def _graph(
    *,
    frame: pd.DataFrame,
    region_edges: pd.DataFrame,
    physical_drivers: torch.Tensor,
    fine_to_coarse: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    node_ids = frame["node_id"].tolist()
    node_index = {node_id: index for index, node_id in enumerate(node_ids)}
    coordinates = torch.tensor(
        frame[["x_3857", "y_3857"]].to_numpy(dtype=np.float32)
    )
    mass = fine_to_coarse.sum(dim=1, keepdim=True).clamp_min(1.0)
    coarse_coordinates = (fine_to_coarse / mass) @ coordinates
    all_coordinates = torch.cat([coordinates, coarse_coordinates], dim=0)
    fine_count = len(frame)
    edge_pairs: list[tuple[int, int]] = []
    edge_features: list[list[float]] = []
    edge_types: list[int] = []

    def append(source: int, target: int, relation_type: int, base: list[float]) -> None:
        displacement = (
            all_coordinates[target] - all_coordinates[source]
        ) / EDGE_DISTANCE_METERS
        edge_pairs.append((source, target))
        edge_features.append(
            base
            + [
                float(displacement[0]),
                float(displacement[1]),
                float(torch.linalg.vector_norm(displacement)),
            ]
        )
        edge_types.append(relation_type)

    for edge in region_edges.itertuples(index=False):
        source = node_index.get(edge.source_node_id)
        target = node_index.get(edge.target_node_id)
        if source is None or target is None:
            continue
        terrain_difference = float(
            torch.mean(torch.abs(physical_drivers[source] - physical_drivers[target]))
        )
        append(
            source,
            target,
            TWM_RELATION_TYPES["grid_adjacency"],
            [1.0, terrain_difference, 0.0, 1.0],
        )
    for fine_index in range(fine_count):
        coarse_index = int(torch.argmax(fine_to_coarse[:, fine_index])) + fine_count
        append(
            fine_index,
            coarse_index,
            TWM_RELATION_TYPES["fine_within_block"],
            [1.0, 0.0, 1.0, 1.0],
        )
        append(
            coarse_index,
            fine_index,
            TWM_RELATION_TYPES["block_contains_fine"],
            [1.0, 0.0, 1.0, 1.0],
        )
    if not edge_pairs:
        raise ValueError("region_graph_is_empty")
    return (
        torch.tensor(edge_pairs, dtype=torch.long).T.contiguous(),
        torch.tensor(edge_features, dtype=torch.float32),
        torch.tensor(edge_types, dtype=torch.long),
    )


def _build_region_sequence(
    *,
    frame: pd.DataFrame,
    region_edges: pd.DataFrame,
    initial_year: int,
    target_years: tuple[int, int, int],
    future_class_by_year: dict[int, torch.Tensor] | None,
) -> TWMDAMGKSequence:
    """Build one TWM sequence using only columns already present in the bundle."""

    frame = frame.sort_values("node_id", kind="mergesort").reset_index(drop=True)
    region_ids = frame["region_id"].drop_duplicates().tolist()
    if len(region_ids) != 1:
        raise ValueError("one_region_required_per_sequence")
    region_id = region_ids[0]
    class_by_year = {
        year: torch.tensor(frame[f"land_class_{year}"].to_numpy(), dtype=torch.long)
        for year in TRAIN_YEARS
    }
    viirs_by_year = {
        year: torch.tensor(
            frame[f"viirs_nightlight_{year}"].to_numpy(dtype=np.float32)
        )
        for year in range(2016, 2021)
    }
    node_ids = frame["node_id"].tolist()
    neighbors = _neighbor_indices(node_ids=node_ids, region_edges=region_edges)
    maximum_known_year = max(class_by_year)
    fine_context_steps = []
    for clock_year in range(initial_year, initial_year + len(target_years)):
        feature_year = min(clock_year, maximum_known_year)
        fine_context_steps.append(
            _fine_context(
                frame=frame,
                class_by_year=class_by_year,
                viirs_by_year=viirs_by_year,
                neighbors=neighbors,
                feature_year=feature_year,
                clock_year=clock_year,
            )
        )
    fine_context_by_step = torch.stack(fine_context_steps, dim=1)
    if fine_context_by_step.shape[-1] != CONTEXT_DIM:
        raise ValueError("foundation_twm_context_shape_mismatch")

    initial_class = class_by_year[initial_year]
    initial_one_hot = functional.one_hot(
        initial_class, num_classes=TWM_CLASS_COUNT
    ).float()
    raw_drivers = torch.tensor(
        np.column_stack(
            [
                frame["srtm_elevation"].to_numpy(dtype=np.float32),
                frame["srtm_slope"].to_numpy(dtype=np.float32),
                frame[f"viirs_nightlight_{initial_year}"].to_numpy(
                    dtype=np.float32
                ),
            ]
        ),
        dtype=torch.float32,
    )
    physical_drivers = _transform_physical_drivers(raw_drivers)
    fine_state = torch.cat([initial_one_hot, physical_drivers], dim=1)
    fine_to_coarse, _ = _hierarchy(frame)
    mass = fine_to_coarse.sum(dim=1, keepdim=True).clamp_min(1.0)
    aggregate = fine_to_coarse / mass
    coarse_state = aggregate @ fine_state
    node_state = torch.cat([fine_state, coarse_state], dim=0)
    coarse_context_by_step = torch.einsum(
        "cf,fhd->chd", aggregate, fine_context_by_step
    )
    coarse_context_by_step[:, :, 2] = 1.0
    node_context_by_step = torch.cat(
        [fine_context_by_step, coarse_context_by_step], dim=0
    )

    edge_index, edge_features, edge_types = _graph(
        frame=frame,
        region_edges=region_edges,
        physical_drivers=physical_drivers,
        fine_to_coarse=fine_to_coarse,
    )
    normalized_coordinates = torch.tensor(
        frame[["x_3857", "y_3857"]].to_numpy(dtype=np.float32)
    ) / WEB_MERCATOR_HALF_WORLD_METERS
    region_descriptor = _build_region_descriptor(
        current_one_hot=initial_one_hot,
        physical_drivers=physical_drivers,
        normalized_coordinates=normalized_coordinates,
    )
    if region_descriptor.shape != (TWM_REGION_CONTEXT_DIM,):
        raise ValueError("region_descriptor_shape_mismatch")
    region_context = region_descriptor.unsqueeze(0).repeat(node_state.shape[0], 1)

    if future_class_by_year is None:
        fine_future_class = initial_class[:, None].repeat(1, len(target_years))
    else:
        fine_future_class = torch.stack(
            [future_class_by_year[year] for year in target_years], dim=1
        )
    fine_future_state = functional.one_hot(
        fine_future_class, num_classes=TWM_CLASS_COUNT
    ).float()
    coarse_future_state = torch.einsum(
        "cf,fhd->chd", aggregate, fine_future_state
    )
    target_state = torch.cat([fine_future_state, coarse_future_state], dim=0)
    previous_state = torch.cat(
        [node_state[:, None, :TWM_CLASS_COUNT], target_state[:, :-1]], dim=1
    )
    target_delta = target_state - previous_state
    static_drivers = node_state[:, None, TWM_CLASS_COUNT:].repeat(
        1, len(target_years), 1
    )
    teacher_state_by_step = torch.cat([target_state, static_drivers], dim=-1)
    batch = DAMGKBatch(
        node_state=node_state,
        node_action=torch.zeros((node_state.shape[0], 1), dtype=torch.float32),
        node_context=node_context_by_step[:, 0],
        node_context_by_step=node_context_by_step,
        teacher_state_by_step=teacher_state_by_step,
        region_context=region_context,
        edge_index=edge_index,
        edge_features=edge_features,
        edge_types=edge_types,
        edge_valid_mask=None,
    )
    return TWMDAMGKSequence(
        batch=batch,
        target_delta=target_delta,
        target_state=target_state,
        initial_class=initial_class,
        future_class=fine_future_class,
        fine_to_coarse=fine_to_coarse,
        node_ids=node_ids,
        years=(initial_year, *target_years),
        metadata={
            "schema": "gwm_bench.foundation_twm_sequence.v1",
            "region_id": region_id,
            "fine_node_count": len(frame),
            "coarse_node_count": int(fine_to_coarse.shape[0]),
            "maximum_observed_input_year": maximum_known_year,
            "target_years": list(target_years),
            "future_observed_inputs_used": False,
            "post_origin_context_policy": "freeze_2020_observed_features_and_advance_known_clock",
            "action_tensor": "all_zero_observed_non_intervention_track",
        },
    )


def _train_sequences(
    *, fold_train: pd.DataFrame, edges: pd.DataFrame
) -> list[TWMDAMGKSequence]:
    sequences = []
    for region_id, region_frame in fold_train.groupby("region_id", sort=True):
        wide = _training_region_wide(region_frame)
        future = {
            year: torch.tensor(wide[f"land_class_{year}"].to_numpy(), dtype=torch.long)
            for year in TRAIN_YEARS[1:]
        }
        sequences.append(
            _build_region_sequence(
                frame=wide,
                region_edges=edges[edges["region_id"] == region_id],
                initial_year=TRAIN_YEARS[0],
                target_years=TRAIN_YEARS[1:],
                future_class_by_year=future,
            )
        )
    return sequences


def _inference_sequences(
    *, fold_inputs: pd.DataFrame, edges: pd.DataFrame
) -> list[TWMDAMGKSequence]:
    return [
        _build_region_sequence(
            frame=region_frame,
            region_edges=edges[edges["region_id"] == region_id],
            initial_year=2020,
            target_years=TARGET_YEARS,
            future_class_by_year=None,
        )
        for region_id, region_frame in fold_inputs.groupby("region_id", sort=True)
    ]


def _submission_rows(
    *,
    fold_index: int,
    sequences: list[TWMDAMGKSequence],
    probabilities: torch.Tensor,
) -> list[dict[str, Any]]:
    rows = []
    fine_offset = 0
    for sequence in sequences:
        fine_count = sequence.metadata["fine_node_count"]
        region_probability = probabilities[fine_offset : fine_offset + fine_count]
        fine_offset += fine_count
        for node_index, node_id in enumerate(sequence.node_ids):
            for horizon_index, target_year in enumerate(TARGET_YEARS):
                row = {
                    "fold_index": fold_index,
                    "region_id": sequence.metadata["region_id"],
                    "node_id": node_id,
                    "target_year": target_year,
                }
                values = region_probability[node_index, horizon_index].tolist()
                row.update(
                    {
                        column: float(values[class_index])
                        for class_index, column in enumerate(PROBABILITY_COLUMNS)
                    }
                )
                rows.append(row)
    if fine_offset != probabilities.shape[0]:
        raise ValueError("prediction_node_count_mismatch")
    return rows


def _roll_calibrated_probabilities(
    *, output, fine_node_mask: torch.Tensor, initial_class: torch.Tensor, offsets: tuple[float, float, float]
) -> torch.Tensor:
    """Apply validation-selected change priors without future observed inputs."""

    change_logit = output.change_logit[fine_node_mask]
    destination = torch.softmax(
        output.destination_logits[fine_node_mask], dim=-1
    )
    current = functional.one_hot(
        initial_class, num_classes=TWM_CLASS_COUNT
    ).float()
    probabilities = []
    for horizon_index, offset in enumerate(offsets):
        change_probability = torch.sigmoid(
            change_logit[:, horizon_index] - offset
        ).unsqueeze(-1)
        current = (
            (1.0 - change_probability) * current
            + change_probability * destination[:, horizon_index]
        )
        current = current / current.sum(dim=-1, keepdim=True).clamp_min(1e-12)
        probabilities.append(current)
    return torch.stack(probabilities, dim=1)


def _validation_targets(
    *,
    fold_index: int,
    sequences: list[TWMDAMGKSequence],
    validation_labels: pd.DataFrame,
) -> torch.Tensor:
    label_lookup = {
        (row.region_id, row.node_id, int(row.target_year)): int(row.target_class)
        for row in validation_labels.itertuples(index=False)
        if int(row.fold_index) == fold_index
    }
    targets = []
    for sequence in sequences:
        for node_id in sequence.node_ids:
            targets.append(
                [
                    label_lookup[
                        (sequence.metadata["region_id"], node_id, target_year)
                    ]
                    for target_year in TARGET_YEARS
                ]
            )
    if len(label_lookup) != len(targets) * len(TARGET_YEARS):
        raise ValueError("validation_label_keys_do_not_match_inference_nodes")
    return torch.tensor(targets, dtype=torch.long)


def _prior_probability_tensor(
    *,
    fold_index: int,
    sequences: list[TWMDAMGKSequence],
    probability_by_key: dict[tuple, np.ndarray],
) -> torch.Tensor:
    rows = []
    for sequence in sequences:
        region_id = sequence.metadata["region_id"]
        for node_id in sequence.node_ids:
            rows.append(
                [
                    probability_by_key[
                        (fold_index, region_id, node_id, target_year)
                    ]
                    for target_year in TARGET_YEARS
                ]
            )
    probability = torch.tensor(np.asarray(rows), dtype=torch.float32)
    if probability.ndim != 3 or probability.shape[-1] != TWM_CLASS_COUNT:
        raise ValueError("prior_probability_shape_mismatch")
    return probability


def _binary_f1_numpy(predicted: np.ndarray, observed: np.ndarray) -> float:
    true_positive = int(np.sum(predicted & observed))
    false_positive = int(np.sum(predicted & ~observed))
    false_negative = int(np.sum(~predicted & observed))
    denominator = 2 * true_positive + false_positive + false_negative
    return 2 * true_positive / denominator if denominator else 1.0


def _macro_f1_numpy(predicted: np.ndarray, observed: np.ndarray) -> float:
    scores = []
    for class_index in sorted(set(predicted.tolist()) | set(observed.tolist())):
        predicted_class = predicted == class_index
        observed_class = observed == class_index
        true_positive = int(np.sum(predicted_class & observed_class))
        false_positive = int(np.sum(predicted_class & ~observed_class))
        false_negative = int(np.sum(~predicted_class & observed_class))
        denominator = 2 * true_positive + false_positive + false_negative
        if denominator:
            scores.append(2 * true_positive / denominator)
    return float(np.mean(scores)) if scores else 1.0


def _selection_metrics(
    *,
    probabilities: torch.Tensor,
    initial_class: torch.Tensor,
    target_class: torch.Tensor,
) -> dict[str, Any]:
    probability = probabilities.detach().cpu().numpy().astype(np.float64)
    predicted_class = np.argmax(probability, axis=-1).astype(np.int64)
    initial = initial_class.detach().cpu().numpy().astype(np.int64)
    observed = target_class.detach().cpu().numpy().astype(np.int64)
    predicted_previous = initial.copy()
    observed_previous = initial.copy()
    change_f1 = []
    predicted_change_count = 0
    observed_change_count = 0
    for horizon_index in range(len(TARGET_YEARS)):
        predicted_change = predicted_class[:, horizon_index] != predicted_previous
        observed_change = observed[:, horizon_index] != observed_previous
        change_f1.append(_binary_f1_numpy(predicted_change, observed_change))
        predicted_change_count += int(predicted_change.sum())
        observed_change_count += int(observed_change.sum())
        predicted_previous = predicted_class[:, horizon_index]
        observed_previous = observed[:, horizon_index]
    targets = np.eye(TWM_CLASS_COUNT, dtype=np.float64)[observed]
    return {
        "mean_horizon_change_f1": float(np.mean(change_f1)),
        "change_f1_by_horizon": change_f1,
        "overall_class_macro_f1": _macro_f1_numpy(
            predicted_class.reshape(-1), observed.reshape(-1)
        ),
        "multiclass_brier_score": float(
            np.mean(np.sum(np.square(probability - targets), axis=-1))
        ),
        "predicted_change_count": predicted_change_count,
        "observed_change_count": observed_change_count,
    }


def _calibration_rank(
    metrics: dict[str, Any], offsets: tuple[float, float, float]
) -> tuple[float, float, float, float, float]:
    return (
        round(metrics["mean_horizon_change_f1"], 12),
        round(metrics["overall_class_macro_f1"], 12),
        -round(metrics["multiclass_brier_score"], 12),
        -abs(
            metrics["predicted_change_count"] - metrics["observed_change_count"]
        ),
        -sum(abs(offset) for offset in offsets),
    )


def _select_change_offsets(
    *,
    output,
    fine_node_mask: torch.Tensor,
    initial_class: torch.Tensor,
    target_class: torch.Tensor,
    calibration_mode: str,
) -> tuple[tuple[float, float, float], dict[str, Any], dict[str, Any]]:
    if calibration_mode not in {"shared", "per_horizon"}:
        raise ValueError("unsupported_validation_calibration_mode")
    raw_offsets = (0.0, 0.0, 0.0)
    raw_probability = _roll_calibrated_probabilities(
        output=output,
        fine_node_mask=fine_node_mask,
        initial_class=initial_class,
        offsets=raw_offsets,
    )
    raw_metrics = _selection_metrics(
        probabilities=raw_probability,
        initial_class=initial_class,
        target_class=target_class,
    )
    best_offsets = raw_offsets
    best_metrics = raw_metrics

    def search(candidates: list[tuple[float, float, float]]) -> None:
        nonlocal best_offsets, best_metrics
        for offsets in candidates:
            probability = _roll_calibrated_probabilities(
                output=output,
                fine_node_mask=fine_node_mask,
                initial_class=initial_class,
                offsets=offsets,
            )
            metrics = _selection_metrics(
                probabilities=probability,
                initial_class=initial_class,
                target_class=target_class,
            )
            if _calibration_rank(metrics, offsets) > _calibration_rank(
                best_metrics, best_offsets
            ):
                best_offsets = offsets
                best_metrics = metrics

    if calibration_mode == "shared":
        search(
            [(offset, offset, offset) for offset in CALIBRATION_COARSE_OFFSETS]
        )
        fine_candidates = [
            round(float(value), 2)
            for value in np.arange(best_offsets[0] - 0.4, best_offsets[0] + 0.41, 0.1)
        ]
        search([(offset, offset, offset) for offset in fine_candidates])
    else:
        search(list(itertools.product(CALIBRATION_COARSE_OFFSETS, repeat=3)))
        fine_values = [
            tuple(
                round(float(value), 2)
                for value in np.arange(offset - 0.4, offset + 0.41, 0.1)
            )
            for offset in best_offsets
        ]
        search(list(itertools.product(*fine_values)))
    return best_offsets, raw_metrics, best_metrics


def _select_prior_blend(
    *,
    model_probability: torch.Tensor,
    prior_probability_by_name: dict[str, torch.Tensor],
    initial_class: torch.Tensor,
    target_class: torch.Tensor,
    twm_weights: tuple[float, ...] = PRIOR_BLEND_WEIGHTS,
) -> tuple[dict[str, Any], torch.Tensor]:
    best_selection = {
        "prior": None,
        "twm_weight": 1.0,
        "prior_weight": 0.0,
    }
    best_probability = model_probability
    best_metrics = _selection_metrics(
        probabilities=model_probability,
        initial_class=initial_class,
        target_class=target_class,
    )
    before = best_metrics
    for prior_name, prior_probability in prior_probability_by_name.items():
        for twm_weight in twm_weights:
            blended = (
                float(twm_weight) * model_probability
                + (1.0 - float(twm_weight)) * prior_probability
            )
            blended = blended / blended.sum(dim=-1, keepdim=True).clamp_min(1e-12)
            metrics = _selection_metrics(
                probabilities=blended,
                initial_class=initial_class,
                target_class=target_class,
            )
            selection = {
                "prior": prior_name,
                "twm_weight": round(float(twm_weight), 2),
                "prior_weight": round(1.0 - float(twm_weight), 2),
            }
            if _calibration_rank(metrics, (0.0, 0.0, 0.0)) > _calibration_rank(
                best_metrics, (0.0, 0.0, 0.0)
            ):
                best_selection = selection
                best_probability = blended
                best_metrics = metrics
    return {
        **best_selection,
        "before": before,
        "after": best_metrics,
    }, best_probability


def _final_distribution_loss(
    output, sequence, *, change_sample_weight: float
) -> torch.Tensor:
    """Optimize submitted probabilities with modest emphasis on real changes."""

    fine_probability = output.kernel_output.predicted_state[
        sequence.fine_node_mask, :, :TWM_CLASS_COUNT
    ].clamp_min(1e-8)
    target_class = sequence.future_class
    previous_class = torch.cat(
        [sequence.initial_class[:, None], target_class[:, :-1]], dim=1
    )
    changed = target_class != previous_class
    target_probability = torch.gather(
        fine_probability, dim=-1, index=target_class.unsqueeze(-1)
    ).squeeze(-1)
    sample_weight = torch.where(
        changed,
        target_probability.new_tensor(change_sample_weight),
        target_probability.new_tensor(1.0),
    )
    distribution_nll = torch.mean(sample_weight * -torch.log(target_probability))
    target_one_hot = functional.one_hot(
        target_class, num_classes=TWM_CLASS_COUNT
    ).float()
    brier_loss = torch.mean(
        sample_weight
        * torch.sum(torch.square(fine_probability - target_one_hot), dim=-1)
    )
    change_logit = output.change_logit[sequence.fine_node_mask]
    change_loss = functional.binary_cross_entropy_with_logits(
        change_logit, changed.float()
    )
    destination_logits = output.destination_logits[sequence.fine_node_mask]
    destination_loss = (
        functional.cross_entropy(destination_logits[changed], target_class[changed])
        if torch.any(changed)
        else destination_logits.sum() * 0.0
    )
    delta_loss = functional.smooth_l1_loss(
        output.kernel_output.state_delta_mean, sequence.target_delta
    )
    return (
        distribution_nll
        + 0.10 * brier_loss
        + 0.25 * change_loss
        + 0.25 * destination_loss
        + 0.02 * delta_loss
    )


def _fit_foundation_model(
    *,
    train,
    state_writeback_mode: str,
    seed: int,
    epochs: int,
    training_objective: str,
    change_sample_weight: float,
    kernel_variant: str,
):
    if training_objective not in TRAINING_OBJECTIVES:
        raise ValueError("unsupported_twm_training_objective")
    if kernel_variant not in KERNEL_VARIANTS:
        raise ValueError("unsupported_twm_kernel_variant")
    if training_objective == "legacy_change_focal" and kernel_variant == "full":
        return _fit_model(
            train=train,
            state_writeback_mode=state_writeback_mode,
            seed=seed,
            epochs=epochs,
        )
    if change_sample_weight < 1.0:
        raise ValueError("change_sample_weight_must_be_at_least_one")
    torch.manual_seed(seed)
    config = _kernel_config(
        state_writeback_mode=state_writeback_mode,
        context_dim=train.batch.node_context.shape[1],
    )
    if kernel_variant in {"fixed_topology", "fixed_topology_no_lag"}:
        config = replace(config, use_topology_rewrite=False)
    if kernel_variant in {"no_lag", "fixed_topology_no_lag"}:
        config = replace(config, use_lag_structure=False)
    model = TWMLandTransitionModel(config)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.003, weight_decay=2e-4)
    for _ in range(epochs):
        model.train()
        optimizer.zero_grad()
        output = model(train.batch)
        loss = (
            _sequence_loss(output, train)
            if training_objective == "legacy_change_focal"
            else _final_distribution_loss(
                output, train, change_sample_weight=change_sample_weight
            )
        )
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optimizer.step()
    return model


def _run_fold(
    *,
    fold_index: int,
    train: pd.DataFrame,
    inputs: pd.DataFrame,
    edges: pd.DataFrame,
    fold: dict[str, Any],
    seed: int,
    epochs: int,
    validation_labels: pd.DataFrame | None = None,
    calibration_mode: str = "none",
    training_objective: str = "legacy_change_focal",
    change_sample_weight: float = 3.0,
    probability_blend_mode: str = "none",
    prior_probability_by_name: dict[str, dict[tuple, np.ndarray]] | None = None,
    kernel_variant: str = "full",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if calibration_mode not in {"none", "shared", "per_horizon"}:
        raise ValueError("unsupported_validation_calibration_mode")
    if training_objective not in TRAINING_OBJECTIVES:
        raise ValueError("unsupported_twm_training_objective")
    if probability_blend_mode not in PROBABILITY_BLEND_MODES:
        raise ValueError("unsupported_probability_blend_mode")
    if kernel_variant not in KERNEL_VARIANTS:
        raise ValueError("unsupported_twm_kernel_variant")
    fold_train = train[train["fold_index"] == fold_index]
    fold_test = inputs[
        (inputs["fold_index"] == fold_index) & (inputs["split"] == "test")
    ]
    fold_validation = inputs[
        (inputs["fold_index"] == fold_index) & (inputs["split"] == "validation")
    ]
    if set(fold_train["region_id"]) != set(fold["training_regions"]):
        raise ValueError("training_regions_do_not_match_frozen_fold")
    if set(fold_test["region_id"]) != set(fold["test_regions"]):
        raise ValueError("test_regions_do_not_match_frozen_fold")
    train_sequences = _train_sequences(fold_train=fold_train, edges=edges)
    test_sequences = _inference_sequences(fold_inputs=fold_test, edges=edges)
    stacked_train = _stack_sequences(train_sequences)
    stacked_test = _stack_sequences(test_sequences)
    model = _fit_foundation_model(
        train=stacked_train,
        state_writeback_mode="categorical_mixture",
        seed=seed,
        epochs=epochs,
        training_objective=training_objective,
        change_sample_weight=change_sample_weight,
        kernel_variant=kernel_variant,
    )
    model.eval()
    selected_offsets = (0.0, 0.0, 0.0)
    validation_calibration = None
    validation_prior_blend = None
    with torch.no_grad():
        if calibration_mode != "none" or probability_blend_mode != "none":
            if validation_labels is None:
                raise ValueError("validation_labels_required_for_model_selection")
            validation_sequences = _inference_sequences(
                fold_inputs=fold_validation, edges=edges
            )
            stacked_validation = _stack_sequences(validation_sequences)
            validation_output = model(stacked_validation.batch)
            validation_target = _validation_targets(
                fold_index=fold_index,
                sequences=validation_sequences,
                validation_labels=validation_labels,
            )
        if calibration_mode != "none":
            selected_offsets, before, after = _select_change_offsets(
                output=validation_output,
                fine_node_mask=stacked_validation.fine_node_mask,
                initial_class=stacked_validation.initial_class,
                target_class=validation_target,
                calibration_mode=calibration_mode,
            )
            validation_calibration = {
                "mode": calibration_mode,
                "selected_logit_offsets_by_horizon": list(selected_offsets),
                "before": before,
                "after": after,
            }
        if probability_blend_mode != "none":
            if prior_probability_by_name is None:
                raise ValueError("prior_probabilities_required_for_blending")
            validation_model_probability = _roll_calibrated_probabilities(
                output=validation_output,
                fine_node_mask=stacked_validation.fine_node_mask,
                initial_class=stacked_validation.initial_class,
                offsets=selected_offsets,
            )
            validation_priors = {
                name: _prior_probability_tensor(
                    fold_index=fold_index,
                    sequences=validation_sequences,
                    probability_by_key=probability_by_key,
                )
                for name, probability_by_key in prior_probability_by_name.items()
            }
            validation_prior_blend, _ = _select_prior_blend(
                model_probability=validation_model_probability,
                prior_probability_by_name=validation_priors,
                initial_class=stacked_validation.initial_class,
                target_class=validation_target,
                twm_weights=(
                    REGULARIZED_PRIOR_BLEND_WEIGHTS
                    if probability_blend_mode
                    == "validation_selected_fixed_adjacency"
                    else PRIOR_BLEND_WEIGHTS
                ),
            )
        output = model(stacked_test.batch)
        probability = _roll_calibrated_probabilities(
            output=output,
            fine_node_mask=stacked_test.fine_node_mask,
            initial_class=stacked_test.initial_class,
            offsets=selected_offsets,
        )
        if validation_prior_blend is not None and validation_prior_blend["prior"]:
            prior_name = validation_prior_blend["prior"]
            test_prior = _prior_probability_tensor(
                fold_index=fold_index,
                sequences=test_sequences,
                probability_by_key=prior_probability_by_name[prior_name],
            )
            twm_weight = validation_prior_blend["twm_weight"]
            probability = (
                twm_weight * probability + (1.0 - twm_weight) * test_prior
            )
            probability = probability / probability.sum(
                dim=-1, keepdim=True
            ).clamp_min(1e-12)
    rows = _submission_rows(
        fold_index=fold_index,
        sequences=test_sequences,
        probabilities=probability,
    )
    return rows, {
        "fold_index": fold_index,
        "seed": seed,
        "epochs": epochs,
        "training_objective": training_objective,
        "change_sample_weight": change_sample_weight,
        "kernel_variant": kernel_variant,
        "training_regions": fold["training_regions"],
        "validation_regions": fold["validation_regions"],
        "validation_region_use": (
            "probability_model_selection"
            if calibration_mode != "none" or probability_blend_mode != "none"
            else "reserved_not_used"
        ),
        "test_regions": fold["test_regions"],
        "training_fine_node_count": int(stacked_train.fine_node_mask.sum()),
        "test_fine_node_count": int(stacked_test.fine_node_mask.sum()),
        "test_prediction_row_count": len(rows),
        "future_observed_inputs_used": False,
        "test_labels_loaded_before_prediction_commit": False,
        "validation_calibration": validation_calibration,
        "validation_prior_blend": validation_prior_blend,
    }


def _write_submission(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(path)


def run_twm_observed_scenario(
    *,
    bundle_root: Path = DEFAULT_BUNDLE_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    seed: int = 31,
    epochs: int = 80,
    calibration_mode: str = "none",
    training_objective: str = "legacy_change_focal",
    change_sample_weight: float = 3.0,
    probability_blend_mode: str = "none",
    kernel_variant: str = "full",
) -> dict[str, Any]:
    if epochs <= 0:
        raise ValueError("epochs_must_be_positive")
    if calibration_mode not in {"none", "shared", "per_horizon"}:
        raise ValueError("unsupported_validation_calibration_mode")
    if training_objective not in TRAINING_OBJECTIVES:
        raise ValueError("unsupported_twm_training_objective")
    if probability_blend_mode not in PROBABILITY_BLEND_MODES:
        raise ValueError("unsupported_probability_blend_mode")
    if kernel_variant not in KERNEL_VARIANTS:
        raise ValueError("unsupported_twm_kernel_variant")
    bundle_root = bundle_root.resolve()
    output_root = output_root.resolve()
    contract = _load_json(CONTRACT_PATH)
    folds_payload = _load_json(bundle_root / "region_folds.json")
    train = pd.read_parquet(bundle_root / "observed_train.parquet")
    inputs = pd.read_parquet(bundle_root / "observed_inputs.parquet")
    edges = pd.read_parquet(bundle_root / "observed_edges.parquet")
    validation_labels = None
    if calibration_mode != "none" or probability_blend_mode != "none":
        validation_labels = pd.read_parquet(
            bundle_root / "observed_labels.parquet",
            filters=[("split", "==", "validation")],
        )
        if set(validation_labels["split"]) != {"validation"}:
            raise ValueError("test_labels_must_not_be_loaded_for_model_selection")
    prior_probability_by_name = None
    if probability_blend_mode != "none":
        fixed_adjacency = _fixed_adjacency_probabilities(inputs, train, edges)
        if probability_blend_mode == "validation_selected_fixed_adjacency":
            prior_probability_by_name = {"fixed_adjacency": fixed_adjacency}
        else:
            prior_probability_by_name = {
                "history_only": _history_only_probabilities(inputs),
                "independent_one_step": _one_step_probabilities(inputs, train),
                "fixed_adjacency": fixed_adjacency,
            }
    # Test labels are deliberately not opened until the prediction file is committed.
    rows = []
    fold_reports = []
    for fold in folds_payload["folds"]:
        fold_rows, fold_report = _run_fold(
            fold_index=int(fold["fold_index"]),
            train=train,
            inputs=inputs,
            edges=edges,
            fold=fold,
            seed=seed,
            epochs=epochs,
            validation_labels=validation_labels,
            calibration_mode=calibration_mode,
            training_objective=training_objective,
            change_sample_weight=change_sample_weight,
            probability_blend_mode=probability_blend_mode,
            prior_probability_by_name=prior_probability_by_name,
            kernel_variant=kernel_variant,
        )
        rows.extend(fold_rows)
        fold_reports.append(fold_report)
        print(
            f"completed fold={fold['fold_index']} rows={len(fold_rows)}",
            flush=True,
        )

    submission = pd.DataFrame(rows, columns=KEY_COLUMNS + PROBABILITY_COLUMNS)
    submission = submission.sort_values(KEY_COLUMNS, kind="mergesort").reset_index(
        drop=True
    )
    if submission.duplicated(KEY_COLUMNS).any():
        raise ValueError("duplicate_twm_submission_keys")
    expected_rows = len(inputs[inputs["split"] == "test"]) * len(TARGET_YEARS)
    if len(submission) != expected_rows:
        raise ValueError("incomplete_twm_submission")
    values = submission[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64)
    if not np.isfinite(values).all() or not np.allclose(
        values.sum(axis=1), 1.0, atol=1e-6, rtol=0.0
    ):
        raise ValueError("invalid_twm_submission_probabilities")

    output_root.mkdir(parents=True, exist_ok=True)
    submission_path = output_root / "twm_observed_submission.parquet"
    _write_submission(submission, submission_path)
    committed_sha256 = _sha256(submission_path)

    evaluation = evaluate_observed_submission(
        submission_path=submission_path,
        labels_path=bundle_root / "observed_labels.parquet",
    )
    evaluation_path = output_root / "twm_observed_evaluation.json"
    evaluation_path.write_text(
        json.dumps(evaluation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    baseline_report = _load_json(bundle_root / "baselines/baseline_report.json")
    baseline_primary = {
        name: report["primary_metric"]["value"]
        for name, report in baseline_report["observed_baselines"].items()
    }
    candidate_primary = evaluation["primary_metric"]["value"]
    report = {
        "schema": "gwm_bench.foundation_twm_observed_scenario.v1",
        "benchmark_id": contract["benchmark_id"],
        "track_id": "OBSERVED-O1",
        "status": "scenario_executed_and_officially_scored",
        "candidate": {
            "name": "TWM DAM-GK recursive land-transition candidate",
            "state_writeback_mode": "categorical_mixture",
            "seed": seed,
            "epochs": epochs,
            "forecast_origin_year": 2020,
            "target_years": list(TARGET_YEARS),
            "validation_probability_calibration": calibration_mode,
            "training_objective": training_objective,
            "change_sample_weight": change_sample_weight,
            "probability_blend_mode": probability_blend_mode,
            "kernel_variant": kernel_variant,
        },
        "data_protocol": {
            "model_inputs_loaded_from_materialized_bundle_only": True,
            "training_years": list(TRAIN_YEARS),
            "post_2020_land_state_used_as_model_input": False,
            "post_2020_viirs_used_as_model_input": False,
            "period_mean_viirs_used": False,
            "test_labels_loaded_before_submission_commit": False,
            "validation_labels_used_for_model_selection": (
                calibration_mode != "none" or probability_blend_mode != "none"
            ),
            "submission_sha256_before_label_access": committed_sha256,
            "open_loop_state_writeback": "predicted_probability_state",
            "post_origin_context_policy": (
                "freeze_2020_observed features and advance known calendar clock"
            ),
        },
        "folds": fold_reports,
        "official_evaluation": evaluation,
        "baseline_primary_metrics": baseline_primary,
        "primary_comparison": {
            "candidate": candidate_primary,
            "beats_baseline": {
                name: candidate_primary > score
                for name, score in baseline_primary.items()
            },
        },
        "artifacts": {
            "submission": {
                "path": str(submission_path.relative_to(BENCHMARK_ROOT)),
                "sha256": committed_sha256,
                "row_count": len(submission),
            },
            "evaluation": {
                "path": str(evaluation_path.relative_to(BENCHMARK_ROOT)),
                "sha256": _sha256(evaluation_path),
            },
        },
        "claim_boundary": {
            "twm_land_state_scenario_executable": True,
            "observed_action_conditioning_supported": False,
            "policy_effect_supported": False,
            "operational_forecasting_supported": False,
            "general_twm_supported": False,
            "general_gwm_supported": False,
        },
    }
    report_path = output_root / "twm_observed_run_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "primary_metric": evaluation["primary_metric"],
                "overall_secondary_metrics": evaluation[
                    "overall_secondary_metrics"
                ],
                "beats_baseline": report["primary_comparison"]["beats_baseline"],
                "report": str(report_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, default=DEFAULT_BUNDLE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--seed", type=int, default=31)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument(
        "--calibration-mode",
        choices=["none", "shared", "per_horizon"],
        default="none",
    )
    parser.add_argument(
        "--training-objective",
        choices=sorted(TRAINING_OBJECTIVES),
        default="legacy_change_focal",
    )
    parser.add_argument("--change-sample-weight", type=float, default=3.0)
    parser.add_argument(
        "--probability-blend-mode",
        choices=sorted(PROBABILITY_BLEND_MODES),
        default="none",
    )
    parser.add_argument(
        "--kernel-variant",
        choices=sorted(KERNEL_VARIANTS),
        default="full",
    )
    args = parser.parse_args()
    run_twm_observed_scenario(
        bundle_root=args.bundle_root,
        output_root=args.output_root,
        seed=args.seed,
        epochs=args.epochs,
        calibration_mode=args.calibration_mode,
        training_objective=args.training_objective,
        change_sample_weight=args.change_sample_weight,
        probability_blend_mode=args.probability_blend_mode,
        kernel_variant=args.kernel_variant,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
