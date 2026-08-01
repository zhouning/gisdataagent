#!/usr/bin/env python3
"""Build a bounded, non-admitted Center Hill travel-time prior diagnostic."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
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

import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    DEFAULT_REGISTRY_PATH,
    LinearReferencedPath,
    TravelTimePrior,
    build_nwm_q_lateral_plan,
    extract_nwm_velocity,
    load_nwm_velocity_schema,
    load_public_data_registry,
    nwm_chunk_url,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METADATA_ROOT = REPO_ROOT / "data/geotransport_v0_1/metadata"
DEFAULT_NLDI_REPORT = (
    REPO_ROOT / "benchmarks/geotransport_v0_1/nldi_path_crosswalk_report.json"
)
DEFAULT_NAVIGATION = (
    REPO_ROOT / "data/geotransport_v0_1/topology/raw/center_hill-downstream-flowlines.json"
)
DEFAULT_GAUGE = REPO_ROOT / "data/geotransport_v0_1/metadata/nldi-link-03424860.json"
DEFAULT_Q_MANIFEST = (
    REPO_ROOT / "data/geotransport_v0_1/nwm_q_lateral/extraction_manifest.json"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data/geotransport_v0_1/nwm_velocity"
DEFAULT_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/center_hill_travel_time_prior_report.json"
)
SCHEMA = "gwm.geotransport.center_hill_travel_time_prior.v1"
ACQUISITION_SCHEMA = "gwm.geotransport.nwm_velocity_acquisition.v1"
ALLOWED_HOST = "noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com"
TIME_CHUNK_INDEX = 559
FEATURE_CHUNK_INDEX = 63
USER_AGENT = "gisdataagent-center-hill-travel-time-prior/0.1"
CWMS_TIME_EVIDENCE = (
    "https://github.com/USACE/cwms-data-api/blob/"
    "beb8d507c9da8ec074d444117bda7d7daf69e5ee/"
    "docs/source/data/timeseries.rst#L97-L118"
)
WRF_HYDRO_PHYSICS_EVIDENCE = (
    "https://github.com/NCAR/wrf_hydro_nwm_public/blob/"
    "4510c28c9afc72b42062158125a56b6d9dc6c057/"
    "docs/userguide/model-physics.rest#L1138-L1223"
)


@dataclass(frozen=True)
class CompiledTravelTimePrior:
    report: dict[str, Any]
    velocity_csv_body: bytes
    travel_time_csv_body: bytes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--metadata-root", type=Path, default=DEFAULT_METADATA_ROOT)
    parser.add_argument("--nldi-report", type=Path, default=DEFAULT_NLDI_REPORT)
    parser.add_argument("--navigation", type=Path, default=DEFAULT_NAVIGATION)
    parser.add_argument("--gauge", type=Path, default=DEFAULT_GAUGE)
    parser.add_argument("--q-manifest", type=Path, default=DEFAULT_Q_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--acquire-velocity", action="store_true")
    parser.add_argument("--accept-modeled-velocity", action="store_true")
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--evidence-parent-registry-sha256")
    return parser.parse_args()


def compile_prior(
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    metadata_root: Path = DEFAULT_METADATA_ROOT,
    nldi_report_path: Path = DEFAULT_NLDI_REPORT,
    navigation_path: Path = DEFAULT_NAVIGATION,
    gauge_path: Path = DEFAULT_GAUGE,
    q_manifest_path: Path = DEFAULT_Q_MANIFEST,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    evidence_parent_registry_sha256: str | None = None,
) -> CompiledTravelTimePrior:
    registry = load_public_data_registry(registry_path)
    evidence = registry.payload.get("center_hill_travel_time_prior_evidence") or {}
    parent_hash = (
        evidence_parent_registry_sha256
        or evidence.get("parent_registry_sha256")
        or registry.sha256
    )
    if not isinstance(parent_hash, str) or len(parent_hash) != 64:
        raise ValueError("travel_time_prior_parent_registry_sha256_required")
    system = next(
        system
        for system in registry.payload["systems"]
        if system["system_id"] == "center_hill"
    )
    acquisition_path = output_root / "acquisition_manifest.json"
    acquisition_body = acquisition_path.read_bytes()
    acquisition = json.loads(acquisition_body)
    if acquisition.get("schema") != ACQUISITION_SCHEMA:
        raise ValueError("nwm_velocity_acquisition_schema_mismatch")
    _verify_acquisition(acquisition)

    schema = load_nwm_velocity_schema(metadata_root)
    chunk_start_index = TIME_CHUNK_INDEX * schema.base.time_chunk_size
    chunk_end_index = chunk_start_index + schema.base.time_chunk_size
    start = schema.base.time_origin + timedelta(hours=chunk_start_index)
    end = schema.base.time_origin + timedelta(hours=chunk_end_index)
    plan = build_nwm_q_lateral_plan(
        registry,
        schema.base,
        system_id="center_hill",
        start=_iso(start),
        end=_iso(end),
    )
    if (
        plan.time_chunk_indices != (TIME_CHUNK_INDEX,)
        or plan.feature_chunk_indices != (FEATURE_CHUNK_INDEX,)
    ):
        raise ValueError("center_hill_velocity_chunk_plan_mismatch")

    q_manifest_body = q_manifest_path.read_bytes()
    q_manifest = json.loads(q_manifest_body)
    time_descriptor = _time_chunk_descriptor(q_manifest)
    time_body = _read_verified_artifact(time_descriptor)
    velocity_descriptor = next(
        artifact
        for artifact in acquisition["artifacts"]
        if artifact["variable"] == "velocity"
    )
    velocity_body = _read_verified_artifact(velocity_descriptor)
    result = extract_nwm_velocity(
        plan,
        schema,
        time_chunks={TIME_CHUNK_INDEX: time_body},
        velocity_chunks={(TIME_CHUNK_INDEX, FEATURE_CHUNK_INDEX): velocity_body},
    )

    nldi_report_body = nldi_report_path.read_bytes()
    nldi_report = json.loads(nldi_report_body)
    navigation_body = navigation_path.read_bytes()
    navigation = json.loads(navigation_body)
    gauge_body = gauge_path.read_bytes()
    gauge = json.loads(gauge_body)
    path, path_diagnostics = build_linear_referenced_path(
        system=system,
        nldi_report=nldi_report,
        navigation=navigation,
        gauge=gauge,
        nldi_report_sha256=hashlib.sha256(nldi_report_body).hexdigest(),
    )
    if tuple(result.feature_ids) != path.feature_ids:
        raise ValueError("velocity_and_linear_path_feature_order_mismatch")

    travel_seconds, valid_rows = advective_travel_time_seconds(
        result.values_ms, path.effective_lengths_m
    )
    valid_values = travel_seconds[valid_rows]
    if valid_values.size < int(math.ceil(0.9 * travel_seconds.size)):
        raise ValueError("insufficient_valid_velocity_hours_for_prior")
    lower, central, upper = np.quantile(valid_values, [0.05, 0.5, 0.95])
    prior = TravelTimePrior(
        path_id=path.path_id,
        quantity="advective_residence_time",
        method="sum_linear_referenced_reach_length_over_nwm_v3_river_velocity_q05_q50_q95",
        lower_seconds=float(lower),
        central_seconds=float(central),
        upper_seconds=float(upper),
        state_dependent=True,
        outcome_calibrated=False,
        admitted_as_flood_wave_lag=False,
        provenance_id="noaa-nwm-v3-retrospective:chrtout.zarr:velocity:559.63",
        evidence_level="candidate",
    )

    velocity_csv_body = _velocity_csv(result)
    travel_time_csv_body = _travel_time_csv(
        result.timestamps, travel_seconds, valid_rows
    )
    velocity_path = output_root / "values/center_hill.csv"
    travel_path = output_root / "values/center_hill_advective_travel_time.csv"
    report = {
        "schema": SCHEMA,
        "status": "candidate_advective_prior_not_flood_wave_lag",
        "input_registry_sha256": parent_hash,
        "source_artifacts": {
            "velocity_acquisition_manifest": _artifact(acquisition_path, acquisition_body),
            "q_lateral_extraction_manifest": _artifact(q_manifest_path, q_manifest_body),
            "time_chunk": _artifact_from_descriptor(time_descriptor),
            "velocity_chunk": _artifact_from_descriptor(velocity_descriptor),
            "nldi_path_report": _artifact(nldi_report_path, nldi_report_body),
            "navigation": _artifact(navigation_path, navigation_body),
            "gauge": _artifact(gauge_path, gauge_body),
            "selected_velocity": _body_artifact(velocity_path, velocity_csv_body),
            "advective_travel_time": _body_artifact(
                travel_path, travel_time_csv_body
            ),
        },
        "official_semantics_evidence": {
            "cwms_composite_default_timestamp_position": {
                "conclusion": "end_of_period_unless_duration_has_BOP_suffix",
                "source_url": CWMS_TIME_EVIDENCE,
            },
            "wrf_hydro_flood_wave_relation": {
                "conclusion": "K_equals_dx_over_wave_celerity_and_is_state_dependent",
                "source_url": WRF_HYDRO_PHYSICS_EVIDENCE,
            },
        },
        "linear_referenced_path": path.as_dict(),
        "path_diagnostics": path_diagnostics,
        "velocity_window": {
            "start_inclusive": result.timestamps[0],
            "end_exclusive": _iso(
                _parse_utc(result.timestamps[-1]) + timedelta(hours=1)
            ),
            "time_count": len(result.timestamps),
            "feature_count": len(result.feature_ids),
            "fill_value_count": result.fill_value_count,
            "invalid_travel_time_hour_count": int((~valid_rows).sum()),
        },
        "advective_travel_time_prior": prior.as_dict(),
        "advective_travel_time_summary": {
            "minimum_seconds": float(valid_values.min()),
            "maximum_seconds": float(valid_values.max()),
            "mean_seconds": float(valid_values.mean()),
            "q05_seconds": float(lower),
            "q50_seconds": float(central),
            "q95_seconds": float(upper),
        },
        "checks": {
            "official_source_allowlist_enforced": True,
            "single_velocity_chunk_bound_enforced": True,
            "time_chunk_hash_reused_from_q_lateral_manifest": True,
            "registry_feature_order_reconstructed": True,
            "linear_reference_trims_action_and_gauge_reaches": True,
            "velocity_is_not_relabelled_as_wave_celerity": True,
            "outcome_values_not_used": True,
        },
        "claim_boundary": {
            "cwms_interval_timestamp_semantics_admitted": True,
            "linear_referenced_path_compiled": True,
            "bounded_nwm_velocity_prior_compiled": True,
            "advective_residence_time_is_flood_wave_travel_time": False,
            "flood_wave_travel_time_admitted": False,
            "travel_time_or_lag_calibrated": False,
            "training_or_evaluation_panel_ready": False,
            "benchmark_validated": False,
            "geospatial_kernel_validated": False,
        },
    }
    return CompiledTravelTimePrior(
        report=report,
        velocity_csv_body=velocity_csv_body,
        travel_time_csv_body=travel_time_csv_body,
    )


def build_linear_referenced_path(
    *,
    system: Mapping[str, Any],
    nldi_report: Mapping[str, Any],
    navigation: Mapping[str, Any],
    gauge: Mapping[str, Any],
    nldi_report_sha256: str,
) -> tuple[LinearReferencedPath, dict[str, Any]]:
    row = next(
        item for item in nldi_report["systems"] if item["system_id"] == "center_hill"
    )
    feature_ids = tuple(int(value) for value in row["path"]["feature_ids"])
    if feature_ids != tuple(system["forcing"]["feature_ids"]):
        raise ValueError("linear_path_registry_feature_mismatch")
    by_id = {
        int(feature["properties"]["nhdplus_comid"]): feature
        for feature in navigation.get("features") or []
    }
    if not set(feature_ids) <= set(by_id):
        raise ValueError("linear_path_navigation_feature_missing")
    raw_lines = [by_id[feature_id]["geometry"]["coordinates"] for feature_id in feature_ids]
    lines, orientations, connection_gaps_m = orient_path_lines(raw_lines)
    action_point = (
        float(row["action_point"]["longitude"]),
        float(row["action_point"]["latitude"]),
    )
    gauge_features = gauge.get("features") or []
    if len(gauge_features) != 1 or gauge_features[0]["geometry"]["type"] != "Point":
        raise ValueError("linear_path_gauge_point_required")
    gauge_point = tuple(float(value) for value in gauge_features[0]["geometry"]["coordinates"])
    lengths_m = tuple(geometry_length_m(line) for line in lines)
    action_snap_m, action_measure_m = project_point_to_line(action_point, lines[0])
    gauge_snap_m, gauge_measure_m = project_point_to_line(gauge_point, lines[-1])
    if action_snap_m > 100.0 or gauge_snap_m > 100.0:
        raise ValueError("linear_path_endpoint_snap_exceeds_100m")
    entries = [0.0] * len(lines)
    exits = list(lengths_m)
    entries[0] = min(lengths_m[0], action_measure_m)
    exits[-1] = min(lengths_m[-1], gauge_measure_m)
    path = LinearReferencedPath(
        path_id="center_hill:CETT1-CENTER_HILL:USGS-03424860",
        feature_ids=feature_ids,
        full_lengths_m=lengths_m,
        entry_offsets_m=tuple(entries),
        exit_offsets_m=tuple(exits),
        provenance_id=f"nldi-path-report:{nldi_report_sha256}",
        evidence_level="derived",
    )
    full_report_m = float(row["path"]["full_reach_path_length_km"]) * 1000.0
    if abs(sum(lengths_m) - full_report_m) > 5.0:
        raise ValueError("linear_path_full_length_reproduction_mismatch")
    return path, {
        "orientation_by_feature": [
            {"feature_id": feature_id, "coordinate_order": orientation}
            for feature_id, orientation in zip(feature_ids, orientations, strict=True)
        ],
        "maximum_connection_gap_m": max(connection_gaps_m, default=0.0),
        "action_snap_distance_m": action_snap_m,
        "action_measure_from_oriented_start_m": action_measure_m,
        "gauge_snap_distance_m": gauge_snap_m,
        "gauge_measure_from_oriented_start_m": gauge_measure_m,
        "full_reach_path_length_m": float(sum(lengths_m)),
        "linear_referenced_path_length_m": path.total_effective_length_m,
    }


def orient_path_lines(
    raw_lines: list[list[list[float]]],
) -> tuple[list[list[list[float]]], list[str], list[float]]:
    if not raw_lines or any(len(line) < 2 for line in raw_lines):
        raise ValueError("linear_path_lines_required")
    candidates = [(line, list(reversed(line))) for line in raw_lines]
    costs = [0.0, 0.0]
    parents: list[list[int]] = []
    for index in range(1, len(candidates)):
        next_costs: list[float] = []
        next_parents: list[int] = []
        for orientation in range(2):
            options = [
                costs[previous]
                + haversine_m(
                    tuple(candidates[index - 1][previous][-1]),
                    tuple(candidates[index][orientation][0]),
                )
                for previous in range(2)
            ]
            parent = int(np.argmin(options))
            next_costs.append(options[parent])
            next_parents.append(parent)
        costs = next_costs
        parents.append(next_parents)
    orientations = [0] * len(candidates)
    orientations[-1] = int(np.argmin(costs))
    for index in range(len(candidates) - 1, 0, -1):
        orientations[index - 1] = parents[index - 1][orientations[index]]
    lines = [candidates[index][value] for index, value in enumerate(orientations)]
    gaps = [
        haversine_m(tuple(first[-1]), tuple(second[0]))
        for first, second in zip(lines, lines[1:])
    ]
    if any(gap > 100.0 for gap in gaps):
        raise ValueError("linear_path_connection_gap_exceeds_100m")
    labels = ["source_order" if value == 0 else "reversed" for value in orientations]
    return lines, labels, gaps


def project_point_to_line(
    point: tuple[float, float], line: list[list[float]]
) -> tuple[float, float]:
    lon_scale = 111_195.08 * math.cos(math.radians(point[1]))
    lat_scale = 111_195.08
    px, py = point[0] * lon_scale, point[1] * lat_scale
    best_distance = math.inf
    best_measure = 0.0
    measure = 0.0
    for first, second in zip(line, line[1:]):
        ax, ay = first[0] * lon_scale, first[1] * lat_scale
        bx, by = second[0] * lon_scale, second[1] * lat_scale
        dx, dy = bx - ax, by - ay
        length_squared = dx * dx + dy * dy
        ratio = 0.0 if length_squared == 0.0 else (
            ((px - ax) * dx + (py - ay) * dy) / length_squared
        )
        ratio = min(1.0, max(0.0, ratio))
        qx, qy = ax + ratio * dx, ay + ratio * dy
        distance = math.hypot(px - qx, py - qy)
        segment_length = haversine_m(tuple(first), tuple(second))
        if distance < best_distance:
            best_distance = distance
            best_measure = measure + ratio * segment_length
        measure += segment_length
    return float(best_distance), float(best_measure)


def geometry_length_m(line: list[list[float]]) -> float:
    return float(
        sum(
            haversine_m(tuple(first), tuple(second))
            for first, second in zip(line, line[1:])
        )
    )


def haversine_m(first: tuple[float, float], second: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, first)
    lon2, lat2 = map(math.radians, second)
    delta_lon = lon2 - lon1
    delta_lat = lat2 - lat1
    value = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2.0) ** 2
    )
    return 6_371_008.8 * 2.0 * math.asin(min(1.0, math.sqrt(value)))


def advective_travel_time_seconds(
    velocity_ms: np.ndarray, effective_lengths_m: tuple[float, ...]
) -> tuple[np.ndarray, np.ndarray]:
    values = np.asarray(velocity_ms, dtype=float)
    lengths = np.asarray(effective_lengths_m, dtype=float)
    if values.ndim != 2 or values.shape[1] != lengths.size:
        raise ValueError("velocity_path_shape_mismatch")
    active = lengths > 1e-6
    valid_rows = np.isfinite(values[:, active]).all(axis=1) & (
        values[:, active] > 0.0
    ).all(axis=1)
    travel = np.full(values.shape[0], np.nan, dtype=float)
    travel[valid_rows] = np.sum(
        lengths[active] / values[valid_rows][:, active], axis=1
    )
    return travel, valid_rows


def acquire_velocity(
    *,
    metadata_root: Path,
    output_root: Path,
    proxy: str,
    timeout_seconds: float,
    retries: int,
) -> Path:
    if retries <= 0 or timeout_seconds <= 0.0:
        raise ValueError("positive_velocity_acquisition_limits_required")
    opener = _opener(proxy)
    requests = (
        (
            "consolidated_metadata",
            "https://noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com/"
            "CONUS/zarr/chrtout.zarr/.zmetadata",
            metadata_root / "nwm-chrtout-zmetadata.json",
            200_000,
        ),
        (
            "velocity_array",
            f"{nwm_chunk_url('velocity', '.zarray')}",
            metadata_root / "nwm-velocity-zarray.json",
            100_000,
        ),
        (
            "velocity_attrs",
            f"{nwm_chunk_url('velocity', '.zattrs')}",
            metadata_root / "nwm-velocity-zattrs.json",
            100_000,
        ),
        (
            "velocity",
            nwm_chunk_url("velocity", f"{TIME_CHUNK_INDEX}.{FEATURE_CHUNK_INDEX}"),
            output_root
            / f"raw/velocity/{TIME_CHUNK_INDEX}.{FEATURE_CHUNK_INDEX}.zst",
            20_000_000,
        ),
    )
    artifacts = []
    for variable, url, path, limit in requests:
        body, retrieval = _fetch(
            url,
            opener=opener,
            timeout_seconds=timeout_seconds,
            retries=retries,
            maximum_bytes=limit,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        artifacts.append(
            {
                **retrieval,
                "variable": variable,
                "path": _display(path),
                "sha256": hashlib.sha256(body).hexdigest(),
                "size_bytes": len(body),
            }
        )
    manifest = {
        "schema": ACQUISITION_SCHEMA,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source": "noaa_nwm_v3_retrospective",
        "request_count": len(requests),
        "maximum_total_response_bytes": 20_400_000,
        "artifacts": artifacts,
        "claim_boundary": {
            "modeled_velocity_acquired": True,
            "observed_velocity_acquired": False,
            "flood_wave_travel_time_admitted": False,
            "benchmark_validated": False,
        },
    }
    path = output_root / "acquisition_manifest.json"
    _write_json(path, manifest)
    return path


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
        raise ValueError("velocity_url_outside_official_allowlist")
    error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                body = response.read(maximum_bytes + 1)
                if len(body) > maximum_bytes:
                    raise ValueError("velocity_response_size_limit_exceeded")
                return body, {
                    "url": url,
                    "http_status": response.status,
                    "content_type": response.headers.get("Content-Type"),
                    "attempt_count": attempt,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                raise RuntimeError(f"non_retryable_velocity_http_error:{exc.code}") from exc
            error = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            error = exc
        if attempt < retries:
            time.sleep(float(attempt))
    raise RuntimeError(f"velocity_request_failed:{error}")


def _verify_acquisition(payload: Mapping[str, Any]) -> None:
    artifacts = payload.get("artifacts") or []
    if payload.get("request_count") != 4 or len(artifacts) != 4:
        raise ValueError("velocity_acquisition_artifact_count_mismatch")
    if {item.get("variable") for item in artifacts} != {
        "velocity_array",
        "velocity_attrs",
        "consolidated_metadata",
        "velocity",
    }:
        raise ValueError("velocity_acquisition_variable_set_mismatch")
    for descriptor in artifacts:
        parsed = urllib.parse.urlparse(str(descriptor.get("url")))
        if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
            raise ValueError("velocity_acquisition_source_outside_allowlist")
        _read_verified_artifact(descriptor)


def _time_chunk_descriptor(q_manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    if q_manifest.get("schema") != "gwm.geotransport.nwm_q_lateral_extract.v1":
        raise ValueError("q_lateral_manifest_required_for_time_chunk")
    matches = [
        item
        for item in q_manifest.get("raw_chunk_artifacts") or []
        if item.get("variable") == "time"
        and item.get("path", "").endswith(f"/{TIME_CHUNK_INDEX}.zst")
    ]
    if len(matches) != 1:
        raise ValueError("single_verified_time_chunk_required")
    return matches[0]


def _read_verified_artifact(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("travel_time_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError(f"travel_time_artifact_identity_mismatch:{descriptor.get('path')}")
    return body


def _velocity_csv(result: Any) -> bytes:
    rows = [["timestamp_utc", "feature_id", "velocity_ms", "source_role"]]
    for row, timestamp in enumerate(result.timestamps):
        for column, feature_id in enumerate(result.feature_ids):
            value = result.values_ms[row, column]
            rows.append(
                [
                    timestamp,
                    feature_id,
                    "" if math.isnan(value) else format(value, ".10g"),
                    result.variable_role,
                ]
            )
    return _csv_body(rows)


def _travel_time_csv(
    timestamps: tuple[str, ...], values: np.ndarray, valid_rows: np.ndarray
) -> bytes:
    rows = [["timestamp_utc", "advective_travel_time_seconds", "valid"]]
    for timestamp, value, valid in zip(timestamps, values, valid_rows, strict=True):
        rows.append([timestamp, format(float(value), ".10g") if valid else "", str(bool(valid)).lower()])
    return _csv_body(rows)


def _csv_body(rows: list[list[object]]) -> bytes:
    import io

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": _display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _body_artifact(path: Path, body: bytes) -> dict[str, Any]:
    return _artifact(path, body)


def _artifact_from_descriptor(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": descriptor["path"],
        "sha256": descriptor["sha256"],
        "size_bytes": descriptor["size_bytes"],
        "source_url": descriptor.get("url"),
        "retrieved_at": descriptor.get("retrieved_at"),
    }


def _opener(proxy: str) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(*handlers)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone_aware_timestamp_required")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    if args.acquire_velocity:
        if not args.accept_modeled_velocity:
            raise ValueError("velocity_acquisition_requires_accept_modeled_velocity")
        acquire_velocity(
            metadata_root=args.metadata_root,
            output_root=args.output_root,
            proxy=args.proxy,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
        )
    compiled = compile_prior(
        registry_path=args.registry,
        metadata_root=args.metadata_root,
        nldi_report_path=args.nldi_report,
        navigation_path=args.navigation,
        gauge_path=args.gauge,
        q_manifest_path=args.q_manifest,
        output_root=args.output_root,
        evidence_parent_registry_sha256=args.evidence_parent_registry_sha256,
    )
    velocity_path = args.output_root / "values/center_hill.csv"
    travel_path = args.output_root / "values/center_hill_advective_travel_time.csv"
    velocity_path.parent.mkdir(parents=True, exist_ok=True)
    velocity_path.write_bytes(compiled.velocity_csv_body)
    travel_path.write_bytes(compiled.travel_time_csv_body)
    report = dict(compiled.report)
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(args.report, report)
    print(args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
