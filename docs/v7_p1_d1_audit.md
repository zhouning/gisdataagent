# D1 Universal-Fail Audit (v7 P1)

Auto-generated from `audit_d1_universal_fails.py`.
Source: `data_agent\nl2sql_eval_results\v7_p1_main_n3_2026-05-13_172802` + `data_agent\nl2sql_eval_results\v7_gemma_n3_gapfill_20260523`.
Families: ['deepseek-v4-flash', 'deepseek-v4-pro', 'gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-3.1-flash-lite-preview', 'gemini-3.1-pro-preview', 'gemini-3.5-flash', 'gemma-4-31b-it-ollama', 'qwen3.6-flash', 'qwen3.6-plus', 'qwen3.7-max']
Universal-fail qids: **1**

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
| LIKELY EVALUATOR / GOLD STRICTNESS | 1 |

---

## `CQ_GEO_HARD_15` — KNN / Hard

**Question**: 找出离每条有名字的主干道最近的医疗设施是哪个？列出路名、医疗设施名和距离（米），只要最近的 5 对。

**Gold SQL** (cols=3):
```sql
SELECT DISTINCT ON (r.name) r.name AS road_name, a."名称" AS aoi_name, ST_Distance(r.geometry::geography, ST_Transform(a.shape, 4326)::geography) AS dist_m FROM cq_osm_roads_2021 r CROSS JOIN cq_baidu_aoi_2024 a WHERE r.fclass = 'primary' AND r.name IS NOT NULL AND a."第一分类" = '医疗' ORDER BY r.name, r.geometry <-> ST_Transform(a.shape, 4326) LIMIT 5;
```

**Failure reason buckets** (total 33):
- `rowset`: 24
- `empty`: 7
- `sql_error`: 2

**Raw failure reason distribution** (total 33 samples):
- `rowset mismatch`: 24
- `empty`: 7
- `(psycopg2.errors.SyntaxError) syntax error at or near ":"
LINE 1: ...CT road_name, medical_name, distance_meters FROM D: ...`: 1
- `(psycopg2.errors.SyntaxError) syntax error at or near ":"
LINE 1: SELECT * FROM D:\adk\data_agent\uploads\cq_benchmark\q ...`: 1

**gen_status distribution**:
- `ok`: 26
- `timeout`: 7

**Col-count (gold, pred) distribution**:
- gold=3 / pred=None: 17
- gold=3 / pred=3: 15
- gold=3 / pred=1: 1

**Distinct pred_sql** (top 10):
- [7× first=deepseek-v4-flash] `<EMPTY>`
- [1× first=deepseek-v4-flash] `WITH named_primary_roads AS ( SELECT "name", "geometry" FROM public.cq_osm_roads_2021 WHERE "fclass" = 'primary' AND "name" IS NOT NULL ), medical_pois AS ( SELECT "名称", "geometry" FROM public.cq_amap_poi_2024 WHERE "类型" ...`
- [1× first=deepseek-v4-flash] `WITH road_medical_pairs AS ( SELECT DISTINCT ON (r.name) r.name AS road_name, p."名称" AS medical_name, ST_Distance(r.geometry::geography, p.geometry::geography) AS distance_m FROM public.cq_osm_roads_2021 r CROSS JOIN LAT ...`
- [1× first=deepseek-v4-pro] `SELECT roads.name AS road_name, poi."名称" AS facility_name, ST_Distance(roads.geometry::geography, poi.geometry::geography) AS distance_m FROM public.cq_osm_roads_2021 AS roads CROSS JOIN LATERAL ( SELECT "名称", geometry F ...`
- [1× first=deepseek-v4-pro] `SELECT r."name" AS road_name, p."名称" AS facility_name, ST_Distance(r.geometry::geography, p.geometry::geography) AS distance_m FROM public.cq_osm_roads_2021 r CROSS JOIN LATERAL ( SELECT "名称", geometry FROM public.cq_ama ...`
- [1× first=deepseek-v4-pro] `SELECT r.name AS road_name, p."名称" AS facility_name, ST_Distance(r.geometry::geography, p.geometry::geography) AS distance_m FROM cq_osm_roads_2021 r CROSS JOIN LATERAL ( SELECT "名称", geometry FROM cq_amap_poi_2024 WHERE ...`
- [1× first=gemini-2.5-flash] `SELECT r.name AS road_name, p."名称" AS medical_facility_name, ST_Distance(r.geometry::geography, p.geometry::geography) AS distance_meters FROM public.cq_osm_roads_2021 AS r CROSS JOIN LATERAL ( SELECT "名称", geometry FROM ...`
- [1× first=gemini-2.5-flash] `SELECT r.name AS road_name, p."名称" AS medical_facility_name, ST_Distance(r.geometry::geography, p.geometry::geography) AS distance_meters FROM public.cq_osm_roads_2021 AS r CROSS JOIN LATERAL ( SELECT "名称", geometry FROM ...`
- [1× first=gemini-2.5-flash] `SELECT r.name AS road_name, p."名称" AS medical_facility_name, ST_Distance(r.geometry::geography, p.geometry::geography) AS distance_meters FROM public.cq_osm_roads_2021 AS r CROSS JOIN LATERAL ( SELECT p_inner."名称", p_inn ...`
- [1× first=gemini-2.5-pro] `SELECT roads.name AS road_name, pois."名称" AS facility_name, ROUND(ST_Distance(roads.geometry::geography, pois.geometry::geography)::numeric, 2) AS distance_meters FROM public.cq_osm_roads_2021 AS roads CROSS JOIN LATERAL ...`

**Heuristic verdict**: **LIKELY EVALUATOR / GOLD STRICTNESS** — 24/33 rowset_mismatch but pred SQLs vary; review if gold filter is too narrow

---
