"""Technical audit ledger for the evidence-bounded S2 geospatial world model."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any, Mapping


SCHEMA = "uwm.livability_s2.technical_audit.v1"


def build_s2_technical_audit(
    *,
    bundle: Mapping[str, Any],
    rollout: Mapping[str, Any],
    business_assessment: Mapping[str, Any],
    execution_scope: Mapping[str, Any],
) -> dict[str, Any]:
    """Create a customer-auditable attribution ledger for one S2 run.

    The ledger deliberately separates the geospatial state/action kernel from the
    deterministic coverage proxy used by the business decision layer.  This
    prevents a spatial scenario signal from being presented as an observed policy
    effect or a population/service-capacity result.
    """

    intervention = _mapping(rollout.get("intervention"))
    transition = _mapping(intervention.get("action_validation")).get("transition") or {}
    t1 = _mapping(intervention.get("t1"))
    t2 = _mapping(intervention.get("t2"))
    messages = [row for row in t2.get("messages") or [] if isinstance(row, Mapping)]
    direct_delta = _mapping(t1.get("direct_state_delta"))
    manifest = _mapping(bundle.get("manifest"))

    relation_counts = _counts(messages, "relation_type")
    support_counts = _counts(messages, "support_level")
    priority_counts = _counts(messages, "review_priority")
    assessment_method = str(business_assessment.get("assessment_method") or "unavailable")

    return {
        "schema": SCHEMA,
        "audit_status": "passed_with_bounded_claims",
        "world_model_classification": {
            "geospatial_state_graph": True,
            "action_conditioned_counterfactual": True,
            "direct_transition_kernel": True,
            "relation_aware_spatial_propagation": True,
            "baseline_vs_intervention_worlds": True,
            "learned_transition_model": False,
            "empirical_intervention_effect": False,
            "formal_planning_approval": False,
        },
        "stage_attribution": [
            {
                "stage": "t0_current_state",
                "mechanism": "validated_snapshot_backed_geospatial_state_graph",
                "evidence": {
                    "bundle_id": manifest.get("bundle_id"),
                    "source_content_digest": manifest.get("source_content_digest"),
                    "snapshot_digest": rollout.get("t0_snapshot_digest"),
                    "parcel_count": len(_mapping(bundle.get("parcels")).get("features") or []),
                    "facility_count": len(_mapping(bundle.get("facilities")).get("features") or []),
                },
                "claim": "snapshot_state_and_geometry_context",
            },
            {
                "stage": "action_validation",
                "mechanism": "server_bound_action_plus_dictionary_and_transition_matrix_validation",
                "evidence": {
                    "transition_status": transition.get("status"),
                    "human_review_required": bool(transition.get("human_review_required")),
                    "approval_claim": False,
                },
                "claim": "action_admissibility_not_planning_approval",
            },
            {
                "stage": "t1_scenario_transition",
                "mechanism": "direct_target_parcel_state_mutation_and_relation_compatibility_recalculation",
                "evidence": {
                    "target_parcel_id": direct_delta.get("target_parcel_id"),
                    "from_land_use_class": direct_delta.get("from_land_use_class"),
                    "to_land_use_class": direct_delta.get("to_land_use_class"),
                    "changed_edge_count": len(direct_delta.get("changed_edge_ids") or []),
                    "state_semantics": direct_delta.get("state_semantics"),
                    "observed_outcome": bool(direct_delta.get("observed_outcome")),
                },
                "claim": "action_conditioned_scenario_state_not_observed_outcome",
            },
            {
                "stage": "t2_spatial_propagation",
                "mechanism": "relation_aware_local_and_cross_scale_message_passing",
                "evidence": {
                    "message_count": len(messages),
                    "relation_counts": relation_counts,
                    "support_level_counts": support_counts,
                    "review_priority_counts": priority_counts,
                    "kernel_distance_bands_m": [[0, 50], [50, 150], [150, 300]],
                },
                "claim": "bounded_spatial_context_and_review_signals",
            },
            {
                "stage": "business_decision_layer",
                "mechanism": assessment_method,
                "evidence": {
                    "demand_basis": business_assessment.get("demand_basis"),
                    "coverage_delta_percentage_points": business_assessment.get("coverage_delta_percentage_points"),
                    "business_rule_version": business_assessment.get("business_rule_version"),
                    "triggered_rules": list(business_assessment.get("triggered_rules") or []),
                },
                "claim": "equal_weight_parcel_coverage_proxy_not_population_or_network_accessibility",
            },
        ],
        "result_attribution": {
            "business_recommendation_inputs": [
                "deterministic_parcel_representative_point_coverage_proxy",
                "versioned_business_rules",
                "facility_inventory_completeness_gate",
                "service_radius_evidence_gate",
                "land_use_transition_review_status",
            ],
            "world_model_outputs_used_as_decision_context": [
                "t1_action_conditioned_state_delta",
                "t2_relation_aware_spatial_messages",
                "review_required_and_unresolved_relation_signals",
            ],
            "world_model_outputs_not_converted_to_policy_effect": [
                "population_migration",
                "facility_capacity",
                "traffic_and_walkability",
                "livability_score",
                "approval_probability",
                "validated_policy_effect",
            ],
            "coverage_proxy_is_not_t2_message_count": True,
        },
        "reproducibility": {
            "bundle_id": manifest.get("bundle_id"),
            "snapshot_digest": rollout.get("t0_snapshot_digest"),
            "rollout_digest": rollout.get("rollout_digest"),
            "assessment_digest": business_assessment.get("assessment_digest"),
            "kernel_version": rollout.get("kernel_version"),
            "execution_scope": deepcopy(dict(execution_scope)),
            "snapshot_content_digests_verified_on_load": True,
            "run_record_digest_verified_when_persisted": True,
        },
        "evidence_gates": {
            "facility_inventory_complete": bool(manifest.get("facility_inventory_complete")),
            "population_coverage_claim": bool(business_assessment.get("population_coverage_claim")),
            "statutory_service_radius_claim": bool(business_assessment.get("statutory_service_radius_claim")),
            "approval_claim": False,
            "unavailable_effects": list(rollout.get("unavailable_effects") or []),
        },
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _counts(rows: list[Mapping[str, Any]], field: str) -> dict[str, int]:
    counts = Counter(str(row.get(field) or "unresolved") for row in rows)
    return {key: counts[key] for key in sorted(counts)}
