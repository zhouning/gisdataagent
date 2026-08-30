from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

from data_agent.dltb_vertical_demo import DLTBVerticalDemo
from data_agent.offline_ingest import OfflineIngestStore
from scripts.run_dltb_vertical_demo import (
    _paper9_product_handoff,
    _publish_paper9_handoff,
    _quality_gate_summary,
    _reference_year_metadata,
)


def _fixture(tmp_path, *, quality_status: str = "pass", mapping_status: str = "accepted"):
    target = tmp_path / "governed" / "DLTB.parquet"
    target.parent.mkdir(parents=True)
    frame = gpd.GeoDataFrame(
        {
            "BSM": ["p-001", "p-002", "p-003"],
            "YSDM": ["DLTB", "DLTB", "DLTB"],
            "DLBM": ["011", "021", "011"],
            "DLMC": ["水田", "农村宅基地", "水田"],
            "QSDWDM": ["5001", "5001", "5002"],
            "QSDWMC": ["甲区", "甲区", "乙区"],
            "ZLDWDM": ["5001", "5001", "5002"],
            "ZLDWMC": ["甲区", "甲区", "乙区"],
            "TBMJ": [100.0, 400.0, 900.0],
        },
        geometry=[box(0, 0, 10, 10), box(10, 0, 30, 20), box(0, 10, 30, 40)],
        crs="EPSG:3857",
    )
    frame.to_parquet(target, index=False)
    store = OfflineIngestStore(tmp_path / "lake")
    plan_id = "a" * 32
    plan_root = store.root / "standardized" / plan_id
    materialized_root = store.root / "materialized" / plan_id
    plan_root.mkdir(parents=True)
    materialized_root.mkdir(parents=True)
    source_asset = "scan:asset-dltb"
    mapping = {
        "ea_model_candidate": "DLTB",
        "status": mapping_status,
        "field_mappings": [
            {"canonical_field": field, "source_field": field}
            for field in frame.columns
            if field != "geometry"
        ],
    }
    (plan_root / "standardization_plan.json").write_text(
        json.dumps({"plan_id": plan_id, "status": "planned", "parent_run_id": "b" * 32}),
        encoding="utf-8",
    )
    parent_root = store.root / "runs" / ("b" * 32)
    parent_root.mkdir(parents=True)
    (parent_root / "run.json").write_text(
        json.dumps(
            {
                "run_id": "b" * 32,
                "quality": [],
                "deep_quality": {
                    "items": [{"asset_id": source_asset, "layer": "DLTB", "status": quality_status}]
                },
            }
        ),
        encoding="utf-8",
    )
    (materialized_root / "materialization.json").write_text(
        json.dumps(
            {
                "status": "succeeded",
                "outputs": [
                    {
                        "target_id": "standardized:dltb",
                        "target_kind": "postgis_or_geoparquet",
                        "target_path": str(target),
                        "target_sha256": "1" * 64,
                        "source_asset_id": source_asset,
                        "source_layer": "DLTB",
                        "canonical_dataset": "DLTB",
                        "execution_status": "succeeded",
                        "mapping": mapping,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return store, plan_id, target


def test_projection_creates_metrics_lineage_and_catalog(tmp_path):
    store, plan_id, _ = _fixture(tmp_path)
    result = DLTBVerticalDemo(store).build_projection(plan_id, mode="rehearsal")
    projection = result["projection"]
    assert projection["semantic_source"] == "land_parcel_current"
    assert projection["ontology_version"] == "2.3.0"
    assert projection["production_eligible"] is False
    assert projection["default_execution_engine"] == "postgis"
    assert projection["publication_status"] == "lake_only"
    assert projection["execution_bindings"]["lake"]["row_count"] == 3
    semantic_query_path = Path(
        projection["execution_bindings"]["lake"]["projection_path"]
    )
    semantic_query_frame = gpd.read_parquet(semantic_query_path)
    assert semantic_query_path != Path(projection["target_path"])
    assert {
        "_gda_geometry_area_sqm",
        "_gda_area_delta_sqm",
        "_gda_area_delta_ratio",
    } <= set(semantic_query_frame.columns)
    assert result["metrics"]["feature_count"] == 3
    assert (
        store.root / "semantic_products" / projection["projection_id"] / "lineage.json"
    ).exists()
    catalog = json.loads((store.root / "semantic_products" / "catalog.json").read_text())
    assert catalog["sources"][0]["table_name"] == "land_parcel_current"


def test_projection_production_gate_rejects_review(tmp_path):
    store, plan_id, _ = _fixture(tmp_path, quality_status="review")
    try:
        DLTBVerticalDemo(store).build_projection(plan_id, mode="production")
    except ValueError as exc:
        assert "accepted mapping" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("review data must not become a production semantic source")


def test_projection_registers_postgis_and_lake_bindings(tmp_path, monkeypatch):
    store, plan_id, _ = _fixture(tmp_path)

    def fake_publish(path, **kwargs):
        return {
            "status": "succeeded",
            "engine": "postgis",
            "table_name": "public.land_parcel_current",
            "version_table_name": "public.land_parcel_current__version",
            "projection_id": kwargs["projection_id"],
            "projection_path": str(path),
            "row_count": 3,
        }

    monkeypatch.setattr(
        "data_agent.postgis_projection_publisher.publish_geoparquet_to_postgis",
        fake_publish,
    )
    projection = DLTBVerticalDemo(store).build_projection(plan_id, publish_postgis=True)[
        "projection"
    ]

    assert projection["publication_status"] == "dual_published"
    assert projection["postgis_table_name"] == "public.land_parcel_current"
    assert set(projection["execution_bindings"]) == {"lake", "postgis"}
    catalog = json.loads((store.root / "semantic_products" / "catalog.json").read_text())
    assert catalog["sources"][0]["execution_bindings"]["postgis"]["row_count"] == 3


def test_query_uses_semantic_fields_for_land_use_and_area_checks(tmp_path):
    store, plan_id, _ = _fixture(tmp_path)
    projection = DLTBVerticalDemo(store).build_projection(plan_id)["projection"]
    result = (
        DLTBVerticalDemo.query(
            projection["projection_id"],  # exercise the explicit path form below too
            "各地类图斑数量和面积是多少",
        )
        if False
        else DLTBVerticalDemo.query(
            store.root
            / "semantic_products"
            / projection["projection_id"]
            / "semantic_projection.json",
            "各地类图斑数量和面积是多少",
        )
    )
    assert result["query_type"] == "group_summary"
    assert sum(row["feature_count"] for row in result["rows"]) == 3
    consistency = DLTBVerticalDemo.query(
        store.root / "semantic_products" / projection["projection_id"] / "semantic_projection.json",
        "列出面积属性与几何面积差异较大的图斑",
    )
    assert consistency["query_type"] == "area_consistency"
    assert consistency["rows"][0]["_gda_area_delta_pct"] >= 0

    cultivated = DLTBVerticalDemo.query(
        store.root / "semantic_products" / projection["projection_id"] / "semantic_projection.json",
        "每个行政区的耕地面积有多少？",
    )
    assert sum(row["feature_count"] for row in cultivated["rows"]) == 2

    lookup = DLTBVerticalDemo.query(
        store.root / "semantic_products" / projection["projection_id"] / "semantic_projection.json",
        "图斑 BSM:p-001 是什么地类？",
    )
    assert lookup["query_type"] == "parcel_lookup"
    assert lookup["rows"][0]["BSM"] == "p-001"


def test_quality_gate_summary_exposes_production_blockers():
    summary = _quality_gate_summary(
        {
            "status": "review",
            "counts": {"review": 1},
            "deep_quality": {
                "items": [
                    {
                        "asset_id": "asset-1",
                        "asset_name": "GDB.gdb",
                        "layer": "DLTB",
                        "status": "review",
                        "semantic_mapping_status": "manual_review",
                        "checks": {"invalid_geometry_count": 3, "duplicate_key_count": 0},
                    }
                ]
            },
        }
    )
    assert summary["production_gate_passed"] is False
    assert summary["findings"][0]["reasons"] == [
        "semantic_mapping:manual_review",
        "invalid_geometry:3",
    ]


def test_paper9_handoff_exposes_dltb_dem_and_admin_products():
    outputs = [
        {
            "target_id": "product:dltb",
            "target_kind": "postgis_or_geoparquet",
            "target_path": "/lake/DLTB.parquet",
            "target_sha256": "1" * 64,
            "source_raw_path": "/lake/raw/DLTB.gdb",
            "source_layer": "DLTB",
            "canonical_dataset": "DLTB",
            "execution_status": "succeeded",
            "mapping": {"status": "accepted"},
            "materialization_profile": {
                "crs": "EPSG:4490",
                "bbox": [105.0, 35.0, 106.0, 36.0],
                "feature_count": 12,
                "columns": ["BSM", "DLBM", "QSDWDM"],
            },
        },
        {
            "target_id": "product:dem",
            "target_kind": "cog_stac",
            "target_path": "/lake/dem.tif",
            "target_sha256": "2" * 64,
            "source_raw_path": "/lake/raw/dem.tif",
            "execution_status": "succeeded",
        },
        {
            "target_id": "product:admin",
            "target_kind": "postgis_or_geoparquet",
            "target_path": "/lake/XZQ.parquet",
            "target_sha256": "3" * 64,
            "source_raw_path": "/lake/raw/XZQ.gpkg",
            "source_layer": "XZQ",
            "execution_status": "succeeded",
        },
    ]

    handoff = _paper9_product_handoff(
        {"materialization": {"outputs": outputs}},
        dem_name="dem.tif",
        admin_name="XZQ.gpkg",
        reference_years={"dltb": 2025, "dem": 2024, "administrative_units": 2025},
        reference_year_metadata={
            "dltb": {
                "year": 2025,
                "source": "operator_supplied",
                "authoritative": True,
            },
            "dem": {"year": 2024, "source": "path_inferred", "authoritative": False},
            "administrative_units": {
                "year": 2025,
                "source": "operator_supplied",
                "authoritative": True,
            },
        },
    )

    assert handoff["governed_input_ready"] is True
    assert handoff["administrative_units_ready"] is True
    assert handoff["products"]["dltb"]["path"] == "/lake/DLTB.parquet"
    assert handoff["products"]["dem"]["path"] == "/lake/dem.tif"
    assert handoff["products"]["dltb"]["crs"] == "EPSG:4490"
    assert handoff["products"]["dltb"]["reference_year"] == 2025
    assert handoff["products"]["dltb"]["reference_year_authoritative"] is True
    assert handoff["products"]["dem"]["reference_year_source"] == "path_inferred"


def test_reference_year_metadata_distinguishes_operator_input_from_path_inference():
    explicit = _reference_year_metadata(2025, "/data/dem_2020.tif")
    inferred = _reference_year_metadata(None, "/data/dem_2020.tif")

    assert explicit == {
        "year": 2025,
        "source": "operator_supplied",
        "authoritative": True,
    }
    assert inferred == {
        "year": 2020,
        "source": "path_inferred",
        "authoritative": False,
    }


def test_paper9_handoff_prefers_xzq_layer_from_multi_layer_gdb():
    shared_source = "/lake/raw/boundaries.gdb"
    outputs = [
        {
            "target_id": "product:cjdcq",
            "target_kind": "postgis_or_geoparquet",
            "target_path": "/lake/CJDCQ.parquet",
            "source_raw_path": shared_source,
            "source_layer": "CJDCQ",
            "execution_status": "succeeded",
            "materialization_profile": {"columns": ["ZLDWDM", "ZLDWMC"]},
        },
        {
            "target_id": "product:xzq",
            "target_kind": "postgis_or_geoparquet",
            "target_path": "/lake/XZQ.parquet",
            "source_raw_path": shared_source,
            "source_layer": "XZQ",
            "execution_status": "succeeded",
            "materialization_profile": {"columns": ["XZQDM", "XZQMC"]},
        },
    ]

    handoff = _paper9_product_handoff(
        {"materialization": {"outputs": outputs}},
        dem_name=None,
        admin_name="boundaries.gdb",
    )

    assert handoff["products"]["administrative_units"]["source_layer"] == "XZQ"
    assert handoff["products"]["administrative_units"]["path"] == "/lake/XZQ.parquet"


def test_publish_paper9_handoff_writes_discoverable_catalog(tmp_path):
    handoff = {
        "products": {"dltb": {"status": "succeeded", "path": "/lake/DLTB.parquet"}},
        "governed_input_ready": False,
        "administrative_units_ready": False,
    }

    result = _publish_paper9_handoff(
        tmp_path,
        handoff,
        phase1_report=tmp_path / "reports" / "phase1.json",
        source=tmp_path / "DLTB.gdb",
        quality_status="review",
        production_eligible=False,
        plan_id="plan-1",
    )

    entry = json.loads(Path(result["entry_path"]).read_text(encoding="utf-8"))
    catalog = json.loads(Path(result["catalog_path"]).read_text(encoding="utf-8"))
    assert entry["handoff_id"] == "plan-1"
    assert catalog["items"][0]["quality_status"] == "review"
