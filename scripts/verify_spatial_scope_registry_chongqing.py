from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


FILES = ("overview.json", "spatial_units.json", "scope_registry.json", "diagnostics.json", "data_contracts.json", "map.json")


def verify(root: Path):
    payloads = {name: json.loads((root / name).read_text()) for name in FILES}; bundle_ids = {payload.get("bundle_id") for payload in payloads.values()}
    if len(bundle_ids) != 1 or None in bundle_ids: raise ValueError("bundle_mismatch")
    overview = payloads["overview.json"]; units = payloads["spatial_units.json"]["spatial_units"]; registry = payloads["scope_registry.json"]["scope_registry"]; diagnostics = payloads["diagnostics.json"]["diagnostics"]; map_payload = payloads["map.json"]; bindings = map_payload["feature_bindings"]
    if overview.get("fabricated_value_count") != 0: raise ValueError("fabricated_value")
    if len(units) != overview["summary"]["spatial_unit_count"] or len(bindings) != len(units): raise ValueError("unit_map_count_mismatch")
    if map_payload.get("geometry_embedded") is not False or not map_payload.get("source_layer_reference"): raise ValueError("invalid_map_reference")
    if len({unit["unit_id"] for unit in units}) != len(units): raise ValueError("duplicate_unit_id")
    if any(unit.get("evidence_status") != "fragile" or not unit.get("source_dataset_id") for unit in units): raise ValueError("invalid_evidence_status")
    if registry.get("kernel_adjacency_requirement") != "independently_verified_adjacency_required": raise ValueError("unsafe_kernel_adjacency")
    if diagnostics.get("topology_validated") is not False or diagnostics.get("official_vintage_verified") is not False or diagnostics.get("source_license_verified") is not False: raise ValueError("false_authority_claim")
    digest = hashlib.sha256("".join((root / name).read_text() for name in FILES).encode()).hexdigest()
    return {"bundle_id": next(iter(bundle_ids)), "summary": overview["summary"], "diagnostics": diagnostics, "fabricated_value_count": 0, "digest": "sha256:" + digest}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("root", type=Path); args = parser.parse_args(); print(json.dumps(verify(args.root), ensure_ascii=False))


if __name__ == "__main__": main()
