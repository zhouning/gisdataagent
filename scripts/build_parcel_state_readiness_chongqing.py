from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from data_agent.uwm.parcel_state_readiness import build_parcel_state_readiness_product


SELECTED = {
    "bishan_land_use_dltb_local": ("primary_land_use_state_source", "璧山地类图斑字段与规模审计"),
    "fulu_village_planning_database_local": ("supporting_planned_use_source", "福禄村规划图层集合审计"),
    "bishan_land_development_ledger_2019_local": ("supporting_development_status_source", "2019年璧山土地开发台账审计"),
}


def _assets(audit):
    rows = []
    for group_name in ("vector_profiles", "tabular_profiles", "database_profiles"):
        for profile in audit.get(group_name) or []:
            asset_id = profile.get("asset_id")
            if asset_id not in SELECTED: continue
            role, title = SELECTED[asset_id]
            rows.append({"asset_id": asset_id, "title": title, "asset_role": role, "source_path": profile.get("source_path") or "audit_profile_without_source_path", "audit_group": group_name, "feature_count": profile.get("feature_count") if role == "primary_land_use_state_source" else 0, "profile_feature_count": profile.get("feature_count"), "row_count": profile.get("row_count"), "layer_count": profile.get("layer_count"), "geometry_type": profile.get("geometry_type"), "crs": profile.get("crs"), "bounds": profile.get("bounds"), "fields": profile.get("fields") or [], "required_state_fields_present": all(field in (profile.get("fields") or []) for field in ("BSM", "DLBM", "DLMC", "TBMJ")) if role == "primary_land_use_state_source" else None, "source_rows_materialized": False, "version_status": "unresolved", "state_status": "schema_audit_only", "limitations": ["source_feature_rows_not_materialized", "authoritative_version_baseline_missing", "no_land_use_distribution_or_transition_claim"]})
    return sorted(rows, key=lambda row: row["asset_id"])


def _write(product, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True); bundle_id = product["bundle_id"]
    payloads = {
        "overview.json": {key: value for key, value in product.items() if key not in {"source_assets", "state_channels", "data_contracts", "state_gate"}},
        "source_assets.json": {"schema": "uwm.parcel_state_source_assets.v1", "bundle_id": bundle_id, "source_assets": product["source_assets"]},
        "state_channels.json": {"schema": "uwm.parcel_state_channels.v1", "bundle_id": bundle_id, "state_channels": product["state_channels"]},
        "data_contracts.json": {"schema": "uwm.parcel_state_contracts.v1", "bundle_id": bundle_id, "data_contracts": product["data_contracts"]},
        "state_gate.json": {"schema": "uwm.parcel_state_gate.v1", "bundle_id": bundle_id, "state_gate": product["state_gate"]},
        "map.json": {"schema": "uwm.parcel_state_map.v1", "bundle_id": bundle_id, "layers": [{"asset_id": asset["asset_id"], "source_path": asset["source_path"], "geometry_embedded": False, "state_status": asset["state_status"]} for asset in product["source_assets"] if asset.get("geometry_type")]},
    }
    for name, payload in payloads.items():
        temporary = output_dir / f".{name}.tmp"; temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))); temporary.replace(output_dir / name)


def build_product(*, audit_path: Path, output_dir: Path):
    audit = json.loads(audit_path.read_text()); assets = _assets(audit)
    product = build_parcel_state_readiness_product(source_assets=assets, source_artifacts=[str(audit_path)]); _write(product, output_dir); return product


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--audit", type=Path, required=True); parser.add_argument("--output-dir", type=Path, required=True); args = parser.parse_args()
    product = build_product(audit_path=args.audit, output_dir=args.output_dir); print(json.dumps({"bundle_id": product["bundle_id"], "summary": product["summary"]}, ensure_ascii=False))


if __name__ == "__main__": main()
