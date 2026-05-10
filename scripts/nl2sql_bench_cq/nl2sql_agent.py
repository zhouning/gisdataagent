"""Focused NL2SQL evaluation agent for GIS benchmark.

Fully leverages the semantic layer system:
  - ContextEngine (6 providers: semantic_layer, reference_queries, metrics, KB, etc.)
  - resolve_semantic_context → sql_filters, hierarchy_matches, equivalences
  - describe_table_semantic (annotated schema with domain/aliases/unit)
  - fetch_nl2sql_few_shots (embedding-based similar query examples)
  - query_database (execution with security enforcement)
"""
from __future__ import annotations

import os

from google.adk.agents import LlmAgent


def build_nl2sql_agent():
    """Construct a focused NL2SQL agent that fully utilizes the semantic layer.

    System instruction is loaded from `data_agent/prompts_nl2sql/<family>/
    system_instruction.md` via the namespace loader, where <family> is
    determined from the constructed model object (gemini / deepseek / qwen /
    litellm / lm_studio). Unknown families fall back to gemini's instruction
    so the agent always builds.
    """
    from data_agent.toolsets import (
        DatabaseToolset, SemanticLayerToolset, ExplorationToolset,
    )
    from data_agent.model_gateway import create_model, family_of
    from data_agent import prompts_nl2sql

    model_name = os.environ.get("NL2SQL_AGENT_MODEL", "gemini-2.5-flash")
    # Route via model_gateway so non-Gemini backends (DeepSeek, LM Studio,
    # other LiteLLM providers) get wrapped in google.adk.models.lite_llm.LiteLlm
    # instead of being passed as a bare string (which ADK would route to Gemini
    # regardless of the name).
    model_obj = create_model(model_name)
    family = family_of(model_obj)
    # Research override: NL2SQL_PROMPT_FAMILY_OVERRIDE forces a different
    # prompt namespace than the model's natural family. Used only by the
    # cross-family portability experiments (e.g. running DS R1-R7 prompt on a
    # Gemini model). DO NOT set this in production.
    prompt_family = os.environ.get("NL2SQL_PROMPT_FAMILY_OVERRIDE") or family
    instruction = prompts_nl2sql.load_system_instruction(prompt_family)

    # Propagate prompt_family (NOT the underlying model family) to downstream
    # callers via env var so build_nl2sql_context() and run_cq_eval.run_one()
    # pick the matching grounding template / intent path.
    os.environ["NL2SQL_AGENT_FAMILY"] = prompt_family

    # No explicit generate_content_config: each provider uses its production
    # default (Gemini: server-side default; DeepSeek via LiteLlm: OpenAI-spec
    # default temperature=1.0). Cross-family comparisons therefore evaluate
    # each model family at its deployed configuration rather than a forced
    # artificial temperature pin. Stochastic variance is controlled at the
    # experiment level via N=3 sampling per cell (see v5 Spatial protocol).

    return LlmAgent(
        name="NL2SQLEvalAgent",
        instruction=instruction,
        description="Focused NL2SQL evaluation agent with full semantic layer",
        model=model_obj,
        tools=[
            DatabaseToolset(tool_filter=[
                "query_database", "describe_table", "list_tables",
            ]),
            SemanticLayerToolset(tool_filter=[
                "resolve_semantic_context", "describe_table_semantic",
                "list_semantic_sources", "browse_hierarchy",
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
