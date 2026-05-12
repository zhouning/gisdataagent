"""Generate paren-leakage-cleaned benchmark for v7.

Source:  D:\\adk\\benchmarks\\chongqing_geo_nl2sql_100_benchmark.json (125 questions)
Output:  D:\\adk\\benchmarks\\chongqing_geo_nl2sql_125q_clean.json

Cleaning rule (decided 2026-05-11 with user, strict mode):
  - Strip ALL parenthetical spans, both ASCII () and fullwidth （）, including:
    * pure schema identifiers (table/column names, PostGIS function names)
    * predicates with values (DLMC = '水田')
    * type casts (geometry::geography)
    * Chinese semantic clarifications (POI名称或类型中包含'三甲'和'医院')
    * unit equations (1公顷=10000平方米)
    * enumerator markers ((1) (2))
    * business classification rules ((年龄 <= 17 为'青少年' ...))
  - Two known under-specified cases after cleaning are ACCEPTED as benchmark
    artifacts and tagged for analysis: HARD_20 (age-banding rule lost),
    EASY_19 (geography-cast hint lost). v7 paper will report these separately.

The cleaned `question` field is the only change. `golden_sql`, `id`,
`difficulty`, `category`, `reasoning_points`, `target_metric` are preserved
verbatim — they are the ground truth and don't change just because the
question's hint scaffolding was removed.

Each output row gets a new field `question_original` that preserves the
pre-cleaning text for diff/debug; loaders can ignore it.

Safety check (printed): for every row, assert that no '(' or '（' remains
in the cleaned question. Whitespace is normalised (collapse runs of spaces,
strip leading punctuation residue like trailing comma before period).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "benchmarks" / "chongqing_geo_nl2sql_100_benchmark.json"
DST = ROOT / "benchmarks" / "chongqing_geo_nl2sql_125q_clean.json"

# Tagged questions whose meaning becomes under-specified after stripping;
# v7 analysis will surface these separately.
UNDERSPECIFIED = {
    "CQ_GEO_HARD_20": "age-banding rule (17/59) was given inside paren",
    "CQ_GEO_EASY_19": "geography-cast hint (use ST_Length without transform) was given inside paren",
}

# Match a single innermost paren span — both ASCII () and fullwidth （）
# We deliberately don't match nested parens (none exist in the source after
# manual inspection); a flat one-pass strip is enough.
PAREN_RE = re.compile(r"[\(（]([^\(（\)）]*)[\)）]")


def clean_question(q: str) -> str:
    # Drop every paren span. Run repeatedly in case of (rare) sequential
    # adjacency or nested edge cases — re.sub handles all non-overlapping
    # matches in one pass, but we loop to be safe.
    prev = None
    cur = q
    while prev != cur:
        prev = cur
        cur = PAREN_RE.sub("", cur)
    # Whitespace + punctuation cleanup after deletion:
    # - collapse runs of ASCII spaces
    # - remove leftover Chinese space artifacts like "， ，" or "  ，"
    cur = re.sub(r"[ \t]+", " ", cur)
    # Remove space immediately before Chinese punctuation
    cur = re.sub(r" +([，。、；：？！])", r"\1", cur)
    # Collapse double Chinese commas/full-stops that may appear when a
    # paren sat between two clauses
    cur = re.sub(r"，\s*，", "，", cur)
    cur = re.sub(r"。\s*。", "。", cur)
    # Trim
    cur = cur.strip()
    return cur


def main() -> int:
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    print(f"[strip] source: {SRC} ({len(rows)} questions)")

    out = []
    n_changed = 0
    n_paren_residual = 0
    n_underspec = 0
    for r in rows:
        orig = r["question"]
        cleaned = clean_question(orig)
        new_row = dict(r)  # copy preserves all original fields
        new_row["question"] = cleaned
        new_row["question_original"] = orig
        if cleaned != orig:
            n_changed += 1
        # Safety: no remaining parens
        if "(" in cleaned or "（" in cleaned:
            n_paren_residual += 1
            print(f"[WARN] residual paren in {r['id']}: {cleaned}")
        # Tag under-specified
        if r["id"] in UNDERSPECIFIED:
            new_row["v7_underspecified_reason"] = UNDERSPECIFIED[r["id"]]
            n_underspec += 1
        out.append(new_row)

    DST.write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[strip] output: {DST}")
    print(f"[strip] questions changed: {n_changed}/{len(rows)}")
    print(f"[strip] under-specified tagged: {n_underspec}")
    print(f"[strip] residual paren after cleanup: {n_paren_residual}")
    if n_paren_residual:
        print("[ERROR] residual parens detected — fix cleaner")
        return 1

    # Diff sample for sanity
    print()
    print("=== sample diff (first 8 changed) ===")
    shown = 0
    for new in out:
        if new["question"] == new["question_original"]:
            continue
        print(f"[{new['id']}]")
        print(f"  before: {new['question_original']}")
        print(f"  after : {new['question']}")
        if "v7_underspecified_reason" in new:
            print(f"  TAG: {new['v7_underspecified_reason']}")
        print()
        shown += 1
        if shown >= 8:
            break

    # Difficulty + category stats unchanged
    from collections import Counter
    diff_dist = Counter(r["difficulty"] for r in out)
    print(f"[strip] difficulty distribution: {dict(diff_dist)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
