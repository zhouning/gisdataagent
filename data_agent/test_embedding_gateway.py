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
