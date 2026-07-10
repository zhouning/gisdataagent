import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point, Polygon

from data_agent.uwm import traditional_livability_source_adapter as adapter


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_traditional_livability_phase1a.py"
SPEC = importlib.util.spec_from_file_location("build_traditional_livability_phase1a", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def _specs():
    return (
        {"asset_id": "gaode_poi", "kind": "vector", "relative_path": "poi.gpkg", "layer": "poi", "required": True},
        {"asset_id": "baidu_aoi", "kind": "vector", "relative_path": "aoi.gpkg", "layer": "aoi", "required": True},
        {"asset_id": "admin_population_2021", "kind": "excel", "relative_path": "population.xlsx", "required": True},
        {"asset_id": "osm_roads_2021", "kind": "vector", "relative_path": "roads.gpkg", "layer": "roads", "required": True},
        {"asset_id": "current_land_use", "kind": "vector", "relative_path": "land.gpkg", "layer": "land", "required": True},
    )


def _vector(path, layer, rows, geometry):
    gpd.GeoDataFrame(rows, geometry=geometry, crs="EPSG:4326").to_file(path, layer=layer, driver="GPKG")


def _sources(root):
    _vector(root / "poi.gpkg", "poi", [{"ID": 1, "名称": "人民小学", "类型": "科教文化服务;学校;小学", "区域ID": 500103, "经度wgs84": 106.5, "纬度wgs84": 29.5}], [Point(106.5, 29.5)])
    _vector(root / "aoi.gpkg", "aoi", [{"uid": "a1", "名称": "公园", "第一分类": "旅游景点", "第二分类": "公园", "区县": "渝中区", "经度wgs84": 106.5, "纬度wgs84": 29.5}], [Polygon([(106.4,29.4),(106.5,29.4),(106.5,29.5),(106.4,29.4)])])
    _vector(root / "roads.gpkg", "roads", [{"osm_id": "r1", "fclass": "primary"}], [LineString([(106.4,29.4),(106.5,29.5)])])
    _vector(root / "land.gpkg", "land", [{"BSM": 1, "DLBM": "0701", "DLMC": "住宅", "TBMJ": 10}], [Polygon([(106.4,29.4),(106.5,29.4),(106.5,29.5),(106.4,29.4)])])
    pd.DataFrame([{"行政区划代码": 500103, "区划名称": "渝中区", "常住人口": 10.0}]).to_excel(root / "population.xlsx", index=False)


def test_builder_fails_closed_for_missing_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs())
    monkeypatch.setattr(MODULE.source_adapter, "ASSET_SPECS", _specs())

    result = MODULE.build_phase1a(source_root=tmp_path, output_dir=tmp_path / "out")

    assert result["ready"] is False
    assert not (tmp_path / "out" / "uwm_traditional_livability_s1.json").exists()


def test_builder_writes_atomic_public_snapshots_without_absolute_paths(tmp_path, monkeypatch):
    _sources(tmp_path)
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs())
    monkeypatch.setattr(MODULE.source_adapter, "ASSET_SPECS", _specs())
    output = tmp_path / "out"

    result = MODULE.build_phase1a(source_root=tmp_path, output_dir=output)

    assert result["ready"] is True
    for filename in ["uwm_traditional_livability_source_manifest.json", "uwm_traditional_livability_facility_product.json", "uwm_traditional_livability_s1.json"]:
        payload = json.loads((output / filename).read_text(encoding="utf-8"))
        assert str(tmp_path) not in json.dumps(payload, ensure_ascii=False)
    s1 = json.loads((output / "uwm_traditional_livability_s1.json").read_text(encoding="utf-8"))
    assert s1["supply_metrics"][0]["compliance_status"] == "not_assessed"


def test_script_help_runs_from_repository_checkout():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=SCRIPT.parents[1],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--source-root" in completed.stdout
