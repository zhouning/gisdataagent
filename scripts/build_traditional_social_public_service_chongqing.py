from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_agent.uwm.traditional_social_public_service import build_social_public_service_product

CATEGORY_MAP = {
    "education.school": "education",
    "education.primary_school": "education",
    "healthcare.facility": "healthcare",
    "green_space.park": "park_recreation",
    "sports.facility": "sports",
    "culture.facility": "culture",
    "government_community.facility": "government_service",
}


def build_product(*, facility_product_path: Path, mobility_admin_units_path: Path, output_dir: Path) -> dict[str, Any]:
    facility_source = _load(facility_product_path)
    mobility_source = _load(mobility_admin_units_path)
    if facility_source.get("schema") != "uwm.traditional_livability.facility_product.v1":
        raise ValueError("facility_product_schema_invalid")
    if mobility_source.get("schema") != "traditional_livability.mobility_admin_units.v1":
        raise ValueError("mobility_admin_units_schema_invalid")

    admin_names = {str(row["admin_code"]): row.get("admin_name") for row in facility_source.get("population_units", []) if row.get("admin_code")}
    admins = [{
        "admin_unit_id": code,
        "county": name,
        "township": None,
        "service_accessibility_score": None,
    } for code, name in admin_names.items() if code != "500000"]
    admin_codes_by_name = {name: code for code, name in admin_names.items() if name}
    facilities = []
    unmapped_admin_count = 0
    for index, source in enumerate(facility_source.get("facilities", [])):
        category = CATEGORY_MAP.get(source.get("canonical_class"))
        if not category:
            continue
        raw_admin = source.get("admin_code")
        admin_code = str(raw_admin) if raw_admin is not None else ""
        if admin_code not in admin_names:
            admin_code = admin_codes_by_name.get(raw_admin, "")
        if admin_code not in admin_names or admin_code == "500000":
            unmapped_admin_count += 1
            admin_code = None
        facilities.append({
            "facility_id": f"{source.get('source_dataset_id')}:{source.get('source_record_id')}",
            "name": source.get("name"),
            "raw_category": source.get("raw_secondary_class") or source.get("raw_primary_class"),
            "canonical_category": category,
            "longitude": source.get("longitude"),
            "latitude": source.get("latitude"),
            "admin_unit_id": admin_code,
            "source_dataset": source.get("source_dataset_id"),
            "source_record_id": source.get("source_record_id"),
            "classification_method": source.get("mapping_status") or "upstream_semantic_mapping",
            "classification_confidence": None,
        })
    product = build_social_public_service_product(
        facilities=facilities,
        admin_units=admins,
        source_artifacts=[str(facility_product_path), str(mobility_admin_units_path)],
    )
    product["production_blockers"] = sorted(set(product["production_blockers"] + [
        "township_accessibility_not_joined_to_county_facilities",
        "facility_inventory_sampling_not_complete" if not facility_source.get("source_manifest", {}).get("complete_inventory") else "",
    ]) - {""})
    product["summary"].update({
        "source_facility_count": len(facility_source.get("facilities", [])),
        "selected_facility_count": len(facilities),
        "unmapped_selected_facility_admin_count": unmapped_admin_count,
        "source_township_accessibility_unit_count": len(mobility_source.get("admin_units", [])),
        "joined_township_accessibility_unit_count": 0,
        "selected_category_counts": dict(sorted(Counter(row["canonical_category"] for row in facilities).items())),
    })
    product["fabricated_value_count"] = 0
    _write_bundle(product, output_dir)
    return product


def _write_bundle(product: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_id = product["bundle_id"]
    payloads = {
        "overview.json": {key: value for key, value in product.items() if key not in {"facilities", "admin_units", "channel_readiness"}},
        "facilities.json": {"schema": "traditional_livability.social_public_service_facilities.v1", "bundle_id": bundle_id, "facilities": product["facilities"]},
        "admin_units.json": {"schema": "traditional_livability.social_public_service_admin_units.v1", "bundle_id": bundle_id, "admin_units": product["admin_units"]},
        "channel_readiness.json": {"schema": "traditional_livability.social_public_service_readiness.v1", "bundle_id": bundle_id, "channel_readiness": product["channel_readiness"]},
        "map.json": {"schema": "traditional_livability.social_public_service_map.v1", "bundle_id": bundle_id, "layers": _map_layers(product)},
    }
    for filename, payload in payloads.items():
        temporary = output_dir / f".{filename}.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        temporary.replace(output_dir / filename)


def _map_layers(product: dict[str, Any]) -> list[dict[str, Any]]:
    features = []
    for row in product["facilities"]:
        if row.get("longitude") is None or row.get("latitude") is None:
            continue
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [row["longitude"], row["latitude"]]}, "properties": {"facility_id": row["facility_id"], "name": row["name"], "canonical_category": row["canonical_category"], "view_membership": row["view_membership"], "admin_unit_id": row["admin_unit_id"]}})
    return [{"name": "社会基础设施与公共服务设施", "type": "geojson", "geojsonData": {"type": "FeatureCollection", "features": features}}]


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--facility-product", type=Path, required=True)
    parser.add_argument("--mobility-admin-units", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    product = build_product(facility_product_path=args.facility_product, mobility_admin_units_path=args.mobility_admin_units, output_dir=args.output_dir)
    print(json.dumps({"bundle_id": product["bundle_id"], "summary": product["summary"], "production_blockers": product["production_blockers"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
