#!/usr/bin/env python3
"""Test the V3 OBSERVED-O3 evaluator with constructed labels only."""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from observed_o3_evaluator import (
    KEY_COLUMNS,
    PROBABILITY_COLUMNS,
    LabelValidationError,
    SubmissionValidationError,
    evaluate,
)


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
BUNDLE_ROOT = ROOT / "phase_a_bundle"
DEFAULT_OUTPUT = ROOT / "evaluator_conformance_report.json"
TARGET_ROOT = (
    REPO_ROOT
    / "data/twm_public_landcover/gee_dynamic_world_v3_lockbox_targets_2023_2025"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expect_rejection(callback: Callable[[], object], error: type[Exception]) -> bool:
    try:
        callback()
    except error:
        return True
    return False


def _one_hot(keys: pd.DataFrame, classes: np.ndarray) -> pd.DataFrame:
    frame = keys.copy()
    for class_index, column in enumerate(PROBABILITY_COLUMNS):
        frame[column] = (classes == class_index).astype(np.float64)
    return frame


def run(output_path: Path = DEFAULT_OUTPUT) -> dict:
    keys = pd.read_parquet(BUNDLE_ROOT / "submission_keys.parquet")
    inputs = pd.read_parquet(BUNDLE_ROOT / "observed_inputs.parquet")
    origins = inputs[["region_id", "node_id", "land_class_2022"]]
    constructed = keys.merge(origins, on=["region_id", "node_id"], validate="many_to_one")
    node_codes = pd.factorize(
        constructed["region_id"].astype(str) + ":" + constructed["node_id"].astype(str),
        sort=True,
    )[0]
    steps = constructed["target_year"].to_numpy(dtype=np.int64) - 2022
    origin_classes = constructed["land_class_2022"].to_numpy(dtype=np.int64)
    target_classes = (
        origin_classes + ((node_codes + steps) % 3 == 0).astype(np.int64)
    ) % 9
    labels = constructed[KEY_COLUMNS].copy()
    labels["target_class"] = target_classes
    oracle = _one_hot(constructed[KEY_COLUMNS], target_classes)
    persistence_classes = np.repeat(
        inputs.sort_values(["region_id", "node_id"], kind="mergesort")[
            "land_class_2022"
        ].to_numpy(dtype=np.int64),
        3,
    )
    persistence = _one_hot(keys, persistence_classes)

    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="gwm-v3-evaluator-") as directory:
        temporary_root = Path(directory)
        labels_path = temporary_root / "constructed_labels.parquet"
        submission_path = temporary_root / "submission.parquet"
        labels.to_parquet(labels_path, index=False)
        oracle.to_parquet(submission_path, index=False)
        oracle_report = evaluate(
            submission_path=submission_path,
            labels_path=labels_path,
            bundle_root=BUNDLE_ROOT,
        )
        repeated_report = evaluate(
            submission_path=submission_path,
            labels_path=labels_path,
            bundle_root=BUNDLE_ROOT,
        )
        checks["constructed_oracle_scores_perfectly"] = (
            oracle_report["primary_metric"]["value"] == 1.0
            and oracle_report["overall_secondary_metrics"][
                "overall_class_macro_f1"
            ]
            == 1.0
            and oracle_report["overall_secondary_metrics"][
                "multiclass_brier_score"
            ]
            == 0.0
        )
        checks["evaluator_is_deterministic"] = oracle_report == repeated_report

        persistence.to_parquet(submission_path, index=False)
        persistence_report = evaluate(
            submission_path=submission_path,
            labels_path=labels_path,
            bundle_root=BUNDLE_ROOT,
        )
        checks["constructed_persistence_is_not_better_than_oracle"] = (
            persistence_report["primary_metric"]["value"]
            <= oracle_report["primary_metric"]["value"]
            and persistence_report["overall_secondary_metrics"][
                "multiclass_brier_score"
            ]
            >= oracle_report["overall_secondary_metrics"][
                "multiclass_brier_score"
            ]
        )

        def reject_submission(frame: pd.DataFrame) -> bool:
            frame.to_parquet(submission_path, index=False)
            return _expect_rejection(
                lambda: evaluate(
                    submission_path=submission_path,
                    labels_path=labels_path,
                    bundle_root=BUNDLE_ROOT,
                ),
                SubmissionValidationError,
            )

        duplicate = pd.concat([oracle, oracle.iloc[[0]]], ignore_index=True)
        checks["duplicate_submission_key_rejected"] = reject_submission(duplicate)
        checks["missing_submission_key_rejected"] = reject_submission(
            oracle.iloc[1:].copy()
        )
        extra_column = oracle.copy()
        extra_column["unexpected"] = 1
        checks["extra_submission_column_rejected"] = reject_submission(extra_column)
        non_finite = oracle.copy()
        non_finite.loc[non_finite.index[0], PROBABILITY_COLUMNS[0]] = np.nan
        checks["non_finite_probability_rejected"] = reject_submission(non_finite)
        bad_range = oracle.copy()
        bad_range.loc[bad_range.index[0], PROBABILITY_COLUMNS[0]] = -0.01
        checks["out_of_range_probability_rejected"] = reject_submission(bad_range)
        bad_sum = oracle.copy()
        bad_sum.loc[bad_sum.index[0], PROBABILITY_COLUMNS] = [0.1] * 9
        checks["probability_sum_rejected"] = reject_submission(bad_sum)

        oracle.to_parquet(submission_path, index=False)

        def reject_labels(frame: pd.DataFrame) -> bool:
            frame.to_parquet(labels_path, index=False)
            return _expect_rejection(
                lambda: evaluate(
                    submission_path=submission_path,
                    labels_path=labels_path,
                    bundle_root=BUNDLE_ROOT,
                ),
                LabelValidationError,
            )

        duplicate_labels = pd.concat([labels, labels.iloc[[0]]], ignore_index=True)
        checks["duplicate_label_key_rejected"] = reject_labels(duplicate_labels)
        checks["missing_label_key_rejected"] = reject_labels(labels.iloc[1:].copy())
        bad_label = labels.copy()
        bad_label.loc[bad_label.index[0], "target_class"] = 9
        checks["out_of_range_target_class_rejected"] = reject_labels(bad_label)
        extra_label_column = labels.copy()
        extra_label_column["unexpected"] = 1
        checks["extra_label_column_rejected"] = reject_labels(extra_label_column)

        checks["temporary_constructed_labels_removed"] = True

    target_files = (
        [path for path in TARGET_ROOT.rglob("*") if path.is_file()]
        if TARGET_ROOT.exists()
        else []
    )
    checks["real_target_directory_contains_no_files"] = not target_files
    checks["real_target_pixels_not_read"] = True
    report = {
        "schema": "gwm_bench.observed_o3_evaluator_conformance.v1",
        "suite_id": "GWM-BENCH-FOUNDATION-V3.0-DRAFT1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_EVALUATOR_CONFORMANCE"
        if all(checks.values())
        else "FAIL",
        "check_count": len(checks),
        "checks": checks,
        "constructed_row_count": len(labels),
        "constructed_oracle_primary": oracle_report["primary_metric"]["value"],
        "constructed_persistence_primary": persistence_report["primary_metric"][
            "value"
        ],
        "source_artifacts": {
            "evaluator": {
                "path": "benchmarks/gwm_bench_foundation_v3_0_draft/observed_o3_evaluator.py",
                "sha256": _sha256(ROOT / "observed_o3_evaluator.py"),
            },
            "runtime_contract": {
                "path": "benchmarks/gwm_bench_foundation_v3_0_draft/runtime_r2_contract.json",
                "sha256": _sha256(ROOT / "runtime_r2_contract.json"),
            },
            "submission_contract": {
                "path": "benchmarks/gwm_bench_foundation_v3_0_draft/submission_contract.json",
                "sha256": _sha256(ROOT / "submission_contract.json"),
            },
            "bundle_manifest": {
                "path": "benchmarks/gwm_bench_foundation_v3_0_draft/phase_a_bundle/bundle_manifest.json",
                "sha256": _sha256(BUNDLE_ROOT / "bundle_manifest.json"),
            },
        },
        "protocol": {
            "constructed_labels_are_real_lockbox_labels": False,
            "constructed_labels_retained": False,
            "real_target_pixels_read": False,
            "llm_judge_used": False,
        },
    }
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"GWM-Bench V3 evaluator: {report['status']}")
    print(f"Conformance report: {output_path}")
    return report


if __name__ == "__main__":
    result = run()
    raise SystemExit(0 if result["status"] == "PASS_EVALUATOR_CONFORMANCE" else 1)
