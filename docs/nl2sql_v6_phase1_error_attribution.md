# NL2SQL v6 — 17 个 Grounding-Reversal QID 的 Error Attribution

**Date**: 2026-05-10
**Source**: `docs/nl2sql_v6_grounding_reversal_17.json`
**Scope**: 用 Fix 0 (thinking=disabled + timeout=240s) 之后，DS baseline MV=1 但 DS full MV=0 的 17 个 qid。这就是 `within_family_deepseek` McNemar 的 c 桶——"grounding + agent loop 反而让 DS 做得比 baseline 差"的证据。

---

## TL;DR — 失败模式分布

51 条记录（17 qid × 3 sample）按 DS full 的具体错法分类：

| 失败模式 | 记录数 | 占比 | 主要表现 |
|---|---:|---:|---|
| **A. Projection drift（投影漂移）** | 17 | 33% | 加了没要的列（COUNT、ROUND、CASE 重命名、辅助列） |
| **B. Intent over-interpretation（意图过度解读）** | 12 | 24% | COUNT 被替换成 listing，或反过来 |
| **C. Silent refusal → EMPTY** | 7 | 14% | agent loop 走完也没调 query_database |
| **D. Numeric formatting（数值格式化副作用）** | 5 | 10% | `ROUND(AVG, 2)` / `COALESCE(...0)` 改变了数值表达 |
| **E. Over-engineering spatial predicates** | 5 | 10% | `ST_DWithin(..., 0.00005)` 替代 `ST_Intersects` |
| **F. Hallucinated table name** | 3 | 6% | 把 CSV 缓存路径当 table 名（`cq_query_result_xxx`） |
| **G. Give-up SQL** | 2 | 4% | `SELECT 1 AS test` |

**最大的两个杠杆**：A（33%）+ B（24%）= 57% 的失败是 **"DS 想帮用户多做一点"** 导致的——加辅助列、换更友好的表达、把 COUNT 展开成 listing。

---

## 分桶详单

### A. Projection drift（17 records）

DS full 在 SELECT 子句里多加了没被要求的列。

#### CQ_GEO_EASY_09 (Attribute Filtering)
- **Q**: "列出权属单位名称 ZLDWMC" （只要一列）
- **baseline** (3/3 correct): `SELECT "ZLDWMC" FROM cq_land_use_dltb WHERE "DLMC"='村庄' LIMIT 100`
- **full** (1/3 correct): s1 `SELECT "DLMC", "ZLDWMC" ...`（多加 DLMC），s2 `SELECT "BSM", "DLMC", "ZLDWMC" ...`（多加 BSM 和 DLMC）
- **Why**: grounding 提示 DLMC 是权属关键字段，agent 把"已使用在 WHERE 里的列"一并 SELECT 出来作为 context。这对人类友好，对 rowset 比较致命。

#### CQ_GEO_HARD_01 (Proximity Buffer)
- **Q**: 求"三甲医院周围 500m 建筑平均层高"
- **gold**: `SELECT AVG(b."Floor") ...`（1 列）
- **full** s1: `SELECT COUNT(*) AS 匹配建筑数量 ...`（完全换了聚合函数）
- **full** s2: `SELECT COUNT(*), ROUND(AVG,2) ...`（多加了 COUNT）
- **full** s3: `SELECT ..., 4 列 CTE ...`

#### CQ_GEO_HARD_03 (Spatial Topology)
- **Q**: "与道路相交的水田总面积"（1 列 SUM）
- **full** s1: `SELECT COUNT(*) AS 相交图斑数, ROUND(SUM(area)) AS ... ` (2 列)
- **full** s2: `SELECT ROUND(SUM(area)), COUNT(DISTINCT BSM) ...` (2 列)
- **full** s3: `SELECT 1 AS test LIMIT 100000`（直接放弃）

#### CQ_GEO_HARD_16 (Complex Multi-Step)
- **Q**: "使用 CTE 先找大于平均 TBMJ 的有林地图斑，再统计与道路相交的数量"
- **full** s1: CTE 里 SELECT "BSM", "TBMJ", "geometry"（多列），最终聚合还多了一列
- **full** s2: 调用了错误的缓存表名（见 Pattern F）
- **full** s3: 正确

---

### B. Intent over-interpretation（12 records）

DS full 把用户的意图曲解——COUNT 变 listing，或 listing 变 GROUP BY。

#### CQ_GEO_EASY_12 (Attribute Filtering)
- **Q**: "统计图斑数量"（COUNT(*)）
- **baseline** (3/3): `SELECT COUNT(*) FROM ... WHERE "DLMC"='果园'`
- **full** s1/s2 (0/2): `SELECT * FROM ... WHERE "DLMC"='果园' LIMIT 100000` （3428 行 vs 预期 1 行）
- **Intent classifier**: `attribute_filter`（错；应该是 aggregation）
- **Why**: intent router 误路由成 attribute_filter → agent 按 "列出属性" 的模式生成 listing。baseline 没走 intent router，直接按 question 语义生成了 COUNT。

#### CQ_GEO_EASY_17 (Aggregation)
- **Q**: "统计有多少种不同的地类名称"（COUNT DISTINCT）
- **baseline** (3/3): `SELECT COUNT(DISTINCT "DLMC") FROM cq_land_use_dltb`
- **full** s1/s2: `SELECT DISTINCT "DLMC" FROM ... ORDER BY "DLMC"` （列出 24 种，不是 COUNT）
- **Why**: 同样是 intent 把 aggregation 丢了 → 退化成 listing。

#### CQ_GEO_EASY_02 (Attribute Filtering)
- **Q**: "maxspeed>100 AND fclass='primary' 的 name" （一维过滤）
- **full** s2: `SELECT DISTINCT "maxspeed" FROM ... WHERE "fclass" = 'primary'` — **丢掉了 maxspeed>100 过滤** 并改变了 SELECT 目标
- **full** s3: `SELECT "maxspeed", COUNT(*) GROUP BY "maxspeed"` — 完全换成了 aggregation
- **Intent classifier**: `preview_listing`（错；应该是 attribute_filter）

#### CQ_GEO_HARD_08 (Aggregation)
- **Q**: "按 fclass 和 bridge 分组统计"
- **baseline** (3/3): `... GROUP BY fclass, bridge`
- **full** s1/s2: `... CASE WHEN bridge='T' THEN '是桥梁' ELSE '非桥梁' END AS 是否桥梁 GROUP BY fclass, CASE ...` — **把原始 bridge 值改成中文标签**
- **full** s3: `SELECT DISTINCT "bridge"` — 退化成 listing
- **Intent classifier**: `attribute_filter`（错；应该是 aggregation）

#### CQ_GEO_MEDIUM_12 (Aggregation)
- **Q**: "按 fclass 分组，AVG 和 MAX maxspeed, HAVING AVG>20, ORDER BY avg DESC"
- **full** s1: `SELECT COUNT(*), COUNT(maxspeed)` — 完全不同的聚合
- **full** s2/s3: GROUP BY 部分对了，但加了 NULLS LAST / FILTER (WHERE maxspeed IS NOT NULL) / ROUND(2) — 结果集与 gold 不匹配

---

### C. Silent refusal → EMPTY（7 records）

Agent loop 跑完但 `pred_sql=""`，tokens=0 → 被 120/240s timeout 或 loop-exit 切掉。Fix 0 把 EMPTY 从 51 降到 27 但还有剩余。

- **CQ_GEO_MEDIUM_04 (Spatial Filtering)**: 3/3 EMPTY。Baseline 用 ST_Union 子查询能做出来。
- **CQ_GEO_HARD_21 (Cross-Table)**: 3/3 EMPTY。需要三表 JOIN（POI / historic_districts / dltb）。
- **CQ_GEO_MEDIUM_27 s3 (KNN)**: 1/3 EMPTY。

---

### D. Numeric formatting side-effects（5 records）

对 AVG / SUM 做 `ROUND(..., 2)` 或 `COALESCE(..., 0)` → gold_rowset 比较失败。

- **CQ_GEO_EASY_15 (Aggregation)**: 3/3 都错。Q 要 `MAX/MIN/AVG("Floor")`，full 把 AVG 改成 `ROUND(AVG("Floor")::numeric, 2)` → 数值不同。gold=某个 float，pred=保留 2 位小数，比较失败。
- **CQ_GEO_HARD_05 (Spatial Geometry Creation)**: full 用 `COALESCE(ROUND(...,3), 0)` 把 NULL 替换成 0，gold 是 NULL。

**Why**: instruction 里原本有 "For ROUND: ROUND(expr::numeric, N)"，这个规则被 DS 理解成"**总是**应该 ROUND 聚合结果"。

---

### E. Over-engineering spatial predicates（5 records）

DS 用更"技术上正确但语义不同"的谓词替代 ST_Intersects。

- **CQ_GEO_HARD_10 (Spatial Join)**: gold 用 `ST_Intersects(r.geometry, p.geometry)`, full 用 `ST_DWithin(..., 0.00005)` 或 `ST_DWithin(..., 0.00001)`（数学上不等价）
- **CQ_GEO_HARD_14 (KNN)**: DS 在子查询里加 `ORDER BY "ID" LIMIT 1`，baseline 不加排序直接 LIMIT 1。不同 POI 被选到 → 不同建筑数量。

---

### F. Hallucinated table name（3 records）

- **CQ_GEO_HARD_16 s2**: `SELECT * FROM public.cq_query_result_5f273c3a LIMIT 100000`
- **CQ_GEO_EASY_20 s? 和 HARD_22 s?** (observed in earlier EMPTY analysis): `FROM "D:\\adk\\data_agent\\uploads\\cq_benchmark\\query_result_xxx.csv"`
- **Why**: agent 的 tool context 里出现过临时 CSV 缓存路径，DS 把它当 table 名 hallucinate 回来。Gemini 不会。

---

### G. Give-up SQL（2 records）

- **CQ_GEO_HARD_03 s3**: `SELECT 1 AS test LIMIT 100000`
- **CQ_GEO_HARD_08 s3**: `SELECT DISTINCT "bridge" FROM cq_osm_roads ORDER BY "bridge"` — 注意用的是 `cq_osm_roads` 不是 `cq_osm_roads_2021`，table name 也错

---

## 对 Phase 1 DS Adapter 设计的直接 implications

按 attribution 证据推出 DS 专属 prompt 需要做的 7 件事（按预期 lift 排序）：

### 1. 抑制 projection drift（覆盖桶 A，17 records）

**规则**：DS prompt 增加硬约束 "**SELECT 子句只包含用户在 question 中明确要的字段**。不要加 WHERE 用到的列、不要加 'BSM' / 'ID' 辅助列、不要为了可读性添加列"。

配合：few-shot 示范"简洁 SELECT"的 3-5 个正例。

### 2. 抑制 intent over-interpretation（覆盖桶 B，12 records）

**问题根因**：intent router 在 DS 上把 aggregation 误路由成 attribute_filter / preview_listing 太频繁。

**两种修法**：
- **选项 A（保守）**：DS 版 prompt 增加 "如果 question 含 'COUNT' / '多少' / '数量' / '统计' / '几种' / 'DISTINCT' → 不管 intent router 说什么，都必须生成 aggregation SQL"
- **选项 B（激进）**：DS 路径完全绕过 intent router，直接让 DS 从 question 语义推断。配合 few-shot 里每种 intent 3-5 个正例。

**看数据**：baseline 无 intent router 反而做得对 17/17 — 至少在这些 qid 上，intent router 是负资产。建议选项 B。

### 3. 抑制 numeric formatting side-effects（覆盖桶 D，5 records）

**规则**：DS prompt 里原本的 "For ROUND: ROUND(expr::numeric, N)" 改成 "**只在用户明确要求保留小数位时才用 ROUND**。对 MAX / MIN / AVG / SUM 的 raw 返回值不要加任何数值包装（不要 ROUND, 不要 COALESCE, 不要 CAST AS TEXT）"。

### 4. 约束 spatial predicate 选择（覆盖桶 E，5 records）

**规则**：DS prompt 增加 "**相交判断只用 `ST_Intersects`**。除非用户明确提到距离阈值（如 '500 米内'），否则不要用 `ST_DWithin`。不要猜距离阈值"。

### 5. 解决 hallucinated table name（覆盖桶 F，3 records）

**规则**：DS prompt 增加 "**只能使用 schema 中明确列出的表名**。以下格式绝对不是表名：任何带 `cq_query_result_`、`uploads\\`、`.csv` 后缀、路径分隔符 `/` 或 `\\` 的字符串"。

配合：runner 在 tool_execution_log 里不要 leak CSV 缓存路径给 DS（Gemini 也不会受影响，但清理一下更干净）。

### 6. EMPTY 桶剩余问题（覆盖桶 C，7 records）

**做法**：
- Fix 1 runner 文本兜底 SQL 提取（独立做，优先级高）
- Phase 1 DS adapter 额外：要求 DS 在 tool loop 第一轮就**必须**调 query_database；如果它想先调 resolve_semantic_context / describe_table，需要在"计划一次、执行一次"的严格协议下运行（避免无限 exploration）

### 7. Give-up SQL（覆盖桶 G，2 records）

**做法**：在 runner 侧加一个后处理 guard：如果 `pred_sql` 匹配 `SELECT 1 AS test` / `SELECT 1 LIMIT` 这类占位 SQL → 直接判定为 agent-failure 而非 wrong，记录为 `ABORTED` 桶。这样我们能看到真实的"DS 放弃"比例。产品层面：这种场景可以 trigger retry 或 fallback。

---

## 预估 Phase 1 DS Adapter 的 lift

保守估计（每一桶修复率按 50-70%）：

| 桶 | 当前 failure records | 修复率估计 | 回收 records | 对应 qid |
|---|---:|---:|---:|---:|
| A (projection drift) | 17 | 60% | 10 | ~3-4 qid |
| B (intent over-interpret) | 12 | 70% | 8 | ~3 qid |
| C (EMPTY) | 7 | 60% | 4 | ~1-2 qid |
| D (ROUND) | 5 | 80% | 4 | ~1-2 qid |
| E (spatial predicate) | 5 | 50% | 3 | ~1 qid |
| F (hallucinate table) | 3 | 80% | 2 | ~1 qid |
| G (give up) | 2 | 50% | 1 | — |
| **合计** | **51** | — | **~32** | **~10-12 qid** |

**预估 qid-level 回收**：17 个 grounding-reversal qid 中可能修复 10-12 个。

配合 Phase 2 runner 健壮性（Fix 1 文本兜底），Cross-family full MV EX 的 `b/c` 有望从 17/17 变成 **22-24 / 5-7**（Fix 0 下的 b=c=17 是一个对称的基准线）。

**投影 DS full MV EX**: 0.529 → **0.62-0.66**  
**投影 within-family Δ**: 0.000 → **+0.09 ~ +0.13**, p ~0.01-0.05

**大概率过及格线**（Δ ≥ +0.08, p < 0.10）。

---

## 要求 Phase 1 设计文档回答的问题

1. `data_agent/prompts/` 目录结构改成什么？谁使用哪个？
2. `nl2sql_agent.py` 的 instruction 拆分规则：common 放什么，per-family 放什么？
3. 如何在 model_gateway 里选 prompt namespace？
4. Intent router 对 DS 是否绕过？如果绕过，DS 版 few-shot 的组织形式？
5. 运行时 guards（给 DS 用，对 Gemini 不启用）放哪里？

这些是下一个文档的工作。
