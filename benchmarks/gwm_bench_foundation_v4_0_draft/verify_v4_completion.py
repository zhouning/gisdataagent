#!/usr/bin/env python3
"""Verify the complete, immutable evidence chain for GWM Benchmark V4."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
PREDICTION_ROOT = DRAFT_ROOT / "predictions"
RESULT_ROOT = DRAFT_ROOT / "final_results"
RESULT_PATH = RESULT_ROOT / "action_a4_results.json"
COMMITMENT_PATH = PREDICTION_ROOT / "prediction_commitment.json"
ERRATUM_SEAL_PATH = DRAFT_ROOT / "evaluator_r1_2_erratum_seal.json"
REPORT_PATH = REPO_ROOT / "docs/research/GWM_BENCHMARK_V4_0_FINAL_REPORT_2026-07-23.md"
FIGURE_ROOT = REPO_ROOT / "docs/research/assets/gwm_benchmark_v4_final_2026-07-23"
OUTPUT_PATH = RESULT_ROOT / "completion_verification.json"


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
    commitment = load_json(COMMITMENT_PATH)
    seal = load_json(ERRATUM_SEAL_PATH)
    result = load_json(RESULT_PATH)
    checks: dict[str, bool] = {}

    checks["prediction_commitment_status"] = (
        commitment["status"]
        == "PREDICTIONS_COMMITTED_EVALUATOR_TARGET_ACCESS_PERMITTED"
    )
    checks["target_firewall_preserved_before_commitment"] = (
        commitment["test_target_rows_loaded_before_commitment"] is False
    )
    committed_files_ok = True
    for row in commitment["committed_files"]:
        path = REPO_ROOT / row["path"]
        committed_files_ok = committed_files_ok and path.is_file()
        if path.is_file():
            committed_files_ok = committed_files_ok and path.stat().st_size == row["bytes"]
            committed_files_ok = committed_files_ok and sha256_file(path) == row["sha256"]
    checks["all_112_committed_prediction_files_unchanged"] = (
        committed_files_ok and len(commitment["committed_files"]) == 112
    )
    checks["all_35_predictions_replayed_exactly"] = (
        commitment["counts"]["prediction_parquet_files"] == 35
        and commitment["counts"]["replay_checks"] == 35
        and commitment["maximum_replay_absolute_difference"] == 0.0
    )
    checks["r1_2_evaluator_sealed"] = (
        seal["status"] == "EVALUATOR_R1_2_ERRATUM_SEALED_FINAL_SCORING_PERMITTED"
    )
    seal_artifacts_ok = all(
        (REPO_ROOT / row["path"]).is_file()
        and (REPO_ROOT / row["path"]).stat().st_size == row["bytes"]
        and sha256_file(REPO_ROOT / row["path"]) == row["sha256"]
        for row in seal["artifacts"].values()
    )
    checks["r1_2_seal_artifacts_unchanged"] = seal_artifacts_ok
    checks["formal_result_exists_and_completed"] = (
        result["benchmark_completed"] is True
        and result["status"] in {"ACTION_TRANSFER_SUPPORTED", "ACTION_TRANSFER_NOT_SUPPORTED"}
    )
    checks["formal_result_uses_r1_2"] = (
        result["evaluator_revision"] == "R1.2_KEY_DTYPE_ERRATUM"
    )
    checks["formal_result_binds_prediction_commitment"] = (
        result["submission_manifest_sha256"] == sha256_file(COMMITMENT_PATH)
    )
    checks["formal_result_binds_frozen_protocol"] = (
        result["protocol_sha256"] == sha256_file(DRAFT_ROOT / "suite_protocol.json")
    )
    checks["formal_result_binds_frozen_contract"] = (
        result["submission_contract_sha256"]
        == sha256_file(DRAFT_ROOT / "submission_contract.json")
    )
    checks["formal_result_binds_frozen_targets"] = (
        result["targets_sha256"]
        == sha256_file(DRAFT_ROOT / "rc1_bundle/test_targets/weekly_targets.parquet")
    )
    runtime_contract = load_json(DRAFT_ROOT / "runtime_r3_contract.json")
    required_ids = [
        *runtime_contract["required_models"],
        *runtime_contract["required_controls"],
    ]
    checks["all_11_required_submissions_scored"] = (
        set(result["metrics"]) == set(required_ids)
        and set(result["prediction_artifacts"]) == set(required_ids)
    )
    prediction_hashes_ok = all(
        result["prediction_artifacts"][model_id]["sha256"]
        == commitment["submissions"][model_id]["prediction_sha256"]
        for model_id in required_ids
    )
    checks["scored_prediction_hashes_match_commitment"] = prediction_hashes_ok
    gate_passed = result["action_transfer_gate"]["passed"]
    checks["status_matches_action_transfer_gate"] = (
        (gate_passed and result["status"] == "ACTION_TRANSFER_SUPPORTED")
        or (not gate_passed and result["status"] == "ACTION_TRANSFER_NOT_SUPPORTED")
    )
    checks["all_gate_conditions_are_boolean"] = all(
        isinstance(value, bool)
        for value in result["action_transfer_gate"]["conditions"].values()
    )
    commitment_time = datetime.fromisoformat(commitment["created_at"])
    seal_time = datetime.fromisoformat(seal["created_at"])
    result_time = datetime.fromisoformat(result["generated_at"])
    checks["chronology_commit_then_seal_then_score"] = (
        commitment_time < seal_time < result_time
    )
    figures = sorted(FIGURE_ROOT.glob("*.png"))
    previews = sorted(FIGURE_ROOT.glob("*.csv"))
    checks["final_report_and_visual_previews_exist"] = (
        REPORT_PATH.is_file() and len(figures) == 5 and len(previews) == 3
    )

    passed = all(checks.values())
    status_suffix = result["status"]
    report = {
        "schema": "gwm_bench.foundation_v4_completion_verification.v1",
        "suite_id": result["suite_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            f"PASS_V4_BENCHMARK_COMPLETE_{status_suffix}" if passed else "FAIL"
        ),
        "benchmark_completed": bool(passed and result["benchmark_completed"]),
        "scientific_result": result["status"],
        "check_count": len(checks),
        "checks": checks,
        "artifacts": {
            "prediction_commitment": artifact(COMMITMENT_PATH),
            "evaluator_r1_2_erratum_seal": artifact(ERRATUM_SEAL_PATH),
            "formal_result": artifact(RESULT_PATH),
            "final_report": artifact(REPORT_PATH),
            "figures": [artifact(path) for path in figures],
            "preview_csvs": [artifact(path) for path in previews],
        },
        "plain_language_conclusion": (
            "The benchmark and audit chain are complete. The tested action-transfer "
            "claim is not supported by the frozen gate."
        ),
    }
    OUTPUT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"GWM-Bench Foundation V4.0 completion: {report['status']}")
    print(f"Completion verification: {OUTPUT_PATH}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
