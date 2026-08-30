from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from data_agent.dltb_llm_query import parse_semantic_ast
from data_agent.openai_compatible_llm import (
    LLMServiceError,
    OpenAICompatibleLLMConfig,
    chat_completion,
    infer_llm_provider,
    normalize_deepseek_base_url,
    normalize_openai_base_url,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://127.0.0.1:11434", "http://127.0.0.1:11434/v1"),
        ("http://127.0.0.1:1234/v1/", "http://127.0.0.1:1234/v1"),
        (
            "http://10.0.0.8:1234/v1/chat/completions",
            "http://10.0.0.8:1234/v1",
        ),
        (
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            "https://generativelanguage.googleapis.com/v1beta/openai",
        ),
        ("10.0.0.8:11434", "http://10.0.0.8:11434/v1"),
    ],
)
def test_normalize_openai_base_url(raw, expected):
    assert normalize_openai_base_url(raw) == expected


def test_provider_inference_distinguishes_ollama_and_lm_studio():
    assert infer_llm_provider("http://127.0.0.1:11434/v1") == "ollama"
    assert infer_llm_provider("http://127.0.0.1:1234/v1") == "lm_studio"


def test_deepseek_responses_base_url_and_provider():
    assert normalize_deepseek_base_url("https://api.deepseek.com/v1") == "https://api.deepseek.com"
    assert normalize_deepseek_base_url("https://api.deepseek.com/responses") == "https://api.deepseek.com"
    assert infer_llm_provider("https://api.deepseek.com", "deepseek") == "deepseek"


def test_openai_provider_uses_openai_key(monkeypatch):
    monkeypatch.setenv("GDA_LLM_PROVIDER", "openai")
    monkeypatch.delenv("GDA_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("GDA_LLM_MODEL", "gpt-5.6-terra")
    monkeypatch.setenv("GDA_LLM_API_KEY", "stale-generic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-dedicated-key")

    config = OpenAICompatibleLLMConfig.from_env()

    assert config.provider == "openai"
    assert config.api_key == "openai-dedicated-key"
    assert config.base_url == "https://api.openai.com/v1"
    assert config.api_style == "chat"


def test_env_config_uses_gemini_dedicated_key_and_openai_root(monkeypatch):
    monkeypatch.setenv("GDA_LLM_PROVIDER", "gemini")
    monkeypatch.setenv(
        "GDA_LLM_BASE_URL",
        "https://generativelanguage.googleapis.com/v1beta/openai",
    )
    monkeypatch.setenv("GDA_LLM_MODEL", "gemini-3.6-flash")
    monkeypatch.setenv("GDA_LLM_API_KEY", "stale-generic-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-dedicated-key")
    monkeypatch.setenv("GDA_LLM_API_STYLE", "chat")

    config = OpenAICompatibleLLMConfig.from_env()

    assert config.provider == "gemini"
    assert config.api_key == "gemini-dedicated-key"
    assert config.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert config.chat_completions_url.endswith("/v1beta/openai/chat/completions")


def test_env_config_uses_deepseek_key_and_responses_style(monkeypatch):
    monkeypatch.setenv("GDA_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("GDA_LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("GDA_LLM_MODEL", "deepseek-v4-flash")
    monkeypatch.delenv("GDA_LLM_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-only")
    config = OpenAICompatibleLLMConfig.from_env()
    assert config.base_url == "https://api.deepseek.com"
    assert config.responses_url == "https://api.deepseek.com/responses"
    assert config.api_style == "responses"
    assert config.api_key == "sk-test-only"


def test_env_config_accepts_full_completion_url(monkeypatch):
    monkeypatch.setenv("GDA_LLM_BASE_URL", "http://nx-llm:1234/v1/chat/completions")
    monkeypatch.setenv("GDA_LLM_PROVIDER", "lm_studio")
    monkeypatch.setenv("GDA_LLM_MODEL", "qwen-27b")
    config = OpenAICompatibleLLMConfig.from_env()
    assert config.base_url == "http://nx-llm:1234/v1"
    assert config.chat_completions_url == "http://nx-llm:1234/v1/chat/completions"
    assert config.model == "qwen-27b"


def test_chat_completion_records_model_endpoint_and_hashes():
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                id="chatcmpl-test",
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"intent":"dataset_summary"}'))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4, total_tokens=14),
            )

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    config = OpenAICompatibleLLMConfig(
        "ollama", "http://127.0.0.1:11434/v1", "Qwen3.6:27b", "ollama", 30
    )
    text, evidence = chat_completion(
        system_prompt="system",
        user_prompt="question",
        config=config,
        client_factory=FakeClient,
    )
    assert json.loads(text)["intent"] == "dataset_summary"
    assert captured["model"] == "Qwen3.6:27b"
    assert captured["reasoning_effort"] == "none"
    assert evidence["endpoint"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert evidence["request_id"] == "chatcmpl-test"
    assert len(evidence["prompt_sha256"]) == 64


def test_chat_completion_can_explicitly_disable_qwen_thinking(monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                id="chatcmpl-qwen-online",
                choices=[SimpleNamespace(message=SimpleNamespace(content="SELECT 1"))],
                usage=SimpleNamespace(prompt_tokens=8, completion_tokens=3, total_tokens=11),
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("GDA_LLM_ENABLE_THINKING", "false")
    config = OpenAICompatibleLLMConfig(
        "openai_compatible",
        "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "qwen3.8-max",
        "sk-test",
        30,
        "chat",
    )
    text, evidence = chat_completion(
        system_prompt="system",
        user_prompt="question",
        config=config,
        max_tokens=8192,
        client_factory=FakeClient,
    )

    assert text == "SELECT 1"
    assert captured["enable_thinking"] is False
    assert captured["max_tokens"] == 8192
    assert evidence["thinking_enabled"] is False


def test_chat_completion_sends_gemini_low_reasoning_effort(monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                id="chatcmpl-gemini",
                choices=[SimpleNamespace(message=SimpleNamespace(content="SELECT 1"))],
                usage=SimpleNamespace(prompt_tokens=9, completion_tokens=3, total_tokens=12),
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    # A Qwen profile may leave this generic compatibility flag behind. Gemini
    # must not receive the DashScope extension when providers are switched.
    monkeypatch.setenv("GDA_LLM_ENABLE_THINKING", "false")
    monkeypatch.setenv("GDA_GEMINI_REASONING_EFFORT", "low")
    config = OpenAICompatibleLLMConfig(
        "gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "gemini-3.6-flash",
        "gemini-key",
        30,
        "chat",
    )

    text, evidence = chat_completion(
        system_prompt="system",
        user_prompt="question",
        config=config,
        client_factory=FakeClient,
    )

    assert text == "SELECT 1"
    assert captured["reasoning_effort"] == "low"
    assert "enable_thinking" not in captured
    assert evidence["reasoning_effort"] == "low"


def test_chat_completion_adapts_gpt5_reasoning_parameters(monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                id="chatcmpl-openai",
                choices=[SimpleNamespace(message=SimpleNamespace(content="SELECT 1"))],
                usage=SimpleNamespace(prompt_tokens=9, completion_tokens=3, total_tokens=12),
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("GDA_OPENAI_REASONING_EFFORT", "low")
    config = OpenAICompatibleLLMConfig(
        "openai",
        "https://api.openai.com/v1",
        "gpt-5.6-terra",
        "openai-key",
        30,
        "chat",
    )

    text, evidence = chat_completion(
        system_prompt="system",
        user_prompt="question",
        config=config,
        max_tokens=2048,
        client_factory=FakeClient,
    )

    assert text == "SELECT 1"
    assert captured["max_completion_tokens"] == 2048
    assert captured["reasoning_effort"] == "low"
    assert "max_tokens" not in captured
    assert captured["temperature"] == 0
    assert evidence["reasoning_effort"] == "low"


def test_deepseek_responses_completion_extracts_output_text(monkeypatch):
    captured = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                id="resp-test",
                output_text="SELECT COUNT(*) FROM parcels",
                usage=SimpleNamespace(input_tokens=12, output_tokens=7, total_tokens=19),
            )

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.responses = FakeResponses()

    monkeypatch.setenv("GDA_DEEPSEEK_REASONING_EFFORT", "low")
    config = OpenAICompatibleLLMConfig(
        "deepseek", "https://api.deepseek.com", "deepseek-v4-flash", "sk-test", 30, "responses"
    )
    text, evidence = chat_completion(
        system_prompt="system",
        user_prompt="question",
        config=config,
        client_factory=FakeClient,
    )
    assert text == "SELECT COUNT(*) FROM parcels"
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["instructions"] == "system"
    assert captured["input"] == "question"
    assert captured["max_output_tokens"] == 800
    assert captured["reasoning"] == {"effort": "low"}
    assert evidence["provider"] == "deepseek"
    assert evidence["api_style"] == "responses"
    assert evidence["endpoint"] == "https://api.deepseek.com/responses"
    assert evidence["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 7,
        "total_tokens": 19,
    }


def test_deepseek_empty_response_reports_sanitized_response_state(monkeypatch):
    class FakeResponses:
        def create(self, **kwargs):
            return {
                "id": "resp-empty",
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "output": [{"type": "reasoning", "content": []}],
            }

    class FakeClient:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    config = OpenAICompatibleLLMConfig(
        "deepseek", "https://api.deepseek.com", "deepseek-v4-flash", "sk-test", 30, "responses"
    )
    with pytest.raises(LLMServiceError) as exc_info:
        chat_completion(
            system_prompt="system",
            user_prompt="question",
            config=config,
            client_factory=FakeClient,
        )
    message = str(exc_info.value)
    assert "status=incomplete" in message
    assert "max_output_tokens" in message
    assert "output_types=reasoning" in message


def test_semantic_ast_accepts_bounded_group_query():
    ast = parse_semantic_ast(
        {
            "intent": "group_summary",
            "dataset": "land_parcel_current",
            "group_by": "located_admin_name",
            "metrics": ["feature_count", "parcel_area_sqm"],
            "filters": [
                {"field": "land_use_code", "operator": "prefix", "value": "01"}
            ],
            "limit": 5000,
        }
    )
    assert ast["limit"] == 1000
    assert ast["filters"][0]["value"] == "01"


def test_semantic_ast_accepts_qwen_attribute_alias():
    ast = parse_semantic_ast(
        {
            "intent": "group_summary",
            "dataset": "land_parcel_current",
            "group_by": "located_admin_name",
            "metrics": ["feature_count"],
            "filters": [
                {"attribute": "land_use_code", "operator": "prefix", "value": "01"}
            ],
        }
    )
    assert ast["filters"][0]["field"] == "land_use_code"


@pytest.mark.parametrize(
    "payload",
    [
        {"intent": "raw_sql", "dataset": "land_parcel_current"},
        {"intent": "dataset_summary", "dataset": "secret_table"},
        {
            "intent": "group_summary",
            "dataset": "land_parcel_current",
            "group_by": "__import__",
        },
        {
            "intent": "parcel_lookup",
            "dataset": "land_parcel_current",
            "filters": [],
        },
    ],
)
def test_semantic_ast_rejects_uncontrolled_operations(payload):
    with pytest.raises(ValueError):
        parse_semantic_ast(payload)
