from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from data_agent.uwm.infrastructure_network_readiness import build_infrastructure_network_readiness_product


SELECTED = {
    "chongqing_osm_roads_2021": ("visible_road_inventory", "visible_vector", "重庆OSM道路2021审计"),
    "chongqing_central_buildings_2021": ("visible_building_inventory", "visible_vector", "重庆中心城区建筑2021审计"),
    "chongqing_unicom_commuting_2023_local": ("mobility_activity_proxy", "commuting_od_proxy", "联通职住通勤OD代理审计"),
}


def _assets(audit, repo_root: Path):
    rows = []
    for group_name in ("vector_profiles", "tabular_profiles"):
        for profile in audit.get(group_name) or []:
            asset_id = profile.get("asset_id")
            if asset_id not in SELECTED: continue
            role, source_kind, title = SELECTED[asset_id]
            rows.append({"asset_id": asset_id, "title": title, "asset_role": role, "source_kind": source_kind, "source_path": profile.get("source_path") or "audit_profile_without_source_path", "feature_count": profile.get("feature_count"), "row_count": profile.get("row_count"), "geometry_type": profile.get("geometry_type"), "crs": profile.get("crs"), "bounds": profile.get("bounds"), "fields": profile.get("fields") or profile.get("columns") or [], "observation_status": "audit_inventory_only", "capacity_status": "unavailable", "ownership_status": "unavailable", "operations_status": "unavailable", "limitations": ["source_rows_not_materialized_in_product", "asset_inventory_not_capacity_or_condition"]})
    for source_path, title in (("data_agent/standards/compiled_docx/01_统一地理底图.yaml", "统一地理底图市政字段标准"), ("data_agent/standards/compiled_docx/06_用途管制1128V2.yaml", "用途管制市政字段标准")):
        if (repo_root / source_path).is_file(): rows.append({"asset_id": source_path.split("/")[-1].replace(".yaml", ""), "title": title, "asset_role": "utility_data_contract", "source_kind": "field_standard", "source_path": source_path, "feature_count": None, "row_count": None, "fields": [], "observation_status": "contract_only", "capacity_status": "unavailable", "ownership_status": "unavailable", "operations_status": "unavailable", "limitations": ["field_standard_not_observed_utility_network"]})
    return sorted(rows, key=lambda row: row["asset_id"])


def _write(product, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True); bundle_id = product["bundle_id"]
    payloads = {
        "overview.json": {key: value for key, value in product.items() if key not in {"infrastructure_assets", "utility_channels", "data_contracts", "kernel_gate"}},
        "infrastructure_assets.json": {"schema": "uwm.infrastructure_assets.v1", "bundle_id": bundle_id, "infrastructure_assets": product["infrastructure_assets"]},
        "utility_channels.json": {"schema": "uwm.utility_channels.v1", "bundle_id": bundle_id, "utility_channels": product["utility_channels"]},
        "data_contracts.json": {"schema": "uwm.infrastructure_network_contracts.v1", "bundle_id": bundle_id, "data_contracts": product["data_contracts"]},
        "kernel_gate.json": {"schema": "uwm.infrastructure_cascade_kernel_gate.v1", "bundle_id": bundle_id, "kernel_gate": product["kernel_gate"]},
        "map.json": {"schema": "uwm.infrastructure_network_map.v1", "bundle_id": bundle_id, "layers": [{"asset_id": asset["asset_id"], "source_path": asset["source_path"], "geometry_embedded": False, "asset_role": asset["asset_role"]} for asset in product["infrastructure_assets"] if asset.get("geometry_type")]},
    }
    for name, payload in payloads.items():
        temporary = output_dir / f".{name}.tmp"; temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))); temporary.replace(output_dir / name)


def build_product(*, audit_path: Path, repo_root: Path, output_dir: Path):
    audit = json.loads(audit_path.read_text()); assets = _assets(audit, repo_root)
    product = build_infrastructure_network_readiness_product(assets=assets, source_artifacts=[str(audit_path)] + [asset["source_path"] for asset in assets if asset["source_kind"] == "field_standard"]); _write(product, output_dir); return product


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--audit", type=Path, required=True); parser.add_argument("--repo-root", type=Path, required=True); parser.add_argument("--output-dir", type=Path, required=True); args = parser.parse_args()
    product = build_product(audit_path=args.audit, repo_root=args.repo_root, output_dir=args.output_dir); print(json.dumps({"bundle_id": product["bundle_id"], "summary": product["summary"]}, ensure_ascii=False))


if __name__ == "__main__": main()
