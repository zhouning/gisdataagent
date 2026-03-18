# GIS Data Agent Technical Architecture Guide

**Version**: v12.0 &nbsp;|&nbsp; **Framework**: Google ADK v1.26.0 &nbsp;|&nbsp; **Date**: 2026-03-18

---

## 目录

1. [总体架构](#1-总体架构)
2. [语义意图路由层](#2-语义意图路由层)
3. [多管线 Agent 编排](#3-多管线-agent-编排)
4. [工具体系](#4-工具体系)
5. [多租户与用户隔离](#5-多租户与用户隔离)
6. [认证与 RBAC](#6-认证与-rbac)
7. [前端三面板架构](#7-前端三面板架构)
8. [REST API 层](#8-rest-api-层)
9. [数据融合引擎](#9-数据融合引擎)
10. [地理知识图谱](#10-地理知识图谱)
11. [深度强化学习优化引擎](#11-深度强化学习优化引擎)
12. [语义层与数据目录](#12-语义层与数据目录)
13. [ADK Skills 框架](#13-adk-skills-框架)
14. [工作流引擎](#14-工作流引擎)
15. [MCP Hub](#15-mcp-hub)
16. [多模态输入处理](#16-多模态输入处理)
17. [可观测性与运维](#17-可观测性与运维)
18. [数据库架构](#18-数据库架构)
19. [评测体系](#19-评测体系)
20. [CI/CD 流水线](#20-cicd-流水线)
21. [架构缺陷与改进建议](#21-架构缺陷与改进建议)

---

## 1. 总体架构

### 1.1 系统定位

GIS Data Agent 是一个基于大语言模型的地理空间智能分析平台。它接收用户的自然语言指令（文本、语音、图片、PDF），通过**语义意图路由**将请求分发到三条专业化 Agent 管线中执行，最终以交互式地图、数据表格、分析报告等形式返回结果。

### 1.2 分层架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     Frontend (React SPA)                        │
│   ChatPanel(320px) │ MapPanel(flex-1) │ DataPanel(360px)        │
├─────────────────────────────────────────────────────────────────┤
│                    REST API Layer (92 endpoints)                │
│   Starlette Routes → mount before Chainlit catch-all           │
├─────────────────────────────────────────────────────────────────┤
│                    Chainlit Application Layer                   │
│   Auth Callbacks │ Session Mgmt │ File Upload │ Intent Router   │
├─────────────────────────────────────────────────────────────────┤
│                    Semantic Intent Router                       │
│   Gemini 2.0 Flash → OPTIMIZATION│GOVERNANCE│GENERAL│AMBIGUOUS │
├────────────┬────────────┬─────────────┬────────────────────────┤
│ Optimization│ Governance │   General   │      Planner           │
│  Pipeline   │  Pipeline  │  Pipeline   │  (Dynamic Orchestrator)│
│ Sequential  │ Sequential │ Sequential  │  LlmAgent + Sub-agents │
├────────────┴────────────┴─────────────┴────────────────────────┤
│                    Tool Execution Layer                         │
│   23 BaseToolset (130+ tools) │ 18 ADK Skills │ MCP Hub        │
│   UserToolset (user-defined declarative tools)                 │
├─────────────────────────────────────────────────────────────────┤
│                    Data & Infrastructure                        │
│ PostgreSQL+PostGIS │ Fusion Engine │ DRL Engine │ Knowledge Graph│
│ Semantic Layer │ Data Catalog │ Token Tracker │ Audit Logger     │
└─────────────────────────────────────────────────────────────────┘
```

### 1.3 核心技术栈

| 层级 | 技术 | 版本 |
|------|------|------|
| Agent 框架 | Google ADK | v1.26.0 |
| LLM（Agent） | Gemini 2.5 Flash / 2.5 Pro | Latest |
| LLM（路由） | Gemini 2.0 Flash | Latest |
| 前端 | React 18 + TypeScript + Vite | 18.3 / 5.7 / 6.3 |
| 地图渲染 | Leaflet.js + deck.gl + MapLibre GL | 1.9 / 9.2 / 5.19 |
| 后端 | Chainlit + Starlette | Latest |
| 数据库 | PostgreSQL 16 + PostGIS 3.4 | 16 / 3.4 |
| GIS | GeoPandas, Shapely, Rasterio, PySAL | Latest |
| 机器学习 | PyTorch, Stable Baselines 3, Gymnasium | Latest |
| Python | CPython (Anaconda) | 3.13.7 |

### 1.4 请求生命周期

```
用户消息 (文本 + 文件上传)
    │
    ▼
[文件处理] ZIP 解压、多模态分类 (IMAGE/PDF/SPATIAL)
    │
    ▼
[上下文注入] 上轮结果 + 空间记忆 + 语义层 + 分析视角 + ArcPy 可用性
    │
    ▼
[语义意图路由] classify_intent() → Gemini 2.0 Flash
    │  返回: (intent, reason, router_tokens, tool_categories)
    ▼
[RBAC 鉴权] viewer 角色禁止访问 Governance/Optimization
    │
    ▼
[管线调度] → data_pipeline / governance_pipeline / general_pipeline / planner_agent
    │
    ▼
[ADK Runner 执行] Agent 链式调用 → 工具执行 → Token 记录
    │
    ▼
[结果聚合] layer_control 元数据注入 → pending_map_updates 缓存
    │
    ▼
[前端渲染] ChatPanel 轮询 /api/map/pending → MapPanel 更新地图
```

### 1.5 代码组织

```
data_agent/
├── app.py              # 入口 (3267 行): Chainlit UI, RBAC, 文件上传, 管线调度
├── agent.py            # Agent 定义 (625 行): 管线组装, 工厂函数
├── intent_router.py    # 语义路由 (153 行): classify_intent, 从 app.py 提取
├── pipeline_helpers.py # 管线辅助 (284 行): 工具说明, 进度渲染, 错误分类
├── pipeline_runner.py  # 无头执行器 (360 行): run_pipeline_headless
├── frontend_api.py     # REST API (2330 行): 92 个端点
├── auth.py             # 认证 (454 行): 密码/OAuth/暴力破解防护
├── user_context.py     # 上下文传播 (36 行): ContextVar
├── db_engine.py        # 数据库单例 (40 行): 连接池
├── custom_skills.py    # 自定义技能 (472 行): CRUD, 验证, Agent 工厂
├── user_tools.py       # 用户自定义工具 (407 行): 声明式模板 CRUD
├── user_tool_engines.py # 工具执行引擎 (361 行): http_call, sql_query, 动态 FunctionTool 构建
├── capabilities.py     # 能力发现 (98 行): 聚合内置技能 + 工具集元数据
├── prompts/            # 3 个 YAML: optimization, planner, general
├── toolsets/            # 23 个 BaseToolset 子类 (25 .py 文件, 含 UserToolset)
├── skills/             # 18 个 ADK Skill 目录
├── fusion/             # 22 模块: 多模态数据融合
├── evals/              # 4 管线评测集
├── semantic_layer.py   # 语义目录 (1551 行)
├── data_catalog.py     # 数据资产目录 (1057 行)
├── knowledge_graph.py  # 地理知识图谱 (625 行)
├── drl_engine.py       # DRL 优化引擎 (557 行)
├── workflow_engine.py  # 工作流引擎 (1166 行): 顺序 + DAG 执行 + custom_skill 步骤
├── mcp_hub.py          # MCP Hub 管理器 (773 行)
├── multimodal.py       # 多模态输入 (186 行)
├── failure_learning.py # 失败学习 (158 行)
├── observability.py    # 可观测性 (141 行)
├── health.py           # 健康检查 (282 行)
├── report_generator.py # 报告生成 (304 行)
├── token_tracker.py    # Token 追踪 (233 行)
├── audit_logger.py     # 审计日志 (365 行)
├── memory.py           # 空间记忆 (409 行)
└── test_*.py           # 92 个测试文件 (2100+ 测试)
```

---

## 2. 语义意图路由层

### 2.1 设计目标

传统 GIS 系统依赖菜单/表单驱动。本系统通过 LLM 对自然语言进行语义分类，实现"说什么做什么"的交互范式。路由层是整个系统的入口决策点，需要同时满足：低延迟（使用 Flash 模型）、多模态支持（文本+图片+PDF）、可解释性（返回分类理由）。

### 2.2 路由实现 (`app.py` classify_intent)

```python
async def classify_intent(user_text: str, multimodal_parts=None) -> tuple:
    """
    Returns: (intent, reason, router_tokens, tool_categories)
    - intent: OPTIMIZATION | GOVERNANCE | GENERAL | AMBIGUOUS
    - reason: 分类理由（用于前端展示路由信息卡片）
    - router_tokens: 路由器消耗的 Token 数
    - tool_categories: 工具类别集合（用于动态工具过滤）
    """
```

路由器使用 Gemini 2.0 Flash（成本最低、延迟最低的模型），通过结构化 Prompt 要求模型返回 JSON 格式的分类结果。

**工具类别（v7.5.6 引入）**：路由器不仅返回意图，还返回工具类别（如 `spatial_processing`、`poi_location`、`remote_sensing`），用于在 General 管线中动态过滤可用工具集，减少 Token 消耗并防止工具幻觉。

### 2.3 多模态路由

路由器支持三种输入模态的组合：

| 模态 | 处理方式 | Gemini 输入 |
|------|---------|------------|
| 文本 | 直接传入 | `types.Part(text=...)` |
| 图片 | PIL 缩放至 512px, JPEG 编码 | `types.Part(inline_data=Blob)` |
| PDF | pypdf 文本提取 (max 20 页) | 文本追加到 Prompt |

### 2.4 路由错误处理

路由器异常时 fallback 到 GENERAL 管线。这是一个务实的设计选择——GENERAL 管线具有最广的工具覆盖范围，可以处理大多数请求。

### 2.5 架构评价

**优势**：
- 选用 Flash 模型做路由，将昂贵的 Pro 模型留给需要深度推理的 Agent，成本结构合理
- 路由器返回 `tool_categories` 实现了工具的动态裁剪，比静态配置更灵活

**不足**：
- 路由器 Token 消耗未持久化到 `token_tracker`，存在计费盲区
- 路由器的 Prompt 与意图列表硬编码在 `app.py` 中，新增管线需要修改路由器 Prompt，无法通过配置扩展
- 多模态上下文注入（上轮结果、记忆、语义层、ArcPy 可用性等 5+ 来源）拼接到路由 Prompt，存在 Token 溢出风险，缺乏总长度保护

---

## 3. 多管线 Agent 编排

### 3.1 管线架构总览

系统定义了四条独立管线，每条对应特定的业务场景：

| 管线 | 类型 | 模型 | 用途 |
|------|------|------|------|
| `data_pipeline` | SequentialAgent | Flash | 空间布局优化（DRL） |
| `governance_pipeline` | SequentialAgent | Flash | 数据质量治理审计 |
| `general_pipeline` | SequentialAgent | Flash | 通用空间分析 |
| `planner_agent` | LlmAgent | Flash | 动态编排（含子 Agent + 工作流） |

### 3.2 Optimization Pipeline

```
ParallelDataIngestion (Exploration ‖ SemanticPreFetch)
    ↓
DataProcessing (特征工程, GIS 操作, 融合)
    ↓
AnalysisQualityLoop (Analysis → QualityChecker, max 3 次)
    ↓
DataVisualization (专题图, 气泡图, 交互式地图)
    ↓
DataSummary (决策报告)
```

特点：
- 并行数据摄入：数据探索与语义预取同时进行，减少延迟
- 质量保证循环：LoopAgent 模式，最多 3 轮迭代确保输出质量

### 3.3 Governance Pipeline

```
GovExploration (审计, 拓扑, 字段标准)
    ↓
GovProcessing (修复, 地理编码, 融合)
    ↓
GovernanceReportLoop (Report → Checker, max 3 次)
```

特点：
- Reporter 使用 Gemini 2.5 Pro（Premium 模型），因为治理报告需要更强的综合推理能力
- 质量检查器验证报告的完整性和 DRL 优化效果

### 3.4 General Pipeline

```
GeneralProcessing (全工具集, 动态过滤)
    ↓
GeneralViz (热力图, 专题图, 交互式地图)
    ↓
GeneralSummaryLoop (Summary → Checker, max 3 次)
```

特点：
- 通过 `intent_tool_predicate` 根据路由器返回的 `tool_categories` 动态过滤工具
- 预定义工具子集：`_AUDIT_TOOLS`、`_TRANSFORM_TOOLS`、`_DB_READ`、`_DATALAKE_READ`

### 3.5 Planner Agent（动态编排器）

```
Planner (LlmAgent)
├── 子 Agent: PlannerExplorer, PlannerProcessor, PlannerAnalyzer,
│             PlannerVisualizer, PlannerReporter
├── 工作流: ExploreAndProcess, AnalyzeAndVisualize
└── 工具: 19 Toolsets + SkillBundles + MCP Hub + Fusion + KnowledgeGraph
```

Planner 是最复杂的管线。它不走固定的 Sequential 顺序，而是由 LLM 根据任务需求动态选择调用哪个子 Agent 或工作流。两个打包工作流（`ExploreAndProcess`、`AnalyzeAndVisualize`）将常见序列从 8 跳减少到 3 跳，降低路由开销。

### 3.6 ADK 单父约束的工厂函数解法

ADK 框架强制要求每个 Agent 实例只能有一个父级。当多条管线需要复用相同配置的 Agent 时，不能共享实例。

解决方案：4 个工厂函数（`_make_planner_explorer`、`_make_planner_processor`、`_make_planner_analyzer`、`_make_planner_visualizer`）创建配置相同但实例独立的 Agent。

```python
def _make_planner_explorer(name: str = "PlannerExplorer") -> LlmAgent:
    return LlmAgent(
        name=name,
        model=get_model_for_tier("standard"),
        instruction=prompts["planner"]["explorer_instruction"],
        tools=[ExplorationToolset(), DatabaseToolset(), ...],
    )
```

### 3.7 模型分层策略

```python
MODEL_FAST     = "gemini-2.0-flash"     # 路由器, 质量检查器, 语义预取
MODEL_STANDARD = "gemini-2.5-flash"     # 主 Agent（默认）
MODEL_PREMIUM  = "gemini-2.5-pro"       # Reporter（复杂综合推理）
```

通过 ContextVar `current_model_tier` 支持按请求粒度的模型覆盖，使管理员或高级用户可以在特定场景使用更强的模型。

### 3.8 质量保证循环

```
Generator Agent (e.g., DataAnalysis)
    ↓ 产出 analysis_report
Critic Agent (QualityChecker)
    ↓ 调用 approve_quality 工具评估
    ├── 通过 → 输出传递给下一个 Agent
    └── 不通过 → 输出修改意见, LoopAgent 重试 (max 3 次)
```

质量检查器验证的维度包括：结果完整性、DRL 优化效果（是否产生了地块置换）、遥感/统计分析值域合理性（如 NDVI、Moran's I 的取值范围）。

### 3.9 架构评价

**优势**：
- SequentialAgent + LoopAgent 组合既保证了执行顺序的可预测性，又引入了质量自检闭环
- Planner 的子工作流打包模式有效减少了 LLM 路由跳数

**不足**：
- 工厂函数增殖：每新增一种可复用 Agent 就要新增一个工厂函数，维护负担随管线数量线性增长
- 工具过滤列表（`_AUDIT_TOOLS` 等）硬编码为模块级常量，新增工具需修改代码
- 管线无故障恢复机制：子 Agent 失败时 LoopAgent 会重试，但没有熔断器（Circuit Breaker），极端情况下可能在错误路径上反复消耗 Token
- Planner 的工具空间过大（19 Toolsets + 5 子 Agent + 2 工作流），存在路由混乱或工具冲突的风险

---

## 4. 工具体系

### 4.1 BaseToolset 模式

所有工具集继承自 `google.adk.tools.base_toolset.BaseToolset`：

```python
class ExplorationToolset(BaseToolset):
    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
```

关键设计点：
- `tool_filter` 参数允许按名称裁剪暴露的工具，同一 Toolset 类在不同管线中可暴露不同工具子集
- `get_tools()` 是异步方法，支持动态生成工具列表

### 4.2 工具集清单（23 个 BaseToolset + 附加）

| 类别 | Toolset | 工具数 | 核心能力 |
|------|---------|--------|---------|
| **数据探索** | ExplorationToolset | 6 | 数据画像, 拓扑审计, 字段标准检查, 一致性检查 |
| **GIS 处理** | GeoProcessingToolset | 18+8 | 镶嵌, 裁剪, 缓冲, 叠加, 聚类; 可选 ArcPy 工具 |
| **位置服务** | LocationToolset | 5 | 地理编码, POI 检索, 行政区划, 逆地理编码 |
| **分析** | AnalysisToolset | 4 | DRL 优化, FFI 计算, Pareto 分析 |
| **可视化** | VisualizationToolset | 15 | 交互式地图, 专题图, 气泡图, 3D, PNG 导出, 图层控制 |
| **数据库** | DatabaseToolset | 8 | SQL 查询, 表描述, 导入/导出, 语义上下文 |
| **文件** | FileToolset | 6 | 用户文件 CRUD |
| **记忆** | MemoryToolset | 4 | 空间记忆的保存/检索/删除 |
| **管理** | AdminToolset | 3 | 用户管理, 审计日志, 系统诊断 |
| **遥感** | RemoteSensingToolset | 8 | NDVI, 栅格分类, DEM/LULC 下载 |
| **空间统计** | SpatialStatisticsToolset | 3 | Moran's I, LISA, Gi* 热点分析 |
| **语义层** | SemanticLayerToolset | 9 | 域浏览, 语义映射, 列等价 |
| **流处理** | StreamingToolset | 5 | 实时数据流, 事件聚合 |
| **团队** | TeamToolset | 8 | 团队 CRUD, 成员管理, 资源共享 |
| **数据湖** | DataLakeToolset | 8 | 资产搜索, 打标, 血缘, 云下载 |
| **MCP Hub** | McpHubToolset | 2 | MCP 服务器状态, 工具列表 |
| **融合** | FusionToolset | 4 | 多源数据融合, 兼容性评估 |
| **知识图谱** | KnowledgeGraphToolset | 3 | 构建/查询/导出地理知识图谱 |
| **知识库** | KnowledgeBaseToolset | 12 | Vertex AI Search 集成 |
| **高级分析** | AdvancedAnalysisToolset | 6 | 高级空间统计, 网络分析 |
| **流域** | WatershedToolset | 3 | 流域提取, DEM 处理 |
| **用户自定义** | UserToolset | 动态 | 用户声明式工具 (http_call, sql_query, file_transform, chain) |

### 4.3 懒加载注册表

`custom_skills.py` 中的 `_RegistryProxy` 实现了延迟加载：

```python
class _RegistryProxy(dict):
    """Dict proxy, 首次访问时才导入 Toolset 类"""
    def __getitem__(self, key):
        return _get_toolset_registry()[key]
```

**设计动机**：19 个 Toolset 依赖大量重型库（GeoPandas、Rasterio、PyTorch 等），模块级导入会显著拖慢启动速度。懒加载将导入延迟到 Agent 实际请求工具时。

### 4.4 工具过滤与技能包

`skill_bundles.py` 定义了 5 个命名工具包，为不同场景预配置工具子集：

```python
AUDIT_TOOLS = ["describe_geodataframe", "check_topology",
               "check_field_standards", "check_consistency"]
TRANSFORM_TOOLS = ["reproject_spatial_data", "engineer_spatial_features"]
DB_READ = ["query_database", "list_tables"]
```

Agent 可以通过 `ExplorationToolset(tool_filter=AUDIT_TOOLS)` 仅暴露审计相关工具。

### 4.5 架构评价

**优势**：
- BaseToolset 模式提供了统一的工具发现和注册接口
- 懒加载注册表显著优化了冷启动性能
- `tool_filter` 机制允许同一 Toolset 在不同管线中暴露不同工具

**不足**：
- 无工具版本控制：工具通过直接 import 引入，无法在运行时切换实现（如 ArcPy 与开源替代方案之间的热切换）
- 工具间缺乏显式依赖声明：例如可视化工具依赖数据探索工具的输出，但这种依赖仅通过 `output_key` 在 Agent 间隐式传递

---

## 5. 多租户与用户隔离

### 5.1 ContextVar 模式

核心设计：使用 Python `contextvars.ContextVar` 实现异步安全的用户身份传播，不修改任何工具函数签名。

```python
# user_context.py (36 行)
current_user_id    = ContextVar('user_id', default='')
current_session_id = ContextVar('session_id', default='')
current_user_role  = ContextVar('role', default='analyst')
current_trace_id   = ContextVar('trace_id', default='')
current_tool_categories = ContextVar('tool_categories', default=set())
current_model_tier = ContextVar('model_tier', default='')
```

**传播链路**：

```
app.py @on_message
    ↓ _set_user_context(user_id, session_id, role)
    ↓ ContextVar.set()
    ↓
Tool Function (e.g., query_database)
    ↓ current_user_id.get() → user_id
    ↓
用途:
  ├── 文件沙箱: uploads/{user_id}/
  ├── 数据库 RLS: SET app.current_user = :user_id
  ├── 审计日志: record_audit(user_id, action, ...)
  └── Token 追踪: record_usage(user_id, ...)
```

### 5.2 文件沙箱

```python
def get_user_upload_dir() -> str:
    """返回 uploads/{user_id}/, 不存在则创建"""
    user_id = current_user_id.get("")
    path = os.path.join(_BASE_UPLOAD_DIR, user_id)
    os.makedirs(path, exist_ok=True)
    return path

def is_path_in_sandbox(path: str) -> bool:
    """验证路径在用户沙箱或共享上传目录内"""
    abs_path = os.path.abspath(path)
    user_dir = os.path.abspath(get_user_upload_dir())
    base_dir = os.path.abspath(_BASE_UPLOAD_DIR)
    return abs_path.startswith(user_dir) or abs_path.startswith(base_dir)
```

所有工具函数的输出文件通过 `_generate_output_path(prefix, ext)` 写入用户沙箱，输入文件通过 `_resolve_path(file_path)` 进行三级路径解析：用户沙箱 → 共享目录 → 云存储 OBS 下载。

### 5.3 数据库级隔离

```python
# database_tools.py
def _inject_user_context(conn):
    """在 SQL 查询前注入用户上下文，为 RLS 做准备"""
    user_id = current_user_id.get("")
    if user_id:
        conn.execute(text("SET app.current_user = :u"), {"u": user_id})
```

### 5.4 架构评价

**优势**：
- ContextVar 方案优雅——零侵入，不需要修改任何工具函数签名
- async 安全：每个异步任务有独立上下文，天然支持并发请求

**不足**：
- **默认值过于宽松**：`current_user_role` 默认 `'analyst'`。如果 ContextVar 未设置（理论上不应发生，但异常路径下可能），工具将以 analyst 权限运行
- **沙箱检查基于字符串前缀匹配**：`abs_path.startswith(user_dir)` 可能被符号链接或特殊路径绕过
- **无过期机制**：ContextVar 持续到异步任务结束，正常情况没问题，但如果任务被复用（事件循环异常），可能泄露上下文

---

## 6. 认证与 RBAC

### 6.1 认证流程

系统支持三种认证方式：

| 方式 | 实现 | 用户自动创建 |
|------|------|------------|
| 密码认证 | PBKDF2-HMAC-SHA256, 100k 迭代 | 需手动注册 |
| OAuth2 | Google / GitHub（条件注册） | 首次登录自动创建 |
| Bot 平台 | 微信/钉钉/飞书 | 首次交互自动创建 |

密码存储格式：`salt$hash`，验证使用 `secrets.compare_digest()` 进行常量时间比较。

### 6.2 RBAC 模型

| 角色 | 权限 |
|------|------|
| `admin` | 全部功能 + 用户管理 + 审计日志 + MCP 管理 |
| `analyst` | 三条管线 + 自定义技能 + 工作流 |
| `viewer` | 仅 General 管线（只读查询） |

RBAC 检查在路由调度前执行：

```python
if user_role == "viewer" and intent in ("OPTIMIZATION", "GOVERNANCE"):
    # 发送权限不足提示, 拒绝请求
```

### 6.3 账户生命周期

- **注册**：校验用户名（3-30 字符, 字母数字下划线）、密码（8+ 字符, 必须含字母和数字）
- **登录**：Chainlit `@cl.password_auth_callback` 回调
- **注销**：级联删除 8 张关联表（token_usage, memories, share_links, team_members, audit_log, annotations, knowledge_bases, app_users）+ 物理删除上传目录

### 6.4 架构评价

**不足**：
- **缺少密码重置**：用户遗忘密码后只能由管理员介入
- **缺少暴力破解防护**：审计日志记录了登录失败，但无账户锁定机制和速率限制
- **DB 降级后门**：数据库不可用时 `authenticate_user()` 接受硬编码的 `admin/admin123`，生产环境有安全风险
- **级联删除脆弱性**：新增关联表时需手动更新 `delete_user_account()` 中的 DELETE 列表，容易遗漏

---

## 7. 前端三面板架构

### 7.1 布局设计

```
┌─────────────────────────────────────────────────────────────┐
│ AppHeader (56px): Logo + Admin 按钮 + 用户菜单               │
├──────────┬─ ─ ─ ─ ┬───────────────────┬─ ─ ─ ─ ┬──────────┤
│ ChatPanel│ Resizer │    MapPanel       │ Resizer │DataPanel │
│ (var)    │ (5px)   │   (flex-1)        │ (5px)   │(var)     │
│          │         │                   │         │          │
│ Messages │  drag   │ 2D: Leaflet.js    │  drag   │ 12 Tabs  │
│ Streaming│         │ 3D: deck.gl +     │         │ Files    │
│ Voice    │         │     MapLibre GL   │         │ CSV      │
│ Upload   │         │ Annotations       │         │ Catalog  │
│ Actions  │         │ Layer Control     │         │ History  │
│          │         │ Basemap Switcher  │         │ Usage    │
│          │         │ Legend            │         │ MCP      │
│          │         │                   │         │ Workflows│
├──────────┴─────────┴───────────────────┴─────────┴──────────┤
```

面板宽度可拖拽调整（240-700px 范围），使用原生 mousedown/mousemove 事件实现，通过 CSS 变量 `--chat-width` 和 `--data-width` 传递。

### 7.2 状态管理

App.tsx（183 行）是状态中枢，所有面板状态通过 props drilling 向下传递：

```typescript
// 地图状态
const [mapLayers, setMapLayers] = useState<MapLayer[]>([]);
const [mapCenter, setMapCenter] = useState<[number, number]>();
const [mapZoom, setMapZoom] = useState<number>();
const [layerControl, setLayerControl] = useState(null);

// 数据状态
const [dataFile, setDataFile] = useState<string>('');

// UI 状态
const [showAdmin, setShowAdmin] = useState(false);
const [chatWidth, setChatWidth] = useState(320);
const [dataWidth, setDataWidth] = useState(360);
```

### 7.3 地图渲染管线

**2D 渲染（Leaflet.js）**：

MapPanel.tsx（685 行）支持 7 种图层类型：
- `point` → CircleMarker
- `line` → Polyline
- `polygon` → GeoJSON
- `choropleth` → 分级设色（breaks + color_scheme）
- `bubble` → 比例圆
- `categorized` → 分类设色
- `heatmap` → 降级为点图层

底图切换：CartoDB (Light/Dark), OpenStreetMap, 高德, 天地图

**3D 渲染（deck.gl + MapLibre GL）**：

Map3DView.tsx（290 行）支持 4 种 3D 图层：
- `extrusion` → GeoJsonLayer (3D 拉伸多边形)
- `column` → ColumnLayer (3D 柱状图)
- `arc` → ArcLayer (连线)
- `point/bubble` → ScatterplotLayer

自动检测：当图层配置含 `type === 'extrusion'|'column'|'arc'` 或 `extruded`/`elevation_column` 属性时自动切换到 3D 视图。

### 7.4 地图更新传递机制

这是一个被 Chainlit 框架限制所迫的重要设计决策：

**问题**：Chainlit `@chainlit/react-client` v0.3.1 不传递 step-level `metadata`，导致 Agent 产生的地图配置无法通过 WebSocket 直接传递到前端。

**解决方案**：REST 轮询模式

```
app.py: Agent 产生 map_update metadata
    ↓ 存入 pending_map_updates[user_id] (内存字典)
    ↓
ChatPanel: 检测到 loading=false (Agent 完成)
    ↓ fetch GET /api/map/pending
    ↓ 获取地图配置
    ↓ 调用 onMapUpdate() callback
    ↓
MapPanel: 接收新图层, 渲染地图
```

### 7.5 自然语言图层控制

Agent 可以在响应中注入 `layer_control` 元数据，前端解析后执行图层操作：

| 动作 | 效果 |
|------|------|
| `hide` | 隐藏指定图层 |
| `show` | 显示指定图层 |
| `style` | 修改图层样式 |
| `remove` | 移除图层 |
| `list` | 列出当前图层 |

### 7.6 架构评价

**优势**：
- 三面板布局高效利用屏幕空间，ChatPanel 聚焦对话，MapPanel 展示空间结果，DataPanel 提供数据浏览
- 2D/3D 双渲染引擎覆盖了平面分析和立体可视化两种需求

**不足**：
- **Props Drilling 过深**：所有状态从 App.tsx 向下传递，当面板组件层级加深时维护成本增加。应考虑 React Context API 或状态管理库
- **全局回调反模式**：地图标注的操作按钮使用 `window.__resolveAnnotation()` / `window.__deleteAnnotation()` 全局函数，类型不安全且易碎
- **CSS 架构**：2291 行的单一 `layout.css` 文件，无 CSS Modules 或 CSS-in-JS 方案，存在样式冲突风险
- **缺少 Error Boundaries**：主要区域（地图、数据面板、聊天）缺少 React Error Boundary，单个组件崩溃会导致整个应用白屏
- **REST 轮询属于 Workaround**：本质上是 Chainlit 客户端库的限制导致的，如果未来 Chainlit 支持完整的 metadata 传递，应替换为 WebSocket 直推

---

## 8. REST API 层

### 8.1 路由挂载策略

```python
def mount_frontend_api(app: Starlette):
    """将 REST 路由插入到 Chainlit catch-all /{full_path:path} 之前"""
    routes = [
        Route("/api/catalog", catalog_list, methods=["GET"]),
        Route("/api/map/pending", get_pending_map_update, methods=["GET"]),
        # ... 44 个端点
    ]
    # 插入到 Chainlit 路由表的前面
    app.routes = routes + app.routes
```

这是一个关键的架构决策：Chainlit 挂载了一个 catch-all 路由 `/{full_path:path}` 来服务其前端资源。如果 REST 路由放在后面，所有 `/api/*` 请求都会被 Chainlit 拦截。

### 8.2 端点分类（92 个）

| 类别 | 端点数 | 代表端点 |
|------|--------|---------|
| 数据目录 | 3 | `/api/catalog`, `/api/catalog/{id}/lineage` |
| 语义层 | 2 | `/api/semantic/domains`, `/api/semantic/hierarchy/{domain}` |
| 管线历史 | 1 | `/api/pipeline/history` |
| 用户 | 3 | `/api/user/token-usage`, `/api/user/account`, `/api/user/analysis-perspective` |
| 标注 | 4 | `/api/annotations` CRUD |
| 管理 | 4 | `/api/admin/users`, `/api/admin/metrics/summary` |
| MCP Hub | 10 | `/api/mcp/servers` CRUD + toggle + reconnect + test + share |
| 工作流 | 8 | `/api/workflows` CRUD + execute + history |
| 分析 | 5 | `/api/analytics/latency`, `/api/analytics/tool-success` |
| 会话 | 2 | `/api/sessions` list + delete |
| 地图 | 1 | `/api/map/pending` |
| 配置 | 1 | `/api/config/basemaps` |

### 8.3 认证模式

所有端点使用 JWT Cookie 认证：

```python
async def _get_user_from_request(request: Request) -> dict | None:
    """从 Chainlit JWT Cookie 中提取用户信息"""
    token = request.cookies.get("access_token")
    if not token:
        return None
    payload = decode_jwt(token)
    return {"username": payload["sub"], "role": payload.get("role", "analyst")}
```

管理端点通过 `_require_admin()` 守卫增强权限检查。

### 8.4 架构评价

**不足**：
- 44 个端点全部定义在单个 `frontend_api.py`（2165 行）中，违反了单一职责原则。建议按功能域拆分为独立模块
- 缺少请求验证中间件：输入参数验证分散在各个处理函数中，没有统一的 schema 验证层（如 Pydantic models）
- 缺少 API 版本控制：所有端点均为 `/api/...`，未来 breaking changes 无法通过 `/api/v2/...` 平滑迁移

---

## 9. 数据融合引擎

### 9.1 架构设计

融合引擎是系统中最复杂的子系统之一，从单一 `fusion_engine.py` 重构为 22 个聚焦模块的包结构：

```
fusion/
├── models.py        # 数据模型: FusionSource, CompatibilityReport, FusionResult
├── constants.py     # 策略矩阵, 单位表, 阈值
├── profiling.py     # 数据源画像 (vector/raster/tabular/point_cloud/PostGIS)
├── matching.py      # 4 级语义字段匹配
├── compatibility.py # CRS/空间重叠/时间对齐评估
├── alignment.py     # 单位转换, 列冲突解决, CRS 重投影
├── execution.py     # 策略选择, 多源编排, 自动路由
├── validation.py    # 10 维质量验证
├── io.py            # 大数据检测, 分块 I/O, 惰性物化
├── raster_utils.py  # 栅格重投影和重采样
├── db.py            # 融合操作数据库记录
└── strategies/      # 10 个融合策略实现
    ├── registry.py
    ├── spatial_join.py
    ├── overlay.py
    ├── nearest_join.py
    ├── attribute_join.py
    ├── zonal_statistics.py
    ├── point_sampling.py
    ├── band_stack.py
    ├── time_snapshot.py
    ├── height_assign.py
    └── raster_vectorize.py
```

### 9.2 融合流水线

```
用户上传 2+ 数据源
    ↓
profile_source() → FusionSource 画像
    ↓
assess_compatibility() → CompatibilityReport
    │  (CRS 兼容性, 空间重叠 IoU, 时间对齐, 字段匹配)
    ↓
align_sources() → 对齐数据
    │  (CRS 重投影, 单位转换, 列冲突解决)
    ↓
execute_fusion(strategy='auto') → _auto_select_strategy()
    │  规则式评分 (IoU, 几何类型, 行数比, 用户提示)
    ↓
策略函数执行 (spatial_join / overlay / zonal_statistics / ...)
    ↓
validate_quality() → 10 维质量评分
    ↓
FusionResult (output_path, provenance, alignment_log)
```

### 9.3 四级语义字段匹配

```
Level 1: 精确匹配 (score=1.0) — 字段名相同
Level 2: 等价组匹配 (score=0.8) — 如 [area, 面积, zmj] 属于同一等价组
Level 3: 嵌入匹配 (score≥0.78) — Gemini text-embedding-004 向量相似度
Level 4: 模糊匹配 (score=0.5-0.7) — SequenceMatcher 字符串相似度
```

### 9.4 策略选择

v7.1 将 LLM 路由替换为规则式评分，基于以下维度：
- IoU（空间重叠比）
- 几何类型组合（矢量×矢量、矢量×栅格等）
- 行数比
- 用户提示中的关键词

策略矩阵将数据类型对映射到可用策略列表：
- vector + vector → [spatial_join, overlay, nearest_join, attribute_join]
- vector + raster → [zonal_statistics, point_sampling, height_assign]
- raster + raster → [band_stack]

### 9.5 PostGIS 推算下沉（v7.1）

对于大数据集（行数 > 阈值），融合操作可直接在 PostGIS 中执行 SQL，减少内存占用：

```python
if both_sources_in_postgis and row_count > PUSHDOWN_THRESHOLD:
    result = _execute_postgis_fusion(source_a, source_b, strategy)
```

### 9.6 架构评价

**优势**：
- 包结构清晰，职责分离——画像、匹配、对齐、执行、验证各司其职
- 四级语义匹配从精确到模糊逐级降级，兼顾准确性和召回率
- PostGIS 推算下沉是应对大数据场景的正确方向

**不足**：
- 嵌入 API 依赖 Gemini text-embedding-004，模块级缓存无 TTL，故障降级到跳过嵌入匹配
- `_MAX_SPATIAL_PAIRS = 1000` 的空间对爆炸保护是硬上限截断，对被截断的数据没有告知或补偿策略
- 多源融合按固定顺序（vector → raster → tabular）两两配对，不一定是最优执行计划
- 单位转换表硬编码 + 目录驱动混合，领域特定单位可能遗漏

---

## 10. 地理知识图谱

### 10.1 设计

`knowledge_graph.py`（625 行）基于 NetworkX DiGraph 构建内存中的地理知识图谱：

```python
class GeoKnowledgeGraph:
    def __init__(self):
        self._graph = nx.DiGraph()
        self._spatial_index = None  # STRtree 空间索引

    def build_from_geodataframe(self, gdf, entity_type=None):
        """从 GeoDataFrame 构建节点 + 自动检测空间关系"""

    def merge_layer(self, gdf, entity_type=None):
        """跨图层关系检测（新节点 vs 已有节点）"""

    def query_neighbors(self, node_id, depth=1):
        """自我图遍历至指定深度"""

    def query_path(self, source_id, target_id):
        """最短路径（无向视图）"""
```

### 10.2 空间关系检测

| 关系类型 | 检测方法 |
|---------|---------|
| `adjacent_to` | STRtree 索引 + 边界 touch/共边检测 |
| `contains` / `within` | `geom.contains()` 有向边 |
| `overlaps` | 几何相交判定 |
| `nearest_to` | 最近邻检测 |

### 10.3 架构评价

**不足**：
- **纯内存**：无持久化到图数据库（Neo4j 等），大数据集受内存限制
- **O(n²) 空间对检测**：`_MAX_SPATIAL_PAIRS = 1000` 截断处理是权宜之计
- **WKT 存储**：几何体序列化为 WKT 字符串供 JSON 存储，丧失了空间索引能力
- **无时序建模**：关系是静态的，不支持时序变化（如土地利用变化序列）
- **实体类型检测基于关键词启发式**：可能误分类领域特定实体类型

---

## 11. 深度强化学习优化引擎

### 11.1 Gymnasium 环境

`drl_engine.py`（557 行）实现 `LandUseOptEnv`：

| 属性 | 描述 |
|------|------|
| **状态空间** | 每地块特征（坡度、面积、邻域均值坡度）+ 全局指标（耕地/林地数、破碎度） |
| **动作空间** | 离散（选择可交换地块进行耕地↔林地转换） |
| **回合长度** | 200 步 |
| **算法** | MaskablePPO (sb3_contrib) |
| **模型权重** | `scorer_weights_v7.pt` |

### 11.2 奖励函数

```
reward = slope_reward + continuity_reward - count_penalty + pair_bonus

SLOPE_REWARD_WEIGHT  = 1000.0  # 激励高坡度转换
CONT_REWARD_WEIGHT   = 500.0   # 惩罚破碎化
COUNT_PENALTY_WEIGHT = 500.0   # v7 从 100,000 大幅降低（原来淹没梯度信号）
PAIR_BONUS           = 1.0     # 成对策略奖励
```

### 11.3 架构评价

**不足**：
- 无早停机制：无论是否收敛都执行完 200 步
- 奖励权重需要大量调优，v7 的调整说明 v6 的权重设计存在缺陷
- 邻接图 O(n) 计算，约 10k 地块以上的可扩展性未验证

---

## 12. 语义层与数据目录

### 12.1 语义层 (`semantic_layer.py`, 1551 行)

将业务概念映射到空间数据对象，注入到 Agent Prompt 中，解决字段名不可读的问题（如 `zmj` → 面积, `dlmc` → 地类名称）。

**三级架构**：
1. **静态 YAML 目录**：`semantic_catalog.yaml`，GIS 领域知识
2. **DB 动态注册**：`agent_semantic_registry` 表，每列的语义注解（自动发现 + 用户标注）
3. **自定义域**：`agent_semantic_domains` 表，用户自定义层级

**缓存策略**：5 分钟 TTL，按表级别缓存，写操作后调用 `invalidate_semantic_cache(table_name)` 主动失效。

### 12.2 数据目录 (`data_catalog.py`, 1057 行)

统一资产注册表，跨越本地、云存储（OBS）、PostGIS 三种后端：

```sql
CREATE TABLE agent_data_catalog (
    asset_name, asset_type, format,
    storage_backend,  -- local / cloud / postgis
    spatial_extent,   -- JSONB bbox
    crs, srid, feature_count, file_size_bytes,
    creation_tool, source_assets,  -- 血缘
    owner_username, is_shared,
    UNIQUE(asset_name, owner_username, storage_backend)
)
```

工具输出自动注册为数据资产，搜索支持中文 n-gram 分词。

### 12.3 架构评价

**优势**：语义层消除了 Agent 对缩写字段名的猜测，显著提高了工具调用的准确率

**不足**：
- 语义缓存 TTL（5 分钟）对高频写场景可能过短，导致频繁刷新；但对极少写的场景又可能过长
- 数据目录的元数据提取（CRS、bbox、feature_count）在注册时同步执行，大文件可能阻塞

---

## 13. ADK Skills 框架

### 13.1 设计

18 个细粒度场景技能，位于 `data_agent/skills/` 下，每个技能是一个 kebab-case 目录：

```
skills/
├── 3d-visualization/SKILL.md
├── buffer-overlay/SKILL.md
├── coordinate-transform/SKILL.md
├── data-profiling/SKILL.md
├── ecological-assessment/SKILL.md
├── farmland-compliance/SKILL.md
├── geocoding/SKILL.md
├── land-fragmentation/SKILL.md
├── multi-source-fusion/SKILL.md
├── postgis-analysis/SKILL.md
├── site-selection/SKILL.md
├── spatial-clustering/SKILL.md
├── thematic-mapping/SKILL.md
├── topology-validation/SKILL.md
├── knowledge-retrieval/SKILL.md
├── land-fragmentation/SKILL.md
├── multi-source-fusion/SKILL.md
├── postgis-analysis/SKILL.md
├── site-selection/SKILL.md
├── spatial-clustering/SKILL.md
├── team-collaboration/SKILL.md
├── thematic-mapping/SKILL.md
├── topology-validation/SKILL.md
├── advanced-analysis/SKILL.md
└── data-import-export/SKILL.md
```

### 13.2 技能结构

每个 `SKILL.md` 包含 YAML frontmatter + 自然语言指令：

```yaml
---
name: data-profiling           # 必须与目录名一致 (kebab-case)
description: "数据画像与质量评估"
metadata:
  domain: "governance"          # 值必须为字符串（ADK 约束）
  version: "1.0"
  intent_triggers: "profile, 画像, 数据质量, describe"
---

# 数据画像专家技能
## 职责
...
```

### 13.3 三级增量加载

| 级别 | 加载内容 | 时机 |
|------|---------|------|
| L1 | metadata (name, description, domain) | 应用启动 |
| L2 | instructions (完整 Prompt) | 路由匹配时 |
| L3 | resources (附加文件) | 执行时 |

### 13.4 自定义技能 (`custom_skills.py`, 470 行)

用户可以通过 REST API 创建自己的 LLM Agent：

```python
def build_custom_agent(skill: dict) -> LlmAgent:
    """从 DB 记录动态构建 ADK Agent"""
    registry = _get_toolset_registry()
    tools = [registry[name]() for name in skill["toolset_names"]]
    return LlmAgent(
        name=f"CustomSkill_{safe_name}",
        instruction=skill["instruction"],
        model=get_model_for_tier(skill["model_tier"]),
        tools=tools,
    )
```

安全防护：指令文本检查 forbidden patterns（`system:`, `ignore previous`, `<|im_start|>` 等）防止基本的 Prompt 注入。

### 13.5 用户自定义工具 (`user_tools.py` + `user_tool_engines.py`, v12.0 新增)

用户可以通过声明式模板创建自定义工具，无需编写代码：

| 模板类型 | 用途 | 关键配置 |
|---------|------|---------|
| `http_call` | 调用外部 REST API | method, url, headers, body_template, extract_path |
| `sql_query` | 参数化数据库查询 | query, readonly |
| `file_transform` | 文件处理管道 | operations (filter/reproject/buffer/dissolve/clip) |
| `chain` | 串联多个自定义工具 | steps + param_map ($input.X, $prev.result) |

工具定义存储在 `agent_user_tools` 表，通过 `build_function_tool()` 动态构建 ADK `FunctionTool`（使用 `inspect.Signature` 动态构建函数签名）。`UserToolset(BaseToolset)` 将用户工具暴露给 ADK Agent。

安全模型：HTTPS-only URL、参数化 SQL 绑定、DDL 关键词黑名单、文件路径沙箱、chain 最多 5 步。

---

## 14. 工作流引擎

### 14.1 设计 (`workflow_engine.py`, 1166 行)

多步骤管线工作流，支持 CRUD、顺序执行、**DAG 执行**、Cron 调度、Webhook 推送。

**步骤模型**：
```json
{
  "step_id": "step_1",
  "pipeline_type": "general|governance|optimization|custom_skill",
  "prompt": "用户查询",
  "skill_id": null,
  "parameters": {},
  "on_error": "continue|stop"
}
```

### 14.2 执行流程

**顺序执行** (`execute_workflow`):
```
工作流定义 → 验证步骤 → 顺序执行 → 聚合结果 → Webhook 推送
```

**DAG 执行** (`execute_workflow_dag`):
```
工作流定义 → 拓扑排序 → 并行层执行 (asyncio.gather)
  → 条件节点评估 → 跨步骤参数引用 ({step_id.output})
  → 实时状态追踪 → 聚合结果 → Webhook 推送
```

步骤 N 的结果通过上下文传递给步骤 N+1。`custom_skill` 类型步骤通过 `build_custom_agent()` 动态创建 LlmAgent 实例。

### 14.3 架构评价

**优势**：
- 支持顺序执行和 DAG 执行两种模式，DAG 支持拓扑排序 + 并行层 + 条件节点
- `pipeline_type: "custom_skill"` 支持用户自定义 Agent 节点，实现多 Agent 编排
- 参数替换支持跨步骤引用（`{step_id.output}`、`{step_id.files}`）
- Live status tracking 支持前端实时轮询 DAG 执行进度

**不足**：
- Webhook Fire-and-Forget：无重试机制
- Cron 基于内存（APScheduler 在进程内运行，重启后需从 DB 重新同步）

---

## 15. MCP Hub

### 15.1 设计 (`mcp_hub.py`, 773 行)

MCP (Model Context Protocol) Hub 管理器，实现外部工具服务器的配置驱动连接。

**配置加载层级**：
1. PostgreSQL 数据库（主要）→ `agent_mcp_servers` 表
2. YAML 种子文件（回退/初始化）→ `mcp_servers.yaml`
3. 运行时状态 → `McpServerStatus` 字典

### 15.2 三种传输协议

| 协议 | 用途 | 参数 |
|------|------|------|
| `stdio` | 本地进程 | command, args, env, cwd |
| `sse` | HTTP Server-Sent Events | url, headers, timeout |
| `streamable_http` | HTTP 流式 | url, headers, timeout |

### 15.3 安全：Fernet 加密

敏感字段（env 环境变量、headers 中的 API Key）使用 Fernet 对称加密存储：

```python
def _encrypt_dict(d: dict) -> str:
    f = _get_fernet()  # 密钥来自 CHAINLIT_AUTH_SECRET
    return json.dumps({"_enc": f.encrypt(json.dumps(d).encode()).decode()})
```

### 15.4 热重载

支持运行时 CRUD 操作：add/update/remove/toggle/reconnect，无需重启应用。

---

## 16. 多模态输入处理

### 16.1 分类 (`multimodal.py`, 186 行)

```python
class UploadType(Enum):
    SPATIAL   = "spatial"   # .shp, .geojson, .gpkg, .kml, .kmz
    IMAGE     = "image"     # .png, .jpg, .jpeg
    PDF       = "pdf"       # .pdf
    DOCUMENT  = "document"  # .docx, .xlsx
    UNKNOWN   = "unknown"
```

### 16.2 处理策略

| 类型 | 处理 | 输出 |
|------|------|------|
| 图片 | PIL 缩放至 1024px, RGBA→RGB, JPEG(85%) | `types.Part(inline_data=Blob)` |
| PDF | pypdf 文本提取(max 20 页) + 原生 PDF Blob(max 20MB) | 双策略：文本追加到 Prompt + Blob 给 Gemini Vision |
| 空间数据 | ZIP 自动解压, 加载到 GeoDataFrame | 直接进入管线工具处理 |

### 16.3 语音输入

浏览器端 Web Speech API（`zh-CN`/`en-US`），纯前端实现，识别结果作为文本消息发送。

---

## 17. 可观测性与运维

### 17.1 结构化日志 (`observability.py`, 141 行)

```python
class JsonFormatter(logging.Formatter):
    """JSON-lines 格式，包含 trace_id, user_id, 异常上下文"""
```

通过环境变量配置：`LOG_LEVEL`, `LOG_FORMAT` (text|json)。

### 17.2 Prometheus 指标

| 指标 | 类型 | 标签 |
|------|------|------|
| `pipeline_runs` | Counter | pipeline_type, status |
| `tool_calls` | Counter | tool_name, status |
| `auth_events` | Counter | event_type |
| `llm_tokens` | Histogram | pipeline_type, model |
| `tool_duration` | Histogram | tool_name |

### 17.3 健康检查 (`health.py`, 282 行)

K8s 就绪/存活探针：

| 端点 | 检查内容 | 策略 |
|------|---------|------|
| Liveness | 进程存活 | 始终 OK |
| Readiness | 数据库连接（关键）+ 云存储/Redis（可选） | DB down = Not Ready |

启动诊断：ASCII Banner 显示所有子系统状态。

### 17.4 Token 追踪 (`token_tracker.py`, 233 行)

按用户的 LLM 消耗管理：
- 日级限制（默认 20 次/天，admin 无限制）
- 月级 Token 限制（可选）
- 按管线类型的消耗分布

### 17.5 审计日志 (`audit_logger.py`, 365 行)

50+ 审计事件，覆盖认证、数据操作、管线执行、管理操作、MCP 管理、团队协作等。非致命设计——记录失败不会影响业务流程。

### 17.6 失败学习 (`failure_learning.py`, 158 行)

记录工具执行失败模式，在重试时向 Agent 注入历史提示：

```python
def get_failure_hints(tool_name: str) -> list[str]:
    """获取近期未解决的失败提示 (limit 3)"""

def mark_resolved(tool_name: str):
    """工具成功执行后标记历史失败为已解决"""
```

### 17.7 架构评价

**不足**：
- **指标基数爆炸风险**：`tool_name` 和 `pipeline_type` 标签值无界限，大量工具会导致 Prometheus 时间序列膨胀
- **Trace ID 非默认设置**：`current_trace_id` 的 ContextVar 默认为空，依赖 app.py 显式设置。如果某些代码路径未设置，日志缺少追踪能力
- **失败学习仅按用户隔离**：跨用户的共性失败模式（如某工具的系统级 bug）无法聚合学习

---

## 18. 数据库架构

### 18.1 连接管理 (`db_engine.py`, 40 行)

单例 SQLAlchemy Engine，全局共享连接池：

```python
def get_engine() -> Engine | None:
    global _engine
    if _engine is None:
        url = get_db_connection_url()
        if url:
            _engine = create_engine(url,
                pool_size=5,          # 5 个持久连接
                max_overflow=10,      # 高峰期额外 10 个 (总计 max 15)
                pool_recycle=1800,    # 30 分钟回收（防 PostgreSQL 空闲超时）
                pool_pre_ping=True    # 使用前测试连接
            )
    return _engine
```

### 18.2 数据库表清单

系统使用 17+ 张业务表：

| 表 | 用途 |
|---|------|
| `app_users` | 用户账户 |
| `agent_token_usage` | Token 消耗记录 |
| `agent_user_memories` | 空间记忆 |
| `agent_audit_log` | 审计日志 |
| `agent_data_catalog` | 数据资产目录 |
| `agent_semantic_registry` | 语义注册表 |
| `agent_semantic_sources` | 语义数据源 |
| `agent_semantic_domains` | 自定义语义域 |
| `agent_map_annotations` | 地图标注 |
| `agent_mcp_servers` | MCP 服务器配置 |
| `agent_workflows` | 工作流定义 |
| `agent_workflow_runs` | 工作流执行记录 |
| `agent_knowledge_graphs` | 知识图谱 |
| `agent_knowledge_bases` | 知识库 |
| `agent_custom_skills` | 自定义技能 |
| `agent_share_links` | 共享链接 |
| `agent_team_members` | 团队成员 |
| `tool_failures` | 工具失败记录 |
| `agent_user_tools` | 用户自定义工具（声明式模板） |

### 18.3 表创建方式

**无迁移框架**：所有表通过 `ensure_*_table()` 函数在应用启动时 `CREATE TABLE IF NOT EXISTS` 创建。这意味着：
- 新增表容易（添加一个 ensure 函数）
- 修改表结构（加列、改列类型）需要手动 ALTER TABLE 或重建
- 无版本化的 schema 迁移历史

### 18.4 架构评价

**不足**：
- **连接池大小硬编码**：`pool_size=5` 对高并发部署可能不足，对低流量可能浪费
- **延迟初始化**：Engine 在首次 `get_engine()` 调用时创建。如果 DB 启动慢，首个用户请求会承受建连延迟
- **无迁移框架**：缺少 Alembic 等迁移工具，表结构变更依赖手动操作，多环境部署时 schema 一致性难以保证
- **get_engine() 可能返回 None**：当 DB 连接 URL 不可用时返回 None，但并非所有调用方都处理了 None 情况

---

## 19. 评测体系

### 19.1 框架 (`run_evaluation.py`, 437 行)

基于 ADK AgentEvaluator 的多管线评测：

| 管线 | 通过率阈值 |
|------|-----------|
| optimization | 0.6 (60%) |
| governance | 0.6 (60%) |
| general | 0.7 (70%) |
| planner | 0.5 (50%) |

每个管线有独立的测试用例文件（`{pipeline}.test.json`）和指标配置（`test_config.json`）。

### 19.2 评测能力

- 按管线独立评测，失败不中断其他管线
- 从 ADK 断言错误中提取 `metric_name: actual_value < threshold`
- 自动生成改进建议（工具轨迹不匹配、超时、API 错误、幻觉检测）
- Matplotlib 柱状图输出（支持中文字体）
- 输出 `eval_summary.json` + 每管线详情 JSON + PNG 图表

### 19.3 CI 集成

```yaml
# .github/workflows/ci.yml
jobs:
  test:       # Ubuntu + PostGIS, pytest
  frontend:   # Node.js 20, npm build
  evaluate:   # 全管线评测 (main push only)
  route-eval: # PR 快速评测 (general pipeline only, ≥70%)
```

---

## 20. CI/CD 流水线

### 20.1 四阶段流水线

| 阶段 | 触发 | 环境 | 内容 |
|------|------|------|------|
| **test** | 所有推送 | Ubuntu + PostGIS 16-3.4 | 1530+ pytest 测试 |
| **frontend** | 所有推送 | Node.js 20 | React 构建验证 |
| **evaluate** | main 推送 | GOOGLE_API_KEY | 全管线 ADK 评测 |
| **route-eval** | PR | GOOGLE_API_KEY | General 管线快速评测 (≥70%) |

---

## 21. 架构缺陷与改进建议

> **注：本节于 2026-03-18 更新，反映最新修复状态。已修复项标记为 ✅。**

### 21.1 系统级问题

| 编号 | 问题 | 严重性 | 影响 | 状态 |
|------|------|--------|------|------|
| S-1 | `app.py` 3700+ 行，承担路由/认证/文件处理/会话/管线调度等多重职责 | 高 | 可维护性差，改动风险高 | ✅ 已拆分：`intent_router.py`（153 行）+ `pipeline_helpers.py`（284 行）提取，app.py 降至 3267 行 |
| S-2 | 模块级全局变量（`_mcp_started`, `_workflow_scheduler`）非线程安全 | 中 | 并发请求下可能竞态 | 待修复 |
| S-3 | 无数据库迁移框架 | 中 | schema 变更依赖手动操作 | 待修复 |
| S-4 | `frontend_api.py` 2165 行包含 44 个端点 | 中 | 单一职责违反 | 部分缓解（现 2330 行 92 端点，功能更多但结构清晰） |

### 21.2 安全问题

| 编号 | 问题 | 严重性 | 状态 |
|------|------|--------|------|
| SEC-1 | DB 不可用时接受硬编码 admin/admin123 | 高 | ✅ 已修复：DB 不可用时直接拒绝认证 |
| SEC-2 | 无暴力破解防护（无速率限制、无账户锁定） | 中 | ✅ 已修复：per-username 连续 5 次失败锁定 15 分钟 |
| SEC-3 | 沙箱验证基于字符串前缀匹配 | 中 | 待修复 |
| SEC-4 | 自定义技能的 Prompt 注入防护仅为模式匹配 | 中 | 待修复 |
| SEC-5 | ContextVar 默认角色为 analyst | 低 | 待修复 |

### 21.3 可扩展性问题

| 编号 | 问题 | 影响 | 状态 |
|------|------|------|------|
| E-1 | 知识图谱纯内存，无持久化图数据库 | 大数据集无法处理 | 待修复 |
| E-2 | 工作流仅支持顺序执行 | 独立步骤无法并行 | ✅ 已实现：DAG 执行引擎 `execute_workflow_dag()` 支持拓扑排序 + 并行层 + 条件节点 + Custom Skill Agent 节点 |
| E-3 | Cron 调度基于内存 (APScheduler) | 重启后丢失 | 部分缓解（APScheduler 已安装，DB 持久化调度待实现） |
| E-4 | Prometheus 指标标签基数无限制 | 时间序列膨胀 | 待修复 |
| E-5 | 多源融合按固定顺序配对 | 非最优执行计划 | 待修复 |

### 21.4 前端问题

| 编号 | 问题 | 状态 |
|------|------|------|
| F-1 | Props drilling 过深 | 待修复 |
| F-2 | 全局回调函数 (`window.__*`) | 待修复 |
| F-3 | 单文件 CSS (2291 行) | 部分缓解（现 2366 行，功能更多但结构仍是单文件） |
| F-4 | 缺少 Error Boundaries | 待修复 |
| F-5 | REST 轮询地图更新 | 待修复（受限于 Chainlit 客户端） |

### 21.5 测试与质量

| 编号 | 问题 | 状态 |
|------|------|------|
| T-1 | test_knowledge_agent.py 有语法错误被永久排除 | ✅ 已修复：修正 imports、prompts 路径、字符串字面量 |
| T-2 | arcpy_tools.py:424 有语法错误 | ✅ 已修复：删除重复的 `import json` + `try:` 块 |
| T-3 | 评测通过率阈值硬编码 | 待修复 |
| T-4 | 路由器 Token 未纳入 token_tracker | 待修复 |

### 21.6 v12.0 新增能力（2026-03-18）

| 能力 | 描述 |
|------|------|
| **用户自定义技能 (Custom Skills CRUD)** | 前端 CapabilitiesView 支持创建/编辑/删除自定义 LlmAgent（指令+工具集+触发词+模型等级） |
| **用户自定义工具 (User Tools)** | 声明式工具模板：http_call / sql_query / file_transform / chain，DB 存储，动态 FunctionTool 构建，通过 UserToolset 暴露给 ADK Agent |
| **能力浏览 (Capabilities Tab)** | DataPanel 第 12 个 tab，聚合展示内置技能、自定义技能、工具集、自建工具，支持分类过滤和搜索 |
| **多 Agent Pipeline 编排** | WorkflowEditor 新增 Skill Agent 节点类型，用户可可视化编排多个自定义技能为 DAG 工作流 |
| **面板拖拽调整** | 三面板布局支持拖拽分隔条调整宽度（240-700px） |
| **安全加固** | DB 降级后门移除 (SEC-1) + 暴力破解防护 (SEC-2) |
| **代码拆分** | app.py 拆分为 intent_router.py + pipeline_helpers.py (S-1) |

### 21.4 前端问题

| 编号 | 问题 | 建议 |
|------|------|------|
| F-1 | Props drilling 过深 | React Context API 或 Zustand |
| F-2 | 全局回调函数 (`window.__*`) | 事件总线或 Context |
| F-3 | 单文件 CSS (2291 行) | CSS Modules 或 Tailwind |
| F-4 | 缺少 Error Boundaries | 主要区域添加 `<ErrorBoundary>` |
| F-5 | REST 轮询地图更新 | 升级 Chainlit 客户端后改为 WS 直推 |

### 21.5 测试与质量

| 编号 | 问题 | 建议 |
|------|------|------|
| T-1 | test_knowledge_agent.py 有语法错误被永久排除 | 修复或删除 |
| T-2 | arcpy_tools.py:424 有语法错误 | 修复 |
| T-3 | 评测通过率阈值硬编码 | 改为环境变量配置 |
| T-4 | 路由器 Token 未纳入 token_tracker | 应同步记录到使用追踪 |

### 21.6 架构优势总结

尽管存在上述改进空间，系统在以下方面展现了成熟的架构设计：

1. **语义路由 + 多管线分发**：用低成本 Flash 模型做路由、高能力模型做推理，成本结构合理
2. **ContextVar 多租户隔离**：零侵入式的用户上下文传播，是 Python 异步应用的最佳实践
3. **质量保证循环**：Generator + Critic 的 LoopAgent 模式提供了自动质量自检
4. **四级语义字段匹配**：从精确到模糊的渐进式匹配策略，兼顾准确性和鲁棒性
5. **数据融合包结构**：22 模块的清晰职责分离，10 种策略的可扩展注册表
6. **懒加载工具注册表**：显著优化冷启动性能
7. **MCP Hub 热重载**：运行时 CRUD + Fernet 加密，外部工具集成的生产级方案
8. **端到端评测体系**：4 管线独立评测 + CI 集成 + 自动改进建议
9. **无头管线执行器**：解耦 UI，为 CLI/TUI/Bot 等多形态接入奠定基础
10. **失败学习机制**：从历史失败中提取提示注入后续尝试，提升系统韧性

---

*本文档基于 GIS Data Agent v12.0 代码库（2026-03-18）编写。文中所有模块描述、行数、函数签名均来自实际代码审查。§21 已标注各问题的修复状态。*
