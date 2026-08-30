# NL2Semantic2SQL — 技术架构与复现指南 (v3.1 current)

> GIS Data Agent (ADK Edition) — 跨域自然语言到 SQL 框架
> 版本: 3.1 | 日期: 2026-08-24 | Branch: current working tree
> 作者: 周宁 (Beijing SuperMap Software Co., Ltd.)
> 前置版本: `semantic_layer_architecture.md` v1.1 (2026-08-24，历史通用 GIS 语义层说明)

> 本文前半部分保留历史 P2/通用 NL2SQL 的复现记录。阿布扎比两库的当前实现、双路线边界、v4 语义层和最新评测口径以 [`docs/nl2semantic2sql_architecture.md`](nl2semantic2sql_architecture.md) 第 13 节为准。历史 benchmark 数字不能直接作为当前产品准确率。

---

## 0. 本文档的目的

本文档是 GIS Data Agent 中 NL2Semantic2SQL 功能的**完整技术规格**，相比 v1.0 版本，重点说明：

1. **如何同时支持 GIS 与非 GIS 场景**（双轨适配的核心机制）
2. **意图分类 + 路由如何实现领域无关的统一架构**
3. **从 NL 到 SQL 的端到端流水线**（5 个阶段，可独立复现）
4. **每个组件的实现细节、数据契约、可测试边界**
5. **复现指南**：从零搭建一个等价系统所需的全部信息

读完本文档，读者应能在自己的环境中实现等价框架，或直接复用本仓库代码并理解每个决策的理由。

---

## 目录

- [1. 总体架构](#1-总体架构)
- [2. 双场景统一设计原则](#2-双场景统一设计原则)
- [3. 五阶段流水线](#3-五阶段流水线)
- [4. 模块详解](#4-模块详解)
- [5. 数据契约](#5-数据契约)
- [6. GIS 场景适配](#6-gis-场景适配)
- [7. 仓库（非GIS）场景适配](#7-仓库非gis场景适配)
- [8. 端到端调用流程](#8-端到端调用流程)
- [9. 关键文件清单](#9-关键文件清单)
- [10. 复现步骤](#10-复现步骤)
- [11. 已验证性能](#11-已验证性能)
- [12. 已知限制与未来工作](#12-已知限制与未来工作)

---

## 1. 总体架构

NL2Semantic2SQL 是一个**统一**的自然语言查询框架，通过**意图条件化路由**同时支持：

- **GIS 空间查询**（中文，PostGIS 几何运算、SRID、空间谓词、安全拒答）
- **企业仓库查询**（英文/中文，事实-维度建模、聚合、JOIN 推理）

核心思想是：**单一 grounding 流水线 + 意图驱动的规则注入**。架构在结构上对所有领域统一，在每次请求层面通过意图分类条件化激活领域规则。

```
┌─────────────────────────────────────────────────────────────────────┐
│                     NL2Semantic2SQL Pipeline                        │
│                                                                     │
│  NL Question ──┐                                                    │
│                ▼                                                    │
│         ┌──────────────┐                                            │
│         │ Stage 1:     │  ← Bilingual Intent Classifier             │
│         │ Intent       │    (9 classes, regex + LLM judge)          │
│         │ Classifier   │                                            │
│         └──────┬───────┘                                            │
│                ▼                                                    │
│         ┌──────────────┐                                            │
│         │ Stage 2:     │  ← Semantic Layer (aliases, hierarchy,     │
│         │ Semantic     │    metric definitions, value hints)        │
│         │ Resolution   │  ← MetricFlow Models (fact/dim, joins)     │
│         └──────┬───────┘                                            │
│                ▼                                                    │
│         ┌──────────────┐                                            │
│         │ Stage 3:     │  ← Intent-conditioned Rule Injection       │
│         │ Grounding    │    (GIS rules / warehouse rules)           │
│         │ Prompt Build │  ← Few-shot retrieval (when relevant)      │
│         └──────┬───────┘                                            │
│                ▼                                                    │
│         ┌──────────────┐                                            │
│         │ Stage 4:     │  ← Single LLM call (Gemini 2.5 Flash)      │
│         │ SQL          │    Temperature=0.0, JSON-strict prompt     │
│         │ Generation   │                                            │
│         └──────┬───────┘                                            │
│                ▼                                                    │
│         ┌──────────────┐                                            │
│         │ Stage 5:     │  ← Postprocess (LIMIT, quoting, safety)    │
│         │ Postprocess  │  ← Execute on PG/PostGIS                   │
│         │ + Execute +  │  ← LLM-based retry on error (≤2 retries)   │
│         │ Self-correct │                                            │
│         └──────┬───────┘                                            │
│                ▼                                                    │
│       Executable SQL + Result                                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. 双场景统一设计原则

### 2.1 不要为每个领域写一套流水线

错误的做法是分别建立 GIS pipeline 和 warehouse pipeline，然后在入口 dispatch。这样会导致代码冗余、维护成本高、跨域知识无法共享。

正确的做法（本框架采用）：

- **同一套 5 阶段流水线**对两个领域都跑
- **每个阶段的内部逻辑**根据意图和上下文条件化激活规则
- **意图分类器是双语的**：同时识别中文 GIS 关键词（"面积"、"附近"、"图斑"）和英文仓库表达（"how many"、"what is the average"）

### 2.2 意图驱动的条件化路由

意图分类器输出 9 个类别中的一个：

```
attribute_filter   — 属性过滤 (e.g., DLMC = '水田', segment = 'SME')
category_filter    — 类别过滤 (e.g., 耕地、林地、城镇)
spatial_measurement — 空间测量 (面积、长度、周长)
spatial_join       — 空间关联 (相交、包含、与...相邻)
knn                — 最近邻 (最近的5条道路, nearest 10 customers)
aggregation        — 聚合 (how many, ratio, average, group by)
preview_listing    — 预览列举 (列出所有, please list)
refusal_intent     — 拒答类 (删除、改成、drop, delete)
unknown            — 兜底
```

每个意图激活/抑制不同的规则集。例如：

| 意图 | 激活 | 抑制 |
|------|------|------|
| `spatial_measurement` | 几何类型注入、`::geography` casting、SRID 警告 | LIMIT 注入、KNN 算子 |
| `aggregation` | MetricFlow JOIN 提示、聚合粒度规则 | LIMIT 注入、几何规则 |
| `knn` | `<->` 算子规则、ST_Distance 禁用警告 | LIMIT 注入（KNN 内部已含 LIMIT） |
| `preview_listing` | LIMIT 注入（防 OOM） | KNN 算子 |
| `refusal_intent` | 拒答模板生成 | 任何 SQL 生成 |

这种设计的关键效果：**GIS 规则不会污染仓库查询，仓库规则不会干扰 GIS 查询**。

### 2.3 Schema 上的领域信号

除意图外，框架还从 schema 自身识别领域信号：

- **几何列检测**: 通过 `geometry_columns` 系统视图识别 PostGIS 几何列 → 激活空间规则
- **MetricFlow 模型**: 检查 `agent_semantic_models` 表是否有该 schema 的 fact/dim 注册 → 激活仓库 JOIN 提示
- **SRID 异构**: 多表 SRID 不同 → 强制注入 `ST_Transform` 警告

这是 schema 级的**自动域判断**，不需要用户标注或显式 dispatch。

---

## 3. 五阶段流水线

### 阶段 1: Intent Classification (`data_agent/nl2sql_intent.py`)

**输入**: 自然语言问题 (str)
**输出**: `IntentResult { primary: IntentLabel, secondary: list, confidence: float, source: str }`

**实现**：两阶段分类器
1. **规则阶段** (`classify_rule`): 双语正则模式按优先级匹配 (REFUSAL > KNN > SPATIAL_JOIN > AGGREGATION > CATEGORY_FILTER > ATTRIBUTE_FILTER > SPATIAL_MEASUREMENT > PREVIEW_LISTING)。匹配置信度 0.85-0.95。
2. **LLM judge 阶段** (`_llm_judge`): 当规则阶段返回 UNKNOWN 时，调用 Gemini 2.0 Flash 输出严格 JSON 分类（fallback to UNKNOWN on failure）。

**规则模式中英文混合**：
```python
# AGGREGATION 同时识别中英文
r"\bhow\s+many|how\s+much|what\s+is\s+the\s+(ratio|percentage|average|...)"
r"|分组|按.{0,20}统计|总和|总数|占比"
```

**ContextVar 传递**: 分类结果通过 `current_nl2sql_intent: ContextVar[IntentLabel]` 在异步调用链中传递，下游所有阶段可读取。

### 阶段 2: Semantic Resolution (`data_agent/semantic_layer.py`)

**输入**: 用户文本
**输出**: `dict { sources, matched_columns, spatial_ops, region_filter, metric_hints, hierarchy_matches, sql_filters, equivalences }`

**职责**: 通过 `resolve_semantic_context(user_text)` 从语义注册表中解析：

- **数据源候选**: 通过别名、关键词匹配从 `agent_semantic_sources` 表查找候选表
- **列名匹配**: 通过 `agent_semantic_registry` 表查列别名（如 "面积" → `TBMJ`, "consumption" → `Consumption`）
- **空间算子**: 识别用户意图中的空间操作（intersects, within, buffer 等）
- **层次扩展**: 类别词扩展（"林地" → DLBM LIKE '03%'）
- **指标定义**: MetricFlow-style 度量识别（"average monthly consumption" → measure: yearmonth.Consumption）

**5 分钟 TTL 缓存**: 通过 `lru_cache` 缓存语义层查询结果，写入时通过 `invalidate_semantic_cache()` 失效。

### 阶段 3: Grounding Prompt Build (`data_agent/nl2sql_grounding.py`)

**入口**: `build_nl2sql_context(user_text: str) -> dict`

**子步骤**：

1. `classify_intent(user_text)` — 调用阶段 1
2. `resolve_semantic_context(user_text)` — 调用阶段 2
3. `_rank_sources(...)` — 候选表排序（语义置信度 + 关键词匹配 + schema hint）
4. `_rank_candidate_tables(...)` — 二次排序，过滤到 top-3
5. `_build_warehouse_join_hints(...)` — 仅非空间查询：从 `SemanticModelStore` 读 fact/dim 模型，构建 JOIN 路径提示
6. `_sample_distinct_values(...)` — 仅仓库类英文查询：为低基数文本列采样示例值（避免 LLM 编造枚举）
7. `fetch_nl2sql_few_shots(...)` — 检索 top-3 历史成功 SQL 示例
8. `_format_grounding_prompt(payload)` — 拼装最终 prompt

**意图条件化的输出区段**（在 `_format_grounding_prompt` 内）：

```
[NL2SQL 上下文 — 必须严格遵循以下 schema]
## 候选数据源
  ### table_name
  - 列定义、别名、单位、几何类型、SRID

## (条件) SRID 不一致警告  ← 仅当多表 SRID 不同
## (条件) 空间几何字段规则 (地理坐标)  ← 仅当存在 4326/4490/4610 几何列
## (条件) 空间几何字段规则 (投影坐标)  ← 仅当存在投影几何列

## 语义提示
- 空间操作 / 区域过滤 / 层次匹配 / 指标提示 / 推荐 SQL 过滤

## (条件) 数据仓库 Join 路径提示  ← 仅非空间查询且有 MetricFlow 模型
- table_name: 事实表/维度表; 实体键: ...; 度量: ...
- JOIN: a JOIN b ON a.key = b.key

## (条件) 参考 SQL  ← 仅 few-shot 触发条件成立
Q: ... / SQL: ...

## 安全规则
- 只允许 SELECT
- 不允许 DELETE / UPDATE / INSERT / DROP / ALTER

## (条件意图) 大表全表扫描必须有 LIMIT  ← 仅 PREVIEW_LISTING / UNKNOWN
## (条件意图) KNN 排序规则                 ← 仅 KNN / UNKNOWN
- 最近邻必须用 ORDER BY a.geometry <-> b.geometry LIMIT K
- 不允许 ORDER BY ST_Distance(...) 排序
```

### 阶段 4: SQL Generation

**单次 LLM 调用** (P2 模式):

> **P2 命名说明**: P2 = "Pass-2 单次生成模式"，是相对于早期 P1（"Pass-1 多轮 ADK Agent Loop 模式"）的优化。P1 走 ADK agent 循环（5-15 轮 tool call），token 成本约 32× baseline 且某些题会无限循环。P2 是确定性单次推理：本地构建 grounding（无 LLM 调用）→ 1 次主生成 LLM 调用 → 后处理 + 执行 → 失败时最多 2 次纠错 LLM 调用。每道题固定 1-3 次 LLM 调用，token 降至约 8× baseline，且消除卡死。生产环境推荐使用 P2 直接调用模式。

```python
prompt = (
    "You are a PostgreSQL SQL expert. Convert the user question into a single SELECT query.\n"
    + grounding_prompt_from_stage3
    + "QUESTION: {user_text}\n\nSQL:"
)
resp = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=[prompt],
    config=GenerateContentConfig(temperature=0.0, http_options={"timeout": 60_000}),
)
```

**为什么单次而非 agent loop**：
- agent loop（多轮 tool call）token 成本 32× baseline，且会在某些题上无限循环不超时
- 单次生成 token 成本 8× baseline，确定性收敛
- 自纠错由阶段 5 的 `_retry_with_llm` 负责（最多 2 次重试），不依赖 agent

### 阶段 5: Postprocess + Execute + Self-correct (`data_agent/sql_postprocessor.py`, `data_agent/nl2sql_executor.py`)

**Postprocess** (`postprocess_sql(raw_sql, table_schemas, large_tables, intent)`):

1. **AST 解析**: 用 `sqlglot` 解析 SQL → `exp.Expression`
2. **安全检查**: 拒绝任何 DELETE/UPDATE/INSERT/DROP/ALTER 节点
3. **大小写修正**: 通过 `_build_column_map` 将引用纠正为正确的双引号大小写（PostgreSQL 规则）
4. **意图条件化 LIMIT 注入**: 仅当 `intent ∈ {PREVIEW_LISTING, UNKNOWN}` 且引用大表（>1M 行）时注入 LIMIT 1000
5. **拒答检测**: 如果 SQL 含写入操作 → 返回 `rejected=True, reject_reason="..."`

**Execute** (`execute_safe_sql(sql)`):
- 通过 `data_agent/database_tools.py` 的安全执行接口跑在 PostgreSQL/PostGIS 上
- 60 秒超时
- 返回 `{status: "ok"|"error", rows: [...], error: "..."}`

**Self-correct** (`_retry_with_llm`):
- 仅当 execute 返回 error 时触发
- 调用 Gemini 2.0 Flash（fast tier）传入：原始问题 + 失败 SQL + 错误信息 + 表结构
- 最多 2 次重试
- 修复后再次 postprocess + execute，若仍失败返回最后一次错误

---

## 4. 模块详解

### 4.1 `data_agent/nl2sql_intent.py` (209 行)

**核心 API**:
- `IntentLabel` (Enum, 9 类)
- `IntentResult` (dataclass)
- `classify_rule(question: str) -> IntentResult`
- `_llm_judge(question: str) -> IntentResult`
- `classify_intent(question: str) -> IntentResult` — 公共入口（先规则后 LLM）

**关键设计**：
- 规则模式按 **优先级排序**（first match wins），避免聚合关键词被属性过滤吞掉
- 中英文模式合并到同一个正则，减少匹配次数
- LLM judge 只在规则不确定时触发，且失败优雅降级到 UNKNOWN

### 4.2 `data_agent/semantic_layer.py` (1901 行)

**核心 API**:
- `resolve_semantic_context(user_text)` — 语义解析主入口
- `describe_table_semantic(table_name)` — 表 schema + 列别名/单位
- `list_semantic_sources()` — 列出所有注册数据源
- `invalidate_semantic_cache()` — 缓存失效

**数据源**：
- DB 表 `agent_semantic_sources` (源数据集元数据)
- DB 表 `agent_semantic_registry` (列别名、单位、层次)
- DB 表 `agent_semantic_models` (MetricFlow fact/dim 模型)
- 可选 YAML 文件（`config/semantic/*.yaml`）作为 fallback

### 4.3 `data_agent/semantic_model.py` (387 行)

**核心 API**:
- `SemanticModelStore.save(name, yaml_text, ...)` — 注册 MetricFlow 模型
- `SemanticModelStore.list_active()` — 列出所有激活模型
- `SemanticModelGenerator.generate_from_table(table, schema, fks)` — 自动生成 YAML

**MetricFlow YAML 格式**:
```yaml
semantic_models:
  - name: "schema.table_name"
    source_table: "schema.table"
    entities:
      - name: "id"
        type: "primary"      # primary | foreign
        column: "id"
    dimensions:
      - name: "category"
        type: "categorical"   # categorical | time | spatial
        column: "category"
    measures:
      - name: "amount"
        agg: "sum"            # sum | count | avg | min | max | count_distinct
        column: "amount"
    metrics:
      - name: "total_amount"
        type: "simple"
        measure: "amount"
```

### 4.4 `data_agent/nl2sql_grounding.py` (532 行)

`build_nl2sql_context(user_text)` 是整个流水线的**协调器**。它把意图、语义、schema、MetricFlow、few-shot 整合成一个 grounding prompt。

返回的 payload 字段：
```python
{
  "candidate_tables": [                      # top-3 排序后的候选表
    {"table_name", "confidence", "row_count_hint", "columns": [...]}
  ],
  "semantic_hints": {                        # 语义层提示
    "spatial_ops": [...],
    "region_filter": ...,
    "hierarchy_matches": [...],
    "metric_hints": [...],
    "sql_filters": [...]
  },
  "few_shots": [...],
  "warehouse_join_hints": {                  # 仅非空间查询
    "table_roles": {...},
    "join_paths": [...]
  },
  "intent": IntentLabel.AGGREGATION,         # 主意图
  "intent_secondary": [...],
  "intent_confidence": 0.95,
  "intent_source": "rule",
  "grounding_prompt": "..."                  # 最终拼装的 prompt
}
```

### 4.5 `data_agent/sql_postprocessor.py` (242 行)

**核心 API**:
- `postprocess_sql(raw_sql, table_schemas, large_tables=None, intent=None) -> PostprocessResult`

**PostprocessResult**:
```python
@dataclass
class PostprocessResult:
    sql: str                  # 修正后的 SQL
    rejected: bool            # 是否被安全规则拒绝
    reject_reason: str
    fixes_applied: list[str]  # 应用的修复列表
```

**关键修复**：
1. AST 安全检查（无写操作）
2. 列名大小写引用修正
3. 意图门控的 LIMIT 注入

### 4.6 `data_agent/nl2sql_executor.py` (167 行)

**核心 API**:
- `prepare_nl2sql_context(user_question) -> str` — 构建 grounding 并缓存到 ContextVar
- `execute_nl2sql(sql) -> str` — postprocess + execute + 自纠错循环

**ContextVar 链**:
- `current_nl2sql_question`: 用户原始问题（用于 retry prompt 和 auto_curate）
- `current_nl2sql_schemas`: 候选表 schema 字典
- `current_nl2sql_large_tables`: 大表名集合
- `current_nl2sql_intent`: 当前请求的意图（用于 postprocess）

这套 ContextVar 设计让 `prepare_nl2sql_context` 和 `execute_nl2sql` 可以作为两个独立的 ADK tool 暴露给 agent，但内部状态自动传递，无需把状态参数化。

---

## 5. 数据契约

### 5.1 输入

```python
question: str                # 自然语言问题（中/英文均可）
```

### 5.2 中间产物

```python
intent: IntentLabel          # 9 类意图
semantic_context: dict       # 语义层解析结果
candidate_tables: list[dict] # top-3 候选表
grounding_prompt: str        # 拼装好的 LLM prompt
raw_sql: str                 # LLM 第一次输出
postprocessed_sql: str       # 修复后的 SQL
```

### 5.3 输出

```python
{
  "status": "ok" | "error" | "rejected",
  "rows": [...],
  "data": [{...}, ...],
  "message": "...",
  "sql": "<final SQL>",
  "intent": "<classified intent>"
}
```

---

## 6. GIS 场景适配

### 6.1 自动激活的 GIS 规则

当 `_format_grounding_prompt` 检测到候选表存在几何列（`is_geometry=True`）时：

1. **几何类型 + SRID 注入**: 每个几何列在 prompt 中标注 `geometry(Polygon, 4326)`
2. **多 SRID 警告**: 当多表 SRID 不同时，注入 `ST_Transform` 强制对齐警告
3. **地理坐标 vs 投影坐标分支**:
   - SRID ∈ {4326, 4490, 4610}（地理坐标系，单位"度"）→ 强制 `::geography` 转换才能算米
   - 其他 SRID（投影坐标，单位"米"）→ 禁止 `::geography`，直接用 `ST_Area`
4. **KNN 算子规则**（仅 KNN 意图）: 强制 `ORDER BY a.geometry <-> b.geometry LIMIT K`，禁止 `ORDER BY ST_Distance`

### 6.2 中文别名匹配

`agent_semantic_registry` 表存储中文 → 英文/拼音列名的别名：

```sql
-- 例：CQ 数据库
INSERT INTO agent_semantic_registry (table_name, column_name, alias, unit) VALUES
  ('cq_land_use_dltb', 'DLMC', '地类名称', NULL),
  ('cq_land_use_dltb', 'TBMJ', '图斑面积', '平方米'),
  ('cq_buildings_2021', 'Floor', '楼层', NULL);
```

用户问"统计水田图斑总面积"时，语义层将"水田"识别为 `DLMC = '水田'`、"图斑面积"识别为 `TBMJ`。

### 6.3 安全/拒答处理

`refusal_intent` 类问题（如"删除所有未命名的道路"）：
- 意图分类器识别 → 触发安全分支
- LLM 被指示生成形如 `SELECT 1 -- REFUSED: ...` 的拒答 SQL
- postprocessor 进一步拦截任何漏网的 DELETE/UPDATE
- evaluator 检查是否正确拒答（不是 EX 比对，而是 robustness success rate）

### 6.4 GIS 场景实测数据

100 题 GIS benchmark（85 spatial + 15 robustness）:
- **Spatial EX 0.682** vs baseline 0.529 (McNemar p=0.0072 ✅)
- **Robustness Success 0.800** vs baseline 0.333 (p=0.0156 ✅)

---

## 7. 仓库（非GIS）场景适配

### 7.1 自动激活的仓库规则

当候选表无几何列时：

1. **GIS 规则全部抑制**（无 SRID 警告、无 `::geography`、无 KNN 算子）
2. **MetricFlow JOIN 提示注入**（如果 `agent_semantic_models` 有该 schema 的模型）：
   - 表角色（fact / dimension）
   - 实体键（primary / foreign）
   - 度量列（measures）
   - 推导的 JOIN 路径
3. **示例值采样**: 低基数文本列采样 top-8 distinct 值，注入 prompt（防止 LLM 编造枚举值）
4. **意图条件化**:
   - `aggregation` → MetricFlow 提示 + 聚合粒度规则激活
   - `attribute_filter` → 抑制 LIMIT 注入（精确查询不应该限制）
   - `preview_listing` → LIMIT 1000 防 OOM

### 7.2 自动 MetricFlow 模型生成

`SemanticModelGenerator.generate_from_table(table, schema, fks)`：

1. 查 `information_schema.columns` 拿列定义
2. 查 `geometry_columns` 检测几何列
3. 通过 SQLite `PRAGMA foreign_key_list`（BIRD imports）或 PG `referential_constraints` 拿 FK 关系
4. **角色分类**：
   - 0 FK → dimension
   - ≥2 FK 且 ≤1 非 FK 列 → bridge
   - ≥1 FK 且有数值列 → fact
5. 输出标准 YAML，存入 `agent_semantic_models`

实测 11 个 BIRD 数据库自动生成 70 个模型 + 5 个手工模型 = 75 个语义模型。

### 7.3 英文意图模式（P0a 修复）

意图分类器加入英文 BIRD 风格模式：
- "what is the (ratio|percentage|average|highest|...)" → AGGREGATION
- "please list / show / display" → PREVIEW_LISTING
- "state the X / tell the X / what's X's Y" → ATTRIBUTE_FILTER
- "calculate / compute the" → AGGREGATION

将 BIRD 500 题中 UNKNOWN 从 498 降到 96（80% 减少），让仓库查询不再因为"全规则注入"而退化。

### 7.4 仓库场景实测数据

BIRD ~495 题 (PostgreSQL):
- **Full EX 0.501** vs baseline 0.474 (+0.027, McNemar p=0.136 NS)
- **DIN-SQL EX 0.482** (paired comparison p=0.382 NS)
- 三方系统在 BIRD 上**统计可比**，无显著优势

这是诚实的 finding：当前框架在仓库查询上未达统计显著超越，是 future work 重点。

---

## 8. 端到端调用流程

### 8.1 顶层调用（生产环境）

```python
from data_agent.nl2sql_executor import prepare_nl2sql_context, execute_nl2sql
from data_agent.user_context import current_nl2sql_intent, current_nl2sql_schemas
from data_agent.nl2sql_intent import IntentLabel

def answer_nl_query(user_question: str) -> dict:
    # Step 1-3: build grounding (intent classification + semantic resolution + prompt)
    grounding_prompt = prepare_nl2sql_context(user_question)
    # ContextVars now contain: question, schemas, large_tables, intent

    # Step 4: single LLM call with grounding
    sql = call_llm_with_prompt(grounding_prompt + f"\n\nQUESTION: {user_question}\n\nSQL:")

    # Step 5: postprocess + execute + retry
    result_json = execute_nl2sql(sql)

    return json.loads(result_json)
```

### 8.2 ADK Agent 风格调用

NL2SQL 也作为 ADK tool 暴露给 LlmAgent（`data_agent/toolsets/nl2sql_enhanced_tools.py`）。Agent 模式：

```
Agent 决定调用 → prepare_nl2sql_context(question)
                ↓
            返回 grounding prompt
                ↓
Agent 用 prompt + 自己的推理生成 SQL
                ↓
Agent 调用 execute_nl2sql(sql)
                ↓
            返回执行结果
```

注意：**生产 benchmark 评测使用直接调用（8.1）**而非 agent 模式（避免 agent loop 的 token 32× 成本）。

### 8.3 跨域单一入口

无论 GIS 还是仓库查询，调用接口完全相同：

```python
# GIS query
answer_nl_query("统计重庆所有水田图斑的总面积")
# → intent=spatial_measurement, GIS rules activated, geography casting injected

# Warehouse query
answer_nl_query("What is the average monthly consumption of SME customers in 2013?")
# → intent=aggregation, MetricFlow hints activated, no GIS rules

# Mixed (rare)
answer_nl_query("Show all districts where average building floor > 30")
# → intent=aggregation, both spatial (geometry on building) and warehouse (group by district) rules activated
```

---

## 9. 关键文件清单

| 路径 | 行数 | 职责 |
|------|------|------|
| `data_agent/nl2sql_intent.py` | 209 | 9 类意图分类器 (规则 + LLM judge) |
| `data_agent/semantic_layer.py` | 1901 | 语义解析主模块 |
| `data_agent/semantic_model.py` | 387 | MetricFlow 模型 CRUD + 自动生成器 |
| `data_agent/nl2sql_grounding.py` | 532 | grounding 主协调器 + prompt 拼装 |
| `data_agent/sql_postprocessor.py` | 242 | AST 安全检查 + LIMIT 注入 + 引用修复 |
| `data_agent/nl2sql_executor.py` | 167 | execute_nl2sql + 自纠错循环 |
| `data_agent/user_context.py` | — | ContextVar 链（intent, schemas, etc） |
| `data_agent/database_tools.py` | — | `execute_safe_sql` 安全执行接口 |
| `data_agent/toolsets/nl2sql_enhanced_tools.py` | — | ADK FunctionTool 包装 |
| `data_agent/llm_client.py` | — | Gemini 客户端封装（含 DeepSeek fallback） |

DB tables（迁移文件在 `data_agent/migrations/`）:
- `agent_semantic_sources` — 数据源元数据
- `agent_semantic_registry` — 列别名、单位、层次
- `agent_semantic_models` — MetricFlow fact/dim 模型
- `agent_reference_queries` — few-shot 库（自纠错时自动 curate 进来的成功 query）

Benchmark 文件:
- `benchmarks/chongqing_geo_nl2sql_100_benchmark.json` — 100 题 GIS
- `benchmarks/chongqing_geo_nl2sql_full_benchmark.json` — 20 题 GIS (原版)
- `benchmarks/bird_chinese_100_benchmark.json` — 100 题中文 BIRD（cross-lingual）

评测脚本:
- `scripts/nl2sql_bench_cq/run_cq_eval.py` — GIS benchmark runner (baseline + full + enhanced)
- `scripts/nl2sql_bench_cq/run_din_sql.py` — DIN-SQL on GIS
- `scripts/nl2sql_bench_bird/run_pg_eval.py` — BIRD benchmark runner (P2 单次模式)
- `scripts/nl2sql_bench_bird/run_din_sql.py` — DIN-SQL on BIRD
- `scripts/nl2sql_bench_common/{bootstrap_ci.py, mcnemar.py, derive_ablation.py}` — 统计工具

---

## 10. 复现步骤

### 10.1 环境

```bash
Python 3.13.7
PostgreSQL 16 + PostGIS 3.4
Google Gemini API Key (GOOGLE_API_KEY env var)
```

### 10.2 依赖安装

```bash
git clone https://github.com/zhouning/gisdataagent.git
cd gisdataagent
git checkout feat/v12-extensible-platform
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

### 10.3 数据库初始化

```bash
# 设置 PG 连接（在 data_agent/.env）
echo "POSTGRES_HOST=..." > data_agent/.env
echo "POSTGRES_USER=..." >> data_agent/.env
echo "POSTGRES_PASSWORD=..." >> data_agent/.env
echo "POSTGRES_DB=..." >> data_agent/.env

# 应用 migrations
$env:PYTHONPATH="D:\adk"
.venv/Scripts/python.exe -c "from data_agent.migrations import apply_all; apply_all()"

# 注册 GIS 数据源（若有 CQ 数据）
.venv/Scripts/python.exe scripts/register_cq_semantic.py
```

### 10.4 注册 BIRD 仓库（可选）

```bash
# 导入 BIRD mini_dev 到 PG（需先下载 BIRD 数据集到 data/bird_mini_dev/）
.venv/Scripts/python.exe scripts/nl2sql_bench_bird/import_to_pg.py

# 注册语义层
.venv/Scripts/python.exe scripts/nl2sql_bench_bird/register_semantic.py

# 自动生成 MetricFlow 模型
.venv/Scripts/python.exe scripts/nl2sql_bench_bird/auto_generate_warehouse_models.py
```

### 10.5 单条查询测试

```python
import sys
sys.path.insert(0, "D:/adk")
from dotenv import load_dotenv; load_dotenv("data_agent/.env")

from data_agent.nl2sql_grounding import build_nl2sql_context
from data_agent.sql_postprocessor import postprocess_sql

# Step 1-3: build grounding
ctx = build_nl2sql_context("统计水田图斑的总面积")
print(ctx["intent"])              # IntentLabel.SPATIAL_MEASUREMENT
print(ctx["grounding_prompt"])    # full prompt with GIS rules

# Step 4: LLM call (your code)
sql = call_gemini(ctx["grounding_prompt"] + "\nQUESTION: ...\nSQL:")

# Step 5: postprocess
result = postprocess_sql(sql, ctx["candidate_tables"], intent=ctx["intent"])
print(result.sql)

# Execute via PG
# ...
```

### 10.6 完整 benchmark 复现

```bash
# GIS 100 题
.venv/Scripts/python.exe scripts/nl2sql_bench_cq/run_cq_eval.py \
  --mode both --benchmark benchmarks/chongqing_geo_nl2sql_100_benchmark.json

# BIRD 500 题
.venv/Scripts/python.exe scripts/nl2sql_bench_bird/run_pg_eval.py --mode both

# DIN-SQL baseline (GIS)
.venv/Scripts/python.exe scripts/nl2sql_bench_cq/run_din_sql.py \
  --benchmark benchmarks/chongqing_geo_nl2sql_100_benchmark.json

# DIN-SQL baseline (BIRD)
.venv/Scripts/python.exe scripts/nl2sql_bench_bird/run_din_sql.py

# 统计分析
.venv/Scripts/python.exe scripts/compute_final_stats.py
.venv/Scripts/python.exe scripts/compute_gis_split.py
.venv/Scripts/python.exe scripts/compute_dinsql_100q.py
.venv/Scripts/python.exe scripts/offline_ablation.py
```

### 10.7 添加新数据源（GIS 或仓库）

```python
from data_agent.semantic_layer import register_semantic_source, register_semantic_column

# 注册数据源
register_semantic_source(
    table_name="my_schema.my_table",
    aliases=["客户表", "user table"],
    description="...",
)

# 注册列（中英别名）
register_semantic_column(
    table_name="my_schema.my_table",
    column_name="amount",
    aliases=["金额", "consumption"],
    unit="元",
)

# 若是仓库表，注册 MetricFlow 模型
from data_agent.semantic_model import SemanticModelStore
SemanticModelStore().save(
    name="my_schema.my_table",
    yaml_text="""
semantic_models:
  - name: my_schema.my_table
    source_table: my_schema.my_table
    entities:
      - {name: id, type: primary, column: id}
    measures:
      - {name: amount, agg: sum, column: amount}
""",
    description="...",
)
```

新数据源即时可用于 NL2SQL（缓存自动失效）。

---

## 11. 已验证性能

### 11.1 GIS 100 题（Chongqing PostGIS）

| Mode | EX | Spatial 85q | Robust 15q | Mean tokens |
|------|-----|------------|------------|-------------|
| Baseline (direct LLM) | 0.500 | 0.529 | 0.333 | 753 |
| DIN-SQL (4-stage) | 0.520 | 0.565 | 0.267 | (not tracked) |
| **NL2Semantic2SQL Full** | **0.700** | **0.682** | **0.800** | 10,261 |

McNemar significance:
- Full vs Baseline: Spatial p=0.0072 ✅, Robust p=0.0156 ✅
- Full vs DIN-SQL: Spatial p=0.0213 ✅, Robust p=0.0078 ✅

### 11.2 BIRD ~495 题 (PostgreSQL warehouse)

| Mode | EX | simple | moderate | challenging | Validity | Mean tokens |
|------|-----|--------|----------|-------------|----------|-------------|
| Baseline | 0.474 | 0.588 | 0.456 | 0.353 | 0.978 | 1,010 |
| DIN-SQL | 0.482 | 0.608 | 0.476 | 0.314 | 0.990 | (not tracked) |
| **Full (P2 single-pass)** | **0.501** | **0.622** | **0.482** | **0.373** | **0.996** | 7,975 |

McNemar significance:
- Full vs Baseline: p=0.136 NS (directional only)
- Full vs DIN-SQL: p=0.382 NS

### 11.3 组件归因（Offline ablation on GIS 100）

| Component | Δ questions | Δ EX |
|-----------|-------------|------|
| Safety guardrails | +7 | +0.070 |
| **Semantic grounding** | **+13** | **+0.130** |
| Intent routing | +2 | +0.020 |
| Complex spatial | +2 | +0.020 |
| Regressions | -4 | -0.040 |
| **Net (Full pipeline)** | **+20** | **+0.200** |

Semantic grounding is the dominant contributor (65% of total gain).

---

## 12. 已知限制与未来工作

### 12.1 PostgreSQL/PostGIS 方言耦合

当前 grounding 规则强耦合 PG/PostGIS 语法（`::geography`, `<->`, `ST_*`）。迁移到 MySQL Spatial / Oracle Spatial / SpatiaLite 需替换 dialect-specific 规则字典，但整体架构（语义层 → 意图分类 → grounding → 生成 → 后处理）方言无关。

### 12.2 Token 成本

8-14× baseline。生产建议：
- 使用 P2 单次模式（不要 ADK agent loop）
- 实现 selective grounding：仅注入与意图相关的规则，估计可减 60% prompt
- 考虑模型缓存（Gemini context caching API）

### 12.3 未做但可做

- GeoSQL-Bench (Hou et al. 2025) 跑一遍（如能下载数据集）—— 14,178 题
- 多 LLM 家族对比（DeepSeek、Claude、GPT-4 vs Gemini 2.5 Flash）
- 100+ GIS benchmark 进一步扩展
- Selective grounding 实现 + 评测
- BIRD 中文 100 题完整跑（已生成数据，未跑 baseline + full）
- BIRD warehouse 上达成统计显著超越（当前 NS）

## 12.4 阿布扎比当前实现补充（2026-08）

### 12.4.1 运行入口

```text
@Liveability <question>
  -> data_agent/liveability_nl2sql.py
  -> governed_virtual_nl2sql.run_governed_virtual_nl2sql()
  -> liveability_data_20260730_semantic_layer_v4_full_coverage.json

@Makani <question>
  -> data_agent/makani_nl2sql.py
  -> governed_virtual_nl2sql.run_governed_virtual_nl2sql()
  -> makani_sync_full_semantic_layer_v4_full_coverage.json
```

`execution_profile=baseline_sql` 是当前默认生产路径；`execution_profile=semantic_ir_experimental`
是并行实验路径。两者共享同一 source admission、策略预检、候选资产召回和结果审计，
因此可以做同 case paired comparison。

### 12.4.2 语义层加载和执行授权

v4 配置覆盖全部技术表，但每个 binding 都必须经过 `execution_eligible` 检查：

- `true`：允许进入 SQL validator 或 SemanticQueryIR compiler；
- `false`：允许展示和召回，但只能作为技术目录/待审核资产，不能执行；
- 缺失（仅旧 v3 fixture 兼容）：只有 `review_status` 以 `reviewed` 开头才兼容放行。

产品代码不能通过 benchmark case id、问题原文或具体表名增加特例。任何新别名、关系、
指标合同和敏感字段策略都必须作为版本化语义资产发布，并由测试验证其唯一性和边界。

共享实体名的消歧遵循同一原则：先比较问题中分组/筛选子句引用的物理字段名、语义字段名
和非通用多词字段标签；只有某个已发布 binding 获得严格更强的字段证据时才解除同名门禁。
单词级通用标签（例如对象名本身）不能构成授权；证据相同或不存在时必须返回结构化澄清，
不允许由模型随机选择兄弟资产。

### 12.4.3 SemanticQueryIR 生产路径

1. 模型返回 `GovernedSemanticIRProposal`，不能携带 SQL 或物理表名。
2. `AdHocSemanticQueryIR` 做 schema、聚合、过滤、join 和空间意图校验。
3. 编译器按 `semantic_entity`/`semantic_field` 在 active binding 中解析物理对象。
4. 编译器生成带参数的 Postgres/PostGIS SQL；用户值进入 `sql_params`，不能拼接。
5. SQL 再经过语义表列校验、只读 guard、数据库查询预算和源准入。
6. 失败时返回结构化错误类别；不能降级成“模型直接写 SQL”来掩盖 IR 缺口。

### 12.4.4 离线评估要求

最新 scenario benchmark 必须按 `business_language`、`technical_catalog_control`、`safety` 分桶，
并按 single-table、multi-table equality、multi-table spatial、mixed、language、split 分层。
Gold 只供 evaluator 读取，不能进入运行时 prompt。真实源库离线时，只能运行 artifact/schema
校验、候选召回和 compiler unit tests；不能把历史报告或控制库 healthy 状态当成实时源库验证。

长批次必须固定输入 artifact：runner 启动时记录 benchmark/语义层的规范化 JSON SHA 和原始
字节 SHA，并把启动时语义字节复制为本次运行专用快照。每个 case 发起前复核原文件字节 SHA；
若发生变化，立即取消未开始的 case，checkpoint 写为 `aborted`，并以
`BenchmarkConfigurationError` 终止整批。禁止继续读取同一路径的新内容，也禁止把 artifact
漂移包装为普通 `contract_check_failure`。失败子集恢复报告只能用于验证修复，不能与旧批次的
通过题拼接成新的全量分数。

### 12.4.5 生产前检查清单

- [ ] 两个入口都加载 v4 全表语义层，且 source binding 指纹与发现快照一致。
- [ ] 所有未审核表的 `execution_eligible` 明确为 `false`。
- [ ] 相似资产和数字后缀具备唯一性/歧义回归测试。
- [ ] 公共电话亭等公共设施不被个人敏感数据策略误拒，个人/居民联系方式仍拒绝。
- [ ] baseline 与 IR 路线在相同 benchmark、模型和执行配置下 paired run。
- [ ] 报告和 checkpoint 同时绑定 benchmark/语义层原始字节 SHA，运行期无 artifact 漂移。
- [ ] 结果报告同时提供状态通过率、Gold 等价率、失败分类、P95 耗时和安全 precision/recall。
- [ ] 没有以“总 benchmark 分数”掩盖业务语义覆盖缺口。

### 12.4.6 当前已发布配对证据

`benchmarks/abu_dhabi_nl2semantic2sql_v2/published_report_manifest.json` 是当前已发布的
路线比较入口，绑定 baseline、IR、paired 和 3-run stability 报告的 checksum。它记录的是
同一冻结集上的真实源执行证据，不是把问题或 Gold SQL 缓存到运行时：

| 范围 | baseline_sql | semantic_ir_experimental | 解释 |
|---|---:|---:|---|
| 全部 36 cases 状态合同 | 36/36 | 36/36 | 包含准入/澄清/拒答控制题 |
| 可执行结果等价 | 21/21 | 21/21 | 按 Gold result contract 判断 |
| 自由问数路线配对 | 6/6 | 6/6 | 当前结果持平，样本仍小 |
| 3-run route observations | 17/18 | 17/18 | 稳定性无候选优势 |

因此，当前可以复现和审计的是“新路线已可执行、可独立比较”；不能据此写成“新路线
已经替代基线”或“全表业务语义已经完善”。完整 benchmark 资产的用途和 claim boundary
见 [`docs/nl2semantic2sql_architecture.md`](nl2semantic2sql_architecture.md) 第 13.8 节。

### 12.5 BIRD 上不显著的原因分析

可能因素：
1. 仓库查询的失败模式（join path confusion, aggregation semantics, date parsing）需要更细的 schema 推理，semantic layer 提供的是粗粒度提示
2. 无完整 MetricFlow 覆盖时（仅 1/11 schema 有手工模型），auto-generated 模型质量不足
3. BIRD evidence 字段已经包含很多领域提示，semantic layer 重复提示 → 边际效用低
4. 英文意图分类器对仓库查询的细粒度类型还不够分（aggregation 内部还可分 group_by / window / pivot 等）

---

## 附录 A: 配置参数

```python
# 模型（历史通用配置；阿布扎比产品入口以 12.4 的 GPT-5.1 profile 为准）
MODEL_GENERATION = "gemini-2.5-flash"   # 历史通用主生成模型
MODEL_INTENT_JUDGE = "gemini-2.0-flash"  # 历史意图 LLM judge
MODEL_RETRY = "gemini-2.0-flash"         # 历史自纠错 retry
TEMPERATURE = 0.0
TIMEOUT_GENERATION = 60_000  # ms
TIMEOUT_RETRY = 20_000

# Postprocess
LARGE_TABLE_ROW_THRESHOLD = 1_000_000
LIMIT_INJECTION_VALUE = 1000
MAX_RETRIES = 2

# Semantic layer
SEMANTIC_CACHE_TTL = 300  # seconds (5 min)
TOP_K_CANDIDATE_TABLES = 3
TOP_K_FEW_SHOTS = 3
LOW_CARDINALITY_SAMPLE = 8  # distinct values per text column
```

## 附录 B: 数据库 Schema (关键表)

```sql
-- 数据源元数据
CREATE TABLE agent_semantic_sources (
  id SERIAL PRIMARY KEY,
  table_name TEXT NOT NULL UNIQUE,
  aliases JSONB,
  description TEXT,
  ...
);

-- 列级语义注册
CREATE TABLE agent_semantic_registry (
  id SERIAL PRIMARY KEY,
  table_name TEXT NOT NULL,
  column_name TEXT NOT NULL,
  alias TEXT,
  unit TEXT,
  hierarchy_code TEXT,  -- 用于层次扩展
  ...
);

-- MetricFlow 模型
CREATE TABLE agent_semantic_models (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  yaml_content TEXT,
  parsed JSONB,
  source_table TEXT,
  entities JSONB,
  dimensions JSONB,
  measures JSONB,
  metrics JSONB,
  is_active BOOLEAN DEFAULT TRUE,
  ...
);

-- 历史成功 query（自动 curate, few-shot 来源）
CREATE TABLE agent_reference_queries (
  id SERIAL PRIMARY KEY,
  query_text TEXT NOT NULL,
  response_summary TEXT,        -- 实际是 SQL
  task_type TEXT,                -- 'nl2sql'
  domain_id TEXT,                -- 自动从 SQL 推断的表名
  embedding VECTOR(768),
  upvotes INT DEFAULT 0,
  source TEXT,                   -- 'auto_curate' / 'manual'
  ...
);
```

---

## 附录 C: 与前一版（v1.0）的差异

v1.0（`semantic_layer_architecture.md`，2026-02-27）只覆盖 GIS 场景，本文档新增/重构：

| 内容 | v1.0 | v2.0 |
|------|------|------|
| 双场景统一设计原则 | 无 | §2 完整阐述 |
| 意图分类器（9 类双语） | 无 | §3.1, §4.1 |
| 意图条件化路由 | 无 | §3.3 详细规则表 |
| MetricFlow 自动生成 | 提到未实现 | §4.3, §7.2 完整流程 |
| 仓库 JOIN 路径提示 | 无 | §3.3, §7.1 |
| 自纠错循环 | 简提 | §3.5, §4.6 完整描述 |
| P2 单次模式 vs agent loop | 无 | §3.4 决策依据 |
| 跨语言（中英） | 隐式 | §6.2, §7.3 显式 |
| 端到端调用示例 | 部分 | §8 完整代码 |
| 复现步骤 | 部分 | §10 全流程 |
| 性能数据 | 部分 | §11 三表对比 |
| 限制与 future work | 简提 | §12 详细分析 |

---

**文档版本**: 2.0
**最后更新**: 2026-05-04
**作者**: 周宁 (Beijing SuperMap Software Co., Ltd.)
**邮箱**: zhouning1@supermap.com
**仓库**: https://github.com/zhouning/gisdataagent (branch: `feat/v12-extensible-platform`)
**论文**: `docs/nl2semantic2sql_cross_domain_paper.pdf` (中英双语版)
