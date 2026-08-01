#!/usr/bin/env python3
"""Acquire bounded public spatial-boundary evidence around COMID 18421703."""

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


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/stage27_center_hill_spatial_boundary_evidence"
)
SCHEMA = "gwm.geotransport.stage27_spatial_boundary_acquisition.v1"
USER_AGENT = "gisdataagent-stage27-spatial-boundary-evidence/0.1"
ROOT_COMID = 18421703
ANCHOR_SITE_ID = "USGS-03424860"
MAXIMUM_CANDIDATE_COUNT = 12
MAXIMUM_MATCH_WINDOW_COUNT = 4
MATCH_WINDOW_HALF_WIDTH_SECONDS = 3600
MAXIMUM_MATCH_WINDOW_BYTES = 400_000
MAXIMUM_TOTAL_DOWNLOAD_BYTES = 34_000_000
FOLLOW_UP_MAXIMUM_BYTES = {
    "monitoring_location": 100_000,
    "time_series_metadata": 400_000,
    "field_measurements": 2_000_000,
}
LICENSE = "USGS public-domain data"
LICENSE_URL = (
    "https://www.usgs.gov/information-policies-and-instructions/"
    "copyrights-and-credits"
)

NLDI_BASE = (
    "https://api.water.usgs.gov/nldi/linked-data/comid/"
    f"{ROOT_COMID}/navigation"
)
WATERDATA_BASE = "https://api.waterdata.usgs.gov/ogcapi/v0/collections"
NAVIGATION_REQUESTS = (
    {
        "source_id": "nldi_upstream_tributary_sites_10km",
        "direction": "upstream_tributaries",
        "navigation_code": "UT",
        "distance_km": 10.0,
        "url": f"{NLDI_BASE}/UT/nwissite?distance=10",
        "output_name": "raw/nldi_upstream_tributary_sites_10km.json",
        "maximum_bytes": 250_000,
    },
    {
        "source_id": "nldi_upstream_main_sites_50km",
        "direction": "upstream_main",
        "navigation_code": "UM",
        "distance_km": 50.0,
        "url": f"{NLDI_BASE}/UM/nwissite?distance=50",
        "output_name": "raw/nldi_upstream_main_sites_50km.json",
        "maximum_bytes": 250_000,
    },
    {
        "source_id": "nldi_downstream_main_sites_50km",
        "direction": "downstream_main",
        "navigation_code": "DM",
        "distance_km": 50.0,
        "url": f"{NLDI_BASE}/DM/nwissite?distance=50",
        "output_name": "raw/nldi_downstream_main_sites_50km.json",
        "maximum_bytes": 250_000,
    },
)
ALLOWED_HOSTS = frozenset(
    {"api.water.usgs.gov", "api.waterdata.usgs.gov"}
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=5)
    return parser.parse_args()


def compile_plan(*, values_mode: bool = False) -> dict[str, Any]:
    navigation_maximum = sum(
        int(value["maximum_bytes"]) for value in NAVIGATION_REQUESTS
    )
    follow_up_per_candidate = sum(FOLLOW_UP_MAXIMUM_BYTES.values())
    planned_maximum = (
        navigation_maximum
        + MAXIMUM_CANDIDATE_COUNT * follow_up_per_candidate
        + MAXIMUM_MATCH_WINDOW_COUNT * MAXIMUM_MATCH_WINDOW_BYTES
    )
    if planned_maximum > MAXIMUM_TOTAL_DOWNLOAD_BYTES:
        raise ValueError("stage27_spatial_boundary_request_boundary_exceeded")
    return {
        "schema": SCHEMA,
        "mode": "values" if values_mode else "plan",
        "purpose": (
            "discover hydrologically linked public observation sites and "
            "test whether a spatially distinct discharge or stage boundary "
            "overlaps the Center Hill anchor in time"
        ),
        "target": {
            "root_comid": ROOT_COMID,
            "anchor_monitoring_location_id": ANCHOR_SITE_ID,
        },
        "request_boundary": {
            "allowed_hosts": sorted(ALLOWED_HOSTS),
            "navigation_request_count": len(NAVIGATION_REQUESTS),
            "maximum_candidate_count": MAXIMUM_CANDIDATE_COUNT,
            "maximum_match_window_count": MAXIMUM_MATCH_WINDOW_COUNT,
            "match_window_half_width_seconds": (
                MATCH_WINDOW_HALF_WIDTH_SECONDS
            ),
            "follow_up_requests_per_candidate": 3,
            "maximum_request_count": (
                len(NAVIGATION_REQUESTS)
                + 3 * MAXIMUM_CANDIDATE_COUNT
                + MAXIMUM_MATCH_WINDOW_COUNT
            ),
            "maximum_total_download_bytes": (
                MAXIMUM_TOTAL_DOWNLOAD_BYTES
            ),
            "planned_maximum_bytes": planned_maximum,
            "item_limit": 10_000,
            "workspace_or_private_data_sent": False,
        },
        "navigation_requests": [dict(value) for value in NAVIGATION_REQUESTS],
        "candidate_follow_up": {
            "selection": "union_of_returned_nldi_site_identifiers",
            "collections": [
                "monitoring-locations",
                "time-series-metadata",
                "field-measurements",
            ],
            "maximum_bytes_per_collection": dict(
                FOLLOW_UP_MAXIMUM_BYTES
            ),
            "license": LICENSE,
            "license_url": LICENSE_URL,
        },
        "claim_boundary": {
            "source_values_acquired": values_mode,
            "candidate_site_must_be_nldi_discovered": True,
            "time_series_extent_is_not_a_spatial_observation": True,
            "successive_anchor_records_may_replace_spatial_neighbor": False,
            "spatial_boundary_pair_admitted": False,
            "observed_spatial_rollout_completed": False,
            "operator_admitted": False,
        },
    }


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("stage27_spatial_boundary_request_limits_invalid")
    output = args.output.resolve()
    data_root = (REPO_ROOT / "data/geotransport_v0_1").resolve()
    if output != data_root and data_root not in output.parents:
        raise ValueError("stage27_spatial_boundary_output_outside_data_root")
    output.mkdir(parents=True, exist_ok=True)
    plan = compile_plan(values_mode=not args.plan_only)
    if args.plan_only:
        path = output / "acquisition_plan.json"
        _write_json(path, plan)
        print(path)
        return 0

    opener = _opener(args.proxy)
    artifacts: list[dict[str, Any]] = []
    navigation_bodies: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    for source in NAVIGATION_REQUESTS:
        body, retrieval = _fetch(
            str(source["url"]),
            opener=opener,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            maximum_bytes=int(source["maximum_bytes"]),
        )
        value = _validate_navigation_body(body)
        navigation_bodies[str(source["source_id"])] = value
        total_bytes = _checked_total(total_bytes, len(body))
        path = output / str(source["output_name"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        artifacts.append(
            _artifact_record(
                path,
                source=source,
                retrieval=retrieval,
                role="nldi_topology_candidate_discovery",
            )
        )

    candidates = _discover_candidates(navigation_bodies)
    follow_up_bodies: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate in candidates:
        site_id = str(candidate["monitoring_location_id"])
        site_number = site_id.removeprefix("USGS-")
        requests = _candidate_requests(site_id, site_number)
        for source in requests:
            body, retrieval = _fetch(
                str(source["url"]),
                opener=opener,
                timeout_seconds=args.timeout_seconds,
                retries=args.retries,
                maximum_bytes=int(source["maximum_bytes"]),
            )
            _validate_follow_up_body(
                str(source["collection"]), site_id, body
            )
            follow_up_bodies[(site_id, str(source["collection"]))] = (
                json.loads(body)
            )
            total_bytes = _checked_total(total_bytes, len(body))
            path = output / str(source["output_name"])
            path.write_bytes(body)
            artifacts.append(
                _artifact_record(
                    path,
                    source=source,
                    retrieval=retrieval,
                    role=str(source["role"]),
                )
            )

    match_windows = _compile_match_window_requests(
        candidates, follow_up_bodies
    )
    for source in match_windows:
        body, retrieval = _fetch(
            str(source["url"]),
            opener=opener,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            maximum_bytes=int(source["maximum_bytes"]),
        )
        _validate_continuous_body(
            ANCHOR_SITE_ID, str(source["parameter_code"]), body
        )
        total_bytes = _checked_total(total_bytes, len(body))
        path = output / str(source["output_name"])
        path.write_bytes(body)
        artifacts.append(
            _artifact_record(
                path,
                source=source,
                retrieval=retrieval,
                role="anchor_continuous_values_bracketing_candidate_field_time",
            )
        )

    manifest = {
        **plan,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "candidates": candidates,
        "candidate_count": len(candidates),
        "match_windows": match_windows,
        "match_window_count": len(match_windows),
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "actual_request_count": len(artifacts),
        "total_downloaded_bytes": total_bytes,
    }
    path = output / "acquisition_manifest.json"
    _write_json(path, manifest)
    print(path)
    print(f"candidates={len(candidates)}")
    print(f"requests={len(artifacts)}")
    print(f"match_windows={len(match_windows)}")
    print(f"downloaded_bytes={total_bytes}")
    return 0


def _candidate_requests(
    site_id: str, site_number: str
) -> tuple[dict[str, Any], ...]:
    encoded = urllib.parse.quote(site_id, safe="-")
    return (
        {
            "source_id": f"usgs_monitoring_location_{site_number}",
            "collection": "monitoring-locations",
            "url": (
                f"{WATERDATA_BASE}/monitoring-locations/items/"
                f"{encoded}?f=json"
            ),
            "output_name": f"raw/monitoring_location_{site_number}.json",
            "maximum_bytes": FOLLOW_UP_MAXIMUM_BYTES["monitoring_location"],
            "role": "site_identity_coordinates_and_support_metadata",
        },
        {
            "source_id": f"usgs_time_series_metadata_{site_number}",
            "collection": "time-series-metadata",
            "url": (
                f"{WATERDATA_BASE}/time-series-metadata/items?f=json"
                f"&limit=10000&monitoring_location_id={encoded}"
            ),
            "output_name": (
                f"raw/time_series_metadata_{site_number}.json"
            ),
            "maximum_bytes": FOLLOW_UP_MAXIMUM_BYTES[
                "time_series_metadata"
            ],
            "role": "parameter_units_and_temporal_support_catalog",
        },
        {
            "source_id": f"usgs_field_measurements_{site_number}",
            "collection": "field-measurements",
            "url": (
                f"{WATERDATA_BASE}/field-measurements/items?f=json"
                f"&limit=10000&monitoring_location_id={encoded}"
            ),
            "output_name": f"raw/field_measurements_{site_number}.json",
            "maximum_bytes": FOLLOW_UP_MAXIMUM_BYTES["field_measurements"],
            "role": "discrete_discharge_and_stage_observation_times",
        },
    )


def _compile_match_window_requests(
    candidates: list[dict[str, Any]],
    follow_up_bodies: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    discovered = {
        str(value["monitoring_location_id"]) for value in candidates
    }
    anchor_metadata = follow_up_bodies[
        (ANCHOR_SITE_ID, "time-series-metadata")
    ]
    coverage: dict[str, list[tuple[datetime, datetime]]] = {}
    for feature in anchor_metadata["features"]:
        properties = feature["properties"]
        code = str(properties.get("parameter_code"))
        if (
            code in {"00060", "00065"}
            and properties.get("computation_period_identifier") == "Points"
            and properties.get("computation_identifier") == "Instantaneous"
            and properties.get("statistic_id") == "00011"
        ):
            coverage.setdefault(code, []).append(
                (
                    _parse_datetime(str(properties["begin_utc"])),
                    _parse_datetime(str(properties["end_utc"])),
                )
            )
    matches = []
    for site_id in sorted(discovered - {ANCHOR_SITE_ID}):
        fields = follow_up_bodies[(site_id, "field-measurements")]
        for feature in fields["features"]:
            properties = feature["properties"]
            code = str(properties.get("parameter_code"))
            if code not in coverage:
                continue
            observed_at = _parse_datetime(str(properties["time"]))
            if not any(start <= observed_at <= end for start, end in coverage[code]):
                continue
            start = observed_at.timestamp() - MATCH_WINDOW_HALF_WIDTH_SECONDS
            end = observed_at.timestamp() + MATCH_WINDOW_HALF_WIDTH_SECONDS
            start_text = datetime.fromtimestamp(
                start, tz=timezone.utc
            ).isoformat().replace("+00:00", "Z")
            end_text = datetime.fromtimestamp(
                end, tz=timezone.utc
            ).isoformat().replace("+00:00", "Z")
            encoded_interval = urllib.parse.quote(
                f"{start_text}/{end_text}", safe=""
            )
            timestamp_id = observed_at.strftime("%Y%m%dT%H%M%SZ")
            site_number = site_id.removeprefix("USGS-")
            matches.append(
                {
                    "source_id": (
                        f"usgs_anchor_continuous_match_{site_number}_"
                        f"{timestamp_id}_{code}"
                    ),
                    "collection": "continuous",
                    "url": (
                        f"{WATERDATA_BASE}/continuous/items?f=json&limit=10000"
                        f"&monitoring_location_id={ANCHOR_SITE_ID}"
                        f"&parameter_code={code}&datetime={encoded_interval}"
                    ),
                    "output_name": (
                        f"raw/anchor_continuous_match_{site_number}_"
                        f"{timestamp_id}_{code}.json"
                    ),
                    "maximum_bytes": MAXIMUM_MATCH_WINDOW_BYTES,
                    "candidate_monitoring_location_id": site_id,
                    "candidate_field_measurement_id": str(feature["id"]),
                    "candidate_field_time": str(properties["time"]),
                    "candidate_field_value": str(properties["value"]),
                    "candidate_field_unit": str(properties["unit_of_measure"]),
                    "candidate_approval_status": str(
                        properties["approval_status"]
                    ),
                    "parameter_code": code,
                    "window_start": start_text,
                    "window_end": end_text,
                }
            )
    matches.sort(
        key=lambda value: (
            str(value["candidate_field_time"]),
            str(value["candidate_monitoring_location_id"]),
        )
    )
    if len(matches) > MAXIMUM_MATCH_WINDOW_COUNT:
        raise ValueError("stage27_spatial_boundary_match_boundary_exceeded")
    return matches


def _discover_candidates(
    navigation_bodies: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    request_by_id = {
        str(value["source_id"]): value for value in NAVIGATION_REQUESTS
    }
    for source_id, body in navigation_bodies.items():
        source = request_by_id.get(source_id)
        if source is None:
            raise ValueError("stage27_spatial_boundary_navigation_source_unknown")
        for feature in body["features"]:
            properties = feature["properties"]
            site_id = str(properties["identifier"])
            if not site_id.startswith("USGS-"):
                raise ValueError("stage27_spatial_boundary_site_id_invalid")
            coordinates = feature["geometry"]["coordinates"]
            current = by_id.setdefault(
                site_id,
                {
                    "monitoring_location_id": site_id,
                    "name": str(properties["name"]),
                    "coordinate_wgs84": [
                        float(coordinates[0]),
                        float(coordinates[1]),
                    ],
                    "comid": int(properties["comid"]),
                    "reachcode": str(properties["reachcode"]),
                    "measure_percent": float(properties["measure"]),
                    "mainstem_uri": properties.get("mainstem"),
                    "topology_directions": [],
                    "navigation_search_bounds_km": {},
                },
            )
            if (
                current["comid"] != int(properties["comid"])
                or current["coordinate_wgs84"]
                != [float(coordinates[0]), float(coordinates[1])]
            ):
                raise ValueError(
                    "stage27_spatial_boundary_candidate_identity_conflict"
                )
            direction = str(source["direction"])
            if direction not in current["topology_directions"]:
                current["topology_directions"].append(direction)
            current["navigation_search_bounds_km"][direction] = float(
                source["distance_km"]
            )
    if ANCHOR_SITE_ID not in by_id:
        raise ValueError("stage27_spatial_boundary_anchor_not_discovered")
    if len(by_id) > MAXIMUM_CANDIDATE_COUNT:
        raise ValueError("stage27_spatial_boundary_candidate_boundary_exceeded")
    candidates = []
    for site_id in sorted(by_id):
        value = by_id[site_id]
        value["topology_directions"] = sorted(value["topology_directions"])
        candidates.append(value)
    return candidates


def _opener(proxy: str) -> urllib.request.OpenerDirector:
    parsed = urllib.parse.urlparse(proxy)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("stage27_spatial_boundary_proxy_invalid")
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    )


def _fetch(
    url: str,
    *,
    opener: urllib.request.OpenerDirector,
    timeout_seconds: float,
    retries: int,
    maximum_bytes: int,
) -> tuple[bytes, dict[str, object]]:
    _validate_url(url)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                _validate_url(response.geturl())
                body = response.read(maximum_bytes + 1)
                if len(body) > maximum_bytes:
                    raise ValueError(
                        "stage27_spatial_boundary_object_boundary_exceeded"
                    )
                return body, {
                    "http_status": int(response.status),
                    "content_type": response.headers.get("Content-Type"),
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "final_url": response.geturl(),
                    "attempt_count": attempt,
                }
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 8))
    raise RuntimeError("stage27_spatial_boundary_download_failed") from last_error


def _validate_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("stage27_spatial_boundary_url_outside_allowlist")


def _validate_navigation_body(body: bytes) -> dict[str, Any]:
    value = json.loads(body)
    features = value.get("features")
    if value.get("type") != "FeatureCollection" or not isinstance(features, list):
        raise ValueError("stage27_spatial_boundary_navigation_body_invalid")
    for feature in features:
        properties = feature.get("properties", {})
        coordinates = feature.get("geometry", {}).get("coordinates", [])
        if (
            feature.get("geometry", {}).get("type") != "Point"
            or len(coordinates) != 2
            or not all(math.isfinite(float(item)) for item in coordinates)
            or not str(properties.get("identifier", "")).startswith("USGS-")
            or not isinstance(properties.get("comid"), int)
        ):
            raise ValueError("stage27_spatial_boundary_navigation_body_invalid")
    return value


def _validate_follow_up_body(
    collection: str, site_id: str, body: bytes
) -> None:
    value = json.loads(body)
    if collection == "monitoring-locations":
        observed = value.get("properties", {}).get("id")
        valid = value.get("type") == "Feature" and observed == site_id
    else:
        features = value.get("features")
        valid = value.get("type") == "FeatureCollection" and isinstance(
            features, list
        )
        if valid:
            valid = all(
                feature.get("properties", {}).get("monitoring_location_id")
                == site_id
                for feature in features
            )
    if not valid:
        raise ValueError("stage27_spatial_boundary_follow_up_body_invalid")


def _validate_continuous_body(
    site_id: str, parameter_code: str, body: bytes
) -> None:
    value = json.loads(body)
    features = value.get("features")
    valid = (
        value.get("type") == "FeatureCollection"
        and isinstance(features, list)
        and bool(features)
        and all(
            feature.get("properties", {}).get("monitoring_location_id")
            == site_id
            and feature.get("properties", {}).get("parameter_code")
            == parameter_code
            for feature in features
        )
    )
    if not valid:
        raise ValueError("stage27_spatial_boundary_continuous_body_invalid")


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("stage27_spatial_boundary_datetime_naive")
    return parsed.astimezone(timezone.utc)


def _checked_total(current: int, added: int) -> int:
    total = current + added
    if total > MAXIMUM_TOTAL_DOWNLOAD_BYTES:
        raise ValueError("stage27_spatial_boundary_total_boundary_exceeded")
    return total


def _artifact_record(
    path: Path,
    *,
    source: dict[str, Any],
    retrieval: dict[str, object],
    role: str,
) -> dict[str, Any]:
    body = path.read_bytes()
    return {
        **source,
        **retrieval,
        "path": path.relative_to(REPO_ROOT).as_posix(),
        "size_bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "role": role,
        "license": LICENSE,
        "license_url": LICENSE_URL,
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
