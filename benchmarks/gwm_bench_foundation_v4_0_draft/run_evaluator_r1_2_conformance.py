#!/usr/bin/env python3
"""Run 15 frozen checks plus dtype and stable-delegation checks for R1.2."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import action_a4_evaluator as frozen_r1
import run_evaluator_conformance as r1_tests
from action_a4_evaluator_r1_2 import DRAFT_ROOT, validate_submission


OUTPUT_PATH = DRAFT_ROOT / "evaluator_r1_2_conformance_report.json"


def main() -> int:
    original_output = r1_tests.OUTPUT_PATH
    original_validate = r1_tests.validate_submission
    temporary_output = DRAFT_ROOT / "evaluator_r1_2_base15_conformance_report.json"
    r1_tests.OUTPUT_PATH = temporary_output
    r1_tests.validate_submission = validate_submission
    try:
        base_exit = r1_tests.main()
    finally:
        r1_tests.OUTPUT_PATH = original_output
        r1_tests.validate_submission = original_validate

    report = json.loads(temporary_output.read_text(encoding="utf-8"))
    temporary_output.unlink()
    contract = json.loads(
        (DRAFT_ROOT / "submission_contract.json").read_text(encoding="utf-8")
    )
    keys = pd.MultiIndex.from_product(
        [range(1, 264), range(1, 13)],
        names=["zone_id", "horizon_week"],
    ).to_frame(index=False)
    keys["zone_id"] = keys["zone_id"].astype(np.int64)
    keys["horizon_week"] = keys["horizon_week"].astype(np.int16)
    prediction = keys.astype({"zone_id": np.int16, "horizon_week": np.int64})
    for target in ("pickup_count", "dropoff_count", "cbd_inflow", "cbd_outflow"):
        prediction[f"{target}_prediction"] = 1.0
    validated = validate_submission(prediction, keys, contract)
    original_frozen_validate = frozen_r1.validate_submission
    frozen_r1.validate_submission = validate_submission
    try:
        delegated = validate_submission(prediction, keys, contract)
        stable_delegation = len(delegated) == 3156
    finally:
        frozen_r1.validate_submission = original_frozen_validate

    report["schema"] = "gwm_bench.foundation_v4_evaluator_r1_2_conformance.v1"
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    report["checks"]["integer_storage_width_does_not_change_key_identity"] = (
        len(validated) == 3156
        and validated["zone_id"].dtype == np.dtype("int64")
        and validated["horizon_week"].dtype == np.dtype("int64")
    )
    report["checks"]["delegation_remains_stable_while_r1_entry_is_patched"] = (
        stable_delegation
    )
    report["check_count"] = len(report["checks"])
    passed = base_exit == 0 and all(report["checks"].values())
    report["status"] = (
        "PASS_ACTION_A4_EVALUATOR_R1_2_CONFORMANCE" if passed else "FAIL"
    )
    report["erratum_scope"] = (
        "Only key integer widths and stable delegation are addressed; scoring is R1."
    )
    OUTPUT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"GWM-Bench Foundation V4.0 evaluator R1.2: {report['status']}")
    print(f"Conformance report: {OUTPUT_PATH}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
