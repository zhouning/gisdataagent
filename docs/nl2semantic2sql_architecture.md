# NL2Semantic2SQL 技术架构文档

> **版本**: v24.1 | **验证状态**: Benchmark 16/16 全量通过 | **最后更新**: 2026-04-30

## 1. 系统概述

NL2Semantic2SQL 是 GIS Data Agent 平台中的自然语言到 SQL 翻译子系统。它将用户的中文自然语言问题转换为可执行的 PostgreSQL/PostGIS 空间查询，核心设计原则是**语义优先、schema 驱动、安全兜底**。

与传统 NL2SQL 方案（直接让 LLM 生成 SQL）不同，本系统在 LLM 介入前先完成一轮完整的语义解析和 schema grounding，将"用户说了什么"翻译成"数据库里有什么能回答这个问题"，再把这份结构化上下文交给 LLM 做最后的 SQL 组装。

**核心指标**：
- Benchmark 16 题全量通过（4 Easy + 4 Medium + 4 Hard + 4 Robustness）
- 简单查询端到端延迟 10-20 秒，复杂空间查询 40-70 秒
- 支持 Gemini 和 DeepSeek 双模型，输出质量一致
- 无英文表名输入也能正确匹配数据表

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户自然语言问题                           │
│              "统计历史文化街区的总数量"                             │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                    ① NL2SQL Agent (LlmAgent)                     │
│  model: gemini-2.5-flash | tools: prepare + execute             │
│  instruction: 3 步顺序执行 + 安全规则 + 输出规则                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │ 步骤 1: prepare_nl2sql_context()
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                 ② 语义解析层 (Semantic Layer)                     │
│                                                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐          │
│  │ 表级同义词   │  │ 列级别名反查  │  │ 静态领域目录    │          │
│  │ 匹配        │  │              │  │ (YAML)         │          │
│  └──────┬──────┘  └──────┬───────┘  └───────┬────────┘          │
│         │                │                   │                   │
│         ▼                ▼                   ▼                   │
│  ┌──────────────────────────────────────────────────┐           │
│  │        resolve_semantic_context()                 │           │
│  │  输出: 候选表 + 匹配列 + 空间操作 + 区域过滤       │           │
│  └──────────────────────────┬───────────────────────┘           │
└─────────────────────────────┼───────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                ③ Grounding 引擎 (nl2sql_grounding)               │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐         │
│  │ Schema 充实   │  │ Few-shot 检索 │  │ Prompt 格式化  │         │
│  │ (describe_   │  │ (embedding   │  │ (SRID 规则 +   │         │
│  │  table)      │  │  cosine)     │  │  安全约束)     │         │
│  └──────┬───────┘  └──────┬───────┘  └───────┬────────┘         │
│         │                 │                   │                  │
│         ▼                 ▼                   ▼                  │
│  ┌──────────────────────────────────────────────────┐           │
│  │         build_nl2sql_context()                    │           │
│  │  输出: grounding_prompt (结构化 schema 文本块)     │           │
│  └──────────────────────────┬───────────────────────┘           │
└─────────────────────────────┼───────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│              ④ LLM SQL 生成 (Gemini / DeepSeek)                  │
│                                                                  │
│  输入: grounding_prompt + 用户问题                                │
│  输出: SELECT ... FROM ... WHERE ... LIMIT 1000;                │
└──────────────────────────┬──────────────────────────────────────┘
                           │ 步骤 3: execute_nl2sql(sql)
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                  ⑤ 执行与自纠错 (Executor)                        │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ SQL 后处理│→│ 安全执行  │→│ 错误检测  │→│ LLM 修复  │        │
│  │ (LIMIT/  │  │ (参数化  │  │ (最多 2  │  │ (Gemini  │        │
│  │  引号)   │  │  事务)   │  │  次重试) │  │  Flash)  │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
│                                                                  │
│  成功 → auto_curate() 自动入库参考查询                            │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│               ⑥ 输出清理与交付 (app.py + ChatPanel)              │
│                                                                  │
│  后端: 缓冲 sub_agent 输出 → clean_cot_leakage() 正则清理        │
│  前端: cleanCotLeakage() 显示层兜底 → ReactMarkdown 渲染         │
└──────────────────────────────────────────────────────────────────┘
```

## 3. 各层详细说明

### 3.1 NL2SQL Agent 定义

**文件**: `data_agent/agent.py` (第 883-902 行)

```python
"NL2SQL": lambda: LlmAgent(
    name="MentionNL2SQL",
    instruction="""...""",
    model=get_model_for_tier("standard"),  # gemini-2.5-flash
    output_key="nl2sql_result",
    tools=[NL2SQLEnhancedToolset(), SemanticLayerToolset(),
           DatabaseToolset(tool_filter=["query_database", "describe_table"])],
)
```

**设计决策**：

| 决策点 | 选择 | 原因 |
|--------|------|------|
| Agent 框架 | Google ADK `LlmAgent` | 项目统一框架，支持 tool calling、output_key、plugin 挂载 |
| 模型层级 | standard (gemini-2.5-flash) | 平衡推理能力和成本；premium 太贵，fast 推理不够 |
| 工具限制 | 只允许 prepare + execute | 防止 agent 自行调用 describe_table 绕过 grounding |
| 执行模式 | 3 步顺序 | 强制 grounding → 生成 → 执行的流程，避免跳步 |

**Instruction 中的关键规则**：

1. **LIMIT 硬规则**：所有 SELECT 必须包含 LIMIT，即使用户要求全部数据
2. **写操作拒绝**：DELETE/UPDATE/DROP 直接拒绝，不解释规则原文
3. **输出格式**：只输出最终结论，禁止输出推理过程
4. **拒绝格式**：标准化一句话拒绝，不追问用户

### 3.2 语义解析层 (Semantic Layer)

**文件**: `data_agent/semantic_layer.py`

这是整个系统的核心匹配引擎，负责把用户的自然语言映射到数据库中的具体表和列。

#### 3.2.1 数据模型

系统依赖两张元数据表：

**表 `agent_semantic_sources`** — 表级语义注册

```sql
CREATE TABLE agent_semantic_sources (
    id SERIAL PRIMARY KEY,
    table_name VARCHAR(255) UNIQUE NOT NULL,
    display_name VARCHAR(255),          -- 中文显示名，如"重庆历史文化街区"
    description TEXT,                    -- 表的业务描述
    geometry_type VARCHAR(50),           -- Polygon / Point / LineString
    srid INTEGER,                        -- 空间参考 ID，如 4326 / 4490 / 4523
    synonyms JSONB,                      -- 中文短别名数组，如 ["历史文化街区", "历史街区", "老街区"]
    suggested_analyses JSONB,            -- 推荐分析类型
    owner_username VARCHAR(100),
    is_shared BOOLEAN DEFAULT true
);
```

**表 `agent_semantic_registry`** — 列级语义注册

```sql
CREATE TABLE agent_semantic_registry (
    id SERIAL PRIMARY KEY,
    table_name VARCHAR(255) NOT NULL,
    column_name VARCHAR(255) NOT NULL,
    semantic_domain VARCHAR(100),        -- 语义域，如 NAME / ID / AREA / CATEGORY
    aliases JSONB,                       -- 列别名数组，如 ["楼层数", "层数", "层高"]
    unit VARCHAR(50),                    -- 单位，如 "万人" / "%" / "米"
    description TEXT,                    -- 列的业务描述
    is_geometry BOOLEAN DEFAULT false,
    owner_username VARCHAR(100),
    UNIQUE(table_name, column_name)
);
```

**技术选型说明**：

- **JSONB 存储同义词/别名**：PostgreSQL 原生 JSONB 支持 GIN 索引和 `@>` 操作符，比关系表更灵活
- **owner_username 多租户**：每个用户可以有自己的语义注册，`is_shared` 控制可见性
- **unit 字段**：直接嵌入 grounding prompt，让 LLM 知道"100 万 = 100（万人）"

#### 3.2.2 核心函数：resolve_semantic_context()

**文件**: `data_agent/semantic_layer.py` (第 374-595 行)

这个函数是语义解析的入口，执行 4 层渐进式匹配：

```
用户问题: "统计历史文化街区的总数量"
         │
         ▼
Layer 1: 表级同义词匹配
         synonyms 包含 "历史文化街区" → cq_historic_districts (conf=0.70)
         │
         ▼
Layer 2: 列级别名反查
         如果 Layer 1 未命中，扫描所有列的 aliases
         找到包含用户关键词的列 → 反推所属表
         置信度打 0.8 折扣
         │
         ▼
Layer 3: 静态领域目录匹配
         semantic_catalog.yaml 中的领域层次（LAND_USE / BUILDING / TRANSPORT）
         匹配 "林地" → LAND_USE.Forest → 生成 SQL 过滤条件
         │
         ▼
Layer 4: 用户自定义领域匹配
         agent_semantic_domains 表中的自定义层次
         支持 parent → child → sub_child 三级匹配
```

**输出结构**：

```python
{
    "sources": [                          # 匹配到的候选表
        {"table_name": "cq_historic_districts", "confidence": 0.70, ...}
    ],
    "matched_columns": {                  # 每张表匹配到的列
        "cq_historic_districts": [
            {"column_name": "jqmc", "aliases": ["街区名称"], "unit": "", ...}
        ]
    },
    "spatial_ops": [{"operation": "buffer"}],  # 检测到的空间操作
    "region_filter": None,                     # 区域过滤
    "metric_hints": [],                        # 指标提示
    "sql_filters": [],                         # 推荐 SQL WHERE 条件
}
```

#### 3.2.3 双向子串匹配算法

**文件**: `data_agent/semantic_layer.py` (第 247-280 行)

这是让"无英文表名查询"成为可能的关键算法。

```python
def _match_aliases(user_text: str, aliases: list, fuzzy: bool = True) -> float:
```

**匹配策略（按优先级）**：

| 策略 | 条件 | 置信度 | 示例 |
|------|------|--------|------|
| 精确匹配 | `alias == user_text` | 1.0 | "历史文化街区" == "历史文化街区" |
| 正向子串 | `alias in user_text` | 0.70 | "历史文化街区" in "统计历史文化街区的总数量" |
| 反向子串 | user_text 的子段出现在 alias 中，覆盖率 ≥50% | 0.50-0.65 | "搜索指数" 在 "2023年百度搜索指数" 中 |
| 模糊匹配 | SequenceMatcher ratio ≥ 0.75 | ratio×0.6 | 处理拼写变体 |

**反向子串的实现细节**：

```python
# 从用户文本中提取所有长度 ≥3 的子段
# 检查每个子段是否出现在 alias 中
# 计算覆盖率 = len(子段) / len(alias)
# 覆盖率 ≥ 50% 才算命中
for seg_len in range(min(len(user_lower), len(alias_lower)), 2, -1):
    for start in range(len(user_lower) - seg_len + 1):
        seg = user_lower[start:start + seg_len]
        if len(seg) >= 3 and seg in alias_lower:
            coverage = len(seg) / max(len(alias_lower), 1)
            if coverage >= 0.5:
                best_score = max(best_score, min(0.65, coverage))
```

**技术选型说明**：

- **为什么不用 embedding 做表匹配**：表名匹配是高频操作（每次查询都要跑），embedding API 调用 ~2 秒，而字符串匹配 <1ms。embedding 只用在 few-shot 检索（低频、高价值）
- **为什么 50% 覆盖率阈值**：低于 50% 会产生大量误匹配（如"数据"匹配到"AOI数据"），高于 70% 又会漏掉合理的短别名

#### 3.2.4 缓存策略

```
查询路径: 内存缓存 (dict, 5min TTL) → Redis 缓存 (5min TTL) → PostgreSQL
写入路径: PostgreSQL → 同时失效 Redis + 内存缓存
```

**技术选型说明**：

- **三级缓存**：内存最快（<1ms），Redis 跨进程共享（~5ms），DB 持久化
- **5 分钟 TTL**：平衡实时性和性能；元数据变更不频繁，5 分钟延迟可接受
- **失效函数**：`invalidate_semantic_cache(table_name=None)` 支持全量或单表失效

### 3.3 Grounding 引擎

**文件**: `data_agent/nl2sql_grounding.py`

Grounding 引擎的职责是把语义解析的结果组装成 LLM 能理解的结构化 prompt。

#### 3.3.1 核心函数：build_nl2sql_context()

```python
def build_nl2sql_context(user_text: str) -> dict:
```

**执行流程**：

```
1. resolve_semantic_context(user_text)     # ~2s
   → 得到候选表 + 语义提示
   
2. 模糊补充 (fuzzy supplement)             # <10ms
   → 对未命中的表做 _score_source() 评分
   → 取 top-2 低置信度补充表
   
3. Schema 充实                             # ~1s (每表 ~0.4s)
   → 对每张候选表调用 describe_table_semantic()
   → 合并语义注解 + 原始 schema
   → 构建 _build_candidate_table() 对象
   
4. Few-shot 检索（条件触发）               # 0s 或 ~18s
   → _should_fetch_few_shots() 判断是否需要
   → 如需要，调用 fetch_nl2sql_few_shots()
   
5. Prompt 格式化                           # <10ms
   → _format_grounding_prompt() 生成文本块
```

#### 3.3.2 智能 Few-shot 跳过

**文件**: `data_agent/nl2sql_grounding.py` (第 13-23 行)

Few-shot 检索是整个流程中最昂贵的操作（~18 秒，因为要调用 embedding API）。系统通过启发式规则决定是否跳过：

```python
def _should_fetch_few_shots(user_text, candidate_tables, semantic):
    # 多个高置信度表 → 复杂查询，需要 few-shot
    high_conf = [t for t in candidate_tables if t.get("confidence", 0) >= 0.6]
    if len(high_conf) > 1:
        return True
    # 用户问题包含复杂空间关键词
    if any(h in user_text for h in ("面积", "距离", "交集", "占比", ...)):
        return True
    # 空间操作 + 指标提示同时存在
    if semantic.get("spatial_ops") and (semantic.get("metric_hints") or semantic.get("sql_filters")):
        return True
    return False
```

**效果**：

| 查询类型 | 是否触发 few-shot | grounding 耗时 |
|----------|------------------|---------------|
| "统计历史文化街区的总数量" | 否 | ~4s |
| "找出常住人口超过100万的区县" | 否 | ~3s |
| "计算两个规划区的交集面积" | 是（多表 + "面积"） | ~21s |
| "解放碑周边1000米内的建筑物" | 是（多表） | ~21s |
| "查地下矿产资源" | 否（单表 + 无指标） | ~4s |

**技术选型说明**：

- **为什么不全部跳过 few-shot**：复杂空间查询（ST_DWithin + geography、ST_Intersection + SUM）如果没有 few-shot 示例，LLM 生成的 SQL 正确率显著下降
- **为什么阈值是 0.6**：低于 0.6 的表通常是 fuzzy fallback 补充的，不代表真正的多表查询意图

#### 3.3.3 Grounding Prompt 格式

`_format_grounding_prompt()` 生成的文本块包含以下段落：

```
[NL2SQL 上下文 — 必须严格遵循以下 schema]

## 候选数据源
### cq_historic_districts (重庆历史文化街区)
置信度: 0.70; 估计行数: 20
- jqmc :: character varying [单位: ] | 别名: 街区名称
- shape :: geometry(GEOMETRY,4490) | 别名: 几何
⚠ PostgreSQL 规则: 大小写混合列名必须使用双引号

## ⚠ SRID 不一致警告
- cq_historic_districts.shape: SRID=4490
- cq_osm_roads.shape: SRID=4326
- 建议: 将其他列 ST_Transform 到 SRID=4490 后再做空间运算

## 空间几何字段规则 (地理坐标)
- 适用于: cq_historic_districts.shape
- 面积: ST_Area(geom::geography) → 平方米
- 距离: ST_Distance(a::geography, b::geography) → 米

## 空间几何字段规则 (投影坐标)
- 适用于: cq_ghfw.shape
- ST_Area(geom) 直接返回平方米
- 禁止对这些列使用 ::geography

## 参考 SQL
- 问: 查找某个AOI区域周边指定距离范围内的建筑物
  SQL: SELECT b."Id", b."Floor" FROM ...

## 安全规则
- 只允许 SELECT 查询
- 大表全表扫描必须有 LIMIT
- 不允许 DELETE / UPDATE / INSERT / DROP / ALTER
```

**关键设计点**：

1. **SRID 规则分离**：地理坐标（4326/4490/4610）和投影坐标（4523 等）的面积/距离计算方式完全不同，必须在 prompt 中明确区分
2. **单位标注**：`[单位: 万人]` 直接嵌入列描述，让 LLM 知道"100 万 = WHERE 常住人口 > 100"
3. **Transform 建议**：当检测到多 SRID 时，明确建议目标 SRID，避免 LLM 猜测

### 3.4 执行与自纠错

**文件**: `data_agent/nl2sql_executor.py`

#### 3.4.1 两阶段工具设计

NL2SQL 暴露给 Agent 的只有两个工具：

**工具 1: `prepare_nl2sql_context(user_question: str) → str`**

- 调用 `build_nl2sql_context()` 获取完整 grounding
- 将候选表 schema 缓存到 `ContextVar`（供重试时使用）
- 返回格式化的 grounding prompt 文本

**工具 2: `execute_nl2sql(sql: str) → str`**

- SQL 后处理（LIMIT 注入、引号校验）
- 安全执行（参数化事务、超时保护）
- 最多 2 次 LLM 自纠错重试
- 成功后自动入库参考查询

#### 3.4.2 自纠错重试机制

```
attempt 0: 执行原始 SQL
  → 成功 → auto_curate() → 返回结果
  → 失败 → _retry_with_llm(question, failed_sql, error, schemas)
  
attempt 1: 执行 LLM 修复后的 SQL
  → 成功 → auto_curate() → 返回结果
  → 失败 → _retry_with_llm(...)
  
attempt 2: 最后一次尝试
  → 成功 → 返回结果
  → 失败 → 返回错误信息
```

**LLM 修复 prompt**：

```
你是 SQL 修复专家。以下 SQL 执行失败，请修复。
原始问题: {question}
失败 SQL: {failed_sql}
错误信息: {error}
可用 Schema: {schemas}
只返回修复后的 SQL，不要解释。
```

**技术选型说明**：

- **修复模型用 fast tier (gemini-2.0-flash)**：修复是机械性任务，不需要强推理，fast 模型更快更便宜
- **最多 2 次重试**：经验表明，如果 2 次修复都失败，问题通常不在 SQL 语法而在语义理解，继续重试无意义
- **ContextVar 缓存 schema**：重试时不需要重新调用 grounding，直接复用上一轮的 schema

#### 3.4.3 自动策展 (Auto-Curate)

每次成功执行后，系统自动将 (question, SQL) 对入库到 `agent_reference_queries`：

```python
def _auto_curate(question: str, sql: str) -> None:
    store = ReferenceQueryStore()
    domain_id = _extract_domain(sql)  # 从 SQL 中提取表名作为 domain
    store.add(
        query_text=question,
        response_summary=sql,
        task_type="nl2sql",
        source="auto_curate",
        domain_id=domain_id,
    )
```

**去重机制**：`ReferenceQueryStore.add()` 内置 cosine > 0.92 去重，相似问题不会重复入库。

### 3.5 参考查询库 (Reference Query Store)

**文件**: `data_agent/reference_queries.py`

#### 3.5.1 数据模型

```sql
CREATE TABLE agent_reference_queries (
    id BIGSERIAL PRIMARY KEY,
    query_text TEXT NOT NULL,            -- 自然语言问题
    description TEXT,                     -- 描述
    response_summary TEXT,                -- 对应的 SQL
    tags JSONB,                           -- 标签，如 ["spatial", "distance"]
    pipeline_type VARCHAR(50),
    task_type VARCHAR(50),                -- "nl2sql"
    source VARCHAR(30),                   -- "auto_curate" / "benchmark_pattern" / "manual"
    feedback_id BIGINT,
    embedding REAL[],                     -- 768 维向量
    domain_id VARCHAR(255),               -- 关联的表名
    use_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    created_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### 3.5.2 Embedding 检索

```python
def search(self, query: str, top_k: int = 5, task_type: str = None) -> list[dict]:
    query_emb = self._embed(query)  # Gemini text-embedding-004, 768 维
    # 从 DB 加载所有有 embedding 的记录
    rows = conn.execute("SELECT ... FROM agent_reference_queries WHERE embedding IS NOT NULL")
    # 计算 cosine similarity
    for row in rows:
        sim = dot(query_vec, emb_vec) / (norm(query_vec) * norm(emb_vec))
        scored.append((sim, row))
    # 按相似度降序排列，返回 top-k
    return sorted(scored, reverse=True)[:top_k]
```

**技术选型说明**：

| 决策点 | 选择 | 备选方案 | 选择原因 |
|--------|------|----------|----------|
| Embedding 模型 | Gemini text-embedding-004 | OpenAI ada-002, BGE-M3 | 项目已用 Gemini，无需额外 API key；768 维平衡精度和存储 |
| 向量存储 | PostgreSQL REAL[] | pgvector, Pinecone, Qdrant | 数据量小（<1000 条），不需要专用向量数据库；REAL[] 足够 |
| 相似度计算 | numpy cosine | pgvector <=> 操作符 | 全量加载到内存计算，避免 pgvector 扩展依赖 |
| 去重阈值 | cosine > 0.92 | 0.85, 0.95 | 0.92 在实测中平衡了去重效果和语义变体保留 |

#### 3.5.3 可复用空间 Few-shot 模式

**文件**: `data_agent/seed_nl2sql_patterns.py`

系统预置了两条 canonical 空间查询模式：

**模式 A: AOI 距离 + 建筑物属性过滤**

```
问: 查找某个AOI区域（如景点、商圈）周边指定距离范围内，
    满足楼层数或层高条件的建筑物，返回建筑物ID和楼层数

SQL: SELECT b."Id", b."Floor"
     FROM cq_buildings_2021 b
     JOIN cq_baidu_aoi_2024 a
       ON ST_DWithin(b.geometry::geography,
                     ST_Transform(a.shape, 4326)::geography, 1000)
     WHERE a."名称" LIKE '%解放碑%' AND b."Floor" > 30;
```

**教会 LLM 的关键点**：
- AOI polygon 需要先 `ST_Transform` 到 4326 再 `::geography`
- 距离查询用 `ST_DWithin(...::geography, ...::geography, 米)`
- 属性过滤是普通 WHERE 条件

**模式 B: 面面相交 + 总面积聚合**

```
问: 计算两个面图层（如规划区、管制区）的空间交集总面积，
    以公顷或平方米为单位返回单个汇总结果

SQL: SELECT SUM(ST_Area(ST_Intersection(j.shape, g.shape))) / 10000.0
       AS intersect_area_ha
     FROM cq_jsydgzq j
     JOIN cq_ghfw g ON ST_Intersects(j.shape, g.shape);
```

**教会 LLM 的关键点**：
- `ST_Intersects` 是 JOIN 条件
- `ST_Intersection` 计算交集几何
- **必须** 用 `SUM(...)` 聚合成单个总面积
- 投影坐标下 `ST_Area()` 直接返回平方米

### 3.6 输出清理

#### 3.6.1 后端缓冲 (app.py)

对 `sub_agent_direct` 类型的 pipeline，文本不再实时 streaming，而是先缓冲：

```python
if part.text:
    if pipeline_type != "sub_agent_direct":
        await final_msg.stream_token(part.text)  # 其他管道正常 streaming
    full_response_text += part.text               # sub_agent 只缓冲
```

Pipeline 结束后，先清理再发送：

```python
if full_response_text and pipeline_type in ("sub_agent_direct", "general"):
    cleaned = clean_cot_leakage(full_response_text)
    if cleaned != full_response_text:
        full_response_text = cleaned

if pipeline_type == "sub_agent_direct" and full_response_text:
    final_msg.content = full_response_text
    await final_msg.send()
```

#### 3.6.2 CoT 清理正则 (pipeline_helpers.py)

```python
_COT_PATTERNS = re.compile(
    r"(?:^|\n)"
    r"(?:让我|我来|我需要|我应该|根据规则|根据返回|不过根据|"
    r"所以我|实际上|用户想要|用户要求|不过，安全|现在我来|这涉及到)"
    r"[^\n]{0,200}\n?"
    r")+",
    re.MULTILINE,
)
```

#### 3.6.3 前端显示层兜底 (ChatPanel.tsx)

```typescript
function cleanCotLeakage(text: string): string {
    // 短拒绝归一化
    if (text.length < 120 && text.includes('DELETE/UPDATE/DROP')) {
        return '我不能执行修改、删除或新增数据的操作。我只能帮助查询。';
    }
    // 从最终答案标记开始截断
    const finalMarkers = ['已成功', '查询成功', '以下是结果', '数据来源表'];
    for (const marker of finalMarkers) {
        const idx = text.indexOf(marker);
        if (idx > 0) { text = text.slice(idx); break; }
    }
    // 正则清理推理痕迹
    // ...
}
```

**为什么需要前后端双层清理**：

- **后端清理**：处理缓冲后的完整文本，效果最好
- **前端清理**：兜底处理 Chainlit `msg.output` 和 `msg.content` 不同步的情况（前端渲染的是 `output`，后端 `update()` 改的是 `content`）

## 4. 安全机制

### 4.1 SQL 注入防护

- `execute_safe_sql()` 使用参数化查询
- `postprocess_sql()` 拒绝 DDL/DML 关键词
- Agent instruction 明确禁止写操作

### 4.2 资源保护

- 所有 SELECT 强制 LIMIT（默认 1000）
- CostGuard 插件监控 token 消耗（可配置阈值）
- 大表（>1M 行）在 grounding 中标记警告

### 4.3 幻觉防护

- 当 schema 中不存在用户请求的字段时，agent 直接拒绝
- 不会编造不存在的表名或列名
- Benchmark ROBUSTNESS_03 专门验证此能力

## 5. 复现指南

### 5.1 环境准备

```bash
# PostgreSQL 16 + PostGIS 3.4
# Python 3.13+
# Node.js 20+

pip install -r requirements.txt
cd frontend && npm install && npm run build
```

### 5.2 数据库初始化

```sql
-- 1. 创建语义源表
CREATE TABLE agent_semantic_sources (...);  -- 见 migration 009

-- 2. 创建语义注册表
CREATE TABLE agent_semantic_registry (...);  -- 见 migration 009

-- 3. 创建参考查询表
CREATE TABLE agent_reference_queries (...);  -- 见 migration 054

-- 4. 注册数据表的语义元数据
INSERT INTO agent_semantic_sources (table_name, display_name, synonyms)
VALUES ('cq_historic_districts', '重庆历史文化街区',
        '["历史文化街区", "历史街区", "文化街区"]');

-- 5. 注册列的语义元数据
INSERT INTO agent_semantic_registry (table_name, column_name, aliases, unit)
VALUES ('cq_district_population', '常住人口', '["常住人口"]', '万人');
```

### 5.3 种子 Few-shot

```python
from data_agent.seed_nl2sql_patterns import seed_nl2sql_patterns
seed_nl2sql_patterns(created_by="admin")
```

### 5.4 启动应用

```bash
PYTHONPATH="D:\adk" chainlit run data_agent/app.py -w
# 访问 http://localhost:8000
# 在聊天框输入: @NL2SQL 统计历史文化街区的总数量
```

### 5.5 验证 Benchmark

逐题测试 `benchmarks/chongqing_geo_nl2sql_full_benchmark_v2.json` 中的 16 道题，对比 golden SQL 结果。

## 6. 性能优化记录

| 优化项 | 优化前 | 优化后 | 方法 |
|--------|--------|--------|------|
| 简单查询 grounding | 22s | 4s | 智能跳过 few-shot embedding 检索 |
| MEDIUM_02 空间 join | 219s | 0.5s | 转换小表 polygon 而非大表 point，触发 GiST 索引 |
| DeepSeek CoT 泄露 | 整屏推理 | 干净结果 | 后端缓冲 + 正则清理 + 前端兜底 |
| 无表名查询匹配 | 0% | 100% | 双向子串匹配 + 中文同义词补齐 |
| 单位换算错误 | 100万→1000000 | 100万→100 | 列 unit 字段嵌入 grounding prompt |
