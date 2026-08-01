#!/usr/bin/env python3
"""Fit and diagnose a low-dimensional forecast closure on pre-D3 public data."""

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
    ActionBoundaryFlux,
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportConfig,
    CausalDischargeObservation,
    CausalObservationUpdateConfig,
    CausalStateDependentManningForecastClosure,
    ForecastClosedBranchingTransportOperator,
    ForecastClosureConfig,
    ForcingFlux,
    ReachForcingSupport,
    StateDependentManningClosureParameters,
    StockState,
)

if __package__:
    from scripts.run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
        REPO_ROOT,
        _geometry,
        _network,
        _read_npy,
        _read_verified,
    )
    from scripts.run_geotransport_center_hill_v2_outcome_free import compile_domain
else:
    from run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
        REPO_ROOT,
        _geometry,
        _network,
        _read_npy,
        _read_verified,
    )
    from run_geotransport_center_hill_v2_outcome_free import compile_domain


DEFAULT_INPUT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "forecast_closure_center_hill_development_inputs_report.json"
)
DEFAULT_TOPOLOGY_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_v2_d5_full_subnetwork_report.json"
)
DEFAULT_PANEL_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_672h_development_panel_report.json"
)
DEFAULT_PARAMETER_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/forecast_closure_center_hill_development/"
    "parameters.json"
)
DEFAULT_PREDICTION_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/forecast_closure_center_hill_development/"
    "predictions.csv"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "forecast_closure_center_hill_development_report.json"
)
SCHEMA = "gwm.geotransport.forecast_closure_development_training.v1"
PARAMETER_ARTIFACT_SCHEMA = (
    "gwm.geotransport.forecast_closure_parameter_artifact.v1"
)
INPUT_SCHEMA = "gwm.geotransport.forecast_closure_development_inputs.v1"
TOPOLOGY_SCHEMA = "gwm.geotransport.center_hill_v2_d5_full_subnetwork.v1"
PANEL_SCHEMA = "gwm.geotransport.center_hill_672h_development_panel.v1"
START = datetime(2021, 12, 9, 1, tzinfo=timezone.utc)
END = datetime(2022, 1, 6, 1, tzinfo=timezone.utc)
HOUR_COUNT = 672
FIT_HOURS = 168
ACTIVATION_INDEX = FIT_HOURS + 1
OBSERVATION_PUBLICATION_LAG = timedelta(hours=1)
MAXIMUM_OBSERVATION_AGE_SECONDS = 7200.0
ROUGHNESS_MULTIPLIER_BOUNDS = (0.5, 2.0)
RIDGE_PENALTY = 1.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-report", type=Path, default=DEFAULT_INPUT_REPORT)
    parser.add_argument("--topology-report", type=Path, default=DEFAULT_TOPOLOGY_REPORT)
    parser.add_argument("--panel-report", type=Path, default=DEFAULT_PANEL_REPORT)
    parser.add_argument("--parameters", type=Path, default=DEFAULT_PARAMETER_OUTPUT)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTION_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_training(
    *,
    input_report_path: Path = DEFAULT_INPUT_REPORT,
    topology_report_path: Path = DEFAULT_TOPOLOGY_REPORT,
    panel_report_path: Path = DEFAULT_PANEL_REPORT,
    parameter_output_path: Path = DEFAULT_PARAMETER_OUTPUT,
    prediction_output_path: Path = DEFAULT_PREDICTION_OUTPUT,
) -> tuple[bytes, bytes, dict[str, Any]]:
    input_body = input_report_path.read_bytes()
    inputs = json.loads(input_body)
    if (
        inputs.get("schema") != INPUT_SCHEMA
        or inputs.get("status") != "pass_public_development_inputs_acquired"
        or (inputs.get("window") or {}).get("role")
        != "pre_d3_public_development_only"
        or (inputs.get("data_isolation") or {}).get("d3_outcomes_read") is not False
        or (inputs.get("data_isolation") or {}).get("two_system_blind_outcomes_read")
        is not False
    ):
        raise ValueError("forecast_closure_development_input_report_invalid")

    topology_body = topology_report_path.read_bytes()
    topology = json.loads(topology_body)
    if (
        topology.get("schema") != TOPOLOGY_SCHEMA
        or topology.get("status") != "pass_full_incremental_subnetwork_compiled"
        or inputs["topology_report"]["sha256"]
        != hashlib.sha256(topology_body).hexdigest()
    ):
        raise ValueError("forecast_closure_development_topology_invalid")
    network_body = _read_verified(topology["artifacts"]["full_subnetwork"])
    network = _network(json.loads(network_body)["network"])
    route_link_body = _read_verified(topology["artifacts"]["route_link_subset"])
    route_link_path = REPO_ROOT / topology["artifacts"]["route_link_subset"]["path"]
    geometry = _geometry(route_link_path, network, route_link_body)

    arrays = {
        name: _read_npy(descriptor)
        for name, descriptor in inputs["decoded_arrays"].items()
    }
    feature_ids = tuple(int(value) for value in arrays["feature_ids"])
    initial_storage = np.asarray(arrays["initial_storage_m3"], dtype=float)
    q_lateral = np.asarray(arrays["q_lateral_m3s"], dtype=float)
    timestamps = tuple(str(value) for value in arrays["forcing_timestamps_utc"])
    expected_timestamps = tuple(
        _iso(START + timedelta(hours=value)) for value in range(HOUR_COUNT)
    )
    if (
        feature_ids != network.feature_ids
        or initial_storage.shape != (len(feature_ids),)
        or q_lateral.shape != (HOUR_COUNT, len(feature_ids))
        or timestamps != expected_timestamps
    ):
        raise ValueError("forecast_closure_development_dynamic_axis_mismatch")

    panel_report_body = panel_report_path.read_bytes()
    panel_report = json.loads(panel_report_body)
    if (
        panel_report.get("schema") != PANEL_SCHEMA
        or panel_report.get("status")
        != "compiled_with_observation_gap_not_admitted"
        or (panel_report.get("window") or {}).get("warmup_hours") != FIT_HOURS
        or (panel_report.get("quality_summary") or {}).get(
            "warmup_outcome_missing_hour_count"
        )
        != 0
    ):
        raise ValueError("forecast_closure_development_panel_report_invalid")
    panel_body = _read_descriptor(panel_report["panel_artifact"])
    panel = _parse_panel(panel_body)

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
        support_method=(
            "D2 audited terminal support plus full support for complete branches"
        ),
        provenance_id=(
            f"{prior_domain.forcing_support_central.provenance_id}|"
            "forecast-closure-development"
        ),
        evidence_level="derived",
        admitted_as_spatial_support=True,
    )
    operator = BranchingManningNetworkTransportOperator(
        network,
        BranchingNetworkTransportConfig(
            timestep_seconds=3600.0,
            integration_substep_seconds=300.0,
            operator_form_admitted=True,
        ),
    )
    action_index = network.feature_ids.index(network.action_entry_feature_ids[0])
    outlet_index = network.feature_ids.index(network.outlet_feature_id)
    reference_storage = tuple(
        max(
            float(initial_storage[index]),
            network.effective_lengths_m[index]
            * geometry.bottom_width_m[index]
            * 0.01,
            1.0,
        )
        for index in range(len(feature_ids))
    )
    identity_parameters = StateDependentManningClosureParameters(
        feature_ids=network.feature_ids,
        reference_storage_m3=reference_storage,
        log_roughness_intercept=(0.0,) * len(feature_ids),
        log_roughness_storage_slope=(0.0,) * len(feature_ids),
        training_system_ids=("identity-physical-baseline",),
        training_data_start=datetime(2020, 1, 1, tzinfo=timezone.utc),
        training_data_end=datetime(2020, 1, 2, tzinfo=timezone.utc),
        provenance_id="identity-forecast-closure:no-outcome-calibration",
        evidence_level="derived",
        admitted=True,
        outcome_calibrated=False,
    )
    closure_config = _closure_config()
    identity_wrapper = ForecastClosedBranchingTransportOperator(
        operator,
        CausalStateDependentManningForecastClosure(
            identity_parameters,
            closure_config,
        ),
    )
    baseline_state = StockState(
        values=tuple(float(value) for value in initial_storage),
        unit="m3",
        provenance_id=(
            "nwm-v3-development-modeled-initial-state:"
            f"{inputs['decoded_arrays']['initial_storage_m3']['sha256']}"
        ),
    )
    fit_predictions: list[float] = []
    fit_storages: list[float] = []
    fit_targets: list[float] = []
    warmup_mass_ratios: list[float] = []
    observation_update_count = 0
    for hour in range(ACTIVATION_INDEX):
        issue_time = START + timedelta(hours=hour)
        observation = _available_observation(panel, issue_time, network.outlet_feature_id)
        action, forcing = _fields(
            panel,
            q_lateral,
            hour,
            action_index,
            len(feature_ids),
        )
        result = identity_wrapper.step(
            baseline_state,
            geometry,
            issue_time=issue_time,
            observations=(() if observation is None else (observation,)),
            action=action,
            forcing=forcing,
            forcing_support=forcing_support,
        )
        baseline_state = result.transport.next_stock
        warmup_mass_ratios.append(
            abs(result.forecast_cycle_mass_balance_residual_m3)
            / result.forecast_cycle_mass_tolerance_m3
        )
        observation_update_count += int(observation is not None)
        if hour < FIT_HOURS:
            target = panel[hour]["outcome"]
            if target is None:
                raise ValueError("forecast_closure_fit_target_must_be_complete")
            fit_predictions.append(result.outlet_mean_flow_m3s)
            fit_storages.append(result.closure.analysis_stock.values[outlet_index])
            fit_targets.append(float(target))

    intercept, slope, fit_details = _fit_shared_roughness_residual(
        predicted=np.asarray(fit_predictions, dtype=float),
        observed=np.asarray(fit_targets, dtype=float),
        storage=np.asarray(fit_storages, dtype=float),
        reference_storage=reference_storage[outlet_index],
    )
    training_start = START + timedelta(hours=1)
    training_end = START + timedelta(hours=FIT_HOURS)
    parameter_provenance = (
        "center-hill-pre-d3-shared-roughness|"
        f"inputs={hashlib.sha256(input_body).hexdigest()}|"
        f"panel={hashlib.sha256(panel_body).hexdigest()}"
    )
    fitted_parameters = StateDependentManningClosureParameters(
        feature_ids=network.feature_ids,
        reference_storage_m3=reference_storage,
        log_roughness_intercept=(intercept,) * len(feature_ids),
        log_roughness_storage_slope=(slope,) * len(feature_ids),
        training_system_ids=("center_hill:2021-12-09:pre-d3-development",),
        training_data_start=training_start,
        training_data_end=training_end,
        provenance_id=parameter_provenance,
        evidence_level="derived",
        admitted=True,
        outcome_calibrated=True,
    )
    parameter_payload = {
        "schema": PARAMETER_ARTIFACT_SCHEMA,
        "parameterization": {
            "family": "shared_state_dependent_log_roughness_residual",
            "free_parameter_count": 2,
            "shared_across_feature_count": len(feature_ids),
            "ridge_penalty": RIDGE_PENALTY,
            "roughness_multiplier_bounds": list(ROUGHNESS_MULTIPLIER_BOUNDS),
        },
        "observation_policy": _observation_policy(),
        "fit": fit_details,
        "forecast_closure_parameters": fitted_parameters.as_dict(),
        "data_isolation": {
            "fit_window": "2021-12-09T01Z/2021-12-16T01Z",
            "d3_outcomes_used": False,
            "two_system_blind_outcomes_used": False,
        },
        "claim_boundary": {
            "public_development_parameters_fitted": True,
            "cross_system_transfer_validated": False,
            "predictive_improvement_validated": False,
            "geospatial_kernel_validated": False,
        },
    }
    parameter_body = (
        json.dumps(parameter_payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")

    wrappers = {
        "candidate": ForecastClosedBranchingTransportOperator(
            operator,
            CausalStateDependentManningForecastClosure(
                fitted_parameters,
                closure_config,
            ),
        ),
        "state_update_only": identity_wrapper,
        "residual_no_update": ForecastClosedBranchingTransportOperator(
            operator,
            CausalStateDependentManningForecastClosure(
                fitted_parameters,
                closure_config,
            ),
        ),
        "identity_no_update": identity_wrapper,
    }
    states = {
        name: StockState(
            values=baseline_state.values,
            unit="m3",
            provenance_id=f"shared-activation-state:{name}",
        )
        for name in wrappers
    }
    mass_ratios = {name: [] for name in wrappers}
    cycle_analysis_increment = {name: 0.0 for name in wrappers}
    clipping_counts = {name: 0 for name in wrappers}
    rows: list[dict[str, object]] = []
    for hour in range(ACTIVATION_INDEX, HOUR_COUNT):
        issue_time = START + timedelta(hours=hour)
        support_end = issue_time + timedelta(hours=1)
        observation = _available_observation(panel, issue_time, network.outlet_feature_id)
        observation_tuple = () if observation is None else (observation,)
        action, forcing = _fields(
            panel,
            q_lateral,
            hour,
            action_index,
            len(feature_ids),
        )
        predictions: dict[str, float] = {}
        candidate_result = None
        for name, wrapper in wrappers.items():
            use_observation = name in {"candidate", "state_update_only"}
            result = wrapper.step(
                states[name],
                geometry,
                issue_time=issue_time,
                observations=(observation_tuple if use_observation else ()),
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
            cycle_analysis_increment[name] += result.analysis_increment_m3
            clipping_counts[name] += sum(result.closure.residual_clipped)
            if name == "candidate":
                candidate_result = result
        assert candidate_result is not None
        prior_outcome = panel[hour - 1]["outcome"]
        latency_value = None if observation is None else observation.discharge_m3s
        rows.append(
            {
                "support_start_utc": _iso(issue_time),
                "support_end_utc": _iso(support_end),
                "split_role": "development_diagnostic",
                "observed_discharge_m3s": _optional(panel[hour]["outcome"]),
                "one_hour_persistence_m3s": _optional(prior_outcome),
                "latency_matched_persistence_m3s": _optional(latency_value),
                "candidate_m3s": predictions["candidate"],
                "state_update_only_m3s": predictions["state_update_only"],
                "residual_no_update_m3s": predictions["residual_no_update"],
                "identity_no_update_m3s": predictions["identity_no_update"],
                "closure_observation_valid_at_utc": (
                    "" if observation is None else _iso(observation.valid_at)
                ),
                "candidate_outlet_roughness_multiplier": (
                    candidate_result.closure.applied_roughness_multiplier[
                        outlet_index
                    ]
                ),
                "candidate_analysis_increment_m3": (
                    candidate_result.analysis_increment_m3
                ),
            }
        )
    prediction_body = _encode_rows(rows)
    metrics, scoring = _score(rows)
    parameter_artifact = _artifact(parameter_output_path, parameter_body)
    prediction_artifact = _artifact(prediction_output_path, prediction_body)
    report = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "public_development_training_and_diagnostic_complete",
        "source_artifacts": {
            "development_input_report": _artifact(input_report_path, input_body),
            "topology_report": _artifact(topology_report_path, topology_body),
            "full_subnetwork": topology["artifacts"]["full_subnetwork"],
            "route_link_subset": topology["artifacts"]["route_link_subset"],
            "development_panel_report": _artifact(
                panel_report_path,
                panel_report_body,
            ),
            "development_panel": panel_report["panel_artifact"],
            "prior_mainstem_support": prior_artifacts["forcing_support"],
        },
        "outputs": {
            "parameters": parameter_artifact,
            "predictions": prediction_artifact,
        },
        "window": {
            "input_start": _iso(START),
            "input_end_exclusive": _iso(END),
            "fit_target_start": _iso(training_start),
            "fit_target_end_inclusive": _iso(training_end),
            "fit_hour_count": FIT_HOURS,
            "activation_issue_time": _iso(
                START + timedelta(hours=ACTIVATION_INDEX)
            ),
            "diagnostic_hour_count": HOUR_COUNT - ACTIVATION_INDEX,
            "role": "public_development_only_not_validation",
        },
        "parameterization": parameter_payload["parameterization"],
        "observation_policy": _observation_policy(),
        "fit": fit_details,
        "scoring": scoring,
        "metrics": metrics,
        "conservation": {
            "warmup_maximum_cycle_residual_to_tolerance_ratio": max(
                warmup_mass_ratios
            ),
            "scenario_maximum_cycle_residual_to_tolerance_ratio": {
                name: max(values) for name, values in mass_ratios.items()
            },
            "all_scenarios_passed": all(
                max(values) <= 1.0 for values in mass_ratios.values()
            ),
            "analysis_increment_total_m3": cycle_analysis_increment,
            "constitutive_residual_external_mass": False,
        },
        "diagnostics": {
            "warmup_observation_update_count": observation_update_count,
            "scenario_clipped_feature_step_count": clipping_counts,
            "candidate_beats_state_update_only_rmse": (
                metrics["candidate"]["rmse_m3s"]
                < metrics["state_update_only"]["rmse_m3s"]
            ),
            "candidate_beats_identity_no_update_rmse": (
                metrics["candidate"]["rmse_m3s"]
                < metrics["identity_no_update"]["rmse_m3s"]
            ),
            "candidate_beats_one_hour_persistence_rmse": (
                metrics["candidate"]["rmse_m3s"]
                < metrics["one_hour_persistence"]["rmse_m3s"]
            ),
        },
        "data_isolation": {
            "only_pre_d3_development_outcomes_used": True,
            "d3_outcomes_used": False,
            "two_system_blind_outcomes_used": False,
            "missing_outcomes_imputed": False,
            "fit_targets_end_before_activation_issue": training_end
            < START + timedelta(hours=ACTIVATION_INDEX),
        },
        "claim_boundary": {
            "public_development_parameters_fitted": True,
            "development_diagnostic_scored": True,
            "operational_observation_vintage_verified": False,
            "cross_system_transfer_validated": False,
            "predictive_improvement_validated": False,
            "forecast_closure_validated": False,
            "geospatial_kernel_validated": False,
            "untouched_multi_system_window_required": True,
        },
    }
    if not report["conservation"]["all_scenarios_passed"]:
        raise RuntimeError("forecast_closure_development_conservation_failed")
    return parameter_body, prediction_body, report


def _closure_config() -> ForecastClosureConfig:
    return ForecastClosureConfig(
        observation_update=CausalObservationUpdateConfig(
            analysis_gain=1.0,
            maximum_observation_age_seconds=MAXIMUM_OBSERVATION_AGE_SECONDS,
            accepted_quality_statuses=("approved",),
            require_authoritative_evidence=False,
        ),
        minimum_roughness_multiplier=ROUGHNESS_MULTIPLIER_BOUNDS[0],
        maximum_roughness_multiplier=ROUGHNESS_MULTIPLIER_BOUNDS[1],
    )


def _observation_policy() -> dict[str, object]:
    return {
        "analysis_gain": 1.0,
        "gain_selected_by_outcome_search": False,
        "source_support": "previous_hour_interval_sample_mean",
        "assumed_publication_lag_seconds": int(
            OBSERVATION_PUBLICATION_LAG.total_seconds()
        ),
        "maximum_observation_age_seconds": MAXIMUM_OBSERVATION_AGE_SECONDS,
        "quality_status": "approved",
        "evidence_level": "derived",
        "operational_vintage_availability_verified": False,
        "missing_observation_policy": "use_latest_available_within_age_else_no_update",
        "missing_observation_imputation": False,
    }


def _available_observation(
    panel: list[dict[str, Any]],
    issue_time: datetime,
    outlet_feature_id: int,
) -> CausalDischargeObservation | None:
    for row in reversed(panel):
        valid_at = row["support_end"]
        available_at = valid_at + OBSERVATION_PUBLICATION_LAG
        if available_at > issue_time or row["outcome"] is None:
            continue
        age = (issue_time - valid_at).total_seconds()
        if age > MAXIMUM_OBSERVATION_AGE_SECONDS:
            return None
        return CausalDischargeObservation(
            feature_id=outlet_feature_id,
            discharge_m3s=float(row["outcome"]),
            valid_at=valid_at,
            available_at=available_at,
            quality_status="approved",
            provenance_id=(
                "USGS-03424860:00060:derived-hourly-interval-sample-mean:"
                f"{_iso(valid_at)}"
            ),
            evidence_level="derived",
        )
    return None


def _fields(
    panel: list[dict[str, Any]],
    q_lateral: np.ndarray,
    hour: int,
    action_index: int,
    feature_count: int,
) -> tuple[ActionBoundaryFlux, ForcingFlux]:
    action_values = np.zeros(feature_count, dtype=float)
    action_values[action_index] = panel[hour]["action"]
    return (
        ActionBoundaryFlux(
            values=tuple(float(value) for value in action_values),
            unit="m3 s-1",
            provenance_id=f"center-hill:development:action:{hour:03d}",
        ),
        ForcingFlux(
            values=tuple(float(value) for value in q_lateral[hour]),
            unit="m3 s-1",
            provenance_id=f"nwm-v3:development:q-lateral:{hour:03d}",
            modeled=True,
        ),
    )


def _fit_shared_roughness_residual(
    *,
    predicted: np.ndarray,
    observed: np.ndarray,
    storage: np.ndarray,
    reference_storage: float,
) -> tuple[float, float, dict[str, Any]]:
    valid = (
        np.isfinite(predicted)
        & np.isfinite(observed)
        & np.isfinite(storage)
        & (predicted > 0.0)
        & (observed > 0.0)
        & (storage >= 0.0)
    )
    if int(valid.sum()) != FIT_HOURS:
        raise ValueError("forecast_closure_fit_requires_complete_positive_targets")
    lower_log = np.log(ROUGHNESS_MULTIPLIER_BOUNDS[0])
    upper_log = np.log(ROUGHNESS_MULTIPLIER_BOUNDS[1])
    target = np.clip(np.log(predicted[valid] / observed[valid]), lower_log, upper_log)
    state_feature = np.log1p(storage[valid] / reference_storage) - np.log(2.0)
    design = np.column_stack((np.ones_like(state_feature), state_feature))
    penalty = np.diag((0.0, RIDGE_PENALTY))
    coefficients = np.linalg.solve(
        design.T @ design + penalty,
        design.T @ target,
    )
    fitted = design @ coefficients
    return (
        float(coefficients[0]),
        float(coefficients[1]),
        {
            "sample_count": int(valid.sum()),
            "target_definition": "log(identity_prediction/observed_discharge)",
            "target_clipped_to_log_multiplier_bounds": True,
            "intercept": float(coefficients[0]),
            "storage_slope": float(coefficients[1]),
            "ridge_penalty_on_slope": RIDGE_PENALTY,
            "fit_rmse_log_multiplier": float(
                np.sqrt(np.mean((fitted - target) ** 2))
            ),
            "target_minimum": float(target.min()),
            "target_maximum": float(target.max()),
            "state_feature_minimum": float(state_feature.min()),
            "state_feature_maximum": float(state_feature.max()),
        },
    )


def _parse_panel(body: bytes) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    required = {
        "support_start_utc",
        "support_end_utc",
        "split_role",
        "action_release_m3s",
        "outcome_discharge_interval_sample_mean_m3s",
        "outcome_available",
        "usgs_qualifier",
    }
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValueError("forecast_closure_development_panel_columns_invalid")
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(reader):
        start = _parse_utc(row["support_start_utc"])
        end = _parse_utc(row["support_end_utc"])
        expected_role = "warmup" if index < FIT_HOURS else "development"
        available = row["outcome_available"].lower() == "true"
        outcome = (
            float(row["outcome_discharge_interval_sample_mean_m3s"])
            if available
            else None
        )
        if (
            start != START + timedelta(hours=index)
            or end != start + timedelta(hours=1)
            or row["split_role"] != expected_role
            or (available and row["usgs_qualifier"] != "A")
        ):
            raise ValueError("forecast_closure_development_panel_row_invalid")
        rows.append(
            {
                "support_start": start,
                "support_end": end,
                "action": float(row["action_release_m3s"]),
                "outcome": outcome,
            }
        )
    if len(rows) != HOUR_COUNT:
        raise ValueError("forecast_closure_development_panel_hour_count_mismatch")
    return rows


def _score(
    rows: list[dict[str, object]],
) -> tuple[dict[str, dict[str, float]], dict[str, object]]:
    names = (
        "candidate",
        "state_update_only",
        "residual_no_update",
        "identity_no_update",
        "one_hour_persistence",
        "latency_matched_persistence",
    )
    observed: list[float] = []
    values = {name: [] for name in names}
    omitted: list[str] = []
    for row in rows:
        if row["observed_discharge_m3s"] == "" or row["one_hour_persistence_m3s"] == "":
            omitted.append(str(row["support_end_utc"]))
            continue
        observed.append(float(row["observed_discharge_m3s"]))
        for name in names:
            value = row[f"{name}_m3s"]
            values[name].append(np.nan if value == "" else float(value))
    observed_values = np.asarray(observed, dtype=float)
    metrics: dict[str, dict[str, float]] = {}
    sample_counts: dict[str, int] = {}
    for name in names:
        predicted = np.asarray(values[name], dtype=float)
        mask = np.isfinite(predicted)
        metrics[name] = _metrics(observed_values[mask], predicted[mask])
        sample_counts[name] = int(mask.sum())
    return metrics, {
        "primary_comparison_support": (
            "target and one-hour-persistence both available; no imputation"
        ),
        "diagnostic_row_count": len(rows),
        "primary_candidate_sample_count": sample_counts["candidate"],
        "per_model_sample_count": sample_counts,
        "omitted_support_end_utc": omitted,
    }


def _metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    if not observed.size or observed.shape != predicted.shape:
        raise ValueError("forecast_closure_metric_axis_invalid")
    error = predicted - observed
    denominator = float(np.sum((observed - observed.mean()) ** 2))
    return {
        "rmse_m3s": float(np.sqrt(np.mean(error**2))),
        "mae_m3s": float(np.mean(np.abs(error))),
        "bias_m3s": float(np.mean(error)),
        "nse": float(1.0 - np.sum(error**2) / denominator),
    }


def _read_descriptor(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("forecast_closure_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("forecast_closure_artifact_identity_mismatch")
    return body


def _encode_rows(rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        display = resolved.as_posix()
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _optional(value: Any) -> Any:
    return "" if value is None else value


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("forecast_closure_timestamp_timezone_required")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    args = parse_args()
    parameter_body, prediction_body, report = compile_training(
        input_report_path=args.input_report,
        topology_report_path=args.topology_report,
        panel_report_path=args.panel_report,
        parameter_output_path=args.parameters,
        prediction_output_path=args.predictions,
    )
    args.parameters.parent.mkdir(parents=True, exist_ok=True)
    args.parameters.write_bytes(parameter_body)
    args.predictions.parent.mkdir(parents=True, exist_ok=True)
    args.predictions.write_bytes(prediction_body)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.parameters)
    print(args.predictions)
    print(args.report)
    print(json.dumps(report["metrics"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
