"""Executor tools for NL2SQL Phase 2: prepare grounding, execute with self-correction, auto-curate."""
from __future__ import annotations

import json
import re

from .nl2sql_grounding import build_nl2sql_context
from .sql_postprocessor import postprocess_sql
from .toolsets.nl2sql_tools import execute_safe_sql
from .user_context import (
    current_nl2sql_large_tables,
    current_nl2sql_question,
    current_nl2sql_schemas,
)

# Backward-compatible names used in tests / plan prose
_cached_schemas = current_nl2sql_schemas
_cached_large_tables = current_nl2sql_large_tables

MAX_RETRIES = 2


def _strip_fences(s: str) -> str:
    """Strip markdown code fences from LLM output."""
    s = (s or "").strip()
    m = re.match(r"^```(?:sql)?\s*(.*?)\s*```$", s, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else s


def _format_schema_for_retry(schemas: dict) -> str:
    """Format cached schemas into a compact block for the retry prompt."""
    lines = []
    for table_name, columns in schemas.items():
        col_strs = []
        for col in columns:
            name = col.get("column_name", "")
            needs_q = col.get("needs_quoting", False)
            ref = f'"{name}"' if needs_q else name
            pg_type = col.get("pg_type", "")
            col_strs.append(f"  {ref} {pg_type}")
        lines.append(f"-- {table_name}")
        lines.extend(col_strs)
    return "\n".join(lines) if lines else "(no schema available)"


def _retry_with_llm(
    question: str, failed_sql: str, error: str, schemas: dict
) -> str | None:
    """Ask LLM to fix the failed SQL based on error message.

    Uses Gemini 2.0 Flash for fast, cheap retry. Returns fixed SQL or None.
    """
    schema_block = _format_schema_for_retry(schemas)
    prompt = (
        "你是 PostgreSQL SQL 修复专家。上一次生成的 SQL 执行失败。\n\n"
        f"原始问题: {question}\n"
        f"失败的 SQL: {failed_sql}\n"
        f"错误信息: {error}\n\n"
        f"可用 Schema:\n{schema_block}\n\n"
        "请修复 SQL。只输出修复后的 SQL，不要解释。\n"
        "注意：大小写混合的列名必须双引号（如 \"DLMC\"、\"Floor\"）。"
    )
    try:
        from .llm_client import generate_text, strip_fences
        raw = generate_text(prompt, tier="fast", timeout_ms=20_000)
        fixed = strip_fences(raw)
        return fixed if fixed else None
    except Exception:
        return None


def _auto_curate(question: str, sql: str) -> None:
    """Auto-curate successful (question, SQL) pairs into reference_queries.

    Uses dedup (cosine > 0.92) built into ReferenceQueryStore.add().
    Infers domain_id from table names in the SQL for domain isolation.
    Non-fatal: silently ignores any errors.
    """
    if not question or not sql:
        return
    try:
        # Infer domain from table names in SQL
        import re
        domain_id = None
        table_match = re.findall(r'\bFROM\s+"?(\w+)"?', sql, re.IGNORECASE)
        if table_match:
            domain_id = table_match[0]

        from .reference_queries import ReferenceQueryStore
        store = ReferenceQueryStore()
        store.add(
            query_text=question,
            response_summary=sql,
            task_type="nl2sql",
            source="auto_curate",
            domain_id=domain_id,
        )
    except Exception:
        pass


def prepare_nl2sql_context(user_question: str) -> str:
    """Prepare semantic/schema grounding prompt for NL2SQL generation.

    Caches per-request schemas and large-table hints in ContextVars so the next
    tool call `execute_nl2sql()` can postprocess the generated SQL.
    """
    payload = build_nl2sql_context(user_question)

    schemas = {}
    large_tables = set()
    for table in payload.get("candidate_tables", []):
        name = table["table_name"]
        schemas[name] = table.get("columns", [])
        if int(table.get("row_count_hint", 0) or 0) >= 1_000_000:
            large_tables.add(name)

    current_nl2sql_question.set(user_question)
    current_nl2sql_schemas.set(schemas)
    current_nl2sql_large_tables.set(large_tables)

    return payload.get("grounding_prompt", "")


def execute_nl2sql(sql: str) -> str:
    """Postprocess, execute, and self-correct NL2SQL-generated SQL.

    Phase 2 enhancements:
    - On execution failure, retries up to MAX_RETRIES times with LLM-based SQL fix
    - On success, auto-curates (question, SQL) pair into reference_queries for few-shot
    """
    schemas = current_nl2sql_schemas.get()
    large_tables = current_nl2sql_large_tables.get()
    question = current_nl2sql_question.get()

    last_sql = sql

    for attempt in range(MAX_RETRIES + 1):
        pp_result = postprocess_sql(last_sql, schemas, large_tables)
        if pp_result.rejected:
            return f"安全拒绝: {pp_result.reject_reason}"

        exec_result = execute_safe_sql(pp_result.sql)

        try:
            parsed = json.loads(exec_result)
        except Exception:
            parsed = {}

        error = parsed.get("error")
        if error is None or parsed.get("status") == "ok":
            _auto_curate(question, pp_result.sql)
            return exec_result

        if attempt >= MAX_RETRIES:
            return exec_result

        fixed_sql = _retry_with_llm(question, pp_result.sql, str(error), schemas)
        if not fixed_sql:
            return exec_result

        last_sql = fixed_sql
