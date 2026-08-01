#!/usr/bin/env python3
"""Freeze downstream evaluation of the causal Smith Fork boundary transition."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PARENT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_internal_boundary_development_protocol.json"
)
DEFAULT_PARENT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_internal_boundary_development_report.json"
)
DEFAULT_TRANSITION_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/smith_fork_boundary_transition_report.json"
)
DEFAULT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_dynamic_internal_boundary_protocol.json"
)
SCHEMA = "gwm.geotransport.center_hill_dynamic_internal_boundary_protocol.v1"
PARENT_PROTOCOL_SCHEMA = (
    "gwm.geotransport.center_hill_internal_boundary_development_protocol.v1"
)
PARENT_REPORT_SCHEMA = (
    "gwm.geotransport.center_hill_internal_boundary_development.v1"
)
TRANSITION_REPORT_SCHEMA = (
    "gwm.geotransport.smith_fork_boundary_transition_report.v1"
)
CORE_PATHS = (
    "data_agent/uwm/geospatial_kernel_v2/boundary_hydrograph.py",
    "data_agent/uwm/geospatial_kernel_v2/branching_network.py",
    "data_agent/uwm/geospatial_kernel_v2/forecast_closure.py",
)
HORIZONS = (1, 3, 6, 12, 24)
CORE_HORIZONS = (3, 6, 12, 24)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--parent-protocol", type=Path, default=DEFAULT_PARENT_PROTOCOL
    )
    parser.add_argument("--parent-report", type=Path, default=DEFAULT_PARENT_REPORT)
    parser.add_argument(
        "--transition-report", type=Path, default=DEFAULT_TRANSITION_REPORT
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    return parser.parse_args()


def compile_protocol(
    *,
    parent_protocol_path: Path,
    parent_report_path: Path,
    transition_report_path: Path,
) -> dict[str, Any]:
    parent_protocol_body, parent_protocol = _load(parent_protocol_path)
    parent_report_body, parent_report = _load(parent_report_path)
    transition_body, transition = _load(transition_report_path)
    if (
        parent_protocol.get("schema") != PARENT_PROTOCOL_SCHEMA
        or parent_protocol.get("status")
        != "frozen_before_internal_boundary_development_execution"
        or parent_report.get("schema") != PARENT_REPORT_SCHEMA
        or parent_report.get("registered_gates", {}).get(
            "development_gate_passed"
        )
        is not False
        or transition.get("schema") != TRANSITION_REPORT_SCHEMA
        or transition.get("registered_gates", {}).get(
            "all_horizons_holdout_gate_passed"
        )
        is not True
    ):
        raise ValueError("dynamic_internal_boundary_parent_evidence_invalid")
    parent_predictions = parent_report["outputs"]["predictions"]
    parameter_descriptor = transition["outputs"]["parameters"]
    _read_verified(parent_predictions)
    _read_verified(parameter_descriptor)
    return {
        "schema": SCHEMA,
        "status": "frozen_before_dynamic_internal_boundary_execution",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "parent_evidence": {
            "parent_internal_boundary_protocol": _artifact(
                parent_protocol_path, parent_protocol_body
            ),
            "parent_internal_boundary_report": _artifact(
                parent_report_path, parent_report_body
            ),
            "parent_internal_boundary_predictions": parent_predictions,
            "boundary_transition_report": _artifact(
                transition_report_path, transition_body
            ),
            "boundary_transition_parameters": parameter_descriptor,
            "internal_boundary_reference": parent_report["source_artifacts"][
                "internal_boundary_reference"
            ],
        },
        "core_code": {
            path: _artifact(REPO_ROOT / path, (REPO_ROOT / path).read_bytes())
            for path in CORE_PATHS
        },
        "window_and_horizons": {
            **parent_protocol["window_and_horizons"],
            "core_horizons_hours": list(CORE_HORIZONS),
        },
        "gis_compilation_lock": parent_protocol["gis_compilation_lock"],
        "operator_lock": {
            **parent_protocol["operator_lock"],
            "boundary_transition": "stationary_ar2_on_log1p_hourly_discharge",
            "transition_parameter_source": "pre_window_smith_fork_only",
            "boundary_flow_alignment": (
                "for transition ending issue_time_plus_k use AR2 forecast valid "
                "at issue_time_plus_k"
            ),
            "latest_observation_at_issue": "issue_time_minus_one_hour",
            "required_history": "two consecutive available hourly observations",
            "missing_history": "fall back to modeled upstream transfer",
            "future_boundary_observations": "forbidden",
        },
        "baseline_and_gate_lock": {
            "baselines_reused_from_hash_verified_parent": [
                "held_observed_internal_boundary",
                "modeled_cut_control",
                "zero_internal_boundary",
                "parent_local_multi_gauge",
                "causal_latency_matched_persistence",
                "zero_latency_archive_persistence",
            ],
            "primary_metric": "rmse_m3s",
            "common_complete_case_mask_per_horizon": True,
            "per_core_horizon_gate": (
                "dynamic boundary RMSE below held boundary, modeled cut, zero "
                "boundary, parent local, and causal persistence"
            ),
            "development_gate": (
                "all four core horizons plus conservation; no compensation"
            ),
            "one_hour_can_change_development_gate": False,
        },
        "information_track": {
            "name": "retrospective_oracle_action_forcing_causal_boundary_forecast",
            "future_realized_action_used": True,
            "future_retrospective_q_lateral_used": True,
            "future_outlet_target_used": False,
            "future_smith_fork_observation_used": False,
            "observation_operational_vintage_verified": False,
            "operational_forecast_claim_permitted": False,
        },
        "forbidden_after_freeze": [
            "change AR2 coefficients or maximum discharge",
            "change cut geometry or forcing support fraction",
            "fit any parameter from Center Hill outlet targets",
            "use future Smith Fork observations within a branch",
            "omit a failed horizon",
            "claim the linear reference or partial forcing support is admitted",
        ],
        "data_isolation": {
            "boundary_parameters_fitted_from_outlet_targets": False,
            "boundary_parameters_fitted_from_current_window": False,
            "window_outcomes_previously_accessed": True,
            "prospective_or_validation_claim_permitted": False,
            "untouched_window_consumed": False,
        },
        "claim_boundary_before_execution": {
            "boundary_transition_upstream_holdout_passed": True,
            "dynamic_internal_boundary_diagnostic_executed": False,
            "internal_boundary_reference_admitted": False,
            "partial_forcing_support_admitted": False,
            "downstream_improvement_validated": False,
            "operational_forecast_evaluated": False,
            "geospatial_kernel_validated": False,
        },
    }


def _load(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    return body, json.loads(body)


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("dynamic_internal_boundary_artifact_identity_mismatch")
    return body


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _json_body(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def main() -> int:
    args = parse_args()
    if args.protocol.exists():
        raise ValueError("dynamic_internal_boundary_protocol_refuses_overwrite")
    protocol = compile_protocol(
        parent_protocol_path=args.parent_protocol,
        parent_report_path=args.parent_report,
        transition_report_path=args.transition_report,
    )
    body = _json_body(protocol)
    args.protocol.parent.mkdir(parents=True, exist_ok=True)
    args.protocol.write_bytes(body)
    print(args.protocol)
    print(hashlib.sha256(body).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
