from copy import deepcopy

import pytest

from data_agent.uwm.traditional_mobility_accessibility import (
    DEMAND8_CHANNELS,
    build_mobility_accessibility_product,
)


def source_fixture():
    return {
        "surface": {
            "schema": "uwm.full_admin_service_accessibility_surface.v1",
            "source_dataset_ids": ["service-poi", "osm-roads"],
            "admin_unit_count": 2,
            "admin_service_rows": [
                {
                    "admin_unit_id": "B",
                    "county": "县B",
                    "township": "镇B",
                    "longitude": 106.7,
                    "latitude": 29.6,
                    "service_point_count": 0,
                    "essential_service_count": 0,
                    "nearest_essential_service_distance_m": None,
                    "nearest_essential_service_travel_time_min_proxy": None,
                    "road_segment_count": 0,
                    "road_length_km": 0.0,
                    "mean_road_speed_kmh": None,
                    "service_accessibility_score": None,
                },
                {
                    "admin_unit_id": "A",
                    "county": "县A",
                    "township": "镇A",
                    "longitude": 106.5,
                    "latitude": 29.5,
                    "service_point_count": 10,
                    "essential_service_count": 3,
                    "nearest_essential_service_distance_m": 900.0,
                    "nearest_essential_service_travel_time_min_proxy": 12.0,
                    "road_segment_count": 40,
                    "road_length_km": 20.0,
                    "mean_road_speed_kmh": 30.0,
                    "service_accessibility_score": 0.4,
                },
            ],
            "claim_boundary": {"max_claim_level": "bounded_support"},
            "limitations": ["service_accessibility_surface_is_proxy_not_observed_travel_time"],
        },
        "mobility_graph": {
            "schema": "uwm.full_admin_mobility_graph.v1",
            "graph_id": "mobility-1",
            "summary": {"node_count": 2, "edge_count": 1, "road_segment_count_sum": 40, "road_length_km_sum": 20.0},
            "claim_boundary": {"max_claim_level": "bounded_support"},
            "limitations": ["mobility_graph_uses_travel_time_and_road_context_proxies_not_observed_trip_times"],
        },
        "quality_audit": {
            "schema": "uwm.full_admin_service_surface_quality_audit.v1",
            "supported_claim": "full_admin_service_surface_quality_audit_ready",
            "claim_boundary": {"max_claim_level": "bounded_support"},
            "limitations": ["not_observed_policy_outcome"],
        },
    }


def test_demand8_channel_registry_covers_complete_source_requirement():
    assert set(DEMAND8_CHANNELS) == {
        "service_inventory",
        "administrative_accessibility_surface",
        "nearest_service_distance",
        "road_network_travel_time",
        "walking_time",
        "first_last_mile",
        "road_connectivity",
        "cycling_routes",
        "public_transport",
        "shaded_routes",
        "universal_accessibility",
        "parking_pressure",
        "pedestrian_crossings",
        "road_safety",
    }


def test_product_builds_canonical_rows_and_complete_channel_readiness():
    product = build_mobility_accessibility_product(**source_fixture())

    assert [row["admin_unit_id"] for row in product["admin_units"]] == ["A", "B"]
    assert set(product["channel_readiness"]) == set(DEMAND8_CHANNELS)
    assert product["channel_readiness"]["service_inventory"]["status"] == "implemented"
    assert product["channel_readiness"]["walking_time"]["status"] == "proxy_only"
    assert product["channel_readiness"]["public_transport"]["status"] == "unavailable"


def test_proxy_fields_carry_explicit_non_observed_flags():
    product = build_mobility_accessibility_product(**source_fixture())
    row = product["admin_units"][0]

    assert row["nearest_essential_service_travel_time_min_proxy"] == 12.0
    assert row["network_proxy_not_observed_walk_time"] is True
    assert row["observed_trip_time"] is False
    assert row["policy_outcome_claim"] is False


def test_unavailable_channels_have_no_numeric_value():
    product = build_mobility_accessibility_product(**source_fixture())
    for channel in ("public_transport", "road_safety", "shaded_routes", "universal_accessibility"):
        readiness = product["channel_readiness"][channel]
        assert readiness["status"] == "unavailable"
        assert readiness["value"] is None


def test_missing_source_values_remain_null_not_zero():
    product = build_mobility_accessibility_product(**source_fixture())
    row = next(row for row in product["admin_units"] if row["admin_unit_id"] == "B")

    assert row["nearest_essential_service_distance_m"] is None
    assert row["nearest_essential_service_travel_time_min_proxy"] is None
    assert row["service_accessibility_score"] is None


def test_product_is_input_order_independent_and_does_not_mutate_sources():
    sources = source_fixture()
    before = deepcopy(sources)
    first = build_mobility_accessibility_product(**sources)
    sources["surface"]["admin_service_rows"].reverse()
    second = build_mobility_accessibility_product(**sources)

    assert first["product_digest"] == second["product_digest"]
    assert before["mobility_graph"] == sources["mobility_graph"]


def test_invalid_source_schemas_fail_closed():
    sources = source_fixture()
    sources["surface"]["schema"] = "wrong"
    with pytest.raises(ValueError, match="invalid_accessibility_surface_schema"):
        build_mobility_accessibility_product(**sources)
