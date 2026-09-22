#!/usr/bin/env python3
"""Build the controlled 506-point customer hotspot map derivative.

The source archive contains the official 506-point master list together with
auxiliary point, line and polygon features.  Admission is therefore based on
the Arabic customer ID field (``م``), not on geometry type alone.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any


KML_NS = "http://www.opengis.net/kml/2.2"
NS = {"k": KML_NS}
MASTER_KMZ_NAME = "506 Hot Spots AUH.kmz"
ID_FIELD = "م"
PRIORITY_FIELD = "الاولوية"
CENTER_FIELD = "المركز"
DESCRIPTION_FIELD = "الوصف"
EVIDENCE_CLASS = "customer_static_hotspot_prior"
SOURCE_VERSION = "FW__Hot_Spots_506.zip@2026-09-20"

CENTER_LABELS = {
    "الشهامة": "Shahamah",
    "مصفح": "Musaffah",
    "الوثبة": "Al Wathba",
    "المدينة": "Island / City",
    "مدينة زايد": "Zayed City / Mainland",
}


def _text(node: ET.Element | None) -> str:
    return (node.text or "").strip() if node is not None else ""


def _attributes(placemark: ET.Element) -> dict[str, str]:
    values: dict[str, str] = {}
    for node in placemark.findall(".//k:SimpleData", NS):
        name = node.attrib.get("name", "").strip()
        if name:
            values[name] = _text(node)
    for node in placemark.findall(".//k:Data", NS):
        name = node.attrib.get("name", "").strip()
        if name and name not in values:
            values[name] = _text(node.find("k:value", NS))
    return values


def _hotspot_id(value: Any) -> int | None:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if 1 <= number <= 506 else None


def _point_coordinates(placemark: ET.Element) -> list[float] | None:
    node = placemark.find(".//k:Point/k:coordinates", NS)
    if node is None:
        return None
    token = _text(node).split()[0] if _text(node) else ""
    parts = token.split(",")
    if len(parts) < 2:
        return None
    try:
        longitude = float(parts[0])
        latitude = float(parts[1])
    except ValueError:
        return None
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        return None
    return [longitude, latitude]


def build_feature_collection(source_zip: Path) -> dict[str, Any]:
    source_bytes = source_zip.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    with zipfile.ZipFile(io.BytesIO(source_bytes)) as outer:
        try:
            master_kmz = outer.read(MASTER_KMZ_NAME)
        except KeyError as error:
            raise ValueError(f"Missing {MASTER_KMZ_NAME} in {source_zip}") from error
    with zipfile.ZipFile(io.BytesIO(master_kmz)) as inner:
        kml_names = [name for name in inner.namelist() if name.lower().endswith(".kml")]
        if not kml_names:
            raise ValueError(f"No KML document found in {MASTER_KMZ_NAME}")
        root = ET.fromstring(inner.read(kml_names[0]))

    features: list[dict[str, Any]] = []
    for placemark in root.findall(".//k:Placemark", NS):
        attrs = _attributes(placemark)
        hotspot_id = _hotspot_id(attrs.get(ID_FIELD))
        if hotspot_id is None:
            continue
        coordinates = _point_coordinates(placemark)
        if coordinates is None:
            raise ValueError(f"Hotspot {hotspot_id} does not have point geometry")
        priority = attrs.get(PRIORITY_FIELD, "").strip()
        center_source = attrs.get(CENTER_FIELD, "").strip()
        description = attrs.get(DESCRIPTION_FIELD, "").strip()
        features.append(
            {
                "type": "Feature",
                "id": hotspot_id,
                "geometry": {"type": "Point", "coordinates": coordinates},
                "properties": {
                    "hotspot_id": hotspot_id,
                    "priority": priority,
                    "center": CENTER_LABELS.get(center_source, center_source),
                    "center_source_ar": center_source,
                    "description": description,
                    "source_version": SOURCE_VERSION,
                    "source_sha256": source_sha256,
                    "evidence_class": EVIDENCE_CLASS,
                    "event_linkage": "unavailable",
                },
            }
        )

    features.sort(key=lambda feature: int(feature["properties"]["hotspot_id"]))
    ids = [int(feature["properties"]["hotspot_id"]) for feature in features]
    if ids != list(range(1, 507)):
        raise ValueError("Official hotspot IDs must be unique and complete from 1 through 506")
    if len(features) != 506:
        raise ValueError(f"Expected 506 official hotspots, found {len(features)}")

    longitudes = [float(feature["geometry"]["coordinates"][0]) for feature in features]
    latitudes = [float(feature["geometry"]["coordinates"][1]) for feature in features]
    priority_counts = Counter(str(feature["properties"]["priority"]) for feature in features)
    center_counts = Counter(str(feature["properties"]["center"]) for feature in features)
    return {
        "type": "FeatureCollection",
        "name": "abu_dhabi_customer_hotspots_506",
        "bbox": [min(longitudes), min(latitudes), max(longitudes), max(latitudes)],
        "metadata": {
            "feature_count": 506,
            "geometry_type": "Point",
            "source_archive": source_zip.name,
            "source_member": MASTER_KMZ_NAME,
            "source_version": SOURCE_VERSION,
            "source_sha256": source_sha256,
            "evidence_class": EVIDENCE_CLASS,
            "event_linkage": "unavailable",
            "position_authority": "KML geometry coordinates",
            "priority_counts": dict(sorted(priority_counts.items())),
            "center_counts": dict(sorted(center_counts.items())),
            "excluded_auxiliary_features": {
                "booster_points": 4,
                "engineering_polygons": 28,
                "engineering_lines": 3,
            },
            "fitness_for_use": "Static customer-reported hotspot prior; not an event observation or measured flood depth.",
        },
        "features": features,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_zip", type=Path)
    parser.add_argument("output_geojson", type=Path)
    args = parser.parse_args()
    payload = build_feature_collection(args.source_zip)
    args.output_geojson.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output_geojson.with_suffix(args.output_geojson.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(args.output_geojson)
    print(json.dumps(payload["metadata"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
