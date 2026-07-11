from data_agent.uwm.geospatial_kernel.counterfactual_rollout import run_counterfactual_rollout
from data_agent.uwm.geospatial_kernel.land_use_action import (
    bind_server_actor,
    build_change_land_use_action,
)
from data_agent.uwm.geospatial_kernel.state_graph import build_state_graph
from data_agent.uwm.geospatial_kernel.transition_matrix import build_transition_matrix


def _graph() -> dict:
    return build_state_graph(
        kernel_version="0.1.0",
        nodes=[
            {
                "node_id": "parcel-target",
                "node_type": "parcel",
                "state_time": "t0_current",
                "current_land_use_class": "residential",
                "planned_land_use_class": "public_service",
                "candidate_land_use_class": None,
                "source_land_use_code": "0701",
                "effective_land_use_class": "residential",
                "area_m2": 1000.0,
                "perimeter_m": 140.0,
                "evidence_refs": ["source:parcel-target"],
                "observability": "observed",
            },
            {
                "node_id": "parcel-adjacent",
                "node_type": "parcel",
                "state_time": "t0_current",
                "current_land_use_class": "agricultural",
                "planned_land_use_class": "agricultural",
                "candidate_land_use_class": None,
                "source_land_use_code": "0101",
                "effective_land_use_class": "agricultural",
                "area_m2": 800.0,
                "perimeter_m": 120.0,
                "evidence_refs": ["source:parcel-adjacent"],
                "observability": "observed",
            },
            {
                "node_id": "resource-unmapped",
                "node_type": "planning_resource",
                "state_time": "t0_current",
                "mapping_status": "unmapped",
                "evidence_refs": ["source:resource-unmapped"],
                "observability": "observed",
            },
            {
                "node_id": "village-1",
                "node_type": "village_context",
                "state_time": "t0_current",
                "evidence_refs": ["source:village-1"],
                "observability": "derived",
            },
            {
                "node_id": "admin-1",
                "node_type": "admin_context",
                "state_time": "t0_current",
                "evidence_refs": ["source:admin-1"],
                "observability": "derived",
            },
        ],
        edges=[
            {
                "edge_id": "edge-adjacent",
                "source_node_id": "parcel-target",
                "target_node_id": "parcel-adjacent",
                "relation_type": "parcel_adjacent_parcel",
                "shared_boundary_length_m": 35.0,
                "source_perimeter_m": 140.0,
                "target_perimeter_m": 120.0,
                "compatibility_status": "potential_conflict",
                "evidence_refs": ["geometry:shared-boundary"],
                "support_level": "deterministic_geometry",
            },
            {
                "edge_id": "edge-resource",
                "source_node_id": "parcel-target",
                "target_node_id": "resource-unmapped",
                "relation_type": "parcel_contains_resource",
                "intersection_ratio": 0.4,
                "compatibility_by_land_use": {
                    "residential": "compatible",
                    "public_service": "unresolved",
                    "commercial": "potential_conflict",
                },
                "active_compatibility_status": "compatible",
                "evidence_refs": ["geometry:intersection"],
                "support_level": "deterministic_geometry",
            },
            {
                "edge_id": "edge-village",
                "source_node_id": "parcel-target",
                "target_node_id": "village-1",
                "relation_type": "parcel_within_village",
                "evidence_refs": ["geometry:containment"],
                "support_level": "deterministic_geometry",
            },
            {
                "edge_id": "edge-admin",
                "source_node_id": "village-1",
                "target_node_id": "admin-1",
                "relation_type": "village_within_admin",
                "evidence_refs": ["authority:hierarchy"],
                "support_level": "authoritative_rule",
            },
        ],
    )


def _dictionary() -> dict:
    return {
        "schema": "uwm.land_use_dictionary.v1",
        "version": "dict-v1",
        "classes": ["residential", "public_service", "commercial", "agricultural"],
    }


def _matrix() -> dict:
    return build_transition_matrix(
        version="matrix-v1",
        dictionary_version="dict-v1",
        rules=[
            {
                "from_land_use_class": "residential",
                "to_land_use_class": "public_service",
                "status": "conditionally_allowed",
                "authority_refs": ["authority:rule-1"],
                "conditions": ["planning_review_required"],
            },
            {
                "from_land_use_class": "residential",
                "to_land_use_class": "commercial",
                "status": "allowed",
                "authority_refs": ["authority:rule-2"],
                "conditions": [],
            },
        ],
    )


def _action(graph: dict) -> dict:
    return bind_server_actor(
        build_change_land_use_action(
            parcel_id="parcel-target",
            from_land_use_class="residential",
            to_land_use_class="public_service",
            rationale="公共服务用途反事实",
            snapshot_digest=graph["snapshot_digest"],
            dictionary_version="dict-v1",
            transition_matrix_version="matrix-v1",
            requested_at="2026-07-11T08:00:00Z",
        ),
        actor_id="user-123",
    )


def test_counterfactual_rollout_shares_t0_and_produces_three_stage_trajectories():
    graph = _graph()
    result = run_counterfactual_rollout(
        graph=graph,
        intervention_action=_action(graph),
        land_use_dictionary=_dictionary(),
        transition_matrix=_matrix(),
        alternative_land_use_class=None,
    )

    assert result["baseline"]["t0_snapshot_digest"] == graph["snapshot_digest"]
    assert result["intervention"]["t0_snapshot_digest"] == graph["snapshot_digest"]
    assert result["baseline"]["t1"]["state_time"] == "t1_post_change"
    assert result["baseline"]["t2"]["state_time"] == "t2_neighborhood_adaptation"
    assert result["intervention"]["t1"]["state_time"] == "t1_post_change"
    assert result["intervention"]["t2"]["state_time"] == "t2_neighborhood_adaptation"
    assert result["baseline"]["t1"]["direct_state_delta"]["land_use_changed"] is False
    assert result["intervention"]["t1"]["direct_state_delta"]["land_use_changed"] is True
    assert result["claim_boundary"]["max_claim_level"] == "bounded_action_conditioned_spatial_scenario"
    assert result["empirical_policy_effect_claim"] is False


def test_counterfactual_rollout_returns_evidence_bounded_deltas_and_unavailable_heads():
    graph = _graph()
    result = run_counterfactual_rollout(
        graph=graph,
        intervention_action=_action(graph),
        land_use_dictionary=_dictionary(),
        transition_matrix=_matrix(),
        alternative_land_use_class=None,
    )

    assert result["direct_state_delta"]["from_land_use_class"] == "residential"
    assert result["direct_state_delta"]["to_land_use_class"] == "public_service"
    assert result["spillover_state_delta"]["intervention_message_count"] > 0
    assert result["potential_conflicts"]
    assert result["review_required"] is True
    assert result["unavailable_effects"] == [
        "approval_probability",
        "construction_schedule",
        "facility_capacity",
        "land_price",
        "livability_score",
        "population_migration",
        "traffic_and_walkability",
        "validated_policy_effect",
    ]
    assert result["unsupported_prediction_heads_ready"] is False


def test_optional_alternative_must_come_from_controlled_dictionary_and_matrix():
    graph = _graph()
    result = run_counterfactual_rollout(
        graph=graph,
        intervention_action=_action(graph),
        land_use_dictionary=_dictionary(),
        transition_matrix=_matrix(),
        alternative_land_use_class="commercial",
    )

    assert result["alternative"]["action_validation"]["transition"]["status"] == "allowed"
    assert result["alternative"]["t1"]["direct_state_delta"]["to_land_use_class"] == "commercial"


def test_invalid_or_prohibited_alternative_is_rejected():
    graph = _graph()
    try:
        run_counterfactual_rollout(
            graph=graph,
            intervention_action=_action(graph),
            land_use_dictionary=_dictionary(),
            transition_matrix=_matrix(),
            alternative_land_use_class="unknown",
        )
    except ValueError as error:
        assert str(error) == "alternative_action_invalid:unknown_to_land_use_class"
    else:
        raise AssertionError("unknown alternative should fail")


def test_counterfactual_rollout_is_deterministic_for_same_inputs():
    graph = _graph()
    kwargs = {
        "graph": graph,
        "intervention_action": _action(graph),
        "land_use_dictionary": _dictionary(),
        "transition_matrix": _matrix(),
        "alternative_land_use_class": "commercial",
    }

    first = run_counterfactual_rollout(**kwargs)
    second = run_counterfactual_rollout(**kwargs)

    assert first["rollout_digest"] == second["rollout_digest"]
    assert first["baseline"] == second["baseline"]
    assert first["intervention"] == second["intervention"]
    assert first["alternative"] == second["alternative"]
