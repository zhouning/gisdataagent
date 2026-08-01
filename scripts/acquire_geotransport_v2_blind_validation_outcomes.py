#!/usr/bin/env python3
"""Acquire both USGS outcomes only after the joint prediction seal exists."""

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
from urllib.parse import urlencode

if __package__:
    from scripts.acquire_geotransport_center_hill_v2_d3_inputs import _opener
    from scripts.freeze_geotransport_v2_blind_validation_protocol import (
        END,
        HOUR_COUNT,
        SCHEMA as PROTOCOL_SCHEMA,
        START,
    )
    from scripts.run_geotransport_v2_blind_validation_outcome_free import (
        SCHEMA as ROLLOUT_SCHEMA,
    )
else:
    from acquire_geotransport_center_hill_v2_d3_inputs import _opener
    from freeze_geotransport_v2_blind_validation_protocol import (
        END,
        HOUR_COUNT,
        SCHEMA as PROTOCOL_SCHEMA,
        START,
    )
    from run_geotransport_v2_blind_validation_outcome_free import (
        SCHEMA as ROLLOUT_SCHEMA,
    )

from data_agent.uwm.geospatial_kernel_v2 import (
    DEFAULT_REGISTRY_PATH,
    load_public_data_registry,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geotransport_v2_blind_validation_protocol.json"
)
DEFAULT_ROLLOUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geotransport_v2_blind_validation_rollout_report.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/geotransport_v2_blind_validation/outcomes"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geotransport_v2_blind_validation_outcomes_report.json"
)
SCHEMA = "gwm.geotransport.v2_blind_validation_outcomes.v1"
SYSTEM_IDS = ("center_hill", "j_percy_priest")
ALLOWED_USGS_HOSTS = {
    "waterservices.usgs.gov",
    "nwis.waterservices.usgs.gov",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--rollout", type=Path, default=DEFAULT_ROLLOUT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=4)
    return parser.parse_args()


def acquire(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    rollout_path: Path = DEFAULT_ROLLOUT,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    output_root: Path = DEFAULT_OUTPUT,
    proxy: str = "http://127.0.0.1:7897",
    timeout_seconds: float = 180.0,
    retries: int = 4,
) -> tuple[dict[str, bytes], dict[str, bytes], dict[str, Any]]:
    protocol_body, protocol = _load_json(protocol_path)
    rollout_body, rollout = _load_json(rollout_path)
    if (
        protocol.get("schema") != PROTOCOL_SCHEMA
        or rollout.get("schema") != ROLLOUT_SCHEMA
        or rollout.get("status") != "joint_outcome_free_predictions_sealed"
        or rollout.get("input_artifacts", {}).get("protocol", {}).get("sha256")
        != hashlib.sha256(protocol_body).hexdigest()
        or (rollout.get("joint_seal") or {}).get("all_predictions_present")
        is not True
        or (rollout.get("joint_seal") or {}).get("all_invariants_passed")
        is not True
        or (rollout.get("data_isolation") or {}).get("outcome_values_loaded")
        is not False
    ):
        raise ValueError("blind_validation_outcome_joint_seal_invalid")
    for system_id in SYSTEM_IDS:
        _read_verified(rollout["systems"][system_id]["prediction_artifact"])
    registry = load_public_data_registry(registry_path)
    registry_systems = {
        row["system_id"]: row for row in registry.payload["systems"]
    }
    support_starts = tuple(
        START - timedelta(hours=1) + timedelta(hours=index)
        for index in range(HOUR_COUNT + 1)
    )
    support_ends = tuple(value + timedelta(hours=1) for value in support_starts)
    opener = _opener(proxy)
    raw_bodies: dict[str, bytes] = {}
    csv_bodies: dict[str, bytes] = {}
    system_reports: dict[str, dict[str, Any]] = {}
    for system_id in SYSTEM_IDS:
        lock = protocol["systems"][system_id]["outcome"]
        query = urlencode(
            {
                "format": "json",
                "sites": lock["site_id"],
                "parameterCd": lock["parameter_code"],
                "startDT": lock["request_start"],
                "endDT": lock["request_end"],
                "siteStatus": "all",
            }
        )
        url = f"https://waterservices.usgs.gov/nwis/iv/?{query}"
        body, retrieval = _fetch_usgs(
            url,
            opener=opener,
            timeout_seconds=timeout_seconds,
            retries=retries,
            maximum_bytes=5_000_000,
        )
        outcomes, qualifiers, counts, cadence = _parse_usgs_native_hourly(
            json.loads(body),
            system=registry_systems[system_id],
            support_starts=support_starts,
            support_ends=support_ends,
        )
        prior = outcomes[START]
        if prior is None:
            raise ValueError(
                f"blind_validation_{system_id}_persistence_prior_missing"
            )
        csv_body = _outcome_csv(support_ends, outcomes)
        raw_bodies[system_id] = body
        csv_bodies[system_id] = csv_body
        target_values = [outcomes[value] for value in support_ends[1:]]
        system_reports[system_id] = {
            "system_id": system_id,
            "site_id": lock["site_id"],
            "parameter_code": lock["parameter_code"],
            "variable_role": "independent_observation",
            "source": retrieval,
            "raw_outcome": {
                "path": _display(output_root / f"raw/{system_id}.json"),
                "sha256": hashlib.sha256(body).hexdigest(),
                "size_bytes": len(body),
            },
            "outcome_values": {
                "path": _display(output_root / f"values/{system_id}.csv"),
                "sha256": hashlib.sha256(csv_body).hexdigest(),
                "size_bytes": len(csv_body),
            },
            "prior_observation_support_end_utc": _iso(START),
            "prior_observation_m3s": float(prior),
            "quality": {
                "target_hour_count": HOUR_COUNT,
                "native_sample_cadence_seconds": cadence,
                "expected_native_samples_per_complete_hour": 3600 // cadence,
                "target_complete_hour_count": sum(
                    value is not None for value in target_values
                ),
                "target_missing_hour_count": sum(
                    value is None for value in target_values
                ),
                "all_support_complete_hour_count": sum(
                    value is not None for value in outcomes.values()
                ),
                "qualifiers": sorted(
                    {value for value in qualifiers.values() if value}
                ),
                "sample_counts": sorted(set(counts.values())),
                "missing_values_imputed": False,
            },
        }
    report = {
        "schema": SCHEMA,
        "status": "two_system_outcomes_acquired_after_joint_seal",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "start_inclusive": _iso(START),
            "end_exclusive": _iso(END),
            "hour_count": HOUR_COUNT,
        },
        "sealed_artifacts": {
            "protocol": _artifact(protocol_path, protocol_body),
            "rollout_report": _artifact(rollout_path, rollout_body),
            "joint_seal_sha256": rollout["joint_seal"]["sha256"],
            "predictions": {
                system_id: rollout["systems"][system_id]["prediction_artifact"]
                for system_id in SYSTEM_IDS
            },
        },
        "systems": system_reports,
        "ordering_audit": {
            "both_predictions_verified_before_first_outcome_request": True,
            "joint_seal_verified_before_first_outcome_request": True,
            "prediction_files_modified_after_outcome_access": False,
            "outcome_access_phase_compliant": True,
        },
        "claim_boundary": {
            "outcomes_acquired": True,
            "outcome_values_imputed": False,
            "predictions_scored": False,
            "predictive_validation_complete": False,
            "geospatial_kernel_validated": False,
        },
    }
    return raw_bodies, csv_bodies, report


def _parse_usgs_native_hourly(
    payload: Mapping[str, Any],
    *,
    system: Mapping[str, Any],
    support_starts: tuple[datetime, ...],
    support_ends: tuple[datetime, ...],
) -> tuple[
    dict[datetime, float | None],
    dict[datetime, str],
    dict[datetime, int],
    int,
]:
    series = (payload.get("value") or {}).get("timeSeries") or []
    if len(series) != 1:
        raise ValueError("blind_validation_usgs_single_series_required")
    row = series[0]
    site_codes = {
        value.get("value")
        for value in (row.get("sourceInfo") or {}).get("siteCode") or []
    }
    variable = row.get("variable") or {}
    variable_codes = {
        value.get("value") for value in variable.get("variableCode") or []
    }
    if (
        system["outcome"]["site_id"] not in site_codes
        or system["outcome"]["parameter_code"] not in variable_codes
        or (variable.get("unit") or {}).get("unitCode") != "ft3/s"
    ):
        raise ValueError("blind_validation_usgs_identity_or_unit_mismatch")
    groups = row.get("values") or []
    if len(groups) != 1:
        raise ValueError("blind_validation_usgs_single_value_group_required")
    parsed_samples: list[tuple[datetime, float, tuple[str, ...]]] = []
    seen: set[datetime] = set()
    no_data = float(variable.get("noDataValue", -999999.0))
    for sample in groups[0].get("value") or []:
        timestamp = _parse_utc(sample["dateTime"])
        if not support_starts[0] < timestamp <= support_ends[-1]:
            continue
        if timestamp in seen:
            raise ValueError("blind_validation_usgs_duplicate_timestamp")
        seen.add(timestamp)
        value = float(sample["value"])
        if value == no_data:
            continue
        parsed_samples.append(
            (timestamp, value * 0.028316846592, tuple(sample.get("qualifiers") or ()))
        )
    timestamps = [value[0] for value in parsed_samples]
    if len(timestamps) < 2:
        raise ValueError("blind_validation_usgs_insufficient_samples")
    deltas = [
        int((second - first).total_seconds())
        for first, second in zip(timestamps, timestamps[1:])
        if second > first
    ]
    cadence = math.gcd(*deltas)
    if cadence < 300 or cadence > 3600 or 3600 % cadence != 0:
        raise ValueError("blind_validation_usgs_native_cadence_invalid")
    expected_count = 3600 // cadence
    samples: dict[datetime, list[float]] = {value: [] for value in support_ends}
    qualifiers: dict[datetime, set[str]] = {value: set() for value in support_ends}
    for timestamp, value, labels in parsed_samples:
        seconds_from_hour = timestamp.minute * 60 + timestamp.second
        if seconds_from_hour % cadence != 0 or timestamp.microsecond != 0:
            raise ValueError("blind_validation_usgs_sample_off_native_cadence")
        support_end = timestamp.replace(minute=0, second=0, microsecond=0)
        if seconds_from_hour > 0:
            support_end += timedelta(hours=1)
        samples[support_end].append(value)
        qualifiers[support_end].update(labels)
    if any(len(values) > expected_count for values in samples.values()):
        raise ValueError("blind_validation_usgs_excess_samples_per_hour")
    if any(values and qualifiers[key] != {"A"} for key, values in samples.items()):
        raise ValueError("blind_validation_usgs_returned_sample_not_approved")
    outcomes = {
        key: float(sum(values) / len(values))
        if len(values) == expected_count
        else None
        for key, values in samples.items()
    }
    qualifier_labels = {
        key: "A" if qualifiers[key] == {"A"} else "" for key in support_ends
    }
    counts = {key: len(samples[key]) for key in support_ends}
    return outcomes, qualifier_labels, counts, cadence


def _outcome_csv(
    support_ends: tuple[datetime, ...], outcomes: Mapping[datetime, float | None]
) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(
        [
            "support_end_utc",
            "observed_discharge_m3s",
            "source_role",
            "evaluation_role",
        ]
    )
    for index, support_end in enumerate(support_ends):
        value = outcomes[support_end]
        writer.writerow(
            [
                _iso(support_end),
                "" if value is None else format(value, ".10g"),
                "independent_observation",
                "persistence_prior" if index == 0 else "target",
            ]
        )
    return stream.getvalue().encode("utf-8")


def _fetch_usgs(
    url: str,
    *,
    opener: urllib.request.OpenerDirector,
    timeout_seconds: float,
    retries: int,
    maximum_bytes: int,
) -> tuple[bytes, dict[str, Any]]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_USGS_HOSTS:
        raise ValueError("blind_validation_usgs_url_outside_allowlist")
    error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "gisdataagent-geotransport-v2-blind-outcomes/0.1",
            },
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                final_url = response.geturl()
                final = urllib.parse.urlparse(final_url)
                if (
                    final.scheme != "https"
                    or final.hostname not in ALLOWED_USGS_HOSTS
                ):
                    raise ValueError(
                        "blind_validation_usgs_redirect_outside_allowlist"
                    )
                body = response.read(maximum_bytes + 1)
                if len(body) > maximum_bytes:
                    raise ValueError(
                        "blind_validation_usgs_response_size_limit_exceeded"
                    )
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
                    f"blind_validation_usgs_nonretryable_http:{exc.code}"
                ) from exc
            error = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            error = exc
        if attempt < retries:
            time.sleep(float(attempt))
    raise RuntimeError(f"blind_validation_usgs_request_failed:{error}")


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("blind_validation_outcome_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("blind_validation_outcome_artifact_identity_mismatch")
    return body


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    return body, json.loads(body)


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


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("blind_validation_outcome_timezone_required")
    return parsed.astimezone(timezone.utc)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    if args.output.exists() or args.report.exists():
        raise ValueError("blind_validation_outcomes_already_acquired")
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("blind_validation_positive_outcome_request_limits_required")
    raw, values, report = acquire(
        protocol_path=args.protocol,
        rollout_path=args.rollout,
        registry_path=args.registry,
        output_root=args.output,
        proxy=args.proxy,
        timeout_seconds=args.timeout_seconds,
        retries=args.retries,
    )
    for system_id in SYSTEM_IDS:
        raw_path = args.output / f"raw/{system_id}.json"
        value_path = args.output / f"values/{system_id}.csv"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        value_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw[system_id])
        value_path.write_bytes(values[system_id])
    _write_json(args.report, report)
    print(args.report)
    for system_id in SYSTEM_IDS:
        quality = report["systems"][system_id]["quality"]
        print(
            f"{system_id}_complete_target_hours="
            f"{quality['target_complete_hour_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
