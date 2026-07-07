"""Evidence gate over prepared UWM data-foundation artifacts."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .causal_policy_evidence import validate_uwm_causal_policy_evidence_gate
from .data_calibrated_mechanism_table import (
    validate_uwm_data_calibrated_mechanism_table,
)
from .external_observed_holdout import validate_uwm_external_observed_holdout_suite
from .scene_aligned_gridded_air_quality_holdout import (
    validate_uwm_scene_aligned_gridded_air_quality_holdout,
)
from .station_aligned_air_quality_holdout import (
    validate_uwm_station_aligned_air_quality_holdout,
)


UWM_DATA_FOUNDATION_EVIDENCE_GATE_SCHEMA = "uwm.data_foundation_evidence_gate.v1"

ACCEPTED_SYNTHETIC_STATUSES = [
    "real",
    "public_proxy",
    "fitted_proxy",
    "semi_synthetic",
    "synthetic",
    "restricted_expected",
]


def build_uwm_data_foundation_evidence_gate(
    *,
    manifest_path: str | Path,
    openaq_temporal_benchmark_path: str | Path,
    tap_external_dynamics_path: str | Path,
    learned_rollout_path: str | Path,
    livability_intervention_package_path: str | Path,
    local_planning_inventory_path: str | Path,
    admin_spatial_graph_path: str | Path,
    causal_policy_evidence_path: str | Path | None = None,
    external_observed_holdout_suite_path: str | Path | None = None,
    station_aligned_air_quality_holdout_path: str | Path | None = None,
    data_calibrated_mechanism_table_path: str | Path | None = None,
    data_calibrated_planner_replay_path: str | Path | None = None,
    scene_aligned_gridded_air_quality_holdout_path: str | Path | None = None,
    multisource_livability_scene_path: str | Path | None = None,
    osm_admin_mobility_crosswalk_path: str | Path | None = None,
    building_floor_morphology_path: str | Path | None = None,
    livability_endpoint_suite_path: str | Path | None = None,
    endpoint_aligned_planner_evaluator_path: str | Path | None = None,
    spatial_spillover_planner_evaluator_path: str | Path | None = None,
    livability_decision_package_path: str | Path | None = None,
    livability_rl_training_report_path: str | Path | None = None,
    livability_graph_drl_training_report_path: str | Path | None = None,
    gate_id: str,
    created_at: str,
) -> dict[str, Any]:
    """Summarize claim-safe evidence from actual prepared UWM artifacts."""

    manifest_rows = _read_manifest_rows(manifest_path)
    openaq_benchmark = _read_json(openaq_temporal_benchmark_path)
    tap_external_dynamics = _read_json(tap_external_dynamics_path)
    learned_rollout = _read_json(learned_rollout_path)
    intervention_package = _read_json(livability_intervention_package_path)
    local_inventory_rows = _read_csv_rows(local_planning_inventory_path)
    admin_graph = _read_json(admin_spatial_graph_path)
    causal_policy_evidence = (
        _read_json(causal_policy_evidence_path)
        if causal_policy_evidence_path is not None
        else {}
    )
    external_observed_holdout_suite = (
        _read_json(external_observed_holdout_suite_path)
        if external_observed_holdout_suite_path is not None
        else {}
    )
    station_aligned_air_quality_holdout = (
        _read_json(station_aligned_air_quality_holdout_path)
        if station_aligned_air_quality_holdout_path is not None
        else {}
    )
    data_calibrated_mechanism_table = (
        _read_json(data_calibrated_mechanism_table_path)
        if data_calibrated_mechanism_table_path is not None
        else {}
    )
    data_calibrated_planner_replay = (
        _read_json(data_calibrated_planner_replay_path)
        if data_calibrated_planner_replay_path is not None
        else {}
    )
    scene_aligned_gridded_air_quality_holdout = (
        _read_json(scene_aligned_gridded_air_quality_holdout_path)
        if scene_aligned_gridded_air_quality_holdout_path is not None
        else {}
    )
    multisource_livability_scene = (
        _read_json(multisource_livability_scene_path)
        if multisource_livability_scene_path is not None
        else {}
    )
    osm_admin_mobility_crosswalk = (
        _read_json(osm_admin_mobility_crosswalk_path)
        if osm_admin_mobility_crosswalk_path is not None
        else {}
    )
    building_floor_morphology = (
        _read_json(building_floor_morphology_path)
        if building_floor_morphology_path is not None
        else {}
    )
    livability_endpoint_suite = (
        _read_json(livability_endpoint_suite_path)
        if livability_endpoint_suite_path is not None
        else {}
    )
    endpoint_aligned_planner_evaluator = (
        _read_json(endpoint_aligned_planner_evaluator_path)
        if endpoint_aligned_planner_evaluator_path is not None
        else {}
    )
    spatial_spillover_planner_evaluator = (
        _read_json(spatial_spillover_planner_evaluator_path)
        if spatial_spillover_planner_evaluator_path is not None
        else {}
    )
    livability_decision_package = (
        _read_json(livability_decision_package_path)
        if livability_decision_package_path is not None
        else {}
    )
    livability_rl_training_report = (
        _read_json(livability_rl_training_report_path)
        if livability_rl_training_report_path is not None
        else {}
    )
    livability_graph_drl_training_report = (
        _read_json(livability_graph_drl_training_report_path)
        if livability_graph_drl_training_report_path is not None
        else {}
    )

    openaq_slice = _openaq_temporal_state_slice(
        openaq_benchmark,
        source_artifact_exists=Path(openaq_temporal_benchmark_path).exists(),
    )
    tap_transition_slice = _tap_external_temporal_transition_slice(
        tap_external_dynamics,
        source_artifact_exists=Path(tap_external_dynamics_path).exists(),
    )
    rollout_slice = _learned_rollout_slice(
        learned_rollout,
        source_artifact_exists=Path(learned_rollout_path).exists(),
    )
    intervention_slice = _livability_intervention_slice(
        intervention_package,
        source_artifact_exists=Path(livability_intervention_package_path).exists(),
        tap_external_temporal_transition_ready=_external_temporal_transition_superiority(
            tap_transition_slice
        ),
    )
    causal_policy_slice = _causal_policy_effect_validation_slice(
        causal_policy_evidence,
        source_artifact_exists=(
            Path(causal_policy_evidence_path).exists()
            if causal_policy_evidence_path is not None
            else False
        ),
    )
    external_observed_slice = _external_observed_holdout_suite_slice(
        external_observed_holdout_suite,
        source_artifact_exists=(
            Path(external_observed_holdout_suite_path).exists()
            if external_observed_holdout_suite_path is not None
            else False
        ),
    )
    station_aligned_slice = _station_aligned_air_quality_holdout_slice(
        station_aligned_air_quality_holdout,
        source_artifact_exists=(
            Path(station_aligned_air_quality_holdout_path).exists()
            if station_aligned_air_quality_holdout_path is not None
            else False
        ),
    )
    data_calibrated_mechanism_slice = _data_calibrated_mechanism_table_slice(
        data_calibrated_mechanism_table,
        source_artifact_exists=(
            Path(data_calibrated_mechanism_table_path).exists()
            if data_calibrated_mechanism_table_path is not None
            else False
        ),
    )
    data_calibrated_planner_replay_slice = _data_calibrated_planner_replay_slice(
        data_calibrated_planner_replay,
        source_artifact_exists=(
            Path(data_calibrated_planner_replay_path).exists()
            if data_calibrated_planner_replay_path is not None
            else False
        ),
    )
    scene_aligned_gridded_slice = _scene_aligned_gridded_air_quality_holdout_slice(
        scene_aligned_gridded_air_quality_holdout,
        source_artifact_exists=(
            Path(scene_aligned_gridded_air_quality_holdout_path).exists()
            if scene_aligned_gridded_air_quality_holdout_path is not None
            else False
        ),
    )
    multisource_livability_scene_slice = _multisource_livability_scene_slice(
        multisource_livability_scene,
        source_artifact_exists=(
            Path(multisource_livability_scene_path).exists()
            if multisource_livability_scene_path is not None
            else False
        ),
    )
    osm_admin_mobility_crosswalk_slice = _osm_admin_mobility_crosswalk_slice(
        osm_admin_mobility_crosswalk,
        source_artifact_exists=(
            Path(osm_admin_mobility_crosswalk_path).exists()
            if osm_admin_mobility_crosswalk_path is not None
            else False
        ),
    )
    building_floor_morphology_slice = _building_floor_morphology_slice(
        building_floor_morphology,
        source_artifact_exists=(
            Path(building_floor_morphology_path).exists()
            if building_floor_morphology_path is not None
            else False
        ),
    )
    livability_endpoint_suite_slice = _livability_endpoint_suite_slice(
        livability_endpoint_suite,
        source_artifact_exists=(
            Path(livability_endpoint_suite_path).exists()
            if livability_endpoint_suite_path is not None
            else False
        ),
    )
    endpoint_aligned_planner_evaluator_slice = (
        _endpoint_aligned_planner_evaluator_slice(
            endpoint_aligned_planner_evaluator,
            source_artifact_exists=(
                Path(endpoint_aligned_planner_evaluator_path).exists()
                if endpoint_aligned_planner_evaluator_path is not None
                else False
            ),
        )
    )
    spatial_spillover_planner_evaluator_slice = (
        _spatial_spillover_planner_evaluator_slice(
            spatial_spillover_planner_evaluator,
            source_artifact_exists=(
                Path(spatial_spillover_planner_evaluator_path).exists()
                if spatial_spillover_planner_evaluator_path is not None
                else False
            ),
        )
    )
    livability_decision_package_slice = _livability_decision_package_slice(
        livability_decision_package,
        source_artifact_exists=(
            Path(livability_decision_package_path).exists()
            if livability_decision_package_path is not None
            else False
        ),
    )
    livability_rl_training_slice = _livability_rl_training_slice(
        livability_rl_training_report,
        source_artifact_exists=(
            Path(livability_rl_training_report_path).exists()
            if livability_rl_training_report_path is not None
            else False
        ),
    )
    livability_graph_drl_training_slice = _livability_graph_drl_training_slice(
        livability_graph_drl_training_report,
        source_artifact_exists=(
            Path(livability_graph_drl_training_report_path).exists()
            if livability_graph_drl_training_report_path is not None
            else False
        ),
    )
    claim_guard = _claim_guard(manifest_rows)
    bounded_final_system_superiority_claim = _bounded_final_system_superiority_claim(
        openaq_slice,
        tap_transition_slice,
        scene_aligned_gridded_slice,
        multisource_livability_scene_slice,
        livability_endpoint_suite_slice,
        endpoint_aligned_planner_evaluator_slice,
    )
    return {
        "schema": UWM_DATA_FOUNDATION_EVIDENCE_GATE_SCHEMA,
        "gate_id": gate_id,
        "created_at": created_at,
        "data_foundation_scope": _data_foundation_scope(manifest_rows),
        "evidence_slices": {
            "openaq_observed_temporal_state": openaq_slice,
            "tap_external_temporal_transition": tap_transition_slice,
            "learned_world_model_rollout": rollout_slice,
            "livability_intervention_package": intervention_slice,
            "local_planning_data_foundation": _local_planning_data_foundation_slice(
                local_inventory_rows,
                source_artifact_exists=Path(local_planning_inventory_path).exists(),
            ),
            "admin_spatial_adjacency_graph": _admin_spatial_graph_slice(
                admin_graph,
                source_artifact_exists=Path(admin_spatial_graph_path).exists(),
            ),
            "causal_policy_effect_validation": causal_policy_slice,
            "external_observed_holdout_suite": external_observed_slice,
            "station_aligned_air_quality_holdout": station_aligned_slice,
            "data_calibrated_mechanism_table": data_calibrated_mechanism_slice,
            "data_calibrated_planner_replay": data_calibrated_planner_replay_slice,
            "scene_aligned_gridded_air_quality_holdout": scene_aligned_gridded_slice,
            "multisource_livability_scene": multisource_livability_scene_slice,
            "osm_admin_mobility_crosswalk": osm_admin_mobility_crosswalk_slice,
            "building_floor_morphology": building_floor_morphology_slice,
            "livability_endpoint_suite": livability_endpoint_suite_slice,
            "endpoint_aligned_planner_evaluator": (
                endpoint_aligned_planner_evaluator_slice
            ),
            "spatial_spillover_planner_evaluator": (
                spatial_spillover_planner_evaluator_slice
            ),
            "livability_decision_package": livability_decision_package_slice,
            "livability_rl_training": livability_rl_training_slice,
            "livability_graph_drl_training": livability_graph_drl_training_slice,
        },
        "observed_state_prediction_superiority_claim": _observed_state_prediction_superiority(
            openaq_slice
        ),
        "external_temporal_transition_superiority_claim": _external_temporal_transition_superiority(
            tap_transition_slice
        ),
        "external_observed_state_prediction_superiority_claim": _external_observed_holdout_ready(
            external_observed_slice
        ),
        "observed_policy_outcome_superiority_claim": False,
        "bounded_final_system_superiority_claim": (
            bounded_final_system_superiority_claim
        ),
        "empirical_superiority_claim": False,
        "supported_claims": _supported_claims(
            openaq_slice,
            tap_transition_slice,
            rollout_slice,
            intervention_slice,
            causal_policy_slice,
            external_observed_slice,
            station_aligned_slice,
            data_calibrated_mechanism_slice,
            data_calibrated_planner_replay_slice,
            scene_aligned_gridded_slice,
            multisource_livability_scene_slice,
            osm_admin_mobility_crosswalk_slice,
            building_floor_morphology_slice,
            livability_endpoint_suite_slice,
            endpoint_aligned_planner_evaluator_slice,
            spatial_spillover_planner_evaluator_slice,
            livability_decision_package_slice,
            livability_rl_training_slice,
            livability_graph_drl_training_slice,
        ),
        "claim_guard": claim_guard,
        "remaining_gates": _remaining_gates(
            claim_guard,
            tap_external_temporal_transition_ready=_external_temporal_transition_superiority(
                tap_transition_slice
            ),
            causal_policy_diagnostic_ready=_causal_policy_diagnostic_ready(
                causal_policy_slice
            ),
            external_observed_holdout_ready=_external_observed_holdout_ready(
                external_observed_slice
            ),
            scene_aligned_station_calibrated_air_quality_holdout_ready=_scene_aligned_station_calibrated_ready(
                station_aligned_slice
            ),
        ),
    }


def _data_foundation_scope(rows: list[dict[str, str]]) -> dict[str, Any]:
    status_counts = Counter(row.get("synthetic_status", "") for row in rows)
    source_counts = Counter(row.get("source_type", "") for row in rows)
    access_counts = Counter(row.get("access_status", "") for row in rows)
    return {
        "manifest_row_count": len(rows),
        "accepted_synthetic_statuses": ACCEPTED_SYNTHETIC_STATUSES,
        "synthetic_status_counts": {
            status: status_counts.get(status, 0)
            for status in ACCEPTED_SYNTHETIC_STATUSES
        },
        "source_type_counts": dict(sorted(source_counts.items())),
        "access_status_counts": dict(sorted(access_counts.items())),
        "scope_note": (
            "all prepared UWM data-foundation assets may be used, but claims are gated by "
            "synthetic_status, source_type, access_status and artifact-level evidence"
        ),
    }


def _openaq_temporal_state_slice(
    benchmark: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    pm25 = _pollutant_result(benchmark, "pm25")
    best_pm25 = pm25.get("best_traditional_static_baseline") or {}
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": benchmark.get("schema"),
        "scope": "observed_temporal_state_prediction_not_policy_outcome",
        "source_dataset_ids": benchmark.get("source_dataset_ids") or [],
        "pollutant_count": _int(benchmark.get("pollutant_count")),
        "observation_count": _int(benchmark.get("observation_count")),
        "holdout_count": _int(benchmark.get("holdout_count")),
        "overall_holdout_win_count": _int(benchmark.get("overall_holdout_win_count")),
        "overall_holdout_win_rate": _float(benchmark.get("overall_holdout_win_rate")),
        "overall_sign_tests": benchmark.get("overall_sign_tests") or {},
        "temporal_order_negative_control_passed": bool(
            (
                benchmark.get("temporal_order_negative_control_summary")
                or {}
            ).get("all_pollutants_ordered_temporal_state_advantage")
        ),
        "pm25_dynamic_mae": _float(pm25.get("uwm_dynamic_persistence_mae")),
        "pm25_best_static_mae": _float(best_pm25.get("mae")),
        "supported_claim": benchmark.get("supported_claim"),
        "claim_level": (benchmark.get("claim_boundary") or {}).get("max_claim_level"),
        "limitations": benchmark.get("limitations") or [],
        "empirical_superiority_claim": bool(benchmark.get("empirical_superiority_claim")),
    }


def _tap_external_temporal_transition_slice(
    report: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    training = report.get("training_summary") or {}
    overall = report.get("overall_results") or {}
    negative_controls = report.get("negative_control_results") or {}
    temporal_control = negative_controls.get("temporal_order_rotation_control") or {}
    leakage_guard = negative_controls.get("future_label_leakage_guard") or {}
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": report.get("schema"),
        "scope": "tap_external_temporal_transition_without_spatial_claim",
        "source_dataset_ids": report.get("source_dataset_ids") or [],
        "series_count": _int(training.get("series_count")),
        "holdout_count": _int(training.get("holdout_count")),
        "best_spatial_method": overall.get("best_spatial_method"),
        "best_transition_mae": _float(overall.get("best_spatial_mae")),
        "best_traditional_static_mae": _float(overall.get("best_traditional_static_mae")),
        "best_non_spatial_dynamic_mae": _float(
            overall.get("best_non_spatial_dynamic_mae")
        ),
        "mae_reduction_vs_best_static": _float(
            overall.get("spatial_mae_reduction_vs_best_static")
        ),
        "mae_reduction_vs_best_non_spatial_dynamic": _float(
            overall.get("spatial_mae_reduction_vs_best_non_spatial_dynamic")
        ),
        "paired_win_rate_vs_best_non_spatial_dynamic": _float(
            overall.get("paired_win_rate_vs_best_non_spatial_dynamic")
        ),
        "spatial_negative_control_passed": bool(
            overall.get("spatial_negative_control_passed")
        ),
        "temporal_order_negative_control_passed": _float(
            temporal_control.get("ordered_advantage")
        )
        > 0.0,
        "future_label_leakage_guard_passed": bool(leakage_guard.get("passed")),
        "supported_claim": report.get("supported_claim"),
        "claim_level": (report.get("claim_boundary") or {}).get("max_claim_level"),
        "spatial_attribution_claim": False,
        "policy_outcome_claim": False,
        "empirical_superiority_claim": bool(report.get("empirical_superiority_claim")),
        "limitations": report.get("limitations") or [],
    }


def _learned_rollout_slice(
    report: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    planner = report.get("learned_rollout_planner") or {}
    training = report.get("training_summary") or {}
    holdout = report.get("holdout_metrics") or {}
    baseline = report.get("baseline_metrics") or {}
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": report.get("schema"),
        "scope": "simulator_replay_learned_dynamics_not_observed_policy_outcome",
        "transition_count": _int(training.get("transition_count")),
        "holdout_count": _int(training.get("holdout_count")),
        "holdout_reward_mae": _float(holdout.get("reward_mae")),
        "train_mean_reward_mae": _float(baseline.get("train_mean_reward_mae")),
        "reward_win_count_vs_train_mean": _int(holdout.get("reward_win_count_vs_train_mean")),
        "imagined_advantage_over_static": _float(
            planner.get("imagined_advantage_over_static_single_step")
        ),
        "imagined_advantage_over_one_step": _float(
            planner.get("imagined_advantage_over_one_step_policy")
        ),
        "selected_sequence": (planner.get("selected_sequence") or {}).get("action_sequence") or [],
        "supported_claim": report.get("supported_claim"),
        "claim_level": (report.get("claim_boundary") or {}).get("max_claim_level"),
        "empirical_superiority_claim": bool(report.get("empirical_superiority_claim")),
    }


def _livability_intervention_slice(
    package: dict[str, Any],
    *,
    source_artifact_exists: bool,
    tap_external_temporal_transition_ready: bool = False,
) -> dict[str, Any]:
    reported_gates = package.get("remaining_gates") or []
    remaining_gates = list(reported_gates)
    if tap_external_temporal_transition_ready:
        remaining_gates = [
            gate
            for gate in remaining_gates
            if gate != "tap_or_authoritative_air_quality_required"
        ]
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": package.get("schema"),
        "scope": "business_theory_aligned_proxy_package_not_observed_policy_outcome",
        "synthetic_status": package.get("synthetic_status"),
        "supported_claim": package.get("supported_claim"),
        "claim_level": (package.get("claim_boundary") or {}).get("max_claim_level"),
        "action_count": (package.get("multi_step_plan") or {}).get("action_count"),
        "predicted_delta": (package.get("before_after_indicators") or {}).get(
            "predicted_delta"
        )
        or {},
        "equity_status": (package.get("equity_conclusion") or {}).get("status"),
        "reported_remaining_gates": reported_gates,
        "remaining_gates": remaining_gates,
        "empirical_superiority_claim": bool(package.get("empirical_superiority_claim")),
    }


def _local_planning_data_foundation_slice(
    rows: list[dict[str, str]],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    wanted_ids = {
        "gaode_poi_2024",
        "chongqing_central_buildings_2021",
        "chongqing_osm_roads_2021",
        "chongqing_unicom_commuting_2023_local",
    }
    asset_counts = {}
    for row in rows:
        asset_id = str(row.get("asset_id") or "")
        if asset_id not in wanted_ids:
            continue
        asset_counts[asset_id] = {
            "asset_kind": row.get("asset_kind"),
            "status": row.get("status"),
            "feature_count": _int(row.get("feature_count")),
            "row_count": _int(row.get("row_count")),
            "geometry_type": row.get("geometry_type"),
            "crs": row.get("crs"),
            "uwm_roles": row.get("uwm_roles"),
        }
    return {
        "source_artifact_exists": source_artifact_exists,
        "scope": "prepared_local_planning_data_foundation",
        "asset_counts": asset_counts,
        "claim_level": "fragile",
        "empirical_superiority_claim": False,
        "limitations": [
            "restricted_local_sample_terms_pending",
            "not_policy_intervention_outcome",
        ],
    }


def _admin_spatial_graph_slice(
    graph: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    summary = graph.get("summary") or {}
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": graph.get("schema"),
        "scope": "prepared_admin_boundary_adjacency_graph_not_mobility_graph",
        "node_count": _int(summary.get("node_count")),
        "edge_count": _int(summary.get("edge_count")),
        "isolated_node_count": _int(summary.get("isolated_node_count")),
        "edge_rule": summary.get("edge_rule"),
        "claim_level": (graph.get("claim_boundary") or {}).get("max_claim_level"),
        "empirical_superiority_claim": False,
    }


def _causal_policy_effect_validation_slice(
    causal_gate: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    if source_artifact_exists:
        validation = validate_uwm_causal_policy_evidence_gate(causal_gate)
    else:
        validation = {"valid": False, "errors": ["source_artifact_missing"]}
    evidence_slices = causal_gate.get("evidence_slices") or {}
    arcgis = evidence_slices.get("arcgis_sci_plus_county") or {}
    scca = evidence_slices.get("scca_county_social_capital") or {}
    chongqing = evidence_slices.get("chongqing_uhi_analysis") or {}
    diagnostic_ready = (
        source_artifact_exists
        and validation.get("valid") is True
        and causal_gate.get("algorithmic_causal_diagnostic_ready") is True
    )
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": causal_gate.get("schema"),
        "scope": "paper6_causal_policy_effect_validation_diagnostic_not_policy_outcome",
        "algorithmic_causal_diagnostic_ready": diagnostic_ready,
        "observed_local_policy_outcome_ready": bool(
            causal_gate.get("observed_local_policy_outcome_ready")
        ),
        "observed_policy_outcome_superiority_claim": bool(
            causal_gate.get("observed_policy_outcome_superiority_claim")
        ),
        "arcgis_native_parity_ready": bool(arcgis.get("arcgis_native_parity_ready")),
        "arcgis_erf_response_mae": _float(arcgis.get("arcgis_erf_response_mae")),
        "arcgis_trimmed_rows": _int(arcgis.get("trimmed_rows")),
        "arcgis_erf_grid_count": _int(arcgis.get("erf_grid_count")),
        "scca_credibility_ready": bool(scca.get("credibility_ready")),
        "scca_decision": scca.get("decision"),
        "chongqing_causal_case_anchor_ready": bool(
            chongqing.get("causal_case_anchor_ready")
        ),
        "chongqing_sample_size": _int(chongqing.get("sample_size")),
        "chongqing_balance_interpretation": chongqing.get("balance_interpretation"),
        "supported_claims": causal_gate.get("supported_claims") or [],
        "claim_level": (
            (causal_gate.get("claim_boundary") or {}).get("max_claim_level")
            if diagnostic_ready
            else "not_for_claim"
        ),
        "policy_outcome_claim": False,
        "empirical_superiority_claim": False,
        "validation": validation,
        "limitations": causal_gate.get("limitations") or [],
    }


def _external_observed_holdout_suite_slice(
    suite: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    if source_artifact_exists:
        validation = validate_uwm_external_observed_holdout_suite(suite)
    else:
        validation = {"valid": False, "errors": ["source_artifact_missing"]}
    sources = suite.get("holdout_sources") or {}
    openaq = sources.get("openaq_station_temporal_holdout") or {}
    tap = sources.get("tap_gridded_temporal_holdout") or {}
    ready = (
        source_artifact_exists
        and validation.get("valid") is True
        and suite.get("external_observed_holdout_ready") is True
    )
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": suite.get("schema"),
        "scope": "two_source_external_observed_state_holdout_not_policy_outcome",
        "external_observed_holdout_ready": ready,
        "external_observed_state_prediction_superiority_claim": bool(
            suite.get("external_observed_state_prediction_superiority_claim")
        ),
        "scene_aligned_station_calibrated_air_quality_holdout_ready": bool(
            suite.get("scene_aligned_station_calibrated_air_quality_holdout_ready")
        ),
        "observed_policy_outcome_superiority_claim": bool(
            suite.get("observed_policy_outcome_superiority_claim")
        ),
        "openaq_external_holdout_ready": bool(openaq.get("external_holdout_ready")),
        "openaq_observation_count": _int(openaq.get("observation_count")),
        "openaq_holdout_count": _int(openaq.get("holdout_count")),
        "openaq_holdout_win_rate": _float(openaq.get("overall_holdout_win_rate")),
        "tap_external_holdout_ready": bool(tap.get("external_holdout_ready")),
        "tap_series_count": _int(tap.get("series_count")),
        "tap_holdout_count": _int(tap.get("holdout_count")),
        "tap_best_uwm_mae": _float(tap.get("best_uwm_mae")),
        "tap_best_static_baseline_mae": _float(tap.get("best_static_baseline_mae")),
        "supported_claims": suite.get("supported_claims") or [],
        "claim_level": (
            (suite.get("claim_boundary") or {}).get("max_claim_level")
            if ready
            else "not_for_claim"
        ),
        "policy_outcome_claim": False,
        "empirical_superiority_claim": False,
        "validation": validation,
        "limitations": suite.get("limitations") or [],
    }


def _station_aligned_air_quality_holdout_slice(
    holdout: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    if source_artifact_exists:
        validation = validate_uwm_station_aligned_air_quality_holdout(holdout)
    else:
        validation = {"valid": False, "errors": ["source_artifact_missing"]}
    station = holdout.get("station_alignment") or {}
    benchmark = holdout.get("holdout_benchmark") or {}
    scene_attempt = holdout.get("scene_attempt_evidence") or {}
    historical_ready = (
        source_artifact_exists
        and validation.get("valid") is True
        and holdout.get("historical_station_aligned_holdout_ready") is True
    )
    scene_ready = (
        source_artifact_exists
        and validation.get("valid") is True
        and holdout.get("scene_aligned_station_calibrated_air_quality_holdout_ready")
        is True
    )
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": holdout.get("schema"),
        "scope": "historical_station_aligned_air_quality_holdout_not_2024_scene",
        "historical_station_aligned_holdout_ready": historical_ready,
        "scene_aligned_station_calibrated_air_quality_holdout_ready": scene_ready,
        "station_name": station.get("station_name"),
        "station_observation_count": _int(station.get("station_observation_count")),
        "tap_aligned_observation_count": _int(station.get("tap_aligned_observation_count")),
        "nearest_tap_grid_distance_m": _float(station.get("nearest_tap_grid_distance_m")),
        "best_station_aligned_method": benchmark.get("best_station_aligned_method"),
        "raw_tap_mae": _float(benchmark.get("raw_tap_mae")),
        "linear_station_calibrated_tap_mae": _float(
            benchmark.get("linear_station_calibrated_tap_mae")
        ),
        "static_train_mean_mae": _float(benchmark.get("static_train_mean_mae")),
        "static_last_observation_mae": _float(
            benchmark.get("static_last_observation_mae")
        ),
        "raw_tap_beats_static_station_baselines": bool(
            benchmark.get("raw_tap_beats_static_station_baselines")
        ),
        "linear_calibration_beats_raw_tap": bool(
            benchmark.get("linear_calibration_beats_raw_tap")
        ),
        "scene_station_measurement_count": _int(
            scene_attempt.get("scene_station_measurement_count")
        ),
        "supported_claims": holdout.get("supported_claims") or [],
        "claim_level": (
            (holdout.get("claim_boundary") or {}).get("max_claim_level")
            if historical_ready
            else "not_for_claim"
        ),
        "policy_outcome_claim": False,
        "empirical_superiority_claim": False,
        "validation": validation,
        "limitations": holdout.get("limitations") or [],
    }


def _data_calibrated_mechanism_table_slice(
    table: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    if source_artifact_exists:
        validation = validate_uwm_data_calibrated_mechanism_table(table)
    else:
        validation = {"valid": False, "errors": ["source_artifact_missing"]}
    calibration = table.get("calibration_evidence") or {}
    comparison = table.get("traditional_baseline_comparison") or {}
    ready = (
        source_artifact_exists
        and validation.get("valid") is True
        and table.get("data_calibrated_mechanism_ready") is True
        and table.get("hardcoded_mechanism_replacement_ready") is True
        and (table.get("claim_boundary") or {}).get("max_claim_level") == "bounded_support"
        and table.get("observed_policy_outcome_superiority_claim") is False
    )
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": table.get("schema"),
        "scope": "simulator_mechanism_table_calibrated_from_real_state_transition_evidence_not_policy_outcome",
        "data_calibrated_mechanism_ready": ready,
        "hardcoded_mechanism_replacement_ready": ready,
        "openaq_observation_count": _int(calibration.get("openaq_observation_count")),
        "tap_holdout_count": _int(calibration.get("tap_holdout_count")),
        "station_aligned_observation_count": _int(
            calibration.get("station_aligned_observation_count")
        ),
        "noaa_scene_observation_count": _int(
            calibration.get("noaa_scene_observation_count")
        ),
        "admin_livability_row_count": _int(
            calibration.get("admin_livability_row_count")
        ),
        "observed_state_prediction_superiority_claim": bool(
            comparison.get("observed_state_prediction_superiority_claim")
        ),
        "external_temporal_transition_superiority_claim": bool(
            comparison.get("external_temporal_transition_superiority_claim")
        ),
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "supported_claims": table.get("supported_claims") or [],
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "policy_outcome_claim": False,
        "validation": validation,
        "limitations": table.get("limitations") or [],
    }


def _data_calibrated_planner_replay_slice(
    report: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    mechanism_summary = report.get("mechanism_table_summary") or {}
    uncertainty_summary = report.get("air_quality_uncertainty_calibration_summary") or {}
    risk_evaluation = report.get("risk_adjusted_planner_evaluation") or {}
    ready = (
        source_artifact_exists
        and report.get("schema") == "uwm.model_based_graph_search_report.v1"
        and mechanism_summary.get("data_calibrated_mechanism_ready") is True
        and _float(report.get("advantage_over_static_single_step")) > 0.0
        and report.get("supported_claim")
        == "data_calibrated_model_based_graph_search_advantage_over_static_heuristic"
        and report.get("empirical_superiority_claim") is False
    )
    risk_ready = (
        ready
        and uncertainty_summary.get("uwm_uncertainty_calibration_ready") is True
        and risk_evaluation.get("risk_calibrated_planner_replay_ready") is True
        and _float(risk_evaluation.get("risk_adjusted_advantage_over_static_single_step"))
        > 0.0
        and risk_evaluation.get("supported_claim")
        == "risk_calibrated_data_calibrated_planner_replay_advantage_over_static_heuristic"
        and risk_evaluation.get("observed_policy_outcome_superiority_claim") is False
        and risk_evaluation.get("empirical_superiority_claim") is False
    )
    supported_claims = []
    if ready:
        supported_claims.append(
            {
                "claim": "data_calibrated_planner_replay_advantage_over_static_heuristic",
                "scope": "data_calibrated_model_based_planner_replay_not_policy_outcome",
                "claim_level": "bounded_support",
                "policy_outcome_claim": False,
                "spatial_attribution_claim": False,
            }
        )
    if risk_ready:
        supported_claims.append(
            {
                "claim": "risk_calibrated_planner_replay_advantage_over_static_heuristic",
                "scope": "scene_uncertainty_calibrated_model_based_planner_replay_not_policy_outcome",
                "claim_level": "bounded_support",
                "policy_outcome_claim": False,
                "spatial_attribution_claim": False,
            }
        )
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": report.get("schema"),
        "scope": "data_calibrated_model_based_planner_replay_not_policy_outcome",
        "data_calibrated_planner_replay_ready": ready,
        "risk_calibrated_planner_replay_ready": risk_ready,
        "mechanism_table_ready": bool(
            mechanism_summary.get("data_calibrated_mechanism_ready")
        ),
        "mechanism_table_id": mechanism_summary.get("mechanism_table_id"),
        "air_quality_uncertainty_calibration_ready": bool(
            uncertainty_summary.get("uwm_uncertainty_calibration_ready")
        ),
        "air_quality_uncertainty_method": uncertainty_summary.get("method"),
        "air_quality_uncertainty_source_benchmark_id": uncertainty_summary.get(
            "source_benchmark_id"
        ),
        "air_quality_uncertainty_source_scope": uncertainty_summary.get(
            "source_scope"
        ),
        "air_quality_uncertainty_confidence_level": _float(
            uncertainty_summary.get("confidence_level")
        ),
        "air_quality_uncertainty_calibration_count": _int(
            uncertainty_summary.get("calibration_count")
        ),
        "air_quality_uncertainty_holdout_count": _int(
            uncertainty_summary.get("holdout_count")
        ),
        "air_quality_uwm_interval_score": _float(
            uncertainty_summary.get("uwm_interval_score")
        ),
        "air_quality_static_interval_score": _float(
            uncertainty_summary.get("static_interval_score")
        ),
        "air_quality_uwm_interval_score_reduction": _float(
            uncertainty_summary.get("uwm_interval_score_reduction")
        ),
        "pm25_scene_range_ugm3": _float(
            risk_evaluation.get("pm25_scene_range_ugm3")
        ),
        "normalized_uwm_interval_score": _float(
            risk_evaluation.get("normalized_uwm_interval_score")
        ),
        "transition_count": _int(
            (report.get("trajectory_dataset") or {}).get("transition_count")
        ),
        "best_sequence_reward": _float(
            (report.get("best_sequence") or {}).get("cumulative_reward")
        ),
        "static_single_step_reward": _float(
            (report.get("static_single_step_baseline") or {}).get("cumulative_reward")
        ),
        "advantage_over_static_single_step": _float(
            report.get("advantage_over_static_single_step")
        ),
        "best_sequence_risk_adjusted_reward": _float(
            risk_evaluation.get("best_sequence_risk_adjusted_reward")
        ),
        "static_single_step_risk_adjusted_reward": _float(
            risk_evaluation.get("static_single_step_risk_adjusted_reward")
        ),
        "risk_adjusted_advantage_over_static_single_step": _float(
            risk_evaluation.get("risk_adjusted_advantage_over_static_single_step")
        ),
        "supported_claims": supported_claims,
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "policy_outcome_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "limitations": [
            "planner_replay_uses_data_calibrated_simulator_not_observed_policy_outcome",
            "static_single_step_is_planning_baseline_not_counterfactual_policy_outcome",
        ],
    }


def _scene_aligned_gridded_air_quality_holdout_slice(
    holdout: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    if source_artifact_exists:
        validation = validate_uwm_scene_aligned_gridded_air_quality_holdout(holdout)
    else:
        validation = {"valid": False, "errors": ["source_artifact_missing"]}
    overall = holdout.get("overall_results") or {}
    negative_control = holdout.get("spatial_message_negative_control_summary") or {}
    uncertainty = holdout.get("uncertainty_calibration") or {}
    ready = (
        source_artifact_exists
        and validation.get("valid") is True
        and holdout.get("scene_aligned_gridded_air_quality_holdout_ready") is True
        and holdout.get("scene_aligned_station_calibrated_air_quality_holdout_ready")
        is False
        and (holdout.get("claim_boundary") or {}).get("max_claim_level")
        == "bounded_support"
        and holdout.get("observed_policy_outcome_superiority_claim") is False
    )
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": holdout.get("schema"),
        "scope": "scene_aligned_gridded_air_quality_state_reconstruction_not_station_or_policy_outcome",
        "scene_aligned_gridded_air_quality_holdout_ready": ready,
        "scene_aligned_station_calibrated_air_quality_holdout_ready": False,
        "admin_unit_count": _int(holdout.get("admin_unit_count")),
        "holdout_count": _int(holdout.get("holdout_count")),
        "best_uwm_method": overall.get("best_uwm_method"),
        "best_static_baseline_method": overall.get("best_static_baseline_method"),
        "best_uwm_mae": _float(overall.get("best_uwm_mae")),
        "best_static_baseline_mae": _float(overall.get("best_static_baseline_mae")),
        "best_uwm_mae_reduction": _float(overall.get("best_uwm_mae_reduction")),
        "spatial_shuffle_negative_control_passed": bool(
            negative_control.get("spatial_shuffle_negative_control_passed")
        ),
        "uwm_uncertainty_calibration_ready": bool(
            uncertainty.get("uwm_uncertainty_calibration_ready")
        ),
        "uncertainty_confidence_level": _float(uncertainty.get("confidence_level")),
        "uncertainty_calibration_count": _int(uncertainty.get("calibration_count")),
        "uwm_interval_radius": _float(uncertainty.get("uwm_interval_radius")),
        "static_interval_radius": _float(uncertainty.get("static_interval_radius")),
        "uwm_interval_coverage": _float(uncertainty.get("uwm_interval_coverage")),
        "static_interval_coverage": _float(
            uncertainty.get("static_interval_coverage")
        ),
        "uwm_interval_score": _float(uncertainty.get("uwm_interval_score")),
        "static_interval_score": _float(uncertainty.get("static_interval_score")),
        "uwm_interval_score_reduction": _float(
            uncertainty.get("uwm_interval_score_reduction")
        ),
        "supported_claims": [
            {
                "claim": "scene_aligned_gridded_pm25_spatial_message_advantage_over_static_baselines",
                "scope": "scene_aligned_gridded_air_quality_state_reconstruction_not_station_or_policy_outcome",
                "claim_level": "bounded_support",
                "policy_outcome_claim": False,
                "spatial_attribution_claim": False,
            }
        ]
        + [
            {
                "claim": "scene_aligned_gridded_pm25_conformal_uncertainty_advantage_over_static_baseline",
                "scope": "scene_aligned_gridded_air_quality_uncertainty_calibration_not_station_or_policy_outcome",
                "claim_level": "bounded_support",
                "policy_outcome_claim": False,
                "spatial_attribution_claim": False,
            }
        ]
        if ready and uncertainty.get("uwm_uncertainty_calibration_ready") is True
        else [
            {
                "claim": "scene_aligned_gridded_pm25_spatial_message_advantage_over_static_baselines",
                "scope": "scene_aligned_gridded_air_quality_state_reconstruction_not_station_or_policy_outcome",
                "claim_level": "bounded_support",
                "policy_outcome_claim": False,
                "spatial_attribution_claim": False,
            }
        ]
        if ready
        else [],
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "policy_outcome_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "validation": validation,
        "limitations": holdout.get("limitations") or [],
    }


def _multisource_livability_scene_slice(
    scene: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    evaluation = (
        (scene.get("holdout_evaluation") or {}).get(
            "air_quality_multisource_leave_one_admin_out"
        )
        or {}
    )
    source_coverage = scene.get("source_coverage") or {}
    osm_crosswalk_coverage = source_coverage.get("osm_admin_mobility_crosswalk") or {}
    admin_unit_count = _int(scene.get("admin_unit_count"))
    matched_source_count = 0
    for coverage in source_coverage.values():
        if not isinstance(coverage, dict):
            continue
        if _int(coverage.get("matched_admin_units")) == admin_unit_count:
            matched_source_count += 1
    osm_crosswalk_projected = (
        _int(osm_crosswalk_coverage.get("matched_admin_units")) == admin_unit_count
        and str(osm_crosswalk_coverage.get("unit_projection"))
        == "admin_unit_state_vector"
    )
    ready = (
        source_artifact_exists
        and scene.get("schema") == "uwm.multisource_livability_scene.v1"
        and admin_unit_count >= 30
        and matched_source_count >= 7
        and osm_crosswalk_projected
        and evaluation.get("beats_all_single_source_baselines") is True
        and _float(evaluation.get("multisource_mae"))
        < _float(evaluation.get("best_single_source_mae"), default=float("inf"))
        and scene.get("supported_claim")
        == "multisource_livability_scene_air_quality_head_beats_single_source_baselines"
        and scene.get("observed_policy_outcome_superiority_claim") is False
    )
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": scene.get("schema"),
        "scope": "multisource_admin_unit_livability_scene_with_source_gated_air_quality_holdout",
        "multisource_livability_scene_ready": ready,
        "admin_unit_count": admin_unit_count,
        "data_source_count": len(scene.get("data_sources_used") or []),
        "matched_source_count": matched_source_count,
        "osm_admin_mobility_crosswalk_projected": osm_crosswalk_projected,
        "osm_crosswalk_matched_admin_units": _int(
            osm_crosswalk_coverage.get("matched_admin_units")
        ),
        "osm_assigned_road_segment_count_in_scene": _int(
            osm_crosswalk_coverage.get("assigned_road_segment_count")
        ),
        "osm_crosswalk_assignment_rule": osm_crosswalk_coverage.get(
            "assignment_rule"
        ),
        "air_quality_target": evaluation.get("target"),
        "air_quality_model": evaluation.get("model"),
        "air_quality_multisource_mae": _float(evaluation.get("multisource_mae")),
        "air_quality_best_single_source_mae": _float(
            evaluation.get("best_single_source_mae")
        ),
        "air_quality_mae_reduction_vs_best_single_source": _float(
            evaluation.get("mae_reduction_vs_best_single_source")
        ),
        "air_quality_paired_win_count_vs_chap": _int(
            evaluation.get("paired_win_count_vs_chap")
        ),
        "air_quality_paired_loss_count_vs_chap": _int(
            evaluation.get("paired_loss_count_vs_chap")
        ),
        "spatial_interaction_negative_control_passed": bool(
            evaluation.get("spatial_interaction_negative_control_passed")
        ),
        "supported_claims": [
            {
                "claim": "multisource_livability_scene_air_quality_head_beats_single_source_baselines",
                "scope": "multisource_admin_unit_livability_scene_with_source_gated_air_quality_holdout",
                "claim_level": "bounded_support",
                "policy_outcome_claim": False,
                "spatial_attribution_claim": False,
            }
        ]
        if ready
        else [],
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "policy_outcome_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "limitations": [
            "air_quality_head_advantage_is_marginal_and_not_spatial_interaction_attribution",
            "osm_mobility_crosswalk_uses_bbox_midpoint_not_polygon_overlay",
            "not_policy_intervention_outcome",
        ],
    }


def _osm_admin_mobility_crosswalk_slice(
    crosswalk: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    evaluation = (
        (crosswalk.get("holdout_evaluation") or {}).get(
            "service_accessibility_leave_one_admin_out"
        )
        or {}
    )
    ready = (
        source_artifact_exists
        and crosswalk.get("schema") == "uwm.osm_admin_mobility_crosswalk.v1"
        and _int(crosswalk.get("admin_unit_count")) >= 30
        and _int(crosswalk.get("assigned_road_segment_count")) > 0
        and evaluation.get("beats_all_traditional_static_baselines") is True
        and _float(evaluation.get("mobility_crosswalk_mae"))
        < _float(evaluation.get("best_traditional_static_mae"), default=float("inf"))
        and crosswalk.get("supported_claim")
        == "osm_admin_mobility_crosswalk_service_accessibility_head_beats_static_baselines"
        and crosswalk.get("observed_policy_outcome_superiority_claim") is False
    )
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": crosswalk.get("schema"),
        "scope": "osm_road_to_admin_mobility_crosswalk_service_accessibility_not_policy_outcome",
        "osm_admin_mobility_crosswalk_ready": ready,
        "admin_unit_count": _int(crosswalk.get("admin_unit_count")),
        "osm_raw_node_count": _int(crosswalk.get("osm_raw_node_count")),
        "osm_highway_way_count": _int(crosswalk.get("osm_highway_way_count")),
        "assigned_road_segment_count": _int(
            crosswalk.get("assigned_road_segment_count")
        ),
        "unassigned_road_segment_count": _int(
            crosswalk.get("unassigned_road_segment_count")
        ),
        "assignment_rule": crosswalk.get("assignment_rule"),
        "service_accessibility_target": evaluation.get("target"),
        "service_accessibility_model": evaluation.get("model"),
        "service_accessibility_mobility_mae": _float(
            evaluation.get("mobility_crosswalk_mae")
        ),
        "service_accessibility_best_static_mae": _float(
            evaluation.get("best_traditional_static_mae")
        ),
        "service_accessibility_mae_reduction": _float(
            evaluation.get("mae_reduction_vs_best_traditional_static")
        ),
        "service_accessibility_paired_win_count": _int(
            evaluation.get("paired_win_count_vs_best_traditional")
        ),
        "service_accessibility_paired_loss_count": _int(
            evaluation.get("paired_loss_count_vs_best_traditional")
        ),
        "supported_claims": [
            {
                "claim": "osm_admin_mobility_crosswalk_service_accessibility_head_beats_static_baselines",
                "scope": "osm_road_to_admin_mobility_crosswalk_service_accessibility_not_policy_outcome",
                "claim_level": "bounded_support",
                "policy_outcome_claim": False,
                "spatial_attribution_claim": False,
            }
        ]
        if ready
        else [],
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "policy_outcome_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "limitations": crosswalk.get("limitations") or [],
    }


def _building_floor_morphology_slice(
    morphology: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    evaluations = (
        (morphology.get("holdout_evaluation") or {}).get(
            "morphology_endpoint_leave_one_admin_out"
        )
        or []
    )
    ready_endpoint_count = sum(
        item.get("beats_2d_baselines") is True for item in evaluations
    )
    ready = (
        source_artifact_exists
        and morphology.get("schema") == "uwm.building_floor_morphology.v1"
        and _int(morphology.get("admin_unit_count")) >= 30
        and _int(morphology.get("assigned_building_count")) > 0
        and ready_endpoint_count == len(evaluations)
        and len(evaluations) >= 2
        and morphology.get("supported_claim")
        == "building_floor_25d_morphology_service_endpoint_head_beats_2d_baselines"
        and morphology.get("true_3d_claim") is False
    )
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": morphology.get("schema"),
        "scope": "building_floor_25d_morphology_not_full_3d_city_model",
        "building_floor_morphology_ready": ready,
        "admin_unit_count": _int(morphology.get("admin_unit_count")),
        "source_building_record_count": _int(
            morphology.get("source_building_record_count")
        ),
        "assigned_building_count": _int(morphology.get("assigned_building_count")),
        "total_floor_count": _int(morphology.get("total_floor_count")),
        "max_floor": _int(morphology.get("max_floor")),
        "ready_endpoint_count": ready_endpoint_count,
        "endpoint_count": len(evaluations),
        "true_3d_claim": False,
        "supported_claims": [
            {
                "claim": "building_floor_25d_morphology_service_endpoint_head_beats_2d_baselines",
                "scope": "building_floor_25d_morphology_not_full_3d_city_model",
                "claim_level": "bounded_support",
                "policy_outcome_claim": False,
                "spatial_attribution_claim": False,
            }
        ]
        if ready
        else [],
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "policy_outcome_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "limitations": [
            "building_floor_is_25d_not_mesh_bim_or_point_cloud",
            "building_assignment_uses_bbox_center_to_admin_bbox",
        ],
    }


def _livability_endpoint_suite_slice(
    suite: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    ready = (
        source_artifact_exists
        and suite.get("schema") == "uwm.livability_endpoint_suite.v1"
        and _int(suite.get("admin_unit_count")) >= 30
        and _int(suite.get("endpoint_count")) >= 3
        and _int(suite.get("ready_endpoint_count")) == _int(
            suite.get("endpoint_count")
        )
        and suite.get("all_endpoints_beat_traditional_baselines") is True
        and _float(suite.get("mean_relative_mae_reduction_vs_best_traditional")) > 0.0
        and _float(suite.get("min_relative_mae_reduction_vs_best_traditional")) > 0.0
        and suite.get("supported_claim")
        == "uwm_final_livability_endpoint_suite_beats_traditional_baselines"
        and suite.get("observed_policy_outcome_superiority_claim") is False
    )
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": suite.get("schema"),
        "scope": "final_livability_endpoint_prediction_suite_not_policy_outcome",
        "livability_endpoint_suite_ready": ready,
        "admin_unit_count": _int(suite.get("admin_unit_count")),
        "endpoint_count": _int(suite.get("endpoint_count")),
        "ready_endpoint_count": _int(suite.get("ready_endpoint_count")),
        "endpoint_domains": list(suite.get("endpoint_domains") or []),
        "mean_relative_mae_reduction_vs_best_traditional": _float(
            suite.get("mean_relative_mae_reduction_vs_best_traditional")
        ),
        "min_relative_mae_reduction_vs_best_traditional": _float(
            suite.get("min_relative_mae_reduction_vs_best_traditional")
        ),
        "supported_claims": [
            {
                "claim": "uwm_final_livability_endpoint_suite_beats_traditional_baselines",
                "scope": "final_livability_endpoint_prediction_suite_not_policy_outcome",
                "claim_level": "bounded_support",
                "policy_outcome_claim": False,
                "spatial_attribution_claim": False,
            }
        ]
        if ready
        else [],
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "policy_outcome_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "limitations": [
            "endpoint_suite_validates_prediction_targets_not_policy_outcomes",
            "service_endpoint_targets_share_public_proxy_service_inventory_family",
        ],
    }


def _endpoint_aligned_planner_evaluator_slice(
    evaluator: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    ready = (
        source_artifact_exists
        and evaluator.get("schema") == "uwm.endpoint_aligned_planner_evaluator.v1"
        and _int(evaluator.get("endpoint_count")) >= 3
        and _float(evaluator.get("planner_endpoint_aligned_score"))
        > _float(evaluator.get("static_endpoint_aligned_score"))
        and _float(evaluator.get("endpoint_aligned_advantage_over_static")) > 0.0
        and evaluator.get("supported_claim")
        == "endpoint_aligned_planner_replay_advantage_over_static_heuristic"
        and evaluator.get("observed_policy_outcome_superiority_claim") is False
    )
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": evaluator.get("schema"),
        "scope": "endpoint_aligned_planner_replay_not_policy_outcome",
        "endpoint_aligned_planner_evaluator_ready": ready,
        "endpoint_count": _int(evaluator.get("endpoint_count")),
        "planner_sequence_action_count": _int(
            evaluator.get("planner_sequence_action_count")
        ),
        "static_sequence_action_count": _int(
            evaluator.get("static_sequence_action_count")
        ),
        "planner_endpoint_aligned_score": _float(
            evaluator.get("planner_endpoint_aligned_score")
        ),
        "static_endpoint_aligned_score": _float(
            evaluator.get("static_endpoint_aligned_score")
        ),
        "endpoint_aligned_advantage_over_static": _float(
            evaluator.get("endpoint_aligned_advantage_over_static")
        ),
        "endpoint_aligned_advantage_ratio": _float(
            evaluator.get("endpoint_aligned_advantage_ratio")
        ),
        "supported_claims": [
            {
                "claim": "endpoint_aligned_planner_replay_advantage_over_static_heuristic",
                "scope": "endpoint_aligned_planner_replay_not_policy_outcome",
                "claim_level": "bounded_support",
                "policy_outcome_claim": False,
                "spatial_attribution_claim": False,
            }
        ]
        if ready
        else [],
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "policy_outcome_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "limitations": [
            "planner_evaluator_uses_offline_rollout_deltas_not_observed_policy_outcomes",
            "endpoint_weights_come_from_prediction_holdout_not_intervention_effects",
        ],
    }


def _spatial_spillover_planner_evaluator_slice(
    evaluator: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    ready = (
        source_artifact_exists
        and evaluator.get("schema") == "uwm.spatial_spillover_planner_evaluator.v1"
        and _int(evaluator.get("planner_neighbor_benefited_unit_count"))
        > _int(evaluator.get("static_neighbor_benefited_unit_count"))
        and _float(evaluator.get("neighbor_livability_delta_advantage")) > 0.0
        and evaluator.get("supported_claim")
        == "spatial_spillover_planner_replay_advantage_over_static_heuristic"
        and evaluator.get("observed_policy_outcome_superiority_claim") is False
    )
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": evaluator.get("schema"),
        "scope": "spatial_spillover_planner_replay_not_policy_outcome",
        "spatial_spillover_planner_evaluator_ready": ready,
        "planner_neighbor_benefited_unit_count": _int(
            evaluator.get("planner_neighbor_benefited_unit_count")
        ),
        "static_neighbor_benefited_unit_count": _int(
            evaluator.get("static_neighbor_benefited_unit_count")
        ),
        "neighbor_benefited_unit_count_advantage": _int(
            evaluator.get("neighbor_benefited_unit_count_advantage")
        ),
        "planner_neighbor_livability_delta_sum": _float(
            evaluator.get("planner_neighbor_livability_delta_sum")
        ),
        "static_neighbor_livability_delta_sum": _float(
            evaluator.get("static_neighbor_livability_delta_sum")
        ),
        "neighbor_livability_delta_advantage": _float(
            evaluator.get("neighbor_livability_delta_advantage")
        ),
        "neighbor_livability_delta_advantage_ratio": _float(
            evaluator.get("neighbor_livability_delta_advantage_ratio")
        ),
        "supported_claims": [
            {
                "claim": "spatial_spillover_planner_replay_advantage_over_static_heuristic",
                "scope": "spatial_spillover_planner_replay_not_policy_outcome",
                "claim_level": "bounded_support",
                "policy_outcome_claim": False,
                "spatial_attribution_claim": False,
            }
        ]
        if ready
        else [],
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "policy_outcome_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "limitations": [
            "spillover_uses_first_order_admin_adjacency_not_travel_time_network",
            "planner_spillover_uses_offline_rollout_deltas_not_observed_policy_outcomes",
        ],
    }


def _livability_decision_package_slice(
    package: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    comparison = package.get("comparison_against_traditional_static_heuristic") or {}
    action_portfolio = package.get("action_portfolio") or {}
    endpoint_evidence = package.get("validated_endpoint_evidence") or {}
    replay_baselines = package.get("replay_baseline_suite") or {}
    endpoint_weight_sensitivity = package.get("endpoint_weight_sensitivity") or {}
    spatial_kernel = package.get("spatial_spillover_kernel_evidence") or {}
    rl_training = package.get("rl_training_evidence") or {}
    graph_drl_training = package.get("graph_drl_training_evidence") or {}
    ready = (
        source_artifact_exists
        and package.get("schema") == "uwm.livability_decision_package.v1"
        and package.get("decision_package_ready") is True
        and _float(comparison.get("endpoint_aligned_advantage_over_static")) > 0.0
        and _float(comparison.get("risk_adjusted_advantage_over_static")) > 0.0
        and _float(comparison.get("neighbor_livability_delta_advantage")) > 0.0
        and package.get("supported_claim")
        == "uwm_livability_decision_package_beats_static_heuristic_on_validated_endpoints_spillover_and_risk"
        and package.get("observed_policy_outcome_superiority_claim") is False
    )
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": package.get("schema"),
        "scope": "final_livability_decision_package_not_policy_outcome",
        "livability_decision_package_ready": ready,
        "action_count": _int(action_portfolio.get("action_count")),
        "target_unit_count": _int(action_portfolio.get("target_unit_count")),
        "target_units": list(action_portfolio.get("target_units") or []),
        "endpoint_count": _int(endpoint_evidence.get("endpoint_count")),
        "ready_endpoint_count": _int(endpoint_evidence.get("ready_endpoint_count")),
        "building_floor_morphology_projected": bool(
            endpoint_evidence.get("building_floor_morphology_projected")
        ),
        "mean_relative_mae_reduction_vs_best_traditional": _float(
            endpoint_evidence.get("mean_relative_mae_reduction_vs_best_traditional")
        ),
        "endpoint_aligned_advantage_over_static": _float(
            comparison.get("endpoint_aligned_advantage_over_static")
        ),
        "endpoint_aligned_advantage_ratio": _float(
            comparison.get("endpoint_aligned_advantage_ratio")
        ),
        "single_action_transition_count": _int(
            replay_baselines.get("single_action_transition_count")
        ),
        "best_single_action_reward": _float(
            replay_baselines.get("best_single_action_reward")
        ),
        "advantage_vs_best_single_action": _float(
            replay_baselines.get("advantage_vs_best_single_action")
        ),
        "single_action_win_rate": _float(
            replay_baselines.get("single_action_win_rate")
        ),
        "best_sequence_percentile_vs_single_actions": _float(
            replay_baselines.get("best_sequence_percentile_vs_single_actions")
        ),
        "empirical_p_value_vs_single_action_baselines": _float(
            replay_baselines.get("empirical_one_sided_p_value")
        ),
        "endpoint_weight_sensitivity_profile_count": _int(
            endpoint_weight_sensitivity.get("profile_count")
        ),
        "endpoint_weight_sensitivity_all_positive": bool(
            endpoint_weight_sensitivity.get("all_profiles_advantage_positive")
        ),
        "endpoint_weight_sensitivity_min_advantage": _float(
            endpoint_weight_sensitivity.get("min_advantage_over_static")
        ),
        "risk_adjusted_advantage_over_static": _float(
            comparison.get("risk_adjusted_advantage_over_static")
        ),
        "neighbor_livability_delta_advantage": _float(
            comparison.get("neighbor_livability_delta_advantage")
        ),
        "spatial_spillover_kernel_ready": bool(spatial_kernel.get("ready")),
        "spatial_spillover_kernel_directional_edge_count": _int(
            spatial_kernel.get("directional_edge_count")
        ),
        "spatial_spillover_kernel_max_spillover_factor": _float(
            spatial_kernel.get("max_spillover_factor")
        ),
        "spatial_spillover_kernel_uses_shared_boundary_length": bool(
            spatial_kernel.get("uses_shared_boundary_length")
        ),
        "rl_training_ready": bool(rl_training.get("ready")),
        "rl_training_algorithm": rl_training.get("algorithm"),
        "rl_training_episode_count": _int(rl_training.get("episode_count")),
        "rl_training_advantage_over_traditional_static": _float(
            rl_training.get("advantage_over_traditional_static")
        ),
        "graph_drl_training_ready": bool(graph_drl_training.get("ready")),
        "graph_drl_algorithm": graph_drl_training.get("algorithm"),
        "graph_drl_is_deep_rl": bool(graph_drl_training.get("is_deep_rl")),
        "graph_drl_uses_graph_message_passing": bool(
            graph_drl_training.get("uses_graph_message_passing")
        ),
        "graph_policy_or_value_network_trained": bool(
            graph_drl_training.get("policy_or_value_network_trained")
        ),
        "graph_drl_training_sample_count": _int(
            graph_drl_training.get("training_sample_count")
        ),
        "graph_drl_q_return_mae": _float(
            graph_drl_training.get("q_return_mae")
        ),
        "graph_drl_train_mean_return_mae": _float(
            graph_drl_training.get("train_mean_return_mae")
        ),
        "graph_drl_advantage_over_traditional_static": _float(
            graph_drl_training.get("advantage_over_traditional_static")
        ),
        "planner_benefited_unit_count": _int(
            comparison.get("planner_benefited_unit_count")
        ),
        "static_benefited_unit_count": _int(
            comparison.get("static_benefited_unit_count")
        ),
        "planner_positive_equity_delta_sum": _float(
            comparison.get("planner_positive_equity_delta_sum")
        ),
        "static_positive_equity_delta_sum": _float(
            comparison.get("static_positive_equity_delta_sum")
        ),
        "supported_claims": [
            {
                "claim": "uwm_livability_decision_package_beats_static_heuristic_on_validated_endpoints_spillover_and_risk",
                "scope": "final_livability_decision_package_not_policy_outcome",
                "claim_level": "bounded_support",
                "policy_outcome_claim": False,
                "spatial_attribution_claim": False,
            }
        ]
        if ready
        else [],
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "policy_outcome_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "limitations": [
            "decision_package_uses_offline_planner_replay_not_observed_policy_outcome",
            "static_baseline_is_heuristic_not_full_policy_counterfactual",
        ],
    }


def _livability_rl_training_slice(
    report: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    training = report.get("training_summary") or {}
    learned = report.get("learned_policy_evaluation") or {}
    baseline = report.get("baseline_evaluation") or {}
    algorithm = report.get("rl_algorithm") or {}
    ready = (
        source_artifact_exists
        and report.get("schema") == "uwm.livability_rl_training_report.v1"
        and algorithm.get("algorithm") == "dyna_q_tabular_model_based_rl"
        and _int(training.get("episode_count")) > 0
        and _float(learned.get("advantage_over_traditional_static")) > 0.0
        and report.get("supported_claim")
        == "trained_model_based_q_agent_improves_same_scene_static_livability_baseline"
        and report.get("observed_policy_outcome_superiority_claim") is False
    )
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": report.get("schema"),
        "scope": "simulator_grounded_model_based_rl_training_not_policy_outcome",
        "livability_rl_training_ready": ready,
        "algorithm": algorithm.get("algorithm"),
        "uses_simulator_model_for_planning": bool(
            algorithm.get("uses_simulator_model_for_planning")
        ),
        "episode_count": _int(training.get("episode_count")),
        "q_state_count": _int(training.get("q_state_count")),
        "learned_replay_transition_count": _int(
            training.get("learned_replay_transition_count")
        ),
        "real_data_graph_node_count": _int(
            training.get("real_data_graph_node_count")
        ),
        "real_data_available_action_count": _int(
            training.get("real_data_available_action_count")
        ),
        "spatial_spillover_directional_edge_count": _int(
            training.get("spatial_spillover_directional_edge_count")
        ),
        "learned_policy_cumulative_reward": _float(
            learned.get("learned_policy_cumulative_reward")
        ),
        "traditional_static_cumulative_reward": _float(
            baseline.get("traditional_static_cumulative_reward")
        ),
        "advantage_over_traditional_static": _float(
            learned.get("advantage_over_traditional_static")
        ),
        "policy_or_value_network_trained": False,
        "supported_claims": [
            {
                "claim": "trained_model_based_q_agent_improves_same_scene_static_livability_baseline",
                "scope": "simulator_grounded_model_based_rl_training_not_policy_outcome",
                "claim_level": "bounded_support",
                "policy_outcome_claim": False,
                "spatial_attribution_claim": False,
            }
        ]
        if ready
        else [],
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "policy_outcome_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "limitations": [
            "tabular_model_based_rl_uses_simulator_rollouts_not_observed_intervention_logs",
            "policy_or_value_network_not_trained_in_this_stage",
        ],
    }


def _livability_graph_drl_training_slice(
    report: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    training = report.get("training_summary") or {}
    holdout = report.get("holdout_metrics") or {}
    learned = report.get("learned_policy_evaluation") or {}
    baseline = report.get("baseline_evaluation") or {}
    algorithm = report.get("drl_algorithm") or {}
    ready = (
        source_artifact_exists
        and report.get("schema") == "uwm.livability_graph_drl_training_report.v1"
        and algorithm.get("algorithm") == "graph_dqn_fitted_q_model_based_rl"
        and algorithm.get("is_deep_rl") is True
        and algorithm.get("is_model_based") is True
        and algorithm.get("is_model_free") is False
        and algorithm.get("uses_graph_message_passing") is True
        and algorithm.get("policy_or_value_network_trained") is True
        and _int(training.get("training_sample_count")) > 0
        and _float(holdout.get("q_return_mae")) < _float(
            holdout.get("train_mean_return_mae")
        )
        and _float(learned.get("advantage_over_traditional_static")) > 0.0
        and report.get("supported_claim")
        == "graph_dqn_value_network_improves_same_scene_static_livability_baseline"
        and report.get("observed_policy_outcome_superiority_claim") is False
    )
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": report.get("schema"),
        "scope": "simulator_grounded_graph_drl_training_not_policy_outcome",
        "livability_graph_drl_training_ready": ready,
        "algorithm": algorithm.get("algorithm"),
        "is_deep_rl": bool(algorithm.get("is_deep_rl")),
        "is_model_based": bool(algorithm.get("is_model_based")),
        "is_model_free": bool(algorithm.get("is_model_free")),
        "uses_graph_message_passing": bool(
            algorithm.get("uses_graph_message_passing")
        ),
        "policy_or_value_network_trained": bool(
            algorithm.get("policy_or_value_network_trained")
        ),
        "training_sample_count": _int(training.get("training_sample_count")),
        "train_count": _int(training.get("train_count")),
        "holdout_count": _int(training.get("holdout_count")),
        "real_data_graph_node_count": _int(
            training.get("real_data_graph_node_count")
        ),
        "real_data_graph_edge_count": _int(
            training.get("real_data_graph_edge_count")
        ),
        "real_data_available_action_count": _int(
            training.get("real_data_available_action_count")
        ),
        "spatial_spillover_directional_edge_count": _int(
            training.get("spatial_spillover_directional_edge_count")
        ),
        "q_return_mae": _float(holdout.get("q_return_mae")),
        "train_mean_return_mae": _float(holdout.get("train_mean_return_mae")),
        "q_return_rmse": _float(holdout.get("q_return_rmse")),
        "train_mean_return_rmse": _float(
            holdout.get("train_mean_return_rmse")
        ),
        "graph_dqn_policy_cumulative_reward": _float(
            learned.get("graph_dqn_policy_cumulative_reward")
        ),
        "traditional_static_cumulative_reward": _float(
            baseline.get("traditional_static_cumulative_reward")
        ),
        "advantage_over_traditional_static": _float(
            learned.get("advantage_over_traditional_static")
        ),
        "supported_claims": [
            {
                "claim": "graph_dqn_value_network_improves_same_scene_static_livability_baseline",
                "scope": "simulator_grounded_graph_drl_training_not_policy_outcome",
                "claim_level": "bounded_support",
                "policy_outcome_claim": False,
                "spatial_attribution_claim": False,
            }
        ]
        if ready
        else [],
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "policy_outcome_claim": False,
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "limitations": [
            "graph_dqn_value_network_trained_on_simulator_generated_returns_not_observed_intervention_logs",
            "graph_message_passing_uses_existing_admin_graph_and_spatial_spillover_kernel",
        ],
    }


def _supported_claims(
    openaq_slice: dict[str, Any],
    tap_transition_slice: dict[str, Any],
    rollout_slice: dict[str, Any],
    intervention_slice: dict[str, Any],
    causal_policy_slice: dict[str, Any],
    external_observed_slice: dict[str, Any],
    station_aligned_slice: dict[str, Any],
    data_calibrated_mechanism_slice: dict[str, Any],
    data_calibrated_planner_replay_slice: dict[str, Any],
    scene_aligned_gridded_slice: dict[str, Any],
    multisource_livability_scene_slice: dict[str, Any],
    osm_admin_mobility_crosswalk_slice: dict[str, Any],
    building_floor_morphology_slice: dict[str, Any],
    livability_endpoint_suite_slice: dict[str, Any],
    endpoint_aligned_planner_evaluator_slice: dict[str, Any],
    spatial_spillover_planner_evaluator_slice: dict[str, Any],
    livability_decision_package_slice: dict[str, Any],
    livability_rl_training_slice: dict[str, Any],
    livability_graph_drl_training_slice: dict[str, Any],
) -> list[dict[str, Any]]:
    claims = []
    if _observed_state_prediction_superiority(openaq_slice):
        claims.append(
            {
                "claim": openaq_slice["supported_claim"],
                "scope": openaq_slice["scope"],
                "claim_level": openaq_slice["claim_level"],
                "policy_outcome_claim": False,
            }
        )
    if _external_temporal_transition_superiority(tap_transition_slice):
        claims.append(
            {
                "claim": tap_transition_slice["supported_claim"],
                "scope": tap_transition_slice["scope"],
                "claim_level": tap_transition_slice["claim_level"],
                "policy_outcome_claim": False,
                "spatial_attribution_claim": False,
            }
        )
    if rollout_slice.get("imagined_advantage_over_static", 0.0) > 0:
        claims.append(
            {
                "claim": rollout_slice["supported_claim"],
                "scope": rollout_slice["scope"],
                "claim_level": rollout_slice["claim_level"],
                "policy_outcome_claim": False,
            }
        )
    if intervention_slice.get("supported_claim"):
        claims.append(
            {
                "claim": intervention_slice["supported_claim"],
                "scope": intervention_slice["scope"],
                "claim_level": intervention_slice["claim_level"],
                "policy_outcome_claim": False,
            }
        )
    if _causal_policy_diagnostic_ready(causal_policy_slice):
        for causal_claim in causal_policy_slice.get("supported_claims") or []:
            claims.append(
                {
                    "claim": causal_claim.get("claim"),
                    "scope": causal_claim.get("scope"),
                    "claim_level": causal_claim.get("claim_level"),
                    "policy_outcome_claim": False,
                    "spatial_attribution_claim": False,
                }
            )
    if _external_observed_holdout_ready(external_observed_slice):
        for external_claim in external_observed_slice.get("supported_claims") or []:
            claims.append(
                {
                    "claim": external_claim.get("claim"),
                    "scope": external_claim.get("scope"),
                    "claim_level": external_claim.get("claim_level"),
                    "policy_outcome_claim": False,
                    "spatial_attribution_claim": False,
                }
            )
    if station_aligned_slice.get("historical_station_aligned_holdout_ready") is True:
        for station_claim in station_aligned_slice.get("supported_claims") or []:
            claims.append(
                {
                    "claim": station_claim.get("claim"),
                    "scope": station_claim.get("scope"),
                    "claim_level": station_claim.get("claim_level"),
                    "policy_outcome_claim": False,
                    "spatial_attribution_claim": False,
                }
            )
    if data_calibrated_mechanism_slice.get("data_calibrated_mechanism_ready") is True:
        for mechanism_claim in data_calibrated_mechanism_slice.get("supported_claims") or []:
            claims.append(
                {
                    "claim": mechanism_claim.get("claim"),
                    "scope": mechanism_claim.get("scope"),
                    "claim_level": mechanism_claim.get("claim_level"),
                    "policy_outcome_claim": False,
                    "spatial_attribution_claim": False,
                }
            )
    if (
        data_calibrated_planner_replay_slice.get(
            "data_calibrated_planner_replay_ready"
        )
        is True
    ):
        for planner_claim in data_calibrated_planner_replay_slice.get("supported_claims") or []:
            claims.append(
                {
                    "claim": planner_claim.get("claim"),
                    "scope": planner_claim.get("scope"),
                    "claim_level": planner_claim.get("claim_level"),
                    "policy_outcome_claim": False,
                    "spatial_attribution_claim": False,
                }
            )
    if scene_aligned_gridded_slice.get(
        "scene_aligned_gridded_air_quality_holdout_ready"
    ) is True:
        for scene_claim in scene_aligned_gridded_slice.get("supported_claims") or []:
            claims.append(
                {
                    "claim": scene_claim.get("claim"),
                    "scope": scene_claim.get("scope"),
                    "claim_level": scene_claim.get("claim_level"),
                    "policy_outcome_claim": False,
                    "spatial_attribution_claim": False,
                }
            )
    if multisource_livability_scene_slice.get("multisource_livability_scene_ready") is True:
        for scene_claim in multisource_livability_scene_slice.get("supported_claims") or []:
            claims.append(
                {
                    "claim": scene_claim.get("claim"),
                    "scope": scene_claim.get("scope"),
                    "claim_level": scene_claim.get("claim_level"),
                    "policy_outcome_claim": False,
                    "spatial_attribution_claim": False,
                }
            )
    if osm_admin_mobility_crosswalk_slice.get("osm_admin_mobility_crosswalk_ready") is True:
        for mobility_claim in osm_admin_mobility_crosswalk_slice.get("supported_claims") or []:
            claims.append(
                {
                    "claim": mobility_claim.get("claim"),
                    "scope": mobility_claim.get("scope"),
                    "claim_level": mobility_claim.get("claim_level"),
                    "policy_outcome_claim": False,
                    "spatial_attribution_claim": False,
                }
            )
    if building_floor_morphology_slice.get("building_floor_morphology_ready") is True:
        for morphology_claim in building_floor_morphology_slice.get("supported_claims") or []:
            claims.append(
                {
                    "claim": morphology_claim.get("claim"),
                    "scope": morphology_claim.get("scope"),
                    "claim_level": morphology_claim.get("claim_level"),
                    "policy_outcome_claim": False,
                    "spatial_attribution_claim": False,
                }
            )
    if livability_endpoint_suite_slice.get("livability_endpoint_suite_ready") is True:
        for endpoint_claim in livability_endpoint_suite_slice.get("supported_claims") or []:
            claims.append(
                {
                    "claim": endpoint_claim.get("claim"),
                    "scope": endpoint_claim.get("scope"),
                    "claim_level": endpoint_claim.get("claim_level"),
                    "policy_outcome_claim": False,
                    "spatial_attribution_claim": False,
                }
            )
    if (
        endpoint_aligned_planner_evaluator_slice.get(
            "endpoint_aligned_planner_evaluator_ready"
        )
        is True
    ):
        for planner_claim in endpoint_aligned_planner_evaluator_slice.get(
            "supported_claims"
        ) or []:
            claims.append(
                {
                    "claim": planner_claim.get("claim"),
                    "scope": planner_claim.get("scope"),
                    "claim_level": planner_claim.get("claim_level"),
                    "policy_outcome_claim": False,
                    "spatial_attribution_claim": False,
                }
            )
    if (
        spatial_spillover_planner_evaluator_slice.get(
            "spatial_spillover_planner_evaluator_ready"
        )
        is True
    ):
        for spillover_claim in spatial_spillover_planner_evaluator_slice.get(
            "supported_claims"
        ) or []:
            claims.append(
                {
                    "claim": spillover_claim.get("claim"),
                    "scope": spillover_claim.get("scope"),
                    "claim_level": spillover_claim.get("claim_level"),
                    "policy_outcome_claim": False,
                    "spatial_attribution_claim": False,
                }
            )
    if (
        livability_decision_package_slice.get(
            "livability_decision_package_ready"
        )
        is True
    ):
        for decision_claim in livability_decision_package_slice.get(
            "supported_claims"
        ) or []:
            claims.append(
                {
                    "claim": decision_claim.get("claim"),
                    "scope": decision_claim.get("scope"),
                    "claim_level": decision_claim.get("claim_level"),
                    "policy_outcome_claim": False,
                    "spatial_attribution_claim": False,
                }
            )
    if (
        livability_rl_training_slice.get("livability_rl_training_ready")
        is True
    ):
        for rl_claim in livability_rl_training_slice.get("supported_claims") or []:
            claims.append(
                {
                    "claim": rl_claim.get("claim"),
                    "scope": rl_claim.get("scope"),
                    "claim_level": rl_claim.get("claim_level"),
                    "policy_outcome_claim": False,
                    "spatial_attribution_claim": False,
                }
            )
    if (
        livability_graph_drl_training_slice.get(
            "livability_graph_drl_training_ready"
        )
        is True
    ):
        for graph_drl_claim in livability_graph_drl_training_slice.get(
            "supported_claims"
        ) or []:
            claims.append(
                {
                    "claim": graph_drl_claim.get("claim"),
                    "scope": graph_drl_claim.get("scope"),
                    "claim_level": graph_drl_claim.get("claim_level"),
                    "policy_outcome_claim": False,
                    "spatial_attribution_claim": False,
                }
            )
    if _bounded_final_system_superiority_claim(
        openaq_slice,
        tap_transition_slice,
        scene_aligned_gridded_slice,
        multisource_livability_scene_slice,
        livability_endpoint_suite_slice,
        endpoint_aligned_planner_evaluator_slice,
    ):
        claims.append(
            {
                "claim": "uwm_bounded_final_endpoint_and_planner_advantage_over_traditional_methods",
                "scope": "bounded_final_endpoint_prediction_and_endpoint_aligned_planner_replay_not_policy_outcome",
                "claim_level": "bounded_support",
                "policy_outcome_claim": False,
                "spatial_attribution_claim": False,
            }
        )
    return claims


def _bounded_final_system_superiority_claim(
    openaq_slice: dict[str, Any],
    tap_transition_slice: dict[str, Any],
    scene_aligned_gridded_slice: dict[str, Any],
    multisource_livability_scene_slice: dict[str, Any],
    livability_endpoint_suite_slice: dict[str, Any],
    endpoint_aligned_planner_evaluator_slice: dict[str, Any],
) -> bool:
    return (
        _observed_state_prediction_superiority(openaq_slice)
        and _external_temporal_transition_superiority(tap_transition_slice)
        and scene_aligned_gridded_slice.get(
            "scene_aligned_gridded_air_quality_holdout_ready"
        )
        is True
        and multisource_livability_scene_slice.get(
            "multisource_livability_scene_ready"
        )
        is True
        and livability_endpoint_suite_slice.get("livability_endpoint_suite_ready")
        is True
        and endpoint_aligned_planner_evaluator_slice.get(
            "endpoint_aligned_planner_evaluator_ready"
        )
        is True
    )


def _causal_policy_diagnostic_ready(causal_policy_slice: dict[str, Any]) -> bool:
    return (
        causal_policy_slice.get("source_artifact_exists") is True
        and causal_policy_slice.get("algorithmic_causal_diagnostic_ready") is True
        and causal_policy_slice.get("observed_local_policy_outcome_ready") is False
        and causal_policy_slice.get("observed_policy_outcome_superiority_claim") is False
        and causal_policy_slice.get("claim_level") == "bounded_support"
    )


def _external_observed_holdout_ready(external_observed_slice: dict[str, Any]) -> bool:
    return (
        external_observed_slice.get("source_artifact_exists") is True
        and external_observed_slice.get("external_observed_holdout_ready") is True
        and external_observed_slice.get(
            "scene_aligned_station_calibrated_air_quality_holdout_ready"
        )
        is False
        and external_observed_slice.get("observed_policy_outcome_superiority_claim") is False
        and external_observed_slice.get("claim_level") == "bounded_support"
    )


def _scene_aligned_station_calibrated_ready(station_aligned_slice: dict[str, Any]) -> bool:
    return (
        station_aligned_slice.get("source_artifact_exists") is True
        and station_aligned_slice.get(
            "scene_aligned_station_calibrated_air_quality_holdout_ready"
        )
        is True
    )


def _external_temporal_transition_superiority(tap_transition_slice: dict[str, Any]) -> bool:
    return (
        tap_transition_slice.get("source_artifact_exists") is True
        and tap_transition_slice.get("claim_level") == "bounded_support"
        and tap_transition_slice.get("supported_claim")
        == "tap_external_temporal_dynamics_advantage_without_spatial_claim"
        and _int(tap_transition_slice.get("series_count")) >= 1000
        and _int(tap_transition_slice.get("holdout_count")) >= 1000
        and _float(tap_transition_slice.get("best_transition_mae"))
        < _float(tap_transition_slice.get("best_traditional_static_mae"))
        and _float(tap_transition_slice.get("best_transition_mae"))
        < _float(tap_transition_slice.get("best_non_spatial_dynamic_mae"))
        and _float(tap_transition_slice.get("paired_win_rate_vs_best_non_spatial_dynamic"))
        > 0.5
        and tap_transition_slice.get("temporal_order_negative_control_passed") is True
        and tap_transition_slice.get("future_label_leakage_guard_passed") is True
        and tap_transition_slice.get("spatial_negative_control_passed") is False
    )


def _observed_state_prediction_superiority(openaq_slice: dict[str, Any]) -> bool:
    sign_tests = openaq_slice.get("overall_sign_tests") or {}
    static_mean_p = _float(
        (sign_tests.get("static_train_mean") or {}).get("one_sided_p_value"),
        default=1.0,
    )
    last_obs_p = _float(
        (sign_tests.get("static_last_train_observation") or {}).get("one_sided_p_value"),
        default=1.0,
    )
    return (
        openaq_slice.get("source_artifact_exists") is True
        and openaq_slice.get("claim_level") == "bounded_support"
        and _int(openaq_slice.get("observation_count")) >= 100
        and _int(openaq_slice.get("holdout_count")) >= 30
        and _float(openaq_slice.get("overall_holdout_win_rate")) > 0.5
        and static_mean_p < 0.05
        and last_obs_p < 0.05
        and openaq_slice.get("temporal_order_negative_control_passed") is True
    )


def _claim_guard(rows: list[dict[str, str]]) -> dict[str, Any]:
    blocked_statuses = {"synthetic", "semi_synthetic", "fitted_proxy", "smoke_only"}
    blocked_dataset_ids = [
        row.get("dataset_id", "")
        for row in rows
        if row.get("synthetic_status") in blocked_statuses
        or row.get("quality_status") == "smoke_only"
    ]
    return {
        "synthetic_or_smoke_blocked_from_empirical_policy_claim": True,
        "blocked_dataset_ids": sorted(dataset_id for dataset_id in blocked_dataset_ids if dataset_id),
        "rule": (
            "synthetic, semi_synthetic, fitted_proxy and smoke-only assets may support "
            "development or exploratory scaffolds, but cannot support observed policy "
            "outcome superiority claims"
        ),
    }


def _remaining_gates(
    claim_guard: dict[str, Any],
    *,
    tap_external_temporal_transition_ready: bool = False,
    causal_policy_diagnostic_ready: bool = False,
    external_observed_holdout_ready: bool = False,
    scene_aligned_station_calibrated_air_quality_holdout_ready: bool = False,
) -> list[str]:
    gates = [
        "observed_policy_outcome_required",
        "scene_aligned_station_calibrated_air_quality_holdout_required",
        "causal_policy_effect_validation_required",
        "external_observed_holdout_required",
    ]
    if not tap_external_temporal_transition_ready:
        gates.insert(1, "tap_or_authoritative_air_quality_required")
    if causal_policy_diagnostic_ready:
        gates = [
            gate
            for gate in gates
            if gate != "causal_policy_effect_validation_required"
        ]
    if external_observed_holdout_ready:
        gates = [
            gate
            for gate in gates
            if gate != "external_observed_holdout_required"
        ]
    if scene_aligned_station_calibrated_air_quality_holdout_ready:
        gates = [
            gate
            for gate in gates
            if gate != "scene_aligned_station_calibrated_air_quality_holdout_required"
        ]
    if claim_guard.get("blocked_dataset_ids"):
        gates.append("synthetic_proxy_boundary_must_remain_visible")
    return gates


def _pollutant_result(benchmark: dict[str, Any], pollutant: str) -> dict[str, Any]:
    for result in benchmark.get("per_pollutant_results") or []:
        if result.get("pollutant") == pollutant:
            return result
    return {}


def _read_manifest_rows(path: str | Path) -> list[dict[str, str]]:
    return _read_csv_rows(path)


def _read_csv_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _int(value: Any, default: int = 0) -> int:
    if value in {None, ""}:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    if value in {None, ""}:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
