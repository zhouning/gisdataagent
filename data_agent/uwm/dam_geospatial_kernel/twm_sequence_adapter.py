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
    _transform_nightlight,
    _valid_class,
    _valid_continuous,
    build_twm_dynamic_world_transition,
)


TWM_SEQUENCE_ADAPTER_SCHEMA = "gwm.dam_gk.twm_dynamic_world_sequence.v1"
TWM_SEQUENCE_CONTEXT_DIM = 10
TWM_SEQUENCE_CONTEXT_DIM_WITH_ANNUAL_VIIRS = 12
TWM_TEMPORAL_CONTEXT_FEATURES = [
    "changed_from_previous_year",
    "cumulative_historical_change_rate",
    "neighbor_recent_change_rate",
    "neighbor_class_entropy",
    "neighbor_built_class_share",
    "same_class_neighbor_share",
]
TWM_ANNUAL_VIIRS_CONTEXT_FEATURES = [
    "annual_viirs_nightlight_level",
    "annual_viirs_nightlight_lag1_change",
]
TWM_ANNUAL_VIIRS_CONTEXT_MODES = {"none", "initial_only", "rolling"}


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
    annual_viirs_context_mode: str = "none",
) -> TWMDAMGKSequence:
    """Build recursive targets on one geographic node set across all years."""

    if len(years) < 2:
        raise ValueError("at_least_two_sequence_years_required")
    if any(next_year <= year for year, next_year in zip(years, years[1:])):
        raise ValueError("sequence_years_must_be_strictly_increasing")
    if annual_viirs_context_mode not in TWM_ANNUAL_VIIRS_CONTEXT_MODES:
        raise ValueError("unsupported_annual_viirs_context_mode")

    history_years = tuple(range(2017, max(years) + 1))
    selected_cells = _intersect_valid_cells(
        region_dir=region_dir,
        region_id=region_id,
        years=history_years,
        sample_stride=sample_stride,
        annual_viirs_years=(
            tuple(current_year for current_year, _ in zip(years, years[1:]))
            if annual_viirs_context_mode != "none"
            else ()
        ),
    )
    initial_nightlight_path = (
        _annual_viirs_path(region_dir, region_id, years[0])
        if annual_viirs_context_mode != "none"
        else None
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
            nightlight_path=initial_nightlight_path,
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
    if annual_viirs_context_mode != "none":
        annual_viirs_context = _build_annual_viirs_context(
            region_dir=region_dir,
            region_id=region_id,
            transitions=transitions,
            selected_cells=selected_cells,
            mode=annual_viirs_context_mode,
        )
        context_by_step = torch.cat(
            [context_by_step, annual_viirs_context], dim=-1
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
                "dimension": context_by_step.shape[-1],
                "base_dimension": 4,
                "history_features": TWM_TEMPORAL_CONTEXT_FEATURES,
                "history_years": list(history_years),
                "uses_future_target_state": False,
                "coarse_features": "fine_to_coarse_mean",
                "enabled": use_temporal_history_context,
            },
            "annual_viirs_context": {
                "enabled": annual_viirs_context_mode != "none",
                "mode": annual_viirs_context_mode,
                "dimension": len(TWM_ANNUAL_VIIRS_CONTEXT_FEATURES)
                if annual_viirs_context_mode != "none"
                else 0,
                "features": TWM_ANNUAL_VIIRS_CONTEXT_FEATURES
                if annual_viirs_context_mode != "none"
                else [],
                "input_years": [
                    transition.metadata["current_year"]
                    for transition in transitions
                ]
                if annual_viirs_context_mode == "rolling"
                else [years[0]]
                if annual_viirs_context_mode == "initial_only"
                else [],
                "target_years": [
                    transition.metadata["next_year"] for transition in transitions
                ],
                "uses_target_year_viirs": False,
                "initial_graph_nightlight_year": years[0]
                if annual_viirs_context_mode != "none"
                else None,
                "temporal_protocol": (
                    "rolling_observed_current_year_covariate"
                    if annual_viirs_context_mode == "rolling"
                    else "sequence_initial_year_covariate_only"
                    if annual_viirs_context_mode == "initial_only"
                    else "period_composite_static_covariate"
                ),
                "open_loop_multiyear_forecast": (
                    annual_viirs_context_mode == "initial_only"
                    if annual_viirs_context_mode != "none"
                    else None
                ),
                "native_resolution_m_approx": 500
                if annual_viirs_context_mode != "none"
                else None,
                "export_resolution_m": 100
                if annual_viirs_context_mode != "none"
                else None,
            },
            "claim_boundary": {
                "max_claim_level": (
                    "rolling_observed_covariate_multiyear_land_state_prediction"
                    if annual_viirs_context_mode == "rolling"
                    else "initial_covariate_open_loop_multiyear_land_state_prediction"
                    if annual_viirs_context_mode == "initial_only"
                    else "observed_multiyear_land_state_prediction"
                ),
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
    annual_viirs_years: tuple[int, ...] = (),
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
    static_driver_suffixes = [
        "srtm_elevation_100m.tif",
        "srtm_slope_100m.tif",
    ]
    if not annual_viirs_years:
        static_driver_suffixes.append("viirs_nightlight_mean_100m.tif")
    for suffix in static_driver_suffixes:
        values, driver_transform, nodata = _read_raster(
            region_dir / f"{region_id}_{suffix}"
        )
        if values.shape != shape or driver_transform != transform:
            raise ValueError("driver_rasters_must_be_aligned")
        drivers.append((values, nodata))

    annual_driver_paths = [
        _annual_viirs_path(region_dir, region_id, year)
        for year in annual_viirs_years
    ]
    if annual_viirs_years:
        previous_path = _annual_viirs_path(
            region_dir, region_id, min(annual_viirs_years) - 1
        )
        if previous_path.exists():
            annual_driver_paths.insert(0, previous_path)
    for path in annual_driver_paths:
        values, driver_transform, nodata = _read_raster(path)
        if values.shape != shape or driver_transform != transform:
            raise ValueError("annual_viirs_rasters_must_be_aligned")
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


def _annual_viirs_path(region_dir: Path, region_id: str, year: int) -> Path:
    return region_dir / f"{region_id}_viirs_nightlight_{year}_100m.tif"


def _build_annual_viirs_context(
    *,
    region_dir: Path,
    region_id: str,
    transitions: list[TWMDAMGKTransition],
    selected_cells: list[tuple[int, int]],
    mode: str,
) -> torch.Tensor:
    if mode not in {"initial_only", "rolling"}:
        raise ValueError("annual_viirs_context_mode_required")
    contexts = []
    initial_year = int(transitions[0].metadata["current_year"])
    for transition in transitions:
        transition_year = int(transition.metadata["current_year"])
        current_year = initial_year if mode == "initial_only" else transition_year
        current_values, current_transform, current_nodata = _read_raster(
            _annual_viirs_path(region_dir, region_id, current_year)
        )
        land_values, land_transform, _ = _read_raster(
            region_dir / f"{region_id}_dynamic_world_{current_year}_100m.tif"
        )
        if (
            current_values.shape != land_values.shape
            or current_transform != land_transform
        ):
            raise ValueError("annual_viirs_rasters_must_be_aligned")
        current_raw = torch.tensor(
            [float(current_values[cell]) for cell in selected_cells],
            dtype=torch.float32,
        )
        if any(
            not _valid_continuous(current_values[cell], current_nodata)
            for cell in selected_cells
        ):
            raise ValueError("invalid_annual_viirs_cell_after_intersection")
        current_level = _transform_nightlight(current_raw)

        previous_path = _annual_viirs_path(region_dir, region_id, current_year - 1)
        if mode == "rolling" and previous_path.exists():
            previous_values, previous_transform, previous_nodata = _read_raster(
                previous_path
            )
            if (
                previous_values.shape != current_values.shape
                or previous_transform != current_transform
            ):
                raise ValueError("annual_viirs_rasters_must_be_aligned")
            if any(
                not _valid_continuous(previous_values[cell], previous_nodata)
                for cell in selected_cells
            ):
                raise ValueError("invalid_annual_viirs_cell_after_intersection")
            previous_raw = torch.tensor(
                [float(previous_values[cell]) for cell in selected_cells],
                dtype=torch.float32,
            )
            lag_change = current_level - _transform_nightlight(previous_raw)
        else:
            lag_change = torch.zeros_like(current_level)

        fine_context = torch.stack([current_level, lag_change], dim=1)
        fine_to_coarse = transition.fine_to_coarse
        mass = fine_to_coarse.sum(dim=1, keepdim=True).clamp_min(1.0)
        coarse_context = (fine_to_coarse / mass) @ fine_context
        contexts.append(torch.cat([fine_context, coarse_context], dim=0))

    context_by_step = torch.stack(contexts, dim=1)
    if context_by_step.shape[-1] != len(TWM_ANNUAL_VIIRS_CONTEXT_FEATURES):
        raise ValueError("annual_viirs_context_shape_mismatch")
    return context_by_step


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
