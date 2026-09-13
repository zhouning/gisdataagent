#!/usr/bin/env python3
"""Download complete OSM bbox amenity and highway extracts for UWM."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

from data_agent.uwm.manifest import audit_uwm_manifest
from data_agent.uwm.osm_mobility_network import (
    build_mmfe_state_input_from_osm_mobility_network_proxy,
    write_osm_mobility_network_snapshot,
)
from data_agent.uwm.osm_overpass_queries import (
    build_osm_amenity_overpass_query,
    build_osm_highway_overpass_query,
)
from data_agent.uwm.osm_service_accessibility import (
    build_mmfe_state_input_from_osm_service_accessibility_proxy,
    write_osm_service_accessibility_snapshot,
)
from data_agent.uwm.renderer import build_canonical_observation_from_state_input


DEFAULT_BBOX = [29.52, 106.50, 29.60, 106.60]


def main() -> int:
    parser = argparse.ArgumentParser(description="Download OSM complete bbox proxy extracts for UWM.")
    parser.add_argument("--bbox", nargs=4, type=float, default=DEFAULT_BBOX, metavar=("LAT_MIN", "LON_MIN", "LAT_MAX", "LON_MAX"))
    parser.add_argument("--endpoint", default="https://overpass-api.de/api/interpreter")
    parser.add_argument("--output-dir", default="data/uwm_public_proxy/chongqing_central/osm_complete_bbox_2026_07_05")
    parser.add_argument("--manifest-path", default="docs/reports/uwm_data_foundation_manifest.csv")
    parser.add_argument("--http-timeout", type=int, default=240)
    parser.add_argument("--reuse-raw-if-present", action="store_true")
    args = parser.parse_args()

    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    output_dir = Path(args.output_dir)
    service_dir = output_dir / "service"
    mobility_dir = output_dir / "mobility"

    amenity_payload = _load_or_fetch(
        service_dir / "osm_services_overpass_geometry_raw.json",
        build_osm_amenity_overpass_query(args.bbox),
        endpoint=args.endpoint,
        timeout=args.http_timeout,
        reuse_raw_if_present=args.reuse_raw_if_present,
    )
    highway_payload = _load_or_fetch(
        mobility_dir / "osm_mobility_network_overpass_raw.json",
        build_osm_highway_overpass_query(args.bbox),
        endpoint=args.endpoint,
        timeout=args.http_timeout,
        reuse_raw_if_present=args.reuse_raw_if_present,
    )

    service_manifest = write_osm_service_accessibility_snapshot(
        output_dir=service_dir,
        raw_payload=amenity_payload,
        requested_bbox=args.bbox,
        fetched_at=fetched_at,
    )
    mobility_manifest = write_osm_mobility_network_snapshot(
        output_dir=mobility_dir,
        raw_payload=highway_payload,
        requested_bbox=args.bbox,
        fetched_at=fetched_at,
    )

    manifest_audit = audit_uwm_manifest(args.manifest_path)
    _write_service_state_outputs(service_dir, fetched_at, manifest_audit)
    _write_mobility_state_outputs(mobility_dir, fetched_at, manifest_audit)

    summary = {
        "output_dir": str(output_dir),
        "fetched_at": fetched_at,
        "bbox": args.bbox,
        "service": service_manifest,
        "mobility": mobility_manifest,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _fetch_overpass_json(endpoint: str, query: str, *, timeout: int) -> dict:
    response = requests.post(
        endpoint,
        data={"data": query},
        headers={"User-Agent": "gisdataagent-uwm-data-foundation/0.1"},
        timeout=(20, timeout),
    )
    response.raise_for_status()
    return response.json()


def _load_or_fetch(
    raw_path: Path,
    query: str,
    *,
    endpoint: str,
    timeout: int,
    reuse_raw_if_present: bool,
) -> dict:
    if reuse_raw_if_present and raw_path.exists():
        return _read_json(raw_path)
    return _fetch_overpass_json(endpoint, query, timeout=timeout)


def _write_service_state_outputs(output_dir: Path, fetched_at: str, manifest_audit: dict) -> None:
    proxy = _read_json(output_dir / "osm_service_accessibility_proxy.json")
    state_input = build_mmfe_state_input_from_osm_service_accessibility_proxy(proxy, timestamp=fetched_at)
    _write_json(output_dir / "mmfe_uwm_state_input_osm_service_accessibility.json", state_input)
    observation = build_canonical_observation_from_state_input(
        state_input,
        manifest_audit=manifest_audit,
        observation_id="uwm-observation-osm-complete-bbox-service",
        timestamp=fetched_at,
    )
    _write_json(output_dir / "uwm_canonical_observation_osm_service_accessibility.json", observation)


def _write_mobility_state_outputs(output_dir: Path, fetched_at: str, manifest_audit: dict) -> None:
    proxy = _read_json(output_dir / "osm_mobility_network_proxy.json")
    state_input = build_mmfe_state_input_from_osm_mobility_network_proxy(proxy, timestamp=fetched_at)
    _write_json(output_dir / "mmfe_uwm_state_input_osm_mobility_network.json", state_input)
    observation = build_canonical_observation_from_state_input(
        state_input,
        manifest_audit=manifest_audit,
        observation_id="uwm-observation-osm-complete-bbox-mobility",
        timestamp=fetched_at,
    )
    _write_json(output_dir / "uwm_canonical_observation_osm_mobility_network.json", observation)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
