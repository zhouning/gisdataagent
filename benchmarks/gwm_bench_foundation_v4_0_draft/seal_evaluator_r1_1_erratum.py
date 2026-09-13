#!/usr/bin/env python3
"""Seal the ACTION-A4 R1.1 key-dtype erratum before formal scoring."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
OUTPUT_PATH = DRAFT_ROOT / "evaluator_r1_1_erratum_seal.json"
ORIGINAL_EVALUATOR_SHA256 = (
    "26cfb70002108a1d145e143b2d4b0b5588223f6ee0ffc2a0ccaca4ac2030f655"
)
ORIGINAL_RUNTIME_SEAL_SHA256 = (
    "93c8a7f3335bf9c4e7338c6490f951119bc6542e5f6a87fb2656aa901674528c"
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
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def main() -> int:
    original = DRAFT_ROOT / "action_a4_evaluator.py"
    runtime_seal = DRAFT_ROOT / "runtime_r3_evaluator_seal.json"
    revision = DRAFT_ROOT / "action_a4_evaluator_r1_1.py"
    conformance_path = DRAFT_ROOT / "evaluator_r1_1_conformance_report.json"
    commitment_path = DRAFT_ROOT / "predictions/prediction_commitment.json"
    targets = DRAFT_ROOT / "rc1_bundle/test_targets/weekly_targets.parquet"
    if sha256_file(original) != ORIGINAL_EVALUATOR_SHA256:
        raise ValueError("original frozen evaluator was modified")
    if sha256_file(runtime_seal) != ORIGINAL_RUNTIME_SEAL_SHA256:
        raise ValueError("original Runtime-R3/evaluator seal was modified")
    conformance = load_json(conformance_path)
    if conformance["status"] != "PASS_ACTION_A4_EVALUATOR_R1_1_CONFORMANCE":
        raise ValueError("R1.1 conformance did not pass")
    if conformance["check_count"] != 16:
        raise ValueError("R1.1 must preserve 15 checks and add one dtype check")
    commitment = load_json(commitment_path)
    if commitment["status"] != "PREDICTIONS_COMMITTED_EVALUATOR_TARGET_ACCESS_PERMITTED":
        raise ValueError("predictions were not committed before evaluator erratum")
    if commitment["test_target_rows_loaded_before_commitment"] is not False:
        raise ValueError("target firewall was not preserved before prediction commitment")

    report = {
        "schema": "gwm_bench.foundation_v4_evaluator_r1_1_erratum_seal.v1",
        "suite_id": commitment["suite_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "EVALUATOR_R1_1_ERRATUM_SEALED_SCORING_PERMITTED",
        "r1_failed_attempt": {
            "result_file_created": False,
            "exception": "SubmissionError: missing or extra submission keys",
            "root_cause": (
                "R1 used pandas.DataFrame.equals, which treats int16 and int64 "
                "storage widths as unequal even when all key values are identical."
            ),
            "expected_key_rows": 3156,
            "submission_key_rows": 3156,
            "duplicate_submission_keys": 0,
            "all_key_values_equal_after_int64_normalization": True,
            "frozen_key_dtypes": {"zone_id": "int64", "horizon_week": "int16"},
            "submission_key_dtypes": {"zone_id": "int16", "horizon_week": "int64"},
            "note": (
                "The evaluator process opened the target Parquet before validation, "
                "but every prediction had already been hashed in the commitment manifest."
            ),
        },
        "erratum_scope": {
            "changed": [
                "Normalize zone_id and horizon_week integral values to int64 before R1 validation."
            ],
            "unchanged": [
                "prediction artifacts and hashes",
                "test targets",
                "metric equations and reported horizons",
                "paired bootstrap draws and seed",
                "action-transfer gate conditions",
                "claim boundary",
            ],
        },
        "artifacts": {
            "original_runtime_seal": artifact(runtime_seal),
            "original_evaluator_r1": artifact(original),
            "evaluator_r1_1": artifact(revision),
            "r1_1_conformance": artifact(conformance_path),
            "prediction_commitment": artifact(commitment_path),
            "test_targets": artifact(targets),
        },
        "next_permitted_action": (
            "Score the committed predictions exactly once with evaluator R1.1 and publish the result."
        ),
    }
    OUTPUT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("GWM-Bench Foundation V4.0 evaluator erratum: " + report["status"])
    print(f"Erratum seal: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
