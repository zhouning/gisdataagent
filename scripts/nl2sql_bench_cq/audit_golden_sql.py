"""v7 P0-b — Layer 2 golden SQL compliance audit.

Runs every benchmark row's `golden_sql` against the live PostgreSQL+PostGIS
database and classifies its execution status. The audit covers the 105 rows
with non-empty golden_sql; the 20 Refusal Rate rows have golden_sql=None
by design and are tagged `n/a_refusal`.

Output: benchmarks/chongqing_geo_nl2sql_125q_golden_audit.json
        Each row gains:
          - golden_exec_status: ok | syntax_error | dialect_error
                              | empty_result | timeout | other_error
                              | n/a_refusal
          - golden_exec_rowcount: int | None
          - golden_exec_first_row: tuple | None
          - golden_exec_error: str | None
          - golden_exec_duration_ms: int
          - golden_needs_fix: bool  (auto-flagged if non-ok and non-na)

Heuristic dialect detection (string match on Postgres error text):
  - 'function round(double precision, integer) does not exist'  → dialect_error
  - 'syntax error'                                              → syntax_error
  - 'statement timeout'                                         → timeout
  - successful query but 0 rows AND non-aggregate                → empty_result

The script does NOT modify the source benchmark file. Fix decisions are
made by the human reviewer using the audit report below.

Usage:
  cd D:\\adk
  $env:PYTHONPATH = "D:\\adk"
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_cq/audit_golden_sql.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(str(ROOT / "data_agent" / ".env"), override=True)

sys.stdout.reconfigure(encoding="utf-8")

SRC = ROOT / "benchmarks" / "chongqing_geo_nl2sql_100_benchmark.json"
DST = ROOT / "benchmarks" / "chongqing_geo_nl2sql_125q_golden_audit.json"
REPORT = ROOT / "data_agent" / "nl2sql_eval_results" / "v7_golden_audit_report.md"

TIMEOUT_MS = 30_000


def _classify_error(err: str) -> str:
    e = err.lower()
    if "function round" in e and "does not exist" in e:
        return "dialect_error"
    if "operator does not exist" in e:
        return "dialect_error"
    if "syntax error" in e:
        return "syntax_error"
    if "timeout" in e or "canceling statement" in e:
        return "timeout"
    if "does not exist" in e and ("relation" in e or "column" in e):
        return "schema_error"
    return "other_error"


def _is_aggregate(sql: str) -> bool:
    """Detect if the query is aggregate-only (returning 0 rows is OK)."""
    sql_u = sql.upper()
    # Aggregate at top level
    if re.search(r"\bSELECT\s+(COUNT|SUM|AVG|MAX|MIN|STDDEV|VAR_)", sql_u):
        return True
    # Has GROUP BY
    if re.search(r"\bGROUP\s+BY\b", sql_u):
        return True
    return False


def audit_one(sql: str, engine, text) -> dict:
    if not sql or not sql.strip():
        return {
            "golden_exec_status": "n/a_refusal",
            "golden_exec_rowcount": None,
            "golden_exec_first_row": None,
            "golden_exec_error": None,
            "golden_exec_duration_ms": 0,
            "golden_needs_fix": False,
        }
    s = sql.strip().rstrip(";").strip()
    t0 = time.time()
    try:
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"SET LOCAL statement_timeout = {TIMEOUT_MS}"))
            res = conn.execute(text(s))
            rows = res.fetchall()
        dur_ms = int((time.time() - t0) * 1000)
        rowcount = len(rows)
        first = tuple(str(c)[:80] for c in rows[0]) if rows else None
        if rowcount == 0 and not _is_aggregate(s):
            return {
                "golden_exec_status": "empty_result",
                "golden_exec_rowcount": 0,
                "golden_exec_first_row": None,
                "golden_exec_error": None,
                "golden_exec_duration_ms": dur_ms,
                "golden_needs_fix": True,
            }
        return {
            "golden_exec_status": "ok",
            "golden_exec_rowcount": rowcount,
            "golden_exec_first_row": first,
            "golden_exec_error": None,
            "golden_exec_duration_ms": dur_ms,
            "golden_needs_fix": False,
        }
    except Exception as e:
        dur_ms = int((time.time() - t0) * 1000)
        err = str(e)[:500]
        return {
            "golden_exec_status": _classify_error(err),
            "golden_exec_rowcount": None,
            "golden_exec_first_row": None,
            "golden_exec_error": err,
            "golden_exec_duration_ms": dur_ms,
            "golden_needs_fix": True,
        }


def main() -> int:
    from sqlalchemy import text
    from data_agent.db_engine import get_engine

    rows = json.loads(SRC.read_text(encoding="utf-8"))
    engine = get_engine()

    audited = []
    counts: dict[str, int] = {}
    needs_fix = []

    print(f"[audit] src: {SRC}")
    print(f"[audit] rows: {len(rows)}")
    print()

    for i, r in enumerate(rows, 1):
        verdict = audit_one(r.get("golden_sql") or "", engine, text)
        merged = dict(r)
        merged.update(verdict)
        audited.append(merged)
        status = verdict["golden_exec_status"]
        counts[status] = counts.get(status, 0) + 1
        if verdict["golden_needs_fix"]:
            needs_fix.append((r["id"], status, verdict.get("golden_exec_error", "")))
        ok = "✓" if status == "ok" else ("·" if status == "n/a_refusal" else "✗")
        print(f"  [{i:>3}/{len(rows)}] {r['id']:<30} {ok} {status:<14} "
              f"rc={verdict.get('golden_exec_rowcount')} {verdict['golden_exec_duration_ms']}ms",
              flush=True)
        if verdict.get("golden_exec_error"):
            print(f"            err: {verdict['golden_exec_error'][:160]}", flush=True)

    DST.write_text(json.dumps(audited, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"[audit] output: {DST}")
    print(f"[audit] summary: {counts}")

    # Write human-readable report
    lines = [
        "# v7 P0-b — Golden SQL Audit Report",
        "",
        f"**Source benchmark**: `{SRC.name}`  (n={len(rows)})",
        f"**Audit output**:    `{DST.name}`",
        "",
        "## Status counts",
        "",
    ]
    for st in ["ok", "n/a_refusal", "empty_result", "syntax_error", "dialect_error",
               "schema_error", "timeout", "other_error"]:
        c = counts.get(st, 0)
        lines.append(f"- `{st:<15}` {c}")
    lines += [
        "",
        f"## Rows flagged `golden_needs_fix=True` ({len(needs_fix)})",
        "",
        "| ID | status | error (head) |",
        "|---|---|---|",
    ]
    for rid, st, err in needs_fix:
        err_s = (err or "")[:120].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| `{rid}` | `{st}` | {err_s} |")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[audit] report: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
