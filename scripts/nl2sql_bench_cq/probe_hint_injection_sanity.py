"""v7 P1-pre sanity probe — verify hint injection is family-agnostic.

Purpose: BEFORE running the 9-family × 12h P1 matrix, confirm that the
semantic-layer business rules (agent_semantic_hints, value_semantics,
synonyms) inject correctly into the grounding payload regardless of which
family is passed to build_nl2sql_context.

If this probe shows non-zero hints for Gemini but zero for DS/Qwen/Gemma,
we would be comparing "Gemini with semantic layer" vs "other families WITHOUT
semantic layer" — which would confound the Δ (full − baseline) within-family
gate and make P1 numbers uninterpretable.

What it does:
  - Pick 4 test questions known to trigger at least one table_hint or
    column_hint in the CQ seed data.
  - For each (question, family) pair, call build_nl2sql_context(family=...)
    and read the `_hint_injection_stats` sidecar on the returned payload.
  - Report a table: rows=questions, cols=families, cells=injected hint count.
  - Exit 0 iff every (question, family) cell has table_hints + column_hints > 0.

No LLM calls. No DB writes. No wall-clock cost to speak of.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(str(ROOT / "data_agent" / ".env"), override=True)
sys.stdout.reconfigure(encoding="utf-8")

# Questions that reference cq_* tables AND are known to need one of the
# P0-pre business rules:
#   Q1: population query → cq_district_population → 500000 全市汇总排除 hint
#   Q2: SHAPE_Area query → cq_dltb → SHAPE_Area 单位是度² 不是 m² (value_semantics)
#   Q3: poi.类型 query → cq_amap_poi_2024 → 列名用"类型"不是"类别" hint
#   Q4: baidu AOI 第一分类 → cq_baidu_aoi_2024 → 取值枚举 hint
TEST_QUESTIONS = [
    "重庆每个区县的户籍总户数是多少",
    "第三次全国国土调查里每种地类的 SHAPE_Area 总和是多少",
    "高德 POI 数据里类型为住宿的有多少条",
    "百度 AOI 数据里第一分类为美食的平均价格是多少",
]

FAMILIES = ["gemini", "deepseek", "qwen", "gemma"]


def probe_once(question: str, family: str) -> dict:
    """Call build_nl2sql_context with the specified family override and
    return the _hint_injection_stats sidecar."""
    from data_agent.nl2sql_grounding import build_nl2sql_context
    payload = build_nl2sql_context(question, family=family)
    stats = payload.get("_hint_injection_stats") or {}
    return {
        "tables": stats.get("candidate_tables", 0),
        "table_hints": stats.get("table_hints", 0),
        "column_hints": stats.get("column_hints", 0),
        "large_tables": stats.get("large_tables", 0),
        "few_shots": stats.get("few_shots", 0),
    }


def main() -> int:
    print("=" * 90)
    print("v7 P1-pre hint-injection sanity probe")
    print("=" * 90)

    # Header
    header = f"{'Question':<50}  " + "  ".join(f"{f:>10}" for f in FAMILIES)
    print(f"\n{header}")
    print("-" * len(header))

    all_ok = True
    details: list[dict] = []
    for q in TEST_QUESTIONS:
        row = q[:48] + ".." if len(q) > 48 else q
        print(f"\n{row:<50}  ", end="")
        q_detail = {"question": q, "families": {}}
        for fam in FAMILIES:
            try:
                stats = probe_once(q, fam)
            except Exception as e:
                stats = {"error": f"{type(e).__name__}: {e}"}
            q_detail["families"][fam] = stats
            if "error" in stats:
                print(f"{'ERROR':>10}  ", end="")
                all_ok = False
            else:
                th = stats["table_hints"]
                ch = stats["column_hints"]
                mark = f"{th}T+{ch}C"
                print(f"{mark:>10}  ", end="")
                if th + ch == 0:
                    all_ok = False
        details.append(q_detail)

    print("\n\n---- per-cell detail ----")
    for d in details:
        print(f"\nQ: {d['question']}")
        for fam, stats in d["families"].items():
            if "error" in stats:
                print(f"  {fam:<10}  ERROR: {stats['error']}")
            else:
                print(f"  {fam:<10}  candidates={stats['tables']:<2} "
                      f"table_hints={stats['table_hints']:<2} "
                      f"column_hints={stats['column_hints']:<2} "
                      f"large_tables={stats['large_tables']:<2} "
                      f"few_shots={stats['few_shots']}")

    print("\n" + "=" * 90)
    if all_ok:
        print("PASS — every (question, family) cell has table_hints+column_hints > 0.")
        print("Safe to proceed to Smoke-B + P1 matrix.")
    else:
        print("FAIL — some cells have zero injected hints. Root-cause the fallback")
        print("chain (trigger_keywords / family override) before starting P1.")
    print("=" * 90)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
