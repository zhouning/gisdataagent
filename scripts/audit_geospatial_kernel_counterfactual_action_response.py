#!/usr/bin/env python3
"""Audit release-step responses on two reservoirs and two historical windows."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from collections import defaultdict
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
    action_innovation_transition_parameters_from_dict,
)
from data_agent.uwm.geospatial_kernel_v2.counterfactual_action_response import (
    DEFAULT_RELEASE_STEP_DELTAS_M3S,
    DEFAULT_RESPONSE_HORIZONS_HOURS,
    RESPONSE_TOLERANCE_M3S,
    audit_counterfactual_release_steps,
)

if __package__:
    from scripts import evaluate_geospatial_kernel_action_innovation_cross_system as cross
else:
    import evaluate_geospatial_kernel_action_innovation_cross_system as cross


REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = Path(__file__).resolve()
CORE_OPERATOR_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/counterfactual_action_response.py"
)
DEFAULT_FREEZE = cross.DEFAULT_FREEZE
DEFAULT_PRIMARY_INPUT_REPORT = cross.DEFAULT_INPUT_REPORT
DEFAULT_PRIMARY_OUTCOME_REPORT = cross.DEFAULT_OUTCOME_REPORT
DEFAULT_REPLICATION_INPUT_REPORT = cross.DEFAULT_REPLICATION_INPUT_REPORT
DEFAULT_REPLICATION_OUTCOME_REPORT = cross.DEFAULT_REPLICATION_OUTCOME_REPORT
DEFAULT_OUTPUT_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/geospatial_kernel_counterfactual_action_response_posthoc"
)
DEFAULT_OUTPUT = DEFAULT_OUTPUT_ROOT / "responses.csv"
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_counterfactual_action_response_posthoc_report.json"
)
SCHEMA = "gwm.geotransport.counterfactual_action_response_posthoc.v1"
STATUS = "counterfactual_action_response_posthoc_complete_not_causally_validated"
SYSTEM_IDS = ("center_hill", cross.SYSTEM_ID)
WINDOW_NAMES = (
    "center_hill_primary",
    "center_hill_replication",
    "j_percy_priest_primary",
    "j_percy_priest_replication",
)
DELTAS = DEFAULT_RELEASE_STEP_DELTAS_M3S
HORIZONS = DEFAULT_RESPONSE_HORIZONS_HOURS
MAXIMUM_CLIPPED_STEP_FRACTION = 0.05
MAXIMUM_POST_LAG_COLLAPSE_FRACTION = 0.05


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
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_counterfactual_action_response_posthoc(
    *,
    freeze_path: Path = DEFAULT_FREEZE,
    primary_input_report_path: Path = DEFAULT_PRIMARY_INPUT_REPORT,
    primary_outcome_report_path: Path = DEFAULT_PRIMARY_OUTCOME_REPORT,
    replication_input_report_path: Path = DEFAULT_REPLICATION_INPUT_REPORT,
    replication_outcome_report_path: Path = DEFAULT_REPLICATION_OUTCOME_REPORT,
    output_path: Path = DEFAULT_OUTPUT,
    generated_at: datetime | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Compile a fixed posthoc structural audit without fitting parameters."""

    freeze_body, freeze = cross._load_json(freeze_path)
    cross._validate_freeze(freeze)
    parameter_descriptor = freeze["candidate_artifacts"]["parameters"]
    parameter_body = cross._read_verified(parameter_descriptor)
    source_parameters = action_innovation_transition_parameters_from_dict(
        json.loads(parameter_body)
    )
    parameter_sha256 = hashlib.sha256(parameter_body).hexdigest()

    primary = _load_report_pair(
        input_report_path=primary_input_report_path,
        outcome_report_path=primary_outcome_report_path,
        input_schema=cross.INPUT_SCHEMA,
        outcome_schema=cross.OUTCOME_SCHEMA,
    )
    replication = _load_report_pair(
        input_report_path=replication_input_report_path,
        outcome_report_path=replication_outcome_report_path,
        input_schema=cross.REPLICATION_INPUT_SCHEMA,
        outcome_schema=cross.REPLICATION_OUTCOME_SCHEMA,
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
        raise ValueError("counterfactual_action_response_replication_topology_invalid")

    rows: list[dict[str, object]] = []
    windows: dict[str, Any] = {}
    for system_id in SYSTEM_IDS:
        for period_name, bundle in (("primary", primary), ("replication", replication)):
            window_name = f"{system_id}_{period_name}"
            parameters = parameters_by_system[system_id]
            window = _load_system_window(
                system_id=system_id,
                bundle=bundle,
                parameters=parameters,
            )
            window_rows, execution = _audit_window(
                window_name=window_name,
                system_id=system_id,
                window=window,
                parameters=parameters,
                parameter_sha256=parameter_sha256,
            )
            rows.extend(window_rows)
            windows[window_name] = _summarize_window(window_rows, execution)

    if tuple(windows) != WINDOW_NAMES:
        raise ValueError("counterfactual_action_response_window_order_invalid")
    output_body = _encode_rows(rows)
    structural_passed = all(
        window["structural_gate"]["structural_response_gate_passed"] for window in windows.values()
    )
    numerical_passed = all(
        window["numerical_usability_gate"]["numerical_usability_gate_passed"]
        for window in windows.values()
    )
    generated = generated_at if generated_at is not None else datetime.now(UTC)
    if generated.tzinfo is None or generated.utcoffset() is None:
        raise ValueError("counterfactual_action_response_generated_at_invalid")
    report = {
        "schema": SCHEMA,
        "status": STATUS,
        "generated_at": generated.astimezone(UTC).isoformat(),
        "implementation_artifacts": {
            "counterfactual_action_response_operator": _artifact(
                CORE_OPERATOR_PATH, CORE_OPERATOR_PATH.read_bytes()
            ),
            "evaluator": _artifact(EVALUATOR_PATH, EVALUATOR_PATH.read_bytes()),
        },
        "source_artifacts": {
            "candidate_freeze": _artifact(freeze_path, freeze_body),
            "frozen_source_parameters": dict(parameter_descriptor),
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
        },
        "outputs": {"responses": _artifact(output_path, output_body)},
        "protocol": {
            "systems": list(SYSTEM_IDS),
            "windows": list(WINDOW_NAMES),
            "release_step_deltas_m3s": list(DELTAS),
            "horizons_hours": list(HORIZONS),
            "intervention_starts_strictly_after_issue_time": True,
            "pre_issue_action_history_preserved": True,
            "negative_release_floored_at_zero": True,
            "same_frozen_action_innovation_coefficients_used_in_all_windows": True,
            "coefficient_refit_performed": False,
            "maximum_clipped_scenario_step_fraction": MAXIMUM_CLIPPED_STEP_FRACTION,
            "maximum_post_lag_response_collapse_fraction": (MAXIMUM_POST_LAG_COLLAPSE_FRACTION),
        },
        "windows": windows,
        "aggregate_gate": {
            "four_window_structural_response_gate_passed": structural_passed,
            "four_window_numerical_usability_gate_passed": numerical_passed,
            "interventional_causal_validation_gate_passed": False,
            "counterfactual_interface_promotion_gate_passed": False,
        },
        "diagnostic_interpretation": {
            "fixed_lag_and_nonnegative_coefficient_enforce_response_direction": (structural_passed),
            "structural_monotonicity_is_empirical_causal_identification": False,
            "historical_observational_action_archive_identifies_do_release_effect": False,
            "alternative_release_outcomes_observed": False,
            "numerically_usable_without_pathological_clipping_in_all_windows": (numerical_passed),
            "candidate_may_be_used_for_policy_effect_claims": False,
        },
        "information_boundary": {
            "historical_cwms_release_archive_used": True,
            "retrospective_nwm_forcing_used": True,
            "historical_outcome_used_only_as_pre_issue_initial_state": True,
            "future_outcome_used_inside_counterfactual_rollout": False,
            "observed_outcome_under_alternative_release_available": False,
            "randomized_or_natural_release_experiment_available": False,
            "evaluation_counts_as_fresh_validation": False,
        },
        "claim_boundary": {
            "counterfactual_release_interface_structurally_audited": True,
            "counterfactual_release_effect_causally_validated": False,
            "action_innovation_candidate_changed": False,
            "prospective_v5_changed": False,
            "candidate_admitted": False,
            "geospatial_kernel_validated": False,
            "operational_forecast_validated": False,
            "runtime_default_enabled": False,
        },
    }
    return output_body, report


def _load_report_pair(
    *,
    input_report_path: Path,
    outcome_report_path: Path,
    input_schema: str,
    outcome_schema: str,
) -> dict[str, Any]:
    input_report_body, input_report = cross._load_json(input_report_path)
    outcome_report_body, outcome_report = cross._load_json(outcome_report_path)
    protocol_body, protocol, _, _ = cross._validate_source_reports(
        input_report=input_report,
        outcome_report=outcome_report,
        input_schema=input_schema,
        outcome_schema=outcome_schema,
    )
    if set(input_report.get("systems", {})) != set(SYSTEM_IDS) or set(
        outcome_report.get("systems", {})
    ) != set(SYSTEM_IDS):
        raise ValueError("counterfactual_action_response_system_set_invalid")
    return {
        "input_report_body": input_report_body,
        "input_report": input_report,
        "outcome_report_body": outcome_report_body,
        "outcome_report": outcome_report,
        "protocol_body": protocol_body,
        "protocol": protocol,
    }


def _load_system_window(
    *,
    system_id: str,
    bundle: Mapping[str, Any],
    parameters: ActionInnovationTransitionParameters,
) -> dict[str, Any]:
    target_inputs = bundle["input_report"]["systems"][system_id]
    target_outcomes = bundle["outcome_report"]["systems"][system_id]
    lock = bundle["protocol"]["systems"][system_id]
    if (
        cross._descriptor_identity(target_inputs["topology_report"])
        != cross._descriptor_identity(lock["topology_report"])
        or target_outcomes.get("system_id") != system_id
        or target_outcomes.get("site_id") != lock["outcome"]["site_id"]
        or (target_outcomes.get("quality") or {}).get("missing_values_imputed") is not False
    ):
        raise ValueError("counterfactual_action_response_system_identity_invalid")
    return cross._load_window(
        target_inputs=target_inputs,
        target_outcomes=target_outcomes,
        target_lock=lock,
        target_support=parameters.support,
    )


def _audit_window(
    *,
    window_name: str,
    system_id: str,
    window: Mapping[str, Any],
    parameters: ActionInnovationTransitionParameters,
    parameter_sha256: str,
) -> tuple[list[dict[str, object]], dict[str, object]]:
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
    first_issue_index = max(parameters.support.lag_hours) + 1
    rows: list[dict[str, object]] = []
    issue_count = 0
    skipped_missing = 0
    skipped_negative = 0
    baseline_step_count = 0
    baseline_clipped_step_count = 0
    scenario_step_count = 0
    scenario_clipped_step_count = 0
    action_step_count = 0
    action_floor_step_count = 0
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
        audit = audit_counterfactual_release_steps(
            parameters=parameters,
            state=state,
            inputs=inputs,
            issue_time=issue_time,
            release_deltas_m3s=DELTAS,
            horizons_hours=HORIZONS,
        )
        issue_count += 1
        baseline_step_count += len(audit.baseline_forecast.steps)
        baseline_clipped_step_count += sum(step.clipped for step in audit.baseline_forecast.steps)
        for scenario in audit.scenarios:
            scenario_step_count += len(scenario.forecast.steps)
            scenario_clipped_step_count += sum(step.clipped for step in scenario.forecast.steps)
            action_step_count += scenario.action_step_count
            action_floor_step_count += scenario.action_floor_step_count
        for response in audit.responses:
            target_time = issue_time + timedelta(hours=response.horizon_hours)
            rows.append(
                {
                    "system_id": system_id,
                    "window_id": window_name,
                    "issue_time_utc": cross._iso(issue_time),
                    "latest_observation_valid_at_utc": cross._iso(state_time),
                    "target_support_end_utc": cross._iso(target_time),
                    **response.as_dict(),
                    "future_outcome_observation_used": False,
                    "operational_vintages_verified": False,
                    "parameter_sha256": parameter_sha256,
                }
            )
    if not rows:
        raise ValueError("counterfactual_action_response_no_executable_rows")
    return rows, {
        "forecast_issue_count": issue_count,
        "response_row_count": len(rows),
        "skipped_missing_state_issue_count": skipped_missing,
        "skipped_negative_state_issue_count": skipped_negative,
        "baseline_step_count": baseline_step_count,
        "baseline_clipped_step_count": baseline_clipped_step_count,
        "scenario_step_count": scenario_step_count,
        "scenario_clipped_step_count": scenario_clipped_step_count,
        "action_step_count": action_step_count,
        "action_floor_step_count": action_floor_step_count,
        "first_issue_time_utc": rows[0]["issue_time_utc"],
        "last_issue_time_utc": rows[-1]["issue_time_utc"],
    }


def _summarize_window(
    rows: list[dict[str, object]], execution: Mapping[str, object]
) -> dict[str, Any]:
    metrics: dict[str, dict[str, Any]] = {}
    for delta in DELTAS:
        by_horizon: dict[str, Any] = {}
        for horizon in HORIZONS:
            selected = [
                row
                for row in rows
                if float(row["requested_release_delta_m3s"]) == delta
                and int(row["horizon_hours"]) == horizon
            ]
            ratios = [
                float(row["response_per_effective_release_unit"])
                for row in selected
                if row["response_per_effective_release_unit"] != ""
            ]
            effective = [
                row
                for row in selected
                if not math.isclose(
                    float(row["effective_release_delta_m3s"]),
                    0.0,
                    abs_tol=RESPONSE_TOLERANCE_M3S,
                )
            ]
            by_horizon[str(horizon)] = {
                "sample_count": len(selected),
                "effective_intervention_count": len(effective),
                "mean_discharge_response_m3s": sum(
                    float(row["discharge_response_m3s"]) for row in selected
                )
                / len(selected),
                "median_response_per_effective_release_unit": (
                    None if not ratios else median(ratios)
                ),
                "minimum_response_per_effective_release_unit": (
                    None if not ratios else min(ratios)
                ),
                "maximum_response_per_effective_release_unit": (
                    None if not ratios else max(ratios)
                ),
                "zero_response_before_lag_pass_count": sum(
                    bool(row["zero_response_before_lag_passed"]) for row in selected
                ),
                "signed_response_pass_count": sum(
                    bool(row["signed_response_passed"]) for row in selected
                ),
                "post_lag_response_collapse_count": sum(
                    bool(row["response_collapsed_after_lag"]) for row in selected
                ),
            }
        metrics[str(delta)] = by_horizon

    grouped: dict[tuple[str, int], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["issue_time_utc"]), int(row["horizon_hours"]))].append(row)
    monotonic_checks = 0
    monotonic_passes = 0
    for selected in grouped.values():
        baseline = float(selected[0]["baseline_discharge_m3s"])
        points = [(0.0, baseline)] + [
            (
                float(row["requested_release_delta_m3s"]),
                float(row["scenario_discharge_m3s"]),
            )
            for row in selected
        ]
        ordered = sorted(points)
        monotonic_checks += 1
        monotonic_passes += int(
            all(
                right[1] >= left[1] - RESPONSE_TOLERANCE_M3S
                for left, right in zip(ordered, ordered[1:], strict=False)
            )
        )

    prelag = [row for row in rows if bool(row["zero_response_required_before_lag"])]
    postlag_effective = [
        row
        for row in rows
        if not bool(row["zero_response_required_before_lag"])
        and not math.isclose(
            float(row["effective_release_delta_m3s"]),
            0.0,
            abs_tol=RESPONSE_TOLERANCE_M3S,
        )
    ]
    prelag_passed = all(bool(row["zero_response_before_lag_passed"]) for row in prelag)
    signed_passed = all(bool(row["signed_response_passed"]) for row in rows)
    monotonic_passed = monotonic_checks > 0 and monotonic_checks == monotonic_passes
    structural_passed = prelag_passed and signed_passed and monotonic_passed
    scenario_step_count = int(execution["scenario_step_count"])
    clipped_fraction = int(execution["scenario_clipped_step_count"]) / scenario_step_count
    collapse_count = sum(bool(row["response_collapsed_after_lag"]) for row in postlag_effective)
    collapse_fraction = collapse_count / len(postlag_effective)
    numerical_passed = (
        structural_passed
        and clipped_fraction <= MAXIMUM_CLIPPED_STEP_FRACTION
        and collapse_fraction <= MAXIMUM_POST_LAG_COLLAPSE_FRACTION
    )
    enriched_execution = {
        **execution,
        "baseline_clipped_step_fraction": int(execution["baseline_clipped_step_count"])
        / int(execution["baseline_step_count"]),
        "scenario_clipped_step_fraction": clipped_fraction,
        "action_floor_step_fraction": int(execution["action_floor_step_count"])
        / int(execution["action_step_count"]),
    }
    return {
        "system_id": rows[0]["system_id"],
        "window_id": rows[0]["window_id"],
        "execution": enriched_execution,
        "metrics_by_release_delta_and_horizon": metrics,
        "structural_gate": {
            "pre_lag_zero_response_check_count": len(prelag),
            "pre_lag_zero_response_gate_passed": prelag_passed,
            "signed_response_check_count": len(rows),
            "signed_response_gate_passed": signed_passed,
            "monotonicity_check_count": monotonic_checks,
            "monotonicity_pass_count": monotonic_passes,
            "monotonicity_gate_passed": monotonic_passed,
            "structural_response_gate_passed": structural_passed,
        },
        "numerical_usability_gate": {
            "post_lag_effective_response_count": len(postlag_effective),
            "post_lag_response_collapse_count": collapse_count,
            "post_lag_response_collapse_fraction": collapse_fraction,
            "scenario_clipped_step_fraction": clipped_fraction,
            "maximum_clipped_step_fraction": MAXIMUM_CLIPPED_STEP_FRACTION,
            "maximum_post_lag_response_collapse_fraction": (MAXIMUM_POST_LAG_COLLAPSE_FRACTION),
            "numerical_usability_gate_passed": numerical_passed,
        },
    }


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
    output_body, report = compile_counterfactual_action_response_posthoc(
        freeze_path=args.freeze,
        primary_input_report_path=args.primary_input_report,
        primary_outcome_report_path=args.primary_outcome_report,
        replication_input_report_path=args.replication_input_report,
        replication_outcome_report_path=args.replication_outcome_report,
        output_path=args.output,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output_body)
    args.report.write_bytes(_json_body(report))
    print(f"status={report['status']}")
    for name, window in report["windows"].items():
        structural = window["structural_gate"]["structural_response_gate_passed"]
        print(
            f"window={name} "
            f"structural={str(structural).lower()} "
            f"clipped_fraction="
            f"{window['execution']['scenario_clipped_step_fraction']:.6f} "
            f"collapse_fraction="
            f"{window['numerical_usability_gate']['post_lag_response_collapse_fraction']:.6f}"
        )
    print(
        "counterfactual_interface_promotion_gate_passed="
        f"{str(report['aggregate_gate']['counterfactual_interface_promotion_gate_passed']).lower()}"
    )


if __name__ == "__main__":
    main()
