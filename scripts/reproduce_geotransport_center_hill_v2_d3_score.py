#!/usr/bin/env python3
"""Reproduce D3 scoring with non-scientific serialization normalization."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import score_holdout_rollout
from scripts.score_geotransport_center_hill_v2_holdout import (
    DEFAULT_OUTCOME_MANIFEST,
    DEFAULT_PROTOCOL,
    DEFAULT_REPORT,
    DEFAULT_ROLLOUT_REPORT,
    OUTCOME_MANIFEST_SCHEMA,
    PROTOCOL_SCHEMA,
    ROLLOUT_SCHEMA,
    SCHEMA,
    _artifact,
    _artifact_from_descriptor,
    _load_json,
    _parse_outcomes,
    _read_verified,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--rollout-report", type=Path, default=DEFAULT_ROLLOUT_REPORT)
    parser.add_argument(
        "--outcome-manifest", type=Path, default=DEFAULT_OUTCOME_MANIFEST
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_reproduced_score(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    rollout_report_path: Path = DEFAULT_ROLLOUT_REPORT,
    outcome_manifest_path: Path = DEFAULT_OUTCOME_MANIFEST,
) -> dict[str, Any]:
    protocol_body, protocol = _load_json(protocol_path)
    rollout_body, rollout = _load_json(rollout_report_path)
    outcome_manifest_body, outcome_manifest = _load_json(outcome_manifest_path)
    if (
        protocol.get("schema") != PROTOCOL_SCHEMA
        or protocol.get("status") != "frozen_before_d3_value_access"
    ):
        raise ValueError("center_hill_v2_reproduction_protocol_invalid")
    if (
        rollout.get("schema") != ROLLOUT_SCHEMA
        or (rollout.get("data_isolation") or {}).get("outcome_values_loaded")
        is not False
    ):
        raise ValueError("center_hill_v2_reproduction_rollout_invalid")
    if (
        outcome_manifest.get("schema") != OUTCOME_MANIFEST_SCHEMA
        or outcome_manifest.get("variable_role") != "independent_observation"
        or outcome_manifest.get("site_id") != "USGS-03424860"
    ):
        raise ValueError("center_hill_v2_reproduction_outcome_invalid")

    prediction_descriptor = rollout["prediction_artifact"]
    prediction_body = _read_verified(prediction_descriptor)
    outcome_descriptor = outcome_manifest["outcome_values"]
    outcome_body = _read_verified(outcome_descriptor)
    prediction_rows = list(csv.DictReader(io.StringIO(prediction_body.decode("utf-8"))))
    outcomes = {
        _canonical_utc(key): value
        for key, value in _parse_outcomes(outcome_body).items()
    }
    score = score_holdout_rollout(
        prediction_rows,
        outcomes,
        prior_observation_m3s=float(outcome_manifest["prior_observation_m3s"]),
        nonlinear_conservation=rollout["nonlinear_conservation"],
        minimum_scored_hours=int(protocol["scoring"]["minimum_scored_hours"]),
    )
    if set(score["registered_gates"]) != set(protocol["gates"]):
        raise ValueError("center_hill_v2_reproduction_gate_set_mismatch")
    return {
        "schema": SCHEMA,
        "status": score["status"],
        "source_artifacts": {
            "frozen_protocol": _artifact(protocol_path, protocol_body),
            "outcome_free_rollout_report": _artifact(
                rollout_report_path, rollout_body
            ),
            "outcome_manifest": _artifact(
                outcome_manifest_path, outcome_manifest_body
            ),
            "predictions": _artifact_from_descriptor(
                prediction_descriptor, prediction_body
            ),
            "independent_outcomes": _artifact_from_descriptor(
                outcome_descriptor, outcome_body
            ),
        },
        "evaluation": score,
        "claim_boundary": {
            "protocol_frozen_before_d3_value_access": True,
            "executor_outcome_isolation_verified": True,
            "single_system_registered_gates_passed": score["status"] == "pass",
            "multi_system_geospatial_kernel_validated": False,
        },
        "runtime_adapters": {
            "iso8601_utc_canonicalization": (
                "outcome Z and prediction +00:00 normalized to identical UTC instants"
            ),
            "json_gate_mapping_comparison": (
                "mapping keys compared in frozen scientific gate order; JSON "
                "serialization order ignored"
            ),
            "prediction_values_changed": False,
            "outcome_values_changed": False,
            "metrics_or_thresholds_changed": False,
        },
    }


def _canonical_utc(value: str) -> str:
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        .astimezone(timezone.utc)
        .isoformat()
    )


def main() -> int:
    args = parse_args()
    report = compile_reproduced_score(
        protocol_path=args.protocol,
        rollout_report_path=args.rollout_report,
        outcome_manifest_path=args.outcome_manifest,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
