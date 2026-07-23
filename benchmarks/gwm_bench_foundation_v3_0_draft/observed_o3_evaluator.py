#!/usr/bin/env python3
"""Reference evaluator for V3 OBSERVED-O3 geographic transfer submissions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
BUNDLE_ROOT = ROOT / "phase_a_bundle"
KEY_COLUMNS = ["region_id", "node_id", "target_year"]
PROBABILITY_COLUMNS = [f"probability_{index}" for index in range(9)]
SUBMISSION_COLUMNS = KEY_COLUMNS + PROBABILITY_COLUMNS
LABEL_COLUMNS = KEY_COLUMNS + ["target_class"]


class SubmissionValidationError(ValueError):
    pass


class LabelValidationError(ValueError):
    pass


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


def _validate_exact_keys(frame: pd.DataFrame, expected: pd.DataFrame, *, kind: str) -> None:
    if frame.duplicated(KEY_COLUMNS).any():
        error = "duplicate_submission_keys" if kind == "submission" else "duplicate_label_keys"
        raise SubmissionValidationError(error) if kind == "submission" else LabelValidationError(error)
    expected_index = pd.MultiIndex.from_frame(expected[KEY_COLUMNS])
    observed_index = pd.MultiIndex.from_frame(frame[KEY_COLUMNS])
    missing = expected_index.difference(observed_index)
    extra = observed_index.difference(expected_index)
    if len(missing) or len(extra) or len(expected_index) != len(observed_index):
        message = f"{kind}_key_mismatch:missing={len(missing)}:extra={len(extra)}"
        raise SubmissionValidationError(message) if kind == "submission" else LabelValidationError(message)


def _validate_submission(frame: pd.DataFrame, expected: pd.DataFrame) -> pd.DataFrame:
    if list(frame.columns) != SUBMISSION_COLUMNS:
        raise SubmissionValidationError("submission_columns_not_exact")
    _validate_exact_keys(frame, expected, kind="submission")
    try:
        probabilities = frame[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise SubmissionValidationError("probabilities_must_be_numeric") from exc
    if not np.isfinite(probabilities).all():
        raise SubmissionValidationError("non_finite_probability")
    if np.any((probabilities < 0.0) | (probabilities > 1.0)):
        raise SubmissionValidationError("probability_outside_zero_one")
    if not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-6, rtol=0.0):
        raise SubmissionValidationError("probability_rows_must_sum_to_one")
    return frame


def _validate_labels(frame: pd.DataFrame, expected: pd.DataFrame) -> pd.DataFrame:
    if list(frame.columns) != LABEL_COLUMNS:
        raise LabelValidationError("label_columns_not_exact")
    _validate_exact_keys(frame, expected, kind="label")
    targets = frame["target_class"].to_numpy()
    if not np.isfinite(targets.astype(np.float64)).all():
        raise LabelValidationError("non_finite_target_class")
    if not np.equal(targets, targets.astype(np.int64)).all() or np.any(
        (targets < 0) | (targets > 8)
    ):
        raise LabelValidationError("target_class_outside_zero_eight")
    return frame.assign(target_class=targets.astype(np.int64))


def _score_group(group: pd.DataFrame) -> dict[str, Any]:
    predicted_change = group["predicted_change"].to_numpy(dtype=bool)
    observed_change = group["observed_change"].to_numpy(dtype=bool)
    predicted_class = group["predicted_class"].to_numpy(dtype=np.int64)
    target_class = group["target_class"].to_numpy(dtype=np.int64)
    probabilities = group[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64)
    targets = np.eye(9, dtype=np.float64)[target_class]
    observed_changed_count = int(observed_change.sum())
    predicted_changed_count = int(predicted_change.sum())
    return {
        "row_count": len(group),
        "observed_changed_count": observed_changed_count,
        "predicted_changed_count": predicted_changed_count,
        "change_f1": _binary_f1(predicted_change, observed_change),
        "changed_destination_macro_f1": (
            _macro_f1(predicted_class[observed_change], target_class[observed_change])
            if observed_changed_count
            else 1.0
        ),
        "overall_class_macro_f1": _macro_f1(predicted_class, target_class),
        "multiclass_brier_score": float(
            np.mean(np.sum(np.square(probabilities - targets), axis=1))
        ),
        "predicted_to_observed_change_ratio": (
            predicted_changed_count / observed_changed_count
            if observed_changed_count
            else None
        ),
    }


def evaluate(
    *,
    submission_path: Path,
    labels_path: Path,
    bundle_root: Path = BUNDLE_ROOT,
) -> dict[str, Any]:
    expected_keys = pd.read_parquet(bundle_root / "submission_keys.parquet")
    inputs = pd.read_parquet(bundle_root / "observed_inputs.parquet")
    submission = _validate_submission(pd.read_parquet(submission_path), expected_keys)
    labels = _validate_labels(pd.read_parquet(labels_path), expected_keys)
    scored = labels.merge(submission, on=KEY_COLUMNS, validate="one_to_one", sort=True)
    origins = inputs[["region_id", "node_id", "land_class_2022"]].rename(
        columns={"land_class_2022": "origin_class"}
    )
    scored = scored.merge(origins, on=["region_id", "node_id"], validate="many_to_one")
    scored = scored.sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
    scored["predicted_class"] = np.argmax(
        scored[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64), axis=1
    ).astype(np.int64)
    predicted_change = np.zeros(len(scored), dtype=bool)
    observed_change = np.zeros(len(scored), dtype=bool)
    for _, indices in scored.groupby(["region_id", "node_id"], sort=False).indices.items():
        positions = np.asarray(indices, dtype=np.int64)
        years = scored.iloc[positions]["target_year"].to_numpy(dtype=np.int64)
        if not np.array_equal(years, np.array([2023, 2024, 2025])):
            raise ValueError("each_node_requires_exact_2023_2025_targets")
        previous_predicted = int(scored.iloc[positions[0]]["origin_class"])
        previous_observed = previous_predicted
        for position in positions:
            predicted = int(scored.iloc[position]["predicted_class"])
            observed = int(scored.iloc[position]["target_class"])
            predicted_change[position] = predicted != previous_predicted
            observed_change[position] = observed != previous_observed
            previous_predicted = predicted
            previous_observed = observed
    scored["predicted_change"] = predicted_change
    scored["observed_change"] = observed_change

    by_region_horizon = [
        {"region_id": region_id, "target_year": int(year), **_score_group(group)}
        for (region_id, year), group in scored.groupby(
            ["region_id", "target_year"], sort=True
        )
    ]
    if len(by_region_horizon) != 60:
        raise ValueError("expected_exactly_60_region_horizon_groups")
    by_region = [
        {"region_id": region_id, **_score_group(group)}
        for region_id, group in scored.groupby("region_id", sort=True)
    ]
    by_horizon = [
        {"target_year": int(year), **_score_group(group)}
        for year, group in scored.groupby("target_year", sort=True)
    ]
    return {
        "schema": "gwm_bench.observed_o3_evaluation.v1",
        "suite_id": "GWM-BENCH-FOUNDATION-V3.0-DRAFT1",
        "track_id": "OBSERVED-O3",
        "submission_valid": True,
        "primary_metric": {
            "name": "unweighted_mean_region_horizon_change_f1",
            "value": float(np.mean([row["change_f1"] for row in by_region_horizon])),
            "component_count": 60,
            "aggregation": "unweighted_mean",
        },
        "overall_secondary_metrics": _score_group(scored),
        "metrics_by_region_horizon": by_region_horizon,
        "metrics_by_region": by_region,
        "metrics_by_horizon": by_horizon,
        "single_composite_score": False,
        "metric_definitions": {
            "predicted_change": "class differs from the preceding predicted class; 2023 uses observed 2022 origin",
            "observed_change": "class differs from the preceding observed class; 2023 uses observed 2022 origin",
            "zero_denominator_f1": 1.0,
            "argmax_tie_break": "lowest class index",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--bundle-root", type=Path, default=BUNDLE_ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(
        submission_path=args.submission,
        labels_path=args.labels,
        bundle_root=args.bundle_root,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
