#!/usr/bin/env python3
"""Test whether frozen WWM innovation transfers as a physical-model correction."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    ActionInnovationTransitionParameters,
    action_innovation_transition_parameters_from_dict,
)
from data_agent.uwm.geospatial_kernel_v2.physical_action_innovation import (
    PHYSICAL_ACTION_INNOVATION_SCHEMA,
    PhysicalActionInnovationParameters,
    fit_physical_action_innovation,
    physical_action_innovation_parameters_from_dict,
)

if __package__:
    from scripts import evaluate_geospatial_kernel_action_innovation_candidate as candidate
    from scripts import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    from scripts import evaluate_geospatial_kernel_physical_residual_decay_transfer as decay
    from scripts import evaluate_geospatial_kernel_physical_residual_retention_transfer as retention
    from scripts import evaluate_geospatial_kernel_physical_routing_state_correction as baseline
else:
    import evaluate_geospatial_kernel_action_innovation_candidate as candidate
    import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    import evaluate_geospatial_kernel_physical_residual_decay_transfer as decay
    import evaluate_geospatial_kernel_physical_residual_retention_transfer as retention
    import evaluate_geospatial_kernel_physical_routing_state_correction as baseline


REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = Path(__file__).resolve()
CORE_OPERATOR_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/physical_action_innovation.py"
)
DEFAULT_FREEZE = cross.DEFAULT_FREEZE
DEFAULT_SOURCE_INPUT_REPORT = cross.DEFAULT_INPUT_REPORT
DEFAULT_SOURCE_OUTCOME_REPORT = cross.DEFAULT_OUTCOME_REPORT
DEFAULT_REPLICATION_SOURCE_INPUT_REPORT = cross.DEFAULT_REPLICATION_INPUT_REPORT
DEFAULT_REPLICATION_SOURCE_OUTCOME_REPORT = cross.DEFAULT_REPLICATION_OUTCOME_REPORT
DEFAULT_SOURCE_PHYSICAL_REPORT = decay.DEFAULT_SOURCE_PHYSICAL_REPORT
DEFAULT_REPLICATION_SOURCE_PHYSICAL_REPORT = decay.DEFAULT_REPLICATION_SOURCE_PHYSICAL_REPORT
DEFAULT_COMPARISON_REPORT = retention.DEFAULT_REPORT
DEFAULT_OUTPUT_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/geospatial_kernel_physical_action_innovation_transfer_posthoc"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_physical_action_innovation_transfer_posthoc_report.json"
)

SCHEMA = "gwm.geotransport.geospatial_kernel_physical_action_innovation_transfer.v1"
HORIZONS = baseline.HORIZONS
SOURCE_SYSTEM_ID = "center_hill"
TARGET_SYSTEM_ID = cross.SYSTEM_ID


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--source-input-report", type=Path, default=DEFAULT_SOURCE_INPUT_REPORT)
    parser.add_argument("--source-outcome-report", type=Path, default=DEFAULT_SOURCE_OUTCOME_REPORT)
    parser.add_argument(
        "--replication-source-input-report",
        type=Path,
        default=DEFAULT_REPLICATION_SOURCE_INPUT_REPORT,
    )
    parser.add_argument(
        "--replication-source-outcome-report",
        type=Path,
        default=DEFAULT_REPLICATION_SOURCE_OUTCOME_REPORT,
    )
    parser.add_argument(
        "--source-physical-report", type=Path, default=DEFAULT_SOURCE_PHYSICAL_REPORT
    )
    parser.add_argument(
        "--replication-source-physical-report",
        type=Path,
        default=DEFAULT_REPLICATION_SOURCE_PHYSICAL_REPORT,
    )
    parser.add_argument("--comparison-report", type=Path, default=DEFAULT_COMPARISON_REPORT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_physical_action_innovation_transfer_posthoc(
    *,
    freeze_path: Path = DEFAULT_FREEZE,
    source_input_report_path: Path = DEFAULT_SOURCE_INPUT_REPORT,
    source_outcome_report_path: Path = DEFAULT_SOURCE_OUTCOME_REPORT,
    replication_source_input_report_path: Path = DEFAULT_REPLICATION_SOURCE_INPUT_REPORT,
    replication_source_outcome_report_path: Path = DEFAULT_REPLICATION_SOURCE_OUTCOME_REPORT,
    source_physical_report_path: Path = DEFAULT_SOURCE_PHYSICAL_REPORT,
    replication_source_physical_report_path: Path = DEFAULT_REPLICATION_SOURCE_PHYSICAL_REPORT,
    comparison_report_path: Path = DEFAULT_COMPARISON_REPORT,
    parameter_path: Path | None = None,
    source_wwm_prediction_path: Path | None = None,
    replication_source_wwm_prediction_path: Path | None = None,
    primary_prediction_path: Path | None = None,
    replication_prediction_path: Path | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    parameter_path = parameter_path or DEFAULT_OUTPUT_ROOT / "parameters.json"
    source_wwm_prediction_path = source_wwm_prediction_path or (
        DEFAULT_OUTPUT_ROOT / "center_hill_source_wwm_predictions.csv"
    )
    replication_source_wwm_prediction_path = replication_source_wwm_prediction_path or (
        DEFAULT_OUTPUT_ROOT / "center_hill_replication_wwm_predictions.csv"
    )
    primary_prediction_path = primary_prediction_path or (
        DEFAULT_OUTPUT_ROOT / "j_percy_priest_primary_predictions.csv"
    )
    replication_prediction_path = replication_prediction_path or (
        DEFAULT_OUTPUT_ROOT / "j_percy_priest_replication_predictions.csv"
    )

    freeze_body, freeze, wwm_parameter_body, wwm_parameters = _load_frozen_wwm(freeze_path)
    wwm_parameter_sha256 = hashlib.sha256(wwm_parameter_body).hexdigest()
    source_wwm = _load_source_wwm_window(
        input_report_path=source_input_report_path,
        outcome_report_path=source_outcome_report_path,
        expected_input_schema=cross.INPUT_SCHEMA,
        expected_outcome_schema=cross.OUTCOME_SCHEMA,
        parameters=wwm_parameters,
        parameter_sha256=wwm_parameter_sha256,
    )
    source_physical = decay._load_source_physical_rollout(
        path=source_physical_report_path,
        expected_schema=baseline.PRIMARY_PHYSICAL_SCHEMA,
        expected_operator="BranchingManningNetworkTransportOperator",
        value_column="kernel_full_subnetwork_m3s",
        require_all_execution_gates=False,
    )
    source_physical_series = baseline._physical_series(
        source_physical["prediction_body"],
        value_column=source_physical["value_column"],
    )
    fitted = _fit_source_parameter(
        source_rows=source_wwm["rows"],
        physical_series=source_physical_series,
        source_physical=source_physical,
        source_wwm_body=source_wwm["prediction_body"],
        source_wwm_parameter_sha256=wwm_parameter_sha256,
        source_outcome_sha256=source_wwm["outcome_descriptor"]["sha256"],
        provenance_id=(
            "center-hill:2022-03-31--2022-04-28:sealed-physical-plus-global-action-innovation"
        ),
    )
    parameter_body = _json_body(fitted.as_dict())
    parameters = physical_action_innovation_parameters_from_dict(json.loads(parameter_body))
    parameter_sha256 = hashlib.sha256(parameter_body).hexdigest()
    source_fit_result = _score_source_window(
        source_rows=source_wwm["rows"],
        physical_series=source_physical_series,
        parameters=parameters,
    )

    # This later Center Hill coefficient is a stability diagnostic only.
    replication_source_wwm = _load_source_wwm_window(
        input_report_path=replication_source_input_report_path,
        outcome_report_path=replication_source_outcome_report_path,
        expected_input_schema=cross.REPLICATION_INPUT_SCHEMA,
        expected_outcome_schema=cross.REPLICATION_OUTCOME_SCHEMA,
        parameters=wwm_parameters,
        parameter_sha256=wwm_parameter_sha256,
    )
    replication_source_physical = decay._load_source_physical_rollout(
        path=replication_source_physical_report_path,
        expected_schema=baseline.REPLICATION_PHYSICAL_SCHEMA,
        expected_operator="BranchingFiniteVolumeKinematicWaveOperator",
        value_column="kinematic_wave_m3s",
        require_all_execution_gates=True,
    )
    replication_source_physical_series = baseline._physical_series(
        replication_source_physical["prediction_body"],
        value_column=replication_source_physical["value_column"],
    )
    replication_diagnostic = _fit_source_parameter(
        source_rows=replication_source_wwm["rows"],
        physical_series=replication_source_physical_series,
        source_physical=replication_source_physical,
        source_wwm_body=replication_source_wwm["prediction_body"],
        source_wwm_parameter_sha256=wwm_parameter_sha256,
        source_outcome_sha256=replication_source_wwm["outcome_descriptor"]["sha256"],
        provenance_id=(
            "center-hill:2022-11-10--2022-12-08:global-action-innovation-stability-diagnostic-only"
        ),
    )
    replication_source_result = _score_source_window(
        source_rows=replication_source_wwm["rows"],
        physical_series=replication_source_physical_series,
        parameters=replication_diagnostic,
    )

    # Target comparison rows are not loaded until the source parameter is locked.
    comparison_report_body, comparison_report = _load_comparison_report(comparison_report_path)
    primary_source_descriptor = comparison_report["outputs"]["primary_predictions"]
    replication_source_descriptor = comparison_report["outputs"]["replication_predictions"]
    primary_source_body = cross._read_verified(primary_source_descriptor)
    replication_source_body = cross._read_verified(replication_source_descriptor)
    primary_body, primary_result = _compile_target_window(
        source_body=primary_source_body,
        parameters=parameters,
        parameter_sha256=parameter_sha256,
    )
    replication_body, replication_result = _compile_target_window(
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
        "source_wwm_predictions": source_wwm["prediction_body"],
        "replication_source_wwm_predictions": replication_source_wwm["prediction_body"],
        "primary_predictions": primary_body,
        "replication_predictions": replication_body,
    }
    results = (primary_result, replication_result)
    accuracy_passed = all(
        result["comparison"]["hybrid_beats_raw_physical_all_horizons"] for result in results
    )
    report = {
        "schema": SCHEMA,
        "status": "source_fitted_physical_action_innovation_transfer_posthoc_complete",
        "generated_at": datetime.now(UTC).isoformat(),
        "implementation_artifacts": {
            "physical_action_innovation_operator": _artifact(
                CORE_OPERATOR_PATH, CORE_OPERATOR_PATH.read_bytes()
            ),
            "evaluator": _artifact(EVALUATOR_PATH, EVALUATOR_PATH.read_bytes()),
        },
        "source_artifacts": {
            "wwm_candidate_freeze": _artifact(freeze_path, freeze_body),
            "frozen_wwm_parameters": dict(freeze["candidate_artifacts"]["parameters"]),
            "source_input_report": _artifact(
                source_input_report_path, source_wwm["input_report_body"]
            ),
            "source_outcome_report": _artifact(
                source_outcome_report_path, source_wwm["outcome_report_body"]
            ),
            "source_outcome_values": dict(source_wwm["outcome_descriptor"]),
            "source_physical_rollout_report": _artifact(
                source_physical_report_path, source_physical["report_body"]
            ),
            "source_sealed_physical_predictions": dict(source_physical["prediction_descriptor"]),
            "replication_source_input_report": _artifact(
                replication_source_input_report_path,
                replication_source_wwm["input_report_body"],
            ),
            "replication_source_outcome_report": _artifact(
                replication_source_outcome_report_path,
                replication_source_wwm["outcome_report_body"],
            ),
            "replication_source_outcome_values": dict(replication_source_wwm["outcome_descriptor"]),
            "replication_source_physical_rollout_report": _artifact(
                replication_source_physical_report_path,
                replication_source_physical["report_body"],
            ),
            "replication_source_sealed_physical_predictions": dict(
                replication_source_physical["prediction_descriptor"]
            ),
            "target_comparison_report": _artifact(comparison_report_path, comparison_report_body),
            "primary_target_comparison_rows": dict(primary_source_descriptor),
            "replication_target_comparison_rows": dict(replication_source_descriptor),
        },
        "outputs": {
            "parameters": _artifact(parameter_path, parameter_body),
            "source_wwm_predictions": _artifact(
                source_wwm_prediction_path, source_wwm["prediction_body"]
            ),
            "replication_source_wwm_predictions": _artifact(
                replication_source_wwm_prediction_path,
                replication_source_wwm["prediction_body"],
            ),
            "primary_predictions": _artifact(primary_prediction_path, primary_body),
            "replication_predictions": _artifact(replication_prediction_path, replication_body),
        },
        "parameter_lock": {
            "schema": PHYSICAL_ACTION_INNOVATION_SCHEMA,
            "parameter_sha256": parameter_sha256,
            "parameter_body_compiled_before_target_comparison_row_load": True,
            "all_target_windows_use_deserialized_parameter_artifact": True,
        },
        "source_fit_contract": {
            "model_family": "sealed_physical_plus_scaled_wwm_action_innovation",
            "formula": fitted.as_dict()["formula"],
            "estimator": fitted.as_dict()["estimator"],
            "free_parameter_count": 1,
            "innovation_scale_coefficient": parameters.innovation_scale_coefficient,
            "training_pair_count": parameters.training_pair_count,
            "source_system_id": SOURCE_SYSTEM_ID,
            "source_physical_operator": source_physical["operator"],
            "target_system_id": TARGET_SYSTEM_ID,
            "physical_routing_is_primary_trajectory": True,
            "wwm_absolute_discharge_used_as_primary_trajectory": False,
            "target_outcomes_used_for_fit": False,
            "per_target_window_refit_performed": False,
            "same_parameter_used_across_target_windows": True,
        },
        "source_fit_diagnostic": source_fit_result,
        "replication_source_diagnostic": {
            "system_id": SOURCE_SYSTEM_ID,
            "physical_operator": replication_source_physical["operator"],
            "training_pair_count": replication_diagnostic.training_pair_count,
            "innovation_scale_coefficient": (replication_diagnostic.innovation_scale_coefficient),
            "coefficient_minus_frozen_parameter": (
                replication_diagnostic.innovation_scale_coefficient
                - parameters.innovation_scale_coefficient
            ),
            "fit_diagnostic": replication_source_result,
            "used_for_target_prediction": False,
            "admission_evidence": False,
        },
        "transfer_contract": {
            "primary_window": "cross_system_same_window_zero_refit",
            "replication_window": "cross_system_temporal_zero_refit",
            "source_to_target_parameter_refit_performed": False,
            "primary_to_replication_parameter_refit_performed": False,
            "frozen_wwm_parameter_changed": False,
        },
        "primary_window": primary_result,
        "replication_window": replication_result,
        "diagnostic_interpretation": {
            "hybrid_beats_raw_physical_all_horizons_in_both_windows": accuracy_passed,
            "hybrid_beats_wwm_all_horizons_in_both_windows": all(
                result["comparison"]["hybrid_beats_wwm_all_horizons"] for result in results
            ),
            "hybrid_beats_residual_retention_all_horizons_in_both_windows": all(
                result["comparison"]["hybrid_beats_residual_retention_all_horizons"]
                for result in results
            ),
            "existing_wwm_innovation_is_transferable_missing_physics": accuracy_passed,
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
            "physical_action_innovation_promotion_gate_passed": False,
        },
        "information_boundary": {
            "source_center_hill_outcomes_used_for_parameter_fit": True,
            "target_j_percy_priest_outcomes_used_for_parameter_fit": False,
            "target_outcomes_were_exposed_before_model_design": True,
            "future_target_observation_used_inside_forecast": False,
            "historical_realized_action_used_by_wwm": True,
            "retrospective_nwm_forcing_used_by_wwm": True,
            "operational_issue_time_vintages_verified": False,
            "evaluation_counts_as_fresh_validation": False,
            "fresh_prospective_window_consumed": False,
        },
        "claim_boundary": {
            "physical_action_innovation_posthoc_executed": True,
            "physical_action_innovation_admitted": False,
            "physical_action_innovation_promoted": False,
            "existing_wwm_innovation_admitted_as_missing_physics": False,
            "physical_operator_admitted": False,
            "wwm_candidate_admitted": False,
            "geospatial_kernel_validated": False,
            "multi_system_generalization_validated": False,
            "operational_forecast_validated": False,
            "runtime_default_enabled": False,
        },
    }
    return outputs, report


def _load_frozen_wwm(
    path: Path,
) -> tuple[bytes, Mapping[str, Any], bytes, ActionInnovationTransitionParameters]:
    freeze_body, freeze = cross._load_json(path)
    cross._validate_freeze(freeze)
    parameter_body = cross._read_verified(freeze["candidate_artifacts"]["parameters"])
    parameters = action_innovation_transition_parameters_from_dict(json.loads(parameter_body))
    return freeze_body, freeze, parameter_body, parameters


def _load_source_wwm_window(
    *,
    input_report_path: Path,
    outcome_report_path: Path,
    expected_input_schema: str,
    expected_outcome_schema: str,
    parameters: ActionInnovationTransitionParameters,
    parameter_sha256: str,
) -> dict[str, Any]:
    input_report_body, input_report = cross._load_json(input_report_path)
    outcome_report_body, outcome_report = cross._load_json(outcome_report_path)
    protocol_body, protocol, _, _ = cross._validate_source_reports(
        input_report=input_report,
        outcome_report=outcome_report,
        input_schema=expected_input_schema,
        outcome_schema=expected_outcome_schema,
    )
    source_inputs = (input_report.get("systems") or {}).get(SOURCE_SYSTEM_ID) or {}
    source_outcomes = (outcome_report.get("systems") or {}).get(SOURCE_SYSTEM_ID) or {}
    source_lock = (protocol.get("systems") or {}).get(SOURCE_SYSTEM_ID) or {}
    quality = source_outcomes.get("quality") or {}
    support = parameters.support
    if (
        cross._descriptor_identity(source_inputs.get("topology_report") or {})
        != cross._descriptor_identity(source_lock.get("topology_report") or {})
        or source_outcomes.get("system_id") != SOURCE_SYSTEM_ID
        or source_outcomes.get("site_id") != (source_lock.get("outcome") or {}).get("site_id")
        or quality.get("missing_values_imputed") is not False
        or support.action_entry_feature_id != source_lock.get("action_entry_feature_id")
        or support.outlet_feature_id != source_lock.get("outlet_feature_id")
        or len(support.path_feature_ids) != source_lock.get("mainstem_feature_count")
    ):
        raise ValueError("physical_action_innovation_source_wwm_identity_invalid")
    window = cross._load_window(
        target_inputs=source_inputs,
        target_outcomes=source_outcomes,
        target_lock=source_lock,
        target_support=support,
    )
    rows, execution = cross._evaluate_window(
        window=window,
        parameters=parameters,
        parameter_sha256=parameter_sha256,
    )
    rows = [{**row, "system_id": SOURCE_SYSTEM_ID} for row in rows]
    prediction_body = cross._encode_rows(rows)
    return {
        "input_report_body": input_report_body,
        "outcome_report_body": outcome_report_body,
        "protocol_body": protocol_body,
        "prediction_body": prediction_body,
        "rows": rows,
        "execution": execution,
        "outcome_descriptor": source_outcomes["outcome_values"],
    }


def _fit_source_parameter(
    *,
    source_rows: list[dict[str, object]],
    physical_series: Mapping[datetime, float],
    source_physical: Mapping[str, Any],
    source_wwm_body: bytes,
    source_wwm_parameter_sha256: str,
    source_outcome_sha256: str,
    provenance_id: str,
) -> PhysicalActionInnovationParameters:
    aligned = _aligned_source_rows(source_rows=source_rows, physical_series=physical_series)
    return fit_physical_action_innovation(
        issue_times=aligned["issue_times"],
        forecast_horizons_hours=aligned["horizons"],
        physical_discharge_m3s=aligned["physical"],
        action_innovation_wwm_m3s=aligned["wwm"],
        causal_persistence_m3s=aligned["persistence"],
        observed_discharge_m3s=aligned["observed"],
        supported_forecast_horizons_hours=HORIZONS,
        source_system_id=SOURCE_SYSTEM_ID,
        source_physical_operator=str(source_physical["operator"]),
        source_physical_prediction_sha256=str(source_physical["prediction_descriptor"]["sha256"]),
        source_wwm_prediction_sha256=hashlib.sha256(source_wwm_body).hexdigest(),
        source_wwm_parameter_sha256=source_wwm_parameter_sha256,
        source_outcome_sha256=source_outcome_sha256,
        provenance_id=provenance_id,
    )


def _aligned_source_rows(
    *,
    source_rows: list[dict[str, object]],
    physical_series: Mapping[datetime, float],
) -> dict[str, tuple[Any, ...]]:
    if not source_rows or any(row.get("system_id") != SOURCE_SYSTEM_ID for row in source_rows):
        raise ValueError("physical_action_innovation_source_rows_invalid")
    target_times = tuple(cross._parse_time(row["target_support_end_utc"]) for row in source_rows)
    if any(value not in physical_series for value in target_times):
        raise ValueError("physical_action_innovation_source_physical_axis_invalid")
    return {
        "issue_times": tuple(cross._parse_time(row["issue_time_utc"]) for row in source_rows),
        "horizons": tuple(int(row["horizon_hours"]) for row in source_rows),
        "physical": tuple(physical_series[value] for value in target_times),
        "wwm": tuple(float(row["action_innovation_candidate_m3s"]) for row in source_rows),
        "persistence": tuple(float(row["causal_persistence_m3s"]) for row in source_rows),
        "observed": tuple(
            None if row["observed_discharge_m3s"] == "" else float(row["observed_discharge_m3s"])
            for row in source_rows
        ),
    }


def _score_source_window(
    *,
    source_rows: list[dict[str, object]],
    physical_series: Mapping[datetime, float],
    parameters: PhysicalActionInnovationParameters,
) -> dict[str, Any]:
    rows: list[dict[str, object]] = []
    clipped_count = 0
    for source in source_rows:
        target_time = cross._parse_time(source["target_support_end_utc"])
        step = parameters.correct(
            physical_target_m3s=physical_series[target_time],
            action_innovation_wwm_target_m3s=float(source["action_innovation_candidate_m3s"]),
            causal_persistence_target_m3s=float(source["causal_persistence_m3s"]),
            forecast_horizon_hours=int(source["horizon_hours"]),
        )
        clipped_count += int(step.clipped)
        rows.append(
            {
                "issue_time_utc": source["issue_time_utc"],
                "target_support_end_utc": source["target_support_end_utc"],
                "horizon_hours": source["horizon_hours"],
                "observed_discharge_m3s": source["observed_discharge_m3s"],
                "physical_open_loop_m3s": step.physical_target_m3s,
                "physical_action_innovation_m3s": step.corrected_prediction_m3s,
                "action_innovation_wwm_m3s": step.action_innovation_wwm_target_m3s,
                "causal_persistence_m3s": step.causal_persistence_target_m3s,
            }
        )
    columns = {
        "physical_open_loop": "physical_open_loop_m3s",
        "physical_action_innovation": "physical_action_innovation_m3s",
        "action_innovation_wwm": "action_innovation_wwm_m3s",
        "causal_persistence": "causal_persistence_m3s",
    }
    metrics, scoring = candidate._score(rows, columns)
    return {
        "metrics_by_horizon": metrics,
        "comparison": _comparison(metrics, candidate_name="physical_action_innovation"),
        "scoring": scoring,
        "prediction_row_count": len(rows),
        "clipped_prediction_count": clipped_count,
    }


def _load_comparison_report(path: Path) -> tuple[bytes, Mapping[str, Any]]:
    body, report = cross._load_json(path)
    claim = report.get("claim_boundary") or {}
    information = report.get("information_boundary") or {}
    outputs = report.get("outputs") or {}
    if (
        report.get("schema") != retention.SCHEMA
        or report.get("status")
        != "source_fitted_physical_residual_retention_transfer_posthoc_complete"
        or claim.get("physical_residual_retention_posthoc_executed") is not True
        or claim.get("geospatial_kernel_validated") is not False
        or information.get("evaluation_counts_as_fresh_validation") is not False
        or not {"primary_predictions", "replication_predictions"}.issubset(outputs)
    ):
        raise ValueError("physical_action_innovation_comparison_report_invalid")
    return body, report


def _compile_target_window(
    *,
    source_body: bytes,
    parameters: PhysicalActionInnovationParameters,
    parameter_sha256: str,
) -> tuple[bytes, dict[str, Any]]:
    source_rows = retention._comparison_rows(source_body)
    rows: list[dict[str, object]] = []
    clipped_count = 0
    issue_times: set[datetime] = set()
    for source in source_rows:
        horizon = int(source["horizon_hours"])
        issue_time = cross._parse_time(source["issue_time_utc"])
        step = parameters.correct(
            physical_target_m3s=float(source["physical_open_loop_m3s"]),
            action_innovation_wwm_target_m3s=float(source["action_innovation_wwm_m3s"]),
            causal_persistence_target_m3s=float(source["causal_persistence_m3s"]),
            forecast_horizon_hours=horizon,
        )
        clipped_count += int(step.clipped)
        issue_times.add(issue_time)
        rows.append(
            {
                "system_id": source["system_id"],
                "issue_time_utc": source["issue_time_utc"],
                "target_support_end_utc": source["target_support_end_utc"],
                "horizon_hours": horizon,
                # Target outcome is copied only after the forecast is complete.
                "observed_discharge_m3s": source["observed_discharge_m3s"],
                "physical_open_loop_m3s": source["physical_open_loop_m3s"],
                "physical_constant_state_correction_m3s": source[
                    "physical_constant_state_correction_m3s"
                ],
                "physical_residual_decay_m3s": source["physical_residual_decay_m3s"],
                "physical_residual_retention_m3s": source["physical_residual_retention_m3s"],
                "physical_action_innovation_m3s": step.corrected_prediction_m3s,
                "classical_arx_m3s": source["classical_arx_m3s"],
                "action_innovation_wwm_m3s": source["action_innovation_wwm_m3s"],
                "causal_persistence_m3s": source["causal_persistence_m3s"],
                "raw_action_innovation_m3s": step.raw_action_innovation_m3s,
                "innovation_scale_coefficient": step.innovation_scale_coefficient,
                "scaled_action_innovation_m3s": step.scaled_action_innovation_m3s,
                "physical_action_innovation_clipped": step.clipped,
                "future_target_observation_used_for_correction": False,
                "target_parameter_refit_performed": False,
                "operational_vintages_verified": False,
                "physical_action_innovation_parameter_sha256": parameter_sha256,
                "residual_retention_parameter_sha256": source[
                    "residual_retention_parameter_sha256"
                ],
                "residual_decay_parameter_sha256": source["residual_decay_parameter_sha256"],
                "source_physical_prediction_sha256": source["source_physical_prediction_sha256"],
                "arx_parameter_sha256": source["arx_parameter_sha256"],
                "wwm_parameter_sha256": source["wwm_parameter_sha256"],
            }
        )
    columns = {
        "physical_open_loop": "physical_open_loop_m3s",
        "physical_constant_state_correction": "physical_constant_state_correction_m3s",
        "physical_residual_decay": "physical_residual_decay_m3s",
        "physical_residual_retention": "physical_residual_retention_m3s",
        "physical_action_innovation": "physical_action_innovation_m3s",
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
            "physical_action_innovation_clipped_row_count": clipped_count,
            "target_parameter_refit_performed": False,
            "future_target_observation_used_for_correction": False,
        },
    }


def _comparison(
    metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
    *,
    candidate_name: str = "physical_action_innovation",
) -> dict[str, Any]:
    comparators = {
        "raw_physical": "physical_open_loop",
        "constant_correction": "physical_constant_state_correction",
        "ar1_decay": "physical_residual_decay",
        "residual_retention": "physical_residual_retention",
        "arx": "classical_arx",
        "wwm": "action_innovation_wwm",
        "persistence": "causal_persistence",
    }
    available = set(next(iter(metrics.values())))
    comparators = {name: model for name, model in comparators.items() if model in available}
    per_horizon: dict[str, dict[str, float]] = {}
    for horizon in HORIZONS:
        horizon_metrics = metrics[str(horizon)]
        hybrid_rmse = horizon_metrics[candidate_name]["rmse_m3s"]
        per_horizon[str(horizon)] = {
            f"hybrid_minus_{name}_rmse_m3s": (
                hybrid_rmse - horizon_metrics[metric_name]["rmse_m3s"]
            )
            for name, metric_name in comparators.items()
        }
    result: dict[str, Any] = {"per_horizon": per_horizon}
    for name in comparators:
        result[f"hybrid_beats_{name}_all_horizons"] = all(
            values[f"hybrid_minus_{name}_rmse_m3s"] < 0.0 for values in per_horizon.values()
        )
        result[f"hybrid_beats_{name}_horizons_hours"] = [
            horizon
            for horizon in HORIZONS
            if per_horizon[str(horizon)][f"hybrid_minus_{name}_rmse_m3s"] < 0.0
        ]
    return result


def _verify_metric_replay(*, result: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    existing_models = (
        "physical_open_loop",
        "physical_constant_state_correction",
        "physical_residual_decay",
        "physical_residual_retention",
        "classical_arx",
        "action_innovation_wwm",
        "causal_persistence",
    )
    for horizon in HORIZONS:
        actual = result["metrics_by_horizon"][str(horizon)]
        prior = expected["metrics_by_horizon"][str(horizon)]
        for model_name in existing_models:
            if actual[model_name] != prior[model_name]:
                raise ValueError("physical_action_innovation_metric_replay_mismatch")
    if result["scoring"] != expected["scoring"]:
        raise ValueError("physical_action_innovation_scoring_replay_mismatch")


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
        "source_wwm_predictions": (args.output_root / "center_hill_source_wwm_predictions.csv"),
        "replication_source_wwm_predictions": (
            args.output_root / "center_hill_replication_wwm_predictions.csv"
        ),
        "primary_predictions": args.output_root / "j_percy_priest_primary_predictions.csv",
        "replication_predictions": (
            args.output_root / "j_percy_priest_replication_predictions.csv"
        ),
    }
    bodies, report = compile_physical_action_innovation_transfer_posthoc(
        freeze_path=args.freeze,
        source_input_report_path=args.source_input_report,
        source_outcome_report_path=args.source_outcome_report,
        replication_source_input_report_path=args.replication_source_input_report,
        replication_source_outcome_report_path=args.replication_source_outcome_report,
        source_physical_report_path=args.source_physical_report,
        replication_source_physical_report_path=args.replication_source_physical_report,
        comparison_report_path=args.comparison_report,
        parameter_path=paths["parameters"],
        source_wwm_prediction_path=paths["source_wwm_predictions"],
        replication_source_wwm_prediction_path=paths["replication_source_wwm_predictions"],
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
        "source_innovation_scale_coefficient="
        f"{report['source_fit_contract']['innovation_scale_coefficient']:.9f}"
    )
    for window_name in ("primary_window", "replication_window"):
        for horizon in HORIZONS:
            values = report[window_name]["comparison"]["per_horizon"][str(horizon)]
            print(
                f"window={window_name} horizon={horizon}h "
                f"hybrid_minus_raw_rmse="
                f"{values['hybrid_minus_raw_physical_rmse_m3s']:.6f} "
                f"hybrid_minus_retention_rmse="
                f"{values['hybrid_minus_residual_retention_rmse_m3s']:.6f} "
                f"hybrid_minus_wwm_rmse="
                f"{values['hybrid_minus_wwm_rmse_m3s']:.6f}"
            )


if __name__ == "__main__":
    main()
