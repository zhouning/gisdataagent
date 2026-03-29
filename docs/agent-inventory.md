# Data Agent 智能体清单

> 系统中所有 Agent 的完整清单、层级关系和职责说明。

---

## 智能体总数

| 类别 | 数量 | 说明 |
|------|------|------|
| **LlmAgent**（独立推理实体） | 22 | 具有 LLM 推理能力的 Agent |
| **SequentialAgent**（顺序编排） | 6 | 串行执行子 Agent |
| **ParallelAgent**（并行编排） | 3 | 并发执行子 Agent |
| **LoopAgent**（循环编排） | 3 | Generator-Critic 质量循环 |
| **合计** | **34** | 含工厂函数生成的实例 |

此外，用户可通过 Custom Skills 创建**无限数量的自定义 LlmAgent**。

---

## 完整智能体层级图

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Semantic Intent Router                          │
│                  (Gemini 2.0 Flash, 非 Agent)                       │
│         ┌──────────┬──────────┬──────────┬──────────┐              │
│         ▼          ▼          ▼          ▼          │              │
│    OPTIMIZATION  GOVERNANCE  GENERAL   AMBIGUOUS    │              │
└────┬──────────┬──────────┬──────────┬───────────────┘              │
     │          │          │          │                               │
     ▼          ▼          ▼          ▼                               │
┌─────────┐┌─────────┐┌─────────┐┌──────────────────────────────────┐│
│Optimiz. ││Govern.  ││General  ││        Planner Agent              ││
│Pipeline ││Pipeline ││Pipeline ││     (Dynamic Orchestrator)        ││
│         ││         ││         ││                                    ││
│ 8 Agent ││ 6 Agent ││ 6 Agent ││ 5 子Agent + 2 子Workflow          ││
│ 2 编排  ││ 1 编排  ││ 1 编排  ││ = 16 Agent (含工厂实例)           ││
└─────────┘└─────────┘└─────────┘└──────────────────────────────────┘│
```

---

## Pipeline 1: Optimization（空间优化管线）

```
data_pipeline (SequentialAgent) ─────────────────────────────────────
│
├── data_engineering_agent (SequentialAgent)
│   │
│   ├── parallel_data_ingestion (ParallelAgent)
│   │   ├── 🧠 data_exploration_agent (LlmAgent, Flash)
│   │   │     职责: 数据画像、拓扑审计、字段标准检查
│   │   │     工具: ExplorationToolset, DatabaseToolset, DataLakeToolset
│   │   │     输出: data_profile
│   │   │
│   │   └── 🧠 semantic_prefetch_agent (LlmAgent, Flash)
│   │         职责: 并行预加载语义目录和数据资产信息
│   │         工具: SemanticLayerToolset, DataLakeToolset
│   │         输出: semantic_context
│   │
│   └── 🧠 data_processing_agent (LlmAgent, Standard)
│         职责: 空间变换、特征工程、数据融合
│         工具: GeoProcessingToolset, LocationToolset, FusionToolset,
│               RemoteSensingToolset, KnowledgeGraphToolset + AgentTool(knowledge_agent)
│         输出: processed_data
│
├── analysis_quality_loop (LoopAgent, max 3 轮)
│   ├── 🧠 data_analysis_agent (LlmAgent, Standard)
│   │     职责: DRL 优化、FFI 计算、统计分析
│   │     工具: AnalysisToolset, RemoteSensingToolset, SpatialStatisticsToolset
│   │     输出: analysis_report
│   │
│   └── 🧠 quality_checker_agent (LlmAgent, Flash)
│         职责: 验证结果完整性、值域合理性
│         工具: approve_quality 内置工具
│
├── 🧠 data_visualization_agent (LlmAgent, Standard)
│     职责: 专题图、气泡图、交互式地图、3D 可视化
│     工具: VisualizationToolset, DataLakeToolset, FileToolset
│     输出: visualizations
│
└── 🧠 data_summary_agent (LlmAgent, Standard)
      职责: 生成决策报告
      工具: FileToolset, VisualizationToolset, MemoryToolset
      输出: final_summary
```

**智能体数**: 8 个 LlmAgent + 1 ParallelAgent + 1 LoopAgent + 2 SequentialAgent = **12**

---

## Pipeline 2: Governance（数据治理管线）

```
governance_pipeline (SequentialAgent) ───────────────────────────────
│
├── 🧠 governance_exploration_agent (LlmAgent, Flash)
│     职责: 数据审计（拓扑、字段标准、一致性）
│     工具: ExplorationToolset, DatabaseToolset, DataLakeToolset + ArcPy 审计
│     输出: data_profile
│
├── 🧠 governance_processing_agent (LlmAgent, Standard)
│     职责: 数据修复、地理编码、融合
│     工具: GeoProcessingToolset, LocationToolset, FusionToolset + ArcPy 处理
│     输出: processed_data
│
└── governance_report_loop (LoopAgent, max 3 轮)
    ├── 🧠 governance_report_agent (LlmAgent, Premium ⭐)
    │     职责: 撰写治理报告（最强模型，需要深度综合推理）
    │     工具: VisualizationToolset, FileToolset, MemoryToolset
    │     输出: governance_report
    │
    └── 🧠 governance_checker_agent (LlmAgent, Flash)
          职责: 检查报告完整性
          工具: approve_quality 内置工具
```

**智能体数**: 4 个 LlmAgent + 1 LoopAgent + 1 SequentialAgent = **6**

---

## Pipeline 3: General（通用分析管线）

```
general_pipeline (SequentialAgent) ──────────────────────────────────
│
├── 🧠 general_processing_agent (LlmAgent, Standard)
│     职责: 通用空间处理（19 个 Toolset 全量，动态过滤）
│     工具: 全部可用 Toolset（按 tool_categories 动态裁剪）
│     输出: processed_data
│
├── 🧠 general_viz_agent (LlmAgent, Standard)
│     职责: 地图和图表生成
│     工具: VisualizationToolset, DataLakeToolset, FileToolset
│     输出: visualizations
│
└── general_summary_loop (LoopAgent, max 3 轮)
    ├── 🧠 general_summary_agent (LlmAgent, Standard)
    │     职责: 汇总分析结果
    │     工具: VisualizationToolset, FileToolset, MemoryToolset
    │     输出: final_summary
    │
    └── 🧠 general_result_checker (LlmAgent, Flash)
          职责: 结果质量检查
          工具: approve_quality 内置工具
```

**智能体数**: 4 个 LlmAgent + 1 LoopAgent + 1 SequentialAgent = **6**

---

## Pipeline 4: Planner（动态编排器）

```
planner_agent (LlmAgent, Standard) ─────────────────────────────────
│
├── 直接工具: SkillToolset, MemoryToolset, AdminToolset, TeamToolset,
│            DataLakeToolset, VisualizationToolset, RemoteSensingToolset,
│            WatershedToolset, GeoProcessingToolset(含ArcPy)
│
├── 子 Agent (5):
│   ├── 🧠 planner_explorer (LlmAgent, Fast)     ← _make_planner_explorer()
│   ├── 🧠 planner_processor (LlmAgent, Standard) ← _make_planner_processor()
│   ├── 🧠 planner_analyzer (LlmAgent, Standard)  ← _make_planner_analyzer()
│   ├── 🧠 planner_visualizer (LlmAgent, Standard) ← _make_planner_visualizer()
│   └── 🧠 planner_reporter (LlmAgent, Premium ⭐)
│
└── 子工作流 (2):
    ├── explore_process_workflow (SequentialAgent)
    │   ├── WFParallelIngestion (ParallelAgent)
    │   │   ├── 🧠 WFExplorer (LlmAgent)        ← _make_planner_explorer()
    │   │   └── 🧠 WFSemanticPreFetch (LlmAgent) ← _make_semantic_prefetch()
    │   └── 🧠 WFProcessor (LlmAgent)            ← _make_planner_processor()
    │
    └── analyze_viz_workflow (SequentialAgent)
        ├── 🧠 WFAnalyzer (LlmAgent)             ← _make_planner_analyzer()
        └── 🧠 WFVisualizer (LlmAgent)           ← _make_planner_visualizer()
```

**智能体数**: 10 个 LlmAgent + 1 ParallelAgent + 2 SequentialAgent = **13**（含 Planner 自身）

> Planner 模式下 LLM 自主决定调用哪个子 Agent 或工作流，而非固定顺序执行。

---

## 独立智能体

```
🧠 knowledge_agent (Agent, Standard)
     职责: Vertex AI Search 企业文档搜索
     工具: VertexAiSearchTool
     输出: domain_knowledge
     调用方式: 通过 AgentTool 包装，被 data_processing_agent 按需调用
```

---

## 用户自定义智能体

```
🧠 CustomSkill_* (LlmAgent, 动态创建)
     职责: 用户定义的专家行为
     指令: 用户编写的 instruction
     工具: 用户选择的 Toolset 组合（最多 23 个可选）
     创建: build_custom_agent() 从 DB 记录动态构建
     数量: 无限（每用户最多 20 个）
```

---

## 模型分层分配

```
gemini-2.0-flash  (Fast)      gemini-2.5-flash  (Standard)   gemini-2.5-pro (Premium)
─────────────────────────      ──────────────────────────      ─────────────────────────
• 意图路由器 (非Agent)         • data_processing_agent        • governance_report_agent
• data_exploration_agent       • data_analysis_agent          • planner_reporter
• semantic_prefetch_agent      • data_visualization_agent
• quality_checker_agent        • data_summary_agent
• governance_exploration       • governance_processing
• governance_checker           • general_processing_agent
• general_result_checker       • general_viz_agent
• WFExplorer                   • general_summary_agent
• WFSemanticPreFetch           • planner_agent
                               • planner_processor
                               • planner_analyzer
                               • planner_visualizer
                               • WFProcessor
                               • WFAnalyzer
                               • WFVisualizer

共 9 个 Fast Agent             共 14 个 Standard Agent          共 2 个 Premium Agent
(低成本、低延迟)               (平衡能力与成本)                 (复杂综合推理)
```

---

## 工厂函数（ADK 单父约束解法）

ADK 要求每个 Agent 实例只能有一个父级。当 Planner 和子工作流需要相同配置的 Agent 时，通过工厂函数创建独立实例：

| 工厂函数 | 创建的实例 | 使用位置 |
|---------|-----------|---------|
| `_make_planner_explorer(name)` | PlannerExplorer, WFExplorer | Planner 子Agent + ExploreAndProcess |
| `_make_planner_processor(name)` | PlannerProcessor, WFProcessor | Planner 子Agent + ExploreAndProcess |
| `_make_planner_analyzer(name)` | PlannerAnalyzer, WFAnalyzer | Planner 子Agent + AnalyzeAndVisualize |
| `_make_planner_visualizer(name)` | PlannerVisualizer, WFVisualizer | Planner 子Agent + AnalyzeAndVisualize |
| `_make_semantic_prefetch(name)` | semantic_prefetch_agent, WFSemanticPreFetch | Optimization + ExploreAndProcess |

---

## 智能体编排模式

| 模式 | ADK 类型 | 使用场景 | 实例 |
|------|---------|---------|------|
| **顺序执行** | SequentialAgent | 有依赖的流水线 | data_pipeline, governance_pipeline, general_pipeline |
| **并行执行** | ParallelAgent | 无依赖的并发 | parallel_data_ingestion, WFParallelIngestion |
| **质量循环** | LoopAgent | Generator→Critic→重试 | analysis_quality_loop (max 3) |
| **动态路由** | LlmAgent + sub_agents | LLM 自主选择 | planner_agent |
| **工具化调用** | AgentTool | Agent 作为另一个 Agent 的工具 | knowledge_tool |
| **用户编排** | WorkflowEditor DAG | 用户可视化编排 | custom_skill → execute_workflow_dag |

---

*本文档基于 GIS Data Agent v12.0 (ADK v1.27.2) 的 agent.py (625 行) 编写。*
