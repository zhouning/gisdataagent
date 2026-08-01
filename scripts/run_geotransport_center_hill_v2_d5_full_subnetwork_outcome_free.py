#!/usr/bin/env python3
"""Run and seal the D5 full-subnetwork rollout without loading outcomes."""

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
    ActionBoundaryFlux,
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportConfig,
    DirectedReachNetwork,
    ForcingFlux,
    ReachForcingSupport,
    ReachHydraulicGeometry,
    StockState,
)

if __package__:
    from scripts.run_geotransport_center_hill_v2_outcome_free import (
        DEFAULT_ACTION_MANIFEST,
        compile_domain,
    )
else:
    from run_geotransport_center_hill_v2_outcome_free import (
        DEFAULT_ACTION_MANIFEST,
        compile_domain,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOPOLOGY_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_v2_d5_full_subnetwork_report.json"
)
DEFAULT_INPUT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_v2_d5_subnetwork_inputs_report.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d5_full_subnetwork_rollout/"
    "predictions.csv"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_v2_d5_full_subnetwork_rollout_report.json"
)
SCHEMA = "gwm.geotransport.center_hill_v2_d5_full_subnetwork_rollout.v1"
TOPOLOGY_SCHEMA = "gwm.geotransport.center_hill_v2_d5_full_subnetwork.v1"
INPUT_SCHEMA = "gwm.geotransport.center_hill_v2_d5_subnetwork_inputs.v1"
START = datetime(2022, 2, 3, 1, tzinfo=timezone.utc)
HOUR_COUNT = 672
TIMESTEP_SECONDS = 3600.0
SUBSTEP_SECONDS = 300.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action-manifest", type=Path, default=DEFAULT_ACTION_MANIFEST)
    parser.add_argument("--topology-report", type=Path, default=DEFAULT_TOPOLOGY_REPORT)
    parser.add_argument("--input-report", type=Path, default=DEFAULT_INPUT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_rollout(
    *,
    action_manifest_path: Path = DEFAULT_ACTION_MANIFEST,
    topology_report_path: Path = DEFAULT_TOPOLOGY_REPORT,
    input_report_path: Path = DEFAULT_INPUT_REPORT,
    output_path: Path = DEFAULT_OUTPUT,
) -> tuple[bytes, dict[str, Any]]:
    action_body = action_manifest_path.read_bytes()
    action_manifest = json.loads(action_body)
    _validate_action_manifest(action_manifest)
    action_values_body = _read_verified(action_manifest["action_values"])
    actions = _parse_actions(action_values_body)

    topology_body = topology_report_path.read_bytes()
    topology = json.loads(topology_body)
    if (
        topology.get("schema") != TOPOLOGY_SCHEMA
        or topology.get("status") != "pass_full_incremental_subnetwork_compiled"
        or (topology.get("data_isolation") or {}).get("d3_outcome_values_loaded")
        is not False
        or (topology.get("gates") or {}).get("all_upstream_ancestors_compiled")
        is not True
    ):
        raise ValueError("center_hill_d5_rollout_topology_report_invalid")
    network_body = _read_verified(topology["artifacts"]["full_subnetwork"])
    network_payload = json.loads(network_body)
    network = _network(network_payload["network"])
    if network.outlet_feature_id != 18_421_703:
        raise ValueError("center_hill_d5_rollout_outlet_mismatch")
    d4_network_body = _read_verified(topology["artifacts"]["d4_network"])
    d4_network_payload = json.loads(d4_network_body)["network"]
    mainstem_ids = tuple(int(value) for value in d4_network_payload["feature_ids"])
    if not set(mainstem_ids).issubset(network.feature_ids):
        raise ValueError("center_hill_d5_rollout_mainstem_not_in_subnetwork")
    branch_ids = set(network.feature_ids) - set(mainstem_ids)
    if len(branch_ids) != topology["domain"]["incremental_branch_feature_count"]:
        raise ValueError("center_hill_d5_rollout_branch_count_mismatch")

    input_body = input_report_path.read_bytes()
    inputs = json.loads(input_body)
    expected_semantics = {
        "initial_streamflow": {
            "conservation_oracle": False,
            "ground_truth": False,
            "modeled": True,
            "observation": False,
            "possible_nudging": True,
            "role": "retrospective_modeled_initial_state",
        },
        "initial_velocity": {
            "admitted_as_flood_wave_celerity": False,
            "ground_truth": False,
            "modeled": True,
            "role": "retrospective_modeled_initial_state_context",
        },
        "q_lateral": {
            "conservation_oracle": False,
            "ground_truth": False,
            "modeled": True,
            "observation": False,
            "role": "modeled_distributed_reach_forcing",
        },
    }
    if (
        inputs.get("schema") != INPUT_SCHEMA
        or inputs.get("status")
        != "pass_outcome_free_full_subnetwork_inputs_acquired"
        or inputs.get("semantic_contract") != expected_semantics
        or (inputs.get("data_isolation") or {}).get("d3_outcome_values_loaded")
        is not False
        or inputs["topology_report"]["sha256"] != hashlib.sha256(
            topology_body
        ).hexdigest()
    ):
        raise ValueError("center_hill_d5_rollout_input_report_invalid")
    arrays = {
        name: _read_npy(descriptor)
        for name, descriptor in inputs["decoded_arrays"].items()
    }
    feature_ids = tuple(int(value) for value in arrays["feature_ids"])
    if feature_ids != network.feature_ids:
        raise ValueError("center_hill_d5_rollout_feature_axis_mismatch")
    q_lateral = np.asarray(arrays["q_lateral_m3s"], dtype=float)
    initial_storage = np.asarray(arrays["initial_storage_m3"], dtype=float)
    timestamps = tuple(str(value) for value in arrays["forcing_timestamps_utc"])
    if (
        q_lateral.shape != (HOUR_COUNT, len(feature_ids))
        or initial_storage.shape != (len(feature_ids),)
        or timestamps
        != tuple(_iso(START + timedelta(hours=value)) for value in range(HOUR_COUNT))
    ):
        raise ValueError("center_hill_d5_rollout_dynamic_axis_mismatch")

    route_link_body = _read_verified(topology["artifacts"]["route_link_subset"])
    route_link_path = REPO_ROOT / topology["artifacts"]["route_link_subset"]["path"]
    geometry = _geometry(route_link_path, network, route_link_body)
    prior_domain, prior_domain_artifacts = compile_domain()
    prior_support = {
        feature_id: fraction
        for feature_id, fraction in zip(
            prior_domain.forcing_support_central.feature_ids,
            prior_domain.forcing_support_central.coverage_fractions,
            strict=True,
        )
    }
    if tuple(prior_support) != mainstem_ids:
        raise ValueError("center_hill_d5_rollout_prior_mainstem_support_mismatch")
    forcing_support = ReachForcingSupport(
        feature_ids=network.feature_ids,
        coverage_fractions=tuple(
            prior_support.get(feature_id, 1.0) for feature_id in network.feature_ids
        ),
        support_method=(
            "D2 audited mainstem terminal support; full support for complete "
            "RouteLink tributary reaches"
        ),
        provenance_id=(
            f"{prior_domain.forcing_support_central.provenance_id}|"
            f"d5-full-subnetwork:{hashlib.sha256(network_body).hexdigest()}"
        ),
        evidence_level="derived",
        admitted_as_spatial_support=True,
    )
    operator = BranchingManningNetworkTransportOperator(
        network,
        BranchingNetworkTransportConfig(
            timestep_seconds=TIMESTEP_SECONDS,
            integration_substep_seconds=SUBSTEP_SECONDS,
            operator_form_admitted=True,
        ),
    )
    actual_state = StockState(
        values=tuple(float(value) for value in initial_storage),
        unit="m3",
        provenance_id=(
            "nwm-v3-retrospective-modeled-initial-state:"
            f"{inputs['decoded_arrays']['initial_storage_m3']['sha256']}"
        ),
    )
    branch_mask = np.asarray(
        [feature_id in branch_ids for feature_id in network.feature_ids], dtype=bool
    )
    silent_initial = initial_storage.copy()
    silent_initial[branch_mask] = 0.0
    silent_state = StockState(
        values=tuple(float(value) for value in silent_initial),
        unit="m3",
        provenance_id="negative-control:branch-initial-state-zero",
    )
    index = {feature_id: offset for offset, feature_id in enumerate(feature_ids)}
    action_index = index[network.action_entry_feature_ids[0]]
    rows: list[dict[str, object]] = []
    actual_residual_ratios: list[float] = []
    silent_residual_ratios: list[float] = []
    actual_boundary_flags: list[bool] = []
    actual_initial_total = float(initial_storage.sum())
    silent_initial_total = float(silent_initial.sum())
    for hour in range(HOUR_COUNT):
        support_start = START + timedelta(hours=hour)
        support_end = support_start + timedelta(hours=1)
        action_values = np.zeros(len(feature_ids), dtype=float)
        action_values[action_index] = actions[support_start]
        forcing_values = q_lateral[hour]
        silent_forcing = forcing_values.copy()
        silent_forcing[branch_mask] = 0.0
        action = ActionBoundaryFlux(
            values=tuple(float(value) for value in action_values),
            unit="m3 s-1",
            provenance_id=f"center-hill:d5:action:{hour:03d}",
        )
        actual = operator.step(
            actual_state,
            geometry,
            action=action,
            forcing=ForcingFlux(
                values=tuple(float(value) for value in forcing_values),
                unit="m3 s-1",
                provenance_id=f"nwm-v3:q-lateral:d5:{hour:03d}",
                modeled=True,
            ),
            forcing_support=forcing_support,
        )
        silent = operator.step(
            silent_state,
            geometry,
            action=action,
            forcing=ForcingFlux(
                values=tuple(float(value) for value in silent_forcing),
                unit="m3 s-1",
                provenance_id=f"negative-control:branch-q-lateral-zero:{hour:03d}",
                modeled=True,
            ),
            forcing_support=forcing_support,
        )
        actual_state = actual.next_stock
        silent_state = silent.next_stock
        actual_residual_ratios.append(
            abs(actual.global_mass_balance_residual_m3)
            / actual.numeric_mass_tolerance_m3
        )
        silent_residual_ratios.append(
            abs(silent.global_mass_balance_residual_m3)
            / silent.numeric_mass_tolerance_m3
        )
        actual_boundary_flags.append(actual.modeled_tributary_boundary_used)
        rows.append(
            {
                "support_start_utc": _iso(support_start),
                "support_end_utc": _iso(support_end),
                "d5_full_subnetwork_m3s": actual.outlet_mean_flow_m3s,
                "d5_branch_silent_negative_control_m3s": (
                    silent.outlet_mean_flow_m3s
                ),
                "action_input_m3s": float(action_values.sum()),
                "distributed_q_lateral_input_m3s": float(forcing_values.sum()),
                "branch_q_lateral_input_m3s": float(
                    forcing_values[branch_mask].sum()
                ),
            }
        )

    zero = operator.step(
        operator.zero_state(provenance_id="negative-control:zero-state"),
        geometry,
        action=ActionBoundaryFlux(
            values=(0.0,) * len(feature_ids),
            unit="m3 s-1",
            provenance_id="negative-control:zero-action",
        ),
        forcing=ForcingFlux(
            values=(0.0,) * len(feature_ids),
            unit="m3 s-1",
            provenance_id="negative-control:zero-forcing",
            modeled=True,
        ),
        forcing_support=forcing_support,
    )
    zero_passed = (
        zero.outlet_mean_flow_m3s == 0.0
        and zero.final_network_storage_m3 == 0.0
        and zero.global_mass_balance_residual_m3 == 0.0
    )
    if (
        max(actual_residual_ratios) > 1.0
        or max(silent_residual_ratios) > 1.0
        or any(actual_boundary_flags)
        or not zero_passed
    ):
        raise RuntimeError("center_hill_d5_rollout_invariant_failed")

    csv_body = _encode_rows(rows)
    actual_values = np.asarray(
        [float(value["d5_full_subnetwork_m3s"]) for value in rows]
    )
    silent_values = np.asarray(
        [float(value["d5_branch_silent_negative_control_m3s"]) for value in rows]
    )
    return csv_body, {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "outcome_free_full_subnetwork_rollout_complete",
        "window": {
            "start_inclusive": _iso(START),
            "end_exclusive": _iso(START + timedelta(hours=HOUR_COUNT)),
            "hour_count": HOUR_COUNT,
        },
        "input_artifacts": {
            "action_manifest": _artifact(action_manifest_path, action_body),
            "action_values": {**action_manifest["action_values"]},
            "topology_report": _artifact(topology_report_path, topology_body),
            "full_subnetwork": {**topology["artifacts"]["full_subnetwork"]},
            "route_link_subset": {**topology["artifacts"]["route_link_subset"]},
            "subnetwork_input_report": _artifact(input_report_path, input_body),
            "decoded_arrays": {**inputs["decoded_arrays"]},
            "prior_mainstem_support": prior_domain_artifacts["forcing_support"],
        },
        "prediction_artifact": {
            "path": _display(output_path),
            "sha256": hashlib.sha256(csv_body).hexdigest(),
            "size_bytes": len(csv_body),
        },
        "registered_execution": {
            "operator": "BranchingManningNetworkTransportOperator",
            "network_mode": "complete_incremental_tributary_DAG",
            "feature_count": len(feature_ids),
            "mainstem_feature_count": len(mainstem_ids),
            "incremental_branch_feature_count": len(branch_ids),
            "timestep_seconds": int(TIMESTEP_SECONDS),
            "integration_substep_seconds": int(SUBSTEP_SECONDS),
            "mainstem_partial_forcing_support": "D2 central unchanged",
            "complete_branch_forcing_support": 1.0,
            "modeled_tributary_boundary_used": False,
            "distributed_q_lateral_ground_truth": False,
            "initial_streamflow_ground_truth": False,
            "initial_streamflow_possible_nudging": True,
        },
        "result": {
            "prediction_count": len(actual_values),
            "prediction_minimum_m3s": float(actual_values.min()),
            "prediction_maximum_m3s": float(actual_values.max()),
            "prediction_mean_m3s": float(actual_values.mean()),
            "branch_silent_mean_m3s": float(silent_values.mean()),
            "mean_branch_effect_m3s": float(
                (actual_values - silent_values).mean()
            ),
            "initial_network_storage_m3": actual_initial_total,
            "branch_silent_initial_storage_m3": silent_initial_total,
        },
        "invariants": {
            "actual_maximum_mass_residual_to_tolerance_ratio": max(
                actual_residual_ratios
            ),
            "branch_silent_maximum_mass_residual_to_tolerance_ratio": max(
                silent_residual_ratios
            ),
            "actual_conservation_passed": max(actual_residual_ratios) <= 1.0,
            "branch_silent_conservation_passed": (
                max(silent_residual_ratios) <= 1.0
            ),
            "zero_state_zero_input_identity_passed": zero_passed,
            "modeled_tributary_boundary_never_used": not any(actual_boundary_flags),
        },
        "negative_controls": {
            "branch_silent": {
                "definition": (
                    "all 409 branch initial stocks and distributed q_lateral set "
                    "to zero; mainstem initial state, forcing, and action unchanged"
                ),
                "full_window_executed": True,
                "outcome_used": False,
            },
            "zero_identity": {
                "definition": "zero stock plus zero action plus zero forcing",
                "one_step_executed": True,
                "outcome_used": False,
                "passed": zero_passed,
            },
        },
        "data_isolation": {
            "outcome_manifest_accepted_by_executor": False,
            "outcome_columns_accepted_by_executor": False,
            "outcome_values_loaded": False,
            "usgs_observation_loaded": False,
            "d3_rollout_artifact_loaded": False,
            "d4_rollout_artifact_loaded": False,
            "d3_window_role": "post_failure_public_structural_development",
        },
        "claim_boundary": {
            "complete_incremental_topology_executed": True,
            "modeled_tributary_boundary_executed": False,
            "distributed_subnetwork_routing_executed": True,
            "outcome_free_prediction_sealed": True,
            "predictions_scored": False,
            "full_subnetwork_routing_ready": True,
            "predictive_improvement_validated": False,
            "geospatial_kernel_validated": False,
            "new_frozen_evaluation_window_required": True,
            "second_system_required": True,
        },
    }


def _network(payload: Mapping[str, Any]) -> DirectedReachNetwork:
    return DirectedReachNetwork(
        network_id=str(payload["network_id"]),
        feature_ids=tuple(int(value) for value in payload["feature_ids"]),
        downstream_feature_ids=tuple(
            None if value is None else int(value)
            for value in payload["downstream_feature_ids"]
        ),
        full_lengths_m=tuple(float(value) for value in payload["full_lengths_m"]),
        effective_lengths_m=tuple(
            float(value) for value in payload["effective_lengths_m"]
        ),
        action_entry_feature_ids=tuple(
            int(value) for value in payload["action_entry_feature_ids"]
        ),
        provenance_id=str(payload["provenance_id"]),
        evidence_level=str(payload["evidence_level"]),
        admitted=bool(payload["admitted"]),
    )


def _geometry(
    path: Path, network: DirectedReachNetwork, body: bytes
) -> ReachHydraulicGeometry:
    names = ("link", "BtmWdth", "ChSlp", "So", "n")
    with netcdf_file(path, "r", mmap=False) as dataset:
        arrays = {
            name: np.asarray(dataset.variables[name][:]).copy() for name in names
        }
    links = tuple(int(value) for value in arrays["link"])
    if links != network.feature_ids:
        raise ValueError("center_hill_d5_rollout_geometry_axis_mismatch")
    return ReachHydraulicGeometry(
        feature_ids=network.feature_ids,
        bottom_width_m=tuple(float(value) for value in arrays["BtmWdth"]),
        side_slope_horizontal_per_vertical=tuple(
            float(1.0 / value) for value in arrays["ChSlp"]
        ),
        bed_slope=tuple(float(value) for value in arrays["So"]),
        manning_n=tuple(float(value) for value in arrays["n"]),
        provenance_id=f"nwm-v3-routelink:{hashlib.sha256(body).hexdigest()}",
        evidence_level="authoritative",
        admitted_as_hydraulic_geometry=True,
    )


def _validate_action_manifest(payload: Mapping[str, Any]) -> None:
    if (
        payload.get("schema") != "gwm.geotransport.center_hill_v2_action_input.v1"
        or payload.get("variable_role") != "boundary_action"
        or payload.get("outcome_included") is not False
        or (payload.get("result") or {}).get("hour_count") != HOUR_COUNT
        or (payload.get("result") or {}).get("missing_value_count") != 0
    ):
        raise ValueError("center_hill_d5_rollout_action_manifest_invalid")


def _parse_actions(body: bytes) -> dict[datetime, float]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    expected = [
        "support_start_utc",
        "support_end_utc",
        "action_release_m3s",
        "source_role",
    ]
    if reader.fieldnames != expected:
        raise ValueError("center_hill_d5_rollout_action_columns_invalid")
    actions: dict[datetime, float] = {}
    for row in reader:
        start = _parse_utc(row["support_start_utc"])
        end = _parse_utc(row["support_end_utc"])
        value = float(row["action_release_m3s"])
        if (
            end - start != timedelta(hours=1)
            or row["source_role"] != "boundary_action"
            or not np.isfinite(value)
            or value < 0.0
        ):
            raise ValueError("center_hill_d5_rollout_action_value_invalid")
        actions[start] = value
    expected_times = {
        START + timedelta(hours=value) for value in range(HOUR_COUNT)
    }
    if set(actions) != expected_times:
        raise ValueError("center_hill_d5_rollout_action_time_axis_mismatch")
    return actions


def _read_npy(descriptor: Mapping[str, Any]) -> np.ndarray:
    body = _read_verified(descriptor)
    array = np.load(io.BytesIO(body), allow_pickle=False)
    if str(array.dtype) != descriptor.get("dtype") or list(array.shape) != descriptor.get(
        "shape"
    ):
        raise ValueError("center_hill_d5_rollout_npy_schema_mismatch")
    return array


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("center_hill_d5_rollout_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("center_hill_d5_rollout_artifact_identity_mismatch")
    return body


def _encode_rows(rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


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
        raise ValueError("center_hill_d5_rollout_timezone_required")
    return parsed.astimezone(timezone.utc)


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
    csv_body, report = compile_rollout(
        action_manifest_path=args.action_manifest,
        topology_report_path=args.topology_report,
        input_report_path=args.input_report,
        output_path=args.output,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(csv_body)
    _write_json(args.report, report)
    print(args.report)
    print(f"prediction_sha256={report['prediction_artifact']['sha256']}")
    print(
        "actual_maximum_mass_residual_to_tolerance_ratio="
        f"{report['invariants']['actual_maximum_mass_residual_to_tolerance_ratio']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
