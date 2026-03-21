# GIS Data Agent — Roadmap

**Last updated**: 2026-03-21 &nbsp;|&nbsp; **Current version**: v14.3 &nbsp;|&nbsp; **ADK**: v1.27.2

> 参照标杆：SeerAI Geodesic（地理空间数据编排）、OpenClaw（Agent 交互）、Frontier（企业治理）、CoWork（多 Agent 协作）
>
> 核心战略：**智能层 + 交互层保持领先，数据层向 SeerAI 看齐**——从"用户带数据来"转向"Agent 主动发现和连接数据"

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
- [ ] **外部 Agent 接入验证** — Claude Desktop / Cursor 通过 MCP 连接 GIS Data Agent 的端到端测试

---

## 已完成 (v14.0) — 交互增强 + 扩展市场

> **主题**: 用户可见的体验提升，快速出价值

### 自然语言交互
- [x] **意图消歧对话** — AMBIGUOUS 分类时弹出选择卡片（Optimization/Governance/General），用户点选后路由
- [ ] **参数调整重跑** — pipeline 完成后显示"调整参数"按钮，提取上次参数 → 编辑表单 → 重新执行
- [ ] **记忆搜索面板** — ChatPanel 增加 `/recall` 命令或搜索图标，调用 `search_memory()` 展示历史分析

### 用户自扩展
- [x] **Marketplace 画廊** — DataPanel 新增"市场"tab，聚合所有 is_shared=true 的 Skills/Tools/Templates/Bundles，支持排序（评分/使用量/时间）
- [x] **统一评分系统** — Skills 和 Tools 增加 `rating_sum`/`rating_count` 字段 + REST 端点 `POST /api/skills/{id}/rate`、`POST /api/user-tools/{id}/rate`
- [x] **Skill/Tool Clone** — 允许用户克隆他人共享的 Skill/Tool 到自己名下

### DRL 优化
- [x] **场景模板系统** — 定义 `DRLScenario` 配置类，内置 3 个场景模板：耕地优化（现有）、城市绿地布局、设施选址
- [ ] **奖励权重 UI** — 前端可调 slope_weight / contiguity_weight / balance_weight 滑块 → 传入 pipeline

### 三面板 SPA
- [x] **热力图支持** — 集成 deck.gl `HeatmapLayer` 到 Map3DView，MapPanel 增加 `type: heatmap` 处理
- [x] **测量工具** — MapPanel 工具栏增加距离测量 + 面积测量（Leaflet.Draw 或 Turf.js）
- [x] **3D 图层控制** — Map3DView 增加图层列表面板，支持 show/hide/opacity 调节

### 多 Agent 编排
- [ ] **Workflow 断点续跑** — DAG 执行时每个 node 输出持久化到 DB，新增 `resume_workflow_dag(run_id, from_node)`
- [ ] **步骤级重试** — DAG 失败节点可单独重试（不重跑整个 workflow）

---

## 已完成 (v14.1) — 智能深化 + 协作基础

> **主题**: AI 更聪明，协作开始落地

### 自然语言交互
- [x] **追问与上下文链** — Agent 输出后自动生成 3 个推荐追问，用户点击即发送
- [ ] **分析意图消歧 v2** — 对复杂查询拆解为子任务列表，用户确认后按序执行
- [ ] **自动记忆提取增强** — pipeline 完成后自动调用 `extract_facts_from_conversation()` + 弹出确认

### 用户自扩展
- [x] **版本管理** — Skills/Tools 新增 `version` 字段，更新时自动 +1，保留最近 10 个版本，支持回滚
- [ ] **标签分类** — Skills/Tools 新增 `category`/`tags[]` 字段
- [ ] **使用统计** — Skills/Tools 增加 `use_count` + 调用日志，前端 Marketplace 显示热度排行

### DRL 优化
- [ ] **多场景环境引擎** — 重构 `LandUseOptEnv` 支持配置驱动：任意 N 种地类、自定义转换规则、自定义奖励公式
- [ ] **约束建模** — 新增硬约束（保留率下限）+ 软约束（预算/面积上限），Gymnasium action mask 扩展
- [ ] **结果对比面板** — 前端支持 A/B 对比两次优化结果（差异热力图 + 指标表格）

### 三面板 SPA
- [ ] **3D basemap 同步** — Map3DView 读取 2D 选择的 basemap，MapLibre style 动态切换
- [ ] **标注协同** — WebSocket 实时推送标注变更 + 在线用户光标显示
- [x] **GeoJSON 编辑器** — DataPanel 新增 tab/modal，支持粘贴/编辑 GeoJSON + 预览到地图
- [ ] **跨图层关联** — 选中 A 图层要素时高亮 B 图层空间关联要素

### 多 Agent 编排
- [x] **Agent 注册中心** — 新增 `agent_registry.py`：注册/发现/心跳，Redis 或 PostgreSQL 后端
- [x] **A2A 双向 RPC** — 扩展 `a2a_server.py` 支持主动调用远程 Agent
- [ ] **消息总线持久化** — `AgentMessageBus` 升级为 PostgreSQL 持久化 + 投递确认

---

## 已完成 (v14.2) — 深度智能 + 生产就绪

> **主题**: DRL 专业化，系统可投产

### 自然语言交互
- [x] **多轮分析工作流** — 支持"分析链"：用户定义条件触发后续分析
- [ ] **语音输入** — 集成语音转文字（Whisper API 或浏览器 SpeechRecognition）

### 用户自扩展
- [ ] **Skill Marketplace 社区** — 公开 Gallery（匿名浏览）、Skill 详情页（README）、一键安装
- [x] **审批工作流** — 管理员审核 is_shared Skill 的发布请求

### DRL 优化
- [ ] **自定义训练 API** — 暴露 `train_drl_model(data_path, scenario, epochs, reward_config)` 工具
- [ ] **可解释性模块** — SHAP / 特征重要性 → 每个地块转换附带"为什么"说明
- [ ] **时序动画** — 优化过程 200 步回放动画（逐步地块转换 GIF/MP4）

### 三面板 SPA
- [ ] **要素绘制编辑** — Leaflet.Draw 集成：绘制点/线/面 → 保存为 GeoJSON → 可作为分析输入
- [x] **标注导出** — 标注集导出为 GeoJSON / CSV
- [ ] **自适应布局** — 移动端响应式（Chat 全屏 ↔ 地图全屏切换）

### 多 Agent 编排
- [ ] **分布式任务队列** — TaskQueue 升级为 Celery + Redis，支持跨进程/跨机器调度
- [ ] **Pipeline 断点恢复 v2** — 进程崩溃后从 DB checkpoint 自动恢复未完成 DAG
- [x] **Circuit Breaker** — 工具/Agent 连续失败时熔断，自动降级到备选 Agent

---

## 已完成 (v14.3) — 联邦多 Agent + 生态开放

> **主题**: 从单机走向分布式，从工具走向平台

### 自然语言交互
- [ ] **个性化模型微调** — 根据用户历史分析偏好微调 Agent 行为（LoRA adapter on Gemini）
- [x] **多语言支持** — 英文/日文 prompt 自动检测 + 路由到对应语言 Agent

### 用户自扩展
- [~] **Skill 依赖图** — 允许 Skill A 依赖 Skill B（DAG 编排），类似 npm 包依赖 *(schema only, 图遍历待实现)*
- [x] **Webhook 集成** — 第三方平台 Skill 注册（GitHub Action、Zapier trigger）
- [ ] **Skill SDK** — 发布 `gis-skill-sdk` Python 包，外部开发者可独立开发 Skill

### DRL 优化
- [x] **多目标优化 v2** — NSGA-II 替代加权和方法，真 Pareto 前沿搜索
- [ ] **交通网络/设施布局场景** — 新增 2 个 Gymnasium 环境（路网优化、公共设施选址）
- [ ] **联邦学习** — 多租户共享模型权重但不共享数据（隐私保护 DRL）

### 三面板 SPA
- [ ] **协同工作空间** — 多用户同时编辑同一项目（CRDT 冲突解决）
- [x] **插件系统** — 允许用户开发自定义 DataPanel tab 插件
- [ ] **离线模式** — Service Worker 缓存基础地图 + 已下载数据集

### 多 Agent 编排
- [x] **完整 A2A 协议** — 实现 Google A2A spec：Agent Card、Task lifecycle、Streaming、Push Notification
- [x] **跨实例 Agent 协作** — Agent A (本机) 调用 Agent B (远程) 的工具，结果回传
- [ ] **Agent 联邦** — 多个 GIS Data Agent 实例组成联邦，共享 Skill 注册表 + 负载均衡

---

## v14.4 — 治理深化 + 交互式可视化 (进行中)

> **主题**: 治理管道从 40% → 65%，非 GIS 数据的交互式图表从 0 → 可用
>
> **依据**: `docs/governance-capability-assessment.md` (6 领域 22 子能力评估)、`docs/data-source-connector-assessment.md` (5 通道缺口分析)、dv.gaozhijun.me (数据可视化参考)

### 数据治理管道强化
- [x] **Ch21 审计修复** — P0/P1/P2 全部清零 (A2A 认证、SQL 参数化、线程安全 6 处) ✅ 2026-03-21
- [x] **DataPanel 拆分重构** — 2922 行 → 17 模块化组件 + 分组 Tab (数据/智能/运维/编排) ✅ 2026-03-21
- [ ] **GovernanceToolset (7 工具)** — `check_gaps` / `check_completeness` / `check_attribute_range` / `check_duplicates` / `check_crs_consistency` / `governance_score` / `governance_summary`，对标评估 §3 数据质量 6 项子能力
- [ ] **治理评分体系** — 6 维加权评分 (拓扑 25% / 间隙 15% / 完整性 20% / 属性 15% / 重复 10% / CRS 15%)，输出 0-100 综合分 + 雷达图 JSON
- [ ] **治理 Prompt 独立化** — 新建 `prompts/governance.yaml` 解耦 4 个治理专用 prompt，从 `optimization.yaml` / `general.yaml` 中迁出
- [ ] **GovernanceViz Agent** — 治理管道新增第 4 阶段：审计结果可视化 (问题分布图 + 质量雷达图 + 合规热力图)

### 交互式数据可视化
- [ ] **ChartToolset (9 工具)** — `create_bar_chart` / `create_line_chart` / `create_pie_chart` / `create_scatter_chart` / `create_histogram` / `create_box_plot` / `create_heatmap_chart` / `create_treemap` / `create_radar_chart`，输出 ECharts JSON config
- [ ] **前端 ECharts 集成** — `echarts` + `echarts-for-react`，ChartView 通用渲染组件 + DataPanel 图表 Tab
- [ ] **图表交付管道** — `/api/chart/pending` REST 端点 + `app.py` 图表检测 + ChatPanel 内联渲染
- [ ] **Prompt 图表感知** — `general_viz_instruction` 增加非地图可视化指引，Agent 自动选择地图 vs 图表

### 质量保障
- [ ] **治理工具测试** — `test_governance_tools.py`，7 工具 mock 测试 + 评分逻辑验证
- [ ] **图表工具测试** — `test_chart_tools.py`，9 工具 ECharts option schema 验证

---

## v14.5 — 可观测性 + 数据源增强 + 交互打磨 (规划中)

> **主题**: Agent 从黑盒走向白盒，数据接入补齐短板，交互体验收尾
>
> **依据**: `docs/agent-observability-enhancement.md` (Phase 1 指标增强)、`docs/data-source-connector-assessment.md` (S1 阶段)、治理评估剩余 P0 项

### Agent 可观测性 Phase 1 (对标可观测性文档 §3.2)
- [ ] **Prometheus 指标扩展 (4→25+)** — LLM 调用延迟/Token 直方图、工具延迟直方图、缓存命中率、队列深度、熔断器状态
- [ ] **ObservabilityPlugin** — 统一 6 层 ADK 回调 (before/after agent + model + tool)，替代分散的 callback 注册
- [ ] **HTTP 可观测性中间件** — `ObservabilityMiddleware` 为 124 个 REST 端点添加延迟/QPS/错误率指标
- [ ] **缓存命中率指标** — `semantic_layer.py` / `memory.py` / `data_catalog.py` 增加 hit/miss Counter
- [ ] **Grafana Dashboard 模板** — JSON 模板：Pipeline 概览、LLM Token 消耗、工具延迟 Top 10、熔断器状态

### 数据接入增强 (对标数据源评估 S1)
- [ ] **WMS/WMTS 连接器** — `virtual_sources.py` 新增 source_type，前端 MapPanel Leaflet 图层叠加
- [ ] **ArcGIS REST FeatureServer 连接器** — JSON→GeoJSON 自动转换，支持政企 ArcGIS Server
- [ ] **数据源注册向导** — 前端分步引导：选类型 → 填连接 → 测试 → 映射字段 → 预览 → 保存
- [ ] **字段映射可视化编辑器** — 源字段 ↔ 目标字段拖拽映射 (前端组件)

### 治理能力补齐 (对标治理评估 P0)
- [ ] **质量规则库 CRUD** — 用户自定义规则/阈值/关联字段，DB 持久化 + REST API (对标评估 P0-3)
- [ ] **定时质量巡检** — Workflow Engine Cron 触发质量检查 → 结果写入趋势表 (对标评估 P0-4)
- [ ] **质量趋势仪表盘** — DataPanel "运维" 组新增趋势图 Tab，ECharts 折线图展示评分变化

### 交互体验打磨
- [ ] **参数调整重跑** — pipeline 完成后显示"调整参数"按钮，提取上次参数 → 编辑表单 → 重跑
- [ ] **记忆搜索面板** — ChatPanel `/recall` 命令，调用 `search_memory()` 展示历史分析
- [ ] **3D basemap 同步** — Map3DView 读取 2D 底图选择，MapLibre style 动态切换
- [ ] **要素绘制编辑** — Leaflet.Draw 集成：绘制点/线/面 → GeoJSON → 分析输入

### 多 Agent 编排
- [ ] **Workflow 断点续跑** — DAG 节点输出持久化到 DB，`resume_workflow_dag(run_id, from_node)`
- [ ] **步骤级重试** — 失败节点单独重试，不重跑整个 workflow

---

## v15.0 — 深度可观测 + 数据安全 + 连接器插件化 (远期规划)

> **主题**: OpenTelemetry 分布式追踪、Agent 决策透明化、安全合规、连接器架构升级
>
> **依据**: 可观测性文档 Phase 2-4 + 治理评估 §4 数据安全 + 数据源评估 S2 + Spark 架构文档

### Agent 可观测性 Phase 2-4 (对标可观测性文档 §3.3-§7)
- [ ] **OpenTelemetry 分布式追踪** — `otel_tracing.py`：Pipeline/Agent/Tool 三级嵌套 Span，Jaeger/Tempo 集成
- [ ] **Agent 决策追踪** — `agent_decision_tracer.py`：工具选择理由、拒绝路径、质量门判定，Mermaid 序列图生成
- [ ] **Pipeline 执行瀑布图** — 前端 AgentObservabilityTab：各 Agent 耗时甘特图 + Token 分布 + 决策路径
- [ ] **Agent 质量评估** — `quality_monitor.py`：10% 抽样 LLM 评分（忠实度/相关性/完整性），异步不阻塞主流程
- [ ] **实时 Agent 行为 SSE 流** — `/api/observability/realtime/stream` 推送当前执行事件
- [ ] **Prometheus Alert 规则** — Pipeline 慢执行、LLM 高延迟、工具错误率、熔断器、Token 消耗异常 7 条告警

### 数据安全 (对标评估 §4)
- [ ] **数据分类分级引擎** — NLP + 正则识别敏感字段 (身份证/电话/地址)，五级分类标签体系
- [ ] **数据脱敏工具** — 字段级策略 (掩码/泛化/加密/截断)，静态 + 查询时动态脱敏
- [ ] **RLS 实际落地** — 为核心表创建 PostgreSQL Row-Level Security 策略
- [ ] **列级血缘** — `source_assets` 增加字段映射，追踪列来源和转换

### 连接器插件化 (对标数据源评估 S2)
- [ ] **BaseConnector 抽象基类** — `connectors/base.py` + ConnectorRegistry 注册表
- [ ] **现有 4 种 source_type 重构** — 从 if-elif 分支迁移为 Connector 子类
- [ ] **DatabaseConnector** — 用户注册外部数据库 (MySQL/PostgreSQL/SQLite)，连接池隔离 + 只读强制
- [ ] **ObjectStorageConnector** — S3/OSS/OBS 直接拉取 GeoParquet/GeoJSON
- [ ] **增量同步引擎** — 时间戳/ETag 变更检测 + upsert/append 合并策略

### 分布式计算 (对标 Spark 架构文档)
- [ ] **SparkToolset 接口预留** — Long-Running FunctionResponse 模式，submit → callback 回注
- [ ] **SparkGateway 网关** — 多后端抽象 (本地 PySpark / Livy / Dataproc / EMR)
- [ ] **三层执行路由** — L1 即时(<100MB) / L2 队列(100MB-1GB) / L3 分布式(>1GB) 自动切换

---

## 持续强化 — 差异化优势

> 数据层补课的同时，继续拉大智能层和交互层的领先距离

| 方向 | 规划 |
|------|------|
| **自然语言交互** | 多轮对话上下文记忆、分析意图消歧、结果追问与参数调整 |
| **用户自扩展** | Skill Marketplace（社区共享）、User Tool 版本管理、Workflow 模板市场 |
| **DRL 优化** | 多目标优化（碳汇+经济+生态）、更多场景（交通网络、设施布局） |
| **三面板 SPA** | 3D 地图增强（deck.gl 更多图层类型）、DataPanel 数据探索交互、协同标注 |
| **多 Agent 编排** | A2A 协议支持、跨实例 Agent 协作、Pipeline 断点续跑 |

---

## 标杆对标进度

| 标杆能力 | 来源 | v14.3 | v14.4 目标 | v14.5 目标 | v15.0 目标 |
|----------|------|-------|-----------|-----------|-----------|
| 空间数据虚拟化 | SeerAI | 🟢 | 🟢 | 🟢 WMS/ArcGIS | 🟢🟢 插件化 |
| 知识图谱语义发现 | SeerAI | 🟢 | 🟢 | 🟢 | 🟢 |
| 分析血缘自动追踪 | SeerAI | 🟢 | 🟢 | 🟢 | 🟢🟢 列级血缘 |
| MCP Server 暴露 | SeerAI | 🟢 | 🟢 | 🟢 | 🟢 |
| 行业预置模板 | SeerAI | 🟢 | 🟢 | 🟢 | 🟢 |
| Agent 对话交互 | OpenClaw | 🟢🟢🟢 | 🟢🟢🟢 | 🟢🟢🟢 参数重跑 | 🟢🟢🟢 |
| 企业级治理 | Frontier | 🟢 | 🟢🟢 评分+可视化 | 🟢🟢 规则库+巡检 | 🟢🟢🟢 安全+脱敏 |
| 数据可视化 | — | 🟡 仅地图 | 🟢 ECharts 9 图表 | 🟢 趋势仪表盘 | 🟢🟢 |
| **Agent 可观测性** | — | 🟡 4指标+日志 | 🟡 | 🟢 25+指标+中间件 | 🟢🟢 OTel+决策追踪+质量评估 |
| 多 Agent 协作 | CoWork | 🟢 | 🟢 | 🟢🟢 断点+重试 | 🟢🟢 Spark 分布式 |
| 用户生态 | — | 🟢 | 🟢 | 🟢 向导+映射 | 🟢🟢 插件化连接器 |
| DRL 优化深度 | — | 🟢 | 🟢 | 🟢 | 🟢 |

### 治理能力评估对标 (《智能化数据治理能力要求》22 项)

| 领域 | v14.3 | v14.4 目标 | v14.5 目标 | v15.0 目标 |
|------|-------|-----------|-----------|-----------|
| 数据标准 | 35% | 50% | 55% | 65% |
| 数据模型 | 5% | 5% | 10% | 25% |
| 数据质量 | 55% | 75% | 85% | 90% |
| 数据安全 | 25% | 25% | 30% | 60% |
| 元数据 | 70% | 70% | 75% | 85% |
| 数据资源 | 55% | 65% | 70% | 80% |
| **综合** | **~40%** | **~48%** | **~54%** | **~68%** |
