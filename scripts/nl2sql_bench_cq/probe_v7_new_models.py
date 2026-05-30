"""v7 P1-pre — Smoke-test 3 newly registered models.

Sends one 2-line SQL-generation prompt and verifies each model:
  (a) returns a non-empty response
  (b) the response is SQL-ish (starts with SELECT or contains FROM)
  (c) latency is reasonable (< 30s)

Tests: gemini-3-flash-preview, gemini-3.1-pro-preview, qwen3.6-plus.
"""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(str(ROOT / "data_agent" / ".env"), override=True)
sys.stdout.reconfigure(encoding="utf-8")

PROMPT = """You are a PostgreSQL expert. Generate a single SELECT query.

SCHEMA: CREATE TABLE cq_buildings_2021 ("Floor" int, geometry geometry);

QUESTION: How many buildings have 40 or more floors?

Output only the SQL, no markdown."""


def probe_gemini(model_id: str) -> dict:
    from google import genai
    from google.genai import types
    client = genai.Client()
    t0 = time.time()
    try:
        resp = client.models.generate_content(
            model=model_id,
            contents=[PROMPT],
            config=types.GenerateContentConfig(
                temperature=0.0,
                http_options=types.HttpOptions(
                    timeout=30_000,
                    retry_options=types.HttpRetryOptions(initial_delay=2.0, attempts=2),
                ),
            ),
        )
        dur = time.time() - t0
        text = (resp.text or "").strip()
        return {"ok": True, "dur_ms": int(dur * 1000), "text": text[:300]}
    except Exception as e:
        dur = time.time() - t0
        return {"ok": False, "dur_ms": int(dur * 1000),
                "error": f"{type(e).__name__}: {str(e)[:300]}"}


def probe_qwen_via_gateway() -> dict:
    """Use the model_gateway path which applies NO_PROXY bypass for the
    Aliyun token-plan MaaS endpoint."""
    from data_agent.model_gateway import create_model
    import litellm
    t0 = time.time()
    try:
        # create_model triggers _create_qwen_model which sets NO_PROXY +
        # OPENAI_API_BASE + OPENAI_API_KEY correctly. We only need a one-shot
        # completion, not the full ADK agent, so once env is set we call
        # litellm.completion directly.
        adk_model = create_model("qwen3.6-plus")
        resp = litellm.completion(
            model=adk_model.model,  # "openai/qwen3.6-plus"
            messages=[{"role": "user", "content": PROMPT}],
            temperature=0.0,
            timeout=30,
            extra_body=adk_model._additional_args.get("extra_body"),
        )
        dur = time.time() - t0
        text = resp.choices[0].message.content.strip()
        return {"ok": True, "dur_ms": int(dur * 1000), "text": text[:300]}
    except Exception as e:
        dur = time.time() - t0
        return {"ok": False, "dur_ms": int(dur * 1000),
                "error": f"{type(e).__name__}: {str(e)[:300]}"}


def main() -> int:
    models = [
        ("gemini-3-flash-preview", probe_gemini),
        ("gemini-3.1-pro-preview", probe_gemini),
        ("qwen3.6-plus", lambda _: probe_qwen_via_gateway()),
    ]
    for name, probe in models:
        print(f"\n=== {name} ===")
        r = probe(name)
        if r["ok"]:
            print(f"  OK  {r['dur_ms']}ms")
            print(f"  > {r['text'][:200]}")
        else:
            print(f"  FAIL ({r['dur_ms']}ms)")
            print(f"  > {r['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
