#!/usr/bin/env python3
"""Acquire frozen NWM/CWMS holdout inputs while deferring issue observations."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    DEFAULT_REGISTRY_PATH,
    extract_nwm_q_lateral,
    extract_nwm_streamflow,
    extract_nwm_velocity,
    load_nwm_streamflow_schema,
    load_nwm_velocity_schema,
    load_nwm_zarr_schema,
    load_public_data_registry,
)

if __package__:
    from scripts import (
        freeze_geospatial_kernel_horizon_assimilation_holdout_protocol as freeze,
    )
    from scripts import (
        plan_geospatial_kernel_horizon_assimilation_holdout_inputs as frozen_plan,
    )
    from scripts.acquire_geotransport_center_hill_v2_d3_inputs import (
        _fetch as _fetch_companion,
    )
    from scripts.acquire_geotransport_center_hill_v2_d3_inputs import (
        _write_action_values,
    )
    from scripts.acquire_geotransport_center_hill_v2_d5_subnetwork_inputs import (
        _artifact,
        _opener,
        _parse_crosswalk,
        _plan,
        _request,
        _write_npy,
    )
    from scripts.acquire_geotransport_center_hill_v2_d5_subnetwork_inputs import (
        _fetch as _fetch_nwm,
    )
    from scripts.build_geotransport_center_hill_smoke_panel import (
        _parse_cwms_hourly,
    )
else:
    import freeze_geospatial_kernel_horizon_assimilation_holdout_protocol as freeze
    import plan_geospatial_kernel_horizon_assimilation_holdout_inputs as frozen_plan
    from acquire_geotransport_center_hill_v2_d3_inputs import (
        _fetch as _fetch_companion,
    )
    from acquire_geotransport_center_hill_v2_d3_inputs import (
        _write_action_values,
    )
    from acquire_geotransport_center_hill_v2_d5_subnetwork_inputs import (
        _artifact,
        _opener,
        _parse_crosswalk,
        _plan,
        _request,
        _write_npy,
    )
    from acquire_geotransport_center_hill_v2_d5_subnetwork_inputs import (
        _fetch as _fetch_nwm,
    )
    from build_geotransport_center_hill_smoke_panel import _parse_cwms_hourly

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = freeze.DEFAULT_OUTPUT
DEFAULT_FROZEN_PLAN = frozen_plan.DEFAULT_OUTPUT
DEFAULT_METADATA_ROOT = REPO_ROOT / "data/geotransport_v0_1/metadata"
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout/static_inputs"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_static_inputs_report.json"
)
SCHEMA = "gwm.geotransport.horizon_assimilation_holdout_static_inputs.v1"
STATIC_REQUEST_COUNT = 10
DEFERRED_ISSUE_REQUEST_COUNT = 112


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--frozen-plan", type=Path, default=DEFAULT_FROZEN_PLAN)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--metadata-root", type=Path, default=DEFAULT_METADATA_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=4)
    return parser.parse_args()


def compile_static_plan(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    frozen_plan_path: Path = DEFAULT_FROZEN_PLAN,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    metadata_root: Path = DEFAULT_METADATA_ROOT,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    protocol_body, protocol = _load_json(protocol_path)
    frozen_plan_body, plan = _load_json(frozen_plan_path)
    frozen_plan._validate_protocol(protocol)
    try:
        rebuilt_plan = frozen_plan.compile_holdout_input_plan(
            protocol_path=protocol_path,
            generated_at=frozen_plan._parse_time(plan.get("generated_at")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("horizon_holdout_static_frozen_plan_invalid") from exc
    if plan != rebuilt_plan:
        raise ValueError("horizon_holdout_static_frozen_plan_invalid")
    _validate_frozen_plan(
        plan,
        plan_body=frozen_plan_body,
        protocol_body=protocol_body,
    )

    registry = load_public_data_registry(registry_path)
    registry_systems = {
        row["system_id"]: row for row in registry.payload["systems"]
    }
    q_schema = load_nwm_zarr_schema(metadata_root)
    velocity_schema = load_nwm_velocity_schema(metadata_root)
    streamflow_schema = load_nwm_streamflow_schema(metadata_root)
    if velocity_schema.base != q_schema or streamflow_schema.base != q_schema:
        raise ValueError("horizon_holdout_static_nwm_schema_mismatch")

    systems: dict[str, dict[str, Any]] = {}
    requests_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for system_id in freeze.SYSTEM_IDS:
        lock = protocol["systems"][system_id]
        topology_body = _read_verified(lock["topology_report"])
        topology = json.loads(topology_body)
        artifacts = topology["artifacts"]
        network_body = _read_verified(artifacts["full_subnetwork"])
        network = json.loads(network_body)["network"]
        feature_ids = tuple(int(value) for value in network["feature_ids"])
        feature_indices = _parse_crosswalk(
            _read_verified(artifacts["nwm_feature_crosswalk"]),
            feature_ids,
        )
        feature_chunks = tuple(sorted({value // 30_000 for value in feature_indices}))
        if feature_chunks != tuple(lock["feature_chunk_indices"]):
            raise ValueError(f"horizon_holdout_static_{system_id}_feature_chunk_mismatch")
        initial_plan = _plan(
            system_id=f"{system_id}_horizon_holdout_initial_state",
            start=freeze.INITIAL_STATE_AT,
            end=freeze.INITIAL_STATE_AT + timedelta(hours=1),
            schema=q_schema,
            feature_ids=feature_ids,
            feature_indices=feature_indices,
            expected_time_chunk=freeze.INITIAL_TIME_CHUNK,
        )
        forcing_plan = _plan(
            system_id=f"{system_id}_horizon_holdout_forcing",
            start=freeze.START,
            end=freeze.END,
            schema=q_schema,
            feature_ids=feature_ids,
            feature_indices=feature_indices,
            expected_time_chunk=freeze.FORCING_TIME_CHUNK,
        )
        for variable, time_chunk in (
            ("streamflow", freeze.INITIAL_TIME_CHUNK),
            ("velocity", freeze.INITIAL_TIME_CHUNK),
            ("q_lateral", freeze.FORCING_TIME_CHUNK),
        ):
            for feature_chunk in feature_chunks:
                request = _request(variable, f"{time_chunk}.{feature_chunk}")
                requests_by_key[(variable, request["chunk_key"])] = request
        for time_chunk in (freeze.INITIAL_TIME_CHUNK, freeze.FORCING_TIME_CHUNK):
            request = _request("time", str(time_chunk))
            requests_by_key[("time", request["chunk_key"])] = request
        systems[system_id] = {
            "lock": lock,
            "registry": registry_systems[system_id],
            "topology": topology,
            "network": network,
            "feature_ids": feature_ids,
            "feature_indices": feature_indices,
            "feature_chunks": feature_chunks,
            "effective_lengths": tuple(
                float(value) for value in network["effective_lengths_m"]
            ),
            "initial_plan": initial_plan,
            "forcing_plan": forcing_plan,
        }
    requests = [requests_by_key[key] for key in sorted(requests_by_key)]
    _validate_nwm_request_identity(requests, plan["nwm_requests"])
    if len(requests) + len(freeze.SYSTEM_IDS) != STATIC_REQUEST_COUNT:
        raise ValueError("horizon_holdout_static_request_count_mismatch")

    report = {
        "schema": SCHEMA,
        "mode": "plan",
        "status": "static_inputs_ready_to_acquire_issue_observations_deferred",
        "generated_at": datetime.now(UTC).isoformat(),
        "frozen_artifacts": {
            "protocol": _artifact(protocol_path, protocol_body),
            "input_plan": _artifact(frozen_plan_path, frozen_plan_body),
            "registry": _artifact(registry_path, registry_path.read_bytes()),
        },
        "window": dict(protocol["window"]),
        "systems": {
            system_id: {
                "topology_report": value["lock"]["topology_report"],
                "feature_count": len(value["feature_ids"]),
                "feature_chunk_indices": list(value["feature_chunks"]),
                "action_url": value["lock"]["action"]["url"],
            }
            for system_id, value in systems.items()
        },
        "nwm_requests": requests,
        "request_execution": {
            "frozen_total_request_count": 122,
            "static_request_count": STATIC_REQUEST_COUNT,
            "nwm_request_count": len(requests),
            "cwms_request_count": len(freeze.SYSTEM_IDS),
            "usgs_issue_request_count_executed": 0,
            "usgs_issue_request_count_deferred": DEFERRED_ISSUE_REQUEST_COUNT,
            "bulk_issue_observation_prefetch_permitted": False,
        },
        "data_isolation": {
            "usgs_url_requested": False,
            "issue_observation_loaded": False,
            "future_target_loaded": False,
            "score_or_loss_loaded": False,
        },
        "claim_boundary": {
            "request_plan_only": True,
            "static_inputs_acquired": False,
            "issue_observations_acquired": False,
            "outcome_free_predictions_executed": False,
            "candidate_promoted": False,
            "runtime_default_enabled": False,
        },
    }
    schemas = {
        "q": q_schema,
        "velocity": velocity_schema,
        "streamflow": streamflow_schema,
    }
    return report, systems, schemas


def acquire_static_inputs(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    frozen_plan_path: Path = DEFAULT_FROZEN_PLAN,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    metadata_root: Path = DEFAULT_METADATA_ROOT,
    output_root: Path = DEFAULT_OUTPUT,
    proxy: str = "http://127.0.0.1:7897",
    timeout_seconds: float = 180.0,
    retries: int = 4,
) -> dict[str, Any]:
    report, systems, schemas = compile_static_plan(
        protocol_path=protocol_path,
        frozen_plan_path=frozen_plan_path,
        registry_path=registry_path,
        metadata_root=metadata_root,
    )
    opener = _opener(proxy)
    raw: dict[tuple[str, str], bytes] = {}
    raw_artifacts: list[dict[str, Any]] = []
    for request in report["nwm_requests"]:
        variable = str(request["variable"])
        key = str(request["chunk_key"])
        path = output_root / f"raw/nwm/{variable}/{key}.zst"
        if path.exists():
            body = path.read_bytes()
            retrieval = {
                "url": request["url"],
                "retrieval_mode": "verified_local_retry_reuse",
            }
        else:
            body, retrieval = _fetch_nwm(
                request["url"],
                opener=opener,
                timeout_seconds=timeout_seconds,
                retries=retries,
                maximum_bytes=int(request["maximum_bytes"]),
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        raw[(variable, key)] = body
        raw_artifacts.append(
            {
                **retrieval,
                "variable": variable,
                "chunk_key": key,
                **_artifact(path, body),
            }
        )

    support_starts = tuple(
        freeze.START + timedelta(hours=index) for index in range(freeze.HOUR_COUNT)
    )
    support_ends = tuple(value + timedelta(hours=1) for value in support_starts)
    system_results: dict[str, dict[str, Any]] = {}
    for system_id, context in systems.items():
        lock = context["lock"]
        action_raw_path = output_root / f"raw/action/{system_id}.json"
        if action_raw_path.exists():
            action_body = action_raw_path.read_bytes()
            action_retrieval = {
                "url": lock["action"]["url"],
                "retrieval_mode": "verified_local_retry_reuse",
            }
        else:
            action_body, action_retrieval = _fetch_companion(
                lock["action"]["url"],
                opener=opener,
                timeout=timeout_seconds,
                retries=retries,
                maximum_bytes=2_000_000,
            )
            action_raw_path.parent.mkdir(parents=True, exist_ok=True)
            action_raw_path.write_bytes(action_body)
        action_values, action_quality = _parse_cwms_hourly(
            json.loads(action_body),
            field=context["registry"]["action"],
            expected_timestamps=support_ends,
        )
        action_path = output_root / f"systems/{system_id}/action_values.csv"
        _write_action_values(
            action_path,
            support_starts=support_starts,
            support_ends=support_ends,
            values=action_values,
        )
        arrays, quality = _decode_system(context, raw=raw, schemas=schemas)
        array_artifacts: dict[str, dict[str, Any]] = {}
        for name, values in arrays.items():
            path = output_root / f"systems/{system_id}/decoded/{name}.npy"
            _write_npy(path, values)
            array_artifacts[name] = {
                **_artifact(path, path.read_bytes()),
                "dtype": str(values.dtype),
                "shape": list(values.shape),
            }
        system_results[system_id] = {
            "topology_report": lock["topology_report"],
            "feature_count": len(context["feature_ids"]),
            "feature_chunk_indices": list(context["feature_chunks"]),
            "action_raw": {
                **action_retrieval,
                **_artifact(action_raw_path, action_body),
            },
            "action_values": _artifact(action_path, action_path.read_bytes()),
            "action_quality_codes": sorted(set(action_quality.values())),
            "decoded_arrays": array_artifacts,
            "result": quality,
        }
    return {
        **report,
        "mode": "acquired",
        "status": "static_inputs_acquired_issue_observations_deferred",
        "generated_at": datetime.now(UTC).isoformat(),
        "raw_nwm_artifacts": raw_artifacts,
        "systems": system_results,
        "request_execution": {
            **report["request_execution"],
            "static_request_count_executed_or_verified_reuse": STATIC_REQUEST_COUNT,
        },
        "claim_boundary": {
            "request_plan_only": False,
            "static_inputs_acquired": True,
            "issue_observations_acquired": False,
            "outcome_free_predictions_executed": False,
            "candidate_promoted": False,
            "runtime_default_enabled": False,
        },
    }


def _decode_system(
    context: Mapping[str, Any],
    *,
    raw: Mapping[tuple[str, str], bytes],
    schemas: Mapping[str, Any],
) -> tuple[dict[str, np.ndarray[Any, Any]], dict[str, Any]]:
    chunks = context["feature_chunks"]
    initial_time = raw[("time", str(freeze.INITIAL_TIME_CHUNK))]
    forcing_time = raw[("time", str(freeze.FORCING_TIME_CHUNK))]
    streamflow = extract_nwm_streamflow(
        context["initial_plan"],
        schemas["streamflow"],
        time_chunks={freeze.INITIAL_TIME_CHUNK: initial_time},
        streamflow_chunks={
            (freeze.INITIAL_TIME_CHUNK, chunk): raw[
                ("streamflow", f"{freeze.INITIAL_TIME_CHUNK}.{chunk}")
            ]
            for chunk in chunks
        },
    )
    velocity = extract_nwm_velocity(
        context["initial_plan"],
        schemas["velocity"],
        time_chunks={freeze.INITIAL_TIME_CHUNK: initial_time},
        velocity_chunks={
            (freeze.INITIAL_TIME_CHUNK, chunk): raw[
                ("velocity", f"{freeze.INITIAL_TIME_CHUNK}.{chunk}")
            ]
            for chunk in chunks
        },
    )
    forcing = extract_nwm_q_lateral(
        context["forcing_plan"],
        schemas["q"],
        time_chunks={freeze.FORCING_TIME_CHUNK: forcing_time},
        q_chunks={
            (freeze.FORCING_TIME_CHUNK, chunk): raw[
                ("q_lateral", f"{freeze.FORCING_TIME_CHUNK}.{chunk}")
            ]
            for chunk in chunks
        },
    )
    feature_ids = context["feature_ids"]
    if (
        streamflow.timestamps != (_iso(freeze.INITIAL_STATE_AT),)
        or velocity.timestamps != streamflow.timestamps
        or forcing.timestamps
        != tuple(
            _iso(freeze.START + timedelta(hours=index))
            for index in range(freeze.HOUR_COUNT)
        )
        or streamflow.feature_ids != feature_ids
        or velocity.feature_ids != feature_ids
        or forcing.feature_ids != feature_ids
        or streamflow.fill_value_count != 0
        or velocity.fill_value_count != 0
        or forcing.fill_value_count != 0
    ):
        raise ValueError("horizon_holdout_static_decoded_axes_or_fill_invalid")
    discharge = np.asarray(streamflow.values_m3s[0], dtype=np.float64)
    speed = np.asarray(velocity.values_ms[0], dtype=np.float64)
    invalid_velocity = (discharge > 0.0) & (speed <= 0.0)
    if bool(invalid_velocity.any()):
        raise ValueError("horizon_holdout_static_positive_flow_zero_velocity")
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
        raise ValueError("horizon_holdout_static_physical_values_invalid")
    total_forcing = q_lateral.sum(axis=1)
    return {
        "feature_ids": np.asarray(feature_ids, dtype=np.int64),
        "initial_streamflow_m3s": discharge,
        "initial_velocity_ms": speed,
        "initial_cross_section_area_m2": area,
        "initial_storage_m3": storage,
        "q_lateral_m3s": q_lateral,
        "forcing_timestamps_utc": np.asarray(forcing.timestamps, dtype="U20"),
    }, {
        "hour_count": len(forcing.timestamps),
        "action_missing_value_count": 0,
        "initial_streamflow_fill_value_count": streamflow.fill_value_count,
        "initial_velocity_fill_value_count": velocity.fill_value_count,
        "q_lateral_fill_value_count": forcing.fill_value_count,
        "initial_storage_total_m3": float(storage.sum()),
        "distributed_q_lateral_total_mean_m3s": float(total_forcing.mean()),
        "distributed_q_lateral_total_minimum_m3s": float(total_forcing.min()),
        "distributed_q_lateral_total_maximum_m3s": float(total_forcing.max()),
    }


def _validate_frozen_plan(
    plan: Mapping[str, Any],
    *,
    plan_body: bytes,
    protocol_body: bytes,
) -> None:
    counts = plan.get("request_counts") or {}
    isolation = plan.get("data_isolation") or {}
    if (
        plan.get("schema") != frozen_plan.SCHEMA
        or plan.get("status") != "holdout_input_requests_planned_not_executed"
        or counts.get("nwm_unique_object_count") != 8
        or counts.get("cwms_action_request_count") != 2
        or counts.get("usgs_issue_observation_request_count") != 112
        or counts.get("usgs_full_outcome_request_count") != 0
        or counts.get("total_external_request_count_if_executed") != 122
        or isolation.get("network_request_executed") is not False
        or isolation.get("dynamic_value_loaded") is not False
        or plan.get("protocol", {}).get("sha256")
        != hashlib.sha256(protocol_body).hexdigest()
        or not plan_body
    ):
        raise ValueError("horizon_holdout_static_frozen_plan_invalid")


def _validate_nwm_request_identity(
    compiled: list[Mapping[str, Any]],
    frozen: list[Mapping[str, Any]],
) -> None:
    fields = ("variable", "chunk_key", "url")
    compiled_identity = {
        tuple(str(value[field]) for field in fields) for value in compiled
    }
    frozen_identity = {
        tuple(str(value[field]) for field in fields) for value in frozen
    }
    if compiled_identity != frozen_identity or len(compiled_identity) != 8:
        raise ValueError("horizon_holdout_static_nwm_request_identity_mismatch")


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("horizon_holdout_static_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("horizon_holdout_static_artifact_identity_mismatch")
    return body


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("horizon_holdout_static_json_document_required")
    return body, payload


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("horizon_holdout_static_positive_request_limits_required")
    if args.plan_only:
        report, _, _ = compile_static_plan(
            protocol_path=args.protocol,
            frozen_plan_path=args.frozen_plan,
            registry_path=args.registry,
            metadata_root=args.metadata_root,
        )
    else:
        report = acquire_static_inputs(
            protocol_path=args.protocol,
            frozen_plan_path=args.frozen_plan,
            registry_path=args.registry,
            metadata_root=args.metadata_root,
            output_root=args.output,
            proxy=args.proxy,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
        )
    _write_json(args.report, report)
    print(args.report)
    print(f"mode={report['mode']}")
    print(
        "static_requests="
        f"{report['request_execution']['static_request_count']} "
        "usgs_issue_requests_deferred="
        f"{report['request_execution']['usgs_issue_request_count_deferred']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
