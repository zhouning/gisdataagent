"""Explicit, auditable reasoning configuration for local Ollama models."""
from __future__ import annotations

import os
from collections.abc import Mapping


def ollama_reasoning_effort(settings: Mapping[str, str] | None = None) -> str | None:
    """Return an OpenAI-compatible effort or omit it for the model default.

    The default preserves existing latency behaviour. An explicit setting
    takes precedence over the shared boolean switch; `auto` delegates to the
    installed model. Unknown settings must never silently turn thinking off.
    """
    env = os.environ if settings is None else settings
    effort = env.get("GDA_OLLAMA_REASONING_EFFORT", "").strip().casefold()
    if effort:
        if effort == "auto":
            return None
        if effort not in {"none", "low", "medium", "high", "xhigh"}:
            raise ValueError("GDA_OLLAMA_REASONING_EFFORT must be auto, none, low, medium, high, or xhigh")
        return effort
    shared = env.get("GDA_LLM_ENABLE_THINKING", "").strip().casefold()
    if shared in {"1", "true", "yes", "on"}:
        return "high"
    if shared and shared not in {"0", "false", "no", "off"}:
        raise ValueError("GDA_LLM_ENABLE_THINKING must be a boolean")
    return "none"
