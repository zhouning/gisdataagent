#!/usr/bin/env python3
"""Audit twin Manning action-response sensitivity to modeled issue-state storage."""

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

import numpy as np

from data_agent.uwm.geospatial_kernel_v2.branching_network import (
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportConfig,
)
from data_agent.uwm.geospatial_kernel_v2.conservative_twin_action_response import (
    ConservativeTwinManningActionResponseKernel,
)
from data_agent.uwm.geospatial_kernel_v2.contracts import (
    ReachForcingSupport,
    StockState,
)

if __package__:
    from scripts.audit_geospatial_kernel_conservative_twin_action_response import (
        _advance_baseline_state,
        _artifact,
        _scenario_steps,
        _signed_response_passes,
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
else:
    from audit_geospatial_kernel_conservative_twin_action_response import (
        _advance_baseline_state,
        _artifact,
        _scenario_steps,
        _signed_response_passes,
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

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_protocol.json"
)
DEFAULT_INPUT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_inputs_report.json"
)
DEFAULT_STAGE32_GATES = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/stage32_lag_support_gates.json"
)
DEFAULT_STAGE32_LEDGER = REPO_ROOT / (
    "data/geotransport_v0_1/stage32_center_hill_lag_support_events/"
    "lag_support_evidence_ledger.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "geospatial_kernel_twin_response_state_sensitivity_posthoc/responses.csv"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_twin_response_state_sensitivity_posthoc_report.json"
)
OPERATOR_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/conservative_twin_action_response.py"
)
BASE_AUDITOR_PATH = REPO_ROOT / (
    "scripts/audit_geospatial_kernel_conservative_twin_action_response.py"
)
SCHEMA = "gwm.geotransport.twin_response_state_sensitivity_posthoc.v1"
SYSTEM_IDS = ("center_hill", "j_percy_priest")
ISSUE_INDICES = (0, 336)
STORAGE_SCALE_FACTORS = (0.8, 1.0, 1.2)
RELEASE_DELTAS_M3S = (-50.0, 50.0)
HORIZON_HOURS = 12
NON_UNIVERSAL_LAG_REFERENCE_HOURS = 5
TIMESTEP_SECONDS = 3600.0
SUBSTEP_SECONDS = 300.0
RESPONSE_ZERO_TOLERANCE_M3S = 1e-9


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--input-report", type=Path, default=DEFAULT_INPUT_REPORT)
    parser.add_argument("--stage32-gates", type=Path, default=DEFAULT_STAGE32_GATES)
    parser.add_argument("--stage32-ledger", type=Path, default=DEFAULT_STAGE32_LEDGER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_twin_response_state_sensitivity_posthoc(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    input_report_path: Path = DEFAULT_INPUT_REPORT,
    stage32_gates_path: Path = DEFAULT_STAGE32_GATES,
    stage32_ledger_path: Path = DEFAULT_STAGE32_LEDGER,
    output_path: Path = DEFAULT_OUTPUT,
    issue_indices: tuple[int, ...] = ISSUE_INDICES,
    storage_scale_factors: tuple[float, ...] = STORAGE_SCALE_FACTORS,
    generated_at: datetime | None = None,
) -> tuple[bytes, dict[str, Any]]:
    protocol_body = protocol_path.read_bytes()
    input_body = input_report_path.read_bytes()
    protocol = json.loads(protocol_body)
    inputs = json.loads(input_body)
    if (
        protocol.get("schema") != "gwm.geotransport.v2_blind_validation_protocol.v1"
        or protocol.get("status") != "frozen_before_dynamic_input_and_outcome_access"
        or inputs.get("schema") != "gwm.geotransport.v2_blind_validation_inputs.v1"
        or inputs.get("status") != "pass_outcome_free_two_system_inputs_acquired"
        or inputs.get("protocol", {}).get("sha256")
        != hashlib.sha256(protocol_body).hexdigest()
    ):
        raise ValueError("twin_state_sensitivity_source_contract_invalid")
    selected_issues = _validate_issue_indices(issue_indices)
    selected_scales = _validate_storage_scale_factors(storage_scale_factors)
    stage32_gates_body, stage32_ledger_body, lag_boundary = _load_lag_evidence_boundary(
        gates_path=stage32_gates_path,
        ledger_path=stage32_ledger_path,
    )

    rows: list[dict[str, object]] = []
    system_reports: dict[str, dict[str, Any]] = {}
    rows_by_system: dict[str, list[dict[str, object]]] = {}
    for system_id in SYSTEM_IDS:
        system_rows, system_report = _evaluate_system(
            system_id=system_id,
            lock=protocol["systems"][system_id],
            inputs=inputs["systems"][system_id],
            issue_indices=selected_issues,
            storage_scale_factors=selected_scales,
        )
        rows.extend(system_rows)
        rows_by_system[system_id] = system_rows
        system_reports[system_id] = system_report

    cross_system = _cross_system_robustness(
        center_rows=rows_by_system["center_hill"],
        priest_rows=rows_by_system["j_percy_priest"],
    )
    csv_body = _encode_rows(rows)
    structural_passed = all(
        value["structural_gates"]["all_structural_gates_passed"]
        for value in system_reports.values()
    )
    now = generated_at or datetime.now(UTC)
    if not _aware(now):
        raise ValueError("twin_state_sensitivity_generated_at_must_be_aware")
    evaluator_body = Path(__file__).read_bytes()
    operator_body = OPERATOR_PATH.read_bytes()
    base_auditor_body = BASE_AUDITOR_PATH.read_bytes()
    report = {
        "schema": SCHEMA,
        "status": "modeled_issue_state_sensitivity_complete_not_promoted",
        "generated_at": now.astimezone(UTC).isoformat(),
        "design": {
            "systems": list(SYSTEM_IDS),
            "issue_indices": list(selected_issues),
            "issue_state_storage_scale_factors": list(selected_scales),
            "release_deltas_m3s": list(RELEASE_DELTAS_M3S),
            "forecast_horizon_hours": HORIZON_HOURS,
            "non_universal_lag_reference_hours": NON_UNIVERSAL_LAG_REFERENCE_HOURS,
            "scale_applied_to_modeled_reach_storage_at_each_issue": True,
            "scale_applied_before_issue_state_spinup": False,
            "shared_scaled_issue_state_per_twin_pair": True,
            "shared_distributed_forcing_per_twin_pair": True,
            "same_geometry_and_network_across_scales_within_system": True,
            "new_fitted_parameter_count": 0,
        },
        "source_artifacts": {
            "blind_validation_protocol": _artifact(protocol_path, protocol_body),
            "blind_validation_input_report": _artifact(input_report_path, input_body),
            "stage32_lag_support_gates": _artifact(
                stage32_gates_path, stage32_gates_body
            ),
            "stage32_lag_support_ledger": _artifact(
                stage32_ledger_path, stage32_ledger_body
            ),
        },
        "implementation_artifacts": {
            "conservative_twin_operator": _artifact(OPERATOR_PATH, operator_body),
            "base_conservative_twin_auditor": _artifact(
                BASE_AUDITOR_PATH, base_auditor_body
            ),
            "evaluator": _artifact(Path(__file__), evaluator_body),
        },
        "lag_evidence_boundary": lag_boundary,
        "systems": system_reports,
        "cross_system_robustness": cross_system,
        "aggregate_gates": {
            "two_system_structural_gate_passed": structural_passed,
            "cross_system_response_contrast_preserved_under_tested_storage_scales": (
                cross_system["all_three_partition_rankings_preserved"]
            ),
            "all_requested_interventions_have_nonzero_action_excitation": all(
                value["action_support"]["zero_excitation_rollout_count"] == 0
                for value in system_reports.values()
            ),
            "fresh_prospective_validation_passed": False,
            "mechanistic_candidate_promotion_gate_passed": False,
        },
        "outputs": {"responses": _artifact(output_path, csv_body)},
        "information_boundary": {
            "raw_usgs_outcome_files_opened": False,
            "stage32_posthoc_outcome_summary_loaded": True,
            "stage32_summary_used_as_model_target": False,
            "outcome_values_used_in_current_twin_rollouts": False,
            "historical_archived_actions_loaded": True,
            "nwm_v3_retrospective_forcing_loaded": True,
            "issue_reach_storage_is_modeled_not_observed": True,
        },
        "diagnostic_interpretation": {
            "tested_storage_scaling_explains_away_cross_system_contrast": not cross_system[
                "all_three_partition_rankings_preserved"
            ],
            "tested_storage_scaling_preserves_cross_system_contrast": cross_system[
                "all_three_partition_rankings_preserved"
            ],
            "initial_storage_uncertainty_resolved": False,
            "topology_or_geometry_causally_identified_as_difference_source": False,
            "five_hour_reference_validated_as_travel_time": False,
            "j_percy_priest_travel_time_validated": False,
            "negative_release_response_comparable_across_both_systems": False,
            "predictive_accuracy_evaluated": False,
        },
        "claim_boundary": {
            "modeled_issue_state_sensitivity_audited": True,
            "counterfactual_release_effect_causally_validated": False,
            "hydrodynamic_response_validated": False,
            "geospatial_kernel_validated": False,
            "prospective_v5_changed": False,
            "candidate_promoted": False,
            "runtime_default_enabled": False,
        },
    }
    return csv_body, report


def _validate_issue_indices(values: tuple[int, ...]) -> tuple[int, ...]:
    selected = tuple(values)
    if (
        not selected
        or tuple(sorted(set(selected))) != selected
        or any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            or value + HORIZON_HOURS > 672
            for value in selected
        )
    ):
        raise ValueError("twin_state_sensitivity_issue_indices_invalid")
    return selected


def _validate_storage_scale_factors(values: tuple[float, ...]) -> tuple[float, ...]:
    selected = tuple(float(value) for value in values)
    if (
        not selected
        or tuple(sorted(set(selected))) != selected
        or 1.0 not in selected
        or any(not np.isfinite(value) or value <= 0.0 for value in selected)
    ):
        raise ValueError("twin_state_sensitivity_storage_scale_factors_invalid")
    return selected


def _load_lag_evidence_boundary(
    *, gates_path: Path, ledger_path: Path
) -> tuple[bytes, bytes, dict[str, Any]]:
    gates_body = gates_path.read_bytes()
    ledger_body = ledger_path.read_bytes()
    gates = json.loads(gates_body)
    ledger = json.loads(ledger_body)
    ledger_artifact = gates.get("ledger_artifact", {})
    gate_decision = gates.get("decision", {})
    ledger_decision = ledger.get("decision", {})
    event_summary = gates.get("event_summary", [])
    ledger_summary = ledger.get("lag_support_summary", {})
    event_supports = [value.get("supported_lags_hours") for value in event_summary]
    if (
        gates.get("schema") != "gwm.geotransport.stage32_lag_support_gates.v1"
        or gates.get("status") != "blind_common_empirical_lag_support_rejected"
        or gates.get("all_gates_passed") is not True
        or ledger.get("schema") != "gwm.geotransport.public_lag_support_evidence.v1"
        or ledger_artifact.get("sha256") != hashlib.sha256(ledger_body).hexdigest()
        or ledger_artifact.get("size_bytes") != len(ledger_body)
        or gate_decision != ledger_decision
        or gate_decision.get("common_empirical_support_admitted") is not False
        or gate_decision.get("common_supported_lags_hours") != []
        or gate_decision.get("physical_travel_time_admitted") is not False
        or gates.get("gates", {}).get("cross_event_support_intersection_is_empty")
        is not True
        or gates.get("gates", {}).get(
            "empirical_support_is_neither_physical_nor_hydraulic_time"
        )
        is not True
        or event_supports
        != ledger_summary.get("per_event_supported_lags_hours")
    ):
        raise ValueError("twin_state_sensitivity_stage32_evidence_invalid")
    return gates_body, ledger_body, {
        "center_hill_stage32_status": gates["status"],
        "center_hill_common_empirical_support_admitted": False,
        "center_hill_common_supported_lags_hours": [],
        "center_hill_event_supported_lags_hours": event_supports,
        "center_hill_event_response_detectable": [
            bool(value["response_detectable"]) for value in event_summary
        ],
        "center_hill_empirical_lag_is_physical_travel_time": False,
        "center_hill_empirical_lag_is_hydraulic_edge_travel_time": False,
        "j_percy_priest_independent_lag_support_bound": False,
        "j_percy_priest_absence_scope": (
            "no_j_percy_priest_lag_support_artifact_in_bound_stage32_evidence"
        ),
        "five_hour_value_role_in_this_audit": (
            "non_universal_pre_response_volume_reference_only"
        ),
        "lag_evidence_used_for_parameter_fitting": False,
        "travel_time_validated_by_this_sensitivity_audit": False,
    }


def _evaluate_system(
    *,
    system_id: str,
    lock: Mapping[str, Any],
    inputs: Mapping[str, Any],
    issue_indices: tuple[int, ...],
    storage_scale_factors: tuple[float, ...],
) -> tuple[list[dict[str, object]], dict[str, Any]]:
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
        raise ValueError(f"twin_state_sensitivity_{system_id}_network_lock_mismatch")
    arrays = {name: _read_npy(descriptor) for name, descriptor in inputs["decoded_arrays"].items()}
    feature_ids = tuple(int(value) for value in arrays["feature_ids"])
    q_lateral = np.asarray(arrays["q_lateral_m3s"], dtype=float)
    initial_storage = np.asarray(arrays["initial_storage_m3"], dtype=float)
    if (
        feature_ids != network.feature_ids
        or q_lateral.shape != (672, len(feature_ids))
        or initial_storage.shape != (len(feature_ids),)
    ):
        raise ValueError(f"twin_state_sensitivity_{system_id}_dynamic_axis_mismatch")
    actions = _parse_actions(_read_verified(inputs["action_values"]))
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
        provenance_id=f"twin-state-sensitivity:{system_id}:forcing-support",
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
    kernel = ConservativeTwinManningActionResponseKernel(operator)
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
    all_steps = []
    signed_steps = []
    ordering_checks: list[bool] = []
    modeled_issue_state_storage: dict[str, float] = {}
    for hour in range(max(issue_indices) + 1):
        issue_time = start + timedelta(hours=hour)
        if hour in issue_set:
            modeled_storage = float(sum(canonical_state.values))
            modeled_issue_state_storage[str(hour)] = modeled_storage
            for scale_factor in storage_scale_factors:
                scaled_state = StockState(
                    values=tuple(float(value) * scale_factor for value in canonical_state.values),
                    unit="m3",
                    provenance_id=(
                        f"{canonical_state.provenance_id}|issue:{hour}:"
                        f"storage-scale:{scale_factor}"
                    ),
                )
                results = {}
                for release_delta in RELEASE_DELTAS_M3S:
                    rollout_steps = _scenario_steps(
                        issue_time=issue_time,
                        issue_index=hour,
                        release_delta_m3s=release_delta,
                        actions=actions,
                        q_lateral=q_lateral,
                        feature_ids=feature_ids,
                        action_index=action_index,
                        forcing_support=forcing_support,
                        system_id=system_id,
                    )
                    result = kernel.forecast(
                        scaled_state,
                        geometry,
                        rollout_steps,
                        issue_time=issue_time,
                    )
                    results[release_delta] = result
                    all_steps.extend(result.steps)
                    signed_steps.extend((release_delta, value) for value in result.steps)
                    rows.append(
                        _response_row(
                            system_id=system_id,
                            issue_index=hour,
                            issue_time=issue_time,
                            modeled_issue_storage_m3=modeled_storage,
                            storage_scale_factor=scale_factor,
                            release_delta_m3s=release_delta,
                            result=result,
                        )
                    )
                negative_steps = results[RELEASE_DELTAS_M3S[0]].steps
                positive_steps = results[RELEASE_DELTAS_M3S[1]].steps
                for negative, positive in zip(negative_steps, positive_steps, strict=True):
                    common_baseline = abs(
                        negative.baseline_outlet_mean_flow_m3s
                        - positive.baseline_outlet_mean_flow_m3s
                    ) <= RESPONSE_ZERO_TOLERANCE_M3S
                    ordering_checks.append(
                        common_baseline
                        and negative.scenario_outlet_mean_flow_m3s
                        <= negative.baseline_outlet_mean_flow_m3s
                        + RESPONSE_ZERO_TOLERANCE_M3S
                        and positive.baseline_outlet_mean_flow_m3s
                        <= positive.scenario_outlet_mean_flow_m3s
                        + RESPONSE_ZERO_TOLERANCE_M3S
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

    mass_checks = [
        value.individual_mass_balances_passed and value.differential_mass_balance_passed
        for value in all_steps
    ]
    sign_checks = [
        _signed_response_passes(release_delta, value) for release_delta, value in signed_steps
    ]
    structural = {
        "mass_balance_check_count": len(mass_checks),
        "mass_balance_pass_count": sum(mass_checks),
        "all_mass_balances_passed": all(mass_checks),
        "signed_response_check_count": len(sign_checks),
        "signed_response_pass_count": sum(sign_checks),
        "signed_response_gate_passed": all(sign_checks),
        "release_ordering_check_count": len(ordering_checks),
        "release_ordering_pass_count": sum(ordering_checks),
        "release_ordering_gate_passed": all(ordering_checks),
    }
    structural["all_structural_gates_passed"] = all(
        (
            structural["all_mass_balances_passed"],
            structural["signed_response_gate_passed"],
            structural["release_ordering_gate_passed"],
        )
    )
    sensitivity = _storage_sensitivity_summary(rows, storage_scale_factors)
    identifiable_row_count = sum(
        bool(value["action_excitation_identifiable_12h"]) for value in rows
    )
    return rows, {
        "system_id": system_id,
        "network": {
            "feature_count": len(feature_ids),
            "action_entry_feature_id": network.action_entry_feature_ids[0],
            "outlet_feature_id": network.outlet_feature_id,
            "modeled_issue_state_storage_m3": modeled_issue_state_storage,
            "issue_state_ground_truth": False,
        },
        "execution": {
            "issue_count": len(issue_indices),
            "storage_scale_count": len(storage_scale_factors),
            "paired_rollout_count": (
                len(issue_indices) * len(storage_scale_factors) * len(RELEASE_DELTAS_M3S)
            ),
            "paired_step_count": len(all_steps),
            "reported_row_count": len(rows),
        },
        "action_support": {
            "requested_rollout_count": len(rows),
            "identifiable_action_excitation_rollout_count": identifiable_row_count,
            "zero_excitation_rollout_count": len(rows) - identifiable_row_count,
            "zero_excitation_reason": (
                "negative_intervention_is_bounded_at_zero_release"
                if identifiable_row_count < len(rows)
                else None
            ),
        },
        "structural_gates": structural,
        "storage_sensitivity": sensitivity,
        "response_envelopes_across_all_tested_states": {
            metric: _range(
                [float(value[metric]) for value in rows if value[metric] is not None]
            )
            for metric in (
                "input_recovered_at_outlet_fraction_12h",
                "input_retained_in_storage_fraction_12h",
                "response_rate_gain_12h",
                "absolute_outlet_response_volume_before_5h_reference_fraction",
            )
        },
        "claim_boundary": {
            "issue_state_perturbation_audited": True,
            "outcomes_used_in_rollouts": False,
            "predictive_accuracy_scored": False,
            "physical_travel_time_inferred": False,
            "causal_effect_validated": False,
        },
    }


def _response_row(
    *,
    system_id: str,
    issue_index: int,
    issue_time: datetime,
    modeled_issue_storage_m3: float,
    storage_scale_factor: float,
    release_delta_m3s: float,
    result,
) -> dict[str, object]:
    arrivals = [
        index + 1
        for index, value in enumerate(result.steps)
        if abs(value.incremental_outlet_mean_flow_m3s) > RESPONSE_ZERO_TOLERANCE_M3S
    ]
    input_volume = float(
        sum(value.incremental_action_input_volume_m3 for value in result.steps)
    )
    outlet_volume = float(sum(value.incremental_outlet_volume_m3 for value in result.steps))
    absolute_volume = float(
        sum(abs(value.incremental_outlet_volume_m3) for value in result.steps)
    )
    pre_reference_volume = float(
        sum(
            abs(value.incremental_outlet_volume_m3)
            for value in result.steps[: NON_UNIVERSAL_LAG_REFERENCE_HOURS - 1]
        )
    )
    target = result.steps[-1]
    mean_release_delta = input_volume / (HORIZON_HOURS * TIMESTEP_SECONDS)
    excitation_identifiable = abs(input_volume) > RESPONSE_ZERO_TOLERANCE_M3S
    recovery_fraction = outlet_volume / input_volume if excitation_identifiable else None
    storage_fraction = (
        target.final_incremental_storage_m3 / input_volume
        if excitation_identifiable
        else None
    )
    return {
        "system_id": system_id,
        "issue_index": issue_index,
        "issue_time_utc": _iso(issue_time),
        "modeled_issue_state_storage_m3": modeled_issue_storage_m3,
        "storage_scale_factor": storage_scale_factor,
        "scaled_issue_state_storage_m3": modeled_issue_storage_m3 * storage_scale_factor,
        "release_delta_m3s": release_delta_m3s,
        "effective_mean_release_delta_m3s_12h": mean_release_delta,
        "action_excitation_identifiable_12h": excitation_identifiable,
        "first_response_hour_at_1e_9_m3s_tolerance": (
            arrivals[0] if excitation_identifiable and arrivals else None
        ),
        "absolute_outlet_response_volume_before_5h_reference_fraction": (
            pre_reference_volume / absolute_volume
            if excitation_identifiable and absolute_volume > 0.0
            else None
        ),
        "response_rate_gain_12h": (
            target.incremental_outlet_mean_flow_m3s / mean_release_delta
            if excitation_identifiable
            else None
        ),
        "cumulative_incremental_action_volume_m3_12h": input_volume,
        "cumulative_incremental_outlet_volume_m3_12h": outlet_volume,
        "incremental_storage_m3_12h": target.final_incremental_storage_m3,
        "input_recovered_at_outlet_fraction_12h": recovery_fraction,
        "input_retained_in_storage_fraction_12h": storage_fraction,
        "mass_balance_residual_m3_12h": (
            target.final_incremental_storage_m3 + outlet_volume - input_volume
        ),
        "all_mass_balances_passed": result.all_mass_balances_passed,
        "signed_response_gate_passed": all(
            _signed_response_passes(release_delta_m3s, value) for value in result.steps
        ),
        "five_hour_reference_is_validated_travel_time": False,
        "future_outcome_observation_used": False,
    }


def _storage_sensitivity_summary(
    rows: list[dict[str, object]], storage_scale_factors: tuple[float, ...]
) -> dict[str, Any]:
    scale_summaries = {}
    for scale in storage_scale_factors:
        selected = [value for value in rows if value["storage_scale_factor"] == scale]
        identifiable = [
            value for value in selected if value["action_excitation_identifiable_12h"]
        ]
        scale_summaries[str(scale)] = {
            "requested_rollout_count": len(selected),
            "identifiable_action_excitation_rollout_count": len(identifiable),
            "median_first_response_hour": median(
                int(value["first_response_hour_at_1e_9_m3s_tolerance"])
                for value in identifiable
                if value["first_response_hour_at_1e_9_m3s_tolerance"] is not None
            ),
            "median_input_recovered_at_outlet_fraction_12h": median(
                float(value["input_recovered_at_outlet_fraction_12h"])
                for value in identifiable
            ),
            "median_input_retained_in_storage_fraction_12h": median(
                float(value["input_retained_in_storage_fraction_12h"])
                for value in identifiable
            ),
            "median_response_rate_gain_12h": median(
                float(value["response_rate_gain_12h"]) for value in identifiable
            ),
            "median_absolute_outlet_response_volume_before_5h_reference_fraction": median(
                float(
                    value[
                        "absolute_outlet_response_volume_before_5h_reference_fraction"
                    ]
                )
                for value in identifiable
            ),
        }

    grouped: dict[tuple[int, float], list[dict[str, object]]] = {}
    for row in rows:
        if not row["action_excitation_identifiable_12h"]:
            continue
        key = (int(row["issue_index"]), float(row["release_delta_m3s"]))
        grouped.setdefault(key, []).append(row)
    metric_fields = (
        "input_recovered_at_outlet_fraction_12h",
        "input_retained_in_storage_fraction_12h",
        "response_rate_gain_12h",
        "absolute_outlet_response_volume_before_5h_reference_fraction",
    )
    maximum_relative_deviation = {value: 0.0 for value in metric_fields}
    maximum_absolute_deviation = {value: 0.0 for value in metric_fields}
    first_response_spans = []
    first_response_undetected_pair_count = 0
    pair_count = 0
    for pair_rows in grouped.values():
        if {float(value["storage_scale_factor"]) for value in pair_rows} != set(
            storage_scale_factors
        ):
            raise ValueError("twin_state_sensitivity_incomplete_scale_pair")
        nominal = next(
            value for value in pair_rows if float(value["storage_scale_factor"]) == 1.0
        )
        pair_count += 1
        for metric in metric_fields:
            nominal_value = float(nominal[metric])
            deviations = [abs(float(value[metric]) - nominal_value) for value in pair_rows]
            maximum_absolute_deviation[metric] = max(
                maximum_absolute_deviation[metric], max(deviations)
            )
            maximum_relative_deviation[metric] = max(
                maximum_relative_deviation[metric],
                max(deviations) / max(abs(nominal_value), 1e-12),
            )
        arrivals = [
            int(value["first_response_hour_at_1e_9_m3s_tolerance"])
            for value in pair_rows
            if value["first_response_hour_at_1e_9_m3s_tolerance"] is not None
        ]
        if len(arrivals) == len(pair_rows):
            first_response_spans.append(max(arrivals) - min(arrivals))
        else:
            first_response_undetected_pair_count += 1
    return {
        "requested_comparison_pair_count": len(rows) // len(storage_scale_factors),
        "comparison_pair_count": pair_count,
        "zero_excitation_comparison_pair_count": (
            len(rows) // len(storage_scale_factors) - pair_count
        ),
        "scale_medians": scale_summaries,
        "maximum_absolute_deviation_from_nominal_by_pair": maximum_absolute_deviation,
        "maximum_relative_deviation_from_nominal_by_pair": maximum_relative_deviation,
        "maximum_first_response_hour_span_across_scales": max(
            first_response_spans, default=None
        ),
        "any_first_response_hour_changed_across_scales": any(first_response_spans),
        "first_response_undetected_pair_count": first_response_undetected_pair_count,
        "initial_storage_uncertainty_resolved": False,
    }


def _cross_system_robustness(
    *,
    center_rows: list[dict[str, object]],
    priest_rows: list[dict[str, object]],
) -> dict[str, Any]:
    def keyed(rows: list[dict[str, object]]) -> dict[tuple[int, float, float], dict[str, object]]:
        return {
            (
                int(value["issue_index"]),
                float(value["storage_scale_factor"]),
                float(value["release_delta_m3s"]),
            ): value
            for value in rows
        }

    center_all = keyed(center_rows)
    priest_all = keyed(priest_rows)
    if set(center_all) != set(priest_all):
        raise ValueError("twin_state_sensitivity_cross_system_axis_mismatch")
    comparable_keys = [
        key
        for key in center_all
        if center_all[key]["action_excitation_identifiable_12h"]
        and priest_all[key]["action_excitation_identifiable_12h"]
    ]
    center = {key: center_all[key] for key in comparable_keys}
    priest = {key: priest_all[key] for key in comparable_keys}
    if not comparable_keys:
        raise ValueError("twin_state_sensitivity_no_common_identifiable_action_axis")
    recovery_checks = [
        float(center[key]["input_recovered_at_outlet_fraction_12h"])
        < float(priest[key]["input_recovered_at_outlet_fraction_12h"])
        for key in center
    ]
    storage_checks = [
        float(center[key]["input_retained_in_storage_fraction_12h"])
        > float(priest[key]["input_retained_in_storage_fraction_12h"])
        for key in center
    ]
    gain_checks = [
        float(center[key]["response_rate_gain_12h"])
        < float(priest[key]["response_rate_gain_12h"])
        for key in center
    ]
    all_rankings = all(recovery_checks) and all(storage_checks) and all(gain_checks)
    return {
        "aligned_requested_comparison_count": len(center_all),
        "aligned_comparison_count": len(center),
        "excluded_zero_excitation_comparison_count": len(center_all) - len(center),
        "comparable_release_deltas_m3s": sorted({key[2] for key in comparable_keys}),
        "center_hill_lower_outlet_recovery_pass_count": sum(recovery_checks),
        "center_hill_higher_storage_retention_pass_count": sum(storage_checks),
        "center_hill_lower_response_gain_pass_count": sum(gain_checks),
        "all_three_partition_rankings_preserved": all_rankings,
        "tested_issue_state_storage_scaling_reverses_cross_system_contrast": not all_rankings,
        "interpretation": (
            "tested_issue_state_storage_uncertainty_does_not_explain_away_"
            "the_cross_system_response_contrast_on_common_identifiable_action_axes"
            if all_rankings
            else "cross_system_response_contrast_is_not_robust_to_tested_issue_state_storage"
        ),
        "causal_source_of_cross_system_difference_identified": False,
    }


def _range(values: list[float]) -> dict[str, float]:
    return {"minimum": min(values), "maximum": max(values), "span": max(values) - min(values)}


def _encode_rows(rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def main() -> int:
    args = parse_args()
    body, report = compile_twin_response_state_sensitivity_posthoc(
        protocol_path=args.protocol,
        input_report_path=args.input_report,
        stage32_gates_path=args.stage32_gates,
        stage32_ledger_path=args.stage32_ledger,
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
    print(f"responses_sha256={report['outputs']['responses']['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
