from data_agent.uwm.data_acquisition import (
    UWM_PUBLIC_SOURCE_REGISTRY,
    build_uwm_public_data_acquisition_plan,
    summarize_acquisition_blockers,
)
from data_agent.uwm.data_foundation import audit_uwm_data_foundation_manifest


def test_public_data_acquisition_plan_marks_credentials_and_downloadability():
    plan = build_uwm_public_data_acquisition_plan(
        requested_roles=["meteorology", "air_pollution_exposure", "population_vulnerability", "service_accessibility"]
    )

    assert plan["schema"] == "uwm.public_data_acquisition_plan.v1"
    assert plan["roles"]["meteorology"]["preferred_source"] == "era5_meteorology_chongqing"
    assert plan["roles"]["meteorology"]["status"] == "downloadable_public"
    assert plan["sources"]["era5_meteorology_chongqing"]["status"] == "downloadable_via_gee_authenticated"
    assert plan["sources"]["cams_air_pollution_proxy"]["status"] == "downloadable_via_gee_authenticated"
    assert plan["sources"]["openaq_air_quality_proxy"]["status"] == "downloadable_with_runtime_secret"
    assert "openmeteo_weather_current_proxy" in plan["roles"]["meteorology"]["candidate_sources"]
    assert "openmeteo_weather_historical_point_proxy" in plan["roles"]["meteorology"]["candidate_sources"]
    assert plan["roles"]["air_pollution_exposure"]["status"] == "requires_source_choice"
    assert "cams_air_pollution_proxy" in plan["roles"]["air_pollution_exposure"]["candidate_sources"]
    assert "openaq_air_quality_proxy" in plan["roles"]["air_pollution_exposure"]["candidate_sources"]
    assert "openmeteo_air_quality_current_proxy" in plan["roles"]["air_pollution_exposure"]["candidate_sources"]
    assert "openmeteo_air_quality_historical_point_proxy" in plan["roles"]["air_pollution_exposure"]["candidate_sources"]
    assert plan["sources"]["worldpop_population_chongqing_proxy"]["status"] == "downloadable_public"
    assert plan["sources"]["ghsl_population_built_chongqing_proxy"]["status"] == "downloadable_public"
    assert plan["sources"]["osm_services_chongqing_public_proxy"]["status"] == "downloadable_public"


def test_acquisition_blocker_summary_tells_user_what_cannot_be_downloaded_by_us():
    plan = build_uwm_public_data_acquisition_plan(
        requested_roles=["meteorology", "air_pollution_exposure", "population_vulnerability"]
    )

    summary = summarize_acquisition_blockers(plan)

    assert summary["schema"] == "uwm.public_data_acquisition_blockers.v1"
    assert "era5_meteorology_chongqing" not in summary["requires_user_credentials"]
    assert "cams_air_pollution_proxy" not in summary["requires_user_credentials"]
    assert "openaq_air_quality_proxy" not in summary["requires_user_credentials"]
    assert summary["requires_runtime_secrets"] == ["openaq_air_quality_proxy"]
    assert "era5_meteorology_chongqing" in summary["can_attempt_public_download"]
    assert "cams_air_pollution_proxy" in summary["can_attempt_public_download"]
    assert "air_pollution_exposure" in summary["requires_source_decision"]
    assert "openmeteo_weather_current_proxy" in summary["can_attempt_public_download"]
    assert "openmeteo_weather_historical_point_proxy" in summary["can_attempt_public_download"]
    assert "openmeteo_air_quality_current_proxy" in summary["can_attempt_public_download"]
    assert "openmeteo_air_quality_historical_point_proxy" in summary["can_attempt_public_download"]
    assert "worldpop_population_chongqing_proxy" in summary["can_attempt_public_download"]
    assert "ghsl_population_built_chongqing_proxy" in summary["can_attempt_public_download"]
    assert summary["no_silent_substitution"] is True


def test_public_source_registry_keeps_official_urls_and_manifest_mapping():
    assert UWM_PUBLIC_SOURCE_REGISTRY["era5_meteorology_chongqing"]["gee_asset"] == "ECMWF/ERA5/HOURLY"
    assert UWM_PUBLIC_SOURCE_REGISTRY["cams_air_pollution_proxy"]["gee_asset"] == "ECMWF/CAMS/NRT"
    assert UWM_PUBLIC_SOURCE_REGISTRY["era5_meteorology_chongqing"]["official_url"].startswith("https://developers.google.com/earth-engine/datasets/catalog/ECMWF_ERA5_HOURLY")
    assert UWM_PUBLIC_SOURCE_REGISTRY["cams_air_pollution_proxy"]["manifest_dataset_id"] == "cams_air_pollution_proxy"
    assert UWM_PUBLIC_SOURCE_REGISTRY["worldpop_population_chongqing_proxy"]["manifest_dataset_id"] == (
        "worldpop_population_chongqing_proxy"
    )
    assert UWM_PUBLIC_SOURCE_REGISTRY["openmeteo_weather_current_proxy"]["current_fields"] == [
        "temperature_2m",
        "relative_humidity_2m",
        "precipitation",
        "surface_pressure",
        "wind_speed_10m",
    ]
    assert UWM_PUBLIC_SOURCE_REGISTRY["openmeteo_air_quality_current_proxy"]["current_fields"] == [
        "pm10",
        "pm2_5",
        "carbon_monoxide",
        "nitrogen_dioxide",
        "sulphur_dioxide",
        "ozone",
    ]
    assert UWM_PUBLIC_SOURCE_REGISTRY["openmeteo_weather_historical_point_proxy"]["history_fields"]["daily"] == [
        "temperature_2m_mean",
        "precipitation_sum",
        "wind_speed_10m_max",
    ]


def test_registered_public_sources_are_present_in_manifest():
    audit = audit_uwm_data_foundation_manifest("docs/reports/uwm_data_foundation_manifest.csv")
    manifest_dataset_ids = {
        dataset_id
        for coverage in audit["role_coverage"].values()
        for dataset_id in coverage["dataset_ids"]
    }

    assert {
        source["manifest_dataset_id"]
        for source in UWM_PUBLIC_SOURCE_REGISTRY.values()
    }.issubset(manifest_dataset_ids)
