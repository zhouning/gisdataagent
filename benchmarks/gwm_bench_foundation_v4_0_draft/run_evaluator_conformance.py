#!/usr/bin/env python3
"""Constructed-answer conformance tests for the frozen ACTION-A4 evaluator."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from action_a4_evaluator import (
    DRAFT_ROOT,
    REPORT_HORIZONS,
    SubmissionError,
    evaluate_submission,
    load_json,
    paired_comparison,
    validate_submission,
)


OUTPUT_PATH = DRAFT_ROOT / "evaluator_conformance_report.json"
TARGETS = ["pickup_count", "dropoff_count", "cbd_inflow", "cbd_outflow"]


def _expect_submission_error(callback: Callable[[], object]) -> bool:
    try:
        callback()
    except SubmissionError:
        return True
    return False


def _prediction(keys: pd.DataFrame, values: dict[str, np.ndarray]) -> pd.DataFrame:
    frame = keys.copy()
    for target in TARGETS:
        frame[f"{target}_prediction"] = values[target]
    return frame


def main() -> int:
    contract = load_json(DRAFT_ROOT / "submission_contract.json")
    keys = pd.MultiIndex.from_product(
        [range(1, 264), range(1, 13)],
        names=["zone_id", "horizon_week"],
    ).to_frame(index=False)
    history = pd.MultiIndex.from_product(
        [range(1, 264), range(-52, 0)],
        names=["zone_id", "relative_week"],
    ).to_frame(index=False)
    for target_index, target in enumerate(TARGETS):
        history[target] = (
            100.0
            + history["zone_id"].to_numpy(dtype=float) % 11
            + target_index * 10.0
        )

    targets = keys.copy()
    target_values: dict[str, np.ndarray] = {}
    for target_index, target in enumerate(TARGETS):
        values = (
            100.0
            + targets["zone_id"].to_numpy(dtype=float) % 11
            + target_index * 10.0
            + targets["horizon_week"].to_numpy(dtype=float)
        )
        targets[target] = values
        target_values[target] = values

    perfect = _prediction(keys, target_values)
    biased = _prediction(
        keys,
        {target: values + 10.0 for target, values in target_values.items()},
    )
    validated_perfect = validate_submission(perfect, keys, contract)
    validated_biased = validate_submission(biased, keys, contract)
    perfect_metrics, perfect_errors = evaluate_submission(
        validated_perfect, history, targets
    )
    biased_metrics, biased_errors = evaluate_submission(
        validated_biased, history, targets
    )
    comparison = paired_comparison(
        perfect_errors,
        biased_errors,
        draws=2000,
        seed=20260723,
    )

    duplicate = pd.concat([perfect, perfect.iloc[[0]]], ignore_index=True).iloc[:3156]
    duplicate.iloc[-1] = duplicate.iloc[0]
    missing = perfect.iloc[:-1].copy()
    negative = perfect.copy()
    negative.loc[0, "pickup_count_prediction"] = -1.0
    nonfinite = perfect.copy()
    nonfinite.loc[0, "pickup_count_prediction"] = np.nan
    partial_uncertainty = perfect.copy()
    partial_uncertainty["pickup_count_p10"] = 0.0
    bad_uncertainty = perfect.copy()
    for target in TARGETS:
        bad_uncertainty[f"{target}_p10"] = bad_uncertainty[f"{target}_prediction"] + 1.0
        bad_uncertainty[f"{target}_p90"] = bad_uncertainty[f"{target}_prediction"] + 2.0

    checks = {
        "perfect_submission_validates": len(validated_perfect) == 3156,
        "perfect_primary_metric_is_zero": abs(
            perfect_metrics["primary_macro_pre_event_normalized_mae"]
        )
        < 1e-12,
        "biased_primary_metric_is_positive": biased_metrics[
            "primary_macro_pre_event_normalized_mae"
        ]
        > 0,
        "perfect_beats_biased": comparison["candidate_minus_baseline"] < 0,
        "perfect_vs_biased_interval_is_below_zero": comparison[
            "bootstrap_95_percentile_interval"
        ][1]
        < 0,
        "all_four_target_directions_are_correct": sum(
            value < 0 for value in comparison["by_target"].values()
        )
        == 4,
        "all_five_horizon_directions_are_correct": sorted(
            int(value) for value in comparison["by_horizon"].keys()
        )
        == REPORT_HORIZONS
        and sum(value < 0 for value in comparison["by_horizon"].values()) == 5,
        "duplicate_keys_are_rejected": _expect_submission_error(
            lambda: validate_submission(duplicate, keys, contract)
        ),
        "missing_keys_are_rejected": _expect_submission_error(
            lambda: validate_submission(missing, keys, contract)
        ),
        "negative_predictions_are_rejected": _expect_submission_error(
            lambda: validate_submission(negative, keys, contract)
        ),
        "nonfinite_predictions_are_rejected": _expect_submission_error(
            lambda: validate_submission(nonfinite, keys, contract)
        ),
        "partial_uncertainty_is_rejected": _expect_submission_error(
            lambda: validate_submission(partial_uncertainty, keys, contract)
        ),
        "bad_uncertainty_order_is_rejected": _expect_submission_error(
            lambda: validate_submission(bad_uncertainty, keys, contract)
        ),
        "metric_reports_only_frozen_horizons": sorted(
            int(value) for value in perfect_metrics["by_horizon"].keys()
        )
        == REPORT_HORIZONS,
        "metric_reports_all_four_targets": sorted(perfect_metrics["by_target"].keys())
        == sorted(TARGETS),
    }
    checks = {key: bool(value) for key, value in checks.items()}
    passed = all(checks.values())
    report = {
        "schema": "gwm_bench.foundation_v4_evaluator_conformance.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_ACTION_A4_EVALUATOR_CONFORMANCE" if passed else "FAIL",
        "check_count": len(checks),
        "checks": checks,
        "constructed_answer_metrics": {
            "perfect": perfect_metrics["primary_macro_pre_event_normalized_mae"],
            "biased": biased_metrics["primary_macro_pre_event_normalized_mae"],
            "perfect_minus_biased": comparison,
        },
    }
    OUTPUT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"GWM-Bench Foundation V4.0 evaluator: {report['status']}")
    print(f"Conformance report: {OUTPUT_PATH}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
