"""Tests for prompts_nl2sql namespace loader."""
from __future__ import annotations

import pytest

from data_agent import prompts_nl2sql


def test_load_gemini_system_instruction_returns_known_text():
    """Gemini instruction must contain the legacy 'Mandatory Workflow' header."""
    text = prompts_nl2sql.load_system_instruction("gemini")
    assert "## Mandatory Workflow" in text
    assert "resolve_semantic_context" in text
    assert "describe_table_semantic" in text
    assert "ORDER BY a.geometry <-> b.geometry" in text


def test_load_unknown_family_falls_back_to_gemini():
    """Unknown families fall back to gemini's instruction (graceful degradation)."""
    text = prompts_nl2sql.load_system_instruction("nonexistent_family_xyz")
    gem = prompts_nl2sql.load_system_instruction("gemini")
    assert text == gem


def test_load_grounding_template_returns_none_when_missing():
    """Families without a grounding_template.md return None so callers fall back."""
    # gemini does not yet have a grounding_template.md (Phase 1 doesn't add one)
    assert prompts_nl2sql.load_grounding_template("gemini") is None
    assert prompts_nl2sql.load_grounding_template("deepseek") is None


def test_load_few_shots_returns_none_when_missing():
    """Families without few_shots.yaml return None."""
    assert prompts_nl2sql.load_few_shots("gemini") is None
    assert prompts_nl2sql.load_few_shots("deepseek") is None


def test_deepseek_system_instruction_is_distinct_from_gemini():
    """Phase 1 Step 4: DS now has its own R1-R7 rules instruction."""
    ds = prompts_nl2sql.load_system_instruction("deepseek")
    gem = prompts_nl2sql.load_system_instruction("gemini")
    assert ds != gem, "DS instruction must differ from Gemini after Step 4 lands"
    # DS instruction has the R1-R7 contract structure
    assert "R1." in ds and "R7." in ds
    assert "Output Contract" in ds or "output contract" in ds.lower()
    # Both still produce PostGIS instructions
    assert "PostgreSQL" in ds or "PostGIS" in ds


def test_qwen_directory_exists_for_phase_3():
    """Qwen directory must exist as a placeholder so Phase 3 can drop files in."""
    from pathlib import Path
    qwen_dir = Path(prompts_nl2sql.__file__).resolve().parent / "qwen"
    assert qwen_dir.exists() and qwen_dir.is_dir()


def test_common_domain_facts_exists():
    """common/domain_facts.md must exist so per-family files can reference it."""
    from pathlib import Path
    common = Path(prompts_nl2sql.__file__).resolve().parent / "common"
    assert (common / "domain_facts.md").exists()
    assert (common / "schema_quoting_rules.md").exists()
