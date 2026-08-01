#!/usr/bin/env python3
"""Post-hoc score of the sealed D5 full-subnetwork rollout on the D3 window."""

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
    "center_hill_v2_d5_full_subnetwork_rollout_report.json"
)
DEFAULT_OUTCOME_MANIFEST = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d3_inputs/outcome/"
    "acquisition_manifest.json"
)
DEFAULT_D4_SCORE = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_v2_d4_boundary_diagnostic_score.json"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_v2_d5_full_subnetwork_diagnostic_score.json"
)
SCHEMA = "gwm.geotransport.center_hill_v2_d5_full_subnetwork_diagnostic_score.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rollout-report", type=Path, default=DEFAULT_ROLLOUT_REPORT)
    parser.add_argument(
        "--outcome-manifest", type=Path, default=DEFAULT_OUTCOME_MANIFEST
    )
    parser.add_argument("--d4-score", type=Path, default=DEFAULT_D4_SCORE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_score(
    *,
    rollout_report_path: Path = DEFAULT_ROLLOUT_REPORT,
    outcome_manifest_path: Path = DEFAULT_OUTCOME_MANIFEST,
    d4_score_path: Path = DEFAULT_D4_SCORE,
) -> dict[str, Any]:
    rollout_body, rollout = _load_json(rollout_report_path)
    if (
        rollout.get("schema")
        != "gwm.geotransport.center_hill_v2_d5_full_subnetwork_rollout.v1"
        or rollout.get("status")
        != "outcome_free_full_subnetwork_rollout_complete"
        or (rollout.get("data_isolation") or {}).get("outcome_values_loaded")
        is not False
        or (rollout.get("invariants") or {}).get("actual_conservation_passed")
        is not True
        or (rollout.get("invariants") or {}).get(
            "branch_silent_conservation_passed"
        )
        is not True
        or (rollout.get("claim_boundary") or {}).get(
            "outcome_free_prediction_sealed"
        )
        is not True
    ):
        raise ValueError("center_hill_d5_diagnostic_rollout_invalid")
    prediction_body = _read_descriptor(rollout["prediction_artifact"])
    prediction_rows = list(
        csv.DictReader(io.StringIO(prediction_body.decode("utf-8")))
    )
    expected_columns = [
        "support_start_utc",
        "support_end_utc",
        "d5_full_subnetwork_m3s",
        "d5_branch_silent_negative_control_m3s",
        "action_input_m3s",
        "distributed_q_lateral_input_m3s",
        "branch_q_lateral_input_m3s",
    ]
    if not prediction_rows or list(prediction_rows[0]) != expected_columns:
        raise ValueError("center_hill_d5_diagnostic_prediction_columns_invalid")

    outcome_manifest_body, outcome_manifest = _load_json(outcome_manifest_path)
    if (
        outcome_manifest.get("schema")
        != "gwm.geotransport.center_hill_v2_outcome_input.v1"
        or outcome_manifest.get("variable_role") != "independent_observation"
        or outcome_manifest.get("site_id") != "USGS-03424860"
    ):
        raise ValueError("center_hill_d5_diagnostic_outcome_manifest_invalid")
    outcome_body = _read_descriptor(outcome_manifest["outcome_values"])
    outcomes = _parse_outcomes(outcome_body)

    d4_score_body, d4_score = _load_json(d4_score_path)
    if (
        d4_score.get("schema")
        != "gwm.geotransport.center_hill_v2_d4_boundary_diagnostic_score.v1"
        or d4_score.get("status")
        != "post_hoc_diagnostic_complete_no_activation_gate"
        or (d4_score.get("window_role") or {}).get("model_selection_allowed")
        is not False
    ):
        raise ValueError("center_hill_d5_diagnostic_d4_score_invalid")

    observed: list[float] = []
    persistence: list[float] = []
    branch_silent: list[float] = []
    full_subnetwork: list[float] = []
    q_lateral_total: list[float] = []
    q_lateral_branch: list[float] = []
    previous = float(outcome_manifest["prior_observation_m3s"])
    for row in prediction_rows:
        support_end = _canonical_utc(row["support_end_utc"])
        if support_end not in outcomes or outcomes[support_end] is None:
            raise ValueError("center_hill_d5_diagnostic_complete_outcome_required")
        value = float(outcomes[support_end])
        observed.append(value)
        persistence.append(previous)
        branch_silent.append(
            float(row["d5_branch_silent_negative_control_m3s"])
        )
        full_subnetwork.append(float(row["d5_full_subnetwork_m3s"]))
        q_lateral_total.append(float(row["distributed_q_lateral_input_m3s"]))
        q_lateral_branch.append(float(row["branch_q_lateral_input_m3s"]))
        previous = value
    if len(observed) != 672:
        raise ValueError("center_hill_d5_diagnostic_hour_count_mismatch")
    observed_values = np.asarray(observed, dtype=float)
    metrics = {
        "persistence": _metrics(observed_values, np.asarray(persistence)),
        "d5_branch_silent_negative_control": _metrics(
            observed_values, np.asarray(branch_silent)
        ),
        "d5_full_subnetwork": _metrics(
            observed_values, np.asarray(full_subnetwork)
        ),
    }
    d4_metrics = d4_score["metrics"]["d4_modeled_tributary_boundary"]
    d5_metrics = metrics["d5_full_subnetwork"]
    silent_metrics = metrics["d5_branch_silent_negative_control"]
    persistence_metrics = metrics["persistence"]
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "post_hoc_diagnostic_complete_no_activation_gate",
        "source_artifacts": {
            "sealed_outcome_free_rollout": _artifact(
                rollout_report_path, rollout_body
            ),
            "sealed_predictions": {**rollout["prediction_artifact"]},
            "outcome_manifest": _artifact(
                outcome_manifest_path, outcome_manifest_body
            ),
            "independent_outcomes": {**outcome_manifest["outcome_values"]},
            "d4_post_hoc_score": _artifact(d4_score_path, d4_score_body),
        },
        "window_role": {
            "name": "D3 public falsification/development window",
            "prospective_holdout": False,
            "model_selection_allowed": False,
            "parameter_tuning_allowed": False,
            "topology_revision_allowed": False,
            "activation_gate_registered": False,
        },
        "scored_hour_count": len(observed),
        "metrics": metrics,
        "context_metrics": {
            "d4_modeled_tributary_boundary": d4_metrics,
        },
        "input_side_flux": {
            "distributed_q_lateral_mean_m3s": float(np.mean(q_lateral_total)),
            "branch_q_lateral_mean_m3s": float(np.mean(q_lateral_branch)),
            "branch_fraction_of_q_lateral_mean": float(
                np.mean(q_lateral_branch) / np.mean(q_lateral_total)
            ),
        },
        "non_gating_diagnostics": {
            "rmse_change_from_branch_silent_m3s": float(
                d5_metrics["rmse_m3s"] - silent_metrics["rmse_m3s"]
            ),
            "rmse_change_from_d4_boundary_m3s": float(
                d5_metrics["rmse_m3s"] - d4_metrics["rmse_m3s"]
            ),
            "absolute_bias_change_from_branch_silent_m3s": float(
                abs(d5_metrics["bias_m3s"])
                - abs(silent_metrics["bias_m3s"])
            ),
            "d5_beats_branch_silent_rmse": (
                d5_metrics["rmse_m3s"] < silent_metrics["rmse_m3s"]
            ),
            "d5_beats_d4_boundary_rmse": (
                d5_metrics["rmse_m3s"] < d4_metrics["rmse_m3s"]
            ),
            "d5_beats_persistence_rmse": (
                d5_metrics["rmse_m3s"] < persistence_metrics["rmse_m3s"]
            ),
            "interpretation": (
                "These comparisons diagnose an already public development "
                "window after the D5 artifact was sealed. They cannot validate, "
                "select, tune, or revise D5."
            ),
        },
        "independence_limits": {
            "evaluation_outcome_loaded_only_after_prediction_seal": True,
            "external_tributary_streamflow_boundary_used": False,
            "nwm_initial_streamflow_ground_truth": False,
            "nwm_initial_streamflow_possible_nudging": True,
            "fully_observation_independent_inputs": False,
        },
        "claim_boundary": {
            "executor_outcome_isolation_verified": True,
            "score_is_post_hoc": True,
            "full_subnetwork_executed": True,
            "external_modeled_tributary_boundary_used": False,
            "d5_predictive_improvement_validated": False,
            "full_subnetwork_routing_validated": False,
            "geospatial_kernel_validated": False,
            "new_frozen_evaluation_window_required": True,
            "second_system_required": True,
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
        raise ValueError("center_hill_d5_diagnostic_outcome_columns_invalid")
    result: dict[str, float | None] = {}
    for row in reader:
        if row["source_role"] != "independent_observation":
            raise ValueError("center_hill_d5_diagnostic_outcome_role_invalid")
        value = row["observed_discharge_m3s"]
        result[_canonical_utc(row["support_end_utc"])] = (
            None if value == "" else float(value)
        )
    return result


def _canonical_utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("center_hill_d5_diagnostic_timestamp_timezone_required")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_descriptor(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("center_hill_d5_diagnostic_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("center_hill_d5_diagnostic_artifact_identity_mismatch")
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
        d4_score_path=args.d4_score,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.report)
    print(f"d5_rmse_m3s={report['metrics']['d5_full_subnetwork']['rmse_m3s']}")
    print(f"d5_bias_m3s={report['metrics']['d5_full_subnetwork']['bias_m3s']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
