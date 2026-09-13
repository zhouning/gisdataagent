import json

from data_agent.uwm.osm_service_accessibility import (
    OSM_SERVICE_ACCESSIBILITY_PROXY_SCHEMA,
    build_mmfe_state_input_from_osm_service_accessibility_proxy,
    build_osm_service_accessibility_proxy,
    write_osm_service_accessibility_snapshot,
)


def _raw_payload():
    return {
        "version": 0.6,
        "osm3s": {"timestamp_osm_base": "2026-07-05T03:00:29Z"},
        "elements": [
            {"type": "node", "id": 1, "lat": 29.56, "lon": 106.55, "tags": {"amenity": "hospital"}},
            {"type": "node", "id": 2, "lat": 29.57, "lon": 106.56, "tags": {"amenity": "school"}},
            {"type": "node", "id": 3, "lat": 29.58, "lon": 106.57, "tags": {"amenity": "restaurant"}},
            {"type": "node", "id": 4, "lat": 29.59, "lon": 106.58, "tags": {"amenity": "bank"}},
            {"type": "node", "id": 5, "tags": {"amenity": "parking"}},
        ],
    }


def test_build_osm_service_accessibility_proxy_classifies_coordinate_sample_without_overclaim():
    proxy = build_osm_service_accessibility_proxy(
        raw_payload=_raw_payload(),
        requested_bbox=[29.45, 106.40, 29.70, 106.70],
        fetched_at="2026-07-05T13:40:00Z",
    )

    assert proxy["schema"] == OSM_SERVICE_ACCESSIBILITY_PROXY_SCHEMA
    assert proxy["source_dataset_ids"] == ["osm_services_geometry_public_proxy"]
    assert proxy["record_counts"] == {"elements": 5, "coordinate_elements": 4, "amenity_elements": 5}
    assert proxy["service_category_counts"]["healthcare"] == 1
    assert proxy["service_category_counts"]["education"] == 1
    assert proxy["service_category_counts"]["food_retail"] == 1
    assert proxy["service_category_counts"]["finance"] == 1
    assert proxy["service_category_counts"]["mobility_parking"] == 1
    assert proxy["coordinate_coverage"]["coordinate_element_share"] == 0.8
    assert proxy["service_accessibility_proxy"]["essential_service_count"] == 2
    assert proxy["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert "overpass_bbox_extract_not_full_municipality" in proxy["limitations"]
    assert proxy["empirical_superiority_claim"] is False


def test_build_osm_service_accessibility_proxy_uses_way_centers_from_complete_bbox_extract():
    raw_payload = {
        "version": 0.6,
        "osm3s": {"timestamp_osm_base": "2026-07-05T04:00:00Z"},
        "elements": [
            {
                "type": "way",
                "id": 11,
                "center": {"lat": 29.561, "lon": 106.552},
                "tags": {"amenity": "clinic", "name": "clinic from way center"},
            },
            {
                "type": "relation",
                "id": 12,
                "center": {"lat": 29.562, "lon": 106.553},
                "tags": {"amenity": "library", "name:zh": "图书馆"},
            },
        ],
    }

    proxy = build_osm_service_accessibility_proxy(
        raw_payload=raw_payload,
        requested_bbox=[29.52, 106.50, 29.60, 106.60],
        fetched_at="2026-07-05T14:10:00Z",
    )

    assert proxy["record_counts"] == {"elements": 2, "coordinate_elements": 2, "amenity_elements": 2}
    assert proxy["service_points"][0]["osm_type"] == "way"
    assert proxy["service_points"][0]["latitude"] == 29.561
    assert proxy["service_points"][0]["longitude"] == 106.552
    assert proxy["service_category_counts"]["healthcare"] == 1
    assert proxy["service_category_counts"]["education"] == 1


def test_build_mmfe_state_input_from_osm_service_accessibility_proxy_preserves_sample_warning():
    proxy = build_osm_service_accessibility_proxy(
        raw_payload=_raw_payload(),
        requested_bbox=[29.45, 106.40, 29.70, 106.70],
        fetched_at="2026-07-05T13:40:00Z",
    )

    payload = build_mmfe_state_input_from_osm_service_accessibility_proxy(
        proxy,
        timestamp="2026-07-05T13:45:00Z",
    )

    assert payload["schema"] == "mmfe.uwm_state_input.v1"
    assert payload["source_product"]["product_id"] == "mmfe-osm-service-accessibility-2026-07-05T03:00:29Z"
    assert payload["urban_spatial_unit"]["unit_type"] == "osm_bbox_service_point_sample"
    assert payload["state_components"]["service_accessibility"]["source_dataset_ids"] == [
        "osm_services_geometry_public_proxy"
    ]
    assert payload["graph_summary"]["relation_type_distribution"]["bbox_contains_osm_service_point"] == 4
    assert payload["source_proxy"]["empirical_superiority_claim"] is False
    assert any("not a complete service accessibility surface" in warning for warning in payload["warnings"])


def test_write_osm_service_accessibility_snapshot_persists_proxy_and_manifest(tmp_path):
    manifest = write_osm_service_accessibility_snapshot(
        output_dir=tmp_path,
        raw_payload=_raw_payload(),
        requested_bbox=[29.45, 106.40, 29.70, 106.70],
        fetched_at="2026-07-05T13:40:00Z",
    )

    assert manifest["schema"] == "uwm.public_proxy_snapshot_manifest.v1"
    assert manifest["dataset_id"] == "osm_service_accessibility_proxy_snapshot"
    assert manifest["record_counts"]["coordinate_elements"] == 4
    assert (tmp_path / "osm_services_overpass_geometry_raw.json").exists()
    assert (tmp_path / "osm_service_accessibility_proxy.json").exists()
    assert json.loads((tmp_path / "snapshot_manifest.json").read_text(encoding="utf-8")) == manifest
