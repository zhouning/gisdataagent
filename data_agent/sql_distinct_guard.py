"""SQL post-processor: detect JOIN row multiplication risks.

Strategy: parse pred_sql with sqlglot, look for the pattern:
  SELECT parent.X, ..., child_aggregate(...)
  FROM parent JOIN child ON spatial_predicate
  [GROUP BY parent.X]

without DISTINCT inside the aggregate. When found, return a hint.

Returns: list of (severity, message) tuples. Empty list means SQL is fine.

This is a STATIC analyzer — no DB call. Used as a retry trigger:
when the analyzer fires, _retry_with_llm is called with the hint as feedback.
"""
from __future__ import annotations

import re
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

# Spatial predicates that commonly produce one-to-many joins
SPATIAL_PREDICATES = ("ST_Intersects", "ST_Contains", "ST_Within", "ST_Crosses",
                      "ST_Touches", "ST_Overlaps", "ST_DWithin")

# Aggregations that need DISTINCT to handle row multiplication
AGGREGATE_FNS = ("COUNT", "SUM", "AVG", "MAX", "MIN")


def detect_join_multiplication(sql: str) -> list[tuple[str, str]]:
    """Return list of (severity, message) findings.

    Severity: "high" (very likely buggy), "medium" (worth checking), "low" (just info).
    """
    if not sql:
        return []
    try:
        import sqlglot
        from sqlglot import exp
    except ImportError:
        logger.warning("sqlglot not available; column guard disabled")
        return []

    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except Exception as e:
        logger.warning(f"[distinct_guard] sqlglot parse failed: {e}")
        return []

    findings: list[tuple[str, str]] = []
    if tree is None:
        return findings

    # Walk for SELECT with JOIN
    for select in tree.find_all(exp.Select):
        joins = list(select.find_all(exp.Join))
        if not joins:
            continue

        # Check if any JOIN uses a spatial predicate
        has_spatial_join = False
        for join in joins:
            on_clause = join.args.get("on")
            if on_clause:
                on_sql = on_clause.sql().upper()
                if any(p.upper() in on_sql for p in SPATIAL_PREDICATES):
                    has_spatial_join = True
                    break
        # Also flag CROSS JOIN LATERAL with spatial ordering
        for join in joins:
            if join.args.get("kind") == "CROSS" and join.args.get("side") == "LATERAL":
                has_spatial_join = True
                break

        if not has_spatial_join:
            continue

        # Check if any aggregate in SELECT lacks DISTINCT
        agg_no_distinct = []
        for func in select.find_all(exp.Func):
            fn_name = (func.sql_name() or "").upper()
            if fn_name in AGGREGATE_FNS:
                # DISTINCT inside aggregate appears as a Distinct child of the
                # function's argument expression. Walk all descendant nodes.
                has_distinct = False
                for node in func.walk():
                    if isinstance(node, exp.Distinct):
                        has_distinct = True
                        break
                if not has_distinct:
                    agg_no_distinct.append(fn_name + "(" + func.sql()[:50] + "...)")

        if agg_no_distinct:
            findings.append((
                "high",
                f"Spatial JOIN with aggregate without DISTINCT may inflate counts. "
                f"Found: {agg_no_distinct[:3]}. "
                f"Consider COUNT(DISTINCT child.id) or DISTINCT ON (parent.x) to prevent row multiplication."
            ))

        # Check for "per X" / DISTINCT ON pattern: SELECT has non-aggregated parent column
        # alongside KNN/<-> ordering. The query needs DISTINCT ON to return one row per X.
        has_knn = bool(select.sql().count("<->"))
        has_limit = bool(select.args.get("limit"))
        has_distinct_on = bool(select.find(exp.Distinct) and "ON" in select.sql().upper()[:200])
        if has_knn and has_limit and not has_distinct_on and not agg_no_distinct:
            # Could be "find K nearest" — needs DISTINCT ON if "for each parent"
            findings.append((
                "medium",
                "KNN query with LIMIT but no DISTINCT ON / GROUP BY. If the question asks 'for each X, find nearest Y', "
                "use 'SELECT DISTINCT ON (X) ... ORDER BY X, X.geom <-> Y.geom' to avoid the same X appearing multiple times."
            ))

    return findings


def format_retry_hint(findings: list[tuple[str, str]]) -> str:
    """Format findings into a retry-prompt hint."""
    if not findings:
        return ""
    lines = ["SQL post-processor flagged potential row-multiplication issues:"]
    for sev, msg in findings:
        lines.append(f"  [{sev.upper()}] {msg}")
    return "\n".join(lines)
