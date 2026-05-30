"""v7 P1 — Six-dimension failure forensics.

Reads all records_*.jsonl under v7_p1_main_n3_<ts> + v7_p1_gemma_n1_<ts>,
emits a structured Markdown report with six analyses:

  D1. Cross-family failure overlap heatmap
       — Which questions do ALL families fail in `full` mode?
         (Likely evaluator/question issues, not model issues.)

  D2. hint_injection_stats × pass-rate correlation
       — For questions with table_hints>0 vs =0, compute pass-rate delta
         per family and globally.

  D3. catalog × category crossing
       — Failure-bin classification × question category, identifies which
         categories still need more semantic-layer coverage.

  D4. unknown bin pred_sql audit list
       — All pred_sql values that landed in `unknown` bucket, listed
         per family for human review.

  D5. baseline-fail → full-pass delta set
       — Per family: questions that ONLY pass with grounding. These are
         the purest direct evidence of semantic-layer ROI.

  D6. pred_sql vs gold_sql micro-diff
       — Discipline-level differences (LIMIT / DISTINCT / IS NOT NULL /
         SHAPE_Area-vs-ST_Area unit usage) over the failed-then-fixed set.

Output: docs/v7_p1_failure_analysis.md
"""
from __future__ import annotations

import json
import re
import statistics as stats
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

P1_MAIN = ROOT / "data_agent" / "nl2sql_eval_results" / "v7_p1_main_n3_2026-05-13_172802"
P1_GEMMA = ROOT / "data_agent" / "nl2sql_eval_results" / "v7_p1_gemma_n1_2026-05-13_172807"
OUT = ROOT / "docs" / "v7_p1_failure_analysis.md"


# Ordered display list — matches the FAMILIES list in run_v7_smoke_b.py.
FAMILIES_ORDER = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.1-pro-preview",
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "qwen3.6-flash",
    "qwen3.6-plus",
    "gemma-4-31b-it-ollama",
]


def classify_failure(rec: dict) -> str:
    """Mirror of run_v7_iteration.classify_failure."""
    if rec.get("ex") == 1:
        return "pass"
    reason = (rec.get("reason") or "").lower()
    perr = (rec.get("pred_error") or "").lower()
    gerr = (rec.get("gold_error") or "").lower()
    pred = (rec.get("pred_sql") or "").lower()
    if rec.get("is_robust"):
        return "safety"
    if gerr and "no gold" not in gerr:
        return "golden"
    if "round(double precision, integer)" in perr:
        return "dialect"
    if "operator does not exist" in perr:
        return "dialect"
    if "function" in perr and "does not exist" in perr:
        return "dialect"
    if "column" in perr and "does not exist" in perr:
        return "catalog"
    if "relation" in perr and "does not exist" in perr:
        return "catalog"
    if not pred:
        return "unknown"
    if "row count" in reason or "rowset mismatch" in reason or "value:" in reason:
        return "catalog"
    return "unknown"


def load_family_records(family: str, mode: str) -> list[list[dict]]:
    """Return list of sample-record-lists. Each element = one sample's 125 records."""
    samples: list[list[dict]] = []
    if family == "gemma-4-31b-it-ollama":
        f = P1_GEMMA / "gemma-4-31b-it-ollama" / f"records_{mode}.jsonl"
        if f.exists():
            recs = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
            if recs:
                samples.append(recs)
        return samples
    fam_dir = P1_MAIN / family
    if not fam_dir.exists():
        return samples
    for sample_dir in sorted(fam_dir.glob("sample_*")):
        f = sample_dir / f"records_{mode}.jsonl"
        if not f.exists():
            continue
        recs = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        if recs:
            samples.append(recs)
    return samples


def aggregate_pass(samples: list[list[dict]]) -> dict[str, float]:
    """For each qid, fraction of samples that passed."""
    if not samples:
        return {}
    qid_pass: dict[str, list[int]] = defaultdict(list)
    for sample in samples:
        for r in sample:
            qid_pass[r["qid"]].append(r.get("ex", 0))
    return {qid: sum(v) / len(v) for qid, v in qid_pass.items()}


# ---------------- D1 — cross-family failure overlap ---------------------------

def d1_overlap() -> str:
    out: list[str] = ["## D1 — Cross-family failure overlap (full mode)\n"]
    out.append("Per qid, fraction of families with at-least-one-pass sample. "
               "Questions with `0/9` are universally failed → likely evaluator "
               "or question-design issues, not model capability gaps.\n")

    n_families = 0
    qid_family_pass: dict[str, set[str]] = defaultdict(set)
    qid_meta: dict[str, dict] = {}

    for fam in FAMILIES_ORDER:
        samples = load_family_records(fam, "full")
        if not samples:
            continue
        n_families += 1
        per_q = aggregate_pass(samples)
        for qid, frac in per_q.items():
            if frac > 0:
                qid_family_pass[qid].add(fam)
            if qid not in qid_meta:
                # grab one sample for category/difficulty/question
                for s in samples:
                    for r in s:
                        if r["qid"] == qid:
                            qid_meta[qid] = {
                                "cat": r.get("category", "?"),
                                "diff": r.get("difficulty", "?"),
                                "q": (r.get("question") or "")[:80],
                                "gold": (r.get("gold_sql") or "")[:80],
                            }
                            break
                    if qid in qid_meta:
                        break

    universal_fails = []
    near_universal = []
    for qid, fams in qid_family_pass.items():
        if len(fams) == 0:
            universal_fails.append(qid)
        elif len(fams) <= 2:
            near_universal.append((qid, len(fams), fams))

    # Add qids that no family even saw passing (qid in qid_meta but not qid_family_pass keys)
    for qid in qid_meta:
        if qid not in qid_family_pass:
            universal_fails.append(qid)

    out.append(f"- families analysed: **{n_families}**")
    out.append(f"- universal full-mode fails (0/{n_families}): **{len(universal_fails)}**")
    out.append(f"- near-universal fails (≤2/{n_families}): **{len(near_universal)}**\n")

    if universal_fails:
        out.append(f"### Universal fails ({len(universal_fails)} qids)\n")
        out.append("| qid | category | diff | question (truncated) |")
        out.append("|---|---|---|---|")
        for qid in sorted(universal_fails):
            m = qid_meta.get(qid, {})
            out.append(f"| `{qid}` | {m.get('cat','?')} | {m.get('diff','?')} | {m.get('q','?')} |")
        out.append("")

    if near_universal:
        out.append(f"### Near-universal fails ({len(near_universal)} qids — ≤2 families pass)\n")
        out.append("| qid | n_pass_fam | category | diff | passing families |")
        out.append("|---|---|---|---|---|")
        for qid, npass, fams in sorted(near_universal, key=lambda x: x[1]):
            m = qid_meta.get(qid, {})
            out.append(f"| `{qid}` | {npass} | {m.get('cat','?')} | {m.get('diff','?')} | "
                       f"{', '.join(sorted(fams))} |")
        out.append("")

    return "\n".join(out)


# ---------------- D2 — hint_injection_stats × pass-rate -----------------------

def d2_hint_corr() -> str:
    out: list[str] = ["## D2 — hint_injection × pass-rate correlation\n"]
    out.append("For each family, segment qids into {with-hint, without-hint} by "
               "`hint_injection_stats.table_hints + column_hints > 0` measured "
               "in the *full* mode. Compare pass-rate.\n")
    out.append("| family | n_with_hint | pass% (with) | n_no_hint | pass% (no) | Δ (pp) |")
    out.append("|---|---|---|---|---|---|")

    overall_with: list[int] = []
    overall_no: list[int] = []

    for fam in FAMILIES_ORDER:
        samples = load_family_records(fam, "full")
        if not samples:
            continue
        with_pass: list[int] = []
        no_pass: list[int] = []
        for sample in samples:
            for r in sample:
                stats = r.get("hint_injection_stats") or {}
                n_hint = (stats.get("table_hints", 0) or 0) + (stats.get("column_hints", 0) or 0)
                if n_hint > 0:
                    with_pass.append(r.get("ex", 0))
                else:
                    no_pass.append(r.get("ex", 0))
        overall_with.extend(with_pass)
        overall_no.extend(no_pass)
        wp = (sum(with_pass) / len(with_pass) * 100) if with_pass else float("nan")
        np_ = (sum(no_pass) / len(no_pass) * 100) if no_pass else float("nan")
        delta = wp - np_ if not (wp != wp or np_ != np_) else float("nan")
        out.append(f"| {fam} | {len(with_pass)} | {wp:.2f} | {len(no_pass)} | "
                   f"{np_:.2f} | {delta:+.2f} |")

    if overall_with and overall_no:
        wp = sum(overall_with) / len(overall_with) * 100
        np_ = sum(overall_no) / len(overall_no) * 100
        out.append(f"| **TOTAL** | {len(overall_with)} | **{wp:.2f}** | "
                   f"{len(overall_no)} | **{np_:.2f}** | **{wp-np_:+.2f}** |")
    out.append("")
    return "\n".join(out)


# ---------------- D3 — catalog bin × category cross-table ---------------------

def d3_catalog_x_category() -> str:
    out: list[str] = ["## D3 — catalog-bucket × category cross-table\n"]
    out.append("How many `catalog`-bucket failures (full mode) per question "
               "category, aggregated over all family×sample cells. Highlights "
               "which categories still need more semantic-layer coverage.\n")
    out.append("| category | catalog_fails | total_obs | catalog_rate (%) |")
    out.append("|---|---|---|---|")

    cat_catalog: dict[str, int] = Counter()
    cat_total: dict[str, int] = Counter()

    for fam in FAMILIES_ORDER:
        for sample in load_family_records(fam, "full"):
            for r in sample:
                cat = r.get("category", "?")
                cat_total[cat] += 1
                if classify_failure(r) == "catalog":
                    cat_catalog[cat] += 1

    for cat in sorted(cat_total, key=lambda c: -cat_catalog.get(c, 0)):
        rate = cat_catalog[cat] / cat_total[cat] * 100
        out.append(f"| {cat} | {cat_catalog[cat]} | {cat_total[cat]} | {rate:.1f} |")
    out.append("")
    return "\n".join(out)


# ---------------- D4 — unknown bin pred_sql audit -----------------------------

def d4_unknown_audit() -> str:
    out: list[str] = ["## D4 — `unknown` bin pred_sql audit\n"]
    out.append("All pred_sql samples that classified as `unknown` (full mode), "
               "deduplicated per (family, qid). Manual review needed to surface "
               "new sub-categories of failure.\n")

    # We sample at most one per (family, qid) — first encountered.
    seen: dict[tuple[str, str], dict] = {}
    for fam in FAMILIES_ORDER:
        for sample in load_family_records(fam, "full"):
            for r in sample:
                if classify_failure(r) != "unknown":
                    continue
                key = (fam, r["qid"])
                if key in seen:
                    continue
                seen[key] = {
                    "fam": fam, "qid": r["qid"],
                    "cat": r.get("category", "?"),
                    "diff": r.get("difficulty", "?"),
                    "q": (r.get("question") or "")[:60],
                    "pred": (r.get("pred_sql") or "")[:200].replace("\n", " "),
                    "reason": (r.get("reason") or "")[:80],
                }

    out.append(f"Total unique unknown-cells: **{len(seen)}**\n")

    # Group by family for readability
    by_fam: dict[str, list[dict]] = defaultdict(list)
    for v in seen.values():
        by_fam[v["fam"]].append(v)

    for fam in FAMILIES_ORDER:
        if fam not in by_fam:
            continue
        items = sorted(by_fam[fam], key=lambda x: x["qid"])
        out.append(f"\n### {fam} — {len(items)} unique unknown qids\n")
        out.append("| qid | cat | reason | pred_sql (truncated) |")
        out.append("|---|---|---|---|")
        for it in items:
            pred = it["pred"].replace("|", r"\|")
            reason = it["reason"].replace("|", r"\|")
            out.append(f"| `{it['qid']}` | {it['cat']} | {reason} | `{pred}` |")
    return "\n".join(out)


# ---------------- D5 — baseline-fail → full-pass --------------------------------

def d5_grounding_rescues() -> str:
    out: list[str] = ["## D5 — Grounding rescue set (baseline-fail → full-pass)\n"]
    out.append("Per family, count qids where the *majority* of samples (≥2/3) "
               "fail in baseline but pass in full. These are the purest direct "
               "evidence of semantic-layer ROI.\n")
    out.append("| family | rescues | regressions | net |")
    out.append("|---|---|---|---|")

    rescue_cat = Counter()  # (family, category) → count
    rescue_qids: dict[str, list[str]] = defaultdict(list)

    for fam in FAMILIES_ORDER:
        b_samples = load_family_records(fam, "baseline")
        f_samples = load_family_records(fam, "full")
        if not b_samples or not f_samples:
            continue
        b_pass = aggregate_pass(b_samples)
        f_pass = aggregate_pass(f_samples)
        rescues = 0
        regressions = 0
        # Per-qid metadata for category breakdown
        qid_cat: dict[str, str] = {}
        for s in f_samples:
            for r in s:
                qid_cat[r["qid"]] = r.get("category", "?")
        for qid in b_pass:
            bp = b_pass[qid]
            fp = f_pass.get(qid, 0)
            # Rescue: baseline-majority-fail (bp <= 0.34) AND full-majority-pass (fp >= 0.67)
            if bp <= 0.34 and fp >= 0.67:
                rescues += 1
                rescue_qids[fam].append(qid)
                rescue_cat[(fam, qid_cat.get(qid, "?"))] += 1
            elif bp >= 0.67 and fp <= 0.34:
                regressions += 1
        out.append(f"| {fam} | {rescues} | {regressions} | {rescues - regressions:+d} |")
    out.append("")

    # Category-level rescue heatmap
    out.append("### Rescue category heatmap\n")
    out.append("Cells = #rescue qids in (family, category).\n")
    cats = sorted({c for (_, c) in rescue_cat.keys()})
    header = "| family | " + " | ".join(cats) + " |"
    sep = "|---|" + "---|" * len(cats)
    out.append(header)
    out.append(sep)
    for fam in FAMILIES_ORDER:
        row = [fam]
        for c in cats:
            row.append(str(rescue_cat.get((fam, c), 0)))
        out.append("| " + " | ".join(row) + " |")
    out.append("")
    return "\n".join(out)


# ---------------- D6 — pred_sql vs gold_sql discipline diffs -------------------

DISCIPLINE_CHECKS = {
    "limit_missing": lambda p, g: ("limit" in g.lower()) and ("limit" not in p.lower()),
    "distinct_missing": lambda p, g: ("distinct" in g.lower()) and ("distinct" not in p.lower()),
    "is_not_null_missing": lambda p, g: ("is not null" in g.lower()) and ("is not null" not in p.lower()),
    "shape_area_used_when_st_area_expected": lambda p, g: (
        "shape_area" in p.lower() and "st_area" in g.lower()
    ),
    "st_area_used_when_shape_area_expected": lambda p, g: (
        "st_area" in p.lower() and "shape_area" in g.lower()
    ),
    "geography_cast_missing": lambda p, g: (
        "::geography" in g.lower() and "::geography" not in p.lower()
    ),
    "st_transform_missing": lambda p, g: (
        "st_transform" in g.lower() and "st_transform" not in p.lower()
    ),
}


def d6_discipline_diffs() -> str:
    out: list[str] = ["## D6 — Discipline-level pred vs gold diff (full mode)\n"]
    out.append("Counts of micro-discipline mismatches between pred_sql and "
               "gold_sql, restricted to records where ex=0 and pred_sql is "
               "non-empty (i.e. model produced something but mismatched gold). "
               "Pinpoints which discipline rules need reinforcement.\n")

    counts_per_fam: dict[str, Counter] = defaultdict(Counter)
    totals_per_fam: dict[str, int] = Counter()

    for fam in FAMILIES_ORDER:
        for sample in load_family_records(fam, "full"):
            for r in sample:
                if r.get("ex") == 1:
                    continue
                pred = r.get("pred_sql") or ""
                gold = r.get("gold_sql") or ""
                if not pred or not gold:
                    continue
                totals_per_fam[fam] += 1
                for name, fn in DISCIPLINE_CHECKS.items():
                    if fn(pred, gold):
                        counts_per_fam[fam][name] += 1

    checks = list(DISCIPLINE_CHECKS.keys())
    out.append("| family | failed_records | " + " | ".join(checks) + " |")
    out.append("|---|---|" + "---|" * len(checks))
    for fam in FAMILIES_ORDER:
        if fam not in totals_per_fam:
            continue
        row = [fam, str(totals_per_fam[fam])]
        for c in checks:
            row.append(str(counts_per_fam[fam].get(c, 0)))
        out.append("| " + " | ".join(row) + " |")

    # Aggregate summary
    agg = Counter()
    total = 0
    for fam, cnt in counts_per_fam.items():
        agg.update(cnt)
        total += totals_per_fam[fam]
    out.append("")
    out.append(f"### Aggregate over {total} failed records\n")
    out.append("| discipline | count | rate (%) |")
    out.append("|---|---|---|")
    for c in checks:
        out.append(f"| {c} | {agg.get(c, 0)} | "
                   f"{agg.get(c, 0)/max(1,total)*100:.1f} |")
    out.append("")
    return "\n".join(out)


# ---------------- summary ------------------------------------------------------

def header_block() -> str:
    lines = [
        "# v7 P1 — Six-Dimension Failure Forensics",
        "",
        f"Generated: {Path(__file__).name} on records under "
        f"`{P1_MAIN.relative_to(ROOT)}` + `{P1_GEMMA.relative_to(ROOT)}`",
        "",
        "Six analyses, each scoped to **full-mode** records unless noted:",
        "1. D1 — Cross-family failure overlap (find evaluator/question issues)",
        "2. D2 — hint_injection × pass-rate correlation (validate semantic layer impact)",
        "3. D3 — catalog × category cross-table (find next catalog targets)",
        "4. D4 — `unknown` bin pred_sql audit list",
        "5. D5 — baseline-fail → full-pass rescue set (semantic layer ROI direct evidence)",
        "6. D6 — pred vs gold discipline-level diff (LIMIT/DISTINCT/IS NOT NULL/etc.)",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    parts = [header_block(), d1_overlap(), d2_hint_corr(), d3_catalog_x_category(),
             d5_grounding_rescues(), d6_discipline_diffs(), d4_unknown_audit()]
    OUT.write_text("\n\n".join(parts), encoding="utf-8")
    print(f"[done] {OUT}")
    print(f"  size: {OUT.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
