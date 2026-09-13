#!/usr/bin/env python3
"""Verify the V5 Runtime-R4 smoke run without reading outer-fold answers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v5_runtime_models import (
    STATE_COLUMNS,
    load_checkpoint,
    load_relations,
    load_test_input,
    predict_residual,
    sha256_file,
    test_residual_example,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_ROOT = Path(__file__).resolve().parent
SMOKE_ROOT = DRAFT_ROOT / "smoke_runtime_r4"
SMOKE_REPORT_PATH = SMOKE_ROOT / "smoke_report.json"
OUTPUT_PATH = SMOKE_ROOT / "smoke_verification.json"
FOLD_ID = "holdout_2015"
FOLD_ROOT = DRAFT_ROOT / "rc1_bundle/folds" / FOLD_ID
DETERMINISTIC_IDS = ["history_ar_backbone", "fixed_adjacency_spatial_ar"]
STOCHASTIC_IDS = [
    "dam_gk_residual_no_action",
    "uwm_dam_gk_action_residual",
    "action_deleted",
    "effective_date_minus_4w",
    "effective_date_plus_4w",
    "action_component_permutation",
    "wrong_spatial_scope",
    "cross_event_action_swap",
    "zone_exposure_shuffle_seed_20260723",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def artifact_ok(row: dict[str, Any]) -> bool:
    path = REPO_ROOT / row["path"]
    return (
        path.is_file()
        and path.stat().st_size == row["bytes"]
        and sha256_file(path) == row["sha256"]
    )


def prediction_path(model_id: str) -> Path:
    if model_id in DETERMINISTIC_IDS:
        return SMOKE_ROOT / model_id / "folds" / FOLD_ID / "prediction.parquet"
    return (
        SMOKE_ROOT
        / model_id
        / "members/seed_31/folds"
        / FOLD_ID
        / "prediction.parquet"
    )


def prediction_array(frame: pd.DataFrame) -> np.ndarray:
    ordered = frame.sort_values(["horizon_week", "zone_id"])
    return ordered[[f"{target}_prediction" for target in STATE_COLUMNS]].to_numpy(
        dtype=np.float32
    ).reshape(12, 263, 4)


def main() -> int:
    smoke = load_json(SMOKE_REPORT_PATH)
    fold_report = smoke["folds"][0]
    expected_keys = pd.read_parquet(
        FOLD_ROOT / "test_input/submission_keys.parquet"
    ).sort_values(["zone_id", "horizon_week"]).reset_index(drop=True)
    frames = {
        model_id: pd.read_parquet(prediction_path(model_id))
        for model_id in [*DETERMINISTIC_IDS, *STOCHASTIC_IDS]
    }
    key_checks = {}
    value_checks = {}
    for model_id, frame in frames.items():
        actual = frame[["zone_id", "horizon_week"]].sort_values(
            ["zone_id", "horizon_week"]
        ).reset_index(drop=True)
        actual = actual.astype({"zone_id": np.int64, "horizon_week": np.int64})
        frozen = expected_keys.astype(
            {"zone_id": np.int64, "horizon_week": np.int64}
        )
        values = frame[
            [f"{target}_prediction" for target in STATE_COLUMNS]
        ].to_numpy(dtype=float)
        key_checks[model_id] = bool(len(frame) == 3156 and actual.equals(frozen))
        value_checks[model_id] = bool(
            np.isfinite(values).all() and (values >= 0).all()
        )

    arrays = {model_id: prediction_array(frame) for model_id, frame in frames.items()}
    history = arrays["history_ar_backbone"]
    candidate = arrays["uwm_dam_gk_action_residual"]
    plus4 = arrays["effective_date_plus_4w"]
    action = pd.read_parquet(FOLD_ROOT / "test_input/future_action_spec.parquet")
    exposure_unique = action["spatial_applicability_share"].nunique()

    checkpoint_path = (
        SMOKE_ROOT
        / "uwm_dam_gk_action_residual/members/seed_31/folds"
        / FOLD_ID
        / "model.pt"
    )
    model, scaler, _ = load_checkpoint(checkpoint_path)
    test = load_test_input(
        FOLD_ROOT / "test_input/weekly_state_history.parquet",
        FOLD_ROOT / "test_input/future_action_spec.parquet",
    )
    relations, _ = load_relations(FOLD_ROOT / "graph/test_spatial_edges.parquet")
    example = test_residual_example(
        "event_2015_improvement_surcharge", test, history, relations
    )
    replayed, _ = predict_residual(
        model, scaler, example, action_conditioned=True
    )
    replay_max_abs = float(np.max(np.abs(replayed - candidate)))

    changed_controls = [
        "effective_date_minus_4w",
        "effective_date_plus_4w",
        "action_component_permutation",
        "wrong_spatial_scope",
        "cross_event_action_swap",
    ]
    checks = {
        "smoke_status_passed": smoke["status"]
        == "PASS_RUNTIME_R4_SMOKE_NO_TARGET_ACCESS",
        "smoke_is_not_formal_prediction": smoke["formal_predictions_created"] is False,
        "exactly_one_smoke_fold": len(smoke["folds"]) == 1
        and fold_report["outer_fold_id"] == FOLD_ID,
        "read_audit_contains_no_answer_directory": fold_report[
            "model_read_paths_contain_answer_directory"
        ]
        is False
        and fold_report["test_target_rows_loaded"] is False,
        "all_recorded_read_artifacts_still_match": all(
            artifact_ok(row) for row in fold_report["model_read_artifacts"]
        ),
        "runner_and_model_core_hashes_match_smoke_report": artifact_ok(smoke["runner"])
        and artifact_ok(smoke["model_core"]),
        "all_eleven_fold_predictions_exist": len(frames) == 11,
        "all_prediction_keys_match_frozen_fold_keys": all(key_checks.values()),
        "all_predictions_are_finite_and_nonnegative": all(value_checks.values()),
        "candidate_emits_nonzero_residual": not np.array_equal(candidate, history),
        "action_deleted_is_exact_history_backbone": np.array_equal(
            arrays["action_deleted"], history
        ),
        "plus_four_week_control_has_exact_four_week_zero_action_anchor": np.array_equal(
            plus4[:4], history[:4]
        )
        and not np.array_equal(plus4[4:], history[4:]),
        "component_date_scope_and_swap_controls_change_prediction": all(
            not np.array_equal(arrays[control_id], candidate)
            for control_id in changed_controls
        ),
        "uniform_citywide_exposure_explains_shuffle_identity": exposure_unique == 1
        and np.array_equal(
            arrays["zone_exposure_shuffle_seed_20260723"], candidate
        ),
        "saved_checkpoint_replays_candidate_within_tolerance": replay_max_abs <= 1e-6,
    }
    checks = {key: bool(value) for key, value in checks.items()}
    passed = all(checks.values())
    report = {
        "schema": "gwm_bench.foundation_v5_runtime_r4_smoke_verification.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_RUNTIME_R4_SMOKE_VERIFIED" if passed else "FAIL",
        "check_count": len(checks),
        "passed_check_count": sum(checks.values()),
        "failed_checks": [key for key, value in checks.items() if not value],
        "checks": checks,
        "prediction_key_checks": key_checks,
        "prediction_value_checks": value_checks,
        "checkpoint_replay_max_abs_difference": replay_max_abs,
        "next_permitted_action": (
            "Run the four-fold formal Runtime-R4 prediction matrix without answer access."
            if passed
            else "Fix the smoke runner before any formal prediction run."
        ),
    }
    write_json(OUTPUT_PATH, report)
    print(f"GWM-Bench Foundation V5.0 Runtime-R4 smoke: {report['status']}")
    print(f"Checks: {report['passed_check_count']}/{report['check_count']}")
    print(f"Verification: {OUTPUT_PATH}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
