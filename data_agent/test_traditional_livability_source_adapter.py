from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point, Polygon

from data_agent.uwm import traditional_livability_source_adapter as adapter


def _write_vector(path: Path, layer: str, rows: list[dict], geometries) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = gpd.GeoDataFrame(rows, geometry=geometries, crs="EPSG:4326")
    frame.to_file(path, layer=layer, driver="GPKG")


def _fixture_specs():
    return (
        {"asset_id": "gaode_poi", "kind": "vector", "relative_path": "poi.gpkg", "layer": "poi", "required": True},
        {"asset_id": "baidu_aoi", "kind": "vector", "relative_path": "aoi.gpkg", "layer": "aoi", "required": True},
        {"asset_id": "admin_population_2021", "kind": "excel", "relative_path": "population.xlsx", "required": True},
        {"asset_id": "osm_roads_2021", "kind": "vector", "relative_path": "roads.gpkg", "layer": "roads", "required": True},
        {"asset_id": "current_land_use", "kind": "vector", "relative_path": "land.gpkg", "layer": "land", "required": True},
    )


def _build_source_root(tmp_path: Path) -> Path:
    _write_vector(
        tmp_path / "poi.gpkg",
        "poi",
        [
            {"ID": 1, "名称": "人民小学", "类型": "科教文化服务;学校;小学", "区域ID": 500103, "经度wgs84": 106.5, "纬度wgs84": 29.5},
            {"ID": 2, "名称": "社区医院", "类型": "医疗保健服务;医院;综合医院", "区域ID": 500103, "经度wgs84": 106.6, "纬度wgs84": 29.6},
        ],
        [Point(106.5, 29.5), Point(106.6, 29.6)],
    )
    _write_vector(
        tmp_path / "aoi.gpkg",
        "aoi",
        [{"uid": "a-1", "名称": "中央公园", "类型": "旅游景点,公园", "第一分类": "旅游景点", "第二分类": "公园", "区县": "渝中区", "经度wgs84": 106.55, "纬度wgs84": 29.55}],
        [Polygon([(106.5, 29.5), (106.6, 29.5), (106.6, 29.6), (106.5, 29.5)])],
    )
    _write_vector(tmp_path / "roads.gpkg", "roads", [{"osm_id": "r1", "fclass": "primary", "oneway": "B", "maxspeed": 40}], [LineString([(106.5, 29.5), (106.6, 29.6)])])
    _write_vector(tmp_path / "land.gpkg", "land", [{"BSM": 9, "DLBM": "0701", "DLMC": "城镇住宅用地", "TBMJ": 1000.0}], [Polygon([(106.4, 29.4), (106.5, 29.4), (106.5, 29.5), (106.4, 29.4)])])
    pd.DataFrame([{"行政区划代码": 500103, "区划名称": "渝中区", "常住人口": 58.8717, "年份": 2021}]).to_excel(tmp_path / "population.xlsx", index=False)
    return tmp_path


def test_inspection_fails_closed_when_required_sources_are_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _fixture_specs())

    manifest = adapter.inspect_traditional_livability_sources(tmp_path)

    assert manifest["schema"] == "uwm.traditional_livability.source_manifest.v1"
    assert manifest["ready"] is False
    assert "missing_required_source:gaode_poi" in manifest["blockers"]
    assert all(not Path(source["relative_path"]).is_absolute() for source in manifest["sources"])


def test_inspects_and_loads_normalized_rows_with_sampling_boundary(tmp_path, monkeypatch):
    root = _build_source_root(tmp_path)
    monkeypatch.setattr(adapter, "ASSET_SPECS", _fixture_specs())

    manifest = adapter.inspect_traditional_livability_sources(root)
    loaded = adapter.load_traditional_livability_source_rows(root, max_poi_features=1)

    assert manifest["ready"] is True
    assert manifest["blockers"] == []
    poi_source = next(row for row in manifest["sources"] if row["asset_id"] == "gaode_poi")
    assert poi_source["relative_path"] == "poi.gpkg"
    assert len(poi_source["sha256"]) == 64
    assert poi_source["feature_count"] == 2
    assert poi_source["crs"] == "EPSG:4326"
    assert "类型" in poi_source["fields"]

    assert loaded["manifest"]["complete_inventory"] is False
    assert loaded["manifest"]["sampling"]["max_poi_features"] == 1
    assert loaded["poi_rows"] == [
        {
            "source_record_id": "1",
            "source_dataset_id": "gaode_poi",
            "name": "人民小学",
            "raw_primary_class": "科教文化服务",
            "raw_secondary_class": "学校",
            "raw_tertiary_class": "小学",
            "admin_code": "500103",
            "longitude": 106.5,
            "latitude": 29.5,
            "geometry_type": "Point",
        }
    ]
    assert loaded["aoi_rows"][0]["source_record_id"] == "a-1"
    assert loaded["population_rows"][0]["population"] == 588717
    assert loaded["road_rows"][0]["source_record_id"] == "r1"
    assert loaded["land_parcel_rows"][0]["source_record_id"] == "9"


def test_unbounded_load_is_complete_when_all_sources_exist(tmp_path, monkeypatch):
    root = _build_source_root(tmp_path)
    monkeypatch.setattr(adapter, "ASSET_SPECS", _fixture_specs())

    loaded = adapter.load_traditional_livability_source_rows(root)

    assert loaded["manifest"]["ready"] is True
    assert loaded["manifest"]["complete_inventory"] is True
    assert len(loaded["poi_rows"]) == 2
