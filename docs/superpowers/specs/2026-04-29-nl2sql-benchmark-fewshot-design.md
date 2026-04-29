# NL2SQL benchmark uplift design

## Context

Current NL2SQL benchmark status is 14/16 pass. The remaining failures are not caused by missing tables or broken grounding; they are model reasoning failures on two reusable spatial query patterns:

1. **AOI distance + building attribute filter** (`HARD_01`)
   - User asks for buildings within a distance of a named AOI and filtered by floor count.
   - Grounding already finds the correct tables/columns, but the model refuses instead of composing the spatial SQL.

2. **Polygon intersection + aggregated area output** (`MEDIUM_04`)
   - User asks for overlap/intersection area between two polygon layers.
   - The model computes per-piece areas but omits the final `SUM(...)`, returning fragments instead of a single total.

The codebase already has a reusable few-shot retrieval layer via `agent_reference_queries` and `fetch_nl2sql_few_shots()`. The goal is to improve benchmark pass rate by adding **reusable NL2SQL spatial patterns**, not benchmark-specific hardcoded text.

## Recommended approach

Add **two canonical NL2SQL reference queries** to `agent_reference_queries`, both tagged with `task_type='nl2sql'`, so the existing embedding-based few-shot retrieval can surface them naturally for semantically similar questions.

This approach is preferred over benchmark-specific patches because it improves real user queries of the same type and does not require branching logic in the NL2SQL pipeline.

## Scope

In scope:
- Add two reusable spatial few-shots to the reference query store
- Use abstracted natural-language pattern text, not benchmark-specific wording only
- Validate improvement on `HARD_01` and `MEDIUM_04`

Out of scope:
- Changing model provider logic
- Adding hardcoded query templates in prompt/router code
- Changing benchmark golden SQL beyond already completed fixes
- Introducing a new retrieval subsystem

## Canonical few-shot patterns

### Pattern A: AOI distance + building attribute filter

**Purpose**
Teach the model the pattern:
- named AOI lookup
- spatial distance search around AOI
- building attribute filter on floor count
- return building identifiers and height/floor data

**Representative natural-language query_text**
A generic phrasing such as:
- 查找某个 AOI 周边指定距离范围内、满足楼层数条件的建筑物，并返回建筑物 ID 和楼层数

This should mention:
- AOI / 兴趣区 / 景点区域
- 周边 / 距离 / 米
- 建筑物
- 楼层数 / 层高

**Canonical SQL shape**
```sql
SELECT b."Id", b."Floor"
FROM cq_buildings_2021 b
JOIN cq_baidu_aoi_2024 a
  ON ST_DWithin(
       b.geometry::geography,
       ST_Transform(a.shape, 4326)::geography,
       1000
     )
WHERE a."名称" LIKE '%解放碑%'
  AND b."Floor" > 30;
```

**What this teaches**
- AOI polygon needs transform to 4326 before geography cast
- distance query should use `ST_DWithin(...::geography, ...::geography, meters)`
- attribute filter remains a normal numeric predicate
- output is a raw row list, not an aggregate

### Pattern B: Polygon intersection + total area aggregation

**Purpose**
Teach the model the pattern:
- polygon/polygon overlap
- compute intersection geometry
- aggregate all pieces into one final total area
- convert square meters to hectares when requested

**Representative natural-language query_text**
A generic phrasing such as:
- 计算两个规划区/管制区图层的空间交集总面积，并以公顷返回单个结果

This should mention:
- 两个面图层
- 重叠 / 交集
- 总面积
- 公顷 / 平方米

**Canonical SQL shape**
```sql
SELECT
  SUM(ST_Area(ST_Intersection(j.shape, g.shape))) / 10000.0 AS intersect_area_ha
FROM cq_jsydgzq j
JOIN cq_ghfw g
  ON ST_Intersects(j.shape, g.shape);
```

**What this teaches**
- `ST_Intersects` is the join predicate
- `ST_Intersection` computes overlap geometry
- **must** wrap with `SUM(...)` to return one total
- projected CRS means direct `ST_Area(...)` is valid
- hectares require `/ 10000.0`

## Data model / storage plan

Reuse `agent_reference_queries` with existing schema.

For each inserted example:
- `query_text`: abstract reusable natural-language pattern
- `description`: what spatial pattern the example teaches
- `response_summary`: canonical SQL
- `task_type`: `nl2sql`
- `pipeline_type`: optional `general` or null depending on existing conventions
- `tags`: JSON/array tags like:
  - Pattern A: `spatial`, `distance`, `aoi`, `buildings`, `dwithin`
  - Pattern B: `spatial`, `intersection`, `area`, `aggregation`, `polygon`
- `source`: something explicit like `benchmark_pattern`

## Retrieval behavior expectations

No retrieval code changes are required for the initial version. The current `fetch_nl2sql_few_shots()` flow should remain unchanged and simply gain better candidates to retrieve.

Expected behavior:
- `HARD_01` should retrieve Pattern A due to AOI + distance + building/floor semantics
- `MEDIUM_04` should retrieve Pattern B due to overlap/intersection + area aggregation semantics

## Validation plan

### Functional checks

1. Re-run `HARD_01`
   - Expected: no refusal
   - Expected shape: `Id`, `Floor` rows
   - Expected benchmark outcome: 698 rows

2. Re-run `MEDIUM_04`
   - Expected: one aggregated area result
   - Expected value: `578.374210417018` hectares
   - Failure condition: multiple fragment rows instead of one total

### Regression checks

Spot-check that these still behave correctly after adding few-shots:
- `HARD_02` line/polygon intersection count
- `HARD_03` top-5 search index aggregation
- `ROBUSTNESS_01/04` write-operation refusal

The risk is low because few-shots are additive and retrieval-ranked, but benchmark verification should confirm they do not distort unrelated simple queries.

## Files / systems involved

Primary:
- `data_agent/reference_queries.py`
- `data_agent/api/reference_query_routes.py`
- database table `agent_reference_queries`

Validation targets:
- `benchmarks/chongqing_geo_nl2sql_full_benchmark_v2.json`

Potential helper touchpoints only if needed:
- `data_agent/nl2sql_grounding.py`
- `data_agent/nl2sql_executor.py`

## Risks and mitigations

### Risk 1: Few-shot too benchmark-specific
**Mitigation:** phrase `query_text` as generalized user intent, not copied benchmark wording.

### Risk 2: Retrieval does not pick the new examples reliably
**Mitigation:** include high-signal semantic words in `query_text` and tags; validate with the two target benchmark questions.

### Risk 3: Few-shot hurts unrelated queries
**Mitigation:** keep examples narrowly scoped to two distinct spatial patterns and run spot regressions.

## Recommendation

Proceed with **two reusable spatial few-shots only**, using the current reference-query retrieval stack. This is the smallest change that has a credible path to lifting benchmark performance from **14/16 to 16/16** while still benefiting real NL2SQL usage outside the benchmark.
