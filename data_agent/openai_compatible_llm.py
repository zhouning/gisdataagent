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

from .nl2sql_observability import observe_stage, annotate_stage


class LLMServiceError(RuntimeError):
    """Raised when a required local LLM request cannot be completed."""

    def __init__(self, message: str, *, code: str = "request_failed",
                 retryable: bool = True, evidence: dict | None = None):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.evidence = evidence or {}


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
    http_proxy: str | None = None

    @classmethod
    def from_env(cls) -> OpenAICompatibleLLMConfig:
        explicit_provider = os.environ.get("GDA_LLM_PROVIDER")
        provider_hint = str(explicit_provider or "").strip().casefold().replace("-", "_")
        configured_base = (
            os.environ.get("GDA_LLM_BASE_URL")
            or (os.environ.get("OPENAI_BASE_URL") if provider_hint == "openai" else None)
            or (
                "https://generativelanguage.googleapis.com/v1beta/openai"
                if provider_hint == "gemini"
                else None
            )
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
        http_proxy = os.environ.get("GDA_LLM_HTTP_PROXY", "").strip() or None
        if http_proxy:
            parsed_proxy = urlsplit(http_proxy)
            if (parsed_proxy.scheme not in {"http", "https", "socks5", "socks5h"}
                    or not parsed_proxy.hostname or parsed_proxy.query or parsed_proxy.fragment):
                raise ValueError("GDA_LLM_HTTP_PROXY must be a valid proxy URL")
        return cls(provider, base_url, model, api_key, timeout, api_style, http_proxy)

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    @property
    def responses_url(self) -> str:
        return f"{self.base_url}/responses"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def llm_http_client_options(config: OpenAICompatibleLLMConfig) -> dict[str, Any]:
    """Apply an explicit online proxy while always bypassing it for local models."""
    if config.provider in {"ollama", "lm_studio"}:
        return {"trust_env": False}
    if config.http_proxy:
        return {"proxy": config.http_proxy, "trust_env": False}
    return {"trust_env": True}


def public_proxy_url(value: str) -> str:
    """Keep proxy routing evidence without user information or URL secrets."""
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    netloc = host + (f":{parsed.port}" if parsed.port else "")
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


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


@observe_stage("llm.request")
def chat_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    config: OpenAICompatibleLLMConfig | None = None,
    max_tokens: int = 800,
    client_factory: Callable[..., Any] | None = None,
    response_format: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Call a required local model and return response text plus audit evidence."""

    cfg = config or OpenAICompatibleLLMConfig.from_env()
    annotate_stage(provider=cfg.provider, model=cfg.model, dispatched=False)
    started = time.perf_counter()
    response_for_diagnostics: Any = None
    response_model = ""
    request: dict[str, Any] = {}
    response_id = ""
    usage_payload = None
    text = ""
    from .llm_call_budget import BudgetDenied, active_budget
    budget = active_budget()
    reservation = None

    def evidence(status: str, error_code: str | None = None) -> dict:
        result = _completion_evidence(
            cfg, request, response_for_diagnostics, usage_payload,
            response_id=response_id, response_model=response_model,
            prompt=system_prompt + "\n" + user_prompt, response_text=text,
            elapsed_ms=round((time.perf_counter() - started) * 1000), status=status,
        )
        if error_code:
            result["error_code"] = error_code
        if reservation is not None:
            result["budget_reservation"] = reservation
        annotate_stage(actual_model=response_model or cfg.model,
                       **(result.get("usage") or {}))
        return result
    try:
        use_responses = cfg.api_style == "responses"
        if response_format is not None and use_responses:
            raise ValueError("response_format requires the Chat Completions API")
        if use_responses:
            request = {
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
            if response_format is not None:
                request["response_format"] = response_format
            thinking_enabled = _optional_bool_env("GDA_LLM_ENABLE_THINKING")
            if thinking_enabled is not None and cfg.provider not in {"gemini", "ollama"}:
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
                from .llm_reasoning import ollama_reasoning_effort

                effort = ollama_reasoning_effort()
                if effort is not None:
                    request["reasoning_effort"] = effort
        if budget is not None:
            reservation = budget.reserve(cfg, request)
            # Admission expires across generation, repair and retry calls.
            from dataclasses import replace
            from datetime import datetime, timezone
            remaining = (datetime.fromisoformat(budget.policy['expires_at'].replace('Z', '+00:00'))
                         - datetime.now(timezone.utc)).total_seconds()
            if remaining <= 0:
                budget._deny("budget_expired")
            cfg = replace(cfg, timeout_seconds=min(cfg.timeout_seconds, remaining))
        if client_factory is not None:
            # Test/integration hook for an OpenAI-shaped fake client.
            client = client_factory(
                api_key=cfg.api_key,
                base_url=cfg.base_url,
                timeout=cfg.timeout_seconds,
                max_retries=0,
            )
            annotate_stage(dispatched=True)
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
            with httpx.Client(timeout=cfg.timeout_seconds, **llm_http_client_options(cfg)) as client:
                annotate_stage(dispatched=True)
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
            response_id = str(payload.get("id") or "")
            response_model = str(payload.get("model") or "")
            usage_payload = payload.get("usage")
            if use_responses:
                text = _response_output_text(payload)
            else:
                choices = payload.get("choices") or []
                if not choices:
                    raise LLMServiceError("LLM response does not contain choices")
                message = choices[0].get("message") or {}
                text = str(message.get("content") or "").strip()
        finish_reason = _chat_finish_reason(response_for_diagnostics) if not use_responses else None
        if not text or finish_reason == "length":
            details = (
                f" ({_response_empty_diagnostics(response_for_diagnostics)})"
                if use_responses
                else ""
            )
            code = "output_token_limit" if finish_reason == "length" else "empty_response"
            if code == "output_token_limit":
                message = f"{cfg.provider} LLM output reached the configured token limit"
            else:
                message = f"{cfg.provider} LLM returned an empty response{details}"
            raise LLMServiceError(message, code=code, retryable=code != "output_token_limit")
    except BudgetDenied:
        raise
    except LLMServiceError as exc:
        if reservation is not None:
            budget.finish(reservation, "failed", usage_payload)
        exc.evidence = evidence("failed", exc.code)
        raise
    except Exception as exc:
        if reservation is not None:
            budget.finish(reservation, "failed", usage_payload)
        raise LLMServiceError(
            f"{cfg.provider} LLM request failed at "
            f"{cfg.responses_url if cfg.api_style == 'responses' else cfg.chat_completions_url}: "
            f"{exc}", evidence=evidence("failed", "request_failed")
        ) from exc
    except BaseException:
        if reservation is not None:
            budget.finish(reservation, "interrupted", usage_payload)
        raise

    if reservation is not None:
        budget.finish(reservation, "succeeded", usage_payload)
    return text, evidence("succeeded")


def _value(obj: Any, name: str, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _chat_finish_reason(response: Any) -> str | None:
    choices = _value(response, "choices", []) or []
    if not choices:
        return None
    reason = _value(choices[0], "finish_reason")
    # Diagnostics must not copy arbitrary model/provider text into traces.
    return reason if reason in {"stop", "length", "content_filter", "tool_calls", "function_call"} else "other" if reason else None


def _completion_evidence(cfg, request, response, usage, *, response_id: str,
                         response_model: str, prompt: str, response_text: str,
                         elapsed_ms: int, status: str) -> dict:
    evidence = {
        "provider": cfg.provider,
        "model": cfg.model,
        "base_url": cfg.base_url,
        "endpoint": cfg.responses_url if cfg.api_style == "responses" else cfg.chat_completions_url,
        "api_style": cfg.api_style,
        "request_id": response_id,
        "response_model": response_model or None,
        "latency_ms": elapsed_ms,
        "prompt_sha256": _sha256_text(prompt),
        "response_sha256": _sha256_text(response_text),
        "status": status,
        "response_received": response is not None,
        "max_output_tokens": request.get("max_tokens", request.get("max_output_tokens", request.get("max_completion_tokens"))),
    }
    finish_reason = _chat_finish_reason(response)
    if finish_reason:
        evidence["finish_reason"] = finish_reason
    if cfg.http_proxy and cfg.provider not in {"ollama", "lm_studio"}:
        evidence["http_proxy"] = public_proxy_url(cfg.http_proxy)
    if "enable_thinking" in request:
        evidence["thinking_enabled"] = request["enable_thinking"]
    if "response_format" in request:
        evidence["response_format"] = request["response_format"].get("type")
    if "reasoning_effort" in request:
        evidence["reasoning_effort"] = request["reasoning_effort"]
    elif cfg.provider == "ollama":
        evidence["reasoning_effort"] = "auto"
    if usage is not None:
        def _usage_value(name: str):
            value = _value(usage, name)
            return value if type(value) is int and value >= 0 else None

        def _first_usage(primary, alternate):
            value = _usage_value(primary)
            return value if value is not None else _usage_value(alternate)

        evidence["usage"] = {
            "prompt_tokens": _first_usage("prompt_tokens", "input_tokens"),
            "completion_tokens": _first_usage("completion_tokens", "output_tokens"),
            "total_tokens": _usage_value("total_tokens"),
        }
        details = _value(usage, "completion_tokens_details") or _value(usage, "output_tokens_details")
        reasoning = _value(details, "reasoning_tokens")
        if type(reasoning) is int and reasoning >= 0:
            evidence["usage"]["reasoning_tokens"] = reasoning
    return evidence


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
