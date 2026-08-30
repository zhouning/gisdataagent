from __future__ import annotations

import json

from data_agent.dltb_multi_engine_query import query_dltb
from scripts.validate_dltb_query_engines import _normalize


def _projection(tmp_path):
    projection_id = "a" * 32
    product = tmp_path / "semantic_products" / projection_id
    product.mkdir(parents=True)
    projection = {
        "projection_id": projection_id,
        "production_eligible": False,
        "execution_bindings": {
            "lake": {
                "projection_id": projection_id,
                "projection_path": str(tmp_path / "DLTB.parquet"),
            },
            "postgis": {
                "projection_id": projection_id,
                "table_name": "public.land_parcel_current",
            },
        },
    }
    projection_path = product / "semantic_projection.json"
    projection_path.write_text(json.dumps(projection), encoding="utf-8")
    (product.parent / "catalog.json").write_text(
        json.dumps({"sources": [projection]}), encoding="utf-8"
    )
    return projection_path


def test_postgis_and_lake_use_unified_nl2semantic2sql(tmp_path, monkeypatch):
    projection_path = _projection(tmp_path)
    calls = []

    def fake_run(question, execution_engine):
        from data_agent.semantic_layer import current_offline_semantic_catalog_path

        calls.append(
            (
                question,
                execution_engine,
                current_offline_semantic_catalog_path.get(),
            )
        )
        return json.dumps(
            {
                "status": "ok",
                "sql": "SELECT COUNT(*) AS feature_count FROM land_parcel_current",
                "raw_sql": "SELECT COUNT(*) AS feature_count FROM land_parcel_current",
                "execution_engine": execution_engine,
                "dialect": "postgres" if execution_engine == "postgis" else "duckdb",
                "execution": {
                    "status": "ok",
                    "data": [{"feature_count": 3}],
                    "source_bindings": [],
                },
                "llm": {"model": "Qwen3.6:27b", "request_id": "chatcmpl-test"},
                "semantic": {"candidate_tables": ["land_parcel_current"]},
            }
        )

    monkeypatch.setattr("data_agent.nl2sql_executor.run_nl2semantic2sql", fake_run)

    for engine in ("postgis", "lake"):
        result = query_dltb(
            projection_path,
            "图斑有多少条？",
            execution_engine=engine,
        )
        assert result["status"] == "succeeded"
        assert result["rows"] == [{"feature_count": 3}]
        assert result["execution_engine"] == engine
        assert result["fallback_used"] is False
        assert result["diagnostic_only"] is False

    expected_catalog = str(projection_path.parent.parent / "catalog.json")
    assert calls == [
        ("图斑有多少条？", "postgis", expected_catalog),
        ("图斑有多少条？", "lake", expected_catalog),
    ]


def test_validation_normalizes_native_postgres_and_duckdb_aggregate_names():
    assert _normalize([{"count": 101657}], "count") == {"feature_count": 101657}
    assert _normalize([{"count_star()": 3, "sum(TBMJ)": 120.5}], "count_area") == {
        "feature_count": 3,
        "area_sqm": 120.5,
    }
    assert _normalize(
        [
            {"DLBM": "011", "feature_count": 2, "area_sqm": 70.0},
            {"DLBM": "012", "feature_count": 1, "area_sqm": 50.5},
        ],
        "count_area",
    ) == {"feature_count": 3, "area_sqm": 120.5}
