# Data Agent 项目代码量统计报告

> **统计日期**: 2026-03-25
> **项目版本**: v15.3 (三角度因果推断体系)
> **统计范围**: `D:\adk` 全仓库（排除 `.venv/`、`node_modules/`、`dist/`、`__pycache__/`）

---

## 一、总览

| 大类 | 文件数 | 行数 | 占比 |
|------|------:|-----:|-----:|
| **Python 后端（生产代码）** | 208 | 66,573 | 37.4% |
| **Python 测试代码** | 113 | 33,111 | 18.6% |
| **前端应用源码（TSX/TS/CSS/HTML）** | 36 | 11,861 | 6.7% |
| **Agent 提示词 & Skill 指令** | 41 | 3,970 | 2.2% |
| **SQL 迁移脚本** | 43 | 1,268 | 0.7% |
| **YAML 配置（非提示词）** | 8 | 1,464 | 0.8% |
| **Docker / K8s 基础设施** | 15 | 951 | 0.5% |
| **CI/CD** | 1 | 211 | 0.1% |
| **文档（Markdown + DITA 源文件）** | 87 | 22,079 | 12.4% |
| **DITA 生成产物** | ~50 | 2,216 | 1.2% |
| **项目配置 & Chainlit** | 14 | 2,006 | 1.1% |
| **前端配置（含 package-lock）** | 6 | 4,551 | 2.6% |
| **Chainlit 国际化翻译** | 40 | 10,122 | 5.7% |
| **根目录文档** | 14 | 4,745 | 2.7% |
| **合计** | **~676** | **~165,128** | **100%** |

### 核心指标

| 指标 | 数值 |
|------|------|
| **手写代码总量（排除生成产物/lock/翻译）** | **~118,348 行** |
| **Python 总行数** | 99,684 行（321 文件） |
| **前端应用源码** | 11,861 行（36 文件） |
| **测试覆盖比** | 测试 33,111 行 / 生产 66,573 行 = **49.7%** |
| **文档总量** | 26,824 行（101 文件） |

### v14.5 → v15.3 增量

| 新增模块 | 文件数 | 行数 |
|----------|------:|-----:|
| 因果推断 Angle A (`causal_inference.py` + toolset + test) | 3 | 1,782 |
| LLM 因果推理 Angle B (`llm_causal.py` + toolset + test) | 3 | 1,792 |
| 因果世界模型 Angle C (`causal_world_model.py` + toolset + test) | 3 | 1,875 |
| 世界模型 (`world_model.py` + `embedding_store.py` + toolset) | 3 | 1,913 |
| NL2SQL (`nl2sql.py` + toolset) | 2 | ~480 |
| 前端新增 (`CausalReasoningTab` + `WorldModelTab` 扩展 + `ObservabilityTab`) | 3 | ~1,045 |
| API 路由 (`causal_routes` + `causal_world_model_routes` + `world_model_routes` + `file_routes` + `distribution_routes`) | 5 | ~760 |
| **v14.5→v15.3 净增** | **~22** | **~9,647** |

---

## 二、Python 后端详细统计（321 文件 / 99,684 行）

### 2.1 生产代码（208 文件 / 66,573 行）

#### 核心模块（data_agent/ 根目录，116 文件 / 52,198 行）

| # | 文件 | 行数 | 功能说明 |
|---|------|-----:|---------|
| 1 | `app.py` | 3,598 | Chainlit UI 主入口、RBAC、文件上传、图层控制 |
| 2 | `frontend_api.py` | 2,837 | 178+ 个 REST API 端点 |
| 3 | `semantic_layer.py` | 1,799 | 语义层目录 + 3 级层级 + 5 分钟 TTL 缓存 |
| 4 | `workflow_engine.py` | 1,470 | 工作流引擎：CRUD + DAG + 节点重试 |
| 5 | `causal_inference.py` | 1,247 | **[NEW]** Angle A 因果推断（PSM/ERF/DiD/Granger/GCCM/CF） |
| 6 | `data_catalog.py` | 1,222 | 数据湖目录 + 沿袭追踪 + 语义搜索 |
| 7 | `gis_processors.py` | 1,147 | GIS 处理核心（18 个空间分析函数） |
| 8 | `world_model.py` | 1,122 | **[NEW]** AlphaEarth + LatentDynamicsNet JEPA 世界模型 |
| 9 | `causal_world_model.py` | 1,049 | **[NEW]** Angle C 因果世界模型（干预/反事实） |
| 10 | `remote_sensing.py` | 974 | 遥感分析（NDVI/DEM/LULC） |
| 11 | `llm_causal.py` | 949 | **[NEW]** Angle B LLM 因果推理（DAG/反事实/机制） |
| 12 | `knowledge_base.py` | 874 | 知识库 + GraphRAG |
| 13 | `drl_engine.py` | 863 | 深度强化学习优化引擎（5 场景 + NSGA-II） |
| 14 | `advanced_analysis.py` | 803 | 高级分析（时间序列/情景模拟/网络） |
| 15 | `custom_skills.py` | 791 | 自定义技能 CRUD + 版本 + 评分 + 审批 |
| 16 | `geocoding.py` | 784 | 地理编码（批量/POI/行政区划） |
| 17 | `mcp_hub.py` | 773 | MCP Hub 管理器（DB + YAML + 3 传输协议） |
| 18 | `spatial_analysis_tier2.py` | 751 | 二级空间分析工具集 |
| 19 | `knowledge_graph.py` | 705 | 地理知识图谱（networkx DiGraph） |
| 20 | `utils.py` | 703 | 通用工具函数 |
| 21 | `agent.py` | 687 | Agent 定义、管道组装、工厂函数 |
| 22 | `virtual_sources.py` | 628 | 虚拟数据源 CRUD + Schema 映射 |
| 23 | `cli.py` | 609 | 命令行界面 |
| 24 | `tui.py` | 601 | 终端用户界面 |
| 25 | `user_tools.py` | 601 | 用户自定义声明式工具 |
| 26 | `watershed_analysis.py` | 580 | 流域分析 |
| 27 | `mcp_tool_registry.py` | 568 | MCP 工具注册表 |
| 28 | `stream_engine.py` | 540 | 流式数据引擎 |
| 29 | `storage_manager.py` | 533 | 存储管理器（S3/本地/PostGIS URI 路由） |
| 30 | `database_tools.py` | 513 | 数据库工具 |
| 31 | `graph_rag.py` | 507 | GraphRAG 检索增强生成 |
| 32 | `arcpy_tools.py` | 502 | ArcPy 桥接工具 |
| 33 | `workflow_templates.py` | 501 | 工作流模板 |
| 34 | `embedding_store.py` | 501 | **[NEW]** pgvector 嵌入缓存 |
| 35 | `team_manager.py` | 474 | 团队管理 |
| 36 | `arcpy_worker.py` | 471 | ArcPy 子进程 |
| 37 | `sharing.py` | 471 | 数据共享 |
| 38 | `auth.py` | 459 | 认证（密码哈希/暴力防护/注册） |
| 39 | `cloud_storage.py` | 453 | 云存储（OBS） |
| 40 | `code_exporter.py` | 443 | 代码导出器 |
| | 其他 76 个文件 | ~17,125 | 机器人/审计/插件/观测/任务/沙箱等 |

#### 工具集（data_agent/toolsets/，38 文件 / 7,491 行）

| # | 文件 | 行数 | 功能 |
|---|------|-----:|---------|
| 1 | `visualization_tools.py` | 1,310 | 专题制图（分级设色/气泡/热力/多图层） |
| 2 | `governance_tools.py` | 985 | 14 个治理审计工具 |
| 3 | `chart_tools.py` | 545 | 9 种 ECharts 交互图表 |
| 4 | `precision_tools.py` | 426 | 精度评估工具 |
| 5 | `data_cleaning_tools.py` | 397 | 数据清洗工具集 |
| 6 | `virtual_source_tools.py` | 377 | 5 个虚拟源工具 |
| 7 | `nl2sql_tools.py` | 352 | **[NEW]** NL2SQL 工具集 |
| 8 | `knowledge_base_tools.py` | 321 | 知识库工具 |
| 9 | `exploration_tools.py` | 293 | 数据探查工具 |
| 10 | `world_model_tools.py` | 290 | **[NEW]** 世界模型工具集 |
| 11 | `fusion_tools.py` | 253 | 4 个融合工具 |
| 12 | `analysis_tools.py` | 252 | 分析工具 |
| 13 | `skill_bundles.py` | 212 | 技能包工具 |
| 14 | `knowledge_graph_tools.py` | 207 | 知识图谱工具 |
| 15 | `report_tools.py` | 161 | 报告工具 |
| 16 | `storage_tools.py` | 159 | 存储工具 |
| 17 | `file_tools.py` | 146 | 文件工具 |
| 18 | `geo_processing_tools.py` | 117 | GIS 处理工具集入口 |
| 19 | `spark_tools.py` | 109 | Spark 工具 |
| 20 | `causal_world_model_tools.py` | 58 | **[NEW]** Angle C 因果世界模型工具集 |
| 21 | `mcp_hub_toolset.py` | 47 | MCP Hub 工具集入口 |
| 22 | `semantic_layer_tools.py` | 38 | 语义层工具集入口 |
| 23 | `__init__.py` | 35 | 注册表（37 个工具集） |
| 24 | `causal_inference_tools.py` | 31 | **[NEW]** Angle A 因果推断工具集 |
| 25 | `llm_causal_tools.py` | 27 | **[NEW]** Angle B LLM 因果推理工具集 |
| | 其他 13 个文件 | ~543 | 位置/团队/流式/管理/遥感/空间统计等 |

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

#### API 路由（data_agent/api/，14 文件 / 2,775 行）

| # | 文件 | 行数 |
|---|------|-----:|
| 1 | `mcp_routes.py` | 274 |
| 2 | `skills_routes.py` | 250 |
| 3 | `workflow_routes.py` | 215 |
| 4 | `kb_routes.py` | 186 |
| 5 | `virtual_routes.py` | 170 |
| 6 | `causal_world_model_routes.py` | 153 | **[NEW]** |
| 7 | `quality_routes.py` | 141 |
| 8 | `file_routes.py` | 139 |
| 9 | `bundle_routes.py` | 128 |
| 10 | `causal_routes.py` | 127 | **[NEW]** |
| 11 | `distribution_routes.py` | 125 |
| 12 | `world_model_routes.py` | 100 |
| 13 | `helpers.py` | 50 |
| 14 | `__init__.py` | 10 |

### 2.2 测试代码（113 文件 / 33,111 行）

**Top 10 最大测试文件：**

| # | 文件 | 行数 |
|---|------|-----:|
| 1 | `test_fusion_engine.py` | 1,936 |
| 2 | `test_mcp_hub.py` | 1,097 |
| 3 | `test_semantic_layer.py` | 1,082 |
| 4 | `test_frontend_api.py` | 824 |
| 5 | `test_llm_causal.py` | 816 | **[NEW]** |
| 6 | `test_causal_world_model.py` | 768 | **[NEW]** |
| 7 | `test_workflow_engine.py` | 733 |
| 8 | `test_virtual_sources.py` | 708 |
| 9 | `test_data_catalog.py` | 703 |
| 10 | `test_knowledge_base.py` | 584 |

### 2.3 Python 代码量分布汇总

| 类别 | 文件数 | 行数 | 占 Python 总量 |
|------|------:|-----:|------:|
| 核心模块 | 116 | 52,198 | 52.4% |
| 工具集 | 38 | 7,491 | 7.5% |
| 融合引擎 | 26 | 2,847 | 2.9% |
| API 路由 | 14 | 2,775 | 2.8% |
| 连接器 | 9 | 1,013 | 1.0% |
| 其他子包 | 5 | 249 | 0.2% |
| **生产代码小计** | **208** | **66,573** | **66.8%** |
| 测试代码 | 113 | 33,111 | 33.2% |
| **Python 合计** | **321** | **99,684** | **100%** |

---

## 三、前端详细统计（36 源文件 / 11,861 行）

### 3.1 React 组件（32 个 TSX 文件 / 8,952 行）

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
| 9 | `DataPanel.tsx` | 199 | 数据面板框架（22 个 Tab 路由） |
| 10 | `ChartView.tsx` | 42 | ECharts 图表视图 |
| 11 | `main.tsx` | 19 | 入口 |

**DataPanel Tab 组件（21 文件 / 4,934 行）：**

| # | 文件 | 行数 | Tab 名称 |
|---|------|-----:|---------|
| 1 | `CapabilitiesTab.tsx` | 622 | 技能/工具/Agent 能力视图 |
| 2 | `WorldModelTab.tsx` | 516 | 世界模型 + 干预/反事实模式 |
| 3 | `FileListTab.tsx` | 416 | 文件管理 + 数据表格 |
| 4 | `VirtualSourcesTab.tsx` | 414 | 虚拟数据源管理 |
| 5 | `CausalReasoningTab.tsx` | 384 | **[NEW]** 因果推理（DAG/反事实/机制/情景） |
| 6 | `CatalogTab.tsx` | 379 | 数据目录 + 语义搜索 |
| 7 | `KnowledgeBaseTab.tsx` | 354 | 知识库 |
| 8 | `ToolsTab.tsx` | 292 | MCP 工具 |
| 9 | `WorkflowsTab.tsx` | 275 | 工作流管理 |
| 10 | `GovernanceTab.tsx` | 264 | 数据治理仪表盘 |
| 11 | `ObservabilityTab.tsx` | 145 | 可观测性追踪 |
| 12 | `MarketplaceTab.tsx` | 140 | 技能市场 |
| 13 | `MemorySearchTab.tsx` | 136 | 记忆搜索 |
| 14 | `UsageTab.tsx` | 97 | Token 用量 |
| 15 | `GeoJsonEditorTab.tsx` | 90 | GeoJSON 编辑器 |
| 16 | `ChartsTab.tsx` | 89 | 图表 |
| 17 | `TasksTab.tsx` | 75 | 任务队列 |
| 18 | `AnalyticsTab.tsx` | 70 | 管道分析 |
| 19 | `HistoryTab.tsx` | 70 | 管道历史 |
| 20 | `SuggestionsTab.tsx` | 70 | 智能建议 |
| 21 | `TemplatesTab.tsx` | 66 | 模板管理 |

### 3.2 其他前端源文件

| 类型 | 文件数 | 行数 |
|------|------:|-----:|
| TypeScript 模块（contexts.ts, utils.ts） | 2 | 117 |
| CSS 样式（layout.css） | 1 | 2,770 |
| HTML（index.html） | 1 | 22 |

---

## 四、提示词 & Skill 指令（41 文件 / 3,970 行）

### 4.1 Agent 提示词（YAML，4 文件 / 796 行）

| 文件 | 行数 | 用途 |
|------|-----:|------|
| `prompts/optimization.yaml` | 295 | 优化管道提示词 |
| `prompts/general.yaml` | 225 | 通用管道提示词 |
| `prompts/planner.yaml` | 151 | 规划 Agent 提示词 |
| `prompts/governance.yaml` | 125 | 治理管道提示词 |

### 4.2 Skill 定义（37 文件 / 3,174 行）

| 类型 | 文件数 | 行数 |
|------|------:|-----:|
| SKILL.md（21 个技能定义） | 21 | 2,154 |
| references/*.md（参考资料） | 14 | 939 |
| assets/*.md（模板） | 2 | 81 |

**21 个内置技能清单：**

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
| 21 | `data-version-control` | 48 | 数据版本 |

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

### 5.3 SQL 迁移脚本（43 文件 / 1,268 行）

最大迁移文件：
- `004_enable_rls.sql` — 166 行（行级安全策略）
- `014_create_data_catalog.sql` — 119 行
- `012_create_teams.sql` — 106 行

### 5.4 YAML 配置（非提示词，8 文件 / 1,464 行）

| 文件 | 行数 | 用途 |
|------|-----:|------|
| `locales/en.yaml` | 220 | 英文翻译 |
| `locales/zh.yaml` | 220 | 中文翻译 |
| `prompts.yaml`（旧版） | 310 | 旧版提示词 |
| `semantic_catalog.yaml` | 247 | 语义目录 |
| `standards/gb_t_21010_2017.yaml` | 98 | 国标编码表 |
| `standards/dltb_2023.yaml` | 91 | DLTB 字段标准 |
| `mcp_servers.yaml` | 62 | MCP 服务配置 |
| `standards/code_mappings/*.yaml` | ~216 | 编码映射 |

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

## 六、文档（101 文件 / 26,824 行）

### 6.1 技术文档（docs/ Markdown，45 文件 / 17,260 行）

| # | 文件 | 行数 | 内容 |
|---|------|-----:|------|
| 1 | `world-model-tech-preview-design.md` | 1,893 | **[NEW]** 世界模型方案设计（A/B/C/D 四方案 + 验证） |
| 2 | `technical-guide.md` | 1,461 | 技术指南（21 章） |
| 3 | `agent-observability-enhancement.md` | 1,393 | 可观测性增强方案 |
| 4 | `technical_paper_fusion_engine.md` | 1,270 | 融合引擎技术论文 |
| 5 | `spark-datalake-integration-architecture.md` | 946 | Spark 数据湖架构 |
| 6 | `enterprise-architecture.md` | 866 | 企业级架构 |
| 7 | `roadmap.md` | 850 | 项目路线图 |
| 8 | `GIS_Data_Agent_Pitch_Deck.md` | 650 | 产品宣讲 |
| 9 | `RELEASE_NOTES_v7.0.md` | 567 | 发版说明 |
| 10 | `semantic_layer_architecture.md` | 530 | 语义层架构 |
| | 其他 35 个文件 | ~5,834 | |

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
| 测试 / 生产代码比 | 33,111 / 66,573 = **49.7%** | 优秀（行业标准 30-60%） |
| 文档 / 代码比 | 26,824 / 78,434 = **34.2%** | 优秀 |
| 最大单文件 | `app.py` 3,598 行 | 偏大（已拆分 intent_router + pipeline_helpers） |
| 前后端比例 | 后端 99,684 / 前端 11,861 = **8.4:1** | 后端密集型项目 |
| 平均文件大小（生产 Python） | 66,573 / 208 = **320 行/文件** | 适中 |

### 按功能域分布

| 功能域 | 行数 | 占生产代码 |
|--------|-----:|------:|
| 核心框架（app/agent/intent/pipeline） | ~6,230 | 9.4% |
| REST API 层（frontend_api + api/） | ~5,612 | 8.4% |
| GIS 处理 & 分析 | ~5,747 | 8.6% |
| 因果推断（A + B + C） | ~3,245 | 4.9% |
| 世界模型 + 嵌入缓存 | ~1,623 | 2.4% |
| 数据治理 & 质量 | ~2,830 | 4.2% |
| 语义层 & 数据目录 | ~3,021 | 4.5% |
| 融合引擎 | ~2,847 | 4.3% |
| 工具集框架 | ~7,491 | 11.3% |
| 工作流 & 任务 | ~2,327 | 3.5% |
| MCP / A2A / 连接器 | ~2,554 | 3.8% |
| 知识图谱 & RAG | ~2,086 | 3.1% |
| 认证 & 安全 | ~1,399 | 2.1% |
| DRL 优化 | ~1,231 | 1.8% |
| 可观测性 & 运维 | ~1,281 | 1.9% |
| 其他（CLI/TUI/Bot/存储等） | ~17,049 | 25.6% |

---

## 八、汇总

```
D:\adk 项目代码量总计 (v15.3)
├── Python 后端 .............. 99,684 行 (321 文件)
│   ├── 生产代码 ............. 66,573 行 (208 文件)
│   └── 测试代码 ............. 33,111 行 (113 文件)
├── 前端源码 ................. 11,861 行 (36 文件)
├── 提示词 & Skill ........... 3,970 行 (41 文件)
├── SQL 迁移 ................. 1,268 行 (43 文件)
├── YAML 配置 ................ 1,464 行 (8 文件)
├── Docker / K8s ............. 951 行 (15 文件)
├── CI/CD .................... 211 行 (1 文件)
├── 文档 ..................... 26,824 行 (101 文件)
├── DITA 生成产物 ............ 2,216 行 (~50 文件)
├── Chainlit 翻译 ............ 10,122 行 (40 文件)
├── 项目配置 ................. 6,557 行 (20 文件)
└── JSON/其他 ................ ~1,000 行
────────────────────────────────────────
手写代码（Python+前端+SQL+Prompt+Config）
                             = 118,348 行
项目全量（含文档/翻译/生成物）
                             ≈ 165,128 行 (~676 文件)
```

### v14.5 → v15.3 增长对比

| 指标 | v14.5 | v15.3 | 增长 |
|------|------:|------:|------:|
| Python 生产代码 | 55,886 行 | 66,573 行 | +10,687 (+19.1%) |
| Python 测试代码 | 29,346 行 | 33,111 行 | +3,765 (+12.8%) |
| 前端源码 | 9,724 行 | 11,861 行 | +2,137 (+22.0%) |
| 工具集文件 | 29 | 38 | +9 |
| API 路由文件 | 9 | 14 | +5 |
| DataPanel Tab | 18 | 21 | +3 |
| REST API 端点 | ~124 | ~178 | +54 |
| 手写代码总量 | ~103,316 行 | ~118,348 行 | +15,032 (+14.5%) |
| 项目全量 | ~156,906 行 | ~165,128 行 | +8,222 (+5.2%) |
