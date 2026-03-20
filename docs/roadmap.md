# GIS Data Agent — Roadmap

**Last updated**: 2026-03-20 &nbsp;|&nbsp; **Current version**: v14.3 &nbsp;|&nbsp; **ADK**: v1.27.2

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
- [ ] **意图消歧对话** — AMBIGUOUS 分类时弹出选择卡片（Optimization/Governance/General），用户点选后路由
- [ ] **参数调整重跑** — pipeline 完成后显示"调整参数"按钮，提取上次参数 → 编辑表单 → 重新执行
- [ ] **记忆搜索面板** — ChatPanel 增加 `/recall` 命令或搜索图标，调用 `search_memory()` 展示历史分析

### 用户自扩展
- [ ] **Marketplace 画廊** — DataPanel 新增"市场"tab，聚合所有 is_shared=true 的 Skills/Tools/Templates/Bundles，支持排序（评分/使用量/时间）
- [ ] **统一评分系统** — Skills 和 Tools 增加 `rating_sum`/`rating_count` 字段 + REST 端点 `POST /api/skills/{id}/rate`、`POST /api/user-tools/{id}/rate`
- [ ] **Skill/Tool Clone** — 允许用户克隆他人共享的 Skill/Tool 到自己名下

### DRL 优化
- [ ] **场景模板系统** — 定义 `DRLScenario` 配置类，内置 3 个场景模板：耕地优化（现有）、城市绿地布局、设施选址
- [ ] **奖励权重 UI** — 前端可调 slope_weight / contiguity_weight / balance_weight 滑块 → 传入 pipeline

### 三面板 SPA
- [ ] **热力图支持** — 集成 deck.gl `HeatmapLayer` 到 Map3DView，MapPanel 增加 `type: heatmap` 处理
- [ ] **测量工具** — MapPanel 工具栏增加距离测量 + 面积测量（Leaflet.Draw 或 Turf.js）
- [ ] **3D 图层控制** — Map3DView 增加图层列表面板，支持 show/hide/opacity 调节

### 多 Agent 编排
- [ ] **Workflow 断点续跑** — DAG 执行时每个 node 输出持久化到 DB，新增 `resume_workflow_dag(run_id, from_node)`
- [ ] **步骤级重试** — DAG 失败节点可单独重试（不重跑整个 workflow）

---

## 已完成 (v14.1) — 智能深化 + 协作基础

> **主题**: AI 更聪明，协作开始落地

### 自然语言交互
- [ ] **追问与上下文链** — Agent 输出后自动生成 3 个推荐追问，用户点击即发送
- [ ] **分析意图消歧 v2** — 对复杂查询拆解为子任务列表，用户确认后按序执行
- [ ] **自动记忆提取增强** — pipeline 完成后自动调用 `extract_facts_from_conversation()` + 弹出确认

### 用户自扩展
- [ ] **版本管理** — Skills/Tools 新增 `version` 字段，更新时自动 +1，保留最近 10 个版本，支持回滚
- [ ] **标签分类** — Skills/Tools 新增 `category`/`tags[]` 字段
- [ ] **使用统计** — Skills/Tools 增加 `use_count` + 调用日志，前端 Marketplace 显示热度排行

### DRL 优化
- [ ] **多场景环境引擎** — 重构 `LandUseOptEnv` 支持配置驱动：任意 N 种地类、自定义转换规则、自定义奖励公式
- [ ] **约束建模** — 新增硬约束（保留率下限）+ 软约束（预算/面积上限），Gymnasium action mask 扩展
- [ ] **结果对比面板** — 前端支持 A/B 对比两次优化结果（差异热力图 + 指标表格）

### 三面板 SPA
- [ ] **3D basemap 同步** — Map3DView 读取 2D 选择的 basemap，MapLibre style 动态切换
- [ ] **标注协同** — WebSocket 实时推送标注变更 + 在线用户光标显示
- [ ] **GeoJSON 编辑器** — DataPanel 新增 tab/modal，支持粘贴/编辑 GeoJSON + 预览到地图
- [ ] **跨图层关联** — 选中 A 图层要素时高亮 B 图层空间关联要素

### 多 Agent 编排
- [ ] **Agent 注册中心** — 新增 `agent_registry.py`：注册/发现/心跳，Redis 或 PostgreSQL 后端
- [ ] **A2A 双向 RPC** — 扩展 `a2a_server.py` 支持主动调用远程 Agent
- [ ] **消息总线持久化** — `AgentMessageBus` 升级为 PostgreSQL 持久化 + 投递确认

---

## 已完成 (v14.2) — 深度智能 + 生产就绪

> **主题**: DRL 专业化，系统可投产

### 自然语言交互
- [ ] **多轮分析工作流** — 支持"分析链"：用户定义条件触发后续分析
- [ ] **语音输入** — 集成语音转文字（Whisper API 或浏览器 SpeechRecognition）

### 用户自扩展
- [ ] **Skill Marketplace 社区** — 公开 Gallery（匿名浏览）、Skill 详情页（README）、一键安装
- [ ] **审批工作流** — 管理员审核 is_shared Skill 的发布请求

### DRL 优化
- [ ] **自定义训练 API** — 暴露 `train_drl_model(data_path, scenario, epochs, reward_config)` 工具
- [ ] **可解释性模块** — SHAP / 特征重要性 → 每个地块转换附带"为什么"说明
- [ ] **时序动画** — 优化过程 200 步回放动画（逐步地块转换 GIF/MP4）

### 三面板 SPA
- [ ] **要素绘制编辑** — Leaflet.Draw 集成：绘制点/线/面 → 保存为 GeoJSON → 可作为分析输入
- [ ] **标注导出** — 标注集导出为 GeoJSON / CSV
- [ ] **自适应布局** — 移动端响应式（Chat 全屏 ↔ 地图全屏切换）

### 多 Agent 编排
- [ ] **分布式任务队列** — TaskQueue 升级为 Celery + Redis，支持跨进程/跨机器调度
- [ ] **Pipeline 断点恢复 v2** — 进程崩溃后从 DB checkpoint 自动恢复未完成 DAG
- [ ] **Circuit Breaker** — 工具/Agent 连续失败时熔断，自动降级到备选 Agent

---

## 已完成 (v14.3) — 联邦多 Agent + 生态开放

> **主题**: 从单机走向分布式，从工具走向平台

### 自然语言交互
- [ ] **个性化模型微调** — 根据用户历史分析偏好微调 Agent 行为（LoRA adapter on Gemini）
- [ ] **多语言支持** — 英文/日文 prompt 自动检测 + 路由到对应语言 Agent

### 用户自扩展
- [ ] **Skill 依赖图** — 允许 Skill A 依赖 Skill B（DAG 编排），类似 npm 包依赖
- [ ] **Webhook 集成** — 第三方平台 Skill 注册（GitHub Action、Zapier trigger）
- [ ] **Skill SDK** — 发布 `gis-skill-sdk` Python 包，外部开发者可独立开发 Skill

### DRL 优化
- [ ] **多目标优化 v2** — NSGA-II 替代加权和方法，真 Pareto 前沿搜索
- [ ] **交通网络/设施布局场景** — 新增 2 个 Gymnasium 环境（路网优化、公共设施选址）
- [ ] **联邦学习** — 多租户共享模型权重但不共享数据（隐私保护 DRL）

### 三面板 SPA
- [ ] **协同工作空间** — 多用户同时编辑同一项目（CRDT 冲突解决）
- [ ] **插件系统** — 允许用户开发自定义 DataPanel tab 插件
- [ ] **离线模式** — Service Worker 缓存基础地图 + 已下载数据集

### 多 Agent 编排
- [ ] **完整 A2A 协议** — 实现 Google A2A spec：Agent Card、Task lifecycle、Streaming、Push Notification
- [ ] **跨实例 Agent 协作** — Agent A (本机) 调用 Agent B (远程) 的工具，结果回传
- [ ] **Agent 联邦** — 多个 GIS Data Agent 实例组成联邦，共享 Skill 注册表 + 负载均衡

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

| 标杆能力 | 来源 | 当前状态 | v14.0 后 | v14.3 后 |
|----------|------|---------|---------|---------|
| 空间数据虚拟化 | SeerAI | 🟢 已完成 | 🟢 | 🟢 |
| 知识图谱语义发现 | SeerAI | 🟢 已完成 | 🟢 | 🟢 |
| 分析血缘自动追踪 | SeerAI | 🟢 已完成 | 🟢 | 🟢 |
| MCP Server 暴露 | SeerAI | 🟢 v2.0 已完成 | 🟢 | 🟢 |
| 行业预置模板 | SeerAI | 🟢 已完成 | 🟢 | 🟢 |
| Agent 对话交互 | OpenClaw | 🟢 已领先 | 🟢🟢 显著领先 | 🟢🟢🟢 |
| 企业级治理 | Frontier | 🟡 RBAC+审计 | 🟡 | 🟢 审批+联邦 |
| 多 Agent 协作 | CoWork | 🟢 DAG 编排 | 🟡 断点续跑 | 🟢 完整 A2A+联邦 |
| 用户生态 | — | 🟡 共享标志 | 🟡 市场+评分 | 🟢 SDK+社区 |
| DRL 优化深度 | — | 🟡 单场景+Pareto | 🟡 多场景 | 🟢 训练API+NSGA-II |
