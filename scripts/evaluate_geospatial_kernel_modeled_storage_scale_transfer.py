#!/usr/bin/env python3
"""Evaluate whether modeled reach-storage scaling transfers across time."""

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

from data_agent.uwm.geospatial_kernel_v2.branching_network import (
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportConfig,
)
from data_agent.uwm.geospatial_kernel_v2.contracts import (
    ActionBoundaryFlux,
    ForcingFlux,
    ReachForcingSupport,
    StockState,
)

if __package__:
    from scripts.audit_geospatial_kernel_conservative_twin_action_response import (
        _advance_baseline_state,
        _artifact,
    )
    from scripts.run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
        _geometry,
        _network,
        _read_npy,
    )
    from scripts.run_geotransport_v2_blind_validation_outcome_free import (
        _parse_actions,
        _read_verified,
    )
    from scripts.score_geotransport_v2_blind_validation import _outcome_values
else:
    from audit_geospatial_kernel_conservative_twin_action_response import (
        _advance_baseline_state,
        _artifact,
    )
    from run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
        _geometry,
        _network,
        _read_npy,
    )
    from run_geotransport_v2_blind_validation_outcome_free import (
        _parse_actions,
        _read_verified,
    )
    from score_geotransport_v2_blind_validation import _outcome_values

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_protocol.json"
)
DEFAULT_INPUT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_inputs_report.json"
)
DEFAULT_ROLLOUT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_rollout_report.json"
)
DEFAULT_OUTCOME_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_outcomes_report.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "geospatial_kernel_modeled_storage_scale_transfer_posthoc/predictions.csv"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_modeled_storage_scale_transfer_posthoc_report.json"
)
OPERATOR_PATH = REPO_ROOT / "data_agent/uwm/geospatial_kernel_v2/branching_network.py"
SCHEMA = "gwm.geotransport.modeled_storage_scale_transfer_posthoc.v1"
SYSTEM_IDS = ("center_hill", "j_percy_priest")
STORAGE_SCALE_FACTORS = (0.8, 1.0, 1.2)
HORIZONS_HOURS = (1, 3, 6, 12)
ISSUE_INDICES = tuple(range(0, 661, 12))
CALIBRATION_END_ISSUE_INDEX = 336
TIMESTEP_SECONDS = 3600.0
SUBSTEP_SECONDS = 300.0
SEALED_CONFORMANCE_RELATIVE_TOLERANCE = 1e-9


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--input-report", type=Path, default=DEFAULT_INPUT_REPORT)
    parser.add_argument("--rollout-report", type=Path, default=DEFAULT_ROLLOUT_REPORT)
    parser.add_argument("--outcome-report", type=Path, default=DEFAULT_OUTCOME_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_modeled_storage_scale_transfer_posthoc(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    input_report_path: Path = DEFAULT_INPUT_REPORT,
    rollout_report_path: Path = DEFAULT_ROLLOUT_REPORT,
    outcome_report_path: Path = DEFAULT_OUTCOME_REPORT,
    output_path: Path = DEFAULT_OUTPUT,
    issue_indices: tuple[int, ...] = ISSUE_INDICES,
    storage_scale_factors: tuple[float, ...] = STORAGE_SCALE_FACTORS,
    calibration_end_issue_index: int = CALIBRATION_END_ISSUE_INDEX,
    generated_at: datetime | None = None,
) -> tuple[bytes, dict[str, Any]]:
    protocol_body, protocol = _load_json(protocol_path)
    input_body, inputs = _load_json(input_report_path)
    rollout_body, rollout = _load_json(rollout_report_path)
    outcome_body, outcomes = _load_json(outcome_report_path)
    _validate_lineage(
        protocol_body=protocol_body,
        protocol=protocol,
        input_body=input_body,
        inputs=inputs,
        rollout_body=rollout_body,
        rollout=rollout,
        outcome_body=outcome_body,
        outcomes=outcomes,
    )
    selected_issues = _validate_issue_indices(
        issue_indices, calibration_end_issue_index=calibration_end_issue_index
    )
    selected_scales = _validate_scale_factors(storage_scale_factors)

    rows: list[dict[str, object]] = []
    system_reports: dict[str, dict[str, Any]] = {}
    for system_id in SYSTEM_IDS:
        prediction_body = _read_verified(
            rollout["systems"][system_id]["prediction_artifact"]
        )
        outcome_values_body = _read_verified(
            outcomes["systems"][system_id]["outcome_values"]
        )
        system_rows, system_report = _evaluate_system(
            system_id=system_id,
            lock=protocol["systems"][system_id],
            inputs=inputs["systems"][system_id],
            sealed_prediction_body=prediction_body,
            outcome_values_body=outcome_values_body,
            issue_indices=selected_issues,
            storage_scale_factors=selected_scales,
            calibration_end_issue_index=calibration_end_issue_index,
        )
        rows.extend(system_rows)
        system_reports[system_id] = system_report

    performance_gate = all(
        value["validation_comparison"][
            "selected_scale_beats_nominal_all_horizons"
        ]
        for value in system_reports.values()
    )
    persistence_gate = all(
        value["validation_comparison"][
            "selected_scale_beats_persistence_all_horizons"
        ]
        for value in system_reports.values()
    )
    csv_body = _encode_rows(rows)
    now = generated_at or datetime.now(UTC)
    if not _aware(now):
        raise ValueError("modeled_storage_scale_transfer_generated_at_must_be_aware")
    evaluator_body = Path(__file__).read_bytes()
    operator_body = OPERATOR_PATH.read_bytes()
    report = {
        "schema": SCHEMA,
        "status": "historical_temporal_transfer_complete_not_promoted",
        "generated_at": now.astimezone(UTC).isoformat(),
        "design": {
            "systems": list(SYSTEM_IDS),
            "issue_indices": list(selected_issues),
            "issue_stride_hours": _common_stride(selected_issues),
            "calibration_issue_indices": [
                value for value in selected_issues if value < calibration_end_issue_index
            ],
            "validation_issue_indices": [
                value for value in selected_issues if value >= calibration_end_issue_index
            ],
            "calibration_end_issue_index_exclusive": calibration_end_issue_index,
            "storage_scale_factors": list(selected_scales),
            "horizons_hours": list(HORIZONS_HOURS),
            "selection_objective": (
                "minimum_equal_horizon_mean_MSE_on_calibration_split"
            ),
            "selection_tie_break": "closest_to_1_then_lower_scale",
            "state_scale_applied_at_each_issue": True,
            "future_archived_actions_used": True,
            "future_retrospective_nwm_forcing_used": True,
            "fitted_parameter_count_per_system": 1,
        },
        "source_artifacts": {
            "blind_validation_protocol": _artifact(protocol_path, protocol_body),
            "blind_validation_input_report": _artifact(input_report_path, input_body),
            "sealed_rollout_report": _artifact(rollout_report_path, rollout_body),
            "outcome_report": _artifact(outcome_report_path, outcome_body),
        },
        "implementation_artifacts": {
            "branching_manning_operator": _artifact(OPERATOR_PATH, operator_body),
            "evaluator": _artifact(Path(__file__), evaluator_body),
        },
        "systems": system_reports,
        "aggregate_gates": {
            "both_systems_nominal_replay_matches_sealed_predictions": all(
                value["execution_gates"]["nominal_replay_matches_sealed_predictions"]
                for value in system_reports.values()
            ),
            "both_systems_all_mass_balances_passed": all(
                value["execution_gates"]["all_mass_balances_passed"]
                for value in system_reports.values()
            ),
            "both_systems_selected_scale_beats_nominal_all_validation_horizons": (
                performance_gate
            ),
            "both_systems_selected_scale_beats_persistence_all_validation_horizons": (
                persistence_gate
            ),
            "historical_transfer_performance_gate_passed": (
                performance_gate and persistence_gate
            ),
            "fresh_prospective_validation_passed": False,
            "candidate_promotion_gate_passed": False,
        },
        "outputs": {"predictions": _artifact(output_path, csv_body)},
        "information_boundary": {
            "historical_outcomes_loaded": True,
            "outcomes_used_for_calibration_scale_selection": True,
            "validation_outcomes_used_for_scale_selection": False,
            "historical_outcomes_were_exposed_before_experiment_design": True,
            "sealed_nominal_predictions_modified": False,
            "operational_action_schedule_vintage_verified": False,
            "nwm_forecast_forcing_used": False,
            "nwm_v3_retrospective_forcing_used": True,
        },
        "diagnostic_interpretation": {
            "uniform_storage_scale_is_sufficient_state_assimilation": (
                performance_gate and persistence_gate
            ),
            "state_initialization_problem_resolved": False,
            "full_reach_state_observed": False,
            "predictive_accuracy_evaluated": True,
            "historical_temporal_transfer_evaluated": True,
            "fresh_validation_evaluated": False,
        },
        "claim_boundary": {
            "historical_state_scale_candidate_evaluated": True,
            "state_scale_candidate_admitted": False,
            "geospatial_kernel_validated": False,
            "prospective_v5_changed": False,
            "candidate_promoted": False,
            "runtime_default_enabled": False,
        },
    }
    return csv_body, report


def _validate_lineage(
    *,
    protocol_body: bytes,
    protocol: Mapping[str, Any],
    input_body: bytes,
    inputs: Mapping[str, Any],
    rollout_body: bytes,
    rollout: Mapping[str, Any],
    outcome_body: bytes,
    outcomes: Mapping[str, Any],
) -> None:
    del outcome_body
    sealed = outcomes.get("sealed_artifacts", {})
    if (
        protocol.get("schema") != "gwm.geotransport.v2_blind_validation_protocol.v1"
        or protocol.get("status") != "frozen_before_dynamic_input_and_outcome_access"
        or inputs.get("schema") != "gwm.geotransport.v2_blind_validation_inputs.v1"
        or inputs.get("status") != "pass_outcome_free_two_system_inputs_acquired"
        or rollout.get("schema") != "gwm.geotransport.v2_blind_validation_rollout.v1"
        or rollout.get("status") != "joint_outcome_free_predictions_sealed"
        or outcomes.get("schema") != "gwm.geotransport.v2_blind_validation_outcomes.v1"
        or outcomes.get("status") != "two_system_outcomes_acquired_after_joint_seal"
        or inputs.get("protocol", {}).get("sha256")
        != hashlib.sha256(protocol_body).hexdigest()
        or rollout.get("input_artifacts", {}).get("input_report", {}).get("sha256")
        != hashlib.sha256(input_body).hexdigest()
        or sealed.get("protocol", {}).get("sha256")
        != hashlib.sha256(protocol_body).hexdigest()
        or sealed.get("rollout_report", {}).get("sha256")
        != hashlib.sha256(rollout_body).hexdigest()
        or sealed.get("joint_seal_sha256") != rollout.get("joint_seal", {}).get("sha256")
        or outcomes.get("ordering_audit", {}).get(
            "both_predictions_verified_before_first_outcome_request"
        )
        is not True
    ):
        raise ValueError("modeled_storage_scale_transfer_lineage_invalid")
    for system_id in SYSTEM_IDS:
        if sealed.get("predictions", {}).get(system_id) != rollout.get("systems", {}).get(
            system_id, {}
        ).get("prediction_artifact"):
            raise ValueError("modeled_storage_scale_transfer_prediction_seal_invalid")


def _validate_issue_indices(
    values: tuple[int, ...], *, calibration_end_issue_index: int
) -> tuple[int, ...]:
    selected = tuple(values)
    if (
        not selected
        or tuple(sorted(set(selected))) != selected
        or not isinstance(calibration_end_issue_index, int)
        or isinstance(calibration_end_issue_index, bool)
        or any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            or value + max(HORIZONS_HOURS) > 672
            for value in selected
        )
        or not any(value < calibration_end_issue_index for value in selected)
        or not any(value >= calibration_end_issue_index for value in selected)
    ):
        raise ValueError("modeled_storage_scale_transfer_issue_split_invalid")
    return selected


def _validate_scale_factors(values: tuple[float, ...]) -> tuple[float, ...]:
    selected = tuple(float(value) for value in values)
    if (
        not selected
        or tuple(sorted(set(selected))) != selected
        or 1.0 not in selected
        or any(not math.isfinite(value) or value <= 0.0 for value in selected)
    ):
        raise ValueError("modeled_storage_scale_transfer_scales_invalid")
    return selected


def _evaluate_system(
    *,
    system_id: str,
    lock: Mapping[str, Any],
    inputs: Mapping[str, Any],
    sealed_prediction_body: bytes,
    outcome_values_body: bytes,
    issue_indices: tuple[int, ...],
    storage_scale_factors: tuple[float, ...],
    calibration_end_issue_index: int,
) -> tuple[list[dict[str, object]], dict[str, Any]]:
    topology_body = _read_verified(lock["topology_report"])
    topology = json.loads(topology_body)
    network_body = _read_verified(topology["artifacts"]["full_subnetwork"])
    network = _network(json.loads(network_body)["network"])
    if (
        network.action_entry_feature_ids != (int(lock["action_entry_feature_id"]),)
        or network.outlet_feature_id != int(lock["outlet_feature_id"])
        or len(network.feature_ids) != int(lock["feature_count"])
    ):
        raise ValueError(f"modeled_storage_scale_transfer_{system_id}_network_mismatch")
    arrays = {name: _read_npy(value) for name, value in inputs["decoded_arrays"].items()}
    feature_ids = tuple(int(value) for value in arrays["feature_ids"])
    q_lateral = np.asarray(arrays["q_lateral_m3s"], dtype=float)
    initial_storage = np.asarray(arrays["initial_storage_m3"], dtype=float)
    if (
        feature_ids != network.feature_ids
        or q_lateral.shape != (672, len(feature_ids))
        or initial_storage.shape != (len(feature_ids),)
    ):
        raise ValueError(f"modeled_storage_scale_transfer_{system_id}_axis_mismatch")
    actions = _parse_actions(_read_verified(inputs["action_values"]))
    sealed_predictions = _sealed_predictions(sealed_prediction_body)
    observations = _outcome_values(outcome_values_body)
    route_link_body = _read_verified(topology["artifacts"]["route_link_subset"])
    route_link_path = REPO_ROOT / topology["artifacts"]["route_link_subset"]["path"]
    geometry = _geometry(route_link_path, network, route_link_body)
    terminal_fraction = float(lock["forcing_support"]["partial_terminal_reach_fraction"])
    forcing_support = ReachForcingSupport(
        feature_ids=feature_ids,
        coverage_fractions=tuple(
            terminal_fraction if value == network.outlet_feature_id else 1.0
            for value in feature_ids
        ),
        support_method=str(lock["forcing_support"]["partial_terminal_reach_method"]),
        provenance_id=f"modeled-storage-scale-transfer:{system_id}:forcing-support",
        evidence_level="derived",
        admitted_as_spatial_support=True,
    )
    operator = BranchingManningNetworkTransportOperator(
        network,
        BranchingNetworkTransportConfig(
            timestep_seconds=TIMESTEP_SECONDS,
            integration_substep_seconds=SUBSTEP_SECONDS,
            operator_form_admitted=True,
        ),
    )
    canonical_state = StockState(
        values=tuple(float(value) for value in initial_storage),
        unit="m3",
        provenance_id=(
            f"nwm-v3-retrospective:{system_id}:"
            f"{inputs['decoded_arrays']['initial_storage_m3']['sha256']}"
        ),
    )
    start = min(actions)
    action_index = feature_ids.index(network.action_entry_feature_ids[0])
    issue_set = set(issue_indices)
    rows: list[dict[str, object]] = []
    mass_checks: list[bool] = []
    conformance_errors: list[float] = []
    modeled_issue_storage: dict[str, float] = {}
    for hour in range(max(issue_indices) + 1):
        issue_time = start + timedelta(hours=hour)
        if hour in issue_set:
            modeled_storage = float(sum(canonical_state.values))
            modeled_issue_storage[str(hour)] = modeled_storage
            for scale_factor in storage_scale_factors:
                state = StockState(
                    values=tuple(float(value) * scale_factor for value in canonical_state.values),
                    unit="m3",
                    provenance_id=(
                        f"{canonical_state.provenance_id}|issue:{hour}:"
                        f"storage-scale:{scale_factor}"
                    ),
                )
                for offset in range(max(HORIZONS_HOURS)):
                    support_start = issue_time + timedelta(hours=offset)
                    result = _step(
                        operator=operator,
                        geometry=geometry,
                        state=state,
                        support_start=support_start,
                        action_release_m3s=actions[support_start],
                        forcing_values=q_lateral[hour + offset],
                        feature_ids=feature_ids,
                        action_index=action_index,
                        forcing_support=forcing_support,
                        system_id=system_id,
                        provenance_suffix=(f"issue:{hour}:scale:{scale_factor}:step:{offset}"),
                    )
                    state = result.next_stock
                    mass_passed = (
                        abs(result.global_mass_balance_residual_m3)
                        <= result.numeric_mass_tolerance_m3
                    )
                    mass_checks.append(mass_passed)
                    horizon = offset + 1
                    if horizon not in HORIZONS_HOURS:
                        continue
                    target_time = support_start + timedelta(hours=1)
                    target_key = _iso(target_time)
                    sealed_value = sealed_predictions[target_key]
                    conformance_error = (
                        abs(result.outlet_mean_flow_m3s - sealed_value)
                        if scale_factor == 1.0
                        else None
                    )
                    if conformance_error is not None:
                        conformance_errors.append(conformance_error)
                    rows.append(
                        {
                            "system_id": system_id,
                            "split": (
                                "calibration"
                                if hour < calibration_end_issue_index
                                else "validation"
                            ),
                            "issue_index": hour,
                            "issue_time_utc": _iso(issue_time),
                            "target_time_utc": target_key,
                            "horizon_hours": horizon,
                            "storage_scale_factor": scale_factor,
                            "modeled_issue_state_storage_m3": modeled_storage,
                            "scaled_issue_state_storage_m3": modeled_storage * scale_factor,
                            "predicted_outlet_m3s": result.outlet_mean_flow_m3s,
                            "nominal_sealed_outlet_m3s": sealed_value,
                            "nominal_replay_absolute_error_m3s": conformance_error,
                            "observed_outlet_m3s": observations[target_key],
                            "causal_persistence_m3s": observations[_iso(issue_time)],
                            "mass_balance_residual_m3": (
                                result.global_mass_balance_residual_m3
                            ),
                            "mass_balance_tolerance_m3": result.numeric_mass_tolerance_m3,
                            "mass_balance_passed": mass_passed,
                            "future_archived_action_used": True,
                            "future_retrospective_forcing_used": True,
                        }
                    )
        if hour < max(issue_indices):
            canonical_state = _advance_baseline_state(
                operator=operator,
                geometry=geometry,
                state=canonical_state,
                support_start=issue_time,
                action_release_m3s=actions[issue_time],
                forcing_values=q_lateral[hour],
                feature_ids=feature_ids,
                action_index=action_index,
                forcing_support=forcing_support,
                system_id=system_id,
                hour=hour,
            )

    maximum_sealed_value = max(abs(value) for value in sealed_predictions.values())
    conformance_tolerance = SEALED_CONFORMANCE_RELATIVE_TOLERANCE * max(
        1.0, maximum_sealed_value
    )
    conformance_passed = max(conformance_errors) <= conformance_tolerance
    if not all(mass_checks) or not conformance_passed:
        raise RuntimeError(f"modeled_storage_scale_transfer_{system_id}_execution_failed")
    calibration = _split_metrics(rows, split="calibration", scales=storage_scale_factors)
    validation = _split_metrics(rows, split="validation", scales=storage_scale_factors)
    selected_scale = _select_scale(calibration, storage_scale_factors)
    comparison = _validation_comparison(validation, selected_scale=selected_scale)
    return rows, {
        "system_id": system_id,
        "network": {
            "feature_count": len(feature_ids),
            "modeled_issue_state_storage_m3": modeled_issue_storage,
            "issue_state_ground_truth": False,
        },
        "execution": {
            "issue_count": len(issue_indices),
            "calibration_issue_count": sum(
                value < calibration_end_issue_index for value in issue_indices
            ),
            "validation_issue_count": sum(
                value >= calibration_end_issue_index for value in issue_indices
            ),
            "scaled_rollout_count": len(issue_indices) * len(storage_scale_factors),
            "physical_step_count": len(mass_checks),
            "reported_prediction_count": len(rows),
        },
        "execution_gates": {
            "mass_balance_check_count": len(mass_checks),
            "mass_balance_pass_count": sum(mass_checks),
            "all_mass_balances_passed": all(mass_checks),
            "nominal_conformance_check_count": len(conformance_errors),
            "maximum_nominal_replay_absolute_error_m3s": max(conformance_errors),
            "nominal_replay_tolerance_m3s": conformance_tolerance,
            "nominal_replay_matches_sealed_predictions": conformance_passed,
        },
        "calibration_metrics": calibration,
        "selected_storage_scale_factor": selected_scale,
        "validation_metrics": validation,
        "validation_comparison": comparison,
        "claim_boundary": {
            "selection_uses_calibration_outcomes": True,
            "selection_uses_validation_outcomes": False,
            "validation_is_fresh_prospective": False,
            "state_scale_admitted": False,
        },
    }


def _step(
    *,
    operator: BranchingManningNetworkTransportOperator,
    geometry,
    state: StockState,
    support_start: datetime,
    action_release_m3s: float,
    forcing_values: np.ndarray,
    feature_ids: tuple[int, ...],
    action_index: int,
    forcing_support: ReachForcingSupport,
    system_id: str,
    provenance_suffix: str,
):
    action_values = np.zeros(len(feature_ids), dtype=float)
    action_values[action_index] = action_release_m3s
    return operator.step(
        state,
        geometry,
        action=ActionBoundaryFlux(
            values=tuple(float(value) for value in action_values),
            unit="m3 s-1",
            provenance_id=f"{system_id}:state-scale-action:{provenance_suffix}",
        ),
        forcing=ForcingFlux(
            values=tuple(float(value) for value in forcing_values),
            unit="m3 s-1",
            provenance_id=f"nwm-v3:{system_id}:state-scale-forcing:{provenance_suffix}",
            modeled=True,
        ),
        forcing_support=forcing_support,
    )


def _split_metrics(
    rows: list[dict[str, object]], *, split: str, scales: tuple[float, ...]
) -> dict[str, Any]:
    result: dict[str, Any] = {"scales": {}}
    for scale in scales:
        horizon_metrics = {}
        for horizon in HORIZONS_HOURS:
            selected = [
                value
                for value in rows
                if value["split"] == split
                and value["storage_scale_factor"] == scale
                and value["horizon_hours"] == horizon
                and value["observed_outlet_m3s"] is not None
                and value["causal_persistence_m3s"] is not None
            ]
            observed = np.asarray(
                [float(value["observed_outlet_m3s"]) for value in selected], dtype=float
            )
            predicted = np.asarray(
                [float(value["predicted_outlet_m3s"]) for value in selected], dtype=float
            )
            persistence = np.asarray(
                [float(value["causal_persistence_m3s"]) for value in selected], dtype=float
            )
            if not observed.size:
                raise ValueError("modeled_storage_scale_transfer_no_scorable_rows")
            horizon_metrics[str(horizon)] = {
                "prediction": _metrics(observed, predicted),
                "causal_persistence": _metrics(observed, persistence),
            }
        mean_mse = float(
            np.mean(
                [
                    horizon_metrics[str(value)]["prediction"]["mse_m6s2"]
                    for value in HORIZONS_HOURS
                ]
            )
        )
        result["scales"][str(scale)] = {
            "metrics_by_horizon": horizon_metrics,
            "equal_horizon_mean_mse_m6s2": mean_mse,
            "equal_horizon_root_mean_mse_m3s": math.sqrt(mean_mse),
        }
    return result


def _select_scale(metrics: Mapping[str, Any], scales: tuple[float, ...]) -> float:
    return min(
        scales,
        key=lambda value: (
            float(metrics["scales"][str(value)]["equal_horizon_mean_mse_m6s2"]),
            abs(value - 1.0),
            value,
        ),
    )


def _validation_comparison(
    metrics: Mapping[str, Any], *, selected_scale: float
) -> dict[str, Any]:
    selected = metrics["scales"][str(selected_scale)]
    nominal = metrics["scales"]["1.0"]
    per_horizon = {}
    nominal_wins = []
    persistence_wins = []
    for horizon in HORIZONS_HOURS:
        chosen = selected["metrics_by_horizon"][str(horizon)]["prediction"]
        base = nominal["metrics_by_horizon"][str(horizon)]["prediction"]
        persistence = selected["metrics_by_horizon"][str(horizon)]["causal_persistence"]
        chosen_rmse = float(chosen["rmse_m3s"])
        nominal_rmse = float(base["rmse_m3s"])
        persistence_rmse = float(persistence["rmse_m3s"])
        if chosen_rmse < nominal_rmse:
            nominal_wins.append(horizon)
        if chosen_rmse < persistence_rmse:
            persistence_wins.append(horizon)
        per_horizon[str(horizon)] = {
            "selected_scale_rmse_m3s": chosen_rmse,
            "nominal_scale_rmse_m3s": nominal_rmse,
            "causal_persistence_rmse_m3s": persistence_rmse,
            "selected_minus_nominal_rmse_m3s": chosen_rmse - nominal_rmse,
            "selected_minus_persistence_rmse_m3s": chosen_rmse - persistence_rmse,
            "scored_count": int(chosen["count"]),
        }
    selected_mean = float(selected["equal_horizon_mean_mse_m6s2"])
    nominal_mean = float(nominal["equal_horizon_mean_mse_m6s2"])
    return {
        "per_horizon": per_horizon,
        "selected_scale_beats_nominal_horizons_hours": nominal_wins,
        "selected_scale_beats_nominal_all_horizons": len(nominal_wins)
        == len(HORIZONS_HOURS),
        "selected_scale_beats_persistence_horizons_hours": persistence_wins,
        "selected_scale_beats_persistence_all_horizons": len(persistence_wins)
        == len(HORIZONS_HOURS),
        "selected_equal_horizon_mean_mse_m6s2": selected_mean,
        "nominal_equal_horizon_mean_mse_m6s2": nominal_mean,
        "selected_to_nominal_mean_mse_ratio": selected_mean / nominal_mean,
        "selected_scale_differs_from_nominal": selected_scale != 1.0,
        "performance_promotion_gate_passed": (
            selected_scale != 1.0
            and len(nominal_wins) == len(HORIZONS_HOURS)
            and len(persistence_wins) == len(HORIZONS_HOURS)
        ),
    }


def _metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float | int]:
    error = predicted - observed
    mse = float(np.mean(error**2))
    return {
        "count": int(error.size),
        "mse_m6s2": mse,
        "rmse_m3s": math.sqrt(mse),
        "mae_m3s": float(np.mean(np.abs(error))),
        "bias_m3s": float(np.mean(error)),
    }


def _sealed_predictions(body: bytes) -> dict[str, float]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    expected = [
        "support_start_utc",
        "support_end_utc",
        "kernel_full_subnetwork_m3s",
        "branch_silent_negative_control_m3s",
        "action_input_m3s",
        "distributed_q_lateral_input_m3s",
        "branch_q_lateral_input_m3s",
    ]
    if reader.fieldnames != expected:
        raise ValueError("modeled_storage_scale_transfer_sealed_columns_invalid")
    result = {
        _canonical_utc(value["support_end_utc"]): float(
            value["kernel_full_subnetwork_m3s"]
        )
        for value in reader
    }
    if len(result) != 672:
        raise ValueError("modeled_storage_scale_transfer_sealed_axis_invalid")
    return result


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    return body, json.loads(body)


def _encode_rows(rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _common_stride(values: tuple[int, ...]) -> int | None:
    if len(values) < 2:
        return None
    strides = {
        right - left for left, right in zip(values, values[1:], strict=False)
    }
    return strides.pop() if len(strides) == 1 else None


def _canonical_utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not _aware(parsed):
        raise ValueError("modeled_storage_scale_transfer_timezone_required")
    return _iso(parsed)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def main() -> int:
    args = parse_args()
    body, report = compile_modeled_storage_scale_transfer_posthoc(
        protocol_path=args.protocol,
        input_report_path=args.input_report,
        rollout_report_path=args.rollout_report,
        outcome_report_path=args.outcome_report,
        output_path=args.output,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(body)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.report)
    for system_id in SYSTEM_IDS:
        system = report["systems"][system_id]
        print(
            f"{system_id}_selected_scale={system['selected_storage_scale_factor']} "
            f"validation_mse_ratio="
            f"{system['validation_comparison']['selected_to_nominal_mean_mse_ratio']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
