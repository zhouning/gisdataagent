"""DIN-SQL 4-stage runner adapted for PostgreSQL.

Stages: schema_linking -> classification -> generation -> self_correction
Uses Gemini 2.5 Flash for all stages.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from .prompts import (
    SCHEMA_LINKING_PROMPT,
    CLASSIFICATION_PROMPT,
    DIFFICULTY_TO_PROMPT,
    SELF_CORRECTION_PROMPT,
)

MODEL = os.environ.get("DINSQL_MODEL", "gemini-2.5-flash")
_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client()
    return _client


def _call_llm(prompt: str, temperature: float = 0.0) -> str:
    """Call LLM and return text response."""
    from google.genai import types
    client = _get_client()
    resp = client.models.generate_content(
        model=MODEL,
        contents=[prompt],
        config=types.GenerateContentConfig(
            temperature=temperature,
            http_options=types.HttpOptions(timeout=60_000),
        ),
    )
    return (resp.text or "").strip()


def _strip_fences(s: str) -> str:
    """Strip markdown code fences."""
    s = (s or "").strip()
    m = re.match(r"^```(?:sql)?\s*(.*?)\s*```$", s, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else s


def schema_linking(schema: str, question: str, evidence: str = "") -> str:
    """Stage 1: Identify relevant tables and columns."""
    prompt = SCHEMA_LINKING_PROMPT.format(
        schema=schema, question=question, evidence=evidence
    )
    return _call_llm(prompt)


def classify_difficulty(question: str, evidence: str, schema_links: str) -> str:
    """Stage 2: Classify query difficulty."""
    prompt = CLASSIFICATION_PROMPT.format(
        question=question, evidence=evidence, schema_links=schema_links
    )
    result = _call_llm(prompt).upper().strip()
    # Extract just the label
    for label in ("HARD", "MEDIUM", "EASY"):
        if label in result:
            return label
    return "MEDIUM"  # default fallback


def generate_sql(schema: str, question: str, evidence: str,
                 schema_links: str, difficulty: str) -> str:
    """Stage 3: Generate SQL based on difficulty."""
    template = DIFFICULTY_TO_PROMPT.get(difficulty, DIFFICULTY_TO_PROMPT["MEDIUM"])
    prompt = template.format(
        schema=schema, question=question,
        evidence=evidence, schema_links=schema_links
    )
    raw = _call_llm(prompt)
    return _strip_fences(raw)


def self_correct(schema: str, question: str, failed_sql: str, error: str) -> str:
    """Stage 4: Fix failed SQL."""
    prompt = SELF_CORRECTION_PROMPT.format(
        schema=schema, question=question,
        failed_sql=failed_sql, error=error
    )
    raw = _call_llm(prompt)
    return _strip_fences(raw)


def predict(schema: str, question: str, evidence: str = "",
            execute_fn=None, max_retries: int = 1) -> dict:
    """Run the full DIN-SQL pipeline.

    Args:
        schema: Database schema text (CREATE TABLE statements)
        question: Natural language question
        evidence: Optional evidence/hint text
        execute_fn: Optional callable(sql) -> dict with 'status' and 'error' keys.
                    If provided, enables self-correction on execution failure.
        max_retries: Max self-correction attempts

    Returns:
        dict with keys: sql, difficulty, schema_links, tokens (approximate), stages_run
    """
    # Stage 1: Schema linking
    links = schema_linking(schema, question, evidence)

    # Stage 2: Classification
    difficulty = classify_difficulty(question, evidence, links)

    # Stage 3: Generation
    sql = generate_sql(schema, question, evidence, links, difficulty)

    stages_run = 3

    # Stage 4: Self-correction (if execute_fn provided)
    if execute_fn and sql:
        for _ in range(max_retries):
            result = execute_fn(sql)
            if result.get("status") == "ok" or not result.get("error"):
                break
            corrected = self_correct(schema, question, sql, str(result["error"]))
            if corrected and corrected != sql:
                sql = corrected
                stages_run += 1
            else:
                break

    return {
        "sql": sql,
        "difficulty": difficulty,
        "schema_links": links,
        "tokens": 0,  # approximate; caller can track via API usage
        "stages_run": stages_run,
    }
