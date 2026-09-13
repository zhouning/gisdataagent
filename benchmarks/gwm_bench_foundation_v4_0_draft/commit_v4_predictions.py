#!/usr/bin/env python3
"""Seal V4 predictions before the frozen evaluator may read test targets."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
PREDICTION_ROOT = DRAFT_ROOT / "predictions"
RUNTIME_SEAL_PATH = DRAFT_ROOT / "runtime_r3_evaluator_seal.json"
RUNTIME_CONTRACT_PATH = DRAFT_ROOT / "runtime_r3_contract.json"
SUBMISSION_CONTRACT_PATH = DRAFT_ROOT / "submission_contract.json"
DRAFT_MANIFEST_PATH = PREDICTION_ROOT / "prediction_manifest_draft.json"
REPLAY_REPORT_PATH = PREDICTION_ROOT / "runtime_replay_report.json"
OUTPUT_PATH = PREDICTION_ROOT / "prediction_commitment.json"

EXPECTED_SEAL_SHA256 = (
    "93c8a7f3335bf9c4e7338c6490f951119bc6542e5f6a87fb2656aa901674528c"
)
EXPECTED_EVALUATOR_SHA256 = (
    "26cfb70002108a1d145e143b2d4b0b5588223f6ee0ffc2a0ccaca4ac2030f655"
)
CODE_PATHS = (
    DRAFT_ROOT / "run_v4_predictions.py",
    DRAFT_ROOT / "v4_weekly_models.py",
    DRAFT_ROOT / "replay_v4_predictions.py",
    DRAFT_ROOT / "action_a4_evaluator.py",
)
REQUIRED_SIDECARS = (
    "model_spec.json",
    "training_row_manifest.json",
    "runtime_environment.json",
    "run_report.json",
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"required artifact is missing: {path}")
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def main() -> int:
    seal = load_json(RUNTIME_SEAL_PATH)
    contract = load_json(RUNTIME_CONTRACT_PATH)
    submission_contract = load_json(SUBMISSION_CONTRACT_PATH)
    draft_manifest = load_json(DRAFT_MANIFEST_PATH)
    replay = load_json(REPLAY_REPORT_PATH)

    if sha256_file(RUNTIME_SEAL_PATH) != EXPECTED_SEAL_SHA256:
        raise ValueError("Runtime-R3/evaluator seal changed after freezing")
    evaluator_path = DRAFT_ROOT / "action_a4_evaluator.py"
    if sha256_file(evaluator_path) != EXPECTED_EVALUATOR_SHA256:
        raise ValueError("frozen evaluator changed after sealing")
    if seal["status"] != "RUNTIME_R3_EVALUATOR_SEALED_PREDICTIONS_PENDING":
        raise ValueError("unexpected Runtime-R3 seal state")
    if contract["status"] != "frozen_before_predictions":
        raise ValueError("Runtime-R3 contract is not frozen")
    if submission_contract["status"] != "frozen_before_predictions":
        raise ValueError("submission contract is not frozen")
    if draft_manifest["status"] != "ALL_REQUIRED_PREDICTIONS_MATERIALIZED_UNCOMMITTED":
        raise ValueError("prediction draft manifest is not ready for commitment")
    if draft_manifest["test_target_rows_loaded"] is not False:
        raise ValueError("prediction generation did not preserve the target firewall")
    if replay["status"] != "PASS_RUNTIME_R3_ALL_PREDICTIONS_REPLAYED":
        raise ValueError("Runtime-R3 replay has not passed")
    if replay["test_target_rows_loaded"] is not False:
        raise ValueError("prediction replay did not preserve the target firewall")
    if replay["check_count"] != 35:
        raise ValueError("expected exactly 35 replay checks")

    required_ids = [*contract["required_models"], *contract["required_controls"]]
    if set(draft_manifest["submissions"]) != set(required_ids):
        raise ValueError("draft manifest IDs differ from the frozen Runtime-R3 contract")

    submissions: dict[str, Any] = {}
    for model_id in required_ids:
        entry = draft_manifest["submissions"][model_id]
        prediction_path = REPO_ROOT / entry["prediction_path"]
        prediction_artifact = artifact(prediction_path)
        if prediction_artifact["sha256"] != entry["prediction_sha256"]:
            raise ValueError(f"prediction hash changed for {model_id}")
        sidecars: dict[str, Any] = {}
        model_root = prediction_path.parent
        for name in REQUIRED_SIDECARS:
            sidecar_path = model_root / name
            sidecars[name] = artifact(sidecar_path)
            sidecar = load_json(sidecar_path)
            if sidecar.get("test_target_rows_loaded") is True:
                raise ValueError(f"target firewall violation recorded by {sidecar_path}")
            if sidecar.get("model_process_target_access_permitted") is True:
                raise ValueError(f"target access was permitted in {sidecar_path}")
        submissions[model_id] = {
            "prediction_path": entry["prediction_path"],
            "prediction_sha256": prediction_artifact["sha256"],
            "prediction_bytes": prediction_artifact["bytes"],
            "sidecars": sidecars,
        }

    excluded = {OUTPUT_PATH.resolve()}
    committed_files = [
        artifact(path)
        for path in sorted(PREDICTION_ROOT.rglob("*"))
        if path.is_file() and path.resolve() not in excluded
    ]
    prediction_files = [row for row in committed_files if row["path"].endswith("prediction.parquet")]
    checkpoint_files = [row for row in committed_files if row["path"].endswith("model.pt")]
    if len(prediction_files) != 35:
        raise ValueError(f"expected 35 prediction Parquet files, found {len(prediction_files)}")
    if len(checkpoint_files) != 6:
        raise ValueError(f"expected 6 stochastic model checkpoints, found {len(checkpoint_files)}")

    payload = {
        "schema": "gwm_bench.foundation_v4_prediction_commitment.v1",
        "suite_id": contract["suite_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "PREDICTIONS_COMMITTED_EVALUATOR_TARGET_ACCESS_PERMITTED",
        "test_target_rows_loaded_before_commitment": False,
        "commitment_boundary": (
            "Every required prediction, stochastic checkpoint, sidecar, runtime environment, "
            "selection record, replay report, runner, model core, and frozen evaluator is hashed."
        ),
        "runtime_seal": artifact(RUNTIME_SEAL_PATH),
        "runtime_contract": artifact(RUNTIME_CONTRACT_PATH),
        "submission_contract": artifact(SUBMISSION_CONTRACT_PATH),
        "draft_manifest": artifact(DRAFT_MANIFEST_PATH),
        "runtime_replay": artifact(REPLAY_REPORT_PATH),
        "code_artifacts": [artifact(path) for path in CODE_PATHS],
        "counts": {
            "required_submission_ids": len(required_ids),
            "committed_files_under_predictions": len(committed_files),
            "prediction_parquet_files": len(prediction_files),
            "stochastic_model_checkpoints": len(checkpoint_files),
            "replay_checks": replay["check_count"],
        },
        "maximum_replay_absolute_difference": replay[
            "maximum_observed_absolute_difference"
        ],
        "submissions": submissions,
        "committed_files": committed_files,
        "next_permitted_action": (
            "Run the already-frozen ACTION-A4 evaluator against this commitment manifest."
        ),
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("GWM-Bench Foundation V4.0 commitment: " + payload["status"])
    print(f"Committed prediction files: {len(prediction_files)}")
    print(f"Commitment manifest: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
