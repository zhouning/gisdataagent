#!/usr/bin/env python3
"""Evaluate a source-fitted residual decay on sealed physical routing."""

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

from data_agent.uwm.geospatial_kernel_v2.physical_residual_decay import (
    PHYSICAL_RESIDUAL_DECAY_SCHEMA,
    PhysicalResidualDecayParameters,
    fit_physical_residual_decay,
    physical_residual_decay_parameters_from_dict,
)

if __package__:
    from scripts import evaluate_geospatial_kernel_action_innovation_candidate as candidate
    from scripts import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    from scripts import evaluate_geospatial_kernel_physical_routing_state_correction as baseline
else:
    import evaluate_geospatial_kernel_action_innovation_candidate as candidate
    import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    import evaluate_geospatial_kernel_physical_routing_state_correction as baseline


REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = Path(__file__).resolve()
CORE_OPERATOR_PATH = REPO_ROOT / ("data_agent/uwm/geospatial_kernel_v2/physical_residual_decay.py")
DEFAULT_SOURCE_PHYSICAL_REPORT = baseline.DEFAULT_PRIMARY_PHYSICAL_REPORT
DEFAULT_SOURCE_OUTCOME_REPORT = cross.DEFAULT_OUTCOME_REPORT
DEFAULT_REPLICATION_SOURCE_PHYSICAL_REPORT = baseline.DEFAULT_REPLICATION_PHYSICAL_REPORT
DEFAULT_REPLICATION_SOURCE_OUTCOME_REPORT = cross.DEFAULT_REPLICATION_OUTCOME_REPORT
DEFAULT_COMPARISON_REPORT = baseline.DEFAULT_REPORT
DEFAULT_OUTPUT_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/geospatial_kernel_physical_residual_decay_transfer_posthoc"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_physical_residual_decay_transfer_posthoc_report.json"
)

SCHEMA = "gwm.geotransport.geospatial_kernel_physical_residual_decay_transfer.v1"
PRIMARY_OUTCOME_SCHEMA = "gwm.geotransport.v2_blind_validation_outcomes.v1"
REPLICATION_OUTCOME_SCHEMA = "gwm.geotransport.kinematic_wave_holdout_outcomes.v2"
HORIZONS = baseline.HORIZONS
SOURCE_SYSTEM_ID = "center_hill"
TARGET_SYSTEM_ID = cross.SYSTEM_ID


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-physical-report",
        type=Path,
        default=DEFAULT_SOURCE_PHYSICAL_REPORT,
    )
    parser.add_argument(
        "--source-outcome-report",
        type=Path,
        default=DEFAULT_SOURCE_OUTCOME_REPORT,
    )
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


def compile_physical_residual_decay_transfer_posthoc(
    *,
    source_physical_report_path: Path = DEFAULT_SOURCE_PHYSICAL_REPORT,
    source_outcome_report_path: Path = DEFAULT_SOURCE_OUTCOME_REPORT,
    replication_source_physical_report_path: Path = (DEFAULT_REPLICATION_SOURCE_PHYSICAL_REPORT),
    replication_source_outcome_report_path: Path = (DEFAULT_REPLICATION_SOURCE_OUTCOME_REPORT),
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

    source_physical = _load_source_physical_rollout(
        path=source_physical_report_path,
        expected_schema=baseline.PRIMARY_PHYSICAL_SCHEMA,
        expected_operator="BranchingManningNetworkTransportOperator",
        value_column="kernel_full_subnetwork_m3s",
        require_all_execution_gates=False,
    )
    (
        source_outcome_report_body,
        source_outcome_descriptor,
        source_outcome_body,
    ) = _load_source_outcomes(
        path=source_outcome_report_path,
        expected_schema=PRIMARY_OUTCOME_SCHEMA,
    )
    source_fit = _aligned_source_series(
        physical_body=source_physical["prediction_body"],
        physical_value_column=source_physical["value_column"],
        outcome_body=source_outcome_body,
    )
    fitted = fit_physical_residual_decay(
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
            "center-hill:2022-03-31--2022-04-28:sealed-physical-residual-zero-intercept-ar1"
        ),
    )
    parameter_body = _json_body(fitted.as_dict())
    parameters = physical_residual_decay_parameters_from_dict(json.loads(parameter_body))
    parameter_sha256 = hashlib.sha256(parameter_body).hexdigest()

    # This later Center Hill window is a coefficient-stability diagnostic only.
    replication_source_physical = _load_source_physical_rollout(
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
    ) = _load_source_outcomes(
        path=replication_source_outcome_report_path,
        expected_schema=REPLICATION_OUTCOME_SCHEMA,
    )
    replication_source_fit = _aligned_source_series(
        physical_body=replication_source_physical["prediction_body"],
        physical_value_column=replication_source_physical["value_column"],
        outcome_body=replication_source_outcome_body,
    )
    replication_diagnostic = fit_physical_residual_decay(
        valid_times=replication_source_fit["valid_times"],
        physical_discharge_m3s=replication_source_fit["physical_values"],
        observed_discharge_m3s=replication_source_fit["observed_values"],
        observation_latency_hours=1,
        supported_forecast_horizons_hours=HORIZONS,
        source_system_id=SOURCE_SYSTEM_ID,
        source_operator=replication_source_physical["operator"],
        source_prediction_sha256=replication_source_physical["prediction_descriptor"]["sha256"],
        source_outcome_sha256=replication_source_outcome_descriptor["sha256"],
        provenance_id=("center-hill:2022-11-10--2022-12-08:coefficient-stability-diagnostic-only"),
    )

    # Outcome-bearing target rows are not read until the source parameter is locked.
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
    _verify_metric_replay(
        result=primary_result,
        expected=comparison_report["primary_window"],
    )
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
    report = {
        "schema": SCHEMA,
        "status": "source_fitted_physical_residual_decay_transfer_posthoc_complete",
        "generated_at": datetime.now(UTC).isoformat(),
        "implementation_artifacts": {
            "physical_residual_decay_operator": _artifact(
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
            "schema": PHYSICAL_RESIDUAL_DECAY_SCHEMA,
            "parameter_sha256": parameter_sha256,
            "parameter_body_compiled_before_target_comparison_row_load": True,
            "all_target_windows_use_deserialized_parameter_artifact": True,
        },
        "source_fit_contract": {
            "model_family": "bounded_zero_intercept_physical_residual_AR1",
            "formula": fitted.as_dict()["formula"],
            "free_parameter_count": 1,
            "source_system_id": SOURCE_SYSTEM_ID,
            "source_operator": source_physical["operator"],
            "training_pair_count": parameters.training_pair_count,
            "residual_decay_coefficient": parameters.residual_decay_coefficient,
            "coefficient_lower_bound": 0.0,
            "coefficient_upper_bound": 1.0,
            "target_system_id": TARGET_SYSTEM_ID,
            "target_outcomes_used_for_fit": False,
            "per_target_window_refit_performed": False,
            "same_parameter_used_across_target_windows": True,
        },
        "transfer_contract": {
            "primary_window": ("cross_system_same_window_same_physical_operator_form"),
            "replication_window": ("cross_system_temporal_and_physical_operator_form_transfer"),
            "source_to_target_parameter_refit_performed": False,
            "primary_to_replication_parameter_refit_performed": False,
        },
        "replication_source_diagnostic": {
            "system_id": SOURCE_SYSTEM_ID,
            "operator": replication_source_physical["operator"],
            "training_pair_count": replication_diagnostic.training_pair_count,
            "residual_decay_coefficient": (replication_diagnostic.residual_decay_coefficient),
            "coefficient_minus_frozen_parameter": (
                replication_diagnostic.residual_decay_coefficient
                - parameters.residual_decay_coefficient
            ),
            "used_for_target_prediction": False,
            "admission_evidence": False,
        },
        "primary_window": primary_result,
        "replication_window": replication_result,
        "diagnostic_interpretation": {
            "decay_beats_constant_correction_all_horizons_in_both_windows": all(
                result["comparison"]["decay_beats_constant_correction_all_horizons"]
                for result in results
            ),
            "decay_beats_raw_physical_all_horizons_in_both_windows": all(
                result["comparison"]["decay_beats_raw_physical_all_horizons"] for result in results
            ),
            "decay_beats_wwm_all_horizons_in_both_windows": all(
                result["comparison"]["decay_beats_wwm_all_horizons"] for result in results
            ),
            "raw_physical_remains_required_minimum_physical_bar": not all(
                result["comparison"]["decay_beats_raw_physical_all_horizons"] for result in results
            ),
            "result_may_trigger_refit_on_these_windows": False,
        },
        "promotion_gate": {
            "must_beat_raw_physical_all_horizons_in_both_windows": True,
            "target_outcome_free_parameter_fit_required": True,
            "target_outcome_free_parameter_fit_passed": True,
            "prospective_model_design_required": True,
            "prospective_model_design_passed": False,
            "accuracy_requirement_passed": all(
                result["comparison"]["decay_beats_raw_physical_all_horizons"] for result in results
            ),
            "physical_residual_decay_promotion_gate_passed": False,
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
            "physical_residual_decay_posthoc_executed": True,
            "physical_residual_decay_admitted": False,
            "physical_residual_decay_promoted": False,
            "physical_operator_admitted": False,
            "wwm_candidate_admitted": False,
            "geospatial_kernel_validated": False,
            "multi_system_generalization_validated": False,
            "operational_forecast_validated": False,
            "runtime_default_enabled": False,
        },
    }
    return outputs, report


def _load_source_outcomes(
    *, path: Path, expected_schema: str
) -> tuple[bytes, Mapping[str, Any], bytes]:
    report_body, report = cross._load_json(path)
    claim = report.get("claim_boundary") or {}
    system = (report.get("systems") or {}).get(SOURCE_SYSTEM_ID) or {}
    descriptor = system.get("outcome_values") or {}
    if (
        report.get("schema") != expected_schema
        or report.get("status") != "two_system_outcomes_acquired_after_joint_seal"
        or claim.get("outcome_values_imputed") is not False
        or system.get("variable_role") != "independent_observation"
    ):
        raise ValueError("physical_residual_decay_source_outcome_report_invalid")
    body = cross._read_verified(descriptor)
    return report_body, descriptor, body


def _load_source_physical_rollout(
    *,
    path: Path,
    expected_schema: str,
    expected_operator: str,
    value_column: str,
    require_all_execution_gates: bool,
) -> dict[str, Any]:
    report_body, report = cross._load_json(path)
    system = (report.get("systems") or {}).get(SOURCE_SYSTEM_ID) or {}
    data_isolation = system.get("data_isolation") or {}
    invariants = system.get("invariants") or {}
    execution = system.get("registered_execution") or {}
    descriptor = system.get("prediction_artifact") or {}
    claim = report.get("claim_boundary") or {}
    gates_valid = (
        invariants.get("all_execution_gates_passed") is True
        if require_all_execution_gates
        else invariants.get("actual_conservation_passed") is True
    )
    if (
        report.get("schema") != expected_schema
        or report.get("status") != "joint_outcome_free_predictions_sealed"
        or execution.get("operator") != expected_operator
        or data_isolation.get("outcome_values_loaded") is not False
        or claim.get("outcome_free_predictions_sealed") is not True
        or invariants.get("zero_state_zero_input_identity_passed") is not True
        or not gates_valid
    ):
        raise ValueError("physical_residual_decay_source_rollout_report_invalid")
    prediction_body = cross._read_verified(descriptor)
    prediction_count = len(baseline._physical_series(prediction_body, value_column=value_column))
    if prediction_count != int(
        system.get("result", {}).get("prediction_count", -1)
    ) or prediction_count != int(report.get("window", {}).get("hour_count", -1)):
        raise ValueError("physical_residual_decay_source_prediction_count_invalid")
    return {
        "report_body": report_body,
        "prediction_body": prediction_body,
        "prediction_descriptor": descriptor,
        "value_column": value_column,
        "operator": expected_operator,
    }


def _aligned_source_series(
    *, physical_body: bytes, physical_value_column: str, outcome_body: bytes
) -> dict[str, tuple[Any, ...]]:
    physical = baseline._physical_series(physical_body, value_column=physical_value_column)
    outcomes = _outcome_series(outcome_body)
    valid_times = tuple(sorted(physical))
    if any(value not in outcomes for value in valid_times):
        raise ValueError("physical_residual_decay_source_axis_invalid")
    return {
        "valid_times": valid_times,
        "physical_values": tuple(physical[value] for value in valid_times),
        "observed_values": tuple(outcomes[value] for value in valid_times),
    }


def _outcome_series(body: bytes) -> dict[datetime, float | None]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    required = {"support_end_utc", "observed_discharge_m3s"}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValueError("physical_residual_decay_source_outcome_columns_invalid")
    values: dict[datetime, float | None] = {}
    for row in reader:
        valid_time = cross._parse_time(row["support_end_utc"])
        raw = row["observed_discharge_m3s"]
        value = None if raw == "" else float(raw)
        if valid_time in values or (
            value is not None and (not math.isfinite(value) or value < 0.0)
        ):
            raise ValueError("physical_residual_decay_source_outcome_axis_invalid")
        values[valid_time] = value
    if not values:
        raise ValueError("physical_residual_decay_source_outcome_axis_invalid")
    return values


def _load_comparison_report(path: Path) -> tuple[bytes, Mapping[str, Any]]:
    body, report = cross._load_json(path)
    claim = report.get("claim_boundary") or {}
    outputs = report.get("outputs") or {}
    if (
        report.get("schema") != baseline.SCHEMA
        or report.get("status") != "traditional_physical_routing_state_correction_posthoc_complete"
        or claim.get("traditional_physical_router_posthoc_comparison_executed") is not True
        or claim.get("geospatial_kernel_validated") is not False
        or not {"primary_predictions", "replication_predictions"}.issubset(outputs)
    ):
        raise ValueError("physical_residual_decay_comparison_report_invalid")
    return body, report


def _compile_window(
    *,
    source_body: bytes,
    parameters: PhysicalResidualDecayParameters,
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
            raise ValueError("physical_residual_decay_residual_replay_mismatch")
        clipped_count += int(step.clipped)
        issue_times.add(issue_time)
        rows.append(
            {
                "system_id": source["system_id"],
                "issue_time_utc": source["issue_time_utc"],
                "target_support_end_utc": source["target_support_end_utc"],
                "horizon_hours": horizon,
                # The target outcome enters only after the forecast is complete.
                "observed_discharge_m3s": source["observed_discharge_m3s"],
                "physical_open_loop_m3s": source["physical_open_loop_m3s"],
                "physical_constant_state_correction_m3s": source["physical_state_corrected_m3s"],
                "physical_residual_decay_m3s": step.corrected_prediction_m3s,
                "classical_arx_m3s": source["classical_arx_m3s"],
                "action_innovation_wwm_m3s": source["action_innovation_wwm_m3s"],
                "causal_persistence_m3s": source["causal_persistence_m3s"],
                "physical_at_latest_observation_m3s": (step.physical_at_latest_observation_m3s),
                "latest_observation_residual_m3s": (step.latest_observation_residual_m3s),
                "residual_decay_weight": step.decay_weight,
                "elapsed_from_latest_observation_hours": (
                    step.elapsed_from_latest_observation_hours
                ),
                "latest_observation_valid_at_utc": source["latest_observation_valid_at_utc"],
                "latest_observation_available_at_utc": source[
                    "latest_observation_available_at_utc"
                ],
                "residual_decay_clipped": step.clipped,
                "future_target_observation_used_for_correction": False,
                "target_parameter_refit_performed": False,
                "operational_vintages_verified": False,
                "residual_decay_parameter_sha256": parameter_sha256,
                "source_physical_prediction_sha256": source["source_physical_prediction_sha256"],
                "arx_parameter_sha256": source["arx_parameter_sha256"],
                "wwm_parameter_sha256": source["wwm_parameter_sha256"],
            }
        )
    columns = {
        "physical_open_loop": "physical_open_loop_m3s",
        "physical_constant_state_correction": ("physical_constant_state_correction_m3s"),
        "physical_residual_decay": "physical_residual_decay_m3s",
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
            "residual_decay_clipped_row_count": clipped_count,
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
        "physical_state_corrected_m3s",
        "classical_arx_m3s",
        "action_innovation_wwm_m3s",
        "causal_persistence_m3s",
        "physical_at_latest_observation_m3s",
        "latest_observation_residual_m3s",
        "latest_observation_valid_at_utc",
        "latest_observation_available_at_utc",
        "source_physical_prediction_sha256",
        "arx_parameter_sha256",
        "wwm_parameter_sha256",
    }
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValueError("physical_residual_decay_comparison_columns_invalid")
    rows = list(reader)
    if not rows or any(row["system_id"] != TARGET_SYSTEM_ID for row in rows):
        raise ValueError("physical_residual_decay_comparison_axis_invalid")
    return rows


def _comparison(
    metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> dict[str, Any]:
    comparators = {
        "raw_physical": "physical_open_loop",
        "constant_correction": "physical_constant_state_correction",
        "arx": "classical_arx",
        "wwm": "action_innovation_wwm",
        "persistence": "causal_persistence",
    }
    per_horizon: dict[str, dict[str, float]] = {}
    for horizon in HORIZONS:
        horizon_metrics = metrics[str(horizon)]
        decay_rmse = horizon_metrics["physical_residual_decay"]["rmse_m3s"]
        per_horizon[str(horizon)] = {
            f"decay_minus_{name}_rmse_m3s": (decay_rmse - horizon_metrics[metric_name]["rmse_m3s"])
            for name, metric_name in comparators.items()
        }
    result: dict[str, Any] = {"per_horizon": per_horizon}
    for name in comparators:
        result[f"decay_beats_{name}_all_horizons"] = all(
            values[f"decay_minus_{name}_rmse_m3s"] < 0.0 for values in per_horizon.values()
        )
        result[f"decay_beats_{name}_horizons_hours"] = [
            horizon
            for horizon in HORIZONS
            if per_horizon[str(horizon)][f"decay_minus_{name}_rmse_m3s"] < 0.0
        ]
    return result


def _verify_metric_replay(*, result: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    mapping = {
        "physical_open_loop": "physical_open_loop",
        "physical_constant_state_correction": "physical_state_corrected",
        "classical_arx": "classical_arx",
        "action_innovation_wwm": "action_innovation_wwm",
        "causal_persistence": "causal_persistence",
    }
    for horizon in HORIZONS:
        actual = result["metrics_by_horizon"][str(horizon)]
        prior = expected["metrics_by_horizon"][str(horizon)]
        for actual_name, prior_name in mapping.items():
            if actual[actual_name] != prior[prior_name]:
                raise ValueError("physical_residual_decay_metric_replay_mismatch")
    if result["scoring"] != expected["scoring"]:
        raise ValueError("physical_residual_decay_scoring_replay_mismatch")


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
        "primary_predictions": (args.output_root / "j_percy_priest_primary_predictions.csv"),
        "replication_predictions": (
            args.output_root / "j_percy_priest_replication_predictions.csv"
        ),
    }
    bodies, report = compile_physical_residual_decay_transfer_posthoc(
        source_physical_report_path=args.source_physical_report,
        source_outcome_report_path=args.source_outcome_report,
        replication_source_physical_report_path=(args.replication_source_physical_report),
        replication_source_outcome_report_path=(args.replication_source_outcome_report),
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
    print(
        "source_residual_decay_coefficient="
        f"{report['source_fit_contract']['residual_decay_coefficient']:.9f}"
    )
    for window_name in ("primary_window", "replication_window"):
        for horizon in HORIZONS:
            values = report[window_name]["comparison"]["per_horizon"][str(horizon)]
            print(
                f"window={window_name} horizon={horizon}h "
                f"decay_minus_raw_rmse="
                f"{values['decay_minus_raw_physical_rmse_m3s']:.6f} "
                f"decay_minus_constant_rmse="
                f"{values['decay_minus_constant_correction_rmse_m3s']:.6f} "
                f"decay_minus_wwm_rmse="
                f"{values['decay_minus_wwm_rmse_m3s']:.6f}"
            )


if __name__ == "__main__":
    main()
