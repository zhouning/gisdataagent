# FloodSQL-Bench Local PostgreSQL Dataset

**位置**: `192.168.100.215:30355` / database `gis_agent` / schema `floodsql_bench`
**PG 版本**: 14.15 + PostGIS 3.5.1
**数据来源**: HuggingFace `HanzhouLiu/FloodSQL-Bench` + GitHub `HanzhouLiu/FloodSQL-Bench` (Dec 16, 2025)
**论文**: arXiv 2512.12084 "FloodSQL-Bench: A Retrieval-Augmented Benchmark for Geospatially-Grounded Text-to-SQL"

## 连接信息

```bash
POSTGRES_HOST=192.168.100.215
POSTGRES_PORT=30355
POSTGRES_DATABASE=gis_agent
POSTGRES_USER=postgres
POSTGRES_PASSWORD='Supermap2024.'
SCHEMA=floodsql_bench
```

```python
from urllib.parse import quote_plus
url = f'postgresql+psycopg2://postgres:{quote_plus("Supermap2024.")}@192.168.100.215:30355/gis_agent'
```

## 数据集总览

聚焦三个洪水高发州（**Texas / Florida / Louisiana**），整合 10 张异构表，覆盖：
- **非空间属性表 4 张**: claims, svi, cre, nri
- **多边形空间层 4 张**: floodplain, census_tracts, zcta, county
- **点位层 2 张**: schools, hospitals（点位用 LAT/LON 字段，论文 A.1 显式说明 "opaque point BLOBs are discarded"）

**坐标系**: 全部 EPSG:4326 (WGS84 lon/lat)，Polygon 已 ST_SimplifyPreserveTopology 简化。

**总数据量**: ~2.3M rows, 灌库后约 5-6 GB（含 GIST + BTREE 索引）。

## 关键 ID 体系

| 标识 | 长度 | 说明 |
|---|---|---|
| **GEOID (tract-level)** | 11 位 | 2 位 STATEFP + 3 位 COUNTYFP + 6 位 tract code，主键关联 census_tracts/claims/svi/nri/cre |
| **GEOID (county-level)** | 5 位 | 11 位的左 5 位前缀，关联 county/hospitals.countyfips |
| **STATEFP** | 2 位 | `'12'`=Florida, `'22'`=Louisiana, `'48'`=Texas |
| **ZIP** | 5 位 | 关联 schools/hospitals |

---

## 10 张表详细描述

### 1. `floodsql_bench.census_tracts` (13,444 rows × 5 cols)

**用途**：U.S. Census 普查 tract 多边形边界（最细粒度的关联键载体）

| 列 | 类型 | 含义 |
|---|---|---|
| `geoid` | text | **11 位 GEOID** ⭐ 主键 |
| `statefp` | text | 2 位州 FIPS（'12'/'22'/'48'）|
| `countyfp` | text | 3 位县 FIPS |
| `name` | text | tract 名称（如 `'101.02'`）|
| `geometry` | geometry(MultiPolygon, 4326) | **GIST 索引** ⭐ |

**关联**：通过 `geoid` 直接 key-join → claims/svi/nri/cre；通过 `geometry` 空间 join → floodplain/zcta/county/schools/hospitals

---

### 2. `floodsql_bench.county` (385 rows × 5 cols)

**用途**：县级行政边界（TX/FL/LA 共 385 县）

| 列 | 类型 | 含义 |
|---|---|---|
| `geoid` | text | **5 位 GEOID** ⭐ 主键 |
| `statefp` | text | 2 位州 FIPS |
| `countyfp` | text | 3 位县 FIPS |
| `name` | text | 县名（如 `'Harris'`）|
| `geometry` | geometry(MultiPolygon, 4326) | **GIST 索引** |

**关联**：`LEFT(claims.geoid, 5) = county.geoid` (key)；空间 join → floodplain/zcta

---

### 3. `floodsql_bench.floodplain` (915,760 rows × 4 cols) ⭐

**用途**：FEMA 国家洪水危险图层（NFHL）多边形——**最大空间表**

| 列 | 类型 | 含义 |
|---|---|---|
| `gfid` | text | FEMA 图斑 ID |
| `statefp` | text | 2 位州 FIPS |
| `fld_zone` | text | 洪水危险区类型（`'A', 'AE', 'X', 'D', 'AH', 'AO', 'V', 'VE', 'OPEN_WATER'` 等 10 种）|
| `geometry` | geometry(MultiPolygon, 4326) | **GIST 索引** ⭐ 简化容差 100m |

**特点**：
- ~875K MultiPolygon + ~40K Polygon
- 无键关联，**仅靠 spatial join** 与 census_tracts/zcta/county/schools/hospitals 关联
- 是 L2/L4/L5 级题目（spatial join）的核心表，**复杂题可能 60s+**

---

### 4. `floodsql_bench.zcta` (5,284 rows × 3 cols)

**用途**：ZIP Code Tabulation Area（ZCTA）多边形边界

| 列 | 类型 | 含义 |
|---|---|---|
| `geoid` | text | 5 位 ZIP code（**注意**：ZCTA != USPS ZIP）|
| `statefp` | text | 2 位州 FIPS |
| `geometry` | geometry(MultiPolygon, 4326) | **GIST 索引** |

**关联**：仅 spatial join（无键）；与 census_tracts/floodplain/county/schools/hospitals 做 polygon-polygon 或 point-polygon 相交

---

### 5. `floodsql_bench.claims` (1,316,689 rows × 8 cols) ⭐

**用途**：NFIP（国家洪水保险计划）历史理赔记录——**最大业务表**

| 列 | 类型 | 含义 |
|---|---|---|
| `id` | text | 理赔单号 |
| `geoid` | text | **11 位 GEOID** ⭐（关联 census_tracts/svi/nri/cre）|
| `statefp` | text | 2 位州 FIPS |
| `dateofloss` | **date** | 损失日期 |
| `amountpaidonbuildingclaim` | text* | 建筑物理赔金额 USD |
| `amountpaidoncontentsclaim` | text* | 物品理赔金额 USD |
| `amountpaidonincreasedcostofcomplianceclaim` | text* | ICC 理赔金额 USD |
| `geometry` | geometry(Point, 4326) | 理赔点位（论文 A.1 说"用作 key-only 关联，不做 spatial"）|

⚠️ `text*`: 三个金额列在 PG 是 **text 类型**（DuckDB 写出来时是字符串）。SQL 里用了 `CAST(col AS DOUBLE PRECISION)` 转换 — 数据值范围 -201,667.50 .. +10,741,476.93。

**关联**：
- key: `geoid` 11 位 → census_tracts/svi/nri/cre
- key: `LEFT(geoid, 5) = county.geoid`（聚到县级）
- spatial join：**论文不推荐**用 claims.geometry 做 spatial（用 GEOID 即可）

---

### 6. `floodsql_bench.hospitals` (1,526 rows × 13 cols)

**用途**：医院点位（HIFLD 数据集）

| 列 | 类型 | 含义 |
|---|---|---|
| `hospital_id` | text | 唯一 ID |
| `name` | text | 医院名 |
| `address`, `city`, `state`, `zip`, `county` | text | 地址信息 |
| `countyfips` | text | **5 位县 FIPS** ⭐ |
| `lat` | double precision | 纬度 |
| `lon` | double precision | 经度 |
| `type` | text | 医院类型（如 `'GENERAL ACUTE CARE'`, `'CRITICAL ACCESS'`, `'PSYCHIATRIC'`，10 类）|
| `statefp` | text | 2 位州 FIPS |
| `unique_id` | text | 复合 ID（如 `'48_hospital_0005479830'`）|

**特别说明**：**没有 geometry 列**（论文 A.1: "opaque point BLOBs are discarded"）。SQL 用 `ST_SetSRID(ST_Point(lon, lat), 4326)` 现场构造点位（rewrite 规则 #3）。

**关联**：
- key: `countyfips` ↔ county.geoid; `zip` ↔ schools.zip
- spatial: `ST_SetSRID(ST_Point(lon, lat), 4326)` 与 census_tracts/floodplain/zcta/county 做 point-in-polygon

---

### 7. `floodsql_bench.schools` (20,523 rows × 11 cols)

**用途**：学校点位（HIFLD 数据集）

| 列 | 类型 | 含义 |
|---|---|---|
| `school_id` | text | 唯一 ID |
| `name`, `address`, `city`, `state`, `zip` | text | 地址信息 |
| `lat` | double precision | 纬度 |
| `lon` | double precision | 经度 |
| `type` | text | 类型（3 类：`'COLLEGE'`, `'PUBLIC_SCHOOL'`, `'PRIVATE_SCHOOL'`）|
| `statefp` | text | 2 位州 FIPS |
| `unique_id` | text | 复合 ID |

**关联**：
- key: `zip` ↔ hospitals.zip; **没有 countyfips 列**（必须 spatial 算）
- spatial: 同 hospitals 模式

---

### 8. `floodsql_bench.svi` (13,385 rows × 159 cols) ⭐

**用途**：CDC/ATSDR 社会脆弱指数（SVI）——**最复杂表**

主要列分组（共 159 列）：
| 类别 | 列例 | 说明 |
|---|---|---|
| **Identifiers** | `geoid`(text, 11 位 ⭐), `st`(int), `state`, `st_abbr`, `stcnty`, `county`, `fips`, `location` | 地理键 |
| **Demographics (E_*)** | `e_totpop`, `e_pov150`, `e_unemp`, `e_age65`, `e_age17`, `e_minrty`, `e_disabl`, `e_sngpnt`, `e_limeng`, `e_uninsur`, ... (~30 列 bigint) | 估计值 |
| **Margins of error (M_*)** | `m_totpop`, `m_pov150`, ... | 误差界 |
| **Percentages (EP_*, MP_*)** | `ep_pov150`, `ep_unemp`, ... | 百分比形式 |
| **Percentile ranks (EPL_*)** | `epl_pov150`, `epl_unemp`, ... | 0-1 排名 |
| **Theme rankings (RPL_THEME{1-4})** ⭐ | `rpl_theme1` (Socioeconomic), `rpl_theme2` (Household), `rpl_theme3` (Minority), `rpl_theme4` (Housing) | **4 大主题相对脆弱性 0-1**（题目最常引用）|
| **Composite (RPL_THEMES, SPL_*)** | `rpl_themes`, `spl_themes` | 总体脆弱性 |
| **Race (E_AFAM, E_HISP 等)** | bigint | 各族群人口 |
| **Flags (F_*)** | bigint | 标记字段 |
| **`-999` 标记缺失值** | | SVI 约定：填值 -999 表示缺失（不是 NULL）|

**关联**：通过 `geoid` 11 位 key-join 到 census_tracts/claims/nri/cre

---

### 9. `floodsql_bench.nri` (13,373 rows × 50 cols) ⭐

**用途**：FEMA National Risk Index（国家风险指数）——**多 hazard 的洪水风险评估**

主要列：
| 类别 | 列例 | 说明 |
|---|---|---|
| **Identifiers** | `geoid` (text, 11 位 ⭐), `state` (text: 'TX'/'FL'/'LA') | |
| **Coastal Flood (CFLD_\*)** | `cfld_evnts`, `cfld_afreq`, `cfld_exp_area`, `cfld_expb`, `cfld_eals`, `cfld_riskr` | **沿海洪水**风险 |
| **Riverine Flood (RFLD_\*)** | `rfld_evnts`, `rfld_afreq`, `rfld_eals`, `rfld_riskr`, ... | **河洪**风险 |
| **Risk rating (`*_riskr`)** | text | 风险等级（'Very Low'/'Relatively Low'/'Relatively Moderate'/'Relatively High'/'Very High'/'No Rating'/'Insufficient Data'）|
| **Loss estimates (`*_eal*`)** | double | 期望年损失（建筑/人口/农业/总）|

**关联**：通过 `geoid` 11 位 key-join

---

### 10. `floodsql_bench.cre` (13,444 rows × 20 cols)

**用途**：U.S. Census Community Resilience Estimates（社区韧性估计）

| 列 | 类型 | 含义 |
|---|---|---|
| `geoid` | text | 11 位 ⭐ |
| `geo_id` | text | 全长 GEOID（如 `'1400000US12001000201'`）|
| `state`, `county`, `tract` | bigint | 数字形式 |
| `name` | text | tract 描述 |
| `popuni` | bigint | 总人口 |
| `pred0_e/m/pe/pm` | bigint/double | **0 个**风险因子的人口（估计/误差界/百分比/百分比误差）|
| `pred12_e/m/pe/pm` | bigint/double | **1-2 个**风险因子的人口 |
| `pred3_e/m/pe/pm` | bigint/double | **≥3 个**风险因子的人口 |

**含义**：CRE 把人按"面对的风险因子数"分桶（0 / 1-2 / ≥3）—— 风险因子越多，灾害韧性越差。

**关联**：通过 `geoid` key-join

---

## Join 关系矩阵（论文 Table 1）

```
        Tract Flood ZCTA Schl Hosp Claim Cnty NRI SVI CRE
Tract     -    S    S    S    S    K    S/K  K   K   K
Flood     S    -    S    S    S    -    S    -   -   -
ZCTA      S    S    -    S    S    -    S    -   -   -
Schl      S    S    S    -    K    -    S    -   -   -
Hosp      S    S    S    K    -    -    S/K  -   -   -
Claim     K    -    -    -    -    -    K    K   K   K
Cnty      S/K  S    S    S    S/K  K    -    K   K   K
NRI       K    -    -    -    -    K    K    -   K   K
SVI       K    -    -    -    -    K    K    K   -   K
CRE       K    -    -    -    -    K    K    K   K   -
```

| 标记 | 说明 |
|---|---|
| **K** = Key-based join（GEOID/COUNTYFIPS/ZIP）|
| **S** = Spatial join（ST_Intersects/ST_Contains/ST_Within）|
| **S/K** = 两种路径都可用 |
| **-** = 不直接 join |

**14 条 key-based + 14 条 spatial = 28 条 join 规则**

---

## 索引清单

| 表 | 索引 |
|---|---|
| census_tracts | GIST(geometry), BTREE(geoid), BTREE(statefp) |
| county | GIST(geometry), BTREE(geoid), BTREE(statefp) |
| floodplain | GIST(geometry), BTREE(statefp) |
| zcta | GIST(geometry), BTREE(geoid), BTREE(statefp) |
| claims | BTREE(geoid), BTREE(statefp), BTREE(dateofloss) |
| hospitals | BTREE(zip), BTREE(statefp), BTREE(countyfips), BTREE(lat), BTREE(lon) |
| schools | BTREE(zip), BTREE(statefp) |
| svi | BTREE(geoid), BTREE(state) |
| nri | BTREE(geoid), BTREE(state) |
| cre | BTREE(geoid) |

---

## DuckDB → PostgreSQL Rewrite 规则（4 条覆盖 100% gold SQL）

| # | DuckDB 写法 | PG 替换 | 影响题数 |
|---|---|---|---|
| 1 | `STRFTIME('%Y', col)` | `EXTRACT(YEAR FROM col)::TEXT` | 1 |
| 2 | `CAST(... AS DOUBLE)` | `CAST(... AS DOUBLE PRECISION)` | 56 |
| 3 | `ST_Point(lon, lat)` | `ST_SetSRID(ST_Point(lon, lat), 4326)` | 113 |
| 4 | `tablename` (unqualified) | `floodsql_bench.tablename` | 全部 |

加上 **lowercase 列名**（loader 已处理）让 unquoted mixed-case 引用（如 `dateOfLoss`、`RPL_THEME1`）直接跑通。

---

## 题目示例（per-level）

### L0 — 单表（50 题）
```sql
-- L0_0001: Harris County 自 2010-01-01 起 NFIP 理赔数
SELECT COUNT(*) AS num_claims
FROM floodsql_bench.claims
WHERE geoid LIKE '48201%' AND dateofloss >= DATE '2010-01-01';
-- gold result: [[75192]]
```

### L1 — 双表 key join（100 题）
```sql
-- L1_0001: Louisiana NFIP 理赔最多的年份（claims × county）
SELECT EXTRACT(YEAR FROM cl.dateofloss)::TEXT AS year
FROM floodsql_bench.claims cl
JOIN floodsql_bench.county c ON LEFT(cl.geoid, 5) = c.geoid
WHERE c.statefp = '22' AND cl.dateofloss IS NOT NULL
GROUP BY year ORDER BY COUNT(*) DESC LIMIT 1;
-- gold result: [['2005']]
```

### L2 — 双表 spatial join（150 题）
```sql
-- L2_0001: Duval County 与 floodplain 相交的 census_tracts 数
SELECT COUNT(DISTINCT a.geoid)
FROM floodsql_bench.census_tracts a
JOIN floodsql_bench.floodplain b ON ST_Intersects(a.geometry, b.geometry)
WHERE a.geoid LIKE '12031%' AND ST_IsValid(a.geometry) AND ST_IsValid(b.geometry);
-- gold result: [[219]]
```

### L3 — 三表 key-key（50 题）
```sql
-- L3_0001: Texas 有理赔的 tract 中, 加权平均河洪事件数（claims × nri × svi）
SELECT SUM(n.rfld_evnts * s.ep_noveh) / SUM(s.ep_noveh) AS weighted_avg_events
FROM (SELECT DISTINCT geoid, statefp FROM floodsql_bench.claims WHERE statefp = '48') cl
JOIN floodsql_bench.nri n ON cl.geoid = n.geoid
JOIN floodsql_bench.svi s ON s.geoid = cl.geoid
WHERE n.rfld_evnts IS NOT NULL AND s.ep_noveh IS NOT NULL;
-- gold result: [[93.17169105846224]]
```

### L4 — 三表 key-spatial（43 题）
```sql
-- L4_0001: Texas 与 floodplain 相交的 census_tracts 平均 RPL_THEME1
SELECT AVG(v.rpl_theme1) AS avg_theme1_rank
FROM floodsql_bench.svi v
JOIN floodsql_bench.census_tracts t ON v.geoid = t.geoid
JOIN floodsql_bench.floodplain f ON ST_Intersects(t.geometry, f.geometry)
WHERE t.statefp = '48' AND ST_IsValid(t.geometry) AND ST_IsValid(f.geometry)
  AND v.rpl_theme1 IS NOT NULL AND v.rpl_theme1 BETWEEN 0 AND 100;
-- gold result: [[0.543291524199177]]
```

### L5 — 三表 spatial-spatial（50 题）
```sql
-- L5_0001: Harris County 同时位于 floodplain 和 census_tract 的医院数
SELECT COUNT(DISTINCT h.unique_id) AS num_hospitals
FROM floodsql_bench.hospitals h
JOIN floodsql_bench.floodplain f ON ST_Within(ST_SetSRID(ST_Point(h.lon, h.lat), 4326), f.geometry)
JOIN floodsql_bench.census_tracts t ON ST_Within(ST_SetSRID(ST_Point(h.lon, h.lat), 4326), t.geometry)
WHERE LEFT(t.geoid, 5) = '48201' AND ST_IsValid(f.geometry) AND ST_IsValid(t.geometry);
-- gold result: [[106]]
```

---

## 数据使用注意

1. **空间查询要加 `ST_IsValid(geom)`** —— floodplain 有 ~5% 几何不闭合，会让 ST_Intersects 报错
2. **复杂 spatial join 可能 60s+** —— L4/L5 涉及 floodplain × census_tracts，建议 `statement_timeout = 180s`
3. **claims 金额列是 text** —— 题目里都用 `CAST(col AS DOUBLE PRECISION)` 解析
4. **SVI 用 -999 表示缺失** —— 不是 NULL，过滤时要 `BETWEEN 0 AND 100` 或 `!= -999`
5. **state 字段不一致**：
   - `nri.state`/`hospitals.state`/`schools.state`: 'TX'/'FL'/'LA'（缩写）
   - `svi.state`: 'Texas'/'Florida'/'Louisiana'（全名）
   - `svi.st_abbr`: 'TX'/'FL'/'LA'
   - `cre.state`: 12/22/48（数字 STATEFP）

---

## Benchmark 题库（GitHub repo）

```
D:/adk/data/floodsql_bench_repo/benchmark/
├── bechmark_updated.jsonl       # 443 题最终版 ⭐
├── benchmark.jsonl               # 450 题旧版
├── single_table/50.json         # L0 难度
├── double_table_key/100.json    # L1
├── double_table_spatial/150.json # L2
├── triple_table_key/50.json     # L3
├── triple_table_key_spatial/50.json # L4
├── triple_table_spatial_spatial/50.json # L5（待确认目录名）
└── triple_table_spatial_spatial_updated/  # L5 修订版
```

每条记录格式：
```json
{
  "id": "L0_0001",
  "question": "In Harris County, Texas...",
  "sql": "SELECT COUNT(*) FROM claims WHERE GEOID LIKE '48201%'...",
  "elapsed": 0.054,
  "row_count": 1,
  "result": [[75192]]   // gold output, 已用 DuckDB 预跑
}
```

**难度分布**：L0=50 + L1=100 + L2=150 + L3=50 + L4=43 + L5=50 = **443 题**

---

## 跟 v7 CQ 重庆 benchmark 对比

| 维度 | CQ 重庆（v7）| FloodSQL-Bench |
|---|---|---|
| 题数 | 125 | 443 |
| 语言 | 中文 | 英文 |
| 域 | 通用 GIS | 洪水风险（窄域）|
| 表数 | ~10 | 10 |
| 总数据 | ~150 万行 | ~230 万行 |
| 难度 | 单/双/三表混合 | L0-L5 严格分级 |
| Schema 复杂度 | 中（10-20 列）| **高**（svi 159 列）|
| 中文列名 | 是（DLMC、TBMJ 等）| 无 |
| Gold 已预跑 | 是 | **是**（result 字段）|
| 评估方法 | EX 执行准确率 | 论文用 embedding cosine（你用 EX 重测）|
