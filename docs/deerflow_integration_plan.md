# DeerFlow 借鉴融合 — Roadmap 补充方案

> 2026-03-30 | 基于 DeerFlow v2.0 vs Data Agent v15.8 对比分析

## 融合原则

1. **借鉴架构思想，不照搬实现** — Data Agent 是垂直 GIS 平台，不需要变成通用 Agent Harness
2. **优先解决技术债** — 先重构再加功能，DeerFlow 的 Harness/App 分离正好指导 app.py 拆分
3. **按投入产出比排序** — 小成本大收益的先做
4. **与现有 roadmap 自然衔接** — 融入 v16.0+ 规划，不打乱节奏

---

## 融合项一览

| 序号 | 借鉴点 | 优先级 | 预估工作量 | 建议版本 | 依赖 |
|------|--------|--------|-----------|---------|------|
| D-1 | App 分层重构 (Harness/App 分离) | **P0** | 大 (3-5天) | v15.9 | 无 |
| D-2 | 中间件链模式 | **P1** | 中 (2-3天) | v15.9 | D-1 |
| D-3 | 上下文自动摘要 | **P1** | 小 (1天) | v15.9 | 无 |
| D-4 | 工具调用 Guardrails | **P2** | 中 (1-2天) | v16.0 | D-2 |
| D-5 | AI 辅助 Skill 创建 | **P2** | 中 (2天) | v16.0 | 无 |
| D-6 | 长期记忆增强 | **P3** | 中 (2天) | v16.0+ | D-3 |

---

## D-1: App 分层重构 — Harness/App 分离 (P0)

### 问题
app.py 3340 行是项目最大技术债。UI 逻辑、RBAC、路由、文件处理、图层控制全部混在一起。每次改动都有副作用风险，AI 助手在长上下文中也容易迷失。

### DeerFlow 启发
DeerFlow 严格划分 Harness (`deerflow.*`) 和 App (`app.*`)，用 CI 测试强制约束边界——Harness 永远不能 import App。

### 方案

将 app.py 拆分为 4 层：

```
data_agent/
├── core/                    # Harness 层 — 可独立测试，零 UI 依赖
│   ├── agent_runtime.py     # Agent 创建 + pipeline 组装 (从 agent.py 提取)
│   ├── intent_router.py     # 已独立 ✓
│   ├── pipeline_runner.py   # 已独立 ✓
│   ├── pipeline_helpers.py  # 已独立 ✓
│   └── tool_registry.py     # 所有 Toolset 的注册表 (从 agent.py 提取)
├── api/                     # API 层 — REST 端点，零 Chainlit 依赖
│   ├── frontend_api.py      # 已有 ✓ (待进一步按 domain 拆分)
│   ├── workflow_routes.py   # 已独立 ✓
│   ├── quality_routes.py    # 已独立 ✓
│   └── ...
├── app.py                   # UI 层 — 仅 Chainlit 回调 + 胶水代码 (目标 <500 行)
└── middleware/              # 中间件层 (见 D-2)
```

### 边界规则 (CI 测试强制)
```python
# test_harness_boundary.py
def test_core_never_imports_chainlit():
    """core/ 下的模块永远不能 import chainlit"""
    for path in glob("data_agent/core/**/*.py"):
        source = open(path).read()
        assert "import chainlit" not in source
        assert "from chainlit" not in source
```

### 收益
- app.py 从 3340 行降到 <500 行
- core/ 可独立测试，不需要 Chainlit 上下文
- AI 助手处理代码更高效 (每个文件职责单一)

### 与现有 roadmap 衔接
这是 v14.4 "DataPanel 拆分重构" 的延续——当时拆了前端 (2922→17 组件)，现在拆后端。

---

## D-2: 中间件链模式 (P1)

### 问题
当前 pipeline 执行中的横切关注点 (token 追踪、错误处理、上下文管理、RBAC 检查) 散布在 app.py 各处，修改一个关注点需要理解整个文件。

### DeerFlow 启发
DeerFlow 的 12 层中间件链 — 每层单一职责，可独立启停，执行顺序严格定义。

### 方案

定义 `PipelineMiddleware` 协议，将现有散落逻辑提取为独立中间件：

```python
# data_agent/middleware/base.py
class PipelineMiddleware(ABC):
    async def before_run(self, context: PipelineContext) -> PipelineContext: ...
    async def after_run(self, context: PipelineContext, result: Any) -> Any: ...
    async def on_error(self, context: PipelineContext, error: Exception) -> None: ...
```

**首批中间件 (从 app.py 提取):**

| 中间件 | 来源 | 职责 |
|--------|------|------|
| `RBACMiddleware` | app.py RBAC 检查 | 角色权限验证 |
| `TokenTrackingMiddleware` | token_tracker.py 调用 | Token 计量 + 成本归因 |
| `FileUploadMiddleware` | app.py 文件处理 | ZIP 解压 + 格式检测 + 沙箱路径 |
| `LayerControlMiddleware` | app.py 图层检测 | 工具输出 → 地图图层元数据注入 |
| `ErrorClassificationMiddleware` | pipeline_helpers.py | 错误分类 + 用户友好提示 |
| `ContextSummarizationMiddleware` | **新增 (D-3)** | 长对话自动摘要 |
| `GuardrailMiddleware` | **新增 (D-4)** | 工具调用前置策略检查 |

**执行顺序:**
```
RBAC → FileUpload → ContextSummarization → [Pipeline 执行] → TokenTracking → LayerControl → ErrorClassification
```

### 收益
- 关注点分离——改 token 追踪不碰 RBAC 代码
- 可组合——不同 pipeline 可挂不同中间件组合
- 可测试——每个中间件独立单测

### 依赖
需要 D-1 先完成，否则中间件没有清晰的挂载点。

---

## D-3: 上下文自动摘要 (P1)

### 问题
长对话场景下 (特别是多轮分析)，上下文 token 不断累积。Gemini 虽有大 context window，但越长的上下文 = 越高的成本 + 越慢的响应 + 越低的注意力精度。

### DeerFlow 启发
SummarizationMiddleware — 当对话 token 接近阈值时，自动调用 LLM 摘要历史对话，压缩上下文。

### 方案

```python
# data_agent/middleware/summarization.py
class SummarizationMiddleware(PipelineMiddleware):
    TOKEN_THRESHOLD = 80000  # 80% of Gemini 2.5 Flash context

    async def before_run(self, context):
        if context.total_tokens > self.TOKEN_THRESHOLD:
            summary = await self._summarize(context.history)
            context.history = [SystemMessage(summary)] + context.history[-3:]
        return context
```

**关键设计:**
- 只摘要历史消息，保留最近 3 轮完整对话
- 摘要保留：关键数据文件路径、分析结论、用户偏好
- 摘要丢弃：中间推理过程、工具调用细节、重复信息
- 使用 Gemini 2.0 Flash (便宜快速) 做摘要

### 收益
- 长对话不再退化
- Token 成本可控
- 与 D-2 中间件链自然集成

### 工作量
约 1 天——核心逻辑简单，难点在摘要 prompt 的质量调优。

---

## D-4: 工具调用 Guardrails (P2)

### 问题
当前工具调用没有前置安全检查。Agent 可以调用任何已注册工具，包括危险操作 (如数据库写入、文件删除)。RBAC 只做了 pipeline 级别的粗粒度控制。

### DeerFlow 启发
GuardrailMiddleware — 可插拔的确定性策略引擎 (非 LLM 判断)，支持 allowlist / OAP policy / custom provider。

### 方案

```python
# data_agent/middleware/guardrail.py
class GuardrailMiddleware(PipelineMiddleware):
    """工具调用前置策略检查"""

    # 策略配置 (YAML)
    policies:
      viewer:
        deny: [delete_*, drop_*, execute_sql_write, mask_sensitive_*]
        allow: [query_*, search_*, list_*, get_*]
      analyst:
        deny: [delete_user, admin_*]
        require_confirmation: [execute_sql_write, bulk_clean_*]
      admin:
        allow_all: true
```

**三级策略:**
1. **Deny** — 静默拒绝，Agent 收到"权限不足"消息
2. **Require Confirmation** — 暂停执行，推送确认卡片给用户
3. **Allow** — 直接执行

### 与现有 RBAC 的关系
RBAC (pipeline 级) + Guardrails (工具级) = 完整的两层安全：
- RBAC: viewer 不能进 Governance pipeline
- Guardrails: analyst 进了 pipeline 但不能调用 `delete_data_asset`

### 工作量
约 1-2 天。策略引擎简单 (模式匹配)，主要工作在梳理 28 个 Toolset 的工具分级。

---

## D-5: AI 辅助 Skill 创建 (P2)

### 问题
当前 Custom Skills 需要用户手写 instructions、选择 toolsets、配置 trigger keywords。对非技术用户门槛较高。

### DeerFlow 启发
Skill Creator 元技能 — 用 AI 创建新 Skill，含分析器、比较器、评分器，自我进化。

### 方案

新增一个内置 Skill: `skill-creator`

```yaml
# data_agent/skills/skill-creator/SKILL.md
name: skill-creator
description: 用自然语言描述你想要的分析能力，AI 自动生成 Custom Skill
trigger_keywords: [创建技能, 新建skill, make skill]
```

**工作流:**
1. 用户描述需求: "我需要一个技能，对比两个时间点的建筑物数据，找出新增和拆除的建筑"
2. AI 分析需求 → 推荐合适的 toolsets (GeoProcessing + Analysis + Visualization)
3. AI 生成 Skill 配置 (name, instructions, tools, triggers)
4. 用户预览 → 确认 → 保存到 DB
5. 新 Skill 立即可用

**与现有体系的集成:**
- 复用 `custom_skills.py` 的 CRUD API
- 复用 `capabilities.py` 的 toolset 元数据
- 新增 `/api/skills/generate` 端点

### 收益
- 非技术用户也能创建 Skills
- 利用 AI 理解 toolset 能力，推荐最佳组合
- 降低自服务扩展门槛

---

## D-6: 长期记忆增强 (P3)

### 问题
当前 memory 系统 (`memory.py`) 是简单的 key-value 存储。没有自动事实抽取、去重、跨会话关联。

### DeerFlow 启发
LLM 驱动的事实抽取 + 空白标准化去重 + 异步批量更新 + top-K 相关记忆注入。

### 方案

在现有 memory.py 基础上增加：

1. **自动事实抽取** — pipeline 完成后，LLM 提取关键事实 (数据集特征、分析结论、用户偏好)
2. **语义去重** — 新事实与已有记忆做嵌入相似度比较，>0.9 则更新而非新增
3. **相关记忆注入** — Agent 执行前，检索 top-5 相关记忆注入 system prompt
4. **记忆衰减** — 长期未被访问的记忆降低权重

**与 D-3 的关系:**
D-3 (上下文摘要) 解决单次对话的上下文膨胀；D-6 (长期记忆) 解决跨会话的知识积累。两者互补。

### 工作量
约 2 天。依赖现有的 embedding 基础设施 (text-embedding-004 + pgvector)。

---

## Roadmap 时间线整合

```
v15.9 (近期)
├── D-1: App 分层重构 ← 最高优先级，解决最大技术债
├── D-2: 中间件链模式 ← 依赖 D-1
├── D-3: 上下文自动摘要 ← 独立可做
├── 字段映射可视化编辑器 (历史遗留)
└── 自适应布局 (历史遗留)

v16.0 (中期，与遥感智能体并行)
├── D-4: 工具调用 Guardrails
├── D-5: AI 辅助 Skill 创建
├── 遥感核心能力 Phase 1 (光谱指数库 + 经验池)
└── Generator/Reviewer Pydantic 校验 (历史遗留)

v16.0+ (远期)
├── D-6: 长期记忆增强
├── 遥感 Phase 2-4
└── 其他远期规划
```

---

## 不借鉴的部分 (及原因)

| DeerFlow 特性 | 不借鉴原因 |
|--------------|-----------|
| **四服务架构** (Nginx + LangGraph + Gateway + Frontend) | Data Agent 是单机/小团队场景，单体 + 子系统已够用，不需要微服务化 |
| **LangGraph 状态机** | 已深度绑定 ADK，迁移成本远大于收益 |
| **IM 通道** (Telegram/Slack/飞书) | 目标用户通过 Web UI 交互，不需要 IM |
| **Docker/K8s 沙箱** | GIS 工具 (GeoPandas/Rasterio/PostGIS) 需要本地文件系统访问，沙箱反而增加复杂度 |
| **Claude Code / Codex 集成** | 定位不同，Data Agent 不是开发者工具 |
| **ACP 协议** | 已有 A2A 协议实现，功能重叠 |
| **虚拟路径系统** | 当前用户沙箱 (uploads/{user_id}/) 已满足需求 |

---

## 新增标杆对标

在 roadmap 标杆对标表中增加 DeerFlow 维度：

| 标杆能力 | 来源 | 当前状态 | 目标 |
|----------|------|---------|------|
| Harness/App 分离 | DeerFlow | 🔴 app.py 3340 行 | 🟢 v15.9 core/ 独立 |
| 中间件链 | DeerFlow | 🔴 横切关注点散布 | 🟢 v15.9 7 层中间件 |
| 上下文摘要 | DeerFlow | 🔴 无 | 🟢 v15.9 自动摘要 |
| Guardrails | DeerFlow | 🟡 RBAC 仅 pipeline 级 | 🟢 v16.0 工具级策略 |
| Skill Creator | DeerFlow | 🟡 手工创建 | 🟢 v16.0 AI 辅助生成 |
| 长期记忆 | DeerFlow | 🟡 简单 KV | 🟢 v16.0+ 事实抽取+去重 |
