"""Compile a customer FileGDB stormwater snapshot without publishing source rows.

The adapter intentionally separates public implementation code from private
customer-derived artifacts. Source identifiers are used in memory to reconcile
topology, but they are not written to the normalized outputs or aggregate audit.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .network_compiler import PipelineCompilePolicy, compile_pipeline_topology
from .registered_network_compiler import aggregate_facility_attachments_to_nodes
from .registered_swmm_diagnostic import (
    RegisteredSwmmDiagnosticPolicy,
    render_registered_swmm_input,
    select_registered_subnetwork,
)
from .smartmakani_acquisition import TARGET_CRS, canonical_json_bytes

CUSTOMER_GDB_NETWORK_SCHEMA = "gwm.abu_dhabi_flood.customer_gdb_network.v1"
CUSTOMER_GDB_AUDIT_SCHEMA = "gwm.abu_dhabi_flood.customer_gdb_network_audit.v1"
CUSTOMER_GDB_SWMM_SCHEMA = "gwm.abu_dhabi_flood.customer_gdb_swmm_diagnostic.v1"
CUSTOMER_GDB_SWMM_BATCH_SCHEMA = (
    "gwm.abu_dhabi_flood.customer_gdb_swmm_diagnostic_batch.v1"
)
CUSTOMER_GDB_GWM_GRAPH_SCHEMA = "gwm.abu_dhabi_flood.customer_gdb_gwm_static_graph.v1"
CUSTOMER_GDB_GWM_TENSOR_SCHEMA = (
    "gwm.abu_dhabi_flood.customer_gdb_gwm_static_tensors.v1"
)
CUSTOMER_GDB_SWMM_GWM_ALIGNMENT_SCHEMA = (
    "gwm.abu_dhabi_flood.customer_gdb_swmm_gwm_alignment.v1"
)
CUSTOMER_GDB_SWMM_GWM_DYNAMIC_SCHEMA = (
    "gwm.abu_dhabi_flood.customer_gdb_swmm_gwm_dynamic_diagnostic.v1"
)
CUSTOMER_GDB_GWM_WINDOW_SCHEMA = (
    "gwm.abu_dhabi_flood.customer_gdb_gwm_input_window_shapes.v1"
)

TARGET_BBOX_EPSG32640 = (
    225623.2395648436,
    2687161.5223497953,
    273803.2395648436,
    2723551.5223497953,
)

_FACILITY_LAYERS = {
    "INLET": "inlet",
    "CATCHBASIN": "catchbasin",
    "SW_NODE": "node",
    "SW_JUNCTION": "junction",
    "OUTFALL": "outfall",
    "PS_PUMP": "pump",
    "SOAKAWAY": "soakaway",
    "SW_CAPPEDEND": "capped_end",
}

_SENTINELS = frozenset(
    {
        "",
        "NC",
        "N/C",
        "N.A",
        "N/A",
        "NA",
        "NONE",
        "NULL",
        "UNKNOWN",
        "NOT CONNECTED",
        "NOT APPLICABLE",
        "0",
        "-",
        "NIL",
    }
)

_PRIVATE_PIPELINE_COLUMNS = (
    "registered_pipeline_fid",
    "source_node_id",
    "target_node_id",
    "recomputed_length_m",
    "diameter_numeric",
    "invert_up_numeric",
    "invert_down_numeric",
    "invert_up_plausible_candidate",
    "invert_down_plausible_candidate",
    "flow_direction_conflict",
    "self_loop_after_snap",
    "duplicate_node_pair",
    "pipe_material",
    "pipeline_status",
    "geometry_supported",
    "geometry",
)

_PRIVATE_NODE_COLUMNS = (
    "node_id",
    "snap_x_m",
    "snap_y_m",
    "component_id",
    "component_node_count",
    "degree",
    "endpoint_count",
    "candidate_surface_intake_count",
    "candidate_outfall_count",
    "candidate_pump_count",
    "candidate_facility_count",
    "candidate_facility_roles",
    "geometry",
)

_PRIVATE_FACILITY_COLUMNS = (
    "node_id",
    "facility_role",
    "registered_facility_fid",
    "minimum_endpoint_distance_m",
    "endpoint_roles",
    "geometry_endpoints",
    "match_method",
    "evidence_level",
    "admitted",
)


@dataclass(frozen=True)
class CustomerGdbCompilePolicy:
    """Fail-closed policy for the customer stormwater FileGDB adapter."""

    bbox_epsg32640: tuple[float, float, float, float] = TARGET_BBOX_EPSG32640
    snap_tolerance_m: float = 0.1
    maximum_facility_attachment_distance_m: float = 1.0
    plausible_invert_min_m: float = -20.0
    plausible_invert_max_m: float = 100.0
    derived_facility_depth_m: float = 1.2
    derived_facility_depth_tolerance_m: float = 1.0e-6

    def __post_init__(self) -> None:
        if len(self.bbox_epsg32640) != 4 or not all(
            isinstance(value, (int, float)) and math.isfinite(value)
            for value in self.bbox_epsg32640
        ):
            raise ValueError("customer_gdb_bbox_invalid")
        xmin, ymin, xmax, ymax = self.bbox_epsg32640
        if xmin >= xmax or ymin >= ymax:
            raise ValueError("customer_gdb_bbox_order_invalid")
        positive = (
            self.snap_tolerance_m,
            self.maximum_facility_attachment_distance_m,
            self.derived_facility_depth_m,
            self.derived_facility_depth_tolerance_m,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("customer_gdb_positive_policy_value_invalid")
        if self.plausible_invert_min_m >= self.plausible_invert_max_m:
            raise ValueError("customer_gdb_invert_bounds_invalid")


@dataclass(frozen=True)
class CustomerGdbSwmmBatchPolicy:
    """Selection limits for a diverse, diagnostic-only SWMM pilot batch."""

    maximum_pilots: int = 5
    maximum_candidate_attempts: int = 30
    maximum_edge_overlap_fraction: float = 0.75

    def __post_init__(self) -> None:
        if (
            isinstance(self.maximum_pilots, bool)
            or not isinstance(self.maximum_pilots, int)
            or self.maximum_pilots < 1
        ):
            raise ValueError("customer_gdb_swmm_batch_maximum_pilots_invalid")
        if (
            isinstance(self.maximum_candidate_attempts, bool)
            or not isinstance(self.maximum_candidate_attempts, int)
            or self.maximum_candidate_attempts < self.maximum_pilots
        ):
            raise ValueError("customer_gdb_swmm_batch_candidate_attempts_invalid")
        if not 0.0 <= self.maximum_edge_overlap_fraction <= 1.0:
            raise ValueError("customer_gdb_swmm_batch_overlap_fraction_invalid")


@dataclass(frozen=True)
class CustomerGwmStaticTensorPolicy:
    """Private tensor layout policy; this does not admit dynamic GWM training."""

    maximum_nodes_per_partition: int = 8192

    def __post_init__(self) -> None:
        if (
            isinstance(self.maximum_nodes_per_partition, bool)
            or not isinstance(self.maximum_nodes_per_partition, int)
            or self.maximum_nodes_per_partition < 128
        ):
            raise ValueError("customer_gwm_partition_size_invalid")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(canonical_json_bytes(payload))
    temporary.replace(path)


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value, encoding="ascii")
    temporary.replace(path)


def _artifact(path: Path, root: Path, *, record_count: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": str(path.relative_to(root)),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }
    if record_count is not None:
        payload["record_count"] = record_count
    return payload


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _require_private_output_root(output_root: Path) -> Path:
    root = output_root.expanduser().resolve()
    repository = _repository_root()
    try:
        root.relative_to(repository)
    except ValueError:
        return root
    raise ValueError("customer_gdb_output_must_be_outside_public_repository")


def _column(frame: Any, name: str) -> str | None:
    return next(
        (column for column in frame.columns if str(column).casefold() == name.casefold()),
        None,
    )


def _series(frame: Any, name: str, *, default: object = None) -> Any:
    import pandas as pd

    column = _column(frame, name)
    if column is None:
        return pd.Series(default, index=frame.index)
    return frame[column]


def _normalized(value: object) -> str | None:
    if value is None:
        return None
    result = str(value).strip().upper()
    if result in _SENTINELS:
        return None
    return result


def _read_layer(
    gdb_path: Path,
    layer: str,
    *,
    bbox: tuple[float, float, float, float],
    columns: tuple[str, ...],
) -> Any:
    import pyogrio

    available = {
        str(field)
        for field in pyogrio.read_info(gdb_path, layer=layer)["fields"]
    }
    selected = [field for field in columns if field in available]
    frame = pyogrio.read_dataframe(
        gdb_path,
        layer=layer,
        columns=selected,
        bbox=bbox,
        use_arrow=True,
    )
    if frame.crs is None:
        raise ValueError(f"customer_gdb_layer_crs_required:{layer}")
    return frame.to_crs(TARGET_CRS).reset_index(drop=True)


def load_customer_gdb_snapshot(
    gdb_path: Path,
    *,
    policy: CustomerGdbCompilePolicy | None = None,
) -> tuple[Any, Any, dict[str, Any]]:
    """Load only the target-area columns needed for network compilation."""

    import geopandas as gpd
    import pandas as pd
    import pyogrio

    active = policy or CustomerGdbCompilePolicy()
    source = gdb_path.expanduser().resolve()
    if not source.is_dir() or source.suffix.casefold() != ".gdb":
        raise ValueError("customer_gdb_directory_required")
    layer_names = {str(name) for name in pyogrio.list_layers(source)[:, 0]}
    required = {"PIPELINE", "INLET", "CATCHBASIN", "OUTFALL"}
    missing = sorted(required.difference(layer_names))
    if missing:
        raise ValueError(f"customer_gdb_required_layers_missing:{','.join(missing)}")

    pipeline_fields = (
        "UNITID",
        "UID",
        "ASSET_BEFORE",
        "ASSET_AFTER",
        "OUTFALLID",
        "StartCode",
        "EndCode",
        "StartElev",
        "EndElev",
        "StartX",
        "StartY",
        "EndX",
        "EndY",
        "Diameter",
        "PIPE_DIAMETER",
        "PIPE_MATERIAL",
        "STATUS",
        "CONDITION",
    )
    pipelines = _read_layer(
        source,
        "PIPELINE",
        bbox=active.bbox_epsg32640,
        columns=pipeline_fields,
    )
    pipelines["fid"] = pd.RangeIndex(1, len(pipelines) + 1, dtype="int64")
    pipelines["registered_pipeline_fid"] = pipelines["fid"]
    pipelines["OBJECTID"] = pipelines["fid"]
    pipelines["ASSET_DIAMETER"] = pd.to_numeric(
        _series(pipelines, "Diameter", default=math.nan), errors="coerce"
    ).fillna(
        pd.to_numeric(
            _series(pipelines, "PIPE_DIAMETER", default=math.nan),
            errors="coerce",
        )
    )
    pipelines["INVERT_LEVEL_UP"] = pd.to_numeric(
        _series(pipelines, "StartElev", default=math.nan), errors="coerce"
    )
    pipelines["INVERT_LEVEL_DOWN"] = pd.to_numeric(
        _series(pipelines, "EndElev", default=math.nan), errors="coerce"
    )
    for source_field, target_field in (
        ("StartX", "Start_X"),
        ("StartY", "Start_Y"),
        ("EndX", "End_X"),
        ("EndY", "End_Y"),
    ):
        pipelines[target_field] = pd.to_numeric(
            _series(pipelines, source_field, default=math.nan), errors="coerce"
        )
    pipelines["pipe_material"] = _series(pipelines, "PIPE_MATERIAL", default=None)
    pipelines["pipeline_status"] = _series(pipelines, "STATUS", default=None)

    facility_frames = []
    facility_offset = 0
    layer_counts: dict[str, int] = {}
    for layer, role in _FACILITY_LAYERS.items():
        if layer not in layer_names:
            continue
        frame = _read_layer(
            source,
            layer,
            bbox=active.bbox_epsg32640,
            columns=(
                "UNITID",
                "PointCode",
                "OUTFALL_NAME",
                "MAINASSETNAME",
                "GroundElev",
                "WellBottomElev",
                "STATUS",
                "CONDITION",
            ),
        )
        frame["facility_role"] = role
        frame["facility_layer"] = layer
        frame["registered_facility_fid"] = pd.RangeIndex(
            facility_offset + 1,
            facility_offset + len(frame) + 1,
            dtype="int64",
        )
        frame["fid"] = frame["registered_facility_fid"]
        facility_offset += len(frame)
        layer_counts[layer] = len(frame)
        facility_frames.append(frame)
    facilities = gpd.GeoDataFrame(
        pd.concat(facility_frames, ignore_index=True),
        geometry="geometry",
        crs=TARGET_CRS,
    )
    receipt = {
        "pipeline_count": len(pipelines),
        "facility_count": len(facilities),
        "facility_layer_counts": layer_counts,
        "crs": TARGET_CRS,
        "bbox_epsg32640": list(active.bbox_epsg32640),
        "source_path_persisted": False,
        "source_identifiers_persisted": False,
    }
    return pipelines, facilities, receipt


def _facility_identifier_index(facilities: Any) -> tuple[dict[str, int], dict[str, Any]]:
    identifier_rows: dict[str, set[int]] = defaultdict(set)
    for row in facilities.itertuples(index=False):
        facility_id = int(row.registered_facility_fid)
        for field in ("UNITID", "PointCode", "OUTFALL_NAME", "MAINASSETNAME"):
            value = _normalized(getattr(row, field, None))
            if value is not None:
                identifier_rows[value].add(facility_id)
    unique = {
        identifier: next(iter(ids))
        for identifier, ids in identifier_rows.items()
        if len(ids) == 1
    }
    return unique, {
        "distinct_identifier_count": len(identifier_rows),
        "unique_identifier_count": len(unique),
        "ambiguous_identifier_count": sum(len(ids) > 1 for ids in identifier_rows.values()),
    }


def compile_customer_facility_attachments(
    source_pipelines: Any,
    compiled_pipelines: Any,
    facilities: Any,
    *,
    maximum_distance_m: float = 1.0,
) -> tuple[Any, dict[str, Any]]:
    """Match endpoints by unique references, then use spatial fallback."""

    import numpy as np
    import pandas as pd
    import shapely
    from shapely.strtree import STRtree

    if maximum_distance_m <= 0:
        raise ValueError("customer_gdb_facility_distance_invalid")
    if len(source_pipelines) != len(compiled_pipelines):
        raise ValueError("customer_gdb_pipeline_alignment_changed")
    unique_identifiers, identifier_audit = _facility_identifier_index(facilities)
    facility_index = facilities.set_index("registered_facility_fid", drop=False)
    rows: list[dict[str, Any]] = []
    endpoint_matched: set[tuple[int, str]] = set()
    reference_counts = Counter()
    accepted_reference_counts = Counter()
    ambiguous_or_missing_reference_counts = Counter()

    reference_specs = (
        ("geometry_start", "asset_before", "StartCode", None),
        ("geometry_start", "asset_before", "ASSET_BEFORE", None),
        ("geometry_end", "asset_after", "EndCode", None),
        ("geometry_end", "asset_after", "ASSET_AFTER", None),
        ("geometry_end", "asset_after", "OUTFALLID", "outfall"),
    )
    for row_index, (source_row, compiled_row) in enumerate(
        zip(
            source_pipelines.itertuples(index=False),
            compiled_pipelines.itertuples(index=False),
            strict=True,
        )
    ):
        pipeline_id = int(compiled_row.registered_pipeline_fid)
        endpoints = {
            "geometry_start": shapely.Point(
                float(compiled_row.geometry_start_x_m),
                float(compiled_row.geometry_start_y_m),
            ),
            "geometry_end": shapely.Point(
                float(compiled_row.geometry_end_x_m),
                float(compiled_row.geometry_end_y_m),
            ),
        }
        accepted_keys: set[tuple[str, int]] = set()
        for geometry_endpoint, endpoint_role, field, required_role in reference_specs:
            value = _normalized(getattr(source_row, field, None))
            if value is None:
                continue
            reference_counts[field] += 1
            facility_id = unique_identifiers.get(value)
            if facility_id is None:
                ambiguous_or_missing_reference_counts[field] += 1
                continue
            facility = facility_index.loc[facility_id]
            if required_role is not None and str(facility["facility_role"]) != required_role:
                ambiguous_or_missing_reference_counts[field] += 1
                continue
            distance = float(endpoints[geometry_endpoint].distance(facility.geometry))
            if not math.isfinite(distance) or distance > maximum_distance_m:
                continue
            key = (geometry_endpoint, facility_id)
            if key in accepted_keys:
                continue
            accepted_keys.add(key)
            endpoint_matched.add((row_index, geometry_endpoint))
            accepted_reference_counts[field] += 1
            rows.append(
                {
                    "registered_pipeline_fid": pipeline_id,
                    "endpoint_role": endpoint_role,
                    "facility_role": str(facility["facility_role"]),
                    "registered_facility_fid": facility_id,
                    "nearest_geometry_endpoint": geometry_endpoint,
                    "nearest_endpoint_distance_m": distance,
                    "match_method": "unique_identifier_and_endpoint_distance",
                    "reference_field": field,
                    "evidence_level": "candidate_high",
                    "admitted": False,
                }
            )

    facility_geometries = np.asarray(facilities.geometry.array, dtype="object")
    tree = STRtree(facility_geometries)
    unmatched_points = []
    unmatched_metadata = []
    for row_index, compiled_row in enumerate(compiled_pipelines.itertuples(index=False)):
        for geometry_endpoint, endpoint_role, x_field, y_field in (
            ("geometry_start", "asset_before", "geometry_start_x_m", "geometry_start_y_m"),
            ("geometry_end", "asset_after", "geometry_end_x_m", "geometry_end_y_m"),
        ):
            if (row_index, geometry_endpoint) in endpoint_matched:
                continue
            x = float(getattr(compiled_row, x_field))
            y = float(getattr(compiled_row, y_field))
            if not math.isfinite(x) or not math.isfinite(y):
                continue
            unmatched_points.append(shapely.Point(x, y))
            unmatched_metadata.append(
                (
                    row_index,
                    int(compiled_row.registered_pipeline_fid),
                    geometry_endpoint,
                    endpoint_role,
                )
            )
    spatial_accepted = 0
    if unmatched_points:
        indexes, distances = tree.query_nearest(
            np.asarray(unmatched_points, dtype="object"),
            return_distance=True,
            all_matches=False,
        )
        for query_index, facility_position, distance in zip(
            indexes[0], indexes[1], distances, strict=True
        ):
            if float(distance) > maximum_distance_m:
                continue
            row_index, pipeline_id, geometry_endpoint, endpoint_role = unmatched_metadata[
                int(query_index)
            ]
            facility = facilities.iloc[int(facility_position)]
            spatial_accepted += 1
            endpoint_matched.add((row_index, geometry_endpoint))
            rows.append(
                {
                    "registered_pipeline_fid": pipeline_id,
                    "endpoint_role": endpoint_role,
                    "facility_role": str(facility["facility_role"]),
                    "registered_facility_fid": int(facility["registered_facility_fid"]),
                    "nearest_geometry_endpoint": geometry_endpoint,
                    "nearest_endpoint_distance_m": float(distance),
                    "match_method": "nearest_facility_spatial_fallback",
                    "reference_field": None,
                    "evidence_level": "candidate_medium",
                    "admitted": False,
                }
            )
    attachments = pd.DataFrame(rows)
    if not attachments.empty:
        attachments = attachments.sort_values(
            [
                "registered_pipeline_fid",
                "nearest_geometry_endpoint",
                "registered_facility_fid",
                "match_method",
            ]
        ).reset_index(drop=True)
    supported_endpoint_count = int(compiled_pipelines["geometry_supported"].sum()) * 2
    audit = {
        "identifier_index": identifier_audit,
        "reference_counts": dict(sorted(reference_counts.items())),
        "accepted_reference_counts": dict(sorted(accepted_reference_counts.items())),
        "ambiguous_or_missing_reference_counts": dict(
            sorted(ambiguous_or_missing_reference_counts.items())
        ),
        "identifier_attachment_count": len(rows) - spatial_accepted,
        "spatial_fallback_attachment_count": spatial_accepted,
        "attachment_count": len(attachments),
        "mapped_pipeline_endpoint_count": len(endpoint_matched),
        "supported_pipeline_endpoint_count": supported_endpoint_count,
        "mapped_pipeline_endpoint_percent": round(
            100.0 * len(endpoint_matched) / supported_endpoint_count
            if supported_endpoint_count
            else 0.0,
            6,
        ),
        "maximum_distance_m": maximum_distance_m,
        "source_identifiers_persisted": False,
        "authoritative_connectivity_established": False,
    }
    return attachments, audit


def _facility_depth_audit(
    facilities: Any,
    policy: CustomerGdbCompilePolicy,
) -> dict[str, Any]:
    import numpy as np
    import pandas as pd

    ground = pd.to_numeric(_series(facilities, "GroundElev", default=math.nan), errors="coerce")
    bottom = pd.to_numeric(
        _series(facilities, "WellBottomElev", default=math.nan), errors="coerce"
    )
    comparable = ground.notna() & bottom.notna()
    depth = (ground[comparable] - bottom[comparable]).to_numpy(dtype="float64")
    derived = np.isclose(
        depth,
        policy.derived_facility_depth_m,
        atol=policy.derived_facility_depth_tolerance_m,
        rtol=0.0,
    )
    return {
        "comparable_count": int(comparable.sum()),
        "exact_derived_depth_count": int(derived.sum()),
        "exact_derived_depth_percent": round(
            100.0 * int(derived.sum()) / int(comparable.sum()) if comparable.any() else 0.0,
            6,
        ),
        "derived_depth_m": policy.derived_facility_depth_m,
        "engineering_facility_bottom_elevation_admitted": False,
    }


def build_customer_gwm_static_graph_contract(
    pipelines: Any,
    nodes: Any,
    links: Any,
) -> dict[str, Any]:
    """Describe the compiled GWM graph surface without persisting row details."""

    import pandas as pd

    edge_count = len(pipelines)
    node_count = len(nodes)
    geometry_usable = pipelines["geometry_supported"].fillna(False) & pipelines[
        "recomputed_length_m"
    ].gt(0.01)
    topology_clean = (
        geometry_usable
        & ~pipelines["self_loop_after_snap"].fillna(True)
        & ~pipelines["duplicate_node_pair"].fillna(True)
    )
    diagnostic_direction = (
        topology_clean
        & ~pipelines["flow_direction_conflict"].fillna(True)
        & pipelines["diameter_numeric"].between(100.0, 3000.0, inclusive="both")
        & pipelines["invert_up_plausible_candidate"].fillna(False)
        & pipelines["invert_down_plausible_candidate"].fillna(False)
    )
    material = pipelines["pipe_material"].astype("string").fillna("").str.strip()
    status = pipelines["pipeline_status"].astype("string").fillna("").str.strip()
    facility_role_counts = {
        str(role): int(count)
        for role, count in links["facility_role"].value_counts().sort_index().items()
    }

    def count_percent(mask: Any, denominator: int) -> dict[str, float | int]:
        count = int(pd.Series(mask).fillna(False).sum())
        return {
            "count": count,
            "percent": round(100.0 * count / denominator if denominator else 0.0, 6),
        }

    component_sizes = nodes[["component_id", "component_node_count"]].drop_duplicates(
        "component_id"
    )
    return {
        "schema": CUSTOMER_GDB_GWM_GRAPH_SCHEMA,
        "graph": {
            "edge_count": edge_count,
            "node_count": node_count,
            "connected_component_count": len(component_sizes),
            "largest_component_node_count": int(
                component_sizes["component_node_count"].max()
                if len(component_sizes)
                else 0
            ),
            "facility_link_count": len(links),
            "facility_role_counts": facility_role_counts,
            "directed_edges_are_engineering_verified": False,
        },
        "quality_masks": {
            "geometry_usable": count_percent(geometry_usable, edge_count),
            "topology_clean": count_percent(topology_clean, edge_count),
            "diagnostic_processed_elevation_direction": count_percent(
                diagnostic_direction, edge_count
            ),
            "pipe_material_present": count_percent(material.ne(""), edge_count),
            "pipeline_status_present": count_percent(status.ne(""), edge_count),
            "nodes_with_surface_intake_candidate": count_percent(
                nodes["candidate_surface_intake_count"].gt(0), node_count
            ),
            "nodes_with_outfall_candidate": count_percent(
                nodes["candidate_outfall_count"].gt(0), node_count
            ),
            "nodes_with_pump_candidate": count_percent(
                nodes["candidate_pump_count"].gt(0), node_count
            ),
        },
        "static_feature_contract": {
            "edge_features_available": [
                "recomputed_length_m",
                "diameter_numeric_unit_unverified",
                "pipe_material",
                "pipeline_status",
                "processed_endpoint_elevations_diagnostic_only",
                "topology_quality_masks",
            ],
            "node_features_available": [
                "projected_coordinates_private",
                "degree",
                "component_membership",
                "facility_role_counts",
                "intake_outfall_and_pump_candidate_masks",
            ],
            "source_asset_identifiers_persisted": False,
            "facility_bottom_elevation_consumed": False,
        },
        "dynamic_feature_gaps": [
            "customer_event_rainfall_or_radar_qpe",
            "coastal_tide_and_surge_boundary_series",
            "pump_gate_storage_and_outfall_operations",
            "timed_pipe_node_and_surface_hydraulic_states",
            "timed_inundation_depth_extent_and_recession_labels",
            "maintenance_blockage_and_failure_history",
        ],
        "readiness": {
            "static_graph_compiled": True,
            "static_encoder_development_allowed": True,
            "traditional_model_distillation_training_allowed": False,
            "supervised_state_transition_training_allowed": False,
            "action_conditioned_training_allowed": False,
            "blind_validation_possible": False,
            "gwm_training_admitted": False,
            "city_scale_prediction_claim_allowed": False,
        },
        "privacy": {
            "aggregate_contract_only": True,
            "single_asset_or_node_details_persisted": False,
            "customer_rows_in_public_repository": False,
        },
    }


def compile_customer_gdb_network(
    gdb_path: Path,
    *,
    output_root: Path,
    policy: CustomerGdbCompilePolicy | None = None,
    source_archive_path: Path | None = None,
) -> dict[str, Any]:
    """Compile private normalized artifacts and an aggregate-only receipt."""

    import geopandas as gpd

    active = policy or CustomerGdbCompilePolicy()
    destination = _require_private_output_root(output_root)
    destination.mkdir(parents=True, exist_ok=True)
    source_pipelines, facilities, intake = load_customer_gdb_snapshot(
        gdb_path,
        policy=active,
    )
    topology_policy = PipelineCompilePolicy(
        snap_tolerance_m=active.snap_tolerance_m,
        zero_length_tolerance_m=0.01,
        endpoint_match_tolerance_m=1.0,
        plausible_invert_min=active.plausible_invert_min_m,
        plausible_invert_max=active.plausible_invert_max_m,
    )
    compiled_pipelines, nodes, topology_audit = compile_pipeline_topology(
        source_pipelines,
        policy=topology_policy,
    )
    compiled_pipelines["registered_pipeline_fid"] = source_pipelines[
        "registered_pipeline_fid"
    ]
    compiled_pipelines["pipe_material"] = source_pipelines["pipe_material"]
    compiled_pipelines["pipeline_status"] = source_pipelines["pipeline_status"]
    attachments, attachment_audit = compile_customer_facility_attachments(
        source_pipelines,
        compiled_pipelines,
        facilities,
        maximum_distance_m=active.maximum_facility_attachment_distance_m,
    )
    enriched_nodes, links, node_facility_audit = aggregate_facility_attachments_to_nodes(
        compiled_pipelines,
        nodes,
        attachments,
        maximum_distance_m=active.maximum_facility_attachment_distance_m,
    )
    if not links.empty:
        links["match_method"] = "customer_multi_evidence_endpoint_match"

    private_pipelines = gpd.GeoDataFrame(
        compiled_pipelines[list(_PRIVATE_PIPELINE_COLUMNS)].copy(),
        geometry="geometry",
        crs=TARGET_CRS,
    )
    private_nodes = gpd.GeoDataFrame(
        enriched_nodes[list(_PRIVATE_NODE_COLUMNS)].copy(),
        geometry="geometry",
        crs=TARGET_CRS,
    )
    private_links = links[list(_PRIVATE_FACILITY_COLUMNS)].copy()
    pipelines_path = destination / "customer_stormwater_pipelines.private.parquet"
    nodes_path = destination / "customer_stormwater_nodes.private.parquet"
    links_path = destination / "customer_node_facilities.private.parquet"
    private_pipelines.to_parquet(pipelines_path, index=False)
    private_nodes.to_parquet(nodes_path, index=False)
    private_links.to_parquet(links_path, index=False)

    archive_receipt = None
    if source_archive_path is not None:
        archive = source_archive_path.expanduser().resolve()
        if not archive.is_file():
            raise ValueError("customer_gdb_source_archive_missing")
        archive_receipt = {
            "logical_name": archive.name,
            "size_bytes": archive.stat().st_size,
            "sha256": _sha256_file(archive),
        }
    outputs = {
        "pipelines_private_geoparquet": _artifact(
            pipelines_path, destination, record_count=len(private_pipelines)
        ),
        "nodes_private_geoparquet": _artifact(
            nodes_path, destination, record_count=len(private_nodes)
        ),
        "node_facilities_private_parquet": _artifact(
            links_path, destination, record_count=len(private_links)
        ),
    }
    aggregate_audit = {
        "schema": CUSTOMER_GDB_AUDIT_SCHEMA,
        "intake": intake,
        "topology": topology_audit,
        "facility_attachments": attachment_audit,
        "node_facilities": node_facility_audit,
        "facility_elevation": _facility_depth_audit(facilities, active),
        "privacy": {
            "aggregate_only": True,
            "source_paths_persisted": False,
            "source_asset_identifiers_persisted": False,
            "customer_rows_in_public_repository": False,
        },
        "admission": {
            "network_cleanup_and_prototype_allowed": True,
            "network_engineering_admitted": False,
            "traditional_model_calibration_admitted": False,
            "gwm_training_admitted": False,
            "city_scale_prediction_claim_allowed": False,
        },
    }
    audit_path = destination / "customer_gdb_network_aggregate_audit.json"
    _atomic_write_json(audit_path, aggregate_audit)
    outputs["aggregate_audit"] = _artifact(audit_path, destination)
    gwm_graph_contract = build_customer_gwm_static_graph_contract(
        private_pipelines,
        private_nodes,
        private_links,
    )
    gwm_graph_path = destination / "customer_gwm_static_graph_contract.json"
    _atomic_write_json(gwm_graph_path, gwm_graph_contract)
    outputs["gwm_static_graph_contract"] = _artifact(gwm_graph_path, destination)
    manifest: dict[str, Any] = {
        "schema": CUSTOMER_GDB_NETWORK_SCHEMA,
        "network_id": "abu-dhabi-customer-stormwater-private-candidate-v1",
        "source_archive": archive_receipt,
        "source_gdb_path_persisted": False,
        "policy": asdict(active),
        "outputs": outputs,
        "contains_customer_derived_geometry": True,
        "storage_class": "private_customer_controlled_not_for_public_repository",
        "source_asset_identifiers_persisted": False,
        "evidence_level": "customer_provided_geometry_engineering_semantics_unverified",
        "diagnostic_only": True,
        "admitted": False,
        "claim_boundary": [
            "customer_geometry_received_and_normalized",
            "topology_requires_reconciliation",
            "processed_elevations_and_vertical_datum_not_engineering_admitted",
            "pump_operations_tide_rainfall_and_inundation_observations_not_included",
            "not_a_calibrated_or_city_scale_prediction_model",
        ],
    }
    manifest_path = destination / "customer_gdb_network_private_manifest.json"
    _atomic_write_json(manifest_path, manifest)
    manifest["manifest"] = _artifact(manifest_path, destination)
    return manifest


def load_customer_private_network(output_root: Path) -> tuple[Any, Any, Any, dict[str, Any]]:
    """Load customer-derived artifacts only after hash and boundary validation."""

    import geopandas as gpd
    import pandas as pd

    root = _require_private_output_root(output_root)
    manifest_path = root / "customer_gdb_network_private_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != CUSTOMER_GDB_NETWORK_SCHEMA:
        raise ValueError("customer_gdb_private_manifest_schema_invalid")
    if manifest.get("admitted") is not False or manifest.get("diagnostic_only") is not True:
        raise ValueError("customer_gdb_private_manifest_boundary_invalid")
    outputs = manifest["outputs"]

    def verified(key: str) -> Path:
        artifact = outputs[key]
        path = (root / artifact["path"]).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("customer_gdb_artifact_outside_private_root") from exc
        if not path.is_file() or _sha256_file(path) != artifact["sha256"]:
            raise ValueError(f"customer_gdb_artifact_integrity_failed:{key}")
        return path

    pipelines = gpd.read_parquet(verified("pipelines_private_geoparquet"))
    nodes = gpd.read_parquet(verified("nodes_private_geoparquet"))
    links = pd.read_parquet(verified("node_facilities_private_parquet"))
    expected = (
        (pipelines, "pipelines_private_geoparquet"),
        (nodes, "nodes_private_geoparquet"),
        (links, "node_facilities_private_parquet"),
    )
    for frame, key in expected:
        if len(frame) != outputs[key].get("record_count"):
            raise ValueError(f"customer_gdb_artifact_record_count_failed:{key}")
    return pipelines, nodes, links, manifest


def select_customer_gdb_swmm_pilot_batch(
    pipelines: Any,
    nodes: Any,
    links: Any,
    *,
    selection_policy: RegisteredSwmmDiagnosticPolicy,
    batch_policy: CustomerGdbSwmmBatchPolicy | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select several outfall-rooted pilots while limiting edge overlap."""

    active = batch_policy or CustomerGdbSwmmBatchPolicy()
    remaining = links.copy()
    selected: list[dict[str, Any]] = []
    selected_edge_sets: list[set[int]] = []
    attempt_count = 0
    rejected_for_overlap = 0
    first_candidate_outfall_count = 0
    while (
        len(selected) < active.maximum_pilots
        and attempt_count < active.maximum_candidate_attempts
    ):
        try:
            candidate = select_registered_subnetwork(
                pipelines,
                nodes,
                remaining,
                policy=selection_policy,
            )
        except ValueError as exc:
            if str(exc) in {
                "registered_swmm_outfall_candidate_required",
                "registered_swmm_no_outfall_subnetwork_meets_minimum_edges",
            }:
                break
            raise
        attempt_count += 1
        if first_candidate_outfall_count == 0:
            first_candidate_outfall_count = int(
                candidate["selection_candidate_outfall_count"]
            )
        root_node_id = str(candidate["root_node_id"])
        edge_ids = {
            int(value) for value in candidate["edges"]["registered_pipeline_fid"]
        }
        overlap_fractions = [
            len(edge_ids.intersection(previous)) / min(len(edge_ids), len(previous))
            for previous in selected_edge_sets
            if edge_ids and previous
        ]
        maximum_overlap = max(overlap_fractions, default=0.0)
        candidate["maximum_previous_edge_overlap_fraction"] = maximum_overlap
        remaining = remaining[
            ~(
                remaining["facility_role"].eq("outfall")
                & remaining["node_id"].eq(root_node_id)
            )
        ].copy()
        if maximum_overlap > active.maximum_edge_overlap_fraction:
            rejected_for_overlap += 1
            continue
        selected.append(candidate)
        selected_edge_sets.append(edge_ids)

    if not selected:
        raise ValueError("customer_gdb_swmm_no_diverse_pilot_selected")
    audit = {
        "selection_algorithm": (
            "ranked_outfall_rooted_upstream_trees_with_pairwise_edge_overlap_limit"
        ),
        "source_candidate_outfall_count": first_candidate_outfall_count,
        "attempted_candidate_count": attempt_count,
        "selected_pilot_count": len(selected),
        "rejected_for_overlap_count": rejected_for_overlap,
        "maximum_selected_edge_overlap_fraction": round(
            max(
                (
                    float(item["maximum_previous_edge_overlap_fraction"])
                    for item in selected
                ),
                default=0.0,
            ),
            8,
        ),
        "batch_policy": asdict(active),
        "source_asset_identifiers_persisted": False,
    }
    return selected, audit


def compile_customer_gdb_swmm_diagnostic_batch(
    output_root: Path,
    *,
    hourly_precipitation_mm: tuple[float, ...],
    forcing_descriptor: dict[str, Any],
    selection_policy: RegisteredSwmmDiagnosticPolicy | None = None,
    batch_policy: CustomerGdbSwmmBatchPolicy | None = None,
) -> dict[str, Any]:
    """Compile a diverse private SWMM pilot batch from normalized customer data."""

    active_selection = selection_policy or RegisteredSwmmDiagnosticPolicy(
        maximum_edges=48,
        maximum_upstream_hops=10,
        minimum_edges=4,
    )
    active_batch = batch_policy or CustomerGdbSwmmBatchPolicy()
    root = _require_private_output_root(output_root)
    pipelines, nodes, links, manifest = load_customer_private_network(root)
    selections, selection_audit = select_customer_gdb_swmm_pilot_batch(
        pipelines,
        nodes,
        links,
        selection_policy=active_selection,
        batch_policy=active_batch,
    )
    pilots = []
    for pilot_number, selection in enumerate(selections, start=1):
        pilot_id = f"pilot_{pilot_number:02d}"
        input_text, ledger = render_registered_swmm_input(
            selection,
            hourly_precipitation_mm,
            forcing_label=str(forcing_descriptor.get("model_label", "Diagnostic")),
        )
        input_path = root / f"customer_stormwater_{pilot_id}_diagnostic.inp"
        _atomic_write_text(input_path, input_text)
        selected_facilities = selection["facilities"]
        role_counts = {
            str(role): int(count)
            for role, count in selected_facilities["facility_role"]
            .value_counts()
            .sort_index()
            .items()
        }
        pilots.append(
            {
                "pilot_id": pilot_id,
                "selection": {
                    "selected_pipeline_count": len(selection["edges"]),
                    "selected_node_count": len(selection["nodes"]),
                    "selected_surface_intake_node_count": len(
                        selection["intake_node_ids"]
                    ),
                    "selected_facility_role_counts": role_counts,
                    "maximum_previous_edge_overlap_fraction": round(
                        float(selection["maximum_previous_edge_overlap_fraction"]),
                        8,
                    ),
                    "source_asset_identifiers_persisted": False,
                },
                "model_input": {
                    **_artifact(input_path, root),
                    "flow_units": "CMS",
                    "routing_method": "KINWAVE",
                    "aggregate_ledger": {
                        "junction_count": ledger["junction_count"],
                        "outfall_count": ledger["outfall_count"],
                        "conduit_count": ledger["conduit_count"],
                        "subcatchment_count": ledger["subcatchment_count"],
                        "rainfall_interval_count": ledger["rainfall_interval_count"],
                        "single_asset_or_node_details_persisted": False,
                    },
                },
            }
        )
    receipt = {
        "schema": CUSTOMER_GDB_SWMM_BATCH_SCHEMA,
        "status": "compiled_customer_geometry_diagnostic_batch_not_calibrated",
        "source_manifest_sha256": _sha256_file(
            root / "customer_gdb_network_private_manifest.json"
        ),
        "source_network_counts": {
            "pipeline_count": len(pipelines),
            "node_count": len(nodes),
            "facility_link_count": len(links),
        },
        "selection": {
            **selection_audit,
            "selection_policy": asdict(active_selection),
        },
        "pilots": pilots,
        "forcing": dict(forcing_descriptor),
        "assumptions": {
            "diameter_source_unit": "assumed_mm_not_engineering_verified",
            "vertical_datum": "unverified",
            "processed_pipe_elevations": "diagnostic_only_not_survey_admitted",
            "facility_bottom_elevations": "excluded_uniform_1_2m_derivation_detected",
            "catchments_roughness_and_node_depth": "diagnostic_assumptions",
            "pump_gate_tide_or_backwater_operations_included": False,
        },
        "admission": {
            "network_cleanup_and_prototype_allowed": True,
            "traditional_model_admitted": False,
            "calibration_admitted": False,
            "gwm_training_admitted": False,
            "production_admitted": False,
            "city_scale_prediction_claim_allowed": False,
        },
        "claim_boundary": manifest["claim_boundary"],
    }
    receipt_path = root / "customer_stormwater_subnetwork_batch_compile_receipt.json"
    _atomic_write_json(receipt_path, receipt)
    receipt["receipt"] = _artifact(receipt_path, root)
    return receipt


def _standardized_feature(
    values: Any,
    *,
    valid_mask: Any | None = None,
) -> tuple[Any, dict[str, float | int]]:
    import numpy as np

    numeric = np.asarray(values, dtype="float64")
    valid = np.isfinite(numeric)
    if valid_mask is not None:
        valid &= np.asarray(valid_mask, dtype="bool")
    result = np.zeros(len(numeric), dtype="float32")
    if not valid.any():
        return result, {"valid_count": 0, "mean": 0.0, "standard_deviation": 1.0}
    mean = float(numeric[valid].mean())
    standard_deviation = float(numeric[valid].std())
    if not math.isfinite(standard_deviation) or standard_deviation < 1.0e-12:
        standard_deviation = 1.0
    result[valid] = ((numeric[valid] - mean) / standard_deviation).astype("float32")
    return result, {
        "valid_count": int(valid.sum()),
        "mean": round(mean, 8),
        "standard_deviation": round(standard_deviation, 8),
    }


def _partition_static_graph(
    node_count: int,
    edge_index: Any,
    topology_clean: Any,
    *,
    maximum_nodes_per_partition: int,
) -> Any:
    import numpy as np

    adjacency: list[list[int]] = [[] for _ in range(node_count)]
    clean_positions = np.flatnonzero(np.asarray(topology_clean, dtype="bool"))
    for position in clean_positions:
        source = int(edge_index[0, position])
        target = int(edge_index[1, position])
        if source == target:
            continue
        adjacency[source].append(target)
        adjacency[target].append(source)
    partition = np.full(node_count, -1, dtype="int32")
    enqueued = np.zeros(node_count, dtype="bool")
    partition_id = 0
    partition_size = 0
    for seed in range(node_count):
        if partition[seed] >= 0 or enqueued[seed]:
            continue
        queue: deque[int] = deque([seed])
        enqueued[seed] = True
        while queue:
            node = queue.popleft()
            if partition_size >= maximum_nodes_per_partition:
                partition_id += 1
                partition_size = 0
            partition[node] = partition_id
            partition_size += 1
            for neighbour in sorted(adjacency[node]):
                if partition[neighbour] < 0 and not enqueued[neighbour]:
                    enqueued[neighbour] = True
                    queue.append(neighbour)
    if node_count and (partition < 0).any():
        raise ValueError("customer_gwm_partition_assignment_incomplete")
    return partition


def build_customer_gwm_static_tensors(
    pipelines: Any,
    nodes: Any,
    *,
    policy: CustomerGwmStaticTensorPolicy | None = None,
) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    """Build ID-free private tensors and a partition inventory."""

    import numpy as np
    import pandas as pd

    active = policy or CustomerGwmStaticTensorPolicy()
    required_pipeline_columns = {
        "source_node_id",
        "target_node_id",
        "recomputed_length_m",
        "diameter_numeric",
        "invert_up_numeric",
        "invert_down_numeric",
        "invert_up_plausible_candidate",
        "invert_down_plausible_candidate",
        "flow_direction_conflict",
        "self_loop_after_snap",
        "duplicate_node_pair",
        "geometry_supported",
        "pipe_material",
        "pipeline_status",
    }
    required_node_columns = {
        "node_id",
        "snap_x_m",
        "snap_y_m",
        "degree",
        "component_node_count",
        "candidate_surface_intake_count",
        "candidate_outfall_count",
        "candidate_pump_count",
        "candidate_facility_count",
    }
    missing_pipelines = sorted(required_pipeline_columns.difference(pipelines.columns))
    missing_nodes = sorted(required_node_columns.difference(nodes.columns))
    if missing_pipelines:
        raise ValueError(
            f"customer_gwm_pipeline_columns_missing:{','.join(missing_pipelines)}"
        )
    if missing_nodes:
        raise ValueError(f"customer_gwm_node_columns_missing:{','.join(missing_nodes)}")
    ordered_nodes = nodes.sort_values("node_id").reset_index(drop=True)
    if ordered_nodes["node_id"].duplicated().any():
        raise ValueError("customer_gwm_node_id_not_unique")
    node_index = {
        str(node_id): index for index, node_id in enumerate(ordered_nodes["node_id"])
    }
    source_index = pipelines["source_node_id"].astype(str).map(node_index)
    target_index = pipelines["target_node_id"].astype(str).map(node_index)
    if source_index.isna().any() or target_index.isna().any():
        raise ValueError("customer_gwm_edge_endpoint_missing_from_nodes")
    edge_index = np.vstack(
        [
            source_index.to_numpy(dtype="int64"),
            target_index.to_numpy(dtype="int64"),
        ]
    )

    length = pd.to_numeric(pipelines["recomputed_length_m"], errors="coerce").to_numpy()
    diameter = pd.to_numeric(pipelines["diameter_numeric"], errors="coerce").to_numpy()
    invert_up = pd.to_numeric(pipelines["invert_up_numeric"], errors="coerce").to_numpy()
    invert_down = pd.to_numeric(
        pipelines["invert_down_numeric"], errors="coerce"
    ).to_numpy()
    geometry_usable = (
        pipelines["geometry_supported"].fillna(False).to_numpy(dtype="bool")
        & np.isfinite(length)
        & (length > 0.01)
    )
    self_loop = pipelines["self_loop_after_snap"].fillna(True).to_numpy(dtype="bool")
    duplicate = pipelines["duplicate_node_pair"].fillna(True).to_numpy(dtype="bool")
    direction_conflict = pipelines["flow_direction_conflict"].fillna(True).to_numpy(
        dtype="bool"
    )
    invert_up_valid = (
        pipelines["invert_up_plausible_candidate"].fillna(False).to_numpy(dtype="bool")
        & np.isfinite(invert_up)
    )
    invert_down_valid = (
        pipelines["invert_down_plausible_candidate"]
        .fillna(False)
        .to_numpy(dtype="bool")
        & np.isfinite(invert_down)
    )
    diameter_valid = np.isfinite(diameter) & (diameter >= 100.0) & (diameter <= 3000.0)
    topology_clean = geometry_usable & ~self_loop & ~duplicate
    diagnostic_direction = (
        topology_clean
        & ~direction_conflict
        & invert_up_valid
        & invert_down_valid
        & diameter_valid
    )

    length_log = np.zeros(len(length), dtype="float64")
    length_valid = np.isfinite(length) & (length > 0.0)
    length_log[length_valid] = np.log1p(length[length_valid])
    length_feature, length_stats = _standardized_feature(
        length_log,
        valid_mask=length_valid,
    )
    diameter_log = np.zeros(len(diameter), dtype="float64")
    diameter_log[diameter_valid] = np.log1p(diameter[diameter_valid])
    diameter_feature, diameter_stats = _standardized_feature(
        diameter_log,
        valid_mask=diameter_valid,
    )
    invert_up_feature, invert_up_stats = _standardized_feature(
        invert_up,
        valid_mask=invert_up_valid,
    )
    invert_down_feature, invert_down_stats = _standardized_feature(
        invert_down,
        valid_mask=invert_down_valid,
    )
    gradient = np.zeros(len(length), dtype="float64")
    gradient[diagnostic_direction] = (
        invert_up[diagnostic_direction] - invert_down[diagnostic_direction]
    ) / length[diagnostic_direction]
    gradient_feature, gradient_stats = _standardized_feature(
        gradient,
        valid_mask=diagnostic_direction,
    )
    material_present = (
        pipelines["pipe_material"].astype("string").fillna("").str.strip().ne("")
    ).to_numpy(dtype="bool")
    status_present = (
        pipelines["pipeline_status"].astype("string").fillna("").str.strip().ne("")
    ).to_numpy(dtype="bool")
    edge_features = np.column_stack(
        [
            length_feature,
            diameter_feature,
            invert_up_feature,
            invert_down_feature,
            gradient_feature,
            geometry_usable,
            topology_clean,
            diagnostic_direction,
            diameter_valid,
            invert_up_valid,
            invert_down_valid,
            material_present,
            status_present,
        ]
    ).astype("float32")

    x_feature, x_stats = _standardized_feature(ordered_nodes["snap_x_m"])
    y_feature, y_stats = _standardized_feature(ordered_nodes["snap_y_m"])
    degree_log = np.log1p(
        pd.to_numeric(ordered_nodes["degree"], errors="coerce")
        .fillna(0.0)
        .clip(lower=0.0)
        .to_numpy(dtype="float64")
    )
    degree_feature, degree_stats = _standardized_feature(degree_log)
    component_log = np.log1p(
        pd.to_numeric(ordered_nodes["component_node_count"], errors="coerce")
        .fillna(0.0)
        .clip(lower=0.0)
        .to_numpy(dtype="float64")
    )
    component_feature, component_stats = _standardized_feature(component_log)
    facility_log = np.log1p(
        pd.to_numeric(ordered_nodes["candidate_facility_count"], errors="coerce")
        .fillna(0.0)
        .clip(lower=0.0)
        .to_numpy(dtype="float64")
    )
    facility_feature, facility_stats = _standardized_feature(facility_log)
    intake_mask = ordered_nodes["candidate_surface_intake_count"].gt(0).to_numpy()
    outfall_mask = ordered_nodes["candidate_outfall_count"].gt(0).to_numpy()
    pump_mask = ordered_nodes["candidate_pump_count"].gt(0).to_numpy()
    node_features = np.column_stack(
        [
            x_feature,
            y_feature,
            degree_feature,
            component_feature,
            facility_feature,
            intake_mask,
            outfall_mask,
            pump_mask,
        ]
    ).astype("float32")
    node_partition = _partition_static_graph(
        len(ordered_nodes),
        edge_index,
        topology_clean,
        maximum_nodes_per_partition=active.maximum_nodes_per_partition,
    )
    partition_count = int(node_partition.max()) + 1 if len(node_partition) else 0
    source_partition = node_partition[edge_index[0]]
    target_partition = node_partition[edge_index[1]]
    internal_edge = source_partition == target_partition
    node_counts = np.bincount(node_partition, minlength=partition_count)
    internal_edge_counts = np.bincount(
        source_partition[internal_edge], minlength=partition_count
    )
    boundary_incident_counts = np.bincount(
        np.concatenate(
            [
                source_partition[~internal_edge],
                target_partition[~internal_edge],
            ]
        ),
        minlength=partition_count,
    )
    inventory = pd.DataFrame(
        {
            "partition_id": np.arange(partition_count, dtype="int32"),
            "node_count": node_counts.astype("int64"),
            "internal_edge_count": internal_edge_counts.astype("int64"),
            "boundary_incident_edge_count": boundary_incident_counts.astype("int64"),
        }
    )
    arrays = {
        "edge_index": edge_index,
        "node_features": node_features,
        "edge_features": edge_features,
        "node_partition": node_partition,
        "edge_topology_clean_mask": topology_clean,
        "edge_diagnostic_direction_mask": diagnostic_direction,
        "node_surface_intake_mask": intake_mask,
        "node_outfall_mask": outfall_mask,
        "node_pump_mask": pump_mask,
    }
    contract = {
        "node_feature_names": [
            "projected_x_standardized_private",
            "projected_y_standardized_private",
            "log_degree_standardized",
            "log_component_node_count_standardized",
            "log_candidate_facility_count_standardized",
            "surface_intake_candidate_mask",
            "outfall_candidate_mask",
            "pump_candidate_mask",
        ],
        "edge_feature_names": [
            "log_length_standardized",
            "log_diameter_source_value_standardized",
            "processed_invert_up_standardized_diagnostic_only",
            "processed_invert_down_standardized_diagnostic_only",
            "processed_gradient_standardized_diagnostic_only",
            "geometry_usable_mask",
            "topology_clean_mask",
            "diagnostic_direction_mask",
            "diameter_candidate_valid_mask",
            "invert_up_candidate_valid_mask",
            "invert_down_candidate_valid_mask",
            "material_present_mask",
            "status_present_mask",
        ],
        "normalization": {
            "projected_x": x_stats,
            "projected_y": y_stats,
            "log_degree": degree_stats,
            "log_component_node_count": component_stats,
            "log_candidate_facility_count": facility_stats,
            "log_length": length_stats,
            "log_diameter_source_value": diameter_stats,
            "processed_invert_up": invert_up_stats,
            "processed_invert_down": invert_down_stats,
            "processed_gradient": gradient_stats,
        },
        "partition_count": partition_count,
        "maximum_nodes_per_partition": active.maximum_nodes_per_partition,
        "cross_partition_edge_count": int((~internal_edge).sum()),
        "source_asset_identifiers_persisted": False,
        "raw_projected_coordinates_persisted": False,
    }
    return arrays, inventory, contract


def compile_customer_gwm_static_tensors(
    output_root: Path,
    *,
    policy: CustomerGwmStaticTensorPolicy | None = None,
) -> dict[str, Any]:
    """Write private ID-free static tensors without opening dynamic training."""

    import numpy as np

    root = _require_private_output_root(output_root)
    pipelines, nodes, _, _ = load_customer_private_network(root)
    active = policy or CustomerGwmStaticTensorPolicy()
    arrays, inventory, contract = build_customer_gwm_static_tensors(
        pipelines,
        nodes,
        policy=active,
    )
    tensor_path = root / "customer_gwm_static_graph_tensors.private.npz"
    temporary_tensor = tensor_path.with_name(f".{tensor_path.name}.tmp")
    with temporary_tensor.open("wb") as handle:
        np.savez_compressed(handle, **arrays)
    temporary_tensor.replace(tensor_path)
    inventory_path = root / "customer_gwm_graph_partition_inventory.private.parquet"
    temporary_inventory = inventory_path.with_name(f".{inventory_path.name}.tmp")
    inventory.to_parquet(temporary_inventory, index=False)
    temporary_inventory.replace(inventory_path)
    array_contract = {
        name: {"shape": list(value.shape), "dtype": str(value.dtype)}
        for name, value in sorted(arrays.items())
    }
    manifest = {
        "schema": CUSTOMER_GDB_GWM_TENSOR_SCHEMA,
        "status": "static_private_graph_tensors_compiled_dynamic_training_closed",
        "source_manifest_sha256": _sha256_file(
            root / "customer_gdb_network_private_manifest.json"
        ),
        "policy": asdict(active),
        "outputs": {
            "static_tensors_private_npz": _artifact(tensor_path, root),
            "partition_inventory_private_parquet": _artifact(
                inventory_path,
                root,
                record_count=len(inventory),
            ),
        },
        "arrays": array_contract,
        "feature_contract": contract,
        "privacy": {
            "contains_customer_derived_topology": True,
            "storage_class": "private_customer_controlled_not_for_public_repository",
            "source_asset_identifiers_persisted": False,
            "raw_geometry_persisted": False,
            "raw_projected_coordinates_persisted": False,
        },
        "readiness": {
            "static_encoder_development_allowed": True,
            "graph_partition_loading_allowed": True,
            "traditional_model_output_alignment_pending": True,
            "gwm_training_admitted": False,
            "supervised_state_transition_training_allowed": False,
            "action_conditioned_training_allowed": False,
            "city_scale_prediction_claim_allowed": False,
        },
    }
    manifest_path = root / "customer_gwm_static_tensor_manifest.json"
    _atomic_write_json(manifest_path, manifest)
    manifest["manifest"] = _artifact(manifest_path, root)
    return manifest


def load_customer_gwm_static_tensors(
    output_root: Path,
) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    """Load private tensors after source and output integrity verification."""

    import numpy as np
    import pandas as pd

    root = _require_private_output_root(output_root)
    manifest_path = root / "customer_gwm_static_tensor_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != CUSTOMER_GDB_GWM_TENSOR_SCHEMA:
        raise ValueError("customer_gwm_tensor_manifest_schema_invalid")
    source_hash = _sha256_file(root / "customer_gdb_network_private_manifest.json")
    if manifest.get("source_manifest_sha256") != source_hash:
        raise ValueError("customer_gwm_tensor_source_manifest_sha256_mismatch")

    def verified(key: str) -> Path:
        artifact = manifest["outputs"][key]
        path = (root / artifact["path"]).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("customer_gwm_tensor_artifact_outside_private_root") from exc
        if not path.is_file() or _sha256_file(path) != artifact["sha256"]:
            raise ValueError(f"customer_gwm_tensor_artifact_integrity_failed:{key}")
        return path

    with np.load(verified("static_tensors_private_npz"), allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    if set(arrays) != set(manifest["arrays"]):
        raise ValueError("customer_gwm_tensor_array_contract_mismatch")
    for name, array in arrays.items():
        expected = manifest["arrays"][name]
        if list(array.shape) != expected["shape"] or str(array.dtype) != expected["dtype"]:
            raise ValueError(f"customer_gwm_tensor_array_shape_or_dtype_mismatch:{name}")
    inventory = pd.read_parquet(verified("partition_inventory_private_parquet"))
    expected_count = manifest["outputs"][
        "partition_inventory_private_parquet"
    ].get("record_count")
    if len(inventory) != expected_count:
        raise ValueError("customer_gwm_partition_inventory_record_count_mismatch")
    return arrays, inventory, manifest


def compile_customer_swmm_gwm_alignment(output_root: Path) -> dict[str, Any]:
    """Align diagnostic SWMM pilots to the full private GWM graph indices."""

    import numpy as np

    root = _require_private_output_root(output_root)
    pipelines, nodes, links, _ = load_customer_private_network(root)
    tensors, _, tensor_manifest = load_customer_gwm_static_tensors(root)
    batch_receipt_path = root / "customer_stormwater_subnetwork_batch_compile_receipt.json"
    batch_receipt = json.loads(batch_receipt_path.read_text(encoding="utf-8"))
    if batch_receipt.get("schema") != CUSTOMER_GDB_SWMM_BATCH_SCHEMA:
        raise ValueError("customer_swmm_gwm_batch_receipt_schema_invalid")
    network_manifest_hash = _sha256_file(
        root / "customer_gdb_network_private_manifest.json"
    )
    if batch_receipt.get("source_manifest_sha256") != network_manifest_hash:
        raise ValueError("customer_swmm_gwm_batch_source_manifest_sha256_mismatch")
    selection_contract = batch_receipt.get("selection")
    if not isinstance(selection_contract, dict):
        raise ValueError("customer_swmm_gwm_batch_selection_required")
    selection_policy_payload = selection_contract.get("selection_policy")
    batch_policy_payload = selection_contract.get("batch_policy")
    if not isinstance(selection_policy_payload, dict) or not isinstance(
        batch_policy_payload, dict
    ):
        raise ValueError("customer_swmm_gwm_batch_policies_required")
    selection_policy = RegisteredSwmmDiagnosticPolicy(**selection_policy_payload)
    batch_policy = CustomerGdbSwmmBatchPolicy(**batch_policy_payload)
    selections, reproduced_audit = select_customer_gdb_swmm_pilot_batch(
        pipelines,
        nodes,
        links,
        selection_policy=selection_policy,
        batch_policy=batch_policy,
    )
    if len(selections) != selection_contract.get("selected_pilot_count"):
        raise ValueError("customer_swmm_gwm_pilot_count_reproduction_failed")
    if reproduced_audit["maximum_selected_edge_overlap_fraction"] != selection_contract.get(
        "maximum_selected_edge_overlap_fraction"
    ):
        raise ValueError("customer_swmm_gwm_overlap_reproduction_failed")

    ordered_nodes = nodes.sort_values("node_id").reset_index(drop=True)
    node_index = {
        str(node_id): index for index, node_id in enumerate(ordered_nodes["node_id"])
    }
    pipeline_index = {
        int(pipeline_id): index
        for index, pipeline_id in enumerate(pipelines["registered_pipeline_fid"])
    }
    if len(pipeline_index) != len(pipelines):
        raise ValueError("customer_swmm_gwm_pipeline_id_not_unique")
    pilot_node_indices: list[int] = []
    pilot_edge_indices: list[int] = []
    pilot_intake_node_indices: list[int] = []
    node_offsets = [0]
    edge_offsets = [0]
    intake_offsets = [0]
    outfall_node_indices = []
    pilot_summaries = []
    for pilot_number, selection in enumerate(selections, start=1):
        selected_nodes = selection["nodes"].sort_values("node_id")
        node_positions = [
            node_index[str(node_id)] for node_id in selected_nodes["node_id"]
        ]
        selected_edges = selection["edges"].sort_values("selection_order")
        edge_positions = [
            pipeline_index[int(pipeline_id)]
            for pipeline_id in selected_edges["registered_pipeline_fid"]
        ]
        for edge_position, edge in zip(
            edge_positions,
            selected_edges.itertuples(index=False),
            strict=True,
        ):
            expected = (
                node_index[str(edge.source_node_id)],
                node_index[str(edge.target_node_id)],
            )
            actual = tuple(
                int(value) for value in tensors["edge_index"][:, edge_position]
            )
            if actual != expected:
                raise ValueError("customer_swmm_gwm_edge_index_alignment_failed")
        intake_positions = [
            node_index[str(node_id)] for node_id in selection["intake_node_ids"]
        ]
        outfall_position = node_index[str(selection["root_node_id"])]
        pilot_node_indices.extend(node_positions)
        pilot_edge_indices.extend(edge_positions)
        pilot_intake_node_indices.extend(intake_positions)
        outfall_node_indices.append(outfall_position)
        node_offsets.append(len(pilot_node_indices))
        edge_offsets.append(len(pilot_edge_indices))
        intake_offsets.append(len(pilot_intake_node_indices))
        selected_partitions = np.unique(
            tensors["node_partition"][np.asarray(node_positions, dtype="int64")]
        )
        pilot_summaries.append(
            {
                "pilot_number": pilot_number,
                "node_count": len(node_positions),
                "edge_count": len(edge_positions),
                "surface_intake_node_count": len(intake_positions),
                "partition_count": len(selected_partitions),
                "maximum_previous_edge_overlap_fraction": round(
                    float(selection["maximum_previous_edge_overlap_fraction"]),
                    8,
                ),
            }
        )
    alignment_arrays = {
        "pilot_node_indices": np.asarray(pilot_node_indices, dtype="int64"),
        "pilot_node_offsets": np.asarray(node_offsets, dtype="int64"),
        "pilot_edge_indices": np.asarray(pilot_edge_indices, dtype="int64"),
        "pilot_edge_offsets": np.asarray(edge_offsets, dtype="int64"),
        "pilot_intake_node_indices": np.asarray(
            pilot_intake_node_indices, dtype="int64"
        ),
        "pilot_intake_node_offsets": np.asarray(intake_offsets, dtype="int64"),
        "pilot_outfall_node_indices": np.asarray(
            outfall_node_indices, dtype="int64"
        ),
    }
    alignment_path = root / "customer_swmm_gwm_pilot_alignment.private.npz"
    temporary = alignment_path.with_name(f".{alignment_path.name}.tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, **alignment_arrays)
    temporary.replace(alignment_path)
    manifest = {
        "schema": CUSTOMER_GDB_SWMM_GWM_ALIGNMENT_SCHEMA,
        "status": "static_solver_graph_alignment_compiled_time_series_pending",
        "source_hashes": {
            "network_manifest_sha256": network_manifest_hash,
            "gwm_tensor_manifest_sha256": _sha256_file(
                root / "customer_gwm_static_tensor_manifest.json"
            ),
            "swmm_batch_compile_receipt_sha256": _sha256_file(batch_receipt_path),
        },
        "output": _artifact(alignment_path, root),
        "arrays": {
            name: {"shape": list(value.shape), "dtype": str(value.dtype)}
            for name, value in sorted(alignment_arrays.items())
        },
        "pilots": pilot_summaries,
        "graph_contract": {
            "full_node_count": int(tensors["node_features"].shape[0]),
            "full_edge_count": int(tensors["edge_features"].shape[0]),
            "partition_count": tensor_manifest["feature_contract"]["partition_count"],
            "pilot_order_matches_swmm_batch_receipt": True,
            "node_order_within_pilot": "ascending_private_full_graph_node_index",
            "edge_order_within_pilot": "swmm_conduit_input_and_selection_order",
            "source_asset_identifiers_persisted": False,
        },
        "future_dynamic_channels": {
            "node": [
                "water_depth_m",
                "hydraulic_head_m",
                "stored_volume_m3",
                "lateral_inflow_m3s",
                "total_inflow_m3s",
                "overflow_or_flooding_m3s",
            ],
            "edge": [
                "flow_m3s",
                "velocity_ms",
                "water_depth_m",
                "capacity_fraction",
            ],
            "forcing": ["rainfall_interval_depth_mm", "outfall_boundary_level_m"],
            "observation_mask_required": True,
            "quality_mask_required": True,
        },
        "readiness": {
            "static_solver_graph_index_alignment_compiled": True,
            "solver_time_series_extraction_implemented": False,
            "dynamic_state_tensor_materialized": False,
            "traditional_model_output_alignment_pending": (
                "time_series_values_only_static_indices_complete"
            ),
            "gwm_training_admitted": False,
            "city_scale_prediction_claim_allowed": False,
        },
        "privacy": {
            "contains_customer_derived_indices": True,
            "storage_class": "private_customer_controlled_not_for_public_repository",
            "source_asset_identifiers_persisted": False,
            "raw_geometry_persisted": False,
            "absolute_paths_persisted": False,
        },
    }
    manifest_path = root / "customer_swmm_gwm_alignment_manifest.json"
    _atomic_write_json(manifest_path, manifest)
    manifest["manifest"] = _artifact(manifest_path, root)
    return manifest


def load_customer_swmm_gwm_alignment(
    output_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the private SWMM-to-GWM index bridge after integrity checks."""

    import numpy as np

    root = _require_private_output_root(output_root)
    manifest_path = root / "customer_swmm_gwm_alignment_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != CUSTOMER_GDB_SWMM_GWM_ALIGNMENT_SCHEMA:
        raise ValueError("customer_swmm_gwm_alignment_manifest_schema_invalid")
    expected_sources = {
        "network_manifest_sha256": _sha256_file(
            root / "customer_gdb_network_private_manifest.json"
        ),
        "gwm_tensor_manifest_sha256": _sha256_file(
            root / "customer_gwm_static_tensor_manifest.json"
        ),
        "swmm_batch_compile_receipt_sha256": _sha256_file(
            root / "customer_stormwater_subnetwork_batch_compile_receipt.json"
        ),
    }
    if manifest.get("source_hashes") != expected_sources:
        raise ValueError("customer_swmm_gwm_alignment_source_hash_mismatch")
    artifact = manifest["output"]
    path = (root / artifact["path"]).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("customer_swmm_gwm_alignment_outside_private_root") from exc
    if not path.is_file() or _sha256_file(path) != artifact["sha256"]:
        raise ValueError("customer_swmm_gwm_alignment_integrity_failed")
    with np.load(path, allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    if set(arrays) != set(manifest["arrays"]):
        raise ValueError("customer_swmm_gwm_alignment_array_contract_mismatch")
    for name, array in arrays.items():
        expected = manifest["arrays"][name]
        if list(array.shape) != expected["shape"] or str(array.dtype) != expected["dtype"]:
            raise ValueError(f"customer_swmm_gwm_alignment_array_invalid:{name}")
    return arrays, manifest


def compile_customer_swmm_gwm_dynamic_diagnostic(
    output_root: Path,
    *,
    library_path: Path,
) -> dict[str, Any]:
    """Materialize private diagnostic SWMM states in full-graph index order."""

    import numpy as np

    from .swmm_adapter import evaluate_swmm_quality, parse_swmm_report
    from .swmm_saved_results import execute_swmm_saved_results
    from .traditional_solver import TraditionalSolverQualityPolicy

    root = _require_private_output_root(output_root)
    pipelines, nodes, links, _ = load_customer_private_network(root)
    alignment, alignment_manifest = load_customer_swmm_gwm_alignment(root)
    batch_receipt_path = root / "customer_stormwater_subnetwork_batch_compile_receipt.json"
    batch_receipt = json.loads(batch_receipt_path.read_text(encoding="utf-8"))
    selection_contract = batch_receipt["selection"]
    selections, _ = select_customer_gdb_swmm_pilot_batch(
        pipelines,
        nodes,
        links,
        selection_policy=RegisteredSwmmDiagnosticPolicy(
            **selection_contract["selection_policy"]
        ),
        batch_policy=CustomerGdbSwmmBatchPolicy(**selection_contract["batch_policy"]),
    )
    pilots = batch_receipt.get("pilots")
    if not isinstance(pilots, list) or len(pilots) != len(selections):
        raise ValueError("customer_swmm_gwm_dynamic_pilot_contract_mismatch")
    runtime = library_path.expanduser().resolve()
    if not runtime.is_file():
        raise ValueError("customer_swmm_gwm_dynamic_library_missing")
    arrays: dict[str, Any] = {}
    pilot_summaries = []
    quality_policy = TraditionalSolverQualityPolicy()
    node_channels: list[str] | None = None
    edge_channels: list[str] | None = None
    for pilot_position, (selection, pilot_contract) in enumerate(
        zip(selections, pilots, strict=True)
    ):
        pilot_id = f"pilot_{pilot_position + 1:02d}"
        if pilot_contract.get("pilot_id") != pilot_id:
            raise ValueError("customer_swmm_gwm_dynamic_pilot_order_changed")
        input_artifact = pilot_contract["model_input"]
        input_path = (root / input_artifact["path"]).resolve()
        try:
            input_path.relative_to(root)
        except ValueError as exc:
            raise ValueError("customer_swmm_gwm_dynamic_input_outside_private_root") from exc
        if not input_path.is_file() or _sha256_file(input_path) != input_artifact["sha256"]:
            raise ValueError("customer_swmm_gwm_dynamic_input_integrity_failed")
        node_names = tuple(selection["nodes"].sort_values("node_id")["node_id"].astype(str))
        link_names = tuple(
            f"c_{int(value)}"
            for value in selection["edges"].sort_values("selection_order")[
                "registered_pipeline_fid"
            ]
        )
        result = execute_swmm_saved_results(
            library_path=runtime,
            model_input_path=input_path,
            node_names=node_names,
            link_names=link_names,
        )
        parsed = parse_swmm_report(result["report_text"])
        quality = evaluate_swmm_quality(parsed, quality_policy)
        if not quality["passed"]:
            raise ValueError("customer_swmm_gwm_dynamic_numerical_quality_failed")
        node_start = int(alignment["pilot_node_offsets"][pilot_position])
        node_end = int(alignment["pilot_node_offsets"][pilot_position + 1])
        edge_start = int(alignment["pilot_edge_offsets"][pilot_position])
        edge_end = int(alignment["pilot_edge_offsets"][pilot_position + 1])
        node_count = node_end - node_start
        edge_count = edge_end - edge_start
        if result["node_state"].shape[1] != node_count:
            raise ValueError("customer_swmm_gwm_dynamic_node_alignment_failed")
        if result["link_state"].shape[1] != edge_count:
            raise ValueError("customer_swmm_gwm_dynamic_edge_alignment_failed")
        if node_channels is None:
            node_channels = list(result["node_channel_names"])
            edge_channels = list(result["link_channel_names"])
        elif node_channels != result["node_channel_names"] or edge_channels != result[
            "link_channel_names"
        ]:
            raise ValueError("customer_swmm_gwm_dynamic_channels_changed")
        timestamp_key = f"{pilot_id}_elapsed_seconds"
        node_key = f"{pilot_id}_node_state"
        edge_key = f"{pilot_id}_edge_state"
        arrays[timestamp_key] = result["timestamp_seconds_since_model_start"]
        arrays[node_key] = result["node_state"]
        arrays[edge_key] = result["link_state"]
        node_minimum = np.min(result["node_state"], axis=(0, 1))
        node_maximum = np.max(result["node_state"], axis=(0, 1))
        edge_minimum = np.min(result["link_state"], axis=(0, 1))
        edge_maximum = np.max(result["link_state"], axis=(0, 1))
        pilot_summaries.append(
            {
                "pilot_id": pilot_id,
                "reporting_period_count": result["period_count"],
                "first_elapsed_seconds": int(arrays[timestamp_key][0]),
                "last_elapsed_seconds": int(arrays[timestamp_key][-1]),
                "node_count": node_count,
                "edge_count": edge_count,
                "node_channel_minimum": {
                    name: round(float(value), 8)
                    for name, value in zip(node_channels, node_minimum, strict=True)
                },
                "node_channel_maximum": {
                    name: round(float(value), 8)
                    for name, value in zip(node_channels, node_maximum, strict=True)
                },
                "edge_channel_minimum": {
                    name: round(float(value), 8)
                    for name, value in zip(edge_channels, edge_minimum, strict=True)
                },
                "edge_channel_maximum": {
                    name: round(float(value), 8)
                    for name, value in zip(edge_channels, edge_maximum, strict=True)
                },
                "quality": {
                    "passed": quality["passed"],
                    "runoff_continuity_error_percent": parsed[
                        "runoff_quantity_continuity"
                    ]["continuity_error_percent"],
                    "routing_continuity_error_percent": parsed[
                        "flow_routing_continuity"
                    ]["continuity_error_percent"],
                    "steps_not_converging_percent": parsed["convergence"][
                        "steps_not_converging_percent"
                    ],
                    "all_links_stable": parsed["stability"]["all_links_stable"],
                },
            }
        )
    tensor_path = root / "customer_swmm_gwm_dynamic_diagnostic.private.npz"
    temporary = tensor_path.with_name(f".{tensor_path.name}.tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, **arrays)
    temporary.replace(tensor_path)
    runtime_hash = _sha256_file(runtime)
    manifest = {
        "schema": CUSTOMER_GDB_SWMM_GWM_DYNAMIC_SCHEMA,
        "status": "diagnostic_dynamic_state_interface_materialized_not_training_admitted",
        "source_hashes": {
            "alignment_manifest_sha256": _sha256_file(
                root / "customer_swmm_gwm_alignment_manifest.json"
            ),
            "swmm_batch_compile_receipt_sha256": _sha256_file(batch_receipt_path),
            "solver_runtime_sha256": runtime_hash,
        },
        "output": _artifact(tensor_path, root),
        "arrays": {
            name: {"shape": list(value.shape), "dtype": str(value.dtype)}
            for name, value in sorted(arrays.items())
        },
        "alignment_contract": {
            "node_state_axis_1_matches_pilot_node_indices_slice": True,
            "edge_state_axis_1_matches_pilot_edge_indices_slice": True,
            "alignment_pilot_count": len(alignment_manifest["pilots"]),
            "node_channels": node_channels,
            "edge_channels": edge_channels,
            "source_asset_identifiers_persisted": False,
        },
        "pilots": pilot_summaries,
        "execution": {
            "solver": "EPA SWMM",
            "version": "5.2.4",
            "official_saved_value_api_used": True,
            "isolated_temporary_working_directory": True,
            "temporary_working_directory_retained": False,
            "shell_used": False,
            "absolute_paths_persisted": False,
        },
        "readiness": {
            "diagnostic_dynamic_state_interface_materialized": True,
            "static_solver_graph_index_alignment_compiled": True,
            "authoritative_event_labels_present": False,
            "calibrated_traditional_model_rollouts_present": False,
            "gwm_input_pipeline_development_allowed": True,
            "gwm_training_admitted": False,
            "city_scale_prediction_claim_allowed": False,
        },
        "claim_boundary": [
            "dynamic_values_come_from_diagnostic_swmm_assumptions",
            "rainfall_is_public_proxy_not_customer_gauge_or_radar_qpe",
            "not_calibrated_against_observed_water_levels_flows_or_inundation",
            "valid_for_interface_and_tensor_contract_testing_only",
            "not_admitted_as_gwm_training_or_city_prediction_evidence",
        ],
        "privacy": {
            "contains_customer_derived_dynamic_states": True,
            "storage_class": "private_customer_controlled_not_for_public_repository",
            "source_asset_identifiers_persisted": False,
            "raw_geometry_persisted": False,
            "absolute_paths_persisted": False,
        },
    }
    manifest_path = root / "customer_swmm_gwm_dynamic_diagnostic_manifest.json"
    _atomic_write_json(manifest_path, manifest)
    manifest["manifest"] = _artifact(manifest_path, root)
    return manifest


def load_customer_swmm_gwm_dynamic_diagnostic(
    output_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load private diagnostic states after source and output verification."""

    import numpy as np

    root = _require_private_output_root(output_root)
    manifest_path = root / "customer_swmm_gwm_dynamic_diagnostic_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != CUSTOMER_GDB_SWMM_GWM_DYNAMIC_SCHEMA:
        raise ValueError("customer_swmm_gwm_dynamic_manifest_schema_invalid")
    expected_sources = {
        "alignment_manifest_sha256": _sha256_file(
            root / "customer_swmm_gwm_alignment_manifest.json"
        ),
        "swmm_batch_compile_receipt_sha256": _sha256_file(
            root / "customer_stormwater_subnetwork_batch_compile_receipt.json"
        ),
        "solver_runtime_sha256": manifest["source_hashes"].get("solver_runtime_sha256"),
    }
    if manifest.get("source_hashes") != expected_sources:
        raise ValueError("customer_swmm_gwm_dynamic_source_hash_mismatch")
    artifact = manifest["output"]
    path = (root / artifact["path"]).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("customer_swmm_gwm_dynamic_outside_private_root") from exc
    if not path.is_file() or _sha256_file(path) != artifact["sha256"]:
        raise ValueError("customer_swmm_gwm_dynamic_integrity_failed")
    with np.load(path, allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    if set(arrays) != set(manifest["arrays"]):
        raise ValueError("customer_swmm_gwm_dynamic_array_contract_mismatch")
    for name, array in arrays.items():
        expected = manifest["arrays"][name]
        if list(array.shape) != expected["shape"] or str(array.dtype) != expected["dtype"]:
            raise ValueError(f"customer_swmm_gwm_dynamic_array_invalid:{name}")
        if not np.isfinite(array).all():
            raise ValueError(f"customer_swmm_gwm_dynamic_array_nonfinite:{name}")
    return arrays, manifest


def compile_customer_gwm_input_window_shapes(
    output_root: Path,
    *,
    input_steps: int = 12,
    target_steps: int = 6,
    stride_steps: int = 6,
) -> dict[str, Any]:
    """Create private GWM window tensors from diagnostic dynamic states.

    The window contract intentionally separates observed/available channels from
    future labels. Diagnostic SWMM states are copied into the input and target
    slots only to validate shapes; the manifest marks them as non-authoritative.
    """

    import numpy as np

    if (
        isinstance(input_steps, bool)
        or isinstance(target_steps, bool)
        or isinstance(stride_steps, bool)
        or not isinstance(input_steps, int)
        or not isinstance(target_steps, int)
        or not isinstance(stride_steps, int)
        or input_steps < 1
        or target_steps < 1
        or stride_steps < 1
    ):
        raise ValueError("customer_gwm_window_step_policy_invalid")
    root = _require_private_output_root(output_root)
    static_tensors, _, static_manifest = load_customer_gwm_static_tensors(root)
    dynamic, dynamic_manifest = load_customer_swmm_gwm_dynamic_diagnostic(root)
    alignment, alignment_manifest = load_customer_swmm_gwm_alignment(root)
    node_feature_count = int(static_tensors["node_features"].shape[1])
    edge_feature_count = int(static_tensors["edge_features"].shape[1])
    node_state_count = len(dynamic_manifest["alignment_contract"]["node_channels"])
    edge_state_count = len(dynamic_manifest["alignment_contract"]["edge_channels"])
    window_arrays: dict[str, Any] = {}
    pilot_summaries = []
    total_window_count = 0
    for pilot_number, pilot in enumerate(dynamic_manifest["pilots"]):
        pilot_id = str(pilot["pilot_id"])
        node_state = dynamic[f"{pilot_id}_node_state"]
        edge_state = dynamic[f"{pilot_id}_edge_state"]
        timestamps = dynamic[f"{pilot_id}_elapsed_seconds"]
        period_count = int(node_state.shape[0])
        if edge_state.shape[0] != period_count or len(timestamps) != period_count:
            raise ValueError("customer_gwm_window_dynamic_period_alignment_failed")
        if period_count < input_steps + target_steps:
            raise ValueError("customer_gwm_window_period_count_too_small")
        starts = tuple(
            range(0, period_count - input_steps - target_steps + 1, stride_steps)
        )
        if not starts:
            raise ValueError("customer_gwm_window_no_complete_windows")
        node_start = int(alignment["pilot_node_offsets"][pilot_number])
        node_end = int(alignment["pilot_node_offsets"][pilot_number + 1])
        edge_start = int(alignment["pilot_edge_offsets"][pilot_number])
        edge_end = int(alignment["pilot_edge_offsets"][pilot_number + 1])
        node_indices = alignment["pilot_node_indices"][node_start:node_end]
        edge_indices = alignment["pilot_edge_indices"][edge_start:edge_end]
        static_node_features = static_tensors["node_features"][node_indices]
        static_edge_features = static_tensors["edge_features"][edge_indices]
        node_static = np.broadcast_to(
            static_node_features,
            (len(starts), input_steps + target_steps, *static_node_features.shape),
        ).copy()
        edge_static = np.broadcast_to(
            static_edge_features,
            (len(starts), input_steps + target_steps, *static_edge_features.shape),
        ).copy()
        node_values = np.stack(
            [
                node_state[start : start + input_steps + target_steps]
                for start in starts
            ],
            axis=0,
        ).astype("float32")
        edge_values = np.stack(
            [
                edge_state[start : start + input_steps + target_steps]
                for start in starts
            ],
            axis=0,
        ).astype("float32")
        timestamp_values = np.stack(
            [
                timestamps[start : start + input_steps + target_steps]
                for start in starts
            ],
            axis=0,
        ).astype("int64")
        valid_node = np.ones(node_values.shape, dtype="bool")
        valid_edge = np.ones(edge_values.shape, dtype="bool")
        window_arrays[f"{pilot_id}_node_static_features"] = node_static
        window_arrays[f"{pilot_id}_edge_static_features"] = edge_static
        window_arrays[f"{pilot_id}_node_state_values"] = node_values
        window_arrays[f"{pilot_id}_edge_state_values"] = edge_values
        window_arrays[f"{pilot_id}_node_state_valid_mask"] = valid_node
        window_arrays[f"{pilot_id}_edge_state_valid_mask"] = valid_edge
        window_arrays[f"{pilot_id}_timestamps_seconds"] = timestamp_values
        pilot_summaries.append(
            {
                "pilot_id": pilot_id,
                "window_count": len(starts),
                "node_count": int(node_values.shape[2]),
                "edge_count": int(edge_values.shape[2]),
                "input_steps": input_steps,
                "target_steps": target_steps,
                "stride_steps": stride_steps,
                "diagnostic_target_values_present": True,
                "authoritative_target_values_present": False,
            }
        )
        total_window_count += len(starts)
    tensor_path = root / "customer_gwm_input_window_shapes.private.npz"
    temporary = tensor_path.with_name(f".{tensor_path.name}.tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, **window_arrays)
    temporary.replace(tensor_path)
    manifest = {
        "schema": CUSTOMER_GDB_GWM_WINDOW_SCHEMA,
        "status": "gwm_input_window_shapes_compiled_diagnostic_targets_not_admitted",
        "source_hashes": {
            "static_tensor_manifest_sha256": _sha256_file(
                root / "customer_gwm_static_tensor_manifest.json"
            ),
            "dynamic_diagnostic_manifest_sha256": _sha256_file(
                root / "customer_swmm_gwm_dynamic_diagnostic_manifest.json"
            ),
            "alignment_manifest_sha256": _sha256_file(
                root / "customer_swmm_gwm_alignment_manifest.json"
            ),
        },
        "output": _artifact(tensor_path, root),
        "arrays": {
            name: {"shape": list(value.shape), "dtype": str(value.dtype)}
            for name, value in sorted(window_arrays.items())
        },
        "feature_contract": {
            "static_node_feature_count": node_feature_count,
            "static_edge_feature_count": edge_feature_count,
            "dynamic_node_state_count": node_state_count,
            "dynamic_edge_state_count": edge_state_count,
            "node_static_feature_axis_order": [
                "window",
                "time",
                "node",
                "feature",
            ],
            "edge_static_feature_axis_order": [
                "window",
                "time",
                "edge",
                "feature",
            ],
            "node_state_axis_order": ["window", "time", "node", "channel"],
            "edge_state_axis_order": ["window", "time", "edge", "channel"],
            "timestamps_axis_order": ["window", "time"],
            "node_state_valid_mask_semantics": "finite_diagnostic_swmm_state_available",
            "edge_state_valid_mask_semantics": "finite_diagnostic_swmm_state_available",
        },
        "pilots": pilot_summaries,
        "total_window_count": total_window_count,
        "source_context": {
            "static_tensor_status": static_manifest["status"],
            "dynamic_diagnostic_status": dynamic_manifest["status"],
            "alignment_status": alignment_manifest["status"],
        },
        "readiness": {
            "window_shape_contract_compiled": True,
            "diagnostic_target_values_present": True,
            "authoritative_target_values_present": False,
            "observation_fusion_ready": False,
            "gwm_input_pipeline_development_allowed": True,
            "gwm_training_admitted": False,
            "supervised_state_transition_training_allowed": False,
            "city_scale_prediction_claim_allowed": False,
        },
        "privacy": {
            "contains_customer_derived_dynamic_values": True,
            "storage_class": "private_customer_controlled_not_for_public_repository",
            "source_asset_identifiers_persisted": False,
            "raw_geometry_persisted": False,
            "absolute_paths_persisted": False,
        },
        "claim_boundary": [
            "diagnostic_swmm_states_are_not_authoritative_observation_labels",
            "public_proxy_rainfall_and_assumed_hydraulics_remain_in_source_states",
            "window_shapes_validate_input_pipeline_only",
            "gwm_training_and_city_scale_prediction_claims_remain_closed",
        ],
    }
    manifest_path = root / "customer_gwm_input_window_shapes_manifest.json"
    _atomic_write_json(manifest_path, manifest)
    manifest["manifest"] = _artifact(manifest_path, root)
    return manifest


def load_customer_gwm_input_window_shapes(
    output_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load private window tensors with strict source and shape checks."""

    import numpy as np

    root = _require_private_output_root(output_root)
    manifest_path = root / "customer_gwm_input_window_shapes_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != CUSTOMER_GDB_GWM_WINDOW_SCHEMA:
        raise ValueError("customer_gwm_window_manifest_schema_invalid")
    expected_hashes = {
        "static_tensor_manifest_sha256": _sha256_file(
            root / "customer_gwm_static_tensor_manifest.json"
        ),
        "dynamic_diagnostic_manifest_sha256": _sha256_file(
            root / "customer_swmm_gwm_dynamic_diagnostic_manifest.json"
        ),
        "alignment_manifest_sha256": _sha256_file(
            root / "customer_swmm_gwm_alignment_manifest.json"
        ),
    }
    if manifest.get("source_hashes") != expected_hashes:
        raise ValueError("customer_gwm_window_source_hash_mismatch")
    artifact = manifest["output"]
    path = (root / artifact["path"]).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("customer_gwm_window_output_outside_private_root") from exc
    if not path.is_file() or _sha256_file(path) != artifact["sha256"]:
        raise ValueError("customer_gwm_window_output_integrity_failed")
    with np.load(path, allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    if set(arrays) != set(manifest["arrays"]):
        raise ValueError("customer_gwm_window_array_contract_mismatch")
    for name, array in arrays.items():
        expected = manifest["arrays"][name]
        if list(array.shape) != expected["shape"] or str(array.dtype) != expected["dtype"]:
            raise ValueError(f"customer_gwm_window_array_invalid:{name}")
        if not np.isfinite(array).all():
            raise ValueError(f"customer_gwm_window_array_nonfinite:{name}")
    return arrays, manifest


def compile_customer_gdb_swmm_diagnostic(
    output_root: Path,
    *,
    hourly_precipitation_mm: tuple[float, ...],
    forcing_descriptor: dict[str, Any],
    policy: RegisteredSwmmDiagnosticPolicy | None = None,
) -> dict[str, Any]:
    """Compile a private diagnostic SWMM subnetwork from normalized artifacts."""

    active = policy or RegisteredSwmmDiagnosticPolicy(
        maximum_edges=24,
        maximum_upstream_hops=6,
        minimum_edges=4,
    )
    root = _require_private_output_root(output_root)
    pipelines, nodes, links, manifest = load_customer_private_network(root)
    selection = select_registered_subnetwork(
        pipelines,
        nodes,
        links,
        policy=active,
    )
    input_text, ledger = render_registered_swmm_input(
        selection,
        hourly_precipitation_mm,
        forcing_label=str(forcing_descriptor.get("model_label", "Diagnostic")),
    )
    input_path = root / "customer_stormwater_subnetwork_diagnostic.inp"
    _atomic_write_text(input_path, input_text)
    selected_facilities = selection["facilities"]
    role_counts = {
        str(role): int(count)
        for role, count in selected_facilities["facility_role"].value_counts().items()
    }
    receipt = {
        "schema": CUSTOMER_GDB_SWMM_SCHEMA,
        "status": "compiled_customer_geometry_diagnostic_not_calibrated",
        "source_manifest_sha256": _sha256_file(
            root / "customer_gdb_network_private_manifest.json"
        ),
        "selection": {
            "algorithm": "deterministic_outfall_rooted_upstream_tree",
            "source_pipeline_count": selection["source_pipeline_count"],
            "valid_pipeline_count": selection["valid_pipeline_count"],
            "candidate_outfall_count": selection["selection_candidate_outfall_count"],
            "selected_pipeline_count": len(selection["edges"]),
            "selected_node_count": len(selection["nodes"]),
            "selected_surface_intake_node_count": len(selection["intake_node_ids"]),
            "selected_facility_role_counts": role_counts,
            "source_asset_identifiers_persisted": False,
            "selection_policy": asdict(active),
        },
        "model_input": {
            **_artifact(input_path, root),
            "flow_units": "CMS",
            "routing_method": "KINWAVE",
            "aggregate_ledger": {
                "junction_count": ledger["junction_count"],
                "outfall_count": ledger["outfall_count"],
                "conduit_count": ledger["conduit_count"],
                "subcatchment_count": ledger["subcatchment_count"],
                "rainfall_interval_count": ledger["rainfall_interval_count"],
                "single_asset_or_node_details_persisted": False,
            },
        },
        "forcing": dict(forcing_descriptor),
        "assumptions": {
            "diameter_source_unit": "assumed_mm_not_engineering_verified",
            "vertical_datum": "unverified",
            "processed_pipe_elevations": "diagnostic_only_not_survey_admitted",
            "facility_bottom_elevations": "excluded_uniform_1_2m_derivation_detected",
            "catchments_roughness_and_node_depth": "diagnostic_assumptions",
            "pump_gate_tide_or_backwater_operations_included": False,
        },
        "admission": {
            "network_cleanup_and_prototype_allowed": True,
            "traditional_model_admitted": False,
            "calibration_admitted": False,
            "gwm_training_admitted": False,
            "production_admitted": False,
            "city_scale_prediction_claim_allowed": False,
        },
        "claim_boundary": manifest["claim_boundary"],
    }
    receipt_path = root / "customer_stormwater_subnetwork_compile_receipt.json"
    _atomic_write_json(receipt_path, receipt)
    receipt["receipt"] = _artifact(receipt_path, root)
    return receipt
