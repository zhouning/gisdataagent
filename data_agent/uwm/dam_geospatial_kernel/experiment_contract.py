"""Machine-readable experiment contract for DAM-GK claims."""

from __future__ import annotations

from typing import Any


DAM_GK_EXPERIMENT_SCHEMA = "gwm.dam_gk.experiment_contract.v1"


def build_dam_gk_experiment_contract() -> dict[str, Any]:
    return {
        "schema": DAM_GK_EXPERIMENT_SCHEMA,
        "research_model": "dynamic_action_conditioned_multiscale_geospatial_kernel",
        "falsifiable_hypotheses": [
            "action_conditioning_changes_effective_relations",
            "multi_relational_kernel_beats_single_relation_on_at_least_one_real_holdout",
            "dynamic_topology_beats_frozen_topology_when_relations_change",
            "fine_and_coarse_predictions_satisfy_declared_scale_tolerance",
            "geographic_negative_controls_degrade_claimed_mechanism_metrics",
            "future_state_writeback_improves_bounded_multistep_planning",
        ],
        "required_data_tracks": [
            "controlled_geographic_dynamics",
            "twm_cross_region_2017_2023",
            "uwm_chongqing_multirelational_graph",
            "external_observed_environmental_holdout",
            "prepared_action_conditioned_replay",
        ],
        "required_baselines": [
            "static_persistence",
            "historical_mean",
            "target_only_dynamics",
            "fixed_distance_decay",
            "fixed_boundary_adjacency",
            "static_graph_model",
            "action_conditioned_no_graph",
            "dam_gk_no_topology_rewrite",
            "dam_gk_no_lag_structure",
            "dam_gk_no_multiscale_consistency",
            "dam_gk_no_state_writeback",
        ],
        "required_negative_controls": [
            "action_assignment_shuffle",
            "relation_type_shuffle",
            "spatial_target_rewire",
            "temporal_order_shuffle",
            "coordinate_or_projection_control",
        ],
        "allowed_claims_before_observed_policy_data": [
            "algorithmic_mechanism_recovery",
            "bounded_observed_state_prediction",
            "geographic_negative_control_sensitivity",
            "bounded_future_state_planning_advantage",
        ],
        "blocked_claims": [
            "identified_policy_causal_effect",
            "universal_geographic_law",
            "general_purpose_foundation_gwm",
            "cross_city_policy_effect_generalization",
        ],
    }


def validate_dam_gk_experiment_contract(payload: dict[str, Any]) -> dict[str, Any]:
    errors = []
    if payload.get("schema") != DAM_GK_EXPERIMENT_SCHEMA:
        errors.append("schema_mismatch")
    for field in (
        "falsifiable_hypotheses",
        "required_data_tracks",
        "required_baselines",
        "required_negative_controls",
        "blocked_claims",
    ):
        if not payload.get(field):
            errors.append(f"{field}_required")
    if "identified_policy_causal_effect" not in (payload.get("blocked_claims") or []):
        errors.append("policy_causal_claim_must_be_blocked")
    return {"valid": not errors, "errors": errors}
