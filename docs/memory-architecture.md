# Data Agent 记忆体系架构

> GIS Data Agent 的五层记忆体系：从即时状态传递到永久知识库，实现跨请求、跨会话、跨用户的智能记忆。

---

## 五层记忆架构

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 5: 永久知识 (Knowledge)                               │
│  Knowledge Base (RAG) + 知识图谱 — 文档/实体/关系              │
│  生命周期: 永久 | 存储: PostgreSQL | 范围: per-user + 共享     │
├─────────────────────────────────────────────────────────────┤
│  Layer 4: 长期记忆 (Long-term Memory)                        │
│  空间记忆 (memory.py) — 区域偏好/可视化偏好/分析视角           │
│  失败学习 (failure_learning.py) — 工具失败模式 + 修复提示       │
│  生命周期: 永久 | 存储: PostgreSQL | 范围: per-user            │
├─────────────────────────────────────────────────────────────┤
│  Layer 3: 中期记忆 (Cross-session Memory)                    │
│  对话记忆 (conversation_memory.py) — 历史分析片段 + Memory ETL │
│  生命周期: 永久 | 存储: PostgreSQL | 范围: per-user            │
│  ADK Runner 自动检索相关历史，注入到当前 prompt                 │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: 短期记忆 (Session Memory)                          │
│  上轮上下文 (last_context) — 上一轮管线/文件/摘要              │
│  生命周期: 当前会话 | 存储: Chainlit user_session | 范围: 单会话 │
│  手动注入到 prompt: "上一轮使用了 X 管线，生成了 Y 文件"         │
├─────────────────────────────────────────────────────────────┤
│  Layer 1: 即时状态 (Immediate State)                         │
│  Agent output_key — Pipeline 内 Agent 间状态传递              │
│  ContextVar (user_context.py) — 用户身份/角色/会话 ID 传播     │
│  生命周期: 单次请求 | 存储: 内存 | 范围: 单次 Pipeline 执行     │
└─────────────────────────────────────────────────────────────┘
```

---

## Layer 1: 即时状态 (Immediate State)

### 1.1 Agent `output_key` — Pipeline 内状态传递

**位置**: ADK Agent 配置，`agent.py` 中定义

**机制**: SequentialAgent 中的每个 LlmAgent 通过 `output_key` 将输出写入 session state，下游 Agent 自动继承。

**示例**:
```python
# agent.py
SequentialAgent(
    name="OptimizationPipeline",
    agents=[
        LlmAgent(name="DataAudit", output_key="data_profile", ...),
        LlmAgent(name="Processing", output_key="processed_data", ...),
        LlmAgent(name="Analysis", output_key="analysis_report", ...),
    ]
)
```

**生命周期**: 单次 Pipeline 执行（请求结束即清空）

**访问方式**: 隐式 — ADK 自动将前序 Agent 的 output 注入到后续 Agent 的 context

---

### 1.2 ContextVar — 用户身份传播

**位置**: `data_agent/user_context.py` (36 行)

**机制**: Python `contextvars` 实现线程安全的用户身份传播，所有工具函数通过 `current_user_id.get()` 获取当前用户。

**代码**:
```python
# user_context.py
from contextvars import ContextVar

current_user_id: ContextVar[str] = ContextVar("current_user_id", default="")
current_session_id: ContextVar[str] = ContextVar("current_session_id", default="")
current_user_role: ContextVar[str] = ContextVar("current_user_role", default="analyst")
```

**生命周期**: 单次请求（异步任务上下文）

**访问方式**: 隐式 — 工具函数内部调用 `current_user_id.get()`

---

## Layer 2: 短期记忆 (Session Memory)

### 2.1 上轮上下文 (`last_context`)

**位置**: `app.py:2439-2451`

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

**注入示例** (`app.py:2442-2451`):
```python
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

**ADK 集成** (`app.py:1539-1554`):
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

**检索机制** (`conversation_memory.py:211-270`):
- ADK 调用 `search_memory(query, app_name, user_id)`
- 从 PostgreSQL 取最近 200 条记忆
- 用 Gemini Embedding 计算相似度
- 返回 top-K 相关片段，ADK 自动注入到 prompt

**生命周期**: 永久（跨会话、跨设备）

**访问方式**: ADK Runner 自动检索 + 注入

---

### 3.2 Memory ETL — 自动事实提取

**位置**: `app.py:1983-2001`, `memory.py:274-325`

**机制**: 每次 Pipeline 执行后，用 Gemini 2.0 Flash 从报告中提取关键事实（地名、数据集、分析结论），自动保存为 `auto_extract` 类型记忆。

**提取流程**:
```python
# app.py:1987-1995
facts = extract_facts_from_conversation(report_text, user_text)
# 返回: [{"key": "福禄镇耕地面积", "value": "1234.5公顷", "category": "数据统计"}]

save_auto_extract_memories(facts)
# 存入 user_memories 表，memory_type='auto_extract'
```

**配额限制**: 每用户最多 100 条 `auto_extract` 记忆（防止爆炸）

**生命周期**: 永久

**访问方式**: 通过 `recall_memories(memory_type="auto_extract")` 工具调用

---

## Layer 4: 长期记忆 (Long-term Memory)

### 4.1 空间记忆 (`memory.py`)

**位置**: `data_agent/memory.py` (409 行)

**机制**: 用户显式保存的偏好、区域、分析视角，存入 PostgreSQL `user_memories` 表（JSONB 值）。

**表结构**:
```sql
CREATE TABLE user_memories (
    id SERIAL PRIMARY KEY,
    username TEXT,
    memory_type TEXT,  -- region / viz_preference / analysis_result / analysis_perspective / auto_extract / custom
    memory_key TEXT,
    memory_value JSONB,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(username, memory_type, memory_key)
);
```

**工具接口** (`memory.py`):
```python
save_memory(memory_type, key, value, description)
recall_memories(memory_type="", keyword="")
list_memories()
delete_memory(memory_id)
```

**使用示例**:
```python
# 保存用户偏好区域
save_memory(
    memory_type="region",
    key="福禄镇",
    value={"bbox": [120.1, 30.2, 120.3, 30.4], "crs": "EPSG:4326"},
    description="用户常分析的区域"
)

# 保存可视化偏好
save_memory(
    memory_type="viz_preference",
    key="choropleth_colors",
    value={"scheme": "YlOrRd", "bins": 5},
    description="用户偏好的分级设色方案"
)
```

**注入方式** (`app.py:2454-2470`):
```python
from data_agent.memory import get_user_preferences, get_recent_analysis_results
prefs = get_user_preferences()  # 取 viz_preference 类型记忆
results = get_recent_analysis_results(limit=3)  # 取 analysis_result 类型记忆
# 手动拼接到 prompt
```

**生命周期**: 永久

**访问方式**: 工具调用 + 手动注入

---

### 4.2 失败学习 (`failure_learning.py`)

**位置**: `data_agent/failure_learning.py` (158 行)

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

**集成示例** (`GISToolRetryPlugin`):
```python
# 工具失败时
record_failure("query_database", "字段名不存在", "建议使用语义层映射")

# 下次执行前
hints = get_failure_hints("query_database")
# 返回: ["建议使用语义层映射", "检查表名大小写"]
# 注入到工具的 instruction
```

**生命周期**: 永久（直到 `mark_resolved`）

**访问方式**: Plugin 自动注入

---

## Layer 5: 永久知识 (Knowledge)

### 5.1 Knowledge Base (RAG)

**位置**: `data_agent/knowledge_base.py` (1057 行)

**机制**: 用户上传文档（PDF/TXT/Markdown），系统自动分块、向量化（Gemini Embedding），存入 PostgreSQL，支持语义检索。

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
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE kb_chunks (
    id SERIAL PRIMARY KEY,
    doc_id INTEGER REFERENCES kb_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER,
    chunk_text TEXT,
    embedding VECTOR(768),  -- pgvector
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_kb_chunks_embedding ON kb_chunks USING ivfflat (embedding vector_cosine_ops);
```

**工具接口**:
```python
search_knowledge_base(query, kb_ids=[], top_k=5)
# 返回: [{"text": "...", "score": 0.85, "source": "doc.pdf"}]
```

**生命周期**: 永久

**访问方式**: 工具调用（RAG 检索）

---

### 5.2 Knowledge Graph

**位置**: `data_agent/knowledge_graph.py` (625 行)

**机制**: 从 GeoDataFrame 自动提取地理实体（地名、行政区划）和关系（邻接、包含），构建 NetworkX 图，支持图查询。

**存储**: 内存（NetworkX Graph 对象）+ 可选持久化到 GraphML

**工具接口**:
```python
build_knowledge_graph(gdf)
query_knowledge_graph(entity_name)
find_related_entities(entity_name, relation_type)
```

**生命周期**: 会话内（内存）或永久（持久化）

**访问方式**: 工具调用

---

## 记忆注入流程（完整示例）

```
用户消息到达: "继续分析福禄镇的耕地，用上次的配色方案"
    │
    ├── 1. 注入上轮上下文 (Layer 2: last_context)
    │     "[上轮分析上下文]
    │      上一轮使用了 general 管线。
    │      上一轮生成的文件:
    │      - /uploads/user123/fuluzhen_parcels.geojson
    │      分析摘要：分析了 5432 个地块，发现 23 处拓扑错误"
    │
    ├── 2. 注入空间记忆 (Layer 4: memory.py)
    │     from data_agent.memory import get_user_preferences
    │     prefs = get_user_preferences()
    │     → "[用户偏好] 分级设色方案: YlOrRd, 5 bins"
    │
    ├── 3. 注入语义层映射 (Layer 5: semantic_layer.py)
    │     → "字段名映射: 耕地面积 → GDMJ, 地块编号 → DKBH"
    │
    ├── 4. 注入失败提示 (Layer 4: failure_learning.py)
    │     hints = get_failure_hints("query_database")
    │     → "上次 query_database 失败：建议使用语义层映射"
    │
    ├── 5. ADK 自动检索对话记忆 (Layer 3: PostgresMemoryService)
    │     Runner 调用 memory_service.search_memory("福禄镇 耕地", ...)
    │     → 返回历史分析片段:
    │       "福禄镇位于 XX 县，总面积 1234.5 公顷..."
    │     → ADK 自动注入到 prompt
    │
    ▼
    拼接后的 full_prompt → 送入 Pipeline 执行
    │
    ├── Agent A (output_key="data_profile") → Layer 1 状态传递
    ├── Agent B (继承 data_profile) → Layer 1 状态传递
    └── Agent C (继承 data_profile + processed_data)
    │
    ▼
    Pipeline 执行完成
    │
    ├── 保存 last_context (Layer 2)
    ├── Memory ETL 自动提取事实 (Layer 3)
    └── 工具成功 → mark_resolved (Layer 4)
```

---

## 记忆体系对比表

| 层 | 机制 | 存储 | 生命周期 | 范围 | 访问方式 | 代码位置 |
|----|------|------|---------|------|---------|---------|
| **L1 即时** | `output_key` | ADK session state | 单次请求 | 单 Pipeline | 隐式（ADK 自动） | `agent.py` |
| | ContextVar | 内存 | 单次请求 | 单请求 | 隐式（工具内部） | `user_context.py` |
| **L2 短期** | `last_context` | Chainlit user_session | 当前会话 | 单会话 | 显式注入 prompt | `app.py:2439` |
| **L3 中期** | PostgresMemoryService | PostgreSQL `memories` | 永久 | per-user | ADK 自动检索 | `conversation_memory.py` |
| | Memory ETL | PostgreSQL `user_memories` | 永久 | per-user | 工具调用 | `memory.py:274` |
| **L4 长期** | 空间记忆 | PostgreSQL `user_memories` | 永久 | per-user | 工具调用 + 注入 | `memory.py` |
| | 失败学习 | PostgreSQL `tool_failures` | 永久（可标记已解决） | per-user | Plugin 自动注入 | `failure_learning.py` |
| **L5 知识** | Knowledge Base | PostgreSQL + pgvector | 永久 | per-user + 共享 | 工具调用（RAG） | `knowledge_base.py` |
| | Knowledge Graph | 内存 (NetworkX) | 会话内 / 永久 | per-session | 工具调用 | `knowledge_graph.py` |

---

## 记忆工具清单

| 工具名 | 所属层 | 功能 | 代码位置 |
|-------|-------|------|---------|
| `save_memory` | L4 | 保存用户偏好/区域/视角 | `memory.py:51` |
| `recall_memories` | L4 | 检索记忆（按类型/关键词） | `memory.py:92` |
| `list_memories` | L4 | 列出所有记忆 | `memory.py:145` |
| `delete_memory` | L4 | 删除指定记忆 | `memory.py:154` |
| `search_knowledge_base` | L5 | 语义检索知识库 | `knowledge_base.py` |
| `build_knowledge_graph` | L5 | 构建地理知识图谱 | `knowledge_graph.py` |
| `query_knowledge_graph` | L5 | 查询图谱实体 | `knowledge_graph.py` |

---

## 设计原则

1. **分层隔离**：不同生命周期的记忆使用不同机制，避免混淆
2. **自动 + 手动**：L1-L3 自动注入（用户无感），L4-L5 工具调用（用户可控）
3. **去重 + 配额**：Memory ETL 用 content_hash 去重，auto_extract 限额 100 条/用户
4. **降级策略**：PostgresMemoryService 不可用时自动降级到 InMemoryMemoryService
5. **隐私隔离**：所有记忆按 `username` 隔离，RLS 策略强制执行

---

*本文档基于 GIS Data Agent v12.0 (ADK v1.27.2) 架构编写。*
