"""Tests for nl2sql_grounding.build_nl2sql_context."""
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _flush_semantic_caches(monkeypatch):
    """Reset semantic-layer state between tests.

    Sibling test files transitively trigger `load_dotenv(override=True)`
    when they importlib-load `scripts/nl2sql_bench_cq/run_cq_eval.py`,
    populating DB connection env vars AND caching a live engine. That
    state leaks into `build_nl2sql_context` → `list_semantic_sources`
    returns real CQ rows, padding candidate_tables beyond what each test
    mocked.

    Mitigation: invalidate the semantic cache, and mock
    `list_semantic_sources` to an empty-sources default so tests that
    expect only their mocked semantic.sources see exactly those. Tests
    that specifically exercise the list-fallback path provide their own
    `list_semantic_sources` override inside their with-patch block, which
    takes precedence over this fixture's autouse mock.
    """
    try:
        from data_agent.semantic_layer import invalidate_semantic_cache
        invalidate_semantic_cache(None)
    except Exception:
        pass
    # Default no-op for list_semantic_sources so autodiscovery stays quiet.
    monkeypatch.setattr(
        "data_agent.nl2sql_grounding.list_semantic_sources",
        lambda: {"status": "error", "message": "disabled in tests"},
        raising=False,
    )
    yield
    try:
        from data_agent.semantic_layer import invalidate_semantic_cache
        invalidate_semantic_cache(None)
    except Exception:
        pass


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

    assert {"candidate_tables", "semantic_hints", "few_shots", "grounding_prompt"}.issubset(result.keys())
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


def test_build_context_prioritizes_non_gis_tables_for_english_warehouse_query():
    from data_agent.nl2sql_grounding import build_nl2sql_context

    semantic = {
        "sources": [
            {
                "table_name": "cq_jsydgzq",
                "display_name": "重庆市建设用地管制区",
                "description": "GIS polygon layer",
                "geometry_type": "POLYGON",
                "confidence": 0.56,
            },
            {
                "table_name": "bird_debit_card_specializing.customers",
                "display_name": "debit_card_specializing.customers",
                "description": "BIRD mini_dev: debit_card_specializing",
                "geometry_type": None,
                "confidence": 0.70,
            },
            {
                "table_name": "bird_debit_card_specializing.yearmonth",
                "display_name": "debit_card_specializing.yearmonth",
                "description": "BIRD mini_dev: debit_card_specializing",
                "geometry_type": None,
                "confidence": 0.56,
            },
            {
                "table_name": "bird_card_games.legalities",
                "display_name": "card_games.legalities",
                "description": "BIRD mini_dev: card_games",
                "geometry_type": None,
                "confidence": 0.56,
            },
        ],
        "matched_columns": {
            "bird_debit_card_specializing.customers": [
                {"column_name": "segment", "aliases": [], "semantic_domain": None, "is_geometry": False},
                {"column_name": "currency", "aliases": [], "semantic_domain": None, "is_geometry": False},
            ],
            "bird_debit_card_specializing.yearmonth": [
                {"column_name": "date", "aliases": [], "semantic_domain": None, "is_geometry": False},
                {"column_name": "consumption", "aliases": [], "semantic_domain": None, "is_geometry": False},
            ],
        },
        "spatial_ops": [],
        "region_filter": None,
        "metric_hints": [],
        "hierarchy_matches": [],
        "sql_filters": [],
        "equivalences": [],
    }

    schemas = {
        "cq_jsydgzq": {
            "status": "success",
            "table_name": "cq_jsydgzq",
            "display_name": "重庆市建设用地管制区",
            "columns": [{"column_name": "shape", "data_type": "USER-DEFINED", "semantic_domain": None, "aliases": [], "is_geometry": True}],
            "geometry_type": "POLYGON",
            "srid": 4523,
        },
        "bird_debit_card_specializing.customers": {
            "status": "success",
            "table_name": "bird_debit_card_specializing.customers",
            "display_name": "debit_card_specializing.customers",
            "columns": [
                {"column_name": "customerid", "data_type": "bigint", "semantic_domain": None, "aliases": []},
                {"column_name": "segment", "data_type": "text", "semantic_domain": None, "aliases": []},
                {"column_name": "currency", "data_type": "text", "semantic_domain": None, "aliases": []},
            ],
        },
        "bird_debit_card_specializing.yearmonth": {
            "status": "success",
            "table_name": "bird_debit_card_specializing.yearmonth",
            "display_name": "debit_card_specializing.yearmonth",
            "columns": [
                {"column_name": "customerid", "data_type": "bigint", "semantic_domain": None, "aliases": []},
                {"column_name": "date", "data_type": "text", "semantic_domain": None, "aliases": []},
                {"column_name": "consumption", "data_type": "double precision", "semantic_domain": None, "aliases": []},
            ],
        },
        "bird_card_games.legalities": {
            "status": "success",
            "table_name": "bird_card_games.legalities",
            "display_name": "card_games.legalities",
            "columns": [
                {"column_name": "format", "data_type": "text", "semantic_domain": None, "aliases": []},
                {"column_name": "status", "data_type": "text", "semantic_domain": None, "aliases": []},
            ],
        },
    }

    def _describe(table_name: str):
        return schemas[table_name]

    with patch("data_agent.nl2sql_grounding.resolve_semantic_context", return_value=semantic), \
         patch("data_agent.nl2sql_grounding.describe_table_semantic", side_effect=_describe), \
         patch("data_agent.nl2sql_grounding.fetch_nl2sql_few_shots", return_value=""), \
         patch("data_agent.nl2sql_grounding._estimate_table_size", return_value=1000):
        result = build_nl2sql_context("What was the average monthly consumption of customers in SME for the year 2013?")

    names = [t["table_name"] for t in result["candidate_tables"]]
    assert names[:2] == [
        "bird_debit_card_specializing.customers",
        "bird_debit_card_specializing.yearmonth",
    ]
    assert "cq_jsydgzq" not in names[:2]
def test_build_context_prefers_relevant_tables_within_schema_hint():
    from data_agent.nl2sql_grounding import build_nl2sql_context

    semantic = {
        "sources": [
            {
                "table_name": "bird_debit_card_specializing.yearmonth",
                "display_name": "debit_card_specializing.yearmonth",
                "description": "BIRD mini_dev: debit_card_specializing",
                "geometry_type": None,
                "confidence": 0.56,
            },
            {
                "table_name": "bird_debit_card_specializing.gasstations",
                "display_name": "debit_card_specializing.gasstations",
                "description": "BIRD mini_dev: debit_card_specializing",
                "geometry_type": None,
                "confidence": 0.56,
            },
            {
                "table_name": "bird_debit_card_specializing.products",
                "display_name": "debit_card_specializing.products",
                "description": "BIRD mini_dev: debit_card_specializing",
                "geometry_type": None,
                "confidence": 0.56,
            },
        ],
        "matched_columns": {
            "bird_debit_card_specializing.yearmonth": [
                {"column_name": "date", "aliases": [], "semantic_domain": None, "is_geometry": False},
                {"column_name": "consumption", "aliases": [], "semantic_domain": None, "is_geometry": False},
            ],
        },
        "spatial_ops": [],
        "region_filter": None,
        "metric_hints": [],
        "hierarchy_matches": [],
        "sql_filters": [],
        "equivalences": [],
    }

    source_list = {
        "status": "success",
        "sources": [
            {
                "table_name": "bird_debit_card_specializing.customers",
                "display_name": "debit_card_specializing.customers",
                "description": "BIRD mini_dev: debit_card_specializing",
                "geometry_type": None,
                "synonyms": ["customers"],
                "suggested_analyses": [],
            },
            {
                "table_name": "bird_debit_card_specializing.transactions_1k",
                "display_name": "debit_card_specializing.transactions_1k",
                "description": "BIRD mini_dev: debit_card_specializing",
                "geometry_type": None,
                "synonyms": ["transactions_1k"],
                "suggested_analyses": [],
            },
            {
                "table_name": "bird_thrombosis_prediction.examination",
                "display_name": "thrombosis_prediction.examination",
                "description": "BIRD mini_dev: thrombosis_prediction",
                "geometry_type": None,
                "synonyms": ["examination"],
                "suggested_analyses": [],
            },
        ],
    }

    schemas = {
        "bird_debit_card_specializing.yearmonth": {
            "status": "success",
            "table_name": "bird_debit_card_specializing.yearmonth",
            "display_name": "debit_card_specializing.yearmonth",
            "columns": [
                {"column_name": "customerid", "data_type": "bigint", "semantic_domain": None, "aliases": []},
                {"column_name": "date", "data_type": "text", "semantic_domain": None, "aliases": []},
                {"column_name": "consumption", "data_type": "double precision", "semantic_domain": None, "aliases": []},
            ],
        },
        "bird_debit_card_specializing.customers": {
            "status": "success",
            "table_name": "bird_debit_card_specializing.customers",
            "display_name": "debit_card_specializing.customers",
            "columns": [
                {"column_name": "customerid", "data_type": "bigint", "semantic_domain": None, "aliases": []},
                {"column_name": "segment", "data_type": "text", "semantic_domain": None, "aliases": []},
                {"column_name": "currency", "data_type": "text", "semantic_domain": None, "aliases": []},
            ],
        },
        "bird_debit_card_specializing.gasstations": {
            "status": "success",
            "table_name": "bird_debit_card_specializing.gasstations",
            "display_name": "debit_card_specializing.gasstations",
            "columns": [
                {"column_name": "gasstationid", "data_type": "bigint", "semantic_domain": None, "aliases": []},
                {"column_name": "country", "data_type": "text", "semantic_domain": None, "aliases": []},
                {"column_name": "segment", "data_type": "text", "semantic_domain": None, "aliases": []},
            ],
        },
        "bird_debit_card_specializing.products": {
            "status": "success",
            "table_name": "bird_debit_card_specializing.products",
            "display_name": "debit_card_specializing.products",
            "columns": [
                {"column_name": "productid", "data_type": "bigint", "semantic_domain": None, "aliases": []},
                {"column_name": "description", "data_type": "text", "semantic_domain": None, "aliases": []},
            ],
        },
        "bird_debit_card_specializing.transactions_1k": {
            "status": "success",
            "table_name": "bird_debit_card_specializing.transactions_1k",
            "display_name": "debit_card_specializing.transactions_1k",
            "columns": [
                {"column_name": "customerid", "data_type": "bigint", "semantic_domain": None, "aliases": []},
                {"column_name": "amount", "data_type": "double precision", "semantic_domain": None, "aliases": []},
                {"column_name": "price", "data_type": "double precision", "semantic_domain": None, "aliases": []},
            ],
        },
        "bird_thrombosis_prediction.examination": {
            "status": "success",
            "table_name": "bird_thrombosis_prediction.examination",
            "display_name": "thrombosis_prediction.examination",
            "columns": [
                {"column_name": "id", "data_type": "bigint", "semantic_domain": None, "aliases": []},
            ],
        },
    }

    def _describe(table_name: str):
        return schemas[table_name]

    def _values(table_name: str, column_name: str, limit: int = 8):
        mapping = {
            ("bird_debit_card_specializing.customers", "segment"): ["SME", "LAM", "KAM"],
            ("bird_debit_card_specializing.customers", "currency"): ["CZK", "EUR"],
            ("bird_debit_card_specializing.gasstations", "segment"): ["Discount", "Premium"],
            ("bird_debit_card_specializing.gasstations", "country"): ["CZE", "SVK"],
        }
        return mapping.get((table_name, column_name), [])

    user_text = (
        "Database: PostgreSQL schema `bird_debit_card_specializing`. "
        "In 2012, who had the least consumption in LAM?"
    )

    with patch("data_agent.nl2sql_grounding.resolve_semantic_context", return_value=semantic), \
         patch("data_agent.nl2sql_grounding.list_semantic_sources", return_value=source_list), \
         patch("data_agent.nl2sql_grounding.describe_table_semantic", side_effect=_describe), \
         patch("data_agent.nl2sql_grounding._sample_distinct_values", side_effect=_values), \
         patch("data_agent.nl2sql_grounding.fetch_nl2sql_few_shots", return_value=""), \
         patch("data_agent.nl2sql_grounding._estimate_table_size", return_value=1000):
        result = build_nl2sql_context(user_text)

    names = [t["table_name"] for t in result["candidate_tables"]]
    assert set(names[:2]) == {
        "bird_debit_card_specializing.yearmonth",
        "bird_debit_card_specializing.customers",
    }
    assert "bird_debit_card_specializing.gasstations" not in names[:2]
    assert "bird_debit_card_specializing.products" not in names[:2]
    assert "bird_thrombosis_prediction.examination" not in names[:2]



    semantic = {
        "sources": [
            {
                "table_name": "bird_debit_card_specializing.gasstations",
                "display_name": "debit_card_specializing.gasstations",
                "description": "BIRD mini_dev: debit_card_specializing",
                "geometry_type": None,
                "confidence": 0.65,
            },
            {
                "table_name": "bird_european_football_2.country",
                "display_name": "european_football_2.country",
                "description": "BIRD mini_dev: european_football_2",
                "geometry_type": None,
                "confidence": 0.65,
            },
        ],
        "matched_columns": {
            "bird_debit_card_specializing.gasstations": [
                {"column_name": "country", "aliases": [], "semantic_domain": None, "is_geometry": False},
                {"column_name": "segment", "aliases": [], "semantic_domain": None, "is_geometry": False},
            ],
        },
        "spatial_ops": [],
        "region_filter": None,
        "metric_hints": [],
        "hierarchy_matches": [],
        "sql_filters": [],
        "equivalences": [],
    }

    schemas = {
        "bird_debit_card_specializing.gasstations": {
            "status": "success",
            "table_name": "bird_debit_card_specializing.gasstations",
            "display_name": "debit_card_specializing.gasstations",
            "columns": [
                {"column_name": "gasstationid", "data_type": "bigint", "semantic_domain": None, "aliases": []},
                {"column_name": "country", "data_type": "text", "semantic_domain": None, "aliases": []},
                {"column_name": "segment", "data_type": "text", "semantic_domain": None, "aliases": []},
            ],
        },
        "bird_european_football_2.country": {
            "status": "success",
            "table_name": "bird_european_football_2.country",
            "display_name": "european_football_2.country",
            "columns": [
                {"column_name": "id", "data_type": "bigint", "semantic_domain": None, "aliases": []},
                {"column_name": "name", "data_type": "text", "semantic_domain": None, "aliases": []},
            ],
        },
    }

    def _describe(table_name: str):
        return schemas[table_name]

    def _values(table_name: str, column_name: str, limit: int = 5):
        mapping = {
            ("bird_debit_card_specializing.gasstations", "country"): ["CZE", "SVK"],
            ("bird_debit_card_specializing.gasstations", "segment"): ["Discount", "Premium"],
        }
        return mapping.get((table_name, column_name), [])

    with patch("data_agent.nl2sql_grounding.resolve_semantic_context", return_value=semantic), \
         patch("data_agent.nl2sql_grounding.describe_table_semantic", side_effect=_describe), \
         patch("data_agent.nl2sql_grounding._sample_distinct_values", side_effect=_values), \
         patch("data_agent.nl2sql_grounding.fetch_nl2sql_few_shots") as mock_few_shots, \
         patch("data_agent.nl2sql_grounding._estimate_table_size", return_value=1000):
        result = build_nl2sql_context("How many more \"discount\" gas stations does the Czech Republic have compared to Slovakia?")

    text = result["grounding_prompt"]
    assert "示例值" in text
    assert "CZE" in text and "SVK" in text
    assert "Discount" in text
    mock_few_shots.assert_not_called()


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


def test_format_grounding_prompt_includes_warehouse_join_hints():
    """When warehouse_join_hints is present and spatial_query=False, inject join-path section."""
    from data_agent.nl2sql_grounding import _format_grounding_prompt

    payload = {
        "candidate_tables": [
            {
                "table_name": "bird_debit_card_specializing.customers",
                "display_name": "customers",
                "confidence": 0.8,
                "row_count_hint": 100,
                "columns": [
                    {"column_name": "customerid", "pg_type": "bigint", "quoted_ref": "customerid",
                     "aliases": [], "needs_quoting": False},
                    {"column_name": "segment", "pg_type": "text", "quoted_ref": "segment",
                     "aliases": [], "needs_quoting": False},
                ],
            },
            {
                "table_name": "bird_debit_card_specializing.yearmonth",
                "display_name": "yearmonth",
                "confidence": 0.7,
                "row_count_hint": 500,
                "columns": [
                    {"column_name": "customerid", "pg_type": "bigint", "quoted_ref": "customerid",
                     "aliases": [], "needs_quoting": False},
                    {"column_name": "consumption", "pg_type": "double precision",
                     "quoted_ref": "consumption", "aliases": [], "needs_quoting": False},
                ],
            },
        ],
        "semantic_hints": {
            "spatial_ops": [], "region_filter": None,
            "metric_hints": [], "hierarchy_matches": [], "sql_filters": [],
        },
        "few_shots": [],
        "warehouse_join_hints": {
            "table_roles": {
                "bird_debit_card_specializing.customers": {"role": "dimension", "entities": ["CustomerID"]},
                "bird_debit_card_specializing.yearmonth": {"role": "fact", "entities": ["CustomerID"], "measures": ["Consumption"]},
            },
            "join_paths": [
                "yearmonth.CustomerID -> customers.CustomerID",
            ],
        },
    }
    text = _format_grounding_prompt(payload)
    assert "Join 路径提示" in text
    assert "CustomerID" in text
    assert "dimension" in text or "维度" in text
    assert "fact" in text or "事实" in text


def test_format_grounding_prompt_no_warehouse_hints_for_spatial():
    """When spatial_ops are present, warehouse join hints should NOT appear."""
    from data_agent.nl2sql_grounding import _format_grounding_prompt

    payload = {
        "candidate_tables": [],
        "semantic_hints": {
            "spatial_ops": ["ST_Intersects"], "region_filter": "重庆",
            "metric_hints": [], "hierarchy_matches": [], "sql_filters": [],
        },
        "few_shots": [],
        "warehouse_join_hints": {
            "table_roles": {"t1": {"role": "fact", "entities": ["id"], "measures": ["val"]}},
            "join_paths": ["t1.id -> t2.id"],
        },
    }
    text = _format_grounding_prompt(payload)
    assert "Join 路径提示" not in text


def test_build_context_injects_warehouse_hints_from_semantic_model():
    """build_nl2sql_context should look up SemanticModelStore and inject warehouse hints."""
    from data_agent.nl2sql_grounding import build_nl2sql_context

    semantic = {
        "sources": [
            {"table_name": "bird_debit_card_specializing.customers",
             "display_name": "customers", "description": "", "geometry_type": None, "confidence": 0.8},
            {"table_name": "bird_debit_card_specializing.yearmonth",
             "display_name": "yearmonth", "description": "", "geometry_type": None, "confidence": 0.7},
        ],
        "matched_columns": {},
        "spatial_ops": [], "region_filter": None,
        "metric_hints": [], "hierarchy_matches": [], "sql_filters": [], "equivalences": [],
    }
    schemas = {
        "bird_debit_card_specializing.customers": {
            "status": "success", "table_name": "bird_debit_card_specializing.customers",
            "columns": [
                {"column_name": "customerid", "data_type": "bigint", "semantic_domain": None, "aliases": []},
                {"column_name": "segment", "data_type": "text", "semantic_domain": None, "aliases": []},
            ],
        },
        "bird_debit_card_specializing.yearmonth": {
            "status": "success", "table_name": "bird_debit_card_specializing.yearmonth",
            "columns": [
                {"column_name": "customerid", "data_type": "bigint", "semantic_domain": None, "aliases": []},
                {"column_name": "consumption", "data_type": "double precision", "semantic_domain": None, "aliases": []},
            ],
        },
    }

    # Fake semantic models from SemanticModelStore
    model_customers = {
        "name": "bird_debit_card_specializing.customers",
        "entities": [{"name": "CustomerID", "column": "customerid"}],
        "measures": [],
        "dimensions": [{"name": "segment", "type": "categorical"}],
    }
    model_yearmonth = {
        "name": "bird_debit_card_specializing.yearmonth",
        "entities": [{"name": "CustomerID", "column": "customerid"}],
        "measures": [{"name": "Consumption", "agg": "sum", "column": "consumption"}],
        "dimensions": [],
    }

    def _store_get(name):
        return {"bird_debit_card_specializing.customers": model_customers,
                "bird_debit_card_specializing.yearmonth": model_yearmonth}.get(name)

    with patch("data_agent.nl2sql_grounding.resolve_semantic_context", return_value=semantic), \
         patch("data_agent.nl2sql_grounding.describe_table_semantic", side_effect=lambda t: schemas[t]), \
         patch("data_agent.nl2sql_grounding.fetch_nl2sql_few_shots", return_value=""), \
         patch("data_agent.nl2sql_grounding._estimate_table_size", return_value=500), \
         patch("data_agent.nl2sql_grounding.SemanticModelStore") as MockStore:
        MockStore.return_value.get.side_effect = _store_get
        result = build_nl2sql_context("What is the average consumption of SME customers?")

    assert "warehouse_join_hints" in result
    hints = result["warehouse_join_hints"]
    assert "bird_debit_card_specializing.customers" in hints["table_roles"]
    assert hints["table_roles"]["bird_debit_card_specializing.customers"]["role"] == "dimension"
    assert "Join 路径提示" in result["grounding_prompt"]


def test_format_grounding_prompt_attribute_filter_omits_limit_rule():
    from data_agent.nl2sql_grounding import _format_grounding_prompt
    from data_agent.nl2sql_intent import IntentLabel
    payload = {"candidate_tables": [], "semantic_hints": {}, "intent": IntentLabel.ATTRIBUTE_FILTER}
    out = _format_grounding_prompt(payload)
    assert "大表全表扫描必须有 LIMIT" not in out


def test_format_grounding_prompt_preview_listing_keeps_limit_rule():
    from data_agent.nl2sql_grounding import _format_grounding_prompt
    from data_agent.nl2sql_intent import IntentLabel
    payload = {"candidate_tables": [], "semantic_hints": {}, "intent": IntentLabel.PREVIEW_LISTING}
    out = _format_grounding_prompt(payload)
    assert "大表全表扫描必须有 LIMIT" in out


def test_format_grounding_prompt_knn_emphasizes_arrow_operator():
    from data_agent.nl2sql_grounding import _format_grounding_prompt
    from data_agent.nl2sql_intent import IntentLabel
    payload = {"candidate_tables": [], "semantic_hints": {}, "intent": IntentLabel.KNN}
    out = _format_grounding_prompt(payload)
    assert "<->" in out


def test_build_nl2sql_context_attaches_intent_to_payload():
    from unittest.mock import patch
    from data_agent.nl2sql_grounding import build_nl2sql_context
    from data_agent.nl2sql_intent import IntentLabel, IntentResult

    fake = IntentResult(primary=IntentLabel.ATTRIBUTE_FILTER, confidence=0.95, source="rule")
    with patch("data_agent.nl2sql_grounding.classify_intent", return_value=fake), \
         patch("data_agent.nl2sql_grounding.resolve_semantic_context", return_value={
             "sources": [], "matched_columns": {}, "spatial_ops": [], "region_filter": None,
             "metric_hints": [], "hierarchy_matches": [], "equivalences": [], "sql_filters": [],
         }):
        payload = build_nl2sql_context("列出 fclass = 'primary' 的道路")
    assert payload["intent"] is IntentLabel.ATTRIBUTE_FILTER
    assert "intent_source" in payload
