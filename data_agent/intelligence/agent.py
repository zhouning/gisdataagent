"""
Agent 编排层 — 治理场景 Agent 定义

复用原型验证过的 ADK 模式：
  - LlmAgent: 单个专家 Agent（有工具、有 Prompt、有 output_key）
  - SequentialAgent: 顺序编排（感知→对照→推荐→执行→报告）
  - LoopAgent: 质量闭环（执行→审核→重试）
  - AgentTool: 子 Agent 可被路由 Agent 按需调用

Prompt 从 prompts/governance_v2.yaml 加载（复用原型的 get_prompt 机制）。
"""

from __future__ import annotations

import logging
import os

from google.adk.agents import LlmAgent, SequentialAgent, LoopAgent
from google.adk.tools import AgentTool

from data_agent.prompts import get_prompt
from data_agent.intelligence.tools import (
    analyze_fields_tool,
    check_compliance_tool,
    advise_model_tool,
    execute_governance_tool,
    generate_report_tool,
    query_knowledge_tool,
)

logger = logging.getLogger(__name__)

# --- 模型配置（复用原型的环境变量模式）---
MODEL_STANDARD = os.environ.get("MODEL_STANDARD", "gemini-2.5-flash")
MODEL_FAST = os.environ.get("MODEL_FAST", "gemini-2.0-flash")


# ---------------------------------------------------------------------------
# 专家 Agent 定义
# ---------------------------------------------------------------------------

# 1. 数据感知 Agent
data_profiling_agent = LlmAgent(
    name="DataProfiling",
    instruction=get_prompt("governance_v2", "data_profiling_instruction"),
    description="数据感知专家：识别字段含义、生成数据画像、推荐标准表",
    model=MODEL_STANDARD,
    output_key="data_profile",
    tools=[analyze_fields_tool],
)

# 2. 标准对照 Agent
compliance_agent = LlmAgent(
    name="ComplianceCheck",
    instruction=get_prompt("governance_v2", "compliance_instruction"),
    description="标准对照专家：将数据现状与标准规则对照，生成差距报告",
    model=MODEL_STANDARD,
    output_key="gap_report",
    tools=[check_compliance_tool],
)

# 3. 模型推荐 Agent
model_advisor_agent = LlmAgent(
    name="ModelAdvisor",
    instruction=get_prompt("governance_v2", "model_advisor_instruction"),
    description="模型推荐专家：对比数据现状与目标模型，推荐调整方案",
    model=MODEL_STANDARD,
    output_key="adjustment_advice",
    tools=[advise_model_tool],
)

# 4. 治理执行 Agent
governance_executor_agent = LlmAgent(
    name="GovernanceExecutor",
    instruction=get_prompt("governance_v2", "executor_instruction"),
    description="治理执行专家：编排治理步骤，调用底座执行",
    model=MODEL_STANDARD,
    output_key="governance_result",
    tools=[execute_governance_tool],
)

# 5. 质量审核 Agent（LoopAgent 的 Critic 角色，复用原型的 Generator-Critic 闭环）
quality_reviewer_agent = LlmAgent(
    name="QualityReviewer",
    instruction=get_prompt("governance_v2", "reviewer_instruction"),
    description="质量审核员：检查治理结果是否达标，不达标则指导修正",
    model=MODEL_STANDARD,
    output_key="review_result",
)

# 6. 治理质量闭环（LoopAgent：执行→审核→重试，最多 3 轮）
governance_quality_loop = LoopAgent(
    name="GovernanceQualityLoop",
    description="治理质量闭环：执行→审核，不达标则重试",
    sub_agents=[governance_executor_agent, quality_reviewer_agent],
    max_iterations=3,
)

# 7. 报告生成 Agent
report_agent = LlmAgent(
    name="ReportGenerator",
    instruction=get_prompt("governance_v2", "report_instruction"),
    description="报告生成专家：汇总治理成果，生成可验收的 Word 报告",
    model=MODEL_STANDARD,
    output_key="governance_report",
    tools=[generate_report_tool],
)


# ---------------------------------------------------------------------------
# 管线编排
# ---------------------------------------------------------------------------

# 完整治理管线（SequentialAgent：感知→对照→推荐→执行闭环→报告）
governance_pipeline = SequentialAgent(
    name="GovernancePipeline",
    description="数据治理全流程：感知→对照→推荐→执行→审核→报告",
    sub_agents=[
        data_profiling_agent,
        compliance_agent,
        model_advisor_agent,
        governance_quality_loop,
        report_agent,
    ],
)


# ---------------------------------------------------------------------------
# 路由 Agent（顶层入口）
# ---------------------------------------------------------------------------

# 路由 Agent 可以：
# 1. 走完整管线（用户说"帮我治理这份数据"）
# 2. 按需调用子 Agent（用户说"帮我看看这份数据的字段"→只调 DataProfiling）
# 3. 查询知识库（用户说"DLBM 是什么字段"→调 query_knowledge）

# 将子 Agent 包装为 AgentTool（复用原型的 AgentTool 模式）
_profiling_tool = AgentTool(agent=data_profiling_agent, skip_summarization=False)
_compliance_tool = AgentTool(agent=compliance_agent, skip_summarization=False)
_advisor_tool = AgentTool(agent=model_advisor_agent, skip_summarization=False)
_report_tool = AgentTool(agent=report_agent, skip_summarization=False)

router_agent = LlmAgent(
    name="GovernanceRouter",
    instruction=get_prompt("governance_v2", "router_instruction"),
    description="数据治理智能助手：理解用户意图，分发到对应专家或走完整流程",
    model=MODEL_FAST,  # 路由用快速模型
    tools=[
        # 按需调用子 Agent
        _profiling_tool,
        _compliance_tool,
        _advisor_tool,
        _report_tool,
        # 直接可用的工具
        analyze_fields_tool,
        check_compliance_tool,
        advise_model_tool,
        generate_report_tool,
        query_knowledge_tool,
    ],
    sub_agents=[governance_pipeline],  # 也可以走完整管线
)


# ---------------------------------------------------------------------------
# 便捷入口
# ---------------------------------------------------------------------------

def get_root_agent() -> LlmAgent:
    """获取根 Agent（供 Chainlit app.py 使用）。"""
    return router_agent


def get_pipeline_agent() -> SequentialAgent:
    """获取完整治理管线 Agent。"""
    return governance_pipeline
