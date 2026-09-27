from datetime import datetime
import json
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from data_agent.api import abu_dhabi_flood_routes as flood_routes
from data_agent.abu_dhabi_rainfall_profiles import (
    build_custom_rainfall_series,
    build_rainfall_profile,
    build_solver_forcing_contract,
    build_solver_forcing_package,
    disaggregate_hourly_rainfall_naturally,
    import_rainfall_profile_csv,
    list_saved_rainfall_profiles,
    list_rainfall_profiles,
    load_rainfall_profile,
    rainfall_profile_series,
    save_rainfall_profile,
    spatial_rainfall_preview_geojson,
    validate_spatial_rainfall_zones,
)


def _square():
    return {
        "type": "Polygon",
        "coordinates": [[[54.3, 24.4], [54.4, 24.4], [54.4, 24.5], [54.3, 24.5], [54.3, 24.4]]],
    }


def test_catalog_exposes_zone_b_and_explicit_pending_zone_a():
    catalog = list_rainfall_profiles()
    zones = {item["id"]: item for item in catalog["climate_zones"]}
    assert zones["zone_b"]["status"] == "registered_official_extract"
    assert zones["zone_a"]["status"] == "pending_authoritative_idf_ddf"
    assert len(catalog["profiles"]) == 6


def test_zone_b_official_profile_conserves_depth():
    profile = build_rainfall_profile(
        {
            "climate_zone": "zone_b",
            "temporal_pattern": "official_zone_b_ddf_abm",
            "return_period_years": 10,
            "duration_minutes": 180,
            "interval_minutes": 5,
        }
    )
    assert profile["total_depth_mm"] == pytest.approx(28.71)
    series, stats = rainfall_profile_series(profile, start=datetime(2024, 4, 16))
    assert len(series) == 37
    assert stats["generated_total_depth_mm"] == pytest.approx(28.71)


def test_zone_a_cannot_invent_official_values():
    with pytest.raises(ValueError, match="zone_a_authoritative_idf_ddf_not_available"):
        build_rainfall_profile(
            {
                "climate_zone": "zone_a",
                "temporal_pattern": "official_zone_b_ddf_abm",
                "return_period_years": 10,
                "duration_minutes": 180,
                "interval_minutes": 5,
            }
        )


def test_custom_profile_and_map_zones_are_validated():
    profile = build_rainfall_profile(
        {
            "climate_zone": "zone_a",
            "temporal_pattern": "custom",
            "duration_minutes": 10,
            "interval_minutes": 5,
            "values_mm_per_interval": [2.0, 3.0],
            "spatial_mode": "zones",
            "zones": [{"zone_id": "bateen", "geometry": _square(), "rainfall_factor": 1.35, "priority": 1}],
        }
    )
    assert profile["validation"]["status"] == "ready"
    assert profile["total_depth_mm"] == pytest.approx(5.0)
    assert profile["zones"][0]["rainfall_factor"] == pytest.approx(1.35)


def test_spatial_rainfall_preview_reprojects_utm40_and_keeps_summary_properties():
    preview = spatial_rainfall_preview_geojson(
        [
            {
                "zone_id": "al_bateen_reference",
                "crs": "EPSG:32640",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [231000.0, 2687059.0],
                        [239000.0, 2687059.0],
                        [239000.0, 2723671.0],
                        [231000.0, 2723671.0],
                        [231000.0, 2687059.0],
                    ]],
                },
                "rainfall_factor": 1.0,
                "total_depth_mm": 67.8,
                "values_mm_per_interval": [1.0, 2.0],
            }
        ]
    )
    feature = preview["features"][0]
    lon, lat = feature["geometry"]["coordinates"][0][0]
    assert 54.0 < lon < 55.0
    assert 24.0 < lat < 25.0
    assert feature["properties"]["zone_id"] == "al_bateen_reference"
    assert feature["properties"]["total_depth_mm"] == pytest.approx(67.8)
    assert "values_mm_per_interval" not in feature["properties"]
    assert feature["properties"]["preview_crs"] == "EPSG:4326"


def test_custom_series_converts_mm_interval_to_mm_per_hour():
    series, stats = build_custom_rainfall_series(
        start=datetime(2024, 1, 1), values_mm_per_interval=[1.0, 2.0], interval_minutes=5
    )
    assert [value for _stamp, value in series[:2]] == [12.0, 24.0]
    assert stats["generated_total_depth_mm"] == pytest.approx(3.0)


def test_natural_hourly_disaggregation_is_deterministic_nonflat_and_mass_conserving():
    hourly = [0.0, 1.2, 4.8, 2.4, 0.0]
    values = disaggregate_hourly_rainfall_naturally(hourly, phase_seed=20240415)
    repeated = disaggregate_hourly_rainfall_naturally(hourly, phase_seed=20240415)
    assert values == repeated
    assert len(values) == 60
    for hour_index, hourly_depth in enumerate(hourly):
        block = values[hour_index * 12:(hour_index + 1) * 12]
        assert sum(block) == pytest.approx(hourly_depth, abs=1e-12)
        assert all(value >= 0 for value in block)
        if hourly_depth > 0:
            assert max(block) <= hourly_depth / 12 * 1.6 + 1e-12
    assert len(set(round(value, 10) for value in values[24:36])) > 6
    assert max(values[24:36]) > sum(values[24:36]) / 12


def test_solver_forcing_contract_translates_units_and_marks_commercial_adapter_boundary():
    profile = build_rainfall_profile(
        {
            "climate_zone": "zone_b",
            "temporal_pattern": "custom",
            "duration_minutes": 10,
            "interval_minutes": 5,
            "values_mm_per_interval": [1.0, 2.0],
        }
    )
    anuga = build_solver_forcing_contract(profile, target_solver="anuga")
    commercial = build_solver_forcing_contract(profile, target_solver="commercial")
    assert anuga["temporal_unit"] == "m_per_second"
    assert anuga["temporal_values"][0] == pytest.approx(1.0 / 300.0 / 1000.0)
    assert commercial["temporal_unit"] == "mm_per_hour"
    assert commercial["adapter_status"] == "vendor_adapter_required"


def test_solver_forcing_package_contains_auditable_exchange_files():
    profile = build_rainfall_profile(
        {
            "climate_zone": "zone_b",
            "temporal_pattern": "custom",
            "duration_minutes": 10,
            "interval_minutes": 5,
            "values_mm_per_interval": [1.0, 2.0],
        }
    )
    package = build_solver_forcing_package(profile, target_solver="commercial")
    with ZipFile(BytesIO(package)) as archive:
        assert set(archive.namelist()) == {
            "README.txt",
            "manifest.json",
            "profile.json",
            "rainfall_timeseries.csv",
            "rainfall_zone_timeseries.csv",
            "spatial_zones.geojson",
        }
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["adapter_status"] == "vendor_adapter_required"
        assert "elapsed_minutes,timestamp,forcing_value" in archive.read("rainfall_timeseries.csv").decode("utf-8")


def test_spatial_zones_require_explicit_geometry_and_ids():
    with pytest.raises(ValueError, match="spatial_rainfall_zones_required"):
        validate_spatial_rainfall_zones([], spatial_mode="zones")
    with pytest.raises(ValueError, match="spatial_zone_.*geometry_invalid"):
        validate_spatial_rainfall_zones([{"zone_id": "bad", "rainfall_factor": 1.0}], spatial_mode="zones")


def test_spatial_zone_can_select_an_independent_template_shape():
    profile = build_rainfall_profile(
        {
            "name": "spatial temporal patterns",
            "climate_zone": "zone_b",
            "temporal_pattern": "uniform",
            "duration_minutes": 20,
            "interval_minutes": 5,
            "total_depth_mm": 4.0,
            "spatial_mode": "zones",
            "zones": [
                {
                    "zone_id": "front_peak",
                    "geometry": _square(),
                    "rainfall_factor": 1.5,
                    "temporal_pattern_id": "front_loaded",
                }
            ],
        }
    )
    contract = build_solver_forcing_contract(profile, target_solver="swmm")
    zone = contract["spatial_zone_forcings"][0]
    assert zone["total_depth_mm"] == pytest.approx(6.0)
    assert zone["temporal_pattern_id"] == "front_loaded"
    assert zone["temporal_values"][0] > zone["temporal_values"][-1]


def test_spatial_zone_can_use_independent_custom_five_minute_nodes():
    profile = build_rainfall_profile(
        {
            "name": "spatial custom nodes",
            "climate_zone": "zone_b",
            "temporal_pattern": "uniform",
            "duration_minutes": 20,
            "interval_minutes": 5,
            "total_depth_mm": 4.0,
            "spatial_mode": "zones",
            "zones": [
                {
                    "zone_id": "custom_peak",
                    "geometry": _square(),
                    "rainfall_factor": 2.0,
                    "temporal_pattern_id": "custom",
                    "values_mm_per_interval": [0.0, 1.0, 3.0, 0.0],
                }
            ],
        }
    )
    contract = build_solver_forcing_contract(profile, target_solver="swmm")
    zone = contract["spatial_zone_forcings"][0]
    assert zone["total_depth_mm"] == pytest.approx(8.0)
    assert zone["temporal_values"] == pytest.approx([0.0, 24.0, 72.0, 0.0])


def test_profile_csv_round_trip_uses_elapsed_minutes_and_depth(tmp_path):
    profile = build_rainfall_profile(
        {
            "name": "Al Bateen test profile",
            "climate_zone": "zone_a",
            "temporal_pattern": "custom",
            "duration_minutes": 10,
            "interval_minutes": 5,
            "values_mm_per_interval": [1.0, 2.0],
        }
    )
    saved = save_rainfall_profile(profile, root=tmp_path)
    assert saved["status"] == "saved"
    csv_text = (tmp_path / saved["profile_id"] / "rainfall.csv").read_text(encoding="utf-8")
    assert csv_text.splitlines()[0] == "elapsed_minutes,depth_mm_per_interval"
    imported = import_rainfall_profile_csv(csv_text, metadata={"name": "imported"})
    assert imported["values_mm_per_interval"] == pytest.approx([1.0, 2.0])
    assert imported["duration_minutes"] == 10
    loaded = load_rainfall_profile(saved["profile_id"], root=tmp_path)
    assert loaded["profile_id"] == saved["profile_id"]
    assert loaded["profile_hash_sha256"] == saved["profile_hash_sha256"]
    assert len(list_saved_rainfall_profiles(root=tmp_path)) == 1


def test_profile_csv_accepts_intensity_or_timestamp_but_not_both():
    imported = import_rainfall_profile_csv(
        "timestamp,intensity_mm_per_hour\n"
        "2024-04-16T00:00:00,12\n"
        "2024-04-16T00:05:00,24\n",
        metadata={"climate_zone": "zone_b", "name": "station import"},
    )
    assert imported["values_mm_per_interval"] == pytest.approx([1.0, 2.0])
    with pytest.raises(ValueError, match="rainfall_csv_value_columns_mutually_exclusive"):
        import_rainfall_profile_csv(
            "elapsed_minutes,depth_mm_per_interval,intensity_mm_per_hour\n0,1,12\n5,2,24\n"
        )


def test_saved_profile_id_cannot_be_silently_overwritten_and_hash_is_verified(tmp_path):
    original = {
        "profile_id": "named-profile",
        "name": "immutable",
        "climate_zone": "zone_b",
        "temporal_pattern": "custom",
        "duration_minutes": 10,
        "interval_minutes": 5,
        "values_mm_per_interval": [1.0, 2.0],
    }
    saved = save_rainfall_profile(original, root=tmp_path)
    assert save_rainfall_profile(original, root=tmp_path)["profile_hash_sha256"] == saved["profile_hash_sha256"]
    with pytest.raises(ValueError, match="rainfall_profile_id_conflict"):
        save_rainfall_profile({**original, "values_mm_per_interval": [2.0, 2.0]}, root=tmp_path)
    profile_path = tmp_path / "named-profile" / "profile.json"
    tampered = json.loads(profile_path.read_text(encoding="utf-8"))
    tampered["values_mm_per_interval"] = [9.0, 9.0]
    profile_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="rainfall_profile_persisted_integrity_mismatch"):
        load_rainfall_profile("named-profile", root=tmp_path)


def test_profile_csv_rejects_irregular_or_duplicate_time():
    with pytest.raises(ValueError, match="rainfall_csv_interval_not_regular"):
        import_rainfall_profile_csv(
            "elapsed_minutes,depth_mm_per_interval\n0,1\n5,2\n15,1\n"
        )
    with pytest.raises(ValueError, match="rainfall_csv_duplicate_time"):
        import_rainfall_profile_csv(
            "elapsed_minutes,depth_mm_per_interval\n0,1\n0,2\n"
        )


def test_profile_update_and_delete_are_explicit_and_persistent(tmp_path):
    from data_agent.abu_dhabi_rainfall_profiles import delete_rainfall_profile, update_rainfall_profile

    saved = save_rainfall_profile(
        {
            "profile_id": "crud-profile",
            "name": "before",
            "climate_zone": "zone_b",
            "temporal_pattern": "custom",
            "duration_minutes": 10,
            "interval_minutes": 5,
            "values_mm_per_interval": [1.0, 2.0],
        },
        root=tmp_path,
    )
    updated = update_rainfall_profile(
        saved["profile_id"],
        {
            "name": "after",
            "climate_zone": "zone_b",
            "temporal_pattern": "custom",
            "duration_minutes": 10,
            "interval_minutes": 5,
            "values_mm_per_interval": [2.0, 3.0],
        },
        root=tmp_path,
    )
    assert updated["profile_id"] == saved["profile_id"]
    assert updated["profile_hash_sha256"] != saved["profile_hash_sha256"]
    assert load_rainfall_profile("crud-profile", root=tmp_path)["values_mm_per_interval"] == [2.0, 3.0]
    deleted = delete_rainfall_profile("crud-profile", root=tmp_path)
    assert deleted["deleted"] is True
    with pytest.raises(KeyError, match="rainfall_profile_not_found"):
        load_rainfall_profile("crud-profile", root=tmp_path)


def test_profile_update_rejects_stale_expected_hash(tmp_path):
    from data_agent.abu_dhabi_rainfall_profiles import update_rainfall_profile

    saved = save_rainfall_profile(
        {
            "profile_id": "concurrent-profile",
            "name": "before",
            "climate_zone": "zone_b",
            "temporal_pattern": "custom",
            "duration_minutes": 10,
            "interval_minutes": 5,
            "values_mm_per_interval": [1.0, 2.0],
        },
        root=tmp_path,
    )
    with pytest.raises(ValueError, match="rainfall_profile_conflict"):
        update_rainfall_profile(
            "concurrent-profile",
            {
                "name": "stale update",
                "climate_zone": "zone_b",
                "temporal_pattern": "custom",
                "duration_minutes": 10,
                "interval_minutes": 5,
                "values_mm_per_interval": [2.0, 3.0],
                "expected_profile_hash_sha256": "stale-hash",
            },
            root=tmp_path,
        )


def test_rainfall_profile_persistence_routes_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(
        flood_routes,
        "_get_user_from_request",
        lambda request: SimpleNamespace(identifier="analyst", metadata={"role": "analyst"}),
    )
    monkeypatch.setattr(flood_routes, "_set_user_context", lambda user: None)
    import data_agent.abu_dhabi_rainfall_profiles as rainfall_profiles

    monkeypatch.setattr(rainfall_profiles, "DEFAULT_PROFILE_ROOT", tmp_path)
    app = Starlette(routes=flood_routes.get_abu_dhabi_flood_routes())
    with TestClient(app) as client:
        payload = {
            "name": "API profile",
            "climate_zone": "zone_b",
            "temporal_pattern": "custom",
            "duration_minutes": 10,
            "interval_minutes": 5,
            "values_mm_per_interval": [1.0, 2.0],
        }
        saved = client.post("/api/abu-dhabi/flood/rainfall/profiles", json=payload)
        assert saved.status_code == 201
        profile_id = saved.json()["profile_id"]
        catalog = client.get("/api/abu-dhabi/flood/rainfall/profiles/saved")
        assert catalog.status_code == 200
        assert catalog.json()["profiles"][0]["profile_id"] == profile_id
        loaded = client.get(f"/api/abu-dhabi/flood/rainfall/profiles/{profile_id}")
        assert loaded.status_code == 200
        assert loaded.json()["values_mm_per_interval"] == [1.0, 2.0]
        updated = client.put(
            f"/api/abu-dhabi/flood/rainfall/profiles/{profile_id}",
            json={**payload, "name": "API profile updated", "values_mm_per_interval": [2.0, 3.0]},
        )
        assert updated.status_code == 200
        assert updated.json()["profile_id"] == profile_id
        stale = client.put(
            f"/api/abu-dhabi/flood/rainfall/profiles/{profile_id}",
            json={
                **payload,
                "values_mm_per_interval": [4.0, 5.0],
                "expected_profile_hash_sha256": "stale-hash",
            },
        )
        assert stale.status_code == 409
        assert stale.json()["error"] == "rainfall_profile_conflict"
        assert client.get(f"/api/abu-dhabi/flood/rainfall/profiles/{profile_id}").json()["values_mm_per_interval"] == [2.0, 3.0]
        exported = client.get(f"/api/abu-dhabi/flood/rainfall/profiles/{profile_id}/csv")
        assert exported.status_code == 200
        assert exported.text.startswith("elapsed_minutes,depth_mm_per_interval\n")
        assert "attachment" in exported.headers["content-disposition"]
        imported = client.post(
            "/api/abu-dhabi/flood/rainfall/profiles/import",
            json={"csv": "elapsed_minutes,depth_mm_per_interval\n0,1\n5,2\n"},
        )
        assert imported.status_code == 200
        assert imported.json()["total_depth_mm"] == pytest.approx(3.0)
        spatial_preview = client.post(
            "/api/abu-dhabi/flood/rainfall/spatial-preview",
            json={
                "zones": [{
                    "zone_id": "bateen",
                    "geometry": _square(),
                    "crs": "EPSG:4326",
                    "rainfall_factor": 1.2,
                }]
            },
        )
        assert spatial_preview.status_code == 200
        assert spatial_preview.json()["zone_count"] == 1
        assert spatial_preview.json()["feature_collection"]["features"][0]["properties"]["zone_id"] == "bateen"
        package = client.post(
            "/api/abu-dhabi/flood/rainfall/forcing/package",
            json={"profile": payload, "target_solver": "anuga"},
        )
        assert package.status_code == 200
        assert package.headers["content-type"] == "application/zip"
        assert len(package.headers["x-content-sha256"]) == 64
        deleted = client.delete(f"/api/abu-dhabi/flood/rainfall/profiles/{profile_id}")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
        assert client.get(f"/api/abu-dhabi/flood/rainfall/profiles/{profile_id}").status_code == 404
