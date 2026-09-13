#!/usr/bin/env python3
"""R1.1 erratum wrapper for the sealed ACTION-A4 evaluator.

The R1 evaluator compared pandas integer storage widths with DataFrame.equals,
although the frozen submission contract defines key values, not physical integer
widths. R1.1 normalizes only the two key columns to int64, then delegates every
validation, metric, bootstrap, and gate calculation to the untouched R1 module.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import action_a4_evaluator as frozen_r1


DRAFT_ROOT = frozen_r1.DRAFT_ROOT
DEFAULT_OUTPUT = DRAFT_ROOT / "final_results/action_a4_results.json"
REPORT_HORIZONS = frozen_r1.REPORT_HORIZONS
SubmissionError = frozen_r1.SubmissionError
evaluate_submission = frozen_r1.evaluate_submission
load_json = frozen_r1.load_json
paired_comparison = frozen_r1.paired_comparison


def _normalized_integer_key(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        values = pd.to_numeric(result[column], errors="raise").to_numpy(dtype=np.float64)
        if not np.isfinite(values).all() or not np.equal(values, np.floor(values)).all():
            raise SubmissionError(f"non-integral submission key: {column}")
        result[column] = values.astype(np.int64)
    return result


def validate_submission(
    submission: pd.DataFrame,
    expected_keys: pd.DataFrame,
    contract: dict[str, Any],
) -> pd.DataFrame:
    key_columns = contract["key_columns"]
    missing = [column for column in key_columns if column not in submission.columns]
    if missing:
        return frozen_r1.validate_submission(submission, expected_keys, contract)
    normalized_submission = _normalized_integer_key(submission, key_columns)
    normalized_expected = _normalized_integer_key(expected_keys, key_columns)
    return frozen_r1.validate_submission(
        normalized_submission,
        normalized_expected,
        contract,
    )


def evaluate_manifest(submission_manifest_path: Path) -> dict[str, Any]:
    original = frozen_r1.validate_submission
    frozen_r1.validate_submission = validate_submission
    try:
        report = frozen_r1.evaluate_manifest(submission_manifest_path)
    finally:
        frozen_r1.validate_submission = original
    report["evaluator_revision"] = "R1.1_KEY_DTYPE_ERRATUM"
    report["evaluator_erratum_scope"] = (
        "Normalize zone_id and horizon_week integer storage widths before invoking "
        "the untouched R1 validator; metrics, bootstrap, and gates are unchanged."
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission-manifest", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = evaluate_manifest(args.submission_manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"GWM-Bench Foundation V4.0 ACTION-A4: {report['status']}")
    print(f"Evaluator revision: {report['evaluator_revision']}")
    print(f"Results: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
