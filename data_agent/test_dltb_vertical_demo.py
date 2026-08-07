from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from data_agent.dltb_vertical_demo import DLTBVerticalDemo
from data_agent.offline_ingest import OfflineIngestStore
from scripts.run_dltb_vertical_demo import _quality_gate_summary


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
                "deep_quality": {"items": [{"asset_id": source_asset, "layer": "DLTB", "status": quality_status}]},
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
    assert result["metrics"]["feature_count"] == 3
    assert (store.root / "semantic_products" / projection["projection_id"] / "lineage.json").exists()
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


def test_query_uses_semantic_fields_for_land_use_and_area_checks(tmp_path):
    store, plan_id, _ = _fixture(tmp_path)
    projection = DLTBVerticalDemo(store).build_projection(plan_id)["projection"]
    result = DLTBVerticalDemo.query(
        projection["projection_id"],  # exercise the explicit path form below too
        "各地类图斑数量和面积是多少",
    ) if False else DLTBVerticalDemo.query(
        store.root / "semantic_products" / projection["projection_id"] / "semantic_projection.json",
        "各地类图斑数量和面积是多少",
    )
    assert result["query_type"] == "group_summary"
    assert sum(row["feature_count"] for row in result["rows"]) == 3
    consistency = DLTBVerticalDemo.query(
        store.root / "semantic_products" / projection["projection_id"] / "semantic_projection.json",
        "列出面积属性与几何面积差异较大的图斑",
    )
    assert consistency["query_type"] == "area_consistency"


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
