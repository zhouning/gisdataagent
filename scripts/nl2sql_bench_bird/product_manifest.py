"""Reproducible runtime configuration without including connection secrets."""
from __future__ import annotations

import os
import hashlib
import json
from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit


def public_settings(settings: Mapping[str, str] | None = None) -> dict:
    env = os.environ if settings is None else settings
    result = {}
    for key, value in sorted(env.items()):
        if not key.startswith(("NL2SQL_", "GDA_NL2SQL_", "GDA_LLM_", "GDA_OLLAMA_", "GDA_GEMINI_")):
            continue
        upper = key.upper()
        if any(secret in upper for secret in ("API_KEY", "PASSWORD", "SECRET", "ACCESS_TOKEN", "AUTH_TOKEN", "BEARER")):
            continue
        if upper.endswith(("_KEY", "_TOKEN")):
            continue
        if "URL" in upper or "PROXY" in upper:
            parsed = urlsplit(value)
            if parsed.netloc:
                host = parsed.hostname or ""
                if ":" in host:
                    host = f"[{host}]"
                netloc = host + (f":{parsed.port}" if parsed.port else "")
                value = urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
        result[key] = value
    return result


def deployed_model(config) -> dict:
    """Pin the installed model artifact; never load a model to obtain metadata."""
    if config.provider == "gemini":
        import httpx
        from data_agent.openai_compatible_llm import llm_http_client_options

        official_base = "https://generativelanguage.googleapis.com/v1beta/openai"
        if config.base_url != official_base:
            raise RuntimeError("Gemini evaluation requires the official API endpoint")
        model_id = config.model.removeprefix("models/")
        if not model_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for c in model_id):
            raise RuntimeError("Invalid Gemini model identifier")
        url = "https://generativelanguage.googleapis.com/v1beta/models/" + model_id
        with httpx.Client(timeout=30, **llm_http_client_options(config)) as client:
            response = client.get(url, headers={"x-goog-api-key": config.api_key})
            response.raise_for_status()
            raw = response.json()
        metadata = {key: raw.get(key) for key in (
            "name", "version", "displayName", "inputTokenLimit", "outputTokenLimit",
            "supportedGenerationMethods")}
        if (metadata["name"] != "models/" + model_id or not metadata["version"]
                or "generateContent" not in (metadata["supportedGenerationMethods"] or [])):
            raise RuntimeError("Official Gemini model identity or generation capability differs")
        return {"model": config.model, "provider": config.provider, "digest": None,
                "identity_kind": "official-provider-metadata-v1", "metadata": metadata,
                "metadata_sha256": hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest(),
                "metadata_endpoint": url,
                "limitation": "Provider model metadata is checked before and after the run; hosted weights cannot be independently frozen."}
    if config.provider != "ollama":
        return {"model": config.model, "provider": config.provider, "digest": None}
    import httpx

    base = config.base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    with httpx.Client(timeout=20, trust_env=False) as client:
        response = client.get(base + "/api/tags")
        response.raise_for_status()
        models = response.json().get("models") or []
    target = config.model.casefold()
    matched = next((m for m in models if target in {
        str(m.get("name") or "").casefold(), str(m.get("model") or "").casefold()}), None)
    if not matched or not matched.get("digest"):
        raise RuntimeError("Configured Ollama model has no installed artifact digest")
    result = {"model": config.model, "provider": config.provider,
              "digest": matched["digest"], "details": matched.get("details") or {}}
    expected_context = os.environ.get("GDA_OLLAMA_EXPECTED_CONTEXT_LENGTH")
    if expected_context:
        with httpx.Client(timeout=20, trust_env=False) as client:
            response = client.get(base + "/api/ps")
            response.raise_for_status()
        running = next((m for m in response.json().get("models", [])
                        if m.get("digest") == matched["digest"]), None)
        if not running or running.get("context_length") != int(expected_context):
            raise RuntimeError("Isolated Ollama context differs from the pinned configuration; preload the model first")
        result["runtime_context_length"] = running["context_length"]
    return result
