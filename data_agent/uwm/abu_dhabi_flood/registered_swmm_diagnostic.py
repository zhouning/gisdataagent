"""Compile a deterministic registered-Makani subnetwork for SWMM diagnostics.

The compiler consumes the frozen candidate topology, not a live database. It
keeps source geometry, diameter and invert attributes traceable while marking
all unverified units, catchments and hydraulic parameters as assumptions.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

REGISTERED_SWMM_COMPILE_SCHEMA = "gwm.abu_dhabi_flood.registered_swmm_diagnostic_compile_receipt.v1"
REGISTERED_NETWORK_SCHEMA = "gwm.abu_dhabi_flood.registered_network_candidate.v1"
DEFAULT_INPUT_PATH_LABEL = (
    "benchmarks/abu_dhabi_stormwater_data_v1/derived/makani_registered/"
    "swmm_diagnostic/registered_subnetwork_openmeteo.inp"
)


@dataclass(frozen=True)
class RegisteredSwmmDiagnosticPolicy:
    maximum_edges: int = 12
    maximum_upstream_hops: int = 4
    minimum_edges: int = 4
    minimum_pipe_length_m: float = 1.0
    minimum_diameter_source_value: float = 100.0
    maximum_diameter_source_value: float = 3000.0
    assumed_diameter_source_unit: str = "mm"
    diameter_source_to_metre_scale: float = 0.001
    assumed_manning_roughness: float = 0.013
    assumed_node_maximum_depth_m: float = 3.0
    assumed_catchment_area_ha_per_intake_node: float = 0.1
    assumed_impervious_percent: float = 80.0
    assumed_catchment_width_m: float = 30.0
    assumed_catchment_slope_percent: float = 0.5

    def __post_init__(self) -> None:
        if (
            isinstance(self.maximum_edges, bool)
            or not isinstance(self.maximum_edges, int)
            or self.maximum_edges < 1
        ):
            raise ValueError("registered_swmm_maximum_edges_invalid")
        if (
            isinstance(self.maximum_upstream_hops, bool)
            or not isinstance(self.maximum_upstream_hops, int)
            or self.maximum_upstream_hops < 1
        ):
            raise ValueError("registered_swmm_maximum_hops_invalid")
        if (
            isinstance(self.minimum_edges, bool)
            or not isinstance(self.minimum_edges, int)
            or not 1 <= self.minimum_edges <= self.maximum_edges
        ):
            raise ValueError("registered_swmm_minimum_edges_invalid")
        positive = (
            self.minimum_pipe_length_m,
            self.minimum_diameter_source_value,
            self.maximum_diameter_source_value,
            self.diameter_source_to_metre_scale,
            self.assumed_manning_roughness,
            self.assumed_node_maximum_depth_m,
            self.assumed_catchment_area_ha_per_intake_node,
            self.assumed_catchment_width_m,
            self.assumed_catchment_slope_percent,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0.0
            for value in positive
        ):
            raise ValueError("registered_swmm_positive_policy_value_invalid")
        if self.maximum_diameter_source_value < self.minimum_diameter_source_value:
            raise ValueError("registered_swmm_diameter_bounds_invalid")
        if not 0.0 <= self.assumed_impervious_percent <= 100.0:
            raise ValueError("registered_swmm_impervious_percent_invalid")
        if self.assumed_diameter_source_unit != "mm":
            raise ValueError("registered_swmm_diameter_assumption_must_be_mm")


_PIPELINE_COLUMNS = (
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
)
_NODE_COLUMNS = (
    "node_id",
    "snap_x_m",
    "snap_y_m",
    "component_id",
    "component_node_count",
    "degree",
    "candidate_surface_intake_count",
    "candidate_outfall_count",
)
_FACILITY_COLUMNS = (
    "node_id",
    "facility_role",
    "registered_facility_fid",
    "minimum_endpoint_distance_m",
    "endpoint_roles",
    "geometry_endpoints",
    "evidence_level",
    "admitted",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: dict[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return _sha256_bytes(encoded)


def _require_columns(frame: Any, columns: tuple[str, ...], label: str) -> None:
    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise ValueError(f"registered_swmm_{label}_missing_columns:{','.join(missing)}")


def _artifact_path(root: Path, artifact: dict[str, object], label: str) -> Path:
    path_label = artifact.get("path")
    if not isinstance(path_label, str) or not path_label:
        raise ValueError(f"registered_swmm_{label}_path_invalid")
    path = (root / path_label).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"registered_swmm_{label}_path_outside_dataset") from exc
    if not path.is_file():
        raise ValueError(f"registered_swmm_{label}_missing")
    expected_hash = artifact.get("sha256")
    if not isinstance(expected_hash, str) or _sha256_file(path) != expected_hash:
        raise ValueError(f"registered_swmm_{label}_sha256_mismatch")
    return path


def load_registered_network_artifacts(
    dataset_root: Path,
) -> tuple[Any, Any, Any, dict[str, object]]:
    """Load only required columns after validating the frozen manifest and hashes."""

    import pandas as pd

    root = dataset_root.resolve()
    manifest_path = root / "derived/makani_registered/registered_network_candidate_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != REGISTERED_NETWORK_SCHEMA:
        raise ValueError("registered_swmm_network_manifest_schema_invalid")
    if manifest.get("admitted") is not False or manifest.get("diagnostic_only") is not True:
        raise ValueError("registered_swmm_candidate_manifest_boundary_invalid")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError("registered_swmm_network_outputs_required")
    pipeline_artifact = outputs["pipelines_geoparquet"]
    node_artifact = outputs["nodes_geoparquet"]
    facility_artifact = outputs["node_facility_candidates_parquet"]
    pipeline_path = _artifact_path(root, pipeline_artifact, "pipelines")
    node_path = _artifact_path(root, node_artifact, "nodes")
    facility_path = _artifact_path(root, facility_artifact, "facilities")
    pipelines = pd.read_parquet(pipeline_path, columns=list(_PIPELINE_COLUMNS))
    nodes = pd.read_parquet(node_path, columns=list(_NODE_COLUMNS))
    facilities = pd.read_parquet(facility_path, columns=list(_FACILITY_COLUMNS))
    expected_counts = (
        (pipelines, pipeline_artifact, "pipelines"),
        (nodes, node_artifact, "nodes"),
        (facilities, facility_artifact, "facilities"),
    )
    for frame, artifact, label in expected_counts:
        if len(frame) != artifact.get("record_count"):
            raise ValueError(f"registered_swmm_{label}_record_count_mismatch")
    source = {
        "network_manifest": {
            "path": str(manifest_path.relative_to(root)),
            "sha256": _sha256_file(manifest_path),
        },
        "registered_snapshot_id": manifest["registered_snapshot_id"],
        "registered_snapshot_sha256": manifest["registered_snapshot_sha256"],
        "pipeline_artifact": dict(pipeline_artifact),
        "node_artifact": dict(node_artifact),
        "facility_artifact": dict(facility_artifact),
    }
    return pipelines, nodes, facilities, source


def _valid_pipeline_mask(pipelines: Any, policy: RegisteredSwmmDiagnosticPolicy) -> Any:
    return (
        ~pipelines["self_loop_after_snap"].fillna(True)
        & ~pipelines["duplicate_node_pair"].fillna(True)
        & pipelines["invert_up_plausible_candidate"].fillna(False)
        & pipelines["invert_down_plausible_candidate"].fillna(False)
        & ~pipelines["flow_direction_conflict"].fillna(True)
        & pipelines["recomputed_length_m"].ge(policy.minimum_pipe_length_m)
        & pipelines["diameter_numeric"].between(
            policy.minimum_diameter_source_value,
            policy.maximum_diameter_source_value,
            inclusive="both",
        )
    )


def select_registered_subnetwork(
    pipelines: Any,
    nodes: Any,
    facilities: Any,
    *,
    policy: RegisteredSwmmDiagnosticPolicy | None = None,
) -> dict[str, object]:
    """Select the best deterministic upstream tree ending at an outfall candidate."""

    import pandas as pd

    active = policy or RegisteredSwmmDiagnosticPolicy()
    _require_columns(pipelines, _PIPELINE_COLUMNS, "pipelines")
    _require_columns(nodes, _NODE_COLUMNS, "nodes")
    _require_columns(facilities, _FACILITY_COLUMNS, "facilities")
    if pipelines["registered_pipeline_fid"].duplicated().any():
        raise ValueError("registered_swmm_pipeline_fid_not_unique")
    if nodes["node_id"].duplicated().any():
        raise ValueError("registered_swmm_node_id_not_unique")

    valid = pipelines[_valid_pipeline_mask(pipelines, active)].copy()
    valid = valid.sort_values("registered_pipeline_fid").reset_index(drop=True)
    incoming: dict[str, list[Any]] = defaultdict(list)
    for record in valid.itertuples(index=False):
        incoming[str(record.target_node_id)].append(record)

    outfall_links = facilities[
        facilities["facility_role"].eq("outfall")
        & facilities["minimum_endpoint_distance_m"].le(1.0)
        & facilities["endpoint_roles"].fillna("").str.contains("asset_after", regex=False)
        & facilities["geometry_endpoints"].fillna("").str.contains("geometry_end", regex=False)
        & facilities["evidence_level"].eq("candidate")
        & facilities["admitted"].eq(False)  # noqa: E712
    ].copy()
    node_index = nodes.set_index("node_id", drop=False)
    outfall_nodes = sorted(
        set(outfall_links["node_id"]).intersection(
            node_index[node_index["candidate_outfall_count"].gt(0)].index
        )
    )
    if not outfall_nodes:
        raise ValueError("registered_swmm_outfall_candidate_required")

    def collect(root_node_id: str) -> tuple[list[tuple[int, Any]], set[str]]:
        selected: list[tuple[int, Any]] = []
        visited = {root_node_id}
        queue: deque[tuple[str, int]] = deque([(root_node_id, 0)])
        while queue and len(selected) < active.maximum_edges:
            target_node_id, depth = queue.popleft()
            if depth >= active.maximum_upstream_hops:
                continue
            for edge in incoming.get(target_node_id, []):
                if len(selected) >= active.maximum_edges:
                    break
                source_node_id = str(edge.source_node_id)
                if source_node_id in visited:
                    continue
                visited.add(source_node_id)
                selected.append((depth + 1, edge))
                queue.append((source_node_id, depth + 1))
        return selected, visited

    candidates = []
    for root_node_id in outfall_nodes:
        edges, visited = collect(root_node_id)
        selected_nodes = node_index.loc[sorted(visited)]
        intake_count = int(selected_nodes["candidate_surface_intake_count"].gt(0).sum())
        candidates.append(
            {
                "root_node_id": root_node_id,
                "edges": edges,
                "visited": visited,
                "edge_count": len(edges),
                "intake_count": intake_count,
            }
        )
    candidates.sort(
        key=lambda item: (
            -int(item["edge_count"]),
            -int(item["intake_count"]),
            str(item["root_node_id"]),
        )
    )
    selected = candidates[0]
    if int(selected["edge_count"]) < active.minimum_edges:
        raise ValueError("registered_swmm_no_outfall_subnetwork_meets_minimum_edges")
    if int(selected["intake_count"]) < 1:
        raise ValueError("registered_swmm_selected_subnetwork_has_no_intake")

    edge_rows = []
    for selection_order, (hop, record) in enumerate(selected["edges"], start=1):
        row = record._asdict()
        row["upstream_hop"] = hop
        row["selection_order"] = selection_order
        edge_rows.append(row)
    selected_edges = pd.DataFrame(edge_rows)
    selected_node_ids = sorted(selected["visited"])
    selected_nodes = nodes[nodes["node_id"].isin(selected_node_ids)].copy()
    selected_nodes = selected_nodes.sort_values("node_id").reset_index(drop=True)
    selected_facilities = facilities[facilities["node_id"].isin(selected_node_ids)].copy()
    selected_facilities = selected_facilities.sort_values(
        ["node_id", "facility_role", "registered_facility_fid"]
    ).reset_index(drop=True)
    root_node_id = str(selected["root_node_id"])
    intake_node_ids = sorted(
        selected_nodes.loc[
            selected_nodes["candidate_surface_intake_count"].gt(0)
            & selected_nodes["node_id"].ne(root_node_id),
            "node_id",
        ]
    )
    return {
        "root_node_id": root_node_id,
        "edges": selected_edges,
        "nodes": selected_nodes,
        "facilities": selected_facilities,
        "intake_node_ids": intake_node_ids,
        "selection_candidate_outfall_count": len(candidates),
        "valid_pipeline_count": len(valid),
        "source_pipeline_count": len(pipelines),
        "policy": active,
    }


def _node_elevations(selection: dict[str, object]) -> dict[str, float]:
    endpoint_inverts: dict[str, list[float]] = defaultdict(list)
    for edge in selection["edges"].itertuples(index=False):
        endpoint_inverts[str(edge.source_node_id)].append(float(edge.invert_up_numeric))
        endpoint_inverts[str(edge.target_node_id)].append(float(edge.invert_down_numeric))
    if set(endpoint_inverts) != set(selection["nodes"]["node_id"]):
        raise ValueError("registered_swmm_node_invert_coverage_incomplete")
    return {node_id: min(values) for node_id, values in sorted(endpoint_inverts.items())}


def _format_rows(rows: list[tuple[object, ...]]) -> list[str]:
    return ["  ".join(str(value) for value in row) for row in rows]


def render_registered_swmm_input(
    selection: dict[str, object],
    hourly_precipitation_mm: tuple[float, ...],
    *,
    forcing_label: str = "Open-Meteo",
) -> tuple[str, dict[str, object]]:
    """Render one self-contained SWMM input and return its derived node ledger."""

    policy = selection["policy"]
    if not isinstance(policy, RegisteredSwmmDiagnosticPolicy):
        raise ValueError("registered_swmm_policy_required")
    if len(hourly_precipitation_mm) != 72 or any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0.0
        for value in hourly_precipitation_mm
    ):
        raise ValueError("registered_swmm_72_nonnegative_hourly_depths_required")
    if (
        not isinstance(forcing_label, str)
        or not forcing_label.strip()
        or not forcing_label.isascii()
        or "\n" in forcing_label
        or "\r" in forcing_label
    ):
        raise ValueError("registered_swmm_ascii_forcing_label_required")
    root_node_id = str(selection["root_node_id"])
    raw_outfall_node_ids = selection.get("outfall_node_ids")
    if raw_outfall_node_ids is None:
        outfall_node_ids = (root_node_id,)
    else:
        outfall_node_ids = tuple(sorted({str(value) for value in raw_outfall_node_ids}))
        if not outfall_node_ids or root_node_id not in outfall_node_ids:
            raise ValueError("registered_swmm_outfall_node_ids_invalid")
    routing_method = str(selection.get("routing_method", "KINWAVE")).upper()
    if routing_method not in {"KINWAVE", "DYNWAVE"}:
        raise ValueError("registered_swmm_routing_method_invalid")
    routing_step_seconds = int(selection.get("routing_step_seconds", 30))
    if routing_step_seconds < 1:
        raise ValueError("registered_swmm_routing_step_invalid")
    edges = selection["edges"]
    nodes = selection["nodes"]
    intake_node_ids = tuple(selection["intake_node_ids"])
    node_elevation = _node_elevations(selection)
    node_coordinates = {
        str(row.node_id): (float(row.snap_x_m), float(row.snap_y_m))
        for row in nodes.itertuples(index=False)
    }

    junction_rows = []
    for node_id in sorted(set(nodes["node_id"]).difference(outfall_node_ids)):
        junction_rows.append(
            (
                node_id,
                f"{node_elevation[node_id]:.3f}",
                f"{policy.assumed_node_maximum_depth_m:.3f}",
                "0",
                "0",
                "0",
            )
        )
    outfall_rows = [
        (node_id, f"{node_elevation[node_id]:.3f}", "FREE", "", "NO")
        for node_id in outfall_node_ids
    ]
    conduit_rows = []
    xsection_rows = []
    conduit_ledger = []
    for edge in edges.sort_values("selection_order").itertuples(index=False):
        link_id = f"c_{int(edge.registered_pipeline_fid)}"
        source = str(edge.source_node_id)
        target = str(edge.target_node_id)
        diameter_m = float(edge.diameter_numeric) * policy.diameter_source_to_metre_scale
        inlet_offset = max(0.0, float(edge.invert_up_numeric) - node_elevation[source])
        outlet_offset = max(0.0, float(edge.invert_down_numeric) - node_elevation[target])
        conduit_rows.append(
            (
                link_id,
                source,
                target,
                f"{float(edge.recomputed_length_m):.3f}",
                f"{policy.assumed_manning_roughness:.4f}",
                f"{inlet_offset:.3f}",
                f"{outlet_offset:.3f}",
                "0",
                "0",
            )
        )
        xsection_rows.append((link_id, "CIRCULAR", f"{diameter_m:.3f}", "0", "0", "0", "1"))
        conduit_ledger.append(
            {
                "registered_pipeline_fid": int(edge.registered_pipeline_fid),
                "swmm_link_id": link_id,
                "source_node_id": source,
                "target_node_id": target,
                "upstream_hop": int(edge.upstream_hop),
                "recomputed_length_m": float(edge.recomputed_length_m),
                "diameter_source_value": float(edge.diameter_numeric),
                "assumed_diameter_m": diameter_m,
                "invert_upstream_source_value": float(edge.invert_up_numeric),
                "invert_downstream_source_value": float(edge.invert_down_numeric),
                "derived_inlet_offset_m": inlet_offset,
                "derived_outlet_offset_m": outlet_offset,
                "pipe_material_source_value": (
                    None if edge.pipe_material is None else str(edge.pipe_material)
                ),
            }
        )

    subcatchment_rows = []
    subarea_rows = []
    infiltration_rows = []
    for index, node_id in enumerate(intake_node_ids, start=1):
        catchment_id = f"s_{index:02d}"
        subcatchment_rows.append(
            (
                catchment_id,
                "RG_PUBLIC",
                node_id,
                f"{policy.assumed_catchment_area_ha_per_intake_node:.3f}",
                f"{policy.assumed_impervious_percent:.1f}",
                f"{policy.assumed_catchment_width_m:.1f}",
                f"{policy.assumed_catchment_slope_percent:.2f}",
                "0",
            )
        )
        subarea_rows.append((catchment_id, "0.015", "0.25", "0.05", "0.15", "25", "OUTLET"))
        infiltration_rows.append((catchment_id, "75", "7", "4", "7", "0"))

    timeseries_rows = []
    start = datetime(2024, 4, 15)
    for index, depth_mm in enumerate(hourly_precipitation_mm):
        timestamp = start + timedelta(hours=index)
        timeseries_rows.append(
            (
                "TS_PUBLIC",
                timestamp.strftime("%m/%d/%Y"),
                timestamp.strftime("%H:%M"),
                f"{float(depth_mm):.6f}",
            )
        )
    timeseries_rows.append(("TS_PUBLIC", "04/18/2024", "00:00", "0"))
    coordinate_rows = [
        (node_id, f"{x:.3f}", f"{y:.3f}") for node_id, (x, y) in sorted(node_coordinates.items())
    ]

    sections: list[tuple[str, list[str]]] = [
        (
            "TITLE",
            [
                (
                    "Registered Makani candidate subnetwork with "
                    f"{forcing_label} public proxy rainfall"
                ),
                ";; Diagnostic only: customer-unverified topology and assumed hydraulics",
            ],
        ),
        (
            "OPTIONS",
            _format_rows(
                [
                    ("FLOW_UNITS", "CMS"),
                    ("INFILTRATION", "HORTON"),
                    ("FLOW_ROUTING", routing_method),
                    ("LINK_OFFSETS", "DEPTH"),
                    ("MIN_SLOPE", "0"),
                    ("ALLOW_PONDING", "NO"),
                    ("SKIP_STEADY_STATE", "NO"),
                    ("START_DATE", "04/15/2024"),
                    ("START_TIME", "00:00:00"),
                    ("REPORT_START_DATE", "04/15/2024"),
                    ("REPORT_START_TIME", "00:00:00"),
                    ("END_DATE", "04/18/2024"),
                    ("END_TIME", "06:00:00"),
                    ("SWEEP_START", "01/01"),
                    ("SWEEP_END", "12/31"),
                    ("DRY_DAYS", "0"),
                    ("REPORT_STEP", "00:15:00"),
                    ("WET_STEP", "00:05:00"),
                    ("DRY_STEP", "01:00:00"),
                    (
                        "ROUTING_STEP",
                        f"00:{routing_step_seconds // 60:02d}:{routing_step_seconds % 60:02d}",
                    ),
                ]
            ),
        ),
        ("EVAPORATION", ["CONSTANT  0.0"]),
        (
            "RAINGAGES",
            ["RG_PUBLIC  INTENSITY  01:00  1.0  TIMESERIES  TS_PUBLIC"],
        ),
        ("SUBCATCHMENTS", _format_rows(subcatchment_rows)),
        ("SUBAREAS", _format_rows(subarea_rows)),
        ("INFILTRATION", _format_rows(infiltration_rows)),
        ("JUNCTIONS", _format_rows(junction_rows)),
        ("OUTFALLS", _format_rows(outfall_rows)),
        ("CONDUITS", _format_rows(conduit_rows)),
        ("XSECTIONS", _format_rows(xsection_rows)),
        ("TIMESERIES", _format_rows(timeseries_rows)),
        (
            "REPORT",
            [
                "INPUT  YES",
                "CONTROLS  NO",
                # Keep all native objects in the RPT/OUT pair. The full-city
                # report is retained privately and parsed for maxima; the
                # browser consumes filtered GeoJSON and selected OUT periods.
                "SUBCATCHMENTS  ALL",
                "NODES  ALL",
                "LINKS  ALL",
            ],
        ),
        ("COORDINATES", _format_rows(coordinate_rows)),
        (
            "TAGS",
            [
                ";; Registered asset geometry/attributes plus public proxy rainfall.",
                ";; Catchment areas, roughness, maximum depth and diameter unit are assumptions.",
            ],
        ),
    ]
    lines = []
    for name, body in sections:
        lines.append(f"[{name}]")
        lines.extend(body)
        lines.append("")
    text = "\n".join(lines).rstrip() + "\n"
    ledger = {
        "root_outfall_node_id": root_node_id,
        "junction_count": len(junction_rows),
        "outfall_count": len(outfall_rows),
        "outfall_node_ids": list(outfall_node_ids),
        "conduit_count": len(conduit_rows),
        "subcatchment_count": len(subcatchment_rows),
        "rainfall_interval_count": len(hourly_precipitation_mm),
        "routing_method": routing_method,
        "routing_step_seconds": routing_step_seconds,
        "node_elevation_m": node_elevation,
        "conduits": conduit_ledger,
    }
    return text, ledger


def compile_registered_swmm_diagnostic(
    dataset_root: Path,
    *,
    hourly_precipitation_mm: tuple[float, ...],
    forcing_descriptor: dict[str, object],
    policy: RegisteredSwmmDiagnosticPolicy | None = None,
    input_path_label: str = DEFAULT_INPUT_PATH_LABEL,
) -> tuple[str, dict[str, object]]:
    """Compile the frozen assets and forcing into an admission-safe SWMM input."""

    active = policy or RegisteredSwmmDiagnosticPolicy()
    pipelines, nodes, facilities, source = load_registered_network_artifacts(dataset_root)
    selection = select_registered_subnetwork(
        pipelines,
        nodes,
        facilities,
        policy=active,
    )
    input_text, ledger = render_registered_swmm_input(
        selection,
        hourly_precipitation_mm,
        forcing_label=str(forcing_descriptor.get("model_label", "Open-Meteo")),
    )
    input_bytes = input_text.encode("ascii")
    selected_nodes = selection["nodes"]
    selected_facilities = selection["facilities"]
    root_node = selected_nodes[selected_nodes["node_id"].eq(selection["root_node_id"])].iloc[0]
    role_counts = {
        str(role): int(count)
        for role, count in selected_facilities["facility_role"].value_counts().items()
    }
    receipt: dict[str, object] = {
        "schema": REGISTERED_SWMM_COMPILE_SCHEMA,
        "status": "compiled_customer_unverified_assets_with_public_proxy_forcing_not_calibrated",
        "source_artifacts": source,
        "selection": {
            "algorithm": (
                "rank_outfall_candidates_by_valid_breadth_first_upstream_tree_"
                "edge_count_then_surface_intake_count_then_node_id"
            ),
            "candidate_outfall_count": selection["selection_candidate_outfall_count"],
            "source_pipeline_count": selection["source_pipeline_count"],
            "valid_pipeline_count": selection["valid_pipeline_count"],
            "selected_component_id": int(root_node["component_id"]),
            "source_component_node_count": int(root_node["component_node_count"]),
            "root_outfall_node_id": selection["root_node_id"],
            "selected_pipeline_count": len(selection["edges"]),
            "selected_node_count": len(selected_nodes),
            "selected_surface_intake_node_count": len(selection["intake_node_ids"]),
            "selected_facility_role_counts": role_counts,
            "selected_registered_pipeline_fids": [
                int(value)
                for value in selection["edges"].sort_values("selection_order")[
                    "registered_pipeline_fid"
                ]
            ],
            "selected_registered_outfall_fids": [
                int(value)
                for value in selected_facilities.loc[
                    selected_facilities["facility_role"].eq("outfall"),
                    "registered_facility_fid",
                ]
            ],
            "selection_policy": asdict(active),
            "filters": [
                "no_self_loop_after_snap",
                "no_duplicate_node_pair",
                "both_inverts_plausible_candidate",
                "no_invert_direction_conflict_with_geometry_orientation",
                "minimum_recomputed_length",
                "diameter_within_candidate_bounds",
                "outfall_candidate_matches_asset_after_and_geometry_end_within_1m",
            ],
        },
        "model_input": {
            "path": input_path_label,
            "sha256": _sha256_bytes(input_bytes),
            "size_bytes": len(input_bytes),
            "flow_units": "CMS",
            "routing_method": "KINWAVE",
            "ledger": ledger,
        },
        "forcing": dict(forcing_descriptor),
        "field_provenance": {
            "registered_asset_fields_used": [
                "registered_pipeline_fid",
                "source_node_id",
                "target_node_id",
                "recomputed_length_m",
                "diameter_numeric",
                "invert_up_numeric",
                "invert_down_numeric",
                "pipe_material",
                "snap_x_m",
                "snap_y_m",
                "candidate_surface_intake_count",
                "candidate_outfall_count",
            ],
            "registered_asset_names_or_addresses_consumed": False,
            "database_connection_executed": False,
            "credentials_consumed_or_recorded": False,
        },
        "assumptions": {
            "diameter_source_unit": "assumed_mm_not_engineering_verified",
            "diameter_conversion_to_m": active.diameter_source_to_metre_scale,
            "source_target_semantics": (
                "geometry_orientation_filtered_by_candidate_invert_direction_not_"
                "authoritative_flow_direction"
            ),
            "node_invert_elevation": (
                "minimum_incident_candidate_pipe_endpoint_invert_with_offsets_"
                "preserving_each_selected_pipe_invert"
            ),
            "vertical_datum": "unverified",
            "manning_roughness": active.assumed_manning_roughness,
            "node_maximum_depth_m": active.assumed_node_maximum_depth_m,
            "catchment_area_ha_per_intake_node": (active.assumed_catchment_area_ha_per_intake_node),
            "impervious_percent": active.assumed_impervious_percent,
            "catchment_width_m": active.assumed_catchment_width_m,
            "catchment_slope_percent": active.assumed_catchment_slope_percent,
            "pump_gate_tide_or_backwater_operations_included": False,
        },
        "admission": {
            "k0_status": "closed_not_admitted",
            "traditional_model_admitted": False,
            "calibration_admitted": False,
            "gwm_training_admitted": False,
            "production_admitted": False,
            "city_scale_prediction_claim_allowed": False,
        },
        "claim_boundary": [
            "registered_asset_geometry_and_attributes_are_customer_unverified_candidates",
            "selected_tree_is_diagnostic_not_authoritative_network_connectivity",
            "diameter_unit_vertical_datum_and_hydraulic_parameters_are_assumptions",
            "catchments_are_synthetic_and_not_registered_surface_drainage_areas",
            "public_proxy_rainfall_is_not_local_gauge_or_radar_calibration_evidence",
            "compiled_input_is_not_a_calibrated_engineering_or_city_scale_model",
        ],
    }
    receipt["receipt_sha256"] = _sha256_json(receipt)
    return input_text, receipt


def verify_registered_swmm_compile_receipt(receipt: dict[str, object]) -> None:
    """Verify the compile receipt's immutable content and admission boundary."""

    if receipt.get("schema") != REGISTERED_SWMM_COMPILE_SCHEMA:
        raise ValueError("registered_swmm_compile_receipt_schema_invalid")
    claimed = receipt.get("receipt_sha256")
    if not isinstance(claimed, str) or len(claimed) != 64:
        raise ValueError("registered_swmm_compile_receipt_sha256_invalid")
    content = dict(receipt)
    content.pop("receipt_sha256")
    if claimed != _sha256_json(content):
        raise ValueError("registered_swmm_compile_receipt_sha256_mismatch")
    admission = receipt.get("admission")
    if not isinstance(admission, dict) or any(
        admission.get(key) is not False
        for key in (
            "traditional_model_admitted",
            "calibration_admitted",
            "gwm_training_admitted",
            "production_admitted",
            "city_scale_prediction_claim_allowed",
        )
    ):
        raise ValueError("registered_swmm_compile_receipt_admission_boundary_invalid")
