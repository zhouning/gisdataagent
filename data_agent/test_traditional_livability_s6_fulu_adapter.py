import hashlib
from copy import deepcopy
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
    geometries = [row["geometry"] for row in rows]
    attributes = [
        {key: value for key, value in row.items() if key != "geometry"}
        for row in rows
    ]
    driver = "ESRI Shapefile" if path.suffix == ".shp" else "GPKG"
    gpd.GeoDataFrame(attributes, geometry=geometries, crs=crs).to_file(path, driver=driver)


def _specs(extension: str = "gpkg"):
    return tuple(
        {
            "area_id": area_id,
            "layer": layer,
            "relative_path": f"{area_id}/{layer}.{extension}",
            "required": True,
        }
        for area_id in ("fulu_heping", "fulu_banzhu")
        for layer in ("GHFW", "JQDLTB", "TDGHDL")
    )


def _polygon(x: float, y: float = 0) -> Polygon:
    return Polygon([(x, y), (x + 100, y), (x + 100, y + 100), (x, y + 100), (x, y)])


def _planning_fixture_root(
    tmp_path: Path,
    extension: str = "gpkg",
    *,
    reverse_rows: bool = False,
    include_exact_duplicate: bool = False,
) -> Path:
    area_specs = (
        ("fulu_heping", "EPSG:4523", 35597400, 3209600, None),
        ("fulu_banzhu", "EPSG:32648", 626600, 3208600, "现状"),
    )
    for area_id, crs, origin_x, origin_y, source_status in area_specs:
        _write(
            tmp_path / area_id / f"GHFW.{extension}",
            [{"BSM": f"boundary-{area_id}", "geometry": _polygon(origin_x, origin_y)}],
            crs,
        )
        current_rows = [
            {"TBBH": f"current-{area_id}", "BSM": f"bsm-current-{area_id}", "DLDM": "2121", "DLMC": "村居住用地", "geometry": _polygon(origin_x + 10, origin_y + 10)},
            {"TBBH": f"unknown-{area_id}", "DLDM": "999", "DLMC": "未知用途", "geometry": _polygon(origin_x + 15, origin_y + 15)},
        ]
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
                    "TBBH": f"planned-{area_id}",
                    "CGHDLDM": "2123",
                    "CGHDLMC": "村公共服务用地",
                    "geometry": _polygon(origin_x + 25, origin_y + 25),
                }
            )
            planned_rows.append(
                {
                    "TBBH": "status-unrecognized",
                    "CGHDLDM": "2123",
                    "CGHDLMC": "预留公共服务用地",
                    "GHZT": "待核",
                    "geometry": _polygon(origin_x + 30, origin_y + 30),
                }
            )
        if include_exact_duplicate:
            planned_rows.append(deepcopy(planned_row))
        if reverse_rows:
            current_rows.reverse()
            planned_rows.reverse()
        _write(
            tmp_path / area_id / f"JQDLTB.{extension}",
            current_rows,
            crs,
        )
        _write(tmp_path / area_id / f"TDGHDL.{extension}", planned_rows, crs)
    return tmp_path


def _facility_product() -> dict:
    return {
        "schema": "uwm.traditional_livability.facility_product.v1",
        "product_id": "fixture-product",
        "mapping_version": "traditional_livability_facility_mapping.v1",
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

    unknown = next(row for row in payload["planning_resources"] if row["raw_tbbh"] == "planned-fulu_heping")
    unrecognized = next(row for row in payload["planning_resources"] if row["raw_tbbh"] == "status-unrecognized")
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

    first_rows = [row for row in first["planning_resources"] if row["planning_area_id"] == "fulu_heping" and row["source_layer"] == "TDGHDL" and row["raw_tbbh"] == "planned-fulu_heping"]
    second_ids = {row["resource_id"] for row in second["planning_resources"]}
    planned = first_rows[0]
    assert {row["resource_id"] for row in first["planning_resources"]} == second_ids
    assert planned["raw_land_use_code"] == "2123"
    assert planned["raw_land_use_name"] == "村公共服务用地"
    assert planned["area_m2"] == 10000.0
    assert shape(planned["metric_geometry"]).geom_type == "Polygon"
    assert shape(planned["display_geometry_wgs84"]).geom_type == "Polygon"
    assert str(tmp_path) not in str(first["source_manifest"])
    assert all(source.get("relative_path") and source.get("sha256") for source in first["source_manifest"]["sources"])
    assert planned["source_manifest_ref"] in {source["source_id"] for source in first["source_manifest"]["sources"]}
    gpkg_source = next(source for source in first["source_manifest"]["sources"] if source["source_id"] == planned["source_manifest_ref"])
    assert gpkg_source["sha256"] == hashlib.sha256((source_root / gpkg_source["relative_path"]).read_bytes()).hexdigest()
    assert "components" not in gpkg_source


def test_planning_resources_emit_controlled_domain_rules_and_explicit_unresolved(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs())

    payload = build_fulu_s6_resources(
        source_root=_planning_fixture_root(tmp_path),
        facility_product=_facility_product(),
    )

    known = next(row for row in payload["planning_resources"] if row["raw_tbbh"] == "planned-fulu_heping")
    unresolved = next(row for row in payload["planning_resources"] if row["raw_tbbh"] == "unknown-fulu_heping")
    assert known["resource_domain"] == "village_public_service_land"
    assert known["interpretation_rule"] == "exact_land_use_code:2123"
    assert known["interpretation_evidence"] == {"field": "raw_land_use_code", "value": "2123"}
    assert unresolved["resource_domain"] == "unresolved"
    assert unresolved["interpretation_rule"] is None
    assert unresolved["interpretation_evidence"] == {
        "raw_land_use_code": "999",
        "raw_land_use_name": "未知用途",
        "resolution_status": "unresolved",
    }


def test_shapefile_manifest_hashes_complete_dataset_family(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs("shp"))
    source_root = _planning_fixture_root(tmp_path, "shp")

    first = build_fulu_s6_resources(source_root=source_root, facility_product=_facility_product())
    second = build_fulu_s6_resources(source_root=source_root, facility_product=_facility_product())

    source = next(row for row in first["source_manifest"]["sources"] if row["planning_area_id"] == "fulu_heping" and row["layer"] == "GHFW")
    repeated = next(row for row in second["source_manifest"]["sources"] if row["source_id"] == source["source_id"])
    component_suffixes = {Path(row["relative_path"]).suffix for row in source["components"]}
    assert {".shp", ".dbf", ".shx", ".prj", ".cpg"} <= component_suffixes
    assert all(row["sha256"] for row in source["components"])
    assert source["sha256"] == repeated["sha256"]
    assert source["sha256"] not in {row["sha256"] for row in source["components"]}
    assert str(tmp_path) not in str(source)


def test_repeated_tbbh_rows_have_stable_unique_source_and_resource_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs())
    source_root = _planning_fixture_root(tmp_path)

    first = build_fulu_s6_resources(source_root=source_root, facility_product=_facility_product())
    second = build_fulu_s6_resources(source_root=source_root, facility_product=_facility_product())

    first_source_ids = [row["source_record_id"] for row in first["planning_resources"]]
    second_source_ids = [row["source_record_id"] for row in second["planning_resources"]]
    first_resource_ids = [row["resource_id"] for row in first["planning_resources"]]
    second_resource_ids = [row["resource_id"] for row in second["planning_resources"]]
    repeated = [row for row in first["planning_resources"] if row["raw_tbbh"] == "planned-fulu_heping"]
    bsm_row = next(row for row in first["planning_resources"] if row["raw_tbbh"] == "current-fulu_heping")
    assert first_source_ids == second_source_ids
    assert first_resource_ids == second_resource_ids
    assert len(set(first_source_ids)) == len(first_source_ids)
    assert len(set(first_resource_ids)) == len(first_resource_ids)
    assert len(repeated) == 2
    assert len({row["source_record_id"] for row in repeated}) == 2
    assert all(row["raw_bsm"] is None for row in repeated)
    assert bsm_row["raw_bsm"] == "bsm-current-fulu_heping"
    assert bsm_row["source_identity_field"] == "BSM"
    assert bsm_row["source_identity_value"] == "bsm-current-fulu_heping"


def test_source_and_resource_ids_are_stable_under_row_reordering(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs())
    first_root = _planning_fixture_root(
        tmp_path / "ordered", include_exact_duplicate=True
    )
    second_root = _planning_fixture_root(
        tmp_path / "reversed", reverse_rows=True, include_exact_duplicate=True
    )

    first = build_fulu_s6_resources(
        source_root=first_root, facility_product=_facility_product()
    )
    second = build_fulu_s6_resources(
        source_root=second_root, facility_product=_facility_product()
    )

    first_source_ids = [row["source_record_id"] for row in first["planning_resources"]]
    second_source_ids = [row["source_record_id"] for row in second["planning_resources"]]
    first_resource_ids = [row["resource_id"] for row in first["planning_resources"]]
    second_resource_ids = [row["resource_id"] for row in second["planning_resources"]]
    assert first_source_ids == second_source_ids
    assert first_resource_ids == second_resource_ids
    assert len(set(first_source_ids)) == len(first_source_ids)
    assert len(set(first_resource_ids)) == len(first_resource_ids)
    exact_duplicates = [
        row
        for row in first["planning_resources"]
        if row["planning_area_id"] == "fulu_banzhu"
        and row["source_layer"] == "TDGHDL"
        and row["raw_tbbh"] == "planned-fulu_banzhu"
    ]
    assert len(exact_duplicates) == 2
    assert {row["source_duplicate_ordinal"] for row in exact_duplicates} == {0, 1}
    assert len({row["source_record_digest"] for row in exact_duplicates}) == 1
    second_by_id = {
        row["source_record_id"]: row for row in second["planning_resources"]
    }
    assert any(
        row["source_row_number"]
        != second_by_id[row["source_record_id"]]["source_row_number"]
        for row in first["planning_resources"]
        if row["source_duplicate_ordinal"] is None
    )


def test_unmapped_and_mapped_facilities_are_retained_with_completeness(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs())
    planning_inputs = build_fulu_s6_resources(
        source_root=_planning_fixture_root(tmp_path),
        facility_product={"facilities": [], "source_manifest": {"complete_inventory": True}},
    )

    product = _facility_product()
    planning_before = deepcopy(planning_inputs)
    product_before = deepcopy(product)

    payload = attach_facility_resources(planning_inputs, product)

    facilities = {row["source_record_id"]: row for row in payload["current_facilities"]}
    assert set(facilities) == {"unmapped-heping", "mapped-banzhu"}
    assert facilities["unmapped-heping"]["mapping_status"] == "unmapped"
    assert facilities["mapped-banzhu"]["mapping_status"] == "mapped_internal_taxonomy"
    assert facilities["unmapped-heping"]["mapping_version"] == "traditional_livability_facility_mapping.v1"
    assert facilities["mapped-banzhu"]["mapping_version"] == "traditional_livability_facility_mapping.v1"
    assert facilities["unmapped-heping"]["raw_primary_class"] == "生活服务"
    assert shape(facilities["unmapped-heping"]["metric_geometry"]).geom_type == "Point"
    assert shape(facilities["unmapped-heping"]["display_geometry_wgs84"]).geom_type == "Point"
    assert payload["facility_inventory"]["complete_inventory"] is False
    assert payload["facility_inventory"]["mapping_version"] == "traditional_livability_facility_mapping.v1"
    assert payload["facility_inventory"]["source_manifest"] == _facility_product()["source_manifest"]
    assert planning_inputs == planning_before
    assert product == product_before


def test_boundary_crossing_facility_polygon_is_spatially_associated(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs())
    planning_inputs = build_fulu_s6_resources(
        source_root=_planning_fixture_root(tmp_path),
        facility_product={"facilities": [], "source_manifest": {"complete_inventory": True}},
    )
    product = {
        "mapping_version": "traditional_livability_facility_mapping.v1",
        "source_manifest": {"complete_inventory": True},
        "facilities": [
            {
                "source_dataset_id": "baidu_aoi",
                "source_record_id": "crossing-aoi",
                "name": "跨界文化设施",
                "canonical_class": "culture.facility",
                "mapping_status": "mapped_internal_taxonomy",
                "geometry": Polygon(
                    [
                        (35597450, 3209650),
                        (35597550, 3209650),
                        (35597550, 3209750),
                        (35597450, 3209750),
                        (35597450, 3209650),
                    ]
                ).__geo_interface__,
                "geometry_crs": "EPSG:4523",
            }
        ],
    }

    payload = attach_facility_resources(planning_inputs, product)

    assert [row["source_record_id"] for row in payload["current_facilities"]] == ["crossing-aoi"]
    assert shape(payload["current_facilities"][0]["metric_geometry"]).geom_type == "Polygon"


def test_multi_area_facility_overlap_is_unresolved_without_arbitrary_crs(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "ASSET_SPECS", _specs())
    planning_inputs = build_fulu_s6_resources(
        source_root=_planning_fixture_root(tmp_path),
        facility_product={"facilities": [], "source_manifest": {"complete_inventory": True}},
    )
    first_area = planning_inputs["planning_areas"][0]
    overlapping_area = deepcopy(first_area)
    overlapping_area["planning_area_id"] = "fulu_overlap"
    overlapping_area["distance_crs"] = "EPSG:32648"
    planning_inputs["planning_areas"].append(overlapping_area)
    centroid = shape(first_area["display_geometry_wgs84"]).centroid
    product = {
        "mapping_version": "traditional_livability_facility_mapping.v1",
        "source_manifest": {"complete_inventory": True},
        "facilities": [
            {
                "source_dataset_id": "gaode_poi",
                "source_record_id": "multi-area",
                "name": "跨区设施",
                "canonical_class": "unmapped",
                "mapping_status": "unmapped",
                "longitude": centroid.x,
                "latitude": centroid.y,
            }
        ],
    }

    payload = attach_facility_resources(planning_inputs, product)

    facility = payload["current_facilities"][0]
    assert facility["association_status"] == "multi_area_overlap_unresolved"
    assert facility["matching_planning_area_ids"] == ["fulu_heping", "fulu_overlap"]
    assert facility["planning_area_id"] is None
    assert facility["distance_crs"] is None
    assert facility["metric_geometry"] is None


def test_write_helper_does_not_mutate_fixture_rows(tmp_path):
    rows = [{"TBBH": "row-1", "geometry": _polygon(0)}]
    before = deepcopy(rows)

    _write(tmp_path / "fixture.gpkg", rows, "EPSG:4523")

    assert rows == before
