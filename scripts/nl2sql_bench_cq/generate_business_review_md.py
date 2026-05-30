"""v7 P0-c — Generate business-expert review markdown for the 125 rows.

Combines:
  - question_original  (v6 schema-laden text)
  - question_business  (v7 LLM rewrite, the version evaluated)
  - golden_sql         (post-fix v7 SQL)
  - golden_sql_v6_original (only for the 6 fixed rows)
  - golden_exec_status / rowcount / first_row (audit results)

Output: docs/v7_business_review_125q.md
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.stdout.reconfigure(encoding="utf-8")

RW = ROOT / "benchmarks" / "chongqing_geo_nl2sql_125q_business_lang.json"
AU = ROOT / "benchmarks" / "chongqing_geo_nl2sql_125q_golden_audit.json"
DST = ROOT / "docs" / "v7_business_review_125q.md"


def main() -> int:
    rw = json.loads(RW.read_text(encoding="utf-8"))
    au = json.loads(AU.read_text(encoding="utf-8"))
    rw_by = {r["id"]: r for r in rw}
    au_by = {r["id"]: r for r in au}

    out = []
    out.append("# v7 Benchmark Business-Expert Review (125 questions)\n")
    out.append("\n")
    out.append("**Source:** `benchmarks/chongqing_geo_nl2sql_125q_business_lang.json`\n")
    out.append("**Audit:**  `benchmarks/chongqing_geo_nl2sql_125q_golden_audit.json`\n")
    out.append("**Date:**   2026-05-12\n\n")
    out.append("## 复核重点\n\n")
    out.append("对每一题，请确认四件事：\n\n")
    out.append("1. **业务问法是否自然**（v7 改写版本是否像真实业务人会问的话）\n")
    out.append("2. **题目语义是否仍与 golden SQL 等价**（看 OLD vs NEW SQL 对比；fix 的题尤其留意）\n")
    out.append("3. **结果数量是否合理**（是否符合应该返回多少条的直觉）\n")
    out.append("4. **first row 实际样本是否符合预期**（首行返回值是不是对的）\n\n")
    out.append("如有意见，在每题下添加 `> 业务复核：xxx` 引用块即可。\n\n")
    out.append("---\n\n")

    # Group by category for easier review
    by_cat: dict[str, list] = {}
    for r in rw:
        by_cat.setdefault(r.get("category", "?"), []).append(r["id"])

    out.append("## 概览\n\n")
    out.append("| Category | n | difficulty mix |\n")
    out.append("|---|---|---|\n")
    for cat, ids in sorted(by_cat.items()):
        diff = {"Easy": 0, "Medium": 0, "Hard": 0, "Robustness": 0}
        for i in ids:
            d = rw_by[i].get("difficulty", "?")
            diff[d] = diff.get(d, 0) + 1
        diff_str = " / ".join(f"{k}={v}" for k, v in diff.items() if v)
        out.append(f"| {cat} | {len(ids)} | {diff_str} |\n")
    out.append("\n## 修订题（v6→v7 重点关注）\n\n")
    fixed_ids = [r["id"] for r in rw if "golden_sql_v6_original" in
                 (au_by[r["id"]] if r["id"] in au_by else r)
                 or "golden_sql_v7_fix_note" in (au_by.get(r["id"], {}))]
    # Actually look at the source file for fix metadata
    src = json.loads((ROOT / "benchmarks" / "chongqing_geo_nl2sql_100_benchmark.json").read_text(encoding="utf-8"))
    fix_ids = [r["id"] for r in src if "golden_sql_v7_fix_note" in r]
    out.append(f"共 {len(fix_ids)} 题：{', '.join(fix_ids)}\n\n")
    out.append("---\n\n")

    # Now per-row sections
    for r in rw:
        rid = r["id"]
        au_r = au_by.get(rid, {})
        src_r = next((x for x in src if x["id"] == rid), {})
        diff = r.get("difficulty", "?")
        cat = r.get("category", "?")
        out.append(f"## {rid}  *[{diff} / {cat}]*\n\n")

        # Question pair
        out.append(f"**Q (v6 原文)**：{r.get('question_original') or r.get('question', '')}\n\n")
        if "question_v6_original" in src_r:
            out.append(f"**Q (v7 改写——题目修订)**：{src_r['question']}\n\n")
        out.append(f"**Q (v7 业务化)**：{r.get('question_business', '')}\n\n")

        # Golden SQL
        if "golden_sql_v6_original" in src_r:
            out.append(f"**Golden SQL (v6 原)**：\n```sql\n{src_r['golden_sql_v6_original']}\n```\n")
            out.append(f"**Golden SQL (v7 修)**：\n```sql\n{r.get('golden_sql', '')}\n```\n")
            out.append(f"**修订原因**：{src_r.get('golden_sql_v7_fix_note', '')}\n\n")
        else:
            gs = r.get("golden_sql") or "(refusal — golden SQL is None by design)"
            out.append(f"**Golden SQL**：\n```sql\n{gs}\n```\n")

        # Audit
        st = au_r.get("golden_exec_status", "?")
        rc = au_r.get("golden_exec_rowcount")
        fr = au_r.get("golden_exec_first_row")
        if st == "n/a_refusal":
            out.append(f"**审计**：refusal/robustness 题，无 golden SQL（设计内）\n\n")
        else:
            out.append(f"**审计**：`{st}` rows={rc}")
            if fr:
                out.append(f"，first_row={fr}")
            out.append("\n\n")

        # Rewrite metadata
        rn = r.get("rewrite_notes", "")
        if rn:
            out.append(f"**改写说明**：{rn}\n\n")

        # Robustness target hint
        tm = r.get("target_metric")
        if tm and tm not in ("Execution Accuracy",):
            out.append(f"**评分指标**：{tm}\n\n")

        out.append("---\n\n")

    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_text("".join(out), encoding="utf-8")
    print(f"[review] wrote {DST}")
    print(f"[review] {len(rw)} rows, {len(fix_ids)} fixed rows highlighted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
