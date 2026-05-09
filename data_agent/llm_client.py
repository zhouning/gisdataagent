"""Unified LLM Client — Gemini-first with DeepSeek fallback on 429.

Provides a single `generate_text()` function that:
1. Tries Gemini (google.genai) first
2. On 429 RESOURCE_EXHAUSTED, falls back to DeepSeek via OpenAI SDK
3. Returns plain text response

Usage:
    from data_agent.llm_client import generate_text
    text = generate_text("your prompt", model="fast")
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Model tier mapping
_GEMINI_MODELS = {
    "fast": "gemini-2.0-flash",
    "standard": "gemini-2.5-flash",
    "pro": "gemini-2.5-pro",
}

_DEEPSEEK_MODELS = {
    "fast": "deepseek-v4-flash",
    "standard": "deepseek-v4-flash",
    "pro": "deepseek-v4-pro",
}

_DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def _get_deepseek_key() -> Optional[str]:
    return os.environ.get("DEEPSEEK_API_KEY")


def _call_gemini(prompt: str, model: str, temperature: float = 0.0,
                 timeout_ms: int = 30_000) -> str:
    """Call Gemini API. Raises on 429."""
    from google import genai
    client = genai.Client()
    resp = client.models.generate_content(
        model=model,
        contents=[prompt],
        config=genai.types.GenerateContentConfig(
            http_options=genai.types.HttpOptions(
                timeout=timeout_ms,
                retry_options=genai.types.HttpRetryOptions(
                    initial_delay=1.0, attempts=2,
                ),
            ),
            temperature=temperature,
        ),
    )
    return (resp.text or "").strip()


def _call_deepseek(prompt: str, model: str, temperature: float = 0.0,
                    timeout: int = 30) -> str:
    """Call DeepSeek API via OpenAI SDK."""
    from openai import OpenAI
    key = _get_deepseek_key()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY not set")
    client = OpenAI(api_key=key, base_url=_DEEPSEEK_BASE_URL)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        timeout=timeout,
    )
    return (resp.choices[0].message.content or "").strip()


def generate_text(
    prompt: str,
    tier: str = "fast",
    temperature: float = 0.0,
    timeout_ms: int = 30_000,
    gemini_model: Optional[str] = None,
) -> str:
    """Generate text with Gemini-first, DeepSeek-fallback strategy.

    Args:
        prompt: The prompt text.
        tier: Model tier — "fast", "standard", or "pro".
        temperature: Sampling temperature.
        timeout_ms: Timeout in milliseconds.
        gemini_model: Override Gemini model name (ignores tier).

    Returns:
        Generated text string.

    Raises:
        RuntimeError: If both Gemini and DeepSeek fail.
    """
    # --- env-flag: force DeepSeek as primary (for cross-family ablation) ---
    _FORCE_DEEPSEEK = os.environ.get("NL2SQL_FORCE_DEEPSEEK", "").strip() in ("1", "true", "True")
    if _FORCE_DEEPSEEK:
        ds_key = _get_deepseek_key()
        if not ds_key:
            raise RuntimeError("NL2SQL_FORCE_DEEPSEEK=1 but DEEPSEEK_API_KEY missing")
        ds_model = _DEEPSEEK_MODELS.get(tier, _DEEPSEEK_MODELS["fast"])
        return _call_deepseek(prompt, ds_model, temperature, timeout_ms // 1000)
    # -----------------------------------------------------------------------

    g_model = gemini_model or _GEMINI_MODELS.get(tier, _GEMINI_MODELS["fast"])
    last_error = None

    # 1. Try Gemini
    try:
        return _call_gemini(prompt, g_model, temperature, timeout_ms)
    except Exception as e:
        err_str = str(e)
        is_429 = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
        if not is_429:
            raise
        last_error = e
        logger.info("[LLM] Gemini 429, falling back to DeepSeek (%s)", tier)

    # 2. Fallback to DeepSeek
    ds_key = _get_deepseek_key()
    if not ds_key:
        logger.warning("[LLM] DeepSeek fallback unavailable (no DEEPSEEK_API_KEY)")
        raise last_error  # type: ignore[misc]

    ds_model = _DEEPSEEK_MODELS.get(tier, _DEEPSEEK_MODELS["fast"])
    try:
        return _call_deepseek(prompt, ds_model, temperature, timeout_ms // 1000)
    except Exception as ds_err:
        logger.error("[LLM] DeepSeek fallback also failed: %s", ds_err)
        raise RuntimeError(f"Both Gemini and DeepSeek failed. Gemini: {last_error}; DeepSeek: {ds_err}")


def strip_fences(s: str) -> str:
    """Strip markdown code fences from LLM output."""
    s = (s or "").strip()
    m = re.match(r"^```(?:sql|json|python)?\s*(.*?)\s*```$", s, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else s
