#!/usr/bin/env python3
"""Run and jointly seal both blind-validation predictions without outcomes."""

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

from data_agent.uwm.geospatial_kernel_v2 import (
    ActionBoundaryFlux,
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportConfig,
    ForcingFlux,
    ReachForcingSupport,
    StockState,
)

if __package__:
    from scripts.freeze_geotransport_v2_blind_validation_protocol import (
        END,
        HOUR_COUNT,
        SCHEMA as PROTOCOL_SCHEMA,
        START,
        SUBSTEP_SECONDS,
        TIMESTEP_SECONDS,
    )
    from scripts.run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
        _geometry,
        _network,
        _read_npy,
    )
else:
    from freeze_geotransport_v2_blind_validation_protocol import (
        END,
        HOUR_COUNT,
        SCHEMA as PROTOCOL_SCHEMA,
        START,
        SUBSTEP_SECONDS,
        TIMESTEP_SECONDS,
    )
    from run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
        _geometry,
        _network,
        _read_npy,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geotransport_v2_blind_validation_protocol.json"
)
DEFAULT_INPUT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geotransport_v2_blind_validation_inputs_report.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/geotransport_v2_blind_validation/predictions"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geotransport_v2_blind_validation_rollout_report.json"
)
SCHEMA = "gwm.geotransport.v2_blind_validation_rollout.v1"
INPUT_SCHEMA = "gwm.geotransport.v2_blind_validation_inputs.v1"
SYSTEM_IDS = ("center_hill", "j_percy_priest")
OUTCOME_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/geotransport_v2_blind_validation/outcomes"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--input-report", type=Path, default=DEFAULT_INPUT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_rollouts(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    input_report_path: Path = DEFAULT_INPUT_REPORT,
    output_root: Path = DEFAULT_OUTPUT,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    if OUTCOME_ROOT.exists():
        raise ValueError("blind_validation_rollout_forbidden_after_outcome_access")
    protocol_body = protocol_path.read_bytes()
    protocol = json.loads(protocol_body)
    inputs_body = input_report_path.read_bytes()
    inputs = json.loads(inputs_body)
    if (
        protocol.get("schema") != PROTOCOL_SCHEMA
        or protocol.get("status")
        != "frozen_before_dynamic_input_and_outcome_access"
        or inputs.get("schema") != INPUT_SCHEMA
        or inputs.get("status")
        != "pass_outcome_free_two_system_inputs_acquired"
        or inputs.get("protocol", {}).get("sha256")
        != hashlib.sha256(protocol_body).hexdigest()
        or (inputs.get("data_isolation") or {}).get("outcome_values_loaded")
        is not False
    ):
        raise ValueError("blind_validation_rollout_inputs_or_protocol_invalid")

    predictions: dict[str, bytes] = {}
    system_reports: dict[str, dict[str, Any]] = {}
    for system_id in SYSTEM_IDS:
        body, report = _run_system(
            system_id=system_id,
            lock=protocol["systems"][system_id],
            inputs=inputs["systems"][system_id],
            output_path=output_root / f"{system_id}.csv",
        )
        predictions[system_id] = body
        system_reports[system_id] = report
    if any(
        not report["invariants"]["actual_conservation_passed"]
        or not report["invariants"]["branch_silent_conservation_passed"]
        or not report["invariants"]["zero_state_zero_input_identity_passed"]
        or not report["invariants"]["modeled_tributary_boundary_never_used"]
        for report in system_reports.values()
    ):
        raise RuntimeError("blind_validation_joint_rollout_invariant_failed")
    prediction_descriptors = {
        system_id: report["prediction_artifact"]
        for system_id, report in system_reports.items()
    }
    seal_payload = json.dumps(
        {
            "protocol_sha256": hashlib.sha256(protocol_body).hexdigest(),
            "input_report_sha256": hashlib.sha256(inputs_body).hexdigest(),
            "predictions": prediction_descriptors,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return predictions, {
        "schema": SCHEMA,
        "status": "joint_outcome_free_predictions_sealed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "start_inclusive": _iso(START),
            "end_exclusive": _iso(END),
            "hour_count": HOUR_COUNT,
        },
        "input_artifacts": {
            "protocol": _artifact(protocol_path, protocol_body),
            "input_report": _artifact(input_report_path, inputs_body),
        },
        "systems": system_reports,
        "joint_seal": {
            "algorithm": "sha256_canonical_json",
            "sha256": hashlib.sha256(seal_payload).hexdigest(),
            "sealed_system_ids": list(SYSTEM_IDS),
            "all_predictions_present": True,
            "all_invariants_passed": True,
            "outcome_access_permitted_after_this_report_is_written": True,
        },
        "data_isolation": {
            "outcome_manifest_accepted_by_executor": False,
            "outcome_path_accepted_by_executor": False,
            "outcome_columns_accepted_by_executor": False,
            "outcome_urls_requested": False,
            "outcome_values_loaded": False,
            "usgs_observations_loaded": False,
        },
        "claim_boundary": {
            "two_system_complete_subnetworks_executed": True,
            "outcome_free_predictions_sealed": True,
            "predictions_scored": False,
            "outcomes_acquired": False,
            "predictive_validation_complete": False,
            "geospatial_kernel_validated": False,
        },
    }


def _run_system(
    *,
    system_id: str,
    lock: Mapping[str, Any],
    inputs: Mapping[str, Any],
    output_path: Path,
) -> tuple[bytes, dict[str, Any]]:
    topology_body = _read_verified(lock["topology_report"])
    topology = json.loads(topology_body)
    network_body = _read_verified(topology["artifacts"]["full_subnetwork"])
    network_payload = json.loads(network_body)
    network = _network(network_payload["network"])
    if (
        network.action_entry_feature_ids != (int(lock["action_entry_feature_id"]),)
        or network.outlet_feature_id != int(lock["outlet_feature_id"])
        or len(network.feature_ids) != int(lock["feature_count"])
    ):
        raise ValueError(f"blind_validation_{system_id}_network_lock_mismatch")
    if system_id == "center_hill":
        d4_body = _read_verified(topology["artifacts"]["d4_network"])
        mainstem_ids = tuple(
            int(value) for value in json.loads(d4_body)["network"]["feature_ids"]
        )
    else:
        mainstem_ids = tuple(
            int(value)
            for value in network_payload["linear_referenced_mainstem"]["feature_ids"]
        )
    branch_ids = set(network.feature_ids) - set(mainstem_ids)
    if (
        len(mainstem_ids) != int(lock["mainstem_feature_count"])
        or len(branch_ids) != int(lock["branch_feature_count"])
    ):
        raise ValueError(f"blind_validation_{system_id}_domain_count_mismatch")

    arrays = {
        name: _read_npy(descriptor)
        for name, descriptor in inputs["decoded_arrays"].items()
    }
    feature_ids = tuple(int(value) for value in arrays["feature_ids"])
    q_lateral = np.asarray(arrays["q_lateral_m3s"], dtype=float)
    initial_storage = np.asarray(arrays["initial_storage_m3"], dtype=float)
    timestamps = tuple(str(value) for value in arrays["forcing_timestamps_utc"])
    if (
        feature_ids != network.feature_ids
        or q_lateral.shape != (HOUR_COUNT, len(feature_ids))
        or initial_storage.shape != (len(feature_ids),)
        or timestamps
        != tuple(_iso(START + timedelta(hours=index)) for index in range(HOUR_COUNT))
    ):
        raise ValueError(f"blind_validation_{system_id}_dynamic_axis_mismatch")
    actions = _parse_actions(_read_verified(inputs["action_values"]))
    route_link_body = _read_verified(topology["artifacts"]["route_link_subset"])
    route_link_path = REPO_ROOT / topology["artifacts"]["route_link_subset"]["path"]
    geometry = _geometry(route_link_path, network, route_link_body)
    terminal_fraction = float(
        lock["forcing_support"]["partial_terminal_reach_fraction"]
    )
    support_values = tuple(
        terminal_fraction if feature == network.outlet_feature_id else 1.0
        for feature in network.feature_ids
    )
    forcing_support = ReachForcingSupport(
        feature_ids=network.feature_ids,
        coverage_fractions=support_values,
        support_method=str(
            lock["forcing_support"]["partial_terminal_reach_method"]
        ),
        provenance_id=(
            f"blind-protocol:{hashlib.sha256(json.dumps(lock, sort_keys=True).encode()).hexdigest()}"
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
        [feature in branch_ids for feature in feature_ids], dtype=bool
    )
    silent_initial = initial_storage.copy()
    silent_initial[branch_mask] = 0.0
    silent_state = StockState(
        values=tuple(float(value) for value in silent_initial),
        unit="m3",
        provenance_id=f"negative-control:{system_id}:branch-initial-state-zero",
    )
    action_index = feature_ids.index(network.action_entry_feature_ids[0])
    rows: list[dict[str, object]] = []
    actual_ratios: list[float] = []
    silent_ratios: list[float] = []
    boundary_flags: list[bool] = []
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
            provenance_id=f"{system_id}:blind-action:{hour:03d}",
        )
        actual = operator.step(
            actual_state,
            geometry,
            action=action,
            forcing=ForcingFlux(
                values=tuple(float(value) for value in forcing_values),
                unit="m3 s-1",
                provenance_id=f"nwm-v3:{system_id}:q-lateral:{hour:03d}",
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
                provenance_id=f"negative-control:{system_id}:branch-zero:{hour:03d}",
                modeled=True,
            ),
            forcing_support=forcing_support,
        )
        actual_state = actual.next_stock
        silent_state = silent.next_stock
        actual_ratios.append(
            abs(actual.global_mass_balance_residual_m3)
            / actual.numeric_mass_tolerance_m3
        )
        silent_ratios.append(
            abs(silent.global_mass_balance_residual_m3)
            / silent.numeric_mass_tolerance_m3
        )
        boundary_flags.append(actual.modeled_tributary_boundary_used)
        rows.append(
            {
                "support_start_utc": _iso(support_start),
                "support_end_utc": _iso(support_end),
                "kernel_full_subnetwork_m3s": actual.outlet_mean_flow_m3s,
                "branch_silent_negative_control_m3s": silent.outlet_mean_flow_m3s,
                "action_input_m3s": float(action_values.sum()),
                "distributed_q_lateral_input_m3s": float(forcing_values.sum()),
                "branch_q_lateral_input_m3s": float(
                    forcing_values[branch_mask].sum()
                ),
            }
        )
    zero = operator.step(
        operator.zero_state(provenance_id=f"negative-control:{system_id}:zero-state"),
        geometry,
        action=ActionBoundaryFlux(
            values=(0.0,) * len(feature_ids),
            unit="m3 s-1",
            provenance_id=f"negative-control:{system_id}:zero-action",
        ),
        forcing=ForcingFlux(
            values=(0.0,) * len(feature_ids),
            unit="m3 s-1",
            provenance_id=f"negative-control:{system_id}:zero-forcing",
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
        max(actual_ratios) > 1.0
        or max(silent_ratios) > 1.0
        or any(boundary_flags)
        or not zero_passed
    ):
        raise RuntimeError(f"blind_validation_{system_id}_rollout_invariant_failed")
    csv_body = _encode_rows(rows)
    actual_values = np.asarray(
        [float(row["kernel_full_subnetwork_m3s"]) for row in rows]
    )
    silent_values = np.asarray(
        [float(row["branch_silent_negative_control_m3s"]) for row in rows]
    )
    return csv_body, {
        "system_id": system_id,
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
            "branch_feature_count": len(branch_ids),
            "timestep_seconds": TIMESTEP_SECONDS,
            "integration_substep_seconds": SUBSTEP_SECONDS,
            "terminal_forcing_support_fraction": terminal_fraction,
            "terminal_forcing_support_method": lock["forcing_support"][
                "partial_terminal_reach_method"
            ],
            "modeled_tributary_boundary_used": False,
            "initial_state_ground_truth": False,
            "initial_state_possible_nudging": True,
            "distributed_q_lateral_ground_truth": False,
        },
        "result": {
            "prediction_count": len(actual_values),
            "prediction_minimum_m3s": float(actual_values.min()),
            "prediction_maximum_m3s": float(actual_values.max()),
            "prediction_mean_m3s": float(actual_values.mean()),
            "branch_silent_mean_m3s": float(silent_values.mean()),
            "mean_branch_effect_m3s": float((actual_values - silent_values).mean()),
            "initial_network_storage_m3": float(initial_storage.sum()),
            "branch_silent_initial_storage_m3": float(silent_initial.sum()),
        },
        "invariants": {
            "actual_maximum_mass_residual_to_tolerance_ratio": max(actual_ratios),
            "branch_silent_maximum_mass_residual_to_tolerance_ratio": max(
                silent_ratios
            ),
            "actual_conservation_passed": max(actual_ratios) <= 1.0,
            "branch_silent_conservation_passed": max(silent_ratios) <= 1.0,
            "zero_state_zero_input_identity_passed": zero_passed,
            "modeled_tributary_boundary_never_used": not any(boundary_flags),
        },
        "data_isolation": {
            "outcome_values_loaded": False,
            "outcome_columns_accepted": False,
            "outcome_path_accepted": False,
        },
    }


def _parse_actions(body: bytes) -> dict[datetime, float]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    if reader.fieldnames != [
        "support_start_utc",
        "support_end_utc",
        "action_release_m3s",
        "source_role",
    ]:
        raise ValueError("blind_validation_action_columns_invalid")
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
            raise ValueError("blind_validation_action_value_invalid")
        actions[start] = value
    expected = {START + timedelta(hours=index) for index in range(HOUR_COUNT)}
    if set(actions) != expected:
        raise ValueError("blind_validation_action_time_axis_mismatch")
    return actions


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("blind_validation_rollout_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("blind_validation_rollout_artifact_identity_mismatch")
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
        raise ValueError("blind_validation_timezone_required")
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
    predictions, report = compile_rollouts(
        protocol_path=args.protocol,
        input_report_path=args.input_report,
        output_root=args.output,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    for system_id, body in predictions.items():
        (args.output / f"{system_id}.csv").write_bytes(body)
    _write_json(args.report, report)
    print(args.report)
    print(f"joint_seal_sha256={report['joint_seal']['sha256']}")
    for system_id in SYSTEM_IDS:
        print(
            f"{system_id}_prediction_sha256="
            f"{report['systems'][system_id]['prediction_artifact']['sha256']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
