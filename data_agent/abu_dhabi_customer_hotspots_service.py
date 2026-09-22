"""Validated read-only delivery for the Abu Dhabi customer hotspot layer."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any


ARTIFACT_ENV = "ABU_DHABI_CUSTOMER_HOTSPOTS_GEOJSON"
DEFAULT_ARTIFACT = Path(__file__).resolve().parent / "uploads" / "admin" / "abu_dhabi_customer_hotspots_506.geojson"
EXPECTED_FEATURE_COUNT = 506
EXPECTED_EVIDENCE_CLASS = "customer_static_hotspot_prior"


def _artifact_path(override: str | Path | None = None) -> Path:
    if override is not None:
        return Path(override).expanduser().resolve()
    configured = os.environ.get(ARTIFACT_ENV, "").strip()
    return Path(configured).expanduser().resolve() if configured else DEFAULT_ARTIFACT


def customer_hotspots_bootstrap_payload(artifact_path: str | Path | None = None) -> dict[str, Any]:
    path = _artifact_path(artifact_path)
    if not path.is_file():
        raise FileNotFoundError(f"Customer hotspot derivative not found: {path.name}")
    try:
        source = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Customer hotspot derivative is not valid UTF-8 GeoJSON") from error

    features = source.get("features")
    if source.get("type") != "FeatureCollection" or not isinstance(features, list):
        raise ValueError("Customer hotspot derivative must be a GeoJSON FeatureCollection")
    if len(features) != EXPECTED_FEATURE_COUNT:
        raise ValueError(f"Customer hotspot derivative must contain exactly {EXPECTED_FEATURE_COUNT} features")

    ids: list[int] = []
    priorities: Counter[str] = Counter()
    centers: Counter[str] = Counter()
    for feature in features:
        if feature.get("geometry", {}).get("type") != "Point":
            raise ValueError("Customer hotspot derivative may contain Point geometry only")
        coordinates = feature.get("geometry", {}).get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            raise ValueError("Customer hotspot derivative contains an invalid point coordinate")
        properties = feature.get("properties") or {}
        try:
            hotspot_id = int(properties.get("hotspot_id"))
        except (TypeError, ValueError) as error:
            raise ValueError("Customer hotspot derivative contains an invalid hotspot_id") from error
        ids.append(hotspot_id)
        if properties.get("evidence_class") != EXPECTED_EVIDENCE_CLASS:
            raise ValueError("Customer hotspot evidence class is invalid")
        if properties.get("event_linkage") != "unavailable":
            raise ValueError("Customer hotspot event linkage must remain unavailable")
        priorities[str(properties.get("priority") or "Unspecified")] += 1
        centers[str(properties.get("center") or "Unspecified")] += 1

    if sorted(ids) != list(range(1, EXPECTED_FEATURE_COUNT + 1)) or len(set(ids)) != EXPECTED_FEATURE_COUNT:
        raise ValueError("Customer hotspot IDs must be unique and complete from 1 through 506")

    source_metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    source_sha256 = str(source_metadata.get("source_sha256") or features[0]["properties"].get("source_sha256") or "")
    if len(source_sha256) != 64 or any(character not in "0123456789abcdef" for character in source_sha256.lower()):
        raise ValueError("Customer hotspot source SHA-256 is missing or invalid")

    geojson = {
        "type": "FeatureCollection",
        "name": str(source.get("name") or "abu_dhabi_customer_hotspots_506"),
        "bbox": source.get("bbox"),
        "features": features,
    }
    return {
        "metadata": {
            **source_metadata,
            "feature_count": EXPECTED_FEATURE_COUNT,
            "id_range": [1, EXPECTED_FEATURE_COUNT],
            "unique_id_count": EXPECTED_FEATURE_COUNT,
            "geometry_type": "Point",
            "priority_counts": dict(sorted(priorities.items())),
            "center_counts": dict(sorted(centers.items())),
            "source_sha256": source_sha256,
            "evidence_class": EXPECTED_EVIDENCE_CLASS,
            "event_linkage": "unavailable",
            "validation_status": "validated_for_static_map_reference",
        },
        "geojson": geojson,
    }
