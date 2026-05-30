"""Generate a stricter clean benchmark: v3 strips bare cq_* table names too.

v7 `chongqing_geo_nl2sql_125q_clean.json` already stripped paren spans but left
bare `cq_dltb` / `cq_land_use_dltb` / `cq_osm_roads_2021` etc. intact in the
question body. This produces the *stricter* variant that replaces them with
their Chinese business concepts, so the question cannot leak schema names at all.

Rules:
  - Replace each cq_* table name with its Chinese concept name
  - Preserve golden_sql / id / difficulty etc.
  - Tag `question_v2_preclean` with the v2 text for diff/debug

Output: benchmarks/chongqing_geo_nl2sql_125q_clean_v3.json
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "benchmarks" / "chongqing_geo_nl2sql_125q_clean.json"
DST = ROOT / "benchmarks" / "chongqing_geo_nl2sql_125q_clean_v3.json"

# Mapping: bare cq_* name → Chinese business concept
# Chosen to match natural phrasing seen elsewhere in the same benchmark.
TABLE_TO_CONCEPT = {
    "cq_land_use_dltb":           "土地利用现状",
    "cq_dltb":                    "地类图斑",
    "cq_osm_roads_2021":          "道路",
    "cq_amap_poi_2024":           "高德 POI",
    "cq_buildings_2021":          "建筑",
    "cq_historic_districts":      "历史街区",
    "cq_baidu_aoi_2024":          "百度 AOI",
    "cq_baidu_search_index_2023": "百度搜索指数",
    "cq_district_population":     "区县人口",
    "cq_unicom_commuting_2023":   "联通通勤数据",
}

# Longer first so cq_land_use_dltb matches before cq_dltb
SORTED_KEYS = sorted(TABLE_TO_CONCEPT.keys(), key=len, reverse=True)


def clean_v3(q: str) -> str:
    t = q
    for k in SORTED_KEYS:
        t = re.sub(rf"\b{re.escape(k)}\b", TABLE_TO_CONCEPT[k], t, flags=re.IGNORECASE)
    # Tidy up residue like " 表中" / " 中" that now follows a Chinese concept
    # (these are grammatical, leave them)
    t = re.sub(r"\s+", " ", t)
    # Smooth "在地类图斑 表中" → "在地类图斑表中" (space before 表)
    t = re.sub(r"(一-鿿)\s+([一-鿿])", r"\1\2", t)
    # Fix common english tails that look awkward
    t = t.strip()
    return t


def main() -> int:
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    out = []
    n_changed = 0
    n_residual = 0
    for r in rows:
        before = r["question"]
        after = clean_v3(before)
        if before != after:
            n_changed += 1
        # Residual check: no more cq_*
        if re.search(r"\bcq_[a-z0-9_]+\b", after, re.IGNORECASE):
            n_residual += 1
            print(f"[WARN] residual table name in {r['id']}: {after}")
        new_r = dict(r)
        new_r["question_v2_preclean"] = before
        new_r["question"] = after
        out.append(new_r)

    DST.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {DST}")
    print(f"  changed: {n_changed}/{len(rows)}")
    print(f"  residual table names: {n_residual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
