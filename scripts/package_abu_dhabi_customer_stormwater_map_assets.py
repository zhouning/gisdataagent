#!/usr/bin/env python3
"""Package private customer-GDB topology assets for authenticated map use."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


PIPELINE_COLUMNS = [
    "registered_pipeline_fid",
    "source_node_id",
    "target_node_id",
    "recomputed_length_m",
    "diameter_numeric",
    "pipe_material",
    "pipeline_status",
    "geometry",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_fgb(frame: Any, path: Path, *, layer: str) -> None:
    temporary = path.with_name(f".{path.stem}.tmp.fgb")
    temporary.unlink(missing_ok=True)
    frame.to_file(temporary, driver="FlatGeobuf", layer=layer)
    temporary.replace(path)


def package(private_root: Path, output_root: Path) -> dict[str, Any]:
    import geopandas as gpd

    private_root = private_root.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    node_source = private_root / "customer_stormwater_nodes.private.parquet"
    pipeline_source = private_root / "customer_stormwater_pipelines.private.parquet"
    if not node_source.is_file() or not pipeline_source.is_file():
        raise FileNotFoundError("customer_gdb_private_topology_artifacts_missing")

    nodes = gpd.read_parquet(node_source)
    pipelines = gpd.read_parquet(pipeline_source)
    if len(nodes) != 238350 or len(pipelines) != 238287:
        raise ValueError("customer_gdb_topology_count_mismatch")
    if nodes.crs is None or pipelines.crs is None:
        raise ValueError("customer_gdb_topology_crs_missing")
    if nodes.geometry.isna().any() or pipelines.geometry.isna().any():
        raise ValueError("customer_gdb_topology_null_geometry")

    output_root.mkdir(parents=True, exist_ok=True)
    node_output = output_root / "abu_dhabi_customer_stormwater_topology_nodes_full.fgb"
    pipeline_output = output_root / "abu_dhabi_customer_stormwater_gdb_pipeline_full.fgb"
    _write_fgb(nodes.to_crs("EPSG:4326"), node_output, layer="STORMWATER_TOPOLOGY_NODE")
    _write_fgb(
        pipelines[PIPELINE_COLUMNS].to_crs("EPSG:4326"),
        pipeline_output,
        layer="STORMWATER_PIPELINE",
    )
    receipt = {
        "schema": "gwm.abu_dhabi_flood.customer_stormwater_map_assets.v1",
        "status": "private_authenticated_map_derivatives_created",
        "files": {
            "topology_nodes": {
                "path": node_output.name,
                "feature_count": len(nodes),
                "sha256": _sha256(node_output),
            },
            "pipelines": {
                "path": pipeline_output.name,
                "feature_count": len(pipelines),
                "sha256": _sha256(pipeline_output),
            },
        },
        "semantics": {
            "topology_nodes": "0.1_m_snap_derived_pipe_endpoint_nodes_not_raw_facility_inventory",
            "pipelines": "customer_gdb_normalized_model_input_geometry",
        },
        "privacy": {
            "public_repository_allowed": False,
            "authenticated_private_delivery_only": True,
        },
    }
    manifest = output_root / "abu_dhabi_customer_stormwater_map_assets_manifest.json"
    manifest.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.private_root, args.output_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
