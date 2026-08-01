#!/usr/bin/env python3
"""Calibrate and diagnose uncertainty around the frozen innovation candidate."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    action_innovation_transition_parameters_from_dict,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_uncertainty import (
    HorizonResidualEnvelopeParameters,
    fit_horizon_residual_envelope,
    horizon_residual_envelope_parameters_from_dict,
)

if __package__:
    from scripts import evaluate_geospatial_kernel_action_innovation_candidate as point
else:
    import evaluate_geospatial_kernel_action_innovation_candidate as point

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_OPERATOR_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/action_innovation_uncertainty.py"
)
EVALUATOR_PATH = Path(__file__).resolve()
DEFAULT_POINT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_action_innovation_candidate_report.json"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / ("data/geotransport_v0_1/kernel_innovation_uncertainty_candidate")
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_action_innovation_uncertainty_report.json"
)
SCHEMA = "gwm.geotransport.geospatial_kernel_action_innovation_uncertainty_candidate.v1"
HORIZONS = (1, 3, 6, 12)
TARGET_COVERAGE = 0.9


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--point-report", type=Path, default=DEFAULT_POINT_REPORT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_uncertainty_candidate(
    *,
    point_report_path: Path = DEFAULT_POINT_REPORT,
    parameter_output_path: Path | None = None,
    development_prediction_path: Path | None = None,
    january_prediction_path: Path | None = None,
    d3_prediction_path: Path | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    parameter_output_path = parameter_output_path or DEFAULT_OUTPUT_ROOT / "parameters.json"
    development_prediction_path = development_prediction_path or (
        DEFAULT_OUTPUT_ROOT / "development_intervals.csv"
    )
    january_prediction_path = january_prediction_path or (
        DEFAULT_OUTPUT_ROOT / "january_temporal_holdout_intervals.csv"
    )
    d3_prediction_path = d3_prediction_path or DEFAULT_OUTPUT_ROOT / "february_d3_intervals.csv"

    point_report_body, point_report = point.development._load_json(point_report_path)
    _validate_point_report(point_report)
    point_parameter_body = point.development._read_verified(point_report["outputs"]["parameters"])
    point_parameters = action_innovation_transition_parameters_from_dict(
        json.loads(point_parameter_body)
    )
    point_parameter_hash = hashlib.sha256(point_parameter_body).hexdigest()
    source_rows: dict[str, list[dict[str, str]]] = {}
    source_bodies: dict[str, bytes] = {}
    for name in (
        "development_predictions",
        "january_temporal_holdout_predictions",
        "february_d3_predictions",
    ):
        body = point.development._read_verified(point_report["outputs"][name])
        rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
        _validate_point_rows(rows, point_parameter_hash)
        source_rows[name] = rows
        source_bodies[name] = body

    calibration_rows = _complete_rows(source_rows["development_predictions"])
    uncertainty_fit = fit_horizon_residual_envelope(
        point_parameters=point_parameters,
        point_parameter_artifact_sha256=point_parameter_hash,
        calibration_target_times=tuple(
            _parse_utc(row["target_support_end_utc"]) for row in calibration_rows
        ),
        calibration_horizon_hours=tuple(int(row["horizon_hours"]) for row in calibration_rows),
        observed_discharge_m3s=tuple(
            float(row["observed_discharge_m3s"]) for row in calibration_rows
        ),
        predicted_discharge_m3s=tuple(
            float(row["action_innovation_candidate_m3s"]) for row in calibration_rows
        ),
        target_marginal_coverage=TARGET_COVERAGE,
        provenance_id=(
            "center-hill:action-innovation:horizon-residual-envelope:"
            f"point-parameters={point_parameter_hash}:development-post-fit-only"
        ),
    )
    parameter_body = point.development._json_body(uncertainty_fit.as_dict())
    uncertainty_parameter_hash = hashlib.sha256(parameter_body).hexdigest()
    replay_parameters = horizon_residual_envelope_parameters_from_dict(json.loads(parameter_body))

    outputs: dict[str, bytes] = {"parameters": parameter_body}
    evaluations: dict[str, dict[str, Any]] = {}
    window_map = {
        "development": "development_predictions",
        "january_temporal_holdout": "january_temporal_holdout_predictions",
        "february_d3": "february_d3_predictions",
    }
    output_map = {
        "development": "development_intervals",
        "january_temporal_holdout": "january_temporal_holdout_intervals",
        "february_d3": "february_d3_intervals",
    }
    for window_id, source_name in window_map.items():
        body, evaluation = _evaluate_window(
            window_id=window_id,
            point_rows=source_rows[source_name],
            parameters=replay_parameters,
            uncertainty_parameter_hash=uncertainty_parameter_hash,
            maximum_discharge_m3s=point_parameters.maximum_discharge_m3s,
        )
        outputs[output_map[window_id]] = body
        evaluations[window_id] = evaluation

    output_paths = {
        "parameters": parameter_output_path,
        "development_intervals": development_prediction_path,
        "january_temporal_holdout_intervals": january_prediction_path,
        "february_d3_intervals": d3_prediction_path,
    }
    calibration_complete = (
        uncertainty_fit.calibration_sample_count == (475, 475, 475, 475)
        and uncertainty_fit.calibration_target_start > point_parameters.training_data_end
        and all(
            evaluation["all_rows_use_frozen_uncertainty_parameters"]
            for evaluation in evaluations.values()
        )
    )
    report = {
        "schema": SCHEMA,
        "status": (
            "uncertainty_candidate_calibrated_posthoc_diagnostics_complete_not_validated"
            if calibration_complete
            else "uncertainty_candidate_calibration_failed"
        ),
        "generated_at": datetime.now(UTC).isoformat(),
        "implementation_artifacts": {
            "uncertainty_operator": point.development._artifact(
                CORE_OPERATOR_PATH, CORE_OPERATOR_PATH.read_bytes()
            ),
            "evaluator": point.development._artifact(EVALUATOR_PATH, EVALUATOR_PATH.read_bytes()),
        },
        "source_artifacts": {
            "point_candidate_report": point.development._artifact(
                point_report_path, point_report_body
            ),
            "point_parameters": point_report["outputs"]["parameters"],
            **{
                name: point.development._artifact(
                    REPO_ROOT / str(point_report["outputs"][name]["path"]),
                    source_bodies[name],
                )
                for name in source_bodies
            },
        },
        "outputs": {
            name: point.development._artifact(output_paths[name], body)
            for name, body in outputs.items()
        },
        "parameter_lock": {
            "point_parameter_artifact_sha256": point_parameter_hash,
            "uncertainty_parameter_artifact_sha256": uncertainty_parameter_hash,
            "all_windows_use_deserialized_uncertainty_parameter_artifact": True,
            "per_window_uncertainty_refit_performed": False,
        },
        "calibration": {
            "role": "original_development_post_point_fit_residual_calibration",
            "target_marginal_coverage": TARGET_COVERAGE,
            "parameters": uncertainty_fit.as_dict(),
            "evaluation": evaluations["development"],
            "point_training_outcomes_reused_for_uncertainty_calibration": False,
            "calibration_outcomes_used": True,
        },
        "posthoc_temporal_diagnostics": {
            "january_temporal_holdout": evaluations["january_temporal_holdout"],
            "february_d3": evaluations["february_d3"],
        },
        "calibration_gate": {
            "all_horizons_have_475_post_fit_calibration_rows": (
                uncertainty_fit.calibration_sample_count == (475, 475, 475, 475)
            ),
            "calibration_targets_strictly_follow_point_training": (
                uncertainty_fit.calibration_target_start > point_parameters.training_data_end
            ),
            "point_parameter_identity_locked": (
                uncertainty_fit.point_parameter_artifact_sha256 == point_parameter_hash
            ),
            "calibration_complete": calibration_complete,
            "admission_gate_passed": False,
        },
        "selection_boundary": {
            "uncertainty_fit_uses_development_post_fit_outcomes_only": True,
            "uncertainty_fit_uses_january_outcomes": False,
            "uncertainty_fit_uses_february_d3_outcomes": False,
            "point_architecture_selected_after_transfer_outcomes_were_seen": True,
            "fresh_prospective_window_consumed": False,
            "new_target_data_acquired": False,
        },
        "statistical_claim_boundary": {
            "time_series_exchangeability_claimed": False,
            "finite_sample_coverage_guarantee_claimed": False,
            "conditional_coverage_guarantee_claimed": False,
            "posthoc_coverage_is_validation": False,
            "empirical_horizon_specific_residual_envelope_implemented": True,
        },
        "operational_claim_boundary": {
            "future_outlet_observation_used_at_interval_inference": False,
            "current_point_diagnostics_use_realized_future_action_archive": True,
            "current_point_diagnostics_use_retrospective_nwm_forcing": True,
            "operational_forecast_validated": False,
            "multi_system_uncertainty_validated": False,
            "uncertainty_candidate_admitted": False,
            "runtime_default_enabled": False,
        },
    }
    return outputs, report


def _validate_point_report(report: Mapping[str, Any]) -> None:
    gate = report.get("aggregate_gate") or {}
    claims = report.get("claim_boundary") or {}
    if (
        report.get("schema") != "gwm.geotransport.geospatial_kernel_action_innovation_candidate.v1"
        or report.get("status") != "action_innovation_candidate_posthoc_gates_passed_not_validated"
        or gate.get("candidate_diagnostic_gate_passed") is not True
        or gate.get("admission_gate_passed") is not False
        or claims.get("geospatial_kernel_validated") is not False
        or claims.get("operational_forecast_validated") is not False
    ):
        raise ValueError("action_innovation_uncertainty_point_report_invalid")


def _validate_point_rows(rows: list[dict[str, str]], point_parameter_hash: str) -> None:
    if not rows:
        raise ValueError("action_innovation_uncertainty_point_rows_required")
    if any(
        row["future_outcome_observation_used"] != "False"
        or row["parameter_sha256"] != point_parameter_hash
        or int(row["horizon_hours"]) not in HORIZONS
        for row in rows
    ):
        raise ValueError("action_innovation_uncertainty_point_row_contract_invalid")


def _complete_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if row["observed_discharge_m3s"] and row["action_innovation_candidate_m3s"]
    ]


def _evaluate_window(
    *,
    window_id: str,
    point_rows: list[dict[str, str]],
    parameters: HorizonResidualEnvelopeParameters,
    uncertainty_parameter_hash: str,
    maximum_discharge_m3s: float,
) -> tuple[bytes, dict[str, Any]]:
    rows: list[dict[str, object]] = []
    for source in _complete_rows(point_rows):
        horizon = int(source["horizon_hours"])
        point_value = float(source["action_innovation_candidate_m3s"])
        observed = float(source["observed_discharge_m3s"])
        lower, upper = parameters.interval_for_point(
            horizon_hours=horizon,
            point_discharge_m3s=point_value,
            maximum_discharge_m3s=maximum_discharge_m3s,
        )
        rows.append(
            {
                "window_id": window_id,
                "issue_time_utc": source["issue_time_utc"],
                "target_support_end_utc": source["target_support_end_utc"],
                "horizon_hours": horizon,
                "observed_discharge_m3s": observed,
                "point_discharge_m3s": point_value,
                "lower_discharge_m3s": lower,
                "upper_discharge_m3s": upper,
                "interval_width_m3s": upper - lower,
                "observed_inside_interval": lower <= observed <= upper,
                "lower_bound_clipped": math.isclose(lower, 0.0, abs_tol=1e-12),
                "upper_bound_clipped": math.isclose(upper, maximum_discharge_m3s, abs_tol=1e-12),
                "future_outcome_observation_used_at_inference": False,
                "point_parameter_sha256": parameters.point_parameter_artifact_sha256,
                "uncertainty_parameter_sha256": uncertainty_parameter_hash,
            }
        )
    body = point.development._encode_rows(rows)
    metrics = {str(horizon): _coverage_metrics(rows, horizon) for horizon in HORIZONS}
    return body, {
        "metrics_by_horizon": metrics,
        "all_rows_use_frozen_uncertainty_parameters": bool(rows)
        and all(row["uncertainty_parameter_sha256"] == uncertainty_parameter_hash for row in rows),
        "future_outlet_observation_used_at_interval_inference": False,
        "empirical_coverage_is_posthoc_diagnostic": window_id != "development",
    }


def _coverage_metrics(rows: list[dict[str, object]], horizon: int) -> dict[str, float | int]:
    selected = [row for row in rows if row["horizon_hours"] == horizon]
    if not selected:
        raise ValueError("action_innovation_uncertainty_coverage_rows_required")
    covered = np.asarray([bool(row["observed_inside_interval"]) for row in selected], dtype=bool)
    widths = np.asarray([float(row["interval_width_m3s"]) for row in selected])
    return {
        "sample_count": len(selected),
        "empirical_marginal_coverage": float(np.mean(covered)),
        "mean_interval_width_m3s": float(np.mean(widths)),
        "median_interval_width_m3s": float(np.median(widths)),
        "lower_bound_clipped_count": sum(bool(row["lower_bound_clipped"]) for row in selected),
        "upper_bound_clipped_count": sum(bool(row["upper_bound_clipped"]) for row in selected),
    }


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("action_innovation_uncertainty_utc_time_required")
    return parsed.astimezone(UTC)


def main() -> None:
    args = parse_args()
    paths = {
        "parameters": args.output_root / "parameters.json",
        "development_intervals": args.output_root / "development_intervals.csv",
        "january_temporal_holdout_intervals": (
            args.output_root / "january_temporal_holdout_intervals.csv"
        ),
        "february_d3_intervals": args.output_root / "february_d3_intervals.csv",
    }
    outputs, report = compile_uncertainty_candidate(
        point_report_path=args.point_report,
        parameter_output_path=paths["parameters"],
        development_prediction_path=paths["development_intervals"],
        january_prediction_path=paths["january_temporal_holdout_intervals"],
        d3_prediction_path=paths["february_d3_intervals"],
    )
    args.output_root.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    for name, path in paths.items():
        path.write_bytes(outputs[name])
    args.report.write_bytes(point.development._json_body(report))
    print(f"status={report['status']}")
    radii = report["calibration"]["parameters"]["absolute_error_radius_m3s"]
    for index, horizon in enumerate(HORIZONS):
        print(f"horizon={horizon}h radius_m3s={radii[index]:.6f}")
        for window_id, evaluation in (
            ("development", report["calibration"]["evaluation"]),
            *report["posthoc_temporal_diagnostics"].items(),
        ):
            coverage = evaluation["metrics_by_horizon"][str(horizon)]["empirical_marginal_coverage"]
            print(f"window={window_id} horizon={horizon}h coverage={coverage:.6f}")


if __name__ == "__main__":
    main()
