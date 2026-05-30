"""Embedding Gateway — configurable embedding model with multi-backend support.

Backends:
- gemini: Google Vertex AI text-embedding-004 (default, online)
- local: sentence-transformers (offline, e.g. bge-m3, gte-multilingual)
- ollama: Ollama REST API (offline, e.g. nomic-embed-text)

Configuration priority: DB agent_model_config > env EMBEDDING_MODEL > default text-embedding-004
"""
from __future__ import annotations

import os
from typing import Optional

from .observability import get_logger

logger = get_logger("embedding_gateway")

_BATCH_SIZE = 100


class EmbeddingRegistry:
    """Registry of available embedding models (mirrors ModelRegistry pattern)."""

    _builtin_models: dict[str, dict] = {
        "text-embedding-004": {
            "backend": "gemini",
            "dimension": 768,
            "online": True,
            "description": "Google Vertex AI text-embedding-004",
        },
        "bge-m3": {
            "backend": "local",
            "dimension": 1024,
            "online": False,
            "model_path": "BAAI/bge-m3",
            "description": "BGE-M3 multilingual (sentence-transformers)",
        },
        "nomic-embed-text": {
            "backend": "ollama",
            "dimension": 768,
            "online": False,
            "description": "Nomic Embed Text via Ollama",
        },
    }

    models: dict[str, dict] = {}
    _initialized: bool = False

    @classmethod
    def _ensure_initialized(cls):
        if cls._initialized:
            return
        cls.models = dict(cls._builtin_models)
        cls._initialized = True

    @classmethod
    def register_model(cls, name: str, *, backend: str, dimension: int,
                       online: bool = False, **kwargs):
        cls._ensure_initialized()
        cls.models[name] = {
            "backend": backend, "dimension": dimension,
            "online": online, **kwargs,
        }
        logger.info("[Embedding] Registered model: %s (backend=%s, dim=%d)", name, backend, dimension)

    @classmethod
    def get_active_model(cls) -> str:
        cls._ensure_initialized()
        try:
            from .model_config import get_config_manager
            mgr = get_config_manager()
            db_val = mgr.get("embedding_model")
            if db_val and db_val in cls.models:
                return db_val
        except Exception:
            pass
        env_val = os.environ.get("EMBEDDING_MODEL", "")
        if env_val and env_val in cls.models:
            return env_val
        return "text-embedding-004"

    @classmethod
    def get_model_info(cls, name: str = None) -> dict:
        cls._ensure_initialized()
        name = name or cls.get_active_model()
        return cls.models.get(name, {})

    @classmethod
    def list_models(cls) -> dict[str, dict]:
        cls._ensure_initialized()
        return dict(cls.models)


# ---------------------------------------------------------------------------
# Lazy-loaded local model singleton
# ---------------------------------------------------------------------------
_local_model_instance = None
_local_model_name: str = ""


def _get_local_model(model_path: str):
    global _local_model_instance, _local_model_name
    if _local_model_instance is not None and _local_model_name == model_path:
        return _local_model_instance
    from sentence_transformers import SentenceTransformer
    logger.info("[Embedding] Loading local model: %s", model_path)
    _local_model_instance = SentenceTransformer(model_path)
    _local_model_name = model_path
    return _local_model_instance


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------

def _embed_gemini(texts: list[str], info: dict) -> list[list[float]]:
    from google import genai
    client = genai.Client()
    model_name = info.get("gemini_model_id", "text-embedding-004")
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i:i + _BATCH_SIZE]
        response = client.models.embed_content(model=model_name, contents=batch)
        for emb in response.embeddings:
            all_embeddings.append(emb.values)
    return all_embeddings


def _embed_local(texts: list[str], info: dict) -> list[list[float]]:
    model_path = info.get("model_path", "BAAI/bge-m3")
    model = _get_local_model(model_path)
    embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
    return [e.tolist() for e in embeddings]


def _embed_ollama(texts: list[str], info: dict) -> list[list[float]]:
    import httpx
    base_url = info.get("api_base") or os.environ.get("OLLAMA_API_BASE", "http://localhost:11434")
    model_name = info.get("ollama_model_id") or "nomic-embed-text"
    all_embeddings: list[list[float]] = []
    for text in texts:
        resp = httpx.post(
            f"{base_url}/api/embeddings",
            json={"model": model_name, "prompt": text},
            timeout=30.0,
        )
        resp.raise_for_status()
        all_embeddings.append(resp.json()["embedding"])
    return all_embeddings


_BACKENDS = {
    "gemini": _embed_gemini,
    "local": _embed_local,
    "ollama": _embed_ollama,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Unified embedding entry point — dispatches to active backend.

    Returns empty list on failure (graceful degradation).
    """
    if not texts:
        return []
    model_name = EmbeddingRegistry.get_active_model()
    info = EmbeddingRegistry.get_model_info(model_name)
    backend = info.get("backend", "gemini")
    fn = _BACKENDS.get(backend)
    if not fn:
        logger.warning("[Embedding] Unknown backend '%s', falling back to gemini", backend)
        fn = _embed_gemini
    try:
        result = fn(texts, info)
        return result
    except Exception as e:
        logger.warning("[Embedding] %s/%s failed: %s", backend, model_name, e)
        return []


def get_active_dimension() -> int:
    """Return the embedding dimension of the active model."""
    info = EmbeddingRegistry.get_model_info()
    return info.get("dimension", 768)
