#!/usr/bin/env python3
"""Evaluate the frozen Center Hill candidate on J. Percy Priest without refitting."""

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
    GeographicResponseSupport,
    HourlyActionForcingSeries,
    OutletTransitionState,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    ActionInnovationTransitionParameters,
    CausalActionInnovationGeospatialKernel,
    action_innovation_transition_parameters_from_dict,
)

if __package__:
    from scripts import evaluate_geospatial_kernel_action_innovation_candidate as candidate
else:
    import evaluate_geospatial_kernel_action_innovation_candidate as candidate


REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = Path(__file__).resolve()
DEFAULT_FREEZE = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_action_innovation_candidate_freeze.json"
)
DEFAULT_INPUT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_inputs_report.json"
)
DEFAULT_OUTCOME_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_outcomes_report.json"
)
DEFAULT_REPLICATION_INPUT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_inputs_report.json"
)
DEFAULT_REPLICATION_OUTCOME_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_outcomes_report.json"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/kernel_innovation_cross_system_posthoc"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_action_innovation_cross_system_posthoc_report.json"
)

SCHEMA = "gwm.geotransport.action_innovation_cross_system_posthoc.v1"
FREEZE_SCHEMA = "gwm.geotransport.geospatial_kernel_action_innovation_candidate_freeze.v1"
INPUT_SCHEMA = "gwm.geotransport.v2_blind_validation_inputs.v1"
OUTCOME_SCHEMA = "gwm.geotransport.v2_blind_validation_outcomes.v1"
REPLICATION_INPUT_SCHEMA = "gwm.geotransport.kinematic_wave_holdout_inputs.v2"
REPLICATION_OUTCOME_SCHEMA = "gwm.geotransport.kinematic_wave_holdout_outcomes.v2"
SYSTEM_ID = "j_percy_priest"
HORIZONS = (1, 3, 6, 12)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--input-report", type=Path, default=DEFAULT_INPUT_REPORT)
    parser.add_argument("--outcome-report", type=Path, default=DEFAULT_OUTCOME_REPORT)
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
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_cross_system_posthoc(
    *,
    freeze_path: Path = DEFAULT_FREEZE,
    input_report_path: Path = DEFAULT_INPUT_REPORT,
    outcome_report_path: Path = DEFAULT_OUTCOME_REPORT,
    replication_input_report_path: Path = DEFAULT_REPLICATION_INPUT_REPORT,
    replication_outcome_report_path: Path = DEFAULT_REPLICATION_OUTCOME_REPORT,
    transferred_parameter_path: Path | None = None,
    prediction_path: Path | None = None,
    replication_prediction_path: Path | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    transferred_parameter_path = transferred_parameter_path or (
        DEFAULT_OUTPUT_ROOT / "j_percy_priest_transferred_parameters.json"
    )
    prediction_path = prediction_path or (
        DEFAULT_OUTPUT_ROOT / "j_percy_priest_predictions.csv"
    )
    replication_prediction_path = replication_prediction_path or (
        DEFAULT_OUTPUT_ROOT / "j_percy_priest_replication_predictions.csv"
    )

    freeze_body, freeze = _load_json(freeze_path)
    _validate_freeze(freeze)
    source_parameter_descriptor = freeze["candidate_artifacts"]["parameters"]
    source_parameter_body = _read_verified(source_parameter_descriptor)
    source_parameters = action_innovation_transition_parameters_from_dict(
        json.loads(source_parameter_body)
    )
    source_parameter_sha256 = hashlib.sha256(source_parameter_body).hexdigest()

    input_report_body, input_report = _load_json(input_report_path)
    outcome_report_body, outcome_report = _load_json(outcome_report_path)
    protocol_body, protocol, target_inputs, target_outcomes = _validate_source_reports(
        input_report=input_report,
        outcome_report=outcome_report,
    )
    topology_body = _read_verified(target_inputs["topology_report"])
    topology_report = json.loads(topology_body)
    network_body = _read_verified(topology_report["artifacts"]["full_subnetwork"])
    network_payload = json.loads(network_body)
    target_lock = protocol["systems"][SYSTEM_ID]

    target_support = _transfer_support(
        source=source_parameters.support,
        network_payload=network_payload,
        target_lock=target_lock,
        source_parameter_sha256=source_parameter_sha256,
        topology_sha256=hashlib.sha256(topology_body).hexdigest(),
    )
    transferred_parameters = _transfer_parameters(
        source=source_parameters,
        support=target_support,
        source_parameter_sha256=source_parameter_sha256,
    )
    transferred_parameter_body = _json_body(transferred_parameters.as_dict())
    transferred_parameter_sha256 = hashlib.sha256(
        transferred_parameter_body
    ).hexdigest()

    primary_prediction_body, primary = _compile_diagnostic_window(
        target_inputs=target_inputs,
        target_outcomes=target_outcomes,
        target_lock=target_lock,
        target_support=target_support,
        parameters=transferred_parameters,
        parameter_sha256=transferred_parameter_sha256,
    )

    replication_input_body, replication_input = _load_json(
        replication_input_report_path
    )
    replication_outcome_body, replication_outcome = _load_json(
        replication_outcome_report_path
    )
    (
        replication_protocol_body,
        replication_protocol,
        replication_inputs,
        replication_outcomes,
    ) = _validate_source_reports(
        input_report=replication_input,
        outcome_report=replication_outcome,
        input_schema=REPLICATION_INPUT_SCHEMA,
        outcome_schema=REPLICATION_OUTCOME_SCHEMA,
    )
    if _descriptor_identity(replication_inputs["topology_report"]) != (
        _descriptor_identity(target_inputs["topology_report"])
    ):
        raise ValueError("cross_system_posthoc_replication_topology_identity_invalid")
    replication_prediction_body, replication = _compile_diagnostic_window(
        target_inputs=replication_inputs,
        target_outcomes=replication_outcomes,
        target_lock=replication_protocol["systems"][SYSTEM_ID],
        target_support=target_support,
        parameters=transferred_parameters,
        parameter_sha256=transferred_parameter_sha256,
    )

    freeze_time = _parse_time(freeze["frozen_at"])
    outcome_access_time = _parse_time(outcome_report["generated_at"])
    replication_outcome_access_time = _parse_time(replication_outcome["generated_at"])
    outcomes_exposed_before_freeze = (
        outcome_access_time < freeze_time
        and replication_outcome_access_time < freeze_time
    )
    if not outcomes_exposed_before_freeze:
        raise ValueError("cross_system_posthoc_outcome_timing_boundary_invalid")

    primary_passed = primary["diagnostic_gate"][
        "cross_system_diagnostic_gate_passed"
    ]
    replication_passed = replication["diagnostic_gate"][
        "cross_system_diagnostic_gate_passed"
    ]
    all_windows_passed = primary_passed and replication_passed
    failure_replicated = not primary_passed and not replication_passed
    if all_windows_passed:
        status = "zero_refit_cross_system_posthoc_both_windows_passed_not_validated"
    elif failure_replicated:
        status = "zero_refit_cross_system_posthoc_failure_replicated"
    else:
        status = "zero_refit_cross_system_posthoc_windows_inconsistent"

    outputs = {
        "transferred_parameters": transferred_parameter_body,
        "predictions": primary_prediction_body,
        "replication_predictions": replication_prediction_body,
    }
    report = {
        "schema": SCHEMA,
        "status": status,
        "generated_at": datetime.now(UTC).isoformat(),
        "system_id": SYSTEM_ID,
        "implementation_artifacts": {
            "evaluator": _artifact(EVALUATOR_PATH, EVALUATOR_PATH.read_bytes()),
            "frozen_core_operator": freeze["candidate_artifacts"]["core_operator"],
        },
        "source_artifacts": {
            "candidate_freeze": _artifact(freeze_path, freeze_body),
            "source_parameters": source_parameter_descriptor,
            "input_report": _artifact(input_report_path, input_report_body),
            "outcome_report": _artifact(outcome_report_path, outcome_report_body),
            "protocol": _artifact_from_descriptor(input_report["protocol"], protocol_body),
            "target_topology_report": _artifact_from_descriptor(
                target_inputs["topology_report"], topology_body
            ),
            "target_network": topology_report["artifacts"]["full_subnetwork"],
            "target_action": target_inputs["action_values"],
            "target_feature_axis": target_inputs["decoded_arrays"]["feature_ids"],
            "target_q_lateral": target_inputs["decoded_arrays"]["q_lateral_m3s"],
            "target_forcing_time": target_inputs["decoded_arrays"][
                "forcing_timestamps_utc"
            ],
            "target_outcomes": target_outcomes["outcome_values"],
            "replication_input_report": _artifact(
                replication_input_report_path, replication_input_body
            ),
            "replication_outcome_report": _artifact(
                replication_outcome_report_path, replication_outcome_body
            ),
            "replication_protocol": _artifact_from_descriptor(
                replication_input["protocol"], replication_protocol_body
            ),
            "replication_action": replication_inputs["action_values"],
            "replication_feature_axis": replication_inputs["decoded_arrays"][
                "feature_ids"
            ],
            "replication_q_lateral": replication_inputs["decoded_arrays"][
                "q_lateral_m3s"
            ],
            "replication_forcing_time": replication_inputs["decoded_arrays"][
                "forcing_timestamps_utc"
            ],
            "replication_outcomes": replication_outcomes["outcome_values"],
        },
        "outputs": {
            "transferred_parameters": _artifact(
                transferred_parameter_path, transferred_parameter_body
            ),
            "predictions": _artifact(prediction_path, primary_prediction_body),
            "replication_predictions": _artifact(
                replication_prediction_path, replication_prediction_body
            ),
        },
        "transfer_contract": {
            "source_network_id": source_parameters.support.network_id,
            "target_network_id": target_support.network_id,
            "coefficient_refit_performed": False,
            "target_outcomes_used_for_parameter_fit": False,
            "baseline_drift_unchanged": (
                transferred_parameters.baseline_drift_m3s_per_hour
                == source_parameters.baseline_drift_m3s_per_hour
            ),
            "action_change_coefficient_unchanged": (
                transferred_parameters.action_change_coefficient
                == source_parameters.action_change_coefficient
            ),
            "forcing_coefficient_unchanged": (
                transferred_parameters.forcing_coefficient
                == source_parameters.forcing_coefficient
            ),
            "lag_hours_unchanged": (
                transferred_parameters.support.lag_hours
                == source_parameters.support.lag_hours
            ),
            "lag_weights_unchanged": (
                transferred_parameters.support.lag_weights
                == source_parameters.support.lag_weights
            ),
            "adapted_fields": [
                "support.network_id",
                "support.action_entry_feature_id",
                "support.outlet_feature_id",
                "support.path_feature_ids",
                "support.provenance_id",
                "parameter.provenance_id",
            ],
            "target_path_feature_count": len(target_support.path_feature_ids),
            "forcing_support": "sum_of_target_mainstem_q_lateral_rows",
        },
        "window": primary["window"],
        "execution": primary["execution"],
        "metrics_by_horizon": primary["metrics_by_horizon"],
        "rmse_deltas_by_horizon": primary["rmse_deltas_by_horizon"],
        "scoring": primary["scoring"],
        "diagnostic_gate": primary["diagnostic_gate"],
        "replication_window": replication,
        "diagnostic_interpretation": {
            "zero_refit_transfer_supported": all_windows_passed,
            "failure_replicated_on_second_historical_window": failure_replicated,
            "candidate_beats_persistence_horizons_hours": [
                horizon
                for horizon in HORIZONS
                if primary["diagnostic_gate"]["per_horizon"][str(horizon)][
                    "candidate_beats_causal_persistence_rmse"
                ]
            ],
            "replication_candidate_beats_persistence_horizons_hours": [
                horizon
                for horizon in HORIZONS
                if replication["diagnostic_gate"]["per_horizon"][str(horizon)][
                    "candidate_beats_causal_persistence_rmse"
                ]
            ],
            "candidate_clipping_observed": (
                primary["execution"]["clipped_candidate_step_count"] > 0
                or replication["execution"]["clipped_candidate_step_count"] > 0
            ),
            "result_may_trigger_refit_on_these_windows": False,
            "result_may_motivate_new_candidate_identity": True,
            "reason": (
                "posthoc_target_outcomes_were_exposed_before_source_candidate_freeze"
            ),
        },
        "information_boundary": {
            "historical_action_archive_used": True,
            "retrospective_nwm_forcing_used": True,
            "target_outcomes_were_exposed_before_candidate_freeze": (
                outcomes_exposed_before_freeze
            ),
            "historical_window_count": 2,
            "fresh_prospective_window_consumed": False,
            "operational_issue_time_vintages_verified": False,
            "future_outcomes_used_inside_each_rollout": False,
            "latest_observation_latency_assumption_hours": 1,
        },
        "claim_boundary": {
            "cross_system_posthoc_diagnostic_executed": True,
            "cross_system_diagnostic_gate_passed": all_windows_passed,
            "cross_system_failure_replicated": failure_replicated,
            "source_candidate_artifacts_unchanged": True,
            "transferred_parameter_identity_is_separate_diagnostic_artifact": True,
            "candidate_admitted": False,
            "geospatial_kernel_validated": False,
            "multi_system_generalization_validated": False,
            "operational_forecast_validated": False,
            "runtime_default_enabled": False,
        },
    }
    return outputs, report


def _compile_diagnostic_window(
    *,
    target_inputs: Mapping[str, Any],
    target_outcomes: Mapping[str, Any],
    target_lock: Mapping[str, Any],
    target_support: GeographicResponseSupport,
    parameters: ActionInnovationTransitionParameters,
    parameter_sha256: str,
) -> tuple[bytes, dict[str, Any]]:
    window = _load_window(
        target_inputs=target_inputs,
        target_outcomes=target_outcomes,
        target_lock=target_lock,
        target_support=target_support,
    )
    rows, execution = _evaluate_window(
        window=window,
        parameters=parameters,
        parameter_sha256=parameter_sha256,
    )
    prediction_body = _encode_rows(rows)
    columns = {
        "candidate": "action_innovation_candidate_m3s",
        "causal_persistence": "causal_persistence_m3s",
        "no_future_action": "no_future_action_m3s",
        "no_future_forcing": "no_future_forcing_m3s",
    }
    metrics, scoring = candidate._score(rows, columns)
    gate = candidate._gate(
        rows=rows,
        metrics=metrics,
        candidate_name="candidate",
        comparison_names=("causal_persistence", "no_future_forcing"),
        additional_all_horizon_names=(),
        clipped_step_count=execution["clipped_candidate_step_count"],
        gate_name="cross_system_diagnostic_gate_passed",
    )
    rmse_deltas = {
        str(horizon): {
            f"candidate_minus_{baseline}_rmse_m3s": (
                metrics[str(horizon)]["candidate"]["rmse_m3s"]
                - metrics[str(horizon)][baseline]["rmse_m3s"]
            )
            for baseline in (
                "causal_persistence",
                "no_future_action",
                "no_future_forcing",
            )
        }
        for horizon in HORIZONS
    }
    return prediction_body, {
        "window": {
            "input_start_utc": _iso(window["valid_times"][0]),
            "input_end_utc": _iso(window["valid_times"][-1]),
            "input_hour_count": len(window["valid_times"]),
            "first_issue_time_utc": _iso(
                window["valid_times"][max(target_support.lag_hours) + 1]
            ),
            "horizons_hours": list(HORIZONS),
        },
        "execution": execution,
        "metrics_by_horizon": metrics,
        "rmse_deltas_by_horizon": rmse_deltas,
        "scoring": scoring,
        "diagnostic_gate": gate,
    }


def _validate_freeze(freeze: Mapping[str, Any]) -> None:
    claims = freeze.get("claim_boundary") or {}
    admission = freeze.get("admission_contract") or {}
    if (
        freeze.get("schema") != FREEZE_SCHEMA
        or freeze.get("status") != "frozen_bounded_candidate_not_admitted"
        or claims.get("candidate_identity_frozen") is not True
        or claims.get("candidate_admitted") is not False
        or claims.get("geospatial_kernel_validated") is not False
        or claims.get("multi_system_generalization_validated") is not False
        or claims.get("runtime_default_enabled") is not False
        or admission.get("multi_system_evidence_required") is not True
        or admission.get("automatic_admission_from_posthoc_gate_results") is not False
    ):
        raise ValueError("cross_system_posthoc_candidate_freeze_invalid")


def _validate_source_reports(
    *,
    input_report: Mapping[str, Any],
    outcome_report: Mapping[str, Any],
    input_schema: str = INPUT_SCHEMA,
    outcome_schema: str = OUTCOME_SCHEMA,
) -> tuple[bytes, Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    if (
        input_report.get("schema") != input_schema
        or input_report.get("status") != "pass_outcome_free_two_system_inputs_acquired"
        or (input_report.get("data_isolation") or {}).get("outcome_values_loaded")
        is not False
        or outcome_report.get("schema") != outcome_schema
        or outcome_report.get("status") != "two_system_outcomes_acquired_after_joint_seal"
        or (outcome_report.get("ordering_audit") or {}).get(
            "both_predictions_verified_before_first_outcome_request"
        )
        is not True
        or (outcome_report.get("claim_boundary") or {}).get(
            "outcome_values_imputed"
        )
        is not False
    ):
        raise ValueError("cross_system_posthoc_source_report_invalid")
    protocol_body = _read_verified(input_report["protocol"])
    protocol = json.loads(protocol_body)
    sealed_protocol = outcome_report["sealed_artifacts"]["protocol"]
    if (
        _descriptor_identity(input_report["protocol"])
        != _descriptor_identity(sealed_protocol)
        or SYSTEM_ID not in input_report.get("systems", {})
        or SYSTEM_ID not in outcome_report.get("systems", {})
        or SYSTEM_ID not in protocol.get("systems", {})
    ):
        raise ValueError("cross_system_posthoc_protocol_or_system_identity_invalid")
    target_inputs = input_report["systems"][SYSTEM_ID]
    target_outcomes = outcome_report["systems"][SYSTEM_ID]
    lock = protocol["systems"][SYSTEM_ID]
    if (
        _descriptor_identity(target_inputs["topology_report"])
        != _descriptor_identity(lock["topology_report"])
        or target_outcomes.get("system_id") != SYSTEM_ID
        or target_outcomes.get("site_id") != lock["outcome"]["site_id"]
        or (target_outcomes.get("quality") or {}).get("missing_values_imputed")
        is not False
    ):
        raise ValueError("cross_system_posthoc_target_source_identity_invalid")
    return protocol_body, protocol, target_inputs, target_outcomes


def _transfer_support(
    *,
    source: GeographicResponseSupport,
    network_payload: Mapping[str, Any],
    target_lock: Mapping[str, Any],
    source_parameter_sha256: str,
    topology_sha256: str,
) -> GeographicResponseSupport:
    network = network_payload["network"]
    path = network_payload["linear_referenced_mainstem"]
    feature_ids = tuple(int(value) for value in path["feature_ids"])
    action_entry = int(target_lock["action_entry_feature_id"])
    outlet = int(target_lock["outlet_feature_id"])
    if (
        network.get("network_id") != "j-percy-priest:dam-to-gauge:full-incremental-subnetwork-v1"
        or network.get("outlet_feature_id") != outlet
        or network.get("action_entry_feature_ids") != [action_entry]
        or feature_ids[0] != action_entry
        or feature_ids[-1] != outlet
        or len(feature_ids) != int(target_lock["mainstem_feature_count"])
    ):
        raise ValueError("cross_system_posthoc_target_geographic_support_invalid")
    return GeographicResponseSupport(
        network_id=str(network["network_id"]),
        action_entry_feature_id=action_entry,
        outlet_feature_id=outlet,
        path_feature_ids=feature_ids,
        lag_hours=source.lag_hours,
        lag_weights=source.lag_weights,
        provenance_id=(
            "zero-refit-cross-system-support:"
            f"source-parameters={source_parameter_sha256}:"
            f"target-topology={topology_sha256}"
        ),
        evidence_level="candidate",
        admitted=False,
    )


def _transfer_parameters(
    *,
    source: ActionInnovationTransitionParameters,
    support: GeographicResponseSupport,
    source_parameter_sha256: str,
) -> ActionInnovationTransitionParameters:
    return ActionInnovationTransitionParameters(
        support=support,
        baseline_drift_m3s_per_hour=source.baseline_drift_m3s_per_hour,
        action_change_coefficient=source.action_change_coefficient,
        forcing_coefficient=source.forcing_coefficient,
        timestep_seconds=source.timestep_seconds,
        supported_forecast_horizons_hours=source.supported_forecast_horizons_hours,
        maximum_discharge_m3s=source.maximum_discharge_m3s,
        training_data_start=source.training_data_start,
        training_data_end=source.training_data_end,
        training_sample_count=source.training_sample_count,
        provenance_id=(
            f"{source.provenance_id}|zero-refit-transfer:"
            f"source-parameters={source_parameter_sha256}:target={support.network_id}"
        ),
        evidence_level="candidate",
        admitted=False,
        outcome_calibrated=source.outcome_calibrated,
    )


def _load_window(
    *,
    target_inputs: Mapping[str, Any],
    target_outcomes: Mapping[str, Any],
    target_lock: Mapping[str, Any],
    target_support: GeographicResponseSupport,
) -> dict[str, Any]:
    action_body = _read_verified(target_inputs["action_values"])
    action_starts, valid_times, action_values = _parse_actions(action_body)
    arrays = target_inputs["decoded_arrays"]
    feature_ids = tuple(
        int(value) for value in _read_npy(arrays["feature_ids"]).tolist()
    )
    q_lateral = np.asarray(_read_npy(arrays["q_lateral_m3s"]), dtype=float)
    forcing_times = tuple(
        _parse_time(str(value))
        for value in _read_npy(arrays["forcing_timestamps_utc"]).tolist()
    )
    path_indices = tuple(feature_ids.index(value) for value in target_support.path_feature_ids)
    if (
        action_starts != forcing_times
        or q_lateral.shape != (len(valid_times), len(feature_ids))
        or len(feature_ids) != int(target_lock["feature_count"])
        or not np.isfinite(q_lateral).all()
        or bool((q_lateral < 0.0).any())
    ):
        raise ValueError("cross_system_posthoc_input_axis_invalid")
    forcing_values = tuple(
        float(value) for value in q_lateral[:, path_indices].sum(axis=1)
    )
    outcome_body = _read_verified(target_outcomes["outcome_values"])
    outcomes = _parse_outcomes(outcome_body)
    prior_time = valid_times[0] - timedelta(hours=1)
    if (
        prior_time not in outcomes
        or any(value not in outcomes for value in valid_times)
        or sum(outcomes[value] is None for value in valid_times)
        != int(target_outcomes["quality"]["target_missing_hour_count"])
    ):
        raise ValueError("cross_system_posthoc_outcome_axis_invalid")
    return {
        "valid_times": valid_times,
        "action_values": action_values,
        "forcing_values": forcing_values,
        "outcomes": outcomes,
        "action_sha256": hashlib.sha256(action_body).hexdigest(),
        "forcing_sha256": target_inputs["decoded_arrays"]["q_lateral_m3s"]["sha256"],
        "outcome_sha256": hashlib.sha256(outcome_body).hexdigest(),
    }


def _evaluate_window(
    *,
    window: Mapping[str, Any],
    parameters: ActionInnovationTransitionParameters,
    parameter_sha256: str,
) -> tuple[list[dict[str, object]], dict[str, int | float]]:
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
    kernel = CausalActionInnovationGeospatialKernel(parameters)
    first_issue_index = max(parameters.support.lag_hours) + 1
    rows: list[dict[str, object]] = []
    clipped_step_count = 0
    candidate_step_count = 0
    skipped_missing_state_count = 0
    skipped_nonphysical_state_count = 0
    forecast_issue_count = 0
    for issue_index in range(first_issue_index, len(valid_times) - 1):
        issue_time = valid_times[issue_index]
        state_time = valid_times[issue_index - 1]
        state_value = outcomes[state_time]
        if state_value is None:
            skipped_missing_state_count += 1
            continue
        if float(state_value) < 0.0:
            skipped_nonphysical_state_count += 1
            continue
        horizons = tuple(
            horizon for horizon in HORIZONS if issue_index + horizon < len(valid_times)
        )
        targets = tuple(issue_time + timedelta(hours=value) for value in horizons)
        state = OutletTransitionState(
            valid_at=state_time,
            available_at=issue_time,
            discharge_m3s=float(state_value),
            provenance_id=(
                f"historical-usgs:{window['outcome_sha256']}:valid={_iso(state_time)}"
            ),
            evidence_level="candidate",
            observed=True,
        )
        forecast = kernel.forecast(
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
        if (
            forecast.operational_vintages_verified
            or forecast.admitted
            or forecast.future_observations_used
        ):
            raise ValueError("cross_system_posthoc_forecast_claim_boundary_invalid")
        forecast_issue_count += 1
        candidate_step_count += len(forecast.steps)
        clipped_step_count += sum(step.clipped for step in forecast.steps)
        for offset, horizon in enumerate(horizons):
            target_time = targets[offset]
            observed = outcomes[target_time]
            rows.append(
                {
                    "system_id": SYSTEM_ID,
                    "issue_time_utc": _iso(issue_time),
                    "target_support_end_utc": _iso(target_time),
                    "horizon_hours": horizon,
                    "observed_discharge_m3s": "" if observed is None else observed,
                    "action_innovation_candidate_m3s": (
                        forecast.target_discharge_m3s[offset]
                    ),
                    "causal_persistence_m3s": state.discharge_m3s,
                    "no_future_action_m3s": no_action.target_discharge_m3s[offset],
                    "no_future_forcing_m3s": no_forcing.target_discharge_m3s[offset],
                    "latest_observation_valid_at_utc": _iso(state.valid_at),
                    "latest_observation_available_at_utc": _iso(state.available_at),
                    "issue_state_writeback_m3s": forecast.issue_state.discharge_m3s,
                    "target_state_writeback_m3s": (
                        forecast.target_discharge_m3s[offset]
                    ),
                    "future_outcome_observation_used": False,
                    "operational_vintages_verified": False,
                    "parameter_sha256": parameter_sha256,
                }
            )
    if not rows:
        raise ValueError("cross_system_posthoc_no_executable_rows")
    return rows, {
        "forecast_issue_count": forecast_issue_count,
        "prediction_row_count": len(rows),
        "skipped_missing_state_issue_count": skipped_missing_state_count,
        "skipped_nonphysical_state_issue_count": skipped_nonphysical_state_count,
        "candidate_step_count": candidate_step_count,
        "clipped_candidate_step_count": clipped_step_count,
        "clipped_candidate_step_fraction": (
            clipped_step_count / candidate_step_count
        ),
    }


def _parse_actions(
    body: bytes,
) -> tuple[tuple[datetime, ...], tuple[datetime, ...], tuple[float, ...]]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    if reader.fieldnames != [
        "support_start_utc",
        "support_end_utc",
        "action_release_m3s",
        "source_role",
    ]:
        raise ValueError("cross_system_posthoc_action_columns_invalid")
    rows = list(reader)
    starts = tuple(_parse_time(row["support_start_utc"]) for row in rows)
    ends = tuple(_parse_time(row["support_end_utc"]) for row in rows)
    values = tuple(float(row["action_release_m3s"]) for row in rows)
    if (
        len(rows) != 672
        or any(
            end - start != timedelta(hours=1)
            for start, end in zip(starts, ends, strict=True)
        )
        or any(row["source_role"] != "boundary_action" for row in rows)
        or any(not np.isfinite(value) or value < 0.0 for value in values)
        or tuple(sorted(set(starts))) != starts
        or tuple(sorted(set(ends))) != ends
    ):
        raise ValueError("cross_system_posthoc_action_values_invalid")
    return starts, ends, values


def _parse_outcomes(body: bytes) -> dict[datetime, float | None]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    if reader.fieldnames != [
        "support_end_utc",
        "observed_discharge_m3s",
        "source_role",
        "evaluation_role",
    ]:
        raise ValueError("cross_system_posthoc_outcome_columns_invalid")
    outcomes: dict[datetime, float | None] = {}
    for row in reader:
        valid_at = _parse_time(row["support_end_utc"])
        raw = row["observed_discharge_m3s"]
        value = None if raw == "" else float(raw)
        if (
            valid_at in outcomes
            or row["source_role"] != "independent_observation"
            or row["evaluation_role"] not in {"persistence_prior", "target"}
            or (value is not None and not np.isfinite(value))
        ):
            raise ValueError("cross_system_posthoc_outcome_value_invalid")
        outcomes[valid_at] = value
    if len(outcomes) != 673 or tuple(sorted(outcomes)) != tuple(outcomes):
        raise ValueError("cross_system_posthoc_outcome_values_invalid")
    return outcomes


def _read_npy(descriptor: Mapping[str, Any]) -> np.ndarray:
    body = _read_verified(descriptor)
    value = np.load(io.BytesIO(body), allow_pickle=False)
    if (
        str(value.dtype) != descriptor.get("dtype")
        or list(value.shape) != descriptor.get("shape")
    ):
        raise ValueError("cross_system_posthoc_array_descriptor_invalid")
    return value


def _load_json(path: Path) -> tuple[bytes, Mapping[str, Any]]:
    body = path.read_bytes()
    value = json.loads(body)
    if not isinstance(value, Mapping):
        raise ValueError("cross_system_posthoc_json_mapping_required")
    return body, value


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    if not isinstance(descriptor, Mapping) or not {
        "path",
        "sha256",
        "size_bytes",
    }.issubset(descriptor):
        raise ValueError("cross_system_posthoc_artifact_descriptor_invalid")
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("cross_system_posthoc_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor["sha256"]
        or len(body) != descriptor["size_bytes"]
    ):
        raise ValueError("cross_system_posthoc_artifact_identity_mismatch")
    return body


def _descriptor_identity(descriptor: Mapping[str, Any]) -> tuple[str, str, int]:
    return (
        str(descriptor.get("path")),
        str(descriptor.get("sha256")),
        int(descriptor.get("size_bytes", -1)),
    )


def _artifact_from_descriptor(
    descriptor: Mapping[str, Any], body: bytes
) -> dict[str, Any]:
    if (
        hashlib.sha256(body).hexdigest() != descriptor["sha256"]
        or len(body) != descriptor["size_bytes"]
    ):
        raise ValueError("cross_system_posthoc_artifact_body_mismatch")
    return {
        "path": str(descriptor["path"]),
        "sha256": str(descriptor["sha256"]),
        "size_bytes": int(descriptor["size_bytes"]),
    }


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": _display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _encode_rows(rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _json_body(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("cross_system_posthoc_time_invalid")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("cross_system_posthoc_time_invalid")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def main() -> None:
    args = parse_args()
    paths = {
        "transferred_parameters": (
            args.output_root / "j_percy_priest_transferred_parameters.json"
        ),
        "predictions": args.output_root / "j_percy_priest_predictions.csv",
        "replication_predictions": (
            args.output_root / "j_percy_priest_replication_predictions.csv"
        ),
    }
    bodies, report = compile_cross_system_posthoc(
        freeze_path=args.freeze,
        input_report_path=args.input_report,
        outcome_report_path=args.outcome_report,
        replication_input_report_path=args.replication_input_report,
        replication_outcome_report_path=args.replication_outcome_report,
        transferred_parameter_path=paths["transferred_parameters"],
        prediction_path=paths["predictions"],
        replication_prediction_path=paths["replication_predictions"],
    )
    args.output_root.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    for name, body in bodies.items():
        paths[name].write_bytes(body)
    args.report.write_bytes(_json_body(report))
    print(f"status={report['status']}")
    for window_id, result in (
        ("primary", report),
        ("replication", report["replication_window"]),
    ):
        for horizon in HORIZONS:
            metrics = result["metrics_by_horizon"][str(horizon)]
            print(
                f"window={window_id} horizon={horizon}h "
                f"candidate_rmse={metrics['candidate']['rmse_m3s']:.6f} "
                f"persistence_rmse={metrics['causal_persistence']['rmse_m3s']:.6f}"
            )
    print(
        "cross_system_diagnostic_gate_passed="
        f"{str(report['claim_boundary']['cross_system_diagnostic_gate_passed']).lower()}"
    )


if __name__ == "__main__":
    main()
