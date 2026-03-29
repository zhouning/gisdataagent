# GIS Data Agent — Roadmap

**Last updated**: 2026-03-29 &nbsp;|&nbsp; **Current version**: v15.8 &nbsp;|&nbsp; **ADK**: v1.27.2

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
- [x] **参数调整重跑** — rerun_with_params action + session 参数存储 ✅ v14.5
- [x] **记忆搜索面板** — MemorySearchTab + /api/memory/search ✅ v14.5

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
- [x] **Workflow 断点续跑** — resume_workflow_dag + /runs/{id}/resume ✅ v14.5
- [x] **步骤级重试** — retry_workflow_node + REST 端点 ✅ v14.5

---

## 已完成 (v14.1) — 智能深化 + 协作基础

> **主题**: AI 更聪明，协作开始落地

### 自然语言交互
- [x] **追问与上下文链** — Agent 输出后自动生成 3 个推荐追问，用户点击即发送
- [ ] **分析意图消歧 v2** — 对复杂查询拆解为子任务列表，用户确认后按序执行
- [ ] **自动记忆提取增强** — pipeline 完成后自动调用 `extract_facts_from_conversation()` + 弹出确认

### 用户自扩展
- [x] **版本管理** — Skills/Tools 新增 `version` 字段，更新时自动 +1，保留最近 10 个版本，支持回滚
- [x] **标签分类** — category + tags[] 列 + migration 035 ✅ v15.0
- [x] **使用统计** — use_count 列 + increment_skill_use_count ✅ v15.0

### DRL 优化
- [ ] **多场景环境引擎** — 重构 `LandUseOptEnv` 支持配置驱动：任意 N 种地类、自定义转换规则、自定义奖励公式
- [ ] **约束建模** — 新增硬约束（保留率下限）+ 软约束（预算/面积上限），Gymnasium action mask 扩展
- [ ] **结果对比面板** — 前端支持 A/B 对比两次优化结果（差异热力图 + 指标表格）

### 三面板 SPA
- [x] **3D basemap 同步** — Map3DView 高德/天地图 MapLibre 栅格源 ✅ v14.5
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
- [x] **要素绘制编辑** — Leaflet.Draw 点/线/面/矩形 + 导出 GeoJSON ✅ v14.5
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
- [ ] **字段映射可视化编辑器** — 源字段 ↔ 目标字段拖拽映射 (前端组件)

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
- [ ] **Generator/Reviewer 输出结构化校验** — Pydantic schema *(v16.0+)*

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
- [ ] **字段映射可视化编辑器** — 源↔目标字段拖拽映射 *(v14.5, 前端中等工作量)*
- [x] **MCP 外部 Agent 接入验证** — Claude Desktop / Cursor E2E 测试 *(v13.1)* ✅ v15.9

### 择机完成 (中等价值)
- [x] **分析意图消歧 v2** — 复杂查询拆解子任务列表 *(v14.1)* ✅ v15.9
- [x] **自动记忆提取增强** — pipeline 后 extract_facts + 弹窗确认 *(v14.1)* ✅ v15.9
- [x] **消息总线持久化** — AgentMessageBus → PostgreSQL *(v14.1)* ✅ v15.9
- [ ] **自适应布局** — 移动端响应式 *(v14.2)*
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

## v16.0+ — 遥感智能体能力增强 (远期规划)

> **主题**: 从"通用 GIS 分析平台"升级为"遥感领域专业智能体平台"
>
> **理论基础**: Tang et al. (2026) *Intelligent Remote Sensing Agents: A Survey*
>
> **详细方案**: 见 `docs/roadmap_v6.0_rs_agents.md`

### Phase 1 — 遥感核心能力 (v16.0)
- [ ] **光谱指数库** — 15+ 遥感指数 (EVI/SAVI/NDWI/NDBI/NBR 等) + 智能推荐
- [ ] **经验池 (Experience Pool)** — 成功分析经验记录 + RAG 检索 + 经验进化
- [ ] **数据质量门控** — 云覆盖检测 + 自动降级 (光学→SAR 切换)
- [ ] **卫星数据预置** — Sentinel-2/Landsat STAC 模板 + 3-5 预置源
- [ ] **新增 Skills** — spectral-analysis + satellite-imagery

### Phase 2 — 时空分析 (v17.0)
- [ ] **变化检测引擎** — 双时相差异 + 指数差异 + 分类后比较 + 语义描述
- [ ] **时间序列分析** — Mann-Kendall 趋势 + 断点检测 + 物候提取
- [ ] **证据充分性评估** — 数据覆盖度 × 方法多样性 × 结论支撑强度

### Phase 3 — 智能化可信度 (v18.0)
- [ ] **代码生成执行** — Agent 动态生成 Python + 沙箱执行
- [ ] **幻觉检测增强** — 空间约束 Fact-Checking + 多源交叉验证
- [ ] **多 Agent Debate** — 主分析 + 独立验证 + 统计检验 + Judge 汇总
- [ ] **RS 领域知识库** — 光谱特性 + 处理流程 + 分类体系 + 法规标准

### Phase 4 — 高级遥感 (v19.0+)
- [ ] **SAR/高光谱/LiDAR** 数据处理
- [ ] **深度学习推理** — segment-anything-geo / SatMAE / Prithvi
- [ ] **具身执行接口** — 卫星调度 / 无人机航线规划 (预留)

---

## 持续强化 — 差异化优势

> 数据层补课的同时，继续拉大智能层和交互层的领先距离

| 方向 | 规划 | v15.8 状态 |
|------|------|-----------|
| **因果推断** | 三角度体系 (统计+LLM+世界模型) | ✅ 14 工具全部交付 |
| **世界模型** | AlphaEarth JEPA + 因果干预/反事实 | ✅ 核心+因果扩展+Dreamer |
| **测绘质检** | GB/T 24356 全流程 + 4 子系统 | ✅ v15.7 全量交付 |
| **企业平台** | BCG 6 模块 (Prompt/Model/Context/Eval) | ✅ v15.8 全部交付 |
| **自然语言交互** | Inversion 采访、意图消歧、NL2SQL | ✅ NL2SQL 已交付，消歧 v2 待做 |
| **Skill 设计模式** | 5 模式覆盖 + 结构化输出校验 | ✅ 5 模式完成，Pydantic 校验待做 |
| **标准驱动治理** | 标准注册表、Gap Matrix、标准感知质检 | ✅ 全部完成 + QC 工作流模板 |
| **用户自扩展** | Marketplace 社区、Skill SDK | 🟡 基础完成，社区/SDK 冻结 |
| **DRL 优化** | 多目标优化、更多场景 | 🟡 NSGA-II + Dreamer 完成，新场景冻结 |
| **三面板 SPA** | 3D 增强、时间轴、因果推理 Tab | ✅ 时间轴+因果 Tab+QcMonitor+24 Tab |
| **数据生态** | 分发审批、热度统计 | ✅ 全部完成 + 统一资产表 |
| **多 Agent 编排** | 断点续跑、Spark 分布式 | ✅ 全部完成 + 非阻塞工作流 |
| **技术债务** | 6 项登记 (2P1 + 4P2) | ✅ 6/6 全部清零 |

---

## 标杆对标进度

| 标杆能力 | 来源 | v14.5 ✅ | v15.0 ✅ | v15.3 ✅ | v15.8 ✅ |
|----------|------|-----------|-----------|-----------|-----------|
| 空间数据虚拟化 | SeerAI | 🟢🟢 插件化+WMS+ArcGIS | 🟢🟢 DB+OBS 连接器 | 🟢🟢 | 🟢🟢 统一资产表 |
| 知识图谱语义发现 | SeerAI | 🟢 | 🟢 | 🟢 | 🟢 |
| 分析血缘自动追踪 | SeerAI | 🟢 批量探查+跨集关联 | 🟢🟢 列级血缘 | 🟢🟢 | 🟢🟢 4 层元数据 |
| MCP Server 暴露 | SeerAI | 🟢 | 🟢 | 🟢 | 🟢 |
| 行业预置模板 | SeerAI | 🟢🟢 标准注册表+DLTB | 🟢🟢 | 🟢🟢 | 🟢🟢🟢 QC 工作流模板 |
| Agent 对话交互 | OpenClaw | 🟢🟢🟢 Inversion 采访 | 🟢🟢🟢 | 🟢🟢🟢 + LLM 因果推理 | 🟢🟢🟢 |
| 企业级治理 | Frontier | 🟢🟢🟢 标准驱动+清洗+Gap | 🟢🟢🟢 安全+脱敏 | 🟢🟢🟢 | 🟢🟢🟢 QC+BCG 平台 |
| 数据可视化 | — | 🟢 趋势+总览仪表盘 | 🟢🟢 | 🟢🟢🟢 世界模型时间轴+因果效应图 | 🟢🟢🟢 |
| **Agent 可观测性** | — | 🟢 25+指标+中间件 | 🟢🟢 OTel+决策追踪 | 🟢🟢 | 🟢🟢🟢 Eval+Token 归因 |
| 多 Agent 协作 | CoWork | 🟢🟢 断点+重试 | 🟢🟢 Spark 分布式 | 🟢🟢 | 🟢🟢🟢 非阻塞+上下文连续 |
| 用户生态 | — | 🟢 图层发现+类型表单 | 🟢🟢 分发+反馈 | 🟢🟢 | 🟢🟢 |
| Skill 设计模式 | Skillmatic | 🟢 Inversion+Generator+Reviewer | 🟢🟢 Pipeline | 🟢🟢 | 🟢🟢 |
| 数据分发/反馈 | Frontier | 🟡 | 🟢 审批+热度+API 网关 | 🟢 | 🟢 |
| DRL 优化深度 | — | 🟢 | 🟢 | 🟢 | 🟢🟢 Dreamer 融合 |
| **时空预测** | — | — | 🟢 世界模型 Tech Preview | 🟢🟢🟢 JEPA+因果干预+反事实 | 🟢🟢🟢 |
| **因果推断** | — | — | — | 🟢🟢🟢 三角度 14 工具 + 82 测试 | 🟢🟢🟢 |
| **NL2SQL** | — | — | — | 🟢🟢 Schema-aware 动态查询 | 🟢🟢 |
| **测绘质检** | — | — | — | — | 🟢🟢🟢 GB/T 24356+4 子系统 |
| **企业平台** | BCG | — | — | — | 🟢🟢 6 模块 |

### 治理能力评估对标 (《智能化数据治理能力要求》22 项)

| 领域 | v14.5 ✅ | v15.0 ✅ | v15.3 ✅ | v15.8 ✅ |
|------|-----------|-----------|-----------|-----------|
| 数据标准 | 70% | 80% | 80% | 85% *(GB/T 24356 质检标准)* |
| 数据模型 | 20% | 35% | 40% *(因果 DAG 建模)* | 45% *(4 层元数据统一)* |
| 数据质量 | 90% | 95% | 95% | 98% *(QC 智能体+工作流)* |
| 数据安全 | 30% | 60% | 60% | 60% |
| 元数据 | 80% | 85% | 88% *(语义搜索+嵌入缓存)* | 92% *(统一资产表+4 层)* |
| 数据资源 | 80% | 85% | 88% *(世界模型+NL2SQL)* | 90% *(自动迁移+资产统一)* |
| **综合** | **~62%** | **~73%** | **~75%** | **~78%** |
