from copy import deepcopy

from data_agent.uwm.geospatial_kernel.direct_transition import apply_direct_transition
from data_agent.uwm.geospatial_kernel.facility_action import (
    bind_server_facility_actor,
    build_facility_action,
    scenario_facility_id,
    validate_facility_action,
)
from data_agent.uwm.geospatial_kernel.state_graph import build_state_graph


def _parcel(node_id: str, area_id: str, x0: float) -> dict:
    return {
        "node_id": node_id,
        "node_type": "parcel",
        "state_time": "t0_current",
        "current_land_use_class": "residential",
        "planned_land_use_class": "residential",
        "candidate_land_use_class": None,
        "source_land_use_code": "R",
        "effective_land_use_class": "residential",
        "planning_area_id": area_id,
        "distance_crs": "EPSG:3857",
        "display_geometry_wgs84": {
            "type": "Polygon",
            "coordinates": [
                [
                    [x0, 0.0],
                    [x0 + 0.001, 0.0],
                    [x0 + 0.001, 0.001],
                    [x0, 0.001],
                    [x0, 0.0],
                ]
            ],
        },
        "evidence_refs": [f"fixture:{node_id}"],
    }


def _graph() -> dict:
    nodes = [
        _parcel("parcel-a1", "area-a", 0.0),
        _parcel("parcel-a2", "area-a", 0.002),
        _parcel("parcel-b1", "area-b", 0.01),
        {
            "node_id": "facility-a",
            "node_type": "facility",
            "state_time": "t0_current",
            "planning_area_id": "area-a",
            "canonical_class": "education.school",
            "distance_crs": "EPSG:3857",
            "display_geometry_wgs84": {
                "type": "Point",
                "coordinates": [0.0005, 0.0005],
            },
            "evidence_refs": ["fixture:facility-a"],
        },
        {
            "node_id": "facility-b",
            "node_type": "facility",
            "state_time": "t0_current",
            "planning_area_id": "area-b",
            "canonical_class": "education.school",
            "distance_crs": "EPSG:3857",
            "display_geometry_wgs84": {
                "type": "Point",
                "coordinates": [0.0105, 0.0005],
            },
            "evidence_refs": ["fixture:facility-b"],
        },
    ]
    edges = [
        {
            "edge_id": "edge-parcel-a1-facility-a",
            "source_node_id": "parcel-a1",
            "target_node_id": "facility-a",
            "relation_type": "parcel_near_facility",
            "distance_m": 0.0,
            "support_level": "bounded_proxy",
            "evidence_refs": ["fixture:distance"],
        }
    ]
    return build_state_graph(nodes=nodes, edges=edges, kernel_version="test")


def _action(
    graph: dict,
    *,
    action_type: str = "add_facility",
    facility_id: str | None = None,
    planning_area_id: str = "area-a",
    authorized_areas: list[str] | None = None,
) -> dict:
    action = build_facility_action(
        action_type=action_type,
        parcel_id="parcel-a1",
        planning_area_id=planning_area_id,
        facility_class="education.school",
        facility_id=facility_id,
        service_radius_m=300.0,
        radius_evidence_source="user_scenario_assumption",
        placement_geometry_wgs84={
            "type": "Point",
            "coordinates": [0.0005, 0.0005],
        },
        distance_crs="EPSG:3857",
        rationale="bounded facility scenario",
        snapshot_digest=graph["snapshot_digest"],
        requested_at="2026-07-28T00:00:00Z",
    )
    return bind_server_facility_actor(
        action,
        actor_id="planner-1",
        authorized_planning_area_ids=(["area-a"] if authorized_areas is None else authorized_areas),
    )


def test_add_facility_writes_node_and_dynamic_relations_to_future_graph():
    graph = _graph()
    action = _action(graph)
    validation = validate_facility_action(action, graph=graph)

    assert validation["valid"] is True
    transition = apply_direct_transition(graph=graph, action=action, action_validation=validation)
    future = transition["state_graph"]
    facility_id = scenario_facility_id(parcel_id="parcel-a1", facility_class="education.school")

    assert all(node["node_id"] != facility_id for node in graph["nodes"])
    added = next(node for node in future["nodes"] if node["node_id"] == facility_id)
    assert added["observability"] == "action_conditioned_scenario"
    relations = [
        edge
        for edge in future["edges"]
        if edge.get("target_node_id") == facility_id
        and edge.get("relation_type") == "parcel_near_facility"
    ]
    assert {edge["source_node_id"] for edge in relations} == {
        "parcel-a1",
        "parcel-a2",
    }
    assert transition["direct_state_delta"]["added_node_ids"] == [facility_id]


def test_remove_facility_removes_node_and_all_incident_relations():
    graph = _graph()
    action = _action(graph, action_type="remove_facility", facility_id="facility-a")
    validation = validate_facility_action(action, graph=graph)

    assert validation["valid"] is True
    transition = apply_direct_transition(graph=graph, action=action, action_validation=validation)
    future = transition["state_graph"]

    assert all(node["node_id"] != "facility-a" for node in future["nodes"])
    assert all(
        "facility-a" not in {edge["source_node_id"], edge["target_node_id"]}
        for edge in future["edges"]
    )
    assert transition["direct_state_delta"]["removed_node_ids"] == ["facility-a"]


def test_facility_action_rejects_stale_duplicate_missing_cross_area_and_permission():
    graph = _graph()

    stale = _action(graph)
    stale["snapshot_digest"] = "stale"
    assert "snapshot_digest_mismatch" in validate_facility_action(stale, graph=graph)["errors"]

    first = _action(graph)
    first_validation = validate_facility_action(first, graph=graph)
    future = apply_direct_transition(graph=graph, action=first, action_validation=first_validation)[
        "state_graph"
    ]
    duplicate = _action(future)
    assert "duplicate_facility_id" in validate_facility_action(duplicate, graph=future)["errors"]

    missing = _action(graph, action_type="remove_facility", facility_id="facility-missing")
    assert "facility_not_found" in validate_facility_action(missing, graph=graph)["errors"]

    cross_area = _action(graph, action_type="remove_facility", facility_id="facility-b")
    assert (
        "facility_planning_area_mismatch"
        in validate_facility_action(cross_area, graph=graph)["errors"]
    )

    denied = _action(graph, authorized_areas=["area-b"])
    assert (
        "planning_area_permission_denied" in validate_facility_action(denied, graph=graph)["errors"]
    )

    unbound = deepcopy(_action(graph))
    unbound["permission_binding"] = "unbound"
    assert "permission_not_server_bound" in validate_facility_action(unbound, graph=graph)["errors"]
