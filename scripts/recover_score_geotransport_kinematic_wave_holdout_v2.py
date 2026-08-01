#!/usr/bin/env python3
"""Score v2 while preserving finite approved negative USGS discharge."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

if __package__:
    import scripts.score_geotransport_kinematic_wave_holdout_v1 as base
    import scripts.score_geotransport_kinematic_wave_holdout_v2 as v2
else:
    import score_geotransport_kinematic_wave_holdout_v1 as base
    import score_geotransport_kinematic_wave_holdout_v2 as v2


REPO_ROOT = Path(__file__).resolve().parents[1]
RECOVERY_ADR = REPO_ROOT / (
    "docs/architecture-decisions/"
    "adr-035-kinematic-wave-holdout-v2-approved-negative-discharge.md"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=v2.DEFAULT_PROTOCOL)
    parser.add_argument("--rollout", type=Path, default=v2.DEFAULT_ROLLOUT)
    parser.add_argument("--outcomes", type=Path, default=v2.DEFAULT_OUTCOMES)
    parser.add_argument("--report", type=Path, default=v2.DEFAULT_REPORT)
    return parser.parse_args()


def _finite_outcome_values(body: bytes) -> dict[str, float | None]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    expected = [
        "support_end_utc",
        "observed_discharge_m3s",
        "source_role",
        "evaluation_role",
    ]
    if reader.fieldnames != expected:
        raise ValueError("kinematic_holdout_recovery_outcome_columns_invalid")
    result: dict[str, float | None] = {}
    roles: list[str] = []
    for row in reader:
        if row["source_role"] != "independent_observation":
            raise ValueError("kinematic_holdout_recovery_outcome_role_invalid")
        key = base._canonical_utc(row["support_end_utc"])
        if key in result:
            raise ValueError("kinematic_holdout_recovery_outcome_duplicate_timestamp")
        value = (
            None
            if row["observed_discharge_m3s"] == ""
            else float(row["observed_discharge_m3s"])
        )
        if value is not None and not np.isfinite(value):
            raise ValueError("kinematic_holdout_recovery_outcome_value_nonfinite")
        result[key] = value
        roles.append(row["evaluation_role"])
    expected_axis = {
        base._iso(base.START + base.timedelta(hours=index))
        for index in range(base.HOUR_COUNT + 1)
    }
    if (
        set(result) != expected_axis
        or roles[0] != "persistence_prior"
        or any(value != "target" for value in roles[1:])
    ):
        raise ValueError("kinematic_holdout_recovery_outcome_axis_invalid")
    return result


def compile_score(
    *, protocol_path: Path, rollout_path: Path, outcomes_path: Path
) -> dict[str, Any]:
    original = base._outcome_values
    base._outcome_values = _finite_outcome_values
    try:
        report = v2.compile_score(
            protocol_path=protocol_path,
            rollout_path=rollout_path,
            outcomes_path=outcomes_path,
        )
    finally:
        base._outcome_values = original
    predictive_gate = report["multi_system_gates"][
        "both_systems_predictive_and_execution_gates_passed"
    ]
    report["multi_system_gates"]["strict_protocol_conformance_passed"] = False
    report["multi_system_gates"]["prospective_holdout_gate_passed"] = False
    report["protocol_conformance"].update(
        {
            "strict_protocol_conformance_passed": False,
            "post_outcome_acquisition_recovery_required": True,
            "post_outcome_scoring_recovery_required": True,
            "prediction_metric_baseline_or_gate_changed": False,
            "deviation": (
                "Frozen acquisition rejected a missing persistence prior despite "
                "the omit-without-imputation policy; frozen scoring rejected "
                "finite approved negative USGS discharge. Recovery preserved "
                "missingness and all published finite values unchanged."
            ),
        }
    )
    report["operator_admission"].update(
        {
            "holdout_gate_passed": False,
            "raw_predictive_gate_passed": predictive_gate,
            "current_role": "diagnostic_geospatial_kernel_candidate",
        }
    )
    report["claim_boundary"].update(
        {
            "predictive_gate_passed": predictive_gate,
            "prospective_holdout_gate_passed": False,
            "strict_end_to_end_protocol_conformance": False,
            "operator_form_admitted": False,
            "geospatial_kernel_validated": False,
        }
    )
    report["score_recovery"] = {
        "frozen_scorer_wrote_score_before_failure": False,
        "frozen_scorer_error": "kinematic_holdout_outcome_value_invalid",
        "recovery_code_frozen_before_outcome_access": False,
        "approved_negative_values_preserved": True,
        "negative_values_clipped_omitted_or_imputed": False,
        "prediction_values_changed": False,
        "evaluation_mask_metric_baseline_or_gate_changed": False,
        "recovery_decision": _artifact(RECOVERY_ADR),
    }
    return report


def _artifact(path: Path) -> dict[str, Any]:
    body = path.read_bytes()
    return {
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def main() -> int:
    args = parse_args()
    if args.report.exists():
        raise ValueError("kinematic_holdout_v2_recovery_score_already_exists")
    report = compile_score(
        protocol_path=args.protocol,
        rollout_path=args.rollout,
        outcomes_path=args.outcomes,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.report)
    for system_id in base.SYSTEM_IDS:
        system = report["systems"][system_id]
        metrics = system["metrics"]
        print(f"{system_id}_scored_hours={system['scored_hour_count']}")
        print(
            f"{system_id}_kinematic_rmse_m3s="
            f"{metrics['kinematic_wave']['rmse_m3s']}"
        )
        print(
            f"{system_id}_persistence_rmse_m3s="
            f"{metrics['observed_persistence']['rmse_m3s']}"
        )
        print(
            f"{system_id}_raw_gate="
            f"{system['gates']['all_predictive_and_execution_gates_passed']}"
        )
    print(
        "raw_two_system_predictive_gate="
        f"{report['multi_system_gates']['both_systems_predictive_and_execution_gates_passed']}"
    )
    print("prospective_holdout_gate_passed=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
