#!/usr/bin/env python3
"""Strict reference evaluator for OBSERVED-O1 unseen-region rollouts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BENCHMARK_ROOT = Path(__file__).resolve().parent
DEFAULT_LABELS = BENCHMARK_ROOT / "development/observed_labels.parquet"
KEY_COLUMNS = ["fold_index", "region_id", "node_id", "target_year"]
PROBABILITY_COLUMNS = [f"probability_{index}" for index in range(9)]


class SubmissionValidationError(ValueError):
    """Raised when a submission does not exactly satisfy the frozen schema."""


def _binary_f1(predicted: np.ndarray, observed: np.ndarray) -> float:
    true_positive = int(np.sum(predicted & observed))
    false_positive = int(np.sum(predicted & ~observed))
    false_negative = int(np.sum(~predicted & observed))
    denominator = 2 * true_positive + false_positive + false_negative
    return 2 * true_positive / denominator if denominator else 1.0


def _macro_f1(predicted: np.ndarray, observed: np.ndarray) -> float:
    scores = []
    for class_index in sorted(set(predicted.tolist()) | set(observed.tolist())):
        predicted_class = predicted == class_index
        observed_class = observed == class_index
        true_positive = int(np.sum(predicted_class & observed_class))
        false_positive = int(np.sum(predicted_class & ~observed_class))
        false_negative = int(np.sum(~predicted_class & observed_class))
        denominator = 2 * true_positive + false_positive + false_negative
        if denominator:
            scores.append(2 * true_positive / denominator)
    return float(np.mean(scores)) if scores else 1.0


def _score_group(group: pd.DataFrame) -> dict[str, Any]:
    predicted_change = group["predicted_change"].to_numpy(dtype=bool)
    observed_change = group["changed_from_previous_observed_year"].to_numpy(
        dtype=bool
    )
    predicted_class = group["predicted_class"].to_numpy(dtype=np.int64)
    target_class = group["target_class"].to_numpy(dtype=np.int64)
    probabilities = group[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64)
    targets = np.eye(9, dtype=np.float64)[target_class]
    changed_count = int(observed_change.sum())
    return {
        "row_count": int(len(group)),
        "observed_changed_count": changed_count,
        "predicted_changed_count": int(predicted_change.sum()),
        "change_f1": _binary_f1(predicted_change, observed_change),
        "changed_destination_macro_f1": _macro_f1(
            predicted_class[observed_change], target_class[observed_change]
        )
        if changed_count
        else 1.0,
        "overall_class_macro_f1": _macro_f1(predicted_class, target_class),
        "multiclass_brier_score": float(
            np.mean(np.sum(np.square(probabilities - targets), axis=1))
        ),
    }


def _validate_submission(
    submission: pd.DataFrame, labels: pd.DataFrame
) -> pd.DataFrame:
    expected_columns = KEY_COLUMNS + PROBABILITY_COLUMNS
    if list(submission.columns) != expected_columns:
        raise SubmissionValidationError(
            f"submission_columns_must_be_exactly:{','.join(expected_columns)}"
        )
    if submission.duplicated(KEY_COLUMNS).any():
        raise SubmissionValidationError("duplicate_submission_keys")
    expected_keys = pd.MultiIndex.from_frame(labels[KEY_COLUMNS])
    observed_keys = pd.MultiIndex.from_frame(submission[KEY_COLUMNS])
    missing = expected_keys.difference(observed_keys)
    extra = observed_keys.difference(expected_keys)
    if len(missing) or len(extra) or len(expected_keys) != len(observed_keys):
        raise SubmissionValidationError(
            f"submission_key_mismatch:missing={len(missing)}:extra={len(extra)}"
        )
    try:
        probabilities = submission[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise SubmissionValidationError("probabilities_must_be_numeric") from exc
    if not np.isfinite(probabilities).all():
        raise SubmissionValidationError("non_finite_probability")
    if np.any((probabilities < 0.0) | (probabilities > 1.0)):
        raise SubmissionValidationError("probability_outside_zero_one")
    if not np.allclose(
        probabilities.sum(axis=1), 1.0, atol=1e-6, rtol=0.0
    ):
        raise SubmissionValidationError("probability_rows_must_sum_to_one")
    return labels.merge(
        submission, on=KEY_COLUMNS, validate="one_to_one", sort=True
    )


def _attach_recursive_change_predictions(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.sort_values(
        ["fold_index", "region_id", "node_id", "target_year"], kind="mergesort"
    ).copy()
    probabilities = frame[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64)
    frame["predicted_class"] = np.argmax(probabilities, axis=1).astype(np.int64)
    predicted_change = np.zeros(len(frame), dtype=bool)
    for _, indices in frame.groupby(
        ["fold_index", "region_id", "node_id"], sort=False
    ).indices.items():
        ordered_indices = np.asarray(indices, dtype=np.int64)
        years = frame.iloc[ordered_indices]["target_year"].to_numpy(dtype=np.int64)
        if not np.array_equal(years, np.array([2021, 2022, 2023])):
            raise ValueError("reference_node_must_have_exact_2021_2023_targets")
        predicted_classes = frame.iloc[ordered_indices]["predicted_class"].to_numpy(
            dtype=np.int64
        )
        origin_classes = frame.iloc[ordered_indices]["origin_class"].to_numpy(
            dtype=np.int64
        )
        if len(set(origin_classes.tolist())) != 1:
            raise ValueError("origin_class_must_be_constant_per_node")
        previous = int(origin_classes[0])
        for positional_index, predicted_class in zip(
            ordered_indices, predicted_classes
        ):
            predicted_change[positional_index] = int(predicted_class) != previous
            previous = int(predicted_class)
    frame["predicted_change"] = predicted_change
    return frame


def evaluate_observed_submission(
    *, submission_path: Path, labels_path: Path = DEFAULT_LABELS
) -> dict[str, Any]:
    labels = pd.read_parquet(labels_path)
    labels = labels[labels["split"] == "test"].copy()
    if labels.empty:
        raise ValueError("test_labels_are_empty")
    if labels.duplicated(KEY_COLUMNS).any():
        raise ValueError("reference_labels_have_duplicate_keys")
    submission = pd.read_parquet(submission_path)
    scored = _attach_recursive_change_predictions(
        _validate_submission(submission, labels)
    )

    by_fold_horizon = []
    for (fold_index, target_year), group in scored.groupby(
        ["fold_index", "target_year"], sort=True
    ):
        by_fold_horizon.append(
            {
                "fold_index": int(fold_index),
                "target_year": int(target_year),
                **_score_group(group),
            }
        )
    if len(by_fold_horizon) != 15:
        raise ValueError("expected_exactly_15_fold_horizon_groups")
    by_horizon = [
        {"target_year": int(target_year), **_score_group(group)}
        for target_year, group in scored.groupby("target_year", sort=True)
    ]
    by_region = [
        {"region_id": region_id, **_score_group(group)}
        for region_id, group in scored.groupby("region_id", sort=True)
    ]
    overall = _score_group(scored)
    primary = float(np.mean([row["change_f1"] for row in by_fold_horizon]))
    return {
        "schema": "gwm_bench.observed_evaluation.v1",
        "benchmark_id": "gwm-bench-foundation-v0.1",
        "track_id": "OBSERVED-O1",
        "scored_split": "test",
        "submission_valid": True,
        "primary_metric": {
            "name": "mean_fold_horizon_change_f1",
            "value": primary,
            "component_count": 15,
            "aggregation": "unweighted_mean",
        },
        "overall_secondary_metrics": overall,
        "metrics_by_fold_horizon": by_fold_horizon,
        "metrics_by_horizon": by_horizon,
        "metrics_by_region": by_region,
        "single_composite_score": False,
        "metric_definitions": {
            "predicted_class": "argmax with lowest-class-index tie break",
            "predicted_change": (
                "argmax class differs from preceding predicted class; 2021 uses "
                "the observed 2020 origin class"
            ),
            "observed_change": "target differs from preceding observed year",
            "multiclass_brier_score": (
                "mean row-wise sum of squared nine-class probability error"
            ),
            "zero_denominator_f1": 1.0,
        },
        "claim_boundary": {
            "real_action_conditioning_supported": False,
            "causal_policy_effect_supported": False,
            "operational_forecasting_supported": False,
            "general_gwm_supported": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate_observed_submission(
        submission_path=args.submission, labels_path=args.labels
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
