#!/usr/bin/env python3
"""Acquire modeled initial state and distributed forcing for the D5 subnetwork."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Mapping
import urllib.error
import urllib.parse
import urllib.request

import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    NwmQlatPlan,
    extract_nwm_q_lateral,
    extract_nwm_streamflow,
    extract_nwm_velocity,
    load_nwm_streamflow_schema,
    load_nwm_velocity_schema,
    load_nwm_zarr_schema,
    nwm_chunk_url,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOPOLOGY_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_v2_d5_full_subnetwork_report.json"
)
DEFAULT_METADATA_ROOT = REPO_ROOT / "data/geotransport_v0_1/metadata"
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d5_subnetwork_inputs"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_v2_d5_subnetwork_inputs_report.json"
)
SCHEMA = "gwm.geotransport.center_hill_v2_d5_subnetwork_inputs.v1"
TOPOLOGY_SCHEMA = "gwm.geotransport.center_hill_v2_d5_full_subnetwork.v1"
INITIAL_START = datetime(2022, 2, 3, 0, tzinfo=timezone.utc)
ROLLOUT_START = datetime(2022, 2, 3, 1, tzinfo=timezone.utc)
ROLLOUT_END = datetime(2022, 3, 3, 1, tzinfo=timezone.utc)
INITIAL_TIME_CHUNK = 560
ROLLOUT_TIME_CHUNK = 561
HOUR_COUNT = 672
ALLOWED_HOST = "noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com"
USER_AGENT = "gisdataagent-center-hill-d5-subnetwork-inputs/0.1"
MAXIMUM_CHUNK_BYTES = 100_000_000
REUSED_RAW = {
    ("time", "560"): REPO_ROOT / (
        "data/geotransport_v0_1/center_hill_evaluation/nwm/raw/time/560.zst"
    ),
    ("time", "561"): REPO_ROOT / (
        "data/geotransport_v0_1/center_hill_v2_d3_inputs/nwm/raw/time/561.zst"
    ),
    ("streamflow", "560.63"): REPO_ROOT / (
        "data/geotransport_v0_1/center_hill_initial_state_nwm_v3/"
        "raw/streamflow/560.63.zst"
    ),
    ("velocity", "560.63"): REPO_ROOT / (
        "data/geotransport_v0_1/center_hill_evaluation/nwm/"
        "raw/velocity/560.63.zst"
    ),
    ("q_lateral", "561.63"): REPO_ROOT / (
        "data/geotransport_v0_1/center_hill_v2_d3_inputs/nwm/"
        "raw/q_lateral/561.63.zst"
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--topology-report", type=Path, default=DEFAULT_TOPOLOGY_REPORT)
    parser.add_argument("--metadata-root", type=Path, default=DEFAULT_METADATA_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=4)
    return parser.parse_args()


def compile_plan(
    *,
    topology_report_path: Path = DEFAULT_TOPOLOGY_REPORT,
    metadata_root: Path = DEFAULT_METADATA_ROOT,
) -> tuple[dict[str, Any], NwmQlatPlan, NwmQlatPlan, dict[str, Any]]:
    topology_body = topology_report_path.read_bytes()
    topology = json.loads(topology_body)
    if (
        topology.get("schema") != TOPOLOGY_SCHEMA
        or topology.get("status") != "pass_full_incremental_subnetwork_compiled"
        or (topology.get("data_isolation") or {}).get("d3_outcome_values_loaded")
        is not False
        or (topology.get("gates") or {}).get("all_upstream_ancestors_compiled")
        is not True
        or (topology.get("gates") or {}).get(
            "nwm_retrospective_feature_coverage_complete"
        )
        is not True
    ):
        raise ValueError("center_hill_d5_input_topology_report_invalid")
    artifacts = topology["artifacts"]
    network_body = _read_verified(artifacts["full_subnetwork"])
    network_payload = json.loads(network_body)["network"]
    feature_ids = tuple(int(value) for value in network_payload["feature_ids"])
    effective_lengths = tuple(
        float(value) for value in network_payload["effective_lengths_m"]
    )
    if (
        not feature_ids
        or len(feature_ids) != len(set(feature_ids))
        or len(effective_lengths) != len(feature_ids)
        or any(value <= 0.0 for value in effective_lengths)
    ):
        raise ValueError("center_hill_d5_input_network_axis_invalid")
    crosswalk_body = _read_verified(artifacts["nwm_feature_crosswalk"])
    feature_indices = _parse_crosswalk(crosswalk_body, feature_ids)
    feature_chunks = tuple(sorted({index // 30_000 for index in feature_indices}))
    declared_chunks = tuple(topology["nwm_crosswalk"]["feature_chunk_indices"])
    if feature_chunks != declared_chunks:
        raise ValueError("center_hill_d5_input_feature_chunk_plan_mismatch")

    q_schema = load_nwm_zarr_schema(metadata_root)
    velocity_schema = load_nwm_velocity_schema(metadata_root)
    streamflow_schema = load_nwm_streamflow_schema(metadata_root)
    if velocity_schema.base != q_schema or streamflow_schema.base != q_schema:
        raise ValueError("center_hill_d5_input_nwm_schema_mismatch")
    initial_plan = _plan(
        system_id="center_hill_v2_d5_initial_state",
        start=INITIAL_START,
        end=ROLLOUT_START,
        schema=q_schema,
        feature_ids=feature_ids,
        feature_indices=feature_indices,
        expected_time_chunk=INITIAL_TIME_CHUNK,
    )
    forcing_plan = _plan(
        system_id="center_hill_v2_d5_distributed_forcing",
        start=ROLLOUT_START,
        end=ROLLOUT_END,
        schema=q_schema,
        feature_ids=feature_ids,
        feature_indices=feature_indices,
        expected_time_chunk=ROLLOUT_TIME_CHUNK,
    )
    requests = [
        _request(variable, f"{time_chunk}.{feature_chunk}")
        for variable, time_chunk in (
            ("streamflow", INITIAL_TIME_CHUNK),
            ("velocity", INITIAL_TIME_CHUNK),
            ("q_lateral", ROLLOUT_TIME_CHUNK),
        )
        for feature_chunk in feature_chunks
    ]
    requests.extend(
        _request("time", str(value))
        for value in (INITIAL_TIME_CHUNK, ROLLOUT_TIME_CHUNK)
    )
    reusable = [
        {
            "variable": variable,
            "chunk_key": key,
            **_artifact(path, path.read_bytes()),
        }
        for (variable, key), path in REUSED_RAW.items()
        if path.exists() and any(
            row["variable"] == variable and row["chunk_key"] == key
            for row in requests
        )
    ]
    plan_payload = {
        "schema": SCHEMA,
        "mode": "plan",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready_to_acquire_outcome_free_inputs",
        "topology_report": _artifact(topology_report_path, topology_body),
        "full_subnetwork": artifacts["full_subnetwork"],
        "route_link_subset": artifacts["route_link_subset"],
        "feature_count": len(feature_ids),
        "feature_chunk_indices": list(feature_chunks),
        "initial_state_support": {
            "valid_at_utc": _iso(INITIAL_START),
            "next_window_start_utc": _iso(ROLLOUT_START),
            "time_chunk_index": INITIAL_TIME_CHUNK,
        },
        "forcing_window": {
            "start_utc": _iso(ROLLOUT_START),
            "end_exclusive_utc": _iso(ROLLOUT_END),
            "hour_count": HOUR_COUNT,
            "time_chunk_index": ROLLOUT_TIME_CHUNK,
        },
        "requests": requests,
        "reusable_raw_artifacts": reusable,
        "semantic_contract": {
            "initial_streamflow": {
                "role": "retrospective_modeled_initial_state",
                "modeled": True,
                "ground_truth": False,
                "possible_nudging": True,
                "observation": False,
                "conservation_oracle": False,
            },
            "initial_velocity": {
                "role": "retrospective_modeled_initial_state_context",
                "modeled": True,
                "ground_truth": False,
                "admitted_as_flood_wave_celerity": False,
            },
            "q_lateral": {
                "role": "modeled_distributed_reach_forcing",
                "modeled": True,
                "ground_truth": False,
                "observation": False,
                "conservation_oracle": False,
            },
        },
        "data_isolation": {
            "d3_outcome_values_loaded": False,
            "d3_outcome_artifacts_read": False,
            "d3_window_role": "public_structural_development_only",
        },
        "claim_boundary": {
            "request_plan_only": True,
            "public_data_without_user_supplied_data": True,
            "full_subnetwork_initial_state_available": False,
            "full_subnetwork_q_lateral_available": False,
            "outcome_free_rollout_sealed": False,
            "geospatial_kernel_validated": False,
        },
    }
    context = {
        "topology": topology,
        "network_payload": network_payload,
        "feature_ids": feature_ids,
        "feature_indices": feature_indices,
        "effective_lengths": effective_lengths,
        "q_schema": q_schema,
        "velocity_schema": velocity_schema,
        "streamflow_schema": streamflow_schema,
    }
    return plan_payload, initial_plan, forcing_plan, context


def acquire(
    *,
    topology_report_path: Path = DEFAULT_TOPOLOGY_REPORT,
    metadata_root: Path = DEFAULT_METADATA_ROOT,
    output_root: Path = DEFAULT_OUTPUT,
    proxy: str = "http://127.0.0.1:7897",
    timeout_seconds: float = 180.0,
    retries: int = 4,
) -> dict[str, Any]:
    plan_payload, initial_plan, forcing_plan, context = compile_plan(
        topology_report_path=topology_report_path,
        metadata_root=metadata_root,
    )
    opener = _opener(proxy)
    raw: dict[tuple[str, str], bytes] = {}
    raw_artifacts: list[dict[str, Any]] = []
    for request in plan_payload["requests"]:
        variable = str(request["variable"])
        key = str(request["chunk_key"])
        reused_path = REUSED_RAW.get((variable, key))
        if reused_path is not None and reused_path.exists():
            body = reused_path.read_bytes()
            descriptor = {
                "retrieval_mode": "verified_local_reuse",
                "url": request["url"],
                "variable": variable,
                "chunk_key": key,
                **_artifact(reused_path, body),
            }
        else:
            body, retrieval = _fetch(
                request["url"],
                opener=opener,
                timeout_seconds=timeout_seconds,
                retries=retries,
                maximum_bytes=int(request["maximum_bytes"]),
            )
            path = output_root / f"raw/{variable}/{key}.zst"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            descriptor = {
                **retrieval,
                "retrieval_mode": "official_remote_fetch",
                "variable": variable,
                "chunk_key": key,
                **_artifact(path, body),
            }
        raw[(variable, key)] = body
        raw_artifacts.append(descriptor)

    feature_chunks = initial_plan.feature_chunk_indices
    time_initial = raw[("time", str(INITIAL_TIME_CHUNK))]
    time_forcing = raw[("time", str(ROLLOUT_TIME_CHUNK))]
    streamflow = extract_nwm_streamflow(
        initial_plan,
        context["streamflow_schema"],
        time_chunks={INITIAL_TIME_CHUNK: time_initial},
        streamflow_chunks={
            (INITIAL_TIME_CHUNK, chunk): raw[
                ("streamflow", f"{INITIAL_TIME_CHUNK}.{chunk}")
            ]
            for chunk in feature_chunks
        },
    )
    velocity = extract_nwm_velocity(
        initial_plan,
        context["velocity_schema"],
        time_chunks={INITIAL_TIME_CHUNK: time_initial},
        velocity_chunks={
            (INITIAL_TIME_CHUNK, chunk): raw[
                ("velocity", f"{INITIAL_TIME_CHUNK}.{chunk}")
            ]
            for chunk in feature_chunks
        },
    )
    forcing = extract_nwm_q_lateral(
        forcing_plan,
        context["q_schema"],
        time_chunks={ROLLOUT_TIME_CHUNK: time_forcing},
        q_chunks={
            (ROLLOUT_TIME_CHUNK, chunk): raw[
                ("q_lateral", f"{ROLLOUT_TIME_CHUNK}.{chunk}")
            ]
            for chunk in feature_chunks
        },
    )
    if (
        streamflow.timestamps != (_iso(INITIAL_START),)
        or velocity.timestamps != streamflow.timestamps
        or forcing.timestamps[0] != _iso(ROLLOUT_START)
        or len(forcing.timestamps) != HOUR_COUNT
        or streamflow.feature_ids != context["feature_ids"]
        or velocity.feature_ids != context["feature_ids"]
        or forcing.feature_ids != context["feature_ids"]
        or streamflow.fill_value_count != 0
        or velocity.fill_value_count != 0
        or forcing.fill_value_count != 0
    ):
        raise ValueError("center_hill_d5_decoded_input_axes_or_fill_invalid")

    discharge = np.asarray(streamflow.values_m3s[0], dtype=np.float64)
    speed = np.asarray(velocity.values_ms[0], dtype=np.float64)
    invalid_velocity = (discharge > 0.0) & (speed <= 0.0)
    if bool(invalid_velocity.any()):
        invalid_ids = np.asarray(context["feature_ids"])[invalid_velocity]
        raise ValueError(
            "center_hill_d5_positive_flow_requires_positive_velocity:"
            f"{invalid_ids[:20].tolist()}"
        )
    area = np.divide(
        discharge,
        speed,
        out=np.zeros_like(discharge),
        where=speed > 0.0,
    )
    storage = area * np.asarray(context["effective_lengths"], dtype=np.float64)
    q_lateral = np.asarray(forcing.values_m3s, dtype=np.float64)
    if (
        not np.isfinite(storage).all()
        or bool((storage < 0.0).any())
        or not np.isfinite(q_lateral).all()
        or bool((q_lateral < 0.0).any())
    ):
        raise ValueError("center_hill_d5_decoded_physical_values_invalid")

    arrays = {
        "feature_ids": np.asarray(context["feature_ids"], dtype=np.int64),
        "initial_streamflow_m3s": discharge,
        "initial_velocity_ms": speed,
        "initial_cross_section_area_m2": area,
        "initial_storage_m3": storage,
        "q_lateral_m3s": q_lateral,
        "forcing_timestamps_utc": np.asarray(forcing.timestamps, dtype="U20"),
    }
    array_artifacts: dict[str, dict[str, Any]] = {}
    for name, values in arrays.items():
        path = output_root / f"decoded/{name}.npy"
        _write_npy(path, values)
        array_artifacts[name] = {
            **_artifact(path, path.read_bytes()),
            "dtype": str(values.dtype),
            "shape": list(values.shape),
        }

    total_forcing = q_lateral.sum(axis=1)
    return {
        **plan_payload,
        "mode": "acquired",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass_outcome_free_full_subnetwork_inputs_acquired",
        "raw_artifacts": raw_artifacts,
        "decoded_arrays": array_artifacts,
        "result": {
            "feature_count": len(context["feature_ids"]),
            "hour_count": len(forcing.timestamps),
            "initial_streamflow_fill_value_count": streamflow.fill_value_count,
            "initial_velocity_fill_value_count": velocity.fill_value_count,
            "q_lateral_fill_value_count": forcing.fill_value_count,
            "positive_flow_zero_velocity_count": int(invalid_velocity.sum()),
            "initial_storage_m3": {
                "total": float(storage.sum()),
                "minimum": float(storage.min()),
                "maximum": float(storage.max()),
            },
            "distributed_q_lateral_m3s": {
                "total_mean": float(total_forcing.mean()),
                "total_median": float(np.median(total_forcing)),
                "total_minimum": float(total_forcing.min()),
                "total_maximum": float(total_forcing.max()),
                "reach_value_minimum": float(q_lateral.min()),
                "reach_value_maximum": float(q_lateral.max()),
            },
        },
        "claim_boundary": {
            "request_plan_only": False,
            "public_data_without_user_supplied_data": True,
            "full_subnetwork_initial_state_available": True,
            "full_subnetwork_q_lateral_available": True,
            "initial_state_ground_truth": False,
            "q_lateral_ground_truth": False,
            "outcome_free_rollout_sealed": False,
            "geospatial_kernel_validated": False,
        },
    }


def _plan(
    *,
    system_id: str,
    start: datetime,
    end: datetime,
    schema: Any,
    feature_ids: tuple[int, ...],
    feature_indices: tuple[int, ...],
    expected_time_chunk: int,
) -> NwmQlatPlan:
    start_index = int((start - schema.time_origin).total_seconds() / 3600.0)
    end_index = int((end - schema.time_origin).total_seconds() / 3600.0)
    time_chunks = tuple(
        range(
            start_index // schema.time_chunk_size,
            (end_index - 1) // schema.time_chunk_size + 1,
        )
    )
    feature_chunks = tuple(
        sorted({index // schema.q_chunks[1] for index in feature_indices})
    )
    if time_chunks != (expected_time_chunk,):
        raise ValueError("center_hill_d5_unexpected_time_chunk_plan")
    return NwmQlatPlan(
        system_id=system_id,
        start=start,
        end=end,
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


def _request(variable: str, key: str) -> dict[str, Any]:
    return {
        "variable": variable,
        "chunk_key": key,
        "url": nwm_chunk_url(variable, key),
        "maximum_bytes": (
            1_000_000 if variable == "time" else MAXIMUM_CHUNK_BYTES
        ),
    }


def _parse_crosswalk(body: bytes, feature_ids: tuple[int, ...]) -> tuple[int, ...]:
    text = body.decode("utf-8").splitlines()
    reader = csv.DictReader(text)
    rows = list(reader)
    ids = tuple(int(row["feature_id"]) for row in rows)
    indices = tuple(int(row["nwm_feature_index"]) for row in rows)
    chunks = tuple(int(row["nwm_feature_chunk_index"]) for row in rows)
    if (
        ids != feature_ids
        or len(indices) != len(set(indices))
        or any(index // 30_000 != chunk for index, chunk in zip(indices, chunks, strict=True))
    ):
        raise ValueError("center_hill_d5_input_crosswalk_invalid")
    return indices


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
        raise ValueError("center_hill_d5_input_url_outside_allowlist")
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
                    raise ValueError("center_hill_d5_input_redirect_outside_allowlist")
                body = response.read(maximum_bytes + 1)
                if len(body) > maximum_bytes:
                    raise ValueError("center_hill_d5_input_object_size_limit_exceeded")
                return body, {
                    "url": url,
                    "http_status": response.status,
                    "content_type": response.headers.get("Content-Type"),
                    "attempt_count": attempt,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            error = exc
            if attempt < retries:
                time.sleep(float(attempt))
    raise RuntimeError(f"center_hill_d5_input_request_failed:{error}")


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("center_hill_d5_input_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("center_hill_d5_input_artifact_identity_mismatch")
    return body


def _write_npy(path: Path, values: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        np.save(stream, values, allow_pickle=False)
    temporary.replace(path)


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


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("center_hill_d5_input_positive_request_limits_required")
    if args.plan_only:
        report, _, _, _ = compile_plan(
            topology_report_path=args.topology_report,
            metadata_root=args.metadata_root,
        )
    else:
        report = acquire(
            topology_report_path=args.topology_report,
            metadata_root=args.metadata_root,
            output_root=args.output,
            proxy=args.proxy,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
        )
    _write_json(args.report, report)
    print(args.report)
    print(f"feature_count={report['feature_count']}")
    print(
        "feature_chunk_indices="
        + ",".join(str(value) for value in report["feature_chunk_indices"])
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
