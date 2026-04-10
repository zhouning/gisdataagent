# Agent · Skill · Tool 架构关系

> GIS Data Agent v23.0 多 Agent 架构中核心概念的定义、层次关系和协作方式。

---

## 层次结构

```
Platform (BCG Enterprise Agent Platform)
│
├── Semantic Router (intent_router.py, Gemini 2.0 Flash)
│     → OPTIMIZATION / GOVERNANCE / GENERAL / WORKFLOW / AMBIGUOUS
│     → 多语言检测 (zh/en/ja) + 多模态 (text/image/PDF)
│     → 分析意图消歧 v2: should_decompose + decompose_task + wave 按序执行
│
├── Pipeline (SequentialAgent / ParallelAgent / LoopAgent)
│     │
│     ├── Agent (LlmAgent) ─── 大脑：推理、决策、调用工具
│     │     │
│     │     ├── Instruction ─── 来源：Prompt Registry / ADK Skill / Custom Skill
│     │     │
│     │     ├── Tools ─── 双手：执行具体操作
│     │     │     ├── 40 个 BaseToolset ────── 215+ 内置工具函数
│     │     │     ├── UserToolset ──────────── 用户声明式自定义工具
│     │     │     ├── McpHubToolset ────────── MCP 外部工具聚合
│     │     │     └── OperatorToolset ──────── 语义算子（Clean/Integrate/Analyze/Visualize）
│     │     │
│     │     └── output_key ─── 产出写入 session.state，传递给下游 Agent
│     │
│     ├── Agent B ...
│     └── Agent C ...
│
├── Model Gateway ─── 在线/离线统一路由（Gemini + LM Studio + LiteLLM）
├── Context Manager ── 可插拔上下文提供器 + token 预算
├── Prompt Registry ── DB 版本化 Prompt 管理（dev / staging / prod）
├── Feedback Loop ──── 结构化反馈闭环 + 参考查询自动入库
├── Eval Framework ─── 场景化评估 + Golden Dataset
└── Observability ──── OTel 4 级 span + Prometheus + Alert Engine
```

---

## 概念定义

| 概念 | 本质 | 粒度 | 谁定义 | 运行时表现 |
|------|------|------|--------|-----------|
| **Tool** | 一个 Python 函数 | 原子操作 | 开发者 / 用户 | `FunctionTool(fn)` — LLM 看到函数签名和描述，决定是否调用 |
| **Toolset** | 按领域分组的 Tool 集合 | 能力域 | 开发者 | `BaseToolset` 子类，支持 `tool_filter` 动态裁剪 |
| **Skill** | 一套领域专家知识 | 场景模板 | 开发者 / 用户 | 提供 instruction（注入 Agent prompt）或作为 `AgentTool` 被其他 Agent 调用 |
| **Operator** | 高级语义操作 | 工作流步骤 | 系统 | 封装领域知识，自动选策略、规划 tool_calls、执行并汇报 |
| **Agent** | 一个 LLM 推理实体 | 决策单元 | 系统 / 用户 | `LlmAgent` — 接收指令，选择并调用 Tools，产生输出 |
| **Pipeline** | 多 Agent 编排容器 | 端到端流程 | 系统 / 用户 | `SequentialAgent` / `ParallelAgent` / `LoopAgent` 组合 |

---

## Tool — 原子操作能力

Tool 是系统中最小的功能单元。每个 Tool 是一个带类型标注和 docstring 的 Python 函数，通过 ADK 的 `FunctionTool` 包装后暴露给 LLM。

```python
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

### Tool 的组织方式 — BaseToolset

Tool 按领域分组到 `BaseToolset` 子类中，支持 `tool_filter` 按需裁剪：

```python
class ExplorationToolset(BaseToolset):
    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
```

系统共有 **40 个 Toolset**（215+ 工具函数），分布在 `toolsets/` 目录下的 41 个 Python 文件中：

| 类别 | Toolset | 说明 |
|------|---------|------|
| **数据探查** | ExplorationToolset | geodataframe 描述、拓扑检查、字段分析 |
| **空间处理** | GeoProcessingToolset | 缓冲、裁剪、叠加、空间连接、镶嵌 |
| **分析统计** | AnalysisToolset, SpatialStatisticsToolset, SpatialAnalysisTier2Toolset | Moran's I, LISA, 热点、GWR、插值 |
| **高级分析** | AdvancedAnalysisToolset | DRL 优化、FFI 计算、NSGA-II Pareto |
| **可视化** | VisualizationToolset, ChartToolset | 专题图、热力图、3D 挤出、雷达/折线/饼图 |
| **数据库** | DatabaseToolset, NL2SQLToolset | SQL 查询、表管理、自然语言转 SQL |
| **语义层** | SemanticLayerToolset, DataLakeToolset | 语义解析、数据资产搜索 |
| **文件/存储** | FileToolset, StorageToolset | 用户文件管理、云存储（S3/GCS） |
| **遥感** | RemoteSensingToolset | NDVI、DEM、LULC、光谱指数 |
| **流域/生态** | WatershedToolset | 流域划分、水文分析 |
| **治理** | GovernanceToolset (18 tools), DataCleaningToolset (11 tools), PrecisionToolset (5 tools) | 合规检查、缺陷修复、套合精度 |
| **融合** | FusionToolset | 10 种融合策略、LLM 路由 |
| **知识** | KnowledgeGraphToolset, KnowledgeBaseToolset | 实体关系图谱、文档语义检索 |
| **因果推断** | CausalInferenceToolset, LLMCausalToolset, CausalWorldModelToolset | PSM/DiD/Granger、LLM 因果推理、世界模型干预 |
| **世界模型** | WorldModelToolset, DreamerToolset | LULC 预测、Dreamer 环境模拟 |
| **语义算子** | OperatorToolset | Clean/Integrate/Analyze/Visualize 四大算子 |
| **协作** | TeamToolset, MemoryToolset | 团队资源共享、用户偏好记忆 |
| **扩展** | UserToolset, McpHubToolset, ToolEvolutionToolset | 用户自定义、MCP 聚合、工具版本演化 |
| **管理** | AdminToolset, LocationToolset, StreamingToolset | 系统管理、地理编码、流式数据 |
| **报告/分发** | ReportToolset | 报告生成、导出 |
| **分布式** | SparkToolset | Spark 分布式计算网关 |
| **虚拟源** | VirtualSourceToolset | 虚拟表创建、连接器调度 |

### 用户扩展 Tool 的方式

通过声明式模板创建自定义工具（无需写代码），系统自动包装为 `FunctionTool`：

| 模板类型 | 用途 | 关键配置 |
|---------|------|---------|
| `http_call` | 调用外部 REST API | url, method, headers, body_template |
| `sql_query` | 参数化数据库查询（只读） | query, connection_string; 拦截 DDL/DML |
| `file_transform` | 文件处理管道 | input_format, output_format, transform_steps |
| `chain` | 串联多个自定义工具（最多 5 步） | steps, pass-through mappings |
| `python_sandbox` | Python 沙箱执行（Phase 2） | restricted environment |

每个用户最多创建 50 个工具，每工具最多 20 个参数，支持评分、克隆、版本管理。

---

## Skill — 领域专家知识

Skill 定义了"Agent 应该如何思考和行动"。它有**双重身份**：

### 身份一：作为 Instruction

Skill 的核心是一段结构化指令，注入到 Agent 的系统提示中：

```yaml
# data_agent/skills/data-profiling/skill.yaml
name: data-profiling
description: "空间数据画像与质量评估技能"
metadata:
  domain: governance
  intent_triggers: "profile, 画像, 数据质量"
```

```markdown
# data_agent/skills/data-profiling/SKILL.md

## 职责
数据画像是所有空间分析的第一步...

## 画像分析维度
| 检查项 | 内容 | 关注点 |
|--------|------|--------|
| 要素数量 | 总记录数 | 空记录占比 |
| 字段清单 | 字段名、类型 | 类型是否合理 |
...
```

当 Agent 收到匹配 `intent_triggers` 的请求时，这段指令被加载并注入到 Agent prompt 中。

### 身份二：作为 Tool（可被调用的 Agent）

通过 `AgentTool`，一个 Skill/Agent 可以被另一个 Agent 当作工具调用：

```python
knowledge_tool = AgentTool(agent=knowledge_agent, skip_summarization=False)

planner = LlmAgent(
    name="Planner",
    tools=[knowledge_tool, ...],  # Planner 可以"调用" knowledge_agent
)
```

### Skill 的三种来源

| 来源 | 数量 | 存储 | 加载方式 |
|------|------|------|---------|
| **内置 ADK Skill** | 25 个 | `skills/` 目录（kebab-case） | `load_skill_from_dir()` → 三级增量加载 |
| **Custom Skill** | 用户定义 | PostgreSQL `agent_custom_skills` 表 | `build_custom_agent()` → `LlmAgent` |
| **Prompt YAML** | 5 个 | `prompts/` 目录 + DB `agent_prompt_versions` 表 | Prompt Registry 按环境加载 |

### 25 个内置 ADK Skill

| Skill | 领域 | 说明 |
|-------|------|------|
| data-profiling | 治理 | 空间数据画像与质量评估 |
| data-quality-reviewer | 治理 | 拓扑审计、一致性检查 |
| topology-validation | 治理 | 多边形闭合、重叠检测 |
| farmland-compliance | 治理 | GB/T 21010 标准合规 |
| surveying-qc | 治理 | 测绘质检（30 缺陷编码） |
| data-import-export | 数据 | Shapefile/GeoJSON/CSV I/O |
| coordinate-transform | 数据 | 重投影、基准面转换 |
| buffer-overlay | 分析 | 缓冲区、裁剪、叠加分析 |
| advanced-analysis | 分析 | 统计方法、回归、插值 |
| spatial-clustering | 分析 | DBSCAN, K-means, 层次聚类 |
| site-selection | 分析 | AHP、加权叠加、适宜性 |
| land-fragmentation | 分析 | 地块破碎度指标、邻接性 |
| ecological-assessment | 分析 | 栖息地适宜性、生物多样性 |
| postgis-analysis | 分析 | PostGIS 空间查询 |
| multi-source-fusion | 融合 | 多源数据融合策略 |
| satellite-imagery | 遥感 | NDVI、LULC、光谱指数 |
| spectral-analysis | 遥感 | SAR、高光谱处理 |
| 3d-visualization | 可视化 | 体数据、3D 挤出、地形渲染 |
| thematic-mapping | 可视化 | 专题制图 |
| geocoding | 位置 | 地址↔坐标互转 |
| knowledge-retrieval | 知识 | KB 检索、语义搜索 |
| world-model | 预测 | LULC 预测、情景模拟 |
| team-collaboration | 协作 | 共享工作区、版本控制 |
| rhinitis-causal-analysis | 因果 | 流行病学因果推断 |
| skill-creator | 元技能 | Skill 定义 UI |

### 三级增量加载

| 级别 | 加载内容 | 时机 | 性能考量 |
|------|---------|------|---------|
| L1 | metadata (name, description, domain) | 应用启动 | 极轻量 |
| L2 | instructions (完整 Prompt) | 路由匹配时 | 按需加载 |
| L3 | resources (附加文件、参考数据) | 执行时 | 惰性加载 |

### Custom Skill 模型

用户在"能力"Tab 创建自定义 Skill，数据库存储，运行时动态构建 `LlmAgent`：

```python
# CustomSkill 数据模型（简化）
{
    "skill_name": "耕地变化监测",          # 2-100 字符
    "description": "监测耕地时序变化趋势",
    "instruction": "你是耕地变化监测专家...",  # 最大 10,000 字符
    "toolsets": ["RemoteSensingToolset", "AnalysisToolset"],  # 从 40 个 Toolset 中选择
    "trigger_keywords": ["耕地变化", "时序监测"],
    "model_tier": "standard",              # fast | standard | premium
    "is_shared": true                       # 团队共享
}
```

安全机制：指令注入防御（禁止 "system:", "ignore previous", "override:" 等模式）。

---

## Semantic Operator — 语义算子（v16.0）

语义算子是 v16.0 引入的高级抽象层，封装领域知识，自动完成"策略选择→工具规划→执行→汇报"全流程。

### 四大算子

| 算子 | 职责 | 自动策略选择 |
|------|------|------------|
| **CleanOperator** | 数据清洗 | CRS 标准化、空值处理、PII 脱敏、拓扑修复 |
| **IntegrateOperator** | 数据融合 | 10 种融合策略（空间连接、属性叠加、栅格配准…） |
| **AnalyzeOperator** | 分析计算 | 空间统计、聚类、回归、插值 |
| **VisualizeOperator** | 可视化 | 专题图、热力图、3D 挤出、流向图 |

### 执行模型

```python
# 算子执行流程
class SemanticOperator(ABC):
    def plan(self, data_profile: dict, goal: str) -> OperatorPlan:
        """根据数据特征和目标，规划 tool_calls 序列"""
        ...

    def execute(self, plan: OperatorPlan) -> OperatorResult:
        """执行计划中的 tool_calls，返回结果"""
        ...

# OperatorPlan 数据结构
@dataclass
class OperatorPlan:
    strategy: str              # 选定的策略名
    tool_calls: list[ToolCall] # 规划的工具调用序列
    estimated_steps: int       # 预估步骤数
    precondition_warnings: list[str]  # 前置条件警告
```

算子通过 `OperatorToolset` 暴露给 Agent，Agent 可以直接调用 `clean_data()`、`integrate_data()` 等高级接口。

---

## Agent — 推理与决策单元

Agent 是绑定了模型、指令和工具的 LLM 推理实体。当前系统共有 **30+ 个 Agent 实例**（19 个 LlmAgent + 11 个编排容器 + 工厂函数动态生成）。

```python
data_exploration_agent = LlmAgent(
    name="DataExploration",
    model=get_model_for_tier("fast"),               # 模型路由
    instruction=prompts["exploration_instruction"],  # Prompt Registry 或 YAML
    tools=[
        ExplorationToolset(tool_filter=_AUDIT_TOOLS),
        DatabaseToolset(tool_filter=_DB_READ),
    ],
    output_key="data_profile",                      # 产出存入 session.state
)
```

### Agent 的编排方式

ADK 提供三种编排容器，系统当前使用：

| 容器 | 实例数 | 行为 | 用途 |
|------|--------|------|------|
| `SequentialAgent` | 7 | 按顺序执行子 Agent | 主管线 + 专业工作流 |
| `ParallelAgent` | 2 | 并发执行子 Agent | 数据摄入（Exploration ‖ SemanticPreFetch） |
| `LoopAgent` | 3 | Generator → Critic 循环（最多 3 轮） | 质量保证（Analysis → QualityChecker） |

### 工厂函数

ADK 要求每个 Agent 只能有一个 parent。为了在多个 Pipeline 中复用相同角色，系统使用 **9 个工厂函数**：

```python
_make_planner_explorer(name, **overrides)   → LlmAgent  # Planner 子管线
_make_planner_processor(name, **overrides)  → LlmAgent
_make_planner_analyzer(name, **overrides)   → LlmAgent
_make_planner_visualizer(name, **overrides) → LlmAgent
_make_semantic_prefetch(name)               → LlmAgent  # 语义预取
_make_data_engineer(name, **overrides)      → LlmAgent  # S-5 多 Agent 协作
_make_analyst(name, **overrides)            → LlmAgent
_make_visualizer_agent(name, **overrides)   → LlmAgent
_make_remote_sensing(name, **overrides)     → LlmAgent
```

### 模型分层策略（Model Gateway — 在线/离线统一路由）

不同角色的 Agent 使用不同级别的模型，由 `ModelRouter` 根据任务类型自动路由。支持三种后端：

| 后端 | 说明 | 配置 |
|------|------|------|
| `gemini` | Google Vertex AI 在线模型 | 默认 |
| `litellm` | 任意 LiteLLM 兼容模型 | `LITELLM_BASE_URL` |
| `lm_studio` | 本地离线模型 | `LM_STUDIO_BASE_URL` (默认 localhost:1234) |

| 模型 | Tier | 成本（1k tokens） | 上下文 | 用途 |
|------|------|-------------------|--------|------|
| gemini-2.0-flash | fast | $0.10 / $0.40 | 1M | 路由器、质量检查器、语义预取 |
| gemini-2.5-flash | standard | $0.15 / $0.60 | 2M | 主 Agent（默认） |
| gemini-2.5-pro | premium | $1.25 / $5.00 | 2M | Reporter、复杂推理、因果分析 |

`ModelRouter` 考虑 `task_type`（classification/extraction/reasoning/generation）、`context_tokens`、`quality_requirement`、`budget_per_call_usd` 四个维度自动选模型。用户可通过 `ContextVar(current_model_tier)` 临时覆盖。DB-backed `ModelConfigManager` 支持运行时动态调整 tier 映射。

### Agent 间状态传递

```
Agent A (output_key="data_profile")
    ↓ session.state["data_profile"] = "数据包含 5000 条记录..."
Agent B (读取上游状态，作为自己的输入上下文)
    ↓ session.state["processed_data"] = "处理后数据路径: ..."
Agent C ...
```

---

## Pipeline — 端到端管线

### 三大核心 Pipeline

**1. Optimization Pipeline** (`data_pipeline`) — 优化分析：

```
ParallelDataIngestion
├── DataExploration ──── [ExplorationToolset, DatabaseToolset]
└── SemanticPreFetch ─── [SemanticLayerToolset, DataLakeToolset]
        ↓
DataProcessing ────────── [GeoProcessingToolset, FusionToolset, UserToolset]
        ↓
AnalysisQualityLoop (max 3 轮)
├── DataAnalysis ──────── [AnalysisToolset, SpatialStatisticsToolset, CausalToolsets, DRL]
└── QualityChecker ────── [业务级验证]
        ↓
DataVisualization ─────── [VisualizationToolset, ChartToolset]
        ↓
DataSummary ──────────── [FileToolset, ReportToolset]
```

**2. Governance Pipeline** (`governance_pipeline`) — 数据治理：

```
GovExploration ──── [ExplorationToolset, GovernanceToolset] (7 点治理清单)
        ↓
GovProcessing ───── [DataCleaningToolset, PrecisionToolset] (修复、填补、去重)
        ↓
GovernanceViz ───── [ChartToolset] (雷达图、问题分布)
        ↓
GovernanceReportLoop (max 3 轮)
├── GovernanceReporter ── [ReportToolset] (综合报告)
└── GovQualityChecker ─── [合规认证]
```

**3. General Pipeline** (`general_pipeline`) — 通用查询：

```
GeneralProcessing → GeneralViz → GeneralSummaryLoop (max 3 轮)
```

### 扩展 Pipeline（v16.0）

**4. Planner Pipeline** — 多 Agent 精炼：

```
PlannerExplorer ──── 语义理解
        ↓
DependencyComposer ── 任务图构建
        ↓
MultiAgentRefinement ── 并行子 Agent 辩论
        ↓
ExecutionPlanner ───── 语义算子编排
```

**5. Full Analysis Workflow** — 完整分析：

```
FADataEngineer → FAAnalyst → FAVisualizer
```

**6. RS Analysis Workflow** — 遥感分析：

```
RSRemoteSensing → RSVisualizer
```

### S-5 多 Agent 协作（v16.0）

四类专业化 Agent 可通过工厂函数按需创建，支持并行协作：

| Agent 角色 | 工厂函数 | 专长 |
|-----------|---------|------|
| DataEngineer | `_make_data_engineer()` | 清洗、融合、标准化 |
| Analyst | `_make_analyst()` | 空间统计、DRL、因果、世界模型 |
| Visualizer | `_make_visualizer_agent()` | 地图、图表、报告 |
| RemoteSensing | `_make_remote_sensing()` | 光谱、DEM、流域、LULC |

---

## 语义路由（Intent Router）

每条用户消息经过 `classify_intent()` 进行语义分类：

```
用户消息 + 图片 + PDF
    ↓
Gemini 2.0 Flash (30s timeout)
    ↓
(intent, reason, tokens, tool_categories, language)
```

### 5 种意图

| 意图 | 路由到 | 示例 |
|------|--------|------|
| OPTIMIZATION | data_pipeline | "分析耕地破碎化" |
| GOVERNANCE | governance_pipeline | "检查拓扑错误" |
| GENERAL | general_pipeline | "查询人口数据" |
| WORKFLOW | workflow_engine | "执行标准质检" |
| AMBIGUOUS | 继续前一管线或提示 | "好的"、"确认" |

### 10 种工具类别（动态过滤）

路由器同时输出工具类别标签，用于动态裁剪 Agent 的工具集：
`spatial_processing`, `poi_location`, `remote_sensing`, `database_management`, `quality_audit`, `streaming_iot`, `collaboration`, `advanced_analysis`, `world_model`, `causal_reasoning`

### 多模态支持

- 文本输入
- 图片分析（最多 3 张，缩放至 512px）
- PDF 上下文摘要（2000 字符摘录）
- 语言检测（zh/en/ja，基于字符分布）

---

## MCP Hub — 外部工具聚合

MCP Hub 管理外部 MCP 服务器，将其工具聚合进 Agent 的工具列表：

```
McpServerConfig
├── transport: stdio | sse | streamable_http
├── enabled: bool
├── category: str
├── pipelines: list[str]  ← 哪些管线可使用
└── credentials → Fernet 加密存储
```

- 最多 20 个 MCP 服务器
- DB + YAML 双源配置（DB 优先）
- 用户级隔离 + 可选共享
- `ToolRuleEngine`：基于 task_type 的工具选择规则 + 降级链

### 内置子系统 MCP 服务器

| 子系统 | 路径 | 传输 | 技术栈 |
|--------|------|------|--------|
| CV Detection | `subsystems/cv-service/` | stdio | FastAPI + YOLO/ultralytics |
| CAD/3D Parser | `subsystems/cad-parser/` | stdio | FastAPI + ezdxf + trimesh |
| ArcGIS/QGIS/Blender | `subsystems/tool-mcp-servers/` | stdio | subprocess → arcpy/QGIS/Blender |
| Reference Data | `subsystems/reference-data/` | REST | FastAPI + PostGIS |

---

## BCG 企业 Agent 平台能力（v15.8+）

基于 BCG《Building Effective Enterprise Agents》框架的平台能力：

### 1. Prompt Registry

DB 版本化 Prompt 管理，支持环境隔离：

```
agent_prompt_versions 表
├── domain: optimization | governance | general | planner
├── prompt_key: "data_exploration_instruction"
├── version: int (自增)
├── environment: prod | dev | staging
├── is_active: bool
└── change_reason, created_by
```

操作：`create_version()` → `deploy(version_id, target_env)` → `rollback()`

### 2. Model Gateway

统一在线/离线模型路由 + 成本追踪（`agent_token_usage` 表，支持 scenario/project_id 归因）。三后端：Gemini / LiteLLM / LM Studio。

### 3. Context Manager

可插拔上下文提供器（SemanticProvider, KBProvider, StandardsProvider, CaseLibraryProvider, ReferenceQueryProvider, MetricDefinitionProvider），按相关性排序，token 预算强制执行（默认 100k tokens）。

### 4. Eval Scenario Framework

场景化评估 + Golden Dataset：`SurveyingQCScenario` 预设指标（defect_precision, defect_recall, defect_f1, fix_success_rate）。可插拔评估器注册表（15 内置评估器）。

### 5. Context Engineering（v19.0）

统一上下文引擎 `ContextEngine` — 6 个 provider 自动收集语义层、知识库、知识图谱、参考查询、成功案例、指标定义。

### 6. Feedback Loop（v19.0）

结构化反馈闭环 — 前端 👍👎 → `agent_feedback` 表 → upvote 自动入库参考查询 → downvote 触发 FailureAnalyzer。`ReferenceQueryStore` 支持 embedding 搜索 + NL2SQL few-shot 注入。

### 7. Semantic Model（v19.0）

MetricFlow 语义模型 — GIS 扩展 YAML 格式 + PostGIS 自动生成器 + MetricDefinitionProvider。

---

## 知识系统

### Knowledge Graph（`knowledge_graph.py`）

基于 networkx DiGraph 的地理知识图谱 — 实体链接、关系发现、推理辅助。

### Knowledge Base（`knowledge_base.py`）

文档索引 + 语义检索 + 案例库（`add_case()` / `search_cases()`，结构化 QC 经验记录）。

### Reference Query Store（`reference_queries.py`，v19.0）

参考查询库 — embedding 搜索 + NL2SQL few-shot 注入 + 自动/手动策展。upvote 的查询自动入库。

---

## 可观测性与安全

### OTel 埋点（v23.0）

4 级 span 层次：pipeline → agent → tool → llm，graceful degradation（OTel 不可用时静默降级）。

### Alert Engine（`observability.py`）

可配置阈值告警规则 + webhook 推送。Prometheus 指标导出。

### API 安全中间件（v22.0）

- `RateLimitMiddleware`：Starlette 层速率限制
- `CircuitBreakerMiddleware`：Starlette 层熔断器
- 无需外部 API 网关（Kong）

---

## 因果推断 · 世界模型

### 三角度因果推断体系

| 角度 | 模块 | 方法 |
|------|------|------|
| **A: 统计因果** | CausalInferenceToolset | PSM, ERF, DiD, Granger, GCCM, Causal Forest |
| **B: LLM 因果** | LLMCausalToolset | DAG 构建, 反事实推理, 机制解释, 情景生成 |
| **C: 世界模型因果** | CausalWorldModelToolset | 干预预测, 反事实对比, 嵌入效应, 统计先验 |

### World Model（JEPA 架构）

```
Encoder: AlphaEarth 64-dim 嵌入（冻结）
    ↓
Dynamics: LatentDynamicsNet（残差 CNN，200 步预测）
    ↓
Decoder: LULC 分类器（83.7% 准确率）
```

`predict_lulc(geometry, years_ahead)` → 土地利用概率 | `simulate_scenario(geometry, interventions, years)` → 反事实模拟

---

## Workflow Engine — 工作流引擎

用户在 WorkflowEditor（ReactFlow DAG 编辑器）中可视化编排工作流：

### 节点类型

| 节点类型 | 说明 |
|---------|------|
| `agent_call` | 调用管线 Agent |
| `tool_call` | 单工具执行 |
| `custom_skill` | 自定义 Skill 调用 |
| `conditional` | 条件分支 |
| `loop` | 循环 N 次 |

### 核心特性

- **DAG 执行**：拓扑排序 → 并行分支 → 汇聚
- **Cron 调度**：定时触发（v5.4）
- **Webhook 推送**：完成后推送结果（v5.4）
- **SLA 追踪**：步骤级超时 + 总时限（v15.6）
- **检查点/恢复**：node_checkpoints 支持断点续跑（v14.0）
- **优先级队列**：low / normal / high（v15.6）
- **QC 模板**：标准质检(5步)、快速质检(2步)、DLG/DOM/DEM 专项质检
- **NL2Workflow**：自然语言生成可执行工作流 DAG（`nl2workflow.py`）

---

## 实际执行流程

以用户输入 "分析福禄镇的耕地破碎化程度" 为例：

```
用户消息: "分析福禄镇的耕地破碎化程度"
    │
    ▼
① 语义路由 (intent_router.py, Gemini 2.0 Flash)
   → intent=OPTIMIZATION, tools=[spatial_processing, advanced_analysis]
   → language=zh
    │
    ▼
② RBAC 检查 (viewer 角色被拦截)
    │
    ▼
③ Model Gateway 选择模型 → gemini-2.5-flash (standard)
    │
    ▼
④ Context Manager 准备上下文
   → SemanticProvider: 耕地语义定义
   → StandardsProvider: GB/T 21010 分类标准
   → token budget 裁剪
    │
    ▼
⑤ Optimization Pipeline (SequentialAgent)
    │
    ├── ParallelDataIngestion
    │     ├── DataExploration → describe_geodataframe() → data_profile
    │     └── SemanticPreFetch → resolve_semantic_context() → 语义上下文
    │
    ├── DataProcessing
    │     → engineer_spatial_features() → 空间特征工程
    │     output_key: "processed_data"
    │
    ├── AnalysisQualityLoop (max 3 轮)
    │     ├── DataAnalysis
    │     │     → drl_model() → FFI 破碎度优化方案
    │     └── QualityChecker
    │           → 验证结果完整性，不通过则重试
    │     output_key: "analysis_report"
    │
    ├── DataVisualization
    │     → generate_choropleth_map() → 交互式专题地图
    │
    └── DataSummary
          → 生成决策报告 + GeoJSON layer_control 元数据
          output_key: "final_summary"
    │
    ▼
⑥ 前端接收
   → ChatPanel 显示报告
   → MapPanel 渲染 GeoJSON 图层
   → DataPanel 展示分析数据
```

---

## 用户自助扩展闭环

用户可以在四个层面扩展系统，形成完整闭环：

```
┌──────────────────────────────────────────┐
│     ① 扩展 Tool 层                       │
│  在"能力"Tab 创建声明式工具模板            │
│  (http_call / sql_query / chain / ...)   │
│  每用户最多 50 个，支持评分 + 克隆 + 版本   │
└──────────────┬───────────────────────────┘
               │ 工具注入 (UserToolset)
               ▼
┌──────────────────────────────────────────┐
│     ② 扩展 Skill 层                      │
│  在"能力"Tab 创建自定义 Agent              │
│  (指令 + 40 个 Toolset 可选 + 触发词)     │
│  支持团队共享、评分、克隆、审批             │
└──────────────┬───────────────────────────┘
               │ Agent 编排
               ▼
┌──────────────────────────────────────────┐
│     ③ 扩展 Pipeline 层                   │
│  在"工作流"Tab 可视化编排 (ReactFlow DAG) │
│  拖入 Skill Agent 节点组成 DAG            │
│  定义依赖关系、参数传递、Cron 调度         │
└──────────────┬───────────────────────────┘
               │ MCP 集成
               ▼
┌──────────────────────────────────────────┐
│     ④ 扩展 MCP 层                        │
│  注册外部 MCP 服务器（stdio/sse/http）    │
│  工具自动聚合进 Agent，按管线分配          │
│  工具规则引擎自动选择最佳工具              │
└──────────────────────────────────────────┘
```

**Tool → Skill → Pipeline → MCP**：四层自助扩展，全栈闭环。

---

## A2A 协议（Agent-to-Agent）

系统支持 A2A 协议 v0.2，允许外部 Agent 通过标准接口调用：

```python
build_agent_card(base_url)  → 5 个技能的 Agent Card
execute_a2a_task(message, caller_id) → {status, result_text, files, tokens}
```

5 个公告技能：Spatial Analysis、Data Governance、Land Optimization、GIS Visualization、Data Fusion。

---

## 连接器架构（Connectors）

`data_agent/connectors/` 提供 10 种数据连接器，统一 `BaseConnector` 接口 + `ConnectorRegistry` 注册发现：

| 连接器 | 协议 | 说明 |
|--------|------|------|
| WFSConnector | OGC WFS | Web Feature Service |
| WMSConnector | OGC WMS | Web Map Service |
| STACConnector | STAC | 时空资产目录 |
| OGCAPIConnector | OGC API | Records + Features |
| ArcGISRESTConnector | Esri REST | FeatureServer / MapServer |
| CustomAPIConnector | HTTP | 通用 REST 端点 |
| DatabaseConnector | SQL | PostgreSQL / MySQL / SQL Server |
| ObjectStorageConnector | S3/GCS/Azure | 云对象存储 |
| ReferenceDataConnector | REST | 参考数据服务 |
| SaveMyselfConnector | HTTP | 第三方集成 |

---

## DRL 优化引擎（`drl_engine.py`）

深度强化学习优化引擎，支持 7 种场景：

| 场景 | 说明 |
|------|------|
| land_use | 土地利用优化（默认） |
| farmland_forest | 耕地↔林地配对交换 |
| ecological | 生态适宜性优化 |
| urban_planning | 城市规划布局 |
| road_network | 交通网络优化（v23.0） |
| public_facility_layout | 公共设施布局（v23.0） |
| custom | 用户自定义场景 |

- `MaskablePPO` (sb3_contrib) + 自定义 `ParcelScoringPolicy`
- 硬约束 `min_retention_rate`（action mask）+ 软约束 `budget_cap`/`max_area_cap`（reward penalty）
- NSGA-II Pareto 多目标优化
- DRL 动画：GIF 优化过程回放 + 前后对比 PNG

---

## 遥感智能体（Phase 1-3）

### Phase 1（v16.0）
空间约束 fact-check + 光谱指数计算 + LULC 分类

### Phase 2（v22.0）
变化检测（3 方法）+ Mann-Kendall 趋势 + 断点检测 + 证据评估

### Phase 3（v22.0）
空间约束 fact-check + 交叉验证 + 多 Agent Debate + 代码沙箱

RS 知识库：5 光谱指数 + 3 分类体系 + 3 处理流程模板（`rs_experience_pool.yaml`）

---

## L4 自主监控（v22.0）

- `DataLakeMonitor`：持续监控数据湖变化
- `IntrinsicMotivation`：ε-greedy 内在动机驱动自主探索

---

## 具身执行接口（v23.0）

`embodied.py` — `BaseExecutor` ABC + MockUAV/Satellite 执行器 + 注册表。为无人机/卫星等物理设备预留标准化接口。

---

## 离线模式（v23.0）

- Service Worker (`sw.js`) 缓存地图瓦片/静态资源/用户数据
- Lite 模式启动：`app.py _LITE_MODE` 标志 + 治理/优化路由降级到 General
- DuckDB 本地数据库初始化
- 可选依赖分组：`pyproject.toml [lite]/[full]/[dev]`

---

## 标注协同（v23.0）

`annotation_ws.py` — WebSocket 单实例广播 + REST 集成，支持多用户实时标注协同。

---

## 数量汇总

| 维度 | 数量 |
|------|------|
| LlmAgent 实例 | 19（+ 工厂函数动态生成） |
| SequentialAgent | 7 |
| ParallelAgent | 2 |
| LoopAgent | 3 |
| 工厂函数 | 9 |
| Toolset 类 | 40 |
| 内置工具函数 | 215+ |
| 内置 ADK Skill | 25 |
| Prompt YAML | 5（general/governance/optimization/planner/multi_agent） |
| 语义算子 | 4（Clean/Integrate/Analyze/Visualize） |
| 用户工具模板类型 | 5 |
| MCP 传输协议 | 3（stdio/sse/streamable_http） |
| 子系统 | 4 |
| 连接器 | 10 |
| REST API 端点 | 280 |
| API 路由模块 | 23（`api/` 目录） |
| 数据标准文件 | 9 |
| DB 迁移 | 64（001-057 + 补丁） |
| 测试文件 | 171 |
| 测试用例 | 3588+ |
| 因果推断方法 | 14（3 角度） |
| 融合策略 | 10 |
| 内置评估器 | 15 |
| DRL 优化场景 | 7（含 road_network + public_facility_layout） |

---

*本文档基于 GIS Data Agent v23.0 (ADK v1.27.2, 2026-04-10) 架构刷新。*
