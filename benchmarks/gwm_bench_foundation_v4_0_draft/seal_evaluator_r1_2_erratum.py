#!/usr/bin/env python3
"""Seal ACTION-A4 evaluator R1.2 before the final scoring run."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
OUTPUT_PATH = DRAFT_ROOT / "evaluator_r1_2_erratum_seal.json"
ORIGINAL_EVALUATOR_SHA256 = "26cfb70002108a1d145e143b2d4b0b5588223f6ee0ffc2a0ccaca4ac2030f655"
ORIGINAL_RUNTIME_SEAL_SHA256 = "93c8a7f3335bf9c4e7338c6490f951119bc6542e5f6a87fb2656aa901674528c"
FAILED_R1_1_SHA256 = "355f1ce5d1eae2d2a233e404793d5ba37c30d375af676ca4eb2d5c48c7217f2e"


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
    failed_r1_1 = DRAFT_ROOT / "action_a4_evaluator_r1_1.py"
    revision = DRAFT_ROOT / "action_a4_evaluator_r1_2.py"
    conformance_path = DRAFT_ROOT / "evaluator_r1_2_conformance_report.json"
    commitment_path = DRAFT_ROOT / "predictions/prediction_commitment.json"
    prior_erratum = DRAFT_ROOT / "evaluator_r1_1_erratum_seal.json"
    targets = DRAFT_ROOT / "rc1_bundle/test_targets/weekly_targets.parquet"
    if sha256_file(original) != ORIGINAL_EVALUATOR_SHA256:
        raise ValueError("original frozen evaluator was modified")
    if sha256_file(runtime_seal) != ORIGINAL_RUNTIME_SEAL_SHA256:
        raise ValueError("original Runtime-R3/evaluator seal was modified")
    if sha256_file(failed_r1_1) != FAILED_R1_1_SHA256:
        raise ValueError("failed R1.1 evaluator record was modified")
    conformance = load_json(conformance_path)
    if conformance["status"] != "PASS_ACTION_A4_EVALUATOR_R1_2_CONFORMANCE":
        raise ValueError("R1.2 conformance did not pass")
    if conformance["check_count"] != 17:
        raise ValueError("R1.2 requires 17 conformance checks")
    commitment = load_json(commitment_path)
    if commitment["status"] != "PREDICTIONS_COMMITTED_EVALUATOR_TARGET_ACCESS_PERMITTED":
        raise ValueError("predictions are not committed")

    report = {
        "schema": "gwm_bench.foundation_v4_evaluator_r1_2_erratum_seal.v1",
        "suite_id": commitment["suite_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "EVALUATOR_R1_2_ERRATUM_SEALED_FINAL_SCORING_PERMITTED",
        "failed_attempts_preserved": [
            {
                "revision": "R1",
                "failure": "physical integer dtype mismatch treated as missing or extra keys",
                "result_file_created": False,
            },
            {
                "revision": "R1.1",
                "failure": "wrapper delegation recursed after entry-point monkeypatch",
                "result_file_created": False,
            },
        ],
        "r1_2_scope": {
            "changed": [
                "normalize integral key columns to int64",
                "delegate through an immutable reference to the original R1 validator",
            ],
            "unchanged": [
                "all committed prediction bytes and hashes",
                "all target bytes and hash",
                "metric equations, horizons, bootstrap, gates, and claim boundary",
            ],
        },
        "artifacts": {
            "original_runtime_seal": artifact(runtime_seal),
            "original_evaluator_r1": artifact(original),
            "failed_evaluator_r1_1": artifact(failed_r1_1),
            "r1_1_erratum_seal": artifact(prior_erratum),
            "evaluator_r1_2": artifact(revision),
            "r1_2_conformance": artifact(conformance_path),
            "prediction_commitment": artifact(commitment_path),
            "test_targets": artifact(targets),
        },
        "next_permitted_action": (
            "Run evaluator R1.2 once against the committed prediction manifest and publish."
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
