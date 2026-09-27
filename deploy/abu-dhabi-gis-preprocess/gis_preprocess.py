#!/usr/bin/env python3
"""Governed GIS source-data inventory and Abu Dhabi FileGDB compilation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "gwm.gis_preprocess.run_manifest.v1"
MAX_ARCHIVE_MEMBERS = 100_000
MAX_UNCOMPRESSED_BYTES = 100 * 1024**3


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _private_output_root(path: Path) -> Path:
    output = path.expanduser().resolve()
    input_root = Path(os.environ.get("GIS_PREPROCESS_INPUT_ROOT", "/input")).resolve()
    if output == input_root or input_root in output.parents:
        raise ValueError("output_must_not_be_inside_read_only_input")
    if output == Path("/"):
        raise ValueError("filesystem_root_not_allowed_as_output")
    output.mkdir(parents=True, exist_ok=True)
    return output


def _safe_extract_gdb_archive(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        members = source.infolist()
        if len(members) > MAX_ARCHIVE_MEMBERS:
            raise ValueError("gdb_archive_member_limit_exceeded")
        total_bytes = sum(member.file_size for member in members)
        if total_bytes > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("gdb_archive_uncompressed_size_limit_exceeded")
        for member in members:
            name = member.filename.replace("\\", "/")
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("gdb_archive_unsafe_member_path")
            mode = member.external_attr >> 16
            if mode and (mode & 0o170000) == 0o120000:
                raise ValueError("gdb_archive_symlink_not_allowed")
        source.extractall(destination)
    candidates = sorted(destination.rglob("*.gdb"), key=lambda item: str(item))
    if len(candidates) != 1 or not candidates[0].is_dir():
        raise ValueError("gdb_archive_must_contain_exactly_one_filegdb_directory")
    return candidates[0]


def _inventory(path: Path) -> dict[str, Any]:
    import pyogrio

    resolved = path.expanduser().resolve()
    if resolved.is_file() and resolved.suffix.casefold() == ".zip":
        with tempfile.TemporaryDirectory(prefix="gis-inventory-") as temporary:
            source = _safe_extract_gdb_archive(resolved, Path(temporary))
            return _inventory_gdb(source, archive_path=resolved)
    if resolved.is_dir() and resolved.suffix.casefold() == ".gdb":
        return _inventory_gdb(resolved)
    info = pyogrio.read_info(resolved)
    return {
        "source_path": resolved.name,
        "source_format": info.get("driver"),
        "layer_count": 1,
        "layers": [_layer_inventory(resolved, None, info)],
    }


def _layer_inventory(path: Path, layer: str | None, info: dict[str, Any]) -> dict[str, Any]:
    import pyogrio

    selected = layer or info.get("layer_name")
    try:
        count = int(pyogrio.read_info(path, layer=selected).get("features", -1))
    except Exception:
        count = int(info.get("features", -1))
    bounds = info.get("total_bounds")
    return {
        "name": selected,
        "driver": info.get("driver"),
        "geometry_type": info.get("geometry_type"),
        "crs": info.get("crs"),
        "feature_count": count,
        "fields": [str(field) for field in info.get("fields", [])],
        "bounds": list(bounds) if bounds is not None else None,
    }


def _inventory_gdb(gdb: Path, *, archive_path: Path | None = None) -> dict[str, Any]:
    import pyogrio

    layers = []
    for raw_layer in pyogrio.list_layers(gdb):
        name = str(raw_layer[0])
        info = pyogrio.read_info(gdb, layer=name)
        layers.append(_layer_inventory(gdb, name, info))
    result: dict[str, Any] = {
        "source_path": archive_path.name if archive_path else gdb.name,
        "source_format": "FileGDB",
        "layer_count": len(layers),
        "layers": layers,
    }
    if archive_path:
        result["source_archive"] = {
            "size_bytes": archive_path.stat().st_size,
            "sha256": _sha256(archive_path),
        }
    return result


def command_inventory(args: argparse.Namespace) -> int:
    source = Path(args.source)
    if not source.exists():
        raise ValueError("source_path_not_found")
    report = _inventory(source)
    if args.output:
        destination = _private_output_root(Path(args.output))
        report_path = destination / "source_inventory.json"
        _json(report_path, report)
        report["inventory_report"] = str(report_path)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def command_compile_abudhabi_gdb(args: argparse.Namespace) -> int:
    from data_agent.uwm.abu_dhabi_flood.customer_gdb_network import (
        CustomerGwmStaticTensorPolicy,
        compile_customer_gdb_network,
        compile_customer_gwm_static_tensors,
    )

    source = Path(args.gdb).expanduser().resolve()
    if not source.exists():
        raise ValueError("gdb_source_not_found")
    output = _private_output_root(Path(args.output_root))
    temporary_root: Path | None = None
    archive_path: Path | None = None
    try:
        if source.is_file() and source.suffix.casefold() == ".zip":
            temporary_root = Path(tempfile.mkdtemp(prefix="abu-gdb-"))
            source = _safe_extract_gdb_archive(source, temporary_root)
            archive_path = Path(args.gdb).expanduser().resolve()
        manifest = compile_customer_gdb_network(
            source,
            output_root=output,
            source_archive_path=archive_path,
        )
        inventory = _inventory_gdb(source, archive_path=archive_path)
        _json(output / "source_inventory.json", inventory)
        if args.compile_gwm_static_tensors:
            compile_customer_gwm_static_tensors(
                output,
                policy=CustomerGwmStaticTensorPolicy(
                    maximum_nodes_per_partition=args.maximum_nodes_per_partition
                ),
            )
        source_archive = manifest.get("source_archive")
        receipt = {
            "schema": SCHEMA,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "pipeline": "abu_dhabi_customer_stormwater_filegdb_v1",
            "status": "completed_diagnostic_only",
            "source": {
                "format": "FileGDB",
                "logical_name": source.name,
                "archive": source_archive,
                "gdb_inventory": "source_inventory.json",
            },
            "outputs": {
                "network_manifest": "customer_gdb_network_private_manifest.json",
                "aggregate_audit": "customer_gdb_network_aggregate_audit.json",
                "static_graph_contract": "customer_gwm_static_graph_contract.json",
                "swmm_citywide_input_generated": False,
                "surface_grid_generated": False,
                "coupling_bindings_generated": False,
            },
            "model_readiness": {
                "network_engineering_admitted": False,
                "swmm_citywide_ready": False,
                "surface_model_ready": False,
                "pump_station_inputs_included": False,
                "tide_boundary_inputs_included": False,
                "land_use_inputs_included": False,
            },
            "claim_boundary": manifest["claim_boundary"],
        }
        _json(output / "gis_preprocess_run_manifest.json", receipt)
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2))
    finally:
        if temporary_root is not None:
            shutil.rmtree(temporary_root)
    return 0


def command_compile_pump_stations(args: argparse.Namespace) -> int:
    from source_adapters import compile_pump_stations

    manifest = compile_pump_stations(
        Path(args.source),
        output_root=_private_output_root(Path(args.output_root)),
        layer=args.layer,
        target_crs=args.target_crs,
        flow_unit=args.flow_unit,
        capacity_unit=args.capacity_unit,
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def command_compile_tide_boundaries(args: argparse.Namespace) -> int:
    from source_adapters import compile_tide_boundaries

    manifest = compile_tide_boundaries(
        Path(args.source),
        output_root=_private_output_root(Path(args.output_root)),
        timestamp_field=args.timestamp_field,
        value_field=args.value_field,
        boundary_field=args.boundary_field,
        value_kind=args.value_kind,
        value_unit=args.value_unit,
        timezone=args.timezone,
        vertical_datum=args.vertical_datum,
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def command_compile_land_use(args: argparse.Namespace) -> int:
    from source_adapters import compile_land_use

    manifest = compile_land_use(
        Path(args.source),
        output_root=_private_output_root(Path(args.output_root)),
        layer=args.layer,
        class_field=args.class_field,
        code_field=args.code_field,
        imperviousness_field=args.imperviousness_field,
        target_crs=args.target_crs,
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inventory and compile governed GIS source data into model artifacts."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory = subparsers.add_parser("inventory", help="inventory vector dataset metadata")
    inventory.add_argument("--source", required=True, help="file, FileGDB directory, or GDB ZIP")
    inventory.add_argument("--output", help="private directory for source_inventory.json")
    inventory.set_defaults(handler=command_inventory)

    compile_group = subparsers.add_parser(
        "compile-abudhabi-stormwater-gdb",
        help="compile the customer's stormwater FileGDB to normalized private network data",
    )
    compile_group.add_argument("--gdb", required=True, help="FileGDB directory or ZIP archive")
    compile_group.add_argument("--output-root", required=True, help="private writable output directory")
    compile_group.add_argument("--compile-gwm-static-tensors", action="store_true")
    compile_group.add_argument("--maximum-nodes-per-partition", type=int, default=8192)
    compile_group.set_defaults(handler=command_compile_abudhabi_gdb)

    pump_group = subparsers.add_parser(
        "compile-pump-stations",
        help="normalize pump-station geometry and attributes into a private GeoParquet contract",
    )
    pump_group.add_argument("--source", required=True, help="vector source or FileGDB ZIP/directory")
    pump_group.add_argument("--output-root", required=True, help="private writable output directory")
    pump_group.add_argument("--layer", default="PS_PUMP", help="source layer; defaults to PS_PUMP")
    pump_group.add_argument("--target-crs", default="EPSG:32640")
    pump_group.add_argument("--flow-unit", help="explicit flow unit, for example m3/s")
    pump_group.add_argument("--capacity-unit", help="explicit capacity unit, for example m3")
    pump_group.set_defaults(handler=command_compile_pump_stations)

    tide_group = subparsers.add_parser(
        "compile-tide-boundaries",
        help="normalize timestamped tide/stage/flow observations into a private Parquet contract",
    )
    tide_group.add_argument("--source", required=True, help="CSV or Parquet source")
    tide_group.add_argument("--output-root", required=True, help="private writable output directory")
    tide_group.add_argument("--timestamp-field", required=True)
    tide_group.add_argument("--value-field", required=True)
    tide_group.add_argument("--boundary-field")
    tide_group.add_argument("--value-kind", choices=("stage", "flow"), default="stage")
    tide_group.add_argument("--value-unit", help="explicit unit, for example m or m3/s")
    tide_group.add_argument("--timezone", default="UTC")
    tide_group.add_argument("--vertical-datum", help="explicit vertical datum")
    tide_group.set_defaults(handler=command_compile_tide_boundaries)

    land_group = subparsers.add_parser(
        "compile-land-use",
        help="normalize land-use polygons and private area metrics into GeoParquet",
    )
    land_group.add_argument("--source", required=True, help="vector source or FileGDB ZIP/directory")
    land_group.add_argument("--output-root", required=True, help="private writable output directory")
    land_group.add_argument("--layer", help="source layer for a multilayer FileGDB")
    land_group.add_argument("--class-field", help="land-use class field")
    land_group.add_argument("--code-field", help="land-use code field")
    land_group.add_argument("--imperviousness-field", help="imperviousness fraction field")
    land_group.add_argument("--target-crs", default="EPSG:32640")
    land_group.set_defaults(handler=command_compile_land_use)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.handler(args))
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
