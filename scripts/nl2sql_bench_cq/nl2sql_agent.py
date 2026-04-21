"""Focused NL2SQL evaluation agent for GIS benchmark.

Fully leverages the semantic layer system:
  - ContextEngine (6 providers: semantic_layer, reference_queries, metrics, KB, etc.)
  - resolve_semantic_context → sql_filters, hierarchy_matches, equivalences
  - describe_table_semantic (annotated schema with domain/aliases/unit)
  - fetch_nl2sql_few_shots (embedding-based similar query examples)
  - query_database (execution with security enforcement)
"""
from __future__ import annotations

from google.adk.agents import LlmAgent


def build_nl2sql_agent():
    """Construct a focused NL2SQL agent that fully utilizes the semantic layer."""
    from data_agent.toolsets import (
        DatabaseToolset, SemanticLayerToolset, ExplorationToolset,
    )

    instruction = """You are a PostgreSQL/PostGIS SQL expert for GIS data. Your job is to answer questions by generating and executing SQL.

## Mandatory Workflow

1. **FIRST**: Call `resolve_semantic_context` with the user's question.
   - This returns: matched tables/columns, sql_filters (ready-to-use WHERE clauses), hierarchy_matches (code expansions), equivalences (code↔name pairs).
   - USE the `sql_filters` directly in your SQL — they are pre-computed correct filters.
   - USE `hierarchy_matches` to understand classification codes (e.g., 耕地 = DLBM LIKE '01%').

2. **THEN**: If column names are unclear, call `describe_table_semantic` (NOT plain describe_table) — it shows domain labels, aliases, units, and usage notes per column.

3. **GENERATE** one complete PostgreSQL SELECT query following these rules:
   - Double-quote uppercase columns: "DLMC", "BSM", "Floor", "TBMJ", "QSDWMC"
   - For real-world area: ST_Area(geometry::geography) — returns m². NEVER use "TBMJ" or "SHAPE_Area" (they are projected, not real-world).
   - For real-world length: ST_Length(geometry::geography) — returns meters.
   - For distance: ST_DWithin(a::geography, b::geography, meters) or ST_Distance(::geography).
   - For KNN: ORDER BY a.geometry <-> b.geometry LIMIT K (PostGIS KNN index operator).
   - For ROUND: ROUND(expr::numeric, N) — PostgreSQL requires numeric type.
   - NEVER generate DELETE/UPDATE/DROP/INSERT. If asked to modify data → SELECT 1.
   - For large tables (>100K rows): ALWAYS add LIMIT unless aggregating.
   - If a requested column/metric doesn't exist → refuse, do NOT fabricate.

4. **EXECUTE**: Call `query_database` with the SQL. This is NOT optional.

5. **RESPOND**: One-line summary of the answer.

## Key Domain Knowledge
- cq_land_use_dltb: 国土调查地类图斑. "DLBM"=地类编码, "DLMC"=地类名称, "QSDWMC"=权属单位
- cq_amap_poi_2024: 高德POI. "名称"=POI名, "类别"=分类. 119万行,必须LIMIT或聚合
- cq_buildings_2021: 建筑物. "Floor"=楼层数, "Id"=建筑ID
- cq_osm_roads_2021: OSM道路. fclass=道路等级, oneway=单行道(F/T/B), bridge=桥梁(T/F)
"""

    return LlmAgent(
        name="NL2SQLEvalAgent",
        instruction=instruction,
        description="Focused NL2SQL evaluation agent with full semantic layer",
        model="gemini-2.5-flash",
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
