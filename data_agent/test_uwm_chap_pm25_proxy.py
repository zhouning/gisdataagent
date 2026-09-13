import json

import h5py

from data_agent.uwm.chap_pm25_proxy import (
    CHAP_PM25_ADMIN_PROXY_SCHEMA,
    build_chap_pm25_admin_proxy,
    write_chap_pm25_admin_proxy_snapshot,
)


def _write_fixture_chap(path):
    with h5py.File(path, "w") as handle:
        pm25 = handle.create_dataset(
            "PM2.5",
            data=[
                [100, 65535, 300],
                [400, 500, 600],
                [700, 800, 900],
            ],
        )
        pm25.attrs["_FillValue"] = [65535]
        pm25.attrs["scale_factor"] = [0.1]
        pm25.attrs["add_offset"] = [0.0]
        pm25.attrs["units"] = b"ug/m3"
        handle.create_dataset("lat", data=[30.0, 29.0, 28.0])
        handle.create_dataset("lon", data=[106.0, 107.0, 108.0])


def _admin_geojson():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "admin_unit_id": "A",
                    "county": "County A",
                    "township": "Town A",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [105.95, 29.95],
                        [106.05, 29.95],
                        [106.05, 30.05],
                        [105.95, 30.05],
                        [105.95, 29.95],
                    ]],
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "admin_unit_id": "B",
                    "county": "County B",
                    "township": "Town B",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [106.95, 29.95],
                        [107.05, 29.95],
                        [107.05, 30.05],
                        [106.95, 30.05],
                        [106.95, 29.95],
                    ]],
                },
            },
        ],
    }


def test_build_chap_pm25_admin_proxy_samples_scale_factor_and_fill_value(tmp_path):
    nc_path = tmp_path / "CHAP_PM2.5_M1K_202407_V4.nc"
    _write_fixture_chap(nc_path)

    proxy = build_chap_pm25_admin_proxy(
        nc_path=nc_path,
        admin_geojson=_admin_geojson(),
        selected_admin_ids={"A", "B"},
        fetched_at="2026-07-05T10:00:00Z",
    )

    assert proxy["schema"] == CHAP_PM25_ADMIN_PROXY_SCHEMA
    assert proxy["source_dataset_ids"] == ["chap_pm25_monthly_1km_2024_07_proxy"]
    assert proxy["record_counts"] == {
        "requested_admin_units": 2,
        "sampled_admin_units": 2,
        "valid_pm25_admin_units": 1,
        "missing_pm25_admin_units": 1,
    }
    assert proxy["admin_pm25_rows"][0]["pm25_ugm3"] == 10.0
    assert proxy["admin_pm25_rows"][1]["pm25_ugm3"] is None
    assert proxy["summary"]["pm25_avg_ugm3"] == 10.0
    assert proxy["synthetic_flags"] == [
        {"dataset_id": "chap_pm25_monthly_1km_2024_07_proxy", "status": "public_proxy"}
    ]
    assert proxy["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert "ai_fused_gridded_product_not_station_observation" in proxy["limitations"]
    assert proxy["empirical_superiority_claim"] is False


def test_write_chap_pm25_admin_proxy_snapshot_persists_manifest(tmp_path):
    nc_path = tmp_path / "CHAP_PM2.5_M1K_202407_V4.nc"
    output_dir = tmp_path / "out"
    _write_fixture_chap(nc_path)

    manifest = write_chap_pm25_admin_proxy_snapshot(
        nc_path=nc_path,
        admin_geojson=_admin_geojson(),
        selected_admin_ids={"A"},
        output_dir=output_dir,
        fetched_at="2026-07-05T10:00:00Z",
    )

    assert manifest["schema"] == "uwm.public_proxy_snapshot_manifest.v1"
    assert manifest["dataset_id"] == "chap_pm25_monthly_1km_2024_07_proxy_snapshot"
    assert manifest["record_counts"]["valid_pm25_admin_units"] == 1
    assert (output_dir / "chap_pm25_admin_proxy.json").exists()
    assert json.loads((output_dir / "snapshot_manifest.json").read_text(encoding="utf-8")) == manifest
