"""SQL execution + result-set comparison utilities for NL2SQL benchmark.

- Executes SQL against the project Postgres/PostGIS in a read-only transaction
  with statement timeout
- Auto-qualifies bare table names with `floodsql_bench` schema (LLMs/baseline
  may forget the schema prefix)
- Compares predicted vs gold result sets as multisets with float tolerance
"""
from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from data_agent.db_engine import get_engine  # noqa: E402

SCHEMA = "floodsql_bench"
DEFAULT_TIMEOUT_MS = 30_000

# 10 FloodSQL tables — used to auto-qualify bare names
KNOWN_TABLES = {
    "claims", "svi", "cre", "nri", "floodplain",
    "census_tracts", "zcta", "county", "schools", "hospitals",
}


@dataclass
class ExecResult:
    status: str  # "ok" | "error" | "timeout"
    rows: list[tuple] | None = None
    columns: list[str] | None = None
    error: str | None = None
    duration: float = 0.0


def _duckdb_to_postgres(sql: str) -> str:
    """Translate common DuckDB idioms (used by FloodSQL gold SQL) to PostgreSQL.

    Minimal conservative rules:
      - CAST(x AS DOUBLE)    → CAST(x AS DOUBLE PRECISION)
      - x::DOUBLE            → x::DOUBLE PRECISION
      - DOUBLE in data types → DOUBLE PRECISION (within a CAST context only)
    """
    s = re.sub(
        r"(CAST\s*\(\s*[^)]+?\s+AS\s+)DOUBLE(\s*\))",
        r"\1DOUBLE PRECISION\2",
        sql,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"::\s*DOUBLE\b(?!\s+PRECISION)", "::DOUBLE PRECISION", s, flags=re.IGNORECASE)
    return s


def _qualify_schema(sql: str, schema: str = SCHEMA) -> str:
    """Add `schema.` prefix to bare references to KNOWN_TABLES.

    Crude but effective for this benchmark: matches `FROM table`, `JOIN table`
    when `table` has no dot. Skips already-qualified names and CTE aliases.
    """
    out = sql

    def repl(m: re.Match) -> str:
        kw, ws, name = m.group(1), m.group(2), m.group(3)
        if name.lower() in KNOWN_TABLES:
            return f"{kw}{ws}{schema}.{name}"
        return m.group(0)

    pattern = re.compile(
        r"\b(FROM|JOIN)(\s+)([A-Za-z_][A-Za-z0-9_]*)\b(?!\s*\.)",
        re.IGNORECASE,
    )
    out = pattern.sub(repl, out)
    return out


def execute_sql(
    sql: str,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    qualify_schema: bool = True,
) -> ExecResult:
    """Run a SELECT/WITH against the configured DB.

    Returns ExecResult with rows/columns or error/timeout.
    """
    engine = get_engine()
    if engine is None:
        return ExecResult(status="error", error="DB engine not configured")

    s = sql.strip().rstrip(";").strip()
    if not s:
        return ExecResult(status="error", error="empty SQL")

    head = s.lower().lstrip("(")
    if not (head.startswith("select") or head.startswith("with")):
        return ExecResult(status="error", error="only SELECT/WITH allowed")

    s = _duckdb_to_postgres(s)
    if qualify_schema:
        s = _qualify_schema(s)

    t0 = time.time()
    try:
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
            result = conn.execute(text(s))
            cols = list(result.keys())
            rows = result.fetchall()
        return ExecResult(
            status="ok",
            rows=[tuple(r) for r in rows],
            columns=cols,
            duration=time.time() - t0,
        )
    except Exception as e:
        msg = str(e)
        if "statement timeout" in msg.lower() or "canceling statement" in msg.lower():
            return ExecResult(status="timeout", error=msg, duration=time.time() - t0)
        return ExecResult(status="error", error=msg, duration=time.time() - t0)


# -------------------- result-set comparison --------------------

def _normalize_cell(v: Any, float_tol: float = 1e-4) -> Any:
    """Round floats to absorb engine differences; stringify geometries."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int,)):
        return v
    if isinstance(v, float):
        # Round to 4 decimals — generous tol for spatial computations.
        return round(v, 4) if not (v != v) else None  # nan → None
    # Decimal, datetime, geometry → str()
    s = str(v)
    return s


def _normalize_rows(rows: list[tuple]) -> list[tuple]:
    return [tuple(_normalize_cell(c) for c in r) for r in rows]


def compare_result_sets(
    gold: ExecResult,
    pred: ExecResult,
    order_sensitive: bool = False,
) -> tuple[bool, str]:
    """Return (is_match, reason).

    Multiset compare unless `order_sensitive=True`. Column count must match
    but column names need not (gold may use aliases, pred may not).
    """
    if gold.status != "ok":
        return False, f"gold not ok: {gold.error}"
    if pred.status != "ok":
        return False, f"pred {pred.status}: {pred.error}"

    if gold.rows is None or pred.rows is None:
        return False, "rows None"

    g = _normalize_rows(gold.rows)
    p = _normalize_rows(pred.rows)

    if g and p and len(g[0]) != len(p[0]):
        return False, f"column count differ: gold={len(g[0])} pred={len(p[0])}"

    if len(g) != len(p):
        return False, f"row count differ: gold={len(g)} pred={len(p)}"

    if order_sensitive:
        return (g == p, "row mismatch" if g != p else "match")

    # multiset compare via sorted tuple-of-strings
    g_sorted = sorted(tuple(map(str, r)) for r in g)
    p_sorted = sorted(tuple(map(str, r)) for r in p)
    if g_sorted == p_sorted:
        return True, "match"
    return False, "rowset mismatch"


def has_order_by(sql: str) -> bool:
    """Detect ORDER BY at top level (cheap heuristic)."""
    return bool(re.search(r"\border\s+by\b", sql, re.IGNORECASE))


if __name__ == "__main__":
    # Sanity check
    r = execute_sql("SELECT COUNT(*) FROM claims")
    print(r.status, r.rows[:5] if r.rows else r.error)
