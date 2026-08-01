#!/usr/bin/env python3
"""Evaluate causal outlet and mainstem issue-state updates on two real systems."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportConfig,
    CausalDischargeObservation,
    ReachForcingSupport,
    StockState,
)
from data_agent.uwm.geospatial_kernel_v2.graph_state_estimation import (
    DETERMINISTIC_MAINSTEM_GAIN_SEMANTICS,
)
from data_agent.uwm.geospatial_kernel_v2.horizon_assimilation_rollout import (
    build_state_assimilation_closures,
    graph_gain_profiles,
)

if __package__:
    from scripts.audit_geospatial_kernel_conservative_twin_action_response import (
        _advance_baseline_state,
        _artifact,
    )
    from scripts.evaluate_geospatial_kernel_modeled_storage_scale_transfer import (
        CALIBRATION_END_ISSUE_INDEX,
        DEFAULT_INPUT_REPORT,
        DEFAULT_OUTCOME_REPORT,
        DEFAULT_PROTOCOL,
        DEFAULT_ROLLOUT_REPORT,
        HORIZONS_HOURS,
        ISSUE_INDICES,
        SEALED_CONFORMANCE_RELATIVE_TOLERANCE,
        SUBSTEP_SECONDS,
        SYSTEM_IDS,
        TIMESTEP_SECONDS,
        _load_json,
        _metrics,
        _sealed_predictions,
        _validate_issue_indices,
        _validate_lineage,
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
    from evaluate_geospatial_kernel_modeled_storage_scale_transfer import (
        CALIBRATION_END_ISSUE_INDEX,
        DEFAULT_INPUT_REPORT,
        DEFAULT_OUTCOME_REPORT,
        DEFAULT_PROTOCOL,
        DEFAULT_ROLLOUT_REPORT,
        HORIZONS_HOURS,
        ISSUE_INDICES,
        SEALED_CONFORMANCE_RELATIVE_TOLERANCE,
        SUBSTEP_SECONDS,
        SYSTEM_IDS,
        TIMESTEP_SECONDS,
        _load_json,
        _metrics,
        _sealed_predictions,
        _validate_issue_indices,
        _validate_lineage,
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
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/geospatial_kernel_issue_state_assimilation_posthoc/predictions.csv"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_issue_state_assimilation_posthoc_report.json"
)
OPERATOR_PATH = REPO_ROOT / "data_agent/uwm/geospatial_kernel_v2/branching_network.py"
CLOSURE_PATH = REPO_ROOT / "data_agent/uwm/geospatial_kernel_v2/forecast_closure.py"
GRAPH_PATH = REPO_ROOT / "data_agent/uwm/geospatial_kernel_v2/graph_state_estimation.py"
HORIZON_ROLLOUT_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/horizon_assimilation_rollout.py"
)
SCHEMA = "gwm.geotransport.issue_state_assimilation_posthoc.v1"
MODES = ("nominal", "outlet_only_observation_update", "mainstem_ratio_observation_update")
OBSERVATION_MODES = MODES[1:]
LINEAR_DISTANCE_MODE = "linear_distance_localized_mainstem_update"
QUADRATIC_DISTANCE_MODE = "quadratic_distance_localized_mainstem_update"
GRAPH_UPDATE_MODES = {
    "mainstem_ratio_observation_update",
    LINEAR_DISTANCE_MODE,
    QUADRATIC_DISTANCE_MODE,
}
SUPPORTED_MODES = MODES + (LINEAR_DISTANCE_MODE, QUADRATIC_DISTANCE_MODE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--input-report", type=Path, default=DEFAULT_INPUT_REPORT)
    parser.add_argument("--rollout-report", type=Path, default=DEFAULT_ROLLOUT_REPORT)
    parser.add_argument("--outcome-report", type=Path, default=DEFAULT_OUTCOME_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_issue_state_assimilation_posthoc(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    input_report_path: Path = DEFAULT_INPUT_REPORT,
    rollout_report_path: Path = DEFAULT_ROLLOUT_REPORT,
    outcome_report_path: Path = DEFAULT_OUTCOME_REPORT,
    output_path: Path = DEFAULT_OUTPUT,
    issue_indices: tuple[int, ...] = ISSUE_INDICES,
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
        issue_indices,
        calibration_end_issue_index=calibration_end_issue_index,
    )

    rows: list[dict[str, object]] = []
    system_reports: dict[str, dict[str, Any]] = {}
    for system_id in SYSTEM_IDS:
        prediction_body = _read_verified(rollout["systems"][system_id]["prediction_artifact"])
        outcome_values_body = _read_verified(outcomes["systems"][system_id]["outcome_values"])
        system_rows, system_report = _evaluate_system(
            system_id=system_id,
            lock=protocol["systems"][system_id],
            inputs=inputs["systems"][system_id],
            outcome_metadata=outcomes["systems"][system_id],
            sealed_prediction_body=prediction_body,
            outcome_values_body=outcome_values_body,
            issue_indices=selected_issues,
            calibration_end_issue_index=calibration_end_issue_index,
        )
        rows.extend(system_rows)
        system_reports[system_id] = system_report

    aggregate_calibration = _aggregate_mode_metrics(
        system_reports,
        split_key="calibration_metrics",
    )
    selected_mode = _select_mode(aggregate_calibration)
    aggregate_validation = _aggregate_mode_metrics(
        system_reports,
        split_key="validation_metrics",
    )
    for system in system_reports.values():
        system["selected_mode_from_joint_calibration"] = selected_mode
        system["validation_comparison"] = _validation_comparison(
            system["validation_metrics"],
            selected_mode=selected_mode,
        )

    comparisons = [system["validation_comparison"] for system in system_reports.values()]
    selected_is_assimilation = selected_mode in OBSERVATION_MODES
    beats_nominal = all(value["selected_mode_beats_nominal_all_horizons"] for value in comparisons)
    beats_persistence = all(
        value["selected_mode_beats_persistence_all_horizons"] for value in comparisons
    )
    branch_gate = all(
        system["execution_gates"]["mainstem_update_preserved_all_branch_states"]
        for system in system_reports.values()
    )
    mass_gate = all(
        system["execution_gates"]["all_physical_mass_balances_passed"]
        for system in system_reports.values()
    )
    historical_support = (
        selected_is_assimilation
        and beats_nominal
        and beats_persistence
        and branch_gate
        and mass_gate
    )

    csv_body = _encode_rows(rows)
    now = generated_at or datetime.now(UTC)
    if not _aware(now):
        raise ValueError("issue_state_assimilation_generated_at_must_be_aware")
    report = {
        "schema": SCHEMA,
        "status": "historical_issue_state_assimilation_complete_not_promoted",
        "generated_at": now.astimezone(UTC).isoformat(),
        "design": {
            "systems": list(SYSTEM_IDS),
            "modes": list(MODES),
            "issue_indices": list(selected_issues),
            "issue_stride_hours": _common_stride(selected_issues),
            "calibration_issue_indices": [
                value for value in selected_issues if value < calibration_end_issue_index
            ],
            "validation_issue_indices": [
                value for value in selected_issues if value >= calibration_end_issue_index
            ],
            "calibration_end_issue_index_exclusive": calibration_end_issue_index,
            "horizons_hours": list(HORIZONS_HOURS),
            "analysis_gain": 1.0,
            "mode_selection_scope": "joint_two_system_calibration_split_only",
            "selection_objective": (
                "minimum_equal_system_equal_horizon_mean_MSE_on_calibration_split"
            ),
            "selection_tie_break": "declared_mode_order_nominal_first",
            "state_update_frequency": "once_at_each_issue_then_free_physical_rollout",
            "mainstem_spatial_gain": 1.0,
            "mainstem_gain_outcome_fitted": False,
            "mainstem_gain_semantics": DETERMINISTIC_MAINSTEM_GAIN_SEMANTICS,
            "branch_state_update": "none",
            "future_archived_actions_used": True,
            "future_retrospective_nwm_forcing_used": True,
        },
        "source_artifacts": {
            "blind_validation_protocol": _artifact(protocol_path, protocol_body),
            "blind_validation_input_report": _artifact(input_report_path, input_body),
            "sealed_rollout_report": _artifact(rollout_report_path, rollout_body),
            "outcome_report": _artifact(outcome_report_path, outcome_body),
        },
        "implementation_artifacts": {
            "branching_manning_operator": _artifact(
                OPERATOR_PATH,
                OPERATOR_PATH.read_bytes(),
            ),
            "causal_forecast_closure": _artifact(
                CLOSURE_PATH,
                CLOSURE_PATH.read_bytes(),
            ),
            "graph_state_update_contract": _artifact(
                GRAPH_PATH,
                GRAPH_PATH.read_bytes(),
            ),
            "horizon_assimilation_rollout_core": _artifact(
                HORIZON_ROLLOUT_PATH,
                HORIZON_ROLLOUT_PATH.read_bytes(),
            ),
            "evaluator": _artifact(Path(__file__), Path(__file__).read_bytes()),
        },
        "systems": system_reports,
        "joint_calibration_metrics": aggregate_calibration,
        "selected_mode_from_joint_calibration": selected_mode,
        "joint_validation_metrics": aggregate_validation,
        "aggregate_gates": {
            "both_systems_nominal_replay_matches_sealed_predictions": all(
                system["execution_gates"]["nominal_replay_matches_sealed_predictions"]
                for system in system_reports.values()
            ),
            "both_systems_all_analysis_ledgers_passed": all(
                system["execution_gates"]["all_analysis_ledgers_passed"]
                for system in system_reports.values()
            ),
            "both_systems_all_physical_mass_balances_passed": mass_gate,
            "both_systems_mainstem_update_preserved_all_branch_states": branch_gate,
            "selected_mode_is_observation_assimilation": selected_is_assimilation,
            "selected_mode_beats_nominal_all_validation_horizons_both_systems": (beats_nominal),
            "selected_mode_beats_persistence_all_validation_horizons_both_systems": (
                beats_persistence
            ),
            "historical_assimilation_support_gate_passed": historical_support,
            "fresh_prospective_validation_passed": False,
            "candidate_promotion_gate_passed": False,
        },
        "outputs": {"predictions": _artifact(output_path, csv_body)},
        "information_boundary": {
            "issue_update_uses_only_observation_valid_at_issue_time": True,
            "future_target_used_for_issue_state_update": False,
            "calibration_targets_used_for_mode_selection": True,
            "validation_targets_used_for_mode_selection": False,
            "historical_outcomes_were_exposed_before_experiment_design": True,
            "archived_usgs_support_end_treated_as_available_at_support_end": True,
            "actual_operational_usgs_latency_verified": False,
            "negative_discharge_used_in_forward_manning_inversion": False,
            "negative_or_missing_issue_observation_fallback": "nominal_issue_state",
            "operational_action_schedule_vintage_verified": False,
            "nwm_forecast_forcing_used": False,
            "nwm_v3_retrospective_forcing_used": True,
        },
        "diagnostic_interpretation": {
            "spatial_state_update_supported_historically": historical_support,
            "full_reach_state_observed": False,
            "issue_observation_represents_entire_mainstem": False,
            "api_latency_uncertainty_resolved": False,
            "state_initialization_problem_resolved": False,
            "fresh_validation_evaluated": False,
        },
        "claim_boundary": {
            "historical_issue_state_candidate_evaluated": True,
            "issue_state_candidate_admitted": False,
            "geospatial_kernel_validated": False,
            "prospective_v5_changed": False,
            "candidate_promoted": False,
            "runtime_default_enabled": False,
        },
    }
    return csv_body, report


def _evaluate_system(
    *,
    system_id: str,
    lock: Mapping[str, Any],
    inputs: Mapping[str, Any],
    outcome_metadata: Mapping[str, Any],
    sealed_prediction_body: bytes,
    outcome_values_body: bytes,
    issue_indices: tuple[int, ...],
    calibration_end_issue_index: int,
    modes: tuple[str, ...] = MODES,
) -> tuple[list[dict[str, object]], dict[str, Any]]:
    modes = _validate_modes(modes)
    observation_modes = tuple(mode for mode in modes if mode != "nominal")
    topology_body = _read_verified(lock["topology_report"])
    topology = json.loads(topology_body)
    network_body = _read_verified(topology["artifacts"]["full_subnetwork"])
    network_payload = json.loads(network_body)
    network = _network(network_payload["network"])
    if (
        network.action_entry_feature_ids != (int(lock["action_entry_feature_id"]),)
        or network.outlet_feature_id != int(lock["outlet_feature_id"])
        or len(network.feature_ids) != int(lock["feature_count"])
    ):
        raise ValueError(f"issue_state_assimilation_{system_id}_network_mismatch")

    mainstem_ids, mainstem_artifact = _mainstem_ids(
        system_id=system_id,
        topology=topology,
        network_payload=network_payload,
        network=network,
    )
    mainstem_set = set(mainstem_ids)
    branch_indices = tuple(
        index
        for index, feature_id in enumerate(network.feature_ids)
        if feature_id not in mainstem_set
    )
    arrays = {name: _read_npy(value) for name, value in inputs["decoded_arrays"].items()}
    feature_ids = tuple(int(value) for value in arrays["feature_ids"])
    q_lateral = np.asarray(arrays["q_lateral_m3s"], dtype=float)
    initial_storage = np.asarray(arrays["initial_storage_m3"], dtype=float)
    if (
        feature_ids != network.feature_ids
        or q_lateral.shape != (672, len(feature_ids))
        or initial_storage.shape != (len(feature_ids),)
    ):
        raise ValueError(f"issue_state_assimilation_{system_id}_axis_mismatch")
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
        provenance_id=f"issue-state-assimilation:{system_id}:forcing-support",
        evidence_level="derived",
        admitted_as_spatial_support=True,
    )
    operator = BranchingManningNetworkTransportOperator(
        network,
        BranchingNetworkTransportConfig(
            timestep_seconds=TIMESTEP_SECONDS,
            integration_substep_seconds=SUBSTEP_SECONDS,
            operator_form_admitted=True,
            allow_unadmitted_components_for_diagnostics=True,
        ),
    )
    start = min(actions)
    reference_floor = np.maximum(
        np.asarray(network.effective_lengths_m, dtype=float)
        * np.asarray(geometry.bottom_width_m, dtype=float)
        * 0.01,
        1.0,
    )
    reference_storage = np.where(
        initial_storage > 0.0,
        initial_storage,
        reference_floor,
    )
    closures, graph_gain_profiles = _closures(
        system_id=system_id,
        network=network,
        reference_storage=reference_storage,
        mainstem_ids=mainstem_ids,
        reference_time=start - timedelta(hours=1),
        modes=modes,
    )
    canonical_state = StockState(
        values=tuple(float(value) for value in initial_storage),
        unit="m3",
        provenance_id=(
            f"nwm-v3-retrospective:{system_id}:"
            f"{inputs['decoded_arrays']['initial_storage_m3']['sha256']}"
        ),
    )
    action_index = feature_ids.index(network.action_entry_feature_ids[0])
    issue_set = set(issue_indices)
    rows: list[dict[str, object]] = []
    physical_mass_checks: list[bool] = []
    analysis_checks: list[bool] = []
    conformance_errors: list[float] = []
    branch_checks: list[bool] = []
    closure_admission_checks: list[bool] = []
    refusal_reasons: Counter[str] = Counter()
    assimilated_issue_counts: Counter[str] = Counter()
    total_analysis_increment_by_mode: Counter[str] = Counter()

    for hour in range(max(issue_indices) + 1):
        issue_time = start + timedelta(hours=hour)
        if hour in issue_set:
            issue_key = _iso(issue_time)
            issue_observation = observations.get(issue_key)
            fallback_reason = _fallback_reason(issue_observation)
            for mode in modes:
                observation_tuple: tuple[CausalDischargeObservation, ...] = ()
                mode_fallback = None
                if mode in observation_modes:
                    mode_fallback = fallback_reason
                    if mode_fallback is None:
                        observation_tuple = (
                            CausalDischargeObservation(
                                feature_id=network.outlet_feature_id,
                                discharge_m3s=float(issue_observation),
                                valid_at=issue_time,
                                available_at=issue_time,
                                quality_status="approved",
                                provenance_id=(
                                    f"usgs:{outcome_metadata['site_id']}:"
                                    f"archived-support-end:{issue_key}"
                                ),
                                evidence_level="authoritative",
                            ),
                        )
                        assimilated_issue_counts[mode] += 1
                    else:
                        refusal_reasons[mode_fallback] += 1
                closure_result = closures[mode].prepare(
                    network,
                    canonical_state,
                    geometry,
                    issue_time=issue_time,
                    observations=observation_tuple,
                )
                closure_admission_checks.append(
                    closure_result.diagnostic_only
                    if mode in GRAPH_UPDATE_MODES
                    else closure_result.closure_admitted
                )
                prior_total = float(sum(canonical_state.values))
                analysis_total = float(sum(closure_result.analysis_stock.values))
                analysis_increment = closure_result.total_analysis_increment_m3
                analysis_residual = analysis_total - prior_total - analysis_increment
                analysis_tolerance = 1e-10 * max(
                    1.0,
                    abs(prior_total),
                    abs(analysis_total),
                    abs(analysis_increment),
                )
                analysis_passed = abs(analysis_residual) <= analysis_tolerance
                analysis_checks.append(analysis_passed)
                total_analysis_increment_by_mode[mode] += analysis_increment
                branch_max = max(
                    (abs(closure_result.analysis_increment_m3[index]) for index in branch_indices),
                    default=0.0,
                )
                if mode in GRAPH_UPDATE_MODES:
                    branch_checks.append(branch_max == 0.0)
                update = (
                    closure_result.observation_updates[0]
                    if closure_result.observation_updates
                    else None
                )
                state = closure_result.analysis_stock
                for offset in range(max(HORIZONS_HOURS)):
                    support_start = issue_time + timedelta(hours=offset)
                    result = _step(
                        operator=operator,
                        geometry=closure_result.effective_geometry,
                        state=state,
                        support_start=support_start,
                        action_release_m3s=actions[support_start],
                        forcing_values=q_lateral[hour + offset],
                        feature_ids=feature_ids,
                        action_index=action_index,
                        forcing_support=forcing_support,
                        system_id=system_id,
                        provenance_suffix=f"issue:{hour}:mode:{mode}:step:{offset}",
                    )
                    state = result.next_stock
                    mass_passed = (
                        abs(result.global_mass_balance_residual_m3)
                        <= result.numeric_mass_tolerance_m3
                    )
                    physical_mass_checks.append(mass_passed)
                    horizon = offset + 1
                    if horizon not in HORIZONS_HOURS:
                        continue
                    target_time = support_start + timedelta(hours=1)
                    target_key = _iso(target_time)
                    sealed_value = sealed_predictions[target_key]
                    conformance_error = (
                        abs(result.outlet_mean_flow_m3s - sealed_value)
                        if mode == "nominal"
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
                            "issue_time_utc": issue_key,
                            "target_time_utc": target_key,
                            "horizon_hours": horizon,
                            "mode": mode,
                            "issue_observed_outlet_m3s": issue_observation,
                            "observation_assimilated": bool(observation_tuple),
                            "observation_fallback_reason": mode_fallback,
                            "prior_issue_state_storage_m3": prior_total,
                            "analysis_issue_state_storage_m3": analysis_total,
                            "analysis_increment_m3": analysis_increment,
                            "local_outlet_analysis_increment_m3": (
                                None if update is None else update.analysis_increment_m3
                            ),
                            "graph_analysis_increment_m3": (
                                None if update is None else update.graph_analysis_increment_m3
                            ),
                            "graph_updated_feature_count": (
                                0 if update is None else update.graph_updated_feature_count
                            ),
                            "branch_analysis_increment_max_abs_m3": branch_max,
                            "analysis_ledger_residual_m3": analysis_residual,
                            "analysis_ledger_tolerance_m3": analysis_tolerance,
                            "analysis_ledger_passed": analysis_passed,
                            "predicted_outlet_m3s": result.outlet_mean_flow_m3s,
                            "nominal_sealed_outlet_m3s": sealed_value,
                            "nominal_replay_absolute_error_m3s": conformance_error,
                            "observed_outlet_m3s": observations[target_key],
                            "causal_persistence_m3s": issue_observation,
                            "mass_balance_residual_m3": (result.global_mass_balance_residual_m3),
                            "mass_balance_tolerance_m3": (result.numeric_mass_tolerance_m3),
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
        1.0,
        maximum_sealed_value,
    )
    conformance_passed = max(conformance_errors) <= conformance_tolerance
    if (
        not all(physical_mass_checks)
        or not all(analysis_checks)
        or not all(branch_checks)
        or not all(closure_admission_checks)
        or not conformance_passed
    ):
        raise RuntimeError(f"issue_state_assimilation_{system_id}_execution_failed")

    calibration = _mode_metrics(rows, split="calibration", modes=modes)
    validation = _mode_metrics(rows, split="validation", modes=modes)
    return rows, {
        "system_id": system_id,
        "network": {
            "feature_count": len(feature_ids),
            "mainstem_feature_ids": list(mainstem_ids),
            "mainstem_feature_count": len(mainstem_ids),
            "branch_feature_count": len(branch_indices),
            "outlet_feature_id": network.outlet_feature_id,
            "mainstem_source_artifact": mainstem_artifact,
            "graph_gain_profiles": graph_gain_profiles,
            "reference_storage_zero_replacement_count": int((initial_storage <= 0.0).sum()),
            "reference_storage_zero_replacement_semantics": (
                "one-centimeter rectangular-channel storage floor, minimum 1 m3"
            ),
            "issue_state_ground_truth": False,
        },
        "observation": {
            "site_id": outcome_metadata["site_id"],
            "feature_id": network.outlet_feature_id,
            "source_role": "archived_independent_observation_as_issue_state_update",
            "nonnegative_issue_count": sum(assimilated_issue_counts.values())
            // len(observation_modes),
            "assimilation_issue_count_by_mode": dict(assimilated_issue_counts),
            "fallback_issue_count_by_reason_across_observation_modes": dict(refusal_reasons),
            "fallback_issue_count": sum(refusal_reasons.values()) // len(observation_modes),
            "negative_values_clipped": False,
            "forward_manning_refusal_is_nominal_fallback": True,
        },
        "execution": {
            "issue_count": len(issue_indices),
            "calibration_issue_count": sum(
                value < calibration_end_issue_index for value in issue_indices
            ),
            "validation_issue_count": sum(
                value >= calibration_end_issue_index for value in issue_indices
            ),
            "mode_rollout_count": len(issue_indices) * len(modes),
            "physical_step_count": len(physical_mass_checks),
            "reported_prediction_count": len(rows),
            "total_analysis_increment_m3_by_mode": dict(total_analysis_increment_by_mode),
        },
        "execution_gates": {
            "physical_mass_balance_check_count": len(physical_mass_checks),
            "physical_mass_balance_pass_count": sum(physical_mass_checks),
            "all_physical_mass_balances_passed": all(physical_mass_checks),
            "analysis_ledger_check_count": len(analysis_checks),
            "analysis_ledger_pass_count": sum(analysis_checks),
            "all_analysis_ledgers_passed": all(analysis_checks),
            "mainstem_branch_preservation_check_count": len(branch_checks),
            "mainstem_branch_preservation_pass_count": sum(branch_checks),
            "mainstem_update_preserved_all_branch_states": all(branch_checks),
            "closure_admission_status_check_count": len(closure_admission_checks),
            "closure_admission_status_pass_count": sum(closure_admission_checks),
            "admitted_nominal_and_outlet_closures_and_diagnostic_mainstem_closure": (
                all(closure_admission_checks)
            ),
            "nominal_conformance_check_count": len(conformance_errors),
            "maximum_nominal_replay_absolute_error_m3s": max(conformance_errors),
            "nominal_replay_tolerance_m3s": conformance_tolerance,
            "nominal_replay_matches_sealed_predictions": conformance_passed,
        },
        "calibration_metrics": calibration,
        "validation_metrics": validation,
        "claim_boundary": {
            "mode_selection_uses_calibration_outcomes": True,
            "mode_selection_uses_validation_outcomes": False,
            "validation_is_fresh_prospective": False,
            "state_update_admitted_for_runtime": False,
        },
    }


def _mainstem_ids(
    *,
    system_id: str,
    topology: Mapping[str, Any],
    network_payload: Mapping[str, Any],
    network: Any,
) -> tuple[tuple[int, ...], dict[str, Any]]:
    if system_id == "center_hill":
        descriptor = topology["artifacts"]["d4_network"]
        body = _read_verified(descriptor)
        raw_ids = json.loads(body)["network"]["feature_ids"]
        artifact = _artifact(REPO_ROOT / descriptor["path"], body)
    elif system_id == "j_percy_priest":
        raw_ids = network_payload["linear_referenced_mainstem"]["feature_ids"]
        body = json.dumps(
            network_payload["linear_referenced_mainstem"],
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        artifact = {
            "path": topology["artifacts"]["full_subnetwork"]["path"],
            "embedded_object": "linear_referenced_mainstem",
            "embedded_canonical_sha256": hashlib.sha256(body).hexdigest(),
        }
    else:
        raise ValueError("issue_state_assimilation_system_unsupported")
    feature_ids = tuple(int(value) for value in raw_ids)
    if (
        len(feature_ids) != int(topology["domain"]["active_mainstem_feature_count"])
        or feature_ids[0] != network.action_entry_feature_ids[0]
        or feature_ids[-1] != network.outlet_feature_id
        or not set(feature_ids).issubset(network.feature_ids)
    ):
        raise ValueError(f"issue_state_assimilation_{system_id}_mainstem_invalid")
    downstream = dict(zip(network.feature_ids, network.downstream_feature_ids, strict=True))
    if any(
        downstream[left] != right for left, right in zip(feature_ids, feature_ids[1:], strict=False)
    ):
        raise ValueError(f"issue_state_assimilation_{system_id}_mainstem_not_contiguous")
    return feature_ids, artifact


def _closures(
    *,
    system_id: str,
    network: Any,
    reference_storage: np.ndarray,
    mainstem_ids: tuple[int, ...],
    reference_time: datetime,
    modes: tuple[str, ...] = MODES,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    return build_state_assimilation_closures(
        system_id=system_id,
        network=network,
        reference_storage_m3=tuple(float(value) for value in reference_storage),
        mainstem_feature_ids=mainstem_ids,
        reference_time=reference_time,
        modes=modes,
    )


def _graph_gain_profiles(
    *,
    network: Any,
    mainstem_ids: tuple[int, ...],
    modes: tuple[str, ...],
) -> tuple[dict[str, tuple[float, ...]], dict[str, dict[str, Any]]]:
    rows, reports = graph_gain_profiles(
        network=network,
        mainstem_feature_ids=mainstem_ids,
        modes=modes,
    )
    return rows, reports  # type: ignore[return-value]


def _step(
    *,
    operator: BranchingManningNetworkTransportOperator,
    geometry: Any,
    state: StockState,
    support_start: datetime,
    action_release_m3s: float,
    forcing_values: np.ndarray,
    feature_ids: tuple[int, ...],
    action_index: int,
    forcing_support: ReachForcingSupport,
    system_id: str,
    provenance_suffix: str,
) -> Any:
    from data_agent.uwm.geospatial_kernel_v2 import ActionBoundaryFlux, ForcingFlux

    action_values = np.zeros(len(feature_ids), dtype=float)
    action_values[action_index] = action_release_m3s
    return operator.step(
        state,
        geometry,
        action=ActionBoundaryFlux(
            values=tuple(float(value) for value in action_values),
            unit="m3 s-1",
            provenance_id=f"{system_id}:issue-state-action:{provenance_suffix}",
        ),
        forcing=ForcingFlux(
            values=tuple(float(value) for value in forcing_values),
            unit="m3 s-1",
            provenance_id=f"nwm-v3:{system_id}:issue-state-forcing:{provenance_suffix}",
            modeled=True,
        ),
        forcing_support=forcing_support,
    )


def _fallback_reason(value: float | None) -> str | None:
    if value is None:
        return "missing_issue_observation"
    if value < 0.0:
        return "negative_discharge_outside_forward_manning_domain"
    return None


def _validate_modes(values: tuple[str, ...]) -> tuple[str, ...]:
    modes = tuple(values)
    if (
        not modes
        or len(modes) != len(set(modes))
        or modes[0] != "nominal"
        or "outlet_only_observation_update" not in modes
        or not set(modes).issubset(SUPPORTED_MODES)
    ):
        raise ValueError("issue_state_assimilation_modes_invalid")
    return modes


def _mode_metrics(
    rows: list[dict[str, object]],
    *,
    split: str,
    modes: tuple[str, ...] = MODES,
) -> dict[str, Any]:
    result: dict[str, Any] = {"modes": {}}
    for mode in modes:
        horizon_metrics: dict[str, Any] = {}
        for horizon in HORIZONS_HOURS:
            selected = [
                value
                for value in rows
                if value["split"] == split
                and value["mode"] == mode
                and value["horizon_hours"] == horizon
                and value["observed_outlet_m3s"] is not None
                and value["causal_persistence_m3s"] is not None
            ]
            observed = np.asarray(
                [float(value["observed_outlet_m3s"]) for value in selected],
                dtype=float,
            )
            predicted = np.asarray(
                [float(value["predicted_outlet_m3s"]) for value in selected],
                dtype=float,
            )
            persistence = np.asarray(
                [float(value["causal_persistence_m3s"]) for value in selected],
                dtype=float,
            )
            if not observed.size:
                raise ValueError("issue_state_assimilation_no_scorable_rows")
            horizon_metrics[str(horizon)] = {
                "prediction": _metrics(observed, predicted),
                "causal_persistence": _metrics(observed, persistence),
            }
        mean_mse = float(
            np.mean(
                [horizon_metrics[str(value)]["prediction"]["mse_m6s2"] for value in HORIZONS_HOURS]
            )
        )
        result["modes"][mode] = {
            "metrics_by_horizon": horizon_metrics,
            "equal_horizon_mean_mse_m6s2": mean_mse,
            "equal_horizon_root_mean_mse_m3s": math.sqrt(mean_mse),
        }
    return result


def _aggregate_mode_metrics(
    systems: Mapping[str, Mapping[str, Any]],
    *,
    split_key: str,
    modes: tuple[str, ...] = MODES,
) -> dict[str, Any]:
    result: dict[str, Any] = {"modes": {}}
    for mode in modes:
        per_system = {
            system_id: float(system[split_key]["modes"][mode]["equal_horizon_mean_mse_m6s2"])
            for system_id, system in systems.items()
        }
        mean_mse = float(np.mean(list(per_system.values())))
        result["modes"][mode] = {
            "per_system_equal_horizon_mean_mse_m6s2": per_system,
            "equal_system_equal_horizon_mean_mse_m6s2": mean_mse,
            "equal_system_equal_horizon_root_mean_mse_m3s": math.sqrt(mean_mse),
        }
    return result


def _select_mode(
    metrics: Mapping[str, Any],
    modes: tuple[str, ...] = MODES,
) -> str:
    order = {mode: index for index, mode in enumerate(modes)}
    return min(
        modes,
        key=lambda mode: (
            float(metrics["modes"][mode]["equal_system_equal_horizon_mean_mse_m6s2"]),
            order[mode],
        ),
    )


def _validation_comparison(
    metrics: Mapping[str, Any],
    *,
    selected_mode: str,
) -> dict[str, Any]:
    selected = metrics["modes"][selected_mode]
    nominal = metrics["modes"]["nominal"]
    per_horizon: dict[str, Any] = {}
    nominal_wins: list[int] = []
    persistence_wins: list[int] = []
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
            "selected_mode_rmse_m3s": chosen_rmse,
            "nominal_rmse_m3s": nominal_rmse,
            "causal_persistence_rmse_m3s": persistence_rmse,
            "selected_minus_nominal_rmse_m3s": chosen_rmse - nominal_rmse,
            "selected_minus_persistence_rmse_m3s": (chosen_rmse - persistence_rmse),
            "scored_count": int(chosen["count"]),
        }
    selected_mean = float(selected["equal_horizon_mean_mse_m6s2"])
    nominal_mean = float(nominal["equal_horizon_mean_mse_m6s2"])
    return {
        "selected_mode": selected_mode,
        "per_horizon": per_horizon,
        "selected_mode_beats_nominal_horizons_hours": nominal_wins,
        "selected_mode_beats_nominal_all_horizons": len(nominal_wins) == len(HORIZONS_HOURS),
        "selected_mode_beats_persistence_horizons_hours": persistence_wins,
        "selected_mode_beats_persistence_all_horizons": len(persistence_wins)
        == len(HORIZONS_HOURS),
        "selected_equal_horizon_mean_mse_m6s2": selected_mean,
        "nominal_equal_horizon_mean_mse_m6s2": nominal_mean,
        "selected_to_nominal_mean_mse_ratio": selected_mean / nominal_mean,
    }


def _encode_rows(rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _common_stride(values: tuple[int, ...]) -> int | None:
    if len(values) < 2:
        return None
    strides = {right - left for left, right in zip(values, values[1:], strict=False)}
    return strides.pop() if len(strides) == 1 else None


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def main() -> int:
    args = parse_args()
    body, report = compile_issue_state_assimilation_posthoc(
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
    print(f"selected_mode={report['selected_mode_from_joint_calibration']}")
    for system_id in SYSTEM_IDS:
        comparison = report["systems"][system_id]["validation_comparison"]
        print(
            f"{system_id}_validation_mse_ratio={comparison['selected_to_nominal_mean_mse_ratio']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
