from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point, Polygon, shape

from data_agent.uwm import traditional_livability_s6_fulu_adapter as adapter
from data_agent.uwm.traditional_livability_s6_fulu_adapter import (
    attach_facility_resources,
    build_fulu_s6_resources,
)


def _write(path: Path, rows: list[dict], crs: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    geometries = [row.pop("geometry") for row in rows]
    gpd.GeoDataFrame(rows, geometry=geometries, crs=crs).to_file(path, driver="GPKG")


def _specs():
    return tuple(
        {
            "area_id": area_id,
            "layer": layer,
            "relative_path": f"{area_id}/{layer}.gpkg",
            "required": True,
        }
        for area_id in ("fulu_heping", "fulu_banzhu")
        for layer in ("GHFW", "JQDLTB", "TDGHDL")
    )


def _polygon(x: float, y: float = 0) -> Polygon:
    return Polygon([(x, y), (x + 100, y), (x + 100, y + 100), (x, y + 100), (x, y)])


def _planning_fixture_root(tmp_path: Path) -> Path:
    area_specs = (
        ("fulu_heping", "EPSG:4523", 35597400, 3209600, None),
        ("fulu_banzhu", "EPSG:32648", 626600, 3208600, "现状"),
    )
    for area_id, crs, origin_x, origin_y, source_status in area_specs:
        _write(
            tmp_path / area_id / "GHFW.gpkg",
            [{"BSM": f"boundary-{area_id}", "geometry": _polygon(origin_x, origin_y)}],
            crs,
        )
        _write(
            tmp_path / area_id / "JQDLTB.gpkg",
            [{"TBBH": f"current-{area_id}", "DLDM": "2121", "DLMC": "村居住用地", "geometry": _polygon(origin_x + 10, origin_y + 10)}],
            crs,
        )
        planned_row = {
            "TBBH": f"planned-{area_id}",
            "CGHDLDM": "2123",
            "CGHDLMC": "村公共服务用地",
            "geometry": _polygon(origin_x + 20, origin_y + 20),
        }
        if source_status is not None:
            planned_row["GHZT"] = source_status
        planned_rows = [planned_row]
        if area_id == "fulu_heping":
            planned_rows.append(
                {
                    "TBBH": "status-unrecognized",
                    "CGHDLDM": "2123",
                    "CGHDLMC": "预留公共服务用地",
                    "GHZT": "待核",
                    "geometry": _polygon(origin_x + 30, origin_y + 30),
                }
            )
        _write(tmp_path / area_id / "TDGHDL.gpkg", planned_rows, crs)
    return tmp_path


def _facility_product() -> dict:
    return {
        "schema": "uwm.traditional_livability.facility_product.v1",
        "product_id": "fixture-product",
        "source_manifest": {
            "schema": "uwm.traditional_livability.source_manifest.v1",
            "complete_inventory": False,
            "sources": [{"asset_id": "gaode_poi", "relative_path": "poi/gaode.gpkg", "sha256": "abc123"}],
        },
        "facilities": [
            {
                "source_dataset_id": "gaode_poi",
                "source_record_id": "unmapped-heping",
                "name": "和平便民点",
                "raw_primary_class": "生活服务",
                "raw_secondary_class": "便民服务",
                "raw_tertiary_class": None,
                "canonical_class": "unmapped",
                "mapping_status": "unmapped",
                "longitude": None,
                "latitude": None,
                "geometry": Point(35597450, 3209650).__geo_interface__,
                "geometry_crs": "EPSG:4523",
            },
            {
                "source_dataset_id": "gaode_poi",
                "source_record_id": "mapped-banzhu",
                "name": "斑竹卫生室",
                "raw_primary_class": "医疗保健服务",
                "raw_secondary_class": "诊所",
                "raw_tertiary_class": None,
                "canonical_class": "healthcare.facility",
                "mapping_status": "mapped_internal_taxonomy",
                "longitude": None,
                "latitude": None,
                "geometry": Point(626650, 3208650).__geo_interface__,
                "geometry_crs": "EPSG:32648",
            },
            {
                "source_dataset_id": "gaode_poi",
                "source_record_id": "outside",
                "name": "村外设施",
                "canonical_class": "unmapped",
                "mapping_status": "unmapped",
                "longitude": 120.0,
                "latitude": 30.0,
            },
        ],
    }


def test_resource_adapter_preserves_source_status_without_guessing_reserved(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs())

    payload = build_fulu_s6_resources(
        source_root=_planning_fixture_root(tmp_path),
        facility_product=_facility_product(),
    )

    unknown = next(row for row in payload["planning_resources"] if row["source_record_id"] == "planned-fulu_heping")
    unrecognized = next(row for row in payload["planning_resources"] if row["source_record_id"] == "status-unrecognized")
    current = next(row for row in payload["planning_resources"] if row["planning_area_id"] == "fulu_banzhu" and row["source_layer"] == "TDGHDL")
    assert unknown["planning_status"] == "status_unknown"
    assert unknown["planning_status_evidence"] is None
    assert unrecognized["planning_status"] == "status_unknown"
    assert unrecognized["planning_status_evidence"] == {"field": "GHZT", "value": "待核"}
    assert current["planning_status"] == "current"
    assert current["planning_status_evidence"] == {"field": "GHZT", "value": "现状"}
    assert all(row["planning_status"] != "reserved" for row in payload["planning_resources"])


def test_resource_adapter_keeps_area_specific_distance_crs_and_serialized_geometries(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs())

    payload = build_fulu_s6_resources(
        source_root=_planning_fixture_root(tmp_path),
        facility_product=_facility_product(),
    )

    areas = {row["planning_area_id"]: row for row in payload["planning_areas"]}
    assert set(areas) == {"fulu_heping", "fulu_banzhu"}
    assert areas["fulu_heping"]["distance_crs"] == "EPSG:4523"
    assert areas["fulu_banzhu"]["distance_crs"] == "EPSG:32648"
    assert shape(areas["fulu_heping"]["metric_geometry"]).geom_type == "Polygon"
    assert shape(areas["fulu_heping"]["display_geometry_wgs84"]).bounds[0] < 180


def test_planning_resources_keep_stable_ids_raw_land_use_and_relative_source_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs())
    source_root = _planning_fixture_root(tmp_path)

    first = build_fulu_s6_resources(source_root=source_root, facility_product=_facility_product())
    second = build_fulu_s6_resources(source_root=source_root, facility_product=_facility_product())

    first_rows = {(row["planning_area_id"], row["source_layer"], row["source_record_id"]): row for row in first["planning_resources"]}
    second_ids = {row["resource_id"] for row in second["planning_resources"]}
    planned = first_rows[("fulu_heping", "TDGHDL", "planned-fulu_heping")]
    assert {row["resource_id"] for row in first["planning_resources"]} == second_ids
    assert planned["raw_land_use_code"] == "2123"
    assert planned["raw_land_use_name"] == "村公共服务用地"
    assert shape(planned["metric_geometry"]).geom_type == "Polygon"
    assert shape(planned["display_geometry_wgs84"]).geom_type == "Polygon"
    assert str(tmp_path) not in str(first["source_manifest"])
    assert all(source.get("relative_path") and source.get("sha256") for source in first["source_manifest"]["sources"])
    assert planned["source_manifest_ref"] in {source["source_id"] for source in first["source_manifest"]["sources"]}


def test_unmapped_and_mapped_facilities_are_retained_with_completeness(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs())
    planning_inputs = build_fulu_s6_resources(
        source_root=_planning_fixture_root(tmp_path),
        facility_product={"facilities": [], "source_manifest": {"complete_inventory": True}},
    )

    payload = attach_facility_resources(planning_inputs, _facility_product())

    facilities = {row["source_record_id"]: row for row in payload["current_facilities"]}
    assert set(facilities) == {"unmapped-heping", "mapped-banzhu"}
    assert facilities["unmapped-heping"]["mapping_status"] == "unmapped"
    assert facilities["mapped-banzhu"]["mapping_status"] == "mapped_internal_taxonomy"
    assert facilities["unmapped-heping"]["raw_primary_class"] == "生活服务"
    assert shape(facilities["unmapped-heping"]["metric_geometry"]).geom_type == "Point"
    assert shape(facilities["unmapped-heping"]["display_geometry_wgs84"]).geom_type == "Point"
    assert payload["facility_inventory"]["complete_inventory"] is False
    assert payload["facility_inventory"]["source_manifest"] == _facility_product()["source_manifest"]
