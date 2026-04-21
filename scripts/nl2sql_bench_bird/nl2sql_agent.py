"""Focused NL2SQL evaluation agent for benchmark.

Builds a minimal LlmAgent that has ONLY:
  - DatabaseToolset (for query_database)
  - SemanticLayerToolset (for resolve_semantic_context)
  - ExplorationToolset (for describe_table)

This bypasses the multi-agent General Pipeline (intent router → processing →
viz → summary loop) which:
  - Has 22+ unrelated toolsets that dilute LLM attention
  - Is biased toward "exploration → analysis → visualization → report" not pure NL2SQL
  - Routes through summary-loop that often discards the SQL step

By keeping only the three NL2SQL-relevant toolsets, we measure the true
"NL → Semantic Layer → SQL" capability that the user explicitly cares about,
WITHOUT noise from product-level orchestration.

Note: This agent still uses the existing semantic layer + ContextEngine,
so the A/B comparison vs the pure-LLM baseline still validates the
semantic-layer increment.
"""
from __future__ import annotations

from google.adk.agents import LlmAgent

# Import these only when called — they pull in the world.
def build_nl2sql_agent():
    """Construct a focused NL2SQL agent for benchmark evaluation."""
    # Lazy imports to avoid heavy startup if module is loaded but not used
    from data_agent.toolsets import (
        DatabaseToolset, SemanticLayerToolset, ExplorationToolset,
    )

    instruction = """You are a PostgreSQL SQL expert. Your ONLY job is to answer the user's question by generating and executing a single SELECT query.

Workflow:
1. If you don't know the schema, call `describe_table` for the relevant table(s).
2. Optionally call `resolve_semantic_context` to disambiguate column names against the semantic layer.
3. Generate a SINGLE PostgreSQL SELECT query and execute it via `query_database`.
4. After `query_database` returns, output a brief one-line summary including the answer.

CRITICAL rules:
- You MUST call `query_database` exactly once with a complete SELECT query that fully answers the question.
- Do NOT generate exploratory queries like `SELECT * FROM t LIMIT 1` first — write the final SQL directly.
- Use bare table names (search_path is set per-question) OR fully-qualified `schema.table`.
- Use PostgreSQL syntax: CASE WHEN (not IIF), NULLIF, ::numeric, SUBSTRING (not SUBSTR cast tricks).
- Do not add LIMIT unless the question explicitly asks for top-K.
- Do not visualize, summarize, or transform — just produce the SQL answer.
"""

    return LlmAgent(
        name="NL2SQLEvalAgent",
        instruction=instruction,
        description="Focused NL2SQL evaluation agent for benchmark",
        model="gemini-2.5-flash",
        tools=[
            DatabaseToolset(tool_filter=[
                "query_database", "describe_table", "list_tables",
            ]),
            SemanticLayerToolset(tool_filter=[
                "resolve_semantic_context", "describe_table_semantic",
                "list_semantic_sources",
            ]),
            ExplorationToolset(tool_filter=[
                "describe_table", "list_tables",
            ]),
        ],
    )


_cached_agent = None


def get_nl2sql_agent():
    global _cached_agent
    if _cached_agent is None:
        _cached_agent = build_nl2sql_agent()
    return _cached_agent
