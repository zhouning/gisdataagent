from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from data_agent.connectors.arcgis_rest import ArcGISQuerySnapshot, _sanitize_geojson_geometry
from data_agent.uwm.abu_dhabi_flood.network_compiler import (
    PipelineCompilePolicy,
    compile_pipeline_topology,
)
from data_agent.uwm.abu_dhabi_flood.smartmakani_acquisition import (
    LAYER_SPECS,
    MIMS_MODEL_FIELDS,
    SENSITIVE_MIMS_FIELDS,
    SmartMakaniLayerSpec,
    download_layer,
)
from data_agent.uwm.abu_dhabi_flood.supporting_surfaces import (
    BUILDING_EXCLUDED_SOURCE_FIELDS,
    BUILDING_FIELDS,
    SUPPORTING_LAYER_SPECS,
    build_supporting_surface_audit,
)
from data_agent.uwm.abu_dhabi_flood.surface_clip_compiler import (
    clip_surface_frame,
    compile_surface_clip_bundle,
)


class FakeArcGISConnector:
    def __init__(self, object_ids: tuple[int, ...]) -> None:
        self.object_ids = object_ids
        self.snapshot_calls = 0
        self.page_runs: list[tuple[int, ...]] = []

    async def create_query_snapshot(
        self,
        endpoint_url: str,
        auth_config: dict,
        query_config: dict,
        **kwargs,
    ) -> ArcGISQuerySnapshot:
        self.snapshot_calls += 1
        layer_id = int(endpoint_url.rsplit("/", 1)[-1])
        service_url = endpoint_url.rsplit("/", 1)[0]
        return ArcGISQuerySnapshot(
            query_url=f"{endpoint_url}/query",
            service_url=service_url,
            layer_id=layer_id,
            object_id_field="OBJECTID",
            object_ids=self.object_ids,
            matched_record_count=len(self.object_ids),
            where="1=1",
            out_fields=query_config["out_fields"],
            return_geometry=True,
            snapshot_strategy="return_ids_only",
        )

    async def iter_snapshot_pages(
        self,
        snapshot: ArcGISQuerySnapshot,
        auth_config: dict,
        *,
        page_size: int,
        target_crs: str,
    ):
        import geopandas as gpd
        from shapely.geometry import Point

        self.page_runs.append(tuple(snapshot.object_ids))
        for batch_index, start in enumerate(range(0, snapshot.record_count, page_size)):
            object_ids = snapshot.object_ids[start : start + page_size]
            frame = gpd.GeoDataFrame(
                {"OBJECTID": object_ids},
                geometry=[Point(225_000 + value, 2_687_000) for value in object_ids],
                crs=target_crs,
            )
            yield {
                "batch_index": batch_index,
                "object_ids": object_ids,
                "frame": frame,
                "records_read": len(frame),
                "records_total": snapshot.record_count,
            }


class FakeSupportingSurfaceConnector:
    def __init__(self, spec: SmartMakaniLayerSpec) -> None:
        self.spec = spec

    async def create_query_snapshot(
        self,
        endpoint_url: str,
        auth_config: dict,
        query_config: dict,
        **kwargs,
    ) -> ArcGISQuerySnapshot:
        assert endpoint_url == self.spec.endpoint_url
        return ArcGISQuerySnapshot(
            query_url=f"{endpoint_url}/query",
            service_url=self.spec.service_url,
            layer_id=self.spec.layer_id,
            object_id_field=self.spec.object_id_field,
            object_ids=(1, 2),
            matched_record_count=2,
            where="1=1",
            out_fields=query_config["out_fields"],
            return_geometry=True,
            snapshot_strategy="return_ids_only",
        )

    async def iter_snapshot_pages(
        self,
        snapshot: ArcGISQuerySnapshot,
        auth_config: dict,
        *,
        page_size: int,
        target_crs: str,
    ):
        import geopandas as gpd
        from shapely.geometry import LineString, Polygon

        if self.spec.storage_key == "building_survey":
            attributes = {
                "OBJECTID": [1, 2],
                "BUILDINGNUMBEROFFLOORS": [1, 3],
                "BUILDINGHEIGHT": [4.0, 12.0],
                "PHYSICALSTATUS": ["existing", None],
            }
            geometries = [
                Polygon(
                    [
                        (230_000, 2_690_000),
                        (230_002, 2_690_000),
                        (230_002, 2_690_002),
                        (230_000, 2_690_002),
                    ]
                ),
                Polygon(
                    [
                        (230_003, 2_690_000),
                        (230_005, 2_690_000),
                        (230_005, 2_690_002),
                        (230_003, 2_690_002),
                    ]
                ),
            ]
        else:
            value_field = (
                "Contour"
                if self.spec.storage_key == "contour_2017_zone40"
                else "ELEVATION"
            )
            attributes = {"OBJECTID": [1, 2], value_field: [-1.0, 2.0]}
            geometries = [
                LineString([(230_000, 2_690_000), (230_002, 2_690_000)]),
                LineString([(230_003, 2_690_000), (230_005, 2_690_000)]),
            ]
        frame = gpd.GeoDataFrame(
            attributes,
            geometry=geometries,
            crs=target_crs,
        )
        yield {
            "batch_index": 0,
            "object_ids": snapshot.object_ids,
            "frame": frame,
            "records_read": 2,
            "records_total": 2,
        }


@pytest.mark.asyncio
async def test_feature_download_freezes_ids_resumes_and_repairs_only_bad_page(
    tmp_path: Path,
) -> None:
    spec = SmartMakaniLayerSpec(
        layer_id=37,
        role="test_pipeline",
        out_fields=("OBJECTID",),
        bbox_wgs84=(54.0, 24.0, 55.0, 25.0),
    )
    first = FakeArcGISConnector((1, 2, 3, 4, 5))
    manifest = await download_layer(tmp_path, spec, connector=first, page_size=2)

    assert first.snapshot_calls == 1
    assert first.page_runs == [(1, 2, 3, 4, 5)]
    assert manifest["status"] == "complete"
    assert manifest["completed_record_count"] == 5
    assert manifest["completed_page_count"] == 3
    assert manifest["public_feature_rows"] is True
    assert manifest["contains_personal_fields"] is False

    second = FakeArcGISConnector((99,))
    resumed = await download_layer(tmp_path, spec, connector=second, page_size=2)
    assert second.snapshot_calls == 0
    assert second.page_runs == []
    assert resumed["content_fingerprint"] == manifest["content_fingerprint"]

    layer_root = tmp_path / "online/smartmakani/features/layer_37"
    (layer_root / "pages/page_000001.geojson").write_text("corrupt", encoding="utf-8")
    repair = FakeArcGISConnector((99,))
    repaired = await download_layer(tmp_path, spec, connector=repair, page_size=2)
    assert repair.snapshot_calls == 0
    assert repair.page_runs == [(3, 4)]
    assert repaired["status"] == "complete"
    assert repaired["completed_record_count"] == 5


def test_mims_download_contract_excludes_sensitive_fields() -> None:
    assert not SENSITIVE_MIMS_FIELDS.intersection(MIMS_MODEL_FIELDS)
    assert LAYER_SPECS[30].contains_personal_fields is False
    assert LAYER_SPECS[32].out_fields == MIMS_MODEL_FIELDS
    assert "VIOLATOR_PHONE_NUMBER" not in LAYER_SPECS[30].out_fields


def test_supporting_surface_contracts_are_query_only_and_privacy_minimized() -> None:
    assert set(SUPPORTING_LAYER_SPECS) == {
        "bathymetry_2017",
        "building_survey",
        "contour_2017_zone40",
    }
    buildings = SUPPORTING_LAYER_SPECS["building_survey"]
    assert buildings.out_fields == BUILDING_FIELDS
    assert not set(BUILDING_FIELDS).intersection(BUILDING_EXCLUDED_SOURCE_FIELDS)
    assert buildings.endpoint_url.endswith("Building_Survey/FeatureServer/1")
    assert buildings.storage_key == "building_survey"

    invalid = SmartMakaniLayerSpec(
        layer_id=1,
        role="invalid",
        out_fields=("OBJECTID",),
        bbox_wgs84=None,
        dataset_key="../escape",
    )
    with pytest.raises(ValueError, match="invalid_smartmakani_dataset_key"):
        _ = invalid.storage_key


@pytest.mark.asyncio
async def test_supporting_surface_audit_keeps_surface_and_k0_closed(
    tmp_path: Path,
) -> None:
    for spec in SUPPORTING_LAYER_SPECS.values():
        test_spec = replace(spec, snapshot_bbox_grid=None)
        await download_layer(
            tmp_path,
            test_spec,
            connector=FakeSupportingSurfaceConnector(test_spec),
            page_size=2,
        )

    audit = build_supporting_surface_audit(tmp_path)

    assert audit["surface_candidate_summary"]["contour_record_count"] == 2
    assert audit["surface_candidate_summary"]["building_record_count"] == 2
    assert audit["surface_candidate_summary"]["vertical_datum_verified"] is False
    assert audit["admission"]["engineering_dem_admitted"] is False
    assert audit["admission"]["surface_patch_contract_compiled"] is False
    assert audit["admission"]["k0_opened"] is False
    building = next(
        item for item in audit["layers"] if item["dataset_key"] == "building_survey"
    )
    assert building["field_contract"]["unexpected_field_count"] == 0
    assert building["field_contract"]["building_excluded_source_fields_present"] is False


def test_surface_clip_forces_2d_and_drops_non_line_intersections() -> None:
    import geopandas as gpd
    import shapely
    from shapely.geometry import LineString, box

    frame = gpd.GeoDataFrame(
        {
            "OBJECTID": [1, 2],
            "Contour": [5.0, 6.0],
        },
        geometry=[
            LineString([(-5.0, 5.0, 9.0), (15.0, 5.0, 9.0)]),
            LineString([(20.0, 20.0, 9.0), (30.0, 30.0, 9.0)]),
        ],
        crs="EPSG:32640",
    )

    output, audit = clip_surface_frame(
        frame,
        dataset_key="contour_2017_zone40",
        clip_geometry=box(0.0, 0.0, 10.0, 10.0),
        source_page_index=7,
    )

    assert output["OBJECTID"].tolist() == [1]
    assert output["source_page_index"].tolist() == [7]
    assert not bool(shapely.has_z(output.geometry.iloc[0]))
    assert output.geometry.iloc[0].length == pytest.approx(10.0)
    assert audit["empty_after_exact_clip_count"] == 1
    assert audit["output_invalid_geometry_count"] == 0
    assert audit["output_outside_target_count"] == 0
    assert audit["output_has_z_count"] == 0


def test_surface_clip_repairs_invalid_building_without_admitting_it() -> None:
    import geopandas as gpd
    from shapely.geometry import Polygon, box

    bowtie = Polygon([(1, 1), (9, 9), (1, 9), (9, 1), (1, 1)])
    assert bowtie.is_valid is False
    frame = gpd.GeoDataFrame(
        {
            "OBJECTID": [1],
            "BUILDINGNUMBEROFFLOORS": [2],
            "BUILDINGHEIGHT": [8.0],
            "PHYSICALSTATUS": ["existing"],
        },
        geometry=[bowtie],
        crs="EPSG:32640",
    )

    output, audit = clip_surface_frame(
        frame,
        dataset_key="building_survey",
        clip_geometry=box(0.0, 0.0, 10.0, 10.0),
    )

    assert len(output) == 1
    assert output.geometry.iloc[0].is_valid is True
    assert output["geometry_repaired"].tolist() == [True]
    assert audit["invalid_before_repair_count"] == 1
    assert audit["geometry_repaired_count"] == 1
    assert audit["output_invalid_geometry_count"] == 0
    assert audit["output_outside_target_count"] == 0


@pytest.mark.asyncio
async def test_surface_clip_bundle_is_resumable_and_keeps_k0_closed(
    tmp_path: Path,
) -> None:
    for spec in SUPPORTING_LAYER_SPECS.values():
        test_spec = replace(spec, snapshot_bbox_grid=None)
        await download_layer(
            tmp_path,
            test_spec,
            connector=FakeSupportingSurfaceConnector(test_spec),
            page_size=2,
        )

    first = compile_surface_clip_bundle(tmp_path)
    assert first["summary"]["source_page_count"] == 3
    assert first["summary"]["source_record_count"] == 6
    assert first["summary"]["output_record_count"] == 6
    assert first["summary"]["all_returned_geometries_clipped_to_target"] is True
    assert first["summary"]["output_outside_target_count"] == 0
    assert first["summary"]["output_has_z_count"] == 0
    assert first["admission"]["engineering_dem_admitted"] is False
    assert first["admission"]["surface_patch_contract_compiled"] is False
    assert first["admission"]["k0_opened"] is False

    contour_page = (
        tmp_path
        / "derived/smartmakani/surface_clip_candidate/"
        "contour_2017_zone40/pages/page_000000.parquet"
    )
    contour_page.write_text("corrupt", encoding="utf-8")
    repaired = compile_surface_clip_bundle(tmp_path)

    assert repaired["output"]["sha256"] == first["output"]["sha256"]
    assert repaired["summary"] == first["summary"]


def test_arcgis_null_coordinate_geometry_keeps_row_as_missing_geometry() -> None:
    assert (
        _sanitize_geojson_geometry(
            {"type": "Point", "coordinates": [None, None]}
        )
        is None
    )
    valid = {"type": "Point", "coordinates": [54.4, 24.4]}
    assert _sanitize_geojson_geometry(valid) == valid


def test_pipeline_compiler_audits_snap_duplicates_components_and_direction() -> None:
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import LineString

    starts = [
        (200_000.0, 2_600_000.0),
        (200_010.2, 2_600_000.1),
        (200_030.0, 2_600_000.0),
        (200_010.0, 2_600_000.0),
    ]
    ends = [
        (200_010.0, 2_600_000.0),
        (200_020.0, 2_600_000.0),
        (200_030.2, 2_600_000.0),
        (200_000.0, 2_600_000.0),
    ]
    frame = gpd.GeoDataFrame(
        {
            "OBJECTID": [1, 2, 3, 4],
            "ASSET_DIAMETER": [500.0, 0.0, 300.0, 500.0],
            "INVERT_LEVEL_UP": [5.0, 3.0, -999.0, 5.0],
            "INVERT_LEVEL_DOWN": [4.0, 4.0, -999.0, 4.0],
            "OUTFALL_NAME": ["", "O-1", "", ""],
            "Start_X": [value[0] for value in starts],
            "Start_Y": [value[1] for value in starts],
            "End_X": [value[0] for value in ends],
            "End_Y": [value[1] for value in ends],
        },
        geometry=[
            LineString([start, end])
            for start, end in zip(starts, ends, strict=True)
        ],
        crs="EPSG:32640",
    )

    enriched, nodes, audit = compile_pipeline_topology(
        frame,
        policy=PipelineCompilePolicy(snap_tolerance_m=1.0),
    )

    assert len(enriched) == 4
    assert len(nodes) == 4
    assert audit["topology"]["connected_component_count"] == 2
    assert audit["topology"]["self_loops_after_snap"]["count"] == 1
    assert audit["topology"]["duplicate_node_pair_group_count"] == 1
    assert audit["topology"]["rows_in_duplicate_node_pairs"]["count"] == 2
    assert audit["attributes"]["diameter_positive"]["count"] == 3
    assert audit["attributes"]["flow_direction_conflict"]["count"] == 1
    assert audit["attributes"]["attribute_endpoints"]["within_tolerance"]["count"] == 4
    assert audit["geometry"]["z_available"]["count"] == 0
    assert audit["geometry"]["z_source_unit_or_datum_verified"] is False
    assert audit["admission"]["admitted"] is False
    assert audit["admission"]["flood_network_contract_compiled"] is False
