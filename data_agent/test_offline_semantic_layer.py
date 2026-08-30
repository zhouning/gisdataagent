from __future__ import annotations

import json

from data_agent.semantic_layer import (
    describe_table_semantic,
    list_semantic_sources,
    resolve_semantic_context,
)


def _write_catalog(tmp_path):
    catalog = tmp_path / "semantic_products" / "catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(
        json.dumps(
            {
                "schema": "gda.offline-semantic-catalog.v1",
                "sources": [
                    {
                        "table_name": "land_parcel_current",
                        "display_name": "现状地类图斑（治理产品）",
                        "description": "file-backed DLTB",
                        "geometry_type": "Polygon",
                        "srid": 4610,
                        "synonyms": ["地类图斑", "现状用地", "DLTB"],
                        "fields": {
                            "land_use_code": {
                                "source_field": "DLBM",
                                "property": "currentLandUseCode",
                                "aliases": ["地类编码", "DLBM"],
                                "required": True,
                            },
                            "parcel_area_sqm": {
                                "source_field": "TBMJ",
                                "property": "parcelArea",
                                "aliases": ["图斑面积", "面积", "TBMJ"],
                                "unit": "m²",
                                "required": True,
                            },
                        },
                        "production_eligible": False,
                        "projection_id": "a" * 32,
                        "projection_path": str(tmp_path / "governed" / "DLTB.parquet"),
                        "postgis_table_name": "public.land_parcel_current",
                        "execution_bindings": {
                            "lake": {
                                "projection_id": "a" * 32,
                                "projection_path": str(tmp_path / "governed" / "DLTB.parquet"),
                            },
                            "postgis": {
                                "table_name": "public.land_parcel_current",
                                "projection_id": "a" * 32,
                            },
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_semantic_layer_discovers_file_backed_projection_without_database(tmp_path, monkeypatch):
    _write_catalog(tmp_path)
    monkeypatch.setenv("GDA_FILE_LAKE_ROOT", str(tmp_path))
    monkeypatch.setattr("data_agent.semantic_layer.get_engine", lambda: None)

    sources = list_semantic_sources()
    assert sources["status"] == "success"
    assert sources["sources"][0]["table_name"] == "land_parcel_current"

    context = resolve_semantic_context("各地类图斑的面积是多少")
    assert context["sources"][0]["table_name"] == "land_parcel_current"
    assert context["sources"][0]["projection_path"].endswith("DLTB.parquet")
    assert context["sources"][0]["postgis_table_name"] == "public.land_parcel_current"
    assert "land_parcel_current" in context["matched_columns"]

    description = describe_table_semantic("land_parcel_current")
    assert description["status"] == "success"
    assert any(column["column_name"] == "TBMJ" for column in description["columns"])
    assert description["source_metadata"]["source_kind"] == "offline_projection"
    assert description["source_metadata"]["projection_path"].endswith("DLTB.parquet")
    assert description["source_metadata"]["postgis_table_name"] == "public.land_parcel_current"
