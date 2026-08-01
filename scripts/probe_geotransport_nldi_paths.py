#!/usr/bin/env python3
"""Build action-to-gauge NLDI path evidence for GeoTransport v0.1."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from data_agent.uwm.geospatial_kernel_v2.public_data import (
    DEFAULT_REGISTRY_PATH,
    load_public_data_registry,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METADATA_ROOT = REPO_ROOT / "data/geotransport_v0_1/metadata"
DEFAULT_METADATA_MANIFEST = REPO_ROOT / "data/geotransport_v0_1/metadata_manifest.json"
DEFAULT_RAW_ROOT = REPO_ROOT / "data/geotransport_v0_1/topology/raw"
DEFAULT_OUTPUT = REPO_ROOT / "benchmarks/geotransport_v0_1/nldi_path_crosswalk_report.json"
NLDI_ROOT = "https://api.water.usgs.gov/nldi/linked-data"
SCHEMA = "gwm.geotransport.nldi_path_crosswalk.v1"
USER_AGENT = "gisdataagent-geotransport-nldi-path/0.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--metadata-root", type=Path, default=DEFAULT_METADATA_ROOT)
    parser.add_argument(
        "--metadata-manifest", type=Path, default=DEFAULT_METADATA_MANIFEST
    )
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--maximum-distance-km", type=float, default=500.0)
    parser.add_argument("--maximum-snap-distance-km", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--retries", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    registry = load_public_data_registry(args.registry)
    metadata_manifest = _load_json(args.metadata_manifest)
    if metadata_manifest.get("registry_sha256") != registry.sha256:
        raise ValueError("metadata_manifest_registry_hash_mismatch")
    if metadata_manifest.get("claim_boundary", {}).get("time_series_acquired") is not False:
        raise ValueError("metadata_only_manifest_required")
    opener = _opener(args.proxy)
    args.raw_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for system in registry.systems():
        if not system["track"].startswith("GeoTransport"):
            continue
        action_point, action_evidence = load_action_point(
            system, metadata_root=args.metadata_root
        )
        gauge_feature, gauge_evidence = load_gauge_feature(
            system, metadata_root=args.metadata_root
        )
        action_position_url = (
            f"{NLDI_ROOT}/comid/position?"
            + urllib.parse.urlencode(
                {"coords": f"POINT({action_point[0]} {action_point[1]})"}
            )
        )
        position, position_evidence = fetch_json(
            action_position_url,
            opener=opener,
            output=args.raw_root / f"{system['system_id']}-action-position.json",
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
        )
        action_feature = _single_feature(position, "action_position")
        action_comid = _comid(action_feature)
        navigation_url = (
            f"{NLDI_ROOT}/comid/{action_comid}/navigation/DM/flowlines?"
            + urllib.parse.urlencode({"distance": args.maximum_distance_km})
        )
        navigation, navigation_evidence = fetch_json(
            navigation_url,
            opener=opener,
            output=args.raw_root / f"{system['system_id']}-downstream-flowlines.json",
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
        )
        path = summarize_path(
            navigation,
            action_comid=action_comid,
            gauge_comid=_comid(gauge_feature),
        )
        snap_distance = nearest_vertex_distance_km(
            action_point, action_feature.get("geometry")
        )
        snap_gate = (
            "pass"
            if snap_distance is not None
            and snap_distance <= args.maximum_snap_distance_km
            else "fail"
        )
        path_gate = "pass" if path["gauge_reachable"] else "fail"
        overall = "pass" if snap_gate == path_gate == "pass" else "fail"
        rows.append(
            {
                "system_id": system["system_id"],
                "track": system["track"],
                "action_point": {
                    "longitude": action_point[0],
                    "latitude": action_point[1],
                    "evidence": action_evidence,
                },
                "action_comid": action_comid,
                "action_snap_distance_km_vertex_approximation": (
                    round(snap_distance, 6) if snap_distance is not None else None
                ),
                "gauge_site_id": system["outcome"]["site_id"],
                "gauge_comid": _comid(gauge_feature),
                "gauge_evidence": gauge_evidence,
                "path": path,
                "gate_statuses": {
                    "action_snap_within_threshold": snap_gate,
                    "gauge_downstream_reachable": path_gate,
                },
                "topology_gate_status": overall,
                "source_requests": {
                    "action_position": position_evidence,
                    "downstream_navigation": navigation_evidence,
                },
                "claim_boundary": {
                    "full_reach_boundary_approximation": True,
                    "intervening_control_screening_inherited_from_registry": True,
                    "nwm_feature_id_membership_verified": False,
                    "forcing_feature_ids_admitted": False,
                },
            }
        )
    all_pass = all(row["topology_gate_status"] == "pass" for row in rows)
    report = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "registry_path": _display(args.registry),
        "registry_sha256": registry.sha256,
        "metadata_manifest_path": _display(args.metadata_manifest),
        "metadata_manifest_sha256": _sha256_file(args.metadata_manifest),
        "maximum_navigation_distance_km": args.maximum_distance_km,
        "maximum_action_snap_distance_km": args.maximum_snap_distance_km,
        "systems": rows,
        "topology_gate_status": "pass" if all_pass else "fail",
        "claim_boundary": {
            "topology_paths_verified": all_pass,
            "nwm_feature_id_membership_verified": False,
            "forcing_feature_ids_admitted": False,
            "time_series_acquired": False,
            "benchmark_validated": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    return 0 if all_pass else 2


def load_action_point(
    system: dict[str, Any], *, metadata_root: Path
) -> tuple[tuple[float, float], dict[str, object]]:
    action = system["action"]
    if action["source"] == "usace_cwms":
        name = f"cwms-location-{_safe_id(action['location_id'])}.json"
        path = metadata_root / name
        payload = _load_json(path)
        if payload.get("name") != action["location_id"]:
            raise ValueError(f"cwms_action_location_mismatch:{system['system_id']}")
        point = (float(payload["longitude"]), float(payload["latitude"]))
    elif action["source"] == "usbr_rise":
        path = metadata_root / f"rise-catalog-item-{action['item_id']}.json"
        payload = _load_json(path)
        if payload.get("id") != action["item_id"]:
            raise ValueError(f"rise_action_item_mismatch:{system['system_id']}")
        spatial = payload.get("dcat:spatial") or {}
        if spatial.get("type") != "Point" or len(spatial.get("coordinates", [])) != 2:
            raise ValueError(f"rise_action_point_missing:{system['system_id']}")
        point = tuple(float(value) for value in spatial["coordinates"])
    else:
        raise ValueError("unsupported_action_location_source")
    return point, {
        "path": _display(path),
        "sha256": _sha256_file(path),
        "source": action["source"],
    }


def load_gauge_feature(
    system: dict[str, Any], *, metadata_root: Path
) -> tuple[dict[str, Any], dict[str, object]]:
    site_id = system["outcome"]["site_id"]
    path = metadata_root / f"nldi-link-{site_id}.json"
    payload = _load_json(path)
    feature = _single_feature(payload, "gauge_link")
    if feature.get("id") != f"USGS-{site_id}":
        raise ValueError(f"nldi_gauge_identity_mismatch:{site_id}")
    return feature, {
        "path": _display(path),
        "sha256": _sha256_file(path),
        "source": "usgs_nldi",
    }


def summarize_path(
    feature_collection: dict[str, Any],
    *,
    action_comid: int,
    gauge_comid: int,
) -> dict[str, object]:
    features = feature_collection.get("features") or []
    comids = [_comid(feature) for feature in features]
    if not comids or comids[0] != action_comid:
        raise ValueError("downstream_path_does_not_start_at_action")
    if len(comids) != len(set(comids)):
        raise ValueError("downstream_path_contains_duplicate_comids")
    reachable = gauge_comid in comids
    target_index = comids.index(gauge_comid) if reachable else None
    included = features[: target_index + 1] if target_index is not None else []
    return {
        "gauge_reachable": reachable,
        "gauge_feature_index": target_index,
        "returned_feature_count": len(features),
        "path_feature_count": len(included),
        "feature_ids": [_comid(feature) for feature in included],
        "full_reach_path_length_km": (
            round(sum(geometry_length_km(feature.get("geometry")) for feature in included), 6)
            if included
            else None
        ),
    }


def fetch_json(
    url: str,
    *,
    opener: urllib.request.OpenerDirector,
    output: Path,
    timeout_seconds: float,
    retries: int,
) -> tuple[dict[str, Any], dict[str, object]]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "api.water.usgs.gov":
        raise ValueError("nldi_url_outside_allowlist")
    error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/geo+json", "User-Agent": USER_AGENT},
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                body = response.read(25_000_001)
                if len(body) > 25_000_000:
                    raise ValueError("nldi_response_size_limit_exceeded")
                payload = json.loads(body)
                if payload.get("type") != "FeatureCollection":
                    raise ValueError("nldi_feature_collection_required")
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(body)
                return payload, {
                    "url": url,
                    "http_status": response.status,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "path": _display(output),
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "size_bytes": len(body),
                    "attempt_count": attempt,
                }
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            error = exc
            if attempt < retries:
                time.sleep(float(attempt))
    raise RuntimeError(f"nldi_request_failed:{url}:{error}")


def nearest_vertex_distance_km(
    point: tuple[float, float], geometry: dict[str, Any] | None
) -> float | None:
    if not geometry or geometry.get("type") != "LineString":
        return None
    coordinates = geometry.get("coordinates") or []
    if not coordinates:
        return None
    return min(haversine_km(point, tuple(vertex)) for vertex in coordinates)


def geometry_length_km(geometry: dict[str, Any] | None) -> float:
    if not geometry or geometry.get("type") != "LineString":
        return 0.0
    coordinates = geometry.get("coordinates") or []
    return sum(
        haversine_km(tuple(first), tuple(second))
        for first, second in zip(coordinates, coordinates[1:])
    )


def haversine_km(first: tuple[float, float], second: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, first)
    lon2, lat2 = map(math.radians, second)
    delta_lon = lon2 - lon1
    delta_lat = lat2 - lat1
    value = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2.0) ** 2
    )
    return 6371.0088 * 2.0 * math.asin(min(1.0, math.sqrt(value)))


def _single_feature(payload: dict[str, Any], name: str) -> dict[str, Any]:
    features = payload.get("features") or []
    if len(features) != 1:
        raise ValueError(f"{name}_must_have_exactly_one_feature")
    return features[0]


def _comid(feature: dict[str, Any]) -> int:
    properties = feature.get("properties") or {}
    value = properties.get("nhdplus_comid", properties.get("comid", feature.get("id")))
    if value is None:
        raise ValueError("feature_comid_missing")
    return int(value)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _safe_id(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value).strip("-")


def _opener(proxy: str) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(*handlers)


if __name__ == "__main__":
    raise SystemExit(main())
