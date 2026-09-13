from data_agent.uwm.admin_exposure_equity import (
    UWM_ADMIN_EXPOSURE_EQUITY_PANEL_SCHEMA,
    build_admin_exposure_equity_panel,
    validate_admin_exposure_equity_panel,
)


def test_build_admin_exposure_equity_panel_joins_population_and_environment_for_targets():
    ghsl_rows = [
        {
            "admin_unit_id": "A|one|0",
            "county": "A",
            "township": "one",
            "feature_index": "0",
            "population_proxy_sum": "100",
            "built_surface_proxy_sum": "200",
        },
        {
            "admin_unit_id": "B|two|1",
            "county": "B",
            "township": "two",
            "feature_index": "1",
            "population_proxy_sum": "1000",
            "built_surface_proxy_sum": "900",
        },
        {
            "admin_unit_id": "C|three|2",
            "county": "C",
            "township": "three",
            "feature_index": "2",
            "population_proxy_sum": "500",
            "built_surface_proxy_sum": "300",
        },
    ]
    admin_environment_proxy = {
        "schema": "uwm.gee_admin_environment_proxy.v1",
        "source_dataset_ids": ["gee_admin_environment_chongqing_proxy"],
        "time_range": {"start_date": "2024-07-01", "end_date": "2024-07-07"},
        "admin_environment_rows": [
            {"admin_id": "cq-admin-0000", "temperature_2m_mean_c": 27.0, "cams_pm25_ugm3": 15.0},
            {"admin_id": "cq-admin-0001", "temperature_2m_mean_c": 31.0, "cams_pm25_ugm3": 35.0},
            {"admin_id": "cq-admin-0002", "temperature_2m_mean_c": 29.0, "cams_pm25_ugm3": 25.0},
        ],
        "limitations": ["representative_point_not_zonal_mean"],
    }

    panel = build_admin_exposure_equity_panel(
        ghsl_zonal_rows=ghsl_rows,
        admin_environment_proxy=admin_environment_proxy,
        panel_id="uwm-admin-equity-test",
        created_at="2026-07-05T12:45:00Z",
    )

    validation = validate_admin_exposure_equity_panel(panel)
    assert validation["valid"], validation["errors"]
    assert panel["schema"] == UWM_ADMIN_EXPOSURE_EQUITY_PANEL_SCHEMA
    assert panel["joined_admin_count"] == 3
    assert panel["summary"]["target_candidate_count"] == 1
    assert panel["admin_exposure_equity_rows"][0]["admin_unit_id"] == "B|two|1"
    assert panel["admin_exposure_equity_rows"][0]["target_candidate"] is True
    assert panel["admin_exposure_equity_rows"][0]["priority_score"] == 1.0
    assert panel["admin_exposure_equity_rows"][0]["priority_flags"] == [
        "high_population_proxy",
        "high_heat_proxy",
        "high_pm25_proxy",
        "target_candidate",
    ]
    assert panel["target_units"][0]["admin_unit_id"] == "B|two|1"
    assert "representative_point_not_zonal_mean" in panel["limitations"]
    assert panel["empirical_superiority_claim"] is False


def test_admin_exposure_equity_panel_still_exports_top_priority_units_when_strict_targets_are_empty():
    ghsl_rows = [
        {
            "admin_unit_id": "A|one|0",
            "county": "A",
            "township": "one",
            "feature_index": "0",
            "population_proxy_sum": "100",
            "built_surface_proxy_sum": "200",
        },
        {
            "admin_unit_id": "B|two|1",
            "county": "B",
            "township": "two",
            "feature_index": "1",
            "population_proxy_sum": "1000",
            "built_surface_proxy_sum": "500",
        },
        {
            "admin_unit_id": "C|three|2",
            "county": "C",
            "township": "three",
            "feature_index": "2",
            "population_proxy_sum": "300",
            "built_surface_proxy_sum": "900",
        },
    ]
    admin_environment_proxy = {
        "schema": "uwm.gee_admin_environment_proxy.v1",
        "time_range": {"start_date": "2024-07-01", "end_date": "2024-07-07"},
        "admin_environment_rows": [
            {"admin_id": "cq-admin-0000", "temperature_2m_mean_c": 27.0, "cams_pm25_ugm3": 35.0},
            {"admin_id": "cq-admin-0001", "temperature_2m_mean_c": 31.0, "cams_pm25_ugm3": 15.0},
            {"admin_id": "cq-admin-0002", "temperature_2m_mean_c": 29.0, "cams_pm25_ugm3": 25.0},
        ],
        "limitations": [],
    }

    panel = build_admin_exposure_equity_panel(
        ghsl_zonal_rows=ghsl_rows,
        admin_environment_proxy=admin_environment_proxy,
        panel_id="uwm-admin-equity-fallback-test",
        created_at="2026-07-05T12:55:00Z",
    )

    assert panel["summary"]["target_candidate_count"] == 0
    assert len(panel["target_units"]) == 3
    assert panel["target_units"][0]["priority_score"] >= panel["target_units"][1]["priority_score"]
    assert panel["target_units"][0]["target_candidate"] is False
    assert "top_priority_proxy_unit" in panel["target_units"][0]["priority_flags"]
