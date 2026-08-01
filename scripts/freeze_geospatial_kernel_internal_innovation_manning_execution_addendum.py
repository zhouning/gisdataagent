#!/usr/bin/env python3
"""Freeze the Manning executor and prospective execution-ledger identities."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_PROTOCOL_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_internal_innovation_rollout_protocol.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_internal_innovation_manning_execution_addendum.json"
)
SCHEMA = "gwm.geospatial_kernel.internal_innovation_manning_execution_addendum.v1"
BASE_PROTOCOL_SCHEMA = "gwm.geospatial_kernel.internal_innovation_rollout_protocol.v1"
BASE_PROTOCOL_FILE_SHA256 = "411071ad99c597358199710365e1267e2ce0847685484208b2a1169056ba8f41"
BASE_PROTOCOL_SEAL_SHA256 = "9d69d960c43a972d77d42267fa4fe854e6b85f9f13dae9ea7cf50b7888901fd3"
FROZEN_AT = "2026-07-31T10:23:29Z"
CODE_PATHS = (
    "scripts/assess_geospatial_kernel_internal_innovation_episode_preflight.py",
    "scripts/run_geospatial_kernel_internal_innovation_manning_episode.py",
    "scripts/compile_geospatial_kernel_internal_innovation_execution_ledger.py",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_addendum(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    protocol_path = root / BASE_PROTOCOL_PATH.relative_to(REPO_ROOT)
    protocol_body = protocol_path.read_bytes()
    protocol = json.loads(protocol_body)
    if (
        hashlib.sha256(protocol_body).hexdigest() != BASE_PROTOCOL_FILE_SHA256
        or protocol.get("schema") != BASE_PROTOCOL_SCHEMA
        or protocol.get("protocol_seal", {}).get("sha256")
        != BASE_PROTOCOL_SEAL_SHA256
    ):
        raise ValueError("internal_innovation_execution_addendum_base_protocol_mismatch")
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "frozen_before_prospective_manning_episode_execution",
        "frozen_at": FROZEN_AT,
        "base_rollout_protocol": {
            "path": BASE_PROTOCOL_PATH.relative_to(REPO_ROOT).as_posix(),
            "sha256": BASE_PROTOCOL_FILE_SHA256,
            "size_bytes": len(protocol_body),
            "schema": BASE_PROTOCOL_SCHEMA,
            "protocol_seal_sha256": BASE_PROTOCOL_SEAL_SHA256,
            "bytes_modified": False,
        },
        "executor_contract": {
            "execution_schema": (
                "gwm.geospatial_kernel.prospective_manning_episode_execution.v2"
            ),
            "prediction_schema": (
                "gwm.geospatial_kernel.prospective_physical_prediction.v1"
            ),
            "operator": "BranchingManningNetworkTransportOperator",
            "operator_schema": (
                "gwm.geospatial_kernel.branching_manning_network_storage.v1"
            ),
            "episode_horizon_hours": 24,
            "hourly_step_count": 24,
            "timestep_seconds": 3600.0,
            "integration_substep_seconds": 300.0,
            "output_directory_must_not_exist": True,
            "all_input_identities_recomputed_before_execution": True,
            "prediction_and_five_telemetry_artifacts_hash_bound": True,
            "outcome_argument_accepted": False,
            "network_requests_performed": False,
        },
        "execution_ledger_contract": {
            "schema": "gwm.geospatial_kernel.internal_innovation_execution_ledger.v1",
            "complete_manifest_inventory_required": True,
            "complete_execution_report_inventory_required": True,
            "manifest_prediction_and_five_telemetry_identities_recomputed": True,
            "duplicate_episode_system_issue_or_output_hash_rejected": True,
            "minimum_unique_issue_times_per_system": 28,
            "minimum_sealed_hourly_prediction_steps_per_system": 672,
            "required_system_ids": ["center_hill", "j_percy_priest"],
            "diagnostic_fit_gate_logic": "all_noncompensatory_gates_must_pass",
            "outcome_argument_accepted": False,
            "innovation_fit_executed": False,
        },
        "manifest_binding_contract": {
            "execution_addendum_descriptor_required": True,
            "descriptor_fields": [
                "path",
                "sha256",
                "size_bytes",
                "schema",
                "addendum_seal_sha256",
            ],
            "addendum_file_identity_recomputed": True,
            "addendum_seal_recomputed": True,
            "every_frozen_code_identity_recomputed": True,
            "base_rollout_protocol_identity_recomputed": True,
        },
        "forbidden_inputs": [
            "outcome_values",
            "outcome_columns",
            "outcome_manifest",
            "outcome_path",
            "outcome_url",
            "future_target_observations",
            "score_report",
            "candidate_fit_parameters",
        ],
        "frozen_code": {path: _artifact(root, path) for path in CODE_PATHS},
        "claim_boundary": {
            "base_rollout_protocol_modified": False,
            "manning_execution_chain_frozen": True,
            "prospective_manifests_acquired": False,
            "prospective_predictions_executed": False,
            "outcomes_loaded": False,
            "internal_innovation_fitted": False,
            "candidate_promoted": False,
            "runtime_enabled": False,
            "geospatial_kernel_validated": False,
        },
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["addendum_seal"] = {
        "algorithm": "sha256_canonical_json_without_addendum_seal",
        "sha256": hashlib.sha256(canonical).hexdigest(),
    }
    return payload


def _artifact(root: Path, relative_path: str) -> dict[str, object]:
    path = (root / relative_path).resolve()
    try:
        display = path.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError(
            "internal_innovation_execution_addendum_code_outside_repository"
        ) from error
    body = path.read_bytes()
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def main() -> int:
    args = parse_args()
    payload = compile_addendum()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(f"status={payload['status']}")
    print(f"addendum_sha256={payload['addendum_seal']['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
