# D1 Universal-Fail Audit (v7 P1)

Auto-generated from `audit_d1_universal_fails.py`.
Source: `data_agent\nl2sql_eval_results\v7_p1_main_n3_2026-05-13_172802` + `data_agent\nl2sql_eval_results\v7_p1_gemma_n1_2026-05-13_172807`.
Families: ['deepseek-v4-flash', 'deepseek-v4-pro', 'gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-3.1-flash-lite-preview', 'gemini-3.1-pro-preview', 'gemma-4-31b-it-ollama', 'qwen3.6-flash', 'qwen3.6-plus']
Universal-fail qids: **14**

Heuristic verdict legend (checked in order):
- **LIKELY GOLD-EMPTY BUG** — gold returns 0 rows but pred returns >0 (gold filter broken)
- **LIKELY EVALUATOR BUG** — rowset_mismatch dominates + many pred byte-identical to gold (row order / float precision)
- **LIKELY EVALUATOR / GOLD STRICTNESS** — rowset_mismatch dominates but pred SQLs differ (gold filter narrow)
- **LIKELY GOLD UNDER-SPEC** — col_count dominates, pred consistent on different count (gold needs more cols)
- **LIKELY GOLD ROW-COUNT OFF** — row_count dominates, pred consistent on different count (gold limit wrong)
- **LIKELY GOLD STRICTNESS (filter ambiguity)** — row_count dominates, pred varies (gold filter too narrow, e.g. enum synonyms)
- **LIKELY HARD QUERY** — empty pred dominates with timeouts
- **LIKELY MODEL ISSUE** — empty pred dominates without timeouts
- **MODEL BUG (qwen-plus CSV leak)** — sql_error from file-path leak (Qwen-plus only)
- **MIXED** — manual review required

---

## Verdict summary

| verdict | count |
|---|---|
| LIKELY EVALUATOR / GOLD STRICTNESS | 5 |
| LIKELY EVALUATOR BUG | 2 |
| LIKELY GOLD UNDER-SPEC | 2 |
| LIKELY GOLD-EMPTY BUG | 2 |
| LIKELY GOLD ROW-COUNT OFF | 2 |
| LIKELY GOLD STRICTNESS (filter ambiguity) | 1 |

---

## `CQ_GEO_EASY_02` — Attribute Filtering / Easy

**Question**: 我想知道哪些主干道的限速超过了 100，把这些路的名字列出来。

**Gold SQL** (cols=1):
```sql
SELECT name FROM cq_osm_roads_2021 WHERE maxspeed > 100 AND fclass IN ('primary', 'motorway');
```

**Failure reason buckets** (total 24):
- `row_count`: 22
- `empty`: 2

**Raw failure reason distribution** (total 24 samples):
- `row count: gold=3 pred=2`: 10
- `row count: gold=3 pred=0`: 7
- `row count: gold=3 pred=4`: 4
- `empty`: 2
- `row count: gold=3 pred=11`: 1

**gen_status distribution**:
- `ok`: 22
- `timeout`: 2

**Col-count (gold, pred) distribution**:
- gold=1 / pred=1: 17
- gold=1 / pred=3: 3
- gold=1 / pred=2: 2
- gold=1 / pred=None: 2

**Row-count (gold, pred) distribution** (only when reason=row_count):
- gold_rows=3 / pred_rows=2: 10
- gold_rows=3 / pred_rows=0: 7
- gold_rows=3 / pred_rows=4: 4
- gold_rows=3 / pred_rows=11: 1

**Distinct pred_sql** (top 10):
- [2× first=qwen3.6-flash] `<EMPTY>`
- [1× first=deepseek-v4-flash] `SELECT name, fclass, maxspeed FROM cq_osm_roads_2021 WHERE fclass IN ('primary', 'trunk') AND maxspeed > 100 AND name IS NOT NULL AND name != '' ORDER BY name LIMIT 100000`
- [1× first=deepseek-v4-flash] `SELECT "name", "fclass", "maxspeed" FROM cq_osm_roads_2021 WHERE "maxspeed" > 100 ORDER BY "maxspeed" DESC LIMIT 100000`
- [1× first=deepseek-v4-flash] `SELECT name FROM cq_osm_roads_2021 WHERE fclass = 'primary' AND maxspeed > 100 AND name IS NOT NULL LIMIT 100000`
- [1× first=deepseek-v4-pro] `SELECT "maxspeed", COUNT(*) AS cnt FROM cq_osm_roads_2021 WHERE "fclass" = 'primary' GROUP BY "maxspeed" ORDER BY "maxspeed" DESC LIMIT 20`
- [1× first=deepseek-v4-pro] `SELECT "name" FROM public.cq_osm_roads_2021 WHERE "fclass" = 'primary' AND "maxspeed" > 100 LIMIT 100000`
- [1× first=deepseek-v4-pro] `SELECT name FROM cq_osm_roads_2021 WHERE fclass = 'primary' AND maxspeed > 100 LIMIT 100000`
- [1× first=gemini-2.5-flash] `SELECT DISTINCT name FROM public.cq_osm_roads_2021 WHERE maxspeed > 100 AND (fclass = 'primary' OR fclass = 'motorway' OR fclass = 'trunk') AND name IS NOT NULL LIMIT 100000`
- [1× first=gemini-2.5-flash] `SELECT name FROM public.cq_osm_roads_2021 WHERE maxspeed > 100 LIMIT 100000`
- [1× first=gemini-2.5-flash] `SELECT DISTINCT name FROM public.cq_osm_roads_2021 WHERE maxspeed > 100 AND fclass IN ('primary', 'motorway', 'trunk') AND name IS NOT NULL LIMIT 100000`

**Heuristic verdict**: **LIKELY GOLD STRICTNESS (filter ambiguity)** — 22/24 row_count fails (gold=3 rows) but pred row counts vary; gold filter likely too narrow (e.g. enum synonyms, NULL handling)

---

## `CQ_GEO_EASY_10` — Attribute Filtering / Easy

**Question**: 帮我从高德POI数据里，找找地址在渝北区的兴趣点，列出它们的名字和类型，先看50个就行。

**Gold SQL** (cols=2):
```sql
SELECT "名称", "类型" FROM cq_amap_poi_2024 WHERE "地址" LIKE '%渝北区%' LIMIT 50;
```

**Failure reason buckets** (total 24):
- `rowset`: 24

**Raw failure reason distribution** (total 24 samples):
- `rowset mismatch`: 24

**gen_status distribution**:
- `ok`: 24

**Col-count (gold, pred) distribution**:
- gold=2 / pred=2: 24

**Distinct pred_sql** (top 2):
- [23× first=deepseek-v4-flash] `SELECT "名称", "类型" FROM public.cq_amap_poi_2024 WHERE "地址" LIKE '%渝北区%' LIMIT 50`
- [1× first=gemini-3.1-pro-preview] `SELECT "名称", "类型" FROM cq_amap_poi_2024 WHERE "地址" LIKE '%渝北区%' LIMIT 50`

**Heuristic verdict**: **LIKELY EVALUATOR BUG** — 24/24 rowset_mismatch + 24/24 byte-identical-to-gold (modulo schema/LIMIT) → evaluator likely row-order or float-precision sensitive

---

## `CQ_GEO_EASY_20` — Spatial Measurement / Easy

**Question**: 帮我计算每个历史文化街区的面积，然后把街区名称和面积列出来，从大到小排个序。

**Gold SQL** (cols=2):
```sql
SELECT jqmc, ST_Area(shape) AS area FROM cq_historic_districts ORDER BY area DESC;
```

**Failure reason buckets** (total 24):
- `rowset`: 21
- `row_count`: 3

**Raw failure reason distribution** (total 24 samples):
- `rowset mismatch`: 21
- `row count: gold=20 pred=7`: 3

**gen_status distribution**:
- `ok`: 24

**Col-count (gold, pred) distribution**:
- gold=2 / pred=2: 24

**Row-count (gold, pred) distribution** (only when reason=row_count):
- gold_rows=20 / pred_rows=7: 3

**Distinct pred_sql** (top 10):
- [3× first=qwen3.6-flash] `SELECT "jqmc" AS 街区名称, ST_Area("shape"::geography) AS 面积 FROM public.cq_historic_districts ORDER BY 面积 DESC LIMIT 100000`
- [2× first=deepseek-v4-pro] `SELECT "jqmc", ST_Area("shape"::geography) AS area FROM cq_historic_districts ORDER BY area DESC LIMIT 100000`
- [2× first=gemini-2.5-flash] `SELECT "jqmc", ST_Area(shape::geography) AS area_sq_m FROM public.cq_historic_districts ORDER BY area_sq_m DESC LIMIT 100000`
- [1× first=deepseek-v4-flash] `SELECT "jqmc" AS 街区名称, "tymj" AS 面积 FROM public.cq_historic_districts WHERE "tymj" IS NOT NULL ORDER BY "tymj" DESC LIMIT 100000`
- [1× first=deepseek-v4-flash] `SELECT "jqmc" AS 街区名称, ROUND(SUM(ST_Area(ST_Transform("shape", 4326)::geography))::numeric, 2) AS 面积_平方米 FROM public.cq_historic_districts GROUP BY "jqmc" ORDER BY SUM(ST_Area(ST_Transform("shape", 4326)::geography)) DES ...`
- [1× first=deepseek-v4-flash] `SELECT "jqmc" AS 街区名称, ROUND(ST_Area("shape"::geography)::numeric, 2) AS 面积_平方米 FROM public.cq_historic_districts ORDER BY ST_Area("shape"::geography) DESC LIMIT 100000`
- [1× first=deepseek-v4-pro] `SELECT "jqmc", ST_Area(ST_Transform("shape", 4326)::geography) AS area FROM public.cq_historic_districts ORDER BY area DESC LIMIT 100000`
- [1× first=deepseek-v4-pro] `SELECT jqmc, ST_Area(shape::geography) AS 面积 FROM cq_historic_districts ORDER BY 面积 DESC LIMIT 100000`
- [1× first=gemini-2.5-flash] `SELECT "jqmc", ST_Area("shape"::geography) AS area_sq_m FROM public.cq_historic_districts ORDER BY area_sq_m DESC LIMIT 100000`
- [1× first=gemini-2.5-pro] `SELECT jqmc AS "街区名称", ST_Area(shape::geography) AS "面积（平方米）" FROM public.cq_historic_districts ORDER BY "面积（平方米）" DESC LIMIT 100000`

**Heuristic verdict**: **LIKELY EVALUATOR / GOLD STRICTNESS** — 21/24 rowset_mismatch but pred SQLs vary; review if gold filter is too narrow

---

## `CQ_GEO_EASY_24` — Preview/Listing / Easy

**Question**: 查看 2023 年百度搜索指数数据的前 10 条记录，展示出发城市、目的地城市、PC 搜索次数和移动端搜索次数。

**Gold SQL** (cols=4):
```sql
SELECT odjsmc, ddjsmc, pcsscs, ydsscs FROM cq_baidu_search_index_2023 ORDER BY pcsscs DESC LIMIT 10;
```

**Failure reason buckets** (total 24):
- `rowset`: 23
- `row_count`: 1

**Raw failure reason distribution** (total 24 samples):
- `rowset mismatch`: 23
- `row count: gold=10 pred=1`: 1

**gen_status distribution**:
- `ok`: 24

**Col-count (gold, pred) distribution**:
- gold=4 / pred=4: 23
- gold=4 / pred=1: 1

**Row-count (gold, pred) distribution** (only when reason=row_count):
- gold_rows=10 / pred_rows=1: 1

**Distinct pred_sql** (top 10):
- [8× first=deepseek-v4-pro] `SELECT "odjsmc" AS "出发城市", "ddjsmc" AS "目的地城市", "pcsscs" AS "PC搜索次数", "ydsscs" AS "移动端搜索次数" FROM public.cq_baidu_search_index_2023 LIMIT 10`
- [3× first=deepseek-v4-pro] `SELECT "odjsmc" AS 出发城市, "ddjsmc" AS 目的地城市, "pcsscs" AS PC搜索次数, "ydsscs" AS 移动端搜索次数 FROM public.cq_baidu_search_index_2023 LIMIT 10`
- [3× first=gemini-2.5-flash] `SELECT odjsmc, ddjsmc, pcsscs, ydsscs FROM public.cq_baidu_search_index_2023 LIMIT 10`
- [3× first=gemini-3.1-flash-lite-preview] `SELECT odjsmc AS "出发城市", ddjsmc AS "目的地城市", pcsscs AS "PC搜索次数", ydsscs AS "移动端搜索次数" FROM cq_baidu_search_index_2023 LIMIT 10`
- [2× first=deepseek-v4-flash] `SELECT "odjsmc" AS "出发城市", "ddjsmc" AS "目的地城市", "pcsscs" AS "PC搜索次数", "ydsscs" AS "移动端搜索次数" FROM public.cq_baidu_search_index_2023 ORDER BY "objectid" LIMIT 10`
- [1× first=deepseek-v4-flash] `SELECT COUNT(*) FROM (SELECT "odjsmc" AS "出发城市", "ddjsmc" AS "目的地城市", "pcsscs" AS "PC搜索次数", "ydsscs" AS "移动端搜索次数" FROM public.cq_baidu_search_index_2023 LIMIT 10) AS sub`
- [1× first=deepseek-v4-pro] `SELECT "odjsmc", "ddjsmc", "pcsscs", "ydsscs" FROM cq_baidu_search_index_2023 LIMIT 10`
- [1× first=gemini-2.5-flash] `SELECT "odjsmc", "ddjsmc", "pcsscs", "ydsscs" FROM public.cq_baidu_search_index_2023 LIMIT 10`
- [1× first=gemini-2.5-pro] `SELECT "odjsmc" AS "出发城市", "ddjsmc" AS "目的地城市", "pcsscs" AS "PC搜索次数", "ydsscs" AS "移动端搜索次数" FROM cq_baidu_search_index_2023 LIMIT 10`
- [1× first=gemini-3.1-flash-lite-preview] `SELECT odjsmc AS "出发城市", ddjsmc AS "目的地城市", pcsscs AS "PC 搜索次数", ydsscs AS "移动端搜索次数" FROM public.cq_baidu_search_index_2023 LIMIT 10`

**Heuristic verdict**: **LIKELY EVALUATOR / GOLD STRICTNESS** — 23/24 rowset_mismatch but pred SQLs vary; review if gold filter is too narrow

---

## `CQ_GEO_MEDIUM_05` — Centroid Calculation / Medium

**Question**: 找出所有'有林地'地块的中心点坐标，并告诉我每个地块的编号。

**Gold SQL** (cols=2):
```sql
SELECT "BSM", ST_AsText(ST_Centroid(geometry)) AS center_wkt FROM cq_land_use_dltb WHERE "DLMC" = '有林地';
```

**Failure reason buckets** (total 24):
- `col_count`: 14
- `rowset`: 8
- `row_count`: 2

**Raw failure reason distribution** (total 24 samples):
- `col count: gold=2 pred=3`: 14
- `rowset mismatch`: 8
- `row count: gold=13004 pred=1000`: 2

**gen_status distribution**:
- `ok`: 24

**Col-count (gold, pred) distribution**:
- gold=2 / pred=3: 14
- gold=2 / pred=2: 10

**Row-count (gold, pred) distribution** (only when reason=row_count):
- gold_rows=13004 / pred_rows=1000: 2

**Distinct pred_sql** (top 10):
- [3× first=gemini-2.5-pro] `SELECT bsm, ST_AsText(ST_Centroid(shape)) FROM public.cq_dltb WHERE dlmc = '有林地' LIMIT 100000`
- [2× first=deepseek-v4-pro] `SELECT bsm AS 地块编号, ST_X(ST_Centroid(shape)) AS 中心点经度, ST_Y(ST_Centroid(shape)) AS 中心点纬度 FROM cq_dltb WHERE dlmc = '有林地' LIMIT 100000`
- [2× first=gemini-2.5-flash] `SELECT "BSM", ST_X(ST_Centroid(geometry)) AS longitude, ST_Y(ST_Centroid(geometry)) AS latitude FROM public.cq_land_use_dltb WHERE "DLMC" = '有林地' LIMIT 100000`
- [2× first=gemini-3.1-pro-preview] `SELECT bsm, ST_X(ST_Centroid(shape)) AS longitude, ST_Y(ST_Centroid(shape)) AS latitude FROM cq_dltb WHERE dlmc = '有林地' LIMIT 100000`
- [2× first=qwen3.6-plus] `SELECT "bsm", ST_Centroid("shape") AS center_point FROM public.cq_dltb WHERE "dlmc" = '有林地' LIMIT 100000`
- [1× first=deepseek-v4-flash] `SELECT "bsm" AS 地块编号, ST_X(ST_Centroid("shape")) AS 中心点经度, ST_Y(ST_Centroid("shape")) AS 中心点纬度 FROM public.cq_dltb WHERE "dlmc" = '有林地' LIMIT 100000`
- [1× first=deepseek-v4-flash] `SELECT bsm AS "地块编号", ST_X(ST_Centroid(shape)) AS "中心点经度", ST_Y(ST_Centroid(shape)) AS "中心点纬度" FROM public.cq_dltb WHERE dlmc = '有林地' LIMIT 100000`
- [1× first=deepseek-v4-flash] `SELECT "bsm" AS 地块编号, ST_X(ST_Centroid(ST_Transform("shape", 4326))) AS 经度, ST_Y(ST_Centroid(ST_Transform("shape", 4326))) AS 纬度 FROM public.cq_dltb WHERE "dlmc" = '有林地' LIMIT 100000`
- [1× first=deepseek-v4-pro] `SELECT bsm AS 编号, ST_X(ST_Transform(ST_Centroid(shape), 4326)) AS 经度, ST_Y(ST_Transform(ST_Centroid(shape), 4326)) AS 纬度 FROM cq_dltb WHERE dlmc = '有林地' LIMIT 100000`
- [1× first=gemini-2.5-flash] `SELECT "BSM", ST_X(ST_Centroid("geometry")) AS longitude, ST_Y(ST_Centroid("geometry")) AS latitude FROM public.cq_land_use_dltb WHERE "DLMC" = '有林地' LIMIT 100000`

**Heuristic verdict**: **LIKELY GOLD UNDER-SPEC** — gold cols=2 but 14/24 samples agree on cols=3; gold likely needs to expand output schema

---

## `CQ_GEO_MEDIUM_08` — Attribute Filtering / Medium

**Question**: 帮我找一下名字里带'大学'，但不带'附属'的地方，列出 20 个名字就行。

**Gold SQL** (cols=1):
```sql
SELECT "名称" FROM cq_amap_poi_2024 WHERE "名称" LIKE '%大学%' AND "名称" NOT LIKE '%附属%' LIMIT 20;
```

**Failure reason buckets** (total 24):
- `rowset`: 24

**Raw failure reason distribution** (total 24 samples):
- `rowset mismatch`: 24

**gen_status distribution**:
- `ok`: 24

**Col-count (gold, pred) distribution**:
- gold=1 / pred=1: 24

**Distinct pred_sql** (top 6):
- [13× first=deepseek-v4-flash] `SELECT "名称" FROM public.cq_amap_poi_2024 WHERE "名称" LIKE '%大学%' AND "名称" NOT LIKE '%附属%' LIMIT 20`
- [4× first=gemini-2.5-pro] `SELECT "名称" FROM public.cq_baidu_aoi_2024 WHERE "名称" LIKE '%大学%' AND "名称" NOT LIKE '%附属%' LIMIT 20`
- [2× first=deepseek-v4-flash] `SELECT "名称" FROM public.cq_amap_poi_2024 WHERE "名称" LIKE '%大学%' AND "名称" NOT LIKE '%附属%' ORDER BY "名称" LIMIT 20`
- [2× first=deepseek-v4-pro] `SELECT "名称" FROM cq_amap_poi_2024 WHERE "名称" LIKE '%大学%' AND "名称" NOT LIKE '%附属%' LIMIT 20`
- [2× first=gemini-2.5-pro] `SELECT DISTINCT "名称" FROM public.cq_amap_poi_2024 WHERE "名称" LIKE '%大学%' AND "名称" NOT LIKE '%附属%' LIMIT 20`
- [1× first=gemini-3.1-pro-preview] `SELECT DISTINCT "名称" FROM public.cq_amap_poi_2024 WHERE "名称" LIKE '%大学%' AND "名称" NOT LIKE '%附属%' AND "名称" IS NOT NULL LIMIT 20`

**Heuristic verdict**: **LIKELY EVALUATOR BUG** — 24/24 rowset_mismatch + 15/24 byte-identical-to-gold (modulo schema/LIMIT) → evaluator likely row-order or float-precision sensitive

---

## `CQ_GEO_MEDIUM_10` — Attribute Filtering / Medium

**Question**: 帮我找一下百度地图上的美食，要求评分不低于4.5，人均消费在100到500块钱之间。给我看前20个就行。

**Gold SQL** (cols=1):
```sql
SELECT "名称" FROM cq_baidu_aoi_2024 WHERE "评分" >= 4.5 AND "人均价格_元" BETWEEN 100 AND 500 AND "第一分类" LIKE '%美食%' LIMIT 20;
```

**Failure reason buckets** (total 24):
- `col_count`: 22
- `row_count`: 2

**Raw failure reason distribution** (total 24 samples):
- `col count: gold=1 pred=4`: 13
- `col count: gold=1 pred=3`: 5
- `col count: gold=1 pred=5`: 4
- `row count: gold=2 pred=128`: 1
- `row count: gold=2 pred=3`: 1

**gen_status distribution**:
- `ok`: 24

**Col-count (gold, pred) distribution**:
- gold=1 / pred=4: 13
- gold=1 / pred=3: 5
- gold=1 / pred=5: 4
- gold=1 / pred=1: 2

**Row-count (gold, pred) distribution** (only when reason=row_count):
- gold_rows=2 / pred_rows=128: 1
- gold_rows=2 / pred_rows=3: 1

**Distinct pred_sql** (top 10):
- [7× first=gemini-2.5-pro] `SELECT "名称", "地址", "评分", "人均价格_元" FROM public.cq_baidu_aoi_2024 WHERE "第一分类" = '美食' AND "评分" >= 4.5 AND "人均价格_元" BETWEEN 100 AND 500 LIMIT 20`
- [5× first=gemini-2.5-flash] `SELECT "名称", "评分", "人均价格_元" FROM public.cq_baidu_aoi_2024 WHERE "第一分类" = '美食' AND "评分" >= 4.5 AND "人均价格_元" BETWEEN 100 AND 500 LIMIT 20`
- [2× first=deepseek-v4-flash] `SELECT "名称", "地址", "评分", "人均价格_元", "电话" FROM public.cq_baidu_aoi_2024 WHERE "第一分类" = '美食' AND "评分" >= 4.5 AND "人均价格_元" >= 100 AND "人均价格_元" <= 500 ORDER BY "评分" DESC LIMIT 20`
- [1× first=deepseek-v4-flash] `SELECT "名称", "地址", "评分", "人均价格_元", "电话" FROM public.cq_baidu_aoi_2024 WHERE "第一分类" = '美食' AND "评分" >= 4.5 AND "人均价格_元" >= 100 AND "人均价格_元" <= 500 LIMIT 20`
- [1× first=deepseek-v4-pro] `SELECT "名称", "评分", "人均价格_元", "地址" FROM cq_baidu_aoi_2024 WHERE "第一分类" = '美食' AND "评分" >= 4.5 AND "人均价格_元" >= 100 AND "人均价格_元" <= 500 ORDER BY "评分" DESC LIMIT 20`
- [1× first=deepseek-v4-pro] `SELECT "名称", "地址", "评分", "人均价格_元" FROM public.cq_baidu_aoi_2024 WHERE "第一分类" = '美食' AND "评分" >= 4.5 AND "人均价格_元" BETWEEN 100 AND 500 ORDER BY "评分" DESC LIMIT 20`
- [1× first=deepseek-v4-pro] `SELECT "名称", "地址", "评分", "人均价格_元" FROM public.cq_baidu_aoi_2024 WHERE "第一分类" = '美食' AND "评分" >= 4.5 AND "人均价格_元" >= 100 AND "人均价格_元" <= 500 ORDER BY "评分" DESC LIMIT 20`
- [1× first=gemini-2.5-flash] `SELECT "名称", "地址", "评分", "人均价格_元" FROM public.cq_baidu_aoi_2024 WHERE "第一分类" = '美食' AND "评分" >= 4.5 AND "人均价格_元" >= 100 AND "人均价格_元" <= 500 LIMIT 20`
- [1× first=gemini-2.5-flash] `SELECT "名称", "评分", "人均价格_元", "地址", "电话" FROM public.cq_baidu_aoi_2024 WHERE "第一分类" = '美食' AND "评分" >= 4.5 AND "人均价格_元" >= 100 AND "人均价格_元" <= 500 LIMIT 20`
- [1× first=gemini-2.5-pro] `SELECT "名称", "评分", "人均价格_元", "地址" FROM public.cq_baidu_aoi_2024 WHERE "第一分类" = '美食' AND "评分" >= 4.5 AND "人均价格_元" BETWEEN 100 AND 500 LIMIT 20`

**Heuristic verdict**: **LIKELY GOLD UNDER-SPEC** — gold cols=1 but 13/24 samples agree on cols=4; gold likely needs to expand output schema

---

## `CQ_GEO_MEDIUM_20` — Spatial Measurement / Medium

**Question**: 找出所有 'secondary' 类型的道路，按米为单位计算长度，列出最长的前 10 条道路的名称和长度。

**Gold SQL** (cols=2):
```sql
SELECT name, ROUND(ST_Length(geometry::geography)::numeric, 1) AS length_m FROM cq_osm_roads_2021 WHERE fclass = 'secondary' ORDER BY length_m DESC LIMIT 10;
```

**Failure reason buckets** (total 24):
- `rowset`: 24

**Raw failure reason distribution** (total 24 samples):
- `rowset mismatch`: 24

**gen_status distribution**:
- `ok`: 24

**Col-count (gold, pred) distribution**:
- gold=2 / pred=2: 24

**Distinct pred_sql** (top 10):
- [3× first=deepseek-v4-pro] `SELECT "name", ST_Length("geometry"::geography) AS length_m FROM public.cq_osm_roads_2021 WHERE "fclass" = 'secondary' ORDER BY length_m DESC LIMIT 10`
- [3× first=qwen3.6-plus] `SELECT "name", ST_Length(geometry::geography) AS length_m FROM public.cq_osm_roads_2021 WHERE "fclass" = 'secondary' ORDER BY length_m DESC LIMIT 10`
- [2× first=deepseek-v4-flash] `SELECT name, ST_Length(geometry::geography) AS length FROM cq_osm_roads_2021 WHERE fclass = 'secondary' ORDER BY ST_Length(geometry::geography) DESC LIMIT 10`
- [2× first=gemini-2.5-flash] `SELECT name, ST_Length(shape::geography) AS length_meters FROM public.cq_osm_roads WHERE fclass = 'secondary' ORDER BY length_meters DESC LIMIT 10`
- [2× first=gemini-2.5-flash] `SELECT name, ST_Length(geometry::geography) AS length_meters FROM public.cq_osm_roads_2021 WHERE fclass = 'secondary' ORDER BY length_meters DESC LIMIT 10`
- [2× first=gemini-2.5-pro] `SELECT name, ST_Length(geometry::geography) AS length_in_meters FROM public.cq_osm_roads_2021 WHERE fclass = 'secondary' ORDER BY length_in_meters DESC LIMIT 10`
- [2× first=gemini-3.1-flash-lite-preview] `SELECT name, ST_Length(geometry::geography) AS length_meters FROM public.cq_osm_roads_2021 WHERE fclass = 'secondary' AND name IS NOT NULL ORDER BY length_meters DESC LIMIT 10`
- [1× first=deepseek-v4-flash] `SELECT name, ST_Length(geometry::geography) AS 长度_米 FROM cq_osm_roads_2021 WHERE fclass = 'secondary' AND name IS NOT NULL ORDER BY ST_Length(geometry::geography) DESC LIMIT 10`
- [1× first=deepseek-v4-flash] `SELECT name, ST_Length(geometry::geography) AS length_m FROM cq_osm_roads_2021 WHERE fclass = 'secondary' ORDER BY ST_Length(geometry::geography) DESC LIMIT 10`
- [1× first=deepseek-v4-pro] `SELECT "name", ST_Length("geometry"::geography) AS length_m FROM cq_osm_roads_2021 WHERE "fclass" = 'secondary' ORDER BY length_m DESC LIMIT 10`

**Heuristic verdict**: **LIKELY EVALUATOR / GOLD STRICTNESS** — 24/24 rowset_mismatch but pred SQLs vary; review if gold filter is too narrow

---

## `CQ_GEO_MEDIUM_26` — KNN / Medium

**Question**: 随便找一个'茶园'地块，离它最近的 5 个高德兴趣点是哪些？告诉我它们的名字和距离（米）。

**Gold SQL** (cols=2):
```sql
SELECT p."名称", ST_Distance(ST_Transform(p.geometry, 4610)::geography, t.shape::geography) AS dist_m FROM cq_amap_poi_2024 p CROSS JOIN (SELECT shape FROM cq_dltb WHERE dlmc = '茶园' ORDER BY objectid LIMIT 1) t ORDER BY ST_Transform(p.geometry, 4610) <-> t.shape LIMIT 5;
```

**Failure reason buckets** (total 24):
- `rowset`: 22
- `col_count`: 1
- `empty`: 1

**Raw failure reason distribution** (total 24 samples):
- `rowset mismatch`: 22
- `col count: gold=2 pred=3`: 1
- `empty`: 1

**gen_status distribution**:
- `ok`: 23
- `no_sql`: 1

**Col-count (gold, pred) distribution**:
- gold=2 / pred=None: 12
- gold=2 / pred=2: 12

**Distinct pred_sql** (top 10):
- [1× first=deepseek-v4-flash] `WITH random_tea_garden AS ( SELECT "geometry" AS geom FROM cq_land_use_dltb WHERE "DLMC" LIKE '%茶园%' ORDER BY RANDOM() LIMIT 1 ) SELECT p."名称" AS name, ST_Distance(rg.geom::geography, p.geometry::geography) AS distance_m ...`
- [1× first=deepseek-v4-flash] `WITH tea_garden AS ( SELECT "geometry" AS geom FROM public.cq_land_use_dltb WHERE "DLMC" = '茶园' ORDER BY random() LIMIT 1 ) SELECT poi."名称" AS poi_name, ROUND(ST_Distance(tea.geom::geography, poi."geometry"::geography):: ...`
- [1× first=deepseek-v4-flash] `WITH chayuan AS ( SELECT geometry FROM cq_land_use_dltb WHERE "DLMC" LIKE '%茶园%' LIMIT 1 ) SELECT poi."名称" AS name, ROUND(ST_Distance(ST_Centroid(chayuan.geometry)::geography, poi.geometry::geography)::numeric, 2) AS dis ...`
- [1× first=deepseek-v4-pro] `SELECT p."名称", ROUND(ST_Distance(p.geometry::geography, (SELECT geometry::geography FROM cq_land_use_dltb WHERE "DLBM" LIKE '0202%' LIMIT 1))::numeric, 2) AS distance_m FROM cq_amap_poi_2024 p ORDER BY p.geometry <-> (SE ...`
- [1× first=deepseek-v4-pro] `WITH tea_plot AS ( SELECT geometry FROM cq_land_use_dltb WHERE "DLBM" LIKE '0202%' LIMIT 1 ) SELECT p."名称", ST_Distance(p.geometry::geography, (SELECT geometry FROM tea_plot)::geography) AS 距离_米 FROM cq_amap_poi_2024 p O ...`
- [1× first=deepseek-v4-pro] `WITH tea_garden AS ( SELECT "DLMC", geometry FROM cq_land_use_dltb WHERE "DLMC" LIKE '%茶园%' LIMIT 1 ) SELECT tg."DLMC" AS garden_name, p."名称" AS poi_name, ROUND(ST_Distance(p.geometry::geography, tg.geometry::geography): ...`
- [1× first=gemini-2.5-flash] `SELECT p."名称", ST_Distance(p.geometry::geography, c.geometry::geography) AS distance_meters FROM public.cq_amap_poi_2024 AS p CROSS JOIN ( SELECT geometry FROM public.cq_land_use_dltb WHERE "DLMC" = '茶园' LIMIT 1 ) AS c O ...`
- [1× first=gemini-2.5-flash] `SELECT poi."名称", ST_Distance(poi.geometry::geography, tea_garden.geometry::geography) AS distance_meters FROM public.cq_amap_poi_2024 AS poi CROSS JOIN ( SELECT geometry FROM public.cq_land_use_dltb WHERE "DLMC" = '茶园' L ...`
- [1× first=gemini-2.5-flash] `SELECT a."名称", ST_Distance(a.geometry::geography, p.geometry::geography) AS "距离" FROM public.cq_amap_poi_2024 AS a CROSS JOIN LATERAL ( SELECT geometry FROM public.cq_land_use_dltb WHERE "DLMC" = '茶园' LIMIT 1 ) AS p ORDE ...`
- [1× first=gemini-2.5-pro] `SELECT t1."名称", ST_Distance(t1.geometry::geography, p.geometry::geography) as "距离（米）" FROM public.cq_amap_poi_2024 AS t1 CROSS JOIN (SELECT geometry FROM public.cq_land_use_dltb WHERE "DLMC" = '茶园' LIMIT 1) AS p ORDER BY ...`

**Heuristic verdict**: **LIKELY EVALUATOR / GOLD STRICTNESS** — 22/24 rowset_mismatch but pred SQLs vary; review if gold filter is too narrow

---

## `CQ_GEO_HARD_10` — Spatial Join / Hard

**Question**: 哪些类型为 'primary' 的主干道沿线的兴趣点最多？请列出排名前 5 的道路名称和对应的兴趣点数量。

**Gold SQL** (cols=2):
```sql
SELECT r.name, COUNT(DISTINCT p."ID") AS poi_cnt FROM cq_osm_roads_2021 r JOIN cq_amap_poi_2024 p ON ST_Intersects(r.geometry, p.geometry) WHERE r.fclass = 'primary' GROUP BY r.name ORDER BY poi_cnt DESC LIMIT 5;
```

**Failure reason buckets** (total 24):
- `empty`: 14
- `row_count`: 9
- `timeout`: 1

**Raw failure reason distribution** (total 24 samples):
- `empty`: 14
- `row count: gold=0 pred=5`: 9
- `(psycopg2.errors.QueryCanceled) canceling statement due to statement timeout

[SQL: SELECT r.name, COUNT(p."ID") AS poi_ ...`: 1

**gen_status distribution**:
- `timeout`: 14
- `ok`: 10

**Col-count (gold, pred) distribution**:
- gold=2 / pred=None: 16
- gold=2 / pred=2: 8

**Row-count (gold, pred) distribution** (only when reason=row_count):
- gold_rows=0 / pred_rows=5: 9

**Distinct pred_sql** (top 10):
- [14× first=deepseek-v4-flash] `<EMPTY>`
- [1× first=deepseek-v4-flash] `SELECT r.name, COUNT(*)::integer AS cnt FROM cq_osm_roads_2021 r JOIN cq_amap_poi_2024 p ON ST_DWithin(r.geometry, p.geometry, 0.0005) WHERE r.fclass = 'primary' AND r.name IS NOT NULL GROUP BY r.name ORDER BY cnt DESC L ...`
- [1× first=deepseek-v4-pro] `SELECT r.name, COUNT(p."ID") AS poi_count FROM cq_osm_roads_2021 r JOIN cq_amap_poi_2024 p ON ST_DWithin(r.geometry, p.geometry, 0.0005) WHERE r.fclass = 'primary' AND r.name IS NOT NULL GROUP BY r.name ORDER BY poi_coun ...`
- [1× first=deepseek-v4-pro] `SELECT r.name AS road_name, COUNT(p."ID") AS poi_count FROM cq_osm_roads_2021 r JOIN cq_amap_poi_2024 p ON ST_DWithin(r.geometry, p.geometry, 0.0005) WHERE r.fclass = 'primary' GROUP BY r.name ORDER BY poi_count DESC LIM ...`
- [1× first=deepseek-v4-pro] `WITH primary_roads AS ( SELECT name, geometry FROM cq_osm_roads_2021 WHERE fclass = 'primary' AND name IS NOT NULL ) SELECT r.name, COUNT(p."ID") AS poi_count FROM primary_roads r JOIN cq_amap_poi_2024 p ON ST_DWithin(p. ...`
- [1× first=gemini-2.5-flash] `SELECT r.name, COUNT(p."ID") AS poi_count FROM public.cq_osm_roads_2021 AS r JOIN public.cq_amap_poi_2024 AS p ON ST_DWithin(r.geometry::geography, p.geometry::geography, 10) WHERE r.fclass = 'primary' AND r.name IS NOT  ...`
- [1× first=gemini-2.5-pro] `SELECT r.name AS road_name, COUNT(p."ID") AS poi_count FROM public.cq_osm_roads_2021 AS r JOIN public.cq_amap_poi_2024 AS p ON ST_DWithin(r.geometry, p.geometry, 0.0003) WHERE r.fclass = 'primary' AND r.name IS NOT NULL  ...`
- [1× first=gemini-3.1-pro-preview] `SELECT r.name, COUNT(DISTINCT p."ID") AS poi_count FROM cq_osm_roads_2021 r JOIN cq_amap_poi_2024 p ON ST_DWithin(r.geometry, p.geometry, 0.001) WHERE r.fclass = 'primary' AND r.name IS NOT NULL GROUP BY r.name ORDER BY  ...`
- [1× first=gemini-3.1-pro-preview] `SELECT r.name AS 道路名称, COUNT(DISTINCT p."ID") AS 兴趣点数量 FROM cq_osm_roads_2021 r JOIN cq_amap_poi_2024 p ON ST_DWithin(r.geometry, p.geometry, 0.002) AND ST_DWithin(r.geometry::geography, p.geometry::geography, 100) WHERE ...`
- [1× first=qwen3.6-flash] `WITH primary_roads AS ( SELECT "name", "geometry" FROM public.cq_osm_roads_2021 WHERE "fclass" = 'primary' ) SELECT pr."name" AS road_name, COUNT(*) AS poi_count FROM primary_roads pr JOIN public.cq_amap_poi_2024 p ON ST ...`

**Heuristic verdict**: **LIKELY GOLD-EMPTY BUG** — gold returns 0 rows but 9/9 evaluable pred return >0 rows; gold SQL filter likely broken

---

## `CQ_GEO_HARD_12` — Spatial Join / Hard

**Question**: 统计每种地类里有多少栋楼、平均楼层是多少？只看那些楼超过10栋的地类，再按楼的数量从多到少排序。

**Gold SQL** (cols=3):
```sql
SELECT l."DLMC", COUNT(DISTINCT b."Id") AS bld_cnt, ROUND(AVG(b."Floor")::numeric, 1) AS avg_floor FROM cq_land_use_dltb l JOIN cq_buildings_2021 b ON ST_Contains(l.geometry, b.geometry) GROUP BY l."DLMC" HAVING COUNT(DISTINCT b."Id") > 10 ORDER BY bld_cnt DESC;
```

**Failure reason buckets** (total 24):
- `row_count`: 23
- `empty`: 1

**Raw failure reason distribution** (total 24 samples):
- `row count: gold=0 pred=11`: 18
- `row count: gold=0 pred=5`: 4
- `empty`: 1
- `row count: gold=0 pred=7`: 1

**gen_status distribution**:
- `ok`: 23
- `no_sql`: 1

**Col-count (gold, pred) distribution**:
- gold=3 / pred=3: 22
- gold=3 / pred=None: 2

**Row-count (gold, pred) distribution** (only when reason=row_count):
- gold_rows=0 / pred_rows=11: 18
- gold_rows=0 / pred_rows=5: 4
- gold_rows=0 / pred_rows=7: 1

**Distinct pred_sql** (top 10):
- [1× first=deepseek-v4-flash] `SELECT d."dlmc" AS 地类名称, COUNT(b.*) AS 楼栋数量, AVG(b."Floor") AS 平均楼层 FROM public.cq_dltb d JOIN public.cq_buildings_2021 b ON ST_Intersects(ST_Transform(d.shape, 4326), b.geometry) GROUP BY d."dlmc" HAVING COUNT(b.*) > 10 ...`
- [1× first=deepseek-v4-flash] `SELECT d."dlmc", COUNT(*) AS 楼栋数量, AVG(b."Floor") AS 平均楼层 FROM cq_buildings_2021 b JOIN cq_dltb d ON ST_Intersects(ST_Transform(b.geometry, 4610), d.shape) GROUP BY d."dlmc" HAVING COUNT(*) > 10 ORDER BY 楼栋数量 DESC LIMIT  ...`
- [1× first=deepseek-v4-flash] `SELECT d.dlmc AS 地类, COUNT(*) AS 楼栋数, AVG(b."Floor") AS 平均楼层 FROM public.cq_dltb d JOIN public.cq_buildings_2021 b ON ST_Intersects(d.shape, ST_Transform(b."geometry", 4610)) GROUP BY d.dlmc HAVING COUNT(*) > 10 ORDER BY ...`
- [1× first=deepseek-v4-pro] `SELECT d.dlmc AS 地类名称, COUNT(*) AS 楼栋数量, AVG(b."Floor") AS 平均楼层 FROM cq_dltb d JOIN cq_buildings_2021 b ON ST_Intersects(ST_Transform(d.shape, 4326), b.geometry) GROUP BY d.dlmc HAVING COUNT(*) > 10 ORDER BY COUNT(*) DES ...`
- [1× first=deepseek-v4-pro] `SELECT d.dlmc AS 地类名称, COUNT(*) AS 楼栋数量, AVG(b."Floor") AS 平均楼层 FROM cq_dltb d JOIN cq_buildings_2021 b ON ST_Intersects(d.shape, ST_Transform(b.geometry, 4610)) GROUP BY d.dlmc HAVING COUNT(*) > 10 ORDER BY COUNT(*) DES ...`
- [1× first=deepseek-v4-pro] `SELECT d.dlmc AS 地类名称, COUNT(*) AS 楼栋数量, AVG(b."Floor") AS 平均楼层 FROM cq_buildings_2021 b JOIN cq_dltb d ON ST_Within(b.geometry, ST_Transform(d.shape, 4326)) GROUP BY d.dlmc HAVING COUNT(*) > 10 ORDER BY COUNT(*) DESC LI ...`
- [1× first=gemini-2.5-flash] `SELECT lu."DLMC", COUNT(*) AS num_buildings, ROUND(AVG(b."Floor")::numeric, 2) AS avg_floor FROM public.cq_land_use_dltb AS lu JOIN public.cq_buildings_2021 AS b ON ST_Intersects(lu.geometry, b.geometry) GROUP BY lu."DLM ...`
- [1× first=gemini-2.5-flash] `<EMPTY>`
- [1× first=gemini-2.5-flash] `SELECT lu."DLMC" AS land_use_type, COUNT(b."Id") AS building_count, ROUND(AVG(b."Floor")::numeric, 2) AS average_floor FROM public.cq_land_use_dltb AS lu JOIN public.cq_buildings_2021 AS b ON ST_Intersects(lu.geometry, b ...`
- [1× first=gemini-2.5-pro] `SELECT l."DLMC" AS "地类名称", COUNT(b."Id") AS "建筑数量", AVG(b."Floor") AS "平均楼层" FROM public.cq_land_use_dltb AS l JOIN public.cq_buildings_2021 AS b ON ST_Contains(l.geometry, b.geometry) GROUP BY l."DLMC" HAVING COUNT(b."I ...`

**Heuristic verdict**: **LIKELY GOLD-EMPTY BUG** — gold returns 0 rows but 23/23 evaluable pred return >0 rows; gold SQL filter likely broken

---

## `CQ_GEO_HARD_15` — KNN / Hard

**Question**: 找出离每条有名字的主干道最近的医疗设施是哪个？列出路名、医疗设施名和距离（米），只要最近的 5 对。

**Gold SQL** (cols=3):
```sql
SELECT DISTINCT ON (r.name) r.name AS road_name, a."名称" AS aoi_name, ST_Distance(r.geometry::geography, ST_Transform(a.shape, 4326)::geography) AS dist_m FROM cq_osm_roads_2021 r CROSS JOIN cq_baidu_aoi_2024 a WHERE r.fclass = 'primary' AND r.name IS NOT NULL AND a."第一分类" = '医疗' ORDER BY r.name, r.geometry <-> ST_Transform(a.shape, 4326) LIMIT 5;
```

**Failure reason buckets** (total 24):
- `rowset`: 18
- `empty`: 4
- `sql_error`: 2

**Raw failure reason distribution** (total 24 samples):
- `rowset mismatch`: 18
- `empty`: 4
- `(psycopg2.errors.SyntaxError) syntax error at or near ":"
LINE 1: ...CT road_name, medical_name, distance_meters FROM D: ...`: 1
- `(psycopg2.errors.SyntaxError) syntax error at or near ":"
LINE 1: SELECT * FROM D:\adk\data_agent\uploads\cq_benchmark\q ...`: 1

**gen_status distribution**:
- `ok`: 20
- `timeout`: 4

**Col-count (gold, pred) distribution**:
- gold=3 / pred=3: 12
- gold=3 / pred=None: 11
- gold=3 / pred=1: 1

**Distinct pred_sql** (top 10):
- [4× first=deepseek-v4-flash] `<EMPTY>`
- [1× first=deepseek-v4-flash] `WITH named_primary_roads AS ( SELECT "name", "geometry" FROM public.cq_osm_roads_2021 WHERE "fclass" = 'primary' AND "name" IS NOT NULL ), medical_pois AS ( SELECT "名称", "geometry" FROM public.cq_amap_poi_2024 WHERE "类型" ...`
- [1× first=deepseek-v4-flash] `WITH road_medical_pairs AS ( SELECT DISTINCT ON (r.name) r.name AS road_name, p."名称" AS medical_name, ST_Distance(r.geometry::geography, p.geometry::geography) AS distance_m FROM public.cq_osm_roads_2021 r CROSS JOIN LAT ...`
- [1× first=deepseek-v4-pro] `SELECT roads.name AS road_name, poi."名称" AS facility_name, ST_Distance(roads.geometry::geography, poi.geometry::geography) AS distance_m FROM public.cq_osm_roads_2021 AS roads CROSS JOIN LATERAL ( SELECT "名称", geometry F ...`
- [1× first=deepseek-v4-pro] `SELECT r."name" AS road_name, p."名称" AS facility_name, ST_Distance(r.geometry::geography, p.geometry::geography) AS distance_m FROM public.cq_osm_roads_2021 r CROSS JOIN LATERAL ( SELECT "名称", geometry FROM public.cq_ama ...`
- [1× first=deepseek-v4-pro] `SELECT r.name AS road_name, p."名称" AS facility_name, ST_Distance(r.geometry::geography, p.geometry::geography) AS distance_m FROM cq_osm_roads_2021 r CROSS JOIN LATERAL ( SELECT "名称", geometry FROM cq_amap_poi_2024 WHERE ...`
- [1× first=gemini-2.5-flash] `SELECT r.name AS road_name, p."名称" AS medical_facility_name, ST_Distance(r.geometry::geography, p.geometry::geography) AS distance_meters FROM public.cq_osm_roads_2021 AS r CROSS JOIN LATERAL ( SELECT "名称", geometry FROM ...`
- [1× first=gemini-2.5-flash] `SELECT r.name AS road_name, p."名称" AS medical_facility_name, ST_Distance(r.geometry::geography, p.geometry::geography) AS distance_meters FROM public.cq_osm_roads_2021 AS r CROSS JOIN LATERAL ( SELECT "名称", geometry FROM ...`
- [1× first=gemini-2.5-flash] `SELECT r.name AS road_name, p."名称" AS medical_facility_name, ST_Distance(r.geometry::geography, p.geometry::geography) AS distance_meters FROM public.cq_osm_roads_2021 AS r CROSS JOIN LATERAL ( SELECT p_inner."名称", p_inn ...`
- [1× first=gemini-2.5-pro] `SELECT roads.name AS road_name, pois."名称" AS facility_name, ROUND(ST_Distance(roads.geometry::geography, pois.geometry::geography)::numeric, 2) AS distance_meters FROM public.cq_osm_roads_2021 AS roads CROSS JOIN LATERAL ...`

**Heuristic verdict**: **LIKELY EVALUATOR / GOLD STRICTNESS** — 18/24 rowset_mismatch but pred SQLs vary; review if gold filter is too narrow

---

## `CQ_GEO_HARD_22` — Cross-Table / Hard

**Question**: 对于常住人口超过100万的区县，分别统计一下它们有多少家医院？按医院数量从多到少排序。

**Gold SQL** (cols=2):
```sql
SELECT d."区划名称", COUNT(p."ID") AS hospital_cnt FROM cq_district_population d LEFT JOIN cq_amap_poi_2024 p ON p."地址" LIKE '%' || d."区划名称" || '%' AND p."类型" LIKE '%医院%' WHERE d."常住人口" > 100 AND d."行政区划代码" != 500000 GROUP BY d."区划名称" ORDER BY hospital_cnt DESC;
```

**Failure reason buckets** (total 24):
- `row_count`: 18
- `rowset`: 3
- `empty`: 2
- `sql_error`: 1

**Raw failure reason distribution** (total 24 samples):
- `row count: gold=12 pred=11`: 15
- `rowset mismatch`: 3
- `empty`: 2
- `row count: gold=12 pred=0`: 1
- `row count: gold=12 pred=15`: 1
- `row count: gold=12 pred=39`: 1
- `(psycopg2.errors.SyntaxError) syntax error at or near ":"
LINE 1: SELECT * FROM D:\adk\data_agent\uploads\cq_benchmark\q ...`: 1

**gen_status distribution**:
- `ok`: 22
- `timeout`: 2

**Col-count (gold, pred) distribution**:
- gold=2 / pred=2: 16
- gold=2 / pred=None: 6
- gold=2 / pred=3: 1
- gold=2 / pred=1: 1

**Row-count (gold, pred) distribution** (only when reason=row_count):
- gold_rows=12 / pred_rows=11: 15
- gold_rows=12 / pred_rows=0: 1
- gold_rows=12 / pred_rows=15: 1
- gold_rows=12 / pred_rows=39: 1

**Distinct pred_sql** (top 10):
- [2× first=gemini-3.1-flash-lite-preview] `<EMPTY>`
- [1× first=deepseek-v4-flash] `SELECT d."区划名称", COUNT(p."ID") AS hospital_count FROM public.cq_district_population d LEFT JOIN public.cq_amap_poi_2024 p ON p."区域ID"::integer = d."行政区划代码" AND p."类型" LIKE '%医院%' WHERE d."行政区划代码" != 500000 AND d."常住人口" > ...`
- [1× first=deepseek-v4-flash] `SELECT p."区划名称", COUNT(*) AS 医院数量 FROM cq_district_population p JOIN cq_amap_poi_2024 a ON a."区域ID" = p."行政区划代码" WHERE p."常住人口" > 100 AND p."行政区划代码" != 500000 AND a."类型" LIKE '%医院%' GROUP BY p."区划名称" ORDER BY 医院数量 DESC L ...`
- [1× first=deepseek-v4-flash] `SELECT p."区划名称", COUNT(*) AS "医院数量" FROM public.cq_district_population p INNER JOIN public.cq_amap_poi_2024 a ON a."区域ID" = p."行政区划代码" WHERE p."行政区划代码" != 500000 AND p."常住人口" > 100 AND a."类型" LIKE '%医院%' GROUP BY p."区划名称 ...`
- [1× first=deepseek-v4-pro] `WITH pop AS ( SELECT "区划名称", "常住人口" FROM cq_district_population WHERE "行政区划代码" != 500000 AND "常住人口" > 100 ) SELECT pop."区划名称", COUNT(*) AS 医院数量 FROM pop JOIN cq_amap_poi_2024 AS h ON h."地址" LIKE '%' || pop."区划名称" || '%'  ...`
- [1× first=deepseek-v4-pro] `WITH high_pop_districts AS ( SELECT "区划名称", "常住人口" FROM public.cq_district_population WHERE "常住人口" > 100 AND "行政区划代码" != 500000 ) SELECT h."区划名称", COUNT(b."类型") AS "医院数量" FROM high_pop_districts h LEFT JOIN public.cq_bai ...`
- [1× first=deepseek-v4-pro] `SELECT p."区划名称", p."常住人口", COUNT(*) AS hospital_count FROM cq_district_population p JOIN cq_amap_poi_2024 a ON a."区域ID" = p."行政区划代码" WHERE p."常住人口" > 100 AND p."行政区划代码" != 500000 AND a."类型" LIKE '%医院%' GROUP BY p."区划名称", ...`
- [1× first=gemini-2.5-flash] `SELECT dp."区划名称", COUNT(bai."uid") AS "医院数量" FROM public.cq_district_population AS dp JOIN public.cq_baidu_aoi_2024 AS bai ON dp."区划名称" = bai."区县" WHERE dp."常住人口" > 1000000 AND dp."行政区划代码" != 500000 AND bai."第一分类" = '医疗' ...`
- [1× first=gemini-2.5-flash] `SELECT dp."区划名称", COUNT(bai."uid") AS hospital_count FROM public.cq_district_population AS dp JOIN public.cq_baidu_aoi_2024 AS bai ON dp."区划名称" = bai."区县" WHERE dp."常住人口" > 100 AND dp."行政区划代码" != 500000 AND bai."第一分类" =  ...`
- [1× first=gemini-2.5-flash] `SELECT dp."区划名称", COUNT(aoi."uid") AS "医院数量" FROM public.cq_district_population AS dp JOIN public.cq_baidu_aoi_2024 AS aoi ON dp."区划名称" = aoi."区县" WHERE dp."常住人口" > 100 AND dp."行政区划代码" != 500000 AND aoi."第一分类" = '医疗' GRO ...`

**Heuristic verdict**: **LIKELY GOLD ROW-COUNT OFF** — gold expects 12 rows but 15/24 samples consistently return 11 rows; gold filter/limit likely needs adjustment

---

## `CQ_GEO_HARD_23` — Cross-Table / Hard

**Question**: 统计每个历史文化街区里有多少栋建筑，然后按建筑数量从多到少排个序。

**Gold SQL** (cols=2):
```sql
SELECT h.jqmc, COUNT(DISTINCT b."Id") AS bld_cnt FROM cq_historic_districts h LEFT JOIN cq_buildings_2021 b ON ST_Contains(ST_Transform(h.shape, 4326), b.geometry) GROUP BY h.jqmc ORDER BY bld_cnt DESC;
```

**Failure reason buckets** (total 24):
- `row_count`: 20
- `rowset`: 4

**Raw failure reason distribution** (total 24 samples):
- `row count: gold=7 pred=5`: 20
- `rowset mismatch`: 4

**gen_status distribution**:
- `ok`: 24

**Col-count (gold, pred) distribution**:
- gold=2 / pred=2: 24

**Row-count (gold, pred) distribution** (only when reason=row_count):
- gold_rows=7 / pred_rows=5: 20

**Distinct pred_sql** (top 10):
- [2× first=qwen3.6-plus] `SELECT h."jqmc", COUNT(b."Id") AS "建筑数量" FROM public.cq_historic_districts h JOIN public.cq_buildings_2021 b ON ST_Intersects(ST_Transform(h.shape, 4326), b.geometry) GROUP BY h."jqmc" ORDER BY "建筑数量" DESC LIMIT 100000`
- [1× first=deepseek-v4-flash] `SELECT h."jqmc" AS 街区名称, COUNT(b."Id") AS 建筑数量 FROM public.cq_historic_districts h LEFT JOIN public.cq_buildings_2021 b ON ST_Contains(ST_Transform(h."shape", 4326), b."geometry") GROUP BY h."jqmc" ORDER BY 建筑数量 DESC LIM ...`
- [1× first=deepseek-v4-flash] `SELECT hd.jqmc AS 历史文化街区名称, COUNT(*) AS 建筑数量 FROM cq_historic_districts hd JOIN cq_buildings_2021 b ON ST_Contains(ST_Transform(hd.shape, 4326), b.geometry) GROUP BY hd.jqmc ORDER BY COUNT(*) DESC LIMIT 100000`
- [1× first=deepseek-v4-flash] `SELECT h."jqmc" AS 历史文化街区名称, COUNT(b."Id") AS 建筑数量 FROM public.cq_historic_districts h LEFT JOIN public.cq_buildings_2021 b ON ST_Contains(ST_Transform(h."shape", 4326), b."geometry") GROUP BY h."jqmc" ORDER BY COUNT(b." ...`
- [1× first=deepseek-v4-pro] `SELECT hd."jqmc" AS 街区名称, COUNT(*) AS 建筑数量 FROM public.cq_historic_districts hd JOIN public.cq_buildings_2021 b ON ST_Within(b.geometry, ST_Transform(hd.shape, 4326)) GROUP BY hd."jqmc" ORDER BY 建筑数量 DESC LIMIT 100000`
- [1× first=deepseek-v4-pro] `SELECT h.jqmc AS 街区名称, COUNT(*) AS 建筑数量 FROM cq_historic_districts h JOIN cq_buildings_2021 b ON ST_Within(b.geometry, ST_Transform(h.shape, 4326)) GROUP BY h.jqmc ORDER BY COUNT(*) DESC LIMIT 100000`
- [1× first=deepseek-v4-pro] `SELECT h.jqmc AS 历史文化街区, COUNT(*) AS 建筑数量 FROM cq_historic_districts h JOIN cq_buildings_2021 b ON ST_Contains(ST_Transform(h.shape, 4326), b.geometry) GROUP BY h.jqmc ORDER BY COUNT(*) DESC LIMIT 100000`
- [1× first=gemini-2.5-flash] `SELECT hd.jqmc, COUNT(b."Id") AS building_count FROM public.cq_historic_districts hd JOIN public.cq_buildings_2021 b ON ST_Intersects(hd.shape, ST_Transform(b.geometry, 4490)) GROUP BY hd.jqmc ORDER BY building_count DES ...`
- [1× first=gemini-2.5-flash] `SELECT hd.jqmc, COUNT(b."Id") AS building_count FROM public.cq_historic_districts AS hd JOIN public.cq_buildings_2021 AS b ON ST_Intersects(hd.shape, ST_Transform(b.geometry, 4490)) GROUP BY hd.jqmc ORDER BY building_cou ...`
- [1× first=gemini-2.5-flash] `SELECT d.jqmc AS "历史文化街区名称", COUNT(b."Id") AS "建筑数量" FROM public.cq_historic_districts AS d JOIN public.cq_buildings_2021 AS b ON ST_Intersects(d.shape, ST_Transform(b.geometry, 4490)) GROUP BY d.jqmc ORDER BY "建筑数量" DES ...`

**Heuristic verdict**: **LIKELY GOLD ROW-COUNT OFF** — gold expects 7 rows but 20/24 samples consistently return 5 rows; gold filter/limit likely needs adjustment

---
