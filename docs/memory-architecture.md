# Data Agent 记忆体系架构

> GIS Data Agent 的五层记忆体系 + ContextEngine 统一上下文引擎 + FeedbackLoop 反馈飞轮：从即时状态传递到永久知识库，实现跨请求、跨会话、跨用户的智能记忆。

---

## 架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                   ContextEngine (v19.0 统一上下文引擎)                │
│     6 ContextProvider → token budget → 按相关性裁剪 → TTL 缓存 (3min) │
│     SemanticLayer | KnowledgeBase | KnowledgeGraph |                │
│     ReferenceQuery | SuccessStory | MetricDefinition                │
├─────────────────────────────────────────────────────────────────────┤
│                   FeedbackLoop (v19.0 反馈飞轮)                      │
│     FeedbackStore (👍👎) → Upvote→ReferenceQueryStore 自动入库       │
│                          → Downvote→FailureAnalyzer→PromptOptimizer │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 5: 永久知识 (Knowledge)                                       │
│  Knowledge Base (RAG + GraphRAG) + 知识图谱 + 案例库(v15.7)           │
│  ReferenceQueryStore (v19.0) + MetricFlow 语义模型 (v19.0)            │
│  生命周期: 永久 | 存储: PostgreSQL + pgvector | 范围: per-user + 共享   │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 4: 长期记忆 (Long-term Memory)                                │
│  空间记忆 (memory.py) — 区域/可视化偏好/分析视角/自动提取              │
│  失败学习 (failure_learning.py) — 工具失败模式 + 修复提示               │
│  生命周期: 永久 | 存储: PostgreSQL | 范围: per-user                    │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 3: 中期记忆 (Cross-session Memory)                            │
│  对话记忆 (conversation_memory.py) — 历史分析片段 + Memory ETL          │
│  生命周期: 永久 | 存储: PostgreSQL | 范围: per-user                    │
│  ADK Runner 自动检索相关历史，注入到当前 prompt                         │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 2: 短期记忆 (Session Memory)                                  │
│  上轮上下文 (last_context) — 上一轮管线/文件/摘要                      │
│  生命周期: 当前会话 | 存储: Chainlit user_session | 范围: 单会话         │
│  手动注入到 prompt: "上一轮使用了 X 管线，生成了 Y 文件"                 │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 1: 即时状态 (Immediate State)                                 │
│  Agent output_key — Pipeline 内 Agent 间状态传递                      │
│  ContextVar (user_context.py) — 用户身份/角色/会话/追踪/工具类别/模型层  │
│  生命周期: 单次请求 | 存储: 内存 | 范围: 单次 Pipeline 执行              │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Layer 1: 即时状态 (Immediate State)

### 1.1 Agent `output_key` — Pipeline 内状态传递

**位置**: ADK Agent 配置，`agent.py` (853 行) 中定义

**机制**: SequentialAgent 中的每个 LlmAgent 通过 `output_key` 将输出写入 session state，下游 Agent 自动继承。

**output_key 清单**:

| output_key | 生产 Agent | 消费 Agent |
|------------|-----------|-----------|
| `data_profile` | data_exploration_agent, governance_exploration_agent, PlannerExplorer | Processing, Analysis 阶段 |
| `semantic_context` | semantic_prefetch_agent | Processing 阶段 |
| `processed_data` | data_processing_agent, governance_processing_agent, PlannerProcessor | Analysis, Visualization 阶段 |
| `analysis_report` | data_analysis_agent, PlannerAnalyzer | Visualization, Summary 阶段 |
| `visualizations` | data_visualization_agent, governance_viz_agent, PlannerVisualizer | Summary 阶段 |
| `final_summary` | data_summary_agent, general_summary_agent | 返回用户 |
| `governance_visualizations` | governance_viz_agent | Report 阶段 |
| `governance_report` | governance_report_agent | Checker 验证 |
| `prepared_data` | DataEngineerAgent (S-5) | Analyst 阶段 |
| `analysis_result` | AnalystAgent (S-5) | Visualizer 阶段 |
| `visualization_output` | VisualizerAgent (S-5) | 返回用户 |
| `rs_analysis` | RemoteSensingAgent (S-5) | Visualizer 阶段 |
| `quality_verdict` | quality_checker_agent | LoopAgent 决策 |
| `gov_quality_verdict` | governance_checker_agent | LoopAgent 决策 |
| `general_quality_verdict` | general_result_checker | LoopAgent 决策 |

**生命周期**: 单次 Pipeline 执行（请求结束即清空）

**访问方式**: 隐式 — ADK 自动将前序 Agent 的 output 注入到后续 Agent 的 context

---

### 1.2 ContextVar — 用户身份与运行时状态传播

**位置**: `data_agent/user_context.py` (38 行)

**机制**: Python `contextvars` 实现线程安全的用户身份与运行时状态传播，所有工具函数通过 `current_user_id.get()` 等获取当前上下文。

**变量清单** (6 个):

| ContextVar | 默认值 | 用途 | 版本 |
|------------|-------|------|------|
| `current_user_id` | `'anonymous'` | 用户 ID — 文件沙箱、DB RLS、记忆隔离 | v12.0 |
| `current_session_id` | `'default'` | 会话 ID — ADK Session 关联 | v12.0 |
| `current_user_role` | `'anonymous'` | 角色 — RBAC 权限控制 | v12.0 |
| `current_trace_id` | `''` | 追踪 ID — 可观测性链路追踪 | v15.0 |
| `current_tool_categories` | `set()` | 工具类别 — Intent Router 输出，动态工具过滤 | v15.8 |
| `current_model_tier` | `'standard'` | 模型层 — fast/standard/premium 路由 | v15.8 |

**辅助函数** (2 个):

| 函数 | 功能 |
|------|------|
| `get_user_upload_dir()` | 返回当前用户的上传目录 `uploads/{user_id}/`，自动创建 |
| `is_path_in_sandbox(path)` | 检查路径是否在用户沙箱或共享上传目录内，防止路径遍历 |

**生命周期**: 单次请求（异步任务上下文）

**访问方式**: 隐式 — 工具函数内部调用 `current_user_id.get()`

---

## Layer 2: 短期记忆 (Session Memory)

### 2.1 上轮上下文 (`last_context`)

**位置**: `app.py:2114`（写入）、`app.py:2764-2775`（注入）

**机制**: 每次 Pipeline 执行后，将管线类型、生成文件、分析摘要存入 Chainlit `user_session`，下次请求时手动注入到 prompt。

**存储结构**:
```python
last_context = {
    "pipeline": "general",
    "files": ["/uploads/user123/result.geojson"],
    "summary": "分析了 5432 个地块，发现 23 处拓扑错误"
}
cl.user_session.set("last_context", last_context)
```

**注入代码** (`app.py:2764-2775`):
```python
last_ctx = cl.user_session.get("last_context")
if last_ctx:
    ctx_block = "\n\n[上轮分析上下文]"
    ctx_block += f"\n上一轮使用了 {last_ctx['pipeline']} 管线。"
    if last_ctx.get("files"):
        ctx_block += "\n上一轮生成的文件："
        for f in last_ctx["files"]:
            ctx_block += f"\n- {f}"
    if last_ctx.get("summary"):
        ctx_block += f"\n分析摘要：{last_ctx['summary']}"
    ctx_block += "\n\n如果用户提到「上面的结果」「刚才的数据」「之前的分析」「继续」等指代词，请使用以上文件路径和上下文。"
    full_prompt += ctx_block
```

**生命周期**: 当前会话（浏览器关闭或会话超时后清空）

**访问方式**: 显式注入到 prompt

---

## Layer 3: 中期记忆 (Cross-session Memory)

### 3.1 对话记忆 (`PostgresMemoryService`)

**位置**: `data_agent/conversation_memory.py` (365 行)

**机制**: ADK 的 `BaseMemoryService` 实现，将对话中的关键片段（Event.content.parts.text）存入 PostgreSQL `memories` 表，支持语义检索和自动注入。

**表结构**:
```sql
CREATE TABLE memories (
    id SERIAL PRIMARY KEY,
    app_name TEXT,
    user_id TEXT,
    content_text TEXT,
    content_hash TEXT UNIQUE,  -- 去重
    session_id TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_memories_user ON memories(app_name, user_id);
```

**ADK 集成**:
```python
from data_agent.conversation_memory import get_memory_service
_memory_svc = get_memory_service()  # PostgresMemoryService or InMemory fallback

runner = Runner(
    agent=selected_agent,
    session_service=_session_svc,
    memory_service=_memory_svc,  # ADK 自动检索相关记忆
    ...
)
```

**检索机制**:
- ADK 调用 `search_memory(query, app_name, user_id)`
- 从 PostgreSQL 取最近 200 条记忆
- 用 Gemini Embedding 计算相似度（中文 n-gram 分词优化）
- 返回 top-K 相关片段，ADK 自动注入到 prompt

**生命周期**: 永久（跨会话、跨设备）

**访问方式**: ADK Runner 自动检索 + 注入

---

### 3.2 Memory ETL — 自动事实提取

**位置**: `memory.py:274-360`

**机制**: 每次 Pipeline 执行后，用 Gemini 2.0 Flash 从报告中提取关键事实（地名、数据集、分析结论），自动保存为 `auto_extract` 类型记忆。

**提取流程**:
```python
# Pipeline 执行完成后
facts = extract_facts_from_conversation(report_text, user_text)
# 返回: [{"key": "福禄镇耕地面积", "value": "1234.5公顷", "category": "data_characteristic"}]
# 每次最多提取 5 条，category: data_characteristic | analysis_conclusion | user_preference

save_auto_extract_memories(facts)
# 存入 user_memories 表，memory_type='auto_extract'
# UPSERT 去重（ON CONFLICT ... DO UPDATE）
```

**配额限制**: 每用户最多 100 条 `auto_extract` 记忆（`AUTO_EXTRACT_QUOTA = 100`）

**生命周期**: 永久

**访问方式**: 通过 `recall_memories(memory_type="auto_extract")` 工具调用

---

## Layer 4: 长期记忆 (Long-term Memory)

### 4.1 空间记忆 (`memory.py`)

**位置**: `data_agent/memory.py` (410 行)

**机制**: 用户显式保存的偏好、区域、分析视角，存入 PostgreSQL `user_memories` 表（JSONB 值）。

**表结构**:
```sql
CREATE TABLE user_memories (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    memory_type VARCHAR(30) NOT NULL,
    memory_key VARCHAR(200) NOT NULL,
    memory_value JSONB NOT NULL,
    description TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(username, memory_type, memory_key)
);
CREATE INDEX idx_user_memories_user ON user_memories (username);
CREATE INDEX idx_user_memories_type ON user_memories (username, memory_type);
```

**记忆类型** (6 种):

| memory_type | 用途 | 版本 |
|-------------|------|------|
| `region` | 用户常分析区域（bbox + CRS） | v12.0 |
| `viz_preference` | 可视化偏好（配色/分级/图例） | v12.0 |
| `analysis_result` | 分析结果记录（文件列表+摘要） | v12.0 |
| `custom` | 用户自定义记忆 | v12.0 |
| `analysis_perspective` | 分析视角（如"关注生态"/"关注经济"），注入 prompt 引导分析方向 | v14.0 |
| `auto_extract` | Pipeline 后自动提取的事实（配额 100 条/用户） | v14.0 |

**工具接口** (`MemoryToolset`, 4 个工具):
```python
save_memory(memory_type, key, value, description)
recall_memories(memory_type="", keyword="")
list_memories()
delete_memory(memory_id)
```

**分析视角注入** (v14.0, `memory.py:247`):
```python
def get_analysis_perspective() -> str:
    """Fetch the current user's analysis perspective text for prompt injection."""
    # 从 user_memories 取 memory_type='analysis_perspective' 最新一条
    # 返回 perspective 字符串，如 "关注土地碎片化对生态连通性的影响"
```

**注入方式** (`app.py:2777-2804`):
```python
from data_agent.memory import get_user_preferences, get_recent_analysis_results, get_analysis_perspective
viz_prefs = get_user_preferences()      # viz_preference 类型
recent_results = get_recent_analysis_results(limit=3)  # analysis_result 类型
perspective = get_analysis_perspective()  # analysis_perspective 类型

if viz_prefs or recent_results or perspective:
    mem_block = "\n\n[用户空间记忆]"
    # ... 拼接偏好、近期分析记录、分析视角
    if perspective:
        mem_block += f"\n\n用户分析视角：{perspective}"
        mem_block += "\n请在分析过程中考虑用户的分析视角和关注点。"
    full_prompt += mem_block
```

**生命周期**: 永久

**访问方式**: 工具调用 + 手动注入 prompt

---

### 4.2 失败学习 (`failure_learning.py`)

**位置**: `data_agent/failure_learning.py` (159 行)

**机制**: 工具执行失败时，记录错误模式和修复提示，下次执行同工具时自动注入提示。

**表结构**:
```sql
CREATE TABLE tool_failures (
    id SERIAL PRIMARY KEY,
    username TEXT,
    tool_name TEXT,
    error_snippet TEXT,
    hint_applied TEXT,
    resolved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
```

**API**:
```python
record_failure(tool_name, error_snippet, hint_applied)
get_failure_hints(tool_name, limit=3)  # 返回最近 3 条未解决的提示
mark_resolved(tool_name)  # 工具成功后标记已解决
```

**集成**: 6 个 Agent 绑定 `_self_correction_after_tool` 回调，工具失败后自动记录并尝试修正。

**生命周期**: 永久（直到 `mark_resolved`）

**访问方式**: 回调自动注入

---

## Layer 5: 永久知识 (Knowledge)

### 5.1 Knowledge Base (RAG + GraphRAG)

**位置**: `data_agent/knowledge_base.py` (1,007 行)

**机制**: 用户上传文档（PDF/TXT/Markdown/Word），系统自动分块、向量化（Gemini text-embedding-004, 768 维），存入 PostgreSQL，支持语义检索 + GraphRAG 图增强检索。

**表结构**:
```sql
CREATE TABLE knowledge_bases (
    id SERIAL PRIMARY KEY,
    name TEXT,
    description TEXT,
    owner_username TEXT,
    is_shared BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE kb_documents (
    id SERIAL PRIMARY KEY,
    kb_id INTEGER REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    filename TEXT,
    content_type TEXT,
    chunk_count INTEGER DEFAULT 0,
    raw_text TEXT,                      -- v15.7: 原始文本存储
    doc_type TEXT DEFAULT 'document',   -- v15.7: 'document' | 'case'
    defect_category TEXT,              -- v15.7: 缺陷类别 (案例库)
    product_type TEXT,                 -- v15.7: 产品类型 (案例库)
    resolution TEXT,                   -- v15.7: 处理方案 (案例库)
    tags JSONB,                        -- v15.7: 标签 (案例库)
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE kb_chunks (
    id SERIAL PRIMARY KEY,
    doc_id INTEGER REFERENCES kb_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER,
    chunk_text TEXT,
    embedding REAL[],  -- 768 维 Gemini embedding
    created_at TIMESTAMP DEFAULT NOW()
);
```

**RAG 工具接口** (`KnowledgeBaseToolset`, 9 个工具):

| 工具 | 功能 | 版本 |
|------|------|------|
| `create_knowledge_base` | 创建知识库 | v12.0 |
| `add_document_to_kb` | 添加文档（自动分块 + 向量化） | v12.0 |
| `search_knowledge_base` | 语义检索（cosine similarity, top-K） | v12.0 |
| `get_kb_context` | 获取 KB 上下文（RAG 增强） | v12.0 |
| `list_knowledge_bases` | 列出知识库 | v12.0 |
| `delete_knowledge_base` | 删除知识库 | v12.0 |
| `graph_rag_search_tool` | GraphRAG 图增强语义搜索 | v14.0 |
| `build_kb_graph_tool` | 从 KB 文档构建实体关系图 | v14.0 |
| `get_kb_entity_graph_tool` | 获取实体关系图（可视化） | v14.0 |

**生命周期**: 永久

**访问方式**: 工具调用（RAG 检索）

---

### 5.2 案例库 (Case Library, v15.7)

**位置**: `knowledge_base.py:878-1007`

**机制**: 基于 KB 文档扩展的结构化质检经验记录，每条案例包含缺陷类别、产品类型、处理方案和标签，支持结构化检索 + 语义混合搜索。

**API**:
```python
add_case(
    kb_id=1,
    title="DLG 拓扑错误批量修复",
    content="发现 23 处多边形重叠...",
    defect_category="TOP",        # FMT/PRE/TOP/MIS/NRM
    product_type="DLG",           # DLG/DOM/DEM/TDOM
    resolution="使用 check_topology + auto_fix_defects 修复",
    tags=["拓扑", "DLG", "批量修复"]
)
# → 存为 doc_type='case' 的 KB 文档

search_cases(
    query="拓扑错误修复",
    defect_category="TOP",
    product_type="DLG",
    top_k=10
)
# → 结构化过滤 + 语义搜索混合排序

list_cases(kb_id=1)
# → search_cases(kb_id=1, top_k=100)
```

**生命周期**: 永久

**访问方式**: 工具调用（`KnowledgeBaseToolset`）

---

### 5.3 Knowledge Graph

**位置**: `data_agent/knowledge_graph.py` (706 行)

**机制**: 从 GeoDataFrame 自动提取地理实体（8 种类型：parcel, building, road, water, admin, vegetation, poi, data_asset）和关系（7 种：contains, within, adjacent_to, overlaps, nearest_to, derives_from, feeds_into），构建 NetworkX 图，支持图查询。

**v12.1+ 增强**:

| 功能 | 方法 | 说明 |
|------|------|------|
| 数据血缘边 | `add_lineage_edge(source_id, target_id, tool_name)` | `derives_from` / `feeds_into` 关系 |
| 数据资产注册 | `register_catalog_assets(assets)` | 从 data_catalog 注册 `data_asset` 类型节点 |
| 关联资产发现 | `discover_related_assets(asset_id, depth=2)` | BFS 搜索关联资产 |

**存储**: 内存（NetworkX DiGraph）+ PostgreSQL 持久化（`agent_knowledge_graphs` 表）

**工具接口** (`KnowledgeGraphToolset`, 3 个工具):
```python
build_knowledge_graph(gdf)
query_knowledge_graph(entity_name)
export_knowledge_graph()
```

**生命周期**: 会话内（内存）或永久（持久化）

**访问方式**: 工具调用

---

## 跨切面: ContextEngine (v19.0 统一上下文引擎)

**位置**: `data_agent/context_engine.py` (583 行)

> 替代 v15.8 的 `context_manager.py` (59 行)，从单一 SemanticProvider 扩展为 6 个内置 Provider + 查询 embedding 相关性排序 + TTL 缓存。

**架构**:
```
ContextProvider (ABC)
├── SemanticLayerProvider     — 包装 semantic_layer.resolve_semantic_context()
├── KnowledgeBaseProvider     — 包装 knowledge_base.search_knowledge_base()
├── KnowledgeGraphProvider    — 包装 knowledge_graph.query_knowledge_graph()
├── ReferenceQueryProvider    — 包装 reference_queries.ReferenceQueryStore.search()
├── SuccessStoryProvider      — 包装 feedback.FeedbackStore.get_positive_examples()
├── MetricDefinitionProvider  — 包装 semantic_model.SemanticModelStore.search()
└── [自定义 Provider]         — 用户可注册任意 ContextProvider

ContextEngine (singleton via get_context_engine())
├── register_provider(name, provider)
├── get_context(query, task_type, user_context) → list[ContextBlock]
└── format_context(blocks) → str
```

**核心数据结构**:
```python
@dataclass
class ContextBlock:
    provider: str           # Provider 名称（如 "semantic_layer"）
    source: str             # 来源标识
    content: str            # 上下文内容
    token_count: int        # 估算 token 数（len(content) // 4）
    relevance_score: float  # 相关性分数（0-1）
    compressible: bool      # 是否可压缩（True = 预算不足时可丢弃）
    metadata: dict          # 附加元数据
```

**执行流程**:
1. 收集所有 Provider 的 ContextBlock（per-provider 错误隔离，单个 Provider 失败不影响其他）
2. 按 `relevance_score` 降序排列
3. 贪心填充直到 `max_tokens` (默认 100,000) 耗尽
4. TTL 缓存 (3 分钟)：相同 query + task_type 组合命中缓存
5. `format_context()` 输出为 `[provider:source]\ncontent\n` 格式

**REST API**:
- `GET /api/context/preview` — 预览当前任务的上下文块

**生命周期**: 单次请求

**访问方式**: Pipeline 执行前由 `get_context()` 组装

---

## 跨切面: FeedbackLoop (v19.0 反馈飞轮)

**位置**: `data_agent/feedback.py` (368 行)

**机制**: 结构化反馈闭环，将用户对 Agent 响应的评价转化为系统改进。

**表结构**:
```sql
CREATE TABLE agent_feedback (
    id SERIAL PRIMARY KEY,
    username TEXT,
    session_id TEXT,
    message_id TEXT,
    pipeline_type TEXT,
    query_text TEXT,
    response_text TEXT,
    vote INTEGER,              -- +1 (upvote) / -1 (downvote)
    issue_description TEXT,
    issue_tags JSONB,
    context_snapshot JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

**反馈处理流程**:
```
用户点击 👍 (FeedbackBar.tsx)
    ↓ POST /api/feedback
    ↓ FeedbackStore.record(vote=+1)
    ↓ FeedbackProcessor.process_upvote()
    ↓ ReferenceQueryStore.add(query, source="feedback")
    → 成功查询自动入库参考查询库 → 后续 NL2SQL few-shot 注入

用户点击 👎 (FeedbackBar.tsx)
    ↓ POST /api/feedback
    ↓ FeedbackStore.record(vote=-1)
    ↓ FeedbackProcessor.process_downvote()
    ↓ FailureAnalyzer.analyze(query, response)
    → 失败模式分析 → PromptOptimizer 改进建议
```

**前端组件**:
- `FeedbackBar.tsx`: 每条 Agent 消息下方的 👍👎 按钮 + 可选文本反馈
- `FeedbackTab.tsx` (DataPanel): 反馈看板 — 统计、趋势、详情列表

**REST API** (`feedback_routes.py`, 5 端点):
- `POST /api/feedback` — 提交反馈
- `GET /api/feedback` — 查询反馈列表
- `GET /api/feedback/stats` — 反馈统计
- `GET /api/feedback/{id}` — 反馈详情
- `DELETE /api/feedback/{id}` — 删除反馈

**生命周期**: 永久

**访问方式**: 前端 UI + REST API

---

## 跨切面: ReferenceQueryStore (v19.0 参考查询库)

**位置**: `data_agent/reference_queries.py` (395 行)

**机制**: 经过验证的成功查询库，为 NL2SQL 提供 few-shot 示例注入。支持 embedding 语义搜索 + 自动/手动策展。

**表结构**:
```sql
CREATE TABLE agent_reference_queries (
    id SERIAL PRIMARY KEY,
    query_text TEXT NOT NULL,
    description TEXT,
    response_summary TEXT,
    tags JSONB,
    pipeline_type TEXT,
    task_type TEXT,
    source TEXT DEFAULT 'manual',    -- 'manual' | 'feedback' | 'auto'
    feedback_id INTEGER,
    embedding REAL[],                -- Gemini embedding (768 维)
    created_by TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

**API**:
```python
store = ReferenceQueryStore()
store.add(query_text, description, tags, source="feedback")
store.search(query, top_k=5)  # embedding cosine similarity
store.list(pipeline_type=None, limit=50)
store.delete(query_id)
```

**去重**: 新增时自动计算 embedding，cosine > 0.92 的相似查询跳过入库。

**ContextEngine 集成**: `ReferenceQueryProvider` 将 top-K 参考查询注入到 Agent prompt，提供 few-shot 示例。

**REST API** (`reference_query_routes.py`, 6 端点):
- CRUD + 搜索 + 批量导入

**生命周期**: 永久

**访问方式**: ContextEngine 自动注入 + REST API 手动管理

---

## 跨切面: MetricFlow 语义模型 (v19.0)

**位置**: `data_agent/semantic_model.py` (338 行)

**机制**: GIS 扩展的 MetricFlow 兼容语义模型定义。支持 YAML 格式的指标定义、维度声明（含 `spatial` 维度类型）、计算公式。

**表结构**:
```sql
CREATE TABLE agent_semantic_models (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    yaml_definition TEXT,
    parsed_entities JSONB,
    parsed_dimensions JSONB,
    parsed_measures JSONB,
    parsed_metrics JSONB,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

**YAML 格式** (GIS 扩展):
```yaml
name: land_use_analysis
dimensions:
  - name: district
    type: categorical
  - name: geometry
    type: spatial          # GIS 扩展: 空间维度
measures:
  - name: total_area
    agg: sum
    expr: ST_Area(geometry)  # PostGIS 表达式
metrics:
  - name: avg_parcel_area
    type: derived
    expr: total_area / parcel_count
```

**PostGIS 自动生成**: 从 PostGIS 表结构自动推导语义模型定义。

**ContextEngine 集成**: `MetricDefinitionProvider` 将指标定义注入到 Agent prompt，帮助 Agent 理解业务指标含义。

**REST API** (`semantic_model_routes.py`, 5 端点):
- CRUD + YAML 导入 + PostGIS 自动生成

**生命周期**: 永久

**访问方式**: ContextEngine 自动注入 + REST API 管理

---

## 跨切面: PromptOptimizer (v23.0)

**位置**: `data_agent/prompt_optimizer.py` (436 行)

**机制**: 基于反馈数据的提示词自动优化。从 `agent_feedback` 表收集负反馈，分析失败模式，生成 prompt 改进建议。

**流程**:
```
agent_feedback (vote=-1) → 收集 bad cases
    ↓ FailureAnalyzer.analyze()
    ↓ 分类失败模式 (工具选择错误 / 参数错误 / 幻觉 / 格式错误)
    ↓ PromptOptimizer.suggest_improvements()
    → 生成 prompt 改进建议 (可人工审核后应用)
```

**生命周期**: 永久（改进建议持久化）

**访问方式**: 管理员 API 调用

---

## 跨切面: Eval Scenario Framework (v15.8)

**位置**: `data_agent/eval_scenario.py` (130 行)

**机制**: 场景化评估框架，为不同任务类型（如测绘质检）定义专属评估指标和黄金测试集。

**架构**:
```python
class EvalScenario(ABC):
    @abstractmethod
    def evaluate(self, result, expected) -> dict: ...

class SurveyingQCScenario(EvalScenario):
    """测绘质检专用评估"""
    # 指标: defect_precision, defect_recall, defect_f1, fix_success_rate

class EvalDatasetManager:
    """黄金测试集管理"""
    # 表: agent_eval_datasets
    # CRUD: add_dataset(), get_dataset(), list_datasets()
```

**表结构**:
```sql
CREATE TABLE agent_eval_datasets (
    id SERIAL PRIMARY KEY,
    scenario TEXT,
    name TEXT,
    input_data JSONB,
    expected_output JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

**REST API** (v15.8):
- `POST /api/eval/datasets` — 添加测试集
- `POST /api/eval/run` — 运行评估
- `GET /api/eval/scenarios` — 列出可用场景

---

## 记忆注入流程（v23.0 完整示例）

```
用户消息到达: "继续分析福禄镇的耕地，用上次的配色方案"
    │
    ├── 0. 多模态上下文（如有图片/PDF）
    │     → "[多模态上下文] 用户附带了 N 张图片"
    │     → "[PDF文档内容摘要] ..."
    │
    ├── 1. 注入上轮上下文 (Layer 2: last_context)
    │     → "[上轮分析上下文]
    │        上一轮使用了 general 管线。
    │        上一轮生成的文件: - /uploads/user123/parcels.geojson
    │        分析摘要：分析了 5432 个地块，发现 23 处拓扑错误"
    │
    ├── 2. 注入空间记忆 (Layer 4: memory.py)
    │     → "[用户空间记忆]
    │        可视化偏好: choropleth_colors: YlOrRd, 5 bins
    │        近期分析记录: 福禄镇耕地分析 (文件: result.geojson)
    │        用户分析视角: 关注土地碎片化对生态连通性的影响"
    │
    ├── 3. ContextEngine 统一上下文注入 (v19.0)
    │     → get_context_engine().get_context("福禄镇 耕地", task_type="analysis")
    │     → SemanticLayerProvider: "字段名映射: 耕地面积 → GDMJ, 地块编号 → DKBH"
    │     → ReferenceQueryProvider: "参考查询: SELECT ... FROM dltb WHERE ..."
    │     → MetricDefinitionProvider: "指标: 耕地破碎度 = 地块数/总面积"
    │     → KnowledgeBaseProvider: "相关文档: 福禄镇土地利用现状..."
    │     → SuccessStoryProvider: "历史成功案例: 类似分析的成功查询..."
    │     → 按 relevance_score 排序 → token budget 裁剪 → 注入 prompt
    │
    ├── 4. 注入 ArcPy 引擎上下文（如可用）
    │     → "[系统环境] ArcPy 引擎可用..."
    │
    ├── 5. 语言提示注入
    │     → "[Language] Please respond in English."（非中文时）
    │
    ├── 6. ADK 自动检索对话记忆 (Layer 3: PostgresMemoryService)
    │     → Runner 调用 memory_service.search_memory("福禄镇 耕地", ...)
    │     → 返回历史分析片段: "福禄镇位于 XX 县，总面积 1234.5 公顷..."
    │     → ADK 自动注入到 prompt
    │
    ▼
    拼接后的 full_prompt → 意图路由 → Pipeline 执行
    │
    ├── Agent A (output_key="data_profile") → Layer 1 状态传递
    ├── Agent B (继承 data_profile) → Layer 1 状态传递
    └── Agent C (继承 data_profile + processed_data)
    │
    ▼
    Pipeline 执行完成
    │
    ├── 保存 last_context (Layer 2)
    ├── Memory ETL 自动提取事实 (Layer 3→4)
    ├── 工具成功 → mark_resolved (Layer 4)
    └── 用户反馈 → FeedbackLoop (v19.0)
          ├── 👍 → ReferenceQueryStore 自动入库 (L5)
          └── 👎 → FailureAnalyzer → PromptOptimizer
```

---

## 语义层缓存 (Layer 5 辅助)

**位置**: `data_agent/semantic_layer.py` (1,847 行)

**机制**: 语义元数据 3 级层次结构（domain → table → column），5 分钟 TTL 缓存，写操作自动失效。

| 特性 | 值 |
|------|---|
| 缓存 TTL | 300 秒（`_CACHE_TTL = 300`） |
| 失效触发 | `register_semantic_annotation()`, `register_source_metadata()` 等写操作调用 `invalidate_semantic_cache()` |
| 可观测性 | cache hit/miss 指标上报到 Prometheus |

---

## 记忆体系对比表

| 层 | 机制 | 存储 | 生命周期 | 范围 | 访问方式 | 代码位置 |
|----|------|------|---------|------|---------|---------|
| **L1 即时** | `output_key` | ADK session state | 单次请求 | 单 Pipeline | 隐式（ADK 自动） | `agent.py` |
| | ContextVar (6 个) | 内存 | 单次请求 | 单请求 | 隐式（工具内部） | `user_context.py` (37 行) |
| **L2 短期** | `last_context` | Chainlit user_session | 当前会话 | 单会话 | 显式注入 prompt | `app.py` |
| **L3 中期** | PostgresMemoryService | PostgreSQL `memories` | 永久 | per-user | ADK 自动检索 | `conversation_memory.py` (364 行) |
| | Memory ETL | PostgreSQL `user_memories` | 永久 | per-user | 工具调用 | `memory.py:274` |
| **L4 长期** | 空间记忆 (6 种类型) | PostgreSQL `user_memories` | 永久 | per-user | 工具调用 + 注入 | `memory.py` (409 行) |
| | 分析视角 | PostgreSQL `user_memories` | 永久 | per-user | 自动注入 prompt | `memory.py:247` |
| | 失败学习 | PostgreSQL `tool_failures` | 永久（可标记已解决） | per-user | 回调自动注入 | `failure_learning.py` (158 行) |
| **L5 知识** | Knowledge Base (RAG) | PostgreSQL + pgvector | 永久 | per-user + 共享 | 工具调用 | `knowledge_base.py` (1,006 行) |
| | GraphRAG | PostgreSQL | 永久 | per-KB | 工具调用 | `graph_rag.py` (507 行) |
| | 案例库 (Case Library) | PostgreSQL `kb_documents` | 永久 | per-KB | 工具调用 | `knowledge_base.py:878` |
| | Knowledge Graph | 内存 (NetworkX) + PostgreSQL | 会话/永久 | per-session | 工具调用 | `knowledge_graph.py` (705 行) |
| | 语义层 | PostgreSQL + 内存缓存 | 永久 (5min TTL cache) | 全局 | 自动注入 prompt | `semantic_layer.py` (1,847 行) |
| | 参考查询库 | PostgreSQL + embedding | 永久 | 全局 | ContextEngine 自动注入 | `reference_queries.py` (395 行) |
| | 语义模型 | PostgreSQL | 永久 | 全局 | ContextEngine 自动注入 | `semantic_model.py` (338 行) |
| **跨切面** | ContextEngine | 内存 (3min TTL) | 单次请求 | per-task | get_context() 组装 | `context_engine.py` (583 行) |
| | FeedbackLoop | PostgreSQL `agent_feedback` | 永久 | per-user | 前端 UI + API | `feedback.py` (368 行) |
| | ReferenceQueryStore | PostgreSQL + embedding | 永久 | 全局 | ContextEngine + API | `reference_queries.py` (395 行) |
| | PromptOptimizer | PostgreSQL | 永久 | 全局 | 管理员 API | `prompt_optimizer.py` (436 行) |
| | Eval Scenario | PostgreSQL `agent_eval_datasets` | 永久 | per-scenario | API 调用 | `eval_scenario.py` (130 行) |

---

## 记忆工具清单

| 工具名 | 所属 Toolset | 所属层 | 功能 | 代码位置 |
|-------|------------|-------|------|---------|
| `save_memory` | MemoryToolset | L4 | 保存用户偏好/区域/视角 | `memory.py` |
| `recall_memories` | MemoryToolset | L4 | 检索记忆（按类型/关键词） | `memory.py` |
| `list_memories` | MemoryToolset | L4 | 列出所有记忆 | `memory.py` |
| `delete_memory` | MemoryToolset | L4 | 删除指定记忆 | `memory.py` |
| `create_knowledge_base` | KnowledgeBaseToolset | L5 | 创建知识库 | `knowledge_base.py` |
| `add_document_to_kb` | KnowledgeBaseToolset | L5 | 添加文档（自动分块+向量化） | `knowledge_base.py` |
| `search_knowledge_base` | KnowledgeBaseToolset | L5 | 语义检索知识库 | `knowledge_base.py` |
| `get_kb_context` | KnowledgeBaseToolset | L5 | 获取 KB 上下文（RAG） | `knowledge_base.py` |
| `list_knowledge_bases` | KnowledgeBaseToolset | L5 | 列出知识库 | `knowledge_base.py` |
| `delete_knowledge_base` | KnowledgeBaseToolset | L5 | 删除知识库 | `knowledge_base.py` |
| `graph_rag_search_tool` | KnowledgeBaseToolset | L5 | GraphRAG 图增强搜索 | `knowledge_base.py:847` |
| `build_kb_graph_tool` | KnowledgeBaseToolset | L5 | 构建实体图谱 | `knowledge_base.py:831` |
| `get_kb_entity_graph_tool` | KnowledgeBaseToolset | L5 | 获取实体关系图 | `knowledge_base.py` |
| `build_knowledge_graph` | KnowledgeGraphToolset | L5 | 构建地理知识图谱 | `knowledge_graph.py` |
| `query_knowledge_graph` | KnowledgeGraphToolset | L5 | 查询图谱实体 | `knowledge_graph.py` |
| `export_knowledge_graph` | KnowledgeGraphToolset | L5 | 导出图谱 | `knowledge_graph.py` |

---

## v12.0 → v23.0 变更摘要

| 版本 | 变更 | 影响层 |
|------|------|-------|
| v14.0 | 新增 `analysis_perspective` / `auto_extract` 记忆类型 | L4 |
| v14.0 | `get_analysis_perspective()` 自动注入 prompt | L4 |
| v14.0 | GraphRAG 图增强搜索（`graph_rag_search`, `build_kb_graph`） | L5 |
| v14.0 | Memory ETL — `extract_facts_from_conversation()` + `save_auto_extract_memories()` | L3→L4 |
| v15.0 | `current_trace_id` ContextVar（可观测性链路追踪） | L1 |
| v15.7 | 案例库（`add_case`, `search_cases`, `list_cases`）— 质检经验记录 | L5 |
| v15.7 | `kb_documents` 表增加 `doc_type`, `defect_category`, `product_type`, `resolution`, `tags` 列 | L5 |
| v15.7 | Knowledge Graph 增加 `add_lineage_edge`, `register_catalog_assets`, `discover_related_assets` | L5 |
| v15.8 | `current_tool_categories` / `current_model_tier` ContextVar | L1 |
| v15.8 | `is_path_in_sandbox()` 安全函数 | L1 |
| v15.8 | Context Manager — 可插拔 Provider + token budget (100k) | 跨切面 |
| v15.8 | Eval Scenario Framework — `SurveyingQCScenario` + `EvalDatasetManager` | 跨切面 |
| **v19.0** | **ContextEngine 统一上下文引擎** — 6 Provider + TTL 缓存 + 查询 embedding 排序 (替代 context_manager.py) | 跨切面 |
| **v19.0** | **FeedbackLoop 反馈飞轮** — 👍👎 + FeedbackStore + FeedbackProcessor | 跨切面 |
| **v19.0** | **ReferenceQueryStore 参考查询库** — embedding 搜索 + NL2SQL few-shot + 自动策展 | L5 + 跨切面 |
| **v19.0** | **MetricFlow 语义模型** — GIS 扩展 YAML + PostGIS 自动生成 + MetricDefinitionProvider | L5 + 跨切面 |
| **v19.0** | `agent_feedback` / `agent_reference_queries` / `agent_semantic_models` 3 张新表 | L5 |
| **v19.0** | 前端 `FeedbackBar.tsx` + `FeedbackTab.tsx` | 跨切面 |
| **v23.0** | **PromptOptimizer** — bad case 收集 + 失败分析 + prompt 自动改进 | 跨切面 |
| **v23.0** | **EvaluatorRegistry** — 15 内置评估器 (质量/安全/性能/准确性) | 跨切面 |

---

## 设计原则

1. **分层隔离**：不同生命周期的记忆使用不同机制，避免混淆
2. **自动 + 手动**：L1-L3 自动注入（用户无感），L4-L5 工具调用（用户可控）
3. **去重 + 配额**：Memory ETL 用 UPSERT 去重，auto_extract 限额 100 条/用户；ReferenceQueryStore cosine > 0.92 去重
4. **降级策略**：PostgresMemoryService 不可用时自动降级到 InMemoryMemoryService
5. **隐私隔离**：所有记忆按 `username` 隔离，RLS 策略强制执行
6. **Token 预算**：ContextEngine 通过 relevance_score 排序 + 贪心填充控制 prompt 大小 (100k 上限)
7. **可插拔扩展**：ContextProvider ABC 允许注册自定义上下文源（v19.0 已内置 6 个 Provider）
8. **安全边界**：`is_path_in_sandbox()` 防止工具函数读取沙箱外文件
9. **反馈闭环**：用户 👍→参考查询自动入库→NL2SQL 精度提升；👎→失败分析→prompt 优化（v19.0）
10. **越用越准**：ContextEngine + FeedbackLoop + ReferenceQueryStore 构成"上下文飞轮"，使用越多、上下文越精准

---

*本文档基于 GIS Data Agent v23.0 (ADK v1.27.2) 的源码精确同步，2026-04-10。*
