#!/usr/bin/env python3
"""Fit and evaluate the bounded, non-stage Center Hill Geospatial Kernel MVP."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from data_agent.uwm.geospatial_kernel_v2.action_conditioned_transition import (
    CausalActionConditionedGeospatialKernel,
    GeographicResponseSupport,
    HourlyActionForcingSeries,
    OutletTransitionState,
    fit_action_conditioned_transition,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_OPERATOR_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/action_conditioned_transition.py"
)
EVALUATOR_PATH = Path(__file__).resolve()
DEFAULT_PANEL_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_672h_development_panel_report.json"
)
DEFAULT_TOPOLOGY_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_v2_d5_full_subnetwork_report.json"
)
DEFAULT_LEAD_TIME_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_lead_time_development_report.json"
)
DEFAULT_LAG_SUPPORT_GATES = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/stage32_lag_support_gates.json"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data/geotransport_v0_1/kernel_mvp"
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_mvp_development_report.json"
)

SCHEMA = "gwm.geotransport.geospatial_kernel_mvp_development.v1"
PANEL_SCHEMA = "gwm.geotransport.center_hill_672h_development_panel.v1"
TOPOLOGY_SCHEMA = "gwm.geotransport.center_hill_v2_d5_full_subnetwork.v1"
LEAD_TIME_SCHEMA = "gwm.geotransport.center_hill_lead_time_development.v1"
LAG_GATE_SCHEMA = "gwm.geotransport.stage32_lag_support_gates.v1"
HORIZONS = (1, 3, 6, 12)
CORE_HORIZONS = (3, 6, 12)
FIT_HOURS = 168
ACTIVATION_INDEX = FIT_HOURS + 1
PUBLICATION_LAG = timedelta(hours=1)
MAXIMUM_OBSERVATION_AGE = timedelta(hours=2)
MAXIMUM_DISCHARGE_M3S = 10_000.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-report", type=Path, default=DEFAULT_PANEL_REPORT)
    parser.add_argument("--topology-report", type=Path, default=DEFAULT_TOPOLOGY_REPORT)
    parser.add_argument("--lead-time-report", type=Path, default=DEFAULT_LEAD_TIME_REPORT)
    parser.add_argument("--lag-support-gates", type=Path, default=DEFAULT_LAG_SUPPORT_GATES)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_evaluation(
    *,
    panel_report_path: Path = DEFAULT_PANEL_REPORT,
    topology_report_path: Path = DEFAULT_TOPOLOGY_REPORT,
    lead_time_report_path: Path = DEFAULT_LEAD_TIME_REPORT,
    lag_support_gates_path: Path = DEFAULT_LAG_SUPPORT_GATES,
    parameter_output_path: Path | None = None,
    prediction_output_path: Path | None = None,
) -> tuple[bytes, bytes, dict[str, Any]]:
    parameter_output_path = parameter_output_path or DEFAULT_OUTPUT_ROOT / "parameters.json"
    prediction_output_path = prediction_output_path or DEFAULT_OUTPUT_ROOT / "predictions.csv"
    panel_report_body, panel_report = _load_json(panel_report_path)
    topology_report_body, topology_report = _load_json(topology_report_path)
    lead_report_body, lead_report = _load_json(lead_time_report_path)
    lag_gate_body, lag_gates = _load_json(lag_support_gates_path)
    _validate_parent_reports(panel_report, topology_report, lead_report, lag_gates)

    panel_body = _read_verified(panel_report["panel_artifact"])
    panel = _parse_panel(panel_body)
    network_body = _read_verified(topology_report["artifacts"]["full_subnetwork"])
    network = json.loads(network_body)["network"]
    lead_prediction_body = _read_verified(lead_report["outputs"]["predictions"])
    lead_rows = list(csv.DictReader(io.StringIO(lead_prediction_body.decode("utf-8"))))
    _validate_axes(panel, lead_rows)

    path = _action_to_outlet_path(network)
    lag_support = _candidate_lag_union(lag_gates)
    support = GeographicResponseSupport(
        network_id=str(network["network_id"]),
        action_entry_feature_id=int(path[0]),
        outlet_feature_id=int(path[-1]),
        path_feature_ids=path,
        lag_hours=lag_support,
        lag_weights=tuple(1.0 / len(lag_support) for _ in lag_support),
        provenance_id=(
            "center-hill:directed-full-subnetwork-path:"
            f"network={hashlib.sha256(network_body).hexdigest()}:"
            f"candidate-lag-union={hashlib.sha256(lag_gate_body).hexdigest()}"
        ),
        evidence_level="candidate",
        admitted=False,
    )
    inputs = HourlyActionForcingSeries(
        valid_times=tuple(row["support_end"] for row in panel),
        action_release_m3s=tuple(row["action"] for row in panel),
        nwm_lateral_inflow_m3s=tuple(row["forcing"] for row in panel),
        action_provenance_id=(
            f"center-hill:cwms-archive-action:{hashlib.sha256(panel_body).hexdigest()}"
        ),
        forcing_provenance_id=(
            f"center-hill:nwm-archive-q-lateral:{hashlib.sha256(panel_body).hexdigest()}"
        ),
        action_plan_vintage_verified=False,
        forcing_vintage_verified=False,
    )
    training = panel[:FIT_HOURS]
    if any(row["outcome"] is None for row in training):
        raise ValueError("kernel_mvp_training_outcomes_must_be_complete")
    fit = fit_action_conditioned_transition(
        support=support,
        observed_valid_times=tuple(row["support_end"] for row in training),
        observed_discharge_m3s=tuple(float(row["outcome"]) for row in training),
        inputs=inputs,
        maximum_discharge_m3s=MAXIMUM_DISCHARGE_M3S,
        provenance_id=(
            "center-hill:kernel-mvp:ols-fit:"
            f"panel={hashlib.sha256(panel_body).hexdigest()}:"
            "fixed-lag-weights=uniform"
        ),
    )
    parameter_body = _json_body(fit.parameters.as_dict())
    kernel = CausalActionConditionedGeospatialKernel(fit.parameters)

    panel_by_time = {row["support_end"]: row for row in panel}
    prediction_rows: list[dict[str, object]] = []
    clipped_step_count = 0
    unavailable_state_row_count = 0
    for source in lead_rows:
        horizon = int(source["horizon_hours"])
        if horizon not in HORIZONS:
            continue
        issue_time = _parse_utc(source["issue_time_utc"])
        target_time = _parse_utc(source["target_support_end_utc"])
        if target_time != issue_time + timedelta(hours=horizon):
            raise ValueError("kernel_mvp_lead_time_axis_invalid")
        try:
            state = _latest_causal_state(panel, issue_time)
        except ValueError as exc:
            if str(exc) != "kernel_mvp_causal_outlet_state_unavailable":
                raise
            unavailable_state_row_count += 1
            observed = panel_by_time[target_time]["outcome"]
            prediction_rows.append(
                {
                    "issue_time_utc": _iso(issue_time),
                    "target_support_end_utc": _iso(target_time),
                    "horizon_hours": horizon,
                    "observed_discharge_m3s": _optional(observed),
                    "kernel_mvp_m3s": "",
                    "no_future_action_m3s": "",
                    "no_future_forcing_m3s": "",
                    "causal_persistence_m3s": source["causal_latency_matched_persistence_m3s"],
                    "graph_manning_m3s": source["graph_multi_gauge_m3s"],
                    "local_manning_m3s": source["local_multi_gauge_m3s"],
                    "outlet_only_manning_m3s": source["outlet_only_m3s"],
                    "latest_observation_valid_at_utc": "",
                    "latest_observation_available_at_utc": "",
                    "issue_state_writeback_m3s": "",
                    "future_outcome_observation_used": False,
                    "future_action_archive_used": True,
                    "future_nwm_archive_forcing_used": True,
                }
            )
            continue
        targets = (target_time,)
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
        clipped_step_count += sum(value.clipped for value in candidate.steps)
        observed = panel_by_time[target_time]["outcome"]
        prediction_rows.append(
            {
                "issue_time_utc": _iso(issue_time),
                "target_support_end_utc": _iso(target_time),
                "horizon_hours": horizon,
                "observed_discharge_m3s": _optional(observed),
                "kernel_mvp_m3s": candidate.target_discharge_m3s[0],
                "no_future_action_m3s": no_action.target_discharge_m3s[0],
                "no_future_forcing_m3s": no_forcing.target_discharge_m3s[0],
                "causal_persistence_m3s": source["causal_latency_matched_persistence_m3s"],
                "graph_manning_m3s": source["graph_multi_gauge_m3s"],
                "local_manning_m3s": source["local_multi_gauge_m3s"],
                "outlet_only_manning_m3s": source["outlet_only_m3s"],
                "latest_observation_valid_at_utc": _iso(state.valid_at),
                "latest_observation_available_at_utc": _iso(state.available_at),
                "issue_state_writeback_m3s": candidate.issue_state.discharge_m3s,
                "future_outcome_observation_used": False,
                "future_action_archive_used": True,
                "future_nwm_archive_forcing_used": True,
            }
        )

    prediction_body = _encode_rows(prediction_rows)
    metrics, scoring = _score(prediction_rows)
    per_horizon = {
        str(horizon): {
            "candidate_beats_causal_persistence_rmse": (
                metrics[str(horizon)]["kernel_mvp"]["rmse_m3s"]
                < metrics[str(horizon)]["causal_persistence"]["rmse_m3s"]
            ),
            "candidate_beats_graph_manning_rmse": (
                metrics[str(horizon)]["kernel_mvp"]["rmse_m3s"]
                < metrics[str(horizon)]["graph_manning"]["rmse_m3s"]
            ),
            "candidate_beats_local_manning_rmse": (
                metrics[str(horizon)]["kernel_mvp"]["rmse_m3s"]
                < metrics[str(horizon)]["local_manning"]["rmse_m3s"]
            ),
            "candidate_beats_no_forcing_rmse": (
                metrics[str(horizon)]["kernel_mvp"]["rmse_m3s"]
                < metrics[str(horizon)]["no_future_forcing"]["rmse_m3s"]
            ),
            "action_effect_expected_at_horizon": horizon >= min(lag_support),
            "candidate_beats_no_action_rmse": (
                metrics[str(horizon)]["kernel_mvp"]["rmse_m3s"]
                < metrics[str(horizon)]["no_future_action"]["rmse_m3s"]
            ),
        }
        for horizon in HORIZONS
    }
    for gates in per_horizon.values():
        comparison_values = [
            gates["candidate_beats_causal_persistence_rmse"],
            gates["candidate_beats_graph_manning_rmse"],
            gates["candidate_beats_local_manning_rmse"],
            gates["candidate_beats_no_forcing_rmse"],
        ]
        if gates["action_effect_expected_at_horizon"]:
            comparison_values.append(gates["candidate_beats_no_action_rmse"])
        gates["accuracy_gate_passed"] = all(comparison_values)

    core_accuracy_passed = all(
        per_horizon[str(horizon)]["accuracy_gate_passed"] for horizon in CORE_HORIZONS
    )
    all_horizons_passed = all(
        per_horizon[str(horizon)]["accuracy_gate_passed"] for horizon in HORIZONS
    )
    executable_rows = [row for row in prediction_rows if row["kernel_mvp_m3s"] not in (None, "")]
    state_writeback_passed = bool(executable_rows) and all(
        row["issue_state_writeback_m3s"] not in (None, "")
        and np.isfinite(float(row["issue_state_writeback_m3s"]))
        for row in executable_rows
    )
    structural_passed = (
        fit.design_rank == 4
        and fit.parameters.autoregressive_coefficient < 1.0
        and fit.parameters.action_coefficient >= 0.0
        and fit.parameters.forcing_coefficient >= 0.0
        and clipped_step_count == 0
        and state_writeback_passed
    )
    development_gate = core_accuracy_passed and structural_passed
    report = {
        "schema": SCHEMA,
        "status": (
            "kernel_mvp_development_gate_passed_not_validated"
            if development_gate
            else "kernel_mvp_development_gate_failed"
        ),
        "generated_at": datetime.now(UTC).isoformat(),
        "source_artifacts": {
            "development_panel_report": _artifact(panel_report_path, panel_report_body),
            "development_panel": panel_report["panel_artifact"],
            "full_subnetwork_report": _artifact(topology_report_path, topology_report_body),
            "full_subnetwork": topology_report["artifacts"]["full_subnetwork"],
            "lead_time_development_report": _artifact(lead_time_report_path, lead_report_body),
            "lead_time_predictions": lead_report["outputs"]["predictions"],
            "candidate_lag_support_gates": _artifact(lag_support_gates_path, lag_gate_body),
        },
        "implementation_artifacts": {
            "core_operator": _artifact(CORE_OPERATOR_PATH, CORE_OPERATOR_PATH.read_bytes()),
            "evaluator": _artifact(EVALUATOR_PATH, EVALUATOR_PATH.read_bytes()),
        },
        "outputs": {
            "parameters": _artifact(parameter_output_path, parameter_body),
            "predictions": _artifact(prediction_output_path, prediction_body),
        },
        "kernel": {
            "role": "action_conditioned_predictive_closure_over_conservative_graph",
            "fit": fit.as_dict(),
            "geographic_path_feature_count": len(path),
            "candidate_lag_support_hours": list(lag_support),
            "lag_weights": list(support.lag_weights),
            "lag_weights_selected_from_evaluation_outcomes": False,
            "free_parameter_count": 4,
            "state_writeback_implemented": True,
            "mass_conserving_network_routing_replacement": False,
        },
        "window": {
            "training_row_count": FIT_HOURS,
            "training_start_utc": _iso(training[0]["support_end"]),
            "training_end_utc": _iso(training[-1]["support_end"]),
            "first_issue_time_utc": min(row["issue_time_utc"] for row in prediction_rows),
            "horizons_hours": list(HORIZONS),
            "core_horizons_hours": list(CORE_HORIZONS),
        },
        "metrics_by_horizon": metrics,
        "scoring": scoring,
        "registered_hard_gate": {
            "per_horizon": per_horizon,
            "all_core_horizons_accuracy_gate_passed": core_accuracy_passed,
            "all_horizons_accuracy_gate_passed": all_horizons_passed,
            "stable_nonnegative_transition_gate_passed": structural_passed,
            "state_writeback_gate_passed": state_writeback_passed,
            "causal_state_unavailable_row_count": unavailable_state_row_count,
            "executable_prediction_row_count": len(executable_rows),
            "clipped_candidate_step_count": clipped_step_count,
            "development_gate_passed": development_gate,
        },
        "baseline_roles": {
            "causal_persistence": "latest issue-time-available outlet observation",
            "no_future_action": "same state and forcing with post-issue action set to zero",
            "no_future_forcing": "same state and action with post-issue NWM forcing set to zero",
            "graph_manning": "existing 435-reach conservative graph replay with graph observer",
            "local_manning": "existing 435-reach conservative graph replay with local observer",
            "professional_router_same_window": (
                "not_available; t-route MC evidence exists on a different linear holdout and "
                "is not relabelled as an apples-to-apples baseline"
            ),
        },
        "information_boundary": {
            "future_outlet_observations_used": False,
            "outlet_target_passed_to_kernel": False,
            "future_realized_action_archive_used": True,
            "future_retrospective_nwm_forcing_used": True,
            "action_plan_vintage_verified": False,
            "forcing_forecast_vintage_verified": False,
            "operational_forecast_claim_permitted": False,
        },
        "data_isolation": {
            "model_fit_uses_first_168_public_development_hours_only": True,
            "scoring_targets_used_for_fit": False,
            "new_target_data_acquired": False,
            "stage45_usgs_requests_executed": False,
            "untouched_blind_window_consumed": False,
        },
        "claim_boundary": {
            "kernel_mvp_implemented": True,
            "kernel_mvp_development_gate_passed": development_gate,
            "single_system_public_development_evidence_only": True,
            "geospatial_kernel_validated": False,
            "operational_forecast_validated": False,
            "universal_lag_admitted": False,
            "mass_conserving_graph_operator_retained": True,
            "action_conditioned_closure_admitted_as_default": False,
        },
    }
    return parameter_body, prediction_body, report


def _validate_parent_reports(
    panel: Mapping[str, Any],
    topology: Mapping[str, Any],
    lead: Mapping[str, Any],
    lag_gates: Mapping[str, Any],
) -> None:
    if panel.get("schema") != PANEL_SCHEMA:
        raise ValueError("kernel_mvp_panel_report_schema_invalid")
    if topology.get("schema") != TOPOLOGY_SCHEMA:
        raise ValueError("kernel_mvp_topology_report_schema_invalid")
    if lead.get("schema") != LEAD_TIME_SCHEMA:
        raise ValueError("kernel_mvp_lead_time_report_schema_invalid")
    if (
        lag_gates.get("schema") != LAG_GATE_SCHEMA
        or lag_gates.get("all_gates_passed") is not True
        or lag_gates.get("decision", {}).get("common_empirical_support_admitted") is not False
    ):
        raise ValueError("kernel_mvp_lag_support_gate_invalid")


def _parse_panel(body: bytes) -> list[dict[str, Any]]:
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
    parsed: list[dict[str, Any]] = []
    for row in rows:
        parsed.append(
            {
                "support_end": _parse_utc(row["support_end_utc"]),
                "action": float(row["action_release_m3s"]),
                "forcing": float(row["nwm_q_lateral_active_reach_sum_m3s"]),
                "outcome": (
                    None
                    if not row["outcome_discharge_interval_sample_mean_m3s"]
                    else float(row["outcome_discharge_interval_sample_mean_m3s"])
                ),
            }
        )
    return parsed


def _validate_axes(panel: list[dict[str, Any]], lead_rows: list[Mapping[str, str]]) -> None:
    if (
        len(panel) != 672
        or any(
            second["support_end"] - first["support_end"] != timedelta(hours=1)
            for first, second in zip(panel, panel[1:], strict=False)
        )
        or len(lead_rows) != 2_400
    ):
        raise ValueError("kernel_mvp_source_axis_invalid")
    horizons = {int(row["horizon_hours"]) for row in lead_rows}
    if not set(HORIZONS).issubset(horizons):
        raise ValueError("kernel_mvp_required_horizons_missing")


def _action_to_outlet_path(network: Mapping[str, Any]) -> tuple[int, ...]:
    feature_ids = tuple(int(value) for value in network["feature_ids"])
    downstream = tuple(
        None if value is None else int(value) for value in network["downstream_feature_ids"]
    )
    if len(feature_ids) != len(downstream):
        raise ValueError("kernel_mvp_network_axis_invalid")
    next_feature = dict(zip(feature_ids, downstream, strict=True))
    action_entries = tuple(int(value) for value in network["action_entry_feature_ids"])
    if len(action_entries) != 1:
        raise ValueError("kernel_mvp_requires_one_action_entry")
    cursor: int | None = action_entries[0]
    path: list[int] = []
    while cursor is not None:
        if cursor in path or cursor not in next_feature:
            raise ValueError("kernel_mvp_action_path_invalid")
        path.append(cursor)
        cursor = next_feature[cursor]
    if len(path) < 2:
        raise ValueError("kernel_mvp_action_path_too_short")
    return tuple(path)


def _candidate_lag_union(lag_gates: Mapping[str, Any]) -> tuple[int, ...]:
    values = {
        int(lag)
        for event in lag_gates["event_summary"]
        if event.get("response_detectable") is True
        for lag in event["supported_lags_hours"]
    }
    result = tuple(sorted(values))
    if result != (5, 6, 7):
        raise ValueError("kernel_mvp_candidate_lag_union_changed")
    return result


def _latest_causal_state(
    panel: list[dict[str, Any]], issue_time: datetime
) -> OutletTransitionState:
    for row in reversed(panel):
        valid_at = row["support_end"]
        available_at = valid_at + PUBLICATION_LAG
        if available_at > issue_time or row["outcome"] is None:
            continue
        if issue_time - valid_at > MAXIMUM_OBSERVATION_AGE:
            break
        return OutletTransitionState(
            valid_at=valid_at,
            available_at=available_at,
            discharge_m3s=float(row["outcome"]),
            provenance_id=f"USGS-03424860:00060:archive:{_iso(valid_at)}",
            evidence_level="candidate",
            observed=True,
        )
    raise ValueError("kernel_mvp_causal_outlet_state_unavailable")


def _score(
    rows: list[dict[str, object]],
) -> tuple[dict[str, dict[str, dict[str, float]]], dict[str, Any]]:
    names = (
        "kernel_mvp",
        "no_future_action",
        "no_future_forcing",
        "causal_persistence",
        "graph_manning",
        "local_manning",
        "outlet_only_manning",
    )
    metrics: dict[str, dict[str, dict[str, float]]] = {}
    counts: dict[str, int] = {}
    omitted: dict[str, list[str]] = {}
    for horizon in HORIZONS:
        selected = [row for row in rows if row["horizon_hours"] == horizon]
        complete: list[dict[str, object]] = []
        missing: list[str] = []
        for row in selected:
            required = [row["observed_discharge_m3s"]]
            required.extend(row[f"{name}_m3s"] for name in names)
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
                np.asarray([float(row[f"{name}_m3s"]) for row in complete], dtype=float),
            )
            for name in names
        }
        counts[str(horizon)] = len(complete)
        omitted[str(horizon)] = missing
    return metrics, {
        "common_complete_case_count_by_horizon": counts,
        "omitted_target_times_by_horizon": omitted,
        "missing_values_imputed": False,
        "comparison_uses_identical_rows_within_each_horizon": True,
    }


def _metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    if not observed.size or observed.shape != predicted.shape:
        raise ValueError("kernel_mvp_metric_axis_invalid")
    error = predicted - observed
    denominator = float(np.sum((observed - observed.mean()) ** 2))
    return {
        "sample_count": int(observed.size),
        "rmse_m3s": float(np.sqrt(np.mean(error**2))),
        "mae_m3s": float(np.mean(np.abs(error))),
        "bias_m3s": float(np.mean(error)),
        "nse": float(1.0 - np.sum(error**2) / denominator),
    }


def _encode_rows(rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    return body, json.loads(body)


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != descriptor.get("sha256") or len(body) != descriptor.get(
        "size_bytes"
    ):
        raise ValueError("kernel_mvp_artifact_identity_mismatch")
    return body


def _artifact(path: Path, body: bytes) -> dict[str, object]:
    resolved = path.resolve()
    try:
        display_path = str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        display_path = str(resolved)
    return {
        "path": display_path,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _json_body(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("kernel_mvp_utc_time_required")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _optional(value: object) -> object:
    return "" if value is None else value


def main() -> None:
    args = parse_args()
    parameter_path = args.output_root / "parameters.json"
    prediction_path = args.output_root / "predictions.csv"
    parameter_body, prediction_body, report = compile_evaluation(
        panel_report_path=args.panel_report,
        topology_report_path=args.topology_report,
        lead_time_report_path=args.lead_time_report,
        lag_support_gates_path=args.lag_support_gates,
        parameter_output_path=parameter_path,
        prediction_output_path=prediction_path,
    )
    args.output_root.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    parameter_path.write_bytes(parameter_body)
    prediction_path.write_bytes(prediction_body)
    args.report.write_bytes(_json_body(report))
    gate = report["registered_hard_gate"]["development_gate_passed"]
    print(f"kernel_mvp_development_gate_passed={str(gate).lower()}")
    for horizon in HORIZONS:
        metrics = report["metrics_by_horizon"][str(horizon)]
        print(
            f"horizon={horizon}h "
            f"kernel_rmse={metrics['kernel_mvp']['rmse_m3s']:.6f} "
            f"persistence_rmse={metrics['causal_persistence']['rmse_m3s']:.6f} "
            f"graph_rmse={metrics['graph_manning']['rmse_m3s']:.6f}"
        )


if __name__ == "__main__":
    main()
