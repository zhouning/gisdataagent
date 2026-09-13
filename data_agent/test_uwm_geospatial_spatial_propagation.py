from data_agent.uwm.geospatial_kernel.spatial_propagation import propagate_spatial_messages
from data_agent.uwm.geospatial_kernel.state_graph import build_state_graph


def _parcel(node_id: str, land_use: str = "residential") -> dict:
    return {
        "node_id": node_id,
        "node_type": "parcel",
        "state_time": "t0_current",
        "current_land_use_class": land_use,
        "planned_land_use_class": land_use,
        "candidate_land_use_class": None,
        "source_land_use_code": land_use,
        "effective_land_use_class": land_use,
        "area_m2": 1000.0,
        "perimeter_m": 140.0,
        "evidence_refs": [f"source:{node_id}"],
        "observability": "observed",
    }


def _graph() -> dict:
    nodes = [
        _parcel("parcel-target"),
        _parcel("parcel-adjacent", "agricultural"),
        _parcel("parcel-near-40", "commercial"),
        _parcel("parcel-near-120", "public_service"),
        _parcel("parcel-near-250", "residential"),
        _parcel("parcel-far-301", "industrial"),
        {
            "node_id": "resource-1",
            "node_type": "planning_resource",
            "state_time": "t0_current",
            "mapping_status": "mapped",
            "evidence_refs": ["source:resource-1"],
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
            "node_id": "facility-1",
            "node_type": "facility",
            "state_time": "t0_current",
            "mapping_status": "mapped",
            "evidence_refs": ["source:facility-1"],
            "observability": "observed",
        },
        {
            "node_id": "village-target",
            "node_type": "village_context",
            "state_time": "t0_current",
            "evidence_refs": ["source:village-target"],
            "observability": "derived",
        },
        {
            "node_id": "village-neighbor",
            "node_type": "village_context",
            "state_time": "t0_current",
            "evidence_refs": ["source:village-neighbor"],
            "observability": "derived",
        },
        {
            "node_id": "admin-1",
            "node_type": "admin_context",
            "state_time": "t0_current",
            "evidence_refs": ["source:admin-1"],
            "observability": "derived",
        },
        {
            "node_id": "admin-2",
            "node_type": "admin_context",
            "state_time": "t0_current",
            "evidence_refs": ["source:admin-2"],
            "observability": "derived",
        },
    ]
    edges = [
        {
            "edge_id": "edge-adjacent-forward",
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
            "edge_id": "edge-adjacent-cycle",
            "source_node_id": "parcel-adjacent",
            "target_node_id": "parcel-target",
            "relation_type": "parcel_adjacent_parcel",
            "shared_boundary_length_m": 35.0,
            "source_perimeter_m": 120.0,
            "target_perimeter_m": 140.0,
            "compatibility_status": "potential_conflict",
            "evidence_refs": ["geometry:shared-boundary"],
            "support_level": "deterministic_geometry",
        },
        *[
            {
                "edge_id": f"edge-near-{distance}",
                "source_node_id": "parcel-target",
                "target_node_id": target,
                "relation_type": "parcel_near_parcel",
                "distance_m": float(distance),
                "evidence_refs": [f"geometry:distance:{distance}"],
                "support_level": "deterministic_geometry",
            }
            for distance, target in [
                (40, "parcel-near-40"),
                (120, "parcel-near-120"),
                (250, "parcel-near-250"),
                (301, "parcel-far-301"),
            ]
        ],
        {
            "edge_id": "edge-resource",
            "source_node_id": "parcel-target",
            "target_node_id": "resource-1",
            "relation_type": "parcel_contains_resource",
            "intersection_ratio": 0.75,
            "active_compatibility_status": "unresolved",
            "evidence_refs": ["geometry:intersection"],
            "support_level": "deterministic_geometry",
        },
        {
            "edge_id": "edge-resource-unmapped",
            "source_node_id": "parcel-target",
            "target_node_id": "resource-unmapped",
            "relation_type": "parcel_contains_resource",
            "intersection_ratio": 0.25,
            "active_compatibility_status": "unmapped",
            "evidence_refs": ["geometry:intersection-unmapped"],
            "support_level": "deterministic_geometry",
        },
        {
            "edge_id": "edge-facility",
            "source_node_id": "parcel-target",
            "target_node_id": "facility-1",
            "relation_type": "parcel_near_facility",
            "distance_m": 90.0,
            "active_compatibility_status": "potential_synergy",
            "evidence_refs": ["geometry:facility-distance"],
            "support_level": "bounded_proxy",
        },
        {
            "edge_id": "edge-target-village",
            "source_node_id": "parcel-target",
            "target_node_id": "village-target",
            "relation_type": "parcel_within_village",
            "evidence_refs": ["geometry:containment"],
            "support_level": "deterministic_geometry",
        },
        {
            "edge_id": "edge-village-neighbor",
            "source_node_id": "village-target",
            "target_node_id": "village-neighbor",
            "relation_type": "cross_scale_context",
            "context_relation": "direct_village_neighbor",
            "evidence_refs": ["geometry:village-adjacency"],
            "support_level": "deterministic_geometry",
        },
        {
            "edge_id": "edge-village-admin",
            "source_node_id": "village-target",
            "target_node_id": "admin-1",
            "relation_type": "village_within_admin",
            "evidence_refs": ["authority:hierarchy"],
            "support_level": "authoritative_rule",
        },
        {
            "edge_id": "edge-admin-chain",
            "source_node_id": "admin-1",
            "target_node_id": "admin-2",
            "relation_type": "cross_scale_context",
            "evidence_refs": ["geometry:admin-adjacency"],
            "support_level": "deterministic_geometry",
        },
    ]
    return build_state_graph(nodes=nodes, edges=edges, kernel_version="0.1.0")


def test_spatial_propagation_respects_hops_distance_bands_and_admin_stop():
    result = propagate_spatial_messages(
        graph=_graph(),
        target_parcel_id="parcel-target",
        from_land_use_class="residential",
        to_land_use_class="public_service",
        kernel_version="0.1.0",
    )

    targets = {message["target_node_id"] for message in result["messages"]}
    assert "parcel-target" in targets
    assert "parcel-adjacent" in targets
    assert "parcel-near-40" in targets
    assert "parcel-near-120" in targets
    assert "parcel-near-250" in targets
    assert "parcel-far-301" not in targets
    assert "resource-1" in targets
    assert "resource-unmapped" in targets
    assert "facility-1" in targets
    assert "village-target" in targets
    assert "village-neighbor" in targets
    assert "admin-1" in targets
    assert "admin-2" not in targets
    assert result["summary"]["max_local_distance_m"] == 300.0
    assert result["summary"]["admin_propagation_stopped"] is True


def test_messages_are_decomposed_traceable_and_not_policy_scores():
    result = propagate_spatial_messages(
        graph=_graph(),
        target_parcel_id="parcel-target",
        from_land_use_class="residential",
        to_land_use_class="public_service",
        kernel_version="0.1.0",
    )

    for message in result["messages"]:
        assert message["message_id"]
        assert message["relation_type"]
        assert message["effect_type"]
        assert message["direction"]
        assert message["raw_evidence"]
        assert message["normalization_basis"]
        assert message["propagation_stage"] in {0, 1, 2, 3}
        assert message["support_level"] in {
            "deterministic_geometry",
            "authoritative_rule",
            "bounded_proxy",
        }
        assert message["uncertainty"] in {"none", "bounded", "unresolved"}
        assert message["claim_level"] == "bounded_action_conditioned_spatial_scenario"
        assert message["kernel_version"] == "0.1.0"
        assert "impact_score" not in message
        assert "policy_success_probability" not in message
        assert "learned_effect" not in message


def test_distance_and_adjacency_messages_preserve_evidence_vectors():
    result = propagate_spatial_messages(
        graph=_graph(),
        target_parcel_id="parcel-target",
        from_land_use_class="residential",
        to_land_use_class="public_service",
        kernel_version="0.1.0",
    )

    by_target = {message["target_node_id"]: message for message in result["messages"]}
    adjacent = by_target["parcel-adjacent"]["raw_evidence"]
    assert adjacent["compatibility_status"] == "potential_conflict"
    assert adjacent["shared_boundary_length_m"] == 35.0
    assert adjacent["source_shared_boundary_ratio"] == 0.25
    assert adjacent["target_shared_boundary_ratio"] == 0.291666667
    assert by_target["parcel-near-40"]["raw_evidence"]["proxy_distance_band"] == "0_50m"
    assert by_target["parcel-near-120"]["raw_evidence"]["proxy_distance_band"] == "50_150m"
    assert by_target["parcel-near-250"]["raw_evidence"]["proxy_distance_band"] == "150_300m"
    assert by_target["resource-1"]["raw_evidence"]["intersection_ratio"] == 0.75
    assert by_target["resource-unmapped"]["review_priority"] == "unmapped_object"


def test_cycle_and_duplicate_paths_do_not_accumulate_messages():
    result = propagate_spatial_messages(
        graph=_graph(),
        target_parcel_id="parcel-target",
        from_land_use_class="residential",
        to_land_use_class="public_service",
        kernel_version="0.1.0",
    )

    message_keys = [
        (
            message["source_node_id"],
            message["target_node_id"],
            message["relation_type"],
            message["effect_type"],
        )
        for message in result["messages"]
    ]
    assert len(message_keys) == len(set(message_keys))
    assert sum(message["target_node_id"] == "parcel-target" for message in result["messages"]) == 1
    assert result["summary"]["cycle_paths_skipped"] >= 1


def test_spatial_propagation_is_deterministic_for_same_graph_and_versions():
    first = propagate_spatial_messages(
        graph=_graph(),
        target_parcel_id="parcel-target",
        from_land_use_class="residential",
        to_land_use_class="public_service",
        kernel_version="0.1.0",
    )
    second = propagate_spatial_messages(
        graph=_graph(),
        target_parcel_id="parcel-target",
        from_land_use_class="residential",
        to_land_use_class="public_service",
        kernel_version="0.1.0",
    )

    assert first["messages"] == second["messages"]
    assert first["message_digest"] == second["message_digest"]


def test_local_messages_are_action_conditioned_not_static_relationship_enumeration():
    graph = _graph()
    baseline = propagate_spatial_messages(
        graph=graph,
        target_parcel_id="parcel-target",
        from_land_use_class="residential",
        to_land_use_class="residential",
        kernel_version="0.1.0",
    )
    intervention = propagate_spatial_messages(
        graph=graph,
        target_parcel_id="parcel-target",
        from_land_use_class="residential",
        to_land_use_class="public_service",
        kernel_version="0.1.0",
    )

    baseline_by_target = {row["target_node_id"]: row for row in baseline["messages"]}
    intervention_by_target = {row["target_node_id"]: row for row in intervention["messages"]}
    for target_id in ["parcel-adjacent", "parcel-near-40", "resource-1", "facility-1", "village-target"]:
        assert baseline_by_target[target_id]["raw_evidence"]["action_land_use_changed"] is False
        assert intervention_by_target[target_id]["raw_evidence"]["action_land_use_changed"] is True
        assert intervention_by_target[target_id]["raw_evidence"]["action_to_land_use_class"] == "public_service"
    assert baseline["message_digest"] != intervention["message_digest"]


def test_undirected_parcel_relation_propagates_from_either_endpoint():
    graph = _graph()
    reverse = propagate_spatial_messages(
        graph=graph,
        target_parcel_id="parcel-adjacent",
        from_land_use_class="agricultural",
        to_land_use_class="public_service",
        kernel_version="0.1.0",
    )

    target_messages = [
        row for row in reverse["messages"] if row["target_node_id"] == "parcel-target"
    ]
    assert len(target_messages) == 1
    assert target_messages[0]["relation_type"] == "parcel_adjacent_parcel"
    assert target_messages[0]["direction"] == "outbound"
