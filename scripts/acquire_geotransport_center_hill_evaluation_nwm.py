#!/usr/bin/env python3
"""Acquire the three NWM objects frozen by the Center Hill holdout protocol."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
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
    extract_nwm_velocity,
    load_nwm_velocity_schema,
    load_public_data_registry,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_temporal_holdout_protocol_v1.json"
)
DEFAULT_METADATA_ROOT = REPO_ROOT / "data/geotransport_v0_1/metadata"
DEFAULT_OUTPUT = REPO_ROOT / "data/geotransport_v0_1/center_hill_evaluation/nwm"
SCHEMA = "gwm.geotransport.center_hill_evaluation_nwm.v1"
ALLOWED_HOST = "noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com"
USER_AGENT = "gisdataagent-center-hill-frozen-evaluation-nwm/0.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--metadata-root", type=Path, default=DEFAULT_METADATA_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--accept-modeled-inputs", action="store_true")
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def compile_plan(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    metadata_root: Path = DEFAULT_METADATA_ROOT,
    values_mode: bool = False,
) -> tuple[dict[str, Any], Any, Any]:
    protocol_body = protocol_path.read_bytes()
    protocol = json.loads(protocol_body)
    _validate_protocol(protocol)
    registry = load_public_data_registry(registry_path)
    velocity_schema = load_nwm_velocity_schema(metadata_root)
    split = protocol["temporal_split"]
    nwm_plan = build_nwm_q_lateral_plan(
        registry,
        velocity_schema.base,
        system_id="center_hill",
        start=split["acquisition_start_inclusive"],
        end=split["end_exclusive"],
    )
    if (
        nwm_plan.time_chunk_indices != (560,)
        or nwm_plan.q_chunk_keys != ((560, 63),)
        or nwm_plan.time_count != 672
    ):
        raise ValueError("evaluation_nwm_plan_mismatch")
    acquisition = protocol["nwm_acquisition"]
    requests = [
        {
            "variable": "time",
            "key": "560",
            "url": acquisition["required_urls"]["time"],
            "maximum_bytes": acquisition["maximum_time_chunk_bytes"],
        },
        {
            "variable": "q_lateral",
            "key": "560.63",
            "url": acquisition["required_urls"]["q_lateral"],
            "maximum_bytes": acquisition["maximum_q_lateral_chunk_bytes"],
        },
        {
            "variable": "velocity",
            "key": "560.63",
            "url": acquisition["required_urls"]["velocity"],
            "maximum_bytes": acquisition["maximum_velocity_chunk_bytes"],
        },
    ]
    if len(requests) != acquisition["maximum_object_count"]:
        raise ValueError("evaluation_nwm_object_count_mismatch")
    manifest = {
        "schema": SCHEMA,
        "mode": "values" if values_mode else "plan",
        "evaluation_protocol": _artifact(protocol_path, protocol_body),
        "registry": _artifact(registry_path, registry_path.read_bytes()),
        "metadata_root": _display(metadata_root),
        "metadata_sha256": dict(velocity_schema.metadata_sha256),
        "system_id": "center_hill",
        "window": {
            "start_inclusive": split["acquisition_start_inclusive"],
            "end_exclusive": split["end_exclusive"],
            "time_count": nwm_plan.time_count,
        },
        "feature_ids": list(nwm_plan.feature_ids),
        "feature_indices": list(nwm_plan.feature_indices),
        "requests": requests,
        "source_semantics": {
            "q_lateral": {
                "role": "modeled_forcing",
                "ground_truth": False,
                "units": "m3 s-1",
            },
            "velocity": {
                "role": "modeled_state_context",
                "ground_truth": False,
                "units": "m s-1",
                "admitted_as_flood_wave_celerity": False,
            },
        },
        "claim_boundary": {
            "request_plan_only": not values_mode,
            "modeled_inputs_acquired": values_mode,
            "evaluation_outcome_acquired": False,
            "evaluation_scored": False,
            "flood_wave_transport_admitted": False,
            "benchmark_validated": False,
            "geospatial_kernel_validated": False,
        },
    }
    return manifest, nwm_plan, velocity_schema


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("evaluation_nwm_positive_request_limits_required")
    manifest, nwm_plan, velocity_schema = compile_plan(
        protocol_path=args.protocol,
        registry_path=args.registry,
        metadata_root=args.metadata_root,
        values_mode=not args.plan_only,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    if args.plan_only:
        output = args.output / "acquisition_plan.json"
        _write_json(output, manifest)
        print(output)
        return 0
    if not args.accept_modeled_inputs:
        raise ValueError("evaluation_nwm_values_require_accept_modeled_inputs")

    opener = _opener(args.proxy)
    bodies: dict[str, bytes] = {}
    raw_artifacts: list[dict[str, Any]] = []
    for request in manifest["requests"]:
        body, retrieval = _fetch(
            request["url"],
            opener=opener,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            maximum_bytes=request["maximum_bytes"],
        )
        path = args.output / "raw" / request["variable"] / f"{request['key']}.zst"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        bodies[request["variable"]] = body
        raw_artifacts.append(
            {
                **retrieval,
                "variable": request["variable"],
                "key": request["key"],
                **_artifact(path, body),
            }
        )

    q_result = extract_nwm_q_lateral(
        nwm_plan,
        velocity_schema.base,
        time_chunks={560: bodies["time"]},
        q_chunks={(560, 63): bodies["q_lateral"]},
    )
    velocity_result = extract_nwm_velocity(
        nwm_plan,
        velocity_schema,
        time_chunks={560: bodies["time"]},
        velocity_chunks={(560, 63): bodies["velocity"]},
    )
    if q_result.timestamps != velocity_result.timestamps:
        raise ValueError("evaluation_nwm_variable_time_axes_mismatch")
    if q_result.feature_ids != velocity_result.feature_ids:
        raise ValueError("evaluation_nwm_variable_feature_axes_mismatch")

    q_path = args.output / "values/q_lateral.csv"
    velocity_path = args.output / "values/velocity.csv"
    _write_reach_values(
        q_path,
        timestamps=q_result.timestamps,
        feature_ids=q_result.feature_ids,
        values=q_result.values_m3s,
        value_column="q_lateral_m3s",
        source_role=q_result.variable_role,
    )
    _write_reach_values(
        velocity_path,
        timestamps=velocity_result.timestamps,
        feature_ids=velocity_result.feature_ids,
        values=velocity_result.values_ms,
        value_column="velocity_ms",
        source_role=velocity_result.variable_role,
    )
    manifest["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    manifest["raw_artifacts"] = raw_artifacts
    manifest["value_artifacts"] = {
        "q_lateral": _artifact(q_path, q_path.read_bytes()),
        "velocity": _artifact(velocity_path, velocity_path.read_bytes()),
    }
    manifest["result"] = {
        "time_count": len(q_result.timestamps),
        "feature_count": len(q_result.feature_ids),
        "q_lateral_value_count": int(q_result.values_m3s.size),
        "velocity_value_count": int(velocity_result.values_ms.size),
        "q_lateral_fill_value_count": q_result.fill_value_count,
        "velocity_fill_value_count": velocity_result.fill_value_count,
    }
    output = args.output / "acquisition_manifest.json"
    _write_json(output, manifest)
    print(output)
    return 0


def _validate_protocol(protocol: Mapping[str, Any]) -> None:
    split = protocol.get("temporal_split") or {}
    acquisition = protocol.get("nwm_acquisition") or {}
    claims = protocol.get("claim_boundary") or {}
    if (
        protocol.get("schema")
        != "gwm.geotransport.center_hill_temporal_holdout_protocol.v1"
        or protocol.get("status")
        != "frozen_before_evaluation_outcome_acquisition"
        or protocol.get("system_id") != "center_hill"
        or split.get("acquisition_start_inclusive") != "2022-01-06T01:00:00Z"
        or split.get("end_exclusive") != "2022-02-03T01:00:00Z"
        or acquisition.get("time_chunk_indices") != [560]
        or acquisition.get("q_lateral_chunk_keys") != [[560, 63]]
        or claims.get("protocol_frozen_before_evaluation_outcome_acquisition")
        is not True
        or claims.get("evaluation_values_acquired") is not False
    ):
        raise ValueError("evaluation_nwm_frozen_protocol_invalid")


def _write_reach_values(
    path: Path,
    *,
    timestamps: tuple[str, ...],
    feature_ids: tuple[int, ...],
    values: Any,
    value_column: str,
    source_role: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp_utc", "feature_id", value_column, "source_role"])
        for row, timestamp in enumerate(timestamps):
            for column, feature_id in enumerate(feature_ids):
                value = float(values[row, column])
                writer.writerow(
                    [
                        timestamp,
                        feature_id,
                        "" if math.isnan(value) else format(value, ".10g"),
                        source_role,
                    ]
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
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        raise ValueError("evaluation_nwm_url_outside_official_allowlist")
    error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                final = urllib.parse.urlparse(response.geturl())
                if final.scheme != "https" or final.hostname != ALLOWED_HOST:
                    raise ValueError("evaluation_nwm_redirect_outside_official_allowlist")
                body = response.read(maximum_bytes + 1)
                if len(body) > maximum_bytes:
                    raise ValueError("evaluation_nwm_object_size_limit_exceeded")
                return body, {
                    "url": url,
                    "http_status": response.status,
                    "content_type": response.headers.get("Content-Type"),
                    "attempt_count": attempt,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                raise RuntimeError(
                    f"non_retryable_evaluation_nwm_http_error:{exc.code}"
                ) from exc
            error = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            error = exc
        if attempt < retries:
            time.sleep(float(attempt))
    raise RuntimeError(f"evaluation_nwm_request_failed:{error}")


def _opener(proxy: str) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(*handlers)


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


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
