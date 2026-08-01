#!/usr/bin/env python3
"""Fit and diagnose the state-anchored Geospatial Kernel innovation candidate."""

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

import numpy as np

from data_agent.uwm.geospatial_kernel_v2.action_conditioned_transition import (
    HourlyActionForcingSeries,
    OutletTransitionState,
    action_conditioned_transition_parameters_from_dict,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    ActionInnovationTransitionParameters,
    CausalActionInnovationGeospatialKernel,
    action_innovation_transition_parameters_from_dict,
    fit_action_innovation_transition,
)

if __package__:
    from scripts import evaluate_geospatial_kernel_mvp as development
    from scripts import evaluate_geospatial_kernel_mvp_temporal_transfer as transfer
else:
    import evaluate_geospatial_kernel_mvp as development
    import evaluate_geospatial_kernel_mvp_temporal_transfer as transfer

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_OPERATOR_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/action_innovation_transition.py"
)
EVALUATOR_PATH = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data/geotransport_v0_1/kernel_innovation_candidate"
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_action_innovation_candidate_report.json"
)

SCHEMA = "gwm.geotransport.geospatial_kernel_action_innovation_candidate.v1"
HORIZONS = (1, 3, 6, 12)
ACTION_EFFECT_HORIZONS = (6, 12)
FIT_HOURS = 168


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_candidate(
    *,
    parameter_output_path: Path | None = None,
    development_prediction_path: Path | None = None,
    january_prediction_path: Path | None = None,
    d3_prediction_path: Path | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    parameter_output_path = parameter_output_path or DEFAULT_OUTPUT_ROOT / "parameters.json"
    development_prediction_path = development_prediction_path or (
        DEFAULT_OUTPUT_ROOT / "development_predictions.csv"
    )
    january_prediction_path = january_prediction_path or (
        DEFAULT_OUTPUT_ROOT / "january_temporal_holdout_predictions.csv"
    )
    d3_prediction_path = d3_prediction_path or DEFAULT_OUTPUT_ROOT / "february_d3_predictions.csv"

    support_parameter_body, support_parameter_document = development._load_json(
        transfer.DEFAULT_PARAMETERS
    )
    support_parameters = action_conditioned_transition_parameters_from_dict(
        support_parameter_document
    )
    panel_report_body, panel_report = development._load_json(development.DEFAULT_PANEL_REPORT)
    panel_body = development._read_verified(panel_report["panel_artifact"])
    panel = development._parse_panel(panel_body)
    if len(panel) != 672:
        raise ValueError("action_innovation_development_panel_axis_invalid")
    inputs = HourlyActionForcingSeries(
        valid_times=tuple(row["support_end"] for row in panel),
        action_release_m3s=tuple(row["action"] for row in panel),
        nwm_lateral_inflow_m3s=tuple(row["forcing"] for row in panel),
        action_provenance_id=(
            f"center-hill:development-action:{hashlib.sha256(panel_body).hexdigest()}"
        ),
        forcing_provenance_id=(
            f"center-hill:development-nwm-q-lateral:{hashlib.sha256(panel_body).hexdigest()}"
        ),
        action_plan_vintage_verified=False,
        forcing_vintage_verified=False,
    )
    training = panel[:FIT_HOURS]
    if any(row["outcome"] is None for row in training):
        raise ValueError("action_innovation_training_outcomes_must_be_complete")
    fit = fit_action_innovation_transition(
        support=support_parameters.support,
        observed_valid_times=tuple(row["support_end"] for row in training),
        observed_discharge_m3s=tuple(float(row["outcome"]) for row in training),
        inputs=inputs,
        maximum_discharge_m3s=support_parameters.maximum_discharge_m3s,
        provenance_id=(
            "center-hill:kernel-action-innovation:ols-increment-fit:"
            f"panel={hashlib.sha256(panel_body).hexdigest()}:"
            "fixed-path-lags-and-uniform-weights"
        ),
    )
    parameter_body = development._json_body(fit.parameters.as_dict())
    parameter_hash = hashlib.sha256(parameter_body).hexdigest()
    replay_parameters = action_innovation_transition_parameters_from_dict(
        json.loads(parameter_body)
    )

    development_body, development_result = _evaluate_development(
        panel=panel,
        inputs=inputs,
        parameters=replay_parameters,
        parameter_hash=parameter_hash,
    )
    january_window, january_sources = _january_window()
    d3_window, d3_sources = _d3_window(replay_parameters)
    january_body, january_result = _evaluate_transfer_window(
        january_window, replay_parameters, parameter_hash
    )
    d3_body, d3_result = _evaluate_transfer_window(d3_window, replay_parameters, parameter_hash)

    output_bodies = {
        "parameters": parameter_body,
        "development_predictions": development_body,
        "january_temporal_holdout_predictions": january_body,
        "february_d3_predictions": d3_body,
    }
    development_passed = development_result["hard_gate"]["development_gate_passed"]
    transfer_passed = all(
        value["hard_gate"]["window_diagnostic_gate_passed"] for value in (january_result, d3_result)
    )
    report = {
        "schema": SCHEMA,
        "status": (
            "action_innovation_candidate_posthoc_gates_passed_not_validated"
            if development_passed and transfer_passed
            else "action_innovation_candidate_gate_failed"
        ),
        "generated_at": datetime.now(UTC).isoformat(),
        "implementation_artifacts": {
            "core_operator": development._artifact(
                CORE_OPERATOR_PATH, CORE_OPERATOR_PATH.read_bytes()
            ),
            "evaluator": development._artifact(EVALUATOR_PATH, EVALUATOR_PATH.read_bytes()),
        },
        "source_artifacts": {
            "prior_mvp_parameters_used_for_support_only": development._artifact(
                transfer.DEFAULT_PARAMETERS, support_parameter_body
            ),
            "development_panel_report": development._artifact(
                development.DEFAULT_PANEL_REPORT, panel_report_body
            ),
            "development_panel": panel_report["panel_artifact"],
        },
        "outputs": {
            "parameters": development._artifact(parameter_output_path, parameter_body),
            "development_predictions": development._artifact(
                development_prediction_path, development_body
            ),
            "january_temporal_holdout_predictions": development._artifact(
                january_prediction_path, january_body
            ),
            "february_d3_predictions": development._artifact(d3_prediction_path, d3_body),
        },
        "kernel": {
            "role": "state_anchored_action_innovation_predictive_closure",
            "fit": fit.as_dict(),
            "free_parameter_count": 3,
            "state_persistence_coefficient_fixed": 1.0,
            "absolute_outlet_level_coefficient_fitted": False,
            "asymptotic_stability_claimed": False,
            "mass_conserving_network_routing_replacement": False,
        },
        "parameter_lock": {
            "serialized_parameter_sha256": parameter_hash,
            "all_evaluations_use_deserialized_parameter_artifact": True,
            "per_window_refit_performed": False,
        },
        "development": development_result,
        "posthoc_temporal_diagnostics": {
            "january_temporal_holdout": {
                **january_result,
                "source_artifacts": january_sources,
            },
            "february_d3": {**d3_result, "source_artifacts": d3_sources},
        },
        "aggregate_gate": {
            "development_gate_passed": development_passed,
            "both_posthoc_temporal_window_gates_passed": transfer_passed,
            "candidate_diagnostic_gate_passed": development_passed and transfer_passed,
            "admission_gate_passed": False,
        },
        "selection_boundary": {
            "fit_uses_first_168_original_development_hours_only": True,
            "fit_uses_temporal_transfer_outcomes": False,
            "architecture_revised_after_prior_mvp_transfer_outcomes_were_seen": True,
            "public_transfer_windows_can_validate_revised_architecture": False,
            "fresh_blind_window_consumed": False,
            "new_target_data_acquired": False,
            "stage45_usgs_requests_executed": False,
        },
        "information_boundary": {
            "future_outlet_observations_used_by_kernel": False,
            "future_realized_action_archive_used": True,
            "future_retrospective_nwm_forcing_used": True,
            "operational_forecast_claim_permitted": False,
        },
        "claim_boundary": {
            "action_innovation_candidate_implemented": True,
            "posthoc_public_diagnostics_passed": transfer_passed,
            "action_innovation_closure_admitted_as_default": False,
            "geospatial_kernel_validated": False,
            "operational_forecast_validated": False,
            "multi_system_generalization_validated": False,
        },
    }
    return output_bodies, report


def _evaluate_development(
    *,
    panel: list[dict[str, Any]],
    inputs: HourlyActionForcingSeries,
    parameters: ActionInnovationTransitionParameters,
    parameter_hash: str,
) -> tuple[bytes, dict[str, Any]]:
    lead_report_body, lead_report = development._load_json(development.DEFAULT_LEAD_TIME_REPORT)
    lead_body = development._read_verified(lead_report["outputs"]["predictions"])
    lead_rows = list(csv.DictReader(io.StringIO(lead_body.decode("utf-8"))))
    development._validate_axes(panel, lead_rows)
    panel_by_time = {row["support_end"]: row for row in panel}
    kernel = CausalActionInnovationGeospatialKernel(parameters)
    rows: list[dict[str, object]] = []
    clipped_step_count = 0
    unavailable_state_count = 0
    for source in lead_rows:
        horizon = int(source["horizon_hours"])
        if horizon not in HORIZONS:
            continue
        issue_time = development._parse_utc(source["issue_time_utc"])
        target_time = development._parse_utc(source["target_support_end_utc"])
        try:
            state = development._latest_causal_state(panel, issue_time)
        except ValueError as exc:
            if str(exc) != "kernel_mvp_causal_outlet_state_unavailable":
                raise
            unavailable_state_count += 1
            rows.append(
                _empty_development_row(
                    source, panel_by_time[target_time]["outcome"], parameter_hash
                )
            )
            continue
        target = (target_time,)
        candidate = kernel.forecast(state, inputs, issue_time=issue_time, target_valid_times=target)
        no_action = kernel.forecast(
            state,
            inputs.counterfactual(issue_time=issue_time, zero_future_action=True),
            issue_time=issue_time,
            target_valid_times=target,
        )
        no_forcing = kernel.forecast(
            state,
            inputs.counterfactual(issue_time=issue_time, zero_future_forcing=True),
            issue_time=issue_time,
            target_valid_times=target,
        )
        clipped_step_count += sum(step.clipped for step in candidate.steps)
        rows.append(
            {
                "window_id": "development",
                "issue_time_utc": development._iso(issue_time),
                "target_support_end_utc": development._iso(target_time),
                "horizon_hours": horizon,
                "observed_discharge_m3s": development._optional(
                    panel_by_time[target_time]["outcome"]
                ),
                "action_innovation_candidate_m3s": candidate.target_discharge_m3s[0],
                "no_future_action_m3s": no_action.target_discharge_m3s[0],
                "no_future_forcing_m3s": no_forcing.target_discharge_m3s[0],
                "causal_persistence_m3s": source["causal_latency_matched_persistence_m3s"],
                "graph_manning_m3s": source["graph_multi_gauge_m3s"],
                "local_manning_m3s": source["local_multi_gauge_m3s"],
                "latest_observation_valid_at_utc": development._iso(state.valid_at),
                "latest_observation_available_at_utc": development._iso(state.available_at),
                "issue_state_writeback_m3s": candidate.issue_state.discharge_m3s,
                "target_state_writeback_m3s": candidate.target_discharge_m3s[0],
                "future_outcome_observation_used": False,
                "parameter_sha256": parameter_hash,
            }
        )
    body = development._encode_rows(rows)
    columns = {
        "candidate": "action_innovation_candidate_m3s",
        "causal_persistence": "causal_persistence_m3s",
        "no_future_action": "no_future_action_m3s",
        "no_future_forcing": "no_future_forcing_m3s",
        "graph_manning": "graph_manning_m3s",
        "local_manning": "local_manning_m3s",
    }
    metrics, scoring = _score(rows, columns)
    gate = _gate(
        rows=rows,
        metrics=metrics,
        candidate_name="candidate",
        comparison_names=("causal_persistence", "no_future_forcing"),
        additional_all_horizon_names=("graph_manning", "local_manning"),
        clipped_step_count=clipped_step_count,
        gate_name="development_gate_passed",
    )
    return body, {
        "role": "original_public_development_scoring",
        "source_artifacts": {
            "lead_time_report": development._artifact(
                development.DEFAULT_LEAD_TIME_REPORT, lead_report_body
            ),
            "lead_time_predictions": lead_report["outputs"]["predictions"],
        },
        "metrics_by_horizon": metrics,
        "scoring": scoring,
        "causal_state_unavailable_row_count": unavailable_state_count,
        "hard_gate": gate,
    }


def _empty_development_row(
    source: Mapping[str, str], observed: object, parameter_hash: str
) -> dict[str, object]:
    return {
        "window_id": "development",
        "issue_time_utc": source["issue_time_utc"],
        "target_support_end_utc": source["target_support_end_utc"],
        "horizon_hours": int(source["horizon_hours"]),
        "observed_discharge_m3s": development._optional(observed),
        "action_innovation_candidate_m3s": "",
        "no_future_action_m3s": "",
        "no_future_forcing_m3s": "",
        "causal_persistence_m3s": source["causal_latency_matched_persistence_m3s"],
        "graph_manning_m3s": source["graph_multi_gauge_m3s"],
        "local_manning_m3s": source["local_multi_gauge_m3s"],
        "latest_observation_valid_at_utc": "",
        "latest_observation_available_at_utc": "",
        "issue_state_writeback_m3s": "",
        "target_state_writeback_m3s": "",
        "future_outcome_observation_used": False,
        "parameter_sha256": parameter_hash,
    }


def _january_window() -> tuple[transfer.TransferWindow, dict[str, object]]:
    report_body, report = transfer._load_json(transfer.DEFAULT_TEMPORAL_PANEL_REPORT)
    return transfer._load_january_window(
        transfer.DEFAULT_TEMPORAL_PANEL_REPORT, report_body, report
    )


def _d3_window(
    parameters: ActionInnovationTransitionParameters,
) -> tuple[transfer.TransferWindow, dict[str, object]]:
    action_body, action = transfer._load_json(transfer.DEFAULT_D3_ACTION_MANIFEST)
    nwm_body, nwm = transfer._load_json(transfer.DEFAULT_D3_NWM_MANIFEST)
    outcome_body, outcome = transfer._load_json(transfer.DEFAULT_D3_OUTCOME_MANIFEST)
    return transfer._load_d3_window(
        action_manifest_path=transfer.DEFAULT_D3_ACTION_MANIFEST,
        action_manifest_body=action_body,
        action_manifest=action,
        nwm_manifest_path=transfer.DEFAULT_D3_NWM_MANIFEST,
        nwm_manifest_body=nwm_body,
        nwm_manifest=nwm,
        outcome_manifest_path=transfer.DEFAULT_D3_OUTCOME_MANIFEST,
        outcome_manifest_body=outcome_body,
        outcome_manifest=outcome,
        expected_feature_ids=parameters.support.path_feature_ids,
        first_issue_index=max(parameters.support.lag_hours) + 1,
    )


def _evaluate_transfer_window(
    window: transfer.TransferWindow,
    parameters: ActionInnovationTransitionParameters,
    parameter_hash: str,
) -> tuple[bytes, dict[str, Any]]:
    inputs = HourlyActionForcingSeries(
        valid_times=window.valid_times,
        action_release_m3s=window.action_release_m3s,
        nwm_lateral_inflow_m3s=window.nwm_lateral_inflow_m3s,
        action_provenance_id=window.action_provenance_id,
        forcing_provenance_id=window.forcing_provenance_id,
        action_plan_vintage_verified=False,
        forcing_vintage_verified=False,
    )
    kernel = CausalActionInnovationGeospatialKernel(parameters)
    rows: list[dict[str, object]] = []
    clipped_step_count = 0
    for issue_index in range(
        window.first_issue_index, window.target_end_index_exclusive - min(HORIZONS)
    ):
        issue_time = window.valid_times[issue_index]
        horizons = tuple(
            horizon
            for horizon in HORIZONS
            if issue_index + horizon < window.target_end_index_exclusive
        )
        targets = tuple(issue_time + timedelta(hours=horizon) for horizon in horizons)
        state = OutletTransitionState(
            valid_at=window.valid_times[issue_index - 1],
            available_at=issue_time,
            discharge_m3s=window.observed_discharge_m3s[issue_index - 1],
            provenance_id=(
                f"{window.outcome_provenance_id}:valid="
                f"{transfer._iso(window.valid_times[issue_index - 1])}"
            ),
            evidence_level="candidate",
            observed=True,
        )
        candidate = kernel.forecast(
            state, inputs, issue_time=issue_time, target_valid_times=targets
        )
        no_action = kernel.forecast(
            state,
            inputs.counterfactual(issue_time=issue_time, zero_future_action=True),
            issue_time=issue_time,
            target_valid_times=targets,
        )
        no_forcing = kernel.forecast(
            state,
            inputs.counterfactual(issue_time=issue_time, zero_future_forcing=True),
            issue_time=issue_time,
            target_valid_times=targets,
        )
        clipped_step_count += sum(step.clipped for step in candidate.steps)
        for offset, horizon in enumerate(horizons):
            target_index = issue_index + horizon
            rows.append(
                {
                    "window_id": window.window_id,
                    "issue_time_utc": transfer._iso(issue_time),
                    "target_support_end_utc": transfer._iso(window.valid_times[target_index]),
                    "horizon_hours": horizon,
                    "observed_discharge_m3s": window.observed_discharge_m3s[target_index],
                    "action_innovation_candidate_m3s": (candidate.target_discharge_m3s[offset]),
                    "no_future_action_m3s": no_action.target_discharge_m3s[offset],
                    "no_future_forcing_m3s": no_forcing.target_discharge_m3s[offset],
                    "causal_persistence_m3s": state.discharge_m3s,
                    "latest_observation_valid_at_utc": transfer._iso(state.valid_at),
                    "latest_observation_available_at_utc": transfer._iso(state.available_at),
                    "issue_state_writeback_m3s": candidate.issue_state.discharge_m3s,
                    "target_state_writeback_m3s": candidate.target_discharge_m3s[offset],
                    "future_outcome_observation_used": False,
                    "parameter_sha256": parameter_hash,
                }
            )
    body = development._encode_rows(rows)
    columns = {
        "candidate": "action_innovation_candidate_m3s",
        "causal_persistence": "causal_persistence_m3s",
        "no_future_action": "no_future_action_m3s",
        "no_future_forcing": "no_future_forcing_m3s",
    }
    metrics, scoring = _score(rows, columns)
    gate = _gate(
        rows=rows,
        metrics=metrics,
        candidate_name="candidate",
        comparison_names=("causal_persistence", "no_future_forcing"),
        additional_all_horizon_names=(),
        clipped_step_count=clipped_step_count,
        gate_name="window_diagnostic_gate_passed",
    )
    return body, {
        "role": window.role,
        "window": {
            "first_issue_time_utc": transfer._iso(window.valid_times[window.first_issue_index]),
            "last_scored_target_utc": transfer._iso(
                window.valid_times[window.target_end_index_exclusive - 1]
            ),
            "horizons_hours": list(HORIZONS),
        },
        "metrics_by_horizon": metrics,
        "scoring": scoring,
        "hard_gate": gate,
    }


def _score(
    rows: list[dict[str, object]], columns: Mapping[str, str]
) -> tuple[dict[str, dict[str, dict[str, float]]], dict[str, Any]]:
    metrics: dict[str, dict[str, dict[str, float]]] = {}
    counts: dict[str, int] = {}
    omitted: dict[str, list[str]] = {}
    for horizon in HORIZONS:
        selected = [row for row in rows if row["horizon_hours"] == horizon]
        complete: list[dict[str, object]] = []
        missing: list[str] = []
        for row in selected:
            required = [row["observed_discharge_m3s"]]
            required.extend(row[column] for column in columns.values())
            if any(value in (None, "") for value in required):
                missing.append(str(row["target_support_end_utc"]))
            else:
                complete.append(row)
        observed = np.asarray(
            [float(row["observed_discharge_m3s"]) for row in complete], dtype=float
        )
        metrics[str(horizon)] = {
            name: _metrics(
                observed,
                np.asarray([float(row[column]) for row in complete], dtype=float),
            )
            for name, column in columns.items()
        }
        counts[str(horizon)] = len(complete)
        omitted[str(horizon)] = missing
    return metrics, {
        "common_complete_case_count_by_horizon": counts,
        "omitted_target_times_by_horizon": omitted,
        "missing_values_imputed": False,
        "comparison_uses_identical_rows_within_each_horizon": True,
    }


def _gate(
    *,
    rows: list[dict[str, object]],
    metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
    candidate_name: str,
    comparison_names: tuple[str, ...],
    additional_all_horizon_names: tuple[str, ...],
    clipped_step_count: int,
    gate_name: str,
) -> dict[str, Any]:
    all_horizon_comparisons = comparison_names + additional_all_horizon_names
    per_horizon = {
        str(horizon): {
            **{
                f"candidate_beats_{name}_rmse": (
                    metrics[str(horizon)][candidate_name]["rmse_m3s"]
                    < metrics[str(horizon)][name]["rmse_m3s"]
                )
                for name in all_horizon_comparisons
            },
            "candidate_beats_no_future_action_rmse": (
                metrics[str(horizon)][candidate_name]["rmse_m3s"]
                < metrics[str(horizon)]["no_future_action"]["rmse_m3s"]
            ),
            "action_effect_required_at_horizon": horizon in ACTION_EFFECT_HORIZONS,
        }
        for horizon in HORIZONS
    }
    comparisons_passed = all(
        per_horizon[str(horizon)][f"candidate_beats_{name}_rmse"]
        for horizon in HORIZONS
        for name in all_horizon_comparisons
    )
    action_passed = all(
        per_horizon[str(horizon)]["candidate_beats_no_future_action_rmse"]
        for horizon in ACTION_EFFECT_HORIZONS
    )
    executable = [row for row in rows if row["action_innovation_candidate_m3s"] not in (None, "")]
    state_passed = bool(executable) and all(
        math.isfinite(float(row["issue_state_writeback_m3s"]))
        and float(row["target_state_writeback_m3s"])
        == float(row["action_innovation_candidate_m3s"])
        for row in executable
    )
    information_passed = bool(executable) and all(
        row["future_outcome_observation_used"] is False for row in executable
    )
    passed = all(
        (
            comparisons_passed,
            action_passed,
            state_passed,
            information_passed,
            clipped_step_count == 0,
        )
    )
    return {
        "per_horizon": per_horizon,
        "all_required_accuracy_comparisons_passed": comparisons_passed,
        "supported_horizons_beat_no_future_action": action_passed,
        "state_writeback_gate_passed": state_passed,
        "no_future_outcome_gate_passed": information_passed,
        "clipped_candidate_step_count": clipped_step_count,
        gate_name: passed,
    }


def _metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    if not observed.size or observed.shape != predicted.shape:
        raise ValueError("action_innovation_metric_axis_invalid")
    error = predicted - observed
    denominator = float(np.sum((observed - observed.mean()) ** 2))
    return {
        "sample_count": int(observed.size),
        "rmse_m3s": float(np.sqrt(np.mean(error**2))),
        "mae_m3s": float(np.mean(np.abs(error))),
        "bias_m3s": float(np.mean(error)),
        "nse": float(1.0 - np.sum(error**2) / denominator),
    }


def main() -> None:
    args = parse_args()
    paths = {
        "parameters": args.output_root / "parameters.json",
        "development_predictions": args.output_root / "development_predictions.csv",
        "january_temporal_holdout_predictions": (
            args.output_root / "january_temporal_holdout_predictions.csv"
        ),
        "february_d3_predictions": args.output_root / "february_d3_predictions.csv",
    }
    bodies, report = compile_candidate(
        parameter_output_path=paths["parameters"],
        development_prediction_path=paths["development_predictions"],
        january_prediction_path=paths["january_temporal_holdout_predictions"],
        d3_prediction_path=paths["february_d3_predictions"],
    )
    args.output_root.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    for name, path in paths.items():
        path.write_bytes(bodies[name])
    args.report.write_bytes(development._json_body(report))
    print(f"status={report['status']}")
    print(
        "candidate_diagnostic_gate_passed="
        f"{str(report['aggregate_gate']['candidate_diagnostic_gate_passed']).lower()}"
    )
    for window_id, result in (
        ("development", report["development"]),
        *report["posthoc_temporal_diagnostics"].items(),
    ):
        for horizon in HORIZONS:
            metrics = result["metrics_by_horizon"][str(horizon)]
            print(
                f"window={window_id} horizon={horizon}h "
                f"candidate_rmse={metrics['candidate']['rmse_m3s']:.6f} "
                f"persistence_rmse={metrics['causal_persistence']['rmse_m3s']:.6f}"
            )


if __name__ == "__main__":
    main()
