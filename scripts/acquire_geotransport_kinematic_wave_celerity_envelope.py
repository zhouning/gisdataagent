#!/usr/bin/env python3
"""Acquire public NWM state and compile outcome-free path celerity envelopes."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from data_agent.uwm.geospatial_kernel_v2.manning_path_response import (
    MANNING_PATH_RESPONSE_SCHEMA,
    ManningPathResponseDiagnostic,
)
from data_agent.uwm.geospatial_kernel_v2.nwm_q_lateral import (
    extract_nwm_streamflow,
    extract_nwm_velocity,
    load_nwm_streamflow_schema,
    load_nwm_velocity_schema,
    load_nwm_zarr_schema,
)

if __package__:
    from scripts.acquire_geotransport_center_hill_v2_d5_subnetwork_inputs import (
        _artifact,
        _fetch,
        _opener,
        _parse_crosswalk,
        _plan,
        _read_verified,
        _request,
        _write_npy,
    )
    from scripts.run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
        _geometry,
        _network,
    )
else:
    from acquire_geotransport_center_hill_v2_d5_subnetwork_inputs import (
        _artifact,
        _fetch,
        _opener,
        _parse_crosswalk,
        _plan,
        _read_verified,
        _request,
        _write_npy,
    )
    from run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
        _geometry,
        _network,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
INPUT_REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_inputs_report.json"
)
METADATA_ROOT = REPO_ROOT / "data/geotransport_v0_1/metadata"
OUTPUT_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/kinematic_wave_celerity_envelope"
)
PLAN_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_celerity_envelope_plan.json"
)
REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_celerity_envelope_report.json"
)
START = datetime(2022, 3, 31, 1, tzinfo=timezone.utc)
END = datetime(2022, 4, 28, 1, tzinfo=timezone.utc)
TIME_CHUNK = 563
HOUR_COUNT = 672
SYSTEM_IDS = ("center_hill", "j_percy_priest")
SCHEMA = "gwm.geotransport.kinematic_wave_celerity_envelope.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=4)
    return parser.parse_args()


def compile_plan() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    input_body = INPUT_REPORT_PATH.read_bytes()
    inputs = json.loads(input_body)
    if (
        inputs.get("status") != "pass_outcome_free_two_system_inputs_acquired"
        or inputs.get("window", {}).get("start_inclusive") != _iso(START)
        or inputs.get("window", {}).get("end_exclusive") != _iso(END)
        or inputs.get("window", {}).get("hour_count") != HOUR_COUNT
        or set(inputs.get("systems", {})) != set(SYSTEM_IDS)
    ):
        raise ValueError("celerity_envelope_input_report_invalid")

    q_schema = load_nwm_zarr_schema(METADATA_ROOT)
    streamflow_schema = load_nwm_streamflow_schema(METADATA_ROOT)
    velocity_schema = load_nwm_velocity_schema(METADATA_ROOT)
    if streamflow_schema.base != q_schema or velocity_schema.base != q_schema:
        raise ValueError("celerity_envelope_nwm_schema_mismatch")
    time_descriptor = next(
        row
        for row in inputs["raw_nwm_artifacts"]
        if row["variable"] == "time" and row["chunk_key"] == str(TIME_CHUNK)
    )

    contexts: dict[str, dict[str, Any]] = {}
    requests: dict[tuple[str, str], dict[str, Any]] = {}
    for system_id in SYSTEM_IDS:
        source = inputs["systems"][system_id]
        topology_body = _read_verified(source["topology_report"])
        topology = json.loads(topology_body)
        network_body = _read_verified(topology["artifacts"]["full_subnetwork"])
        network_payload = json.loads(network_body)["network"]
        network = _network(network_payload)
        feature_ids = network.feature_ids
        feature_indices = _parse_crosswalk(
            _read_verified(topology["artifacts"]["nwm_feature_crosswalk"]),
            feature_ids,
        )
        plan = _plan(
            system_id=f"{system_id}_development_celerity_envelope",
            start=START,
            end=END,
            schema=q_schema,
            feature_ids=feature_ids,
            feature_indices=feature_indices,
            expected_time_chunk=TIME_CHUNK,
        )
        if tuple(source["feature_chunk_indices"]) != plan.feature_chunk_indices:
            raise ValueError(f"celerity_envelope_{system_id}_chunk_mismatch")
        route_link_descriptor = topology["artifacts"]["route_link_subset"]
        route_link_body = _read_verified(route_link_descriptor)
        geometry = _geometry(
            REPO_ROOT / str(route_link_descriptor["path"]),
            network,
            route_link_body,
        )
        for variable in ("streamflow", "velocity"):
            for feature_chunk in plan.feature_chunk_indices:
                request = _request(variable, f"{TIME_CHUNK}.{feature_chunk}")
                requests[(variable, request["chunk_key"])] = request
        contexts[system_id] = {
            "source": source,
            "topology": topology,
            "network": network,
            "geometry": geometry,
            "plan": plan,
            "route_link_descriptor": route_link_descriptor,
        }

    plan_payload = {
        "schema": SCHEMA,
        "mode": "plan",
        "status": "ready_to_acquire_public_modeled_state_context",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "start_inclusive": _iso(START),
            "end_exclusive": _iso(END),
            "hour_count": HOUR_COUNT,
            "time_chunk": TIME_CHUNK,
        },
        "input_report": _artifact(INPUT_REPORT_PATH, input_body),
        "time_chunk": time_descriptor,
        "requests": [requests[key] for key in sorted(requests)],
        "unique_request_count": len(requests),
        "systems": {
            system_id: {
                "feature_count": len(context["network"].feature_ids),
                "feature_chunk_indices": list(
                    context["plan"].feature_chunk_indices
                ),
                "action_entry_feature_id": context[
                    "network"
                ].action_entry_feature_ids[0],
                "outlet_feature_id": context["network"].outlet_feature_id,
                "topology_report": context["source"]["topology_report"],
                "route_link_subset": context["route_link_descriptor"],
            }
            for system_id, context in contexts.items()
        },
        "semantic_contract": {
            "streamflow": "NWM retrospective modeled state; not ground truth",
            "velocity": (
                "NWM retrospective modeled advective velocity proxy; not "
                "flood-wave celerity"
            ),
            "manning_celerity": (
                "RouteLink geometry and NWM streamflow evaluated as dQ/dA; "
                "candidate diagnostic only"
            ),
            "outcome_values_used": False,
        },
        "claim_boundary": {
            "public_data_without_user_supplied_data": True,
            "outcomes_visible_before_diagnostic_defined": True,
            "outcome_artifacts_read_by_acquisition": False,
            "nwm_state_possible_nudging": True,
            "nwm_velocity_admitted_as_flood_wave_celerity": False,
            "manning_path_response_admitted": False,
            "geospatial_kernel_validated": False,
        },
    }
    contexts["_shared"] = {
        "inputs": inputs,
        "input_body": input_body,
        "q_schema": q_schema,
        "streamflow_schema": streamflow_schema,
        "velocity_schema": velocity_schema,
        "time_descriptor": time_descriptor,
    }
    return plan_payload, contexts


def acquire(
    *,
    proxy: str,
    timeout_seconds: float,
    retries: int,
) -> dict[str, Any]:
    plan_payload, contexts = compile_plan()
    shared = contexts.pop("_shared")
    opener = _opener(proxy)
    raw: dict[tuple[str, str], bytes] = {}
    raw_artifacts: list[dict[str, Any]] = []
    for request in plan_payload["requests"]:
        variable = str(request["variable"])
        key = str(request["chunk_key"])
        path = OUTPUT_ROOT / f"raw/{variable}/{key}.zst"
        if path.exists():
            body = path.read_bytes()
            retrieval = {
                "url": request["url"],
                "retrieval_mode": "verified_local_retry_reuse",
            }
        else:
            body, retrieval = _fetch(
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

    time_body = _read_verified(shared["time_descriptor"])
    systems: dict[str, dict[str, Any]] = {}
    for system_id in SYSTEM_IDS:
        context = contexts[system_id]
        plan = context["plan"]
        chunks = plan.feature_chunk_indices
        streamflow = extract_nwm_streamflow(
            plan,
            shared["streamflow_schema"],
            time_chunks={TIME_CHUNK: time_body},
            streamflow_chunks={
                (TIME_CHUNK, chunk): raw[
                    ("streamflow", f"{TIME_CHUNK}.{chunk}")
                ]
                for chunk in chunks
            },
        )
        velocity = extract_nwm_velocity(
            plan,
            shared["velocity_schema"],
            time_chunks={TIME_CHUNK: time_body},
            velocity_chunks={
                (TIME_CHUNK, chunk): raw[("velocity", f"{TIME_CHUNK}.{chunk}")]
                for chunk in chunks
            },
        )
        systems[system_id] = _compile_system(
            system_id=system_id,
            context=context,
            streamflow=streamflow,
            velocity=velocity,
        )

    return {
        **plan_payload,
        "mode": "acquired_and_compiled",
        "status": "public_modeled_state_celerity_envelopes_compiled",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "raw_artifacts": raw_artifacts,
        "systems": systems,
        "claim_boundary": {
            **plan_payload["claim_boundary"],
            "public_state_context_acquired": True,
            "state_dependent_celerity_envelope_compiled": True,
            "manning_path_response_admitted": False,
            "geospatial_kernel_validated": False,
        },
    }


def _compile_system(
    *,
    system_id: str,
    context: Mapping[str, Any],
    streamflow: Any,
    velocity: Any,
) -> dict[str, Any]:
    network = context["network"]
    if (
        streamflow.timestamps != velocity.timestamps
        or streamflow.feature_ids != network.feature_ids
        or velocity.feature_ids != network.feature_ids
        or streamflow.values_m3s.shape != (HOUR_COUNT, len(network.feature_ids))
        or velocity.values_ms.shape != streamflow.values_m3s.shape
        or streamflow.fill_value_count != 0
        or velocity.fill_value_count != 0
        or not np.isfinite(streamflow.values_m3s).all()
        or not np.isfinite(velocity.values_ms).all()
        or bool((streamflow.values_m3s < 0.0).any())
        or bool((velocity.values_ms < 0.0).any())
    ):
        raise ValueError(f"celerity_envelope_{system_id}_decoded_axis_invalid")

    decoded = {
        "feature_ids": np.asarray(network.feature_ids, dtype=np.int64),
        "state_timestamps_utc": np.asarray(streamflow.timestamps, dtype="U20"),
        "streamflow_m3s": np.asarray(streamflow.values_m3s, dtype=np.float64),
        "velocity_ms": np.asarray(velocity.values_ms, dtype=np.float64),
    }
    decoded_artifacts: dict[str, dict[str, Any]] = {}
    for name, values in decoded.items():
        path = OUTPUT_ROOT / f"systems/{system_id}/decoded/{name}.npy"
        _write_npy(path, values)
        decoded_artifacts[name] = {
            **_artifact(path, path.read_bytes()),
            "dtype": str(values.dtype),
            "shape": list(values.shape),
        }

    diagnostic = ManningPathResponseDiagnostic(
        network,
        context["geometry"],
    )
    index = {feature: offset for offset, feature in enumerate(network.feature_ids)}
    rows: list[dict[str, object]] = []
    manning_times: list[float] = []
    advective_times: list[float] = []
    area_ratios: list[float] = []
    celerity_velocity_ratios: list[float] = []
    nonpropagating_hours = 0
    invalid_advective_hours = 0
    for hour, timestamp in enumerate(streamflow.timestamps):
        response = diagnostic.analyze(
            tuple(float(value) for value in streamflow.values_m3s[hour]),
            start_feature_id=network.action_entry_feature_ids[0],
            end_feature_id=network.outlet_feature_id,
            path_id=f"{system_id}:nwm-state:{timestamp}",
            provenance_id=(
                f"nwm-v3:streamflow:{TIME_CHUNK}:"
                f"{context['route_link_descriptor']['sha256']}"
            ),
            evidence_level="candidate",
            outcome_calibrated=False,
        )
        path_indices = np.asarray(
            [index[feature] for feature in response.feature_ids], dtype=int
        )
        path_velocity = velocity.values_ms[hour, path_indices]
        path_flow = streamflow.values_m3s[hour, path_indices]
        lengths = np.asarray(
            [value.effective_length_m for value in response.reaches], dtype=float
        )
        positive = (path_flow > 0.0) & (path_velocity > 0.0)
        for offset, reach in enumerate(response.reaches):
            if positive[offset]:
                area_proxy = path_flow[offset] / path_velocity[offset]
                area_ratios.append(reach.manning_area_m2 / area_proxy)
                celerity_velocity_ratios.append(
                    reach.manning_dq_da_celerity_mps / path_velocity[offset]
                )
        if response.total_travel_time_seconds is None:
            nonpropagating_hours += 1
            manning_hours: float | None = None
        else:
            manning_hours = response.total_travel_time_seconds / 3600.0
            manning_times.append(manning_hours)
        if bool((path_velocity <= 0.0).any()):
            invalid_advective_hours += 1
            advective_hours: float | None = None
        else:
            advective_hours = float(np.sum(lengths / path_velocity) / 3600.0)
            advective_times.append(advective_hours)
        rows.append(
            {
                "state_valid_at_utc": timestamp,
                "manning_path_travel_time_hours": _optional(manning_hours),
                "manning_effective_celerity_mps": _optional(
                    response.effective_celerity_mps
                ),
                "nwm_velocity_advective_path_time_hours": _optional(
                    advective_hours
                ),
                "path_streamflow_minimum_m3s": float(path_flow.min()),
                "path_streamflow_median_m3s": float(np.median(path_flow)),
                "path_streamflow_maximum_m3s": float(path_flow.max()),
                "nonpropagating_reach_count": len(
                    response.nonpropagating_feature_ids
                ),
            }
        )

    csv_body = _encode_rows(rows)
    csv_path = OUTPUT_ROOT / f"systems/{system_id}/path_response.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_bytes(csv_body)
    return {
        "system_id": system_id,
        "path_response_schema": MANNING_PATH_RESPONSE_SCHEMA,
        "path_feature_ids": list(
            diagnostic.analyze(
                tuple(float(value) for value in streamflow.values_m3s[0]),
                start_feature_id=network.action_entry_feature_ids[0],
                end_feature_id=network.outlet_feature_id,
                path_id=f"{system_id}:path-identity",
                provenance_id="path-identity-only",
                evidence_level="candidate",
                outcome_calibrated=False,
            ).feature_ids
        ),
        "decoded_arrays": decoded_artifacts,
        "path_response_values": _artifact(csv_path, csv_body),
        "quality": {
            "state_hour_count": HOUR_COUNT,
            "streamflow_fill_value_count": streamflow.fill_value_count,
            "velocity_fill_value_count": velocity.fill_value_count,
            "nonpropagating_path_hour_count": nonpropagating_hours,
            "invalid_advective_path_hour_count": invalid_advective_hours,
        },
        "envelopes": {
            "manning_wave_travel_time_hours_q05_q50_q95": _quantiles(
                manning_times
            ),
            "nwm_velocity_advective_path_time_hours_q05_q50_q95": _quantiles(
                advective_times
            ),
            "manning_to_nwm_area_proxy_ratio_q05_q50_q95": _quantiles(
                area_ratios
            ),
            "manning_celerity_to_nwm_velocity_ratio_q05_q50_q95": _quantiles(
                celerity_velocity_ratios
            ),
        },
        "semantic_contract": {
            "streamflow_ground_truth": False,
            "streamflow_possible_nudging": True,
            "nwm_velocity_is_flood_wave_celerity": False,
            "manning_envelope_outcome_calibrated": False,
            "manning_envelope_admitted_as_flood_wave_lag": False,
        },
    }


def _quantiles(values: list[float]) -> list[float] | None:
    if not values:
        return None
    return [float(value) for value in np.quantile(values, (0.05, 0.5, 0.95))]


def _optional(value: float | None) -> object:
    return "" if value is None else value


def _encode_rows(rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


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
        raise ValueError("celerity_envelope_positive_request_limits_required")
    target = PLAN_PATH if args.plan_only else REPORT_PATH
    if target.exists() and not args.overwrite:
        raise ValueError("celerity_envelope_refuses_overwrite")
    if args.plan_only:
        payload, _ = compile_plan()
    else:
        payload = acquire(
            proxy=args.proxy,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
        )
    _write_json(target, payload)
    print(target)
    if not args.plan_only:
        for system_id in SYSTEM_IDS:
            quantiles = payload["systems"][system_id]["envelopes"][
                "manning_wave_travel_time_hours_q05_q50_q95"
            ]
            print(
                f"{system_id}_manning_hours_q05_q50_q95={quantiles}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
