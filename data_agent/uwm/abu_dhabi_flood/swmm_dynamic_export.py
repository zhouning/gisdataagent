"""Export private SWMM diagnostic state tensors to auditable CSV files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .customer_gdb_network import _require_private_output_root

SCHEMA = "gwm.abu_dhabi_flood.customer_swmm_dynamic_csv_export.v1"
NODE_CHANNELS = (
    "water_depth_m",
    "hydraulic_head_m",
    "stored_volume_m3",
    "lateral_inflow_m3s",
    "total_inflow_m3s",
    "overflow_or_flooding_m3s",
)
EDGE_CHANNELS = (
    "flow_m3s",
    "water_depth_m",
    "velocity_ms",
    "capacity_fraction",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    import csv

    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    temporary.replace(path)


def _validate_array(array: Any, *, name: str, dimensions: int) -> None:
    import numpy as np

    if getattr(array, "ndim", None) != dimensions:
        raise ValueError(f"swmm_dynamic_export_{name}_dimensions_invalid")
    if not np.isfinite(array).all():
        raise ValueError(f"swmm_dynamic_export_{name}_nonfinite")


def export_customer_swmm_dynamic_diagnostic(
    *,
    input_npz: Path,
    input_manifest: Path,
    output_root: Path,
) -> dict[str, Any]:
    """Export a private diagnostic tensor without persisting asset identifiers."""

    import numpy as np

    source_npz = input_npz.expanduser().resolve()
    source_manifest = input_manifest.expanduser().resolve()
    destination = _require_private_output_root(output_root)
    if not source_npz.is_file() or not source_manifest.is_file():
        raise ValueError("swmm_dynamic_export_source_missing")
    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    if manifest.get("schema") != "gwm.abu_dhabi_flood.customer_gdb_swmm_gwm_dynamic_diagnostic.v1":
        raise ValueError("swmm_dynamic_export_manifest_schema_invalid")
    arrays = np.load(source_npz, allow_pickle=False)
    try:
        pilot_ids = sorted(
            key.removesuffix("_elapsed_seconds")
            for key in arrays.files
            if key.endswith("_elapsed_seconds")
        )
        if not pilot_ids:
            raise ValueError("swmm_dynamic_export_pilots_missing")
        destination.mkdir(parents=True, exist_ok=True)
        time_rows: list[list[Any]] = []
        node_rows: list[list[Any]] = []
        edge_rows: list[list[Any]] = []
        pilot_receipts: list[dict[str, Any]] = []
        for pilot_id in pilot_ids:
            elapsed = arrays[f"{pilot_id}_elapsed_seconds"]
            nodes = arrays[f"{pilot_id}_node_state"]
            edges = arrays[f"{pilot_id}_edge_state"]
            _validate_array(elapsed, name=f"{pilot_id}_elapsed_seconds", dimensions=1)
            _validate_array(nodes, name=f"{pilot_id}_node_state", dimensions=3)
            _validate_array(edges, name=f"{pilot_id}_edge_state", dimensions=3)
            if nodes.shape[0] != len(elapsed) or edges.shape[0] != len(elapsed):
                raise ValueError(f"swmm_dynamic_export_{pilot_id}_time_axis_mismatch")
            if nodes.shape[2] != len(NODE_CHANNELS) or edges.shape[2] != len(EDGE_CHANNELS):
                raise ValueError(f"swmm_dynamic_export_{pilot_id}_channel_axis_mismatch")
            for time_index, elapsed_seconds in enumerate(elapsed.tolist()):
                time_rows.append(
                    [pilot_id, time_index, int(elapsed_seconds), float(elapsed_seconds) / 3600.0]
                )
                for node_position in range(nodes.shape[1]):
                    node_rows.append(
                        [
                            pilot_id,
                            time_index,
                            int(elapsed_seconds),
                            node_position,
                            *nodes[time_index, node_position, :].tolist(),
                        ]
                    )
                for edge_position in range(edges.shape[1]):
                    edge_rows.append(
                        [
                            pilot_id,
                            time_index,
                            int(elapsed_seconds),
                            edge_position,
                            *edges[time_index, edge_position, :].tolist(),
                        ]
                    )
            pilot_receipts.append(
                {
                    "pilot_id": pilot_id,
                    "reporting_period_count": int(len(elapsed)),
                    "node_count": int(nodes.shape[1]),
                    "edge_count": int(edges.shape[1]),
                    "elapsed_seconds_first": int(elapsed[0]),
                    "elapsed_seconds_last": int(elapsed[-1]),
                }
            )
    finally:
        arrays.close()
    time_path = destination / "customer_swmm_dynamic_time_index.csv"
    node_path = destination / "customer_swmm_dynamic_node_states.csv"
    edge_path = destination / "customer_swmm_dynamic_edge_states.csv"
    _write_csv(time_path, ["pilot_id", "time_index", "elapsed_seconds", "elapsed_hours"], time_rows)
    _write_csv(
        node_path,
        ["pilot_id", "time_index", "elapsed_seconds", "node_position", *NODE_CHANNELS],
        node_rows,
    )
    _write_csv(
        edge_path,
        ["pilot_id", "time_index", "elapsed_seconds", "edge_position", *EDGE_CHANNELS],
        edge_rows,
    )
    files = []
    for path, role, row_count in (
        (time_path, "time index", len(time_rows)),
        (node_path, "node dynamic states", len(node_rows)),
        (edge_path, "edge dynamic states", len(edge_rows)),
    ):
        files.append(
            {
                "path": path.name,
                "role": role,
                "row_count": row_count,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    result = {
        "schema": SCHEMA,
        "version": "2026-08-23",
        "status": "csv_exported_diagnostic_only",
        "source": {
            "npz_path": source_npz.name,
            "npz_sha256": _sha256(source_npz),
            "manifest_path": source_manifest.name,
            "source_asset_identifiers_persisted": False,
        },
        "files": files,
        "pilots": pilot_receipts,
        "claim_boundary": [
            "values_are_exported_from_diagnostic_swmm_assumptions",
            "csv_has_positions_not_customer_asset_identifiers",
            "not_calibrated_against_observations",
            "not_admitted_as_gwm_training_or_city_prediction_evidence",
        ],
        "admission": {
            "traditional_model_admitted": False,
            "gwm_training_admitted": False,
            "city_scale_prediction_claim_allowed": False,
        },
    }
    receipt_path = destination / "customer_swmm_dynamic_csv_export_manifest.json"
    receipt_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
