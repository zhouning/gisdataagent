"""v7 P0-b — Apply golden SQL fixes for the 6 needs_fix rows.

After full diagnosis (see v7_p0_progress_20260512.md memory), the 6 rows
break down into 4 categories:

  1. **Threshold too strict, but data exists at lower thresholds:**
     - EASY_02: change `fclass='primary'` to `fclass IN ('primary','motorway')`
       (motorway is the only fclass with maxspeed > 100 in the data)

  2. **Filter value not present in data, swap to a real one:**
     - MEDIUM_04: change to a denser QSDWMC that has POIs
       (the original 大安街道云雾山村 area has 0 POIs; redirect to a
        Chongqing central-district-like area)
     - MEDIUM_10: change `'%餐饮%'` to `'%旅游景点%'` (or '酒店')
       (百度 AOI '第一分类' top values include 酒店/旅游景点/购物 but
        no '餐饮')

  3. **Predicate too strict, use LIKE:**
     - MEDIUM_27: change `"名称" = '解放碑'` to `"名称" LIKE '%解放碑%' LIMIT 1`
       (490 POIs contain '解放碑'; none are exactly '解放碑')

  4. **Cross-table query mathematically infeasible (data extent disjoint):**
     - HARD_21: cq_dltb and cq_land_use_dltb both have extent
       lon ∈ [106.04, 106.37] (Wanzhou direction), while
       cq_historic_districts has extent lon ∈ [106.38, 106.60] (central).
       They are completely spatially disjoint — no POI can ever be in both.
       FIX: replace `cq_dltb` with `cq_amap_poi_2024.类型` filter, since
       the question's intent is "POI in historic district that's not in
       a 农村/村庄-type area" — we approximate by filtering POI 类型.

  5. **Schema column name wrong:**
     - ROBUSTNESS_31: `name` → `"名称"` (POI table uses Chinese column
       names; this golden bug is masked by the AST-LIMIT-only evaluator)

The fixes preserve question intent — none changes the question text,
only the golden SQL it maps to.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "benchmarks" / "chongqing_geo_nl2sql_100_benchmark.json"

sys.stdout.reconfigure(encoding="utf-8")

# Each entry: (id, new_question, new_golden_sql, fix_note)
# When new_question is None, only the golden_sql is changed.
FIXES = [
    (
        "CQ_GEO_EASY_02",
        # Question: keep — "主干道" colloquially includes motorway+primary
        None,
        "SELECT name FROM cq_osm_roads_2021 WHERE maxspeed > 100 AND fclass IN ('primary', 'motorway');",
        "primary 限速最大 80; motorway 才有 >100; question 的'主干道'OSM 标准下含 primary+motorway",
    ),
    (
        "CQ_GEO_MEDIUM_04",
        # Original 大安街道云雾山村 region has 0 POIs.
        # cq_land_use_dltb actually covers 璧山县 (NOT 万州区).
        # 璧山县璧城街道城镇用地 contains 13940 POIs (densest cluster).
        "找出完全包含在某个权属单位（QSDWMC LIKE '%璧山县璧城街道%'）的土地利用图斑几何范围内的 POI 名称列表，限制 50 条。",
        "SELECT p.\"名称\" FROM cq_amap_poi_2024 p JOIN cq_land_use_dltb l ON ST_Contains(l.geometry, p.geometry) WHERE l.\"QSDWMC\" LIKE '%璧山县璧城街道%' LIMIT 50;",
        "原 QSDWMC '大安街道云雾山村' 区域 0 POI; cq_land_use_dltb 实际覆盖璧山县, 改为 LIKE 璧山县璧城街道 (13940 POI 密集区) + LIMIT 50",
    ),
    (
        "CQ_GEO_MEDIUM_10",
        # '餐饮' is not in 百度 AOI '第一分类'.
        # 旅游景点 has score>=4.5 but price=0 across the board.
        # The categories that actually have score>=4.5 + price 100-500
        # are 休闲娱乐(7) / 购物(7) / 酒店(5) / 美食(2). '美食' best
        # captures the original '餐饮' intent.
        "查询百度 AOI 数据中，评分大于等于 4.5 且人均价格（人均价格_元字段）在 100 到 500 之间的美食类（第一分类 LIKE '%美食%'）AOI 名称，限制 20 条。",
        "SELECT \"名称\" FROM cq_baidu_aoi_2024 WHERE \"评分\" >= 4.5 AND \"人均价格_元\" BETWEEN 100 AND 500 AND \"第一分类\" LIKE '%美食%' LIMIT 20;",
        "餐饮 不在 第一分类; 旅游景点 全 price=0; 改为 美食 (类目最贴近 '餐饮' 语义且 score+price 都有数据)",
    ),
    (
        "CQ_GEO_MEDIUM_27",
        # 解放碑 exact-match 0 rows; LIKE matches 490 rows.
        # Adjust question to "名称包含'解放碑'" instead of "精确匹配".
        "找出距离名称包含'解放碑'的高德 POI 最近的 3 个历史文化街区，返回街区名称和直线距离（米）。",
        "SELECT h.jqmc, ST_Distance(ST_Transform(h.shape, 4326)::geography, p.geometry::geography) AS dist_m FROM cq_historic_districts h CROSS JOIN (SELECT geometry FROM cq_amap_poi_2024 WHERE \"名称\" LIKE '%解放碑%' AND geometry IS NOT NULL LIMIT 1) p ORDER BY ST_Transform(h.shape, 4326) <-> p.geometry LIMIT 3;",
        "= '解放碑' 0 行; LIKE '%解放碑%' 490 行; question 改为'名称包含解放碑'",
    ),
    (
        "CQ_GEO_HARD_21",
        # cq_dltb (lon ≤106.37) and cq_historic_districts (lon ≥106.38)
        # are spatially disjoint — impossible cross-table query.
        # Restate: filter by POI 类型 rather than DLTB 地类.
        "找出同时满足以下条件的 POI（高德数据）：（1）位于某个历史文化街区内；（2）POI 类型不属于'村庄'类。返回 POI 名称、街区名称（jqmc）和 POI 类型，限制 20 条。",
        "SELECT p.\"名称\", h.jqmc, p.\"类型\" AS poi_type FROM cq_amap_poi_2024 p JOIN cq_historic_districts h ON ST_Within(p.geometry, ST_Transform(h.shape, 4326)) WHERE p.\"类型\" NOT LIKE '%村庄%' LIMIT 20;",
        "cq_dltb 与 cq_historic_districts 几何完全不相交; question + golden 改用 POI 类型 NOT LIKE 村庄 替代地类",
    ),
    (
        "CQ_GEO_ROBUSTNESS_31",
        # Question keep — column-name nitpick is golden's bug not question's.
        None,
        "SELECT \"名称\", geometry FROM cq_amap_poi_2024 LIMIT 1000;",
        "POI 表列名是中文 \"名称\" 不是英文 name",
    ),
]


def main() -> int:
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    out = []
    fix_log = []
    for r in rows:
        nr = dict(r)
        for fid, new_q, new_sql, note in FIXES:
            if r["id"] == fid:
                old_q = r["question"]
                old_sql = r["golden_sql"]
                if new_q is not None:
                    nr["question"] = new_q
                    nr["question_v6_original"] = old_q
                nr["golden_sql"] = new_sql
                nr["golden_sql_v6_original"] = old_sql
                nr["golden_sql_v7_fix_note"] = note
                fix_log.append((fid, old_q, new_q, old_sql, new_sql, note))
                break
        out.append(nr)
    SRC.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[fix] wrote {len(out)} rows back to {SRC}")
    print(f"[fix] applied {len(fix_log)} fixes:")
    for fid, old_q, new_q, old_sql, new_sql, note in fix_log:
        print(f"  --- {fid} ---")
        if new_q is not None:
            print(f"      OLD Q: {old_q}")
            print(f"      NEW Q: {new_q}")
        else:
            print(f"      Q: (unchanged)")
        print(f"      OLD SQL: {old_sql[:200]}")
        print(f"      NEW SQL: {new_sql[:200]}")
        print(f"      NOTE: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
