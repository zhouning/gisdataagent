from data_agent.uwm.admin_service_accessibility import (
    UWM_ADMIN_SERVICE_ACCESSIBILITY_PANEL_SCHEMA,
    build_admin_service_accessibility_panel,
    validate_admin_service_accessibility_panel,
)


def _admin_features():
    return [
        {
            "type": "Feature",
            "properties": {"admin_unit_id": "A|one|0", "county": "A", "township": "one"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[106.50, 29.50], [106.55, 29.50], [106.55, 29.55], [106.50, 29.55], [106.50, 29.50]]],
            },
        },
        {
            "type": "Feature",
            "properties": {"admin_unit_id": "B|two|1", "county": "B", "township": "two"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[106.56, 29.50], [106.60, 29.50], [106.60, 29.55], [106.56, 29.55], [106.56, 29.50]]],
            },
        },
        {
            "type": "Feature",
            "properties": {"admin_unit_id": "C|three|2", "county": "C", "township": "three"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[107.00, 30.00], [107.10, 30.00], [107.10, 30.10], [107.00, 30.10], [107.00, 30.00]]],
            },
        },
    ]


def _service_proxy():
    return {
        "schema": "uwm.osm_service_accessibility_proxy.v1",
        "requested_bbox": [29.49, 106.49, 29.56, 106.61],
        "service_points": [
            {
                "osm_id": 1,
                "latitude": 29.52,
                "longitude": 106.52,
                "amenity": "hospital",
                "service_category": "healthcare",
            },
            {
                "osm_id": 2,
                "latitude": 29.53,
                "longitude": 106.53,
                "amenity": "school",
                "service_category": "education",
            },
            {
                "osm_id": 3,
                "latitude": 29.52,
                "longitude": 106.57,
                "amenity": "restaurant",
                "service_category": "food_retail",
            },
        ],
        "limitations": ["overpass_bbox_extract_not_full_municipality"],
    }


def test_build_admin_service_accessibility_panel_counts_points_only_for_bbox_admins():
    panel = build_admin_service_accessibility_panel(
        admin_features=_admin_features(),
        service_proxy=_service_proxy(),
        panel_id="admin-service-test",
        created_at="2026-07-05T14:30:00Z",
    )

    validation = validate_admin_service_accessibility_panel(panel)
    assert validation["valid"], validation["errors"]
    assert panel["schema"] == UWM_ADMIN_SERVICE_ACCESSIBILITY_PANEL_SCHEMA
    assert panel["bbox_admin_count"] == 2
    assert panel["admin_units_with_service_points"] == 2
    assert panel["service_point_count"] == 3
    assert panel["admin_service_rows"][0]["admin_unit_id"] == "A|one|0"
    assert panel["admin_service_rows"][0]["service_point_count"] == 2
    assert panel["admin_service_rows"][0]["essential_service_count"] == 2
    assert panel["admin_service_rows"][1]["admin_unit_id"] == "B|two|1"
    assert panel["admin_service_rows"][1]["food_retail_count"] == 1
    assert "bbox_limited_sample_gap_not_true_absence" in panel["limitations"]
    assert panel["empirical_superiority_claim"] is False


def test_admin_service_accessibility_panel_marks_bbox_admin_with_no_points_as_sample_gap():
    proxy = _service_proxy()
    proxy["service_points"] = proxy["service_points"][:1]

    panel = build_admin_service_accessibility_panel(
        admin_features=_admin_features(),
        service_proxy=proxy,
        panel_id="admin-service-gap-test",
        created_at="2026-07-05T14:30:00Z",
    )

    row_b = [row for row in panel["admin_service_rows"] if row["admin_unit_id"] == "B|two|1"][0]
    assert row_b["service_point_count"] == 0
    assert row_b["sample_gap_flag"] == "no_osm_points_in_bbox_sample"
    assert row_b["interpretable_as_true_service_absence"] is False
