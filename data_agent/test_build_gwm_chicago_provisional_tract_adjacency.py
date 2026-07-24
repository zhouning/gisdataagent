import hashlib
import json

from scripts.build_gwm_chicago_provisional_tract_adjacency import (
    DEFAULT_OUTPUT,
    ROOT,
    _canonical_digest,
    build_provisional_tract_adjacency,
)


def test_checked_provisional_adjacency_is_reproducible_and_hash_bound():
    checked = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    rebuilt = build_provisional_tract_adjacency()

    assert checked == rebuilt
    digest_payload = dict(checked)
    checked_digest = digest_payload.pop("adjacency_digest")
    assert _canonical_digest(digest_payload) == checked_digest
    for artifact in checked["artifacts"].values():
        payload = (ROOT / artifact["path"]).read_bytes()
        assert len(payload) == artifact["bytes"]
        assert hashlib.sha256(payload).hexdigest() == artifact["sha256"]


def test_secondary_geometry_is_complete_but_topology_quality_fails_closed():
    payload = build_provisional_tract_adjacency()
    geometry = payload["geometry_validation"]
    graph = payload["graph_summary"]
    quality = payload["topology_quality_diagnostics"]
    readiness = payload["readiness"]

    assert geometry == {
        "feature_count": 1332,
        "unique_tract_geoid_count": 1332,
        "geometry_types": ["Polygon"],
        "valid_nonempty_geometry_count": 1332,
        "coordinate_reference_system": "WGS84 longitude_latitude",
    }
    assert graph["queen_edge_count"] == 2458
    assert graph["rook_edge_count"] == 1081
    assert graph["queen_connected_component_count"] == 100
    assert graph["rook_connected_component_count"] == 378
    assert graph["queen_isolated_node_count"] == 67
    assert graph["rook_isolated_node_count"] == 234
    assert quality["queen_isolated_node_share"] == 0.0503
    assert quality["rook_to_queen_edge_ratio"] == 0.439788
    assert quality["passed"] is False
    assert readiness["secondary_full_cook_geometry_verified"] is True
    assert readiness["provisional_queen_adjacency_constructed"] is True
    assert readiness["provisional_rook_adjacency_constructed"] is True
    assert readiness["provisional_topology_quality_pass"] is False
    assert readiness["provisional_interference_network_usable"] is False
    assert readiness["official_tiger_geometry_verified"] is False
    assert readiness["official_adjacency_constructed"] is False
    assert readiness["network_to_unit_time_ready"] is False


def test_all_target_tracts_are_present_but_rook_neighbors_are_incomplete():
    payload = build_provisional_tract_adjacency()
    target = payload["target_cohort"]

    assert target["event_count"] == 17
    assert target["distinct_tract_count"] == 17
    assert target["missing_target_tracts"] == []
    assert target["tracts_with_zero_queen_neighbors"] == []
    assert target["tracts_with_zero_rook_neighbors"] == [
        "17031242700",
        "17031243500",
        "17031836000",
    ]
    assert set(target["adjacency"]) == {
        "17031010400",
        "17031010600",
        "17031071000",
        "17031222500",
        "17031222900",
        "17031242700",
        "17031242800",
        "17031243400",
        "17031243500",
        "17031300900",
        "17031310600",
        "17031310900",
        "17031460800",
        "17031830600",
        "17031833100",
        "17031836000",
        "17031841300",
    }
