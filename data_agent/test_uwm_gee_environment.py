import json

from data_agent.uwm.gee_environment import (
    GEE_ENVIRONMENTAL_PROXY_SCHEMA,
    build_gee_environmental_proxy,
    build_mmfe_state_input_from_gee_environmental_proxy,
    write_gee_environmental_snapshot,
)


def _era5_feature_collection():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "system:time_start": 1719792000000,
                    "temperature_2m": 300.15,
                    "surface_pressure": 97000.0,
                    "u_component_of_wind_10m": 3.0,
                    "v_component_of_wind_10m": 4.0,
                    "total_precipitation": 0.001,
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "system:time_start": 1719795600000,
                    "temperature_2m": 302.15,
                    "surface_pressure": 96800.0,
                    "u_component_of_wind_10m": 0.0,
                    "v_component_of_wind_10m": 5.0,
                    "total_precipitation": 0.002,
                },
            },
        ],
    }


def _cams_feature_collection():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "system:time_start": 1719792000000,
                    "particulate_matter_d_less_than_25_um_surface": 2.0e-8,
                    "total_aerosol_optical_depth_at_550nm_surface": 0.42,
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "system:time_start": 1719795600000,
                    "particulate_matter_d_less_than_25_um_surface": 2.6e-8,
                    "total_aerosol_optical_depth_at_550nm_surface": 0.38,
                },
            },
        ],
    }


def test_build_gee_environmental_proxy_normalizes_era5_and_cams_without_holdout_claim():
    proxy = build_gee_environmental_proxy(
        era5_payload=_era5_feature_collection(),
        cams_payload=_cams_feature_collection(),
        requested_location={"latitude": 29.563, "longitude": 106.551, "label": "Chongqing central"},
        time_range={"start_date": "2024-07-01", "end_date": "2024-07-01"},
        fetched_at="2026-07-05T10:00:00Z",
    )

    assert proxy["schema"] == GEE_ENVIRONMENTAL_PROXY_SCHEMA
    assert proxy["source"] == "Google Earth Engine"
    assert proxy["source_dataset_ids"] == [
        "gee_era5_hourly_chongqing_proxy",
        "gee_cams_nrt_chongqing_proxy",
    ]
    assert proxy["gee_assets"]["era5"] == "ECMWF/ERA5/HOURLY"
    assert proxy["gee_assets"]["cams"] == "ECMWF/CAMS/NRT"
    assert proxy["record_counts"] == {"era5_hourly": 2, "cams_hourly": 2}
    assert proxy["meteorology_summary"]["temperature_2m_mean_avg_c"] == 28.0
    assert proxy["meteorology_summary"]["surface_pressure_avg_hpa"] == 969.0
    assert proxy["meteorology_summary"]["wind_speed_10m_avg_ms"] == 5.0
    assert proxy["meteorology_summary"]["precipitation_total_mm"] == 3.0
    assert proxy["air_pollution_summary"]["cams_pm25_avg_ugm3"] == 23.0
    assert proxy["air_pollution_summary"]["cams_aod550_avg"] == 0.4
    assert proxy["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert "gee_reanalysis_or_model_proxy_not_station_holdout" in proxy["limitations"]
    assert proxy["empirical_superiority_claim"] is False


def test_build_mmfe_state_input_from_gee_environmental_proxy_preserves_proxy_boundary():
    proxy = build_gee_environmental_proxy(
        era5_payload=_era5_feature_collection(),
        cams_payload=_cams_feature_collection(),
        requested_location={"latitude": 29.563, "longitude": 106.551, "label": "Chongqing central"},
        time_range={"start_date": "2024-07-01", "end_date": "2024-07-01"},
        fetched_at="2026-07-05T10:00:00Z",
    )

    payload = build_mmfe_state_input_from_gee_environmental_proxy(
        proxy,
        timestamp="2026-07-05T10:05:00Z",
    )

    assert payload["schema"] == "mmfe.uwm_state_input.v1"
    assert payload["source_product"]["product_id"] == "mmfe-gee-era5-cams-2024-07-01-2024-07-01"
    assert payload["urban_spatial_unit"]["unit_type"] == "gee_point_environmental_proxy"
    assert payload["state_components"]["meteorology"]["source_dataset_ids"] == ["gee_era5_hourly_chongqing_proxy"]
    assert payload["state_components"]["air_pollution_exposure"]["source_dataset_ids"] == [
        "gee_cams_nrt_chongqing_proxy"
    ]
    assert payload["graph_summary"]["relation_type_distribution"]["point_has_era5_hourly_record"] == 2
    assert payload["graph_summary"]["relation_type_distribution"]["point_has_cams_hourly_record"] == 2
    assert payload["native_geometry_contract"]["metadata_complete"] is True
    assert payload["native_geometry_contract"]["complete_role_count"] == 2
    assert payload["native_geometry_contract"]["geometry_types"] == ["point"]
    assert payload["native_geometry_contract"]["observation_semantics"] == ["proxy"]
    assert (
        payload["object_role_registry"][0]["spatial_support"]["support_type"]
        == "sensor_footprint"
    )
    assert payload["source_proxy"]["empirical_superiority_claim"] is False
    assert any("GEE ERA5/CAMS proxy is not observed station holdout" in warning for warning in payload["warnings"])


def test_write_gee_environmental_snapshot_persists_no_credentials(tmp_path):
    manifest = write_gee_environmental_snapshot(
        output_dir=tmp_path,
        era5_payload=_era5_feature_collection(),
        cams_payload=_cams_feature_collection(),
        requested_location={"latitude": 29.563, "longitude": 106.551, "label": "Chongqing central"},
        time_range={"start_date": "2024-07-01", "end_date": "2024-07-01"},
        fetched_at="2026-07-05T10:00:00Z",
    )

    assert manifest["schema"] == "uwm.public_proxy_snapshot_manifest.v1"
    assert manifest["dataset_id"] == "gee_era5_cams_environmental_proxy_snapshot"
    assert manifest["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert (tmp_path / "gee_era5_hourly_raw.json").exists()
    assert (tmp_path / "gee_cams_nrt_raw.json").exists()
    assert (tmp_path / "gee_era5_cams_environmental_proxy.json").exists()
    assert json.loads((tmp_path / "snapshot_manifest.json").read_text(encoding="utf-8")) == manifest
    serialized = "\n".join(path.read_text(encoding="utf-8") for path in tmp_path.iterdir() if path.is_file())
    assert "X-API-Key" not in serialized
    assert "OPENAQ_TEST_SECRET_SHOULD_NOT_APPEAR" not in serialized
