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
