# Roadmap v6.0: 工程化智能体开放平台

> **Vision**: 从"AI 驱动的 GIS 分析平台"升级为"工程化、可扩展、可自主进化的空间智能开放平台"。
>
> **Philosophy**: "工具即生态，上下文即记忆，反思即质量，扩展即插件。"
>
> **理论基础**: 《Agentic Design Patterns》21 种模式 + Google/Kaggle 5-Day AI Agents 工程实践

---

## 当前状态 (v9.5 Baseline — 2026-03-14)

| 指标 | 数值 |
|------|------|
| 测试覆盖 | 1895 tests, 80 test files |
| 工具集 | 21 BaseToolset, 5 SkillBundle, 113+ 工具 |
| ADK Skills | 16 场景化领域技能 + DB 驱动自定义 Skills |
| REST API | 58 endpoints |
| 前端组件 | 10 React components (含 WorkflowEditor) |
| 管道 | 3 固定 + 1 动态规划器 (7 子智能体) + 自定义 Skills, 全部含反思循环 |
| ADK Agent 类型 | SequentialAgent + LoopAgent + ParallelAgent |
| 数据库表 | 24 (含 agent_custom_skills, agent_tool_failures, agent_conversation_memories) |
| 融合引擎 | fusion/ 包, 22 模块, 10 策略, PostGIS 下推 |
| 知识图谱 | ~625 行, 7 实体类型 |
| Plugins | 4 (CostGuard, GISToolRetry, Provenance, HITLApproval) |
| Guardrails | 4 (InputLength, SQLInjection, OutputSanitizer, Hallucination) |
| 跨会话记忆 | PostgreSQL 持久化 (BaseMemoryService) |
| Pipeline 可观测性 | 延迟/成功率/Token 效率/吞吐量/Agent 分布 |
| Streaming | 批量 + SSE 流式 |
| 部署方式 | Docker / K8s / 本地 |
| CI | GitHub Actions (test + frontend build + evaluation + route-eval) |

### Agentic Design Patterns 覆盖度 (v9.5)

| 模式 | 章节 | 实现状态 | 代码位置 |
|------|------|----------|----------|
| 提示链 (Prompt Chaining) | Ch1 | ✅ 完整 | 3 条 SequentialAgent 管道, `agent.py` |
| 路由 (Routing) | Ch2 | ✅ 完整 | Gemini 2.0 Flash `classify_intent()`, `app.py` |
| 并行化 (Parallelization) | Ch3 | ✅ 完整 | ParallelAgent 数据摄取 + 任务分解 (v9.0.2/9.0.4), `agent.py` |
| 反思 (Reflection) | Ch4 | ✅ 完整 | LoopAgent 全部 3 管道 (v7.1.6) |
| 工具使用 (Tool Use) | Ch5 | ✅ 完整 | 21 BaseToolset, 113+ FunctionTool, 16 ADK Skills, `toolsets/` + `skills/` |
| 规划 (Planning) | Ch6 | ✅ 完整 | TaskDecomposer DAG 分解 + 波次并行执行 (v9.0.4), `task_decomposer.py` |
| 多智能体协作 | Ch7 | ✅ 完整 | 层级 Planner + 7 子 Agent + transfer_to_agent |
| 记忆管理 (Memory) | Ch8 | ✅ 完整 | Memory ETL + PostgresMemoryService 跨会话持久化 (v9.0.3), `conversation_memory.py` |
| 学习与适应 | Ch9 | ✅ 完整 | 工具失败模式学习 + 历史提示注入 (v8.0.5), `failure_learning.py` |
| MCP 协议 | Ch10 | ✅ 完整 | 3 传输协议 + DB CRUD + 管理 UI + 安全加固, `mcp_hub.py` |
| 目标监控 | Ch11 | ✅ 完整 | ProgressTracker 按管道追踪完成百分比 (v9.0.6), `agent_hooks.py` |
| 异常恢复 (Recovery) | Ch12 | ✅ 完整 | 5 个高频工具含恢复建议 + GISToolRetryPlugin (v9.0.1) |
| HITL 人类参与 | Ch13 | ✅ 完整 | BasePlugin, 13 工具风险注册, `hitl_approval.py` |
| RAG 知识检索 | Ch14 | ⚠️ 部分 | 16 Skills 领域知识 + knowledge_agent (待: 私有知识库) |
| A2A 通信 | Ch15 | ❌ 未实现 | 单进程架构 |
| 资源感知 (Resource) | Ch16 | ✅ 完整 | 动态工具加载 + 动态模型选择 + CostGuardPlugin + LongRunningFunctionTool (v9.5.5) |
| 推理技术 | Ch17 | ❌ 未实现 | 无 Self-Consistency / ToT |
| 护栏与安全 | Ch18 | ✅ 完整 | RBAC + RLS + 审计 + 4 Guardrails (v9.5.3) + before_tool_callback |
| 评估与监控 | Ch19 | ✅ 完整 | 4 管道评估 + CI + Trace ID + 5 Analytics 端点 (v9.0.5) |
| 优先级排序 | Ch20 | ❌ 未实现 | 单请求单管道 |
| 探索与发现 | Ch21 | ❌ 未实现 | Agent 被动响应 |

**覆盖度: 16/21 (76%)**

---

## 已完成版本回顾

| 版本 | 功能集 | Tests | 状态 |
|------|--------|-------|------|
| v1.0–v3.2 | 基础 GIS、PostGIS、语义层、多管道架构 | — | ✅ |
| v4.0 | 前端三面板 SPA、可观测性、CI/CD、技能包、协作标注 | — | ✅ |
| v4.1 | 会话持久化、管道进度可视化、错误恢复、数据预览、i18n | — | ✅ |
| v5.1–v5.6 | MCP 市场、多模态输入、3D 可视化、工作流编排、融合引擎 | — | ✅ |
| v6.0 | 融合增强（栅格重投影、点云、流数据、语义增强） | — | ✅ |
| v7.0 | 向量嵌入匹配、LLM 策略路由、知识图谱、分布式计算 | — | ✅ |
| v7.1 | MCP 管理 UI、WorkflowEditor、分析视角、反思推广、Trace ID | — | ✅ |
| v7.5 | MCP 安全加固、Memory ETL、动态工具加载、16 场景化 Skills、Context Caching | 1530 | ✅ |
| v8.0 | 失败学习、动态模型选择、评估门控 CI、DB 自定义 Skills | 1735 | ✅ |
| v9.0 | Agent Plugins (4)、ParallelAgent、跨会话记忆、任务分解、Pipeline Analytics、Agent Hooks | 1859 | ✅ |
| v9.5 | conftest.py、LongRunningFunctionTool、Guardrails (4)、SSE Streaming、评估增强 | 1895 | ✅ |

---

## v9.0 — Intelligent Agent Collaboration ✅ 已完成

**目标**: 利用 ADK 高级能力 (ParallelAgent, BasePlugin, BaseMemoryService, agent callbacks)，让 Agent 系统更智能、可观测、可协作。

| Step | 功能 | 关键文件 |
|------|------|----------|
| 9.0.1 ✅ | Agent Plugins (CostGuard, GISToolRetry, Provenance) | `plugins.py`, `test_plugins.py` |
| 9.0.2 ✅ | 并行 Pipeline (ParallelAgent 数据摄取) | `agent.py`, `test_parallel_pipeline.py` |
| 9.0.3 ✅ | 跨会话对话记忆 (PostgresMemoryService) | `conversation_memory.py`, `test_conversation_memory.py` |
| 9.0.4 ✅ | 智能任务分解 (TaskGraph DAG) | `task_decomposer.py`, `test_task_decomposer.py` |
| 9.0.5 ✅ | Pipeline 分析仪表盘 (5 REST 端点) | `pipeline_analytics.py`, `test_pipeline_analytics.py` |
| 9.0.6 ✅ | Agent 生命周期钩子 (Prometheus + ProgressTracker) | `agent_hooks.py`, `test_agent_hooks.py` |

## v9.5 — Production Hardening ✅ 已完成

**目标**: 系统健壮性、可评估性、可流式、可测试性全面提升。

| Step | 功能 | 关键文件 |
|------|------|----------|
| 9.5.1 ✅ | 集中测试夹具 (conftest.py) | `conftest.py` |
| 9.5.2 ✅ | 评估框架 (已有 trajectory + rubric 评估) | `evals/`, `run_evaluation.py` |
| 9.5.3 ✅ | Agent Guardrails (4 个输入/输出护栏) | `guardrails.py`, `test_guardrails.py` |
| 9.5.4 ✅ | Headless SSE Streaming | `pipeline_runner.py`, `test_pipeline_streaming.py` |
| 9.5.5 ✅ | LongRunningFunctionTool for DRL | `toolsets/analysis_tools.py`, `test_analysis_agent.py` |

---

## v10.0 — 知识增强与工作流智能化 ⬅️ 下一阶段

**目标**: 补齐 RAG 私有知识库 (Ch14 完整)、DAG 工作流、高级分析，形成完整的知识驱动分析平台。
**周期**: 4-6 周
**补齐模式**: Ch14 RAG (完整)、Ch3 并行化 (DAG 工作流)

### 10.0.1 RAG 私有知识库

**现状**: Vertex AI Search 仅用于 optimization pipeline 的 knowledge_agent，16 Skills 提供领域知识但无用户自定义知识。
**方案**:
- 用户上传行业 PDF/文档 → 系统创建 RAG 知识库 (向量化存储)
- 知识库绑定到自定义 Skill 或全局可用
- 运行时动态挂载知识检索工具到 Agent
- 多租户隔离: 每用户/团队独立知识库
- 可与 `knowledge_graph.py` 结合实现 GraphRAG

**影响范围**: `rag_service.py`(新), `agent.py`, `frontend_api.py`, ~400 行

### 10.0.2 DAG 工作流引擎

**现状**: `workflow_engine.py` 为线性顺序执行器，`depends_on` 字段存在但未使用。
**方案**:
- 重构执行引擎: 顺序 → DAG 拓扑排序 (复用 `task_decomposer.py` 的 TaskGraph)
- 步骤间数据传递: 前步输出文件自动注入后步 prompt
- 条件分支节点: 基于工具输出的 if/else 判断
- 并行执行: 无依赖步骤用 ADK `ParallelAgent` 并发
- 前端 React Flow 编辑器增强: 条件节点、并行分支

**影响范围**: `workflow_engine.py`, `frontend/WorkflowEditor.tsx`, ~300 行

### 10.0.3 高级空间分析引擎

- 时空预测（GWR/GTWR，空间趋势预测）
- 场景模拟（Monte Carlo，空间溢出效应）
- 网络分析（等时圈、最优路径、设施覆盖）
- 新增 AdvancedAnalysisToolset

**影响范围**: `toolsets/advanced_analysis.py`(新), `agent.py`, ~300 行

### 10.0.4 用户自定义技能包组合

**现状**: `skill_bundles.py` 定义 5 个命名工具组合 + 16 ADK Skills，但用户无法自选组合。
**方案**:
- 新建 `agent_custom_bundles` 表（用户 ID + 选择的 bundle/skill 列表）
- 前端 SkillBuilder 面板: 从 16 个 ADK Skills 中勾选组合
- Planner Agent 根据用户配置动态调整可用技能集

**影响范围**: `skill_bundles.py`, `agent.py`, `frontend_api.py`, ~200 行

### 10.0.5 per-User MCP 服务器隔离

- 数据库中 MCP 配置增加 `created_by` 字段
- 全局服务器（admin 创建）对所有用户可见
- 用户私有服务器仅本人可见
- 工具发现按用户范围过滤

**影响范围**: `mcp_hub.py`, `frontend_api.py`, ~100 行

---

## v11.0 — 多 Agent 协同与互操作

**目标**: 从单用户工具进化为多用户协同决策平台，支持跨框架 Agent 互操作。
**周期**: 长期
**补齐模式**: Ch15 A2A、Ch17 推理技术、Ch20 优先级排序、Ch21 探索与发现

### 11.1 A2A 智能体互操作

> 来源: Google A2A 开放协议 + 《Agentic Design Patterns》Ch15

- 实现 A2A 协议的 Server 端（AgentCard 注册、Task 管理）
- 允许外部 Agent（气象、交通、人口）通过 A2A 接入
- Agent 发现: 注册中心 + AgentCard 服务描述

### 11.2 主动探索与发现 (Ch21)

- Agent 主动发现数据中的异常/趋势/空间模式
- 假设生成: "该区域耕地碎片化指数异常升高，可能与近年城市扩张相关"
- 用户可配置关注主题，Agent 定期扫描并推送洞察

### 11.3 多任务智能调度 (Ch20)

- 并发请求优先级排序
- 资源约束下的任务编排（token budget, API rate limit）
- 长任务拆分 + 中间结果缓存

### 11.4 高级推理技术 (Ch17)

- Self-Consistency: 多次采样取多数票
- Tree-of-Thought: 分支探索复杂分析路径
- 可配置推理深度（快速/标准/深度）

### 11.5 实时协同编辑

- 多用户同时查看同一地图
- CRDT 冲突解决（类 Figma 模式）
- WebRTC 语音/视频协同

### 11.6 边缘部署 + 离线模式

- ONNX Runtime 本地推理（无需 Gemini API）
- PWA 离线缓存
- 野外巡查: GPS + 拍照 + 本地分析 + 回连同步

---

## 设计模式覆盖演进图

```
模式覆盖度 (v7.5 → v9.5 → v11.0)

v7.5 已实现 (11/21):
  ✅ Ch1  提示链         ✅ Ch2  路由
  ✅ Ch4  反思           ✅ Ch5  工具使用
  ✅ Ch7  多智能体协作   ✅ Ch10 MCP
  ✅ Ch12 异常恢复       ✅ Ch13 HITL
  ✅ Ch18 护栏与安全     ✅ Ch19 评估与监控
  ✅ Ch8  记忆管理

v9.0 新增 (→ 14/21):
  ✅ Ch3  并行化         → ParallelAgent + TaskDecomposer
  ✅ Ch6  规划           → DAG 任务分解 + 波次并行执行
  ✅ Ch11 目标监控       → ProgressTracker + Prometheus Hooks

v9.5 增强 (→ 16/21):
  ✅ Ch9  学习与适应     → 失败学习 (v8.0) + GISToolRetryPlugin (v9.0)
  ✅ Ch16 资源感知       → 动态工具 + 动态模型 + CostGuard + LongRunning (完整)

v10.0 计划补齐:
  ⬆ Ch14 RAG            → 私有知识库 + GraphRAG (完整)

v11.0 计划补齐 (→ 21/21):
  ⬆ Ch15 A2A            → 跨框架智能体互操作
  ⬆ Ch17 推理技术       → Self-Consistency + ToT
  ⬆ Ch20 优先级排序     → 多任务智能调度
  ⬆ Ch21 探索与发现     → 主动数据洞察推送
```

---

## 五层架构全景

```
┌─────────────────────────────────────────────────────────┐
│             工程化智能体开放平台 (v9.5)                    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  第六层：生产就绪加固 (v9.5 ✅)                           │
│  ┌─────────────────────────────────────────────┐       │
│  │  Guardrails: 4 输入/输出护栏 (递归挂载)       │       │
│  │  LongRunning: DRL 异步执行防重复调用           │       │
│  │  SSE Streaming: 流式 pipeline 输出             │       │
│  │  conftest.py: 集中测试夹具 + 事件循环安全      │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
│  第五层：智能协作 (v9.0 ✅)                              │
│  ┌─────────────────────────────────────────────┐       │
│  │  ParallelAgent: 并行数据摄取                  │       │
│  │  Plugins: CostGuard + ToolRetry + Provenance  │       │
│  │  TaskDecomposer: DAG 任务分解 + 波次并行       │       │
│  │  PostgresMemoryService: 跨会话记忆持久化       │       │
│  │  Analytics: 5 REST 端点 + Agent Hooks          │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
│  第四层：Agent 工程化基线 (v7.5–v8.0 ✅)                │
│  ┌─────────────────────────────────────────────┐       │
│  │  Memory ETL + 动态工具加载 + MCP 安全加固      │       │
│  │  失败学习 + 动态模型选择 + 评估门控 CI         │       │
│  │  DB 驱动自定义 Skills + @mention 路由          │       │
│  │  Trace ID + 反思推广 + Context Cache           │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
│  第三层：多渠道交互 (v4.0–v8.5)                        │
│  ┌─────────────────────────────────────────────┐       │
│  │  Web UI: React 三面板 SPA (Chainlit)          │       │
│  │  REST: 58 API endpoints + SSE streaming       │       │
│  │  pipeline_runner.py: headless 执行层          │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
│  第二层：领域专家 Skills (v7.1–v8.0)                    │
│  ┌─────────────────────────────────────────────┐       │
│  │  16 场景化领域技能 + 6 参考文档               │       │
│  │  分析视角注入 + SkillBundle 工具组合           │       │
│  │  DB 驱动自定义 Agent + 工具集选择              │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
│  第一层：MCP + 工具生态 (v5.1–v7.5)                    │
│  ┌─────────────────────────────────────────────┐       │
│  │  21 工具集 · 113+ 工具 · 3 传输协议           │       │
│  │  MCP 管理 UI + CRUD + DB 持久化 + 安全加固    │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  基座：v9.5 能力                                         │
│  1895 tests · 58 API · 4 Plugins · 4 Guardrails        │
│  3+1 管道 · ParallelAgent · PostgresMemory             │
│  16/21 设计模式 · SSE Streaming · LongRunningTool       │
└─────────────────────────────────────────────────────────┘
```

---

## 推荐实施路线

```
Phase 1–4 (v1.0–v9.5) ✅ 已完成
  1895 tests | 58 REST API | 80 test files
  16/21 设计模式 | 4 Plugins | 4 Guardrails
  ParallelAgent | PostgresMemory | SSE Streaming

Phase 5 (v10.0, 4-6 周) — 知识增强 + 工作流智能化
  ├── 10.0.1 RAG 私有知识库 (向量化 + GraphRAG)
  ├── 10.0.2 DAG 工作流引擎 (拓扑排序 + 并行)
  ├── 10.0.3 高级空间分析 (GWR/Monte Carlo/网络)
  ├── 10.0.4 用户自定义技能包组合
  └── 10.0.5 per-User MCP 隔离

Phase 6 (v11.0, 持续迭代) — 协同 + 互操作 + 高级推理
  ├── 11.1 A2A 智能体互操作 (Ch15)
  ├── 11.2 主动探索与发现 (Ch21)
  ├── 11.3 多任务智能调度 (Ch20)
  ├── 11.4 高级推理技术 (Ch17)
  ├── 11.5 实时协同编辑 (CRDT)
  └── 11.6 边缘部署 + PWA 离线
```

---

## 竞品差异化分析

| 能力维度 | 本平台 (v9.5) | ArcGIS Pro | Julius AI | Carto |
|----------|---------------|------------|-----------|-------|
| NL 交互 | ★★★★★ | ★★☆☆☆ | ★★★★☆ | ★★☆☆☆ |
| GIS 深度 | ★★★★☆ | ★★★★★ | ★☆☆☆☆ | ★★★☆☆ |
| 多模态 | ★★★★☆ | ★★★☆☆ | ★★★☆☆ | ★☆☆☆☆ |
| Agent 工程化 | ★★★★★ (16/21 模式) | ★★☆☆☆ | ★★★☆☆ | ★☆☆☆☆ |
| 用户扩展性 | ★★★★★ (MCP+Skills+自定义) | ★★★☆☆ | ★☆☆☆☆ | ★★☆☆☆ |
| 可观测性 | ★★★★★ (Plugins+Hooks+Analytics) | ★★★☆☆ | ★★☆☆☆ | ★★☆☆☆ |
| 安全护栏 | ★★★★★ (4 Guardrails+RBAC+RLS) | ★★★★☆ | ★★☆☆☆ | ★★★☆☆ |
| 私有部署 | ★★★★★ | ★★★★☆ | ☆☆☆☆☆ | ★★☆☆☆ |
| 学习曲线 | 零 (NL) | 高 | 低 | 中 |

**核心壁垒**: "High GIS + High Agent Engineering (16/21) + Open Ecosystem (MCP) + Production Hardening (Guardrails+Plugins+Streaming)" 四位一体。

---

## 成功指标 (KPIs)

| 指标 | v7.5 | v9.0 | v9.5 实际 | v10.0 目标 |
|------|------|------|----------|------------|
| Tests | 1530 | 1859 | 1895 | 2100+ |
| REST API 端点 | 44 | 57 | 58 | 65+ |
| Test files | 66 | 74 | 80 | 85+ |
| Plugins | 1 | 4 | 4 | 5+ |
| Guardrails | 0 | 0 | 4 | 6+ |
| 设计模式覆盖 | 11/21 (52%) | 14/21 (67%) | 16/21 (76%) | 17/21 (81%) |
| ADK Agent 类型 | 2 | 3 | 3 | 3 |
| 跨会话记忆 | 无 | PostgreSQL | PostgreSQL | + RAG 向量化 |
| Streaming | 无 | 无 | SSE | SSE + WebSocket |
| Pipeline 可观测性 | Token 计数 | 5 Analytics 端点 | + Guardrails | + 告警 |

---

**方案版本**: v6.0
**更新日期**: 2026-03-14
**基于**: v9.5 代码验证 (1895 tests, 58 API, 16/21 设计模式)
