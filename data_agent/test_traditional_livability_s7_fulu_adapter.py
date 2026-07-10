from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon

from data_agent.uwm import traditional_livability_s7_fulu_adapter as adapter
from data_agent.uwm.traditional_livability_s7_fulu_adapter import classify_primary_school_supply


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


def test_accepts_actual_dltb_land_use_field_names(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs())
    root = _root(tmp_path)
    for area, name in (("fulu_heping", "宅基地（村居住用地）"), ("fulu_banzhu", "村居住用地")):
        _write(
            root / area / "JQDLTB.gpkg",
            [{"TBBH": "actual", "DLDM": "2121", "DLMC": name, "geometry": _poly(500)}],
        )

    payload = adapter.load_fulu_s7_planning_inputs(root)

    assert len(payload["demand_parcels"]) == 2
    assert {row["source_parcel_id"] for row in payload["demand_parcels"]} == {"actual"}


def test_classifies_exact_primary_school_supply_against_planning_boundaries():
    planning_inputs = {
        "planning_areas": [
            {
                "planning_area_id": "fulu_heping",
                "distance_crs": "EPSG:4523",
                "boundary_geometry_wgs84": Polygon([(106.0, 29.0), (106.1, 29.0), (106.1, 29.1), (106.0, 29.1)]),
            },
            {
                "planning_area_id": "fulu_banzhu",
                "distance_crs": "EPSG:4523",
                "boundary_geometry_wgs84": Polygon([(106.2, 29.0), (106.3, 29.0), (106.3, 29.1), (106.2, 29.1)]),
            },
        ]
    }
    facility_product = {
        "facilities": [
            {"name": "和平小学", "source_record_id": "primary-heping", "source_dataset_id": "poi", "canonical_class": "education.primary_school", "longitude": 106.05, "latitude": 29.05},
            {"name": "斑竹小学", "source_record_id": "primary-banzhu", "source_dataset_id": "poi", "canonical_class": "education.primary_school", "longitude": 106.25, "latitude": 29.05},
            {"name": "村外小学", "source_record_id": "primary-outside", "source_dataset_id": "poi", "canonical_class": "education.primary_school", "longitude": 106.4, "latitude": 29.05},
            {"name": "无坐标小学", "source_record_id": "primary-unlocatable", "source_dataset_id": "poi", "canonical_class": "education.primary_school", "longitude": None, "latitude": None},
            {"name": "泛学校", "source_record_id": "school-generic", "source_dataset_id": "poi", "canonical_class": "education.school", "longitude": 106.05, "latitude": 29.05},
        ]
    }

    supply = classify_primary_school_supply(
        facility_product=facility_product,
        planning_inputs=planning_inputs,
    )

    assert {row["source_record_id"]: row["supply_verification_status"] for row in supply} == {
        "primary-heping": "locally_verified_current_supply",
        "primary-banzhu": "locally_verified_current_supply",
        "primary-outside": "outside_planning_area_reference",
        "primary-unlocatable": "unlocatable_reference",
    }
    assert {row["source_record_id"]: row.get("planning_area_id") for row in supply} == {
        "primary-heping": "fulu_heping",
        "primary-banzhu": "fulu_banzhu",
        "primary-outside": None,
        "primary-unlocatable": None,
    }
    assert "school-generic" not in {row["source_record_id"] for row in supply}


def test_classifies_only_exact_primary_schools_against_planning_boundaries():
    planning_inputs = {
        "planning_areas": [
            {"planning_area_id": "fulu_heping", "distance_crs": "EPSG:4326", "boundary_geometry_wgs84": Polygon([(106, 29), (106.1, 29), (106.1, 29.1), (106, 29.1), (106, 29)])},
            {"planning_area_id": "fulu_banzhu", "distance_crs": "EPSG:4326", "boundary_geometry_wgs84": Polygon([(106.2, 29), (106.3, 29), (106.3, 29.1), (106.2, 29.1), (106.2, 29)])},
        ]
    }
    product = {"facilities": [
        {"source_dataset_id": "poi", "source_record_id": "h", "name": "和平小学", "canonical_class": "education.primary_school", "longitude": 106.05, "latitude": 29.05},
        {"source_dataset_id": "poi", "source_record_id": "b", "name": "斑竹小学", "canonical_class": "education.primary_school", "longitude": 106.25, "latitude": 29.05},
        {"source_dataset_id": "poi", "source_record_id": "o", "name": "范围外小学", "canonical_class": "education.primary_school", "longitude": 107, "latitude": 30},
        {"source_dataset_id": "poi", "source_record_id": "u", "name": "未知小学", "canonical_class": "education.primary_school"},
        {"source_dataset_id": "poi", "source_record_id": "not-primary", "canonical_class": "education.school", "longitude": 106.05, "latitude": 29.05},
    ]}

    rows = adapter.classify_primary_school_supply(facility_product=product, planning_inputs=planning_inputs)

    assert [(row["source_record_id"], row["supply_verification_status"]) for row in rows] == [
        ("h", "locally_verified_current_supply"),
        ("b", "locally_verified_current_supply"),
        ("o", "outside_planning_area_reference"),
        ("u", "unlocatable_reference"),
    ]
    assert rows[0]["planning_area_id"] == "fulu_heping"
