#!/usr/bin/env python3
"""Acquire bounded USGS field channel measurements for Stage 23."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/stage23_usgs_channel_measurements_03424860"
)
SCHEMA = "gwm.geotransport.stage23_usgs_channel_measurement_acquisition.v1"
USER_AGENT = "gisdataagent-stage23-usgs-channel-measurements/0.1"
MAXIMUM_TOTAL_DOWNLOAD_BYTES = 1_500_000
ALLOWED_HOSTS = frozenset({"api.waterdata.usgs.gov"})

BASE = "https://api.waterdata.usgs.gov/ogcapi/v0/collections"
REQUESTS = (
    {
        "source_id": "usgs_channel_measurements_queryables",
        "url": f"{BASE}/channel-measurements/queryables?f=json",
        "output_name": "raw/channel_measurements_queryables.json",
        "maximum_bytes": 100_000,
        "role": "machine_readable_field_semantics",
    },
    {
        "source_id": "usgs_channel_measurements_03424860",
        "url": (
            f"{BASE}/channel-measurements/items?f=json&limit=10000"
            "&monitoring_location_id=USGS-03424860"
        ),
        "output_name": "raw/channel_measurements_03424860.json",
        "maximum_bytes": 500_000,
        "role": "observed_width_area_velocity_and_discharge",
    },
    {
        "source_id": "usgs_field_measurements_03424860",
        "url": (
            f"{BASE}/field-measurements/items?f=json&limit=10000"
            "&monitoring_location_id=USGS-03424860"
        ),
        "output_name": "raw/field_measurements_03424860.json",
        "maximum_bytes": 800_000,
        "role": "field_visit_gage_height_and_discharge_join",
    },
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
    planned = sum(int(value["maximum_bytes"]) for value in REQUESTS)
    if planned > MAXIMUM_TOTAL_DOWNLOAD_BYTES:
        raise ValueError("stage23_channel_measurement_request_boundary_exceeded")
    return {
        "schema": SCHEMA,
        "mode": "values" if values_mode else "plan",
        "purpose": (
            "compile observed downstream reach hydraulic states and "
            "state-conditioned equivalent cross-section priors"
        ),
        "target": {
            "monitoring_location_id": "USGS-03424860",
            "nwm_feature_id": 18421703,
            "relation_to_confluence": (
                "same_downstream_feature_approximately_925m_from_junction"
            ),
        },
        "request_boundary": {
            "allowed_hosts": sorted(ALLOWED_HOSTS),
            "request_count": len(REQUESTS),
            "maximum_total_download_bytes": MAXIMUM_TOTAL_DOWNLOAD_BYTES,
            "planned_maximum_bytes": planned,
            "limit_per_items_request": 10_000,
            "workspace_or_private_data_sent": False,
        },
        "requests": [
            {
                **value,
                "license": "USGS public-domain data",
                "license_url": (
                    "https://www.usgs.gov/information-policies-and-"
                    "instructions/copyrights-and-credits"
                ),
            }
            for value in REQUESTS
        ],
        "claim_boundary": {
            "source_values_acquired": values_mode,
            "measurement_location_is_junction_patch": False,
            "single_measurement_defines_permanent_cross_section": False,
            "gage_height_is_bed_referenced_depth": False,
            "confluence_bathymetry_completed": False,
            "operator_admitted": False,
        },
    }


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("stage23_channel_measurement_request_limits_invalid")
    output = args.output.resolve()
    data_root = (REPO_ROOT / "data/geotransport_v0_1").resolve()
    if output != data_root and data_root not in output.parents:
        raise ValueError("stage23_channel_measurement_output_outside_data_root")
    output.mkdir(parents=True, exist_ok=True)
    plan = compile_plan(values_mode=not args.plan_only)
    if args.plan_only:
        path = output / "acquisition_plan.json"
        _write_json(path, plan)
        print(path)
        return 0

    opener = _opener(args.proxy)
    artifacts = []
    total_bytes = 0
    for source in REQUESTS:
        body, retrieval = _fetch(
            str(source["url"]),
            opener=opener,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            maximum_bytes=int(source["maximum_bytes"]),
        )
        _validate_source_body(str(source["source_id"]), body)
        total_bytes += len(body)
        if total_bytes > MAXIMUM_TOTAL_DOWNLOAD_BYTES:
            raise ValueError(
                "stage23_channel_measurement_total_boundary_exceeded"
            )
        path = output / str(source["output_name"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        artifacts.append(
            {
                **source,
                **retrieval,
                "path": path.relative_to(REPO_ROOT).as_posix(),
                "size_bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "license": "USGS public-domain data",
                "license_url": (
                    "https://www.usgs.gov/information-policies-and-"
                    "instructions/copyrights-and-credits"
                ),
            }
        )
    manifest = {
        **plan,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "total_downloaded_bytes": total_bytes,
    }
    path = output / "acquisition_manifest.json"
    _write_json(path, manifest)
    print(path)
    print(f"downloaded_bytes={total_bytes}")
    print(f"artifacts={len(artifacts)}")
    return 0


def _opener(proxy: str) -> urllib.request.OpenerDirector:
    parsed = urllib.parse.urlparse(proxy)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("stage23_channel_measurement_proxy_invalid")
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
                        "stage23_channel_measurement_object_boundary_exceeded"
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
    raise RuntimeError("stage23_channel_measurement_download_failed") from last_error


def _validate_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("stage23_channel_measurement_url_outside_allowlist")


def _validate_source_body(source_id: str, body: bytes) -> None:
    value = json.loads(body)
    if source_id == "usgs_channel_measurements_queryables":
        properties = value.get("properties", {})
        valid = all(
            field in properties
            for field in (
                "channel_flow",
                "channel_width",
                "channel_area",
                "channel_velocity",
                "field_visit_id",
            )
        )
    elif source_id == "usgs_channel_measurements_03424860":
        features = value.get("features", [])
        valid = (
            value.get("numberReturned") == 110
            and len(features) == 110
            and all(
                item.get("properties", {}).get("monitoring_location_id")
                == "USGS-03424860"
                for item in features
            )
            and not any(
                link.get("rel") == "next" for link in value.get("links", [])
            )
        )
    elif source_id == "usgs_field_measurements_03424860":
        features = value.get("features", [])
        valid = (
            value.get("numberReturned") == 401
            and len(features) == 401
            and all(
                item.get("properties", {}).get("monitoring_location_id")
                == "USGS-03424860"
                for item in features
            )
            and not any(
                link.get("rel") == "next" for link in value.get("links", [])
            )
        )
    else:
        valid = False
    if not valid:
        raise ValueError("stage23_channel_measurement_source_identity_invalid")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
