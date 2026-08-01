#!/usr/bin/env python3
"""Post-hoc score of the sealed D4 boundary rollout on the public D3 window."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROLLOUT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_v2_d4_boundary_rollout_report.json"
)
DEFAULT_OUTCOME_MANIFEST = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d3_inputs/outcome/"
    "acquisition_manifest.json"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_v2_d4_boundary_diagnostic_score.json"
)
SCHEMA = "gwm.geotransport.center_hill_v2_d4_boundary_diagnostic_score.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rollout-report", type=Path, default=DEFAULT_ROLLOUT_REPORT
    )
    parser.add_argument(
        "--outcome-manifest", type=Path, default=DEFAULT_OUTCOME_MANIFEST
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_score(
    *,
    rollout_report_path: Path = DEFAULT_ROLLOUT_REPORT,
    outcome_manifest_path: Path = DEFAULT_OUTCOME_MANIFEST,
) -> dict[str, Any]:
    rollout_body, rollout = _load_json(rollout_report_path)
    if (
        rollout.get("schema")
        != "gwm.geotransport.center_hill_v2_d4_boundary_rollout.v1"
        or rollout.get("status") != "outcome_free_boundary_rollout_complete"
        or (rollout.get("data_isolation") or {}).get("outcome_values_loaded")
        is not False
        or (rollout.get("invariants") or {}).get(
            "d3_mainstem_reference_reproduced"
        )
        is not True
        or (rollout.get("invariants") or {}).get("boundary_conservation_passed")
        is not True
    ):
        raise ValueError("center_hill_d4_diagnostic_rollout_invalid")
    prediction_body = _read_descriptor(rollout["prediction_artifact"])
    prediction_rows = list(
        csv.DictReader(io.StringIO(prediction_body.decode("utf-8")))
    )

    outcome_manifest_body, outcome_manifest = _load_json(outcome_manifest_path)
    if (
        outcome_manifest.get("schema")
        != "gwm.geotransport.center_hill_v2_outcome_input.v1"
        or outcome_manifest.get("variable_role") != "independent_observation"
        or outcome_manifest.get("site_id") != "USGS-03424860"
    ):
        raise ValueError("center_hill_d4_diagnostic_outcome_manifest_invalid")
    outcome_body = _read_descriptor(outcome_manifest["outcome_values"])
    outcomes = _parse_outcomes(outcome_body)

    observed: list[float] = []
    persistence: list[float] = []
    d3_central: list[float] = []
    d4_boundary: list[float] = []
    boundary_input: list[float] = []
    previous = float(outcome_manifest["prior_observation_m3s"])
    for row in prediction_rows:
        support_end = _canonical_utc(row["support_end_utc"])
        if support_end not in outcomes or outcomes[support_end] is None:
            raise ValueError("center_hill_d4_diagnostic_complete_outcome_required")
        value = float(outcomes[support_end])
        observed.append(value)
        persistence.append(previous)
        d3_central.append(float(row["d3_nonlinear_central_reference_m3s"]))
        d4_boundary.append(float(row["d4_modeled_tributary_boundary_m3s"]))
        boundary_input.append(float(row["modeled_tributary_boundary_input_m3s"]))
        previous = value
    if len(observed) != 672:
        raise ValueError("center_hill_d4_diagnostic_hour_count_mismatch")
    observed_values = np.asarray(observed, dtype=float)
    metrics = {
        "persistence": _metrics(observed_values, np.asarray(persistence)),
        "d3_nonlinear_central": _metrics(
            observed_values, np.asarray(d3_central)
        ),
        "d4_modeled_tributary_boundary": _metrics(
            observed_values, np.asarray(d4_boundary)
        ),
    }
    d3 = metrics["d3_nonlinear_central"]
    d4 = metrics["d4_modeled_tributary_boundary"]
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "post_hoc_diagnostic_complete_no_activation_gate",
        "source_artifacts": {
            "sealed_outcome_free_rollout": _artifact(
                rollout_report_path, rollout_body
            ),
            "sealed_predictions": {
                **rollout["prediction_artifact"],
            },
            "outcome_manifest": _artifact(
                outcome_manifest_path, outcome_manifest_body
            ),
            "independent_outcomes": {
                **outcome_manifest["outcome_values"],
            },
        },
        "window_role": {
            "name": "D3 public falsification/development window",
            "prospective_holdout": False,
            "model_selection_allowed": False,
            "parameter_tuning_allowed": False,
            "activation_gate_registered": False,
        },
        "scored_hour_count": len(observed),
        "metrics": metrics,
        "input_side_flux": {
            "modeled_tributary_boundary_mean_m3s": float(
                np.mean(boundary_input)
            ),
            "d3_mean_bias_magnitude_m3s": abs(float(d3["bias_m3s"])),
            "ratio_to_d3_mean_bias_magnitude": float(
                np.mean(boundary_input) / abs(float(d3["bias_m3s"]))
            ),
        },
        "non_gating_diagnostics": {
            "rmse_change_from_d3_m3s": float(
                d4["rmse_m3s"] - d3["rmse_m3s"]
            ),
            "absolute_bias_change_from_d3_m3s": float(
                abs(d4["bias_m3s"]) - abs(d3["bias_m3s"])
            ),
            "d4_beats_d3_central_rmse": (
                d4["rmse_m3s"] < d3["rmse_m3s"]
            ),
            "d4_beats_persistence_rmse": (
                d4["rmse_m3s"] < metrics["persistence"]["rmse_m3s"]
            ),
            "interpretation": (
                "These comparisons diagnose the already public failure window; "
                "they do not validate or select the D4 model."
            ),
        },
        "claim_boundary": {
            "executor_outcome_isolation_verified": True,
            "score_is_post_hoc": True,
            "modeled_boundary_ground_truth": False,
            "modeled_boundary_possible_nudging": True,
            "d4_predictive_improvement_validated": False,
            "full_subnetwork_routing_validated": False,
            "geospatial_kernel_validated": False,
        },
    }


def _metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    error = predicted - observed
    denominator = float(np.sum((observed - float(observed.mean())) ** 2))
    return {
        "rmse_m3s": float(np.sqrt(np.mean(error**2))),
        "mae_m3s": float(np.mean(np.abs(error))),
        "bias_m3s": float(np.mean(error)),
        "nse": float(1.0 - np.sum(error**2) / denominator),
    }


def _parse_outcomes(body: bytes) -> dict[str, float | None]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    if reader.fieldnames != [
        "support_end_utc",
        "observed_discharge_m3s",
        "source_role",
    ]:
        raise ValueError("center_hill_d4_diagnostic_outcome_columns_invalid")
    result: dict[str, float | None] = {}
    for row in reader:
        if row["source_role"] != "independent_observation":
            raise ValueError("center_hill_d4_diagnostic_outcome_role_invalid")
        value = row["observed_discharge_m3s"]
        result[_canonical_utc(row["support_end_utc"])] = (
            None if value == "" else float(value)
        )
    return result


def _canonical_utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("center_hill_d4_diagnostic_timestamp_timezone_required")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_descriptor(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("center_hill_d4_diagnostic_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("center_hill_d4_diagnostic_artifact_identity_mismatch")
    return body


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    return body, json.loads(body)


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
        rollout_report_path=args.rollout_report,
        outcome_manifest_path=args.outcome_manifest,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
