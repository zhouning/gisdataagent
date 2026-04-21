# NL2SQL 系统性优化 Phase 1 — Schema 接地 + SQL 后处理

> Date: 2026-04-21
> Branch: feat/v12-extensible-platform
> Benchmark 基线: Gemini 3.1 Pro 50% (10/20), Gemma4 31B 35% (7/20)
> 目标: Gemini 3.1 Pro ≥ 80% (16/20)
> 运行时路径: Custom Skill / @NL2SQL

---

## 1. 问题分析

基于 `benchmarks/chongqing_geo_nl2sql_full_benchmark.json`（20 题）的 3 份 baseline 报告，主失败模式：

| 失败类型 | 占比 | 示例 |
|---|---|---|
| PostgreSQL 大小写标识符 | ~40% | `Floor` → `floor`（UndefinedColumn） |
| 语义召回失败 | ~15% | "中心城区建筑数据" 找不到 `cq_buildings_2021` |
| 安全拦截失败 | ~10% | 模型生成 DELETE/UPDATE 而不是拒绝 |
| LIMIT 丢失 | ~5% | 对 119 万行 POI 表不加 LIMIT |
| 其他（空间函数/逻辑错误） | ~30% | geography 转换遗漏、JOIN 条件错误 |

当前系统的核心缺陷：
- 语义层 9 步解析管线已存在，但 NL2SQL 路径**不强制调用**
- `fetch_nl2sql_few_shots()` 已实现但**从未接入**
- SQL 安全检查只有关键字黑名单，**无 AST 级校验**
- 无 identifier 大小写自动修复机制

---

## 2. 总体架构

```
用户自然语言
    ↓
@NL2SQL Custom Skill
    ↓
工具 1: prepare_nl2sql_context(user_question)
    ├─ resolve_semantic_context(user_text) → sources/columns/hints
    ├─ describe_table_semantic(table) × N → 真实列 schema + quoted_ref
    ├─ fetch_nl2sql_few_shots(user_text, top_k=3) → 历史成功 SQL
    └─ 组装 grounding_prompt → 返回给 LLM
    ↓
LLM 阅读 grounding_prompt，生成 SQL
    ↓
工具 2: execute_nl2sql(sql)
    ├─ postprocess_sql(sql, table_schemas)
    │   ├─ AST 安全校验（sqlglot: 只允许 SELECT/WITH）
    │   ├─ Identifier 修复（column_map 匹配 → 自动加双引号）
    │   ├─ LIMIT 注入（大表无 LIMIT → 追加 LIMIT 1000）
    │   └─ EXPLAIN 干跑（可选，验证结构）
    └─ execute_safe_sql(corrected_sql) → 返回结果
```

---

## 3. 模块设计

### 3.1 nl2sql_grounding.py — 语义接地

核心函数: `build_nl2sql_context(user_text: str) -> dict`

返回:
```python
{
    "candidate_tables": [
        {
            "table_name": "cq_buildings_2021",
            "display_name": "重庆建筑物数据",
            "confidence": 0.85,
            "columns": [
                {"column_name": "Id", "pg_type": "integer", "quoted_ref": "\"Id\"",
                 "aliases": ["建筑编号"], "needs_quoting": True},
                {"column_name": "Floor", "pg_type": "integer", "quoted_ref": "\"Floor\"",
                 "aliases": ["层高", "层数", "楼层"], "needs_quoting": True},
                {"column_name": "geometry", "pg_type": "geometry(Polygon,4326)",
                 "quoted_ref": "geometry", "aliases": [], "needs_quoting": False},
            ],
            "row_count_hint": 107035,
        }
    ],
    "semantic_hints": {
        "spatial_ops": [...],
        "region_filter": None,
        "hierarchy_matches": [...],
        "metric_hints": [...],
        "sql_filters": [...],
    },
    "few_shots": [
        {"question": "...", "sql": "SELECT ..."},
    ],
    "grounding_prompt": "...(组装好的文本块)",
}
```

quoted_ref 判定逻辑:
- 全小写且非 PG 保留字 → 不加引号
- 否则 → `"ColumnName"`

Fallback 策略:
- `resolve_semantic_context` 返回空 sources → `list_semantic_sources()` 全量 + 模糊匹配
- `describe_table_semantic` 失败 → 直接查 INFORMATION_SCHEMA
- `fetch_nl2sql_few_shots` 不可用 → 跳过 few-shot 段
- DB 完全不可用 → 返回空 grounding（退化到当前行为）

### 3.2 sql_postprocessor.py — SQL 后处理

核心函数: `postprocess_sql(raw_sql, table_schemas, large_tables=None) -> PostprocessResult`

返回:
```python
@dataclass
class PostprocessResult:
    sql: str              # 校正后的 SQL
    corrections: list[str] # 修正日志
    rejected: bool        # 是否被安全拒绝
    reject_reason: str    # 拒绝原因
```

4 步处理管线:

1. **AST 安全校验**: sqlglot.parse → 只允许 Select/With 节点类型 → 发现 Insert/Update/Delete/Drop → rejected=True
2. **Identifier 修复**: 从 table_schemas 构建 {lower_name → real_name} map → 遍历 AST Column 节点 → 替换为 quoted real_name
3. **LIMIT 注入**: 无 LIMIT 且涉及 large_tables → 追加 LIMIT 1000
4. **EXPLAIN 干跑**（可选）: EXPLAIN (FORMAT JSON) 验证结构 → 错误附在 corrections

sqlglot 解析失败时 fallback 到正则级修复（word boundary 替换）。

### 3.3 nl2sql_executor.py — 工具函数

两个 ADK FunctionTool:

```python
def prepare_nl2sql_context(user_question: str) -> str:
    """第一步：获取 NL2SQL 上下文（候选表 schema + 语义提示 + 参考 SQL）"""
    ctx = build_nl2sql_context(user_question)
    return ctx["grounding_prompt"]

def execute_nl2sql(sql: str) -> str:
    """第二步：校正并执行 SQL 查询"""
    # 从 ContextVar 获取上一步缓存的 table_schemas
    result = postprocess_sql(sql, _cached_schemas.get(), _cached_large_tables.get())
    if result.rejected:
        return f"安全拒绝: {result.reject_reason}"
    return execute_safe_sql(result.sql)
```

`_cached_schemas` 用 `contextvars.ContextVar` 在 `prepare_nl2sql_context` 时写入，`execute_nl2sql` 时读取。同一轮对话内有效。

### 3.4 NL2SQLEnhancedToolset

```python
class NL2SQLEnhancedToolset(BaseToolset):
    """增强版 NL2SQL: 语义接地 + SQL 后处理"""
    async def get_tools(self, readonly_context=None):
        return [FunctionTool(prepare_nl2sql_context), FunctionTool(execute_nl2sql)]
```

### 3.5 NL2SQL Custom Skill instruction 更新

```
你是 NL2SQL 智能体。严格按以下两步执行：

第一步：调用 prepare_nl2sql_context(user_question=用户原始问题)
  - 获取候选表的真实 schema、语义提示和参考 SQL
  - 仔细阅读返回的列引用格式，PostgreSQL 大小写敏感列必须用双引号

第二步：基于第一步返回的 schema 编写 SQL，然后调用 execute_nl2sql(sql=你的SQL)
  - 系统会自动校正标识符大小写和补充 LIMIT
  - 只允许 SELECT 查询
  - 如果第一步没有找到匹配的表，告知用户并列出可用数据源

绝对禁止：
- 不调 prepare_nl2sql_context 就直接写 SQL
- 生成 DELETE / UPDATE / DROP / INSERT 语句
- 对超过 100 万行的表不加 LIMIT
```

---

## 4. Benchmark 回归

改造 `scripts/nl2sql_bench_cq/run_cq_eval.py`，新增 `--mode enhanced`:

- baseline 模式: 纯 LLM + schema dump（对照组，不变）
- enhanced 模式: grounding + postprocessor + execute_nl2sql

输出 report JSON 与现有格式兼容，增加 `corrections` 和 `postprocessed_sql` 字段。

成功标准: Gemini 3.1 Pro 从 50% (10/20) 提升到 ≥ 80% (16/20)。

---

## 5. 测试策略

| 测试文件 | 覆盖 |
|---|---|
| `test_nl2sql_grounding.py` | build_nl2sql_context 返回结构；fallback 降级；prompt 格式化 |
| `test_sql_postprocessor.py` | identifier 修复（Floor/DLMC/BSM/Id）；LIMIT 注入；安全拒绝 DELETE/UPDATE；sqlglot 失败 fallback |
| `test_nl2sql_executor.py` | prepare + execute 链路；ContextVar 传递 |

关键测试用例直接来自 benchmark 失败模式（CQ_GEO_EASY_01/03, ROBUSTNESS_01/03/04）。

---

## 6. 文件变更清单

| 文件 | 操作 |
|---|---|
| `data_agent/nl2sql_grounding.py` | 新建 |
| `data_agent/sql_postprocessor.py` | 新建 |
| `data_agent/nl2sql_executor.py` | 新建 |
| `data_agent/toolsets/nl2sql_enhanced_tools.py` | 新建 |
| `data_agent/toolsets/__init__.py` | 修改: 注册 NL2SQLEnhancedToolset |
| `data_agent/custom_skills.py` | 修改: VALID_TOOLSET_NAMES 加入 NL2SQLEnhancedToolset |
| `scripts/nl2sql_bench_cq/run_cq_eval.py` | 修改: 新增 --mode enhanced |
| `data_agent/test_nl2sql_grounding.py` | 新建 |
| `data_agent/test_sql_postprocessor.py` | 新建 |
| `data_agent/test_nl2sql_executor.py` | 新建 |
| `requirements.txt` | 修改: 加 sqlglot |

---

## 7. 不做的事

- 不改 `resolve_semantic_context` 的签名或逻辑
- 不改 `execute_safe_sql` 的接口
- 不改 GeneralPipeline / Planner 的 agent 结构（Phase 2）
- 不做自纠错循环（Phase 2）
- 不做 SQL 方言转换（只做 PostgreSQL）
- 不改前端

---

## 8. 后续阶段预告

- Phase 2: 自纠错循环（执行失败 → 反馈错误 + schema → LLM 重写，max 2 次）+ few-shot 自动入库
- Phase 3: 统一 NL2SQL 路径（GeneralPipeline + Planner 都走增强版）+ SemanticPreFetch 泛化
