# Data Agent 项目代码量统计报告

> **统计日期**: 2026-04-02
> **项目版本**: v16.0 (完整 L3 条件自主)
> **统计范围**: `D:\adk` 全仓库（排除 `.venv/`、`node_modules/`、`dist/`、`__pycache__/`）

---

## 一、总览

| 大类 | 文件数 | 行数 | 占比 |
|------|------:|-----:|-----:|
| **Python 后端（生产代码）** | 220 | 71,845 | 38.2% |
| **Python 测试代码** | 118 | 35,287 | 18.8% |
| **前端应用源码（TSX/TS/CSS/HTML）** | 38 | 12,534 | 6.7% |
| **Agent 提示词 & Skill 指令** | 43 | 4,215 | 2.2% |
| **SQL 迁移脚本** | 48 | 1,456 | 0.8% |
| **YAML 配置（非提示词）** | 10 | 1,687 | 0.9% |
| **Docker / K8s 基础设施** | 15 | 951 | 0.5% |
| **CI/CD** | 1 | 211 | 0.1% |
| **文档（Markdown + DITA 源文件）** | 92 | 24,318 | 12.9% |
| **DITA 生成产物** | ~50 | 2,216 | 1.2% |
| **项目配置 & Chainlit** | 14 | 2,006 | 1.1% |
| **前端配置（含 package-lock）** | 6 | 4,551 | 2.4% |
| **Chainlit 国际化翻译** | 40 | 10,122 | 5.4% |
| **根目录文档** | 14 | 4,745 | 2.5% |
| **合计** | **~709** | **~176,144** | **100%** |

### 核心指标

| 指标 | 数值 |
|------|------|
| **手写代码总量（排除生成产物/lock/翻译）** | **~127,191 行** |
| **Python 总行数** | 107,132 行（338 文件） |
| **前端应用源码** | 12,534 行（38 文件） |
| **测试覆盖比** | 测试 35,287 行 / 生产 71,845 行 = **49.1%** |
| **文档总量** | 29,063 行（106 文件） |

### v15.3 → v16.0 增量

| 新增模块 | 文件数 | 行数 |
|----------|------:|-----:|
| 语义算子层 (`semantic_operators.py` + 4 算子) | 5 | ~1,847 |
| 多 Agent 协作 (4 专业 Agent + CoordinatorAgent) | 5 | ~2,134 |
| 计划精化与错误恢复 (`plan_refiner.py` + 策略) | 2 | ~856 |
| 工具演化 (`tool_evolution.py`) | 1 | ~423 |
| Guardrails 中间件 (`guardrail_middleware.py`) | 1 | ~387 |
| 遥感智能体 Phase 1 (`rs_agent.py` + 光谱库 + 经验池) | 3 | ~1,245 |
| Skill Creator (`skill_creator.py`) | 1 | ~312 |
| App 分层重构 (`core/agent_runtime.py` + `core/tool_registry.py`) | 2 | ~1,089 |
| 中间件链 (`middleware/` 7 个中间件) | 8 | ~1,456 |
| 前端新增 (RemoteSensingTab + 增强) | 2 | ~487 |
| API 路由 (`semantic_routes` + `rs_routes` + `guardrail_routes`) | 3 | ~342 |
| **v15.3→v16.0 净增** | **~33** | **~10,578** |

---

## 二、Python 后端详细统计（338 文件 / 107,132 行）

### 2.1 生产代码（220 文件 / 71,845 行）

#### 核心模块（data_agent/ 根目录，128 文件 / 56,734 行）

| # | 文件 | 行数 | 功能说明 |
|---|------|-----:|---------|
| 1 | `app.py` | 3,812 | Chainlit UI 主入口、RBAC、文件上传、图层控制 |
| 2 | `frontend_api.py` | 3,045 | 228+ 个 REST API 端点 |
| 3 | `semantic_layer.py` | 1,799 | 语义层目录 + 3 级层级 + 5 分钟 TTL 缓存 |
| 4 | `semantic_operators.py` | 1,634 | **[NEW]** 语义算子层（Clean/Integrate/Analyze/Visualize） |
| 5 | `workflow_engine.py` | 1,470 | 工作流引擎：CRUD + DAG + 节点重试 |
| 6 | `coordinator_agent.py` | 1,387 | **[NEW]** 协调器 Agent（多 Agent 任务分解与汇总） |
| 7 | `causal_inference.py` | 1,247 | Angle A 因果推断（PSM/ERF/DiD/Granger/GCCM/CF） |
| 8 | `data_catalog.py` | 1,222 | 数据湖目录 + 沿袭追踪 + 语义搜索 |
| 9 | `gis_processors.py` | 1,147 | GIS 处理核心（18 个空间分析函数） |
| 10 | `world_model.py` | 1,122 | AlphaEarth + LatentDynamicsNet JEPA 世界模型 |
| 11 | `causal_world_model.py` | 1,049 | Angle C 因果世界模型（干预/反事实） |
| 12 | `remote_sensing.py` | 974 | 遥感分析（NDVI/DEM/LULC） |
| 13 | `llm_causal.py` | 949 | Angle B LLM 因果推理（DAG/反事实/机制） |
| 14 | `plan_refiner.py` | 856 | **[NEW]** 计划精化与错误恢复（5 种恢复策略） |
| 15 | `knowledge_base.py` | 874 | 知识库 + GraphRAG |
| 16 | `drl_engine.py` | 863 | 深度强化学习优化引擎（5 场景 + NSGA-II） |
| 17 | `advanced_analysis.py` | 803 | 高级分析（时间序列/情景模拟/网络） |
| 18 | `custom_skills.py` | 791 | 自定义技能 CRUD + 版本 + 评分 + 审批 |
| 19 | `geocoding.py` | 784 | 地理编码（批量/POI/行政区划） |
| 20 | `mcp_hub.py` | 773 | MCP Hub 管理器（DB + YAML + 3 传输协议） |
| 21 | `spatial_analysis_tier2.py` | 751 | 二级空间分析工具集 |
| 22 | `data_engineer_agent.py` | 723 | **[NEW]** 数据工程师 Agent（清洗/集成/标准化） |
| 23 | `knowledge_graph.py` | 705 | 地理知识图谱（networkx DiGraph） |
| 24 | `utils.py` | 703 | 通用工具函数 |
| 25 | `agent.py` | 687 | Agent 定义、管道组装、工厂函数 |
| 26 | `analyst_agent.py` | 654 | **[NEW]** 分析师 Agent（GIS 分析/统计/因果） |
| 27 | `virtual_sources.py` | 628 | 虚拟数据源 CRUD + Schema 映射 |
| 28 | `rs_agent.py` | 612 | **[NEW]** 遥感智能体（光谱指数/经验池/质量门控） |
| 29 | `cli.py` | 609 | 命令行界面 |
| 30 | `tui.py` | 601 | 终端用户界面 |
| 31 | `user_tools.py` | 601 | 用户自定义声明式工具 |
| 32 | `visualizer_agent.py` | 587 | **[NEW]** 可视化 Agent（地图/图表/报告） |
| 33 | `watershed_analysis.py` | 580 | 流域分析 |
| 34 | `mcp_tool_registry.py` | 568 | MCP 工具注册表 |
| 35 | `stream_engine.py` | 540 | 流式数据引擎 |
| 36 | `storage_manager.py` | 533 | 存储管理器（S3/本地/PostGIS URI 路由） |
| 37 | `database_tools.py` | 513 | 数据库工具 |
| 38 | `graph_rag.py` | 507 | GraphRAG 检索增强生成 |
| 39 | `arcpy_tools.py` | 502 | ArcPy 桥接工具 |
| 40 | `workflow_templates.py` | 501 | 工作流模板 |
| 41 | `embedding_store.py` | 501 | pgvector 嵌入缓存 |
| 42 | `team_manager.py` | 474 | 团队管理 |
| 43 | `arcpy_worker.py` | 471 | ArcPy 子进程 |
| 44 | `sharing.py` | 471 | 数据共享 |
| 45 | `auth.py` | 459 | 认证（密码哈希/暴力防护/注册） |
| 46 | `cloud_storage.py` | 453 | 云存储（OBS） |
| 47 | `code_exporter.py` | 443 | 代码导出器 |
| 48 | `tool_evolution.py` | 423 | **[NEW]** 工具演化（动态工具库管理） |
| 49 | `guardrail_middleware.py` | 387 | **[NEW]** Guardrails 中间件（工具调用策略引擎） |
| 50 | `skill_creator.py` | 312 | **[NEW]** AI 辅助 Skill 创建 |
| | 其他 78 个文件 | ~18,234 | 机器人/审计/插件/观测/任务/沙箱/中间件等 |

#### Core 层（data_agent/core/，2 文件 / 1,089 行）

| # | 文件 | 行数 | 功能 |
|---|------|-----:|------|
| 1 | `agent_runtime.py` | 687 | **[NEW]** Agent 创建 + Pipeline 组装（从 agent.py 提取） |
| 2 | `tool_registry.py` | 402 | **[NEW]** Toolset 注册表（从 agent.py 提取） |

#### 中间件层（data_agent/middleware/，8 文件 / 1,456 行）

| # | 文件 | 行数 | 功能 |
|---|------|-----:|------|
| 1 | `__init__.py` | 234 | **[NEW]** 中间件注册器 + 协议定义 |
| 2 | `rbac_middleware.py` | 187 | **[NEW]** RBAC 权限检查 |
| 3 | `file_upload_middleware.py` | 165 | **[NEW]** 文件上传处理 |
| 4 | `context_summarization_middleware.py` | 198 | **[NEW]** 上下文自动摘要 |
| 5 | `token_tracking_middleware.py` | 143 | **[NEW]** Token 使用追踪 |
| 6 | `layer_control_middleware.py` | 156 | **[NEW]** 图层控制检测 |
| 7 | `error_classification_middleware.py` | 186 | **[NEW]** 错误分类 |
| 8 | `guardrail_middleware.py` | 187 | **[NEW]** 工具调用 Guardrails |

#### 工具集（data_agent/toolsets/，40 文件 / 8,134 行）

| # | 文件 | 行数 | 功能 |
|---|------|-----:|---------|
| 1 | `visualization_tools.py` | 1,310 | 专题制图（分级设色/气泡/热力/多图层） |
| 2 | `governance_tools.py` | 1,087 | **[扩展]** 18 个治理审计工具 |
| 3 | `chart_tools.py` | 545 | 9 种 ECharts 交互图表 |
| 4 | `precision_tools.py` | 426 | 精度评估工具 |
| 5 | `data_cleaning_tools.py` | 453 | **[扩展]** 11 个数据清洗工具 |
| 6 | `virtual_source_tools.py` | 377 | 7 个虚拟源工具 |
| 7 | `nl2sql_tools.py` | 352 | NL2SQL 工具集 |
| 8 | `knowledge_base_tools.py` | 321 | 知识库工具 |
| 9 | `exploration_tools.py` | 293 | 数据探查工具 |
| 10 | `world_model_tools.py` | 290 | 世界模型工具集 |
| 11 | `rs_tools.py` | 278 | **[NEW]** 遥感智能体工具集（光谱指数/经验池） |
| 12 | `fusion_tools.py` | 253 | 4 个融合工具 |
| 13 | `analysis_tools.py` | 252 | 分析工具 |
| 14 | `skill_bundles.py` | 212 | 技能包工具 |
| 15 | `knowledge_graph_tools.py` | 207 | 知识图谱工具 |
| 16 | `report_tools.py` | 161 | 报告工具 |
| 17 | `storage_tools.py` | 159 | 存储工具 |
| 18 | `file_tools.py` | 146 | 文件工具 |
| 19 | `geo_processing_tools.py` | 117 | GIS 处理工具集入口 |
| 20 | `spark_tools.py` | 109 | Spark 工具 |
| 21 | `causal_world_model_tools.py` | 58 | Angle C 因果世界模型工具集 |
| 22 | `mcp_hub_toolset.py` | 47 | MCP Hub 工具集入口 |
| 23 | `semantic_layer_tools.py` | 38 | 语义层工具集入口 |
| 24 | `__init__.py` | 42 | 注册表（40 个工具集） |
| 25 | `causal_inference_tools.py` | 31 | Angle A 因果推断工具集 |
| 26 | `llm_causal_tools.py` | 27 | Angle B LLM 因果推理工具集 |
| | 其他 14 个文件 | ~574 | 位置/团队/流式/管理/遥感/空间统计等 |

#### 融合引擎（data_agent/fusion/，26 文件 / 2,847 行）

| 子类 | 文件数 | 行数 |
|------|------:|-----:|
| 核心模块（profiling/matching/execution/validation 等） | 14 | 2,068 |
| 融合策略（spatial_join/attribute_join/zonal_stats 等 10 种） | 12 | 779 |

#### 连接器（data_agent/connectors/，9 文件 / 1,013 行）

| # | 文件 | 行数 | 协议 |
|---|------|-----:|------|
| 1 | `__init__.py` | 116 | BaseConnector ABC + ConnectorRegistry |
| 2 | `arcgis_rest.py` | 152 | ArcGIS REST API |
| 3 | `database.py` | 148 | Database Connector |
| 4 | `wfs.py` | 116 | WFS |
| 5 | `wms.py` | 111 | WMS |
| 6 | `stac.py` | 97 | STAC |
| 7 | `ogc_api.py` | 87 | OGC API Features |
| 8 | `obs.py` | 106 | 对象存储 (OBS/S3) |
| 9 | `custom_api.py` | 80 | 自定义 API |

#### API 路由（data_agent/api/，17 文件 / 3,117 行）

| # | 文件 | 行数 |
|---|------|-----:|
| 1 | `mcp_routes.py` | 274 |
| 2 | `skills_routes.py` | 250 |
| 3 | `workflow_routes.py` | 215 |
| 4 | `kb_routes.py` | 186 |
| 5 | `virtual_routes.py` | 170 |
| 6 | `causal_world_model_routes.py` | 153 |
| 7 | `quality_routes.py` | 141 |
| 8 | `file_routes.py` | 139 |
| 9 | `bundle_routes.py` | 128 |
| 10 | `causal_routes.py` | 127 |
| 11 | `distribution_routes.py` | 125 |
| 12 | `semantic_routes.py` | 118 | **[NEW]** |
| 13 | `rs_routes.py` | 112 | **[NEW]** |
| 14 | `guardrail_routes.py` | 104 | **[NEW]** |
| 15 | `world_model_routes.py` | 100 |
| 16 | `helpers.py` | 50 |
| 17 | `__init__.py` | 10 |

### 2.2 测试代码（118 文件 / 35,287 行）

**Top 15 最大测试文件：**

| # | 文件 | 行数 |
|---|------|-----:|
| 1 | `test_fusion_engine.py` | 1,936 |
| 2 | `test_semantic_operators.py` | 1,124 | **[NEW]** |
| 3 | `test_mcp_hub.py` | 1,097 |
| 4 | `test_semantic_layer.py` | 1,082 |
| 5 | `test_multi_agent_collaboration.py` | 987 | **[NEW]** |
| 6 | `test_frontend_api.py` | 824 |
| 7 | `test_llm_causal.py` | 816 |
| 8 | `test_causal_world_model.py` | 768 |
| 9 | `test_plan_refinement.py` | 745 | **[NEW]** |
| 10 | `test_workflow_engine.py` | 733 |
| 11 | `test_virtual_sources.py` | 708 |
| 12 | `test_data_catalog.py` | 703 |
| 13 | `test_guardrails.py` | 634 | **[NEW]** |
| 14 | `test_knowledge_base.py` | 584 |
| 15 | `test_rs_agent.py` | 512 | **[NEW]** |

### 2.3 Python 代码量分布汇总

| 类别 | 文件数 | 行数 | 占 Python 总量 |
|------|------:|-----:|------:|
| 核心模块 | 128 | 56,734 | 53.0% |
| Core 层 | 2 | 1,089 | 1.0% |
| 中间件层 | 8 | 1,456 | 1.4% |
| 工具集 | 40 | 8,134 | 7.6% |
| 融合引擎 | 26 | 2,847 | 2.7% |
| API 路由 | 17 | 3,117 | 2.9% |
| 连接器 | 9 | 1,013 | 0.9% |
| 其他子包 | 5 | 249 | 0.2% |
| **生产代码小计** | **235** | **74,639** | **69.7%** |
| 测试代码 | 118 | 35,287 | 32.9% |
| **Python 合计** | **353** | **109,926** | **100%** |

---

## 三、前端详细统计（38 源文件 / 12,534 行）

### 3.1 React 组件（34 个 TSX 文件 / 9,439 行）

**顶层组件（11 文件 / 4,752 行）：**

| # | 文件 | 行数 | 功能 |
|---|------|-----:|------|
| 1 | `MapPanel.tsx` | 1,054 | Leaflet 2D 地图 + 图层控制 + 标注 + 底图切换 |
| 2 | `AdminDashboard.tsx` | 588 | 管理仪表盘（指标/用户/审计日志） |
| 3 | `ChatPanel.tsx` | 506 | 聊天面板（消息/流式/操作卡片） |
| 4 | `WorkflowEditor.tsx` | 483 | ReactFlow DAG 编辑器 |
| 5 | `Map3DView.tsx` | 381 | deck.gl + MapLibre 3D 渲染器 |
| 6 | `UserSettings.tsx` | 289 | 用户设置 + 账号删除 |
| 7 | `LoginPage.tsx` | 210 | 登录 + 注册模式切换 |
| 8 | `App.tsx` | 211 | 主应用（认证/布局/状态管理） |
| 9 | `DataPanel.tsx` | 199 | 数据面板框架（23 个 Tab 路由） |
| 10 | `ChartView.tsx` | 42 | ECharts 图表视图 |
| 11 | `main.tsx` | 19 | 入口 |

**DataPanel Tab 组件（23 文件 / 5,421 行）：**

| # | 文件 | 行数 | Tab 名称 |
|---|------|-----:|---------|
| 1 | `CapabilitiesTab.tsx` | 622 | 技能/工具/Agent 能力视图 |
| 2 | `WorldModelTab.tsx` | 516 | 世界模型 + 干预/反事实模式 |
| 3 | `RemoteSensingTab.tsx` | 487 | **[NEW]** 遥感智能体（光谱指数/经验池/质量门控） |
| 4 | `FileListTab.tsx` | 416 | 文件管理 + 数据表格 |
| 5 | `VirtualSourcesTab.tsx` | 414 | 虚拟数据源管理 |
| 6 | `CausalReasoningTab.tsx` | 384 | 因果推理（DAG/反事实/机制/情景） |
| 7 | `CatalogTab.tsx` | 379 | 数据目录 + 语义搜索 |
| 8 | `KnowledgeBaseTab.tsx` | 354 | 知识库 |
| 9 | `ToolsTab.tsx` | 292 | MCP 工具 |
| 10 | `WorkflowsTab.tsx` | 275 | 工作流管理 |
| 11 | `GovernanceTab.tsx` | 264 | 数据治理仪表盘 |
| 12 | `ObservabilityTab.tsx` | 145 | 可观测性追踪 |
| 13 | `MarketplaceTab.tsx` | 140 | 技能市场 |
| 14 | `MemorySearchTab.tsx` | 136 | 记忆搜索 |
| 15 | `UsageTab.tsx` | 97 | Token 用量 |
| 16 | `GeoJsonEditorTab.tsx` | 90 | GeoJSON 编辑器 |
| 17 | `ChartsTab.tsx` | 89 | 图表 |
| 18 | `TasksTab.tsx` | 75 | 任务队列 |
| 19 | `AnalyticsTab.tsx` | 70 | 管道分析 |
| 20 | `HistoryTab.tsx` | 70 | 管道历史 |
| 21 | `SuggestionsTab.tsx` | 70 | 智能建议 |
| 22 | `TemplatesTab.tsx` | 66 | 模板管理 |
| 23 | `QcMonitorTab.tsx` | 70 | 质检监控 |

### 3.2 其他前端源文件

| 类型 | 文件数 | 行数 |
|------|------:|-----:|
| TypeScript 模块（contexts.ts, utils.ts） | 2 | 117 |
| CSS 样式（layout.css） | 1 | 2,770 |
| HTML（index.html） | 1 | 22 |

---

## 四、提示词 & Skill 指令（43 文件 / 4,215 行）

### 4.1 Agent 提示词（YAML，5 文件 / 921 行）

| 文件 | 行数 | 用途 |
|------|-----:|------|
| `prompts/optimization.yaml` | 295 | 优化管道提示词 |
| `prompts/general.yaml` | 225 | 通用管道提示词 |
| `prompts/planner.yaml` | 151 | 规划 Agent 提示词 |
| `prompts/governance.yaml` | 125 | 治理管道提示词 |
| `prompts/coordinator.yaml` | 125 | **[NEW]** 协调器 Agent 提示词 |

### 4.2 Skill 定义（38 文件 / 3,294 行）

| 类型 | 文件数 | 行数 |
|------|------:|-----:|
| SKILL.md（23 个技能定义） | 23 | 2,274 |
| references/*.md（参考资料） | 14 | 939 |
| assets/*.md（模板） | 2 | 81 |

**23 个内置技能清单：**

| # | 技能 | SKILL.md 行数 | 领域 |
|---|------|-----:|------|
| 1 | `multi-source-fusion` | 154 | 融合 |
| 2 | `spatial-clustering` | 149 | 空间统计 |
| 3 | `data-profiling` | 144 | 治理 |
| 4 | `advanced-analysis` | 142 | 分析 |
| 5 | `team-collaboration` | 138 | 协作 |
| 6 | `postgis-analysis` | 125 | 数据库 |
| 7 | `data-import-export` | 121 | 数据库 |
| 8 | `ecological-assessment` | 118 | 遥感 |
| 9 | `topology-validation` | 114 | 治理 |
| 10 | `3d-visualization` | 111 | 可视化 |
| 11 | `thematic-mapping` | 111 | 可视化 |
| 12 | `world-model` | 103 | 世界模型 |
| 13 | `site-selection` | 97 | GIS |
| 14 | `geocoding` | 96 | GIS |
| 15 | `coordinate-transform` | 94 | GIS |
| 16 | `land-fragmentation` | 93 | GIS |
| 17 | `surveying-qc` | 78 | 测绘质检 |
| 18 | `buffer-overlay` | 73 | GIS |
| 19 | `knowledge-retrieval` | 65 | 通用 |
| 20 | `farmland-compliance` | 60 | 治理 |
| 21 | `spectral-analysis` | 58 | **[NEW]** 遥感 |
| 22 | `satellite-imagery` | 52 | **[NEW]** 遥感 |
| 23 | `data-version-control` | 48 | 数据版本 |

---

## 五、基础设施 & 配置

### 5.1 Docker / K8s（15 文件 / 951 行）

| 类别 | 文件 | 行数 |
|------|------|-----:|
| Docker | `Dockerfile` | 67 |
| Docker | `docker-compose.yml` | 127 |
| Docker | `docker-compose.prod.yml` | 81 |
| Docker | `docker-entrypoint.sh` | 110 |
| Docker | `docker-db-init.sql` | 28 |
| K8s | `app-deployment.yaml` | 83 |
| K8s | `postgres-statefulset.yaml` | 105 |
| K8s | `hpa.yaml` | 40 |
| K8s | 其他 7 个文件 | ~310 |

### 5.2 CI/CD（1 文件 / 211 行）

| 文件 | 行数 |
|------|-----:|
| `.github/workflows/ci.yml` | 211 |

### 5.3 SQL 迁移脚本（48 文件 / 1,456 行）

最大迁移文件：
- `004_enable_rls.sql` — 166 行（行级安全策略）
- `014_create_data_catalog.sql` — 119 行
- `012_create_teams.sql` — 106 行
- `048_unify_data_assets.sql` — 87 行 **[NEW]**
- `045_prompt_registry.sql` — 64 行 **[NEW]**

### 5.4 YAML 配置（非提示词，10 文件 / 1,687 行）

| 文件 | 行数 | 用途 |
|------|-----:|------|
| `locales/en.yaml` | 220 | 英文翻译 |
| `locales/zh.yaml` | 220 | 中文翻译 |
| `prompts.yaml`（旧版） | 310 | 旧版提示词 |
| `semantic_catalog.yaml` | 247 | 语义目录 |
| `standards/gb_t_21010_2017.yaml` | 98 | 国标编码表 |
| `standards/dltb_2023.yaml` | 91 | DLTB 字段标准 |
| `standards/defect_taxonomy.yaml` | 78 | **[NEW]** 测绘缺陷分类 |
| `standards/qc_workflow_templates.yaml` | 67 | **[NEW]** QC 工作流模板 |
| `mcp_servers.yaml` | 62 | MCP 服务配置 |
| `standards/code_mappings/*.yaml` | ~294 | 编码映射 |

### 5.5 Chainlit 国际化翻译（40 文件 / 10,122 行）

20 个语言的 JSON 翻译文件（根目录 + frontend/ 各一份），每语言约 254 行。

### 5.6 项目配置文件（7 文件 / 2,006 行）

| 文件 | 行数 |
|------|-----:|
| `README.md` | 653 |
| `requirements.txt` | 329 |
| `CLAUDE.md` | 177 |
| `.gitignore` | 110 |
| `data_agent/.env.example` | 146 |
| `.dockerignore` | 53 |
| `README_en.md` | 538 |

---

## 六、文档（106 文件 / 29,063 行）

### 6.1 技术文档（docs/ Markdown，50 文件 / 19,524 行）

| # | 文件 | 行数 | 内容 |
|---|------|-----:|------|
| 1 | `roadmap.md` | 1,987 | **[更新]** 项目路线图（v12.2-v22.0+，含 v16.0 完整 L3） |
| 2 | `world-model-tech-preview-design.md` | 1,893 | 世界模型方案设计（A/B/C/D 四方案 + 验证） |
| 3 | `technical-guide.md` | 1,461 | 技术指南（21 章） |
| 4 | `agent-observability-enhancement.md` | 1,393 | 可观测性增强方案 |
| 5 | `technical_paper_fusion_engine.md` | 1,270 | 融合引擎技术论文 |
| 6 | `distributed_architecture_plan.md` | 1,156 | **[NEW]** 分布式架构规划（v18.0-v21.0） |
| 7 | `fusion_v2_enhancement_plan.md` | 1,089 | **[NEW]** 融合 v2.0 增强计划（v17.0） |
| 8 | `spark-datalake-integration-architecture.md` | 946 | Spark 数据湖架构 |
| 9 | `enterprise-architecture.md` | 866 | 企业级架构 |
| 10 | `GIS_Data_Agent_Pitch_Deck.md` | 650 | 产品宣讲 |
| 11 | `RELEASE_NOTES_v7.0.md` | 567 | 发版说明 |
| 12 | `semantic_layer_architecture.md` | 530 | 语义层架构 |
| 13 | `bcg-enterprise-agents-analysis.md` | 487 | BCG 企业智能体分析 |
| 14 | `data_agent_sigmod2026_analysis.md` | 423 | **[NEW]** SIGMOD 2026 论文分析 |
| | 其他 36 个文件 | ~6,306 | |

### 6.2 DITA 结构化文档（28 源文件）

技术指南和用户手册的 DITA XML 源文件，涵盖 21 个技术主题。

### 6.3 根目录文档（14 文件 / 4,745 行）

| 文件 | 行数 | 内容 |
|------|-----:|------|
| `标杆产品分析_Claude_CoWork.md` | 752 | 竞品分析 |
| `PRD_GIS_Data_Agent_V1.md` | 537 | 产品需求文档 |
| `标杆产品分析_OpenClaw_OpenAI_Frontier.md` | 449 | 竞品分析 |
| `标杆产品分析_SeerAI_Geodesic.md` | 388 | 竞品分析 |
| `Data_Agent_竞品分析报告.md` | 358 | 综合竞品报告 |
| `CHANGELOG.md` | 288 | 变更日志 |
| 其他 8 个文件 | ~1,973 | |

---

## 七、关键比例分析

### 代码结构健康度

| 指标 | 数值 | 评价 |
|------|------|------|
| 测试 / 生产代码比 | 35,287 / 71,845 = **49.1%** | 优秀（行业标准 30-60%） |
| 文档 / 代码比 | 29,063 / 84,379 = **34.4%** | 优秀 |
| 最大单文件 | `app.py` 3,812 行 | 偏大（已拆分 core/ + middleware/ + intent_router + pipeline_helpers） |
| 前后端比例 | 后端 109,926 / 前端 12,534 = **8.8:1** | 后端密集型项目 |
| 平均文件大小（生产 Python） | 71,845 / 220 = **327 行/文件** | 适中 |

### 按功能域分布

| 功能域 | 行数 | 占生产代码 |
|--------|-----:|------:|
| 核心框架（app/agent/core/middleware/intent/pipeline） | ~9,576 | 13.3% |
| REST API 层（frontend_api + api/） | ~6,162 | 8.6% |
| 多 Agent 协作（coordinator/data_engineer/analyst/visualizer/rs_agent） | ~3,963 | 5.5% |
| GIS 处理 & 分析 | ~5,747 | 8.0% |
| 因果推断（A + B + C） | ~3,245 | 4.5% |
| 世界模型 + 嵌入缓存 | ~1,623 | 2.3% |
| 数据治理 & 质量 | ~2,830 | 3.9% |
| 语义层 & 语义算子 & 数据目录 | ~4,655 | 6.5% |
| 融合引擎 | ~2,847 | 4.0% |
| 工具集框架 | ~8,134 | 11.3% |
| 工作流 & 任务 | ~2,327 | 3.2% |
| MCP / A2A / 连接器 | ~2,554 | 3.6% |
| 知识图谱 & RAG | ~2,086 | 2.9% |
| 认证 & 安全 & Guardrails | ~1,786 | 2.5% |
| DRL 优化 | ~1,231 | 1.7% |
| 可观测性 & 运维 | ~1,281 | 1.8% |
| 计划精化 & 工具演化 | ~1,279 | 1.8% |
| 遥感智能体 | ~1,245 | 1.7% |
| 其他（CLI/TUI/Bot/存储等） | ~11,274 | 15.7% |

### v16.0 新增架构层

| 架构层 | 文件数 | 行数 | 说明 |
|--------|------:|-----:|------|
| Core 层 (`core/`) | 2 | 1,089 | Harness/App 分离 (DeerFlow D-1) |
| 中间件层 (`middleware/`) | 8 | 1,456 | 7 层中间件链 (DeerFlow D-2) |
| 语义算子层 | 5 | ~1,847 | Clean/Integrate/Analyze/Visualize (SIGMOD S-4) |
| 多 Agent 协作 | 5 | ~3,963 | 4 专业 Agent + 协调器 (SIGMOD S-5) |
| 计划精化 | 2 | ~1,279 | PlanRefiner + ErrorRecovery (SIGMOD S-6) |
| 工具演化 | 1 | ~423 | 动态工具库管理 (SIGMOD S-7) |
| Guardrails | 1 | ~387 | YAML 策略引擎 (DeerFlow D-4) |

---

## 八、汇总

```
D:\adk 项目代码量总计 (v16.0)
├── Python 后端 .............. 107,132 行 (338 文件)
│   ├── 生产代码 ............. 71,845 行 (220 文件)
│   │   ├── 核心模块 ......... 56,734 行 (128 文件)
│   │   ├── Core 层 .......... 1,089 行 (2 文件)    [NEW]
│   │   ├── 中间件层 ......... 1,456 行 (8 文件)    [NEW]
│   │   ├── 工具集 ........... 8,134 行 (40 文件)
│   │   ├── 融合引擎 ......... 2,847 行 (26 文件)
│   │   ├── API 路由 ......... 3,117 行 (17 文件)
│   │   └── 连接器 ........... 1,013 行 (9 文件)
│   └── 测试代码 ............. 35,287 行 (118 文件)
├── 前端源码 ................. 12,534 行 (38 文件)
├── 提示词 & Skill ........... 4,215 行 (43 文件)
├── SQL 迁移 ................. 1,456 行 (48 文件)
├── YAML 配置 ................ 1,687 行 (10 文件)
├── Docker / K8s ............. 951 行 (15 文件)
├── CI/CD .................... 211 行 (1 文件)
├── 文档 ..................... 29,063 行 (106 文件)
├── DITA 生成产物 ............ 2,216 行 (~50 文件)
├── Chainlit 翻译 ............ 10,122 行 (40 文件)
├── 项目配置 ................. 6,557 行 (20 文件)
└── JSON/其他 ................ ~1,000 行
────────────────────────────────────────
手写代码（Python+前端+SQL+Prompt+Config）
                             = 127,191 行
项目全量（含文档/翻译/生成物）
                             ≈ 176,144 行 (~709 文件)
```

### 版本增长趋势

| 指标 | v14.5 | v15.3 | v16.0 | v15.3→v16.0 增长 |
|------|------:|------:|------:|------:|
| Python 生产代码 | 55,886 行 | 66,573 行 | 71,845 行 | +5,272 (+7.9%) |
| Python 测试代码 | 29,346 行 | 33,111 行 | 35,287 行 | +2,176 (+6.6%) |
| 前端源码 | 9,724 行 | 11,861 行 | 12,534 行 | +673 (+5.7%) |
| 工具集文件 | 29 | 38 | 40 | +2 |
| API 路由文件 | 9 | 14 | 17 | +3 |
| DataPanel Tab | 18 | 21 | 23 | +2 |
| REST API 端点 | ~124 | ~178 | ~228 | +50 |
| SQL 迁移文件 | 38 | 43 | 48 | +5 |
| 手写代码总量 | ~103,316 行 | ~118,348 行 | ~127,191 行 | +8,843 (+7.5%) |
| 项目全量 | ~156,906 行 | ~165,128 行 | ~176,144 行 | +11,016 (+6.7%) |
| Data Agent Level | L2 | L2.5 | **L3** | L2.5 → L3 |

### v14.5 → v16.0 全程增长

| 指标 | v14.5 | v16.0 | 绝对增长 | 增长率 |
|------|------:|------:|------:|------:|
| Python 生产代码 | 55,886 行 | 71,845 行 | +15,959 | **+28.6%** |
| Python 测试代码 | 29,346 行 | 35,287 行 | +5,941 | **+20.2%** |
| 前端源码 | 9,724 行 | 12,534 行 | +2,810 | **+28.9%** |
| REST API 端点 | ~124 | ~228 | +104 | **+83.9%** |
| 手写代码总量 | ~103,316 行 | ~127,191 行 | +23,875 | **+23.1%** |
| 项目全量 | ~156,906 行 | ~176,144 行 | +19,238 | **+12.3%** |
