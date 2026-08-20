"""Compile SmartMakani pipeline rows into an auditable topology candidate."""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .smartmakani_acquisition import (
    TARGET_CRS,
    canonical_json_bytes,
    sha256_file,
)

PIPELINE_TOPOLOGY_SCHEMA = "gwm.abu_dhabi_flood.pipeline_topology.v1"
PIPELINE_AUDIT_SCHEMA = "gwm.abu_dhabi_flood.pipeline_network_audit.v1"


@dataclass(frozen=True)
class PipelineCompilePolicy:
    snap_tolerance_m: float = 1.0
    zero_length_tolerance_m: float = 0.01
    endpoint_match_tolerance_m: float = 5.0
    plausible_invert_min: float = -100.0
    plausible_invert_max: float = 200.0

    def __post_init__(self) -> None:
        if self.snap_tolerance_m <= 0:
            raise ValueError("snap_tolerance_m_must_be_positive")
        if self.zero_length_tolerance_m < 0:
            raise ValueError("zero_length_tolerance_m_must_be_nonnegative")
        if self.endpoint_match_tolerance_m < 0:
            raise ValueError("endpoint_match_tolerance_m_must_be_nonnegative")
        if self.plausible_invert_min >= self.plausible_invert_max:
            raise ValueError("invert_plausibility_bounds_invalid")


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(canonical_json_bytes(payload))
    temporary.replace(path)


def _column(frame: Any, name: str) -> str | None:
    return next(
        (column for column in frame.columns if str(column).casefold() == name.casefold()),
        None,
    )


def _numeric_series(frame: Any, name: str) -> Any:
    import pandas as pd

    column = _column(frame, name)
    if column is None:
        return pd.Series(float("nan"), index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _text_series(frame: Any, name: str) -> Any:
    import pandas as pd

    column = _column(frame, name)
    if column is None:
        return pd.Series("", index=frame.index, dtype="string")
    return frame[column].astype("string").fillna("").str.strip()


def _line_endpoints(
    geometry: Any,
) -> tuple[float, float, float, float, float, float, bool] | None:
    from shapely.geometry import LineString, MultiLineString
    from shapely.ops import linemerge

    if geometry is None or geometry.is_empty:
        return None
    line = geometry
    multipart = isinstance(line, MultiLineString)
    if multipart:
        merged = linemerge(line)
        if isinstance(merged, LineString):
            line = merged
        elif isinstance(merged, MultiLineString) and merged.geoms:
            line = max(merged.geoms, key=lambda item: item.length)
        else:
            return None
    if not isinstance(line, LineString) or len(line.coords) < 2:
        return None
    start = line.coords[0]
    end = line.coords[-1]
    start_z = float(start[2]) if len(start) >= 3 else math.nan
    end_z = float(end[2]) if len(end) >= 3 else math.nan
    return (
        float(start[0]),
        float(start[1]),
        float(end[0]),
        float(end[1]),
        start_z,
        end_z,
        multipart,
    )


def _snap_key(x: float, y: float, tolerance: float) -> tuple[int, int]:
    return math.floor(x / tolerance + 0.5), math.floor(y / tolerance + 0.5)


def _node_id(key: tuple[int, int]) -> str:
    return f"n_{key[0]}_{key[1]}"


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[tuple[int, int], tuple[int, int]] = {}

    def add(self, value: tuple[int, int]) -> None:
        self.parent.setdefault(value, value)

    def find(self, value: tuple[int, int]) -> tuple[int, int]:
        parent = self.parent[value]
        while parent != self.parent[parent]:
            parent = self.parent[parent]
        while value != parent:
            next_value = self.parent[value]
            self.parent[value] = parent
            value = next_value
        return parent

    def union(self, first: tuple[int, int], second: tuple[int, int]) -> None:
        self.add(first)
        self.add(second)
        first_root = self.find(first)
        second_root = self.find(second)
        if first_root == second_root:
            return
        if second_root < first_root:
            first_root, second_root = second_root, first_root
        self.parent[second_root] = first_root


def _finite_summary(values: Any) -> dict[str, float | int | None]:
    import numpy as np

    finite = np.asarray(values, dtype="float64")
    finite = finite[np.isfinite(finite)]
    if not finite.size:
        return {
            "count": 0,
            "minimum": None,
            "p05": None,
            "median": None,
            "p95": None,
            "maximum": None,
        }
    return {
        "count": int(finite.size),
        "minimum": float(finite.min()),
        "p05": float(np.percentile(finite, 5)),
        "median": float(np.median(finite)),
        "p95": float(np.percentile(finite, 95)),
        "maximum": float(finite.max()),
    }


def _count_and_percent(mask: Any, denominator: int) -> dict[str, float | int]:
    count = int(mask.sum())
    return {
        "count": count,
        "percent": round((count / denominator * 100.0) if denominator else 0.0, 6),
    }


def _attribute_endpoint_diagnostics(frame: Any, policy: PipelineCompilePolicy) -> dict[str, Any]:
    import numpy as np
    from pyproj import Transformer

    start_x = _numeric_series(frame, "Start_X").to_numpy(dtype="float64")
    start_y = _numeric_series(frame, "Start_Y").to_numpy(dtype="float64")
    end_x = _numeric_series(frame, "End_X").to_numpy(dtype="float64")
    end_y = _numeric_series(frame, "End_Y").to_numpy(dtype="float64")
    available = (
        np.isfinite(start_x)
        & np.isfinite(start_y)
        & np.isfinite(end_x)
        & np.isfinite(end_y)
    )
    looks_wgs84 = (
        available
        & (start_x >= -180)
        & (start_x <= 180)
        & (end_x >= -180)
        & (end_x <= 180)
        & (start_y >= -90)
        & (start_y <= 90)
        & (end_y >= -90)
        & (end_y <= 90)
    )
    looks_projected = available & ~looks_wgs84
    normalized_start_x = start_x.copy()
    normalized_start_y = start_y.copy()
    normalized_end_x = end_x.copy()
    normalized_end_y = end_y.copy()
    if looks_wgs84.any():
        transformer = Transformer.from_crs("EPSG:4326", TARGET_CRS, always_xy=True)
        sx, sy = transformer.transform(start_x[looks_wgs84], start_y[looks_wgs84])
        ex, ey = transformer.transform(end_x[looks_wgs84], end_y[looks_wgs84])
        normalized_start_x[looks_wgs84] = sx
        normalized_start_y[looks_wgs84] = sy
        normalized_end_x[looks_wgs84] = ex
        normalized_end_y[looks_wgs84] = ey

    geometry_start_x = frame["geometry_start_x_m"].to_numpy(dtype="float64")
    geometry_start_y = frame["geometry_start_y_m"].to_numpy(dtype="float64")
    geometry_end_x = frame["geometry_end_x_m"].to_numpy(dtype="float64")
    geometry_end_y = frame["geometry_end_y_m"].to_numpy(dtype="float64")
    geometry_available = np.isfinite(geometry_start_x) & np.isfinite(geometry_end_x)
    comparable = available & geometry_available
    direct_start = np.hypot(
        normalized_start_x - geometry_start_x,
        normalized_start_y - geometry_start_y,
    )
    direct_end = np.hypot(
        normalized_end_x - geometry_end_x,
        normalized_end_y - geometry_end_y,
    )
    reverse_start = np.hypot(
        normalized_start_x - geometry_end_x,
        normalized_start_y - geometry_end_y,
    )
    reverse_end = np.hypot(
        normalized_end_x - geometry_start_x,
        normalized_end_y - geometry_start_y,
    )
    direct_total = direct_start + direct_end
    reverse_total = reverse_start + reverse_end
    reversed_orientation = comparable & (reverse_total < direct_total)
    best_start = np.where(reversed_orientation, reverse_start, direct_start)
    best_end = np.where(reversed_orientation, reverse_end, direct_end)
    maximum_error = np.maximum(best_start, best_end)
    matches = comparable & (maximum_error <= policy.endpoint_match_tolerance_m)

    frame["attribute_endpoint_available"] = available
    frame["attribute_endpoint_crs_inferred"] = np.select(
        [looks_wgs84, looks_projected],
        ["EPSG:4326", TARGET_CRS],
        default="unavailable",
    )
    frame["attribute_endpoint_reversed_to_geometry"] = reversed_orientation
    frame["attribute_endpoint_max_error_m"] = np.where(comparable, maximum_error, np.nan)
    frame["attribute_endpoint_within_tolerance"] = matches
    return {
        "available": _count_and_percent(available, len(frame)),
        "inferred_wgs84": _count_and_percent(looks_wgs84, len(frame)),
        "inferred_projected": _count_and_percent(looks_projected, len(frame)),
        "within_tolerance": _count_and_percent(matches, len(frame)),
        "maximum_endpoint_error_m": _finite_summary(maximum_error[comparable]),
        "match_tolerance_m": policy.endpoint_match_tolerance_m,
        "orientation_compared_both_directions": True,
    }


def compile_pipeline_topology(
    pipelines: Any,
    *,
    policy: PipelineCompilePolicy | None = None,
) -> tuple[Any, Any, dict[str, Any]]:
    """Return enriched pipelines, snapped nodes, and an admission-safe audit."""

    import geopandas as gpd
    import numpy as np
    import pandas as pd
    from shapely.geometry import Point

    active_policy = policy or PipelineCompilePolicy()
    if pipelines.crs is None:
        raise ValueError("pipeline_crs_required")
    frame = pipelines.to_crs(TARGET_CRS).copy().reset_index(drop=True)
    row_count = len(frame)
    endpoints = [_line_endpoints(geometry) for geometry in frame.geometry]
    geometry_valid = np.asarray([item is not None for item in endpoints], dtype=bool)
    multipart = np.asarray(
        [bool(item[6]) if item is not None else False for item in endpoints],
        dtype=bool,
    )
    endpoint_values = [
        item[:4] if item is not None else (math.nan, math.nan, math.nan, math.nan)
        for item in endpoints
    ]
    endpoint_array = np.asarray(endpoint_values, dtype="float64")
    z_values = np.asarray(
        [
            (item[4], item[5]) if item is not None else (math.nan, math.nan)
            for item in endpoints
        ],
        dtype="float64",
    )
    frame["geometry_start_x_m"] = endpoint_array[:, 0] if row_count else []
    frame["geometry_start_y_m"] = endpoint_array[:, 1] if row_count else []
    frame["geometry_end_x_m"] = endpoint_array[:, 2] if row_count else []
    frame["geometry_end_y_m"] = endpoint_array[:, 3] if row_count else []
    frame["geometry_start_z"] = z_values[:, 0] if row_count else []
    frame["geometry_end_z"] = z_values[:, 1] if row_count else []
    frame["geometry_supported"] = geometry_valid
    frame["geometry_multipart"] = multipart
    geometry_z_available = np.isfinite(z_values).all(axis=1)
    geometry_z_both_zero = geometry_z_available & (z_values[:, 0] == 0) & (
        z_values[:, 1] == 0
    )
    frame["geometry_z_available"] = geometry_z_available
    frame["geometry_z_both_zero"] = geometry_z_both_zero
    frame["recomputed_length_m"] = frame.geometry.length
    zero_length = geometry_valid & (
        frame["recomputed_length_m"].to_numpy(dtype="float64")
        <= active_policy.zero_length_tolerance_m
    )
    frame["zero_length"] = zero_length

    node_start: list[tuple[int, int] | None] = []
    node_end: list[tuple[int, int] | None] = []
    union_find = _UnionFind()
    edge_keys: list[tuple[tuple[int, int], tuple[int, int]] | None] = []
    degree: Counter[tuple[int, int]] = Counter()
    endpoint_count: Counter[tuple[int, int]] = Counter()
    for item in endpoints:
        if item is None:
            node_start.append(None)
            node_end.append(None)
            edge_keys.append(None)
            continue
        start = _snap_key(item[0], item[1], active_policy.snap_tolerance_m)
        end = _snap_key(item[2], item[3], active_policy.snap_tolerance_m)
        node_start.append(start)
        node_end.append(end)
        union_find.add(start)
        union_find.add(end)
        endpoint_count[start] += 1
        endpoint_count[end] += 1
        normalized_edge = (start, end) if start <= end else (end, start)
        edge_keys.append(normalized_edge)
        if start != end:
            union_find.union(start, end)
            degree[start] += 1
            degree[end] += 1

    edge_counts = Counter(key for key in edge_keys if key is not None)
    self_loop = np.asarray(
        [
            start is not None and start == end
            for start, end in zip(node_start, node_end, strict=True)
        ],
        dtype=bool,
    )
    duplicate_edge = np.asarray(
        [key is not None and edge_counts[key] > 1 for key in edge_keys],
        dtype=bool,
    )
    frame["source_node_id"] = [
        _node_id(value) if value is not None else None for value in node_start
    ]
    frame["target_node_id"] = [
        _node_id(value) if value is not None else None for value in node_end
    ]
    frame["self_loop_after_snap"] = self_loop
    frame["duplicate_node_pair"] = duplicate_edge

    invert_up = _numeric_series(frame, "INVERT_LEVEL_UP")
    invert_down = _numeric_series(frame, "INVERT_LEVEL_DOWN")
    diameter = _numeric_series(frame, "ASSET_DIAMETER")
    invert_up_valid = invert_up.between(
        active_policy.plausible_invert_min,
        active_policy.plausible_invert_max,
        inclusive="both",
    )
    invert_down_valid = invert_down.between(
        active_policy.plausible_invert_min,
        active_policy.plausible_invert_max,
        inclusive="both",
    )
    both_inverts = invert_up_valid & invert_down_valid
    direction_conflict = both_inverts & (invert_up <= invert_down)
    valid_length = frame["recomputed_length_m"] > active_policy.zero_length_tolerance_m
    frame["diameter_numeric"] = diameter
    frame["diameter_positive"] = diameter > 0
    frame["invert_up_numeric"] = invert_up
    frame["invert_down_numeric"] = invert_down
    frame["invert_up_plausible_candidate"] = invert_up_valid
    frame["invert_down_plausible_candidate"] = invert_down_valid
    frame["flow_direction_conflict"] = direction_conflict
    frame["candidate_invert_slope"] = np.where(
        both_inverts & valid_length,
        (invert_up - invert_down) / frame["recomputed_length_m"],
        np.nan,
    )
    direct_z_error = np.maximum(
        np.abs(z_values[:, 0] - invert_up.to_numpy(dtype="float64")),
        np.abs(z_values[:, 1] - invert_down.to_numpy(dtype="float64")),
    )
    reverse_z_error = np.maximum(
        np.abs(z_values[:, 0] - invert_down.to_numpy(dtype="float64")),
        np.abs(z_values[:, 1] - invert_up.to_numpy(dtype="float64")),
    )
    best_z_error = np.minimum(direct_z_error, reverse_z_error)
    z_comparable = geometry_z_available & both_inverts.to_numpy(dtype=bool)
    z_matches_inverts = z_comparable & (best_z_error <= 0.01)
    frame["geometry_z_best_invert_error"] = np.where(
        z_comparable,
        best_z_error,
        np.nan,
    )
    frame["geometry_z_matches_inverts_within_0_01"] = z_matches_inverts
    outfall = _text_series(frame, "OUTFALL_NAME")
    frame["outfall_name_present"] = outfall.ne("")
    endpoint_audit = _attribute_endpoint_diagnostics(frame, active_policy)

    roots = {node: union_find.find(node) for node in union_find.parent}
    component_roots = sorted(set(roots.values()))
    component_index = {root: index for index, root in enumerate(component_roots)}
    component_sizes = Counter(component_index[root] for root in roots.values())
    node_rows = []
    for key in sorted(roots):
        component_id = component_index[roots[key]]
        node_rows.append(
            {
                "node_id": _node_id(key),
                "snap_x_m": key[0] * active_policy.snap_tolerance_m,
                "snap_y_m": key[1] * active_policy.snap_tolerance_m,
                "component_id": component_id,
                "component_node_count": component_sizes[component_id],
                "degree": degree[key],
                "endpoint_count": endpoint_count[key],
                "geometry": Point(
                    key[0] * active_policy.snap_tolerance_m,
                    key[1] * active_policy.snap_tolerance_m,
                ),
            }
        )
    nodes = gpd.GeoDataFrame(node_rows, geometry="geometry", crs=TARGET_CRS)
    component_edge_counts: Counter[int] = Counter()
    for start, end in zip(node_start, node_end, strict=True):
        if start is not None and end is not None and start != end:
            component_edge_counts[component_index[roots[start]]] += 1

    object_id_column = _column(frame, "OBJECTID")
    if object_id_column is not None:
        frame["source_object_id"] = frame[object_id_column]
    unique_edge_count = len(edge_counts)
    duplicate_group_count = sum(count > 1 for count in edge_counts.values())
    isolated_nodes = nodes["degree"].eq(0) if len(nodes) else pd.Series(dtype=bool)
    audit = {
        "schema": PIPELINE_AUDIT_SCHEMA,
        "crs": TARGET_CRS,
        "row_count": row_count,
        "policy": {
            "snap_tolerance_m": active_policy.snap_tolerance_m,
            "zero_length_tolerance_m": active_policy.zero_length_tolerance_m,
            "endpoint_match_tolerance_m": active_policy.endpoint_match_tolerance_m,
            "plausible_invert_range_candidate": [
                active_policy.plausible_invert_min,
                active_policy.plausible_invert_max,
            ],
            "invert_range_is_engineering_authority": False,
        },
        "geometry": {
            "supported_lines": _count_and_percent(geometry_valid, row_count),
            "multipart_lines": _count_and_percent(multipart, row_count),
            "zero_length": _count_and_percent(zero_length, row_count),
            "recomputed_length_m": _finite_summary(frame["recomputed_length_m"]),
            "stored_shape_length_used": False,
            "z_available": _count_and_percent(geometry_z_available, row_count),
            "z_both_endpoints_zero": _count_and_percent(
                geometry_z_both_zero,
                row_count,
            ),
            "z_source_unit_or_datum_verified": False,
            "z_matches_plausible_inverts_within_0_01": _count_and_percent(
                z_matches_inverts,
                row_count,
            ),
            "z_match_percent_of_comparable_rows": round(
                (
                    int(z_matches_inverts.sum())
                    / int(z_comparable.sum())
                    * 100.0
                )
                if z_comparable.any()
                else 0.0,
                6,
            ),
            "z_best_invert_error_for_comparable_rows": _finite_summary(
                best_z_error[z_comparable]
            ),
        },
        "attributes": {
            "diameter_numeric": _count_and_percent(diameter.notna(), row_count),
            "diameter_positive": _count_and_percent(diameter.gt(0), row_count),
            "diameter_source_unit_verified": False,
            "diameter_source_values": _finite_summary(diameter),
            "invert_up_plausible_candidate": _count_and_percent(invert_up_valid, row_count),
            "invert_down_plausible_candidate": _count_and_percent(invert_down_valid, row_count),
            "both_inverts_plausible_candidate": _count_and_percent(both_inverts, row_count),
            "flow_direction_conflict": _count_and_percent(direction_conflict, row_count),
            "outfall_name_present": _count_and_percent(outfall.ne(""), row_count),
            "invert_up_source_values": _finite_summary(invert_up),
            "invert_down_source_values": _finite_summary(invert_down),
            "attribute_endpoints": endpoint_audit,
        },
        "topology": {
            "node_count": len(nodes),
            "unique_node_pair_count": unique_edge_count,
            "connected_component_count": len(component_roots),
            "largest_component_node_count": max(component_sizes.values(), default=0),
            "largest_component_edge_count": max(component_edge_counts.values(), default=0),
            "self_loops_after_snap": _count_and_percent(self_loop, row_count),
            "rows_in_duplicate_node_pairs": _count_and_percent(duplicate_edge, row_count),
            "duplicate_node_pair_group_count": duplicate_group_count,
            "isolated_nodes": _count_and_percent(isolated_nodes, len(nodes)),
        },
        "admission": {
            "evidence_level": "candidate",
            "admitted": False,
            "calibration_admitted": False,
            "operator_admitted": False,
            "flood_network_contract_compiled": False,
            "flood_network_blocker": (
                "pipeline_nodes_are_not_surface_patches; authoritative catchment and "
                "surface-to-network bindings, outfall and pump connectivity, engineering "
                "units and vertical datum, and event operations and observations remain missing"
            ),
        },
    }
    return frame, nodes, audit


def load_frozen_pipeline_pages(dataset_root: Path) -> tuple[Any, dict[str, Any]]:
    import geopandas as gpd
    import pandas as pd

    layer_root = (
        dataset_root.resolve()
        / "online"
        / "smartmakani"
        / "features"
        / "layer_37"
    )
    manifest_path = layer_root / "snapshot_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "complete":
        raise ValueError("pipeline_snapshot_not_complete")
    frames = []
    row_count = 0
    for page in manifest["pages"]:
        path = layer_root / page["path"]
        if sha256_file(path) != page["sha256"]:
            raise ValueError(f"pipeline_page_checksum_mismatch:{page['page_index']}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        frame = gpd.GeoDataFrame.from_features(payload.get("features", []), crs=TARGET_CRS)
        if len(frame) != page["record_count"]:
            raise ValueError(f"pipeline_page_record_count_mismatch:{page['page_index']}")
        frames.append(frame)
        row_count += len(frame)
    if row_count != manifest["expected_record_count"]:
        raise ValueError("pipeline_snapshot_total_record_count_mismatch")
    combined = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True),
        geometry="geometry",
        crs=TARGET_CRS,
    )
    return combined, manifest


def compile_frozen_pipeline_network(
    dataset_root: Path,
    *,
    output_root: Path | None = None,
    policy: PipelineCompilePolicy | None = None,
    write_geopackage: bool = True,
) -> dict[str, Any]:
    """Compile the frozen layer-37 pages and write reproducible candidate assets."""

    root = dataset_root.resolve()
    destination = (output_root or root / "derived" / "smartmakani").resolve()
    destination.mkdir(parents=True, exist_ok=True)
    pipelines, source_manifest = load_frozen_pipeline_pages(root)
    enriched, nodes, audit = compile_pipeline_topology(pipelines, policy=policy)

    pipelines_path = destination / "abu_dhabi_stormwater_pipelines.parquet"
    nodes_path = destination / "abu_dhabi_stormwater_nodes.parquet"
    pipelines_tmp = pipelines_path.with_name(f".{pipelines_path.name}.tmp")
    nodes_tmp = nodes_path.with_name(f".{nodes_path.name}.tmp")
    enriched.to_parquet(pipelines_tmp, index=False)
    nodes.to_parquet(nodes_tmp, index=False)
    pipelines_tmp.replace(pipelines_path)
    nodes_tmp.replace(nodes_path)

    outputs = {
        "pipelines_geoparquet": {
            "path": str(pipelines_path.relative_to(root)),
            "sha256": sha256_file(pipelines_path),
            "size_bytes": pipelines_path.stat().st_size,
            "row_count": len(enriched),
        },
        "nodes_geoparquet": {
            "path": str(nodes_path.relative_to(root)),
            "sha256": sha256_file(nodes_path),
            "size_bytes": nodes_path.stat().st_size,
            "row_count": len(nodes),
        },
    }
    if write_geopackage:
        geopackage_path = destination / "abu_dhabi_stormwater_network.gpkg"
        geopackage_tmp = geopackage_path.with_name(f".{geopackage_path.name}.tmp.gpkg")
        if geopackage_tmp.exists():
            geopackage_tmp.unlink()
        enriched.to_file(
            geopackage_tmp,
            layer="stormwater_pipelines",
            driver="GPKG",
            engine="pyogrio",
        )
        nodes.to_file(
            geopackage_tmp,
            layer="stormwater_nodes",
            driver="GPKG",
            engine="pyogrio",
            append=True,
        )
        geopackage_tmp.replace(geopackage_path)
        outputs["network_geopackage"] = {
            "path": str(geopackage_path.relative_to(root)),
            "sha256": sha256_file(geopackage_path),
            "size_bytes": geopackage_path.stat().st_size,
            "layers": ["stormwater_pipelines", "stormwater_nodes"],
        }

    audit["source_snapshot_fingerprint"] = source_manifest["snapshot_fingerprint"]
    audit["outputs"] = outputs
    audit_path = destination / "network_audit.json"
    _atomic_write_json(audit_path, audit)
    topology_manifest = {
        "schema": PIPELINE_TOPOLOGY_SCHEMA,
        "network_id": "abu-dhabi-smartmakani-stormwater-pipeline-candidate-v1",
        "crs": TARGET_CRS,
        "source_layer": 37,
        "source_snapshot_fingerprint": source_manifest["snapshot_fingerprint"],
        "pipeline_count": len(enriched),
        "node_count": len(nodes),
        "outputs": outputs,
        "audit": {
            "path": str(audit_path.relative_to(root)),
            "sha256": sha256_file(audit_path),
        },
        "evidence_level": "candidate",
        "admitted": False,
        "diagnostic_only": True,
        "flood_network_contract_compiled": False,
        "claim_boundary": (
            "This is a snapped public-pipeline topology candidate, not a calibrated "
            "hydraulic graph or city-scale flood predictor."
        ),
    }
    _atomic_write_json(destination / "pipeline_topology_manifest.json", topology_manifest)
    return topology_manifest
