#!/usr/bin/env python3
"""Score a sealed Center Hill v2 rollout against an independent outcome file."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping

from data_agent.uwm.geospatial_kernel_v2 import score_holdout_rollout


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_v2_d3_protocol.json"
)
DEFAULT_ROLLOUT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_v2_d3_rollout_report.json"
)
DEFAULT_OUTCOME_MANIFEST = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d3_inputs/outcome/"
    "acquisition_manifest.json"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_v2_d3_scoring_report.json"
)
SCHEMA = "gwm.geotransport.center_hill_v2_d3_scoring.v1"
OUTCOME_MANIFEST_SCHEMA = "gwm.geotransport.center_hill_v2_outcome_input.v1"
ROLLOUT_SCHEMA = "gwm.geotransport.center_hill_v2_outcome_free_rollout.v1"
PROTOCOL_SCHEMA = "gwm.geotransport.center_hill_v2_d3_protocol.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--rollout-report", type=Path, default=DEFAULT_ROLLOUT_REPORT)
    parser.add_argument(
        "--outcome-manifest", type=Path, default=DEFAULT_OUTCOME_MANIFEST
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_score(
    *,
    protocol_path: Path,
    rollout_report_path: Path,
    outcome_manifest_path: Path,
) -> dict[str, Any]:
    protocol_body, protocol = _load_json(protocol_path)
    rollout_body, rollout = _load_json(rollout_report_path)
    outcome_manifest_body, outcome_manifest = _load_json(outcome_manifest_path)
    if protocol.get("schema") != PROTOCOL_SCHEMA or protocol.get("status") != "frozen_before_d3_value_access":
        raise ValueError("center_hill_v2_scoring_protocol_invalid")
    if rollout.get("schema") != ROLLOUT_SCHEMA:
        raise ValueError("center_hill_v2_scoring_rollout_invalid")
    if (rollout.get("data_isolation") or {}).get("outcome_values_loaded") is not False:
        raise ValueError("center_hill_v2_scoring_rollout_not_outcome_free")
    if outcome_manifest.get("schema") != OUTCOME_MANIFEST_SCHEMA:
        raise ValueError("center_hill_v2_outcome_manifest_invalid")
    if outcome_manifest.get("variable_role") != "independent_observation":
        raise ValueError("center_hill_v2_outcome_role_invalid")
    if outcome_manifest.get("site_id") != "USGS-03424860":
        raise ValueError("center_hill_v2_outcome_site_invalid")

    prediction_descriptor = rollout["prediction_artifact"]
    prediction_body = _read_verified(prediction_descriptor)
    outcome_descriptor = outcome_manifest["outcome_values"]
    outcome_body = _read_verified(outcome_descriptor)
    prediction_rows = list(csv.DictReader(io.StringIO(prediction_body.decode("utf-8"))))
    outcomes = _parse_outcomes(outcome_body)
    score = score_holdout_rollout(
        prediction_rows,
        outcomes,
        prior_observation_m3s=float(outcome_manifest["prior_observation_m3s"]),
        nonlinear_conservation=rollout["nonlinear_conservation"],
        minimum_scored_hours=int(protocol["scoring"]["minimum_scored_hours"]),
    )
    registered = protocol["gates"]
    if tuple(score["registered_gates"]) != tuple(registered):
        raise ValueError("center_hill_v2_scoring_gate_set_mismatch")
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
    }


def _parse_outcomes(body: bytes) -> dict[str, float | None]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    if reader.fieldnames != [
        "support_end_utc",
        "observed_discharge_m3s",
        "source_role",
    ]:
        raise ValueError("center_hill_v2_outcome_columns_invalid")
    result: dict[str, float | None] = {}
    for row in reader:
        if row["source_role"] != "independent_observation":
            raise ValueError("center_hill_v2_outcome_row_role_invalid")
        value = row["observed_discharge_m3s"]
        result[row["support_end_utc"]] = None if value == "" else float(value)
    if len(result) != 672:
        raise ValueError("center_hill_v2_outcome_time_axis_mismatch")
    return result


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    return body, json.loads(body)


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("center_hill_v2_scoring_artifact_outside_repository") from exc
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != descriptor.get("sha256") or len(body) != descriptor.get("size_bytes"):
        raise ValueError("center_hill_v2_scoring_artifact_identity_mismatch")
    return body


def _artifact_from_descriptor(descriptor: Mapping[str, Any], body: bytes) -> dict[str, Any]:
    return {
        "path": str(descriptor["path"]),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        display = resolved.as_posix()
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def main() -> int:
    args = parse_args()
    report = compile_score(
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
