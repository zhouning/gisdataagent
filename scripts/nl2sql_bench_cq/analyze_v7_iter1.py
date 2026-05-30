"""v7 P0-d iter1 error analysis — categorize failure buckets.

For each failure mode (catalog/dialect/safety/unknown), enumerate every
failing qid with (a) the question, (b) the predicted SQL, (c) the gold
SQL, (d) the failure reason, and (e) an inferred remediation hint.

Output:
  - docs/v7_iter1_error_analysis.md   (human-readable report)
  - data_agent/nl2sql_eval_results/v7_iter1_2026-05-12_164032/
        catalog_actions.jsonl          (structured action items for catalog fix)
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
IT1 = ROOT / "data_agent" / "nl2sql_eval_results" / "v7_iter1_2026-05-12_164032"
BIZREV = json.loads((ROOT / "benchmarks" / "chongqing_geo_nl2sql_125q_business_lang.json").read_text(encoding="utf-8"))
BIZREV_BY = {r["id"]: r for r in BIZREV}


def load_records(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_bins(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def categorize_catalog_error(rec: dict) -> str:
    """Sub-classify catalog failures for targeted remediation."""
    pe = (rec.get("pred_error") or "").lower()
    reason = (rec.get("reason") or "").lower()
    pred = (rec.get("pred_sql") or "")
    # Column name hallucination (UndefinedColumn)
    if "column" in pe and "does not exist" in pe:
        return "halluc_column"
    # Missing table relation
    if "relation" in pe and "does not exist" in pe:
        return "halluc_table"
    # Row count off by a small delta — filter boundary issue
    if "row count" in reason:
        try:
            parts = reason.split("gold=")[1].split(" pred=")
            g = int(parts[0])
            p = int(parts[1].split()[0])
            delta = abs(g - p)
            if delta <= 3:
                return "filter_offby_small"
            if g == 0 and p > 0:
                return "filter_toolarge"
            if p == 0 and g > 0:
                return "filter_empty"
            return "filter_offby_big"
        except Exception:
            return "filter_other"
    # Value mismatch on aggregate
    if "value:" in reason:
        return "value_mismatch"
    # Rowset mismatch — usually ORDER BY / column count / extra row
    if "rowset mismatch" in reason:
        return "rowset_mismatch"
    if "col count" in reason:
        return "column_count"
    return "other_catalog"


def render_error_section(title: str, recs: list[dict], limit: int | None = None) -> list[str]:
    lines = [f"## {title} ({len(recs)} errors)\n\n"]
    if not recs:
        lines.append("_none_\n\n")
        return lines
    shown = recs[:limit] if limit else recs
    for r in shown:
        bq = BIZREV_BY.get(r["qid"], {})
        qorig = bq.get("question_original", r.get("question", ""))
        qbiz = bq.get("question_business", r.get("question", ""))
        gold = r.get("gold_sql", "")
        pred = r.get("pred_sql", "")
        pe = r.get("pred_error", "")
        reason = r.get("reason", "")
        lines.append(f"### {r['qid']}  *[{r.get('difficulty','?')}/{r.get('category','?')}]*\n\n")
        lines.append(f"**Q (biz)**: {qbiz[:160]}\n\n")
        lines.append(f"**Gold**: `{gold[:240]}`\n\n")
        lines.append(f"**Pred**: `{pred[:240]}`\n\n")
        lines.append(f"**Reason**: {reason[:200]}\n\n")
        if pe:
            lines.append(f"**PG err**: {pe[:200]}\n\n")
        lines.append("---\n\n")
    if limit and len(recs) > limit:
        lines.append(f"_... {len(recs) - limit} more omitted_\n\n")
    return lines


def main() -> int:
    baseline_recs = load_records(IT1 / "records_baseline.jsonl")
    full_recs = load_records(IT1 / "records_full.jsonl")
    bl_bins = load_bins(IT1 / "failure_bins_baseline.json")
    fl_bins = load_bins(IT1 / "failure_bins_full.json")

    def recs_in_bucket(records, per_qid_bins, bucket):
        ids = {x["qid"] for x in per_qid_bins["per_qid"] if x["bucket"] == bucket and x["ex"] == 0}
        return [r for r in records if r["qid"] in ids]

    bl_catalog = recs_in_bucket(baseline_recs, bl_bins, "catalog")
    fl_catalog = recs_in_bucket(full_recs, fl_bins, "catalog")
    fl_safety = recs_in_bucket(full_recs, fl_bins, "safety")
    fl_unknown = recs_in_bucket(full_recs, fl_bins, "unknown")
    bl_safety = recs_in_bucket(baseline_recs, bl_bins, "safety")
    bl_dialect = recs_in_bucket(baseline_recs, bl_bins, "dialect")

    # Catalog subtype breakdown (full mode is the primary target for catalog work)
    fl_catalog_sub = Counter(categorize_catalog_error(r) for r in fl_catalog)
    bl_catalog_sub = Counter(categorize_catalog_error(r) for r in bl_catalog)

    # Write main report
    lines = [
        "# v7 P0-d Iteration 1 — Error Analysis\n\n",
        f"**Benchmark**: `chongqing_geo_nl2sql_125q_business_lang.json` (125 q)\n",
        f"**Model**: gemini-2.5-flash  **Date**: 2026-05-12\n\n",
        "## Summary\n\n",
        "| Mode | EX | catalog | dialect | safety | unknown | pass |\n",
        "|---|---|---|---|---|---|---|\n",
        f"| baseline | {sum(1 for r in baseline_recs if r['ex'])}/125 = {sum(1 for r in baseline_recs if r['ex'])/125:.4f} | "
        f"{bl_bins['bins']['catalog']} | {bl_bins['bins']['dialect']} | "
        f"{bl_bins['bins']['safety']} | {bl_bins['bins']['unknown']} | "
        f"{bl_bins['bins']['pass']} |\n",
        f"| full | {sum(1 for r in full_recs if r['ex'])}/125 = {sum(1 for r in full_recs if r['ex'])/125:.4f} | "
        f"{fl_bins['bins']['catalog']} | {fl_bins['bins']['dialect']} | "
        f"{fl_bins['bins']['safety']} | {fl_bins['bins']['unknown']} | "
        f"{fl_bins['bins']['pass']} |\n\n",
        f"**Δ full − baseline = +{(sum(1 for r in full_recs if r['ex']) - sum(1 for r in baseline_recs if r['ex']))/125:.4f}**\n\n",
        "## Key observations\n\n",
        "1. **baseline 44.80% vs v6 leaky baseline 52.94% = Δ-8.14** — confirms paren-hint contamination worth ~8 pts.\n",
        "2. **full 64.00% vs v6 leaky full 66.27% = Δ-2.27** — grounding layer is partially resilient to schema-hint removal.\n",
        "3. **full eliminated all 6 dialect errors** (postprocessor + retry_with_llm does PG dialect self-repair).\n",
        "4. **full cut safety errors 24→2** (ADK agent's refusal logic > plain-prompt robustness).\n",
        "5. **catalog errors unchanged 35→35** — this is the ONLY bucket the semantic catalog can realistically attack.\n\n",
        "## Catalog subtype breakdown (full mode — the iter2 target)\n\n",
        "| Subtype | baseline | full | Meaning |\n",
        "|---|---|---|---|\n",
    ]
    subtype_meaning = {
        "halluc_column": "Model referenced a column that doesn't exist (e.g. `Id`, `station_name`)",
        "halluc_table": "Model referenced a non-existent table",
        "filter_offby_small": "Row count off by 1-3 — boundary inclusive/exclusive issue",
        "filter_offby_big": "Row count off by large — predicate mistake",
        "filter_empty": "Model returned 0 rows but gold has rows — over-restrictive filter",
        "filter_toolarge": "Model returned rows but gold has 0 — should-be-empty but model hallucinated",
        "filter_other": "Row count mismatch (unparseable delta)",
        "value_mismatch": "Aggregate value off (e.g. COUNT returned 1 vs 41)",
        "rowset_mismatch": "Same row count but different rows/ordering",
        "column_count": "Returned wrong number of columns",
        "other_catalog": "Other catalog-related issue",
    }
    for k in ("halluc_column", "halluc_table", "filter_offby_small", "filter_offby_big",
              "filter_empty", "filter_toolarge", "filter_other", "value_mismatch",
              "rowset_mismatch", "column_count", "other_catalog"):
        if fl_catalog_sub.get(k, 0) or bl_catalog_sub.get(k, 0):
            lines.append(f"| `{k}` | {bl_catalog_sub.get(k,0)} | {fl_catalog_sub.get(k,0)} | {subtype_meaning[k]} |\n")
    lines.append("\n---\n\n")
    lines.extend(render_error_section("Full-mode catalog errors", fl_catalog))
    lines.extend(render_error_section("Full-mode safety errors (evaluator over-strict?)", fl_safety))
    lines.extend(render_error_section("Full-mode unknown errors", fl_unknown))
    lines.extend(render_error_section("Baseline dialect errors (for reference — all fixed in full)", bl_dialect))

    dst = ROOT / "docs" / "v7_iter1_error_analysis.md"
    dst.write_text("".join(lines), encoding="utf-8")

    # Structured catalog actions
    actions = []
    for r in fl_catalog:
        actions.append({
            "qid": r["qid"],
            "subtype": categorize_catalog_error(r),
            "question": BIZREV_BY.get(r["qid"], {}).get("question_business", r.get("question", "")),
            "gold_sql": r.get("gold_sql", ""),
            "pred_sql": r.get("pred_sql", ""),
            "reason": r.get("reason", ""),
            "pred_error": r.get("pred_error", ""),
        })
    (IT1 / "catalog_actions.jsonl").write_text(
        "\n".join(json.dumps(a, ensure_ascii=False) for a in actions), encoding="utf-8")

    print(f"[analysis] report: {dst}")
    print(f"[analysis] catalog_actions: {IT1 / 'catalog_actions.jsonl'} ({len(actions)} items)")
    print()
    print("Catalog subtype breakdown:")
    print("  full:     ", dict(fl_catalog_sub))
    print("  baseline: ", dict(bl_catalog_sub))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
