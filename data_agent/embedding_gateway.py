"""Embedding Gateway — configurable embedding model with multi-backend support.

Backends:
- gemini: Google Vertex AI text-embedding-004 (explicit opt-in, online)
- local: sentence-transformers (offline, e.g. bge-m3, gte-multilingual)
- ollama: Ollama REST API (offline, e.g. nomic-embed-text)
- openai_compatible: LM Studio or another OpenAI-compatible /embeddings API

Configuration priority: DB agent_model_config > env EMBEDDING_MODEL > the offline
Nomic Ollama model. Gemini remains available only when explicitly selected.
Set GDA_EMBEDDING_* when the vector service is separate from the chat service;
otherwise GDA_LLM_BASE_URL is used for an LM Studio-compatible embedding API.
"""
from __future__ import annotations

import os

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
        # nomic-embed-text-v2 MoE — 305M active / 475M total, 768-dim, F16.
        # ollama tag is `nomic-embed-text-v2-moe:latest`; `ollama_model_id`
        # below is what gets sent to Ollama's /api/embeddings (case-sensitive
        # match with `ollama list`).
        "nomic-embed-text-v2-moe": {
            "backend": "ollama",
            "dimension": 768,
            "online": False,
            "ollama_model_id": "nomic-embed-text-v2-moe:latest",
            "description": "Nomic Embed Text v2 MoE via Ollama",
        },
        # LM Studio exposes the same model under its OpenAI model ID.  The
        # endpoint and API key remain deployment configuration, not code.
        "text-embedding-nomic-embed-text-v2-moe": {
            "backend": "openai_compatible",
            "dimension": 768,
            "online": False,
            "model_id": "text-embedding-nomic-embed-text-v2-moe",
            "description": "Nomic Embed Text v2 MoE via LM Studio/OpenAI API",
        },
        "text-embedding-nomic-embed-text-v1.5": {
            "backend": "openai_compatible",
            "dimension": 768,
            "online": False,
            "model_id": "text-embedding-nomic-embed-text-v1.5",
            "description": "Nomic Embed Text v1.5 via LM Studio/OpenAI API",
        },
        # Cross-host benchmark cell — same v2-moe model served by a
        # *different* Ollama instance (192.168.43.10). Pinned api_base
        # so OLLAMA_API_BASE env doesn't redirect it. Companion to
        # ModelRegistry.gemma4-26b-host43.
        "nomic-embed-text-v2-moe-host43": {
            "backend": "ollama",
            "dimension": 768,
            "online": False,
            "ollama_model_id": "nomic-embed-text-v2-moe:latest",
            "api_base": "http://192.168.43.10:11434",
            "description": "Nomic Embed Text v2 MoE via Ollama @ 192.168.43.10",
        },
        # Current LAN Ollama embedding cell paired with gemma4-26b-host9.
        "nomic-embed-text-v2-moe-host9": {
            "backend": "ollama",
            "dimension": 768,
            "online": False,
            "ollama_model_id": "nomic-embed-text-v2-moe:latest",
            "api_base": "http://192.168.43.9:11434",
            "api_base_pinned": True,
            "description": "Nomic Embed Text v2 MoE via Ollama @ 192.168.43.9",
        },
        "nomic-embed-text-v2-moe-host228": {
            "backend": "ollama",
            "dimension": 768,
            "online": False,
            "ollama_model_id": "nomic-embed-text-v2-moe:latest",
            "api_base": "http://192.168.25.228:11434",
            "api_base_pinned": True,
            "description": "Nomic Embed Text v2 MoE via Ollama @ 192.168.25.228",
        },
    }

    models: dict[str, dict] = {}
    _initialized: bool = False

    @classmethod
    def _ensure_initialized(cls):
        if cls._initialized:
            return
        cls.models = dict(cls._builtin_models)
        cls._register_configured_model()
        cls._initialized = True

    @classmethod
    def _register_configured_model(cls):
        """Register an arbitrary deployment-provided embedding model.

        Field deployments often expose a model ID that is not known at build
        time.  This keeps the Windows package configuration-only: the model
        ID, endpoint, backend and vector dimension come from environment
        variables and are visible to the admin model selector.
        """
        model_name = (
            os.environ.get("GDA_EMBEDDING_MODEL")
            or os.environ.get("EMBEDDING_MODEL")
            or ""
        ).strip()
        if not model_name:
            return
        base_url = (
            os.environ.get("GDA_EMBEDDING_BASE_URL")
            or os.environ.get("EMBEDDING_BASE_URL")
            or ""
        ).strip()
        provider = (
            os.environ.get("GDA_EMBEDDING_PROVIDER")
            or os.environ.get("EMBEDDING_PROVIDER")
            or ""
        ).strip().casefold().replace("-", "_")
        if not provider and base_url:
            try:
                from .openai_compatible_llm import infer_llm_provider
                provider = infer_llm_provider(base_url)
            except Exception:
                provider = "openai_compatible"
        if not provider:
            # Preserve the historical Ollama behavior when only
            # EMBEDDING_MODEL is configured.
            provider = "ollama"
        if provider not in {"ollama", "lm_studio", "openai_compatible", "local", "gemini"}:
            raise ValueError(
                "GDA_EMBEDDING_PROVIDER must be ollama, lm_studio, "
                "openai_compatible, local, or gemini"
            )
        dimension_raw = (
            os.environ.get("GDA_EMBEDDING_DIMENSION")
            or os.environ.get("EMBEDDING_DIMENSION")
            or ""
        ).strip()
        try:
            dimension = int(
                dimension_raw or "768"
            )
        except ValueError as exc:
            raise ValueError("EMBEDDING_DIMENSION must be a positive integer") from exc
        if dimension <= 0:
            raise ValueError("EMBEDDING_DIMENSION must be a positive integer")
        api_key = (
            os.environ.get("GDA_EMBEDDING_API_KEY")
            or os.environ.get("EMBEDDING_API_KEY")
            or ""
        ).strip()
        if model_name in cls.models:
            # Known IDs still accept deployment-specific endpoint/provider and
            # dimension overrides. With no GDA_EMBEDDING_* overrides this is a
            # no-op and preserves the historical built-in definitions.
            if not (base_url or provider != "ollama" or api_key or dimension_raw):
                return
            info = dict(cls.models[model_name])
            if provider:
                info["backend"] = (
                    "openai_compatible" if provider == "lm_studio" else provider
                )
            if base_url:
                info["api_base"] = base_url
            if api_key:
                info["api_key"] = api_key
            if dimension_raw:
                info["dimension"] = dimension
            cls.models[model_name] = info
            return
        info = {
            "backend": "openai_compatible" if provider == "lm_studio" else provider,
            "dimension": dimension,
            "online": False,
            "model_id": model_name,
            "description": f"Configured {provider} embedding model",
        }
        if base_url:
            info["api_base"] = base_url
        if api_key:
            info["api_key"] = api_key
        cls.models[model_name] = info

    @classmethod
    def register_model(cls, name: str, *, backend: str, dimension: int,
                       online: bool = False, **kwargs):
        cls._ensure_initialized()
        cls.models[name] = {
            "backend": backend, "dimension": dimension,
            "online": online, **kwargs,
        }
        logger.info(
            "[Embedding] Registered model: %s (backend=%s, dim=%d)",
            name,
            backend,
            dimension,
        )

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
        env_val = (
            os.environ.get("GDA_EMBEDDING_MODEL")
            or os.environ.get("EMBEDDING_MODEL", "")
        )
        if env_val and env_val in cls.models:
            return env_val
        # A clean, air-gapped installation must not make an online request
        # merely because the administrator has not yet opened the model page.
        return "nomic-embed-text-v2-moe"

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
    # Built-in registry entries use ``ollama_model_id`` while arbitrary
    # field-configured models use ``model_id``.  Falling back directly to the
    # historical default made a configured value such as
    # ``nomic-embed-text-v2-moe:latest`` call the wrong model silently.
    model_name = (
        info.get("ollama_model_id")
        or info.get("model_id")
        or os.environ.get("GDA_EMBEDDING_MODEL")
        or os.environ.get("EMBEDDING_MODEL")
        or "nomic-embed-text"
    )
    all_embeddings: list[list[float]] = []
    for text in texts:
        resp = httpx.post(
            f"{base_url}/api/embeddings",
            json={"model": model_name, "prompt": text},
            timeout=30.0,
            # Ollama is an on-host/on-LAN service.  Do not route it through
            # HTTP(S)_PROXY, which can turn a healthy local endpoint into a
            # misleading 502 in air-gapped deployments.
            trust_env=False,
        )
        resp.raise_for_status()
        all_embeddings.append(resp.json()["embedding"])
    return all_embeddings


def _embed_openai_compatible(texts: list[str], info: dict) -> list[list[float]]:
    """Call LM Studio or another OpenAI-compatible embeddings endpoint."""
    import httpx

    from .openai_compatible_llm import normalize_openai_base_url

    configured_base = (
        info.get("api_base")
        or os.environ.get("GDA_EMBEDDING_BASE_URL")
        or os.environ.get("EMBEDDING_BASE_URL")
        or os.environ.get("GDA_LLM_BASE_URL")
        or os.environ.get("LM_STUDIO_BASE_URL")
        or "http://127.0.0.1:1234/v1"
    )
    base_url = normalize_openai_base_url(configured_base)
    model_name = info.get("model_id") or os.environ.get("GDA_EMBEDDING_MODEL") or os.environ.get(
        "EMBEDDING_MODEL", ""
    )
    if not model_name:
        raise ValueError("EMBEDDING_MODEL is required for OpenAI-compatible embeddings")
    api_key = (
        info.get("api_key")
        or os.environ.get("GDA_EMBEDDING_API_KEY")
        or os.environ.get("EMBEDDING_API_KEY")
        or os.environ.get("GDA_LLM_API_KEY")
        or "lm-studio"
    )
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    with httpx.Client(timeout=30.0, trust_env=False) as client:
        response = client.post(
            f"{base_url}/embeddings",
            headers=headers,
            json={"model": model_name, "input": texts},
        )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data") or []
    if len(rows) != len(texts):
        raise ValueError(
            f"embedding response returned {len(rows)} vectors for {len(texts)} inputs"
        )
    rows = sorted(rows, key=lambda row: int(row.get("index", 0)))
    vectors = [row.get("embedding") for row in rows]
    if any(not isinstance(vector, list) or not vector for vector in vectors):
        raise ValueError("embedding response contains an empty vector")
    expected_dimension = int(info.get("dimension") or 0)
    if expected_dimension and any(len(vector) != expected_dimension for vector in vectors):
        actual_dimensions = sorted({len(vector) for vector in vectors})
        raise ValueError(
            f"embedding dimension mismatch: expected {expected_dimension}, "
            f"received {actual_dimensions}"
        )
    return vectors


_BACKENDS = {
    "gemini": _embed_gemini,
    "local": _embed_local,
    "ollama": _embed_ollama,
    "openai_compatible": _embed_openai_compatible,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_embeddings(texts: list[str], model_name: str | None = None) -> list[list[float]]:
    """Unified embedding entry point — dispatches to active backend.

    Returns empty list on failure (graceful degradation).
    """
    if not texts:
        return []
    selected_model = model_name or EmbeddingRegistry.get_active_model()
    info = EmbeddingRegistry.get_model_info(selected_model)
    if not info:
        logger.warning(
            "[Embedding] Unknown model '%s', falling back to active model",
            selected_model,
        )
        selected_model = EmbeddingRegistry.get_active_model()
        info = EmbeddingRegistry.get_model_info(selected_model)
    backend = info.get("backend", "ollama")
    fn = _BACKENDS.get(backend)
    if not fn:
        logger.error("[Embedding] Unknown backend '%s'; refusing implicit online fallback", backend)
        return []
    try:
        result = fn(texts, info)
        return result
    except Exception as e:
        logger.warning("[Embedding] %s/%s failed: %s", backend, selected_model, e)
        return []


def get_active_dimension() -> int:
    """Return the embedding dimension of the active model."""
    info = EmbeddingRegistry.get_model_info()
    return info.get("dimension", 768)
