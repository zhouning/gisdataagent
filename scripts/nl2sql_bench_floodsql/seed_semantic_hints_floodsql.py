"""Seed FloodSQL-Bench business rules into the semantic-layer DB (Phase 0a step 2).

Mirror of `data_agent/seed_semantic_hints_cq.py` for FloodSQL-Bench.
Writes domain rules to:
  - agent_semantic_hints                  (free-text business rules)
  - agent_semantic_registry.value_semantics  (per-column enums/sentinels/units)
  - agent_semantic_sources.synonyms       (additional fuzzy-match aliases)

Idempotent: safe to re-run.

Usage:
    cd D:/adk
    .venv/Scripts/python.exe scripts/nl2sql_bench_floodsql/seed_semantic_hints_floodsql.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).resolve().parents[2] / "data_agent" / ".env"), override=True)


# ---------------------------------------------------------------------------
# Hints: 24 business rules covering ID encoding, dialect quirks, NULL
# conventions, spatial pitfalls, and column-vs-column choice.
# ---------------------------------------------------------------------------
_HINTS: list[dict] = [
    # === ID-encoding rules ===
    {
        "scope_type": "dataset",
        "scope_ref": "floodsql_bench_geoid",
        "hint_kind": "category_choice",
        "severity": "critical",
        "hint_text_zh": "FloodSQL 用 11 位 GEOID 作 tract 主键，前 5 位 = 5 位县级 GEOID（STATEFP+COUNTYFP）。LEFT(geoid, 5) 提取县代码; LEFT(geoid, 2) 提取州代码。",
        "hint_text_en": "FloodSQL uses 11-digit GEOID as tract primary key; LEFT(geoid, 5) = county GEOID (STATEFP + COUNTYFP). LEFT(geoid, 2) = state code.",
        "trigger_keywords": ["GEOID", "tract", "county", "Harris", "Miami-Dade", "Orleans"],
    },
    {
        "scope_type": "dataset",
        "scope_ref": "floodsql_bench_statefp",
        "hint_kind": "value_enum",
        "severity": "warn",
        "hint_text_zh": "STATEFP: '12'=Florida, '22'=Louisiana, '48'=Texas. 注意是字符串非数字。Texas 的 GEOID 以 '48' 开头（如 Harris County GEOID 前 5 位 = '48201'）。",
        "hint_text_en": "STATEFP: '12'=FL, '22'=LA, '48'=TX (string, not int). Texas tracts have GEOID LIKE '48%'. E.g. Harris County = '48201'.",
        "trigger_keywords": ["Texas", "Florida", "Louisiana", "Harris", "Miami", "New Orleans"],
    },

    # === claims TEXT amount columns ===
    {
        "scope_type": "table",
        "scope_ref": "claims",
        "hint_kind": "unit_note",
        "severity": "critical",
        "hint_text_zh": "claims 表的 amountpaidonbuildingclaim / amountpaidoncontentsclaim / amountpaidonincreasedcostofcomplianceclaim 三个金额列存储为 TEXT，做数值聚合前必须 CAST(col AS DOUBLE PRECISION)；DOUBLE 单写在 PG 不存在。",
        "hint_text_en": "In claims table, amountpaidonbuildingclaim / amountpaidoncontentsclaim / amountpaidonincreasedcostofcomplianceclaim are TEXT. CAST(col AS DOUBLE PRECISION) before SUM/AVG/MAX. Bare DOUBLE is NOT a PG type — use DOUBLE PRECISION.",
        "trigger_keywords": ["amount paid", "building claim", "contents claim", "ICC", "payout", "average", "sum", "max"],
    },

    # === SVI -999 missing-value sentinel ===
    {
        "scope_type": "table",
        "scope_ref": "svi",
        "hint_kind": "filter_default",
        "severity": "critical",
        "hint_text_zh": "SVI 表用 -999 表示缺失（不是 NULL）。RPL_THEMES / RPL_THEME{1-4} / EPL_* 等列过滤要 BETWEEN 0 AND 100 或 != -999；IS NOT NULL 不会过掉 -999。",
        "hint_text_en": "SVI uses -999 as missing-value sentinel (NOT NULL). When filtering RPL_THEMES / RPL_THEME{1-4} / EPL_*, use BETWEEN 0 AND 100 or != -999 — IS NOT NULL will NOT filter out -999.",
        "trigger_keywords": ["RPL_THEME", "RPL_THEMES", "EPL_", "vulnerability", "percentile rank", "non-null"],
    },

    # === hospitals/schools have no geometry — must construct point ===
    {
        "scope_type": "table",
        "scope_ref": "hospitals",
        "hint_kind": "srid_note",
        "severity": "critical",
        "hint_text_zh": "hospitals 表没有 geometry 列（论文 A.1: opaque BLOBs discarded），必须用 ST_SetSRID(ST_Point(lon, lat), 4326) 现场构造点；裸 ST_Point 不带 SRID, spatial join 时会报 'mixed SRID' 错。",
        "hint_text_en": "hospitals has NO geometry column. Construct points on the fly: ST_SetSRID(ST_Point(lon, lat), 4326). Bare ST_Point returns SRID=0 and crashes spatial joins with 'mixed SRID' error.",
        "trigger_keywords": ["hospital", "ST_Point", "ST_Within", "ST_Contains", "spatial join"],
    },
    {
        "scope_type": "table",
        "scope_ref": "schools",
        "hint_kind": "srid_note",
        "severity": "critical",
        "hint_text_zh": "schools 表没有 geometry 列，用 ST_SetSRID(ST_Point(lon, lat), 4326) 构造点。",
        "hint_text_en": "schools has NO geometry column. Use ST_SetSRID(ST_Point(lon, lat), 4326) to construct points.",
        "trigger_keywords": ["school", "ST_Point", "spatial filter"],
    },

    # === floodplain ST_IsValid guard ===
    {
        "scope_type": "table",
        "scope_ref": "floodplain",
        "hint_kind": "filter_default",
        "severity": "warn",
        "hint_text_zh": "floodplain 表 ~5% 多边形几何不闭合，spatial join 前要加 ST_IsValid(f.geometry) 过滤；censu_tracts 也建议加 ST_IsValid。",
        "hint_text_en": "About 5% of floodplain polygons are invalid. Always add ST_IsValid(f.geometry) when ST_Intersects/ST_Contains/ST_Within with floodplain. Add ST_IsValid for census_tracts too as a defensive practice.",
        "trigger_keywords": ["floodplain", "flood zone", "spatial join", "ST_Intersects", "ST_Contains"],
    },

    # === claims is key-only, do not spatial-join its geometry ===
    {
        "scope_type": "table",
        "scope_ref": "claims",
        "hint_kind": "join_note",
        "severity": "info",
        "hint_text_zh": "claims 的 geometry 列虽然是 Point 类型，但论文规定它仅作 key-only 关联（用 GEOID）；不做 spatial join。需要 claims 与空间层关联时先按 GEOID join 到 census_tracts，再用 census_tracts.geometry 做空间运算。",
        "hint_text_en": "claims.geometry is stored as Point but per benchmark spec is KEY-ONLY (use GEOID). Do NOT spatial-join via claims.geometry. To intersect claims with floodplain, key-join to census_tracts first then spatial-join census_tracts.geometry to floodplain.",
        "trigger_keywords": ["claim", "spatial join", "ST_Intersects"],
    },

    # === state field discrepancies ===
    {
        "scope_type": "dataset",
        "scope_ref": "floodsql_bench_state_fmt",
        "hint_kind": "value_enum",
        "severity": "warn",
        "hint_text_zh": "state 字段格式不一致：hospitals.state/schools.state='TX'/'FL'/'LA'（缩写）, svi.state='Texas'/'Florida'/'Louisiana'（全名）, svi.st_abbr='TX'/'FL'/'LA', cre.state=12/22/48（数字 STATEFP）, nri.state='TX'/'FL'/'LA'。Cross-table 过滤要按各表实际格式。",
        "hint_text_en": "state column format varies: hospitals/schools/nri.state = 'TX'/'FL'/'LA' (abbr), svi.state = 'Texas'/'Florida'/'Louisiana' (full), svi.st_abbr = 'TX'/'FL'/'LA', cre.state = 12/22/48 (numeric). Filter using each table's actual format.",
        "trigger_keywords": ["state", "Texas", "Florida", "Louisiana", "TX", "FL", "LA"],
    },

    # === DOUBLE PRECISION dialect ===
    {
        "scope_type": "dataset",
        "scope_ref": "floodsql_bench_dialect",
        "hint_kind": "other",
        "severity": "critical",
        "hint_text_zh": "DuckDB 接受 CAST(col AS DOUBLE), PostgreSQL 不接受裸 DOUBLE; 必须用 CAST(col AS DOUBLE PRECISION) 或 col::DOUBLE PRECISION 或 col::FLOAT8。STRFTIME 也是 DuckDB 函数，PG 用 EXTRACT(YEAR FROM date)::TEXT 替代。",
        "hint_text_en": "PostgreSQL does NOT accept bare DOUBLE — use DOUBLE PRECISION or FLOAT8. STRFTIME is DuckDB-only — use EXTRACT(YEAR FROM date)::TEXT instead.",
        "trigger_keywords": ["CAST", "DOUBLE", "STRFTIME", "year", "extract"],
    },

    # === floodplain has no GEOID — spatial-only ===
    {
        "scope_type": "table",
        "scope_ref": "floodplain",
        "hint_kind": "join_note",
        "severity": "info",
        "hint_text_zh": "floodplain 没有 GEOID/key 列，只能通过 ST_Intersects/ST_Within 等空间谓词与其他表关联。zcta 也是 spatial-only（geoid 是 ZIP code 不是 tract）。",
        "hint_text_en": "floodplain has NO key column — spatial joins only. zcta is also spatial-only (its 'geoid' is a ZIP code, not a tract GEOID).",
        "trigger_keywords": ["floodplain", "zcta", "ZIP", "spatial join", "key join"],
    },

    # === county.name does not include "County" ===
    {
        "scope_type": "column",
        "scope_ref": "county.name",
        "hint_kind": "value_enum",
        "severity": "info",
        "hint_text_zh": "county.name 不包含 'County' 后缀（如 'Harris', 不是 'Harris County'）；svi.county 包含 'County' 后缀。",
        "hint_text_en": "county.name has NO 'County' suffix (e.g. 'Harris'). svi.county DOES include 'County' suffix.",
        "trigger_keywords": ["county name", "Harris County", "Miami-Dade"],
    },

    # === Theme 1-4 semantic mapping ===
    {
        "scope_type": "table",
        "scope_ref": "svi",
        "hint_kind": "category_choice",
        "severity": "info",
        "hint_text_zh": "SVI 4 个主题映射：RPL_THEME1=Socioeconomic（社会经济）, RPL_THEME2=Household Composition（家庭构成）, RPL_THEME3=Minority/Language（少数族裔/语言）, RPL_THEME4=Housing/Transportation（住房/交通）。RPL_THEMES=4 主题综合。值范围 0-1, -999=missing。",
        "hint_text_en": "SVI 4 themes: RPL_THEME1=Socioeconomic, RPL_THEME2=Household Composition, RPL_THEME3=Minority/Language, RPL_THEME4=Housing/Transportation. RPL_THEMES=overall composite (0-1 rank, -999=missing).",
        "trigger_keywords": ["Theme 1", "Theme 2", "Theme 3", "Theme 4", "Socioeconomic", "minority", "household composition", "housing transportation"],
    },

    # === NRI CFLD vs RFLD ===
    {
        "scope_type": "table",
        "scope_ref": "nri",
        "hint_kind": "category_choice",
        "severity": "info",
        "hint_text_zh": "NRI 表两类 flood: CFLD_*=Coastal Flood（沿海洪水）, RFLD_*=Riverine Flood（河洪）。每类有 EVNTS（事件数）, AFREQ（年频率）, EXP*（暴露）, HLR*（历史损失率）, EAL*（期望年损失）, RISK*（综合风险）。",
        "hint_text_en": "NRI has two flood families: CFLD_* (Coastal Flood) and RFLD_* (Riverine Flood). Each has EVNTS, AFREQ, EXP*, HLR*, EAL*, RISK* components.",
        "trigger_keywords": ["coastal flood", "riverine flood", "CFLD", "RFLD", "expected annual loss", "EAL"],
    },

    # === LIMIT/ORDER BY discipline ===
    {
        "scope_type": "dataset",
        "scope_ref": "floodsql_bench_orderby",
        "hint_kind": "other",
        "severity": "info",
        "hint_text_zh": "提到 'top N / highest / largest / lowest' 时配合 ORDER BY ... DESC/ASC LIMIT N；不要光 LIMIT 不 ORDER BY。统计性 ORDER BY pcsscs DESC + LIMIT 10 用于 top-K，注意是稳定排序时才确定。",
        "hint_text_en": "When question says 'top N / highest / largest / lowest', use ORDER BY ... DESC/ASC LIMIT N. LIMIT without ORDER BY is non-deterministic in PG.",
        "trigger_keywords": ["top", "highest", "largest", "smallest", "lowest", "rank"],
    },

    # === fld_zone enum guidance ===
    {
        "scope_type": "column",
        "scope_ref": "floodplain.fld_zone",
        "hint_kind": "value_enum",
        "severity": "info",
        "hint_text_zh": "fld_zone 有 10 个枚举值: A/AE/AH/AO=1% 年发洪水概率（100年洪水）, V/VE=沿海高风险, X=最低风险, D=未确定, OPEN_WATER=水体. 'high-risk flood zone' 一般指 A* / V* 系列。",
        "hint_text_en": "fld_zone enum: A/AE/AH/AO = 1% annual chance flood (100-year), V/VE = coastal high-risk, X = minimal risk, D = undetermined, OPEN_WATER. 'High-risk flood zone' usually means A* or V* codes.",
        "trigger_keywords": ["high-risk flood zone", "100-year flood", "fld_zone", "AE zone", "VE zone"],
    },

    # === spatial join + COUNT DISTINCT discipline ===
    {
        "scope_type": "dataset",
        "scope_ref": "floodsql_bench_spatial_count",
        "hint_kind": "join_note",
        "severity": "warn",
        "hint_text_zh": "Spatial join 计数时要用 COUNT(DISTINCT child.<id>) 防多边形重叠造成重复计数（如一个 census_tract 可能与多个 floodplain polygon 相交，每个相交记一次会膨胀）。例：COUNT(DISTINCT a.geoid)、COUNT(DISTINCT h.unique_id)。",
        "hint_text_en": "When counting via spatial join, use COUNT(DISTINCT child.<id>) to avoid double-counting due to polygon overlap (e.g., a census_tract intersecting multiple floodplain polygons would be counted N times without DISTINCT). E.g., COUNT(DISTINCT a.geoid) or COUNT(DISTINCT h.unique_id).",
        "trigger_keywords": ["how many", "count", "spatial join", "intersects", "within"],
    },

    # === City-level filtering ===
    {
        "scope_type": "dataset",
        "scope_ref": "floodsql_bench_city_filter",
        "hint_kind": "category_choice",
        "severity": "info",
        "hint_text_zh": "题目提 'in San Antonio, TX / in Austin, TX' 等城市，hospitals/schools 用 city = 'SAN ANTONIO' AND statefp = '48' 过滤（city 是 UPPERCASE）；不能用 city LIKE '%San Antonio%'。",
        "hint_text_en": "When filtering by city in hospitals/schools, use city = 'SAN ANTONIO' AND statefp = '48' (city is UPPERCASE in source). Avoid case-sensitive LIKE.",
        "trigger_keywords": ["in San Antonio", "in Austin", "in Houston", "in Miami", "in Dallas", "in Tampa"],
    },

    # === Date filtering ===
    {
        "scope_type": "column",
        "scope_ref": "claims.dateofloss",
        "hint_kind": "filter_default",
        "severity": "info",
        "hint_text_zh": "claims.dateofloss 是 DATE 类型, 用 DATE 'YYYY-MM-DD' 字面量比较, 例: dateofloss >= DATE '2010-01-01'. 提取年份用 EXTRACT(YEAR FROM dateofloss)::TEXT 而非 STRFTIME（DuckDB-only）.",
        "hint_text_en": "claims.dateofloss is DATE type. Compare with DATE 'YYYY-MM-DD' literal: dateofloss >= DATE '2010-01-01'. Extract year via EXTRACT(YEAR FROM dateofloss)::TEXT (NOT STRFTIME, that's DuckDB-only).",
        "trigger_keywords": ["after", "before", "between", "year", "date of loss", "since"],
    },

    # === LEFT(geoid, 5) idiom ===
    {
        "scope_type": "dataset",
        "scope_ref": "floodsql_bench_leftgeoid",
        "hint_kind": "join_note",
        "severity": "info",
        "hint_text_zh": "claims/svi/nri/cre.geoid 是 11 位 tract 级；county/hospitals.countyfips 是 5 位县级。跨 grain 关联用 LEFT(claims.geoid, 5) = county.geoid 或 LEFT(svi.geoid, 5) = hospitals.countyfips。",
        "hint_text_en": "claims/svi/nri/cre.geoid is 11-digit tract level; county.geoid and hospitals.countyfips are 5-digit county level. Bridge via LEFT(claims.geoid, 5) = county.geoid or LEFT(svi.geoid, 5) = hospitals.countyfips.",
        "trigger_keywords": ["county", "Harris County", "tract", "join", "claims and county", "svi and county"],
    },

    # === ST_Distance is for reporting only, not for ranking ===
    {
        "scope_type": "dataset",
        "scope_ref": "floodsql_bench_knn",
        "hint_kind": "category_choice",
        "severity": "info",
        "hint_text_zh": "KNN 排序用 PostGIS 索引算子: ORDER BY a.geometry <-> b.geometry LIMIT K（用 GIST 索引）。ST_Distance 只用于在 SELECT 报告距离值，不用于 ORDER BY（会丢索引）。",
        "hint_text_en": "KNN nearest-neighbour ranking: ORDER BY a.geometry <-> b.geometry LIMIT K (uses GIST index). Use ST_Distance ONLY in SELECT to report distance, NEVER in ORDER BY (disables index).",
        "trigger_keywords": ["nearest", "closest", "K nearest", "within X meters"],
    },

    # === Zero-payout filter convention ===
    {
        "scope_type": "table",
        "scope_ref": "claims",
        "hint_kind": "filter_default",
        "severity": "info",
        "hint_text_zh": "'zero payout / no payout' 类问题: 因金额是 TEXT, 用 CAST(amountpaid... AS DOUBLE PRECISION) = 0 过滤; 注意有些题题面是 'zero ICC' 即 IncreasedCostOfComplianceClaim = 0。负值（如 -201,667）表示退款, 不是缺失。",
        "hint_text_en": "'zero payout' / 'no payout' filter: with amounts as TEXT, use CAST(amountpaid... AS DOUBLE PRECISION) = 0. Negative values (e.g. -201,667) represent refunds, not missing data.",
        "trigger_keywords": ["zero payout", "no payout", "zero amount", "ICC = 0"],
    },

    # === COUNT(*) vs COUNT(DISTINCT) (R8 reinforcement) ===
    {
        "scope_type": "dataset",
        "scope_ref": "floodsql_bench_count_distinct",
        "hint_kind": "category_choice",
        "severity": "info",
        "hint_text_zh": "单表 COUNT 用 COUNT(*); 跨表 join 后维度列计数加 DISTINCT 防膨胀（如 COUNT(DISTINCT a.geoid) when census_tracts a JOIN floodplain b）；只有题面明说 '不同的 / 几种 / distinct' 才用 COUNT(DISTINCT some_attr)。",
        "hint_text_en": "Single-table count: use COUNT(*). After JOIN, count via COUNT(DISTINCT parent.<id>) to avoid row inflation. Use COUNT(DISTINCT col) ONLY when question says 'how many distinct / different / unique'.",
        "trigger_keywords": ["how many", "count", "distinct", "unique", "different"],
    },

    # === Polygon area in m² ===
    {
        "scope_type": "dataset",
        "scope_ref": "floodsql_bench_st_area",
        "hint_kind": "unit_note",
        "severity": "info",
        "hint_text_zh": "polygon 几何在 SRID 4326 时, ST_Area(geometry) 返回平方度, 不是平方米! 求真实面积要用 ST_Area(geometry::geography) → m². floodplain/census_tracts/zcta/county 都是 SRID 4326, area 都要 ::geography。",
        "hint_text_en": "Polygon geoms are SRID 4326; bare ST_Area(geometry) returns square DEGREES, not m². For real area in m² use ST_Area(geometry::geography). Applies to floodplain/census_tracts/zcta/county.",
        "trigger_keywords": ["area", "square meters", "square feet", "square km", "total area"],
    },
]


# ---------------------------------------------------------------------------
# value_semantics: enum/sentinel/unit annotations on registered columns
# ---------------------------------------------------------------------------
_VALUE_SEMANTICS: list[tuple[str, str, dict]] = [
    # claims TEXT amounts
    ("claims", "amountpaidonbuildingclaim", {
        "unit_caveat": "USD stored as TEXT; CAST(col AS DOUBLE PRECISION) before SUM/AVG/MAX",
        "value_range": "-201,667.50 .. 10,741,476.93 (negative = refund)",
    }),
    ("claims", "amountpaidoncontentsclaim", {
        "unit_caveat": "USD stored as TEXT; CAST(col AS DOUBLE PRECISION) before SUM/AVG/MAX",
        "value_range": "-80,000 .. 500,000",
    }),
    ("claims", "amountpaidonincreasedcostofcomplianceclaim", {
        "unit_caveat": "USD stored as TEXT; CAST(col AS DOUBLE PRECISION) before SUM/AVG/MAX",
        "value_range": "-6,450 .. 426,321",
    }),

    # SVI -999 sentinels
    ("svi", "rpl_theme1", {
        "sentinels": [{"value": -999, "meaning": "missing"}],
        "value_range": "0..1 (1 = most vulnerable; -999 = missing)",
    }),
    ("svi", "rpl_theme2", {
        "sentinels": [{"value": -999, "meaning": "missing"}],
        "value_range": "0..1 (1 = most vulnerable; -999 = missing)",
    }),
    ("svi", "rpl_theme3", {
        "sentinels": [{"value": -999, "meaning": "missing"}],
        "value_range": "0..1",
    }),
    ("svi", "rpl_theme4", {
        "sentinels": [{"value": -999, "meaning": "missing"}],
        "value_range": "0..1",
    }),
    ("svi", "rpl_themes", {
        "sentinels": [{"value": -999, "meaning": "missing"}],
        "value_range": "0..1 (overall vulnerability)",
    }),

    # NRI categorical risk ratings
    ("nri", "cfld_riskr", {
        "enum": [
            {"value": "Very Low", "meaning": "lowest coastal flood risk"},
            {"value": "Relatively Low", "meaning": "below-average coastal flood risk"},
            {"value": "Relatively Moderate", "meaning": "average coastal flood risk"},
            {"value": "Relatively High", "meaning": "above-average coastal flood risk"},
            {"value": "Very High", "meaning": "highest coastal flood risk"},
            {"value": "No Rating", "meaning": "rating unavailable"},
            {"value": "Insufficient Data", "meaning": "missing data"},
        ],
    }),
    ("nri", "rfld_riskr", {
        "enum": [
            {"value": "Very Low", "meaning": "lowest riverine flood risk"},
            {"value": "Relatively Low", "meaning": "below-average riverine flood risk"},
            {"value": "Relatively Moderate", "meaning": "average riverine flood risk"},
            {"value": "Relatively High", "meaning": "above-average riverine flood risk"},
            {"value": "Very High", "meaning": "highest riverine flood risk"},
            {"value": "No Rating", "meaning": "rating unavailable"},
            {"value": "Insufficient Data", "meaning": "missing data"},
        ],
    }),

    # floodplain fld_zone
    ("floodplain", "fld_zone", {
        "enum": [
            {"value": "A",  "meaning": "1% annual chance flood (100-year), no BFE shown"},
            {"value": "AE", "meaning": "1% annual chance flood, with BFE"},
            {"value": "AH", "meaning": "shallow flooding, sheet flow"},
            {"value": "AO", "meaning": "shallow flooding, sloping terrain"},
            {"value": "V",  "meaning": "coastal high-risk, no BFE"},
            {"value": "VE", "meaning": "coastal high-risk, with BFE"},
            {"value": "X",  "meaning": "minimal flood hazard"},
            {"value": "D",  "meaning": "undetermined"},
            {"value": "OPEN_WATER", "meaning": "open water body"},
        ],
    }),

    # hospitals.type
    ("hospitals", "type", {
        "enum": [
            {"value": "GENERAL ACUTE CARE",   "meaning": "general acute-care hospital"},
            {"value": "CRITICAL ACCESS",      "meaning": "rural critical-access hospital"},
            {"value": "PSYCHIATRIC",          "meaning": "psychiatric hospital"},
            {"value": "REHABILITATION",       "meaning": "rehabilitation hospital"},
            {"value": "LONG TERM CARE",       "meaning": "long-term care facility"},
            {"value": "MILITARY",             "meaning": "military hospital"},
            {"value": "CHILDREN",             "meaning": "children's hospital"},
            {"value": "WOMEN",                "meaning": "women's hospital"},
            {"value": "SPECIAL",              "meaning": "specialty hospital"},
            {"value": "CHRONIC DISEASE",      "meaning": "chronic disease hospital"},
        ],
    }),
    # schools.type
    ("schools", "type", {
        "enum": [
            {"value": "COLLEGE",         "meaning": "college / university"},
            {"value": "PUBLIC_SCHOOL",   "meaning": "public K-12 school"},
            {"value": "PRIVATE_SCHOOL",  "meaning": "private K-12 school"},
        ],
    }),

    # state semantic in svi (full-name vs abbreviation)
    ("svi", "state", {
        "enum": [
            {"value": "Florida",   "meaning": "FL (use full name in svi.state, NOT abbreviation)"},
            {"value": "Louisiana", "meaning": "LA"},
            {"value": "Texas",     "meaning": "TX"},
        ],
    }),
    ("svi", "st_abbr", {
        "enum": [
            {"value": "FL", "meaning": "Florida"},
            {"value": "LA", "meaning": "Louisiana"},
            {"value": "TX", "meaning": "Texas"},
        ],
    }),
    ("hospitals", "state", {
        "enum": [
            {"value": "FL", "meaning": "Florida"},
            {"value": "LA", "meaning": "Louisiana"},
            {"value": "TX", "meaning": "Texas"},
        ],
    }),
    ("schools", "state", {
        "enum": [
            {"value": "FL", "meaning": "Florida"},
            {"value": "LA", "meaning": "Louisiana"},
            {"value": "TX", "meaning": "Texas"},
        ],
    }),
    ("nri", "state", {
        "enum": [
            {"value": "FL", "meaning": "Florida"},
            {"value": "LA", "meaning": "Louisiana"},
            {"value": "TX", "meaning": "Texas"},
        ],
    }),

    # statefp (string)
    ("census_tracts", "statefp", {
        "enum": [
            {"value": "12", "meaning": "Florida"},
            {"value": "22", "meaning": "Louisiana"},
            {"value": "48", "meaning": "Texas"},
        ],
    }),
    ("county", "statefp", {
        "enum": [
            {"value": "12", "meaning": "Florida"},
            {"value": "22", "meaning": "Louisiana"},
            {"value": "48", "meaning": "Texas"},
        ],
    }),
    ("claims", "statefp", {
        "enum": [
            {"value": "12", "meaning": "Florida"},
            {"value": "22", "meaning": "Louisiana"},
            {"value": "48", "meaning": "Texas"},
        ],
    }),
]


# ---------------------------------------------------------------------------
# Synonym augmentation — colloquial / paraphrased table aliases
# ---------------------------------------------------------------------------
_EXTRA_SYNONYMS: list[tuple[str, list[str]]] = [
    ("census_tracts", ["census tract", "tract polygons", "census areas", "tract-level boundary"]),
    ("county",        ["U.S. county", "counties polygon", "county boundary", "administrative county"]),
    ("floodplain",    ["FEMA floodplain", "FEMA flood hazard zone", "NFHL", "flood polygon", "100-year flood zone", "flood hazard area"]),
    ("zcta",          ["ZIP code tabulation area", "ZIP polygon", "ZCTA polygon", "postal area boundary"]),
    ("claims",        ["NFIP claims", "flood insurance claims", "flood claim records", "insurance payouts", "policy claims", "flood damage records"]),
    ("hospitals",     ["healthcare facility", "medical facility", "hospitals dataset", "HIFLD hospitals"]),
    ("schools",       ["educational facility", "schools dataset", "HIFLD schools", "K-12 schools and colleges"]),
    ("svi",           ["Social Vulnerability Index", "CDC SVI", "vulnerability dataset", "ATSDR vulnerability"]),
    ("nri",           ["FEMA NRI", "National Risk Index", "natural hazard risk", "expected annual loss", "risk score"]),
    ("cre",           ["Community Resilience Estimates", "Census CRE", "resilience score", "household risk factors"]),
]


def seed_semantic_hints_floodsql(owner: str = "floodsql_bench") -> dict:
    """Idempotent upsert of FloodSQL business rules into the semantic-layer DB."""
    from sqlalchemy import text
    from data_agent.db_engine import get_engine
    from data_agent.semantic_layer import invalidate_semantic_cache

    engine = get_engine()
    if not engine:
        return {"status": "no_db", "hints": 0, "value_semantics": 0}

    hints_written = 0
    vs_written = 0
    vs_skipped: list[str] = []
    syn_augmented = 0

    with engine.begin() as conn:
        # 1. agent_semantic_hints
        for h in _HINTS:
            conn.execute(text("""
                INSERT INTO agent_semantic_hints
                    (scope_type, scope_ref, hint_kind,
                     hint_text_zh, hint_text_en, severity,
                     trigger_keywords, sample_sql, source_tag, owner_username)
                VALUES
                    (:scope_type, :scope_ref, :hint_kind,
                     :hint_text_zh, :hint_text_en, :severity,
                     CAST(:trigger_keywords AS jsonb), :sample_sql,
                     'floodsql_bench_seed', :owner)
                ON CONFLICT (scope_ref, hint_kind, hint_text_zh)
                DO UPDATE SET
                    hint_text_en     = EXCLUDED.hint_text_en,
                    severity         = EXCLUDED.severity,
                    trigger_keywords = EXCLUDED.trigger_keywords,
                    sample_sql       = EXCLUDED.sample_sql,
                    updated_at       = NOW()
            """), {
                "scope_type": h["scope_type"],
                "scope_ref": h["scope_ref"],
                "hint_kind": h["hint_kind"],
                "hint_text_zh": h["hint_text_zh"],
                "hint_text_en": h.get("hint_text_en"),
                "severity": h.get("severity", "info"),
                "trigger_keywords": json.dumps(h.get("trigger_keywords", [])),
                "sample_sql": h.get("sample_sql"),
                "owner": owner,
            })
            hints_written += 1

        # 2. agent_semantic_registry.value_semantics — only update existing rows
        for table_name, column_name, vs_dict in _VALUE_SEMANTICS:
            row = conn.execute(text("""
                SELECT 1 FROM agent_semantic_registry
                WHERE table_name = :t AND column_name = :c
                LIMIT 1
            """), {"t": table_name, "c": column_name}).fetchone()
            if not row:
                vs_skipped.append(f"{table_name}.{column_name}")
                continue
            conn.execute(text("""
                UPDATE agent_semantic_registry
                SET value_semantics = CAST(:vs AS jsonb),
                    updated_at = NOW()
                WHERE table_name = :t AND column_name = :c
            """), {
                "vs": json.dumps(vs_dict, ensure_ascii=False),
                "t": table_name,
                "c": column_name,
            })
            vs_written += 1

        # 3. agent_semantic_sources.synonyms augmentation
        for table_name, extra_syns in _EXTRA_SYNONYMS:
            row = conn.execute(text("""
                SELECT COALESCE(synonyms, '[]'::jsonb) FROM agent_semantic_sources
                WHERE table_name = :t
            """), {"t": table_name}).fetchone()
            if row is None:
                continue
            current = row[0] if isinstance(row[0], list) else json.loads(row[0] or "[]")
            merged = list(dict.fromkeys(list(current) + extra_syns))
            if merged == list(current):
                continue
            conn.execute(text("""
                UPDATE agent_semantic_sources
                SET synonyms = CAST(:syns AS jsonb), updated_at = NOW()
                WHERE table_name = :t
            """), {"syns": json.dumps(merged, ensure_ascii=False), "t": table_name})
            syn_augmented += 1

    invalidate_semantic_cache(None)

    return {
        "status": "ok",
        "hints": hints_written,
        "value_semantics": vs_written,
        "value_semantics_skipped": vs_skipped,
        "synonyms_augmented": syn_augmented,
    }


if __name__ == "__main__":
    result = seed_semantic_hints_floodsql()
    print(json.dumps(result, ensure_ascii=False, indent=2))
