#!/usr/bin/env python3
"""Evaluate unchanged Geospatial Kernel MVP parameters on public later windows."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from data_agent.uwm.geospatial_kernel_v2.action_conditioned_transition import (
    ActionConditionedTransitionParameters,
    CausalActionConditionedGeospatialKernel,
    HourlyActionForcingSeries,
    OutletTransitionState,
    action_conditioned_transition_parameters_from_dict,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = Path(__file__).resolve()
DEFAULT_PARAMETERS = REPO_ROOT / "data/geotransport_v0_1/kernel_mvp/parameters.json"
DEFAULT_DEVELOPMENT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_mvp_development_report.json"
)
DEFAULT_TEMPORAL_PANEL_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_temporal_holdout_panel_report.json"
)
DEFAULT_D3_ACTION_MANIFEST = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d3_inputs/action/acquisition_manifest.json"
)
DEFAULT_D3_NWM_MANIFEST = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d3_inputs/nwm/acquisition_manifest.json"
)
DEFAULT_D3_OUTCOME_MANIFEST = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_v2_d3_inputs/outcome/acquisition_manifest.json"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data/geotransport_v0_1/kernel_mvp/temporal_transfer"
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_mvp_temporal_transfer_report.json"
)

SCHEMA = "gwm.geotransport.geospatial_kernel_mvp_temporal_transfer.v1"
DEVELOPMENT_SCHEMA = "gwm.geotransport.geospatial_kernel_mvp_development.v1"
TEMPORAL_PANEL_SCHEMA = "gwm.geotransport.center_hill_temporal_holdout_panel.v1"
D3_ACTION_SCHEMA = "gwm.geotransport.center_hill_v2_action_input.v1"
D3_NWM_SCHEMA = "gwm.geotransport.center_hill_v2_nwm_input.v1"
D3_OUTCOME_SCHEMA = "gwm.geotransport.center_hill_v2_outcome_input.v1"
D3_PROTOCOL_SCHEMA = "gwm.geotransport.center_hill_v2_d3_protocol.v1"
HORIZONS = (1, 3, 6, 12)
ACTION_EFFECT_HORIZONS = (6, 12)
HOUR_COUNT = 672
TEMPORAL_WARMUP_HOURS = 168


@dataclass(frozen=True)
class TransferWindow:
    window_id: str
    role: str
    valid_times: tuple[datetime, ...]
    action_release_m3s: tuple[float, ...]
    nwm_lateral_inflow_m3s: tuple[float, ...]
    observed_discharge_m3s: tuple[float, ...]
    first_issue_index: int
    target_end_index_exclusive: int
    action_provenance_id: str
    forcing_provenance_id: str
    outcome_provenance_id: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parameters", type=Path, default=DEFAULT_PARAMETERS)
    parser.add_argument("--development-report", type=Path, default=DEFAULT_DEVELOPMENT_REPORT)
    parser.add_argument("--temporal-panel-report", type=Path, default=DEFAULT_TEMPORAL_PANEL_REPORT)
    parser.add_argument("--d3-action-manifest", type=Path, default=DEFAULT_D3_ACTION_MANIFEST)
    parser.add_argument("--d3-nwm-manifest", type=Path, default=DEFAULT_D3_NWM_MANIFEST)
    parser.add_argument("--d3-outcome-manifest", type=Path, default=DEFAULT_D3_OUTCOME_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_temporal_transfer(
    *,
    parameter_path: Path = DEFAULT_PARAMETERS,
    development_report_path: Path = DEFAULT_DEVELOPMENT_REPORT,
    temporal_panel_report_path: Path = DEFAULT_TEMPORAL_PANEL_REPORT,
    d3_action_manifest_path: Path = DEFAULT_D3_ACTION_MANIFEST,
    d3_nwm_manifest_path: Path = DEFAULT_D3_NWM_MANIFEST,
    d3_outcome_manifest_path: Path = DEFAULT_D3_OUTCOME_MANIFEST,
    january_prediction_path: Path | None = None,
    d3_prediction_path: Path | None = None,
) -> tuple[bytes, bytes, dict[str, Any]]:
    january_prediction_path = january_prediction_path or (
        DEFAULT_OUTPUT_ROOT / "january_temporal_holdout_predictions.csv"
    )
    d3_prediction_path = d3_prediction_path or (DEFAULT_OUTPUT_ROOT / "february_d3_predictions.csv")
    parameter_body, parameter_document = _load_json(parameter_path)
    development_body, development = _load_json(development_report_path)
    parameter_descriptor = _validate_parameter_lineage(
        development=development,
        parameter_path=parameter_path,
        parameter_body=parameter_body,
    )
    parameters = action_conditioned_transition_parameters_from_dict(parameter_document)
    parameter_hash = hashlib.sha256(parameter_body).hexdigest()

    temporal_report_body, temporal_report = _load_json(temporal_panel_report_path)
    january_window, january_sources = _load_january_window(
        temporal_panel_report_path,
        temporal_report_body,
        temporal_report,
    )
    action_manifest_body, action_manifest = _load_json(d3_action_manifest_path)
    nwm_manifest_body, nwm_manifest = _load_json(d3_nwm_manifest_path)
    outcome_manifest_body, outcome_manifest = _load_json(d3_outcome_manifest_path)
    d3_window, d3_sources = _load_d3_window(
        action_manifest_path=d3_action_manifest_path,
        action_manifest_body=action_manifest_body,
        action_manifest=action_manifest,
        nwm_manifest_path=d3_nwm_manifest_path,
        nwm_manifest_body=nwm_manifest_body,
        nwm_manifest=nwm_manifest,
        outcome_manifest_path=d3_outcome_manifest_path,
        outcome_manifest_body=outcome_manifest_body,
        outcome_manifest=outcome_manifest,
        expected_feature_ids=parameters.support.path_feature_ids,
        first_issue_index=max(parameters.support.lag_hours),
    )

    window_outputs: dict[str, dict[str, Any]] = {}
    prediction_bodies: dict[str, bytes] = {}
    for window, output_path in (
        (january_window, january_prediction_path),
        (d3_window, d3_prediction_path),
    ):
        rows, clipped_step_count = _evaluate_window(window, parameters, parameter_hash)
        body = _encode_rows(rows)
        metrics, scoring = _score(rows)
        gates = _window_gates(
            rows=rows,
            metrics=metrics,
            clipped_step_count=clipped_step_count,
            parameter_hash=parameter_hash,
            expected_parameter_hash=str(parameter_descriptor["sha256"]),
        )
        prediction_bodies[window.window_id] = body
        window_outputs[window.window_id] = {
            "role": window.role,
            "window": {
                "input_start_utc": _iso(window.valid_times[0]),
                "input_end_utc": _iso(window.valid_times[-1]),
                "first_issue_time_utc": _iso(window.valid_times[window.first_issue_index]),
                "last_scored_target_utc": _iso(
                    window.valid_times[window.target_end_index_exclusive - 1]
                ),
                "input_hour_count": len(window.valid_times),
                "first_issue_index": window.first_issue_index,
                "terminal_input_reserved_as_next_window_boundary": (
                    window.target_end_index_exclusive < len(window.valid_times)
                ),
                "horizons_hours": list(HORIZONS),
            },
            "source_artifacts": january_sources if window is january_window else d3_sources,
            "predictions": _artifact(output_path, body),
            "metrics_by_horizon": metrics,
            "scoring": scoring,
            "diagnostic_hard_gate": gates,
        }

    all_windows_passed = all(
        value["diagnostic_hard_gate"]["window_transfer_gate_passed"]
        for value in window_outputs.values()
    )
    january_body = prediction_bodies[january_window.window_id]
    d3_body = prediction_bodies[d3_window.window_id]
    report = {
        "schema": SCHEMA,
        "status": (
            "fixed_parameter_temporal_transfer_passed_not_validated"
            if all_windows_passed
            else "fixed_parameter_temporal_transfer_failed"
        ),
        "generated_at": datetime.now(UTC).isoformat(),
        "evaluation_role": "previously_public_posthoc_fixed_parameter_temporal_transfer",
        "source_artifacts": {
            "development_report": _artifact(development_report_path, development_body),
            "unchanged_parameters": _artifact(parameter_path, parameter_body),
        },
        "implementation_artifact": _artifact(EVALUATOR_PATH, EVALUATOR_PATH.read_bytes()),
        "parameter_lock": {
            "loaded_parameter_sha256": parameter_hash,
            "development_parameter_sha256": parameter_descriptor["sha256"],
            "hash_unchanged": parameter_hash == parameter_descriptor["sha256"],
            "parameter_refit_performed": False,
            "parameter_selection_or_revision_from_transfer_outcomes": False,
            "free_parameter_count": 4,
        },
        "gate_policy": {
            "aggregation": "non_compensatory_all_required_checks_and_windows_must_pass",
            "all_horizons_must_beat_causal_persistence": list(HORIZONS),
            "horizons_that_must_beat_no_future_action": list(ACTION_EFFECT_HORIZONS),
            "all_horizons_must_beat_no_future_forcing": list(HORIZONS),
            "gate_was_prospectively_registered_before_source_outcome_access": False,
            "gate_changed_after_metric_computation": False,
        },
        "windows": window_outputs,
        "aggregate_gate": {
            "all_windows_transfer_gate_passed": all_windows_passed,
            "geospatial_kernel_temporal_transfer_gate_passed": all_windows_passed,
        },
        "information_boundary": {
            "future_outlet_observations_used_by_kernel": False,
            "latest_outlet_state_is_one_hour_old_at_issue": True,
            "future_realized_action_archive_used": True,
            "future_retrospective_nwm_forcing_used": True,
            "action_plan_vintage_verified": False,
            "forcing_forecast_vintage_verified": False,
            "archive_oracle_scenario_replay": True,
            "operational_forecast_claim_permitted": False,
        },
        "data_isolation": {
            "new_target_data_acquired": False,
            "stage45_usgs_requests_executed": False,
            "existing_public_windows_only": True,
            "untouched_blind_window_consumed": False,
        },
        "claim_boundary": {
            "fixed_parameter_temporal_transfer_passed": all_windows_passed,
            "action_conditioned_mechanism_remains_development_candidate": True,
            "action_conditioned_closure_admitted_as_default": False,
            "geospatial_kernel_validated": False,
            "operational_forecast_validated": False,
            "mass_conserving_graph_operator_replaced": False,
        },
    }
    return january_body, d3_body, report


def _validate_parameter_lineage(
    *, development: Mapping[str, Any], parameter_path: Path, parameter_body: bytes
) -> Mapping[str, Any]:
    if (
        development.get("schema") != DEVELOPMENT_SCHEMA
        or (development.get("claim_boundary") or {}).get("geospatial_kernel_validated") is not False
    ):
        raise ValueError("kernel_mvp_transfer_development_report_invalid")
    descriptor = (development.get("outputs") or {}).get("parameters")
    if not isinstance(descriptor, Mapping) or descriptor != _artifact(
        parameter_path, parameter_body
    ):
        raise ValueError("kernel_mvp_transfer_parameter_lineage_mismatch")
    return descriptor


def _load_january_window(
    report_path: Path, report_body: bytes, report: Mapping[str, Any]
) -> tuple[TransferWindow, dict[str, object]]:
    if report.get("schema") != TEMPORAL_PANEL_SCHEMA:
        raise ValueError("kernel_mvp_transfer_temporal_panel_report_invalid")
    descriptor = report.get("panel_artifact")
    if not isinstance(descriptor, Mapping):
        raise ValueError("kernel_mvp_transfer_temporal_panel_artifact_missing")
    panel_body = _read_verified(descriptor)
    rows = list(csv.DictReader(io.StringIO(panel_body.decode("utf-8"))))
    if len(rows) != HOUR_COUNT or any(
        row["split_role"]
        != ("evaluation_warmup" if index < TEMPORAL_WARMUP_HOURS else "evaluation")
        for index, row in enumerate(rows)
    ):
        raise ValueError("kernel_mvp_transfer_temporal_panel_axis_invalid")
    times = tuple(_parse_utc(row["support_end_utc"]) for row in rows)
    _require_hourly(times, "temporal_panel")
    action = tuple(
        _finite_nonnegative(row["action_release_m3s"], "temporal_action") for row in rows
    )
    forcing = tuple(
        _finite_nonnegative(row["nwm_q_lateral_active_reach_sum_m3s"], "temporal_forcing")
        for row in rows
    )
    observed = tuple(
        _finite_nonnegative(row["outcome_discharge_interval_sample_mean_m3s"], "temporal_outcome")
        for row in rows
    )
    body_hash = hashlib.sha256(panel_body).hexdigest()
    return (
        TransferWindow(
            window_id="january_temporal_holdout",
            role="previously_scored_external_temporal_holdout_posthoc_for_mvp",
            valid_times=times,
            action_release_m3s=action,
            nwm_lateral_inflow_m3s=forcing,
            observed_discharge_m3s=observed,
            first_issue_index=TEMPORAL_WARMUP_HOURS,
            # The terminal observation is the D3 prior state, not a second window target.
            target_end_index_exclusive=HOUR_COUNT - 1,
            action_provenance_id=f"center-hill:temporal-panel:action:{body_hash}",
            forcing_provenance_id=f"center-hill:temporal-panel:nwm-q-lateral:{body_hash}",
            outcome_provenance_id=f"USGS-03424860:00060:temporal-panel:{body_hash}",
        ),
        {
            "panel_report": _artifact(report_path, report_body),
            "panel": dict(descriptor),
        },
    )


def _load_d3_window(
    *,
    action_manifest_path: Path,
    action_manifest_body: bytes,
    action_manifest: Mapping[str, Any],
    nwm_manifest_path: Path,
    nwm_manifest_body: bytes,
    nwm_manifest: Mapping[str, Any],
    outcome_manifest_path: Path,
    outcome_manifest_body: bytes,
    outcome_manifest: Mapping[str, Any],
    expected_feature_ids: tuple[int, ...],
    first_issue_index: int,
) -> tuple[TransferWindow, dict[str, object]]:
    if (
        action_manifest.get("schema") != D3_ACTION_SCHEMA
        or nwm_manifest.get("schema") != D3_NWM_SCHEMA
        or outcome_manifest.get("schema") != D3_OUTCOME_SCHEMA
    ):
        raise ValueError("kernel_mvp_transfer_d3_manifest_schema_invalid")
    protocol_descriptors = {
        json.dumps(value.get("protocol"), sort_keys=True)
        for value in (action_manifest, nwm_manifest, outcome_manifest)
    }
    if len(protocol_descriptors) != 1:
        raise ValueError("kernel_mvp_transfer_d3_protocol_identity_mismatch")
    protocol_descriptor = action_manifest.get("protocol")
    if not isinstance(protocol_descriptor, Mapping):
        raise ValueError("kernel_mvp_transfer_d3_protocol_artifact_missing")
    protocol_body = _read_verified(protocol_descriptor)
    protocol = json.loads(protocol_body)
    if (
        not isinstance(protocol, Mapping)
        or protocol.get("schema") != D3_PROTOCOL_SCHEMA
        or protocol.get("status") != "frozen_before_d3_value_access"
    ):
        raise ValueError("kernel_mvp_transfer_d3_protocol_invalid")
    if (
        tuple(int(value) for value in nwm_manifest.get("feature_ids", ())) != expected_feature_ids
        or nwm_manifest.get("ground_truth") is not False
        or (outcome_manifest.get("quality") or {}).get("missing_values_imputed") is not False
    ):
        raise ValueError("kernel_mvp_transfer_d3_input_contract_invalid")

    action_descriptor = action_manifest.get("action_values")
    forcing_descriptor = nwm_manifest.get("q_lateral_values")
    outcome_descriptor = outcome_manifest.get("outcome_values")
    if not all(
        isinstance(value, Mapping)
        for value in (action_descriptor, forcing_descriptor, outcome_descriptor)
    ):
        raise ValueError("kernel_mvp_transfer_d3_value_artifact_missing")
    action_body = _read_verified(action_descriptor)
    forcing_body = _read_verified(forcing_descriptor)
    outcome_body = _read_verified(outcome_descriptor)
    action_rows = list(csv.DictReader(io.StringIO(action_body.decode("utf-8"))))
    forcing_rows = list(csv.DictReader(io.StringIO(forcing_body.decode("utf-8"))))
    outcome_rows = list(csv.DictReader(io.StringIO(outcome_body.decode("utf-8"))))
    if len(action_rows) != HOUR_COUNT or len(outcome_rows) != HOUR_COUNT:
        raise ValueError("kernel_mvp_transfer_d3_hour_count_invalid")

    times = tuple(_parse_utc(row["support_end_utc"]) for row in action_rows)
    outcome_times = tuple(_parse_utc(row["support_end_utc"]) for row in outcome_rows)
    _require_hourly(times, "d3_action")
    if outcome_times != times:
        raise ValueError("kernel_mvp_transfer_d3_outcome_axis_mismatch")
    action = tuple(
        _finite_nonnegative(row["action_release_m3s"], "d3_action") for row in action_rows
    )
    observed = tuple(
        _finite_nonnegative(row["observed_discharge_m3s"], "d3_outcome") for row in outcome_rows
    )

    forcing_by_time: dict[datetime, dict[int, float]] = {}
    for row in forcing_rows:
        # NWM timestamps mark interval starts; the transition consumes the interval-end sum.
        valid_at = _parse_utc(row["timestamp_utc"]) + timedelta(hours=1)
        feature_id = int(row["feature_id"])
        by_feature = forcing_by_time.setdefault(valid_at, {})
        if feature_id in by_feature:
            raise ValueError("kernel_mvp_transfer_d3_forcing_duplicate")
        by_feature[feature_id] = _finite_nonnegative(row["q_lateral_m3s"], "d3_forcing")
    if tuple(sorted(forcing_by_time)) != times:
        raise ValueError("kernel_mvp_transfer_d3_forcing_time_axis_mismatch")
    expected_features = set(expected_feature_ids)
    if any(set(values) != expected_features for values in forcing_by_time.values()):
        raise ValueError("kernel_mvp_transfer_d3_forcing_feature_axis_mismatch")
    forcing = tuple(sum(forcing_by_time[valid_at].values()) for valid_at in times)

    prior_time = _parse_utc(str(outcome_manifest["prior_observation_support_end_utc"]))
    prior = _finite_nonnegative(outcome_manifest["prior_observation_m3s"], "d3_prior_observation")
    if prior_time + timedelta(hours=1) != times[0] or not math.isfinite(prior):
        raise ValueError("kernel_mvp_transfer_d3_prior_observation_invalid")
    return (
        TransferWindow(
            window_id="february_d3",
            role="previously_scored_independent_d3_window_posthoc_for_mvp",
            valid_times=times,
            action_release_m3s=action,
            nwm_lateral_inflow_m3s=forcing,
            observed_discharge_m3s=observed,
            first_issue_index=first_issue_index,
            target_end_index_exclusive=HOUR_COUNT,
            action_provenance_id=(
                f"center-hill:d3-action:{hashlib.sha256(action_body).hexdigest()}"
            ),
            forcing_provenance_id=(
                f"center-hill:d3-nwm-q-lateral:{hashlib.sha256(forcing_body).hexdigest()}"
            ),
            outcome_provenance_id=(
                f"USGS-03424860:00060:d3:{hashlib.sha256(outcome_body).hexdigest()}"
            ),
        ),
        {
            "frozen_protocol": dict(protocol_descriptor),
            "action_manifest": _artifact(action_manifest_path, action_manifest_body),
            "action_values": dict(action_descriptor),
            "nwm_manifest": _artifact(nwm_manifest_path, nwm_manifest_body),
            "q_lateral_values": dict(forcing_descriptor),
            "outcome_manifest": _artifact(outcome_manifest_path, outcome_manifest_body),
            "outcome_values": dict(outcome_descriptor),
            "prior_observation": {
                "support_end_utc": _iso(prior_time),
                "discharge_m3s": prior,
                "used_as_scored_future_input": False,
            },
        },
    )


def _evaluate_window(
    window: TransferWindow,
    parameters: ActionConditionedTransitionParameters,
    parameter_hash: str,
) -> tuple[list[dict[str, object]], int]:
    inputs = HourlyActionForcingSeries(
        valid_times=window.valid_times,
        action_release_m3s=window.action_release_m3s,
        nwm_lateral_inflow_m3s=window.nwm_lateral_inflow_m3s,
        action_provenance_id=window.action_provenance_id,
        forcing_provenance_id=window.forcing_provenance_id,
        action_plan_vintage_verified=False,
        forcing_vintage_verified=False,
    )
    kernel = CausalActionConditionedGeospatialKernel(parameters)
    rows: list[dict[str, object]] = []
    clipped_step_count = 0
    for issue_index in range(
        window.first_issue_index, window.target_end_index_exclusive - min(HORIZONS)
    ):
        issue_time = window.valid_times[issue_index]
        available_horizons = tuple(
            horizon
            for horizon in HORIZONS
            if issue_index + horizon < window.target_end_index_exclusive
        )
        if not available_horizons:
            continue
        targets = tuple(issue_time + timedelta(hours=horizon) for horizon in available_horizons)
        state = OutletTransitionState(
            valid_at=window.valid_times[issue_index - 1],
            available_at=issue_time,
            discharge_m3s=window.observed_discharge_m3s[issue_index - 1],
            provenance_id=(
                f"{window.outcome_provenance_id}:valid={_iso(window.valid_times[issue_index - 1])}"
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
        for offset, horizon in enumerate(available_horizons):
            target_index = issue_index + horizon
            rows.append(
                {
                    "window_id": window.window_id,
                    "issue_time_utc": _iso(issue_time),
                    "target_support_end_utc": _iso(window.valid_times[target_index]),
                    "horizon_hours": horizon,
                    "observed_discharge_m3s": window.observed_discharge_m3s[target_index],
                    "kernel_mvp_m3s": candidate.target_discharge_m3s[offset],
                    "no_future_action_m3s": no_action.target_discharge_m3s[offset],
                    "no_future_forcing_m3s": no_forcing.target_discharge_m3s[offset],
                    "causal_persistence_m3s": state.discharge_m3s,
                    "latest_observation_valid_at_utc": _iso(state.valid_at),
                    "latest_observation_available_at_utc": _iso(state.available_at),
                    "issue_state_writeback_m3s": candidate.issue_state.discharge_m3s,
                    "target_state_writeback_m3s": candidate.target_discharge_m3s[offset],
                    "future_outcome_observation_used": False,
                    "future_action_archive_used": True,
                    "future_nwm_archive_forcing_used": True,
                    "parameter_refit_performed": False,
                    "parameter_sha256": parameter_hash,
                }
            )
    return rows, clipped_step_count


def _score(
    rows: list[dict[str, object]],
) -> tuple[dict[str, dict[str, dict[str, float]]], dict[str, Any]]:
    names = ("kernel_mvp", "causal_persistence", "no_future_action", "no_future_forcing")
    metrics: dict[str, dict[str, dict[str, float]]] = {}
    counts: dict[str, int] = {}
    for horizon in HORIZONS:
        selected = [row for row in rows if row["horizon_hours"] == horizon]
        complete = [
            row
            for row in selected
            if all(
                row.get(column) not in (None, "")
                for column in (
                    "observed_discharge_m3s",
                    "kernel_mvp_m3s",
                    "causal_persistence_m3s",
                    "no_future_action_m3s",
                    "no_future_forcing_m3s",
                )
            )
        ]
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
        if len(complete) != len(selected):
            raise ValueError("kernel_mvp_transfer_missing_common_case_value")
    return metrics, {
        "common_complete_case_count_by_horizon": counts,
        "missing_values_imputed": False,
        "comparison_uses_identical_rows_within_each_horizon": True,
        "future_outlet_values_used_for_prediction": False,
    }


def _window_gates(
    *,
    rows: list[dict[str, object]],
    metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
    clipped_step_count: int,
    parameter_hash: str,
    expected_parameter_hash: str,
) -> dict[str, Any]:
    per_horizon = {
        str(horizon): {
            "candidate_beats_causal_persistence_rmse": (
                metrics[str(horizon)]["kernel_mvp"]["rmse_m3s"]
                < metrics[str(horizon)]["causal_persistence"]["rmse_m3s"]
            ),
            "candidate_beats_no_future_action_rmse": (
                metrics[str(horizon)]["kernel_mvp"]["rmse_m3s"]
                < metrics[str(horizon)]["no_future_action"]["rmse_m3s"]
            ),
            "candidate_beats_no_future_forcing_rmse": (
                metrics[str(horizon)]["kernel_mvp"]["rmse_m3s"]
                < metrics[str(horizon)]["no_future_forcing"]["rmse_m3s"]
            ),
            "action_effect_required_at_horizon": horizon in ACTION_EFFECT_HORIZONS,
        }
        for horizon in HORIZONS
    }
    persistence_passed = all(
        value["candidate_beats_causal_persistence_rmse"] for value in per_horizon.values()
    )
    action_passed = all(
        per_horizon[str(horizon)]["candidate_beats_no_future_action_rmse"]
        for horizon in ACTION_EFFECT_HORIZONS
    )
    forcing_passed = all(
        value["candidate_beats_no_future_forcing_rmse"] for value in per_horizon.values()
    )
    state_writeback_passed = bool(rows) and all(
        math.isfinite(float(row["issue_state_writeback_m3s"]))
        and math.isfinite(float(row["target_state_writeback_m3s"]))
        for row in rows
    )
    information_passed = bool(rows) and all(
        row["future_outcome_observation_used"] is False
        and row["parameter_refit_performed"] is False
        and row["parameter_sha256"] == expected_parameter_hash
        for row in rows
    )
    parameter_lock_passed = parameter_hash == expected_parameter_hash
    passed = all(
        (
            persistence_passed,
            action_passed,
            forcing_passed,
            state_writeback_passed,
            information_passed,
            parameter_lock_passed,
            clipped_step_count == 0,
        )
    )
    return {
        "per_horizon": per_horizon,
        "all_horizons_beat_causal_persistence": persistence_passed,
        "supported_horizons_beat_no_future_action": action_passed,
        "all_horizons_beat_no_future_forcing": forcing_passed,
        "unchanged_parameter_hash_gate_passed": parameter_lock_passed,
        "no_future_outcome_and_no_refit_gate_passed": information_passed,
        "state_writeback_gate_passed": state_writeback_passed,
        "clipped_candidate_step_count": clipped_step_count,
        "window_transfer_gate_passed": passed,
    }


def _metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    if not observed.size or observed.shape != predicted.shape:
        raise ValueError("kernel_mvp_transfer_metric_axis_invalid")
    error = predicted - observed
    denominator = float(np.sum((observed - observed.mean()) ** 2))
    return {
        "sample_count": int(observed.size),
        "rmse_m3s": float(np.sqrt(np.mean(error**2))),
        "mae_m3s": float(np.mean(np.abs(error))),
        "bias_m3s": float(np.mean(error)),
        "nse": float(1.0 - np.sum(error**2) / denominator),
    }


def _require_hourly(times: tuple[datetime, ...], name: str) -> None:
    if len(times) != HOUR_COUNT or any(
        second - first != timedelta(hours=1)
        for first, second in zip(times, times[1:], strict=False)
    ):
        raise ValueError(f"kernel_mvp_transfer_{name}_time_axis_invalid")


def _finite_nonnegative(value: object, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"kernel_mvp_transfer_{name}_value_invalid") from exc
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(f"kernel_mvp_transfer_{name}_value_invalid")
    return result


def _encode_rows(rows: list[dict[str, object]]) -> bytes:
    if not rows:
        raise ValueError("kernel_mvp_transfer_prediction_rows_missing")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError("kernel_mvp_transfer_json_object_required")
    return body, value


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != descriptor.get("sha256") or len(body) != descriptor.get(
        "size_bytes"
    ):
        raise ValueError("kernel_mvp_transfer_artifact_identity_mismatch")
    return body


def _artifact(path: Path, body: bytes) -> dict[str, object]:
    resolved = path.resolve()
    try:
        display = str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        display = str(resolved)
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _json_body(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("kernel_mvp_transfer_utc_time_required")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def main() -> None:
    args = parse_args()
    january_path = args.output_root / "january_temporal_holdout_predictions.csv"
    d3_path = args.output_root / "february_d3_predictions.csv"
    january_body, d3_body, report = compile_temporal_transfer(
        parameter_path=args.parameters,
        development_report_path=args.development_report,
        temporal_panel_report_path=args.temporal_panel_report,
        d3_action_manifest_path=args.d3_action_manifest,
        d3_nwm_manifest_path=args.d3_nwm_manifest,
        d3_outcome_manifest_path=args.d3_outcome_manifest,
        january_prediction_path=january_path,
        d3_prediction_path=d3_path,
    )
    args.output_root.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    january_path.write_bytes(january_body)
    d3_path.write_bytes(d3_body)
    args.report.write_bytes(_json_body(report))
    passed = report["aggregate_gate"]["all_windows_transfer_gate_passed"]
    print(f"geospatial_kernel_mvp_temporal_transfer_passed={str(passed).lower()}")
    for window_id, window in report["windows"].items():
        for horizon in HORIZONS:
            metrics = window["metrics_by_horizon"][str(horizon)]
            print(
                f"window={window_id} horizon={horizon}h "
                f"kernel_rmse={metrics['kernel_mvp']['rmse_m3s']:.6f} "
                f"persistence_rmse={metrics['causal_persistence']['rmse_m3s']:.6f}"
            )


if __name__ == "__main__":
    main()
