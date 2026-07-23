#!/usr/bin/env python3
"""Verify final V3 artifacts without running the evaluator again."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from prediction_runtime import (
    DRAFT_ROOT,
    PROTOCOL_PATH,
    REPO_ROOT,
    artifact,
    fingerprint,
    load_json,
    sha256_file,
    utc_now,
    write_json_atomic,
)


FINAL_ROOT = DRAFT_ROOT / "final_results"
FINAL_PATH = FINAL_ROOT / "final_results.json"
COMMITMENT_PATH = DRAFT_ROOT / "predictions/prediction_commitment.json"
TARGET_REGISTRY_PATH = DRAFT_ROOT / "phase_c_targets/target_registry.json"
RUNTIME_SEAL_PATH = DRAFT_ROOT / "runtime_r2_evaluator_seal.json"
EVALUATOR_PATH = DRAFT_ROOT / "observed_o3_evaluator.py"
DEFAULT_OUTPUT = FINAL_ROOT / "final_verification.json"


def verify(output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    final = load_json(FINAL_PATH)
    commitment = load_json(COMMITMENT_PATH)
    targets = load_json(TARGET_REGISTRY_PATH)
    seal = load_json(RUNTIME_SEAL_PATH)
    checks = {
        "final_status_is_completed": final["status"].startswith("V3_FINAL_COMPLETED"),
        "formal_scoring_event_count_is_one": final["formal_scoring_event_count"] == 1,
        "final_fingerprint_matches": final["final_results_fingerprint"]
        == fingerprint(final["final_identity"]),
        "protocol_hash_matches": final["final_identity"]["protocol_sha256"]
        == sha256_file(PROTOCOL_PATH),
        "prediction_commitment_fingerprint_matches": final["final_identity"][
            "prediction_commitment_fingerprint"
        ]
        == commitment["commitment_fingerprint"],
        "target_dataset_fingerprint_matches": final["final_identity"][
            "target_dataset_fingerprint"
        ]
        == targets["target_dataset_fingerprint"],
        "evaluator_hash_matches_seal": sha256_file(EVALUATOR_PATH)
        == seal["artifacts"]["observed_o3_evaluator.py"]["sha256"]
        == final["final_identity"]["evaluator_sha256"],
        "all_five_model_evaluation_hashes_match": True,
        "all_five_models_published": final["publication"][
            "all_five_models_published"
        ],
        "negative_results_retained": final["publication"][
            "negative_results_retained"
        ],
        "single_composite_score_is_false": not final["publication"][
            "single_composite_score"
        ],
    }
    model_checks = {}
    for model_id, recorded_hash in final["final_identity"][
        "evaluation_sha256"
    ].items():
        path = FINAL_ROOT / f"{model_id}_evaluation.json"
        passed = path.is_file() and sha256_file(path) == recorded_hash
        checks["all_five_model_evaluation_hashes_match"] = checks[
            "all_five_model_evaluation_hashes_match"
        ] and passed
        model_checks[model_id] = {
            "path": str(path.relative_to(REPO_ROOT)),
            "sha256": recorded_hash,
            "passed": passed,
        }
    passed = all(checks.values()) and len(model_checks) == 5
    report = {
        "schema": "gwm_bench.foundation_v3_final_verification.v1",
        "suite_id": final["suite_id"],
        "status": "PASS_V3_FINAL_VERIFIED" if passed else "FAIL_V3_FINAL_VERIFICATION",
        "created_at": utc_now(),
        "checks": checks,
        "models": model_checks,
        "final_results_fingerprint": final["final_results_fingerprint"],
        "artifacts": {
            "final_results": artifact(FINAL_PATH, role="verified_v3_final_results"),
            "prediction_commitment": artifact(
                COMMITMENT_PATH, role="verified_pre_target_prediction_commitment"
            ),
            "target_registry": artifact(
                TARGET_REGISTRY_PATH, role="verified_phase_c_target_registry"
            ),
            "evaluator": artifact(EVALUATOR_PATH, role="verified_sealed_evaluator"),
        },
    }
    write_json_atomic(report, output_path)
    if not passed:
        raise RuntimeError(report["status"])
    print(report["status"])
    print(f"final_results_fingerprint: {final['final_results_fingerprint']}")
    print(f"verification: {output_path}")
    return report


if __name__ == "__main__":
    verify()
