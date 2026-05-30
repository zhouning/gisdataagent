"""Hint attribution analysis for gemini-3.5-flash regression rows.

For each (sample, qid) in v7_gemini35_recheck:
  - classify into regression (b=1, f=0), retain (b=1, f=1),
    rescue (b=0, f=1), miss (b=0, f=0)
  - pull hint_injection_stats and SQL text features

Goal: tell whether grounding regressions correlate with column_hints/few_shots
density (=> drop those in conservative profile) or are independent of hint count
(=> the regression is from prompt style and needs system_instruction rewrite).
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, stdev

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "data_agent/nl2sql_eval_results/v7_gemini35_recheck_n3_2026-05-22_095253/gemini-3.5-flash"

SQL_FEATURES = [
    ("distinct", re.compile(r"\bDISTINCT\b", re.I)),
    ("join", re.compile(r"\bJOIN\b", re.I)),
    ("cast", re.compile(r"::\w+|\bCAST\s*\(", re.I)),
    ("st_transform", re.compile(r"\bST_Transform\b", re.I)),
    ("st_dwithin", re.compile(r"\bST_DWithin\b", re.I)),
    ("st_union", re.compile(r"\bST_Union\b", re.I)),
    ("subquery", re.compile(r"\bSELECT\b.*\bSELECT\b", re.I | re.S)),
    ("group_by", re.compile(r"\bGROUP\s+BY\b", re.I)),
    ("limit_model", re.compile(r"\bLIMIT\s+(?!100000\b)\d+\b", re.I)),  # exclude harness-injected LIMIT 100000
    ("where", re.compile(r"\bWHERE\b", re.I)),
    ("round", re.compile(r"\bROUND\s*\(", re.I)),
    ("sum_avg", re.compile(r"\b(SUM|AVG|MAX|MIN|COUNT)\s*\(", re.I)),
    ("order_by", re.compile(r"\bORDER\s+BY\b", re.I)),
]


def load_jsonl(p: Path) -> dict[str, dict]:
    out = {}
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            out[r["qid"]] = r
    return out


def feats(sql: str) -> set[str]:
    s = sql or ""
    return {name for name, rx in SQL_FEATURES if rx.search(s)}


def categorize(b_ex: int, f_ex: int) -> str:
    if b_ex == 1 and f_ex == 0:
        return "regression"
    if b_ex == 1 and f_ex == 1:
        return "retain"
    if b_ex == 0 and f_ex == 1:
        return "rescue"
    return "miss"


def main() -> int:
    rows: list[dict] = []
    for sample_dir in sorted(RUN.glob("sample_*")):
        b_path = sample_dir / "records_baseline.jsonl"
        f_path = sample_dir / "records_full.jsonl"
        if not (b_path.exists() and f_path.exists()):
            continue
        b = load_jsonl(b_path)
        f = load_jsonl(f_path)
        for qid in set(b) & set(f):
            br, fr = b[qid], f[qid]
            cat = categorize(br["ex"], fr["ex"])
            stats = fr.get("hint_injection_stats") or {}
            rows.append({
                "sample": sample_dir.name,
                "qid": qid,
                "category": br.get("category", ""),
                "difficulty": br.get("difficulty", ""),
                "is_robust": br.get("is_robust", False),
                "outcome": cat,
                "table_hints": stats.get("table_hints", 0),
                "column_hints": stats.get("column_hints", 0),
                "few_shots": stats.get("few_shots", 0),
                "candidate_tables": stats.get("candidate_tables", 0),
                "large_tables": stats.get("large_tables", 0),
                "b_sql": br.get("pred_sql") or "",
                "f_sql": fr.get("pred_sql") or "",
                "b_feats": feats(br.get("pred_sql") or ""),
                "f_feats": feats(fr.get("pred_sql") or ""),
                "f_reason": fr.get("reason") or "",
            })

    print(f"# Hint attribution — gemini-3.5-flash recheck N=3 (5-22→5-23)\n")
    print(f"Total rows: {len(rows)} = 125q × 3 samples = 375 expected; got {len(rows)}.\n")

    # Outcome counts
    by_outcome = Counter(r["outcome"] for r in rows)
    print("## Outcome breakdown\n")
    print("| outcome | count | %  |")
    print("|---|---|---|")
    for k in ("retain", "rescue", "regression", "miss"):
        c = by_outcome.get(k, 0)
        print(f"| {k} | {c} | {c/len(rows)*100:.1f}% |")
    print()

    # Hint stats: regression vs retain
    print("## Hint density: regression rows vs retain rows\n")
    print("If regressions cluster on rows where grounding injects more hints, ")
    print("the conservative profile should cap or drop those hint types. If means ")
    print("are similar, the regression is style-driven (prompt rewrite, not hint count).\n")
    print("| metric | regression mean ± std | retain mean ± std | gap | n_reg | n_ret |")
    print("|---|---|---|---|---|---|")
    metrics = ["table_hints", "column_hints", "few_shots", "candidate_tables", "large_tables"]
    for m in metrics:
        reg = [r[m] for r in rows if r["outcome"] == "regression"]
        ret = [r[m] for r in rows if r["outcome"] == "retain"]
        reg_m = mean(reg) if reg else 0
        reg_s = stdev(reg) if len(reg) > 1 else 0
        ret_m = mean(ret) if ret else 0
        ret_s = stdev(ret) if len(ret) > 1 else 0
        gap = reg_m - ret_m
        print(f"| {m} | {reg_m:.2f} ± {reg_s:.2f} | {ret_m:.2f} ± {ret_s:.2f} | "
              f"{gap:+.2f} | {len(reg)} | {len(ret)} |")
    print()

    # Difficulty / category distribution
    print("## Where do regressions concentrate?\n")
    print("### By difficulty\n")
    print("| difficulty | regression | retain | reg / (reg+ret) |")
    print("|---|---|---|---|")
    diffs = sorted(set(r["difficulty"] for r in rows))
    for d in diffs:
        r_d = sum(1 for r in rows if r["outcome"] == "regression" and r["difficulty"] == d)
        rt_d = sum(1 for r in rows if r["outcome"] == "retain" and r["difficulty"] == d)
        ratio = r_d / (r_d + rt_d) if (r_d + rt_d) else 0
        print(f"| {d} | {r_d} | {rt_d} | {ratio*100:.1f}% |")
    print()

    print("### By category (top 10 by regression count)\n")
    cat_reg = Counter(r["category"] for r in rows if r["outcome"] == "regression")
    cat_ret = Counter(r["category"] for r in rows if r["outcome"] == "retain")
    print("| category | regression | retain | reg / (reg+ret) |")
    print("|---|---|---|---|")
    for cat, _ in cat_reg.most_common(10):
        r_c = cat_reg[cat]
        rt_c = cat_ret.get(cat, 0)
        ratio = r_c / (r_c + rt_c) if (r_c + rt_c) else 0
        print(f"| {cat} | {r_c} | {rt_c} | {ratio*100:.1f}% |")
    print()

    # SQL feature delta on regression rows
    print("## SQL-feature drift on regression rows (full vs baseline)\n")
    print("On rows that regressed, what did the full-mode SQL pick up that baseline didn't ")
    print("(or drop)? Each cell = count of regression rows where the feature is in full-only / baseline-only.\n")
    feats_added: Counter = Counter()
    feats_dropped: Counter = Counter()
    for r in rows:
        if r["outcome"] != "regression":
            continue
        added = r["f_feats"] - r["b_feats"]
        dropped = r["b_feats"] - r["f_feats"]
        for k in added:
            feats_added[k] += 1
        for k in dropped:
            feats_dropped[k] += 1
    n_reg = by_outcome["regression"]
    print("| feature | added by full | % of regressions | dropped by full | % of regressions |")
    print("|---|---|---|---|---|")
    all_feats = sorted(set(feats_added) | set(feats_dropped))
    for k in all_feats:
        a = feats_added.get(k, 0)
        d = feats_dropped.get(k, 0)
        print(f"| {k} | {a} | {a/n_reg*100:.1f}% | {d} | {d/n_reg*100:.1f}% |")
    print()

    # Sample regression cases
    print("## Sample regression cases (5 picked across difficulty)\n")
    seen_diff = set()
    samples = []
    for r in rows:
        if r["outcome"] != "regression":
            continue
        if r["difficulty"] not in seen_diff:
            samples.append(r)
            seen_diff.add(r["difficulty"])
        if len(samples) >= 5:
            break
    # Backfill if not enough difficulty diversity
    if len(samples) < 5:
        for r in rows:
            if r["outcome"] == "regression" and r not in samples:
                samples.append(r)
                if len(samples) >= 5:
                    break
    for s in samples:
        print(f"### `{s['qid']}` ({s['difficulty']} / {s['category']}) — {s['sample']}")
        print(f"- hints: column={s['column_hints']} few_shot={s['few_shots']} table={s['table_hints']}")
        print(f"- baseline pred (correct):")
        print(f"  ```sql\n  {s['b_sql'][:300]}\n  ```")
        print(f"- full pred (regressed):")
        print(f"  ```sql\n  {s['f_sql'][:300]}\n  ```")
        print(f"- evaluator reason: `{s['f_reason']}`")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
