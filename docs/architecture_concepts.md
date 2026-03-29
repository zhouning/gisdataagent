# Data Agent 核心概念关系说明

## Pipeline / Workflow / Agent / Skill / Tool 概念层次

```
Tool (工具函数)
  └── Toolset (工具集)
        └── Agent (智能体)
              └── Pipeline (管道，固定编排)
                    └── Workflow (工作流，用户可配置编排)

Skill (技能) = 用户自定义的 Agent
  └── 也可作为 Workflow 的节点
```

## 各概念定义

| 概念 | 定义 | 创建者 | 存储位置 | 示例 |
|------|------|--------|----------|------|
| **Tool** | 一个可调用的原子函数 | 开发者 | Python 代码（toolsets/） | `buffer_analysis()`, `check_topology()` |
| **Toolset** | 一组相关 Tool 的集合（BaseToolset 子类） | 开发者 | Python 代码（toolsets/） | GovernanceToolset (18 个工具), AnalysisToolset |
| **Agent** | 一个 LLM 智能体，挂载若干 Toolset，有 instruction 指令 | 开发者 | agent.py | DataAnalysis, GovProcessing, GeneralProcessing |
| **Pipeline** | 多个 Agent 按固定结构编排的链路（Sequential/Parallel/Loop） | 开发者 | agent.py | Optimization Pipeline, Governance Pipeline |
| **Skill** | 用户自定义的 Agent（可选 Toolset + 自定义 prompt + 触发词） | 用户 | 数据库（custom_skills 表） | "地形分析专家", "水资源评估" |
| **Workflow** | 用户编排的 DAG 任务流，节点可调用 Pipeline 或 Skill | 用户 | 数据库（workflows 表） | 标准质检流程 (5步), 完整质检流程 (7步) |

## 调用关系图

```
用户输入
  │
  ▼
Intent Router (Gemini Flash 分类)
  │
  ├──→ OPTIMIZATION ──→ Optimization Pipeline (SequentialAgent)
  │                        ├── DataEngineering (Sequential)
  │                        │     ├── ParallelDataIngestion (Parallel)
  │                        │     │     ├── DataExploration [ExplorationToolset, DatabaseToolset, DataLakeToolset]
  │                        │     │     └── SemanticPreFetch [SemanticLayerToolset, DataLakeToolset]
  │                        │     └── DataProcessing [ExplorationToolset, GeoProcessingToolset, ...]
  │                        ├── AnalysisQualityLoop (Loop)
  │                        │     ├── DataAnalysis [AnalysisToolset, RemoteSensingToolset, CausalInferenceToolset, DreamerToolset, ...]
  │                        │     └── QualityChecker
  │                        ├── DataVisualization [VisualizationToolset]
  │                        └── DataSummary
  │
  ├──→ GOVERNANCE ──→ Governance Pipeline (SequentialAgent)
  │                      ├── GovExploration [ExplorationToolset, DatabaseToolset, GovernanceToolset]
  │                      ├── GovProcessing [GeoProcessingToolset, FusionToolset, ...]
  │                      ├── GovernanceViz [VisualizationToolset, ChartToolset]
  │                      └── GovernanceReportLoop (Loop)
  │
  ├──→ GENERAL ──→ General Pipeline (SequentialAgent)
  │                   ├── GeneralProcessing [22 个 Toolset — 全能力]
  │                   ├── GeneralViz [VisualizationToolset, ChartToolset]
  │                   └── GeneralSummaryLoop (Loop)
  │
  ├──→ WORKFLOW ──→ Workflow Engine (DAG 执行引擎)
  │                   ├── 从模板创建 → 选择文件 → 异步执行
  │                   ├── 每步可调用 Pipeline 或 Skill
  │                   └── SLA 超时控制 + 进度回调
  │
  └──→ CUSTOM ──→ 用户自定义 Skill (动态 LlmAgent)
```

## Pipeline vs Workflow 的区别

| 维度 | Pipeline | Workflow |
|------|----------|----------|
| **定义方式** | 代码硬编码 (agent.py) | 用户通过 UI/API 配置 |
| **编排结构** | 固定的 Agent 链路 | 可视化 DAG，节点可增删 |
| **执行触发** | Intent Router 自动路由 | 用户手动执行或自然语言触发 |
| **节点类型** | ADK Agent (LlmAgent, SequentialAgent, ...) | Pipeline 调用 或 Skill 调用 |
| **适用场景** | 通用分析、治理、优化 | 定制化流程（质检、审批等） |
| **SLA 控制** | 无 | 有（总时限 + 步骤超时 + 重试） |
| **可编辑** | 否（需改代码） | 是（WorkflowEditor 可视化编辑） |

## DRL 耕地空间布局优化工具的位置

```
Optimization Pipeline
  └── AnalysisQualityLoop (LoopAgent)
        └── DataAnalysis (LlmAgent)
              ├── AnalysisToolset ← 包含 drl_optimize(), calculate_ffi()
              └── DreamerToolset ← 包含 dreamer_optimize() (DRL + World Model)
```

- `drl_optimize`: 基于 MaskablePPO 的耕地-林地交换优化，最小化碎片化指数
- `calculate_ffi`: 计算 Forest Fragmentation Index
- `dreamer_optimize`: Dreamer-style look-ahead 优化，结合 World Model 进行多步预测

## 当前系统规模

- **24** 个 Agent (13 LlmAgent + 5 SequentialAgent + 3 LoopAgent + 2 ParallelAgent + 1 unknown)
- **30** 个 Toolset
- **3** 个固定 Pipeline
- **7** 个预置工作流模板 (3 通用 + 4 成果类型专属)
- **18** 个内置 Skill
- **用户可创建**: 自定义 Skill + 自定义工作流 (无上限)
