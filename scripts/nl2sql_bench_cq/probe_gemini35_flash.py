"""Probe Gemini 3.5 Flash (GA 2026-05-19).

Verifies the model is reachable via google-genai with the same config shape
run_cq_eval uses (temperature=0.0). The 3.5 docs say temperature is no longer
recommended but still accepted; this probe confirms that empirically.
"""
from __future__ import annotations
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


def probe(model_id: str, with_temp: bool) -> dict:
    from google import genai
    from google.genai import types
    client = genai.Client()
    kwargs = {
        "http_options": types.HttpOptions(
            timeout=30_000,
            retry_options=types.HttpRetryOptions(initial_delay=2.0, attempts=2),
        ),
    }
    if with_temp:
        kwargs["temperature"] = 0.0
    t0 = time.time()
    try:
        resp = client.models.generate_content(
            model=model_id,
            contents=[PROMPT],
            config=types.GenerateContentConfig(**kwargs),
        )
        dur = time.time() - t0
        text = (resp.text or "").strip()
        return {"ok": True, "dur_ms": int(dur * 1000), "text": text[:300]}
    except Exception as e:
        dur = time.time() - t0
        return {"ok": False, "dur_ms": int(dur * 1000),
                "error": f"{type(e).__name__}: {str(e)[:300]}"}


def main():
    for label, with_temp in [("with temperature=0.0", True),
                              ("no temperature", False)]:
        print(f"\n[probe] gemini-3.5-flash {label}")
        r = probe("gemini-3.5-flash", with_temp=with_temp)
        status = "OK" if r["ok"] else "FAIL"
        print(f"  {status}  ({r['dur_ms']} ms)")
        if r["ok"]:
            print(f"  text: {r['text'][:200]}")
        else:
            print(f"  err:  {r['error']}")


if __name__ == "__main__":
    main()
