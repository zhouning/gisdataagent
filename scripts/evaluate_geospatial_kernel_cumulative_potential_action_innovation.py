#!/usr/bin/env python3
"""Evaluate cumulative latent action potential against prior boundary updates."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
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
from data_agent.uwm.geospatial_kernel_v2.counterfactual_action_response import (
    audit_counterfactual_release_steps,
)
from data_agent.uwm.geospatial_kernel_v2.cumulative_potential_action_innovation import (
    CUMULATIVE_POTENTIAL_FORMULA,
    CumulativePotentialActionInnovationGeospatialKernel,
)

if __package__:
    from scripts import audit_geospatial_kernel_counterfactual_action_response as response
    from scripts import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    from scripts import evaluate_geospatial_kernel_boundary_preserving_action_innovation as prior
else:
    import audit_geospatial_kernel_counterfactual_action_response as response
    import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    import evaluate_geospatial_kernel_boundary_preserving_action_innovation as prior


REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = Path(__file__).resolve()
CORE_OPERATOR_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/cumulative_potential_action_innovation.py"
)
DEFAULT_FREEZE = cross.DEFAULT_FREEZE
DEFAULT_PRIMARY_INPUT_REPORT = cross.DEFAULT_INPUT_REPORT
DEFAULT_PRIMARY_OUTCOME_REPORT = cross.DEFAULT_OUTCOME_REPORT
DEFAULT_REPLICATION_INPUT_REPORT = cross.DEFAULT_REPLICATION_INPUT_REPORT
DEFAULT_REPLICATION_OUTCOME_REPORT = cross.DEFAULT_REPLICATION_OUTCOME_REPORT
DEFAULT_HARD_RESPONSE_REPORT = response.DEFAULT_REPORT
DEFAULT_RECURSIVE_BOUNDARY_REPORT = prior.DEFAULT_REPORT
DEFAULT_OUTPUT_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/geospatial_kernel_cumulative_potential_action_innovation_posthoc"
)
DEFAULT_OUTPUT = DEFAULT_OUTPUT_ROOT / "predictions.csv"
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_cumulative_potential_action_innovation_posthoc_report.json"
)
SCHEMA = "gwm.geotransport.cumulative_potential_action_innovation_posthoc.v1"
STATUS = "cumulative_potential_action_innovation_posthoc_complete_not_promoted"
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
    parser.add_argument(
        "--recursive-boundary-report",
        type=Path,
        default=DEFAULT_RECURSIVE_BOUNDARY_REPORT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_cumulative_potential_action_innovation_posthoc(
    *,
    freeze_path: Path = DEFAULT_FREEZE,
    primary_input_report_path: Path = DEFAULT_PRIMARY_INPUT_REPORT,
    primary_outcome_report_path: Path = DEFAULT_PRIMARY_OUTCOME_REPORT,
    replication_input_report_path: Path = DEFAULT_REPLICATION_INPUT_REPORT,
    replication_outcome_report_path: Path = DEFAULT_REPLICATION_OUTCOME_REPORT,
    hard_response_report_path: Path = DEFAULT_HARD_RESPONSE_REPORT,
    recursive_boundary_report_path: Path = DEFAULT_RECURSIVE_BOUNDARY_REPORT,
    output_path: Path = DEFAULT_OUTPUT,
    generated_at: datetime | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Run the cumulative-potential candidate on the fixed historical windows."""

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
    hard_response_body, hard_response_report = prior._load_hard_response_report(
        hard_response_report_path
    )
    recursive_body, recursive_report = _load_recursive_boundary_report(
        recursive_boundary_report_path
    )
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
        raise ValueError("cumulative_potential_replication_topology_invalid")

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
        raise ValueError("cumulative_potential_window_order_invalid")

    for name, window in windows.items():
        hard_window = hard_response_report["windows"][name]
        recursive_window = recursive_report["windows"][name]
        if int(hard_window["execution"]["forecast_issue_count"]) != int(
            window["execution"]["forecast_issue_count"]
        ) or int(recursive_window["execution"]["forecast_issue_count"]) != int(
            window["execution"]["forecast_issue_count"]
        ):
            raise ValueError("cumulative_potential_comparison_axis_mismatch")
        cumulative_response = window["counterfactual_response"]
        hard_numerical = hard_window["numerical_usability_gate"]
        recursive_response = recursive_window["counterfactual_response"]
        window["response_comparison"] = {
            "hard_clip": {
                "structural_gate_passed": hard_window["structural_gate"][
                    "structural_response_gate_passed"
                ],
                "collapse_fraction": hard_numerical["post_lag_response_collapse_fraction"],
                "scenario_clipped_step_fraction": hard_window["execution"][
                    "scenario_clipped_step_fraction"
                ],
            },
            "recursive_boundary": {
                "structural_gate_passed": recursive_response["structural_gate"][
                    "structural_response_gate_passed"
                ],
                "collapse_fraction": recursive_response["numerical_usability_gate"][
                    "post_lag_response_collapse_fraction"
                ],
                "scenario_clipped_step_fraction": recursive_response["numerical_usability_gate"][
                    "scenario_clipped_step_fraction"
                ],
            },
            "cumulative_potential": {
                "structural_gate_passed": cumulative_response["structural_gate"][
                    "structural_response_gate_passed"
                ],
                "collapse_fraction": cumulative_response["numerical_usability_gate"][
                    "post_lag_response_collapse_fraction"
                ],
                "scenario_clipped_step_fraction": cumulative_response["numerical_usability_gate"][
                    "scenario_clipped_step_fraction"
                ],
            },
        }
        window["comparison_to_recursive_boundary"] = _compare_to_recursive(
            cumulative_metrics=window["metrics_by_horizon"],
            recursive_metrics=recursive_window["metrics_by_horizon"],
        )

    output_body = _encode_rows(rows)
    hard_counts = _comparison_counts(windows, "comparison_to_hard_clip")
    recursive_counts = _comparison_counts(windows, "comparison_to_recursive_boundary")
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
        hard_counts["candidate_lower_rmse_count"] >= 1
        and hard_counts["comparator_lower_rmse_count"] == 0
    )
    posthoc_technical_passed = structural_passed and numerical_passed and accuracy_passed
    generated = generated_at if generated_at is not None else datetime.now(UTC)
    if generated.tzinfo is None or generated.utcoffset() is None:
        raise ValueError("cumulative_potential_generated_at_invalid")
    report = {
        "schema": SCHEMA,
        "status": STATUS,
        "generated_at": generated.astimezone(UTC).isoformat(),
        "implementation_artifacts": {
            "cumulative_potential_operator": _artifact(
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
            "recursive_boundary_report": _artifact(recursive_boundary_report_path, recursive_body),
        },
        "outputs": {"predictions": _artifact(output_path, output_body)},
        "operator_contract": {
            "formula": CUMULATIVE_POTENTIAL_FORMULA,
            "frozen_increment_formula_changed": False,
            "latent_potential_accumulated_before_boundary_projection": True,
            "predicted_state_carries_anchor_and_cumulative_potential": True,
            "split_rollout_equals_one_shot_rollout": True,
            "new_fitted_parameter_count": 0,
            "coefficient_refit_performed": False,
            "hard_output_clip_used": False,
            "release_step_deltas_m3s": list(DELTAS),
            "horizons_hours": list(HORIZONS),
        },
        "windows": windows,
        "aggregate_comparison_to_hard_clip": hard_counts,
        "aggregate_comparison_to_recursive_boundary": recursive_counts,
        "promotion_gate": {
            "must_not_increase_rmse_in_any_of_16_hard_clip_comparisons": True,
            "must_strictly_reduce_rmse_in_at_least_one_hard_clip_comparison": True,
            "accuracy_gate_passed": accuracy_passed,
            "four_window_structural_response_gate_passed": structural_passed,
            "four_window_numerical_response_gate_passed": numerical_passed,
            "posthoc_technical_gate_passed": posthoc_technical_passed,
            "fresh_prospective_validation_required": True,
            "fresh_prospective_validation_passed": False,
            "cumulative_potential_candidate_promotion_gate_passed": False,
        },
        "diagnostic_interpretation": {
            "cumulative_state_restores_four_window_action_monotonicity": structural_passed,
            "cumulative_state_is_empirical_causal_identification": False,
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
            "cumulative_potential_operator_implemented": True,
            "cumulative_potential_operator_promoted": False,
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
    cumulative_kernel = CumulativePotentialActionInnovationGeospatialKernel(parameters)
    first_issue_index = max(parameters.support.lag_hours) + 1
    rows: list[dict[str, object]] = []
    response_rows: list[dict[str, object]] = []
    issue_count = 0
    skipped_missing = 0
    skipped_negative = 0
    hard_step_count = 0
    hard_clipped_step_count = 0
    candidate_step_count = 0
    boundary_adjusted_step_count = 0
    hard_clip_would_apply_count = 0
    exact_boundary_step_count = 0
    potential_retentions: list[float] = []
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
        candidate = cumulative_kernel.forecast(
            state, inputs, issue_time=issue_time, target_valid_times=targets
        )
        action_response = audit_counterfactual_release_steps(
            parameters=parameters,
            state=state,
            inputs=inputs,
            issue_time=issue_time,
            release_deltas_m3s=DELTAS,
            horizons_hours=HORIZONS,
            kernel=cumulative_kernel,
        )
        issue_count += 1
        hard_step_count += len(hard.steps)
        hard_clipped_step_count += sum(step.clipped for step in hard.steps)
        candidate_step_count += len(candidate.steps)
        boundary_adjusted_step_count += sum(step.boundary_adjusted for step in candidate.steps)
        hard_clip_would_apply_count += sum(step.hard_clip_would_apply for step in candidate.steps)
        exact_boundary_step_count += sum(
            step.predicted_discharge_m3s in (0.0, parameters.maximum_discharge_m3s)
            for step in candidate.steps
        )
        potential_retentions.extend(step.potential_retention for step in candidate.steps)
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
                    "cumulative_potential_action_innovation_m3s": (
                        candidate.target_discharge_m3s[offset]
                    ),
                    "causal_persistence_m3s": state.discharge_m3s,
                    "future_outcome_observation_used": False,
                    "operational_vintages_verified": False,
                    "parameter_sha256": parameter_sha256,
                }
            )
    if not rows or not response_rows:
        raise ValueError("cumulative_potential_no_executable_rows")
    metrics = _score(rows)
    comparison = _compare_metrics(
        metrics,
        candidate_name="cumulative_potential",
        comparator_name="hard_clipped",
    )
    response_execution = {
        "forecast_issue_count": issue_count,
        "response_row_count": len(response_rows),
        "skipped_missing_state_issue_count": skipped_missing,
        "skipped_negative_state_issue_count": skipped_negative,
        "baseline_step_count": candidate_step_count,
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
            "cumulative_potential_step_count": candidate_step_count,
            "boundary_adjusted_step_count": boundary_adjusted_step_count,
            "boundary_adjusted_step_fraction": (
                boundary_adjusted_step_count / candidate_step_count
            ),
            "hard_clip_would_apply_step_count": hard_clip_would_apply_count,
            "hard_clip_would_apply_step_fraction": (
                hard_clip_would_apply_count / candidate_step_count
            ),
            "exact_boundary_step_count": exact_boundary_step_count,
            "minimum_potential_retention": min(potential_retentions),
            "median_potential_retention": median(potential_retentions),
            "p05_potential_retention": prior._quantile(potential_retentions, 0.05),
        },
        "metrics_by_horizon": metrics,
        "comparison_to_hard_clip": comparison,
        "counterfactual_response": counterfactual,
    }


def _score(rows: list[dict[str, object]]) -> dict[str, dict[str, dict[str, float]]]:
    columns = {
        "cumulative_potential": "cumulative_potential_action_innovation_m3s",
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
            name: prior._metrics(
                observed,
                [float(row[column]) for row in selected],
            )
            for name, column in columns.items()
        }
    return metrics


def _compare_metrics(
    metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
    *,
    candidate_name: str,
    comparator_name: str,
) -> dict[str, Any]:
    wins: list[int] = []
    losses: list[int] = []
    ties: list[int] = []
    per_horizon: dict[str, Any] = {}
    for horizon in HORIZONS:
        candidate = metrics[str(horizon)][candidate_name]["rmse_m3s"]
        comparator = metrics[str(horizon)][comparator_name]["rmse_m3s"]
        delta = candidate - comparator
        if delta < -RMSE_EQUALITY_TOLERANCE_M3S:
            wins.append(horizon)
        elif delta > RMSE_EQUALITY_TOLERANCE_M3S:
            losses.append(horizon)
        else:
            ties.append(horizon)
        per_horizon[str(horizon)] = {
            "candidate_minus_comparator_rmse_m3s": delta,
            "candidate_lower_rmse": horizon in wins,
            "comparator_lower_rmse": horizon in losses,
            "rmse_equal_within_tolerance": horizon in ties,
        }
    return {
        "per_horizon": per_horizon,
        "candidate_lower_rmse_horizons_hours": wins,
        "comparator_lower_rmse_horizons_hours": losses,
        "equal_rmse_horizons_hours": ties,
        "candidate_not_worse_all_horizons": not losses,
    }


def _compare_to_recursive(
    *,
    cumulative_metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
    recursive_metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> dict[str, Any]:
    combined = {
        str(horizon): {
            "cumulative": cumulative_metrics[str(horizon)]["cumulative_potential"],
            "recursive": recursive_metrics[str(horizon)]["boundary_preserving"],
        }
        for horizon in HORIZONS
    }
    return _compare_metrics(
        combined,
        candidate_name="cumulative",
        comparator_name="recursive",
    )


def _comparison_counts(
    windows: Mapping[str, Mapping[str, Any]], comparison_name: str
) -> dict[str, int]:
    wins = sum(
        len(window[comparison_name]["candidate_lower_rmse_horizons_hours"])
        for window in windows.values()
    )
    losses = sum(
        len(window[comparison_name]["comparator_lower_rmse_horizons_hours"])
        for window in windows.values()
    )
    ties = sum(
        len(window[comparison_name]["equal_rmse_horizons_hours"]) for window in windows.values()
    )
    return {
        "comparison_count": wins + losses + ties,
        "candidate_lower_rmse_count": wins,
        "comparator_lower_rmse_count": losses,
        "equal_rmse_count": ties,
    }


def _load_recursive_boundary_report(path: Path) -> tuple[bytes, Mapping[str, Any]]:
    body, report = cross._load_json(path)
    claims = report.get("claim_boundary") or {}
    if (
        report.get("schema") != prior.SCHEMA
        or report.get("status") != prior.STATUS
        or tuple((report.get("windows") or {}).keys()) != WINDOW_NAMES
        or claims.get("boundary_preserving_operator_promoted") is not False
        or claims.get("geospatial_kernel_validated") is not False
    ):
        raise ValueError("cumulative_potential_recursive_report_invalid")
    cross._read_verified(report["implementation_artifacts"]["boundary_preserving_operator"])
    cross._read_verified(report["implementation_artifacts"]["evaluator"])
    cross._read_verified(report["outputs"]["predictions"])
    return body, report


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
    output_body, report = compile_cumulative_potential_action_innovation_posthoc(
        freeze_path=args.freeze,
        primary_input_report_path=args.primary_input_report,
        primary_outcome_report_path=args.primary_outcome_report,
        replication_input_report_path=args.replication_input_report,
        replication_outcome_report_path=args.replication_outcome_report,
        hard_response_report_path=args.hard_response_report,
        recursive_boundary_report_path=args.recursive_boundary_report,
        output_path=args.output,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output_body)
    args.report.write_bytes(_json_body(report))
    hard = report["aggregate_comparison_to_hard_clip"]
    recursive = report["aggregate_comparison_to_recursive_boundary"]
    print(f"status={report['status']}")
    print(
        "vs_hard_clip="
        f"candidate:{hard['candidate_lower_rmse_count']},"
        f"hard:{hard['comparator_lower_rmse_count']},"
        f"equal:{hard['equal_rmse_count']}"
    )
    print(
        "vs_recursive_boundary="
        f"candidate:{recursive['candidate_lower_rmse_count']},"
        f"recursive:{recursive['comparator_lower_rmse_count']},"
        f"equal:{recursive['equal_rmse_count']}"
    )
    for name, window in report["windows"].items():
        structural = window["counterfactual_response"]["structural_gate"]
        numerical = window["counterfactual_response"]["numerical_usability_gate"]
        print(
            f"window={name} "
            f"monotonic={str(structural['monotonicity_gate_passed']).lower()} "
            f"collapse={numerical['post_lag_response_collapse_fraction']:.6f}"
        )
    print(
        "cumulative_potential_candidate_promotion_gate_passed="
        f"{str(report['promotion_gate']['cumulative_potential_candidate_promotion_gate_passed']).lower()}"
    )


if __name__ == "__main__":
    main()
