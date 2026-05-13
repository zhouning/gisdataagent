"""Seed Chongqing (CQ) dataset business rules into the semantic-layer DB.

v7 P0-pre: the 20 Category-A rules that were hard-coded in
`prompts_nl2sql/*/system_instruction.md` live here as structured data,
written to:
  - agent_semantic_hints           (generic carrier for free-text rules)
  - agent_semantic_registry.value_semantics  (per-column enums/sentinels/unit caveats)
  - agent_semantic_sources.synonyms (table-level fuzzy-match aliases)

New customers run their own equivalent of this script (or configure via
the app's semantic-layer UI) to teach the NL2SQL agent about their data
WITHOUT editing any prompt file.

Idempotent: re-running is safe; rows are upserted on
(scope_ref, hint_kind, hint_text_zh).
"""
from __future__ import annotations

import json
from typing import Optional


# ---------------------------------------------------------------------------
# Hints payload — one entry per CQ-specific business rule.
# ---------------------------------------------------------------------------

_HINTS: list[dict] = [
    # Rule 3: SHAPE_Area is degrees² — critical
    {
        "scope_type": "column",
        "scope_ref": "cq_land_use_dltb.SHAPE_Area",
        "hint_kind": "unit_note",
        "severity": "critical",
        "hint_text_zh": "SHAPE_Area 以平方度为单位（SRID 4326 未投影）, 严禁用于真实 m² 计算；用 TBMJ 或 ST_Area(geometry::geography)。",
        "hint_text_en": "SHAPE_Area is stored in square DEGREES (SRID 4326 unprojected), NEVER use it as m². Use TBMJ or ST_Area(geometry::geography) instead.",
        "trigger_keywords": [],  # critical → always emit
    },
    # Rule 4: SHAPE_Length is degrees — critical
    {
        "scope_type": "column",
        "scope_ref": "cq_land_use_dltb.SHAPE_Length",
        "hint_kind": "unit_note",
        "severity": "critical",
        "hint_text_zh": "SHAPE_Length 以度为单位, 严禁用于真实米计算; 用 ST_Length(geometry::geography) 返回米。",
        "hint_text_en": "SHAPE_Length is stored in DEGREES, NEVER use it as metres. Use ST_Length(geometry::geography).",
        "trigger_keywords": [],
    },
    # Rule 5: TBMJ real m² preference
    {
        "scope_type": "column",
        "scope_ref": "cq_land_use_dltb.TBMJ",
        "hint_kind": "unit_note",
        "severity": "info",
        "hint_text_zh": "TBMJ 是图斑真实面积, 单位 m² (已预计算)。",
        "hint_text_en": "TBMJ is pre-computed parcel area in real m².",
        "trigger_keywords": ["面积", "平方米", "m²", "平方千米", "公顷"],
    },
    # Rule 6: TBMJ vs ST_Area preference
    {
        "scope_type": "table",
        "scope_ref": "cq_land_use_dltb",
        "hint_kind": "category_choice",
        "severity": "info",
        "hint_text_zh": "单图斑面积过滤/求和优先用 TBMJ；聚合/几何操作 (如 ST_Union 后求面积) 用 ST_Area(geometry::geography)。",
        "hint_text_en": "Prefer TBMJ for per-parcel filtering/sum; use ST_Area(geometry::geography) for aggregated/geometry-operation areas.",
        "trigger_keywords": ["面积", "m²", "平方米", "平方千米", "公顷", "求和"],
    },
    # Rule 7: prefer cq_dltb when no year specified
    {
        "scope_type": "dataset",
        "scope_ref": "cq_dltb",
        "hint_kind": "category_choice",
        "severity": "info",
        "hint_text_zh": "问题无具体年份/版本时, 优先使用 cq_dltb (基础数据, 小写列名: bsm/dlbm/dlmc/tbmj/shape)。",
        "hint_text_en": "When question is year-agnostic, prefer cq_dltb (base data, lowercase columns).",
        "trigger_keywords": ["地类", "图斑", "耕地", "林地"],
    },
    # Rule 8: 类型 not 类别
    {
        "scope_type": "column",
        "scope_ref": "cq_amap_poi_2024.类型",
        "hint_kind": "category_choice",
        "severity": "warn",
        "hint_text_zh": "高德 POI 类型字段列名是 \"类型\" (NOT \"类别\")；医院/学校/餐厅类过滤用 \"类型\" LIKE '%医院%' 等。",
        "hint_text_en": "Gaode POI category column is \"类型\" (NOT \"类别\"); filter hospitals/schools/restaurants via \"类型\" LIKE '%医院%' etc.",
        "trigger_keywords": [],  # applies whenever this column appears
    },
    # Rule 9: hospital/school POI
    {
        "scope_type": "table",
        "scope_ref": "cq_amap_poi_2024",
        "hint_kind": "category_choice",
        "severity": "info",
        "hint_text_zh": "医院/学校/餐厅等 POI 分类过滤用 \"类型\" LIKE '%医院%'/'%学校%'/'%餐饮%'；避免精确等于。",
        "hint_text_en": "Filter hospital/school/restaurant POIs via \"类型\" LIKE '%医院%' etc. (fuzzy, not exact).",
        "trigger_keywords": ["医院", "学校", "三甲", "餐厅", "酒店", "POI"],
        "sample_sql": "SELECT \"名称\" FROM cq_amap_poi_2024 WHERE \"类型\" LIKE '%三甲%' OR \"类型\" LIKE '%医院%'",
    },
    # Rule 10: 第一分类 vs 类型
    {
        "scope_type": "table",
        "scope_ref": "cq_baidu_aoi_2024",
        "hint_kind": "category_choice",
        "severity": "warn",
        "hint_text_zh": "百度 AOI 顶层分类过滤用 \"第一分类\" (取值: 房地产/酒店/旅游景点/医疗/美食/购物/休闲娱乐)，不要用 \"类型\"。",
        "hint_text_en": "Baidu AOI top-level category filter uses \"第一分类\" (房地产/酒店/旅游景点/医疗/美食/购物/休闲娱乐), NOT \"类型\".",
        "trigger_keywords": [],
    },
    # Rule 11: cq_buildings_2021 has no Id pk
    {
        "scope_type": "table",
        "scope_ref": "cq_buildings_2021",
        "hint_kind": "quoting",
        "severity": "warn",
        "hint_text_zh": "cq_buildings_2021 没有主键式 \"Id\" 列，计数用 COUNT(*) 而非 COUNT(DISTINCT \"Id\")。",
        "hint_text_en": "cq_buildings_2021 has no primary-key-like \"Id\" column; use COUNT(*) not COUNT(DISTINCT \"Id\").",
        "trigger_keywords": ["建筑", "楼", "多少", "几栋", "COUNT"],
    },
    # Rule 13: maxspeed 0 means unset
    {
        "scope_type": "column",
        "scope_ref": "cq_osm_roads_2021.maxspeed",
        "hint_kind": "value_enum",
        "severity": "warn",
        "hint_text_zh": "OSM maxspeed=0 表示未设置 (NOT NULL)；\"设置了限速\"用 maxspeed > 0，不是 IS NOT NULL。",
        "hint_text_en": "OSM maxspeed=0 means UNSET (not NULL); 'has speed limit' → maxspeed > 0, NOT IS NOT NULL.",
        "trigger_keywords": ["限速", "maxspeed", "设置"],
    },
    # Rule 16: NULL filter discipline for DISTINCT list
    {
        "scope_type": "column",
        "scope_ref": "cq_osm_roads_2021.name",
        "hint_kind": "filter_default",
        "severity": "info",
        "hint_text_zh": "列出不重复道路名时加 name IS NOT NULL (避免 NULL 行污染 DISTINCT)；但若问题只是过滤 tunnel='T' 等, 保留 NULL 名字。",
        "hint_text_en": "For DISTINCT name listing add name IS NOT NULL; do NOT add it for plain filter queries like tunnel='T'.",
        "trigger_keywords": ["不重复", "去重", "distinct", "列出", "列出不同的"],
    },
    # Rule 19: cq_district_population 500000 exclusion
    {
        "scope_type": "column",
        "scope_ref": "cq_district_population.行政区划代码",
        "hint_kind": "exclusion",
        "severity": "warn",
        "hint_text_zh": "cq_district_population 含一行 \"行政区划代码\"=500000 (\"全市总计\"); 列出/统计区县类问题必须用 WHERE \"行政区划代码\" != 500000 排除全市汇总行 (不要用 \"区划名称\" 做排除，用代码字段更稳)。",
        "hint_text_en": "cq_district_population has a city-total row with 行政区划代码=500000; exclude via WHERE \"行政区划代码\" != 500000 for any per-district query (prefer code over name for exclusion).",
        "trigger_keywords": [
            "各区县", "每个区县", "分别", "每个区",
            "全市", "合计", "区县", "各区", "哪些区",
            "区县排", "区县的",
        ],
    },
    # Rule 17: cq_historic_districts SRID 4610
    {
        "scope_type": "table",
        "scope_ref": "cq_historic_districts",
        "hint_kind": "srid_note",
        "severity": "warn",
        "hint_text_zh": "cq_historic_districts.shape 存储于 SRID 4610 (与其他表 SRID 4326 不同); 做空间 join 前用 ST_Transform(shape, 4326)。",
        "hint_text_en": "cq_historic_districts.shape is stored in SRID 4610 (other tables in 4326); use ST_Transform(shape, 4326) before spatial join.",
        "trigger_keywords": ["历史街区", "历史文化", "历史保护"],
    },
]


# ---------------------------------------------------------------------------
# value_semantics payload — per-column enums / sentinels / unit caveats.
# ---------------------------------------------------------------------------

_VALUE_SEMANTICS: list[tuple[str, str, dict]] = [
    # (table_name, column_name, value_semantics_dict)
    ("cq_land_use_dltb", "SHAPE_Area", {
        "unit_caveat": "square DEGREES (SRID 4326 unprojected); NEVER use as m²",
    }),
    ("cq_land_use_dltb", "SHAPE_Length", {
        "unit_caveat": "DEGREES; NEVER use as metres",
    }),
    ("cq_land_use_dltb", "TBMJ", {
        "unit_caveat": "pre-computed parcel area in real m²",
    }),
    ("cq_baidu_aoi_2024", "第一分类", {
        "enum": [
            {"value": "房地产", "meaning": "real estate"},
            {"value": "酒店", "meaning": "hotel"},
            {"value": "旅游景点", "meaning": "tourist attraction"},
            {"value": "医疗", "meaning": "medical"},
            {"value": "美食", "meaning": "food / dining"},
            {"value": "购物", "meaning": "shopping"},
            {"value": "休闲娱乐", "meaning": "leisure / entertainment"},
        ],
    }),
    ("cq_osm_roads_2021", "fclass", {
        "enum": [
            {"value": "motorway", "meaning": "高速公路"},
            {"value": "trunk", "meaning": "快速路"},
            {"value": "primary", "meaning": "主干道"},
            {"value": "secondary", "meaning": "次干道"},
            {"value": "tertiary", "meaning": "支路"},
            {"value": "residential", "meaning": "居住区道路"},
            {"value": "footway", "meaning": "步行道"},
            {"value": "service", "meaning": "服务道路"},
        ],
    }),
    ("cq_osm_roads_2021", "maxspeed", {
        "sentinels": [{"value": 0, "meaning": "unset / not configured"}],
        "unit_caveat": "km/h when > 0",
    }),
    ("cq_osm_roads_2021", "oneway", {
        "enum": [
            {"value": "T", "meaning": "one-way forward"},
            {"value": "F", "meaning": "one-way reverse"},
            {"value": "B", "meaning": "bi-directional"},
        ],
    }),
    ("cq_osm_roads_2021", "bridge", {
        "enum": [{"value": "T", "meaning": "是桥梁"}, {"value": "F", "meaning": "非桥梁"}],
    }),
    ("cq_osm_roads_2021", "tunnel", {
        "enum": [{"value": "T", "meaning": "是隧道"}, {"value": "F", "meaning": "非隧道"}],
    }),
    ("cq_unicom_commuting_2023", "性别", {
        "enum": [{"value": 1, "meaning": "男"}, {"value": 2, "meaning": "女"}],
    }),
    ("cq_unicom_commuting_2023", "职住格网是否重合", {
        "enum": [
            {"value": 1, "meaning": "同网格 (本地通勤)"},
            {"value": 0, "meaning": "跨网格 (跨区县通勤)"},
        ],
    }),
]


# ---------------------------------------------------------------------------
# Synonyms augmentation — expand fuzzy-match aliases on agent_semantic_sources
# so common colloquial vocabulary ("楼", "道路", "银行", "户籍人口") routes to
# the right table instead of falling through to BIRD tables or no-match.
# ---------------------------------------------------------------------------

_EXTRA_SYNONYMS: list[tuple[str, list[str]]] = [
    ("cq_buildings_2021", ["楼", "栋楼", "高楼", "建筑", "建筑物", "楼房", "住房", "房屋"]),
    ("cq_amap_poi_2024", [
        "POI", "兴趣点", "门店", "医院", "三甲医院", "学校", "银行", "药店",
        "餐厅", "酒店", "加油站", "超市", "商场",
    ]),
    ("cq_baidu_aoi_2024", ["AOI", "兴趣区", "商圈", "景区", "旅游景点", "评分", "消费"]),
    ("cq_osm_roads_2021", [
        "道路", "路网", "公路", "街道", "单行路", "单行道",
        "主干道", "次干道", "快速路", "高速公路", "桥梁", "隧道",
    ]),
    ("cq_district_population", [
        "区县人口", "户籍人口", "常住人口", "城镇人口", "区县",
        "区县常住", "区县户籍",
    ]),
    ("cq_historic_districts", [
        "历史街区", "历史文化街区", "文物保护", "保护建筑",
    ]),
    ("cq_unicom_commuting_2023", ["通勤", "职住", "通勤数据", "上下班"]),
    ("cq_dltb", [
        "地类", "地类图斑", "图斑", "土地利用", "耕地", "林地", "草地",
        "水域", "建设用地", "农用地",
    ]),
    ("cq_land_use_dltb", [
        "土地利用现状", "地类图斑", "DLTB", "图斑面积", "用地图斑",
    ]),
]


def seed_semantic_hints_cq(owner: str = "audit") -> dict:
    """Idempotent upsert of CQ business rules into the semantic-layer DB.

    Returns a summary dict with counts.
    """
    from sqlalchemy import text
    from .db_engine import get_engine
    from .semantic_layer import invalidate_semantic_cache

    engine = get_engine()
    if not engine:
        return {"status": "no_db", "hints": 0, "value_semantics": 0}

    hints_written = 0
    vs_written = 0
    vs_skipped: list[str] = []
    srid_fixed = False
    syn_augmented = 0

    with engine.begin() as conn:
        # --- 1. Upsert agent_semantic_hints rows ---
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
                     'cq_migration_069', :owner)
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

        # --- 2. Patch agent_semantic_registry.value_semantics ---
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

        # --- 3. Conditional SRID patch for cq_historic_districts ---
        srid_row = conn.execute(text("""
            SELECT srid FROM agent_semantic_sources
            WHERE table_name = 'cq_historic_districts'
        """)).fetchone()
        if srid_row is not None and srid_row[0] != 4610:
            conn.execute(text("""
                UPDATE agent_semantic_sources
                SET srid = 4610, updated_at = NOW()
                WHERE table_name = 'cq_historic_districts'
            """))
            srid_fixed = True

        # --- 4. Augment agent_semantic_sources.synonyms (fuzzy-match aliases) ---
        for table_name, extra_syns in _EXTRA_SYNONYMS:
            row = conn.execute(text("""
                SELECT COALESCE(synonyms, '[]'::jsonb) FROM agent_semantic_sources
                WHERE table_name = :t
            """), {"t": table_name}).fetchone()
            if row is None:
                continue
            current = row[0] if isinstance(row[0], list) else json.loads(row[0] or "[]")
            merged = list(dict.fromkeys(list(current) + extra_syns))  # preserve order, dedup
            if merged == list(current):
                continue
            conn.execute(text("""
                UPDATE agent_semantic_sources
                SET synonyms = CAST(:syns AS jsonb), updated_at = NOW()
                WHERE table_name = :t
            """), {"syns": json.dumps(merged, ensure_ascii=False), "t": table_name})
            syn_augmented += 1

    # Flush caches so next resolve_semantic_context picks up changes
    invalidate_semantic_cache(None)

    return {
        "status": "ok",
        "hints": hints_written,
        "value_semantics": vs_written,
        "value_semantics_skipped": vs_skipped,
        "srid_fixed": srid_fixed,
        "synonyms_augmented": syn_augmented,
    }


if __name__ == "__main__":
    result = seed_semantic_hints_cq()
    print(json.dumps(result, ensure_ascii=False, indent=2))
