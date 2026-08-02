#!/usr/bin/env python3
"""Fetch and provenance-lock the Abu Dhabi city OSM relation boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = HERE / "source/abu_dhabi_city_osm_r4479763.geojson"
DEFAULT_MANIFEST = HERE / "boundary_manifest.json"
SOURCE_URL = (
    "https://nominatim.openstreetmap.org/lookup"
    "?osm_ids=R4479763&format=geojson&polygon_geojson=1"
)
USER_AGENT = "gisdataagent-abu-dhabi-benchmark/1.0 (research boundary acquisition)"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_boundary(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("type") != "FeatureCollection":
        raise ValueError("nominatim_response_is_not_feature_collection")
    features = payload.get("features") or []
    if len(features) != 1:
        raise ValueError(f"expected_one_boundary_feature:{len(features)}")
    feature = features[0]
    properties = feature.get("properties") or {}
    osm_id = int(properties.get("osm_id", 0))
    osm_type = str(properties.get("osm_type", "")).lower()
    if osm_id != 4479763 or osm_type not in {"relation", "r"}:
        raise ValueError(f"unexpected_osm_object:{osm_type}:{osm_id}")
    geometry_type = str((feature.get("geometry") or {}).get("type"))
    if geometry_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError(f"unexpected_boundary_geometry:{geometry_type}")
    return feature


def fetch_boundary(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    manifest_path: Path = DEFAULT_MANIFEST,
    proxy: str | None = None,
) -> dict[str, Any]:
    proxies = {"http": proxy, "https": proxy} if proxy else None
    response = requests.get(
        SOURCE_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json"},
        proxies=proxies,
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    feature = validate_boundary(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    properties = feature["properties"]
    manifest = {
        "schema": "gwm.boundary_source_manifest.v1",
        "benchmark_id": "abu-dhabi-land-use-v1",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "source_url": SOURCE_URL,
        "provider": "OpenStreetMap via Nominatim",
        "licence": "OpenStreetMap contributors, ODbL 1.0",
        "osm_type": properties.get("osm_type"),
        "osm_id": int(properties["osm_id"]),
        "display_name": properties.get("display_name"),
        "geometry_type": feature["geometry"]["type"],
        "bbox_wgs84": [float(value) for value in feature.get("bbox") or []],
        "artifact": {
            "path": str(output_path.relative_to(HERE)),
            "size_bytes": output_path.stat().st_size,
            "sha256": sha256_file(output_path),
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--proxy", default="")
    args = parser.parse_args()
    manifest = fetch_boundary(
        output_path=args.output,
        manifest_path=args.manifest,
        proxy=args.proxy or None,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
