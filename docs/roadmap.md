# GIS Data Agent — Roadmap

**Last updated**: 2026-04-30 &nbsp;|&nbsp; **Current version**: v24.1 &nbsp;|&nbsp; **ADK**: v1.27.2

> 参照标杆：SeerAI Geodesic（地理空间数据编排）、OpenClaw（Agent 交互）、Frontier（企业治理）、CoWork（多 Agent 协作）、**DeerFlow v2.0（ByteDance 通用 Agent Harness — 工程质量）**、**SIGMOD 2026 Data Agent Levels（L0-L5 自主性分级）**、**AgentArts（华为云企业级智能体平台 — 平台能力）**、**Datus.ai（开源数据工程智能体 — 上下文工程 + 反馈飞轮）**、**Hermes Agent（通用 Agent Runtime — learning loop + 持久记忆 + 多入口网关）**、**Atlan / Alation / Ataccama（Agentic Governance + Active Metadata）**、**DataWorks / Dataphin（数据开发治理一体化 + Agent）**、**袋鼠云（多模态数据中台）**
>
> 核心战略：**从 Data Agent 自主性演进，升级为 Agentic Spatial Data Governance Platform（智能体驱动的时空数据治理平台）**——保持智能层 + 交互层领先，把空间数据治理、活跃元数据、声明式治理、数据产品化和多模态治理做成面向行业客户的产品能力；从"用户带数据来"转向"Agent 主动发现、治理、编排和运营数据"，从"一次性回答"转向"越用越准、越用越能沉淀的数据治理飞轮"。
>
> **Data Agent Level**: v24.1 = L3.5（垂直场景 + 显式路由 + 域标准 + NL2SQL 16/16）→ v25.0 起进入 **Agentic Governance** 阶段；下一阶段以数据治理产品化交付为主，Hermes 对标能力仍保留在观察池，仅择机落地低成本试点

---

## 已完成 (v24.1) — NL2SQL Benchmark 16/16 + DeepSeek 兼容 + CostGuard 前端配置

> **主题**: NL2SQL 从"需要英文表名"到"纯自然语言查询"，benchmark 全量通过

### NL2SQL 增强
- [x] **Benchmark v2 去英文表名** — 16 题 question 全部改为纯中文自然语言，不再包含英文表名
- [x] **双向子串匹配** — `_match_aliases()` 支持 alias→text 和 text→alias 双向匹配
- [x] **中文同义词补齐** — 12 张 cq_* 表的 `agent_semantic_sources.synonyms` 全部补充短别名
- [x] **可复用空间 few-shot** — 2 条 canonical pattern (AOI 距离 + 面面相交聚合) 入库 `agent_reference_queries`
- [x] **智能 few-shot 跳过** — 简单单表查询不再触发 embedding 检索，grounding 提速 5-8x
- [x] **SRID 修复** — `cq_ghfw` 和 `cq_jsydgzq` 从 SRID=0 更新为 4523，同步 `agent_semantic_sources`
- [x] **Golden SQL 优化** — MEDIUM_02 空间 join 从 219s→0.5s（转换小表 + GiST 索引命中）
- [x] **Grounding 单位标注** — 列 unit 字段显示在 grounding prompt 中（如"万人"）
- [x] **Grounding SRID 建议** — SRID 不一致时给出具体 Transform 目标 SRID
- [x] **Benchmark 题目修正** — EASY_01 去歧义、EASY_03 改措辞、HARD_03 重写 golden SQL
- [x] **SQL 语法修复** — `reference_queries.py` 的 `:tags::jsonb` 改为 `CAST(:tags AS jsonb)`

### DeepSeek 兼容
- [x] **CoT 泄露清理** — 后端缓冲 sub_agent_direct 输出 + `clean_cot_leakage()` 正则清理
- [x] **前端显示层兜底** — `ChatPanel.tsx` 的 `cleanCotLeakage()` 对 assistant 消息做最终清理
- [x] **标准拒绝格式** — 写操作拒绝和不存在字段拒绝统一为一句标准文案
- [x] **LIMIT 硬规则** — NL2SQL prompt 强制所有 SELECT 必须包含 LIMIT

### CostGuard 前端配置
- [x] **AdminDashboard 成本控制 tab** — 3 个输入框（警告阈值/中止阈值/USD 上限）+ 保存
- [x] **REST API** — `GET/PUT /api/admin/cost-guard-config`（admin only）
- [x] **DB 持久化** — 复用 `agent_model_config` 表，`ModelConfigManager` 扩展 3 个 cost_guard key
- [x] **CostGuardPlugin 读 DB** — 优先从 DB 读取阈值，DB 不可用时降级到 env var

---

## 已完成 (v12.2)

- [x] 能力浏览 Tab (CapabilitiesView) — 内置技能/自定义技能/工具集/用户工具聚合展示
- [x] Custom Skills 前端 CRUD — 创建/编辑/删除自定义 Agent
- [x] User-Defined Tools Phase 1 — 声明式工具模板 (http_call / sql_query / file_transform / chain)
- [x] UserToolset — 用户工具暴露给 ADK Agent
- [x] 多 Agent Pipeline 编排 — WorkflowEditor 支持 Skill Agent 节点 + DAG 执行
- [x] 面板拖拽调整宽度 (240-700px)
- [x] DataPanel Tab 横向滚动
- [x] SEC-1~3: DB 降级后门移除、暴力破解防护、SQL 注入 Guardrail
- [x] Skill Bundles 前端 UI — bundle 列表、创建/编辑表单、toolset/skill 多选
- [x] Knowledge Base GraphRAG UI — 图构建按钮、实体列表、图谱搜索
- [x] User Tools Phase 2: Python 沙箱 — AST 验证 + subprocess 隔离 + 环境清洗
- [x] S-2: 线程安全 — _mcp_started / _a2a_started_at 双检锁
- [x] F-2: 全局回调移除 — window.__* → CustomEvent
- [x] SEC-4: Prompt 注入增强 — 24 模式 + 安全边界包裹
- [x] WorkflowEditor 实时执行状态 — 轮询 run status + per-node 状态面板
- [x] ADK list_skills_in_dir 采用 — 替代手动 YAML 解析
- [x] S-4 API 拆分 — api/helpers + bundle_routes + kb_routes + mcp_routes + workflow_routes + skills_routes (42%)
- [x] 启动缺表修复 — workflow_templates + skill_bundles 表初始化
- [x] BP-3 分析血缘自动记录 — pipeline_run_id ContextVar + tool_params 传递 + KG derives_from/feeds_into 边
- [x] 血缘 DAG 可视化 — DataPanel 资产详情横向 DAG 布局 (SVG 箭头 + 类型徽章)
- [x] BP-5 行业分析模板 (首批) — 城市热岛效应/植被变化检测/土地利用优化 3 个模板
- [x] CapabilitiesView 行业分组 — 行业模板过滤器 + /api/templates 集成
- [x] Cartographic Precision UI — Space Grotesk + Teal/Amber + Stone 暖白 + 等高线登录页

---

## 已完成 (v13.0) — 虚拟数据层

> 从"9 个静态资产"到"按需连接多源数据"（参照 SeerAI Entanglement Engine）

- [x] **BP-1 VirtualDataSource 注册表** — `virtual_sources.py`: CRUD + Fernet 加密，支持 `wfs` / `stac` / `ogc_api` / `custom_api` 四种源类型，零复制按需查询
- [x] **WFS/STAC/OGC API 连接器** — 4 个 async 连接器 (`query_wfs`, `search_stac`, `query_ogc_api`, `query_api`)，支持 bbox + CQL 空间过滤
- [x] **查询时 CRS 自动对齐** — 连接器返回 GeoDataFrame 后自动 `to_crs(target_crs)`
- [x] **Schema 基础映射** — `apply_schema_mapping()` 列名重映射（语义匹配 fallback 进行中）
- [x] **连接器健康监控** — `check_source_health()` 端点连通性检测 + DataPanel 健康状态指示灯
- [x] **VirtualSourceToolset** — 5 个 ADK 工具，挂载到 General + Planner pipeline (24 toolsets)
- [x] **REST API** — 6 个端点 `/api/virtual-sources/*` (101 total endpoints)
- [x] **前端 "数据源" Tab** — VirtualSourcesView: 列表/新增/编辑/删除/测试连接 UI
- [x] **52 单元测试** — CRUD、加密、连接器、调度器、健康检查全覆盖

---

## v13.0.1 — Schema 语义映射 (已完成)

> 基于向量嵌入的字段名自动映射

- [x] **语义匹配 fallback** — 当 `schema_mapping` 为空时，用 `text-embedding-004` 对远程列名和规范词汇表做余弦相似度匹配
- [x] **规范词汇表** — 35 个地理空间常用字段语义 (geometry, population, area, elevation, land_use, ...)

---

## v13.1 — MCP Server 高阶工具暴露 (已完成)

> 让外部 Agent（Claude Desktop / GPT）通过 MCP 调用 GIS Data Agent 的分析能力（参照 SeerAI MCP Server 设计）

- [x] **BP-4 高阶元数据工具** — 新增 6 个 MCP 工具：`search_catalog`（语义搜索数据目录）、`get_data_lineage`（血缘追踪）、`list_skills`（技能列出）、`list_toolsets`（工具集列出）、`list_virtual_sources`（虚拟数据源）、`run_analysis_pipeline`（执行完整分析管线）
- [x] **MCP Server v2.0** — 从 30+ 底层 GIS 工具扩展为 36+ 工具（底层 + 高阶元数据 + pipeline 执行）
- [x] **外部 Agent 接入验证** — MCP routes + A2A server 集成测试 ✅

---

## 已完成 (v14.0) — 交互增强 + 扩展市场

> **主题**: 用户可见的体验提升，快速出价值

### 自然语言交互
- [x] **意图消歧对话** — AMBIGUOUS 分类时弹出选择卡片（Optimization/Governance/General），用户点选后路由
- [x] **参数调整重跑** — rerun_with_params action + session 参数存储 ✅ v14.5
- [x] **记忆搜索面板** — MemorySearchTab + /api/memory/search ✅ v14.5

### 用户自扩展
- [x] **Marketplace 画廊** — DataPanel 新增"市场"tab，聚合所有 is_shared=true 的 Skills/Tools/Templates/Bundles，支持排序（评分/使用量/时间）
- [x] **统一评分系统** — Skills 和 Tools 增加 `rating_sum`/`rating_count` 字段 + REST 端点 `POST /api/skills/{id}/rate`、`POST /api/user-tools/{id}/rate`
- [x] **Skill/Tool Clone** — 允许用户克隆他人共享的 Skill/Tool 到自己名下

### DRL 优化
- [x] **场景模板系统** — 定义 `DRLScenario` 配置类，内置 3 个场景模板：耕地优化（现有）、城市绿地布局、设施选址
- [x] **奖励权重 UI** — 前端 slope_weight / contiguity_weight / balance_weight 滑块 ✅

### 三面板 SPA
- [x] **热力图支持** — 集成 deck.gl `HeatmapLayer` 到 Map3DView，MapPanel 增加 `type: heatmap` 处理
- [x] **测量工具** — MapPanel 工具栏增加距离测量 + 面积测量（Leaflet.Draw 或 Turf.js）
- [x] **3D 图层控制** — Map3DView 增加图层列表面板，支持 show/hide/opacity 调节

### 多 Agent 编排
- [x] **Workflow 断点续跑** — resume_workflow_dag + /runs/{id}/resume ✅ v14.5
- [x] **步骤级重试** — retry_workflow_node + REST 端点 ✅ v14.5

---

## 已完成 (v14.1) — 智能深化 + 协作基础

> **主题**: AI 更聪明，协作开始落地

### 自然语言交互
- [x] **追问与上下文链** — Agent 输出后自动生成 3 个推荐追问，用户点击即发送
- [x] **分析意图消歧 v2** — 对复杂查询拆解为子任务列表，用户确认后按序执行 ✅ v23.0
- [x] **自动记忆提取增强** — pipeline 完成后自动调用 `extract_facts_from_conversation()` + 弹出确认 ✅

### 用户自扩展
- [x] **版本管理** — Skills/Tools 新增 `version` 字段，更新时自动 +1，保留最近 10 个版本，支持回滚
- [x] **标签分类** — category + tags[] 列 + migration 035 ✅ v15.0
- [x] **使用统计** — use_count 列 + increment_skill_use_count ✅ v15.0

### DRL 优化
- [x] **多场景环境引擎** — LandUseOptEnv 配置驱动多场景支持 ✅
- [x] **约束建模** — 新增硬约束（保留率下限）+ 软约束（预算/面积上限），Gymnasium action mask 扩展 ✅ v23.0
- [x] **结果对比面板** — OptimizationTab A/B 对比两次优化结果 ✅

### 三面板 SPA
- [x] **3D basemap 同步** — Map3DView 高德/天地图 MapLibre 栅格源 ✅ v14.5
- [x] **标注协同** — WebSocket 实时推送标注变更 (单实例版) ✅ v23.0
- [x] **GeoJSON 编辑器** — DataPanel 新增 tab/modal，支持粘贴/编辑 GeoJSON + 预览到地图
- [x] **跨图层关联** — 选中 A 图层要素时高亮 B 图层空间关联要素 ✅ v23.0

### 多 Agent 编排
- [x] **Agent 注册中心** — 新增 `agent_registry.py`：注册/发现/心跳，Redis 或 PostgreSQL 后端
- [x] **A2A 双向 RPC** — 扩展 `a2a_server.py` 支持主动调用远程 Agent
- [x] **消息总线持久化** — `AgentMessageBus` PostgreSQL 持久化 + 投递确认 ✅

---

## 已完成 (v14.2) — 深度智能 + 生产就绪

> **主题**: DRL 专业化，系统可投产

### 自然语言交互
- [x] **多轮分析工作流** — 支持"分析链"：用户定义条件触发后续分析
- [x] **语音输入** — 集成语音转文字（浏览器 SpeechRecognition）✅

### 用户自扩展
- [x] **Skill Marketplace 社区** — MarketplaceTab Gallery + 排序 + 热度排行 ✅
- [x] **审批工作流** — 管理员审核 is_shared Skill 的发布请求

### DRL 优化
- [x] **自定义训练 API** — train_drl_model 工具暴露 ✅
- [x] **可解释性模块** — 特征重要性分析 ✅ *(SHAP 集成待 GPU 环境)*
- [x] **时序动画** — DRL 优化过程 GIF 回放 + 前后对比 PNG ✅ 2026-04-08

### 三面板 SPA
- [x] **要素绘制编辑** — Leaflet.Draw 点/线/面/矩形 + 导出 GeoJSON ✅ v14.5
- [x] **标注导出** — 标注集导出为 GeoJSON / CSV
- [x] **自适应布局** — 移动端响应式 ✅

### 多 Agent 编排
- [x] **分布式任务队列** — TaskQueue Redis Sorted Set 后端 (替代 Celery) ✅ 2026-04-08
- [x] **Pipeline 断点恢复 v2** — workflow_engine.py checkpoint/resume 逻辑 ✅
- [x] **Circuit Breaker** — 工具/Agent 连续失败时熔断，自动降级到备选 Agent

---

## 已完成 (v14.3) — 联邦多 Agent + 生态开放

> **主题**: 从单机走向分布式，从工具走向平台

### 自然语言交互
- [ ] **个性化模型微调** — 根据用户历史分析偏好微调 Agent 行为（LoRA adapter on Gemini）
- [x] **多语言支持** — 英文/日文 prompt 自动检测 + 路由到对应语言 Agent

### 用户自扩展
- [x] **Skill 依赖图** — 允许 Skill A 依赖 Skill B（DAG 编排），拓扑排序 + 循环检测 + REST API ✅ v23.0
- [x] **Webhook 集成** — 第三方平台 Skill 注册（GitHub Action、Zapier trigger）
- [x] **Skill SDK** — gis-skill-sdk Python 包 (CLI + 验证器 + 测试) ✅

### DRL 优化
- [x] **多目标优化 v2** — NSGA-II 替代加权和方法，真 Pareto 前沿搜索
- [x] **交通网络/设施布局场景** — 新增 2 个 Gymnasium 环境（路网优化、公共设施选址） ✅ v23.0
- [ ] **联邦学习** — 多租户共享模型权重但不共享数据（隐私保护 DRL）

### 三面板 SPA
- [ ] **协同工作空间** — 多用户同时编辑同一项目（CRDT 冲突解决）
- [x] **插件系统** — 允许用户开发自定义 DataPanel tab 插件
- [x] **离线模式** — Service Worker 缓存基础地图 + 已下载数据集 ✅ v23.0

### 多 Agent 编排
- [x] **完整 A2A 协议** — 实现 Google A2A spec：Agent Card、Task lifecycle、Streaming、Push Notification
- [x] **跨实例 Agent 协作** — Agent A (本机) 调用 Agent B (远程) 的工具，结果回传
- [ ] **Agent 联邦** — 多个 GIS Data Agent 实例组成联邦，共享 Skill 注册表 + 负载均衡

---

## 已完成 (v14.4) — 治理深化 + 交互式可视化

> **主题**: 治理管道从 40% → 65%，非 GIS 数据的交互式图表从 0 → 可用
>
> **依据**: `docs/governance-capability-assessment.md` (6 领域 22 子能力评估)、`docs/data-source-connector-assessment.md` (5 通道缺口分析)、dv.gaozhijun.me (数据可视化参考)

### 数据治理管道强化
- [x] **Ch21 审计修复** — P0/P1/P2 全部清零 (A2A 认证、SQL 参数化、线程安全 6 处) ✅ 2026-03-21
- [x] **DataPanel 拆分重构** — 2922 行 → 17 模块化组件 + 分组 Tab (数据/智能/运维/编排) ✅ 2026-03-21
- [x] **GovernanceToolset (7 工具)** — `check_gaps` / `check_completeness` / `check_attribute_range` / `check_duplicates` / `check_crs_consistency` / `governance_score` / `governance_summary` ✅ 2026-03-21
- [x] **治理评分体系** — 6 维加权评分 (拓扑 25% / 间隙 15% / 完整性 20% / 属性 15% / 重复 10% / CRS 15%)，0-100 综合分 + 雷达图 JSON ✅ 2026-03-21
- [x] **治理 Prompt 独立化** — `prompts/governance.yaml` 5 个治理专用 prompt ✅ 2026-03-21
- [x] **GovernanceViz Agent** — 治理管道第 4 阶段：审计结果可视化 ✅ 2026-03-21

### 交互式数据可视化
- [x] **ChartToolset (9 工具)** — bar/line/pie/scatter/histogram/box_plot/heatmap/treemap/radar → ECharts JSON config ✅ 2026-03-21
- [x] **前端 ECharts 集成** — ChartView 通用渲染组件 + DataPanel ChartsTab ✅ 2026-03-21
- [x] **图表交付管道** — `/api/chart/pending` REST 端点 + `app.py` 图表检测 ✅ 2026-03-21
- [x] **Prompt 图表感知** — `general_viz_instruction` 增加非地图可视化指引 ✅ 2026-03-21

### 质量保障
- [x] **治理工具测试** — `test_governance_tools.py` 7 工具 mock 测试 + 评分逻辑验证 ✅ 2026-03-21
- [x] **图表工具测试** — `test_chart_tools.py` 9 工具 ECharts option schema 验证 ✅ 2026-03-21

---

## 已完成 (v14.5) — 全栈治理升级 + 连接器插件化 + Skill 5 模式 + 可观测性

> **主题**: 数据接入补齐短板，标准驱动治理引擎，Skill 设计模式从单一 Tool Wrapper 走向 5 模式全覆盖
>
> **依据**: `docs/agent-observability-enhancement.md` (Phase 1 指标增强)、`docs/data-source-connector-assessment.md` (S1 阶段)、`docs/data-agent-readiness-assessment.md` (客户 Demo 差距评估)、`docs/skill-design-patterns-analysis.md` (5 种 Skill 设计模式)

### 数据接入增强 + 连接器插件化 *(v15.0 插件化提前完成)*
- [x] **BaseConnector 插件架构** — `connectors/__init__.py`: BaseConnector ABC + ConnectorRegistry 注册表，替代 virtual_sources.py 内联 if-elif 分派 ✅ 2026-03-22
- [x] **现有 4 种连接器重构** — WFS/STAC/OGC API/Custom API 从 virtual_sources.py 提取为独立 Connector 子类 ✅ 2026-03-22
- [x] **WMS/WMTS 连接器** — `connectors/wms.py`: GetCapabilities XML 解析 + 返回 `L.TileLayer.WMS` ���层配置 (非像素下载) ✅ 2026-03-22
- [x] **ArcGIS REST FeatureServer 连接器** — `connectors/arcgis_rest.py`: 分页查询 + f=geojson + BBOX，返回 GeoDataFrame ✅ 2026-03-22
- [x] **前端 WMS 图层渲染** — MapPanel 新增 `'wms'` 图层类型 + `L.tileLayer.wms()` 渲染 ✅ 2026-03-22
- [x] **类型专属表单** — VirtualSourcesTab: WMS (layers/styles/format/version) + ArcGIS (layer_id/where/fields) 专属配置表单 ✅ 2026-03-22
- [x] **图层发现** — `POST /api/virtual-sources/discover` 端点 + 前端"发现图层"按钮 (GetCapabilities 代理) ✅ 2026-03-22
- [x] **Toolset 增强** — VirtualSourceToolset 5→7 工具: 新增 `discover_layers_tool` + `add_wms_layer_tool` ✅ 2026-03-22
- [x] **22 连接器测试** — `test_connectors.py`: Registry + 6 连接器 + auth headers 全覆盖 ✅ 2026-03-22
- [x] **Esri File Geodatabase (.gdb) 支持** — `_load_spatial_data()` 增加 FGDB 读取分支 + 图层列表枚举 ✅ 2026-03-22
- [x] **DWG/DXF 元数据读取** — ezdxf 解析 DXF 图层/实体 (POINT/LINE/POLYLINE)，DWG 提示转换 ✅ 2026-03-22
- [x] **数据源注册向导** — 4 步向导 UI (基本信息→CRS/刷新→类型配置→预览确认) ✅ 2026-03-22
- [x] **字段映射可视化编辑器** — FieldMappingEditor 拖拽映射组件 ✅

### 数据标准与治理引擎 *(全部完成)*
- [x] **Data Standard Registry** — YAML 标准定义 + GB/T 21010 (73 值) + DLTB (30 字段 + 4 代码表) ✅ 2026-03-22
- [x] **DataCleaningToolset** — 7 清洗工具 (空值填充/编码映射/字段重命名/类型转换/异常值/CRS/补齐) ✅ 2026-03-22
- [x] **地类编码交叉映射** — CLCD→GB/T 21010 映射表 + map_field_codes 支持 mapping_id ✅ 2026-03-22
- [x] **Gap Matrix 自动生成** — 逐字段标准对比 (present/missing/extra) + 必填覆盖率 ✅ 2026-03-22
- [x] **批量数据集探查** — 目录递归扫描 + 可选标准对照 + 汇总统计 ✅ 2026-03-22
- [x] **标准感知质检规则** — M/C/O 必填/max_length/类型兼容/枚举/公式校验/合规率评分 ✅ 2026-03-22
- [x] **质量规则库 CRUD** — DB 持久化 + 批量执行 + 趋势记录 + REST API 8 端点 ✅ 2026-03-22
- [x] **治理流程模板化** — generate_governance_plan 自动诊断→生成可执行治理步骤 ✅ 2026-03-22

### Skill 设计模式升级 *(全部完成)*
- [x] **Inversion 模式: site-selection** — 4 阶段采访 + 执行门控 (v3.0) ✅ 2026-03-22
- [x] **Inversion 模式: land-fragmentation** — 4 阶段采访 + DRL 参数确认 (v3.0) ✅ 2026-03-22
- [x] **Generator 模式: data-profiling** — assets/ 报告模板 + references/ 评分标准 (v3.0) ✅ 2026-03-22
- [x] **Generator 模式: ecological-assessment** — assets/ 生态评估模板 ✅ 2026-03-22
- [x] **Reviewer 模式: farmland-compliance** — 检查清单提取到 references/ (v3.0) ✅ 2026-03-22
- [x] **Skill L3 参考文档补全** — +5 skills (geocoding/buffer-overlay/3d-viz/data-import-export/site-selection) ✅ 2026-03-22

### Agent 可观测性 Phase 1 *(全部完成)*
- [x] **Prometheus 指标扩展 (4→25+)** — LLM/Tool/Pipeline/Cache/HTTP/CB 6 层 ✅ 2026-03-22
- [x] **ObservabilityMiddleware** — ASGI HTTP 中间件 + path 归一化 ✅ 2026-03-22
- [x] **缓存命中率指标** — semantic_layer hit/miss Counter ✅ 2026-03-22
- [x] **Grafana Dashboard 模板** — grafana/agent_overview.json 11 面板 ✅ 2026-03-22

### 治理运营 *(全部完成)*
- [x] **质量规则库 + 趋势 + 总览** — agent_quality_rules/trends 表 + 8 REST 端点 + GovernanceTab ✅ 2026-03-22

### 交互体验打磨 *(全部完成)*
- [x] **参数调整重跑** — last_pipeline_params session 存储 + rerun_with_params action ✅ 2026-03-22
- [x] **记忆搜索面板** — /api/memory/search + MemorySearchTab + DataPanel "记忆" tab ✅ 2026-03-22
- [x] **3D basemap 同步** — Map3DView 扩展高德/天地图 MapLibre 栅格源样式 ✅ 2026-03-22
- [x] **要素绘制编辑** — Leaflet.Draw 点/线/面 + 导出 GeoJSON + /api/user/drawn-features ✅ 2026-03-22

### 多 Agent 编排 *(全部完成)*
- [x] **Workflow 断点续跑** — resume_workflow_dag() + POST /runs/{id}/resume 端点 ✅ 2026-03-22
- [x] **步骤级重试** — retry_workflow_node() 已有，REST 端点已暴露 ✅ 2026-03-22

---

## 已完成 (v15.0) — 深度可观测 + 数据安全 + 分布式计算

> **主题**: OpenTelemetry 分布式追踪、Agent 决策透明化、安全合规、数据分发与反馈闭环
>
> **依据**: 可观测性文档 Phase 2-4 + 治理评估 §4 数据安全 + 数据源评估 S2 + Spark 架构文档 + readiness 评估 P2 项 + skill-design-patterns P2 项

### Agent 可观测性 Phase 2-4 *(全部完成)*
- [x] **OpenTelemetry 分布式追踪** — `otel_tracing.py`: Pipeline/Agent/Tool 三级 Span + OTLP 导出 ✅ 2026-03-22
- [x] **Agent 决策追踪** — `agent_decision_tracer.py`: DecisionEvent/DecisionTrace + Mermaid 序列图 ✅ 2026-03-22
- [x] **Pipeline 执行瀑布图** — ObservabilityTab 决策时间线 + 事件颜色编码 ✅ 2026-03-22
- [x] **Prometheus Alert 规则** — 9 条告警 (Pipeline/LLM/Tool/CB/Token/Cache/HTTP + 安全) ✅ 2026-03-22

### 数据安全 *(全部完成)*
- [x] **数据分类分级引擎** — PII 检测 (6 模式) + 5 级敏感度 + classify_data_sensitivity 工具 ✅ 2026-03-22
- [x] **数据脱敏工具** — 4 策略 (mask/redact/hash/generalize) + mask_sensitive_fields 工具 ✅ 2026-03-22
- [x] **RLS 实际落地** — 8 核心表 Row Level Security 策略 (owner/shared/admin) ✅ 2026-03-22
- [x] **安全事件告警** — SensitiveDataAccessSpike + BruteForceDetected ✅ 2026-03-22

### 数据分发与反馈闭环 *(全部完成)*
- [x] **数据申请审批流程** — create/approve/reject + 角色过滤 ✅ 2026-03-22
- [x] **数据分发包打包下载** — package_assets ZIP 打包 ✅ 2026-03-22
- [x] **用户反馈通道** — add_review (1-5 评分 + 评论) + get_reviews ✅ 2026-03-22
- [x] **使用热度统计** — log_access + get_hot_assets + access_stats ✅ 2026-03-22

### 数据更新与版本管理 *(全部完成)*
- [x] **增量更新机制** — compare_datasets 差异对比 (要素/列/CRS) ✅ 2026-03-22
- [x] **数据版本管理** — create_version_snapshot + rollback_version + list_versions ✅ 2026-03-22
- [x] **更新日志与通知** — notify_asset_update + get_notifications + mark_read ✅ 2026-03-22

### 连接器扩展 *(全部完成)*
- [x] **BaseConnector 抽象基类** — ConnectorRegistry *(v14.5 提前完成)*
- [x] **DatabaseConnector** — MySQL/PostgreSQL/SQLite 外部数据库连接 ✅ 2026-03-22
- [x] **ObjectStorageConnector** — S3/OBS/OSS 对象存储拉取 ✅ 2026-03-22

### Skill 设计模式深化 *(核心完成)*
- [x] **Pipeline 模式: multi-source-fusion** — 5 步检查点融合 (v3.0) ✅ 2026-03-22
- [x] **新增 data-quality-reviewer Skill** — 入库前 13 项质量审查 ✅ 2026-03-22
- [x] **数据模型推荐引擎** — recommend_data_model 工具 (差距分析+转换路径+工作量评估) ✅ 2026-03-22
- [x] **Generator/Reviewer 输出结构化校验** — Pydantic schema ✅

### 分布式计算 *(全部完成)*
- [x] **SparkToolset (3 工具)** — submit_task + check_tier + list_jobs ✅ 2026-03-22
- [x] **SparkGateway 网关** — 多后端抽象 (local/Livy/Dataproc/EMR) ✅ 2026-03-22
- [x] **三层执行路由** — L1 本地(<100MB) / L2 队列(<1GB) / L3 Spark(>1GB) ✅ 2026-03-22

---

## 已完成 (v15.2) — 地理空间世界模型 + NL2SQL + 地图时间轴

> **主题**: 从"分析已有数据"到"预测未来演变"——构建地理空间 JEPA 世界模型，自然语言直达数据库
>
> **依据**: `docs/world-model-tech-preview-design.md` (方案 A/B/C/D 评审 + 阶段 0 验证)、`docs/multimodal-semantic-fusion-plus-alphaearth-strategy.md`

### 地理空间世界模型 (Plan D: AlphaEarth + LatentDynamicsNet)
- [x] **LatentDynamicsNet 残差 CNN** — `world_model.py`: 459K 参数, 空洞卷积 (dilation 1/2/4, 170m 感受野), 残差连接 + L2 流形保持 ✅ 2026-03-22
- [x] **AlphaEarth 64 维嵌入集成** — GEE `GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL` 采集 + zonal 聚合 ✅ 2026-03-22
- [x] **5 种情景模拟** — 城市蔓延 / 生态修复 / 农业集约化 / 气候适应 / 基线趋势，one-hot 编码 ✅ 2026-03-22
- [x] **地形上下文感知** — DEM elevation + slope 作为 CNN 额外通道 ✅ 2026-03-22
- [x] **LULC 解码器** — LogisticRegression: 嵌入 → 9 类 ESRI LULC (准确率 83.7%) ✅ 2026-03-22
- [x] **训练管线** — 15 区域 × 8 年嵌入对 + 多步展开训练损失 + GEE 自动下载 ✅ 2026-03-22
- [x] **WorldModelToolset (5 工具)** — predict / scenarios / status / embedding_coverage / find_similar ✅ 2026-03-22
- [x] **世界模型快捷路径** — 意图分类直判 world_model → 跳过 LLM Planner，1 次 API 调用完成预测 ✅ 2026-03-22
- [x] **阶段 0 验证通过** — 年际 cos_sim=0.953, 变化/稳定分离度=2.44x, 嵌入→LULC 解码 83.7% ✅ 2026-03-22

### pgvector 嵌入缓存
- [x] **embedding_store.py** — `agent_geo_embeddings` 表 + pgvector VECTOR(64) + IVFFlat 索引 ✅ 2026-03-23
- [x] **三级缓存** — pgvector (24ms) → .npy 文件 (ms) → GEE 下载 (seconds)，自动回填 ✅ 2026-03-23
- [x] **余弦相似度搜索** — `find_similar_embeddings()` 支持空间半径 + top-K ✅ 2026-03-23

### NL2SQL 动态数据查询
- [x] **NL2SQLToolset (3 工具)** — discover_database_schema / execute_spatial_query / load_admin_boundary ✅ 2026-03-22
- [x] **Schema 发现** — 自动探索 public schema 表结构 + 列类型 + 注释 ✅ 2026-03-22
- [x] **参数化安全查询** — 自动 LIKE 模糊匹配构造，零 SQL 注入风险 ✅ 2026-03-22
- [x] **行政区划加载** — 自然语言地名 → 模糊匹配 → 自动 SQL → GeoJSON ✅ 2026-03-22

### 地图时间轴 + 底图增强
- [x] **时间轴播放器** — MapPanel 多时序 LULC 图层动画切换 + 年份滑块 ✅ 2026-03-22
- [x] **卫星影像底图** — Gaode Satellite + ESRI World Imagery 底图选项 ✅ 2026-03-22
- [x] **WorldModelTab** — DataPanel 新增世界模型专属 Tab (情景选择/预测/面积趋势表/转移矩阵/堆叠条形图) ✅ 2026-03-22

### 质量保障
- [x] **世界模型测试** — `test_world_model.py` 场景/模型/预测/缓存全覆盖 ✅ 2026-03-22
- [x] **NL2SQL 测试** — `test_nl2sql.py` Schema/Query/AdminBoundary 测试 ✅ 2026-03-22

---

## 已完成 (v15.3) — 三角度时空因果推断体系

> **主题**: 为论文构建三个互补角度的因果推断能力——统计方法 × LLM 推理 × 因果世界模型
>
> **依据**: 项目思想起源 (2023-09) 时空因果推断平台构想

### Angle A — GeoFM 嵌入因果推断 (6 tools)
- [x] **CausalInferenceToolset** — `causal_inference.py` (1247 行): PSM / ERF / DiD / Granger / GCCM / Causal Forest ✅ 2026-03-25
- [x] **AlphaEarth 嵌入增强** — 全部 6 工具支持 `use_geofm_embedding=True`，64 维嵌入作为空间混淆控制 ✅ 2026-03-25
- [x] **空间距离加权匹配** — PSM 支持 `spatial_distance_weight` 空间邻近约束 ✅ 2026-03-25
- [x] **21 测试** — 合成数据 ground truth 验证 (Park-price ATE, Pollution DiD, 灌溉 CATE 等) ✅ 2026-03-25

### Angle B — LLM 因果推理 (4 tools)
- [x] **LLMCausalToolset** — `llm_causal.py` (949 行): Gemini 2.5 Pro/Flash 驱动 ✅ 2026-03-25
- [x] **因果 DAG 构建** — `construct_causal_dag()`: 变量/混淆因子/中介/碰撞因子识别 + networkx 可视化 + Mermaid 图 ✅ 2026-03-25
- [x] **反事实推理** — `counterfactual_reasoning()`: 结构化推理链 + 置信度 + 敏感性因子 ✅ 2026-03-25
- [x] **因果机制解释** — `explain_causal_mechanism()`: 接收 Angle A 统计结果 JSON 自动解读 ✅ 2026-03-25
- [x] **What-If 情景生成** — `generate_what_if_scenarios()`: 自动映射到世界模型情景 + Angle A 参数 ✅ 2026-03-25
- [x] **33 测试** — Gemini mock + JSON 解析 + DAG 渲染 + Mermaid 生成 ✅ 2026-03-25

### Angle C — 因果世界模型 (4 tools)
- [x] **CausalWorldModelToolset** — `causal_world_model.py` (1049 行): 世界模型 + 因果干预 ✅ 2026-03-25
- [x] **空间干预预测** — `intervention_predict()`: 子区域施加干预 + 空间溢出效应分析 ✅ 2026-03-25
- [x] **反事实对比** — `counterfactual_comparison()`: 平行情景 + 逐像素 LULC 差异 + 效应图 ✅ 2026-03-25
- [x] **嵌入空间处理效应** — `embedding_treatment_effect()`: cosine/euclidean/manhattan 距离度量 ✅ 2026-03-25
- [x] **统计先验整合** — `integrate_statistical_prior()`: ATT → 校准世界模型预测偏移 ✅ 2026-03-25
- [x] **28 测试** — 空间 mask + 干预/反事实/嵌入效应/校准 全覆盖 ✅ 2026-03-25

### 集成与前端
- [x] **8 REST API 端点** — `/api/causal/*` (4) + `/api/causal-world-model/*` (4) ✅ 2026-03-25
- [x] **CausalReasoningTab** — DataPanel 新增"因果推理" Tab (DAG/反事实/机制/情景 4 区域) ✅ 2026-03-25
- [x] **WorldModelTab 扩展** — 模式切换 (预测/干预/反事实) + 子区域输入 + 双情景选择 ✅ 2026-03-25
- [x] **Data Catalog 语义搜索** — `/api/catalog/search` + CatalogTab 双搜索模式 + 分页 ✅ 2026-03-25
- [x] **intent_router 扩展** — `causal_reasoning` + `world_model` 子类别增强 ✅ 2026-03-25
- [x] **tool_filter 扩展** — `causal_reasoning` 类别 (4 工具) + `world_model` 类别扩展 (7 工具) ✅ 2026-03-25

---

## 已完成 (v15.5) — 论文修订 + DRL-World Model Dreamer 集成

> **主题**: 学术论文 R2 审稿回复 + DRL 与世界模型深度融合
>
> **依据**: IJGIS 审稿意见 + 因果推断论文投稿准备

### 论文修订
- [x] **World Model 论文 R2 回复** — 审稿人意见逐条回复 + 补充实验 ✅ 2026-03-26
- [x] **因果推断论文** — 三角度因果推断体系论文撰写 (IJGIS 目标) ✅ 2026-03-26

### DRL-World Model 融合
- [x] **DreamerEnv** — 世界模型驱动的 DRL 环境，嵌入空间中训练 ✅ 2026-03-26
- [x] **DreamerToolset** — 梦境训练 + 策略评估 + 情景对比工具 ✅ 2026-03-26

---

## 已完成 (v15.7) — 测绘质检智能体系统

> **主题**: 面向测绘行业的专业质检智能体，覆盖 GB/T 24356 标准全流程
>
> **依据**: `docs/surveying_qc_agent_gap_analysis.md`、`docs/qc_agent_architecture_comparison.md`

### 缺陷分类与标准
- [x] **缺陷分类法** — 30 缺陷编码 / 5 类别 (几何/属性/拓扑/完整性/精度)，对标 GB/T 24356 ✅ 2026-03-27
- [x] **QC 工作流模板** — `qc_workflow_templates.yaml`: 3 套标准流程 (通用/建筑/地形) + SLA 约束 ✅ 2026-03-27

### 治理工具集扩展
- [x] **GovernanceToolset 扩展至 18 工具** — 新增拓扑检查/面积一致性/层高验证/坐标精度等 ✅ 2026-03-27
- [x] **DataCleaningToolset 扩展至 11 工具** — 新增几何修复/拓扑修复/属性标准化/批量清洗 ✅ 2026-03-27
- [x] **PrecisionToolset (5 工具)** — 坐标精度评估/高程精度/面积精度/角度精度/综合精度报告 ✅ 2026-03-27

### QC 运营
- [x] **QC 报告引擎** — 结构化质检报告生成 (缺陷统计/分布图/修复建议) ✅ 2026-03-27
- [x] **告警规则** — 缺陷率阈值告警 + SLA 超时告警 ✅ 2026-03-27
- [x] **案例库** — 历史质检案例存储 + 相似案例检索 ✅ 2026-03-27
- [x] **人工复核工作流** — 机检→人审→终审三级流程 + 复核意见记录 ✅ 2026-03-27

### 4 独立子系统
- [x] **CV 检测子系统** — `subsystems/cv_detection/`: 影像缺陷自动识别 ✅ 2026-03-27
- [x] **CAD/3D 解析子系统** — `subsystems/cad_parser/`: DWG/DXF/BIM 数据解析 ✅ 2026-03-27
- [x] **专业工具 MCP 服务** — `subsystems/mcp_tools/`: 测绘专业工具 MCP 封装 ✅ 2026-03-27
- [x] **参考数据服务** — `subsystems/reference_data/`: 标准参考数据管理 ✅ 2026-03-27

### 前端
- [x] **QcMonitorTab** — 实时质检统计 + 最近审查列表 + 工作流进度 ✅ 2026-03-28
- [x] **WorkflowsTab 增强** — 工作流列表 + 运行历史 + 进度可视化 ✅ 2026-03-28
- [x] **质检 API** — `quality_routes.py` + `workflow_routes.py` REST 端点 ✅ 2026-03-28

---

## 已完成 (v15.8) — BCG 企业智能体平台 + 技术债务清零

> **主题**: 对标 BCG 企业级 Agent 平台 6 大能力模块，同时系统性清理全部技术债务
>
> **依据**: `docs/bcg-enterprise-agents-analysis.md`、`tech_debt.md` 技术债务登记表

### BCG 企业平台能力 (6 模块)
- [x] **Prompt Registry** — 版本化 Prompt 管理 + 环境隔离 (dev/staging/prod) + A/B 测试 ✅ 2026-03-28
- [x] **Model Gateway** — 任务感知路由 (Flash/Pro 自动选择) + 成本追踪 + 场景标注 ✅ 2026-03-28
- [x] **Context Manager** — 可插拔上下文策略 + Token 预算管理 + 上下文压缩 ✅ 2026-03-28
- [x] **Eval Scenario Framework** — 场景化评估框架 + 黄金数据集 + 自动回归测试 ✅ 2026-03-28
- [x] **Token Tracking 增强** — 场景/项目/任务类型维度追踪 + 成本归因 ✅ 2026-03-28
- [x] **Eval History** — 评估历史记录 + 版本间对比 + 趋势分析 ✅ 2026-03-28

### DB 迁移 (045-048)
- [x] **Migration 045** — Prompt Registry 表 (agent_prompt_registry) ✅ 2026-03-28
- [x] **Migration 046** — Model Gateway 扩展 (token_usage 增加 scenario/project_id/task_type) ✅ 2026-03-28
- [x] **Migration 047** — Eval Framework 表 (agent_eval_scenarios + agent_eval_history) ✅ 2026-03-28
- [x] **Migration 048** — 数据资产表统一 (agent_data_catalog → agent_data_assets 兼容 VIEW) ✅ 2026-03-29

### 技术债务清零 (6/6)
- [x] **TD-001 (P1)** — 双数据资产表统一: migration 048 + data_catalog.py 全函数迁移至 agent_data_assets ✅ 2026-03-29
- [x] **TD-002 (P2)** — SQLAlchemy `::jsonb` 类型转换: 改用 `CAST(:param AS jsonb)` ✅ 2026-03-28
- [x] **TD-003 (P2)** — 自动迁移运行器: `migration_runner.py` + schema_migrations 追踪表 ✅ 2026-03-29
- [x] **TD-004 (P2)** — 工作流 Chainlit 上下文丢失: `asyncio.create_task()` → `await` ✅ 2026-03-28
- [x] **TD-005 (P1)** — 工作流步骤上下文隔离: `accumulated_context` 步间结果注入 ✅ 2026-03-29
- [x] **TD-006 (P2)** — 工作流阻塞聊天: Chainlit context_var 传播至 background task ✅ 2026-03-29

### 质量保障
- [x] **test_workflow_context.py** — 工作流上下文注入验证 ✅ 2026-03-29
- [x] **50/50 data_catalog 测试通过** — 表统一后全部测试绿色 ✅ 2026-03-29

---

## 历史遗留未完成项 (v13~v14 积累)

> 以下项目在各版本迭代中被跳过或延期，按优先级分类管理

### 优先完成 (低成本高价值)
- [x] **奖励权重 UI** — DRL 前端 slope/contiguity/balance 滑块 *(v14.0, 前端 ~100 行)* ✅ v15.9
- [x] **字段映射可视化编辑器** — FieldMappingEditor 拖拽映射 ✅
- [x] **MCP 外部 Agent 接入验证** — Claude Desktop / Cursor E2E 测试 *(v13.1)* ✅ v15.9

### 择机完成 (中等价值)
- [x] **分析意图消歧 v2** — 复杂查询拆解子任务列表 *(v14.1)* ✅ v15.9
- [x] **自动记忆提取增强** — pipeline 后 extract_facts + 弹窗确认 *(v14.1)* ✅ v15.9
- [x] **消息总线持久化** — AgentMessageBus → PostgreSQL *(v14.1)* ✅ v15.9
- [x] **自适应布局** — 移动端响应式 ✅
- [x] **Skill SDK 发布** — `gis-skill-sdk` Python 包 *(v14.3)* ✅ v15.9

### 远期/冻结
- [~] **标注协同 (WebSocket)** — 实时协同复杂度高 *(v14.1, 冻结)*
- [~] **跨图层关联高亮** — 选中要素联动 *(v14.1, 冻结)*
- [~] **Skill Marketplace 社区** — 需要公网部署 *(v14.2, 冻结)*
- [~] **DRL 自定义训练 API** — *(v14.2, 冻结)*
- [~] **DRL 可解释性 (SHAP)** — *(v14.2, 冻结)*
- [~] **DRL 时序动画** — 优化过程回放 *(v14.2, 冻结)*
- [~] **多场景环境引擎** — DRL 配置驱动重构 *(v14.1, 冻结)*
- [~] **约束建模** — 硬/软约束 Gymnasium 扩展 *(v14.1, 冻结)*
- [~] **结果对比面板** — A/B 对比优化结果 *(v14.1, 冻结)*
- [~] **分布式任务队列 (Celery)** — *(v14.2, 冻结)*
- [~] **Pipeline 断点恢复 v2** — 崩溃后自动恢复 *(v14.2, 冻结)*
- [~] **协同工作空间 (CRDT)** — *(v14.3, 冻结)*
- [~] **Agent 联邦** — 多实例负载均衡 *(v14.3, 冻结)*
- [~] **联邦学习** — 隐私保护 DRL *(v14.3, 冻结)*
- [~] **个性化模型微调 (LoRA)** — *(v14.3, 冻结)*
- [~] **离线模式** — Service Worker *(v14.3, 冻结)*
- [~] **语音输入 (Whisper)** — *(v14.2, 冻结)*
- [~] **Generator/Reviewer 输出结构化校验** — Pydantic schema *(v15.0, 移至 v16.0+)*

---

---

## v15.9 — 向 L3 迈进：Planner-Executor + 中间件链 + DeerFlow 工程质量

> **主题**: 补齐 Proto-L3 短板 + 解决最大技术债 + 工程质量提升
>
> **依据**: SIGMOD 2026 "Data Agents: Levels, State of the Art, and Open Problems" (Luo et al.) + DeerFlow v2.0 架构借鉴
>
> **当前水平**: L2.5 (完整 L2 + 部分 Proto-L3) → **目标**: 完整 L3 条件自主

### 核心升级：从 L2 执行者 → L3 编排者

**关键演进跃迁 (SIGMOD 2026 论文):**
- L2: 人类设计流程，Agent 执行任务特定过程
- L3: Agent 设计流程，人类监督执行结果

### DeerFlow 工程质量借鉴 (P0-P2)

#### **D-1: App 分层重构 — Harness/App 分离 (P0)**
- [x] **core/ 层提取** — agent_runtime.py (Agent 创建 + pipeline 组装) + tool_registry.py (Toolset 注册表) 从 agent.py 提取
- [x] **app.py 瘦身** — 从 3340 行降到 <500 行，仅保留 Chainlit 回调 + 胶水代码
- [x] **CI 边界测试** — test_harness_boundary.py 强制 core/ 永不 import chainlit
- [x] **api/ 进一步拆分** — frontend_api.py 按 domain 拆分 (catalog/workflow/quality/skill 等)

#### **D-2: 中间件链模式 (P1)**
- [x] **PipelineMiddleware 协议** — before_run / after_run / on_error 三阶段钩子
- [x] **7 层中间件提取** — RBAC → FileUpload → ContextSummarization → [Pipeline] → TokenTracking → LayerControl → ErrorClassification
- [x] **中间件注册器** — 可组合、可启停、严格执行顺序

#### **D-3: 上下文自动摘要 (P1)**
- [x] **SummarizationMiddleware** — token 超 80% 阈值时自动压缩历史对话
- [x] **摘要策略** — 保留最近 3 轮完整对话 + 关键数据路径 + 分析结论，丢弃中间推理
- [x] **使用 Gemini 2.0 Flash** — 便宜快速的摘要模型

### SIGMOD 2026 论文借鉴 (P1-P2)

#### **S-1: Planner-Executor 分离 (P1, 向 L3 关键跃迁)**
- [x] **PlannerAgent** — 根据用户意图动态生成 ExecutionPlan (DAG nodes + edges + dependencies)
- [x] **ExecutorAgent** — 拓扑排序 + 并行执行计划
- [x] **ExecutionPlan 数据结构** — 替代硬编码的三条流水线 (Optimization/Governance/General)
- [x] **复用 workflow_engine.py** — DAG 执行逻辑已有，重构为 Planner 输出格式

#### **S-2: 工具选择器 (P2)**
- [x] **ToolSelector** — 根据 task_type + data_profile 推荐工具子集
- [x] **选择规则** — 遥感任务 → RemoteSensingToolset，数据量 >1GB → SparkToolset，因果分析 → CausalInferenceToolset
- [x] **降低 Agent 负担** — 从 28 个 Toolset 全暴露 → 智能推荐 5-8 个相关工具

#### **S-3: 因果错误诊断 (P2)**
- [x] **PipelineErrorDiagnoser** — 构建管道因果图 + 反向追踪错误传播路径
- [x] **根因识别** — 定位哪一步引入错误 (而非仅报告哪一步失败)
- [x] **修复建议** — 自动推荐修复策略 (插入工具调用、调整参数、替换工具)

### 历史遗留完成 (低成本高价值)

- [x] **奖励权重 UI** — DRL 前端 slope/contiguity/balance 滑块 *(v14.0 遗留)*
- [x] **MCP 外部 Agent 接入验证** — Claude Desktop / Cursor E2E 测试 *(v13.1 遗留)*
- [x] **分析意图消歧 v2** — 复杂查询拆解子任务列表 *(v14.1 遗留)*
- [x] **自动记忆提取增强** — pipeline 后 extract_facts + 弹窗确认 *(v14.1 遗留)*
- [x] **消息总线持久化** — AgentMessageBus → PostgreSQL *(v14.1 遗留)*
- [x] **Skill SDK 发布** — `gis-skill-sdk` Python 包 *(v14.3 遗留)*

### 质量保障
- [x] **test_planner_executor.py** — Planner 生成计划 + Executor 执行验证
- [x] **test_middleware_chain.py** — 7 层中间件执行顺序 + 钩子调用
- [x] **test_tool_selector.py** — 任务特征 → 工具推荐准确性
- [x] **test_error_diagnoser.py** — 管道错误根因识别

---

## v16.0 — 完整 L3：语义算子 + 多 Agent 协作 + 遥感智能体

> **主题**: 达到完整 L3 条件自主 + 遥感领域专业化
>
> **依据**: SIGMOD 2026 论文 Proto-L3 设计模式 + Tang et al. (2026) 遥感智能体综述
>
> **目标**: 成为地理空间领域标杆 L3 系统

### SIGMOD 2026 论文借鉴 (完整 L3)

#### **S-4: 语义算子层 (P1)**
- [x] **SemanticOperator 抽象** — Clean / Integrate / Analyze / Visualize 高层算子 ✅ 2026-04-01
- [x] **CleanOperator** — 封装 DataCleaningToolset 11 工具，根据数据特征自动选择清洗策略 ✅ 2026-04-01
- [x] **IntegrateOperator** — 封装连接器 + schema 映射 + 冲突解决 ✅ 2026-04-01
- [x] **AnalyzeOperator** — 封装 GeoProcessing + Analysis + CausalInference ✅ 2026-04-01
- [x] **算子组合** — Planner 组合语义算子而非直接调用底层工具 ✅ 2026-04-01

#### **S-5: 多 Agent 协作 (P1)**
- [x] **DataEngineerAgent** — 负责数据准备 (清洗、集成、标准化) ✅ 2026-04-01
- [x] **AnalystAgent** — 负责分析 (GIS 分析、统计、因果推断) ✅ 2026-04-01
- [x] **VisualizerAgent** — 负责可视化 (地图、图表、报告) ✅ 2026-04-01
- [x] **RemoteSensingAgent** — 负责遥感分析 (光谱指数、变化检测、时序分析) ✅ 2026-04-01
- [x] **CoordinatorAgent** — Planner 增强为协调器，管理 4 专业 Agent + 2 组合工作流 ✅ 2026-04-01

#### **S-6: 计划精化与错误恢复 (P2)**
- [x] **PlanRefiner** — 根据执行反馈调整计划 (插入修复步骤、跳过失败步骤、替换工具) ✅ 2026-04-01
- [x] **ErrorRecoveryStrategy** — 多种恢复策略 (retry / alternative_tool / skip / simplify / escalate) ✅ 2026-04-01
- [x] **局部调整** — 从"全有或全无"到"局部精化" ✅ 2026-04-01

#### **S-7: 工具演化 (P2)**
- [x] **ToolEvolution** — 动态工具库管理 (add_tool / remove_tool / suggest_new_tools) ✅ 2026-04-01
- [x] **失败驱动的工具发现** — 分析失败任务，推荐缺失的工具 ✅ 2026-04-01
- [x] **工具元数据** — 能力描述、成本、可靠性、适用场景 ✅ 2026-04-01

### DeerFlow 工程质量借鉴 (v16.0)

#### **D-4: 工具调用 Guardrails (P2)**
- [x] **GuardrailMiddleware** — 可插拔的确定性策略引擎 (非 LLM 判断) ✅ 2026-04-01
- [x] **三级策略** — Deny (静默拒绝) / Require Confirmation (暂停确认) / Allow (直接执行) ✅ 2026-04-01
- [x] **YAML 策略配置** — viewer deny [delete_*, drop_*], analyst require_confirmation [execute_sql_write] ✅ 2026-04-01
- [x] **与 RBAC 协同** — RBAC (pipeline 级) + Guardrails (工具级) = 两层安全 ✅ 2026-04-01

#### **D-5: AI 辅助 Skill 创建 (P2)**
- [x] **skill-creator Skill** — 用自然语言描述需求 → AI 生成 Skill 配置 ✅ 2026-04-01
- [x] **工作流** — 需求分析 → 推荐 toolsets → 生成配置 → 用户预览确认 → 保存 DB ✅ 2026-04-01
- [x] **复用现有 API** — `/api/skills/generate` 端点 + custom_skills.py CRUD ✅ 2026-04-01

### 遥感智能体 Phase 1 (v16.0)

- [x] **光谱指数库** — 15+ 遥感指数 (EVI/SAVI/NDWI/NDBI/NBR 等) + 智能推荐 ✅ 2026-04-01
- [x] **经验池 (Experience Pool)** — 成功分析经验记录 + RAG 检索 + 经验进化 ✅ 2026-04-01
- [x] **数据质量门控** — 云覆盖检测 + 自动降级 (光学→SAR 切换) ✅ 2026-04-01
- [x] **卫星数据预置** — Sentinel-2/Landsat/SAR STAC 模板 + 5 预置源 ✅ 2026-04-01
- [x] **新增 Skills** — spectral-analysis + satellite-imagery ✅ 2026-04-02

### 质量保障
- [x] **test_semantic_operators.py** — 语义算子组合 + 自动工具选择 ✅ 2026-04-02
- [x] **test_multi_agent_collaboration.py** — 多 Agent 任务分解 + 协调 + 汇总 ✅ 2026-04-02
- [x] **test_plan_refinement.py** — 执行反馈 → 计划调整 ✅ 2026-04-02
- [x] **test_guardrails.py** — 策略引擎 + 三级策略验证 ✅ 2026-04-02

---

## 已完成 (v17.0) — 多模态融合 v2.0 增强

> **主题**: 时序对齐 + 语义增强 + 冲突解决 + 可解释性
>
> **依据**: `docs/fusion_v2_enhancement_plan.md` — 从基础融合到智能语义融合
>
> **目标**: 提升多源数据融合质量，增强语义理解和冲突处理能力

### 时序对齐模块

- [x] **TemporalAligner** — `fusion/temporal.py` 时序对齐引擎 ✅ 2026-04-04
- [x] **时间戳标准化** — 多时区/多格式统一到 UTC ISO8601 ✅ 2026-04-04
- [x] **时序插值** — 线性/样条/最近邻插值，填补时间间隙 ✅ 2026-04-04
- [x] **时间窗口对齐** — 滑动窗口匹配 + 容差配置 ✅ 2026-04-04
- [x] **事件序列对齐** — DTW (Dynamic Time Warping) 算法 ✅ 2026-04-04
- [x] **5 对齐工具** — standardize_timestamps / interpolate_temporal / align_time_windows / align_event_sequences / validate_temporal_consistency ✅ 2026-04-04

### 语义增强模块

- [x] **SemanticEnhancer** — `fusion/semantic_llm.py` + `fusion/ontology.py` 语义增强引擎 ✅ 2026-04-04
- [x] **本体推理** — OWL 本体加载 + RDFS 推理 + 关系传播 ✅ 2026-04-04
- [x] **LLM 语义理解** — Gemini 2.5 Pro 字段语义解析 + 关系抽取 ✅ 2026-04-04
- [x] **跨源实体链接** — 基于嵌入的实体消歧 + 同义词扩展 ✅ 2026-04-04
- [x] **语义相似度计算** — 字段级 + 记录级相似度评分 ✅ 2026-04-04
- [x] **6 语义工具** — load_ontology / infer_relationships / llm_semantic_parse / link_entities / compute_semantic_similarity / enrich_with_context ✅ 2026-04-04

### 冲突解决模块

- [x] **ConflictResolver** — `fusion/conflict_resolver.py` 冲突解决引擎 ✅ 2026-04-04
- [x] **冲突检测** — 值冲突 / 模式冲突 / 时序冲突 / 空间冲突 ✅ 2026-04-04
- [x] **解决策略** — 6 种策略 (source_priority / latest_wins / voting / llm_arbitration / spatial_proximity / user_defined) ✅ 2026-04-04
- [x] **置信度评分** — 数据源可信度 + 时效性 + 空间精度综合评分 ✅ 2026-04-04
- [x] **冲突日志** — 记录所有冲突及解决决策，支持审计 ✅ 2026-04-04
- [x] **5 冲突工具** — detect_conflicts / resolve_value_conflict / resolve_schema_conflict / resolve_temporal_conflict / log_conflict_resolution ✅ 2026-04-04

### 可解释性模块

- [x] **ExplainabilityEngine** — `fusion/explainability.py` 可解释性引擎 ✅ 2026-04-04
- [x] **融合溯源** — 每个融合结果追溯到源数据集 + 转换步骤 ✅ 2026-04-04
- [x] **决策解释** — 为什么选择某个值/策略，生成自然语言解释 ✅ 2026-04-04
- [x] **影响分析** — 某个源数据变化对融合结果的影响评估 ✅ 2026-04-04
- [x] **可视化报告** — Sankey 图 (数据流) + 决策树 (策略选择) ✅ 2026-04-04
- [x] **4 解释工具** — trace_fusion_lineage / explain_decision / analyze_impact / generate_fusion_report ✅ 2026-04-04

### 集成与测试

- [x] **FusionToolset 扩展** — 新增 20 个融合 v2.0 工具 ✅ 2026-04-04
- [x] **fusion_v2_routes.py** — 8 个 REST API 端点 ✅ 2026-04-04
- [x] **FusionV2Tab** — DataPanel 新增融合 v2.0 配置和监控 Tab ✅ 2026-04-04
- [x] **84 测试** — 时序对齐/语义增强/冲突解决/可解释性全覆盖 ✅ 2026-04-04

---

## 已完成 (v17.1) — 矢量切片渲染 + 数据资产编码

> **主题**: 大数据量地图渲染优化 + 数据资产标准化编码
>
> **依据**: 大数据量 GeoJSON 渲染性能瓶颈 + 资产管理规范化需求

### 矢量切片大数据渲染

- [x] **三级自适应交付** — GeoJSON (≤5K features) / FlatGeobuf (5K-50K) / PostGIS MVT (>50K) ✅ 2026-04-04
- [x] **tile_server.py** — MVT 矢量切片生成: 临时表管理 + ST_AsMVT 查询 + 过期清理 ✅ 2026-04-04
- [x] **tile_routes.py** — 5 个切片 REST API 端点 ✅ 2026-04-04
- [x] **Martin 集成** — 外部矢量切片服务器配置 ✅ 2026-04-04
- [x] **Migration 050** — mvt_tile_layers 表 ✅ 2026-04-04

### 数据资产编码系统

- [x] **asset_coder.py** — DA-{TYPE}-{SRC}-{YEAR}-{SEQ} 编码规范 ✅ 2026-04-04
- [x] **data_catalog.py 集成** — 资产注册时自动分配编码 ✅ 2026-04-04
- [x] **Migration 051** — asset_code 字段 + 唯一索引 ✅ 2026-04-04

### 质量保障

- [x] **test_tile_server.py** — 切片生成/清理/API 全覆盖 ✅ 2026-04-04
- [x] **test_asset_coder.py** — 编码生成/解析/唯一性验证 ✅ 2026-04-04

---

## 已完成 (v18.0) — 应用层数据库优化

> **主题**: 连接池扩容 + asyncpg 异步引擎 + 读写分离预埋 + 物化视图 + 连接池监控
>
> **依据**: `docs/distributed_architecture_plan.md` Phase 1 (调整: 华为云 RDS 已有 HA，聚焦应用层优化)
>
> **目标**: 提升数据库连接效率和可观测性，为未来 RDS 只读副本做接口预埋

### 连接池扩容

- [x] **pool_size 5→20** — 适配华为云 RDS 连接能力 ✅ 2026-04-04
- [x] **max_overflow 10→30** — 允许更多突发连接 ✅ 2026-04-04
- [x] **环境变量配置** — DB_POOL_SIZE / DB_MAX_OVERFLOW 可调 ✅ 2026-04-04

### 读写分离接口预埋

- [x] **get_engine(readonly=True/False)** — 接口预埋，当前 fallback 到主库 ✅ 2026-04-04
- [x] **DATABASE_READ_URL 支持** — 配置 RDS 只读副本时自动启用读写分离 ✅ 2026-04-04
- [x] **get_pool_status()** — 连接池实时状态查询 ✅ 2026-04-04

### asyncpg 异步数据库引擎

- [x] **db_engine_async.py** — asyncpg 连接池单例 (min=5, max=20, 可配置) ✅ 2026-04-04
- [x] **便利函数** — fetch_async / fetchrow_async / fetchval_async / execute_async ✅ 2026-04-04
- [x] **RLS 上下文注入** — _inject_user_context_async 支持异步连接 ✅ 2026-04-04
- [x] **优雅关闭** — close_async_pool() 应用关闭时调用 ✅ 2026-04-04

### 物化视图

- [x] **Migration 052** — mv_pipeline_analytics + mv_token_usage_daily + refresh 函数 ✅ 2026-04-04
- [x] **只读角色** — agent_reader 角色创建 (SELECT only) ✅ 2026-04-04
- [x] **连接统计视图** — v_connection_stats (pg_stat_activity 聚合) ✅ 2026-04-04

### 连接池 Prometheus 监控

- [x] **4 个新 Gauge** — db_pool_size / checkedin / checkedout / overflow ✅ 2026-04-04
- [x] **查询延迟 Histogram** — db_query_duration_seconds ✅ 2026-04-04
- [x] **collect_db_pool_metrics()** — /metrics 端点自动采集 ✅ 2026-04-04

### 质量保障

- [x] **test_db_engine_v18.py** — 23 测试: 连接池配置/读写分离/async 生命周期/物化视图/监控 ✅ 2026-04-04

### 跳过的项目 (华为云 RDS 已内置)

- [~] ~~PostgreSQL 主从复制~~ — RDS 内置 HA
- [~] ~~Patroni 故障转移~~ — RDS 自动故障转移
- [~] ~~PgBouncer K8s 部署~~ — 应用层连接池已优化
- [~] ~~postgres-replication.yaml~~ — RDS 已处理

---

## 已完成 (v18.5) — 智能体平台能力增强 + Palantir 风格 UI 重设计

> **主题**: NL2Workflow + 提示词自动优化 + 评估器扩充 + Palantir-inspired 深色主题 UI
>
> **依据**: `docs/agentarts-benchmark-analysis.md` — 华为云 AgentArts 对标分析 + 产品顾问 UI/UX 建议
>
> **目标**: 补齐平台级能力短板 + 产品级视觉升级

### NL2Workflow — 自然语言生成工作流 (P0)

> AgentArts 核心能力: 用户一句话描述业务场景 → 自动生成可执行工作流 DAG

- [x] **NL2WorkflowGenerator** — LLM 解析自然语言需求 → 输出 workflow_engine DAG JSON ✅ 2026-04-04
- [x] **工具推荐** — 根据描述自动匹配 Toolset/Skill 节点 (23 内置 Skill 元数据) ✅ 2026-04-04
- [x] **预览确认** — 生成后返回 DAG 预览 + explanation，用户确认后执行 ✅ 2026-04-04
- [x] **WorkflowEditor 集成** — auto_save 参数直接保存到 workflow_engine ✅ 2026-04-04
- [x] **REST API** — `POST /api/workflows/generate` 接收自然语言描述 ✅ 2026-04-04
- [x] **验证** — 循环依赖检测 (Kahn 拓扑排序) + 字段完整性 + pipeline_type 校验 ✅ 2026-04-04
- [x] **测试** — 26 测试全覆盖 ✅ 2026-04-04

### 提示词自动优化 (P1)

> AgentArts 核心能力: 文本梯度自动分析 bad case → 提示词自动优化

- [x] **BadCaseCollector** — 从评估历史/pipeline 失败/用户反馈三源收集 bad case ✅ 2026-04-04
- [x] **FailureAnalyzer** — LLM 分析失败模式 (模式/根因/受影响 prompt) ✅ 2026-04-04
- [x] **PromptOptimizer** — 基于失败分析生成改进后的 prompt 版本 ✅ 2026-04-04
- [x] **Human-in-the-loop** — 优化建议保存到 dev 环境，需人工确认后部署 ✅ 2026-04-04
- [x] **REST API** — 4 端点 (collect-bad-cases / analyze-failures / optimize / apply-suggestion) ✅ 2026-04-04
- [x] **测试** — 20 测试全覆盖 ✅ 2026-04-04

### 评估器扩充 (P1)

> AgentArts: 30+ 平台精选评估器 (任务完成率/内容质量/安全/轨迹质量)

- [x] **EvaluatorRegistry** — 可插拔评估器注册表 ✅ 2026-04-04
- [x] **内置评估器 (15)** — Quality (ExactMatch/Regex/JsonSchema/Completeness/Coherence) + Safety (Safety/PII/SqlInjection) + Performance (Latency/TokenCost/OutputLength) + Accuracy (ToolCallAccuracy/Numeric/GeoSpatial/InstructionFollowing) ✅ 2026-04-04
- [x] **批量评估** — `run_evaluation()` 多评估器 × 多测试用例 + 聚合统计 ✅ 2026-04-04
- [x] **REST API** — `GET /api/eval/evaluators` + `POST /api/eval/evaluate` ✅ 2026-04-04
- [x] **测试** — 67 测试全覆盖 ✅ 2026-04-04

### Palantir-inspired UI/UX 重设计 (v18.5)

> 产品顾问建议参照 Palantir AIP 风格，提升产品级视觉品质

- [x] **Deep Intelligence 深色主题** — 设计令牌体系: #0B0F19 base / #3B82F6 primary / #111827 surface ✅ 2026-04-05
- [x] **字体升级** — Space Grotesk → Inter (UI) + JetBrains Mono (代码/数据) ✅ 2026-04-05
- [x] **Lucide 图标系统** — DataPanel 所有 emoji 图标 → Lucide SVG (lucide-react v1.7.0) ✅ 2026-04-05
- [x] **DataPanel 3 组重构** — 4 组 → 3 组 (数据资源 / 智能分析 / 平台运营)，编排组解散 ✅ 2026-04-05
- [x] **左右分屏登录页** — 居中卡片 → 左 60% 品牌展示 (统计+特性) + 右 40% 表单 ✅ 2026-04-05
- [x] **AppNav 图标导航栏** — 48px 左侧 icon rail + Header 56px → 40px 状态栏 ✅ 2026-04-05

---

## v19.0 — 上下文工程 + 反馈飞轮 (Datus.ai 对标) ✅ 2026-04-08

> **主题**: 统一上下文引擎 + 结构化反馈闭环 + 语义模型标准化 + 参考查询库
>
> **依据**: `docs/datus_ai_benchmark_analysis.md` — Datus.ai 对标分析 (上下文工程方法论 + 反馈飞轮设计)
>
> **核心洞察**: LLM 回答准确性 80% 取决于输入上下文质量，而非模型本身能力。积累的语义模型、参考查询、成功案例才是真正壁垒。
>
> **v19.0 S3 对象存储** 已在早期版本中实现 (cloud_storage.py + storage_manager.py + obs_storage.py)，版本号复用。

### P0 — 统一上下文引擎 (Context Engine)

> Datus 核心竞争力: Context Engine 自动构建"活的语义地图"，融合 6 类知识源为统一检索接口
>
> 我们现状: semantic_layer.py / knowledge_graph.py / knowledge_base.py / context_manager.py 分散在 4 个模块

- [x] **ContextEngine 统一抽象** — 新增 `context_engine.py`: 融合所有知识源为一个检索接口，替代 BCG context_manager.py 的简单实现 ✅ 2026-04-08
- [x] **6 个 ContextProvider** — SemanticLayerProvider (现有) / KnowledgeGraphProvider (现有) / KnowledgeBaseProvider (现有) / ReferenceQueryProvider (新增) / SuccessStoryProvider (新增) / MetricDefinitionProvider (新增) ✅ 2026-04-08
- [x] **相关性排序** — 基于 query embedding + 任务类型对所有 provider 返回的上下文块进行统一排序 ✅ 2026-04-08
- [x] **Token 预算截断** — 按相关性分数截断到 token_budget，确保不超出 LLM 上下文窗口 ✅ 2026-04-08
- [x] **上下文缓存** — 相同 query + task_type 组合缓存 3 分钟，避免重复检索 ✅ 2026-04-08
- [x] **Pipeline 集成** — Planner/Executor 在生成计划和执行工具前自动调用 `context_engine.prepare()` ✅ 2026-04-08
- [x] **REST API** — `GET /api/context/prepare` (预览上下文) + `GET /api/context/providers` (列出 provider 状态) ✅ 2026-04-08
- [x] **测试** — context_engine 统一检索 + provider 注册 + 排序 + 截断 + 缓存全覆盖 ✅ 2026-04-08

### P0 — 结构化反馈学习闭环 (Feedback Loop)

> Datus 核心差异化: 用户每次 upvote/downvote 都在训练系统，形成"越用越准"的飞轮
>
> 我们现状: prompt_optimizer.py 有 bad case 收集，但无用户侧反馈采集 UI 和自动学习管道

- [x] **前端反馈 UI** — 每条 Agent 回答增加 👍/👎 按钮 + 可选 issue 描述弹窗 (ChatPanel 消息组件扩展) ✅ 2026-04-08
- [x] **agent_feedback 表** — Migration: query_text, response_text, vote (up/down), issue_description, pipeline_type, resolved_at, created_by ✅ 2026-04-08
- [x] **反馈收集 API** — `POST /api/feedback` (提交反馈) + `GET /api/feedback/stats` (反馈统计) ✅ 2026-04-08
- [x] **成功案例自动提取** — upvote 的查询自动提取为参考查询 (query + response + tags)，进入 ReferenceQueryProvider ✅ 2026-04-08
- [x] **失败模式分析管道** — 定期聚合 downvote 反馈 → 调用 prompt_optimizer.py FailureAnalyzer → 生成改进建议 ✅ 2026-04-08
- [x] **反馈→上下文自动更新** — 成功案例 → SuccessStoryProvider；失败模式 → 触发 prompt 优化建议 ✅ 2026-04-08
- [x] **反馈看板** — DataPanel 新增反馈统计子面板 (满意率趋势 / 高频失败模式 / 最近反馈列表) ✅ 2026-04-08
- [x] **测试** — 反馈 CRUD + 成功案例提取 + 失败分析管道 + 统计聚合全覆盖 ✅ 2026-04-08

### P1 — 语义模型标准化 (MetricFlow 兼容)

> Datus 采用 MetricFlow YAML 语义模型，自动从表结构生成，支持指标/维度/关系定义
>
> 我们现状: semantic_layer.py 自定义三级层次结构，与主流数据栈不兼容

- [x] **GIS Semantic Model YAML 格式** — 扩展 MetricFlow YAML 规范，增加 `type: spatial` 维度 + `srid` 字段 + `geometry_type` 属性 ✅ 2026-04-08
- [x] **自动生成器** — `gen_semantic_model` 工具: 从 PostGIS 表结构自动生成语义模型 YAML ✅ 2026-04-08
- [x] **semantic_layer.py 适配** — 现有三级层次结构保留为向后兼容，新增 MetricFlow YAML 读取器 ✅ 2026-04-08
- [x] **语义模型 CRUD API** — `GET/POST/PUT/DELETE /api/semantic/models` ✅ 2026-04-08
- [x] **MetricDefinitionProvider** — 从语义模型中提取指标定义，注入 ContextEngine ✅ 2026-04-08
- [x] **测试** — YAML 解析 + PostGIS 表结构提取 + 语义模型 CRUD + Provider 注入全覆盖 ✅ 2026-04-08

### P1 — 参考查询库 (Reference Query Library)

> Datus 的 gen_sql_summary 子Agent 自动分类+标注 SQL，成功查询积累为参考库
>
> 我们现状: 无验证过的参考查询积累机制

- [x] **agent_reference_queries 表** — Migration: query_text, description, tags[], verified_by, use_count, success_rate, pipeline_type, created_by ✅ 2026-04-08
- [x] **ReferenceQueryProvider** — 实现 ContextProvider 接口，基于 query embedding 检索相似参考查询 ✅ 2026-04-08
- [x] **自动入库** — 用户 upvote → 查询自动进入参考库 (关联 agent_feedback 表) ✅ 2026-04-08
- [x] **手动策展** — `POST /api/reference-queries` 手动添加参考查询 + `PUT` 编辑标签/描述 ✅ 2026-04-08
- [x] **NL2SQL 增强** — NL2SQLToolset 执行前先检索参考库中的相似查询作为 few-shot 示例 ✅ 2026-04-08
- [x] **REST API** — 6 端点 (CRUD + search + stats) ✅ 2026-04-08
- [x] **测试** — 参考查询 CRUD + 相似度检索 + NL2SQL few-shot 注入全覆盖 ✅ 2026-04-08

### 质量保障

- [x] **test_context_engine.py** — 统一上下文引擎全流程 ✅ 2026-04-08
- [x] **test_feedback_loop.py** — 反馈收集→学习→上下文更新闭环 ✅ 2026-04-08
- [x] **test_semantic_model_metricflow.py** — MetricFlow YAML 解析+生成 ✅ 2026-04-08
- [x] **test_reference_queries.py** — 参考查询库 CRUD + NL2SQL 集成 ✅ 2026-04-08

---

## v20.0 — 分布式任务队列与缓存 + 体验优化 ✅ 2026-04-08

> **状态**: ✅ 完成 — Redis 本机部署 (localhost:6379)
>
> **主题**: Celery 分布式任务队列 + Redis 缓存 + Datus 对标 P2 体验优化项
>
> **依据**: `docs/distributed_architecture_plan.md` Phase 2 + `docs/datus_ai_benchmark_analysis.md` P2 项

### Redis 分布式任务队列 ✅

- [x] **redis_client.py** — 统一 Redis 连接管理 (async/sync) + 分布式锁 RedisLock (SETNX+TTL+Lua) ✅ 2026-04-08
- [x] **task_queue.py Redis 后端** — Sorted Set 优先级队列 + 分布式信号量 + 内存降级 ✅ 2026-04-08
- [x] **Redis 缓存迁移** — semantic_layer.py + context_engine.py 双层缓存 (Redis+内存) ✅ 2026-04-08
- [x] **health.py 集成** — Redis 健康检查 + System Status 显示版本 ✅ 2026-04-08

### P2 — 多 LLM 一键切换体验 ✅

- [x] **统一 LLM 配置 YAML** — `conf/models.yaml` 声明式配置所有 LLM provider ✅ 2026-04-08
- [x] **model_gateway.py 适配** — load_from_yaml() 动态注册，保持现有 API 兼容 ✅ 2026-04-08

### P2 — Agentic/Workflow 双模式 ✅

- [x] **模式检测** — intent_router.py 增加 execution_mode 检测 (中英文关键词 + WORKFLOW 意图) ✅ 2026-04-08
- [x] **Agentic Mode** — 现有语义路由 → Planner 自主决策 → 灵活探索 (默认模式) ✅ 2026-04-08
- [x] **Workflow Mode** — 选择预定义工作流 → 确定性步骤执行 → 无 LLM 中间决策 ✅ 2026-04-08
- [x] **模式感知路由** — intent_router.py 返回 execution_mode，app.py 消费 ✅ 2026-04-08

### P2 — 轻量化部署选项 ✅

- [x] **DuckDB 适配器** — duckdb_adapter.py: DuckDB + spatial 扩展，GeoDataFrame 双向转换 ✅ 2026-04-08
- [x] **Lite 模式设计** — 仅 General Pipeline + DuckDB 后端，无 PostGIS 依赖 ✅ v23.0
- [x] **可选依赖分组** — `pip install gis-data-agent[lite]` (核心) vs `[full]` (含 PostGIS/DRL/WorldModel) ✅ v23.0
- [x] **快速启动脚本** — `gis-agent init` 一键初始化 (DuckDB + 默认配置 + 示例数据) ✅ 2026-04-08

---

## 已完成 (v24.0) — @SubAgent 显式路由 + XMI 领域标准

> **主题**: 专家用户直控 + 行业标准体系化
>
> **日期**: 2026-04-19

### @SubAgent Mention Routing
- [x] **mention_registry.py** — 4 类 target 聚合（pipeline / sub-agent / custom skill / ADK skill），handle 去重 + 大小写无关查找
- [x] **mention_parser.py** — leading `@handle` 正则解析，非首位 `@` 忽略，未知 mention 回退语义路由
- [x] **app.py 集成** — `classify_intent()` 前插入 mention 路由，4 种 dispatch 路径（pipeline 直设 intent / sub-agent 状态校验+直接执行 / custom skill DB 查找+build_custom_agent / ADK skill SkillToolset 包装）
- [x] **agent.py `_make_agent_by_name`** — 10 个子代理工厂 lambda，ADK one-parent 约束下按需创建新实例
- [x] **GET /api/chat/mention-targets** — RBAC 过滤的 autocomplete 数据源，返回 handle/type/description/allowed/required_state_keys
- [x] **ChatPanel.tsx autocomplete** — `@` 触发 dropdown，ArrowUp/Down 导航，Enter/Tab 选中，Esc 关闭，onMouseDown 点选
- [x] **observability.py** — `mention_routes` Prometheus counter (target_type/handle/status) + `log_mention_event` 结构化日志
- [x] **24 单元/集成测试** — TestMentionRegistry (9) + TestMentionParser (8) + TestMentionDispatch (4) + TestMentionTargetsAPI (3)

### XMI Domain Standard System
- [x] **XMI 领域标准体系** — 解析器、编译器、工具集、上下文提供器、REST API、前端 Tab

---

## 四看驱动的战略刷新 (2026-04-21)

> **背景**: 基于 2026 Q2 技术四看分析（技术趋势 / 宏观 PEST / 竞争格局 / 自我评估），行业已从"AI 辅助数据治理"全面进入 **Agentic Data Governance** 阶段。GIS Data Agent 原型阶段已完成，下一阶段以"智能体驱动的时空数据治理平台"为叙事，分三个版本产品化落地。
>
> **四看核心结论**:
> - **趋势**: Gartner 2026 MQ for D&A Governance 把 agentic AI + 活跃元数据作为核心评估维度；数据产品化 + AI-Ready Data 成为新范式；MCP/A2A 协议栈重塑 Agent↔数据集成
> - **宏观**: 国务院"AI+"意见、国家数据局数据产权三权分置登记、网安法修订罚款 5-10 倍提升、EU AI Act 2026.8 全面执行
> - **竞争**: 北京数慧（数据编织 + 智能体）、土豆数据（Data for AI 闭环）、阿里 DataWorks（Agent + 语义 ETL）、袋鼠云（多模态数据中台）、Atlan / Alation / Ataccama（agentic governance + metadata lakehouse）
> - **自己**: 空间数据一等公民是核心优势；智能化治理从"缺失"升级为"原型验证"；多模态治理、数据产品化、合规审计、声明式治理仍为缺失项

---

## v25.0 — Agentic Governance Foundation (2026 H2, 计划)

> **主题**: 把 GIS Data Agent 的智能化治理原型产品化，补齐 agentic data governance 基础设施
>
> **Data Agent Level**: L3.5 → **L4**（治理 Agent 自主执行 + 声明式策略 + 持续监控）
>
> **工作量估算**: 4-5 个月 | **依赖**: 无外部基础设施硬依赖（Kong / Jaeger 等保持搁置）

### P0 — 活跃元数据引擎 (Atlan / Gartner 对标)

- [ ] **active_metadata.py** — 统一活跃元数据层，封装 `semantic_layer.py` + `data_catalog.py` 现有能力 + 新增变更事件流
- [ ] **自动采集扩展** — DB schema / 文件 / API 源 / MCP 工具四类来源的元数据自动采集
- [ ] **元数据 CDC 事件流** — 元数据变更 → Redis Stream → 下游 Agent 订阅响应（血缘重建、质量门禁触发）
- [ ] **活跃血缘** — 当前 BFS 血缘 → 增量血缘 + 影响分析（upstream change → downstream impact 告警）
- [ ] **策略联动** — 元数据变更触发治理策略自动执行（质量门禁、分类分级、合规检查）

### P0 — 治理 Agent 体系 (Alation / Ataccama 对标)

- [ ] **ClassificationAgent** — `skills/classification-agent/` + Skill L1/L2/L3，智能分类分级 + 规则库持续学习
- [ ] **QualityAgent** — `skills/quality-agent/`，智能质检 + 自动修复 + 质量趋势预测
- [ ] **LineageAgent** — `skills/lineage-agent/`，血缘自动发现 + 影响分析 + 血缘差异报告
- [ ] **ComplianceAgent** — `skills/compliance-agent/`，合规审计检查 + 审计报告生成 + 整改追踪
- [ ] **CurationAgent** — `skills/curation-agent/`，元数据策展 + 质量门禁 + 自然语言治理意图翻译
- [ ] **GovernanceTeamPipeline** — 5 个 Agent 组成的治理协作管线，复用现有 `TeamToolset` + A2A 协议

### P0 — 声明式治理引擎 Policy as Code (Alation Curation Automation 对标)

- [ ] **policy_engine.py** — 治理策略 DSL（YAML / JSON），类型: quality / classification / compliance / lineage
- [ ] **LLM 策略翻译层** — 自然语言治理意图（如"所有含身份证号的字段必须脱敏"）→ 可执行策略定义
- [ ] **持续监控** — 策略周期性检查（cron / 事件驱动）+ 违规告警 + Agent 自动修复
- [ ] **策略版本管理** — 复用现有 `prompt_registry.py` 模式，支持 dev/staging/prod 环境隔离 + 回滚
- [ ] **workflow_engine.py 扩展** — 新增 `policy_execution` 步骤类型，让策略执行纳入工作流编排

### P0 — 数据产品化框架 (Gartner MQ 2026 "数据产品策展")

- [ ] **data_products.py** — DataProduct 实体：数据契约 + 质量 SLA + 版本 + 消费统计 + 生命周期
- [ ] **数据契约 DSL** — 面向消费者的数据契约定义（schema / freshness / completeness / uniqueness）
- [ ] **质量门禁** — 数据产品发布前自动执行质检，未达标不允许发布
- [ ] **数据产品目录** — 扩展现有 Marketplace，支持数据产品的发布、订阅、消费审计
- [ ] **DB migration 064** — `agent_data_products` + `agent_data_product_contracts` + `agent_data_product_subscriptions`

### P1 — 统一治理仪表盘

- [ ] **GovernanceDashboard.tsx** — 治理覆盖率 / 质量趋势 / 合规状态 / Agent 执行统计四象限视图
- [ ] **治理 KPI API** — `/api/governance/kpi` 聚合治理运营指标
- [ ] **告警中心** — 治理异常的集中告警视图（复用现有 `AlertEngine`）

### P2 — 面向空间数据的治理深化

- [ ] **空间数据契约** — 数据产品契约扩展空间维度（CRS / 空间范围 / 几何有效性 / 拓扑一致性）
- [ ] **空间质检 Agent 化** — 现有 PrecisionToolset + DataCleaningToolset 包装为 QualityAgent 的子能力
- [ ] **空间血缘可视化增强** — 血缘图谱在 MapPanel 上叠加展示（数据流经过的空间范围）

---

## v26.0 — Multi-Modal & Data Economy (2027 H1, 计划)

> **主题**: 多模态数据治理 + 数据要素流通与资产化支撑
>
> **Data Agent Level**: L4 → **L4+**（多模态治理 + 数据资产化 + 合规自动化）
>
> **工作量估算**: 5-6 个月 | **驱动政策**: 国家数据局数据产权登记、数据资产入表、网安法修订合规审计

### P0 — 多模态数据治理 (袋鼠云多模态中台对标)

- [ ] **unstructured_governance.py** — 文档 / 图像 / 视频 / 音频的元数据采集、解析、治理
- [ ] **PDF / Word 解析器** — 结构化抽取（章节、表格、图片）+ 元数据提取 + 向量化
- [ ] **图像 / 视频元数据提取** — EXIF / 帧采样 / OCR + 场景分类
- [ ] **非结构化数据质检** — 完整性 / 格式合规 / 内容分类 / 敏感信息识别
- [ ] **统一元数据模型** — 覆盖结构化 + 空间（矢量 / 栅格 / 三维）+ 非结构化的统一 schema
- [ ] **multimodal.py 扩展** — 与 active_metadata 集成，非结构化数据自动纳入元数据管理

### P0 — 数据资产化支撑 (响应数据资产入表政策)

- [ ] **data_asset_valuation.py** — 数据资产价值评估模型（成本法 / 收益法 / 市场法）
- [ ] **资产编码体系增强** — 扩展现有 `DA-{TYPE}-{SRC}-{YEAR}-{SEQ}` 编码，对接数据产权登记
- [ ] **数据资产盘点** — 自动化数据资产清单生成（数量 / 质量 / 使用频次 / 衍生关系）
- [ ] **入表辅助报告** — 按财政部《企业数据资源相关会计处理暂行规定》生成辅助资料
- [ ] **数据产权三权分置支持** — 持有权 / 使用权 / 经营权元数据字段 + 登记信息导出

### P0 — 合规审计自动化 (响应网安法修订 + 个保法合规审计制度)

- [ ] **compliance_audit.py** — 合规检查规则库 + 自动化审计引擎
- [ ] **GB/T 45574（敏感个人信息）规则适配** — 2025.11 生效
- [ ] **GB/T 46068（跨境处理）规则适配** — 2026.3 生效
- [ ] **个人信息合规审计** — 处理 1000 万+ 个人信息的企业每两年审计（自动生成审计底稿）
- [ ] **跨境数据传输 PIP 认证辅助** — 非 CIIO 年传输 10 万-100 万人数据的合规检查
- [ ] **整改追踪工作流** — 审计发现 → 整改任务 → Agent 自动修复 → 复查

### P1 — 可信流通接口层 (预留数据空间 / 隐私计算集成位)

- [ ] **trusted_exchange.py** — 数据契约签署 + 使用权授权 + 审计日志的统一抽象
- [ ] **IDSA 连接器骨架** — 为可信数据空间预留连接器位置，实现需外部基础设施
- [ ] **隐私计算集成接口** — 对接华为等厂商的隐私计算基础设施（联邦学习 / 多方安全计算）
- [ ] **数据产权登记导出** — 生成符合国家数据局登记指南格式的 XML / JSON

### P1 — 湖仓一体适配 (航天云际 / 星环科技对标)

- [ ] **connectors/doris.py** — Doris 连接器 + 元数据采集
- [ ] **connectors/starrocks.py** — StarRocks 连接器
- [ ] **connectors/clickhouse.py** — ClickHouse 连接器
- [ ] **connectors/iceberg.py** — Iceberg 表格式元数据采集
- [ ] **空间数据湖仓统一查询** — PostGIS 空间能力 + 湖仓表数据的联邦查询

### P2 — 数据要素交易试点支撑

- [ ] **数据产品定价模型** — 基于使用频次 / 稀缺性 / 衍生价值的自动定价建议
- [ ] **数据产品交易记录** — 审计级别的交易日志 + 区块链存证预留接口

---

## v27.0 — Platform & Ecosystem (2027 H2 – 2028 H1, 计划)

> **主题**: 平台化 + 规模化 + 生态化 + 搁置项清零
>
> **Data Agent Level**: L4+ → **L4.5**（分布式治理 + Agent 互操作 + 经验沉淀 + 行业知识库深化）
>
> **工作量估算**: 6-12 个月 | **依赖**: 外部基础设施就位（K8s 集群 / Kong / Jaeger / Loki / 隐私计算底座）

### P0 — Agent 互操作协议标准化 (MCP / A2A 对标)

- [ ] **治理 Agent MCP 暴露** — v25.0 的 5 个治理 Agent 通过 MCP 向外部工具链暴露
- [ ] **跨组织 A2A 协作** — 数据空间场景下的跨组织 Agent 协作（需可信身份 + 权限协商）
- [ ] **MCP 工具目录联邦** — 多实例 MCP Hub 的工具目录联邦查询
- [ ] **Agent 服务注册中心** — 基于现有 `agent_registry.py` 扩展，支持跨实例 Agent 发现

### P0 — 分布式治理架构

- [ ] **治理任务分布式调度** — 基于现有 Celery 扩展，大规模数据治理任务拆分 + 并行执行
- [ ] **metadata_federation.py** — 多实例元数据联邦同步（最终一致性）
- [ ] **水平扩展** — 治理 Agent 无状态化 + 水平扩缩容（HPA）

### P1 — Hermes 观察池择机落地

- [ ] **USER Profile 轻量层** — 用户偏好记录（输出粒度 / 常用场景 / 工作习惯）
- [ ] **历史会话召回** — PG FTS 检索 + LLM 总结，支持"上次做到哪了"
- [ ] **Skill 建议沉淀** — 从成功任务 / 高质量工作流中提炼 Skill / Prompt 建议
- [ ] **结果卡片沉淀入口** — ChatPanel "沉淀为能力"按钮，人工确认后入库

### P1 — 行业知识库深化

- [ ] **行业数据标准自动匹配** — 数据进入时自动匹配 DLTB / GB/T 21010 / CityGML 等标准
- [ ] **行业质检规则模板库** — 自然资源 / 住建 / 水利 / 测绘 / 新能源的质检规则预置
- [ ] **行业治理最佳实践案例库** — 扩展现有 `knowledge_base.py` 的 case 能力
- [ ] **行业本体库** — 基于 v15.7 XMI 领域标准 + v16.0 本体论技术，持续沉淀行业本体

### P2 — 外部基础设施落地 (搁置项清零)

- [ ] **Kong API 网关** — kong-gateway.yaml + Ingress + 插件绑定
- [ ] **Jaeger 追踪后端** — 与 OTel 现有埋点对接
- [ ] **Loki 集中日志** — LokiHandler 日志推送 + 与 trace_id 关联
- [ ] **Grafana 统一看板** — Prometheus + Jaeger + Loki 三数据源聚合

### P2 — 面向客户的产品化交付

- [ ] **治理交付模板** — 面向自然资源 / 住建 / 水利的"开箱即用"治理方案（Skill + Workflow + Policy 三件套）
- [ ] **治理成熟度评估工具** — 对标 DAMA / 《智能化数据治理能力要求》，自动生成客户治理成熟度报告
- [ ] **迁移助手** — 从传统数据治理平台（睿治 / 普元 / 国网等）的资产迁移工具

---

## v21.0+ — L4 主动式探索 (已完成项归档)

> 本节内容为 v21.0-v23.0 已完成项归档；v24.0 之后的新规划请参见上方 v25.0 / v26.0 / v27.0 段落



> **主题**: 从响应式 → 主动式，从有监督 → 无监督
>
> **依据**: SIGMOD 2026 论文 L4 愿景 + Datus.ai P3 CLI 入口
>
> **目标**: 持续监控 + 自主任务发现 + 内在动机驱动

### P3 — CLI 终端接口 ✅ (已在 v15.9 实现)

- [x] **gis-agent CLI 框架** — cli.py (609 行, Typer + Rich) ✅
- [x] **chat 命令** — `gis-agent chat` 交互式 REPL + `gis-agent run "..."` 单次执行 ✅
- [x] **TUI 全屏界面** — tui.py (601 行, Textual) 三面板布局 (Chat/Report/Status) ✅
- [x] **Rich 终端渲染** — 表格/进度条/Markdown 渲染 ✅

### 跨系统血缘与数据治理 ✅ 2026-04-08

- [x] **跨系统血缘追踪** — agent_asset_lineage 边表 + 外部资产字段 (external_system/external_id/external_url) ✅ 2026-04-08
- [x] **Migration 056** — agent_asset_lineage 表 + agent_data_assets 外部字段 ✅ 2026-04-08
- [x] **register_external_asset** — 注册外部系统资产 (Tableau/Airflow/PowerBI) ✅ 2026-04-08
- [x] **add_lineage_edge** — 内部↔外部任意组合血缘边 ✅ 2026-04-08
- [x] **get_cross_system_lineage** — BFS 跨系统血缘图谱查询 ✅ 2026-04-08
- [x] **REST API** — 5 端点 (添加血缘/跨系统图谱/注册外部资产/列出系统/删除边) ✅ 2026-04-08

### API 网关与服务网格 ⏸️ (搁置: 等待 Kong 实例)

- [~] **Kong API 网关** — 统一入口，限流/熔断/认证前置 *(搁置)*
- [ ] **kong-gateway.yaml** — K8s 部署 (2 副本 + LoadBalancer)
- [x] **限流插件** — RateLimitMiddleware per-user/minute + per-IP/hour ✅ 2026-04-08
- [x] **JWT 认证** — Starlette 中间件层 JWT cookie 认证 ✅
- [x] **熔断器** — CircuitBreakerMiddleware CLOSED→OPEN→HALF_OPEN ✅ 2026-04-08
- [ ] **kong-ingress.yaml** — Ingress 配置 + 插件绑定

### 分布式追踪与可观测性 ⏸️ (搁置: 等待 Jaeger/Loki 实例)

- [x] **OpenTelemetry 全链路追踪** — HTTP/DB/Pipeline/Tool/LLM 埋点就绪，graceful degradation ✅ v23.0 *(导出需 Jaeger)*
- [~] **Jaeger 追踪后端** — 存储 trace 数据 + UI 查询 *(搁置: 需 Jaeger 实例)*
- [~] **Loki 集中日志** — 替代 stdout，与 trace_id 关联 *(搁置: 需 Loki 实例)*
- [~] **Grafana 统一看板** — Prometheus + Jaeger + Loki 数据源 *(搁置: 需 Grafana 实例)*
- [x] **observability.py 增强** — setup_otel_tracing() + get_tracer() 已实现 ✅
- [~] **LokiHandler** — 日志自动推送到 Loki *(搁置: 需 Loki 实例)*

### SIGMOD 2026 论文借鉴 (L4 能力，v22.0+)

#### **S-8: 持续监控与任务发现** ✅ 2026-04-08
- [x] **DataLakeMonitor** — 7x24 监控守护进程 ✅ 2026-04-08
- [x] **数据漂移检测** — 自动发现数据分布变化 → 触发重训练任务 ✅ 2026-04-08
- [x] **性能退化检测** — 查询延迟监控 → 触发优化任务 ✅ 2026-04-08
- [x] **优化机会发现** — 缺失索引、有益物化视图、冗余计算 → 自主优化 ✅ 2026-04-08
- [x] **任务优先级** — 多任务自主排序 (紧急度 × 收益) ✅ 2026-04-08

#### **S-9: 内在动机引擎** ✅ 2026-04-08
- [x] **IntrinsicMotivation** — 内部奖励信号驱动探索 ✅ 2026-04-08
- [x] **奖励函数** — 发现新数据源 +10，提升数据质量 +5×improvement，减少延迟 +2×reduction ✅ 2026-04-08
- [x] **探索 vs 利用** — ε-greedy 策略平衡已知优化和新机会探索 ✅ 2026-04-08
- [x] **持续自我改进** — 基于操作日志和遥测数据适应策略 ✅ 2026-04-08

### 遥感智能体 Phase 2-4 (v22.0+)

#### **Phase 2: 时空分析**
- [x] **变化检测引擎** — 双时相差异 + 指数差异 + 分类后比较 (rs_temporal.py) ✅ 2026-04-08
- [x] **时间序列分析** — Mann-Kendall 趋势 + 断点检测 (rs_temporal.py) ✅ 2026-04-08
- [x] **证据充分性评估** — 数据覆盖度 × 方法多样性 × 结论支撑强度 (rs_temporal.py) ✅ 2026-04-08

#### **Phase 3: 智能化可信度**
- [x] **代码生成执行** — validate_generated_code 安全沙箱验证 (rs_credibility.py) ✅ 2026-04-08
- [x] **幻觉检测增强** — 空间约束 Fact-Checking + 多源交叉验证 (rs_credibility.py) ✅ 2026-04-08
- [x] **多 Agent Debate** — 主分析 + 独立验证 + 证据评分 + 判定 (rs_credibility.py) ✅ 2026-04-08
- [x] **RS 领域知识库** — 光谱特性 (5 指数) + 处理流程 (3 模板) + 分类体系 (3 标准) ✅ 2026-04-08

#### **Phase 4: 高级遥感**
- [ ] **SAR/高光谱/LiDAR** 数据处理
- [ ] **深度学习推理** — segment-anything-geo / SatMAE / Prithvi
- [x] **具身执行接口** — BaseExecutor ABC + MockUAV/Satellite + 注册表 ✅ v23.0 *(对接实际硬件待定)*
- [x] **Gemma 4 + 多模型管理** — Gemma 4 31B 注册 (Gemini API + vLLM) + DB 持久化管理员配置 + 前端交互式切换 + Intent Router 可配置化 ✅ v23.0

---

## Hermes Agent 对标观察池 (暂不承诺版本)

> **定位**: 作为后续平台化增强候选项进入观察池，不纳入当前已承诺版本范围
>
> **依据**: `docs/hermes_agent_benchmark_analysis.md`
>
> **原则**: 以垂直场景落地优先，仅在有明确产品收益或客户牵引时择机迭代；优先做低成本、高复用、可独立验证的小步增强

### 候选方向 (按建议优先级)

#### P0 — 连续协作体验增强 (优先试点)
- [ ] **USER Profile 轻量层** — 记录用户偏好输出粒度、常用场景、工作习惯，用于提升跨会话协作连续性
- [ ] **历史会话召回** — 基于 SQLite/PostgreSQL FTS 检索历史对话并由 LLM 总结，用于"上次做到哪了"类问题

#### P0 — 经验沉淀闭环 (小范围验证)
- [ ] **Skill 建议沉淀** — 从成功任务、用户正反馈或高质量工作流中自动提炼 Skill / Prompt / Workflow 建议项
- [ ] **结果卡片沉淀入口** — ChatPanel 增加"沉淀为能力"入口，人工确认后入库，避免全自动写入污染资产库

#### P1 — Agent Runtime 平台化增强 (观察项)
- [ ] **执行后端抽象** — 梳理 local / docker / remote worker / arcpy worker / gpu worker 等统一执行后端接口
- [ ] **Agent 执行面安全栈** — 补齐 User Tool / MCP / Shell 级别的审批、分级权限、URL/SSRF 防护、上下文注入检测、隔离执行策略
- [ ] **轻量多入口扩展** — 先考虑消息投递/任务回执类入口，不优先建设完整 TUI 或通用消息网关

### 何时启动
- 出现明确客户需求：需要连续协作、跨端触达、远程任务托管或更强 Agent 安全治理
- 现有垂直场景（测绘质检 / 新能源 / 数据治理）交付稳定，主线需求阶段性收敛
- 能以 1-2 周试点验证价值，而非大规模架构改造

### 当前结论
- **现在不立即启动 Hermes 方向的大规模建设**
- 先保留为 roadmap 观察池，后续仅择机推进 1 个低成本 P0 试点

---

## 标杆对标进度 (更新 2026-04-18)

> 新增标杆: DeerFlow (ByteDance 通用 Agent Harness) + **AgentArts (华为云企业级智能体平台)** + **Datus.ai (开源数据工程智能体 — 上下文工程 + 反馈飞轮)** + **Hermes Agent (通用 Agent Runtime — learning loop + 持久记忆 + 多入口网关)**
>
> AgentArts 对标详情见 `docs/agentarts-benchmark-analysis.md`
>
> Datus.ai 对标详情见 `docs/datus_ai_benchmark_analysis.md`
>
> Hermes Agent 对标详情见 `docs/hermes_agent_benchmark_analysis.md`

| 标杆能力 | 来源 | v16.0 ✅ | v17.1 ✅ | v18.0 ✅ | v18.5 ✅ | v19.0 ✅ | v20.0 ✅ | v21.0 ✅ |
|----------|------|-----------|-----------|-----------|-----------|-----------|-----------|-----------|
| 空间数据虚拟化 | SeerAI | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢🟢 跨系统 |
| 知识图谱语义发现 | SeerAI | 🟢 | 🟢 | 🟢🟢 本体推理 | 🟢🟢 | 🟢🟢🟢 上下文引擎 | 🟢🟢🟢 | 🟢🟢🟢 |
| 分析血缘自动追踪 | SeerAI | 🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢🟢 跨系统 |
| 行业预置模板 | SeerAI | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 |
| Agent 对话交互 | OpenClaw | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 NL2W | 🟢🟢🟢 反馈UI | 🟢🟢🟢 | 🟢🟢🟢🟢 CLI |
| 企业级治理 | Frontier | 🟢🟢🟢 | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 |
| Agent 可观测性 | — | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢🟢 全链路 |
| 多 Agent 协作 | CoWork | 🟢🟢🟢 | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 |
| 时空预测 | — | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 |
| 因果推断 | — | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 |
| 测绘质检 | — | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 |
| 企业平台 | BCG | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢🟢 评估器+NL2W | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 |
| **Harness/App 分离** | DeerFlow | 🔴 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 |
| **中间件链** | DeerFlow | 🔴 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 |
| **上下文摘要** | DeerFlow | 🔴 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 |
| **Guardrails** | DeerFlow | 🟡 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 |
| **Planner-Executor** | SIGMOD L3 | 🔴 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 |
| **语义算子** | SIGMOD L3 | 🔴 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 |
| **工具选择器** | SIGMOD L3 | 🔴 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 |
| **因果错误诊断** | SIGMOD L3 | 🔴 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢 |
| **多模态融合** | — | 🟢🟢 基础 | 🟢🟢🟢 v2.0 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 |
| **NL2Workflow** | AgentArts | 🔴 | 🔴 | 🔴 | 🟢🟢 | 🟢🟢 | 🟢🟢 | 🟢🟢🟢 |
| **提示词自动优化** | AgentArts | 🔴 | 🔴 | 🔴 | 🟢🟢 | 🟢🟢🟢 反馈驱动 | 🟢🟢🟢 | 🟢🟢🟢 |
| **评估器体系** | AgentArts | 🟡 | 🟡 | 🟡 | 🟢🟢🟢 15 评估器 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 |
| **产品级 UI** | Palantir | 🟡 | 🟡 | 🟡 | 🟢🟢 深色主题 | 🟢🟢 反馈UI | 🟢🟢 | 🟢🟢🟢 |
| **数据库优化** | — | 🔴 | 🔴 | 🟢🟢 asyncpg+池 | 🟢🟢 | 🟢🟢 | 🟢🟢🟢 Celery | 🟢🟢🟢 |
| **矢量切片** | — | 🔴 | 🟢🟢🟢 MVT | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 |
| **上下文引擎** | Datus | 🔴 | 🔴 | 🔴 | 🟡 BCG CM | 🟢🟢🟢 统一引擎 | 🟢🟢🟢 | 🟢🟢🟢🟢 |
| **反馈学习闭环** | Datus | 🔴 | 🔴 | 🔴 | 🟡 bad case | 🟢🟢🟢 完整飞轮 | 🟢🟢🟢 | 🟢🟢🟢🟢 |
| **语义模型标准化** | Datus | 🔴 | 🔴 | 🔴 | 🟡 自定义 | 🟢🟢 MetricFlow | 🟢🟢 | 🟢🟢🟢 |
| **参考查询库** | Datus | 🔴 | 🔴 | 🔴 | 🔴 | 🟢🟢 NL2SQL 增强 | 🟢🟢🟢 | 🟢🟢🟢 |
| **多 LLM 切换** | Datus | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 | 🟢🟢 YAML 配置 | 🟢🟢🟢 |
| **双模式执行** | Datus | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🟢🟢 Agentic/WF | 🟢🟢🟢 |
| **CLI 终端入口** | Datus | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🟢🟢 gis-agent |
| **轻量部署** | Datus | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🟢🟢 DuckDB Lite | 🟢🟢 |
| **Learning Loop** | Hermes | 🔴 | 🔴 | 🔴 | 🔴 | 🟡 反馈闭环基础 | 🟡 | 🟡 观察池 |
| **持久用户画像** | Hermes | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🟡 观察池 |
| **历史会话召回** | Hermes | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🟡 观察池 |
| **执行后端抽象** | Hermes | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🟡 观察池 |
| **Agent 执行面安全栈** | Hermes | 🟡 Guardrails | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 观察池 |
| **多入口 Agent Runtime** | Hermes | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🟡 CLI | 🟡 观察池 |
| **API 网关** | — | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🟢🟢 Kong || **分布式追踪** | — | 🟡 OTel | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 | 🟢🟢🟢 Jaeger |
| **Data Agent Level** | SIGMOD | L3 | L3 | L3 | L3 | L3+ | L3+ | L3.5→L4 |

### 四看驱动的新增对标维度 (2026-04-21)

| 标杆能力 | 来源 | v24.0 ✅ | v25.0 🎯 | v26.0 🎯 | v27.0 🎯 |
|----------|------|----------|----------|----------|----------|
| **活跃元数据 (Active Metadata)** | Atlan / Gartner 2026 | 🟡 语义层 + 基础目录 | 🟢🟢🟢 CDC 事件流 + 策略联动 | 🟢🟢🟢🟢 全模态 | 🟢🟢🟢🟢 联邦 |
| **Agentic Governance** | Alation / Ataccama | 🟡 Agent 原型 | 🟢🟢🟢 5 治理 Agent | 🟢🟢🟢🟢 | 🟢🟢🟢🟢 MCP 标准化 |
| **声明式治理 (Policy as Code)** | Alation Curation Automation | 🔴 | 🟢🟢 LLM 策略翻译 + 规则库 | 🟢🟢🟢 合规策略 | 🟢🟢🟢🟢 |
| **数据产品化** | Gartner MQ 2026 "数据产品策展" | 🔴 | 🟢🟢 契约 + 目录 | 🟢🟢🟢 市场化 | 🟢🟢🟢🟢 |
| **多模态数据治理** | 袋鼠云多模态中台 | 🟡 `multimodal.py` 基础 | 🟡 | 🟢🟢🟢 非结构化治理 | 🟢🟢🟢🟢 |
| **数据资产化 / 入表** | 国家数据局三权分置 | 🔴 | 🟡 编码体系扩展 | 🟢🟢🟢 评估 + 辅助报告 | 🟢🟢🟢 |
| **合规审计自动化** | 网安法修订 / 个保法 | 🔴 | 🟡 合规 Agent 骨架 | 🟢🟢🟢 审计自动化 | 🟢🟢🟢🟢 |
| **MCP / A2A 互操作** | Anthropic / Google | 🟢🟢 MCP Hub | 🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢🟢 标准化暴露 |
| **湖仓一体适配** | 航天云际 / 星环 | 🔴 | 🟡 | 🟢🟢 Doris/StarRocks/ICE | 🟢🟢🟢 统一查询 |
| **可信数据空间** | 国家数据局行动计划 | 🔴 | 🔴 | 🟡 接口骨架 | 🟢🟢 集成华为等底座 |
| **行业知识库深化** | — | 🟢 XMI + 本体 | 🟢🟢 | 🟢🟢 | 🟢🟢🟢🟢 自然资源/住建/水利 |


### Data Agent Level 演进路径

```
v15.9: L2.8 — + Planner-Executor + 中间件链 + 工具选择 + 上下文摘要
v16.0: L3   — + 语义算子 + 多 Agent 协作 + 计划精化 + Guardrails
v17.0: L3   — + 多模态融合 v2.0 (时序对齐 + 语义增强 + 冲突解决) ✅
v17.1: L3   — + 矢量切片大数据渲染 (三级自适应) + 数据资产编码 ✅
v18.0: L3   — + 应用层 DB 优化 (连接池扩容 + asyncpg + 物化视图 + 监控) ✅
v18.5: L3   — + 平台能力增强 (NL2Workflow + 提示词自动优化 + 评估器) + Palantir UI ✅
v19.0: L3+  — + 上下文工程 (统一引擎 + 反馈飞轮 + 语义模型标准化 + 参考查询库) ✅ 2026-04-08
v20.0: L3+  — + 分布式任务队列 (Redis) + 多 LLM 切换 + 双模式执行 + DuckDB Lite ✅ 2026-04-08
v21.0: L3.5 — + 跨系统血缘追踪 (外部资产 + 血缘边表 + BFS 图谱) ✅ 2026-04-08
v21.0: L3.5 — + API 网关 + 分布式追踪 + 跨系统血缘 + CLI 终端入口 (向 L4 探索)
v22.0: L4-  — + 持续监控 + 任务发现 + 内在动机 (L4 初步) ✅ 2026-04-08
v23.0: L3.5 — + Roadmap 清零 (意图消歧 v2 + DRL 约束 + 交通/设施场景 + 离线模式) ✅ 2026-04-09
v24.0: L3.5 — + @SubAgent 显式路由 + XMI 领域标准 ✅ 2026-04-19
v25.0: L4   — + Agentic Governance (5 治理 Agent + 活跃元数据 + 声明式策略 + 数据产品化) 🎯
v26.0: L4+  — + 多模态治理 + 数据资产化 + 合规自动化 + 湖仓一体 + 可信流通接口 🎯
v27.0: L4.5 — + 分布式治理 + Agent 互操作 + 经验沉淀 + 行业知识库深化 + 搁置项清零 🎯
```

### 治理能力评估对标 (《智能化数据治理能力要求》22 项)

| 领域 | v14.5 ✅ | v18.5 ✅ | v21.0 ✅ | v24.0 ✅ | v25.0 🎯 | v26.0 🎯 | v27.0 🎯 |
|------|-----------|-----------|-----------|-----------|-----------|-----------|-----------|
| 数据标准 | 70% | 88% | 90% | 90% | 93% | 95% 多模态 | 98% |
| 数据模型 | 20% | 50% 本体 | 55% | 55% | 65% 语义+策略 | 75% 多模态 | 85% |
| 数据质量 | 90% | 98% | 98% | 98% | 98% | 98% | 98% |
| 数据安全 | 30% | 60% | 65% | 65% | 75% 合规 Agent | 85% 审计自动化 | 92% |
| 元数据 | 80% | 95% 语义 | 98% 跨系统 | 98% | 98% 活跃元数据 | 98% | 98% 联邦 |
| 数据资源 | 80% | 92% | 95% 分布式 | 95% | 95% | 98% 多模态+湖仓 | 98% |
| **综合** | **~62%** | **~80%** | **~84%** | **~84%** | **~87%** | **~92%** | **~95%** |

---

## 架构演进对比

### 当前架构 (v18.5)

```
单节点部署:
- App (1 进程, Chainlit + ADK)
- PostgreSQL (华为云 RDS 托管, 连接池 20+30, asyncpg 异步)
- 物化视图 (mv_pipeline_analytics + mv_token_usage_daily)
- 本地文件存储 (uploads/) + OBS 云存储可选
- Prometheus 监控 (连接池 + 查询延迟)
- 3300+ 测试, 254 REST API, 59 迁移, 40 工具集, 26 Skills

适用场景: 开发环境、演示、<20 用户
```

### 目标架构 (v21.0)

```
分布式高可用部署:
- App (3-5 Pod, HPA 自动扩缩容)
- Celery Worker (3 Pod, 任务并行执行)
- PostgreSQL (1主2从 + PgBouncer 连接池)
- Redis Cluster (3主3从, 分片 + 副本)
- MinIO (4 节点, 纠删码 EC:2)
- Kong Gateway (2 Pod, 限流 + 熔断)
- Observability Stack (Jaeger + Loki + Grafana)

适用场景: 生产环境、>50 用户、高并发
性能指标: 500+ 并发用户, <500ms P95 延迟, 99.9% 可用性
```

---

## 性能指标演进

| 指标 | v16.0 当前 | v18.0 目标 | v19.0 目标 | v21.0 目标 |
|------|------------|------------|------------|------------|
| 并发用户 | 10 | 50 | 200 | 500+ |
| 请求延迟 P95 | 2s | 1s | 800ms | <500ms |
| 数据库连接数 | 5 | 50 主 + 100 从 | 50 主 + 100 从 | 50 主 + 100 从 |
| 任务并发数 | 3 | 3 | 50+ | 50+ |
| 文件存储 | 本地 5GB | 本地 5GB | MinIO 10TB+ | MinIO 10TB+ |
| 可用性 | 单点 | 99% | 99.5% | 99.9% |
| RTO 恢复时间 | 手动 | <30 分钟 | <10 分钟 | <5 分钟 |
| RPO 数据丢失 | 未知 | <5 分钟 | <1 分钟 | <1 分钟 |

---

## 成本估算 (云厂商部署)

### 阿里云 (华东2 区域)

| 资源 | v16.0 | v21.0 | 月成本 |
|------|-------|-------|--------|
| ECS 计算 | 1×4C8G | 5×4C8G | ¥3000 |
| PolarDB MySQL | 无 | 2C4G 主从 | ¥1500 |
| Redis 集群 | 单实例 | 4G×3 节点 | ¥1200 |
| OSS 对象存储 | 无 | 10TB | ¥2000 |
| SLB 负载均衡 | 无 | 标准版 | ¥300 |
| **总计** | **~¥500** | **~¥8000** | **16x** |

### 自建 K8s (本地机房)

- 服务器 (32C64G × 3): 一次性 ¥60,000
- 存储 (20TB): 一次性 ¥30,000
- 网络设备: 一次性 ¥20,000
- **总计**: ~¥110,000 (一次性) + 电费/运维

---

## 实施时间线

| 版本 | 主题 | 工作量 | 开始时间 | 完成时间 |
|------|------|--------|----------|----------|
| v17.0 | 多模态融合 v2.0 | 4-6 周 | 2026-04-01 | ✅ 2026-04-04 |
| v18.0 | 数据库 HA | 2-3 周 | 2026-04-04 | ✅ 2026-04-04 |
| v18.5 | 平台能力 + UI | 2-3 周 | 2026-04-04 | ✅ 2026-04-05 |
| v19.0 | 上下文工程 + 反馈飞轮 (Datus) | 3-4 周 | 2026-04-08 | ✅ 2026-04-08 |
| v20.0 | 分布式队列 + 体验优化 | 3-4 周 | 2026-04-08 | ✅ 2026-04-08 |
| v21.0 | 跨系统血缘 + CLI | 4-5 周 | 2026-04-08 | ✅ 2026-04-08 |
| v22.0 | L4 持续监控 + 遥感 Phase 2-3 | 1-2 周 | 2026-04-08 | ✅ 2026-04-08 |
| v23.0 | Roadmap 清零 + DRL 约束 | 1-2 周 | 2026-04-09 | ✅ 2026-04-09 |
| v24.0 | @SubAgent 路由 + XMI 域标准 | 2-3 周 | 2026-04-18 | ✅ 2026-04-19 |
| **v25.0** | **Agentic Governance Foundation** | **4-5 个月** | **2026-05** | **🎯 2026 H2** |
| **v26.0** | **多模态治理 + 数据要素流通** | **5-6 个月** | **2026-12** | **🎯 2027 H1** |
| **v27.0** | **平台化 + 生态化 + 搁置项清零** | **6-12 个月** | **2027-07** | **🎯 2028 H1** |

**总计**: v12.0 → v24.0 全部完成。v25.0-v27.0 是基于 2026 Q2 技术四看刷新后的中长期规划，主线叙事从"Data Agent 自主性演进"升级为"Agentic Spatial Data Governance Platform"。

---

## 关键文件清单 (v17.0-v21.0)

### v17.0 多模态融合 v2.0 (新增 ~15 个文件)

- `data_agent/fusion/temporal_alignment.py` (~350 行)
- `data_agent/fusion/semantic_enhancement.py` (~400 行)
- `data_agent/fusion/conflict_resolution.py` (~380 行)
- `data_agent/fusion/explainability.py` (~320 行)
- `data_agent/toolsets/fusion_v2_tools.py` (~200 行)
- `data_agent/api/fusion_v2_routes.py` (~180 行)
- `frontend/src/components/datapanel/FusionV2Tab.tsx` (~250 行)
- 测试文件 4 个 (~800 行)

### v18.0-v21.0 分布式架构 (新增 ~40 个文件)

- `data_agent/db_engine_async.py` (~150 行)
- `data_agent/celery_app.py` + tasks/ (~400 行)
- `data_agent/storage/object_storage.py` (~180 行)
- `data_agent/archival/cold_storage.py` (~200 行)
- K8s 配置 15+ 个 YAML 文件
- 数据库迁移 3 个 (059-061)

---

## 总结

本次 roadmap 整合完成了 Datus.ai 对标分析的融入：

**1. v19.0 上下文工程 + 反馈飞轮 (Datus 对标, P0)** — 统一上下文引擎 + 结构化反馈闭环 + 语义模型标准化 + 参考查询库

**2. v20.0 增补体验优化项 (Datus 对标, P2)** — 多 LLM YAML 一键切换 + Agentic/Workflow 双模式 + 轻量部署 (DuckDB Lite)

**3. v21.0+ 增补 CLI 终端入口 (Datus 对标, P3)** — gis-agent CLI 三命令设计 (chat/context/exec)

**4. 标杆对标表扩展** — 新增 8 行 Datus 对标能力追踪 (上下文引擎/反馈闭环/语义模型/参考查询/多LLM/双模式/CLI/轻量部署)

**5. 演进逻辑** — v18.5 (平台能力) → v19.0 (上下文工程, **无外部依赖可立即启动**) → v20.0 (分布式+体验) → v21.0+ (生产级+CLI)

**6. 核心策略调整** — 从"Agent 更聪明"到"Agent 看到的上下文更好"。学习 Datus 的上下文工程方法论和反馈飞轮设计，嫁接到已有的空间智能深度上。

**7. Hermes 对标纳入观察池** — 将 learning loop、用户画像、历史会话召回、执行后端抽象、Agent 执行面安全栈列为后续平台化候选项，但不进入当前版本承诺，避免分散垂直场景交付主线。
