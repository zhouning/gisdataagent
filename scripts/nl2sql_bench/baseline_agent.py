"""Pure-LLM NL2SQL baseline — no semantic layer, no RAG, no few-shot.

Sends {full schema dump} + {question} to Gemini and asks for SQL back.
This is the control group for the A/B benchmark against the full pipeline.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from data_agent.db_engine import get_engine  # noqa: E402

from google import genai as genai_client  # noqa: E402
from google.genai import types  # noqa: E402

SCHEMA = "floodsql_bench"
DEFAULT_MODEL = os.environ.get("MODEL_STANDARD", "gemini-2.5-flash")

_client = genai_client.Client()
_SCHEMA_CACHE: str | None = None


def dump_schema(schema: str = SCHEMA) -> str:
    """Build a compact schema string suitable for injection into a prompt."""
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is not None:
        return _SCHEMA_CACHE

    engine = get_engine()
    if engine is None:
        raise RuntimeError("DB engine not configured")

    lines: list[str] = []
    with engine.connect() as conn:
        tables = [r[0] for r in conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema=:s ORDER BY table_name"
        ), {"s": schema}).fetchall()]

        for t in tables:
            cols = conn.execute(text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema=:s AND table_name=:t ORDER BY ordinal_position"
            ), {"s": schema, "t": t}).fetchall()

            # Geometry info
            geom = conn.execute(text(
                "SELECT type, srid FROM geometry_columns "
                "WHERE f_table_schema=:s AND f_table_name=:t LIMIT 1"
            ), {"s": schema, "t": t}).fetchone()
            suffix = f"  [geom={geom[0]}, srid={geom[1]}]" if geom else ""

            col_strs = [f"{c[0]}:{c[1]}" for c in cols]
            lines.append(f"{schema}.{t}{suffix}")
            # wrap columns at 6 per line for readability
            for i in range(0, len(col_strs), 6):
                lines.append("  " + ", ".join(col_strs[i:i + 6]))

    _SCHEMA_CACHE = "\n".join(lines)
    return _SCHEMA_CACHE


SYSTEM_PROMPT = """You are a PostGIS SQL expert. Convert the user question into a
single PostgreSQL/PostGIS SELECT query over the given schema.

Rules:
- Output ONLY the SQL, no commentary, no markdown fences.
- Always schema-qualify tables (e.g. floodsql_bench.claims).
- Use PostGIS functions (ST_Within, ST_Intersects, ST_Buffer, ST_Distance, etc.)
  when spatial reasoning is needed.
- Use CAST or ::numeric when dividing integers.
- Do not add LIMIT unless the question explicitly asks for a sample/top-K.
"""


def _strip_fences(s: str) -> str:
    s = s.strip()
    m = re.match(r"^```(?:sql)?\s*(.*?)\s*```$", s, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return s


def generate_sql(question: str, schema_dump: str | None = None,
                 model: str = DEFAULT_MODEL, timeout_ms: int = 60_000) -> dict:
    """Generate SQL for `question`. Returns {status, sql, tokens, error}."""
    if schema_dump is None:
        schema_dump = dump_schema()

    prompt = (
        SYSTEM_PROMPT
        + "\n\nSCHEMA:\n"
        + schema_dump
        + f"\n\nQUESTION: {question}\n\nSQL:"
    )

    try:
        resp = _client.models.generate_content(
            model=model,
            contents=[prompt],
            config=types.GenerateContentConfig(
                http_options=types.HttpOptions(
                    timeout=timeout_ms,
                    retry_options=types.HttpRetryOptions(initial_delay=2.0, attempts=3),
                ),
                temperature=0.0,
            ),
        )
    except Exception as e:
        return {"status": "error", "sql": "", "error": str(e), "tokens": 0}

    text_out = (resp.text or "").strip()
    sql = _strip_fences(text_out)

    input_tokens = 0
    output_tokens = 0
    if hasattr(resp, "usage_metadata") and resp.usage_metadata:
        input_tokens = getattr(resp.usage_metadata, "prompt_token_count", 0) or 0
        output_tokens = getattr(resp.usage_metadata, "candidates_token_count", 0) or 0

    return {
        "status": "ok",
        "sql": sql,
        "error": None,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tokens": input_tokens + output_tokens,
    }


if __name__ == "__main__":
    print(dump_schema()[:500])
    print("---")
    r = generate_sql("How many claims are in Texas?")
    print(r)
