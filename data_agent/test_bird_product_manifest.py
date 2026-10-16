import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location("product_manifest", Path(__file__).resolve().parents[1] / "scripts/nl2sql_bench_bird/product_manifest.py")
manifest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manifest)


def test_manifest_keeps_token_budget_and_reasoning_but_excludes_credentials():
    actual = manifest.public_settings({
        "GDA_LLM_API_KEY": "private", "GDA_LLM_ACCESS_TOKEN": "private",
        "GDA_LLM_BASE_URL": "http://person:private@127.0.0.1:11434/v1?api_key=private",
        "GDA_NL2SQL_MAX_OUTPUT_TOKENS": "8192", "GDA_OLLAMA_REASONING_EFFORT": "high",
        "GDA_LLM_MODEL": "Gemma4:26b", "BIRD_PG_PASSWORD": "private"})
    assert "private" not in str(actual)
    assert actual["GDA_NL2SQL_MAX_OUTPUT_TOKENS"] == "8192"
    assert actual["GDA_OLLAMA_REASONING_EFFORT"] == "high"
    assert actual["GDA_LLM_BASE_URL"] == "http://127.0.0.1:11434/v1"


def test_deployed_model_pins_digest_without_triggering_generation(monkeypatch):
    from types import SimpleNamespace
    import httpx

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, url):
            assert url == "http://127.0.0.1:11434/api/tags"
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
                "models": [{"name": "Gemma4:26b", "digest": "sha256:installed"}]})
    monkeypatch.setattr(httpx, "Client", Client)
    actual = manifest.deployed_model(SimpleNamespace(provider="ollama", model="Gemma4:26b", base_url="http://127.0.0.1:11434/v1"))
    assert actual["digest"] == "sha256:installed"


def test_isolated_runtime_rejects_context_drift(monkeypatch):
    from types import SimpleNamespace
    import httpx
    import pytest

    monkeypatch.setenv("GDA_OLLAMA_EXPECTED_CONTEXT_LENGTH", "32768")
    runtime_context = 32768
    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, url):
            value = {"name": "local", "digest": "artifact"}
            if url.endswith("/api/ps"):
                value["context_length"] = runtime_context
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"models": [value]})
    monkeypatch.setattr(httpx, "Client", Client)
    config = SimpleNamespace(provider="ollama", model="local", base_url="http://127.0.0.1:11435/v1")
    assert manifest.deployed_model(config)["runtime_context_length"] == 32768
    runtime_context = 8192
    with pytest.raises(RuntimeError, match="context differs"):
        manifest.deployed_model(config)


def test_gemini_pins_official_metadata_through_explicit_proxy_without_secrets(monkeypatch):
    import httpx
    from types import SimpleNamespace
    from data_agent.openai_compatible_llm import OpenAICompatibleLLMConfig
    class Client:
        def __init__(self, **kwargs):
            assert kwargs["proxy"] == "http://127.0.0.1:7897"
            assert kwargs["trust_env"] is False
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, url, headers):
            assert url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-4-argon"
            assert headers == {"x-goog-api-key": "private-key"}
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
                "name": "models/gemini-4-argon", "version": "3.0",
                "supportedGenerationMethods": ["generateContent"]})
    monkeypatch.setattr(httpx, "Client", Client)
    config = OpenAICompatibleLLMConfig("gemini", "https://generativelanguage.googleapis.com/v1beta/openai",
        "gemini-4-argon", "private-key", 120, http_proxy="http://127.0.0.1:7897")
    actual = manifest.deployed_model(config)
    assert actual["metadata"]["version"] == "3.0"
    assert len(actual["metadata_sha256"]) == 64
    assert actual["digest"] is None
    assert "private-key" not in str(actual)


def test_public_settings_keep_gemini_effort_and_redact_proxy_credentials():
    actual = manifest.public_settings({"GDA_GEMINI_REASONING_EFFORT": "low",
        "GDA_LLM_HTTP_PROXY": "http://person:private@127.0.0.1:7897?token=private"})
    assert actual["GDA_GEMINI_REASONING_EFFORT"] == "low"
    assert actual["GDA_LLM_HTTP_PROXY"] == "http://127.0.0.1:7897"
    assert "private" not in str(actual)
