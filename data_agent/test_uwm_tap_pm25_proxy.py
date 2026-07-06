import zipfile
from pathlib import Path

import pytest

from data_agent.uwm.tap_pm25_proxy import (
    TAP_PM25_PROXY_SCHEMA,
    build_tap_pm25_proxy,
    validate_tap_pm25_proxy,
)


def test_tap_pm25_proxy_joins_gridid_to_lonlat_and_summarizes_periods(tmp_path):
    tap_root = _write_tap_fixture(tmp_path)

    proxy = build_tap_pm25_proxy(
        tap_root=tap_root,
        proxy_id="tap-fixture",
        created_at="2026-07-06T00:00:00Z",
        include_records=True,
        max_records_per_period=10,
    )

    validation = validate_tap_pm25_proxy(proxy)
    assert validation["valid"], validation["errors"]
    assert proxy["schema"] == TAP_PM25_PROXY_SCHEMA
    assert proxy["proxy_id"] == "tap-fixture"
    assert proxy["synthetic_flags"] == [
        {"dataset_id": "tap_pm25_observed_gridded_chongqing_2018_2024", "status": "public_proxy"}
    ]
    assert proxy["empirical_superiority_claim"] is False
    assert proxy["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert "not_policy_intervention_outcome" in proxy["limitations"]

    period = proxy["periods_1km"][0]
    assert period["period_id"] == "chongqing_pm25_2024_07_01_07"
    assert period["year"] == "2024"
    assert period["doy_values"] == ["183", "184"]
    assert period["tile_ids"] == ["074", "075"]
    assert period["pm_file_count"] == 4
    assert period["tile_lonlat_file_count"] == 2
    assert period["join_missing_row_count"] == 0
    assert period["pm25_summary"] == {"count": 8, "min": 10.0, "max": 23.0, "mean": 16.5}
    assert period["joined_extent"] == {
        "lon_min": 103.0,
        "lon_max": 106.1,
        "lat_min": 29.0,
        "lat_max": 29.1,
    }
    assert len(period["sample_records"]) == 8
    assert period["sample_records"][0] == {
        "period_id": "chongqing_pm25_2024_07_01_07",
        "year": "2024",
        "doy": "183",
        "tile_id": "074",
        "grid_id": "1",
        "longitude": 103.0,
        "latitude": 29.0,
        "pm25_ugm3": 10.0,
    }


def test_tap_pm25_proxy_parses_species_zip(tmp_path):
    tap_root = _write_tap_fixture(tmp_path)

    proxy = build_tap_pm25_proxy(
        tap_root=tap_root,
        proxy_id="tap-fixture",
        created_at="2026-07-06T00:00:00Z",
    )

    species = proxy["species_10km"]
    assert species["file_count"] == 2
    assert species["date_values"] == ["20240701", "20240702"]
    assert species["fields"] == ["GridID", "X_Lon", "Y_Lat", "PM2.5", "SO4", "NO3", "NH4", "OM", "BC"]
    assert species["overall_extent"] == {
        "lon_min": 108.75,
        "lon_max": 108.85,
        "lat_min": 28.25,
        "lat_max": 28.35,
    }
    assert species["overall_metrics"]["PM2.5"] == {"count": 4, "min": 15.0, "max": 18.0, "mean": 16.5}
    assert species["first7_metrics"]["BC"] == {"count": 4, "min": 0.5, "max": 0.8, "mean": 0.65}


def test_tap_pm25_proxy_raises_on_missing_lonlat_join(tmp_path):
    tap_root = _write_tap_fixture(tmp_path, omit_lonlat_for_tile="075")

    with pytest.raises(ValueError, match="missing lon/lat tile"):
        build_tap_pm25_proxy(
            tap_root=tap_root,
            proxy_id="tap-fixture",
            created_at="2026-07-06T00:00:00Z",
        )


def _write_tap_fixture(tmp_path: Path, omit_lonlat_for_tile: str | None = None) -> Path:
    tap_root = tmp_path / "tap_uwm"
    downloaded = tap_root / "chongqing_pm25_2024_07_01_07" / "downloaded"
    downloaded.mkdir(parents=True)

    lonlat_by_tile = {
        "074": [
            {"GridID": "1", "Longitude": "103.0", "Latitude": "29.0", "TileID": "74"},
            {"GridID": "2", "Longitude": "103.1", "Latitude": "29.1", "TileID": "74"},
        ],
        "075": [
            {"GridID": "3", "Longitude": "106.0", "Latitude": "29.0", "TileID": "75"},
            {"GridID": "4", "Longitude": "106.1", "Latitude": "29.1", "TileID": "75"},
        ],
    }
    pm25_by_day_tile = {
        ("183", "074"): [("1", "10"), ("2", "11")],
        ("183", "075"): [("3", "12"), ("4", "13")],
        ("184", "074"): [("1", "20"), ("2", "21")],
        ("184", "075"): [("3", "22"), ("4", "23")],
    }
    for tile_id, rows in lonlat_by_tile.items():
        if tile_id == omit_lonlat_for_tile:
            continue
        _write_csv_zip(
            downloaded / f"Tile_{tile_id}_lonlat.csv.zip",
            f"Tile_{tile_id}_lonlat.csv",
            ["Longitude", "Latitude", "GridID", "TileID"],
            rows,
        )
    for (doy, tile_id), pairs in pm25_by_day_tile.items():
        _write_csv_zip(
            downloaded / f"China_PM25_1km_2024_{doy}_{tile_id}.csv.zip",
            f"China_PM25_1km_2024_{doy}_{tile_id}.csv",
            ["GridID", "PM2.5"],
            [{"GridID": grid_id, "PM2.5": value} for grid_id, value in pairs],
        )

    _write_species_zip(tap_root / "d07f3d.zip")
    return tap_root


def _write_species_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        rows_by_name = {
            "20240701_PM25_and_species.csv": [
                ["GridID", "X_Lon", "Y_Lat", "PM2.5", "SO4", "NO3", "NH4", "OM", "BC"],
                ["1", "108.75", "28.25", "15", "1", "2", "3", "4", "0.5"],
                ["2", "108.85", "28.25", "16", "2", "3", "4", "5", "0.6"],
            ],
            "20240702_PM25_and_species.csv": [
                ["GridID", "X_Lon", "Y_Lat", "PM2.5", "SO4", "NO3", "NH4", "OM", "BC"],
                ["1", "108.75", "28.35", "17", "3", "4", "5", "6", "0.7"],
                ["2", "108.85", "28.35", "18", "4", "5", "6", "7", "0.8"],
            ],
        }
        for name, rows in rows_by_name.items():
            handle.writestr(name, "\n".join(",".join(row) for row in rows) + "\n")
        handle.writestr("readme.txt", "fixture")


def _write_csv_zip(path: Path, inner_name: str, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    lines = [",".join(fieldnames)]
    for row in rows:
        lines.append(",".join(str(row.get(field, "")) for field in fieldnames))
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        handle.writestr(inner_name, "\n".join(lines) + "\n")
