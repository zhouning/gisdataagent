from __future__ import annotations

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, box

from data_agent.planning_monitoring import (
    MonitoringConfig,
    discover_materialized_inputs,
    run_monitoring_evaluation,
)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _target(path: Path, name: str) -> dict[str, object]:
    return {
        "target_path": str(path),
        "target_name": name,
        "target_id": f"target:{name}",
        "source_asset_id": f"asset:{name}",
        "target_sha256": _hash(path),
        "execution_status": "succeeded",
    }


def _make_fixture(tmp_path: Path, *, include_optional: bool = True) -> Path:
    crs = "EPSG:4326"
    buildings = gpd.GeoDataFrame(
        {"Id": [1, 2, 3, 4], "Floor": [2, 4, 6, 8]},
        geometry=[
            box(106.50, 29.50, 106.52, 29.52),
            box(106.53, 29.50, 106.55, 29.52),
            box(106.50, 29.55, 106.52, 29.57),
            box(106.53, 29.55, 106.55, 29.57),
        ],
        crs=crs,
    )
    building_path = tmp_path / "buildings.parquet"
    buildings.to_parquet(building_path, index=False)
    outputs: list[dict[str, object]] = [_target(building_path, "中心城区建筑数据带层高")]
    if include_optional:
        poi = gpd.GeoDataFrame(
            geometry=[Point(106.51, 29.51), Point(106.54, 29.56), Point(106.54, 29.56)],
            crs=crs,
        )
        poi_path = tmp_path / "poi.parquet"
        poi.to_parquet(poi_path, index=False)
        roads = gpd.GeoDataFrame(
            geometry=[LineString([(106.49, 29.49), (106.56, 29.58)])], crs=crs
        )
        road_path = tmp_path / "roads.parquet"
        roads.to_parquet(road_path, index=False)
        outputs.extend(
            [_target(poi_path, "高德地图POI数据2024年"), _target(road_path, "OSM_roads")]
        )

        transform = from_origin(106.4, 29.7, 0.002, 0.002)
        for filename, values in (
            ("CLCD_test.tif", np.ones((150, 150), dtype="uint8") * 8),
            ("test_DEM.tif", np.arange(150 * 150, dtype="int16").reshape(150, 150)),
        ):
            path = tmp_path / filename
            with rasterio.open(
                path,
                "w",
                driver="GTiff",
                width=150,
                height=150,
                count=1,
                dtype=values.dtype,
                crs=crs,
                transform=transform,
                nodata=15 if values.dtype == np.dtype("uint8") else -9999,
            ) as dataset:
                dataset.write(values, 1)
            outputs.append(_target(path, filename))
    materialization = tmp_path / "materialization.json"
    materialization.write_text(
        json.dumps({"outputs": outputs}, ensure_ascii=False), encoding="utf-8"
    )
    return materialization


def test_discovery_maps_governed_targets_to_roles(tmp_path):
    materialization = _make_fixture(tmp_path)
    inputs = discover_materialized_inputs(materialization)
    assert set(inputs["roles"]) == {"building", "poi", "road", "land_cover", "dem"}


def test_model_writes_metrics_quality_and_lineage(tmp_path):
    materialization = _make_fixture(tmp_path)
    output = tmp_path / "model"
    report = run_monitoring_evaluation(
        materialization,
        output,
        config=MonitoringConfig(cell_size_m=5000, analysis_crs="EPSG:32648"),
    )
    assert report["status"] == "pass"
    assert report["unit_count"] >= 1
    assert report["production_eligible"] is False
    assert (output / "spatial_units.parquet").is_file()
    assert (output / "spatial_units.geojson").is_file()
    assert (output / "indicators.csv").is_file()
    assert len(json.loads((output / "lineage.json").read_text())["edges"]) == 8
    quality = json.loads((output / "quality_report.json").read_text())
    assert quality["checks"]["input_hashes"]["building"] is True


def test_missing_optional_sources_is_review_and_does_not_fake_zero(tmp_path):
    materialization = _make_fixture(tmp_path, include_optional=False)
    output = tmp_path / "model"
    report = run_monitoring_evaluation(
        materialization,
        output,
        config=MonitoringConfig(cell_size_m=5000, analysis_crs="EPSG:32648"),
    )
    assert report["status"] == "succeeded_with_review"
    assert set(report["role_quality"]) == {"building"}
    row = gpd.read_parquet(output / "spatial_units.parquet").iloc[0]
    assert np.isnan(row["poi_count"])
