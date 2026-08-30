"""OpenAI-compatible local LLM configuration and transport.

Ollama and LM Studio expose the same Chat Completions API but commonly use
different ports.  This module keeps the configured value as an API base URL
and guarantees that callers issue exactly one ``/v1/chat/completions`` path.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit


class LLMServiceError(RuntimeError):
    """Raised when a required local LLM request cannot be completed."""


def normalize_openai_base_url(value: str) -> str:
    """Normalize a host, API base, or Chat Completions URL to an API base."""

    raw = str(value or "").strip().rstrip("/")
    if not raw:
        raise ValueError("LLM base URL is required")
    if "://" not in raw:
        raw = f"http://{raw}"
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"invalid LLM base URL: {value}")
    if parsed.query or parsed.fragment:
        raise ValueError("LLM base URL must not contain a query string or fragment")

    path = parsed.path.rstrip("/")
    lower = path.casefold()
    for suffix in ("/chat/completions", "/completions", "/embeddings", "/models"):
        if lower.endswith(suffix):
            path = path[: -len(suffix)].rstrip("/")
            lower = path.casefold()
            break
    if not path:
        path = "/v1"
    elif lower.endswith("/openai"):
        # Gemini's documented OpenAI compatibility root is
        # /v1beta/openai, not an API root that accepts another /v1 suffix.
        pass
    elif not (lower == "/v1" or lower.endswith("/v1")):
        path = f"{path}/v1"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def normalize_deepseek_base_url(value: str) -> str:
    """Normalize the DeepSeek API root used by its Responses API.

    DeepSeek's documented Responses endpoint is ``https://api.deepseek.com/
    responses`` (without the OpenAI-compatible ``/v1`` prefix). Accepting a
    copied ``/v1`` or full ``/responses`` URL is useful for deployment
    profiles, but the wire endpoint remains unambiguous.
    """

    raw = str(value or "").strip().rstrip("/")
    if not raw:
        raise ValueError("DeepSeek base URL is required")
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"invalid DeepSeek base URL: {value}")
    if parsed.query or parsed.fragment:
        raise ValueError("DeepSeek base URL must not contain a query string or fragment")
    path = parsed.path.rstrip("/")
    lower = path.casefold()
    for suffix in ("/responses", "/v1/chat/completions", "/chat/completions", "/v1"):
        if lower.endswith(suffix):
            path = path[: -len(suffix)].rstrip("/")
            break
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def infer_llm_provider(base_url: str, explicit: str | None = None) -> str:
    provider = str(explicit or "").strip().casefold().replace("-", "_")
    if provider:
        if provider not in {
            "ollama",
            "lm_studio",
            "openai_compatible",
            "openai",
            "deepseek",
            "gemini",
        }:
            raise ValueError(
                "GDA_LLM_PROVIDER must be ollama, lm_studio, openai, deepseek, "
                "gemini, or openai_compatible"
            )
        return provider
    parsed = urlsplit(base_url)
    if parsed.port == 11434:
        return "ollama"
    if parsed.port == 1234:
        return "lm_studio"
    return "openai_compatible"


@dataclass(frozen=True)
class OpenAICompatibleLLMConfig:
    provider: str
    base_url: str
    model: str
    api_key: str
    timeout_seconds: float
    api_style: str = "chat"

    @classmethod
    def from_env(cls) -> OpenAICompatibleLLMConfig:
        explicit_provider = os.environ.get("GDA_LLM_PROVIDER")
        provider_hint = str(explicit_provider or "").strip().casefold().replace("-", "_")
        configured_base = (
            os.environ.get("GDA_LLM_BASE_URL")
            or (os.environ.get("OPENAI_BASE_URL") if provider_hint == "openai" else None)
            or os.environ.get("LM_STUDIO_BASE_URL")
            or os.environ.get("OLLAMA_API_BASE")
            or (
                "https://api.openai.com/v1"
                if provider_hint == "openai"
                else "http://127.0.0.1:11434/v1"
            )
        )
        base_url = (
            normalize_deepseek_base_url(configured_base)
            if provider_hint == "deepseek"
            else normalize_openai_base_url(configured_base)
        )
        provider = infer_llm_provider(base_url, explicit_provider)
        model = (
            os.environ.get("GDA_LLM_MODEL")
            or os.environ.get("LM_STUDIO_MODEL")
            or "Qwen3.6:27b"
        ).strip()
        if not model:
            raise ValueError("GDA_LLM_MODEL is required")
        generic_api_key = os.environ.get("GDA_LLM_API_KEY", "").strip()
        if provider == "deepseek":
            api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip() or generic_api_key
        elif provider == "openai":
            api_key = os.environ.get("OPENAI_API_KEY", "").strip() or generic_api_key
        elif provider == "gemini":
            api_key = (
                os.environ.get("GEMINI_API_KEY", "").strip()
                or os.environ.get("GOOGLE_API_KEY", "").strip()
                or generic_api_key
            )
        else:
            api_key = generic_api_key
        if not api_key:
            if provider == "ollama":
                api_key = "ollama"
            elif provider == "lm_studio":
                api_key = "lm-studio"
            else:
                api_key = ""
        timeout = float(os.environ.get("GDA_LLM_TIMEOUT_SECONDS", "180"))
        if timeout <= 0:
            raise ValueError("GDA_LLM_TIMEOUT_SECONDS must be greater than zero")
        api_style = (
            os.environ.get("GDA_LLM_API_STYLE", "responses" if provider == "deepseek" else "chat")
            .strip()
            .casefold()
        )
        if api_style not in {"chat", "responses"}:
            raise ValueError("GDA_LLM_API_STYLE must be chat or responses")
        return cls(provider, base_url, model, api_key, timeout, api_style)

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    @property
    def responses_url(self) -> str:
        return f"{self.base_url}/responses"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _optional_bool_env(name: str) -> bool | None:
    """Return an explicitly configured boolean without inventing a default."""

    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def chat_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    config: OpenAICompatibleLLMConfig | None = None,
    max_tokens: int = 800,
    client_factory: Callable[..., Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Call a required local model and return response text plus audit evidence."""

    cfg = config or OpenAICompatibleLLMConfig.from_env()
    started = time.perf_counter()
    response_for_diagnostics: Any = None
    response_model = ""
    try:
        use_responses = cfg.api_style == "responses"
        if use_responses:
            request: dict[str, Any] = {
                "model": cfg.model,
                "instructions": system_prompt,
                "input": user_prompt,
                "temperature": 0,
                "max_output_tokens": max_tokens,
            }
            effort = os.environ.get("GDA_DEEPSEEK_REASONING_EFFORT", "low").strip().casefold()
            if cfg.provider == "deepseek" and effort and effort not in {"disabled", "off", "none"}:
                request["reasoning"] = {"effort": effort}
        else:
            request = {
                "model": cfg.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0,
                "max_tokens": max_tokens,
            }
            thinking_enabled = _optional_bool_env("GDA_LLM_ENABLE_THINKING")
            if thinking_enabled is not None and cfg.provider != "gemini":
                # DashScope/Qwen's OpenAI-compatible endpoint supports this
                # top-level extension. It is opt-in so ordinary OpenAI-shaped
                # servers never receive a vendor extension unexpectedly.
                request["enable_thinking"] = thinking_enabled
            if cfg.provider == "gemini":
                reasoning_effort = os.environ.get(
                    "GDA_GEMINI_REASONING_EFFORT", "low"
                ).strip().casefold()
                if reasoning_effort and reasoning_effort not in {"disabled", "off", "none"}:
                    request["reasoning_effort"] = reasoning_effort
            if cfg.provider == "openai":
                # Use the current Chat Completions token-limit field and pass
                # the GPT-5.x reasoning effort explicitly.
                model_id = cfg.model.rsplit("/", 1)[-1].casefold()
                if model_id.startswith("gpt-5"):
                    request["max_completion_tokens"] = request.pop("max_tokens")
                    reasoning_effort = os.environ.get(
                        "GDA_OPENAI_REASONING_EFFORT",
                        os.environ.get("OPENAI_REASONING_EFFORT", "low"),
                    ).strip().casefold()
                    if reasoning_effort in {"none", "low", "medium", "high", "xhigh", "max"}:
                        request["reasoning_effort"] = reasoning_effort
            if cfg.provider == "ollama":
                # Ollama's OpenAI-compatible endpoint maps reasoning_effort=none
                # to native think=false. Sending a top-level think flag is
                # currently ignored by the OpenAI compatibility layer.
                request["reasoning_effort"] = "none"
        response_id = ""
        usage_payload = None
        if client_factory is not None:
            # Test/integration hook for an OpenAI-shaped fake client.
            client = client_factory(
                api_key=cfg.api_key,
                base_url=cfg.base_url,
                timeout=cfg.timeout_seconds,
                max_retries=0,
            )
            response = (
                client.responses.create(**request)
                if use_responses
                else client.chat.completions.create(**request)
            )
            response_for_diagnostics = response
            if use_responses:
                text = _response_output_text(response)
            else:
                text = str(response.choices[0].message.content or "").strip()
            response_id = str(getattr(response, "id", "") or "")
            response_model = str(getattr(response, "model", "") or "")
            usage_payload = getattr(response, "usage", None)
        else:
            # Direct HTTP is deliberately used here instead of the OpenAI
            # Python SDK. Some Ollama releases return 502 through that SDK
            # while accepting the identical JSON over the wire. trust_env is
            # disabled so HTTP_PROXY cannot intercept 127.0.0.1 or an
            # explicitly configured internal LM Studio host.
            import httpx

            endpoint = cfg.responses_url if use_responses else cfg.chat_completions_url
            # Local services must bypass system proxies; online DeepSeek must
            # be allowed to use the configured HTTPS proxy in restricted
            # environments.
            trust_env = cfg.provider not in {"ollama", "lm_studio"}
            with httpx.Client(timeout=cfg.timeout_seconds, trust_env=trust_env) as client:
                wire_response = client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {cfg.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=request,
                )
            try:
                wire_response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                # Response bodies often contain the actionable provider error
                # (unsupported parameter/model). They never contain our
                # Authorization request header, but still cap the diagnostic.
                body = wire_response.text.strip().replace("\n", " ")[:1000]
                raise LLMServiceError(
                    f"{cfg.provider} LLM HTTP {wire_response.status_code} at "
                    f"{endpoint}: {body or '<empty response body>'}"
                ) from exc
            payload = wire_response.json()
            response_for_diagnostics = payload
            if use_responses:
                text = _response_output_text(payload)
            else:
                choices = payload.get("choices") or []
                if not choices:
                    raise LLMServiceError("LLM response does not contain choices")
                message = choices[0].get("message") or {}
                text = str(message.get("content") or "").strip()
            response_id = str(payload.get("id") or "")
            response_model = str(payload.get("model") or "")
            usage_payload = payload.get("usage")
        if not text:
            details = (
                f" ({_response_empty_diagnostics(response_for_diagnostics)})"
                if use_responses
                else ""
            )
            raise LLMServiceError(f"{cfg.provider} LLM returned an empty response{details}")
    except LLMServiceError:
        raise
    except Exception as exc:
        raise LLMServiceError(
            f"{cfg.provider} LLM request failed at "
            f"{cfg.responses_url if cfg.api_style == 'responses' else cfg.chat_completions_url}: "
            f"{exc}"
        ) from exc

    elapsed_ms = round((time.perf_counter() - started) * 1000)
    evidence = {
        "provider": cfg.provider,
        "model": cfg.model,
        "base_url": cfg.base_url,
        "endpoint": cfg.responses_url if cfg.api_style == "responses" else cfg.chat_completions_url,
        "api_style": cfg.api_style,
        "request_id": response_id,
        "response_model": response_model or None,
        "latency_ms": elapsed_ms,
        "prompt_sha256": _sha256_text(f"{system_prompt}\n{user_prompt}"),
        "response_sha256": _sha256_text(text),
        "status": "succeeded",
    }
    if "enable_thinking" in request:
        evidence["thinking_enabled"] = request["enable_thinking"]
    if "reasoning_effort" in request:
        evidence["reasoning_effort"] = request["reasoning_effort"]
    usage = usage_payload
    if usage is not None:
        def _usage_value(name: str):
            return usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)

        evidence["usage"] = {
            "prompt_tokens": _usage_value("prompt_tokens") or _usage_value("input_tokens"),
            "completion_tokens": _usage_value("completion_tokens") or _usage_value("output_tokens"),
            "total_tokens": _usage_value("total_tokens"),
        }
    return text, evidence


def _response_output_text(response: Any) -> str:
    """Extract output text from an OpenAI/DeepSeek Responses response."""

    if isinstance(response, dict):
        direct = response.get("output_text")
        output = response.get("output") or []
    else:
        direct = getattr(response, "output_text", None)
        output = getattr(response, "output", None) or []
    if direct:
        return str(direct).strip()
    texts: list[str] = []
    for item in output:
        if isinstance(item, dict):
            content = item.get("content") or []
            item_type = item.get("type")
        else:
            content = getattr(item, "content", None) or []
            item_type = getattr(item, "type", None)
        if item_type == "output_text" and isinstance(item, dict) and item.get("text"):
            texts.append(str(item["text"]))
        for part in content:
            if isinstance(part, dict):
                if part.get("type") in {"output_text", "text"} and part.get("text"):
                    texts.append(str(part["text"]))
            else:
                part_type = getattr(part, "type", None)
                part_text = getattr(part, "text", None)
                if part_type in {"output_text", "text"} and part_text:
                    texts.append(str(part_text))
    return "\n".join(texts).strip()


def _response_empty_diagnostics(response: Any) -> str:
    """Return a content-free summary for diagnosing empty Responses output."""

    if isinstance(response, dict):
        status = response.get("status")
        incomplete = response.get("incomplete_details")
        output = response.get("output") or []
    else:
        status = getattr(response, "status", None)
        incomplete = getattr(response, "incomplete_details", None)
        output = getattr(response, "output", None) or []
    output_types: list[str] = []
    for item in output:
        item_type = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
        if item_type:
            output_types.append(str(item_type))
    return (
        f"status={status or 'unknown'}, "
        f"incomplete_details={incomplete or 'none'}, "
        f"output_types={','.join(output_types) or 'none'}"
    )
