# GIS Data Agent — Roadmap

**Last updated**: 2026-03-19 &nbsp;|&nbsp; **Current version**: v12.0 &nbsp;|&nbsp; **ADK**: v1.27.2

> 参照标杆：SeerAI Geodesic（地理空间数据编排）、OpenClaw（Agent 交互）、Frontier（企业治理）、CoWork（多 Agent 协作）
>
> 核心战略：**智能层 + 交互层保持领先，数据层向 SeerAI 看齐**——从"用户带数据来"转向"Agent 主动发现和连接数据"

---

## 已完成 (v12.0)

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
- [x] S-4 API 拆分 (部分) — api/helpers + bundle_routes + kb_routes
- [x] 启动缺表修复 — workflow_templates + skill_bundles 表初始化

---

## v12.1 — 血缘追踪 + 行业模板 (1-2 周)

> 低投入快速见效，利用现有基础设施补齐可追溯性短板

- [ ] **BP-3 分析血缘自动记录** — 管线执行时自动将步骤写入 knowledge_graph（新增 `derives_from` / `feeds_into` 边类型），从 ADK agent `output_key` 链提取血缘
- [ ] **血缘可视化** — DataPanel Catalog tab 渲染血缘链（lineage 字段已有，需前端 DAG 渲染）
- [ ] **BP-5 行业分析模板 (首批)** — 基于现有 18 Skills + Workflow 引擎，按场景组织 2-3 个端到端模板：城市规划（热岛效应/设施选址）、环境监测（植被变化/水体提取）、国土资源（用地优化）
- [ ] **CapabilitiesView 行业分类** — 模板按行业场景分组浏览，一键导入为 Workflow
- [ ] S-4 API 拆分 (续) — 剩余路由模块化提取

---

## v12.2 — 语义数据发现 (2-3 周)

> 核心转变：Agent 从"等用户上传"到"主动搜索数据目录"（参照 SeerAI 知识图谱语义层）

- [ ] **BP-2 数据资产入图** — knowledge_graph.py 新增数据资产节点类型（当前仅地理实体），建立资产↔实体↔分析工作流的语义关系网络
- [ ] **向量嵌入搜索** — 为数据资产生成 Gemini embedding，`search_data_assets` 工具增加向量相似度搜索（当前仅 n-gram 文本匹配）
- [ ] **Planner 数据发现优先** — 优化 Planner prompt：收到分析请求时先搜索数据目录，找到相关数据集后确认再执行，而非直接要求用户上传
- [ ] **语义层增强** — semantic_layer.py 增加业务度量定义能力（如"植被覆盖率 = NDVI > 0.3 面积占比"），支持自然语言→度量映射

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
| 知识图谱语义发现 | SeerAI | 🟡 基础已有 | v12.2 |
| 分析血缘自动追踪 | SeerAI | 🟡 字段已有 | v12.1 |
| MCP Server 暴露 | SeerAI | 🔴 未开始 | v13.1 |
| 行业预置模板 | SeerAI | 🟡 基础设施就绪 | v12.1 |
| Agent 对话交互 | OpenClaw | 🟢 已领先 | 持续 |
| 企业级治理 | Frontier | 🟡 RBAC+审计已有 | 持续 |
| 多 Agent 协作 | CoWork | 🟢 DAG 编排已有 | 持续 |
