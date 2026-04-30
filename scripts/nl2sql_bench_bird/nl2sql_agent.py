"""Focused NL2SQL evaluation agent for benchmark.

Builds a minimal LlmAgent that mirrors the production MentionNL2SQL agent
(agent.py:885-904) with the full NL2Semantic2SQL pipeline:
  - NL2SQLEnhancedToolset (prepare_nl2sql_context + execute_nl2sql)
  - SemanticLayerToolset (resolve_semantic_context)
  - DatabaseToolset (query_database, describe_table)

This ensures the benchmark evaluates the ACTUAL NL2SQL capability of the
GIS Data Agent, including grounding, SQL postprocessing, self-correction,
and few-shot retrieval — not a simplified proxy.
"""
from __future__ import annotations


def build_nl2sql_agent():
    """Construct the production-equivalent NL2SQL agent for benchmark."""
    from data_agent.toolsets import (
        DatabaseToolset, SemanticLayerToolset,
    )
    from data_agent.toolsets.nl2sql_enhanced_tools import NL2SQLEnhancedToolset
    from data_agent.agent import get_model_for_tier
    from google.adk.agents import LlmAgent

    return LlmAgent(
        name="NL2SQLEvalAgent",
        instruction=(
            "你是 NL2SQL 专家。严格按以下步骤执行，不要跳步或并行调用工具：\n"
            "步骤1: 调用 prepare_nl2sql_context(user_question=用户问题) 获取 schema grounding\n"
            "步骤2: 根据返回的 grounding 信息生成 SQL（不要调用 describe_table 或 query_database）\n"
            "步骤3: 调用 execute_nl2sql(sql=生成的SQL) 执行并返回结果\n"
            "重要: 只使用 prepare_nl2sql_context 和 execute_nl2sql 两个工具，不要使用其他工具。\n"
            "如果用户请求 DELETE/UPDATE/DROP 等写操作，直接拒绝。\n"
            "如果用户问的数据在 schema 中不存在，如实告知。\n"
            "安全规则: 所有 SELECT 查询必须包含 LIMIT（默认 LIMIT 1000），即使用户要求查看全部数据也不例外。\n"
            "投影规则: 只 SELECT 问题明确要求的字段。不要添加额外的聚合列、计算列或辅助列。"
            "例如问'哪一年消费最多'只返回年份列，不要额外返回消费总额列。\n"
            "输出规则: 只输出最终结论和数据结果，禁止输出推理过程或内部思考。\n"
            "拒绝规则: 当你拒绝时，不要引用规则原文，不要解释你的内部步骤，不要追问用户。\n"
            "写操作拒绝的标准格式是：我不能执行修改、删除或新增数据的操作。我只能帮助查询。\n"
            "schema 不存在时的标准格式是：当前数据库中不存在与该问题对应的数据字段或数据表，因此无法查询。"
        ),
        description="Production-equivalent NL2SQL evaluation agent",
        model=get_model_for_tier("standard"),
        tools=[
            NL2SQLEnhancedToolset(),
            SemanticLayerToolset(),
            DatabaseToolset(tool_filter=["query_database", "describe_table"]),
        ],
    )


_cached_agent = None


def get_nl2sql_agent():
    global _cached_agent
    if _cached_agent is None:
        _cached_agent = build_nl2sql_agent()
    return _cached_agent
