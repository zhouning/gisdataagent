#!/usr/bin/env python3
"""Seal V4 Runtime-R3, submission contract and evaluator before predictions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
OUTPUT_PATH = DRAFT_ROOT / "runtime_r3_evaluator_seal.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def main() -> int:
    paths = {
        "protocol": DRAFT_ROOT / "suite_protocol.json",
        "preflight": DRAFT_ROOT / "preflight_report.json",
        "bundle_manifest": DRAFT_ROOT / "rc1_bundle/bundle_manifest.json",
        "bundle_verification": DRAFT_ROOT / "rc1_bundle/bundle_verification.json",
        "runtime_r3_contract": DRAFT_ROOT / "runtime_r3_contract.json",
        "submission_contract": DRAFT_ROOT / "submission_contract.json",
        "evaluator": DRAFT_ROOT / "action_a4_evaluator.py",
        "evaluator_conformance": DRAFT_ROOT / "evaluator_conformance_report.json",
        "test_history": DRAFT_ROOT / "rc1_bundle/test_input/weekly_state_history.parquet",
        "future_action_spec": DRAFT_ROOT / "rc1_bundle/test_input/future_action_spec.parquet",
        "submission_keys": DRAFT_ROOT / "rc1_bundle/test_input/submission_keys.parquet",
        "spatial_edges": DRAFT_ROOT / "rc1_bundle/graph/spatial_edges.parquet",
        "test_targets": DRAFT_ROOT / "rc1_bundle/test_targets/weekly_targets.parquet",
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing seal inputs: {missing}")

    protocol = _load_json(paths["protocol"])
    preflight = _load_json(paths["preflight"])
    bundle_manifest = _load_json(paths["bundle_manifest"])
    bundle_verification = _load_json(paths["bundle_verification"])
    runtime_contract = _load_json(paths["runtime_r3_contract"])
    submission_contract = _load_json(paths["submission_contract"])
    conformance = _load_json(paths["evaluator_conformance"])
    protocol_hash = _sha256(paths["protocol"])
    checks = {
        "protocol_is_v4_draft": protocol["schema"]
        == "gwm_bench.foundation_v4_draft_protocol.v1",
        "preflight_passed": preflight["status"]
        == "PASS_READY_TO_MATERIALIZE_WEEKLY_BUNDLE"
        and preflight["protocol_sha256"] == protocol_hash,
        "bundle_is_materialized_against_protocol": bundle_manifest["status"]
        == "V4_RC1_DATA_MATERIALIZED"
        and bundle_manifest["protocol_sha256"] == protocol_hash,
        "bundle_verification_passed": bundle_verification["status"]
        == "PASS_V4_RC1_DATA_VERIFIED"
        and bundle_verification["protocol_sha256"] == protocol_hash,
        "runtime_contract_is_frozen": runtime_contract["status"]
        == "frozen_before_predictions",
        "submission_contract_is_frozen": submission_contract["status"]
        == "frozen_before_predictions",
        "evaluator_conformance_passed": conformance["status"]
        == "PASS_ACTION_A4_EVALUATOR_CONFORMANCE",
        "runtime_denies_test_targets": "rc1_bundle/test_targets"
        in runtime_contract["read_routes"]["model_runtime_denied"],
        "runtime_forbids_observed_writeback": runtime_contract["contracts"][
            "OpenLoopRolloutRequest"
        ]["observed_state_writeback_permitted"]
        is False,
        "completion_does_not_require_model_win": protocol["evaluation"][
            "benchmark_completion_requires_model_win"
        ]
        is False,
        "claim_boundary_rejects_causal_and_blind_claims": "causal effect of congestion pricing"
        in protocol["claim_boundary"]["does_not_support"]
        and "analyst-unseen or externally hidden-label evaluation"
        in protocol["claim_boundary"]["does_not_support"],
    }
    checks = {key: bool(value) for key, value in checks.items()}
    if not all(checks.values()):
        raise ValueError(f"cannot seal: failed checks {checks}")

    seal = {
        "schema": "gwm_bench.foundation_v4_runtime_r3_evaluator_seal.v1",
        "suite_id": protocol["suite_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "RUNTIME_R3_EVALUATOR_SEALED_PREDICTIONS_PENDING",
        "checks": checks,
        "artifacts": {name: _artifact(path) for name, path in paths.items()},
        "model_runtime_target_access_permitted": False,
        "formal_evaluator_target_access_permitted_after_all_prediction_commitments": True,
        "required_model_ids": runtime_contract["required_models"],
        "required_control_ids": runtime_contract["required_controls"],
        "required_seeds": runtime_contract["stochastic_seed_contract"]["required_seeds"],
        "next_permitted_action": "Run and commit all required model and control predictions without opening rc1_bundle/test_targets from any model process.",
    }
    OUTPUT_PATH.write_text(
        json.dumps(seal, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("GWM-Bench Foundation V4.0: RUNTIME_R3_EVALUATOR_SEALED_PREDICTIONS_PENDING")
    print(f"Seal: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
