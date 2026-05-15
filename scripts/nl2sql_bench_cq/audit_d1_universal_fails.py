"""D1 universal-fail audit aggregator.

For each qid that no family passes in any sample of full-mode (0/9 families),
emit:
  - question + gold_sql
  - per-family aggregated pred_sql (deduplicated, with count)
  - failure reason distribution
  - gen_status distribution
  - column-count mismatch pattern

Output: markdown report.

Usage:
  python scripts/nl2sql_bench_cq/audit_d1_universal_fails.py \
    --main-dir data_agent/nl2sql_eval_results/v7_p1_main_n3_2026-05-13_172802 \
    --gemma-dir data_agent/nl2sql_eval_results/v7_p1_gemma_n1_2026-05-13_172807 \
    --out docs/v7_p1_d1_audit.md
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


def _norm_sql(s: str) -> str:
    """Collapse whitespace + trailing semicolons for dedup."""
    s = re.sub(r"\s+", " ", s or "").strip()
    return s.rstrip(";").strip()


def _load_family_records(family_dir: Path) -> list[dict]:
    """Load records_full.jsonl from all samples under a family directory."""
    rows: list[dict] = []
    samples = sorted(p for p in family_dir.iterdir() if p.is_dir() and p.name.startswith("sample_"))
    if not samples:
        # gemma case: records_full.jsonl directly under family dir
        candidate = family_dir / "records_full.jsonl"
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        return rows
    for sd in samples:
        fp = sd / "records_full.jsonl"
        if not fp.exists():
            continue
        for line in fp.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                row["_sample"] = sd.name
                rows.append(row)
    return rows


def _load_all(main_dir: Path, gemma_dir: Path | None) -> dict[str, list[dict]]:
    """Return {family_name: [record, ...]}."""
    out: dict[str, list[dict]] = {}
    for fam_dir in sorted(p for p in main_dir.iterdir() if p.is_dir()):
        rows = _load_family_records(fam_dir)
        if rows:
            for r in rows:
                r["_family"] = fam_dir.name
            out[fam_dir.name] = rows
    if gemma_dir and gemma_dir.exists():
        for fam_dir in sorted(p for p in gemma_dir.iterdir() if p.is_dir()):
            rows = _load_family_records(fam_dir)
            if rows:
                for r in rows:
                    r["_family"] = fam_dir.name
                out[fam_dir.name] = rows
    return out


def _find_universal_fails(by_family: dict[str, list[dict]]) -> list[str]:
    """Qids where no family has any pass in any sample."""
    qid_pass_fams: dict[str, set[str]] = defaultdict(set)
    qid_seen_fams: dict[str, set[str]] = defaultdict(set)
    for fam, rows in by_family.items():
        for r in rows:
            qid = r["qid"]
            qid_seen_fams[qid].add(fam)
            if r.get("ex") == 1:
                qid_pass_fams[qid].add(fam)
    universal: list[str] = []
    for qid, seen in qid_seen_fams.items():
        if len(seen) == len(by_family) and not qid_pass_fams.get(qid):
            universal.append(qid)
    # sort by qid lexical order grouped by difficulty
    diff_order = {"EASY": 0, "MEDIUM": 1, "HARD": 2}
    def _key(q: str) -> tuple:
        m = re.search(r"_(EASY|MEDIUM|HARD)_(\d+)", q)
        if not m:
            return (9, 0, q)
        return (diff_order.get(m.group(1), 9), int(m.group(2)), q)
    return sorted(universal, key=_key)


def _col_count(sql: str) -> int | None:
    """Best-effort top-level SELECT col count, ignoring nested parens.

    Returns None if we can't parse confidently.
    """
    if not sql:
        return None
    s = re.sub(r"\s+", " ", sql).strip()
    m = re.search(r"^\s*SELECT\s+(.+?)\s+FROM\s+", s, re.IGNORECASE)
    if not m:
        return None
    sel = m.group(1)
    depth = 0
    cols = 1
    for ch in sel:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            cols += 1
    return cols


def _reason_bucket(reason: str) -> str:
    """Collapse reason string into one of: rowset / row_count / col_count / empty / timeout / sql_error / other."""
    if not reason:
        return "empty"
    r = reason.lower()
    if r.startswith("rowset mismatch"):
        return "rowset"
    if r.startswith("row count"):
        return "row_count"
    if r.startswith("col count"):
        return "col_count"
    if r.startswith("empty"):
        return "empty"
    if "queryCanceled" in reason or "statement timeout" in r:
        return "timeout"
    if "syntaxerror" in r.replace(" ", "") or "psycopg2.errors" in r:
        return "sql_error"
    return "other"


def _parse_row_count(reason: str) -> tuple[int, int] | None:
    """Parse 'row count: gold=X pred=Y' into (X, Y)."""
    m = re.search(r"row count:\s*gold=(\d+)\s*pred=(\d+)", reason or "")
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def _norm_for_byte_match(sql: str) -> str:
    """Aggressive normalization for 'is this byte-identical to gold ignoring trivial diffs' check."""
    s = re.sub(r"\s+", " ", sql or "").strip()
    s = s.rstrip(";").strip()
    s = re.sub(r"\bpublic\.", "", s, flags=re.IGNORECASE)  # strip "public." schema
    s = re.sub(r"\s+LIMIT\s+\d+\s*$", "", s, flags=re.IGNORECASE)  # strip trailing LIMIT
    s = s.lower()
    return s


def _build_audit_section(qid: str, by_family: dict[str, list[dict]]) -> str:
    """Build one markdown section for a single qid."""
    fam_rows: dict[str, list[dict]] = {}
    question = ""
    category = ""
    difficulty = ""
    gold_sql = ""
    for fam, rows in by_family.items():
        for r in rows:
            if r["qid"] != qid:
                continue
            fam_rows.setdefault(fam, []).append(r)
            if not question:
                question = r.get("question", "")
                category = r.get("category", "")
                difficulty = r.get("difficulty", "")
                gold_sql = r.get("gold_sql", "")

    gold_cols = _col_count(gold_sql)

    lines: list[str] = []
    lines.append(f"## `{qid}` — {category} / {difficulty}")
    lines.append("")
    lines.append(f"**Question**: {question}")
    lines.append("")
    lines.append(f"**Gold SQL** (cols={gold_cols}):")
    lines.append("```sql")
    lines.append(gold_sql)
    lines.append("```")
    lines.append("")

    reason_counter: Counter = Counter()
    status_counter: Counter = Counter()
    pred_groups: Counter = Counter()
    pred_first_fam: dict[str, str] = {}
    col_count_pairs: Counter = Counter()
    reason_bucket_counter: Counter = Counter()  # collapsed: rowset / row_count / col_count / empty / timeout / other
    row_count_pairs: Counter = Counter()  # (gold_rows, pred_rows) parsed from reason text
    for fam, rows in fam_rows.items():
        for r in rows:
            reason = r.get("reason", "") or ""
            reason_counter[reason] += 1
            status_counter[r.get("gen_status", "")] += 1
            norm = _norm_sql(r.get("pred_sql", ""))
            label = norm if norm else "<EMPTY>"
            pred_groups[label] += 1
            pred_first_fam.setdefault(label, fam)
            pc = _col_count(r.get("pred_sql", ""))
            col_count_pairs[(gold_cols, pc)] += 1
            bucket = _reason_bucket(reason)
            reason_bucket_counter[bucket] += 1
            rc = _parse_row_count(reason)
            if rc is not None:
                row_count_pairs[rc] += 1

    lines.append(f"**Failure reason buckets** (total {sum(reason_bucket_counter.values())}):")
    for bucket, cnt in reason_bucket_counter.most_common():
        lines.append(f"- `{bucket}`: {cnt}")
    lines.append("")

    lines.append(f"**Raw failure reason distribution** (total {sum(reason_counter.values())} samples):")
    for reason, cnt in reason_counter.most_common(8):
        truncated_reason = reason[:120] + " ..." if len(reason) > 120 else reason
        lines.append(f"- `{truncated_reason or '<empty>'}`: {cnt}")
    lines.append("")

    lines.append("**gen_status distribution**:")
    for status, cnt in status_counter.most_common():
        lines.append(f"- `{status or '<empty>'}`: {cnt}")
    lines.append("")

    lines.append("**Col-count (gold, pred) distribution**:")
    for (gc, pc), cnt in col_count_pairs.most_common():
        lines.append(f"- gold={gc} / pred={pc}: {cnt}")
    lines.append("")

    if row_count_pairs:
        lines.append("**Row-count (gold, pred) distribution** (only when reason=row_count):")
        for (gr, pr), cnt in row_count_pairs.most_common():
            lines.append(f"- gold_rows={gr} / pred_rows={pr}: {cnt}")
        lines.append("")

    lines.append(f"**Distinct pred_sql** (top {min(10, len(pred_groups))}):")
    for pred, cnt in pred_groups.most_common(10):
        first_fam = pred_first_fam.get(pred, "?")
        truncated = pred if len(pred) <= 220 else pred[:220] + " ..."
        lines.append(f"- [{cnt}× first={first_fam}] `{truncated}`")
    lines.append("")

    # Heuristic verdict
    verdict = _verdict(
        gold_sql=gold_sql,
        gold_cols=gold_cols,
        col_count_pairs=col_count_pairs,
        pred_groups=pred_groups,
        reason_buckets=reason_bucket_counter,
        row_count_pairs=row_count_pairs,
    )
    lines.append(f"**Heuristic verdict**: {verdict}")
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def _verdict(
    *,
    gold_sql: str,
    gold_cols: int | None,
    col_count_pairs: Counter,
    pred_groups: Counter,
    reason_buckets: Counter,
    row_count_pairs: Counter,
) -> str:
    """Best-effort flag for human auditor.

    Order matters — we check from most-specific to least-specific patterns.
    """
    total = sum(col_count_pairs.values())
    if total == 0:
        return "no samples — investigate manually"

    empty_count = pred_groups.get("<EMPTY>", 0)
    rowset_count = reason_buckets.get("rowset", 0)
    row_count_fails = reason_buckets.get("row_count", 0)
    col_count_fails = reason_buckets.get("col_count", 0)
    timeout_count = reason_buckets.get("timeout", 0)
    sql_error_count = reason_buckets.get("sql_error", 0)

    # Pattern 1: gold returns 0 rows but pred consistently returns N>0 rows
    # → gold SQL is broken (filter too tight, wrong table, etc.)
    # Check this BEFORE empty-pred check, since gold-empty often co-occurs with model timeouts.
    if row_count_pairs:
        gold_zero = sum(cnt for (gr, _), cnt in row_count_pairs.items() if gr == 0)
        # use share of *non-empty* preds (where row_count was actually evaluable)
        nonzero_pred_preds = sum(cnt for (gr, pr), cnt in row_count_pairs.items() if gr == 0 and pr > 0)
        evaluable = sum(row_count_pairs.values())
        if gold_zero >= max(3, evaluable * 0.5) and nonzero_pred_preds >= max(3, evaluable * 0.5):
            return f"**LIKELY GOLD-EMPTY BUG** — gold returns 0 rows but {nonzero_pred_preds}/{evaluable} evaluable pred return >0 rows; gold SQL filter likely broken"

    # Pattern 2: rowset mismatch dominates AND most pred match gold byte-identically (modulo schema/LIMIT)
    # → evaluator row-order or floating-point sensitivity bug
    if rowset_count >= total * 0.7:
        gold_norm = _norm_for_byte_match(gold_sql)
        byte_match = 0
        for pred, cnt in pred_groups.items():
            if pred == "<EMPTY>":
                continue
            if _norm_for_byte_match(pred) == gold_norm:
                byte_match += cnt
        if byte_match >= total * 0.4:
            return f"**LIKELY EVALUATOR BUG** — {rowset_count}/{total} rowset_mismatch + {byte_match}/{total} byte-identical-to-gold (modulo schema/LIMIT) → evaluator likely row-order or float-precision sensitive"
        return f"**LIKELY EVALUATOR / GOLD STRICTNESS** — {rowset_count}/{total} rowset_mismatch but pred SQLs vary; review if gold filter is too narrow"

    # Pattern 3: col_count failures dominate AND pred is internally consistent on a different col count
    # → gold under-specifies output columns (e.g. WKT vs lon/lat split)
    if col_count_fails >= total * 0.5 and gold_cols is not None:
        # find dominant pred col count (excluding None)
        pc_counter: Counter = Counter()
        for (_, pc), cnt in col_count_pairs.items():
            if pc is not None and pc != gold_cols:
                pc_counter[pc] += cnt
        if pc_counter:
            top_pc, top_cnt = pc_counter.most_common(1)[0]
            if top_cnt >= total * 0.4:
                return f"**LIKELY GOLD UNDER-SPEC** — gold cols={gold_cols} but {top_cnt}/{total} samples agree on cols={top_pc}; gold likely needs to expand output schema"

    # Pattern 4: row_count fails dominate but neither gold==0 nor consistent
    # → gold row count off (e.g. wrong filter granularity, off-by-one limit)
    if row_count_fails >= total * 0.7:
        # check if pred row counts cluster
        pr_counter: Counter = Counter()
        for (gr, pr), cnt in row_count_pairs.items():
            if gr > 0:
                pr_counter[pr] += cnt
        if pr_counter:
            top_pr, top_cnt = pr_counter.most_common(1)[0]
            if top_cnt >= total * 0.6:
                gr_top = next(gr for (gr, pr), _ in row_count_pairs.most_common(1) if pr == top_pr)
                return f"**LIKELY GOLD ROW-COUNT OFF** — gold expects {gr_top} rows but {top_cnt}/{total} samples consistently return {top_pr} rows; gold filter/limit likely needs adjustment"
        # row_count fails dominate but pred doesn't cluster → gold filter ambiguity (e.g. fclass synonym scope)
        gold_rows = next(iter(row_count_pairs.most_common(1)))[0][0]
        return f"**LIKELY GOLD STRICTNESS (filter ambiguity)** — {row_count_fails}/{total} row_count fails (gold={gold_rows} rows) but pred row counts vary; gold filter likely too narrow (e.g. enum synonyms, NULL handling)"

    # Pattern 5: empty pred dominates → model issue (router rejected, generation failed, timeout)
    if empty_count >= total * 0.6:
        if timeout_count >= total * 0.4:
            return f"**LIKELY HARD QUERY** — {empty_count}/{total} empty pred ({timeout_count} timeouts); query likely too expensive or model gives up"
        return f"**LIKELY MODEL ISSUE** — {empty_count}/{total} empty pred (router/parser refused or no_sql)"

    # Pattern 6: sql_error from CSV path leakage → known qwen3.6-plus bug, not benchmark issue
    if sql_error_count >= total * 0.3:
        return f"**MODEL BUG (qwen-plus CSV leak)** — {sql_error_count}/{total} sql_error (model leaked file path into SQL)"

    return "MIXED — manual review needed"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--main-dir", required=True, type=Path)
    ap.add_argument("--gemma-dir", required=False, type=Path, default=None)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    by_family = _load_all(args.main_dir, args.gemma_dir)
    print(f"loaded {len(by_family)} families, total records: {sum(len(v) for v in by_family.values())}")

    universal = _find_universal_fails(by_family)
    print(f"universal-fail qids ({len(universal)}): {universal}")

    out_lines: list[str] = []
    out_lines.append("# D1 Universal-Fail Audit (v7 P1)")
    out_lines.append("")
    out_lines.append(f"Auto-generated from `audit_d1_universal_fails.py`.")
    out_lines.append(f"Source: `{args.main_dir}` + `{args.gemma_dir}`.")
    out_lines.append(f"Families: {sorted(by_family.keys())}")
    out_lines.append(f"Universal-fail qids: **{len(universal)}**")
    out_lines.append("")
    out_lines.append("Heuristic verdict legend (checked in order):")
    out_lines.append("- **LIKELY GOLD-EMPTY BUG** — gold returns 0 rows but pred returns >0 (gold filter broken)")
    out_lines.append("- **LIKELY EVALUATOR BUG** — rowset_mismatch dominates + many pred byte-identical to gold (row order / float precision)")
    out_lines.append("- **LIKELY EVALUATOR / GOLD STRICTNESS** — rowset_mismatch dominates but pred SQLs differ (gold filter narrow)")
    out_lines.append("- **LIKELY GOLD UNDER-SPEC** — col_count dominates, pred consistent on different count (gold needs more cols)")
    out_lines.append("- **LIKELY GOLD ROW-COUNT OFF** — row_count dominates, pred consistent on different count (gold limit wrong)")
    out_lines.append("- **LIKELY GOLD STRICTNESS (filter ambiguity)** — row_count dominates, pred varies (gold filter too narrow, e.g. enum synonyms)")
    out_lines.append("- **LIKELY HARD QUERY** — empty pred dominates with timeouts")
    out_lines.append("- **LIKELY MODEL ISSUE** — empty pred dominates without timeouts")
    out_lines.append("- **MODEL BUG (qwen-plus CSV leak)** — sql_error from file-path leak (Qwen-plus only)")
    out_lines.append("- **MIXED** — manual review required")
    out_lines.append("")
    out_lines.append("---")
    out_lines.append("")

    sections = []
    verdict_summary: Counter = Counter()
    for qid in universal:
        section = _build_audit_section(qid, by_family)
        sections.append(section)
        # extract verdict for summary
        for line in section.split("\n"):
            if line.startswith("**Heuristic verdict**:"):
                v = line.replace("**Heuristic verdict**:", "").strip()
                # extract the bold tag e.g. **LIKELY GOLD UNDER-SPEC**
                m = re.match(r"\*\*([^*]+)\*\*", v)
                tag = m.group(1) if m else v.split(" ")[0]
                verdict_summary[tag] += 1
                break

    out_lines.append("## Verdict summary")
    out_lines.append("")
    out_lines.append("| verdict | count |")
    out_lines.append("|---|---|")
    for v, c in verdict_summary.most_common():
        out_lines.append(f"| {v} | {c} |")
    out_lines.append("")
    out_lines.append("---")
    out_lines.append("")

    out_lines.extend(sections)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
