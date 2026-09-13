from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_agent.uwm.asset_lifecycle_readiness import build_asset_lifecycle_readiness_product


DEFAULT_SPECS = (
    ("infrastructure", "infrastructure_network_readiness_chongqing/overview.json", ("visible_building_feature_count", "visible_road_feature_count"), "visible_building_and_road_features"),
    ("social_public_service", "traditional_social_public_service_chongqing/overview.json", ("selected_facility_count",), "selected_facility_pois"),
    ("public_space", "traditional_public_space_chongqing/overview.json", ("eligible_space_count",), "eligible_public_space_pois"),
    ("cultural_heritage", "traditional_cultural_heritage_chongqing/overview.json", ("confirmed_place_count", "candidate_lead_count"), "cultural_place_and_candidate_records"),
    ("business_activity", "business_licence_chongqing/overview.json", ("business_poi_count",), "business_activity_pois"),
    ("digital_capability", "digital_readiness_chongqing/overview.json", ("platform_capability_count",), "platform_capability_catalog_records"),
)


def _nested_summary_value(summary, field):
    value = summary.get(field)
    return int(value) if isinstance(value, (int, float)) else 0


def _write(product, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_id = product["bundle_id"]
    payloads = {
        "overview.json": {key: value for key, value in product.items() if key not in {"source_products", "lifecycle_channels", "data_contracts", "lifecycle_gate"}},
        "source_products.json": {"schema": "uwm.asset_lifecycle_source_products.v1", "bundle_id": bundle_id, "source_products": product["source_products"]},
        "lifecycle_channels.json": {"schema": "uwm.asset_lifecycle_channels.v1", "bundle_id": bundle_id, "lifecycle_channels": product["lifecycle_channels"]},
        "data_contracts.json": {"schema": "uwm.asset_lifecycle_contracts.v1", "bundle_id": bundle_id, "data_contracts": product["data_contracts"]},
        "lifecycle_gate.json": {"schema": "uwm.asset_lifecycle_gate.v1", "bundle_id": bundle_id, "lifecycle_gate": product["lifecycle_gate"]},
        "map.json": {"schema": "uwm.asset_lifecycle_map.v1", "bundle_id": bundle_id, "layers": []},
    }
    for name, payload in payloads.items():
        temporary = output_dir / f".{name}.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        temporary.replace(output_dir / name)


def build_product(*, source_specs, output_dir: Path):
    products = []
    for spec in source_specs:
        source_path = Path(spec["source_path"])
        overview = json.loads(source_path.read_text())
        summary = overview.get("summary") or {}
        fields = list(spec.get("record_fields") or [])
        products.append({
            "product_id": spec["product_id"],
            "source_path": str(source_path),
            "bundle_id": overview.get("bundle_id"),
            "record_count": sum(_nested_summary_value(summary, field) for field in fields),
            "record_count_fields": fields,
            "record_semantics": spec["record_semantics"],
            "asset_status": "catalog_evidence_only",
            "identity_evidence": None,
            "lifecycle_observation_status": "unavailable",
            "limitations": ["source_records_may_overlap_other_products", "records_not_authoritative_lifecycle_assets"],
        })
    product = build_asset_lifecycle_readiness_product(source_products=products, source_artifacts=[str(spec["source_path"]) for spec in source_specs])
    _write(product, output_dir)
    return product


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    specs = [{"product_id": product_id, "source_path": args.source_root / relative, "record_fields": fields, "record_semantics": semantics} for product_id, relative, fields, semantics in DEFAULT_SPECS]
    product = build_product(source_specs=specs, output_dir=args.output_dir)
    print(json.dumps({"bundle_id": product["bundle_id"], "summary": product["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
