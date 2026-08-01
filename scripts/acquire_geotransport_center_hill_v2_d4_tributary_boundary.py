#!/usr/bin/env python3
"""Acquire outcome-free NWM streamflow at the 19 D4 tributary mouths."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    NwmQlatPlan,
    extract_nwm_streamflow,
    load_nwm_streamflow_schema,
    nwm_chunk_url,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOPOLOGY_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_v2_d4_topology_report.json"
)
DEFAULT_METADATA_ROOT = REPO_ROOT / "data/geotransport_v0_1/metadata"
DEFAULT_TIME_CHUNK = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d3_inputs/nwm/raw/time/561.zst"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d4_tributary_boundary"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_v2_d4_tributary_boundary_report.json"
)
SCHEMA = "gwm.geotransport.center_hill_v2_d4_tributary_boundary.v1"
START = datetime(2022, 2, 3, 1, tzinfo=timezone.utc)
END = datetime(2022, 3, 3, 1, tzinfo=timezone.utc)
HOUR_COUNT = 672
USER_AGENT = "gisdataagent-center-hill-d4-boundary/0.1"
ALLOWED_HOST = "noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--proxy", default="")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument(
        "--topology-report", type=Path, default=DEFAULT_TOPOLOGY_REPORT
    )
    parser.add_argument("--metadata-root", type=Path, default=DEFAULT_METADATA_ROOT)
    parser.add_argument("--time-chunk", type=Path, default=DEFAULT_TIME_CHUNK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_plan(
    *,
    topology_report_path: Path = DEFAULT_TOPOLOGY_REPORT,
    metadata_root: Path = DEFAULT_METADATA_ROOT,
) -> tuple[NwmQlatPlan, dict[str, Any], bytes, dict[str, Any]]:
    topology_body = topology_report_path.read_bytes()
    topology = json.loads(topology_body)
    if (
        topology.get("schema")
        != "gwm.geotransport.center_hill_v2_d4_topology_audit.v1"
        or topology.get("status") != "pass_direct_confluence_boundary_ready"
        or (topology.get("data_isolation") or {}).get("d3_outcome_values_loaded")
        is not False
        or (topology.get("claim_boundary") or {}).get(
            "modeled_tributary_boundary_acquisition_ready"
        )
        is not True
    ):
        raise ValueError("center_hill_d4_topology_report_invalid")
    schema = load_nwm_streamflow_schema(metadata_root)
    rows = topology["nwm_boundary_crosswalk"]["rows"]
    feature_ids = tuple(int(row["tributary_feature_id"]) for row in rows)
    feature_indices = tuple(int(row["nwm_feature_index"]) for row in rows)
    if len(feature_ids) != 19 or len(feature_ids) != len(set(feature_ids)):
        raise ValueError("center_hill_d4_tributary_axis_invalid")
    start_index = int((START - schema.base.time_origin).total_seconds() / 3600.0)
    end_index = int((END - schema.base.time_origin).total_seconds() / 3600.0)
    time_chunks = tuple(
        range(
            start_index // schema.base.time_chunk_size,
            (end_index - 1) // schema.base.time_chunk_size + 1,
        )
    )
    feature_chunks = tuple(
        sorted({index // schema.streamflow_chunks[1] for index in feature_indices})
    )
    if time_chunks != (561,) or feature_chunks != (63, 87):
        raise ValueError("center_hill_d4_streamflow_chunk_plan_mismatch")
    plan = NwmQlatPlan(
        system_id="center_hill_v2_d4_tributary_boundary",
        start=START,
        end=END,
        start_time_index=start_index,
        end_time_index=end_index,
        feature_ids=feature_ids,
        feature_indices=feature_indices,
        time_chunk_indices=time_chunks,
        feature_chunk_indices=feature_chunks,
        q_chunk_keys=tuple(
            (time_chunk, feature_chunk)
            for time_chunk in time_chunks
            for feature_chunk in feature_chunks
        ),
    )
    return plan, topology, topology_body, {
        "schema": SCHEMA,
        "mode": "plan",
        "window": _window(),
        "topology_report": _artifact(topology_report_path),
        "feature_ids": list(feature_ids),
        "feature_indices": list(feature_indices),
        "time_chunk_indices": list(time_chunks),
        "feature_chunk_indices": list(feature_chunks),
        "requests": [
            {
                "variable": "streamflow",
                "chunk_key": f"{time_chunk}.{feature_chunk}",
                "url": nwm_chunk_url(
                    "streamflow", f"{time_chunk}.{feature_chunk}"
                ),
                "maximum_bytes": 100_000_000,
            }
            for time_chunk, feature_chunk in plan.q_chunk_keys
        ],
        "semantic_contract": {
            "variable_role": "modeled_tributary_boundary_flux",
            "modeled": True,
            "ground_truth": False,
            "possible_nudging": True,
            "evaluation_outcome": False,
            "conservation_oracle": False,
        },
        "data_isolation": {
            "outcome_values_loaded": False,
            "d3_window_use": "post_failure_input_flux_diagnostic_only",
        },
    }


def acquire(
    *,
    topology_report_path: Path = DEFAULT_TOPOLOGY_REPORT,
    metadata_root: Path = DEFAULT_METADATA_ROOT,
    time_chunk_path: Path = DEFAULT_TIME_CHUNK,
    output_root: Path = DEFAULT_OUTPUT,
    proxy: str = "",
    timeout_seconds: float = 180.0,
    retries: int = 4,
) -> dict[str, Any]:
    plan, topology, topology_body, plan_payload = compile_plan(
        topology_report_path=topology_report_path,
        metadata_root=metadata_root,
    )
    schema = load_nwm_streamflow_schema(metadata_root)
    opener = _opener(proxy)
    raw_bodies: dict[tuple[int, int], bytes] = {}
    retrievals: dict[str, dict[str, Any]] = {}
    for time_chunk, feature_chunk in plan.q_chunk_keys:
        chunk_key = f"{time_chunk}.{feature_chunk}"
        body, retrieval = _fetch(
            nwm_chunk_url("streamflow", chunk_key),
            opener=opener,
            timeout_seconds=timeout_seconds,
            retries=retries,
            maximum_bytes=100_000_000,
        )
        path = output_root / f"raw/streamflow/{chunk_key}.zst"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        raw_bodies[(time_chunk, feature_chunk)] = body
        retrievals[chunk_key] = {
            **retrieval,
            **_artifact(path),
        }
    time_body = time_chunk_path.read_bytes()
    result = extract_nwm_streamflow(
        plan,
        schema,
        time_chunks={561: time_body},
        streamflow_chunks=raw_bodies,
    )
    if (
        result.fill_value_count != 0
        or len(result.timestamps) != HOUR_COUNT
        or result.feature_ids != plan.feature_ids
        or not np.isfinite(result.values_m3s).all()
        or bool((result.values_m3s < 0.0).any())
    ):
        raise ValueError("center_hill_d4_streamflow_result_invalid")
    value_path = output_root / "tributary_streamflow_values.csv"
    _write_values(value_path, result.timestamps, result.feature_ids, result.values_m3s)
    total = result.values_m3s.sum(axis=1)
    crosswalk_by_id = {
        int(row["tributary_feature_id"]): row
        for row in topology["nwm_boundary_crosswalk"]["rows"]
    }
    confluence_by_id = {
        int(row["tributary_feature_id"]): row
        for row in topology["confluences"]
    }
    per_tributary = [
        {
            **crosswalk_by_id[feature_id],
            "receiving_feature_id": confluence_by_id[feature_id][
                "receiving_feature_id"
            ],
            "mean_m3s": float(result.values_m3s[:, index].mean()),
            "minimum_m3s": float(result.values_m3s[:, index].min()),
            "maximum_m3s": float(result.values_m3s[:, index].max()),
        }
        for index, feature_id in enumerate(result.feature_ids)
    ]
    return {
        **plan_payload,
        "mode": "acquired",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass_outcome_free_tributary_boundary_acquired",
        "topology_report": {
            "path": _display(topology_report_path),
            "sha256": _sha256(topology_body),
            "size_bytes": len(topology_body),
        },
        "raw_artifacts": {
            "time": _artifact(time_chunk_path),
            "streamflow": retrievals,
        },
        "normalized_values": _artifact(value_path),
        "result": {
            "hour_count": len(result.timestamps),
            "tributary_count": len(result.feature_ids),
            "value_count": int(result.values_m3s.size),
            "fill_value_count": result.fill_value_count,
            "total_boundary_flow_m3s": {
                "mean": float(total.mean()),
                "minimum": float(total.min()),
                "maximum": float(total.max()),
                "median": float(np.median(total)),
            },
            "per_tributary": per_tributary,
        },
        "adjudication": {
            "usable_as_transition_input": True,
            "usable_as_observation": False,
            "usable_as_conservation_oracle": False,
            "usable_to_select_or_tune_on_d3": False,
            "independent_end_to_end_prediction": False,
            "full_subnetwork_replacement": False,
            "next_use": (
                "outcome-free branch-boundary rollout invariant and public "
                "post-failure D3 flux accounting diagnostic"
            ),
        },
        "claim_boundary": {
            "modeled_tributary_boundary_available": True,
            "modeled_tributary_boundary_ground_truth": False,
            "modeled_tributary_boundary_possible_nudging": True,
            "full_subnetwork_routing_ready": False,
            "predictive_improvement_validated": False,
            "geospatial_kernel_validated": False,
        },
    }


def _write_values(
    path: Path,
    timestamps: tuple[str, ...],
    feature_ids: tuple[int, ...],
    values: np.ndarray,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["support_start_utc", "support_end_utc"]
            + [f"tributary_{value}_m3s" for value in feature_ids]
            + ["total_modeled_tributary_boundary_m3s"]
        )
        for timestamp, row in zip(timestamps, values, strict=True):
            start = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            writer.writerow(
                [timestamp, _iso(start + timedelta(hours=1))]
                + [f"{float(value):.12g}" for value in row]
                + [f"{float(row.sum()):.12g}"]
            )


def _opener(proxy: str) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = []
    if proxy:
        handlers.append(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    return urllib.request.build_opener(*handlers)


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
        raise ValueError("center_hill_d4_boundary_url_outside_allowlist")
    error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/octet-stream",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                final = urllib.parse.urlparse(response.geturl())
                if final.scheme != "https" or final.hostname != ALLOWED_HOST:
                    raise ValueError(
                        "center_hill_d4_boundary_redirect_outside_allowlist"
                    )
                body = response.read(maximum_bytes + 1)
                if len(body) > maximum_bytes:
                    raise ValueError(
                        "center_hill_d4_boundary_object_size_limit_exceeded"
                    )
                return body, {
                    "url": url,
                    "http_status": response.status,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "attempt_count": attempt,
                    "content_type": response.headers.get("Content-Type"),
                }
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            error = exc
            if attempt < retries:
                time.sleep(float(attempt))
    raise RuntimeError(f"center_hill_d4_boundary_request_failed:{error}")


def _window() -> dict[str, Any]:
    return {
        "start_utc": _iso(START),
        "end_exclusive_utc": _iso(END),
        "hour_count": HOUR_COUNT,
        "support_kind": "interval_mean",
        "timestamp_position": "beginning",
    }


def _artifact(path: Path) -> dict[str, Any]:
    body = path.read_bytes()
    return {
        "path": _display(path),
        "sha256": _sha256(body),
        "size_bytes": len(body),
    }


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    if args.plan_only:
        _, _, _, report = compile_plan(
            topology_report_path=args.topology_report,
            metadata_root=args.metadata_root,
        )
    else:
        report = acquire(
            topology_report_path=args.topology_report,
            metadata_root=args.metadata_root,
            time_chunk_path=args.time_chunk,
            output_root=args.output,
            proxy=args.proxy,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
        )
    _write_json(args.report, report)
    print(args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
