#!/usr/bin/env python3
"""Verify the V3 prediction commitment before any target acquisition."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from prediction_runtime import (
    BUNDLE_MANIFEST_PATH,
    DRAFT_ROOT,
    PROTOCOL_PATH,
    artifact,
    enforce_label_firewall,
    fingerprint,
    load_json,
    load_prediction_contract,
    sha256_file,
    utc_now,
    validate_submission,
    write_json_atomic,
)


PREDICTION_ROOT = DRAFT_ROOT / "predictions"
COMMITMENT_PATH = PREDICTION_ROOT / "prediction_commitment.json"
DEFAULT_OUTPUT = PREDICTION_ROOT / "prediction_commitment_verification.json"


def verify(output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    protocol = load_json(PROTOCOL_PATH)
    firewall = enforce_label_firewall(protocol)
    bundle = load_json(BUNDLE_MANIFEST_PATH)
    commitment = load_json(COMMITMENT_PATH)
    contract, expected_keys = load_prediction_contract()
    checks: dict[str, bool] = {
        "commitment_status_is_complete": commitment["status"]
        == "ALL_FIVE_PREDICTIONS_COMMITTED_TARGET_ACQUISITION_ALLOWED",
        "protocol_hash_matches": commitment["commitment_identity"][
            "protocol_sha256"
        ]
        == sha256_file(PROTOCOL_PATH),
        "phase_a_bundle_fingerprint_matches": commitment[
            "commitment_identity"
        ]["phase_a_bundle_fingerprint"]
        == bundle["bundle_fingerprint"],
        "commitment_fingerprint_matches": commitment["commitment_fingerprint"]
        == fingerprint(commitment["commitment_identity"]),
        "exactly_five_models": len(commitment["models"]) == 5,
        "runtime_replay_report_hash_matches": True,
        "all_artifact_hashes_match": True,
        "all_submissions_match_contract": True,
        "all_submissions_have_identical_keys": True,
        "target_file_count_is_zero": firewall["target_file_count"] == 0,
        "target_pixels_read_is_false": not firewall["target_pixels_read"],
    }
    runtime_path = DRAFT_ROOT.parents[1] / commitment["runtime_replay"]["path"]
    checks["runtime_replay_report_hash_matches"] = (
        runtime_path.is_file()
        and sha256_file(runtime_path) == commitment["runtime_replay"]["sha256"]
        and load_json(runtime_path)["status"]
        == "PASS_ALL_FIVE_MODELS_REPLAYED_LABEL_FIREWALL_INTACT"
    )

    reference_keys = None
    model_checks = {}
    for model_id, row in commitment["models"].items():
        artifact_checks = {}
        for name in ("prediction", "model_spec", "run_report"):
            recorded = row[name]
            path = DRAFT_ROOT.parents[1] / recorded["path"]
            artifact_checks[name] = (
                path.is_file()
                and path.stat().st_size == int(recorded["size_bytes"])
                and sha256_file(path) == recorded["sha256"]
            )
        checks["all_artifact_hashes_match"] = checks[
            "all_artifact_hashes_match"
        ] and all(artifact_checks.values())
        prediction_path = DRAFT_ROOT.parents[1] / row["prediction"]["path"]
        try:
            frame = validate_submission(
                pd.read_parquet(prediction_path),
                contract=contract,
                expected_keys=expected_keys,
            )
            contract_pass = True
        except Exception:
            frame = None
            contract_pass = False
        checks["all_submissions_match_contract"] = checks[
            "all_submissions_match_contract"
        ] and contract_pass
        if frame is not None:
            keys = frame.iloc[:, :3].reset_index(drop=True)
            if reference_keys is None:
                reference_keys = keys
            else:
                checks["all_submissions_have_identical_keys"] = checks[
                    "all_submissions_have_identical_keys"
                ] and keys.equals(reference_keys)
        model_checks[model_id] = {
            "artifact_hashes": artifact_checks,
            "submission_contract_pass": contract_pass,
            "prediction_sha256": row["prediction"]["sha256"],
        }

    passed = all(checks.values())
    report = {
        "schema": "gwm_bench.v3_prediction_commitment_verification.v1",
        "suite_id": protocol["suite_id"],
        "status": (
            "PASS_RC2_PREDICTIONS_COMMITTED_TARGET_ACQUISITION_ALLOWED"
            if passed
            else "FAIL_PREDICTION_COMMITMENT_VERIFICATION"
        ),
        "created_at": utc_now(),
        "commitment": artifact(
            COMMITMENT_PATH, role="verified_v3_prediction_commitment"
        ),
        "commitment_fingerprint": commitment["commitment_fingerprint"],
        "checks": checks,
        "models": model_checks,
        "label_firewall": firewall,
        "target_acquisition_allowed": passed,
    }
    write_json_atomic(report, output_path)
    if not passed:
        raise RuntimeError(report["status"])
    print(report["status"])
    print(f"commitment_fingerprint: {commitment['commitment_fingerprint']}")
    print(f"verification: {output_path}")
    return report


if __name__ == "__main__":
    verify()
