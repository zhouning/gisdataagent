#!/usr/bin/env python3
"""Run an outcome-free graph-state update on Center Hill development data."""

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
    CausalDischargeObservation,
    CausalObservationUpdateConfig,
    CausalStateDependentManningForecastClosure,
    ForecastClosedBranchingTransportOperator,
    ForecastClosureConfig,
    GraphStateUpdateParameters,
    ReachForcingSupport,
    StateDependentManningClosureParameters,
    StockState,
    extract_nwm_streamflow,
    extract_nwm_velocity,
)

if __package__:
    from scripts.acquire_geotransport_forecast_closure_development_inputs import (
        compile_development_plan,
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
    from acquire_geotransport_forecast_closure_development_inputs import (
        compile_development_plan,
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


DEFAULT_DEVELOPMENT_INPUT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "forecast_closure_center_hill_development_inputs_report.json"
)
DEFAULT_MULTIGAUGE_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_multigauge_development_inputs_report.json"
)
DEFAULT_TOPOLOGY_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_v2_d5_full_subnetwork_report.json"
)
DEFAULT_PANEL_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_672h_development_panel_report.json"
)
DEFAULT_PARAMETER_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_graph_multigauge_development/"
    "graph_state_update_parameters.json"
)
DEFAULT_PREDICTION_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_graph_multigauge_development/"
    "predictions.csv"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_graph_multigauge_development_report.json"
)
SCHEMA = "gwm.geotransport.center_hill_graph_multigauge_development.v1"
PARAMETER_SCHEMA = (
    "gwm.geotransport.center_hill_graph_state_update_parameter_artifact.v1"
)
DEVELOPMENT_INPUT_SCHEMA = "gwm.geotransport.forecast_closure_development_inputs.v1"
MULTIGAUGE_SCHEMA = (
    "gwm.geotransport.center_hill_multigauge_development_inputs.v1"
)
TOPOLOGY_SCHEMA = "gwm.geotransport.center_hill_v2_d5_full_subnetwork.v1"
PANEL_SCHEMA = "gwm.geotransport.center_hill_672h_development_panel.v1"
START = datetime(2021, 12, 9, 1, tzinfo=timezone.utc)
END = datetime(2022, 1, 6, 1, tzinfo=timezone.utc)
HOUR_COUNT = 672
FIT_HOURS = 168
ACTIVATION_INDEX = FIT_HOURS + 1
PUBLICATION_LAG = timedelta(hours=1)
MAXIMUM_OBSERVATION_AGE_SECONDS = 7200.0
INTERIOR_SITE_ID = "03424730"
INTERIOR_FEATURE_ID = 18_421_273
OUTLET_SITE_ID = "03424860"
OUTLET_FEATURE_ID = 18_421_703
SCENARIOS = (
    "graph_multi_gauge",
    "local_multi_gauge",
    "outlet_only",
    "interior_only",
    "no_update",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
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
    parser.add_argument("--parameters", type=Path, default=DEFAULT_PARAMETER_OUTPUT)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTION_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_diagnostic(
    *,
    development_input_report_path: Path = DEFAULT_DEVELOPMENT_INPUT_REPORT,
    multigauge_report_path: Path = DEFAULT_MULTIGAUGE_REPORT,
    topology_report_path: Path = DEFAULT_TOPOLOGY_REPORT,
    panel_report_path: Path = DEFAULT_PANEL_REPORT,
    parameter_output_path: Path = DEFAULT_PARAMETER_OUTPUT,
    prediction_output_path: Path = DEFAULT_PREDICTION_OUTPUT,
) -> tuple[bytes, bytes, dict[str, Any]]:
    development_body, development = _load_json(development_input_report_path)
    if (
        development.get("schema") != DEVELOPMENT_INPUT_SCHEMA
        or development.get("status") != "pass_public_development_inputs_acquired"
        or (development.get("data_isolation") or {}).get("d3_outcomes_read")
        is not False
        or (development.get("data_isolation") or {}).get(
            "two_system_blind_outcomes_read"
        )
        is not False
    ):
        raise ValueError("graph_multigauge_development_input_report_invalid")
    multigauge_body, multigauge = _load_json(multigauge_report_path)
    if (
        multigauge.get("schema") != MULTIGAUGE_SCHEMA
        or multigauge.get("status")
        != "pass_public_multigauge_development_inputs_acquired"
        or (multigauge.get("station_screening") or {}).get("eligible_site_count")
        != 2
    ):
        raise ValueError("graph_multigauge_observation_report_invalid")

    topology_body, topology = _load_json(topology_report_path)
    if (
        topology.get("schema") != TOPOLOGY_SCHEMA
        or topology.get("status") != "pass_full_incremental_subnetwork_compiled"
        or development["topology_report"]["sha256"]
        != hashlib.sha256(topology_body).hexdigest()
        or multigauge["topology_report"]["sha256"]
        != hashlib.sha256(topology_body).hexdigest()
    ):
        raise ValueError("graph_multigauge_topology_identity_invalid")
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
        raise ValueError("graph_multigauge_dynamic_axis_invalid")

    panel_report_body, panel_report = _load_json(panel_report_path)
    if (
        panel_report.get("schema") != PANEL_SCHEMA
        or panel_report.get("status")
        != "compiled_with_observation_gap_not_admitted"
    ):
        raise ValueError("graph_multigauge_panel_report_invalid")
    panel_body = _read_descriptor(panel_report["panel_artifact"])
    panel = _parse_panel(panel_body)
    multigauge_hourly_body = _read_descriptor(multigauge["hourly_observations"])
    observations = _parse_multigauge_hourly(multigauge_hourly_body)

    full_storage, modeled_state = _modeled_storage_training_array(
        development,
        network=network,
    )
    graph_parameters, graph_fit = _fit_graph_parameters(
        network=network,
        geometry=geometry,
        modeled_storage=full_storage[:FIT_HOURS],
        source_provenance=(
            f"development-inputs={hashlib.sha256(development_body).hexdigest()}|"
            f"topology={hashlib.sha256(network_body).hexdigest()}"
        ),
    )
    parameter_payload = {
        "schema": PARAMETER_SCHEMA,
        "graph_state_update_parameters": graph_parameters.as_dict(),
        "fit": graph_fit,
        "observation_policy": _observation_policy(),
        "source_modeled_state": modeled_state,
        "data_isolation": {
            "parameter_basis": "NWM modeled streamflow-velocity state only",
            "usgs_values_used_to_fit_graph_gains": False,
            "d3_outcomes_used": False,
            "two_system_blind_outcomes_used": False,
        },
        "claim_boundary": {
            "graph_basis_fitted": True,
            "basis_possible_nudging": True,
            "outcome_calibrated": False,
            "graph_state_estimation_validated": False,
            "geospatial_kernel_validated": False,
        },
    }
    parameter_body = _json_body(parameter_payload)

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
        provenance_id="center-hill:graph-multigauge:forcing-support",
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
    warmup_outlet_update_count = 0
    for hour in range(ACTIVATION_INDEX):
        issue_time = START + timedelta(hours=hour)
        available = _available_observations(observations, issue_time)
        outlet_observation = tuple(
            value for value in available if value.feature_id == OUTLET_FEATURE_ID
        )
        action, forcing = _fields(
            panel, q_lateral, hour, action_index, len(feature_ids)
        )
        result = local_wrapper.step(
            baseline_state,
            geometry,
            issue_time=issue_time,
            observations=outlet_observation,
            action=action,
            forcing=forcing,
            forcing_support=forcing_support,
        )
        baseline_state = result.transport.next_stock
        warmup_mass_ratios.append(
            abs(result.forecast_cycle_mass_balance_residual_m3)
            / result.forecast_cycle_mass_tolerance_m3
        )
        warmup_outlet_update_count += len(outlet_observation)

    wrappers = {
        "graph_multi_gauge": graph_wrapper,
        "local_multi_gauge": local_wrapper,
        "outlet_only": local_wrapper,
        "interior_only": local_wrapper,
        "no_update": local_wrapper,
    }
    states = {
        name: StockState(
            values=baseline_state.values,
            unit="m3",
            provenance_id=f"graph-multigauge-shared-activation-state:{name}",
        )
        for name in SCENARIOS
    }
    mass_ratios = {name: [] for name in SCENARIOS}
    analysis_increment_totals = {name: 0.0 for name in SCENARIOS}
    graph_increment_totals = {name: 0.0 for name in SCENARIOS}
    observation_update_counts = {name: 0 for name in SCENARIOS}
    rows: list[dict[str, object]] = []
    for hour in range(ACTIVATION_INDEX, HOUR_COUNT):
        issue_time = START + timedelta(hours=hour)
        support_end = issue_time + timedelta(hours=1)
        available = _available_observations(observations, issue_time)
        outlet = tuple(
            value for value in available if value.feature_id == OUTLET_FEATURE_ID
        )
        interior = tuple(
            value for value in available if value.feature_id == INTERIOR_FEATURE_ID
        )
        scenario_observations = {
            "graph_multi_gauge": tuple(sorted(available, key=lambda value: value.feature_id)),
            "local_multi_gauge": tuple(sorted(available, key=lambda value: value.feature_id)),
            "outlet_only": outlet,
            "interior_only": interior,
            "no_update": (),
        }
        action, forcing = _fields(
            panel, q_lateral, hour, action_index, len(feature_ids)
        )
        predictions: dict[str, float] = {}
        graph_result = None
        for name in SCENARIOS:
            result = wrappers[name].step(
                states[name],
                geometry,
                issue_time=issue_time,
                observations=scenario_observations[name],
                action=action,
                forcing=forcing,
                forcing_support=forcing_support,
            )
            states[name] = result.transport.next_stock
            predictions[name] = result.outlet_mean_flow_m3s
            mass_ratios[name].append(
                abs(result.forecast_cycle_mass_balance_residual_m3)
                / result.forecast_cycle_mass_tolerance_m3
            )
            analysis_increment_totals[name] += result.analysis_increment_m3
            graph_increment_totals[name] += sum(
                result.closure.graph_analysis_increment_m3
            )
            observation_update_counts[name] += len(result.closure.observation_updates)
            if name == "graph_multi_gauge":
                graph_result = result
        assert graph_result is not None
        outlet_observation = outlet[0] if outlet else None
        interior_observation = interior[0] if interior else None
        rows.append(
            {
                "support_start_utc": _iso(issue_time),
                "support_end_utc": _iso(support_end),
                "observed_discharge_m3s": _optional(panel[hour]["outcome"]),
                "one_hour_persistence_m3s": _optional(panel[hour - 1]["outcome"]),
                "latency_matched_persistence_m3s": _optional(
                    None
                    if outlet_observation is None
                    else outlet_observation.discharge_m3s
                ),
                **{
                    f"{name}_m3s": predictions[name] for name in SCENARIOS
                },
                "outlet_observation_valid_at_utc": (
                    "" if outlet_observation is None else _iso(outlet_observation.valid_at)
                ),
                "interior_observation_valid_at_utc": (
                    ""
                    if interior_observation is None
                    else _iso(interior_observation.valid_at)
                ),
                "graph_step_analysis_increment_m3": graph_result.analysis_increment_m3,
                "graph_step_spatial_increment_m3": sum(
                    graph_result.closure.graph_analysis_increment_m3
                ),
            }
        )

    prediction_body = _encode_rows(rows)
    metrics, scoring = _score(rows)
    graph_gate = all(
        metrics["graph_multi_gauge"]["rmse_m3s"] < metrics[name]["rmse_m3s"]
        for name in (
            "local_multi_gauge",
            "outlet_only",
            "latency_matched_persistence",
            "one_hour_persistence",
        )
    )
    report = {
        "schema": SCHEMA,
        "status": "public_development_graph_multigauge_diagnostic_complete",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_artifacts": {
            "development_input_report": _artifact(
                development_input_report_path, development_body
            ),
            "multigauge_input_report": _artifact(
                multigauge_report_path, multigauge_body
            ),
            "topology_report": _artifact(topology_report_path, topology_body),
            "full_subnetwork": topology["artifacts"]["full_subnetwork"],
            "route_link_subset": topology["artifacts"]["route_link_subset"],
            "development_panel_report": _artifact(
                panel_report_path, panel_report_body
            ),
            "development_panel": panel_report["panel_artifact"],
            "multigauge_hourly_observations": multigauge["hourly_observations"],
            "prior_mainstem_support": prior_artifacts["forcing_support"],
        },
        "outputs": {
            "graph_parameters": _artifact(parameter_output_path, parameter_body),
            "predictions": _artifact(prediction_output_path, prediction_body),
        },
        "window": {
            "input_start": _iso(START),
            "input_end_exclusive": _iso(END),
            "modeled_state_fit_hour_count": FIT_HOURS,
            "activation_issue_time": _iso(START + timedelta(hours=ACTIVATION_INDEX)),
            "diagnostic_hour_count": HOUR_COUNT - ACTIVATION_INDEX,
            "role": "public_development_only_not_validation",
        },
        "graph_parameterization": graph_fit,
        "observation_policy": _observation_policy(),
        "scenarios": {
            "graph_multi_gauge": "local two-gauge update plus NWM covariance graph basis",
            "local_multi_gauge": "two-gauge local updates without graph propagation",
            "outlet_only": "original outlet local update",
            "interior_only": "Smith Fork local update only",
            "no_update": "identity open loop from shared activation state",
        },
        "scoring": scoring,
        "metrics": metrics,
        "conservation": {
            "warmup_maximum_residual_to_tolerance_ratio": max(warmup_mass_ratios),
            "scenario_maximum_residual_to_tolerance_ratio": {
                name: max(values) for name, values in mass_ratios.items()
            },
            "all_scenarios_passed": all(
                max(values) <= 1.0 for values in mass_ratios.values()
            ),
            "analysis_increment_total_m3": analysis_increment_totals,
            "graph_spatial_increment_total_m3": graph_increment_totals,
        },
        "diagnostics": {
            "warmup_outlet_update_count": warmup_outlet_update_count,
            "scenario_observation_update_count": observation_update_counts,
            "graph_beats_local_multi_gauge_rmse": (
                metrics["graph_multi_gauge"]["rmse_m3s"]
                < metrics["local_multi_gauge"]["rmse_m3s"]
            ),
            "graph_beats_outlet_only_rmse": (
                metrics["graph_multi_gauge"]["rmse_m3s"]
                < metrics["outlet_only"]["rmse_m3s"]
            ),
            "graph_beats_latency_matched_persistence_rmse": (
                metrics["graph_multi_gauge"]["rmse_m3s"]
                < metrics["latency_matched_persistence"]["rmse_m3s"]
            ),
            "graph_beats_one_hour_persistence_rmse": (
                metrics["graph_multi_gauge"]["rmse_m3s"]
                < metrics["one_hour_persistence"]["rmse_m3s"]
            ),
            "development_gate_passed": graph_gate,
        },
        "data_isolation": {
            "graph_gain_uses_usgs_values": False,
            "graph_gain_uses_only_first_168_nwm_modeled_states": True,
            "nwm_modeled_state_possible_nudging": True,
            "d3_outcomes_used": False,
            "two_system_blind_outcomes_used": False,
            "missing_observations_imputed": False,
        },
        "claim_boundary": {
            "public_multigauge_data_available": True,
            "graph_state_update_contract_implemented": True,
            "graph_state_update_parameters_fitted": True,
            "graph_state_update_outcome_calibrated": False,
            "operational_observation_vintage_verified": False,
            "development_gate_passed": graph_gate,
            "graph_state_estimation_validated": False,
            "predictive_improvement_validated": False,
            "forecast_closure_validated": False,
            "geospatial_kernel_validated": False,
            "untouched_multi_system_window_consumed": False,
        },
    }
    if not report["conservation"]["all_scenarios_passed"]:
        raise RuntimeError("graph_multigauge_development_conservation_failed")
    return parameter_body, prediction_body, report


def _modeled_storage_training_array(
    development: Mapping[str, Any], *, network: Any
) -> tuple[np.ndarray, dict[str, Any]]:
    _, _, full_plan, context = compile_development_plan()
    artifacts = {
        (row["variable"], row["chunk_key"]): row
        for row in development["raw_artifacts"]
    }
    time_body = _read_descriptor(artifacts[("time", "559")])
    streamflow = extract_nwm_streamflow(
        full_plan,
        context["streamflow_schema"],
        time_chunks={559: time_body},
        streamflow_chunks={
            (559, chunk): _read_descriptor(
                artifacts[("streamflow", f"559.{chunk}")]
            )
            for chunk in full_plan.feature_chunk_indices
        },
    )
    velocity = extract_nwm_velocity(
        full_plan,
        context["velocity_schema"],
        time_chunks={559: time_body},
        velocity_chunks={
            (559, chunk): _read_descriptor(
                artifacts[("velocity", f"559.{chunk}")]
            )
            for chunk in full_plan.feature_chunk_indices
        },
    )
    discharge = np.asarray(streamflow.values_m3s, dtype=float)
    speed = np.asarray(velocity.values_ms, dtype=float)
    if (
        discharge.shape != (HOUR_COUNT, len(network.feature_ids))
        or speed.shape != discharge.shape
        or streamflow.feature_ids != network.feature_ids
        or velocity.feature_ids != network.feature_ids
        or streamflow.fill_value_count != 0
        or velocity.fill_value_count != 0
    ):
        raise ValueError("graph_multigauge_modeled_state_axis_or_fill_invalid")
    if bool(((discharge > 0.0) & (speed <= 0.0)).any()):
        raise ValueError("graph_multigauge_positive_flow_zero_velocity")
    area = np.divide(discharge, speed, out=np.zeros_like(discharge), where=speed > 0.0)
    storage = area * np.asarray(network.effective_lengths_m, dtype=float)[None, :]
    if not np.isfinite(storage).all() or bool((storage < 0.0).any()):
        raise ValueError("graph_multigauge_modeled_storage_invalid")
    return storage, {
        "streamflow_fill_value_count": streamflow.fill_value_count,
        "velocity_fill_value_count": velocity.fill_value_count,
        "shape": list(storage.shape),
        "modeled": True,
        "ground_truth": False,
        "possible_nudging": True,
        "timestamps_start": streamflow.timestamps[0],
        "timestamps_end": streamflow.timestamps[-1],
    }


def _fit_graph_parameters(
    *,
    network: Any,
    geometry: Any,
    modeled_storage: np.ndarray,
    source_provenance: str,
) -> tuple[GraphStateUpdateParameters, dict[str, Any]]:
    feature_index = {
        feature_id: index for index, feature_id in enumerate(network.feature_ids)
    }
    gauge_index = feature_index[INTERIOR_FEATURE_ID]
    upstream = _upstream_ancestors(network, INTERIOR_FEATURE_ID)
    minimum_reference = np.maximum(
        np.asarray(network.effective_lengths_m, dtype=float)
        * np.asarray(geometry.bottom_width_m, dtype=float)
        * 0.01,
        1.0,
    )
    reference = np.maximum(np.median(modeled_storage, axis=0), minimum_reference)
    normalized = np.log1p(modeled_storage / reference[None, :])
    gauge = normalized[:, gauge_index]
    centered_gauge = gauge - gauge.mean()
    variance = float(centered_gauge @ centered_gauge)
    if variance <= 0.0 or not np.isfinite(variance):
        raise ValueError("graph_multigauge_gauge_state_variance_required")
    gains = np.zeros(len(network.feature_ids), dtype=float)
    raw_gains: list[float] = []
    for feature_id in upstream:
        index = feature_index[feature_id]
        centered = normalized[:, index] - normalized[:, index].mean()
        raw = float(centered @ centered_gauge / variance)
        raw_gains.append(raw)
        gains[index] = float(np.clip(raw, 0.0, 1.0))
    positive = gains > 0.0
    if not bool(positive.any()):
        raise ValueError("graph_multigauge_positive_covariance_support_required")
    training_start = START
    training_end = START + timedelta(hours=FIT_HOURS - 1)
    parameters = GraphStateUpdateParameters(
        feature_ids=network.feature_ids,
        observation_feature_ids=(INTERIOR_FEATURE_ID,),
        reference_storage_m3=tuple(float(value) for value in reference),
        log_storage_gain_rows=(tuple(float(value) for value in gains),),
        training_system_ids=("center_hill:nwm-v3:pre-d3-development",),
        training_data_start=training_start,
        training_data_end=training_end,
        provenance_id=(
            "center-hill-smith-fork-nwm-modeled-covariance|" + source_provenance
        ),
        evidence_level="candidate",
        admitted=False,
        modeled_state_based=True,
        possible_nudging=True,
        outcome_calibrated=False,
    )
    return parameters, {
        "family": "rank_one_nwm_modeled_log_storage_covariance",
        "rank": 1,
        "free_outcome_parameter_count": 0,
        "observation_site_id": INTERIOR_SITE_ID,
        "observation_feature_id": INTERIOR_FEATURE_ID,
        "training_hour_count": FIT_HOURS,
        "training_start": _iso(training_start),
        "training_end": _iso(training_end),
        "upstream_ancestor_count": len(upstream),
        "positive_gain_feature_count": int(positive.sum()),
        "zero_gain_feature_count": int((~positive).sum()),
        "raw_gain_minimum_on_upstream_support": min(raw_gains),
        "raw_gain_maximum_on_upstream_support": max(raw_gains),
        "applied_gain_minimum_positive": float(gains[positive].min()),
        "applied_gain_maximum": float(gains.max()),
        "gain_bounds": [0.0, 1.0],
        "support_rule": "strict upstream ancestors on frozen NWM RouteLink DAG",
        "gauge_local_gain": 0.0,
        "local_gauge_update_handled_separately": True,
        "outcome_calibrated": False,
        "possible_nudging": True,
    }


def _upstream_ancestors(network: Any, target_feature_id: int) -> tuple[int, ...]:
    downstream = dict(
        zip(network.feature_ids, network.downstream_feature_ids, strict=True)
    )
    ancestors: list[int] = []
    for feature_id in network.feature_ids:
        if feature_id == target_feature_id:
            continue
        current: int | None = feature_id
        visited: set[int] = set()
        while current is not None and current != target_feature_id:
            if current in visited:
                raise RuntimeError("graph_multigauge_network_cycle_detected")
            visited.add(current)
            current = downstream[current]
        if current == target_feature_id:
            ancestors.append(feature_id)
    if not ancestors:
        raise ValueError("graph_multigauge_interior_gauge_has_no_upstream_support")
    return tuple(ancestors)


def _identity_parameters(
    network: Any, geometry: Any, initial_storage: np.ndarray
) -> StateDependentManningClosureParameters:
    reference = tuple(
        max(
            float(initial_storage[index]),
            network.effective_lengths_m[index]
            * geometry.bottom_width_m[index]
            * 0.01,
            1.0,
        )
        for index in range(len(network.feature_ids))
    )
    return StateDependentManningClosureParameters(
        feature_ids=network.feature_ids,
        reference_storage_m3=reference,
        log_roughness_intercept=(0.0,) * len(network.feature_ids),
        log_roughness_storage_slope=(0.0,) * len(network.feature_ids),
        training_system_ids=("identity-physical-baseline",),
        training_data_start=datetime(2020, 1, 1, tzinfo=timezone.utc),
        training_data_end=datetime(2020, 1, 2, tzinfo=timezone.utc),
        provenance_id="identity-forecast-closure:no-outcome-calibration",
        evidence_level="derived",
        admitted=True,
        outcome_calibrated=False,
    )


def _closure_config() -> ForecastClosureConfig:
    return ForecastClosureConfig(
        observation_update=CausalObservationUpdateConfig(
            analysis_gain=1.0,
            maximum_observation_age_seconds=MAXIMUM_OBSERVATION_AGE_SECONDS,
            accepted_quality_statuses=("approved",),
            require_authoritative_evidence=False,
            allow_unadmitted_components_for_diagnostics=True,
        ),
        minimum_roughness_multiplier=0.5,
        maximum_roughness_multiplier=2.0,
        allow_unadmitted_components_for_diagnostics=True,
    )


def _observation_policy() -> dict[str, object]:
    return {
        "analysis_gain": 1.0,
        "gain_selected_by_outcome_search": False,
        "source_support": "complete native samples in (t-1h,t]",
        "assumed_publication_lag_seconds": int(PUBLICATION_LAG.total_seconds()),
        "maximum_observation_age_seconds": MAXIMUM_OBSERVATION_AGE_SECONDS,
        "quality_status": "approved",
        "evidence_level": "derived_currently_retrieved_revised_archive",
        "operational_vintage_availability_verified": False,
        "missing_observation_imputation": False,
    }


def _parse_multigauge_hourly(
    body: bytes,
) -> dict[str, list[tuple[datetime, float | None]]]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    required = {
        "support_start_utc",
        "support_end_utc",
        f"usgs_{INTERIOR_SITE_ID}_discharge_m3s",
        f"usgs_{INTERIOR_SITE_ID}_qualifier",
        f"usgs_{OUTLET_SITE_ID}_discharge_m3s",
        f"usgs_{OUTLET_SITE_ID}_qualifier",
    }
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValueError("graph_multigauge_hourly_columns_invalid")
    result = {INTERIOR_SITE_ID: [], OUTLET_SITE_ID: []}
    for index, row in enumerate(reader):
        expected_start = START + timedelta(hours=index)
        expected_end = expected_start + timedelta(hours=1)
        if (
            _parse_utc(row["support_start_utc"]) != expected_start
            or _parse_utc(row["support_end_utc"]) != expected_end
        ):
            raise ValueError("graph_multigauge_hourly_time_axis_invalid")
        for site_id in result:
            raw = row[f"usgs_{site_id}_discharge_m3s"]
            qualifier = row[f"usgs_{site_id}_qualifier"]
            if raw and qualifier != "A":
                raise ValueError("graph_multigauge_hourly_qualifier_invalid")
            result[site_id].append((expected_end, None if not raw else float(raw)))
    if any(len(values) != HOUR_COUNT for values in result.values()):
        raise ValueError("graph_multigauge_hourly_row_count_invalid")
    return result


def _available_observations(
    values: Mapping[str, list[tuple[datetime, float | None]]], issue_time: datetime
) -> tuple[CausalDischargeObservation, ...]:
    feature_by_site = {
        INTERIOR_SITE_ID: INTERIOR_FEATURE_ID,
        OUTLET_SITE_ID: OUTLET_FEATURE_ID,
    }
    observations: list[CausalDischargeObservation] = []
    for site_id in (INTERIOR_SITE_ID, OUTLET_SITE_ID):
        for valid_at, discharge in reversed(values[site_id]):
            available_at = valid_at + PUBLICATION_LAG
            if available_at > issue_time or discharge is None:
                continue
            if (issue_time - valid_at).total_seconds() > MAXIMUM_OBSERVATION_AGE_SECONDS:
                break
            observations.append(
                CausalDischargeObservation(
                    feature_id=feature_by_site[site_id],
                    discharge_m3s=discharge,
                    valid_at=valid_at,
                    available_at=available_at,
                    quality_status="approved",
                    provenance_id=(
                        f"USGS-{site_id}:00060:derived-hourly-mean:{_iso(valid_at)}"
                    ),
                    evidence_level="derived",
                )
            )
            break
    return tuple(observations)


def _score(
    rows: list[dict[str, object]],
) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    prediction_columns = {
        name: f"{name}_m3s" for name in SCENARIOS
    }
    prediction_columns.update(
        {
            "latency_matched_persistence": "latency_matched_persistence_m3s",
            "one_hour_persistence": "one_hour_persistence_m3s",
        }
    )
    metrics: dict[str, dict[str, float]] = {}
    sample_counts: dict[str, int] = {}
    for name, column in prediction_columns.items():
        pairs = [
            (float(row["observed_discharge_m3s"]), float(row[column]))
            for row in rows
            if row["observed_discharge_m3s"] is not None
            and row[column] is not None
        ]
        observed = np.asarray([value[0] for value in pairs], dtype=float)
        predicted = np.asarray([value[1] for value in pairs], dtype=float)
        metrics[name] = _metrics(observed, predicted)
        sample_counts[name] = len(pairs)
    return metrics, {
        "diagnostic_row_count": len(rows),
        "per_model_sample_count": sample_counts,
        "missing_targets_imputed": False,
        "primary_comparison_support": (
            "each model scored on its available target pairs; graph/local/outlet/no-update "
            "share identical target support"
        ),
    }


def _metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    if observed.size == 0 or observed.shape != predicted.shape:
        raise ValueError("graph_multigauge_metric_support_invalid")
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


def _read_descriptor(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("graph_multigauge_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("graph_multigauge_artifact_identity_mismatch")
    return body


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    return body, json.loads(body)


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


def _json_body(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("graph_multigauge_timezone_required")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _optional(value: Any) -> Any:
    return None if value is None else float(value)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_body(payload))


def main() -> int:
    args = parse_args()
    if args.parameters.exists() or args.predictions.exists() or args.report.exists():
        raise ValueError("graph_multigauge_development_refuses_overwrite")
    parameters, predictions, report = compile_diagnostic(
        development_input_report_path=args.development_input_report,
        multigauge_report_path=args.multigauge_report,
        topology_report_path=args.topology_report,
        panel_report_path=args.panel_report,
        parameter_output_path=args.parameters,
        prediction_output_path=args.predictions,
    )
    args.parameters.parent.mkdir(parents=True, exist_ok=True)
    args.predictions.parent.mkdir(parents=True, exist_ok=True)
    args.parameters.write_bytes(parameters)
    args.predictions.write_bytes(predictions)
    _write_json(args.report, report)
    print(args.report)
    print(f"graph_rmse_m3s={report['metrics']['graph_multi_gauge']['rmse_m3s']:.6f}")
    print(f"outlet_only_rmse_m3s={report['metrics']['outlet_only']['rmse_m3s']:.6f}")
    print(f"development_gate_passed={report['diagnostics']['development_gate_passed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
