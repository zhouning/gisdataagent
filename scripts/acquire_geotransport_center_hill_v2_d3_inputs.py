#!/usr/bin/env python3
"""Acquire Center Hill D3 inputs in sealed input and outcome phases."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Mapping
import urllib.error
import urllib.parse
import urllib.request

from data_agent.uwm.geospatial_kernel_v2 import (
    DEFAULT_REGISTRY_PATH,
    build_nwm_q_lateral_plan,
    extract_nwm_q_lateral,
    load_nwm_zarr_schema,
    load_public_data_registry,
    nwm_chunk_url,
)
if __package__:
    from scripts.build_geotransport_center_hill_672h_development_panel import (
        _parse_usgs_with_gaps,
    )
    from scripts.build_geotransport_center_hill_smoke_panel import (
        _parse_cwms_hourly,
    )
    from scripts.run_geotransport_center_hill_v2_outcome_free import compile_domain
else:
    from build_geotransport_center_hill_672h_development_panel import (
        _parse_usgs_with_gaps,
    )
    from build_geotransport_center_hill_smoke_panel import _parse_cwms_hourly
    from run_geotransport_center_hill_v2_outcome_free import compile_domain


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_v2_d3_protocol.json"
)
DEFAULT_METADATA_ROOT = REPO_ROOT / "data/geotransport_v0_1/metadata"
DEFAULT_INPUT_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d3_inputs"
)
DEFAULT_ROLLOUT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_v2_d3_rollout_report.json"
)
ACTION_SCHEMA = "gwm.geotransport.center_hill_v2_action_input.v1"
FORCING_SCHEMA = "gwm.geotransport.center_hill_v2_nwm_input.v1"
OUTCOME_SCHEMA = "gwm.geotransport.center_hill_v2_outcome_input.v1"
PROTOCOL_SCHEMA = "gwm.geotransport.center_hill_v2_d3_protocol.v1"
ROLLOUT_SCHEMA = "gwm.geotransport.center_hill_v2_outcome_free_rollout.v1"
START = datetime(2022, 2, 3, 1, tzinfo=timezone.utc)
END = datetime(2022, 3, 3, 1, tzinfo=timezone.utc)
HOUR_COUNT = 672
ALLOWED_HOSTS = {
    "cwms-data.usace.army.mil",
    "noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com",
    "waterservices.usgs.gov",
}
USER_AGENT = "gisdataagent-center-hill-v2-d3/0.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("inputs", "outcome"), required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--metadata-root", type=Path, default=DEFAULT_METADATA_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument(
        "--rollout-report", type=Path, default=DEFAULT_ROLLOUT_REPORT
    )
    parser.add_argument("--proxy", default="")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def acquire_inputs(args: argparse.Namespace) -> tuple[Path, Path]:
    protocol_body, protocol = _load_protocol(args.protocol)
    registry = load_public_data_registry(args.registry)
    system = next(
        row for row in registry.payload["systems"] if row["system_id"] == "center_hill"
    )
    schema = load_nwm_zarr_schema(args.metadata_root)
    plan = build_nwm_q_lateral_plan(
        registry,
        schema,
        system_id="center_hill",
        start=_iso(START),
        end=_iso(END),
    )
    if (
        plan.time_count != HOUR_COUNT
        or plan.time_chunk_indices != (561,)
        or plan.feature_chunk_indices != (63,)
        or plan.q_chunk_keys != ((561, 63),)
    ):
        raise ValueError("center_hill_v2_d3_nwm_plan_mismatch")
    opener = _opener(args.proxy)
    action_spec = protocol["input_acquisition"]["action"]
    action_raw, action_retrieval = _fetch(
        action_spec["url"], opener=opener, timeout=args.timeout_seconds,
        retries=args.retries, maximum_bytes=2_000_000,
    )
    time_url = nwm_chunk_url("time", "561")
    q_url = nwm_chunk_url("q_lateral", "561.63")
    time_raw, time_retrieval = _fetch(
        time_url, opener=opener, timeout=args.timeout_seconds,
        retries=args.retries, maximum_bytes=1_000_000,
    )
    q_raw, q_retrieval = _fetch(
        q_url, opener=opener, timeout=args.timeout_seconds,
        retries=args.retries, maximum_bytes=100_000_000,
    )

    action_raw_path = args.output / "action/raw/cwms_action.json"
    time_raw_path = args.output / "nwm/raw/time/561.zst"
    q_raw_path = args.output / "nwm/raw/q_lateral/561.63.zst"
    _write_bytes(action_raw_path, action_raw)
    _write_bytes(time_raw_path, time_raw)
    _write_bytes(q_raw_path, q_raw)

    support_starts = tuple(START + timedelta(hours=index) for index in range(HOUR_COUNT))
    support_ends = tuple(value + timedelta(hours=1) for value in support_starts)
    action_values, action_quality = _parse_cwms_hourly(
        json.loads(action_raw),
        field=system["action"],
        expected_timestamps=support_ends,
    )
    action_value_path = args.output / "action/action_values.csv"
    _write_action_values(
        action_value_path,
        support_starts=support_starts,
        support_ends=support_ends,
        values=action_values,
    )
    q_result = extract_nwm_q_lateral(
        plan,
        schema,
        time_chunks={561: time_raw},
        q_chunks={(561, 63): q_raw},
    )
    if q_result.fill_value_count != 0:
        raise ValueError("center_hill_v2_d3_q_lateral_fill_values_present")
    domain, _ = compile_domain()
    active_feature_ids = domain.geometry.feature_ids
    q_value_path = args.output / "nwm/q_lateral_values.csv"
    _write_q_values(q_value_path, q_result, active_feature_ids=active_feature_ids)

    action_manifest = {
        "schema": ACTION_SCHEMA,
        "variable_role": "boundary_action",
        "outcome_included": False,
        "window": _window(),
        "protocol": _artifact(args.protocol, protocol_body),
        "source": {
            **action_retrieval,
            "timeseries": action_spec["timeseries"],
            "office": action_spec["office"],
            "unit": action_spec["unit"],
            "support_kind": action_spec["support_kind"],
            "timestamp_position": action_spec["timestamp_position"],
        },
        "raw_action": _artifact(action_raw_path, action_raw),
        "action_values": _artifact(action_value_path, action_value_path.read_bytes()),
        "quality_codes": sorted(set(action_quality.values())),
        "result": {"hour_count": len(action_values), "missing_value_count": 0},
    }
    forcing_manifest = {
        "schema": FORCING_SCHEMA,
        "variable_role": "modeled_forcing",
        "ground_truth": False,
        "window": _window(),
        "protocol": _artifact(args.protocol, protocol_body),
        "time_chunk_indices": [561],
        "feature_chunk_indices": [63],
        "feature_ids": list(active_feature_ids),
        "raw_artifacts": {
            "time": {**time_retrieval, **_artifact(time_raw_path, time_raw)},
            "q_lateral": {**q_retrieval, **_artifact(q_raw_path, q_raw)},
        },
        "q_lateral_values": _artifact(q_value_path, q_value_path.read_bytes()),
        "result": {
            "time_count": len(q_result.timestamps),
            "feature_count": len(active_feature_ids),
            "source_feature_count": len(q_result.feature_ids),
            "value_count": len(q_result.timestamps) * len(active_feature_ids),
            "fill_value_count": q_result.fill_value_count,
        },
    }
    action_manifest_path = args.output / "action/acquisition_manifest.json"
    forcing_manifest_path = args.output / "nwm/acquisition_manifest.json"
    _write_json(action_manifest_path, action_manifest)
    _write_json(forcing_manifest_path, forcing_manifest)
    return action_manifest_path, forcing_manifest_path


def acquire_outcome(args: argparse.Namespace) -> Path:
    protocol_body, protocol = _load_protocol(args.protocol)
    rollout_body = args.rollout_report.read_bytes()
    rollout = json.loads(rollout_body)
    if (
        rollout.get("schema") != ROLLOUT_SCHEMA
        or rollout.get("status") != "outcome_free_rollout_complete"
        or (rollout.get("data_isolation") or {}).get("outcome_values_loaded") is not False
    ):
        raise ValueError("center_hill_v2_d3_rollout_must_be_sealed_before_outcome")
    prediction = rollout.get("prediction_artifact") or {}
    _read_verified(prediction)
    registry = load_public_data_registry(args.registry)
    system = next(
        row for row in registry.payload["systems"] if row["system_id"] == "center_hill"
    )
    outcome_spec = protocol["input_acquisition"]["outcome"]
    query = urllib.parse.urlencode(
        {
            "format": "json",
            "sites": outcome_spec["site_id"],
            "parameterCd": outcome_spec["parameter_code"],
            "startDT": outcome_spec["request_start"],
            "endDT": outcome_spec["request_end"],
            "siteStatus": "all",
        }
    )
    url = f"https://waterservices.usgs.gov/nwis/iv/?{query}"
    body, retrieval = _fetch(
        url, opener=_opener(args.proxy), timeout=args.timeout_seconds,
        retries=args.retries, maximum_bytes=5_000_000,
    )
    raw_path = args.output / "outcome/raw/usgs_iv.json"
    _write_bytes(raw_path, body)
    support_starts = tuple(
        START - timedelta(hours=1) + timedelta(hours=index)
        for index in range(HOUR_COUNT + 1)
    )
    support_ends = tuple(value + timedelta(hours=1) for value in support_starts)
    outcomes, qualifiers, counts = _parse_usgs_with_gaps(
        json.loads(body),
        system=system,
        support_starts=support_starts,
        support_ends=support_ends,
    )
    prior = outcomes[START]
    if prior is None:
        raise ValueError("center_hill_v2_d3_prior_observation_missing")
    value_path = args.output / "outcome/outcome_values.csv"
    _write_outcomes(
        value_path,
        support_ends=support_ends[1:],
        outcomes=outcomes,
    )
    manifest = {
        "schema": OUTCOME_SCHEMA,
        "variable_role": "independent_observation",
        "site_id": "USGS-03424860",
        "parameter_code": "00060",
        "window": _window(),
        "protocol": _artifact(args.protocol, protocol_body),
        "sealed_rollout_report": _artifact(args.rollout_report, rollout_body),
        "sealed_predictions": prediction,
        "source": retrieval,
        "raw_outcome": _artifact(raw_path, body),
        "outcome_values": _artifact(value_path, value_path.read_bytes()),
        "prior_observation_support_end_utc": _iso(START),
        "prior_observation_m3s": prior,
        "quality": {
            "complete_hour_count": sum(value is not None for value in outcomes.values()),
            "missing_hour_count": sum(value is None for value in outcomes.values()),
            "qualifiers": sorted(set(value for value in qualifiers.values() if value)),
            "sample_counts": sorted(set(counts.values())),
            "missing_values_imputed": False,
        },
    }
    manifest_path = args.output / "outcome/acquisition_manifest.json"
    _write_json(manifest_path, manifest)
    return manifest_path


def _load_protocol(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    protocol = json.loads(body)
    if (
        protocol.get("schema") != PROTOCOL_SCHEMA
        or protocol.get("status") != "frozen_before_d3_value_access"
        or (protocol.get("data_isolation_at_freeze") or {}).get("chunk_561_loaded") is not False
        or (protocol.get("claim_boundary_before_execution") or {}).get("d3_protocol_frozen") is not True
    ):
        raise ValueError("center_hill_v2_d3_protocol_invalid")
    return body, protocol


def _fetch(
    url: str,
    *,
    opener: urllib.request.OpenerDirector,
    timeout: float,
    retries: int,
    maximum_bytes: int,
) -> tuple[bytes, dict[str, Any]]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("center_hill_v2_d3_url_outside_allowlist")
    error: Exception | None = None
    for attempt in range(1, retries + 1):
        accept = (
            "application/json;version=2"
            if parsed.hostname == "cwms-data.usace.army.mil"
            else (
                "application/octet-stream"
                if parsed.hostname
                == "noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com"
                else "application/json"
            )
        )
        request = urllib.request.Request(
            url,
            headers={"Accept": accept, "User-Agent": USER_AGENT},
        )
        try:
            with opener.open(request, timeout=timeout) as response:
                final = urllib.parse.urlparse(response.geturl())
                if final.scheme != "https" or final.hostname not in ALLOWED_HOSTS:
                    raise ValueError("center_hill_v2_d3_redirect_outside_allowlist")
                body = response.read(maximum_bytes + 1)
                if len(body) > maximum_bytes:
                    raise ValueError("center_hill_v2_d3_object_size_limit_exceeded")
                return body, {
                    "url": url,
                    "http_status": response.status,
                    "content_type": response.headers.get("Content-Type"),
                    "attempt_count": attempt,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                raise RuntimeError(f"center_hill_v2_d3_nonretryable_http:{exc.code}") from exc
            error = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            error = exc
        if attempt < retries:
            time.sleep(float(attempt))
    raise RuntimeError(f"center_hill_v2_d3_request_failed:{error}")


def _opener(proxy: str) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(*handlers)


def _write_action_values(
    path: Path,
    *,
    support_starts: tuple[datetime, ...],
    support_ends: tuple[datetime, ...],
    values: Mapping[datetime, float],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "support_start_utc", "support_end_utc", "action_release_m3s", "source_role"
        ])
        for start, end in zip(support_starts, support_ends, strict=True):
            writer.writerow([_iso(start), _iso(end), format(values[end], ".10g"), "boundary_action"])


def _write_q_values(
    path: Path, result: Any, *, active_feature_ids: tuple[int, ...]
) -> None:
    source_index = {
        feature_id: index for index, feature_id in enumerate(result.feature_ids)
    }
    if any(feature_id not in source_index for feature_id in active_feature_ids):
        raise ValueError("center_hill_v2_d3_active_q_lateral_feature_missing")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp_utc", "feature_id", "q_lateral_m3s", "source_role"])
        for row, timestamp in enumerate(result.timestamps):
            for feature_id in active_feature_ids:
                column = source_index[feature_id]
                value = float(result.values_m3s[row, column])
                writer.writerow([
                    timestamp, feature_id, "" if math.isnan(value) else format(value, ".10g"), result.variable_role
                ])


def _write_outcomes(
    path: Path,
    *,
    support_ends: tuple[datetime, ...],
    outcomes: Mapping[datetime, float | None],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["support_end_utc", "observed_discharge_m3s", "source_role"])
        for support_end in support_ends:
            value = outcomes[support_end]
            writer.writerow([
                _iso(support_end), "" if value is None else format(value, ".10g"), "independent_observation"
            ])


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("center_hill_v2_d3_artifact_outside_repository") from exc
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != descriptor.get("sha256") or len(body) != descriptor.get("size_bytes"):
        raise ValueError("center_hill_v2_d3_artifact_identity_mismatch")
    return body


def _window() -> dict[str, Any]:
    return {
        "start_inclusive": _iso(START),
        "end_exclusive": _iso(END),
        "time_step": "PT1H",
        "hour_count": HOUR_COUNT,
    }


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


def _write_bytes(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("center_hill_v2_d3_positive_request_limits_required")
    if args.phase == "inputs":
        paths = acquire_inputs(args)
        print("\n".join(str(path) for path in paths))
    else:
        print(acquire_outcome(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
