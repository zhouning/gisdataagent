"""Unit tests for llm_schema_mapper module.

Tests focus on parsing/filtering logic — the actual LLM call is mocked.
"""
from __future__ import annotations

from unittest.mock import patch

from data_agent import llm_schema_mapper


def test_parse_clean_json():
    s = '["cq_buildings_2021", "cq_osm_roads_2021"]'
    assert llm_schema_mapper._parse_table_names(s) == ["cq_buildings_2021", "cq_osm_roads_2021"]


def test_parse_with_markdown_fences():
    s = '```json\n["a", "b"]\n```'
    assert llm_schema_mapper._parse_table_names(s) == ["a", "b"]


def test_parse_with_schema_prefix():
    s = '["public.cq_buildings", "public.cq_roads"]'
    raw = llm_schema_mapper._parse_table_names(s)
    stripped = [llm_schema_mapper._strip_schema_prefix(n) for n in raw]
    assert stripped == ["cq_buildings", "cq_roads"]


def test_parse_with_extra_prose():
    s = "The most relevant tables are:\n[\"cq_a\", \"cq_b\"]\n\nLet me know if you need more."
    assert llm_schema_mapper._parse_table_names(s) == ["cq_a", "cq_b"]


def test_parse_empty_response():
    assert llm_schema_mapper._parse_table_names("") == []


def test_parse_garbage_response():
    assert llm_schema_mapper._parse_table_names("I cannot help with that") == []


def test_filter_against_valid_names():
    valid = {"cq_a", "cq_b"}
    with patch.object(llm_schema_mapper, "_mapper_call_cached",
                      return_value='["cq_a", "fake_table", "cq_b"]'):
        result = llm_schema_mapper.select_relevant_tables(
            "test", "schema", valid_table_names=valid
        )
    assert result == ["cq_a", "cq_b"]


def test_strip_schema_prefix_filtering():
    valid = {"cq_a", "cq_b"}
    with patch.object(llm_schema_mapper, "_mapper_call_cached",
                      return_value='["public.cq_a", "public.cq_b"]'):
        result = llm_schema_mapper.select_relevant_tables(
            "test", "schema", valid_table_names=valid
        )
    assert result == ["cq_a", "cq_b"]


def test_dedup_preserves_order():
    valid = {"cq_a", "cq_b", "cq_c"}
    with patch.object(llm_schema_mapper, "_mapper_call_cached",
                      return_value='["cq_b", "cq_a", "cq_b", "cq_c"]'):
        result = llm_schema_mapper.select_relevant_tables(
            "test", "schema", valid_table_names=valid
        )
    assert result == ["cq_b", "cq_a", "cq_c"]


def test_top_k_limit():
    valid = {"cq_a", "cq_b", "cq_c", "cq_d", "cq_e", "cq_f"}
    with patch.object(llm_schema_mapper, "_mapper_call_cached",
                      return_value='["cq_a", "cq_b", "cq_c", "cq_d", "cq_e", "cq_f"]'):
        result = llm_schema_mapper.select_relevant_tables(
            "test", "schema", top_k=3, valid_table_names=valid
        )
    assert result == ["cq_a", "cq_b", "cq_c"]


def test_empty_question_returns_empty():
    assert llm_schema_mapper.select_relevant_tables("", "schema") == []


def test_llm_failure_returns_empty():
    with patch.object(llm_schema_mapper, "_mapper_call_cached",
                      side_effect=Exception("API error")):
        assert llm_schema_mapper.select_relevant_tables("q", "s") == []


def test_feature_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("NL2SQL_LLM_SCHEMA_MAPPER", raising=False)
    assert llm_schema_mapper.schema_mapper_enabled() is False


def test_feature_flag_on(monkeypatch):
    monkeypatch.setenv("NL2SQL_LLM_SCHEMA_MAPPER", "1")
    assert llm_schema_mapper.schema_mapper_enabled() is True


def test_mode_default(monkeypatch):
    monkeypatch.delenv("NL2SQL_LLM_SCHEMA_MAPPER_MODE", raising=False)
    assert llm_schema_mapper.schema_mapper_mode() == "backfill"


if __name__ == "__main__":
    import pytest, sys
    sys.exit(pytest.main([__file__, "-v"]))
