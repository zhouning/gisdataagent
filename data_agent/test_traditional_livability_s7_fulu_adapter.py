from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon

from data_agent.uwm import traditional_livability_s7_fulu_adapter as adapter


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(rows, geometry=[row.pop("geometry") for row in rows], crs="EPSG:4523").to_file(path, driver="GPKG")


def _specs():
    output = []
    for area in ("fulu_heping", "fulu_banzhu"):
        for layer in ("GHFW", "JQDLTB", "TDGHDL"):
            output.append({"area_id": area, "layer": layer, "relative_path": f"{area}/{layer}.gpkg", "required": True})
    return tuple(output)


def _poly(x):
    return Polygon([(x, 0), (x + 10, 0), (x + 10, 10), (x, 10), (x, 0)])


def _root(tmp_path):
    for offset, area in enumerate(("fulu_heping", "fulu_banzhu")):
        _write(tmp_path / area / "GHFW.gpkg", [{"BSM": 1, "geometry": _poly(offset * 100)}])
        demand_name = "宅基地（村居住用地）" if area == "fulu_heping" else "村居住用地"
        _write(tmp_path / area / "JQDLTB.gpkg", [{"TBBH": "d1", "JQDLDM": "2121", "JQDLMC": demand_name, "geometry": _poly(offset * 100 + 20)}])
        _write(tmp_path / area / "TDGHDL.gpkg", [
            {"TBBH": "c1", "CGHDLDM": "2123", "CGHDLMC": "村公共服务用地", "geometry": _poly(offset * 100 + 40)},
            {"TBBH": "x1", "CGHDLDM": "011", "CGHDLMC": "水田", "geometry": _poly(offset * 100 + 60)},
            {"TBBH": "x2", "CGHDLDM": "151", "CGHDLMC": "设施农用地", "geometry": _poly(offset * 100 + 80)},
        ])
    return tmp_path


def test_inspect_fulu_s7_planning_sources_reports_missing_required_source(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs())
    manifest = adapter.inspect_fulu_s7_planning_sources(tmp_path)
    assert manifest["schema"] == "uwm.traditional_livability.s7_fulu_planning_inputs.v1"
    assert manifest["ready"] is False
    assert "missing_required_source:fulu_heping:GHFW" in manifest["blockers"]
    assert str(tmp_path) not in str(manifest)


def test_loads_two_area_contract_with_demand_candidates_and_exclusions(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs())
    payload = adapter.load_fulu_s7_planning_inputs(_root(tmp_path))
    assert payload["ready"] is True
    assert {row["planning_area_id"] for row in payload["planning_areas"]} == {"fulu_heping", "fulu_banzhu"}
    assert len(payload["demand_parcels"]) == 2
    assert payload["demand_parcels"][0]["demand_proxy"] == "residential_land_area_m2"
    assert payload["demand_parcels"][0]["weight_m2"] > 0
    assert len(payload["candidate_parcels"]) == 2
    candidate = payload["candidate_parcels"][0]
    assert candidate["candidate_policy"] == "planned_public_service_or_mixed_or_independent_construction"
    assert candidate["suitability_score"] == 3
    assert {row["exclusion_reason"] for row in payload["excluded_parcels"]} == {
        "cultivated_land",
        "facilities_agriculture_land",
    }
    assert candidate["distance_crs"]
    assert {"longitude", "latitude"} <= set(candidate["display_centroid"])
