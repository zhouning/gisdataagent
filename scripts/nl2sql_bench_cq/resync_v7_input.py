"""v7 — Re-sync golden_sql + question fields in business_lang.json from
the source benchmark, which has been updated with v7 fixes.

The rewrite step ran before the golden_sql fixes were applied, so the
business_lang.json file still carries the v6 golden_sql for the 6 fixed
rows. This script re-syncs the source→business_lang for ALL fields
EXCEPT `question_business`, `rewrite_notes`, `rewrite_verification_ok`,
and `rewrite_verification_issues`.

It also preserves `question_original`. The `question` field in
business_lang gets re-aligned with the source (which now has the v7
question text for the 4 fixed rows).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "benchmarks" / "chongqing_geo_nl2sql_100_benchmark.json"
V7 = ROOT / "benchmarks" / "chongqing_geo_nl2sql_125q_business_lang.json"

REWRITE_FIELDS = {"question_business", "rewrite_notes",
                  "rewrite_verification_ok", "rewrite_verification_issues",
                  "question_original"}

src_rows = json.loads(SRC.read_text(encoding="utf-8"))
v7_rows = json.loads(V7.read_text(encoding="utf-8"))
v7_by = {r["id"]: r for r in v7_rows}

changed = []
out = []
for sr in src_rows:
    nr = dict(sr)  # all source fields (incl. updated golden_sql / question)
    v7r = v7_by.get(sr["id"])
    if v7r:
        # Restore rewrite-side fields
        for k in REWRITE_FIELDS:
            if k in v7r:
                nr[k] = v7r[k]
        old_g = v7r.get("golden_sql")
        new_g = sr.get("golden_sql")
        if old_g != new_g:
            changed.append((sr["id"], "golden_sql"))
        old_q = v7r.get("question")
        new_q = sr.get("question")
        if old_q != new_q:
            changed.append((sr["id"], "question"))
    out.append(nr)

V7.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[sync] {len(out)} rows written to {V7.name}")
print(f"[sync] {len(changed)} field updates:")
for cid, field in changed:
    print(f"  {cid}: {field}")
