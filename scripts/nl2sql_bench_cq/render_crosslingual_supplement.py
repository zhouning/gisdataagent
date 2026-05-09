"""Render LaTeX longtable rows for the BIRD Chinese 50-question re-audit
(qid, db_id, difficulty, reviewer label, pre/post EX). Underscore-escaped,
suitable for direct insertion into supplementary_v5.tex.

Usage:
  PYTHONPATH=/d/adk python scripts/nl2sql_bench_cq/render_crosslingual_supplement.py \
      > /tmp/crosslingual_supplement_rows.tex
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = (
    ROOT / "data_agent" / "nl2sql_eval_results"
    / "crosslingual_reviewed_2026-05-08_155144"
    / "crosslingual_paired_report.json"
)


def main() -> int:
    d = json.loads(REPORT.read_text(encoding="utf-8"))
    aligned = d["summary"]["aligned"]
    post_by_qid = {int(r["qid"]): r for r in d["post_records"]}
    for r in aligned:
        qid = int(r["qid"])
        rec = post_by_qid.get(qid, {})
        db = rec.get("db_id", "?").replace("_", r"\_")
        diff = rec.get("difficulty", "?").replace("_", r"\_")
        status = r["review_status"].replace("_", r"\_")
        print(
            f"{qid} & {db} & {diff} & {status} "
            f"& {r['pre']} & {r['post']} \\\\"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
