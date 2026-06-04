"""Tests for major-project KG hint injection in NL2SQL grounding."""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _isolate_semantic_sources(monkeypatch):
    """Keep grounding tests deterministic and independent of live semantic cache."""
    try:
        from data_agent.semantic_layer import invalidate_semantic_cache

        invalidate_semantic_cache(None)
    except Exception:
        pass
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


def _semantic_for_major_project(table_names: list[str]) -> dict:
    return {
        "sources": [
            {
                "table_name": table_name,
                "display_name": table_name,
                "description": "重大项目测试表",
                "confidence": 0.9,
            }
            for table_name in table_names
        ],
        "matched_columns": {},
        "spatial_ops": [],
        "region_filter": None,
        "metric_hints": [],
        "hierarchy_matches": [],
        "sql_filters": [],
        "equivalences": [],
    }


def _schema_for(table_name: str) -> dict:
    columns_by_table = {
        "mp_project_list": [
            {"column_name": "project_id", "data_type": "text", "aliases": ["项目ID"]},
            {"column_name": "project_name", "data_type": "text", "aliases": ["项目名称"]},
        ],
        "mp_relation_confidence": [
            {"column_name": "project_id", "data_type": "text", "aliases": ["项目ID"]},
            {"column_name": "target_id", "data_type": "text", "aliases": ["目标地块ID"]},
            {"column_name": "confidence", "data_type": "double precision", "aliases": ["关系置信度"]},
        ],
        "mp_parcel": [
            {"column_name": "parcel_id", "data_type": "text", "aliases": ["地块ID"]},
            {"column_name": "land_type", "data_type": "text", "aliases": ["地类"]},
            {"column_name": "area_mu", "data_type": "double precision", "aliases": ["地块面积"]},
        ],
        "cq_dltb": [
            {"column_name": "bsm", "data_type": "text", "aliases": ["BSM"]},
            {"column_name": "dlmc", "data_type": "text", "aliases": ["\u5730\u7c7b\u540d\u79f0", "\u8015\u5730"]},
            {"column_name": "tbmj", "data_type": "double precision", "aliases": ["\u56fe\u6591\u9762\u79ef"]},
            {
                "column_name": "shape",
                "data_type": "USER-DEFINED",
                "aliases": ["geometry"],
                "is_geometry": True,
            },
        ],
        "mp_pre_review": [
            {"column_name": "project_id", "data_type": "text", "aliases": ["\u9879\u76eeID"]},
            {"column_name": "pre_review_status", "data_type": "text", "aliases": ["\u9884\u5ba1\u72b6\u6001"]},
        ],
        "mp_conversion_expropriation": [
            {"column_name": "project_id", "data_type": "text", "aliases": ["\u9879\u76eeID"]},
            {"column_name": "conversion_status", "data_type": "text", "aliases": ["\u519c\u8f6c\u5f81\u72b6\u6001"]},
        ],
        "mp_land_supply": [
            {"column_name": "project_id", "data_type": "text", "aliases": ["\u9879\u76eeID"]},
            {"column_name": "supply_area_mu", "data_type": "double precision", "aliases": ["\u4f9b\u5730\u9762\u79ef"]},
        ],
        "cq_buildings_2021": [
            {"column_name": "Id", "data_type": "integer", "aliases": ["建筑ID"]},
            {"column_name": "Floor", "data_type": "integer", "aliases": ["楼层"]},
        ],
        "bird_debit_card_specializing.customers": [
            {"column_name": "customerid", "data_type": "bigint", "aliases": ["客户ID"]},
            {"column_name": "segment", "data_type": "text", "aliases": ["客户分层"]},
        ],
    }
    return {
        "status": "success",
        "table_name": table_name,
        "display_name": table_name,
        "columns": columns_by_table[table_name],
    }


def _fake_intent():
    from data_agent.nl2sql_intent import IntentLabel, IntentResult

    return IntentResult(
        primary=IntentLabel.PREVIEW_LISTING,
        confidence=0.95,
        source="rule",
    )


def test_build_context_includes_major_project_kg_hints():
    from data_agent.nl2sql_grounding import build_nl2sql_context

    semantic = _semantic_for_major_project(["mp_project_list"])

    with patch("data_agent.nl2sql_grounding.classify_intent", return_value=_fake_intent()), \
         patch("data_agent.nl2sql_grounding.resolve_semantic_context", return_value=semantic), \
         patch("data_agent.nl2sql_grounding.describe_table_semantic", side_effect=_schema_for), \
         patch("data_agent.nl2sql_grounding.fetch_nl2sql_few_shots", return_value=""), \
         patch("data_agent.nl2sql_grounding._estimate_table_size", return_value=100), \
         patch("data_agent.nl2sql_grounding._build_warehouse_join_hints", return_value=None):
        result = build_nl2sql_context("列出存在审批流程断点的重大项目")

    assert result["kg_hints"]["missing_stage_filter"] is True
    assert "MISSING_STAGE" in result["kg_hints"]["required_edges"]
    assert "KG hints:" in result["grounding_prompt"]


def test_build_context_renders_relation_confidence_kg_hints():
    from data_agent.nl2sql_grounding import build_nl2sql_context

    semantic = _semantic_for_major_project(
        ["mp_project_list", "mp_relation_confidence", "mp_parcel"]
    )

    with patch("data_agent.nl2sql_grounding.classify_intent", return_value=_fake_intent()), \
         patch("data_agent.nl2sql_grounding.resolve_semantic_context", return_value=semantic), \
         patch("data_agent.nl2sql_grounding.describe_table_semantic", side_effect=_schema_for), \
         patch("data_agent.nl2sql_grounding.fetch_nl2sql_few_shots", return_value=""), \
         patch("data_agent.nl2sql_grounding._estimate_table_size", return_value=100), \
         patch("data_agent.nl2sql_grounding._build_warehouse_join_hints", return_value=None):
        result = build_nl2sql_context(
            "列出占用耕地且关系置信度大于0.9的重大项目名称和地块面积。",
            family="deepseek",
        )

    kg_hints = result["kg_hints"]
    prompt = result["grounding_prompt"]
    assert "OCCUPIES_PARCEL" in kg_hints["required_edges"]
    assert "mp_relation_confidence" in kg_hints["candidate_tables"]
    assert kg_hints["min_relation_confidence"] == 0.9
    assert "mp_project_list.project_id -> mp_relation_confidence.project_id" in kg_hints["join_paths"]
    assert "OCCUPIES_PARCEL" in prompt
    assert "mp_relation_confidence" in prompt
    assert "min_relation_confidence: 0.9" in prompt
    assert "mp_project_list.project_id -> mp_relation_confidence.project_id" in prompt


def test_format_kg_hints_renders_neo4j_backend_metadata():
    from data_agent.nl2sql_grounding import _format_kg_hints_lines

    lines = _format_kg_hints_lines({
        "matched_entities": ["\u91cd\u5927\u9879\u76ee"],
        "required_edges": ["OCCUPIES_PARCEL"],
        "graph_backend": "neo4j",
        "neo4j": {
            "status": "ok",
            "database": "zdxmdb",
            "edge_counts": {"OCCUPIES_PARCEL": 200},
        },
    })

    rendered = "\n".join(lines)
    assert "graph backend: neo4j" in rendered
    assert "database: zdxmdb" in rendered
    assert "OCCUPIES_PARCEL=200" in rendered


def test_kg_hint_tables_are_grounded_when_semantic_only_finds_project_list():
    from data_agent.nl2sql_grounding import build_nl2sql_context

    semantic = _semantic_for_major_project(["mp_project_list"])

    with patch("data_agent.nl2sql_grounding.classify_intent", return_value=_fake_intent()), \
         patch("data_agent.nl2sql_grounding.resolve_semantic_context", return_value=semantic), \
         patch("data_agent.nl2sql_grounding.describe_table_semantic", side_effect=_schema_for), \
         patch("data_agent.nl2sql_grounding.fetch_nl2sql_few_shots", return_value=""), \
         patch("data_agent.nl2sql_grounding._estimate_table_size", return_value=100), \
         patch("data_agent.nl2sql_grounding._build_warehouse_join_hints", return_value=None):
        result = build_nl2sql_context(
            "列出占用耕地且关系置信度大于0.9的重大项目名称和地块面积。",
            family="deepseek",
        )

    candidate_names = {table["table_name"] for table in result["candidate_tables"]}
    assert {"mp_project_list", "mp_relation_confidence", "mp_parcel"} <= candidate_names
    assert {"mp_project_list", "mp_relation_confidence", "mp_parcel"} <= set(
        result["kg_hints"]["candidate_tables"]
    )
    assert "### mp_relation_confidence" in result["grounding_prompt"]
    assert "### mp_parcel" in result["grounding_prompt"]
    assert "mp_project_list.project_id -> mp_relation_confidence.project_id" in result["grounding_prompt"]


def test_kg_required_tables_survive_competing_farmland_semantic_source():
    from data_agent.nl2sql_grounding import build_nl2sql_context

    semantic = _semantic_for_major_project(["mp_project_list"])
    source_list = {
        "status": "success",
        "sources": [
            {
                "table_name": "cq_dltb",
                "display_name": "\u571f\u5730\u5229\u7528\u73b0\u72b6\u56fe\u6591",
                "description": "\u5305\u542b\u8015\u5730\u7b49\u5730\u7c7b\u56fe\u6591\u4fe1\u606f",
                "synonyms": ["\u8015\u5730", "\u5730\u7c7b\u56fe\u6591"],
                "geometry_type": "MULTIPOLYGON",
                "srid": 4326,
            },
            {
                "table_name": "mp_parcel",
                "display_name": "\u91cd\u5927\u9879\u76ee\u5730\u5757",
                "description": "\u91cd\u5927\u9879\u76ee\u5173\u8054\u5730\u5757\u53ca\u5730\u7c7b",
                "synonyms": ["\u5730\u5757", "\u5730\u5757\u9762\u79ef", "\u8015\u5730"],
            },
            {
                "table_name": "mp_relation_confidence",
                "display_name": "\u91cd\u5927\u9879\u76ee\u5173\u7cfb\u7f6e\u4fe1\u5ea6",
                "description": "\u9879\u76ee\u4e0e\u5730\u5757\u7684\u5173\u7cfb\u8fb9\u7f6e\u4fe1\u5ea6",
                "synonyms": ["\u5173\u7cfb\u7f6e\u4fe1\u5ea6", "\u7f6e\u4fe1\u5ea6"],
            },
        ],
    }

    with patch("data_agent.nl2sql_grounding.classify_intent", return_value=_fake_intent()), \
         patch("data_agent.nl2sql_grounding.resolve_semantic_context", return_value=semantic), \
         patch("data_agent.nl2sql_grounding.list_semantic_sources", return_value=source_list), \
         patch("data_agent.nl2sql_grounding.describe_table_semantic", side_effect=_schema_for), \
         patch("data_agent.nl2sql_grounding.fetch_nl2sql_few_shots", return_value=""), \
         patch("data_agent.nl2sql_grounding._estimate_table_size", return_value=100), \
         patch("data_agent.nl2sql_grounding._build_warehouse_join_hints", return_value=None):
        result = build_nl2sql_context(
            "\u5217\u51fa\u5360\u7528\u8015\u5730\u4e14\u5173\u7cfb\u7f6e\u4fe1\u5ea6\u5927\u4e8e0.9\u7684\u91cd\u5927\u9879\u76ee\u540d\u79f0\u548c\u5730\u5757\u9762\u79ef\u3002",
            family="deepseek",
        )

    candidate_names = {table["table_name"] for table in result["candidate_tables"]}
    assert {"mp_project_list", "mp_relation_confidence", "mp_parcel"} <= candidate_names
    assert "OCCUPIES_PARCEL" in result["kg_hints"]["required_edges"]
    assert result["kg_hints"]["relation_confidence_filter"] is True
    assert result["kg_hints"]["min_relation_confidence"] == 0.9
    assert "mp_project_list.project_id -> mp_relation_confidence.project_id" in result["grounding_prompt"]


def test_unasked_lifecycle_tables_from_semantic_context_do_not_expand_kg_grounding():
    from data_agent.nl2sql_grounding import build_nl2sql_context

    semantic = _semantic_for_major_project(
        [
            "mp_project_list",
            "mp_pre_review",
            "mp_conversion_expropriation",
            "mp_land_supply",
        ]
    )

    with patch("data_agent.nl2sql_grounding.classify_intent", return_value=_fake_intent()), \
         patch("data_agent.nl2sql_grounding.resolve_semantic_context", return_value=semantic), \
         patch("data_agent.nl2sql_grounding.describe_table_semantic", side_effect=_schema_for), \
         patch("data_agent.nl2sql_grounding.fetch_nl2sql_few_shots", return_value=""), \
         patch("data_agent.nl2sql_grounding._estimate_table_size", return_value=100), \
         patch("data_agent.nl2sql_grounding._build_warehouse_join_hints", return_value=None):
        result = build_nl2sql_context(
            "\u5217\u51fa\u5360\u7528\u8015\u5730\u4e14\u5173\u7cfb\u7f6e\u4fe1\u5ea6\u5927\u4e8e0.9\u7684\u91cd\u5927\u9879\u76ee\u540d\u79f0\u548c\u5730\u5757\u9762\u79ef\u3002",
            family="deepseek",
        )

    candidate_names = {table["table_name"] for table in result["candidate_tables"]}
    assert candidate_names == {"mp_project_list", "mp_relation_confidence", "mp_parcel"}
    assert result["kg_hints"]["required_edges"] == ["OCCUPIES_PARCEL"]
    assert "HAS_PRE_REVIEW" not in result["grounding_prompt"]
    assert "mp_pre_review" not in result["grounding_prompt"]


def test_access_control_removes_kg_edges_when_required_tables_are_filtered():
    from data_agent.nl2sql_grounding import build_nl2sql_context
    from data_agent.user_context import current_user_role

    semantic = _semantic_for_major_project(["mp_project_list"])
    token = current_user_role.set("viewer")
    try:
        with patch("data_agent.nl2sql_grounding.classify_intent", return_value=_fake_intent()), \
             patch("data_agent.nl2sql_grounding.resolve_semantic_context", return_value=semantic), \
             patch("data_agent.nl2sql_grounding.describe_table_semantic", side_effect=_schema_for), \
             patch("data_agent.nl2sql_grounding.fetch_nl2sql_few_shots", return_value=""), \
             patch("data_agent.nl2sql_grounding._estimate_table_size", return_value=100), \
             patch("data_agent.nl2sql_grounding._build_warehouse_join_hints", return_value=None), \
             patch(
                 "data_agent.nl2sql_grounding._table_accessible",
                 side_effect=lambda table_name, role: table_name == "mp_project_list",
             ):
            result = build_nl2sql_context(
                "列出占用耕地且关系置信度大于0.9的重大项目名称和地块面积。",
                family="deepseek",
            )
    finally:
        current_user_role.reset(token)

    assert {table["table_name"] for table in result["candidate_tables"]} == {"mp_project_list"}
    assert result["kg_hints"] == {}
    assert "KG hints:" not in result["grounding_prompt"]


def test_non_major_query_has_no_kg_hints_or_prompt_block():
    from data_agent.nl2sql_grounding import build_nl2sql_context

    semantic = _semantic_for_major_project(["cq_buildings_2021"])

    with patch("data_agent.nl2sql_grounding.classify_intent", return_value=_fake_intent()), \
         patch("data_agent.nl2sql_grounding.resolve_semantic_context", return_value=semantic), \
         patch("data_agent.nl2sql_grounding.describe_table_semantic", side_effect=_schema_for), \
         patch("data_agent.nl2sql_grounding.fetch_nl2sql_few_shots", return_value=""), \
         patch("data_agent.nl2sql_grounding._estimate_table_size", return_value=100), \
         patch("data_agent.nl2sql_grounding._build_warehouse_join_hints", return_value=None):
        result = build_nl2sql_context("统计中心城区建筑数据中层高大于40层的建筑数量")

    assert result["kg_hints"] == {}
    assert "KG hints:" not in result["grounding_prompt"]


def test_schema_filter_blocks_unqualified_major_project_kg_table_injection():
    from data_agent.nl2sql_grounding import build_nl2sql_context

    semantic = _semantic_for_major_project(["bird_debit_card_specializing.customers"])

    with patch("data_agent.nl2sql_grounding.classify_intent", return_value=_fake_intent()), \
         patch("data_agent.nl2sql_grounding.resolve_semantic_context", return_value=semantic), \
         patch("data_agent.nl2sql_grounding.describe_table_semantic", side_effect=_schema_for), \
         patch("data_agent.nl2sql_grounding.fetch_nl2sql_few_shots", return_value=""), \
         patch("data_agent.nl2sql_grounding._estimate_table_size", return_value=100), \
         patch("data_agent.nl2sql_grounding._build_warehouse_join_hints", return_value=None):
        result = build_nl2sql_context(
            "列出占用耕地且关系置信度大于0.9的重大项目名称和地块面积。",
            schema_filter="bird_debit_card_specializing",
            family="deepseek",
        )

    candidate_names = {table["table_name"] for table in result["candidate_tables"]}
    assert candidate_names == {"bird_debit_card_specializing.customers"}
    assert result["kg_hints"] == {}
    assert "mp_relation_confidence" not in result["grounding_prompt"]
    assert "mp_parcel" not in result["grounding_prompt"]


def test_build_context_survives_major_project_kg_resolver_failure():
    from data_agent.nl2sql_grounding import build_nl2sql_context

    semantic = _semantic_for_major_project(["mp_project_list"])

    with patch("data_agent.nl2sql_grounding.classify_intent", return_value=_fake_intent()), \
         patch("data_agent.nl2sql_grounding.resolve_semantic_context", return_value=semantic), \
         patch("data_agent.nl2sql_grounding.describe_table_semantic", side_effect=_schema_for), \
         patch("data_agent.nl2sql_grounding.fetch_nl2sql_few_shots", return_value=""), \
         patch("data_agent.nl2sql_grounding._estimate_table_size", return_value=100), \
         patch("data_agent.nl2sql_grounding._build_warehouse_join_hints", return_value=None), \
         patch(
             "data_agent.major_project_kg_resolver.resolve_major_project_kg_hints",
             side_effect=RuntimeError("resolver unavailable"),
         ):
        result = build_nl2sql_context("列出存在审批流程断点的重大项目")

    assert result["kg_hints"] == {}
