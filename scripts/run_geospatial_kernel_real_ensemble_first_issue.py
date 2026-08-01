#!/usr/bin/env python3
"""Run the physical ensemble cycle on the first sealed real-system issue."""

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

from data_agent.uwm.geospatial_kernel_v2 import (
    BranchingNetworkTransportConfig,
    CausalDischargeObservation,
    ReachForcingSupport,
    StockState,
)
from data_agent.uwm.geospatial_kernel_v2.ensemble_graph_state_estimation import (
    LocalizedEnsembleStateEstimator,
    LocalizedEnsembleStateEstimatorConfig,
)
from data_agent.uwm.geospatial_kernel_v2.ensemble_manning_forecast_cycle import (
    GRAPH_PARTITION_ENSEMBLE_SEMANTICS,
    PhysicalEnsembleManningForecastCycle,
    build_graph_partition_physical_ensemble_design,
    build_symmetric_physical_ensemble_design,
)
from data_agent.uwm.geospatial_kernel_v2.physical_uncertainty_profile import (
    PHYSICAL_UNCERTAINTY_PROFILE_SCHEMA,
    FeatureAlignedPhysicalUncertaintyProfile,
    PhysicalUncertaintySource,
)

if __package__:
    from scripts.run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
        _geometry,
        _network,
        _read_npy,
    )
else:
    from run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
        _geometry,
        _network,
        _read_npy,
    )

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_protocol.json"
)
DEFAULT_STATIC_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_static_inputs_report.json"
)
DEFAULT_SEALED_ROLLOUT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_rollout_report.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_real_ensemble_first_issue_report.json"
)
DEFAULT_GRAPH_PARTITION_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_real_graph_partition_ensemble_first_issue_report.json"
)
DEFAULT_EXTERNAL_PROFILE_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_external_physical_uncertainty_profiles.json"
)
DEFAULT_EXTERNAL_PROFILE_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_real_external_profile_ensemble_first_issue_report.json"
)

SCHEMA = "gwm.geospatial_kernel.real_ensemble_first_issue.v1"
PROTOCOL_SCHEMA = "gwm.geotransport.horizon_assimilation_holdout_protocol.v1"
STATIC_SCHEMA = "gwm.geotransport.horizon_assimilation_holdout_static_inputs.v1"
ROLLOUT_SCHEMA = "gwm.geotransport.horizon_assimilation_holdout_rollout.v1"
EXTERNAL_PROFILE_REPORT_SCHEMA = (
    "gwm.geospatial_kernel.external_physical_uncertainty_profiles.v1"
)
SYSTEM_IDS = ("center_hill", "j_percy_priest")
HORIZONS_HOURS = (1, 3, 6, 12)
MODES = (
    "nominal",
    "outlet_only_observation_update",
    "linear_distance_localized_mainstem_update",
    "quadratic_distance_localized_mainstem_update",
)
PREDICTION_COLUMNS = (
    "issue_index",
    "issue_time_utc",
    "system_id",
    "mode",
    "horizon_hours",
    "target_time_utc",
    "predicted_outlet_m3s",
    "selected_by_policy",
    "issue_observed_outlet_m3s",
    "observation_fallback_reason",
)

TIMESTEP_SECONDS = 3600.0
SUBSTEP_SECONDS = 300.0
FORECAST_HOURS = 12
INITIAL_STORAGE_FRACTION = 0.10
MANNING_N_FRACTION = 0.10
MODELED_FORCING_FRACTION = 0.20
LOCALIZATION_RADIUS_M = 100_000.0
OBSERVATION_ERROR_RELATIVE_FRACTION = 0.10
OBSERVATION_ERROR_ABSOLUTE_FLOOR_M3S = 1.0
SYMMETRIC_ENSEMBLE_DESIGN = "symmetric_one_factor_at_a_time"
GRAPH_PARTITION_ENSEMBLE_DESIGN = "graph_partition"
EXTERNAL_PROFILE_GRAPH_PARTITION_ENSEMBLE_DESIGN = (
    "external_profile_graph_partition"
)
ENSEMBLE_DESIGNS = (
    SYMMETRIC_ENSEMBLE_DESIGN,
    GRAPH_PARTITION_ENSEMBLE_DESIGN,
    EXTERNAL_PROFILE_GRAPH_PARTITION_ENSEMBLE_DESIGN,
)
GRAPH_PARTITION_MODE_COUNT = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--static-report", type=Path, default=DEFAULT_STATIC_REPORT)
    parser.add_argument(
        "--sealed-rollout-report",
        type=Path,
        default=DEFAULT_SEALED_ROLLOUT_REPORT,
    )
    parser.add_argument(
        "--ensemble-design",
        choices=ENSEMBLE_DESIGNS,
        default=SYMMETRIC_ENSEMBLE_DESIGN,
    )
    parser.add_argument(
        "--external-profile-report",
        type=Path,
        default=DEFAULT_EXTERNAL_PROFILE_REPORT,
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def compile_real_ensemble_first_issue_report(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    static_report_path: Path = DEFAULT_STATIC_REPORT,
    sealed_rollout_report_path: Path = DEFAULT_SEALED_ROLLOUT_REPORT,
    external_profile_report_path: Path = DEFAULT_EXTERNAL_PROFILE_REPORT,
    ensemble_design: str = SYMMETRIC_ENSEMBLE_DESIGN,
) -> dict[str, Any]:
    """Execute both real systems using only issue-time and earlier observations."""

    if ensemble_design not in ENSEMBLE_DESIGNS:
        raise ValueError("real_ensemble_design_invalid")
    protocol_body = protocol_path.read_bytes()
    protocol = json.loads(protocol_body)
    static_body = static_report_path.read_bytes()
    static_report = json.loads(static_body)
    rollout_body = sealed_rollout_report_path.read_bytes()
    rollout_report = json.loads(rollout_body)
    _validate_reports(
        protocol=protocol,
        protocol_body=protocol_body,
        static_report=static_report,
        static_body=static_body,
        rollout_report=rollout_report,
    )

    external_profile_body: bytes | None = None
    external_profile_report: Mapping[str, Any] | None = None
    if ensemble_design == EXTERNAL_PROFILE_GRAPH_PARTITION_ENSEMBLE_DESIGN:
        external_profile_body = external_profile_report_path.read_bytes()
        external_profile_report = json.loads(external_profile_body)
        _validate_external_profile_report(
            report=external_profile_report,
            protocol_body=protocol_body,
            static_body=static_body,
        )

    prediction_descriptor = rollout_report["prediction_artifact"]
    prediction_body = _read_verified(prediction_descriptor)
    issue_time = _parse_time(protocol["window"]["issue_times_utc"][0])
    reference_time = _parse_time(protocol["window"]["initial_state_valid_at_utc"])
    if issue_time - reference_time != timedelta(hours=1):
        raise ValueError("real_ensemble_first_issue_history_axis_invalid")
    observations = _issue_observations(
        prediction_body,
        issue_time=issue_time,
    )

    systems: dict[str, Any] = {}
    for system_id in SYSTEM_IDS:
        systems[system_id] = _run_system(
            system_id=system_id,
            lock=protocol["systems"][system_id],
            inputs=static_report["systems"][system_id],
            issue_observation_m3s=observations[system_id],
            issue_time=issue_time,
            reference_time=reference_time,
            prediction_descriptor=prediction_descriptor,
            ensemble_design=ensemble_design,
            uncertainty_profile_payload=(
                external_profile_report["systems"][system_id]
                if external_profile_report is not None
                else None
            ),
        )

    all_gates_passed = all(
        system["execution_gates"]["all_passed"] for system in systems.values()
    )
    if not all_gates_passed:
        raise RuntimeError("real_ensemble_first_issue_execution_gate_failed")
    member_counts = {system["ensemble_member_count"] for system in systems.values()}
    if len(member_counts) != 1:
        raise RuntimeError("real_ensemble_cross_system_member_count_mismatch")
    member_count = member_counts.pop()
    graph_mode_count = (
        GRAPH_PARTITION_MODE_COUNT
        if ensemble_design
        in (
            GRAPH_PARTITION_ENSEMBLE_DESIGN,
            EXTERNAL_PROFILE_GRAPH_PARTITION_ENSEMBLE_DESIGN,
        )
        else 0
    )
    return {
        "schema": SCHEMA,
        "status": "real_two_system_first_issue_ensemble_cycle_executed",
        "issue_time_utc": _iso(issue_time),
        "reference_time_utc": _iso(reference_time),
        "design": {
            "ensemble_design": ensemble_design,
            "ensemble_member_count": member_count,
            "graph_partition_mode_count": graph_mode_count,
            "graph_partition_semantics": (
                GRAPH_PARTITION_ENSEMBLE_SEMANTICS
                if graph_mode_count
                else None
            ),
            "forecast_horizon_hours": FORECAST_HOURS,
            "timestep_seconds": TIMESTEP_SECONDS,
            "integration_substep_seconds": SUBSTEP_SECONDS,
            "initial_storage_fraction": (
                None
                if external_profile_report is not None
                else INITIAL_STORAGE_FRACTION
            ),
            "manning_n_fraction": (
                None if external_profile_report is not None else MANNING_N_FRACTION
            ),
            "modeled_forcing_fraction": (
                None
                if external_profile_report is not None
                else MODELED_FORCING_FRACTION
            ),
            "localization_radius_m": LOCALIZATION_RADIUS_M,
            "observation_error_model": {
                "relative_fraction": OBSERVATION_ERROR_RELATIVE_FRACTION,
                "absolute_floor_m3s": OBSERVATION_ERROR_ABSOLUTE_FLOOR_M3S,
            },
            "per_feature_sample_variance_by_source": (
                "feature_fraction_squared_divided_by_three"
                if external_profile_report is not None
                else {
                    "initial_storage_multiplier": (
                        INITIAL_STORAGE_FRACTION**2 / 3.0
                    ),
                    "manning_n_multiplier": MANNING_N_FRACTION**2 / 3.0,
                    "modeled_forcing_multiplier": (
                        MODELED_FORCING_FRACTION**2 / 3.0
                    ),
                }
            ),
            **(
                {"external_feature_profile_used": True}
                if external_profile_report is not None
                else {}
            ),
            "spatial_modes_derived_from_topology_only": bool(graph_mode_count),
            "issue_observation_used_to_construct_members": False,
            "perturbations_selected_without_future_target_fit": True,
        },
        "time_alignment": {
            "initial_modeled_state_valid_at_utc": _iso(reference_time),
            "analysis_observation_valid_at_utc": _iso(issue_time),
            "historical_transition_support": "[reference_time, issue_time]",
            "historical_cwms_action_timestamp_role": "support_end",
            "historical_nwm_q_lateral_timestamp_role": (
                "assumed_support_end_for_hourly_transition"
            ),
            "nwm_q_lateral_interval_support_verified": False,
            "forecast_action_rows_start_at_issue_time": True,
            "forecast_q_lateral_rows_start_after_issue_time": True,
        },
        "input_artifacts": {
            "protocol": _artifact(protocol_path, protocol_body),
            "static_input_report": _artifact(static_report_path, static_body),
            "outcome_free_rollout_report": _artifact(
                sealed_rollout_report_path,
                rollout_body,
            ),
            "sealed_prediction_source": dict(prediction_descriptor),
            **(
                {
                    "external_physical_uncertainty_profile": _artifact(
                        external_profile_report_path, external_profile_body
                    )
                }
                if external_profile_body is not None
                else {}
            ),
        },
        "systems": systems,
        "execution_gates": {
            "system_count": len(systems),
            "all_system_gates_passed": all_gates_passed,
        },
        "data_isolation": {
            "input_accepts_outcome_path": False,
            "input_accepts_future_target": False,
            "input_accepts_score_or_loss": False,
            "future_target_values_loaded": False,
            "outcome_artifact_loaded": False,
            "scoring_artifact_loaded": False,
            "forecast_skill_computed": False,
            "issue_observation_source": (
                "sealed_outcome_free_predictions_issue_observed_outlet_m3s"
            ),
            "historical_issue_observation_publication_at_issue_time_verified": False,
        },
        "claim_boundary": {
            "real_center_hill_cycle_executed": True,
            "real_j_percy_priest_cycle_executed": True,
            "physical_ensemble_cycle_integrated": True,
            "graph_partition_ensemble_executed": bool(graph_mode_count),
            **(
                {"external_physical_uncertainty_profile_executed": True}
                if external_profile_report is not None
                else {}
            ),
            "development_integration_only": True,
            "candidate_admitted": False,
            "runtime_default_enabled": False,
            "forecast_skill_scored": False,
            "predictive_validation_complete": False,
            "geospatial_kernel_validated": False,
            "superiority_claim_supported": False,
        },
    }


def _run_system(
    *,
    system_id: str,
    lock: Mapping[str, Any],
    inputs: Mapping[str, Any],
    issue_observation_m3s: float,
    issue_time: datetime,
    reference_time: datetime,
    prediction_descriptor: Mapping[str, Any],
    ensemble_design: str,
    uncertainty_profile_payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if inputs.get("topology_report") != lock.get("topology_report"):
        raise ValueError(f"real_ensemble_{system_id}_topology_identity_mismatch")
    topology_body = _read_verified(lock["topology_report"])
    topology = json.loads(topology_body)
    network_body = _read_verified(topology["artifacts"]["full_subnetwork"])
    network_payload = json.loads(network_body)
    network = _network(network_payload["network"])
    if (
        len(network.feature_ids) != int(lock["feature_count"])
        or network.outlet_feature_id != int(lock["outlet_feature_id"])
        or network.action_entry_feature_ids != (int(lock["action_entry_feature_id"]),)
    ):
        raise ValueError(f"real_ensemble_{system_id}_network_lock_mismatch")

    arrays = {
        name: _read_npy(descriptor)
        for name, descriptor in inputs["decoded_arrays"].items()
    }
    feature_ids = tuple(int(value) for value in arrays["feature_ids"])
    initial_storage = np.asarray(arrays["initial_storage_m3"], dtype=float)
    q_lateral = np.asarray(arrays["q_lateral_m3s"], dtype=float)
    forcing_times = tuple(str(value) for value in arrays["forcing_timestamps_utc"])
    if (
        feature_ids != network.feature_ids
        or initial_storage.shape != (len(feature_ids),)
        or q_lateral.shape != (672, len(feature_ids))
        or forcing_times[0] != _iso(issue_time)
        or forcing_times[FORECAST_HOURS] != _iso(
            issue_time + timedelta(hours=FORECAST_HOURS)
        )
    ):
        raise ValueError(f"real_ensemble_{system_id}_dynamic_axis_mismatch")

    route_link = topology["artifacts"]["route_link_subset"]
    route_link_body = _read_verified(route_link)
    geometry = _geometry(REPO_ROOT / route_link["path"], network, route_link_body)
    forcing_support = _forcing_support(
        system_id=system_id,
        lock=lock,
        feature_ids=feature_ids,
        outlet_feature_id=network.outlet_feature_id,
    )
    actions = _parse_actions(_read_verified(inputs["action_values"]))
    historical_release_m3s = _historical_release_at_support_end(
        _read_verified(inputs["action_raw"]),
        support_end=issue_time,
    )
    action_index = feature_ids.index(network.action_entry_feature_ids[0])
    historical_action = np.zeros((1, len(feature_ids)), dtype=float)
    historical_action[0, action_index] = historical_release_m3s
    forecast_action = np.zeros((FORECAST_HOURS, len(feature_ids)), dtype=float)
    for offset in range(FORECAST_HOURS):
        forecast_action[offset, action_index] = actions[
            issue_time + timedelta(hours=offset)
        ]

    uncertainty_profile: FeatureAlignedPhysicalUncertaintyProfile | None = None
    if ensemble_design == SYMMETRIC_ENSEMBLE_DESIGN:
        members = build_symmetric_physical_ensemble_design(
            feature_ids=feature_ids,
            initial_storage_fraction=INITIAL_STORAGE_FRACTION,
            manning_n_fraction=MANNING_N_FRACTION,
            forcing_fraction=MODELED_FORCING_FRACTION,
        )
    elif ensemble_design == GRAPH_PARTITION_ENSEMBLE_DESIGN:
        members = build_graph_partition_physical_ensemble_design(
            network=network,
            initial_storage_fraction=INITIAL_STORAGE_FRACTION,
            manning_n_fraction=MANNING_N_FRACTION,
            forcing_fraction=MODELED_FORCING_FRACTION,
            graph_partition_mode_count=GRAPH_PARTITION_MODE_COUNT,
        )
    else:
        if uncertainty_profile_payload is None:
            raise ValueError("real_ensemble_external_profile_required")
        uncertainty_profile = _uncertainty_profile(
            uncertainty_profile_payload,
            expected_system_id=system_id,
            expected_feature_ids=feature_ids,
            expected_evaluation_start=issue_time,
        )
        members = build_graph_partition_physical_ensemble_design(
            network=network,
            initial_storage_fraction=(
                uncertainty_profile.initial_storage_fraction_by_feature
            ),
            manning_n_fraction=uncertainty_profile.manning_n_fraction_by_feature,
            forcing_fraction=(
                uncertainty_profile.modeled_forcing_fraction_by_feature
            ),
            graph_partition_mode_count=GRAPH_PARTITION_MODE_COUNT,
        )
    cycle = PhysicalEnsembleManningForecastCycle(
        transport_config=BranchingNetworkTransportConfig(
            timestep_seconds=TIMESTEP_SECONDS,
            integration_substep_seconds=SUBSTEP_SECONDS,
            operator_form_admitted=True,
            allow_unadmitted_components_for_diagnostics=True,
        ),
        state_estimator=LocalizedEnsembleStateEstimator(
            LocalizedEnsembleStateEstimatorConfig(
                localization_radius_m=LOCALIZATION_RADIUS_M,
                maximum_observation_age_seconds=0.0,
                require_authoritative_evidence=False,
                allow_unadmitted_components_for_diagnostics=True,
            )
        ),
    )
    observation_error = max(
        OBSERVATION_ERROR_ABSOLUTE_FLOOR_M3S,
        OBSERVATION_ERROR_RELATIVE_FRACTION * issue_observation_m3s,
    )
    result = cycle.execute(
        network=network,
        base_geometry=geometry,
        initial_stock=StockState(
            values=tuple(float(value) for value in initial_storage),
            unit="m3",
            provenance_id=(
                f"real-ensemble:{system_id}:nwm-modeled-initial:"
                f"{inputs['decoded_arrays']['initial_storage_m3']['sha256']}"
            ),
        ),
        member_specs=members,
        historical_action_m3s_by_step=historical_action,
        historical_forcing_m3s_by_step=q_lateral[0:1],
        forecast_action_m3s_by_step=forecast_action,
        forecast_forcing_m3s_by_step=q_lateral[1 : FORECAST_HOURS + 1],
        forcing_support=forcing_support,
        observations=(
            CausalDischargeObservation(
                feature_id=network.outlet_feature_id,
                discharge_m3s=issue_observation_m3s,
                valid_at=issue_time,
                available_at=issue_time,
                quality_status="approved",
                provenance_id=(
                    f"sealed-outcome-free-predictions:"
                    f"{prediction_descriptor['sha256']}:{system_id}:issue-0"
                ),
                evidence_level="derived",
            ),
        ),
        observation_error_std_m3s=(observation_error,),
        reference_time=reference_time,
        analysis_time=issue_time,
        provenance_id=f"real-ensemble-first-issue:{system_id}",
    )
    return _system_report(
        system_id=system_id,
        feature_count=len(feature_ids),
        historical_release_m3s=historical_release_m3s,
        historical_forcing_total_m3s=float(q_lateral[0].sum()),
        issue_observation_m3s=issue_observation_m3s,
        observation_error_m3s=observation_error,
        ensemble_design=ensemble_design,
        expected_member_count=len(members),
        uncertainty_profile=uncertainty_profile,
        uncertainty_profile_payload=uncertainty_profile_payload,
        result=result,
    )


def _system_report(
    *,
    system_id: str,
    feature_count: int,
    historical_release_m3s: float,
    historical_forcing_total_m3s: float,
    issue_observation_m3s: float,
    observation_error_m3s: float,
    ensemble_design: str,
    expected_member_count: int,
    uncertainty_profile: FeatureAlignedPhysicalUncertaintyProfile | None,
    uncertainty_profile_payload: Mapping[str, Any] | None,
    result: Any,
) -> dict[str, Any]:
    analysis = result.state_analysis
    forecast_observation_ensemble = np.asarray(
        analysis.forecast_observation_ensemble_m3s, dtype=float
    ).reshape(-1)
    analysis_observation_ensemble = np.asarray(
        analysis.analysis_observation_ensemble_m3s, dtype=float
    ).reshape(-1)
    forecast_mean = float(forecast_observation_ensemble.mean())
    analysis_mean = float(analysis_observation_ensemble.mean())
    forecast_std = float(forecast_observation_ensemble.std(ddof=1))
    analysis_std = float(analysis_observation_ensemble.std(ddof=1))
    innovation_before = issue_observation_m3s - forecast_mean
    innovation_after = issue_observation_m3s - analysis_mean
    if abs(innovation_before) > 0.0:
        reduction_fraction = 1.0 - abs(innovation_after) / abs(innovation_before)
    else:
        reduction_fraction = 0.0
    horizon_rows: dict[str, Any] = {}
    for horizon in HORIZONS_HOURS:
        index = horizon - 1
        p05 = result.outlet_flow_p05_m3s_by_horizon[index]
        p95 = result.outlet_flow_p95_m3s_by_horizon[index]
        horizon_rows[str(horizon)] = {
            "valid_time_utc": _iso(result.forecast_valid_times[index]),
            "mean_m3s": result.outlet_flow_mean_m3s_by_horizon[index],
            "p05_m3s": p05,
            "median_m3s": result.outlet_flow_median_m3s_by_horizon[index],
            "p95_m3s": p95,
            "p90_spread_m3s": p95 - p05,
        }
    checks = sum(result.physical_mass_balance_check_count_by_member)
    passes = sum(result.physical_mass_balance_pass_count_by_member)
    forecast_storage = np.asarray(
        analysis.forecast_storage_ensemble_m3, dtype=float
    )
    storage_anomalies = forecast_storage - forecast_storage.mean(axis=0)
    singular_values = np.linalg.svd(storage_anomalies, compute_uv=False)
    covariance_eigenvalues = singular_values**2 / float(
        forecast_storage.shape[0] - 1
    )
    covariance_total = float(covariance_eigenvalues.sum())
    effective_rank = (
        covariance_total**2 / float(np.square(covariance_eigenvalues).sum())
        if covariance_total > 0.0
        else 0.0
    )
    state_rank = int(np.linalg.matrix_rank(storage_anomalies))
    expected_mass_checks = expected_member_count * (1 + FORECAST_HOURS)
    gain = np.asarray(analysis.localized_kalman_gain_by_observation, dtype=float)
    taper = np.asarray(analysis.localization_taper_by_observation, dtype=float)
    gates = {
        "feature_axis_matches_real_network": feature_count == len(result.feature_ids),
        "expected_physical_members_executed": (
            len(result.member_ids) == expected_member_count
        ),
        "analysis_mass_accounting_passed": analysis.mass_accounting_passed,
        "all_physical_mass_balances_passed": result.all_physical_mass_balances_passed,
        "physical_mass_check_counts_match": (
            checks == passes == expected_mass_checks
        ),
        "issue_innovation_absolute_value_reduced": (
            abs(innovation_after) < abs(innovation_before)
        ),
        "forecast_ensemble_spread_nonzero": all(
            row["p90_spread_m3s"] > 0.0 for row in horizon_rows.values()
        ),
        "prior_gauge_ensemble_spread_nonzero": forecast_std > 0.0,
    }
    return {
        "system_id": system_id,
        "feature_count": feature_count,
        "ensemble_design": ensemble_design,
        "ensemble_member_count": len(result.member_ids),
        "outlet_feature_id": analysis.observation_feature_ids[0],
        "member_ids": list(result.member_ids),
        "uncertainty_sources_varied": dict(result.uncertainty_sources_varied),
        **(
            {
                "external_uncertainty_profile": {
                    "profile_id": uncertainty_profile.profile_id,
                    "amplitude_summary": uncertainty_profile_payload[
                        "amplitude_summary"
                    ],
                    "source_semantic_roles": {
                        "initial_storage": (
                            uncertainty_profile.initial_storage_source.semantic_role
                        ),
                        "manning_n": (
                            uncertainty_profile.manning_n_source.semantic_role
                        ),
                        "modeled_forcing": (
                            uncertainty_profile.modeled_forcing_source.semantic_role
                        ),
                    },
                    "evaluation_outcome_derived": False,
                    "admitted": uncertainty_profile.admitted,
                }
            }
            if uncertainty_profile is not None
            and uncertainty_profile_payload is not None
            else {}
        ),
        "historical_transition": {
            "step_count": 1,
            "reservoir_release_m3s": historical_release_m3s,
            "distributed_q_lateral_total_m3s": historical_forcing_total_m3s,
        },
        "state_analysis": {
            "issue_observed_outlet_m3s": issue_observation_m3s,
            "observation_error_std_m3s": observation_error_m3s,
            "forecast_ensemble_mean_at_gauge_m3s": forecast_mean,
            "forecast_ensemble_std_at_gauge_m3s": forecast_std,
            "analysis_ensemble_mean_at_gauge_m3s": analysis_mean,
            "analysis_ensemble_std_at_gauge_m3s": analysis_std,
            "innovation_before_analysis_m3s": innovation_before,
            "innovation_after_analysis_m3s": innovation_after,
            "absolute_innovation_to_prior_std_ratio": (
                abs(innovation_before) / forecast_std
            ),
            "absolute_innovation_reduction_fraction": reduction_fraction,
            "localized_nonzero_gain_feature_count": int(np.count_nonzero(gain)),
            "localization_supported_feature_count": int(np.count_nonzero(taper)),
            "mean_external_analysis_increment_m3": float(
                np.mean(analysis.external_analysis_increment_m3_by_member)
            ),
            "maximum_absolute_mass_accounting_residual_m3": (
                analysis.maximum_absolute_mass_accounting_residual_m3
            ),
            "mass_accounting_passed": analysis.mass_accounting_passed,
            "observation_covariance_condition_number": (
                analysis.observation_covariance_condition_number
            ),
        },
        "prior_state_ensemble": {
            "anomaly_matrix_rank": state_rank,
            "maximum_possible_rank": min(
                forecast_storage.shape[0] - 1,
                forecast_storage.shape[1],
            ),
            "covariance_effective_rank": effective_rank,
            "feature_count_with_nonzero_sample_variance": int(
                np.count_nonzero(forecast_storage.var(axis=0, ddof=1) > 0.0)
            ),
        },
        "forecast_by_horizon_hours": horizon_rows,
        "physical_mass_ledger": {
            "check_count": checks,
            "pass_count": passes,
            "maximum_absolute_residual_m3": max(
                result.maximum_absolute_physical_mass_residual_m3_by_member
            ),
            "all_passed": result.all_physical_mass_balances_passed,
        },
        "execution_gates": {**gates, "all_passed": all(gates.values())},
    }


def _validate_external_profile_report(
    *,
    report: Mapping[str, Any],
    protocol_body: bytes,
    static_body: bytes,
) -> None:
    isolation = report.get("data_isolation") or {}
    claims = report.get("claim_boundary") or {}
    artifacts = report.get("input_artifacts") or {}
    protocol_descriptor = artifacts.get("evaluation_protocol") or {}
    static_descriptor = artifacts.get("evaluation_static_input_report") or {}
    systems = report.get("systems") or {}
    if (
        report.get("schema") != EXTERNAL_PROFILE_REPORT_SCHEMA
        or report.get("status")
        != "outcome_independent_feature_profiles_compiled"
        or isolation.get("evaluation_outcome_loaded") is not False
        or isolation.get("evaluation_score_loaded") is not False
        or isolation.get("issue_observation_loaded") is not False
        or claims.get("amplitudes_outcome_independent") is not True
        or claims.get("amplitudes_calibrated_as_forecast_error") is not False
        or claims.get("candidate_admitted") is not False
        or protocol_descriptor.get("sha256")
        != hashlib.sha256(protocol_body).hexdigest()
        or static_descriptor.get("sha256")
        != hashlib.sha256(static_body).hexdigest()
        or set(systems) != set(SYSTEM_IDS)
        or any(
            (systems[system_id].get("execution_gates") or {}).get("all_passed")
            is not True
            for system_id in SYSTEM_IDS
        )
    ):
        raise ValueError("real_ensemble_external_profile_report_invalid")


def _uncertainty_profile(
    payload: Mapping[str, Any],
    *,
    expected_system_id: str,
    expected_feature_ids: tuple[int, ...],
    expected_evaluation_start: datetime,
) -> FeatureAlignedPhysicalUncertaintyProfile:
    profile = payload.get("profile") or {}
    fractions = profile.get("fractions_by_feature") or {}
    sources = profile.get("sources") or {}
    if (
        payload.get("system_id") != expected_system_id
        or int(payload.get("feature_count", -1)) != len(expected_feature_ids)
        or profile.get("schema") != PHYSICAL_UNCERTAINTY_PROFILE_SCHEMA
        or tuple(profile.get("feature_ids") or ()) != expected_feature_ids
        or (profile.get("claim_boundary") or {}).get("evaluation_outcome_used")
        is not False
    ):
        raise ValueError("real_ensemble_external_profile_identity_invalid")

    def source(name: str) -> PhysicalUncertaintySource:
        value = sources.get(name) or {}
        evidence_time = value.get("evidence_window_end_utc")
        return PhysicalUncertaintySource(
            source_name=str(value.get("source_name", "")),
            semantic_role=str(value.get("semantic_role", "")),
            provenance_ids=tuple(str(item) for item in value.get("provenance_ids") or ()),
            evidence_window_end_utc=(
                _parse_time(evidence_time) if evidence_time is not None else None
            ),
            evaluation_outcome_derived=value.get("evaluation_outcome_derived"),
            admitted_as_calibrated_uncertainty=value.get(
                "admitted_as_calibrated_uncertainty"
            ),
        )

    result = FeatureAlignedPhysicalUncertaintyProfile(
        profile_id=str(profile.get("profile_id", "")),
        feature_ids=tuple(int(value) for value in profile.get("feature_ids") or ()),
        initial_storage_fraction_by_feature=tuple(
            float(value) for value in fractions.get("initial_storage") or ()
        ),
        manning_n_fraction_by_feature=tuple(
            float(value) for value in fractions.get("manning_n") or ()
        ),
        modeled_forcing_fraction_by_feature=tuple(
            float(value) for value in fractions.get("modeled_forcing") or ()
        ),
        initial_storage_source=source("initial_storage"),
        manning_n_source=source("manning_n"),
        modeled_forcing_source=source("modeled_forcing"),
        evaluation_window_start_utc=_parse_time(
            profile.get("evaluation_window_start_utc")
        ),
        diagnostic_only=profile.get("diagnostic_only"),
        admitted=profile.get("admitted"),
    )
    if (
        result.feature_ids != expected_feature_ids
        or result.evaluation_window_start_utc != expected_evaluation_start
    ):
        raise ValueError("real_ensemble_external_profile_axis_or_time_invalid")
    return result


def _validate_reports(
    *,
    protocol: Mapping[str, Any],
    protocol_body: bytes,
    static_report: Mapping[str, Any],
    static_body: bytes,
    rollout_report: Mapping[str, Any],
) -> None:
    protocol_claims = protocol.get("claim_boundary") or {}
    static_isolation = static_report.get("data_isolation") or {}
    rollout_isolation = rollout_report.get("data_isolation") or {}
    rollout_claims = rollout_report.get("claim_boundary") or {}
    frozen = rollout_report.get("frozen_artifacts") or {}
    if (
        protocol.get("schema") != PROTOCOL_SCHEMA
        or protocol.get("status") != "frozen_before_holdout_input_value_access"
        or protocol_claims.get("holdout_outcomes_acquired") is not False
        or static_report.get("schema") != STATIC_SCHEMA
        or static_report.get("status")
        != "static_inputs_acquired_issue_observations_deferred"
        or static_isolation.get("future_target_loaded") is not False
        or static_isolation.get("score_or_loss_loaded") is not False
        or rollout_report.get("schema") != ROLLOUT_SCHEMA
        or rollout_report.get("status")
        != "all_chronological_issue_predictions_jointly_sealed"
        or rollout_isolation.get("full_outcome_series_requested") is not False
        or rollout_isolation.get("scores_computed") is not False
        or rollout_isolation.get("target_or_score_input_accepted") is not False
        or rollout_claims.get("holdout_outcomes_acquired_for_scoring") is not False
        or rollout_claims.get("holdout_scored") is not False
        or frozen.get("protocol", {}).get("sha256")
        != hashlib.sha256(protocol_body).hexdigest()
        or frozen.get("static_input_report", {}).get("sha256")
        != hashlib.sha256(static_body).hexdigest()
    ):
        raise ValueError("real_ensemble_first_issue_input_reports_invalid")


def _issue_observations(body: bytes, *, issue_time: datetime) -> dict[str, float]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    if tuple(reader.fieldnames or ()) != PREDICTION_COLUMNS:
        raise ValueError("real_ensemble_prediction_columns_invalid")
    values: dict[str, list[float]] = {system_id: [] for system_id in SYSTEM_IDS}
    row_keys: dict[str, set[tuple[str, int]]] = {
        system_id: set() for system_id in SYSTEM_IDS
    }
    for row in reader:
        if row["issue_index"] != "0":
            continue
        system_id = row["system_id"]
        if system_id not in values or _parse_time(row["issue_time_utc"]) != issue_time:
            raise ValueError("real_ensemble_first_issue_prediction_identity_invalid")
        mode = row["mode"]
        horizon = int(row["horizon_hours"])
        if (
            mode not in MODES
            or horizon not in HORIZONS_HOURS
            or _parse_time(row["target_time_utc"])
            != issue_time + timedelta(hours=horizon)
            or row["observation_fallback_reason"]
            or not np.isfinite(float(row["predicted_outlet_m3s"]))
        ):
            raise ValueError("real_ensemble_first_issue_prediction_row_invalid")
        value = float(row["issue_observed_outlet_m3s"])
        if not np.isfinite(value) or value < 0.0:
            raise ValueError("real_ensemble_first_issue_observation_invalid")
        values[system_id].append(value)
        row_keys[system_id].add((mode, horizon))
    expected_keys = {(mode, horizon) for mode in MODES for horizon in HORIZONS_HOURS}
    result: dict[str, float] = {}
    for system_id in SYSTEM_IDS:
        unique_values = set(values[system_id])
        if row_keys[system_id] != expected_keys or len(values[system_id]) != 16:
            raise ValueError("real_ensemble_first_issue_prediction_set_incomplete")
        if len(unique_values) != 1:
            raise ValueError("real_ensemble_first_issue_observation_inconsistent")
        result[system_id] = unique_values.pop()
    return result


def _parse_actions(body: bytes) -> dict[datetime, float]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    expected = (
        "support_start_utc",
        "support_end_utc",
        "action_release_m3s",
        "source_role",
    )
    if tuple(reader.fieldnames or ()) != expected:
        raise ValueError("real_ensemble_action_columns_invalid")
    actions: dict[datetime, float] = {}
    for row in reader:
        start = _parse_time(row["support_start_utc"])
        end = _parse_time(row["support_end_utc"])
        value = float(row["action_release_m3s"])
        if (
            end - start != timedelta(hours=1)
            or row["source_role"] != "boundary_action"
            or not np.isfinite(value)
            or value < 0.0
            or start in actions
        ):
            raise ValueError("real_ensemble_action_value_invalid")
        actions[start] = value
    if len(actions) != 672:
        raise ValueError("real_ensemble_action_axis_invalid")
    return actions


def _historical_release_at_support_end(body: bytes, *, support_end: datetime) -> float:
    payload = json.loads(body)
    expected_columns = [
        {"name": "date-time", "ordinal": 1, "datatype": "java.sql.Timestamp"},
        {"name": "value", "ordinal": 2, "datatype": "java.lang.Double"},
        {"name": "quality-code", "ordinal": 3, "datatype": "int"},
    ]
    if (
        payload.get("units") != "cms"
        or payload.get("interval") != "PT1H"
        or payload.get("interval-offset") != 0
        or payload.get("value-columns") != expected_columns
    ):
        raise ValueError("real_ensemble_historical_action_schema_invalid")
    matches: list[float] = []
    for row in payload.get("values") or ():
        if not isinstance(row, list) or len(row) != 3:
            raise ValueError("real_ensemble_historical_action_row_invalid")
        timestamp = datetime.fromtimestamp(float(row[0]) / 1000.0, tz=UTC)
        value = float(row[1])
        quality_code = int(row[2])
        if timestamp == support_end:
            if not np.isfinite(value) or value < 0.0 or quality_code != 0:
                raise ValueError("real_ensemble_historical_action_value_invalid")
            matches.append(value)
    if len(matches) != 1:
        raise ValueError("real_ensemble_historical_action_support_end_missing")
    return matches[0]


def _forcing_support(
    *,
    system_id: str,
    lock: Mapping[str, Any],
    feature_ids: tuple[int, ...],
    outlet_feature_id: int,
) -> ReachForcingSupport:
    terminal_fraction = float(
        lock["forcing_support"]["partial_terminal_reach_fraction"]
    )
    return ReachForcingSupport(
        feature_ids=feature_ids,
        coverage_fractions=tuple(
            terminal_fraction if value == outlet_feature_id else 1.0
            for value in feature_ids
        ),
        support_method=str(
            lock["forcing_support"]["partial_terminal_reach_method"]
        ),
        provenance_id=f"real-ensemble-first-issue:{system_id}:forcing-support",
        evidence_level="derived",
        admitted_as_spatial_support=True,
    )


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("real_ensemble_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("real_ensemble_artifact_identity_mismatch")
    return body


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


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("real_ensemble_timestamp_invalid")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("real_ensemble_timestamp_invalid")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    report = compile_real_ensemble_first_issue_report(
        protocol_path=args.protocol,
        static_report_path=args.static_report,
        sealed_rollout_report_path=args.sealed_rollout_report,
        external_profile_report_path=args.external_profile_report,
        ensemble_design=args.ensemble_design,
    )
    if args.output is not None:
        output = args.output
    elif args.ensemble_design == GRAPH_PARTITION_ENSEMBLE_DESIGN:
        output = DEFAULT_GRAPH_PARTITION_OUTPUT
    elif args.ensemble_design == EXTERNAL_PROFILE_GRAPH_PARTITION_ENSEMBLE_DESIGN:
        output = DEFAULT_EXTERNAL_PROFILE_OUTPUT
    else:
        output = DEFAULT_OUTPUT
    _write_json(output, report)
    print(output)
    for system_id in SYSTEM_IDS:
        system = report["systems"][system_id]
        print(
            f"{system_id}: features={system['feature_count']} "
            f"innovation_before={system['state_analysis']['innovation_before_analysis_m3s']:.6f} "
            f"innovation_after={system['state_analysis']['innovation_after_analysis_m3s']:.6f} "
            f"mass={system['physical_mass_ledger']['pass_count']}/"
            f"{system['physical_mass_ledger']['check_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
