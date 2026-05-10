"""Tests for model_gateway.family_of()."""
from __future__ import annotations

import os
import pytest

from data_agent.model_gateway import family_of


class _Fake:
    """Mimic an ADK model instance with a class name."""
    def __init__(self, cls_name, model=""):
        self._cls_name = cls_name
        self.model = model

    @property
    def __class__(self):
        class _C:
            __name__ = self._cls_name
        return _C


def _fake(cls_name: str, model: str = ""):
    """Make an object whose type().__name__ is cls_name."""
    t = type(cls_name, (object,), {})
    obj = t()
    obj.model = model
    return obj


def test_family_of_gemini():
    obj = _fake("Gemini")
    assert family_of(obj) == "gemini"


def test_family_of_deepseek_v4_flash():
    obj = _fake("LiteLlm", model="openai/deepseek-v4-flash")
    assert family_of(obj) == "deepseek"


def test_family_of_deepseek_v4_pro():
    obj = _fake("LiteLlm", model="openai/deepseek-v4-pro")
    assert family_of(obj) == "deepseek"


def test_family_of_qwen_dashscope(monkeypatch):
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    obj = _fake("LiteLlm", model="dashscope/qwen-max")
    assert family_of(obj) == "qwen"


def test_family_of_qwen_via_openai_compat(monkeypatch):
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    obj = _fake("LiteLlm", model="openai/qwen-plus")
    assert family_of(obj) == "qwen"


def test_family_of_lm_studio(monkeypatch):
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:1234/v1")
    obj = _fake("LiteLlm", model="openai/local-model")
    assert family_of(obj) == "lm_studio"


def test_family_of_generic_litellm(monkeypatch):
    """Unrecognised LiteLlm (e.g. Anthropic via LiteLLM) returns 'litellm'."""
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    obj = _fake("LiteLlm", model="anthropic/claude-sonnet-4")
    assert family_of(obj) == "litellm"


def test_family_of_unknown_class():
    obj = _fake("SomeRandomModelWrapper", model="")
    assert family_of(obj) == "unknown"


def test_family_of_deepseek_case_insensitive():
    """Case variations in model string should still match deepseek."""
    obj = _fake("LiteLlm", model="openai/DeepSeek-V4-Flash")
    assert family_of(obj) == "deepseek"


def test_family_of_gemma_distinguished_from_gemini():
    """Gemma uses ADK's Gemini wrapper class, but must be a distinct family.

    Because Gemma (e.g. gemma-4-31b-it) is served through the Gemini API and
    routes through google.adk.models.google_llm.Gemini, we detect it by model-
    string substring BEFORE the class-name check.
    """
    obj = _fake("Gemini", model="gemma-4-31b-it")
    assert family_of(obj) == "gemma"


def test_family_of_gemma_case_insensitive():
    obj = _fake("Gemini", model="Gemma-4-31B-IT")
    assert family_of(obj) == "gemma"


def test_family_of_gemini_not_confused_with_gemma():
    """gemini-2.5-flash stays 'gemini', not 'gemma'."""
    obj = _fake("Gemini", model="gemini-2.5-flash")
    assert family_of(obj) == "gemini"


def test_family_of_qwen36_flash():
    """Phase 3 target: qwen3.6-flash via dashscope / bailian."""
    obj = _fake("LiteLlm", model="dashscope/qwen3.6-flash")
    assert family_of(obj) == "qwen"
