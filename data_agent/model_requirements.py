"""Runtime environment requirements for configured LLM backends."""

from __future__ import annotations

import os
from typing import Mapping, Sequence


def model_requires_google_cloud_project(
    model_name: str,
    *,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return whether this model needs ``GOOGLE_CLOUD_PROJECT`` at runtime.

    The project id is required for Vertex AI-backed Gemini models. It is not
    required for local LiteLLM/Ollama models, LM Studio, DeepSeek/Qwen, or
    Gemma served through AI Studio/local endpoints.
    """
    name = (model_name or "").strip()
    if not name:
        return False

    runtime_env = env or os.environ
    if not _truthy(runtime_env.get("GOOGLE_GENAI_USE_VERTEXAI")):
        return False

    backend = _backend_for_model(name)
    if backend != "gemini":
        return False

    # Gemma models are routed away from Vertex in model_gateway._create_gemini_model.
    if "gemma" in name.lower():
        return False

    return True


def configured_models_require_google_cloud_project(
    *,
    env: Mapping[str, str] | None = None,
    model_names: Sequence[str] | None = None,
) -> bool:
    """Return whether any active router/tier model requires a GCP project id."""
    names = list(model_names) if model_names is not None else _configured_model_names()
    return any(model_requires_google_cloud_project(name, env=env) for name in names)


def _configured_model_names() -> list[str]:
    from .model_config import get_config_manager

    manager = get_config_manager()
    return [
        manager.get_router_model(),
        manager.get_tier_model("fast"),
        manager.get_tier_model("standard"),
        manager.get_tier_model("premium"),
    ]


def _backend_for_model(model_name: str) -> str:
    from .model_gateway import ModelRegistry, _detect_backend

    ModelRegistry._ensure_initialized()
    info = ModelRegistry.get_model_info(model_name) or {}
    return str(info.get("backend") or _detect_backend(model_name))


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
