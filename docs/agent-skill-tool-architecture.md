# Agent · Skill · Tool 架构关系

> GIS Data Agent 多 Agent 架构中三个核心概念的定义、层次关系和协作方式。

---

## 层次结构

```
Pipeline (SequentialAgent / ParallelAgent / LoopAgent)
│
├── Agent (LlmAgent) ─── 大脑：推理、决策、调用工具
│     │
│     ├── Instruction ─── 来源：Prompt YAML / ADK Skill / Custom Skill
│     │
│     ├── Tools ─── 双手：执行具体操作
│     │     ├── ExplorationToolset ──── [describe_geodataframe, check_topology, ...]
│     │     ├── DatabaseToolset ─────── [query_database, list_tables, ...]
│     │     ├── VisualizationToolset ── [generate_choropleth_map, ...]
│     │     ├── UserToolset ─────────── [用户自定义的 http_call/sql_query/...]
│     │     └── SkillToolset ────────── [内置 ADK Skill 作为可调用工具]
│     │
│     └── output_key ─── 产出传递给下游 Agent
│
├── Agent B ...
└── Agent C ...
```

---

## 概念定义

| 概念 | 本质 | 粒度 | 谁定义 | 运行时表现 |
|------|------|------|--------|-----------|
| **Tool** | 一个 Python 函数 | 原子操作 | 开发者 / 用户 | `FunctionTool(fn)` — LLM 看到函数签名和描述，决定是否调用 |
| **Skill** | 一套领域专家知识 | 场景模板 | 开发者 / 用户 | 提供 instruction（告诉 Agent 怎么思考）或作为 AgentTool 被其他 Agent 调用 |
| **Agent** | 一个 LLM 推理实体 | 决策单元 | 系统 / 用户 | `LlmAgent` — 接收指令，选择并调用 Tools，产生输出 |

---

## Tool — 原子操作能力

Tool 是系统中最小的功能单元。每个 Tool 是一个带类型标注和 docstring 的 Python 函数，通过 ADK 的 `FunctionTool` 包装后暴露给 LLM。

```python
# 定义一个 Tool
def describe_geodataframe(file_path: str) -> dict:
    """数据探查画像：对空间数据进行全面质量预检。

    Args:
        file_path: 空间数据文件路径 (.shp / .geojson / .gpkg)

    Returns:
        包含字段信息、几何类型、坐标系、统计摘要的画像字典。
    """
    # 实现...
```

**ADK 自动完成的工作**：
1. 解析函数签名 → 生成参数 JSON Schema
2. 解析 docstring → 提取工具描述和参数说明
3. LLM 在推理时看到工具列表，自主决定调用哪个

**Tool 的组织方式** — BaseToolset：

Tool 不是散落的函数，而是按领域分组到 `BaseToolset` 子类中：

```python
class ExplorationToolset(BaseToolset):
    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
```

系统共有 **23 个 Toolset**（130+ 工具函数），包括用户自定义的 `UserToolset`。

**用户扩展 Tool 的方式**：

通过声明式模板创建自定义工具（无需写代码），系统自动包装为 `FunctionTool`：

| 模板类型 | 用途 |
|---------|------|
| `http_call` | 调用外部 REST API |
| `sql_query` | 参数化数据库查询 |
| `file_transform` | 文件处理管道（filter/reproject/buffer/dissolve） |
| `chain` | 串联多个自定义工具 |

---

## Skill — 领域专家知识

Skill 定义了"Agent 应该如何思考和行动"。它有**双重身份**：

### 身份一：作为 Instruction

Skill 的核心是一段结构化指令，注入到 Agent 的系统提示中：

```yaml
# data_agent/skills/data-profiling/SKILL.md
---
name: data-profiling
description: "空间数据画像与质量评估技能"
metadata:
  domain: governance
  intent_triggers: "profile, 画像, 数据质量"
---

# 空间数据画像与质量评估技能

## 职责
数据画像是所有空间分析的第一步...

## 画像分析维度
### 基础结构维度
| 检查项 | 内容 | 关注点 |
|--------|------|--------|
| 要素数量 | 总记录数 | 空记录占比 |
| 字段清单 | 字段名、类型 | 类型是否合理 |
...
```

当 Agent 收到匹配 `intent_triggers` 的请求时，这段指令会被加载并注入到 Agent 的 prompt 中，让 Agent 具备该领域的专业行为。

### 身份二：作为 Tool（可被调用的 Agent）

通过 `AgentTool` 或 `SkillToolset`，一个 Skill/Agent 可以被另一个 Agent 当作工具调用：

```python
# knowledge_agent 作为工具注入 Planner
knowledge_tool = AgentTool(agent=knowledge_agent, skip_summarization=False)

planner = LlmAgent(
    name="Planner",
    tools=[knowledge_tool, ...],  # Planner 可以"调用"knowledge_agent
)
```

### Skill 的三种来源

| 来源 | 数量 | 存储 | 加载方式 |
|------|------|------|---------|
| **内置 ADK Skill** | 18 个 | `skills/` 目录下的 SKILL.md | `load_skill_from_dir()` → `SkillToolset` |
| **Custom Skill** | 用户定义 | PostgreSQL `agent_custom_skills` 表 | `build_custom_agent()` → `LlmAgent` |
| **Prompt YAML** | 3 个 | `prompts/` 目录下的 YAML | `get_prompt()` 直接注入 Agent instruction |

### 三级增量加载

| 级别 | 加载内容 | 时机 |
|------|---------|------|
| L1 | metadata (name, description, domain) | 应用启动 |
| L2 | instructions (完整 Prompt) | 路由匹配时 |
| L3 | resources (附加文件) | 执行时 |

---

## Agent — 推理与决策单元

Agent 是一个绑定了模型、指令和工具的 LLM 推理实体。它接收输入，自主选择工具，产生输出。

```python
data_exploration_agent = LlmAgent(
    name="DataExploration",
    model=get_model_for_tier("fast"),           # 模型：gemini-2.0-flash
    instruction=prompts["exploration_instruction"],  # 指令：来自 Skill 或 YAML
    tools=[                                     # 工具：决定 Agent 的能力边界
        ExplorationToolset(tool_filter=_AUDIT_TOOLS),
        DatabaseToolset(tool_filter=_DB_READ),
    ],
    output_key="data_profile",                  # 产出：存入 session state
)
```

### Agent 的编排方式

ADK 提供三种编排容器：

| 容器 | 行为 | 用途 |
|------|------|------|
| `SequentialAgent` | 按顺序执行子 Agent | 主管线（Optimization/Governance/General） |
| `ParallelAgent` | 并发执行子 Agent | 数据摄入（Exploration ‖ SemanticPreFetch） |
| `LoopAgent` | Generator → Critic 循环 | 质量保证（Analysis → QualityChecker，最多 3 轮） |

### Agent 间状态传递

```
Agent A (output_key="data_profile")
    ↓ session.state["data_profile"] = "数据包含 5000 条记录..."
Agent B (读取上游状态，作为自己的输入上下文)
    ↓ session.state["processed_data"] = "处理后数据路径: ..."
Agent C ...
```

### 模型分层策略

不同角色的 Agent 使用不同级别的模型，平衡成本与能力：

```
gemini-2.0-flash  (fast)     ← 路由器、质量检查器、语义预取
gemini-2.5-flash  (standard) ← 主 Agent（默认）
gemini-2.5-pro    (premium)  ← Reporter（复杂综合推理）
```

---

## 实际执行流程

以用户输入 "分析福禄镇的耕地破碎化程度" 为例：

```
用户消息: "分析福禄镇的耕地破碎化程度"
    │
    ▼
语义路由 (intent_router.py, Gemini Flash) → OPTIMIZATION
    │
    ▼
Optimization Pipeline (SequentialAgent)
    │
    ├── 1. DataExploration Agent
    │     instruction: "你是数据质量审计专家..."
    │     tools: [ExplorationToolset, DatabaseToolset]
    │     → 调用 describe_geodataframe() → 产出数据画像
    │     output_key: "data_profile"
    │
    ├── 2. DataProcessing Agent
    │     instruction: "你是空间数据处理专家..."
    │     tools: [GeoProcessingToolset, FusionToolset, UserToolset]
    │     → 调用 engineer_spatial_features() → 产出处理后数据
    │     output_key: "processed_data"
    │
    ├── 3. AnalysisQualityLoop (LoopAgent, max 3 轮)
    │     ├── Analysis Agent
    │     │     tools: [AnalysisToolset, SpatialStatisticsToolset]
    │     │     → 调用 drl_model() → 产出优化方案
    │     └── QualityChecker Agent
    │           → 验证结果完整性，不通过则重试
    │     output_key: "analysis_report"
    │
    ├── 4. Visualization Agent
    │     tools: [VisualizationToolset]
    │     → 调用 generate_choropleth_map() → 产出交互式地图
    │
    └── 5. Summary Agent
          tools: [FileToolset]
          → 生成决策报告
          output_key: "final_summary"
```

---

## 用户自助扩展闭环

用户可以在三个层面扩展系统，形成完整闭环：

```
                    ┌──────────────────────────────────┐
                    │     扩展 Tool 层                  │
                    │  在"能力"Tab 创建声明式工具模板     │
                    │  (http_call / sql_query / chain)  │
                    └──────────┬───────────────────────┘
                               │ 工具注入
                               ▼
                    ┌──────────────────────────────────┐
                    │     扩展 Skill 层                 │
                    │  在"能力"Tab 创建自定义 Agent       │
                    │  (指令 + 工具集选择 + 触发词)       │
                    │  选择 UserToolset 使用自定义工具    │
                    └──────────┬───────────────────────┘
                               │ Agent 编排
                               ▼
                    ┌──────────────────────────────────┐
                    │     扩展 Pipeline 层              │
                    │  在"工作流"Tab 可视化编排           │
                    │  拖入 Skill Agent 节点组成 DAG     │
                    │  定义依赖关系和参数传递             │
                    └──────────────────────────────────┘
```

**Tool → Skill → Pipeline**：用户定义 Tool → 选入 Skill 的工具集 → 编排进 Pipeline → DAG 引擎自动执行。

---

*本文档基于 GIS Data Agent v12.0 (ADK v1.27.2) 架构编写。*
