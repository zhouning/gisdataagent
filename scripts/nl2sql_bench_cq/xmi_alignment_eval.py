"""XMI ↔ 85q benchmark alignment evaluation.

Aligns the 10 cq_* tables used in 85q golden SQL with XMI class names
to estimate coverage potential of stance #2 (XMI as synonym dictionary
for NL2SQL grounding).
"""
import json
import re
import yaml
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"D:\adk")
BENCH = ROOT / "benchmarks" / "chongqing_geo_nl2sql_100_benchmark.json"
XMI_INDEX = ROOT / "data_agent" / "standards" / "compiled" / "indexes" / "xmi_global_index.yaml"

# Manual mapping: cq_ table -> source/domain rationale
TABLE_DOMAIN = {
    "cq_osm_roads_2021":         ("public_osm",      "OpenStreetMap 道路 — 公开众包数据，非自然资源标准"),
    "cq_amap_poi_2024":          ("public_amap",     "高德 POI — 公开商业数据"),
    "cq_buildings_2021":         ("public_unknown",  "建筑层高数据 — 来源未明，可能矢量化或公开"),
    "cq_land_use_dltb":          ("natural_res",     "土地利用现状（地类图斑 DLTB）— 自然资源标准核心"),
    "cq_dltb":                   ("natural_res",     "地类图斑别名表 — 自然资源标准核心"),
    "cq_historic_districts":     ("public_other",    "历史文化街区 — 文物/规划公开数据"),
    "cq_baidu_aoi_2024":         ("public_baidu",    "百度 AOI — 公开商业数据"),
    "cq_district_population":    ("public_stat",     "区县人口统计 — 统计局公开数据"),
    "cq_baidu_search_index_2023":("public_baidu",    "百度搜索指数 — 公开商业数据"),
    "cq_unicom_commuting_2023":  ("public_telco",    "联通通勤数据 — 公开运营商数据"),
}

def load_85q() -> list[dict]:
    rows = json.loads(BENCH.read_text(encoding="utf-8"))
    return [r for r in rows if str(r.get("difficulty","")).lower() in ("easy","medium","hard")]

def load_xmi_classes() -> dict[str, list[dict]]:
    """Returns: module_name -> [{class_name, ...}, ...]"""
    idx = yaml.safe_load(XMI_INDEX.read_text(encoding="utf-8"))
    by_module = defaultdict(list)
    for entry in idx.get("class_index", {}).values():
        if isinstance(entry, dict):
            by_module[entry.get("module_name","")].append({
                "class_name": entry.get("class_name",""),
                "module_name": entry.get("module_name",""),
            })
    return dict(by_module)

def main():
    qs = load_85q()
    xmi_by_module = load_xmi_classes()

    # Step 1: tag each q with its primary table
    table_to_qs = defaultdict(list)
    for q in qs:
        sql = q.get("golden_sql","") or ""
        tables = re.findall(r"\bcq_[a-zA-Z0-9_]+", sql, re.IGNORECASE)
        primary = tables[0].lower() if tables else "<none>"
        table_to_qs[primary].append(q)

    # Step 2: for natural_res tables, try keyword match against XMI class names
    natural_res_modules = ["06统一资源利用","02统一调查监测","04统一空间规划"]
    candidate_classes = []
    for m in natural_res_modules:
        candidate_classes.extend(xmi_by_module.get(m, []))

    # Look for "地类图斑" / "土地利用" / "耕地" / "DLTB" / "用地" etc.
    keywords_dltb = ["地类图斑","DLTB","土地利用","用地","耕地","林地","草地","建设用地"]
    matched = []
    for c in candidate_classes:
        cn = c["class_name"]
        for kw in keywords_dltb:
            if kw.lower() in cn.lower():
                matched.append((cn, c["module_name"], kw))
                break

    # Step 3: report
    print("="*80)
    print("85q 题目按主表分布 + 数据来源分类")
    print("="*80)
    rows = []
    for tbl, qlist in sorted(table_to_qs.items(), key=lambda x: -len(x[1])):
        domain, rationale = TABLE_DOMAIN.get(tbl, ("?","?"))
        rows.append((tbl, len(qlist), domain, rationale))
        print(f"  {tbl:35s} | n={len(qlist):3d} | {domain:14s} | {rationale}")

    print()
    print("="*80)
    print("数据来源汇总")
    print("="*80)
    src_counter = Counter()
    for tbl, n, dom, _ in rows:
        src_counter[dom] += n
    for dom, n in src_counter.most_common():
        pct = 100*n/sum(src_counter.values())
        print(f"  {dom:14s}: {n:3d} 题 ({pct:5.1f}%)")

    nat_q = src_counter.get("natural_res", 0)
    pub_q = sum(v for k,v in src_counter.items() if k.startswith("public"))
    print()
    print(f"  自然资源标准覆盖题: {nat_q} ({100*nat_q/85:.1f}%)")
    print(f"  公开/外部数据题:    {pub_q} ({100*pub_q/85:.1f}%)")

    print()
    print("="*80)
    print("XMI 候选类匹配结果（针对自然资源 cq_dltb / cq_land_use_dltb）")
    print("="*80)
    print(f"  扫描 3 个自然资源相关模块，共 {len(candidate_classes)} 个 XMI 类")
    print(f"  与 DLTB/用地/耕地等关键词匹配的类: {len(matched)}")
    for cn, mod, kw in matched[:20]:
        print(f"    [{kw}] {cn} (来自 {mod})")
    if len(matched) > 20:
        print(f"    ... 共 {len(matched)} 个，仅显示前 20")

    # Step 4: list questions hitting natural_res tables — show what synonyms could help
    print()
    print("="*80)
    print("自然资源相关 26 题题面（看 XMI 同义词能否补 grounding）")
    print("="*80)
    for tbl in ("cq_land_use_dltb","cq_dltb"):
        for q in table_to_qs.get(tbl, [])[:30]:
            qid = q.get("id","")
            qtext = q.get("question","")[:120]
            print(f"  [{qid:18s}] {qtext}")

if __name__ == "__main__":
    main()
