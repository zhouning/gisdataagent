"""LLM-based Schema Mapper — Monkuu-style table selection via single LLM call.

Background
----------
The current `resolve_semantic_context` (data_agent/semantic_layer.py) uses
substring + SequenceMatcher fuzzy matching. This works when user text contains
table aliases verbatim, but fails on indirect Chinese references — e.g. the
question "百度 AOI" cannot be matched to `cq_baidu_aoi_2024` by substring
because neither is a substring of the other and Chinese isn't tokenized.

This module adds an LLM-call schema mapper as a **backfill layer**: when
substring matching returns too few candidates (< min_required), call an LLM
with the user question + full schema dump and ask it to select top-K relevant
tables. Filter the response against the actual schema and return them as
candidate sources.

Validated on `CQ_GEO_HARD_15` (the universal-fail question across 11 families):
- substring match: 0 candidates
- LLM call (gemini-2.5-flash, 1828 tokens, 53 output tokens, ~3s): correctly
  returns top-4 including `cq_baidu_aoi_2024`

Per Monkuu (IJGIS 2025) §4.1 Table 7, this approach beat embedding-RAG by
~5.9pp on KaggleDBQA. We replicate the architectural claim here.

Design choices
--------------
- Cheap model only: gemini-2.5-flash (cost ~$0.0003/call)
- Cache by question hash to avoid duplicate calls in N=3 runs
- Always filter response against actual schema names (LLM may hallucinate)
- Keep substring match as primary; this is backfill only by default
"""
from __future__ import annotations

import functools
import hashlib
import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# Default conservative settings
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_TOP_K = 5
DEFAULT_MAX_TOKENS = 200  # output cap

_MAPPER_PROMPT = """你是数据库 schema 匹配助手。给定用户问题和完整 schema,选出最相关的 {top_k} 个表(按相关性排序)。

输出格式:JSON 数组,只返回表名(不带 schema 前缀)。不要任何解释、注释或 markdown。

示例输出: ["cq_buildings_2021", "cq_osm_roads_2021"]

SCHEMA:
{schema}

USER QUESTION:
{question}

RELEVANT TABLES (JSON array, top-{top_k}):"""


def _question_hash(question: str, schema: str) -> str:
    """Deterministic cache key for (question, schema) pairs."""
    h = hashlib.sha256()
    h.update(question.encode("utf-8"))
    h.update(b"||")
    h.update(schema.encode("utf-8"))
    return h.hexdigest()[:16]


@functools.lru_cache(maxsize=512)
def _mapper_call_cached(cache_key: str, question: str, schema: str, top_k: int, model: str) -> str:
    """Inner cached call. cache_key is the dedup key; other args are inputs."""
    from google import genai
    from google.genai import types

    prompt = _MAPPER_PROMPT.format(top_k=top_k, schema=schema, question=question)

    client = genai.Client()
    resp = client.models.generate_content(
        model=model,
        contents=[prompt],
        config=types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=DEFAULT_MAX_TOKENS,
            http_options=types.HttpOptions(
                timeout=30_000,
                retry_options=types.HttpRetryOptions(initial_delay=1.0, attempts=2),
            ),
        ),
    )
    return resp.text or ""


def _parse_table_names(response_text: str) -> list[str]:
    """Extract table-name list from LLM response. Tolerant of markdown fences,
    extra prose, and json-like-but-not-valid output.
    """
    if not response_text:
        return []
    s = response_text.strip()
    # Strip markdown code fences
    s = re.sub(r"^```(?:json)?\s*\n?", "", s, flags=re.MULTILINE)
    s = re.sub(r"\n?```\s*$", "", s, flags=re.MULTILINE)
    # Try direct JSON parse
    try:
        result = json.loads(s)
        if isinstance(result, list):
            return [str(x).strip() for x in result if x]
    except json.JSONDecodeError:
        pass
    # Fallback: regex-extract table names from quoted strings within brackets
    m = re.search(r"\[(.*?)\]", s, flags=re.DOTALL)
    if m:
        items = re.findall(r'"([^"]+)"', m.group(1))
        if items:
            return items
    # Fallback 2: line-by-line table-name guesses
    lines = [ln.strip().strip('-*"`,').strip() for ln in s.split("\n") if ln.strip()]
    return [ln for ln in lines if ln and re.match(r"^[a-zA-Z_][\w.]*$", ln)]


def _strip_schema_prefix(name: str) -> str:
    """`public.cq_baidu_aoi_2024` -> `cq_baidu_aoi_2024`."""
    if "." in name:
        return name.rsplit(".", 1)[-1]
    return name


def select_relevant_tables(
    question: str,
    schema: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    model: str = DEFAULT_MODEL,
    valid_table_names: set[str] | None = None,
) -> list[str]:
    """Select top-k relevant tables for a question via single LLM call.

    Args:
        question: The user's natural language query.
        schema: Full schema dump (e.g. CREATE TABLE statements).
        top_k: Maximum tables to return.
        model: LLM model id (default gemini-2.5-flash).
        valid_table_names: If provided, filter response against this set.
            Recommended: pass `set(_benchmark_tables())` to drop hallucinations.

    Returns:
        List of table names (schema prefix stripped), in LLM-ranked order.
        Empty on failure.
    """
    if not question or not schema:
        return []
    cache_key = _question_hash(question, schema)
    try:
        raw = _mapper_call_cached(cache_key, question, schema, top_k, model)
    except Exception as e:
        logger.warning(f"[SchemaMapper] LLM call failed: {e}")
        return []

    names = _parse_table_names(raw)
    names = [_strip_schema_prefix(n) for n in names]

    if valid_table_names is not None:
        names = [n for n in names if n in valid_table_names]

    # Dedup preserving order
    seen = set()
    deduped = []
    for n in names:
        if n not in seen:
            seen.add(n)
            deduped.append(n)
    return deduped[:top_k]


def schema_mapper_enabled() -> bool:
    """Feature flag. Off by default; enable via env for ablation runs."""
    return os.environ.get("NL2SQL_LLM_SCHEMA_MAPPER", "0") in ("1", "true", "True", "yes")


def schema_mapper_mode() -> str:
    """Mode: 'backfill' (only when substring fails) | 'replace' (skip substring) | 'merge'."""
    return os.environ.get("NL2SQL_LLM_SCHEMA_MAPPER_MODE", "backfill")
