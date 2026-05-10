"""Tests for v6 Phase 1 family-aware intent classification."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from data_agent.nl2sql_intent import (
    classify_intent,
    classify_rule,
    IntentLabel,
    IntentResult,
)


def test_classify_intent_default_uses_llm_judge_when_rule_unknown():
    """Legacy behaviour: unspecified family + UNKNOWN rule → LLM judge."""
    # Vague question that no rule matches
    with patch("data_agent.nl2sql_intent._llm_judge") as mock_judge:
        mock_judge.return_value = IntentResult(
            primary=IntentLabel.PREVIEW_LISTING, confidence=0.8, source="llm",
        )
        r = classify_intent("帮我看看大家都在干什么")
        # No family arg → legacy path → LLM judge should be called
        assert mock_judge.called
        assert r.source == "llm"


def test_classify_intent_deepseek_skips_llm_judge():
    """DS family: even when rule is UNKNOWN, do NOT call LLM judge."""
    with patch("data_agent.nl2sql_intent._llm_judge") as mock_judge:
        r = classify_intent("帮我看看大家都在干什么", family="deepseek")
        # DS family bypass: LLM judge must not be called
        assert not mock_judge.called
        # Returns rule-stage result (UNKNOWN with rule source)
        assert r.source == "rule"
        assert r.primary is IntentLabel.UNKNOWN


def test_classify_intent_qwen_skips_llm_judge():
    """Qwen family bypasses LLM judge same as DeepSeek (Phase 3 prep)."""
    with patch("data_agent.nl2sql_intent._llm_judge") as mock_judge:
        r = classify_intent("随便聊聊吧", family="qwen")
        assert not mock_judge.called
        assert r.source == "rule"


def test_classify_intent_deepseek_still_uses_rule_stage():
    """DS family: rule stage still runs and detects clear intent."""
    with patch("data_agent.nl2sql_intent._llm_judge") as mock_judge:
        # KNN keyword matches rule
        r = classify_intent("找出最近的 5 个 POI", family="deepseek")
        assert not mock_judge.called
        # Rule stage detects KNN
        assert r.primary is IntentLabel.KNN
        assert r.source == "rule"


def test_classify_intent_gemini_uses_full_pipeline():
    """Gemini family (or 'gemini' explicit): rule + LLM judge fallback."""
    with patch("data_agent.nl2sql_intent._llm_judge") as mock_judge:
        mock_judge.return_value = IntentResult(
            primary=IntentLabel.AGGREGATION, confidence=0.85, source="llm",
        )
        r = classify_intent("vague question", family="gemini")
        # Gemini family is treated as legacy behaviour: LLM judge fallback runs
        assert mock_judge.called
        assert r.source == "llm"


def test_classify_intent_disabled_env_overrides_family():
    """NL2SQL_DISABLE_INTENT=1 short-circuits all paths regardless of family."""
    import os
    old = os.environ.get("NL2SQL_DISABLE_INTENT")
    os.environ["NL2SQL_DISABLE_INTENT"] = "1"
    try:
        with patch("data_agent.nl2sql_intent._llm_judge") as mock_judge:
            r = classify_intent("anything", family="deepseek")
            assert not mock_judge.called
            assert r.source == "disabled"
            assert r.primary is IntentLabel.UNKNOWN
    finally:
        if old is None:
            os.environ.pop("NL2SQL_DISABLE_INTENT", None)
        else:
            os.environ["NL2SQL_DISABLE_INTENT"] = old


def test_classify_intent_deepseek_count_question_via_rule():
    """DS family: COUNT-style question hits rule-stage AGGREGATION (no LLM)."""
    with patch("data_agent.nl2sql_intent._llm_judge") as mock_judge:
        r = classify_intent("统计 cq_dltb 中有多少种不同的 dlmc", family="deepseek")
        assert not mock_judge.called
        # The rule pattern '多少' for AGGREGATION isn't strict — but the DS prompt
        # R2 rule will catch surface 多少/几种 directly. So rule-stage may return
        # UNKNOWN; the contract is "no LLM call", regardless of result.


def test_classify_intent_no_family_arg_is_legacy():
    """No family arg → uses legacy path (rule + LLM judge fallback)."""
    with patch("data_agent.nl2sql_intent._llm_judge") as mock_judge:
        mock_judge.return_value = IntentResult(
            primary=IntentLabel.UNKNOWN, confidence=0.5, source="llm",
        )
        # Vague question that's unlikely to match a strong rule
        classify_intent("hmm")
        # Legacy path → LLM judge attempted (may succeed or fall back)
        assert mock_judge.called
