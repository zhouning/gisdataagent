"""v7 P0-b deeper probe — diagnose the 5 empty_result rows.

For each empty_result golden SQL, run progressively relaxed variants to
distinguish "data really is empty" (legitimate) from "golden SQL has a
filter typo / unit error / wrong table" (real bug).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(str(ROOT / "data_agent" / ".env"), override=True)
sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import text
from data_agent.db_engine import get_engine

ENGINE = get_engine()


def run(sql: str, label: str) -> None:
    with ENGINE.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        conn.execute(text("SET LOCAL statement_timeout = 20000"))
        try:
            res = conn.execute(text(sql))
            rows = res.fetchall()
            print(f"  [{label:<55}] rows={len(rows)}", end="")
            if rows and len(rows) <= 5:
                for r in rows:
                    s = str(tuple(str(c)[:60] for c in r))[:200]
                    print(f"\n     {s}", end="")
            print()
        except Exception as e:
            print(f"  [{label:<55}] ERR {str(e)[:120]}")


print("=" * 80)
print("EASY_02 — maxspeed > 100 AND fclass='primary'")
print("=" * 80)
run("SELECT COUNT(*) FROM cq_osm_roads_2021", "total rows")
run("SELECT COUNT(*) FROM cq_osm_roads_2021 WHERE fclass='primary'", "fclass='primary' alone")
run("SELECT COUNT(*) FROM cq_osm_roads_2021 WHERE maxspeed IS NOT NULL", "maxspeed not null")
run("SELECT MIN(maxspeed), MAX(maxspeed), COUNT(*) FROM cq_osm_roads_2021 WHERE maxspeed > 0", "maxspeed range")
run("SELECT fclass, MIN(maxspeed), MAX(maxspeed), COUNT(*) FROM cq_osm_roads_2021 WHERE maxspeed > 0 GROUP BY fclass ORDER BY 4 DESC LIMIT 5", "by fclass top5")
run("SELECT COUNT(*) FROM cq_osm_roads_2021 WHERE maxspeed > 100 AND fclass='motorway'", "motorway > 100")
run("SELECT COUNT(*) FROM cq_osm_roads_2021 WHERE maxspeed >= 80 AND fclass='primary'", "primary >= 80")

print()
print("=" * 80)
print("MEDIUM_04 — QSDWMC LIKE '%大安街道映秀山村%'")
print("=" * 80)
run("SELECT COUNT(*) FROM cq_land_use_dltb", "total dltb rows")
run("SELECT COUNT(*) FROM cq_land_use_dltb WHERE \"QSDWMC\" LIKE '%大安%'", "LIKE '%大安%'")
run("SELECT COUNT(*) FROM cq_land_use_dltb WHERE \"QSDWMC\" LIKE '%映秀%'", "LIKE '%映秀%'")
run("SELECT COUNT(*) FROM cq_land_use_dltb WHERE \"QSDWMC\" LIKE '%山村%'", "LIKE '%山村%'")
run("SELECT \"QSDWMC\", COUNT(*) FROM cq_land_use_dltb GROUP BY 1 ORDER BY 2 DESC LIMIT 8", "top QSDWMC values")

print()
print("=" * 80)
print("MEDIUM_10 — 百度 AOI 评分>=4.5 价格 100-500 第一分类 LIKE '%餐饮%'")
print("=" * 80)
run("SELECT COUNT(*) FROM cq_baidu_aoi_2024", "total aoi rows")
run("SELECT \"第一分类\", COUNT(*) FROM cq_baidu_aoi_2024 GROUP BY 1 ORDER BY 2 DESC LIMIT 10", "top 第一分类")
run("SELECT COUNT(*) FROM cq_baidu_aoi_2024 WHERE \"评分\" >= 4.5", "评分>=4.5")
run("SELECT MIN(\"评分\"), MAX(\"评分\"), COUNT(\"评分\") FROM cq_baidu_aoi_2024", "评分 range")
run("SELECT MIN(\"人均价格_元\"), MAX(\"人均价格_元\"), COUNT(\"人均价格_元\") FROM cq_baidu_aoi_2024", "人均价格 range")
run("SELECT COUNT(*) FROM cq_baidu_aoi_2024 WHERE \"评分\" >= 4.5 AND \"人均价格_元\" BETWEEN 100 AND 500", "score+price")

print()
print("=" * 80)
print("MEDIUM_27 — POI '南滨路' KNN")
print("=" * 80)
run("SELECT COUNT(*) FROM cq_amap_poi_2024 WHERE \"名称\" = '南滨路'", "exact = '南滨路'")
run("SELECT COUNT(*) FROM cq_amap_poi_2024 WHERE \"名称\" LIKE '%南滨路%'", "LIKE '%南滨路%'")
run("SELECT \"名称\" FROM cq_amap_poi_2024 WHERE \"名称\" LIKE '%南滨路%' LIMIT 5", "samples LIKE")

print()
print("=" * 80)
print("HARD_21 — POI ∩ 历史街区 ∩ 非农庄地类")
print("=" * 80)
run("SELECT COUNT(*) FROM cq_historic_districts", "total historic")
run("SELECT COUNT(*) FROM cq_amap_poi_2024", "total POI")
run("SELECT COUNT(*) FROM cq_dltb", "total dltb")
run("SELECT COUNT(*) FROM cq_amap_poi_2024 p JOIN cq_historic_districts h ON ST_Within(p.geometry, ST_Transform(h.shape, 4326))", "POI in historic (joined)")
run("SELECT COUNT(*) FROM cq_dltb WHERE dlmc != '农庄'", "dltb non-农庄")

print()
print("=" * 80)
print("ROBUSTNESS_31 — column 'name' missing")
print("=" * 80)
run("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='cq_amap_poi_2024' ORDER BY ordinal_position", "amap columns")
