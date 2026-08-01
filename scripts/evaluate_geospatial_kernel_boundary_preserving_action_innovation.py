#!/usr/bin/env python3
"""Compare a smooth bounded state update with the frozen hard-clipped WWM."""

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
from statistics import median
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.action_conditioned_transition import (
    HourlyActionForcingSeries,
    OutletTransitionState,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    ActionInnovationTransitionParameters,
    CausalActionInnovationGeospatialKernel,
    action_innovation_transition_parameters_from_dict,
)
from data_agent.uwm.geospatial_kernel_v2.boundary_preserving_action_innovation import (
    BOUNDARY_PRESERVING_FORMULA,
    BoundaryPreservingActionInnovationGeospatialKernel,
)
from data_agent.uwm.geospatial_kernel_v2.counterfactual_action_response import (
    audit_counterfactual_release_steps,
)

if __package__:
    from scripts import audit_geospatial_kernel_counterfactual_action_response as response
    from scripts import evaluate_geospatial_kernel_action_innovation_cross_system as cross
else:
    import audit_geospatial_kernel_counterfactual_action_response as response
    import evaluate_geospatial_kernel_action_innovation_cross_system as cross


REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = Path(__file__).resolve()
CORE_OPERATOR_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/boundary_preserving_action_innovation.py"
)
DEFAULT_FREEZE = cross.DEFAULT_FREEZE
DEFAULT_PRIMARY_INPUT_REPORT = cross.DEFAULT_INPUT_REPORT
DEFAULT_PRIMARY_OUTCOME_REPORT = cross.DEFAULT_OUTCOME_REPORT
DEFAULT_REPLICATION_INPUT_REPORT = cross.DEFAULT_REPLICATION_INPUT_REPORT
DEFAULT_REPLICATION_OUTCOME_REPORT = cross.DEFAULT_REPLICATION_OUTCOME_REPORT
DEFAULT_HARD_RESPONSE_REPORT = response.DEFAULT_REPORT
DEFAULT_OUTPUT_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/geospatial_kernel_boundary_preserving_action_innovation_posthoc"
)
DEFAULT_OUTPUT = DEFAULT_OUTPUT_ROOT / "predictions.csv"
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_boundary_preserving_action_innovation_posthoc_report.json"
)
SCHEMA = "gwm.geotransport.boundary_preserving_action_innovation_posthoc.v1"
STATUS = "boundary_preserving_action_innovation_posthoc_complete_not_promoted"
SYSTEM_IDS = response.SYSTEM_IDS
WINDOW_NAMES = response.WINDOW_NAMES
DELTAS = response.DELTAS
HORIZONS = response.HORIZONS
RMSE_EQUALITY_TOLERANCE_M3S = 1e-12


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--primary-input-report", type=Path, default=DEFAULT_PRIMARY_INPUT_REPORT)
    parser.add_argument(
        "--primary-outcome-report", type=Path, default=DEFAULT_PRIMARY_OUTCOME_REPORT
    )
    parser.add_argument(
        "--replication-input-report",
        type=Path,
        default=DEFAULT_REPLICATION_INPUT_REPORT,
    )
    parser.add_argument(
        "--replication-outcome-report",
        type=Path,
        default=DEFAULT_REPLICATION_OUTCOME_REPORT,
    )
    parser.add_argument("--hard-response-report", type=Path, default=DEFAULT_HARD_RESPONSE_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_boundary_preserving_action_innovation_posthoc(
    *,
    freeze_path: Path = DEFAULT_FREEZE,
    primary_input_report_path: Path = DEFAULT_PRIMARY_INPUT_REPORT,
    primary_outcome_report_path: Path = DEFAULT_PRIMARY_OUTCOME_REPORT,
    replication_input_report_path: Path = DEFAULT_REPLICATION_INPUT_REPORT,
    replication_outcome_report_path: Path = DEFAULT_REPLICATION_OUTCOME_REPORT,
    hard_response_report_path: Path = DEFAULT_HARD_RESPONSE_REPORT,
    output_path: Path = DEFAULT_OUTPUT,
    generated_at: datetime | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Run the parameter-free boundary alternative on the fixed four windows."""

    freeze_body, freeze = cross._load_json(freeze_path)
    cross._validate_freeze(freeze)
    parameter_descriptor = freeze["candidate_artifacts"]["parameters"]
    parameter_body = cross._read_verified(parameter_descriptor)
    source_parameters = action_innovation_transition_parameters_from_dict(
        json.loads(parameter_body)
    )
    parameter_sha256 = hashlib.sha256(parameter_body).hexdigest()
    primary = response._load_report_pair(
        input_report_path=primary_input_report_path,
        outcome_report_path=primary_outcome_report_path,
        input_schema=cross.INPUT_SCHEMA,
        outcome_schema=cross.OUTCOME_SCHEMA,
    )
    replication = response._load_report_pair(
        input_report_path=replication_input_report_path,
        outcome_report_path=replication_outcome_report_path,
        input_schema=cross.REPLICATION_INPUT_SCHEMA,
        outcome_schema=cross.REPLICATION_OUTCOME_SCHEMA,
    )
    hard_response_body, hard_response_report = _load_hard_response_report(hard_response_report_path)
    primary_jpp_inputs = primary["input_report"]["systems"][cross.SYSTEM_ID]
    topology_body = cross._read_verified(primary_jpp_inputs["topology_report"])
    topology_report = json.loads(topology_body)
    network_payload = json.loads(
        cross._read_verified(topology_report["artifacts"]["full_subnetwork"])
    )
    target_support = cross._transfer_support(
        source=source_parameters.support,
        network_payload=network_payload,
        target_lock=primary["protocol"]["systems"][cross.SYSTEM_ID],
        source_parameter_sha256=parameter_sha256,
        topology_sha256=hashlib.sha256(topology_body).hexdigest(),
    )
    parameters_by_system = {
        "center_hill": source_parameters,
        cross.SYSTEM_ID: cross._transfer_parameters(
            source=source_parameters,
            support=target_support,
            source_parameter_sha256=parameter_sha256,
        ),
    }
    if cross._descriptor_identity(
        replication["input_report"]["systems"][cross.SYSTEM_ID]["topology_report"]
    ) != cross._descriptor_identity(primary_jpp_inputs["topology_report"]):
        raise ValueError("boundary_preserving_replication_topology_invalid")

    rows: list[dict[str, object]] = []
    windows: dict[str, Any] = {}
    for system_id in SYSTEM_IDS:
        for period_name, bundle in (("primary", primary), ("replication", replication)):
            window_name = f"{system_id}_{period_name}"
            parameters = parameters_by_system[system_id]
            window = response._load_system_window(
                system_id=system_id,
                bundle=bundle,
                parameters=parameters,
            )
            window_rows, result = _evaluate_window(
                window_name=window_name,
                system_id=system_id,
                window=window,
                parameters=parameters,
                parameter_sha256=parameter_sha256,
            )
            rows.extend(window_rows)
            windows[window_name] = result
    if tuple(windows) != WINDOW_NAMES:
        raise ValueError("boundary_preserving_window_order_invalid")
    for name, window in windows.items():
        hard_window = hard_response_report["windows"][name]
        hard_execution = hard_window["execution"]
        hard_numerical = hard_window["numerical_usability_gate"]
        bounded_numerical = window["counterfactual_response"]["numerical_usability_gate"]
        if int(hard_execution["forecast_issue_count"]) != int(
            window["execution"]["forecast_issue_count"]
        ) or int(hard_execution["response_row_count"]) != int(
            window["counterfactual_response"]["execution"]["response_row_count"]
        ):
            raise ValueError("boundary_preserving_hard_response_axis_mismatch")
        window["comparison_to_hard_clip_response"] = {
            "hard_clip_scenario_clipped_step_fraction": hard_execution[
                "scenario_clipped_step_fraction"
            ],
            "boundary_preserving_scenario_clipped_step_fraction": bounded_numerical[
                "scenario_clipped_step_fraction"
            ],
            "hard_clip_post_lag_response_collapse_fraction": hard_numerical[
                "post_lag_response_collapse_fraction"
            ],
            "boundary_preserving_post_lag_response_collapse_fraction": bounded_numerical[
                "post_lag_response_collapse_fraction"
            ],
            "collapse_fraction_change": (
                bounded_numerical["post_lag_response_collapse_fraction"]
                - hard_numerical["post_lag_response_collapse_fraction"]
            ),
            "hard_clip_structural_response_gate_passed": hard_window["structural_gate"][
                "structural_response_gate_passed"
            ],
            "boundary_preserving_structural_response_gate_passed": window[
                "counterfactual_response"
            ]["structural_gate"]["structural_response_gate_passed"],
        }

    output_body = _encode_rows(rows)
    comparison_counts = _comparison_counts(windows)
    structural_passed = all(
        window["counterfactual_response"]["structural_gate"]["structural_response_gate_passed"]
        for window in windows.values()
    )
    numerical_passed = all(
        window["counterfactual_response"]["numerical_usability_gate"][
            "numerical_usability_gate_passed"
        ]
        for window in windows.values()
    )
    accuracy_passed = (
        comparison_counts["boundary_lower_rmse_count"] >= 1
        and comparison_counts["hard_clip_lower_rmse_count"] == 0
    )
    posthoc_technical_passed = structural_passed and numerical_passed and accuracy_passed
    generated = generated_at if generated_at is not None else datetime.now(UTC)
    if generated.tzinfo is None or generated.utcoffset() is None:
        raise ValueError("boundary_preserving_generated_at_invalid")
    report = {
        "schema": SCHEMA,
        "status": STATUS,
        "generated_at": generated.astimezone(UTC).isoformat(),
        "implementation_artifacts": {
            "boundary_preserving_operator": _artifact(
                CORE_OPERATOR_PATH, CORE_OPERATOR_PATH.read_bytes()
            ),
            "evaluator": _artifact(EVALUATOR_PATH, EVALUATOR_PATH.read_bytes()),
        },
        "source_artifacts": {
            "candidate_freeze": _artifact(freeze_path, freeze_body),
            "frozen_parameters": dict(parameter_descriptor),
            "primary_input_report": _artifact(
                primary_input_report_path, primary["input_report_body"]
            ),
            "primary_outcome_report": _artifact(
                primary_outcome_report_path, primary["outcome_report_body"]
            ),
            "replication_input_report": _artifact(
                replication_input_report_path, replication["input_report_body"]
            ),
            "replication_outcome_report": _artifact(
                replication_outcome_report_path, replication["outcome_report_body"]
            ),
            "hard_clip_counterfactual_response_report": _artifact(
                hard_response_report_path, hard_response_body
            ),
        },
        "outputs": {"predictions": _artifact(output_path, output_body)},
        "operator_contract": {
            "formula": BOUNDARY_PRESERVING_FORMULA,
            "frozen_increment_formula_changed": False,
            "state_boundary_update_changed": True,
            "new_fitted_parameter_count": 0,
            "coefficient_refit_performed": False,
            "per_window_refit_performed": False,
            "hard_output_clip_used": False,
            "locally_first_order_equivalent_to_additive_update": True,
            "release_step_deltas_m3s": list(DELTAS),
            "horizons_hours": list(HORIZONS),
        },
        "windows": windows,
        "aggregate_comparison": comparison_counts,
        "promotion_gate": {
            "must_not_increase_rmse_in_any_of_16_window_horizon_comparisons": True,
            "must_strictly_reduce_rmse_in_at_least_one_comparison": True,
            "accuracy_gate_passed": accuracy_passed,
            "four_window_structural_response_gate_passed": structural_passed,
            "four_window_numerical_response_gate_passed": numerical_passed,
            "posthoc_technical_gate_passed": posthoc_technical_passed,
            "fresh_prospective_validation_required": True,
            "fresh_prospective_validation_passed": False,
            "boundary_preserving_candidate_promotion_gate_passed": False,
        },
        "diagnostic_interpretation": {
            "hard_clipping_eliminated_by_construction": True,
            "boundary_response_is_empirical_causal_identification": False,
            "historical_accuracy_supports_replacing_hard_clip": accuracy_passed,
            "posthoc_technical_candidate_supported": posthoc_technical_passed,
            "frozen_candidate_should_change": False,
        },
        "information_boundary": {
            "historical_outcomes_exposed_before_operator_design": True,
            "historical_outcome_used_only_for_posthoc_scoring_and_initial_state": True,
            "future_outcome_used_inside_forecast": False,
            "historical_realized_action_used": True,
            "retrospective_nwm_forcing_used": True,
            "evaluation_counts_as_fresh_validation": False,
        },
        "claim_boundary": {
            "boundary_preserving_operator_implemented": True,
            "boundary_preserving_operator_promoted": False,
            "counterfactual_release_effect_causally_validated": False,
            "action_innovation_candidate_changed": False,
            "prospective_v5_changed": False,
            "geospatial_kernel_validated": False,
            "runtime_default_enabled": False,
        },
    }
    return output_body, report


def _evaluate_window(
    *,
    window_name: str,
    system_id: str,
    window: Mapping[str, Any],
    parameters: ActionInnovationTransitionParameters,
    parameter_sha256: str,
) -> tuple[list[dict[str, object]], dict[str, Any]]:
    valid_times = tuple(window["valid_times"])
    outcomes = window["outcomes"]
    inputs = HourlyActionForcingSeries(
        valid_times=valid_times,
        action_release_m3s=tuple(window["action_values"]),
        nwm_lateral_inflow_m3s=tuple(window["forcing_values"]),
        action_provenance_id=f"historical-cwms:{window['action_sha256']}",
        forcing_provenance_id=f"retrospective-nwm:{window['forcing_sha256']}",
        action_plan_vintage_verified=False,
        forcing_vintage_verified=False,
    )
    hard_kernel = CausalActionInnovationGeospatialKernel(parameters)
    bounded_kernel = BoundaryPreservingActionInnovationGeospatialKernel(parameters)
    first_issue_index = max(parameters.support.lag_hours) + 1
    rows: list[dict[str, object]] = []
    response_rows: list[dict[str, object]] = []
    issue_count = 0
    skipped_missing = 0
    skipped_negative = 0
    hard_step_count = 0
    hard_clipped_step_count = 0
    bounded_step_count = 0
    boundary_adjusted_step_count = 0
    hard_clip_would_apply_count = 0
    exact_boundary_step_count = 0
    local_retentions: list[float] = []
    response_scenario_step_count = 0
    response_action_step_count = 0
    response_action_floor_step_count = 0
    for issue_index in range(first_issue_index, len(valid_times) - max(HORIZONS)):
        issue_time = valid_times[issue_index]
        state_time = valid_times[issue_index - 1]
        state_value = outcomes[state_time]
        if state_value is None:
            skipped_missing += 1
            continue
        if float(state_value) < 0.0:
            skipped_negative += 1
            continue
        state = OutletTransitionState(
            valid_at=state_time,
            available_at=issue_time,
            discharge_m3s=float(state_value),
            provenance_id=(
                f"historical-usgs:{window['outcome_sha256']}:valid={cross._iso(state_time)}"
            ),
            evidence_level="candidate",
            observed=True,
        )
        targets = tuple(issue_time + timedelta(hours=value) for value in HORIZONS)
        hard = hard_kernel.forecast(
            state, inputs, issue_time=issue_time, target_valid_times=targets
        )
        bounded = bounded_kernel.forecast(
            state, inputs, issue_time=issue_time, target_valid_times=targets
        )
        action_response = audit_counterfactual_release_steps(
            parameters=parameters,
            state=state,
            inputs=inputs,
            issue_time=issue_time,
            release_deltas_m3s=DELTAS,
            horizons_hours=HORIZONS,
            kernel=bounded_kernel,
        )
        issue_count += 1
        hard_step_count += len(hard.steps)
        hard_clipped_step_count += sum(step.clipped for step in hard.steps)
        bounded_step_count += len(bounded.steps)
        boundary_adjusted_step_count += sum(step.boundary_adjusted for step in bounded.steps)
        hard_clip_would_apply_count += sum(step.hard_clip_would_apply for step in bounded.steps)
        exact_boundary_step_count += sum(
            step.predicted_discharge_m3s in (0.0, parameters.maximum_discharge_m3s)
            for step in bounded.steps
        )
        local_retentions.extend(step.local_increment_retention for step in bounded.steps)
        for scenario in action_response.scenarios:
            response_scenario_step_count += len(scenario.forecast.steps)
            response_action_step_count += scenario.action_step_count
            response_action_floor_step_count += scenario.action_floor_step_count
        for response_row in action_response.responses:
            response_rows.append(
                {
                    "system_id": system_id,
                    "window_id": window_name,
                    "issue_time_utc": cross._iso(issue_time),
                    "latest_observation_valid_at_utc": cross._iso(state_time),
                    "target_support_end_utc": cross._iso(
                        issue_time + timedelta(hours=response_row.horizon_hours)
                    ),
                    **response_row.as_dict(),
                    "future_outcome_observation_used": False,
                    "operational_vintages_verified": False,
                    "parameter_sha256": parameter_sha256,
                }
            )
        for offset, (horizon, target) in enumerate(zip(HORIZONS, targets, strict=True)):
            observed = outcomes[target]
            rows.append(
                {
                    "system_id": system_id,
                    "window_id": window_name,
                    "issue_time_utc": cross._iso(issue_time),
                    "target_support_end_utc": cross._iso(target),
                    "horizon_hours": horizon,
                    "observed_discharge_m3s": "" if observed is None else observed,
                    "hard_clipped_action_innovation_m3s": hard.target_discharge_m3s[offset],
                    "boundary_preserving_action_innovation_m3s": (
                        bounded.target_discharge_m3s[offset]
                    ),
                    "causal_persistence_m3s": state.discharge_m3s,
                    "future_outcome_observation_used": False,
                    "operational_vintages_verified": False,
                    "parameter_sha256": parameter_sha256,
                }
            )
    if not rows or not response_rows:
        raise ValueError("boundary_preserving_no_executable_rows")
    metrics = _score(rows)
    comparison = _window_comparison(metrics)
    response_execution = {
        "forecast_issue_count": issue_count,
        "response_row_count": len(response_rows),
        "skipped_missing_state_issue_count": skipped_missing,
        "skipped_negative_state_issue_count": skipped_negative,
        "baseline_step_count": bounded_step_count,
        "baseline_clipped_step_count": 0,
        "scenario_step_count": response_scenario_step_count,
        "scenario_clipped_step_count": 0,
        "action_step_count": response_action_step_count,
        "action_floor_step_count": response_action_floor_step_count,
        "first_issue_time_utc": rows[0]["issue_time_utc"],
        "last_issue_time_utc": rows[-1]["issue_time_utc"],
    }
    counterfactual = response._summarize_window(response_rows, response_execution)
    return rows, {
        "system_id": system_id,
        "window_id": window_name,
        "execution": {
            "forecast_issue_count": issue_count,
            "prediction_row_count": len(rows),
            "skipped_missing_state_issue_count": skipped_missing,
            "skipped_negative_state_issue_count": skipped_negative,
            "hard_clipped_step_count": hard_clipped_step_count,
            "hard_clipped_step_fraction": hard_clipped_step_count / hard_step_count,
            "boundary_preserving_step_count": bounded_step_count,
            "boundary_adjusted_step_count": boundary_adjusted_step_count,
            "boundary_adjusted_step_fraction": (boundary_adjusted_step_count / bounded_step_count),
            "hard_clip_would_apply_step_count": hard_clip_would_apply_count,
            "hard_clip_would_apply_step_fraction": (
                hard_clip_would_apply_count / bounded_step_count
            ),
            "exact_boundary_step_count": exact_boundary_step_count,
            "minimum_local_increment_retention": min(local_retentions),
            "median_local_increment_retention": median(local_retentions),
            "p05_local_increment_retention": _quantile(local_retentions, 0.05),
        },
        "metrics_by_horizon": metrics,
        "comparison_to_hard_clip": comparison,
        "counterfactual_response": counterfactual,
    }


def _load_hard_response_report(path: Path) -> tuple[bytes, Mapping[str, Any]]:
    body, report = cross._load_json(path)
    claims = report.get("claim_boundary") or {}
    if (
        report.get("schema") != response.SCHEMA
        or report.get("status") != response.STATUS
        or tuple((report.get("windows") or {}).keys()) != WINDOW_NAMES
        or (report.get("aggregate_gate") or {}).get(
            "counterfactual_interface_promotion_gate_passed"
        )
        is not False
        or claims.get("counterfactual_release_effect_causally_validated") is not False
    ):
        raise ValueError("boundary_preserving_hard_response_report_invalid")
    cross._read_verified(
        report["implementation_artifacts"]["counterfactual_action_response_operator"]
    )
    cross._read_verified(report["implementation_artifacts"]["evaluator"])
    cross._read_verified(report["outputs"]["responses"])
    return body, report


def _score(rows: list[dict[str, object]]) -> dict[str, dict[str, dict[str, float]]]:
    columns = {
        "boundary_preserving": "boundary_preserving_action_innovation_m3s",
        "hard_clipped": "hard_clipped_action_innovation_m3s",
        "causal_persistence": "causal_persistence_m3s",
    }
    metrics: dict[str, dict[str, dict[str, float]]] = {}
    for horizon in HORIZONS:
        selected = [
            row
            for row in rows
            if int(row["horizon_hours"]) == horizon and row["observed_discharge_m3s"] != ""
        ]
        observed = [float(row["observed_discharge_m3s"]) for row in selected]
        metrics[str(horizon)] = {
            name: _metrics(observed, [float(row[column]) for row in selected])
            for name, column in columns.items()
        }
    return metrics


def _metrics(observed: list[float], predicted: list[float]) -> dict[str, float]:
    if not observed or len(observed) != len(predicted):
        raise ValueError("boundary_preserving_metric_axis_invalid")
    errors = [prediction - outcome for prediction, outcome in zip(predicted, observed, strict=True)]
    mean_observed = sum(observed) / len(observed)
    denominator = sum((value - mean_observed) ** 2 for value in observed)
    squared_error = sum(value**2 for value in errors)
    return {
        "sample_count": len(observed),
        "rmse_m3s": math.sqrt(squared_error / len(errors)),
        "mae_m3s": sum(abs(value) for value in errors) / len(errors),
        "bias_m3s": sum(errors) / len(errors),
        "nse": 1.0 - squared_error / denominator,
    }


def _window_comparison(
    metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> dict[str, Any]:
    per_horizon: dict[str, Any] = {}
    wins: list[int] = []
    losses: list[int] = []
    ties: list[int] = []
    for horizon in HORIZONS:
        bounded = metrics[str(horizon)]["boundary_preserving"]["rmse_m3s"]
        hard = metrics[str(horizon)]["hard_clipped"]["rmse_m3s"]
        delta = bounded - hard
        if delta < -RMSE_EQUALITY_TOLERANCE_M3S:
            wins.append(horizon)
        elif delta > RMSE_EQUALITY_TOLERANCE_M3S:
            losses.append(horizon)
        else:
            ties.append(horizon)
        per_horizon[str(horizon)] = {
            "boundary_minus_hard_clip_rmse_m3s": delta,
            "boundary_lower_rmse": horizon in wins,
            "hard_clip_lower_rmse": horizon in losses,
            "rmse_equal_within_tolerance": horizon in ties,
        }
    return {
        "per_horizon": per_horizon,
        "boundary_lower_rmse_horizons_hours": wins,
        "hard_clip_lower_rmse_horizons_hours": losses,
        "equal_rmse_horizons_hours": ties,
        "boundary_not_worse_all_horizons": not losses,
    }


def _comparison_counts(windows: Mapping[str, Mapping[str, Any]]) -> dict[str, int]:
    wins = 0
    losses = 0
    ties = 0
    for window in windows.values():
        comparison = window["comparison_to_hard_clip"]
        wins += len(comparison["boundary_lower_rmse_horizons_hours"])
        losses += len(comparison["hard_clip_lower_rmse_horizons_hours"])
        ties += len(comparison["equal_rmse_horizons_hours"])
    return {
        "comparison_count": wins + losses + ties,
        "boundary_lower_rmse_count": wins,
        "hard_clip_lower_rmse_count": losses,
        "equal_rmse_count": ties,
    }


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _encode_rows(rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _artifact(path: Path, body: bytes) -> dict[str, object]:
    try:
        display = path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        display = str(path.resolve())
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _json_body(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> None:
    args = parse_args()
    output_body, report = compile_boundary_preserving_action_innovation_posthoc(
        freeze_path=args.freeze,
        primary_input_report_path=args.primary_input_report,
        primary_outcome_report_path=args.primary_outcome_report,
        replication_input_report_path=args.replication_input_report,
        replication_outcome_report_path=args.replication_outcome_report,
        hard_response_report_path=args.hard_response_report,
        output_path=args.output,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output_body)
    args.report.write_bytes(_json_body(report))
    counts = report["aggregate_comparison"]
    print(f"status={report['status']}")
    print(
        "rmse_comparisons="
        f"boundary:{counts['boundary_lower_rmse_count']},"
        f"hard_clip:{counts['hard_clip_lower_rmse_count']},"
        f"equal:{counts['equal_rmse_count']}"
    )
    for name, window in report["windows"].items():
        execution = window["execution"]
        numerical = window["counterfactual_response"]["numerical_usability_gate"]
        print(
            f"window={name} "
            f"hard_clip_would_apply={execution['hard_clip_would_apply_step_fraction']:.6f} "
            f"response_collapse={numerical['post_lag_response_collapse_fraction']:.6f}"
        )
    print(
        "boundary_preserving_candidate_promotion_gate_passed="
        f"{str(report['promotion_gate']['boundary_preserving_candidate_promotion_gate_passed']).lower()}"
    )


if __name__ == "__main__":
    main()
