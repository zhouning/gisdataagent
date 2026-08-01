#!/usr/bin/env python3
"""Evaluate source-fitted horizon residual retention on sealed physical routing."""

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

from data_agent.uwm.geospatial_kernel_v2.physical_residual_retention import (
    PHYSICAL_RESIDUAL_RETENTION_SCHEMA,
    PhysicalResidualRetentionParameters,
    fit_physical_residual_retention,
    physical_residual_retention_parameters_from_dict,
)

if __package__:
    from scripts import evaluate_geospatial_kernel_action_innovation_candidate as candidate
    from scripts import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    from scripts import evaluate_geospatial_kernel_physical_residual_decay_transfer as decay
    from scripts import evaluate_geospatial_kernel_physical_routing_state_correction as baseline
else:
    import evaluate_geospatial_kernel_action_innovation_candidate as candidate
    import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    import evaluate_geospatial_kernel_physical_residual_decay_transfer as decay
    import evaluate_geospatial_kernel_physical_routing_state_correction as baseline


REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = Path(__file__).resolve()
CORE_OPERATOR_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/physical_residual_retention.py"
)
DEFAULT_SOURCE_PHYSICAL_REPORT = decay.DEFAULT_SOURCE_PHYSICAL_REPORT
DEFAULT_SOURCE_OUTCOME_REPORT = decay.DEFAULT_SOURCE_OUTCOME_REPORT
DEFAULT_REPLICATION_SOURCE_PHYSICAL_REPORT = decay.DEFAULT_REPLICATION_SOURCE_PHYSICAL_REPORT
DEFAULT_REPLICATION_SOURCE_OUTCOME_REPORT = decay.DEFAULT_REPLICATION_SOURCE_OUTCOME_REPORT
DEFAULT_COMPARISON_REPORT = decay.DEFAULT_REPORT
DEFAULT_OUTPUT_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/geospatial_kernel_physical_residual_retention_transfer_posthoc"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_physical_residual_retention_transfer_posthoc_report.json"
)

SCHEMA = "gwm.geotransport.geospatial_kernel_physical_residual_retention_transfer.v1"
HORIZONS = baseline.HORIZONS
SOURCE_SYSTEM_ID = decay.SOURCE_SYSTEM_ID
TARGET_SYSTEM_ID = decay.TARGET_SYSTEM_ID


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-physical-report", type=Path, default=DEFAULT_SOURCE_PHYSICAL_REPORT
    )
    parser.add_argument("--source-outcome-report", type=Path, default=DEFAULT_SOURCE_OUTCOME_REPORT)
    parser.add_argument(
        "--replication-source-physical-report",
        type=Path,
        default=DEFAULT_REPLICATION_SOURCE_PHYSICAL_REPORT,
    )
    parser.add_argument(
        "--replication-source-outcome-report",
        type=Path,
        default=DEFAULT_REPLICATION_SOURCE_OUTCOME_REPORT,
    )
    parser.add_argument("--comparison-report", type=Path, default=DEFAULT_COMPARISON_REPORT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_physical_residual_retention_transfer_posthoc(
    *,
    source_physical_report_path: Path = DEFAULT_SOURCE_PHYSICAL_REPORT,
    source_outcome_report_path: Path = DEFAULT_SOURCE_OUTCOME_REPORT,
    replication_source_physical_report_path: Path = DEFAULT_REPLICATION_SOURCE_PHYSICAL_REPORT,
    replication_source_outcome_report_path: Path = DEFAULT_REPLICATION_SOURCE_OUTCOME_REPORT,
    comparison_report_path: Path = DEFAULT_COMPARISON_REPORT,
    parameter_path: Path | None = None,
    primary_prediction_path: Path | None = None,
    replication_prediction_path: Path | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    parameter_path = parameter_path or DEFAULT_OUTPUT_ROOT / "parameters.json"
    primary_prediction_path = primary_prediction_path or (
        DEFAULT_OUTPUT_ROOT / "j_percy_priest_primary_predictions.csv"
    )
    replication_prediction_path = replication_prediction_path or (
        DEFAULT_OUTPUT_ROOT / "j_percy_priest_replication_predictions.csv"
    )

    source_physical = decay._load_source_physical_rollout(
        path=source_physical_report_path,
        expected_schema=baseline.PRIMARY_PHYSICAL_SCHEMA,
        expected_operator="BranchingManningNetworkTransportOperator",
        value_column="kernel_full_subnetwork_m3s",
        require_all_execution_gates=False,
    )
    source_outcome_report_body, source_outcome_descriptor, source_outcome_body = (
        decay._load_source_outcomes(
            path=source_outcome_report_path,
            expected_schema=decay.PRIMARY_OUTCOME_SCHEMA,
        )
    )
    source_fit = decay._aligned_source_series(
        physical_body=source_physical["prediction_body"],
        physical_value_column=source_physical["value_column"],
        outcome_body=source_outcome_body,
    )
    fitted = fit_physical_residual_retention(
        valid_times=source_fit["valid_times"],
        physical_discharge_m3s=source_fit["physical_values"],
        observed_discharge_m3s=source_fit["observed_values"],
        observation_latency_hours=1,
        supported_forecast_horizons_hours=HORIZONS,
        source_system_id=SOURCE_SYSTEM_ID,
        source_operator=source_physical["operator"],
        source_prediction_sha256=source_physical["prediction_descriptor"]["sha256"],
        source_outcome_sha256=source_outcome_descriptor["sha256"],
        provenance_id=(
            "center-hill:2022-03-31--2022-04-28:"
            "sealed-physical-zero-intercept-residual-retention-by-horizon"
        ),
    )
    parameter_body = _json_body(fitted.as_dict())
    parameters = physical_residual_retention_parameters_from_dict(json.loads(parameter_body))
    parameter_sha256 = hashlib.sha256(parameter_body).hexdigest()

    # The later Center Hill window is diagnostic and cannot alter the frozen weights.
    replication_source_physical = decay._load_source_physical_rollout(
        path=replication_source_physical_report_path,
        expected_schema=baseline.REPLICATION_PHYSICAL_SCHEMA,
        expected_operator="BranchingFiniteVolumeKinematicWaveOperator",
        value_column="kinematic_wave_m3s",
        require_all_execution_gates=True,
    )
    (
        replication_source_outcome_report_body,
        replication_source_outcome_descriptor,
        replication_source_outcome_body,
    ) = decay._load_source_outcomes(
        path=replication_source_outcome_report_path,
        expected_schema=decay.REPLICATION_OUTCOME_SCHEMA,
    )
    replication_source_fit = decay._aligned_source_series(
        physical_body=replication_source_physical["prediction_body"],
        physical_value_column=replication_source_physical["value_column"],
        outcome_body=replication_source_outcome_body,
    )
    replication_diagnostic = fit_physical_residual_retention(
        valid_times=replication_source_fit["valid_times"],
        physical_discharge_m3s=replication_source_fit["physical_values"],
        observed_discharge_m3s=replication_source_fit["observed_values"],
        observation_latency_hours=1,
        supported_forecast_horizons_hours=HORIZONS,
        source_system_id=SOURCE_SYSTEM_ID,
        source_operator=replication_source_physical["operator"],
        source_prediction_sha256=replication_source_physical["prediction_descriptor"]["sha256"],
        source_outcome_sha256=replication_source_outcome_descriptor["sha256"],
        provenance_id=(
            "center-hill:2022-11-10--2022-12-08:horizon-retention-stability-diagnostic-only"
        ),
    )

    # Outcome-bearing target rows are not read until the parameter body is locked.
    comparison_report_body, comparison_report = _load_comparison_report(comparison_report_path)
    primary_source_descriptor = comparison_report["outputs"]["primary_predictions"]
    replication_source_descriptor = comparison_report["outputs"]["replication_predictions"]
    primary_source_body = cross._read_verified(primary_source_descriptor)
    replication_source_body = cross._read_verified(replication_source_descriptor)
    primary_body, primary_result = _compile_window(
        source_body=primary_source_body,
        parameters=parameters,
        parameter_sha256=parameter_sha256,
    )
    replication_body, replication_result = _compile_window(
        source_body=replication_source_body,
        parameters=parameters,
        parameter_sha256=parameter_sha256,
    )
    _verify_metric_replay(result=primary_result, expected=comparison_report["primary_window"])
    _verify_metric_replay(
        result=replication_result,
        expected=comparison_report["replication_window"],
    )

    outputs = {
        "parameters": parameter_body,
        "primary_predictions": primary_body,
        "replication_predictions": replication_body,
    }
    results = (primary_result, replication_result)
    accuracy_passed = all(
        result["comparison"]["retention_beats_raw_physical_all_horizons"] for result in results
    )
    report = {
        "schema": SCHEMA,
        "status": "source_fitted_physical_residual_retention_transfer_posthoc_complete",
        "generated_at": datetime.now(UTC).isoformat(),
        "implementation_artifacts": {
            "physical_residual_retention_operator": _artifact(
                CORE_OPERATOR_PATH, CORE_OPERATOR_PATH.read_bytes()
            ),
            "evaluator": _artifact(EVALUATOR_PATH, EVALUATOR_PATH.read_bytes()),
        },
        "source_artifacts": {
            "source_physical_rollout_report": _artifact(
                source_physical_report_path, source_physical["report_body"]
            ),
            "source_sealed_physical_predictions": dict(source_physical["prediction_descriptor"]),
            "source_outcome_report": _artifact(
                source_outcome_report_path, source_outcome_report_body
            ),
            "source_outcome_values": dict(source_outcome_descriptor),
            "replication_source_physical_rollout_report": _artifact(
                replication_source_physical_report_path,
                replication_source_physical["report_body"],
            ),
            "replication_source_sealed_physical_predictions": dict(
                replication_source_physical["prediction_descriptor"]
            ),
            "replication_source_outcome_report": _artifact(
                replication_source_outcome_report_path,
                replication_source_outcome_report_body,
            ),
            "replication_source_outcome_values": dict(replication_source_outcome_descriptor),
            "target_comparison_report": _artifact(comparison_report_path, comparison_report_body),
            "primary_target_comparison_rows": dict(primary_source_descriptor),
            "replication_target_comparison_rows": dict(replication_source_descriptor),
        },
        "outputs": {
            "parameters": _artifact(parameter_path, parameter_body),
            "primary_predictions": _artifact(primary_prediction_path, primary_body),
            "replication_predictions": _artifact(replication_prediction_path, replication_body),
        },
        "parameter_lock": {
            "schema": PHYSICAL_RESIDUAL_RETENTION_SCHEMA,
            "parameter_sha256": parameter_sha256,
            "parameter_body_compiled_before_target_comparison_row_load": True,
            "all_target_windows_use_deserialized_parameter_artifact": True,
        },
        "source_fit_contract": {
            "model_family": "zero_intercept_physical_residual_retention_by_horizon",
            "formula": fitted.as_dict()["formula"],
            "estimator": fitted.as_dict()["estimator"],
            "free_parameter_count": len(parameters.weights),
            "source_system_id": SOURCE_SYSTEM_ID,
            "source_operator": source_physical["operator"],
            "weights_by_horizon": _weights_by_horizon(parameters),
            "weight_bounds_applied": False,
            "target_system_id": TARGET_SYSTEM_ID,
            "target_outcomes_used_for_fit": False,
            "per_target_window_refit_performed": False,
            "same_parameters_used_across_target_windows": True,
        },
        "transfer_contract": {
            "primary_window": "cross_system_same_window_same_physical_operator_form",
            "replication_window": "cross_system_temporal_and_physical_operator_form_transfer",
            "source_to_target_parameter_refit_performed": False,
            "primary_to_replication_parameter_refit_performed": False,
        },
        "replication_source_diagnostic": {
            "system_id": SOURCE_SYSTEM_ID,
            "operator": replication_source_physical["operator"],
            "weights_by_horizon": _diagnostic_weights(
                frozen=parameters,
                diagnostic=replication_diagnostic,
            ),
            "used_for_target_prediction": False,
            "admission_evidence": False,
        },
        "primary_window": primary_result,
        "replication_window": replication_result,
        "diagnostic_interpretation": {
            "retention_beats_constant_correction_all_horizons_in_both_windows": all(
                result["comparison"]["retention_beats_constant_correction_all_horizons"]
                for result in results
            ),
            "retention_beats_ar1_decay_all_horizons_in_both_windows": all(
                result["comparison"]["retention_beats_ar1_decay_all_horizons"] for result in results
            ),
            "retention_beats_raw_physical_all_horizons_in_both_windows": (accuracy_passed),
            "retention_beats_wwm_all_horizons_in_both_windows": all(
                result["comparison"]["retention_beats_wwm_all_horizons"] for result in results
            ),
            "negative_long_horizon_source_weight_is_phase_reversal_diagnostic": any(
                item.weight < 0.0 for item in parameters.weights
            ),
            "raw_physical_remains_required_minimum_physical_bar": not accuracy_passed,
            "result_may_trigger_refit_on_these_windows": False,
        },
        "promotion_gate": {
            "must_beat_raw_physical_all_horizons_in_both_windows": True,
            "target_outcome_free_parameter_fit_required": True,
            "target_outcome_free_parameter_fit_passed": True,
            "prospective_model_design_required": True,
            "prospective_model_design_passed": False,
            "accuracy_requirement_passed": accuracy_passed,
            "physical_residual_retention_promotion_gate_passed": False,
        },
        "information_boundary": {
            "source_center_hill_outcomes_used_for_parameter_fit": True,
            "target_j_percy_priest_outcomes_used_for_parameter_fit": False,
            "target_outcomes_were_exposed_before_model_design": True,
            "future_target_observation_used_inside_forecast": False,
            "operational_issue_time_vintages_verified": False,
            "evaluation_counts_as_fresh_validation": False,
            "fresh_prospective_window_consumed": False,
        },
        "claim_boundary": {
            "physical_residual_retention_posthoc_executed": True,
            "physical_residual_retention_admitted": False,
            "physical_residual_retention_promoted": False,
            "physical_operator_admitted": False,
            "wwm_candidate_admitted": False,
            "geospatial_kernel_validated": False,
            "multi_system_generalization_validated": False,
            "operational_forecast_validated": False,
            "runtime_default_enabled": False,
        },
    }
    return outputs, report


def _load_comparison_report(path: Path) -> tuple[bytes, Mapping[str, Any]]:
    body, report = cross._load_json(path)
    claim = report.get("claim_boundary") or {}
    information = report.get("information_boundary") or {}
    outputs = report.get("outputs") or {}
    if (
        report.get("schema") != decay.SCHEMA
        or report.get("status") != "source_fitted_physical_residual_decay_transfer_posthoc_complete"
        or claim.get("physical_residual_decay_posthoc_executed") is not True
        or claim.get("geospatial_kernel_validated") is not False
        or information.get("evaluation_counts_as_fresh_validation") is not False
        or not {"primary_predictions", "replication_predictions"}.issubset(outputs)
    ):
        raise ValueError("physical_residual_retention_comparison_report_invalid")
    return body, report


def _compile_window(
    *,
    source_body: bytes,
    parameters: PhysicalResidualRetentionParameters,
    parameter_sha256: str,
) -> tuple[bytes, dict[str, Any]]:
    source_rows = _comparison_rows(source_body)
    rows: list[dict[str, object]] = []
    clipped_count = 0
    issue_times: set[datetime] = set()
    for source in source_rows:
        horizon = int(source["horizon_hours"])
        issue_time = cross._parse_time(source["issue_time_utc"])
        step = parameters.correct(
            latest_observed_discharge_m3s=float(source["causal_persistence_m3s"]),
            physical_at_latest_observation_m3s=float(source["physical_at_latest_observation_m3s"]),
            physical_target_m3s=float(source["physical_open_loop_m3s"]),
            forecast_horizon_hours=horizon,
        )
        if not math.isclose(
            step.latest_observation_residual_m3s,
            float(source["latest_observation_residual_m3s"]),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("physical_residual_retention_residual_replay_mismatch")
        clipped_count += int(step.clipped)
        issue_times.add(issue_time)
        rows.append(
            {
                "system_id": source["system_id"],
                "issue_time_utc": source["issue_time_utc"],
                "target_support_end_utc": source["target_support_end_utc"],
                "horizon_hours": horizon,
                # This outcome is copied only after the forecast is complete.
                "observed_discharge_m3s": source["observed_discharge_m3s"],
                "physical_open_loop_m3s": source["physical_open_loop_m3s"],
                "physical_constant_state_correction_m3s": source[
                    "physical_constant_state_correction_m3s"
                ],
                "physical_residual_decay_m3s": source["physical_residual_decay_m3s"],
                "physical_residual_retention_m3s": step.corrected_prediction_m3s,
                "classical_arx_m3s": source["classical_arx_m3s"],
                "action_innovation_wwm_m3s": source["action_innovation_wwm_m3s"],
                "causal_persistence_m3s": source["causal_persistence_m3s"],
                "physical_at_latest_observation_m3s": (step.physical_at_latest_observation_m3s),
                "latest_observation_residual_m3s": (step.latest_observation_residual_m3s),
                "residual_retention_weight": step.retention_weight,
                "elapsed_from_latest_observation_hours": (
                    step.elapsed_from_latest_observation_hours
                ),
                "latest_observation_valid_at_utc": source["latest_observation_valid_at_utc"],
                "latest_observation_available_at_utc": source[
                    "latest_observation_available_at_utc"
                ],
                "residual_retention_clipped": step.clipped,
                "future_target_observation_used_for_correction": False,
                "target_parameter_refit_performed": False,
                "operational_vintages_verified": False,
                "residual_retention_parameter_sha256": parameter_sha256,
                "residual_decay_parameter_sha256": source["residual_decay_parameter_sha256"],
                "source_physical_prediction_sha256": source["source_physical_prediction_sha256"],
                "arx_parameter_sha256": source["arx_parameter_sha256"],
                "wwm_parameter_sha256": source["wwm_parameter_sha256"],
            }
        )
    columns = {
        "physical_open_loop": "physical_open_loop_m3s",
        "physical_constant_state_correction": ("physical_constant_state_correction_m3s"),
        "physical_residual_decay": "physical_residual_decay_m3s",
        "physical_residual_retention": "physical_residual_retention_m3s",
        "classical_arx": "classical_arx_m3s",
        "action_innovation_wwm": "action_innovation_wwm_m3s",
        "causal_persistence": "causal_persistence_m3s",
    }
    metrics, scoring = candidate._score(rows, columns)
    return cross._encode_rows(rows), {
        "window": {
            "first_issue_time_utc": _iso(min(issue_times)),
            "last_issue_time_utc": _iso(max(issue_times)),
            "horizons_hours": list(HORIZONS),
        },
        "metrics_by_horizon": metrics,
        "comparison": _comparison(metrics),
        "scoring": scoring,
        "execution": {
            "prediction_row_count": len(rows),
            "forecast_issue_count": len(issue_times),
            "residual_retention_clipped_row_count": clipped_count,
            "target_parameter_refit_performed": False,
            "future_target_observation_used_for_correction": False,
        },
    }


def _comparison_rows(body: bytes) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    required = {
        "system_id",
        "issue_time_utc",
        "target_support_end_utc",
        "horizon_hours",
        "observed_discharge_m3s",
        "physical_open_loop_m3s",
        "physical_constant_state_correction_m3s",
        "physical_residual_decay_m3s",
        "classical_arx_m3s",
        "action_innovation_wwm_m3s",
        "causal_persistence_m3s",
        "physical_at_latest_observation_m3s",
        "latest_observation_residual_m3s",
        "latest_observation_valid_at_utc",
        "latest_observation_available_at_utc",
        "residual_decay_parameter_sha256",
        "source_physical_prediction_sha256",
        "arx_parameter_sha256",
        "wwm_parameter_sha256",
    }
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValueError("physical_residual_retention_comparison_columns_invalid")
    rows = list(reader)
    if not rows or any(row["system_id"] != TARGET_SYSTEM_ID for row in rows):
        raise ValueError("physical_residual_retention_comparison_axis_invalid")
    return rows


def _comparison(
    metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> dict[str, Any]:
    comparators = {
        "raw_physical": "physical_open_loop",
        "constant_correction": "physical_constant_state_correction",
        "ar1_decay": "physical_residual_decay",
        "arx": "classical_arx",
        "wwm": "action_innovation_wwm",
        "persistence": "causal_persistence",
    }
    per_horizon: dict[str, dict[str, float]] = {}
    for horizon in HORIZONS:
        horizon_metrics = metrics[str(horizon)]
        retention_rmse = horizon_metrics["physical_residual_retention"]["rmse_m3s"]
        per_horizon[str(horizon)] = {
            f"retention_minus_{name}_rmse_m3s": (
                retention_rmse - horizon_metrics[metric_name]["rmse_m3s"]
            )
            for name, metric_name in comparators.items()
        }
    result: dict[str, Any] = {"per_horizon": per_horizon}
    for name in comparators:
        result[f"retention_beats_{name}_all_horizons"] = all(
            values[f"retention_minus_{name}_rmse_m3s"] < 0.0 for values in per_horizon.values()
        )
        result[f"retention_beats_{name}_horizons_hours"] = [
            horizon
            for horizon in HORIZONS
            if per_horizon[str(horizon)][f"retention_minus_{name}_rmse_m3s"] < 0.0
        ]
    return result


def _verify_metric_replay(*, result: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    existing_models = (
        "physical_open_loop",
        "physical_constant_state_correction",
        "physical_residual_decay",
        "classical_arx",
        "action_innovation_wwm",
        "causal_persistence",
    )
    for horizon in HORIZONS:
        actual = result["metrics_by_horizon"][str(horizon)]
        prior = expected["metrics_by_horizon"][str(horizon)]
        for model_name in existing_models:
            if actual[model_name] != prior[model_name]:
                raise ValueError("physical_residual_retention_metric_replay_mismatch")
    if result["scoring"] != expected["scoring"]:
        raise ValueError("physical_residual_retention_scoring_replay_mismatch")


def _weights_by_horizon(
    parameters: PhysicalResidualRetentionParameters,
) -> dict[str, dict[str, float | int]]:
    return {
        str(item.forecast_horizon_hours): {
            "elapsed_from_latest_observation_hours": (item.elapsed_from_latest_observation_hours),
            "weight": item.weight,
            "training_pair_count": item.training_pair_count,
        }
        for item in parameters.weights
    }


def _diagnostic_weights(
    *,
    frozen: PhysicalResidualRetentionParameters,
    diagnostic: PhysicalResidualRetentionParameters,
) -> dict[str, dict[str, float | int]]:
    frozen_by_horizon = {item.forecast_horizon_hours: item for item in frozen.weights}
    return {
        str(item.forecast_horizon_hours): {
            "elapsed_from_latest_observation_hours": (item.elapsed_from_latest_observation_hours),
            "training_pair_count": item.training_pair_count,
            "diagnostic_weight": item.weight,
            "diagnostic_minus_frozen_weight": (
                item.weight - frozen_by_horizon[item.forecast_horizon_hours].weight
            ),
        }
        for item in diagnostic.weights
    }


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": cross._display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _json_body(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def main() -> None:
    args = parse_args()
    paths = {
        "parameters": args.output_root / "parameters.json",
        "primary_predictions": args.output_root / "j_percy_priest_primary_predictions.csv",
        "replication_predictions": (
            args.output_root / "j_percy_priest_replication_predictions.csv"
        ),
    }
    bodies, report = compile_physical_residual_retention_transfer_posthoc(
        source_physical_report_path=args.source_physical_report,
        source_outcome_report_path=args.source_outcome_report,
        replication_source_physical_report_path=args.replication_source_physical_report,
        replication_source_outcome_report_path=args.replication_source_outcome_report,
        comparison_report_path=args.comparison_report,
        parameter_path=paths["parameters"],
        primary_prediction_path=paths["primary_predictions"],
        replication_prediction_path=paths["replication_predictions"],
    )
    args.output_root.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    for name, body in bodies.items():
        paths[name].write_bytes(body)
    args.report.write_bytes(_json_body(report))
    print(f"status={report['status']}")
    for horizon in HORIZONS:
        source = report["source_fit_contract"]["weights_by_horizon"][str(horizon)]
        print(
            f"source_horizon={horizon}h elapsed={source['elapsed_from_latest_observation_hours']}h "
            f"weight={source['weight']:.9f} pairs={source['training_pair_count']}"
        )
    for window_name in ("primary_window", "replication_window"):
        for horizon in HORIZONS:
            values = report[window_name]["comparison"]["per_horizon"][str(horizon)]
            print(
                f"window={window_name} horizon={horizon}h "
                f"retention_minus_raw_rmse="
                f"{values['retention_minus_raw_physical_rmse_m3s']:.6f} "
                f"retention_minus_ar1_rmse="
                f"{values['retention_minus_ar1_decay_rmse_m3s']:.6f} "
                f"retention_minus_wwm_rmse="
                f"{values['retention_minus_wwm_rmse_m3s']:.6f}"
            )


if __name__ == "__main__":
    main()
