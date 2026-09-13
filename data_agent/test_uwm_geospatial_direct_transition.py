from copy import deepcopy

import pytest

from data_agent.uwm.geospatial_kernel.direct_transition import apply_direct_transition
from data_agent.uwm.geospatial_kernel.land_use_action import (
    bind_server_actor,
    build_change_land_use_action,
    build_no_change_action,
    validate_land_use_action,
)
from data_agent.uwm.geospatial_kernel.state_graph import build_state_graph
from data_agent.uwm.geospatial_kernel.transition_matrix import build_transition_matrix


def _graph() -> dict:
    return build_state_graph(
        kernel_version="0.1.0",
        nodes=[
            {
                "node_id": "parcel-1",
                "node_type": "parcel",
                "state_time": "t0_current",
                "current_land_use_class": "residential",
                "planned_land_use_class": "public_service",
                "candidate_land_use_class": None,
                "source_land_use_code": "0701",
                "effective_land_use_class": "residential",
                "population": 120,
                "land_price": None,
                "facility_capacity": None,
                "traffic_flow": None,
                "construction_status": "not_observed",
                "livability_score": None,
                "evidence_refs": ["source:parcel-1"],
                "observability": "observed",
            },
            {
                "node_id": "parcel-2",
                "node_type": "parcel",
                "state_time": "t0_current",
                "current_land_use_class": "agricultural",
                "planned_land_use_class": "agricultural",
                "candidate_land_use_class": None,
                "source_land_use_code": "0101",
                "effective_land_use_class": "agricultural",
                "evidence_refs": ["source:parcel-2"],
                "observability": "observed",
            },
            {
                "node_id": "resource-1",
                "node_type": "planning_resource",
                "state_time": "t0_current",
                "compatibility_status": "compatible_with_residential",
                "evidence_refs": ["source:resource-1"],
                "observability": "observed",
            },
            {
                "node_id": "village-1",
                "node_type": "village_context",
                "state_time": "t0_current",
                "evidence_refs": ["source:village-1"],
                "observability": "derived",
            },
        ],
        edges=[
            {
                "edge_id": "edge-resource",
                "source_node_id": "parcel-1",
                "target_node_id": "resource-1",
                "relation_type": "parcel_contains_resource",
                "compatibility_by_land_use": {
                    "residential": "compatible",
                    "public_service": "unresolved",
                },
                "active_compatibility_status": "compatible",
                "evidence_refs": ["geometry:intersection"],
                "support_level": "deterministic_geometry",
            },
            {
                "edge_id": "edge-adjacent",
                "source_node_id": "parcel-1",
                "target_node_id": "parcel-2",
                "relation_type": "parcel_adjacent_parcel",
                "evidence_refs": ["geometry:shared-boundary"],
                "support_level": "deterministic_geometry",
            },
            {
                "edge_id": "edge-village",
                "source_node_id": "parcel-1",
                "target_node_id": "village-1",
                "relation_type": "parcel_within_village",
                "evidence_refs": ["geometry:containment"],
                "support_level": "deterministic_geometry",
            },
        ],
    )


def _dictionary() -> dict:
    return {
        "version": "dict-v1",
        "classes": ["residential", "public_service", "agricultural"],
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
            }
        ],
    )


def _validated_action(graph: dict, *, no_change: bool = False) -> tuple[dict, dict]:
    builder = build_no_change_action if no_change else build_change_land_use_action
    kwargs = {
        "parcel_id": "parcel-1",
        "rationale": "基线" if no_change else "用途变更情景",
        "snapshot_digest": graph["snapshot_digest"],
        "dictionary_version": "dict-v1",
        "transition_matrix_version": "matrix-v1",
        "requested_at": "2026-07-11T08:00:00Z",
    }
    if no_change:
        kwargs["current_land_use_class"] = "residential"
    else:
        kwargs["from_land_use_class"] = "residential"
        kwargs["to_land_use_class"] = "public_service"
    action = bind_server_actor(builder(**kwargs), actor_id="user-123")
    parcel = next(node for node in graph["nodes"] if node["node_id"] == "parcel-1")
    validation = validate_land_use_action(
        action,
        parcel=parcel,
        actual_snapshot_digest=graph["snapshot_digest"],
        land_use_dictionary=_dictionary(),
        transition_matrix=_matrix(),
    )
    assert validation["valid"], validation["errors"]
    return action, validation


def test_change_transition_updates_only_target_direct_state_and_relationships():
    graph = _graph()
    original = deepcopy(graph)
    action, validation = _validated_action(graph)

    result = apply_direct_transition(
        graph=graph, action=action, action_validation=validation
    )

    assert graph == original
    assert result["state_time"] == "t1_post_change"
    target = next(node for node in result["state_graph"]["nodes"] if node["node_id"] == "parcel-1")
    neighbor = next(node for node in result["state_graph"]["nodes"] if node["node_id"] == "parcel-2")
    assert target["current_land_use_class"] == "residential"
    assert target["planned_land_use_class"] == "public_service"
    assert target["candidate_land_use_class"] == "public_service"
    assert target["effective_land_use_class"] == "public_service"
    assert target["state_time"] == "t1_post_change"
    assert neighbor["state_time"] == "t0_current"
    assert neighbor["effective_land_use_class"] == "agricultural"
    relationship = next(
        edge for edge in result["state_graph"]["edges"] if edge["edge_id"] == "edge-resource"
    )
    assert relationship["active_compatibility_status"] == "unresolved"
    assert result["direct_state_delta"]["changed_node_ids"] == ["parcel-1"]
    assert result["direct_state_delta"]["changed_edge_ids"] == ["edge-resource"]


def test_transition_never_invents_unsupported_effects():
    graph = _graph()
    action, validation = _validated_action(graph)

    result = apply_direct_transition(
        graph=graph, action=action, action_validation=validation
    )
    target = next(node for node in result["state_graph"]["nodes"] if node["node_id"] == "parcel-1")

    assert target["population"] == 120
    assert target["land_price"] is None
    assert target["facility_capacity"] is None
    assert target["traffic_flow"] is None
    assert target["construction_status"] == "not_observed"
    assert target["livability_score"] is None
    assert result["unsupported_effect_fields"] == [
        "approval_probability",
        "construction_status",
        "facility_capacity",
        "land_price",
        "livability_score",
        "population",
        "traffic_flow",
    ]


def test_no_change_transition_creates_t1_baseline_without_land_use_delta():
    graph = _graph()
    action, validation = _validated_action(graph, no_change=True)

    result = apply_direct_transition(
        graph=graph, action=action, action_validation=validation
    )

    target = next(node for node in result["state_graph"]["nodes"] if node["node_id"] == "parcel-1")
    assert target["candidate_land_use_class"] == "residential"
    assert target["effective_land_use_class"] == "residential"
    assert target["state_time"] == "t1_post_change"
    assert result["direct_state_delta"]["land_use_changed"] is False
    assert result["direct_state_delta"]["changed_edge_ids"] == []


def test_transition_rejects_unvalidated_or_wrong_snapshot_action():
    graph = _graph()
    action, validation = _validated_action(graph)
    validation["valid"] = False

    with pytest.raises(ValueError, match="validated_action_required"):
        apply_direct_transition(graph=graph, action=action, action_validation=validation)

    action, validation = _validated_action(graph)
    action["snapshot_digest"] = "b" * 64
    with pytest.raises(ValueError, match="action_snapshot_digest_mismatch"):
        apply_direct_transition(graph=graph, action=action, action_validation=validation)
