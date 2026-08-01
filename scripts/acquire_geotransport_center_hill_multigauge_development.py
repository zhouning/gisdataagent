#!/usr/bin/env python3
"""Acquire public in-domain gauges for Center Hill development diagnostics."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import time
from typing import Any, Mapping
import urllib.error
import urllib.parse
import urllib.request


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOPOLOGY_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_v2_d5_full_subnetwork_report.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_multigauge_development"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_multigauge_development_inputs_report.json"
)
SCHEMA = "gwm.geotransport.center_hill_multigauge_development_inputs.v1"
TOPOLOGY_SCHEMA = "gwm.geotransport.center_hill_v2_d5_full_subnetwork.v1"
START = datetime(2021, 12, 9, 1, tzinfo=timezone.utc)
END = datetime(2022, 1, 6, 1, tzinfo=timezone.utc)
HOUR_COUNT = 672
OUTLET_SITE_ID = "03424860"
OUTLET_FEATURE_ID = 18_421_703
PARAMETER_CODE = "00060"
NLDI_DISTANCE_KM = 1000.0
MINIMUM_COMPLETE_HOURS = 500
FT3S_TO_M3S = 0.028316846592
ALLOWED_HOSTS = {
    "api.water.usgs.gov",
    "nwis.waterservices.usgs.gov",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--topology-report", type=Path, default=DEFAULT_TOPOLOGY_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=4)
    return parser.parse_args()


def compile_plan(
    *, topology_report_path: Path = DEFAULT_TOPOLOGY_REPORT
) -> tuple[dict[str, Any], tuple[int, ...], dict[str, Any]]:
    topology_body = topology_report_path.read_bytes()
    topology = json.loads(topology_body)
    if (
        topology.get("schema") != TOPOLOGY_SCHEMA
        or topology.get("status") != "pass_full_incremental_subnetwork_compiled"
    ):
        raise ValueError("multigauge_development_topology_report_invalid")
    network_descriptor = topology["artifacts"]["full_subnetwork"]
    network_body = _read_verified(network_descriptor)
    network_payload = json.loads(network_body)
    network = network_payload.get("network") or {}
    feature_ids = tuple(int(value) for value in network.get("feature_ids") or ())
    if (
        len(feature_ids) != 435
        or len(feature_ids) != len(set(feature_ids))
        or int(network.get("outlet_feature_id")) != OUTLET_FEATURE_ID
    ):
        raise ValueError("multigauge_development_network_axis_invalid")
    nldi_url = (
        "https://api.water.usgs.gov/nldi/linked-data/comid/"
        f"{OUTLET_FEATURE_ID}/navigation/UT/nwissite"
        f"?distance={NLDI_DISTANCE_KM:g}&f=json"
    )
    payload = {
        "schema": SCHEMA,
        "mode": "plan",
        "status": "ready_to_acquire_public_multigauge_development_inputs",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "start_inclusive_utc": _iso(START),
            "end_exclusive_utc": _iso(END),
            "hour_count": HOUR_COUNT,
            "role": "pre_d3_public_development_only",
        },
        "topology_report": _artifact(topology_report_path, topology_body),
        "full_subnetwork": network_descriptor,
        "feature_count": len(feature_ids),
        "outlet": {
            "site_id": OUTLET_SITE_ID,
            "feature_id": OUTLET_FEATURE_ID,
        },
        "requests": {
            "nldi_upstream_nwissite": {
                "url": nldi_url,
                "maximum_bytes": 2_000_000,
                "catalog_snapshot_is_historical_vintage": False,
            },
            "nwis_iv": {
                "url_template": (
                    "https://nwis.waterservices.usgs.gov/nwis/iv/"
                    "?format=json&sites={site_ids}&parameterCd=00060&"
                    "startDT=2021-12-09T01:00:00Z&"
                    "endDT=2022-01-06T01:00:00Z&siteStatus=all"
                ),
                "maximum_bytes": 20_000_000,
            },
        },
        "admission_policy": {
            "station_must_attach_to_frozen_feature_axis": True,
            "parameter_code": PARAMETER_CODE,
            "unit": "ft3/s",
            "accepted_qualifiers": ["A"],
            "minimum_complete_hour_count": MINIMUM_COMPLETE_HOURS,
            "hourly_support": "native samples in (t-1h,t]",
            "missing_values_imputed": False,
        },
        "data_isolation": {
            "d3_outcomes_read": False,
            "two_system_blind_outcomes_read": False,
            "only_pre_d3_development_window_requested": True,
        },
        "claim_boundary": {
            "request_plan_only": True,
            "public_data_without_user_supplied_data": True,
            "operational_vintage_availability_verified": False,
            "multigauge_state_estimation_validated": False,
            "geospatial_kernel_validated": False,
        },
    }
    return payload, feature_ids, network_descriptor


def acquire(
    *,
    topology_report_path: Path = DEFAULT_TOPOLOGY_REPORT,
    output_root: Path = DEFAULT_OUTPUT,
    proxy: str = "http://127.0.0.1:7897",
    timeout_seconds: float = 120.0,
    retries: int = 4,
) -> tuple[dict[str, bytes], bytes, dict[str, Any]]:
    plan, feature_ids, _ = compile_plan(
        topology_report_path=topology_report_path
    )
    opener = _opener(proxy)
    nldi_url = plan["requests"]["nldi_upstream_nwissite"]["url"]
    nldi_body, nldi_retrieval = _fetch(
        nldi_url,
        opener=opener,
        timeout_seconds=timeout_seconds,
        retries=retries,
        maximum_bytes=plan["requests"]["nldi_upstream_nwissite"]["maximum_bytes"],
    )
    candidates = _in_domain_candidates(json.loads(nldi_body), feature_ids)
    site_ids = tuple(sorted(row["site_id"] for row in candidates))
    if OUTLET_SITE_ID not in site_ids:
        raise ValueError("multigauge_development_outlet_site_missing_from_nldi")
    query = urllib.parse.urlencode(
        {
            "format": "json",
            "sites": ",".join(site_ids),
            "parameterCd": PARAMETER_CODE,
            "startDT": _iso(START),
            "endDT": _iso(END),
            "siteStatus": "all",
        }
    )
    nwis_url = f"https://nwis.waterservices.usgs.gov/nwis/iv/?{query}"
    nwis_body, nwis_retrieval = _fetch(
        nwis_url,
        opener=opener,
        timeout_seconds=timeout_seconds,
        retries=retries,
        maximum_bytes=plan["requests"]["nwis_iv"]["maximum_bytes"],
    )
    parsed = _parse_nwis(json.loads(nwis_body), candidates)
    eligible = tuple(
        row for row in parsed if row["complete_hour_count"] >= MINIMUM_COMPLETE_HOURS
    )
    if (
        len(eligible) < 2
        or OUTLET_SITE_ID not in {row["site_id"] for row in eligible}
    ):
        raise ValueError("multigauge_development_insufficient_eligible_sites")
    hourly_body = _hourly_csv(eligible)
    raw_paths = {
        "nldi_upstream_nwissite": output_root / "raw/nldi_upstream_nwissite.json",
        "nwis_iv": output_root / "raw/nwis_iv.json",
    }
    raw_bodies = {
        "nldi_upstream_nwissite": nldi_body,
        "nwis_iv": nwis_body,
    }
    hourly_path = output_root / "values/hourly_discharge.csv"
    report = {
        **plan,
        "mode": "acquired",
        "status": "pass_public_multigauge_development_inputs_acquired",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "nldi_upstream_nwissite": {
                **nldi_retrieval,
                **_artifact(raw_paths["nldi_upstream_nwissite"], nldi_body),
            },
            "nwis_iv": {
                **nwis_retrieval,
                **_artifact(raw_paths["nwis_iv"], nwis_body),
            },
        },
        "station_screening": {
            "nldi_returned_site_count": len(
                (json.loads(nldi_body).get("features") or [])
            ),
            "in_domain_site_count": len(candidates),
            "in_domain_feature_count": len(
                {int(row["feature_id"]) for row in candidates}
            ),
            "nwis_returned_series_count": len(parsed),
            "eligible_site_count": len(eligible),
            "eligible_sites": [
                {
                    key: row[key]
                    for key in (
                        "site_id",
                        "feature_id",
                        "name",
                        "native_cadence_seconds",
                        "native_sample_count",
                        "complete_hour_count",
                        "missing_hour_count",
                        "qualifiers",
                    )
                }
                for row in eligible
            ],
            "in_domain_sites_without_returned_discharge_series": sorted(
                set(site_ids) - {row["site_id"] for row in parsed}
            ),
        },
        "hourly_observations": _artifact(hourly_path, hourly_body),
        "semantics": {
            "variable_role": "historical_state_update",
            "source_is_currently_retrieved_revised_archive": True,
            "approved_qualifier_means_processing_and_review_complete": True,
            "operational_vintage_availability_verified": False,
            "publication_lag_seconds_used_by_closure": 3600,
            "publication_lag_evidence_level": "derived",
            "missing_values_imputed": False,
            "nwm_modeled_state_possible_nudging": True,
        },
        "claim_boundary": {
            "request_plan_only": False,
            "public_data_without_user_supplied_data": True,
            "in_domain_multigauge_development_data_available": True,
            "operational_vintage_availability_verified": False,
            "multigauge_state_estimation_validated": False,
            "predictive_improvement_validated": False,
            "geospatial_kernel_validated": False,
        },
    }
    return raw_bodies, hourly_body, report


def _in_domain_candidates(
    payload: Mapping[str, Any], feature_ids: tuple[int, ...]
) -> list[dict[str, Any]]:
    if payload.get("type") != "FeatureCollection":
        raise ValueError("multigauge_development_nldi_feature_collection_required")
    axis = set(feature_ids)
    candidates: dict[str, dict[str, Any]] = {}
    for feature in payload.get("features") or []:
        properties = feature.get("properties") or {}
        identifier = str(feature.get("id") or properties.get("identifier") or "")
        if not identifier.startswith("USGS-"):
            continue
        feature_id = int(properties.get("comid"))
        if feature_id not in axis:
            continue
        site_id = identifier.removeprefix("USGS-")
        row = {
            "site_id": site_id,
            "feature_id": feature_id,
            "name": str(properties.get("name") or "").strip(),
            "reachcode": properties.get("reachcode"),
            "measure": float(properties.get("measure")),
            "geometry": feature.get("geometry"),
        }
        if site_id in candidates and candidates[site_id] != row:
            raise ValueError("multigauge_development_nldi_site_identity_conflict")
        candidates[site_id] = row
    if not candidates:
        raise ValueError("multigauge_development_no_in_domain_nldi_sites")
    return [candidates[key] for key in sorted(candidates)]


def _parse_nwis(
    payload: Mapping[str, Any], candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_site = {row["site_id"]: row for row in candidates}
    support_ends = tuple(START + timedelta(hours=index + 1) for index in range(HOUR_COUNT))
    parsed: list[dict[str, Any]] = []
    seen_sites: set[str] = set()
    series = (payload.get("value") or {}).get("timeSeries") or []
    for row in series:
        site_codes = {
            str(value.get("value"))
            for value in (row.get("sourceInfo") or {}).get("siteCode") or []
        }
        matched = site_codes & set(by_site)
        if len(matched) != 1:
            raise ValueError("multigauge_development_nwis_site_identity_mismatch")
        site_id = next(iter(matched))
        if site_id in seen_sites:
            raise ValueError("multigauge_development_nwis_duplicate_site_series")
        seen_sites.add(site_id)
        variable = row.get("variable") or {}
        variable_codes = {
            str(value.get("value"))
            for value in variable.get("variableCode") or []
        }
        if (
            PARAMETER_CODE not in variable_codes
            or (variable.get("unit") or {}).get("unitCode") != "ft3/s"
        ):
            raise ValueError("multigauge_development_nwis_variable_or_unit_mismatch")
        groups = row.get("values") or []
        if len(groups) != 1:
            raise ValueError("multigauge_development_nwis_single_value_group_required")
        no_data = float(variable.get("noDataValue", -999999.0))
        samples: list[tuple[datetime, float, tuple[str, ...]]] = []
        seen_timestamps: set[datetime] = set()
        for sample in groups[0].get("value") or []:
            timestamp = _parse_utc(sample["dateTime"])
            if not START <= timestamp <= END:
                continue
            if timestamp in seen_timestamps:
                raise ValueError("multigauge_development_nwis_duplicate_timestamp")
            seen_timestamps.add(timestamp)
            value = float(sample["value"])
            if value == no_data:
                continue
            qualifiers = tuple(str(value) for value in sample.get("qualifiers") or ())
            samples.append((timestamp, value * FT3S_TO_M3S, qualifiers))
        if len(samples) < 2:
            continue
        samples.sort(key=lambda value: value[0])
        deltas = [
            int((second[0] - first[0]).total_seconds())
            for first, second in zip(samples, samples[1:])
            if second[0] > first[0]
        ]
        cadence = math.gcd(*deltas)
        if cadence < 300 or cadence > 3600 or 3600 % cadence != 0:
            raise ValueError("multigauge_development_nwis_native_cadence_invalid")
        expected_count = 3600 // cadence
        values_by_end: dict[datetime, list[float]] = {
            value: [] for value in support_ends
        }
        qualifiers_by_end: dict[datetime, set[str]] = {
            value: set() for value in support_ends
        }
        for timestamp, value, qualifiers in samples:
            if timestamp <= START:
                continue
            seconds = timestamp.minute * 60 + timestamp.second
            if timestamp.microsecond or seconds % cadence:
                raise ValueError("multigauge_development_nwis_sample_off_cadence")
            support_end = timestamp.replace(minute=0, second=0, microsecond=0)
            if seconds:
                support_end += timedelta(hours=1)
            if support_end not in values_by_end:
                continue
            values_by_end[support_end].append(value)
            qualifiers_by_end[support_end].update(qualifiers)
        if any(len(values) > expected_count for values in values_by_end.values()):
            raise ValueError("multigauge_development_nwis_excess_samples_per_hour")
        if any(
            values and qualifiers_by_end[key] != {"A"}
            for key, values in values_by_end.items()
        ):
            raise ValueError("multigauge_development_nwis_unapproved_sample")
        hourly = {
            key: float(sum(values) / len(values))
            if len(values) == expected_count
            else None
            for key, values in values_by_end.items()
        }
        complete = sum(value is not None for value in hourly.values())
        parsed.append(
            {
                **by_site[site_id],
                "native_cadence_seconds": cadence,
                "expected_native_samples_per_hour": expected_count,
                "native_sample_count": len(samples),
                "complete_hour_count": complete,
                "missing_hour_count": HOUR_COUNT - complete,
                "qualifiers": sorted(
                    {
                        qualifier
                        for _, _, qualifiers in samples
                        for qualifier in qualifiers
                    }
                ),
                "hourly": hourly,
                "sample_counts": {
                    key: len(values) for key, values in values_by_end.items()
                },
            }
        )
    return sorted(parsed, key=lambda value: value["site_id"])


def _hourly_csv(eligible: tuple[dict[str, Any], ...]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    header = ["support_start_utc", "support_end_utc"]
    for row in eligible:
        site_id = row["site_id"]
        header.extend(
            [
                f"usgs_{site_id}_discharge_m3s",
                f"usgs_{site_id}_native_sample_count",
                f"usgs_{site_id}_qualifier",
            ]
        )
    writer.writerow(header)
    for index in range(HOUR_COUNT):
        support_start = START + timedelta(hours=index)
        support_end = support_start + timedelta(hours=1)
        values: list[object] = [_iso(support_start), _iso(support_end)]
        for row in eligible:
            value = row["hourly"][support_end]
            count = row["sample_counts"][support_end]
            values.extend(
                [
                    "" if value is None else format(float(value), ".12g"),
                    count,
                    "A" if value is not None else "",
                ]
            )
        writer.writerow(values)
    return stream.getvalue().encode("utf-8")


def _opener(proxy: str) -> urllib.request.OpenerDirector:
    if not proxy:
        return urllib.request.build_opener()
    parsed = urllib.parse.urlparse(proxy)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("multigauge_development_proxy_invalid")
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
) -> tuple[bytes, dict[str, Any]]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("multigauge_development_url_outside_allowlist")
    error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "gisdataagent-center-hill-multigauge-development/0.1",
            },
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                final_url = response.geturl()
                final = urllib.parse.urlparse(final_url)
                if final.scheme != "https" or final.hostname not in ALLOWED_HOSTS:
                    raise ValueError("multigauge_development_redirect_outside_allowlist")
                body = response.read(maximum_bytes + 1)
                if not body:
                    raise ValueError("multigauge_development_empty_response")
                if len(body) > maximum_bytes:
                    raise ValueError("multigauge_development_response_size_limit")
                json.loads(body)
                return body, {
                    "url": url,
                    "final_url": final_url,
                    "http_status": response.status,
                    "content_type": response.headers.get("Content-Type"),
                    "attempt_count": attempt,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                raise RuntimeError(
                    f"multigauge_development_nonretryable_http:{exc.code}"
                ) from exc
            error = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            error = exc
        if attempt < retries:
            time.sleep(float(attempt))
    raise RuntimeError(f"multigauge_development_request_failed:{error}")


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("multigauge_development_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("multigauge_development_artifact_identity_mismatch")
    return body


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": _display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("multigauge_development_timezone_required")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("multigauge_development_positive_request_limits_required")
    if args.plan_only:
        report, _, _ = compile_plan(topology_report_path=args.topology_report)
    else:
        if args.output.exists() or args.report.exists():
            raise ValueError("multigauge_development_refuses_overwrite")
        raw, hourly, report = acquire(
            topology_report_path=args.topology_report,
            output_root=args.output,
            proxy=args.proxy,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
        )
        for name, body in raw.items():
            path = args.output / f"raw/{name}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        hourly_path = args.output / "values/hourly_discharge.csv"
        hourly_path.parent.mkdir(parents=True, exist_ok=True)
        hourly_path.write_bytes(hourly)
    _write_json(args.report, report)
    print(args.report)
    print(report["status"])
    if not args.plan_only:
        print(
            "eligible_site_count="
            f"{report['station_screening']['eligible_site_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
