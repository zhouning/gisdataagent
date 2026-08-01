#!/usr/bin/env python3
"""Compare WWM with sealed physical routing and causal state correction."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

if __package__:
    from scripts import evaluate_geospatial_kernel_action_innovation_candidate as candidate
    from scripts import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    from scripts import evaluate_geospatial_kernel_traditional_arx_baseline as arx
else:
    import evaluate_geospatial_kernel_action_innovation_candidate as candidate
    import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    import evaluate_geospatial_kernel_traditional_arx_baseline as arx


REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = Path(__file__).resolve()
DEFAULT_PRIMARY_PHYSICAL_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_rollout_report.json"
)
DEFAULT_REPLICATION_PHYSICAL_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_rollout_report.json"
)
DEFAULT_PRIMARY_PHYSICAL_SCORE = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_score.json"
)
DEFAULT_REPLICATION_PHYSICAL_SCORE = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_score.json"
)
DEFAULT_ARX_REPORT = arx.DEFAULT_REPORT
DEFAULT_TROUTE_EXECUTION_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/t_route_mc_execution_semantics_report.json"
)
DEFAULT_TROUTE_DIAGNOSTIC_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/t_route_mc_initialized_diagnostic_response_matrix.json"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/geospatial_kernel_physical_routing_state_correction_posthoc"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_physical_routing_state_correction_posthoc_report.json"
)

SCHEMA = "gwm.geotransport.geospatial_kernel_physical_routing_state_correction_posthoc.v1"
PRIMARY_PHYSICAL_SCHEMA = "gwm.geotransport.v2_blind_validation_rollout.v1"
REPLICATION_PHYSICAL_SCHEMA = "gwm.geotransport.kinematic_wave_holdout_rollout.v2"
TROUTE_EXECUTION_SCHEMA = "gwm.geotransport.t_route_mc_execution_semantics.v1"
TROUTE_DIAGNOSTIC_SCHEMA = "gwm.geotransport.t_route_mc_initialized_diagnostic_matrix.v1"
HORIZONS = arx.HORIZONS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--primary-physical-report",
        type=Path,
        default=DEFAULT_PRIMARY_PHYSICAL_REPORT,
    )
    parser.add_argument(
        "--replication-physical-report",
        type=Path,
        default=DEFAULT_REPLICATION_PHYSICAL_REPORT,
    )
    parser.add_argument("--arx-report", type=Path, default=DEFAULT_ARX_REPORT)
    parser.add_argument(
        "--troute-execution-report",
        type=Path,
        default=DEFAULT_TROUTE_EXECUTION_REPORT,
    )
    parser.add_argument(
        "--troute-diagnostic-report",
        type=Path,
        default=DEFAULT_TROUTE_DIAGNOSTIC_REPORT,
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_physical_routing_state_correction_posthoc(
    *,
    primary_physical_report_path: Path = DEFAULT_PRIMARY_PHYSICAL_REPORT,
    replication_physical_report_path: Path = (DEFAULT_REPLICATION_PHYSICAL_REPORT),
    arx_report_path: Path = DEFAULT_ARX_REPORT,
    troute_execution_report_path: Path = DEFAULT_TROUTE_EXECUTION_REPORT,
    troute_diagnostic_report_path: Path = DEFAULT_TROUTE_DIAGNOSTIC_REPORT,
    primary_prediction_path: Path | None = None,
    replication_prediction_path: Path | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    primary_prediction_path = primary_prediction_path or (
        DEFAULT_OUTPUT_ROOT / "j_percy_priest_primary_predictions.csv"
    )
    replication_prediction_path = replication_prediction_path or (
        DEFAULT_OUTPUT_ROOT / "j_percy_priest_replication_predictions.csv"
    )

    arx_report_body, arx_report = _load_arx_report(arx_report_path)
    primary_arx_descriptor = arx_report["outputs"]["primary_predictions"]
    replication_arx_descriptor = arx_report["outputs"]["replication_predictions"]
    primary_arx_body = cross._read_verified(primary_arx_descriptor)
    replication_arx_body = cross._read_verified(replication_arx_descriptor)

    primary_physical = _load_physical_rollout(
        path=primary_physical_report_path,
        expected_schema=PRIMARY_PHYSICAL_SCHEMA,
        expected_operator="BranchingManningNetworkTransportOperator",
        value_column="kernel_full_subnetwork_m3s",
        require_all_execution_gates=False,
    )
    replication_physical = _load_physical_rollout(
        path=replication_physical_report_path,
        expected_schema=REPLICATION_PHYSICAL_SCHEMA,
        expected_operator="BranchingFiniteVolumeKinematicWaveOperator",
        value_column="kinematic_wave_m3s",
        require_all_execution_gates=True,
    )
    troute = _load_troute_decision(
        execution_path=troute_execution_report_path,
        diagnostic_path=troute_diagnostic_report_path,
    )
    original_score_scope = _load_original_score_scope()

    primary_body, primary_result = _compile_window(
        arx_prediction_body=primary_arx_body,
        physical_prediction_body=primary_physical["prediction_body"],
        physical_value_column=primary_physical["value_column"],
        physical_prediction_sha256=primary_physical["prediction_descriptor"]["sha256"],
        physical_operator=primary_physical["operator"],
    )
    replication_body, replication_result = _compile_window(
        arx_prediction_body=replication_arx_body,
        physical_prediction_body=replication_physical["prediction_body"],
        physical_value_column=replication_physical["value_column"],
        physical_prediction_sha256=replication_physical["prediction_descriptor"]["sha256"],
        physical_operator=replication_physical["operator"],
    )
    _verify_arx_metric_replay(
        result=primary_result,
        expected=arx_report["primary_window"],
    )
    _verify_arx_metric_replay(
        result=replication_result,
        expected=arx_report["replication_window"],
    )

    outputs = {
        "primary_predictions": primary_body,
        "replication_predictions": replication_body,
    }
    results = (primary_result, replication_result)
    report = {
        "schema": SCHEMA,
        "status": "traditional_physical_routing_state_correction_posthoc_complete",
        "generated_at": datetime.now(UTC).isoformat(),
        "implementation_artifacts": {
            "evaluator": _artifact(EVALUATOR_PATH, EVALUATOR_PATH.read_bytes())
        },
        "source_artifacts": {
            "arx_comparison_report": _artifact(arx_report_path, arx_report_body),
            "primary_arx_comparison_rows": dict(primary_arx_descriptor),
            "replication_arx_comparison_rows": dict(replication_arx_descriptor),
            "primary_physical_rollout_report": _artifact(
                primary_physical_report_path,
                primary_physical["report_body"],
            ),
            "primary_sealed_physical_predictions": dict(primary_physical["prediction_descriptor"]),
            "replication_physical_rollout_report": _artifact(
                replication_physical_report_path,
                replication_physical["report_body"],
            ),
            "replication_sealed_physical_predictions": dict(
                replication_physical["prediction_descriptor"]
            ),
            "primary_original_sealed_score": _artifact(
                DEFAULT_PRIMARY_PHYSICAL_SCORE,
                original_score_scope["primary_body"],
            ),
            "replication_original_sealed_score": _artifact(
                DEFAULT_REPLICATION_PHYSICAL_SCORE,
                original_score_scope["replication_body"],
            ),
            "t_route_mc_execution_semantics_report": _artifact(
                troute_execution_report_path, troute["execution_body"]
            ),
            "t_route_mc_initialized_diagnostic_report": _artifact(
                troute_diagnostic_report_path, troute["diagnostic_body"]
            ),
        },
        "outputs": {
            "primary_predictions": _artifact(primary_prediction_path, primary_body),
            "replication_predictions": _artifact(replication_prediction_path, replication_body),
        },
        "comparator_contract": {
            "model_family": "sealed_physical_router_with_additive_state_residual",
            "formula": (
                "max(0, physical(target) + observed(latest_available) "
                "- physical(latest_observation_time))"
            ),
            "fitted_parameter_count": 0,
            "parameter_fit_performed": False,
            "per_window_refit_performed": False,
            "future_target_observation_used_for_correction": False,
            "latest_available_outlet_observation_only": True,
            "same_target_rows_as_arx_wwm_and_persistence": True,
            "raw_physical_rollouts_reexecuted": False,
            "raw_physical_prediction_bytes_modified": False,
            "raw_physical_prediction_sha256_verified": True,
            "nonnegative_discharge_clip_is_fixed_not_tuned": True,
        },
        "operator_identity": {
            "primary_window": primary_physical["operator_contract"],
            "replication_window": replication_physical["operator_contract"],
            "same_operator_form_across_windows": False,
        },
        "scoring_scope_boundary": {
            "original_sealed_score": original_score_scope["summary"],
            "original_persistence_definition": (
                "observation at physical support_start for the observation at "
                "support_end; an immediate prior-hour baseline"
            ),
            "this_comparison_persistence_definition": (
                "latest observation available at WWM issue time, valid one hour "
                "before issue, held to issue plus forecast horizon"
            ),
            "horizon_1_latest_state_age_at_target_hours": 2,
            "raw_physical_beats_original_immediate_prior_hour_persistence": False,
            "raw_physical_beats_wwm_latency_matched_persistence_all_horizons": (
                all(
                    values["raw_physical_minus_persistence_rmse_m3s"] < 0.0
                    for result in results
                    for values in result["comparison"]["per_horizon"].values()
                )
            ),
            "persistence_results_are_not_contradictory": True,
        },
        "primary_window": primary_result,
        "replication_window": replication_result,
        "diagnostic_interpretation": {
            "state_correction_beats_raw_physical_all_horizons_in_both_windows": (
                all(
                    result["comparison"]["state_corrected_beats_raw_physical_all_horizons"]
                    for result in results
                )
            ),
            "state_correction_beats_arx_all_horizons_in_both_windows": all(
                result["comparison"]["state_corrected_beats_arx_all_horizons"] for result in results
            ),
            "state_correction_beats_wwm_all_horizons_in_both_windows": all(
                result["comparison"]["state_corrected_beats_wwm_all_horizons"] for result in results
            ),
            "state_correction_beats_persistence_all_horizons_in_both_windows": (
                all(
                    result["comparison"]["state_corrected_beats_persistence_all_horizons"]
                    for result in results
                )
            ),
            "benchmark_role": (
                "measure whether sealed open-loop physical routing gains from "
                "the same causal issue-state anchoring available to WWM"
            ),
            "arx_remains_required_minimum_statistical_baseline": True,
            "result_may_trigger_refit_on_these_windows": False,
        },
        "t_route_mc_decision": {
            "fixed_commit_initialization_gate_passed": False,
            "promotion_gate_passed": False,
            "derived_initialized_runtime_professional_baseline_eligible": False,
            "derived_initialized_runtime_negative_lobe_gate_passed": False,
            "derived_initialized_runtime_timestep_stability_gate_passed": False,
            "role_in_this_comparison": "excluded_from_professional_baseline",
            "generic_muskingum_cunge_family_impugned": False,
            "reason": (
                "the audited fixed commit reads output variables before "
                "assignment and the derived initialized runtime fails its "
                "professional eligibility boundary"
            ),
        },
        "information_boundary": {
            "raw_physical_predictions_were_sealed_outcome_free": True,
            "historical_outcomes_were_exposed_before_this_correction_design": True,
            "latest_outlet_observation_used_at_issue_time": True,
            "future_target_observation_used_inside_forecast": False,
            "historical_realized_action_used_by_raw_physical_rollout": True,
            "retrospective_nwm_forcing_used_by_raw_physical_rollout": True,
            "operational_issue_time_vintages_verified": False,
            "evaluation_counts_as_fresh_validation": False,
            "fresh_prospective_window_consumed": False,
        },
        "claim_boundary": {
            "traditional_physical_router_posthoc_comparison_executed": True,
            "physical_state_correction_admitted": False,
            "physical_operator_admitted": False,
            "professional_baseline_admitted": False,
            "wwm_candidate_admitted": False,
            "geospatial_kernel_validated": False,
            "multi_system_generalization_validated": False,
            "operational_forecast_validated": False,
            "runtime_default_enabled": False,
        },
    }
    return outputs, report


def _load_arx_report(path: Path) -> tuple[bytes, Mapping[str, Any]]:
    body, report = cross._load_json(path)
    claim = report.get("claim_boundary") or {}
    information = report.get("information_boundary") or {}
    outputs = report.get("outputs") or {}
    if (
        report.get("schema") != arx.SCHEMA
        or report.get("status") != "traditional_arx_zero_refit_posthoc_benchmark_complete"
        or claim.get("traditional_arx_posthoc_benchmark_executed") is not True
        or claim.get("geospatial_kernel_validated") is not False
        or information.get("evaluation_counts_as_fresh_validation") is not False
        or not {"primary_predictions", "replication_predictions"}.issubset(outputs)
    ):
        raise ValueError("physical_state_correction_arx_report_invalid")
    return body, report


def _load_physical_rollout(
    *,
    path: Path,
    expected_schema: str,
    expected_operator: str,
    value_column: str,
    require_all_execution_gates: bool,
) -> dict[str, Any]:
    report_body, report = cross._load_json(path)
    system = (report.get("systems") or {}).get(cross.SYSTEM_ID) or {}
    data_isolation = system.get("data_isolation") or {}
    invariants = system.get("invariants") or {}
    execution = system.get("registered_execution") or {}
    claim = report.get("claim_boundary") or {}
    descriptor = system.get("prediction_artifact") or {}
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
        or claim.get("predictions_scored") is not False
        or invariants.get("zero_state_zero_input_identity_passed") is not True
        or not gates_valid
    ):
        raise ValueError("physical_state_correction_rollout_report_invalid")
    prediction_body = cross._read_verified(descriptor)
    prediction_count = len(_physical_series(prediction_body, value_column=value_column))
    if prediction_count != int(
        system.get("result", {}).get("prediction_count", -1)
    ) or prediction_count != int(report.get("window", {}).get("hour_count", -1)):
        raise ValueError("physical_state_correction_prediction_count_invalid")
    operator_contract = {
        "operator": expected_operator,
        "prediction_value_column": value_column,
        "network_mode": execution.get("network_mode"),
        "feature_count": execution.get("feature_count"),
        "outcome_free_prediction_sealed": True,
        "conservation_gate_passed": True,
        "operator_form_admitted": bool(
            execution.get("operator_form", True) and claim.get("operator_form_admitted", False)
        ),
        "diagnostic_only": bool(execution.get("diagnostic_only", False)),
    }
    return {
        "report_body": report_body,
        "prediction_body": prediction_body,
        "prediction_descriptor": descriptor,
        "value_column": value_column,
        "operator": expected_operator,
        "operator_contract": operator_contract,
    }


def _load_troute_decision(*, execution_path: Path, diagnostic_path: Path) -> dict[str, bytes]:
    execution_body, execution = cross._load_json(execution_path)
    diagnostic_body, diagnostic = cross._load_json(diagnostic_path)
    execution_claim = execution.get("claim_boundary") or {}
    diagnostic_claim = diagnostic.get("claim_boundary") or {}
    diagnostic_gates = diagnostic.get("gates") or {}
    if (
        execution.get("schema") != TROUTE_EXECUTION_SCHEMA
        or execution_claim.get("fixed_commit_kernel_initialization_gate_passed") is not False
        or execution_claim.get("t_route_mc_promotion_gate_passed") is not False
        or diagnostic.get("schema") != TROUTE_DIAGNOSTIC_SCHEMA
        or diagnostic_claim.get("professional_baseline_eligible") is not False
        or diagnostic_gates.get("all_diagnostic_gates_passed") is not False
        or diagnostic_gates.get("all_outlet_negative_lobes_within_tolerance") is not False
        or diagnostic_gates.get("timestep_stability") is not False
    ):
        raise ValueError("physical_state_correction_troute_decision_invalid")
    return {
        "execution_body": execution_body,
        "diagnostic_body": diagnostic_body,
    }


def _load_original_score_scope() -> dict[str, Any]:
    primary_body, primary = cross._load_json(DEFAULT_PRIMARY_PHYSICAL_SCORE)
    replication_body, replication = cross._load_json(DEFAULT_REPLICATION_PHYSICAL_SCORE)
    primary_system = (primary.get("systems") or {}).get(cross.SYSTEM_ID) or {}
    replication_system = (replication.get("systems") or {}).get(cross.SYSTEM_ID) or {}
    primary_metrics = primary_system.get("metrics") or {}
    replication_metrics = replication_system.get("metrics") or {}
    primary_physical = primary_metrics.get("kernel_full_subnetwork") or {}
    primary_persistence = primary_metrics.get("observed_persistence") or {}
    replication_physical = replication_metrics.get("kinematic_wave") or {}
    replication_persistence = replication_metrics.get("observed_persistence") or {}
    if (
        primary.get("schema") != "gwm.geotransport.v2_blind_validation_score.v1"
        or primary.get("status") != "two_system_blind_validation_scored_once"
        or primary_system.get("gates", {}).get("kernel_beats_observed_persistence_rmse")
        is not False
        or replication.get("schema") != "gwm.geotransport.kinematic_wave_holdout_score.v2"
        or replication.get("status") != "two_system_kinematic_wave_holdout_scored_once"
        or replication_system.get("gates", {}).get("kinematic_beats_observed_persistence_rmse")
        is not False
        or float(primary_physical.get("rmse_m3s", math.nan))
        <= float(primary_persistence.get("rmse_m3s", math.nan))
        or float(replication_physical.get("rmse_m3s", math.nan))
        <= float(replication_persistence.get("rmse_m3s", math.nan))
    ):
        raise ValueError("physical_state_correction_original_score_scope_invalid")
    return {
        "primary_body": primary_body,
        "replication_body": replication_body,
        "summary": {
            "primary_window": {
                "physical_open_loop_rmse_m3s": primary_physical["rmse_m3s"],
                "immediate_prior_hour_persistence_rmse_m3s": (primary_persistence["rmse_m3s"]),
                "physical_minus_persistence_rmse_m3s": (
                    primary_physical["rmse_m3s"] - primary_persistence["rmse_m3s"]
                ),
            },
            "replication_window": {
                "physical_open_loop_rmse_m3s": replication_physical["rmse_m3s"],
                "immediate_prior_hour_persistence_rmse_m3s": (replication_persistence["rmse_m3s"]),
                "physical_minus_persistence_rmse_m3s": (
                    replication_physical["rmse_m3s"] - replication_persistence["rmse_m3s"]
                ),
            },
        },
    }


def _compile_window(
    *,
    arx_prediction_body: bytes,
    physical_prediction_body: bytes,
    physical_value_column: str,
    physical_prediction_sha256: str,
    physical_operator: str,
) -> tuple[bytes, dict[str, Any]]:
    physical = _physical_series(physical_prediction_body, value_column=physical_value_column)
    source_rows = _arx_rows(arx_prediction_body)
    rows: list[dict[str, object]] = []
    clipped_count = 0
    issue_times: set[datetime] = set()
    for source in source_rows:
        prediction = _state_corrected_prediction(source, physical)
        clipped_count += int(prediction["clipped"])
        issue_times.add(prediction["issue_time"])
        rows.append(
            {
                "system_id": source["system_id"],
                "issue_time_utc": source["issue_time_utc"],
                "target_support_end_utc": source["target_support_end_utc"],
                "horizon_hours": int(source["horizon_hours"]),
                # The target outcome enters only here, after all forecasts exist.
                "observed_discharge_m3s": source["observed_discharge_m3s"],
                "physical_open_loop_m3s": prediction["raw_target"],
                "physical_state_corrected_m3s": prediction["corrected"],
                "classical_arx_m3s": source["classical_arx_m3s"],
                "action_innovation_wwm_m3s": source["action_innovation_wwm_m3s"],
                "causal_persistence_m3s": source["causal_persistence_m3s"],
                "physical_at_latest_observation_m3s": prediction["raw_state"],
                "latest_observation_residual_m3s": prediction["residual"],
                "latest_observation_valid_at_utc": source["latest_observation_valid_at_utc"],
                "latest_observation_available_at_utc": source[
                    "latest_observation_available_at_utc"
                ],
                "state_correction_clipped": prediction["clipped"],
                "future_target_observation_used_for_correction": False,
                "physical_parameter_refit_performed": False,
                "operational_vintages_verified": False,
                "physical_operator": physical_operator,
                "source_physical_prediction_sha256": physical_prediction_sha256,
                "arx_parameter_sha256": source["arx_parameter_sha256"],
                "wwm_parameter_sha256": source["wwm_parameter_sha256"],
            }
        )
    columns = {
        "physical_open_loop": "physical_open_loop_m3s",
        "physical_state_corrected": "physical_state_corrected_m3s",
        "classical_arx": "classical_arx_m3s",
        "action_innovation_wwm": "action_innovation_wwm_m3s",
        "causal_persistence": "causal_persistence_m3s",
    }
    metrics, scoring = candidate._score(rows, columns)
    comparison = _comparison(metrics)
    return cross._encode_rows(rows), {
        "window": {
            "first_issue_time_utc": _iso(min(issue_times)),
            "last_issue_time_utc": _iso(max(issue_times)),
            "horizons_hours": list(HORIZONS),
            "physical_operator": physical_operator,
        },
        "metrics_by_horizon": metrics,
        "comparison": comparison,
        "scoring": scoring,
        "execution": {
            "prediction_row_count": len(rows),
            "forecast_issue_count": len(issue_times),
            "state_correction_clipped_row_count": clipped_count,
            "raw_physical_prediction_count": len(physical),
            "raw_physical_rollout_reexecuted": False,
            "physical_parameter_refit_performed": False,
            "future_target_observation_used_for_correction": False,
        },
    }


def _state_corrected_prediction(
    source: Mapping[str, str], physical: Mapping[datetime, float]
) -> dict[str, Any]:
    issue_time = cross._parse_time(source["issue_time_utc"])
    target_time = cross._parse_time(source["target_support_end_utc"])
    state_time = cross._parse_time(source["latest_observation_valid_at_utc"])
    available_time = cross._parse_time(source["latest_observation_available_at_utc"])
    horizon = int(source["horizon_hours"])
    if (
        source["system_id"] != cross.SYSTEM_ID
        or horizon not in HORIZONS
        or target_time != issue_time + timedelta(hours=horizon)
        or not state_time < issue_time
        or available_time > issue_time
        or source["future_outcome_observation_used"] != "False"
        or source["operational_vintages_verified"] != "False"
    ):
        raise ValueError("physical_state_correction_comparison_row_invalid")
    try:
        raw_target = physical[target_time]
        raw_state = physical[state_time]
    except KeyError as exc:
        raise ValueError("physical_state_correction_time_support_missing") from exc
    latest_observed = float(source["causal_persistence_m3s"])
    if not math.isfinite(latest_observed) or latest_observed < 0.0:
        raise ValueError("physical_state_correction_issue_observation_invalid")
    residual = latest_observed - raw_state
    unbounded = raw_target + residual
    corrected = max(0.0, unbounded)
    return {
        "issue_time": issue_time,
        "raw_target": raw_target,
        "raw_state": raw_state,
        "residual": residual,
        "corrected": corrected,
        "clipped": unbounded < 0.0,
    }


def _physical_series(body: bytes, *, value_column: str) -> dict[datetime, float]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    required = {"support_start_utc", "support_end_utc", value_column}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValueError("physical_state_correction_physical_columns_invalid")
    values: dict[datetime, float] = {}
    previous_end: datetime | None = None
    for row in reader:
        start = cross._parse_time(row["support_start_utc"])
        end = cross._parse_time(row["support_end_utc"])
        value = float(row[value_column])
        if (
            end != start + timedelta(hours=1)
            or (previous_end is not None and start != previous_end)
            or end in values
            or not math.isfinite(value)
            or value < 0.0
        ):
            raise ValueError("physical_state_correction_physical_axis_invalid")
        values[end] = value
        previous_end = end
    if not values:
        raise ValueError("physical_state_correction_physical_axis_invalid")
    return values


def _arx_rows(body: bytes) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    required = {
        "system_id",
        "issue_time_utc",
        "target_support_end_utc",
        "horizon_hours",
        "observed_discharge_m3s",
        "classical_arx_m3s",
        "action_innovation_wwm_m3s",
        "causal_persistence_m3s",
        "latest_observation_valid_at_utc",
        "latest_observation_available_at_utc",
        "future_outcome_observation_used",
        "operational_vintages_verified",
        "arx_parameter_sha256",
        "wwm_parameter_sha256",
    }
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValueError("physical_state_correction_arx_columns_invalid")
    rows = list(reader)
    keys = {
        (
            row["issue_time_utc"],
            row["target_support_end_utc"],
            row["horizon_hours"],
        )
        for row in rows
    }
    if not rows or len(keys) != len(rows):
        raise ValueError("physical_state_correction_arx_axis_invalid")
    return rows


def _comparison(
    metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> dict[str, Any]:
    comparators = {
        "raw_physical": "physical_open_loop",
        "arx": "classical_arx",
        "wwm": "action_innovation_wwm",
        "persistence": "causal_persistence",
    }
    per_horizon: dict[str, dict[str, float]] = {}
    for horizon in HORIZONS:
        horizon_metrics = metrics[str(horizon)]
        corrected_rmse = horizon_metrics["physical_state_corrected"]["rmse_m3s"]
        values = {
            f"state_corrected_minus_{name}_rmse_m3s": (
                corrected_rmse - horizon_metrics[metric_name]["rmse_m3s"]
            )
            for name, metric_name in comparators.items()
        }
        values["raw_physical_minus_persistence_rmse_m3s"] = (
            horizon_metrics["physical_open_loop"]["rmse_m3s"]
            - horizon_metrics["causal_persistence"]["rmse_m3s"]
        )
        per_horizon[str(horizon)] = values
    result: dict[str, Any] = {"per_horizon": per_horizon}
    for name in comparators:
        result[f"state_corrected_beats_{name}_all_horizons"] = all(
            values[f"state_corrected_minus_{name}_rmse_m3s"] < 0.0
            for values in per_horizon.values()
        )
        result[f"state_corrected_beats_{name}_horizons_hours"] = [
            horizon
            for horizon in HORIZONS
            if per_horizon[str(horizon)][f"state_corrected_minus_{name}_rmse_m3s"] < 0.0
        ]
    return result


def _verify_arx_metric_replay(*, result: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    for horizon in HORIZONS:
        actual = result["metrics_by_horizon"][str(horizon)]
        prior = expected["metrics_by_horizon"][str(horizon)]
        for model in (
            "classical_arx",
            "action_innovation_wwm",
            "causal_persistence",
        ):
            if actual[model] != prior[model]:
                raise ValueError("physical_state_correction_arx_metric_replay_mismatch")
    if result["scoring"] != expected["scoring"]:
        raise ValueError("physical_state_correction_scoring_replay_mismatch")


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
        "primary_predictions": (args.output_root / "j_percy_priest_primary_predictions.csv"),
        "replication_predictions": (
            args.output_root / "j_percy_priest_replication_predictions.csv"
        ),
    }
    bodies, report = compile_physical_routing_state_correction_posthoc(
        primary_physical_report_path=args.primary_physical_report,
        replication_physical_report_path=args.replication_physical_report,
        arx_report_path=args.arx_report,
        troute_execution_report_path=args.troute_execution_report,
        troute_diagnostic_report_path=args.troute_diagnostic_report,
        primary_prediction_path=paths["primary_predictions"],
        replication_prediction_path=paths["replication_predictions"],
    )
    args.output_root.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    for name, body in bodies.items():
        paths[name].write_bytes(body)
    args.report.write_bytes(_json_body(report))
    print(f"status={report['status']}")
    for window_name in ("primary_window", "replication_window"):
        for horizon in HORIZONS:
            values = report[window_name]["comparison"]["per_horizon"][str(horizon)]
            print(
                f"window={window_name} horizon={horizon}h "
                "corrected_minus_raw_rmse="
                f"{values['state_corrected_minus_raw_physical_rmse_m3s']:.6f} "
                "corrected_minus_arx_rmse="
                f"{values['state_corrected_minus_arx_rmse_m3s']:.6f} "
                "corrected_minus_wwm_rmse="
                f"{values['state_corrected_minus_wwm_rmse_m3s']:.6f}"
            )


if __name__ == "__main__":
    main()
