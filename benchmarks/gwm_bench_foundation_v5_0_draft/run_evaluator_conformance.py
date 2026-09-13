#!/usr/bin/env python3
"""Constructed-answer conformance tests for the frozen V5 multi-fold evaluator."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from action_transfer_evaluator import (
    CANDIDATE_ID,
    DRAFT_ROOT,
    HISTORY_BASELINE_ID,
    REPORT_HORIZONS,
    TARGETS,
    SubmissionError,
    action_transfer_decision,
    evaluate_submission,
    load_json,
    paired_comparison,
    validate_submission,
)


OUTPUT_PATH = DRAFT_ROOT / "evaluator_conformance_report.json"


def expect_submission_error(callback: Callable[[], object]) -> bool:
    try:
        callback()
    except (SubmissionError, ValueError, TypeError):
        return True
    return False


def prediction(keys: pd.DataFrame, values: dict[str, np.ndarray]) -> pd.DataFrame:
    frame = keys.copy()
    for target in TARGETS:
        frame[f"{target}_prediction"] = values[target]
    return frame


def main() -> int:
    contract = load_json(DRAFT_ROOT / "submission_contract.json")
    protocol = load_json(DRAFT_ROOT / "suite_protocol.json")
    fold_ids = contract["expected_fold_ids"]
    keys = pd.MultiIndex.from_product(
        [fold_ids, range(1, 264), range(1, 13)],
        names=["fold_id", "zone_id", "horizon_week"],
    ).to_frame(index=False)
    histories: dict[str, pd.DataFrame] = {}
    targets = keys.copy()
    target_values: dict[str, np.ndarray] = {}
    fold_offset = targets["fold_id"].map(
        {fold_id: index * 25.0 for index, fold_id in enumerate(fold_ids)}
    ).to_numpy(dtype=float)
    for fold_index, fold_id in enumerate(fold_ids):
        history = pd.MultiIndex.from_product(
            [range(1, 264), range(-52, 0)],
            names=["zone_id", "relative_week"],
        ).to_frame(index=False)
        for target_index, target in enumerate(TARGETS):
            history[target] = (
                100.0
                + fold_index * 25.0
                + history["zone_id"].to_numpy(dtype=float) % 11
                + target_index * 10.0
            )
        histories[fold_id] = history
    for target_index, target in enumerate(TARGETS):
        values = (
            100.0
            + fold_offset
            + targets["zone_id"].to_numpy(dtype=float) % 11
            + target_index * 10.0
            + targets["horizon_week"].to_numpy(dtype=float)
        )
        targets[target] = values
        target_values[target] = values

    perfect = prediction(keys, target_values)
    biased_10 = prediction(
        keys, {target: values + 10.0 for target, values in target_values.items()}
    )
    biased_11 = prediction(
        keys, {target: values + 11.0 for target, values in target_values.items()}
    )
    biased_20 = prediction(
        keys, {target: values + 20.0 for target, values in target_values.items()}
    )
    validated_perfect = validate_submission(perfect, keys, contract)
    validated_biased = validate_submission(biased_10, keys, contract)
    perfect_metrics, perfect_errors = evaluate_submission(
        validated_perfect, histories, targets
    )
    biased_metrics, biased_errors = evaluate_submission(
        validated_biased, histories, targets
    )
    comparison = paired_comparison(
        perfect_errors,
        biased_errors,
        draws=2000,
        seed=20260723,
    )

    duplicate = perfect.copy()
    duplicate.loc[duplicate.index[-1], contract["key_columns"]] = duplicate.loc[
        duplicate.index[0], contract["key_columns"]
    ].to_numpy()
    missing = perfect.iloc[:-1].copy()
    wrong_fold = perfect.copy()
    wrong_fold.loc[0, "fold_id"] = "holdout_unknown"
    nonintegral_key = perfect.copy()
    nonintegral_key["zone_id"] = nonintegral_key["zone_id"].astype(float)
    nonintegral_key.loc[0, "zone_id"] = 1.5
    negative = perfect.copy()
    negative.loc[0, "pickup_count_prediction"] = -1.0
    nonfinite = perfect.copy()
    nonfinite.loc[0, "pickup_count_prediction"] = np.nan
    extra_column = perfect.copy()
    extra_column["event_year"] = 2025
    partial_uncertainty = perfect.copy()
    partial_uncertainty["pickup_count_p10"] = 0.0
    bad_uncertainty = perfect.copy()
    for target in TARGETS:
        bad_uncertainty[f"{target}_p10"] = bad_uncertainty[f"{target}_prediction"] + 1.0
        bad_uncertainty[f"{target}_p90"] = bad_uncertainty[f"{target}_prediction"] + 2.0
    mixed_width_keys = perfect.astype({"zone_id": np.int16, "horizon_week": np.int64})
    validated_mixed_width = validate_submission(mixed_width_keys, keys, contract)

    conformance_protocol = copy.deepcopy(protocol)
    conformance_protocol["evaluation"]["paired_bootstrap"]["draws"] = 2000
    required_ids = [
        *protocol["required_models"],
        *protocol["required_controls"],
    ]
    pass_submissions: dict[str, pd.DataFrame] = {
        model_id: biased_20 for model_id in required_ids
    }
    pass_submissions[CANDIDATE_ID] = perfect
    pass_submissions[HISTORY_BASELINE_ID] = biased_10
    pass_metrics: dict[str, dict] = {}
    pass_errors: dict[str, pd.DataFrame] = {}
    for model_id, submission in pass_submissions.items():
        model_metrics, model_errors = evaluate_submission(
            validate_submission(submission, keys, contract), histories, targets
        )
        pass_metrics[model_id] = model_metrics
        pass_errors[model_id] = model_errors
    passing_gate, _ = action_transfer_decision(
        pass_metrics, pass_errors, conformance_protocol
    )

    fail_submissions = dict(pass_submissions)
    fail_submissions[CANDIDATE_ID] = biased_11
    fail_metrics: dict[str, dict] = {}
    fail_errors: dict[str, pd.DataFrame] = {}
    for model_id, submission in fail_submissions.items():
        model_metrics, model_errors = evaluate_submission(
            validate_submission(submission, keys, contract), histories, targets
        )
        fail_metrics[model_id] = model_metrics
        fail_errors[model_id] = model_errors
    failing_gate, _ = action_transfer_decision(
        fail_metrics, fail_errors, conformance_protocol
    )

    checks = {
        "perfect_multifold_submission_validates": len(validated_perfect) == 12624,
        "all_four_folds_have_exact_key_counts": validated_perfect.groupby(
            "fold_id", observed=True
        ).size().eq(3156).all(),
        "integer_storage_width_does_not_change_key_identity": len(validated_mixed_width)
        == 12624
        and validated_mixed_width["zone_id"].dtype == np.dtype("int64")
        and validated_mixed_width["horizon_week"].dtype == np.dtype("int64"),
        "perfect_primary_metric_is_zero": abs(
            perfect_metrics["primary_equal_event_macro_pre_action_normalized_mae"]
        )
        < 1e-12,
        "biased_primary_metric_is_positive": biased_metrics[
            "primary_equal_event_macro_pre_action_normalized_mae"
        ]
        > 0,
        "four_equal_event_fold_scores_are_reported": sorted(
            perfect_metrics["by_fold"]
        )
        == sorted(fold_ids),
        "all_four_targets_are_reported": sorted(
            perfect_metrics["by_target_equal_event"]
        )
        == sorted(TARGETS),
        "only_five_frozen_horizons_are_primary": sorted(
            int(value) for value in perfect_metrics["by_horizon_equal_event"]
        )
        == REPORT_HORIZONS,
        "perfect_beats_biased_equal_event": comparison[
            "candidate_minus_baseline_equal_event"
        ]
        < 0,
        "perfect_vs_biased_interval_is_below_zero": comparison[
            "bootstrap_95_percentile_interval"
        ][1]
        < 0,
        "all_sixteen_event_target_directions_are_correct": sum(
            value < 0 for value in comparison["by_fold_target"].values()
        )
        == 16,
        "all_five_horizon_directions_are_correct": sum(
            value < 0 for value in comparison["by_horizon_equal_event"].values()
        )
        == 5,
        "constructed_supported_case_passes_all_eight_gates": passing_gate["passed"]
        and len(passing_gate["conditions"]) == 8
        and all(passing_gate["conditions"].values()),
        "constructed_unsupported_case_completes_but_fails_gate": not failing_gate[
            "passed"
        ],
        "duplicate_keys_are_rejected": expect_submission_error(
            lambda: validate_submission(duplicate, keys, contract)
        ),
        "missing_keys_are_rejected": expect_submission_error(
            lambda: validate_submission(missing, keys, contract)
        ),
        "wrong_fold_is_rejected": expect_submission_error(
            lambda: validate_submission(wrong_fold, keys, contract)
        ),
        "nonintegral_keys_are_rejected": expect_submission_error(
            lambda: validate_submission(nonintegral_key, keys, contract)
        ),
        "negative_predictions_are_rejected": expect_submission_error(
            lambda: validate_submission(negative, keys, contract)
        ),
        "nonfinite_predictions_are_rejected": expect_submission_error(
            lambda: validate_submission(nonfinite, keys, contract)
        ),
        "extra_columns_are_rejected": expect_submission_error(
            lambda: validate_submission(extra_column, keys, contract)
        ),
        "partial_uncertainty_is_rejected": expect_submission_error(
            lambda: validate_submission(partial_uncertainty, keys, contract)
        ),
        "bad_uncertainty_order_is_rejected": expect_submission_error(
            lambda: validate_submission(bad_uncertainty, keys, contract)
        ),
    }
    checks = {key: bool(value) for key, value in checks.items()}
    passed = all(checks.values())
    report = {
        "schema": "gwm_bench.foundation_v5_action_transfer_evaluator_conformance.v1",
        "suite_id": protocol["suite_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_V5_ACTION_TRANSFER_EVALUATOR_CONFORMANCE" if passed else "FAIL",
        "check_count": len(checks),
        "passed_check_count": sum(checks.values()),
        "failed_checks": [key for key, value in checks.items() if not value],
        "checks": checks,
        "constructed_answer_metrics": {
            "perfect": perfect_metrics[
                "primary_equal_event_macro_pre_action_normalized_mae"
            ],
            "biased": biased_metrics[
                "primary_equal_event_macro_pre_action_normalized_mae"
            ],
            "perfect_minus_biased": comparison,
            "passing_gate": passing_gate,
            "failing_gate": failing_gate,
        },
    }
    OUTPUT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"GWM-Bench Foundation V5.0 evaluator: {report['status']}")
    print(f"Checks: {report['passed_check_count']}/{report['check_count']}")
    print(f"Conformance report: {OUTPUT_PATH}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
