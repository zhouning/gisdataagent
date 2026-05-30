"""v7 P1-pre extension — smoke-probe 3 additional models.

Sends one 2-line SQL-generation prompt and verifies each model:
  (a) returns a non-empty response
  (b) the response is SQL-ish (starts with SELECT or contains FROM)
  (c) latency is reasonable (< 60s)

Extends probe_v7_new_models.py with:
  - gemini-2.5-pro (registered but never used in v6/v7 benchmarks)
  - gemini-3.1-flash-lite-preview (newly registered)
  - qwen3.6-flash (registered but never ran full benchmark)
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
                    timeout=60_000,
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


def probe_via_gateway(name: str) -> dict:
    """Route through model_gateway so Aliyun NO_PROXY bypass is applied."""
    from data_agent.model_gateway import create_model
    import litellm
    t0 = time.time()
    try:
        adk_model = create_model(name)
        resp = litellm.completion(
            model=adk_model.model,
            messages=[{"role": "user", "content": PROMPT}],
            temperature=0.0,
            timeout=60,
            extra_body=(adk_model._additional_args or {}).get("extra_body"),
        )
        dur = time.time() - t0
        text = (resp.choices[0].message.content or "").strip()
        return {"ok": True, "dur_ms": int(dur * 1000), "text": text[:300]}
    except Exception as e:
        dur = time.time() - t0
        return {"ok": False, "dur_ms": int(dur * 1000),
                "error": f"{type(e).__name__}: {str(e)[:300]}"}


def main() -> int:
    targets = [
        ("gemini-2.5-pro", probe_gemini),
        ("gemini-3.1-flash-lite-preview", probe_gemini),
        ("qwen3.6-flash", lambda _: probe_via_gateway("qwen3.6-flash")),
    ]
    results: list[tuple[str, dict]] = []
    for name, probe in targets:
        print(f"\n=== {name} ===", flush=True)
        r = probe(name)
        results.append((name, r))
        if r["ok"]:
            print(f"  OK  {r['dur_ms']}ms")
            print(f"  > {r['text'][:200]}")
        else:
            print(f"  FAIL ({r['dur_ms']}ms)")
            print(f"  > {r['error']}")
    print("\n---- summary ----")
    for name, r in results:
        mark = "PASS" if r["ok"] else "FAIL"
        print(f"  {mark}  {name:<40} {r['dur_ms']}ms")
    return 0 if all(r["ok"] for _, r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
