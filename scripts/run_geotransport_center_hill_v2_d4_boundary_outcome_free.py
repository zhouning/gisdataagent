#!/usr/bin/env python3
"""Run the Center Hill D4 tributary-boundary diagnostic without outcomes."""

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
    DirectedReachNetwork,
    ForcingFlux,
    ModeledTributaryBoundaryFlux,
    TributaryConfluence,
)
if __package__:
    from scripts.run_geotransport_center_hill_v2_outcome_free import (
        DEFAULT_ACTION_MANIFEST,
        DEFAULT_FORCING_MANIFEST,
        START,
        HOUR_COUNT,
        _parse_actions,
        _parse_q_lateral,
        _read_verified,
        _validate_input_manifests,
        compile_domain,
    )
else:
    from run_geotransport_center_hill_v2_outcome_free import (
        DEFAULT_ACTION_MANIFEST,
        DEFAULT_FORCING_MANIFEST,
        START,
        HOUR_COUNT,
        _parse_actions,
        _parse_q_lateral,
        _read_verified,
        _validate_input_manifests,
        compile_domain,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOPOLOGY_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_v2_d4_topology_report.json"
)
DEFAULT_BOUNDARY_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_v2_d4_tributary_boundary_report.json"
)
DEFAULT_D3_ROLLOUT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_v2_d3_rollout_report.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d4_boundary_rollout/predictions.csv"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_v2_d4_boundary_rollout_report.json"
)
SCHEMA = "gwm.geotransport.center_hill_v2_d4_boundary_rollout.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action-manifest", type=Path, default=DEFAULT_ACTION_MANIFEST)
    parser.add_argument(
        "--forcing-manifest", type=Path, default=DEFAULT_FORCING_MANIFEST
    )
    parser.add_argument(
        "--topology-report", type=Path, default=DEFAULT_TOPOLOGY_REPORT
    )
    parser.add_argument(
        "--boundary-report", type=Path, default=DEFAULT_BOUNDARY_REPORT
    )
    parser.add_argument(
        "--d3-rollout-report", type=Path, default=DEFAULT_D3_ROLLOUT_REPORT
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_rollout(
    *,
    action_manifest_path: Path = DEFAULT_ACTION_MANIFEST,
    forcing_manifest_path: Path = DEFAULT_FORCING_MANIFEST,
    topology_report_path: Path = DEFAULT_TOPOLOGY_REPORT,
    boundary_report_path: Path = DEFAULT_BOUNDARY_REPORT,
    d3_rollout_report_path: Path = DEFAULT_D3_ROLLOUT_REPORT,
    output_path: Path = DEFAULT_OUTPUT,
) -> tuple[bytes, dict[str, Any]]:
    action_body, action_manifest = _load_json(action_manifest_path)
    forcing_body, forcing_manifest = _load_json(forcing_manifest_path)
    _validate_input_manifests(action_manifest, forcing_manifest)
    action_values_body = _read_verified(action_manifest["action_values"])
    forcing_values_body = _read_verified(forcing_manifest["q_lateral_values"])
    actions = _parse_actions(action_values_body)
    domain, domain_artifacts = compile_domain()
    q_lateral = _parse_q_lateral(
        forcing_values_body,
        expected_feature_ids=domain.geometry.feature_ids,
    )

    topology_body, topology_report = _load_json(topology_report_path)
    if (
        topology_report.get("status") != "pass_direct_confluence_boundary_ready"
        or (topology_report.get("data_isolation") or {}).get(
            "d3_outcome_values_loaded"
        )
        is not False
    ):
        raise ValueError("center_hill_d4_rollout_topology_report_invalid")
    network_body = _read_descriptor(
        topology_report["artifacts"]["branching_boundary_network"]
    )
    network_payload = json.loads(network_body)
    network = _network(network_payload["network"])
    confluences = tuple(
        _confluence(payload)
        for payload in network_payload["external_tributary_confluences"]
    )
    if network.feature_ids != domain.geometry.feature_ids:
        raise ValueError("center_hill_d4_rollout_network_domain_axis_mismatch")

    boundary_body, boundary_report = _load_json(boundary_report_path)
    if (
        boundary_report.get("status")
        != "pass_outcome_free_tributary_boundary_acquired"
        or boundary_report.get("semantic_contract")
        != {
            "conservation_oracle": False,
            "evaluation_outcome": False,
            "ground_truth": False,
            "modeled": True,
            "possible_nudging": True,
            "variable_role": "modeled_tributary_boundary_flux",
        }
        or (boundary_report.get("data_isolation") or {}).get(
            "outcome_values_loaded"
        )
        is not False
    ):
        raise ValueError("center_hill_d4_rollout_boundary_report_invalid")
    if boundary_report["topology_report"]["sha256"] != _sha256(topology_body):
        raise ValueError("center_hill_d4_rollout_topology_hash_mismatch")
    boundary_values_body = _read_descriptor(boundary_report["normalized_values"])
    boundary_values = _parse_boundaries(
        boundary_values_body,
        network=network,
        confluences=confluences,
    )

    d3_report_body, d3_report = _load_json(d3_rollout_report_path)
    if (
        d3_report.get("status") != "outcome_free_rollout_complete"
        or (d3_report.get("data_isolation") or {}).get("outcome_values_loaded")
        is not False
    ):
        raise ValueError("center_hill_d4_rollout_d3_reference_invalid")
    d3_prediction_body = _read_descriptor(d3_report["prediction_artifact"])
    d3_central = _parse_d3_central(d3_prediction_body)

    operator = BranchingManningNetworkTransportOperator(
        network,
        BranchingNetworkTransportConfig(
            timestep_seconds=3600.0,
            integration_substep_seconds=300.0,
            operator_form_admitted=True,
        ),
        external_confluences=confluences,
    )
    mainstem_state = domain.initial_stock
    boundary_state = domain.initial_stock
    rows: list[dict[str, object]] = []
    mainstem_residual_ratios: list[float] = []
    boundary_residual_ratios: list[float] = []
    reference_differences: list[float] = []
    for hour in range(HOUR_COUNT):
        support_start = START + timedelta(hours=hour)
        support_end = support_start + timedelta(hours=1)
        action_values = tuple(
            actions[support_start] if index == 0 else 0.0
            for index in range(len(network.feature_ids))
        )
        forcing_values = tuple(
            q_lateral[support_start][feature_id]
            for feature_id in network.feature_ids
        )
        action = ActionBoundaryFlux(
            action_values,
            "m3 s-1",
            f"center_hill:d4:action:{hour:03d}",
        )
        forcing = ForcingFlux(
            forcing_values,
            "m3 s-1",
            f"center_hill:d4:q-lateral:{hour:03d}",
            modeled=True,
        )
        mainstem_result = operator.step(
            mainstem_state,
            domain.geometry,
            action=action,
            forcing=forcing,
            forcing_support=domain.forcing_support_central,
        )
        boundary_flux_values = boundary_values[support_start]
        boundary_result = operator.step(
            boundary_state,
            domain.geometry,
            action=action,
            forcing=forcing,
            forcing_support=domain.forcing_support_central,
            tributary_boundary=ModeledTributaryBoundaryFlux(
                feature_ids=network.feature_ids,
                values=boundary_flux_values,
                unit="m3 s-1",
                provenance_id=f"nwm-v3:streamflow:tributary-mouth:{hour:03d}",
            ),
        )
        mainstem_state = mainstem_result.next_stock
        boundary_state = boundary_result.next_stock
        reference = d3_central[support_start]
        difference = mainstem_result.outlet_mean_flow_m3s - reference
        reference_differences.append(abs(difference))
        mainstem_residual_ratios.append(
            abs(mainstem_result.global_mass_balance_residual_m3)
            / mainstem_result.numeric_mass_tolerance_m3
        )
        boundary_residual_ratios.append(
            abs(boundary_result.global_mass_balance_residual_m3)
            / boundary_result.numeric_mass_tolerance_m3
        )
        rows.append(
            {
                "support_start_utc": _iso(support_start),
                "support_end_utc": _iso(support_end),
                "d3_nonlinear_central_reference_m3s": reference,
                "d4_mainstem_only_reproduction_m3s": (
                    mainstem_result.outlet_mean_flow_m3s
                ),
                "d4_modeled_tributary_boundary_m3s": (
                    boundary_result.outlet_mean_flow_m3s
                ),
                "modeled_tributary_boundary_input_m3s": sum(
                    boundary_flux_values
                ),
            }
        )
    maximum_difference = max(reference_differences)
    if maximum_difference > 1e-9:
        raise RuntimeError("center_hill_d4_mainstem_reference_not_reproduced")
    csv_body = _encode_rows(rows)
    return csv_body, {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "outcome_free_boundary_rollout_complete",
        "window": {
            "start_inclusive": _iso(START),
            "end_exclusive": _iso(START + timedelta(hours=HOUR_COUNT)),
            "hour_count": HOUR_COUNT,
        },
        "input_artifacts": {
            "action_manifest": _artifact(action_manifest_path, action_body),
            "modeled_forcing_manifest": _artifact(
                forcing_manifest_path, forcing_body
            ),
            "topology_report": _artifact(topology_report_path, topology_body),
            "branching_boundary_network": {
                **topology_report["artifacts"]["branching_boundary_network"]
            },
            "tributary_boundary_report": _artifact(
                boundary_report_path, boundary_body
            ),
            "tributary_boundary_values": {
                **boundary_report["normalized_values"]
            },
            "d3_rollout_report": _artifact(
                d3_rollout_report_path, d3_report_body
            ),
            "d3_predictions": {**d3_report["prediction_artifact"]},
            "domain": domain_artifacts,
        },
        "prediction_artifact": {
            "path": _display(output_path),
            "sha256": _sha256(csv_body),
            "size_bytes": len(csv_body),
        },
        "registered_execution": {
            "operator": "BranchingManningNetworkTransportOperator",
            "network_mode": "mainstem_with_external_confluence_attachments",
            "timestep_seconds": 3600,
            "integration_substep_seconds": 300,
            "terminal_forcing_support": "D2 central",
            "tributary_boundary_variable_role": (
                "modeled_tributary_boundary_flux"
            ),
            "tributary_boundary_ground_truth": False,
            "tributary_boundary_possible_nudging": True,
        },
        "invariants": {
            "d3_mainstem_reference_maximum_absolute_difference_m3s": (
                maximum_difference
            ),
            "d3_mainstem_reference_reproduced": True,
            "mainstem_maximum_mass_residual_to_tolerance_ratio": max(
                mainstem_residual_ratios
            ),
            "boundary_maximum_mass_residual_to_tolerance_ratio": max(
                boundary_residual_ratios
            ),
            "mainstem_conservation_passed": max(mainstem_residual_ratios) <= 1.0,
            "boundary_conservation_passed": max(boundary_residual_ratios) <= 1.0,
        },
        "data_isolation": {
            "outcome_manifest_accepted_by_executor": False,
            "outcome_columns_accepted_by_executor": False,
            "outcome_values_loaded": False,
            "usgs_observation_loaded": False,
            "d3_window_role": "post_failure_public_development_diagnostic",
        },
        "claim_boundary": {
            "modeled_tributary_boundary_executed": True,
            "independent_end_to_end_prediction": False,
            "predictions_scored": False,
            "full_subnetwork_routing_ready": False,
            "predictive_improvement_validated": False,
            "geospatial_kernel_validated": False,
        },
    }


def _network(payload: Mapping[str, Any]) -> DirectedReachNetwork:
    return DirectedReachNetwork(
        network_id=str(payload["network_id"]),
        feature_ids=tuple(int(value) for value in payload["feature_ids"]),
        downstream_feature_ids=tuple(
            int(value) if value is not None else None
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


def _confluence(payload: Mapping[str, Any]) -> TributaryConfluence:
    return TributaryConfluence(
        tributary_feature_id=int(payload["tributary_feature_id"]),
        receiving_feature_id=int(payload["receiving_feature_id"]),
        longitude=float(payload["coordinate"][0]),
        latitude=float(payload["coordinate"][1]),
        upstream_network_compiled=bool(payload["upstream_network_compiled"]),
        provenance_id=str(payload["provenance_id"]),
        evidence_level=str(payload["evidence_level"]),
        admitted=bool(payload["admitted"]),
    )


def _parse_boundaries(
    body: bytes,
    *,
    network: DirectedReachNetwork,
    confluences: tuple[TributaryConfluence, ...],
) -> dict[datetime, tuple[float, ...]]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    expected_tributary_columns = [
        f"tributary_{value.tributary_feature_id}_m3s" for value in confluences
    ]
    expected_fields = (
        ["support_start_utc", "support_end_utc"]
        + expected_tributary_columns
        + ["total_modeled_tributary_boundary_m3s"]
    )
    if reader.fieldnames != expected_fields:
        raise ValueError("center_hill_d4_boundary_columns_invalid")
    index = {value: offset for offset, value in enumerate(network.feature_ids)}
    result: dict[datetime, tuple[float, ...]] = {}
    for row in reader:
        support_start = _parse_utc(row["support_start_utc"])
        support_end = _parse_utc(row["support_end_utc"])
        if support_end - support_start != timedelta(hours=1):
            raise ValueError("center_hill_d4_boundary_support_invalid")
        values = np.zeros(len(network.feature_ids), dtype=float)
        total = 0.0
        for confluence, column in zip(
            confluences, expected_tributary_columns, strict=True
        ):
            value = float(row[column])
            if not np.isfinite(value) or value < 0.0:
                raise ValueError("center_hill_d4_boundary_value_invalid")
            values[index[confluence.receiving_feature_id]] += value
            total += value
        if not np.isclose(
            total,
            float(row["total_modeled_tributary_boundary_m3s"]),
            rtol=0.0,
            atol=1e-8,
        ):
            raise ValueError("center_hill_d4_boundary_total_mismatch")
        result[support_start] = tuple(float(value) for value in values)
    expected_times = {
        START + timedelta(hours=index) for index in range(HOUR_COUNT)
    }
    if set(result) != expected_times:
        raise ValueError("center_hill_d4_boundary_time_axis_mismatch")
    return result


def _parse_d3_central(body: bytes) -> dict[datetime, float]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    if not reader.fieldnames or "nonlinear_central_m3s" not in reader.fieldnames:
        raise ValueError("center_hill_d4_d3_central_column_missing")
    result = {
        _parse_utc(row["support_start_utc"]): float(row["nonlinear_central_m3s"])
        for row in reader
    }
    if len(result) != HOUR_COUNT:
        raise ValueError("center_hill_d4_d3_central_time_axis_mismatch")
    return result


def _encode_rows(rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _read_descriptor(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("center_hill_d4_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        _sha256(body) != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("center_hill_d4_artifact_identity_mismatch")
    return body


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    return body, json.loads(body)


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": _display(path),
        "sha256": _sha256(body),
        "size_bytes": len(body),
    }


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("center_hill_d4_timestamp_timezone_required")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main() -> int:
    args = parse_args()
    csv_body, report = compile_rollout(
        action_manifest_path=args.action_manifest,
        forcing_manifest_path=args.forcing_manifest,
        topology_report_path=args.topology_report,
        boundary_report_path=args.boundary_report,
        d3_rollout_report_path=args.d3_rollout_report,
        output_path=args.output,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(csv_body)
    _write_json(args.report, report)
    print(args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
