#!/usr/bin/env python3
"""Run the frozen Center Hill history-aware internal-boundary diagnostic."""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportConfig,
    CausalStateDependentManningForecastClosure,
    ForecastClosedBranchingTransportOperator,
    ObservedInternalBoundaryReplacement,
    ReachForcingSupport,
    StockState,
)

if __package__:
    from scripts.freeze_geotransport_center_hill_internal_boundary_development_protocol import (
        CORE_CODE_PATHS,
        CORE_HORIZONS,
        HORIZONS,
        SCENARIOS,
        SCHEMA as PROTOCOL_SCHEMA,
    )
    from scripts.run_geotransport_center_hill_graph_multigauge_development import (
        ACTIVATION_INDEX,
        DEFAULT_DEVELOPMENT_INPUT_REPORT,
        DEFAULT_MULTIGAUGE_REPORT,
        DEFAULT_PANEL_REPORT,
        DEFAULT_TOPOLOGY_REPORT,
        HOUR_COUNT,
        INTERIOR_FEATURE_ID,
        OUTLET_FEATURE_ID,
        START,
        _available_observations,
        _closure_config,
        _identity_parameters,
        _load_json,
        _parse_multigauge_hourly,
        _read_descriptor,
    )
    from scripts.run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
        REPO_ROOT,
        _geometry,
        _network,
        _read_npy,
        _read_verified,
    )
    from scripts.run_geotransport_center_hill_v2_outcome_free import compile_domain
    from scripts.train_geotransport_forecast_closure_center_hill_development import (
        _fields,
        _parse_panel,
    )
else:
    from freeze_geotransport_center_hill_internal_boundary_development_protocol import (
        CORE_CODE_PATHS,
        CORE_HORIZONS,
        HORIZONS,
        SCENARIOS,
        SCHEMA as PROTOCOL_SCHEMA,
    )
    from run_geotransport_center_hill_graph_multigauge_development import (
        ACTIVATION_INDEX,
        DEFAULT_DEVELOPMENT_INPUT_REPORT,
        DEFAULT_MULTIGAUGE_REPORT,
        DEFAULT_PANEL_REPORT,
        DEFAULT_TOPOLOGY_REPORT,
        HOUR_COUNT,
        INTERIOR_FEATURE_ID,
        OUTLET_FEATURE_ID,
        START,
        _available_observations,
        _closure_config,
        _identity_parameters,
        _load_json,
        _parse_multigauge_hourly,
        _read_descriptor,
    )
    from run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
        REPO_ROOT,
        _geometry,
        _network,
        _read_npy,
        _read_verified,
    )
    from run_geotransport_center_hill_v2_outcome_free import compile_domain
    from train_geotransport_forecast_closure_center_hill_development import (
        _fields,
        _parse_panel,
    )


DEFAULT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_internal_boundary_development_protocol.json"
)
DEFAULT_LEAD_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_lead_time_development_report.json"
)
DEFAULT_REFERENCE_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "smith_fork_internal_boundary_reference_report.json"
)
DEFAULT_PREDICTIONS = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_internal_boundary_development/"
    "predictions.csv"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_internal_boundary_development_report.json"
)
SCHEMA = "gwm.geotransport.center_hill_internal_boundary_development.v1"
LEAD_REPORT_SCHEMA = "gwm.geotransport.center_hill_lead_time_development.v1"
REFERENCE_SCHEMA = "gwm.geotransport.smith_fork_internal_boundary_reference.v1"
DEVELOPMENT_INPUT_SCHEMA = "gwm.geotransport.forecast_closure_development_inputs.v1"
MULTIGAUGE_SCHEMA = "gwm.geotransport.center_hill_multigauge_development_inputs.v1"
TOPOLOGY_SCHEMA = "gwm.geotransport.center_hill_v2_d5_full_subnetwork.v1"
PANEL_SCHEMA = "gwm.geotransport.center_hill_672h_development_panel.v1"
MAXIMUM_HORIZON = max(HORIZONS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--lead-report", type=Path, default=DEFAULT_LEAD_REPORT)
    parser.add_argument(
        "--reference-report", type=Path, default=DEFAULT_REFERENCE_REPORT
    )
    parser.add_argument(
        "--development-input-report",
        type=Path,
        default=DEFAULT_DEVELOPMENT_INPUT_REPORT,
    )
    parser.add_argument(
        "--multigauge-report", type=Path, default=DEFAULT_MULTIGAUGE_REPORT
    )
    parser.add_argument("--topology-report", type=Path, default=DEFAULT_TOPOLOGY_REPORT)
    parser.add_argument("--panel-report", type=Path, default=DEFAULT_PANEL_REPORT)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_diagnostic(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    lead_report_path: Path = DEFAULT_LEAD_REPORT,
    reference_report_path: Path = DEFAULT_REFERENCE_REPORT,
    development_input_report_path: Path = DEFAULT_DEVELOPMENT_INPUT_REPORT,
    multigauge_report_path: Path = DEFAULT_MULTIGAUGE_REPORT,
    topology_report_path: Path = DEFAULT_TOPOLOGY_REPORT,
    panel_report_path: Path = DEFAULT_PANEL_REPORT,
    prediction_output_path: Path = DEFAULT_PREDICTIONS,
) -> tuple[bytes, dict[str, Any]]:
    protocol_body, protocol = _load_json(protocol_path)
    lead_body, lead = _load_json(lead_report_path)
    reference_body, reference = _load_json(reference_report_path)
    development_body, development = _load_json(development_input_report_path)
    multigauge_body, multigauge = _load_json(multigauge_report_path)
    topology_body, topology = _load_json(topology_report_path)
    panel_report_body, panel_report = _load_json(panel_report_path)
    _validate_inputs(
        protocol=protocol,
        lead=lead,
        lead_body=lead_body,
        lead_report_path=lead_report_path,
        reference=reference,
        reference_body=reference_body,
        reference_report_path=reference_report_path,
        development=development,
        multigauge=multigauge,
        topology=topology,
        topology_body=topology_body,
        panel_report=panel_report,
    )

    network_body = _read_verified(topology["artifacts"]["full_subnetwork"])
    original_network = _network(json.loads(network_body)["network"])
    route_link_body = _read_verified(topology["artifacts"]["route_link_subset"])
    route_link_path = REPO_ROOT / topology["artifacts"]["route_link_subset"]["path"]
    geometry = _geometry(route_link_path, original_network, route_link_body)
    partial_fraction = float(
        protocol["gis_compilation_lock"]["central_downstream_fraction"]
    )
    partial_length = float(
        protocol["gis_compilation_lock"]["central_downstream_partial_length_m"]
    )
    gauge_index = original_network.feature_ids.index(INTERIOR_FEATURE_ID)
    effective_lengths = list(original_network.effective_lengths_m)
    effective_lengths[gauge_index] = partial_length
    cut_network = replace(
        original_network,
        network_id=f"{original_network.network_id}:smith-fork-cut-candidate",
        effective_lengths_m=tuple(effective_lengths),
        provenance_id=(
            f"{original_network.provenance_id}|smith-fork-nldi-linear-reference:"
            f"{hashlib.sha256(reference_body).hexdigest()}"
        ),
        evidence_level="candidate",
        admitted=False,
    )

    arrays = {
        name: _read_npy(descriptor)
        for name, descriptor in development["decoded_arrays"].items()
    }
    feature_ids = tuple(int(value) for value in arrays["feature_ids"])
    initial_storage = np.asarray(arrays["initial_storage_m3"], dtype=float)
    q_lateral = np.asarray(arrays["q_lateral_m3s"], dtype=float)
    if (
        feature_ids != cut_network.feature_ids
        or initial_storage.shape != (len(feature_ids),)
        or q_lateral.shape != (HOUR_COUNT, len(feature_ids))
    ):
        raise ValueError("internal_boundary_dynamic_axis_invalid")
    original_gauge_storage = float(initial_storage[gauge_index])
    initial_storage = initial_storage.copy()
    initial_storage[gauge_index] *= partial_fraction
    excluded_initial_storage = original_gauge_storage - float(
        initial_storage[gauge_index]
    )

    panel_body = _read_descriptor(panel_report["panel_artifact"])
    panel = _parse_panel(panel_body)
    observations_body = _read_descriptor(multigauge["hourly_observations"])
    observations = _parse_multigauge_hourly(observations_body)
    parent_prediction_body = _read_descriptor(lead["outputs"]["predictions"])
    parent_rows = _parent_rows(parent_prediction_body)

    prior_domain, prior_artifacts = compile_domain()
    mainstem_support = dict(
        zip(
            prior_domain.forcing_support_central.feature_ids,
            prior_domain.forcing_support_central.coverage_fractions,
            strict=True,
        )
    )
    coverage = [
        mainstem_support.get(feature_id, 1.0)
        for feature_id in cut_network.feature_ids
    ]
    coverage[gauge_index] = partial_fraction
    forcing_support = ReachForcingSupport(
        feature_ids=cut_network.feature_ids,
        coverage_fractions=tuple(coverage),
        support_method=(
            "D2 terminal support plus candidate Smith Fork downstream-length fraction"
        ),
        provenance_id=(
            "center-hill:internal-boundary-development:"
            f"reference={hashlib.sha256(reference_body).hexdigest()}"
        ),
        evidence_level="candidate",
        admitted_as_spatial_support=False,
    )
    transport = BranchingManningNetworkTransportOperator(
        cut_network,
        BranchingNetworkTransportConfig(
            timestep_seconds=3600.0,
            integration_substep_seconds=300.0,
            operator_form_admitted=True,
            allow_unadmitted_components_for_diagnostics=True,
        ),
    )
    identity_parameters = _identity_parameters(
        cut_network, geometry, initial_storage
    )
    wrapper = ForecastClosedBranchingTransportOperator(
        transport,
        CausalStateDependentManningForecastClosure(
            identity_parameters, _closure_config()
        ),
    )
    base_state = StockState(
        values=tuple(float(value) for value in initial_storage),
        unit="m3",
        provenance_id=(
            "nwm-v3-development-modeled-cut-initial-state:"
            f"{development['decoded_arrays']['initial_storage_m3']['sha256']}"
        ),
    )
    states = {
        name: StockState(
            values=base_state.values,
            unit="m3",
            provenance_id=f"internal-boundary-initial:{name}",
        )
        for name in SCENARIOS
    }
    action_index = cut_network.feature_ids.index(
        cut_network.action_entry_feature_ids[0]
    )
    warmup_mass_ratios = {name: [] for name in SCENARIOS}
    for hour in range(ACTIVATION_INDEX):
        issue_time = START + timedelta(hours=hour)
        available = _available_observations(observations, issue_time)
        outlet = tuple(
            value for value in available if value.feature_id == OUTLET_FEATURE_ID
        )
        smith = next(
            (
                value
                for value in available
                if value.feature_id == INTERIOR_FEATURE_ID
            ),
            None,
        )
        boundaries = _scenario_boundaries(smith, issue_time)
        action, forcing = _fields(
            panel, q_lateral, hour, action_index, len(feature_ids)
        )
        for name in SCENARIOS:
            result = wrapper.step(
                states[name],
                geometry,
                issue_time=issue_time,
                observations=outlet,
                action=action,
                forcing=forcing,
                forcing_support=forcing_support,
                internal_boundary=boundaries[name],
            )
            states[name] = result.transport.next_stock
            warmup_mass_ratios[name].append(_mass_ratio(result))

    mass_ratios = {name: [] for name in SCENARIOS}
    future_observation_update_counts = {name: 0 for name in SCENARIOS}
    cycling_ledgers = {
        name: {
            "observed_boundary_input_volume_m3": 0.0,
            "displaced_upstream_outflow_volume_m3": 0.0,
            "net_boundary_analysis_volume_m3": 0.0,
        }
        for name in SCENARIOS
    }
    missing_observed_boundary_issue_count = 0
    rows: list[dict[str, object]] = []
    last_issue_index = HOUR_COUNT - MAXIMUM_HORIZON
    for hour in range(ACTIVATION_INDEX, last_issue_index + 1):
        issue_time = START + timedelta(hours=hour)
        available = _available_observations(observations, issue_time)
        outlet = tuple(
            value for value in available if value.feature_id == OUTLET_FEATURE_ID
        )
        smith = next(
            (
                value
                for value in available
                if value.feature_id == INTERIOR_FEATURE_ID
            ),
            None,
        )
        if smith is None:
            missing_observed_boundary_issue_count += 1
        boundaries = _scenario_boundaries(smith, issue_time)
        forecasts = {name: {} for name in SCENARIOS}
        first_results: dict[str, Any] = {}
        for name in SCENARIOS:
            rollout_state = states[name]
            for lead_hour in range(1, MAXIMUM_HORIZON + 1):
                transition_hour = hour + lead_hour - 1
                transition_issue = issue_time + timedelta(hours=lead_hour - 1)
                action, forcing = _fields(
                    panel,
                    q_lateral,
                    transition_hour,
                    action_index,
                    len(feature_ids),
                )
                result = wrapper.step(
                    rollout_state,
                    geometry,
                    issue_time=transition_issue,
                    observations=outlet if lead_hour == 1 else (),
                    action=action,
                    forcing=forcing,
                    forcing_support=forcing_support,
                    internal_boundary=boundaries[name],
                )
                rollout_state = result.transport.next_stock
                mass_ratios[name].append(_mass_ratio(result))
                if lead_hour == 1:
                    first_results[name] = result
                    ledger = cycling_ledgers[name]
                    ledger["observed_boundary_input_volume_m3"] += (
                        result.transport.observed_internal_boundary_input_volume_m3
                    )
                    ledger["displaced_upstream_outflow_volume_m3"] += (
                        result.transport.displaced_upstream_outflow_volume_m3
                    )
                    ledger["net_boundary_analysis_volume_m3"] += (
                        result.transport.internal_boundary_net_analysis_volume_m3
                    )
                else:
                    future_observation_update_counts[name] += len(
                        result.closure.observation_updates
                    )
                if lead_hour in HORIZONS:
                    forecasts[name][lead_hour] = result.outlet_mean_flow_m3s
        for name in SCENARIOS:
            states[name] = first_results[name].transport.next_stock

        for horizon in HORIZONS:
            key = (_iso(issue_time), horizon)
            parent = parent_rows[key]
            if parent["target_support_end_utc"] != _iso(
                issue_time + timedelta(hours=horizon)
            ):
                raise ValueError("internal_boundary_parent_target_axis_invalid")
            rows.append(
                {
                    "issue_time_utc": _iso(issue_time),
                    "target_support_end_utc": parent["target_support_end_utc"],
                    "horizon_hours": horizon,
                    "track": (
                        "retrospective_oracle_action_forcing_archive_observation_replay"
                    ),
                    "observed_discharge_m3s": parent["observed_discharge_m3s"],
                    "causal_latency_matched_persistence_m3s": parent[
                        "causal_latency_matched_persistence_m3s"
                    ],
                    "zero_latency_archive_persistence_m3s": parent[
                        "zero_latency_archive_persistence_m3s"
                    ],
                    "parent_local_multi_gauge_m3s": parent[
                        "local_multi_gauge_m3s"
                    ],
                    **{
                        f"{name}_m3s": forecasts[name][horizon]
                        for name in SCENARIOS
                    },
                    "smith_fork_boundary_m3s": _optional(
                        None if smith is None else smith.discharge_m3s
                    ),
                    "smith_fork_observation_valid_at_utc": (
                        "" if smith is None else _iso(smith.valid_at)
                    ),
                    "future_observations_assimilated": False,
                }
            )

    prediction_body = _encode_rows(rows)
    metrics, scoring = _score(rows)
    per_horizon_gates = {
        str(horizon): {
            "candidate_beats_modeled_cut_rmse": (
                metrics[str(horizon)]["observed_internal_boundary"]["rmse_m3s"]
                < metrics[str(horizon)]["modeled_cut_control"]["rmse_m3s"]
            ),
            "candidate_beats_zero_boundary_rmse": (
                metrics[str(horizon)]["observed_internal_boundary"]["rmse_m3s"]
                < metrics[str(horizon)]["zero_internal_boundary"]["rmse_m3s"]
            ),
            "candidate_beats_parent_local_rmse": (
                metrics[str(horizon)]["observed_internal_boundary"]["rmse_m3s"]
                < metrics[str(horizon)]["parent_local_multi_gauge"]["rmse_m3s"]
            ),
            "candidate_beats_causal_persistence_rmse": (
                metrics[str(horizon)]["observed_internal_boundary"]["rmse_m3s"]
                < metrics[str(horizon)]["causal_latency_matched_persistence"][
                    "rmse_m3s"
                ]
            ),
        }
        for horizon in HORIZONS
    }
    for values in per_horizon_gates.values():
        values["accuracy_gate_passed"] = all(values.values())
    mass_passed = all(max(values) <= 1.0 for values in mass_ratios.values())
    core_accuracy_passed = all(
        per_horizon_gates[str(horizon)]["accuracy_gate_passed"]
        for horizon in CORE_HORIZONS
    )
    development_gate = mass_passed and core_accuracy_passed
    report = {
        "schema": SCHEMA,
        "status": "public_development_internal_boundary_diagnostic_complete",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": _artifact(protocol_path, protocol_body),
        "source_artifacts": {
            "lead_time_report": _artifact(lead_report_path, lead_body),
            "parent_lead_time_predictions": lead["outputs"]["predictions"],
            "internal_boundary_reference": _artifact(
                reference_report_path, reference_body
            ),
            "development_input_report": _artifact(
                development_input_report_path, development_body
            ),
            "multigauge_input_report": _artifact(
                multigauge_report_path, multigauge_body
            ),
            "topology_report": _artifact(topology_report_path, topology_body),
            "development_panel_report": _artifact(
                panel_report_path, panel_report_body
            ),
            "prior_mainstem_support": prior_artifacts["forcing_support"],
        },
        "outputs": {
            "predictions": _artifact(prediction_output_path, prediction_body)
        },
        "domain_compilation": {
            "feature_count": len(feature_ids),
            "boundary_feature_id": INTERIOR_FEATURE_ID,
            "original_effective_length_m": original_network.effective_lengths_m[
                gauge_index
            ],
            "cut_effective_length_m": cut_network.effective_lengths_m[gauge_index],
            "downstream_fraction": partial_fraction,
            "original_initial_storage_m3": original_gauge_storage,
            "cut_initial_storage_m3": float(initial_storage[gauge_index]),
            "excluded_upstream_segment_initial_storage_m3": excluded_initial_storage,
            "gauge_forcing_support_fraction": forcing_support.coverage_fractions[
                gauge_index
            ],
            "network_admitted": cut_network.admitted,
            "forcing_support_admitted": forcing_support.admitted_as_spatial_support,
            "diagnostic_only": True,
        },
        "metrics_by_horizon": metrics,
        "scoring": scoring,
        "registered_gates": {
            "per_horizon": per_horizon_gates,
            "core_horizons": list(CORE_HORIZONS),
            "mass_gate_passed": mass_passed,
            "all_core_horizons_accuracy_gate_passed": core_accuracy_passed,
            "development_gate_passed": development_gate,
        },
        "conservation": {
            "warmup_maximum_residual_to_tolerance_ratio": {
                name: max(values) for name, values in warmup_mass_ratios.items()
            },
            "branch_maximum_residual_to_tolerance_ratio": {
                name: max(values) for name, values in mass_ratios.items()
            },
            "unique_cycling_boundary_ledgers": cycling_ledgers,
            "all_scenarios_passed": mass_passed,
        },
        "diagnostics": {
            "missing_observed_boundary_issue_count": (
                missing_observed_boundary_issue_count
            ),
            "future_observation_update_count": future_observation_update_counts,
            "candidate_minus_modeled_cut_rmse_m3s_by_horizon": {
                str(horizon): (
                    metrics[str(horizon)]["observed_internal_boundary"]["rmse_m3s"]
                    - metrics[str(horizon)]["modeled_cut_control"]["rmse_m3s"]
                )
                for horizon in HORIZONS
            },
            "candidate_minus_parent_local_rmse_m3s_by_horizon": {
                str(horizon): (
                    metrics[str(horizon)]["observed_internal_boundary"]["rmse_m3s"]
                    - metrics[str(horizon)]["parent_local_multi_gauge"]["rmse_m3s"]
                )
                for horizon in HORIZONS
            },
        },
        "information_boundary": {
            "future_realized_action_used": True,
            "future_retrospective_q_lateral_used": True,
            "future_outlet_target_used_by_model": False,
            "future_smith_fork_observation_used_within_branch": False,
            "smith_fork_boundary_persisted_from_issue_time": True,
            "operational_observation_vintage_verified": False,
            "operational_forecast_claim_permitted": False,
        },
        "data_isolation": {
            "outlet_target_fitted_parameters": 0,
            "boundary_scale_fitted_from_outlet_target": False,
            "partial_length_selected_from_outlet_target": False,
            "missing_observations_imputed": False,
            "d3_outcomes_used": False,
            "two_system_blind_outcomes_used": False,
            "untouched_window_consumed": False,
        },
        "claim_boundary": {
            "internal_boundary_contract_implemented": True,
            "internal_boundary_reference_admitted": False,
            "history_aware_boundary_diagnostic_executed": True,
            "development_gate_passed": development_gate,
            "operational_forecast_evaluated": False,
            "lagged_graph_kernel_fitted": False,
            "graph_state_estimation_validated": False,
            "forecast_closure_validated": False,
            "geospatial_kernel_validated": False,
        },
    }
    if any(future_observation_update_counts.values()):
        raise RuntimeError("internal_boundary_future_observation_update_detected")
    if not mass_passed:
        raise RuntimeError("internal_boundary_development_conservation_failed")
    return prediction_body, report


def _validate_inputs(
    *,
    protocol: Mapping[str, Any],
    lead: Mapping[str, Any],
    lead_body: bytes,
    lead_report_path: Path,
    reference: Mapping[str, Any],
    reference_body: bytes,
    reference_report_path: Path,
    development: Mapping[str, Any],
    multigauge: Mapping[str, Any],
    topology: Mapping[str, Any],
    topology_body: bytes,
    panel_report: Mapping[str, Any],
) -> None:
    if (
        protocol.get("schema") != PROTOCOL_SCHEMA
        or protocol.get("status")
        != "frozen_before_internal_boundary_development_execution"
        or (protocol.get("scenario_lock") or {}).get("scenarios")
        != list(SCENARIOS)
        or (protocol.get("window_and_horizons") or {}).get(
            "all_horizons_hours"
        )
        != list(HORIZONS)
        or protocol["parent_evidence"]["lead_time_report"]
        != _artifact(lead_report_path, lead_body)
        or protocol["parent_evidence"]["internal_boundary_reference"]
        != _artifact(reference_report_path, reference_body)
    ):
        raise ValueError("internal_boundary_development_protocol_invalid")
    for path in CORE_CODE_PATHS:
        body = (REPO_ROOT / path).read_bytes()
        if protocol["core_code"][path] != _artifact(REPO_ROOT / path, body):
            raise ValueError("internal_boundary_core_code_changed_after_freeze")
    if (
        lead.get("schema") != LEAD_REPORT_SCHEMA
        or lead.get("status")
        != "public_development_lead_time_diagnostic_complete"
        or reference.get("schema") != REFERENCE_SCHEMA
        or reference.get("status")
        != "candidate_internal_boundary_reference_compiled"
        or (reference.get("claim_boundary") or {}).get(
            "linear_reference_admitted"
        )
        is not False
        or development.get("schema") != DEVELOPMENT_INPUT_SCHEMA
        or development.get("status") != "pass_public_development_inputs_acquired"
        or multigauge.get("schema") != MULTIGAUGE_SCHEMA
        or multigauge.get("status")
        != "pass_public_multigauge_development_inputs_acquired"
        or topology.get("schema") != TOPOLOGY_SCHEMA
        or topology.get("status") != "pass_full_incremental_subnetwork_compiled"
        or panel_report.get("schema") != PANEL_SCHEMA
        or panel_report.get("status")
        != "compiled_with_observation_gap_not_admitted"
    ):
        raise ValueError("internal_boundary_parent_input_invalid")
    if (
        development["topology_report"]["sha256"]
        != hashlib.sha256(topology_body).hexdigest()
        or multigauge["topology_report"]["sha256"]
        != hashlib.sha256(topology_body).hexdigest()
    ):
        raise ValueError("internal_boundary_topology_identity_invalid")


def _scenario_boundaries(
    smith: Any, issue_time: datetime
) -> dict[str, ObservedInternalBoundaryReplacement | None]:
    observed = None
    if smith is not None:
        observed = ObservedInternalBoundaryReplacement(
            feature_ids=(INTERIOR_FEATURE_ID,),
            values=(float(smith.discharge_m3s),),
            unit="m3 s-1",
            provenance_id=(
                f"{smith.provenance_id}|persisted-from-issue={_iso(issue_time)}"
            ),
            evidence_level="candidate",
            admitted=False,
            archive_revised=True,
            operational_vintage_verified=False,
        )
    zero = ObservedInternalBoundaryReplacement(
        feature_ids=(INTERIOR_FEATURE_ID,),
        values=(0.0,),
        unit="m3 s-1",
        provenance_id=f"zero-internal-boundary-control:{_iso(issue_time)}",
        evidence_level="candidate",
        admitted=False,
        archive_revised=False,
        operational_vintage_verified=False,
    )
    return {
        "observed_internal_boundary": observed,
        "modeled_cut_control": None,
        "zero_internal_boundary": zero,
    }


def _parent_rows(body: bytes) -> dict[tuple[str, int], dict[str, str]]:
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
    result = {
        (row["issue_time_utc"], int(row["horizon_hours"])): row
        for row in rows
    }
    if len(rows) != 2400 or len(result) != len(rows):
        raise ValueError("internal_boundary_parent_prediction_axis_invalid")
    return result


def _score(
    rows: list[dict[str, object]],
) -> tuple[dict[str, dict[str, dict[str, float]]], dict[str, Any]]:
    names = (
        *SCENARIOS,
        "parent_local_multi_gauge",
        "causal_latency_matched_persistence",
        "zero_latency_archive_persistence",
    )
    metrics: dict[str, dict[str, dict[str, float]]] = {}
    counts: dict[str, int] = {}
    omitted: dict[str, list[str]] = {}
    for horizon in HORIZONS:
        horizon_rows = [row for row in rows if row["horizon_hours"] == horizon]
        complete: list[dict[str, object]] = []
        missing: list[str] = []
        for row in horizon_rows:
            values = [row["observed_discharge_m3s"]]
            values.extend(row[f"{name}_m3s"] for name in names)
            if any(value in (None, "") for value in values):
                missing.append(str(row["target_support_end_utc"]))
            else:
                complete.append(row)
        observed = np.asarray(
            [float(row["observed_discharge_m3s"]) for row in complete],
            dtype=float,
        )
        if observed.size == 0:
            raise ValueError("internal_boundary_common_support_empty")
        metrics[str(horizon)] = {
            name: _metrics(
                observed,
                np.asarray(
                    [float(row[f"{name}_m3s"]) for row in complete], dtype=float
                ),
            )
            for name in names
        }
        counts[str(horizon)] = len(complete)
        omitted[str(horizon)] = missing
    return metrics, {
        "row_count": len(rows),
        "issue_count": len(rows) // len(HORIZONS),
        "common_complete_sample_count_by_horizon": counts,
        "omitted_target_support_end_utc_by_horizon": omitted,
        "common_complete_case_mask_per_horizon": True,
        "missing_values_imputed": False,
    }


def _metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    if observed.shape != predicted.shape or observed.size == 0:
        raise ValueError("internal_boundary_metric_support_invalid")
    error = predicted - observed
    denominator = float(np.sum((observed - observed.mean()) ** 2))
    return {
        "sample_count": int(observed.size),
        "rmse_m3s": float(np.sqrt(np.mean(error**2))),
        "mae_m3s": float(np.mean(np.abs(error))),
        "bias_m3s": float(np.mean(error)),
        "nse": float(1.0 - np.sum(error**2) / denominator),
    }


def _mass_ratio(result: Any) -> float:
    return abs(result.forecast_cycle_mass_balance_residual_m3) / (
        result.forecast_cycle_mass_tolerance_m3
    )


def _encode_rows(rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


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


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _optional(value: Any) -> Any:
    return None if value is None else float(value)


def _json_body(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def main() -> int:
    args = parse_args()
    if args.predictions.exists() or args.report.exists():
        raise ValueError("internal_boundary_development_refuses_overwrite")
    predictions, report = compile_diagnostic(
        protocol_path=args.protocol,
        lead_report_path=args.lead_report,
        reference_report_path=args.reference_report,
        development_input_report_path=args.development_input_report,
        multigauge_report_path=args.multigauge_report,
        topology_report_path=args.topology_report,
        panel_report_path=args.panel_report,
        prediction_output_path=args.predictions,
    )
    args.predictions.parent.mkdir(parents=True, exist_ok=True)
    args.predictions.write_bytes(predictions)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(_json_body(report))
    print(args.report)
    for horizon in HORIZONS:
        metrics = report["metrics_by_horizon"][str(horizon)]
        print(
            f"h={horizon}:boundary={metrics['observed_internal_boundary']['rmse_m3s']:.6f}:"
            f"modeled={metrics['modeled_cut_control']['rmse_m3s']:.6f}:"
            f"local={metrics['parent_local_multi_gauge']['rmse_m3s']:.6f}:"
            f"persistence={metrics['causal_latency_matched_persistence']['rmse_m3s']:.6f}"
        )
    print(
        f"development_gate_passed={report['registered_gates']['development_gate_passed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
