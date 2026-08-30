from __future__ import annotations

import json
from unittest.mock import patch

import pandas as pd

from data_agent.lake_sql_executor import execute_lake_sql


def _candidate(path):
    return {
        "table_name": "land_parcel_current",
        "source_kind": "offline_projection",
        "projection_id": "p-001",
        "projection_path": str(path),
        "execution_bindings": {
            "lake": {
                "projection_id": "p-001",
                "projection_path": str(path),
            }
        },
    }


def test_execute_lake_sql_queries_governed_parquet_view(tmp_path):
    path = tmp_path / "dltb.parquet"
    pd.DataFrame(
        {
            "DLBM": ["011", "011", "021"],
            "TBMJ": [100.0, 200.0, 400.0],
            "BSM": [1.0, 2.0, 3.0],
        }
    ).to_parquet(path, index=False)

    result = json.loads(
        execute_lake_sql(
            "SELECT DLBM, COUNT(*) AS feature_count, SUM(TBMJ) AS area_sqm "
            "FROM land_parcel_current GROUP BY DLBM ORDER BY DLBM",
            [_candidate(path)],
        )
    )

    assert result["status"] == "ok"
    assert result["engine"] == "lake"
    assert result["dialect"] == "duckdb"
    assert result["rows"] == 2
    assert result["data"][0] == {
        "DLBM": "011",
        "feature_count": 2,
        "area_sqm": 300.0,
    }
    assert result["source_bindings"][0]["projection_id"] == "p-001"


def test_execute_lake_sql_rejects_generated_file_reads(tmp_path):
    path = tmp_path / "dltb.parquet"
    pd.DataFrame({"DLBM": ["011"]}).to_parquet(path, index=False)

    result = json.loads(
        execute_lake_sql(
            "SELECT * FROM read_parquet('/tmp/unregistered.parquet')",
            [_candidate(path)],
        )
    )

    assert result["status"] == "error"
    assert result["error"] == "lake_sql_safety:external_table_function"


def test_execute_lake_sql_rejects_duckdb_file_reader_aliases(tmp_path):
    path = tmp_path / "dltb.parquet"
    pd.DataFrame({"DLBM": ["011"]}).to_parquet(path, index=False)

    for sql in (
        "SELECT * FROM parquet_scan('/tmp/unregistered.parquet')",
        "SELECT read_blob('/tmp/unregistered.bin')",
        "SELECT read_text('/tmp/unregistered.txt')",
    ):
        result = json.loads(execute_lake_sql(sql, [_candidate(path)]))
        assert result["status"] == "error"
        assert result["error"] == "lake_sql_safety:external_table_function"


def test_execute_lake_sql_rewrites_correlated_spatial_exists(tmp_path):
    path = tmp_path / "dltb.parquet"
    pd.DataFrame({"geometry": [b"not-wkb"]}).to_parquet(path, index=False)

    from data_agent.lake_sql_executor import _rewrite_correlated_spatial_exists

    rewritten, note = _rewrite_correlated_spatial_exists(
        "SELECT COUNT(*) FROM land_parcel_current AS p "
        "WHERE EXISTS (SELECT 1 FROM land_parcel_current AS q "
        "WHERE ST_Intersects(p.geometry, q.geometry))"
    )

    assert note == "correlated_spatial_exists_to_deduplicated_join"
    assert "JOIN land_parcel_current AS q ON ST_Intersects(p.geometry, q.geometry)" in rewritten
    assert "SELECT DISTINCT p.geometry AS _gda_entity_id" in rewritten

    result = json.loads(
        execute_lake_sql(
            rewritten,
            [_candidate(path)],
        )
    )

    assert result["status"] == "error"


def test_correlated_spatial_exists_rewrite_targets_outer_from_after_cte():
    from data_agent.lake_sql_executor import _rewrite_correlated_spatial_exists

    rewritten, note = _rewrite_correlated_spatial_exists(
        "WITH selected AS (SELECT geometry FROM parcels WHERE area > 10) "
        "SELECT COUNT(*) FROM selected s WHERE EXISTS "
        "(SELECT 1 FROM roads r WHERE ST_Intersects(s.geometry, r.geometry))"
    )

    assert note == "correlated_spatial_exists_to_deduplicated_join"
    assert "FROM selected AS s JOIN roads AS r ON ST_Intersects(s.geometry, r.geometry)" in rewritten
    assert "SELECT DISTINCT s.geometry AS _gda_entity_id" in rewritten
    assert "FROM parcels WHERE area > 10" in rewritten
    assert "FROM parcels WHERE JOIN" not in rewritten


def test_correlated_spatial_exists_aggregate_deduplicates_left_entities():
    from data_agent.lake_sql_executor import _rewrite_correlated_spatial_exists

    rewritten, note = _rewrite_correlated_spatial_exists(
        'SELECT SUM(l."TBMJ") AS total_area FROM cq_land_use_dltb l '
        'WHERE l."DLMC" = \'水田\' AND EXISTS ('
        'SELECT 1 FROM cq_osm_roads_2021 r '
        'WHERE ST_Intersects(l.geometry, r.geometry))',
        [{
            "table_name": "cq_land_use_dltb",
            "fields": {
                "BSM": {"value_semantics": {"identifier": True}},
                "TBMJ": {},
            },
        }],
    )

    assert note == "correlated_spatial_exists_to_deduplicated_join"
    assert "GROUP BY l.\"BSM\", l.\"TBMJ\"" in rewritten
    assert "l.\"TBMJ\" AS _gda_metric" in rewritten
    assert "SUM(_gda_selected._gda_metric)" in rewritten


def test_correlated_spatial_exists_inside_derived_table_deduplicates_projection():
    from data_agent.lake_sql_executor import _rewrite_correlated_spatial_exists

    rewritten, note = _rewrite_correlated_spatial_exists(
        "SELECT COUNT(*) FROM (SELECT d.objectid FROM parcels d "
        "WHERE d.area > 10 AND EXISTS (SELECT 1 FROM roads r "
        "WHERE ST_Intersects(d.geometry, r.geometry))) sub",
        [{
            "table_name": "parcels",
            "fields": {"objectid": {"value_semantics": {"identifier": True}}},
        }],
    )

    assert note == "correlated_spatial_exists_to_deduplicated_join"
    assert "SELECT COUNT(*) FROM (SELECT DISTINCT d.objectid" in rewritten
    assert "JOIN roads AS r ON ST_Intersects(d.geometry, r.geometry)" in rewritten


def test_execute_lake_sql_reports_missing_spatial_extension(tmp_path):
    path = tmp_path / "dltb.parquet"
    pd.DataFrame({"geometry": [b"not-wkb"]}).to_parquet(path, index=False)

    with patch(
        "data_agent.lake_sql_executor._load_spatial_extension",
        return_value=(False, "offline extension not bundled"),
    ):
        result = json.loads(
            execute_lake_sql(
                "SELECT ST_Area(geometry) FROM land_parcel_current",
                [_candidate(path)],
            )
        )

    assert result["status"] == "error"
    assert "duckdb_spatial_extension_unavailable" in result["error"]


def test_run_nl2semantic2sql_routes_lake_query_and_uses_duckdb_prompt(tmp_path):
    from data_agent import nl2sql_executor

    path = tmp_path / "dltb.parquet"
    pd.DataFrame({"DLBM": ["011"], "TBMJ": [100.0]}).to_parquet(path, index=False)
    candidate = _candidate(path)
    candidate["columns"] = [
        {
            "column_name": "DLBM",
            "quoted_ref": "DLBM",
            "pg_type": "VARCHAR",
            "needs_quoting": False,
        },
        {
            "column_name": "TBMJ",
            "quoted_ref": "TBMJ",
            "pg_type": "DOUBLE",
            "needs_quoting": False,
        },
    ]
    payload = {
        "candidate_tables": [candidate],
        "grounding_prompt": "GROUNDING",
        "few_shots": [],
        "intent": None,
        "_hint_injection_stats": {"candidate_tables": 1, "few_shots": 0},
    }
    captured = {}

    class FakeResult:
        rejected = False
        reject_reason = ""
        corrections = []
        sql = "SELECT COUNT(*) AS count FROM land_parcel_current"

    def fake_generate(prompt, model_name=None):
        captured["prompt"] = prompt
        return FakeResult.sql

    with (
        patch("data_agent.nl2sql_executor.build_nl2sql_context", return_value=payload),
        patch("data_agent.nl2sql_executor._generate_gemma_sql", side_effect=fake_generate),
        patch("data_agent.nl2sql_executor.postprocess_sql", return_value=FakeResult()),
        patch("data_agent.nl2sql_executor._auto_curate"),
    ):
        result = json.loads(
            nl2sql_executor.run_nl2semantic2sql("地类图斑有多少条？", execution_engine="lake")
        )

    assert result["status"] == "ok"
    assert result["execution_engine"] == "lake"
    assert result["dialect"] == "duckdb"
    assert result["execution"]["data"][0]["count"] == 1
    assert "read-only DuckDB SQL" in captured["prompt"]
    assert "never call read_parquet" in captured["prompt"]


def test_described_offline_source_preserves_explicit_lake_binding(tmp_path):
    from data_agent.nl2sql_executor import _candidate_from_described_schema

    governed = tmp_path / "governed.parquet"
    semantic = tmp_path / "semantic.parquet"
    schema = {
        "columns": [{"column_name": "_gda_area_delta_sqm", "data_type": "DOUBLE"}],
        "source_metadata": {
            "source_kind": "offline_projection",
            "projection_id": "projection-1",
            "projection_path": str(governed),
            "execution_bindings": {
                "lake": {
                    "projection_id": "projection-1",
                    "projection_path": str(semantic),
                }
            },
        },
    }

    candidate = _candidate_from_described_schema("land_parcel_current", schema)

    assert candidate["projection_path"] == str(governed)
    assert candidate["execution_bindings"]["lake"]["projection_path"] == str(semantic)


def test_spatial_join_counts_target_entities_once():
    from data_agent.nl2sql_executor import _ensure_spatial_join_entity_distinct

    sql, corrections = _ensure_spatial_join_entity_distinct(
        'SELECT COUNT(b."Id") FROM buildings b '
        "JOIN roads r ON ST_Intersects(b.geometry, r.geometry)"
    )

    assert sql == (
        'SELECT COUNT(DISTINCT b."Id") FROM buildings b '
        "JOIN roads r ON ST_Intersects(b.geometry, r.geometry)"
    )
    assert corrections == ["spatial_join_entity_count_distinct"]


def test_lake_spatial_dialect_normalizes_postgis_geography_and_transform():
    from data_agent.lake_sql_executor import normalize_lake_spatial_sql

    sql, corrections = normalize_lake_spatial_sql(
        "SELECT ST_Distance(r.geometry::geography, p.geometry::geography), "
        "ST_Area(ST_Transform(a.shape, 4326)::geography) "
        "FROM roads r, poi p, area a "
        "WHERE ST_DWithin(r.geometry::geography, p.geometry::geography, 500)",
        metric_crs="EPSG:32648",
    )

    assert "GEOGRAPHY" not in sql
    assert "ST_TRANSFORM(r.geometry, 'EPSG:32648')" in sql
    assert "ST_TRANSFORM(a.shape, 'EPSG:4326')" in sql
    assert (
        "ST_TRANSFORM(ST_TRANSFORM(a.shape, 'EPSG:4326'), "
        "'EPSG:4326', 'EPSG:32648', TRUE)"
    ) in sql
    assert "duckdb_metric_distance" in corrections
    assert "duckdb_metric_dwithin" in corrections


def test_lake_spatial_dialect_normalizes_knn_and_union_aggregate():
    from data_agent.lake_sql_executor import normalize_lake_spatial_sql

    sql, corrections = normalize_lake_spatial_sql(
        "SELECT ST_Union(p.geometry) FROM parcels p "
        "CROSS JOIN poi q ORDER BY p.geometry <-> q.geometry LIMIT 5",
        metric_crs="EPSG:32648",
        source_crs_by_alias={"p": "EPSG:4326", "q": "EPSG:4326"},
    )

    assert "ST_UNION_AGG(p.geometry)" in sql
    assert "<->" not in sql
    assert "ST_DISTANCE(" in sql
    assert "duckdb_spatial_union_aggregate" in corrections
    assert "duckdb_knn_distance_operator" in corrections


def test_lake_spatial_dialect_normalizes_collect_to_union_aggregate():
    from data_agent.lake_sql_executor import normalize_lake_spatial_sql

    sql, corrections = normalize_lake_spatial_sql(
        "SELECT ST_ENVELOPE(ST_Collect(geometry)) FROM roads",
        metric_crs="EPSG:32648",
    )

    assert "ST_UNION_AGG(geometry)" in sql
    assert "ST_COLLECT" not in sql
    assert "duckdb_spatial_collect_aggregate" in corrections


def test_lake_source_crs_propagates_through_simple_subquery_alias():
    from data_agent.lake_sql_executor import _source_crs_by_alias

    sources = [
        {"table_name": "poi", "srid": 4326},
        {"table_name": "cq_dltb", "srid": 4610},
    ]
    aliases = _source_crs_by_alias(
        "SELECT p.geometry, target.shape FROM poi p CROSS JOIN "
        "(SELECT shape FROM cq_dltb WHERE dlmc = '茶园' LIMIT 1) AS target",
        sources,
    )

    assert aliases["p"] == "EPSG:4326"
    assert aliases["target"] == "EPSG:4610"


def test_lake_metric_distance_uses_nested_transform_output_crs():
    from data_agent.lake_sql_executor import normalize_lake_spatial_sql

    sql, corrections = normalize_lake_spatial_sql(
        "SELECT ST_Distance("
        "ST_Transform(p.geometry, 'EPSG:4326', 'EPSG:4610', TRUE), target.shape) "
        "FROM poi p CROSS JOIN target",
        metric_crs="EPSG:32648",
        source_crs_by_alias={"p": "EPSG:4326", "target": "EPSG:4610"},
    )

    assert "ST_TRANSFORM(p.geometry, 'EPSG:4326', 'EPSG:32648', TRUE)" in sql
    assert "ST_TRANSFORM(target.shape, 'EPSG:4610', 'EPSG:32648', TRUE)" in sql
    assert "duckdb_metric_distance" in corrections


def test_lake_metric_distance_collapses_non_metric_two_argument_transform():
    from data_agent.lake_sql_executor import normalize_lake_spatial_sql

    sql, corrections = normalize_lake_spatial_sql(
        "SELECT ST_DWithin(ST_Transform(b.geometry, 3857)::geography, "
        "ST_Transform(p.geometry, 3857)::geography, 500) "
        "FROM buildings b JOIN poi p ON TRUE",
        metric_crs="EPSG:32648",
        source_crs_by_alias={"b": "EPSG:4326", "p": "EPSG:4326"},
    )

    assert "ST_DWITHIN(ST_TRANSFORM(b.geometry, 'EPSG:4326', 'EPSG:32648', TRUE)" in sql
    assert "ST_TRANSFORM(ST_TRANSFORM" not in sql
    assert "duckdb_transform_crs_string" in corrections


def test_lake_metric_dwithin_normalizes_raw_geometry_with_governed_crs():
    from data_agent.lake_sql_executor import normalize_lake_spatial_sql

    sql, corrections = normalize_lake_spatial_sql(
        "SELECT ST_DWithin(b.geometry, p.geometry, 500) "
        "FROM buildings b JOIN poi p ON TRUE",
        metric_crs="EPSG:32648",
        source_crs_by_alias={"b": "EPSG:4326", "p": "EPSG:4326"},
    )

    assert (
        "ST_DWITHIN(ST_TRANSFORM(b.geometry, 'EPSG:4326', 'EPSG:32648', TRUE), "
        "ST_TRANSFORM(p.geometry, 'EPSG:4326', 'EPSG:32648', TRUE), 500)"
    ) in sql
    assert "duckdb_metric_dwithin" in corrections


def test_lake_metric_dwithin_collapses_numeric_transform_to_governed_crs():
    from data_agent.lake_sql_executor import normalize_lake_spatial_sql

    sql, corrections = normalize_lake_spatial_sql(
        "SELECT ST_DWithin(ST_Transform(b.geometry, 3857), "
        "ST_Transform(p.geometry, 3857), 500) "
        "FROM buildings b JOIN poi p ON TRUE",
        metric_crs="EPSG:32648",
        source_crs_by_alias={"b": "EPSG:4326", "p": "EPSG:4326"},
    )

    assert (
        "ST_DWITHIN(ST_TRANSFORM(b.geometry, 'EPSG:4326', 'EPSG:32648', TRUE), "
        "ST_TRANSFORM(p.geometry, 'EPSG:4326', 'EPSG:32648', TRUE), 500)"
    ) in sql
    assert "ST_TRANSFORM(ST_TRANSFORM" not in sql
    assert "duckdb_metric_dwithin" in corrections


def test_lake_spatial_dialect_normalizes_three_argument_transform_to_always_xy():
    from data_agent.lake_sql_executor import normalize_lake_spatial_sql

    sql, corrections = normalize_lake_spatial_sql(
        "SELECT ST_Area(ST_Transform(b.geometry, 'EPSG:4326', 'EPSG:3857')) "
        "FROM buildings b",
        source_crs_by_alias={"b": "EPSG:4326"},
    )

    assert "ST_TRANSFORM(b.geometry, 'EPSG:4326', 'EPSG:3857', TRUE)" in sql
    assert "duckdb_transform_always_xy" in corrections


def test_lake_spatial_dialect_aligns_binary_geometry_crs():
    from data_agent.lake_sql_executor import normalize_lake_spatial_sql

    sql, corrections = normalize_lake_spatial_sql(
        "SELECT ST_Intersection(r.geometry, p.shape) FROM roads r JOIN parcels p "
        "ON ST_Intersects(r.geometry, p.shape)",
        source_crs_by_alias={"r": "EPSG:4326", "p": "EPSG:4610"},
    )

    assert sql.count(
        "ST_TRANSFORM(r.geometry, 'EPSG:4326', 'EPSG:4610', TRUE)"
    ) == 2
    assert "duckdb_spatial_binary_crs" in corrections


def test_lake_sql_allows_semicolon_inside_string_literal():
    from data_agent.lake_sql_executor import _has_statement_separator

    assert not _has_statement_separator("SELECT SPLIT_PART(category, ';', 1) FROM places")
    assert _has_statement_separator("SELECT 1; SELECT 2")


def test_grounding_preserves_explicit_semantic_query_binding(tmp_path):
    from data_agent.nl2sql_grounding import _build_candidate_table

    governed = tmp_path / "governed.parquet"
    semantic = tmp_path / "semantic.parquet"
    source = {
        "table_name": "land_parcel_current",
        "source_kind": "offline_projection",
        "projection_id": "projection-1",
        "projection_path": str(governed),
        "execution_bindings": {
            "lake": {
                "projection_id": "projection-1",
                "projection_path": str(semantic),
            }
        },
    }
    schema = {
        "columns": [{"column_name": "_gda_area_delta_sqm", "data_type": "DOUBLE"}],
        "source_metadata": source,
    }

    candidate = _build_candidate_table(source, schema)

    assert candidate["projection_path"] == str(governed)
    assert candidate["execution_bindings"]["lake"]["projection_path"] == str(semantic)


def test_request_context_selects_lake_without_changing_global_default():
    from data_agent import nl2sql_executor
    from data_agent.user_context import current_nl2sql_requested_engine

    token = current_nl2sql_requested_engine.set("lake")
    try:
        assert nl2sql_executor._normalize_execution_engine(None) == "lake"
        assert nl2sql_executor._normalize_execution_engine("postgis") == "postgis"
    finally:
        current_nl2sql_requested_engine.reset(token)


def test_sql_generator_uses_configured_openai_compatible_local_endpoint(monkeypatch):
    from data_agent import nl2sql_executor
    from data_agent.user_context import current_nl2sql_llm_evidence

    monkeypatch.setenv("GDA_LLM_PROVIDER", "lm_studio")
    monkeypatch.setenv("GDA_LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("GDA_LLM_MODEL", "qwen-27b-local")
    evidence = {
        "provider": "lm_studio",
        "model": "qwen-27b-local",
        "request_id": "chatcmpl-local",
    }

    with patch(
        "data_agent.openai_compatible_llm.chat_completion",
        return_value=("SELECT 1", evidence),
    ) as request:
        sql = nl2sql_executor._generate_gemma_sql("PROMPT")

    assert sql == "SELECT 1"
    assert current_nl2sql_llm_evidence.get() == evidence
    assert request.call_args.kwargs["config"].base_url == "http://127.0.0.1:1234/v1"


def test_two_step_execution_result_contains_engine_and_source_binding():
    from data_agent import nl2sql_executor
    from data_agent.user_context import (
        current_nl2sql_candidate_tables,
        current_nl2sql_execution_engine,
        current_nl2sql_schemas,
    )

    tokens = [
        current_nl2sql_execution_engine.set("postgis"),
        current_nl2sql_candidate_tables.set(
            [{"table_name": "land_parcel_current", "source_kind": "postgis"}]
        ),
        current_nl2sql_schemas.set({"land_parcel_current": []}),
    ]
    try:
        annotated = json.loads(
            nl2sql_executor._annotate_execution_result(
                '{"status":"ok","rows":1}',
                "postgis",
                current_nl2sql_candidate_tables.get(),
            )
        )
        assert annotated["engine"] == "postgis"
        assert annotated["dialect"] == "postgres"
        assert annotated["source_bindings"] == [
            {
                "table_name": "land_parcel_current",
                "source_kind": "postgis",
                "physical_table": "land_parcel_current",
            }
        ]
    finally:
        current_nl2sql_schemas.reset(tokens[2])
        current_nl2sql_candidate_tables.reset(tokens[1])
        current_nl2sql_execution_engine.reset(tokens[0])
