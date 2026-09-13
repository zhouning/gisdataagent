from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from data_agent.uwm.spatial_scope_registry import build_spatial_scope_registry


def _crs(payload):
    return str((((payload.get("crs") or {}).get("properties") or {}).get("name") or "unknown"))


def _write(product, source, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True); bundle_id = product["bundle_id"]
    bindings = [{"unit_id": unit["unit_id"], "source_feature_index": unit["source_feature_index"]} for unit in product["spatial_units"]]
    payloads = {
        "overview.json": {key: value for key, value in product.items() if key not in {"spatial_units", "scope_registry", "diagnostics", "data_contracts"}},
        "spatial_units.json": {"schema": "uwm.spatial_scope_units.v1", "bundle_id": bundle_id, "spatial_units": product["spatial_units"]},
        "scope_registry.json": {"schema": "uwm.spatial_scope_registry.v1", "bundle_id": bundle_id, "scope_registry": product["scope_registry"]},
        "diagnostics.json": {"schema": "uwm.spatial_scope_diagnostics.v1", "bundle_id": bundle_id, "diagnostics": product["diagnostics"]},
        "data_contracts.json": {"schema": "uwm.spatial_scope_contracts.v1", "bundle_id": bundle_id, "data_contracts": product["data_contracts"]},
        "map.json": {"schema": "uwm.spatial_scope_map.v1", "bundle_id": bundle_id, "source_dataset_id": product["scope_registry"]["source_dataset_id"], "source_layer_reference": "admin_units/chongqing_township_admin_units.geojson", "feature_bindings": bindings, "geometry_embedded": False, "evidence_status": "fragile"},
    }
    for name, payload in payloads.items():
        temporary = output_dir / f".{name}.tmp"; temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))); temporary.replace(output_dir / name)


def build_product(*, source_path: Path, manifest_path: Path, output_dir: Path):
    source = json.loads(source_path.read_text()); manifest = json.loads(manifest_path.read_text())
    product = build_spatial_scope_registry(features=source.get("features") or [], crs=_crs(source), source_dataset_id=manifest.get("dataset_id") or source_path.stem, source_manifest=manifest)
    _write(product, source, output_dir); return product


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--source", type=Path, required=True); parser.add_argument("--manifest", type=Path, required=True); parser.add_argument("--output-dir", type=Path, required=True); args = parser.parse_args()
    product = build_product(source_path=args.source, manifest_path=args.manifest, output_dir=args.output_dir); print(json.dumps({"bundle_id": product["bundle_id"], "summary": product["summary"], "diagnostics": product["diagnostics"]}, ensure_ascii=False))


if __name__ == "__main__": main()
