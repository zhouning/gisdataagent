"""TWM Dynamic World temporal adapter for DAM-GK real-data experiments."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import torch

from .contracts import DAMGKBatch


TWM_DAM_GK_ADAPTER_SCHEMA = "gwm.dam_gk.twm_dynamic_world_transition.v1"
TWM_CLASS_COUNT = 9
TWM_REGION_CONTEXT_DIM = 17
TWM_RELATION_TYPES = {
    "grid_adjacency": 0,
    "terrain_similarity": 1,
    "fine_within_block": 2,
    "block_contains_fine": 3,
}
WEB_MERCATOR_HALF_WORLD_METERS = 20037508.342789244
DRIVER_TRANSFORM_SCHEMA = "fixed_physical_scales.v1"
TERRAIN_SIMILARITY_MAX_GRID_STEPS = 3


@dataclass(frozen=True)
class TWMDAMGKTransition:
    batch: DAMGKBatch
    target_delta: torch.Tensor
    current_class: torch.Tensor
    next_class: torch.Tensor
    fine_to_coarse: torch.Tensor
    node_ids: list[str]
    metadata: dict[str, Any]


def build_twm_dynamic_world_transition(
    *,
    region_dir: Path,
    region_id: str,
    current_year: int,
    next_year: int,
    sample_stride: int = 4,
    coarse_block_size: int = 4,
    terrain_similarity_scope: str = "global_configuration",
    selected_cells: list[tuple[int, int]] | None = None,
    nightlight_path: Path | None = None,
) -> TWMDAMGKTransition:
    """Build a non-intervention observed land-state transition.

    The action tensor is intentionally all-zero. This adapter supports geographic
    state-dynamics experiments and must not be used as observed intervention data.
    """

    if next_year <= current_year:
        raise ValueError("next_year_must_follow_current_year")
    if terrain_similarity_scope not in {"global_configuration", "local_spatial_window"}:
        raise ValueError("unsupported_terrain_similarity_scope")
    current_path = region_dir / f"{region_id}_dynamic_world_{current_year}_100m.tif"
    next_path = region_dir / f"{region_id}_dynamic_world_{next_year}_100m.tif"
    driver_paths = [
        region_dir / f"{region_id}_srtm_elevation_100m.tif",
        region_dir / f"{region_id}_srtm_slope_100m.tif",
        nightlight_path
        or region_dir / f"{region_id}_viirs_nightlight_mean_100m.tif",
    ]
    current, transform, nodata = _read_raster(current_path)
    next_state, next_transform, next_nodata = _read_raster(next_path)
    if current.shape != next_state.shape or transform != next_transform:
        raise ValueError("temporal_rasters_must_be_aligned")
    drivers = []
    driver_nodata_values = []
    for path in driver_paths:
        values, driver_transform, driver_nodata = _read_raster(path)
        if values.shape != current.shape or driver_transform != transform:
            raise ValueError("driver_rasters_must_be_aligned")
        drivers.append(values)
        driver_nodata_values.append(driver_nodata)

    if selected_cells is None:
        row_indices = np.arange(0, current.shape[0], sample_stride)
        column_indices = np.arange(0, current.shape[1], sample_stride)
        candidates = [
            (int(row), int(column))
            for row in row_indices
            for column in column_indices
        ]
    else:
        candidates = list(selected_cells)
    valid_cells = [
        (row, column)
        for row, column in candidates
        if _valid_class(current[row, column], nodata)
        and _valid_class(next_state[row, column], next_nodata)
        and all(
            _valid_continuous(driver[row, column], driver_nodata)
            for driver, driver_nodata in zip(drivers, driver_nodata_values)
        )
    ]
    if not valid_cells:
        raise ValueError("no_valid_temporal_cells")

    current_classes = torch.tensor(
        [int(current[row, column]) for row, column in valid_cells], dtype=torch.long
    )
    next_classes = torch.tensor(
        [int(next_state[row, column]) for row, column in valid_cells], dtype=torch.long
    )
    current_one_hot = torch.nn.functional.one_hot(
        current_classes, num_classes=TWM_CLASS_COUNT
    ).float()
    next_one_hot = torch.nn.functional.one_hot(
        next_classes, num_classes=TWM_CLASS_COUNT
    ).float()
    driver_matrix = torch.tensor(
        [[float(driver[row, column]) for driver in drivers] for row, column in valid_cells],
        dtype=torch.float32,
    )
    driver_matrix = _transform_physical_drivers(driver_matrix)
    fine_state = torch.cat([current_one_hot, driver_matrix], dim=1)

    cell_index = {cell: index for index, cell in enumerate(valid_cells)}
    coarse_keys = sorted(
        {
            (row // (sample_stride * coarse_block_size), column // (sample_stride * coarse_block_size))
            for row, column in valid_cells
        }
    )
    coarse_index = {key: index for index, key in enumerate(coarse_keys)}
    fine_to_coarse = torch.zeros((len(coarse_keys), len(valid_cells)), dtype=torch.float32)
    for index, (row, column) in enumerate(valid_cells):
        key = (
            row // (sample_stride * coarse_block_size),
            column // (sample_stride * coarse_block_size),
        )
        fine_to_coarse[coarse_index[key], index] = 1.0
    mass = fine_to_coarse.sum(dim=1, keepdim=True).clamp_min(1.0)
    coarse_state = (fine_to_coarse / mass) @ fine_state
    node_state = torch.cat([fine_state, coarse_state], dim=0)
    fine_count = len(valid_cells)

    node_context = torch.zeros((node_state.shape[0], 4), dtype=torch.float32)
    projected_coordinates = torch.tensor(
        [_projected_cell_center(transform, row, column) for row, column in valid_cells],
        dtype=torch.float32,
    )
    node_context[:fine_count, :2] = (
        projected_coordinates / WEB_MERCATOR_HALF_WORLD_METERS
    ).clamp(-1.0, 1.0)
    node_context[:fine_count, 2] = 0.0
    node_context[:fine_count, 3] = (current_year - 2017) / 10.0
    node_context[fine_count:, :2] = (fine_to_coarse / mass) @ node_context[:fine_count, :2]
    node_context[fine_count:, 2] = 1.0
    node_context[fine_count:, 3] = (current_year - 2017) / 10.0
    region_descriptor = _build_region_descriptor(
        current_one_hot=current_one_hot,
        physical_drivers=driver_matrix,
        normalized_coordinates=node_context[:fine_count, :2],
    )
    region_context = region_descriptor.unsqueeze(0).repeat(node_state.shape[0], 1)
    projected_node_coordinates = torch.cat(
        [
            projected_coordinates,
            (fine_to_coarse / mass) @ projected_coordinates,
        ],
        dim=0,
    )

    edges: list[tuple[int, int]] = []
    edge_features: list[list[float]] = []
    edge_types: list[int] = []
    seen: set[tuple[int, int, int]] = set()
    for source_index, (row, column) in enumerate(valid_cells):
        for delta_row, delta_column in (
            (-sample_stride, 0),
            (sample_stride, 0),
            (0, -sample_stride),
            (0, sample_stride),
        ):
            target_cell = (row + delta_row, column + delta_column)
            target_index = cell_index.get(target_cell)
            if target_index is None:
                continue
            terrain_difference = torch.mean(
                torch.abs(driver_matrix[source_index] - driver_matrix[target_index])
            ).item()
            _append_edge(
                edges,
                edge_features,
                edge_types,
                seen,
                source_index,
                target_index,
                TWM_RELATION_TYPES["grid_adjacency"],
                [1.0, terrain_difference, 0.0, 1.0],
            )
        terrain_distances = torch.mean(
            torch.abs(driver_matrix - driver_matrix[source_index]), dim=1
        )
        spatial_distances = torch.linalg.vector_norm(
            projected_coordinates - projected_coordinates[source_index], dim=1
        )
        maximum_similarity_distance = (
            sample_stride
            * max(abs(float(transform.a)), abs(float(transform.e)))
            * TERRAIN_SIMILARITY_MAX_GRID_STEPS
        )
        candidate_mask = spatial_distances > 0.0
        if terrain_similarity_scope == "local_spatial_window":
            candidate_mask = candidate_mask & (
                spatial_distances <= maximum_similarity_distance
            )
        candidates_for_similarity = torch.where(candidate_mask)[0]
        ranked_candidates = candidates_for_similarity[
            torch.argsort(terrain_distances[candidates_for_similarity])
        ][:2]
        for target_index in ranked_candidates.tolist():
            normalized_spatial_distance = min(
                1.0,
                float(spatial_distances[target_index] / maximum_similarity_distance),
            )
            _append_edge(
                edges,
                edge_features,
                edge_types,
                seen,
                source_index,
                target_index,
                TWM_RELATION_TYPES["terrain_similarity"],
                [
                    1.0 - normalized_spatial_distance,
                    float(terrain_distances[target_index]),
                    0.0,
                    0.7,
                ],
            )
        row_key = (
            row // (sample_stride * coarse_block_size),
            column // (sample_stride * coarse_block_size),
        )
        block_node = fine_count + coarse_index[row_key]
        _append_edge(
            edges,
            edge_features,
            edge_types,
            seen,
            source_index,
            block_node,
            TWM_RELATION_TYPES["fine_within_block"],
            [1.0, 0.0, 1.0, 1.0],
        )
        _append_edge(
            edges,
            edge_features,
            edge_types,
            seen,
            block_node,
            source_index,
            TWM_RELATION_TYPES["block_contains_fine"],
            [1.0, 0.0, 1.0, 1.0],
        )

    coarse_target = (fine_to_coarse / mass) @ next_one_hot
    edge_features = _append_relative_geometry(
        edges=edges,
        edge_features=edge_features,
        projected_coordinates=projected_node_coordinates,
        distance_unit_meters=(
            sample_stride
            * max(abs(float(transform.a)), abs(float(transform.e)))
        ),
    )
    target_delta = torch.cat(
        [next_one_hot - current_one_hot, coarse_target - coarse_state[:, :TWM_CLASS_COUNT]],
        dim=0,
    ).unsqueeze(1)
    node_ids = [f"{region_id}::{row}::{column}" for row, column in valid_cells] + [
        f"{region_id}::block::{row}::{column}" for row, column in coarse_keys
    ]
    return TWMDAMGKTransition(
        batch=DAMGKBatch(
            node_state=node_state,
            node_action=torch.zeros((node_state.shape[0], 1), dtype=torch.float32),
            edge_index=torch.tensor(edges, dtype=torch.long).t().contiguous(),
            edge_features=torch.tensor(edge_features, dtype=torch.float32),
            edge_types=torch.tensor(edge_types, dtype=torch.long),
            node_context=node_context,
            region_context=region_context,
            edge_valid_mask=torch.ones(len(edges), dtype=torch.bool),
        ),
        target_delta=target_delta,
        current_class=current_classes,
        next_class=next_classes,
        fine_to_coarse=fine_to_coarse,
        node_ids=node_ids,
        metadata={
            "schema": TWM_DAM_GK_ADAPTER_SCHEMA,
            "region_id": region_id,
            "current_year": current_year,
            "next_year": next_year,
            "observed_transition": True,
            "observed_action": False,
            "sample_stride": sample_stride,
            "uses_fixed_selected_cells": selected_cells is not None,
            "fine_node_count": fine_count,
            "coarse_node_count": len(coarse_keys),
            "total_node_count": len(node_ids),
            "edge_count": len(edges),
            "edge_geometry": {
                "features": ["relative_dx", "relative_dy", "relative_distance"],
                "source": "current_projected_coordinates",
                "unit": "sampled_grid_step",
            },
            "changed_fine_node_count": int(torch.count_nonzero(current_classes != next_classes)),
            "driver_transform": DRIVER_TRANSFORM_SCHEMA,
            "coordinate_context": "absolute_epsg3857_normalized_to_half_world",
            "region_context": {
                "dimension": TWM_REGION_CONTEXT_DIM,
                "source": "current_state_only",
                "features": [
                    "current_land_class_share_0_to_8",
                    "physical_driver_mean_3",
                    "physical_driver_std_3",
                    "absolute_coordinate_centroid_2",
                ],
                "uses_next_year_label": False,
            },
            "terrain_similarity_constraint": {
                "scope": terrain_similarity_scope,
                "maximum_grid_steps": TERRAIN_SIMILARITY_MAX_GRID_STEPS,
                "maximum_neighbors": 2,
            },
            "driver_nodata_values": driver_nodata_values,
            "nightlight_driver": {
                "path": str(driver_paths[2]),
                "temporal_semantics": (
                    "explicit_current_or_sequence_initial_year"
                    if nightlight_path is not None
                    else "configured_period_composite"
                ),
            },
            "claim_boundary": {
                "max_claim_level": "observed_land_state_transition",
                "action_conditioning_claim": False,
                "policy_effect_claim": False,
            },
        },
    )


def _read_raster(path: Path) -> tuple[np.ndarray, Any, float | None]:
    if not path.exists():
        raise FileNotFoundError(path)
    with rasterio.open(path) as dataset:
        return dataset.read(1), dataset.transform, dataset.nodata


def _valid_class(value: float, nodata: float | None) -> bool:
    if nodata is not None and value == nodata:
        return False
    return np.isfinite(value) and 0 <= int(value) < TWM_CLASS_COUNT


def _valid_continuous(value: float, nodata: float | None) -> bool:
    if nodata is not None and value == nodata:
        return False
    return bool(np.isfinite(value))


def _transform_physical_drivers(values: torch.Tensor) -> torch.Tensor:
    elevation = ((values[:, 0] + 100.0) / 4100.0).clamp(0.0, 1.0)
    slope = (values[:, 1] / 65.0).clamp(0.0, 1.0)
    nightlight = _transform_nightlight(values[:, 2])
    return torch.stack([elevation, slope, nightlight], dim=1)


def _transform_nightlight(values: torch.Tensor) -> torch.Tensor:
    """Map VIIRS radiance to the fixed scale used across regions and years."""

    return (
        torch.log1p(values.clamp_min(0.0)) / np.log1p(320.0)
    ).clamp(0.0, 1.0)


def _projected_cell_center(transform: Any, row: int, column: int) -> tuple[float, float]:
    x_coordinate, y_coordinate = transform * (column + 0.5, row + 0.5)
    return float(x_coordinate), float(y_coordinate)


def _build_region_descriptor(
    *,
    current_one_hot: torch.Tensor,
    physical_drivers: torch.Tensor,
    normalized_coordinates: torch.Tensor,
) -> torch.Tensor:
    land_composition = current_one_hot.mean(dim=0)
    driver_mean = physical_drivers.mean(dim=0)
    driver_std = physical_drivers.std(dim=0, unbiased=False)
    coordinate_centroid = normalized_coordinates.mean(dim=0)
    descriptor = torch.cat(
        [land_composition, driver_mean, driver_std, coordinate_centroid]
    )
    if descriptor.shape != (TWM_REGION_CONTEXT_DIM,):
        raise ValueError("region_descriptor_shape_mismatch")
    return descriptor


def _append_relative_geometry(
    *,
    edges: list[tuple[int, int]],
    edge_features: list[list[float]],
    projected_coordinates: torch.Tensor,
    distance_unit_meters: float,
) -> list[list[float]]:
    if distance_unit_meters <= 0:
        raise ValueError("distance_unit_meters_must_be_positive")
    enriched = []
    for (source, target), features in zip(edges, edge_features):
        displacement = (
            projected_coordinates[target] - projected_coordinates[source]
        ) / distance_unit_meters
        distance = torch.linalg.vector_norm(displacement)
        enriched.append(
            features
            + [float(displacement[0]), float(displacement[1]), float(distance)]
        )
    return enriched


def _append_edge(
    edges: list[tuple[int, int]],
    edge_features: list[list[float]],
    edge_types: list[int],
    seen: set[tuple[int, int, int]],
    source: int,
    target: int,
    relation_type: int,
    features: list[float],
) -> None:
    key = (source, target, relation_type)
    if key in seen:
        return
    seen.add(key)
    edges.append((source, target))
    edge_features.append(features)
    edge_types.append(relation_type)
