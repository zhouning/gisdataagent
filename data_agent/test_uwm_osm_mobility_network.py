import json

from data_agent.uwm.osm_mobility_network import (
    OSM_MOBILITY_NETWORK_PROXY_SCHEMA,
    build_mmfe_state_input_from_osm_mobility_network_proxy,
    build_osm_mobility_network_proxy,
    write_osm_mobility_network_snapshot,
)


def _raw_payload():
    return {
        "version": 0.6,
        "osm3s": {"timestamp_osm_base": "2026-07-05T04:20:00Z"},
        "elements": [
            {"type": "node", "id": 1, "lat": 29.550, "lon": 106.550},
            {"type": "node", "id": 2, "lat": 29.551, "lon": 106.551},
            {"type": "node", "id": 3, "lat": 29.552, "lon": 106.552},
            {"type": "node", "id": 4, "lat": 29.553, "lon": 106.553},
            {
                "type": "way",
                "id": 101,
                "nodes": [1, 2, 3],
                "tags": {"highway": "primary", "name": "main road"},
            },
            {
                "type": "way",
                "id": 102,
                "nodes": [3, 4],
                "tags": {"highway": "footway", "name": "walk link"},
            },
            {
                "type": "way",
                "id": 103,
                "nodes": [4, 99],
                "tags": {"highway": "residential"},
            },
        ],
    }


def test_build_osm_mobility_network_proxy_counts_highway_topology_without_travel_time_claim():
    proxy = build_osm_mobility_network_proxy(
        raw_payload=_raw_payload(),
        requested_bbox=[29.52, 106.50, 29.60, 106.60],
        fetched_at="2026-07-05T14:20:00Z",
    )

    assert proxy["schema"] == OSM_MOBILITY_NETWORK_PROXY_SCHEMA
    assert proxy["source_dataset_ids"] == ["osm_mobility_network_bbox_public_proxy"]
    assert proxy["record_counts"]["coordinate_nodes"] == 4
    assert proxy["record_counts"]["highway_ways"] == 3
    assert proxy["record_counts"]["usable_highway_ways"] == 2
    assert proxy["graph_summary"]["node_count"] == 4
    assert proxy["graph_summary"]["edge_count"] == 3
    assert proxy["graph_summary"]["connected_component_count"] == 1
    assert proxy["highway_distribution"] == {"footway": 1, "primary": 1, "residential": 1}
    assert "not_a_travel_time_or_od_network" in proxy["limitations"]
    assert proxy["empirical_superiority_claim"] is False


def test_build_mmfe_state_input_from_osm_mobility_network_proxy_preserves_mobility_role():
    proxy = build_osm_mobility_network_proxy(
        raw_payload=_raw_payload(),
        requested_bbox=[29.52, 106.50, 29.60, 106.60],
        fetched_at="2026-07-05T14:20:00Z",
    )

    payload = build_mmfe_state_input_from_osm_mobility_network_proxy(
        proxy,
        timestamp="2026-07-05T14:25:00Z",
    )

    assert payload["schema"] == "mmfe.uwm_state_input.v1"
    assert payload["source_product"]["product_id"] == "mmfe-osm-mobility-network-2026-07-05T04:20:00Z"
    assert payload["urban_spatial_unit"]["unit_type"] == "osm_bbox_highway_network_extract"
    assert payload["state_components"]["mobility_activity"]["source_dataset_ids"] == [
        "osm_mobility_network_bbox_public_proxy"
    ]
    assert payload["graph_summary"]["relation_type_distribution"]["osm_way_connects_coordinate_nodes"] == 3
    assert payload["source_proxy"]["empirical_superiority_claim"] is False


def test_write_osm_mobility_network_snapshot_persists_raw_proxy_and_manifest(tmp_path):
    manifest = write_osm_mobility_network_snapshot(
        output_dir=tmp_path,
        raw_payload=_raw_payload(),
        requested_bbox=[29.52, 106.50, 29.60, 106.60],
        fetched_at="2026-07-05T14:20:00Z",
    )

    assert manifest["schema"] == "uwm.public_proxy_snapshot_manifest.v1"
    assert manifest["dataset_id"] == "osm_mobility_network_bbox_proxy_snapshot"
    assert manifest["record_counts"]["highway_ways"] == 3
    assert (tmp_path / "osm_mobility_network_overpass_raw.json").exists()
    assert (tmp_path / "osm_mobility_network_proxy.json").exists()
    assert json.loads((tmp_path / "snapshot_manifest.json").read_text(encoding="utf-8")) == manifest
