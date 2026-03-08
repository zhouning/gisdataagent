# Roadmap v9.0: 工程化智能体开放平台

> **Vision**: 从"AI 驱动的 GIS 分析平台"升级为"工程化、可扩展、可自主进化的空间智能开放平台"。
>
> **Philosophy**: "工具即生态，上下文即记忆，反思即质量，扩展即插件。"
>
> **理论基础**: 《Agentic Design Patterns》21 种模式 + Google/Kaggle 5-Day AI Agents 工程实践

---

## 当前状态 (v7.0 Baseline)

| 指标 | 数值 |
|------|------|
| 测试覆盖 | 1330+ tests, 62 test files |
| 工具集 | 19 BaseToolset, 5 SkillBundle, 113+ 工具 |
| REST API | 31 endpoints |
| 前端组件 | 9 React components |
| 管道 | 3 固定 + 1 动态规划器 (7 子智能体) |
| 数据库迁移 | 19 SQL scripts |
| 融合引擎 | ~2100 行，10 策略，5 模态 |
| 知识图谱 | ~625 行，7 实体类型 |
| 部署方式 | Docker / K8s / 本地 |
| CI | GitHub Actions (test + build + evaluate) |

### Agentic Design Patterns 覆盖度 (v7.0)

| 模式 | 章节 | 实现状态 | 代码位置 |
|------|------|----------|----------|
| 提示链 (Prompt Chaining) | Ch1 | ✅ 完整 | 3 条 SequentialAgent 管道, `agent.py` |
| 路由 (Routing) | Ch2 | ✅ 完整 | Gemini 2.0 Flash `classify_intent()`, `app.py` |
| 工具使用 (Tool Use) | Ch5 | ✅ 完整 | 19 BaseToolset, 113+ FunctionTool, `toolsets/` |
| 多智能体协作 | Ch7 | ✅ 完整 | 层级 Planner + 7 子 Agent + transfer_to_agent |
| MCP 协议 | Ch10 | ✅ 完整 | 3 传输协议 + 工具聚合, `mcp_hub.py` |
| HITL 人类参与 | Ch13 | ✅ 完整 | BasePlugin, 13 工具风险注册, `hitl_approval.py` |
| 护栏与安全 | Ch18 | ✅ 完整 | RBAC + RLS + 审计 + before_tool_callback |
| 评估与监控 | Ch19 | ✅ 完整 | 4 管道评估 + CI 集成, `run_evaluation.py` |
| 反思 (Reflection) | Ch4 | ⚠️ 部分 | LoopAgent 仅 Optimization 管道 |
| 记忆管理 (Memory) | Ch8 | ⚠️ 部分 | 手动 save_memory()，无自动 ETL |
| 规划 (Planning) | Ch6 | ⚠️ 部分 | Planner 选管道但不生成动态步骤 |
| 异常恢复 (Recovery) | Ch12 | ⚠️ 部分 | 有降级回退，工具错误无恢复指导 |
| RAG 知识检索 | Ch14 | ⚠️ 部分 | 仅 Optimization 管道 knowledge_agent |
| 资源感知 (Resource) | Ch16 | ⚠️ 部分 | 静态模型分层，非动态选择 |
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

---

## v7.1 — Agent 工程化基线 + 自助化起步

**目标**: 补齐 Agent 工程化短板，修复已知问题，为用户自助扩展打基础。
**周期**: 2-3 周
**补齐模式**: Ch4 反思、Ch12 异常恢复

### 7.1.1 MCP 服务器管理 UI ⭐ 高优先级

**现状**: MCP 引擎已完成（3 种传输协议、4 个 API 端点），但前端仅只读展示。
**方案**:
- 前端 ToolsView 增加"添加自定义 MCP 服务器"表单（URL/命令、描述、管线选择）
- 管理员可在 UI 中 toggle/reconnect
- 新增 CRUD API：`POST/PUT/DELETE /api/mcp/servers`
- 配置持久化到数据库（当前仅 YAML 静态文件）
- 热加载：DB 变更后无需重启应用

**影响范围**: `frontend_api.py`, `mcp_hub.py`, `DataPanel.tsx`, 新迁移脚本

### 7.1.2 WorkflowEditor 组件修复 ⭐ 高优先级

**现状**: `DataPanel.tsx` import 了 `WorkflowEditor` 但**文件不存在**，运行时崩溃。
**方案**:
- 创建 `WorkflowEditor.tsx`，基于 React Flow (`@xyflow/react` v12 已安装)
- 三种节点类型：DataInput、Pipeline、Output
- 属性面板：管线类型、Prompt 编辑、参数配置
- 导出 `graph_data` JSON 存入已预留的 JSONB 字段

**影响范围**: 新建 `WorkflowEditor.tsx`, `DataPanel.tsx`

### 7.1.3 用户自定义分析视角（轻量 Skills）

**现状**: Agent 提示词硬编码在 YAML，模块加载时一次性创建，运行时不可修改。
**方案**:
- 利用 ADK `global_instruction` 注入用户自定义上下文
- 存入 `user_memories` 表（`memory_type="custom_focus"`）
- 前端 UserSettings 增加"我的分析视角"文本区域
- 示例："我是林业规划师，重点关注生态红线和森林覆盖率"

**影响范围**: `agent.py`, `app.py`, `UserSettings.tsx`, ~50 行

### 7.1.4 Prompt 版本管理 🆕

> 来源: Kaggle Day 5 "Prototype to Production" — 代码、Prompt、Tool Schema 均需版本控制

**现状**: 3 个 YAML 提示词文件无版本号，变更只能 git diff 追踪。
**方案**:
- 每个 YAML 头部加 `_version: "7.0.0"` + `_changelog` 列表
- `prompts/__init__.py` 的 `load_prompts()` 解析版本号并日志输出
- 启动时打印 `[Prompt] optimization=7.0.0, general=7.0.0, planner=7.0.0`

**影响范围**: `prompts/*.yaml`, `prompts/__init__.py`, ~30 行

### 7.1.5 工具错误恢复指导 🆕

> 来源: Kaggle Day 2 "Tool Design Best Practices" — 错误消息应含恢复路径

**现状**: 工具返回 `"Error: {str(e)}"`，Agent 无法判断下一步该做什么。
**方案**:
- 为 5 个高频工具的常见错误场景追加恢复建议：
  - 文件未找到 → "请先调用 search_data_assets 或 list_user_files 检查可用文件"
  - CRS 不匹配 → "请先调用 reproject_spatial_data 统一坐标系"
  - 字段不存在 → "请先调用 describe_geodataframe 查看可用字段列表"
  - 数据为空 → "请检查输入文件是否为空，或筛选条件是否过于严格"
- 优先改进: `describe_geodataframe`, `generate_choropleth`, `fuse_datasets`, `query_database`, `spatial_join`

**影响范围**: `toolsets/exploration_tools.py`, `toolsets/visualization_tools.py`, `toolsets/fusion_tools.py`, `toolsets/database_tools.py`, ~50 行

### 7.1.6 反思循环推广 🆕

> 来源: 《Agentic Design Patterns》Ch4 反思 — "所有输出都值得自我审查"

**现状**: `AnalysisQualityLoop` (LoopAgent, max 3 轮) 仅用于 Optimization 管道。Governance 和 General 管道无质量反思循环。
**方案**:
- **Governance 管道**: 报告生成后增加"合规性自检"循环 — GovernanceReporter → ComplianceChecker，验证报告是否覆盖必要合规项
- **General 管道**: 可视化后增加"结果完整性检查"循环 — GeneralViz → ResultChecker，验证地图/图表是否完整呈现数据
- 复用现有 LoopAgent 模式 (`agent.py:186-190`)

**影响范围**: `agent.py`, `prompts/general.yaml`, `prompts/optimization.yaml`, ~60 行

### 7.1.7 端到端 Trace ID 🆕

> 来源: Kaggle Day 4 "Agent Quality" — 可观测性三位一体: Logs + Traces + Metrics

**现状**: 有 JSON 结构化日志和 Prometheus 指标，但缺少贯穿路由→Agent 1→Agent 2→...的 trace_id，长管道调试困难。
**方案**:
- 每次消息处理生成 `trace_id = uuid4().hex[:12]`
- 新增 `current_trace_id` ContextVar 在 `user_context.py`
- `observability.py` 的 `JsonFormatter` 自动注入 trace_id 字段
- 管道开始/结束打印 `[Trace:{id}] Pipeline={name} Started/Finished duration={s}s`
- 所有 `[ArtifactDetect]`/`[MapInject]`/`[Router]` 日志自动携带

**影响范围**: `user_context.py`, `observability.py`, `app.py`, ~80 行

---

## v7.5 — 上下文工程 + MCP 市场

**目标**: 实现 Agent 上下文工程最佳实践，完善 MCP 自助化。
**周期**: 3-4 周
**补齐模式**: Ch8 记忆管理、Ch14 RAG 增强

### 7.5.1 MCP 服务器安全加固

- 配置输入校验（防止命令注入）
- Auth token 加密存储（非明文 YAML）
- 操作审计日志（谁添加/删除了服务器）
- 用户配额（每用户最多 N 个自定义服务器）
- 连接前自动测试（Test Connection 按钮）

### 7.5.2 用户自定义技能包组合

**现状**: `skill_bundles.py` 定义了 5 个命名工具组合，但实际未在 Agent 装配中使用。
**方案**:
- 新建 `agent_custom_bundles` 表（用户 ID + 选择的 bundle 列表）
- 前端增加 SkillBuilder 面板：从 5 个 bundle 中勾选组合
- Planner Agent 根据用户配置动态调整可用工具集

**影响范围**: `skill_bundles.py`, `agent.py`, `frontend_api.py`, `DataPanel.tsx`, 新迁移脚本

### 7.5.3 per-User MCP 服务器隔离

- 数据库中 MCP 配置增加 `user_id` 外键
- 全局服务器（admin 创建）对所有用户可见
- 用户私有服务器仅本人可见
- 工具发现按用户范围过滤

### 7.5.4 Memory ETL 自动提取 🆕

> 来源: Kaggle Day 3 "Context Engineering" — Memory ETL Pipeline: Extract → Consolidate → Store

**现状**: 记忆系统完全依赖 Agent 手动调用 `save_memory()` 工具。对话中产生的关键发现（数据特征、分析结论、用户偏好）不会自动保存，下次会话丢失上下文。
**方案**:
- 管道执行完成后，自动调用 LLM 提取会话关键事实
- 提取模板: "从以下对话中提取关键发现（数据特征、分析结论、用户偏好），返回 JSON 数组"
- 自动写入 `user_memories` 表 (`memory_type="auto_extract"`)
- 去重: 对比已有记忆的 key 值，新事实合并而非重复
- 用户可在 UserSettings 查看/删除自动记忆
- 配额: 每次会话最多提取 5 条，单用户最多 100 条自动记忆

**影响范围**: `app.py`, `memory.py`, `UserSettings.tsx`, ~100 行

### 7.5.5 Gemini Context Caching 🆕

> 来源: Kaggle Day 3 — 上下文缓存: "缓存长系统提示词，更快更便宜"

**现状**: 系统提示词（optimization.yaml ~2000 token, planner.yaml ~1500 token）每次 API 调用全量传输，重复计费。
**方案**:
- 使用 Gemini API 的 context caching 功能缓存 system instruction
- 适用于不频繁变更的长提示词（optimization、planner 的 system prompt）
- 缓存 TTL 设为 30 分钟（匹配会话典型时长）
- 回退: caching API 不可用时自动降级为全量传输
- 预估节省 ~30% system prompt token 费用

**影响范围**: `agent.py`, ~30 行

### 7.5.6 动态工具加载 🆕

> 来源: Kaggle Day 2 — "Context Window Bloat: 只加载 top 3-5 相关工具"

**现状**: 每个管道在创建时绑定固定工具集（如 GeneralProcessing 加载 7 个 Toolset），全部工具描述占用 context window。
**方案**:
- 在 `classify_intent()` 时同时识别用户意图的工具子类别
- 意图→工具映射: "可视化"→VisualizationToolset, "融合"→FusionToolset, "查询"→DatabaseToolset
- Agent 创建时通过已有 `tool_filter` 机制裁剪工具列表
- 核心工具始终保留 (explore, describe)，专业工具按意图追加
- 预估节省 context window ~40% (工具描述从 ~50 个降至 ~15 个)

**影响范围**: `app.py`, `agent.py`, ~80 行

---

## v8.0 — 自定义 Skills + DAG 工作流 + 智能化

**目标**: 用户可自定义 Agent 身份，工作流支持 DAG，Agent 具备自我学习能力。
**周期**: 6-8 周
**补齐模式**: Ch6 规划、Ch9 学习与适应、Ch16 资源感知、Ch3 并行化

### 8.0.1 数据库驱动的自定义 Skills

**现状**: Agent 在模块加载时创建，提示词烘焙进实例，运行时不可修改。意图路由硬编码 4 种。
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

**现状**: `workflow_engine.py` 为线性顺序执行器，`depends_on` 字段存在但未使用，`graph_data` JSONB 预留但未解析。
**方案**:
- 重构执行引擎: 顺序 → DAG 拓扑排序
- 步骤间数据传递: 前步输出文件自动注入后步 prompt
- 条件分支节点: 基于工具输出的 if/else 判断
- 并行执行: 无依赖步骤用 ADK `ParallelAgent` 并发
- React Flow 编辑器增强: 条件节点、并行分支、循环节点
- 解析 React Flow JSON → ADK Agent 树动态实例化

### 8.0.4 高级分析引擎

- 时空预测（GWR/GTWR，空间趋势预测）
- 场景模拟（Monte Carlo，空间溢出效应）
- 网络分析（等时圈、最优路径、设施覆盖）

### 8.0.5 失败学习与自适应 🆕

> 来源: 《Agentic Design Patterns》Ch9 学习与适应 — "Agent 从历史交互中学习改进"

**现状**: 工具失败后无模式记录，同类错误反复发生，不影响后续行为。
**方案**:
- 新建 `agent_failure_patterns` 表 (tool_name, error_pattern, resolution, frequency, last_seen)
- `after_tool_callback` 检测工具返回 "Error:" → 记录错误模式
- 下次相同工具调用前，检查历史失败模式 → 注入 `turn_instruction` 预警
- 示例: "历史记录显示 spatial_join 常因 CRS 不匹配失败，建议先用 describe_geodataframe 检查 CRS"
- 高频错误模式自动推荐修复策略

**影响范围**: `agent.py`, `app.py`, 新迁移脚本, ~150 行

### 8.0.6 资源感知动态模型选择 🆕

> 来源: 《Agentic Design Patterns》Ch16 资源感知 + Kaggle Day 5 — 成本/延迟平衡

**现状**: 模型分层为静态配置 (Explorer/Viz→Flash, Processor/Analyzer→Flash, Reporter→Pro)，不随任务复杂度调整。
**方案**:
- 路由层增加查询复杂度评估:
  - 简单查询（列表文件、查看数据）→ Gemini 2.0 Flash (最快)
  - 中等任务（单步处理、常规分析）→ Gemini 2.5 Flash (默认)
  - 复杂分析（多步推理、报告生成、优化）→ Gemini 2.5 Pro
- 复杂度信号: 消息长度、专业关键词密度、历史该用户失败率、管道类型
- 预估降低 ~30% API 费用 (简单查询占 60%+ 请求)

**影响范围**: `app.py`, `agent.py`, ~100 行

### 8.0.7 评估门控 CI 🆕

> 来源: Kaggle Day 5 "Evaluation-Gated Deployment" — 三阶段渐进式评估

**现状**: Agent 评估仅在 main push 时运行，失败不阻止合并，无评估趋势追踪。
**方案**:
- **PR 阶段**: 运行轻量路由评估 (`test_routing_evaluation.py` 19 测试)
- **main 合并后**: 完整 4 管道 Agent 评估
- **评估门控**: 核心指标低于阈值 → CI 报红，要求人工确认
- **趋势追踪**: 每次评估结果存入 CI artifact，可视化分数趋势

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

### 9.5 A2A 智能体互操作 🆕

> 来源: Kaggle Day 5 + 《Agentic Design Patterns》Ch15 — Google A2A 开放协议

- 实现 A2A 协议的 Server 端（AgentCard 注册、Task 管理）
- 允许外部 Agent（气象、交通、人口）通过 A2A 接入
- Agent 发现: 注册中心 + AgentCard 服务描述
- 分布式追踪: trace_id 跨 Agent 传递

### 9.6 主动探索与发现 🆕

> 来源: 《Agentic Design Patterns》Ch21 — Agent 主动探索未知空间、生成假设

- Agent 主动发现数据中的异常/趋势/空间模式
- 假设生成: "该区域耕地碎片化指数异常升高，可能与近年城市扩张相关"
- 用户可配置关注主题，Agent 定期扫描并推送洞察
- 借鉴 Google Co-Scientist 模式

---

## 设计模式覆盖演进图

```
模式覆盖度 (v7.0 → v9.0)

v7.0 已充分实现 (8/21):
  ✅ Ch1  提示链         ✅ Ch2  路由
  ✅ Ch5  工具使用       ✅ Ch7  多智能体协作
  ✅ Ch10 MCP            ✅ Ch13 HITL
  ✅ Ch18 护栏与安全     ✅ Ch19 评估与监控

v7.1 补齐 (→ 10/21):
  ⬆ Ch4  反思           → 推广到 Governance + General 管道
  ⬆ Ch12 异常恢复       → 工具错误含恢复建议

v7.5 补齐 (→ 12/21):
  ⬆ Ch8  记忆管理       → Memory ETL 自动提取 + 去重
  ⬆ Ch14 RAG            → 知识图谱 + 上下文缓存

v8.0 补齐 (→ 16/21):
  ⬆ Ch3  并行化         → DAG 工作流并行执行
  ⬆ Ch6  规划           → 动态步骤生成
  ⬆ Ch9  学习与适应     → 失败模式记忆 + 自适应预警
  ⬆ Ch16 资源感知       → 复杂度驱动动态模型选择

v9.0 补齐 (→ 21/21):
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
│  第四层：Agent 工程化基线 (v7.1–v8.0)                    │
│  ┌─────────────────────────────────────────────┐       │
│  │  v7.1: Trace ID + 反思推广 + 错误恢复指导    │       │
│  │  v7.5: Memory ETL + Context Cache + 动态工具  │       │
│  │  v8.0: 失败学习 + 动态模型 + 评估门控 CI      │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
│  第三层：可视化工作流编排 (v8.0)                          │
│  ┌─────────────────────────────────────────────┐       │
│  │  React Flow 画布 → DAG 拓扑 → ADK Agent 树   │       │
│  │  条件分支 / 并行执行 / 步骤间数据传递          │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
│  第二层：自定义领域专家 Skills (v7.5–v8.0)                │
│  ┌─────────────────────────────────────────────┐       │
│  │  v7.1: global_instruction 注入（轻量）        │       │
│  │  v7.5: SkillBundle 组合选择                   │       │
│  │  v8.0: DB 驱动自定义 Agent + RAG 知识库       │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
│  第一层：MCP 工具扩展 (v7.1–v7.5)                        │
│  ┌─────────────────────────────────────────────┐       │
│  │  v7.0: 引擎就绪（3 传输协议、工具发现）        │       │
│  │  v7.1: 管理 UI + CRUD API + DB 持久化         │       │
│  │  v7.5: 安全加固 + per-User 隔离               │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  基座：v7.0 已完成能力                                    │
│  19 工具集 · 113+ 工具 · 10 融合策略 · 4 管道 · 31 API   │
│  8/21 设计模式完整实现 · Level 0-3 智能体分类全覆盖       │
└─────────────────────────────────────────────────────────┘
```

---

## 优先级矩阵

```
业务价值 ↑
│
│  ★ 7.1.1 MCP 管理 UI          ★ 8.0.1 自定义 Skills
│  ★ 7.1.2 WorkflowEditor       ★ 8.0.3 DAG 工作流
│  ★ 7.1.6 反思推广             ★ 8.0.5 失败学习
│  ★ 7.1.7 Trace ID
│                                 ○ 8.0.2 RAG 知识库
│  ○ 7.5.4 Memory ETL            ○ 8.0.6 动态模型
│  ○ 7.5.6 动态工具加载          ○ 8.0.4 高级分析
│  ○ 7.5.5 Context Cache         ○ 8.0.7 评估门控
│
│  △ 7.1.3 分析视角              △ 9.x 远期功能
│  △ 7.1.4 Prompt版本
│  △ 7.1.5 错误恢复
│
└──────────────────────────────────────── 实现复杂度 →
```

## 推荐实施路线

```
Phase 1 (v7.1, 2-3 周) — 工程化基线 + 修复
  ├── 7.1.1 MCP 管理 UI (CRUD API + 前端表单)
  ├── 7.1.2 WorkflowEditor.tsx (React Flow 基础编辑器)
  ├── 7.1.3 分析视角注入 (global_instruction)
  ├── 7.1.4 Prompt 版本管理 (YAML 头部 + 日志)       🆕
  ├── 7.1.5 工具错误恢复指导 (5 个高频工具)           🆕
  ├── 7.1.6 反思循环推广 (Governance + General)       🆕
  └── 7.1.7 端到端 Trace ID (ContextVar + 日志)      🆕

Phase 2 (v7.5, 3-4 周) — 上下文工程 + MCP 市场
  ├── 7.5.1 MCP 安全加固
  ├── 7.5.2 技能包组合 (SkillBuilder UI)
  ├── 7.5.3 per-User MCP 隔离
  ├── 7.5.4 Memory ETL 自动提取                       🆕
  ├── 7.5.5 Gemini Context Caching                    🆕
  └── 7.5.6 动态工具加载                               🆕

Phase 3 (v8.0, 6-8 周) — 自定义 + DAG + 智能化
  ├── 8.0.1 DB 驱动自定义 Skills
  ├── 8.0.2 RAG 私有知识库
  ├── 8.0.3 DAG 工作流引擎
  ├── 8.0.4 高级分析引擎
  ├── 8.0.5 失败学习与自适应                           🆕
  ├── 8.0.6 资源感知动态模型选择                       🆕
  └── 8.0.7 评估门控 CI                                🆕

Phase 4 (v9.0, 持续迭代) — 协同 + 边缘 + 互操作
  ├── 9.1 实时协同编辑 (CRDT)
  ├── 9.2 边缘部署 + PWA 离线
  ├── 9.3 数据连接器生态
  ├── 9.4 多 Agent 并行协作
  ├── 9.5 A2A 智能体互操作                             🆕
  └── 9.6 主动探索与发现                               🆕
```

---

## 竞品差异化分析

| 能力维度 | 本平台 (v8.0) | ArcGIS Pro | Julius AI | Carto |
|----------|---------------|------------|-----------|-------|
| NL 交互 | ★★★★★ | ★★☆☆☆ | ★★★★☆ | ★★☆☆☆ |
| GIS 深度 | ★★★★☆ | ★★★★★ | ★☆☆☆☆ | ★★★☆☆ |
| 多模态 | ★★★★☆ | ★★★☆☆ | ★★★☆☆ | ★☆☆☆☆ |
| 用户扩展性 | ★★★★★ (MCP+Skills) | ★★★☆☆ | ★☆☆☆☆ | ★★☆☆☆ |
| Agent 工程化 | ★★★★★ (21 模式) | ★★☆☆☆ | ★★★☆☆ | ★☆☆☆☆ |
| 开放生态 | ★★★★★ (MCP+A2A) | ★★★☆☆ | ★☆☆☆☆ | ★★☆☆☆ |
| 私有部署 | ★★★★★ | ★★★★☆ | ☆☆☆☆☆ | ★★☆☆☆ |
| 学习曲线 | 零 (NL) | 高 | 低 | 中 |

**核心壁垒**: "High GIS + High Agent Engineering + Open Ecosystem (MCP) + 21 Design Patterns Coverage" 四位一体。

---

## 成功指标 (KPIs)

| 指标 | v7.0 实际 | v7.5 目标 | v8.0 目标 |
|------|----------|----------|----------|
| 分析成功率 | > 90% | > 92% | > 95% |
| 首次分析时间 | < 2 min | < 1.5 min | < 1 min |
| MCP 工具接入数 | 1（静态配置） | ≥ 3（自助添加） | ≥ 10 |
| 自定义 Skills 数 | 0 | 束组合可选 | 用户自建 ≥ 5 |
| 工作流复用率 | — | > 20% | > 40% |
| 测试覆盖 | 1330+ tests | 1500+ tests | 1700+ tests |
| REST API 端点 | 31 | 38+ | 45+ |
| 设计模式覆盖 | 8/21 (38%) | 12/21 (57%) | 16/21 (76%) |
| 管道调试时间 | 无追踪 | Trace ID 秒级定位 | 全链路追踪 |
| API 成本 | 基线 | 降低 ~30% (缓存) | 降低 ~50% (动态模型) |

---

**方案版本**: v3.0
**更新日期**: 2026-03-08
**基于**: 《Agentic Design Patterns》21 种模式评估 + Kaggle/Google 5-Day AI Agents 课程实践 + 代码级现状验证
