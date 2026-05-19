# FloodSQL-Bench 分析报告

**Generated**: 2026-05-18  
**Source**: `D:/adk/data/floodsql_bench_repo/` (论文 commit Dec 16 2025)  
**Paper**: arXiv 2512.12084 (Liu et al., Texas A&M)  
**目的**: 评估 v7 NL2Semantic2SQL stack 迁移到 FloodSQL-Bench 的工作量

## 一句话
**几乎零迁移成本**：DuckDB→PostGIS 只需改 1 题 STRFTIME；443 题 + 10 表 + 完整 gold output 已就绪；可直接用 v7 EX 评估器跑（不需复刻论文 embedding cosine 方法）。

## 数据资源

### 数据库表（10 个 parquet, 2.5 GB）
| 表 | 行数 | 列数 | 类型 | 关键 |
|---|---|---|---|---|
| `claims` | 1,316,689 | 8 | NFIP 洪水理赔 | GEOID 11 位 |
| `floodplain` | 915,760 | 4 | FEMA 洪泛区多边形 | spatial-only |
| `census_tracts` | 13,444 | 5 | 普查 tract 边界 | GEOID 11 位 |
| `cre` | 13,444 | 20 | Community Resilience | GEOID 11 位 |
| `nri` | 13,373 | 50 | FEMA 国家风险指数 | GEOID 11 位 |
| `svi` | 13,385 | **159** | CDC 社会脆弱指数 | GEOID 11 位 |
| `schools` | 19,669 | 11 | 学校点位 | LAT/LON |
| `hospitals` | 1,526 | 13 | 医院点位 | LAT/LON |
| `county` | 385 | 5 | 县边界 | GEOID 5 位 |
| `zcta` | 5,284 | 3 | ZIP code 边界 | spatial-only |

### 题库（443 题）
- `bechmark_updated.jsonl` (443 题, **论文版**)
- `benchmark.jsonl` (450 题, 旧版, 7 题被删 + 21 题改 SQL)
- 6 难度子目录每个有自己的 `{N}.json` + `_results.jsonl` + `_error_ids.txt`

### 题目结构
```json
{
  "id": "L0_0001",
  "question": "In Harris County, Texas...",
  "sql": "SELECT COUNT(*)...",
  "elapsed": 0.054,
  "row_count": 1,
  "result": [[75192]]    // gold output, 已预跑
}
```

## 难度分布

| Level | n | 类型 | 平均 SQL 长度 | %ST_ | %JOIN | %GROUP BY |
|---|---|---|---|---|---|---|
| L0 | 50 | 单表 | 111 | 24% | 0% | 8% |
| L1 | 100 | 双表 key | 193 | 2% | 100% | 45% |
| L2 | 150 | 双表 spatial | 232 | 100% | 100% | 53% |
| L3 | 50 | 三表 key-key | 281 | 2% | 100% | 52% |
| L4 | 43 | 三表 key-spatial | 300 | 100% | 95% | 28% |
| L5 | 50 | 三表 spatial-spatial | 330 | 100% | 100% | 16% |

**总 443 = 50+100+150+50+43+50** （L4 是 43 不是 50）

## SQL 操作分布

### 空间函数（PostGIS 标准命名）
- `ST_Intersects` 23.5% (104)
- `ST_Point` 25.5% (113)
- `ST_Contains` 16.5% (73)
- `ST_Within` 12.6% (56)
- `ST_Area` 8.8% (39)
- `ST_IsValid` **53%** (235)
- `ST_Centroid` 0.2% (1)
- 不用 ST_Distance/ST_DWithin/ST_Transform/ST_Buffer

### 关系操作
- `JOIN` 88.3%（L1+ 几乎 100%）
- `DISTINCT` 56.9%（COUNT DISTINCT 防膨胀）
- `ORDER BY` 41.8%
- `LIMIT` 41.1%
- `GROUP BY` 39.3%
- `WITH` 4.3%
- `DATE 'YYYY-MM-DD'` 5.2%

## DuckDB → PostGIS 兼容性

### ⚠️ 需转换（仅 1 题）
| 题 | DuckDB 写法 | PG 替换 |
|---|---|---|
| L1_0001 | `STRFTIME('%Y', dateOfLoss)` | `EXTRACT(YEAR FROM dateOfLoss)::TEXT` |

### ✅ 直接兼容（其余全部）
- `LEFT(geoid, 5)` — PG 9.1+ ✓
- `CAST(... AS ...)` — 标准 SQL ✓
- `::numeric / ::int` — PG 标准 ✓
- `PERCENTILE_CONT/DISC` — PG 9.4+ ✓
- 所有 ST_* 函数命名一致 ✓
- `DATE 'YYYY-MM-DD'` — PG 标准 ✓
- `IS NOT NULL` / `BETWEEN` — 标准 ✓
- `ILIKE` — PG 原生（DuckDB 也用）✓

### 0 处出现的 DuckDB 特有
- `READ_PARQUET()` 0
- `INSTALL/LOAD spatial` 0
- `TRY_CAST` 0
- `DOUBLE`/`DOUBLE_PRECISION` cast 0
- `LIST_*` / `STRUCT_*` / `MAP_*` 0
- `STRING_AGG` 0（PG 也支持）

## 跟 CQ 重庆 benchmark 对比

| 维度 | CQ 重庆 (你的 v7) | FloodSQL-Bench |
|---|---|---|
| 题数 | 125 | **443** |
| 语言 | 中文 | 英文 |
| 评分 | EX (执行准确率) | embedding cosine（论文）|
| DB | PG/PostGIS | DuckDB（**易迁 PG**）|
| 难度 | 单/双/三表混合 | L0-L5 严格分级 |
| 域 | 通用 GIS | 洪水风险（窄域）|
| 中文列名 | 是（DLMC、TBMJ 等）| 无 |
| 表数 | ~10 | 10 |
| 总数据量 | ~150 万行 | ~230 万行 |
| Schema 复杂度 | 中（10-20 列/表）| **高**（svi 159 列！）|
| Gold 已预跑 | 是 | **是**（result 字段）|
| Schema dump | 已有 | 待生成 |
| Few-shot 例子 | 已有 | 待生成 |

## 方法学对比

### 论文方法（不复刻）
- **评估**: OpenAI text-embedding-3-large + Jina v3 余弦相似度
- **检索**: 双层 RAG (table → column)，纯 metadata-driven
- **Pipeline**: 单次 LLM 生成（无自纠错）
- **优点**: 不跑 SQL → 不会 timeout，对 long-running spatial query 友好
- **缺点**: SQL 字面相似 ≠ 结果相同；无法证明真"对"

### v7 NL2Semantic2SQL（你的方法）
- **评估**: Execution Accuracy（你的 LIMIT-fallback evaluator）
- **检索**: 语义层 grounding (table_hints + column_hints + business rules)
- **Pipeline**: 多次 LLM 调用 + tool use + self-correction (R1-R8)
- **优点**: 真值，可跟 gold result 直接比对
- **缺点**: timeout 风险（FloodSQL 有大量 spatial join）

## 灌库 + 评估工作量

### Phase 1: 灌库（~半天）
1. 创建 PG schema `floodsql`（避免污染 `public`）
2. parquet → PG（10 表）：用 `pyogrio` 或 `geopandas.to_postgis`
3. **关键索引**：geometry 上加 GIST，GEOID/STATEFP 上加 BTREE
4. 验证：跑 `bechmark_updated.jsonl` 头 5 题确认 SQL 都执行得通

### Phase 2: 转 1 题 STRFTIME
- L1_0001 用 `EXTRACT(YEAR FROM dateOfLoss)::TEXT`

### Phase 3: 跑 baseline+full 横评（~12-20h）
- 用 v7 的 9 家族
- 重用 `run_v7_smoke_b.py` 入口（参数化 benchmark 路径）
- N=1 先看趋势，N=3 paper-grade

### Phase 4: 论文层面对比
- 你的 EX (FloodSQL) vs 论文 embedding cosine
- L0-L5 难度分级 → CQ 重庆没有这种 strict tiering，对照价值高
- 可以做"中文域 vs 英文域 vs 难度递进"三维 scaling 分析

## 推荐下一步顺序

1. **现在（不影响后台）**：写 `parquet → PG` 灌库脚本 + DDL
2. **9 家族 N=3 跑完后**（明早）：跑灌库 + 验证 5 题 SQL
3. **灌库验证通过后**：跑 v7 stack 在 FloodSQL N=1 smoke（gemini-flash），看初步数字
4. **smoke OK 后**：完整 9 家族 N=3 跑 FloodSQL（隔夜）

## 关键风险

1. **floodplain 90 万 + 复杂 polygon-polygon JOIN**：spatial join 可能 timeout。论文用 embedding cosine 绕过，你用 EX 必须真跑——需要 GIST 索引 + 适当 statement_timeout
2. **svi 159 列**：grounding 的 column hints 可能选不准 → 加大 top-K 列数或要更精细 prompt
3. **DuckDB result 类型** vs **PG result 类型**：浮点精度可能差异（同 v7 EASY_20 案例），需检查
4. **gold result 是 DuckDB 跑出来的**：在 PG 重跑后值可能不完全一致（特别是 spatial calcs）

## 文件位置速查

```
D:/adk/data/floodsql_bench/                       # HF 下载的纯数据（parquet）
D:/adk/data/floodsql_bench_repo/                   # GitHub clone（含题目+脚本+数据）
  benchmark/bechmark_updated.jsonl                # ⭐ 443 题最终版
  benchmark/benchmark.jsonl                       # 450 题旧版
  benchmark/{single_table,...}/                   # 6 难度子目录
  scripts/run_and_eval/eval.py                    # 论文 embedding 评估器
  scripts/generate_metadata.py                    # 论文 RAG 元数据生成
  data/                                            # 数据 parquet（同 HF）
  download_hf.py                                   # HF 下载脚本
```
