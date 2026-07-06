"""OSM service accessibility public proxy for UWM livability state."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


OSM_SERVICE_ACCESSIBILITY_PROXY_SCHEMA = "uwm.osm_service_accessibility_proxy.v1"
OSM_SERVICE_ACCESSIBILITY_DATASET_ID = "osm_services_geometry_public_proxy"


_CATEGORY_BY_AMENITY = {
    "hospital": "healthcare",
    "clinic": "healthcare",
    "doctors": "healthcare",
    "dentist": "healthcare",
    "pharmacy": "healthcare",
    "school": "education",
    "kindergarten": "education",
    "college": "education",
    "university": "education",
    "library": "education",
    "restaurant": "food_retail",
    "fast_food": "food_retail",
    "cafe": "food_retail",
    "bar": "food_retail",
    "ice_cream": "food_retail",
    "bank": "finance",
    "atm": "finance",
    "post_office": "civic_public",
    "police": "civic_public",
    "toilets": "civic_public",
    "place_of_worship": "civic_public",
    "social_centre": "civic_public",
    "bus_station": "mobility_parking",
    "ferry_terminal": "mobility_parking",
    "parking": "mobility_parking",
    "parking_entrance": "mobility_parking",
    "fuel": "mobility_parking",
    "charging_station": "mobility_parking",
    "cinema": "recreation",
    "nightclub": "recreation",
    "fountain": "recreation",
}


def build_osm_service_accessibility_proxy(
    *,
    raw_payload: dict[str, Any],
    requested_bbox: list[float],
    fetched_at: str,
) -> dict[str, Any]:
    """Normalize OSM amenity nodes with coordinates into a service proxy."""

    elements = raw_payload.get("elements") or []
    amenity_counter = Counter()
    category_counter = Counter()
    service_points = []
    coordinate_count = 0
    for element in elements:
        tags = element.get("tags") or {}
        amenity = str(tags.get("amenity") or "")
        if not amenity:
            continue
        amenity_counter[amenity] += 1
        category = _CATEGORY_BY_AMENITY.get(amenity, "other_service")
        category_counter[category] += 1
        lat, lon = _element_lat_lon(element)
        has_coordinates = lat is not None and lon is not None
        if has_coordinates:
            coordinate_count += 1
            service_points.append(
                {
                    "osm_type": element.get("type"),
                    "osm_id": element.get("id"),
                    "amenity": amenity,
                    "service_category": category,
                    "latitude": lat,
                    "longitude": lon,
                    "name": str(tags.get("name") or tags.get("name:zh") or ""),
                }
            )
    amenity_count = sum(amenity_counter.values())
    essential_service_count = category_counter["healthcare"] + category_counter["education"]
    return {
        "schema": OSM_SERVICE_ACCESSIBILITY_PROXY_SCHEMA,
        "source": "OpenStreetMap Overpass API",
        "source_dataset_ids": [OSM_SERVICE_ACCESSIBILITY_DATASET_ID],
        "osm_base_timestamp": (raw_payload.get("osm3s") or {}).get("timestamp_osm_base"),
        "fetched_at": fetched_at,
        "requested_bbox": requested_bbox,
        "record_counts": {
            "elements": len(elements),
            "coordinate_elements": coordinate_count,
            "amenity_elements": amenity_count,
        },
        "amenity_distribution": dict(sorted(amenity_counter.items())),
        "service_category_counts": dict(sorted(category_counter.items())),
        "coordinate_coverage": {
            "coordinate_element_share": round(coordinate_count / len(elements), 6) if elements else 0.0,
        },
        "service_points": service_points,
        "service_accessibility_proxy": {
            "essential_service_count": essential_service_count,
            "service_category_count": len(category_counter),
            "food_retail_count": category_counter["food_retail"],
            "healthcare_count": category_counter["healthcare"],
            "education_count": category_counter["education"],
        },
        "mmfe_target_roles": ["service_accessibility", "planner_targeting", "baseline_context"],
        "synthetic_flags": [{"dataset_id": OSM_SERVICE_ACCESSIBILITY_DATASET_ID, "status": "public_proxy"}],
        "claim_boundary": {
            "max_claim_level": "bounded_support",
            "reason": "OSM Overpass bbox service extract supports bounded service-accessibility context only.",
        },
        "limitations": [
            "overpass_bbox_extract_not_full_municipality",
            "osm_tag_completeness_varies_spatially",
            "not_a_network_travel_time_accessibility_surface",
            "odbl_attribution_required",
        ],
        "empirical_superiority_claim": False,
    }


def write_osm_service_accessibility_snapshot(
    *,
    output_dir: str | Path,
    raw_payload: dict[str, Any],
    requested_bbox: list[float],
    fetched_at: str,
) -> dict[str, Any]:
    """Persist raw OSM payload, normalized service proxy and manifest."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    _write_json(output_path / "osm_services_overpass_geometry_raw.json", raw_payload)
    proxy = build_osm_service_accessibility_proxy(
        raw_payload=raw_payload,
        requested_bbox=requested_bbox,
        fetched_at=fetched_at,
    )
    _write_json(output_path / "osm_service_accessibility_proxy.json", proxy)
    manifest = {
        "schema": "uwm.public_proxy_snapshot_manifest.v1",
        "dataset_id": "osm_service_accessibility_proxy_snapshot",
        "source_dataset_ids": proxy["source_dataset_ids"],
        "fetched_at": fetched_at,
        "requested_bbox": requested_bbox,
        "files": {
            "raw": "osm_services_overpass_geometry_raw.json",
            "normalized_proxy": "osm_service_accessibility_proxy.json",
        },
        "record_counts": proxy["record_counts"],
        "service_accessibility_proxy": proxy["service_accessibility_proxy"],
        "claim_boundary": proxy["claim_boundary"],
        "limitations": proxy["limitations"],
        "mmfe_target_roles": proxy["mmfe_target_roles"],
        "empirical_superiority_claim": False,
    }
    _write_json(output_path / "snapshot_manifest.json", manifest)
    return manifest


def build_mmfe_state_input_from_osm_service_accessibility_proxy(
    proxy: dict[str, Any],
    *,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Convert OSM service proxy into MMFE UWM state input."""

    from .mmfe_state_input import build_uwm_state_input_from_semantic_product

    if proxy.get("schema") != OSM_SERVICE_ACCESSIBILITY_PROXY_SCHEMA:
        raise ValueError(f"proxy schema must be {OSM_SERVICE_ACCESSIBILITY_PROXY_SCHEMA}")
    osm_time = str(proxy.get("osm_base_timestamp") or "unknown_osm_time")
    coordinate_count = (proxy.get("record_counts") or {}).get("coordinate_elements", 0)
    payload = build_uwm_state_input_from_semantic_product(
        {
            "product_id": f"mmfe-osm-service-accessibility-{osm_time}",
            "product_type": "semantic_fusion_product",
            "version": "0.1",
            "quality": {"score": 0.50},
        },
        semantic_relations=[
            {
                "semantic_relation_type": "bbox_contains_osm_service_point",
                "uwm_usage": "service_accessibility",
                "relation_count": coordinate_count,
            },
            {
                "semantic_relation_type": "service_point_has_amenity_category",
                "uwm_usage": "service_accessibility",
                "relation_count": len(proxy.get("service_category_counts") or {}),
            },
        ],
        input_contract={
            "spatial_unit": {
                "unit_type": "osm_bbox_service_point_sample",
                "crs": "EPSG:4326",
                "spatial_extent": proxy.get("requested_bbox"),
                "temporal_extent": osm_time,
            },
            "role_bindings": [
                {
                    "role": "osm_service_accessibility_points",
                    "uwm_role": "service_accessibility",
                    "object_type": "point_sample",
                    "source_dataset_id": OSM_SERVICE_ACCESSIBILITY_DATASET_ID,
                    "synthetic_status": "public_proxy",
                }
            ],
        },
        timestamp=timestamp,
    )
    payload["source_proxy"] = {
        "schema": proxy.get("schema"),
        "osm_base_timestamp": proxy.get("osm_base_timestamp"),
        "record_counts": proxy.get("record_counts"),
        "claim_boundary": proxy.get("claim_boundary"),
        "limitations": proxy.get("limitations") or [],
        "empirical_superiority_claim": False,
    }
    payload["warnings"].append(
        "OSM Overpass bbox extract is not a complete service accessibility surface and lacks network travel-time modelling"
    )
    return payload


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _element_lat_lon(element: dict[str, Any]) -> tuple[float | None, float | None]:
    """Return coordinates from OSM nodes or Overpass `out center` elements."""

    lat = _float(element.get("lat"))
    lon = _float(element.get("lon"))
    if lat is not None and lon is not None:
        return lat, lon
    center = element.get("center") or {}
    if not isinstance(center, dict):
        return None, None
    return _float(center.get("lat")), _float(center.get("lon"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
