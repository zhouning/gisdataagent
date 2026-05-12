"""Gemma Ollama smoke probe — minimal connectivity + function-call test.

Two-stage probe before running the full NL2SQL agent:
  Stage 1: raw LiteLLM completion (no tools) — confirms endpoint + model + auth
  Stage 2: LiteLLM completion WITH tools — confirms function-call schema works
           (Ollama capabilities list 'tools' but ADK docs warn this is
           model-template dependent and may infinite-loop)

Stage 3 (run separately via probe_gemma_ollama_step2.py): full ADK agent on
4 NL2SQL questions covering buckets A/B/D — same qids as DS/Qwen probes.

Pass criteria for this script:
  - Stage 1 returns non-empty content within 30s
  - Stage 2 returns a tool_call (not a text refusal) within 60s
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(str(ROOT / "data_agent" / ".env"), override=False)


def _setup_proxy_bypass(host: str) -> None:
    existing = os.environ.get("NO_PROXY", "") or os.environ.get("no_proxy", "")
    merged = ",".join(h for h in (existing.split(",") + [host]) if h)
    os.environ["NO_PROXY"] = merged
    os.environ["no_proxy"] = merged


OLLAMA_BASE = "http://192.168.31.252:11434"
MODEL = "ollama_chat/gemma4:31b"
_setup_proxy_bypass("192.168.31.252")
os.environ["OLLAMA_API_BASE"] = OLLAMA_BASE


def stage1_raw_completion() -> bool:
    print("=" * 60)
    print("Stage 1: raw LiteLLM completion (no tools)")
    print("=" * 60)
    import litellm
    t0 = time.time()
    try:
        resp = litellm.completion(
            model=MODEL,
            api_base=OLLAMA_BASE,
            messages=[
                {"role": "system",
                 "content": "You are a SQL expert. Respond concisely."},
                {"role": "user",
                 "content": "Write a PostgreSQL query to count rows in a "
                            "table called 'parcels'. SQL only, no prose."},
            ],
            temperature=0.0,
            timeout=60,
        )
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {str(e)[:300]}")
        return False
    dur = time.time() - t0
    content = resp.choices[0].message.content or ""
    print(f"latency: {dur:.1f}s")
    print(f"tokens: prompt={resp.usage.prompt_tokens} "
          f"completion={resp.usage.completion_tokens}")
    print(f"content ({len(content)} chars):")
    print(content[:500])
    print()
    return bool(content.strip())


def stage2_function_call() -> bool:
    print("=" * 60)
    print("Stage 2: LiteLLM completion WITH function-call schema")
    print("=" * 60)
    import litellm
    tools = [{
        "type": "function",
        "function": {
            "name": "execute_sql",
            "description": "Execute a SQL query against the geospatial database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "The SQL query to execute.",
                    },
                },
                "required": ["sql"],
            },
        },
    }]
    t0 = time.time()
    try:
        resp = litellm.completion(
            model=MODEL,
            api_base=OLLAMA_BASE,
            messages=[
                {"role": "system",
                 "content": "You are a PostGIS SQL expert. To answer the "
                            "user's question, call the execute_sql tool "
                            "with the SQL query that answers it."},
                {"role": "user",
                 "content": "How many parcels are in the table 'parcels'?"},
            ],
            tools=tools,
            tool_choice="auto",
            temperature=0.0,
            timeout=120,
        )
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {str(e)[:300]}")
        return False
    dur = time.time() - t0
    msg = resp.choices[0].message
    print(f"latency: {dur:.1f}s")
    print(f"tokens: prompt={resp.usage.prompt_tokens} "
          f"completion={resp.usage.completion_tokens}")
    print(f"finish_reason: {resp.choices[0].finish_reason}")
    if msg.tool_calls:
        print(f"tool_calls: {len(msg.tool_calls)}")
        for tc in msg.tool_calls:
            print(f"  - {tc.function.name}({tc.function.arguments[:200]})")
        return True
    print(f"NO TOOL CALL — text content: {(msg.content or '')[:300]}")
    return False


def main() -> int:
    print(f"endpoint: {OLLAMA_BASE}")
    print(f"model:    {MODEL}")
    print(f"NO_PROXY: {os.environ.get('NO_PROXY')}")
    print()
    s1 = stage1_raw_completion()
    print(f"Stage 1: {'PASS' if s1 else 'FAIL'}\n")
    if not s1:
        print("Stage 1 failed; skipping Stage 2.")
        return 1
    s2 = stage2_function_call()
    print(f"Stage 2: {'PASS' if s2 else 'FAIL'}\n")
    return 0 if (s1 and s2) else 2


if __name__ == "__main__":
    raise SystemExit(main())
