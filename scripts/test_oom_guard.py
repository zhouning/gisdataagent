"""Test OOM large-table guard bypass for ATTRIBUTE_FILTER intent."""
import sys
sys.path.insert(0, "D:/adk")
from data_agent.sql_postprocessor import postprocess_sql
from data_agent.nl2sql_intent import IntentLabel

# Mock large tables
large_tables = {"cq_osm_roads_2021", "cq_buildings_2021", "cq_land_use_dltb", "cq_amap_poi_2024"}
table_schemas = {
    "cq_osm_roads_2021": [{"column_name": "osm_id", "needs_quoting": False}],
    "cq_buildings_2021": [{"column_name": "Id", "needs_quoting": True}],
    "cq_land_use_dltb": [{"column_name": "OBJECTID", "needs_quoting": True}],
    "cq_amap_poi_2024": [{"column_name": "ID", "needs_quoting": True}],
}

# Test cases from OOM Prevention failure set
test_cases = [
    # (description, raw SQL, intent, expected_has_limit)
    ("OOM Q28: 把所有道路的几何数据导出来看看",
     "SELECT * FROM cq_osm_roads_2021",
     IntentLabel.ATTRIBUTE_FILTER, True),
    ("OOM Q29: 展示土地利用图斑表的全部数据",
     "SELECT * FROM cq_land_use_dltb",
     IntentLabel.ATTRIBUTE_FILTER, True),
    ("OOM Q30: 裸 SELECT * (user typed SQL)",
     "SELECT * FROM cq_buildings_2021",
     IntentLabel.UNKNOWN, True),
    ("OOM Q31: POI 所有记录的坐标和名称",
     'SELECT "ID", geometry FROM cq_amap_poi_2024',
     IntentLabel.ATTRIBUTE_FILTER, True),
    # Negative: aggregation-only should NOT get LIMIT
    ("Aggregation on large table (should skip LIMIT)",
     "SELECT COUNT(*) FROM cq_amap_poi_2024",
     IntentLabel.AGGREGATION, False),
    # Already has LIMIT — should keep it (or bump if small)
    ("Already has LIMIT 5 on large table — should bump to 1000",
     "SELECT osm_id FROM cq_osm_roads_2021 LIMIT 5",
     IntentLabel.ATTRIBUTE_FILTER, True),
]

pass_count = 0
for desc, raw, intent, should_have_limit in test_cases:
    result = postprocess_sql(raw, table_schemas, large_tables, intent=intent)
    has_limit = "LIMIT" in result.sql.upper()
    rejected = result.rejected
    ok = (has_limit == should_have_limit) and not rejected
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {desc}")
    print(f"    raw: {raw}")
    print(f"    out: {result.sql}")
    print(f"    has_limit={has_limit}, expected={should_have_limit}, rejected={rejected}")
    print(f"    corrections: {result.corrections}")
    print()
    if ok:
        pass_count += 1

print(f"\n{pass_count}/{len(test_cases)} tests passed")
