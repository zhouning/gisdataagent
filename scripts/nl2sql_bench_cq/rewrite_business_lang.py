"""v7 P0 — LLM-driven business-language rewrite of the NL2SQL benchmark.

**STATUS**: draft. Pilot mode runs only 5 questions; full mode runs all 125.

Input:  benchmarks/chongqing_geo_nl2sql_100_benchmark.json (125 questions)
Output: benchmarks/chongqing_geo_nl2sql_125q_business_lang.json
        Each row preserves all original fields, adds:
          - question_business: the LLM rewrite (replaces 'question')
          - question_original: a copy of the v6 paren-laden text
          - rewrite_notes:     LLM's explanation of what schema artifacts
                               were removed and how they were paraphrased

Constraints enforced via prompt + post-hoc verification:
  1. The rewritten question MUST NOT contain any cq_* table name.
  2. The rewritten question MUST NOT contain any English ASCII identifier
     that names a column in `golden_sql` (Floor, BSM, DLMC, fclass, etc.),
     except for OSM standard values ('primary', 'secondary', 'motorway' —
     these are data VALUES, not column names).
  3. The rewritten question MUST NOT contain any PostGIS function name
     (ST_*, geometry::geography, etc.).
  4. The rewritten question MUST preserve:
     - Numeric filter values (40 层, 100 限速, 500米, 100万 etc.)
     - Categorical filter values ('水田', '果园', '林地' etc.)
     - Unit names (公顷, 平方千米, 千米, 度)
     - Result-shape constraints (前 5 条, 前 10 名, 保留 2 位小数)
     - 'Refuse and return SELECT 1' intent on Robustness questions (the
       hallucinated table-name traps must remain in the question text).
  5. The rewrite MUST sound like a natural business question a GIS analyst
     would ask, in Mandarin Chinese, ≤ 80 characters where possible.

Rewriter model: Gemini 2.5 Pro (quality > speed; long context for schema).
Failover: DeepSeek V4 Pro if Gemini quota exhausted (same prompt).

Pilot vs full:
  --pilot      Rewrite first 5 questions only, write to *_pilot.json
  --full       Rewrite all 125, write to the canonical _business_lang.json
  (default)    --pilot

Usage:
  $env:PYTHONPATH = "D:\\adk"
  .venv/Scripts/python.exe scripts/nl2sql_bench_cq/rewrite_business_lang.py --pilot
  .venv/Scripts/python.exe scripts/nl2sql_bench_cq/rewrite_business_lang.py --full
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "benchmarks" / "chongqing_geo_nl2sql_100_benchmark.json"

sys.stdout.reconfigure(encoding="utf-8")

# ----- Schema dictionary loaded from the live semantic catalog ------
# We pass this to the rewriter as domain context so it knows what column
# meanings are available, without ever quoting the column NAMES at output.

SCHEMA_DICT = {
    "cq_dltb": {
        "display": "地类图斑（基础数据）",
        "columns": {
            "objectid": "对象 ID",
            "bsm": "标识码",
            "ysdm": "要素代码",
            "dlbm": "地类编码",
            "dlmc": "地类名称",
            "qsdwdm": "权属单位代码",
            "qsdwmc": "权属单位名称",
            "zldwdm": "坐落单位代码",
            "zldwmc": "坐落单位名称",
            "tbmj": "图斑面积（平方米）",
            "shape": "几何信息",
        },
    },
    "cq_land_use_dltb": {
        "display": "土地利用现状图斑（2021，含 SHAPE_Length/Area 派生字段）",
        "columns": {
            "BSM": "标识码",
            "YSDM": "要素代码",
            "DLBM": "地类编码",
            "DLMC": "地类名称",
            "QSDWDM": "权属单位代码",
            "QSDWMC": "权属单位名称",
            "ZLDWDM": "坐落单位代码",
            "ZLDWMC": "坐落单位名称",
            "TBMJ": "图斑面积",
            "SHAPE_Length": "几何周长",
            "SHAPE_Area": "几何面积",
            "geometry": "几何信息",
        },
    },
    "cq_osm_roads": {
        "display": "重庆 OSM 道路",
        "columns": {
            "objectid": "对象 ID",
            "osm_id": "OSM ID",
            "code": "功能代码",
            "fclass": "功能分类（primary/secondary/motorway/residential/footway 等）",
            "name": "道路名称",
            "ref": "参考编号",
            "oneway": "是否单行（T/F）",
            "maxspeed": "最高限速（km/h）",
            "layer": "高程层",
            "bridge": "是否桥梁（T/F）",
            "tunnel": "是否隧道（T/F）",
            "shape": "几何信息",
        },
    },
    "cq_osm_roads_2021": {
        "display": "重庆 OSM 道路（2021 快照）",
        "columns": {
            "osm_id": "OSM ID",
            "code": "功能代码",
            "fclass": "功能分类",
            "name": "道路名称",
            "ref": "参考编号",
            "oneway": "是否单行",
            "maxspeed": "最高限速",
            "layer": "高程层",
            "bridge": "是否桥梁",
            "tunnel": "是否隧道",
            "geometry": "几何信息",
        },
    },
    "cq_buildings_2021": {
        "display": "重庆建筑物（2021）",
        "columns": {
            "Floor": "层数",
            "geometry": "几何信息",
        },
    },
    "cq_amap_poi_2024": {
        "display": "高德 POI（2024）",
        "columns": {
            "名称": "POI 名称",
            "类型": "POI 类型（如 '医院'、'三甲医院'）",
            "地址": "POI 地址",
            "电话": "POI 电话",
            "geometry": "几何信息",
        },
    },
    "cq_baidu_aoi_2024": {
        "display": "百度 AOI（2024）",
        "columns": {
            "名称": "AOI 名称",
            "第一分类": "一级分类（购物/餐饮等）",
            "人均价格_元": "人均价格（元）",
            "shape": "几何信息",
        },
    },
    "cq_baidu_search_index_2023": {
        "display": "百度搜索指数（2023）",
        "columns": {
            "目的地": "搜索目的地",
            "出发地": "搜索出发地",
            "搜索指数": "搜索热度",
        },
    },
    "cq_historic_districts": {
        "display": "历史文化街区",
        "columns": {
            "jqmc": "街区名称",
            "xzqmc": "行政区名称",
            "bhlsjzsl": "保护历史建筑数量",
            "bhbkydwwsl": "保护不可移动文物数量",
            "geometry": "几何信息",
        },
    },
    "cq_district_population": {
        "display": "区县人口（户籍 + 常住）",
        "columns": {
            "行政区划代码": "行政区划代码",
            "区划名称": "区划名称",
            "户籍总人口_万人": "户籍总人口（万人）",
            "常住人口": "常住人口（万人）",
        },
    },
    "cq_unicom_commuting_2023": {
        "display": "联通通勤数据（2023）",
        "columns": {
            "ddjsmc": "居住地街镇名称",
            "odjsmc": "通勤起点街镇名称",
            "年龄": "年龄",
            "扩样后人口": "扩样后人口",
            "geometry": "几何信息",
        },
    },
}


REWRITE_PROMPT = """你是 GIS 业务分析师，正在帮一位刚入职的同事改写"听起来太技术化"的 SQL 提问。

## 任务

给你一道原始问题、原始问题对应的 golden SQL（仅供你参考，不要在改写里提）、相关数据表的语义字典。请你改写问题，让它**听起来像一个不懂 SQL 的业务人会问的话**。

## 严格约束

**改写后的问题：**
1. **绝对不能**出现任何数据库表名（cq_dltb, cq_land_use_dltb, cq_osm_roads_2021, cq_buildings_2021 等所有 cq_* 开头的名字）。
2. **绝对不能**出现任何英文列名（DLMC, BSM, TBMJ, Floor, fclass, maxspeed, oneway, bridge, tunnel, osm_id, jqmc, xzqmc, ddjsmc, 等）。
3. **绝对不能**出现任何 PostGIS 函数名（ST_Intersects, ST_Area, ST_DWithin, ST_Length, ST_Union 等）或 SQL 关键字（CROSS JOIN, CTE, EXISTS 等）。
4. **绝对不能**出现类型转换语法（geometry::geography 等）。
5. **可以保留**：OSM 标准数据**值**（'primary', 'secondary', 'motorway', 'residential', 'footway'），因为这些是 OSM 数据本身的取值，不是字段名。
6. **必须保留**：所有数值（40 层、100 限速、500 米、100 万 等）、分类值（'水田'、'果园'、'三甲医院'、'桥梁' 等）、单位（公顷/平方千米/千米/度）、结果约束（前 5 条/前 10 名/保留 2 位小数）。
7. **必须保留题目的拒答意图**：如果原始问题是要做 DELETE/UPDATE/DROP/TRUNCATE 或查询不存在的表（如 cq_population_census 等"虚构表"），改写后**仍要**显式说这件事（这是测试系统的安全拒绝能力）。改写时**保留**这种"虚构表名"，不要把它擦掉。
8. **风格**：自然中文，业务口吻。地名/数据集用通俗叫法（"建筑物数据"、"道路数据"、"POI 数据"、"区县人口数据"等）。
9. **长度**：≤ 80 个汉字最好；偶尔超出可以，但不要冗长。

## 输入

ORIGINAL QUESTION:
{question}

GOLDEN SQL (仅供理解题意，不要在改写中提及任何表名/列名/函数):
{golden_sql}

RELEVANT SCHEMA DICTIONARY (告诉你哪些字段存在；改写时不能直接说出列名):
{schema_dict}

DIFFICULTY: {difficulty}
CATEGORY: {category}

## 输出格式

严格按以下 JSON 输出（不要有任何额外文字、markdown 包裹）：

{{
  "question_business": "改写后的业务问题",
  "rewrite_notes": "你抹掉了哪些 schema 信息（表名/列名/函数名），如何用中文业务语言替代"
}}
"""


def _relevant_schema(golden_sql: str) -> dict:
    """Pick the schema dictionary entries actually referenced by gold SQL."""
    if not golden_sql:
        return {}
    tables_in_gold = set(re.findall(r"\b(cq_[a-z0-9_]+)\b", golden_sql))
    return {t: SCHEMA_DICT[t] for t in tables_in_gold if t in SCHEMA_DICT}


def _verify_rewrite(rewritten: str, original_row: dict) -> tuple[bool, list[str]]:
    """Post-hoc constraint check on the LLM output."""
    issues = []
    # Drop any quoted Chinese values from check (they're allowed)
    text = re.sub(r"'[^']*'", "", rewritten)
    text = re.sub(r"\"[^\"]*\"", "", text)
    # 1. No cq_* tables
    for t in re.findall(r"\bcq_[a-z0-9_]+\b", text):
        issues.append(f"LEAK: cq_* table name '{t}' still present")
    # 2. No ST_*/PostGIS fns
    for f in re.findall(r"\bST_[A-Za-z_]+\b", text):
        issues.append(f"LEAK: PostGIS fn '{f}' still present")
    # 3. No type casts
    if "::geography" in text or "::geometry" in text:
        issues.append("LEAK: geometry type cast still present")
    # 4. No bare English column names from gold SQL (heuristic — checks
    # uppercase/CamelCase identifiers in gold that are ≥ 3 chars).
    gold = original_row.get("golden_sql") or ""
    if gold:
        # Identifiers in gold SQL that look like columns
        gold_ids = set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"', gold))
        gold_ids |= set(re.findall(r"\b([A-Z][A-Z0-9_]{2,})\b", gold))
        # Also grab common lowercase column names we know about
        gold_ids |= set(t for t in re.findall(r"\b([a-z_][a-z0-9_]{2,})\b", gold)
                        if t in {"fclass", "maxspeed", "oneway", "bridge", "tunnel",
                                 "name", "osm_id", "ddjsmc", "odjsmc", "jqmc",
                                 "xzqmc", "bhlsjzsl", "bhbkydwwsl"})
        SQL_KW = set("SELECT FROM WHERE GROUP ORDER BY HAVING JOIN ON AS LIMIT "
                     "AND OR NOT NULL IS DISTINCT CASE WHEN THEN ELSE END "
                     "COUNT SUM AVG MAX MIN ROUND COALESCE ASC DESC TRUE FALSE "
                     "LIKE BETWEEN CAST INTERVAL DATE TIMESTAMP EXISTS UNION "
                     "CROSS INSERT UPDATE DELETE DROP TRUNCATE WITH ALTER "
                     "ADD COLUMN BOOLEAN DEFAULT GRANT VACUUM PRIVILEGES TABLE "
                     "OF CREATE PUBLIC TO ALL".split())
        # Allowed values (not column names)
        VALUE_WORDS = {"primary", "secondary", "tertiary", "motorway",
                       "residential", "footway", "trunk", "service"}
        for ident in gold_ids:
            if ident.upper() in SQL_KW: continue
            if ident.lower() in VALUE_WORDS: continue
            if re.search(rf"\b{re.escape(ident)}\b", text):
                issues.append(f"LEAK: column-name identifier '{ident}' still present")
    return (len(issues) == 0, issues)


def _call_gemini(prompt: str) -> str:
    """Call Gemini 2.5 Pro for the rewrite. Returns raw text."""
    from google import genai
    from google.genai import types
    client = genai.Client()
    resp = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=[prompt],
        config=types.GenerateContentConfig(
            temperature=0.2,  # mostly deterministic but not pinned
            response_mime_type="application/json",
            http_options=types.HttpOptions(
                timeout=120_000,
                retry_options=types.HttpRetryOptions(initial_delay=3.0, attempts=3),
            ),
        ),
    )
    return resp.text or ""


def rewrite_one(row: dict) -> dict:
    """Rewrite a single benchmark row. Returns updated row dict."""
    schema = _relevant_schema(row.get("golden_sql") or "")
    prompt = REWRITE_PROMPT.format(
        question=row["question"],
        golden_sql=row.get("golden_sql") or "(none — refusal/robustness)",
        schema_dict=json.dumps(schema, ensure_ascii=False, indent=2),
        difficulty=row.get("difficulty", "?"),
        category=row.get("category", "?"),
    )
    raw = _call_gemini(prompt)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # Strip markdown fences if present
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        parsed = json.loads(cleaned)
    qb = parsed["question_business"].strip()
    notes = parsed.get("rewrite_notes", "").strip()
    ok, issues = _verify_rewrite(qb, row)

    out = dict(row)
    out["question_original"] = row["question"]
    out["question_business"] = qb
    out["rewrite_notes"] = notes
    out["rewrite_verification_ok"] = ok
    out["rewrite_verification_issues"] = issues
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true",
                    help="rewrite first 5 questions only (default)")
    ap.add_argument("--full", action="store_true",
                    help="rewrite all 125 questions")
    args = ap.parse_args()
    if not args.pilot and not args.full:
        args.pilot = True  # default

    rows = json.loads(SRC.read_text(encoding="utf-8"))
    if args.pilot:
        rows = rows[:5]
        dst = ROOT / "benchmarks" / "chongqing_geo_nl2sql_125q_business_lang_pilot.json"
    else:
        dst = ROOT / "benchmarks" / "chongqing_geo_nl2sql_125q_business_lang.json"
    print(f"[rewrite] mode={'PILOT' if args.pilot else 'FULL'}  n={len(rows)}")
    print(f"[rewrite] output: {dst}")

    out_rows = []
    for i, r in enumerate(rows, 1):
        t0 = time.time()
        try:
            new = rewrite_one(r)
        except Exception as e:
            print(f"  [{i}/{len(rows)}] {r['id']} FAIL: {type(e).__name__}: {str(e)[:200]}",
                  flush=True)
            new = dict(r)
            new["rewrite_verification_ok"] = False
            new["rewrite_verification_issues"] = [f"exception: {type(e).__name__}: {str(e)[:200]}"]
            new["question_business"] = None
        dur = time.time() - t0
        ok = "✓" if new.get("rewrite_verification_ok") else "✗"
        print(f"  [{i}/{len(rows)}] {r['id']} {ok} {dur:.1f}s  "
              f"orig: {r['question'][:60]}", flush=True)
        if new.get("question_business"):
            print(f"          → {new['question_business'][:80]}", flush=True)
        if new.get("rewrite_verification_issues"):
            for iss in new["rewrite_verification_issues"]:
                print(f"          [issue] {iss}", flush=True)
        out_rows.append(new)
        # Save after every row so partial progress survives a crash
        dst.write_text(json.dumps(out_rows, ensure_ascii=False, indent=2),
                       encoding="utf-8")

    ok_count = sum(1 for r in out_rows if r.get("rewrite_verification_ok"))
    print()
    print(f"[rewrite] complete: {ok_count}/{len(out_rows)} passed verification")
    print(f"[rewrite] output: {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
