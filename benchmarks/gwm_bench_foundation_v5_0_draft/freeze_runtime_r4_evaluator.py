#!/usr/bin/env python3
"""Seal V5 Runtime-R4, multi-fold submission contract and evaluator."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
OUTPUT_PATH = DRAFT_ROOT / "runtime_r4_evaluator_seal.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def main() -> int:
    paths = {
        "protocol": DRAFT_ROOT / "suite_protocol.json",
        "preflight": DRAFT_ROOT / "preflight_report.json",
        "bundle_manifest": DRAFT_ROOT / "rc1_bundle/bundle_manifest.json",
        "bundle_verification": DRAFT_ROOT / "rc1_bundle/bundle_verification.json",
        "runtime_r4_contract": DRAFT_ROOT / "runtime_r4_contract.json",
        "submission_contract": DRAFT_ROOT / "submission_contract.json",
        "evaluator": DRAFT_ROOT / "action_transfer_evaluator.py",
        "evaluator_conformance": DRAFT_ROOT / "evaluator_conformance_report.json",
        "evaluator_conformance_runner": DRAFT_ROOT / "run_evaluator_conformance.py",
    }
    runtime = load_json(paths["runtime_r4_contract"])
    firewall = runtime["contracts"]["OuterFoldFirewall"]
    for fold in runtime["outer_folds"]:
        fold_id = fold["fold_id"]
        root = REPO_ROOT / fold["fold_root"]
        paths[f"{fold_id}_development"] = root / firewall["development_relative_path"]
        paths[f"{fold_id}_history"] = root / firewall["history_relative_path"]
        paths[f"{fold_id}_action"] = root / firewall["action_relative_path"]
        paths[f"{fold_id}_keys"] = root / firewall["submission_keys_relative_path"]
        paths[f"{fold_id}_graph"] = root / firewall["test_graph_relative_path"]
        paths[f"{fold_id}_targets"] = root / firewall["targets_relative_path"]
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing seal inputs: {missing}")

    protocol = load_json(paths["protocol"])
    preflight = load_json(paths["preflight"])
    bundle_manifest = load_json(paths["bundle_manifest"])
    bundle_verification = load_json(paths["bundle_verification"])
    submission = load_json(paths["submission_contract"])
    conformance = load_json(paths["evaluator_conformance"])
    protocol_hash = sha256_file(paths["protocol"])
    protocol_folds = {
        fold["fold_id"]: {
            "test_event": fold["test_event"],
            "training_events": fold["training_events"],
        }
        for fold in protocol["outer_folds"]
    }
    runtime_folds = {
        fold["fold_id"]: {
            "test_event": fold["test_event"],
            "training_events": fold["training_events"],
        }
        for fold in runtime["outer_folds"]
    }
    checks = {
        "protocol_is_v5": protocol["schema"]
        == "gwm_bench.foundation_v5_suite_protocol.v1",
        "preflight_passed_and_bound": preflight["status"]
        == "PASS_V5_DRAFT_READY_FOR_RC1"
        and preflight["protocol_sha256"] == protocol_hash,
        "bundle_materialized_and_bound": bundle_manifest["status"]
        == "V5_RC1_DATA_MATERIALIZED"
        and bundle_manifest["protocol_sha256"] == protocol_hash,
        "bundle_verification_passed_and_bound": bundle_verification["status"]
        == "PASS_V5_RC1_DATA_VERIFIED"
        and bundle_verification["protocol_sha256"] == protocol_hash
        and bundle_verification["failed_check_count"] == 0,
        "runtime_contract_is_frozen": runtime["status"] == "frozen_before_predictions",
        "submission_contract_is_frozen": submission["status"]
        == "frozen_before_predictions",
        "suite_ids_match": runtime["suite_id"]
        == submission["suite_id"]
        == protocol["suite_id"],
        "runtime_folds_exactly_match_protocol": runtime_folds == protocol_folds,
        "runtime_models_exactly_match_protocol": runtime["required_models"]
        == protocol["required_models"],
        "runtime_controls_exactly_match_protocol": runtime["required_controls"]
        == protocol["required_controls"],
        "runtime_seeds_exactly_match_protocol": runtime["stochastic_seed_contract"][
            "required_seeds"
        ]
        == protocol["model_contract"]["required_seeds"],
        "submission_has_exact_four_fold_key_contract": submission["key_columns"]
        == ["fold_id", "zone_id", "horizon_week"]
        and submission["expected_fold_ids"]
        == [fold["fold_id"] for fold in protocol["outer_folds"]]
        and submission["expected_key_count"]
        == protocol["split_contract"]["expected_total_outer_test_keys"],
        "evaluator_conformance_passed": conformance["status"]
        == "PASS_V5_ACTION_TRANSFER_EVALUATOR_CONFORMANCE"
        and conformance["failed_checks"] == [],
        "runtime_denies_current_fold_targets": "current_fold/test_targets"
        in runtime["read_routes"]["model_runtime_denied_per_current_fold"],
        "runtime_forbids_observed_writeback": runtime["contracts"][
            "ActionResidualRolloutRequest"
        ]["observed_test_state_writeback_permitted"]
        is False,
        "runtime_forbids_post_action_graph_update": runtime["contracts"][
            "OuterFoldFirewall"
        ]["heldout_post_action_graph_update_permitted"]
        is False,
        "evaluator_waits_for_complete_commitment": runtime["contracts"][
            "MultiFoldPredictionCommitment"
        ]["all_models_controls_seeds_and_folds_required_before_target_access"]
        is True,
        "completion_does_not_require_model_win": protocol["completion_definition"][
            "model_win_required"
        ]
        is False
        and protocol["action_transfer_gate"]["completion_independent_of_gate"] is True,
        "claim_boundary_rejects_blind_causal_and_external_claims": "causal effects of any taxi fee or congestion-pricing policy"
        in protocol["claim_boundary"]["does_not_support"]
        and "analyst-unseen or externally hidden labels"
        in protocol["claim_boundary"]["does_not_support"]
        and "generalization beyond NYC yellow taxis or beyond the four admitted actions"
        in protocol["claim_boundary"]["does_not_support"],
    }
    checks = {key: bool(value) for key, value in checks.items()}
    failed = [key for key, value in checks.items() if not value]
    if failed:
        raise ValueError(f"cannot seal Runtime-R4: failed checks {failed}")

    seal = {
        "schema": "gwm_bench.foundation_v5_runtime_r4_evaluator_seal.v1",
        "suite_id": protocol["suite_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "RUNTIME_R4_EVALUATOR_SEALED_PREDICTIONS_PENDING",
        "check_count": len(checks),
        "checks": checks,
        "artifacts": {name: artifact(path) for name, path in paths.items()},
        "model_runtime_target_access_permitted": False,
        "formal_evaluator_target_access_permitted_after_complete_commitment": True,
        "required_model_ids": runtime["required_models"],
        "required_control_ids": runtime["required_controls"],
        "required_seeds": runtime["stochastic_seed_contract"]["required_seeds"],
        "required_outer_folds": [fold["fold_id"] for fold in runtime["outer_folds"]],
        "expected_aggregate_submission_count": len(runtime["required_models"])
        + len(runtime["required_controls"]),
        "expected_seed_level_multifold_prediction_count": runtime[
            "stochastic_seed_contract"
        ]["required_seed_level_multifold_predictions"],
        "next_permitted_action": (
            "Implement the frozen Runtime-R4 runner, then run and replay all required models, "
            "controls, seeds and folds without opening any current-fold test target."
        ),
    }
    OUTPUT_PATH.write_text(
        json.dumps(seal, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("GWM-Bench Foundation V5.0: RUNTIME_R4_EVALUATOR_SEALED_PREDICTIONS_PENDING")
    print(f"Checks: {len(checks)}/{len(checks)}")
    print(f"Seal: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
