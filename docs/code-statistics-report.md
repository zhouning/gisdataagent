# Data Agent 项目代码量统计报告

> **统计日期**: 2026-04-10
> **项目版本**: v23.0 (Roadmap 可做项全部清零)
> **统计范围**: `D:\adk` 全仓库（排除 `.venv/`、`node_modules/`、`dist/`、`__pycache__/`）

---

## 一、总览

| 大类 | 文件数 | 行数 | 占比 |
|------|------:|-----:|-----:|
| **Python 后端（生产代码）** | 280 | 91,177 | 40.2% |
| **Python 测试代码** | 171 | 45,124 | 19.9% |
| **前端应用源码（TSX/TS/CSS/HTML）** | 48 | 16,708 | 7.4% |
| **Agent 提示词 & Skill 指令** | ~50 | 4,635 | 2.0% |
| **SQL 迁移脚本** | 64 | 2,118 | 0.9% |
| **YAML 配置（非提示词）** | ~12 | 1,578 | 0.7% |
| **Docker / K8s 基础设施** | ~15 | 1,136 | 0.5% |
| **CI/CD** | 2 | 522 | 0.2% |
| **文档（Markdown）** | 98 | 40,688 | 17.9% |
| **Chainlit 国际化翻译** | 40 | 10,122 | 4.5% |
| **项目配置 & 依赖** | ~20 | ~6,600 | 2.9% |
| **其他（JSON/lock 等）** | ~20 | ~6,000 | 2.6% |
| **合计** | **~820** | **~226,408** | **100%** |

### 核心指标

| 指标 | 数值 |
|------|------|
| **手写代码总量（排除生成产物/lock/翻译）** | **~161,781 行** |
| **Python 总行数** | 136,301 行（451 文件） |
| **前端应用源码** | 16,708 行（48 文件） |
| **测试覆盖比** | 测试 45,124 行 / 生产 91,177 行 = **49.5%** |
| **文档总量** | 40,688 行（98 文件） |
| **REST API 端点** | 280 |
| **DB 迁移** | 64 |
| **测试用例** | 3,588 |

---

## 二、Python 后端详细统计（451 文件 / 136,301 行）

### 2.1 生产代码（280 文件 / 91,177 行）

#### Top 25 最大生产文件

| # | 文件 | 行数 | 功能说明 |
|---|------|-----:|---------|
| 1 | `app.py` | 3,948 | Chainlit UI 主入口、RBAC、文件上传、图层控制 |
| 2 | `frontend_api.py` | 3,438 | 280 个 REST API 端点（主路由） |
| 3 | `workflow_engine.py` | 1,938 | 工作流引擎：CRUD + DAG + Cron + SLA |
| 4 | `semantic_layer.py` | 1,847 | 语义层目录 + 3 级层级 + 5 分钟 TTL 缓存 |
| 5 | `data_catalog.py` | 1,547 | 数据湖目录 + 沿袭追踪 + 语义搜索 |
| 6 | `causal_inference.py` | 1,247 | Angle A 因果推断（PSM/ERF/DiD/Granger/GCCM/CF） |
| 7 | `gis_processors.py` | 1,181 | GIS 处理核心（空间分析函数） |
| 8 | `benchmark_fusion.py` | 1,148 | 融合引擎基准测试 |
| 9 | `world_model.py` | 1,122 | AlphaEarth + LatentDynamicsNet JEPA 世界模型 |
| 10 | `causal_world_model.py` | 1,049 | Angle C 因果世界模型（干预/反事实） |
| 11 | `drl_engine.py` | 1,017 | 深度强化学习优化引擎（7 场景 + NSGA-II） |
| 12 | `knowledge_base.py` | 1,006 | 知识库 + GraphRAG + 案例库 |
| 13 | `remote_sensing.py` | 974 | 遥感分析（NDVI/DEM/LULC/变化检测） |
| 14 | `llm_causal.py` | 949 | Angle B LLM 因果推理（DAG/反事实/机制） |
| 15 | `mcp_hub.py` | 920 | MCP Hub 管理器（DB + YAML + 3 传输协议） |
| 16 | `agent.py` | 853 | Agent 定义、管道组装、工厂函数 |
| 17 | `custom_skills.py` | 813 | 自定义技能 CRUD + 版本 + 评分 + 审批 |
| 18 | `advanced_analysis.py` | 803 | 高级分析（时间序列/情景模拟/网络） |
| 19 | `geocoding.py` | 784 | 地理编码（批量/POI/行政区划） |
| 20 | `dreamer_env.py` | 757 | DreamerEnv（World Model Dreamer 集成） |
| 21 | `spatial_analysis_tier2.py` | 751 | 二级空间分析工具集 |
| 22 | `report_generator.py` | 715 | 报告生成引擎 |
| 23 | `knowledge_graph.py` | 705 | 地理知识图谱（networkx DiGraph） |
| 24 | `evaluator_registry.py` | 665 | 可插拔评估器注册表（15 内置评估器） |
| 25 | `virtual_sources.py` | 628 | 虚拟数据源 CRUD + Schema 映射 |

#### 工具集（data_agent/toolsets/，41 文件 / 8,969 行）

| # | 文件 | 行数 | 功能 |
|---|------|-----:|------|
| 1 | `visualization_tools.py` | 1,310 | 专题制图（分级设色/气泡/热力/多图层） |
| 2 | `governance_tools.py` | 1,235 | 18 个治理审计工具 |
| 3 | `data_cleaning_tools.py` | 553 | 11 个数据清洗工具 |
| 4 | `chart_tools.py` | 545 | 9 种 ECharts 交互图表 |
| 5 | `fusion_tools.py` | 531 | 融合工具（10 种策略） |
| 6 | `precision_tools.py` | 505 | 精度评估工具 |
| 7 | `virtual_source_tools.py` | 377 | 虚拟源工具 |
| 8 | `nl2sql_tools.py` | 353 | NL2SQL 工具集 |
| 9 | `knowledge_base_tools.py` | 321 | 知识库工具 |
| 10 | `world_model_tools.py` | 290 | 世界模型工具集 |
| 11 | `exploration_tools.py` | 293 | 数据探查工具 |
| 12 | `analysis_tools.py` | 276 | 分析工具 |
| 13 | `file_tools.py` | 241 | 文件工具 |
| 14 | `knowledge_graph_tools.py` | 207 | 知识图谱工具 |
| | 其他 27 个文件 | ~2,531 | 位置/团队/流式/管理/遥感/空间统计/因果/Dreamer 等 |

#### API 路由（data_agent/api/，24 文件 / 4,992 行）

| # | 文件 | 行数 |
|---|------|-----:|
| 1 | `mcp_routes.py` | 最大 |
| 2 | `skills_routes.py` | |
| 3 | `workflow_routes.py` | |
| 4 | `kb_routes.py` | |
| 5 | `virtual_routes.py` | |
| 6-24 | 其他 19 个文件 | |
| | **合计** | **4,992** |

新增路由模块（v16.0→v23.0）：`context_routes`, `feedback_routes`, `fusion_v2_routes`, `lineage_routes`, `messaging_routes`, `metadata_routes`, `reference_query_routes`, `semantic_model_routes`, `tile_routes`, `topology_routes`

#### 融合引擎（data_agent/fusion/，32 文件 / 3,988 行）

含核心模块（profiling/matching/execution/validation/conflict_resolver/explainability）+ 10 种融合策略。

#### 连接器（data_agent/connectors/，11 文件 / 1,217 行）

BaseConnector ABC + ConnectorRegistry + 10 个连接器（WFS/WMS/STAC/OGC API/ArcGIS REST/Custom API/Database/Object Storage/Reference Data/SaveMyself）。

### 2.2 测试代码（171 文件 / 45,124 行）

**Top 15 最大测试文件：**

| # | 文件 | 行数 |
|---|------|-----:|
| 1 | `test_fusion_engine.py` | 1,937 |
| 2 | `test_mcp_hub.py` | 1,097 |
| 3 | `test_semantic_layer.py` | 1,082 |
| 4 | `test_frontend_api.py` | 824 |
| 5 | `test_llm_causal.py` | 816 |
| 6 | `test_causal_world_model.py` | 768 |
| 7 | `test_workflow_engine.py` | 733 |
| 8 | `test_virtual_sources.py` | 708 |
| 9 | `test_data_catalog.py` | 703 |
| 10 | `test_knowledge_base.py` | 584 |
| 11 | `test_remote_sensing.py` | 580 |
| 12 | `test_toolsets.py` | 553 |
| 13 | `test_evaluator_registry.py` | 535 |
| 14 | `test_team.py` | 534 |
| 15 | `test_tile_server.py` | 518 |

### 2.3 Python 代码量分布汇总

| 类别 | 文件数 | 行数 | 占 Python 总量 |
|------|------:|-----:|------:|
| 核心模块（data_agent/ 根目录） | ~180 | ~71,011 | 52.1% |
| 工具集（toolsets/） | 41 | 8,969 | 6.6% |
| API 路由（api/） | 24 | 4,992 | 3.7% |
| 融合引擎（fusion/） | 32 | 3,988 | 2.9% |
| 连接器（connectors/） | 11 | 1,217 | 0.9% |
| 其他子包 | ~10 | ~1,000 | 0.7% |
| **生产代码小计** | **280** | **91,177** | **66.9%** |
| 测试代码 | 171 | 45,124 | 33.1% |
| **Python 合计** | **451** | **136,301** | **100%** |

---

## 三、前端详细统计（48 源文件 / 16,708 行）

### 3.1 React 组件（45 个 TSX 文件 / 13,631 行 TSX+TS）

**顶层组件：**

| # | 文件 | 行数 | 功能 |
|---|------|-----:|------|
| 1 | `MapPanel.tsx` | 1,168 | Leaflet 2D 地图 + 图层控制 + 标注 + 底图切换 + 跨图层关联高亮 |
| 2 | `AdminDashboard.tsx` | 680 | 管理仪表盘（指标/用户/审计日志） |
| 3 | `ChatPanel.tsx` | 527 | 聊天面板（消息/流式/操作卡片/FeedbackBar） |
| 4 | `Map3DView.tsx` | 517 | deck.gl + MapLibre 3D 渲染器 |
| 5 | `WorkflowEditor.tsx` | 483 | ReactFlow DAG 编辑器 |

**DataPanel Tab 组件（31 文件）：**

| # | 文件 | 行数 | Tab 名称 |
|---|------|-----:|---------|
| 1 | `CapabilitiesTab.tsx` | 749 | 技能/工具/Agent 能力视图 + AI 生成 |
| 2 | `QcMonitorTab.tsx` | 551 | 质检监控 |
| 3 | `WorldModelTab.tsx` | 516 | 世界模型 + 干预/反事实模式 |
| 4 | `WorkflowsTab.tsx` | 497 | 工作流管理 |
| 5 | `ToolsTab.tsx` | 489 | MCP 工具 |
| 6 | `OptimizationTab.tsx` | 462 | DRL 优化 + 动画回放 |
| 7 | `GovernanceTab.tsx` | 437 | 数据治理仪表盘 |
| 8 | `VirtualSourcesTab.tsx` | 429 | 虚拟数据源管理 |
| 9 | `FileListTab.tsx` | 416 | 文件管理 + 数据表格 |
| 10 | `TopologyTab.tsx` | 402 | 拓扑验证 |
| 11 | `CausalReasoningTab.tsx` | 384 | 因果推理 |
| 12 | `CatalogTab.tsx` | 382 | 数据目录 + 语义搜索 |
| 13 | `FieldMappingEditor.tsx` | 353 | 字段映射编辑器 |
| 14 | `KnowledgeBaseTab.tsx` | 354 | 知识库 |
| | 其他 17 个 Tab | ~2,680 | 分析/历史/用量/GeoJSON/模板/建议/任务/反馈等 |

### 3.2 其他前端源文件

| 类型 | 文件数 | 行数 |
|------|------:|-----:|
| TypeScript 模块（contexts.ts, utils.ts） | 2 | ~117 |
| CSS 样式（layout.css） | 1 | 3,077 |

---

## 四、提示词 & Skill 指令（~50 文件 / ~4,635 行）

### 4.1 Agent 提示词（YAML，5 文件 / 972 行）

| 文件 | 行数 | 用途 |
|------|-----:|------|
| `prompts/optimization.yaml` | 295 | 优化管道提示词 |
| `prompts/general.yaml` | 226 | 通用管道提示词 |
| `prompts/planner.yaml` | 190 | 规划 Agent 提示词 |
| `prompts/multi_agent.yaml` | 136 | 多 Agent 协作提示词 |
| `prompts/governance.yaml` | 125 | 治理管道提示词 |

### 4.2 Skill 定义（25 个技能目录 / ~3,663 行）

| 类型 | 文件数 | 行数 |
|------|------:|-----:|
| SKILL.md / skill.yaml（25 个技能定义） | 25 | ~2,500 |
| references/*.md（参考资料） | ~15 | ~1,000 |
| assets/*.md（模板） | ~3 | ~163 |

---

## 五、基础设施 & 配置

### 5.1 SQL 迁移脚本（64 文件 / 2,118 行）

最新迁移：`057_model_config.sql`

### 5.2 数据标准（9 文件 / 1,578 行）

| 文件 | 行数 | 用途 |
|------|-----:|------|
| `qc_workflow_templates.yaml` | 462 | QC 工作流模板（3 预设） |
| `defect_taxonomy.yaml` | 319 | 测绘缺陷分类（30 编码） |
| `gb_t_24356.yaml` | 216 | 测绘质检标准 |
| `gis_ontology.yaml` | 153 | GIS 领域本体 |
| `rs_experience_pool.yaml` | 107 | 遥感经验池 |
| `gb_t_21010_2017.yaml` | 98 | 国标编码表 |
| `dltb_2023.yaml` | 91 | DLTB 字段标准 |
| `satellite_presets.yaml` | 75 | 卫星数据预设 |
| `guardrail_policies.yaml` | 57 | 安全策略 |

### 5.3 Docker / K8s（~15 文件 / ~1,136 行）

Docker: 657 行（Dockerfile + docker-compose × 3 + entrypoint + db-init）
K8s: 479 行（deployment + statefulset + HPA + services + configmaps）

### 5.4 CI/CD（2 文件 / 522 行）

`.github/workflows/ci.yml` — test + frontend + evaluation + route-eval 4 个 job

---

## 六、文档（98 文件 / 40,688 行）

docs/ 目录下 98 个 Markdown 文件，涵盖技术指南、架构设计、路线图、竞品分析、论文、部署文档等。

---

## 七、关键比例分析

### 代码结构健康度

| 指标 | 数值 | 评价 |
|------|------|------|
| 测试 / 生产代码比 | 45,124 / 91,177 = **49.5%** | 优秀（行业标准 30-60%） |
| 文档 / 代码比 | 40,688 / 136,301 = **29.9%** | 优秀 |
| 最大单文件 | `app.py` 3,948 行 | 偏大（已拆分 intent_router + pipeline_helpers + api/） |
| 前后端比例 | 后端 136,301 / 前端 16,708 = **8.2:1** | 后端密集型项目 |
| 平均文件大小（生产 Python） | 91,177 / 280 = **326 行/文件** | 适中 |

### 按功能域分布（生产代码）

| 功能域 | 估算行数 | 占比 |
|--------|------:|------:|
| 核心框架（app/agent/intent/pipeline/middleware） | ~8,500 | 9.3% |
| REST API 层（frontend_api + api/） | ~8,430 | 9.2% |
| GIS 处理 & 空间分析 | ~6,500 | 7.1% |
| 语义层 & 数据目录 & 语义模型 | ~4,000 | 4.4% |
| 因果推断（A + B + C） | ~3,245 | 3.6% |
| 世界模型 + Dreamer | ~1,879 | 2.1% |
| 数据治理 & 质量 & 标准 | ~2,800 | 3.1% |
| 融合引擎 | ~3,988 | 4.4% |
| 工具集框架 | ~8,969 | 9.8% |
| 工作流 & 任务 | ~2,500 | 2.7% |
| MCP / A2A / 连接器 | ~2,400 | 2.6% |
| 知识图谱 & RAG & KB | ~2,200 | 2.4% |
| 认证 & 安全 & Guardrails | ~1,800 | 2.0% |
| DRL 优化 | ~1,017 | 1.1% |
| 可观测性 & 运维 & 审计 | ~1,500 | 1.6% |
| 遥感智能体 | ~1,500 | 1.6% |
| 上下文工程 & 反馈 & 评估 | ~2,000 | 2.2% |
| 其他（CLI/Bot/存储/编码等） | ~27,649 | 30.3% |

---

## 八、汇总

```
D:\adk 项目代码量总计 (v23.0)
├── Python 后端 .............. 136,301 行 (451 文件)
│   ├── 生产代码 ............. 91,177 行 (280 文件)
│   │   ├── 核心模块 ......... ~71,011 行 (~180 文件)
│   │   ├── 工具集 ........... 8,969 行 (41 文件)
│   │   ├── API 路由 ......... 4,992 行 (24 文件)
│   │   ├── 融合引擎 ......... 3,988 行 (32 文件)
│   │   └── 连接器 ........... 1,217 行 (11 文件)
│   └── 测试代码 ............. 45,124 行 (171 文件)
├── 前端源码 ................. 16,708 行 (48 文件)
│   ├── TSX/TS ............... 13,631 行 (47 文件)
│   └── CSS .................. 3,077 行 (1 文件)
├── 提示词 & Skill ........... ~4,635 行 (~50 文件)
├── SQL 迁移 ................. 2,118 行 (64 文件)
├── 数据标准 YAML ............ 1,578 行 (9 文件)
├── Docker / K8s ............. ~1,136 行 (~15 文件)
├── CI/CD .................... 522 行 (2 文件)
├── 文档 ..................... 40,688 行 (98 文件)
├── Chainlit 翻译 ............ 10,122 行 (40 文件)
└── 项目配置 & 其他 .......... ~12,600 行
────────────────────────────────────────
手写代码（Python+前端+SQL+Prompt+Config）
                             ≈ 161,781 行
项目全量（含文档/翻译/配置）
                             ≈ 226,408 行 (~820 文件)
```

### 版本增长趋势

| 指标 | v14.5 | v16.0 | v23.0 | v16.0→v23.0 增长 |
|------|------:|------:|------:|------:|
| Python 生产代码 | 55,886 行 | 71,845 行 | 91,177 行 | +19,332 (+26.9%) |
| Python 测试代码 | 29,346 行 | 35,287 行 | 45,124 行 | +9,837 (+27.9%) |
| 前端源码 | 9,724 行 | 12,534 行 | 16,708 行 | +4,174 (+33.3%) |
| 工具集文件 | 29 | 40 | 41 | +1 |
| API 路由文件 | 9 | 17 | 24 | +7 |
| DataPanel Tab | 18 | 23 | 31 | +8 |
| REST API 端点 | ~124 | ~228 | ~280 | +52 |
| SQL 迁移文件 | 38 | 48 | 64 | +16 |
| 测试文件 | ~90 | 118 | 171 | +53 |
| 测试用例 | ~2,200 | ~2,966 | ~3,588 | +622 |
| 手写代码总量 | ~103,316 行 | ~127,191 行 | ~161,781 行 | +34,590 (+27.2%) |
| 项目全量 | ~156,906 行 | ~176,144 行 | ~226,408 行 | +50,264 (+28.5%) |

### v14.5 → v23.0 全程增长

| 指标 | v14.5 | v23.0 | 绝对增长 | 增长率 |
|------|------:|------:|------:|------:|
| Python 生产代码 | 55,886 行 | 91,177 行 | +35,291 | **+63.1%** |
| Python 测试代码 | 29,346 行 | 45,124 行 | +15,778 | **+53.8%** |
| 前端源码 | 9,724 行 | 16,708 行 | +6,984 | **+71.8%** |
| REST API 端点 | ~124 | ~280 | +156 | **+125.8%** |
| 手写代码总量 | ~103,316 行 | ~161,781 行 | +58,465 | **+56.6%** |
| 项目全量 | ~156,906 行 | ~226,408 行 | +69,502 | **+44.3%** |
