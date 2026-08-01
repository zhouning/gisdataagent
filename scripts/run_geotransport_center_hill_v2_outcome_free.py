#!/usr/bin/env python3
"""Run the frozen Center Hill v2 scenarios without loading outcome values."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from scipy.io import netcdf_file

from data_agent.uwm.geospatial_kernel_v2 import (
    CtypesTrouteMuskingumCungeKernel,
    HoldoutReachDomain,
    HourlyReachInput,
    LinearReferencedPath,
    ReachForcingSupport,
    ReachHydraulicGeometry,
    StockState,
    TrouteMuskingumCungeParameters,
    TrouteMuskingumCungeState,
    execute_holdout_rollout,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INITIAL_STATE_MANIFEST = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_initial_state_nwm_v3/"
    "acquisition_manifest.json"
)
DEFAULT_FORCING_SUPPORT = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_terminal_forcing_support_nhdplus_v21/"
    "forcing_support.json"
)
DEFAULT_ROUTE_LINK_MANIFEST = REPO_ROOT / (
    "data/geotransport_v0_1/route_link_nwm_v3_center_hill/"
    "acquisition_manifest.json"
)
DEFAULT_TRAVEL_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_travel_time_prior_report.json"
)
DEFAULT_BUILD_MANIFEST = REPO_ROOT / (
    "data/geotransport_v0_1/t_route_mc_runtime/build_manifest.json"
)
DEFAULT_ACTION_MANIFEST = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d3_inputs/action/"
    "acquisition_manifest.json"
)
DEFAULT_FORCING_MANIFEST = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d3_inputs/nwm/"
    "acquisition_manifest.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d3_rollout/predictions.csv"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_v2_d3_rollout_report.json"
)

SCHEMA = "gwm.geotransport.center_hill_v2_outcome_free_rollout.v1"
ACTION_MANIFEST_SCHEMA = "gwm.geotransport.center_hill_v2_action_input.v1"
FORCING_MANIFEST_SCHEMA = "gwm.geotransport.center_hill_v2_nwm_input.v1"
START = datetime(2022, 2, 3, 1, tzinfo=timezone.utc)
END = datetime(2022, 3, 3, 1, tzinfo=timezone.utc)
HOUR_COUNT = 672
ACTIVE_FEATURE_COUNT = 26


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action-manifest", type=Path, default=DEFAULT_ACTION_MANIFEST)
    parser.add_argument(
        "--forcing-manifest", type=Path, default=DEFAULT_FORCING_MANIFEST
    )
    parser.add_argument("--build-manifest", type=Path, default=DEFAULT_BUILD_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_rollout(
    *,
    action_manifest_path: Path,
    forcing_manifest_path: Path,
    t_route_kernel: Any,
    output_path: Path = DEFAULT_OUTPUT,
    initial_state_manifest_path: Path = DEFAULT_INITIAL_STATE_MANIFEST,
    forcing_support_path: Path = DEFAULT_FORCING_SUPPORT,
    route_link_manifest_path: Path = DEFAULT_ROUTE_LINK_MANIFEST,
    travel_report_path: Path = DEFAULT_TRAVEL_REPORT,
) -> tuple[bytes, dict[str, Any]]:
    action_body, action_manifest = _load_json(action_manifest_path)
    forcing_body, forcing_manifest = _load_json(forcing_manifest_path)
    _validate_input_manifests(action_manifest, forcing_manifest)
    action_values_body = _read_verified(action_manifest["action_values"])
    forcing_values_body = _read_verified(forcing_manifest["q_lateral_values"])
    actions = _parse_actions(action_values_body)

    domain, domain_artifacts = compile_domain(
        initial_state_manifest_path=initial_state_manifest_path,
        forcing_support_path=forcing_support_path,
        route_link_manifest_path=route_link_manifest_path,
        travel_report_path=travel_report_path,
    )
    q_lateral = _parse_q_lateral(
        forcing_values_body,
        expected_feature_ids=domain.geometry.feature_ids,
    )
    hourly_inputs = tuple(
        HourlyReachInput(
            support_start_utc=START + timedelta(hours=index),
            support_end_utc=START + timedelta(hours=index + 1),
            action_release_m3s=actions[START + timedelta(hours=index)],
            q_lateral_m3s=tuple(
                q_lateral[START + timedelta(hours=index)][feature_id]
                for feature_id in domain.geometry.feature_ids
            ),
            provenance_id=f"center_hill:v2:d3:hour-{index:03d}",
        )
        for index in range(HOUR_COUNT)
    )
    rollout = execute_holdout_rollout(hourly_inputs, domain, t_route_kernel)
    csv_body = _encode_rows(rollout.rows)
    report = {
        "schema": SCHEMA,
        "status": "outcome_free_rollout_complete",
        "window": {
            "start_inclusive": _iso(START),
            "end_exclusive": _iso(END),
            "time_step": "PT1H",
            "hour_count": HOUR_COUNT,
        },
        "input_manifests": {
            "action": _artifact(action_manifest_path, action_body),
            "modeled_forcing": _artifact(forcing_manifest_path, forcing_body),
        },
        "input_artifacts": {
            "action_values": _artifact_from_descriptor(
                action_manifest["action_values"], action_values_body
            ),
            "q_lateral_values": _artifact_from_descriptor(
                forcing_manifest["q_lateral_values"], forcing_values_body
            ),
        },
        "domain_artifacts": domain_artifacts,
        "prediction_artifact": {
            "path": _display(output_path),
            "sha256": hashlib.sha256(csv_body).hexdigest(),
            "size_bytes": len(csv_body),
        },
        "nonlinear_conservation": rollout.nonlinear_conservation,
        "t_route_diagnostics": rollout.t_route_diagnostics,
        "registered_execution": {
            "nonlinear_timestep_seconds": 3600,
            "nonlinear_substep_seconds": 300,
            "t_route_substep_seconds": 300,
            "t_route_substeps_per_hour": 12,
            "t_route_boundary_previous_equals_current_hourly_interval_mean": True,
            "terminal_forcing_support_central_preselected": True,
            "support_lower_upper_are_report_only": True,
        },
        "data_isolation": {
            "outcome_manifest_accepted_by_executor": False,
            "outcome_columns_accepted_by_executor": False,
            "outcome_values_loaded": False,
            "usgs_observation_loaded": False,
        },
        "claim_boundary": {
            "retrospective_transition_inputs_executed": True,
            "predictions_scored": False,
            "single_system_validated": False,
            "geospatial_kernel_validated": False,
        },
    }
    return csv_body, report


def compile_domain(
    *,
    initial_state_manifest_path: Path = DEFAULT_INITIAL_STATE_MANIFEST,
    forcing_support_path: Path = DEFAULT_FORCING_SUPPORT,
    route_link_manifest_path: Path = DEFAULT_ROUTE_LINK_MANIFEST,
    travel_report_path: Path = DEFAULT_TRAVEL_REPORT,
) -> tuple[HoldoutReachDomain, dict[str, Any]]:
    initial_body, initial = _load_json(initial_state_manifest_path)
    support_body, support = _load_json(forcing_support_path)
    route_manifest_body, route_manifest = _load_json(route_link_manifest_path)
    travel_body, travel = _load_json(travel_report_path)
    if initial.get("schema") != "gwm.geotransport.center_hill_nwm_v3_initial_state.v1":
        raise ValueError("center_hill_v2_initial_state_manifest_invalid")
    if (initial.get("claim_boundary") or {}).get(
        "retrospective_modeled_initial_state_available"
    ) is not True:
        raise ValueError("center_hill_v2_initial_state_not_available")
    if support.get("schema") != "gwm.geospatial_kernel.reach_forcing_spatial_support.v1":
        raise ValueError("center_hill_v2_forcing_support_invalid")
    if support.get("admitted_as_spatial_support") is not True:
        raise ValueError("center_hill_v2_forcing_support_not_admitted")
    if route_manifest.get("schema") != "gwm.geotransport.center_hill_route_link_v3_acquisition.v1":
        raise ValueError("center_hill_v2_route_link_manifest_invalid")
    if (route_manifest.get("adjudication") or {}).get(
        "center_hill_active_feature_coverage_complete"
    ) is not True:
        raise ValueError("center_hill_v2_route_link_coverage_incomplete")
    path = _linear_path(travel["linear_referenced_path"])
    state_payload = initial["decoded_state"]
    active_ids = tuple(int(value) for value in state_payload["active_feature_ids"])
    if tuple(int(value) for value in support["feature_ids"]) != active_ids:
        raise ValueError("center_hill_v2_support_initial_state_axis_mismatch")
    if tuple(
        feature_id
        for feature_id, length in zip(
            path.feature_ids, path.effective_lengths_m, strict=True
        )
        if length > 1e-6
    ) != active_ids:
        raise ValueError("center_hill_v2_path_initial_state_axis_mismatch")
    route_descriptor = route_manifest["subset"]
    route_path = _resolve_descriptor_path(route_descriptor)
    route_body = _read_verified(route_descriptor)
    route_rows = _route_link_rows(route_path)
    selected = [route_rows[feature_id] for feature_id in active_ids]
    for upstream, downstream in zip(selected[:-1], selected[1:], strict=True):
        if int(upstream["to"]) != int(downstream["link"]):
            raise ValueError("center_hill_v2_route_link_topology_mismatch")
    effective_length = {
        feature_id: length
        for feature_id, length in zip(
            path.feature_ids, path.effective_lengths_m, strict=True
        )
    }
    geometry = ReachHydraulicGeometry(
        feature_ids=active_ids,
        bottom_width_m=tuple(float(row["BtmWdth"]) for row in selected),
        side_slope_horizontal_per_vertical=tuple(
            1.0 / float(row["ChSlp"]) for row in selected
        ),
        bed_slope=tuple(float(row["So"]) for row in selected),
        manning_n=tuple(float(row["n"]) for row in selected),
        provenance_id="nwm-v3-route-link:center-hill:ChSlp-inverse",
        evidence_level="derived",
        admitted_as_hydraulic_geometry=True,
    )
    support_fractions = tuple(float(value) for value in support["coverage_fractions"])
    uncertainty = support["coverage_uncertainty"]
    supports = {
        "central": _forcing_support(support, support_fractions, "central"),
        "lower": _forcing_support(
            support,
            support_fractions[:-1] + (float(uncertainty["lower_fraction"]),),
            "lower_30m_bracket",
        ),
        "upper": _forcing_support(
            support,
            support_fractions[:-1] + (float(uncertainty["upper_fraction"]),),
            "upper_30m_bracket",
        ),
    }
    nonlinear_state = state_payload["nonlinear_storage_state"]
    t_route_state_payload = state_payload["t_route_state"]
    parameters = TrouteMuskingumCungeParameters(
        feature_ids=active_ids,
        # The first and terminal segments are cropped to the admitted path endpoints.
        length_m=tuple(float(effective_length[value]) for value in active_ids),
        bottom_width_m=tuple(float(row["BtmWdth"]) for row in selected),
        top_width_m=tuple(float(row["TopWdth"]) for row in selected),
        compound_top_width_m=tuple(float(row["TopWdthCC"]) for row in selected),
        manning_n=tuple(float(row["n"]) for row in selected),
        compound_manning_n=tuple(float(row["nCC"]) for row in selected),
        channel_side_slope_chslp=tuple(float(row["ChSlp"]) for row in selected),
        bed_slope=tuple(float(row["So"]) for row in selected),
        provenance_id="nwm-v3-route-link:center-hill:path-cropped-lengths",
    )
    domain = HoldoutReachDomain(
        path=path,
        geometry=geometry,
        initial_stock=StockState(
            tuple(float(value) for value in nonlinear_state["storage_m3"]),
            "m3",
            "nwm-v3-retrospective:2022-02-03T00Z:modeled-initial-state",
        ),
        forcing_support_central=supports["central"],
        forcing_support_lower=supports["lower"],
        forcing_support_upper=supports["upper"],
        t_route_parameters=parameters,
        t_route_initial_state=TrouteMuskingumCungeState(
            feature_ids=active_ids,
            discharge_m3s=tuple(float(value) for value in t_route_state_payload["discharge_m3s"]),
            velocity_mps=tuple(float(value) for value in t_route_state_payload["velocity_ms"]),
            depth_m=tuple(float(value) for value in t_route_state_payload["depth_m"]),
            provenance_id="nwm-v3-retrospective:2022-02-03T00Z:t-route-qvd",
        ),
        provenance_id="center-hill:v2:D0-D2",
    )
    artifacts = {
        "initial_state_manifest": _artifact(initial_state_manifest_path, initial_body),
        "forcing_support": _artifact(forcing_support_path, support_body),
        "route_link_manifest": _artifact(route_link_manifest_path, route_manifest_body),
        "route_link_subset": _artifact(route_path, route_body),
        "linear_referenced_path": _artifact(travel_report_path, travel_body),
    }
    return domain, artifacts


def _validate_input_manifests(action: Mapping[str, Any], forcing: Mapping[str, Any]) -> None:
    if action.get("schema") != ACTION_MANIFEST_SCHEMA:
        raise ValueError("center_hill_v2_action_manifest_invalid")
    if action.get("variable_role") != "boundary_action" or action.get("outcome_included") is not False:
        raise ValueError("center_hill_v2_action_manifest_role_invalid")
    if forcing.get("schema") != FORCING_MANIFEST_SCHEMA:
        raise ValueError("center_hill_v2_forcing_manifest_invalid")
    if (
        forcing.get("variable_role") != "modeled_forcing"
        or forcing.get("ground_truth") is not False
        or forcing.get("time_chunk_indices") != [561]
        or forcing.get("feature_chunk_indices") != [63]
    ):
        raise ValueError("center_hill_v2_forcing_manifest_role_invalid")
    forbidden = ("outcome", "observed", "observation", "usgs")
    for manifest in (action, forcing):
        lowered = json.dumps(manifest, sort_keys=True).lower()
        if any(token in lowered for token in forbidden):
            allowed = (
                manifest is action
                and '"outcome_included": false' in lowered
                and all(token not in lowered for token in forbidden[1:])
                and lowered.count("outcome") == 1
            )
            if not allowed:
                raise ValueError("center_hill_v2_executor_manifest_contains_outcome_role")


def _parse_actions(body: bytes) -> dict[datetime, float]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    if reader.fieldnames != [
        "support_start_utc",
        "support_end_utc",
        "action_release_m3s",
        "source_role",
    ]:
        raise ValueError("center_hill_v2_action_columns_invalid")
    result: dict[datetime, float] = {}
    for row in reader:
        start = _parse_utc(row["support_start_utc"])
        end = _parse_utc(row["support_end_utc"])
        if end - start != timedelta(hours=1) or row["source_role"] != "boundary_action":
            raise ValueError("center_hill_v2_action_row_semantics_invalid")
        result[start] = float(row["action_release_m3s"])
    expected = {START + timedelta(hours=index) for index in range(HOUR_COUNT)}
    if set(result) != expected:
        raise ValueError("center_hill_v2_action_time_axis_mismatch")
    return result


def _parse_q_lateral(
    body: bytes, *, expected_feature_ids: tuple[int, ...]
) -> dict[datetime, dict[int, float]]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    required = {"timestamp_utc", "feature_id", "q_lateral_m3s", "source_role"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("center_hill_v2_q_lateral_columns_invalid")
    forbidden = {"outcome", "observed_m3s", "usgs_discharge_m3s"}
    if forbidden.intersection(reader.fieldnames):
        raise ValueError("center_hill_v2_q_lateral_contains_outcome_column")
    result: dict[datetime, dict[int, float]] = {}
    for row in reader:
        if row["source_role"] != "modeled_forcing":
            raise ValueError("center_hill_v2_q_lateral_role_invalid")
        timestamp = _parse_utc(row["timestamp_utc"])
        feature_id = int(row["feature_id"])
        result.setdefault(timestamp, {})[feature_id] = float(row["q_lateral_m3s"])
    expected_times = {START + timedelta(hours=index) for index in range(HOUR_COUNT)}
    if set(result) != expected_times or any(
        tuple(values) != expected_feature_ids for values in result.values()
    ):
        raise ValueError("center_hill_v2_q_lateral_axis_mismatch")
    return result


def _linear_path(payload: Mapping[str, Any]) -> LinearReferencedPath:
    return LinearReferencedPath(
        path_id=str(payload["path_id"]),
        feature_ids=tuple(int(value) for value in payload["feature_ids"]),
        full_lengths_m=tuple(float(value) for value in payload["full_lengths_m"]),
        entry_offsets_m=tuple(float(value) for value in payload["entry_offsets_m"]),
        exit_offsets_m=tuple(float(value) for value in payload["exit_offsets_m"]),
        provenance_id=str(payload["provenance_id"]),
        evidence_level=str(payload["evidence_level"]),
    )


def _forcing_support(
    source: Mapping[str, Any], fractions: tuple[float, ...], suffix: str
) -> ReachForcingSupport:
    return ReachForcingSupport(
        feature_ids=tuple(int(value) for value in source["feature_ids"]),
        coverage_fractions=fractions,
        support_method=f"{source['support_method']}|{suffix}",
        provenance_id=f"{source['provenance_id']}|{suffix}",
        evidence_level=str(source["evidence_level"]),
        admitted_as_spatial_support=True,
    )


def _route_link_rows(path: Path) -> dict[int, dict[str, float | int]]:
    names = (
        "link", "to", "Length", "BtmWdth", "TopWdth", "TopWdthCC",
        "ChSlp", "So", "n", "nCC",
    )
    with netcdf_file(path, "r", mmap=False) as dataset:
        arrays = {name: np.asarray(dataset.variables[name][:]).copy() for name in names}
    return {
        int(arrays["link"][index]): {
            name: int(values[index]) if name in {"link", "to"} else float(values[index])
            for name, values in arrays.items()
        }
        for index in range(len(arrays["link"]))
    }


def _encode_rows(rows: tuple[Mapping[str, object], ...]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    return body, json.loads(body)


def _resolve_descriptor_path(descriptor: Mapping[str, Any]) -> Path:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("center_hill_v2_artifact_outside_repository") from exc
    return path


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = _resolve_descriptor_path(descriptor)
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != descriptor.get("sha256") or len(body) != descriptor.get("size_bytes"):
        raise ValueError("center_hill_v2_artifact_identity_mismatch")
    return body


def _artifact_from_descriptor(descriptor: Mapping[str, Any], body: bytes) -> dict[str, Any]:
    return {
        "path": str(descriptor["path"]),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
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


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("center_hill_v2_timestamp_must_be_timezone_aware")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main() -> int:
    args = parse_args()
    kernel = CtypesTrouteMuskingumCungeKernel(args.build_manifest)
    csv_body, report = compile_rollout(
        action_manifest_path=args.action_manifest,
        forcing_manifest_path=args.forcing_manifest,
        t_route_kernel=kernel,
        output_path=args.output,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(csv_body)
    _write_json(args.report, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
