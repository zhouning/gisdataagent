#!/usr/bin/env python3
"""Freeze the prospective outcome-free internal-instrumentation protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_internal_innovation_rollout_protocol.json"
)
SCHEMA = "gwm.geospatial_kernel.internal_innovation_rollout_protocol.v1"
FROZEN_AT = "2026-07-31T06:06:33Z"
SYSTEM_IDS = ("center_hill", "j_percy_priest")
CODE_PATHS = (
    "data_agent/uwm/geospatial_kernel_v2/contracts.py",
    "data_agent/uwm/geospatial_kernel_v2/conservative_flux.py",
    "data_agent/uwm/geospatial_kernel_v2/conservative_edge_flux_innovation.py",
    "data_agent/uwm/geospatial_kernel_v2/branching_network.py",
    "data_agent/uwm/geospatial_kernel_v2/kinematic_wave.py",
    "data_agent/uwm/geospatial_kernel_v2/branching_kinematic_wave.py",
    "data_agent/uwm/geospatial_kernel_v2/internal_innovation_instrumentation.py",
    "data_agent/uwm/geospatial_kernel_v2/instrumented_physical_rollout.py",
    "scripts/assess_geospatial_kernel_internal_innovation_readiness.py",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_protocol(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "frozen_awaiting_prospective_outcome_free_inputs",
        "frozen_at": FROZEN_AT,
        "systems": {
            "system_ids": list(SYSTEM_IDS),
            "system_count": len(SYSTEM_IDS),
            "cross_system_parameter_sharing_required": True,
            "system_specific_refit_after_target_outcome_access": False,
        },
        "operator_roles": {
            "primary_accuracy_floor": {
                "operator": "BranchingManningNetworkTransportOperator",
                "schema": ("gwm.geospatial_kernel.branching_manning_network_storage.v1"),
                "role": "raw_physical_minimum_accuracy_bar",
            },
            "diagnostic_replication": {
                "operator": "BranchingFiniteVolumeKinematicWaveOperator",
                "schema": ("gwm.geospatial_kernel.branching_finite_volume_kinematic_wave.v1"),
                "role": "independent_operator_form_diagnostic_only",
            },
            "candidate_internal_innovation": {
                "operator": "ConservativeEdgeFluxInnovationOperator",
                "schema": ("gwm.geospatial_kernel.conservative_edge_flux_innovation.v1"),
                "role": "signed_internal_edge_transfer_adjustment",
                "default_enabled": False,
                "runtime_admitted": False,
            },
        },
        "prospective_episode_contract": {
            "support_must_start_after_protocol_freeze": True,
            "forecast_issue_must_not_follow_support_start": True,
            "every_input_available_at_or_before_issue": True,
            "episode_horizon_hours": 24,
            "hourly_steps_per_episode": 24,
            "minimum_sealed_episodes_per_system_before_diagnostic_fit": 28,
            "minimum_sealed_hourly_steps_per_system_before_diagnostic_fit": 672,
            "episode_selection_after_outcome_access": False,
            "rolling_issue_times_allowed": True,
            "one_telemetry_bundle_per_issue_time": True,
        },
        "required_hash_bound_inputs_per_episode": {
            "feature_axis": "immutable ordered reach identifiers",
            "edge_axis": "immutable admitted directed reach connections",
            "hydraulic_geometry": "width slope roughness and effective length",
            "initial_state": ("modeled stock or cell volume with possible-nudging label"),
            "reservoir_action_schedule": ("release boundary values known at forecast issue"),
            "distributed_forcing_forecast": (
                "modeled lateral inflow values known at forecast issue"
            ),
            "input_availability_receipts": (
                "source provenance and available_at for every dynamic input"
            ),
        },
        "forbidden_executor_inputs": [
            "outcome_values",
            "outcome_columns",
            "outcome_manifest",
            "outcome_path",
            "outcome_url",
            "future_target_observations",
        ],
        "required_outputs_per_episode": {
            "prediction_artifact": "outlet physical prediction without outcomes",
            "feature_axis_artifact": "gwm.geospatial_kernel.feature_axis.v1",
            "edge_axis_artifact": "gwm.geospatial_kernel.edge_axis.v1",
            "reach_state_artifact": ("gwm.geospatial_kernel.reach_state_timeseries.v1"),
            "edge_flux_artifact": ("gwm.geospatial_kernel.edge_flux_timeseries.v1"),
            "step_mass_ledger_artifact": ("gwm.geospatial_kernel.step_mass_ledger.v1"),
            "telemetry_bundle": ("gwm.geospatial_kernel.internal_innovation_telemetry.v1"),
        },
        "mandatory_gates_before_diagnostic_fit": {
            "source_artifact_hashes_match": True,
            "prediction_and_internal_artifacts_sealed_before_outcomes": True,
            "feature_and_edge_axes_semantically_valid": True,
            "state_transition_continuity_verified": True,
            "every_step_mass_ledger_recomputed_conservative": True,
            "causal_input_availability_verified": True,
            "modeled_internal_state_not_labeled_as_observation": True,
            "two_system_episode_minimum_met": True,
        },
        "fit_and_evaluation_order": [
            "seal outcome-free physical predictions and internal telemetry",
            "pass independent semantic readiness assessment",
            "freeze cross-system candidate parameterization",
            "acquire outcomes only after candidate predictions are sealed",
            "score raw physical and physical-plus-internal-innovation jointly",
            "retain candidate only if it beats raw physical on both systems",
        ],
        "claim_boundary": {
            "protocol_frozen": True,
            "prospective_inputs_acquired": False,
            "prospective_predictions_executed": False,
            "outcomes_loaded": False,
            "internal_innovation_fitted": False,
            "candidate_promoted": False,
            "runtime_enabled": False,
            "geospatial_kernel_validated": False,
            "historical_posthoc_inputs_may_be_relabelled_prospective": False,
        },
        "frozen_code": {path: _artifact(root, path) for path in CODE_PATHS},
    }
    protocol_body = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["protocol_seal"] = {
        "algorithm": "sha256_canonical_json_without_protocol_seal",
        "sha256": hashlib.sha256(protocol_body).hexdigest(),
    }
    return payload


def _artifact(root: Path, relative_path: str) -> dict[str, object]:
    path = (root / relative_path).resolve()
    try:
        display = path.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("internal_innovation_protocol_code_outside_repository") from error
    body = path.read_bytes()
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def main() -> int:
    args = parse_args()
    payload = compile_protocol()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(f"status={payload['status']}")
    print(f"protocol_sha256={payload['protocol_seal']['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
