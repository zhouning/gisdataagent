#!/usr/bin/env python3
"""Acquire two-system blind-validation inputs without accessing outcomes."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

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
    from scripts.acquire_geotransport_center_hill_v2_d3_inputs import (
        _fetch as _fetch_companion,
        _write_action_values,
    )
    from scripts.acquire_geotransport_center_hill_v2_d5_subnetwork_inputs import (
        _artifact,
        _fetch as _fetch_nwm,
        _opener,
        _parse_crosswalk,
        _plan,
        _request,
        _write_npy,
    )
    from scripts.build_geotransport_center_hill_smoke_panel import (
        _parse_cwms_hourly,
    )
    from scripts.freeze_geotransport_v2_blind_validation_protocol import (
        END,
        HOUR_COUNT,
        INITIAL_STATE_AT,
        INITIAL_TIME_CHUNK,
        ROLLOUT_TIME_CHUNK,
        SCHEMA as PROTOCOL_SCHEMA,
        START,
    )
else:
    from acquire_geotransport_center_hill_v2_d3_inputs import (
        _fetch as _fetch_companion,
        _write_action_values,
    )
    from acquire_geotransport_center_hill_v2_d5_subnetwork_inputs import (
        _artifact,
        _fetch as _fetch_nwm,
        _opener,
        _parse_crosswalk,
        _plan,
        _request,
        _write_npy,
    )
    from build_geotransport_center_hill_smoke_panel import _parse_cwms_hourly
    from freeze_geotransport_v2_blind_validation_protocol import (
        END,
        HOUR_COUNT,
        INITIAL_STATE_AT,
        INITIAL_TIME_CHUNK,
        ROLLOUT_TIME_CHUNK,
        SCHEMA as PROTOCOL_SCHEMA,
        START,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geotransport_v2_blind_validation_protocol.json"
)
DEFAULT_METADATA_ROOT = REPO_ROOT / "data/geotransport_v0_1/metadata"
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/geotransport_v2_blind_validation/inputs"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geotransport_v2_blind_validation_inputs_report.json"
)
SCHEMA = "gwm.geotransport.v2_blind_validation_inputs.v1"
SYSTEM_IDS = ("center_hill", "j_percy_priest")
OUTCOME_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/geotransport_v2_blind_validation/outcomes"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--metadata-root", type=Path, default=DEFAULT_METADATA_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=4)
    return parser.parse_args()


def compile_plan(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    metadata_root: Path = DEFAULT_METADATA_ROOT,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    if OUTCOME_ROOT.exists():
        raise ValueError("blind_validation_inputs_forbidden_after_outcome_access")
    protocol_body = protocol_path.read_bytes()
    protocol = json.loads(protocol_body)
    if (
        protocol.get("schema") != PROTOCOL_SCHEMA
        or protocol.get("status")
        != "frozen_before_dynamic_input_and_outcome_access"
        or (protocol.get("data_isolation_at_freeze") or {}).get(
            "outcome_artifacts_present"
        )
        is not False
    ):
        raise ValueError("blind_validation_input_protocol_invalid")
    registry = load_public_data_registry(registry_path)
    registry_systems = {
        row["system_id"]: row for row in registry.payload["systems"]
    }
    q_schema = load_nwm_zarr_schema(metadata_root)
    velocity_schema = load_nwm_velocity_schema(metadata_root)
    streamflow_schema = load_nwm_streamflow_schema(metadata_root)
    if velocity_schema.base != q_schema or streamflow_schema.base != q_schema:
        raise ValueError("blind_validation_nwm_schema_mismatch")

    systems: dict[str, dict[str, Any]] = {}
    requests_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for system_id in SYSTEM_IDS:
        lock = protocol["systems"][system_id]
        topology_body = _read_verified(lock["topology_report"])
        topology = json.loads(topology_body)
        artifacts = topology["artifacts"]
        network_body = _read_verified(artifacts["full_subnetwork"])
        network = json.loads(network_body)["network"]
        feature_ids = tuple(int(value) for value in network["feature_ids"])
        effective_lengths = tuple(
            float(value) for value in network["effective_lengths_m"]
        )
        feature_indices = _parse_crosswalk(
            _read_verified(artifacts["nwm_feature_crosswalk"]), feature_ids
        )
        feature_chunks = tuple(
            sorted({index // 30_000 for index in feature_indices})
        )
        if feature_chunks != tuple(lock["feature_chunk_indices"]):
            raise ValueError(
                f"blind_validation_{system_id}_feature_chunk_mismatch"
            )
        initial_plan = _plan(
            system_id=f"{system_id}_blind_initial_state",
            start=INITIAL_STATE_AT,
            end=INITIAL_STATE_AT + timedelta(hours=1),
            schema=q_schema,
            feature_ids=feature_ids,
            feature_indices=feature_indices,
            expected_time_chunk=INITIAL_TIME_CHUNK,
        )
        forcing_plan = _plan(
            system_id=f"{system_id}_blind_forcing",
            start=START,
            end=END,
            schema=q_schema,
            feature_ids=feature_ids,
            feature_indices=feature_indices,
            expected_time_chunk=ROLLOUT_TIME_CHUNK,
        )
        for variable, time_chunk in (
            ("streamflow", INITIAL_TIME_CHUNK),
            ("velocity", INITIAL_TIME_CHUNK),
            ("q_lateral", ROLLOUT_TIME_CHUNK),
        ):
            for feature_chunk in feature_chunks:
                request = _request(variable, f"{time_chunk}.{feature_chunk}")
                requests_by_key[(variable, request["chunk_key"])] = request
        for time_chunk in (INITIAL_TIME_CHUNK, ROLLOUT_TIME_CHUNK):
            request = _request("time", str(time_chunk))
            requests_by_key[("time", request["chunk_key"])] = request
        systems[system_id] = {
            "lock": lock,
            "registry": registry_systems[system_id],
            "topology": topology,
            "topology_body": topology_body,
            "network": network,
            "feature_ids": feature_ids,
            "feature_indices": feature_indices,
            "feature_chunks": feature_chunks,
            "effective_lengths": effective_lengths,
            "initial_plan": initial_plan,
            "forcing_plan": forcing_plan,
        }
    requests = [requests_by_key[key] for key in sorted(requests_by_key)]
    plan = {
        "schema": SCHEMA,
        "mode": "plan",
        "status": "ready_to_acquire_outcome_free_two_system_inputs",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": _artifact(protocol_path, protocol_body),
        "registry": _artifact(registry_path, registry_path.read_bytes()),
        "window": protocol["window"],
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
        "nwm_unique_object_count": len(requests),
        "action_request_count": len(SYSTEM_IDS),
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
            "action": {
                "role": "observed_boundary_action",
                "outcome": False,
                "ground_truth_for_downstream_streamflow": False,
            },
        },
        "data_isolation": {
            "outcome_url_requested": False,
            "outcome_path_accepted": False,
            "outcome_values_loaded": False,
            "outcome_artifacts_present": False,
        },
        "claim_boundary": {
            "request_plan_only": True,
            "public_data_without_user_supplied_data": True,
            "dynamic_inputs_acquired": False,
            "outcome_free_predictions_sealed": False,
            "outcomes_acquired": False,
            "geospatial_kernel_validated": False,
        },
    }
    schemas = {
        "q": q_schema,
        "velocity": velocity_schema,
        "streamflow": streamflow_schema,
    }
    return plan, systems, schemas


def acquire(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    metadata_root: Path = DEFAULT_METADATA_ROOT,
    output_root: Path = DEFAULT_OUTPUT,
    proxy: str = "http://127.0.0.1:7897",
    timeout_seconds: float = 180.0,
    retries: int = 4,
) -> dict[str, Any]:
    plan, systems, schemas = compile_plan(
        protocol_path=protocol_path,
        registry_path=registry_path,
        metadata_root=metadata_root,
    )
    opener = _opener(proxy)
    raw: dict[tuple[str, str], bytes] = {}
    raw_artifacts: list[dict[str, Any]] = []
    for request in plan["nwm_requests"]:
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
        START + timedelta(hours=index) for index in range(HOUR_COUNT)
    )
    support_ends = tuple(value + timedelta(hours=1) for value in support_starts)
    system_results: dict[str, dict[str, Any]] = {}
    for system_id, context in systems.items():
        lock = context["lock"]
        action_body, action_retrieval = _fetch_companion(
            lock["action"]["url"],
            opener=opener,
            timeout=timeout_seconds,
            retries=retries,
            maximum_bytes=2_000_000,
        )
        action_raw_path = output_root / f"raw/action/{system_id}.json"
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
        initial_plan = context["initial_plan"]
        forcing_plan = context["forcing_plan"]
        chunks = context["feature_chunks"]
        initial_time = raw[("time", str(INITIAL_TIME_CHUNK))]
        forcing_time = raw[("time", str(ROLLOUT_TIME_CHUNK))]
        streamflow = extract_nwm_streamflow(
            initial_plan,
            schemas["streamflow"],
            time_chunks={INITIAL_TIME_CHUNK: initial_time},
            streamflow_chunks={
                (INITIAL_TIME_CHUNK, chunk): raw[
                    ("streamflow", f"{INITIAL_TIME_CHUNK}.{chunk}")
                ]
                for chunk in chunks
            },
        )
        velocity = extract_nwm_velocity(
            initial_plan,
            schemas["velocity"],
            time_chunks={INITIAL_TIME_CHUNK: initial_time},
            velocity_chunks={
                (INITIAL_TIME_CHUNK, chunk): raw[
                    ("velocity", f"{INITIAL_TIME_CHUNK}.{chunk}")
                ]
                for chunk in chunks
            },
        )
        forcing = extract_nwm_q_lateral(
            forcing_plan,
            schemas["q"],
            time_chunks={ROLLOUT_TIME_CHUNK: forcing_time},
            q_chunks={
                (ROLLOUT_TIME_CHUNK, chunk): raw[
                    ("q_lateral", f"{ROLLOUT_TIME_CHUNK}.{chunk}")
                ]
                for chunk in chunks
            },
        )
        _validate_decoded_axes(context, streamflow, velocity, forcing)
        discharge = np.asarray(streamflow.values_m3s[0], dtype=np.float64)
        speed = np.asarray(velocity.values_ms[0], dtype=np.float64)
        invalid_velocity = (discharge > 0.0) & (speed <= 0.0)
        if bool(invalid_velocity.any()):
            raise ValueError(
                f"blind_validation_{system_id}_positive_flow_zero_velocity"
            )
        area = np.divide(
            discharge,
            speed,
            out=np.zeros_like(discharge),
            where=speed > 0.0,
        )
        storage = area * np.asarray(context["effective_lengths"], dtype=float)
        q_lateral = np.asarray(forcing.values_m3s, dtype=np.float64)
        if (
            not np.isfinite(storage).all()
            or bool((storage < 0.0).any())
            or not np.isfinite(q_lateral).all()
            or bool((q_lateral < 0.0).any())
        ):
            raise ValueError(f"blind_validation_{system_id}_physical_values_invalid")
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
            path = output_root / f"systems/{system_id}/decoded/{name}.npy"
            _write_npy(path, values)
            array_artifacts[name] = {
                **_artifact(path, path.read_bytes()),
                "dtype": str(values.dtype),
                "shape": list(values.shape),
            }
        total_forcing = q_lateral.sum(axis=1)
        system_results[system_id] = {
            "topology_report": context["lock"]["topology_report"],
            "feature_count": len(context["feature_ids"]),
            "feature_chunk_indices": list(chunks),
            "action_raw": {
                **action_retrieval,
                **_artifact(action_raw_path, action_body),
            },
            "action_values": _artifact(action_path, action_path.read_bytes()),
            "action_quality_codes": sorted(set(action_quality.values())),
            "decoded_arrays": array_artifacts,
            "result": {
                "hour_count": len(forcing.timestamps),
                "action_missing_value_count": 0,
                "initial_streamflow_fill_value_count": streamflow.fill_value_count,
                "initial_velocity_fill_value_count": velocity.fill_value_count,
                "q_lateral_fill_value_count": forcing.fill_value_count,
                "initial_storage_total_m3": float(storage.sum()),
                "distributed_q_lateral_total_mean_m3s": float(
                    total_forcing.mean()
                ),
                "distributed_q_lateral_total_minimum_m3s": float(
                    total_forcing.min()
                ),
                "distributed_q_lateral_total_maximum_m3s": float(
                    total_forcing.max()
                ),
            },
        }
    return {
        **plan,
        "mode": "acquired",
        "status": "pass_outcome_free_two_system_inputs_acquired",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "raw_nwm_artifacts": raw_artifacts,
        "systems": system_results,
        "data_isolation": {
            "outcome_url_requested": False,
            "outcome_path_accepted": False,
            "outcome_values_loaded": False,
            "outcome_artifacts_present": False,
        },
        "claim_boundary": {
            "request_plan_only": False,
            "public_data_without_user_supplied_data": True,
            "dynamic_inputs_acquired": True,
            "initial_state_ground_truth": False,
            "initial_state_possible_nudging": True,
            "q_lateral_ground_truth": False,
            "outcome_free_predictions_sealed": False,
            "outcomes_acquired": False,
            "geospatial_kernel_validated": False,
        },
    }


def _validate_decoded_axes(
    context: Mapping[str, Any], streamflow: Any, velocity: Any, forcing: Any
) -> None:
    features = context["feature_ids"]
    if (
        streamflow.timestamps != (_iso(INITIAL_STATE_AT),)
        or velocity.timestamps != streamflow.timestamps
        or forcing.timestamps
        != tuple(_iso(START + timedelta(hours=index)) for index in range(HOUR_COUNT))
        or streamflow.feature_ids != features
        or velocity.feature_ids != features
        or forcing.feature_ids != features
        or streamflow.fill_value_count != 0
        or velocity.fill_value_count != 0
        or forcing.fill_value_count != 0
    ):
        raise ValueError("blind_validation_decoded_axes_or_fill_invalid")


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("blind_validation_input_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("blind_validation_input_artifact_identity_mismatch")
    return body


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
        raise ValueError("blind_validation_positive_request_limits_required")
    if args.plan_only:
        report, _, _ = compile_plan(
            protocol_path=args.protocol,
            registry_path=args.registry,
            metadata_root=args.metadata_root,
        )
    else:
        report = acquire(
            protocol_path=args.protocol,
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
    print(f"nwm_unique_object_count={report['nwm_unique_object_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
