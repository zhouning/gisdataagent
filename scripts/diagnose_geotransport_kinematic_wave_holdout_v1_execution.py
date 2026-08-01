#!/usr/bin/env python3
"""Capture the frozen v1 execution invariant at failure without outcomes."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

if __package__:
    from scripts.freeze_geotransport_kinematic_wave_holdout_v1 import SYSTEM_IDS
    from scripts.run_geotransport_kinematic_wave_holdout_v1_outcome_free import (
        DEFAULT_INPUT_REPORT,
        DEFAULT_OUTPUT,
        DEFAULT_PROTOCOL,
        OUTCOME_ROOT,
        _run_system,
    )
else:
    from freeze_geotransport_kinematic_wave_holdout_v1 import SYSTEM_IDS
    from run_geotransport_kinematic_wave_holdout_v1_outcome_free import (
        DEFAULT_INPUT_REPORT,
        DEFAULT_OUTPUT,
        DEFAULT_PROTOCOL,
        OUTCOME_ROOT,
        _run_system,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "kinematic_wave_holdout_v1_execution_failure.json"
)


def main() -> int:
    if OUTCOME_ROOT.exists():
        raise ValueError("kinematic_holdout_diagnostic_forbidden_after_outcome_access")
    if DEFAULT_REPORT.exists():
        raise ValueError("kinematic_holdout_execution_diagnostic_refuses_overwrite")
    protocol_body = DEFAULT_PROTOCOL.read_bytes()
    input_body = DEFAULT_INPUT_REPORT.read_bytes()
    protocol = json.loads(protocol_body)
    inputs = json.loads(input_body)
    captured: dict[str, Any] = {}
    target_code = _run_system.__code__

    def local_trace(frame, event, argument):
        if event == "exception" and "invariants" in frame.f_locals:
            captured["invariants"] = dict(frame.f_locals["invariants"])
        return local_trace

    def global_trace(frame, event, argument):
        if event == "call" and frame.f_code is target_code:
            return local_trace
        return None

    error: Exception | None = None
    sys.settrace(global_trace)
    try:
        _run_system(
            system_id=SYSTEM_IDS[0],
            lock=protocol["systems"][SYSTEM_IDS[0]],
            inputs=inputs["systems"][SYSTEM_IDS[0]],
            output_path=DEFAULT_OUTPUT / f"{SYSTEM_IDS[0]}.csv",
        )
    except Exception as exc:  # The frozen execution is expected to fail.
        error = exc
    finally:
        sys.settrace(None)
    if error is None or "invariants" not in captured:
        raise RuntimeError("kinematic_holdout_execution_failure_not_captured")
    report = {
        "schema": "gwm.geotransport.kinematic_wave_holdout_execution_failure.v1",
        "status": "frozen_v1_outcome_free_execution_gate_failed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "system_id": SYSTEM_IDS[0],
        "protocol_sha256": hashlib.sha256(protocol_body).hexdigest(),
        "input_report_sha256": hashlib.sha256(input_body).hexdigest(),
        "error_type": type(error).__name__,
        "error": str(error),
        "invariants": captured["invariants"],
        "data_isolation": {
            "prediction_artifact_written": False,
            "outcome_url_requested": False,
            "outcome_path_loaded": False,
            "outcome_values_loaded": False,
        },
        "claim_boundary": {
            "frozen_v1_prediction_sealed": False,
            "outcome_access_permitted": False,
            "v1_gate_passed": False,
            "operator_form_admitted": False,
        },
    }
    DEFAULT_REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(DEFAULT_REPORT)
    print(json.dumps(captured["invariants"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
