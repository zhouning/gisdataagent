"""Shared planning metrics and Pareto logic for Abu Dhabi scenarios."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from scipy.ndimage import convolve, distance_transform_edt, label

try:
    from .shared import CLASSES, class_counts
except ImportError:  # Direct script execution from the benchmark directory.
    from shared import CLASSES, class_counts


OBJECTIVES = {
    "demand_total_variation": "min",
    "ecological_conversion_rate": "min",
    "new_built_neighbor_fraction": "max",
    "new_built_mean_major_road_distance_m": "min",
    "new_built_mean_prior_built_distance_m": "min",
    "built_gain_pixels": "max",
    "green_gain_pixels": "max",
}


def planning_metrics(
    state: np.ndarray,
    *,
    origin_state: np.ndarray,
    valid_mask: np.ndarray,
    hard_exclusion_mask: np.ndarray,
    target_counts: Mapping[int, int],
    road_distance_m: np.ndarray,
    major_road_distance_m: np.ndarray,
    pixel_size_m: float = 100.0,
) -> dict[str, Any]:
    """Evaluate one spatial allocation without treating a scenario as a forecast."""

    result = np.asarray(state)
    origin = np.asarray(origin_state)
    valid = np.asarray(valid_mask, dtype=bool)
    hard = np.asarray(hard_exclusion_mask, dtype=bool)
    road_distance = np.asarray(road_distance_m, dtype=np.float64)
    major_road_distance = np.asarray(major_road_distance_m, dtype=np.float64)
    if not (
        result.shape
        == origin.shape
        == valid.shape
        == hard.shape
        == road_distance.shape
        == major_road_distance.shape
    ):
        raise ValueError("planning_metric_shape_mismatch")

    requested = {int(key): int(value) for key, value in target_counts.items()}
    actual = class_counts(result, valid)
    total = max(1, int(valid.sum()))
    demand_l1 = sum(abs(actual[value] - requested[value]) for value in CLASSES)
    new_built = valid & (origin != 5) & (result == 5)
    removed_built = valid & (origin == 5) & (result != 5)
    ecological_conversion = new_built & np.isin(origin, (2, 3, 4))
    new_built_count = int(new_built.sum())

    built = valid & (result == 5)
    neighborhood_kernel = np.ones((3, 3), dtype=np.uint8)
    neighborhood_kernel[1, 1] = 0
    built_neighbors = convolve(built.astype(np.uint8), neighborhood_kernel, mode="constant")
    new_built_neighbor_fraction = _mean_or_zero(
        built_neighbors[new_built].astype(np.float64) / 8.0
    )
    _, built_component_count = label(built, structure=np.ones((3, 3), dtype=np.uint8))
    built_count = max(1, int(built.sum()))

    prior_built_distance = distance_transform_edt(
        ~(valid & (origin == 5)), sampling=float(pixel_size_m)
    )
    green_origin = int(np.count_nonzero(valid & np.isin(origin, (2, 3))))
    green_result = int(np.count_nonzero(valid & np.isin(result, (2, 3))))
    built_origin = int(np.count_nonzero(valid & (origin == 5)))
    built_result = int(np.count_nonzero(valid & (result == 5)))
    constraint_violations = int(np.count_nonzero(valid & hard & (result != origin)))

    return {
        "valid_pixel_count": int(valid.sum()),
        "actual_class_counts": {str(key): value for key, value in actual.items()},
        "target_class_counts": {str(key): value for key, value in requested.items()},
        "demand_l1_error_pixels": int(demand_l1),
        "demand_total_variation": float(demand_l1 / (2 * total)),
        "constraint_violation_pixels": constraint_violations,
        "constraint_violation_rate": float(constraint_violations / total),
        "built_gain_pixels": built_result - built_origin,
        "green_gain_pixels": green_result - green_origin,
        "new_built_pixels": new_built_count,
        "removed_built_pixels": int(removed_built.sum()),
        "ecological_conversion_pixels": int(ecological_conversion.sum()),
        "ecological_conversion_rate": float(
            ecological_conversion.sum() / max(1, new_built_count)
        ),
        "new_built_neighbor_fraction": new_built_neighbor_fraction,
        "built_component_count": int(built_component_count),
        "built_components_per_1000_pixels": float(
            built_component_count * 1000.0 / built_count
        ),
        "new_built_mean_road_distance_m": _mean_or_zero(road_distance[new_built]),
        "new_built_p90_road_distance_m": _percentile_or_zero(
            road_distance[new_built], 90
        ),
        "new_built_mean_major_road_distance_m": _mean_or_zero(
            major_road_distance[new_built]
        ),
        "new_built_p90_major_road_distance_m": _percentile_or_zero(
            major_road_distance[new_built], 90
        ),
        "new_built_mean_prior_built_distance_m": _mean_or_zero(
            prior_built_distance[new_built]
        ),
        "new_built_p90_prior_built_distance_m": _percentile_or_zero(
            prior_built_distance[new_built], 90
        ),
        "infrastructure_proxy_mean_m": _mean_or_zero(
            major_road_distance[new_built] + prior_built_distance[new_built]
        ),
    }


def pareto_frontier(
    candidates: Sequence[Mapping[str, Any]],
    *,
    objectives: Mapping[str, str] = OBJECTIVES,
    tolerance: float = 1e-12,
) -> list[str]:
    """Return candidate IDs not dominated across the declared objective directions."""

    rows = list(candidates)
    for name, direction in objectives.items():
        if direction not in {"min", "max"}:
            raise ValueError(f"invalid_objective_direction:{name}:{direction}")
    frontier = []
    for index, row in enumerate(rows):
        dominated = False
        for other_index, other in enumerate(rows):
            if index == other_index:
                continue
            no_worse = True
            strictly_better = False
            for name, direction in objectives.items():
                value = float(row[name])
                other_value = float(other[name])
                if direction == "min":
                    no_worse &= other_value <= value + tolerance
                    strictly_better |= other_value < value - tolerance
                else:
                    no_worse &= other_value >= value - tolerance
                    strictly_better |= other_value > value + tolerance
            if no_worse and strictly_better:
                dominated = True
                break
        if not dominated:
            frontier.append(str(row["candidate_id"]))
    return frontier


def _mean_or_zero(values: np.ndarray) -> float:
    return float(np.mean(values)) if values.size else 0.0


def _percentile_or_zero(values: np.ndarray, percentile: float) -> float:
    return float(np.percentile(values, percentile)) if values.size else 0.0
