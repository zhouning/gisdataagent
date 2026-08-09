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


def test_lm_studio_embedding_model_is_registered_from_environment(monkeypatch):
    from data_agent.embedding_gateway import EmbeddingRegistry

    monkeypatch.setenv("LM_STUDIO_EMBEDDING_MODEL", "text-embedding-qwen")
    monkeypatch.setenv("LM_STUDIO_EMBEDDING_DIMENSION", "768")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://10.0.0.8:1234/v1")
    monkeypatch.setenv("MODEL_CONFIG_FORCE_ENV", "true")
    EmbeddingRegistry.models = {}
    EmbeddingRegistry._initialized = False
    EmbeddingRegistry._ensure_initialized()

    info = EmbeddingRegistry.get_model_info("text-embedding-qwen")
    assert info["backend"] == "lm_studio"
    assert info["dimension"] == 768
    assert info["model_id"] == "text-embedding-qwen"
    assert info["api_base"] == "http://10.0.0.8:1234/v1"
    assert EmbeddingRegistry.get_active_model() == "text-embedding-qwen"


def test_lm_studio_embeddings_use_openai_compatible_endpoint(monkeypatch):
    from data_agent import embedding_gateway
    from data_agent.embedding_gateway import EmbeddingRegistry, get_embeddings

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {"index": 1, "embedding": [3.0, 4.0]},
                    {"index": 0, "embedding": [1.0, 2.0]},
                ]
            }

    calls = []

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr("httpx.post", fake_post)
    monkeypatch.setenv("LM_STUDIO_API_KEY", "intranet-key")
    EmbeddingRegistry.models = {}
    EmbeddingRegistry._initialized = False
    EmbeddingRegistry._ensure_initialized()
    EmbeddingRegistry.register_model(
        "text-embedding-qwen",
        backend="lm_studio",
        dimension=2,
        online=False,
        model_id="text-embedding-qwen",
        api_base="http://10.0.0.8:1234/v1/",
    )

    vectors = get_embeddings(["a", "b"], model_name="text-embedding-qwen")

    assert vectors == [[1.0, 2.0], [3.0, 4.0]]
    assert calls == [
        {
            "url": "http://10.0.0.8:1234/v1/embeddings",
            "json": {"model": "text-embedding-qwen", "input": ["a", "b"]},
            "headers": {"Authorization": "Bearer intranet-key"},
            "timeout": 60.0,
        }
    ]


def test_lm_studio_embeddings_reject_non_768_environment_contract(monkeypatch):
    from data_agent.embedding_gateway import EmbeddingRegistry, get_embeddings

    monkeypatch.setenv("LM_STUDIO_EMBEDDING_MODEL", "text-embedding-qwen")
    monkeypatch.setenv("LM_STUDIO_EMBEDDING_DIMENSION", "1024")
    EmbeddingRegistry.models = {}
    EmbeddingRegistry._initialized = False

    assert get_embeddings(["a"], model_name="text-embedding-qwen") == []
