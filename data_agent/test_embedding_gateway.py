"""Tests for embedding model registry entries."""


def test_nomic_v2_moe_host9_registration():
    from data_agent.embedding_gateway import EmbeddingRegistry

    EmbeddingRegistry.models = {}
    EmbeddingRegistry._initialized = False
    EmbeddingRegistry._ensure_initialized()

    info = EmbeddingRegistry.get_model_info("nomic-embed-text-v2-moe-host9")
    assert info["backend"] == "ollama"
    assert info["dimension"] == 768
    assert info["online"] is False
    assert info["ollama_model_id"] == "nomic-embed-text-v2-moe:latest"
    assert info["api_base"] == "http://192.168.43.9:11434"
    assert info["api_base_pinned"] is True


def test_get_embeddings_honors_explicit_model_name(monkeypatch):
    from data_agent import embedding_gateway
    from data_agent.embedding_gateway import EmbeddingRegistry, get_embeddings

    EmbeddingRegistry.models = {}
    EmbeddingRegistry._initialized = False
    EmbeddingRegistry._ensure_initialized()
    EmbeddingRegistry.register_model(
        "unit-test-embedder",
        backend="unit",
        dimension=2,
        online=False,
    )

    calls = []

    def unit_embedder(texts, info):
        calls.append({"texts": texts, "info": info})
        return [[float(len(text)), 1.0] for text in texts]

    monkeypatch.setitem(embedding_gateway._BACKENDS, "unit", unit_embedder)

    vectors = get_embeddings(["abc"], model_name="unit-test-embedder")

    assert vectors == [[3.0, 1.0]]
    assert calls[0]["info"]["backend"] == "unit"
    assert calls[0]["info"]["dimension"] == 2


def test_ollama_embedding_bypasses_environment_proxy(monkeypatch):
    from data_agent.embedding_gateway import _embed_ollama

    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"embedding": [0.25, 0.75]}

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr("httpx.post", fake_post)

    vectors = _embed_ollama(
        ["地类图斑面积"],
        {
            "api_base": "http://127.0.0.1:11434",
            "ollama_model_id": "nomic-embed-text-v2-moe:latest",
        },
    )

    assert vectors == [[0.25, 0.75]]
    assert calls[0]["trust_env"] is False


def test_ollama_embedding_uses_field_configured_model_id(monkeypatch):
    from data_agent.embedding_gateway import _embed_ollama

    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"embedding": [0.1, 0.2]}

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr("httpx.post", fake_post)
    vectors = _embed_ollama(
        ["测试"],
        {
            "api_base": "http://127.0.0.1:11434",
            "model_id": "nomic-embed-text-v2-moe:latest",
        },
    )

    assert vectors == [[0.1, 0.2]]
    assert calls[0]["json"]["model"] == "nomic-embed-text-v2-moe:latest"


def test_openai_compatible_embedding_uses_configured_model_and_base(monkeypatch):
    from data_agent.embedding_gateway import _embed_openai_compatible

    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {"index": 1, "embedding": [0.2, 0.8]},
                    {"index": 0, "embedding": [0.1, 0.9]},
                ]
            }

    class Client:
        def __init__(self, **kwargs):
            calls.append({"client": kwargs})

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, **kwargs):
            calls.append({"url": url, **kwargs})
            return Response()

    monkeypatch.setattr("httpx.Client", Client)
    vectors = _embed_openai_compatible(
        ["问题一", "问题二"],
        {
            "api_base": "http://10.64.4.202:1234/v1/chat/completions",
            "model_id": "text-embedding-nomic-embed-text-v2-moe",
            "api_key": "lm-studio",
        },
    )

    assert vectors == [[0.1, 0.9], [0.2, 0.8]]
    assert calls[0]["client"]["trust_env"] is False
    assert calls[1]["url"] == "http://10.64.4.202:1234/v1/embeddings"
    assert calls[1]["json"] == {
        "model": "text-embedding-nomic-embed-text-v2-moe",
        "input": ["问题一", "问题二"],
    }


def test_embedding_registry_registers_unknown_field_model_from_env(monkeypatch):
    from data_agent.embedding_gateway import EmbeddingRegistry

    monkeypatch.setenv("EMBEDDING_MODEL", "field-embedding-model")
    monkeypatch.setenv("GDA_EMBEDDING_PROVIDER", "lm_studio")
    monkeypatch.setenv("GDA_EMBEDDING_BASE_URL", "http://10.64.4.202:1234/v1")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "1024")
    EmbeddingRegistry.models = {}
    EmbeddingRegistry._initialized = False
    EmbeddingRegistry._ensure_initialized()

    info = EmbeddingRegistry.get_model_info("field-embedding-model")
    assert info["backend"] == "openai_compatible"
    assert info["api_base"] == "http://10.64.4.202:1234/v1"
    assert info["dimension"] == 1024


def test_unknown_embedding_backend_does_not_fallback_to_gemini(monkeypatch):
    from data_agent.embedding_gateway import EmbeddingRegistry, get_embeddings

    EmbeddingRegistry.models = {
        "broken-local": {
            "backend": "missing_backend",
            "dimension": 768,
            "online": False,
        }
    }
    EmbeddingRegistry._initialized = True
    monkeypatch.setattr(
        "data_agent.embedding_gateway._embed_gemini",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Gemini must not be called as an implicit fallback")
        ),
    )

    assert get_embeddings(["offline test"], model_name="broken-local") == []


def test_environment_template_does_not_enable_vertex_ai_by_default():
    from pathlib import Path

    template = (Path(__file__).resolve().parent / ".env.example").read_text(
        encoding="utf-8"
    )
    active_lines = {
        line.strip()
        for line in template.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "GOOGLE_GENAI_USE_VERTEXAI=TRUE" not in active_lines
