#!/usr/bin/env python3
"""Acquire bounded Center Hill operational-boundary evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "stage28_center_hill_operational_boundary_evidence"
)
SCHEMA = "gwm.geotransport.stage28_operational_boundary_acquisition.v1"
USER_AGENT = "gisdataagent-stage28-operational-boundary-evidence/0.1"
CWMS_HOST = "cwms-data.usace.army.mil"
CWMS_ROOT = f"https://{CWMS_HOST}/cwms-data"
CWMS_RESOLVED_IPS = ("3.30.180.152", "3.32.180.175")
USGS_ROOT = (
    "https://api.waterdata.usgs.gov/ogcapi/v0/collections/continuous/items"
)
CWMS_LOCATION_ID = "CETT1-CENTER_HILL"
CWMS_SERIES_ID = (
    "CETT1-CENTER_HILL.Flow.Ave.1Hour.1Hour.man-rev"
)
CWMS_OFFICE = "LRN"
USGS_SITE_ID = "USGS-03424860"
USGS_PARAMETER_CODE = "00060"
LAG_CANDIDATES_HOURS = tuple(range(13))
MAXIMUM_REQUEST_COUNT = 6
MAXIMUM_TOTAL_DOWNLOAD_BYTES = 5_000_000
MAXIMUM_BYTES = {
    "cwms_location": 100_000,
    "cwms_catalog": 250_000,
    "cwms_values": 500_000,
    "usgs_values": 1_500_000,
}
ALLOWED_HOSTS = frozenset({CWMS_HOST, "api.waterdata.usgs.gov"})
USGS_LICENSE = "USGS public-domain data"
USGS_LICENSE_URL = (
    "https://www.usgs.gov/information-policies-and-instructions/"
    "copyrights-and-credits"
)
CWMS_SOURCE_TERMS = (
    "USACE CWMS Data API public endpoint; redistribution terms not "
    "independently adjudicated"
)
CWMS_SOURCE_URL = "https://cwms-data.usace.army.mil/cwms-data/swagger-ui.html"
EVENTS = (
    {
        "event_id": "high_release_2024",
        "role": "development",
        "start": "2024-05-15T00:00:00Z",
        "end": "2024-05-18T00:00:00Z",
        "stage27_field_observation_time": "2024-05-16T14:40:55+00:00",
    },
    {
        "event_id": "low_release_2026",
        "role": "transfer",
        "start": "2026-02-09T00:00:00Z",
        "end": "2026-02-12T00:00:00Z",
        "stage27_field_observation_time": "2026-02-10T16:49:30+00:00",
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def compile_plan(*, values_mode: bool = False) -> dict[str, Any]:
    sources = _compile_sources()
    planned_maximum = sum(int(value["maximum_bytes"]) for value in sources)
    if (
        len(sources) > MAXIMUM_REQUEST_COUNT
        or planned_maximum > MAXIMUM_TOTAL_DOWNLOAD_BYTES
    ):
        raise ValueError("stage28_operational_boundary_request_boundary_exceeded")
    return {
        "schema": SCHEMA,
        "mode": "values" if values_mode else "plan",
        "purpose": (
            "bind a public Center Hill tailwater release series to the "
            "Stage 27 upstream-site zone and run a predeclared two-event "
            "lag diagnostic against downstream USGS discharge"
        ),
        "target": {
            "cwms_location_id": CWMS_LOCATION_ID,
            "cwms_series_id": CWMS_SERIES_ID,
            "cwms_office": CWMS_OFFICE,
            "downstream_monitoring_location_id": USGS_SITE_ID,
            "downstream_parameter_code": USGS_PARAMETER_CODE,
            "stage27_upstream_monitoring_location_id": "USGS-03424010",
        },
        "predeclared_diagnostic": {
            "lag_candidates_hours": list(LAG_CANDIDATES_HOURS),
            "development_event_id": "high_release_2024",
            "transfer_event_id": "low_release_2026",
            "selection_metric": "maximum_pearson_r_then_minimum_rmse",
            "cwms_support": "hour_average_timestamped_at_support_end",
            "usgs_aggregation": (
                "mean_of_two_observed_half_hour_samples_in_open_closed_hour"
            ),
            "missing_sample_policy": "drop_hour_without_filling",
        },
        "events": [dict(value) for value in EVENTS],
        "request_boundary": {
            "allowed_hosts": sorted(ALLOWED_HOSTS),
            "maximum_request_count": MAXIMUM_REQUEST_COUNT,
            "maximum_total_download_bytes": MAXIMUM_TOTAL_DOWNLOAD_BYTES,
            "planned_maximum_bytes": planned_maximum,
            "event_count": len(EVENTS),
            "window_hours_per_event": 72,
            "workspace_or_private_data_sent": False,
            "cwms_fixed_ip_fallback_retains_tls_hostname_verification": True,
        },
        "sources": sources,
        "claim_boundary": {
            "source_values_acquired": values_mode,
            "bounded_operational_release_windows_admitted": False,
            "cwms_location_bound_to_stage27_upstream_site_zone": False,
            "cwms_and_usgs_are_same_sensor": False,
            "travel_time_identified": False,
            "boundary_conditioned_rollout_completed": False,
            "runtime_operator_admitted": False,
        },
    }


def _compile_sources() -> list[dict[str, Any]]:
    catalog_query = urllib.parse.urlencode(
        {
            "office": CWMS_OFFICE,
            "page-size": 10,
            "like": CWMS_SERIES_ID,
            "include-aliases": "true",
        }
    )
    location_query = urllib.parse.urlencode({"office": CWMS_OFFICE})
    sources: list[dict[str, Any]] = [
        {
            "source_id": "cwms_tailwater_location",
            "source": "usace_cwms",
            "url": (
                f"{CWMS_ROOT}/locations/"
                f"{urllib.parse.quote(CWMS_LOCATION_ID, safe='-')}?"
                f"{location_query}"
            ),
            "output_name": "raw/cwms_tailwater_location.json",
            "maximum_bytes": MAXIMUM_BYTES["cwms_location"],
            "role": "tailwater_location_identity_and_coordinate_support",
            "source_terms": CWMS_SOURCE_TERMS,
            "source_terms_url": CWMS_SOURCE_URL,
        },
        {
            "source_id": "cwms_release_series_catalog",
            "source": "usace_cwms",
            "url": f"{CWMS_ROOT}/catalog/TIMESERIES?{catalog_query}",
            "output_name": "raw/cwms_release_series_catalog.json",
            "maximum_bytes": MAXIMUM_BYTES["cwms_catalog"],
            "role": "release_series_identity_aliases_units_and_extent",
            "source_terms": CWMS_SOURCE_TERMS,
            "source_terms_url": CWMS_SOURCE_URL,
        },
    ]
    for event in EVENTS:
        event_id = str(event["event_id"])
        cwms_query = urllib.parse.urlencode(
            {
                "name": CWMS_SERIES_ID,
                "office": CWMS_OFFICE,
                "begin": event["start"],
                "end": event["end"],
                "unit": "cms",
                "page-size": 1000,
            }
        )
        usgs_query = urllib.parse.urlencode(
            {
                "f": "json",
                "limit": 10000,
                "monitoring_location_id": USGS_SITE_ID,
                "parameter_code": USGS_PARAMETER_CODE,
                "datetime": f"{event['start']}/{event['end']}",
            }
        )
        sources.extend(
            [
                {
                    "source_id": f"cwms_release_{event_id}",
                    "source": "usace_cwms",
                    "event_id": event_id,
                    "url": f"{CWMS_ROOT}/timeseries?{cwms_query}",
                    "output_name": f"raw/cwms_release_{event_id}.json",
                    "maximum_bytes": MAXIMUM_BYTES["cwms_values"],
                    "role": "bounded_hourly_operational_release_values",
                    "source_terms": CWMS_SOURCE_TERMS,
                    "source_terms_url": CWMS_SOURCE_URL,
                },
                {
                    "source_id": f"usgs_downstream_{event_id}",
                    "source": "usgs_water_data",
                    "event_id": event_id,
                    "url": f"{USGS_ROOT}?{usgs_query}",
                    "output_name": f"raw/usgs_downstream_{event_id}.json",
                    "maximum_bytes": MAXIMUM_BYTES["usgs_values"],
                    "role": "bounded_downstream_continuous_discharge_values",
                    "license": USGS_LICENSE,
                    "license_url": USGS_LICENSE_URL,
                },
            ]
        )
    return sources


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("stage28_operational_boundary_request_limits_invalid")
    output = args.output.resolve()
    data_root = (REPO_ROOT / "data/geotransport_v0_1").resolve()
    if output != data_root and data_root not in output.parents:
        raise ValueError("stage28_operational_boundary_output_outside_data_root")
    output.mkdir(parents=True, exist_ok=True)
    if args.plan_only:
        path = output / "acquisition_plan.json"
        _write_json(path, compile_plan())
        print(path)
        return 0

    frozen_plan_path = output / "acquisition_plan.json"
    frozen_plan = _load_frozen_plan(frozen_plan_path)
    values_plan = compile_plan(values_mode=True)
    artifacts: list[dict[str, Any]] = []
    total_bytes = 0
    opener = _opener(args.proxy)
    events = {str(value["event_id"]): value for value in EVENTS}
    for source in values_plan["sources"]:
        body, retrieval = _fetch(
            str(source["url"]),
            opener=opener,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            maximum_bytes=int(source["maximum_bytes"]),
        )
        payload = _json_object(body)
        source_id = str(source["source_id"])
        if source_id == "cwms_tailwater_location":
            _validate_cwms_location(payload)
        elif source_id == "cwms_release_series_catalog":
            _validate_cwms_catalog(payload)
        elif source_id.startswith("cwms_release_"):
            _validate_cwms_values(payload, events[str(source["event_id"])])
        elif source_id.startswith("usgs_downstream_"):
            _validate_usgs_values(payload, events[str(source["event_id"])])
        else:
            raise ValueError("stage28_operational_boundary_source_unknown")
        total_bytes = _checked_total(total_bytes, len(body))
        path = output / str(source["output_name"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        artifacts.append(
            _artifact_record(path, source=source, retrieval=retrieval)
        )

    manifest = {
        **values_plan,
        "frozen_acquisition_plan": _artifact(frozen_plan_path),
        "frozen_acquisition_plan_content": frozen_plan,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "actual_request_count": len(artifacts),
        "total_downloaded_bytes": total_bytes,
    }
    path = output / "acquisition_manifest.json"
    _write_json(path, manifest)
    print(path)
    print(f"requests={len(artifacts)}")
    print(f"downloaded_bytes={total_bytes}")
    return 0


def _load_frozen_plan(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("stage28_acquisition_plan_must_be_frozen_before_values")
    value = _json_object(path.read_bytes())
    if value != compile_plan():
        raise ValueError("stage28_frozen_acquisition_plan_mismatch")
    return value


def _fetch(
    url: str,
    *,
    opener: urllib.request.OpenerDirector,
    timeout_seconds: float,
    retries: int,
    maximum_bytes: int,
) -> tuple[bytes, dict[str, Any]]:
    host = _validate_url(url)
    failures: list[dict[str, Any]] = []
    error: Exception | None = None
    accept = (
        "application/json;version=2"
        if host == CWMS_HOST
        else "application/json"
    )
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(
            url, headers={"Accept": accept, "User-Agent": USER_AGENT}
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                final_host = _validate_url(response.geturl())
                if final_host not in ALLOWED_HOSTS:
                    raise ValueError(
                        "stage28_operational_boundary_redirect_outside_allowlist"
                    )
                body = response.read(maximum_bytes + 1)
                _validate_size(body, maximum_bytes)
                return body, {
                    "url": url,
                    "transport": "configured_proxy_or_direct_urllib",
                    "http_status": response.status,
                    "content_type": response.headers.get("Content-Type"),
                    "attempt_count": attempt,
                    "failed_attempts": failures,
                    "tls_hostname_verification_retained": True,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            error = exc
            failures.append(
                {
                    "transport": "configured_proxy_or_direct_urllib",
                    "attempt": attempt,
                    "error": str(exc),
                }
            )
            if isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500:
                break
            if attempt < retries:
                time.sleep(float(attempt))
    if host == CWMS_HOST:
        for resolved_ip in CWMS_RESOLVED_IPS:
            command = _cwms_curl_command(
                url,
                resolved_ip=resolved_ip,
                timeout_seconds=timeout_seconds,
            )
            result = subprocess.run(command, capture_output=True, check=False)
            if result.returncode == 0:
                _validate_size(result.stdout, maximum_bytes)
                return result.stdout, {
                    "url": url,
                    "transport": f"direct_resolve_{resolved_ip}",
                    "http_status": 200,
                    "content_type": "application/json",
                    "attempt_count": len(failures) + 1,
                    "failed_attempts": failures,
                    "tls_hostname_verification_retained": True,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }
            failures.append(
                {
                    "transport": f"direct_resolve_{resolved_ip}",
                    "returncode": result.returncode,
                    "error": result.stderr.decode("utf-8", errors="replace"),
                }
            )
    raise RuntimeError(
        f"stage28_operational_boundary_request_failed:{error}:{failures}"
    )


def _cwms_curl_command(
    url: str, *, resolved_ip: str, timeout_seconds: float
) -> list[str]:
    if resolved_ip not in CWMS_RESOLVED_IPS or _validate_url(url) != CWMS_HOST:
        raise ValueError("stage28_cwms_resolved_transport_invalid")
    return [
        "curl",
        "--noproxy",
        "*",
        "--resolve",
        f"{CWMS_HOST}:443:{resolved_ip}",
        "-fsS",
        "--retry",
        "2",
        "--retry-all-errors",
        "--connect-timeout",
        "15",
        "--max-time",
        str(max(1, int(timeout_seconds))),
        "-A",
        USER_AGENT,
        "-H",
        "Accept: application/json;version=2",
        url,
    ]


def _validate_cwms_location(value: dict[str, Any]) -> None:
    if (
        value.get("office-id") != CWMS_OFFICE
        or value.get("name") != CWMS_LOCATION_ID
        or value.get("public-name") != "Center Hill Dam Tailwater"
        or value.get("location-type") != "Tailwater"
        or value.get("horizontal-datum") != "NAD83"
        or value.get("timezone-name") != "US/Central"
        or value.get("active") is not True
        or not isinstance(value.get("latitude"), (int, float))
        or not isinstance(value.get("longitude"), (int, float))
    ):
        raise ValueError("stage28_cwms_tailwater_location_invalid")


def _validate_cwms_catalog(value: dict[str, Any]) -> None:
    entries = value.get("entries")
    if not isinstance(entries, list) or len(entries) != 1:
        raise ValueError("stage28_cwms_release_catalog_not_exact")
    entry = entries[0]
    aliases = {
        str(item.get("value"))
        for item in entry.get("aliases", [])
        if isinstance(item, dict)
    }
    extents = entry.get("extents")
    if (
        entry.get("office") != CWMS_OFFICE
        or entry.get("name") != CWMS_SERIES_ID
        or entry.get("units") != "cms"
        or entry.get("interval") != "1Hour"
        or entry.get("interval-offset") != 0
        or not isinstance(extents, list)
        or not extents
        or not {"Outflow", "Total Flow"}.issubset(aliases)
    ):
        raise ValueError("stage28_cwms_release_catalog_invalid")


def _validate_cwms_values(
    value: dict[str, Any], event: dict[str, Any]
) -> None:
    start = _parse_time(str(event["start"]))
    end = _parse_time(str(event["end"]))
    values = value.get("values")
    expected = tuple(start + timedelta(hours=index) for index in range(73))
    if (
        value.get("name") != CWMS_SERIES_ID
        or value.get("office-id") != CWMS_OFFICE
        or value.get("units") != "cms"
        or value.get("interval") != "PT1H"
        or value.get("interval-offset") != 0
        or not isinstance(values, list)
        or len(values) != len(expected)
    ):
        raise ValueError("stage28_cwms_release_values_invalid")
    actual = []
    for row in values:
        if (
            not isinstance(row, list)
            or len(row) != 3
            or not isinstance(row[0], int)
            or not isinstance(row[1], (int, float))
            or not isinstance(row[2], int)
        ):
            raise ValueError("stage28_cwms_release_value_row_invalid")
        actual.append(datetime.fromtimestamp(row[0] / 1000.0, tz=timezone.utc))
    if tuple(actual) != expected:
        raise ValueError("stage28_cwms_release_time_axis_invalid")


def _validate_usgs_values(
    value: dict[str, Any], event: dict[str, Any]
) -> None:
    features = value.get("features")
    start = _parse_time(str(event["start"]))
    expected = tuple(start + timedelta(minutes=30 * index) for index in range(145))
    if not isinstance(features, list) or len(features) != len(expected):
        raise ValueError("stage28_usgs_downstream_values_invalid")
    actual = []
    for feature in features:
        properties = feature.get("properties") if isinstance(feature, dict) else None
        if (
            not isinstance(properties, dict)
            or properties.get("monitoring_location_id") != USGS_SITE_ID
            or properties.get("parameter_code") != USGS_PARAMETER_CODE
            or properties.get("statistic_id") != "00011"
            or properties.get("unit_of_measure") != "ft^3/s"
            or not isinstance(properties.get("approval_status"), str)
            or not isinstance(properties.get("value"), str)
        ):
            raise ValueError("stage28_usgs_downstream_value_row_invalid")
        actual.append(_parse_time(str(properties["time"])))
        float(properties["value"])
    if tuple(actual) != expected:
        raise ValueError("stage28_usgs_downstream_time_axis_invalid")


def _validate_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("stage28_operational_boundary_url_outside_allowlist")
    return str(parsed.hostname)


def _validate_size(body: bytes, maximum_bytes: int) -> None:
    if len(body) > maximum_bytes:
        raise ValueError("stage28_operational_boundary_object_size_limit_exceeded")


def _checked_total(current: int, added: int) -> int:
    total = current + added
    if total > MAXIMUM_TOTAL_DOWNLOAD_BYTES:
        raise ValueError("stage28_operational_boundary_total_size_limit_exceeded")
    return total


def _artifact_record(
    path: Path, *, source: dict[str, Any], retrieval: dict[str, Any]
) -> dict[str, Any]:
    return {
        "source_id": source["source_id"],
        "source": source["source"],
        "role": source["role"],
        "event_id": source.get("event_id"),
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
        "hash_verified": True,
        "license": source.get("license"),
        "license_url": source.get("license_url"),
        "source_terms": source.get("source_terms"),
        "source_terms_url": source.get("source_terms_url"),
        **retrieval,
    }


def _artifact(path: Path) -> dict[str, Any]:
    body = path.read_bytes()
    return {
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _json_object(body: bytes) -> dict[str, Any]:
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError("stage28_operational_boundary_json_object_required")
    return value


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("stage28_operational_boundary_timezone_required")
    return parsed.astimezone(timezone.utc)


def _opener(proxy: str) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = []
    if proxy:
        handlers.append(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    return urllib.request.build_opener(*handlers)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
