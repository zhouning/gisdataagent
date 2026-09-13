"""Consistent-node multi-year TWM sequences for recursive DAM-GK evaluation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import torch

from .contracts import DAMGKBatch
from .twm_adapter import (
    TWM_CLASS_COUNT,
    TWMDAMGKTransition,
    _read_raster,
    _valid_class,
    _valid_continuous,
    build_twm_dynamic_world_transition,
)


TWM_SEQUENCE_ADAPTER_SCHEMA = "gwm.dam_gk.twm_dynamic_world_sequence.v1"
TWM_SEQUENCE_CONTEXT_DIM = 10
TWM_TEMPORAL_CONTEXT_FEATURES = [
    "changed_from_previous_year",
    "cumulative_historical_change_rate",
    "neighbor_recent_change_rate",
    "neighbor_class_entropy",
    "neighbor_built_class_share",
    "same_class_neighbor_share",
]


@dataclass(frozen=True)
class TWMDAMGKSequence:
    batch: DAMGKBatch
    target_delta: torch.Tensor
    target_state: torch.Tensor
    initial_class: torch.Tensor
    future_class: torch.Tensor
    fine_to_coarse: torch.Tensor
    node_ids: list[str]
    years: tuple[int, ...]
    metadata: dict[str, Any]


def build_twm_dynamic_world_sequence(
    *,
    region_dir: Path,
    region_id: str,
    years: tuple[int, ...],
    sample_stride: int = 4,
    coarse_block_size: int = 4,
    terrain_similarity_scope: str = "global_configuration",
    use_temporal_history_context: bool = True,
) -> TWMDAMGKSequence:
    """Build recursive targets on one geographic node set across all years."""

    if len(years) < 2:
        raise ValueError("at_least_two_sequence_years_required")
    if any(next_year <= year for year, next_year in zip(years, years[1:])):
        raise ValueError("sequence_years_must_be_strictly_increasing")

    history_years = tuple(range(2017, max(years) + 1))
    selected_cells = _intersect_valid_cells(
        region_dir=region_dir,
        region_id=region_id,
        years=history_years,
        sample_stride=sample_stride,
    )
    transitions = [
        build_twm_dynamic_world_transition(
            region_dir=region_dir,
            region_id=region_id,
            current_year=current_year,
            next_year=next_year,
            sample_stride=sample_stride,
            coarse_block_size=coarse_block_size,
            terrain_similarity_scope=terrain_similarity_scope,
            selected_cells=selected_cells,
        )
        for current_year, next_year in zip(years, years[1:])
    ]
    _validate_consistent_sequence(transitions)

    initial = transitions[0]
    if use_temporal_history_context:
        context_by_step = _build_temporal_history_context(
            region_dir=region_dir,
            region_id=region_id,
            transitions=transitions,
            selected_cells=selected_cells,
            history_years=history_years,
            sample_stride=sample_stride,
        )
    else:
        context_by_step = torch.stack(
            [transition.batch.node_context for transition in transitions], dim=1
        )
    batch = replace(
        initial.batch,
        node_context=context_by_step[:, 0],
        node_context_by_step=context_by_step,
    )
    target_delta = torch.cat(
        [transition.target_delta for transition in transitions], dim=1
    )
    target_state = torch.stack(
        [
            transition.batch.node_state[:, :TWM_CLASS_COUNT]
            + transition.target_delta[:, 0]
            for transition in transitions
        ],
        dim=1,
    )
    teacher_state_by_step = torch.cat(
        [
            target_state,
            initial.batch.node_state[:, None, TWM_CLASS_COUNT:].expand(
                -1, len(transitions), -1
            ),
        ],
        dim=-1,
    )
    batch = replace(batch, teacher_state_by_step=teacher_state_by_step)
    future_class = torch.stack(
        [transition.next_class for transition in transitions], dim=1
    )
    return TWMDAMGKSequence(
        batch=batch,
        target_delta=target_delta,
        target_state=target_state,
        initial_class=initial.current_class,
        future_class=future_class,
        fine_to_coarse=initial.fine_to_coarse,
        node_ids=initial.node_ids,
        years=years,
        metadata={
            "schema": TWM_SEQUENCE_ADAPTER_SCHEMA,
            "region_id": region_id,
            "years": list(years),
            "horizon": len(years) - 1,
            "consistent_node_set": True,
            "fine_node_count": initial.metadata["fine_node_count"],
            "coarse_node_count": initial.metadata["coarse_node_count"],
            "observed_transition": True,
            "observed_action": False,
            "recursive_state_writeback_target": True,
            "temporal_history_context": {
                "dimension": TWM_SEQUENCE_CONTEXT_DIM,
                "base_dimension": 4,
                "history_features": TWM_TEMPORAL_CONTEXT_FEATURES,
                "history_years": list(history_years),
                "uses_future_target_state": False,
                "coarse_features": "fine_to_coarse_mean",
                "enabled": use_temporal_history_context,
            },
            "claim_boundary": {
                "max_claim_level": "observed_multiyear_land_state_prediction",
                "action_conditioning_claim": False,
                "policy_effect_claim": False,
            },
        },
    )


def _intersect_valid_cells(
    *,
    region_dir: Path,
    region_id: str,
    years: tuple[int, ...],
    sample_stride: int,
) -> list[tuple[int, int]]:
    land_rasters = []
    transform = None
    shape = None
    for year in years:
        values, current_transform, nodata = _read_raster(
            region_dir / f"{region_id}_dynamic_world_{year}_100m.tif"
        )
        if shape is None:
            shape = values.shape
            transform = current_transform
        elif values.shape != shape or current_transform != transform:
            raise ValueError("sequence_rasters_must_be_aligned")
        land_rasters.append((values, nodata))

    drivers = []
    for suffix in (
        "srtm_elevation_100m.tif",
        "srtm_slope_100m.tif",
        "viirs_nightlight_mean_100m.tif",
    ):
        values, driver_transform, nodata = _read_raster(
            region_dir / f"{region_id}_{suffix}"
        )
        if values.shape != shape or driver_transform != transform:
            raise ValueError("driver_rasters_must_be_aligned")
        drivers.append((values, nodata))

    cells = []
    for row in np.arange(0, shape[0], sample_stride):
        for column in np.arange(0, shape[1], sample_stride):
            cell = (int(row), int(column))
            if all(
                _valid_class(values[cell], nodata)
                for values, nodata in land_rasters
            ) and all(
                _valid_continuous(values[cell], nodata)
                for values, nodata in drivers
            ):
                cells.append(cell)
    if not cells:
        raise ValueError("no_valid_multiyear_cells")
    return cells


def _build_temporal_history_context(
    *,
    region_dir: Path,
    region_id: str,
    transitions: list[TWMDAMGKTransition],
    selected_cells: list[tuple[int, int]],
    history_years: tuple[int, ...],
    sample_stride: int,
) -> torch.Tensor:
    history = []
    for year in history_years:
        values, _, nodata = _read_raster(
            region_dir / f"{region_id}_dynamic_world_{year}_100m.tif"
        )
        classes = []
        for cell in selected_cells:
            if not _valid_class(values[cell], nodata):
                raise ValueError("invalid_historical_cell_after_intersection")
            classes.append(int(values[cell]))
        history.append(torch.tensor(classes, dtype=torch.long))
    class_history = torch.stack(history, dim=1)
    year_index = {year: index for index, year in enumerate(history_years)}
    cell_index = {cell: index for index, cell in enumerate(selected_cells)}
    neighbors = []
    for row, column in selected_cells:
        neighbors.append(
            [
                cell_index[candidate]
                for candidate in (
                    (row - sample_stride, column),
                    (row + sample_stride, column),
                    (row, column - sample_stride),
                    (row, column + sample_stride),
                )
                if candidate in cell_index
            ]
        )

    contexts = []
    for transition in transitions:
        current_year = transition.metadata["current_year"]
        current_index = year_index[current_year]
        current_class = class_history[:, current_index]
        if current_index == 0:
            recent_change = torch.zeros_like(current_class, dtype=torch.float32)
            cumulative_change = torch.zeros_like(recent_change)
        else:
            historical_transitions = (
                class_history[:, 1 : current_index + 1]
                != class_history[:, :current_index]
            ).float()
            recent_change = historical_transitions[:, -1]
            cumulative_change = historical_transitions.mean(dim=1)

        temporal_features = []
        for node_index, neighbor_indices in enumerate(neighbors):
            local_indices = [node_index, *neighbor_indices]
            local_classes = current_class[local_indices]
            distribution = torch.bincount(
                local_classes, minlength=TWM_CLASS_COUNT
            ).float()
            distribution = distribution / distribution.sum().clamp_min(1.0)
            entropy = -torch.sum(
                distribution
                * torch.log(distribution.clamp_min(1e-8))
            ) / np.log(TWM_CLASS_COUNT)
            neighbor_recent = (
                recent_change[neighbor_indices].mean()
                if neighbor_indices
                else recent_change[node_index]
            )
            same_class_share = torch.mean(
                (local_classes == current_class[node_index]).float()
            )
            temporal_features.append(
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
        fine_temporal = torch.stack(temporal_features)
        fine_to_coarse = transition.fine_to_coarse
        mass = fine_to_coarse.sum(dim=1, keepdim=True).clamp_min(1.0)
        coarse_temporal = (fine_to_coarse / mass) @ fine_temporal
        temporal_context = torch.cat([fine_temporal, coarse_temporal], dim=0)
        contexts.append(
            torch.cat([transition.batch.node_context, temporal_context], dim=1)
        )
    context_by_step = torch.stack(contexts, dim=1)
    if context_by_step.shape[-1] != TWM_SEQUENCE_CONTEXT_DIM:
        raise ValueError("temporal_sequence_context_shape_mismatch")
    return context_by_step


def _validate_consistent_sequence(
    transitions: list[TWMDAMGKTransition],
) -> None:
    reference = transitions[0]
    for transition in transitions[1:]:
        if transition.node_ids != reference.node_ids:
            raise ValueError("sequence_node_ids_changed")
        if not torch.equal(
            transition.batch.edge_index, reference.batch.edge_index
        ) or not torch.equal(transition.batch.edge_types, reference.batch.edge_types):
            raise ValueError("sequence_candidate_graph_changed")
        if not torch.allclose(transition.fine_to_coarse, reference.fine_to_coarse):
            raise ValueError("sequence_hierarchy_changed")
