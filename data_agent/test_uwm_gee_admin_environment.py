import json

from data_agent.uwm.gee_admin_environment import (
    GEE_ADMIN_ENVIRONMENT_PROXY_SCHEMA,
    build_gee_admin_environment_proxy,
    build_mmfe_state_input_from_gee_admin_environment_proxy,
    write_gee_admin_environment_snapshot,
)


def _sample_payload():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "admin_id": "cq-001",
                    "county": "渝中区",
                    "township": "解放碑街道",
                    "longitude": 106.58,
                    "latitude": 29.56,
                    "temperature_2m": 302.15,
                    "surface_pressure": 97000.0,
                    "u_component_of_wind_10m": 3.0,
                    "v_component_of_wind_10m": 4.0,
                    "total_precipitation_sum": 0.01,
                    "particulate_matter_d_less_than_25_um_surface": 2.0e-8,
                    "total_aerosol_optical_depth_at_550nm_surface": 0.40,
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "admin_id": "cq-002",
                    "county": "江北区",
                    "township": "观音桥街道",
                    "longitude": 106.53,
                    "latitude": 29.58,
                    "temperature_2m": 300.15,
                    "surface_pressure": 96800.0,
                    "u_component_of_wind_10m": 0.0,
                    "v_component_of_wind_10m": 5.0,
                    "total_precipitation_sum": 0.02,
                    "particulate_matter_d_less_than_25_um_surface": 2.8e-8,
                    "total_aerosol_optical_depth_at_550nm_surface": 0.50,
                },
            },
        ],
    }


def test_build_gee_admin_environment_proxy_normalizes_representative_point_samples():
    proxy = build_gee_admin_environment_proxy(
        sampled_payload=_sample_payload(),
        requested_admin_source={
            "dataset_id": "chongqing_township_admin_units_local",
            "feature_count": 2,
        },
        time_range={"start_date": "2024-07-01", "end_date": "2024-07-07"},
        fetched_at="2026-07-05T12:00:00Z",
    )

    assert proxy["schema"] == GEE_ADMIN_ENVIRONMENT_PROXY_SCHEMA
    assert proxy["source_dataset_ids"] == ["gee_admin_environment_chongqing_proxy"]
    assert proxy["admin_feature_count"] == 2
    assert proxy["sampled_admin_count"] == 2
    assert proxy["coverage"]["sampled_admin_share"] == 1.0
    assert proxy["admin_environment_rows"][0]["temperature_2m_mean_c"] == 29.0
    assert proxy["admin_environment_rows"][0]["surface_pressure_hpa"] == 970.0
    assert proxy["admin_environment_rows"][0]["wind_speed_10m_ms"] == 5.0
    assert proxy["admin_environment_rows"][0]["precipitation_total_mm"] == 10.0
    assert proxy["admin_environment_rows"][0]["cams_pm25_ugm3"] == 20.0
    assert proxy["summary"]["temperature_2m_mean_c_avg"] == 28.0
    assert proxy["summary"]["cams_pm25_ugm3_avg"] == 24.0
    assert proxy["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert "representative_point_not_zonal_mean" in proxy["limitations"]
    assert proxy["empirical_superiority_claim"] is False


def test_build_mmfe_state_input_from_gee_admin_environment_proxy_preserves_spatial_proxy_boundary():
    proxy = build_gee_admin_environment_proxy(
        sampled_payload=_sample_payload(),
        requested_admin_source={"dataset_id": "chongqing_township_admin_units_local", "feature_count": 2},
        time_range={"start_date": "2024-07-01", "end_date": "2024-07-07"},
        fetched_at="2026-07-05T12:00:00Z",
    )

    payload = build_mmfe_state_input_from_gee_admin_environment_proxy(
        proxy,
        timestamp="2026-07-05T12:05:00Z",
    )

    assert payload["schema"] == "mmfe.uwm_state_input.v1"
    assert payload["source_product"]["product_id"] == "mmfe-gee-admin-environment-2024-07-01-2024-07-07"
    assert payload["urban_spatial_unit"]["unit_type"] == "admin_representative_point_environment_proxy"
    assert payload["state_components"]["meteorology"]["source_dataset_ids"] == ["gee_admin_environment_chongqing_proxy"]
    assert payload["state_components"]["air_pollution_exposure"]["source_dataset_ids"] == [
        "gee_admin_environment_chongqing_proxy"
    ]
    assert payload["graph_summary"]["relation_type_distribution"]["admin_unit_has_environment_representative_point"] == 2
    assert payload["source_proxy"]["empirical_superiority_claim"] is False
    assert any("representative point" in warning for warning in payload["warnings"])


def test_write_gee_admin_environment_snapshot_persists_proxy_manifest_and_mmfe_boundary(tmp_path):
    manifest = write_gee_admin_environment_snapshot(
        output_dir=tmp_path,
        sampled_payload=_sample_payload(),
        requested_admin_source={"dataset_id": "chongqing_township_admin_units_local", "feature_count": 2},
        time_range={"start_date": "2024-07-01", "end_date": "2024-07-07"},
        fetched_at="2026-07-05T12:00:00Z",
    )

    assert manifest["schema"] == "uwm.public_proxy_snapshot_manifest.v1"
    assert manifest["dataset_id"] == "gee_admin_environment_proxy_snapshot"
    assert manifest["record_counts"] == {"admin_features": 2, "sampled_admin_units": 2}
    assert manifest["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert (tmp_path / "gee_admin_environment_samples_raw.json").exists()
    assert (tmp_path / "gee_admin_environment_proxy.json").exists()
    assert json.loads((tmp_path / "snapshot_manifest.json").read_text(encoding="utf-8")) == manifest
