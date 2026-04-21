# 智能化数据治理原型分析 × GIS Data Agent 能力匹配度

> Date: 2026-04-21
> 原型文件：`D:\adk\智能化数据治理原型(1).html`（3837 行，双模切换 SPA）
> 分析对象：GIS Data Agent v24.0（`feat/v12-extensible-platform` 分支）
> 核心前提：**GIS Data Agent 作为上层 Agent 提供智能化能力，底层对接已有时空数据治理平台**

---

## 一、原型设计分析

### 1.1 产品形态

双模切换的时空数据治理中台：

- **智能模式**：对话驱动首页（9 个 agent 卡片 + 推荐场景 prompt），输入需求后进入**分屏联动**（左聊天 + 右传统治理页面），agent 操作实时体现在右侧页面
- **传统模式**：还原 Ant Design 风格的治理台（数据汇聚 / 数据开发 / 资产 / 质量 / 安全 / 系统 七大模块，二级菜单三十余项）

### 1.2 核心 9 个智能体

| 智能体 | 职责 | 典型场景 prompt |
|---|---|---|
| 数据汇聚 | 数据源连接/存储/建模/同步/解析 | 请将数据源'人大金仓'中的 gdtb 表同步到核心层的耕地保护目录下 |
| 数据开发 | 开发编排/Notebook/调度任务 | 构建绿地覆盖率模型（xzqh ⊕ ddbh 叠加分析） |
| 数据质检 | 全量质检/趋势统计 | 对 gdtb 进行全量质检（空值/面积=0） |
| 资产管理 | 智能找数/资产地图/分级统计 | 耕地保护资产血缘热度 |
| 数据服务 | API 发布/调用统计 | 行政区划 → RESTful API |
| 数据分析 | 智能问答/仪表盘 | 耕地面积同比变化 |
| 空间分析 | 地图问答/叠加/渲染/地图操作 | 建设用地 vs 基本农田重叠 |
| 通用 | 跨域统计 | 分层模型数 / 资产分级 |
| Auto | 自动路由 | — |

### 1.3 交互核心模式

1. **意图确认卡**：参数解析 → 卡片确认（源表/目标/同步方式/执行计划）→ 用户确认 / 修改 / 取消
2. **步骤条执行**：pending → running → done 实时状态，伴随右侧治理台表格**即时插入新记录**
3. **结果卡 + 续问建议**：任务完成后给"查看详情 / 重跑 / 撤销" + "做质检 / 发布 API / 查血缘"的推荐问
4. **任务托盘**：底部悬浮，跨场景持续追踪
5. **传统模式七大治理模块**：数据架构、数据汇聚、数据开发、资产管理、数据质量、数据安全、系统管理

---

## 二、与 GIS Data Agent 的能力匹配度

### 2.1 匹配度矩阵（9 智能体 × 当前能力）

| 原型智能体 | GIS Data Agent 匹配 | 差距 |
|---|---|---|
| **数据汇聚** | 🟡 部分 — `connectors/`（6 connector：WFS/STAC/ArcGIS REST 等）+ `virtual_sources.py` + `data_catalog.py` | 缺：**人大金仓/超图引擎**连接器；缺数据同步任务编排 UI；缺核心层/主题层分层语义 |
| **数据开发** | 🟡 部分 — `WorkflowEditor`（ReactFlow DAG）+ `workflow_engine.py`（Cron+Webhook）+ `custom_skills` | 缺：**Notebook 集成**；缺算子库；缺"绿地覆盖率=xzqh⊕ddbh"这种**业务算子语义** |
| **数据质检** | 🟢 高 — 治理流水线 `GovExploration/GovProcessing/GovernanceReporter` + `GovernanceToolset`（18 工具）+ QC 子系统（v15.7）+ 缺陷分类 30 码 + SLA 工作流 3 模板 + `AlertEngine` | 仅缺：**质检规则的业务别名**（"耕地空值"）→底层规则 ID 的映射 |
| **资产管理** | 🟢 高 — `data_catalog.py` + `lineage_routes.py`（跨系统血缘）+ `semantic_layer.py` + `knowledge_graph.py` | 缺：**资产地图 UI**（原型的树状图谱视图）；缺资产热度统计 |
| **数据服务** | 🔴 低 — 只有 `frontend_api.py` 内部 REST | 缺：**把表一键发布为对外 API** 的自助服务能力；缺 API 调用统计看板 |
| **数据分析** | 🟢 高 — General/Optimization pipeline + 仪表盘 + 智能问答 + NL2SQL（FloodSQL/BIRD） | 基本齐全 |
| **空间分析** | 🟢 高（核心优势）— `GeoProcessingToolset` + `SpatialStatisticsToolset` + `SpatialAnalysisTier2Toolset` + `WatershedToolset` + MapPanel（Leaflet+deck.gl 3D）+ 叠加 / 缓冲 / 地理编码 | 原型的"地图操作"（缩放到成都 / 切卫星图）NL 已有，但深度整合度需要再打磨 |
| **通用** | 🟢 高 — General pipeline 意图路由 + `intent_router.py` | — |
| **Auto 路由** | 🟢 高 — `intent_router.py`（Gemini Flash）+ `mention_parser.py`（@ 路由） | — |

### 2.2 架构契合度

**与原型高度契合的现有能力**

- `mention_registry.py` + 新做的 AgentsTab（别名管理）→ 对应原型的 9 个 agent pill 切换 + Auto 模式
- 三 pipeline（General/Governance/Optimization）→ 可直接映射原型的三大意图类（统计 / 治理 / 空间）
- `context_manager.py` + `pipeline_runner.py` → 具备"意图确认卡 + 步骤条"所需的中间态上报
- `subagent-driven-development`（v23 已实现）→ 对应原型的子 agent 协作
- ChatPanel + DataPanel 双栏 → 原型分屏布局**已经现成**

**架构层级需要补的关键一层：治理平台适配层（Adapter Layer）**

当前 GIS Data Agent 的 connector/toolset 大多面向**空间数据源本身**（PostGIS/Shapefile/WFS/STAC），而原型要求对接的是**治理平台的管理 API**（数据源管理 CRUD、定时汇聚任务 CRUD、质检方案 CRUD、API 发布 CRUD、资产目录树）。

这意味着要引入一套新抽象：

```
GovernancePlatformAdapter (abstract)
├── DataSourceAdapter       # 对接"数据源管理"模块的 REST API
├── SyncTaskAdapter         # 对接"定时/离线汇聚"任务编排
├── AssetCatalogAdapter     # 对接资产目录 + 分层（核心/主题）
├── QCSchemeAdapter         # 对接质检方案/规则管理
├── ServicePublishAdapter   # 对接 API 发布模块
└── ModelRegistryAdapter    # 对接模型/算子管理
```

每个 Adapter 实现统一接口（list / create / update / delete / execute），**toolset 层调用 adapter 而非直接操作 DB**。这样一套代码可以对接不同厂商的治理平台（超图 / 华为 / 阿里 DataWorks 等）。

---

## 三、关键差距（按优先级）

### P0（落地必需）

1. **治理平台适配层 + 默认 HTTP Adapter**：至少实现 DataSource / SyncTask / AssetCatalog 三个 adapter 的 HTTP 对接模板
2. **分层语义**：核心层 / 主题层 / ODS / DWD 等分层概念要进 `semantic_layer.py`，支持"同步到核心层 / 耕地保护"这种自然语言路径
3. **意图确认卡协议**：在 agent 返回 metadata 里加 `intent_confirmation` 字段（参数 / 执行计划 / action_url），前端统一渲染卡片
4. **分屏联动协议**：agent 调用 adapter 时推送 `split_view_update` 事件，前端联动 DataPanel 切换到对应 tab（类似现在的 `layer_control` 机制）

### P1（体验拉满）

5. **9 个 agent 对应的 Skill 模板**：新建 9 个 Custom Skill（数据汇聚 / 开发 / 质检 / 资产 / 服务 / 分析 / 空间 / 通用 + Auto），每个绑定对应的 toolset 组合，通过 AgentsTab 自然露出
6. **Notebook 执行器**：集成 Jupyter Kernel 或内置 Python 沙箱 runtime
7. **数据服务发布**：补一个 `ServicePublishToolset`，把 PostGIS 表一键转 REST（FastAPI 动态路由生成）
8. **步骤条 + 任务托盘 UI**：现在 ChatPanel 有 subtask_progress metadata，前端渲染还是段落式；要改成原型那种 step dot + 任务托盘

### P2（差异化优势放大）

9. **空间分析深度联动地图**：原型的"地图操作 NL（缩放成都 / 切卫星图）"我们已有 layer_control 协议，但要把空间分析结果自动回显到地图（现在部分场景已有，但不统一）
10. **资产地图 UI**：用 knowledge_graph 的 networkx DiGraph 渲染资产关系图谱

---

## 四、定位建议

原型定位是 **"时空数据治理中台的智能交互层"**，GIS Data Agent 与其完美互补：

- **原型提供形态蓝图**（分屏联动 / 意图卡 / 步骤条 / 任务托盘 / 9 智能体）
- **GIS Data Agent 提供大脑**（ADK pipeline + toolset + 空间算力 + NL2SQL + 知识图谱）
- **治理平台底座**（超图 / 现有产品）**提供手脚**（实际的数据源管理 / 任务调度 / API 发布 API）

### 落地路径建议

**先做一个垂直场景原型**（比如"gdtb 同步到核心层 / 耕地保护"端到端闭环），打通：

```
意图卡 → adapter 调用 → 分屏联动 → 步骤条推进 → 结果卡 → 续问
```

完整链路，证明架构可行性，再横向扩到 9 个 agent。

这是目前最能放大 v24 已经做好的 @mention 路由 + 子智能体体系的方向。

---

## 五、附录：与当前版本的衔接点

| 现有能力 | 衔接点 |
|---|---|
| `mention_registry.py` + AgentsTab（v24.1 新增） | 9 个治理 agent 注册为 mention target，支持中文别名 |
| `intent_router.py` | 扩展意图分类，新增"治理操作类"意图（汇聚 / 同步 / 发布 / 质检方案） |
| `context_manager.py` | 新增 GovernancePlatformProvider 注入底座的分层结构和可用数据源 |
| `workflow_engine.py` | 作为 Notebook / 调度任务的底层执行器 |
| `pipeline_runner.py` 的 `subtask_progress` metadata | 前端改造为 step dot + 任务托盘 UI |
| `layer_control` metadata 机制 | 模板化为 `split_view_update`，支持联动任意 DataPanel tab |
