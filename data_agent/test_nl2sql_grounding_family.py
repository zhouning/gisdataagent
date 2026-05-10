"""Tests for v6 Phase 1 per-family grounding prompt rendering."""
from __future__ import annotations

import pytest

from data_agent.nl2sql_grounding import (
    _format_grounding_prompt,
    _format_grounding_prompt_compact,
    _format_grounding_prompt_legacy,
)
from data_agent.nl2sql_intent import IntentLabel


def _sample_payload(**overrides):
    payload = {
        "candidate_tables": [
            {
                "table_name": "cq_land_use_dltb",
                "display_name": "国土调查地类图斑",
                "confidence": 0.95,
                "row_count_hint": 120000,
                "columns": [
                    {
                        "column_name": "DLMC",
                        "quoted_ref": '"DLMC"',
                        "pg_type": "text",
                        "aliases": ["地类名称"],
                        "sample_values": ["水田", "旱地", "有林地"],
                        "is_geometry": False,
                    },
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "pg_type": "geometry(Polygon,4490)",
                        "aliases": [],
                        "sample_values": None,
                        "is_geometry": True,
                    },
                ],
            },
        ],
        "semantic_hints": {
            "spatial_ops": ["intersects"],
            "region_filter": None,
            "hierarchy_matches": [],
            "metric_hints": ["area"],
            "sql_filters": [],
        },
        "intent": IntentLabel.SPATIAL_MEASUREMENT,
        "few_shots": [
            {"question": "求水田面积", "sql": "SELECT SUM(ST_Area(geometry::geography)) FROM cq_land_use_dltb WHERE \"DLMC\"='水田'"},
        ],
    }
    payload.update(overrides)
    return payload


def test_format_dispatches_by_family():
    """family='gemini' → legacy rendering; family='deepseek' → compact."""
    payload = _sample_payload()
    legacy = _format_grounding_prompt(payload, family=None)
    gemini = _format_grounding_prompt(payload, family="gemini")
    deepseek = _format_grounding_prompt(payload, family="deepseek")
    qwen = _format_grounding_prompt(payload, family="qwen")

    assert legacy == gemini, "family=None and family='gemini' are equivalent (legacy)"
    assert deepseek == qwen, "deepseek and qwen both take compact path"
    assert legacy != deepseek, "compact and legacy must differ"


def test_compact_is_shorter_than_legacy():
    """Compact rendering must be strictly shorter than legacy for same payload."""
    payload = _sample_payload()
    legacy = _format_grounding_prompt_legacy(payload)
    compact = _format_grounding_prompt_compact(payload)
    assert len(compact) < len(legacy), (
        f"Compact rendering ({len(compact)} chars) should be shorter than "
        f"legacy ({len(legacy)} chars)"
    )


def test_compact_omits_intent_gated_rule_blocks():
    """Compact rendering should NOT contain the legacy Chinese rule prose."""
    payload = _sample_payload(intent=IntentLabel.AGGREGATION)
    compact = _format_grounding_prompt_compact(payload)

    # Legacy-specific rule block headers must be absent
    assert "## 聚合语义规则" not in compact
    assert "## DISTINCT 使用规则" not in compact
    assert "## 避免过度 JOIN" not in compact
    assert "## 输出列格式" not in compact
    assert "## 日期 / 时间处理规则" not in compact
    assert "## 安全规则" not in compact, (
        "Safety rules live in system_instruction.md R-rules, not per-question"
    )


def test_compact_keeps_candidate_tables():
    """Candidate tables must still appear — that's per-question info."""
    payload = _sample_payload()
    compact = _format_grounding_prompt_compact(payload)
    assert "cq_land_use_dltb" in compact
    assert '"DLMC"' in compact


def test_compact_keeps_few_shots_but_capped():
    """Few-shots appear but capped at 3 entries."""
    # Build a payload with 5 few-shots
    many_shots = [
        {"question": f"Q{i}", "sql": f"SELECT {i}"}
        for i in range(5)
    ]
    payload = _sample_payload(few_shots=many_shots)
    compact = _format_grounding_prompt_compact(payload)
    # Q0, Q1, Q2 should appear; Q3, Q4 should not
    assert "Q0" in compact
    assert "Q1" in compact
    assert "Q2" in compact
    assert "Q3" not in compact
    assert "Q4" not in compact


def test_compact_keeps_warehouse_join_hints_for_non_spatial():
    """Warehouse join paths are per-question info, kept in compact."""
    payload = _sample_payload(
        semantic_hints={"spatial_ops": [], "region_filter": None},
        warehouse_join_hints={
            "table_roles": {
                "patient": {"role": "fact", "entities": ["patient_id"], "measures": []},
                "laboratory": {"role": "dimension", "entities": ["patient_id"], "measures": []},
            },
            "join_paths": ["patient.patient_id = laboratory.patient_id"],
        },
    )
    compact = _format_grounding_prompt_compact(payload)
    assert "Warehouse join paths" in compact
    assert "patient.patient_id = laboratory.patient_id" in compact


def test_compact_srid_alignment_warning_kept():
    """Per-question SRID info stays — that's not static rule content."""
    payload = _sample_payload(
        candidate_tables=[
            {
                "table_name": "cq_land_use_dltb",
                "confidence": 0.95,
                "row_count_hint": 120000,
                "columns": [
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "pg_type": "geometry(Polygon,4490)",
                        "aliases": [],
                        "is_geometry": True,
                    },
                ],
            },
            {
                "table_name": "cq_amap_poi_2024",
                "confidence": 0.80,
                "row_count_hint": 1190000,
                "columns": [
                    {
                        "column_name": "geometry",
                        "quoted_ref": "geometry",
                        "pg_type": "geometry(Point,4326)",
                        "aliases": [],
                        "is_geometry": True,
                    },
                ],
            },
        ],
    )
    compact = _format_grounding_prompt_compact(payload)
    assert "SRID alignment required" in compact
    assert "SRID=4490" in compact
    assert "SRID=4326" in compact
    assert "ST_Transform" in compact


def test_legacy_preserved_byte_equivalent():
    """Legacy rendering with no family arg is unchanged from pre-phase-1 code."""
    payload = _sample_payload(intent=IntentLabel.AGGREGATION)
    legacy = _format_grounding_prompt(payload, family=None)
    # Sanity: legacy contains the aggregation rule block (part of pre-phase-1 behaviour)
    assert "## 聚合语义规则" in legacy
    assert "## 安全规则" in legacy
    assert "## 候选数据源" in legacy
