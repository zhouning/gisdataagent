"""Tests for nl2sql_grounding.build_nl2sql_context."""
from unittest.mock import patch


def test_build_context_returns_expected_keys():
    from data_agent.nl2sql_grounding import build_nl2sql_context

    semantic = {
        "sources": [{
            "table_name": "cq_buildings_2021",
            "display_name": "重庆建筑物数据",
            "description": "建筑物轮廓",
            "confidence": 0.9,
        }],
        "matched_columns": {
            "cq_buildings_2021": [
                {"column_name": "Floor", "aliases": ["层高", "层数"], "semantic_domain": "HEIGHT"}
            ]
        },
        "spatial_ops": [],
        "region_filter": None,
        "metric_hints": [],
        "hierarchy_matches": [],
        "sql_filters": [],
        "equivalences": [],
    }
    schema = {
        "status": "success",
        "table_name": "cq_buildings_2021",
        "display_name": "重庆建筑物数据",
        "columns": [
            {"column_name": "Id", "data_type": "integer", "semantic_domain": None, "aliases": []},
            {"column_name": "Floor", "data_type": "integer", "semantic_domain": "HEIGHT", "aliases": ["层高", "层数"]},
            {"column_name": "geometry", "data_type": "USER-DEFINED", "semantic_domain": None, "aliases": [], "is_geometry": True},
        ],
    }
    with patch("data_agent.nl2sql_grounding.resolve_semantic_context", return_value=semantic), \
         patch("data_agent.nl2sql_grounding.describe_table_semantic", return_value=schema), \
         patch("data_agent.nl2sql_grounding.fetch_nl2sql_few_shots", return_value="参考查询示例:\nQ: ...\nSQL: SELECT ..."), \
         patch("data_agent.nl2sql_grounding._estimate_table_size", return_value=107035):
        result = build_nl2sql_context("统计层高>=40的建筑数量")

    assert set(result.keys()) == {"candidate_tables", "semantic_hints", "few_shots", "grounding_prompt"}
    assert len(result["candidate_tables"]) == 1
    table = result["candidate_tables"][0]
    assert table["table_name"] == "cq_buildings_2021"
    assert table["row_count_hint"] == 107035
    cols = {c["column_name"]: c for c in table["columns"]}
    assert cols["Floor"]["quoted_ref"] == '"Floor"'
    assert cols["geometry"]["quoted_ref"] == "geometry"
    assert cols["Floor"]["needs_quoting"] is True


def test_build_context_fallbacks_to_list_sources_when_semantic_has_no_sources():
    from data_agent.nl2sql_grounding import build_nl2sql_context

    semantic = {
        "sources": [], "matched_columns": {}, "spatial_ops": [], "region_filter": None,
        "metric_hints": [], "hierarchy_matches": [], "sql_filters": [], "equivalences": [],
    }
    source_list = {
        "status": "success",
        "sources": [
            {
                "table_name": "cq_buildings_2021",
                "display_name": "重庆建筑物数据",
                "description": "重庆市建筑物轮廓数据",
                "synonyms": ["建筑数据", "中心城区建筑数据"],
                "geometry_type": "MULTIPOLYGON",
                "srid": 4326,
                "suggested_analyses": [],
            }
        ],
    }
    schema = {
        "status": "success",
        "table_name": "cq_buildings_2021",
        "display_name": "重庆建筑物数据",
        "columns": [
            {"column_name": "Id", "data_type": "integer", "semantic_domain": None, "aliases": []},
            {"column_name": "Floor", "data_type": "integer", "semantic_domain": "HEIGHT", "aliases": ["层高"]},
        ],
    }
    with patch("data_agent.nl2sql_grounding.resolve_semantic_context", return_value=semantic), \
         patch("data_agent.nl2sql_grounding.list_semantic_sources", return_value=source_list), \
         patch("data_agent.nl2sql_grounding.describe_table_semantic", return_value=schema), \
         patch("data_agent.nl2sql_grounding.fetch_nl2sql_few_shots", return_value=""), \
         patch("data_agent.nl2sql_grounding._estimate_table_size", return_value=107035):
        result = build_nl2sql_context("统计中心城区建筑数据中层高>=40的数量")

    assert len(result["candidate_tables"]) == 1
    assert result["candidate_tables"][0]["table_name"] == "cq_buildings_2021"


def test_grounding_prompt_contains_postgres_quote_warning():
    from data_agent.nl2sql_grounding import _format_grounding_prompt

    payload = {
        "candidate_tables": [
            {
                "table_name": "cq_buildings_2021",
                "display_name": "重庆建筑物数据",
                "confidence": 0.9,
                "row_count_hint": 107035,
                "columns": [
                    {"column_name": "Id", "pg_type": "integer", "quoted_ref": '"Id"', "aliases": ["编号"], "needs_quoting": True},
                    {"column_name": "Floor", "pg_type": "integer", "quoted_ref": '"Floor"', "aliases": ["层高"], "needs_quoting": True},
                    {"column_name": "geometry", "pg_type": "geometry", "quoted_ref": "geometry", "aliases": [], "needs_quoting": False},
                ],
            }
        ],
        "semantic_hints": {"spatial_ops": [], "region_filter": None, "metric_hints": [], "hierarchy_matches": [], "sql_filters": []},
        "few_shots": [
            {"question": "统计建筑数量", "sql": 'SELECT COUNT(*) FROM cq_buildings_2021 WHERE "Floor" >= 40;'}
        ],
    }
    text = _format_grounding_prompt(payload)
    assert "PostgreSQL" in text
    assert '"Floor"' in text
    assert '"Id"' in text
    assert "参考 SQL" in text or "参考查询示例" in text
