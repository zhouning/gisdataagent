from data_agent.uwm.osm_overpass_queries import (
    build_osm_amenity_overpass_query,
    build_osm_highway_overpass_query,
)


def test_build_osm_amenity_overpass_query_requests_nodes_ways_relations_with_centers():
    query = build_osm_amenity_overpass_query([29.52, 106.50, 29.60, 106.60], timeout_seconds=180)

    assert query.startswith("[out:json][timeout:180];")
    assert 'node["amenity"](29.52,106.5,29.6,106.6);' in query
    assert 'way["amenity"](29.52,106.5,29.6,106.6);' in query
    assert 'relation["amenity"](29.52,106.5,29.6,106.6);' in query
    assert "out center tags;" in query


def test_build_osm_highway_overpass_query_expands_way_nodes_for_graph_edges():
    query = build_osm_highway_overpass_query([29.52, 106.50, 29.60, 106.60], timeout_seconds=240)

    assert query.startswith("[out:json][timeout:240];")
    assert 'way["highway"](29.52,106.5,29.6,106.6);' in query
    assert "(._;>;);" in query
    assert "out body;" in query
