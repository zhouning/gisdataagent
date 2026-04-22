"""Executor tools for NL2SQL Phase 1: prepare grounding and execute corrected SQL."""
from __future__ import annotations

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
    """Postprocess and execute NL2SQL-generated SQL.

    Reads the cached schema grounding from ContextVars, applies SQL post-
    processing (AST safety check, identifier quoting, LIMIT injection), and then
    executes via the existing safe executor.
    """
    schemas = current_nl2sql_schemas.get()
    large_tables = current_nl2sql_large_tables.get()

    result = postprocess_sql(sql, schemas, large_tables)
    if result.rejected:
        return f"安全拒绝: {result.reject_reason}"
    return execute_safe_sql(result.sql)
