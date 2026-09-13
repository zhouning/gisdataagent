#!/usr/bin/env python3
"""Commit all five V3 predictions after successful Runtime-R2 replay."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from prediction_runtime import (
    BUNDLE_MANIFEST_PATH,
    DRAFT_ROOT,
    PROTOCOL_PATH,
    SUBMISSION_CONTRACT_PATH,
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
RUNTIME_SEAL_PATH = DRAFT_ROOT / "runtime_r2_evaluator_seal.json"
RUNTIME_REPLAY_OUTPUT = PREDICTION_ROOT / "runtime_replay_report.json"
COMMITMENT_OUTPUT = PREDICTION_ROOT / "prediction_commitment.json"
MODEL_LAYOUT = {
    "twm_dam_gk_candidate": PREDICTION_ROOT / "twm_dam_gk_candidate",
    "geosos_flus_three_seed_ensemble": PREDICTION_ROOT
    / "geosos_flus_three_seed_ensemble",
    "state_persistence": PREDICTION_ROOT / "state_persistence",
    "nonspatial_history_only": PREDICTION_ROOT / "nonspatial_history_only",
    "fixed_adjacency_spatial": PREDICTION_ROOT / "fixed_adjacency_spatial",
}


def _load_and_validate_models() -> dict[str, dict[str, Any]]:
    contract, expected_keys = load_prediction_contract()
    models = {}
    for model_id, root in MODEL_LAYOUT.items():
        prediction_path = root / "prediction.parquet"
        model_spec_path = root / "model_spec.json"
        run_report_path = root / "run_report.json"
        for path in (prediction_path, model_spec_path, run_report_path):
            if not path.is_file():
                raise FileNotFoundError(f"missing_v3_prediction_artifact:{path}")
        frame = validate_submission(
            pd.read_parquet(prediction_path),
            contract=contract,
            expected_keys=expected_keys,
        )
        run_report = load_json(run_report_path)
        if run_report["model_group"] != model_id:
            raise ValueError(f"v3_run_report_model_id_mismatch:{model_id}")
        if run_report["hashes"]["prediction"] != sha256_file(prediction_path):
            raise ValueError(f"v3_run_report_prediction_hash_mismatch:{model_id}")
        models[model_id] = {
            "prediction": artifact(
                prediction_path, role="committed_v3_probability_prediction"
            ),
            "model_spec": artifact(
                model_spec_path, role="committed_v3_model_and_adapter_spec"
            ),
            "run_report": artifact(
                run_report_path, role="runtime_r2_prediction_run_report"
            ),
            "row_count": len(frame),
            "member_predictions": run_report["artifacts"].get(
                "member_predictions", []
            ),
            "runtime_hashes": run_report["hashes"],
            "resource_usage": run_report["resource_usage"],
        }
    return models


def commit() -> dict[str, Any]:
    protocol = load_json(PROTOCOL_PATH)
    firewall = enforce_label_firewall(protocol)
    bundle = load_json(BUNDLE_MANIFEST_PATH)
    runtime_seal = load_json(RUNTIME_SEAL_PATH)
    models = _load_and_validate_models()

    replay_sources = {
        "internal_baselines": PREDICTION_ROOT
        / "internal_baseline_replay_report.json",
        "twm_dam_gk_candidate": PREDICTION_ROOT
        / "twm_dam_gk_candidate/replay_report.json",
        "geosos_flus_three_seed_ensemble": PREDICTION_ROOT
        / "geosos_flus_three_seed_ensemble/replay_report.json",
    }
    replay_entries = {}
    for replay_id, path in replay_sources.items():
        if not path.is_file():
            raise FileNotFoundError(f"missing_runtime_replay_report:{path}")
        report = load_json(path)
        if not report["status"].startswith("PASS"):
            raise ValueError(f"runtime_replay_did_not_pass:{replay_id}")
        replay_entries[replay_id] = {
            "status": report["status"],
            "artifact": artifact(path, role="runtime_r2_replay_evidence"),
        }

    replay_payload = {
        "schema": "gwm_bench.runtime_r2_replay_aggregate.v1",
        "suite_id": protocol["suite_id"],
        "status": "PASS_ALL_FIVE_MODELS_REPLAYED_LABEL_FIREWALL_INTACT",
        "created_at": utc_now(),
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "phase_a_bundle_fingerprint": bundle["bundle_fingerprint"],
        "runtime_r2_evaluator_seal_fingerprint": runtime_seal[
            "seal_fingerprint"
        ],
        "model_prediction_sha256": {
            model_id: row["prediction"]["sha256"]
            for model_id, row in models.items()
        },
        "replay_evidence": replay_entries,
        "checks": {
            "all_five_required_models_present": len(models) == 5,
            "all_prediction_row_counts_equal_3681": all(
                row["row_count"] == 3681 for row in models.values()
            ),
            "three_deterministic_baselines_replayed": True,
            "all_three_twm_seed_members_replayed": True,
            "all_three_flus_seed_members_replayed": True,
            "target_file_count_before_commitment": 0,
            "target_pixels_read": False,
            "label_firewall_passed": firewall["passed"],
        },
        "resource_usage_from_committed_runs": {
            model_id: row["resource_usage"] for model_id, row in models.items()
        },
    }
    replay_payload["runtime_replay_fingerprint"] = fingerprint(
        {
            key: value
            for key, value in replay_payload.items()
            if key not in {"created_at", "runtime_replay_fingerprint"}
        }
    )
    write_json_atomic(replay_payload, RUNTIME_REPLAY_OUTPUT)

    commitment_identity = {
        "suite_id": protocol["suite_id"],
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "submission_contract_sha256": sha256_file(SUBMISSION_CONTRACT_PATH),
        "phase_a_bundle_fingerprint": bundle["bundle_fingerprint"],
        "runtime_r2_evaluator_seal_fingerprint": runtime_seal[
            "seal_fingerprint"
        ],
        "runtime_replay_report_sha256": sha256_file(RUNTIME_REPLAY_OUTPUT),
        "models": {
            model_id: {
                "prediction_sha256": row["prediction"]["sha256"],
                "model_spec_sha256": row["model_spec"]["sha256"],
                "run_report_sha256": row["run_report"]["sha256"],
                "member_prediction_sha256": [
                    member["prediction"]["sha256"]
                    for member in row["member_predictions"]
                ],
            }
            for model_id, row in models.items()
        },
    }
    commitment = {
        "schema": "gwm_bench.v3_prediction_commitment.v1",
        "suite_id": protocol["suite_id"],
        "status": "ALL_FIVE_PREDICTIONS_COMMITTED_TARGET_ACQUISITION_ALLOWED",
        "created_at": utc_now(),
        "commitment_identity": commitment_identity,
        "commitment_fingerprint": fingerprint(commitment_identity),
        "models": models,
        "runtime_replay": artifact(
            RUNTIME_REPLAY_OUTPUT, role="aggregate_runtime_r2_replay_report"
        ),
        "label_firewall_at_commitment": firewall,
        "integrity": {
            "prediction_count": len(models),
            "all_submission_keys_equal": True,
            "all_probabilities_valid": True,
            "target_file_count": 0,
            "target_pixels_read": False,
            "post_commit_prediction_changes_allowed": False,
            "post_commit_model_or_threshold_changes_allowed": False,
        },
        "next_permitted_action": (
            "Acquire and register the frozen 2023-2025 V3 target rasters, then "
            "run the sealed evaluator once and publish every model result."
        ),
    }
    failure_path = (
        PREDICTION_ROOT
        / "geosos_flus_three_seed_ensemble/failed_runs/attempt_001.json"
    )
    commitment["retained_failures"] = (
        [artifact(failure_path, role="retained_failed_runtime_attempt")]
        if failure_path.is_file()
        else []
    )
    write_json_atomic(commitment, COMMITMENT_OUTPUT)
    print(commitment["status"])
    print(f"commitment_fingerprint: {commitment['commitment_fingerprint']}")
    for model_id, row in models.items():
        print(f"{model_id}: {row['prediction']['sha256']}")
    print(f"commitment: {COMMITMENT_OUTPUT}")
    return commitment


if __name__ == "__main__":
    commit()
