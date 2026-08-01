#!/usr/bin/env python3
"""Acquire pre-development Smith Fork history for boundary-transition fitting."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import gzip
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
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/smith_fork_boundary_history"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/smith_fork_boundary_history_report.json"
)
SCHEMA = "gwm.geotransport.smith_fork_boundary_history.v1"
SITE_ID = "03424730"
FEATURE_ID = 18_421_273
PARAMETER_CODE = "00060"
START = datetime(2021, 1, 1, 0, tzinfo=timezone.utc)
FIT_END = datetime(2021, 9, 1, 0, tzinfo=timezone.utc)
END = datetime(2021, 12, 9, 1, tzinfo=timezone.utc)
FT3S_TO_M3S = 0.028316846592
ALLOWED_HOST = "nwis.waterservices.usgs.gov"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=4)
    return parser.parse_args()


def compile_plan() -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "format": "json",
            "sites": SITE_ID,
            "parameterCd": PARAMETER_CODE,
            "startDT": _iso(START),
            "endDT": _iso(END),
            "siteStatus": "all",
        }
    )
    return {
        "schema": SCHEMA,
        "mode": "plan",
        "status": "ready_to_acquire_public_boundary_history",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "site": {"site_id": SITE_ID, "feature_id": FEATURE_ID},
        "window": {
            "start_inclusive_utc": _iso(START),
            "fit_end_exclusive_utc": _iso(FIT_END),
            "holdout_start_inclusive_utc": _iso(FIT_END),
            "end_exclusive_utc": _iso(END),
            "role": "boundary_only_fit_and_temporal_holdout_before_downstream_development",
        },
        "request": {
            "url": f"https://{ALLOWED_HOST}/nwis/iv/?{query}",
            "maximum_uncompressed_bytes": 5_000_000,
            "accept_encoding": "gzip",
        },
        "admission_policy": {
            "parameter_code": PARAMETER_CODE,
            "required_unit": "ft3/s",
            "accepted_qualifiers": ["A"],
            "expected_native_cadence_seconds": 1800,
            "hourly_support": "complete native samples in (t-1h,t]",
            "missing_values_imputed": False,
        },
        "data_isolation": {
            "center_hill_outlet_target_requested": False,
            "current_downstream_development_window_requested": False,
            "d3_or_blind_outcomes_requested": False,
        },
        "claim_boundary": {
            "request_plan_only": True,
            "public_data_without_user_supplied_data": True,
            "operational_vintage_verified": False,
            "boundary_transition_fitted": False,
            "geospatial_kernel_validated": False,
        },
    }


def acquire(
    *,
    output_root: Path,
    proxy: str,
    timeout_seconds: float,
    retries: int,
) -> tuple[bytes, bytes, dict[str, Any]]:
    plan = compile_plan()
    raw, retrieval = _fetch(
        plan["request"]["url"],
        proxy=proxy,
        timeout_seconds=timeout_seconds,
        retries=retries,
        maximum_bytes=plan["request"]["maximum_uncompressed_bytes"],
    )
    hourly, summary = _parse_hourly(json.loads(raw))
    raw_path = output_root / "raw/nwis_iv.json"
    hourly_path = output_root / "values/hourly_discharge.csv"
    report = {
        **plan,
        "mode": "acquired",
        "status": "pass_public_boundary_history_acquired",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {**retrieval, **_artifact(raw_path, raw)},
        "hourly_observations": _artifact(hourly_path, hourly),
        "summary": summary,
        "semantics": {
            "archive_revised": True,
            "operational_vintage_verified": False,
            "observation_publication_lag_seconds_for_diagnostic": 3600,
            "publication_lag_evidence_level": "derived",
            "missing_values_imputed": False,
        },
        "claim_boundary": {
            "request_plan_only": False,
            "public_data_without_user_supplied_data": True,
            "boundary_history_available": True,
            "operational_vintage_verified": False,
            "boundary_transition_fitted": False,
            "geospatial_kernel_validated": False,
        },
    }
    return raw, hourly, report


def _parse_hourly(payload: Mapping[str, Any]) -> tuple[bytes, dict[str, Any]]:
    series = (payload.get("value") or {}).get("timeSeries") or []
    if len(series) != 1:
        raise ValueError("boundary_history_single_series_required")
    row = series[0]
    variable = row.get("variable") or {}
    codes = {
        str(value.get("value")) for value in variable.get("variableCode") or []
    }
    site_codes = {
        str(value.get("value"))
        for value in (row.get("sourceInfo") or {}).get("siteCode") or []
    }
    if (
        PARAMETER_CODE not in codes
        or SITE_ID not in site_codes
        or (variable.get("unit") or {}).get("unitCode") != "ft3/s"
    ):
        raise ValueError("boundary_history_identity_or_unit_invalid")
    groups = row.get("values") or []
    if len(groups) != 1:
        raise ValueError("boundary_history_single_value_group_required")
    no_data = float(variable.get("noDataValue", -999999.0))
    samples: list[tuple[datetime, float]] = []
    seen: set[datetime] = set()
    for sample in groups[0].get("value") or []:
        timestamp = _parse_utc(sample["dateTime"])
        value = float(sample["value"])
        if not START <= timestamp <= END or value == no_data:
            continue
        if timestamp in seen:
            raise ValueError("boundary_history_duplicate_timestamp")
        seen.add(timestamp)
        if set(str(value) for value in sample.get("qualifiers") or ()) != {"A"}:
            raise ValueError("boundary_history_unapproved_sample")
        samples.append((timestamp, value * FT3S_TO_M3S))
    samples.sort()
    deltas = [
        int((second[0] - first[0]).total_seconds())
        for first, second in zip(samples, samples[1:])
    ]
    cadence = math.gcd(*deltas)
    if cadence != 1800:
        raise ValueError("boundary_history_native_cadence_invalid")
    by_end: dict[datetime, list[float]] = {}
    for timestamp, value in samples:
        if timestamp <= START:
            continue
        support_end = timestamp.replace(minute=0, second=0, microsecond=0)
        if timestamp.minute or timestamp.second or timestamp.microsecond:
            support_end += timedelta(hours=1)
        if START < support_end <= END:
            by_end.setdefault(support_end, []).append(value)
    if any(len(values) > 2 for values in by_end.values()):
        raise ValueError("boundary_history_excess_samples_per_hour")

    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(
        [
            "support_start_utc",
            "support_end_utc",
            "usgs_03424730_discharge_m3s",
            "native_sample_count",
            "qualifier",
        ]
    )
    complete_fit = 0
    complete_holdout = 0
    total_hours = int((END - START).total_seconds() // 3600)
    for index in range(total_hours):
        support_start = START + timedelta(hours=index)
        support_end = support_start + timedelta(hours=1)
        values = by_end.get(support_end, [])
        complete = len(values) == 2
        if complete and support_end <= FIT_END:
            complete_fit += 1
        elif complete:
            complete_holdout += 1
        writer.writerow(
            [
                _iso(support_start),
                _iso(support_end),
                format(sum(values) / 2.0, ".12g") if complete else "",
                len(values),
                "A" if complete else "",
            ]
        )
    return stream.getvalue().encode("utf-8"), {
        "native_sample_count": len(samples),
        "native_cadence_seconds": cadence,
        "total_hour_count": total_hours,
        "complete_fit_hour_count": complete_fit,
        "complete_holdout_hour_count": complete_holdout,
        "missing_hour_count": total_hours - complete_fit - complete_holdout,
    }


def _fetch(
    url: str,
    *,
    proxy: str,
    timeout_seconds: float,
    retries: int,
    maximum_bytes: int,
) -> tuple[bytes, dict[str, Any]]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        raise ValueError("boundary_history_url_outside_allowlist")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    )
    error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "User-Agent": "gisdataagent-smith-fork-boundary-history/0.1",
            },
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                final = urllib.parse.urlparse(response.geturl())
                if final.scheme != "https" or final.hostname != ALLOWED_HOST:
                    raise ValueError("boundary_history_redirect_outside_allowlist")
                encoded = response.read(maximum_bytes + 1)
                body = (
                    gzip.decompress(encoded)
                    if response.headers.get("Content-Encoding") == "gzip"
                    else encoded
                )
                if not body or len(body) > maximum_bytes:
                    raise ValueError("boundary_history_response_size_invalid")
                json.loads(body)
                return body, {
                    "url": url,
                    "final_url": response.geturl(),
                    "http_status": response.status,
                    "content_type": response.headers.get("Content-Type"),
                    "content_encoding": response.headers.get("Content-Encoding"),
                    "attempt_count": attempt,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                raise RuntimeError(f"boundary_history_http:{exc.code}") from exc
            error = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            error = exc
        if attempt < retries:
            time.sleep(float(attempt))
    raise RuntimeError(f"boundary_history_request_failed:{error}")


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": _display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("boundary_history_timezone_required")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_body(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("boundary_history_positive_request_limits_required")
    if args.plan_only:
        report = compile_plan()
    else:
        if args.output.exists() or args.report.exists():
            raise ValueError("boundary_history_refuses_overwrite")
        raw, hourly, report = acquire(
            output_root=args.output,
            proxy=args.proxy,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
        )
        raw_path = args.output / "raw/nwis_iv.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw)
        hourly_path = args.output / "values/hourly_discharge.csv"
        hourly_path.parent.mkdir(parents=True, exist_ok=True)
        hourly_path.write_bytes(hourly)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(_json_body(report))
    print(args.report)
    print(report["status"])
    if not args.plan_only:
        print(f"complete_fit_hours={report['summary']['complete_fit_hour_count']}")
        print(
            "complete_holdout_hours="
            f"{report['summary']['complete_holdout_hour_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
