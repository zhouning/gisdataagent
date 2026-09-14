"""Tests for the versioned NL2SQL model compatibility profile."""
from __future__ import annotations

from data_agent.nl2sql_model_profile import (
    infer_model_family,
    profile_for_model,
    resolve_nl2sql_model_profile,
)


def test_infer_model_family_distinguishes_gemma_from_gemini():
    assert infer_model_family("gemma4:26b") == "gemma"
    assert infer_model_family("gemini-2.5-flash") == "gemini"


def test_local_profile_is_explicit_and_serialisable():
    profile = resolve_nl2sql_model_profile("ollama_chat/qwen3.8:latest")
    assert profile.family == "qwen"
    assert profile.grounding_variant == "compact"
    assert profile.intent_strategy == "rule_only"
    assert profile.structured_output_mode == "adk_output_schema"
    assert profile.semantic_ir_enabled is True
    payload = profile_for_model("ollama_chat/qwen3.8:latest")
    assert payload["profile_version"] == "nl2sql-model-profile-v1"
    assert len(payload["fingerprint"]) == 64


def test_gemini_profile_preserves_legacy_compatibility():
    profile = resolve_nl2sql_model_profile("gemini-2.5-flash")
    assert profile.family == "gemini"
    assert profile.grounding_variant == "legacy"
    assert profile.intent_strategy == "rule_then_llm"
    assert profile.structured_output_mode.startswith("native_")


def test_profile_fingerprint_changes_with_model_identity():
    a = resolve_nl2sql_model_profile("gemma4:26b")
    b = resolve_nl2sql_model_profile("gemma4:31b")
    assert a.fingerprint != b.fingerprint


def test_gateway_route_alias_has_the_same_profile_identity_as_configured_model(monkeypatch):
    monkeypatch.setenv("GDA_LLM_PROVIDER", "ollama")
    configured = resolve_nl2sql_model_profile("gemma4:26b")
    routed = resolve_nl2sql_model_profile("ollama_chat/gemma4:26b")

    assert routed.model_id == configured.model_id
    assert routed.fingerprint == configured.fingerprint


def test_local_gemma_profile_bounds_each_attempt_inside_the_request_budget(monkeypatch):
    monkeypatch.setenv("GDA_LLM_PROVIDER", "ollama")
    profile = resolve_nl2sql_model_profile("gemma4:26b")

    assert profile.max_generation_attempts == 3
    assert profile.generation_attempt_timeout_seconds == 90
    assert profile.max_generation_output_tokens == 1280
    assert profile.temperature == 0.0
