#!/usr/bin/env python3
"""Execute the frozen Center Hill multi-horizon development diagnostic."""

from __future__ import annotations

import argparse
import csv
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
    GraphStateUpdateParameters,
    ReachForcingSupport,
    StockState,
)

if __package__:
    from scripts.freeze_geotransport_center_hill_lead_time_development_protocol import (
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
        END,
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
    from freeze_geotransport_center_hill_lead_time_development_protocol import (
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
        END,
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
    "center_hill_lead_time_development_protocol.json"
)
DEFAULT_GRAPH_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_graph_multigauge_development_report.json"
)
DEFAULT_PREDICTIONS = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_lead_time_development/"
    "predictions.csv"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_lead_time_development_report.json"
)
SCHEMA = "gwm.geotransport.center_hill_lead_time_development.v1"
GRAPH_PARAMETER_ARTIFACT_SCHEMA = (
    "gwm.geotransport.center_hill_graph_state_update_parameter_artifact.v1"
)
GRAPH_PARAMETER_SCHEMA = "gwm.geospatial_kernel.graph_state_update_parameters.v1"
DEVELOPMENT_INPUT_SCHEMA = "gwm.geotransport.forecast_closure_development_inputs.v1"
MULTIGAUGE_SCHEMA = "gwm.geotransport.center_hill_multigauge_development_inputs.v1"
TOPOLOGY_SCHEMA = "gwm.geotransport.center_hill_v2_d5_full_subnetwork.v1"
PANEL_SCHEMA = "gwm.geotransport.center_hill_672h_development_panel.v1"
MAXIMUM_HORIZON = max(HORIZONS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--graph-report", type=Path, default=DEFAULT_GRAPH_REPORT)
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
    graph_report_path: Path = DEFAULT_GRAPH_REPORT,
    development_input_report_path: Path = DEFAULT_DEVELOPMENT_INPUT_REPORT,
    multigauge_report_path: Path = DEFAULT_MULTIGAUGE_REPORT,
    topology_report_path: Path = DEFAULT_TOPOLOGY_REPORT,
    panel_report_path: Path = DEFAULT_PANEL_REPORT,
    prediction_output_path: Path = DEFAULT_PREDICTIONS,
) -> tuple[bytes, dict[str, Any]]:
    protocol_body, protocol = _load_json(protocol_path)
    graph_body, graph = _load_json(graph_report_path)
    development_body, development = _load_json(development_input_report_path)
    multigauge_body, multigauge = _load_json(multigauge_report_path)
    topology_body, topology = _load_json(topology_report_path)
    panel_report_body, panel_report = _load_json(panel_report_path)
    _validate_inputs(
        protocol=protocol,
        protocol_body=protocol_body,
        graph=graph,
        graph_body=graph_body,
        graph_report_path=graph_report_path,
        development=development,
        multigauge=multigauge,
        topology=topology,
        topology_body=topology_body,
        panel_report=panel_report,
    )

    network_body = _read_verified(topology["artifacts"]["full_subnetwork"])
    network = _network(json.loads(network_body)["network"])
    route_link_body = _read_verified(topology["artifacts"]["route_link_subset"])
    route_link_path = REPO_ROOT / topology["artifacts"]["route_link_subset"]["path"]
    geometry = _geometry(route_link_path, network, route_link_body)
    arrays = {
        name: _read_npy(descriptor)
        for name, descriptor in development["decoded_arrays"].items()
    }
    feature_ids = tuple(int(value) for value in arrays["feature_ids"])
    initial_storage = np.asarray(arrays["initial_storage_m3"], dtype=float)
    q_lateral = np.asarray(arrays["q_lateral_m3s"], dtype=float)
    if (
        feature_ids != network.feature_ids
        or initial_storage.shape != (len(feature_ids),)
        or q_lateral.shape != (HOUR_COUNT, len(feature_ids))
    ):
        raise ValueError("lead_time_dynamic_axis_invalid")

    panel_body = _read_descriptor(panel_report["panel_artifact"])
    panel = _parse_panel(panel_body)
    multigauge_hourly_body = _read_descriptor(multigauge["hourly_observations"])
    observations = _parse_multigauge_hourly(multigauge_hourly_body)
    graph_parameter_body = _read_descriptor(graph["outputs"]["graph_parameters"])
    graph_parameters = _parse_graph_parameters(graph_parameter_body)
    if graph_parameters.feature_ids != network.feature_ids:
        raise ValueError("lead_time_graph_parameter_axis_invalid")

    prior_domain, prior_artifacts = compile_domain()
    mainstem_support = dict(
        zip(
            prior_domain.forcing_support_central.feature_ids,
            prior_domain.forcing_support_central.coverage_fractions,
            strict=True,
        )
    )
    forcing_support = ReachForcingSupport(
        feature_ids=network.feature_ids,
        coverage_fractions=tuple(
            mainstem_support.get(feature_id, 1.0)
            for feature_id in network.feature_ids
        ),
        support_method="D2 terminal support plus complete branch support",
        provenance_id="center-hill:lead-time-development:forcing-support",
        evidence_level="derived",
        admitted_as_spatial_support=True,
    )
    transport = BranchingManningNetworkTransportOperator(
        network,
        BranchingNetworkTransportConfig(
            timestep_seconds=3600.0,
            integration_substep_seconds=300.0,
            operator_form_admitted=True,
            allow_unadmitted_components_for_diagnostics=True,
        ),
    )
    identity_parameters = _identity_parameters(network, geometry, initial_storage)
    config = _closure_config()
    local_wrapper = ForecastClosedBranchingTransportOperator(
        transport,
        CausalStateDependentManningForecastClosure(identity_parameters, config),
    )
    graph_wrapper = ForecastClosedBranchingTransportOperator(
        transport,
        CausalStateDependentManningForecastClosure(
            identity_parameters,
            config,
            graph_state_update_parameters=graph_parameters,
        ),
    )
    wrappers = {
        "graph_multi_gauge": graph_wrapper,
        "local_multi_gauge": local_wrapper,
        "outlet_only": local_wrapper,
    }

    baseline_state = StockState(
        values=tuple(float(value) for value in initial_storage),
        unit="m3",
        provenance_id=(
            "nwm-v3-development-modeled-initial-state:"
            f"{development['decoded_arrays']['initial_storage_m3']['sha256']}"
        ),
    )
    action_index = network.feature_ids.index(network.action_entry_feature_ids[0])
    warmup_mass_ratios: list[float] = []
    for hour in range(ACTIVATION_INDEX):
        issue_time = START + timedelta(hours=hour)
        available = _available_observations(observations, issue_time)
        outlet = tuple(
            value for value in available if value.feature_id == OUTLET_FEATURE_ID
        )
        action, forcing = _fields(
            panel, q_lateral, hour, action_index, len(feature_ids)
        )
        result = local_wrapper.step(
            baseline_state,
            geometry,
            issue_time=issue_time,
            observations=outlet,
            action=action,
            forcing=forcing,
            forcing_support=forcing_support,
        )
        baseline_state = result.transport.next_stock
        warmup_mass_ratios.append(_mass_ratio(result))

    states = {
        name: StockState(
            values=baseline_state.values,
            unit="m3",
            provenance_id=f"lead-time-shared-activation-state:{name}",
        )
        for name in SCENARIOS
    }
    mass_ratios = {name: [] for name in SCENARIOS}
    future_observation_update_counts = {name: 0 for name in SCENARIOS}
    issue_observation_update_counts = {name: 0 for name in SCENARIOS}
    rows: list[dict[str, object]] = []
    last_issue_index = HOUR_COUNT - MAXIMUM_HORIZON
    for hour in range(ACTIVATION_INDEX, last_issue_index + 1):
        issue_time = START + timedelta(hours=hour)
        available = _available_observations(observations, issue_time)
        outlet = tuple(
            value for value in available if value.feature_id == OUTLET_FEATURE_ID
        )
        scenario_observations = {
            "graph_multi_gauge": tuple(
                sorted(available, key=lambda value: value.feature_id)
            ),
            "local_multi_gauge": tuple(
                sorted(available, key=lambda value: value.feature_id)
            ),
            "outlet_only": outlet,
        }
        forecasts: dict[str, dict[int, float]] = {
            name: {} for name in SCENARIOS
        }
        first_results: dict[str, Any] = {}
        for name in SCENARIOS:
            rollout_state = states[name]
            for lead in range(1, MAXIMUM_HORIZON + 1):
                transition_hour = hour + lead - 1
                transition_issue = issue_time + timedelta(hours=lead - 1)
                action, forcing = _fields(
                    panel,
                    q_lateral,
                    transition_hour,
                    action_index,
                    len(feature_ids),
                )
                step_observations = (
                    scenario_observations[name] if lead == 1 else ()
                )
                result = wrappers[name].step(
                    rollout_state,
                    geometry,
                    issue_time=transition_issue,
                    observations=step_observations,
                    action=action,
                    forcing=forcing,
                    forcing_support=forcing_support,
                )
                rollout_state = result.transport.next_stock
                mass_ratios[name].append(_mass_ratio(result))
                if lead == 1:
                    first_results[name] = result
                    issue_observation_update_counts[name] += len(
                        result.closure.observation_updates
                    )
                else:
                    future_observation_update_counts[name] += len(
                        result.closure.observation_updates
                    )
                if lead in HORIZONS:
                    forecasts[name][lead] = result.outlet_mean_flow_m3s
        for name in SCENARIOS:
            states[name] = first_results[name].transport.next_stock

        causal_outlet = outlet[0] if outlet else None
        zero_latency = _observation_at(observations, OUTLET_FEATURE_ID, issue_time)
        for horizon in HORIZONS:
            target_index = hour + horizon - 1
            rows.append(
                {
                    "issue_time_utc": _iso(issue_time),
                    "target_support_end_utc": _iso(
                        issue_time + timedelta(hours=horizon)
                    ),
                    "horizon_hours": horizon,
                    "track": "retrospective_oracle_forcing_archive_replay",
                    "observed_discharge_m3s": _optional(
                        panel[target_index]["outcome"]
                    ),
                    "causal_latency_matched_persistence_m3s": _optional(
                        None if causal_outlet is None else causal_outlet.discharge_m3s
                    ),
                    "zero_latency_archive_persistence_m3s": _optional(
                        zero_latency
                    ),
                    **{
                        f"{name}_m3s": forecasts[name][horizon]
                        for name in SCENARIOS
                    },
                    "outlet_observation_valid_at_utc": (
                        "" if causal_outlet is None else _iso(causal_outlet.valid_at)
                    ),
                    "future_observations_assimilated": False,
                }
            )

    prediction_body = _encode_rows(rows)
    metrics, scoring = _score(rows)
    one_hour_regression = _one_hour_parent_regression(
        rows, _read_descriptor(graph["outputs"]["predictions"])
    )
    per_horizon_gates = {
        str(horizon): {
            "graph_beats_local_multi_gauge_rmse": (
                metrics[str(horizon)]["graph_multi_gauge"]["rmse_m3s"]
                < metrics[str(horizon)]["local_multi_gauge"]["rmse_m3s"]
            ),
            "graph_beats_outlet_only_rmse": (
                metrics[str(horizon)]["graph_multi_gauge"]["rmse_m3s"]
                < metrics[str(horizon)]["outlet_only"]["rmse_m3s"]
            ),
            "graph_beats_causal_persistence_rmse": (
                metrics[str(horizon)]["graph_multi_gauge"]["rmse_m3s"]
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
    development_gate = mass_passed and all(
        per_horizon_gates[str(horizon)]["accuracy_gate_passed"]
        for horizon in CORE_HORIZONS
    )
    report = {
        "schema": SCHEMA,
        "status": "public_development_lead_time_diagnostic_complete",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": _artifact(protocol_path, protocol_body),
        "source_artifacts": {
            "graph_multigauge_report": _artifact(graph_report_path, graph_body),
            "graph_parameters": graph["outputs"]["graph_parameters"],
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
            "development_panel": panel_report["panel_artifact"],
            "multigauge_hourly_observations": multigauge["hourly_observations"],
            "prior_mainstem_support": prior_artifacts["forcing_support"],
        },
        "outputs": {
            "predictions": _artifact(prediction_output_path, prediction_body)
        },
        "window": protocol["window"],
        "horizons": protocol["horizon_lock"],
        "forecast_cycle": protocol["forecast_cycle_lock"],
        "information_tracks": {
            "retrospective_oracle_forcing": {
                "status": "executed_archive_replay_diagnostic",
                "metrics_by_horizon": metrics,
                "scoring": scoring,
                "future_observations_assimilated": False,
                "operational_forecast_claim_permitted": False,
            },
            "operational_forecast": {
                "status": "not_executable_missing_issue_time_vintages",
                "metrics_by_horizon": None,
                "required_missing_inputs": protocol["information_tracks"][
                    "operational_forecast"
                ]["required_missing_inputs"],
                "fabricated_substitution_used": False,
            },
        },
        "registered_gates": {
            "per_horizon": per_horizon_gates,
            "core_horizons": list(CORE_HORIZONS),
            "mass_gate_passed": mass_passed,
            "all_core_horizons_accuracy_gate_passed": all(
                per_horizon_gates[str(horizon)]["accuracy_gate_passed"]
                for horizon in CORE_HORIZONS
            ),
            "development_gate_passed": development_gate,
            "operational_gate_assessable": False,
        },
        "conservation": {
            "warmup_maximum_residual_to_tolerance_ratio": max(
                warmup_mass_ratios
            ),
            "scenario_maximum_residual_to_tolerance_ratio": {
                name: max(values) for name, values in mass_ratios.items()
            },
            "all_executed_scenarios_passed": mass_passed,
        },
        "diagnostics": {
            "one_hour_parent_prediction_regression": one_hour_regression,
            "issue_observation_update_count": issue_observation_update_counts,
            "future_observation_update_count": future_observation_update_counts,
            "graph_minus_local_rmse_m3s_by_horizon": {
                str(horizon): (
                    metrics[str(horizon)]["graph_multi_gauge"]["rmse_m3s"]
                    - metrics[str(horizon)]["local_multi_gauge"]["rmse_m3s"]
                )
                for horizon in HORIZONS
            },
        },
        "data_isolation": {
            "graph_parameters_reused_without_refit": True,
            "graph_gain_search_on_this_window": False,
            "target_outcomes_present_for_development_scoring": True,
            "future_target_outcomes_used_by_model": False,
            "future_observations_assimilated_within_rollout": False,
            "realized_future_action_used": True,
            "retrospective_future_q_lateral_used": True,
            "operational_input_vintages_used": False,
            "d3_outcomes_used": False,
            "two_system_blind_outcomes_used": False,
            "untouched_window_consumed": False,
        },
        "claim_boundary": {
            "lead_time_protocol_preregistered": True,
            "lead_time_diagnostic_executed": True,
            "oracle_forcing_diagnostic_executed": True,
            "operational_forecast_executed": False,
            "operational_forecast_evaluated": False,
            "operational_observation_vintage_verified": False,
            "development_gate_passed": development_gate,
            "lagged_graph_kernel_fitted": False,
            "graph_state_estimation_validated": False,
            "forecast_closure_validated": False,
            "geospatial_kernel_validated": False,
        },
    }
    if any(future_observation_update_counts.values()):
        raise RuntimeError("lead_time_future_observation_assimilation_detected")
    if one_hour_regression["maximum_absolute_difference_m3s"] > 1e-12:
        raise RuntimeError("lead_time_one_hour_parent_regression_failed")
    if not mass_passed:
        raise RuntimeError("lead_time_development_conservation_failed")
    return prediction_body, report


def _validate_inputs(
    *,
    protocol: Mapping[str, Any],
    protocol_body: bytes,
    graph: Mapping[str, Any],
    graph_body: bytes,
    graph_report_path: Path,
    development: Mapping[str, Any],
    multigauge: Mapping[str, Any],
    topology: Mapping[str, Any],
    topology_body: bytes,
    panel_report: Mapping[str, Any],
) -> None:
    parent = (protocol.get("parent_evidence") or {}).get(
        "graph_multigauge_report"
    ) or {}
    if (
        protocol.get("schema") != PROTOCOL_SCHEMA
        or protocol.get("status")
        != "frozen_before_lead_time_development_execution"
        or (protocol.get("horizon_lock") or {}).get("all_horizons_hours")
        != list(HORIZONS)
        or (protocol.get("forecast_cycle_lock") or {}).get("scenarios")
        != list(SCENARIOS)
        or parent != _artifact(graph_report_path, graph_body)
        or (protocol.get("outcome_access_at_freeze") or {}).get(
            "parameter_or_gain_tuning_after_access"
        )
        is not False
        or (protocol.get("information_tracks") or {})
        .get("operational_forecast", {})
        .get("executable")
        is not False
        or not protocol_body
    ):
        raise ValueError("lead_time_protocol_invalid")
    if (
        graph.get("schema")
        != "gwm.geotransport.center_hill_graph_multigauge_development.v1"
        or graph.get("status")
        != "public_development_graph_multigauge_diagnostic_complete"
        or (graph.get("diagnostics") or {}).get("development_gate_passed")
        is not False
    ):
        raise ValueError("lead_time_graph_parent_invalid")
    if (
        development.get("schema") != DEVELOPMENT_INPUT_SCHEMA
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
        raise ValueError("lead_time_parent_input_report_invalid")
    if (
        development["topology_report"]["sha256"]
        != hashlib.sha256(topology_body).hexdigest()
        or multigauge["topology_report"]["sha256"]
        != hashlib.sha256(topology_body).hexdigest()
    ):
        raise ValueError("lead_time_topology_identity_invalid")


def _parse_graph_parameters(body: bytes) -> GraphStateUpdateParameters:
    payload = json.loads(body)
    raw = payload.get("graph_state_update_parameters") or {}
    if (
        payload.get("schema") != GRAPH_PARAMETER_ARTIFACT_SCHEMA
        or raw.get("schema") != GRAPH_PARAMETER_SCHEMA
        or raw.get("rank") != 1
    ):
        raise ValueError("lead_time_graph_parameter_artifact_invalid")
    return GraphStateUpdateParameters(
        feature_ids=tuple(raw["feature_ids"]),
        observation_feature_ids=tuple(raw["observation_feature_ids"]),
        reference_storage_m3=tuple(raw["reference_storage_m3"]),
        log_storage_gain_rows=tuple(
            tuple(row) for row in raw["log_storage_gain_rows"]
        ),
        training_system_ids=tuple(raw["training_system_ids"]),
        training_data_start=datetime.fromisoformat(raw["training_data_start"]),
        training_data_end=datetime.fromisoformat(raw["training_data_end"]),
        provenance_id=raw["provenance_id"],
        evidence_level=raw["evidence_level"],
        admitted=raw["admitted"],
        modeled_state_based=raw["modeled_state_based"],
        possible_nudging=raw["possible_nudging"],
        outcome_calibrated=raw["outcome_calibrated"],
    )


def _observation_at(
    observations: Mapping[str, list[tuple[datetime, float | None]]],
    feature_id: int,
    valid_at: datetime,
) -> float | None:
    site_id = "03424860" if feature_id == OUTLET_FEATURE_ID else "03424730"
    for timestamp, value in observations[site_id]:
        if timestamp == valid_at:
            return value
    raise ValueError("lead_time_observation_axis_incomplete")


def _score(
    rows: list[dict[str, object]],
) -> tuple[dict[str, dict[str, dict[str, float]]], dict[str, Any]]:
    names = (*SCENARIOS, "causal_latency_matched_persistence", "zero_latency_archive_persistence")
    result: dict[str, dict[str, dict[str, float]]] = {}
    sample_counts: dict[str, int] = {}
    omitted: dict[str, list[str]] = {}
    for horizon in HORIZONS:
        horizon_rows = [row for row in rows if row["horizon_hours"] == horizon]
        complete: list[dict[str, object]] = []
        missing: list[str] = []
        for row in horizon_rows:
            values = [row["observed_discharge_m3s"]]
            values.extend(row[f"{name}_m3s"] for name in names)
            if any(value is None or value == "" for value in values):
                missing.append(str(row["target_support_end_utc"]))
            else:
                complete.append(row)
        if not complete:
            raise ValueError("lead_time_common_complete_support_empty")
        observed = np.asarray(
            [float(row["observed_discharge_m3s"]) for row in complete],
            dtype=float,
        )
        result[str(horizon)] = {
            name: _metrics(
                observed,
                np.asarray(
                    [float(row[f"{name}_m3s"]) for row in complete], dtype=float
                ),
            )
            for name in names
        }
        sample_counts[str(horizon)] = len(complete)
        omitted[str(horizon)] = missing
    return result, {
        "row_count": len(rows),
        "issue_count": len(rows) // len(HORIZONS),
        "common_complete_sample_count_by_horizon": sample_counts,
        "omitted_target_support_end_utc_by_horizon": omitted,
        "common_complete_case_mask_per_horizon": True,
        "missing_values_imputed": False,
    }


def _metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    if observed.shape != predicted.shape or observed.size == 0:
        raise ValueError("lead_time_metric_support_invalid")
    error = predicted - observed
    denominator = float(np.sum((observed - observed.mean()) ** 2))
    return {
        "sample_count": int(observed.size),
        "rmse_m3s": float(np.sqrt(np.mean(error**2))),
        "mae_m3s": float(np.mean(np.abs(error))),
        "bias_m3s": float(np.mean(error)),
        "nse": float(1.0 - np.sum(error**2) / denominator),
    }


def _one_hour_parent_regression(
    rows: list[dict[str, object]], parent_body: bytes
) -> dict[str, Any]:
    parent_rows = {
        row["support_end_utc"]: row
        for row in csv.DictReader(io.StringIO(parent_body.decode("utf-8")))
    }
    differences: list[float] = []
    count = 0
    for row in rows:
        if row["horizon_hours"] != 1:
            continue
        parent = parent_rows[str(row["target_support_end_utc"])]
        for name in SCENARIOS:
            differences.append(
                abs(float(row[f"{name}_m3s"]) - float(parent[f"{name}_m3s"]))
            )
            count += 1
    return {
        "compared_value_count": count,
        "maximum_absolute_difference_m3s": max(differences),
        "passed": max(differences) <= 1e-12,
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
        raise ValueError("lead_time_development_refuses_overwrite")
    predictions, report = compile_diagnostic(
        protocol_path=args.protocol,
        graph_report_path=args.graph_report,
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
        metrics = report["information_tracks"]["retrospective_oracle_forcing"][
            "metrics_by_horizon"
        ][str(horizon)]
        print(
            f"h={horizon}:graph={metrics['graph_multi_gauge']['rmse_m3s']:.6f}:"
            f"local={metrics['local_multi_gauge']['rmse_m3s']:.6f}:"
            f"persistence={metrics['causal_latency_matched_persistence']['rmse_m3s']:.6f}"
        )
    print(
        f"development_gate_passed={report['registered_gates']['development_gate_passed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
