#!/usr/bin/env python3
"""Commit all V5 Runtime-R4 artifacts before evaluator answer access."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
PREDICTION_ROOT = DRAFT_ROOT / "predictions"
SEAL_PATH = DRAFT_ROOT / "runtime_r4_evaluator_seal.json"
RUNTIME_PATH = DRAFT_ROOT / "runtime_r4_contract.json"
PROTOCOL_PATH = DRAFT_ROOT / "suite_protocol.json"
CONTRACT_PATH = DRAFT_ROOT / "submission_contract.json"
EVALUATOR_PATH = DRAFT_ROOT / "action_transfer_evaluator.py"
CONFORMANCE_PATH = DRAFT_ROOT / "evaluator_conformance_report.json"
DRAFT_MANIFEST_PATH = PREDICTION_ROOT / "prediction_manifest_draft.json"
REPLAY_PATH = PREDICTION_ROOT / "runtime_replay_report.json"
RUNNER_PATH = DRAFT_ROOT / "run_runtime_r4_predictions.py"
MODEL_CORE_PATH = DRAFT_ROOT / "v5_runtime_models.py"
REPLAY_RUNNER_PATH = DRAFT_ROOT / "replay_runtime_r4_predictions.py"
OUTPUT_PATH = PREDICTION_ROOT / "prediction_commitment.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
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


def artifact_ok(row: dict[str, Any]) -> bool:
    path = REPO_ROOT / row["path"]
    return (
        path.is_file()
        and path.stat().st_size == row["bytes"]
        and sha256_file(path) == row["sha256"]
    )


def inventory(root: Path) -> list[dict[str, Any]]:
    return [
        artifact(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    ]


def inventory_digest(rows: list[dict[str, Any]]) -> str:
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    seal = load_json(SEAL_PATH)
    runtime = load_json(RUNTIME_PATH)
    draft = load_json(DRAFT_MANIFEST_PATH)
    replay = load_json(REPLAY_PATH)
    required_ids = [*runtime["required_models"], *runtime["required_controls"]]
    checks = {
        "runtime_seal_allows_predictions_not_early_scoring": seal["status"]
        == "RUNTIME_R4_EVALUATOR_SEALED_PREDICTIONS_PENDING"
        and seal["model_runtime_target_access_permitted"] is False,
        "draft_manifest_is_complete_and_uncommitted": draft["status"]
        == "ALL_REQUIRED_MULTIFOLD_PREDICTIONS_MATERIALIZED_UNCOMMITTED"
        and draft["test_target_rows_loaded"] is False,
        "draft_ids_exactly_match_runtime": set(draft["submissions"])
        == set(required_ids),
        "replay_passed_without_target_access": replay["status"]
        == "PASS_RUNTIME_R4_REPLAY_ALL_PREDICTIONS"
        and replay["test_target_rows_loaded"] is False
        and replay["failed_checks"] == [],
        "runner_matches_draft": artifact_ok(draft["runner"])
        and draft["runner"]["sha256"] == sha256_file(RUNNER_PATH),
        "model_core_matches_draft": artifact_ok(draft["model_core"])
        and draft["model_core"]["sha256"] == sha256_file(MODEL_CORE_PATH),
        "evaluator_matches_pre_prediction_seal": seal["artifacts"]["evaluator"][
            "sha256"
        ]
        == sha256_file(EVALUATOR_PATH)
        and seal["artifacts"]["evaluator_conformance"]["sha256"]
        == sha256_file(CONFORMANCE_PATH),
        "protocol_runtime_and_submission_contract_match_seal": all(
            seal["artifacts"][name]["sha256"] == sha256_file(path)
            for name, path in {
                "protocol": PROTOCOL_PATH,
                "runtime_r4_contract": RUNTIME_PATH,
                "submission_contract": CONTRACT_PATH,
            }.items()
        ),
        "all_aggregate_predictions_and_sidecars_match_draft": all(
            all(
                artifact_ok(entry[name])
                for name in (
                    "prediction_artifact",
                    "model_spec",
                    "nested_selection_receipts",
                    "fold_training_manifests",
                    "runtime_environment",
                    "run_report",
                )
            )
            for entry in draft["submissions"].values()
        ),
        "all_outer_fold_run_reports_deny_target_access": all(
            load_json(path)["test_target_rows_loaded"] is False
            and load_json(path)["model_read_paths_contain_answer_directory"] is False
            for path in sorted((PREDICTION_ROOT / "folds").glob("*/run_report.json"))
        ),
    }
    checks = {key: bool(value) for key, value in checks.items()}
    failed = [key for key, value in checks.items() if not value]
    if failed:
        raise ValueError(f"prediction commitment denied: {failed}")

    submissions: dict[str, Any] = {}
    total_inventory_files = 0
    for model_id in required_ids:
        rows = inventory(PREDICTION_ROOT / model_id)
        total_inventory_files += len(rows)
        submissions[model_id] = {
            "prediction_artifact": draft["submissions"][model_id][
                "prediction_artifact"
            ],
            "sidecars": {
                name: draft["submissions"][model_id][name]
                for name in (
                    "model_spec",
                    "nested_selection_receipts",
                    "fold_training_manifests",
                    "runtime_environment",
                    "run_report",
                )
            },
            "complete_model_inventory": rows,
            "complete_model_inventory_sha256": inventory_digest(rows),
            "complete_model_inventory_file_count": len(rows),
        }

    global_runtime_inventory = inventory(PREDICTION_ROOT / "folds")
    payload = {
        "schema": "gwm_bench.foundation_v5_multifold_prediction_commitment.v1",
        "suite_id": seal["suite_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "MULTIFOLD_PREDICTIONS_COMMITTED_EVALUATOR_ACCESS_PERMITTED",
        "test_target_rows_loaded_before_commitment": False,
        "commitment_boundary": (
            "All 11 aggregate predictions, 27 seed-level multifold predictions, 116 fold "
            "predictions, neural checkpoints, sidecars, nested-selection receipts, runner, model "
            "core, replay report and frozen evaluator are hashed before evaluator answer access."
        ),
        "checks": checks,
        "runtime_seal": artifact(SEAL_PATH),
        "protocol": artifact(PROTOCOL_PATH),
        "runtime_contract": artifact(RUNTIME_PATH),
        "submission_contract": artifact(CONTRACT_PATH),
        "evaluator": artifact(EVALUATOR_PATH),
        "evaluator_conformance": artifact(CONFORMANCE_PATH),
        "runner": artifact(RUNNER_PATH),
        "model_core": artifact(MODEL_CORE_PATH),
        "replay_runner": artifact(REPLAY_RUNNER_PATH),
        "prediction_manifest_draft": artifact(DRAFT_MANIFEST_PATH),
        "runtime_replay_report": artifact(REPLAY_PATH),
        "global_outer_fold_runtime_inventory": global_runtime_inventory,
        "global_outer_fold_runtime_inventory_sha256": inventory_digest(
            global_runtime_inventory
        ),
        "counts": {
            "required_aggregate_submissions": len(required_ids),
            "required_seed_level_multifold_predictions": runtime[
                "stochastic_seed_contract"
            ]["required_seed_level_multifold_predictions"],
            "required_outer_folds": len(runtime["outer_folds"]),
            "committed_model_inventory_files": total_inventory_files,
            "committed_global_fold_runtime_files": len(global_runtime_inventory),
        },
        "submissions": submissions,
        "next_permitted_action": (
            "Run the already-frozen V5 action-transfer evaluator exactly against this "
            "commitment and publish the result regardless of gate outcome."
        ),
    }
    write_json(OUTPUT_PATH, payload)
    print(
        "GWM-Bench Foundation V5.0 commitment: "
        "MULTIFOLD_PREDICTIONS_COMMITTED_EVALUATOR_ACCESS_PERMITTED"
    )
    print(f"Committed model inventory files: {total_inventory_files}")
    print(f"Commitment: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
