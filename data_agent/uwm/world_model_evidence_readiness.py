"""Claim-safe UWM world-model evidence readiness summaries."""

from __future__ import annotations

from typing import Any


UWM_WORLD_MODEL_EVIDENCE_READINESS_SCHEMA = "uwm.world_model_evidence_readiness.v1"


def build_world_model_evidence_readiness(
    data_foundation_evidence_gate: dict[str, Any],
) -> dict[str, Any]:
    """Build a world-model claim ladder from the data-foundation evidence gate."""

    evidence_slices = data_foundation_evidence_gate.get("evidence_slices") or {}
    openaq = evidence_slices.get("openaq_observed_temporal_state") or {}
    tap = evidence_slices.get("tap_external_temporal_transition") or {}
    rollout = evidence_slices.get("learned_world_model_rollout") or {}
    intervention = evidence_slices.get("livability_intervention_package") or {}
    admin_graph = evidence_slices.get("admin_spatial_adjacency_graph") or {}
    local_foundation = evidence_slices.get("local_planning_data_foundation") or {}
    causal_policy = evidence_slices.get("causal_policy_effect_validation") or {}
    external_observed = evidence_slices.get("external_observed_holdout_suite") or {}
    station_aligned_air = evidence_slices.get("station_aligned_air_quality_holdout") or {}
    data_calibrated_mechanism = evidence_slices.get("data_calibrated_mechanism_table") or {}
    data_calibrated_planner_replay = (
        evidence_slices.get("data_calibrated_planner_replay") or {}
    )
    scene_aligned_gridded_air = (
        evidence_slices.get("scene_aligned_gridded_air_quality_holdout") or {}
    )
    multisource_livability_scene = (
        evidence_slices.get("multisource_livability_scene") or {}
    )
    osm_admin_mobility_crosswalk = (
        evidence_slices.get("osm_admin_mobility_crosswalk") or {}
    )
    building_floor_morphology = (
        evidence_slices.get("building_floor_morphology") or {}
    )
    livability_endpoint_suite = (
        evidence_slices.get("livability_endpoint_suite") or {}
    )
    endpoint_aligned_planner_evaluator = (
        evidence_slices.get("endpoint_aligned_planner_evaluator") or {}
    )
    spatial_spillover_planner_evaluator = (
        evidence_slices.get("spatial_spillover_planner_evaluator") or {}
    )
    livability_decision_package = (
        evidence_slices.get("livability_decision_package") or {}
    )
    livability_rl_training = evidence_slices.get("livability_rl_training") or {}
    livability_graph_drl_training = (
        evidence_slices.get("livability_graph_drl_training") or {}
    )

    claim_ladder = _claim_ladder(data_foundation_evidence_gate)
    forbidden_claims = _forbidden_claims(data_foundation_evidence_gate, tap)
    traditional_ready = (
        bool(data_foundation_evidence_gate.get("observed_state_prediction_superiority_claim"))
        and bool(data_foundation_evidence_gate.get("external_temporal_transition_superiority_claim"))
    )
    policy_ready = bool(data_foundation_evidence_gate.get("observed_policy_outcome_superiority_claim"))
    empirical_claim = bool(data_foundation_evidence_gate.get("empirical_superiority_claim"))
    bounded_final_system_ready = bool(
        data_foundation_evidence_gate.get("bounded_final_system_superiority_claim")
    )

    return {
        "schema": UWM_WORLD_MODEL_EVIDENCE_READINESS_SCHEMA,
        "overall_claim_ceiling": _overall_claim_ceiling(claim_ladder),
        "system_level_superiority_summary": _system_level_superiority_summary(
            traditional_ready=traditional_ready,
            bounded_final_system_ready=bounded_final_system_ready,
            policy_ready=policy_ready,
            empirical_claim=empirical_claim,
        ),
        "traditional_method_comparison_ready": traditional_ready,
        "bounded_final_system_superiority_ready": bounded_final_system_ready,
        "policy_outcome_superiority_ready": policy_ready,
        "empirical_superiority_claim": empirical_claim,
        "architecture_evidence": {
            "renderer": _renderer_evidence(
                local_foundation,
                admin_graph,
                multisource_livability_scene,
                osm_admin_mobility_crosswalk,
                building_floor_morphology,
            ),
            "simulator": _simulator_evidence(
                openaq,
                tap,
                rollout,
                data_calibrated_mechanism,
            ),
            "external_observed_holdout": _external_observed_holdout_evidence(
                external_observed
            ),
            "station_aligned_air_quality": _station_aligned_air_quality_evidence(
                station_aligned_air
            ),
            "scene_aligned_gridded_air_quality": _scene_aligned_gridded_air_quality_evidence(
                scene_aligned_gridded_air
            ),
            "planner": _planner_evidence(
                rollout,
                intervention,
                data_calibrated_planner_replay,
                endpoint_aligned_planner_evaluator,
                spatial_spillover_planner_evaluator,
            ),
            "final_livability_endpoint_evaluator": _final_livability_endpoint_evaluator_evidence(
                livability_endpoint_suite
            ),
            "final_livability_decision_package": _final_livability_decision_package_evidence(
                livability_decision_package
            ),
            "rl_training": _livability_rl_training_evidence(
                livability_rl_training
            ),
            "graph_drl_training": _livability_graph_drl_training_evidence(
                livability_graph_drl_training
            ),
            "causal_policy_evidence": _causal_policy_evidence(causal_policy),
            "policy_outcome_evaluator": _policy_outcome_evaluator_evidence(
                data_foundation_evidence_gate,
                causal_policy,
            ),
        },
        "claim_ladder": claim_ladder,
        "forbidden_claims": forbidden_claims,
        "remaining_gates": list(data_foundation_evidence_gate.get("remaining_gates") or []),
        "next_actions": _next_actions(data_foundation_evidence_gate),
    }


def _claim_ladder(gate: dict[str, Any]) -> list[dict[str, Any]]:
    ladder = []
    for claim in gate.get("supported_claims") or []:
        claim_level = str(claim.get("claim_level") or "not_for_claim")
        policy_outcome_claim = bool(claim.get("policy_outcome_claim"))
        ladder.append(
            {
                "claim": claim.get("claim"),
                "scope": claim.get("scope"),
                "claim_level": claim_level,
                "allowed_in_report": claim_level == "bounded_support" and not policy_outcome_claim,
                "policy_outcome_claim": policy_outcome_claim,
                "spatial_attribution_claim": bool(claim.get("spatial_attribution_claim")),
            }
        )
    return ladder


def _overall_claim_ceiling(claim_ladder: list[dict[str, Any]]) -> str:
    if any(claim.get("claim_level") == "bounded_support" for claim in claim_ladder):
        return "bounded_support"
    if any(claim.get("claim_level") == "exploratory_only" for claim in claim_ladder):
        return "exploratory_only"
    if any(claim.get("claim_level") == "fragile" for claim in claim_ladder):
        return "fragile"
    return "not_for_claim"


def _system_level_superiority_summary(
    *,
    traditional_ready: bool,
    bounded_final_system_ready: bool,
    policy_ready: bool,
    empirical_claim: bool,
) -> str:
    if traditional_ready and policy_ready and empirical_claim:
        return "observed_policy_outcome_superiority_ready"
    if bounded_final_system_ready:
        return "bounded_final_endpoint_and_endpoint_aligned_planner_advantage_without_policy_outcome_superiority"
    if traditional_ready:
        return "bounded_state_prediction_and_transition_advantage_without_policy_outcome_superiority"
    return "no_system_level_superiority_claim_supported"


def _renderer_evidence(
    local_foundation: dict[str, Any],
    admin_graph: dict[str, Any],
    multisource_livability_scene: dict[str, Any],
    osm_admin_mobility_crosswalk: dict[str, Any],
    building_floor_morphology: dict[str, Any],
) -> dict[str, Any]:
    local_ready = bool(local_foundation.get("source_artifact_exists"))
    graph_ready = bool(admin_graph.get("source_artifact_exists")) and _safe_int(
        admin_graph.get("node_count")
    ) > 0
    multisource_ready = (
        bool(multisource_livability_scene.get("source_artifact_exists"))
        and bool(
            multisource_livability_scene.get("multisource_livability_scene_ready")
        )
        and str(multisource_livability_scene.get("claim_level")) == "bounded_support"
        and _safe_float(
            multisource_livability_scene.get("air_quality_multisource_mae")
        )
        < _safe_float(
            multisource_livability_scene.get("air_quality_best_single_source_mae"),
            default=float("inf"),
        )
    )
    osm_mobility_ready = (
        bool(osm_admin_mobility_crosswalk.get("source_artifact_exists"))
        and bool(
            osm_admin_mobility_crosswalk.get("osm_admin_mobility_crosswalk_ready")
        )
        and str(osm_admin_mobility_crosswalk.get("claim_level")) == "bounded_support"
        and _safe_float(
            osm_admin_mobility_crosswalk.get("service_accessibility_mobility_mae")
        )
        < _safe_float(
            osm_admin_mobility_crosswalk.get(
                "service_accessibility_best_static_mae"
            ),
            default=float("inf"),
        )
    )
    osm_crosswalk_projected_in_scene = bool(
        multisource_livability_scene.get("osm_admin_mobility_crosswalk_projected")
    )
    building_floor_ready = (
        bool(building_floor_morphology.get("source_artifact_exists"))
        and bool(
            building_floor_morphology.get("building_floor_morphology_ready")
        )
        and str(building_floor_morphology.get("claim_level")) == "bounded_support"
        and _safe_int(building_floor_morphology.get("assigned_building_count")) > 0
        and _safe_int(building_floor_morphology.get("ready_endpoint_count")) >= 2
        and _safe_int(building_floor_morphology.get("ready_endpoint_count"))
        == _safe_int(building_floor_morphology.get("endpoint_count"))
        and bool(building_floor_morphology.get("true_3d_claim")) is False
    )
    claim_levels = [
        str(local_foundation.get("claim_level") or "not_for_claim"),
        str(admin_graph.get("claim_level") or "not_for_claim"),
    ]
    if multisource_livability_scene.get("source_artifact_exists"):
        claim_levels.append(
            str(multisource_livability_scene.get("claim_level") or "not_for_claim")
        )
    if osm_admin_mobility_crosswalk.get("source_artifact_exists"):
        claim_levels.append(
            str(osm_admin_mobility_crosswalk.get("claim_level") or "not_for_claim")
        )
    if building_floor_morphology.get("source_artifact_exists"):
        claim_levels.append(
            str(building_floor_morphology.get("claim_level") or "not_for_claim")
        )
    return {
        "ready": local_ready and graph_ready,
        "evidence": [
            "prepared_local_planning_data_foundation" if local_ready else "local_foundation_missing",
            "admin_spatial_adjacency_graph" if graph_ready else "admin_spatial_graph_missing",
            "multisource_livability_scene" if multisource_ready else "multisource_livability_scene_missing",
            "osm_admin_mobility_crosswalk" if osm_mobility_ready else "osm_admin_mobility_crosswalk_missing",
            "building_floor_25d_morphology" if building_floor_ready else "building_floor_25d_morphology_missing",
        ],
        "multisource_livability_scene_ready": multisource_ready,
        "multisource_admin_unit_count": _safe_int(
            multisource_livability_scene.get("admin_unit_count")
        ),
        "multisource_air_quality_mae": _safe_float(
            multisource_livability_scene.get("air_quality_multisource_mae")
        ),
        "multisource_air_quality_best_single_source_mae": _safe_float(
            multisource_livability_scene.get("air_quality_best_single_source_mae")
        ),
        "multisource_air_quality_mae_reduction": _safe_float(
            multisource_livability_scene.get(
                "air_quality_mae_reduction_vs_best_single_source"
            )
        ),
        "osm_admin_mobility_crosswalk_ready": osm_mobility_ready,
        "osm_admin_mobility_crosswalk_projected_in_scene": (
            osm_crosswalk_projected_in_scene
        ),
        "osm_crosswalk_matched_admin_units_in_scene": _safe_int(
            multisource_livability_scene.get("osm_crosswalk_matched_admin_units")
        ),
        "osm_assigned_road_segment_count_in_scene": _safe_int(
            multisource_livability_scene.get(
                "osm_assigned_road_segment_count_in_scene"
            )
        ),
        "osm_assigned_road_segment_count": _safe_int(
            osm_admin_mobility_crosswalk.get("assigned_road_segment_count")
        ),
        "osm_service_accessibility_mae": _safe_float(
            osm_admin_mobility_crosswalk.get("service_accessibility_mobility_mae")
        ),
        "osm_service_accessibility_best_static_mae": _safe_float(
            osm_admin_mobility_crosswalk.get("service_accessibility_best_static_mae")
        ),
        "osm_service_accessibility_mae_reduction": _safe_float(
            osm_admin_mobility_crosswalk.get("service_accessibility_mae_reduction")
        ),
        "building_floor_morphology_ready": building_floor_ready,
        "building_floor_admin_unit_count": _safe_int(
            building_floor_morphology.get("admin_unit_count")
        ),
        "building_floor_source_building_record_count": _safe_int(
            building_floor_morphology.get("source_building_record_count")
        ),
        "building_floor_assigned_building_count": _safe_int(
            building_floor_morphology.get("assigned_building_count")
        ),
        "building_floor_total_floor_count": _safe_int(
            building_floor_morphology.get("total_floor_count")
        ),
        "building_floor_max_floor": _safe_int(
            building_floor_morphology.get("max_floor")
        ),
        "building_floor_ready_endpoint_count": _safe_int(
            building_floor_morphology.get("ready_endpoint_count")
        ),
        "building_floor_endpoint_count": _safe_int(
            building_floor_morphology.get("endpoint_count")
        ),
        "building_floor_true_3d_claim": bool(
            building_floor_morphology.get("true_3d_claim")
        ),
        "claim_level": _min_claim_level(claim_levels),
    }


def _simulator_evidence(
    openaq: dict[str, Any],
    tap: dict[str, Any],
    rollout: dict[str, Any],
    data_calibrated_mechanism: dict[str, Any],
) -> dict[str, Any]:
    observed_temporal_ready = (
        bool(openaq.get("source_artifact_exists"))
        and str(openaq.get("claim_level")) == "bounded_support"
        and _safe_float(openaq.get("overall_holdout_win_rate")) > 0.5
        and bool(openaq.get("temporal_order_negative_control_passed"))
    )
    external_transition_ready = (
        bool(tap.get("source_artifact_exists"))
        and str(tap.get("claim_level")) == "bounded_support"
        and _safe_float(tap.get("best_transition_mae"))
        < _safe_float(tap.get("best_non_spatial_dynamic_mae"), default=float("inf"))
        and _safe_float(tap.get("paired_win_rate_vs_best_non_spatial_dynamic")) > 0.5
        and bool(tap.get("temporal_order_negative_control_passed"))
        and bool(tap.get("future_label_leakage_guard_passed"))
        and tap.get("spatial_negative_control_passed") is False
    )
    learned_rollout_ready = (
        bool(rollout.get("source_artifact_exists"))
        and str(rollout.get("claim_level")) == "bounded_support"
        and _safe_float(rollout.get("holdout_reward_mae"), default=float("inf"))
        < _safe_float(rollout.get("train_mean_reward_mae"), default=0.0)
    )
    mechanism_ready = (
        bool(data_calibrated_mechanism.get("source_artifact_exists"))
        and bool(data_calibrated_mechanism.get("data_calibrated_mechanism_ready"))
        and str(data_calibrated_mechanism.get("claim_level")) == "bounded_support"
        and not bool(
            data_calibrated_mechanism.get("observed_policy_outcome_superiority_claim")
        )
    )
    return {
        "ready": observed_temporal_ready and external_transition_ready and learned_rollout_ready,
        "observed_temporal_state_ready": observed_temporal_ready,
        "external_temporal_transition_ready": external_transition_ready,
        "learned_rollout_ready": learned_rollout_ready,
        "data_calibrated_mechanism_ready": mechanism_ready,
        "hardcoded_mechanism_replacement_ready": bool(
            data_calibrated_mechanism.get("hardcoded_mechanism_replacement_ready")
        )
        and mechanism_ready,
        "spatial_attribution_ready": False,
        "claim_level": "bounded_support"
        if observed_temporal_ready and external_transition_ready and learned_rollout_ready
        else "not_for_claim",
    }


def _external_observed_holdout_evidence(external_observed: dict[str, Any]) -> dict[str, Any]:
    ready = (
        bool(external_observed.get("source_artifact_exists"))
        and bool(external_observed.get("external_observed_holdout_ready"))
        and str(external_observed.get("claim_level")) == "bounded_support"
        and not bool(external_observed.get("observed_policy_outcome_superiority_claim"))
        and not bool(
            external_observed.get(
                "scene_aligned_station_calibrated_air_quality_holdout_ready"
            )
        )
    )
    return {
        "ready": ready,
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "openaq_external_holdout_ready": bool(
            external_observed.get("openaq_external_holdout_ready")
        ),
        "tap_external_holdout_ready": bool(
            external_observed.get("tap_external_holdout_ready")
        ),
        "scene_aligned_station_calibrated_air_quality_holdout_ready": bool(
            external_observed.get(
                "scene_aligned_station_calibrated_air_quality_holdout_ready"
            )
        ),
        "policy_outcome_claim": False,
    }


def _station_aligned_air_quality_evidence(station_aligned_air: dict[str, Any]) -> dict[str, Any]:
    historical_ready = (
        bool(station_aligned_air.get("source_artifact_exists"))
        and bool(station_aligned_air.get("historical_station_aligned_holdout_ready"))
        and str(station_aligned_air.get("claim_level")) == "bounded_support"
    )
    scene_ready = bool(
        station_aligned_air.get(
            "scene_aligned_station_calibrated_air_quality_holdout_ready"
        )
    )
    return {
        "ready": scene_ready,
        "historical_station_aligned_holdout_ready": historical_ready,
        "scene_aligned_station_calibrated_air_quality_holdout_ready": scene_ready,
        "claim_level": "bounded_support" if scene_ready else "not_for_claim",
        "historical_claim_level": "bounded_support" if historical_ready else "not_for_claim",
        "best_station_aligned_method": station_aligned_air.get(
            "best_station_aligned_method"
        ),
        "raw_tap_beats_static_station_baselines": bool(
            station_aligned_air.get("raw_tap_beats_static_station_baselines")
        ),
        "policy_outcome_claim": False,
    }


def _scene_aligned_gridded_air_quality_evidence(
    scene_aligned_gridded_air: dict[str, Any],
) -> dict[str, Any]:
    ready = (
        bool(scene_aligned_gridded_air.get("source_artifact_exists"))
        and bool(
            scene_aligned_gridded_air.get(
                "scene_aligned_gridded_air_quality_holdout_ready"
            )
        )
        and str(scene_aligned_gridded_air.get("claim_level")) == "bounded_support"
        and _safe_float(scene_aligned_gridded_air.get("best_uwm_mae"))
        < _safe_float(
            scene_aligned_gridded_air.get("best_static_baseline_mae"),
            default=float("inf"),
        )
        and bool(
            scene_aligned_gridded_air.get("spatial_shuffle_negative_control_passed")
        )
        and not bool(
            scene_aligned_gridded_air.get("observed_policy_outcome_superiority_claim")
        )
    )
    uncertainty_ready = (
        ready
        and bool(scene_aligned_gridded_air.get("uwm_uncertainty_calibration_ready"))
        and _safe_float(scene_aligned_gridded_air.get("uwm_interval_score"))
        < _safe_float(
            scene_aligned_gridded_air.get("static_interval_score"),
            default=float("inf"),
        )
        and _safe_float(scene_aligned_gridded_air.get("uwm_interval_coverage")) >= 0.9
    )
    return {
        "ready": ready,
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "best_method": scene_aligned_gridded_air.get("best_uwm_method"),
        "best_uwm_mae": _safe_float(scene_aligned_gridded_air.get("best_uwm_mae")),
        "best_static_baseline_mae": _safe_float(
            scene_aligned_gridded_air.get("best_static_baseline_mae")
        ),
        "best_uwm_mae_reduction": _safe_float(
            scene_aligned_gridded_air.get("best_uwm_mae_reduction")
        ),
        "spatial_shuffle_negative_control_passed": bool(
            scene_aligned_gridded_air.get("spatial_shuffle_negative_control_passed")
        ),
        "uncertainty_calibration_ready": uncertainty_ready,
        "uncertainty_confidence_level": _safe_float(
            scene_aligned_gridded_air.get("uncertainty_confidence_level")
        ),
        "uwm_interval_coverage": _safe_float(
            scene_aligned_gridded_air.get("uwm_interval_coverage")
        ),
        "static_interval_coverage": _safe_float(
            scene_aligned_gridded_air.get("static_interval_coverage")
        ),
        "uwm_interval_score": _safe_float(
            scene_aligned_gridded_air.get("uwm_interval_score")
        ),
        "static_interval_score": _safe_float(
            scene_aligned_gridded_air.get("static_interval_score")
        ),
        "uwm_interval_score_reduction": _safe_float(
            scene_aligned_gridded_air.get("uwm_interval_score_reduction")
        ),
        "station_calibrated_ready": bool(
            scene_aligned_gridded_air.get(
                "scene_aligned_station_calibrated_air_quality_holdout_ready"
            )
        ),
        "policy_outcome_claim": False,
    }


def _final_livability_endpoint_evaluator_evidence(
    livability_endpoint_suite: dict[str, Any],
) -> dict[str, Any]:
    ready = (
        bool(livability_endpoint_suite.get("source_artifact_exists"))
        and bool(livability_endpoint_suite.get("livability_endpoint_suite_ready"))
        and str(livability_endpoint_suite.get("claim_level")) == "bounded_support"
        and _safe_int(livability_endpoint_suite.get("endpoint_count")) >= 3
        and _safe_int(livability_endpoint_suite.get("ready_endpoint_count"))
        == _safe_int(livability_endpoint_suite.get("endpoint_count"))
        and _safe_float(
            livability_endpoint_suite.get(
                "min_relative_mae_reduction_vs_best_traditional"
            )
        )
        > 0.0
        and not bool(
            livability_endpoint_suite.get("observed_policy_outcome_superiority_claim")
        )
    )
    return {
        "ready": ready,
        "endpoint_count": _safe_int(livability_endpoint_suite.get("endpoint_count")),
        "ready_endpoint_count": _safe_int(
            livability_endpoint_suite.get("ready_endpoint_count")
        ),
        "endpoint_domains": list(livability_endpoint_suite.get("endpoint_domains") or []),
        "mean_relative_mae_reduction_vs_best_traditional": _safe_float(
            livability_endpoint_suite.get(
                "mean_relative_mae_reduction_vs_best_traditional"
            )
        ),
        "min_relative_mae_reduction_vs_best_traditional": _safe_float(
            livability_endpoint_suite.get(
                "min_relative_mae_reduction_vs_best_traditional"
            )
        ),
        "claim_level": str(livability_endpoint_suite.get("claim_level") or "not_for_claim"),
        "policy_outcome_claim": False,
    }


def _final_livability_decision_package_evidence(
    livability_decision_package: dict[str, Any],
) -> dict[str, Any]:
    ready = (
        bool(livability_decision_package.get("source_artifact_exists"))
        and bool(
            livability_decision_package.get("livability_decision_package_ready")
        )
        and str(livability_decision_package.get("claim_level"))
        == "bounded_support"
        and _safe_float(
            livability_decision_package.get(
                "endpoint_aligned_advantage_over_static"
            )
        )
        > 0.0
        and _safe_float(
            livability_decision_package.get(
                "risk_adjusted_advantage_over_static"
            )
        )
        > 0.0
        and _safe_float(
            livability_decision_package.get("neighbor_livability_delta_advantage")
        )
        > 0.0
        and not bool(
            livability_decision_package.get(
                "observed_policy_outcome_superiority_claim"
            )
        )
    )
    return {
        "ready": ready,
        "action_count": _safe_int(livability_decision_package.get("action_count")),
        "target_unit_count": _safe_int(
            livability_decision_package.get("target_unit_count")
        ),
        "target_units": list(livability_decision_package.get("target_units") or []),
        "endpoint_aligned_advantage_over_static": _safe_float(
            livability_decision_package.get("endpoint_aligned_advantage_over_static")
        ),
        "endpoint_aligned_advantage_ratio": _safe_float(
            livability_decision_package.get("endpoint_aligned_advantage_ratio")
        ),
        "single_action_transition_count": _safe_int(
            livability_decision_package.get("single_action_transition_count")
        ),
        "best_single_action_reward": _safe_float(
            livability_decision_package.get("best_single_action_reward")
        ),
        "advantage_vs_best_single_action": _safe_float(
            livability_decision_package.get("advantage_vs_best_single_action")
        ),
        "single_action_win_rate": _safe_float(
            livability_decision_package.get("single_action_win_rate")
        ),
        "best_sequence_percentile_vs_single_actions": _safe_float(
            livability_decision_package.get(
                "best_sequence_percentile_vs_single_actions"
            )
        ),
        "empirical_p_value_vs_single_action_baselines": _safe_float(
            livability_decision_package.get(
                "empirical_p_value_vs_single_action_baselines"
            )
        ),
        "endpoint_weight_sensitivity_profile_count": _safe_int(
            livability_decision_package.get(
                "endpoint_weight_sensitivity_profile_count"
            )
        ),
        "endpoint_weight_sensitivity_min_advantage": _safe_float(
            livability_decision_package.get(
                "endpoint_weight_sensitivity_min_advantage"
            )
        ),
        "risk_adjusted_advantage_over_static": _safe_float(
            livability_decision_package.get("risk_adjusted_advantage_over_static")
        ),
        "neighbor_livability_delta_advantage": _safe_float(
            livability_decision_package.get("neighbor_livability_delta_advantage")
        ),
        "spatial_spillover_kernel_ready": bool(
            livability_decision_package.get("spatial_spillover_kernel_ready")
        ),
        "spatial_spillover_kernel_directional_edge_count": _safe_int(
            livability_decision_package.get(
                "spatial_spillover_kernel_directional_edge_count"
            )
        ),
        "spatial_spillover_kernel_max_spillover_factor": _safe_float(
            livability_decision_package.get(
                "spatial_spillover_kernel_max_spillover_factor"
            )
        ),
        "rl_training_ready": bool(
            livability_decision_package.get("rl_training_ready")
        ),
        "rl_training_algorithm": livability_decision_package.get(
            "rl_training_algorithm"
        ),
        "rl_training_episode_count": _safe_int(
            livability_decision_package.get("rl_training_episode_count")
        ),
        "rl_training_advantage_over_traditional_static": _safe_float(
            livability_decision_package.get(
                "rl_training_advantage_over_traditional_static"
            )
        ),
        "graph_drl_training_ready": bool(
            livability_decision_package.get("graph_drl_training_ready")
        ),
        "graph_drl_algorithm": livability_decision_package.get(
            "graph_drl_algorithm"
        ),
        "graph_drl_is_deep_rl": bool(
            livability_decision_package.get("graph_drl_is_deep_rl")
        ),
        "graph_drl_uses_graph_message_passing": bool(
            livability_decision_package.get(
                "graph_drl_uses_graph_message_passing"
            )
        ),
        "graph_policy_or_value_network_trained": bool(
            livability_decision_package.get(
                "graph_policy_or_value_network_trained"
            )
        ),
        "graph_drl_training_sample_count": _safe_int(
            livability_decision_package.get("graph_drl_training_sample_count")
        ),
        "graph_drl_q_return_mae": _safe_float(
            livability_decision_package.get("graph_drl_q_return_mae")
        ),
        "graph_drl_train_mean_return_mae": _safe_float(
            livability_decision_package.get("graph_drl_train_mean_return_mae")
        ),
        "graph_drl_advantage_over_traditional_static": _safe_float(
            livability_decision_package.get(
                "graph_drl_advantage_over_traditional_static"
            )
        ),
        "planner_benefited_unit_count": _safe_int(
            livability_decision_package.get("planner_benefited_unit_count")
        ),
        "static_benefited_unit_count": _safe_int(
            livability_decision_package.get("static_benefited_unit_count")
        ),
        "planner_positive_equity_delta_sum": _safe_float(
            livability_decision_package.get("planner_positive_equity_delta_sum")
        ),
        "static_positive_equity_delta_sum": _safe_float(
            livability_decision_package.get("static_positive_equity_delta_sum")
        ),
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "policy_outcome_claim": False,
    }


def _livability_rl_training_evidence(
    livability_rl_training: dict[str, Any],
) -> dict[str, Any]:
    ready = (
        bool(livability_rl_training.get("source_artifact_exists"))
        and bool(livability_rl_training.get("livability_rl_training_ready"))
        and str(livability_rl_training.get("claim_level")) == "bounded_support"
        and _safe_float(
            livability_rl_training.get("advantage_over_traditional_static")
        )
        > 0.0
        and not bool(
            livability_rl_training.get("observed_policy_outcome_superiority_claim")
        )
    )
    return {
        "ready": ready,
        "algorithm": livability_rl_training.get("algorithm"),
        "uses_simulator_model_for_planning": bool(
            livability_rl_training.get("uses_simulator_model_for_planning")
        ),
        "episode_count": _safe_int(livability_rl_training.get("episode_count")),
        "q_state_count": _safe_int(livability_rl_training.get("q_state_count")),
        "learned_replay_transition_count": _safe_int(
            livability_rl_training.get("learned_replay_transition_count")
        ),
        "real_data_graph_node_count": _safe_int(
            livability_rl_training.get("real_data_graph_node_count")
        ),
        "real_data_available_action_count": _safe_int(
            livability_rl_training.get("real_data_available_action_count")
        ),
        "spatial_spillover_directional_edge_count": _safe_int(
            livability_rl_training.get("spatial_spillover_directional_edge_count")
        ),
        "learned_policy_cumulative_reward": _safe_float(
            livability_rl_training.get("learned_policy_cumulative_reward")
        ),
        "traditional_static_cumulative_reward": _safe_float(
            livability_rl_training.get("traditional_static_cumulative_reward")
        ),
        "advantage_over_traditional_static": _safe_float(
            livability_rl_training.get("advantage_over_traditional_static")
        ),
        "policy_or_value_network_trained": bool(
            livability_rl_training.get("policy_or_value_network_trained")
        ),
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "policy_outcome_claim": False,
    }


def _livability_graph_drl_training_evidence(
    livability_graph_drl_training: dict[str, Any],
) -> dict[str, Any]:
    ready = (
        bool(livability_graph_drl_training.get("source_artifact_exists"))
        and bool(
            livability_graph_drl_training.get(
                "livability_graph_drl_training_ready"
            )
        )
        and str(livability_graph_drl_training.get("claim_level"))
        == "bounded_support"
        and bool(livability_graph_drl_training.get("is_deep_rl"))
        and bool(livability_graph_drl_training.get("uses_graph_message_passing"))
        and bool(
            livability_graph_drl_training.get(
                "policy_or_value_network_trained"
            )
        )
        and _safe_float(
            livability_graph_drl_training.get(
                "advantage_over_traditional_static"
            )
        )
        > 0.0
        and not bool(
            livability_graph_drl_training.get(
                "observed_policy_outcome_superiority_claim"
            )
        )
    )
    return {
        "ready": ready,
        "algorithm": livability_graph_drl_training.get("algorithm"),
        "is_deep_rl": bool(livability_graph_drl_training.get("is_deep_rl")),
        "is_model_based": bool(
            livability_graph_drl_training.get("is_model_based")
        ),
        "is_model_free": bool(
            livability_graph_drl_training.get("is_model_free")
        ),
        "uses_graph_message_passing": bool(
            livability_graph_drl_training.get("uses_graph_message_passing")
        ),
        "policy_or_value_network_trained": bool(
            livability_graph_drl_training.get(
                "policy_or_value_network_trained"
            )
        ),
        "training_sample_count": _safe_int(
            livability_graph_drl_training.get("training_sample_count")
        ),
        "holdout_count": _safe_int(
            livability_graph_drl_training.get("holdout_count")
        ),
        "real_data_graph_node_count": _safe_int(
            livability_graph_drl_training.get("real_data_graph_node_count")
        ),
        "real_data_graph_edge_count": _safe_int(
            livability_graph_drl_training.get("real_data_graph_edge_count")
        ),
        "real_data_available_action_count": _safe_int(
            livability_graph_drl_training.get(
                "real_data_available_action_count"
            )
        ),
        "spatial_spillover_directional_edge_count": _safe_int(
            livability_graph_drl_training.get(
                "spatial_spillover_directional_edge_count"
            )
        ),
        "q_return_mae": _safe_float(
            livability_graph_drl_training.get("q_return_mae")
        ),
        "train_mean_return_mae": _safe_float(
            livability_graph_drl_training.get("train_mean_return_mae")
        ),
        "graph_dqn_policy_cumulative_reward": _safe_float(
            livability_graph_drl_training.get(
                "graph_dqn_policy_cumulative_reward"
            )
        ),
        "traditional_static_cumulative_reward": _safe_float(
            livability_graph_drl_training.get(
                "traditional_static_cumulative_reward"
            )
        ),
        "advantage_over_traditional_static": _safe_float(
            livability_graph_drl_training.get(
                "advantage_over_traditional_static"
            )
        ),
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "policy_outcome_claim": False,
    }


def _planner_evidence(
    rollout: dict[str, Any],
    intervention: dict[str, Any],
    data_calibrated_planner_replay: dict[str, Any],
    endpoint_aligned_planner_evaluator: dict[str, Any],
    spatial_spillover_planner_evaluator: dict[str, Any],
) -> dict[str, Any]:
    rollout_advantage_ready = (
        bool(rollout.get("source_artifact_exists"))
        and _safe_float(rollout.get("imagined_advantage_over_static")) > 0.0
        and _safe_float(rollout.get("imagined_advantage_over_one_step")) > 0.0
    )
    intervention_ready = (
        bool(intervention.get("source_artifact_exists"))
        and str(intervention.get("claim_level")) == "exploratory_only"
        and bool(intervention.get("predicted_delta"))
    )
    calibrated_replay_ready = (
        bool(data_calibrated_planner_replay.get("source_artifact_exists"))
        and bool(
            data_calibrated_planner_replay.get(
                "data_calibrated_planner_replay_ready"
            )
        )
        and str(data_calibrated_planner_replay.get("claim_level")) == "bounded_support"
        and _safe_float(
            data_calibrated_planner_replay.get("advantage_over_static_single_step")
        )
        > 0.0
    )
    risk_calibrated_replay_ready = (
        calibrated_replay_ready
        and bool(
            data_calibrated_planner_replay.get(
                "risk_calibrated_planner_replay_ready"
            )
        )
        and bool(
            data_calibrated_planner_replay.get(
                "air_quality_uncertainty_calibration_ready"
            )
        )
        and _safe_float(
            data_calibrated_planner_replay.get(
                "risk_adjusted_advantage_over_static_single_step"
            )
        )
        > 0.0
    )
    endpoint_aligned_ready = (
        bool(endpoint_aligned_planner_evaluator.get("source_artifact_exists"))
        and bool(
            endpoint_aligned_planner_evaluator.get(
                "endpoint_aligned_planner_evaluator_ready"
            )
        )
        and str(endpoint_aligned_planner_evaluator.get("claim_level"))
        == "bounded_support"
        and _safe_float(
            endpoint_aligned_planner_evaluator.get(
                "endpoint_aligned_advantage_over_static"
            )
        )
        > 0.0
    )
    spatial_spillover_ready = (
        bool(spatial_spillover_planner_evaluator.get("source_artifact_exists"))
        and bool(
            spatial_spillover_planner_evaluator.get(
                "spatial_spillover_planner_evaluator_ready"
            )
        )
        and str(spatial_spillover_planner_evaluator.get("claim_level"))
        == "bounded_support"
        and _safe_float(
            spatial_spillover_planner_evaluator.get(
                "neighbor_livability_delta_advantage"
            )
        )
        > 0.0
    )
    return {
        "ready": rollout_advantage_ready and intervention_ready,
        "learned_rollout_planner_ready": rollout_advantage_ready,
        "livability_intervention_package_ready": intervention_ready,
        "data_calibrated_planner_replay_ready": calibrated_replay_ready,
        "risk_calibrated_planner_replay_ready": risk_calibrated_replay_ready,
        "endpoint_aligned_planner_evaluator_ready": endpoint_aligned_ready,
        "endpoint_aligned_advantage_over_static": _safe_float(
            endpoint_aligned_planner_evaluator.get(
                "endpoint_aligned_advantage_over_static"
            )
        ),
        "endpoint_aligned_advantage_ratio": _safe_float(
            endpoint_aligned_planner_evaluator.get(
                "endpoint_aligned_advantage_ratio"
            )
        ),
        "endpoint_aligned_planner_score": _safe_float(
            endpoint_aligned_planner_evaluator.get("planner_endpoint_aligned_score")
        ),
        "endpoint_aligned_static_score": _safe_float(
            endpoint_aligned_planner_evaluator.get("static_endpoint_aligned_score")
        ),
        "spatial_spillover_planner_evaluator_ready": spatial_spillover_ready,
        "planner_neighbor_benefited_unit_count": _safe_int(
            spatial_spillover_planner_evaluator.get(
                "planner_neighbor_benefited_unit_count"
            )
        ),
        "static_neighbor_benefited_unit_count": _safe_int(
            spatial_spillover_planner_evaluator.get(
                "static_neighbor_benefited_unit_count"
            )
        ),
        "neighbor_livability_delta_advantage": _safe_float(
            spatial_spillover_planner_evaluator.get(
                "neighbor_livability_delta_advantage"
            )
        ),
        "neighbor_livability_delta_advantage_ratio": _safe_float(
            spatial_spillover_planner_evaluator.get(
                "neighbor_livability_delta_advantage_ratio"
            )
        ),
        "data_calibrated_planner_advantage_over_static": _safe_float(
            data_calibrated_planner_replay.get("advantage_over_static_single_step")
        ),
        "risk_calibrated_planner_advantage_over_static": _safe_float(
            data_calibrated_planner_replay.get(
                "risk_adjusted_advantage_over_static_single_step"
            )
        ),
        "air_quality_uncertainty_calibration_ready": bool(
            data_calibrated_planner_replay.get(
                "air_quality_uncertainty_calibration_ready"
            )
        ),
        "air_quality_uncertainty_confidence_level": _safe_float(
            data_calibrated_planner_replay.get(
                "air_quality_uncertainty_confidence_level"
            )
        ),
        "claim_level": "exploratory_only" if intervention_ready else "not_for_claim",
        "policy_outcome_claim": False,
    }


def _causal_policy_evidence(causal_policy: dict[str, Any]) -> dict[str, Any]:
    ready = (
        bool(causal_policy.get("source_artifact_exists"))
        and bool(causal_policy.get("algorithmic_causal_diagnostic_ready"))
        and str(causal_policy.get("claim_level")) == "bounded_support"
        and not bool(causal_policy.get("observed_policy_outcome_superiority_claim"))
    )
    return {
        "ready": ready,
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "arcgis_native_parity_ready": bool(causal_policy.get("arcgis_native_parity_ready")),
        "scca_credibility_ready": bool(causal_policy.get("scca_credibility_ready")),
        "chongqing_causal_case_anchor_ready": bool(
            causal_policy.get("chongqing_causal_case_anchor_ready")
        ),
        "observed_local_policy_outcome_ready": bool(
            causal_policy.get("observed_local_policy_outcome_ready")
        ),
        "policy_outcome_claim": False,
    }


def _policy_outcome_evaluator_evidence(
    gate: dict[str, Any],
    causal_policy: dict[str, Any],
) -> dict[str, Any]:
    remaining_gates = list(gate.get("remaining_gates") or [])
    ready = bool(gate.get("observed_policy_outcome_superiority_claim"))
    causal_policy_diagnostic_ready = (
        bool(causal_policy.get("source_artifact_exists"))
        and bool(causal_policy.get("algorithmic_causal_diagnostic_ready"))
        and str(causal_policy.get("claim_level")) == "bounded_support"
    )
    return {
        "ready": ready,
        "claim_level": "bounded_support" if ready else "not_for_claim",
        "causal_policy_diagnostic_ready": causal_policy_diagnostic_ready,
        "causal_policy_diagnostic_claim_level": (
            str(causal_policy.get("claim_level") or "not_for_claim")
            if causal_policy_diagnostic_ready
            else "not_for_claim"
        ),
        "observed_local_policy_outcome_ready": bool(
            causal_policy.get("observed_local_policy_outcome_ready")
        ),
        "remaining_gates": remaining_gates,
        "policy_outcome_claim": ready,
    }


def _forbidden_claims(gate: dict[str, Any], tap: dict[str, Any]) -> list[str]:
    claims = []
    if not gate.get("observed_policy_outcome_superiority_claim"):
        claims.append("observed_policy_outcome_superiority")
    if tap.get("spatial_negative_control_passed") is False:
        claims.append("spatial_attribution_for_tap_external_transition")
    if not gate.get("empirical_superiority_claim"):
        claims.append("overall_empirical_policy_superiority")
    return claims


def _next_actions(gate: dict[str, Any]) -> list[str]:
    actions = ["complete_world_model_evidence_readiness_section"]
    remaining_gates = set(gate.get("remaining_gates") or [])
    if "observed_policy_outcome_required" in remaining_gates:
        actions.append("collect_observed_policy_outcome_validation_data")
    if "scene_aligned_station_calibrated_air_quality_holdout_required" in remaining_gates:
        actions.append("build_scene_aligned_station_calibrated_air_quality_holdout")
    if "causal_policy_effect_validation_required" in remaining_gates:
        actions.append("design_causal_policy_effect_validation")
    if "external_observed_holdout_required" in remaining_gates:
        actions.append("build_external_observed_holdout_suite")
    return actions


def _min_claim_level(levels: list[str]) -> str:
    order = {
        "bounded_support": 3,
        "exploratory_only": 2,
        "fragile": 1,
        "not_for_claim": 0,
    }
    if not levels:
        return "not_for_claim"
    return min(levels, key=lambda level: order.get(level, 0))


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
