# Data Agent 智能体清单

> 系统中所有 Agent 的完整清单、层级关系和职责说明。

---

## 智能体总数

| 类别 | 数量 | 说明 |
|------|------|------|
| **LlmAgent / Agent**（独立推理实体） | 37 | 具有 LLM 推理能力的 Agent（含工厂创建的实例） |
| **SequentialAgent**（顺序编排） | 8 | 串行执行子 Agent |
| **ParallelAgent**（并行编排） | 2 | 并发执行子 Agent |
| **LoopAgent**（循环编排） | 3 | Generator-Critic 质量循环 |
| **合计** | **50** | 全部运行时 Agent 实例 |

此外，用户可通过 Custom Skills 创建**无限数量的自定义 LlmAgent**（每用户最多 20 个）。

---

## 完整智能体层级图

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Semantic Intent Router                          │
│                  (Gemini 2.0 Flash, 非 Agent)                       │
│         ┌──────────┬──────────┬──────────┬──────────┐              │
│         ▼          ▼          ▼          ▼          ▼              │
│    OPTIMIZATION  GOVERNANCE  GENERAL   WORKFLOW   AMBIGUOUS        │
└────┬──────────┬──────────┬──────────┬───────────────┘              │
     │          │          │          │                               │
     ▼          ▼          ▼          ▼                               │
┌─────────┐┌─────────┐┌─────────┐┌──────────────────────────────────┐│
│Optimiz. ││Govern.  ││General  ││        Planner Agent              ││
│Pipeline ││Pipeline ││Pipeline ││     (Dynamic Orchestrator)        ││
│         ││         ││         ││                                    ││
│ 8 Agent ││ 5 Agent ││ 4 Agent ││ 5 子Agent + 4 S-5 Agent           ││
│ 3 编排  ││ 2 编排  ││ 2 编排  ││ + 4 子Workflow = 23 Agent (含实例) ││
└─────────┘└─────────┘└─────────┘└──────────────────────────────────┘│
```

> 另有 1 个独立 knowledge_agent 通过 AgentTool 被 Optimization Pipeline 按需调用。

---

## Pipeline 1: Optimization（空间优化管线）

```
data_pipeline (SequentialAgent) ─────────────────────────────────────
│
├── data_engineering_agent (SequentialAgent)
│   │
│   ├── parallel_data_ingestion (ParallelAgent)
│   │   ├── 🧠 data_exploration_agent (LlmAgent, Standard)
│   │   │     职责: 数据画像、拓扑审计、字段标准检查
│   │   │     工具: ExplorationToolset(_AUDIT_TOOLS), DatabaseToolset(_DB_READ),
│   │   │           DataLakeToolset(_DATALAKE_READ)
│   │   │     回调: _self_correction_after_tool
│   │   │     输出: data_profile
│   │   │
│   │   └── 🧠 semantic_prefetch_agent (LlmAgent, Fast)
│   │         职责: 并行预加载语义目录和数据资产信息
│   │         工具: SemanticLayerToolset(5 tools), DataLakeToolset(_DATALAKE_READ)
│   │         输出: semantic_context
│   │
│   └── 🧠 data_processing_agent (LlmAgent, Standard)
│         职责: 空间变换、特征工程、数据融合
│         工具: ExplorationToolset(_TRANSFORM_TOOLS), GeoProcessingToolset(11 tools),
│               LocationToolset(geocode), RemoteSensingToolset(download),
│               FusionToolset(), AgentTool(knowledge_agent) + ArcPy
│         回调: _self_correction_after_tool
│         输出: processed_data
│
├── analysis_quality_loop (LoopAgent, max 3 轮)
│   ├── 🧠 data_analysis_agent (LlmAgent, Standard)
│   │     职责: DRL 优化、FFI 计算、空间统计、因果推断
│   │     工具: AnalysisToolset, RemoteSensingToolset, SpatialStatisticsToolset,
│   │           AdvancedAnalysisToolset, CausalInferenceToolset,
│   │           LLMCausalToolset, DreamerToolset
│   │     输出: analysis_report
│   │
│   └── 🧠 quality_checker_agent (LlmAgent, Fast)
│         职责: 验证 DRL/遥感指标合理性
│         工具: approve_quality
│         输出: quality_verdict
│
├── 🧠 data_visualization_agent (LlmAgent, Standard)
│     职责: 专题图、气泡图、交互式地图、PNG 导出
│     工具: VisualizationToolset(7 tools)
│     输出: visualizations
│
└── 🧠 data_summary_agent (LlmAgent, Standard)
      职责: 生成决策报告
      全局指令: 注入当天日期
      输出: final_summary
```

**智能体数**: 8 LlmAgent + 1 ParallelAgent + 1 LoopAgent + 2 SequentialAgent = **12**

---

## Pipeline 2: Governance（数据治理管线）

```
governance_pipeline (SequentialAgent) ───────────────────────────────
│
├── 🧠 governance_exploration_agent (LlmAgent, Standard)
│     职责: 7 项治理检查 + 综合评分
│     工具: ExplorationToolset(_AUDIT_TOOLS), DatabaseToolset(_DB_READ),
│           GovernanceToolset(8 tools) + ArcPy 审计
│     回调: _self_correction_after_tool
│     输出: data_profile
│
├── 🧠 governance_processing_agent (LlmAgent, Standard)
│     职责: 数据修复、缺隙填补、去重、套合精度
│     工具: ExplorationToolset(_TRANSFORM), GeoProcessingToolset(3 tools),
│           LocationToolset(geocode), FusionToolset(),
│           GovernanceToolset(5 tools), PrecisionToolset() + ArcPy 处理
│     回调: _self_correction_after_tool
│     输出: processed_data
│
├── 🧠 governance_viz_agent (LlmAgent, Standard)
│     职责: 治理审计可视化 — 雷达图 + 问题分布图
│     工具: VisualizationToolset(3 tools), ChartToolset()
│     输出: governance_visualizations
│
└── governance_report_loop (LoopAgent, max 3 轮)
    ├── 🧠 governance_report_agent (LlmAgent, Standard)
    │     职责: 撰写治理报告（评分、整改建议）
    │     工具: ReportToolset()
    │     输出: governance_report
    │
    └── 🧠 governance_checker_agent (LlmAgent, Fast)
          职责: 检查报告完整性和合规性
          工具: approve_quality
          输出: gov_quality_verdict
```

**智能体数**: 5 LlmAgent + 1 LoopAgent + 1 SequentialAgent = **7**

---

## Pipeline 3: General（通用分析管线）

```
general_pipeline (SequentialAgent) ──────────────────────────────────
│
├── 🧠 general_processing_agent (LlmAgent, Standard)
│     职责: 通用空间处理（25 个 Toolset + ArcPy，按 intent_tool_predicate 动态裁剪）
│     工具: ExplorationToolset, GeoProcessingToolset, LocationToolset,
│           DatabaseToolset, FileToolset, MemoryToolset, AdminToolset,
│           RemoteSensingToolset, SpatialStatisticsToolset, SemanticLayerToolset,
│           StreamingToolset, TeamToolset, DataLakeToolset, McpHubToolset(general),
│           FusionToolset, KnowledgeGraphToolset, KnowledgeBaseToolset,
│           AdvancedAnalysisToolset, VirtualSourceToolset, WorldModelToolset,
│           CausalWorldModelToolset, LLMCausalToolset,
│           GovernanceToolset, DataCleaningToolset, PrecisionToolset, ReportToolset + ArcPy
│     回调: _self_correction_after_tool
│     输出: processed_data
│
├── 🧠 general_viz_agent (LlmAgent, Standard)
│     职责: 地图和图表生成
│     工具: VisualizationToolset(7 tools), ChartToolset()
│     输出: visualizations
│
└── general_summary_loop (LoopAgent, max 3 轮)
    ├── 🧠 general_summary_agent (LlmAgent, Standard)
    │     职责: 汇总分析结果
    │     输出: final_summary
    │
    └── 🧠 general_result_checker (LlmAgent, Fast)
          职责: 结果完整性审查
          工具: approve_quality
          输出: general_quality_verdict
```

**智能体数**: 4 LlmAgent + 1 LoopAgent + 1 SequentialAgent = **6**

---

## Pipeline 4: Planner（动态编排器）

Planner 是 LLM 驱动的动态路由器，自主决定调用哪个子 Agent 或子工作流：

```
planner_agent (LlmAgent, Standard) ─────────────────────────────────
│
├── 直接工具 (12 个 Toolset):
│     SkillToolset(build_all_skills), MemoryToolset, NL2SQLToolset,
│     OperatorToolset, ToolEvolutionToolset, AdminToolset, TeamToolset,
│     DataLakeToolset, VisualizationToolset(1 tool), RemoteSensingToolset(download_dem),
│     WatershedToolset, GeoProcessingToolset(含ArcPy)
│
├── 子 Agent (5 + 4 S-5):
│   │
│   │  ── Planner 专属子 Agent ──
│   ├── 🧠 PlannerExplorer (LlmAgent, Fast)        ← _make_planner_explorer()
│   │     工具: ExplorationToolset, DatabaseToolset, FileToolset,
│   │           SemanticLayerToolset, DataLakeToolset + ArcPy
│   │     输出: data_profile
│   │
│   ├── 🧠 PlannerProcessor (LlmAgent, Standard)   ← _make_planner_processor()
│   │     工具: ExplorationToolset, GeoProcessingToolset, LocationToolset,
│   │           RemoteSensingToolset, StreamingToolset, DatabaseToolset,
│   │           McpHubToolset(planner), FusionToolset,
│   │           KnowledgeGraphToolset, KnowledgeBaseToolset,
│   │           VirtualSourceToolset + ArcPy
│   │     输出: processed_data
│   │
│   ├── 🧠 PlannerAnalyzer (LlmAgent, Standard)    ← _make_planner_analyzer()
│   │     工具: AnalysisToolset, RemoteSensingToolset(4 tools), SpatialStatisticsToolset,
│   │           AdvancedAnalysisToolset, CausalInferenceToolset,
│   │           LLMCausalToolset, DreamerToolset
│   │     输出: analysis_report
│   │
│   ├── 🧠 PlannerVisualizer (LlmAgent, Standard)  ← _make_planner_visualizer()
│   │     工具: VisualizationToolset, ChartToolset
│   │     输出: visualizations
│   │
│   ├── 🧠 PlannerReporter (LlmAgent, Premium ⭐)
│   │     职责: 综合分析报告撰写（唯一 Premium 模型 Agent）
│   │     输出: final_report
│   │
│   │  ── S-5 多 Agent 协作 ──
│   ├── 🧠 DataEngineerAgent (LlmAgent, Standard)  ← _make_data_engineer()
│   │     工具: OperatorToolset(clean/integrate), DataCleaningToolset,
│   │           GovernanceToolset, PrecisionToolset, ExplorationToolset,
│   │           DatabaseToolset, FileToolset
│   │     输出: prepared_data
│   │
│   ├── 🧠 AnalystAgent (LlmAgent, Standard)       ← _make_analyst()
│   │     工具: OperatorToolset(analyze), AnalysisToolset, SpatialStatisticsToolset,
│   │           AdvancedAnalysisToolset, CausalInferenceToolset, LLMCausalToolset,
│   │           WorldModelToolset, CausalWorldModelToolset, DreamerToolset
│   │     输出: analysis_result
│   │
│   ├── 🧠 VisualizerAgent (LlmAgent, Standard)    ← _make_visualizer_agent()
│   │     工具: OperatorToolset(visualize), VisualizationToolset, ChartToolset,
│   │           ReportToolset, DataLakeToolset, ExplorationToolset, FileToolset
│   │     输出: visualization_output
│   │
│   └── 🧠 RemoteSensingAgent (LlmAgent, Standard) ← _make_remote_sensing()
│         工具: RemoteSensingToolset, WatershedToolset, SpatialStatisticsToolset,
│               VisualizationToolset(2 tools), ExplorationToolset(2 tools) + ArcPy
│         输出: rs_analysis
│
└── 子工作流 (4):
    │
    ├── explore_process_workflow (SequentialAgent)
    │   ├── WFParallelIngestion (ParallelAgent)
    │   │   ├── 🧠 WFExplorer (LlmAgent, Fast)             ← _make_planner_explorer()
    │   │   └── 🧠 WFSemanticPreFetch (LlmAgent, Fast)     ← _make_semantic_prefetch()
    │   └── 🧠 WFProcessor (LlmAgent, Standard)            ← _make_planner_processor()
    │
    ├── analyze_viz_workflow (SequentialAgent)
    │   ├── 🧠 WFAnalyzer (LlmAgent, Standard)             ← _make_planner_analyzer()
    │   └── 🧠 WFVisualizer (LlmAgent, Standard)           ← _make_planner_visualizer()
    │
    ├── full_analysis_workflow (SequentialAgent)  [S-5]
    │   ├── 🧠 FADataEngineer (LlmAgent, Standard)         ← _make_data_engineer()
    │   ├── 🧠 FAAnalyst (LlmAgent, Standard)              ← _make_analyst()
    │   └── 🧠 FAVisualizer (LlmAgent, Standard)           ← _make_visualizer_agent()
    │
    └── rs_analysis_workflow (SequentialAgent)  [S-5]
        ├── 🧠 RSRemoteSensing (LlmAgent, Standard)        ← _make_remote_sensing()
        └── 🧠 RSVisualizer (LlmAgent, Standard)           ← _make_visualizer_agent()
```

**智能体数**: 20 LlmAgent + 1 ParallelAgent + 4 SequentialAgent = **25**（含 Planner 自身）

> Planner 模式下 LLM 自主决定调用哪个子 Agent 或工作流，而非固定顺序执行。
> `disallow_transfer_to_peers=True` 防止子 Agent 间横向跳转，确保控制权回归 Planner。

---

## 独立智能体

```
🧠 knowledge_agent (Agent, Standard)
     职责: Vertex AI Search 企业文档搜索
     工具: VertexAiSearchTool(DATASTORE_ID)
     输出: domain_knowledge
     调用方式: 通过 AgentTool 包装，被 data_processing_agent 按需调用
```

---

## 用户自定义智能体

```
🧠 CustomSkill_* (LlmAgent, 动态创建)
     职责: 用户定义的专家行为
     指令: 用户编写的 instruction（最大 10,000 字符，prompt injection 防御）
     工具: 用户从 40 个 Toolset 中选择组合
     模型: 用户选择 fast / standard / premium
     创建: build_custom_agent() 从 DB 记录动态构建
     数量: 每用户最多 20 个
     共享: is_shared 控制团队可见性
```

---

## 模型分层分配

```
gemini-2.0-flash  (Fast)         gemini-2.5-flash  (Standard)        gemini-2.5-pro (Premium)
───────────────────────────      ───────────────────────────────      ─────────────────────────
• 意图路由器 (非Agent)            • knowledge_agent                   • PlannerReporter
• semantic_prefetch_agent        • data_exploration_agent
• quality_checker_agent          • data_processing_agent
• governance_checker_agent       • data_analysis_agent
• general_result_checker         • data_visualization_agent
• PlannerExplorer                • data_summary_agent
• WFExplorer                     • governance_exploration_agent
• WFSemanticPreFetch             • governance_processing_agent
                                 • governance_viz_agent
                                 • governance_report_agent
                                 • general_processing_agent
                                 • general_viz_agent
                                 • general_summary_agent
                                 • planner_agent
                                 • PlannerProcessor
                                 • PlannerAnalyzer
                                 • PlannerVisualizer
                                 • WFProcessor, WFAnalyzer, WFVisualizer
                                 • DataEngineerAgent, AnalystAgent
                                 • VisualizerAgent, RemoteSensingAgent
                                 • FA*, RS* (工厂实例)

共 7 个 Fast Agent              共 29 个 Standard Agent               共 1 个 Premium Agent
($0.10/$0.40 per 1k tokens)    ($0.15/$0.60 per 1k tokens)         ($1.25/$5.00 per 1k tokens)
(低成本、低延迟)                (平衡能力与成本)                      (复杂综合推理)
```

v23.0: 模型分层由 `ModelConfigManager` (DB-backed) 管理，支持运行时动态切换，env var 作为 fallback。
`ModelRouter` 支持任务感知路由（根据 task_type / context_tokens / quality_requirement 自动选模型）。
`model_gateway.py` 统一网关支持 Gemini (在线) + LM Studio (离线) + LiteLLM 后端。

---

## 工厂函数（ADK 单父约束解法）

ADK 要求每个 Agent 实例只能有一个父级。当 Planner 和子工作流需要相同配置的 Agent 时，通过工厂函数创建独立实例：

| 工厂函数 | 创建的实例 | 所属 Pipeline |
|---------|-----------|--------------|
| `_make_planner_explorer(name)` | PlannerExplorer, WFExplorer | Planner, ExploreAndProcess |
| `_make_planner_processor(name)` | PlannerProcessor, WFProcessor | Planner, ExploreAndProcess |
| `_make_planner_analyzer(name)` | PlannerAnalyzer, WFAnalyzer | Planner, AnalyzeAndVisualize |
| `_make_planner_visualizer(name)` | PlannerVisualizer, WFVisualizer, FAVisualizer, RSVisualizer | Planner, AnalyzeAndVisualize, FullAnalysis, RSAnalysis |
| `_make_semantic_prefetch(name)` | semantic_prefetch_agent, WFSemanticPreFetch | Optimization, ExploreAndProcess |
| `_make_data_engineer(name)` | DataEngineerAgent, FADataEngineer | Planner, FullAnalysis |
| `_make_analyst(name)` | AnalystAgent, FAAnalyst | Planner, FullAnalysis |
| `_make_visualizer_agent(name)` | VisualizerAgent, FAVisualizer, RSVisualizer | Planner, FullAnalysis, RSAnalysis |
| `_make_remote_sensing(name)` | RemoteSensingAgent, RSRemoteSensing | Planner, RSAnalysis |

所有工厂函数均支持 `**overrides` 参数，允许调用方覆盖默认配置。

---

## S-5 多 Agent 协作（v16.0）

v16.0 引入四类专业化 Agent，支持语义算子（OperatorToolset）驱动的自动策略选择：

| 角色 | Agent Name | 工厂函数 | 核心能力 | 语义算子 |
|------|-----------|---------|---------|---------|
| **数据工程** | DataEngineerAgent | `_make_data_engineer()` | 清洗、融合、标准化、质量保障 | clean_data, integrate_data |
| **分析专家** | AnalystAgent | `_make_analyst()` | 空间统计、DRL、因果、世界模型 | analyze_data |
| **可视化** | VisualizerAgent | `_make_visualizer_agent()` | 地图、图表、报告、PNG 导出 | visualize_data |
| **遥感** | RemoteSensingAgent | `_make_remote_sensing()` | 光谱指数、DEM、流域、LULC、变化检测 | — |

预定义组合工作流：

| 工作流 | 编排类型 | 子 Agent | 用途 |
|--------|---------|---------|------|
| `full_analysis_workflow` | SequentialAgent | DataEngineer → Analyst → Visualizer | 原始数据 → 完整分析报告 |
| `rs_analysis_workflow` | SequentialAgent | RemoteSensing → Visualizer | 卫星影像 → 遥感分析报告 |

---

## 智能体编排模式

| 模式 | ADK 类型 | 使用场景 | 实例 |
|------|---------|---------|------|
| **顺序执行** | SequentialAgent | 有依赖的流水线 | data_pipeline, governance_pipeline, general_pipeline |
| **并行执行** | ParallelAgent | 无依赖的并发 | parallel_data_ingestion, WFParallelIngestion |
| **质量循环** | LoopAgent (max 3) | Generator → Critic → 重试 | analysis_quality_loop, governance_report_loop, general_summary_loop |
| **动态路由** | LlmAgent + sub_agents | LLM 自主选择子 Agent/Workflow | planner_agent (9 子Agent + 4 子Workflow) |
| **工具化调用** | AgentTool | Agent 作为另一个 Agent 的工具 | knowledge_tool → data_processing_agent |
| **语义算子** | OperatorToolset | 自动策略选择+执行 | S-5 DataEngineer, Analyst, Visualizer |
| **用户编排** | WorkflowEngine DAG | 用户可视化编排 | custom_skill 节点 → DAG 引擎执行 |

---

## 回调机制

| 回调 | 绑定 Agent | 功能 |
|------|-----------|------|
| `_self_correction_after_tool` | 6+ 个 Agent（data_exploration, data_processing, governance_exploration, governance_processing, general_processing, PlannerExplorer, PlannerProcessor, PlannerAnalyzer, S-5 工厂 agents） | 工具执行后自动检查错误并尝试修正 |
| `approve_quality` | 3 个 Checker Agent（quality_checker, governance_checker, general_result_checker） | 业务级质量门控，决定是否通过或重试 |

---

## 工具过滤策略

| 过滤方式 | 说明 | 使用场景 |
|---------|------|---------|
| **静态允许列表** (`tool_filter=["fn1", "fn2"]`) | 编译时确定可用工具 | Optimization/Governance Pipeline 中的精确控制 |
| **动态谓词** (`tool_filter=intent_tool_predicate`) | 运行时根据 intent_router 输出的 tool_categories 决定 | General Pipeline、Planner 子 Agent |
| **pipeline 参数** (`McpHubToolset(pipeline="general")`) | MCP 工具按管线分配 | MCP 外部工具隔离 |
| **无过滤** (`Toolset()`) | 暴露全部工具 | Analysis、Fusion 等全量需求场景 |

---

## Toolset 清单（40 个 .py 文件）

| Toolset | 文件 | 说明 |
|---------|------|------|
| ExplorationToolset | exploration_tools.py | 数据画像、拓扑审计、字段标准、一致性检查 |
| GeoProcessingToolset | geo_processing_tools.py | 镶嵌、裁剪、缓冲、邻域、字段计算、ArcPy 桥接 |
| LocationToolset | location_tools.py | 批量地理编码、逆地理编码 |
| AnalysisToolset | analysis_tools.py | DRL 优化、FFI 计算、土地利用分析 |
| VisualizationToolset | visualization_tools.py | 交互地图、Choropleth、气泡图、热力图、PNG 导出 |
| DatabaseToolset | database_tools_set.py | SQL 查询、表管理、PostGIS 导入 |
| FileToolset | file_tools.py | 用户文件 CRUD |
| MemoryToolset | memory_tools.py | 对话记忆存取 |
| AdminToolset | admin_tools.py | 管理员操作 |
| RemoteSensingToolset | remote_sensing_tools.py | LULC/DEM 下载、NDVI、光谱指数、云量评估 |
| SpatialStatisticsToolset | spatial_statistics_tools.py | 空间自相关、局部 Moran、热点分析 |
| SemanticLayerToolset | semantic_layer_tools.py | 语义上下文解析、层级浏览、列等价发现 |
| StreamingToolset | streaming_tools.py | 流式数据操作 |
| TeamToolset | team_tools.py | 团队协作 |
| DataLakeToolset | datalake_tools.py | 数据资产目录浏览与下载 |
| McpHubToolset | mcp_hub_toolset.py | MCP 外部工具集成 |
| FusionToolset | fusion_tools.py | 多源数据融合 |
| KnowledgeGraphToolset | knowledge_graph_tools.py | 地理知识图谱操作 |
| KnowledgeBaseToolset | knowledge_base_tools.py | 知识库检索与管理 |
| AdvancedAnalysisToolset | advanced_analysis_tools.py | 高级空间分析 |
| GovernanceToolset | governance_tools.py | 18 项治理检查（完整性/属性/CRS/拓扑/面积/建筑高度/坐标精度/缺隙/去重/评分） |
| ChartToolset | chart_tools.py | 统计图表生成 |
| WatershedToolset | watershed_tools.py | 流域/汇水区提取、水流分析 |
| VirtualSourceToolset | virtual_source_tools.py | 虚拟数据源操作 |
| WorldModelToolset | world_model_tools.py | 世界模型预测 |
| NL2SQLToolset | nl2sql_tools.py | 自然语言转 SQL |
| CausalInferenceToolset | causal_inference_tools.py | 时空因果推断 (PSM/ERF/DiD/Granger/GCCM/Causal Forest) |
| LLMCausalToolset | llm_causal_tools.py | LLM 驱动因果推断 (DAG/反事实/机制解释) |
| CausalWorldModelToolset | causal_world_model_tools.py | 因果世界模型 |
| DreamerToolset | dreamer_tools.py | Dreamer 世界模型集成 |
| OperatorToolset | operator_tools.py | 语义算子 (clean/integrate/analyze/visualize) |
| ToolEvolutionToolset | evolution_tools.py | 工具演化与发现 |
| DataCleaningToolset | data_cleaning_tools.py | 数据清洗 (15 tools) |
| PrecisionToolset | precision_tools.py | 套合精度检测 (7 tools) |
| ReportToolset | report_tools.py | 报告生成 |
| SkillBundlesToolset | skill_bundles.py | 技能包构建 |
| StorageToolset | storage_tools.py | 云存储操作 |
| SparkToolset | spark_tools.py | Spark 分布式处理 |
| SpatialAnalysisTier2Toolset | spatial_analysis_tier2_tools.py | 高级空间分析 Tier2 |
| UserToolsToolset | user_tools_toolset.py | 用户自定义工具 |

---

## ADK Skills（26 个内置 + DB 自定义）

| 技能目录 | 领域 | 说明 |
|---------|------|------|
| 3d-visualization | 可视化 | 3D 空间可视化 |
| advanced-analysis | 分析 | 高级空间分析 |
| buffer-overlay | 处理 | 缓冲区与叠加分析 |
| coordinate-transform | 处理 | 坐标系转换 |
| data-import-export | 数据 | 数据导入导出 |
| data-profiling | 治理 | 数据质量画像 (Generator pattern) |
| data-quality-reviewer | 治理 | 数据质量审查 |
| ecological-assessment | 分析 | 生态影响评估 |
| farmland-compliance | 治理 | 耕地合规检查 |
| geocoding | 位置 | 地理编码 |
| knowledge-retrieval | 知识 | 知识库检索 |
| land-fragmentation | 分析 | 土地破碎化分析 |
| multi-source-fusion | 处理 | 多源数据融合 |
| postgis-analysis | 数据库 | PostGIS 空间分析 |
| rhinitis-causal-analysis | 分析 | 因果分析 |
| satellite-imagery | 遥感 | 卫星影像分析 |
| site-selection | 分析 | 选址分析 |
| skill-creator | 开发 | 技能创建框架 |
| spatial-clustering | 分析 | 空间聚类 |
| spectral-analysis | 遥感 | 光谱分析 |
| surveying-qc | 治理 | 测绘质检 (GB/T 24356) |
| team-collaboration | 协作 | 团队协作 |
| thematic-mapping | 可视化 | 专题制图 |
| topology-validation | 治理 | 拓扑验证 |
| world-model | 分析 | 世界模型预测 |

三级增量加载: L1 元数据 → L2 指令 → L3 资源。

---

## 意图路由器

| 属性 | 值 |
|------|-----|
| 模型 | `ModelConfigManager` 管理 (默认 gemini-2.0-flash) |
| 意图类别 | 5: OPTIMIZATION / GOVERNANCE / GENERAL / WORKFLOW / AMBIGUOUS |
| 语言检测 | 中文 (zh) / 英文 (en) / 日文 (ja) |
| 消歧 | v23.0 should_decompose + decompose_task + 用户确认 + wave 按序执行 |
| 位置 | `intent_router.py` (197 行) |

---

## 平台规模汇总

| 维度 | 数量 |
|------|------|
| LlmAgent/Agent 实例 | 37 |
| SequentialAgent | 8 |
| ParallelAgent | 2 |
| LoopAgent | 3 |
| **运行时 Agent 总计** | **50** |
| 工厂函数 | 9 |
| Toolset (.py 文件) | 40 |
| ADK Skills (内置) | 26 (含 skill-creator) |
| REST API 端点 | 127 (frontend_api.py) |
| DB 迁移 (SQL) | 64 |
| 测试文件 | 171 |
| 测试用例 | 3,588 |
| 子系统 | 4 (cv-service, cad-parser, tool-mcp-servers, reference-data) |
| 使用 Fast 模型 | 7 个 Agent |
| 使用 Standard 模型 | 29 个 Agent |
| 使用 Premium 模型 | 1 个 Agent (PlannerReporter) |
| 绑定 after_tool_callback | 9+ 个 Agent |
| agent.py 行数 | 853 |
| frontend_api.py 行数 | 3,438 |

---

*本文档基于 GIS Data Agent v23.0 (ADK v1.27.2) 的 agent.py (853 行) 精确同步，2026-04-10。*

