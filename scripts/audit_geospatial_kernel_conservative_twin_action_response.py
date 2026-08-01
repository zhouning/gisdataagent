#!/usr/bin/env python3
"""Audit conservative twin-rollout action responses on two historical systems."""

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
    ConservativeTwinActionStepInput,
    ConservativeTwinManningActionResponseKernel,
)
from data_agent.uwm.geospatial_kernel_v2.contracts import (
    ActionBoundaryFlux,
    ForcingFlux,
    ReachForcingSupport,
    StockState,
)

if __package__:
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
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "geospatial_kernel_conservative_twin_action_response_posthoc/responses.csv"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_conservative_twin_action_response_posthoc_report.json"
)
PARAMETER_PATH = REPO_ROOT / ("data/geotransport_v0_1/kernel_innovation_candidate/parameters.json")
OPERATOR_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/conservative_twin_action_response.py"
)
SCHEMA = "gwm.geotransport.conservative_twin_action_response_posthoc.v1"
SYSTEM_IDS = ("center_hill", "j_percy_priest")
ISSUE_INDICES = (0, 168, 336, 504)
HORIZONS_HOURS = (1, 3, 6, 12)
RELEASE_DELTAS_M3S = (-50.0, -10.0, 10.0, 50.0)
EMPIRICAL_MINIMUM_LAG_HOURS = 5
TIMESTEP_SECONDS = 3600.0
SUBSTEP_SECONDS = 300.0
RESPONSE_ZERO_TOLERANCE_M3S = 1e-9


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--input-report", type=Path, default=DEFAULT_INPUT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_conservative_twin_action_response_posthoc(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    input_report_path: Path = DEFAULT_INPUT_REPORT,
    output_path: Path = DEFAULT_OUTPUT,
    issue_indices: tuple[int, ...] = ISSUE_INDICES,
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
        or inputs.get("protocol", {}).get("sha256") != hashlib.sha256(protocol_body).hexdigest()
    ):
        raise ValueError("conservative_twin_source_contract_invalid")
    selected = tuple(issue_indices)
    if (
        not selected
        or tuple(sorted(set(selected))) != selected
        or any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            or value + max(HORIZONS_HOURS) > 672
            for value in selected
        )
    ):
        raise ValueError("conservative_twin_issue_indices_invalid")

    parameter_body = PARAMETER_PATH.read_bytes()
    parameter_payload = json.loads(parameter_body)
    learned_action_coefficient = float(parameter_payload["action_change_coefficient"])
    rows: list[dict[str, object]] = []
    system_reports: dict[str, dict[str, Any]] = {}
    for system_id in SYSTEM_IDS:
        system_rows, system_report = _evaluate_system(
            system_id=system_id,
            lock=protocol["systems"][system_id],
            inputs=inputs["systems"][system_id],
            issue_indices=selected,
            learned_action_coefficient=learned_action_coefficient,
        )
        rows.extend(system_rows)
        system_reports[system_id] = system_report

    csv_body = _encode_rows(rows)
    structural_passed = all(
        value["structural_gates"]["all_structural_gates_passed"]
        for value in system_reports.values()
    )
    now = generated_at or datetime.now(UTC)
    if not _aware(now):
        raise ValueError("conservative_twin_generated_at_must_be_aware")
    evaluator_body = Path(__file__).read_bytes()
    operator_body = OPERATOR_PATH.read_bytes()
    report = {
        "schema": SCHEMA,
        "status": "mechanistic_twin_response_posthoc_complete_not_promoted",
        "generated_at": now.astimezone(UTC).isoformat(),
        "design": {
            "systems": list(SYSTEM_IDS),
            "issue_indices": list(selected),
            "issue_stride_hours": (None if len(selected) < 2 else selected[1] - selected[0]),
            "forecast_horizons_hours": list(HORIZONS_HOURS),
            "release_deltas_m3s": list(RELEASE_DELTAS_M3S),
            "empirical_minimum_lag_hours_diagnostic": (EMPIRICAL_MINIMUM_LAG_HOURS),
            "shared_initial_reach_storage_per_pair": True,
            "shared_distributed_forcing_per_pair": True,
            "future_archived_release_used_as_declared_scenario_schedule": True,
            "operational_action_schedule_vintage_verified": False,
            "new_fitted_parameter_count": 0,
        },
        "source_artifacts": {
            "blind_validation_protocol": _artifact(protocol_path, protocol_body),
            "blind_validation_input_report": _artifact(input_report_path, input_body),
            "frozen_action_innovation_parameters": _artifact(PARAMETER_PATH, parameter_body),
        },
        "implementation_artifacts": {
            "conservative_twin_operator": _artifact(OPERATOR_PATH, operator_body),
            "evaluator": _artifact(Path(__file__), evaluator_body),
        },
        "reference_action_change_coefficient": learned_action_coefficient,
        "systems": system_reports,
        "aggregate_gates": {
            "two_system_structural_gate_passed": structural_passed,
            "fresh_prospective_validation_passed": False,
            "mechanistic_candidate_promotion_gate_passed": False,
        },
        "outputs": {"responses": _artifact(output_path, csv_body)},
        "information_boundary": {
            "usgs_outcome_files_opened": False,
            "outcome_values_loaded": False,
            "outcome_columns_accepted": False,
            "historical_archived_actions_loaded": True,
            "nwm_v3_retrospective_forcing_loaded": True,
            "initial_reach_storage_is_modeled_not_observed": True,
        },
        "diagnostic_interpretation": {
            "action_response_now_has_explicit_reach_storage_continuity": True,
            "response_attenuation_can_be_partitioned_into_outlet_and_storage": True,
            "reservoir_storage_required_for_this_routing_diagnostic": False,
            "predictive_accuracy_evaluated": False,
            "counterfactual_effect_identified_from_outcomes": False,
        },
        "claim_boundary": {
            "mechanistic_action_response_implemented": True,
            "counterfactual_release_effect_causally_validated": False,
            "hydrodynamic_response_validated": False,
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
    issue_indices: tuple[int, ...],
    learned_action_coefficient: float,
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
        raise ValueError(f"conservative_twin_{system_id}_network_lock_mismatch")
    arrays = {name: _read_npy(descriptor) for name, descriptor in inputs["decoded_arrays"].items()}
    feature_ids = tuple(int(value) for value in arrays["feature_ids"])
    q_lateral = np.asarray(arrays["q_lateral_m3s"], dtype=float)
    initial_storage = np.asarray(arrays["initial_storage_m3"], dtype=float)
    if (
        feature_ids != network.feature_ids
        or q_lateral.shape != (672, len(feature_ids))
        or initial_storage.shape != (len(feature_ids),)
    ):
        raise ValueError(f"conservative_twin_{system_id}_dynamic_axis_mismatch")
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
        provenance_id=f"conservative-twin:{system_id}:forcing-support",
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
    first_arrivals: list[int | None] = []
    twelve_hour_gains: list[float] = []
    twelve_hour_recovery: list[float] = []
    twelve_hour_storage: list[float] = []
    twelve_hour_partition_residual_fractions: list[float] = []
    pre_lag_absolute_volume = 0.0
    total_absolute_volume = 0.0
    scenario_outlets: dict[tuple[int, int], list[float]] = {}
    baseline_outlets: dict[tuple[int, int], float] = {}
    for hour in range(max(issue_indices) + 1):
        issue_time = start + timedelta(hours=hour)
        if hour in issue_set:
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
                    canonical_state,
                    geometry,
                    rollout_steps,
                    issue_time=issue_time,
                )
                all_steps.extend(result.steps)
                signed_steps.extend((release_delta, value) for value in result.steps)
                arrivals = [
                    index + 1
                    for index, value in enumerate(result.steps)
                    if abs(value.incremental_outlet_mean_flow_m3s) > RESPONSE_ZERO_TOLERANCE_M3S
                ]
                first_arrivals.append(arrivals[0] if arrivals else None)
                for index, value in enumerate(result.steps):
                    volume = abs(value.incremental_outlet_volume_m3)
                    total_absolute_volume += volume
                    if index < EMPIRICAL_MINIMUM_LAG_HOURS - 1:
                        pre_lag_absolute_volume += volume
                for horizon in HORIZONS_HOURS:
                    prefix = result.steps[:horizon]
                    target = prefix[-1]
                    input_volume = float(
                        sum(value.incremental_action_input_volume_m3 for value in prefix)
                    )
                    outlet_volume = float(
                        sum(value.incremental_outlet_volume_m3 for value in prefix)
                    )
                    mean_release_delta = input_volume / (horizon * TIMESTEP_SECONDS)
                    rate_gain = (
                        None
                        if mean_release_delta == 0.0
                        else target.incremental_outlet_mean_flow_m3s / mean_release_delta
                    )
                    recovered_fraction = (
                        None if input_volume == 0.0 else outlet_volume / input_volume
                    )
                    storage_fraction = (
                        None
                        if input_volume == 0.0
                        else target.final_incremental_storage_m3 / input_volume
                    )
                    if horizon == 12 and rate_gain is not None:
                        twelve_hour_gains.append(rate_gain)
                        twelve_hour_recovery.append(float(recovered_fraction))
                        twelve_hour_storage.append(float(storage_fraction))
                        twelve_hour_partition_residual_fractions.append(
                            abs(target.final_incremental_storage_m3 + outlet_volume - input_volume)
                            / max(abs(input_volume), 1.0)
                        )
                    scenario_outlets.setdefault((hour, horizon), []).append(
                        target.scenario_outlet_mean_flow_m3s
                    )
                    baseline_outlets[(hour, horizon)] = target.baseline_outlet_mean_flow_m3s
                    rows.append(
                        {
                            "system_id": system_id,
                            "issue_index": hour,
                            "issue_time_utc": _iso(issue_time),
                            "release_delta_m3s": release_delta,
                            "forecast_horizon_hours": horizon,
                            "effective_mean_release_delta_m3s": mean_release_delta,
                            "baseline_outlet_m3s": (target.baseline_outlet_mean_flow_m3s),
                            "scenario_outlet_m3s": (target.scenario_outlet_mean_flow_m3s),
                            "outlet_response_m3s": (target.incremental_outlet_mean_flow_m3s),
                            "response_rate_gain": rate_gain,
                            "cumulative_incremental_action_volume_m3": (input_volume),
                            "cumulative_incremental_outlet_volume_m3": (outlet_volume),
                            "incremental_storage_m3": (target.final_incremental_storage_m3),
                            "input_recovered_at_outlet_fraction": recovered_fraction,
                            "input_retained_in_storage_fraction": storage_fraction,
                            "cumulative_mass_balance_residual_m3": (
                                target.final_incremental_storage_m3 + outlet_volume - input_volume
                            ),
                            "future_outcome_observation_used": False,
                            "operational_action_schedule_vintage_verified": False,
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

    sign_checks = [
        _signed_response_passes(release_delta, value) for release_delta, value in signed_steps
    ]
    monotonic_checks = [
        all(
            left <= right + RESPONSE_ZERO_TOLERANCE_M3S
            for left, right in zip(
                (values[0], values[1], baseline_outlets[key], values[2]),
                (values[1], baseline_outlets[key], values[2], values[3]),
                strict=True,
            )
        )
        for key, values in scenario_outlets.items()
    ]
    mass_checks = [
        value.individual_mass_balances_passed and value.differential_mass_balance_passed
        for value in all_steps
    ]
    structural = {
        "mass_balance_check_count": len(mass_checks),
        "mass_balance_pass_count": sum(mass_checks),
        "all_mass_balances_passed": all(mass_checks),
        "signed_response_check_count": len(sign_checks),
        "signed_response_pass_count": sum(sign_checks),
        "signed_response_gate_passed": all(sign_checks),
        "release_ordering_check_count": len(monotonic_checks),
        "release_ordering_pass_count": sum(monotonic_checks),
        "release_ordering_gate_passed": all(monotonic_checks),
    }
    structural["all_structural_gates_passed"] = all(
        (
            structural["all_mass_balances_passed"],
            structural["signed_response_gate_passed"],
            structural["release_ordering_gate_passed"],
        )
    )
    finite_arrivals = [value for value in first_arrivals if value is not None]
    return rows, {
        "system_id": system_id,
        "network": {
            "feature_count": len(feature_ids),
            "action_entry_feature_id": network.action_entry_feature_ids[0],
            "outlet_feature_id": network.outlet_feature_id,
            "initial_network_storage_m3": float(initial_storage.sum()),
            "initial_state_ground_truth": False,
        },
        "execution": {
            "issue_count": len(issue_indices),
            "paired_rollout_count": len(issue_indices) * len(RELEASE_DELTAS_M3S),
            "paired_step_count": len(all_steps),
            "reported_horizon_row_count": len(rows),
        },
        "structural_gates": structural,
        "temporal_response_diagnostic": {
            "first_response_arrival_minimum_hours": min(finite_arrivals),
            "first_response_arrival_median_hours": median(finite_arrivals),
            "first_response_arrival_maximum_hours": max(finite_arrivals),
            "response_zero_tolerance_m3s": RESPONSE_ZERO_TOLERANCE_M3S,
            "empirical_minimum_lag_hours_reference": EMPIRICAL_MINIMUM_LAG_HOURS,
            "absolute_outlet_response_volume_before_empirical_lag_fraction": (
                0.0
                if total_absolute_volume == 0.0
                else pre_lag_absolute_volume / total_absolute_volume
            ),
            "temporal_alignment_promoted": False,
        },
        "twelve_hour_partition": {
            "median_response_rate_gain": median(twelve_hour_gains),
            "reference_learned_action_change_coefficient": (learned_action_coefficient),
            "median_input_recovered_at_outlet_fraction": median(twelve_hour_recovery),
            "median_input_retained_in_storage_fraction": median(twelve_hour_storage),
            "partition_roundoff_fraction": (
                median(twelve_hour_recovery) + median(twelve_hour_storage) - 1.0
            ),
            "maximum_absolute_partition_residual_fraction": max(
                twelve_hour_partition_residual_fractions
            ),
        },
        "claim_boundary": {
            "two_schedule_mechanistic_response_computed": True,
            "outcomes_used": False,
            "predictive_accuracy_scored": False,
            "causal_effect_validated": False,
        },
    }


def _signed_response_passes(release_delta_m3s: float, value) -> bool:
    response = value.incremental_outlet_mean_flow_m3s
    if release_delta_m3s > 0.0:
        return response >= -RESPONSE_ZERO_TOLERANCE_M3S
    if release_delta_m3s < 0.0:
        return response <= RESPONSE_ZERO_TOLERANCE_M3S
    return abs(response) <= RESPONSE_ZERO_TOLERANCE_M3S


def _scenario_steps(
    *,
    issue_time: datetime,
    issue_index: int,
    release_delta_m3s: float,
    actions: Mapping[datetime, float],
    q_lateral: np.ndarray,
    feature_ids: tuple[int, ...],
    action_index: int,
    forcing_support: ReachForcingSupport,
    system_id: str,
) -> tuple[ConservativeTwinActionStepInput, ...]:
    rows = []
    for offset in range(max(HORIZONS_HOURS)):
        support_start = issue_time + timedelta(hours=offset)
        baseline_release = float(actions[support_start])
        scenario_release = max(0.0, baseline_release + release_delta_m3s)
        baseline_values = np.zeros(len(feature_ids), dtype=float)
        scenario_values = np.zeros(len(feature_ids), dtype=float)
        baseline_values[action_index] = baseline_release
        scenario_values[action_index] = scenario_release
        rows.append(
            ConservativeTwinActionStepInput(
                support_start=support_start,
                support_end=support_start + timedelta(hours=1),
                inputs_available_at=issue_time,
                baseline_action=ActionBoundaryFlux(
                    values=tuple(float(value) for value in baseline_values),
                    unit="m3 s-1",
                    provenance_id=(f"{system_id}:baseline:{issue_index}:{offset}"),
                ),
                scenario_action=ActionBoundaryFlux(
                    values=tuple(float(value) for value in scenario_values),
                    unit="m3 s-1",
                    provenance_id=(
                        f"{system_id}:scenario:{release_delta_m3s}:{issue_index}:{offset}"
                    ),
                ),
                forcing=ForcingFlux(
                    values=tuple(float(value) for value in q_lateral[issue_index + offset]),
                    unit="m3 s-1",
                    provenance_id=(f"nwm-v3:{system_id}:common-q-lateral:{issue_index + offset}"),
                    modeled=True,
                ),
                forcing_support=forcing_support,
            )
        )
    return tuple(rows)


def _advance_baseline_state(
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
    hour: int,
) -> StockState:
    action_values = np.zeros(len(feature_ids), dtype=float)
    action_values[action_index] = action_release_m3s
    result = operator.step(
        state,
        geometry,
        action=ActionBoundaryFlux(
            values=tuple(float(value) for value in action_values),
            unit="m3 s-1",
            provenance_id=f"{system_id}:state-spinup-action:{hour}",
        ),
        forcing=ForcingFlux(
            values=tuple(float(value) for value in forcing_values),
            unit="m3 s-1",
            provenance_id=f"nwm-v3:{system_id}:state-spinup-forcing:{hour}",
            modeled=True,
        ),
        forcing_support=forcing_support,
    )
    return StockState(
        values=result.next_stock.values,
        unit="m3",
        provenance_id=(f"{result.next_stock.provenance_id}|conservative-twin-spinup:{hour}"),
    )


def _artifact(path: Path, body: bytes) -> dict[str, object]:
    try:
        display = path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        display = path.resolve().as_posix()
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


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
    body, report = compile_conservative_twin_action_response_posthoc(
        protocol_path=args.protocol,
        input_report_path=args.input_report,
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
