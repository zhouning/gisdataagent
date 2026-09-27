from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, box


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "deploy/abu-dhabi-gis-preprocess/source_adapters.py"
spec = importlib.util.spec_from_file_location("gis_preprocess_source_adapters", ADAPTER_PATH)
adapters = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = adapters
assert spec.loader is not None
spec.loader.exec_module(adapters)


def test_pump_station_adapter_writes_private_normalized_contract(tmp_path: Path):
    source = tmp_path / "pumps.gpkg"
    gpd.GeoDataFrame(
        {
            "PUMP_STATION_ID": ["PS-1"],
            "UNITID": ["P-1"],
            "FLOW_RATE": [2.5],
            "TOTAL_CAPACITY": [12.0],
            "STATUS": ["ACTIVE"],
        },
        geometry=[Point(54.4, 24.4)],
        crs="EPSG:4326",
    ).to_file(source, layer="pumps", driver="GPKG")

    manifest = adapters.compile_pump_stations(
        source,
        output_root=tmp_path / "out",
        layer="pumps",
        flow_unit="m3/s",
        capacity_unit="m3",
    )
    normalized = gpd.read_parquet(tmp_path / "out/pump_stations.private.geoparquet")

    assert manifest["admission"]["source_contract_admitted"] is True
    assert manifest["admission"]["model_input_admitted"] is False
    assert manifest["output"]["record_count"] == 1
    assert normalized.crs.to_epsg() == 32640
    assert normalized.loc[0, "flow_rate"] == 2.5
    assert "PUMP_STATION_ID" not in normalized.columns
    assert (tmp_path / "out/pump_stations_compile_manifest.json").is_file()


def test_tide_adapter_normalizes_timezone_and_fails_closed_on_missing_datum(tmp_path: Path):
    source = tmp_path / "tide.csv"
    pd.DataFrame(
        {
            "station": ["A", "A"],
            "observed_at": ["2026-01-01 00:00", "2026-01-01 01:00"],
            "stage": [1.2, 1.4],
        }
    ).to_csv(source, index=False)

    manifest = adapters.compile_tide_boundaries(
        source,
        output_root=tmp_path / "out",
        timestamp_field="observed_at",
        value_field="stage",
        boundary_field="station",
        timezone="Asia/Dubai",
        value_unit="m",
    )
    normalized = pd.read_parquet(tmp_path / "out/tide_boundaries.private.parquet")

    assert manifest["admission"]["source_contract_admitted"] is False
    assert normalized.loc[0, "timestamp_utc"].isoformat() == "2025-12-31T20:00:00+00:00"
    assert manifest["quality"]["monotonic_by_boundary"] is True


def test_tide_adapter_rejects_invalid_values_and_duplicate_timestamps(tmp_path: Path):
    source = tmp_path / "tide.csv"
    pd.DataFrame(
        {
            "time": ["2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"],
            "stage": [1.0, "bad"],
        }
    ).to_csv(source, index=False)

    with pytest.raises(ValueError, match="tide_invalid_timestamp_or_value_count:1"):
        adapters.compile_tide_boundaries(
            source,
            output_root=tmp_path / "out",
            timestamp_field="time",
            value_field="stage",
            value_unit="m",
            vertical_datum="CD",
        )


def test_land_use_adapter_reprojects_validates_and_keeps_model_admission_closed(tmp_path: Path):
    source = tmp_path / "land.gpkg"
    gpd.GeoDataFrame(
        {"code": ["R1"], "class_name": ["residential"], "imperv": [0.65]},
        geometry=[box(54.0, 24.0, 54.001, 24.001)],
        crs="EPSG:4326",
    ).to_file(source, layer="land", driver="GPKG")

    manifest = adapters.compile_land_use(
        source,
        output_root=tmp_path / "out",
        layer="land",
        class_field="class_name",
        code_field="code",
        imperviousness_field="imperv",
    )
    normalized = gpd.read_parquet(tmp_path / "out/land_use.private.geoparquet")

    assert manifest["admission"]["source_contract_admitted"] is True
    assert manifest["admission"]["model_input_admitted"] is False
    assert normalized.crs.to_epsg() == 32640
    assert normalized.loc[0, "area_m2"] > 0
    assert normalized.loc[0, "imperviousness"] == 0.65
    serialized = json.dumps(manifest)
    assert str(tmp_path) not in serialized


def test_land_use_adapter_rejects_unknown_class_and_bad_source_crs(tmp_path: Path):
    source = tmp_path / "land.gpkg"
    gpd.GeoDataFrame(
        {"x": [1]}, geometry=[box(0, 0, 1, 1)], crs="EPSG:4326"
    ).to_file(source, layer="land", driver="GPKG")

    with pytest.raises(ValueError, match="land_use_class_or_code_field_required"):
        adapters.compile_land_use(source, output_root=tmp_path / "out", layer="land")
