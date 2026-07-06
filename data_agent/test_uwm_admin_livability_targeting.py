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
