#!/usr/bin/env python3
"""Acquire a pre-chunk-561 NWM modeled hydraulic state for Center Hill."""

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

import numpy as np
from scipy.io import netcdf_file

from data_agent.uwm.geospatial_kernel_v2 import (
    DEFAULT_REGISTRY_PATH,
    build_nwm_q_lateral_plan,
    extract_nwm_streamflow,
    extract_nwm_velocity,
    load_nwm_streamflow_schema,
    load_nwm_velocity_schema,
    load_public_data_registry,
    nwm_chunk_url,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METADATA_ROOT = REPO_ROOT / "data/geotransport_v0_1/metadata"
DEFAULT_EVALUATION_NWM_MANIFEST = (
    REPO_ROOT
    / "data/geotransport_v0_1/center_hill_evaluation/nwm/"
    "acquisition_manifest.json"
)
DEFAULT_ROUTE_LINK_MANIFEST = (
    REPO_ROOT
    / "data/geotransport_v0_1/route_link_nwm_v3_center_hill/"
    "acquisition_manifest.json"
)
DEFAULT_TRAVEL_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_travel_time_prior_report.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "data/geotransport_v0_1/center_hill_initial_state_nwm_v3"
)
SCHEMA = "gwm.geotransport.center_hill_nwm_v3_initial_state.v1"
ALLOWED_HOST = "noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com"
USER_AGENT = "gisdataagent-center-hill-initial-state/0.1"
INITIAL_VALID_AT = "2022-02-03T00:00:00Z"
NEXT_WINDOW_START = "2022-02-03T01:00:00Z"
TIME_CHUNK_INDEX = 560
FEATURE_CHUNK_INDEX = 63
STREAMFLOW_KEY = "560.63"
MAXIMUM_STREAMFLOW_BYTES = 100_000_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--metadata-root", type=Path, default=DEFAULT_METADATA_ROOT)
    parser.add_argument(
        "--evaluation-nwm-manifest",
        type=Path,
        default=DEFAULT_EVALUATION_NWM_MANIFEST,
    )
    parser.add_argument(
        "--route-link-manifest", type=Path, default=DEFAULT_ROUTE_LINK_MANIFEST
    )
    parser.add_argument("--travel-report", type=Path, default=DEFAULT_TRAVEL_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--accept-modeled-initial-state", action="store_true")
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def compile_plan(
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    metadata_root: Path = DEFAULT_METADATA_ROOT,
    evaluation_nwm_manifest_path: Path = DEFAULT_EVALUATION_NWM_MANIFEST,
    route_link_manifest_path: Path = DEFAULT_ROUTE_LINK_MANIFEST,
    travel_report_path: Path = DEFAULT_TRAVEL_REPORT,
    values_mode: bool = False,
) -> tuple[dict[str, Any], Any, Any, Any]:
    registry = load_public_data_registry(registry_path)
    streamflow_schema = load_nwm_streamflow_schema(metadata_root)
    velocity_schema = load_nwm_velocity_schema(metadata_root)
    if streamflow_schema.base != velocity_schema.base:
        raise ValueError("initial_state_nwm_base_schema_mismatch")
    plan = build_nwm_q_lateral_plan(
        registry,
        streamflow_schema.base,
        system_id="center_hill",
        start=INITIAL_VALID_AT,
        end=NEXT_WINDOW_START,
    )
    if (
        plan.time_chunk_indices != (TIME_CHUNK_INDEX,)
        or plan.q_chunk_keys
        != ((TIME_CHUNK_INDEX, FEATURE_CHUNK_INDEX),)
        or plan.time_count != 1
    ):
        raise ValueError("initial_state_nwm_frozen_chunk_plan_mismatch")

    evaluation_body = evaluation_nwm_manifest_path.read_bytes()
    evaluation = json.loads(evaluation_body)
    reused = _validate_reused_evaluation_inputs(evaluation)
    route_body = route_link_manifest_path.read_bytes()
    route_manifest = json.loads(route_body)
    route_descriptor = _validate_route_link_manifest(route_manifest, plan.feature_ids)
    travel_body = travel_report_path.read_bytes()
    travel = json.loads(travel_body)
    _validate_travel_report(travel, plan.feature_ids)
    request = {
        "variable": "streamflow",
        "key": STREAMFLOW_KEY,
        "url": nwm_chunk_url("streamflow", STREAMFLOW_KEY),
        "maximum_bytes": MAXIMUM_STREAMFLOW_BYTES,
    }
    manifest = {
        "schema": SCHEMA,
        "mode": "values" if values_mode else "plan",
        "system_id": "center_hill",
        "initial_state_support": {
            "valid_at": INITIAL_VALID_AT,
            "next_window_start": NEXT_WINDOW_START,
            "lead_time_to_next_window_seconds": 3600,
            "time_chunk_indices_read": [TIME_CHUNK_INDEX],
            "time_chunk_indices_forbidden": [561],
            "chunk_561_accessed": False,
        },
        "feature_ids": list(plan.feature_ids),
        "feature_indices": list(plan.feature_indices),
        "request": request,
        "reused_inputs": reused,
        "source_artifacts": {
            "registry": _artifact(registry_path, registry_path.read_bytes()),
            "evaluation_nwm_manifest": _artifact(
                evaluation_nwm_manifest_path, evaluation_body
            ),
            "route_link_manifest": _artifact(route_link_manifest_path, route_body),
            "route_link_subset": route_descriptor,
            "travel_report": _artifact(travel_report_path, travel_body),
        },
        "metadata_root": _display(metadata_root),
        "metadata_sha256": {
            "streamflow": dict(streamflow_schema.metadata_sha256),
            "velocity": dict(velocity_schema.metadata_sha256),
        },
        "source_semantics": {
            "streamflow": {
                "role": "modeled_initial_state",
                "ground_truth": False,
                "units": "m3 s-1",
                "may_include_nwm_streamflow_nudging": True,
            },
            "velocity": {
                "role": "modeled_initial_state_context",
                "ground_truth": False,
                "units": "m s-1",
                "admitted_as_flood_wave_celerity": False,
            },
            "availability": {
                "retrospective_publication": True,
                "operational_online_availability_at_valid_time_verified": False,
            },
        },
        "claim_boundary": {
            "request_plan_only": not values_mode,
            "streamflow_object_acquired": values_mode,
            "retrospective_modeled_initial_state_available": False,
            "operational_online_initial_state_available": False,
            "evaluation_outcome_loaded": False,
            "chunk_561_loaded": False,
            "center_hill_transition_execution_admitted": False,
            "benchmark_validated": False,
            "geospatial_kernel_validated": False,
        },
    }
    return manifest, plan, streamflow_schema, velocity_schema


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("initial_state_positive_request_limits_required")
    manifest, plan, streamflow_schema, velocity_schema = compile_plan(
        registry_path=args.registry,
        metadata_root=args.metadata_root,
        evaluation_nwm_manifest_path=args.evaluation_nwm_manifest,
        route_link_manifest_path=args.route_link_manifest,
        travel_report_path=args.travel_report,
        values_mode=not args.plan_only,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    if args.plan_only:
        output = args.output / "acquisition_plan.json"
        _write_json(output, manifest)
        print(output)
        return 0
    if not args.accept_modeled_initial_state:
        raise ValueError("initial_state_values_require_explicit_modeled_acceptance")

    request = manifest["request"]
    body, retrieval = _fetch(
        request["url"],
        proxy=args.proxy,
        timeout_seconds=args.timeout_seconds,
        retries=args.retries,
        maximum_bytes=request["maximum_bytes"],
    )
    streamflow_path = args.output / "raw/streamflow/560.63.zst"
    streamflow_path.parent.mkdir(parents=True, exist_ok=True)
    streamflow_path.write_bytes(body)
    streamflow_artifact = {
        **retrieval,
        "variable": "streamflow",
        "key": STREAMFLOW_KEY,
        **_artifact(streamflow_path, body),
    }

    reused = manifest["reused_inputs"]
    time_body = _read_verified_artifact(reused["time"])
    velocity_body = _read_verified_artifact(reused["velocity"])
    streamflow = extract_nwm_streamflow(
        plan,
        streamflow_schema,
        time_chunks={TIME_CHUNK_INDEX: time_body},
        streamflow_chunks={(TIME_CHUNK_INDEX, FEATURE_CHUNK_INDEX): body},
    )
    velocity = extract_nwm_velocity(
        plan,
        velocity_schema,
        time_chunks={TIME_CHUNK_INDEX: time_body},
        velocity_chunks={(TIME_CHUNK_INDEX, FEATURE_CHUNK_INDEX): velocity_body},
    )
    if (
        streamflow.timestamps != (INITIAL_VALID_AT,)
        or velocity.timestamps != streamflow.timestamps
        or velocity.feature_ids != streamflow.feature_ids
        or streamflow.fill_value_count != 0
        or velocity.fill_value_count != 0
    ):
        raise ValueError("initial_state_decoded_axes_or_fill_invalid")

    route_descriptor = manifest["source_artifacts"]["route_link_subset"]
    route_body = _read_verified_artifact(route_descriptor)
    route_path = REPO_ROOT / route_descriptor["path"]
    travel = json.loads(args.travel_report.read_bytes())
    compiled = _compile_initial_state(
        feature_ids=streamflow.feature_ids,
        discharge_m3s=streamflow.values_m3s[0],
        velocity_ms=velocity.values_ms[0],
        route_link_path=route_path,
        travel=travel,
        available_at=retrieval["retrieved_at"],
    )
    manifest["decoded_source"] = {
        "timestamps": list(streamflow.timestamps),
        "feature_count": len(streamflow.feature_ids),
        "feature_axis_coverage": (
            f"{len(streamflow.feature_ids)}/{len(plan.feature_ids)}"
        ),
        "streamflow_fill_value_count": streamflow.fill_value_count,
        "velocity_fill_value_count": velocity.fill_value_count,
        "active_feature_count": compiled["active_feature_count"],
    }
    state_path = args.output / "initial_state.csv"
    _write_state_csv(state_path, compiled["rows"])
    state_body = state_path.read_bytes()

    manifest["retrieved_at"] = retrieval["retrieved_at"]
    manifest["streamflow_raw_artifact"] = streamflow_artifact
    manifest["decoded_state"] = {
        key: value for key, value in compiled.items() if key != "rows"
    }
    manifest["initial_state_artifact"] = _artifact(state_path, state_body)
    manifest["route_link_subset_reverified_sha256"] = hashlib.sha256(
        route_body
    ).hexdigest()
    manifest["claim_boundary"].update(
        {
            "retrospective_modeled_initial_state_available": True,
            "operational_online_initial_state_available": False,
            "center_hill_transition_execution_admitted": False,
        }
    )
    output = args.output / "acquisition_manifest.json"
    _write_json(output, manifest)
    print(output)
    return 0


def _compile_initial_state(
    *,
    feature_ids: tuple[int, ...],
    discharge_m3s: np.ndarray,
    velocity_ms: np.ndarray,
    route_link_path: Path,
    travel: Mapping[str, Any],
    available_at: str,
) -> dict[str, Any]:
    discharge = np.asarray(discharge_m3s, dtype=float)
    velocity = np.asarray(velocity_ms, dtype=float)
    if (
        discharge.shape != (len(feature_ids),)
        or velocity.shape != discharge.shape
        or not np.isfinite(discharge).all()
        or not np.isfinite(velocity).all()
        or bool((discharge < 0.0).any())
        or bool((velocity < 0.0).any())
    ):
        raise ValueError("initial_state_hydraulic_values_invalid")
    path = travel["linear_referenced_path"]
    if tuple(int(value) for value in path["feature_ids"]) != feature_ids:
        raise ValueError("initial_state_travel_feature_axis_mismatch")
    effective_lengths = np.asarray(path["effective_lengths_m"], dtype=float)
    full_lengths = np.asarray(path["full_lengths_m"], dtype=float)
    if (
        effective_lengths.shape != discharge.shape
        or full_lengths.shape != discharge.shape
        or not np.isfinite(effective_lengths).all()
        or not np.isfinite(full_lengths).all()
        or bool((effective_lengths < 0.0).any())
        or bool((full_lengths <= 0.0).any())
    ):
        raise ValueError("initial_state_effective_length_axis_mismatch")
    active = effective_lengths > 1e-6
    if not bool(active.any()):
        raise ValueError("initial_state_active_feature_axis_empty")
    invalid_active_velocity = (discharge > 0.0) & (velocity <= 0.0) & active
    if bool(invalid_active_velocity.any()):
        raise ValueError(
            "initial_state_active_positive_flow_requires_positive_velocity"
        )
    excluded_zero_velocity = (discharge > 0.0) & (velocity <= 0.0) & ~active

    fields = (
        "link",
        "Length",
        "BtmWdth",
        "TopWdth",
        "TopWdthCC",
        "ChSlp",
    )
    with netcdf_file(route_link_path, "r", mmap=False) as dataset:
        arrays = {
            name: np.asarray(dataset.variables[name][:]).copy() for name in fields
        }
    links = tuple(int(value) for value in arrays["link"])
    if links != feature_ids:
        raise ValueError("initial_state_route_link_feature_axis_mismatch")

    active_indices = np.flatnonzero(active)
    active_discharge = discharge[active]
    active_velocity = velocity[active]
    area = np.divide(
        active_discharge,
        active_velocity,
        out=np.zeros_like(active_discharge),
        where=active_velocity > 0.0,
    )
    side_slope = 1.0 / np.asarray(arrays["ChSlp"], dtype=float)
    depth = np.asarray(
        [
            _depth_for_compound_area(
                area_m2=float(area[position]),
                bottom_width_m=float(arrays["BtmWdth"][index]),
                top_width_m=float(arrays["TopWdth"][index]),
                compound_top_width_m=float(arrays["TopWdthCC"][index]),
                side_slope_horizontal_per_vertical=float(side_slope[index]),
            )
            for position, index in enumerate(active_indices)
        ],
        dtype=float,
    )
    reconstructed_area = np.asarray(
        [
            _compound_area_at_depth(
                depth_m=float(depth[position]),
                bottom_width_m=float(arrays["BtmWdth"][index]),
                top_width_m=float(arrays["TopWdth"][index]),
                compound_top_width_m=float(arrays["TopWdthCC"][index]),
                side_slope_horizontal_per_vertical=float(side_slope[index]),
            )
            for position, index in enumerate(active_indices)
        ],
        dtype=float,
    )
    area_error = np.abs(reconstructed_area - area)
    tolerance = np.maximum(1e-9, np.abs(area) * 1e-10)
    if bool((area_error > tolerance).any()):
        raise RuntimeError("initial_state_compound_area_roundtrip_failed")

    route_lengths = np.asarray(arrays["Length"], dtype=float)
    full_storage = area * route_lengths[active]
    effective_storage = area * effective_lengths[active]
    active_ids = tuple(
        feature_id
        for feature_id, admitted in zip(feature_ids, active, strict=True)
        if admitted
    )
    rows = [
        {
            "valid_at": INITIAL_VALID_AT,
            "available_at": available_at,
            "feature_id": feature_id,
            "active_path_feature": True,
            "streamflow_m3s": float(discharge[index]),
            "velocity_ms": float(velocity[index]),
            "cross_section_area_m2": float(area[position]),
            "compound_depth_m": float(depth[position]),
            "route_link_full_length_m": float(route_lengths[index]),
            "path_effective_length_m": float(effective_lengths[index]),
            "nwm_full_reach_storage_m3": float(full_storage[position]),
            "kernel_effective_storage_m3": float(effective_storage[position]),
            "source_role": "modeled_initial_state",
        }
        for position, (index, feature_id) in enumerate(
            zip(active_indices, active_ids, strict=True)
        )
    ]
    terminal_position = len(active_indices) - 1
    terminal_index = int(active_indices[terminal_position])
    return {
        "valid_at": INITIAL_VALID_AT,
        "available_at": available_at,
        "next_window_start": NEXT_WINDOW_START,
        "feature_count": len(feature_ids),
        "state_feature_count": len(active_ids),
        "active_feature_count": len(active_ids),
        "active_feature_ids": list(active_ids),
        "excluded_zero_length_feature_ids": [
            feature_id
            for feature_id, admitted in zip(feature_ids, active, strict=True)
            if not admitted
        ],
        "excluded_positive_flow_zero_velocity_feature_ids": [
            feature_id
            for feature_id, excluded in zip(
                feature_ids, excluded_zero_velocity, strict=True
            )
            if excluded
        ],
        "t_route_state": {
            "feature_ids": list(active_ids),
            "discharge_m3s": [float(value) for value in active_discharge],
            "velocity_ms": [float(value) for value in active_velocity],
            "depth_m": [float(value) for value in depth],
            "state_role": "retrospective_modeled_initial_state",
        },
        "nonlinear_storage_state": {
            "feature_ids": list(active_ids),
            "storage_m3": [float(value) for value in effective_storage],
            "state_role": "retrospective_modeled_initial_state",
        },
        "terminal_partial_reach_state": {
            "feature_id": int(feature_ids[terminal_index]),
            "nldi_full_length_m": float(full_lengths[terminal_index]),
            "path_effective_length_m": float(effective_lengths[terminal_index]),
            "route_link_length_m": float(route_lengths[terminal_index]),
            "cross_section_area_m2": float(area[terminal_position]),
            "nwm_full_reach_storage_m3": float(full_storage[terminal_position]),
            "kernel_effective_storage_m3": float(
                effective_storage[terminal_position]
            ),
        },
        "diagnostics": {
            "maximum_compound_area_roundtrip_error_m2": float(area_error.max()),
            "zero_flow_positive_velocity_count": int(
                ((discharge == 0.0) & (velocity > 0.0)).sum()
            ),
            "positive_flow_zero_velocity_excluded_feature_count": int(
                excluded_zero_velocity.sum()
            ),
            "minimum_active_streamflow_m3s": float(active_discharge.min()),
            "maximum_active_streamflow_m3s": float(active_discharge.max()),
            "minimum_active_velocity_ms": float(active_velocity.min()),
            "maximum_active_velocity_ms": float(active_velocity.max()),
            "minimum_compound_depth_m": float(depth.min()),
            "maximum_compound_depth_m": float(depth.max()),
            "full_reach_storage_derived_feature_count": len(active_ids),
            "total_nwm_full_reach_storage_m3": float(full_storage.sum()),
            "total_kernel_effective_storage_m3": float(effective_storage.sum()),
        },
        "derivation": {
            "cross_section_area": "streamflow_m3s / velocity_ms",
            "compound_depth": (
                "inverse of t-route/NWM v3 trapezoid plus compound-width area"
            ),
            "nonlinear_storage": "cross_section_area_m2 * path_effective_length_m",
            "outcome_calibrated": False,
        },
        "rows": rows,
    }


def _depth_for_compound_area(
    *,
    area_m2: float,
    bottom_width_m: float,
    top_width_m: float,
    compound_top_width_m: float,
    side_slope_horizontal_per_vertical: float,
) -> float:
    values = np.asarray(
        [
            area_m2,
            bottom_width_m,
            top_width_m,
            compound_top_width_m,
            side_slope_horizontal_per_vertical,
        ],
        dtype=float,
    )
    if (
        not np.isfinite(values).all()
        or area_m2 < 0.0
        or bottom_width_m <= 0.0
        or side_slope_horizontal_per_vertical <= 0.0
    ):
        raise ValueError("initial_state_compound_geometry_invalid")
    if area_m2 == 0.0:
        return 0.0
    bankfull_depth = _bankfull_depth(
        bottom_width_m=bottom_width_m,
        top_width_m=top_width_m,
        side_slope_horizontal_per_vertical=side_slope_horizontal_per_vertical,
    )
    bankfull_area = (
        bottom_width_m * bankfull_depth
        + side_slope_horizontal_per_vertical * bankfull_depth**2
    )
    if area_m2 <= bankfull_area or compound_top_width_m <= 0.0:
        return float(
            (
                -bottom_width_m
                + math.sqrt(
                    bottom_width_m**2
                    + 4.0 * side_slope_horizontal_per_vertical * area_m2
                )
            )
            / (2.0 * side_slope_horizontal_per_vertical)
        )
    return float(
        bankfull_depth
        + (area_m2 - bankfull_area) / compound_top_width_m
    )


def _compound_area_at_depth(
    *,
    depth_m: float,
    bottom_width_m: float,
    top_width_m: float,
    compound_top_width_m: float,
    side_slope_horizontal_per_vertical: float,
) -> float:
    bankfull_depth = _bankfull_depth(
        bottom_width_m=bottom_width_m,
        top_width_m=top_width_m,
        side_slope_horizontal_per_vertical=side_slope_horizontal_per_vertical,
    )
    main_depth = min(depth_m, bankfull_depth)
    area = (
        bottom_width_m * main_depth
        + side_slope_horizontal_per_vertical * main_depth**2
    )
    if depth_m > bankfull_depth and compound_top_width_m > 0.0:
        area += compound_top_width_m * (depth_m - bankfull_depth)
    elif depth_m > bankfull_depth:
        area = (
            bottom_width_m * depth_m
            + side_slope_horizontal_per_vertical * depth_m**2
        )
    return float(area)


def _bankfull_depth(
    *,
    bottom_width_m: float,
    top_width_m: float,
    side_slope_horizontal_per_vertical: float,
) -> float:
    if bottom_width_m > top_width_m:
        return bottom_width_m / 0.00001
    if bottom_width_m == top_width_m:
        return bottom_width_m / (
            2.0 * side_slope_horizontal_per_vertical
        )
    return (top_width_m - bottom_width_m) / (
        2.0 * side_slope_horizontal_per_vertical
    )


def _validate_reused_evaluation_inputs(
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        manifest.get("schema") != "gwm.geotransport.center_hill_evaluation_nwm.v1"
        or manifest.get("mode") != "values"
        or (manifest.get("window") or {}).get("end_exclusive")
        != NEXT_WINDOW_START
    ):
        raise ValueError("initial_state_reused_evaluation_manifest_invalid")
    by_variable = {
        item.get("variable"): item for item in manifest.get("raw_artifacts") or []
    }
    selected = {}
    for variable, key in (("time", "560"), ("velocity", STREAMFLOW_KEY)):
        descriptor = by_variable.get(variable)
        if not isinstance(descriptor, dict) or descriptor.get("key") != key:
            raise ValueError(f"initial_state_reused_{variable}_artifact_missing")
        _read_verified_artifact(descriptor)
        selected[variable] = descriptor
    return selected


def _validate_route_link_manifest(
    manifest: Mapping[str, Any], feature_ids: tuple[int, ...]
) -> dict[str, Any]:
    if (
        manifest.get("schema")
        != "gwm.geotransport.center_hill_route_link_v3_acquisition.v1"
        or manifest.get("status") != "pass"
        or (manifest.get("adjudication") or {}).get(
            "center_hill_active_feature_coverage_complete"
        )
        is not True
    ):
        raise ValueError("initial_state_route_link_manifest_invalid")
    descriptor = manifest.get("subset") or {}
    artifact = {
        key: descriptor[key] for key in ("path", "sha256", "size_bytes")
    }
    _read_verified_artifact(artifact)
    if tuple(descriptor["audit"]["feature_ids"]) != feature_ids:
        raise ValueError("initial_state_route_link_manifest_feature_axis_mismatch")
    return artifact


def _validate_travel_report(
    report: Mapping[str, Any], feature_ids: tuple[int, ...]
) -> None:
    path = report.get("linear_referenced_path") or {}
    if (
        report.get("schema")
        != "gwm.geotransport.center_hill_travel_time_prior.v1"
        or tuple(path.get("feature_ids") or ()) != feature_ids
        or len(path.get("effective_lengths_m") or ()) != len(feature_ids)
    ):
        raise ValueError("initial_state_travel_report_invalid")


def _read_verified_artifact(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("initial_state_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError(f"initial_state_artifact_identity_mismatch:{path}")
    return body


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
        raise ValueError("initial_state_url_outside_official_allowlist")
    handlers: list[urllib.request.BaseHandler] = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                final = urllib.parse.urlparse(response.geturl())
                if final.scheme != "https" or final.hostname != ALLOWED_HOST:
                    raise ValueError("initial_state_redirect_outside_official_allowlist")
                body = response.read(maximum_bytes + 1)
                if len(body) > maximum_bytes:
                    raise ValueError("initial_state_object_size_limit_exceeded")
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
                    f"non_retryable_initial_state_http_error:{exc.code}"
                ) from exc
            error = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            error = exc
        if attempt < retries:
            time.sleep(float(attempt))
    raise RuntimeError(f"initial_state_request_failed:{error}")


def _write_state_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = tuple(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


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
