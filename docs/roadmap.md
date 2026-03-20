# GIS Data Agent — Roadmap

**Last updated**: 2026-03-19 &nbsp;|&nbsp; **Current version**: v12.2 &nbsp;|&nbsp; **ADK**: v1.27.2

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

---

## v13.0 — 虚拟数据层 (4-6 周)

> 最大差距项：从"9 个静态资产"到"按需连接多源数据"（参照 SeerAI Entanglement Engine）

- [ ] **BP-1 VirtualDataSource 注册表** — 新增虚拟数据源抽象层，支持 `postgis` / `wfs` / `stac` / `obs` / `api` 五种源类型，零复制按需查询
- [ ] **WFS/STAC 连接器** — 接入 OGC 标准服务（WFS 矢量、STAC 卫星影像目录），支持 bbox + CQL 空间过滤
- [ ] **查询时 CRS 自动对齐** — 虚拟层查询时自动检测并转换坐标系，替代工具函数中手动 `to_crs()`
- [ ] **Schema 自动映射** — 基于知识图谱语义模型，不同数据源字段名自动映射到统一语义（如 `lng`/`lon`/`longitude` → `geometry.x`）
- [ ] **连接器健康监控** — 虚拟数据源连接状态检测 + DataPanel 可视化

---

## v13.1 — MCP Server 暴露 (2-3 周)

> 让外部 Agent（Claude Desktop / GPT）通过 MCP 调用 GIS Data Agent 的分析能力（参照 SeerAI MCP Server 设计）

- [ ] **BP-4 GIS Data Agent 作为 MCP Server** — 新增 SSE 端点，暴露核心工具：`search_catalog`（语义搜索数据目录）、`query_postgis`（空间查询）、`run_pipeline`（执行分析管线）
- [ ] **元数据工具** — 增加 `get_lineage`（查询血缘链）、`list_skills`（列出可用技能）、`list_toolsets`（列出工具集）
- [ ] **外部 Agent 接入验证** — Claude Desktop / Cursor 通过 MCP 连接 GIS Data Agent 的端到端测试

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

| 标杆能力 | 来源 | 状态 | 目标版本 |
|----------|------|------|----------|
| 空间数据虚拟化 | SeerAI | 🔴 未开始 | v13.0 |
| 知识图谱语义发现 | SeerAI | 🟢 已完成 | v12.2 |
| 分析血缘自动追踪 | SeerAI | 🟢 已完成 | v12.1 |
| MCP Server 暴露 | SeerAI | 🔴 未开始 | v13.1 |
| 行业预置模板 | SeerAI | 🟢 已完成 | v12.1 |
| Agent 对话交互 | OpenClaw | 🟢 已领先 | 持续 |
| 企业级治理 | Frontier | 🟡 RBAC+审计已有 | 持续 |
| 多 Agent 协作 | CoWork | 🟢 DAG 编排已有 | 持续 |
