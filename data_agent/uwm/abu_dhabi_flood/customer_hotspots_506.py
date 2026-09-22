"""Ingest and serve the customer's latest 506 Abu Dhabi flood critical points.

The source delivery is an outer ZIP containing a KMZ.  Only placemarks with
the six declared business fields are admitted; decorative KML points, lines,
and polygons remain outside the published map layer.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from zipfile import ZipFile


SCHEMA_VERSION = "gisdataagent.abu_dhabi.customer_flood_critical_points.v1"
DEFAULT_BUNDLE_ROOT = (
    Path.home()
    / ".local/share/gisdataagent/private/abu_dhabi_stormwater/customer_hotspots_506_20260920"
)
KML_NAMESPACE = {"k": "http://www.opengis.net/kml/2.2"}
REQUIRED_FIELDS = ("الاولوية", "LATIDUE", "LONGITUDE", "الوصف", "المركز", "م")
PRIORITY_RANK = {"Important": 1, "Very Important": 2}
SERVICE_CENTER_EN = {
    "الشهامة": "Al Shahama",
    "مصفح": "Musaffah",
    "الوثبة": "Al Wathba",
    "المدينة": "Abu Dhabi City",
    "مدينة زايد": "Zayed City",
}


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u200f", " ").replace("\u200e", " ").split())


def _json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _json_read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("abu_dhabi_hotspot_506_bundle_not_available")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("abu_dhabi_hotspot_506_bundle_invalid")
    return payload

def _source_kml(source_zip: Path) -> tuple[str, bytes]:
    with ZipFile(source_zip) as delivery:
        candidates = [
            name
            for name in delivery.namelist()
            if name.lower().endswith(".kmz") and "506" in Path(name).name
        ]
        if len(candidates) != 1:
            raise ValueError("abu_dhabi_hotspot_506_kmz_not_unique")
        kmz_name = candidates[0]
        with ZipFile(BytesIO(delivery.read(kmz_name))) as kmz:
            kml_candidates = [name for name in kmz.namelist() if name.lower().endswith(".kml")]
            if "doc.kml" in kml_candidates:
                kml_name = "doc.kml"
            elif len(kml_candidates) == 1:
                kml_name = kml_candidates[0]
            else:
                raise ValueError("abu_dhabi_hotspot_506_kml_not_unique")
            return kmz_name, kmz.read(kml_name)


def _point_coordinates(placemark: ElementTree.Element) -> tuple[float, float]:
    coordinate = placemark.find("k:Point/k:coordinates", KML_NAMESPACE)
    raw = _clean_text(coordinate.text if coordinate is not None else "")
    if not raw:
        raise ValueError("abu_dhabi_hotspot_506_point_missing")
    values = raw.split()[0].split(",")
    if len(values) < 2:
        raise ValueError("abu_dhabi_hotspot_506_point_invalid")
    longitude, latitude = float(values[0]), float(values[1])
    if not (51.0 <= longitude <= 57.0 and 22.0 <= latitude <= 27.0):
        raise ValueError("abu_dhabi_hotspot_506_coordinate_outside_uae")
    return longitude, latitude


def _parse_hotspots(kml_bytes: bytes, *, expected_count: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root = ElementTree.fromstring(kml_bytes)
    placemarks = root.findall(".//k:Placemark", KML_NAMESPACE)
    geometry_counts: Counter[str] = Counter()
    priority_counts: Counter[str] = Counter()
    center_counts: Counter[str] = Counter()
    features: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    coordinate_attribute_delta_max = 0.0

    for placemark in placemarks:
        geometry_type = next(
            (
                geometry
                for geometry in ("Point", "LineString", "Polygon", "MultiGeometry")
                if placemark.find(f"k:{geometry}", KML_NAMESPACE) is not None
            ),
            "Unknown",
        )
        geometry_counts[geometry_type] += 1
        values = {
            item.attrib.get("name", ""): _clean_text(item.text)
            for item in placemark.findall(".//k:SimpleData", KML_NAMESPACE)
        }
        if not all(values.get(field) for field in REQUIRED_FIELDS):
            continue
        if geometry_type != "Point":
            raise ValueError("abu_dhabi_hotspot_506_business_record_not_point")

        hotspot_id = _clean_text(values["م"])
        if hotspot_id in seen_ids:
            raise ValueError("abu_dhabi_hotspot_506_duplicate_id")
        seen_ids.add(hotspot_id)
        longitude, latitude = _point_coordinates(placemark)
        attribute_latitude = float(values["LATIDUE"])
        attribute_longitude = float(values["LONGITUDE"])
        coordinate_attribute_delta_max = max(
            coordinate_attribute_delta_max,
            abs(latitude - attribute_latitude),
            abs(longitude - attribute_longitude),
        )
        priority = _clean_text(values["الاولوية"])
        if priority not in PRIORITY_RANK:
            raise ValueError("abu_dhabi_hotspot_506_priority_invalid")
        service_center_ar = _clean_text(values["المركز"])
        priority_counts[priority] += 1
        center_counts[service_center_ar] += 1
        feature_name = _clean_text(placemark.findtext("k:name", default="", namespaces=KML_NAMESPACE))
        features.append(
            {
                "type": "Feature",
                "id": f"customer-hotspot-506-{hotspot_id}",
                "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                "properties": {
                    "hotspot_id": hotspot_id,
                    "priority": priority,
                    "priority_rank": PRIORITY_RANK[priority],
                    "description_ar": _clean_text(values["الوصف"]),
                    "service_center_ar": service_center_ar,
                    "service_center_en": SERVICE_CENTER_EN.get(service_center_ar, service_center_ar),
                    "latitude": latitude,
                    "longitude": longitude,
                    "source_record_name": feature_name,
                    "inventory_kind": "customer_latest_flood_critical_points",
                    "inventory_version": "2026-09-20-customer-506",
                },
            }
        )

    if len(features) != expected_count:
        raise ValueError(
            f"abu_dhabi_hotspot_506_count_mismatch:expected={expected_count}:actual={len(features)}"
        )
    features.sort(key=lambda feature: int(feature["properties"]["hotspot_id"]))
    longitudes = [float(feature["geometry"]["coordinates"][0]) for feature in features]
    latitudes = [float(feature["geometry"]["coordinates"][1]) for feature in features]
    receipt = {
        "placemark_count": len(placemarks),
        "admitted_hotspot_count": len(features),
        "ignored_auxiliary_placemark_count": len(placemarks) - len(features),
        "geometry_counts": dict(sorted(geometry_counts.items())),
        "priority_counts": dict(sorted(priority_counts.items())),
        "service_center_counts": dict(sorted(center_counts.items())),
        "unique_hotspot_id_count": len(seen_ids),
        "coordinate_attribute_max_delta_degrees": coordinate_attribute_delta_max,
        "bbox_wgs84": [min(longitudes), min(latitudes), max(longitudes), max(latitudes)],
        "crs": "EPSG:4326",
    }
    return features, receipt


def build_private_bundle(
    source_zip: Path,
    output_root: Path = DEFAULT_BUNDLE_ROOT,
    *,
    expected_count: int = 506,
) -> dict[str, Any]:
    source_zip = source_zip.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    if not source_zip.is_file():
        raise FileNotFoundError(source_zip)
    source_bytes = source_zip.read_bytes()
    kmz_name, kml_bytes = _source_kml(source_zip)
    features, quality = _parse_hotspots(kml_bytes, expected_count=expected_count)
    geojson = {
        "type": "FeatureCollection",
        "name": "customer_latest_abu_dhabi_flood_critical_points_506",
        "metadata": {
            "schema": SCHEMA_VERSION,
            "title_zh": "客户最新城市积水关键点",
            "title_en": "Customer latest urban-flood critical points",
            "record_count": len(features),
            "inventory_version": "2026-09-20-customer-506",
            "source_delivery": source_zip.name,
            "source_member": kmz_name,
            "crs": "EPSG:4326",
        },
        "features": features,
    }
    manifest = {
        "schema": f"{SCHEMA_VERSION}.manifest",
        "status": "ready",
        "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": {
            "filename": source_zip.name,
            "size_bytes": len(source_bytes),
            "sha256": sha256(source_bytes).hexdigest(),
            "selected_member": kmz_name,
        },
        "inventory": {
            "record_count": len(features),
            "priority_counts": quality["priority_counts"],
            "service_center_counts": quality["service_center_counts"],
        },
        "quality": quality,
        "claim_boundary": (
            "Customer-provided static flood critical-point inventory. Points are map evidence and "
            "are not event-specific observations, measured depths, or hydraulic model outputs."
        ),
    }
    _json_write(output_root / "hotspots_latest_506.geojson", geojson)
    _json_write(output_root / "manifest.json", manifest)
    return manifest


def configured_bundle_root() -> Path:
    value = os.environ.get("ABU_DHABI_HOTSPOT_506_BUNDLE_ROOT", "").strip()
    return Path(value).expanduser().resolve() if value else DEFAULT_BUNDLE_ROOT.resolve()


def latest_hotspot_catalog_payload() -> dict[str, Any]:
    return _json_read(configured_bundle_root() / "manifest.json")


def latest_hotspot_geojson_payload() -> dict[str, Any]:
    payload = _json_read(configured_bundle_root() / "hotspots_latest_506.geojson")
    if payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
        raise ValueError("abu_dhabi_hotspot_506_bundle_invalid")
    return payload
