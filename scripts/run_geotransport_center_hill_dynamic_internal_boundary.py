#!/usr/bin/env python3
"""Run the frozen causal dynamic internal-boundary development diagnostic."""

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
    AutoregressiveLogBoundaryParameters,
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportConfig,
    CausalAutoregressiveLogBoundaryHydrograph,
    CausalDischargeObservation,
    CausalStateDependentManningForecastClosure,
    ForecastClosedBranchingTransportOperator,
    ObservedInternalBoundaryReplacement,
    ReachForcingSupport,
    StockState,
)

if __package__:
    from scripts import (
        run_geotransport_center_hill_internal_boundary_development as parent,
    )
    from scripts.freeze_geotransport_center_hill_dynamic_internal_boundary_protocol import (
        CORE_HORIZONS,
        CORE_PATHS,
        HORIZONS,
        SCHEMA as PROTOCOL_SCHEMA,
    )
else:
    import run_geotransport_center_hill_internal_boundary_development as parent
    from freeze_geotransport_center_hill_dynamic_internal_boundary_protocol import (
        CORE_HORIZONS,
        CORE_PATHS,
        HORIZONS,
        SCHEMA as PROTOCOL_SCHEMA,
    )


REPO_ROOT = parent.REPO_ROOT
DEFAULT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_dynamic_internal_boundary_protocol.json"
)
DEFAULT_PARENT_PROTOCOL = parent.DEFAULT_PROTOCOL
DEFAULT_PARENT_REPORT = parent.DEFAULT_REPORT
DEFAULT_TRANSITION_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/smith_fork_boundary_transition_report.json"
)
DEFAULT_PREDICTIONS = REPO_ROOT / (
    "data/geotransport_v0_1/center_hill_dynamic_internal_boundary/predictions.csv"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_dynamic_internal_boundary_report.json"
)
SCHEMA = "gwm.geotransport.center_hill_dynamic_internal_boundary.v1"
PARENT_REPORT_SCHEMA = parent.SCHEMA
TRANSITION_REPORT_SCHEMA = (
    "gwm.geotransport.smith_fork_boundary_transition_report.v1"
)
DYNAMIC_NAME = "autoregressive_internal_boundary"
BASELINE_NAMES = (
    "held_observed_internal_boundary",
    "modeled_cut_control",
    "zero_internal_boundary",
    "parent_local_multi_gauge",
    "causal_latency_matched_persistence",
    "zero_latency_archive_persistence",
)
MAXIMUM_HORIZON = max(HORIZONS)
PUBLICATION_LAG = timedelta(hours=1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument(
        "--parent-protocol", type=Path, default=DEFAULT_PARENT_PROTOCOL
    )
    parser.add_argument("--parent-report", type=Path, default=DEFAULT_PARENT_REPORT)
    parser.add_argument(
        "--transition-report", type=Path, default=DEFAULT_TRANSITION_REPORT
    )
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_diagnostic(
    *,
    protocol_path: Path,
    parent_protocol_path: Path,
    parent_report_path: Path,
    transition_report_path: Path,
    prediction_output_path: Path,
) -> tuple[bytes, dict[str, Any]]:
    protocol_body, protocol = _load(protocol_path)
    parent_protocol_body, parent_protocol = _load(parent_protocol_path)
    parent_report_body, parent_report = _load(parent_report_path)
    transition_body, transition = _load(transition_report_path)
    _validate_inputs(
        protocol=protocol,
        parent_protocol_path=parent_protocol_path,
        parent_protocol_body=parent_protocol_body,
        parent_report_path=parent_report_path,
        parent_report_body=parent_report_body,
        parent_report=parent_report,
        transition_report_path=transition_report_path,
        transition_body=transition_body,
        transition=transition,
    )

    reference = _load_descriptor_json(
        parent_report["source_artifacts"]["internal_boundary_reference"]
    )
    development = _load_descriptor_json(
        parent_report["source_artifacts"]["development_input_report"]
    )
    multigauge = _load_descriptor_json(
        parent_report["source_artifacts"]["multigauge_input_report"]
    )
    topology = _load_descriptor_json(
        parent_report["source_artifacts"]["topology_report"]
    )
    panel_report = _load_descriptor_json(
        parent_report["source_artifacts"]["development_panel_report"]
    )
    parameter_body = _read_verified(
        transition["outputs"]["parameters"]
    )
    parameters = _parameters(json.loads(parameter_body))
    predictor = CausalAutoregressiveLogBoundaryHydrograph(parameters)

    network_body = _read_verified(topology["artifacts"]["full_subnetwork"])
    original_network = parent._network(json.loads(network_body)["network"])
    route_link_body = _read_verified(topology["artifacts"]["route_link_subset"])
    route_link_path = REPO_ROOT / topology["artifacts"]["route_link_subset"]["path"]
    geometry = parent._geometry(route_link_path, original_network, route_link_body)
    partial_fraction = float(
        protocol["gis_compilation_lock"]["central_downstream_fraction"]
    )
    partial_length = float(
        protocol["gis_compilation_lock"]["central_downstream_partial_length_m"]
    )
    gauge_index = original_network.feature_ids.index(parent.INTERIOR_FEATURE_ID)
    effective_lengths = list(original_network.effective_lengths_m)
    effective_lengths[gauge_index] = partial_length
    cut_network = replace(
        original_network,
        network_id=f"{original_network.network_id}:smith-fork-dynamic-cut-candidate",
        effective_lengths_m=tuple(effective_lengths),
        provenance_id=(
            f"{original_network.provenance_id}|dynamic-smith-fork-cut:"
            f"{protocol['parent_evidence']['internal_boundary_reference']['sha256']}"
        ),
        evidence_level="candidate",
        admitted=False,
    )

    arrays = {
        name: parent._read_npy(descriptor)
        for name, descriptor in development["decoded_arrays"].items()
    }
    feature_ids = tuple(int(value) for value in arrays["feature_ids"])
    initial_storage = np.asarray(arrays["initial_storage_m3"], dtype=float)
    q_lateral = np.asarray(arrays["q_lateral_m3s"], dtype=float)
    if (
        feature_ids != cut_network.feature_ids
        or initial_storage.shape != (len(feature_ids),)
        or q_lateral.shape != (parent.HOUR_COUNT, len(feature_ids))
    ):
        raise ValueError("dynamic_internal_boundary_axis_invalid")
    original_gauge_storage = float(initial_storage[gauge_index])
    initial_storage = initial_storage.copy()
    initial_storage[gauge_index] *= partial_fraction

    panel_body = _read_verified(panel_report["panel_artifact"])
    panel = parent._parse_panel(panel_body)
    observation_body = _read_verified(multigauge["hourly_observations"])
    observation_values = parent._parse_multigauge_hourly(observation_body)
    parent_prediction_body = _read_verified(parent_report["outputs"]["predictions"])
    parent_rows = _parent_rows(parent_prediction_body)

    prior_domain, prior_artifacts = parent.compile_domain()
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
            "center-hill:dynamic-internal-boundary:"
            f"reference={protocol['parent_evidence']['internal_boundary_reference']['sha256']}"
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
    identity_parameters = parent._identity_parameters(
        cut_network, geometry, initial_storage
    )
    wrapper = ForecastClosedBranchingTransportOperator(
        transport,
        CausalStateDependentManningForecastClosure(
            identity_parameters, parent._closure_config()
        ),
    )
    state = StockState(
        values=tuple(float(value) for value in initial_storage),
        unit="m3",
        provenance_id="dynamic-internal-boundary-initial-state",
    )
    action_index = cut_network.feature_ids.index(
        cut_network.action_entry_feature_ids[0]
    )

    warmup_mass_ratios: list[float] = []
    warmup_fallback_count = 0
    for hour in range(parent.ACTIVATION_INDEX):
        issue_time = parent.START + timedelta(hours=hour)
        available = parent._available_observations(observation_values, issue_time)
        outlet = tuple(
            value for value in available if value.feature_id == parent.OUTLET_FEATURE_ID
        )
        boundary_values = _forecast_boundary_values(
            predictor, observation_values, issue_time, 1, parameter_body
        )
        if boundary_values is None:
            warmup_fallback_count += 1
        action, forcing = parent._fields(
            panel, q_lateral, hour, action_index, len(feature_ids)
        )
        result = wrapper.step(
            state,
            geometry,
            issue_time=issue_time,
            observations=outlet,
            action=action,
            forcing=forcing,
            forcing_support=forcing_support,
            internal_boundary=(
                None if boundary_values is None else boundary_values[0]
            ),
        )
        state = result.transport.next_stock
        warmup_mass_ratios.append(parent._mass_ratio(result))

    mass_ratios: list[float] = []
    cycling_ledger = {
        "observed_boundary_input_volume_m3": 0.0,
        "displaced_upstream_outflow_volume_m3": 0.0,
        "net_boundary_analysis_volume_m3": 0.0,
    }
    fallback_issue_count = 0
    future_observation_update_count = 0
    rows: list[dict[str, object]] = []
    last_issue_index = parent.HOUR_COUNT - MAXIMUM_HORIZON
    for hour in range(parent.ACTIVATION_INDEX, last_issue_index + 1):
        issue_time = parent.START + timedelta(hours=hour)
        available = parent._available_observations(observation_values, issue_time)
        outlet = tuple(
            value for value in available if value.feature_id == parent.OUTLET_FEATURE_ID
        )
        boundary_values = _forecast_boundary_values(
            predictor,
            observation_values,
            issue_time,
            MAXIMUM_HORIZON,
            parameter_body,
        )
        if boundary_values is None:
            fallback_issue_count += 1
        rollout_state = state
        forecasts: dict[int, float] = {}
        first_result: Any = None
        for lead_hour in range(1, MAXIMUM_HORIZON + 1):
            transition_hour = hour + lead_hour - 1
            transition_issue = issue_time + timedelta(hours=lead_hour - 1)
            action, forcing = parent._fields(
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
                internal_boundary=(
                    None
                    if boundary_values is None
                    else boundary_values[lead_hour - 1]
                ),
            )
            rollout_state = result.transport.next_stock
            mass_ratios.append(parent._mass_ratio(result))
            if lead_hour == 1:
                first_result = result
                cycling_ledger["observed_boundary_input_volume_m3"] += (
                    result.transport.observed_internal_boundary_input_volume_m3
                )
                cycling_ledger["displaced_upstream_outflow_volume_m3"] += (
                    result.transport.displaced_upstream_outflow_volume_m3
                )
                cycling_ledger["net_boundary_analysis_volume_m3"] += (
                    result.transport.internal_boundary_net_analysis_volume_m3
                )
            else:
                future_observation_update_count += len(
                    result.closure.observation_updates
                )
            if lead_hour in HORIZONS:
                forecasts[lead_hour] = result.outlet_mean_flow_m3s
        if first_result is None:
            raise RuntimeError("dynamic_internal_boundary_first_result_missing")
        state = first_result.transport.next_stock

        history = _boundary_history(observation_values, issue_time)
        latest_valid = "" if not history else _iso(history[-1].valid_at)
        for horizon in HORIZONS:
            key = (_iso(issue_time), horizon)
            baseline = parent_rows[key]
            rows.append(
                {
                    "issue_time_utc": _iso(issue_time),
                    "target_support_end_utc": baseline["target_support_end_utc"],
                    "horizon_hours": horizon,
                    "track": (
                        "retrospective_oracle_action_forcing_causal_boundary_forecast"
                    ),
                    "observed_discharge_m3s": baseline["observed_discharge_m3s"],
                    "autoregressive_internal_boundary_m3s": forecasts[horizon],
                    "held_observed_internal_boundary_m3s": baseline[
                        "observed_internal_boundary_m3s"
                    ],
                    "modeled_cut_control_m3s": baseline["modeled_cut_control_m3s"],
                    "zero_internal_boundary_m3s": baseline[
                        "zero_internal_boundary_m3s"
                    ],
                    "parent_local_multi_gauge_m3s": baseline[
                        "parent_local_multi_gauge_m3s"
                    ],
                    "causal_latency_matched_persistence_m3s": baseline[
                        "causal_latency_matched_persistence_m3s"
                    ],
                    "zero_latency_archive_persistence_m3s": baseline[
                        "zero_latency_archive_persistence_m3s"
                    ],
                    "latest_smith_fork_observation_valid_at_utc": latest_valid,
                    "boundary_history_fallback_to_modeled": boundary_values is None,
                    "future_smith_fork_observations_used": False,
                }
            )

    prediction_body = _encode_rows(rows)
    metrics, scoring = _score(rows)
    per_horizon = {
        str(horizon): {
            "candidate_beats_held_boundary_rmse": (
                metrics[str(horizon)][DYNAMIC_NAME]["rmse_m3s"]
                < metrics[str(horizon)]["held_observed_internal_boundary"]["rmse_m3s"]
            ),
            "candidate_beats_modeled_cut_rmse": (
                metrics[str(horizon)][DYNAMIC_NAME]["rmse_m3s"]
                < metrics[str(horizon)]["modeled_cut_control"]["rmse_m3s"]
            ),
            "candidate_beats_zero_boundary_rmse": (
                metrics[str(horizon)][DYNAMIC_NAME]["rmse_m3s"]
                < metrics[str(horizon)]["zero_internal_boundary"]["rmse_m3s"]
            ),
            "candidate_beats_parent_local_rmse": (
                metrics[str(horizon)][DYNAMIC_NAME]["rmse_m3s"]
                < metrics[str(horizon)]["parent_local_multi_gauge"]["rmse_m3s"]
            ),
            "candidate_beats_causal_persistence_rmse": (
                metrics[str(horizon)][DYNAMIC_NAME]["rmse_m3s"]
                < metrics[str(horizon)]["causal_latency_matched_persistence"]["rmse_m3s"]
            ),
        }
        for horizon in HORIZONS
    }
    for values in per_horizon.values():
        values["accuracy_gate_passed"] = all(values.values())
    mass_passed = max(mass_ratios) <= 1.0
    core_passed = all(
        per_horizon[str(horizon)]["accuracy_gate_passed"]
        for horizon in CORE_HORIZONS
    )
    development_passed = mass_passed and core_passed
    report = {
        "schema": SCHEMA,
        "status": "dynamic_internal_boundary_development_diagnostic_complete",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": _artifact(protocol_path, protocol_body),
        "source_artifacts": {
            "parent_internal_boundary_report": _artifact(
                parent_report_path, parent_report_body
            ),
            "parent_internal_boundary_predictions": parent_report["outputs"][
                "predictions"
            ],
            "boundary_transition_report": _artifact(
                transition_report_path, transition_body
            ),
            "boundary_transition_parameters": transition["outputs"]["parameters"],
            "internal_boundary_reference": parent_report["source_artifacts"][
                "internal_boundary_reference"
            ],
            "development_input_report": parent_report["source_artifacts"][
                "development_input_report"
            ],
            "multigauge_input_report": parent_report["source_artifacts"][
                "multigauge_input_report"
            ],
            "topology_report": parent_report["source_artifacts"]["topology_report"],
            "development_panel_report": parent_report["source_artifacts"][
                "development_panel_report"
            ],
            "prior_mainstem_support": prior_artifacts["forcing_support"],
        },
        "outputs": {
            "predictions": _artifact(prediction_output_path, prediction_body)
        },
        "domain_compilation": {
            "feature_count": len(feature_ids),
            "boundary_feature_id": parent.INTERIOR_FEATURE_ID,
            "original_effective_length_m": original_network.effective_lengths_m[
                gauge_index
            ],
            "cut_effective_length_m": cut_network.effective_lengths_m[gauge_index],
            "downstream_fraction": partial_fraction,
            "original_initial_storage_m3": original_gauge_storage,
            "cut_initial_storage_m3": float(initial_storage[gauge_index]),
            "network_admitted": cut_network.admitted,
            "forcing_support_admitted": forcing_support.admitted_as_spatial_support,
            "diagnostic_only": True,
        },
        "metrics_by_horizon": metrics,
        "scoring": scoring,
        "registered_gates": {
            "per_horizon": per_horizon,
            "core_horizons": list(CORE_HORIZONS),
            "mass_gate_passed": mass_passed,
            "all_core_horizons_accuracy_gate_passed": core_passed,
            "development_gate_passed": development_passed,
        },
        "conservation": {
            "warmup_maximum_residual_to_tolerance_ratio": max(warmup_mass_ratios),
            "branch_maximum_residual_to_tolerance_ratio": max(mass_ratios),
            "unique_cycling_boundary_ledger": cycling_ledger,
            "passed": mass_passed,
        },
        "diagnostics": {
            "warmup_history_fallback_count": warmup_fallback_count,
            "scored_issue_history_fallback_count": fallback_issue_count,
            "future_observation_update_count": future_observation_update_count,
            "candidate_minus_held_boundary_rmse_m3s_by_horizon": {
                str(horizon): metrics[str(horizon)][DYNAMIC_NAME]["rmse_m3s"]
                - metrics[str(horizon)]["held_observed_internal_boundary"]["rmse_m3s"]
                for horizon in HORIZONS
            },
            "candidate_minus_modeled_cut_rmse_m3s_by_horizon": {
                str(horizon): metrics[str(horizon)][DYNAMIC_NAME]["rmse_m3s"]
                - metrics[str(horizon)]["modeled_cut_control"]["rmse_m3s"]
                for horizon in HORIZONS
            },
        },
        "information_boundary": {
            "future_realized_action_used": True,
            "future_retrospective_q_lateral_used": True,
            "future_outlet_target_used_by_model": False,
            "future_smith_fork_observation_used": False,
            "boundary_transition_fitted_before_current_window": True,
            "operational_observation_vintage_verified": False,
            "operational_forecast_claim_permitted": False,
        },
        "data_isolation": {
            "outlet_target_fitted_parameters": 0,
            "boundary_parameters_fitted_from_current_window": False,
            "missing_observations_imputed": False,
            "d3_or_two_system_blind_outcomes_used": False,
            "untouched_window_consumed": False,
        },
        "claim_boundary": {
            "boundary_transition_upstream_holdout_passed": True,
            "dynamic_internal_boundary_diagnostic_executed": True,
            "dynamic_internal_boundary_development_gate_passed": development_passed,
            "internal_boundary_reference_admitted": False,
            "partial_forcing_support_admitted": False,
            "downstream_improvement_validated": False,
            "operational_forecast_evaluated": False,
            "forecast_closure_validated": False,
            "geospatial_kernel_validated": False,
        },
    }
    if future_observation_update_count:
        raise RuntimeError("dynamic_internal_boundary_future_observation_update")
    if not mass_passed:
        raise RuntimeError("dynamic_internal_boundary_conservation_failed")
    return prediction_body, report


def _forecast_boundary_values(
    predictor: CausalAutoregressiveLogBoundaryHydrograph,
    observation_values: Mapping[str, list[tuple[datetime, float | None]]],
    issue_time: datetime,
    horizon: int,
    parameter_body: bytes,
) -> tuple[ObservedInternalBoundaryReplacement, ...] | None:
    history = _boundary_history(observation_values, issue_time)
    targets = tuple(
        issue_time + timedelta(hours=value) for value in range(1, horizon + 1)
    )
    try:
        forecast = predictor.forecast(
            history, issue_time=issue_time, target_valid_times=targets
        )
    except ValueError as exc:
        if str(exc) in {
            "boundary_hydrograph_two_available_observations_required",
            "boundary_hydrograph_latest_history_must_be_consecutive",
        }:
            return None
        raise
    parameter_hash = hashlib.sha256(parameter_body).hexdigest()
    return tuple(
        ObservedInternalBoundaryReplacement(
            feature_ids=(parent.INTERIOR_FEATURE_ID,),
            values=(value,),
            unit="m3 s-1",
            provenance_id=(
                f"smith-fork-log-ar2:{parameter_hash}:issue={_iso(issue_time)}:"
                f"valid={_iso(valid_at)}"
            ),
            evidence_level="candidate",
            admitted=False,
            archive_revised=True,
            operational_vintage_verified=False,
        )
        for valid_at, value in zip(
            forecast.target_valid_times, forecast.discharge_m3s, strict=True
        )
    )


def _boundary_history(
    observation_values: Mapping[str, list[tuple[datetime, float | None]]],
    issue_time: datetime,
) -> tuple[CausalDischargeObservation, ...]:
    values = observation_values["03424730"]
    result = [
        CausalDischargeObservation(
            feature_id=parent.INTERIOR_FEATURE_ID,
            discharge_m3s=float(discharge),
            valid_at=valid_at,
            available_at=valid_at + PUBLICATION_LAG,
            quality_status="approved",
            provenance_id=f"USGS-03424730:00060:archive:{_iso(valid_at)}",
            evidence_level="candidate",
        )
        for valid_at, discharge in values
        if discharge is not None and valid_at + PUBLICATION_LAG <= issue_time
    ]
    return tuple(result[-2:])


def _parameters(payload: Mapping[str, Any]) -> AutoregressiveLogBoundaryParameters:
    return AutoregressiveLogBoundaryParameters(
        feature_id=int(payload["feature_id"]),
        intercept=float(payload["intercept"]),
        lag1_coefficient=float(payload["lag1_coefficient"]),
        lag2_coefficient=float(payload["lag2_coefficient"]),
        timestep_seconds=int(payload["timestep_seconds"]),
        maximum_discharge_m3s=float(payload["maximum_discharge_m3s"]),
        training_data_start=_parse_utc(payload["training_data_start"]),
        training_data_end=_parse_utc(payload["training_data_end"]),
        provenance_id=str(payload["provenance_id"]),
        evidence_level=str(payload["evidence_level"]),
        admitted=bool(payload["admitted"]),
        outlet_target_calibrated=bool(payload["outlet_target_calibrated"]),
    )


def _validate_inputs(
    *,
    protocol: Mapping[str, Any],
    parent_protocol_path: Path,
    parent_protocol_body: bytes,
    parent_report_path: Path,
    parent_report_body: bytes,
    parent_report: Mapping[str, Any],
    transition_report_path: Path,
    transition_body: bytes,
    transition: Mapping[str, Any],
) -> None:
    if (
        protocol.get("schema") != PROTOCOL_SCHEMA
        or protocol.get("status")
        != "frozen_before_dynamic_internal_boundary_execution"
        or protocol["parent_evidence"]["parent_internal_boundary_protocol"]
        != _artifact(parent_protocol_path, parent_protocol_body)
        or protocol["parent_evidence"]["parent_internal_boundary_report"]
        != _artifact(parent_report_path, parent_report_body)
        or protocol["parent_evidence"]["boundary_transition_report"]
        != _artifact(transition_report_path, transition_body)
    ):
        raise ValueError("dynamic_internal_boundary_protocol_invalid")
    for path in CORE_PATHS:
        body = (REPO_ROOT / path).read_bytes()
        if protocol["core_code"][path] != _artifact(REPO_ROOT / path, body):
            raise ValueError("dynamic_internal_boundary_core_changed_after_freeze")
    if (
        parent_report.get("schema") != PARENT_REPORT_SCHEMA
        or transition.get("schema") != TRANSITION_REPORT_SCHEMA
        or transition.get("registered_gates", {}).get(
            "all_horizons_holdout_gate_passed"
        )
        is not True
        or protocol["parent_evidence"]["parent_internal_boundary_predictions"]
        != parent_report["outputs"]["predictions"]
        or protocol["parent_evidence"]["boundary_transition_parameters"]
        != transition["outputs"]["parameters"]
    ):
        raise ValueError("dynamic_internal_boundary_parent_identity_invalid")
    _read_verified(parent_report["outputs"]["predictions"])
    _read_verified(transition["outputs"]["parameters"])


def _parent_rows(body: bytes) -> dict[tuple[str, int], dict[str, str]]:
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
    result = {
        (row["issue_time_utc"], int(row["horizon_hours"])): row for row in rows
    }
    if len(rows) != 2400 or len(rows) != len(result):
        raise ValueError("dynamic_internal_boundary_parent_axis_invalid")
    return result


def _score(
    rows: list[dict[str, object]],
) -> tuple[dict[str, dict[str, dict[str, float]]], dict[str, Any]]:
    names = (DYNAMIC_NAME, *BASELINE_NAMES)
    metrics: dict[str, dict[str, dict[str, float]]] = {}
    counts: dict[str, int] = {}
    omitted: dict[str, list[str]] = {}
    for horizon in HORIZONS:
        selected = [row for row in rows if row["horizon_hours"] == horizon]
        complete = []
        missing = []
        for row in selected:
            values = [row["observed_discharge_m3s"]]
            values.extend(row[f"{name}_m3s"] for name in names)
            if any(value in (None, "") for value in values):
                missing.append(str(row["target_support_end_utc"]))
            else:
                complete.append(row)
        observed = np.asarray(
            [float(row["observed_discharge_m3s"]) for row in complete], dtype=float
        )
        metrics[str(horizon)] = {
            name: parent._metrics(
                observed,
                np.asarray([float(row[f"{name}_m3s"]) for row in complete]),
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


def _load_descriptor_json(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(_read_verified(descriptor))


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("dynamic_internal_boundary_artifact_identity_mismatch")
    return body


def _load(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    return body, json.loads(body)


def _encode_rows(rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("dynamic_internal_boundary_timezone_required")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_body(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def main() -> int:
    args = parse_args()
    if args.predictions.exists() or args.report.exists():
        raise ValueError("dynamic_internal_boundary_refuses_overwrite")
    predictions, report = compile_diagnostic(
        protocol_path=args.protocol,
        parent_protocol_path=args.parent_protocol,
        parent_report_path=args.parent_report,
        transition_report_path=args.transition_report,
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
            f"h={horizon}:dynamic={metrics[DYNAMIC_NAME]['rmse_m3s']:.6f}:"
            f"held={metrics['held_observed_internal_boundary']['rmse_m3s']:.6f}:"
            f"modeled={metrics['modeled_cut_control']['rmse_m3s']:.6f}:"
            f"local={metrics['parent_local_multi_gauge']['rmse_m3s']:.6f}:"
            f"persistence={metrics['causal_latency_matched_persistence']['rmse_m3s']:.6f}"
        )
    print(
        "development_gate_passed="
        f"{report['registered_gates']['development_gate_passed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
