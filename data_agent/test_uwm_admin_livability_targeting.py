from data_agent.uwm.admin_livability_targeting import (
    UWM_ADMIN_LIVABILITY_TARGET_PANEL_SCHEMA,
    build_admin_livability_target_panel,
    validate_admin_livability_target_panel,
)


def test_build_admin_livability_target_panel_combines_exposure_and_service_sample_gap():
    exposure_panel = {
        "schema": "uwm.admin_exposure_equity_panel.v1",
        "admin_exposure_equity_rows": [
            {
                "admin_unit_id": "A|one|0",
                "county": "A",
                "township": "one",
                "priority_score": 0.9,
                "priority_flags": ["high_pm25_proxy"],
            },
            {
                "admin_unit_id": "B|two|1",
                "county": "B",
                "township": "two",
                "priority_score": 0.5,
                "priority_flags": [],
            },
        ],
        "claim_boundary": {"max_claim_level": "bounded_support"},
    }
    service_panel = {
        "schema": "uwm.admin_service_accessibility_panel.v1",
        "admin_service_rows": [
            {
                "admin_unit_id": "A|one|0",
                "service_point_count": 0,
                "essential_service_count": 0,
                "sample_gap_flag": "no_osm_points_in_bbox_sample",
                "interpretable_as_true_service_absence": False,
            },
            {
                "admin_unit_id": "B|two|1",
                "service_point_count": 8,
                "essential_service_count": 2,
                "sample_gap_flag": "",
                "interpretable_as_true_service_absence": None,
            },
        ],
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "limitations": ["bbox_limited_sample_gap_not_true_absence"],
    }

    panel = build_admin_livability_target_panel(
        exposure_equity_panel=exposure_panel,
        admin_service_panel=service_panel,
        panel_id="uwm-admin-livability-target-test",
        created_at="2026-07-05T15:00:00Z",
    )

    validation = validate_admin_livability_target_panel(panel)
    assert validation["valid"], validation["errors"]
    assert panel["schema"] == UWM_ADMIN_LIVABILITY_TARGET_PANEL_SCHEMA
    assert panel["joined_admin_count"] == 2
    assert panel["target_units"][0]["admin_unit_id"] == "A|one|0"
    assert panel["target_units"][0]["livability_need_score"] == 1.0
    assert panel["target_units"][0]["target_candidate"] is True
    assert panel["target_units"][0]["target_flags"] == [
        "high_exposure_priority",
        "service_sample_gap",
        "low_essential_service_sample",
        "composite_livability_target",
    ]
    assert "bbox_limited_sample_gap_not_true_absence" in panel["limitations"]
    assert panel["empirical_superiority_claim"] is False


def test_full_admin_livability_target_panel_preserves_exposure_rows_without_service_matches():
    exposure_panel = {
        "schema": "uwm.admin_exposure_equity_panel.v1",
        "admin_exposure_equity_rows": [
            {
                "admin_unit_id": "A|one|0",
                "county": "A",
                "township": "one",
                "priority_score": 0.9,
                "priority_flags": ["high_pm25_proxy"],
            },
            {
                "admin_unit_id": "B|two|1",
                "county": "B",
                "township": "two",
                "priority_score": 0.5,
                "priority_flags": [],
            },
            {
                "admin_unit_id": "C|three|2",
                "county": "C",
                "township": "three",
                "priority_score": 0.2,
                "priority_flags": [],
            },
        ],
        "claim_boundary": {"max_claim_level": "bounded_support"},
    }
    service_panel = {
        "schema": "uwm.admin_service_accessibility_panel.v1",
        "admin_service_rows": [
            {
                "admin_unit_id": "A|one|0",
                "service_point_count": 3,
                "essential_service_count": 1,
                "sample_gap_flag": "",
                "interpretable_as_true_service_absence": False,
            }
        ],
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "limitations": ["service_panel_partial_bbox_extract"],
    }

    panel = build_admin_livability_target_panel(
        exposure_equity_panel=exposure_panel,
        admin_service_panel=service_panel,
        panel_id="uwm-admin-livability-full-test",
        created_at="2026-07-08T10:00:00Z",
    )

    validation = validate_admin_livability_target_panel(panel)
    assert validation["valid"], validation["errors"]
    assert panel["experiment_scope"] == "full_admin_graph"
    assert panel["source_admin_count"] == 3
    assert panel["joined_admin_count"] == 3
    assert panel["service_matched_admin_count"] == 1
    assert panel["service_missing_admin_count"] == 2

    rows_by_id = {
        row["admin_unit_id"]: row for row in panel["admin_livability_target_rows"]
    }
    assert rows_by_id["B|two|1"]["service_coverage_status"] == "missing_service_proxy"
    assert rows_by_id["B|two|1"]["sample_gap_flag"] == (
        "service_data_missing_for_admin_unit"
    )
    assert rows_by_id["B|two|1"]["interpretable_as_true_service_absence"] is False
    assert "partial_service_panel_retained_as_missing_not_dropped" in panel["limitations"]


def test_full_admin_livability_target_panel_uses_full_service_surface_without_sample_gap_limitations():
    exposure_panel = {
        "schema": "uwm.admin_exposure_equity_panel.v1",
        "admin_exposure_equity_rows": [
            {
                "admin_unit_id": "A|one|0",
                "county": "A",
                "township": "one",
                "priority_score": 0.9,
                "priority_flags": ["high_pm25_proxy"],
            },
            {
                "admin_unit_id": "B|two|1",
                "county": "B",
                "township": "two",
                "priority_score": 0.4,
                "priority_flags": [],
            },
        ],
        "claim_boundary": {"max_claim_level": "bounded_support"},
    }
    service_surface = {
        "schema": "uwm.full_admin_service_accessibility_surface.v1",
        "source_dataset_ids": [
            "chongqing_township_admin_units_local",
            "gaode_poi_2024",
            "chongqing_osm_roads_2021",
        ],
        "admin_unit_count": 2,
        "coverage": {
            "service_missing_admin_count": 0,
            "admin_units_with_accessibility_score": 2,
            "admin_units_with_road_context": 2,
        },
        "admin_service_rows": [
            {
                "admin_unit_id": "A|one|0",
                "service_point_count": 10,
                "essential_service_count": 3,
                "service_accessibility_score": 0.82,
                "service_gap_score": 0.18,
                "nearest_essential_service_distance_m": 150.0,
                "estimated_nearest_essential_travel_time_min": 0.4,
                "road_segment_count": 6,
                "road_length_km": 3.2,
                "mean_road_speed_kmh": 35.0,
                "sample_gap_flag": "",
                "interpretable_as_true_service_absence": False,
                "service_coverage_status": "covered_by_full_local_surface",
            },
            {
                "admin_unit_id": "B|two|1",
                "service_point_count": 2,
                "essential_service_count": 0,
                "service_accessibility_score": 0.11,
                "service_gap_score": 0.89,
                "nearest_essential_service_distance_m": 2100.0,
                "estimated_nearest_essential_travel_time_min": 5.4,
                "road_segment_count": 1,
                "road_length_km": 0.5,
                "mean_road_speed_kmh": 20.0,
                "sample_gap_flag": "",
                "interpretable_as_true_service_absence": False,
                "service_coverage_status": "covered_by_full_local_surface",
            },
        ],
        "supported_claim": (
            "full_admin_service_accessibility_surface_covers_all_admin_units_from_local_poi_and_road_assets"
        ),
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "limitations": [
            "nearest_service_travel_time_is_network_proxy_not_measured_trip_time"
        ],
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }

    panel = build_admin_livability_target_panel(
        exposure_equity_panel=exposure_panel,
        admin_service_panel=service_surface,
        panel_id="uwm-admin-livability-full-surface-test",
        created_at="2026-07-08T16:00:00Z",
    )

    validation = validate_admin_livability_target_panel(panel)
    assert validation["valid"], validation["errors"]
    assert "full_admin_service_accessibility_surface_2026_07_08" in panel["source_dataset_ids"]
    assert panel["service_matched_admin_count"] == 2
    assert panel["service_missing_admin_count"] == 0
    assert panel["summary"]["service_sample_gap_count"] == 0
    assert "partial_service_panel_retained_as_missing_not_dropped" not in panel["limitations"]
    assert "service_sample_gap_not_true_absence" not in panel["limitations"]
    assert "service_accessibility_surface_is_proxy_not_observed_travel_time" in panel["limitations"]

    rows_by_id = {
        row["admin_unit_id"]: row for row in panel["admin_livability_target_rows"]
    }
    assert rows_by_id["B|two|1"]["service_coverage_status"] == "covered_by_full_local_surface"
    assert rows_by_id["B|two|1"]["service_accessibility_score"] == 0.11
    assert rows_by_id["B|two|1"]["service_gap_score"] == 0.89
    assert rows_by_id["B|two|1"]["estimated_nearest_essential_travel_time_min"] == 5.4
    assert rows_by_id["B|two|1"]["road_segment_count"] == 1
    assert rows_by_id["B|two|1"]["score_components"]["service_gap_norm"] == 0.89
