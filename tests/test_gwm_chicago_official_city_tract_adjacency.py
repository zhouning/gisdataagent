import json

from scripts.build_gwm_chicago_official_city_tract_adjacency import (
    DEFAULT_OUTPUT,
    build_official_city_tract_adjacency,
)


def test_official_chicago_city_network_is_cross_county_and_reproducible():
    result = build_official_city_tract_adjacency()
    checked = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))

    assert result == checked
    units = result["unit_contract"]
    assert units["city_tract_count"] == 801
    assert units["county_counts"] == {"031": 799, "043": 2}
    assert [unit["tract_geoid"] for unit in units["dupage_units"]] == [
        "17043840000",
        "17043840801",
    ]
    graph = result["graph_summary"]
    assert graph["queen_edge_count"] == 2636
    assert graph["rook_edge_count"] == 1889
    assert graph["queen_connected_component_count"] == 1
    assert graph["rook_connected_component_count"] == 1
    assert graph["queen_isolated_node_count"] == 0
    assert graph["rook_isolated_node_count"] == 0


def test_city_network_opens_only_unit_aligned_static_topology():
    result = build_official_city_tract_adjacency()

    assert result["topology_quality_diagnostics"]["passed"] is True
    assert result["readiness"]["network_to_unit_time_ready"] is True
    assert result["readiness"]["outside_city_interference_ready"] is False
    assert result["readiness"]["dynamic_network_ready"] is False
    assert result["readiness"]["causal_estimation_ready"] is False
    assert result["claim_boundary"]["city_internal_network_not_outside_city_interference"] is True
    assert result["claim_boundary"]["gwm_k0_validated"] is False
