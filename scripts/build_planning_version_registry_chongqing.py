from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from data_agent.uwm.planning_version_registry import build_planning_version_registry


SELECTED = {
    "bishan_land_use_dltb_local": ("land_use_parcel_layer", "璧山地类图斑审计资产"),
    "fulu_village_planning_database_local": ("village_planning_database_collection", "福禄村规划数据库审计资产"),
    "bishan_land_development_ledger_2019_local": ("land_development_approval_ledger", "2019年璧山土地开发台账审计资产"),
    "bishan_admin_boundary_cjdcq_local": ("administrative_cadastral_reference_layer", "璧山城镇村调查区参考图层"),
}


def _assets(audit):
    rows = []
    for group_name in ("vector_profiles", "tabular_profiles", "database_profiles"):
        for profile in audit.get(group_name) or []:
            asset_id = profile.get("asset_id")
            if asset_id not in SELECTED: continue
            asset_class, title = SELECTED[asset_id]
            rows.append({"asset_id": asset_id, "title": title, "asset_class": asset_class, "source_path": profile.get("source_path") or "audit_profile_without_source_path", "audit_group": group_name, "audit_status": profile.get("status"), "feature_count": profile.get("feature_count"), "row_count": profile.get("row_count"), "layer_count": profile.get("layer_count"), "sheet_count": profile.get("sheet_count"), "geometry_type": profile.get("geometry_type"), "crs": profile.get("crs"), "bounds": profile.get("bounds"), "fields": profile.get("fields") or [], "observed_folder_or_file_year": 2019 if asset_id == "bishan_land_development_ledger_2019_local" else None, "approval_status": "unverified", "version_status": "unresolved", "effective_start": None, "effective_end": None, "predecessor_version": None, "successor_version": None, "source_authority": None, "source_license_status": "pending", "limitations": ["sample_demo_package_context", "approval_and_effective_period_unverified", "version_lineage_missing"]})
    return sorted(rows, key=lambda row: row["asset_id"])


def _write(product, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True); bundle_id = product["bundle_id"]
    payloads = {
        "overview.json": {key: value for key, value in product.items() if key not in {"version_assets", "version_channels", "data_contracts", "temporal_gate"}},
        "version_assets.json": {"schema": "uwm.planning_version_assets.v1", "bundle_id": bundle_id, "version_assets": product["version_assets"]},
        "version_channels.json": {"schema": "uwm.planning_version_channels.v1", "bundle_id": bundle_id, "version_channels": product["version_channels"]},
        "data_contracts.json": {"schema": "uwm.planning_version_contracts.v1", "bundle_id": bundle_id, "data_contracts": product["data_contracts"]},
        "temporal_gate.json": {"schema": "uwm.planning_temporal_gate.v1", "bundle_id": bundle_id, "temporal_gate": product["temporal_gate"]},
        "map.json": {"schema": "uwm.planning_version_map.v1", "bundle_id": bundle_id, "layers": [{"asset_id": row["asset_id"], "source_path": row["source_path"], "layer_or_collection": row.get("asset_class"), "geometry_embedded": False, "approval_status": "unverified"} for row in product["version_assets"] if row.get("geometry_type")]},
    }
    for name, payload in payloads.items():
        temporary = output_dir / f".{name}.tmp"; temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))); temporary.replace(output_dir / name)


def build_product(*, audit_path: Path, output_dir: Path):
    audit = json.loads(audit_path.read_text()); assets = _assets(audit)
    product = build_planning_version_registry(assets=assets, source_artifacts=[str(audit_path)]); _write(product, output_dir); return product


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--audit", type=Path, required=True); parser.add_argument("--output-dir", type=Path, required=True); args = parser.parse_args()
    product = build_product(audit_path=args.audit, output_dir=args.output_dir); print(json.dumps({"bundle_id": product["bundle_id"], "summary": product["summary"]}, ensure_ascii=False))


if __name__ == "__main__": main()
