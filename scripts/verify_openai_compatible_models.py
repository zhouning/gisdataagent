#!/usr/bin/env python3
"""Verify configured chat and embedding models on an internal OpenAI API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def normalize_base_url(value: str) -> str:
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        raise ValueError("model base URL is required")
    if "://" not in raw:
        raw = f"http://{raw}"
    for suffix in ("/chat/completions", "/embeddings", "/models"):
        if raw.casefold().endswith(suffix):
            raw = raw[: -len(suffix)].rstrip("/")
            break
    if not raw.casefold().endswith("/v1"):
        raw = f"{raw}/v1"
    return raw


def request_json(
    url: str,
    *,
    api_key: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> tuple[dict[str, Any], float]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, headers=headers, data=data)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    started = time.perf_counter()
    with opener.open(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body), round((time.perf_counter() - started) * 1000, 2)


def verify_from_env(*, probe_chat: bool = True) -> dict[str, Any]:
    provider = os.environ.get("GDA_LLM_PROVIDER", "").strip().casefold()
    llm_base = normalize_base_url(os.environ.get("GDA_LLM_BASE_URL", ""))
    llm_model = os.environ.get("GDA_LLM_MODEL", "").strip()
    llm_key = os.environ.get("GDA_LLM_API_KEY", "lm-studio").strip()
    embedding_base = normalize_base_url(
        os.environ.get("GDA_EMBEDDING_BASE_URL") or llm_base
    )
    embedding_model = (
        os.environ.get("GDA_EMBEDDING_MODEL")
        or os.environ.get("EMBEDDING_MODEL")
        or ""
    ).strip()
    embedding_key = (
        os.environ.get("GDA_EMBEDDING_API_KEY")
        or os.environ.get("EMBEDDING_API_KEY")
        or llm_key
    ).strip()
    expected_dimension = int(
        os.environ.get("GDA_EMBEDDING_DIMENSION")
        or os.environ.get("EMBEDDING_DIMENSION")
        or "0"
    )
    if not llm_model:
        raise ValueError("GDA_LLM_MODEL is required")
    if not embedding_model:
        raise ValueError("EMBEDDING_MODEL is required")

    llm_models, llm_models_ms = request_json(
        f"{llm_base}/models", api_key=llm_key
    )
    llm_model_ids = [str(item.get("id") or "") for item in llm_models.get("data") or []]
    embedding_model_ids = llm_model_ids
    embedding_models_ms = llm_models_ms
    if embedding_base != llm_base or embedding_key != llm_key:
        embedding_models, embedding_models_ms = request_json(
            f"{embedding_base}/models", api_key=embedding_key
        )
        embedding_model_ids = [
            str(item.get("id") or "") for item in embedding_models.get("data") or []
        ]
    if llm_model not in llm_model_ids:
        raise ValueError(f"chat model not found in /v1/models: {llm_model}")
    if embedding_model not in embedding_model_ids:
        raise ValueError(
            f"embedding model not found in /v1/models: {embedding_model}"
        )

    chat_ms = None
    if probe_chat:
        chat_response, chat_ms = request_json(
            f"{llm_base}/chat/completions",
            api_key=llm_key,
            payload={
                "model": llm_model,
                "messages": [{"role": "user", "content": "reply with OK"}],
                "temperature": 0,
                "max_tokens": 8,
            },
            timeout=float(os.environ.get("GDA_LLM_TIMEOUT_SECONDS", "180")),
        )
        if not (chat_response.get("choices") or []):
            raise ValueError("chat completion response does not contain choices")

    embedding_response, embedding_ms = request_json(
        f"{embedding_base}/embeddings",
        api_key=embedding_key,
        payload={"model": embedding_model, "input": ["地类图斑面积"]},
    )
    rows = embedding_response.get("data") or []
    vector = rows[0].get("embedding") if rows else None
    if not isinstance(vector, list) or not vector:
        raise ValueError("embedding response does not contain a vector")
    actual_dimension = len(vector)
    if expected_dimension and actual_dimension != expected_dimension:
        raise ValueError(
            f"embedding dimension mismatch: expected {expected_dimension}, "
            f"received {actual_dimension}"
        )

    return {
        "status": "passed",
        "checked_at": datetime.now(UTC).isoformat(),
        "provider": provider or "openai_compatible",
        "chat": {
            "base_url": llm_base,
            "model": llm_model,
            "models_latency_ms": llm_models_ms,
            "probe_latency_ms": chat_ms,
        },
        "embedding": {
            "base_url": embedding_base,
            "model": embedding_model,
            "dimension": actual_dimension,
            "models_latency_ms": embedding_models_ms,
            "probe_latency_ms": embedding_ms,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-chat", action="store_true")
    args = parser.parse_args()
    try:
        report = verify_from_env(probe_chat=not args.skip_chat)
        exit_code = 0
    except (ValueError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        report = {
            "status": "failed",
            "checked_at": datetime.now(UTC).isoformat(),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        exit_code = 1
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
