# Roadmap v9.0: 工程化智能体开放平台

> **Vision**: 从"AI 驱动的 GIS 分析平台"升级为"工程化、可扩展、可自主进化的空间智能开放平台"。
>
> **Philosophy**: "工具即生态，上下文即记忆，反思即质量，扩展即插件。"
>
> **理论基础**: 《Agentic Design Patterns》21 种模式 + Google/Kaggle 5-Day AI Agents 工程实践

---

## 当前状态 (v7.5 Baseline)

| 指标 | 数值 |
|------|------|
| 测试覆盖 | 1490+ tests, 62 test files |
| 工具集 | 19 BaseToolset, 5 SkillBundle, 113+ 工具 |
| ADK Skills | 16 场景化领域技能 + 6 深度参考文档 (v7.5.7) |
| REST API | 36 endpoints |
| 前端组件 | 10 React components (含 WorkflowEditor) |
| 管道 | 3 固定 + 1 动态规划器 (7 子智能体), 全部含反思循环 |
| 数据库表 | 20 (含 agent_mcp_servers) |
| 融合引擎 | fusion/ 包, 22 模块, 10 策略, PostGIS 下推 |
| 知识图谱 | ~625 行，7 实体类型 |
| 上下文工程 | Memory ETL 自动提取 + 动态工具加载 + MCP 安全加固 |
| 部署方式 | Docker / K8s / 本地 |
| CI | GitHub Actions (test + frontend build + evaluation) |

### Agentic Design Patterns 覆盖度 (v7.5)

| 模式 | 章节 | 实现状态 | 代码位置 |
|------|------|----------|----------|
| 提示链 (Prompt Chaining) | Ch1 | ✅ 完整 | 3 条 SequentialAgent 管道, `agent.py` |
| 路由 (Routing) | Ch2 | ✅ 完整 | Gemini 2.0 Flash `classify_intent()`, `app.py` |
| 反思 (Reflection) | Ch4 | ✅ 完整 | LoopAgent 全部 3 管道 (v7.1.6) |
| 工具使用 (Tool Use) | Ch5 | ✅ 完整 | 19 BaseToolset, 113+ FunctionTool, 16 ADK Skills, `toolsets/` + `skills/` |
| 多智能体协作 | Ch7 | ✅ 完整 | 层级 Planner + 7 子 Agent + transfer_to_agent |
| MCP 协议 | Ch10 | ✅ 完整 | 3 传输协议 + DB CRUD + 管理 UI + 安全加固 (v7.5.1), `mcp_hub.py` |
| 异常恢复 (Recovery) | Ch12 | ✅ 完整 | 5 个高频工具含恢复建议 (v7.1.5) |
| HITL 人类参与 | Ch13 | ✅ 完整 | BasePlugin, 13 工具风险注册, `hitl_approval.py` |
| 护栏与安全 | Ch18 | ✅ 完整 | RBAC + RLS + 审计 + before_tool_callback + MCP 安全加固 |
| 评估与监控 | Ch19 | ✅ 完整 | 4 管道评估 + CI + Trace ID (v7.1.7) |
| 记忆管理 (Memory) | Ch8 | ✅ 完整 | Memory ETL 自动提取 (v7.5.4) + 分析视角注入 + save_memory() |
| RAG 知识检索 | Ch14 | ⚠️ 部分 | Optimization 管道 knowledge_agent + 16 Skills 领域知识 (v7.5.7) |
| 资源感知 (Resource) | Ch16 | ⚠️ 部分 | 静态模型分层 + 动态工具加载 (v7.5.6)，非动态模型选择 |
| 规划 (Planning) | Ch6 | ⚠️ 部分 | Planner 选管道但不生成动态步骤 |
| 并行化 | Ch3 | ❌ 未实现 | 无 ParallelAgent，管道互斥 |
| 学习与适应 | Ch9 | ❌ 未实现 | 无失败模式学习 |
| 目标监控 | Ch11 | ❌ 未实现 | 无主动目标追踪 |
| A2A 通信 | Ch15 | ❌ 未实现 | 单进程架构 |
| 推理技术 | Ch17 | ❌ 未实现 | 无 Self-Consistency / ToT |
| 优先级排序 | Ch20 | ❌ 未实现 | 单请求单管道 |
| 探索与发现 | Ch21 | ❌ 未实现 | Agent 被动响应 |

---

## 已完成版本回顾

| 版本 | 功能集 | 状态 |
|------|--------|------|
| v1.0–v3.2 | 基础 GIS、PostGIS、语义层、多管道架构 | ✅ 完成 |
| v4.0 | 前端三面板 SPA、可观测性、CI/CD、技能包、协作标注 | ✅ 完成 |
| v4.1 | 会话持久化、管道进度可视化、错误恢复、数据预览、i18n | ✅ 完成 |
| v5.1 | MCP 工具市场（引擎 + 前端展示 + 管线过滤） | ✅ 完成 |
| v5.2 | 多模态输入（图片理解 + PDF 解析 + 语音输入） | ✅ 完成 |
| v5.3 | 3D 空间可视化（deck.gl + MapLibre + 2D/3D 切换） | ✅ 完成 |
| v5.4 | 工作流编排（引擎 + Cron + Webhook） | ✅ 完成 |
| v5.5 | 多模态数据融合引擎 MMFE（5 模态、10 策略、语义匹配） | ✅ 完成 |
| v5.6 | MGIM 启发增强（模糊匹配、单位转换、数据感知策略、多源编排） | ✅ 完成 |
| v6.0 | 融合增强（栅格重投影、点云、流数据、语义增强、质量验证） | ✅ 完成 |
| v7.0 | 向量嵌入匹配、LLM 策略路由、地理知识图谱、分布式计算 | ✅ 完成 |
| v7.1 | MCP 管理 UI、WorkflowEditor、分析视角、Prompt 版本、反思推广、Trace ID、错误恢复 | ✅ 完成 |
| v7.5 | MCP 安全加固、Memory ETL、动态工具加载、Skills 内容丰富化 (5→16 场景化领域技能) | ✅ 部分完成 |

---

## v7.5 — 上下文工程 + MCP 安全 ⬅️ 当前阶段 (4/7 已完成)

**目标**: 实现 Agent 上下文工程最佳实践，完善 MCP 自助化安全，提升 Agent 智能度。
**周期**: 3-4 周
**补齐模式**: Ch8 记忆管理 ✅、Ch14 RAG 增强 (部分)

### 7.5.1 MCP 服务器安全加固 ✅

**现状**: ~~MCP 管理 UI + DB CRUD 已完成 (v7.1)，但缺少安全校验。~~ 已完成安全加固。
**已实现** (commit `118aef4`):
- 配置输入校验（防止 stdio command 注入 — 白名单可执行文件路径）
- Auth token 加密存储（`pgp_sym_encrypt` 或 AES 加密列，非明文 JSON）
- 操作审计日志（谁添加/删除/toggle 了服务器，写入 `agent_audit_log`）
- 用户配额（每用户最多 N 个自定义服务器）
- 连接前自动测试（Test Connection 按钮 → 前端反馈连接结果）

**影响范围**: `mcp_hub.py`, `frontend_api.py`, `DataPanel.tsx`, ~120 行

### 7.5.2 用户自定义技能包组合

**现状**: `skill_bundles.py` 定义了 5 个命名工具组合 + 16 个 ADK Skills 提供领域知识，但用户无法自选组合。
**方案**:
- 新建 `agent_custom_bundles` 表（用户 ID + 选择的 bundle/skill 列表）
- 前端增加 SkillBuilder 面板：从 16 个 ADK Skills 中勾选组合
- Planner Agent 根据用户配置动态调整可用技能集

**影响范围**: `skill_bundles.py`, `agent.py`, `frontend_api.py`, `DataPanel.tsx`, 新迁移脚本

### 7.5.3 per-User MCP 服务器隔离

- 数据库中 MCP 配置增加 `created_by` 字段
- 全局服务器（admin 创建）对所有用户可见
- 用户私有服务器仅本人可见
- 工具发现按用户范围过滤

### 7.5.4 Memory ETL 自动提取 ✅

> 来源: Kaggle Day 3 "Context Engineering" — Memory ETL Pipeline: Extract → Consolidate → Store

**现状**: 记忆系统完全依赖 Agent 手动调用 `save_memory()` 工具。对话中产生的关键发现不会自动保存。
**方案**:
- 管道执行完成后，自动调用 LLM 提取会话关键事实
- 提取模板: "从以下对话中提取关键发现（数据特征、分析结论、用户偏好），返回 JSON 数组"
- 自动写入 `user_memories` 表 (`memory_type="auto_extract"`)
- 去重: 对比已有记忆的 key 值，新事实合并而非重复
- 用户可在 UserSettings 查看/删除自动记忆
- 配额: 每次会话最多提取 5 条，单用户最多 100 条自动记忆

**影响范围**: `app.py`, `memory.py`, `UserSettings.tsx`, ~100 行

### 7.5.5 Gemini Context Caching

> 来源: Kaggle Day 3 — 上下文缓存: "缓存长系统提示词，更快更便宜"

**现状**: 系统提示词每次 API 调用全量传输，重复计费。
**方案**:
- 使用 Gemini API 的 context caching 功能缓存 system instruction
- 缓存 TTL 设为 30 分钟（匹配会话典型时长）
- 回退: caching API 不可用时自动降级为全量传输

**影响范围**: `agent.py`, ~30 行

### 7.5.6 动态工具加载 ✅

> 来源: Kaggle Day 2 — "Context Window Bloat: 只加载 top 3-5 相关工具"

**现状**: 每个管道在创建时绑定固定工具集，全部工具描述占用 context window。
**方案**:
- 在 `classify_intent()` 时同时识别用户意图的工具子类别（8 类）
- 通过 ADK `ToolPredicate` Protocol + `ContextVar` 动态裁剪工具列表
- `IntentToolPredicate` 读取 `current_tool_categories` ContextVar，按请求过滤
- 核心工具 (10 个) 始终保留，专业工具按意图追加
- 应用于 `general_processing_agent` (11 toolsets) 和 `_make_planner_processor` (5 toolsets)
- 空集合 = 不过滤（兼容旧行为、错误回退、AMBIGUOUS 意图）

**影响范围**: `app.py`, `agent.py`, `tool_filter.py`(新), `user_context.py`, ~200 行

### 7.5.7 ADK Skills 内容丰富化 ✅

> 来源: Claude Code Skills 最佳实践 + ADK Skills 官方文档 — "Skill = 领域知识，不是工具编排脚本"

**现状**: ~~5 个宽泛领域 skill（spatial-analysis, data-quality, visualization, database, collaboration），每个仅列出工具清单和简要工作流。~~ 已拆分为 16 个场景化领域技能。
**已实现** (commit `a1f48e6`):
- 5 个旧 skill 删除 → 16 个细分场景 skill，每个包含深度领域知识（行业标准、阈值、方法论、常见陷阱）
- 6 个 references/*.md 深度参考文档（审计标准、坐标系、FFI 方法论、空间统计、PostGIS 函数、NDVI 解读）
- `skill_bundles.py` intent_triggers 更新覆盖新 skill 触发词
- `test_skills.py` 33 项测试全部通过

**16 个场景 Skill**:

| 原领域 | 新 Skill | 核心知识 |
|--------|----------|----------|
| data-quality | farmland-compliance | GB/T 21010-2017 地类编码、必备字段、面积偏差阈值 |
| data-quality | topology-validation | 拓扑规则体系、严重程度分级、修复策略 |
| data-quality | data-profiling | 四维质量评分、常见数据问题识别 |
| spatial-analysis | land-fragmentation | FFI 计算、DRL MaskablePPO 优化 |
| spatial-analysis | site-selection | 排除法 + 加权叠加、AHP 权重、缓冲距离标准 |
| spatial-analysis | spatial-clustering | Moran's I、LISA、Getis-Ord Gi*、空间权重矩阵 |
| spatial-analysis | buffer-overlay | 缓冲区类型、叠加分析、投影坐标系要求 |
| spatial-analysis | coordinate-transform | CGCS2000/WGS84/GCJ-02/BD-09、高斯带规则 |
| spatial-analysis | geocoding | 正逆向编码、批量注意事项、驾车距离 |
| spatial-analysis | ecological-assessment | NDVI 解读、DEM 地形分析、LULC、生态敏感性 |
| visualization | thematic-mapping | 分级方法、色彩方案、图例设计原则 |
| visualization | 3d-visualization | deck.gl 图层、高度映射、视角设置 |
| database | postgis-analysis | ST_* 函数、空间索引、查询优化 |
| database | data-import-export | 格式支持、入库注意事项、数据目录 |
| collaboration | team-collaboration | 团队角色、记忆类型、共享最佳实践 |
| collaboration | multi-source-fusion | 10 种融合策略、匹配方法、质量指标 |

**影响范围**: `skills/` 16 目录 + 6 references, `skill_bundles.py`, `test_skills.py`, 31 files, +2431/-226 行

---

## v8.0 — 自定义 Skills + DAG 工作流 + 智能化

**目标**: 用户可自定义 Agent 身份，工作流支持 DAG，Agent 具备自我学习能力。
**周期**: 6-8 周
**补齐模式**: Ch6 规划、Ch9 学习与适应、Ch16 资源感知、Ch3 并行化

### 8.0.1 数据库驱动的自定义 Skills

**现状**: 16 个场景化 ADK Skills 提供深度领域知识 (v7.5.7)，但 Agent 在模块加载时创建，提示词烘焙进实例，运行时不可修改。意图路由硬编码 4 种。
**方案**:
```sql
CREATE TABLE agent_custom_skills (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    team_id TEXT,
    skill_name TEXT NOT NULL,
    base_agent_type TEXT NOT NULL,
    custom_instruction TEXT NOT NULL,
    custom_tools TEXT[] DEFAULT '{}',
    trigger_keywords TEXT[] DEFAULT '{}',
    model_config JSONB DEFAULT '{}',
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);
```

- `agent.py` 重构: 静态 Agent → 工厂函数 `_make_custom_agent(skill_id)`
- `app.py` 路由扩展: `classify_intent()` 先检查用户自定义 skill triggers
- 前端 SkillBuilder: Monaco Editor 编辑提示词 + 工具选择器
- `@专家名称` 唤起语法支持
- 安全: 自定义提示词校验（防 LLM 注入），工具白名单

### 8.0.2 RAG 私有知识库挂载

**现状**: Vertex AI Search 仅用于 optimization pipeline 的 knowledge_agent。
**方案**:
- 用户上传行业 PDF → 系统创建 RAG 知识库
- 知识库绑定到自定义 Skill
- 运行时动态挂载 `VertexAiSearchTool` 到用户 Agent
- 多租户隔离: 每用户/团队独立知识库
- 可与 `knowledge_graph.py` 结合实现 GraphRAG

### 8.0.3 可视化 DAG 工作流引擎

**现状**: `workflow_engine.py` 为线性顺序执行器，`depends_on` 字段存在但未使用，`graph_data` JSONB 预留但未解析。WorkflowEditor.tsx (v7.1) 已支持可视化编辑。
**方案**:
- 重构执行引擎: 顺序 → DAG 拓扑排序
- 步骤间数据传递: 前步输出文件自动注入后步 prompt
- 条件分支节点: 基于工具输出的 if/else 判断
- 并行执行: 无依赖步骤用 ADK `ParallelAgent` 并发
- React Flow 编辑器增强: 条件节点、并行分支、循环节点

### 8.0.4 高级分析引擎

- 时空预测（GWR/GTWR，空间趋势预测）
- 场景模拟（Monte Carlo，空间溢出效应）
- 网络分析（等时圈、最优路径、设施覆盖）

### 8.0.5 失败学习与自适应

> 来源: 《Agentic Design Patterns》Ch9 学习与适应

**现状**: 工具失败后无模式记录，同类错误反复发生。
**方案**:
- 新建 `agent_failure_patterns` 表 (tool_name, error_pattern, resolution, frequency, last_seen)
- `after_tool_callback` 检测工具返回 "Error:" → 记录错误模式
- 下次相同工具调用前，检查历史失败模式 → 注入 `turn_instruction` 预警
- 高频错误模式自动推荐修复策略

**影响范围**: `agent.py`, `app.py`, 新迁移脚本, ~150 行

### 8.0.6 资源感知动态模型选择

> 来源: 《Agentic Design Patterns》Ch16 资源感知 + Kaggle Day 5 — 成本/延迟平衡

**现状**: 模型分层为静态配置，不随任务复杂度调整。
**方案**:
- 路由层增加查询复杂度评估:
  - 简单查询 → Gemini 2.0 Flash (最快)
  - 中等任务 → Gemini 2.5 Flash (默认)
  - 复杂分析 → Gemini 2.5 Pro
- 复杂度信号: 消息长度、专业关键词密度、历史失败率、管道类型

**影响范围**: `app.py`, `agent.py`, ~100 行

### 8.0.7 评估门控 CI

> 来源: Kaggle Day 5 "Evaluation-Gated Deployment" — 三阶段渐进式评估

- **PR 阶段**: 运行轻量路由评估
- **main 合并后**: 完整 4 管道 Agent 评估
- **评估门控**: 核心指标低于阈值 → CI 报红

**影响范围**: `.github/workflows/ci.yml`, ~50 行

---

## v9.0 — 协同智能 + 多 Agent 并行 + 边缘

**目标**: 从单用户工具进化为多用户协同决策平台，支持跨框架 Agent 互操作。
**周期**: 长期
**补齐模式**: Ch15 A2A、Ch21 探索与发现、Ch11 目标监控、Ch17 推理技术、Ch20 优先级排序

### 9.1 实时协同编辑
- 多用户同时查看同一地图
- CRDT 冲突解决（类 Figma 模式）
- WebRTC 语音/视频协同

### 9.2 边缘部署 + 离线模式
- ONNX Runtime 本地推理（无需 Gemini API）
- PWA 离线缓存
- 野外巡查: GPS + 拍照 + 本地分析 + 回连同步

### 9.3 数据连接器生态

| 连接器 | 协议 | 用途 |
|--------|------|------|
| WMS/WFS/WMTS | OGC 标准 | 直连地图服务 |
| ArcGIS Online | REST API | ESRI 生态对接 |
| Google Earth Engine | Python API | 遥感大数据 |
| 国土"一张图" | 政务接口 | 规划数据 |
| MQTT | IoT 协议 | 传感器实时接入 |

### 9.4 多 Agent 并行协作
- 多 Agent 并行处理不同区域数据
- ADK `ParallelAgent` 并发派发
- "分别分析 A/B/C 三个区县，汇总对比"

### 9.5 A2A 智能体互操作

> 来源: Kaggle Day 5 + 《Agentic Design Patterns》Ch15 — Google A2A 开放协议

- 实现 A2A 协议的 Server 端（AgentCard 注册、Task 管理）
- 允许外部 Agent（气象、交通、人口）通过 A2A 接入
- Agent 发现: 注册中心 + AgentCard 服务描述

### 9.6 主动探索与发现

> 来源: 《Agentic Design Patterns》Ch21 — Agent 主动探索未知空间、生成假设

- Agent 主动发现数据中的异常/趋势/空间模式
- 假设生成: "该区域耕地碎片化指数异常升高，可能与近年城市扩张相关"
- 用户可配置关注主题，Agent 定期扫描并推送洞察

---

## 设计模式覆盖演进图

```
模式覆盖度 (v7.5 → v9.0)

v7.1 已充分实现 (10/21):
  ✅ Ch1  提示链         ✅ Ch2  路由
  ✅ Ch4  反思           ✅ Ch5  工具使用
  ✅ Ch7  多智能体协作   ✅ Ch10 MCP
  ✅ Ch12 异常恢复       ✅ Ch13 HITL
  ✅ Ch18 护栏与安全     ✅ Ch19 评估与监控

v7.5 已补齐 (→ 11/21):
  ✅ Ch8  记忆管理       → Memory ETL 自动提取 + 去重 (v7.5.4)

v7.5 部分补齐:
  ⬆ Ch14 RAG            → 16 Skills 领域知识 (v7.5.7) + 待: 上下文缓存
  ⬆ Ch16 资源感知       → 动态工具加载 (v7.5.6) + 待: 动态模型选择

v8.0 补齐 (→ 15/21):
  ⬆ Ch3  并行化         → DAG 工作流并行执行
  ⬆ Ch6  规划           → 动态步骤生成
  ⬆ Ch9  学习与适应     → 失败模式记忆 + 自适应预警
  ⬆ Ch14 RAG            → 私有知识库 + GraphRAG (完整)
  ⬆ Ch16 资源感知       → 复杂度驱动动态模型选择 (完整)

v9.0 补齐 (→ 21/21):
  ⬆ Ch3  并行化 (完整)  → 多 Agent 并行协作
  ⬆ Ch11 目标监控       → 任务进度自动追踪
  ⬆ Ch15 A2A            → 跨框架智能体互操作
  ⬆ Ch17 推理技术       → Self-Consistency 多数投票
  ⬆ Ch20 优先级排序     → 多任务智能调度
  ⬆ Ch21 探索与发现     → 主动数据洞察推送
```

---

## 四层架构全景

```
┌─────────────────────────────────────────────────────────┐
│             工程化智能体开放平台                          │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  第四层：Agent 工程化基线 (v7.1 ✅ → v8.0)              │
│  ┌─────────────────────────────────────────────┐       │
│  │  v7.1 ✅ Trace ID + 反思推广 + 错误恢复指导  │       │
│  │  v7.5 ✅ Memory ETL + 动态工具 + MCP 安全     │       │
│  │  v7.5: Context Cache                         │       │
│  │  v8.0: 失败学习 + 动态模型 + 评估门控 CI      │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
│  第三层：可视化工作流编排 (v7.1 ✅ → v8.0)              │
│  ┌─────────────────────────────────────────────┐       │
│  │  v7.1 ✅ WorkflowEditor (React Flow 画布)    │       │
│  │  v8.0: DAG 拓扑 → ADK Agent 树 + 条件/并行   │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
│  第二层：自定义领域专家 Skills (v7.1 ✅ → v8.0)         │
│  ┌─────────────────────────────────────────────┐       │
│  │  v7.1 ✅ 分析视角注入（global_instruction）   │       │
│  │  v7.5 ✅ 16 场景化领域技能 + 6 参考文档       │       │
│  │  v7.5: SkillBundle 组合选择                   │       │
│  │  v8.0: DB 驱动自定义 Agent + RAG 知识库       │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
│  第一层：MCP 工具扩展 (v7.1 ✅ → v7.5)                 │
│  ┌─────────────────────────────────────────────┐       │
│  │  v7.0 ✅ 引擎就绪（3 传输协议、工具发现）     │       │
│  │  v7.1 ✅ 管理 UI + CRUD API + DB 持久化       │       │
│  │  v7.5: 安全加固 ✅ + per-User 隔离            │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  基座：v7.5 已完成能力                                    │
│  19 工具集 · 16 ADK Skills · 113+ 工具 · 10 融合策略     │
│  4 管道 · 36 API · 11/21 设计模式完整实现                 │
│  Level 0-3 智能体分类全覆盖                               │
└─────────────────────────────────────────────────────────┘
```

---

## 优先级矩阵

```
业务价值 ↑
│
│  ★ 7.5.4 Memory ETL ✅          ★ 8.0.1 自定义 Skills
│  ★ 7.5.6 动态工具加载 ✅       ★ 8.0.3 DAG 工作流
│  ★ 7.5.1 MCP 安全加固 ✅       ★ 8.0.5 失败学习
│  ★ 7.5.7 Skills 丰富化 ✅
│
│  ○ 7.5.2 技能包组合            ○ 8.0.2 RAG 知识库
│  ○ 7.5.5 Context Cache         ○ 8.0.6 动态模型
│  ○ 7.5.3 per-User MCP          ○ 8.0.4 高级分析
│                                  ○ 8.0.7 评估门控
│
│                                  △ 9.x 远期功能
│
└──────────────────────────────────────── 实现复杂度 →
```

## 推荐实施路线

```
Phase 1 (v7.5, 3-4 周) — 上下文工程 + MCP 安全 ⬅️ 当前 (4/7 完成)
  ├── 7.5.4 Memory ETL 自动提取     ★ 高价值，Agent 智能度飞跃  ✅
  ├── 7.5.6 动态工具加载             ★ 降低 token 开销 ~40%     ✅
  ├── 7.5.1 MCP 安全加固             ★ 生产就绪必备             ✅
  ├── 7.5.7 Skills 内容丰富化        ★ 5→16 场景化领域知识      ✅
  ├── 7.5.5 Gemini Context Caching   ○ 降低 API 费用 ~30%
  ├── 7.5.2 技能包组合               ○ 用户自助化 (基于 16 Skills)
  └── 7.5.3 per-User MCP 隔离        ○ 多租户隔离

Phase 2 (v8.0, 6-8 周) — 自定义 + DAG + 智能化
  ├── 8.0.1 DB 驱动自定义 Skills
  ├── 8.0.2 RAG 私有知识库
  ├── 8.0.3 DAG 工作流引擎
  ├── 8.0.4 高级分析引擎
  ├── 8.0.5 失败学习与自适应
  ├── 8.0.6 资源感知动态模型选择
  └── 8.0.7 评估门控 CI

Phase 3 (v9.0, 持续迭代) — 协同 + 边缘 + 互操作
  ├── 9.1 实时协同编辑 (CRDT)
  ├── 9.2 边缘部署 + PWA 离线
  ├── 9.3 数据连接器生态
  ├── 9.4 多 Agent 并行协作
  ├── 9.5 A2A 智能体互操作
  └── 9.6 主动探索与发现
```

---

## 竞品差异化分析

| 能力维度 | 本平台 (v8.0) | ArcGIS Pro | Julius AI | Carto |
|----------|---------------|------------|-----------|-------|
| NL 交互 | ★★★★★ | ★★☆☆☆ | ★★★★☆ | ★★☆☆☆ |
| GIS 深度 | ★★★★☆ | ★★★★★ | ★☆☆☆☆ | ★★★☆☆ |
| 多模态 | ★★★★☆ | ★★★☆☆ | ★★★☆☆ | ★☆☆☆☆ |
| 用户扩展性 | ★★★★★ (MCP+16 Skills) | ★★★☆☆ | ★☆☆☆☆ | ★★☆☆☆ |
| Agent 工程化 | ★★★★★ (21 模式) | ★★☆☆☆ | ★★★☆☆ | ★☆☆☆☆ |
| 开放生态 | ★★★★★ (MCP+A2A) | ★★★☆☆ | ★☆☆☆☆ | ★★☆☆☆ |
| 私有部署 | ★★★★★ | ★★★★☆ | ☆☆☆☆☆ | ★★☆☆☆ |
| 学习曲线 | 零 (NL) | 高 | 低 | 中 |

**核心壁垒**: "High GIS + High Agent Engineering + Open Ecosystem (MCP) + 21 Design Patterns Coverage" 四位一体。

---

## 成功指标 (KPIs)

| 指标 | v7.5 实际 | v8.0 目标 |
|------|----------|----------|
| 分析成功率 | > 90% | > 95% |
| 首次分析时间 | < 2 min | < 1 min |
| MCP 工具接入数 | 安全加固就绪 | >= 10 |
| ADK Skills 数 | 16 场景化领域技能 | 16 + 用户自建 >= 5 |
| 工作流复用率 | WorkflowEditor 就绪 | > 40% |
| 测试覆盖 | 1490+ tests | 1700+ tests |
| REST API 端点 | 36 | 48+ |
| 设计模式覆盖 | 11/21 (52%) | 16/21 (76%) |
| 管道调试时间 | Trace ID 秒级定位 | 全链路 + 告警 |
| API 成本 | 动态工具降低 ~40% | 降低 ~50% (动态模型) |

---

**方案版本**: v5.0
**更新日期**: 2026-03-12
**基于**: 《Agentic Design Patterns》21 种模式评估 + Kaggle/Google 5-Day AI Agents 课程实践 + v7.5 代码验证 + Claude Code Skills 最佳实践
