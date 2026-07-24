#!/usr/bin/env python3
"""Verify V5 benchmark completion independently of action-transfer gate outcome."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
PREDICTION_ROOT = DRAFT_ROOT / "predictions"
FINAL_ROOT = DRAFT_ROOT / "final_results"
PROTOCOL_PATH = DRAFT_ROOT / "suite_protocol.json"
DATA_VERIFICATION_PATH = DRAFT_ROOT / "rc1_bundle/bundle_verification.json"
SEAL_PATH = DRAFT_ROOT / "runtime_r4_evaluator_seal.json"
REPLAY_PATH = PREDICTION_ROOT / "runtime_replay_report.json"
COMMITMENT_PATH = PREDICTION_ROOT / "prediction_commitment.json"
EVALUATOR_PATH = DRAFT_ROOT / "action_transfer_evaluator.py"
RESULT_PATH = FINAL_ROOT / "action_transfer_results.json"
OUTPUT_PATH = FINAL_ROOT / "completion_verification.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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
    protocol = load_json(PROTOCOL_PATH)
    data_verification = load_json(DATA_VERIFICATION_PATH)
    seal = load_json(SEAL_PATH)
    replay = load_json(REPLAY_PATH)
    commitment = load_json(COMMITMENT_PATH)
    result = load_json(RESULT_PATH)
    required_ids = [*protocol["required_models"], *protocol["required_controls"]]
    conditions = result["action_transfer_gate"]["conditions"]
    checks = {
        "rc1_data_verified": data_verification["status"]
        == "PASS_V5_RC1_DATA_VERIFIED"
        and data_verification["failed_check_count"] == 0,
        "runtime_and_evaluator_sealed_before_predictions": seal["status"]
        == "RUNTIME_R4_EVALUATOR_SEALED_PREDICTIONS_PENDING",
        "all_predictions_replayed_without_target_access": replay["status"]
        == "PASS_RUNTIME_R4_REPLAY_ALL_PREDICTIONS"
        and replay["test_target_rows_loaded"] is False,
        "prediction_commitment_completed_before_evaluator_access": commitment["status"]
        == "MULTIFOLD_PREDICTIONS_COMMITTED_EVALUATOR_ACCESS_PERMITTED"
        and commitment["test_target_rows_loaded_before_commitment"] is False,
        "frozen_evaluator_hash_matches_commitment": commitment["evaluator"]["sha256"]
        == sha256_file(EVALUATOR_PATH),
        "formal_result_binds_prediction_commitment": result[
            "prediction_commitment_sha256"
        ]
        == sha256_file(COMMITMENT_PATH),
        "formal_result_binds_protocol_runtime_and_submission_contracts": result[
            "protocol_sha256"
        ]
        == commitment["protocol"]["sha256"]
        and result["runtime_r4_contract_sha256"]
        == commitment["runtime_contract"]["sha256"]
        and result["submission_contract_sha256"]
        == commitment["submission_contract"]["sha256"],
        "all_eleven_required_submissions_scored": set(result["metrics"])
        == set(required_ids)
        and set(result["prediction_artifacts"]) == set(required_ids),
        "scored_prediction_hashes_match_commitment": all(
            result["prediction_artifacts"][model_id]["sha256"]
            == commitment["submissions"][model_id]["prediction_artifact"]["sha256"]
            for model_id in required_ids
        ),
        "all_eight_frozen_gate_conditions_reported": len(conditions) == 8
        and set(conditions)
        == {
            "mean_fold_skill_at_least_one_percent",
            "paired_bootstrap_interval_entirely_below_zero",
            "at_least_three_of_four_events_improve",
            "no_fold_degrades_more_than_two_percent",
            "at_least_twelve_of_sixteen_event_target_pairs_improve",
            "at_least_four_of_five_reported_horizons_improve",
            "correct_action_beats_every_frozen_control_equal_event",
            "correct_action_beats_every_control_in_three_of_four_folds",
        },
        "formal_evaluator_completed_regardless_of_gate": result[
            "benchmark_completed"
        ]
        is True
        and protocol["completion_definition"]["model_win_required"] is False,
        "result_status_matches_gate": (
            result["status"] == "ACTION_TRANSFER_SUPPORTED"
        )
        == result["action_transfer_gate"]["passed"],
        "failure_result_is_explicitly_published": result["status"]
        == "ACTION_TRANSFER_NOT_SUPPORTED"
        and result["action_transfer_gate"]["passed"] is False
        and any(value is False for value in conditions.values()),
        "claim_boundary_preserved": result["claim_boundary"]
        == protocol["claim_boundary"],
        "chronology_commitment_precedes_formal_result": commitment["created_at"]
        < result["generated_at"],
    }
    checks = {key: bool(value) for key, value in checks.items()}
    passed = all(checks.values())
    final_status = (
        "PASS_V5_BENCHMARK_COMPLETE_ACTION_TRANSFER_SUPPORTED"
        if result["action_transfer_gate"]["passed"]
        else "PASS_V5_BENCHMARK_COMPLETE_ACTION_TRANSFER_NOT_SUPPORTED"
    )
    artifacts = {
        "protocol": artifact(PROTOCOL_PATH),
        "data_verification": artifact(DATA_VERIFICATION_PATH),
        "runtime_evaluator_seal": artifact(SEAL_PATH),
        "runtime_replay": artifact(REPLAY_PATH),
        "prediction_commitment": artifact(COMMITMENT_PATH),
        "frozen_evaluator": artifact(EVALUATOR_PATH),
        "formal_result": artifact(RESULT_PATH),
    }
    generated_at = datetime.now(timezone.utc).isoformat()
    if OUTPUT_PATH.is_file():
        existing = load_json(OUTPUT_PATH)
        unchanged = (
            existing.get("status") == (final_status if passed else "FAIL_V5_COMPLETION_VERIFICATION")
            and existing.get("checks") == checks
            and existing.get("artifacts") == artifacts
            and existing.get("action_transfer_gate") == result["action_transfer_gate"]
        )
        if unchanged and existing.get("generated_at"):
            generated_at = existing["generated_at"]

    report = {
        "schema": "gwm_bench.foundation_v5_completion_verification.v1",
        "suite_id": protocol["suite_id"],
        "generated_at": generated_at,
        "status": final_status if passed else "FAIL_V5_COMPLETION_VERIFICATION",
        "benchmark_complete": passed,
        "action_transfer_supported": result["action_transfer_gate"]["passed"],
        "check_count": len(checks),
        "passed_check_count": sum(checks.values()),
        "failed_checks": [key for key, value in checks.items() if not value],
        "checks": checks,
        "artifacts": artifacts,
        "action_transfer_gate": result["action_transfer_gate"],
        "next_permitted_action": (
            "Publish the complete V5 result, figures, data previews and failure analysis."
            if passed
            else "Fix completion-evidence failures without changing the scored result."
        ),
    }
    write_json(OUTPUT_PATH, report)
    print(f"GWM-Bench Foundation V5.0 completion: {report['status']}")
    print(f"Checks: {report['passed_check_count']}/{report['check_count']}")
    print(f"Verification: {OUTPUT_PATH}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
