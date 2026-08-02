"""Contracts shared by all Abu Dhabi land-use benchmark candidates."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
PROTOCOL_PATH = HERE / "protocol.json"


class BenchmarkContractError(ValueError):
    """Raised when benchmark data or a model output violates the frozen contract."""


def load_protocol(path: Path = PROTOCOL_PATH) -> dict[str, Any]:
    protocol = json.loads(path.read_text(encoding="utf-8"))
    validate_protocol(protocol)
    return protocol


def class_values(protocol: Mapping[str, Any]) -> tuple[int, ...]:
    return tuple(int(row["value"]) for row in protocol["class_system"]["classes"])


def validate_protocol(protocol: Mapping[str, Any]) -> None:
    if protocol.get("schema") != "gwm.abu_dhabi_land_use_benchmark.v1":
        raise BenchmarkContractError("protocol_schema_mismatch")
    spatial = protocol.get("spatial_world") or {}
    if spatial.get("boundary_osm_relation_id") != 4479763:
        raise BenchmarkContractError("abu_dhabi_city_boundary_not_frozen")
    if spatial.get("canonical_crs") != "EPSG:32640":
        raise BenchmarkContractError("canonical_crs_mismatch")
    if int(spatial.get("canonical_resolution_m", 0)) != 100:
        raise BenchmarkContractError("canonical_resolution_mismatch")
    values = class_values(protocol)
    if values != tuple(range(1, len(values) + 1)):
        raise BenchmarkContractError("classes_must_be_contiguous_from_one")
    mapped_raw = [
        int(raw)
        for row in protocol["class_system"]["classes"]
        for raw in row["dynamic_world_values"]
    ]
    excluded = [int(value) for value in protocol["class_system"]["excluded_dynamic_world_values"]]
    if sorted(mapped_raw + excluded) != list(range(9)):
        raise BenchmarkContractError("dynamic_world_crosswalk_must_partition_0_to_8")
    if len(set(mapped_raw)) != len(mapped_raw):
        raise BenchmarkContractError("dynamic_world_crosswalk_contains_duplicates")
    years = protocol.get("temporal_world") or {}
    if max(years["test_target_years"]) >= min(years["scenario_years"]):
        raise BenchmarkContractError("test_and_scenario_years_overlap")
    model_ids = {str(row["id"]) for row in protocol.get("models") or []}
    expected = {"geosos_flus", "gwm_geospatial_kernel", "paper58"}
    if model_ids != expected:
        raise BenchmarkContractError("three_candidate_models_required")


def canonicalize_dynamic_world(
    raw: np.ndarray,
    *,
    protocol: Mapping[str, Any] | None = None,
) -> np.ndarray:
    """Map Dynamic World values 0..8 into the frozen six-class system."""

    protocol = protocol or load_protocol()
    values = np.asarray(raw)
    result = np.zeros(values.shape, dtype=np.uint8)
    for row in protocol["class_system"]["classes"]:
        for raw_value in row["dynamic_world_values"]:
            result[values == int(raw_value)] = int(row["value"])
    return result


def observed_demand_counts(
    start_state: np.ndarray,
    observed_target: np.ndarray,
    *,
    valid_mask: np.ndarray,
    protocol: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an oracle-demand action for allocation-skill evaluation only."""

    protocol = protocol or load_protocol()
    start = np.asarray(start_state)
    target = np.asarray(observed_target)
    valid = np.asarray(valid_mask, dtype=bool)
    if start.shape != target.shape or start.shape != valid.shape:
        raise BenchmarkContractError("demand_array_shape_mismatch")
    classes = class_values(protocol)
    valid &= np.isin(start, classes) & np.isin(target, classes)
    if not valid.any():
        raise BenchmarkContractError("demand_has_no_valid_pixels")
    return {
        "schema": "gwm.land_use_demand_action.v1",
        "source": "observed_allocation",
        "valid_pixel_count": int(valid.sum()),
        "start_counts": {
            str(value): int(np.count_nonzero(start[valid] == value)) for value in classes
        },
        "target_counts": {
            str(value): int(np.count_nonzero(target[valid] == value)) for value in classes
        },
    }


def validate_prediction(
    prediction: np.ndarray,
    *,
    origin_state: np.ndarray,
    valid_mask: np.ndarray,
    hard_exclusion_mask: np.ndarray,
    protocol: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a candidate map before it can enter the shared evaluator."""

    protocol = protocol or load_protocol()
    predicted = np.asarray(prediction)
    origin = np.asarray(origin_state)
    valid = np.asarray(valid_mask, dtype=bool)
    excluded = np.asarray(hard_exclusion_mask, dtype=bool)
    if not (predicted.shape == origin.shape == valid.shape == excluded.shape):
        raise BenchmarkContractError("prediction_array_shape_mismatch")
    classes = class_values(protocol)
    invalid_class_pixels = int(np.count_nonzero(valid & ~np.isin(predicted, classes)))
    outside_world_pixels = int(np.count_nonzero(~valid & (predicted != 0)))
    changed_excluded_pixels = int(np.count_nonzero(valid & excluded & (predicted != origin)))
    diagnostics = {
        "invalid_class_pixels": invalid_class_pixels,
        "nonzero_outside_world_pixels": outside_world_pixels,
        "changed_hard_exclusion_pixels": changed_excluded_pixels,
        "valid_pixel_count": int(valid.sum()),
    }
    diagnostics["valid"] = not any(
        diagnostics[key]
        for key in (
            "invalid_class_pixels",
            "nonzero_outside_world_pixels",
            "changed_hard_exclusion_pixels",
        )
    )
    return diagnostics
