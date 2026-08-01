#!/usr/bin/env python3
"""Acquire full-subnetwork NWM inputs for the pre-D3 development window."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    NwmQlatPlan,
    extract_nwm_q_lateral,
    extract_nwm_streamflow,
    extract_nwm_velocity,
)
if __package__:
    from scripts.acquire_geotransport_center_hill_v2_d5_subnetwork_inputs import (
        DEFAULT_METADATA_ROOT,
        DEFAULT_TOPOLOGY_REPORT,
        REPO_ROOT,
        _artifact,
        _fetch,
        _opener,
        _request,
        _write_npy,
        compile_plan as compile_d5_plan,
    )
else:
    from acquire_geotransport_center_hill_v2_d5_subnetwork_inputs import (
        DEFAULT_METADATA_ROOT,
        DEFAULT_TOPOLOGY_REPORT,
        REPO_ROOT,
        _artifact,
        _fetch,
        _opener,
        _request,
        _write_npy,
        compile_plan as compile_d5_plan,
    )


DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/forecast_closure_center_hill_development_inputs"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "forecast_closure_center_hill_development_inputs_report.json"
)
SCHEMA = "gwm.geotransport.forecast_closure_development_inputs.v1"
START = datetime(2021, 12, 9, 1, tzinfo=timezone.utc)
END = datetime(2022, 1, 6, 1, tzinfo=timezone.utc)
HOUR_COUNT = 672
TIME_CHUNK = 559
REUSED_RAW = {
    ("time", "559"): REPO_ROOT
    / "data/geotransport_v0_1/nwm_q_lateral/raw/time/559.zst",
    ("q_lateral", "559.63"): REPO_ROOT
    / "data/geotransport_v0_1/nwm_q_lateral/raw/q_lateral/559.63.zst",
    ("velocity", "559.63"): REPO_ROOT
    / "data/geotransport_v0_1/nwm_velocity/raw/velocity/559.63.zst",
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


def compile_development_plan(
    *,
    topology_report_path: Path = DEFAULT_TOPOLOGY_REPORT,
    metadata_root: Path = DEFAULT_METADATA_ROOT,
) -> tuple[dict[str, Any], NwmQlatPlan, NwmQlatPlan, dict[str, Any]]:
    _, _, _, context = compile_d5_plan(
        topology_report_path=topology_report_path,
        metadata_root=metadata_root,
    )
    feature_ids = context["feature_ids"]
    feature_indices = context["feature_indices"]
    schema = context["q_schema"]
    initial_plan = _plan(
        system_id="center_hill_forecast_closure_development_initial",
        start=START,
        end=START + timedelta(hours=1),
        schema=schema,
        feature_ids=feature_ids,
        feature_indices=feature_indices,
    )
    forcing_plan = _plan(
        system_id="center_hill_forecast_closure_development_forcing",
        start=START,
        end=END,
        schema=schema,
        feature_ids=feature_ids,
        feature_indices=feature_indices,
    )
    feature_chunks = forcing_plan.feature_chunk_indices
    requests = [
        _request(variable, f"{TIME_CHUNK}.{feature_chunk}")
        for variable in ("streamflow", "velocity", "q_lateral")
        for feature_chunk in feature_chunks
    ]
    requests.append(_request("time", str(TIME_CHUNK)))
    reusable = [
        {
            "variable": variable,
            "chunk_key": key,
            **_artifact(path, path.read_bytes()),
        }
        for (variable, key), path in REUSED_RAW.items()
        if path.exists()
    ]
    topology_body = topology_report_path.read_bytes()
    payload = {
        "schema": SCHEMA,
        "mode": "plan",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready_to_acquire_public_development_inputs",
        "topology_report": _artifact(topology_report_path, topology_body),
        "window": {
            "start_inclusive_utc": _iso(START),
            "end_exclusive_utc": _iso(END),
            "hour_count": HOUR_COUNT,
            "nwm_time_chunk": TIME_CHUNK,
            "role": "pre_d3_public_development_only",
        },
        "feature_count": len(feature_ids),
        "feature_chunk_indices": list(feature_chunks),
        "requests": requests,
        "reusable_raw_artifacts": reusable,
        "semantic_contract": {
            "initial_streamflow": {
                "role": "retrospective_modeled_initial_state",
                "modeled": True,
                "ground_truth": False,
                "possible_nudging": True,
                "observation": False,
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
            },
        },
        "data_isolation": {
            "d3_outcomes_read": False,
            "two_system_blind_outcomes_read": False,
            "only_pre_d3_development_window_requested": True,
        },
        "claim_boundary": {
            "request_plan_only": True,
            "public_data_without_user_supplied_data": True,
            "development_inputs_available": False,
            "forecast_closure_trained": False,
            "predictive_improvement_validated": False,
            "geospatial_kernel_validated": False,
        },
    }
    return payload, initial_plan, forcing_plan, context


def acquire(
    *,
    topology_report_path: Path = DEFAULT_TOPOLOGY_REPORT,
    metadata_root: Path = DEFAULT_METADATA_ROOT,
    output_root: Path = DEFAULT_OUTPUT,
    proxy: str = "http://127.0.0.1:7897",
    timeout_seconds: float = 180.0,
    retries: int = 4,
) -> dict[str, Any]:
    payload, initial_plan, forcing_plan, context = compile_development_plan(
        topology_report_path=topology_report_path,
        metadata_root=metadata_root,
    )
    opener = _opener(proxy)
    raw: dict[tuple[str, str], bytes] = {}
    raw_artifacts: list[dict[str, Any]] = []
    for request in payload["requests"]:
        variable = str(request["variable"])
        key = str(request["chunk_key"])
        reused = REUSED_RAW.get((variable, key))
        if reused is not None and reused.exists():
            body = reused.read_bytes()
            descriptor = {
                "retrieval_mode": "verified_local_reuse",
                "url": request["url"],
                "variable": variable,
                "chunk_key": key,
                **_artifact(reused, body),
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

    feature_chunks = forcing_plan.feature_chunk_indices
    time_body = raw[("time", str(TIME_CHUNK))]
    streamflow = extract_nwm_streamflow(
        initial_plan,
        context["streamflow_schema"],
        time_chunks={TIME_CHUNK: time_body},
        streamflow_chunks={
            (TIME_CHUNK, chunk): raw[("streamflow", f"{TIME_CHUNK}.{chunk}")]
            for chunk in feature_chunks
        },
    )
    velocity = extract_nwm_velocity(
        initial_plan,
        context["velocity_schema"],
        time_chunks={TIME_CHUNK: time_body},
        velocity_chunks={
            (TIME_CHUNK, chunk): raw[("velocity", f"{TIME_CHUNK}.{chunk}")]
            for chunk in feature_chunks
        },
    )
    forcing = extract_nwm_q_lateral(
        forcing_plan,
        context["q_schema"],
        time_chunks={TIME_CHUNK: time_body},
        q_chunks={
            (TIME_CHUNK, chunk): raw[("q_lateral", f"{TIME_CHUNK}.{chunk}")]
            for chunk in feature_chunks
        },
    )
    expected_features = context["feature_ids"]
    if (
        streamflow.timestamps != (_iso(START),)
        or velocity.timestamps != streamflow.timestamps
        or forcing.timestamps[0] != _iso(START)
        or forcing.timestamps[-1] != _iso(END - timedelta(hours=1))
        or len(forcing.timestamps) != HOUR_COUNT
        or streamflow.feature_ids != expected_features
        or velocity.feature_ids != expected_features
        or forcing.feature_ids != expected_features
        or streamflow.fill_value_count != 0
        or velocity.fill_value_count != 0
        or forcing.fill_value_count != 0
    ):
        raise ValueError("forecast_closure_development_decoded_axes_invalid")

    discharge = np.asarray(streamflow.values_m3s[0], dtype=np.float64)
    speed = np.asarray(velocity.values_ms[0], dtype=np.float64)
    invalid_velocity = (discharge > 0.0) & (speed <= 0.0)
    if bool(invalid_velocity.any()):
        raise ValueError("forecast_closure_development_positive_flow_zero_velocity")
    area = np.divide(discharge, speed, out=np.zeros_like(discharge), where=speed > 0)
    storage = area * np.asarray(context["effective_lengths"], dtype=np.float64)
    q_lateral = np.asarray(forcing.values_m3s, dtype=np.float64)
    if (
        not np.isfinite(storage).all()
        or bool((storage < 0.0).any())
        or not np.isfinite(q_lateral).all()
        or bool((q_lateral < 0.0).any())
    ):
        raise ValueError("forecast_closure_development_physical_values_invalid")

    arrays = {
        "feature_ids": np.asarray(expected_features, dtype=np.int64),
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
        **payload,
        "mode": "acquired",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass_public_development_inputs_acquired",
        "raw_artifacts": raw_artifacts,
        "decoded_arrays": array_artifacts,
        "result": {
            "feature_count": len(expected_features),
            "hour_count": HOUR_COUNT,
            "initial_streamflow_fill_value_count": streamflow.fill_value_count,
            "initial_velocity_fill_value_count": velocity.fill_value_count,
            "q_lateral_fill_value_count": forcing.fill_value_count,
            "initial_storage_total_m3": float(storage.sum()),
            "q_lateral_total_mean_m3s": float(total_forcing.mean()),
            "q_lateral_total_minimum_m3s": float(total_forcing.min()),
            "q_lateral_total_maximum_m3s": float(total_forcing.max()),
        },
        "claim_boundary": {
            "request_plan_only": False,
            "public_data_without_user_supplied_data": True,
            "development_inputs_available": True,
            "initial_state_ground_truth": False,
            "q_lateral_ground_truth": False,
            "forecast_closure_trained": False,
            "predictive_improvement_validated": False,
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
    if time_chunks != (TIME_CHUNK,):
        raise ValueError("forecast_closure_development_time_chunk_mismatch")
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


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    args = parse_args()
    if args.plan_only:
        report, _, _, _ = compile_development_plan(
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
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.report)
    print(report["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
